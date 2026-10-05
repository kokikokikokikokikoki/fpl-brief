# Active task — Matchday: live gameweek, live mini-league, points left on the table

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

**Status:** IN_REVIEW · **Date:** 2026-09-26 · **Overseer request:** "add the league threats panel", plus each club's next fixtures and long breaks.

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
