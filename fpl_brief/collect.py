from datetime import datetime, timezone

from .analyze import compare_squads, select_rivals


STATUS = {"a": "available", "d": "doubtful", "i": "injured", "s": "suspended", "u": "unavailable", "n": "not eligible"}


def event_summary(events):
    current = next((event for event in events if event.get("is_current")), None)
    next_event = next((event for event in events if event.get("is_next")), None)
    finished = [event for event in events if event.get("finished")]
    return {"current": current, "next": next_event, "last_finished": max(finished, key=lambda event: event["id"], default=None)}


def picks_for(client, entry_id, fallback_event):
    entry = client.get(f"entry/{entry_id}/")
    event_id = entry.get("current_event") or fallback_event
    return client.get(f"entry/{entry_id}/event/{event_id}/picks/")


def availability(elements, picks):
    selected = {pick.get("element") for pick in picks.get("picks", [])}
    rows = []
    for player in elements:
        if player["id"] not in selected:
            continue
        chance, news = player.get("chance_of_playing_next_round"), player.get("news") or ""
        if player.get("status") != "a" or (chance is not None and chance < 100) or news:
            rows.append({"player_id": player["id"], "name": player["web_name"], "club_id": player["team"], "status": STATUS.get(player.get("status"), "unknown"), "chance": chance, "news": news, "news_added": player.get("news_added")})
    return rows


def fixture_horizon(fixtures, events, horizon):
    now = datetime.now(timezone.utc)
    def is_future(event):
        deadline = event.get("deadline_time")
        if not deadline:
            return False
        return datetime.fromisoformat(deadline.replace("Z", "+00:00")) > now
    next_ids = [event["id"] for event in events if event.get("id") is not None and is_future(event)][:horizon]
    grouped = {event_id: [] for event_id in next_ids}
    unassigned = []
    for fixture in fixtures:
        event_id = fixture.get("event")
        if event_id in grouped:
            grouped[event_id].append(fixture)
        elif event_id is None:
            unassigned.append(fixture)
    return {"events": grouped, "unassigned": unassigned}


def _xg_by_fixture(live, fixtures, player_teams):
    """Sum player expected_goals into {fixture_id: {club: xG}}; a club's fixture is None when it can't be split."""
    by_club = {}
    for fixture in fixtures:
        for side in ("team_h", "team_a"):
            by_club.setdefault(fixture[side], []).append(fixture["id"])
    totals = {fixture["id"]: {fixture["team_h"]: 0.0, fixture["team_a"]: 0.0} for fixture in fixtures}
    unsplit = set()
    for element in (live or {}).get("elements", []):
        team = player_teams.get(element.get("id"))
        club_fixtures = by_club.get(team)
        if not club_fixtures:
            continue
        try:
            xg = float((element.get("stats") or {}).get("expected_goals") or 0)
        except (TypeError, ValueError):
            continue
        explain = [row for row in element.get("explain") or [] if isinstance(row, dict)]
        played_in = {row.get("fixture") for row in explain}
        if len(club_fixtures) == 1:
            # Skip a player whose minutes were for another club (moved since this gameweek).
            if not explain or club_fixtures[0] in played_in:
                totals[club_fixtures[0]][team] += xg
            continue
        split = {row.get("fixture"): next((float(stat.get("value") or 0) for stat in row.get("stats") or [] if stat.get("identifier") == "expected_goals"), None) for row in explain}
        if xg and any(split.get(fixture_id) is None for fixture_id in club_fixtures if fixture_id in played_in):
            unsplit.update((fixture_id, team) for fixture_id in club_fixtures)
            continue
        for fixture_id in club_fixtures:
            totals[fixture_id][team] += split.get(fixture_id) or 0.0
    for fixture_id, team in unsplit:
        totals[fixture_id][team] = None
    return totals


def team_results(client, fixtures, elements, warnings):
    """One compact row per finished fixture: scores from fixtures/, club xG from event/{gw}/live/."""
    finished = [fixture for fixture in fixtures if fixture.get("finished") and isinstance(fixture.get("event"), int) and fixture.get("id") is not None
                and fixture.get("team_h_score") is not None and fixture.get("team_a_score") is not None]
    player_teams = {player.get("id"): player.get("team") for player in elements}
    rows = []
    for gameweek in sorted({fixture["event"] for fixture in finished}):
        gw_fixtures = [fixture for fixture in finished if fixture["event"] == gameweek]
        try:
            xg = _xg_by_fixture(client.get(f"event/{gameweek}/live/"), gw_fixtures, player_teams)
        except Exception as error:
            warnings.append(f"Could not collect GW{gameweek} xG; projections use goals for that week: {error}")
            xg = {}
        for fixture in sorted(gw_fixtures, key=lambda row: row["id"]):
            values = xg.get(fixture["id"]) or {}
            home_xg, away_xg = values.get(fixture["team_h"]), values.get(fixture["team_a"])
            rows.append({"gw": gameweek, "fixture_id": fixture["id"], "home": fixture["team_h"], "away": fixture["team_a"],
                         "home_goals": fixture["team_h_score"], "away_goals": fixture["team_a_score"],
                         "home_xg": round(home_xg, 2) if home_xg is not None else None,
                         "away_xg": round(away_xg, 2) if away_xg is not None else None})
    return rows


def collect(client, config):
    warnings = []
    boot = client.get("bootstrap-static/")
    events = boot.get("events", [])
    if not events:
        raise ValueError("FPL returned no gameweek events; existing output was preserved")
    summary = event_summary(events)
    fallback = (summary["current"] or summary["next"] or summary["last_finished"])
    if not fallback:
        raise ValueError("FPL returned no usable gameweek")
    team_id, league_id = config["team_id"], config["league_id"]
    entry = client.get(f"entry/{team_id}/")
    history = client.get(f"entry/{team_id}/history/")
    user_picks = picks_for(client, team_id, fallback["id"])
    standings = client.standings(league_id)
    rivals, user_standing = select_rivals(standings, team_id, config["top_rivals"], config["nearby_rivals_each_side"])
    if not user_standing:
        warnings.append("Your entry was not found in the configured mini-league.")
    leader = min(standings, key=lambda row: (row.get("rank", 10**9), row.get("entry", 10**9)), default=None)
    rival_rows = []
    for rival in rivals:
        try:
            rival_picks = picks_for(client, rival["entry"], fallback["id"])
            rival_rows.append({"entry_id": rival["entry"], "name": rival.get("entry_name"), "rank": rival.get("rank"), "points": rival.get("total"), "comparison": compare_squads(user_picks, rival_picks), "snapshot_event": rival_picks.get("entry_history", {}).get("event")})
        except Exception as error:
            warnings.append(f"Could not collect rival {rival['entry']}: {error}")
    fixtures = client.get("fixtures/")
    snapshot = {
        "schema_version": 1, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "chip_rules": boot.get("chips"),
        "team_id": team_id, "league_id": league_id, "events": summary,
        "manager": {"entry_name": entry.get("name"), "points": entry.get("summary_overall_points"), "overall_rank": entry.get("summary_overall_rank"), "history": history.get("current", []), "chips": history.get("chips", [])},
        "squad_snapshot": {"event_id": user_picks.get("entry_history", {}).get("event"), "picks": user_picks.get("picks", []), "bank": user_picks.get("entry_history", {}).get("bank")},
        "league": {"name": "#club-football", "rank": user_standing.get("rank") if user_standing else None, "points": user_standing.get("total") if user_standing else None, "leader": {"entry_id": leader.get("entry"), "name": leader.get("entry_name"), "points": leader.get("total")} if leader else None, "gap_to_leader": (leader.get("total") - user_standing.get("total")) if leader and user_standing else None, "provisional": bool(summary["current"] and not summary["current"].get("finished"))},
        "rivals": rival_rows, "fixtures": fixture_horizon(fixtures, events, config["fixture_horizon"]),
        "availability": availability(boot.get("elements", []), user_picks),
        "team_results": team_results(client, fixtures, boot.get("elements", []), warnings), "warnings": warnings,
    }
    return snapshot, boot
