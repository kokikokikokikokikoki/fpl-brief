"""Transparent, legal replacement filters for the FPL Candidate Lens."""

from datetime import datetime, timezone

from .decision import parse_time, snapshot_freshness


def player_map(catalog):
    return {player["id"]: player for player in catalog.get("players", []) if isinstance(player.get("id"), int)}


def fixture_difficulties(snapshot):
    result = {}
    for fixtures in snapshot.get("fixtures", {}).get("events", {}).values():
        for fixture in fixtures:
            result.setdefault(fixture.get("team_h"), []).append(fixture.get("team_h_difficulty"))
            result.setdefault(fixture.get("team_a"), []).append(fixture.get("team_a_difficulty"))
    return {team_id: round(sum(values) / len(values), 2) for team_id, values in result.items() if values and all(isinstance(value, (int, float)) for value in values)}


def xgi_per_90(player):
    minutes = player.get("minutes") or 0
    if not isinstance(minutes, (int, float)) or minutes <= 0:
        return None
    xgi = float(player.get("expected_goals") or 0) + float(player.get("expected_assists") or 0)
    return round(xgi * 90 / minutes, 3)


def is_available(player):
    chance = player.get("chance_of_playing_next_round")
    return player.get("status") == "a" and (chance is None or chance >= 100)


def lens(snapshot, catalog, replace_id, minimum_minutes=0, stale_after_hours=8, now=None):
    """Return legal same-position alternatives with every applied rule exposed."""
    snapshot = snapshot or {}
    players = player_map(catalog)
    picks = snapshot.get("squad_snapshot", {}).get("picks", [])
    current = now or datetime.now(timezone.utc)
    blockers = []
    if snapshot_freshness(snapshot, stale_after_hours, current)["stale"]:
        blockers.append("Refresh the public snapshot before using Candidate Lens")
    if len(picks) != 15:
        blockers.append("The public squad snapshot is incomplete")
    deadline = parse_time((snapshot.get("events", {}).get("next") or {}).get("deadline_time"))
    if not deadline:
        blockers.append("The next FPL deadline is unavailable")
    elif deadline <= current:
        blockers.append("The next FPL deadline has passed")
    if blockers:
        raise ValueError("; ".join(blockers) + ".")
    outgoing = players.get(replace_id)
    owned_ids = {pick.get("element") for pick in picks}
    if not outgoing or replace_id not in owned_ids:
        raise ValueError("Select a player from the public squad snapshot")
    if not isinstance(minimum_minutes, int) or minimum_minutes < 0:
        raise ValueError("Minimum minutes must be a non-negative integer")
    outgoing_pick = next((pick for pick in picks if pick.get("element") == replace_id), None)
    bank = snapshot.get("squad_snapshot", {}).get("bank")
    selling_price = outgoing_pick.get("selling_price") if isinstance(outgoing_pick, dict) else None
    if isinstance(selling_price, bool) or not isinstance(selling_price, (int, float)) or selling_price < 0:
        raise ValueError("The actual selling price is unavailable; affordability claims are blocked")
    if isinstance(bank, bool) or not isinstance(bank, (int, float)) or bank < 0:
        raise ValueError("The bank balance is unavailable; affordability claims are blocked")
    budget = int(selling_price) + int(bank)
    team_counts = {}
    for player_id in owned_ids - {replace_id}:
        player = players.get(player_id)
        if player:
            team_counts[player.get("team")] = team_counts.get(player.get("team"), 0) + 1
    difficulties = fixture_difficulties(snapshot)
    candidates = []
    for player in players.values():
        if player["id"] in owned_ids or player.get("element_type") != outgoing.get("element_type"):
            continue
        if int(player.get("now_cost") or 0) > budget or team_counts.get(player.get("team"), 0) >= 3:
            continue
        if not is_available(player) or int(player.get("minutes") or 0) < minimum_minutes:
            continue
        candidates.append({
            "id": player["id"], "name": player.get("web_name"), "team_id": player.get("team"), "price": player.get("now_cost"),
            "minutes": player.get("minutes") or 0, "xgi_per_90": xgi_per_90(player),
            "fixture_difficulty_average": difficulties.get(player.get("team")), "availability": "available",
        })
    candidates.sort(key=lambda player: (-(player["xgi_per_90"] or 0), -player["minutes"], player["fixture_difficulty_average"] if player["fixture_difficulty_average"] is not None else 99, player["name"] or ""))
    return {
        "outgoing": {"id": outgoing["id"], "name": outgoing.get("web_name"), "position": outgoing.get("element_type"), "price": outgoing.get("now_cost"), "selling_price": selling_price},
        "budget": budget,
        "filters": {"same_position": True, "within_budget": True, "team_limit": 3, "availability": "available only", "minimum_minutes": minimum_minutes},
        "candidates": candidates,
        "method": "Rows are filtered for legal replacements, then shown by xGI per 90, minutes, and fixture difficulty. This is not a points forecast.",
        "caveats": ["Affordability uses the validated public squad selling price plus bank; private transfer state remains unavailable.", "Fixture difficulty is the average published FDR across the stored horizon."],
    }
