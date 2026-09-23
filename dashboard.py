#!/usr/bin/env python3
"""Local, read-only dashboard for the FPL Brief snapshot."""

import json
import mimetypes
import os
import subprocess
import sys
import threading
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from fpl_brief.config import load as load_config
from fpl_brief.decision import assess, snapshot_freshness
from fpl_brief.candidates import lens
from fpl_brief.research import evidence_status, load_packet
from fpl_brief.storage import read_json

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "dashboard"
LOCAL = ROOT / "local"
JOBS = {}
MAX_PLANS = 4


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


def research_result(config):
    return evidence_status(load_packet(ROOT / "data" / "research_packet.json"), config["research_stale_after_hours"])


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


class Handler(SimpleHTTPRequestHandler):
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

    def body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def api_data(self):
        return read_json(ROOT / "data" / "latest.json", default=None), read_json(ROOT / "data" / "catalog.json", default={"players": [], "teams": []})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        snapshot, catalog = self.api_data()
        if path == "/api/dashboard":
            if not snapshot:
                return self.send_json({"error": "No snapshot yet. Refresh FPL data first."}, HTTPStatus.SERVICE_UNAVAILABLE)
            config = load_config()
            decision = assess(snapshot, config)
            research = research_result(config)
            return self.send_json({"snapshot": snapshot, "catalog": catalog, "plans": load_plans(snapshot), "config": config,
                                   "snapshot_status": decision["snapshot_status"], "decision": decision, "research": research,
                                   "workflow": read_json(ROOT / "data" / "workflow_status.json", default={"schema_version": 1})})
        if path == "/api/research":
            return self.send_json(research_result(load_config()))
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
                return self.send_json(lens(snapshot or {}, catalog, replace_id, minimum_minutes, config.get("stale_after_hours", 8)))
            except (TypeError, ValueError) as error:
                return self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

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
        return self.send_json({"error": "Drafts are device-local; server plan writes are disabled."}, HTTPStatus.METHOD_NOT_ALLOWED)

    def serve_static(self, path):
        requested = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC / requested).resolve()
        if STATIC not in target.parents or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        content = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Cache-Control", "public, max-age=300")
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

def research_result(config):
    return evidence_status(load_packet(ROOT / "data" / "research_packet.json"), config["research_stale_after_hours"])
