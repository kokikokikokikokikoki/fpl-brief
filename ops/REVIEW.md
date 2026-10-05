# Independent review: Stage 3 fix, free-transfer valuation and honest plan ranking

**Date:** 2026-10-05
**Reviewer:** Opus 5.5 subagent, medium effort (did not implement this work)
**Verdict:** **PASS**. Both blocking items from the previous review are resolved. The objective matches the Supervisor ruling exactly, the breakdown reproduces the solver objective, and the cards rank honestly. The earlier PASS items have not regressed. Nothing is blocking; there are four optional notes.

I reviewed the uncommitted diff against HEAD `c3bdcc8`, focusing on the fix: `fpl_brief/optimise.py`, `dashboard/transfer-planner.ts|css`, `tests/test_optimise.py`, `tests/test_transfer_planner.mjs` and `README.md`. I checked it against the active task and ruling in `ops/TASK.md`, the 2026-10-05 FT-valuation row in `ops/DECISIONS.md`, and the "Fix round" in `ops/IMPLEMENTATION_REPORT.md`.

## Objective (against the ruling)

- **No per-week FT term.** The only objective costs are:
  - XI, captain, vice and bench points (`optimise.py:157-162`);
  - `−weight·min_transfer_gain` on each `in` (`:165`);
  - the bank term on `itb[W−1]` only (`:167`);
  - `−weight·hit_cost` on hits (`:168`);
  - the end-FT marginals (`:174-175`).

  The `fts[w]` columns carry no cost (`:170-171`).
- **FTs valued once, only those held after the last GW.**
  - The model adds `fts[W]` (`:171`), set by the same exact clamp rows as every other week (`:220-225`).
  - It enforces `fts[W] = 1 + Σ_{k=2..5} e_k`, with `e_k ∈ [0,1]` continuous and cost `0.85^(W−1)·FT_VALUES[k]` (`:150`, `:174-176`). `FT_VALUES = {2:2.0, 3:1.6, 4:1.3, 5:1.1}` (`:31`), so the 1st FT is worth 0.
- **The linearisation is exact.**
  - `fts[W]` is integer, and the marginal values are positive and non-increasing, so this is a concave piecewise-linear function under maximisation.
  - For any integer `n`, the LP part of the solution fills `e_2…e_n` to 1 and leaves the rest at 0. The value is therefore exactly the list sum.
  - There is no incentive to under-report `fts[W]`: every marginal is positive, and the clamp rows already bound it above.
  - `read_plan` recomputes the value from the list (`:283-284`), and it agrees with the solver objective. See the next point.
- **`MIN_TRANSFER_GAIN = 0.5`** is named and tunable through `settings` (`:33`, `:72`). It applies per purchase at that week's weight (`:165`).
- **Bank value once:** `itb_value/10` at the last GW's weight on `itb[W−1]` only (`:167`, `:285`).
- **The rest of the ILP is unchanged:** the squad, XI, bench, continuity, budget, hit and rollover rows are the same as in the reviewed version (`:178-225`).

## Checks

### Breakdown

- `read_plan` accumulates `points_gain`, `hits`, `transfer_penalty`, `ft_value` and `bank_value` (`:255`, `:274-285`). Each mirrors an objective cost term.
- `score_against` rounds each part to 4 dp and sets `objective_gain = round(Σ parts, 4)` (`:291-294`). The sum check therefore holds to about 1e-12.
- In the real run, `objective_gain` equals the solver's objective difference from hold:

  | Plan | `objective_gain` | Solver difference |
  |---|---|---|
  | 1 | 13.4586 | 13.459 |
  | 2 | 13.0197 | 13.020 |
  | 3 | 12.6586 | 12.659 |

  Hold's `score` 238.681 equals its `objective` 238.681.
- `most_points` goes to the largest `gain`, with ties going to the earlier rank (`:345-348`). It is recomputed after any plan is dropped (`:445-449`).

### Ranking and labels

- **Plan cards** (`transfer-planner.ts:82`), in this order:
  1. the "Most estimated points" badge;
  2. "Points gain vs holding" (large, `.planner-gain strong`, `transfer-planner.css:7`);
  3. "Planner score vs holding" with the labelled parts (`:62-72`).
- **"best overall" is gone:** grep finds no match in the UI, the method text or the README. The panel test asserts it is absent (`tests/test_transfer_planner.mjs:42`).
- **Intro:** it reads "Holding scores X points over the horizon …" and explains the ranking (`:100`).
- **Method text** (`optimise.py:365-380`) and **README** (`README.md:212`) describe the ranking accurately: points, minus hits and the 0.5 threshold, plus one-time end values for FTs (2.0/1.6/1.3/1.1) and bank.
- **Escaping:** every dynamic value goes through `esc`, and the breakdown string is escaped as a whole (`:71`).

### Real run (own model)

I ran `python -m fpl_brief.optimise own`. The CLI uses the current time for `now`, and the result is `ready` in 16.0 s. **Holding scores 229.52**, and holding ends with 5 FTs.

| Plan | GW6 action | `plan.build` | Points gain | Planner score | Points / hits / threshold / FT / bank | FTs after |
|---|---|---|---|---|---|---|
| 1 (most points) | Cherki → Saka; João Pedro → Barry | passed (Δ next GW 0.0) | +16.05 | +13.46 | +16.61 / 0 / −2.09 / −1.06 / +0.01 | 3 |
| 2 | Cherki → Saka; João Pedro → Kostoulas | passed (Δ +3.3) | +15.65 | +13.02 | +16.17 / 0 / −2.09 / −1.06 / +0.01 | 3 |
| 3 | Cherki → Mbeumo; João Pedro → Barry | passed (Δ 0.0) | +15.25 | +12.66 | +15.81 / 0 / −2.09 / −1.06 / +0.01 | 3 |

- All three plans solved to `optimal`. These figures match the implementation report.
- The planner score and the points gain now rank the plans in the same order.
- The FT part checks out: −(1.3 + 1.1) · 0.85⁵ = −1.0649.

### Earlier PASS items

- **ILP rules:** unchanged (see above).
- **Server:** `/api/optimise` still sits after the gate and the loopback Host check (`dashboard.py:870`, `:884`, `:945-946`). It still has the order of checks, cache and lock from the previous review (`:694-721`). `dashboard.py` is not touched by the fix.
- **Dependency:** `highspy>=1.15` is only in `requirements-planner.txt`. `requirements.txt` gained a comment only, and the `Dockerfile` is unchanged.
- **Missing-highspy path:** I re-simulated it with `sys.modules['highspy']=None; sys.modules['numpy']=None`.
  - `import dashboard` succeeds.
  - `optimise.build(...)` and `optimise.solve(...)` both return `{"state":"unavailable", …}`.

### Tests (run once)

| Command | Result |
|---|---|
| `python -m unittest discover -s tests` | 273 tests OK (29.0 s) |
| `npm run typecheck --prefix dashboard` | OK |
| `npm run build --prefix dashboard` | OK |
| `node --test tests/*.mjs` | 12 pass, 0 fail |

The required tests are present in `tests/test_optimise.py`:

| Requirement | Test | Lines |
|---|---|---|
| Parts sum to `objective_gain` and match the solver difference; exactly one most-points plan | breakdown test | `:142-153` |
| Two plans ending with equal FTs rank by points | equal-FT test | `:155-165` |
| One FT held across the horizon is worth exactly its one-time value | one-time FT test (`0.85²·1.3`, threshold −0.5) | `:167-178` |
| `MIN_TRANSFER_GAIN` blocks a +0.2 move | blocking test | `:180-186` |

## Blocking

None.

## Optional

1. **Say that the end values are decayed.** The FT list and bank value are applied at the last GW's weight (0.85⁵ ≈ 0.44), so a kept 2nd FT is worth about 0.89 points, not 2.0. The method text (`optimise.py:373-375`) and README (`:212`) quote "2.0, 1.6, 1.3, 1.1" without saying so. Adding "at the last GW's weight" would make that clear. This is consistent with the ruling, so it is not a correctness issue.
2. **Guard the FT list.** The exact linearisation relies on `ft_values` being non-increasing (`:174-175`). `settings()` accepts any dict, so a caller passing increasing values would get a wrong objective without any warning. A one-line check in `settings()` or `formulate` would make the assumption explicit.
3. **Weekly moves in GW7–9 (noise-chasing).** All three plans use one FT every week:
   - GW7 Rogers → Mbeumo;
   - GW8 Calvert-Lewin → Brobbey;
   - GW9 Suzuki → Trafford (a GK swap).

   Under this objective, a GW9 move needs only about 0.31 (threshold, 0.5·0.85³) + 0.58 (the lost 4th end-FT, 1.3·0.85⁵) ≈ 0.9 decayed points over GW9–11 to pay off. That is well within plausible own-model error between similar players. The guard is reasonable for GW6, which is the only week the UI acts on. The later-week moves are best read as provisional.

   Two possible follow-ups, both tuning decisions for the Supervisor:
   - add a card note that moves after GW6 are indicative;
   - test `MIN_TRANSFER_GAIN` around 1.0.

   Also note that plan 1 and plan 3's GW6 moves have a next-GW `plan.build` delta of 0.0: their value is all in later weeks.
4. **Bench and vice weights in "points".** The `points_gain` breakdown part includes bench and vice weights, while the headline "Points gain" does not (+16.61 vs +16.05 for plan 1). Both are labelled correctly (`transfer-planner.ts:67`, `:82`), so this is only a note in case users ask why the numbers differ.
