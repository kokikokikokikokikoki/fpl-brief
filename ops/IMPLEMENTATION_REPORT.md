# Programmer implementation report

**Task:** Stage 1 projections — six-gameweek expected points from `ep_next` and fixtures (ops/TASK.md)
**Date:** 2026-10-05
**Status:** IN_REVIEW
**Programmer:** Opus 5.5 subagent, medium effort

## Changed paths

- `fpl_brief/projection.py` (new): team ratings, fixture multipliers, player projection, best-XI horizon.
- `fpl_brief/collect.py`: `_xg_by_fixture`, `team_results`; the snapshot gains `team_results`.
- `fpl_brief/candidates.py`: `xp_6` / `xp_6_decayed` on each candidate and on `outgoing`, plus a `projection` block and caveats.
- `fpl_brief/plan.py`: `summary.horizon_delta`, `summary.horizon_gameweeks`, and new `method` text.
- `dashboard/desk-tools.ts`: Candidate lens "Next 6 GWs" column, a "Sort by" select, the method line and the outgoing player's 6-GW number.
- `dashboard/transfer-plan.ts`: the planned-transfers strip shows the six-week delta next to the next-GW delta.
- `tests/test_projection.py` (new, 13 tests). Extended: `tests/test_research_candidates.py` (+1 test, plus assertions), `tests/test_plan.py` (+1 test), `tests/test_dashboard.py` (strip assertion in the existing node script).
- `README.md` (Candidate lens, planned transfers, projection method).
- `ops/TASK.md` (status line only).

`dashboard.py` was not changed; the existing endpoints pass the new fields through. The snapshot `schema_version` stays 1, because nothing in the code checks it and the new field is additive. No `data/` or `digest.md` file was written by this work; the uncommitted changes there are the user's earlier session.

## Behaviour

### Collector (`fpl_brief/collect.py`)

- **Rows.** `team_results(client, fixtures, elements, warnings)` builds one row per finished fixture (`finished`, an integer `event`, both scores present): `{gw, fixture_id, home, away, home_goals, away_goals, home_xg, away_xg}`. Rows are sorted by GW, then fixture id.
- **Fetches.** One `event/{gw}/live/` call per GW with finished fixtures. Each player's `stats.expected_goals` is summed to his current club (from `bootstrap-static` elements).
- **Mid-season transfers.** A player whose `explain[].fixture` doesn't include his current club's fixture is skipped, because he played for another club that week.
- **Double gameweeks.** A club with two fixtures in a GW is split by fixture only when `explain[].stats` carries an `expected_goals` identifier. FPL's live data today does not include one; it has only point-scoring identifiers. So in practice that club's xG is `null` for both fixtures, and the model uses goals for those.
- **Failed fetches.** A failed live fetch leaves that GW's xG `null` and adds the warning "Could not collect GW{n} xG; projections use goals for that week: …". It never fails the collection.

### Model (`fpl_brief/projection.py`, pure functions)

- **`team_ratings(results, team_ids)`.**
  - **Model.** Multiplicative `A`, `D` (D > 1 means a leakier defence) and a league home factor `H`: `λ_home = base·A_h·D_a·H` and `λ_away = base·A_a·D_h/H`. `base` is the league average per club per match.
  - **Fit.** 50 rounds. Attack is updated from the current defence, then defence from the new attack. Both are renormalised to mean 1, and then `H` is updated.
  - **Shrinkage.** Every club gets `PRIOR_MATCHES = 6` pseudo-matches at league average (`6·base` pseudo-goals on both numerator and denominator). See the deviations section for the home factor.
  - **Inputs.** xG is used per side where present, goals otherwise. Matches are sorted before fitting, so the result does not depend on input order.
  - **Empty season.** No results gives every rating 1.0, `H = 1`, and `base = DEFAULT_GOALS = 1.4`, with no division by zero.
- **`fixture_view`** returns `λ_for`, `λ_against`, `cs_prob = exp(−λ_against)`, `att_mult = λ_for/base` and `cs_mult = cs_prob/exp(−base)`. The last one is the "same for the defensive side": the clean-sheet chance relative to the league-average clean-sheet chance.
- **`multiplier`** blends them with `ATTACK_WEIGHT` = MID/FWD 0.7 and GK/DEF 0.3. The rest is the clean-sheet weight. The code comment says these weights are heuristics.
- **`project_player`.**
  - **Base.** `ep_base = ep_next / Σ mult(next-GW fixtures)`, then `xP[w] = ep_base · Σ mult(fixtures in w)`. A blank week gives 0 and a double week sums both fixtures.
  - **No fixture next GW.** The base is `form`, scaled by `chance_of_playing_next_round` only when the status is `d`, because `form` carries no availability. The row is flagged.
  - **Unavailable.** A status other than `a`/`d` gives 0 every week, flagged.
  - **Doubtful players are not scaled again**, because `ep_next` already includes availability.
  - **Output.** Per-GW values, `xp_6`, and `xp_6_decayed` (week k weighted `0.85^k`, with k = 0 for the next GW), each rounded to 2 dp.
- **`horizon_gameweeks`** gives the snapshot's stored fixture horizon from `events.next.id` onwards, at most 6 GWs.
- **`build(snapshot, catalog)`** projects every catalog player. It returns `gameweeks`, `ratings`, `ratings_fitted`, `players`, `method` and `caveats`.
  - **Missing `team_results`** (an old snapshot): the caveat says every club is rated average and only the fixture count changes the projection.
  - **No finished matches:** a separate caveat says so.
- **`best_xi_total` / `squad_horizon`.** Each week's best legal XI from the 15 (1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD, no captain), summed with decay.

### Wiring

- **`candidates.lens`.** Every candidate and the `outgoing` player gain `xp_6` and `xp_6_decayed`. The response also carries `projection: {gameweeks, ratings_fitted, method}`, and the projection caveats are appended to `caveats`. The server's default sort is unchanged. `method` now says "Next 6 GWs is an estimate, not a forecast."
- **`plan.build`.** `summary.horizon_delta = squad_horizon(after) − squad_horizon(before) − hit_points`, rounded to 2 dp. `horizon_gameweeks` lists the weeks used. `xi_delta` and `net_delta` are unchanged. `method` describes both numbers, and that the six-week one is an estimate that assumes no captain and no later transfers; it appends the missing-data caveat when relevant.
- **UI.**
  - **Candidate lens.** A "Next 6 GWs" column (the decayed value is in the cell's title) and a "Sort by" select: xGI per 90 (the server order) or Next 6 GWs (estimate), sorted by the decayed total on the client. Changing the sort re-runs the lens if results are already shown.
  - **Notes.** The method line is prefixed "Next 6 GWs:", and the outgoing player's 6-GW estimate is in the budget line. The panel subtitle now says the column is an estimate.
  - **Planned transfers strip:** "+X FPL estimate next GW after hits · +Y over the next N GWs (decayed estimate) · …". It is shown only when `horizon_delta` is a number, so the Cloudflare worker's lens, which has no projection, still renders with "-".
  - **Escaping.** All new output goes through `escapeHtml`/`esc`.

## Tests

The full task command was run once after implementation:

- `python -m unittest discover -s tests`: **220 tests OK** (26.6 s).
- `npm run typecheck --prefix dashboard`: OK, no errors.
- `npm run build --prefix dashboard`: OK (built in 172 ms).
- `node --test tests/*.mjs`: **10/10 pass**.

New tests in `tests/test_projection.py`:

- **Ratings:**
  - an empty season gives all 1.0 and a multiplier of 1;
  - a strong attack against a weak defence beats the reverse, and `cs_prob = exp(−λ_against)`;
  - the fit is deterministic and independent of input order;
  - shrinkage keeps a 5.0-vs-0.1 xG single match at an attack of about 1.1, not about 50×;
  - xG falls back to goals when null, and xG is preferred over goals when present.
- **Projection:**
  - a DGW sums (12 = 2 × 6), and a BGW gives 0;
  - the base is de-fixtured from `ep_next` (week 1 equals `ep_next`, and week 2 equals `ep_next / easy × harder`);
  - decay;
  - an unavailable player gets 0 and is flagged;
  - no fixture next week uses `form` and is flagged;
  - missing `team_results` runs with average ratings and says so;
  - `squad_horizon` takes the best XI each week.
- **Collector:**
  - xG summed by club;
  - a player who moved clubs is skipped;
  - DGW clubs without per-fixture xG get `null` in both fixtures, while the opponent keeps its xG;
  - a failed GW3 live fetch gives `null` xG, keeps the goals, and adds one warning;
  - unfinished fixtures are excluded.
- **Extended:**
  - the lens fields and caveat with no `team_results`;
  - the lens 2-GW projection, including the outgoing player's blank week using `form`;
  - the plan's `horizon_delta` (equals the next-GW delta with one stored week, grows with a DGW, and drops by 4 with a hit), its method text and its missing-data caveat;
  - the strip renders "+6.4 over the next 6 GWs" and stays escaped.

## Sanity checks (real data, read-only)

**With the existing `data/latest.json` and `data/catalog.json`, which have no `team_results`** (all ratings 1.0, GWs 6–11, every club with one fixture per week), each player gets a flat `ep_next` × 6:

- Haaland: 8.0 → xp_6 48.0, decayed 33.22.
- Raya: 6.0 → 36.0, decayed 24.91.
- Saka: 4.0 → 24.0, decayed 16.61.

**A live read-only fetch** of `bootstrap-static/`, `fixtures/` and `event/{1..5}/live/` went through `team_results` in memory. Its output went to the scratchpad only, and `data/` was untouched.

- **Rows.** 50 rows, no warnings, and no null xG (no DGWs so far).
- **League fit.** Base 1.53 goals per club per match, and a home factor of 1.07.
- **Attack.** BHA 1.24, MCI 1.16, SUN 1.16, MUN 1.15, BRE 1.15 at the top; AVL and TOT 0.84 at the bottom.
- **Defence.** ARS 0.77 (best), NFO 0.87, LIV 0.92 and LEE 0.92; NEW 1.13 and BHA 1.11 are the leakiest.

Projections with the fitted ratings (GW6–11):

| Player | ep_next | Weekly xP, GW6–11 | xp_6 | Decayed |
| --- | --- | --- | --- | --- |
| Haaland (MCI) | 8.0 | 8.0, 10.63, 9.94, 10.17, 7.92, 10.66 | 57.32 | 39.33 |
| Raya (ARS) | 6.0 | 6.0, 5.18, 6.3, 4.9, 6.96, 6.08 | 35.42 | 24.29 |
| Saka (ARS) | 4.0 | — | 23.59 | 16.15 |
| Wood (NFO) | 1.0 | — | 5.54 | 3.86 |

- **Haaland:** GW6 is a hard fixture, so later weeks rise.
- **Semenyo (MCI, status `d`):** ep 6.5 gives xp_6 46.58. The doubt in `ep_next` carries through all six weeks; see Limitations.

## Limitations

- **Doubtful players.** A doubt baked into `ep_next` is carried through all six weeks, because the task forbids applying availability twice. A player doubtful only for next week is understated later.
- **The fixture model is simple.**
  - Independent Poisson, no Dixon–Coles correction, and no time decay on old matches.
  - The home factor is league-wide.
  - Position weights are heuristics, to be tuned in Stage 2.
  - `cs_mult` grows quickly for very strong defences, because it is a ratio of clean-sheet probabilities.
- **DGW xG cannot be split** with FPL's current live data, so a DGW club's xG for that week is `null` and goals are used.
- **xG attribution** uses each player's current club. Players who moved and played for their old club that week are skipped, which is safe but loses a little xG from the old club.
- **The six-week squad delta** uses the best XI each week without a captain. It assumes the plan's squad stays for all weeks, with no further transfers and no chips.
- **The Cloudflare worker** (`cloud/shared/decision.mjs`) has its own lens without projections; it is outside the allowed paths. The UI shows "-" there.
- **Not verified in the browser.** The running preview server holds the old Python modules, and the lens needs fresh account data.
- **Graphify.** The graph was not regenerated, because `graphify-out/` is outside the allowed paths. `fpl_brief/projection.py` is a new module the graph does not know about.

## Deviations and decisions

- **Home factor shrinkage.** The home factor is shrunk with the same `6·base` pseudo-goals. Without it, a one-match season put all the scoring into `H` and pushed the home club's attack below 1. The shrinkage test caught this. The task only specified shrinkage for team ratings.
- **The `form` fallback is scaled by `chance_of_playing_next_round` when the status is `d`.** `form` carries no availability, so this is not double counting. Without it, a doubtful player with a blank next week would be projected as fully fit.
- **The server's default candidate order is unchanged.** Sorting by the six-week estimate is a client-side option, so existing ordering tests and the default xGI view stay as they were.

## Post-review fixes

Optional items 1-3 from `ops/REVIEW.md`:

1. `fpl_brief/projection.py`: the `method` text now says a player's current availability doubt (already in `ep_next`) is applied to every projected week.
2. `dashboard/desk-tools.ts`: the Candidate Lens "Next N GWs" column now shows `xp_6_decayed`, the value the sort uses. The header says "(decayed)" and the lens note says "decayed 0.85 per week". The undecayed `xp_6` is in the cell tooltip. Values are still escaped.
3. `dashboard/desk-tools.ts`: the column header, lens note and outgoing-player budget line use `projection.gameweeks.length`, falling back to 6.

No test asserted the old text, so none changed.

Results: `python -m unittest tests.test_projection tests.test_research_candidates tests.test_dashboard` ran 107 tests, OK. `npm run typecheck --prefix dashboard` is clean. `npm run build --prefix dashboard` succeeded.
