# Independent review: Stage 2 follow-up (clean-sheet calibration, backtest bias, collector isolation)

**Date:** 2026-10-05
**Reviewer:** Opus 5.5 subagent, medium effort (did not implement this work)
**Verdict:** **PASS** (nothing blocking; optional items follow)

Reviewed: the uncommitted diff against HEAD `40fb865` in `fpl_brief/projection.py`, `fpl_brief/xp_model.py`, `fpl_brief/backtest.py`, `fpl_brief/collect.py`, `tests/test_projection.py`, `tests/test_xp_model.py`, `tests/test_backtest.py` and `README.md`, against `ops/TASK.md` and `ops/IMPLEMENTATION_REPORT.md`.

## Checks

- **Goal-anchored level, not a fudge** (`fpl_brief/projection.py:49-59`, `119`, `144-148`):
  - `goal_level` is the league's actual goals per club-match from the same `results` passed to `team_ratings`. It returns `None` when there are no valid rows or no goals, and `team_ratings` then falls back to the xG `base` (`level: goal_level(results) or base`, line 119).
  - The fit loop is unchanged. Relative attack and defence ratings still come from xG (`_matches`, lines 32-46).
  - `fixture_view` scales both λ by `level` instead of `base` (lines 147-148). `att_mult = λ_for / level` (line 157) equals A·D·venue as before, so the attack multipliers are unchanged. That matches the report's six-week table, where the forwards and the own model's goals and assists are identical.
- **Negative-binomial P(CS) follows from the existing shrinkage** (`projection.py:113-128`, `131-139`, `149-155`):
  - The defence rating `D = (conceded + prior)/(expected + prior)` with `prior = PRIOR_MATCHES·base` is the posterior mean of a Gamma–Poisson model. Its posterior shape is `prior + conceded`, which is what `defence_shape` holds (lines 113-118). `attack_shape` is the same with goals scored.
  - The shapes therefore start at the pseudo-count (6·base ≈ 9) and grow with every match, so `combined_shape` rises and `zero_chance` tends to `e^−λ`. The test at `tests/test_projection.py` (`combined_shape(30,30) > combined_shape(8,8)`, and `zero_chance(1.4, 1e9) ≈ e^−1.4`) covers this.
  - `combined_shape` uses the exact CV² of a product of two independent mean-1 Gammas, `1/a + 1/d + 1/(a·d)` (line 128). Matching that to one Gamma is an approximation, and the report states it.
  - `zero_chance` is `(1+λ/α)^−α`, the negative-binomial P(0) (line 139). The mean λ is untouched.
  - There are no new tuning constants.
- **`E[floor(GC/2)]` uses the same distribution** (`fpl_brief/xp_model.py:55-64`, `162`):
  - It starts from `projection.zero_chance(lam, shape)`.
  - It steps by the negative-binomial ratio `P(n+1)/P(n) = (n+α)/(n+1) · λ/(α+λ)`, which is correct.
  - `fixture_points` passes `view["cs_shape"]` (line 162).
  - `test_expected_half_goals_negative_binomial` checks it against an explicit gamma-function sum to 9 places.
- **No NaN and no division by zero; deterministic:**
  - Empty input and all-zero xG return `_average` (lines 62-65). That gives `prior_shape = 6·DEFAULT_GOALS`, empty shape dicts, and every lookup falling back to `prior`.
  - `zero_chance` returns 1.0 for λ ≤ 0. `combined_shape` only ever receives values ≥ prior > 0.
  - I ran three cases with `team_ratings(..., [1,2,3])`: an empty season, an all-0-0 season with zero xG, and a 0-0 season with xG. Each gave finite values, with `cs_mult = 1.0` for the empty season and the fallback to the xG level when there were no goals.
  - Fitting on the reversed result list gave an identical ratings dict.
- **No leakage, including the new level** (`fpl_brief/backtest.py:30-38`):
  - `predict_gameweek` builds `before = [gw < k]` and passes only that to `team_ratings`, so `goal_level` and the shapes see GWs < k only.
  - GW k rows supply only opponents and venue.
  - The existing leak test (`tests/test_backtest.py:29-41`) still passes. It changes the GW ≥ 4 xG; changing the goals is covered by the same `before` filter.
- **Calibration numbers reproduced** (scratch script; ratings from `data/latest.json` `team_results`, GWs < k, both sides of every GW3–5 fixture): 60 team-matches.
  - Mean P(CS) **0.272** against an actual **0.333**.
  - Mean λ_against **1.473** against actual goals against **1.317**.
  - Both match report §3.
- **Backtest reproduced** (`python -m fpl_brief.backtest`, and `--json`): the output matches report §4 exactly.

  | Population | Model | MAE all | ρ all | bias all | n | MAE top | ρ top | bias top | n top |
  |---|---|---|---|---|---|---|---|---|---|
  | Played | Our model | 2.090 | 0.372 | −0.476 | 916 | 2.499 | 0.409 | −0.364 | 215 |
  | Played | Points per game | 2.313 | 0.301 | −0.223 | 916 | 2.831 | 0.342 | +0.280 | 215 |
  | Played | Last 3 GWs | 2.351 | 0.310 | −0.414 | 916 | 2.850 | 0.352 | +0.173 | 215 |
  | Fixture | Our model | 1.138 | 0.720 | −0.037 | 2001 | 1.944 | 0.676 | −0.108 | 300 |
  | Fixture | Points per game | 1.339 | 0.662 | +0.174 | 2001 | 2.414 | 0.569 | +0.586 | 300 |
  | Fixture | Last 3 GWs | 1.240 | 0.693 | −0.027 | 2001 | 2.232 | 0.621 | +0.313 | 300 |

  - The `--json` summary rows carry `all`, `top`, `fixture_all` and `fixture_top`.
  - The per-GW rows carry `with_fixture` and `fixture`.
  - The unavailable `ep_next` row is `{model, available}` only.
- **Second population and bias** (`backtest.py:100-117`, `134-140`):
  - `clubs` is every club in GW k's `team_results`. `squad` is every catalog player at one of those clubs (by today's club), plus anyone who played, with actual = `actual.get(pid, 0)`.
  - Bias is `Σ(p − a)/n`, i.e. mean predicted − mean actual (line 138).
  - The top subsets are taken from the same `ids`/`couples` via `zip` (line 112).
  - `test_bias_and_the_club_had_a_fixture_population` hand-computes both biases. It also checks that a never-playing player is counted with 0 and that a player whose club had no fixture is excluded (n 12 vs 15; top 3 vs 6).
- **Collector isolation** (`fpl_brief/collect.py:151-163`):
  - The fetch and `_xg_by_fixture` sit in the first `try`. On failure that block sets `live, xg = None, {}`.
  - Player rows are parsed in a second `try` that runs only when `live` is set.
  - `player_rows` builds and returns a complete list (`collect.py:118-135`), so `history.extend` is all-or-nothing and a failed GW leaves no partial rows.
  - `test_bad_player_row_drops_only_that_gameweeks_player_rows_not_club_xg` gives one player a malformed `explain` in GW1. GW1 club xG is kept (0.8 / 0.3), only the GW2 rows survive, and there is exactly one warning.
  - The granularity is per GW, not per row, which the task allows.
- **The three changed assertions are legitimate:**
  - `test_projection` `cs_prob`: it was `exp(−λ)`, the old formula. It now checks the NB form exactly and asserts that it is greater than `exp(−λ)`. The new assertion is no weaker; it tests the new definition.
  - `test_xp_model` conceded: it now passes `cs_shape`, matching `xp_model.py:162`.
  - `test_backtest` Spearman `== 1.0` → `> 0.8`. I checked the toy season.
    - GW3 predictions: defender (2 actual) 4.29 against midfielder (3 actual) 4.16.
    - GW5: 4.30 against 4.12.
    - GW4 is ordered correctly. That gives per-GW ρ of 0.8 / 1.0 / 0.8.
    - The flip comes from the goal level (1.0) running below xG (1.1), which raises the defender's CS credit. This is the intended effect, not a hidden bug. Players 1 and 4 stay first and last.
- **Scope:**
  - `git diff --name-only HEAD` lists only allowed paths, plus `ops/TASK.md` (the Supervisor's new task text) and `ops/IMPLEMENTATION_REPORT.md`.
  - No `data/` file changed, so the fetcher was not run.
  - HEAD is still `40fb865`, so nothing was committed.
  - There are no new imports: the code uses stdlib `math`, and `xp_model` already imported `projection`.
  - The README change is method text only.
- **Tests** (the task command, run once):
  - `python -m unittest discover -s tests`: **248 OK**.
  - `npm run typecheck --prefix dashboard`: clean.
  - `npm run build --prefix dashboard`: OK.
  - `node --test tests/*.mjs`: **10/10 pass**.
  - `python -m fpl_brief.backtest`: the table above.

## Calibration

| GW3–5, 60 team-matches | Mean P(CS) | Mean λ_against |
|---|---|---|
| Actual | 0.333 | 1.317 |
| Before (`40fb865`, per the earlier review and report) | 0.216 | 1.570 |
| After (reproduced) | **0.272** | **1.473** |

- **The fix closes about half the clean-sheet gap and about 40% of the goals-against gap.** The residuals are about 1 SE on 60 team-matches.
- **Bias in the "fixture" population is now close to zero.** The own model is at −0.037 all and −0.108 top, an improvement in every cell. MAE rises by about 0.013, consistent with moving GK/DEF towards their mean on a right-skewed target.
- **Diagnosis.** The report's argument that Dixon–Coles τ preserves the marginals, so it cannot change P(CS), is correct. The away-side residual is plausibly home-factor noise.

## Blocking

None.

## Optional

1. **Shape units.** `attack_shape` and `defence_shape` count xG totals as Poisson events (`projection.py:113-118`), while λ is now on the goal scale. xG is less noisy than goals, so this slightly overstates the rating uncertainty. That pushes the uplift the helpful way here, but the effect is small and stated in the report's Limitations. If the uplift looks too generous later, consider scaling the shapes by `level/base`.
2. **Empty-season prior.** With no results, P(CS) is now the prior predictive (about 0.30 at the default 1.4 goals, against `e^−1.4` = 0.25), because the shape is the pseudo-count. This is consistent with the model; it is noted only because the start-of-season own-model GK/DEF numbers will sit a little higher than before.
3. **What the uncertainty leaves out.** The NB uncertainty covers the opponent's attack and the club's defence only, not the level or the home factor. The observed overdispersion (variance 1.66 against a mean of 1.41) is also partly within-match. Some remaining CS under-prediction is therefore expected. I agree with the Supervisor's rulings:
   - accept both changes;
   - defer the goal-level shrinkage and the home-factor shrinkage;
   - re-check at about GW10.

   The goal-level shrink towards xG is the more useful of the two deferred items, because after one or two GWs the level rests on 20–40 team-matches.
4. **Stage 1 reference shape.** The `cs_mult` reference uses the arithmetic mean of the club shapes (`projection.py:154`). That is fine as a normaliser: it is exact for an empty season and only rescales Stage 1 uniformly, and a uniform scale cancels in m_k/m_0.
5. **Today's club** is used for the fixture population (stated in the report and the note). If transfers between Premier League clubs become common, use `team` from the history rows for players who played.
