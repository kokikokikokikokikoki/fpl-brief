# Two-role workflow

## Ownership

- **Overseer (user):** sets product direction and resolves decisions recorded in `DECISIONS.md`.
- **Supervisor/Reviewer:** defines the bounded milestone in `TASK.md`, reviews the delivered diff and test evidence, and owns `REVIEW.md`. Does not implement the milestone under review.
- **Programmer:** changes only allowed implementation paths, runs the task's test command, and records factual results in `IMPLEMENTATION_REPORT.md`. Does not approve their own work.

## Default model and escalation guidance

Choose the cheapest model capable of the task. Astra is exceptional and should remain reserved for consequential architecture or review decisions.

| Role / work | Default model | Reasoning effort | Guidance |
| --- | --- | --- | --- |
| Overseer product and release decision | User-selected | User-selected | The Overseer retains product direction and release authority. |
| Major architecture or high-risk adjudication | gpt-6-astra | low (Light in desktop) | Use for consequential architecture or difficult risk decisions. |
| Supervisor / Reviewer, routine | gpt-6-sol | medium | Use for task definition, standard reviews, and ordinary independent verification. |
| Supervisor / Reviewer, high risk | gpt-6-astra | low (Light in desktop) | Escalate security, data-loss, and public-release reviews. |
| Programmer, clear bounded task | gpt-6-luna | high | Default for implementation with clear scope and acceptance criteria. |
| Programmer, ambiguous or technically demanding task | gpt-6-sol | medium | Use for cross-module work or materially ambiguous implementation; record the reason in `TASK.md`. |
| Research Scout collection | No model | n/a | Keep collection, validation, and storage deterministic. |

These are defaults for future milestones. Model availability can vary during account or workspace rollout. If the specified model is unavailable, state the limitation and ask the Overseer before using a materially different substitute. A task may override these defaults only when `TASK.md` records the reason and the Overseer accepts the trade-off.

### Claude Code sessions

When the work runs in Claude Code, use this mapping instead of the table above. Sonnet is not used (Overseer decision, 2026-09-25).

| Role / work | Model | Effort | Guidance |
| --- | --- | --- | --- |
| Supervisor: task definition, architecture | Opus 5.5 | medium | Main session. |
| Programmer: bounded or cross-module work | Opus 5.5 | medium; high if ambiguous | Main session. Record the reason for high effort in `TASK.md`. |
| Reviewer: routine milestone | Opus 5.5 subagent | medium | Always a separate subagent that did not implement the work. |
| Reviewer: security, data-loss, public-release/deploy | Opus 5.5 subagent | high | Same separation. |
| Mechanical work: whitespace, typo, or doc-only fixes, read-only file searches | Haiku 4.5 subagent | default | Only when no judgment is needed. Opus reviews the result. |
| Research Scout collection | No model | n/a | Deterministic. |

Token discipline:
- Give the reviewer the task, the changed paths, and the report instead of the whole history.
- Run the full test suite once per role; re-run only the focused tests after small fixes.
- Reuse scratch clean-checkout copies within a session.
- Do not spawn subagents where the main session can do the step cheaply. Role separation for review is the exception and is always kept.

## State machine

`DRAFT → READY_FOR_PROGRAMMER → IN_PROGRESS → IN_REVIEW → APPROVED`

From `IN_REVIEW`, a failed gate goes to `CHANGES_REQUESTED → IN_PROGRESS`. A blocked task goes to `BLOCKED` with the blocker and required decision recorded in `TASK.md`; the Supervisor returns it to `READY_FOR_PROGRAMMER` when resolved. Only the Supervisor changes task state, except that the Programmer may move `READY_FOR_PROGRAMMER` or `CHANGES_REQUESTED` to `IN_PROGRESS`, then `IN_PROGRESS` to `IN_REVIEW` on handoff.

## Handoff

Before implementation, the Supervisor fills in objective, acceptance criteria, allowed paths, test command, and status in `TASK.md`. On delivery, the Programmer supplies changed paths, behavior, test command and outcome, limitations, and any architecture update in `IMPLEMENTATION_REPORT.md`, then marks the task `IN_REVIEW`. The Supervisor inspects the actual diff and relevant code, runs the specified and any focused tests, then writes a dated PASS or FAIL review with file/line evidence in `REVIEW.md`. A FAIL includes a bounded follow-up task in `TASK.md`.

## One writer and release gate

Only the active role writes its owned report. During implementation the Programmer alone writes application code; during review the Supervisor writes only `AGENTS.md` and `ops/` unless a new task explicitly changes that scope. Do not edit the same file concurrently. Release or deployment requires `APPROVED`, a passing review and tests, and an explicit Overseer decision to release; approval of a milestone alone does not publish it.
