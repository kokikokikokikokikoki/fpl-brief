"""What FPL managers are doing: official crowd signals from the public FPL API.

Everything here is arithmetic over published FPL fields (ownership, transfers, price
moves, event summaries) and the manager's public mini-league squads. It describes the
crowd; it does not predict points or recommend moves.
"""

TOP = 10


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _row(player, teams, rival_owners=None):
    tin, tout = _int(player.get("transfers_in_event")), _int(player.get("transfers_out_event"))
    return {
        "id": player["id"], "name": player.get("web_name"), "team": (teams.get(player.get("team")) or {}).get("short_name"),
        "position": player.get("element_type"), "price": player.get("now_cost"),
        "ownership": _num(player.get("selected_by_percent")),
        "transfers_in": tin, "transfers_out": tout,
        "net_transfers": tin - tout if tin is not None and tout is not None else None,
        "price_change_event": _int(player.get("cost_change_event")),
        "price_change_start": _int(player.get("cost_change_start")),
        "rival_owners": rival_owners,
    }


def _event_summary(event, players, label):
    if not isinstance(event, dict) or not isinstance(event.get("id"), int):
        return None
    name = lambda pid: (players.get(pid) or {}).get("web_name") if isinstance(pid, int) else None
    chips = [{"chip": chip.get("chip_name"), "played": chip.get("num_played")}
             for chip in event.get("chip_plays") or [] if isinstance(chip, dict) and _int(chip.get("num_played")) is not None]
    return {
        "gameweek": event["id"], "label": label,
        "most_captained": name(event.get("most_captained")), "most_vice_captained": name(event.get("most_vice_captained")),
        "most_selected": name(event.get("most_selected")), "most_transferred_in": name(event.get("most_transferred_in")),
        "top_scorer": name(event.get("top_element")), "transfers_made": _int(event.get("transfers_made")),
        "average_score": _int(event.get("average_entry_score")), "chip_plays": sorted(chips, key=lambda c: -c["played"]),
    }


def build(snapshot, catalog):
    """Return the crowd view model, or {"state": "unavailable", "reason": ...} without transfer data."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    players = {p["id"]: p for p in (catalog or {}).get("players", []) if isinstance(p, dict) and isinstance(p.get("id"), int)}
    teams = {t.get("id"): t for t in (catalog or {}).get("teams", []) if isinstance(t, dict)}
    if not players or not any(_int(p.get("transfers_in_event")) is not None for p in players.values()):
        return {"state": "unavailable", "reason": "Crowd transfer data is not in this snapshot yet. Refresh FPL data."}

    picks = [pick.get("element") for pick in ((snapshot.get("squad_snapshot") or {}).get("picks") or []) if isinstance(pick, dict)]
    rivals = [r for r in snapshot.get("rivals") or [] if isinstance(r, dict) and isinstance(r.get("comparison"), dict) and r["comparison"].get("comparable")]
    owned_by_rivals, others_by_rivals = {}, {}
    for rival in rivals:
        comparison = rival["comparison"]
        for pid in comparison.get("shared") or []:
            if isinstance(pid, int):
                owned_by_rivals[pid] = owned_by_rivals.get(pid, 0) + 1
        for pid in comparison.get("rival_only") or []:
            if isinstance(pid, int):
                others_by_rivals[pid] = others_by_rivals.get(pid, 0) + 1

    ranked = [_row(p, teams) for p in players.values()]
    with_in = [r for r in ranked if r["transfers_in"] is not None]
    events = snapshot.get("events") or {}
    return {
        "state": "ready",
        "gameweek": (events.get("next") or events.get("current") or {}).get("id"),
        "transfers_in": sorted(with_in, key=lambda r: (-r["transfers_in"], r["id"]))[:TOP],
        "transfers_out": sorted(with_in, key=lambda r: (-(r["transfers_out"] or 0), r["id"]))[:TOP],
        "risers": sorted([r for r in ranked if (r["price_change_event"] or 0) > 0], key=lambda r: (-r["price_change_event"], -(r["net_transfers"] or 0)))[:TOP],
        "fallers": sorted([r for r in ranked if (r["price_change_event"] or 0) < 0], key=lambda r: (r["price_change_event"], r["net_transfers"] or 0))[:TOP],
        "events": [summary for summary in (_event_summary(events.get("next"), players, "this gameweek so far"),
                                           _event_summary(events.get("current"), players, "last gameweek")) if summary],
        "squad": {pid: _row(players[pid], teams, owned_by_rivals.get(pid, 0)) for pid in picks if pid in players},
        "league": {
            "rivals_compared": len(rivals),
            "missing": sorted(
                [_row(players[pid], teams, count) for pid, count in others_by_rivals.items() if pid in players and pid not in picks],
                key=lambda r: (-r["rival_owners"], -(r["ownership"] or 0), r["id"]))[:TOP],
        },
        "method": "Official FPL crowd data: ownership, this gameweek's transfers and price moves, and your mini-league rivals' public squads. It shows what managers are doing, not what will score.",
    }


def note(row):
    """One plain-language crowd line for a player row from build()["squad"] (or a transfers list)."""
    if not isinstance(row, dict):
        return ""
    parts = []
    if row.get("ownership") is not None:
        parts.append(f"{row['ownership']:g}% own")
    net = row.get("net_transfers")
    if net is not None:
        parts.append(f"{'+' if net >= 0 else '−'}{abs(net):,} net transfers this GW")
    move = row.get("price_change_event")
    if move:
        parts.append(f"price {'+' if move > 0 else '−'}£{abs(move) / 10:.1f}m this GW")
    if row.get("rival_owners") is not None:
        parts.append(f"{row['rival_owners']} league rival{'s' if row['rival_owners'] != 1 else ''} own")
    return " · ".join(parts)
