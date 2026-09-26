# Supervisor review

**Task:** Hosted dashboard loading-state fix within Railway readiness
**Date:** 2026-09-23
**Verdict:** **FAIL — CHANGES_REQUESTED**

## Scope and findings

I reviewed the uncommitted bounded change, its tests, and the current source. The implementation satisfies the requested functional acceptance criteria:

- dashboard/index.html:9 places app.js, decision-states.js, and desk-tools.js inside body and before its closing tag. Each script is deferred, in deterministic app, decision, then desk order.
- dashboard.py:90-97 retains Cache-Control: no-store for JSON API responses. dashboard.py:192-203 adds Cache-Control: public, max-age=300 to static assets, limiting stale dashboard assets without changing API caching.
- tests/test_dashboard.py:111-132 provides executable coverage for script placement/order and static-versus-API cache headers.
- The actual source diff is limited to dashboard/index.html, dashboard.py, tests/test_dashboard.py, and the Programmer report. It makes no FPL, Research Scout, dashboard semantic, Railway-access, Git, hosting, deployment, or public-access change.

## Independent verification

- python -m unittest discover -s tests -v — **exit 0; 54 tests passed**, including HostedLoadTests.
- python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py — **exit 0**.
- node --check dashboard/app.js; node --check dashboard/decision-states.js; node --check dashboard/desk-tools.js — **exit 0**.
- Injected-port local smoke command — **exit 0; railway-port-smoke-ok**.
- git diff --check — **FAIL**:
  - dashboard.py:229: new blank line at EOF.
  - dashboard/index.html:10: new blank line at EOF.

## Required repair

Remove the extra end-of-file blank line in dashboard.py and dashboard/index.html, then rerun git diff --check. No functional rework is required. Do not commit, push, deploy, create Railway resources, or change hosting configuration.

## Away-Day Route Map redesign — Supervisor review

**Task:** Away-Day Route Map dashboard redesign (local milestone)
**Date:** 2026-09-23
**Verdict:** **FAIL — CHANGES_REQUESTED**

### Scope and findings

Reviewed the current worktree changes for `DESIGN.md`, `dashboard/index.html`, `dashboard/redesign.css`, `dashboard/wayfinding.js`, and the handoff in `ops/IMPLEMENTATION_REPORT.md`. The earlier Railway review above is retained unchanged and remains a separate release blocker.

- **[P2] Diff check fails on handoff whitespace.** `ops/IMPLEMENTATION_REPORT.md:69` has two trailing spaces after the date. This violates the active task's explicit `git diff --check` acceptance gate. Programmer follow-up is limited to removing that trailing whitespace and rerunning the required checks. The report was not edited during this review.
- Route destinations are wired to existing dashboard view IDs: `rivals`, `squad`, `players`, and `wildcard` (`dashboard/wayfinding.js:2-5`); the delegated handler calls the existing `activate` function (`dashboard/wayfinding.js:22-25`, `dashboard/app.js:23`).
- Keyboard-operable native buttons and visible `:focus-visible` styling are present (`dashboard/wayfinding.js:16`, `dashboard/redesign.css:23`).
- The handoff records fresh responsive measurements at 360px and 430px (document width equals viewport and the refresh, warning, and decision boxes end at x=344/x=414), plus fit at 900px and 1440px. The reported independent visual reviewer passed all four widths, route destinations, and keyboard focus. The responsive CSS includes the <=1100px vertical route and <=600px single-column refresh control (`dashboard/redesign.css:143-184`).

### Independent verification

- `python -m unittest discover -s tests -v` — **PASS; 55 tests**.
- `node --check dashboard/wayfinding.js`, `dashboard/app.js`, `dashboard/decision-states.js`, and `dashboard/desk-tools.js` — **PASS**.
- `git diff --check` — **FAIL**; `ops/IMPLEMENTATION_REPORT.md:69` trailing whitespace. Other output consisted of LF/CRLF notices.

### Required repair and release state

Remove the trailing spaces at `ops/IMPLEMENTATION_REPORT.md:69` and rerun the acceptance checks before resubmitting. No application code or report was changed by this review. This local UI review authorizes no commit, push, Railway upload, or deployment. Railway remains **NOT APPROVED**: the earlier `CHANGES_REQUESTED` review is unresolved, and explicit Overseer release authorization is still required.

## Away-Day Route Map whitespace repair — Supervisor follow-up

**Date:** 2026-09-24
**Verdict:** **PASS — APPROVED**

The sole open finding was two trailing spaces on `ops/IMPLEMENTATION_REPORT.md:69`. They were removed without changing the surrounding handoff. Independent read-only review confirmed the exact line is clean. Supervisor verification:

- `python -m unittest discover -s tests -v` — **PASS; 55 tests**.
- `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py` — **PASS**.
- `node --check dashboard/wayfinding.js`, `dashboard/app.js`, `dashboard/decision-states.js`, and `dashboard/desk-tools.js` — **PASS**.
- `git diff --check` — **PASS**; only LF/CRLF notices.

This approval closes only the local Away-Day Route Map milestone. It does not approve the separate Railway readiness task or any commit, push, upload, or deployment.

## Research Desk evidence integrity and usefulness — Supervisor review

**Task:** Research Desk evidence integrity and usefulness (local milestone)
**Date:** 2026-09-24
**Verdict:** **PASS — APPROVED**

### Scope and findings

The independent reviewer inspected the final scoped changes against `ops/TASK.md` and found no remaining acceptance-criteria issues. Three review iterations identified and resolved issues before this final PASS: stale evidence being made to look ready by unrelated fresh sources; successful collection attempts retaining an old attempt timestamp; and missing per-claim capture-time display. Invalid packet contents are also hidden from the Research Desk.

- `fpl_brief/research.py:198` uses each excerpt and claim timestamp for evidence freshness; source-level summaries expose stale item indexes. The mixed-source and recently-fetched/old-item regressions pass.
- `fpl_brief/research_scout.py:238` refreshes `attempted_at_utc` on a successful collection as well as on failures.
- `dashboard/desk-tools.js:73` shows claim capture and review times; excerpts show player/club attribution and capture time. Invalid packet records are not rendered as usable evidence.
- Bounded player prioritization, omitted-item counts, schema migration, allowlist/no-redirect behavior, safe links, HTML escaping, and separate FPL snapshot freshness remain covered.

### Independent verification

- `python -m unittest discover -s tests -v` — **PASS; 67 tests**.
- `python -m py_compile dashboard.py fpl_brief/research_scout.py fpl_brief/research.py` — **PASS**.
- `node --check dashboard/desk-tools.js` — **PASS**.
- `git diff --check` — **PASS**; only existing LF/CRLF notices.

No live FPL or research collection was run. This approval is for the local Research Desk milestone only; no commit, push, Railway configuration, upload, or deployment is authorized. The earlier Railway readiness task remains separately **CHANGES_REQUESTED / NOT APPROVED**.

## Strict TypeScript/Vite dashboard migration — Supervisor review

**Task:** Strict TypeScript/Vite dashboard migration (Milestone 2)
**Date:** 2026-09-24
**Verdict:** **FAIL — CHANGES_REQUESTED**

### Finding

- **[P1] Unescaped public FPL player name reaches `innerHTML`.** `fpl_brief/collect.py:29` copies `player["web_name"]` into availability data. `dashboard/app.ts:245` interpolates the generated `action.title` and `action.text` into `#overview.innerHTML` without HTML escaping; the title contains that FPL-provided name. The independent reviewer verified with a controlled markup name that it appears as raw markup in the decision queue, while the availability table separately escapes the same name. This violates the migration task's requirement to preserve safe escaping. The existing Research Desk escaping test (`tests/test_dashboard.py:156`) does not cover the decision queue.

### Independent verification

- `npm ci` — PASS (16 packages; 0 audit vulnerabilities).
- `npm run typecheck` and `npm run build` — PASS.
- `python -m unittest discover -s tests -v` — PASS; 67 tests.
- `node --test tests/*.mjs` — PASS; 10 tests.
- Python compile checks and `git diff --check` — PASS.
- Local Python serving: `/`, emitted assets, `/api/dashboard`, `/api/research` returned 200; Candidate Lens returned its expected JSON safety-blocked 409 for the deliberately invalid replacement ID.
- Browser checks: all seven views loaded; no document overflow at 360, 430, 900, or 1440px; keyboard navigation and visible focus passed. The migration did not change responsive styles.
- `Procfile` has no tracked diff; Railway deployment remains explicitly blocked pending a separate build-artifact task.

### Required follow-up

Escape all API-derived text inserted into the Decision Desk's decision queue and audit adjacent dynamic overview interpolations. Add a deterministic regression test proving a markup-like player name is rendered literally, then rerun the task checks. The bounded follow-up is recorded in `ops/TASK.md`. No application/report files were changed by the reviewer, and no refresh, research collection, commit, push, or deployment was performed.

## Strict TypeScript/Vite migration escaping follow-up — Supervisor re-review

**Task:** Bounded escaping repair for the Decision Desk overview
**Date:** 2026-09-24
**Verdict:** **PASS — APPROVED**

- `dashboard/app.ts` now escapes decision-queue titles/text and adjacent API-derived overview values before assigning `innerHTML`; fixed CSS class values remain local constants.
- `tests/test_dashboard.py` includes a fake-snapshot markup regression proving hostile `img`/`svg` strings do not become active markup.
- Independent focused dashboard tests — PASS (18/18); full Python suite — PASS (68/68); Node tests — PASS (10/10); strict typecheck, Python compile checks, and `git diff --check` — PASS. The Programmer separately reports the Vite build passed and the bundle reflects the updated source; the reviewer did not rerun the build or browser viewport checks in review-only mode.
- Task/report remain `IN_REVIEW`; unrelated dirty work was preserved. No refresh, research collection, commit, push, or deployment was performed.

This PASS approves the TypeScript/Vite migration milestone including its escaping follow-up. It does not authorize Railway deployment. The next separately scoped local milestone is the accessible squad formation view.

## Accessible squad formation view — independent review

**Task:** Accessible squad formation view (Milestone 3)
**Date:** 2026-09-24
**Verdict:** **FAIL — CHANGES_REQUESTED**

### Finding

- **[P1] Pitch and List do not expose equivalent squad facts.** The List table renders price, form, total points, and the FPL next-round estimate in `dashboard/squad-formation.ts:102`. Pitch cards omit price, and their form/points/estimate span is hidden with `display: none` in `dashboard/squad-formation.css:26` (markup at `dashboard/squad-formation.ts:98`). Therefore a user switching to Pitch loses facts available in List, contrary to the active task's view-equivalence requirement. The current regression only checks these strings in the combined HTML, so it does not detect the visible-view mismatch (`tests/test_dashboard.py:156`).

### Checks

- Independent reviewer: typecheck, production build, 69 Python tests, 10 Node tests, Python compile check, and `git diff --check` — **PASS**.
- Keyboard toggling in both directions, `aria-pressed`, panel visibility, semantic list table, and visible focus — **PASS**.
- Independent browser measurements report no document overflow at 360, 430, 900, or 1440px; section navigation remains available. Full visual inspection at every target width was not completed and remains unverified.
- Saved-pick positional grouping, descriptive snapshot shape, captain/vice labels, saved bench ordering, safe escaping, unknown-player fallback, and no-lineup-advice wording — **PASS**.

### Required follow-up

Make all player facts visible in both modes, including price, form, total points, and the FPL `ep_next` estimate; strengthen tests to validate each mode separately; and complete/report the specified responsive visual checks as far as the browser controls permit. The bounded follow-up and allowed paths are recorded in `ops/TASK.md`. No code or handoff report was changed by the reviewer. No FPL collection, commit, push, Railway change, upload, or deployment was performed. Railway remains **NOT APPROVED**.

## Accessible squad formation view — Supervisor re-review

**Task:** Accessible squad formation view (Milestone 3)
**Date:** 2026-09-24
**Verdict:** **PASS — APPROVED LOCALLY**

The independent reviewer confirmed that the bounded follow-up resolved the sole code finding: Pitch now visibly presents price, form, total points, and the FPL next-round estimate with a caveat, and the deterministic regression compares the same player's information in Pitch and List separately. Existing escaping, unknown-player handling, availability text, captain/vice labels, semantic list, and saved bench order remain covered.

Independent responsive and interaction review completed with full, inspectable squad-panel captures at 360px, 430px, 900px, and 1440px. The complete XI and bench, data labels, estimate caveat, and section navigation were legible; document width matched viewport width with no clipping or overflow at all four widths. Keyboard switching, visible focus, `aria-pressed`, and all 15 semantic-list rows passed.

Supervisor reran `npm run typecheck`, `npm run build`, `python -m unittest discover -s tests -v` (**69 passed**), `node --test tests/*.mjs` (**10 passed**), Python compile checks, and `git diff --check` — **PASS**. Independent review also reran the automated checks — **PASS**. The Programmer ran the Impeccable detector once, with no findings; it was not rerun during review.

This approves the local squad-formation milestone only. No FPL refresh/research collection, commit, push, Railway change, upload, or deployment occurred. Railway remains **NOT APPROVED**; a separate deployment/artifact task and explicit Overseer release decision are still required.

## Team decision and chip status desk — independent review

**Task:** Team decision and chip status desk
**Date:** 2026-09-24
**Verdict:** **FAIL — CHANGES_REQUESTED**

### Findings

- **[P1] Unrecognized official chips are omitted while the ledger can report complete.** `dashboard.py` chip normalization skips a bootstrap rule when `_chip_key()` does not recognize its name, then the final status only checks the four hard-coded rows. An added valid chip definition was therefore absent from the UI while the ledger reported `known`. Preserve every rule in the inventory; surface an unknown official chip (or mark the inventory incomplete and identify it) instead of silently dropping it.
- **[P1] Recorded chip use disappears when rule data is stale or missing.** `chip_ledger()` returns four generic unknown rows before reconciling the valid manager history whenever the snapshot is stale or the rules array is absent. The current saved snapshot does contain the user's recorded GW2 Triple Captain and GW4 Wildcard plays but predates persisted rule metadata; the preview consequently shows `Unknown` for both used-history and availability. Preserve clearly timestamped history as “recorded in snapshot,” while leaving availability unknown unless current official rule windows are valid.
- **[P2] “No official availability flag” is not a sufficient decision status when core evidence is absent.** `build_team_decision()` assigns that status independently of minutes, fixture coverage, or linked research. A fake player with zero minutes, no fixtures, and no research still received the reassuring-looking default. For incomplete evidence, show “Not enough current evidence” and an explicit next step; for complete unflagged players, state that this is only an availability fact and not a transfer recommendation.

### Independent checks

- 74 Python tests, 10 Node tests, TypeScript typecheck, Vite production build, Python compile checks, and `git diff --check` — **PASS**.
- The Impeccable detector was run once by the Programmer and reported no findings.
- I loaded the built dashboard on a fresh loopback server and verified the decision desk renders, includes all 15 saved picks, joins research by player ID, labels captured material unverified, and blocks current conclusions for the stale snapshot. This was an accessibility-tree inspection; viewport-by-viewport visual inspection remains unverified.
- A read-only check of official FPL metadata confirmed numeric chip-rule IDs and split-season windows. No snapshot refresh or research collection was triggered.

### Required follow-up

The bounded chip-inventory, history-retention, and evidence-sufficiency follow-up is recorded in `ops/TASK.md`. Programmer must fix only those findings and return the task to `IN_REVIEW`. Supervisor will inspect and rerun checks before approval. No commit, push, deployment, or Railway change is approved.

## Team decision and chip status desk — second independent re-review

**Task:** Team decision and chip status desk bounded follow-up
**Date:** 2026-09-24
**Verdict:** **FAIL — CHANGES_REQUESTED**

### Findings

- **[P1] Unknown official chip types still disappear in stale/missing-gameweek states.** The early return in `dashboard.py` around lines 140–159 emits only the four hard-coded chips. With a valid `mystery-chip` bootstrap definition and a recorded GW3 manager play, a fresh ledger shows the unknown row and play, but `stale=True` (and the missing-gameweek branch) drops both. Preserve official names and matching recorded usage in every ledger state; unknown freshness or current availability must not erase history.
- **[P2] The summary attributes incomplete evidence to the wrong causes.** `dashboard/team-decision-desk.ts` counts every status except “No official availability flag” as flagged, then describes the set as availability flags, incomplete joins, or FPL notes. A matched player with zero minutes and no fixture has none of those causes. Summarize actual categories or use accurate neutral wording and add a regression for that combination.

### Independent checks

- 28 focused dashboard tests, 10 Node tests, strict TypeScript typecheck, and `git diff --check` — **PASS**.
- Remaining safeguards passed: fresh unknown chips surfaced; known recorded uses persist across stale/missing-rule data; incomplete rows show a next step; complete unflagged rows disclaim a transfer recommendation; escaping, stale-data gates, research provenance and Candidate Lens selection remain intact.
- Mobile/desktop visual checks were not performed by the reviewer. No live collection or edits were made.

### Required follow-up

The second bounded correction is specified at the end of `ops/TASK.md`. Programmer should preserve unknown official chip history on all early-return paths and correct the category summary, then return for another independent review. No deployment or Railway change is approved.

## Team decision and chip status desk — third independent re-review

**Task:** Team decision and chip status desk bounded follow-up
**Date:** 2026-09-24
**Verdict:** **FAIL — CHANGES_REQUESTED**

### Finding

- **[P2] A blank-name official chip rule is still omitted in stale and missing-gameweek states.** The fresh path can label an integer-ID rule with no usable name as `Unrecognized chip (ID 9)`, but the early-return inventory builder only pre-registers unknown rules with a nonblank name. I reproduced the omission for both stale snapshots and snapshots with no current/next event. Every official rule must remain accounted for in the ledger; malformed rules must remain unknown rather than disappear.

### Checks

43 focused Python tests, 10 Node tests, TypeScript typecheck, Python compile checks, and `git diff --check` — **PASS**. Named unknown chips survive fresh/stale/missing-gameweek paths; evidence sufficiency and its category summary now pass. Mobile/desktop visual inspection remains unverified. No files were edited and no live data collection occurred.

### Required follow-up

Add a generic stable display row for official rules without a usable name in every ledger path and test fresh, stale, and missing-gameweek states. Scope is recorded in the newest section of `ops/TASK.md`; no release approval is given.

## Team decision and chip status desk — fourth independent re-review

**Task:** Team decision and chip status desk bounded follow-up
**Date:** 2026-09-24
**Verdict:** **FAIL — CHANGES_REQUESTED**

### Finding

- **[P2] Multiple malformed official rule records collapse into one row.** When two official definitions have both a blank name and an unusable ID, `_unknown_chip_label()` returns the same generic label for both. The stale/missing-gameweek paths deduplicate it, and the fresh path uses it as one dictionary key. Two official records therefore produce one row. Assign a distinct stable identity per malformed record or show a count that proves both are accounted for.

### Checks

82 Python tests, 10 Node tests, TypeScript typecheck, Python compile checks, and `git diff --check` — **PASS**. Prior chip history, evidence-priority, provenance, escaping, freshness, and Candidate Lens checks passed. Mobile/desktop viewport inspection and independent build were not performed in this pass. No changes or live collection were performed by the reviewer.

### Required follow-up

The newest bounded follow-up in `ops/TASK.md` requires distinct rows for multiple malformed records in fresh, stale, and missing-gameweek ledger states. No commit, push, deployment, or Railway change is approved.

## Team decision and chip status desk — Supervisor final review

**Task:** Team decision and chip status desk
**Date:** 2026-09-24
**Verdict:** **PASS — APPROVED LOCALLY**

The final bounded correction resolves the remaining inventory issue: malformed official chip rules without a usable name/ID receive distinct ordinal labels, and the tests prove they remain separate and unavailable/unknown across fresh, stale, and missing-gameweek states. The independent GPT-6 Sol reviewer found no remaining functional issues in the scoped task or follow-ups.

Supervisor independently reran the final checks: **82 Python tests, 10 Node tests, TypeScript typecheck, production build, Python compile checks, and `git diff --check` — PASS**. The Programmer ran the Impeccable detector on the UI changes earlier in this milestone and found no issues; the final code-only follow-up did not change UI, so it was not rerun. The built dashboard was loaded locally and its decision-desk and chip-history content were verified in the browser accessibility tree. Narrow/mobile viewport visual inspection remains unverified and is recorded as a limitation.

No live refresh/research collection, commit, push, upload, Railway change, or deployment was performed. This approval closes only the local decision-desk milestone; Railway remains unapproved pending its separate build-artifact/deployment gate.

## Railway build artifact and clean-checkout readiness — independent review

**Date:** 2026-09-25
**Reviewer:** Independent Supervisor subagent (Claude Opus 5.5). This reviewer did not implement the work.
**Verdict:** **PASS — APPROVED LOCALLY**

### Scope reviewed

Only this task's paths were reviewed: `dashboard.py` (`serve_static`, `send_text`, `MISSING_BUNDLE_MESSAGE`), `tests/test_dashboard.py` (`StaticBundleTests`), `Dockerfile`, `.dockerignore`, the README build/container section, the new top task in `ops/TASK.md`, and the appended handoff in `ops/IMPLEMENTATION_REPORT.md`. Other uncommitted work in the worktree predates this task and belongs to the user. It was not assessed here.

### Findings

1. **Resolved (the core objective).** The fallback to source is removed. `dashboard.py:538-541` resolves `STATIC_DIST`. If `dist/index.html` is missing, it returns `503 text/plain` with `no-store` (`send_text`, `dashboard.py:432-439`) and the build command (`dashboard.py:29-33`). Nothing under `dashboard/` is served any more. Cache headers for built assets are unchanged (`dashboard.py:547-549`).
2. **Verified safe (path traversal).** `dashboard.py:542-543` resolves the target and requires `static_root in target.parents`. The path is never URL-decoded (`dashboard.py:449-450`). I probed the real handler against a temporary `dist` with a sibling secret file. Every one of these returned `404` and none leaked content: `/../secret.txt`, `/%2e%2e/secret.txt`, `/..%2fsecret.txt`, `/assets/../../secret.txt`, `//etc/passwd`, `/..\secret.txt`, `/assets\..\..\secret.txt`, `/C:/Windows/win.ini`, `/C:\Windows\win.ini`, `/\?\C:\Windows\win.ini`, `/.`, `/assets` (a directory), and an absolute-form `http://h/../secret.txt`. A Windows drive-letter join replaces the root, but the resolved target then fails the `parents` check.
3. **Verified (API routes unaffected).** Every `/api/*` GET route is handled before `serve_static` (`dashboard.py:451-493`). With `dist` removed, `/api/workflow-status` and `/api/plans` returned `200` JSON.
4. **Low: unknown API paths and 503.** An unknown `GET /api/...` falls through to `serve_static` (`dashboard.py:494`). With no bundle, it returns the plain-text `503` bundle message instead of a JSON `404`. The same behavior existed before this task, and nothing is exposed. Optional follow-up only.
5. **Low: Node image pin.** `Dockerfile:3` pins `node:22-slim` by major version only. The task asked for major/minor pins, which `python:3.14-slim` meets (`Dockerfile:10`). Vite 8 needs Node 22.12 or later, and the current `22-slim` meets that. Pinning `node:22.17-slim` or similar would satisfy the literal requirement. This does not block.
6. **Verified by reading; Docker build not executed.** The runtime file set covers everything read or written at runtime:
   - `dashboard.py` reads `data/*.json` and `config.json` (`fpl_brief/config.py:13`).
   - Refresh runs `fetch_fpl.py`, which writes `data/latest.json`, `data/decision.json`, `data/changes.json`, `data/catalog.json` (`fetch_fpl.py:202-205`), `data/workflow_status.json` (`fpl_brief/workflow.py:8`), and `digest.md` (`fetch_fpl.py:25,221`).
   - Research runs `python -m fpl_brief.research_scout`, which writes `data/research_packet.json` (`fpl_brief/research_scout.py:256,276`).
   - `write_atomic` creates temporary files in the target's parent directory (`fpl_brief/storage.py:16`). That means `/app` and `/app/data` must be writable by uid 10001. `/app` is chowned explicitly (`Dockerfile:18`), and `data/` gets `COPY --chown` (`Dockerfile:16`). Under Docker/BuildKit semantics, that should also give the created `data` directory to `fpl`, but this is not yet proven in an image.
   - Only the standard library is imported, and there is no runtime Node or TypeScript.
   - The allowlist in `.dockerignore` is sound under Docker's matching rules. `*` excludes top-level names, and `!fpl_brief/`, `!data/`, and `!dashboard/` re-include those trees. Later rules re-exclude `dashboard/node_modules/` and `dashboard/dist/`, and `**/__pycache__/` also matches nested directories. Docker cleans trailing slashes from patterns.
   - The Node stage receives all of `dashboard/`: `tsconfig.json`, `vite.config.ts`, every `.ts` and `.css` file, `index.html`, and the lockfile. Every file matched by the tsconfig `include` pattern is inside `dashboard/`.
   - Using an allowlist instead of the task's exclusion list is an acceptable, stricter deviation.

### Checks run by this reviewer

- `python -m unittest discover -s tests -v`: **PASS**, 86 tests (baseline 82 plus 4 new `StaticBundleTests`).
- `node --test tests/*.mjs`: **PASS**, 10 of 10.
- `npm run typecheck --prefix dashboard`: **PASS**.
- `npm run build --prefix dashboard`: **PASS**, producing `index-CYl5EWcF.js` and `index-B85p7D96.css`.
- `python -m py_compile` on the handoff set: **PASS**.
- `git diff --check`: **PASS**, with CRLF notices only. The untracked `Dockerfile` and `.dockerignore` were also checked with `git diff --no-index --check`: clean.
- **Independent clean-checkout smoke without Docker.** I copied the 116 paths from `git ls-files --cached --others --exclude-standard`, minus deleted paths, into a fresh scratch directory. `npm ci`, typecheck, and build passed there, with the same hashes as the working tree. I assembled exactly the Dockerfile runtime file set, with no `.ts` files and no `node_modules`. I served it on `127.0.0.1:18768`:
  - `/` returned `200 text/html`;
  - the referenced `/assets/index-CYl5EWcF.js` returned `200 text/javascript`;
  - `/api/dashboard` and `/api/workflow-status` returned `200` JSON.

  No refresh or research POST was sent, and no FPL network call was made. The server was stopped.
- `docker info`: **engine unavailable** (`dockerDesktopLinuxEngine` pipe not found). Per the instructions, Docker Desktop was not started. **Acceptance criteria 3 and 4, as written for an image, remain UNVERIFIED.**

### Why the unexecuted docker build does not block local approval

This milestone was about behavior in the local code: no source fallback, a clear 503, safe static serving, and a correct build recipe. Those are verified directly, and the runtime file set was proven equivalent without Docker. The parts still unproven are Docker-specific: `.dockerignore` matching, `--chown` directory ownership, and base-image pulls. They can only fail at image build or deploy time, and that step is gated anyway. **Before any Overseer release decision, `docker build` from a clean copy and a `127.0.0.1`-bound smoke run are required.** The smoke run must also include a non-root write check, for example `docker run --rm fpl-brief:local sh -c 'touch data/.w digest.md && ls -ld /app /app/data'`, and a check that the image has no `node_modules` or `.ts` files. The container and image must be removed afterwards. If any of those fail, this approval does not carry over to release.

### Release boundary

**Railway deployment remains NOT APPROVED** until the Overseer makes an explicit release decision. The TypeScript migration, Team Decision Desk, squad formation work, and this task are all **still uncommitted**. `HEAD` still tracks the legacy `dashboard/*.js`, so a Railway build from GitHub today would build the old code. This reviewer made no commit, stage, push, image build, registry push, Railway change, deployment, live refresh, or research collection, and edited no application code, tests, or the Programmer report.

## Private FPL account data import — independent review

**Date:** 2026-09-25
**Reviewer:** independent Supervisor/Reviewer subagent (Claude Opus 5.5, high effort; did not implement)
**Verdict:** PASS — APPROVED LOCALLY

### Scope reviewed

`fpl_brief/private_team.py`, `fpl_brief/candidates.py` (`lens(private=...)`), `dashboard.py` (`PRIVATE_TEAM`, `apply_private_inputs`, `/api/dashboard`, `/api/candidates`), `dashboard/app.ts`, `dashboard/team-decision-desk.ts`, `dashboard/desk-tools.ts`, `tests/test_private_team.py`, `tests/test_research_candidates.py`, `tests/test_dashboard.py`, `README.md`, plus `.gitignore`, `.dockerignore`, `Dockerfile` for the privacy boundary.

### Privacy boundary

- `local/` is ignored (`.gitignore:3`; `git check-ignore` confirms `local/private_team.json`), no `local/` path is tracked, `.dockerignore` is a deny-all allowlist that does not re-include `local/`, and the `Dockerfile` COPY set (`Dockerfile:14-17`) does not copy it. The file cannot reach the image or Railway.
- The captured file holds only `schema_version`, `source`, `team_id`, `captured_at_utc`, and `my_team` (`chips`, `picks`, `picks_last_updated`, `transfers`), with 15 picks and a `Z` capture time. A grep for cookie/token/password/csrf found nothing. No code path reads, stores, or logs credentials.
- `/api/*` JSON is sent with `Cache-Control: no-store` (`dashboard.py:440`).

### Findings

1. **Medium (release gate, non-blocking locally)**, `dashboard.py:475`, `dashboard.py:582`: `/api/dashboard` now returns account data: per-player selling and purchase prices, bank, value, and chips. With `PORT` set, the server binds `0.0.0.0` with no auth, so running it that way on a LAN while `local/private_team.json` exists would expose this data to the network. On Railway the file is absent, so the state is `missing`. **Before any deploy or other non-loopback serving, the Overseer must decide whether to add a guard**, for example loading private data only when bound to loopback or behind an explicit opt-in env flag, or else document that `PORT` must not be used locally with a capture present.
2. **Low**, `fpl_brief/private_team.py:34`: a timezone-naive `captured_at_utc` is accepted. `parse_time` treats it as machine-local time (UTC+7 here), which skews the age. It was probed as `ready` with a 1-hour-old naive UTC time read as 8.0 h. On a UTC-negative machine it would look fresher than it is. The capture writes `Z`, so the real file is unaffected. Private data should reject naive times as `invalid`.
3. **Low**, `fpl_brief/private_team.py:100`: the stale check compares the rounded `age_hours`, so a capture 8 h 02 m old is still `ready`. It should compare the unrounded age.
4. **Low**, `fpl_brief/private_team.py:97-99`: if the snapshot has no `events` deadlines, the deadline-stale rule is silently skipped. `lens()` still blocks on a missing next deadline (`candidates.py:45-47`), so affordability is not affected, but the panel can say `ready`.
5. **Low**, `fpl_brief/candidates.py:58,100`: `budget_source` is `"account"` whenever the account is usable, even if the fallback branch is taken (`replace_id` not in `prices`). The mismatch check makes this unreachable today, but the label should follow the branch actually taken.
6. **Info**: the chip `window` values and `transfers_made` bounds are not type-checked (`private_team.py:65`). They are display-only and escaped. A huge `made` floors free transfers to 0 correctly.

### Verified correct

- Validation: bool/str/negative/float/NaN prices, duplicate or 14 picks, bool team ID, bool or 0 gameweeks, non-dict chips, a bad schema, bad JSON, and a future capture all yield `invalid` with no numbers. Only `ready` sets `usable=True`. `mismatch` (team ID or pick set) exposes no numbers. `stale` shows values but is not usable.
- `lens()`: the freshness, squad-completeness, deadline, ownership, and minutes gates all run before the account branch. The budget is account selling price + account bank. The non-ready fallback keeps the public path and appends the import hint. Tests cover both, plus the deadline gate with ready data.
- UI: every dynamic value in `renderPrivateTeamPanel` goes through `esc`, and the Candidate Lens output escapes all values including xGI/FDR. The panel is labeled as a read-only account capture, "Not transfer advice", and "never deployed", and stale data carries a warning.
- Tests use temp files and fixtures. The API test patches `PRIVATE_TEAM` to a temp path. No network calls, and nothing reads the real `local/` file.

### Checks run

- `python -m unittest discover -s tests`: PASS (100 tests)
- `node --test tests/*.mjs`: PASS (10)
- `npm run typecheck --prefix dashboard`: PASS
- `npm run build --prefix dashboard`: PASS
- `python -m py_compile dashboard.py fpl_brief/private_team.py fpl_brief/candidates.py`: PASS
- `git diff --check`: PASS (CRLF warnings only)
- Ad hoc loader probes on temp files (naive time, NaN, bool, float, huge values, rounding): results as listed above.

### Release boundary

Nothing is released. No commit, push, deploy, FPL call, or POST to `/api/refresh` or `/api/research` was made in this review. Railway deployment remains NOT APPROVED, and finding 1 must be resolved or explicitly accepted by the Overseer before any release.

## Private FPL account data import — follow-up re-review

**Date:** 2026-09-25
**Reviewer:** independent Supervisor/Reviewer subagent (Claude Opus 5.5; did not implement)
**Verdict:** PASS — APPROVED LOCALLY

Scope: only the six-item bounded follow-up in `ops/TASK.md` ("Bounded follow-up — review findings and 24-hour freshness") and the matching Programmer report subsection.

### Per-item findings

1. **24-hour account freshness — resolved.** `DEFAULT_STALE_AFTER_HOURS = 24` (`fpl_brief/private_team.py:14`). The limit is read from `private_stale_after_hours` independently of the snapshot `stale_after_hours` (`private_team.py:118`), and the age check compares exact seconds (`private_team.py:119`). The test at `tests/test_private_team.py:106` covers 9 h ready, 24 h 02 m stale (rounded age 24.0, which proves the check does not round), and a config override.
2. **Loopback-only guard — resolved.** `LOOPBACK_HOSTS` (`dashboard.py:29`) and `Handler.private_data` (`dashboard.py:459-463`) check the bound `server_address[0]`, and that check fails safe: any host outside the set gets `disabled()` with no values. That includes 0.0.0.0, LAN IPs, `::`, IPv4-mapped `::ffff:127.0.0.1`, and 127.0.0.2. The false negatives in the last two cases are safe. A probe confirmed that binding to "localhost" reports `127.0.0.1` after bind. `/api/dashboard` (`dashboard.py:477`) and `/api/candidates` (`dashboard.py:499`) are the only callers. No other code path references `PRIVATE_TEAM`/`private_team`, and static serving is confined to the built dist (`dashboard.py:566-567`). The default bind is `127.0.0.1`; `PORT` gives `0.0.0.0` and therefore `disabled` (`dashboard.py:578-589`). Test: `tests/test_dashboard.py:736`.
3. **Timezone-naive capture rejected — resolved.** `_captured_time` returns None for naive times, so the state is `invalid` (`private_team.py:23-31`). Test: `tests/test_private_team.py:116`.
4. **Unrounded age — resolved** (see item 1). `age_hours` is still rounded for display only (`private_team.py:43`).
5. **Missing or unparseable deadlines mean stale — resolved.** When neither the current nor the next deadline parses, the state is `stale` with "deadlines are unavailable" (`private_team.py:115-124`). Test: `tests/test_private_team.py:121`.
6. **`budget_source` accurate — resolved.** `account` is set only when the outgoing player's price exists in the account prices (`fpl_brief/candidates.py:59-60`); `budget_source` follows that branch (`candidates.py:101`). Test: `tests/test_research_candidates.py:188`.
- **UI/type — resolved.** `renderPrivateTeamPanel` shows only the escaped warning for every state other than stale or ready, which includes `disabled`, `missing`, `invalid`, and `mismatch` (`dashboard/team-decision-desk.ts:91-93`). The `disabled` state has been added to `PrivateTeamData.state` (`dashboard/app.ts:136`).

### Non-blocking observations

- **Low**, `fpl_brief/private_team.py:118-119`: `private_stale_after_hours` is not type-validated, and `fpl_brief/config.py` does not know the key. A string or null value raises `TypeError`, which returns HTTP 500 on `/api/dashboard` and 400 on `/api/candidates`; `true` is treated as 1 h. This fails closed and no data is served, and the key is operator-controlled and absent from `config.json`. It can be hardened later.
- **Info**, `dashboard/team-decision-desk.ts:96`: the ready text hard-codes "24 hours", so it would not reflect a config override.
- **Info**: the guard is based on the bind address, not the client. A local reverse proxy or tunnel to a loopback-bound server would still expose the data. That is outside the current local-only scope.

### Checks run

- `python -m unittest discover -s tests`: PASS (105 tests)
- `node --test tests/*.mjs`: PASS (10)
- `npm run typecheck --prefix dashboard`: PASS
- `npm run build --prefix dashboard`: PASS
- `git diff --check`: PASS (exit 0)
- Ad hoc probes: the "localhost" bind resolved address, and `private_stale_after_hours` edge values on a temp file.

### Release boundary

Nothing is released. No commit, stage, push, deploy, FPL network call, or POST to `/api/refresh` or `/api/research` was made, and `local/private_team.json` was not read. Railway deployment remains NOT APPROVED. The prior release-gate finding is now mitigated in code by the loopback guard, but any deploy still needs Overseer approval.

## Weekly lineup helper and squad readability — independent review

**Date:** 2026-09-25
**Reviewer:** Independent Supervisor/Reviewer subagent (Claude Opus 5.5, routine tier); did not implement this task.
**Verdict:** PASS — APPROVED LOCALLY

### Scope reviewed

`fpl_brief/lineup.py`, the `lineup` field in `fpl_brief/private_team.py:85-86`, `dashboard.py:484` (API) and `dashboard.py:575` (index `no-cache`), `dashboard/lineup-helper.ts`/`.css`, the `dashboard/app.ts` mount (`:5-6`, `:135`, `:313`), `dashboard/squad-formation.css`, `tests/test_lineup.py`, and `LineupHelperUiTests` plus the cache assertion in `tests/test_dashboard.py`. Checked against the Overseer decision of 2026-09-25 that reverses "no lineup advice".

### Verified

- **Formation optimality (`lineup.py:76-91`).** Players are ranked per position with eligible players first, then by `ep_next` descending, then by id. For a fixed formation, taking each position's prefix is optimal: it minimises forced starts, `max(0, k - eligible)` per line, and then maximises the eligible total. All eight legal 1-GK formations are enumerated, and the key is (forced, -total, formation tuple). "Fewest forced, then highest total" is the correct priority. Because ineligible players pad the prefixes, a legal XI is never missed when a position lacks eligible players. A 15-man squad of 2/5/5/3 always fills every formation. Equal-total formations are tie-broken by the lowest DEF/MID count, which is deterministic.
- **Eligibility (`lineup.py:43-69`).** `i`/`s`/`u`/`n`, a 0% chance, or no fixture blocks a start. Doubtful players (<100%) and players with a non-`a` status are flagged, not hidden. A double gameweek is flagged.
- **Captain (`lineup.py:134`).** The order is eligible, then fully available, then estimate, then id, as specified.
- **Diff (`lineup.py:94-165`).** Both sources carry FPL `position` 1-15 (the public picks were checked in `data/latest.json`). The account lineup keeps `position`. `ordered[11:]` therefore places the backup GK at 12, which matches the engine's GK-first bench. The account lineup is used only when `usable` is true, which requires a ready capture whose squad equals the public squad (`private_team.py:110-129`), so the two squads cannot be mixed.
- **Refusals (`lineup.py:107-127`).** The helper refuses when freshness is missing or stale (it defaults to stale), when the deadline is missing, when the deadline has passed, when the squad is not 15 or has unmatched picks, and when `ep_next` is missing, NaN, inf, or negative for any of the 15 players. The last check is stricter than the spec's "starters", which is acceptable.
- **No claims beyond FPL.** The method text and the UI label every value "FPL est." or "FPL estimate" and say "not a forecast by this app". Research is non-stale only and labelled "captured, unverified". The Bench Boost text says "not advice to play the chip". A hint is shown only when the chip is known to be available; otherwise it states "unknown".
- **Escaping (`lineup-helper.ts:44-87`).** Every dynamic value passes through `esc`. That covers names, team, role, estimate, reason, flags, news, publisher, research text, source, the diff names, the hint, the method, the formation, and the gameweek. Line headings come from a constant tuple. Escaping is covered by a UI test.
- **Cache (`dashboard.py:575`).** Only `index.html` gets `no-cache`, and hashed assets keep `public, max-age=300`. This tightens caching and weakens nothing: static serving stays confined to `dist`. Live `GET /` returned `Cache-Control: no-cache`.
- **CSS widths.** Pitch names are 15px (14px at ≤600px) and other text is 12-13px. Cards use `minmax(0,1fr)` with `overflow-wrap:anywhere`, and there are 2 columns at ≤600px. The lineup panel uses 4, 2, and 1 columns at >1100px, ≤1100px, and ≤600px, and the summary is `auto-fit minmax(170px)`, which fits within the 360px content width. No fixed width exceeds 360px. Reasoned only; the programmer reported a live 375px check.

### Findings (all non-blocking)

- **Low**, `fpl_brief/lineup.py:171`: the Bench Boost rule counts a bench player as available when they are `eligible`, which includes doubtful players (for example, a 25% chance). The hint text at `:175` says "all four bench players are available". The rule should use `fully_available`, or the text should say "not ruled out".
- **Low**, `fpl_brief/lineup.py:148`: `.capitalize()` lowercases the rest of the flag string. The bench reasons therefore read "gw6" and "Fpl status not fully available". Upper-case only the first character instead.
- **Low**, `fpl_brief/lineup.py:151`: the sort key `pick.get("position") or 99` is not validated in `private_team._parse` (`private_team.py:85`). A non-integer `position` in a capture would raise `TypeError`, which returns HTTP 500 on `/api/dashboard`. This fails closed; FPL always sends integers.
- **Info**, `fpl_brief/lineup.py:163` / `dashboard/lineup-helper.ts:78`: `bench_order_changed` is also true when only the bench's membership changed. The UI then says "Bench order differs" alongside the Start/Bench lines. This is accurate but redundant.
- **Info**, `fpl_brief/lineup.py:87`: the XI total excludes forced starters' estimates, so "XI FPL estimate" can understate the XI in the rare forced case.

### Checks run

- `python -m unittest discover -s tests`: PASS (118 tests)
- `node --test tests/*.mjs`: PASS (10)
- `npm run typecheck --prefix dashboard`: PASS
- `npm run build --prefix dashboard`: PASS
- `git diff --check`: PASS; the untracked new files were also scanned for trailing whitespace, with none found.
- Read-only live GETs on 127.0.0.1:8766: the index returns `no-cache`, and `/api/dashboard` returns lineup `ready`, 4-4-2. No private file contents were printed.

### Release boundary

Nothing is released. No commit, stage, push, deploy, FPL network call, or POST to `/api/refresh` or `/api/research` was made. `local/private_team.json` was not read. Stage 2 (in-app Jev chat) remains unauthorized.

## Tactics Board site redesign — independent review

**Date:** 2026-09-25
**Reviewer:** independent Supervisor/Reviewer subagent (Claude Opus 5.5, routine tier). I did not implement this task.
**Verdict:** FAIL — CHANGES_REQUESTED

### Findings

1. **Medium — the first click after a drag is swallowed** (`dashboard/tactics-board.ts:305`, `:311`). `pointerup` sets `suppressClick = true` and then `trySwap` calls `render()`, which replaces both magnets. The browser then dispatches no `click` (the pointerdown node is detached), so the flag stays set. The next genuine click, or a keyboard Enter/Space activation, is discarded.
   - Reproduced live: a refused drag (Haaland onto Suzuki) was followed by a click on Groß, and nothing was selected. The second click selected him.
   - The same happens after a drop outside `.tactics`.
2. **Medium — no `pointercancel` handling** (`dashboard/tactics-board.ts:275-308`). If a touch or pen drag is cancelled by the OS or browser, the ghost stays in `<body>`, the source stays `is-lifted`, and `drag` persists (the `pointermove` guard only clears it while no ghost exists). The next `pointerup` anywhere then performs a swap with whatever magnet is under the pointer.
   - Only the browser-local board changes; FPL is never contacted.
   - No pointer capture is used.
3. **Low — Escape and deselect drop keyboard focus to `<body>`** (`dashboard/tactics-board.ts:265-266`, `:315`). `render()` rebuilds the buttons without restoring focus; confirmed live, with `activeElement` on body after Escape. By contrast, `trySwap` refocuses correctly (`:255`).
4. **Low — the ghost is a full clone of the button** (`dashboard/tactics-board.ts:285-288`). It keeps `aria-label`, `data-id`, and the focusable button, and has no `aria-hidden`/`inert`. It is exposed to assistive technology during a drag.
5. **Low/info.**
   - The section-level listeners (`:275`, `:309`, `:314`, `:317`) are not bound to the `AbortController` `signal`. This is safe today because `renderSquad` replaces `#squad` innerHTML before each mount (`dashboard/app.ts:323-335`), but it is fragile.
   - `data-id="${player.id}"` (`:117`) is unescaped. It relies on server-side integer ids from `fpl_brief/lineup.py`.
   - Window listeners from the last ready mount linger if the next render is a refusal state. They are harmless (null `drag`).

### Verified correct

- **Board logic** (`dashboard/tactics-board.ts:37-97`).
  - `swapMagnets` enforces GK↔GK. Bench↔bench swaps cannot touch `bench[0]`. Starter↔sub results are re-checked with `isLegal`, and illegal swaps return the unchanged state.
  - `loadBoard` requires 11+4 integers, 15 unique ids that are all in the current squad, a GK at `bench[0]`, and a legal XI, all inside try/catch. I found no stored or crafted state that yields a duplicated or illegal board.
  - The key `fpl-brief:board:v1:gw<N>` is namespaced and versioned. Saving the suggested state removes the key.
- **Escaping.** All names, reasons, news, research, the source, the Bench Boost hint, and the refusal reason pass through `esc`. Marker SVG coordinates come only from DOM rects and a numeric id (`:195-216`). The kit team is used only as a lookup key (`dashboard/kits.ts:33`), and the clip ids are generated.
- **No FPL action implied.** The notes read "Only saved in this browser. Make real changes in the FPL app.", and there is no network code in the board.
- **Lineup follow-ups.**
  - `fpl_brief/lineup.py:86-87` includes forced starters in the total.
  - `:147-149` fixes the capitalisation.
  - `:165` checks for the same bench set.
  - `:174-176` requires `fully_available` bench players.
  - `fpl_brief/private_team.py:60-62` requires an integer `position` ≥ 1.
- **Existing views and assets.**
  - Existing IDs and hooks are preserved in `renderSquad`.
  - No Google Fonts references remain, and `styles.css`/`redesign.css` are unlinked.
- **Accessibility.**
  - Magnets are `<button>`s with `aria-pressed`, and the toast, total, summary, and picked-up areas are `aria-live`.
  - There is a global `:focus-visible` outline (`dashboard/board.css:24`).
  - Reduced motion is handled (`dashboard/board.css:177`, `dashboard/tactics-board.css:90`), and magnets set `touch-action: none`.
- **Responsive.** At 360px all seven views had `scrollWidth` 360, with no console errors. The viewport was restored to desktop.

### Checks

- `python -m unittest discover -s tests`: 126 OK.
- `node --test tests/*.mjs`: 10/10 pass.
- `npm run typecheck --prefix dashboard`: clean.
- `npm run build --prefix dashboard`: built.
- `git diff --check`: exit 0, with CRLF notices only.
- Browser pane on localhost:8766, local only:
  - One refused drag and clicks were used to reproduce finding 1. No swap succeeded, so no board key was written; `localStorage` has no `fpl-brief:board*` key.
  - Resize to 360px, then back to desktop.

### Release boundary

Nothing is released. No commit, stage, push, deploy, FPL network call, or POST to `/api/refresh` or `/api/research` was made. `local/private_team.json` was not read.

## Tactics Board site redesign — re-review

**Date:** 2026-09-25
**Reviewer:** independent Supervisor/Reviewer subagent (Claude Opus 5.5, routine tier). I did not implement this task.
**Verdict:** PASS — APPROVED LOCALLY

### Prior findings (all resolved, `dashboard/tactics-board.ts`)

1. **Click suppression after a drag.** A 350 ms `ignoreClicksUntil` window replaces the sticky flag (`:309`, `:346`, `:355`).
   - Live: a refused drag, a 0.6 s wait, then a click on Groß selects him.
   - A click within 350 ms of a drop is still ignored by design, which is acceptable.
2. **Drag cancellation.** `endDrag` is shared by `pointerup`, `pointercancel` and window `blur` (`:310-353`). A cancelled drag removes the ghost, clears the lifted and dragging classes, and never swaps later.
3. **Focus.** `putBack`/`refocus` (`:283-291`) re-render and restore focus. Live: after Escape, `activeElement` is still Groß (data-id 124).
4. **Ghost.** The ghost is `aria-hidden`, `inert` and `tabindex=-1`, and has no label (`:331-334`).
5. **Listeners and data-id.**
   - All section and window listeners take `{ signal }`.
   - `data-id` is escaped (`:117`).

### New changes

- **Stat strip** (`:132-147`).
  - The countdown handles invalid and passed deadlines.
  - Free transfers and bank show "—" plus a capture note unless the account capture is `usable`.
  - Every value is escaped, and the live XI total is set via `textContent` (`:249`).
- **SVG `<text>` notes** (`:227-238`).
  - Player and captain names are escaped; coordinates are numbers from DOM rects.
  - The layer is `aria-hidden` and the same facts are in Coach's notes.
  - The notes are hidden at ≤700px (`dashboard/tactics-board.css:86`, `:98`). Live at 360px, both notes are `display:none`.
- **Per-view H1** (`dashboard/app.ts:384-386`). Set via `textContent`; all seven views were verified live.
- **Wayfinding.** No `mountWayfinding` or `wayfinding` import remains in `app.ts` or `index.html`. `wayfinding.ts` is left on disk, unused.
- **Collapsed sections.** The saved squad and the lineup list are each in `<details>` (`dashboard/app.ts:325-326`). `mountSquadFormation`/`mountTacticsBoard` still run on the same target.
- **Kit renderers.**
  - `runtime.kit` is optional and guarded (`dashboard/desk-tools.ts:225`), and the team-decision `kit` argument is optional (`dashboard/team-decision-desk.ts:45`, `:110`).
  - The team or short name is used only as a kit lookup key.
  - The existing sandbox tests pass.
- **Team decision desk** (`dashboard/team-decision-desk.ts:111`, `:139`). Only flagged rows show by default and unflagged rows sit in `<details>`. When the snapshot is stale, every row shows and the collapse is omitted.
- **Rivals** (`dashboard/app.ts:352-361`).
  - `count()` accepts arrays or numbers and otherwise shows "—", all escaped. The "You" row uses the escaped `league.rank` and `league.points`.
  - The "each side" merge is arithmetically valid for two 15-player squads.
- **Research desk CSS:** presentation only.

### Findings (non-blocking)

- **Low, `dashboard/tactics-board.ts:144`:** if the capture is `usable` but `free_transfers` is missing, the strip shows the literal text "undefined". It is escaped, so this is cosmetic.
- **Low, `dashboard/app.ts:357`:** a non-numeric rival `rank` becomes `NaN`, which makes the sort order unstable. This is display only.
- **Info.**
  - The deadline countdown is computed at render time and does not tick.
  - `wayfinding.ts`, `styles.css` and `redesign.css` remain on disk, unused, pending the Overseer's cleanup decision.

### Checks

- `python -m unittest discover -s tests`: 127 OK.
- `node --test tests/*.mjs`: 10/10 pass.
- `npm run typecheck --prefix dashboard`: clean.
- `npm run build --prefix dashboard`: built.
- `git diff --check`: exit 0.
- Browser pane on localhost:8766, local only:
  - reloaded, one refused drag, click, and Escape;
  - no `fpl-brief:board*` key was written;
  - no console errors;
  - at 360px all seven views have `scrollWidth` 360;
  - the viewport was restored to desktop.

### Release boundary

Nothing is released. No commit, stage, push, deploy, FPL network call, or POST to `/api/refresh` or `/api/research` was made. `local/private_team.json` was not read.

## Self-serve weekly workflow — independent review

**Date:** 2026-09-26
**Reviewer:** Claude Opus 5.5, an independent Supervisor/Reviewer subagent at high effort (HIGH-RISK tier: a new local write endpoint for private account data). It did not implement this task.
**Verdict:** FAIL — CHANGES_REQUESTED

### What holds

- **CSRF.** `POST /api/private-team` requires `application/json`, so an HTML form (text/plain) gets 415. A cross-site `fetch` needs a preflight, and `OPTIONS` answers 501 with no CORS headers. `Origin` must also equal `http://<Host>`: `Origin: null`, a foreign origin, and a `http://127.0.0.1:PORT.evil.com/` Referer are all refused with 403.
- **DNS rebinding and binding.**
  - The Host allow-list (127.0.0.1, localhost, [::1]) blocks rebinding.
  - An off-loopback bind is refused.
- **Body size.** Absent, zero, negative, non-numeric and >64 KB lengths are refused before any read. The server speaks HTTP/1.0, so an unread body cannot be smuggled.
- **Temp file.** It is written in `local/`, validated with `private_team.load`, and moved into place with `os.replace` only when the state is `ready` or `stale`. It is removed on every path. A bad paste leaves the existing file byte-identical (probed).
- **No FPL calls.** There are no FPL network calls or write actions in the server code. The my-team link is only an `<a target=_blank rel="noopener noreferrer">` built from an integer team id.
- **`GET /api/plan`.**
  - It goes through `private_data()`, so off-loopback it returns `disabled` and then 422.
  - It exposes nothing beyond what `/api/dashboard` already returns: bank and selling prices are already in the private summary.
- **`plan.py` rules checked against counterexamples.**
  - Uniqueness covers chained moves such as A→B, B→C and a sold player being re-bought.
  - Owned and not-owned checks, same position, and full availability all hold.
  - The club limit is checked over the whole planned squad.
  - Budget = bank + selling prices − `now_cost`.
  - Hits: `max(0, n − free) × cost`, and zero when unlimited.
  - The base snapshot is untouched (it is deep-copied).
- **Frontend.**
  - Plan storage is validated on load.
  - The plan strip, fixture strip and shortlist are escaped.
  - The countdown is cleared on abort.
  - Note placement is bounded (notes × 5–6 spots) and removes each failed `<text>`.

### Findings

- **Medium (blocking), `dashboard.py:507`: arbitrary pasted fields are stored verbatim.** The whole pasted object is saved as `my_team`, including any extra keys, up to 64 KB.
  - **Probe:** a paste of valid my-team JSON plus `"password": "hunter2", "cookie": "sessionid=abc"` returned 200, and both values were written to `local/private_team.json`.
  - **Why it blocks:** the task says credentials are "never accepted or stored". Only the fields the schema reads should be persisted: picks (element, position, selling/purchase price, is_captain, is_vice_captain), transfers (bank, made, cost, value, limit, status), and chips (name, status_for_entry, played_by_entry, start_event, stop_event, is_pending).
- **Medium (blocking), `dashboard/app.ts:365` and `:373`: plan results are cached forever.** `planCache` is keyed only by the transfers query. It is never invalidated when `loadDashboard()` brings in new data, and network errors are cached too.
  - **Scenario:** the Overseer tries a move while the capture is stale and gets "needs a fresh capture". They then import through the new box, and the strip keeps showing the old refusal until a page reload or a plan change.
  - The same happens after a data refresh or a failed fetch, and a `ready` result can show an outdated lineup, budget or hits.
  - **Fix:** clear `planCache`/`planRequest` whenever `state.data` is replaced, and don't cache the fetch-failure result.
- **Low, `dashboard.py:497-498`: deeply nested JSON crashes the handler.** A body such as 60 000 × `[` makes `json.loads` raise `RecursionError`, which is not caught. The handler thread crashes and the connection closes with no response. No file is touched (probed). Catch `RecursionError` (or `ValueError`) and return 400.
- **Low, `dashboard.py:497`: a short body hangs its thread.** When `Content-Length` is larger than the body actually sent, `rfile.read` blocks that handler thread until the client closes. There is no socket timeout. This is loopback only, so the impact is a local self-DoS.
- **Low, `fpl_brief/private_team.py:15`: stale copy.** `IMPORT_HINT` still says "ask Claude to capture" in the Claude browser pane. The missing, invalid and stale messages should point to the new Import box.
- **Low, `dashboard/tactics-board.ts:169` (via `fpl_brief/lineup.py` changes): sold captain renders as "—".** When a plan sells the captured captain, `changes.captain.from` is `None`, and the note reads "C — → X". Use the sold player's name or "sold".
- **Low, `dashboard/tactics-board.ts:202`: countdown timer can outlive its board.** The function returns before `mounted?.abort()` when a later render has no `ready` lineup, so the previous countdown interval keeps writing to a detached node until the next ready mount.
- **Info.**
  - **Pre-existing, not introduced here: GET routes don't check Host.** `GET /api/dashboard` (and now `/api/plan`) check the bind address but not the Host header. A DNS-rebinding page could therefore read bank, selling prices and chips. Suggest a separate task that applies the `same_origin_local` Host allow-list to private GET routes.
  - **`plan.py:71`:** `now_cost or 0` treats a catalog player with no price as free. This matches `candidates.py`.
  - **Captain shortlist in a double gameweek:** it shows only `next_fixtures[:1]`, although the "double" tag is shown.
  - **Test count:** the handoff reports 139 Python tests; this run found 138.

### Checks

- `python -m unittest discover -s tests`: 138 OK.
- `node --test tests/*.mjs`: 10/10 pass.
- `npm run typecheck --prefix dashboard`: clean.
- `npm run build --prefix dashboard`: built.
- `git diff --check`: exit 0.
- **Throwaway probe server** on 127.0.0.1 at a random port, with `LOCAL`/`PRIVATE_TEAM` patched to a temp dir and config, snapshot and catalog stubbed. It covered:
  - a valid paste;
  - deep nesting;
  - extra fields;
  - a bad paste keeping the old file;
  - text/plain;
  - `Origin: null`;
  - an [::1] Host;
  - the Referer prefix trick;
  - a short body;
  - NaN;
  - an `OPTIONS` preflight.

  No `.tmp` leftovers were found.

### Release boundary

Nothing is released. No commit, stage, push, deploy, or FPL network call was made, and there was no POST to the servers on :8765/:8766 or to `/api/refresh`/`/api/research`. The real `local/private_team.json` was neither read nor written.

## Self-serve weekly workflow — re-review

**Date:** 2026-09-26
**Reviewer:** Claude Opus 5.5, an independent Supervisor/Reviewer subagent at high effort (HIGH-RISK tier). It did not implement this task or its follow-up.
**Verdict:** PASS — APPROVED LOCALLY

### Blocking findings: resolved

- **Import whitelisting (`dashboard.py`, `whitelist_my_team` / `IMPORT_FIELDS`).** Stray keys are now dropped: at the top level, in the `{my_team: …}` wrapper, as extra pick keys, and as extra transfer keys (probed: the secret was absent from the saved file). Non-dict picks are rejected with 422, and non-dict chips fail validation.
- **Plan cache (`dashboard/app.ts:362-374`).**
  - The key is `planQuery | snapshot.generated_at_utc | private_team.captured_at_utc`, so an import or a refresh changes it, and the plan (including a cached error) is re-checked.
  - The callback re-renders only while the same transfers are still planned, and a re-render finds the cached key, so there is no loop.
  - If data reloads mid-flight, there is at most one extra, bounded fetch.

### Low items: resolved

- **Deeply nested JSON:** returns 400 (probed).
- **`Handler.timeout = 15`:** a short body is now dropped after 15.0 s (probed).
- **`IMPORT_HINT`:** points to the Import box.
- **Sold captain or vice:** the "from" is omitted when it is null, on the board (`tactics-board.ts:169-170`) and in the list (`lineup-helper.ts:81`).
- **Abort ordering:** `mountTacticsBoard` aborts before its early return (`tactics-board.ts:201-204`).
- **Double gameweeks:** captain options keep `next_fixtures[:max(1, fixtures)]` (`lineup.py:211`).

### Pre-existing issue: closed

On a loopback bind, `/api/*` GETs refuse any Host that is not local, using `host_is_local`. Probed results:

- **Refused (403):**
  - `evil.example:PORT`;
  - `127.0.0.1.evil.example`;
  - `localhost.`;
  - a missing or empty Host;
  - `//api/dashboard`;
  - `/api/plan`.
- **Accepted:** `127.0.0.1`, `localhost` in any case, `[::1]:PORT`, and a port-less `127.0.0.1`.
- **Non-API paths:** static assets still serve, and `/API/…` and `/static/../api/…` return 404, never data.
- **::1 bind:** it refuses a foreign Host and accepts `[::1]`.
- **0.0.0.0 bind (Railway):** a foreign Host passes the check as before, and import is still 403.

### Findings (non-blocking)

- **Low, `dashboard.py` `whitelist_my_team`: allowed keys still accept arbitrary values.** It filters keys but not value types, and several allowed fields are never type-checked by `private_team._parse`. A crafted paste can therefore still store arbitrary content, including nested objects with any keys, in:
  - picks: `is_captain`, `multiplier`, `element_type`;
  - transfers: `status`;
  - chips: `id`, `name`, `start_event`/`stop_event`, `chip_type`;
  - `picks_last_updated`.

  Probed: for example `"is_captain": {"cookie": "…"}` was saved with 200. The report's claim that nested keys are dropped is therefore inaccurate. The practical risk is negligible: only the local user's own same-origin page can post, and a real FPL paste never carries such values. Suggested hardening:
  - accept only scalar (int, bool, None, or short string) values;
  - accept only int lists for `played_by_entry`;
  - cap string lengths.
- **Info.**
  - A transient fetch failure stays cached for its key until the next data reload (by design).
  - `host_is_local` accepts a malformed `[::1]evil` Host. Browsers cannot send one, so it is not exploitable.
  - Pre-existing and out of scope: `POST /api/refresh` and `/api/research` have no Host or Origin check. A cross-site form could trigger a public refresh, which reads no private data.

### Checks

- `python -m unittest discover -s tests`: 143 OK.
- `node --test tests/*.mjs`: 10/10 pass.
- `npm run typecheck --prefix dashboard`: clean.
- `npm run build --prefix dashboard`: built.
- `git diff --check`: exit 0.
- **Throwaway probe servers** on 127.0.0.1, 0.0.0.0 and ::1 with random ports, with `LOCAL`/`PRIVATE_TEAM` patched to a temp dir and config, snapshot and catalog stubbed. No `.tmp` leftovers were found.

### Release boundary

Approved locally only; nothing is released. No commit, stage, push, deploy, or FPL network call was made. There was no POST to :8765/:8766 and no call to `/api/refresh`/`/api/research`. The real `local/private_team.json` was neither read nor written.
