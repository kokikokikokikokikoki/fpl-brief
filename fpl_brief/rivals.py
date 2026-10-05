"""Stage 4 rival maths: effective ownership, captaincy against rivals, and finish odds.

In a mini-league only the difference from rivals counts. Everything here is an estimate from
simple models (research/fpl-maths.md §4), not a forecast:

- **EO** per player is the average multiplier across the tracked rivals (0 benched or not owned,
  1 started, 2 captain, 3 triple captain; bench counts 1 under Bench Boost).
- **Expected swing** next GW is Σ (your multiplier − theirs) · xP, per rival and against the field.
- **Captain table** scores each of your top-5 starters as captain against the field and the top-3
  rivals, with a one-GW Monte Carlo on shared draws (each player's points drawn once per sim).
- **Finish odds** come from one season Monte Carlo: each manager's true weekly mean is drawn from its
  shrinkage posterior, past gameweeks are resampled for every manager at once (keeps the week-to-week
  correlation), and a Normal top-up makes each weekly difference with you match the shrunk σ_week.
  The analytic Φ formula with the same variance is kept as a cross-check.

Pure functions; randomness only through a seeded ``random.Random``.
"""

import math
import random

from .private_team import _int as _count

SIMS = 10_000
SEED = 20261005
SEASON_GWS = 38
MEAN_SHRINK_GWS = 5        # pseudo-gameweeks at the league mean added to each manager's weekly mean
SD_SHRINK_GWS = 5          # pseudo-gameweeks at the pooled spread added to each pair's weekly spread
SD_SHRINK_APPEARANCES = 50  # pseudo-appearances at the pooled spread added to each position's spread
DEFAULT_SD = 3.0           # points sd per appearance when no player history exists
FLOOR = -2
CAPTAINS = 5
TOP_RIVALS = 3
SWING_DRIVERS = 5
MODE_Z = 0.5
SHIELD_EO = 0.5
DIFFERENTIAL_EO = 0.25
HEURISTIC = {"favourite_eo": 0.75, "alternative_eo": 0.5, "xp_gap": 1.5}
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
ESTIMATE = "Estimate from a simple model, not a forecast."


def phi(x):
    """Standard normal CDF via math.erf."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def multipliers(picks, chip=None, captain=None):
    """{element: multiplier} for one squad: 0 benched (unless Bench Boost), 1 started, 2 captain, 3 triple captain.

    ``captain`` overrides the picks' own captain (used for the assumed or candidate captain).
    """
    rows = [p for p in picks or [] if isinstance(p, dict) and _count(p.get("element"), 1)]
    if captain is None:
        captain = next((p["element"] for p in rows if p.get("is_captain")), None)
    result = {}
    for pick in rows:
        element, position = pick["element"], pick.get("position")
        started = chip == "bboost" or not isinstance(position, int) or position <= 11
        mult = 1 if started else 0
        if started and element == captain:
            mult = 3 if chip == "3xc" else 2
        result[element] = mult
    return result


def assumed_captain(picks, xp):
    """Before the deadline: the rival's last captain if he is still a starter expected to score, else their highest-xP starter."""
    starters = [p["element"] for p in picks or [] if isinstance(p, dict) and _count(p.get("element"), 1) and (p.get("position") or 0) <= 11]
    last = next((p.get("element") for p in picks or [] if isinstance(p, dict) and p.get("is_captain")), None)
    if last in starters and xp.get(last, 0) > 0:
        return last, "last captain"
    if not starters:
        return None, "no squad"
    return max(starters, key=lambda e: (xp.get(e, 0), -e)), "highest next-GW xP starter"


def effective_ownership(rival_mults):
    """EO per player: the average multiplier across rivals (1.0 = every rival starts him, 2.0 = every rival captains him)."""
    if not rival_mults:
        return {}
    eo = {}
    for mults in rival_mults:
        for element, mult in mults.items():
            eo[element] = eo.get(element, 0) + mult
    return {element: total / len(rival_mults) for element, total in eo.items()}


def swing(mine, theirs, xp):
    """Expected points difference next GW (+ is good for you) and each player's contribution."""
    parts = {}
    for element in set(mine) | set(theirs):
        delta = (mine.get(element, 0) - theirs.get(element, 0)) * xp.get(element, 0.0)
        if abs(delta) > 1e-9:
            parts[element] = delta
    return sum(parts.values()), parts


def position_sd(history, positions, k=SD_SHRINK_APPEARANCES):
    """Points sd per appearance for each position, from this season's player-GW rows, shrunk towards the pooled sd.

    sd²_pos = (n·s²_pos + k·s²_pooled) / (n + k) over rows with minutes > 0.
    """
    fields = (history or {}).get("fields") if isinstance(history, dict) else None
    rows = (history or {}).get("rows") if isinstance(history, dict) else None
    groups = {kind: [] for kind in POSITIONS}
    if isinstance(fields, list) and isinstance(rows, list) and {"id", "minutes", "total_points"} <= set(fields):
        at = {name: fields.index(name) for name in ("id", "minutes", "total_points")}
        for row in rows:
            if not isinstance(row, list) or len(row) != len(fields):
                continue
            minutes, points, kind = row[at["minutes"]], row[at["total_points"]], positions.get(row[at["id"]])
            if isinstance(minutes, (int, float)) and minutes > 0 and isinstance(points, (int, float)) and kind in groups:
                groups[kind].append(points)
    pooled = [value for values in groups.values() for value in values]
    if len(pooled) < 2:
        return {kind: {"sd": DEFAULT_SD, "mean": 3.0, "n": 0} for kind in POSITIONS}

    def stats(values):
        mean = sum(values) / len(values)
        return mean, sum((v - mean) ** 2 for v in values) / (len(values) - 1) if len(values) > 1 else 0.0

    pooled_mean, pooled_var = stats(pooled)
    result = {}
    for kind, values in groups.items():
        n = len(values)
        mean, var = stats(values) if n else (pooled_mean, pooled_var)
        result[kind] = {"sd": round(math.sqrt((n * var + k * pooled_var) / (n + k)), 3), "mean": round((n * mean + k * pooled_mean) / (n + k), 3), "n": n}
    return result


def player_sd(xp, spread):
    """A position's sd scaled down for players unlikely to play: sd · min(1, √(xP / mean points per appearance))."""
    if xp <= 0:
        return 0.0
    return spread["sd"] * min(1.0, math.sqrt(xp / spread["mean"])) if spread["mean"] > 0 else spread["sd"]


def draws(xp, sd, elements, sims=SIMS, seed=SEED):
    """Shared draws: {element: [points per sim]}, each player drawn once per sim from Normal(xP, sd), floored at −2 and rounded."""
    rng = random.Random(seed)
    columns = {}
    for element in sorted(elements):
        mean, spread = xp.get(element, 0.0), sd.get(element, 0.0)
        if spread <= 0:
            columns[element] = [max(FLOOR, round(mean))] * sims
        else:
            columns[element] = [max(FLOOR, round(rng.gauss(mean, spread))) for _ in range(sims)]
    return columns


def scores(mults, columns, sims):
    """Points per sim for one lineup on the shared draws."""
    total = [0] * sims
    for element, mult in mults.items():
        if mult:
            column = columns.get(element)
            if column:
                total = [t + mult * v for t, v in zip(total, column)]
    return total


def _shrunk(value, n, prior, k):
    return (n * value + k * prior) / (n + k)


def _weekly(member):
    """{gameweek: (gross points, hit cost)} from a member's season history."""
    weeks = {}
    for row in member.get("history") or []:
        gw, points, cost = row.get("event"), row.get("points"), row.get("event_transfers_cost") or 0
        if _count(gw, 1) and isinstance(points, (int, float)) and isinstance(cost, (int, float)):
            weeks[gw] = (points, cost)
    return weeks


def manager_form(members, k=MEAN_SHRINK_GWS):
    """Per manager: shrunk weekly mean (gross), average hit cost, mean uncertainty and per-GW net deviation from their own mean.

    σ_m is the sd of the manager's weekly points relative to the tracked group's average that GW (the part of their
    weekly score that moves gaps; the league-wide good or bad week cancels out), shrunk towards the pooled value with
    ``SD_SHRINK_GWS`` pseudo-GWs. The shrunk mean's posterior variance is σ_m² / (n + k).
    """
    weekly = [_weekly(m) for m in members]
    allpoints = [p for weeks in weekly for p, _ in weeks.values()]
    league_mean = sum(allpoints) / len(allpoints) if allpoints else 50.0
    by_gw = {}
    for weeks in weekly:
        for gw, (points, _) in weeks.items():
            by_gw.setdefault(gw, []).append(points)
    gw_mean = {gw: sum(values) / len(values) for gw, values in by_gw.items()}
    residuals = [[p - gw_mean[gw] for gw, (p, _) in weeks.items()] for weeks in weekly]
    variances = []
    for values in residuals:
        if len(values) > 1:
            mean = sum(values) / len(values)
            variances.append((sum((v - mean) ** 2 for v in values) / (len(values) - 1), len(values) - 1))
    pooled_var = sum(v * df for v, df in variances) / sum(df for _, df in variances) if variances else 20.0 ** 2
    form = []
    for weeks, values in zip(weekly, residuals):
        n = len(weeks)
        mean = sum(p for p, _ in weeks.values()) / n if n else league_mean
        hits = sum(c for _, c in weeks.values()) / n if n else 0.0
        df = max(n - 1, 0)
        centre = sum(values) / n if n else 0.0
        var = sum((v - centre) ** 2 for v in values) / df if df else 0.0
        sd = math.sqrt((df * var + SD_SHRINK_GWS * pooled_var) / (df + SD_SHRINK_GWS))
        net_mean = mean - hits
        shrunk = _shrunk(mean, n, league_mean, k)
        form.append({"n": n, "mean": mean, "shrunk": shrunk, "hits": hits, "net": shrunk - hits, "sd": sd, "mean_var": sd ** 2 / (n + k),
                     "deviation": {gw: (p - c) - net_mean for gw, (p, c) in weeks.items()},
                     "net_by_gw": {gw: p - c for gw, (p, c) in weeks.items()}})
    return form, league_mean


def _pair_var(a, b):
    """Sample variance of the weekly net-points difference over shared gameweeks; (variance, degrees of freedom)."""
    common = sorted(set(a["net_by_gw"]) & set(b["net_by_gw"]))
    diffs = [a["net_by_gw"][gw] - b["net_by_gw"][gw] for gw in common]
    if len(diffs) < 2:
        return None, 0
    mean = sum(diffs) / len(diffs)
    return sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1), len(diffs) - 1


def finish_odds(gap, edge_per_week, sigma_week, remaining, mean_var=0.0):
    """P(finish ahead) ≈ Φ((G + μ)/σ_total), μ = edge per week × n, σ_total² = n·σ_week² + n²·(mean-uncertainty variance).

    ``mean_var`` is the sum of both managers' posterior variances of their weekly means. Returns (probability, z).
    """
    mu = edge_per_week * remaining
    total_var = remaining * sigma_week ** 2 + remaining ** 2 * mean_var if remaining > 0 else 0.0
    if total_var <= 0:
        lead = gap + mu
        return (1.0 if lead > 0 else 0.0 if lead < 0 else 0.5), (math.inf if lead > 0 else -math.inf if lead < 0 else 0.0)
    z = (gap + mu) / math.sqrt(total_var)
    return phi(z), z


def pairwise(members, form, remaining, k=SD_SHRINK_GWS):
    """Per rival: gap, expected edge, shrunk weekly sd of the difference and the analytic P(you finish ahead).

    Returns (rows, pooled pair sd, unrounded σ_week per rival).
    """
    you = form[0]
    pairs = [_pair_var(you, f) for f in form[1:]]
    usable = [(v, df) for v, df in pairs if v is not None]
    pooled = sum(v * df for v, df in usable) / sum(df for _, df in usable) if usable else 20.0 ** 2
    rows, sigmas = [], []
    for member, f, (var, df) in zip(members[1:], form[1:], pairs):
        sigma = math.sqrt((df * (var or 0.0) + k * pooled) / (df + k))
        gap = _total(members[0]) - _total(member)
        edge = you["net"] - f["net"]
        probability, z = finish_odds(gap, edge, sigma, remaining, you["mean_var"] + f["mean_var"])
        sigmas.append(sigma)
        rows.append({"entry_id": member["entry_id"], "gap": gap, "edge_per_week": round(edge, 2), "edge": round(edge * remaining, 1),
                     "sigma_week": round(sigma, 2), "z": round(z, 3) if math.isfinite(z) else z, "p_ahead_analytic": round(probability, 4)})
    return rows, math.sqrt(pooled), sigmas


def _total(member):
    total = member.get("total")
    return total if isinstance(total, (int, float)) else 0


def top_ups(form, sigmas):
    """Per-manager weekly Normal top-up sd so each (you, rival) weekly difference sd matches the shrunk σ_week.

    b²_r = mean over past GWs of (dev_you − dev_r)² is the spread the GW resampling already gives;
    need_r = max(0, σ_week,r² − b²_r). You get t_you² = ½·min_r need_r and each rival t_r² = need_r − t_you², so
    t_you² + t_r² = need_r for every pair with you (no top-up where the bootstrap already exceeds σ_week).
    """
    gameweeks = sorted({gw for f in form for gw in f["deviation"]})
    needs = []
    for f, sigma in zip(form[1:], sigmas):
        boot = sum((form[0]["deviation"].get(gw, 0.0) - f["deviation"].get(gw, 0.0)) ** 2 for gw in gameweeks) / len(gameweeks) if gameweeks else 0.0
        needs.append(max(0.0, sigma ** 2 - boot))
    mine = min(needs) / 2 if needs else 0.0
    return [math.sqrt(mine)] + [math.sqrt(need - mine) for need in needs]


def season_sims(members, form, sigmas, remaining, sims=SIMS, seed=SEED):
    """Season Monte Carlo, consistent with the pairwise formula.

    Per sim, each manager's true weekly mean is drawn once from Normal(shrunk mean, σ_m/√(n + k)); each remaining week
    resamples one past GW for everyone at once (their net deviation from their own mean keeps the weekly correlation),
    plus an independent Normal top-up per manager (``top_ups``). The n weekly top-ups are summed as one
    Normal(0, t·√n) draw. Returns (P(1st) per manager, your expected rank, P(you finish ahead) per rival, top-up sds).
    Ties share the place.
    """
    rng = random.Random(seed)
    gameweeks = sorted({gw for f in form for gw in f["deviation"]})
    extra = top_ups(form, sigmas)
    count = len(members)
    wins, ahead = [0.0] * count, [0.0] * count
    rank_sum = 0.0
    root = math.sqrt(remaining)
    for _ in range(sims):
        counts = {}
        if gameweeks:
            for _ in range(remaining):
                gw = gameweeks[rng.randrange(len(gameweeks))]
                counts[gw] = counts.get(gw, 0) + 1
        final = []
        for member, f, t in zip(members, form, extra):
            mean = rng.gauss(f["shrunk"], math.sqrt(f["mean_var"])) if f["mean_var"] > 0 else f["shrunk"]
            noise = rng.gauss(0.0, t * root) if t > 0 and remaining else 0.0
            final.append(_total(member) + remaining * (mean - f["hits"]) + sum(c * f["deviation"].get(gw, 0.0) for gw, c in counts.items()) + noise)
        best = max(final)
        leaders = [i for i, v in enumerate(final) if v == best]
        for i in leaders:
            wins[i] += 1 / len(leaders)
        mine = final[0]
        for i in range(1, count):
            ahead[i] += 1.0 if mine > final[i] else 0.5 if mine == final[i] else 0.0
        rank_sum += 1 + sum(v > mine for v in final) + 0.5 * (sum(v == mine for v in final) - 1)
    return [w / sims for w in wins], rank_sum / sims, [a / sims for a in ahead[1:]], extra


def _name(players, element):
    info = players.get(element) or {}
    return info.get("web_name") or info.get("name") or f"#{element}"


def build(snapshot, catalog, gathered, private=None, history=None, sims=SIMS, seed=SEED, projections=None):
    """Rival maths for the Rivals view. ``gathered`` is ``league.gather`` (the League threats fetch)."""
    if not isinstance(gathered, dict) or gathered.get("state") != "ready":
        return gathered if isinstance(gathered, dict) and gathered.get("reason") else {"state": "unavailable", "reason": "League data isn't available right now."}
    members = gathered.get("members") or []
    if len(members) < 2:
        return {"state": "unavailable", "reason": "No rivals could be loaded from your mini-league."}
    from . import projection  # local import keeps this module light for tests that pass projections
    caveats = []
    projected = projections
    if projected is None:
        projected = projection.build(snapshot, catalog, model="own", history=history)
        if not projected.get("available"):
            caveats.extend(projected.get("caveats") or [])
            caveats.append("Our model has no player history, so FPL's own estimate (ep_next) is used instead.")
            projected = projection.build(snapshot, catalog, model="fpl")
    players = {p["id"]: p for p in (catalog or {}).get("players", []) if isinstance(p, dict) and isinstance(p.get("id"), int)}
    teams = {t.get("id"): t.get("short_name") for t in (catalog or {}).get("teams", []) if isinstance(t, dict)}
    rows = projected.get("players") or {}
    xp = {pid: float((row.get("xp") or [0.0])[0]) for pid, row in rows.items()}
    xp6 = {pid: float(row.get("xp_6") or 0.0) for pid, row in rows.items()}
    target = (projected.get("gameweeks") or [None])[0]
    remaining = max(0, SEASON_GWS - (gathered["gameweek"] if gathered.get("finished") else gathered["gameweek"] - 1))

    # Your lineup: the captured account lineup (it reflects changes not yet public), else the public snapshot.
    you = members[0]
    account = private if isinstance(private, dict) and private.get("usable") is True and private.get("lineup") else None
    my_picks = (account or {}).get("lineup") or ((snapshot or {}).get("squad_snapshot") or {}).get("picks") or you.get("picks") or []
    pending = next((c.get("name") for c in (account or {}).get("chips") or [] if c.get("pending")), None)
    my_chip = pending if pending in ("bboost", "3xc") else None
    mine = multipliers(my_picks, my_chip)
    lineup_source = "your captured FPL account lineup" if account else "your public squad from the last snapshot"

    rivals = members[1:]
    assumed, rival_mults = [], []
    for rival in rivals:
        captain, why = assumed_captain(rival.get("picks"), xp)
        assumed.append({"element": captain, "why": why})
        rival_mults.append(multipliers(rival.get("picks"), None, captain))
        if rival.get("active_chip") == "freehit":
            caveats.append(f"{rival.get('name')} played Free Hit in GW{gathered['gameweek']}, so their real squad reverts; their swing uses the Free Hit squad.")
    eo = effective_ownership(rival_mults)

    def player_row(element, extra=None):
        info = players.get(element) or {}
        return {"id": element, "name": _name(players, element), "team": teams.get(info.get("team")), "position": POSITIONS.get(info.get("element_type")),
                "xp": round(xp.get(element, 0.0), 2), "xp_6": round(xp6.get(element, 0.0), 2), "eo": round(eo.get(element, 0.0), 3)} | (extra or {})

    def drivers(parts):
        ordered = sorted(parts.items(), key=lambda item: (-item[1], item[0]))
        return {"for_you": [player_row(e, {"points": round(v, 2)}) for e, v in ordered if v > 0][:SWING_DRIVERS],
                "against_you": [player_row(e, {"points": round(v, 2)}) for e, v in reversed(ordered) if v < 0][:SWING_DRIVERS]}

    field_total, field_parts = swing(mine, eo, xp)
    form, league_mean = manager_form(members)
    pairs, pooled_sd, sigmas = pairwise(members, form, remaining)
    p_first, expected_rank, p_ahead, top_up = season_sims(members, form, sigmas, remaining, sims, seed)

    rival_rows = []
    for index, (rival, mults, pair) in enumerate(zip(rivals, rival_mults, pairs)):
        total, parts = swing(mine, mults, xp)
        captain = assumed[index]["element"]
        rival_rows.append({"entry_id": rival["entry_id"], "name": rival.get("name"), "manager": rival.get("manager"), "rank": rival.get("rank"),
                           "total": rival.get("total"), "gap": pair["gap"], "p_ahead": round(p_ahead[index], 4), "p_ahead_analytic": pair["p_ahead_analytic"], "z": pair["z"],
                           "edge": pair["edge"], "sigma_week": pair["sigma_week"], "p_first": round(p_first[index + 1], 4),
                           "swing": round(total, 2), "drivers": drivers(parts),
                           "assumed_captain": {"id": captain, "name": _name(players, captain) if captain else None, "why": assumed[index]["why"]},
                           "chips_left": rival.get("chips_left") or [], "shared": len(set(mine) & set(mults))})

    # Captain table: your top-5 starters by next-GW xP, scored against the field and the top-3 rivals on shared draws.
    starters = [e for e, m in mine.items() if m > 0]
    candidates = sorted(starters, key=lambda e: (-xp.get(e, 0.0), e))[:CAPTAINS]
    top = sorted(range(len(rivals)), key=lambda i: (rivals[i].get("rank") if isinstance(rivals[i].get("rank"), int) else 10**9, i))[:TOP_RIVALS]
    base_mine = {e: (1 if m > 0 else 0) for e, m in mine.items()}
    cap_mult = 3 if my_chip == "3xc" else 2
    positions = {pid: p.get("element_type") for pid, p in players.items()}
    spread = position_sd(history, positions)
    involved = set(base_mine) | {e for mults in rival_mults for e in mults}
    sd = {e: player_sd(xp.get(e, 0.0), spread.get(positions.get(e), {"sd": DEFAULT_SD, "mean": 3.0})) for e in involved}
    columns = draws(xp, sd, involved, sims, seed)
    base_scores = {i: scores(base_mine, columns, sims) for i in top}
    rival_scores = {i: scores(rival_mults[i], columns, sims) for i in top}
    # The field's captaincy outcome: rivals' extra captain points summed (compared with yours × R, so ties stay exact integers).
    field_captain = [0] * sims
    for mults in rival_mults:
        for element, mult in mults.items():
            if mult > 1:
                field_captain = [f + (mult - 1) * v for f, v in zip(field_captain, columns[element])]
    rival_count = len(rival_mults)
    table = []
    for candidate in candidates:
        mults = dict(mine)
        for element in mults:
            mults[element] = base_mine[element]
        mults[candidate] = cap_mult
        extra = [(cap_mult - 1) * v for v in columns[candidate]]
        beats = sum(1.0 if e * rival_count > f else 0.5 if e * rival_count == f else 0.0 for e, f in zip(extra, field_captain)) / sims
        versus = []
        for i in top:
            diff = [b + x - r for b, x, r in zip(base_scores[i], extra, rival_scores[i])]
            versus.append({"entry_id": rivals[i]["entry_id"], "name": rivals[i].get("name"), "expected": round(swing(mults, rival_mults[i], xp)[0], 2),
                           "p_gain": round(sum(d >= 0 for d in diff) / sims, 4)})
        table.append(player_row(candidate, {"vs_field": round(swing(mults, eo, xp)[0], 2), "p_beats_field": round(beats, 4),
                                            "rivals": versus, "current": mine.get(candidate, 0) > 1}))
    favourite = max(table, key=lambda r: (r["eo"], r["xp"]), default=None)
    for row in table:
        row["differential_flag"] = bool(favourite and row is not favourite and favourite["eo"] > HEURISTIC["favourite_eo"]
                                        and row["eo"] < HEURISTIC["alternative_eo"] and favourite["xp"] - row["xp"] < HEURISTIC["xp_gap"])

    # Mode hint against the leader (or, if you lead, against second place).
    leader_index = min(range(len(rivals)), key=lambda i: (rivals[i].get("rank") if isinstance(rivals[i].get("rank"), int) else 10**9, i))
    pair = pairs[leader_index]
    z = pair["z"]
    leading = pair["gap"] > 0 or (pair["gap"] == 0 and (you.get("rank") or 10**9) < (rivals[leader_index].get("rank") or 10**9))
    if z > MODE_Z:
        mode, text = "protect", ("You're ahead on the numbers. Protect it: copy the field's big picks and captain the template choice; "
                                 "only switch captain if the template is more than about 2 xP behind.")
    elif z < -MODE_Z:
        mode, text = "chase", ("You're behind on the numbers. Chase: you need points they don't get, so back differentials, and a contrarian captain "
                               "is worth considering even at a small xP cost.")
    else:
        mode, text = "balanced", "It's close. Pick on expected points; don't take on or shed risk for its own sake."
    mode_hint = {"mode": mode, "z": z if math.isfinite(z) else (99 if z > 0 else -99), "against": rivals[leader_index].get("name"),
                 "you_lead": leading, "gap": pair["gap"], "edge": pair["edge"], "sigma_week": pair["sigma_week"], "remaining": remaining, "text": text}

    owned = sorted(base_mine, key=lambda e: (-xp.get(e, 0.0), e))
    shield = [player_row(e, {"mult": mine[e]}) for e in owned if eo.get(e, 0.0) >= SHIELD_EO]
    differentials = [player_row(e, {"mult": mine[e]}) for e in owned if eo.get(e, 0.0) < DIFFERENTIAL_EO]
    return {
        "state": "ready", "gameweek": gathered["gameweek"], "target_gameweek": target, "remaining": remaining,
        "model": projected.get("model"), "lineup_source": lineup_source, "sims": sims, "rivals_compared": len(rivals),
        "you": {"name": you.get("name"), "rank": you.get("rank"), "total": you.get("total"), "p_first": round(p_first[0], 4),
                "expected_rank": round(expected_rank, 2)},
        "mode": mode_hint, "field_swing": {"swing": round(field_total, 2), "drivers": drivers(field_parts)},
        "rivals": rival_rows, "captains": table, "shield": shield, "differentials": differentials,
        "spread": {POSITIONS[k]: v for k, v in spread.items()}, "league_mean": round(league_mean, 2), "pooled_sd": round(pooled_sd, 2),
        "top_up_sd": [round(t, 2) for t in top_up],
        "warnings": list(gathered.get("warnings") or []), "caveats": caveats,
        "assumptions": [f"Rivals' GW{target} teams are their GW{gathered['gameweek']} picks (FPL hides picks until the deadline); they will transfer.",
                        "A rival's captain is assumed to be their last captain if he still starts and is expected to score, otherwise their highest-xP starter.",
                        "No chips are assumed for rivals next GW."],
        "method": (f"{ESTIMATE} EO is each player's average multiplier across the top {len(rivals)} rivals (captain 2, triple captain 3, bench 0). "
                   f"Swing = Σ (your multiplier − theirs) × next-GW xP from {'our model' if projected.get('model') == 'own' else 'FPL ep_next'}. "
                   f"Captain odds: {sims:,} simulated gameweeks, each player's points drawn once per sim from Normal(xP, sd) floored at −2 and rounded; "
                   f"sd per position comes from this season's per-appearance points spread, shrunk towards the pooled spread "
                   f"({SD_SHRINK_APPEARANCES} pseudo-appearances), and scaled down for players unlikely to play. "
                   f"The captain's \"vs field\" compares captain points only, because the rest of your squad doesn't change with the captain. "
                   f"Finish and title odds: {sims:,} simulated seasons among you and these {len(rivals)} rivals only. Each manager's true weekly mean is "
                   f"drawn from their mean shrunk to the league mean ({MEAN_SHRINK_GWS} pseudo-GWs) with its uncertainty; each remaining week reuses one "
                   f"past gameweek for everyone at once, plus random noise sized so each weekly gap with you has the spread σ_week "
                   f"(shrunk to the pooled value, {SD_SHRINK_GWS} pseudo-GWs). Cross-check: Φ((gap + edge)/√(n·σ_week² + n²·mean uncertainty)). "
                   f"The noise is sized only against you, so rivals' own title odds are calibrated only against you, not against each other. "
                   f"The vice-captain isn't modelled, because the draws never model a captain playing 0 minutes. "
                   f"Approximation: ignores chips left and transfer plans."),
    }
