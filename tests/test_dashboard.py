import json
import subprocess
import threading
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen

import dashboard


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {"players": [{"id": 1, "web_name": "One"}, {"id": 2, "web_name": "Two"}]}

    def test_snapshot_status_marks_old_snapshot_stale(self):
        now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
        snapshot = {"generated_at_utc": (now - timedelta(hours=8, minutes=30)).isoformat()}
        result = dashboard.snapshot_status(snapshot, {"stale_after_hours": 8}, now)
        self.assertTrue(result["stale"])
        self.assertEqual(result["age_hours"], 8.5)

    def test_snapshot_status_accepts_current_snapshot(self):
        now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
        result = dashboard.snapshot_status({"generated_at_utc": now.isoformat()}, {"stale_after_hours": 8}, now)
        self.assertFalse(result["stale"])
        self.assertEqual(result["message"], "Snapshot is current.")

    def test_snapshot_status_handles_invalid_time(self):
        result = dashboard.snapshot_status({"generated_at_utc": "not-a-date"}, {"stale_after_hours": 8})
        self.assertTrue(result["stale"])
        self.assertEqual(result["message"], "Snapshot time is invalid.")

    def test_validate_plan_rejects_duplicate_and_unknown_players(self):
        with self.assertRaisesRegex(ValueError, "same player"):
            dashboard.validate_plan({"name": "Duplicate", "target_gw": 4, "players": [1, 1]}, self.catalog)
        with self.assertRaisesRegex(ValueError, "current FPL catalog"):
            dashboard.validate_plan({"name": "Unknown", "target_gw": 4, "players": [3]}, self.catalog)

    def test_evaluate_plan_returns_current_catalog_totals(self):
        result = dashboard.evaluate_plan({"name": "Draft", "target_gw": 4, "players": [1, 2]}, {"players": [
            {"id": 1, "web_name": "One", "now_cost": 50, "ep_next": "2.5", "status": "a", "chance_of_playing_next_round": None},
            {"id": 2, "web_name": "Two", "now_cost": 45, "ep_next": "3.0", "status": "d", "chance_of_playing_next_round": 75},
        ]})
        self.assertEqual(result["cost"], 95)
        self.assertEqual(result["ep_next"], 5.5)
        self.assertEqual(result["risk_count"], 1)


if __name__ == "__main__":
    unittest.main()

class RailwayReadinessTests(unittest.TestCase):
    def test_server_address_uses_injected_port_and_railway_host(self):
        self.assertEqual(dashboard.server_address({"PORT": "18765"}), ("0.0.0.0", 18765))
        self.assertEqual(dashboard.server_address({}), ("127.0.0.1", 8765))

    def test_server_address_rejects_invalid_port(self):
        for value in ("nope", "0", "65536"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "PORT"):
                    dashboard.server_address({"PORT": value})

    def test_plans_are_templates_only_and_server_write_endpoint_is_disabled(self):
        self.assertFalse(hasattr(dashboard, "plans_path"))
        result = dashboard.load_plans({"squad_snapshot": {"picks": []}, "events": {}})
        self.assertEqual(result[0]["id"], "hold")
        self.assertIn("Drafts are device-local", Path("dashboard.py").read_text(encoding="utf-8"))

    def test_client_drafts_are_bounded_local_and_validated(self):
        source = Path("dashboard/app.js").read_text(encoding="utf-8")
        self.assertIn("localStorage", source)
        self.assertIn("slice(0,4)", source)
        self.assertIn("slice(0,80)", source)
        self.assertNotIn("/api/plans/", source)
        self.assertIn("current catalog", source)

    def test_client_storage_behavior_drops_invalid_drafts_before_state(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("dashboard/app.js", "utf8");
const prefix = source.slice(0, source.indexOf("const state="));
const sandbox = { Date, localStorage: null };
vm.runInNewContext(prefix, sandbox);
const catalog = { players: [{ id: 1 }, { id: 2 }] };
const stored = [
  { id: "bad-unknown", name: "Unknown", target_gw: 4, players: [999] },
  { id: "bad-duplicate", name: "Duplicate", target_gw: 4, players: [1, 1] },
  { id: "bad-gw", name: "Bad GW", target_gw: 8, players: [1] },
  { id: "bad-name", name: "   ", target_gw: 4, players: [1] },
  { id: "bad-object", name: "Object players", target_gw: 4, players: { 0: 1 } },
  { id: "bad-null", name: "Null players", target_gw: 4, players: null },
  { id: "good", name: "Good", target_gw: 4, players: [1, 2] }
];
const storage = { getItem: () => JSON.stringify(stored) };
const loaded = sandbox.readDrafts([{ id: "fallback", name: "Fallback", target_gw: 4, players: [999] }], catalog, storage);
if (loaded.length !== 1 || loaded[0].id !== "good" || loaded[0].players.join(",") !== "1,2") process.exit(1);
const emptyStorage = { getItem: () => JSON.stringify([{ id: "bad", name: "Bad", target_gw: 4, players: [999] }]) };
const fallback = sandbox.readDrafts([{ id: "also-bad", name: "Also bad", target_gw: 4, players: [999] }], catalog, emptyStorage);
if (fallback.length !== 1 || fallback[0].id !== "hold" || fallback[0].players.length !== 0) process.exit(1);
''';
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
    def test_manual_research_action_is_explicit_and_not_scheduled(self):
        source = Path("dashboard/desk-tools.js").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/research", {method:"POST"})', source)
        self.assertIn("ephemeral on Railway", source)
        self.assertNotIn("setInterval", source)

class HostedLoadTests(unittest.TestCase):
    def test_dashboard_scripts_are_deferred_in_document_order(self):
        source = Path("dashboard/index.html").read_text(encoding="utf-8")
        tags = [source.index('src="app.js"'), source.index('src="decision-states.js"'), source.index('src="desk-tools.js"')]
        self.assertEqual(tags, sorted(tags))
        for script in ("app.js", "decision-states.js", "desk-tools.js"):
            self.assertIn(f'src="{script}" defer', source)
        self.assertLess(source.index("<script"), source.index("</body>"))
        self.assertGreater(source.index("</body>"), source.index('src="desk-tools.js"'))

    def test_decision_feedback_is_explicit_not_self_observing(self):
        decision = Path("dashboard/decision-states.js").read_text(encoding="utf-8")
        app = Path("dashboard/app.js").read_text(encoding="utf-8")
        self.assertNotIn("MutationObserver", decision)
        self.assertIn("window.refreshDecisionStates = feedback", decision)
        self.assertIn("window.refreshDecisionStates?.()", app)
    def test_static_assets_are_cacheable_but_api_json_is_not(self):
        server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/app.js") as response:
                self.assertEqual(response.headers["Cache-Control"], "public, max-age=300")
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/workflow-status") as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        finally:
            server.shutdown()
            server.server_close()
