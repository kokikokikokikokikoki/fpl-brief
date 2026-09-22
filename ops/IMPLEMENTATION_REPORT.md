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
