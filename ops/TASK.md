# Active task — Stage 4: rival maths (effective ownership, captaincy vs rivals, finish odds)

**Owner:** Programmer (Opus 5.5 subagent, medium effort). Review by a separate Opus 5.5 subagent (medium effort).
**Status:** READY_FOR_PROGRAMMER
**Date:** 2026-10-05
**Overseer request:** "after stage 3 do stage 4 and 5" (2026-10-05). Design source: `research/fpl-maths.md` §4. The existing League threats panel (`fpl_brief/league.py` `threats`, `/api/league`) already fetches rivals' picks, history and chips through the shared cache. Build on it rather than re-fetching.

## Objective

In the mini-league only the difference from rivals counts. Show how each choice moves that difference, and how likely the manager is to finish ahead of each rival and to win the league.

## Required implementation

1. **`fpl_brief/rivals.py` (new, stdlib, pure functions, injectable random seed).**
   - **Inputs:** the `threats` data (rivals' latest known picks, captains, chips used, history), the manager's own squad and lineup, and each player's next-GW and 6-GW xP from `projection.build(..., model="own")`.
   - **Effective ownership (EO).** For each player, `EO_p = (1/R) Σ_r mult_{r,p}`:
     - 0 if not owned or benched (unless the rival's chip is BB);
     - 1 if started, 2 if captain, 3 if triple captain.
     - **Before the deadline:** use the rivals' latest known picks. A rival's captain is assumed to be their last captain if they still own him, otherwise their highest next-GW-xP player. Label this as an assumption.
     - The manager's own multipliers come from the captured account lineup when usable, otherwise from the public snapshot.
   - **Expected swing next GW:** `Σ_p (my_mult_p − mult_{r,p}) · xP_p` per rival, and against the field (EO). List the top 5 players driving it each way.
   - **Captain table:** for each of the manager's top-5 next-GW-xP starters as captain, give:
     - the expected difference against the field and against each of the top-3 rivals;
     - from a one-GW Monte Carlo (10,000 sims, fixed seed), P(this captain beats the field's captaincy outcome) and P(gain ≥ 0) against each of the top-3 rivals.
     - **Shared draws:** each player's points are drawn once per sim and reused for everyone who owns him.
     - **Points distribution:** Normal(xP, sd) floored at −2 and rounded. Take `sd` per position from this season's per-GW points spread (`data/player_history.json`), shrunk, and document it.
     - Flag the research's community heuristic as a heuristic: a differential captain when the favourite's EO > 75%, the alternative's EO < 50% and the xP gap < 1.5.
   - **Finish odds.**
     - **Pairwise:** `P(finish ahead of r) ≈ Φ((G + μ)/(σ_week·√n))`.
       - G is the current points gap.
       - μ is the expected remaining edge: (your shrunk mean − theirs) × n. Shrink weekly means towards the league mean with k = 5 GWs.
       - σ_week is the standard deviation of the weekly points difference from both managers' `history`, shrunk towards the pooled value.
       - n is the GWs remaining: 38 − current finished GW.
       - Compute `Φ` with `math.erf`.
     - **Title odds:** Monte Carlo over the remaining season (10,000 sims, fixed seed). Each remaining week samples a past GW index for all managers at once, preserving the weekly correlation. It adds each manager's deviation from their own mean to their shrunk mean, minus their average hit cost.
     - **Output:** P(1st) for the manager and each rival, and the manager's expected final rank.
     - **Labels:** label the method as an approximation. It ignores chips left and transfer plans, so mention chips left per rival as context.
   - **Mode hint:** z = (G + μ)/(σ_week·√n) against the leader. Explain in plain words when to protect the position (z > 0.5: copy the field, template captain), when to chase (z < −0.5: differentials, a contrarian captain worth considering), and otherwise when it's balanced.
2. **Server:** add `GET /api/rivals` behind the existing gate. It reuses the League threats fetch and its cache, so no new endpoints are fetched beyond what `threats` uses. Failures degrade with a warning, the same as `/api/league`.
3. **UI:** a "Rival maths" panel in the Rivals view, loaded lazily (at most once every 10 min), in the existing visual style. It shows:
   - the mode hint;
   - the title-odds bar;
   - per rival: gap, P(finish ahead), next-GW expected swing with its drivers, and chips left;
   - the captain table with EO;
   - the manager's "shield" (high-EO players owned) and their differentials, each with xP.

   Everything is escaped. Every probability is labelled as an estimate from a simple model.
4. **Tests (`tests/test_rivals.py`):**
   - the EO arithmetic (captain, TC, BB bench, benched);
   - the swing sign: you captain a player the rival doesn't own;
   - shared-draw Monte Carlo: identical squads give a zero difference in every sim;
   - Φ against known values, and the pairwise odds' monotonicity in the gap;
   - the title Monte Carlo is deterministic with a seed and sums to 1;
   - shrinkage with little history;
   - the assumed captain before the deadline;
   - an endpoint test with a fake getter;
   - a node render test for escaping and states.

## Allowed paths

`fpl_brief/rivals.py`, `fpl_brief/league.py` (small helpers or exposure of already-fetched data only), `dashboard.py`, `dashboard/rival-maths.ts|css` (new), `dashboard/app.ts` (mount and lazy load only), `tests/test_rivals.py`, `tests/test_dashboard.py`, `tests/test_rival_maths.mjs` (new), `README.md`, `ops/IMPLEMENTATION_REPORT.md`, `ops/TASK.md` (status line only).

Do not commit, and do not run the fetcher.

## Test command

`python -m unittest discover -s tests` · `npm run typecheck --prefix dashboard` · `npm run build --prefix dashboard` · `node --test tests/*.mjs`

## Constraints

- Stdlib only.
- Read-only public endpoints already used by `threats`.
- Probabilities are labelled as estimates from simple models, never as certainties.

---

# Previous task — Stage 3 fix: free-transfer valuation and honest plan ranking

**Owner:** Programmer (Opus 5.5 subagent, the same one who built Stage 3). Re-review by a separate Opus 5.5 subagent.
**Status:** APPROVED (re-review PASS 2026-10-05; post-review polish applied, full suite 274 OK; local only)
**Date:** 2026-10-05
**Source:** Stage 3 review FAIL (`ops/REVIEW.md`). The objective adds `Σ_w 0.85^w · 1.5 · fts[w+1]` (`fpl_brief/optimise.py:163-165`), so a banked FT earns value every week it stays unused. Its value inside the horizon is already captured when it is used later, so FTs are credited twice. In the real run, plan 1 (roll, +7.09 points vs hold) outranked plan 2 (move now, +11.27), and both end with 5 FTs.

## Supervisor ruling

Replaces ruling 1. It is technical, so it's recorded here and in DECISIONS.md.

- **One-time FT value:** a free transfer is valued **once**. Only FTs carried out of the horizon (the count available after the last GW) earn `FT_VALUE` each, undecayed beyond the last GW's weight, using the diminishing list from research §3 (`{2: 2.0, 3: 1.6, 4: 1.3, 5: 1.1}` per marginal FT; the 1st FT is 0 since you always get one).
- **Minimum gain per transfer:** to stop the solver burning FTs on tiny gains inside the horizon, add a named `MIN_TRANSFER_GAIN = 0.5` decayed points per transfer, subtracted in the objective. Document it as a tunable heuristic.
- The bank value (`itb_value`) stays, applied once on the end-of-horizon bank only.

## Required implementation

1. **Objective (`fpl_brief/optimise.py`):** implement the ruling. Keep the rest of the ILP unchanged.
2. **Breakdown (blocking item 1):** each plan returns its result against holding:
   - `points_gain`: decayed XI, captain and bench points;
   - `ft_value`, `bank_value`, `transfer_penalty` and `hits`;
   - `objective_gain`, which must equal the sum of the parts within 1e-6.
3. **Plan cards (blocking items 2–3):**
   - Show "Points gain vs holding" first and prominently, then "Planner score vs holding" with the breakdown.
   - Mark the plan with the most estimated points.
   - Remove "best overall" (`dashboard/transfer-planner.ts:84`, `:338`).
   - Rewrite the method text to explain the ranking: points, minus hits and a small per-transfer threshold, plus a one-time value for free transfers and bank kept at the end.
   - The intro says "Holding scores X points over the horizon".
   - Everything stays escaped.
4. **Tests:**
   - The breakdown parts sum to `objective_gain`.
   - Two plans ending with equal FTs rank by points.
   - Holding one FT across the horizon is worth exactly the one-time value, not a per-week sum.
   - `MIN_TRANSFER_GAIN` blocks a +0.2 move.
   - The card shows both figures, escaped.
   - Update the existing tests that encoded the per-week value.
5. **Housekeeping:** the Stage 3 task below gets ruling 3 recorded. Requirement 4 now reads `requirements-planner.txt`, which is added to its allowed paths. That edit is done by the Supervisor, so the Programmer doesn't touch it.
6. **Re-run on the real squad (own model):** report the new top 3 with the breakdown.

## Allowed paths

`fpl_brief/optimise.py`, `dashboard/transfer-planner.ts|css`, `tests/test_optimise.py`, `tests/test_transfer_planner.mjs`, `README.md` (planner method text only), `ops/IMPLEMENTATION_REPORT.md` (append a "Fix round" section), `ops/TASK.md` (status line of this task only). Do not commit.

## Test command

As for Stage 3: `python -m unittest discover -s tests` · `npm run typecheck --prefix dashboard` · `npm run build --prefix dashboard` · `node --test tests/*.mjs`

---

# Previous task — Stage 3: multi-week transfer optimiser (integer linear program)

**Owner:** Programmer (Opus 5.5 subagent, medium effort). Review by a separate Opus 5.5 subagent (medium effort; it adds a runtime dependency to the public deploy image, so the review must check that build too).
**Status:** APPROVED via the fix task above (first review FAIL on FT valuation, fixed and re-reviewed PASS 2026-10-05)
**Date:** 2026-10-05
**Overseer request:** "start stage 3" (2026-10-05). The Overseer was told beforehand that this stage adds `highspy` (which brings in numpy). Design source: `research/fpl-maths.md` §3 (variables, constraints, objective, parameter table, pitfalls) and §6 Stage 3.

## Objective

Suggest the best transfer plans over the next 6 GWs:
- transfers only, with no chips this stage;
- from the manager's real squad, selling prices, bank and free transfers;
- the top 3 plans, each explained.

`plan.py` stays the rule checker: every suggested plan must pass `plan.build`.

## Required implementation

1. **`fpl_brief/optimise.py` (new).**
   - **Model:** implement the §3 ILP with `highspy`, for transfers only, over horizon W = 6. Variables per player and GW:
     - `squad`, `lineup`, `captain`, `vicecap`, `bench[o]`, `transfer_in` and `transfer_out`;
     - `itb[w]`, `fts[w]` and `hits[w]`.
   - **Constraints:**
     - squad of 15 split 2/5/5/3, at most 3 per club;
     - legal XI (1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD), with one captain and one vice-captain, both in the XI;
     - bench ordering, with a GK in the GK slot;
     - squad continuity from week to week;
     - budget with real selling prices from the account data (`private.prices`): players bought inside the horizon sell at the price paid;
     - free-transfer rollover clamped to 1–5, so the next GW gets the account's actual free transfers;
     - hits = max(0, transfers − FTs) × 4;
     - `no_transfer_last_gws = 2`.
   - **Objective:** decayed sum of XI xP + captain + `vcap_weight` × vice + bench weights, − 4·hits, + `ft_value`·(banked FTs), + `itb_value`·itb.
   - **Defaults** are named constants, taken from the §6 Stage 3 settings: decay 0.85, FT value 1.5, bench GK .03 / S1 .25 / S2 .08 / S3 .02, vice 0.05, itb 0.08 per £1m.
   - **xP input:**
     - `model="fpl"` (Stage 1) or `"own"` (Stage 2), taken from `projection.build`;
     - **default `"own"` for the optimiser only**, because Stage 1's `ep_next` carries 30-day form across six weeks, which the research flags as a pitfall for solvers;
     - the UI states clearly which model was used and lets the user switch.
   - **Player pool:** pre-filter to about 150 players: the manager's 15, plus the top players by horizon xP per position, plus price-efficient options. Make it deterministic and document the rule.
   - **Players flagged out:**
     - out next GW: not allowed in the next GW's XI;
     - otherwise: they follow their projection.
   - **Top 3 plans:** solve, add a "not this exact set of transfers" cut, and re-solve, up to 3 distinct plans.
   - **Per plan, return:**
     - the moves by GW (out → in, with prices);
     - hits;
     - FTs and bank week by week;
     - XI xP per GW, captain per GW and horizon xP;
     - the gain over a "no transfers" baseline solved the same way.
   - **Run limits:** a solve time limit of 10 s per plan, and deterministic seeds/options.
   - **Optional dependency:** the `highspy` import is optional. If it's missing, return `{"state": "unavailable", "reason": "Planner needs the highspy package"}`.
2. **Server:** `GET /api/optimise?model=own|fpl` sits behind the existing gate and loopback rules, the same as the private data. It needs fresh account data (`usable`). If the data isn't usable, it returns the same blocked message the lens uses. Cache the result per snapshot, account capture and model.
3. **UI:** a "Transfer planner" panel in the Candidate lens view, kept consistent with the existing style.
   - **Controls:** a model toggle and a "Suggest plans" button.
   - **Plans:** three plan cards, each showing moves by GW, hits, horizon gain against holding, and the FT/bank path.
   - **Try on board:** a button sends the plan's GW6 moves to the existing planned-transfers strip, which uses `plan.py`.
   - **Labels:** a method note says this is an optimisation over estimates and not advice, names the model, and says chips are not included.
   - **Escaping:** everything is escaped.
4. **Dependency and deploy:**
   - Add `highspy>=1.15` to `requirements-planner.txt` (Supervisor ruling 3, 2026-10-05: kept out of `requirements.txt` so the hosted image stays lean; the hosted planner answers "unavailable" because account data is local-only). If the pinned versions need numpy, that's fine.
   - Check that a binary wheel exists for **Python 3.14 on linux x86_64** (the Dockerfile base is `python:3.14-slim`) and for this Windows machine. Use `pip download --only-binary=:all: --platform ... --python-version 3.14` or the PyPI JSON.
   - Install it locally with pip.
   - Report the image size impact. If Docker is available locally, `docker build`. Otherwise, estimate from the wheel sizes and say so.
5. **Tests:**
   - Add `tests/test_optimise.py`, skipped cleanly when `highspy` is missing. Cover:
     - a tiny synthetic pool where the optimal transfer is known;
     - the budget and selling-price rule;
     - the 3-per-club rule;
     - FT rollover (holding banks an FT);
     - a hit taken only when it pays back within the decayed horizon;
     - no transfers in the last 2 GWs;
     - 3 distinct plans;
     - every plan passes `plan.build`;
     - the unavailable path when the import fails.
   - Add an endpoint test with fake data.
   - Add a node/vm or existing-harness check that the panel escapes and renders its states.

## Allowed paths

`fpl_brief/optimise.py`, `fpl_brief/projection.py` (read-only helpers only if needed), `dashboard.py`, `dashboard/*.ts|css|html` (Candidate lens view and the planned-transfers hand-off only), `requirements.txt`, `requirements-planner.txt`, `Dockerfile` (only if the build needs it), `tests/test_optimise.py`, `tests/test_dashboard.py`, `tests/*.mjs` (new panel test only), `README.md`, `ops/IMPLEMENTATION_REPORT.md`, `ops/TASK.md` (status line only).

You may `pip install highspy`. Do not commit. Do not run the fetcher.

## Test command

`python -m unittest discover -s tests` · `npm run typecheck --prefix dashboard` · `npm run build --prefix dashboard` · `node --test tests/*.mjs`

## Constraints

- Read-only. It never makes transfers or writes to FPL.
- Every output is labelled as an estimate-driven suggestion.
- The rest of the app works with `highspy` absent.

---

# Previous task — Stage 2 follow-up: clean-sheet calibration, backtest bias, collector isolation

**Owner:** Programmer (Opus 5.5 subagent, medium effort). Review by a separate Opus 5.5 subagent (medium effort).
**Status:** APPROVED (review PASS 2026-10-05; recalibration re-check due ~GW10, goal-level shrinkage first)
**Date:** 2026-10-05
**Overseer request:** "commit it and do the follow-up" (2026-10-05). Source: the Stage 2 review's optional items 1, 3 and 4 (the review was replaced by this task's review; see git `40fb865:ops/REVIEW.md`).

## Required implementation

1. **Clean-sheet calibration (`fpl_brief/projection.py`, and `xp_model.py` only if needed).**
   - **The problem:** over GW3–5, the team model gave a mean clean-sheet probability of 0.22 and 1.57 goals against per team-match. The actuals were 0.33 and 1.32 (60 team-matches). Defenders and goalkeepers are undervalued.
   - **Diagnose the cause first, and record it in the report.** Candidates:
     - the league base comes from xG (about 1.53 per club), not goals;
     - home-factor handling;
     - a Poisson zero-inflation or Dixon–Coles low-score effect (research §1);
     - something else.
   - **Fix it with the smallest principled change.** Examples: anchor the league base rate to actual goals while keeping xG for relative strength, or add the Dixon–Coles τ correction. **Don't** just multiply clean-sheet chances by a fudge factor.
   - **Validate without leakage.** Ratings for GW k come only from GWs before k. Report predicted vs actual mean clean-sheet chance and goals against for GW3–5, before and after the fix. Report the backtest table and bias before and after as well.
   - **Keep Stage 1 consistent:** it shares the team model, so its FPL-based multipliers change too. Report the effect on a few defenders: Van Hecke 112, De Cuyper 115, Gvardiol 391, Hall 449, Calafiori 8.
2. **Backtest bias (`fpl_brief/backtest.py`).**
   - Add a **bias** column: mean predicted − mean actual.
   - Add a second population: every player whose club had a fixture in that GW, with no-shows counted as 0 actual. The existing population is players who played.
   - Report both populations in the table and in `--json`.
3. **Collector isolation (`fpl_brief/collect.py`, around lines 150–158).** Parse player-history rows in their own `try` block, separate from the club-xG block. A bad player row should then drop only that row or that GW's player rows, with a warning, and never the GW's club xG. Add a test for this.
4. **Tests:**
   - the clean-sheet calibration change: a synthetic season where goals are below xG still predicts a clean-sheet rate close to the actual rate;
   - the bias column and the second population;
   - collector isolation.

   Update any existing assertions the calibration legitimately changes, and explain each change in the report.

## Allowed paths

`fpl_brief/projection.py`, `fpl_brief/xp_model.py`, `fpl_brief/backtest.py`, `fpl_brief/collect.py`, `tests/test_projection.py`, `tests/test_xp_model.py`, `tests/test_backtest.py`, `tests/test_fetch_fpl.py`, `tests/test_research_candidates.py`, `tests/test_plan.py`, `README.md` (method text only), `ops/IMPLEMENTATION_REPORT.md`, `ops/TASK.md` (status line only). The UI method strings in `fpl_brief/*.py` may change. Do not commit. Do not run the fetcher; the committed data files are enough.

## Test command

`python -m unittest discover -s tests` · `npm run typecheck --prefix dashboard` · `npm run build --prefix dashboard` · `node --test tests/*.mjs` · `python -m fpl_brief.backtest`

---

# Previous task — Stage 2: our own expected-points model, with a backtest

**Owner:** Programmer (Opus 5.5 subagent, medium effort). Review by a separate Opus 5.5 subagent (medium effort). Orchestration by the main session.
**Status:** APPROVED (review PASS 2026-10-05 with calibration check; UI checked in the browser by the orchestrator; local only, release needs Overseer approval)
**Date:** 2026-10-05
**Overseer request:** "start stage 2" (2026-10-05). Design source: `research/fpl-maths.md` §0 (2026/27 scoring), §1 (player model, minutes model, "Putting it together"), §2 (shrinkage defaults) and §6 Stage 2.

## Why

Stage 1 re-weights FPL's `ep_next`, which:
- is a 30-day form average;
- covers only the next week;
- carries a player's current doubt into all six weeks (accepted limitation, Stage 1 review).

Stage 2 builds each player's points from their parts, so we can see why a number is what it is and stop depending on FPL's unexplained estimate.

## Required implementation

1. **Data: per-player gameweek history (collector).**
   - `collect.py` already calls `event/{gw}/live/` for each finished GW. From the same responses, also keep a compact per-player row for every player with minutes > 0: `{gw, id, team, minutes, starts, xg, xa, goals, assists, cs, gc, saves, defcon_points, bonus, yellow, red, total_points}`. Use what the live `stats` object actually provides, and document any field that is missing.
   - **Storage:** write it to a separate file, `data/player_history.json`, not into `latest.json`, so the snapshot stays small. Keep keys short. At season end it should be at most about 2 MB.
   - **No new endpoints** and no per-player `element-summary` calls.
   - **ep_next log:** also log the current `ep_next` for every player, keyed by the upcoming GW, to `data/ep_log.json`. It is append-only; keep the first capture per GW. That lets future backtests compare against FPL's own estimate, which the API does not keep for past GWs.
2. **Model (`fpl_brief/xp_model.py`, new, pure functions, stdlib).** Implement the recipe in research §1 "Putting it together", with the 2026/27 scoring table in §0.
   - **Minutes:**
     - `p_play` and `p_60` come from the player's last N appearances (N = 4, time-weighted).
     - **The next GW only** is multiplied by `chance_of_playing_next_round/100` when FPL flags a doubt. Players with status `i`/`s`/`u`/`n` get 0 next GW.
     - Later weeks use the recent-minutes rate, which fixes the Stage 1 doubt-carry. Players with status `i`, or `s` with a known return, are back at their normal rate from the GW after `news` implies, or GW+2 if unknown. Keep this simple and labelled.
   - **Attack:** shrunk xG/90 and xA/90 with `rate = (events + k·prior)/(exposure + k)` and k = 900 minutes. The prior is the position × price-band mean from this season's pooled data, with price bands from `now_cost`. This season only, no `history_past`. Scale per fixture by Stage 1's `att_mult` (team attack × opponent defence relative to league average).
   - **Defence:** P(CS) from the Stage 1 team model (`exp(−λ_against)`), and `E[floor(GC/2)]` from a Poisson sum. Both apply to GK/DEF with the §0 points.
   - **Side points:**
     - Defensive contribution: a rate of points per 90, shrunk with k = 10 matches to the position mean.
     - Bonus: k = 10 matches, to the position mean.
     - Cards: k = 10 matches.
     - GK saves/3: k = 10 matches.
   - **Output:** per player, per GW of the 6-GW horizon, a total plus a breakdown `{appearance, goals, assists, clean_sheet, conceded, saves, defcon, bonus, cards}`. Double GWs sum, blank GWs are 0.
   - **Constants:** all are named and commented as defaults from AIrsenal/research §2.
3. **Backtest (`fpl_brief/backtest.py`, new, stdlib, `python -m fpl_brief.backtest`).**
   - For each finished GW k ≥ 3, fit using GWs < k only (no leakage) and predict GW k.
   - Report mean absolute error (MAE) and Spearman rank correlation against actual `total_points`, for every player who played and for the top 100 by price.
   - Compare against two baselines available for past GWs: the player's points per game so far, and the average of the last 3 GWs.
   - Where `data/ep_log.json` has FPL's `ep_next` for a GW, compare against that too. Today it will have none, which is expected.
   - Output is a plain table on stdout and an optional `--json`.
4. **Wiring (side by side, not replacing).**
   - `projection.build` gains a `model` choice: `"fpl"` (Stage 1, the default) or `"own"`.
   - The Candidate lens shows **both** six-week numbers: "Next 6 GWs (FPL-based)" and "(our model)". It flags players where they differ by more than 2 points per GW on average.
   - Clicking or hovering a player shows our model's breakdown, with values escaped.
   - The planned-transfers summary gains `horizon_delta_own` next to `horizon_delta`.
   - The default stays FPL-based. **Switching the default is a later Overseer decision**, based on backtest evidence.
5. **Tests (`tests/test_xp_model.py`, `tests/test_backtest.py`, new; extend the existing ones).** Cover:
   - scoring by position;
   - shrinkage: zero minutes gives the prior, and a heavy-minutes player tends to their own rate;
   - the minutes model, including a doubt applying to next GW only and an injured player returning;
   - the Poisson sum for `E[floor(GC/2)]`;
   - DGW and BGW;
   - no-leakage in the backtest, by building a fixture where using GW k data would change the answer;
   - the collector writing both new files from fake live data, including a failed fetch;
   - the lens and plan fields.

## Allowed paths

`fpl_brief/xp_model.py`, `fpl_brief/backtest.py`, `fpl_brief/projection.py`, `fpl_brief/collect.py`, `fpl_brief/candidates.py`, `fpl_brief/plan.py`, `fetch_fpl.py` (only if the new data files need writing there), `dashboard.py` (only if wiring needs it), `dashboard/*.ts|css|html` (Candidate lens and planned-transfers strip only), `tests/test_xp_model.py`, `tests/test_backtest.py`, `tests/test_projection.py`, `tests/test_research_candidates.py`, `tests/test_plan.py`, `tests/test_fpl_brief.py`, `tests/test_fetch_fpl.py`, `tests/test_dashboard.py`, `README.md`, `ops/IMPLEMENTATION_REPORT.md`, `ops/TASK.md` (status line only).

You may run the fetcher once to generate the new data files for the backtest, but do not commit.

## Test command

`python -m unittest discover -s tests` · `npm run typecheck --prefix dashboard` · `npm run build --prefix dashboard` · `node --test tests/*.mjs` · `python -m fpl_brief.backtest` (report the table)

## Constraints

- Stdlib only.
- Read-only public FPL endpoints.
- Every number is labelled as an estimate.
- The bonus prior is this season only, because BPS changed for 2026/27.
- Escape all UI output.

---

# Previous task — Stage 1 projections: six-gameweek expected points from `ep_next` and fixtures

**Owner:** Programmer (Opus 5.5 subagent, medium effort). Review by a separate Opus 5.5 subagent (medium effort). Orchestration by the main session.
**Status:** APPROVED (review PASS 2026-10-05; optional items 1–3 fixed after review, focused tests 107 OK; local only, release needs Overseer approval)
**Date:** 2026-10-05
**Overseer request:** "yes start stage 1" (2026-10-05), from the plan in `research/fpl-maths.md` §6. Today every ranking uses FPL's next-gameweek estimate (`ep_next`) only (`fpl_brief/plan.py:100` says so). Transfers pay back over weeks, so the manager needs a six-gameweek view.

## Objective

Project each player's points for the next 6 gameweeks with stdlib-only code, then show the six-week number in the Candidate lens and in the planned-transfer summary. `lineup.py` is unchanged: `ep_next` is still right for this week's XI.

## Required implementation

1. **Data (collector).** `fpl_brief/collect.py` adds a compact `team_results` list to the snapshot. It has one row per finished fixture this season: `{gw, fixture_id, home, away, home_goals, away_goals, home_xg, away_xg}`.
   - Scores come from `fixtures/`, which is already fetched.
   - xG comes from `event/{gw}/live/` (one call per finished GW). Sum each player's `expected_goals` by club.
   - When a club plays twice in one GW, split by fixture using `explain[].fixture` if the data allows. Otherwise set that fixture's xG to `null`.
   - A failed live fetch leaves xG `null` for that GW and adds a snapshot warning. It must never fail the whole collection.
   - Existing snapshot fields are unchanged. Bump the snapshot schema version only if the existing code requires it.
2. **Model (`fpl_brief/projection.py`, new, pure functions).** Follow `research/fpl-maths.md` §1, the "stdlib-friendly fit" and §6 Stage 1.
   - **Team ratings.** Fit multiplicative attack and defence ratings plus a league-wide home factor by iterating (about 50 rounds) on `team_results`.
     - Use xG where present and goals where xG is `null`.
     - Shrink towards league average with `PRIOR_MATCHES = 6` pseudo-matches.
     - Deterministic, and no division-by-zero on an empty season. With no results, every rating is 1.0.
   - **Per fixture**, for a club: `λ_for`, `λ_against`, `cs_prob = exp(−λ_against)`, and `att_mult = λ_for / league average`. Do the same for the defensive side.
   - **Position blend.** Combine attack and clean-sheet multipliers with named constants: FWD/MID 0.7/0.3 and DEF/GK 0.3/0.7. Label these as heuristics in the code and the UI method text.
   - **Projection.** For each player:
     - `ep_base = ep_next / Σ mult over next-GW fixtures`, which removes the next fixture's difficulty from FPL's estimate.
     - Then `xP[w] = ep_base × Σ mult over the club's fixtures in GW w`.
     - A blank GW gives 0, and a double GW sums both fixtures.
     - If the player has no fixture next GW, use `form` as the base instead, and flag it.
     - Players FPL lists as unavailable (`status` not `a`/`d`) project 0 for every week, flagged.
   - **Totals.** Return per-GW values, the 6-GW total, and a decayed total (`DECAY = 0.85` per week from the next GW).
   - Never double-count availability: `ep_next` already includes it.
3. **Wiring.**
   - **`candidates.lens`:** each candidate, and the player being replaced, gains `xp_6` and `xp_6_decayed`. The Candidate lens UI shows a "Next 6 GWs" column, can sort by it, and gives a one-line method note.
   - **`plan.build`:** the `summary` gains `horizon_delta`, the difference in the best XI's decayed 6-GW xP with and without the moves, minus hits.
     - Keep `xi_delta`/`net_delta` as they are.
     - Update `method` to describe both numbers honestly.
     - The planned-transfers strip shows the six-week delta next to the next-GW delta.
   - **Missing data.** If `team_results` is missing (an old snapshot), projections still run with all ratings at 1.0, so only the fixture count matters. The response says so.
4. **Tests (`tests/test_projection.py`, new).**
   - A strong attack against a weak defence gives a higher multiplier than the reverse.
   - Shrinkage pulls a 1-match team towards 1.0.
   - Empty season gives all 1.0.
   - A DGW sums, and a BGW gives 0.
   - The base is de-fixtured from `ep_next`.
   - Decay is applied correctly.
   - An unavailable player projects 0.
   - xG falls back to goals when it is null.
   - The collector builds `team_results` from fake `fixtures/` and `event/{gw}/live/` data, including a failed live fetch.
   - Extend the existing candidate and plan tests for the new fields.

## Allowed paths

`fpl_brief/projection.py`, `fpl_brief/collect.py`, `fpl_brief/candidates.py`, `fpl_brief/plan.py`, `dashboard.py` (only if wiring needs it), `dashboard/*.ts|css|html` (Candidate lens and planned-transfers strip only), `tests/test_projection.py`, `tests/test_research_candidates.py`, `tests/test_plan.py`, `tests/test_fpl_brief.py`, `tests/test_dashboard.py`, `README.md`, `ops/IMPLEMENTATION_REPORT.md`, `ops/TASK.md` (status line only).

Do not commit, and do not commit regenerated `data/` or `digest.md` files.

## Test command

`python -m unittest discover -s tests` · `npm run typecheck --prefix dashboard` · `npm run build --prefix dashboard` · `node --test tests/*.mjs`

## Constraints

- Stdlib only, with no new dependencies.
- Read-only public FPL endpoints, and no credentials.
- Everything projected is labelled as an estimate built from FPL's `ep_next` plus a fixture model, never as a forecast guarantee.
- Escape all UI output.

---

# Previous task — Matchday: live gameweek, live mini-league, points left on the table

**Owner:** Programmer (Claude Opus 5.5, main session); review by a separate Opus 5.5 subagent at medium effort (read-only public FPL data, no secrets; a new outbound fetch path on the hosted server)
**Status:** APPROVED (independent re-review PASS 2026-09-26; local only, release needs Overseer approval)
**Date:** 2026-09-26
**Milestone:** Overseer asked for "a killer feature that impresses me" (2026-09-26). Chosen: a Matchday view. Evidence it matters: in GW5 the manager's best possible XI from the same 15 scored 79 against 54 actual, with 20 points left on the bench.

## Required implementation

1. `fpl_brief/matchday.py` (pure functions plus a small fetch layer with an injectable getter):
   - **Live scoring** of a 15-player pick set from `event/{gw}/live/` and `fixtures/?event={gw}`:
     - chip-aware multipliers (Bench Boost, Triple Captain);
     - projected auto-subs (FPL rules: in bench order, formation legal, GK for GK; only for starters whose fixtures are all finished with 0 minutes; a pending bench player blocks further projection);
     - captain passes to the vice when the captain didn't play;
     - provisional bonus from BPS for started fixtures whose bonus isn't in yet (FPL tie rules).
   - **Player state:** yet to play, playing, or done.
   - **Live mini-league table** across the snapshot's compared rivals plus the manager:
     - live total = total before the GW + live GW points − hits;
     - live rank and movement against the pre-GW order.
   - **Swing players:** points × (your multiplier − the rivals' average multiplier), with the top gains and losses.
   - **Season hindsight** for each finished GW:
     - the official points against the best legal XI and captain from the same 15 (chip-aware), split into armband cost and lineup cost;
     - bench points compared with the rivals' average.
   - **Caching:** a bounded in-memory TTL cache.
     - Live data: 60 s.
     - Picks per entry/GW: 1 h.
     - Finished GW data: long-lived, reduced to points and minutes.
   - **Fetching:** short timeouts and parallel rival fetches. Failures degrade to `state: unavailable` or per-rival warnings.
2. `GET /api/matchday` behind the existing gate.
3. **UI:** a new Matchday view (Tactics Board world).
   - GW header with status (Live, Provisional or Final) and your points.
   - The board shows real points on the shirts, captain and auto-sub marks, and a bench tray.
   - The live league table with movement arrows, and the swing players.
   - The season "points left on the table" ledger with per-GW bars.
   - It auto-refreshes every 60 s while live and the view is open. Everything is escaped.
4. **Tests:** Python unit tests for bonus ties, auto-subs, captaincy fallback, chips, hindsight optimum, league math (hits), swing, cache and failure degradation, plus the endpoint with a fake getter. A node/vm render test for escaping and the states.

## Allowed paths

`fpl_brief/matchday.py`, `dashboard.py`, `dashboard/*.ts|css|html`, `tests/test_matchday.py`, `tests/test_dashboard.py`, `README.md`, `DESIGN.md`, `ops/*`.

## Test command

`python -m unittest discover -s tests` · `npm run typecheck --prefix dashboard` · `npm run build --prefix dashboard` · `node --test tests/*.mjs`

## Constraints

Read-only public FPL endpoints only; no FPL writes, no credentials. Label everything that is a projection: bonus and auto-subs are provisional until FPL confirms. Hindsight is labelled as "best possible with hindsight", not a skill score.

---

# Follow-on task — League threats panel and fixture ticker

**Status:** APPROVED (review PASS 2026-09-26, see REVIEW.md) · **Date:** 2026-09-26 · **Overseer request:** "add the league threats panel", plus each club's next fixtures and long breaks.

1. **`fpl_brief/league.py`:**
   - `threats(snapshot, get)`: live standings page 1, the top 10 rivals excluding you, and their GW picks plus history. It returns:
     - players owned by at least half of them that you don't have;
     - your differentials (at most one rival owns them);
     - your shield (players you share with at least half of them);
     - their captains;
     - a table with the points gap, shared count and chips left.
   - `chips_left(rules, used, gw)` uses FPL's chip windows (`start_event` and `stop_event`).
   - `ticker(...)`: every club's next 6 GWs with FDR and dates, a break marked when a club goes 12+ days without a match, and blank and double weeks. Sorted by the average FDR over the next 4.
2. **Server:** `GET /api/league` is behind the existing gate and uses the shared Matchday cache. `/api/dashboard` adds `ticker`, built from snapshot fixtures only.
3. **UI:** the Rivals view loads the League threats panel lazily (at most once every 10 min). The Overview's text-only "Fixture horizon" card is replaced by the fixture ticker. Everything is escaped.
4. **Tests:** `tests/test_league.py`, plus a stub in the existing overview harness.

**Allowed paths:** `fpl_brief/league.py`, `dashboard.py`, `dashboard/league-threats.ts|css`, `dashboard/app.ts`, `tests/test_league.py`, `tests/test_dashboard.py`, `ops/*`. **Test command:** as above.
