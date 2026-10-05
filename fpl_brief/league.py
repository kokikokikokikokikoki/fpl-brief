"""League threats and the fixture ticker, from public FPL data.

Threats compare your squad with the top of your mini-league: which players they lean on that you
don't (points you can lose), which of yours they don't have (points you can gain), what they
captained, and which chips they still hold. The ticker lays out every club's next fixtures with
FPL's own difficulty rating and marks long gaps (international breaks) and blank or double weeks.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .matchday import HISTORY_TTL, PICKS_TTL, BOOT_TTL, WORKERS, Unavailable, _attempt, _int

TOP_RIVALS = 10
CHIP_NAMES = {"wildcard": "Wildcard", "freehit": "Free Hit", "bboost": "Bench Boost", "3xc": "Triple Captain", "manager": "Assistant Manager"}
BREAK_DAYS = 12
TICKER_WEEKS = 6


def chips_left(chip_rules, used, gameweek):
    """Chips still playable in the current window: FPL's rules list each chip with a gameweek window."""
    left = []
    for rule in chip_rules or []:
        if not isinstance(rule, dict):
            continue
        start, stop = _int(rule.get("start_event"), 1), _int(rule.get("stop_event"), 38)
        if not start <= gameweek <= stop:
            continue
        name = rule.get("name")
        if not any(chip.get("name") == name and start <= _int(chip.get("event")) <= stop for chip in used or [] if isinstance(chip, dict)):
            left.append({"name": name, "label": CHIP_NAMES.get(name, str(name)), "expires": stop})
    return left


def _parse(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def ticker(fixtures_by_event, teams, squad_teams=None, first=None, weeks=TICKER_WEEKS):
    """Per club: the next ``weeks`` gameweeks with opponent, venue, FPL difficulty and date; gaps and blanks marked."""
    squad_teams = squad_teams or {}
    events = sorted({int(k) for k in (fixtures_by_event or {}) if str(k).isdigit()})
    if first is not None:
        events = [gw for gw in events if gw >= first]
    events = events[:weeks]
    rows = []
    for team_id, team in teams.items():
        cells, last_kickoff, gaps = [], None, []
        for gw in events:
            games = []
            for fixture in fixtures_by_event.get(str(gw), fixtures_by_event.get(gw)) or []:
                if not isinstance(fixture, dict) or team_id not in (fixture.get("team_h"), fixture.get("team_a")):
                    continue
                home = fixture.get("team_h") == team_id
                other = fixture.get("team_a") if home else fixture.get("team_h")
                difficulty = fixture.get("team_h_difficulty" if home else "team_a_difficulty")
                kickoff = _parse(fixture.get("kickoff_time"))
                games.append({"opponent": (teams.get(other) or {}).get("short_name") or "?", "venue": "H" if home else "A",
                              "difficulty": difficulty if isinstance(difficulty, int) and 1 <= difficulty <= 5 else None,
                              "kickoff": fixture.get("kickoff_time"), "_at": kickoff})
            games.sort(key=lambda g: g["kickoff"] or "")
            first_at = next((g["_at"] for g in games if g["_at"]), None)
            if first_at and last_kickoff and (first_at - last_kickoff).days >= BREAK_DAYS:
                gaps.append(gw)
            for g in games:
                last_kickoff = g.pop("_at") or last_kickoff
            cells.append({"gameweek": gw, "games": games, "break_before": gw in gaps})
        scored = [g["difficulty"] for c in cells[:4] for g in c["games"] if g["difficulty"]]
        rows.append({"team_id": team_id, "team": team.get("short_name"), "name": team.get("name"), "cells": cells,
                     "next4": round(sum(scored) / len(scored), 2) if scored else None, "yours": squad_teams.get(team_id, [])})
    rows.sort(key=lambda r: (r["next4"] if r["next4"] is not None else 9, r["team"] or ""))
    return {"gameweeks": events, "rows": rows,
            "method": "FPL's own difficulty (1 easy – 5 hard). Average over the next 4 gameweeks. A break marks 12+ days without a match for that club."}


def threats(snapshot, get):
    """Your squad against the top of your mini-league (live standings, public picks and chip history)."""
    team_id, league_id = _int(snapshot.get("team_id"), None), _int(snapshot.get("league_id"), None)
    if not team_id or not league_id:
        return {"state": "unavailable", "reason": "No team or league is configured yet."}
    try:
        boot = get("bootstrap-static/", BOOT_TTL)
        standings = [r for r in ((get(f"leagues-classic/{league_id}/standings/?page_standings=1", HISTORY_TTL) or {}).get("standings") or {}).get("results") or [] if isinstance(r, dict)]
    except Unavailable as error:
        return {"state": "unavailable", "reason": f"League data isn't available right now ({error})."}
    events = [e for e in boot.get("events") or [] if isinstance(e, dict)]
    current = next((e for e in events if e.get("is_current")), None)
    upcoming = next((e for e in events if e.get("is_next")), None)
    if not current:
        return {"state": "unavailable", "reason": "No gameweek has passed its deadline yet."}
    gameweek, chip_week = _int(current.get("id")), _int((upcoming or current).get("id"))
    teams = {t.get("id"): t.get("short_name") for t in boot.get("teams") or [] if isinstance(t, dict)}
    players = {p.get("id"): {"name": p.get("web_name"), "team": teams.get(p.get("team")), "team_id": p.get("team"), "ownership": p.get("selected_by_percent")}
               for p in boot.get("elements") or [] if isinstance(p, dict)}
    standings = [r for r in standings if _int(r.get("entry"), None)]
    ordered = sorted(standings, key=lambda r: (_int(r.get("rank"), 10**9), _int(r.get("entry"), 10**9)))
    you_row = next((r for r in ordered if _int(r.get("entry")) == team_id), None)
    rivals = [r for r in ordered if _int(r.get("entry")) != team_id][:TOP_RIVALS]
    group = [{"entry": team_id, "row": you_row or {}, "is_you": True}] + [{"entry": _int(r.get("entry")), "row": r, "is_you": False} for r in rivals]

    def load(member):
        entry = member["entry"]
        return get(f"entry/{entry}/event/{gameweek}/picks/", PICKS_TTL), get(f"entry/{entry}/history/", HISTORY_TTL)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda m: _attempt(load, m), group))
    warnings, members = [], []
    for member, (payload, error) in zip(group, results):
        if error:
            if member["is_you"]:
                return {"state": "unavailable", "reason": f"Your squad couldn't be loaded ({error})."}
            warnings.append(f"Skipped {member['row'].get('entry_name')}: {error}.")
            continue
        picks, history = payload
        squad = [_int(p.get("element")) for p in (picks or {}).get("picks") or [] if isinstance(p, dict)]
        captain = next((_int(p.get("element")) for p in (picks or {}).get("picks") or [] if isinstance(p, dict) and p.get("is_captain")), None)
        entry_history = (picks or {}).get("entry_history") or {}
        if member["is_you"] and not member["row"]:  # not on standings page 1: use your own total instead
            member["row"] = {"entry_name": "You", "total": entry_history.get("total_points"), "rank": None}
        members.append({"entry_id": member["entry"], "is_you": member["is_you"], "name": member["row"].get("entry_name"), "manager": member["row"].get("player_name"),
                        "rank": member["row"].get("rank"), "total": member["row"].get("total"), "squad": squad, "captain": captain,
                        "bank": entry_history.get("bank"), "value": entry_history.get("value"),
                        "chips_left": chips_left(boot.get("chips"), (history or {}).get("chips"), chip_week),
                        "chips_used": [{"name": c.get("name"), "label": CHIP_NAMES.get(c.get("name"), c.get("name")), "gameweek": c.get("event")} for c in (history or {}).get("chips") or [] if isinstance(c, dict)]})
    you = members[0]
    others = members[1:]
    counts, captains = {}, {}
    for member in others:
        for element in member["squad"]:
            counts[element] = counts.get(element, 0) + 1
        if member["captain"]:
            captains[member["captain"]] = captains.get(member["captain"], 0) + 1
    mine = set(you["squad"])
    half = max(1, (len(others) + 1) // 2)

    def row(element):
        info = players.get(element) or {}
        return {"id": element, "name": info.get("name") or f"#{element}", "team": info.get("team"), "team_id": info.get("team_id"),
                "rivals": counts.get(element, 0), "captained": captains.get(element, 0), "ownership": info.get("ownership")}

    missing = sorted((row(e) for e in counts if e not in mine and counts[e] >= half), key=lambda r: (-r["rivals"], r["name"]))
    shared = sorted((row(e) for e in mine if counts.get(e, 0) >= half), key=lambda r: (-r["rivals"], r["name"]))
    differentials = sorted((row(e) for e in mine if counts.get(e, 0) <= 1), key=lambda r: (r["rivals"], r["name"]))
    leader = min(members, key=lambda m: _int(m.get("rank"), 10**9))
    table = [{key: m[key] for key in ("entry_id", "is_you", "name", "manager", "rank", "total", "bank", "value", "chips_left", "chips_used")}
             | {"gap": _int(m.get("total")) - _int(you.get("total")), "captain": (players.get(m["captain"]) or {}).get("name"),
                "shared": len(mine & set(m["squad"])) if not m["is_you"] else None}
             for m in sorted(members, key=lambda m: _int(m.get("rank"), 10**9))]
    return {
        "state": "ready", "gameweek": gameweek, "chip_week": chip_week, "rivals_compared": len(others), "you": {"rank": you["rank"], "total": you["total"]},
        "leader": {"name": leader["name"], "gap": _int(leader.get("total")) - _int(you.get("total"))},
        "missing": missing, "shared": shared, "differentials": differentials,
        "captains": sorted((row(e) for e in captains), key=lambda r: -r["captained"]),
        "table": table, "warnings": warnings,
        "method": f"Top {len(others)} of your mini-league by live standings, using their GW{gameweek} squads. \"They have, you don't\" lists players at least half of them own.",
    }
