"""Validate planned transfers against FPL rules and re-optimise the next-gameweek lineup.

Budget uses the manager's captured selling prices and bank; hits use the captured free
transfers and per-transfer cost. Nothing here contacts FPL or makes a transfer.
"""

import copy

from . import lineup

MAX_TRANSFERS = 3
CLUB_LIMIT = 3


def parse_transfers(raw):
    """Parse "OUT:IN,OUT:IN" into integer pairs; raise ValueError on anything else."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Add at least one transfer.")
    pairs = []
    for chunk in raw.split(","):
        parts = chunk.split(":")
        if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
            raise ValueError("Transfers must look like OUT_ID:IN_ID.")
        pairs.append((int(parts[0]), int(parts[1])))
    if len(pairs) > MAX_TRANSFERS:
        raise ValueError(f"Plan at most {MAX_TRANSFERS} transfers at once.")
    return pairs


def _available(player):
    chance = player.get("chance_of_playing_next_round")
    return player.get("status") == "a" and (chance is None or chance >= 100)


def build(snapshot, catalog, private, freshness, pairs, now=None):
    """Return {"state": "ready", "lineup", "summary"} or {"state": "invalid", "reason"}."""
    def invalid(reason):
        return {"state": "invalid", "reason": reason}

    if not (isinstance(private, dict) and private.get("usable") is True):
        return invalid("Planning transfers needs a fresh capture of your FPL account (selling prices, bank and free transfers).")
    players = {p.get("id"): p for p in (catalog or {}).get("players", []) if isinstance(p, dict) and isinstance(p.get("id"), int)}
    picks = ((snapshot or {}).get("squad_snapshot") or {}).get("picks") or []
    owned = [pick.get("element") for pick in picks if isinstance(pick, dict)]
    outs = [out for out, _ in pairs]
    ins = [incoming for _, incoming in pairs]
    if len(set(outs)) != len(outs) or len(set(ins)) != len(ins):
        return invalid("Each player can only be moved once in a plan.")
    for out, incoming in pairs:
        if out not in owned:
            return invalid("You can only sell players in your saved squad.")
        if incoming in owned:
            return invalid(f"{players.get(incoming, {}).get('web_name', 'That player')} is already in your squad.")
        player_in, player_out = players.get(incoming), players.get(out)
        if not player_in or not player_out:
            return invalid("A planned player is missing from the FPL catalog; refresh FPL data.")
        if player_in.get("element_type") != player_out.get("element_type"):
            return invalid(f"{player_in.get('web_name')} does not play the same position as {player_out.get('web_name')}.")
        if not _available(player_in):
            return invalid(f"{player_in.get('web_name')} is not fully available according to FPL.")
    new_squad = [dict(zip(outs, ins)).get(pid, pid) for pid in owned]
    clubs = {}
    for pid in new_squad:
        team = players.get(pid, {}).get("team")
        clubs[team] = clubs.get(team, 0) + 1
    over = [team for team, count in clubs.items() if count > CLUB_LIMIT]
    if over:
        return invalid("That plan puts more than three players from one club in your squad.")
    prices = private.get("prices") or {}
    sold = sum(int(prices.get(out, {}).get("selling_price", -10**6)) for out in outs)
    bought = sum(int(players[incoming].get("now_cost") or 0) for incoming in ins)
    if sold < 0:
        return invalid("A selling price is missing from the account capture; recapture your FPL data.")
    budget_left = int(private.get("bank", 0)) + sold - bought
    if budget_left < 0:
        return invalid(f"Over budget by £{-budget_left / 10:.1f}m (selling prices plus bank).")

    free = private.get("free_transfers")
    hit_cost = int(private.get("hit_cost") or 4)
    paid = 0 if free == "unlimited" else max(0, len(pairs) - int(free or 0))
    hit_points = paid * hit_cost

    base = lineup.suggest(snapshot, catalog, private, freshness, now)
    planned_snapshot = copy.deepcopy(snapshot)
    swap = dict(zip(outs, ins))
    for pick in planned_snapshot["squad_snapshot"]["picks"]:
        if pick.get("element") in swap:
            pick["element"] = swap[pick["element"]]
            pick["is_captain"] = pick["is_vice_captain"] = False
    planned = lineup.suggest(planned_snapshot, catalog, private, freshness, now)
    if planned.get("state") != "ready" or base.get("state") != "ready":
        return invalid((planned if planned.get("state") != "ready" else base).get("reason", "The lineup cannot be built."))
    xi_delta = round(planned["xi_estimate_total"] - base["xi_estimate_total"], 2)
    return {"state": "ready", "lineup": planned, "summary": {
        "transfers": [{"out": {"id": out, "name": players[out].get("web_name"), "selling_price": prices[out]["selling_price"]},
                       "in": {"id": incoming, "name": players[incoming].get("web_name"), "price": players[incoming].get("now_cost")}}
                      for out, incoming in pairs],
        "budget_left": budget_left, "free_transfers": free, "paid_transfers": paid, "hit_points": hit_points,
        "xi_delta": xi_delta, "net_delta": round(xi_delta - hit_points, 2),
        "method": "Next-gameweek FPL estimate only (ep_next), minus any hit. Longer-term value is not modelled.",
    }}
