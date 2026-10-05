# Independent review: Stage 1 projections (six-gameweek expected points)

**Date:** 2026-10-05
**Reviewer:** Opus 5.5 subagent, medium effort (did not implement this work)
**Verdict:** **PASS** (nothing blocking; optional items below)

## Checks

- **Rating fit** (`fpl_brief/projection.py:48-88`):
  - The model is multiplicative: `λ_home = base·A_h·D_a·H` and `λ_away = base·A_a·D_h/H` (lines 51, 65-77).
  - Attack is updated from the current defence, then defence from the new attack. Both are renormalised to mean 1 (lines 78-81), over `ITERATIONS = 50` rounds.
  - Shrinkage adds `PRIOR_MATCHES = 6` pseudo-matches: `prior = 6·base` is added to both the numerator and the denominator (lines 62, 64, 71). A probe kept a 3-0 single match near 1.1, not an extreme value.
  - The home factor update `sqrt(ratio_home / ratio_away)` (line 87) recovers H correctly. It is also shrunk, which is a documented deviation and reasonable.
  - xG falls back to goals per side (line 41). Negative or missing values drop the row (line 42).
  - An empty season returns all 1.0, `H = 1` and `base = 1.4` (line 58). There is no division by zero: every denominator is at least `prior > 0`, and `base <= 0` returns early (line 60).
  - The fit is deterministic: rows and teams are sorted (lines 45 and 55).
- **Per fixture** (lines 91-100): `λ_for`, `λ_against` and `cs_prob = exp(−λ_against)` are as specified. `att_mult = λ_for/base`, and `cs_mult` is the clean-sheet chance relative to the league-average one.
  - The position blend uses named constants, `ATTACK_WEIGHT` (line 18). It is labelled a heuristic in the code (lines 17 and 104), in the method text (line 199) and in `README.md`.
- **Projection** (lines 133-155):
  - `ep_base = ep_next / Σ mult(next GW)` (line 146), then `xP[w] = ep_base·Σ mult(w)` (lines 141-152).
  - A blank week sums an empty list, which gives 0. A double week sums both fixtures.
  - With no fixture next GW, the base is `form`, flagged (lines 147-151). The `d`-status scaling there is justified because `form` carries no availability.
  - A status other than `a`/`d` gives 0 every week, flagged (lines 136-138).
  - `ep_next` is never scaled again for availability (line 145 comment).
  - Decay uses `0.85^k` with k = 0 for the next GW (line 155).
- **Best XI** (lines 158-177): the formation limits are legal (1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD, 11 players), each week is decayed, and there is no captain.
- **`plan.build`** (`fpl_brief/plan.py:93-108`):
  - `xi_delta` and `net_delta` are unchanged (lines 93 and 102).
  - `horizon_delta = squad_horizon(new_squad) − squad_horizon(owned) − hit_points` (lines 95-96 and 103): the decayed six-GW best-XI difference, with the hit subtracted once.
  - `method` describes both numbers and their assumptions (no captain, no later transfers), and appends the missing-data caveat (lines 104-107).
- **Collector** (`fpl_brief/collect.py:53-108`):
  - It makes one `event/{gw}/live/` call per GW that has finished fixtures (lines 94-97). These are read-only public endpoints.
  - A failed fetch adds one warning, leaves xG `null` and keeps the scores (lines 98-100).
  - A DGW club's xG is set to `null` when it can't be split by fixture (lines 77-84).
  - Players who moved clubs are skipped (line 74).
  - The snapshot adds only `team_results` (line 147); all other fields are unchanged. `schema_version` stays 1, and nothing gates on it for this snapshot.
  - `data/latest.json` has no `team_results`, which confirms that the live fetcher was not run into `data/`.
- **Candidate lens** (`fpl_brief/candidates.py:82-111`): candidates and `outgoing` gain `xp_6`/`xp_6_decayed`. The response adds a `projection` block, and the projection caveats are appended. The default server order is unchanged.
- **Old snapshots:** when `team_results` is missing, ratings are 1.0 and a caveat explains that (`projection.py:190-191`), and the plan's `method` carries it too. The UI only shows the horizon when the field is a number (`dashboard/transfer-plan.ts:77`) or present (`desk-tools.ts:236-237`), so the Cloudflare lens shows "-".
- **UI escaping:**
  - Every new interpolation goes through `escapeHtml`/`esc`, which escape `& < > " '`: the `title` attribute, `xp_6`, the outgoing note and the projection method (`desk-tools.ts:232-238`), and the strip (`transfer-plan.ts:77`).
  - The node strip test checks escaping of `method` (`tests/test_dashboard.py:1126-1127`).
- **Sorting:** a client-side sort by the decayed value, with nulls last (`desk-tools.ts:231`). Changing the sort re-runs the lens when a table is already shown (line 259).
- **Scope:** the changed paths are all allowed. Stdlib only (`math`, `itertools`). HEAD is still `133fb1e`, so nothing was committed.
- **Supervisor-accepted limitations:** the 6-week doubt, the DGW goals fallback and defence tuning are all recorded in `ops/IMPLEMENTATION_REPORT.md` under Limitations, and the DGW behaviour is explained in the `collect.py:54` docstring. The doubt limitation is *not* in the user-facing method text (see Optional 1).
- **Runs (the task command, once):**
  - `python -m unittest discover -s tests`: **220 OK**, including 13 in `tests/test_projection.py`.
  - `npm run typecheck`: clean.
  - `npm run build`: OK.
  - `node --test tests/*.mjs`: **10/10 pass**.
  - Edge probes: an all-0-0 season, a club with no matches, a doubtful player with no fixture, and a missing status. None raised an error.

## Blocking

None.

## Optional

1. **The doubt isn't labelled in the UI.**
   - **Problem:** a `d` player's `ep_next` doubt carries into all six weeks. The Supervisor accepted this for Stage 1, but it is stated only in the report, not in `projection.build`'s `method` (`projection.py:197-200`), so the manager can't see it.
   - **Fix:** add one sentence such as "A player's current doubt is applied to every week."
2. **The column and the sort use different numbers.**
   - **Problem:** the "Next 6 GWs" column shows the undecayed `xp_6`, but the "Next 6 GWs (estimate)" sort uses `xp_6_decayed` (`desk-tools.ts:231-232`). Rows can therefore look out of order.
   - **Fix:** show the decayed value, or label the sort "Next 6 GWs (decayed)".
3. **The "6" is hard-coded.**
   - **Problem:** the column header and the lens note always say "6". Near the end of the season the stored horizon can be shorter. The strip already uses `horizon_gameweeks.length`.
   - **Fix:** use `projection.gameweeks.length` in the lens too.
4. **An all-zero season reports itself as fitted.**
   - **Problem:** if every match is 0-0 with no xG, the early return (`projection.py:61`) gives `matches = len(matches)`, so `ratings_fitted` is True while all ratings are 1.0. This is cosmetic and very unlikely.
5. **Repeated full-catalog projection.**
   - **Problem:** `projection.build` projects the whole catalog on every lens and plan request (`candidates.py:82`, `plan.py:94`). It is cheap today (about 700 players × 6 GWs).
   - **Fix:** project only the needed IDs, or cache per snapshot, if latency ever shows.
