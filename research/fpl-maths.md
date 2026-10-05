# How serious FPL tools do their maths — and how fpl-brief can build it

Research note, 2026-10-05 (2026/27 season, GW6 next). Written for the fpl-brief project.

**Where fpl-brief is today.** `fpl_brief/lineup.py` brute-forces the legal formations and
ranks players by FPL's own `ep_next` (next gameweek only). `fpl_brief/plan.py` checks transfers
against the rules (selling prices, bank, free transfers, 3-per-club limit) and scores them as
"change in XI `ep_next` minus hits". `fpl_brief/candidates.py` filters legal replacements and
sorts them by xGI/90 and average FDR, with no points forecast. Nothing looks more than one week
ahead, and nothing models rivals. The fetcher and dashboard use only the standard library.
The only runtime dependency, `anthropic`, is for the optional Jev feature (`requirements.txt`).

---

## 0. The rules the maths has to match (2026/27)

Points are the same as in 2025/26. Defensive contributions are still in.

| Event | GK | DEF | MID | FWD |
|---|---|---|---|---|
| Plays 1–59 min / 60+ min | 1 / 2 | 1 / 2 | 1 / 2 | 1 / 2 |
| Goal | 10 | 6 | 5 | 4 |
| Assist | 3 | 3 | 3 | 3 |
| Clean sheet (60+ min) | 4 | 4 | 1 | 0 |
| Every 2 goals conceded | −1 | −1 | 0 | 0 |
| Every 3 saves | +1 | – | – | – |
| Defensive contribution (capped at 2 per match) | – | 2 pts at 10 CBIT | 2 pts at 12 CBIRT | 2 pts at 12 CBIRT |
| Bonus | 1–3 (BPS) | | | |
| Yellow / red / own goal / pen miss | −1 / −3 / −2 / −2 | | | |

CBIT means clearances, blocks, interceptions and tackles. CBIRT adds ball recoveries.

Rules that matter for planning:
- **Squad:** £100.0m, 2/5/5/3, at most 3 players from one club.
- **Starting XI:** 1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD.
- **Transfers:** you get 1 free transfer (FT) per gameweek and can save up to 5. Each extra
  transfer costs −4 points.
- **Chips:** two sets per season (Wildcard, Free Hit, Bench Boost, Triple Captain). The first set
  must be used before the GW19 deadline and does not carry over.
- **BPS:** changed for 2026/27. CBI now earns less BPS, and goalkeepers and attackers earn more.
  This means bonus rates learned from 2025/26 are slightly biased.

The live `bootstrap-static` (checked today) shows `transfers_sell_on_fee: 0.5`,
`max_extra_free_transfers: 4`, `squad_team_limit: 3` and `squad_total_spend: 1000`. Read the
rules from `game_settings` rather than hard-coding them.

---

## 1. Expected points (xP) models

### In plain English
A player's projection is built bottom-up, like a recipe. Each step answers one question:
1. **Will he play, and for how long?** This is the minutes model. It matters most: a player who
   doesn't play scores 0.
2. **How many goals will his team score, and how many will it concede, in this fixture?** This is
   the team model, and it is where fixture difficulty comes in.
3. **What share of his team's goals and assists does he usually get?** This is the player model,
   built from xG and xA.
4. **Turn that into FPL points** using his position's scoring table, then add the "side" points:
   bonus, defensive contributions, saves and cards.

Add the points up for every fixture in a gameweek. A double gameweek adds two fixtures and a blank
adds none. Then repeat for each gameweek in the horizon.

### Team model: Poisson attack/defence ratings (Dixon–Coles family)
Every team gets an attack rating `a` and a defence rating `d`, plus one league-wide home advantage
`h`. Expected goals in a match between home team i and away team j:

```
λ_home = exp(a_i + d_j + h)        μ_away = exp(a_j + d_i)
P(home scores k) = e^-λ λ^k / k!    (Poisson)
```

**Dixon–Coles** adds a correction τ for the four low scores, because 0-0 and 1-1 happen more often
than independent Poisson predicts:
`τ(0,0)=1−λμρ, τ(0,1)=1+λρ, τ(1,0)=1+μρ, τ(1,1)=1−ρ`, and 1 for everything else.
It also weights older matches by `φ(t)=exp(−ξ·t)`. The dashee87 write-up found ξ ≈ 0.00325 per day
(a half-life of about 7 months) worked best across several seasons.

The model is fitted by maximum likelihood. Fit **xG, not goals**. AIrsenal's xG team model beats
its Dixon–Coles model in every season it tested, and the whole gain comes from the
defending/clean-sheet side.

**A stdlib-friendly fit (no scipy).** Use multiplicative ratings `A_i, D_i` with the means fixed at
1 and iterate about 50 times:

```
A_i = Σ xG_for(i) / Σ_matches (D_opp · H_venue · base)
D_i = Σ xG_against(i) / Σ_matches (A_opp · H_venue · base)
```

This is the same idea as AIrsenal's alternating attack/defence fit. To shrink a team with few
matches (promoted sides, early season), add `m` pseudo-matches at league average. AIrsenal calls
this `prior_matches`, and 5–8 is sensible.

**Key derived quantities per fixture**
- Clean-sheet probability: `P(CS) = e^(−λ_against)`, or the Dixon–Coles-corrected version.
- Expected goals-conceded deduction for GK/DEF: `E[floor(G/2)] = Σ_k floor(k/2)·Pois(k; λ_against)`.
- The team's expected goals scored, `λ_for`, which is shared out between its players.

**How fixture difficulty enters.** It enters only through `λ_for` and `λ_against`, which depend on
the opponent's ratings and on home or away. FPL's own FDR (1–5, in `fixtures` and
`element-summary.fixtures[].difficulty`) is a coarse version of the same thing. It is fine as a
fallback but too blunt to use for points.

### Player model: shares of team output
- `xG_share_p` = player's xG ÷ team xG while he was on the pitch. `xA_share_p` is the same for xA.
- Per fixture: `E[goals_p] = xG_share_p · λ_for · (E[mins_p]/90)`. Assists work the same way.
- AIrsenal splits team goals between players with a Dirichlet distribution. Its default `xg` player
  model fits that to xG/xA shares. The `conjugate` variant fits it to actual goals, with a prior
  worth 35 pooled goals.

### Minutes model (most important, most error-prone)
- Use `p_play` and `p_60`, the chances of appearing at all and of playing 60+. Estimate them from
  the last N matches (AIrsenal uses at least 3, or one per gameweek predicted). Multiply by
  `chance_of_playing_next_round/100` when FPL flags a doubt. AIrsenal treats ≤50% as "plays 0".
- AIrsenal averages the points over the player's recent minute values (for example 0, 70 and 90)
  instead of using a single mean. This handles rotation better.
- Appearance points: `xP_app = p_play·1 + p_60·1`.

### Putting it together (per player, per fixture)
```
xP = p_play + p_60                                     # appearance
   + GOAL[pos]·E[goals] + 3·E[assists]                 # attacking
   + CS[pos]·p_60·P(CS)                                # clean sheet (4/4/1/0)
   − [pos in GK,DEF]·(E[mins]/90)·E[floor(GC/2)]       # goals conceded
   + [GK]·E[saves]/3                                   # saves (approximately)
   + 2·p_60·P(defcon threshold hit)                    # DEF 10 CBIT, MID/FWD 12 CBIRT
   + bonus_rate·(E[mins]/90) − card_rate·(E[mins]/90)  # shrunk historical rates
```
Gameweek xP = sum over that team's fixtures in the gameweek.

### Data needed and where it comes from (public API)
| Need | Endpoint | Notes |
|---|---|---|
| Fixtures, home/away, FDR, scores | `fixtures/` (or `fixtures/?event=N`) | `team_h_difficulty` and `team_a_difficulty` are present |
| Per-player per-GW xG, xA, xGC, minutes, defcon, saves, bonus, starts | `event/{gw}/live/` | **One call per GW for all ~700 players**, far cheaper than 700 `element-summary` calls. Map player → team → fixture. In a double GW the stats are summed, though `explain[].fixture` splits the points |
| Per-match history incl. `defensive_contribution`, `expected_goals`, `starts` | `element-summary/{id}/` → `history` | One call per player, so use it only for shortlisted players |
| Last-season totals (for priors) | `element-summary/{id}/` → `history_past` | Season totals only |
| Availability, `ep_next`, `ep_this`, `now_cost`, `*_per_90`, set-piece order | `bootstrap-static/` | `chance_of_playing_next_round`, `status`, `penalties_order` |
| Team strength numbers | `bootstrap-static/teams[]` | **`strength_attack_*` / `strength_defence_*` are all 0 this season (checked 2026-10-05).** Do not rely on them |

**What `ep_next` is.** FPL does not publish how it is calculated. Most people believe it is a
recency-weighted, form-based average (`stats_form_days: 30`) adjusted for availability. It only
covers the next gameweek and has a strong recency bias. Treat it as one input or a sanity check,
not as ground truth.

### Open-source implementations
- **AIrsenal** (Alan Turing Institute). Component model exactly as above: xG team model with a
  Conway–Maxwell–Poisson scoreline wrapper, Dixon–Coles via `bpl`, a Dirichlet player model, a
  recent-minutes model, and empirical-Bayes bonus, defcon, cards and saves. Its
  `docs/how-it-works.md` and `docs/xg-models.md` are the best free write-up of these choices.
- **OpenFPL** (Groos, arXiv 2508.09992). Position-specific ensemble ML using FPL and Understat
  data. It matched a commercial service in prospective 2024/25 tests and did better on players
  scoring more than 2 points. It is heavier and needs Understat scraping.
- **FPL-Optimization-Tools** does not make projections. It consumes per-GW `Pts` and `xMins`
  columns from FPLReview or Solio exports.

### Pitfalls
- **Minutes errors outweigh everything else.** Rotation, returns from injury and new signings
  break it. AIrsenal found its GW1 model gave every promoted-team player and summer signing 0
  minutes, because it had no Premier League minutes history for them.
- Early season, team ratings rest on 5 games. Shrink hard, or blend with last season or with
  bookmaker odds.
- Double counting: `ep_next` already includes availability, so don't multiply by chance of
  playing twice.
- DGW/BGW: always sum over fixtures. Never multiply a per-GW number.
- Correlation: teammates' returns are correlated, for example a clean sheet for the GK and both
  CBs. This matters for variance (Section 4), not for expected values.
- Penalties and set pieces shift xG shares a lot. Use `penalties_order` when it changes.

---

## 2. Regression to the mean / Bayesian shrinkage

### In plain English
Five good games may be skill or may be luck. Shrinkage is a compromise. Start from a sensible
default rate (the "prior"), then let the player's own data pull the estimate away from it in
proportion to how much data he has. With little data you stay near the default. With lots of data
you trust the player.

### Formula (the only one you really need)
```
shrunk_rate = (player_events + k · prior_rate) / (player_exposure + k)
```
Here exposure is matches, or 90-minute units, and k is the "prior weight" in the same units.
Equivalently, `w = n/(n+k)` and `shrunk = w·observed + (1−w)·prior`.

With time weighting, each past match gets weight `exp(−ε·age)` before summing.

### Sensible defaults (from working implementations)
| Quantity | Prior | Prior weight k | Source |
|---|---|---|---|
| Bonus, defcon hit rate, cards, saves per match | position mean | **10 matches** (`n_prior=10`) | AIrsenal `empirical_bayes.py`, `def_con.py` |
| Player share of team goals/assists | pooled share of all players | **35 goals** (`n_goals_prior`) | AIrsenal `conjugate.py` |
| Player time decay | – | ε = 0.2 per year | AIrsenal `DEFAULT_PLAYER_EPSILON` |
| Team xG ratings | league average | 5–8 pseudo-matches; ε ≈ 0.6 per year | AIrsenal `xg-models.md` |
| Team goals ratings (Dixon–Coles) | – | ξ ≈ 0.00325 per day | dashee87 |

### Practical recommendations for fpl-brief
- Use **xG/xA instead of goals/assists** as the "recent form" signal. Goals minus xG (finishing)
  is mostly noise over one season, and the finishing-skill literature says to shrink G/xG hard
  towards 1.
- Use **last season's per-90 rate** (`history_past`, adjusted for any team change) or a
  position × price-band mean as the prior, with about 900 minutes (10 full matches) of weight.
  By GW10 a regular starter is about 50/50 between his own data and the prior.
- `form` and `ep_next` are 30-day averages. Never use them alone to rank.

### Pitfalls
- Shrinking towards the wrong prior, such as the all-player mean for a premium forward. Use a
  position and price group.
- A change of role (new position, new club, new penalty taker) makes old data stale. Reset or
  downweight it.

---

## 3. Squad and lineup optimisation as integer linear programming

### In plain English
"Pick 15 players under £100m, max 3 per club, a legal XI and a captain, to maximise points" is a
puzzle with millions of combinations. An **integer linear program (ILP)** describes it with yes/no
variables ("is player p in my squad in week w?") plus linear rules. A solver such as HiGHS then
finds the provably best answer in seconds.

The multi-week version adds "who do I buy and sell each week?". It tracks the bank and the number
of free transfers week by week. Because transfers have lasting value, the solver will happily take
a −4 now if the player pays it back over six weeks.

### Variables (from `sertalpbilal/FPL-Optimization-Tools`, `dev/solver.py`)
For each player p and gameweek w in the horizon:
- Binaries: `squad[p,w]`, `lineup[p,w]`, `captain[p,w]`, `vicecap[p,w]`,
  `bench[p,w,o]` (o = 0 for the GK, 1–3 for the outfield order), `transfer_in[p,w]`,
  `transfer_out[p,w]`.
- Chip binaries: `use_wc[w]`, `use_fh[w]`, `use_bb[w]`, `use_tc[p,w]`, plus a separate
  `squad_fh[p,w]` used only in a Free Hit week.
- Continuous or integer: `itb[w]` (money in the bank), `fts[w]` (free transfers available, 1–5),
  `penalized_transfers[w]` (hits).

### Constraints (paraphrasing the code)
- **Squad:** `Σ_p squad = 15`; per position `= 2/5/5/3`; per club `≤ 3`.
- **Lineup:** `Σ lineup = 11 + 4·use_bb`; per-position minimum `{1,3,2,1}` and maximum
  `{1,5,5,3} (+use_bb)`; `lineup ≤ squad`.
- **Captain:** `Σ captain = 1`, `captain ≤ lineup`, `captain + vicecap ≤ 1`.
- **Bench:** exactly one bench GK and one player in each bench slot 1–3 (all relaxed when BB is
  played). A player is either in the lineup or on the bench, never both.
- **Squad continuity:** `squad[p,w] = squad[p,w−1] + in[p,w] − out[p,w]`.
- **Budget with selling prices:**
  `itb[w] = itb[w−1] + Σ sell_price[p]·out[p,w] − Σ buy_price[p]·in[p,w]`.
  Selling price applies only to players you already own whose price has changed. Anyone bought
  inside the horizon is sold at the price paid, because future price moves are unknown.
- **Free transfers:**
  `raw[w] = fts[w] − transfers[w] + 1 − use_wc[w] − use_fh[w]`, then
  `fts[w+1] = clamp(raw, 1, 5)`, written with big-M indicator constraints.
  `hits[w] ≥ transfers[w] − fts[w] − 15·use_wc[w]`. Note that after a Wildcard or Free Hit the FT
  count is kept but does not grow (AIrsenal states the same rule).
- **Chips:** at most one chip per GW; no WC or FH immediately after either; a per-season count
  limit (2026/27: one of each per half, first half closes at GW19). A Free Hit squad must also be
  affordable: `Σ price·squad_fh[w] ≤ Σ sell_price·squad[w−1] + itb[w−1]`.

### Objective
```
gw_xp[w] = Σ_p xP[p,w] · (lineup + captain + vcap_w·vicecap + use_tc + Σ_o bench_w[o]·bench[p,w,o])
gw_total[w] = gw_xp[w] − 4·hits[w] + FT_gain[w] + itb_value·itb[w]
maximise  Σ_w decay^(w − next_gw) · gw_total[w]
```

| Parameter | FPL-Optimization-Tools | FPLReview docs | Meaning |
|---|---|---|---|
| `decay_base` | 0.84 code default, 0.9 in `user_settings.json` | 0.85 (0.80–0.95) | Discounts far-off weeks for uncertainty |
| `ft_value` | 1.5; `ft_value_list` {2:2, 3:1.6, 4:1.3, 5:1.1} | 1.75 | Points a banked FT is "worth" |
| `bench_weights` | GK 0.03, S1 0.21, S2 0.06, S3 0.002 | S1 .30, S2 .10, S3 .03, SGK .03 | Chance the bench player's points count (autosubs) |
| `vcap_weight` | 0.1 | 0.05 | Value of a vice-captain |
| `itb_value` | 0.08 per £1m | 0.10 per £1m | Value of cash in the bank |
| `horizon` | 8 | transfer depth 6 | Weeks modelled |
| `no_transfer_last_gws` | 2 | "a couple of GWs short of horizon" | Avoids short-sighted buys at the end of the horizon |

Without `ft_value` and decay the solver behaves badly. It burns every FT on +0.2-point moves, or
plans transfers for week 6 using guesses about week 6 that are poor.

### Solvers (free, pip-installable). Sizes checked on PyPI today, Windows x64, Python 3.14
| Option | Wheel size | Pulls in | Notes |
|---|---|---|---|
| **highspy 1.15** (HiGHS) | 2.8 MB | numpy (~13 MB) | **Recommended.** Used by FPL-Optimization-Tools, fast and open source (MIT) |
| scipy.optimize.milp | scipy 37 MB + numpy | | HiGHS under the hood, matrix-style API (clunky for this model) |
| PuLP 4.0 | 0.5 MB | **no solver bundled any more** | PuLP 4 removed the bundled CBC and `PULP_CBC_CMD`. You need `pulp[cbc]` (cbcbox) or `pulp[highs]` (pins highspy<1.14). Old tutorials break |
| OR-Tools 9.15 | 25 MB | protobuf etc. | CP-SAT/SCIP are fine but heavy for this |

Model size: about 700 players × 6 GWs × about 10 binaries gives about 40k binaries. Pre-filtering
to around 150 players (top xP per position, plus your own squad, plus anyone whose sale would be
forced) makes solves take seconds. FPL-Optimization-Tools does this with `xmin_lb`,
`ev_per_price_cutoff` and `keep_top_ev_percent`.

### Pitfalls
- **The output is only as good as the xP input.** The ILP will exploit every projection error,
  for example by buying a player who is projected high only because of a bad minutes estimate.
- Selling-price asymmetry: you only get half the rise, so price-fall risk and rise "profit" are
  not symmetric (Section 5).
- Deterministic xP ignores variance. Run several solves (different decay or FT values, or
  "exclude top solution") and show the alternatives, as both FPLReview and FOT do.
- Free Hit and Wildcard double the model size. Keep chips off by default and let the user turn
  them on for specific weeks.
- Render free tier: numpy + highspy adds about 16 MB and a little build time. Keep the import
  optional so the stdlib path still works if the dependency is missing.

---

## 4. Mini-league game theory

### In plain English
Against rivals, only the **difference** between your score and theirs matters. If you and your
rival both own Haaland and both captain him, his 20 points move nothing between you.

**Effective ownership (EO)** measures how much of a player's score the "field" (here, your rivals)
gets. Your gain from a player = (your multiplier − field EO) × his points. A leader wants to copy
the field so nothing changes. A chaser needs players the field does *not* have, and the further
behind they are with fewer weeks left, the bigger the risks they should take.

### Formulas
- **EO in a mini-league (per GW):** `EO_p = (1/R) Σ_r mult_{r,p}`, where `mult` is 0 if not
  owned or benched (unless BB), 1 if started, 2 if captain, 3 if triple captain. The vice-captain
  only counts when the captain gets 0 minutes. Global EO (from FPL or other sites) uses the same
  formula over a sample of the top 10k.
- **Expected swing vs the field:** `Δ = Σ_p (your_mult_p − EO_p) · xP_p`. For one rival r, use
  `mult_{r,p}` in place of EO.
- **Captaincy vs a rival:** if you both captain X, the captain choice adds no difference. Choosing
  Y instead changes the expected difference by `xP_Y − xP_X` and **adds variance**
  `≈ Var(X) + Var(Y) − 2Cov`.
- **When to take variance:** treat your season-long margin over a rival as roughly normal. Let the
  current gap be G (positive means you lead) and the remaining expected edge μ. Then
  `P(you finish ahead) ≈ Φ((G + μ)/σ)`. A **leader** (G + μ > 0) wins more often by *reducing* σ:
  copy the rival, same captain. A **chaser** (G + μ < 0) wins more often by *increasing* σ:
  differentials and contrarian captains, and they should even give up a little μ to get a lot of σ.
  σ grows with the weeks left: `σ_total ≈ σ_week · √n`. Estimate `σ_week` from data as the
  standard deviation of the weekly points difference between you and that rival
  (`entry/{id}/history/`, which fpl-brief already fetches). The "z-score" `|G|/(σ_week·√n)` tells
  you how desperate the position is.
- **Rule of thumb from the FPL community (heuristic, not derived):** consider a differential
  captain when the favourite's EO > 75%, the alternative's EO < 50%, and the xP gap < 1.5. When
  protecting a lead, stick with the template captain unless it is behind by more than 2 xP
  (fploracle).

### Monte Carlo (the honest version of the above)
For each of N simulations, draw every player's points once. Use **the same draw** for every
manager who owns that player: shared random numbers cancel out common players. Score every rival,
including their captains and bench rules, and score each of *your* candidate decisions (captain A,
B or C, transfer plan 1 or 2) on the same draws. P(win) = share of simulations where you finish
first. Run it over the remaining season for a title probability, or over one GW to choose a captain.

- Point distributions: the simplest option is Normal(xP, sd) floored at −4 and rounded, as in
  PublicFF. A better option samples components: appearance from the minutes distribution, goals
  and assists from Poisson, clean sheet from Bernoulli(P(CS)), shared within a team so that GK and
  DEF clean sheets are correlated.
- Implementations: `mrcfox-dot/PublicFF` (shows that win-probability choices differ from
  expected-points choices), `AnshX01/fpl-oracle` (title odds, "defend" vs "chase" modes),
  `bkcodes255/fergies-regression` (MILP plus Monte Carlo, backtested).
- Stdlib-only is fine: `random.gauss` and `random.random` for 10k sims × about 10 rivals × 15
  players runs in about a second in pure Python.

### Data (all public; fpl-brief already fetches most of it)
`leagues-classic/{id}/standings/` (rivals), `entry/{id}/event/{gw}/picks/` (their XI, captain,
`active_chip`), `entry/{id}/history/` (weekly points, `chips` used, so you know their remaining
chips). Picks are only visible after the deadline, so before the deadline you must model rivals'
likely captain from their squad, for example "the highest-xP or most-captained owned player".

### Pitfalls
- Before the deadline you see last week's squads. Rivals will transfer.
- Small leagues make EO very lumpy: with 5 rivals, one owner equals 20% EO.
- The normal approximation ignores fat tails, such as a captain haul. Use the Monte Carlo for
  actual decisions.

---

## 5. Price changes and selling prices

### Rules
- Prices move by at most £0.1m per day and £0.3m per gameweek, overnight. The direction depends on
  net transfers relative to a threshold that depends on ownership. The algorithm is not public.
- **Selling price:** if `now > bought`, then `sell = bought + floor((now − bought)/2)` in £0.1m
  units. Otherwise `sell = now`, because falls are passed on in full. A single +0.1 rise earns you
  nothing.
  - Integer code (AIrsenal `squad/pricing.py`): `(now + bought) // 2` if `now > bought`, else
    `now`. This is identical for integer tenths.
  - `game_settings.transfers_sell_on_fee = 0.5`.
- **New in 2026/27:** FPL publishes an **official price-change predictor**. `bootstrap-static`
  elements now include `price_change_percent` (progress to the threshold; >100 means expected to
  change at the next update), `price_change_hourly_rate`, `price_change_projections` (offset 0–2
  with `projected_percent` and a `likelihood` score that is negative for falls),
  `price_change_locked_until` and `price_change_calibrating`. These were checked live today.
  This removes most of the need to reverse-engineer thresholds. Treat it as a guide only, as FPL
  itself says.
- Your actual selling prices come from the logged-in `my-team/{id}/` (which fpl-brief already
  captures as `private.prices`), or can be rebuilt from `entry/{id}/transfers/` purchase prices
  with the formula above.

### How it feeds the maths
- ILP budget: use the real `selling_price` for owned players and `now_cost` for everyone else
  (Section 3).
- **Value of an early move:** a transfer made tonight instead of at the deadline can save £0.1m on
  a riser, or avoid losing £0.1m on a faller. That is worth `itb_value` × 0.1, roughly 0.01 points.
  It is tiny unless it enables a later upgrade. Show it as a note, not as a driver of decisions.

### Pitfalls
- Planning a chain of transfers on the assumption that a price will rise.
- Forgetting that a player you buy now has selling price = purchase price inside the horizon.

---

## 6. Recommended staged build plan for fpl-brief

Each stage ships on its own and is useful by itself. Stages 1, 2 and 4 stay stdlib-only. Stage 3 is
the only one that needs a new dependency.

### Stage 1: multi-week projections from `ep_next` + fixtures (stdlib, smallest useful step)
- **New module `fpl_brief/projection.py`.**
  1. **Fit team ratings.** Fit multiplicative attack and defence ratings (Section 1, iterative fit)
     from the season's finished fixtures. Use `fixtures/` scores, and team xG summed from
     `event/{gw}/live/` (one call per finished GW). Shrink with 6 pseudo-matches of league
     average.
  2. **Build per-fixture multipliers.** For each team and each upcoming fixture, compute
     `att_mult = λ_for / league_avg` and `cs_prob = e^(−λ_against)`.
  3. **Project points per gameweek.** Use `xP[p,w] = ep_base_p × Σ_fixtures(w) mult(p, fixture)`,
     where `ep_base_p = ep_next_p / Σ_fixtures(next) mult(p, fixture)` (de-fixturing FPL's
     estimate). The multiplier is a position-weighted blend: attack-driven for MID/FWD,
     CS-driven for GK/DEF. Simple weights are 0.7/0.3 for FWD and MID and 0.3/0.7 for DEF and GK.
     These are heuristics, so label them and tune them in Stage 2.
  4. **Apply availability and decay.** Players flagged out get 0. Show a 6-GW total and a decayed
     total (decay 0.85).
- **Wire it in:**
  - `candidates.py` gains a "next 6 GWs xP" column and sort.
  - `plan.py` `summary` adds `horizon_delta`, the XI xP difference summed over 6 GWs with decay,
    and changes the method text.
  - `lineup.py` is unchanged: `ep_next` is right for this week's XI.
- Tests: synthetic fixtures where a team faces strong vs weak opponents; DGW sums; BGW gives 0.
- Dependencies: none. Data: `fixtures/`, `event/{gw}/live/`, `bootstrap-static/`.

### Stage 2: own component xP model with shrinkage (stdlib)
- Replace `ep_base` with the bottom-up recipe in Section 1:
  - minutes model (`p_play`, `p_60` from the last N `starts`/`minutes` × `chance_of_playing`);
  - shrunk xG/90 and xA/90 shares (prior = last season `history_past` or position × price band,
    k = 900 min);
  - P(CS) and E[floor(GC/2)] from the team model;
  - defcon hit rate (k = 10 matches, positional prior), bonus and cards (k = 10), GK saves.
- Keep `ep_next` alongside as a cross-check, and flag players where the two disagree by more
  than 2.
- Backtest: replay GWs already played this season and report MAE and rank correlation against
  actual points, compared with `ep_next`. Only switch the default once it wins.
- Dependencies: none. Pure-Python Poisson sums are trivial.

### Stage 3: ILP transfer planner (adds `highspy`, which brings numpy)
- **New module `fpl_brief/optimise.py`** implementing the Section 3 model on a pre-filtered pool
  of about 150 players over a 6-GW horizon.
  - Settings: decay 0.85, FT value 1.5–1.75, hit −4, bench weights GK .03 / S1 .25 / S2 .08 /
    S3 .02, vice-captain 0.05, itb 0.08.
  - FT rollover clamped to 1–5.
  - Real selling prices from `private.prices`; `no_transfer_last_gws = 2`.
- Start with transfers only. Add chips later, one at a time, user-toggled per GW: BB (easy), TC
  (easy), WC, then FH (hardest).
- Return the top 3 plans (re-solve with a "not this exact plan" cut) and explain each one: moves,
  hits, xP gain over the horizon.
- Make the import optional: if highspy is missing, the dashboard shows "planner unavailable" and
  everything else works. Add `highspy>=1.15` to `requirements.txt`, and check the Render build
  size.
- `plan.py` stays as the rule validator for user-entered plans. The optimiser proposes plans and
  `plan.py` checks them.

### Stage 4: rival EO and captaincy (stdlib)
- From the picks of the tracked rivals in the target league (already fetched by `league.py` and
  `matchday.py`):
  - per-player mini-league EO;
  - "your expected swing vs each rival";
  - a captain table showing xP, EO and swing per candidate.
- A one-GW Monte Carlo (shared draws, normal or component sampling) to give
  P(beat rival r) for each captain option. A season Monte Carlo for title odds, using the
  gap / σ√n logic to label each rival "defend" (mirror) or "chase" (differentiate).
- Show rivals' remaining chips from `entry/{id}/history/` `chips`.
- Dependencies: none.

### Stage 5 (small add-on, any time): price awareness
- Show `price_change_percent` and `price_change_projections` likelihood next to transfer
  candidates.
- Use the selling-price formula wherever `private.prices` is missing, labelled as estimated.
- Dependencies: none.

---

## Sources
- sertalpbilal/FPL-Optimization-Tools (solver model, settings): https://github.com/sertalpbilal/FPL-Optimization-Tools (files `dev/solver.py`, `data/user_settings.json`, `data/comprehensive_settings.json`, `pyproject.toml`)
- Sertalp B. Çay, "FPL Optimization with Excel" series (multi-period FT/budget logic): https://x.com/sertalpbilal/status/1363428251314577411
- FPL Review solver settings docs: https://docs.fplreview.com/the-model/solvers/settings/
- AIrsenal (Alan Turing Institute): https://github.com/alan-turing-institute/AIrsenal (files `docs/how-it-works.md`, `docs/xg-models.md`, `src/airsenal/prediction/point_components/empirical_bayes.py`, `def_con.py`, `player_models/conjugate.py`, `squad/pricing.py`)
- AIrsenal write-up: https://www.turing.ac.uk/news/airsenal
- Dixon–Coles with time weighting (dashee87): https://dashee87.github.io/football/python/predicting-football-results-with-statistical-modelling-dixon-coles-and-time-weighting/
- bpl (Bayesian Dixon–Coles used by AIrsenal): https://github.com/anguswilliams91/bpl-next
- OpenFPL paper: https://arxiv.org/abs/2508.09992 and code https://github.com/daniegr/OpenFPL
- Ramezani & Dinh, data-driven FPL team selection (deterministic/robust MILP): https://arxiv.org/abs/2505.02170
- Finishing skill and shrinkage: https://pena.lt/y/2025/10/01/a-better-way-to-measure-finishing-skill/ ; https://arxiv.org/pdf/2401.09940 ; https://thomaswhelan.com/bayes/football/visualisation/2020/11/14/evaluating-penalty-takers-using-empirical-bayes.html
- Effective ownership and captaincy heuristics: https://fploracle.team/blog/effective-ownership-fpl
- Mini-league strategy: https://www.fplcoachme.com/blog/how-to-win-your-fpl-mini-league
- Monte Carlo mini-league projects: https://github.com/mrcfox-dot/PublicFF ; https://github.com/AnshX01/fpl-oracle ; https://github.com/bkcodes255/fergies-regression
- FPL 2025/26 rule changes (defcon, chips): https://www.premierleague.com/en/news/4373187/whats-new-for-202526-changes-in-fantasy-premier-league
- FPL 2026/27 rule changes: https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627 ; chips: https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627
- FPL 2026/27 price change predictor: https://www.premierleague.com/en/news/4680462/whats-new-in-202627-fantasy-price-change-predictor
- Scoring table and price/selling rules summary: https://fplai.app/fpl/2026-27/rules/ ; https://onefpl.com/blog/fpl-team-value-selling-price-explained
- Solver packages: https://pypi.org/project/highspy/ ; https://pypi.org/project/PuLP/ (4.0 notes on CBC removal) ; https://pypi.org/project/ortools/ ; https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html
- Public FPL API (field names verified live 2026-10-05): https://fantasy.premierleague.com/api/bootstrap-static/ , `fixtures/`, `event/{gw}/live/`, `element-summary/{id}/`, `entry/{id}/history/`, `entry/{id}/event/{gw}/picks/`
