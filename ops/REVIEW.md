# Independent review: Stage 4, rival maths (EO, captaincy vs rivals, finish odds)

**Date:** 2026-10-05
**Reviewer:** Opus 5.5 subagent, medium effort (did not implement this work)
**Verdict:** **PASS**. The EO, swing, captain Monte Carlo and the finish-odds model, as it stands after the Supervisor rulings, match the task and research §4. The analytic and simulated paths use the same mean, mean-uncertainty and σ_week terms. The endpoint reuses the threats fetch, sits behind the gate and degrades on failure. Everything in the UI is escaped and labelled as an estimate. All tests pass. Nothing is blocking; there are six optional notes.

## Checks

- **Tests (run once):**
  - `python -m unittest discover -s tests`: **291 OK** (30.2 s);
  - `npm run typecheck --prefix dashboard`: OK;
  - `npm run build --prefix dashboard`: OK;
  - `node --test tests/*.mjs`: **14/14 pass**.
- **Scope:** the changed paths are `fpl_brief/rivals.py` (new), `fpl_brief/league.py`, `dashboard.py`, `dashboard/app.ts`, `dashboard/rival-maths.ts|css` (new), `tests/test_rivals.py` (new), `tests/test_rival_maths.mjs` (new), `README.md`, `ops/IMPLEMENTATION_REPORT.md` and `ops/TASK.md` (status line only). All of them are allowed paths. Nothing is committed (HEAD is still 4200ae5). Only the stdlib is used: `math` and `random` (`rivals.py:19-22`). The endpoint test lives in `tests/test_rivals.py`, not `test_dashboard.py`; both are allowed.
- **EO arithmetic** (`rivals.py:48-64`):
  - benched is 0 unless `bboost`, a starter is 1, the captain is 2 and `3xc` gives 3;
  - `effective_ownership` is the mean over rivals (`:78-86`);
  - tested in `test_rivals.py:22-35`.
  - The vice-captain is not modelled; see Optional 4.
- **Assumed captain before the deadline** (`rivals.py:67-75`):
  - the rival's last captain if he still starts and has xP > 0, otherwise their highest-xP starter;
  - the reason is returned per rival and shown as "C X (assumed: …)" (`rival-maths.ts:66`), with the rule also listed under assumptions (`rivals.py:463-465`).
  - "Still starts" is slightly stricter than the brief's "still owns him", which is reasonable.
  - Tested in `test_rivals.py:46`.
- **Your multipliers:** taken from the account lineup when `private.usable`, plus a pending BB/TC (`rivals.py:351-356`), otherwise from the public snapshot picks. The account lineup carries `position` and `is_captain` (`private_team.py:85`), so `multipliers` reads it correctly. The source is shown in the UI (`rival-maths.ts:85`). Tested in `test_rivals.py:186`.
- **Swing:**
  - `Σ (mine − theirs)·xP`, so a positive result is good for you (`rivals.py:89-96`).
  - It is computed per rival (`:385`) and against EO (`:378`), with the top 5 drivers each way (`:373-376`).
  - The sign is tested at `test_rivals.py:36`.
- **Captain Monte Carlo:**
  - **Shared draws:** one seeded column per involved player (`rivals.py:139-149`). Every lineup is scored on the same columns (`:152-160`, `:404-424`), so identical squads cancel exactly (`test_rivals.py:55`).
  - **Points distribution:** `max(−2, round(gauss(xP, sd)))`.
  - **sd:**
    - per-appearance sd by position, shrunk with 50 pseudo-appearances (`:99-129`);
    - scaled by `min(1, √(xP/mean))` (`:132-136`).
    - The scaling is justified: it limits the upward bias that the −2 floor puts on low-xP players. It is documented as a deviation and in the method text.
  - **"Beats the field":** your captain's extra points × R vs the summed rival extras, with ties counting ½ (`:408-421`). This captain-only reading is stated in the method (`:471`), and an identical captain gives exactly 50%.
  - **Rival columns:** P(full-squad diff ≥ 0) (`:424-426`).
  - **Heuristic flag:** labelled as a heuristic in the data (`:429-432`) and the UI (`rival-maths.ts:65`, `:80`).
  - **Determinism:** fixed `SEED` (`rivals.py:25`).
- **League refactor:**
  - `gather` only adds `picks`, `active_chip`, `history` and `finished` to data that was already fetched (`league.py:133-137`).
  - `threats` consumes it unchanged, and the existing league tests pass.
  - The endpoint test asserts that `/api/rivals` reads exactly the same set of paths as threats (`test_rivals.py:240-252`).
- **Server** (`dashboard.py:914-921`):
  - it sits after `self.gate(path)` (`:871`) and the loopback/DNS-rebinding check (`:886`);
  - account data still goes through `private_data`, which returns `disabled()` on a non-loopback bind (`:578-582`);
  - any exception gives `state: "unavailable"`;
  - sign-in is required when a password is set (`test_rivals.py:257`).
- **UI:**
  - every interpolation goes through `esc`/`num`/`pct`/`signed` (`rival-maths.ts:24-35`, `:53-88`). `jerseySvg` takes only a lookup key (`kits.ts:32-33`).
  - The subtitle says "Every probability here is an estimate from a simple model". The P columns and the title bar say "estimate", and the method text opens with `ESTIMATE`.
  - Lazy load: at most once per 10 min, including after an error, because `loadedAt` is set in `finally` (`app.ts:467-487`).
  - The node tests cover escaping and the loading, idle, error and unavailable states.

## Odds model (after the Supervisor rulings)

- **Weekly mean:**
  - gross points shrunk to the tracked league mean with k = 5, minus the average hit cost (`rivals.py:202-210`).
  - The analytic edge uses `net` (`:253`); the sims use `mean − hits` (`:308`). Hits are subtracted in both paths.
- **σ_m (group-relative):**
  - residuals against each GW's group average (`:187-192`), shrunk to pooled with 5 pseudo-GWs (`:207`);
  - `mean_var = σ_m²/(n + k)` (`:210`).
  - The same `mean_var` feeds the analytic path (`pairwise` → `finish_odds`, `:254`, `:232`) and the sims (`:306`), so the Supervisor-accepted reading is implemented consistently.
- **Season sims:**
  - the mean is drawn once per sim per manager (`:306`), which gives the n² variance;
  - each week bootstraps one GW index shared by everyone (`:300-303`);
  - deviations are measured from each manager's own net mean, so the bootstrap has zero mean (`:211`).
- **Top-up** (`:266-279`):
  - `need_r = max(0, σ_week² − b²_r)`, so there is no negative top-up;
  - `t_you² = ½·min need`, and `t_r² = need_r − t_you² ≥ 0`, so the variances add to σ_week² per (you, r) pair;
  - the n weekly top-ups are drawn as one `N(0, t√n)`, which is exact for summed iid normals.
  - Tested at `test_rivals.py:121`.
- **Outputs:**
  - P(ahead) comes from the sims, with ties counting ½ (`:313-315`);
  - wins are split on ties, so title odds sum to 1 (`:309-312`; test `:109`);
  - expected rank: `:316`;
  - the analytic Φ uses `math.erf` (`:43-45`) with `n·σ_week² + n²·(v_you + v_r)` (`:232`), the same terms as the sims. The sim and analytic results agree within 5 points in `test_rivals.py:131`, and within 0.9 points on the reported real data.
- **Real numbers:**
  - not reproduced here: the live read-only getter stalled in this sandbox with no network progress, so I stopped it.
  - The reported figures (you 11.7% title, FNN. 41.3% sim vs 41.4% analytic, z = −0.22) are internally consistent: Φ(−0.22) = 0.413.
- **Double counting (judgement):** none.
  - σ_week is the spread of the weekly difference around the pair's own mean difference.
  - The mean-uncertainty term is the uncertainty of that mean.
  - The bootstrap plus the top-up only fill σ_week (they never add to it, except where the bootstrap alone already exceeds it).
  - These are the two parts of a normal–normal predictive variance, not the same variance counted twice.
  - The compression towards 50% comes from the prior strength: k = 5 implies a between-manager sd of true weekly means of σ_m/√5 ≈ 5–6 pts/GW. That is probably generous for a top-of-league group; see Optional 1. It is a modelling choice the Supervisor set, not an error.

## Blocking

None.

## Optional

1. **Prior strength:** k = 5 makes the mean uncertainty dominate this early (all P(ahead) values fall between 41% and 72%). An empirical-Bayes estimate of the between-manager variance, `τ² = max(0, var(observed means) − σ_m²/n)`, so that k = σ_m²/τ², would let the data set the shrinkage as the season goes on. Revisit at around GW10.
2. **Title odds are calibrated pairwise only against you** (`rivals.py:278-279`). Rival-vs-rival weekly spreads are `b² + t_r1² + t_r2²`, which is not matched to their own σ_week. That matters for P(1st) of rivals, not for your P(ahead). It is worth one line in the method text.
3. **Unfinished GW:** when `finished` is false, G uses live totals that include part of the current GW, while `remaining` still counts that GW in full (`rivals.py:347`), and its partial points also enter the means and the bootstrap. This is a small bias mid-gameweek. You could exclude the unfinished GW from `_weekly` and use the previous GW's totals.
4. **Vice-captain:** not modelled. That is acceptable, because the Normal draw never models 0 minutes. A note under assumptions would match research §4 ("the vice only counts when the captain gets 0 minutes").
5. **Heuristic favourite:** it is chosen among your top-5 candidates (`rivals.py:429`), not as the field's most-captained player. If the field's favourite is not one of your top-5 starters, the flag cannot fire. That is rare in practice.
6. **Duplicate fetch:** threats and rival maths fire in parallel on first open, so before the cache fills both may fetch the same endpoints once (this is noted in the report). Chaining the second load after the first would avoid it.
