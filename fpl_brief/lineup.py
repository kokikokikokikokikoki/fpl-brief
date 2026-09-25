"""Deterministic next-gameweek lineup helper built on FPL's published ep_next estimate.

It never forecasts points itself: scores are FPL's own ``ep_next`` values, availability is
the official FPL status, and every choice carries a plain-language reason.
"""

import math
from datetime import datetime, timezone
from itertools import product

from .decision import parse_time

ROLE = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
OUT_STATUS = {"i": "injured", "s": "suspended", "u": "unavailable", "n": "not eligible"}
FORMATION_LIMITS = {2: range(3, 6), 3: range(2, 6), 4: range(1, 4)}
BENCH_BOOST_RULE = 12.0
BENCH_MIN_ESTIMATE = 1.0


def _estimate(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _refuse(reason, gameweek=None):
    return {"state": "unavailable", "reason": reason, "gameweek": gameweek}


def _fixture_counts(snapshot, gameweek):
    events = ((snapshot.get("fixtures") or {}).get("events") or {})
    fixtures = events.get(str(gameweek), events.get(gameweek)) or []
    counts = {}
    for fixture in fixtures if isinstance(fixtures, list) else []:
        if isinstance(fixture, dict):
            for side in ("team_h", "team_a"):
                counts[fixture.get(side)] = counts.get(fixture.get(side), 0) + 1
    return counts


def _player_row(pick, player, teams, fixture_counts, gameweek):
    chance = player.get("chance_of_playing_next_round")
    chance = chance if isinstance(chance, int) and not isinstance(chance, bool) else None
    status = player.get("status")
    fixtures = fixture_counts.get(player.get("team"), 0)
    flags, blockers, doubts = [], [], []
    if status in OUT_STATUS:
        blockers.append(f"FPL lists {OUT_STATUS[status]}")
    elif chance == 0:
        blockers.append("FPL lists 0% chance of playing")
    elif chance is not None and chance < 100:
        doubts.append(f"doubtful: {chance}% chance")
    elif status != "a":
        doubts.append("FPL status not fully available")
    flags.extend(doubts)
    if fixtures == 0:
        blockers.append(f"no fixture in GW{gameweek}")
    elif fixtures > 1:
        flags.append(f"{fixtures} fixtures in GW{gameweek}")
    team = teams.get(player.get("team"), {})
    return {
        "id": player["id"], "name": player.get("web_name"), "team": team.get("short_name"),
        "role": ROLE.get(player.get("element_type")), "element_type": player.get("element_type"),
        "estimate": _estimate(player.get("ep_next")), "chance": chance, "fixtures": fixtures,
        "eligible": not blockers, "fully_available": not blockers and not doubts,
        "flags": flags, "blockers": blockers,
    }


def _rank(row):
    return (not row["eligible"], -(row["estimate"] or 0), row["id"])


def _best_xi(rows):
    by_type = {kind: sorted([row for row in rows if row["element_type"] == kind], key=_rank) for kind in (1, 2, 3, 4)}
    goalkeeper = by_type[1][:1]
    best = None
    for defenders, midfielders, forwards in product(FORMATION_LIMITS[2], FORMATION_LIMITS[3], FORMATION_LIMITS[4]):
        if defenders + midfielders + forwards != 10:
            continue
        chosen = goalkeeper + by_type[2][:defenders] + by_type[3][:midfielders] + by_type[4][:forwards]
        if len(chosen) != 11:
            continue
        forced = sum(not row["eligible"] for row in chosen)
        total = round(sum(row["estimate"] or 0 for row in chosen), 2)
        key = (forced, -total, (defenders, midfielders, forwards))
        if best is None or key < best[0]:
            best = (key, chosen, f"{defenders}-{midfielders}-{forwards}", total)
    return best


def _current_lineup(private, snapshot):
    if isinstance(private, dict) and private.get("usable") is True and isinstance(private.get("lineup"), list):
        return private["lineup"], "your FPL account (captured lineup)"
    picks = (snapshot.get("squad_snapshot") or {}).get("picks") or []
    return picks, "the public snapshot (last submitted lineup)"


def suggest(snapshot, catalog, private=None, freshness=None, now=None):
    """Return a lineup view model, or an ``unavailable`` state with the reason it cannot advise."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    current = now or datetime.now(timezone.utc)
    next_event = (snapshot.get("events") or {}).get("next") or {}
    gameweek = next_event.get("id")
    if not isinstance(freshness, dict) or freshness.get("stale", True):
        return _refuse("The public FPL snapshot is stale; refresh it before choosing a lineup.", gameweek)
    deadline = parse_time(next_event.get("deadline_time"))
    if not deadline or not isinstance(gameweek, int):
        return _refuse("The next FPL deadline is unavailable.", gameweek)
    if deadline <= current:
        return _refuse("The next FPL deadline has passed; no lineup advice after the deadline.", gameweek)
    players = {player.get("id"): player for player in (catalog or {}).get("players", []) if isinstance(player, dict) and isinstance(player.get("id"), int)}
    teams = {team.get("id"): team for team in (catalog or {}).get("teams", []) if isinstance(team, dict)}
    picks = (snapshot.get("squad_snapshot") or {}).get("picks") or []
    matched = [players.get(pick.get("element")) for pick in picks if isinstance(pick, dict)]
    if len(picks) != 15 or any(player is None for player in matched):
        return _refuse("The saved squad is incomplete or has players missing from the FPL catalog.", gameweek)
    counts = _fixture_counts(snapshot, gameweek)
    rows = [_player_row(pick, player, teams, counts, gameweek) for pick, player in zip(picks, matched)]
    missing = [row["name"] for row in rows if row["estimate"] is None]
    if missing:
        return _refuse("FPL's next-round estimate is missing for " + ", ".join(str(name) for name in missing) + ".", gameweek)
    best = _best_xi(rows)
    if best is None:
        return _refuse("No legal formation can be built from the saved squad.", gameweek)
    _, xi, formation, total = best
    xi_ids = {row["id"] for row in xi}
    bench_rows = [row for row in rows if row["id"] not in xi_ids]
    backup = [row for row in bench_rows if row["element_type"] == 1]
    outfield = sorted([row for row in bench_rows if row["element_type"] != 1], key=_rank)
    bench = backup + outfield
    captain_order = sorted(xi, key=lambda row: (not row["eligible"], not row["fully_available"], -row["estimate"], row["id"]))
    captain, vice = captain_order[0], captain_order[1]

    for row in xi:
        row["reason"] = (f"Forced start: {', '.join(row['blockers'])}; no eligible alternative in this position." if not row["eligible"]
                         else "Starts: " + ("; ".join(row["flags"]) if row["flags"] else f"available, one fixture in GW{gameweek}") + ".")
    for index, row in enumerate(bench):
        if not row["eligible"]:
            row["reason"] = "Benched: " + ", ".join(row["blockers"]) + "."
        elif row["element_type"] == 1:
            row["reason"] = "Backup goalkeeper."
        else:
            row["reason"] = f"Bench {index}: lower FPL estimate than the starters in a legal XI."
        if row["eligible"] and row["flags"]:
            note = "; ".join(row["flags"])
            row["reason"] += " " + note[:1].upper() + note[1:] + "."

    lineup_picks, source = _current_lineup(private, snapshot)
    ordered = sorted([pick for pick in lineup_picks if isinstance(pick, dict)], key=lambda pick: pick.get("position") or 99)
    current_xi = {pick.get("element") for pick in ordered[:11]}
    current_bench = [pick.get("element") for pick in ordered[11:]]
    current_captain = next((pick.get("element") for pick in ordered if pick.get("is_captain")), None)
    current_vice = next((pick.get("element") for pick in ordered if pick.get("is_vice_captain")), None)
    names = {row["id"]: row["name"] for row in rows}
    changes = {
        "source": source,
        "current_xi": sorted(player_id for player_id in current_xi if player_id in names),
        "start": [names.get(player_id) for player_id in sorted(xi_ids - current_xi)],
        "bench": [names.get(player_id) for player_id in sorted(current_xi - xi_ids) if player_id in names],
        "captain": None if current_captain == captain["id"] else {"from": names.get(current_captain), "to": captain["name"]},
        "vice": None if current_vice == vice["id"] else {"from": names.get(current_vice), "to": vice["name"]},
        "bench_order_changed": set(current_bench) == {row["id"] for row in bench} and current_bench != [row["id"] for row in bench],
    }
    changes["none"] = not (changes["start"] or changes["bench"] or changes["captain"] or changes["vice"] or changes["bench_order_changed"])

    bench_total = round(sum(row["estimate"] for row in bench), 2)
    chip = None
    if isinstance(private, dict) and private.get("usable") is True:
        chip = any(isinstance(c, dict) and c.get("name") == "bboost" and c.get("status") == "available" for c in private.get("chips", []))
    all_ready = all(row["fully_available"] and row["estimate"] >= BENCH_MIN_ESTIMATE for row in bench)
    worth = chip is True and all_ready and bench_total >= BENCH_BOOST_RULE
    bench_boost = {
        "bench_total": bench_total, "available": chip, "all_bench_playing": all_ready, "rule_of_thumb": BENCH_BOOST_RULE,
        "hint": (f"Worth considering: all four bench players are fully available (no doubts) with fixtures and FPL estimates of at least {BENCH_MIN_ESTIMATE:g}, totalling "
                 f"{bench_total:g} (rule of thumb {BENCH_BOOST_RULE:g}+)." if worth else
                 "Bench Boost availability is unknown without a fresh account capture." if chip is None else
                 "Bench Boost is not available on your account." if chip is False else
                 f"Not this week by the rule of thumb: bench estimate total {bench_total:g}" + ("" if all_ready else f", and not every bench player is fully available with a fixture and an FPL estimate of at least {BENCH_MIN_ESTIMATE:g}") + "."),
    }

    lines = {role: [row for row in xi if row["role"] == role] for role in ("GK", "DEF", "MID", "FWD")}
    return {
        "state": "ready", "gameweek": gameweek, "deadline_utc": next_event.get("deadline_time"),
        "formation": formation, "xi_estimate_total": total, "lines": lines, "bench": bench,
        "captain": {"id": captain["id"], "name": captain["name"], "estimate": captain["estimate"], "flags": captain["flags"]},
        "vice": {"id": vice["id"], "name": vice["name"], "estimate": vice["estimate"], "flags": vice["flags"]},
        "changes": changes, "bench_boost": bench_boost,
        "method": "Highest total FPL next-round estimate (ep_next) across legal formations, after removing players FPL lists as out or without a fixture. FPL's estimate, not a forecast by this app.",
    }
