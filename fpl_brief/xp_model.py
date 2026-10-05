"""Stage 2 expected points: our own component model, built bottom-up from this season's data.

Per player and fixture (research/fpl-maths.md §1 "Putting it together", 2026/27 scoring in §0):
appearance from a recent-minutes model, goals/assists from shrunk xG/90 and xA/90 scaled by the
Stage 1 fixture attack multiplier, clean sheets and goals conceded from the Stage 1 team model,
and saves, defensive contributions, bonus and cards from shrunk per-90 rates. Every number here
is an estimate, not a forecast. Pure functions; stdlib only.
"""

import math
import re
from datetime import datetime

from . import projection
from .collect import HISTORY_FIELDS

# Defaults from AIrsenal and research/fpl-maths.md §2. All are tunable estimates, not fitted values.
RECENT_MATCHES = 4            # minutes model: the player's last N club gameweeks
MINUTES_DECAY = 0.8           # weight per gameweek further back inside that window (heuristic)
ATTACK_PRIOR_MINUTES = 900    # k for xG/90 and xA/90: 10 full matches at the prior rate (§2)
SIDE_PRIOR_MATCHES = 10       # k for defcon, bonus, cards and saves (AIrsenal n_prior=10)
PRICE_BANDS = (50, 65, 85)    # now_cost (tenths of £m) edges of the price bands for the attacking prior
MIN_BAND_MINUTES = 900        # a price band with less pooled exposure falls back to the position prior
UNKNOWN_RETURN_WEEKS = 2      # injured/suspended with no return date in the news: back from next GW + 2
DOUBT_STATUSES = ("a", "d")
OUT_STATUSES = ("i", "s")     # may return within the horizon
GONE_STATUSES = ("u", "n")    # left the club / not eligible: 0 for the whole horizon

# 2026/27 scoring (research §0).
GOAL_POINTS = {1: 10, 2: 6, 3: 5, 4: 4}
ASSIST_POINTS = 3
CLEAN_SHEET_POINTS = {1: 4, 2: 4, 3: 1, 4: 0}
CONCEDED_POSITIONS = (1, 2)   # −1 per 2 goals conceded
SAVES_PER_POINT = 3
BREAKDOWN_KEYS = ("appearance", "goals", "assists", "clean_sheet", "conceded", "saves", "defcon", "bonus", "cards")
MONTHS = {name: index for index, name in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
RETURN_PATTERN = re.compile(r"\b(?:back|until|return(?:s|ing)?(?: on)?)\s+(\d{1,2})\s+([A-Za-z]{3})", re.IGNORECASE)


def history_rows(doc):
    """Dict rows from data/player_history.json (columnar) or an already-expanded list of dicts."""
    if isinstance(doc, list):
        return [row for row in doc if isinstance(row, dict)]
    if not isinstance(doc, dict):
        return []
    fields = list(doc.get("fields") or HISTORY_FIELDS)
    return [dict(zip(fields, row)) for row in doc.get("rows") or [] if isinstance(row, list) and len(row) == len(fields)]


def shrink(events, exposure, prior, k):
    """(events + k·prior) / (exposure + k): the player's rate pulled towards the prior."""
    return (events + k * prior) / (exposure + k)


def expected_half_goals(lam, shape=None):
    """E[floor(GC/2)] for GC ~ Poisson(lam), or negative binomial with Gamma ``shape`` (the same rating
    uncertainty as the clean-sheet chance in ``projection.fixture_view``), by direct summation."""
    if lam <= 0:
        return 0.0
    total, prob = 0.0, projection.zero_chance(lam, shape)
    for goals in range(60):
        total += (goals // 2) * prob
        prob *= lam / (goals + 1) if not shape else (goals + shape) / (goals + 1) * lam / (shape + lam)
    return total


def price_band(cost):
    cost = cost if isinstance(cost, (int, float)) else 0
    return sum(cost >= edge for edge in PRICE_BANDS)


def _num(row, key):
    value = row.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def fit(rows, players, results=None, before_gw=None):
    """Season aggregates, priors and club gameweeks from history rows in gameweeks < ``before_gw``."""
    by_id = {player["id"]: player for player in players if isinstance(player, dict) and isinstance(player.get("id"), int)}
    rows = [row for row in rows if isinstance(row.get("gw"), int) and (before_gw is None or row["gw"] < before_gw)]
    stats, pools = {}, {}
    for row in rows:
        player = by_id.get(row.get("id"))
        if not player:
            continue
        kind = player.get("element_type")
        matches = max(int(_num(row, "fixtures")), 1)
        save_points = math.floor(_num(row, "saves") / matches / SAVES_PER_POINT) * matches
        values = {"exposure": _num(row, "minutes") / 90, "xg": _num(row, "xg"), "xa": _num(row, "xa"),
                  "defcon": _num(row, "defcon_points"), "bonus": _num(row, "bonus"),
                  "cards": -_num(row, "yellow") - 3 * _num(row, "red"), "saves": save_points}
        own = stats.setdefault(row["id"], {"gws": {}, **{key: 0.0 for key in values}})
        own["gws"][row["gw"]] = _num(row, "minutes") / matches
        for key, value in values.items():
            own[key] += value
        for group in ((kind,), (kind, price_band(player.get("now_cost")))):
            pool = pools.setdefault(group, {key: 0.0 for key in values})
            for key, value in values.items():
                pool[key] += value
    priors = {}
    for group, pool in pools.items():
        if len(group) == 2 and pool["exposure"] * 90 < MIN_BAND_MINUTES:
            continue
        priors[group] = {key: (pool[key] / pool["exposure"] if pool["exposure"] else 0.0) for key in pool if key != "exposure"}
    club_gws = {}
    source = [row for row in results or [] if isinstance(row, dict)] if results is not None else []
    for row in source:
        if isinstance(row.get("gw"), int) and (before_gw is None or row["gw"] < before_gw):
            for side in ("home", "away"):
                club_gws.setdefault(row.get(side), set()).add(row["gw"])
    if results is None:
        for row in rows:
            club_gws.setdefault(row.get("team"), set()).add(row["gw"])
    return {"players": stats, "priors": priors, "club_gws": club_gws}


def rates(fitted, player):
    """Shrunk per-90 rates for one player (xG and xA towards position × price band; the rest towards position)."""
    kind = player.get("element_type")
    own = fitted["players"].get(player.get("id")) or {}
    exposure = own.get("exposure", 0.0)
    position = fitted["priors"].get((kind,)) or {}
    band = fitted["priors"].get((kind, price_band(player.get("now_cost")))) or position
    attack_k, side_k = ATTACK_PRIOR_MINUTES / 90, SIDE_PRIOR_MATCHES
    result = {key: shrink(own.get(key, 0.0), exposure, band.get(key, 0.0), attack_k) for key in ("xg", "xa")}
    result.update({key: shrink(own.get(key, 0.0), exposure, position.get(key, 0.0), side_k) for key in ("defcon", "bonus", "cards", "saves")})
    if kind != 1:
        result["saves"] = 0.0
    return result


def minutes_profile(fitted, player, skip_absence=False):
    """p_play, p_60 and expected minutes per match from the last RECENT_MATCHES club gameweeks, time-weighted.

    With ``skip_absence`` (a player FPL lists injured or suspended), the current run of missed
    gameweeks is ignored so his rate on return reflects the matches he was fit for.
    """
    own = (fitted["players"].get(player.get("id")) or {}).get("gws", {})
    gameweeks = sorted(set(fitted["club_gws"].get(player.get("team"), set())) | set(own))
    if skip_absence:
        while gameweeks and gameweeks[-1] not in own:
            gameweeks.pop()
    window = gameweeks[-RECENT_MATCHES:]
    if not window:
        return {"p_play": 0.0, "p_60": 0.0, "minutes": 0.0, "matches": 0}
    weights = [MINUTES_DECAY ** age for age in range(len(window) - 1, -1, -1)]
    minutes = [own.get(gw, 0.0) for gw in window]
    total = sum(weights)
    return {"p_play": sum(w for w, m in zip(weights, minutes) if m > 0) / total,
            "p_60": sum(w for w, m in zip(weights, minutes) if m >= 60) / total,
            "minutes": sum(w * m for w, m in zip(weights, minutes)) / total, "matches": len(window)}


def fixture_points(kind, profile, rate, view):
    """Breakdown of expected points for one fixture (before any availability scaling)."""
    share = profile["minutes"] / 90
    return {
        "appearance": profile["p_play"] + profile["p_60"],
        "goals": GOAL_POINTS.get(kind, 0) * rate["xg"] * share * view["att_mult"],
        "assists": ASSIST_POINTS * rate["xa"] * share * view["att_mult"],
        "clean_sheet": CLEAN_SHEET_POINTS.get(kind, 0) * profile["p_60"] * view["cs_prob"],
        "conceded": -share * expected_half_goals(view["lambda_against"], view.get("cs_shape")) if kind in CONCEDED_POSITIONS else 0.0,
        "saves": rate["saves"] * share,
        "defcon": rate["defcon"] * share,
        "bonus": rate["bonus"] * share,
        "cards": rate["cards"] * share,
    }


def gameweek_dates(snapshot):
    """{gw: first kickoff date} from the snapshot's fixture horizon."""
    dates = {}
    for key, rows in (((snapshot or {}).get("fixtures") or {}).get("events") or {}).items():
        for fixture in rows if isinstance(rows, list) else []:
            try:
                kickoff = datetime.fromisoformat(str(fixture.get("kickoff_time")).replace("Z", "+00:00")).date()
            except (AttributeError, TypeError, ValueError):
                continue
            gw = int(key)
            dates[gw] = min(dates.get(gw, kickoff), kickoff)
    return dates


def return_gameweek(player, next_gw, dates):
    """First gameweek an injured/suspended player is assumed back, and whether the news said so."""
    fallback = next_gw + UNKNOWN_RETURN_WEEKS
    match = RETURN_PATTERN.search(player.get("news") or "")
    month = MONTHS.get(match.group(2).lower()) if match else None
    if not month or not dates:
        return fallback, False
    reference = min(dates.values())
    try:
        back = reference.replace(month=month, day=int(match.group(1)))
        if (reference - back).days > 180:
            back = back.replace(year=back.year + 1)
    except ValueError:
        return fallback, False
    later = [gw for gw, day in sorted(dates.items()) if day >= back]
    return max(later[0] if later else max(dates) + 1, next_gw + 1), True


def availability(player, gameweeks, next_gw, dates):
    """Per-gameweek availability factor and flags. Only the next gameweek takes FPL's chance of playing."""
    status, chance = player.get("status"), player.get("chance_of_playing_next_round")
    if status in GONE_STATUSES:
        return [0.0 for _ in gameweeks], ["FPL lists unavailable: projects 0"]
    if status in OUT_STATUSES:
        back, known = return_gameweek(player, next_gw, dates)
        source = "from FPL news" if known else f"assumed, no date in FPL news (next GW + {UNKNOWN_RETURN_WEEKS})"
        return [1.0 if gw >= back else 0.0 for gw in gameweeks], [f"{'Injured' if status == 'i' else 'Suspended'}: back from GW{back} ({source})"]
    if isinstance(chance, int) and not isinstance(chance, bool) and 0 <= chance < 100:
        return [chance / 100 if gw == next_gw else 1.0 for gw in gameweeks], [f"Doubt: {chance}% applied to GW{next_gw} only"]
    return [1.0 for _ in gameweeks], []


def project_player(fitted, player, fixtures, gameweeks, ratings, next_gw, dates=None):
    """Per-gameweek totals and breakdowns over the horizon. Double gameweeks sum, blanks are 0."""
    kind, team = player.get("element_type"), player.get("team")
    factors, flags = availability(player, gameweeks, next_gw, dates or {})
    profile = minutes_profile(fitted, player, skip_absence=player.get("status") in OUT_STATUSES)
    if not profile["p_play"]:
        flags.append("No recent minutes: projects 0")
    rate = rates(fitted, player)
    weekly, breakdowns = [], []
    for gw, factor in zip(gameweeks, factors):
        parts = {key: 0.0 for key in BREAKDOWN_KEYS}
        for opponent, is_home in fixtures.get(gw, {}).get(team, []):
            for key, value in fixture_points(kind, profile, rate, projection.fixture_view(ratings, team, opponent, is_home)).items():
                parts[key] += value * factor
        breakdowns.append({key: round(value, 2) for key, value in parts.items()})
        weekly.append(round(sum(parts.values()), 2))
    total = {key: round(sum(week[key] for week in breakdowns), 2) for key in BREAKDOWN_KEYS}
    return {"gameweeks": list(gameweeks), "xp": weekly, "xp_6": round(sum(weekly), 2),
            "xp_6_decayed": round(sum(value * projection.DECAY ** index for index, value in enumerate(weekly)), 2),
            "breakdown": breakdowns, "breakdown_total": total, "minutes": {key: round(value, 2) for key, value in profile.items()},
            "flags": flags}


def project_all(snapshot, players, history, ratings, gameweeks, fixtures):
    """Project every catalog player with our model; returns ({id: projection}, caveats)."""
    rows = history_rows(history)
    results = (snapshot or {}).get("team_results")
    fitted = fit(rows, players, results if isinstance(results, list) else None)
    next_id = (((snapshot or {}).get("events") or {}).get("next") or {}).get("id")
    next_gw = next_id if isinstance(next_id, int) else (gameweeks[0] if gameweeks else 1)
    dates = gameweek_dates(snapshot)
    caveats = [] if rows else ["No player history yet (data/player_history.json): our model projects 0 for everyone. Refresh FPL data."]
    return {player["id"]: project_player(fitted, player, fixtures, gameweeks, ratings, next_gw, dates) for player in players}, caveats


METHOD = (f"Estimate, not a forecast: our own model built from this season's data. Minutes from the last {RECENT_MATCHES} "
          f"club gameweeks (recent weighted more); FPL's chance of playing applies to the next GW only, and injured or suspended "
          f"players return from the GW their FPL news implies (else next GW + {UNKNOWN_RETURN_WEEKS}). Goals and assists from xG/90 and "
          f"xA/90 shrunk towards the position and price-band average ({ATTACK_PRIOR_MINUTES} minutes of prior), scaled by fixture. "
          f"Clean sheets and goals conceded from the team model (league level from actual goals, allowing for rating uncertainty). Saves, defensive contributions, bonus and cards are per-90 rates "
          f"shrunk with {SIDE_PRIOR_MATCHES} matches of the position average. Decayed totals weight week k by {projection.DECAY}^k.")
