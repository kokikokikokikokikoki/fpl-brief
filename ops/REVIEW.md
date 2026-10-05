# Independent review: Stage 2 (our own expected-points model, with a backtest)

**Date:** 2026-10-05
**Reviewer:** Opus 5.5 subagent, medium effort (did not implement this work)
**Verdict:** **PASS** (nothing blocking; the calibration finding is explained below, and optional items follow)

## Checks

- **Scoring, 2026/27 (§0)** (`fpl_brief/xp_model.py:30-34`, `153-166`):
  - Goals are 10/6/5/4 and assists 3. Clean sheets are 4/4/1/0.
  - Goals conceded apply to GK/DEF only (`CONCEDED_POSITIONS`, line 161). Saves are zeroed for non-GK (lines 126-127).
  - The clean sheet needs 60+ minutes: `CS[pos]·p_60·P(CS)` (line 160).
  - Appearance is `p_play + p_60` (line 157).
  - DGWs sum the club's fixtures and BGWs give 0, because the loop runs over an empty list (lines 224-230).
- **Shrinkage (§2):**
  - `shrink = (events + k·prior)/(exposure + k)` (line 52).
  - Attack uses k = 900 minutes, i.e. 10 × 90-minute units (lines 20 and 123), towards the position × price-band prior. The band edges are `now_cost` 50/65/85 (line 22).
  - A band with fewer than 900 pooled minutes falls back to the position prior (lines 101-102 and 122).
  - Defcon, bonus, cards and saves use k = 10 matches towards the position mean (lines 21 and 125).
  - Priors are pooled from this season's history rows only (lines 95-103).
  - There are no `history_past` or `element-summary` calls. The only `client.get` calls in `fpl_brief/` are the existing ones. `event/{gw}/live/` is reused (`collect.py:152`) and its player rows are taken from the same response (`collect.py:154-155`).
- **Minutes and availability:**
  - The window is the last 4 club GWs, weighted 0.8^age (`xp_model.py:131-150`). A missed club GW counts as 0 minutes.
  - `u`/`n` give 0 for the whole horizon (line 204).
  - `i`/`s` give 0 until the GW the news implies, or next GW + 2 if it gives none, and never before next GW + 1 (lines 183-209). That means 0 for the next GW.
  - A doubt multiplies the next GW only (line 211).
  - Each case adds a labelled flag (lines 205, 209 and 211). `skip_absence` makes a returning player play at his pre-absence rate (lines 139-141, 219).
- **Poisson** `E[floor(GC/2)]` is summed directly up to 60 goals (lines 55-63), which is ample for any realistic λ.
- **Backtest, no leakage** (`fpl_brief/backtest.py:27-38`), verified in the code:
  - Team ratings are fitted on `results` with `gw < k` (lines 29-30).
  - `xp_model.fit(rows, players, before, before_gw=k)` filters the history rows (`xp_model.py:79`) and the club GWs (`xp_model.py:107`) to `< k`.
  - The GW k fixture list supplies only the opponents and home/away; scores are never read.
  - The baselines also skip `gw >= k` (`backtest.py:45`).
  - `neutral()` strips today's availability news (line 22-24), so no future news leaks in.
  - The remaining leak is today's `now_cost` for the price bands and the top-100 set. It is minor and stated in the note (line 118-119).
- **Metrics:**
  - MAE is `Σ|p−a|/n` (line 125).
  - Spearman is the Pearson correlation of average ranks, with ties sharing ranks (lines 56-79). It returns `None` for constant input or n < 3.
  - The pooled MAE is over all player-GWs. ρ is the mean of the per-GW values, as the table states (lines 130-135).
- **ep_log** (`collect.py:179-190`) is append-only: an existing GW key is never overwritten (line 182), and a non-int GW is a no-op. `data/ep_log.json` holds one GW (6) with 667 players and is 6,672 bytes.
- **player_history** (`collect.py:112-166`):
  - It is columnar: `fields` once, then 1,538 rows for GW1–5 (~300 per GW), 71,681 bytes. That projects to about 550 KB at season end, under the 2 MB limit.
  - Rows are kept only for fully finished GWs (line 146).
  - `defcon_points` is taken from the `explain` points (line 129-130).
  - A player who moved clubs gets `team: null` (line 128).
  - A failed fetch keeps the previous rows for that GW (`player_history_doc`, lines 169-176).
  - It is written atomically by `fetch_fpl.py:195-201`.
- **Wiring:**
  - `projection.build(model="fpl"|"own")` rejects any other value (`projection.py:186-187`). The `own` path is at lines 200-205. The default is still `"fpl"`.
  - The lens computes both numbers and `models_differ` = |Δxp_6|/weeks > 2 (`candidates.py:35, 86-95`), and adds a `projection_own` block (line 120).
  - The plan has `horizon_delta_own`, which is `None` without history (`plan.py:97-107`).
  - `dashboard.py:682-687` passes the history file and returns `None` on read errors.
- **UI:**
  - There are two columns, and the sort can use either (`desk-tools.ts:255-265`).
  - `ownModelCell` (lines 131-140) escapes the title, each breakdown line and each flag, and shows the ≠ flag.
  - When there is no history the cell shows "—" and the note says "unavailable". The strip shows `horizon_delta_own` only when it is a number (`transfer-plan.ts:78`).
- **Old snapshots and missing files:** with `history=None`, `project_all` returns a caveat and `available: false` (`xp_model.py:246`, `projection.py:203`). This is covered by `test_build_with_own_model_and_without_history`.
- **Scope:** every changed path is in the allowed list, and `data/`/`digest.md` were regenerated by the permitted fetch. The code is stdlib only (`math`, `re`, `datetime`, `argparse`, `json`). HEAD is still `c91cf60`, so nothing was committed.
- **Tests** (the task command, run once):
  - `python -m unittest discover -s tests`: **242 OK**.
  - `npm run typecheck`: clean.
  - `npm run build`: OK.
  - `node --test tests/*.mjs`: **10/10 pass**.
- **Backtest table** (`python -m fpl_brief.backtest`), which matches the report:

  | Model | MAE all | ρ all | n all | MAE top | ρ top | n top |
  |---|---|---|---|---|---|---|
  | Our model | 2.076 | 0.370 | 916 | 2.494 | 0.401 | 215 |
  | Points per game | 2.313 | 0.301 | 916 | 2.831 | 0.342 | 215 |
  | Last 3 GWs | 2.351 | 0.310 | 916 | 2.850 | 0.352 | 215 |

## Calibration

Computed with `backtest.predict_gameweek` over GW3–5. Bias is mean predicted minus mean actual points per player-GW.

| Group | n | Mean predicted | Mean actual | Bias |
|---|---|---|---|---|
| Played (the backtest's population) | 916 | 2.49 | 3.06 | **−0.57** |
| Top 100 by price, played | 215 | 3.19 | 3.61 | **−0.41** |
| Played 60+ minutes ("starters") | 620 | 3.05 | 3.93 | **−0.88** |
| Top 100, 60+ minutes | 161 | 3.79 | 4.45 | **−0.66** |
| MID/FWD ≥ £8.5m, 60+ minutes | 15 | 5.16 | 4.87 | **+0.29** |
| Every player whose club had a fixture (non-appearances count as 0) | 2001 | 1.31 | 1.40 | **−0.08** |
| Regulars chosen before the match (model p_60 ≥ 0.75), whether or not they played | 475 | 3.58 | 3.67 | **−0.09** |
| Top 100 regulars, chosen before the match | 130 | 4.30 | 4.47 | **−0.17** |

**Why the starters number is not a FAIL.** The "starters" and "played" groups are chosen on the outcome: they keep only the matches where the player appeared or played 60+ minutes. An unconditional model, which correctly prices in some chance of not starting, must look low on such a group. When the groups are chosen on what was known before the match, the bias is about zero (−0.08 to −0.17).

Per-component bias for the 60+ starters (predicted vs actual):

| Component | Predicted | Actual | Cause |
|---|---|---|---|
| Appearance | 1.71 | 2.00 | Pure selection |
| Clean sheet | 0.42 | 0.83 | Partly the `p_60` selection; the rest is below |
| Goals | 0.55 | 0.49 | — |
| Assists | 0.21 | 0.30 | — |
| Defcon | 0.23 | 0.34 | — |
| Bonus | 0.24 | 0.29 | — |
| Conceded, saves, cards | — | — | Match |

The rest of the clean-sheet gap comes from the Stage 1 team model, which this model shares. Over GW3–5 the model gave a mean P(CS) of 0.22 and λ_against of 1.57 per team-match. The actual clean-sheet rate was 0.33, with 1.32 goals per team-match (n = 60 team-matches, about 1.8 SE).

**Premium sample** (predicted / actual per GW, GW3–5):

| Player | Predicted / actual | Mean predicted vs actual |
|---|---|---|
| Haaland (411) | 5.5/9, 5.2/9, 5.7/6 | 5.5 vs 8.0 |
| Groß (124) | 3.9/1, 3.8/17, 4.3/14 | 4.0 vs 10.7 |
| Saka (12) | 4.4/2, 4.1/8, 6.3/2 | 4.9 vs 4.0 |
| B. Fernandes (426) | 5.2/2, 5.1/2, 6.8/2 | 5.7 vs 2.0 |
| Palmer (154) | | 4.6 vs 2.7 |
| Isak (379) | | 5.1 vs 7.7 |
| Semenyo (397) | | 4.7 vs 8.7 |
| Mbeumo (427) | | 5.9 vs 4.0 |
| Gibbs-White (480) | | 5.4 vs 4.3 |

Premium attackers who started: +0.29 overall. There is no systematic low bias. The ~4–6 xP/GW for premiums is in line with their realised ~5/GW, so the 7–14 gap mostly reflects Stage 1's `ep_next` (a 30-day form average), not under-prediction here. Elite outliers such as Haaland are under-predicted, because k = 900 minutes holds them near the band prior after only 2–4 GWs (see Optional 2).

**Caveat:** the sample is only 3 GWs (about 300 players each) and the priors are early-season. Re-check this before any decision to switch the default.

## Blocking

None.

## Optional

1. **Report bias in the backtest.**
   - **Problem:** the backtest scores only players who played (`backtest.py:95`), and its table has no bias column. Because points are skewed, MAE can reward a low model.
   - **Fix:** add mean(pred − actual) per model. Also add an "all squad players with a fixture" population, with non-appearances as 0, so that calibration is visible before the Overseer decides on the default.
2. **Elite outliers are held back by the attack prior.**
   - **Problem:** k = 900 min keeps Haaland's ~1.0 xG/90 close to the £8.5m+ FWD band prior early in the season. Haaland is predicted 5.5/GW and scored 8.0/GW.
   - **Fix:** this is to spec. Revisit k, or a finer top band, once more GWs exist.
3. **Clean sheets are under-predicted by the shared Stage 1 team model.**
   - **Problem:** over GW3–5 the model predicted P(CS) 0.22 against an actual rate of 0.33.
   - **Fix:** monitor it as GWs accumulate. Any fix belongs to `projection.py`'s rating fit, not this task.
4. **`collect.py:150-158`: one failure loses both datasets.**
   - **Problem:** the player-row parsing runs inside the same `try` as the xG aggregation. A malformed player row would therefore also drop that GW's club xG (it falls back to goals).
   - **Fix:** wrap `player_rows` separately.
5. **Not checked in a browser.**
   - **Problem:** the report says the UI was not viewed in a browser, and neither was it here. The `<details>` inside a table cell and the 11-column table on a phone are checked only by the type check, the build and the node render test.
   - **Fix:** take a quick visual check before release.
