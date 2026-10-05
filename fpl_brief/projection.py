"""Stage 1 multi-gameweek projections: FPL's ``ep_next`` re-weighted by a fixture model.

Team attack/defence ratings are fitted from this season's results (xG where known, goals
otherwise), shrunk towards league average. Each player's ``ep_next`` is divided by his
next-gameweek fixture multiplier to remove that fixture's difficulty, then multiplied by
the multiplier of each later fixture. Everything here is an estimate, not a forecast.
"""

import math
from itertools import product

PRIOR_MATCHES = 6          # pseudo-matches at league average added to every club (shrinkage)
ITERATIONS = 50
HORIZON = 6
DECAY = 0.85               # weight per week after the next gameweek
DEFAULT_GOALS = 1.4        # goals per club per match when no results exist (ratings are then all 1.0)
# Heuristic share of the multiplier driven by attack; the rest is driven by clean-sheet chance.
ATTACK_WEIGHT = {1: 0.3, 2: 0.3, 3: 0.7, 4: 0.7}
AVAILABLE_STATUS = ("a", "d")
FORMATION_LIMITS = {1: (1,), 2: range(3, 6), 3: range(2, 6), 4: range(1, 4)}


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _matches(results):
    """(home, away, home_value, away_value) per result; xG per side when present, else goals."""
    rows = []
    for row in results or []:
        if not isinstance(row, dict):
            continue
        home, away = row.get("home"), row.get("away")
        values = []
        for xg, goals in (("home_xg", "home_goals"), ("away_xg", "away_goals")):
            value = _number(row.get(xg))
            values.append(value if value is not None and value >= 0 else _number(row.get(goals)))
        if home is None or away is None or home == away or any(value is None or value < 0 for value in values):
            continue
        rows.append((home, away, values[0], values[1]))
    return sorted(rows, key=lambda row: (str(row[0]), str(row[1]), row[2], row[3]))


def team_ratings(results, team_ids=()):
    """Fit multiplicative attack/defence ratings and a home factor. Empty input gives all 1.0.

    λ_home = base · A_home · D_away · H and λ_away = base · A_away · D_home / H, where D > 1 is
    a leakier defence. Each club gets PRIOR_MATCHES pseudo-matches at league average.
    """
    matches = _matches(results)
    teams = sorted(set(team_ids) | {team for row in matches for team in row[:2]}, key=str)
    attack, defence, home = {team: 1.0 for team in teams}, {team: 1.0 for team in teams}, 1.0
    if not matches:
        return {"attack": attack, "defence": defence, "home": 1.0, "base": DEFAULT_GOALS, "matches": 0}
    base = sum(row[2] + row[3] for row in matches) / (2 * len(matches))
    if base <= 0:
        return {"attack": attack, "defence": defence, "home": 1.0, "base": DEFAULT_GOALS, "matches": len(matches)}
    prior = PRIOR_MATCHES * base
    for _ in range(ITERATIONS):
        scored, expected = {team: prior for team in teams}, {team: prior for team in teams}
        for h, a, gh, ga in matches:
            scored[h] += gh
            expected[h] += base * defence[a] * home
            scored[a] += ga
            expected[a] += base * defence[h] / home
        attack = {team: scored[team] / expected[team] for team in teams}
        conceded, expected = {team: prior for team in teams}, {team: prior for team in teams}
        for h, a, gh, ga in matches:
            conceded[h] += ga
            expected[h] += base * attack[a] / home
            conceded[a] += gh
            expected[a] += base * attack[h] * home
        defence = {team: conceded[team] / expected[team] for team in teams}
        mean_a = sum(attack.values()) / len(teams)
        mean_d = sum(defence.values()) / len(teams)
        attack = {team: value / mean_a for team, value in attack.items()}
        defence = {team: value / mean_d for team, value in defence.items()}
        home_goals = sum(row[2] for row in matches)
        away_goals = sum(row[3] for row in matches)
        home_raw = sum(base * attack[h] * defence[a] for h, a, _, _ in matches)
        away_raw = sum(base * attack[a] * defence[h] for h, a, _, _ in matches)
        # The home factor is shrunk the same way, so one early result can't explain everything.
        home = math.sqrt(((home_goals + prior) / (home_raw + prior)) / ((away_goals + prior) / (away_raw + prior)))
    return {"attack": attack, "defence": defence, "home": home, "base": base, "matches": len(matches)}


def fixture_view(ratings, team, opponent, is_home):
    """Expected goals for/against, clean-sheet chance and multipliers for one club in one fixture."""
    base, home = ratings["base"], ratings["home"]
    venue = home if is_home else 1 / home
    attack, defence = ratings["attack"], ratings["defence"]
    lambda_for = base * attack.get(team, 1.0) * defence.get(opponent, 1.0) * venue
    lambda_against = base * attack.get(opponent, 1.0) * defence.get(team, 1.0) / venue
    cs_prob = math.exp(-lambda_against)
    return {"lambda_for": lambda_for, "lambda_against": lambda_against, "cs_prob": cs_prob,
            "att_mult": lambda_for / base, "cs_mult": cs_prob / math.exp(-base)}


def multiplier(view, element_type):
    """Position-weighted blend of attack and clean-sheet multipliers (heuristic weights)."""
    weight = ATTACK_WEIGHT.get(element_type, 0.5)
    return weight * view["att_mult"] + (1 - weight) * view["cs_mult"]


def horizon_gameweeks(snapshot, horizon=HORIZON):
    """Gameweeks from the snapshot's fixture horizon, starting at the next gameweek."""
    events = ((snapshot or {}).get("fixtures") or {}).get("events") or {}
    gameweeks = sorted({int(key) for key in events if str(key).isdigit()})
    next_id = (((snapshot or {}).get("events") or {}).get("next") or {}).get("id")
    if isinstance(next_id, int):
        gameweeks = [gw for gw in gameweeks if gw >= next_id] or [next_id]
    return gameweeks[:horizon]


def club_fixtures(snapshot, gameweeks):
    """{gw: {club: [(opponent, is_home), ...]}} from the snapshot's fixture horizon."""
    events = ((snapshot or {}).get("fixtures") or {}).get("events") or {}
    result = {}
    for gw in gameweeks:
        rows = events.get(str(gw), events.get(gw)) or []
        clubs = result.setdefault(gw, {})
        for fixture in rows if isinstance(rows, list) else []:
            if isinstance(fixture, dict) and fixture.get("team_h") is not None and fixture.get("team_a") is not None:
                clubs.setdefault(fixture["team_h"], []).append((fixture["team_a"], True))
                clubs.setdefault(fixture["team_a"], []).append((fixture["team_h"], False))
    return result


def project_player(player, fixtures, gameweeks, ratings):
    """Per-gameweek xP, 6-GW total and decayed total for one catalog player."""
    flags = []
    if player.get("status") not in AVAILABLE_STATUS:
        flags.append("FPL lists unavailable: projects 0")
        weekly = [0.0 for _ in gameweeks]
    else:
        kind, team = player.get("element_type"), player.get("team")
        def gw_mult(gw):
            return sum(multiplier(fixture_view(ratings, team, opponent, is_home), kind)
                       for opponent, is_home in fixtures.get(gw, {}).get(team, []))
        mults = [gw_mult(gw) for gw in gameweeks]
        if mults and mults[0] > 0:  # ep_next already carries availability, so nothing else scales it
            base = (_number(player.get("ep_next")) or 0.0) / mults[0]
        else:
            chance = player.get("chance_of_playing_next_round")
            scale = chance / 100 if isinstance(chance, int) and not isinstance(chance, bool) and player.get("status") == "d" else 1.0
            base = max(_number(player.get("form")) or 0.0, 0.0) * scale
            flags.append("no fixture next GW: base taken from form")
        weekly = [max(base, 0.0) * mult for mult in mults]
    weekly = [round(value, 2) for value in weekly]
    return {"gameweeks": list(gameweeks), "xp": weekly, "xp_6": round(sum(weekly), 2),
            "xp_6_decayed": round(sum(value * DECAY ** index for index, value in enumerate(weekly)), 2), "flags": flags}


def best_xi_total(rows):
    """Best legal XI total from (element_type, value) rows: 1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD."""
    by_type = {kind: sorted((value for k, value in rows if k == kind), reverse=True) for kind in FORMATION_LIMITS}
    best = None
    for counts in product(*(FORMATION_LIMITS[kind] for kind in (1, 2, 3, 4))):
        if sum(counts) != 11 or any(len(by_type[kind]) < count for kind, count in zip((1, 2, 3, 4), counts)):
            continue
        total = sum(sum(by_type[kind][:count]) for kind, count in zip((1, 2, 3, 4), counts))
        best = total if best is None or total > best else best
    return best


def squad_horizon(projections, players, squad_ids):
    """Decayed sum over the horizon of the best XI each week (no captain) for a 15-player squad."""
    weekly = {pid: (projections.get(pid) or {}).get("xp") or [] for pid in squad_ids}
    total = 0.0
    for index in range(max((len(values) for values in weekly.values()), default=0)):
        rows = [((players.get(pid) or {}).get("element_type"), values[index] if index < len(values) else 0.0) for pid, values in weekly.items()]
        total += (best_xi_total(rows) or 0.0) * DECAY ** index
    return round(total, 2)


def build(snapshot, catalog, horizon=HORIZON, model="fpl", history=None):
    """Project every catalog player over the next ``horizon`` gameweeks.

    ``model="fpl"`` (the default) re-weights FPL's ep_next; ``model="own"`` uses the Stage 2
    component model in ``xp_model`` with ``history`` (data/player_history.json).
    """
    if model not in ("fpl", "own"):
        raise ValueError("model must be 'fpl' or 'own'")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    players = [player for player in (catalog or {}).get("players", []) if isinstance(player, dict) and isinstance(player.get("id"), int)]
    team_ids = [team.get("id") for team in (catalog or {}).get("teams", []) if isinstance(team, dict) and team.get("id") is not None]
    results = snapshot.get("team_results")
    ratings = team_ratings(results if isinstance(results, list) else [], team_ids)
    gameweeks = horizon_gameweeks(snapshot, horizon)
    fixtures = club_fixtures(snapshot, gameweeks)
    caveats = []
    if not isinstance(results, list):
        caveats.append("This snapshot has no team results, so every club is rated average and only the number of fixtures changes the projection. Refresh FPL data to fit team ratings.")
    elif not ratings["matches"]:
        caveats.append("No finished matches yet, so every club is rated average.")
    if model == "own":
        from . import xp_model  # imported here: xp_model builds on this module's helpers
        projected, own_caveats = xp_model.project_all(snapshot, players, history, ratings, gameweeks, fixtures)
        return {"model": "own", "available": not own_caveats, "gameweeks": gameweeks, "ratings": ratings,
                "ratings_fitted": bool(ratings["matches"]), "players": projected, "method": xp_model.METHOD,
                "caveats": caveats + own_caveats}
    return {
        "model": "fpl", "gameweeks": gameweeks, "ratings": ratings, "ratings_fitted": bool(ratings["matches"]),
        "players": {player["id"]: project_player(player, fixtures, gameweeks, ratings) for player in players},
        "method": (f"Estimate, not a forecast: FPL's ep_next with next week's fixture difficulty removed, then re-weighted by "
                   f"each later fixture from team attack/defence ratings fitted to this season's xG (goals where xG is missing), "
                   f"shrunk with {PRIOR_MATCHES} average pseudo-matches. Attack/clean-sheet weights are heuristics "
                   f"(MID/FWD 0.7/0.3, GK/DEF 0.3/0.7). Decayed totals weight week k by {DECAY}^k. "
                   f"A player's current availability doubt (already in ep_next) is applied to every projected week."),
        "caveats": caveats,
    }
