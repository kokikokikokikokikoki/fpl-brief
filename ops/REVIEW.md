# Independent review: Stage 5, price awareness (selling prices and FPL's price-change predictor)

**Date:** 2026-10-05
**Reviewer:** Opus 5.5 subagent, medium effort (did not implement this work)
**Verdict:** **PASS**. The selling-price formula is correct and agrees with the account capture. The outlook mapping is robust to missing or malformed fields. Early-move notes are attached after the fact and never reach the optimiser objective, the candidate ranking or the plan deltas. The UI escapes everything and shows the blocked state without account data. The Stage 4 method text is present in both places. All four test commands pass. Nothing is blocking; there are six optional notes.

## Checks

| Area | Result | Evidence |
| --- | --- | --- |
| `selling_price` | Pass | `fpl_brief/prices.py:21-23`: `bought + (now − bought)//2` if `now > bought`, else `now`, in integer tenths. Tests cover the floor, a fall, a single +0.1 rise earning nothing, and an exhaustive match against AIrsenal's `(now+bought)//2` (`tests/test_prices.py:24-36`). |
| Account cross-check | Pass | `prices.py:183-191, 202-208` compares the formula at today's prices with the account selling price, shows the account value and lists mismatches, with a "recapture" caveat (the Supervisor accepted this). The real-data run reports 15/15 matching. |
| Outlook mapping | Pass | `prices.py:30-56` parses decimal strings or numbers and rejects bool, NaN, inf and junk. Projections need an int offset in 0–2 and a parseable percent, and a non-int likelihood becomes None. `prices.py:58-94`: a percent beyond ±100 means the change is expected at update 1; otherwise the first projection beyond ±100 means update `offset+1`; otherwise steady; with no usable fields, unknown. The calibrating flag must be exactly `True`, and `locked_until` must be a string. My fuzzing (a percent of `'1e999'`, `[1]`, `True` or `'nan'`, a bool or out-of-range offset, a string likelihood, `None` catalogs, and string or non-dict picks) gave `unknown`, or a sane result, and never raised. The label always ends with the guide text. |
| Catalog | Pass | `fetch_fpl.py:223-242` adds the five fields to `CATALOG_FIELDS`; missing fields are stored as null. `data/catalog.json`: all 667 players carry all five fields (percent `'1.7'`, projections are 3 dicts, locked null, calibrating false). The live mapping gives 660 steady, 4 rise and 3 fall. |
| Notes only, never a driver | Pass | `fpl_brief/optimise.py:441,444`: `price_notes` is copied from the rule checker after `solve()` (`optimise.py:427`), so it is not in the objective. `fpl_brief/plan.py:109-111` adds `price_notes` beside the unchanged deltas. `fpl_brief/candidates.py:97-102,117` adds `price_outlook` after the filters, and the sort key (`candidates.py:119`) is unchanged. Tests: plan deltas are identical with and without a riser (`tests/test_prices.py:194-205`), and the candidate order ignores prices (`:226`). |
| Sell-note skip rule | Pass | `prices.py:135` skips the note when `sell(purchase, now) == sell(purchase, now−1)`, so the fall only eats unrealised half-profit (for example, bought 57 and now 60 keeps a selling price of 58). Falls at or below the purchase price always note. With no purchase price, the note is kept, which is conservative. Tested at `test_prices.py:100-105`. |
| Deadline / update count | Pass, with a note | `prices.py:17,97-104` counts daily 01:00 UTC updates (5 for 07:45Z on 5 Oct to the 10 Oct 10:00Z deadline, which I checked by hand). A `locked_until` at or after the deadline suppresses the note (`:107-111`). It is labelled as an approximation in the code, the docstring and the implementation report. The user-facing text says "in about N updates", but does not say the update count is approximate (see Optional 2). |
| UI: Prices strip | Pass | `dashboard/prices.ts:65-84` builds the account table (Bought, Sell, Profit locked in, One more rise/fall, "needs a second rise") and the public table with the `evidence-warning` blocked message. Every value goes through `esc`. Wired after the lineup list in `dashboard/app.ts:422`. `dashboard.py:901` serves `squad_view` behind the existing private gate. `tests/test_dashboard.py:740-743` checks the missing-account state. |
| UI: markers and notes | Pass | `prices.ts:56-63`: ▲/▼ marker, with the label in the escaped title and in visually-hidden text. Candidate lens: `dashboard/desk-tools.ts:260` (marker plus escaped note) and the outgoing note and price method line. Planned strip and planner cards: escaped `price_notes` lists (`dashboard/transfer-plan.ts:69-73,86`, `dashboard/transfer-planner.ts:76-79,90`). Node tests feed `<img onerror>` payloads through each renderer (`tests/test_prices.mjs`). |
| Stage 4 method text | Pass | `fpl_brief/rivals.py:476-477` and `dashboard/rival-maths.ts:74,80` both say the odds are calibrated only against the manager, and that the vice-captain isn't modelled. |
| Harness change | Acceptable | `priceMarker` reaches `desk-tools.ts` through the runtime object (`app.ts:200,686`), so `desk-tools` keeps only a type import. The 12-line `priceNotes` helper is duplicated in `transfer-plan.ts` and `transfer-planner.ts`. No existing `.mjs` test was edited: `git status` shows only the new `tests/test_prices.mjs`, so no existing test was weakened. |
| Scope / constraints | Pass | The changed paths are all on the allowed list: `ops/TASK.md` changes only the status line plus the Supervisor-authored task text, and `data/*` and `digest.md` come from the one permitted fetcher run. `prices.py` uses only `math` and `datetime`. Nothing is committed, and HEAD is still `9227996`. |

## Blocking

None.

## Optional

1. **Typo in the user-facing method text.** `fpl_brief/prices.py:199` lowercases the first letter of `GUIDE`, giving "markers are fPL's own predictor". Use `GUIDE` unchanged, or "markers are FPL's own…".
2. **Label the update count as approximate in the UI.** "before the deadline" (the notes and the "soon" underline) depends on the 01:00 UTC daily-update assumption. Add a short clause to the `squad_view` method and/or `price_method`, for example "update count before the deadline is approximate".
3. **Cross-check note when nothing was checked.** When `checked == 0`, `prices.py:206` still says "Account selling prices match the formula". Say "No prices checked" instead.
4. **Sell note in the Candidate lens.** `candidates.py:99` looks up the purchase price via `account`, which is only set when `replace_id` is in the account prices. Using `usable` would be clearer, although the behaviour is the same for the outgoing player.
5. **`priceMarker` lookup.** `prices.ts:57` uses `direction in MARKS`, which is true for inherited keys such as `"constructor"`. The output is still escaped, so this is harmless. `Object.hasOwn(MARKS, …)` would be tidier. A vm render test of the Candidate lens marker cell would close the one wiring path without a node render check.
6. **Catalog size.** `data/catalog.json` grew from about 446 KB to 831 KB. Most of the growth is the indented `price_change_projections` objects; `fpl_brief/storage.write_atomic` pretty-prints dicts. Compact separators for the catalog, as `player_history.json` already uses, or storing projections as `[percent, likelihood]` tuples, would roughly halve it. The Supervisor accepted it for now.

## Tests (run once by the reviewer)

| Command | Result |
| --- | --- |
| `python -m unittest discover -s tests` | 309 tests OK (30.4 s) |
| `npm run typecheck --prefix dashboard` | OK |
| `npm run build --prefix dashboard` | OK (114.10 kB JS, 47.25 kB CSS) |
| `node --test tests/*.mjs` | 19 pass, 0 fail |

Spot checks I added beyond the suite: fuzzing `outlook` and `squad_view` with malformed and `None` inputs, a by-hand check of the update count, and the catalog field census above.
