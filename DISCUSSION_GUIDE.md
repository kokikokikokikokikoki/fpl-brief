# #club-football discussion procedure

1. Run `python fetch_fpl.py` and read `digest.md`, `data/latest.json`, and `data/changes.json`.
2. Stop if the snapshot is stale, incomplete, or the target deadline has passed.
3. Research official club statements and manager press conferences first. Use attributable reporting second and FPL flags as supporting evidence.
4. Cover flagged squad players, watchlist targets, and realistic captain candidates. Label each claim as `confirmed`, `reported`, `prediction`, or `unresolved`, with a source URL and retrieved time.
5. Ask for unrecorded free transfers, selling prices, and any changes after the public squad snapshot before claiming a move is affordable.
6. Compare hold/wait plus no more than three realistic actions over the six-gameweek horizon. Consider likely minutes, fixtures, bench cover, costs, chips, and the league gap.
7. Recommend one action, one credible alternative, and the news that would change the recommendation. Do not make a lineup or transfer recommendation after the deadline.
8. Record a final user-approved decision in `data/journal.json`; do not infer it from a recommendation.

Use this response structure:

```text
League situation:
Important new information:
Recommendation:
Why:
Alternative:
What would change this:
Captain / vice:
Bench:
Unconfirmed inputs:
Sources:
```
