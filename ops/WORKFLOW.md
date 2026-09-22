# Two-role workflow

## Ownership

- **Overseer (user):** sets product direction and resolves decisions recorded in `DECISIONS.md`.
- **Supervisor/Reviewer:** defines the bounded milestone in `TASK.md`, reviews the delivered diff and test evidence, and owns `REVIEW.md`. Does not implement the milestone under review.
- **Programmer:** changes only allowed implementation paths, runs the task's test command, and records factual results in `IMPLEMENTATION_REPORT.md`. Does not approve their own work.

## Future default model matrix

| Role / work | Default model | Reasoning effort | Use |
| --- | --- | --- | --- |
| Overseer (product and release direction) | User-selected | User-selected | Product, risk, and release decisions. |
| Overseer milestone architecture / adjudication | gpt-5.6-sol | high | Milestone architecture decisions and contested adjudication. |
| Supervisor / Reviewer (routine) | gpt-5.6-terra | medium | Task contracts, standard reviews, and independent verification. |
| Supervisor / Reviewer (high risk or release) | gpt-5.6-terra | high | High-risk changes and release-gate reviews. |
| Programmer | gpt-5.6-luna | medium | Bounded implementation tasks with explicit acceptance criteria and tests. |
| Research Scout collection | No model | n/a | Deterministic local collection, validation, and storage only. |

These are defaults for future milestones. A task may request a different model only when its `TASK.md` records the reason and the Overseer accepts the trade-off.

## State machine

`DRAFT → READY_FOR_PROGRAMMER → IN_PROGRESS → IN_REVIEW → APPROVED`

From `IN_REVIEW`, a failed gate goes to `CHANGES_REQUESTED → IN_PROGRESS`. A blocked task goes to `BLOCKED` with the blocker and required decision recorded in `TASK.md`; the Supervisor returns it to `READY_FOR_PROGRAMMER` when resolved. Only the Supervisor changes task state, except that the Programmer may move `READY_FOR_PROGRAMMER` or `CHANGES_REQUESTED` to `IN_PROGRESS`, then `IN_PROGRESS` to `IN_REVIEW` on handoff.

## Handoff

Before implementation, the Supervisor fills in objective, acceptance criteria, allowed paths, test command, and status in `TASK.md`. On delivery, the Programmer supplies changed paths, behavior, test command and outcome, limitations, and any architecture update in `IMPLEMENTATION_REPORT.md`, then marks the task `IN_REVIEW`. The Supervisor inspects the actual diff and relevant code, runs the specified and any focused tests, then writes a dated PASS or FAIL review with file/line evidence in `REVIEW.md`. A FAIL includes a bounded follow-up task in `TASK.md`.

## One writer and release gate

Only the active role writes its owned report. During implementation the Programmer alone writes application code; during review the Supervisor writes only `AGENTS.md` and `ops/` unless a new task explicitly changes that scope. Do not edit the same file concurrently. Release or deployment requires `APPROVED`, a passing review and tests, and an explicit Overseer decision to release; approval of a milestone alone does not publish it.
