# Implementation report — Planner: force players in or out

**Programmer:** Opus 5.5 subagent (medium effort) · **Date:** 2026-10-05 · **Status handed off:** IN_REVIEW · Not committed; fetcher not run.

## Changed paths

- `fpl_brief/optimise.py`: constraint parsing, validation, encoding, unconstrained-best comparison, picker data, CLI flags.
- `dashboard.py`: `/api/optimise` parses `force_in` / `force_out` / `keep`, puts the constraints in the cache key, caches the unconstrained best, and attaches picker `choices`. `OPTIMISE_CACHE_SIZE` goes from 4 to 8.
- `dashboard/transfer-planner.ts` and `.css`: the steering controls, the chips, the per-card constraint summary and the cost line.
- `tests/test_optimise.py`, `tests/test_dashboard.py`, `tests/test_transfer_planner.mjs`: new tests.
- `README.md`: the planner paragraph.
- `ops/TASK.md`: the status line only.

## How the constraints are encoded (`formulate`, steered run only)

The constraints are variable bounds. No new rows are added.

- **`force_in (p, gw)`:** `squad[p, gw]` has lower bound 1.
- **`force_out (p, gw)`:** `squad[p, gw]` has upper bound 0. A player outside the pool can never be in the squad, so build drops his constraint as already satisfied.
- **`keep p`:** `out[p, w]` has upper bound 0 for every week.

The rest of the model is unchanged: continuity, budget, FTs and hits, the club limit, the frozen last 2 GWs and the 3 transfers per GW. It still decides how and when the moves happen.

- **Pool:** forced-in players always join the pool, through `select_pool(..., extra=...)`, even if their status is outside the normal pool.
- **Hold baseline:** it stays unconstrained, because `formulate` ignores constraints when `hold=True`. If the steered run needed the flagged-out XI relaxation, the hold is still solved strictly first (`run(True, relax and not constraints)`), so it is the same hold as in the free run. Plans add the caveat that the holding baseline ignores the constraints.
- **Unchanged:** the GW6 distinctness cut, the rule check (`plan.build`) and the scoring.

## Validation, `invalid` and `infeasible`

**`parse_constraints`** (shared by the endpoint and the CLI) is strict.
- It accepts ASCII digits only, through `re.fullmatch`, as `ID[@GW]` for force_in/force_out and `ID` for keep.
- Anything else raises `ValueError`.
- The endpoint answers that with **400** `{"state": "invalid", "reason"}`. It does the same when a parameter is repeated.

**`validate_constraints`** returns `{"state": "invalid", "reason"}` (HTTP 400 at the endpoint) when:
- a player id is unknown (the catalog in `build`, the pool in `solve`);
- a by-GW is outside the horizon (the default is the next GW);
- a keep player isn't owned;
- the same player is forced in and out at the same GW;
- the same player is both kept and forced out (an extra check);
- a player is listed twice;
- there are more than 5 constraints in total.

**Infeasible.**
- Before solving, `build` gives a plain reason when a forced-in player:
  - has status u/n ("has left his club or is not eligible");
  - is forced in for the next GW but `plan._available` is false ("flagged doubtful or unavailable for GW6 … pick a later GW"). The rule checker would refuse that buy anyway.
- If the steered model itself is infeasible, the result is `state: "infeasible"`. The reason starts with "Constraints: Must buy … ; Never sell …." and then says that the budget, the 3-per-club limit, the transfers allowed per GW or the frozen last 2 GWs rule them out together, and to remove or loosen one.
- No constraint is ever dropped silently, apart from the force-out no-op described above.
- A HiGHS time limit with no solution now says so, instead of reporting infeasible.

**Unconstrained best.**
- Every ready result carries `unconstrained_best_gain` and `unconstrained_best_action`, taken from plan 1 (the highest planner score) of the free run.
- With constraints, `build` takes `unconstrained_best=` (the server passes the cached free result through `best_of`). Without it, `build` solves the free run itself.
- Each plan gets `cost_vs_unconstrained = gain − unconstrained_best_gain`.
- Every result also carries `constraints`: named rows with the texts "Must buy X by GW6", "Must sell X by GW7" and "Never sell X".

**Server.**
- The cache key is `(snapshot time, capture time, model, constraints_key)`. `constraints_key` doesn't depend on order.
- A steered request first gets the free result from the cache, or solves it and caches it.
- The gate, the loopback/DNS-rebinding check, the blocked/unusable-capture handling and the error fallback are unchanged.

**UI.**
- **Steering controls**, added in a "Steer the plans (optional)" fieldset:
  - "Must buy": a search box over a datalist of all players, plus a "By" GW select whose default is the next GW;
  - "Must sell": owned players, plus a "By" select;
  - "Never sell": owned players.
- **Player list:** it arrives as `choices` with the first planner response, so until then the panel says to run "Suggest plans" once.
- **Chips:** they have remove buttons with aria-labels. Adding is disabled at 5. Constraints apply on the next "Suggest plans".
- **Cards:** each card shows "Constraints: …" and one of these lines:
  - "Costs X points against the unconstrained best (+16.05, Cherki → Saka; João Pedro → Barry)";
  - "Same as the unconstrained best";
  - "X more estimated points than the unconstrained best … which ranks higher on planner score", because plan 1 is chosen by planner score, not by points.
- **Errors:** an `invalid` result shows "Constraints not accepted".
- Everything goes through `esc`.

**CLI.** `python -m fpl_brief.optimise own --force-in 268 --keep 165` works. It also takes `--force-out ID[@GW]`, and each flag can be repeated or comma-separated. It now uses argparse; the model stays positional.

## Real runs (own model, the manager's squad)

- **Data:** the snapshot is from 2026-10-05 07:31Z and the capture from 04:54Z. Both were still fresh at run time (10:45Z), so the real `now` was used and no override was needed.
- **Unconstrained best:** +16.05, Cherki → Saka; João Pedro → Barry. It is unchanged.
- **Gains:** decayed points against holding.
- **Solve time:** each run includes 3 plans plus the hold.

**(a) Keep João Pedro and force in King by GW6.** Ready in 18.8 s.

Plan 1: Cherki → Saka; Rogers → King. Gain **+12.24**, cost **3.81** against the unconstrained best, no hits.

| GW | Moves | Bank after | Captain |
|---|---|---|---|
| GW6 | Cherki → Saka; Rogers → King | 0.4 | Saka |
| GW7 | none | | Haaland |
| GW8 | King → B.Fernandes; Haaland → Brobbey | 3.8 | B.Fernandes |
| GW9 | Szoboszlai → Mbeumo | | |
| GW10–11 | none | | |

Plans 2 and 3:
- Plan 2: Gibbs-White → Saka; Cherki → King. Gain +11.88, cost 4.17.
- Plan 3: Cherki → Mbeumo; Rogers → King. Gain +11.35, cost 4.70.

**(b) Keep João Pedro only.** Ready in 21.9 s.

Plan 1: Cherki → Saka; Rogers → E.Le Fée. Gain **+14.49**, cost **1.56**, no hits.

| GW | Moves |
|---|---|
| GW6 | Cherki → Saka; Rogers → E.Le Fée |
| GW7 | Gibbs-White → Mbeumo |
| GW8 | Calvert-Lewin → Brobbey |
| GW9 | Suzuki → Trafford |
| GW10–11 | none |

Plans 2 and 3:
- Plan 2: Gibbs-White → Saka; Cherki → E.Le Fée. Gain +14.22, cost 1.83.
- Plan 3: Cherki → B.Fernandes; Haaland → Barry. Gain +13.93, cost 2.12.

**(c) Force in King only (next GW = GW6).** Ready in 16.7 s.

Plan 1: Cherki → Saka; Rogers → King. Gain **+13.61**, cost **2.44**, no hits.

| GW | Moves |
|---|---|
| GW6 | Cherki → Saka; Rogers → King |
| GW7 | João Pedro → Brobbey |
| GW8 | King → Mbeumo |
| GW9 | Suzuki → Trafford |
| GW10–11 | none |

Plans 2 and 3:
- Plan 2: Gibbs-White → Saka; Cherki → King. Gain +12.82, cost 3.23.
- Plan 3: Cherki → Mbeumo; Rogers → King. Gain +12.34, cost 3.71.

**Reading:**
- Keeping João Pedro costs about 1.6 points.
- Bringing King in for GW6 costs about 2.4.
- Doing both costs about 3.8.
- In (a) and (c) the planner sells King again in GW8, because "must buy by GW6" only requires him to be in the squad at GW6. See the limitations.

The CLI command from the task, `own --force-in 268 --keep 165`, reproduced (a) exactly.

## Tests

Full run, once:
- `python -m unittest discover -s tests`: **323 tests OK** (310 before, 13 new);
- `npm run typecheck --prefix dashboard`: OK;
- `npm run build --prefix dashboard`: OK;
- `node --test tests/*.mjs`: **21 tests, 21 pass** (2 new).

After a small fix that keeps the hold strict, I re-ran only the focused tests:
- `test_optimise.py`: 32 OK;
- the dashboard Optimise tests: 7 OK.

New Python tests:
- **Forced in:**
  - a forced-in non-upgrade is in the squad by its GW in every plan, and the hold is identical to the free run;
  - the default by-GW is the next GW.
- **Force-out and keep:**
  - keep blocks the free plan's sale of 11;
  - force-out removes 13 at GW1.
- **Infeasible:** an unaffordable force-in with its funders kept gives an infeasible state and a clear reason.
- **Invalid cases:** an unknown id, a GW out of the horizon, a keep player not owned, in-and-out at the same GW, kept and sold, more than 5, and duplicates.
- **Parsing:** strict parsing, including full-width digits, `1@`, `1.5` and `@@`. The order-free cache key.
- **`build`:**
  - the unconstrained best and `cost_vs_unconstrained` are reported;
  - a supplied `unconstrained_best` skips the second solve;
  - `build` validates its input;
  - the doubtful force-in reason;
  - the "Constraints: …" prefix on infeasible.
- **Picker data:** `choices`.
- **CLI:** constraint parsing and a bad `--keep` value.
- **Endpoint:**
  - a steered request is ready, solves twice (free, then steered) and is cached, including in a different query order;
  - the free result comes from the cache;
  - new constraints mean a new key;
  - a keep of a player who isn't owned gives 400 invalid;
  - 7 bad query strings give 400;
  - DNS rebinding with constraints gives 403.

New Node tests:
- chips with remove buttons;
- the query string, including `@` encoded as `%40`;
- the 5 limit;
- owned-only selects;
- player resolution, including ambiguous names;
- the card constraint summary and the cost, same and more lines;
- no lines without constraints;
- the invalid state;
- everything escaped.

## Limitations

- **"Must buy X by GW" is literal.** The player must be in the squad at that GW, and the planner may sell him later, as (a) and (c) show by selling King in GW8. "Never sell" applies only to players owned now. A forced-in player can be held for longer by forcing him in again at a later GW, since force-ins for the same player at different GWs are allowed.
- **Cache keys aren't normalised for the default GW.** `force_in=268` and `force_in=268@6` are different cache keys with the same result, so a cache miss costs one extra solve.
- **The player list needs one run first.** It arrives with the first planner response (`choices`), so the steering controls are inactive until the first "Suggest plans". `app.ts` and `desk-tools.ts` were outside the allowed paths, so the catalog couldn't be passed in at mount.
- **"Must sell" lists owned players only in the UI.** The backend also accepts a non-owned player, meaning "not in the squad at that GW", which blocks buying him.
- **Steered solves take 17–22 s each.** The first steered request after a refresh also solves the free run, about 20 s more, unless it is cached.
- **Generic infeasibility reason.** The infeasibility reason names the binding rule families, but not which single constraint is the binding one. Only the not-buyable checks before solving are specific.
- **No architecture change.** Graphify wasn't updated.
