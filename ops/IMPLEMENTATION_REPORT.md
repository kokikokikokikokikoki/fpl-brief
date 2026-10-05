# Implementation report: Stage 5, price awareness

**Programmer:** Opus 5.5 subagent (medium effort) · **Date:** 2026-10-05 · **Status handed off:** IN_REVIEW · Not committed.

## Changed paths

- `fetch_fpl.py`: the catalog whitelist moved into `CATALOG_FIELDS` plus `catalog_players(boot)`, so it can be tested. It now includes the five `price_change_*` fields. No other fetcher change.
- `fpl_brief/prices.py` (new, pure functions):
  - `selling_price`, `outlook`, `marker`, `updates_before`, `buy_note`, `sell_note`, `early_move_notes` and `squad_view`;
  - constants `GUIDE`, `THRESHOLD = 100`, `ITB_VALUE = 0.08` (the same value as `optimise.ITB_VALUE`) and `UPDATE_HOUR_UTC = 1`.
- `fpl_brief/candidates.py`:
  - each candidate gets `price_outlook` (direction, update, likelihood, calibrating, label, before_deadline and a buy note);
  - `outgoing.price_outlook` carries a sell note;
  - there is a new `price_method` text, and the ranking is unchanged.
- `fpl_brief/plan.py`: `summary.price_notes` comes from `prices.early_move_notes`. The other summary numbers are unchanged.
- `fpl_brief/optimise.py`: `price_notes` per plan is copied from the rule checker's summary for the next-GW moves. It is a note only and isn't in the objective.
- `fpl_brief/rivals.py`, `dashboard/rival-maths.ts`: text only. Rivals' title odds are calibrated only against the manager, and the vice-captain isn't modelled because the draws never model a captain playing 0 minutes.
- `dashboard.py`: `/api/dashboard` adds `"prices": prices.squad_view(snapshot, catalog, private)`, behind the same private gate. When account data is disabled or not usable, it serves public prices only.
- `dashboard/prices.ts` (new) has `priceMarker` and `renderPricesStrip`. `dashboard/prices.css` is new.
- `dashboard/app.ts`:
  - the Prices strip (a collapsible panel) sits in the Lineup ("My squad") view, after the lineup list;
  - the type gains `prices?: PricesData`;
  - the runtime gains `priceMarker`, passed to desk-tools so that module keeps no runtime imports, which the vm-based tests need.
- `dashboard/desk-tools.ts`: the Candidate lens shows a ▲/▼ marker plus any note in the Price cell. "Steady" is hidden there to keep the table clean. The outgoing player's sell note and the price method line are also shown.
- `dashboard/transfer-plan.ts`, `dashboard/transfer-planner.ts`: escaped `price_notes` lists in the planned-transfers strip and the planner cards. The helper is local to each module, which keeps them free of runtime imports for the node tests.
- `tests/test_prices.py` (new, 20 tests), `tests/test_prices.mjs` (new, 5 tests), and `tests/test_dashboard.py` (the `/api/dashboard` missing-account test now checks that prices are public only).
- `README.md`: one Prices bullet.
- `ops/TASK.md`: status line only.
- Running the fetcher once (allowed) also rewrote `data/catalog.json`, `latest.json`, `changes.json`, `player_history.json`, `workflow_status.json` and `digest.md`.

## Field names and shapes (live `bootstrap-static`, 2026-10-05)

All 667 elements carry these fields:

- **`price_change_percent`:** a **decimal string**, for example `"100.1"` or `"-53.2"`.
- **`price_change_hourly_rate`:** an int, which can be negative.
- **`price_change_projections`:** a list of 3 objects `{offset: 0|1|2, projected_percent: "<decimal string>", likelihood: int}`. The likelihood was seen from −5 to +5, and it is negative for falls.
- **`price_change_locked_until`:** null for everyone today.
- **`price_change_calibrating`:** false for everyone today.

`game_settings.transfers_sell_on_fee = 0.5`.

## Behaviour

- **`selling_price(bought, now)`:** `bought + (now − bought)//2` if `now > bought`, else `now`.
- **`outlook` direction:**
  - `rise` or `fall` when the current percent is beyond ±100. This is expected at update 1, the next overnight update.
  - Otherwise, the first projection beyond ±100 sets the direction, at update `offset + 1`.
  - Otherwise `steady`. If there are no usable fields at all, `unknown`.
  - It returns the likelihood, `calibrating`, `locked_until`, a `next_change` text, and a label that always ends "FPL's own predictor, a guide only."
- **Early-move note:** a buy predicted to rise, or a sell predicted to fall, whose expected update number is within the number of overnight updates before the deadline.
  - That count is approximated as daily updates at 01:00 UTC.
  - A `locked_until` at or after the deadline suppresses the note.
  - A sell note is skipped when the fall wouldn't change that manager's selling price, which happens when the drop only eats unrealised half-profit.
  - Value: £0.1m × `itb_value` = 0.008, shown as "about 0.01 points". It is text only.
- **Squad view:**
  - **With usable account data:** per player, the current, purchase and account selling price, the formula selling price, the profit locked in, `if_rise`, `if_fall`, `rise_earns_nothing`, and the outlook with `before_deadline`. Totals are included, plus a formula-vs-account cross-check.
  - **Without usable data:** public current prices and the outlook only, plus "Selling prices need a fresh capture of your FPL account; public prices only." and the private-team message.

## Real-data numbers

These use `now = 2026-10-05T07:45Z` (account captured 04:54Z, state ready, bank £0.1m), the next deadline GW6 2026-10-10T10:00Z, and 5 overnight updates before the deadline.

**The manager's 15:**

| Player | Now | Bought | Sell | Outlook |
| --- | --- | --- | --- | --- |
| Suzuki | 5.0 | 5.0 | 5.0 | steady |
| Hall | 5.3 | 5.1 | 5.2 | steady |
| Gvardiol | 5.7 | 5.6 | 5.6 | steady |
| Van Hecke | 4.9 | 4.9 | 4.9 | steady |
| Calafiori | 5.8 | 5.5 | 5.6 | **rise at the next update, likelihood 5** |
| Gibbs-White | 8.0 | 7.9 | 7.9 | steady |
| Szoboszlai | 6.9 | 7.0 | 6.9 | steady |
| Cherki | 7.8 | 7.7 | 7.7 | steady (−57.6%) |
| Rogers | 7.7 | 7.6 | 7.6 | **rise at update 3, likelihood 5** |
| Haaland | 15.6 | 15.5 | 15.5 | steady |
| Calvert-Lewin | 6.0 | 6.0 | 6.0 | steady |
| Dubravka | 4.0 | 4.0 | 4.0 | steady |
| João Pedro | 7.7 | 7.7 | 7.7 | steady (−2.3%) |
| De Cuyper | 5.0 | 4.5 | 4.7 | steady |
| Groß | 5.9 | 5.5 | 5.7 | steady |

- Selling value is £100.0m and the profit locked in is +£0.5m.
- **Cross-check:** 15 of 15 account selling prices match the formula at today's prices, with 0 mismatches.

**Outlooks:**

| Player | Percent | Outlook |
| --- | --- | --- |
| Saka (£9.5m) | 100.1% | **rise at the next update, likelihood 5** |
| Barry (£5.7m) | 0.7% | steady |
| Kostoulas (£5.6m) | 24.3% | steady |
| Brobbey (£5.7m) | 84.9% | steady |
| Mbeumo (£7.9m) | −79.7% | steady |
| Haaland (£15.6m) | 24.9% | steady |
| Groß (£5.9m) | 1.9% | steady |

**Planner GW6 moves:**
- `plan.build` with Cherki→Saka and João Pedro→Barry gives one note: "Early-move note: Saka is predicted to rise before the deadline (FPL's own predictor, a guide only). Buying earlier could save £0.1m, about 0.01 points; a note, not a reason to move." There is no sell note, because neither Cherki nor João Pedro is predicted to fall.
- Planner (own model) top 3 are unchanged by prices:
  1. Cherki→Saka; João Pedro→Barry (+16.05), with the Saka note.
  2. Cherki→Saka; João Pedro→Kostoulas (+15.65), with the Saka note.
  3. Cherki→Mbeumo; João Pedro→Barry (+15.25), no notes.
- The Prices panel was checked rendering in the Browser pane on the local dashboard.

## Tests

| Command | Result |
| --- | --- |
| `python -m unittest discover -s tests` | 309 tests OK |
| `npm run typecheck --prefix dashboard` | OK |
| `npm run build --prefix dashboard` | OK |
| `node --test tests/*.mjs` | 19 pass, 0 fail |

**First-run fixes:** two older vm-based desk-tools tests failed until desk-tools stopped importing `prices.ts` at runtime, and one test expectation was fixed. All three were then re-run on their own and passed.

## Limitations

- **Update timing is approximate.** The count of updates before the deadline assumes one daily update around 01:00 UTC. The offset-to-update mapping assumes offset 0 is the next update, which is consistent with the live data (Saka: current 100.1, offset 0 at 101.2).
- **Likelihood is shown as FPL's raw integer score.** Its scale isn't documented.
- **The cross-check compares account selling prices with the formula at *current* prices.** A price change after capture would show as a mismatch. The note says so and the account value is shown.
- **`data/catalog.json` grew from about 446 KB to about 831 KB.** It is pretty-printed, and every player now has a 3-item projections list.
- **Calibrating and locked behaviour isn't exercised by today's data.** All players are `false`/`null` there; both are covered by unit tests.

## Deviations

- **Sell notes are skipped when the predicted fall wouldn't change that manager's selling price.** This avoids a misleading "£0.1m" note.
- **The Candidate lens hides the "steady" marker.** Only ▲/▼/? show; the Prices strip shows all states.
- **The note helper is duplicated in `transfer-plan.ts` and `transfer-planner.ts`.** Neither imports `prices.ts` at runtime, because the vm-based node tests can't resolve imports.

## Open questions

- Is the catalog size increase acceptable, or should projections be stored more compactly (for example without `offset`)? A change to the JSON formatting is outside this task's paths.
- Should the account-data cross-check use the capture-time price instead? The capture doesn't record `now_cost`.

## Post-review polish

- Fixed the "fPL's" typo in the `squad_view` method text (`fpl_brief/prices.py`); the method text now also says the number of price updates before the deadline is approximate (one overnight update a day assumed).
- The cross-check note now says selling prices "were not checked" when nothing was compared, instead of claiming they match. Added `test_cross_check_note_says_not_checked_when_nothing_compared` in `tests/test_prices.py`.
- Optional items 4 to 6 were left as they were.
