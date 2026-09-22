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
