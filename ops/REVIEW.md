# Independent review: Planner, force players in or out

**Date:** 2026-10-05
**Reviewer:** Opus 5.5 subagent, medium effort (did not implement this work)
**Verdict:** **PASS**. The constraints are variable bounds on the steered solve only. The hold baseline is identical to the free run's, both in code and in a real run. `unconstrained_best_gain` is the free run's plan 1, and it is cached under an order-free key. Validation, strict parsing, the 400s and the infeasible reasons all match the task. The UI escapes everything. All four test commands pass. The real run reproduces exactly. The Haaland sale in GW8 is a genuine (marginal) model choice, not a bug. Nothing is blocking; there are five optional notes.

## Checks

### Encoding (steered run only)

- `formulate` applies the constraints only when `constraints and not hold` (`fpl_brief/optimise.py:309`):
  - force_in sets the lower bound of `squad[p, gw]` to 1 (`:312`);
  - force_out sets its upper bound to 0, for pool players only (`:315`);
  - keep sets the upper bound of `out[p, w]` to 0 for every week (`:318`).
- No other player's bounds or rows are touched. Continuity, budget, FTs, the club limit, the frozen GWs and the 3 transfers per GW are unchanged (`:228-308`).
- **Pool.** Forced-in players are always included through `select_pool(..., extra=...)` (`:165`, `:569`).
- **force_out outside the pool.** Build drops it as already satisfied (`:572`). This is sound: a player outside the pool can never be bought, and every owned player is in the pool.

### Hold baseline (the late fix)

- The hold is solved with `run(True, relax and not constraints)` (`:432`), with the existing fallback to the relaxed XI (`:433-435`).
- I checked that this matches the free run:
  - A strict main-model infeasibility implies a strict hold infeasibility, because holding is a feasible point of the main model.
  - So whenever the free run itself used `relax=True`, the steered strict hold also fails and falls back to the same relaxed hold.
  - Otherwise both runs use the same strict hold, with the same fallback.
  - The pool differs only by players the hold can't buy.
- **Evidence:**
  - the test asserts the steered hold equals the free hold (`tests/test_optimise.py`, `test_forced_in_player_is_in_the_squad_by_his_gw`);
  - in my real runs, hold `horizon_xp` was 229.52 for the free run, for (a), and for (a) plus keep Haaland.
- The report says only focused tests ran after the fix: `test_optimise.py` 32 OK, and the dashboard Optimise tests 7 OK. That follows the token-discipline rule. My full run below covers it.
- No test exercises the relaxed-hold branch with constraints (optional 1).

### Unconstrained best and the cache

- Server (`dashboard.py`):
  - The cache key is `base_key + constraints_key(...)` (`:720`).
  - The free key is `constraints_key(None)` (`:730`), which equals the key of a plain request (`((), (), ())`). The two can't be mixed up.
  - A steered request solves and caches the free run first, then passes `best_of` (`:731-736`).
  - A non-ready free run is returned as-is and never cached (`:733-734`).
- `constraints_key` sorts each kind, so it is order-free (`fpl_brief/optimise.py:110`, and `test_cache_key_is_order_free`).
- `best_of` takes plan 1 of a ready result (`:508`).
- `cost_vs_unconstrained = gain − best gain`, set only when constraints are active (`:629`).
- The CLI path, without a supplied best, solves the free run inside `build`.
- `OPTIMISE_CACHE_SIZE` is 8 (`dashboard.py:64`).

### Validation, parsing and infeasibility

- `validate_constraints` (`fpl_brief/optimise.py:120-158`) returns `invalid` for each case the task lists:
  - an unknown id;
  - a GW outside the horizon (the default is the next GW);
  - a keep player who isn't owned;
  - the same player in and out at the same GW;
  - more than 5 constraints;
  - duplicates;
  - a player both kept and forced out.
- `build` validates against the catalog and `solve` against the pool.
- **Parsing.** `parse_constraints` (`:90`) uses `re.fullmatch` with ASCII `[0-9]`, which rejects full-width digits, `1@`, `1.5` and `@@` (tests).
- **Endpoint.**
  - A ValueError or a repeated parameter gives 400 `invalid` (`dashboard.py:703-708`).
  - A validation `invalid` from `build` also gives 400 (`:742`).
  - The gate, loopback and blocked handling are unchanged. The DNS-rebinding test with constraints gives 403.
- **Infeasible.**
  - Plain reasons come before solving: a gone player, or a doubtful player forced in for the next GW (`:516`).
  - A steered infeasibility names the constraints and the rule families (`:430`, `:589-593`).
  - A time limit is reported separately (`:428`).
  - Nothing is dropped silently, except the force_out no-op above.
- **Unchanged:** the GW6 distinctness cut (`_cut`), `rules.build` for each plan, `score_against` and the scoring.

### UI (`dashboard/transfer-planner.ts`)

- The chips and the remove buttons (with aria-labels) render through `esc` (`:150-160`).
- The steering fieldset (`:163-181`):
  - "Must buy" is a search box over a datalist, with a By-GW select;
  - "Must sell" and "Never sell" list owned players only;
  - adding is disabled at 5.
- The cost line has three states, "Costs X points", "Same as" and "X more", all escaped (`:184-191`).
- The card constraint summary is escaped (`:193`). Invalid results show the title "Constraints not accepted" (`:223`).
- The Node test asserts everything is escaped.
- **The "usable after the first Suggest plans" limitation is acceptable.**
  - The panel says so plainly.
  - Passing the catalog at mount would need `app.ts`, which is outside the allowed paths.
  - Picker data is public catalog data.

### Real run

`python -m fpl_brief.optimise own --force-in 268 --keep 165` gives:
- state ready, with constraints "Must buy King by GW6" and "Never sell João Pedro";
- unconstrained best +16.05 (Cherki → Saka; João Pedro → Barry);
- Plan 1: Cherki → Saka; Rogers → King. Gain +12.24, `cost_vs_unconstrained` −3.81;
- Plan 2: Gibbs-White → Saka; Cherki → King. Gain +11.88, cost −4.17;
- Plan 3: Cherki → Mbeumo; Rogers → King. Gain +11.35, cost −4.70.

These match the report exactly. A bad `--keep x` exits with an argparse error.

### The Haaland sale in GW8 is genuine

- Plan 1 of (a) sells King → B.Fernandes and Haaland → Brobbey in GW8. Planner score 248.12, gain +12.24.
- Re-solving (a) with Haaland (411) also on the never-sell list gives:
  - planner score 247.786, gain +12.15, the same hold;
  - a different later path: Gibbs-White → Mbeumo in GW7, Calvert-Lewin → Brobbey in GW8, Suzuki → Trafford in GW9.
- So keeping Haaland is feasible and scores 0.33 lower. The solver's choice is optimal, not a side effect of the constraints.
- The encoding touches no bound but those of 268 and 165 (`:309-318`).
- The free run's own plan 3 in (b) also sells Haaland.
- The gap is under 0.1 estimated points, so it is a near-tie. The manager should read it as indicative, which the cards already say about moves after GW6.

### Scope

- Changed files are within the allowed paths, and nothing is committed (`git status`: 10 modified files, no new tracked files, HEAD 3f533b7).
- The `ops/TASK.md` diff includes the Supervisor's new task text, which predates review. The Programmer's change is the status line.
- The build output went to the untracked or ignored `dist`.

## Tests (full run, once, by the reviewer)

| Command | Result |
|---|---|
| `python -m unittest discover -s tests` | **323 tests OK** |
| `npm run typecheck --prefix dashboard` | OK |
| `npm run build --prefix dashboard` | OK |
| `node --test tests/*.mjs` | **21 pass, 0 fail** |

## Blocking

None.

## Optional

1. **Relaxed-hold test.** Add a test where the steered main model needs the flagged-out XI relaxation but the free run doesn't. It should assert that the hold is still the strict one (`optimise.py:432`).
2. **Pool difference.**
   - Adding a forced-in player first removes him from the market list (`:165-168`). If he would have been in the top N, the steered pool gains one extra player beyond the free pool.
   - The steered run can then occasionally beat the free best, which is what the "more estimated points" line covers.
   - A comment would help the next reader.
3. **Naming.** `cost_vs_unconstrained` is negative when the plan costs points: it is gain minus best. The UI shows the absolute value, so this only affects API readers. Consider renaming it to `gain_vs_unconstrained`, or documenting the sign in the README.
4. **Wasted re-solve.** If the cached free result is ready but has no plans, `best_of` returns None and `build` re-solves the free run (`optimise.py:619-624`). This is rare and harmless, but it wastes about 20 s.
5. **Cache key normalisation.** It isn't normalised for the default GW (`268` versus `268@6`). This is a known limitation and costs only an extra solve.
