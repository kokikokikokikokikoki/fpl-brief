# Implementation report — Stage 4: rival maths

**Programmer:** Opus 5.5 subagent (medium effort) · **Date:** 2026-10-05 · **Status handed off:** IN_REVIEW · Not committed.

## Changed paths

- `fpl_brief/rivals.py` (new): EO, swing, captain Monte Carlo, pairwise finish odds, title Monte Carlo, mode hint, `build`.
- `fpl_brief/league.py`: the fetch half of `threats` is now `gather(snapshot, get)`; `threats` calls it and builds the same output as before. `gather` also keeps the already-fetched raw picks (position, multiplier, captaincy), `active_chip`, the `history.current` rows, and whether the current GW is `finished`. No new endpoints.
- `dashboard.py`: `GET /api/rivals` (behind the existing gate and the loopback API host check, like `/api/league`). It calls `league.gather` through the shared `MATCHDAY_GET` cache, then `rivals.build` with `private_data` and `player_history`. Any exception returns `{"state": "unavailable", ...}`.
- `dashboard/rival-maths.ts` and `.css` (new): the "Rival maths" panel.
- `dashboard/app.ts`: imports the panel, adds lazy `loadRivalMaths` (at most once per 10 min, the same pattern as threats), and mounts it under League threats in the Rivals view.
- `tests/test_rivals.py` (new, 15 tests) and `tests/test_rival_maths.mjs` (new, 2 node tests).
- `README.md`: a Rival maths paragraph.
- `ops/TASK.md`: status line only.

## Method (as implemented)

- **xP.** Next-GW xP is `xp[0]` and 6-GW xP is `xp_6`, both from `projection.build(..., model="own", history=data/player_history.json)`. If the own model is unavailable (no history), it falls back to `model="fpl"` with a caveat.
- **Multipliers and EO.**
  - `multipliers(picks, chip, captain)`: 0 for a benched player (positions 12–15) unless the chip is `bboost`, 1 for a starter, 2 for the captain, 3 under `3xc`.
  - Rivals: their latest public picks (GW5), with no chip assumed for next GW.
  - **Assumed captain:** a rival's last captain if he still starts and has xP > 0, otherwise their highest next-GW-xP starter. Each case is labelled ("last captain" / "highest next-GW xP starter").
  - A rival who played Free Hit last GW gets a caveat.
  - `EO_p = (1/R) Σ_r mult_{r,p}` over the top 10 rivals.
  - **Your lineup:** the captured account lineup when `private.usable`, plus a pending BB or TC from the account chips. Otherwise the public `squad_snapshot` picks. The source is shown in the UI.
- **Swing.** `Σ_p (my_mult − mult_r) · xP_p` per rival, and with EO for the field. The top 5 contributions are listed each way.
- **Captain Monte Carlo.** Covers your top-5 starters by next-GW xP.
  - **Shared draws:** each involved player (yours plus every rival's owned players) gets one column of 10,000 draws from `Normal(xP, sd)`, floored at −2 and rounded, with a seeded `random.Random`. Every lineup is scored on the same columns.
  - **vs a top-3 rival:** P(gain ≥ 0) of the whole-squad difference with that captain.
  - **vs the field:** P(your captain's extra points beat the field's average extra captain points). Ties count ½. The comparison is in integers (yours × R vs the summed rival extras), so an identical captain gives exactly 50%.
  - **Expected differences:** vs the field (EO) and vs each top-3 rival.
  - **Differential flag:** the community heuristic (the favourite's EO > 0.75, the alternative's < 0.5, xP gap < 1.5). The favourite is the candidate with the highest EO. The UI labels it a heuristic.
- **sd per position.** The sd of `total_points` per appearance (minutes > 0) this season from `data/player_history.json`, by catalog position.
  - It is shrunk towards the pooled sd: `sd² = (n·s²_pos + 50·s²_pooled)/(n + 50)`.
  - Real values: GK 3.02 (n=100), DEF 3.24 (533), MID 2.95 (729), FWD 3.07 (176).
  - Each player's sd is scaled by `min(1, √(xP / position mean per appearance))`. A player at xP 0 is then exactly 0, and players unlikely to play don't get a full-width spread that the −2 floor would bias upwards.
  - The scaling is an addition to the brief (see Deviations).
  - With no history, sd is 3.0.
- **Finish and title odds: one model (revised under Supervisor ruling Q1; see that section).**
  - G is your total minus theirs (live standings); n = 38 − the last finished GW.
  - **Weekly means:** gross GW points from `history.current`, shrunk to the league mean (over every tracked manager-week) with k = 5 GWs, minus each manager's average `event_transfers_cost`.
  - **Mean uncertainty:** each manager's mean has posterior sd `σ_m/√(n_obs + 5)`. σ_m is the sd of their weekly points relative to the tracked group's average that GW, shrunk towards the pooled value with 5 pseudo-GWs.
  - **σ_week per pair:** the sample variance of the weekly net-points difference (you vs r) over shared GWs, shrunk towards the pooled variance across your pairs with 5 pseudo-GWs: `σ² = (df·s² + 5·pooled)/(df + 5)`.
  - **Season Monte Carlo** (10,000 sims, seeded). Per sim, each manager's true weekly mean is drawn once from `Normal(shrunk mean, σ_m/√(n_obs + 5))`. Each remaining week resamples one past GW index for everyone at once and adds each manager's net deviation from their own mean in that GW. On top of that, each manager gets an independent Normal top-up per week.
  - **Top-up formula:**
    - `b²_r = mean over past GWs of (dev_you − dev_r)²` is the spread the resampling already gives;
    - `need_r = max(0, σ_week,r² − b²_r)`;
    - you get `t_you² = ½·min_r need_r`, and each rival gets `t_r² = need_r − t_you²`, so `t_you² + t_r² = need_r` for every pair with you;
    - the n weekly top-ups are drawn as one `Normal(0, t·√n)`.
  - **Outputs:** P(1st) and P(finish ahead of r) are shares of sims (ties count ½), plus your expected final rank, among you and the top 10 only.
  - **Analytic cross-check** (`p_ahead_analytic`, shown as "formula check"): `Φ((G + μ)/√(n·σ_week² + n²·(v_you + v_r)))`, where μ = (your net shrunk mean − theirs) × n, v is each mean's posterior variance, and `Φ` comes from `math.erf`. If the total variance is 0, the result is a step function.
- **Mode hint.** z = (G + μ)/√(n·σ_week² + n²·(v_you + v_r)) against the top-ranked rival, which is second place if you lead. Above +0.5 is "protect" (copy the field, template captain unless it's >2 xP behind). Below −0.5 is "chase" (differentials, consider a contrarian captain). Anything else is "balanced".
- **Shield and differentials.** Shield is your owned players with EO ≥ 0.5. Differentials are your owned players with EO < 0.25. Both are sorted by next-GW xP and show the 6-GW xP and EO.
- **Labels.** The panel subtitle and the method line say every probability is an estimate from a simple model. The method says the odds ignore chips and transfer plans, and chips left are shown per rival. The assumptions are listed.

## Real-data check (live public endpoints via `matchday.cached_getter`, local snapshot/catalog/history, account capture `ready`)

> The title odds, P(finish ahead) and mode figures below are the first-round ("before") numbers. The current ones are under **Supervisor rulings**. The captain table and swings are unchanged.

Manager **kokonut**: rank 3, 381 pts, 33 GWs left; the lineup comes from the captured account (current captain Groß).

- **Title odds (estimate):**
  - P(1st): you **0.24%**; FNN. 48.3%, -Nk_KOP 41.1%, Jazzjuman 5.5%, Azey 4.9%, everyone else ≈0%.
  - Expected final rank: **4.11** of 11.
- **P(finish ahead) vs the top 10:**

  | Rival | Gap | P(finish ahead) |
  |---|---|---|
  | FNN. | −11 | 28.8% |
  | -Nk_KOP | −10 | 35.9% |
  | Jazzjuman | +8 | 63.1% |
  | Azey | +9 | 61.4% |
  | Straku | +14 | 78.1% |
  | Pz | +16 | 78.0% |
  | JAE | +17 | 78.5% |
  | Minnie the Cookie | +18 | 72.0% |
  | visarutdear | +23 | 85.4% |
  | Winchester United | +30 | 85.8% |

- **Mode vs the leader FNN.:** **chase**, z = −0.56.
  - Gap −11; expected edge −36.3 over 33 GWs (−1.1/GW after shrinkage); σ_week 14.7 (raw ≈ 6.9 over 4 df, pulled up towards the pooled 18.8).
- **Captain table, GW6.** All 10 rivals are assumed to captain Haaland (last captain), so his EO is 200%. The P(gain ≥ 0) columns are vs FNN. / -Nk_KOP / Jazzjuman.

  | Captain | xP | EO | vs field (expected) | P(beats field's captains) | Expected vs FNN. / -Nk_KOP / Jazzjuman | P(gain ≥ 0) vs FNN. / -Nk_KOP / Jazzjuman |
  |---|---|---|---|---|---|---|
  | Haaland | 5.39 | 200% | −1.88 | 50% (identical) | −4.31 / −0.63 / −0.63 | 38.3% / 49.4% / 49.4% |
  | Gibbs-White | 4.93 | 20% | −2.34 | 45.4% | −4.77 / −1.09 / −1.09 | 37.9% / 47.6% / 48.1%; **heuristic differential flag** |
  | Rogers | 4.66 | 50% | −2.61 | 42.7% | −5.04 / −1.36 / −1.36 | 37.4% / 47.1% / 47.0% |
  | Groß (current captain) | 4.63 | 60% | −2.64 | 42.5% | −5.07 / −1.39 / −1.39 | 36.7% / 46.5% / 47.0% |
  | Calafiori | 4.59 | 90% | −2.68 | 42.4% | −5.11 / −1.43 / −1.43 | 37.3% / 46.7% / 47.0% |

- **Field swing, GW6, current lineup:** −2.64.
  - For you: Groß +6.48, Gibbs-White +3.94, Hall +3.86, Cherki +3.83, De Cuyper +3.56.
  - Against you: Haaland −5.39, B.Fernandes −4.12, Szoboszlai −3.21, Raya −2.46, Mbeumo −1.74.
- **Shield:** Haaland, Rogers, Groß, Calafiori, Szoboszlai.
- **Differentials:** Gibbs-White, Hall, De Cuyper, Cherki, Suzuki, Van Hecke, João Pedro, Dubravka (bench, xP 0).
- **Runtime** (this machine, pure Python):
  - `league.gather` 0.65 s live, then cached;
  - the whole `rivals.build` 0.30 s, including the own-model projection (0.05 s), the captain Monte Carlo (about 0.13 s) and the title Monte Carlo (0.12 s).
  - Both Monte Carlos use 10,000 sims.
- **End-to-end:** `/api/rivals` was also run on a temporary local server (port 8765, since stopped) and the panel was checked in a separate browser tab. It renders under League threats.

## Tests

- `python -m unittest discover -s tests`: **291 tests OK** (30.2 s, after the rulings); 17 of them are new in `test_rivals.py`:
  - EO arithmetic: captain, TC, BB bench, benched;
  - swing sign;
  - assumed captain;
  - shared draws giving zero difference in every sim, floor/round, seeded;
  - sd shrinkage;
  - Φ known values;
  - pairwise monotonicity in the gap;
  - mean shrinkage with one GW, and hits;
  - the season Monte Carlo is seeded, sums to 1, and the totals decide when no weeks are left;
  - the top-up makes each pair's weekly spread equal max(σ_week², bootstrap);
  - **simulated and analytic P(finish ahead) agree within 5 percentage points** on a synthetic 6-manager league;
  - mean uncertainty widens the analytic spread;
  - `build` end to end, deterministic;
  - account lineup vs public;
  - unavailable pass-through;
  - endpoint with a fake getter: it reads exactly the same paths as `threats`, degrades on bad data, and needs sign-in when a password is set.
- `npm run typecheck --prefix dashboard`: OK.
- `npm run build --prefix dashboard`: OK.
- `node --test tests/*.mjs`: **14 pass**, 2 of them new: the ready render escapes everything and has the estimate labels; loading, idle, error and unavailable states.

## Limitations

- **Mean uncertainty now dominates this early.** With 5 GWs observed, the n² term (≈4 pts/GW posterior sd per manager over 33 GWs) is larger than the week-to-week noise, so every P(finish ahead) sits between 41% and 72%. That is consistent with the data, but it depends on the k = 5 prior strength.
- **Rivals' squads are their GW5 picks:** pre-deadline transfers are invisible. A Free Hit last GW is only flagged, not reverted.
- **Rival chips:** none assumed for next GW. Chips left are shown as context only.
- **The tracked group is you plus the top 10:** title odds ignore managers further down.
- **The Normal points model has no fat tails or team correlation.** A captain's haul and correlated clean sheets are under-represented.
- **Small league:** the EO is lumpy (one owner = 10%).
- **No result cache on the server.** It is cheap at 0.3 s, and the client loads at most every 10 min. Threats and rival maths load in parallel on first open, so both may fetch the same endpoints once before the cache fills.

## Deviations

1. **sd is scaled down for low-xP players:** `sd · min(1, √(xP/mean per appearance))`. Without it, a bench-warmer at xP 0.3 drawn with sd 3 and floored at −2 has a materially higher mean than his xP.
2. **"Beats the field's captaincy outcome"** is interpreted as your captain's extra points against the average of rivals' extra captain points, with ties counting ½. The rival columns use P(gain ≥ 0) of the full-squad difference, as specified.
3. **Model fallback:** if the own model has no history, the FPL model is used with a caveat, rather than failing.
4. **Your lineup:** a pending BB or TC on the account is respected.
5. **`league.py`** was refactored (`gather` extracted). The `threats` output is unchanged; the existing `test_league` tests pass.

## Supervisor rulings (2026-10-05)

**Q1: one consistent model.**
- **Implemented:** `rivals.manager_form` (mean uncertainty), `pairwise` (analytic cross-check with the mean-variance term), `top_ups` and `season_sims` (the former `title_odds`). `build` now takes P(finish ahead) from the sims and keeps `p_ahead_analytic`. The UI shows the sim figure, with "formula check" under it. The method text and README are updated.
- **Interpretation:** σ_m is the sd of a manager's weekly points relative to the tracked group's average that GW, not their raw weekly sd.
  - Raw weekly sd is about 30–35 points, because whole-league good and bad weeks dominate it. With raw sd, the posterior mean sd is about 10 pts/GW, and every pair collapses to roughly 46–60% (FNN. 46.4%).
  - The group-relative sd is about 10–15, giving a posterior sd of about 3–4.6 pts/GW.
  - Please confirm this reading.
- **Before and after, real data** (same live data; you are kokonut, 3rd, 381 points):

  | Rival | Gap | Before: Φ (analytic, no mean uncertainty) | After: sims | After: analytic |
  |---|---|---|---|---|
  | FNN. | −11 | 28.8% | **41.3%** | 41.4% |
  | -Nk_KOP | −10 | 35.9% | **42.0%** | 42.2% |
  | Jazzjuman | +8 | 63.1% | **56.6%** | 56.6% |
  | Azey | +9 | 61.4% | 56.4% | 56.5% |
  | Straku | +14 | 78.1% | 64.1% | 64.9% |
  | Pz | +16 | 78.0% | 63.5% | 64.0% |
  | JAE | +17 | 78.5% | 64.6% | 65.0% |
  | Minnie the Cookie | +18 | 72.0% | 62.7% | 63.0% |
  | visarutdear | +23 | 85.4% | 69.3% | 69.4% |
  | Winchester United | +30 | 85.8% | 71.6% | 71.6% |

  Simulated and analytic now agree within 0.9 points for every rival.
- **Title odds after:** you **11.7%** (before 0.24%). FNN. 26.8%, -Nk_KOP 19.4%, Azey 10.6%, Jazzjuman 9.1%, Minnie the Cookie 5.9%, Pz 4.2%, Straku 3.3%, JAE 3.2%, Winchester United 3.2%, visarutdear 2.6%. Expected final rank: **5.08** (before 4.11).
- **Mode vs FNN.:** z = −0.22, "balanced" (before −0.56, "chase").
- **Top-up sds** (pts/GW) for you, then the rivals in rank order: 0, 13.4, 2.6, 9.8, 0, 11.7, 12.7, 12.0, 0, 11.8, 1.3. A zero means the bootstrap already exceeds σ_week for that pair.
- **Runtime:** `build` takes 0.37 s; the season sims take 0.18 s.
- **Captain table:** unchanged.

**Q2: kept captain-only "vs field".** The method text now says the rest of your squad doesn't change with the captain.

**Q3: accepted.** It is noted in Limitations: on first open, threats and rival maths may fetch the same endpoints once in parallel.

## Open questions for the Supervisor

1. Confirm that σ_m means a manager's group-relative weekly sd (see Supervisor rulings Q1). The raw sd would make all the odds close to a coin flip.
2. The mean-uncertainty term dominates with 5 GWs observed. Is k = 5 the right prior strength for manager means, or should it be larger (true skill differences between managers are probably smaller than k = 5 implies)?
