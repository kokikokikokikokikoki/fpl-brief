# Active task — Stage 1 projections: six-gameweek expected points from `ep_next` and fixtures

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
