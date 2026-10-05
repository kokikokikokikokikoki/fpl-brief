# Programmer implementation report

**Task:** Stage 2 — our own expected-points model, with a backtest (ops/TASK.md)
**Date:** 2026-10-05
**Status:** IN_REVIEW
**Programmer:** Opus 5.5 subagent, medium effort

## Changed paths

- `fpl_brief/xp_model.py` (new): component xP model (minutes, shrinkage, scoring, availability, horizon).
- `fpl_brief/backtest.py` (new): `python -m fpl_brief.backtest [--json]`.
- `fpl_brief/collect.py`: `HISTORY_FIELDS`, `player_rows`, `player_history_doc`, `ep_log_update`; `team_results(..., history=None)` and `collect(client, config, extras=None)`.
- `fetch_fpl.py`: `write_model_data` writes `data/player_history.json` and `data/ep_log.json`; `main` calls it.
- `fpl_brief/projection.py`: `build(..., model="fpl"|"own", history=None)`; the result gains `model` (and `available` for "own").
- `fpl_brief/candidates.py`: `lens(..., history=None)`; candidates and `outgoing` gain `xp_6_own`, `xp_6_own_decayed`, `own_breakdown`, `own_weekly`, `own_flags`, `models_differ`; response gains `projection_own`.
- `fpl_brief/plan.py`: `build(..., history=None)`; `summary.horizon_delta_own` and method text.
- `dashboard.py`: `player_history()` helper; `/api/candidates` and `/api/plan` pass the history file (wiring only).
- `dashboard/desk-tools.ts`: two six-week columns ("FPL-based" and "our model"), sort by either, ≠ flag, exported `ownModelCell` (breakdown in a `<details>` on click and in a `title` on hover, all escaped), method note.
- `dashboard/transfer-plan.ts`: strip shows `horizon_delta_own` next to `horizon_delta`.
- `dashboard/board.css`: three small rules for the breakdown and ≠ flag (Candidate lens only).
- Tests: `tests/test_xp_model.py` (new, 14), `tests/test_backtest.py` (new, 5); extended `tests/test_projection.py` (+1 collector test), `tests/test_fetch_fpl.py` (+1), `tests/test_research_candidates.py` (+1), `tests/test_plan.py` (+1), `tests/test_dashboard.py` (assertions in the existing transfer-plan node script).
- `README.md`, `ops/TASK.md` (status line only).

## Behaviour

**Data.** From the `event/{gw}/live/` responses already fetched for `team_results` (no new endpoints), one row per player with minutes > 0 per gameweek, only for gameweeks whose fixtures have all finished. Confirmed live `stats` field names by one read-only fetch (GW5): `minutes, starts, goals_scored, assists, clean_sheets, goals_conceded, saves, bonus, yellow_cards, red_cards, defensive_contribution, expected_goals, expected_assists, total_points`.
- `defcon_points` is taken from `explain[].stats` points for `defensive_contribution`, because `stats.defensive_contribution` is the raw CBIT/CBIRT count, not points.
- `team` is the player's current club, or `null` if his explain fixtures are not that club's (moved since).
- Extra field `fixtures` = number of matches with minutes (2 in a DGW), used to get per-match minutes.
- Storage is columnar: `{"schema_version", "generated_at_utc", "fields": [...], "rows": [[...], ...]}` with full field names once. A failed live fetch keeps the previous file's rows for that GW and adds a warning.
- `data/ep_log.json`: `{"schema_version": 1, "gameweeks": {"6": {"captured_at_utc", "ep_next": {"<id>": float}}}}`; first capture per GW kept.

**Model** (`xp_model.py`, research §0/§1/§2):
- Minutes: last 4 club gameweeks (club GWs from `team_results`, plus GWs the player appeared), weights 0.8^age; `p_play`, `p_60`, expected minutes per match. A player FPL lists `i`/`s` ignores his current trailing run of missed GWs, so he returns at his pre-absence rate.
- Availability: `u`/`n` → 0 all weeks. `i`/`s` → 0 until the GW implied by news ("back DD Mon" / "until DD Mon" mapped to the first GW kicking off on or after that date, using the snapshot's kickoff times), else from next GW + 2; never before next GW + 1. Otherwise `chance_of_playing_next_round/100` multiplies the next GW only. Each case adds a labelled flag.
- Attack: xG/90 and xA/90 shrunk with k = 900 min to the position × price-band (now_cost edges 5.0/6.5/8.5) mean of this season's pooled data; a band with < 900 pooled minutes falls back to the position mean. Scaled per fixture by Stage 1 `att_mult`.
- Defence: `CS[pos]·p_60·exp(−λ_against)`; GK/DEF `−(E[mins]/90)·E[floor(GC/2)]` by Poisson sum.
- Side points: per-90 rates of defcon points, bonus, card points (−1 yellow, −3 red) and GK save points (floor(saves/3) per match) shrunk with k = 10 matches to the position mean; × E[mins]/90.
- Output per player: `xp` per GW, `xp_6`, `xp_6_decayed`, `breakdown` per GW and `breakdown_total` over `{appearance, goals, assists, clean_sheet, conceded, saves, defcon, bonus, cards}`, `minutes`, `flags`. DGWs sum fixtures; blanks are 0.

**Wiring.** FPL-based stays the default everywhere. `models_differ` is true when |xp_6 − xp_6_own| / horizon GWs > 2. Without a history file, "our model" fields are `null`, `projection_own.available` is false and the UI says so.

## Test command and outcomes

- `python -m unittest discover -s tests`: first full run 242 tests, 2 failures, both float-precision assertions in my new tests (`test_backtest` last-3 equality, `test_xp_model` doubt rounding at 2 dp). Fixed the assertions; focused re-run `tests.test_backtest tests.test_xp_model`: 18 OK. (The other 240 passed in the full run.)
- `npm run typecheck --prefix dashboard`: OK.
- `npm run build --prefix dashboard`: OK.
- `node --test tests/*.mjs`: 10 pass, 0 fail.
- `python -m fpl_brief.backtest`:

```
Backtest over GW3-GW5
Model                       MAE all  rho all  n all  MAE top  rho top  n top
our model                     2.076    0.370    916    2.494    0.401    215
points per game               2.313    0.301    916    2.831    0.342    215
last 3 GWs average            2.351    0.310    916    2.850    0.352    215
FPL ep_next (logged)        (no data for these gameweeks)
top = the 100 most expensive players today; rho = mean per-GW Spearman.
Fitted on earlier gameweeks only. Scored on players who played; availability news is not kept for past GWs, so the backtest runs our model without it. Prices are today's.
```

Per GW (MAE / ρ, all players): GW3 ours 1.957/0.336 vs PPG 2.401/0.231; GW4 2.232/0.339 vs 2.286/0.338; GW5 2.037/0.436 vs 2.250/0.335. Our model wins every GW on MAE and ties or wins on ρ, but this is only 3 GWs (~300 players each).

## Sanity check (live data, horizon GW6–11, 6-GW totals)

| Player | FPL-based (Stage 1) | Our model | Our breakdown (6-GW total) |
|---|---|---|---|
| Haaland (411) | 57.32 | 35.49 | app 12.0, goals 17.13, assists 1.66, bonus 5.64, defcon 0.06, cards −1.02 |
| Groß (124) | 69.47 | 27.99 | app 12.0, goals 7.95, assists 2.87, CS 1.0, defcon 0.96, bonus 4.8, cards −1.62 |
| João Pedro (165) | 18.13 | 17.32 | app 7.59, goals 6.54, assists 0.79, bonus 3.28, cards −0.98 (p_play 0.66) |
| Kostoulas (138) | 47.39 | 25.28 | app 12.0, goals 10.53, assists 0.89, bonus 3.18, cards −1.38 |
| Van Hecke (112) | 45.75 | 20.00 | app 11.5, goals 2.47, assists 0.97, CS 4.93, conceded −3.13, defcon 2.7, bonus 1.66, cards −1.09 |
| De Cuyper (115) | 50.74 | 24.17 | app 12.0, goals 6.82, assists 1.9, CS 4.01, conceded −3.87, defcon 1.98, bonus 2.88, cards −1.5 |

Weekly, our model: João Pedro [2.28, 2.89, 3.16, 3.04, 2.95, 3.0]; Van Hecke [2.18, 3.92, 3.26, 3.84, 3.19, 3.61]. Both carry the flag "Doubt: 75% applied to GW6 only", and only GW6 is reduced. Stage 1 still scales all six weeks by the doubt.

Our model is about 4–6 points per GW for premiums, against 7–14 from the FPL-based numbers (`ep_next` is a 30-day form average). So most premium rows will show ≠.

## Data-file sizes

- `data/player_history.json`: 71,681 bytes for GW1–5 (~300 rows per GW). Projected season end: about 550 KB, under the 2 MB limit.
- `data/ep_log.json`: 6,672 bytes per captured GW. About 250 KB per season.

## Limitations

- The backtest only scores players who played, and it has no historical availability, so all models are scored on players already known to play. Prices are today's, and the 100 most expensive are chosen on today's prices. With 3 GWs and early-season priors (pooled over GW1–2 for GW3), the evidence is thin.
- Model approximations:
  - Clean sheets use full-match P(CS) × p_60.
  - Goals conceded are scaled by expected minutes.
  - Defcon is a linear per-90 rate, not a threshold-hit probability.
  - Saves and bonus are not adjusted for the fixture.
  - Penalties and set pieces are not modelled.
  - DGW minutes are split evenly between the fixtures.
- Players with no recent minutes (new signings, long-term injured with nothing in the last 4 club GWs) project 0 and are flagged.
- A player who changed club uses his current club's gameweeks. His history rows from the old club have `team: null`.
- Parsing return dates from news is a simple regex ("back"/"until"/"return" + "DD Mon"). Anything else falls back to next GW + 2.
- The lens and plan load `data/player_history.json` on each request (~70 KB now).
- Not checked in the browser. The running preview server (started 12:22, before these Python changes) belongs to the main session, and I did not restart it. The UI is covered by typecheck, build and the node render assertions.

## Deviations

- **Storage is columnar, with an extra `fixtures` column.** Key-per-row JSON would be about 4 MB at season end. The extra column lets the model handle double gameweeks.
- **`defcon_points` comes from `explain`, not `stats`.** `stats` only has the raw count.
- **History is kept only for fully finished gameweeks.** This stops a half-played gameweek from looking complete.
- **The fetcher made its network calls twice.** The first `python fetch_fpl.py` run crashed inside `collect` before writing anything: I had shadowed the manager `history` variable, which is now fixed. The second run succeeded. It rewrote `data/latest.json`, `catalog.json`, `changes.json`, `decision.json`, `workflow_status.json` and `digest.md`, and created the two new files. Nothing is committed.
- **`dashboard.py` and `board.css` were edited for wiring and styling only.** Both are within the allowed paths.
