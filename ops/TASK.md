# Active task — "What the internet thinks": crowd data + in-app Jev

**Owner:** Programmer (Claude Opus 5.5); review by a separate Opus 5.5 subagent at high effort (a secret API key, external calls, and untrusted web content)
**Status:** APPROVED (independent re-review PASS 2026-09-26; push allowed, then verify on Render)
**Date:** 2026-09-26
**Milestone:** Overseer decision 2026-09-26 (see ops/DECISIONS.md).

## Required implementation

### A. Crowd data (official FPL, deterministic)

1. `fetch_fpl.py` adds `transfers_in_event`, `transfers_out_event`, `cost_change_event` and `cost_change_start` to the catalog. The digest workflow also commits `data/catalog.json`, so the hosted site stays current.
2. `fpl_brief/crowd.py`:
   - the gameweek's crowd summary: most transferred in and out (top 10, with net, ownership and price move), price risers and fallers, and the most captained/selected players and chip plays (labelled with the gameweek they refer to);
   - a per-player crowd map for the squad: ownership, net transfers, price move, and how many league rivals own each player;
   - the mini-league's most-owned players you don't have.
3. `/api/dashboard` returns `crowd`. There is a new **Crowd** view. The board's picked-up detail and captain shortlist show a one-line crowd note. Candidate lens rows show ownership and net transfers.

### B. In-app Jev

4. The official `anthropic` SDK becomes the first runtime dependency: add it to `requirements.txt`, and have the Dockerfile runtime and the CI workflows install it. `fpl_brief/jev_ask.py` then works as follows:
   - **Model and request:** `claude-opus-5`, adaptive thinking by default, effort `medium`, `max_tokens` 16000.
   - **Tools:** the `web_search_20260209` tool (`max_uses` 5), plus the server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`).
   - **Continuation:** `pause_turn` is continued up to 3 times.
   - **Output:** text and cited sources (http/https only) are extracted, and refusals and errors return a plain message.
   - **Prompting:** the system prompt treats web content as untrusted data, answers only the FPL question, separates sourced facts from opinion, cites, and never produces HTML.
5. `POST /api/jev` requires a signed-in session and the same origin (via the existing gate). It returns `503` when `ANTHROPIC_API_KEY` is unset.
   - **Question:** 3–500 characters.
   - **Context:** optional `transfers`, validated like `/api/plan`. The server builds the context itself from the current lineup, flags, plan and crowd data; the client never supplies free-form context.
   - **Daily cap:** `JEV_DAILY_LIMIT` (default 20) per server day. `429` when it is reached.
   - **Execution:** a background job polled through `/api/jobs/<id>`.
   - **Secrets:** the API key is never logged or returned.
6. **UI.** An "Ask Jev" panel in the Crowd view and on the board replaces the "ask in Claude Code" note.
   - **Controls:** quick prompts plus a free-text question.
   - **Answer:** shown as escaped text with simple paragraphs and bullets, a sources list (safe links), and the label "Internet opinion via Claude web search — unverified".
7. **Tests.** The SDK is mocked and nothing touches the network. Coverage:
   - context building;
   - `pause_turn` continuation;
   - refusal;
   - citation extraction, with unsafe URLs dropped;
   - no key;
   - cap and validation;
   - the endpoint gated behind sign-in;
   - UI escaping;
   - crowd maths.

## Allowed paths

`fetch_fpl.py`, `fpl_brief/crowd.py` (new), `fpl_brief/jev_ask.py` (new), `fpl_brief/candidates.py`, `dashboard.py`, `dashboard/**` (excluding `node_modules`/`dist`), `requirements.txt`, `Dockerfile`, `.github/workflows/*.yml`, `render.yaml`, `tests/**`, `README.md`, `ops/IMPLEMENTATION_REPORT.md`.

## Release boundary

- Push after an independent PASS.
- The Overseer sets `ANTHROPIC_API_KEY` in Render; Claude never handles it.
- Verify on Render.

---

# Closed task — Sign-in page with session cookie

**Owner:** Programmer (Claude Opus 5.5); review by a separate Opus 5.5 subagent at high effort (authentication)
**Status:** APPROVED (independent review 2026-09-26, PASS; see ops/REVIEW.md). Push allowed; verify on Render / = 303 to /login and /healthz = 200, then the Overseer signs in. Optional follow-up: Low findings 1-3 (non-ASCII next crash, >10 login fields, SimpleCookie all-or-nothing).
**Date:** 2026-09-26
**Milestone:** Replace the browser's Basic-auth pop-up (unreliable in some browsers; the Overseer saw only the 401 text) with a proper sign-in page and a signed session cookie. Overseer request 2026-09-26.

## Required implementation

1. **Routes.** `GET /login` serves a self-contained sign-in page in the Tactics Board style: a password field, "Keep me signed in for 30 days", and error and lockout messages. `POST /login` accepts form fields `password`, `remember` and `next`, with a body of at most 4 KB. `GET /logout` clears the session.
2. **Session.** The cookie `fpl_session` holds `<expiry>.<HMAC-SHA256(key, "v1.<expiry>")>`, where `key` is derived from `DASHBOARD_PASSWORD`, so changing the password invalidates every session. Expiry is 30 days with "remember" (with `Max-Age`), otherwise 12 hours (a browser-session cookie). Flags: `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` whenever the request arrived over HTTPS or the server is not on loopback.
3. **Gate.**
   - Always open: `/healthz`, `GET /login`, `POST /login`, `GET /logout`.
   - Everything else requires a valid session.
   - Unauthenticated `GET` or `HEAD` of a page returns `303` to `/login?next=<path>`. `/api/*` and POSTs return `401` JSON with no `WWW-Authenticate`, so no browser pop-up appears.
   - `POST` or `PUT` with a session must also be same-origin (the `Origin` or `Referer` host equals `Host`), otherwise `403`.
   - Basic auth is removed.
4. **Brute force.** The per-client and global limits count failed `POST /login` attempts. When a limit is hit, the page shows the retry time and returns `429`.
5. **Safety.**
   - `next` must be a local path: it starts with `/`, not `//` or `/\`, and has no scheme. Anything else falls back to `/`.
   - The sign-in page is sent with CSP `default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'`, plus `X-Frame-Options: DENY` and `Cache-Control: no-store`.
   - The password is never logged, echoed or stored.
6. **Frontend.** `/api/dashboard` reports `auth.enabled`. The rail shows a "Sign out" link when it is true. `requestJson` sends the browser to `/login?next=…` on a `401`.
7. **Unchanged.** `REQUIRE_PASSWORD` still fails closed, and local runs with no password are unaffected.
8. **Tests** cover: redirect and `401` behaviour, a correct and a wrong login, the cookie flags, expiry, tampering, password rotation, `next` sanitising, rate limits on login, same-origin POST with a session, logout, and the no-password and fail-closed paths.

## Allowed paths

`dashboard.py`, `fpl_brief/web_session.py` (new), `dashboard/app.ts`, `dashboard/index.html`, `dashboard/board.css`, `tests/test_dashboard.py`, `README.md`, and `ops/IMPLEMENTATION_REPORT.md`.

## Release boundary

- Push after the independent review passes.
- Verify on Render that `/` returns `303` to `/login` and `/healthz` returns `200`.
- The Overseer signs in.

---

# Closed task — Password-protect the public site

**Owner:** Programmer (Claude Opus 5.5); review by a separate Opus 5.5 subagent at high effort (authentication on a public deployment)
**Status:** APPROVED (independent re-review 2026-09-26, PASS; see ops/REVIEW.md). Push allowed; the Overseer sets DASHBOARD_PASSWORD in Render, then verify / = 401 and /healthz = 200.
**Date:** 2026-09-26
**Milestone:** Put the Render deployment behind a password (Overseer request 2026-09-26, "just in case"), reversing the no-password choice for the hosted site. Remove the unused Railway config.

## Required implementation

1. **HTTP Basic authentication in `dashboard.py`**, enabled when the `DASHBOARD_PASSWORD` environment variable is set.
   - It covers every route (static files and all `/api/*` GET and POST routes) except `/healthz`.
   - Any username is accepted, and the password is compared in constant time.
   - A missing or wrong password gets `401` with `WWW-Authenticate: Basic realm="FPL Brief"` and no data.
   - The password is never logged or echoed.
2. **Fail closed.** When `REQUIRE_PASSWORD=1` is set without a password (a Render misconfiguration), every route except `/healthz` returns `503` "password not configured". Local runs set neither variable, so behaviour there is unchanged.
3. **Brute-force limit.** After 10 failed attempts per client within 10 minutes, return `429` for the rest of that window.
   - The client is the first `X-Forwarded-For` hop, or the socket address.
   - The failure table is bounded in memory.
4. **`/healthz`.** Returns `200` "ok" when the built frontend is present, otherwise `503`, and exposes no data. `render.yaml` switches its healthcheck to `/healthz` and declares `DASHBOARD_PASSWORD` (`sync: false`, so the Overseer sets it in Render's dashboard) and `REQUIRE_PASSWORD=1`.
5. **Tests.**
   - Open when unset.
   - `401` without credentials or with a wrong password, `200` with the right one, for static files, API GETs and POSTs.
   - `/healthz` stays open.
   - Fail-closed `503`.
   - Lockout `429` and window expiry.
   - The password never appears in responses.
6. Delete `railway.json`. Update the README and ops records.

## Allowed paths

`dashboard.py`, `render.yaml`, `railway.json` (delete), `tests/test_dashboard.py`, `README.md`, and `ops/IMPLEMENTATION_REPORT.md`.

## Release boundary

- Push only after an independent review passes.
- The Overseer sets `DASHBOARD_PASSWORD` in Render. Claude never enters it.
- Verify after deploy that `/` returns `401` without credentials and `/healthz` returns `200`. The Overseer confirms sign-in.

---

# Closed task — Self-serve weekly workflow ("fully functional")

**Owner:** Programmer (Claude Opus 5.5); review by a separate Opus 5.5 subagent at high effort, because it adds a local write endpoint for private account data
**Status:** APPROVED LOCALLY (re-review 2026-09-26, local only; see ops/REVIEW.md)
**Date:** 2026-09-26
**Milestone:** Let the Overseer run the whole weekly decision without Claude in the loop: self-serve account import, transfer planning with a re-optimised XI and captain, a fixture outlook, and a captain shortlist. Overseer request 2026-09-26: "make it fully functional".

## Required implementation

1. **Self-serve account import.**
   - `POST /api/private-team` accepts the raw JSON of FPL's `/api/my-team/{team_id}/`, which the Overseer copies from their own signed-in browser.
   - The server wraps it into the `local/private_team.json` schema (`team_id` from config, `captured_at_utc` set to now, and `source`), validates it with the same `private_team` rules, and writes it atomically.
   - **Safety requirements:**
     - The endpoint answers only when the server is bound to loopback.
     - The `Origin` or `Referer` header must be the same origin.
     - The body is capped at 64 KB and must be `application/json`.
     - Credentials are never accepted or stored, the file is never served beyond the existing loopback-guarded summary, and no FPL call is made.
   - **UI:** the "Your FPL account" panel gets an Import section. It links to the exact my-team URL for the configured team, which opens in the user's own browser, and has a paste box, an Import button, and clear success or error states.
2. **Transfer planner.**
   - `GET /api/plan?transfers=OUT:IN[,OUT:IN…]` (up to 3 pairs) validates each move:
     - the outgoing player is owned and the incoming one is not;
     - both play the same position;
     - the incoming player is available;
     - the club limit of 3 holds after all moves;
     - the budget holds, using the ready account's selling prices plus bank (refused without a usable capture);
     - no player is repeated.
   - It then returns `lineup.suggest` for the modified squad, plus a plan summary: budget left, transfers, free transfers used, hit cost (`transfers_made` and `limit` from the account), and the change in XI estimate against no transfers.
   - **UI:** Candidate lens rows get "Try on board". My Squad shows a "Planned transfers" strip on the board with each OUT → IN pair (removable) and the plan summary. The board renders the re-optimised XI. Plans are browser-local, namespaced by gameweek, and validated on load.
3. **Fixture outlook and captain shortlist.**
   - `lineup.suggest` adds each player's next 3 fixtures (opponent, H/A, FDR) and `captain_options`: the top 3 eligible, fully available starters, with estimate, fixture count and flags.
   - The board's picked-up detail shows the fixture strip, and Coach's notes shows the shortlist.
4. **Polish.**
   - The deadline countdown ticks every 30 s and is torn down on unmount.
   - Free transfers show "—" when absent.
   - The Rivals sort is robust to non-numeric ranks.

## Allowed paths

`dashboard.py`, `fpl_brief/lineup.py`, `fpl_brief/private_team.py`, `fpl_brief/plan.py` (new), `dashboard/**` (excluding `node_modules`/`dist`), `tests/**`, `README.md`, and `ops/IMPLEMENTATION_REPORT.md`.

## Acceptance

- **Import tests:**
  - happy path, with the correct file written in a temporary directory;
  - refused when bound off-loopback;
  - a cross-origin `Origin` rejected;
  - an oversized body, a wrong content type, malformed JSON, a wrong team, or a squad mismatch are rejected;
  - no partial file is left behind.
- **Plan tests:**
  - every validation rule;
  - budget arithmetic against selling prices;
  - hits (free vs −4 each, and unlimited);
  - the re-optimised XI and captain;
  - refusal without a usable account.
- **UI tests:** escaping, the plan storage round-trip and corruption handling, and the countdown teardown.
- **Suite:** all suites, typecheck, build and `git diff --check` pass. Live checks at desktop and 375px.
- **Release:** local only. No FPL write action; no credentials.

### Follow-up (bounded, from review 2026-09-26)

1. **Import stores only schema fields (`dashboard.py`).**
   - Persist only the schema fields of picks, transfers and chips; drop everything else.
   - Catch `RecursionError`/`ValueError` from `json.loads` and return 400.
   - Add a test that a paste with extra `password`/`cookie` keys is saved without them.
2. **Plan cache invalidation (`dashboard/app.ts`).**
   - Clear `planCache` and `planRequest` whenever dashboard data is reloaded.
   - Do not cache the fetch-failure result.
   - Add a test, or a live check, that importing after a "needs a fresh capture" refusal re-checks the plan.
3. **Optional low fixes.**
   - Update `IMPORT_HINT` to point to the Import box.
   - Label a sold captain in `changes.captain.from`.
   - Abort the previous board mount before the early return in `mountTacticsBoard`.

---

# Closed task — Tactics Board site redesign

**Owner:** Programmer (Claude Opus 5.5, medium effort); review by a separate Opus 5.5 subagent, plus the Impeccable finish reviewer
**Status:** APPROVED (re-review 2026-09-25, local only; see ops/REVIEW.md)
**Date:** 2026-09-25
**Milestone:** Replace the Away-Day Route Map look across the whole dashboard with the approved Tactics Board world (Overseer decision 2026-09-25).

## Required implementation

1. **Design system.**
   - Replace `DESIGN.md` with the Tactics Board system.
   - A new `dashboard/board.css` provides the tokens, shell, rail nav, panels, tables, buttons, forms, and the states hover, focus, disabled, loading, empty, error, and stale.
   - Remove `styles.css` and `redesign.css` from the page, and re-tone `squad-formation.css`, `team-decision-desk.css`, and `lineup-helper.css`.
   - Fonts are self-hosted via `@fontsource` (Barlow, Barlow Condensed, Kalam), so pages make no runtime third-party font calls.
2. **Every view restyled.** This covers Overview, Squad, Wildcard lab, Rivals, Player pool, Research desk, and Candidate lens. Existing IDs, `data-*` hooks, text labels, and behaviors are preserved.
3. **Lineup board.** Add `dashboard/tactics-board.ts`, rendered at the top of My Squad from `lineup`.
   - **Board contents:** shirt magnets with magnet bases on an enamel pitch and a bench tray. Marker arrows run from the bench to the pitch for each suggested "start". The captain is circled in marker. A "Coach's notes" column shows the changes, armband, Bench Boost, and a selected-player detail. There is an Ask Jev prompt.
   - **Try-a-lineup.** Drag with pointer or touch. There is also a keyboard/click path: select one magnet, then another, to swap them.
     - Swaps are validated against FPL formation rules (GK↔GK only; DEF 3–5, MID 2–5, FWD 1–3). Illegal drops snap back with a marker message.
     - The XI estimate total and the difference from the suggestion update live, with a warning if the captain or vice is benched.
     - The board is saved to a namespaced, versioned `localStorage` key per gameweek, with try/catch and validation against the current squad. A Reset button restores the suggestion.
     - It is labeled "only saved in this browser; make real changes in the FPL app". It never contacts FPL.
   - The existing lineup-helper refusal states render as a board notice.
4. **Readability.** Body text is at least 15px, and secondary text is at least 13px with ≥4.5:1 contrast. Layouts work at 360, 430, 900, and 1440px with no document overflow.
5. **Folded-in lineup review follow-ups (2026-09-25).**
   - The Bench Boost rule excludes doubtful bench players.
   - Fix the bench reason capitalisation.
   - Validate the captured lineup `position` (non-integers make the account data invalid).
   - `bench_order_changed` compares only the order of the same bench set.
   - The XI total includes forced starters' estimates.

## Required follow-up (review 2026-09-25)

Paths: `dashboard/tactics-board.ts`, `tests/test_dashboard.py` only.

1. Make click suppression after a drag robust. For example, clear it on the next `pointerdown`, or suppress only a click that arrives within the same gesture, so the next click or Enter/Space always selects.
2. Handle `pointercancel` (and a `blur` of the window). It must remove the ghost, clear `is-lifted`/`is-dragging`, and reset `drag` without swapping.
3. Restore focus to the relevant magnet after Escape and after deselecting.
4. Mark the drag ghost `aria-hidden="true"` and `inert` (or strip its label).
5. Pass `{ signal }` to the section listeners.

Add tests where the harness allows. Then re-run the full checks.

## Allowed paths

`DESIGN.md`, `dashboard.py` (font MIME types only), `dashboard/**` (excluding `node_modules`/`dist`), `fpl_brief/lineup.py`, `fpl_brief/private_team.py`, `tests/test_dashboard.py`, `tests/test_lineup.py`, `tests/test_private_team.py`, `README.md`, `.impeccable/**`, and `ops/IMPLEMENTATION_REPORT.md`.

## Acceptance

- **Tests.** The full suite, Node tests, typecheck, build, and `git diff --check` all pass.
- **New tests cover:**
  - swap validation (legal and illegal cases, GK rule);
  - totals recalculation;
  - the captain-benched warning;
  - storage corruption, and restoring a stale squad;
  - escaping in the board;
  - the five follow-ups.
- **Visual checks.** Desktop and 375px, with no console errors and keyboard operability, followed by the independent review and the Impeccable finish review.
- **Release.** Local only.

---

# Closed task — Weekly lineup helper and squad readability (Stage 1)

**Owner:** Programmer (Claude Opus 5.5, medium effort); review by a separate Opus 5.5 subagent at medium effort
**Status:** APPROVED
**Date:** 2026-09-25
**Milestone:** A deterministic next-gameweek lineup helper in My Squad, plus a legibility fix for the pitch cards (Overseer decision 2026-09-25).

## Required implementation

1. Add `fpl_brief/lineup.py`: `suggest(snapshot, catalog, private, freshness, now)`, returning a view model.
   - **Refusals.** It refuses, stating the reason, when the snapshot is stale, the next deadline is missing or has passed, the squad has fewer than 15 matched picks, or `ep_next` is missing for starters.
   - **Scoring.** Each player's score is FPL's `ep_next`, as published.
   - **Starter eligibility.** A player is ineligible to start when their status is `i`/`s`/`u`/`n`, their chance is 0, or their team has no fixture in the next gameweek. Such players are ranked only for the bench.
   - **Doubtful players.** Players with a chance below 100 are flagged, not hidden.
2. **Legal XI.** Pick 1 GK, 3–5 DEF, 2–5 MID and 1–3 FWD, maximizing the total score. Ties are broken by id.
3. **Bench.** The backup GK goes in position 12. Outfield bench players go in descending score order.
4. **Captain and vice.** The two highest-scoring starters, preferring fully available players. Double-gameweek players are flagged.
5. **Comparison with the current lineup.** Compare with the current lineup in the ready account capture, otherwise the public snapshot's last lineup (labeled as such). Report who to start and who to bench, captain and vice changes, and bench order changes.
6. **Bench Boost hint.** State the bench total `ep_next`, whether Bench Boost is available (account chips when ready, otherwise unknown), and a transparent rule of thumb: "worth considering" when the four bench players are all available with fixtures and their total is 12 or more. It is a hint, not advice to play the chip.
7. **API and UI.** `/api/dashboard` returns `lineup`. My Squad shows an escaped "This week's lineup" panel above the pitch with:
   - the XI by line, the bench, and captain/vice;
   - the reason for each choice, with the `ep_next` value labeled "FPL estimate";
   - the diff against the current lineup;
   - the Bench Boost hint;
   - player-linked research as "captured, unverified";
   - a note that Jev (Claude) can weigh web news on request.
8. **Readability.** Enlarge the pitch card text: names ≥14px, other text ≥12px, with stronger contrast. Keep the 360/430/900/1440px widths free of overflow.
9. **Added by the Supervisor 2026-09-25:** serve `index.html` with `Cache-Control: no-cache`. A cached index pointed at a deleted hashed bundle after a rebuild. Hashed assets keep `public, max-age=300`.

## Allowed paths

`fpl_brief/lineup.py` (new), `fpl_brief/private_team.py` (added: expose the captured lineup order and captaincy only), `dashboard.py`, `dashboard/app.ts`, `dashboard/squad-formation.ts`, `dashboard/squad-formation.css`, `dashboard/lineup-helper.ts` (new), `dashboard/lineup-helper.css` (new), `tests/test_lineup.py` (new), `tests/test_dashboard.py`, `README.md`, `ops/IMPLEMENTATION_REPORT.md`.

## Acceptance

- **Fixture tests:**
  - formation legality and optimality;
  - exclusion of injured, suspended and blank-gameweek players;
  - flagging of doubtful players and doubles;
  - backup GK position;
  - captain preference;
  - each refusal case;
  - the diff against both lineup sources;
  - the Bench Boost states;
  - UI escaping.
- **Verification:** the full suite, typecheck, build and `git diff --check` pass. There is a live visual check at desktop width and 375px.
- **Release:** none; this stays local.

---

# Closed task — Private FPL account data import (local only)

**Owner:** Programmer (Claude Opus 5.5, medium effort); review by a separate Opus 5.5 subagent at high effort, since this touches account data
**Status:** APPROVED
**Date:** 2026-09-25
**Milestone:** Use Overseer-captured FPL account data (selling prices, free transfers, bank, chips) when present, and unblock Candidate Lens.

## Context

Overseer decision 2026-09-25 (`ops/DECISIONS.md`): the Overseer signs in to FPL in the Claude browser pane. Claude reads `/api/my-team/{team_id}/` read-only and saves `local/private_team.json` with `schema_version`, `source`, `team_id`, `captured_at_utc`, and `my_team` (raw `picks`, `chips`, `transfers`, `picks_last_updated`). `local/` is gitignored, and `.dockerignore` allowlists it out of the image. Candidate Lens is currently always blocked because the public picks have no `selling_price` (`fpl_brief/candidates.py:60-62`).

## Required implementation

1. Add a new module `fpl_brief/private_team.py` that loads and strictly validates the file. It returns a summary whose `state` is one of `missing`, `invalid`, `mismatch`, `stale`, or `ready`, together with a message and the capture time/age.
   - When the state is `ready` or `stale`, it also returns free transfers (limit − made, floor 0; `unlimited` when the limit is null or the status is unlimited), transfers made, bank, hit cost, team value, per-player selling/purchase prices, and chips (name, status, played gameweeks, window).
   - `mismatch`: the `team_id` differs from config, or the pick element set differs from the public snapshot.
   - `stale`: the age is over `stale_after_hours`, or the current gameweek deadline passed after capture.
   - Invalid or unexpected shapes never crash and never produce partial numbers.
2. `lens()` accepts an optional private summary. When it is `ready`, affordability uses the account selling price plus bank, and the caveats name the source and capture time. Otherwise it stays blocked, with a message that says how to import the data. The existing public `selling_price` path and all other gates stay unchanged.
3. In `dashboard.py`, `/api/dashboard` includes `private_team`, and `/api/candidates` passes it to `lens()`. When the state is `ready`, the decision's `unconfirmed_inputs` line about free transfers and selling prices is replaced by an account-sourced statement with its capture time.
4. The Team Decision Desk UI gets an escaped "Your FPL account" panel. It shows the state/message, capture time, free transfers, bank, hit cost, value, and chips, labeled as account data that can go stale. It never says "transfer advice". The Candidate Lens hint text reflects the budget source.
5. README: document the capture procedure and the privacy boundary (local only, never committed or deployed, no credentials stored).

## Allowed paths

`fpl_brief/private_team.py` (new), `fpl_brief/candidates.py`, `dashboard.py`, `dashboard/app.ts` (added by the Supervisor 2026-09-25 for the `DashboardData.private_team` type and panel mount only), `dashboard/team-decision-desk.ts`, `dashboard/team-decision-desk.css`, `dashboard/desk-tools.ts`, `tests/test_private_team.py` (new), `tests/test_research_candidates.py`, `tests/test_dashboard.py`, `README.md`, `ops/IMPLEMENTATION_REPORT.md`. Do not change the chip ledger logic, the collectors, `data/`, or the hosting files.

## Acceptance criteria

- Fixture tests cover every loader state, including unlimited transfers, the deadline-based stale case, and malformed values (bools, negatives, wrong types, 14 picks).
- Lens tests cover `ready` private data producing the right budget and candidates, and non-ready data staying blocked with the import hint.
- An API test shows that `private_team` is present and that the missing state leaves behavior unchanged.
- The UI escapes all values.
- The full suite, typecheck, build, py_compile, and `git diff --check` all pass, and no test touches the network or the real `local/` file.

## Release boundary

Local only. No FPL write actions, no stored credentials, no commit, push, or deploy.

## Bounded follow-up — review findings and 24-hour freshness (2026-09-25)

Overseer approved these changes:

1. Account data goes stale after **24 hours** (`private_stale_after_hours`, default 24), independent of the snapshot limit. The deadline rule is unchanged.
2. Private data is served only when the server is bound to a loopback address. Otherwise the new `disabled` state carries no values, and Candidate Lens uses the public path.
3. Reject capture times with no timezone.
4. Compare the unrounded age.
5. Treat missing or unparseable current *and* next deadlines as `stale`.
6. Set `budget_source` to `account` only when the account branch ran.

Allowed paths are the same as above. Add tests for each item.

---

# Closed task — Railway build artifact and clean-checkout readiness

**Owner:** Programmer (Claude Opus 5.5 session, per Overseer handoff 2026-09-25)
**Status:** APPROVED
**Date:** 2026-09-25
**Milestone:** Make the reviewed TypeScript/Vite dashboard build and run from a clean checkout, and prepare a Railway-compatible image build, locally only.

## Context and Overseer decisions

- 2026-09-25 Supervisor inspection. The TypeScript migration, Team Decision Desk, and squad formation work are uncommitted. `HEAD` still tracks the legacy `dashboard/*.js`. `.gitignore` excludes `dashboard/dist/`, and `Procfile` runs `python dashboard.py` with no build step. When `dist/index.html` is absent, `dashboard.py:524` falls back to the source directory, whose `index.html:51` loads `/app.ts`. A browser cannot execute that file, so a clean checkout or host serves a non-working page and gives no clear error.
- Baseline on this checkout (2026-09-25): 82 Python tests, 10 Node tests, typecheck, build, py_compile, and `git diff --check` all pass.
- Overseer decision (2026-09-25): **build the frontend on the host**. `dashboard/dist/` stays ignored by Git.
- Overseer decision (2026-09-25): Claude implements as Programmer, and an **independent subagent** performs the Supervisor review. Work stops before any commit or push.
- Prior decisions stand: the dashboard is public and read-only with no password (Railway readiness task, 2026-09-22). No FPL login or write action. Shipped `data/` snapshots and `config.json` are public-FPL data only and are disposable on the server.

## Required implementation

1. Add a root `Dockerfile` with a multi-stage build. A Node stage runs `npm ci` and `npm run build` in `dashboard/` using `package-lock.json`. The runtime stage is Python slim, standard library only. It copies the application plus the built `dashboard/dist/`, contains no Node or `node_modules`, and starts `python dashboard.py` so the injected `PORT` is honored. Pin base image major/minor versions.
2. Add a root `.dockerignore` that excludes `.git`, `local/`, `dashboard/node_modules/`, `dashboard/dist/`, `cloud/`, `.openai/`, `.impeccable/`, `graphify-out/`, `__pycache__/`, `tests/`, `ops/`, and handoff/design markdown not needed at runtime. Do not exclude `data/`, `config.json`, `fpl_brief/`, or anything the server reads.
3. Change `dashboard.py` static serving so that a missing `dashboard/dist/index.html` no longer falls back to the unbuilt source directory. Static requests must return a clear `503` plain-text response saying the frontend bundle is missing and naming the build command. JSON API routes keep working. Path-traversal protection and existing cache headers are preserved.
4. Update `README.md` to describe the clean-checkout build, the Docker image build and local smoke run, and the rule that deployment still requires Overseer approval. Remove the outdated "falls back to the source directory" wording.
5. Leave `Procfile` unchanged. Railway prefers a root `Dockerfile`, and the README must state which one the host uses.

## Allowed paths

- `Dockerfile` (new)
- `.dockerignore` (new)
- `dashboard.py` (static serving only)
- `tests/test_dashboard.py`
- `README.md` (build/deploy sections only)
- `ops/IMPLEMENTATION_REPORT.md` (handoff only)

Do not edit dashboard TypeScript/CSS, collectors, `data/`, `config.json`, `cloud/`, `.openai/`, `.gitignore`, `Procfile`, `requirements.txt`, or other ops files. Do not create a `railway.json` or any Railway resource.

## Acceptance criteria and tests

1. Unit tests, with no network access, cover these cases: missing `dist` produces `503` with the build hint for `/` and for an asset path, and never serves `dashboard/index.html` or `.ts` source. Present `dist` serves `dist/index.html` and hashed assets with the correct content types. Traversal outside `dist` is `404`. API JSON is unaffected when `dist` is missing.
2. Existing suites pass: `python -m unittest discover -s tests -v`, `node --test tests/*.mjs`, `npm run typecheck --prefix dashboard`, `npm run build --prefix dashboard`, the py_compile set from the handoff, and `git diff --check`.
3. **Clean-checkout smoke.** Copy the files Git would ship (`git ls-files --cached --others --exclude-standard`, excluding deleted paths) into a scratch directory, and build the image there. Run it bound to `127.0.0.1` with an injected `PORT` (for example 18766). `/` returns `200` HTML that references a hashed `/assets/*.js`, that asset returns `200` JavaScript, and a read-only GET API returns JSON. No refresh or research POST is sent. The container and image are removed afterwards.
4. The runtime image contains no `node_modules` or TypeScript source, and does contain `dashboard/dist/index.html`.

## Release boundary

Local only. No commit, push, Docker registry push, Railway service, deployment, or public URL. Releasing later requires three things: the uncommitted migration work must be committed, this task must be APPROVED, and the Overseer must explicitly decide to release.

---

# Closed task — Away-Day Route Map dashboard redesign

**Owner:** Programmer (default: gpt-6-luna, high)
**Status:** APPROVED
**Date:** 2026-09-23
**Milestone:** Complete the approved responsive Away-Day Route Map redesign locally.

## Authorization and context

The Overseer approved replacing the prior visual direction with the Away-Day Route Map and a responsive hybrid: composition A above 1100 CSS pixels and composition B at or below 1100 pixels. Implementation is underway. The independent visual review found a P1 mobile clipping/overflow issue; fix it within this milestone.

The Railway task and review history remain preserved below. Its separate `ops/REVIEW.md` verdict remains **CHANGES_REQUESTED**; this redesign's whitespace follow-up passed and is recorded separately in `ops/REVIEW.md`. Railway upload/deployment remains **NOT APPROVED**. This task authorizes no push or deployment.

## Objective and allowed paths

Finish the redesign as a clear matchweek route while retaining real FPL content, existing features, and working interactions. The Programmer may change only:

- `DESIGN.md`
- `dashboard/index.html`
- `dashboard/redesign.css`
- `dashboard/wayfinding.js`
- `ops/IMPLEMENTATION_REPORT.md` (handoff report only)

No other application, test, workflow, review, deployment, or hosting paths may be edited without Supervisor scope expansion. Do not edit the report until implementation handoff.

## Acceptance criteria

1. Keep real FPL facts, existing features, and interactions; no sketch/example data may appear as product data.
2. Route Map links reach the corresponding real dashboard views and work with pointer and keyboard.
3. Composition A appears above 1100px; composition B appears at/below 1100px.
4. No unintended horizontal overflow or clipped content/actions at 360px and 430px mobile widths, tablet widths, and desktop widths. Specifically recheck the refresh control and warning/decision content identified by the visual reviewer.
5. Keyboard navigation works and focus is visibly indicated.
6. UI and `DESIGN.md` match the approved direction and responsive behavior.
7. Existing tests and relevant JavaScript syntax checks pass; `git diff --check` reports no whitespace errors.
8. On handoff, report changed paths, verification results, limitations, and mobile fix in `ops/IMPLEMENTATION_REPORT.md`, then set status to `IN_REVIEW`.

## Local verification and release boundary

Run `python -m unittest discover -s tests -v`, `node --check dashboard/wayfinding.js`, and `git diff --check` from the repo root. Also inspect mobile, tablet, and desktop widths for layout, route destinations, keyboard focus, clipping, and overflow. Do not commit, push, upload to Railway, deploy, modify hosting resources, or disclose a public URL. Railway remains blocked by the later `CHANGES_REQUESTED` review; a pass on this redesign alone is not release approval.

The 2026-09-23 Supervisor review returned `CHANGES_REQUESTED` solely because `git diff --check` found trailing whitespace on `ops/IMPLEMENTATION_REPORT.md:69`. Bounded follow-up: remove the trailing spaces on that date line only, rerun the Python test suite, relevant JavaScript syntax checks, and `git diff --check`, then return the task to `IN_REVIEW`. Do not alter unrelated work. The Programmer does not approve the task; the Supervisor records the next verdict in `ops/REVIEW.md`.

---

## Preserved prior task record — Railway readiness

The Railway task text below is retained verbatim. Its recorded `APPROVED` field predates the later review and is superseded for release purposes by the current `CHANGES_REQUESTED` / NOT APPROVED state above.

# Active task — Railway readiness for the Python Travel Dashboard

**Owner:** Programmer (default: gpt-5.6-luna, medium)
**Status:** APPROVED
**Date:** 2026-09-22
**Milestone:** Prepare the existing Python dashboard for public Railway travel access before 2026-10-06

## Prior product decision

The owner selected **Railway** for remote travel access and explicitly declined an application password. Public access is therefore intentional for this personal, read-only dashboard. Do not add authentication, credentials, secrets, a database, persistent storage service, or a scheduler.

The existing Railway project is `66736c2d-de72-4c2c-8144-aad85267636c`; its production environment is `8758f84d-723d-40ce-bc5a-5cba4deda278`. It has no service or deployment. The confirmed GitHub remote is `kokikokikokikokikoki/fpl-brief` on `main`.

The Cloudflare Worker route is superseded. Do not edit, test, repair, deploy, or otherwise resume `cloud/` or `.openai/hosting.json` in this task.

## Objective

Prepare the existing standard-library Python dashboard to run as a Railway web process while preserving its personal FPL workflow:

- read the current public FPL snapshot, squad, rivals, and player pool;
- manually refresh public FPL data;
- display research evidence and run the bounded fixed-source Research Scout manually on demand;
- retain Candidate Lens safety gates; and
- create and edit draft scenarios on the browser/device.

This task is local preparation only. Do not commit, push, create a Railway service, deploy, or expose a URL.

## Hosting and data boundaries

| Data/function | Railway process | Browser/device |
| --- | --- | --- |
| Public FPL snapshot, catalog, rival data | May be held in the existing local `data/` files while an instance lives. A restart can erase it; UI must show stale/missing state and offer manual refresh. | Reads the current response; no private FPL credential is used. |
| Fixed-source Research Scout | Explicit dashboard action only. Existing source allowlist, no-follow redirect, bounds, verbatim-only extraction, and no-claims rules remain unchanged. Research data on server disk is disposable after restart. | Shows source/freshness state and manual-collection result. |
| Candidate Lens | Uses the latest public snapshot and retains freshness, deadline, ownership, affordability, team-limit, and availability blocks. | Sends ordinary same-origin requests only. |
| Draft scenarios | No Railway filesystem write, database, or server persistence. | Uses a namespaced `localStorage` record, validates input, and labels drafts device-local and unsynchronized. |

The public URL is appropriate because the owner accepted no password and the application holds no secret/authenticated FPL data. Do not claim drafts, snapshots, research packets, or server disk are private or durable.

## Required implementation

1. Update `dashboard.py` to bind `0.0.0.0` and read a valid injected `PORT`, with a local default only when `PORT` is absent. Reject or fail clearly for invalid port values; do not hardcode Railway-specific credentials or hostnames.
2. Add a standard-library Railway start configuration using the existing Python entry point, for example a `Procfile` web command. Do not add dependencies solely for hosting.
3. Remove draft scenario dependence on `local/plans.json` and all server-side plan writes. Keep server-provided default draft data only as a nonpersistent starting template if useful.
4. Update dashboard client code so drafts are bounded and validated locally, persist through `localStorage`, and remain available across Railway instance restarts on the same browser/device. Explain device-local/non-sync behavior in the UI.
5. Preserve the existing `POST /api/refresh` public FPL refresh behavior and no FPL action. Make Research Scout collection an explicit same-origin dashboard action with a bounded request/job result and truthful error/freshness response. It must not schedule later runs.
6. Make missing/expired server snapshots and research data obvious in the dashboard. State that a Railway restart can require a manual refresh or research collection.
7. Preserve existing no-store JSON responses, plan validation constraints, Research Scout safety policy, Candidate Lens decision/legal gates, and safe client HTML/URL escaping.
8. Keep the app public and read-only. Do not add passwords, auth middleware, cookies, OAuth, environment secrets, Railway variables, outbound webhook endpoints, uploads, or a database.

## Allowed paths

The Programmer may change only:

- `dashboard.py`
- `dashboard/app.js`
- `dashboard/desk-tools.js`
- `dashboard/styles.css`
- `Procfile`
- `tests/test_dashboard.py`
- `tests/test_research_scout.py` only for dashboard-triggered manual-collection coverage if needed
- `README.md` only for local Railway start/prerequisite documentation
- `ops/IMPLEMENTATION_REPORT.md`

Do not edit `cloud/**`, `.openai/hosting.json`, FPL collector/source-policy modules, configuration, generated data, GitHub workflows, dependencies, deployment manifests other than `Procfile`, or workflow/review documents. Ask the Supervisor to expand scope before changing another path.

## Required regression coverage

All tests use fakes/fixtures and make no live FPL or Research Scout network call.

1. Dashboard startup selects `0.0.0.0` and an injected valid `PORT`; default local port behavior and invalid-port failure are tested.
2. Dashboard draft endpoints do not create/read/write `local/plans.json`; client draft lifecycle is local-only, bounded to four, validates names/player IDs against the current catalog before use, and handles corrupt/missing storage safely.
3. Existing manual FPL refresh remains explicit and reports a truthful result without FPL action.
4. Manual Research Scout action is explicit, uses the existing bounded collector with fake openers, does not follow redirects, has no schedule, and returns a truthful success/failure result.
5. Dashboard/API and UI make stale/missing ephemeral server data and device-local draft behavior visible.
6. Candidate Lens keeps current freshness, deadline, owned-player, selling-price, bank, team-limit, and availability checks.
7. Existing safe evidence escaping/link behavior continues to pass.

## Local verification commands

Run from repository root:

```powershell
python -m unittest discover -s tests -v
python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py
node --check dashboard/app.js
node --check dashboard/desk-tools.js
powershell -NoProfile -Command "$env:PORT='18765'; $proc=Start-Process -FilePath python -ArgumentList 'dashboard.py' -WindowStyle Hidden -PassThru; try { Start-Sleep -Seconds 2; $response=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18765/; if ($response.StatusCode -ne 200) { exit 1 }; 'railway-port-smoke-ok' } finally { if (!$proc.HasExited) { Stop-Process -Id $proc.Id -Force } }"
git diff --check
```

The smoke test must bind only locally through the injected test port and must not trigger refresh or research collection.

## Deployment prerequisites and release gate

Before any GitHub push, Railway service creation, production deployment, or public URL disclosure:

1. the Programmer completes this task and sets `IN_REVIEW` with local command evidence;
2. an independent review passes and the Supervisor marks the task `APPROVED`;
3. the Overseer explicitly decides to push `main` to `kokikokikokikokikoki/fpl-brief`, create the Railway service, and deploy to the stated production environment; and
4. the service is configured only then to run the reviewed `Procfile` web command with Railway’s injected `PORT`.

No deployment action is authorized by this preparation task.

## Handoff

When complete, set status to `IN_REVIEW` and update `ops/IMPLEMENTATION_REPORT.md` with changed paths, test results, Railway bind/start behavior, device-local draft boundary, manual refresh/research behavior, and a statement that no commit, push, service creation, deployment, public URL, secret, database, or schedule was created.

---
# Active task — Research Desk evidence integrity and usefulness

**Owner:** Programmer (default: gpt-6-luna, high)
**Supervisor/Reviewer:** gpt-6-sol, medium; review-only after programmer handoff.
**Status:** APPROVED
**Date:** 2026-09-24
**Milestone:** 1 of the approved local decision-support roadmap.

**Execution note:** The subagent could not write to this repository. At the Overseer's request, the current Codex task is temporarily acting as Programmer via the approval-gated patch route; an independent reviewer will inspect the handoff. Scope and allowed paths are unchanged.

## Objective

Repair the Research Desk so collected facts are identifiable, attributable, freshness-aware, and useful for the user's FPL squad. Correct the anonymous/misleading evidence shown in the current dashboard before adding more decision features.

This is the first bounded implementation milestone. The roadmap continues in later separately authorized tasks: (2) migrate the frontend from JavaScript to strict TypeScript using Vite while retaining Python as the server; (3) add a weekly transfer/roll Decision Desk with evidence and mini-league differentiation; (4) add an accessible formation view for the current XI and bench. These later milestones are not authorized by this task.

## Product and safety constraints

- Research collection remains deterministic and manually triggered through the existing bounded Research Scout. No LLM, automatic schedule, live collection in tests, new external source, broadened source allowlist, redirect following, or FPL account action.
- Never infer or fabricate a player, club, injury status, source, or fact. If an item cannot be joined reliably to a player/team, label it as unlinked/unknown and retain its source context.
- Preserve verbatim source text and reviewed/unreviewed distinctions. A successful fetch is not a verified claim.
- Show research freshness separately from FPL snapshot freshness. Preserve truthful captured, verified, stale, failed, and empty states.
- Preserve the current Away-Day Route Map visual direction. This is a focused Research Desk content/clarity fix, not another full redesign.
- Do not edit generated data under `data/` to make the screen look correct; fix the collector/API/rendering path and use deterministic fixtures.
- Local only. No commit, push, GitHub, Railway configuration, upload, deployment, or public URL.

## Active implementation scope

The Programmer may change only:

- `fpl_brief/research_scout.py`
- `fpl_brief/research.py`
- `dashboard.py` (Research API serialization only)
- `dashboard/desk-tools.js`
- `tests/test_research_scout.py`
- `tests/test_research_candidates.py`
- `tests/test_dashboard.py`
- `ops/IMPLEMENTATION_REPORT.md` (handoff report only)
- `ops/TASK.md` (status transition only; do not alter scope, acceptance criteria, or roadmap)

Do not change dashboard layout/style, FPL collection policy, generated files under `data/`, app hosting/startup, client draft behavior, or other paths without Supervisor approval and an updated task scope.

## Acceptance criteria

1. Where FPL player news can be joined by stable player ID, each displayed item shows the correct player and club. Unknown joins remain explicitly unknown; no name is guessed from free text.
2. Each evidence item has a meaningful source label/title, source link only when its URL passes existing safety checks, capture time, and an explicit evidence state. Valid records must not render as `JSON_FIELD` or `Untitled source`.
3. The collector selects relevant squad/player evidence before applying its item cap; it reports omitted counts or otherwise makes truncation visible. Selection/order is deterministic and bounded.
4. A successful collection with zero usable items is distinguishable from fetch failure, stale retained evidence, or not-yet-collected state. The UI does not imply that captured text is verified.
5. Research age and FPL snapshot age are presented independently, with clear timestamps/statuses; old data is not silently presented as current.
6. Existing schema migration, source allowlist, no-redirect/no-unsafe-link behavior, HTML escaping, and safe failure preservation continue to pass.
7. Regression tests cover identity joins, unknown identity, relevant-item selection beyond the cap, truncation, timestamps/state rendering, and existing security/migration cases. Tests use fixtures/fakes and make no network request.
8. `python -m unittest discover -s tests -v`, `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py`, `node --check dashboard/desk-tools.js`, and `git diff --check` pass. The report lists exact outcomes and changed paths.
9. On completion, Programmer records limitations and sets this task to `IN_REVIEW`; Programmer must not approve it.

## Handoff and next gate

The Programmer updates only the Research Desk handoff section in `ops/IMPLEMENTATION_REPORT.md`. The Supervisor inspects the actual diff and reruns the task checks, then records PASS/FAIL in `ops/REVIEW.md`. After PASS, create a separate TypeScript/Vite migration task with exact build, local serving, test, and deployment boundaries. Do not combine that migration with this Research Desk fix.

---
# Active task — Strict TypeScript/Vite dashboard migration

**Owner:** Programmer (default: gpt-6-luna, high)
**Supervisor/Reviewer:** gpt-6-sol, medium; review-only after programmer handoff.
**Status:** APPROVED
**Date:** 2026-09-24
**Milestone:** 2 of the approved local decision-support roadmap.

## Objective

Migrate the existing browser dashboard from plain JavaScript files to strict TypeScript, using Vite for development and production builds while retaining the existing Python `dashboard.py` server and all current user-facing behavior. This is an architecture/tooling migration only: no new FPL features, recommendation logic, layout redesign, live data collection, or hosting changes.

Use the existing model defaults in `ops/WORKFLOW.md`: gpt-6-luna high for this bounded implementation and gpt-6-sol medium for independent review. If those models are unavailable, stop and ask the Overseer before substituting.

## Required architecture and boundaries

- Inspect all four existing frontend scripts and document how shared state/functions are exposed before moving code. Preserve their behavior and ordering; use explicit typed interfaces/modules rather than weakening checks or relying on implicit global declarations.
- Use TypeScript with `strict: true`, Vite, npm lockfile, and no React. Do not add a framework or new runtime dependency unless the Supervisor first approves a scoped task update.
- Keep Python as the API/backend and static-file server. Vite is build/dev tooling only; it does not replace the Python API.
- Vite production output is `dashboard/dist/`, ignored by Git. Update the Python static serving path so it serves the built `dist` assets after a build. The local production-like check must build first, then start Python and load the built dashboard plus its existing APIs.
- Local development runs the Python server on `127.0.0.1:8765` and Vite on `127.0.0.1:5173`, with Vite proxying `/api` requests to the Python server. Document the two-terminal commands and expected URLs.
- Preserve device-local drafts, all existing API routes, safe escaping, keyboard behavior, visual design, and current Research Desk/Decision Desk functions. Do not change research source policy or refresh/collection behavior.
- This milestone is local only. Do not change `Procfile`, Railway/Nixpacks/build settings, production environment, hosting, or deployment configuration. Because ignored `dist` is not present in a clean deployment checkout, this task must explicitly leave production deployment blocked until a separately approved task defines the Railway build/artifact path. No commit, push, or deployment.

## Allowed paths

- `dashboard/app.js`, `dashboard/decision-states.js`, `dashboard/desk-tools.js`, `dashboard/wayfinding.js` (migrate to typed source files and remove old JS only after all imports/build/tests use the replacements)
- `dashboard/index.html`
- `dashboard/vite.config.ts`, `dashboard/tsconfig.json`, `dashboard/package.json`, `dashboard/package-lock.json`
- `dashboard.py` (static asset root only; preserve API/server behavior)
- `.gitignore` (ignore `dashboard/dist/`)
- `README.md` (local install, build, development, and run instructions)
- existing tests that read or execute migrated dashboard assets
- `ops/IMPLEMENTATION_REPORT.md` (handoff only)
- `ops/TASK.md` (status transition only; do not change this task’s scope/criteria)

No changes to `fpl_brief/`, `data/`, `cloud/`, `Procfile`, Railway configuration, secrets, workflows, or other paths without Supervisor approval and an updated task scope.

## Acceptance criteria

1. All production dashboard code is TypeScript; no legacy `.js` application source remains referenced or served. Vite output is deterministic and written only under ignored `dashboard/dist/`.
2. TypeScript compiler strict mode passes without `any` escapes, `@ts-ignore`, or disabling strict checks to make migration pass. Add typed models for existing API data, UI state, local drafts, and DOM handlers at module boundaries.
3. All current dashboard routes and interactions still work: overview, squad, wildcard drafts, rivals, player pool, Research Desk collection UI (without triggering collection during tests), Candidate Lens, navigation, and refresh control.
4. Existing Python/unit/Node tests are updated only as needed to target typed sources or built output; retain coverage for device-local drafts, safe HTML escaping, state feedback, Research Desk freshness/claims, and task-specific server behavior.
5. From a clean checkout with Node/npm installed: `npm ci` and `npm run typecheck` pass; `npm run build` succeeds and emits `dashboard/dist/index.html` plus referenced assets. No network-dependent tests or FPL calls are introduced.
6. Local dev: documented command starts Python at `http://127.0.0.1:8765`; documented Vite command serves the UI at `http://127.0.0.1:5173` and proxies existing `/api/*` calls to Python. Verify one API-backed view using local fixture/snapshot state, with no POST refresh or collection action.
7. Built local serving: after `npm run build`, starting `python dashboard.py` serves `/` and every emitted JS/CSS asset successfully; `/api/dashboard`, `/api/research`, and `/api/candidates` retain their existing behavior. Use an injected test port and bind only to loopback for the smoke check.
8. Preserve responsive behavior, visible focus, escaping, source link constraints, cache headers, and no-store API headers. Verify at 360px, 430px, 900px, and 1440px in a browser.
9. `npm run typecheck`, `npm run build`, `node --test tests/*.mjs`, `python -m unittest discover -s tests -v`, `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py`, and `git diff --check` pass. Report exact outcomes and changed paths; task is handed off as `IN_REVIEW`, never self-approved.
10. Verify `Procfile` and Railway configuration are unchanged. State explicitly that deployment is not approved and a separate deployment/build-artifact task is required before Railway can serve `dashboard/dist/`.

## Release boundary

This task authorizes local implementation and testing only. Do not commit, push, create or modify hosting resources, upload, deploy, or disclose a new public URL. After independent PASS, ask the Overseer whether to prepare the separate Railway build-artifact/deployment task; do not infer release approval from milestone approval.

## Bounded follow-up — escape dynamic Decision Desk content

The independent review found that `dashboard/app.ts` inserts `action.title` and `action.text` into overview `innerHTML` without escaping. `action.title` includes an FPL-provided player name from `fpl_brief/collect.py`; a controlled markup value was reproduced as raw HTML. Fix the overview rendering boundary and inspect adjacent overview interpolations that originate from API/snapshot data. Keep this follow-up local and narrow; do not change API/source policy, design, or other features.

Allowed follow-up paths: `dashboard/app.ts`, `tests/test_dashboard.py`, and `ops/IMPLEMENTATION_REPORT.md` for the programmer fix/handoff, plus this file for the status transition only. The Supervisor owns `ops/REVIEW.md`.

Acceptance: decision queue title and text render dynamic FPL content as text (markup is escaped); add a deterministic regression test that proves markup cannot become an element; verify existing overview values and all current interactions remain intact; `npm run typecheck`, `npm run build`, `python -m unittest discover -s tests -v`, `node --test tests/*.mjs`, Python compile check, and `git diff --check` pass. Programmer returned the migration to `IN_REVIEW`; GPT-6 Sol independently repeated the review and approved the migration milestone. The follow-up details and findings remain recorded above and in `ops/REVIEW.md`.

---

# Active task — Accessible squad formation view

**Owner:** Programmer (default: gpt-6-luna, high)
**Supervisor/Reviewer:** gpt-6-sol, medium; review-only after programmer handoff.
**Status:** APPROVED
**Date:** 2026-09-24
**Milestone:** 3 of the approved local decision-support roadmap.

## Objective

Replace the current text-heavy squad presentation with a responsive, pitch-style visualization of the current public FPL picks, while retaining an equivalent accessible list/table alternative. This is a read-only view of the saved public squad and bench order—not lineup, captain, transfer, or points advice.

## Product and design constraints

- Extend the existing Away-Day Route Map visual system; do not redesign the dashboard or change `DESIGN.md`.
- The current public squad snapshot supplies picks and FPL catalog metadata. Do not imply access to intended future changes, private transfer state, or unsubmitted lineup choices.
- Organize players by their actual FPL position (GK/DEF/MID/FWD); derive any displayed shape/counts directly from the selected saved picks and label it as the snapshot shape, not a recommendation.
- Preserve captain/vice-captain markers, current FPL availability warning semantics, and exact bench order (`position` 12–15). Status must always have text, not color alone.
- Unknown player/catalog joins must render safely as unknown; never omit a pick or invent a club, fixture, role, or status.
- Pitch view and list alternative must expose equivalent squad facts. Prefer semantic HTML, native keyboard-operable toggle buttons, visible focus, and screen-reader labels.
- Keep every dynamic player/API value escaped before HTML insertion. No new backend/API, account action, dependency, library, FPL fetch, or persistence behavior.
- Local only. No commit, push, Railway change, upload, deployment, or public URL.

## Allowed paths

- `dashboard/app.ts`
- `dashboard/squad-formation.ts` (new typed presentation module, if useful)
- `dashboard/squad-formation.css` (new focused stylesheet, if useful; import through Vite)
- `tests/test_dashboard.py` (deterministic fake-data coverage only)
- `ops/IMPLEMENTATION_REPORT.md` (Programmer handoff)
- `ops/TASK.md` (status transition only; do not alter scope/criteria)

Do not edit `dashboard.py`, API/data collectors, generated `data/`, global design tokens, `DESIGN.md`, deployment files, other tests, or other UI features.

## Acceptance criteria

1. The My Squad view shows the saved XI as a pitch-like positional layout and the four substitutes in exact snapshot bench order, with an explicit timestamp/gameweek context.
2. Captain and vice-captain identity, player name, team (when known), and meaningful FPL availability risk are visibly and textually indicated. No unsupported fixture, minutes, projection, or lineup claim is introduced.
3. A keyboard-operable Pitch/List control switches between equivalent views. The list is semantic and screen-reader understandable; focus is visible and state is exposed (for example with `aria-pressed`).
4. FPL player/catalog text is safely escaped; unknown/missing players remain visible with truthful fallbacks. Empty or incomplete picks are handled without throwing.
5. Formation and bench layout fit 360px, 430px, 900px, and 1440px without unintended document overflow; the established section navigation remains usable.
6. Existing dashboard behavior, Research Desk, Decision Desk, Candidate Lens, and device-local drafts remain unchanged. No network collection is triggered by tests.
7. Add deterministic tests for derived positional grouping/shape, captain labels, bench ordering, unknown joins, escaping, empty data, and view-toggle semantics as practical. `npm run typecheck`, `npm run build`, `python -m unittest discover -s tests -v`, `node --test tests/*.mjs`, Python compile check, and `git diff --check` pass.
8. Verify the local built app visually at the four specified widths and test keyboard toggling. Programmer documents exact checks and limitations then sets status to `IN_REVIEW`; do not self-approve.

## Release boundary

After independent PASS, the formation milestone may close locally. Railway remains unapproved because the built `dashboard/dist/` artifact path is not configured for a clean deployment checkout. This task grants no hosting or release authority.

## Bounded follow-up — Pitch/List fact parity and responsive visual verification

The independent review returned FAIL. Fix only the following findings; keep this local and do not change unrelated application behavior.

**Follow-up status:** RESOLVED — independent PASS recorded in `ops/REVIEW.md` on 2026-09-24.

Allowed paths remain limited to `dashboard/squad-formation.ts`, `dashboard/squad-formation.css`, `tests/test_dashboard.py`, and `ops/IMPLEMENTATION_REPORT.md` for the Programmer. The Supervisor owns task/review status and review notes.

1. Make every squad fact shown in List also visibly available in Pitch, including price, form, total points, and the FPL next-round estimate. Keep the pitch legible and avoid presenting `ep_next` as a promise. An accessibility-only hidden span does not meet visible fact parity.
2. Strengthen deterministic fake-data tests to compare each view's rendered player facts, not merely assert that facts appear somewhere in the combined HTML. Retain the escaping, unknown-player, empty-state, captaincy, and saved bench-order regressions.
3. Recheck document overflow and visually inspect the local built view at 360px, 430px, 900px, and 1440px using the browser viewport controls available to the reviewer. Record exact widths and any tooling limitation honestly; do not claim a visual check that was not performed.
4. Rerun typecheck, build, full Python and Node suites, Python compile check, and `git diff --check`. Update the Programmer handoff and return this task to `IN_REVIEW`; do not self-approve.

No dependency, backend/API, FPL data, design-token, deployment, commit, push, upload, or Railway changes are authorized by this follow-up.

---

# Active task — Team decision and chip status desk

**Owner:** Programmer (default: gpt-6-luna, high)
**Supervisor/Reviewer:** gpt-6-sol, medium; review-only after handoff.
**Status:** APPROVED
**Date:** 2026-09-24

## Objective

Make the dashboard useful for weekly decisions about the manager's actual squad. Add a compact team decision view that brings together current public FPL player stats, upcoming fixtures, availability and attributable Research Desk items. Add a chip ledger that reports chips used and still available from official season rules plus the manager's recorded chip history. Keep all recommendations auditable, qualified, and read-only.

## Product constraints

- Keep the existing Away-Day Route Map visual system and dashboard architecture. This is a focused functional addition, not a redesign.
- Use only existing public FPL data and the allowlisted Research Desk packet. Never claim access to private intent, unsubmitted transfers, confirmed club lineups, or proprietary projections.
- Distinguish verified/current official FPL status, captured-but-unverified research excerpts, FPL estimates, and derived metrics in labels and copy. Show timestamps/source links where available; stale or invalid evidence cannot drive a recommendation.
- Do not invent point forecasts, certainty, a form cutoff, or a transfer imperative from one statistic. Every derived status must expose the facts/rule that triggered it. When evidence is insufficient, say “Not enough current evidence” and give the next useful step.
- Prefer decision priorities (resolve availability, investigate minutes/role, compare alternatives, or no urgent action) over a forced buy/sell label. Link into the existing Candidate Lens for legal replacement comparisons; do not duplicate its selection logic.
- Chip inventory must come from official season chip definitions returned by FPL bootstrap data and the manager's recorded `/history/` chip plays. Correctly handle repeat chips/counts (including multiple Wildcards), mapping the FPL API chip identifiers to human labels. If either source is absent, invalid, or stale, show an explicit unknown state rather than guessing availability.
- Keep all API/research text escaped and keyboard/screen-reader accessible. Retain the existing read-only and local-only boundaries.

## Allowed paths

- `fetch_fpl.py` and/or `fpl_brief/collect.py` (persist the minimum official chip-rule metadata needed from the already-fetched bootstrap response)
- `dashboard.py` (read-only dashboard API serialization only, if needed)
- `dashboard/app.ts`, `dashboard/desk-tools.ts`, `dashboard/decision-states.ts`, `dashboard/squad-formation.ts`, `dashboard/styles.css`, `dashboard/redesign.css`, plus one focused typed module/style if required
- Relevant deterministic tests: `tests/test_fetch_fpl.py`, `tests/test_dashboard.py`, and/or a focused test module
- `ops/IMPLEMENTATION_REPORT.md` (Programmer handoff only)
- `ops/TASK.md` (status transitions only; do not alter this task's scope or acceptance criteria)

Preserve existing unrelated dirty work. Do not rewrite the Research Desk collector/source allowlist or existing user files/data. No new runtime dependency, authentication, external account action, FPL POST, refresh/research side effect from rendering, deployment configuration, commit, push, or Railway change.

## Acceptance criteria

1. Overview or a clearly named dashboard destination provides a useful decision desk for all 15 owned players, prioritizing actionable official availability risk and presenting the current relevant stats and upcoming fixtures from the saved snapshot. Missing joins remain visible with honest fallbacks.
2. For each surfaced priority, show the precise reason and underlying source/facts. Match Research Desk evidence to a player only through stable player ID; unverified/stale text is visibly labeled and never silently upgraded to confirmed team news. No invented forecast or unsupported player verdict.
3. The manager can move from a flagged player to the existing Candidate Lens for an eligible replacement comparison. The decision view clearly says when freshness, incomplete data, or lack of evidence prevents a useful call.
4. A chip ledger shows each season chip, used count and gameweek(s), and remaining/available count from official current-season chip definitions joined with manager history. Repeatable chips are represented correctly. Missing or inconsistent chip metadata produces “unknown” rather than a false available/used state.
5. All dynamic FPL/research fields are safely escaped; controls work by keyboard with visible focus and accessible names/state; the view fits the existing mobile/desktop layout.
6. Tests cover chip mapping/counts/repeatability/unknown inputs, squad-player join and priority/freshness behavior, stale/unverified evidence handling, and XSS-safe UI output using fake fixtures only. Tests trigger no network calls or collection actions.
7. `npm run typecheck`, `npm run build`, `python -m unittest discover -s tests -v`, `node --test tests/*.mjs`, relevant Python compile checks, and `git diff --check` pass. Run the Impeccable detector once on changed UI targets and report its exact result.
8. Programmer records changed files, verification, limits and unresolved concerns in `ops/IMPLEMENTATION_REPORT.md`, then sets this task to `IN_REVIEW`. Programmer does not self-approve. Supervisor independently inspects the diff and reruns relevant checks before recording PASS/FAIL in `ops/REVIEW.md`.

## Release boundary

Local implementation only. Do not commit, push, upload, deploy, or change Railway. This feature does not remove the existing deployment/build-artifact blocker.

## Bounded follow-up — complete chip inventory and evidence sufficiency

**Follow-up status:** CHANGES_REQUESTED after independent review on 2026-09-24.

The independent reviewer found that an official chip definition with an unfamiliar name is silently skipped while the overall ledger can still report `known` (`dashboard.py` chip-rule normalization and final state). A separate in-memory reproduction found that a player with no minutes, no fixtures, and no linked research can still receive “No official availability flag,” which can look reassuring without enough evidence. The local preview also showed that a stale/legacy snapshot with recorded GW2/GW4 chip plays renders all chip usage as Unknown, rather than preserving the usable history while withholding only availability.

Keep the existing architecture and original allowed paths. The Programmer may additionally update the existing/new focused chip/team-decision tests and `ops/IMPLEMENTATION_REPORT.md`; the Supervisor owns this follow-up and `ops/REVIEW.md`.

1. Represent every official bootstrap chip rule. For an unrecognized official chip name, render a safely labeled row and mark its availability/interpretation unknown, or mark the inventory incomplete with the unknown rule visibly identified. Never skip an official rule and report the complete inventory as known. Reconcile its manager-history plays where possible; unmatched records remain explicitly unknown.
2. Separate historical use from current availability. When manager chip history is valid but season rules are missing, stale, or inconsistent, retain each safely recognized used chip and gameweek as “recorded in snapshot”; mark availability unknown with the reason. Never infer unused chips as available from history alone. With both valid rules and history, keep the existing official-window calculation, including first/second-half chip instances.
3. Make evidence sufficiency explicit. A lack of FPL injury flag must not imply a hold/transfer verdict when decision-critical inputs are absent. For a fresh snapshot with missing meaningful player minutes/stats, relevant fixtures, or other required context, say “Not enough current evidence” and give the next useful action. For a complete row with no official availability flag, state plainly that this is only an availability fact and not a transfer recommendation. Add deterministic regressions for both cases; do not invent point forecasts or thresholds.
4. Preserve current safeguards: stale snapshots cannot support current player decisions; captured research remains unverified/stale as appropriate and joins only by stable player ID; dynamic values remain escaped; Candidate Lens navigation continues to select the outgoing player.
5. Update fixtures to include at least one unfamiliar but structurally valid official chip rule and test that it cannot disappear behind an overall `known` status; test history-only display with absent/stale rules; test evidence insufficiency and the explicit non-recommendation state.
6. Rerun `npm run typecheck`, `npm run build`, full Python and Node suites, compile checks, `git diff --check`, and the Impeccable detector once on any changed UI targets. Programmer updates the implementation report and returns the task to `IN_REVIEW`; no self-approval.

No live data refresh/research, user data rewrite, commit, push, deployment, or Railway modification is authorized.

## Bounded follow-up 2 — preserve unknown chips in stale snapshots and accurate summary

**Follow-up status:** CHANGES_REQUESTED after independent re-review on 2026-09-24.

The second independent review found two remaining issues. The stale-snapshot and missing-gameweek early returns list only the four known chip types, so an unfamiliar official chip and any matching recorded play disappear even though fresh-rule rendering exposes it. Also, the decision summary counts all non-default statuses as “flagged,” then says those players have an availability flag, incomplete join, or FPL note; this is inaccurate for a complete player join with missing minutes/fixtures.

1. Preserve every recognizable official chip definition and matching manager-history play in all ledger states, including stale snapshots and missing current gameweek metadata. Use the safely escaped official name and recorded gameweek; mark chip interpretation/current availability unknown rather than dropping the row or guessing. Keep unmatched/invalid history visible as an explicit unknown record. Add tests for the unfamiliar chip on stale and missing-gameweek paths.
2. Make the desk summary describe the actual reason categories it counts. Distinguish official availability flags, incomplete player joins, FPL notes, and insufficient stats/fixture evidence; do not claim one cause for a different cause. Add a deterministic renderer/backend case for a complete joined player with zero minutes and no fixtures and verify the summary’s wording is accurate.
3. Re-run full required tests, typecheck, build, compile checks, `git diff --check`, and the Impeccable detector once on any changed UI targets. Update the handoff and return to `IN_REVIEW`; do not self-approve.

No live refresh/research, deployment, commit, push, or Railway change.

**Final status:** APPROVED LOCALLY after independent review of the fourth bounded follow-up on 2026-09-24. Narrow/mobile viewport visual inspection was not completed; the tables use horizontal scrolling and responsive layout rules, but that visual check remains an explicit limitation. Railway/deployment remains separately blocked and unapproved.

## Bounded follow-up 4 — keep malformed official rules distinct

**Follow-up status:** CHANGES_REQUESTED after independent review on 2026-09-24.

The fourth independent review found that multiple official rules with both blank names and unusable IDs collapse to one generic row in all ledger branches. This prevents the interface from accounting for every official chip-rule record.

1. Give each malformed rule without a usable name or ID its own stable, safely rendered row identity (for example an ordinal rule label). Do not deduplicate separate official bootstrap records merely because both lack identity fields. Keep each row's interpretation/availability unknown and keep overall ledger state partial/unknown, never known.
2. Add a deterministic fixture containing at least two such malformed rule records and assert the fresh, stale, and missing-gameweek ledgers each render two distinct unknown rows. Preserve all existing named/ID rule behavior and manager-history labeling.
3. Run the full task tests/checks, update the Programmer handoff, and return the task to `IN_REVIEW`. The Impeccable detector need not rerun unless UI files change.

No live refresh/research, deployment, commit, push, or Railway change.

## Bounded follow-up 3 — account for official chip rules without names

**Follow-up status:** IN_REVIEW; Programmer handoff on 2026-09-24.

The third independent review found that stale/missing-gameweek inventory construction only pre-registers unrecognized official chips with nonblank string names. A structurally present official rule with an integer ID but missing/blank name is labelled `Unrecognized chip (ID 9)` in the fresh path, yet omitted from the stale and missing-gameweek paths.

1. Include every official rule in every ledger state. For a missing/blank name, keep a stable safe label such as `Unrecognized chip (ID N)` based on a valid rule ID; if neither a usable name nor ID is available, include a generic “Unrecognized official chip rule” row. In all cases, keep interpretation and availability unknown; do not mark the inventory complete.
2. Add deterministic tests for blank-name official rules with a valid integer ID across fresh, stale, and missing-current-gameweek cases. Assert the row remains visible and availability is never inferred. Unmatched manager history stays explicitly unknown.
3. Rerun the required full checks; rerun Impeccable only if UI files change. Return the task to `IN_REVIEW` for another independent review.

No live refresh/research, deployment, commit, push, or Railway change.
