# Graph Report - fpl-brief  (2026-09-22)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 204 nodes · 411 edges · 15 communities (8 shown, 7 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 13 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3f7e3617`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11

## God Nodes (most connected - your core abstractions)
1. `assess()` - 14 edges
2. `main()` - 13 edges
3. `evidence_status()` - 12 edges
4. `render()` - 11 edges
5. `lens()` - 11 edges
6. `read_json()` - 11 edges
7. `Handler` - 10 edges
8. `esc()` - 9 edges
9. `Client` - 9 edges
10. `collect()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `snapshot_status()` --calls--> `snapshot_freshness()`  [EXTRACTED]
  dashboard.py → fpl_brief/decision.py
- `load_plans()` --calls--> `read_json()`  [EXTRACTED]
  dashboard.py → fpl_brief/storage.py
- `research_result()` --calls--> `evidence_status()`  [EXTRACTED]
  dashboard.py → fpl_brief/research.py
- `research_result()` --calls--> `load_packet()`  [EXTRACTED]
  dashboard.py → fpl_brief/research.py
- `main()` --calls--> `meaningful_changes()`  [EXTRACTED]
  fetch_fpl.py → fpl_brief/analyze.py

## Import Cycles
- None detected.

## Communities (15 total, 7 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.10
Nodes (32): availability(), build_digest(), fixture_map(), format_money(), format_number(), gameweeks(), main(), Build a concise, read-only Fantasy Premier League team digest. (+24 more)

### Community 1 - "Community 1"
Cohesion: 0.11
Nodes (16): compare_squads(), meaningful_changes(), select_rivals(), squad_ids(), Client, FetchError, RuntimeError, availability() (+8 more)

### Community 2 - "Community 2"
Cohesion: 0.11
Nodes (19): default_plans(), evaluate_plan(), Handler, load_plans(), plans_path(), player_map(), Local, read-only dashboard for the FPL Brief snapshot., Validate a locally saved scenario against the current player catalog. (+11 more)

### Community 3 - "Community 3"
Cohesion: 0.21
Nodes (23): activate(), add(), date(), esc(), event(), load(), money(), overview() (+15 more)

### Community 4 - "Community 4"
Cohesion: 0.15
Nodes (12): datetime, assess(), parse_time(), Auditable, deterministic decision gates for the FPL desk., Return a rules-only next decision, or block decisions when facts are unsafe., Return a UTC timestamp for an FPL ISO value, or None when absent/invalid., snapshot_freshness(), Optional Jev decision-layer status. Network use stays opt-in. (+4 more)

### Community 5 - "Community 5"
Cohesion: 0.24
Nodes (8): fixture_difficulties(), is_available(), lens(), player_map(), Transparent, legal replacement filters for the FPL Candidate Lens., Return legal same-position alternatives with every applied rule exposed., xgi_per_90(), CandidateLensTests

### Community 7 - "Community 7"
Cohesion: 0.48
Nodes (5): activate(), openLens(), openResearch(), runLens(), squadOptions()

### Community 10 - "Community 10"
Cohesion: 0.40
Nodes (5): FetchError, get(), RuntimeError, Raised when FPL data cannot be downloaded after retrying., Download JSON from the public FPL API with bounded retry attempts.

## Knowledge Gaps
- **2 isolated node(s):** `state`, `pos`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 61 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `assess()` connect `Community 4` to `Community 0`, `Community 2`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Why does `DigestTests` connect `Community 6` to `Community 4`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `Client` connect `Community 1` to `Community 0`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **What connects `state`, `pos` to the rest of the system?**
  _2 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.1 - nodes in this community are weakly interconnected._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.11397849462365592 - nodes in this community are weakly interconnected._
- **Should `Community 2` be split into smaller, more focused modules?**
  _Cohesion score 0.11494252873563218 - nodes in this community are weakly interconnected._