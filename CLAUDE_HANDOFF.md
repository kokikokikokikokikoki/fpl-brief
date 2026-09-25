# Claude handoff — FPL Brief

**Prepared:** 2026-09-25  
**Repository root:** `C:\Users\User\fpl-brief`  
**Purpose:** Give Claude enough verified project context to resume work without relying on chat history. This handoff summarizes the current state; the repository's task, review, and decision records remain authoritative.

## First steps

1. Open this repository at `C:\Users\User\fpl-brief`.
2. Read `AGENTS.md`, `ops/WORKFLOW.md`, `ops/DECISIONS.md`, `ops/TASK.md`, `ops/REVIEW.md`, and the latest relevant section of `ops/IMPLEMENTATION_REPORT.md` before changing anything.
3. Inspect `git status` and the actual diff. The worktree already contains substantial modified and untracked work, including `cloud/`, TypeScript/Vite files, data files, and test changes. Treat it as user-owned. Preserve it; do not reset, clean, overwrite, stage, or commit it as a shortcut.
4. Establish which task and review state apply to the exact checkout. Older task records are retained in the ops files and some historical status fields are superseded by later reviews.

## Product and architecture

FPL Brief is a read-only Fantasy Premier League analysis tool for the user's team and the `#club-football` mini-league. It collects public FPL data into local snapshots and a readable digest, then serves a browser dashboard.

- Python (`fetch_fpl.py`, `fpl_brief/`) handles FPL API access, snapshot collection, league/rival analysis, decision gates, candidate filtering, and the bounded Research Scout.
- `dashboard.py` is the standard-library local HTTP server/API. The browser interface is strict TypeScript built with Vite (`dashboard/`). Check `dashboard/package.json` for the current scripts.
- `data/` contains saved/generated FPL and research state. `config.json` controls manager/team settings and fixed research sources. Inspect before running collectors or modifying data.
- The dashboard includes squad/formation, rivals, player pool/Candidate Lens, Wildcard planning, Research Desk, and a Team Decision Desk with a chip ledger.
- Wildcard drafts are browser-local. Research collection is deterministic and bounded; captured text is not automatically verified, interpreted as confirmed news, or converted into a points forecast.

## Workflow and product guardrails

Follow `ops/WORKFLOW.md`: the Supervisor defines a bounded task in `ops/TASK.md`; the Programmer changes only the allowed paths and records factual results in `ops/IMPLEMENTATION_REPORT.md`; the Supervisor independently reviews the diff and tests in `ops/REVIEW.md`. The user is the Overseer and retains product and release decisions. Use the documented economical model defaults unless unavailable; ask before substituting a materially different model.

Keep the app read-only with respect to FPL accounts: no login, transfers, or FPL write actions. Respect the user's prior preference for no dashboard password, but treat any public deployment as a separate privacy/release decision. Never create hosting resources, push, publish, disclose a new public URL, or deploy without explicit Overseer approval. Do not create secrets, a database, persistent storage, or scheduled hosting jobs without a separately approved task.

Decision displays must show their evidence and freshness, distinguish official FPL availability from transfer advice, retain uncertainty where data is absent or stale, and label captured research as unverified unless the source is actually reviewed. Do not invent point forecasts or player news.

## Verified status at handoff

- The Team Decision Desk and chip ledger are marked **APPROVED LOCALLY** in the final section of `ops/REVIEW.md`. The final review recorded 82 Python tests, 10 Node tests, TypeScript typecheck, production build, Python compile checks, and `git diff --check` passing on 2026-09-24. A narrow/mobile visual inspection was explicitly not completed.
- This is prior verification, not a claim that the current dirty checkout still passes. Re-run the applicable checks after inspecting the current diff.
- No live refresh or research collection was run for that feature closeout. The saved snapshot/research packet may be stale or legacy; inspect the current dashboard/data timestamps before drawing football conclusions.
- Railway deployment is **not approved**. The task history says a clean deployment checkout does not include the ignored Vite `dashboard/dist/` bundle, and the Python server needs a defined way to serve the built frontend. `ops/REVIEW.md` also retains an earlier Railway readiness **CHANGES_REQUESTED** verdict. Resolve the actual current findings and bundle/artifact path in a new bounded local task; do not treat older `APPROVED` text as release approval.
- No commit, push, Railway upload, deployment, or service creation was part of the locally approved Team Decision Desk milestone.

## Recommended next work

The most useful next engineering milestone is to reconcile Railway readiness and make the TypeScript/Vite build work from a clean checkout, while keeping the work local. Before implementation, the Supervisor should inspect the exact current branch, diff, and existing Railway task/review history, then create/update a bounded task with allowed paths and acceptance tests. The task should cover the build artifact and Python static-file serving path, a clean-checkout/local production smoke test, and any still-current review findings. Keep user data and the current public-access choice explicit in the plan.

After local independent review, stop and ask the Overseer before any push, hosting change, or deployment. Separately, perform a mobile visual check and a user-triggered FPL/research refresh when the user is ready; these are not prerequisites to editing the deployment packaging task.

## Verification commands

Run from the repository root, as applicable to the bounded task:

```powershell
python -m unittest discover -s tests -v
node --test tests/*.mjs
npm run typecheck --prefix dashboard
npm run build --prefix dashboard
python -m py_compile dashboard.py fetch_fpl.py fpl_brief\collect.py fpl_brief\research.py fpl_brief\research_scout.py
git diff --check
```

Use fixtures for automated tests; do not trigger live collection as a test. The README and `ops/WORKFLOW.md` contain the fuller run instructions and release gates.
