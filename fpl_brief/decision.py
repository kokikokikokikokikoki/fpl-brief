"""Auditable, deterministic decision gates for the FPL desk."""

from datetime import datetime, timezone

from .jev import status as jev_status


def parse_time(value):
    """Return a UTC timestamp for an FPL ISO value, or None when absent/invalid."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def snapshot_freshness(snapshot, stale_after_hours, now=None):
    current = now or datetime.now(timezone.utc)
    generated = parse_time((snapshot or {}).get("generated_at_utc"))
    if not snapshot or not snapshot.get("generated_at_utc"):
        return {"stale": True, "age_hours": None, "message": "Snapshot time is unavailable."}
    if not generated:
        return {"stale": True, "age_hours": None, "message": "Snapshot time is invalid."}
    age_hours = max(0, (current - generated).total_seconds() / 3600)
    return {
        "stale": age_hours > stale_after_hours,
        "age_hours": round(age_hours, 1),
        "message": f"Snapshot is {age_hours:.1f} hours old." if age_hours > stale_after_hours else "Snapshot is current.",
    }


def assess(snapshot, config, now=None):
    """Return a rules-only next decision, or block decisions when facts are unsafe."""
    current = now or datetime.now(timezone.utc)
    snapshot = snapshot or {}
    freshness = snapshot_freshness(snapshot, config.get("stale_after_hours", 8), current)
    picks = snapshot.get("squad_snapshot", {}).get("picks", [])
    next_event = snapshot.get("events", {}).get("next") or {}
    deadline = parse_time(next_event.get("deadline_time"))
    blockers = []
    if freshness["stale"]:
        blockers.append("Refresh the public snapshot before deciding.")
    if len(picks) != 15:
        blockers.append("The public squad snapshot is incomplete.")
    if not deadline:
        blockers.append("The next FPL deadline is unavailable.")
    elif deadline <= current:
        blockers.append("The next FPL deadline has passed.")
    if snapshot.get("warnings"):
        blockers.append("The snapshot has collection warnings that need review.")

    availability = snapshot.get("availability", [])
    if blockers:
        recommendation = {
            "action": "Pause transfer and lineup recommendations.",
            "why": blockers[0],
            "alternative": "Use the last snapshot only as discussion context.",
            "what_would_change": "A current, complete snapshot before the deadline.",
        }
        state = "blocked"
    elif availability:
        player = availability[0]
        name = player.get("name") or "the flagged player"
        chance = player.get("chance")
        chance_text = f"FPL lists {chance}% availability." if chance is not None else "FPL has flagged their availability."
        recommendation = {
            "action": f"Investigate {name} before committing the transfer.",
            "why": chance_text,
            "alternative": "Hold the transfer until official team news is clearer.",
            "what_would_change": "Confirmed availability, minutes news, or a deadline-driven need to act.",
        }
        state = "ready"
    else:
        recommendation = {
            "action": "Hold and preserve flexibility.",
            "why": "The public squad has no current FPL availability alerts.",
            "alternative": "Make one realistic move only after checking price, free transfers, and team news.",
            "what_would_change": "New official availability news, a fixture change, or confirmed manager inputs.",
        }
        state = "ready"

    return {
        "schema_version": 1,
        "mode": "rules-only",
        "status": state,
        "snapshot_status": freshness,
        "deadline_utc": next_event.get("deadline_time"),
        "blockers": blockers,
        "recommendation": recommendation,
        "unconfirmed_inputs": [
            "Free transfers and selling prices are not in the public snapshot.",
            "Rivals' unsubmitted moves and captain choices are unavailable.",
        ],
        "jev": jev_status(config),
    }
