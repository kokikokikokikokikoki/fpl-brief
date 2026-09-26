#!/usr/bin/env python3
"""Local, read-only dashboard for the FPL Brief snapshot."""

import base64
import binascii
import hmac
import json
import math
import mimetypes
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from fpl_brief.config import load as load_config
from fpl_brief.decision import assess, snapshot_freshness
from fpl_brief.candidates import lens
from fpl_brief import lineup as lineup_helper
from fpl_brief import plan as transfer_plan
from fpl_brief import private_team
from fpl_brief.research import evidence_status, load_packet
from fpl_brief.storage import read_json

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "dashboard"
STATIC_DIST = STATIC / "dist"
LOCAL = ROOT / "local"
PRIVATE_TEAM = LOCAL / "private_team.json"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
MAX_IMPORT_BYTES = 64 * 1024
# Optional password for hosted deployments (HTTP Basic over HTTPS). Unset locally.
AUTH_WINDOW_SECONDS = 600
AUTH_MAX_FAILURES = 10
AUTH_MAX_CLIENTS = 2048
AUTH_FAILURES = {}
# Across all clients: caps total guessing even if per-client identity is evaded (may briefly lock everyone out).
AUTH_GLOBAL_MAX_FAILURES = 100
AUTH_GLOBAL_FAILURES = []
HEALTH_LOGGED = 0
AUTH_LOCK = threading.Lock()


def auth_settings(environ=None):
    """Return (password, required) from DASHBOARD_PASSWORD and REQUIRE_PASSWORD."""
    environ = os.environ if environ is None else environ
    return environ.get("DASHBOARD_PASSWORD") or "", environ.get("REQUIRE_PASSWORD") == "1"


def basic_password(header):
    """Extract the password from an HTTP Basic Authorization header, or None."""
    if not header or not header[:6].lower() == "basic ":
        return None
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return decoded.split(":", 1)[1] if ":" in decoded else None
JOBS = {}
MAX_PLANS = 4
MISSING_BUNDLE_MESSAGE = (
    "Dashboard frontend bundle is missing (dashboard/dist/index.html).\n"
    "Build it with: npm ci --prefix dashboard && npm run build --prefix dashboard\n"
    "The JSON API under /api/ is still available.\n"
)


def default_plans(snapshot):
    picks = [pick.get("element") for pick in snapshot.get("squad_snapshot", {}).get("picks", [])]
    next_event = snapshot.get("events", {}).get("next") or {}
    current = snapshot.get("events", {}).get("current") or {}
    base = (next_event or current).get("id")
    return [{"id": "hold", "name": "Hold / use 1 FT", "target_gw": base, "players": picks,
             "notes": "Baseline: edit only after deciding the transfer."}]


def load_plans(snapshot):
    return default_plans(snapshot)

def snapshot_status(snapshot, config, now=None):
    return snapshot_freshness(snapshot, config.get("stale_after_hours", 8), now)


def player_map(catalog):
    return {player["id"]: player for player in catalog.get("players", []) if player.get("id")}


def validate_plan(plan, catalog):
    """Validate a locally saved scenario against the current player catalog."""
    if not isinstance(plan, dict):
        raise ValueError("Scenario must be an object")
    if not isinstance(plan.get("name"), str) or not plan["name"].strip():
        raise ValueError("Scenario name is required")
    if len(plan["name"]) > 80:
        raise ValueError("Scenario name must be 80 characters or fewer")
    target_gw = plan.get("target_gw")
    if isinstance(target_gw, bool) or not isinstance(target_gw, int) or target_gw < 1:
        raise ValueError("Target gameweek must be a positive integer")
    player_ids = plan.get("players", [])
    if not isinstance(player_ids, list) or any(isinstance(player_id, bool) or not isinstance(player_id, int) or player_id < 1 for player_id in player_ids):
        raise ValueError("Players must be a list of FPL player IDs")
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("A scenario cannot include the same player twice")
    unknown = [player_id for player_id in player_ids if player_id not in player_map(catalog)]
    if unknown:
        raise ValueError("Scenario includes player IDs that are not in the current FPL catalog")


def research_result(config, snapshot=None, now=None):
    snapshot = snapshot if snapshot is not None else read_json(ROOT / "data" / "latest.json", default=None)
    result = evidence_status(load_packet(ROOT / "data" / "research_packet.json"), config["research_stale_after_hours"], now)
    result["snapshot_status"] = snapshot_status(snapshot, config, now)
    return result


CHIP_LABELS = {
    "wildcard": "Wildcard", "wildcard2": "Wildcard",
    "freehit": "Free Hit", "freehit2": "Free Hit",
    "bboost": "Bench Boost", "bboost2": "Bench Boost",
    "3xc": "Triple Captain", "3xc2": "Triple Captain",
}
CHIP_ORDER = ("Wildcard", "Free Hit", "Bench Boost", "Triple Captain")
PLAYER_STATUS = {
    "a": "Available", "d": "Doubtful", "i": "Injured", "s": "Suspended",
    "u": "Unavailable", "n": "Not in FPL",
}


def _chip_key(*values):
    for value in values:
        if isinstance(value, str) and value.strip().lower() in CHIP_LABELS:
            return CHIP_LABELS[value.strip().lower()]
    return None


def _unknown_chip_label(rule, ordinal=None):
    """Return a stable display label for an official rule we cannot interpret."""
    raw_name = rule.get("name") if isinstance(rule, dict) else None
    if isinstance(raw_name, str) and raw_name.strip():
        return " ".join(raw_name.split())[:80]
    identifier = rule.get("id") if isinstance(rule, dict) else None
    if isinstance(identifier, int) and not isinstance(identifier, bool) and identifier > 0:
        return f"Unrecognized chip (ID {identifier})"
    if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0:
        return f"Unrecognized official chip rule (rule {ordinal})"
    return "Unrecognized official chip rule"


def _finite_number(value):
    if isinstance(value, bool) or value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def chip_ledger(snapshot, stale=False):
    """Reconcile official bootstrap chip windows with recorded manager plays."""
    definitions = snapshot.get("chip_rules") if isinstance(snapshot, dict) else None
    manager = snapshot.get("manager") if isinstance(snapshot, dict) else None
    plays = manager.get("chips") if isinstance(manager, dict) else None
    normalized_plays = {name: [] for name in CHIP_ORDER}
    official_unknown_names = {}
    official_unknown_labels = []
    if isinstance(definitions, list):
        for rule_index, rule in enumerate(definitions, start=1):
            if not isinstance(rule, dict) or _chip_key(rule.get("name")) or _chip_key(rule.get("id")):
                continue
            raw_name = rule.get("name")
            safe_name = _unknown_chip_label(rule, rule_index)
            official_unknown_labels.append(safe_name)
            if isinstance(raw_name, str) and raw_name.strip():
                official_unknown_names[raw_name.strip().lower()] = safe_name
            normalized_plays.setdefault(safe_name, [])
    history_unknown = False
    if isinstance(plays, list):
        for play in plays:
            label = _chip_key(play.get("name")) if isinstance(play, dict) else None
            if label is None and isinstance(play, dict) and isinstance(play.get("name"), str):
                label = official_unknown_names.get(play["name"].strip().lower())
            gameweek = play.get("event") if isinstance(play, dict) else None
            if label is None or isinstance(gameweek, bool) or not isinstance(gameweek, int) or not 1 <= gameweek <= 38:
                history_unknown = True
                continue
            normalized_plays[label].append(gameweek)

    unavailable_reason = (
        "FPL snapshot is stale; recorded plays are shown from this snapshot, but availability is unknown."
        if stale else "Official chip rules are missing or invalid; recorded plays are shown from this snapshot, but availability is unknown."
    )

    def unknown_rows(reason):
        rows = []
        labels = [*CHIP_ORDER, *dict.fromkeys(official_unknown_labels)]
        for label in labels:
            used = sorted(normalized_plays.get(label, []))
            row_reason = reason
            if len(used) != len(set(used)):
                row_reason = "Duplicate plays appear in manager history; availability is unknown."
            rows.append({"name": label, "state": "unknown", "used_count": len(used),
                         "used_gameweeks": used, "used_source": "recorded in snapshot" if used else "",
                         "reason": row_reason})
        if history_unknown:
            rows.append({"name": "Unrecognized recorded chip", "state": "unknown",
                         "reason": "Manager history contains a chip or gameweek that cannot be safely identified."})
        return rows

    if stale or not isinstance(definitions, list) or not definitions or not isinstance(plays, list):
        reason = unavailable_reason if isinstance(plays, list) else "Manager chip history is unavailable; availability is unknown."
        rows = unknown_rows(reason)
        state = "partial" if any(row.get("used_count", 0) for row in rows) or history_unknown else "unknown"
        return {"state": state, "reason": unavailable_reason, "chips": rows}
    event_meta = snapshot.get("events") if isinstance(snapshot.get("events"), dict) else {}
    event = event_meta.get("next") or event_meta.get("current")
    current_gw = event.get("id") if isinstance(event, dict) else None
    if isinstance(current_gw, bool) or not isinstance(current_gw, int) or not 1 <= current_gw <= 38:
        reason = "Recorded plays are shown from this snapshot; current chip availability cannot be determined."
        rows = unknown_rows(reason)
        return {"state": "partial" if any(row.get("used_count", 0) for row in rows) else "unknown",
                "reason": "The next relevant gameweek is unavailable, so current chip availability cannot be determined.",
                "chips": rows}

    windows = {name: [] for name in CHIP_ORDER}
    invalid = set()
    seen_ids = {}
    for rule_index, rule in enumerate(definitions, start=1):
        if not isinstance(rule, dict):
            label = _unknown_chip_label({}, rule_index)
            invalid.add(label)
            windows[label] = []
            continue
        named_label = _chip_key(rule.get("name"))
        id_label = _chip_key(rule.get("id"))
        label = named_label or id_label
        if label is None:
            safe_name = _unknown_chip_label(rule, rule_index)
            invalid.add(safe_name)
            windows[safe_name] = []
            continue
        start, stop, count = rule.get("start_event"), rule.get("stop_event"), rule.get("number")
        identifier = rule.get("id")
        if named_label and id_label and named_label != id_label:
            invalid.update((named_label, id_label))
            continue
        if (isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 1 or identifier in seen_ids
                or any(isinstance(value, bool) or not isinstance(value, int) for value in (start, stop, count))
                or not 1 <= start <= stop <= 38 or count < 1):
            invalid.add(label)
            if isinstance(identifier, int) and not isinstance(identifier, bool) and identifier in seen_ids:
                invalid.update((label, seen_ids[identifier]))
            continue
        seen_ids[identifier] = label
        windows[label].append({"start": start, "stop": stop, "count": count, "id": identifier})
    for label, ranges in windows.items():
        ordered = sorted(ranges, key=lambda row: (row["start"], row["stop"]))
        if any(left["stop"] >= right["start"] for left, right in zip(ordered, ordered[1:])):
            invalid.add(label)

    rows = []
    for label in [*CHIP_ORDER, *(name for name in windows if name not in CHIP_ORDER)]:
        ranges = sorted(windows[label], key=lambda row: row["start"])
        if label in invalid or not ranges:
            reason = ("Unrecognized official chip; its interpretation and availability are unknown."
                      if label not in CHIP_ORDER else
                      "Official definitions are missing, invalid, or overlapping; recorded plays are shown from this snapshot.")
            rows.append({"name": label, "state": "unknown", "used_count": len(normalized_plays.get(label, [])),
                         "used_gameweeks": sorted(normalized_plays.get(label, [])),
                         "used_source": "recorded in snapshot" if normalized_plays.get(label) else "",
                         "reason": reason})
            continue
        used = sorted(normalized_plays[label])
        if len(used) != len(set(used)):
            rows.append({"name": label, "state": "unknown", "used_count": len(used), "used_gameweeks": used, "used_source": "recorded in snapshot", "reason": "History records the same chip more than once in a gameweek."})
            continue
        uses_by_window = {index: 0 for index in range(len(ranges))}
        unmatched = []
        for gameweek in used:
            matches = [index for index, row in enumerate(ranges) if row["start"] <= gameweek <= row["stop"]]
            if len(matches) != 1:
                unmatched.append(gameweek)
            else:
                uses_by_window[matches[0]] += 1
        if unmatched or any(uses_by_window[index] > row["count"] for index, row in enumerate(ranges)):
            rows.append({"name": label, "state": "unknown", "used_count": len(used), "used_gameweeks": used, "used_source": "recorded in snapshot", "reason": "Recorded plays do not reconcile with the official chip windows/counts."})
            continue
        active = [index for index, row in enumerate(ranges) if row["start"] <= current_gw <= row["stop"]]
        future = [index for index, row in enumerate(ranges) if row["start"] > current_gw]
        current_left = sum(ranges[index]["count"] - uses_by_window[index] for index in active)
        future_left = sum(ranges[index]["count"] - uses_by_window[index] for index in future)
        rows.append({"name": label, "state": "known", "used_count": len(used), "used_gameweeks": used, "used_source": "manager history",
                     "available_now": current_left, "future_count": future_left,
                     "future_windows": [{"start_event": ranges[index]["start"], "stop_event": ranges[index]["stop"],
                                         "remaining": ranges[index]["count"] - uses_by_window[index]} for index in future],
                     "season_total": sum(row["count"] for row in ranges)})
    if history_unknown:
        rows.append({"name": "Unrecognized recorded chip", "state": "unknown", "reason": "Manager history contains a chip or gameweek that cannot be safely identified."})
    return {"state": "known" if all(row["state"] == "known" for row in rows) and not history_unknown else "partial",
            "gameweek": current_gw, "reason": "Official FPL bootstrap chip windows reconciled with recorded manager history.", "chips": rows}


def apply_private_inputs(decision, private):
    """Replace the public-snapshot caveat when usable account data confirms transfers and prices."""
    if not (isinstance(private, dict) and private.get("usable") is True):
        return decision
    inputs = decision.get("unconfirmed_inputs", [])
    decision["unconfirmed_inputs"] = [item for item in inputs if not item.startswith("Free transfers and selling prices")]
    decision["confirmed_inputs"] = [
        f"Free transfers ({private['free_transfers']}), bank and selling prices come from your FPL account, captured {private['captured_at_utc']}."]
    return decision


def build_team_decision(snapshot, catalog, research, freshness):
    """Build an auditable, read-only view model from the current saved inputs."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    catalog = catalog if isinstance(catalog, dict) else {}
    players = {player.get("id"): player for player in catalog.get("players", [])
               if isinstance(player, dict) and isinstance(player.get("id"), int)}
    teams = {team.get("id"): team for team in catalog.get("teams", [])
             if isinstance(team, dict) and isinstance(team.get("id"), int)}
    squad_snapshot = snapshot.get("squad_snapshot")
    picks = squad_snapshot.get("picks", []) if isinstance(squad_snapshot, dict) else []
    if not isinstance(picks, list):
        picks = []

    research = research if isinstance(research, dict) else {}
    packet = research.get("packet") if research.get("valid") is True and isinstance(research.get("packet"), dict) else {}
    sources = packet.get("sources", []) if isinstance(packet.get("sources"), list) else []
    summaries = {summary.get("id"): summary for summary in research.get("source_summaries", [])
                 if isinstance(summary, dict) and isinstance(summary.get("id"), str)}
    evidence_by_player = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        excerpts = source.get("excerpts", [])
        summary = summaries.get(source.get("id"), {})
        stale_indexes = set(summary.get("stale_excerpt_indexes", [])) if isinstance(summary, dict) else set()
        if not isinstance(excerpts, list):
            continue
        for index, excerpt in enumerate(excerpts):
            player_id = excerpt.get("player_id") if isinstance(excerpt, dict) else None
            if isinstance(player_id, bool) or not isinstance(player_id, int) or player_id < 1 or not isinstance(excerpt.get("text"), str) or not excerpt["text"].strip():
                continue
            evidence_by_player.setdefault(player_id, []).append({
                "text": excerpt["text"], "captured_at_utc": excerpt.get("captured_at_utc"),
                "publisher": source.get("publisher"), "title": source.get("title"), "url": source.get("url"),
                "stale": bool(research.get("state") != "ready" or research.get("stale") or summary.get("stale") or index in stale_indexes),
                "verification": "captured, unverified",
            })

    fixture_snapshot = snapshot.get("fixtures")
    fixture_events = fixture_snapshot.get("events", {}) if isinstance(fixture_snapshot, dict) else {}
    if not isinstance(fixture_events, dict):
        fixture_events = {}
    fixture_by_team = {}
    for event_key, fixtures in fixture_events.items():
        try:
            gameweek = int(event_key)
        except (TypeError, ValueError):
            continue
        if not 1 <= gameweek <= 38 or not isinstance(fixtures, list):
            continue
        for fixture in fixtures:
            if not isinstance(fixture, dict):
                continue
            for side, opponent, difficulty_field, venue in (
                ("team_h", "team_a", "team_h_difficulty", "H"),
                ("team_a", "team_h", "team_a_difficulty", "A"),
            ):
                team_id = fixture.get(side)
                opponent_id = fixture.get(opponent)
                if isinstance(team_id, int) and not isinstance(team_id, bool):
                    opponent_team = teams.get(opponent_id, {}) if isinstance(opponent_id, int) and not isinstance(opponent_id, bool) else {}
                    fixture_by_team.setdefault(team_id, []).append({
                        "gameweek": gameweek, "opponent": opponent_team.get("short_name") or "Unknown opponent",
                        "venue": venue, "difficulty": fixture.get(difficulty_field),
                    })
    for team_fixtures in fixture_by_team.values():
        team_fixtures.sort(key=lambda row: row["gameweek"])

    rows = []
    stale_snapshot = bool(freshness.get("stale", True)) if isinstance(freshness, dict) else True
    ordered_picks = [item if isinstance(item, dict) else {} for item in picks]
    for pick in sorted(ordered_picks, key=lambda item: item.get("position") if isinstance(item.get("position"), int) and not isinstance(item.get("position"), bool) else 999):
        player_id = pick.get("element")
        player = players.get(player_id) if isinstance(player_id, int) and not isinstance(player_id, bool) else None
        team = teams.get(player.get("team")) if player and isinstance(player.get("team"), int) else None
        status = PLAYER_STATUS.get(player.get("status")) if player else None
        chance = player.get("chance_of_playing_next_round") if player else None
        valid_chance = chance is None or (isinstance(chance, int) and not isinstance(chance, bool) and 0 <= chance <= 100)
        status_known = status is not None and valid_chance
        risk = bool(player and status_known and (player.get("status") != "a" or (chance is not None and chance < 100)))
        news = player.get("news") if player and isinstance(player.get("news"), str) else ""
        next_step = "Review the current FPL status and source context."
        if stale_snapshot:
            priority = "Snapshot stale"
            reason = "Refresh the public FPL snapshot before treating player status, stats, fixtures or FPL notes as current."
        elif not player:
            priority = "Resolve player data"
            reason = "This saved pick has no matching player in the current FPL catalog."
        elif not status_known:
            priority = "Availability unknown"
            reason = "The FPL status or chance field is missing or invalid; refresh the public snapshot."
        elif risk:
            priority = "Resolve availability"
            reason = f"FPL status: {status}" + (f"; chance of playing next round: {chance}%" if chance is not None else "; chance of playing was not supplied")
        elif news:
            priority = "Review FPL note"
            reason = "FPL provides a player note; it is shown as source text, not a separate medical verdict."
        else:
            minutes = player.get("minutes")
            form = player.get("form")
            total_points = player.get("total_points")
            has_minutes = _finite_number(minutes) and float(minutes) > 0
            has_stats = all(_finite_number(value) for value in (form, total_points))
            has_fixtures = bool(fixture_by_team.get(player.get("team")))
            if not (has_minutes and has_stats and has_fixtures):
                priority = "Not enough current evidence"
                missing = []
                if not has_minutes:
                    missing.append("meaningful minutes")
                if not has_stats:
                    missing.append("form/points stats")
                if not has_fixtures:
                    missing.append("upcoming fixtures")
                reason = "Missing " + ", ".join(missing) + "; no transfer conclusion can be drawn."
                next_step = "Refresh FPL data and check team/player context before deciding."
            else:
                priority = "No official availability flag"
                reason = f"FPL status: {status}" + (f"; chance of playing next round: {chance}%" if chance is not None else "; chance of playing was not supplied")
                next_step = "Availability only; this is not a transfer recommendation. Compare minutes, fixtures and alternatives separately."
        rows.append({
            "id": player_id, "position": pick.get("position"), "name": player.get("web_name") if player else None,
            "team": team.get("short_name") if team else None,
            "role": player.get("element_type") if player else pick.get("element_type"),
            "priority": priority, "reason": reason, "next_step": next_step, "status": status or "Unknown",
            "chance": chance if valid_chance else None, "news": news, "news_added": player.get("news_added") if player else None,
            "minutes": player.get("minutes") if player else None, "form": player.get("form") if player else None,
            "total_points": player.get("total_points") if player else None, "ep_next": player.get("ep_next") if player else None,
            "fixtures": fixture_by_team.get(player.get("team"), [])[:3] if player else [],
            "research": evidence_by_player.get(player_id, []) if isinstance(player_id, int) else [],
        })
    return {"generated_at_utc": snapshot.get("generated_at_utc"), "snapshot_stale": stale_snapshot,
            "snapshot_message": freshness.get("message", "Snapshot freshness is unavailable.") if isinstance(freshness, dict) else "Snapshot freshness is unavailable.", "players": rows,
            "research_state": research.get("state", "missing"),
            "research_age_hours": research.get("research_age_hours"),
            "chips": chip_ledger(snapshot, bool(freshness.get("stale", True)))}


def evaluate_plan(plan, catalog):
    players = player_map(catalog)
    selected = [players[player_id] for player_id in plan.get("players", []) if player_id in players]
    ep = sum(float(player.get("ep_next") or 0) for player in selected)
    cost = sum(int(player.get("now_cost") or 0) for player in selected)
    risks = [player for player in selected if player.get("status") != "a" or (player.get("chance_of_playing_next_round") is not None and player.get("chance_of_playing_next_round") < 100)]
    return {"id": plan.get("id"), "name": plan.get("name", "Untitled scenario"),
            "target_gw": plan.get("target_gw"), "valid_squad_size": len(selected) == 15,
            "squad_size": len(selected), "cost": cost, "ep_next": round(ep, 1),
            "risk_count": len(risks), "risks": [{"id": p["id"], "name": p["web_name"], "status": p.get("status"), "chance": p.get("chance_of_playing_next_round")} for p in risks]}


# Only the fields FPL's my-team data contains are kept from a paste; anything else is dropped.
IMPORT_FIELDS = {
    "pick": ("element", "position", "multiplier", "is_captain", "is_vice_captain", "element_type", "selling_price", "purchase_price"),
    "chip": ("id", "status_for_entry", "played_by_entry", "name", "number", "start_event", "stop_event", "chip_type", "is_pending"),
    "transfers": ("cost", "status", "limit", "made", "bank", "value"),
}


def _plain(value):
    """Keep only plain JSON values FPL uses: numbers, booleans, null, short strings, or integer lists."""
    if value is None or isinstance(value, bool) or (isinstance(value, (int, float)) and math.isfinite(value)):
        return True
    if isinstance(value, str):
        return len(value) <= 64
    return isinstance(value, list) and len(value) <= 64 and all(isinstance(v, int) and not isinstance(v, bool) for v in value)


def whitelist_my_team(raw):
    """Rebuild the pasted my-team object from known fields and plain values only (never stores stray data such as cookies)."""
    keep = lambda item, fields: {key: item[key] for key in fields if key in item and _plain(item[key])} if isinstance(item, dict) else item
    result = {
        "picks": [keep(pick, IMPORT_FIELDS["pick"]) for pick in raw["picks"]] if isinstance(raw["picks"], list) else raw["picks"],
        "chips": [keep(chip, IMPORT_FIELDS["chip"]) for chip in raw["chips"]] if isinstance(raw["chips"], list) else raw["chips"],
        "transfers": keep(raw["transfers"], IMPORT_FIELDS["transfers"]),
    }
    if isinstance(raw.get("picks_last_updated"), str):
        result["picks_last_updated"] = raw["picks_last_updated"][:40]
    return result


class Handler(SimpleHTTPRequestHandler):
    # A stalled or short upload must not hold a server thread forever.
    timeout = 15

    def log_message(self, format, *args):
        return

    def send_json(self, value, status=HTTPStatus.OK):
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_text(self, text, status=HTTPStatus.OK):
        content = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def private_data(self, config, snapshot):
        """Serve captured account data only when this server is reachable from this machine alone."""
        if self.server.server_address[0] not in LOOPBACK_HOSTS:
            return private_team.disabled()
        return private_team.load(PRIVATE_TEAM, config, snapshot)

    def same_origin_local(self):
        """Accept only a page served by this loopback server (blocks cross-site and DNS-rebinding posts)."""
        host = (self.headers.get("Host") or "").strip().lower()
        if not self.host_is_local():
            return False
        origin = self.headers.get("Origin") or ""
        referer = self.headers.get("Referer") or ""
        expected = f"http://{host}"
        return origin == expected or (not origin and (referer == expected or referer.startswith(expected + "/")))

    def import_private_team(self):
        """Save FPL's /api/my-team/ JSON that the manager copied from their own signed-in browser."""
        if self.server.server_address[0] not in LOOPBACK_HOSTS or not self.same_origin_local():
            return self.send_json({"error": "Account import only works from this dashboard on this machine."}, HTTPStatus.FORBIDDEN)
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self.send_json({"error": "Paste the JSON text from FPL."}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = -1
        if length <= 0 or length > MAX_IMPORT_BYTES:
            return self.send_json({"error": "That paste is empty or too large to be FPL team data."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            my_team = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            return self.send_json({"error": "That isn't valid JSON. Copy the whole page from the FPL link."}, HTTPStatus.BAD_REQUEST)
        if isinstance(my_team, dict) and isinstance(my_team.get("my_team"), dict):
            my_team = my_team["my_team"]
        if not isinstance(my_team, dict) or not {"picks", "chips", "transfers"} <= set(my_team):
            return self.send_json({"error": "That doesn't look like FPL's my-team data (picks, chips and transfers are missing)."}, HTTPStatus.BAD_REQUEST)
        my_team = whitelist_my_team(my_team)
        config = load_config()
        snapshot, _ = self.api_data()
        record = {"schema_version": private_team.SCHEMA_VERSION, "source": "fpl-api my-team (pasted by the manager from their own browser)",
                  "team_id": config.get("team_id"), "captured_at_utc": datetime.now(timezone.utc).isoformat(), "my_team": my_team}
        LOCAL.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=LOCAL, suffix=".tmp")
        try:
            with handle:
                json.dump(record, handle, indent=2)
            summary = private_team.load(handle.name, config, snapshot or {})
            if summary["state"] not in ("ready", "stale"):
                return self.send_json({"error": summary["message"]}, HTTPStatus.UNPROCESSABLE_ENTITY)
            os.replace(handle.name, PRIVATE_TEAM)
        finally:
            if os.path.exists(handle.name):
                os.remove(handle.name)
        return self.send_json(private_team.load(PRIVATE_TEAM, config, snapshot or {}))

    def api_data(self):
        return read_json(ROOT / "data" / "latest.json", default=None), read_json(ROOT / "data" / "catalog.json", default={"players": [], "teams": []})

    def host_is_local(self):
        host = (self.headers.get("Host") or "").strip().lower()
        hostname = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return hostname in {"127.0.0.1", "localhost", "[::1]"}

    def client_id(self):
        # Proxies differ on where they put the real address, so key on the whole chain plus the socket peer:
        # a visitor can add entries (evading only the per-client limit, which the global ceiling backs up)
        # but can never reproduce another visitor's chain, so nobody can be locked out by imitation.
        chain = ",".join(entry.strip() for entry in (self.headers.get("X-Forwarded-For") or "").split(",") if entry.strip())
        return f"{chain[:256]}|{self.client_address[0]}"

    def gate(self, path):
        """Allow the request, or answer 401/429/503 when the hosted password is required."""
        if path == "/healthz":
            return True
        password, required = auth_settings()
        if not password:
            if required:
                self.send_text("Password protection is required but DASHBOARD_PASSWORD is not configured.\n", HTTPStatus.SERVICE_UNAVAILABLE)
                return False
            return True
        client, now = self.client_id(), time.monotonic()
        with AUTH_LOCK:
            recent = [stamp for stamp in AUTH_FAILURES.get(client, []) if now - stamp < AUTH_WINDOW_SECONDS]
            if recent:
                AUTH_FAILURES[client] = recent
            else:
                AUTH_FAILURES.pop(client, None)
            AUTH_GLOBAL_FAILURES[:] = [stamp for stamp in AUTH_GLOBAL_FAILURES if now - stamp < AUTH_WINDOW_SECONDS]
            blocking = recent if len(recent) >= AUTH_MAX_FAILURES else AUTH_GLOBAL_FAILURES if len(AUTH_GLOBAL_FAILURES) >= AUTH_GLOBAL_MAX_FAILURES else None
            if blocking:
                self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
                self.send_header("Retry-After", str(int(AUTH_WINDOW_SECONDS - (now - blocking[0])) + 1))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
        header = self.headers.get("Authorization")
        supplied = basic_password(header)
        if supplied is not None and hmac.compare_digest(supplied.encode("utf-8"), password.encode("utf-8")):
            return True
        if header:
            with AUTH_LOCK:
                if client not in AUTH_FAILURES and len(AUTH_FAILURES) >= AUTH_MAX_CLIENTS:
                    AUTH_FAILURES.pop(next(iter(AUTH_FAILURES)))
                AUTH_FAILURES.setdefault(client, []).append(now)
                AUTH_GLOBAL_FAILURES.append(now)
        body = b"Sign in to view this FPL Brief dashboard.\n"
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="FPL Brief", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def health(self, method):
        """Answer health probes (GET or HEAD) without data; log the first few so hosting issues are diagnosable."""
        global HEALTH_LOGGED
        ready = (STATIC_DIST / "index.html").is_file()
        status = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
        if HEALTH_LOGGED < 5:
            HEALTH_LOGGED += 1
            print(f"health probe {method} /healthz -> {int(status)}", flush=True)
        if method == "HEAD":
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        return self.send_text("ok\n" if ready else "frontend bundle missing\n", status)

    def do_HEAD(self):
        if urlparse(self.path).path == "/healthz":
            return self.health("HEAD")
        # Never fall back to the base class, which would expose files from the working directory.
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "GET, POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not self.gate(path):
            return
        if path == "/healthz":
            return self.health("GET")
        # On a loopback-bound server, refuse API reads addressed to any other hostname (DNS rebinding).
        if path.startswith("/api/") and self.server.server_address[0] in LOOPBACK_HOSTS and not self.host_is_local():
            return self.send_json({"error": "This dashboard only answers on localhost."}, HTTPStatus.FORBIDDEN)
        snapshot, catalog = self.api_data()
        if path == "/api/dashboard":
            if not snapshot:
                return self.send_json({"error": "No snapshot yet. Refresh FPL data first."}, HTTPStatus.SERVICE_UNAVAILABLE)
            config = load_config()
            decision = assess(snapshot, config)
            private = self.private_data(config, snapshot)
            apply_private_inputs(decision, private)
            research = research_result(config, snapshot)
            team_decision = build_team_decision(snapshot, catalog, research, decision["snapshot_status"])
            return self.send_json({"snapshot": snapshot, "catalog": catalog, "plans": load_plans(snapshot), "config": config,
                                   "private_team": private,
                                   "lineup": lineup_helper.suggest(snapshot, catalog, private, decision["snapshot_status"]),
                                   "snapshot_status": decision["snapshot_status"], "decision": decision, "research": research,
                                   "team_decision": team_decision,
                                   "workflow": read_json(ROOT / "data" / "workflow_status.json", default={"schema_version": 1})})
        if path == "/api/research":
            return self.send_json(research_result(load_config(), snapshot))
        if path == "/api/workflow-status":
            return self.send_json(read_json(ROOT / "data" / "workflow_status.json", default={"schema_version": 1}))
        if path == "/api/candidates":
            try:
                query = parse_qs(parsed.query)
                replace_id = int(query.get("replace_id", [""])[0])
                minimum_minutes = int(query.get("minimum_minutes", ["0"])[0])
                config = load_config()
                decision = assess(snapshot or {}, config)
                if decision["status"] == "blocked":
                    return self.send_json({"error": "Candidate Lens is blocked: " + " ".join(decision["blockers"])}, HTTPStatus.CONFLICT)
                private = self.private_data(config, snapshot or {})
                return self.send_json(lens(snapshot or {}, catalog, replace_id, minimum_minutes, config.get("stale_after_hours", 8), private=private))
            except (TypeError, ValueError) as error:
                return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

        if path == "/api/plan":
            config = load_config()
            freshness = snapshot_freshness(snapshot or {}, config.get("stale_after_hours", 8))
            try:
                pairs = transfer_plan.parse_transfers(parse_qs(parsed.query).get("transfers", [""])[0])
            except ValueError as error:
                return self.send_json({"state": "invalid", "reason": str(error)}, HTTPStatus.BAD_REQUEST)
            result = transfer_plan.build(snapshot or {}, catalog, self.private_data(config, snapshot or {}), freshness, pairs)
            return self.send_json(result, HTTPStatus.OK if result["state"] == "ready" else HTTPStatus.UNPROCESSABLE_ENTITY)
        if path.startswith("/api/players/"):
            try:
                player_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                return self.send_json({"error": "Invalid player id"}, HTTPStatus.BAD_REQUEST)
            player = player_map(catalog).get(player_id)
            return self.send_json(player or {"error": "Player not found"}, HTTPStatus.NOT_FOUND if not player else HTTPStatus.OK)
        if path == "/api/plans":
            if not snapshot:
                return self.send_json([])
            return self.send_json(load_plans(snapshot))
        if path.startswith("/api/jobs/"):
            job = JOBS.get(path.rsplit("/", 1)[1])
            return self.send_json(job or {"error": "Job not found"}, HTTPStatus.NOT_FOUND if not job else HTTPStatus.OK)
        return self.serve_static(path)

    def do_POST(self):
        if not self.gate(urlparse(self.path).path):
            return
        # On this machine, only this dashboard's own pages may trigger actions (blocks cross-site and DNS-rebinding posts).
        if self.server.server_address[0] in LOOPBACK_HOSTS and self.path in ("/api/research", "/api/refresh", "/api/plans/compare") and not self.same_origin_local():
            return self.send_json({"error": "Actions only work from this dashboard on this machine."}, HTTPStatus.FORBIDDEN)
        if self.path == "/api/research":
            job_id = uuid.uuid4().hex[:10]
            JOBS[job_id] = {"id": job_id, "status": "running", "message": "Collecting fixed official research…"}
            def collect():
                try:
                    result = subprocess.run([sys.executable, "-m", "fpl_brief.research_scout"], cwd=ROOT, text=True, capture_output=True, timeout=150)
                    JOBS[job_id] = {"id": job_id, "status": "complete" if result.returncode == 0 else "failed", "message": (result.stdout or result.stderr).strip()}
                except Exception as error:
                    JOBS[job_id] = {"id": job_id, "status": "failed", "message": "Research collection failed."}
            threading.Thread(target=collect, daemon=True).start()
            return self.send_json(JOBS[job_id], HTTPStatus.ACCEPTED)
        if self.path == "/api/refresh":
            job_id = uuid.uuid4().hex[:10]
            JOBS[job_id] = {"id": job_id, "status": "running", "message": "Refreshing public FPL data…"}
            def refresh():
                try:
                    result = subprocess.run([sys.executable, "fetch_fpl.py"], cwd=ROOT, text=True, capture_output=True, timeout=150)
                    JOBS[job_id] = {"id": job_id, "status": "complete" if result.returncode == 0 else "failed", "message": (result.stdout or result.stderr).strip()}
                except Exception as error:
                    JOBS[job_id] = {"id": job_id, "status": "failed", "message": str(error)}
            threading.Thread(target=refresh, daemon=True).start()
            return self.send_json(JOBS[job_id], HTTPStatus.ACCEPTED)
        if self.path == "/api/private-team":
            return self.import_private_team()
        if self.path == "/api/plans/compare":
            try:
                payload = self.body()
                _, catalog = self.api_data()
                candidates = payload.get("plans", [])
                if not isinstance(candidates, list) or not candidates or len(candidates) > MAX_PLANS:
                    raise ValueError(f"Compare between one and {MAX_PLANS} scenarios.")
                for plan in candidates:
                    validate_plan(plan, catalog)
                return self.send_json({"results": [evaluate_plan(plan, catalog) for plan in candidates], "method": "FPL ep_next only; future-GW projections require your assumptions."})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        return self.send_json({"error": "Unknown endpoint"}, HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        if not self.gate(urlparse(self.path).path):
            return
        return self.send_json({"error": "Drafts are device-local; server plan writes are disabled."}, HTTPStatus.METHOD_NOT_ALLOWED)

    def serve_static(self, path):
        requested = "index.html" if path in ("/", "") else path.lstrip("/")
        static_root = STATIC_DIST.resolve()
        if not (static_root / "index.html").is_file():
            # Never fall back to unbuilt TypeScript source; browsers cannot run it.
            return self.send_text(MISSING_BUNDLE_MESSAGE, HTTPStatus.SERVICE_UNAVAILABLE)
        target = (static_root / requested).resolve()
        if static_root not in target.parents or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        content = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        # index.html names the hashed bundle files, so it must be revalidated after every build.
        # Behind a password, never let shared caches keep a copy of the app.
        scope = "private" if auth_settings()[0] else "public"
        self.send_header("Cache-Control", "no-cache" if target.name == "index.html" else f"{scope}, max-age=300")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def server_address(environ=None):
    environ = os.environ if environ is None else environ
    raw_port = environ.get("PORT")
    if raw_port in (None, ""):
        return ("127.0.0.1", 8765)
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as error:
        raise ValueError("PORT must be an integer between 1 and 65535") from error
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return ("0.0.0.0", port)

def main():
    address = server_address()
    print(f"FPL Brief dashboard listening on {address[0]}:{address[1]}")
    ThreadingHTTPServer(address, Handler).serve_forever()

if __name__ == "__main__":
    main()
