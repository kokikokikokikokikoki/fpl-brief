# Programmer implementation report

**Task:** Stage 3 — multi-week transfer optimiser (integer linear program) (ops/TASK.md)
**Date:** 2026-10-05
**Status:** IN_REVIEW
**Programmer:** Opus 5.5 subagent, medium effort

## Changed paths

- `fpl_brief/optimise.py` (new): the ILP (`formulate`), the solver loop with the hold baseline and "not this exact set of transfers" cuts (`solve`), the pool rule (`select_pool`), the account/projection wiring and `plan.build` check (`build`), `method_text`, and a manual CLI (`python -m fpl_brief.optimise [own|fpl]`, read-only).
- `dashboard.py`: `GET /api/optimise?model=own|fpl` (`Handler.optimise`), `OPTIMISE_CACHE` / `OPTIMISE_LOCK`.
- `dashboard/transfer-planner.ts` (new): `renderPlanner` (pure, escaped) and `mountPlanner`; `dashboard/transfer-planner.css` (new).
- `dashboard/app.ts`: `replacePlan` (replaces the browser-local planned-transfers strip with the plan's next-GW moves), `mountPlanner` on the runtime, imports of the planner module and CSS.
- `dashboard/desk-tools.ts`: the Candidate lens view appends the planner panel through `runtime.mountPlanner` (kept import-free so the existing vm test of this file still loads it).
- `requirements.txt`: `highspy>=1.15`, comments updated.
- `tests/test_optimise.py` (new, 14 tests), `tests/test_dashboard.py` (`OptimiseEndpointTests`, 5 tests), `tests/test_transfer_planner.mjs` (new, 2 tests).
- `README.md` (planner paragraph); `ops/TASK.md` (status line only).

`Dockerfile` is unchanged: `pip install -r requirements.txt` already installs the new dependency. Its comment "the runtime is standard-library Python only" (line 1) is now inaccurate; it was out of scope to edit because the build does not need it. No fetcher run, no data or `local/` files changed, nothing committed.

## Model formulation (`fpl_brief/optimise.py`, `formulate`)

Built as column/row lists and passed to HiGHS through its low-level API (`addVars`, `addRow`), not the Python expression API, so building is fast and the order is fixed.

**Variables** (pool player p, horizon week w):
- binary `squad`, `lineup`, `captain`, `vice`, `in`, `out`, and `bench[p,w,o]`, where o = 0 exists only for GKs and o = 1–3 only for outfield players;
- per week: `itb[w]` (continuous, tenths of £m), `fts[w]` (integer 1–5; `fts[0]` fixed to the account value), `hits[w]` (integer), plus two helper binaries for the exact `max` and `clamp`;
- `fts[W]` (the free transfers after the horizon).

**Constraints** (per week):
- squad: 15 players; 2/5/5/3 by position; at most 3 per club (`plan.CLUB_LIMIT`).
- XI: 11 players; GK 1, DEF 3–5, MID 2–5, FWD 1–3.
- captain and vice: one of each per week. `captain + vice ≤ lineup` for every player covers both "in the XI" and "different players".
- bench: exactly one player in each of slots 0–3, with slot 0 GK-only. `lineup + Σ bench = squad` per player.
- continuity: `squad[w] = squad[w−1] + in − out` (week 0 from the owned squad); `in + out ≤ 1`.
- budget: `itb[w] = itb[w−1] + Σ sell·out − Σ now_cost·in`, `itb ≥ 0`, with `itb[−1]` = account bank.
  - `sell` is `private.prices[p].selling_price` for owned players and `now_cost` for everyone else, so players bought inside the horizon sell at the price paid.
  - Owned players can't be bought back once sold (`in` upper bound 0), so the selling-price rule never needs a second price for them.
- hits: `hits = max(0, transfers − fts)`, exactly (big-M with binary z; M = 20).
- FT rollover: `u = fts − transfers + hits` (unused FTs, ≥ 0) and `fts[w+1] = clamp(u + 1, 1, 5)`, exactly (big-M with binary y). If the account reports `unlimited`, week 0 has no hit and the next GW starts from 1.
- `no_transfer_last_gws = 2`: `in`/`out` upper bound 0 in the last two weeks. Week 0 always allows moves, so a 1-GW horizon still works.
- at most `plan.MAX_TRANSFERS` (3) buys per GW, so a next-GW plan always fits the rule checker.
- flagged out next GW: `lineup`, `captain` and `vice` upper bound 0 in week 0.
  - Flagged means status `i`/`s`/`u`/`n`, or chance of playing 0.
  - Later weeks follow the projection.
  - If no legal XI avoids them, the solve is repeated with this relaxed, and a caveat is added. The hold baseline is treated the same way.
- next-GW buys only for players `plan._available` accepts (status `a`, chance None/100). `plan.build` refuses anyone else.

**Objective** (maximise): `Σ_w decay^w · [Σ_p xP[p,w]·(lineup + captain + vice_weight·vice + Σ_o bench_weight[o]·bench[o]) − hit_cost·hits[w] + ft_value·fts[w+1] + itb_value·itb[w]/10]`. The `−1` per week in "banked FTs = fts[w+1] − 1" is a constant and is dropped.

**Defaults** (named constants): decay 0.85; FT value 1.5; bench GK .03 / S1 .25 / S2 .08 / S3 .02; vice 0.05; itb 0.08 per £1m; no transfers in the last 2 GWs; horizon 6; hit cost from the account (`hit_cost`, default 4); 3 plans; 10 s per solve.

**Solver options:**
- set: `random_seed=0`, `threads=1`, `mip_rel_gap=1e-4`, `time_limit=10`, `presolve=off`, `output_flag=False`.
- Presolve is off because its restarts took ~5 s of the ~7.7 s solve on the real own-model data and found the same optimum (267.259). With it off the solve took 2.85 s.
- If a solve reaches the time limit with an incumbent, the plan is marked `time_limit` and a caveat says it is the best found, not proven best.

**Top 3:**
- Solve, then add the cut `Σ_{chosen} x − Σ_{others} x ≤ |chosen| − 1` over all movable `in`/`out` columns, and re-solve on the same HiGHS instance.
- Plans are therefore in non-increasing objective order.
- The hold baseline is the same model with every `in`/`out` fixed to 0.

**Pool rule** (`select_pool`, deterministic, ties broken by player id):
- the manager's 15;
- per position, the top players by decayed horizon xP (`xp_6_decayed`): GK 12, DEF 35, MID 35, FWD 20;
- per position, the best remaining players by `xp_6_decayed / now_cost` with xP > 0: GK 4, DEF 10, MID 10, FWD 6;
- excluded: status `u`/`n`.
- At most 147 players; the real run gave exactly 147.

**Per-plan output:**
- `weeks[]`, each with:
  - `moves` (out → in with names, positions and prices; paired within position, priciest first);
  - `transfers`, `free_transfers`, `hits`, `hit_points` and `bank` (after the week's moves);
  - `squad`, `lineup`, `bench`, `captain`, `vice_captain` and `xi_xp` (XI plus captain).
- totals: `hit_points`; `horizon_xp` (decayed XI + captain − hits); `horizon_xp_undecayed`.
- gains over hold: `gain` (decayed), `gain_undecayed` and `objective_gain`.
- solver details: `objective`, `solve_seconds`, `status`.
- the rules check:
  - `rules_check` is `passed` with plan.py's next-GW net delta, or `no moves next GW`.
  - `next_gw_moves` holds the ids for the board.
- Any plan whose next-GW moves `plan.build` refuses is dropped, with a caveat. None were dropped in tests or the real run.
- top level:
  - `model` and `model_label`, `gameweeks`, `hold`, `plans`, `pool_size`, `settings`;
  - `method` ("optimisation over estimates, not advice", the model, no chips) and `caveats` (the projection's caveats included).

**xP input:** `projection.build(snapshot, catalog, horizon=6, model=…, history=…)`.
- The optimiser defaults to `"own"`.
- If our model is unavailable (no player history), the planner returns `blocked` with "switch to FPL-based".

## Server (`dashboard.py`, `Handler.optimise`)

- **Gate and host:** runs behind the existing `gate` (password) and the loopback rule that refuses `/api/` reads for other Host headers (DNS rebinding). Account data comes from `private_data`, which returns `disabled` (unusable) on a non-loopback bind, so a hosted deploy always answers `blocked`.
- **Order of checks:**
  - bad model → 400 `{"error"}`;
  - no highspy → `{"state":"unavailable","reason":"Planner needs the highspy package"}`;
  - `assess` blocked → `blocked`, "Transfer planner is blocked: …", mirroring the lens's "Candidate Lens is blocked: …";
  - account not `usable` → `blocked` with "The transfer planner needs a fresh capture of your FPL account (selling prices, bank and free transfers). " + the account summary's own message (the same message the lens appends to its blocked text).
- **Cache:** results are cached per `(snapshot generated_at_utc, account captured_at_utc, model)`.
  - It holds 4 entries and evicts the oldest; only `ready` results are cached.
  - Solves run under one lock, because they are CPU-bound.
  - Freshness and usability are checked before the cache, so a stale snapshot or capture is never served from it.
- **Errors:** an unexpected exception returns `unavailable` with a generic message and no traceback.
- **Status codes:** all states return 200 with a `state` field, like `/api/league`; only a bad model returns 400.

## UI

The Candidate lens view gets a "Transfer planner" panel (`.panel`, `.lens-controls`, `.method` and `.evidence-warning`, as the lens uses).

- **Controls:** a model select ("Our model (planner default)" or "FPL-based (ep_next re-weighted)") and a "Suggest plans" button.
- **States:** idle, loading ("can take up to half a minute"), error, blocked, unavailable, infeasible and "no plan".
- **Plan cards:**
  - the gain vs holding (decayed, after hits), hits, horizon estimate and undecayed gain;
  - a week table: GW, moves out → in with prices, FTs, hits, bank after, XI estimate and captain;
  - a time-limit note when it applies.
- **"Try GW6 moves on board":** shown only when the plan has next-GW moves. It replaces the planned-transfers strip with those moves (`replacePlan`, at most 3, all must still match the saved squad) and opens the board, where `/api/plan` re-checks them.
- **Method note:** "Optimisation over estimates, not advice. Model: …. Chips are not included.", followed by the method text and caveats.
- **Escaping:** every dynamic value goes through `esc`.

## Real run: the manager's squad (`local/private_team.json`, read only)

The capture was fresh at run time: 2026-10-05 06:45 UTC, captured 04:54 UTC. It shows 2 free transfers, a £0.1m bank and hit cost 4. The horizon is GW6–11, the pool is 147 players, and the snapshot is GW6 (deadline 2026-10-10). The module was called directly through a scratch script that passes the real `now`.

**Our model (default)**:
- end to end 13.95 s, nearly all of it solving (no plan has next-GW moves, so `plan.build` is not called);
- hold horizon 229.52 (hold solve 0.13 s).

| Plan | Gain vs hold (decayed) | Undecayed | Objective gain | Hits | Solve | Moves |
|---|---|---|---|---|---|---|
| 1 | +7.09 | +12.42 | +4.343 | 0 | 2.73 s | GW6, GW7: roll (FTs 2→3→4). GW8: Cherki £7.7m → Saka £9.5m; João Pedro £7.7m → Brobbey £5.7m. Bank £0.1m → £0.3m. Captain Haaland, Saka from GW8 |
| 2 | +8.57 | +15.17 | +4.094 | 0 | 3.58 s | Plan 1 + GW9 Rogers £7.6m → Mbeumo £7.9m (bank £0.0m) |
| 3 | +4.74 | +9.16 | +4.064 | 0 | 7.40 s | Plan 1's two moves one week later (GW9) |

In all three, the next GW has no moves (`rules_check: no moves next GW`), so the board button is hidden. Plan 2 has a larger xP gain than plan 1 but a lower objective: it gives up a banked FT (worth 1.5 a week, decayed) and £0.3m in the bank.

**FPL-based**:
- end to end 4.00 s, including 3 `plan.build` checks (all passed);
- hold horizon 357.49.

| Plan | Gain | Undecayed | Hits | Solve | GW6 moves (checked by plan.py: net next-GW +11.5) | GW7 moves |
|---|---|---|---|---|---|---|
| 1 | +92.31 | +144.11 | −12 (1 in GW6, 2 in GW7) | 0.80 s | Dubravka £4.0m → A.Becker £5.5m; Calafiori £5.6m → Bogle £4.6m; Szoboszlai £6.9m → Schade £6.2m | Hall → Vuskovic; Gibbs-White → Semenyo; Cherki → Barnes |
| 2 | +92.31 | +144.11 | −12 | 1.54 s | Plan 1, with Cherki → Schade in GW6 and Szoboszlai → Barnes in GW7 | |
| 3 | +92.31 | +144.11 | −12 | 1.23 s | Plan 1, with Gibbs-White → Schade in GW6 and Cherki → Semenyo in GW7 | |

The FPL-based run shows the pitfall the task anticipated:
- `ep_next` (a 30-day form average) is carried across all six weeks, so recent hauls look permanent. Examples: Bogle `ep_next` 11.3 projects 11–17 a week, and Groß projects 10.7–14.0. Our model has Bogle at 3.7–4.7.
- The solver exploits this with six moves and −12 in hits, and a GW7 XI estimate of 126.
- Its three plans differ only in which midfielder leaves in which of the two weeks.

This supports the optimiser defaulting to our model.

## Dependency and deploy

- **Python 3.14 wheels on PyPI** (checked with the PyPI JSON):
  - `highspy 1.15.1` has `cp314-win_amd64` (2.8 MB) and `cp314-manylinux_2_24/2_28_x86_64` (5.0 MB), as well as macOS, aarch64 and musllinux.
  - It requires numpy: `numpy 2.5.3` `cp314-manylinux_2_27/2_28_x86_64` is 16.7 MB.
- **Linux check:** `pip download --only-binary=:all: --platform manylinux_2_28_x86_64 --python-version 3.14 --abi cp314 highspy>=1.15` resolved both wheels, saved in the scratchpad, not the repo.
- **Local install:** `python -m pip install highspy` gave highspy 1.15.1 and numpy 2.4.6 on Windows. Installed size there: highspy 6 MB, numpy 30 MB, numpy.libs 20 MB.
- **Image size:** Docker is not available on this machine (`docker: command not found`), so this is an estimate from the Linux wheels.
  - They unpack to 11.9 MB (highspy) + 56.4 MB (numpy) = **about 68 MB uncompressed**, roughly 22 MB compressed.
  - The `python:3.14-slim` runtime stage is roughly 120–150 MB, so this is a +45–55% increase.
  - The research note's "about 16 MB" counted only the compressed numpy wheel.
- **Build:** pip installs wheels with no compiler step, so build time changes little.
- **Not checked:** the reviewer must run `docker build` (or a Render build) to confirm the image builds and to measure its real size.
- **Without highspy:** `/api/optimise` returns `unavailable`, and every other endpoint and test path is unaffected (tested by patching and by reloading the module with the import blocked).

## Tests

Full command (run once):
- `python -m unittest discover -s tests`: 267 tests OK, 0 skipped (highspy is installed);
- `npm run typecheck --prefix dashboard`: OK;
- `npm run build --prefix dashboard`: OK;
- `node --test tests/*.mjs`: 12 pass.

There is one `ResourceWarning` in the unittest output; it is not from the new tests (checked by running them alone).

Focused re-runs: `python -m unittest discover -s tests -p test_optimise.py` (14 OK) and `-p test_dashboard.py -k Optimise` (5 OK).

New tests:
- `tests/test_optimise.py` (solver and build tests skip cleanly without highspy):
  - known best transfer and its exact decayed gain;
  - budget with selling price (bank 9 can't afford, bank 10 can, bank ends at 0);
  - buy-then-sell inside the horizon at the price paid (bank path 0,0,0,0);
  - the 3-per-club rule;
  - FT rollover (hold path 1,2,3,4,5,5 and 5 after; using 1 of 2 gives 2,2,3);
  - a hit taken only when gain × Σ decay > 4 (1.0/week no, 2.5/week yes);
  - no moves in the last 2 GWs (a late-only asset is bought in GW4);
  - 3 distinct plans in non-increasing objective;
  - a flagged-out player is not in the next GW's XI;
  - every plan's next-GW moves pass `plan.build` on the plan.py fixture, and the doubtful player is never bought next GW;
  - blocked without a fresh account, a fresh snapshot or player history (own), and a bad model raises;
  - the pool is deterministic, keeps owned players and excludes `u`;
  - unavailable when `highspy` is None, and when the import itself fails (module reloaded with `sys.modules["highspy"] = None`).
- `tests/test_dashboard.py` `OptimiseEndpointTests`:
  - ready plus cached (`build` is called once for two identical requests, and again for the other model);
  - the default model is `own` (blocked without history);
  - bad model 400; a foreign Host header 403;
  - unusable account → blocked with the account message;
  - missing highspy → unavailable;
  - a past deadline → "Transfer planner is blocked".
- `tests/test_transfer_planner.mjs` (TypeScript transpile + vm): ready plans render with every dynamic field escaped (names, method, caveats, model label), the board button appears only with next-GW moves, the time-limit note shows, and the idle, loading, error, unavailable, blocked, infeasible and empty states render.

## Limitations

- **Solve times are machine-dependent.** Our model took 2.7–7.4 s per solve here (~14 s per request), against a 10 s limit per solve. On a slower host the second or third plan may stop at the limit; that case is labelled. The result is cached per snapshot, capture and model.
- **"Not this exact set of transfers" allows near-duplicates.** Our model's plan 3 is plan 1 a week later, and the FPL-based plans differ only in which player leaves which week. A stronger cut (for example, distinct next-GW moves) is a possible follow-up.
- **The FT value is counted every week.** `ft_value · fts[w+1]` makes rolling worth 1.5 × the decayed sum of every later week until the FT is used. That is research §3's per-week `FT_gain[w]` read literally. It is conservative: here it rolled GW6 and GW7 and moved twice in GW8. The one-off alternative (value each FT once, or only the end state) is a product choice; see the open questions.
- **Plan order:** plans are ordered by objective (which includes FT, bank, bench and vice values), so plan 2 can show a larger xP gain than plan 1. The card shows both kinds of figure.
- **No chips; deterministic xP.** Variance and price changes are ignored. Players owned now can't be bought back within the horizon.
- **The check covers the next GW only.** plan.py validates the next GW's moves; later weeks rely on the ILP's own constraints, which are the same rules.
- **Not checked in a browser:** the running preview server predates these server changes and belongs to the parent session, so it was not restarted.

## Deviations

- **Transfer cap:** at most 3 buys per GW (`plan.MAX_TRANSFERS`). This keeps every next-GW plan acceptable to plan.py, which caps a plan at 3.
- **Out-flag fallback:** the "flagged out next GW not in the XI" rule falls back to allowing them, with a caveat, when no legal XI exists (for example, both GKs out). Otherwise the hold baseline could be infeasible.
- **Blocked message:** the server's blocked text is "The transfer planner needs a fresh capture of your FPL account (…)" plus the account's own message, rather than the lens's exact "selling price is unavailable" sentence. The lens never fully blocks on unusable data (it falls back to public prices); this mirrors `plan.py`'s wording plus the same account message the lens appends.
- **Mount point:** the planner panel is mounted from `app.ts` through `runtime.mountPlanner`, not imported in `desk-tools.ts`, so the existing vm test of `desk-tools.ts` keeps loading it.

## Supervisor rulings (2026-10-05) and follow-up changes

1. **Banked-FT valuation: kept as is.** `ft_value · fts[w+1]` is counted every week, consistent with FPL-Optimization-Tools.
   - It is a tunable limitation: `settings(ft_value=…)` or `FT_VALUE`.
   - Counting every week makes rolling worth 1.5 × the decayed sum of the later weeks until the FT is used, so the planner rolls readily.
2. **Distinct plans: implemented.**
   - Plan 1 is the overall optimum.
   - After each solve, the cut (`_cut` over `_next_gw_columns`) covers only the next GW's (GW6's) `in`/`out` columns. A plan's GW6 transfer set is excluded, with "no GW6 move" treated as one option. So plans 2 and 3 are the best plans whose GW6 action differs from every earlier plan's.
   - Later-week moves stay free.
   - If fewer distinct GW6 options are feasible, fewer plans are returned.
   - Each plan carries `next_gw_action` ("A → B; …" or "Roll the free transfer (no moves)").
   - Each card is titled "Plan N · GW6: <action>" and shows its gain vs hold.
   - The panel and the method text explain the rule.
3. **Deploy: highspy is kept out of the hosted image.**
   - `highspy` was removed from `requirements.txt`. New `requirements-planner.txt` holds `highspy>=1.15`; the README documents `pip install -r requirements-planner.txt` for local use.
   - The Dockerfile is unchanged, and its "standard-library Python only" comment is true again. The image-size impact above no longer applies to the hosted image.
   - `/api/optimise` keeps returning `{"state":"unavailable","reason":"Planner needs the highspy package"}` there. The panel's unavailable state now reads: "Planner unavailable here. The planner runs on your own computer, next to your account data. Install it with `pip install -r requirements-planner.txt` and use the local dashboard."

Changed in this follow-up:
- code and dependencies: `fpl_brief/optimise.py` (cut, `next_gw_action`, method text, docstring), `dashboard/transfer-planner.ts` (card title, intro line, unavailable text), `requirements.txt`, new `requirements-planner.txt`, `README.md`;
- tests: `tests/test_optimise.py`, `tests/test_transfer_planner.mjs`.

Tests:
- `test_three_distinct_plans` was replaced by `test_plans_differ_in_their_next_gw_action`.
- New `test_rolling_is_one_next_gw_option_and_later_moves_do_not_count`: plan 1 rolls now and buys later, and later plans must act now.
- New `test_fewer_plans_when_fewer_next_gw_options`: with nobody to buy, only 1 plan is returned.
- The build test checks `next_gw_action` and the method text.
- The panel test checks the card titles and the unavailable text.

Re-run:
- focused: `test_optimise.py` 16 OK; panel `.mjs` 2 pass.
- full command once: unittest 269 OK, typecheck OK, build OK, `node --test` 12 pass.

### Real run after the rulings (2026-10-05 06:50 UTC, 2 FTs, £0.1m bank, GW6–11)

**Our model (default):** 15.8 s end to end; holding scores 229.52.

| Plan | GW6 action | Gain vs hold (decayed) | Undecayed | Objective gain | Hits | Solve | Later moves |
|---|---|---|---|---|---|---|---|
| 1 | Roll the free transfer (no moves) | +7.09 | +12.42 | +4.343 | 0 | 2.71 s | GW8: Cherki → Saka; João Pedro → Brobbey |
| 2 | Cherki £7.7m → Saka £9.5m; João Pedro £7.7m → Barry £5.7m (plan.py passed) | +11.27 | +16.18 | +3.178 | 0 | 4.63 s | none |
| 3 | Cherki → Saka; Rogers £7.6m → Mbeumo £7.9m; João Pedro → Barry (plan.py passed) | +10.86 | +17.32 | +2.715 | −4 | 8.13 s | none |

Plans 2 and 3 gain more xP than plan 1 but have lower objectives: they use up the free transfers that plan 1 banks, which the per-week FT value rewards (ruling 1).

**FPL-based:** 3.7 s. GW6 actions:
- plan 1: Dubravka → A.Becker, Calafiori → Bogle, Szoboszlai → Schade;
- plans 2 and 3: the same, with Cherki or Gibbs-White as the third sale instead of Szoboszlai.

Each plan gains +92.31 after −12 in hits, with three more moves in GW7. The ep_next form pitfall is unchanged.

## Open questions for the Supervisor (answered above)

1. **FT valuation:** per-week state value (current) or a one-off value per banked FT? This changes how readily the planner moves now.
2. **Distinct plans:** should "distinct" mean different next-GW moves, so the three cards are more useful?
3. **Hosted planner:** should the hosted (Render) deploy run the planner at all? Account data is local-only, so it always answers `blocked` there, but the image still grows by about 68 MB uncompressed. One option is to keep `highspy` out of `requirements.txt` and in a local-only extra; it is in `requirements.txt` as the task requires.

## Fix round: free-transfer valuation and honest plan ranking (2026-10-05)

This implements the "Stage 3 fix" task (ops/TASK.md) after the review FAIL (ops/REVIEW.md). The new ruling replaces ruling 1.

### Changed paths
- `fpl_brief/optimise.py`: new objective, score breakdown, `most_points`, method text and docstring.
- `dashboard/transfer-planner.ts`, `dashboard/transfer-planner.css`: plan cards and intro.
- `tests/test_optimise.py`, `tests/test_transfer_planner.mjs`.
- `README.md` (planner method text only).
- `ops/TASK.md` (status line).

### Objective (the rest of the ILP is unchanged)
- **Free transfers, valued once:** the per-week `ft_value · fts[w+1]` is removed. Only the FTs carried out of the horizon (`fts[W]`) are valued, once, at the last GW's weight (`0.85^(W−1)`). The values follow the diminishing list `FT_VALUES = {2: 2.0, 3: 1.6, 4: 1.3, 5: 1.1}`; the 1st FT is worth 0.
  - Modelled exactly with continuous `e_k ∈ [0,1]`, k = 2..5, `fts[W] = 1 + Σ e_k` and cost `list[k]·e_k`. The values decrease, so the maximiser fills them in order.
- **Per-transfer threshold:** `MIN_TRANSFER_GAIN = 0.5` decayed points per transfer (cost `−0.85^w · 0.5` on each `in`). It is a named, tunable heuristic (`settings(min_transfer_gain=…)`).
- **Bank:** `itb_value` (0.08 per £1m) applies once, to the end-of-horizon bank `itb[W−1]` only, at the last GW's weight.
- **Settings:** `ft_value` is replaced by `ft_values` (dict) and `min_transfer_gain`.

### Breakdown, ranking and labels
- **Score parts:** `read_plan` computes `score_parts`, the parts of the planner score from the plan's own solution:
  - `points_gain`: decayed XI + captain + vice and bench weights;
  - `hits`, `transfer_penalty`, `ft_value`, `bank_value`.
- **Per plan:** each plan returns `breakdown` (each part minus hold's, rounded to 4 dp) and `objective_gain = Σ breakdown`, exact to 1e-12. Tests also check that the parts reproduce the solver's own objective difference within 0.01.
- **Most points:** `most_points` marks the plan with the largest `gain` (XI + captain after hits, decayed). It is recomputed after any plan is dropped.
- **Cards:** in this order:
  1. a "Most estimated points" badge on that plan;
  2. "Points gain vs holding: +X (XI and captain, decayed estimate, after hits)";
  3. "Planner score vs holding: +Y", listing the parts (points incl. bench and vice weights, hits, per-transfer threshold, free transfers kept at the end, bank kept at the end).
- **Escaping:** all values pass through `esc`.
- **Intro:** "Holding scores X points over the horizon (decayed estimate). Plans are ranked by planner score: points, minus hits and a small per-transfer threshold, plus a one-time value for free transfers and bank kept at the end. … a lower-ranked plan can gain more points." The "best overall" wording is removed from the UI and the method text.
- **Method text:** rewritten to explain the ranking in the same terms.

### Tests
- **New in `tests/test_optimise.py`:**
  - `test_breakdown_sums_to_objective_gain`: parts sum to `objective_gain` within 1e-6, match the solver's objective difference, and exactly one plan is marked most-points.
  - `test_plans_ending_with_equal_free_transfers_rank_by_points`: buying now beats buying a week later when both end with equal FTs.
  - `test_free_transfers_are_valued_once_at_the_end`: hold banks to 4, giving `0.85²·(2.0+1.6+1.3)`. Using one FT costs exactly `0.85²·1.3`, and the transfer threshold is −0.5.
  - `test_min_transfer_gain_blocks_tiny_moves`: a +0.2 move is blocked at 0.5 and made at 0.
- **Updated tests that relied on the per-week FT value:**
  - `test_hit_only_when_it_pays_back`: the threshold is now 4 + 0.5.
  - `test_budget_uses_selling_prices`: the short-budget case now only asserts the unaffordable move isn't made, because a cheaper side move is now worthwhile.
  - The build test also checks that each breakdown sums to `objective_gain`.
- **`tests/test_transfer_planner.mjs`:** both figures and the parts render, escaped; points come before the planner score; exactly one "Most estimated points"; the new intro wording; no "best overall".
- **Full command (once):**

| Check | Result |
|---|---|
| unittest | 273 OK |
| typecheck | OK |
| build | OK |
| `node --test` | 12 pass |

  Focused re-runs: `test_optimise.py` 20 OK; panel test 2 pass.

### Real run after the fix (own model)
Run at 2026-10-05 06:59 UTC with 2 FTs and a £0.1m bank, GW6–11. 15.9 s end to end. Holding scores 229.52 points.

| Plan | GW6 action (plan.py passed) | Points gain vs hold | Planner score vs hold | Breakdown: points / hits / threshold / FTs at end / bank | FTs after | Solve |
|---|---|---|---|---|---|---|
| 1 (most points) | Cherki £7.7m → Saka £9.5m; João Pedro £7.7m → Barry £5.7m | +16.05 (undecayed +24.47) | +13.46 | +16.61 / 0 / −2.09 / −1.06 / +0.01 | 3 | 3.5 s |
| 2 | Cherki → Saka; João Pedro → Kostoulas £5.6m | +15.65 | +13.02 | +16.17 / 0 / −2.09 / −1.06 / +0.01 | 3 | 5.9 s |
| 3 | Cherki → Mbeumo £7.9m; João Pedro → Barry | +15.25 | +12.66 | +15.81 / 0 / −2.09 / −1.06 / +0.01 | 3 | 6.0 s |

- All three continue with one FT a week: GW7 Rogers → Mbeumo (plan 3: → Saka), GW8 Calvert-Lewin → Brobbey, GW9 Suzuki → Trafford. No hits.
- The planner score and the points gain now rank the plans in the same order.
- "Roll the free transfer" is no longer in the top 3. It would rank below these plans on both points and score, because its banked FT is now valued only if carried past GW11.

### Limitations
- **GW6 differences are small:** the three plans differ mostly in the second GW6 purchase (cheap forward options).
- **Heuristic settings:** `MIN_TRANSFER_GAIN` and `FT_VALUES` are heuristics, tunable through `settings`.
- **End-state FT valuation:** because only the end state is valued, a roll's flexibility inside the horizon counts only through the moves the planner itself schedules later.

## Post-review polish

Addresses the "Optional" items in `ops/REVIEW.md`.

- `fpl_brief/optimise.py` `method_text` and `README.md` now say the end-of-horizon free-transfer and bank values are applied "at the last gameweek's weight (decayed)".
- `optimise.settings()` raises `ValueError` if `ft_values` is negative or increasing; new `SettingsTests` in `tests/test_optimise.py`.
- `dashboard/transfer-planner.ts` plan cards show an escaped note "Moves after GW{next} are indicative — re-run the planner each week." (when the horizon has more than one GW); asserted in `tests/test_transfer_planner.mjs`.

Tests: `PYTHONPATH=tests python -m unittest tests.test_optimise tests.test_dashboard` 102 OK (without `PYTHONPATH=tests` the `test_plan` import fails, as before these edits); `npm run typecheck` and `npm run build` clean; `node --test tests/test_transfer_planner.mjs` 2 pass.
