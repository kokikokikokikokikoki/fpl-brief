# Programmer implementation report

**Task:** Matchday — live gameweek, live mini-league, points left on the table (ops/TASK.md)
**Date:** 2026-09-26
**Status:** APPROVED

## Changed paths

- `fpl_brief/matchday.py` (new)
- `dashboard.py` (import, `MATCHDAY_GET`, `GET /api/matchday`)
- `dashboard/matchday.ts`, `dashboard/matchday.css` (new)
- `dashboard/app.ts`, `dashboard/index.html` (view, nav, lazy load, 60 s live refresh)
- `tests/test_matchday.py` (new, 22 tests)
- `README.md`, `DESIGN.md`, `ops/TASK.md`

## Behaviour

- **Endpoint.** `GET /api/matchday` sits behind the existing gate: sign-in when a password is set, and localhost-only Host on loopback. It reads public FPL endpoints only: `bootstrap-static`, `fixtures?event`, `event/{gw}/live`, `entry/{id}/event/{gw}/picks` and `entry/{id}/history`. It never uses credentials, never writes, and never touches `local/`.
- **Scoring (`score_picks`).**
  - Live points plus provisional bonus. Bonus is projected from fixture BPS with FPL tie rules, only for started fixtures that aren't `finished` and have no `bonus` stat yet.
  - Projected auto-subs, only for starters whose team fixtures are all done and who played 0 minutes:
    - bench order is respected, and a keeper is only replaced by a keeper;
    - the formation must stay legal;
    - a bench player still to play blocks further projection.
  - The vice takes the armband when the captain is done on 0 minutes.
  - Triple Captain ×3; Bench Boost counts all 15 with no subs.
  - Checked against real GW5: this computes 54, FPL's official points.
- **League table.** Covers you plus the snapshot's compared rivals.
  - The total before the GW is `total_points − points + event_transfers_cost` (verified on a real entry with a −4 hit: 221 + 97 − 4 = 314). The live total is that plus the live GW points minus hits.
  - Tied players share a rank; movement is measured against the pre-GW order.
- **Swings.** `points × (your multiplier − rivals' mean multiplier)`, top 5 each way. Players on your bench are labelled "on your bench".
- **Season hindsight.** For each finished, data-checked GW that the manager played:
  - the official points against the best legal XI plus best captain from the same 15 (chip-aware);
  - the armband cost, capped at the total left, with the rest counted as lineup cost;
  - bench points against the average of the rivals' `points_on_bench`.
- **Caching.** A bounded in-memory TTL cache (256 keys, evicting the oldest quarter).
  - Timings: live data 60 s, picks 1 h, bootstrap 5 min, history 30 min.
  - Finished GW live feeds are fetched uncached (`ttl=0`) and only `{points, minutes, bonus}` per player is kept, for 7 days.
  - Failures are never cached.
- **Fetching and failure handling.**
  - Up to 8 parallel fetches, with a 12 s timeout and one retry for 429/5xx/network errors.
  - A failure fetching a rival or a GW becomes a warning.
  - A failure on bootstrap or your own picks, or an unexpected payload, becomes `state: unavailable` (the endpoint wraps any exception).
- **UI.** A Matchday view in the Tactics Board world.
  - Header: a status chip (Kick-off soon / Live / Provisional / Final) and your GW points, average, highest, league place and matches played.
  - Board: points on the shirts, the armband, auto-sub notes and projected bonus, with a bench tray.
  - Coach's notes: the live league table and swing players.
  - Below: the "Points left on the table" ledger with its big number, the cost split, the worst-week callout and per-GW hatched bars.
  - Data is fetched lazily when the view opens. It refreshes every minute only while the status is live, the view is open and the tab is visible. All values are escaped.

## Real data (GW5, manager 6572775)

- **This week:** 54 points (average 48, highest 126), 3rd of 10 compared.
- **Season:** 62 points left on the table (20 from the armband, 42 from the lineup).
- **Worst week:** GW5, 25 short, with 20 on the bench (Groß 14).
- **Bench points:** 53 against a rival average of 43.9.

## Tests

- `python -m unittest discover -s tests`: 196 OK.
- `npm run typecheck --prefix dashboard`: OK.
- `npm run build --prefix dashboard`: OK.
- `node --test tests/*.mjs`: 10 pass.
- Checked in the browser at desktop and 375 px widths. There was no horizontal overflow.

## Limitations

- **League scope.** The live table covers the compared rivals, not the whole mini-league. That keeps it to about 17 FPL calls per minute at most, and the table says so.
- **Unconfirmed values.** Auto-subs and bonus are projections until FPL confirms them. Mid-gameweek, a bench player whose match is still to come blocks further sub projection, as FPL itself would wait.
- **Hindsight rules.** Hindsight ignores the vice rule and treats the best scorer as the captain. It is labelled as hindsight, not a skill score.
- **First load.** The first hosted load makes about 45 FPL requests (about 1 s locally). Repeat loads use the cache.
