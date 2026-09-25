"""Load Overseer-captured FPL account data (selling prices, transfers, chips).

The file is captured read-only from the manager's own signed-in browser session and
kept in the gitignored ``local/`` directory. No credentials are stored or used here.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .decision import parse_time

SCHEMA_VERSION = 1
DEFAULT_STALE_AFTER_HOURS = 24
IMPORT_HINT = ("Sign in to FPL in the Claude browser pane and ask Claude to capture your team data "
               "into local/private_team.json.")


def _int(value, minimum=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _captured_time(value):
    """Parse an ISO capture time that carries an explicit timezone; naive times are rejected."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def disabled():
    """Summary used when the server is reachable beyond this machine: no account values are served."""
    return _unavailable("disabled", "FPL account data is only shown when the dashboard is bound to this machine (localhost).")


def _unavailable(state, message, captured=None, now=None):
    summary = {"state": state, "message": message, "usable": False, "captured_at_utc": None, "age_hours": None}
    if captured:
        summary["captured_at_utc"] = captured.isoformat()
        summary["age_hours"] = round((now - captured).total_seconds() / 3600, 1)
    return summary


def _parse(record):
    """Return (captured, picks, transfers, chips) or raise ValueError for any unexpected shape."""
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported schema version")
    captured = _captured_time(record.get("captured_at_utc"))
    my_team = record.get("my_team")
    if not captured or not _int(record.get("team_id"), 1) or not isinstance(my_team, dict):
        raise ValueError("missing team, capture time, or account data")
    picks = my_team.get("picks")
    if not isinstance(picks, list) or len(picks) != 15:
        raise ValueError("the account squad must contain 15 picks")
    prices = {}
    for pick in picks:
        if not isinstance(pick, dict) or not all(_int(pick.get(key), minimum) for key, minimum in
                                                 (("element", 1), ("position", 1), ("selling_price", 0), ("purchase_price", 0))):
            raise ValueError("a pick has an invalid player or price")
        if pick["element"] in prices:
            raise ValueError("the account squad repeats a player")
        prices[pick["element"]] = {"selling_price": pick["selling_price"], "purchase_price": pick["purchase_price"]}
    transfers = my_team.get("transfers")
    if not isinstance(transfers, dict) or not all(_int(transfers.get(key)) for key in ("bank", "made", "cost", "value")):
        raise ValueError("transfer state is invalid")
    limit, status = transfers.get("limit"), transfers.get("status")
    unlimited = limit is None or status == "unlimited"
    if not unlimited and not _int(limit):
        raise ValueError("free transfer limit is invalid")
    if not isinstance(my_team.get("chips"), list):
        raise ValueError("chip state is invalid")
    chips = []
    for chip in my_team["chips"]:
        played = chip.get("played_by_entry") if isinstance(chip, dict) else None
        if (not isinstance(chip, dict) or not isinstance(chip.get("name"), str) or not isinstance(chip.get("status_for_entry"), str)
                or not isinstance(played, list) or not all(_int(gw, 1) for gw in played)):
            raise ValueError("a chip record is invalid")
        chips.append({"name": chip["name"], "status": chip["status_for_entry"], "played_gameweeks": played,
                      "window": [chip.get("start_event"), chip.get("stop_event")],
                      "pending": chip.get("is_pending") is True})
    free = "unlimited" if unlimited else max(limit - transfers["made"], 0)
    lineup = [{key: pick.get(key) for key in ("element", "position", "is_captain", "is_vice_captain")} for pick in picks]
    account = {"lineup": lineup, "free_transfers": free, "transfers_made": transfers["made"], "bank": transfers["bank"],
               "hit_cost": transfers["cost"], "team_value": transfers["value"], "prices": prices, "chips": chips}
    return captured, record["team_id"], account


def load(path, config, snapshot, now=None):
    """Summarize the private team file for display and Candidate Lens use.

    States: missing, invalid, mismatch, stale, ready. Only ``ready`` data is usable for
    affordability; ``stale`` data is shown for context with its age.
    """
    current = now or datetime.now(timezone.utc)
    file = Path(path)
    if not file.is_file():
        return _unavailable("missing", "No FPL account data captured. " + IMPORT_HINT)
    try:
        captured, team_id, account = _parse(json.loads(file.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return _unavailable("invalid", f"Captured FPL account data is unusable ({error}). " + IMPORT_HINT)
    if captured > current:
        return _unavailable("invalid", "Captured FPL account data has a future capture time. " + IMPORT_HINT)
    if team_id != (config or {}).get("team_id"):
        return _unavailable("mismatch", "Captured FPL account data belongs to a different team ID. " + IMPORT_HINT, captured, current)
    public_ids = {pick.get("element") for pick in ((snapshot or {}).get("squad_snapshot") or {}).get("picks", []) if isinstance(pick, dict)}
    if public_ids != set(account["prices"]):
        return _unavailable("mismatch", "Your squad differs between the public snapshot and the captured account data; "
                            "refresh FPL data and recapture before relying on either.", captured, current)
    summary = _unavailable("ready", "", captured, current)
    summary.update(account)
    events = (snapshot or {}).get("events") or {}
    deadlines = [parse_time((events.get(key) or {}).get("deadline_time")) for key in ("current", "next")]
    known = [deadline for deadline in deadlines if deadline]
    passed = any(captured < deadline <= current for deadline in known)
    limit = (config or {}).get("private_stale_after_hours", DEFAULT_STALE_AFTER_HOURS)
    too_old = (current - captured).total_seconds() > limit * 3600
    if not known or passed or too_old:
        summary["state"] = "stale"
        reason = ("FPL deadlines are unavailable, so freshness cannot be confirmed" if not known
                  else "An FPL deadline has passed since capture" if passed
                  else f"Captured account data is older than {limit} hours")
        summary["message"] = reason + "; free transfers, bank and prices may have changed. " + IMPORT_HINT
    else:
        summary["usable"] = True
        summary["message"] = "From your FPL account (read-only capture). Not transfer advice."
    return summary
