# Programmer implementation report

**Task:** Stage 2 follow-up — clean-sheet calibration, backtest bias, collector isolation (ops/TASK.md)
**Date:** 2026-10-05
**Status:** IN_REVIEW
**Programmer:** Opus 5.5 subagent, medium effort

## Changed paths

- `fpl_brief/projection.py`: new `goal_level`, `combined_shape`, `zero_chance`, `_average`; `team_ratings` returns `level`, `attack_shape`, `defence_shape`, `prior_shape` as well; `fixture_view` uses `level` and the negative-binomial clean-sheet chance and returns `cs_shape`; module docstring and Stage 1 method text.
- `fpl_brief/xp_model.py`: `expected_half_goals(lam, shape=None)` (negative binomial when a shape is given); `fixture_points` passes `view["cs_shape"]`; `METHOD` text.
- `fpl_brief/backtest.py`: `bias` in every score; second population (`fixture_all`, `fixture_top`); per-GW `with_fixture` and `fixture`; two-block table; docstring and note.
- `fpl_brief/collect.py`: `team_results` parses player rows in their own `try` block (lines ~152–164).
- `tests/test_projection.py`, `tests/test_xp_model.py`, `tests/test_backtest.py`; `README.md` (method text only); `ops/TASK.md` (status line only).

No fetcher run, no data files changed, nothing committed.

## 1. Diagnosis (numbers, no leakage)

Method: for each GW k in 3–5, ratings fitted on `team_results` with `gw < k` only, then `fixture_view` for both sides of every GW k fixture (60 team-matches). Data: `data/latest.json` `team_results` (50 fixtures, GW1–5, xG on all of them).

League levels by GW (per club per match):

| GW | Goals | xG | Clean-sheet rate | Home goals / away goals per match |
|---|---|---|---|---|
| 1 | 1.50 | 1.54 | 0.30 | 2.2 / 0.8 |
| 2 | 1.60 | 1.70 | 0.20 | 1.5 / 1.7 |
| 3 | 1.15 | 1.43 | 0.30 | 1.1 / 1.2 |
| 4 | 1.45 | 1.34 | 0.35 | 1.1 / 1.8 |
| 5 | 1.35 | 1.62 | 0.35 | 1.7 / 1.0 |
| GW1–5 | 1.41 | 1.53 | 0.30 | |

Candidates checked:

1. **League level from xG (main cause of the λ gap).** The fitted `base` was 1.62 / 1.56 / 1.50 for GW3 / 4 / 5, and the mean λ_against was 1.57. Season-wide, xG ran 1.53 per club-match against 1.41 actual goals (+8%). Swapping only the level to actual goals (ratings unchanged): mean λ_against 1.57 → 1.47, mean P(CS) 0.216 → 0.238.
2. **Plain Poisson on a point estimate (main cause of the zero gap).** Even with an oracle level (each GW's actual goal rate), Poisson gives a mean P(CS) of 0.275 against 0.333 actual. Over GW1–5 the goals-against counts have variance 1.66 against a mean of 1.41, with 30 zeros where Poisson(1.41) expects 24.4: overdispersed. The model used `exp(−λ)` on the shrunk point estimate of λ. The ratings are posterior means with real uncertainty left in them (6 pseudo-matches plus 2–4 real matches), and E[e^−λ] > e^−E[λ] (Jensen). Using the uncertainty the shrinkage already implies (below), with the xG level unchanged: 0.216 → 0.252.
3. **Dixon–Coles τ: ruled out.** τ preserves each team's marginal goal distribution. P(away scores 0) = Σ_h P(h, 0)·τ = e^−μ[e^−λ(1−λμρ) + λe^−λ(1+μρ) + Σ_{h≥2} P(h)] = e^−μ, because the ρ terms cancel (−λμρe^−λ + λμρe^−λ). It changes P(0-0) and P(1-1), not P(clean sheet), so it cannot fix this.
4. **Home factor: a contributor, but noise, so not changed.** H was fitted at 1.08–1.15, mostly from GW1 (home 2.2 vs away 0.8). GW3–5 had no home edge (home 1.30 vs away 1.33 goals per match). After the fix the home sides are calibrated (λ 1.30 vs 1.33 conceded; P(CS) 0.31 vs 0.30). The away sides still over-predict conceding (λ 1.65 vs 1.30; P(CS) 0.23 vs 0.37). That is 30 team-matches each, against a well-established long-run home advantage, so I kept the shrunk home factor.

## 2. The fix and why it is principled

Two changes. Each removes one diagnosed cause, and neither is a fudge factor.

- **Goal-anchored level** (`projection.goal_level`, `team_ratings` → `level`). xG still sets every club's relative attack/defence rating (the fit is unchanged). The absolute scale of λ is the league's actual goals per club-match over the same earlier matches, because goals are what score FPL clean sheets and conceded points. If there are no goals yet, it falls back to the xG level. `att_mult = λ_for / level` equals A·D·venue, so attack multipliers and the own model's goals/assists are unchanged.
- **Rating uncertainty in P(CS)** (`combined_shape`, `zero_chance`). The shrinkage `D = (conceded + m·base)/(expected + m·base)` is the posterior mean of a Gamma–Poisson model, with shape = pseudo-count + observed total (`defence_shape`; `attack_shape` likewise). The opponent's attack and the club's defence are combined into one Gamma by matching CV² (1/a + 1/d + 1/(a·d)). Integrating Poisson over that Gamma gives the negative binomial: P(0) = (1 + λ/α)^−α. The mean λ is unchanged, so goals-against calibration depends only on the level. The uplift shrinks as matches accumulate (α grows), so it disappears late in the season. There are no new constants: the shape comes from the existing `PRIOR_MATCHES` and the data. `expected_half_goals` uses the same negative binomial, so the conceded points stay consistent with P(CS). The Stage 1 `cs_mult` reference uses the same form for an average fixture, so an empty season still gives exactly 1.0.

## 3. Calibration, GW3–5 (60 team-matches, ratings from earlier GWs only)

| | Mean P(CS) | Mean λ_against | CS log-loss | CS Brier |
|---|---|---|---|---|
| Actual | **0.333** | **1.317** | | |
| Before | 0.216 | 1.570 | 0.686 | 0.238 |
| Goal level only | 0.238 | 1.473 | 0.671 | 0.234 |
| Uncertainty only | 0.252 | 1.570 | 0.662 | 0.231 |
| **After (both)** | **0.272** | **1.473** | **0.654** | **0.228** |

The remaining gaps are within about 1 SE: CS 0.061 (SE ≈ 0.061) and goals against 0.16 (SE ≈ 0.17). Most of what is left is the away-side home-factor noise above.

Own model bias by position (every player whose club had a fixture, GW3–5):

| Position | Before | After |
|---|---|---|
| GK (n 219) | −0.250 | −0.180 |
| DEF (n 651) | −0.186 | −0.087 |
| MID (n 894) | −0.009 | +0.007 |
| FWD (n 237) | +0.067 | +0.067 |

## 4. Backtest (`python -m fpl_brief.backtest`), before → after

The bias column is new. "Fixture" means every player whose club (today's club) had a fixture, with a no-show scored 0. The baselines don't use the team model, so only "our model" changes.

Players who played:

| Model | MAE all | ρ all | bias all | n | MAE top | ρ top | bias top | n top |
|---|---|---|---|---|---|---|---|---|
| Our model, before | 2.076 | 0.370 | −0.566 | 916 | 2.494 | 0.401 | −0.414 | 215 |
| **Our model, after** | 2.090 | 0.372 | **−0.476** | 916 | 2.499 | 0.409 | **−0.364** | 215 |
| Points per game | 2.313 | 0.301 | −0.223 | 916 | 2.831 | 0.342 | +0.280 | 215 |
| Last 3 GWs average | 2.351 | 0.310 | −0.414 | 916 | 2.850 | 0.352 | +0.173 | 215 |

Every player whose club had a fixture (no-show = 0):

| Model | MAE all | ρ all | bias all | n | MAE top | ρ top | bias top | n top |
|---|---|---|---|---|---|---|---|---|
| Our model, before | 1.125 | 0.721 | −0.084 | 2001 | 1.939 | 0.672 | −0.146 | 300 |
| **Our model, after** | 1.138 | 0.720 | **−0.037** | 2001 | 1.944 | 0.676 | **−0.108** | 300 |
| Points per game | 1.339 | 0.662 | +0.174 | 2001 | 2.414 | 0.569 | +0.586 | 300 |
| Last 3 GWs average | 1.240 | 0.693 | −0.027 | 2001 | 2.232 | 0.621 | +0.313 | 300 |

Bias improves in every cell. MAE rises by about 0.01, which is expected: points are right-skewed, so MAE is minimised by the median rather than the mean, and raising GK/DEF predictions towards their mean costs a little MAE. ρ is flat to slightly better. The "played" bias stays negative by construction, because that population is chosen on the outcome (see the Stage 2 review).

## 5. Six-gameweek totals (GW6–11), before → after

| Player | FPL-based (Stage 1) | Our model | Our model's clean-sheet points |
|---|---|---|---|
| Van Hecke 112 | 45.75 → 43.23 | 20.00 → 21.54 | 4.93 → 6.19 |
| De Cuyper 115 | 50.74 → 48.97 | 24.17 → 25.78 | 4.01 → 5.26 |
| Gvardiol 391 | 54.76 → 53.51 | 23.23 → 24.83 | 5.25 → 6.57 |
| Hall 449 | 34.47 → 34.31 | 24.19 → 25.79 | 4.83 → 6.15 |
| Calafiori 8 | 17.71 → 17.76 | 25.81 → 27.28 | 7.87 → 9.16 |
| Haaland 411 | 57.32 → 56.78 | 35.49 → 35.49 | 0 |
| Groß 124 | 69.47 → 68.73 | 27.99 → 28.29 | 1.00 → 1.31 |
| João Pedro 165 | 18.13 → 18.26 | 17.32 → 17.32 | 0 |
| Kostoulas 138 | 47.39 → 46.89 | 25.28 → 25.28 | 0 |

- **Our model:** defenders gain about +1.5 over six weeks, from clean sheets net of slightly larger conceded deductions. Forwards are unchanged and midfielders gain a little (1 clean-sheet point each).
- **FPL-based:** the numbers move little (−2.5 to +0.1), because Stage 1 scales `ep_next` by m_k/m_0 and a uniform uplift cancels. Only the spread of clean-sheet chances between fixtures changes: the lower level and the negative binomial make it flatter. Stage 1 still inherits whatever calibration `ep_next` has.

## 6. Backtest bias and second population

- `_score` adds `bias` = mean predicted − mean actual, rounded to 3 places.
- `run` builds, per GW, the "fixture" population: every catalog player whose club (today's club) appears in that GW's `team_results`, plus anyone who played, with actual = `total_points` or 0.
- `summary` rows have `all`, `top` (played, as before) plus `fixture_all` and `fixture_top`. Per-GW rows gain `with_fixture` and a `fixture` dict of scores.
- The text table prints both populations with a bias column, and `--json` carries both.

## 7. Collector isolation

In `team_results`, the live fetch and `_xg_by_fixture` stay in the first `try` block. Player rows are parsed in a separate `try` that runs only after a successful fetch. A malformed player row now drops that gameweek's player rows, with the warning "Could not read GW{n} player rows; club xG is kept and so is any earlier player history for that week". `player_history_doc` already keeps the previous file's rows for any GW missing from this run. Club xG for that GW is always kept.

## Tests

- **New:**
  - `CleanSheetCalibrationTests` (3): a synthetic season of six equal clubs with xG 1.6 and goals 1.1, where the actual clean-sheet rate of 0.30 is predicted within 0.05 and mean λ ≈ 1.1. The old xG-level Poisson value of 0.20 shows the test is meaningful. Also the no-goals fallback to the xG level, and `zero_chance`/`combined_shape` properties.
  - `test_expected_half_goals_negative_binomial`: matches an explicit NB sum, and a huge shape gives the Poisson value.
  - `test_bias_and_the_club_had_a_fixture_population`: bias equals a hand computation in both populations; a never-playing player is counted with 0; a player whose club has no fixture is excluded; top subsets, per-GW fields, table text and JSON keys.
  - `test_bad_player_row_drops_only_that_gameweeks_player_rows_not_club_xg`.
- **Changed assertions:**
  - `test_projection.test_strong_attack_against_weak_defence_has_higher_multiplier`: `cs_prob` was asserted to equal `exp(−λ)`. It now equals the NB form `(1+λ/α)^−α` and is greater than `exp(−λ)`. This is the intended change.
  - `test_xp_model.test_points_follow_the_2026_27_table_by_position`: the expected conceded value now passes `view["cs_shape"]`, matching the model.
  - `test_backtest.test_report_scores_models_and_baselines`: `spearman == 1.0` became `> 0.8`. In that toy season, goals (1.0 per side) run below xG (1.1), so the defender (2 actual points) now gets 4.2–4.3 xP against the 3-point midfielder's 4.1–4.2 in two of three weeks. The ranking is otherwise unchanged, and this is the calibration change working as intended.
- **Results** (full command, run once):
  - `python -m unittest discover -s tests`: **248 OK** (242 before, +6).
  - `npm run typecheck --prefix dashboard`: clean.
  - `npm run build --prefix dashboard`: OK.
  - `node --test tests/*.mjs`: **10/10 pass**.
  - `python -m fpl_brief.backtest`: the table in §4.

## Limitations

- **Small sample.** There are three GWs (60 team-matches), so every calibration figure has an SE of about 0.06 on the CS rate. Re-check this at GW10.
- **Early-season noise in the level.** After GW1 the goal level comes from 20 team-matches, which is noisier than xG (SE ≈ 0.27). This matters only for the own model's clean-sheet and conceded points; Stage 1 multipliers are relative. A light shrink of the goal level towards the xG level is a possible refinement. I did not add one, to keep the change minimal and constant-free.
- **Two scales in the own model.** Player goals and assists still use xG/90 rates, while the defence side uses the goal level. That is deliberate: attack uses only relative multipliers, so the two don't interact. Even so, the own model's attack is on the xG scale, and xG runs about 8% above goals this season.
- **Shape approximation.** Treating xG totals as Poisson pseudo-counts in the Gamma shape slightly overstates the uncertainty. xG is less noisy than goals, which makes the uplift conservative-to-generous early. Matching the product of two Gammas by CV² is an approximation.
- **Home factor.** It is unchanged, and it still drives the away-side residual over GW3–5.
- **Today's club.** The "fixture" population uses today's club, so a player who moved after GW k is assigned to the wrong club for that GW. Prices are today's, as before.
