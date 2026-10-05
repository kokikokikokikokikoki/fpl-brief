"""Selling prices and FPL's own price-change predictor (research/fpl-maths.md §5).

Pure functions. Prices are in £0.1m integers, as FPL sends them. The predictor fields
(``price_change_*`` in bootstrap-static, new in 2026/27) are FPL's own guide, never a
certainty; nothing here drives the transfer planner, it only adds notes.
"""

import math
from datetime import datetime, timedelta, timezone

from .decision import parse_time

GUIDE = "FPL's own predictor, a guide only."
THRESHOLD = 100.0          # price_change_percent above +100 (or below -100) means a change is expected at the next update
ITB_VALUE = 0.08           # points per £1m in the bank; same value as optimise.ITB_VALUE (research §3)
STEP = 1                   # one price change is £0.1m
UPDATE_HOUR_UTC = 1        # FPL updates prices overnight UK time; 01:00 UTC is an approximation for counting updates
DIRECTIONS = ("rise", "fall", "steady", "unknown")


def selling_price(bought, now):
    """FPL selling price in £0.1m: half of any profit (rounded down), falls passed on in full."""
    return bought + (now - bought) // 2 if now > bought else now


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value):
    """FPL sends percentages as decimal strings ("100.4"); accept numbers too. None when unusable."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value) if isinstance(value, (int, float, str)) else None
    except ValueError:
        return None
    return number if number is not None and math.isfinite(number) else None


def _projections(raw):
    rows = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not _int(item.get("offset")) or not 0 <= item["offset"] <= 2:
            continue
        projected = _number(item.get("projected_percent"))
        if projected is None:
            continue
        rows.append({"offset": item["offset"], "projected_percent": projected,
                     "likelihood": item.get("likelihood") if _int(item.get("likelihood")) else None})
    return sorted(rows, key=lambda row: row["offset"])


def _crossed(percent):
    return "rise" if percent > THRESHOLD else "fall" if percent < -THRESHOLD else None


def outlook(player):
    """Rise, fall, steady or unknown from FPL's predictor, with likelihood, timing and calibration.

    ``expected_at_update`` is 1 for the next overnight update, 2 or 3 for the projections' later
    offsets, and None when no change is projected.
    """
    player = player if isinstance(player, dict) else {}
    percent = _number(player.get("price_change_percent"))
    projections = _projections(player.get("price_change_projections"))
    calibrating = player.get("price_change_calibrating") is True
    locked = player.get("price_change_locked_until") if isinstance(player.get("price_change_locked_until"), str) else None
    result = {"direction": "unknown", "percent": percent, "expected_at_update": None, "likelihood": None,
              "calibrating": calibrating, "locked_until": locked, "next_change": None, "guide": GUIDE}
    if percent is None and not projections:
        result["label"] = "No FPL price prediction available."
        return result
    direction, update, likelihood = "steady", None, projections[0]["likelihood"] if projections else None
    if percent is not None and _crossed(percent):
        direction, update = _crossed(percent), 1
    else:
        for row in projections:
            if _crossed(row["projected_percent"]):
                direction, update, likelihood = _crossed(row["projected_percent"]), row["offset"] + 1, row["likelihood"]
                break
    result.update(direction=direction, expected_at_update=update, likelihood=likelihood)
    if locked:
        result["next_change"] = f"No change before {locked}."
    elif update:
        result["next_change"] = "At the next overnight price update." if update == 1 else f"In about {update} overnight price updates."
    words = {"rise": "Predicted to rise £0.1m", "fall": "Predicted to fall £0.1m", "steady": "No change predicted in the next 3 updates"}
    label = words[direction] + (f" ({result['next_change'][0].lower()}{result['next_change'][1:-1]})" if update and not locked else "")
    if likelihood is not None and direction != "steady":
        label += f", FPL likelihood score {likelihood}"
    if calibrating:
        label += "; FPL is still calibrating this prediction"
    result["label"] = f"{label}. {GUIDE}"
    return result


def updates_before(now, deadline):
    """Approximate count of overnight price updates between now and the deadline."""
    if not isinstance(now, datetime) or not isinstance(deadline, datetime) or deadline <= now:
        return 0
    first = now.astimezone(timezone.utc).replace(hour=UPDATE_HOUR_UTC, minute=0, second=0, microsecond=0)
    if first <= now:
        first += timedelta(days=1)
    return 0 if first >= deadline else int((deadline - first).total_seconds() // 86400) + 1


def _before_deadline(view, window, deadline):
    if view["direction"] not in ("rise", "fall") or not view["expected_at_update"] or view["expected_at_update"] > window:
        return False
    locked = parse_time(view["locked_until"])
    return not (locked and deadline and locked >= deadline)


def early_move_value():
    """Points value of £0.1m kept in the bank (research §5): itb_value × 0.1."""
    return round(ITB_VALUE * STEP / 10, 3)


def buy_note(player, window, deadline):
    """Note for a buy predicted to rise before the deadline, or None."""
    if not isinstance(player, dict) or not player or not _before_deadline(outlook(player), window, deadline):
        return None
    value = early_move_value()
    return {"player_id": player.get("id"), "kind": "buy_rise", "value_points": value,
            "text": (f"Early-move note: {player.get('web_name') or 'This player'} is predicted to rise before the deadline "
                     f"({GUIDE[:-1]}). Buying earlier could save £0.1m, about {value:.2f} points; a note, not a reason to move.")}


def sell_note(player, purchase, window, deadline):
    """Note for a sell predicted to fall before the deadline, or None. Skipped when the fall would not
    change the selling price (purchase price known and the drop only eats unrealised half-profit)."""
    if not isinstance(player, dict) or not player or not _before_deadline(outlook(player), window, deadline):
        return None
    now_cost = player.get("now_cost")
    if _int(purchase) and _int(now_cost) and selling_price(purchase, now_cost) == selling_price(purchase, now_cost - STEP):
        return None
    value = early_move_value()
    return {"player_id": player.get("id"), "kind": "sell_fall", "value_points": value,
            "text": (f"Early-move note: {player.get('web_name') or 'This player'} is predicted to fall before the deadline "
                     f"({GUIDE[:-1]}). Selling earlier would keep £0.1m of selling price, about {value:.2f} points; "
                     "a note, not a reason to move.")}


def early_move_notes(moves, players, private=None, deadline=None, now=None):
    """One-line notes for planned (out, in) moves: a buy predicted to rise, or a sell predicted to fall,
    before the deadline. Notes only; never used to choose moves."""
    window = updates_before(now or datetime.now(timezone.utc), deadline)
    prices = (private.get("prices") or {}) if isinstance(private, dict) and private.get("usable") is True else {}
    notes = []
    for out, incoming in moves:
        notes.append(buy_note(players.get(incoming), window, deadline))
        notes.append(sell_note(players.get(out), (prices.get(out) or {}).get("purchase_price"), window, deadline))
    return [note for note in notes if note]


def marker(player, window=0, deadline=None):
    """The outlook fields the dashboard markers need, plus whether the change is expected before the deadline."""
    view = outlook(player)
    compact = {key: view[key] for key in ("direction", "expected_at_update", "likelihood", "calibrating", "label")}
    compact["before_deadline"] = _before_deadline(view, window, deadline)
    return compact


def squad_view(snapshot, catalog, private, now=None):
    """Prices for the 15 owned players. Selling prices need usable account data; otherwise public prices only."""
    players = {p.get("id"): p for p in (catalog or {}).get("players", []) if isinstance(p, dict) and _int(p.get("id"))}
    picks = [pick for pick in (((snapshot or {}).get("squad_snapshot") or {}).get("picks") or []) if isinstance(pick, dict)]
    picks.sort(key=lambda pick: pick.get("position") if _int(pick.get("position")) else 99)
    usable = isinstance(private, dict) and private.get("usable") is True
    prices = (private.get("prices") or {}) if usable else {}
    deadline = parse_time((((snapshot or {}).get("events") or {}).get("next") or {}).get("deadline_time"))
    window = updates_before(now or datetime.now(timezone.utc), deadline)
    rows, mismatches = [], []
    for pick in picks:
        pid = pick.get("element")
        player = players.get(pid) or {}
        current = player.get("now_cost") if _int(player.get("now_cost")) else None
        view = marker(player, window, deadline)
        row = {"id": pid, "name": player.get("web_name") or f"Player {pid}", "position": player.get("element_type") or pick.get("element_type"),
               "current": current, "purchase": None, "selling": None, "formula_selling": None, "profit": None,
               "if_rise": None, "if_fall": None, "rise_earns_nothing": None, "outlook": view}
        account = prices.get(pid) if isinstance(prices, dict) else None
        if account and _int(account.get("purchase_price")) and _int(account.get("selling_price")):
            bought, selling = account["purchase_price"], account["selling_price"]
            row.update(purchase=bought, selling=selling, profit=selling - bought)
            if current is not None:
                formula = selling_price(bought, current)
                row.update(formula_selling=formula,
                           if_rise=selling_price(bought, current + STEP) - formula,
                           if_fall=selling_price(bought, current - STEP) - formula)
                row["rise_earns_nothing"] = row["if_rise"] == 0
                if formula != selling:
                    mismatches.append({"id": pid, "name": row["name"], "account": selling, "formula": formula})
        rows.append(row)
    result = {"state": "account" if usable else "public", "players": rows, "guide": GUIDE,
              "updates_before_deadline": window,
              "method": ("Selling price = purchase price + half of any rise, rounded down to £0.1m; falls are passed on in full. "
                         "So a single +£0.1m rise earns nothing until there's a second one. Rise and fall markers are "
                         f"{GUIDE} The number of price updates before the deadline is approximate (it assumes one overnight update a day).")}
    if usable:
        checked = [row for row in rows if row["formula_selling"] is not None]
        result.update(captured_at_utc=private.get("captured_at_utc"), bank=private.get("bank"),
                      selling_total=sum(row["selling"] for row in rows if _int(row["selling"])),
                      profit_total=sum(row["profit"] for row in rows if _int(row["profit"])),
                      cross_check={"checked": len(checked), "mismatches": mismatches,
                                   "note": ("Account selling prices were not checked against the formula." if not checked else
                                            "Account selling prices match the formula at today's prices." if not mismatches else
                                            "Some account selling prices differ from the formula at today's prices; a price may have "
                                            "changed since the capture, so recapture to be sure. The account value is shown.")})
    else:
        message = private.get("message") if isinstance(private, dict) and isinstance(private.get("message"), str) else ""
        result["message"] = ("Selling prices need a fresh capture of your FPL account; public prices only. " + message).strip()
    return result
