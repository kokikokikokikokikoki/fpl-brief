# Programmer implementation report

**Task:** Railway readiness for the Python Travel Dashboard — F1 localStorage draft-load repair
**Date:** 2026-09-23
**Status:** IN_REVIEW

## Changed paths

- `dashboard/app.js`
- `tests/test_dashboard.py`
- `ops/IMPLEMENTATION_REPORT.md`

No cloud, hosting manifest, deployment, service, Git, FPL collector, Research Scout policy, configuration, or unrelated application paths were changed.

## F1 repair

The client load path now validates every stored draft against the current catalog before it becomes `state.data.plans` or reaches wildcard calculations/rendering. A stored draft whose `players` field is null, an object, or any other non-array shape is rejected rather than coerced. Invalid shape, blank/overlong name, target gameweek outside 4–7, non-positive/non-integer IDs, duplicate IDs, and IDs absent from the current catalog are dropped. The four-draft bound remains enforced. If storage is corrupt, missing, or contains no valid records and no valid server template remains, the client uses a safe `hold` template with no player IDs.

`readDrafts` accepts an injected storage object for deterministic testing. The new executable Python regression runs Node against the client normalization function with mocked localStorage and a catalog fixture: mixed malformed and valid records produce only the valid catalog-matching draft, while all-invalid storage produces only the safe hold template. No browser, FPL, or Research Scout network call is made.

## Verification

- `python -m unittest discover -s tests -v` — exit 0; 52 tests passed, including the object/null `players` storage cases. The existing HTTP-error fixture emits its known `ResourceWarning`.
- `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py` — exit 0.
- `node --check dashboard/app.js` — exit 0.
- `node --check dashboard/desk-tools.js` — exit 0.
- Required local smoke command with `PORT=18765` — exit 0; `railway-port-smoke-ok`.
- `git diff --check` — exit 0; only pre-existing LF/CRLF notices.

The task remains `IN_REVIEW` for independent Supervisor review. No commit, push, Railway service creation, deployment, public URL, secret, authentication, cookie, database, upload, schedule, or live collection was performed.

## Hosted-load fix

- `dashboard/index.html` now loads `app.js`, `decision-states.js`, and `desk-tools.js` inside the document with `defer` in deterministic dependency order.
- `dashboard.py` serves static assets with `Cache-Control: public, max-age=300`; dynamic JSON responses retain `Cache-Control: no-store`.
- `tests/test_dashboard.py` adds executable local HTTP coverage for script placement/order and static-vs-API cache headers.

Verification for this bounded fix:

- `python -m unittest discover -s tests -v` — exit 0; 54 tests passed. The existing HTTP-error fixture emits its known `ResourceWarning`.
- `node --check dashboard/app.js` — exit 0.
- `node --check dashboard/decision-states.js` — exit 0.
- `node --check dashboard/desk-tools.js` — exit 0.
- Local injected-port HTTP smoke — exit 0; `railway-port-smoke-ok`.

No FPL/research live calls, Git history changes, remote branch changes, Railway configuration, deployment, or public access changes were made.

## Hosted dashboard loading repair

- `dashboard/decision-states.js` no longer installs a broad self-observing `MutationObserver`; it exposes `window.refreshDecisionStates` and performs one initial feedback pass.
- `dashboard/app.js` invokes the callback once after the normal render DOM update, guarded with optional chaining.
- `tests/test_dashboard.py` adds a focused regression asserting the explicit seam and absence of the observer loop.

Verification:

- `python -m unittest discover -s tests -v` — exit 0; 55 tests passed.
- `node --check dashboard/app.js`, `node --check dashboard/decision-states.js`, and `node --check dashboard/desk-tools.js` — all exit 0.
- Local HTTP smoke on `PORT=18765` — exit 0; `railway-port-smoke-ok`.

Browser verification was independently run after implementation. The focused seam regression plus browser verification, local HTTP, and syntax checks passed. No live FPL/research call, commit, push, or deployment was performed.
## Planner model defaults update

Updated `ops/WORKFLOW.md` with the requested GPT-6 role defaults, cost-aware selection, exceptional Astra use, escalation criteria, rollout availability limitation, and Overseer approval requirement for materially different substitutes. Appended the dated 2026-09-23 decision to `ops/DECISIONS.md`.

Documentation-only change. No tests were required or run. No application code, runtime settings, task/review file, deployment, commit, or push was changed.

## Away-Day Route Map redesign — local handoff

**Date:** 2026-09-23
**Status:** IN_REVIEW

### Changed paths

- `DESIGN.md` — replaced the prior visual direction with the approved Away-Day Route Map design contract.
- `dashboard/index.html` — updated the product heading, added the visual direction contract, loaded the Route Map behavior, and cache-busted `redesign.css` so browsers fetch the current responsive rules.
- `dashboard/redesign.css` — implemented the night-pitch route layout, horizontal-to-vertical route breakpoint, and narrow-screen wrapping/fit rules for the refresh action, warning, panels, and controls.
- `dashboard/wayfinding.js` — added four accessible route stops leading to the existing Rivals, My Squad, Player Pool, and Wildcard views.

### Verification

- `python -m unittest discover -s tests -v` — exit 0; 55 tests passed.
- `node --test tests\*.mjs` — exit 0; 10 tests passed.
- `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py` — exit 0.
- `node --check dashboard\wayfinding.js` and `node --check dashboard\app.js` — both exit 0.
- `git diff --check` — exit 0; no whitespace errors (Git emitted only LF/CRLF notices).
- Local `/` and `/api/dashboard` endpoints — both HTTP 200.
- Fresh isolated browser verification at 360px and 430px — document width matches viewport; refresh action, stale-data warning, and decision panel remain within 16px side gutters. At 900px and 1440px, the layout fits and the route orientation matches the specified breakpoint. Horizontal scrolling is limited to the intentionally scrollable section navigation.
- Independent visual reviewer — PASS at 360px, 430px, 900px, and 1440px; route destinations and keyboard focus also pass.

No live FPL or research collection was triggered. No commit, push, Railway upload/service change/deployment, public URL, secret, database, or schedule was created. Railway remains outside this local task and is not approved for release.

## Research Desk evidence integrity and usefulness — local handoff

**Date:** 2026-09-24
**Status:** IN_REVIEW

### Changed paths

- `fpl_brief/research_scout.py` — joins official FPL player news to stable player/team IDs, prioritizes squad/watchlist players before the bounded excerpt cap, reports omitted entries, and refreshes attempt timestamps after both successful and failed retrievals.
- `fpl_brief/research.py` — validates player attribution and omission metadata; bases freshness on each excerpt/claim timestamp, preventing stale items from appearing ready even when their source was fetched recently.
- `dashboard.py` — includes independently computed FPL snapshot freshness in Research Desk API responses; removed the duplicate trailing helper definition.
- `dashboard/desk-tools.js` — shows attributable player/club labels, capture times for excerpts and claims, item-level stale labels, source/attempt state, truncation counts, and separately labelled research and FPL freshness. Captured text remains explicitly unverified; invalid packet contents are hidden.
- `tests/test_research_scout.py` — covers identity joins, unknown identities, relevant-player ordering, cap omissions, and refreshed attempt timestamps.
- `tests/test_research_candidates.py` — covers empty, failed, stale-retained, mixed-source freshness, and stale excerpt timestamps within a recently fetched source.
- `tests/test_dashboard.py` — covers independent research/snapshot freshness, absent snapshot reporting, and safe rendering of ready/failed/invalid/stale evidence states, including claim timestamps.

### Verification

- `python -m unittest discover -s tests -v` — exit 0; 67 tests passed.
- `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py` — exit 0.
- `node --check dashboard/desk-tools.js` — exit 0.
- `git diff --check` — exit 0; only Git LF/CRLF notices for existing mixed line endings.

### Limitations and boundaries

- Research remains fixed-source, manually triggered, deterministic, and bounded; this work does not add sources, live-news interpretation, forecasts, recommendations, automation, or verified claims.
- Historical captured excerpts remain in the existing local packet until the user triggers another collection; generated `data/` files were not edited by this task.
- No live FPL/research request was made, and no commit, push, service creation, deployment, public URL, secret, database, or schedule was created. Railway remains outside this local task.
- Programmer handoff only; independent review is pending. No approval is claimed.

## Strict TypeScript/Vite dashboard migration — local handoff

**Date:** 2026-09-24
**Status:** IN_REVIEW

### Changed paths

- `dashboard/app.ts`, `dashboard/decision-states.ts`, `dashboard/desk-tools.ts`, and `dashboard/wayfinding.ts` — migrated browser application modules to strict TypeScript with explicit API/data/runtime/DOM types and module dependencies.
- `dashboard/app.js`, `dashboard/decision-states.js`, `dashboard/desk-tools.js`, and `dashboard/wayfinding.js` — removed their legacy application sources after updating imports, build, and tests.
- `dashboard/package.json`, `dashboard/package-lock.json`, `dashboard/tsconfig.json`, and `dashboard/vite.config.ts` — added Vite development/build tooling, strict type checking, and deterministic npm dependencies. TypeScript is pinned to the stable 5.9 compiler API required by the test harness; the initial TypeScript 7 native-preview package lacked `transpileModule` and has been replaced.
- `dashboard/index.html` — loads the TypeScript entry through Vite as an ES module.
- `dashboard.py` — serves `dashboard/dist/` after a build, falling back to the source directory when no built index is present; API behavior is unchanged.
- `.gitignore` — excludes `dashboard/node_modules/` and `dashboard/dist/`.
- `README.md` — documents installation, Python + Vite local development, build, and built-dashboard serving. Deployment remains explicitly blocked pending a separately approved artifact/build-path task.
- `tests/test_dashboard.py` — exercises migrated TypeScript helpers and Research Desk rendering via the stable compiler API, and checks the emitted asset path.
- `tests/test_research_scout.py` — updates the safe-link regression assertion for the typed source variable name.

### Verification

- `npm ci` from `dashboard/` — PASS; 16 packages installed, 0 audit vulnerabilities.
- `npm run typecheck` from `dashboard/` — PASS (`strict: true`).
- `npm run build` from `dashboard/` — PASS; emitted `dashboard/dist/index.html` plus hashed JavaScript and CSS assets.
- `python -m unittest discover -s tests -v` — PASS; 67 tests.
- `node --test tests/*.mjs` — PASS; 10 tests.
- `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py` — PASS.
- Loopback-only Python HTTP smoke after build — PASS: `/`, every emitted JS/CSS asset, `/api/dashboard`, and `/api/research` returned HTTP 200. `/api/candidates` returned its expected safety-blocked HTTP 409 for an intentionally invalid replacement ID; response was valid JSON. No POST refresh or research action was called.
- Browser loaded the locally Python-served production bundle and rendered the overview at the available narrow viewport. Responsive CSS/layout was not changed by this migration; prior Route Map review covered 360, 430, 900, and 1440px.
- `git diff --check` — PASS; only existing line-ending notices.
- Verified `Procfile` and Railway configuration are unchanged.

### Limitations and release boundary

- Python remains the backend/API and production-like static server. Local development uses Python at `127.0.0.1:8765` and Vite at `127.0.0.1:5173`; Vite proxies `/api` to Python.
- The built output is intentionally ignored and absent from a clean deployment checkout. Railway deployment is not approved and cannot serve the bundle until a separate approved task defines its build/artifact path.
- No live FPL refresh, research collection, POST action, commit, push, Railway configuration change, upload, or deployment was performed.
- Programmer handoff only. Independent gpt-6-sol review is pending; no approval is claimed.

### Bounded follow-up — escaped overview content

**Date:** 2026-09-24
**Status:** IN_REVIEW

#### Changed paths

- `dashboard/app.ts` — escaped decision queue titles and text at the overview `innerHTML` boundary. Escaped adjacent API-derived overview values for league rank, points, leader gap/name, deadline gameweek, availability chance, and availability note. The date label is escaped after formatting; fixed CSS class and fixed labels remain constants.
- `tests/test_dashboard.py` — added a deterministic fake-snapshot regression test that runs the TypeScript overview renderer with markup-like FPL name, chance, and news fields. It asserts the values are encoded for text display and that injected `<img>`/`<svg>` markup is absent as active HTML.
- `ops/TASK.md` — transitioned the migration from `CHANGES_REQUESTED` to `IN_PROGRESS`, then to `IN_REVIEW` for this programmer handoff.

#### Verification

- Targeted overview escaping regression — PASS.
- `npm run typecheck` from `dashboard/` — PASS.
- `npm run build` from `dashboard/` — PASS; emitted `dashboard/dist/index.html` and hashed JS/CSS assets.
- `python -m unittest discover -s tests -v` — PASS; 68 tests.
- `node --test tests/*.mjs` — PASS; 10 tests.
- `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py` — PASS.
- `git diff --check` — PASS; Git emitted existing LF/CRLF notices only.

#### Limitations and release boundary

- Overview regression uses a deterministic local fake snapshot and does not contact FPL or trigger refresh/research actions.
- Existing dashboard routes and interactions were not changed. The complete Python and Node suites pass.
- This is programmer handoff only. Independent Supervisor review is pending; no approval is claimed. No commit, push, deployment, or Railway change was performed.

## Accessible squad formation view — local handoff

**Date:** 2026-09-24
**Status:** IN_REVIEW

### Changed paths

- `dashboard/app.ts` — replaced the text-heavy squad tables with the focused formation renderer; no API, server, or other view behavior changed.
- `dashboard/squad-formation.ts` — added typed, escaped pitch/list rendering, positional grouping and snapshot-shape derivation, availability labels, and native toggle behavior.
- `dashboard/squad-formation.css` — added focused pitch and bench styling with narrow-screen wrapping rules using the current visual system.
- `tests/test_dashboard.py` — added deterministic fake-data coverage for shape/grouping, captain labels, bench order, unknown joins, escaped catalog text, empty data, and toggle state.
- `ops/TASK.md` — status transition only, from `READY_FOR_PROGRAMMER` through `IN_PROGRESS` to `IN_REVIEW`.
- `ops/IMPLEMENTATION_REPORT.md` — this programmer handoff.

### Verification

- `npm run typecheck` — PASS.
- `npm run build` — PASS; emitted the built index and hashed JS/CSS assets.
- `python -m unittest discover -s tests -v` — PASS; 69 tests.
- `node --test tests/*.mjs` — PASS; 10 tests.
- `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py` — PASS.
- `git diff --check` — PASS; Git printed only existing LF/CRLF notices.
- Built app visual check — PASS at the available 1265px browser viewport; the pitch and bench render and section navigation remains visible.
- Keyboard check — PASS; Tab reached the native Pitch/List buttons, and Space switched to List and back to Pitch. The accessibility tree reflected the selected `aria-pressed` state and exposed the equivalent semantic table.
- Impeccable mechanical detector — run once on `dashboard/app.ts`, `dashboard/squad-formation.ts`, and `dashboard/squad-formation.css`; exit 0, no findings (`[]`).

### Limitations and release boundary

- The available browser controls did not provide a working viewport override. Exact visual inspection at 360px, 430px, 900px, and 1440px could not be completed; responsive CSS and deterministic behavior were checked, but those four widths remain for independent review.
- The existing Graphify report predates the checkout, and the `graphify` command was unavailable. The graph was not updated because `graphify-out/` is outside this task's allowed paths.
- All squad facts come from the public saved snapshot. Snapshot shape is descriptive only; this view does not advise a lineup or expose unsubmitted intent. No live FPL refresh or research collection was triggered.
- Programmer handoff only. Independent GPT-6 Sol review is required; no approval is claimed. No commit, push, Railway change, upload, or deployment was performed.

### Bounded follow-up — visible Pitch/List fact parity

- `dashboard/squad-formation.ts` now visibly renders price, form, points, and the FPL next-round estimate in each pitch player card. The pitch retains an explicit estimate caveat.
- `dashboard/squad-formation.css` shows the stats in the normal layout and uses a two-column positional row below 400px so the facts have more room on narrow screens.
- `tests/test_dashboard.py` isolates Pitch and List and compares the same fixture players' price, form, points, estimate, position, team, availability, and captain identity. It also verifies that pitch statistics use a visible CSS display rule, and retains bench order, escaping, unknown player, empty state, vice-captain, and toggle checks.

Follow-up verification:

- Targeted formation regression — PASS.
- `npm run typecheck` and `npm run build` — PASS.
- `python -m unittest discover -s tests -v` — PASS; 69 tests.
- `node --test tests/*.mjs` — PASS; 10 tests.
- `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py` — PASS.
- `git diff --check` — PASS; only existing LF/CRLF notices.
- Built Pitch screenshot — visually checked at the available 1265px browser width; price, form, points, estimate, and estimate caveat are visible. Pitch/List keyboard behavior was unchanged from the prior verified handoff.
- Exact-width visual checks at 360px, 430px, 900px, and 1440px — not completed. This browser session has no viewport override; Ctrl+plus/equal did not change the viewport, and F12/Ctrl+Shift+M did not open responsive preview controls. The independent reviewer had reported no document overflow at those four widths, but that measurement was not repeated by this Programmer.

The task returns to `IN_REVIEW`; independent review remains pending. No additional detector run was made because the one-time detector requirement was already fulfilled for the squad UI.

## Team decision and chip status desk — Programmer handoff

**Date:** 2026-09-24
**Status:** IN_REVIEW

### Changed paths

- `fpl_brief/collect.py` — persists the official bootstrap chip-rule definitions from the already fetched response.
- `dashboard.py` — adds read-only team-decision serialization and reconciles official chip windows with recorded manager history. Chip identifiers are validated as official integer IDs; repeated chip windows are counted independently.
- `dashboard/app.ts`, `dashboard/desk-tools.ts`, `dashboard/decision-states.ts`, `dashboard/squad-formation.ts`, `dashboard/styles.css`, and `dashboard/redesign.css` — integrates the decision desk into the existing dashboard and navigation.
- `dashboard/team-decision-desk.ts` and `dashboard/team-decision-desk.css` — renders the squad decision facts, evidence states, and chip ledger.
- `tests/test_dashboard.py` — adds deterministic decision, research-attribution, escaping, stale-data, chip-window, and integer-ID cases; updates the overview test harness for the mounted decision desk.
- `ops/TASK.md` — status transition only; `ops/IMPLEMENTATION_REPORT.md` — this handoff.

### Verification

- `npm run typecheck` — PASS (`strict: true`).
- `npm run build` — PASS; Vite emitted the local production bundle.
- `python -m unittest discover -s tests -v` — PASS; 74 tests.
- `node --test tests/*.mjs` — PASS; 10 tests.
- `python -m py_compile dashboard.py fetch_fpl.py fpl_brief/collect.py` — PASS.
- `git diff --check` — PASS; Git emitted only existing LF/CRLF conversion notices.
- Impeccable mechanical detector run exactly once on the changed TypeScript/UI targets — exit 0; no findings (`[]`).
- Integer chip ID regression uses official IDs 1–8 and the official windows supplied for this season: Wildcard and Free Hit GW2–19/GW20–38; Bench Boost and Triple Captain GW1–19/GW20–38; each window count 1. With manager history WC GW4 and TC GW2, the ledger reports the first WC and TC windows used and their second windows still future. The fixture also checks available current/future counts for Free Hit and Bench Boost.

### Limitations and release boundary

- All tests use saved/fake inputs. No live FPL refresh or Research Desk collection was triggered; the current runtime snapshot’s freshness still governs whether the desk will show usable availability/chip status.
- The Impeccable detector is mechanical, not a visual browser review. No new viewport-by-viewport visual inspection was performed during this closeout.
- This is Programmer handoff only; independent Supervisor review is pending. No commit, push, Railway change, upload, or deployment was performed. Existing unrelated working-tree changes were preserved, and `ops/REVIEW.md` was not edited.

### Bounded follow-up — chip inventory and evidence sufficiency

**Date:** 2026-09-24
**Status:** IN_REVIEW

#### Changed paths

- `dashboard.py` — preserves recognized manager-recorded chip plays and gameweeks when the snapshot is stale or official chip rules are absent; availability remains unknown in those cases. Unrecognized official rule names are surfaced as unknown rows and make the ledger partial instead of silently disappearing. Fresh player rows now require meaningful minutes, numeric form/points, and an upcoming fixture before the no-availability-flag state is used; incomplete rows receive an explicit next step. Numeric FPL strings are accepted as numeric stats.
- `dashboard/app.ts` — types the new decision next-step field and optional used-chip history fields for unknown ledger rows.
- `dashboard/team-decision-desk.ts` — displays a player's next step and shows recorded used gameweeks alongside unknown chip availability.
- `tests/test_dashboard.py` — adds regressions for unfamiliar official chips, stale/missing rule history preservation without availability inference, fresh incomplete player evidence with zero/missing minutes, no fixtures and no research, and complete unflagged player wording.

#### Verification

- `npm run typecheck --prefix dashboard` — PASS.
- `npm run build --prefix dashboard` — PASS.
- `python -m unittest discover -s tests -v` — PASS; 78 tests.
- `node --test tests/*.mjs` — PASS; 10 tests.
- `python -m py_compile dashboard.py fetch_fpl.py fpl_brief/collect.py` — PASS.
- `git diff --check` — PASS; Git emitted only existing line-ending conversion notices.
- Impeccable detector run once on `dashboard/app.ts` and `dashboard/team-decision-desk.ts` — PASS; no findings (`[]`).

#### Limits and release boundary

All regressions use deterministic fixtures. No FPL refresh or Research Desk collection was performed. The Programmer handoff is not approval; independent Supervisor review is pending. No commit, push, deployment, or Railway modification was made. `ops/REVIEW.md` was not edited.

### Bounded follow-up 2 — preserve unknown chips and correct decision summary

**Date:** 2026-09-24
**Status:** IN_REVIEW

#### Changed paths

- `dashboard.py` — stale-snapshot and missing-current-gameweek chip-ledger branches now retain unfamiliar official chip definitions and matching recorded history, with availability left unknown. Invalid/unmatched manager history remains visible as an unknown record.
- `dashboard/team-decision-desk.ts` — decision summary now groups rows by their actual priority category, including insufficient stats/fixture evidence, instead of attributing every non-default row to availability, join, or FPL-note issues.
- `tests/test_dashboard.py` — added regressions for unfamiliar chip/history retention in both early-return branches and summary wording for a complete player join with insufficient stats/fixtures.
- `ops/TASK.md` — active task status transition to `IN_REVIEW` only.
- `ops/IMPLEMENTATION_REPORT.md` — this Programmer handoff.

#### Verification

- `npm run typecheck --prefix dashboard` — PASS.
- `npm run build --prefix dashboard` — PASS.
- `python -m unittest discover -s tests -v` — PASS; 80 tests.
- `node --test tests/*.mjs` — PASS; 10 tests.
- `python -m py_compile dashboard.py fetch_fpl.py fpl_brief/collect.py` — PASS.
- `git diff --check` — PASS; only existing line-ending conversion notices.
- Impeccable detector run once on `dashboard/team-decision-desk.ts` — PASS; no findings (`[]`).

No live FPL refresh or Research Desk collection was performed. No commit, push, deployment, or Railway modification was made. Independent review is pending; `ops/REVIEW.md` was not edited.

### Bounded follow-up 3 — account for official chip rules without names

**Date:** 2026-09-24
**Status:** IN_REVIEW

#### Changed paths

- `dashboard.py` — all uninterpretable official chip definitions are registered for every ledger path. Missing/blank names use `Unrecognized chip (ID N)` for a positive integer ID, or `Unrecognized official chip rule` when the ID is unusable. These rows remain unknown and never expose inferred availability.
- `tests/test_dashboard.py` — deterministic regressions cover blank-name ID 9 rules in fresh, stale, and missing-gameweek ledgers, verify no availability inference, retain explicit unmatched-history rows, and cover the generic label fallback.
- `ops/TASK.md` — bounded follow-up status transition only.

#### Verification

- Focused dashboard tests — PASS (32 tests).
- `python -m unittest discover -s tests -v` — PASS (82 tests).
- `node --test tests/*.mjs` — PASS (10 tests).
- `npm run typecheck --prefix dashboard` — PASS.
- `npm run build --prefix dashboard` — PASS.
- `python -m py_compile dashboard.py fetch_fpl.py fpl_brief/collect.py fpl_brief/research.py fpl_brief/research_scout.py` — PASS.
- `git diff --check` — PASS; only existing LF/CRLF conversion notices.
- Impeccable detector not run; no UI files changed.

#### Limits and release boundary

All tests use deterministic data; no FPL refresh or Research Desk collection occurred. No commit, push, deployment, or Railway change was made. Independent review is pending; `ops/REVIEW.md` was not edited.

### Bounded follow-up 4 — keep malformed official rules distinct

**Date:** 2026-09-24
**Status:** IN_REVIEW

#### Changed paths

- `dashboard.py` — malformed official chip rules without a usable name or ID receive a deterministic, ordinal-based safe label. Distinct rule records therefore remain distinct in fresh, stale, and missing-gameweek ledgers; each remains unknown and cannot make the inventory complete. Recognized and named-unknown chip handling is unchanged.
- `tests/test_dashboard.py` — added a deterministic fixture with two malformed official rules and assertions that both unique rows appear, remain unknown, and expose no availability in fresh, stale, and missing-gameweek branches.
- `ops/TASK.md` — transitioned the active task from `CHANGES_REQUESTED` to `IN_PROGRESS` and back to `IN_REVIEW` for this handoff.

#### Verification

- Focused malformed-rule regression — PASS.
- `npm run typecheck --prefix dashboard` — PASS.
- `npm run build --prefix dashboard` — PASS.
- `python -m unittest discover -s tests -v` — PASS (82 tests).
- `node --test tests/*.mjs` — PASS (10 tests).
- `python -m py_compile dashboard.py fetch_fpl.py fpl_brief/collect.py fpl_brief/research.py fpl_brief/research_scout.py` — PASS.
- `git diff --check` — PASS; Git emitted existing LF/CRLF conversion notices only.
- Impeccable detector not run; no UI files changed.

#### Limits and release boundary

Known chips and named unknown chips retain their prior labels/history behavior. All tests use deterministic local fixtures; no FPL refresh or Research Desk collection occurred. No commit, push, deployment, or Railway change was made. Independent review is pending; `ops/REVIEW.md` was not edited.

## Railway build artifact and clean-checkout readiness — Programmer handoff

**Date:** 2026-09-25
**Status:** IN_REVIEW
**Programmer:** Claude Opus 5.5 (per Overseer handoff; independent subagent review to follow)

### Changed paths

- `dashboard.py`: `serve_static` no longer falls back to the unbuilt `dashboard/` source directory. When `dashboard/dist/index.html` is missing, every non-API path returns `503 text/plain` (no-store) with the build command. `/api/*` is unaffected. The traversal guard now compares against the resolved `STATIC_DIST`, and the static cache header is unchanged. Adds `MISSING_BUNDLE_MESSAGE` and a `send_text` helper.
- `tests/test_dashboard.py`: new `StaticBundleTests` (4 tests) with a patched temporary `STATIC_DIST`:
  - missing bundle returns 503 with the hint for `/`, `/index.html`, `/app.ts`, and an asset path, and never serves source;
  - API JSON still returns 200 when the bundle is missing;
  - a built bundle serves index, hashed JS, and CSS with correct types;
  - `/../secret.txt`, `/app.ts`, and unknown files return 404.
- `Dockerfile` (new): the `node:22-slim` stage runs `npm ci`, `typecheck`, and `build`. The `python:3.14-slim` runtime copies `dashboard.py`, `fetch_fpl.py`, `config.json`, `digest.md`, `fpl_brief/`, `data/`, and the built `dashboard/dist/`, runs as non-root uid 10001 which owns `/app` (refresh writes `data/` and `digest.md`), and uses `CMD python dashboard.py`.
- `.dockerignore` (new): implemented as an **allowlist** rather than the exclusion list in the task. It excludes everything except the runtime files and `dashboard/`, and re-excludes `node_modules/`, `dist/`, and bytecode. This satisfies both "exclude X" and "do not exclude data/config/fpl_brief".
- `README.md`: the production-bundle section now describes the 503 behavior, and a new "Container image" section covers Dockerfile precedence over `Procfile`, the local smoke commands, disposable server `data/`, and the release gate.
- `ops/TASK.md`: Supervisor task added (READY_FOR_PROGRAMMER), then moved to IN_REVIEW on handoff.

### Verification

- `python -m unittest discover -s tests -v`: PASS (86 tests). The new missing-bundle test would fail against the old fallback, which served `dashboard/index.html` with `/app.ts`.
- `node --test tests/*.mjs`: PASS (10).
- `npm run typecheck --prefix dashboard` and `npm run build --prefix dashboard`: PASS.
- py_compile set from the handoff: PASS. `git diff --check`: PASS (LF/CRLF notices only; new files are whitespace-clean).
- **Clean-checkout smoke (no Docker).** Copied the 116 paths from `git ls-files --cached --others --exclude-standard` minus deleted paths into the scratchpad. That copy has no `dist/`, no `node_modules/`, and no legacy `.js`. Results:
  - Before building, with `PORT=18767`: `/` and `/app.ts` return 503 text/plain, and `/api/workflow-status` returns 200.
  - `npm ci`, typecheck, and build succeed and produce the same content hashes as the working tree (`index-CYl5EWcF.js`, `index-B85p7D96.css`).
  - Assembled the exact Dockerfile runtime file set and ran it with `PORT=18766`: `/` returns 200 HTML, `/assets/index-CYl5EWcF.js` returns 200 text/javascript, and `/api/dashboard` returns 200 JSON. No refresh or research POST was sent.

### Limitations

- **The Docker image build was not executed.** Docker Desktop's engine was not running, and launching it from the session did not start it (WSL `docker-desktop` stayed Stopped). Acceptance criteria 3–4, as specified for a container, are therefore verified only by the equivalent non-Docker smoke above. `docker build` / `docker run` must still be run once the engine is available.
- With an injected PORT, `dashboard.py` binds `0.0.0.0`, so the local smoke briefly listened on all interfaces for about 2 s per run (same as the prior Railway smoke).
- The TypeScript migration and all later milestones are still uncommitted. A Railway build from GitHub would currently build the legacy `HEAD`.

No commit, push, image push, Railway resource, deployment, or public URL was created. `ops/REVIEW.md` was not edited.

## Private FPL account data import — Programmer handoff

**Date:** 2026-09-25
**Status:** IN_REVIEW
**Programmer:** Claude Opus 5.5 (main session)

### Changed paths

- `fpl_brief/private_team.py` (new): `load(path, config, snapshot, now)` validates `local/private_team.json` strictly and returns `state` ∈ missing/invalid/mismatch/stale/ready plus `usable`, a message, and the capture time/age.
  - For ready/stale it also returns free transfers (limit − made, floor 0, or `unlimited`), transfers made, bank, hit cost, value, per-player selling/purchase prices, and chips.
  - Mismatch: the team ID differs from config, or the pick set differs from the public snapshot.
  - Stale: older than `stale_after_hours`, or the current/next deadline passed after capture.
  - Unexpected shapes return `invalid` with no numbers. Only `ready` is `usable`.
- `fpl_brief/candidates.py`: `lens(..., private=None)`. When the private data is usable, the selling price and bank come from the account and `budget_source` is `account`. Otherwise it falls back to the unchanged public path, and the block message appends the private status/import hint. The freshness, squad, deadline, ownership, team-limit, and availability gates are unchanged and still run first.
- `dashboard.py`:
  - adds `PRIVATE_TEAM = local/private_team.json`;
  - `/api/dashboard` returns `private_team`, and `apply_private_inputs()` swaps the "Free transfers and selling prices…" unconfirmed input for an account-sourced `confirmed_inputs` line when the data is usable;
  - `/api/candidates` passes the private summary to `lens()`.
  - The chip ledger is untouched.
- `dashboard/app.ts` (scope expanded by the Supervisor): adds the `PrivateTeamData` type and mounts the panel above the Team Decision Desk.
- `dashboard/team-decision-desk.ts` / `.css`: an escaped `renderPrivateTeamPanel`. Missing/invalid/mismatch states show only a warning; stale shows a warning plus the values; ready shows the facts and a chip table labeled as account data and "Not transfer advice".
- `dashboard/desk-tools.ts`: the Candidate Lens output shows the budget equation and its source. xGI/FDR cells are now escaped. The hint text no longer claims the budget uses the current price.
- Tests:
  - `tests/test_private_team.py` (new, 8 tests: every state, unlimited, floor, 12 malformed mutations, future capture, both stale rules);
  - `tests/test_research_candidates.py` (+3 lens tests);
  - `tests/test_dashboard.py` (+3: caveat swap, API missing state, panel escaping), plus a stub for the new renderer in the existing overview harness.
- `README.md`: capture procedure and privacy boundary.

### Verification

- Full suite: `python -m unittest discover -s tests` — PASS (100 tests). `node --test tests/*.mjs` — PASS (10). Typecheck and build — PASS. py_compile (handoff set + `private_team.py`, `candidates.py`) — PASS. `git diff --check` — PASS.
- Live local check on port 8766 with the real captured file:
  - the state is `ready` (age 0.1 h), with 2 free transfers, £0.1m bank, −4 hit, and £101.2m value;
  - the chips (BB/FH available, TC GW2, WC GW4) agree with the public chip ledger;
  - the decision now lists the account-sourced confirmed input;
  - Candidate Lens for Suzuki gives budget £5.1m = £5.0m selling + £0.1m bank and returns candidates;
  - no console errors.
- Capture: the Overseer signed in to FPL in the browser pane. Claude read `/api/me/` and `/api/my-team/6572775/` with the session cookie (no token was read out or stored) and wrote `local/private_team.json` (gitignored; verified with `git check-ignore`).

### Limitations

- The account data goes stale 8 hours after capture (`stale_after_hours`), after which Candidate Lens re-blocks. Recapture needs the Overseer's browser session and Claude.
- The chip ledger is not reconciled with the account chips; they are shown side by side. Merging them is a possible follow-up.
- The Candidate Lens caveat prints the raw ISO capture time.

No commit, push, deploy, FPL write, or stored credential. `ops/REVIEW.md` not edited.

### Bounded follow-up — review findings and 24-hour freshness

**Date:** 2026-09-25 · **Status:** IN_REVIEW

- `fpl_brief/private_team.py`:
  - account freshness now uses `private_stale_after_hours` (default `DEFAULT_STALE_AFTER_HOURS = 24`) and compares the exact age, not the rounded one;
  - `_captured_time` rejects capture times with no timezone (→ `invalid`);
  - if no current or next deadline parses, the state is `stale` ("deadlines are unavailable");
  - new `disabled()` summary with no account values.
- `dashboard.py`: `LOOPBACK_HOSTS` plus `Handler.private_data()`. The loader is called only when `server_address[0]` is 127.0.0.1, ::1, or localhost; any other binding (for example 0.0.0.0 when `PORT` is set) gets `disabled`. Both `/api/dashboard` and `/api/candidates` use it.
- `fpl_brief/candidates.py`: `budget_source` is `account` only when the account branch actually supplies the outgoing player's price.
- `dashboard/app.ts`: the `disabled` state has been added to the type. `dashboard/team-decision-desk.ts`: every non-stale, non-ready state shows only its warning. The ready text now states the 24-hour/deadline/recapture rule.
- Tests (+6):
  - exact 24 h boundary, 9 h still ready, and a config override;
  - naive capture time;
  - missing deadlines;
  - disabled summary has no values;
  - lens labels a public budget when the account lacks the player;
  - the loopback guard for 0.0.0.0, a LAN IP, and `::` (loader not called), plus 127.0.0.1 (called).
- Verification: 105 Python tests PASS; Node 10 PASS; typecheck, build, py_compile, and `git diff --check` PASS. Live check on 127.0.0.1:8766: `ready` (0.4 h), 2 free transfers, Suzuki budget £5.1m from the account with 45 candidates, and the new panel text is shown.

## Weekly lineup helper and squad readability (Stage 1) — Programmer handoff

**Date:** 2026-09-25 · **Status:** IN_REVIEW · **Programmer:** Claude Opus 5.5

### Changed paths

- `fpl_brief/lineup.py` (new): `suggest(snapshot, catalog, private, freshness, now)`.
  - **Refusals.** It refuses, stating why, when the snapshot is stale or freshness is missing, the deadline is missing or passed, the squad is incomplete or unmatched, or an `ep_next` is missing, non-numeric, or not finite.
  - **Starter eligibility.** Players FPL lists as `i`/`s`/`u`/`n`, those with a 0% chance, and those with no fixture in the next gameweek cannot start. A player is started only when no eligible alternative exists, and is then labeled "Forced start".
  - **Formation.** It picks the legal formation (1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD) with the fewest forced starts, then the highest total `ep_next`. Ties are broken deterministically.
  - **Bench.** Backup GK first, then outfield players by estimate.
  - **Captain and vice.** They prefer eligible, fully available players over doubtful ones, then the highest estimate. Doubles are flagged.
  - **Changes.** A diff against the ready account lineup, otherwise against the public snapshot lineup (source labeled).
  - **Bench Boost hint.** Uses a rule of thumb: every bench player is eligible with an estimate of at least 1, and the bench total is 12 or more. Availability comes from the account chips, otherwise it is unknown.
- `fpl_brief/private_team.py` (scope added): the summary now includes `lineup` (element, position, captain/vice flags).
- `dashboard.py`:
  - `/api/dashboard` returns `lineup`;
  - `serve_static` sends `index.html` with `Cache-Control: no-cache` (scope added). A cached index had pointed at a deleted hashed bundle after a rebuild. Hashed assets keep `public, max-age=300`.
- `dashboard/lineup-helper.ts` / `.css` (new): an escaped "This week's lineup" panel above the pitch. It shows the formation, captain/vice, XI estimate, changes against the current lineup, the XI by line with a reason per player and an "FPL est." badge, and the bench in order. Each player gets their FPL note and up to two non-stale research items, labeled "captured, unverified". The Bench Boost hint is included, and a method note points to Jev (Claude) for web-news judgment.
- `dashboard/app.ts`: `LineupData` import/type and mount in `renderSquad`.
- `dashboard/squad-formation.css`:
  - pitch card names are 15px bold white (14px on mobile), and the other card text is 12–13px with stronger contrast;
  - cards are taller;
  - lines use 2 columns at ≤600px (was ≤400px).
- Tests:
  - `tests/test_lineup.py` (new, 11 tests): optimality, legality, exclusions, forced start, doubtful players and captaincy, doubles, bench order, 7 refusal cases, both diff sources, and the Bench Boost states;
  - `tests/test_dashboard.py`: lineup API and panel escaping, plus the index `no-cache` assertion.

### Verification

- 118 Python tests, 10 Node tests, typecheck, build, py_compile, and `git diff --check` all pass.
- Live on 127.0.0.1:8766 with real data:
  - GW6 is suggested as a 4-4-2 with Groß as captain (FPL est. 11.2) and Haaland as vice (9.2), XI total 72.8;
  - against your account lineup: start Calvert-Lewin, bench Szoboszlai, captain Haaland → Groß, vice Rogers → Haaland;
  - Bench Boost reads "Not this week", because backup GK Dubravka has an estimate of 0;
  - no console errors.
- 375px: no document overflow, and both the lineup panel and the pitch are legible.

### Limitations

- The engine uses FPL's single-gameweek `ep_next` only. There is no multi-week view and no independent forecast.
- Research is joined by player ID from the existing packet, which is currently legacy/stale, so little shows.
- Web-news judgment comes from Jev on request in Claude Code. The in-app chat is not built.

No commit, push, or deploy.

## Tactics Board site redesign — Programmer handoff

**Date:** 2026-09-25 · **Status:** IN_REVIEW · **Programmer:** Claude Opus 5.5

### Changed paths

- `DESIGN.md`: replaced with the Tactics Board system (tokens, typography, components, interaction, don'ts).
- `dashboard/board.css` (new): the site-wide design system.
  - Covers tokens, the tray rail, enamel panels, tables, buttons, forms, warnings/stale/empty/skeleton states, and responsive rules (1100/900/560px). Reduced-motion is supported.
  - Keeps aliases for the pre-redesign variable names.
  - Narrow screens use a `minmax(0, 1fr)` shell column; this fixed a 950px document overflow at 375px.
- `dashboard/index.html`: new direction contract; `styles.css`/`redesign.css` are no longer linked. Both files remain on disk, unlinked, pending the Overseer's OK to delete; `redesign.css` is untracked.
- `dashboard/app.ts`:
  - imports the `@fontsource` fonts, `board.css`, and the board module;
  - My Squad now renders the tactics board, then a `<details>` "lineup as a list" holding the previous text helper, then the saved squad with jerseys.
- `dashboard/package.json`/`package-lock.json`: `@fontsource/barlow`, `@fontsource/barlow-condensed`, `@fontsource/kalam`. Fonts are bundled, with no runtime third-party requests.
- `dashboard/kits.ts` (new): an SVG jersey in illustrative club colours, with a distinct keeper shirt.
- `dashboard/tactics-board.ts` / `.css` (new): the board, made up of:
  - shirt magnets on bases, the enamel pitch and the bench tray;
  - green marker arrows for players entering the XI relative to the current lineup, and a red marker ellipse around the captain;
  - Coach's notes (changes, board summary, Bench Boost, picked-up detail with FPL note and unverified research, Jev prompt);
  - try-a-lineup by pointer/touch drag (a floating ghost) or click/keyboard select-then-swap, with Escape to put a shirt back;
  - `swapMagnets` enforcing GK↔GK and DEF 3–5/MID 2–5/FWD 1–3, bench reorder, and a fixed backup-GK slot;
  - live totals and difference from the suggestion, plus `boardWarnings` (captain or vice benched, starting a player FPL lists as out);
  - a namespaced, versioned `localStorage` key per gameweek, validated on load (exact squad, legal shape, GK in slot 1) with try/catch; Reset clears it;
  - listeners scoped per mount with an `AbortController`.
- `dashboard/squad-formation.ts` / `.css`: an optional `jersey` renderer input, re-toned to enamel. `team-decision-desk.css` and `lineup-helper.css` were re-toned.
- `dashboard.py`: registers the `font/woff2` and `font/woff` MIME types.
- `fpl_brief/lineup.py` follow-ups:
  - the XI total includes forced starters;
  - bench reason capitalisation is fixed;
  - `bench_order_changed` is set only for the same bench set;
  - the Bench Boost rule requires fully available bench players;
  - `changes.current_xi` ids are exposed for the arrows.
- `fpl_brief/private_team.py`: the capture `position` must be an integer ≥ 1.
- Tests:
  - `TacticsBoardTests` (4): swap rules, totals/warnings, storage validation and failure safety, escaping/refusal/kits;
  - lineup follow-ups (+4);
  - private position validation (+2 cases).

### Verification

- 126 Python tests, 10 Node tests, typecheck, build, py_compile, and `git diff --check` all pass.
- **Live on 127.0.0.1:8766:**
  - all seven views render in the new world with no console errors;
  - a click swap (Szoboszlai ⇄ Calvert-Lewin) gives 4-5-1, 70.6 (−2.2), saved to `fpl-brief:board:v1:gw6`;
  - an illegal Haaland ⇄ Calafiori swap is refused (5-5-0);
  - a synthetic pointer drag swaps with the ghost shown;
  - Reset restores the suggestion and clears the key.
- **375px:** all seven views have document width 375; the board and tray fit.
- **Bug fixed during the build:** a click after a click was misread as a drag. Drags now start only while the primary button is held.

### Limitations

- Marker arrows only mark players entering relative to the saved lineup; benched-out players are listed in the notes.
- Mobile name plates truncate long names with an ellipsis; the full name is in the accessible label and in the picked-up detail.
- The old CSS files are still on disk.

### Bounded follow-up — independent review findings (board events)

**Date:** 2026-09-25

`dashboard/tactics-board.ts`:
- The one-shot `suppressClick` flag is replaced with a 350 ms `ignoreClicksUntil` window after a completed drag, so the next real click or Enter/Space is no longer swallowed.
- `endDrag()` is shared by `pointerup`, `pointercancel` and window `blur`. A cancelled drag removes the ghost and never swaps on a later release.
- The drag ghost is `aria-hidden`, `inert`, `tabindex=-1`, and has no label.
- Escape and deselect use `putBack()`, which re-renders and restores focus to the same shirt.
- All 9 listeners, section listeners included, use the mount's abort `signal`.
- `data-id` is escaped.

Test: `test_board_event_handling_guards_regressions`.

Verification:
- 127 Python tests, 10 Node tests, typecheck, build, and `git diff --check` all pass.
- Live synthetic checks:
  - a click immediately after a drag selects;
  - Escape keeps focus on Groß;
  - a cancelled drag leaves no ghost and no swap;
  - the ghost has `aria-hidden="true"`;
  - no console errors;
  - the test board was reset and its key cleared.

### Bounded follow-up — Impeccable finish review fixes

**Date:** 2026-09-25

- **Board.**
  - A stat strip restored the comp: a red deadline countdown, free transfers and bank (from the ready account capture, otherwise "—" with a capture note), and an XI estimate that updates live.
  - Kalam on-board marker notes: "IN: <name> ↑" beside the arrow start and "armband → <captain>" (or "captain") beside the ellipse. They are `aria-hidden`; the same facts appear as text in Coach's notes. They are hidden at ≤700px, where the pitch is taller (68/108) so rows do not collide.
  - Bench magnets are centred on their bases on phones.
  - The board-head H2 was removed.
- **Heading.**
  - Each view sets the H1 to its own name, e.g. "Gameweek 6 lineup" or "Rivals".
  - The snapshot time moved beside Refresh, and the Refresh button no longer spans the row on phones.
- **Removed.**
  - The route map (`mountWayfinding` is no longer mounted; `wayfinding.ts` is left on disk, unused) and its CSS.
  - The "PRIVATE LEAGUE ROUTE" rail label, now "Mini-league".
  - The saved public squad now sits in a collapsed `<details>` instead of a second always-open squad.
- **Other views.**
  - 28px club shirts appear in the Player pool (its raw ID column was dropped), the Candidate lens (via an optional `runtime.kit`), and the Team decision desk (via an optional renderer argument).
  - The Team decision desk shows flagged rows. Unflagged rows sit in a collapsed `<details>` ("N players with no FPL availability flag…"); when the snapshot is stale, all rows are shown.
  - Rivals adds your own row ("You", with a marker underline, sorted by rank) and merges the always-equal "Your/Their diffs" into "Differentials (each side)", with a caption explaining why. That equality is arithmetic (15 − shared), not a data bug. It now accepts numeric or list comparison values.
  - Research desk list: no bullets, dashed separators, ink links underlined on hover.
- **Not done.**
  - The reviewer's "best fit" circle on the Candidate lens's first row was declined: the lens ranks by xGI/90, and "best fit" would overclaim.
  - Wildcard lab shirts, per-club research grouping, and regenerating `.impeccable/design.json` are left for later.

**Verification.**
- 127 Python tests, 10 Node tests, typecheck, build, py_compile, and `git diff --check` all pass.
- Full-page captures were regenerated in `.impeccable/review/` at 1440 and 375px. Checked desktop.png and mobile.png: no collisions, board fully in view.

## Self-serve weekly workflow — Programmer handoff

**Date:** 2026-09-26 · **Status:** IN_REVIEW · **Programmer:** Claude Opus 5.5

### Changed paths

- **`dashboard.py`**
  - **`POST /api/private-team` (`import_private_team`).** Refused unless the server is bound to loopback and `same_origin_local()` passes:
    - the Host hostname is 127.0.0.1, localhost or [::1] (blocks DNS rebinding);
    - `Origin` equals `http://<Host>`, or, with no Origin, `Referer` is on that origin;
    - the request is `application/json`;
    - the body is between 1 byte and 64 KB (`MAX_IMPORT_BYTES`);
    - the body is a JSON object with picks, chips and transfers. A `{my_team: …}` wrapper is also accepted.

    The server wraps the data (`team_id` from config, `captured_at_utc` set to now, and `source`), writes it to a temp file in `local/`, and validates it with `private_team.load`. Only `ready` or `stale` data is moved into place with `os.replace`. The temp file is always removed.
  - **`GET /api/plan?transfers=OUT:IN,…`** uses `plan.parse_transfers`, `private_data()` (loopback-guarded) and `plan.build`. It returns 400, 422, or 200.
- **`fpl_brief/plan.py` (new).** Builds a transfer plan. It requires a usable account and enforces:
  - unique players, and OUT owned while IN is not;
  - the same position;
  - IN fully available;
  - the three-per-club limit over the whole planned squad;
  - budget = bank + selling prices − `now_cost`;
  - hits = max(0, n − free) × `hit_cost`, and none for `unlimited`.

  It re-optimises with `lineup.suggest` on a deep-copied snapshot (swapped picks lose the armband) and returns the planned lineup plus a summary: transfers, `budget_left`, `paid_transfers`, `hit_points`, `xi_delta`, and `net_delta` (after hits).
- **`fpl_brief/lineup.py`.** `_upcoming` adds each player's `next_fixtures` (the next 3: opponent, H/A, FDR 1–5 or null) and `captain_options` (the top 3 eligible, fully available starters in captain order).
- **Frontend**
  - **`transfer-plan.ts` (new).** Holds the browser-local plan, capped at 3 and validated on load against the owned squad, under a namespaced key per gameweek. `addTransfer` replaces a move for the same OUT or IN. `renderPlanStrip` is escaped and has remove and clear controls.
  - **`app.ts`**
    - `renderSquad` fetches `/api/plan` for a saved plan, caches it by key, renders the board with the planned lineup, and wires remove and clear.
    - `runtime.planTransfer` is added.
    - `importAccount()` checks the paste client-side, POSTs it, reloads, and reports in the status line.
    - The rivals rank sort is robust to non-numeric ranks.
  - **`desk-tools.ts`.** Candidate rows get a "Try on board" button, which reports errors via `runtime.status`.
  - **`team-decision-desk.ts`.** The import section links to the exact my-team URL (integer team id only; `rel="noopener noreferrer"`), with a paste box, an Import button and an explanation. It is open by default when the capture is missing, invalid or stale.
  - **`tactics-board.ts`**
    - fixture strip in the picked-up detail;
    - captain shortlist in Coach's notes;
    - the deadline ticks every 30 s and the timer is cleared on abort;
    - free transfers show "—" when absent;
    - marker notes are placed collision-aware against the visible shirt, plate, estimate and badge boxes, with pitch-corner fallbacks, and skipped if none is clear.
  - **CSS.** Adds styles for the fixture strip, the shortlist, the plan strip, the import section, and `.visually-hidden`, and makes `.table-wrap` `position: relative` so hidden header labels can't overflow the page.
- **Tests**
  - `tests/test_plan.py` (6);
  - `PrivateTeamImportTests` (4: happy path; cross-site, rebinding, missing-origin; off-loopback; seven bad-paste cases with no file written);
  - `TransferPlanUiTests`;
  - the countdown-teardown assertion.
- **`README.md`.** Documents the self-serve import and the weekly workflow.

### Verification

- 139 Python tests, 10 Node tests, typecheck, build, py_compile and `git diff --check` all pass.
- **Live (the Overseer's account; public refresh plus the UI import path).** The my-team JSON was copied from the signed-in FPL tab and pasted into the new import box. It gave state `ready`, age 0, 2 free transfers and value £101.3m, with a status-line confirmation.
- **Transfer planner.**
  - Candidate lens → Szoboszlai → "Try on board" (Dewsbury-Hall) jumped to the board: +0 (he would be benched), 1 of 2 free transfers, £0.5m left.
  - João Pedro → Kostoulas: re-optimised to a 3-4-3 with Kostoulas starting, +1.6, £2.2m left. Marker notes placed without collisions at 537px board width.
  - The test plan was cleared afterwards.
- **375px.** All seven views are exactly 375px wide. The fix above resolved a 519px overflow in the Candidate lens.

### Limitations

- The plan values only next-gameweek `ep_next` minus hits; multi-week value is not modelled, and the UI says so.
- Candidate lens ranking is unchanged (xGI/90).
- The import's `Referer` fallback accepts same-origin referers when Origin is absent, which older browsers may do.

### Bounded follow-up — 2026-09-26 independent review findings

- **[Blocking] Stray fields in the import (`dashboard.py`).** `whitelist_my_team()` rebuilds the paste from `IMPORT_FIELDS` only:
  - pick keys;
  - chip keys;
  - transfer keys;
  - `picks_last_updated`, capped at 40 characters.

  Any other key, at the top level or nested, is dropped before validation or storage. Test: `test_only_known_fpl_fields_are_saved` (password, cookie, token and secret all absent from the saved file).
- **[Blocking] Stale plan after a reload (`dashboard/app.ts`).** The plan cache key now includes `snapshot.generated_at_utc` and `private_team.captured_at_utc`. After a refresh or import, the plan is re-checked, and a cached error lasts only until the next data reload. The fetch uses `planQuery(plan)` alone. A static test guards the key.
- **Low items**
  - `RecursionError` on deeply nested JSON now returns 400 (test).
  - `Handler.timeout = 15` stops a short or stalled upload from holding a thread.
  - `IMPORT_HINT` points to "Overview → Your FPL account → Update from FPL".
  - Captain and vice change text drops "— →" when the old armband holder was sold (board and list).
  - `mountTacticsBoard` aborts the previous mount before any early return (static test).
  - Captain options list every fixture in a double gameweek (test).
- **Pre-existing issue now closed.** On a loopback-bound server, `/api/*` GETs refuse any Host other than 127.0.0.1, localhost or [::1] (DNS rebinding), via the shared `host_is_local()`, which is also used by the import. Test: `test_api_reads_refuse_foreign_host_names_on_loopback`.
- **Verification**
  - 143 Python tests, 10 Node tests, typecheck and build pass.
  - The live app on localhost:8766 still loads: the lineup is ready, the account is ready, the board has 15 magnets, the shortlist renders, and the clock reads 14d 6h.
  - The previous report's "139" was a miscount; the reviewer ran 138.

### Post-approval hardening (re-review low/info items)

- `whitelist_my_team` keeps a known field only when its value is plain:
  - a finite number, a boolean, null, or a string of at most 64 characters;
  - or a list of at most 64 integers.

  Crafted nested values in the pick, transfer and chip fields and in `picks_last_updated` are dropped. Test: `test_known_fields_keep_only_plain_values`.
- On a loopback bind, `POST /api/refresh`, `/api/research` and `/api/plans/compare` require `same_origin_local()`. A Railway `0.0.0.0` bind is unaffected. Test: `test_actions_refuse_cross_site_posts_on_loopback`.
- Verified live: the dashboard's own Refresh still works ("Snapshot refreshed", generated 2026-09-26 04:03 UTC).
- 145 Python tests pass.

## Release verification — Render (2026-09-26)

Deployed by the Overseer from the `render.yaml` Blueprint (commit `305c18d`), as the free Docker web service `fpl-brief`. It is live at https://fpl-brief.onrender.com, with a 33.8 s build. This build is the Docker image verification that the 2026-09-25 review asked for.

Smoke test of the public URL (read-only apart from one public-data Refresh):

| Check | Result |
| --- | --- |
| `/` | 200, `Cache-Control: no-cache` |
| Hashed JS bundle | 200, `text/javascript` |
| CSS | 200 |
| Self-hosted fonts | All 6 faces loaded |
| `/api/dashboard` | 200; fresh snapshot; lineup ready |
| `private_team` | `disabled` (not a loopback bind), as designed |
| `/api/plan` | 422 "needs a fresh capture", so no private data online |
| Views | All 7 render with the correct H1; board shows 15 magnets |
| Refresh FPL data | "Snapshot refreshed" (04:30 UTC); the non-root container user can write `data/` and `digest.md` |

The site is public with no password, per the Overseer's decision. Auto-deploy runs on every commit to `main`.

## Password-protect the public site — Programmer handoff

**Date:** 2026-09-26 · **Status:** IN_REVIEW · **Programmer:** Claude Opus 5.5

### Changed paths

- **`dashboard.py`.** When `DASHBOARD_PASSWORD` is set, `Handler.gate(path)` runs first in `do_GET`, `do_POST` and `do_PUT` and protects every route except `/healthz`:
  - HTTP Basic, any username; `basic_password()` uses strict base64 and UTF-8, and `hmac.compare_digest` compares against the password.
  - A missing or wrong password gets `401` with `WWW-Authenticate: Basic realm="FPL Brief", charset="UTF-8"` and a no-store body with no data.
  - **Failures.** Only attempts that send an Authorization header are counted, per client (the first `X-Forwarded-For` hop capped at 64 characters, else the socket address), in a 10-minute window. The 10th failure triggers `429` with `Retry-After`. The table holds at most 2048 clients (oldest evicted) and is lock-protected.
  - **Fail closed.** `REQUIRE_PASSWORD=1` without a password returns `503` everywhere except `/healthz`.
  - **`/healthz`** returns `200` "ok" if `dist/index.html` exists, else `503`. It returns no data.
  - **`do_HEAD`.** Newly overridden to return `405`. The inherited `SimpleHTTPRequestHandler.do_HEAD` previously served headers for any file in the working directory, a pre-existing gap now closed.
  - The password is never logged, since `log_message` is a no-op, and never echoed.
- **`render.yaml`.** The healthcheck is now `/healthz`. It sets `envVars`: `DASHBOARD_PASSWORD` (`sync: false`, which the Overseer sets in Render) and `REQUIRE_PASSWORD="1"`.
- **`railway.json`.** Deleted. Railway is no longer used; the Overseer deletes the Railway project in their own browser.
- **`README.md`.** Documents the password setup and behaviour.
- **`tests/test_dashboard.py`.** `PasswordGateTests` (5 tests):
  - open when unset;
  - `401` on static, API GET, POST and PUT without credentials or with a wrong password;
  - `200` with the right one;
  - malformed and Bearer headers rejected;
  - `/healthz` open;
  - `HEAD` returns `405`;
  - fail-closed `503`;
  - per-client `429` with expiry, and other clients unaffected;
  - the bare challenge is not counted;
  - the table is bounded.

### Verification

150 Python tests, Node, py_compile and `git diff --check` all pass.

### Notes

- Basic auth relies on Render's HTTPS; the browser caches the credentials for the session.
- `X-Forwarded-For` is set by Render's proxy. A direct-to-origin client could spoof it to dodge the per-client limit, but Render does not expose the origin.

### Bounded follow-up — 2026-09-26 security review findings

- **Client identity (`client_id`).** I did not adopt the suggested right-most `X-Forwarded-For` entry. Render's public statement ([feedback.render.com](https://feedback.render.com/features/p/send-the-correct-xforwardedfor)) says it "sets the first IP in the list to the real client IP" and also appends. Taken together, the right-most entry could be a Render internal hop shared by every visitor, which would make the per-client limit global and reopen owner lockout.

  Instead, the identity is the whole normalised chain (capped at 256 characters) plus the socket peer. The consequences are:
  - A visitor can add entries, which only evades the per-client limit.
  - No visitor can reproduce another's chain, because Render always inserts the real address. Framing or locking out the owner is therefore impossible, whatever order Render uses.
- **Global ceiling.** 100 failures across all clients within 10 minutes returns `429` with `Retry-After` for everyone. This is the actual brute-force bound (≤14,400 guesses a day, hopeless against 16+ random characters). The README documents the trade-off: temporary unavailability is possible, password grinding is not.
- **Static caching.** Assets are sent as `private, max-age=300` whenever a password is set, and stay `public` locally.
- **README.** Recommends 16+ random characters and explains the identity model and the ceiling.
- **Tests.**
  - Rotating spoofed entries is capped by the global ceiling.
  - A spoofed chain naming another address does not lock out the owner.
  - The global ceiling blocks at the limit and expires.
  - Assets are `private` behind the password.
  - Existing tests are updated for the global table.
- **Results.** 153 Python tests, Node tests, py_compile and `git diff --check` all pass.

### Release note — password gate on Render (2026-09-26)

- **First deploy of `1b89488` failed.** Render reported "Timed out after waiting for internal health check … fpl-brief.onrender.com:10000/healthz". Its automatic retry at 11:58 went live, with no code change.
- **Verified externally at 11:59:** `/`, `/api/dashboard` and assets return **401**; `/healthz` returns **200** with no data.
- **Follow-up hedge (reviewed PASS, "Health probe fix — review" in ops/REVIEW.md).** `Handler.health()` answers GET and HEAD `/healthz`, and the first 5 probes print "health probe <METHOD> /healthz -> <status>" (method and status only) so future hosting failures are diagnosable. Test: HEAD `/healthz` returns 200. 153 Python tests pass.
