import base64
import http.client
import os
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import urlopen
from types import SimpleNamespace
from unittest.mock import patch

import dashboard
from fpl_brief import web_session


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

    def test_research_result_reports_research_and_snapshot_freshness_separately(self):
        now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
        research_time = (now - timedelta(hours=2)).isoformat()
        snapshot_time = (now - timedelta(hours=10)).isoformat()
        packet = {
            "schema_version": 2,
            "generated_at_utc": research_time,
            "collector": {"version": "v1", "last_run_at_utc": research_time},
            "sources": [{
                "id": "official-fpl-news", "publisher": "Fantasy Premier League",
                "url": "https://fantasy.premierleague.com/api/bootstrap-static/",
                "title": "Official FPL player news", "retrieved_at_utc": research_time,
                "last_success_at_utc": research_time, "collection_state": "captured",
                "verification_status": "unverified", "excerpts": [{
                    "kind": "player_news", "text": "Captured news",
                    "captured_at_utc": research_time, "player_id": 1,
                    "player_name": "One", "team_id": 1, "team_name": "Club",
                }], "claims": [],
            }],
            "warnings": [],
        }
        config = {"research_stale_after_hours": 24, "stale_after_hours": 8}
        with patch.object(dashboard, "load_packet", return_value=packet):
            result = dashboard.research_result(config, {"generated_at_utc": snapshot_time}, now)
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["research_age_hours"], 2.0)
        self.assertFalse(result["stale"])
        self.assertTrue(result["snapshot_status"]["stale"])
        self.assertEqual(result["snapshot_status"]["age_hours"], 10.0)

    def test_research_result_explains_missing_snapshot_without_hiding_research(self):
        config = {"research_stale_after_hours": 24, "stale_after_hours": 8}
        with patch.object(dashboard, "load_packet", return_value=None), patch.object(dashboard, "read_json", return_value=None):
            result = dashboard.research_result(config, None)
        self.assertEqual(result["state"], "missing")
        self.assertTrue(result["snapshot_status"]["stale"])
        self.assertEqual(result["snapshot_status"]["message"], "Snapshot time is unavailable.")

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


class TeamDecisionDeskTests(unittest.TestCase):
    def setUp(self):
        self.rules = [
            {"id": 1, "name": "wildcard", "start_event": 2, "stop_event": 19, "number": 1},
            {"id": 2, "name": "wildcard", "start_event": 20, "stop_event": 38, "number": 1},
            {"id": 3, "name": "freehit", "start_event": 2, "stop_event": 19, "number": 1},
            {"id": 4, "name": "freehit", "start_event": 20, "stop_event": 38, "number": 1},
            {"id": 5, "name": "bboost", "start_event": 1, "stop_event": 19, "number": 1},
            {"id": 6, "name": "bboost", "start_event": 20, "stop_event": 38, "number": 1},
            {"id": 7, "name": "3xc", "start_event": 1, "stop_event": 19, "number": 1},
            {"id": 8, "name": "3xc", "start_event": 20, "stop_event": 38, "number": 1},
        ]
        self.snapshot = {
            "generated_at_utc": "2026-09-24T10:00:00+00:00",
            "events": {"next": {"id": 5}}, "chip_rules": self.rules,
            "manager": {"chips": [{"name": "wildcard", "event": 4}, {"name": "3xc", "event": 2}]},
            "squad_snapshot": {"picks": [{"element": 1, "position": 1}]},
            "fixtures": {"events": {"5": [{"team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 4}]}},
        }

    def test_chip_ledger_maps_and_counts_repeat_windows(self):
        ledger = dashboard.chip_ledger(self.snapshot)
        self.assertEqual(ledger["state"], "known")
        rows = {row["name"]: row for row in ledger["chips"]}
        self.assertEqual(rows["Wildcard"]["used_gameweeks"], [4])
        self.assertEqual(rows["Wildcard"]["available_now"], 0)
        self.assertEqual(rows["Wildcard"]["future_count"], 1)
        self.assertEqual(rows["Free Hit"]["available_now"], 1)
        self.assertEqual(rows["Free Hit"]["future_count"], 1)
        self.assertEqual(rows["Bench Boost"]["available_now"], 1)
        self.assertEqual(rows["Bench Boost"]["future_count"], 1)
        self.assertEqual(rows["Triple Captain"]["used_count"], 1)
        self.assertEqual(rows["Triple Captain"]["used_gameweeks"], [2])
        self.assertEqual(rows["Triple Captain"]["available_now"], 0)
        self.assertEqual(rows["Triple Captain"]["future_count"], 1)

    def test_chip_ledger_returns_unknown_for_stale_or_inconsistent_inputs(self):
        stale = dashboard.chip_ledger(self.snapshot, stale=True)
        self.assertEqual(stale["state"], "partial")
        stale_rows = {row["name"]: row for row in stale["chips"]}
        self.assertEqual(stale_rows["Wildcard"]["used_gameweeks"], [4])
        self.assertEqual(stale_rows["Triple Captain"]["used_gameweeks"], [2])
        self.assertNotIn("available_now", stale_rows["Wildcard"])
        missing_history = {**self.snapshot, "manager": {}}
        self.assertEqual(dashboard.chip_ledger(missing_history)["state"], "unknown")
        duplicate = {**self.snapshot, "manager": {"chips": [{"name": "wildcard", "event": 4}, {"name": "wildcard2", "event": 4}]}}
        wildcard = next(row for row in dashboard.chip_ledger(duplicate)["chips"] if row["name"] == "Wildcard")
        self.assertEqual(wildcard["state"], "unknown")
        rules_conflict = {**self.snapshot, "chip_rules": [*self.rules, {"id": 1, "name": "wildcard", "start_event": 2, "stop_event": 19, "number": 1}]}
        self.assertNotEqual(dashboard.chip_ledger(rules_conflict)["chips"][0]["state"], "known")

    def test_unrecognized_official_chip_is_visible_and_prevents_complete_inventory(self):
        extra = {"id": 9, "name": "mystery-chip", "start_event": 1, "stop_event": 38, "number": 1}
        snapshot = {**self.snapshot, "chip_rules": [*self.rules, extra],
                    "manager": {"chips": [*self.snapshot["manager"]["chips"], {"name": "mystery-chip", "event": 3}]}}
        ledger = dashboard.chip_ledger(snapshot)
        self.assertEqual(ledger["state"], "partial")
        unknown = next(row for row in ledger["chips"] if row["name"] == "mystery-chip")
        self.assertEqual(unknown["state"], "unknown")
        self.assertIn("availability", unknown["reason"])
        self.assertEqual(unknown["used_gameweeks"], [3])

    def test_unrecognized_chip_and_play_survive_stale_snapshot(self):
        extra = {"id": 9, "name": "mystery-chip", "start_event": 1, "stop_event": 38, "number": 1}
        snapshot = {**self.snapshot, "chip_rules": [*self.rules, extra],
                    "manager": {"chips": [*self.snapshot["manager"]["chips"], {"name": "mystery-chip", "event": 3}]}}
        ledger = dashboard.chip_ledger(snapshot, stale=True)
        unknown = next(row for row in ledger["chips"] if row["name"] == "mystery-chip")
        self.assertEqual(unknown["state"], "unknown")
        self.assertEqual(unknown["used_gameweeks"], [3])
        self.assertEqual(unknown["used_source"], "recorded in snapshot")
        self.assertNotIn("available_now", unknown)

    def test_unrecognized_chip_and_play_survive_missing_current_gameweek(self):
        extra = {"id": 9, "name": "mystery-chip", "start_event": 1, "stop_event": 38, "number": 1}
        snapshot = {**self.snapshot, "events": {}, "chip_rules": [*self.rules, extra],
                    "manager": {"chips": [*self.snapshot["manager"]["chips"], {"name": "mystery-chip", "event": 3}]}}
        ledger = dashboard.chip_ledger(snapshot)
        unknown = next(row for row in ledger["chips"] if row["name"] == "mystery-chip")
        self.assertEqual(unknown["state"], "unknown")
        self.assertEqual(unknown["used_gameweeks"], [3])
        self.assertEqual(unknown["used_source"], "recorded in snapshot")
        self.assertNotIn("available_now", unknown)

    def test_blank_name_official_chip_rule_is_accounted_for_in_every_ledger_state(self):
        unnamed = {"id": 9, "name": "   ", "start_event": 1, "stop_event": 38, "number": 1}
        history = [*self.snapshot["manager"]["chips"], {"name": "unmatched-chip", "event": 3}]
        cases = (
            ("fresh", {**self.snapshot, "chip_rules": [*self.rules, unnamed],
                        "manager": {"chips": history}}, False),
            ("stale", {**self.snapshot, "chip_rules": [*self.rules, unnamed],
                        "manager": {"chips": history}}, True),
            ("missing-gameweek", {**self.snapshot, "events": {}, "chip_rules": [*self.rules, unnamed],
                                   "manager": {"chips": history}}, False),
        )
        for name, snapshot, stale in cases:
            with self.subTest(state=name):
                ledger = dashboard.chip_ledger(snapshot, stale=stale)
                row = next((chip for chip in ledger["chips"] if chip["name"] == "Unrecognized chip (ID 9)"), None)
                self.assertIsNotNone(row)
                self.assertEqual(row["state"], "unknown")
                self.assertNotIn("available_now", row)
                self.assertNotEqual(ledger["state"], "known")
                unmatched = next(chip for chip in ledger["chips"] if chip["name"] == "Unrecognized recorded chip")
                self.assertEqual(unmatched["state"], "unknown")

    def test_multiple_unusable_official_rules_remain_distinct_in_every_ledger_state(self):
        malformed = [
            {"id": "not-an-id", "name": "  ", "start_event": 1, "stop_event": 38, "number": 1},
            {"id": None, "name": "", "start_event": 1, "stop_event": 38, "number": 1},
        ]
        snapshot = {**self.snapshot, "chip_rules": [*self.rules, *malformed]}
        cases = (
            ("fresh", self.snapshot["events"], False),
            ("stale", self.snapshot["events"], True),
            ("missing-gameweek", {}, False),
        )
        expected_names = {"Unrecognized official chip rule (rule 9)",
                          "Unrecognized official chip rule (rule 10)"}
        for name, events, stale in cases:
            with self.subTest(state=name):
                ledger = dashboard.chip_ledger({**snapshot, "events": events}, stale=stale)
                rows = [chip for chip in ledger["chips"] if chip["name"] in expected_names]
                self.assertEqual({row["name"] for row in rows}, expected_names)
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(row["state"] == "unknown" for row in rows))
                self.assertTrue(all("available_now" not in row for row in rows))
                self.assertNotEqual(ledger["state"], "known")

    def test_missing_rules_retain_recorded_used_chips_but_not_availability(self):
        ledger = dashboard.chip_ledger({key: value for key, value in self.snapshot.items() if key != "chip_rules"})
        rows = {row["name"]: row for row in ledger["chips"]}
        self.assertEqual(rows["Wildcard"]["used_source"], "recorded in snapshot")
        self.assertEqual(rows["Wildcard"]["used_gameweeks"], [4])
        self.assertEqual(rows["Triple Captain"]["used_gameweeks"], [2])
        self.assertNotIn("available_now", rows["Wildcard"])

    def test_team_decision_hides_actionable_priority_when_snapshot_is_stale(self):
        catalog = {"players": [{"id": 1, "web_name": "Player", "team": 1, "status": "i", "chance_of_playing_next_round": 0}], "teams": [{"id": 1, "short_name": "AAA"}, {"id": 2, "short_name": "BBB"}]}
        result = dashboard.build_team_decision(self.snapshot, catalog, {}, {"stale": True, "message": "Snapshot old."})
        self.assertEqual(len(result["players"]), 1)
        self.assertEqual(result["players"][0]["priority"], "Snapshot stale")
        self.assertIn("Refresh", result["players"][0]["reason"])
        self.assertEqual(result["players"][0]["fixtures"][0]["opponent"], "BBB")
        self.assertEqual(result["chips"]["state"], "partial")

    def test_team_decision_uses_id_link_and_marks_stale_research_unverified(self):
        catalog = {"players": [{"id": 1, "web_name": "Player", "team": 1, "status": "a", "minutes": 90, "form": "2.0", "total_points": 10}], "teams": [{"id": 1, "short_name": "AAA"}]}
        research = {"valid": True, "state": "stale", "packet": {"sources": [{
            "id": "source", "publisher": "Publisher", "title": "News", "url": "https://example.com/",
            "excerpts": [{"player_id": 1, "player_name": "Wrong name", "text": "Captured note", "captured_at_utc": "bad"},
                         {"player_name": "Player", "text": "Must not name-link"}],
        }]}, "source_summaries": [{"id": "source", "stale": True, "stale_excerpt_indexes": [0]}]}
        result = dashboard.build_team_decision(self.snapshot, catalog, research, {"stale": False, "message": "current"})
        self.assertEqual(result["players"][0]["research"][0]["text"], "Captured note")
        self.assertTrue(result["players"][0]["research"][0]["stale"])
        self.assertEqual(len(result["players"][0]["research"]), 1)
        self.assertEqual(result["players"][0]["priority"], "No official availability flag")
        self.assertIn("not a transfer recommendation", result["players"][0]["next_step"])

    def test_incomplete_fresh_player_evidence_gives_next_step(self):
        catalog = {"players": [{"id": 1, "web_name": "Player", "team": 1, "status": "a", "minutes": 0, "form": None, "total_points": 0}], "teams": [{"id": 1, "short_name": "AAA"}]}
        snapshot = {**self.snapshot, "fixtures": {"events": {}}}
        row = dashboard.build_team_decision(snapshot, catalog, {}, {"stale": False, "message": "current"})["players"][0]
        self.assertEqual(row["priority"], "Not enough current evidence")
        self.assertIn("meaningful minutes", row["reason"])
        self.assertIn("upcoming fixtures", row["reason"])
        self.assertEqual(row["research"], [])
        self.assertIn("Refresh FPL data", row["next_step"])

    def test_complete_unflagged_row_says_availability_is_not_a_recommendation(self):
        catalog = {"players": [{"id": 1, "web_name": "Player", "team": 1, "status": "a", "minutes": 90, "form": "2.0", "total_points": 10}], "teams": [{"id": 1, "short_name": "AAA"}]}
        row = dashboard.build_team_decision(self.snapshot, catalog, {}, {"stale": False, "message": "current"})["players"][0]
        self.assertEqual(row["priority"], "No official availability flag")
        self.assertIn("not a transfer recommendation", row["next_step"])

    def test_team_decision_renderer_escapes_dynamic_content_and_compare_is_wired(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const ts = require("./dashboard/node_modules/typescript");
const source = fs.readFileSync("dashboard/team-decision-desk.ts", "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const context = { exports: {} };
vm.runInNewContext(output, context);
const data = { snapshot_stale: false, snapshot_message: "current", generated_at_utc: "2026-09-24T10:00:00Z", research_state: "ready",
  players: [{ id: 7, name: "<img src=x>", team: "A&B", role: 2, priority: "No official availability flag", reason: "OK", next_step: "Not a transfer recommendation", status: "Available", news: "<script>x</script>", minutes: 9, form: 1, total_points: 2, ep_next: 3, fixtures: [], research: [{ text: "<svg onload=x>", publisher: "<bad>", title: "Title", url: "https://evil.example", stale: false, captured_at_utc: "bad" }] }],
  chips: { state: "partial", reason: "<unknown>", gameweek: 5, chips: [{ name: "Wildcard", state: "unknown", reason: "bad" }] } };
const html = context.exports.renderTeamDecisionDesk(data);
for (const value of ["&lt;img src=x&gt;", "A&amp;B", "&lt;script&gt;x&lt;/script&gt;", "&lt;svg onload=x&gt;", "&lt;bad&gt;", "Not a transfer recommendation", "Unknown is not counted as available", "Unknown"]) {
  if (!html.includes(value)) throw new Error("Expected escaped/rendered content missing: " + value);
}
if (html.includes("<script>") || html.includes("<svg") || html.includes("href=\"https://evil.example")) throw new Error("Unsafe dynamic markup or link rendered");
if (!html.includes('data-compare-player="7"')) throw new Error("Candidate Lens comparison control missing");
const incomplete = { ...data, players: [{ ...data.players[0], priority: "Not enough current evidence", reason: "Missing meaningful minutes, upcoming fixtures; no transfer conclusion can be drawn." }] };
const incompleteHtml = context.exports.renderTeamDecisionDesk(incomplete);
if (!incompleteHtml.includes("1 insufficient stats/fixture evidence")) throw new Error("Incomplete evidence category missing from summary");
if (incompleteHtml.includes("availability flag, incomplete join, or FPL note")) throw new Error("Summary incorrectly attributes incomplete stats/fixture evidence");
''';
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        app = Path("dashboard/app.ts").read_text(encoding="utf-8")
        self.assertIn('target.closest<HTMLButtonElement>("[data-compare-player]")', app)

    def test_plans_are_templates_only_and_server_write_endpoint_is_disabled(self):
        self.assertFalse(hasattr(dashboard, "plans_path"))
        result = dashboard.load_plans({"squad_snapshot": {"picks": []}, "events": {}})
        self.assertEqual(result[0]["id"], "hold")
        self.assertIn("Drafts are device-local", Path("dashboard.py").read_text(encoding="utf-8"))

    def test_client_drafts_are_bounded_local_and_validated(self):
        source = Path("dashboard/app.ts").read_text(encoding="utf-8")
        self.assertIn("localStorage", source)
        self.assertIn("slice(0, 4)", source)
        self.assertIn("name.length > 80", source)
        self.assertNotIn("/api/plans/", source)
        self.assertIn("current catalog", source)

    def test_client_storage_behavior_drops_invalid_drafts_before_state(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const ts = require("./dashboard/node_modules/typescript");
const source = fs.readFileSync("dashboard/app.ts", "utf8");
const start = source.indexOf("interface StorageLike {");
const end = source.indexOf("\nfunction writeDrafts", start);
const helpers = source.slice(start, end);
const compiled = ts.transpileModule(helpers, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const sandbox = { exports: {}, Date, window: { localStorage: null } };
vm.runInNewContext(compiled, sandbox);
const readDrafts = sandbox.exports.readDrafts;
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
const loaded = readDrafts([{ id: "fallback", name: "Fallback", target_gw: 4, players: [999] }], catalog, storage);
if (loaded.length !== 1 || loaded[0].id !== "good" || loaded[0].players.join(",") !== "1,2") process.exit(1);
const emptyStorage = { getItem: () => JSON.stringify([{ id: "bad", name: "Bad", target_gw: 4, players: [999] }]) };
const fallback = readDrafts([{ id: "also-bad", name: "Also bad", target_gw: 4, players: [999] }], catalog, emptyStorage);
if (fallback.length !== 1 || fallback[0].id !== "hold" || fallback[0].players.length !== 0) process.exit(1);
''';
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
    def test_manual_research_action_is_explicit_and_not_scheduled(self):
        source = Path("dashboard/desk-tools.ts").read_text(encoding="utf-8")
        self.assertIn('requestJson<JobResponse>("/api/research", { method: "POST" })', source)
        self.assertIn("ephemeral on Railway", source)
        self.assertNotIn("setInterval", source)

class HostedLoadTests(unittest.TestCase):
    def test_squad_formation_groups_public_picks_and_keeps_list_and_pitch_equivalent(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const ts = require("./dashboard/node_modules/typescript");
const source = fs.readFileSync("dashboard/squad-formation.ts", "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const context = { exports: {}, Date, Intl };
vm.runInNewContext(compiled, context);
const { renderSquadFormation, mountSquadFormation } = context.exports;
const picks = [
  { element: 1, position: 1, element_type: 1 },
  ...[2, 3, 4, 5].map((element, i) => ({ element, position: i + 2, element_type: 2 })),
  ...[6, 7, 8].map((element, i) => ({ element, position: i + 6, element_type: 3, is_captain: element === 8 })),
  ...[9, 10, 11].map((element, i) => ({ element, position: i + 9, element_type: 4, is_vice_captain: element === 10 })),
  { element: 13, position: 13, element_type: 3 },
  { element: 12, position: 12, element_type: 2 },
  { element: 14, position: 14, element_type: 1 },
  { element: 15, position: 15, element_type: 4 },
  { element: 99, position: 16, element_type: 2 }
];
const players = picks.filter(p => p.element <= 15).map(p => ({
  id: p.element, web_name: p.element === 1 ? "<img src=x onerror=1>" : `Player ${p.element}`,
  team: 5, element_type: p.element_type, status: p.element === 2 ? "i" : "a",
  chance_of_playing_next_round: p.element === 2 ? 25 : 100, now_cost: 50 + p.element,
  form: `${p.element}.1`, total_points: p.element * 10, ep_next: (p.element / 2).toFixed(1)
}));
const input = { picks, players, teams: [{ id: 5, short_name: "CLB & <FC>" }], gameweek: 5,
  generatedAt: "2026-09-24T10:00:00Z", bank: 15 };
const html = renderSquadFormation(input);
const listStart = html.indexOf('<div id="squad-list"');
const pitchStart = html.indexOf('<div id="squad-pitch"');
if (pitchStart < 0 || listStart < 0 || pitchStart >= listStart) throw new Error("Could not isolate the Pitch and List views");
const summary = html.slice(0, pitchStart);
const pitch = html.slice(pitchStart, listStart);
const list = html.slice(listStart);
for (const expected of ["Snapshot shape (4-3-3)", "24 Sept 2026",
  "does not advise a lineup or expose unsubmitted intent"]) {
  if (!summary.includes(expected)) throw new Error("Missing shared snapshot context: " + expected);
}
for (const expected of ["Captain", "Vice captain", "Bench 1", "Bench 4",
  "Injured · 25% chance (FPL)", "Unknown player", "Unknown", "&lt;img src=x onerror=1&gt;",
  "CLB &amp; &lt;FC&gt;",
  "FPL GW estimates are for the next round only, not a points promise."]) {
  if (!pitch.includes(expected)) throw new Error("Missing Pitch fact or safe fallback: " + expected);
}
for (const expected of ["Captain", "Vice captain", "Bench 1", "Bench 4",
  "Injured · 25% chance (FPL)", "Unknown player", "&lt;img src=x onerror=1&gt;", "CLB &amp; &lt;FC&gt;",
  "<th scope=\"col\">Price</th>", "<th scope=\"col\">Form</th>",
  "<th scope=\"col\">Points</th>", "<th scope=\"col\">GW estimate</th>"]) {
  if (!list.includes(expected)) throw new Error("Missing List fact or safe fallback: " + expected);
}
function pitchCard(position) {
  const start = pitch.indexOf(`Snapshot pick ${position}:`);
  const end = pitch.indexOf("</article>", start);
  return pitch.slice(start, end);
}
function listRow(name) {
  const playerStart = list.indexOf(`<span class="player-name">${name}`);
  const start = list.lastIndexOf("<tr>", playerStart);
  const end = list.indexOf("</tr>", playerStart);
  return list.slice(start, end);
}
const pitchPlayer = pitchCard(6);
const listPlayer = listRow("Player 6</span>");
for (const [viewName, rendered] of [["Pitch", pitchPlayer], ["List", listPlayer]]) {
  for (const expected of ["£5.6m", "6.1", "60", "3.0", "Player 6", "CLB", "Available", "Midfielder"]) {
    if (!rendered.includes(expected)) throw new Error(`${viewName} does not render Player 6's squad facts: ${expected}`);
  }
}
for (const expected of ["Price £5.6m", "Form 6.1", "Points 60", "GW estimate 3.0"]) {
  if (!pitchPlayer.includes(expected)) throw new Error("List fact is not visibly represented for Player 6 in Pitch: " + expected);
}
const pitchCaptain = pitchCard(8);
const listCaptain = listRow("Player 8 · Captain</span>");
for (const [viewName, rendered] of [["Pitch", pitchCaptain], ["List", listCaptain]]) {
  for (const expected of ["Player 8", "CLB", "Available", "Captain"]) {
    if (!rendered.includes(expected)) throw new Error(`${viewName} does not identify the captain consistently: ${expected}`);
  }
}
const pitchRisk = pitchCard(2);
const listRisk = listRow("Player 2</span>");
for (const [viewName, rendered] of [["Pitch", pitchRisk], ["List", listRisk]]) {
  if (!rendered.includes("Injured · 25% chance (FPL)")) {
    throw new Error(`${viewName} does not preserve the player's FPL availability warning`);
  }
}
if (!list.includes("is an estimate for the next round, not a points promise")) {
  throw new Error("The FPL next-round estimate caveat is missing from List");
}
if (/<img\b|<FC>/.test(pitch + list)) throw new Error("Catalog markup became active HTML");
if (html.indexOf("Bench 1") > html.indexOf("Bench 2") || html.indexOf("Bench 2") > html.indexOf("Bench 3") || html.indexOf("Bench 3") > html.indexOf("Bench 4")) {
  throw new Error("Bench order does not follow snapshot positions");
}
const empty = renderSquadFormation({ picks: [], players: [], teams: [] });
const emptyPitch = empty.slice(empty.indexOf('<div id="squad-pitch"'), empty.indexOf('<div id="squad-list"'));
const emptyList = empty.slice(empty.indexOf('<div id="squad-list"'));
if (!emptyPitch.includes("No saved starting picks") || !emptyPitch.includes("No saved substitutes") || !emptyList.includes("No saved picks are available")) {
  throw new Error("Empty squad state is not handled in both views");
}
function button(view, pressed) {
  return { dataset: { squadView: view }, attrs: { "aria-pressed": pressed }, handler: null,
    addEventListener(_event, handler) { this.handler = handler; },
    setAttribute(name, value) { this.attrs[name] = value; } };
}
const pitchButton = button("pitch", "true");
const listButton = button("list", "false");
const pitchPanel = { dataset: { squadPanel: "pitch" }, hidden: false };
const listPanel = { dataset: { squadPanel: "list" }, hidden: true };
mountSquadFormation({ querySelectorAll(selector) { return selector.includes("view") ? [pitchButton, listButton] : [pitchPanel, listPanel]; } });
listButton.handler();
if (listButton.attrs["aria-pressed"] !== "true" || pitchButton.attrs["aria-pressed"] !== "false" || pitchPanel.hidden !== true || listPanel.hidden !== false) {
  throw new Error("List control did not expose its state or switch panels");
}
pitchButton.handler();
if (pitchButton.attrs["aria-pressed"] !== "true" || pitchPanel.hidden !== false || listPanel.hidden !== true) {
  throw new Error("Pitch control did not restore the pitch panel");
}
''';
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        styles = Path("dashboard/squad-formation.css").read_text(encoding="utf-8")
        self.assertRegex(styles, r"\.formation-player-stats\s*\{\s*display:\s*grid;")

    def test_overview_escapes_markup_like_fpl_availability_values(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const ts = require("./dashboard/node_modules/typescript");
const source = fs.readFileSync("dashboard/app.ts", "utf8");
const start = source.indexOf("function renderOverview(): void {");
const end = source.indexOf("\nfunction renderSquad()", start);
if (start < 0 || end < 0) throw new Error("Could not isolate overview renderer");
const renderer = source.slice(start, end);
const harness = `
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>\"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\\\"": "&quot;", "'": "&#39;"
  })[character] ?? character);
}
function formatDate() { return "24 Sept 2026 BKK"; }
const overview = { innerHTML: "", insertAdjacentHTML(_position, html) { this.innerHTML += html; } };
function required() { return overview; }
function renderTeamDecisionDesk() { return ""; }
function renderPrivateTeamPanel() { return ""; }
const state = { data: { snapshot: {
  league: { rank: 12, points: 80, gap_to_leader: 4, leader: { name: "Leader & Co" } },
  availability: [{ name: "</strong><img src=x onerror=alert(1)>", chance: "<svg/onload=alert(2)>", status: "d", news: "<b>untrusted note</b>" }],
  events: { next: { id: 4, deadline_time: "2026-09-24T00:00:00Z" } }
}, team_decision: {} } };
${renderer}
renderOverview();
exports.html = overview.innerHTML;
`;
const compiled = ts.transpileModule(harness, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const context = { exports: {} };
vm.runInNewContext(compiled, context);
const html = context.exports.html;
''';
        script += r'''
for (const expected of [
  "Resolve &lt;/strong&gt;&lt;img src=x onerror=alert(1)&gt;&#39;s availability",
  "FPL lists &lt;svg/onload=alert(2)&gt;% chance",
  "&lt;b&gt;untrusted note&lt;/b&gt;",
  "12", "80 pts", "Leader &amp; Co", "GW4 closes 24 Sept 2026 BKK"
]) {
  if (!html.includes(expected)) throw new Error("Missing safely rendered overview value: " + expected);
}
if (/<img\b|<svg\b/.test(html)) throw new Error("FPL markup became active HTML");
''';
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_research_view_renders_identity_times_states_and_truncation_safely(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const ts = require("./dashboard/node_modules/typescript");
const views = new Map();
const nav = { append: () => {} };
const main = { append: (view) => views.set(view.id, view) };
const document = {
  querySelector(selector) {
    if (selector === "nav") return nav;
    if (selector === "main") return main;
    return selector.startsWith("#") ? views.get(selector.slice(1)) : null;
  },
  createElement(tag) { return { tag, id: "", dataset: {}, addEventListener(_event, handler) { this.click = handler; }, append() {} }; },
  addEventListener() {}
};
const capturedAt = "2026-09-24T10:00:00+00:00";
const payload = {
  state: "ready", valid: true, latest_evidence_at_utc: capturedAt, research_age_hours: 2,
  last_collection_at_utc: capturedAt, warnings: [],
  snapshot_status: { stale: true, age_hours: 10, message: "Snapshot is 10.0 hours old." },
  source_summaries: [{ id: "official-fpl-news", state: "captured", stale: false,
    last_success_at_utc: capturedAt, attempted_at_utc: capturedAt, omitted_excerpts: 3 }],
  packet: { sources: [{ id: "official-fpl-news", publisher: "Fantasy Premier League",
    title: "Official FPL player news", url: "https://fantasy.premierleague.com/api/bootstrap-static/",
    collection_state: "captured", last_success_at_utc: capturedAt, attempted_at_utc: capturedAt,
    omitted_excerpts: 3, claims: [{ source_id: "official-fpl-news", excerpt_ref: 0,
      label: "reported", verification_status: "unverified", claim: "Claim detail",
      reviewer: "not reviewed", retrieved_at_utc: capturedAt, reviewed_at_utc: null }], excerpts: [{ kind: "player_news", text: "Exact news <b>untrusted</b>",
      captured_at_utc: capturedAt, player_id: 1, player_name: "Player <script>", team_name: "Club & Co" }] }] }
};
const source = fs.readFileSync("dashboard/desk-tools.ts", "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const context = { exports: {}, document, window: { scrollTo() {}, setTimeout }, fetch: async () => ({ ok: true, json: async () => payload }), Date, console };
vm.runInNewContext(compiled, context);
const tools = context.exports.mountDeskTools({ state: { data: null, active: "overview" }, activate() {}, status() {} });
(async () => {
  await tools.openResearch();
  const html = views.get("research").innerHTML;
  for (const expected of ["Research evidence: latest usable item captured", "FPL snapshot: Snapshot is 10.0 hours old.",
    "Official FPL player news", "captured, unverified", "Club &amp; Co", "unverified claim",
    "captured " + new Date(capturedAt).toLocaleString(), "Claim detail",
    "3 additional source item(s) omitted", "Exact news &lt;b&gt;untrusted&lt;/b&gt;", "&lt;script&gt;"]) {
    if (!html.includes(expected)) throw new Error("Missing safely rendered research detail: " + expected);
  }
  if (html.includes("<script>")) throw new Error("Player attribution was not HTML-escaped");
  payload.state = "failed";
  payload.latest_success_at_utc = null;
  payload.source_summaries[0].state = "unavailable";
  await tools.openResearch();
  const failedHtml = views.get("research").innerHTML;
  if (!failedHtml.includes("Collection status: failed.") || !failedHtml.includes("The latest collection did not retrieve evidence successfully.")) {
    throw new Error("Failed collection state was not explained in the Research Desk");
  }
  payload.state = "invalid";
  payload.valid = false;
  await tools.openResearch();
  const invalidHtml = views.get("research").innerHTML;
  if (!invalidHtml.includes("Saved research packet is invalid") || invalidHtml.includes("Exact news")) {
    throw new Error("Invalid source records were incorrectly shown as usable evidence");
  }
  payload.state = "stale";
  payload.valid = true;
  payload.latest_evidence_at_utc = "2026-09-22T10:00:00+00:00";
  payload.research_age_hours = 48;
  payload.source_summaries[0].stale_excerpt_indexes = [0];
  await tools.openResearch();
  if (!views.get("research").innerHTML.includes("stale captured, unverified")) {
    throw new Error("Old item timestamp was not visibly marked stale");
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
''';
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dashboard_scripts_are_deferred_in_document_order(self):
        source = Path("dashboard/index.html").read_text(encoding="utf-8")
        self.assertIn('<script type="module" src="/app.ts"></script>', source)
        for legacy in ("app.js", "decision-states.js", "desk-tools.js", "wayfinding.js"):
            self.assertNotIn(legacy, source)
        self.assertLess(source.index("<script"), source.index("</body>"))

    def test_decision_feedback_is_explicit_not_self_observing(self):
        decision = Path("dashboard/decision-states.ts").read_text(encoding="utf-8")
        app = Path("dashboard/app.ts").read_text(encoding="utf-8")
        self.assertNotIn("MutationObserver", decision)
        self.assertIn("mountDecisionStates(readData", decision)
        self.assertIn("refreshDecisionStates = mountDecisionStates", app)

    def test_static_assets_are_cacheable_but_api_json_is_not(self):
        server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-cache")
                html = response.read().decode("utf-8")
            import re
            asset = re.search(r'(?:src|href)="(/assets/[^" ]+\.(?:js|css))"', html)
            self.assertIsNotNone(asset, "Built index must reference a hashed JS or CSS asset")
            with urlopen(f"http://127.0.0.1:{server.server_port}{asset.group(1)}") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Cache-Control"], "public, max-age=300")
            with urlopen(f"http://127.0.0.1:{server.server_port}/api/workflow-status") as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        finally:
            server.shutdown()
            server.server_close()


class StaticBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dist = Path(self.tmp.name) / "dist"
        patcher = patch.object(dashboard, "STATIC_DIST", self.dist)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read().decode("utf-8")
        finally:
            connection.close()

    def build_dist(self):
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text('<script type="module" src="/assets/index-abc123.js"></script>', encoding="utf-8")
        (self.dist / "assets" / "index-abc123.js").write_text("console.log('built');", encoding="utf-8")
        (self.dist / "assets" / "index-abc123.css").write_text("body{}", encoding="utf-8")

    def test_missing_bundle_returns_build_hint_instead_of_typescript_source(self):
        for path in ("/", "/index.html", "/app.ts", "/assets/index-abc123.js"):
            status, content_type, body = self.get(path)
            self.assertEqual(status, 503, path)
            self.assertTrue(content_type.startswith("text/plain"), path)
            self.assertIn("npm run build --prefix dashboard", body)
            self.assertNotIn("<script", body)
            self.assertNotIn("/app.ts\"", body)

    def test_missing_bundle_leaves_json_api_available(self):
        status, content_type, _ = self.get("/api/workflow-status")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("application/json"))

    def test_built_bundle_serves_index_and_hashed_assets(self):
        self.build_dist()
        status, content_type, body = self.get("/")
        self.assertEqual((status, content_type.split(";")[0]), (200, "text/html"))
        self.assertIn("/assets/index-abc123.js", body)
        status, content_type, _ = self.get("/assets/index-abc123.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", content_type)
        status, content_type, _ = self.get("/assets/index-abc123.css")
        self.assertEqual((status, content_type.split(";")[0]), (200, "text/css"))

    def test_built_bundle_does_not_serve_files_outside_dist(self):
        self.build_dist()
        (Path(self.tmp.name) / "secret.txt").write_text("outside", encoding="utf-8")
        for path in ("/../secret.txt", "/app.ts", "/missing.js"):
            status, _, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn("outside", body)


class PrivateTeamDashboardTests(unittest.TestCase):
    def test_usable_account_data_replaces_public_transfer_caveat(self):
        decision = {"unconfirmed_inputs": ["Free transfers and selling prices are not in the public snapshot.", "Rivals' moves are unavailable."]}
        dashboard.apply_private_inputs(decision, {"usable": False, "state": "stale"})
        self.assertEqual(len(decision["unconfirmed_inputs"]), 2)
        dashboard.apply_private_inputs(decision, {"usable": True, "free_transfers": 2, "captured_at_utc": "2026-09-25T13:23:04+00:00"})
        self.assertEqual(decision["unconfirmed_inputs"], ["Rivals' moves are unavailable."])
        self.assertIn("Free transfers (2)", decision["confirmed_inputs"][0])
        self.assertIn("2026-09-25T13:23:04", decision["confirmed_inputs"][0])

    def test_dashboard_api_reports_missing_account_data_without_changing_behaviour(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(dashboard, "PRIVATE_TEAM", Path(directory) / "none.json"):
            server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/dashboard") as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
        self.assertEqual(payload["private_team"]["state"], "missing")
        self.assertFalse(payload["private_team"]["usable"])
        self.assertNotIn("confirmed_inputs", payload["decision"])
        self.assertTrue(any(item.startswith("Free transfers and selling prices") for item in payload["decision"]["unconfirmed_inputs"]))

    def test_account_data_is_only_served_on_loopback_binding(self):
        config = {"team_id": 1}
        with patch.object(dashboard.private_team, "load", return_value={"state": "ready", "usable": True, "bank": 1}) as load:
            for host in ("0.0.0.0", "192.168.1.5", "::"):
                handler = SimpleNamespace(server=SimpleNamespace(server_address=(host, 8080)))
                result = dashboard.Handler.private_data(handler, config, {})
                self.assertEqual((result["state"], result["usable"]), ("disabled", False), host)
                self.assertNotIn("bank", result)
            load.assert_not_called()
            handler = SimpleNamespace(server=SimpleNamespace(server_address=("127.0.0.1", 8765)))
            self.assertTrue(dashboard.Handler.private_data(handler, config, {})["usable"])
            load.assert_called_once()

    def test_private_team_panel_escapes_values_and_labels_state(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const ts = require("./dashboard/node_modules/typescript");
const source = fs.readFileSync("dashboard/team-decision-desk.ts", "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const context = { exports: {}, Intl, Date };
vm.runInNewContext(output, context);
const render = context.exports.renderPrivateTeamPanel;
if (render(undefined) !== "") throw new Error("Absent data must render nothing");
const missing = render({ state: "missing", usable: false, message: "<img src=x>", captured_at_utc: null, age_hours: null });
if (!missing.includes("&lt;img src=x&gt;") || missing.includes("<img") || missing.includes("Free transfers")) throw new Error("Missing state unsafe or shows numbers");
const ready = { state: "ready", usable: true, message: "From your FPL account", captured_at_utc: "2026-09-25T13:23:04Z", age_hours: 1,
  free_transfers: 2, transfers_made: 0, bank: 1, hit_cost: 4, team_value: 1012,
  chips: [{ name: "<b>x</b>", status: "available", played_gameweeks: [], window: [1, 19], pending: false },
          { name: "wildcard", status: "played", played_gameweeks: [4], window: [2, 19], pending: false }] };
const html = render(ready);
for (const value of ["£0.1m", "£101.2m", "−4 pts", "&lt;b&gt;x&lt;/b&gt;", "Wildcard", "played GW4", "Not transfer advice", "never deployed"]) {
  if (!html.includes(value)) throw new Error("Expected content missing: " + value);
}
if (html.includes("<b>x")) throw new Error("Unsafe chip name rendered");
if (!render({ ...ready, free_transfers: "unlimited" }).includes("Unlimited")) throw new Error("Unlimited transfers not shown");
const stale = render({ ...ready, state: "stale", usable: false, message: "A deadline has passed" });
if (!stale.includes("evidence-warning") || !stale.includes("A deadline has passed")) throw new Error("Stale state not warned");
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


class LineupHelperUiTests(unittest.TestCase):
    def test_dashboard_api_includes_lineup_view_model(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(dashboard, "PRIVATE_TEAM", Path(directory) / "none.json"):
            server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/dashboard") as response:
                    payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
        self.assertIn(payload["lineup"]["state"], ("ready", "unavailable"))
        if payload["lineup"]["state"] == "ready":
            self.assertIn("public snapshot", payload["lineup"]["changes"]["source"])

    def test_lineup_panel_escapes_values_and_shows_refusals(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const ts = require("./dashboard/node_modules/typescript");
const source = fs.readFileSync("dashboard/lineup-helper.ts", "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const context = { exports: {} };
vm.runInNewContext(output, context);
const render = context.exports.renderLineupHelper;
if (render(undefined) !== "") throw new Error("Absent lineup must render nothing");
const refused = render({ state: "unavailable", reason: "<b>stale</b>", gameweek: 6 });
if (!refused.includes("&lt;b&gt;stale&lt;/b&gt;") || refused.includes("<b>stale") || refused.includes("Captain")) throw new Error("Refusal unsafe or shows picks");
const player = (id, name, role, extra = {}) => ({ id, name, team: "T&1", role, estimate: 5, chance: null, fixtures: 1, eligible: true, flags: [], blockers: [], reason: "Starts: <i>ok</i>.", ...extra });
const lines = { GK: [player(1, "<img src=x>", "GK")], DEF: [player(2, "D", "DEF")], MID: [player(3, "M", "MID")], FWD: [player(4, "F", "FWD")] };
const data = { state: "ready", gameweek: 6, deadline_utc: "2026-10-10T10:00:00Z", formation: "4-4-2", xi_estimate_total: 50,
  lines, bench: [player(5, "Keeper2", "GK"), player(6, "Doubt", "FWD", { flags: ["doubtful: 75% chance"] })],
  captain: { id: 3, name: "M", estimate: 5, flags: [] }, vice: { id: 4, name: "F", estimate: 5, flags: [] },
  changes: { source: "your FPL account (captured lineup)", start: ["<s>x</s>"], bench: [], captain: { from: "F", to: "M" }, vice: null, bench_order_changed: true, none: false },
  bench_boost: { bench_total: 10, available: true, all_bench_playing: true, rule_of_thumb: 12, hint: "Not this week <x>" }, method: "FPL estimate method" };
const players = [{ id: 6, news: "<script>n</script>", research: [{ text: "<svg onload=x>", publisher: "Pub", stale: false, verification: "captured, unverified" }] }];
const html = render(data, players);
for (const value of ["&lt;img src=x&gt;", "T&amp;1", "&lt;i&gt;ok&lt;/i&gt;", "&lt;s&gt;x&lt;/s&gt;", "&lt;script&gt;n&lt;/script&gt;", "&lt;svg onload=x&gt;", "captured, unverified", "FPL est. 5", "F → M", "Not this week &lt;x&gt;", "lineup-armband", "B1", "Jev", "not a forecast by this app"]) {
  if (!html.includes(value)) throw new Error("Expected content missing: " + value);
}
if (/<(img|script|svg|s|i)[ >]/.test(html.replace(/<(section|div|h2|h3|p|ul|li|span|strong)\b[^>]*>/g, ""))) throw new Error("Unsafe markup rendered");
if (!html.includes("is-flagged")) throw new Error("Doubtful player not flagged");
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


class TacticsBoardTests(unittest.TestCase):
    def run_board_script(self, body):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const ts = require("./dashboard/node_modules/typescript");
const load = (file, req) => {
  const out = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const context = { exports: {}, require: req, Math, JSON, Number, Map, Set, window: {} };
  vm.runInNewContext(out, context);
  return context.exports;
};
const kits = load("dashboard/kits.ts", () => ({}));
const board = load("dashboard/tactics-board.ts", (name) => (name === "./kits" ? kits : {}));
const p = (id, role, estimate, extra = {}) => ({ id, name: "P" + id, team: "MCI", role, estimate, chance: null, fixtures: 1, eligible: true, flags: [], blockers: [], reason: "r", ...extra });
const data = { state: "ready", gameweek: 6, deadline_utc: "x", formation: "4-4-2", xi_estimate_total: 55,
  lines: { GK: [p(1, "GK", 4)], DEF: [p(2, "DEF", 6), p(3, "DEF", 5), p(4, "DEF", 5), p(5, "DEF", 4)], MID: [p(6, "MID", 9), p(7, "MID", 6), p(8, "MID", 5), p(9, "MID", 4)], FWD: [p(10, "FWD", 7), p(11, "FWD", 4)] },
  bench: [p(12, "GK", 2), p(13, "DEF", 3), p(14, "MID", 2), p(15, "FWD", 1, { eligible: false, blockers: ["FPL lists injured"] })],
  captain: { id: 6, name: "P6", estimate: 9, flags: [] }, vice: { id: 10, name: "P10", estimate: 7, flags: [] },
  changes: { source: "the public snapshot <b>", current_xi: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 13], start: ["P11"], bench: ["P13"], captain: null, vice: null, bench_order_changed: false, none: false },
  bench_boost: { bench_total: 8, available: null, all_bench_playing: false, rule_of_thumb: 12, hint: "Hint <i>" }, method: "m" };
const players = board.boardPlayers(data);
const start = board.suggestedState(data);
const check = (cond, msg) => { if (!cond) throw new Error(msg); };
''' + body
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_swaps_follow_fpl_formation_rules(self):
        self.run_board_script(r'''
let r = board.swapMagnets(start, 9, 13, players);
check(r.ok && r.state.xi.includes(13) && r.state.bench.includes(9), "MID out, DEF in should be legal (5-3-2)");
check(board.formationOf(r.state.xi, players).DEF === 5, "formation recount");
r = board.swapMagnets(start, 10, 13, players);
check(r.ok, "4 DEF + 1 FWD: 5-4-1 legal");
r = board.swapMagnets(r.state, 11, 14, players);
check(!r.ok && /legal formation/.test(r.message), "no forwards left must be illegal");
r = board.swapMagnets(start, 1, 13, players);
check(!r.ok && /Keepers only/.test(r.message), "GK only swaps with GK");
r = board.swapMagnets(start, 1, 12, players);
check(r.ok && r.state.bench[0] === 1, "keeper swap keeps GK slot first");
r = board.swapMagnets(start, 2, 3, players);
check(!r.ok && /already starting/.test(r.message), "two starters is a no-op");
r = board.swapMagnets(start, 13, 14, players);
check(r.ok && r.state.bench.join() === "12,14,13,15", "bench reorder");
r = board.swapMagnets(start, 12, 13, players);
check(!r.ok && /Keepers only/.test(r.message), "backup keeper slot cannot take an outfield player");
check(board.swapMagnets(start, 2, 999, players).ok === false, "unknown id refused");
''')

    def test_totals_and_warnings_follow_the_tried_lineup(self):
        self.run_board_script(r'''
check(board.boardTotal(start, players) === 59, "suggested total " + board.boardTotal(start, players));
let r = board.swapMagnets(start, 6, 14, players);
check(board.boardTotal(r.state, players) === 52, "total after benching captain");
const w = board.boardWarnings(r.state, data, players);
check(w.some((x) => /captain P6 is on the bench/.test(x)), "captain benched warning");
r = board.swapMagnets(start, 11, 15, players);
check(board.boardWarnings(r.state, data, players).some((x) => /lists as out: P15/.test(x)), "starting an injured player warns");
check(board.boardWarnings(start, data, players).length === 0, "suggestion has no warnings");
''')

    def test_saved_board_is_validated_and_storage_failures_are_safe(self):
        self.run_board_script(r'''
const store = () => { const m = new Map(); return { getItem: (k) => m.has(k) ? m.get(k) : null, setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k), m }; };
const s = store();
const tried = board.swapMagnets(start, 9, 13, players).state;
board.saveBoard(s, 6, tried);
check(s.m.has("fpl-brief:board:v1:gw6"), "namespaced versioned key");
check(JSON.stringify(board.loadBoard(s, data, players)) === JSON.stringify(tried), "round trip");
const bad = [ "{not json", JSON.stringify({ xi: [1], bench: [] }), JSON.stringify({ xi: [...tried.xi.slice(0, 10), 99], bench: tried.bench }),
  JSON.stringify({ xi: [1, 12, 2, 3, 4, 5, 6, 7, 8, 9, 10], bench: [13, 11, 14, 15] }), JSON.stringify({ xi: tried.xi, bench: [13, 12, 14, 15].map((x) => x === 13 ? 9 : x) }),
  JSON.stringify({ xi: [...tried.xi.slice(0, 10), "11"], bench: tried.bench }) ];
for (const raw of bad) { s.setItem("fpl-brief:board:v1:gw6", raw); check(board.loadBoard(s, data, players) === null, "rejects " + raw); }
const throwing = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); }, removeItem() { throw new Error("denied"); } };
check(board.loadBoard(throwing, data, players) === null, "throwing storage read");
board.saveBoard(throwing, 6, tried); board.saveBoard(throwing, 6, null); board.saveBoard(null, 6, tried);
board.saveBoard(s, 6, null);
check(!s.m.has("fpl-brief:board:v1:gw6"), "reset clears the key");
''')

    def test_board_event_handling_guards_regressions(self):
        source = Path("dashboard/tactics-board.ts").read_text(encoding="utf-8")
        mount = source[source.index("export function mountTacticsBoard"):]
        self.assertNotIn("suppressClick", mount, "a one-shot click flag swallowed the next real click after a drag")
        self.assertIn("ignoreClicksUntil", mount)
        for event in ("pointercancel", "blur"):
            self.assertIn(f'window.addEventListener("{event}", cancelDrag, {{ signal }})', mount)
        self.assertIn('ghost.setAttribute("aria-hidden", "true")', mount)
        self.assertIn('ghost.setAttribute("inert", "")', mount)
        self.assertIn("refocus(id)", mount)
        self.assertIn("window.clearInterval(timer)", mount, "the deadline clock must stop when the board unmounts")
        self.assertEqual(mount.count("addEventListener(") - mount.count("signal.addEventListener("), mount.count("signal })"),
                         "every board listener must be removed when the board re-mounts")

    def test_plan_cache_and_mount_ordering_guards(self):
        app = Path("dashboard/app.ts").read_text(encoding="utf-8")
        self.assertIn("${snapshot.generated_at_utc ?? \"\"}|${data.private_team?.captured_at_utc ?? \"\"}", app, "plan cache must follow data reloads")
        board = Path("dashboard/tactics-board.ts").read_text(encoding="utf-8")
        mount = board[board.index("export function mountTacticsBoard"):]
        self.assertLess(mount.index("mounted?.abort()"), mount.index('data.state !== "ready") return'), "abort the old board before any early return")

    def test_board_markup_escapes_values_and_shows_refusals(self):
        self.run_board_script(r'''
check(board.renderTacticsBoard(undefined) === "", "no data renders nothing");
const refused = board.renderTacticsBoard({ state: "unavailable", reason: "<img src=x>", gameweek: 6 });
check(refused.includes("&lt;img src=x&gt;") && !refused.includes("<img") && !refused.includes("magnet"), "refusal escaped, no magnets");
data.changes.start = ["<s>x</s>"];
const html = board.renderTacticsBoard(data);
for (const v of ["&lt;s&gt;x&lt;/s&gt;", "the public snapshot &lt;b&gt;", "Hint &lt;i&gt;", "Only saved in this browser", "Make real changes in the FPL app", "not a forecast by this app", "Jev"]) check(html.includes(v), "missing " + v);
check(!/<(s|b|i)>/.test(html), "unescaped markup");
check(kits.jerseySvg("NEW").includes("clip-path") && kits.jerseySvg("ZZZ").includes("#9AA5A0") && kits.jerseySvg("MCI", true).includes("#C9F24B"), "kits: stripes, fallback, keeper");
''')


class PrivateTeamImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        local = Path(self.tmp.name)
        for name, value in (("LOCAL", local), ("PRIVATE_TEAM", local / "private_team.json")):
            patcher = patch.object(dashboard, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        picks = [{"element": pid, "position": index + 1, "selling_price": 50, "purchase_price": 50, "is_captain": index == 0, "is_vice_captain": index == 1}
                 for index, pid in enumerate(range(101, 116))]
        self.snapshot = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "squad_snapshot": {"picks": [{"element": p["element"]} for p in picks]},
                         "events": {"next": {"deadline_time": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()}}}
        self.my_team = {"picks": picks, "chips": [], "transfers": {"cost": 4, "status": "cost", "limit": 1, "made": 0, "bank": 3, "value": 1000}}
        patcher = patch.object(dashboard, "load_config", return_value={"team_id": 42, "stale_after_hours": 8})
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(dashboard.Handler, "api_data", lambda handler: (self.snapshot, {"players": [], "teams": []}))
        patcher.start(); self.addCleanup(patcher.stop)
        self.server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, body, headers=None, raw=None):
        host = f"127.0.0.1:{self.server.server_port}"
        payload = raw if raw is not None else json.dumps(body).encode("utf-8")
        base = {"Host": host, "Origin": f"http://{host}", "Content-Type": "application/json", "Content-Length": str(len(payload))}
        base.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            connection.putrequest("POST", "/api/private-team", skip_host=True, skip_accept_encoding=True)
            for key, value in base.items():
                if value is not None:
                    connection.putheader(key, value)
            connection.endheaders(payload)
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()

    def saved(self):
        return dashboard.PRIVATE_TEAM.exists()

    def leftovers(self):
        return [path.name for path in dashboard.LOCAL.iterdir() if path.suffix == ".tmp"]

    def test_valid_paste_is_wrapped_validated_and_saved(self):
        status, body = self.post(self.my_team)
        self.assertEqual(status, 200, body)
        self.assertEqual((body["state"], body["usable"], body["free_transfers"], body["bank"]), ("ready", True, 1, 3))
        record = json.loads(dashboard.PRIVATE_TEAM.read_text(encoding="utf-8"))
        self.assertEqual((record["team_id"], record["schema_version"]), (42, 1))
        self.assertIn("pasted by the manager", record["source"])
        self.assertNotIn("password", json.dumps(record).lower())
        status, _ = self.post({"my_team": self.my_team})
        self.assertEqual(status, 200, "a previously exported record wrapper is also accepted")
        self.assertEqual(self.leftovers(), [])

    def test_only_known_fpl_fields_are_saved(self):
        sneaky = dict(self.my_team, password="hunter2", cookie="sessionid=abc")
        sneaky["picks"] = [dict(pick, token="t0k") for pick in self.my_team["picks"]]
        sneaky["transfers"] = dict(self.my_team["transfers"], secret="s")
        sneaky["chips"] = [{"name": "bboost", "status_for_entry": "available", "played_by_entry": [], "start_event": 1, "stop_event": 19, "cookie": "c"}]
        status, body = self.post(sneaky)
        self.assertEqual(status, 200, body)
        saved = dashboard.PRIVATE_TEAM.read_text(encoding="utf-8")
        for leaked in ("hunter2", "sessionid", "t0k", '"secret"', '"cookie"', '"password"', '"token"'):
            self.assertNotIn(leaked, saved)
        self.assertIn('"selling_price"', saved)

    def test_known_fields_keep_only_plain_values(self):
        crafted = dict(self.my_team)
        crafted["picks"] = [dict(pick, is_captain={"cookie": "x1"}, multiplier=["a"], element_type="y" * 500) for pick in self.my_team["picks"]]
        crafted["transfers"] = dict(self.my_team["transfers"], status={"cookie": "x2"})
        crafted["chips"] = [{"name": {"cookie": "x3"}, "status_for_entry": "available", "played_by_entry": [1, {"c": 1}], "start_event": 1, "stop_event": 19}]
        crafted["picks_last_updated"] = {"cookie": "x4"}
        status, body = self.post(crafted)
        saved = dashboard.PRIVATE_TEAM.read_text(encoding="utf-8") if dashboard.PRIVATE_TEAM.exists() else ""
        for leaked in ("x1", "x2", "x3", "x4", "yyyy", '"a"'):
            self.assertNotIn(leaked, saved, (status, body))

    def test_actions_refuse_cross_site_posts_on_loopback(self):
        for path in ("/api/refresh", "/api/research", "/api/plans/compare"):
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
            try:
                connection.putrequest("POST", path, skip_host=True)
                connection.putheader("Host", f"127.0.0.1:{self.server.server_port}")
                connection.putheader("Origin", "https://evil.example")
                connection.putheader("Content-Length", "0")
                connection.endheaders()
                self.assertEqual(connection.getresponse().status, 403, path)
            finally:
                connection.close()

    def test_deeply_nested_json_is_a_clean_400(self):
        status, body = self.post(None, raw=("[" * 20000 + "]" * 20000).encode())
        self.assertEqual(status, 400, body)
        self.assertFalse(self.saved())

    def test_api_reads_refuse_foreign_host_names_on_loopback(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            connection.putrequest("GET", "/api/workflow-status", skip_host=True)
            connection.putheader("Host", f"evil.example:{self.server.server_port}")
            connection.endheaders()
            self.assertEqual(connection.getresponse().status, 403)
        finally:
            connection.close()
        with urlopen(f"http://127.0.0.1:{self.server.server_port}/api/workflow-status") as response:
            self.assertEqual(response.status, 200)

    def test_cross_site_and_rebinding_requests_are_refused(self):
        for headers in ({"Origin": "https://evil.example"}, {"Origin": None, "Referer": "https://evil.example/x"}, {"Origin": None},
                        {"Host": f"evil.example:{self.server.server_port}", "Origin": f"http://evil.example:{self.server.server_port}"}):
            status, body = self.post(self.my_team, headers)
            self.assertEqual(status, 403, headers)
        self.assertFalse(self.saved())

    def test_off_loopback_binding_is_refused(self):
        with patch.object(dashboard, "LOOPBACK_HOSTS", {"not-this-host"}):
            status, _ = self.post(self.my_team)
        self.assertEqual(status, 403)
        self.assertFalse(self.saved())

    def test_bad_pastes_are_rejected_without_writing(self):
        wrong_team = dict(self.my_team, picks=[dict(p, element=p["element"] + 100) for p in self.my_team["picks"]])
        cases = [
            ({}, {"Content-Type": "text/plain"}, None, 415),
            (None, {}, b"{not json", 400),
            ([], {}, None, 400),
            ({"picks": []}, {}, None, 400),
            (wrong_team, {}, None, 422),
            (dict(self.my_team, transfers={"bank": -1}), {}, None, 422),
            (None, {}, b"x" * (dashboard.MAX_IMPORT_BYTES + 1), 413),
        ]
        for body, headers, raw, expected in cases:
            status, reply = self.post(body, headers, raw)
            self.assertEqual(status, expected, (body if raw is None else raw[:20], reply))
            self.assertIn("error", reply)
        self.assertFalse(self.saved())
        self.assertEqual(self.leftovers(), [])


class TransferPlanUiTests(unittest.TestCase):
    def test_plan_storage_strip_and_import_section(self):
        script = r'''
const fs = require("fs");
const vm = require("vm");
const ts = require("./dashboard/node_modules/typescript");
const load = (file) => { const context = { exports: {}, JSON, Number, Set, Map }; vm.runInNewContext(ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, context); return context.exports; };
const plan = load("dashboard/transfer-plan.ts");
const desk = load("dashboard/team-decision-desk.ts");
const check = (cond, msg) => { if (!cond) throw new Error(msg); };
const store = () => { const m = new Map(); return { getItem: (k) => m.has(k) ? m.get(k) : null, setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k), m }; };
const owned = new Set([1, 2, 3, 4]);
const s = store();
let r = plan.addTransfer([], { out: 1, in: 10 });
r = plan.addTransfer(r.plan, { out: 2, in: 11 });
r = plan.addTransfer(r.plan, { out: 1, in: 12 });
check(r.plan.length === 2 && r.plan.some((t) => t.out === 1 && t.in === 12), "same outgoing player is replaced");
r = plan.addTransfer(r.plan, { out: 3, in: 13 });
const full = plan.addTransfer(r.plan, { out: 4, in: 14 });
check(full.error && full.plan.length === 3, "plan capped at three");
plan.savePlan(s, 6, r.plan);
check(s.m.has("fpl-brief:plan:v1:gw6"), "namespaced key");
check(plan.loadPlan(s, 6, owned).length === 3, "round trip");
check(plan.planQuery(r.plan) === "2:11,1:12,3:13", "query " + plan.planQuery(r.plan));
for (const raw of ["{", "[1]", JSON.stringify([{ out: 9, in: 10 }]), JSON.stringify([{ out: 1, in: 2 }]), JSON.stringify([{ out: 1, in: 10 }, { out: 1, in: 11 }]), JSON.stringify([1, 2, 3, 4].map((o) => ({ out: o, in: o + 20 })))]) {
  s.setItem("fpl-brief:plan:v1:gw6", raw); check(plan.loadPlan(s, 6, owned).length === 0, "rejects " + raw);
}
check(plan.loadPlan({ getItem() { throw new Error("x"); } }, 6, owned).length === 0, "throwing storage");
plan.savePlan({ setItem() { throw new Error("x"); }, removeItem() { throw new Error("x"); } }, 6, r.plan);
plan.savePlan(s, 6, []); check(!s.m.has("fpl-brief:plan:v1:gw6"), "empty plan clears key");
const names = new Map([[1, "<b>Out</b>"], [10, "In&Co"]]);
const invalid = plan.renderPlanStrip([{ out: 1, in: 10 }], { state: "invalid", reason: "<i>no</i>" }, names);
check(invalid.includes("&lt;b&gt;Out&lt;/b&gt;") && invalid.includes("In&amp;Co") && invalid.includes("&lt;i&gt;no&lt;/i&gt;") && !/<(b|i)>/.test(invalid), "strip escaping");
const ready = plan.renderPlanStrip([{ out: 1, in: 10 }, { out: 2, in: 11 }], { state: "ready", lineup: {}, summary: { transfers: [{}, {}], budget_left: 7, free_transfers: 1, paid_transfers: 1, hit_points: 4, xi_delta: 3.5, net_delta: -0.5, method: "m" } }, names);
check(ready.includes("-0.5") && ready.includes("1 of 1 free transfers") && ready.includes("hit −4") && ready.includes("£0.7m left") && ready.includes('data-remove-out="1"'), "ready summary");
check(plan.renderPlanStrip([], null, names) === "", "no plan, no strip");
const missing = desk.renderPrivateTeamPanel({ state: "missing", usable: false, message: "m", captured_at_utc: null, age_hours: null }, 6572775);
check(missing.includes("https://fantasy.premierleague.com/api/my-team/6572775/") && missing.includes('rel="noopener noreferrer"') && missing.includes("never your password") && missing.includes("<details class=\"account-import\" open"), "import section on missing");
check(!desk.renderPrivateTeamPanel({ state: "missing", usable: false, message: "m" }, "6572775/../x").includes("my-team/6572775/../x"), "non-integer team id is not linked");
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


class PasswordGateTests(unittest.TestCase):
    PASSWORD = "correct horse battery staple"

    def setUp(self):
        dashboard.AUTH_FAILURES.clear()
        self.addCleanup(dashboard.AUTH_FAILURES.clear)
        dashboard.AUTH_GLOBAL_FAILURES.clear()
        self.addCleanup(dashboard.AUTH_GLOBAL_FAILURES.clear)
        self.server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, method, path, cookie=None, body=None, forwarded=None, origin="same", proto=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        headers = {}
        if origin == "same":
            headers["Origin"] = self.origin
        elif origin:
            headers["Origin"] = origin
        if cookie:
            headers["Cookie"] = f"fpl_session={cookie}"
        if forwarded:
            headers["X-Forwarded-For"] = forwarded
        if proto:
            headers["X-Forwarded-Proto"] = proto
        payload = body.encode("utf-8") if isinstance(body, str) else body
        if method in ("POST", "PUT"):
            headers["Content-Length"] = str(len(payload or b""))
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read().decode("utf-8", "replace")
        finally:
            connection.close()

    def login(self, password=None, remember=True, next_path="/", forwarded=None, proto=None):
        form = urlencode({"password": self.PASSWORD if password is None else password, "remember": "1" if remember else "", "next": next_path})
        return self.request("POST", "/login", body=form, forwarded=forwarded, proto=proto)

    def token_from(self, headers):
        cookie = headers.get("set-cookie", "")
        return cookie.split(";")[0].split("=", 1)[1] if cookie.startswith("fpl_session=") else None

    def test_open_when_no_password_is_configured(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DASHBOARD_PASSWORD", None); os.environ.pop("REQUIRE_PASSWORD", None)
            self.assertEqual(self.request("GET", "/api/workflow-status")[0], 200)
            self.assertEqual(self.request("GET", "/login")[0], 303)

    def test_pages_redirect_to_sign_in_and_api_returns_401_without_a_popup(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}):
            status, headers, _ = self.request("GET", "/")
            self.assertEqual(status, 303)
            self.assertEqual(headers["location"], "/login?next=%2F")
            status, headers, _ = self.request("GET", "/assets/x.js?v=1")
            self.assertEqual((status, headers["location"]), (303, "/login?next=%2Fassets%2Fx.js%3Fv%3D1"))
            for method, path in (("GET", "/api/dashboard"), ("GET", "/api/plan?transfers=1:2"), ("POST", "/api/refresh"), ("PUT", "/api/plans")):
                status, headers, body = self.request(method, path)
                self.assertEqual(status, 401, (method, path))
                self.assertNotIn("www-authenticate", headers)
                self.assertIn("Sign in required", body)
            status, headers, body = self.request("GET", "/login?next=/players")
            self.assertEqual(status, 200)
            self.assertIn('name="next" value="/players"', body)
            self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])
            self.assertEqual(headers["x-frame-options"], "DENY")
            self.assertEqual(self.request("GET", "/healthz")[0], 200)

    def test_correct_password_sets_a_hardened_cookie_and_returns_to_next(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}):
            status, headers, _ = self.login(next_path="/?view=squad", proto="https")
            self.assertEqual((status, headers["location"]), (303, "/?view=squad"))
            cookie = headers["set-cookie"]
            for flag in ("HttpOnly", "SameSite=Lax", "Path=/", "Secure", f"Max-Age={30 * 24 * 3600}"):
                self.assertIn(flag, cookie)
            token = self.token_from(headers)
            self.assertEqual(self.request("GET", "/api/workflow-status", cookie=token)[0], 200)
            self.assertEqual(self.request("GET", "/login", cookie=token)[0], 303, "signed-in visitors skip the form")
            status, headers, _ = self.login(remember=False)
            self.assertNotIn("Max-Age", headers["set-cookie"])
            self.assertNotIn("Secure", headers["set-cookie"], "plain http on loopback is not marked Secure")

    def test_wrong_password_shows_an_error_and_sets_nothing(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}):
            status, headers, body = self.login(password="nope")
            self.assertEqual(status, 401)
            self.assertNotIn("set-cookie", headers)
            self.assertIn("password isn", body)
            self.assertNotIn("nope", body)
            self.assertNotIn(self.PASSWORD, body)

    def test_tampered_expired_and_rotated_tokens_are_rejected(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}):
            token = self.token_from(self.login()[1])
            expiry, signature = token.split(".")
            for bad in (f"{int(expiry) + 999}.{signature}", f"{expiry}.{'0' * 64}", "garbage", f"{expiry}.{signature}x", ""):
                self.assertEqual(self.request("GET", "/api/workflow-status", cookie=bad)[0], 401, bad)
            expired = web_session.make_token(self.PASSWORD, False, now=time.time() - 13 * 3600)
            self.assertEqual(self.request("GET", "/api/workflow-status", cookie=expired)[0], 401)
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": "a brand new password"}):
            self.assertEqual(self.request("GET", "/api/workflow-status", cookie=token)[0], 401, "changing the password signs everyone out")

    def test_next_is_limited_to_local_paths(self):
        for value in ("//evil.example", "/\\evil.example", "https://evil.example", "javascript:alert(1)", "evil", "/ok\r\nSet-Cookie: x=1", "/" + "a" * 600):
            self.assertEqual(web_session.safe_next(value), "/", value)
        self.assertEqual(web_session.safe_next("/players?x=1"), "/players?x=1")
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}):
            self.assertEqual(self.login(next_path="//evil.example")[1]["location"], "/")
            self.assertIn('value="/"', self.request("GET", "/login?next=https://evil.example")[2])

    def test_signed_in_actions_must_come_from_this_site(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}):
            token = self.token_from(self.login()[1])
            self.assertEqual(self.request("PUT", "/api/plans", cookie=token, origin="https://evil.example")[0], 403)
            self.assertEqual(self.request("PUT", "/api/plans", cookie=token, origin=None)[0], 403)
            self.assertEqual(self.request("PUT", "/api/plans", cookie=token)[0], 405, "same-origin reaches the handler")
            self.assertEqual(self.request("POST", "/login", body="password=x", origin="https://evil.example")[0], 403)

    def test_review_edge_cases_do_not_block_sign_in(self):
        self.assertEqual(web_session.safe_next("/Ā"), "/", "non-ASCII next falls back safely")
        self.assertEqual(web_session.cookie_token('a=b c; other={"x": 1}; fpl_session=abc.def'), "abc.def", "malformed neighbours don't hide the session")
        self.assertEqual(web_session.cookie_token('fpl_session="q.v"'), "q.v")
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}):
            status, headers, _ = self.login(next_path="/Ā")
            self.assertEqual((status, headers["location"]), (303, "/"))
            crowded = urlencode([("password", self.PASSWORD)] + [(f"f{i}", "x") for i in range(12)])
            self.assertEqual(self.request("POST", "/login", body=crowded)[0], 400)
            token = self.token_from(self.login()[1])
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
            try:
                connection.request("GET", "/api/workflow-status", headers={"Cookie": f"junk=a b c; fpl_session={token}"})
                self.assertEqual(connection.getresponse().status, 200)
            finally:
                connection.close()

    def test_logout_clears_the_cookie(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}):
            status, headers, _ = self.request("GET", "/logout")
            self.assertEqual((status, headers["location"]), (303, "/login"))
            self.assertIn("Max-Age=0", headers["set-cookie"])

    def test_failed_sign_ins_are_rate_limited_per_client_and_globally(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}):
            for _ in range(dashboard.AUTH_MAX_FAILURES):
                self.assertEqual(self.login(password="guess", forwarded="203.0.113.9")[0], 401)
            status, headers, body = self.login(forwarded="203.0.113.9")
            self.assertEqual(status, 429)
            self.assertIn("retry-after", headers)
            self.assertIn("Too many wrong passwords", body)
            self.assertEqual(self.login(forwarded="198.51.100.7")[0], 303, "other clients unaffected")
            with patch.object(dashboard.time, "monotonic", return_value=dashboard.time.monotonic() + dashboard.AUTH_WINDOW_SECONDS + 1):
                self.assertEqual(self.login(forwarded="203.0.113.9")[0], 303)
            dashboard.AUTH_FAILURES.clear(); dashboard.AUTH_GLOBAL_FAILURES.clear()
            for _ in range(12):
                self.login(password="guess", forwarded="198.51.100.77, 203.0.113.60")
            self.assertEqual(self.login(forwarded="203.0.113.61")[0], 303, "a spoofed chain cannot lock out another visitor")
            dashboard.AUTH_FAILURES.clear(); dashboard.AUTH_GLOBAL_FAILURES.clear()
            with patch.object(dashboard, "AUTH_GLOBAL_MAX_FAILURES", 15):
                for i in range(15):
                    self.login(password="guess", forwarded=f"192.0.2.{i}")
                self.assertEqual(self.login(forwarded="192.0.2.200")[0], 429)

    def test_fails_closed_when_required_but_unset(self):
        with patch.dict(os.environ, {"REQUIRE_PASSWORD": "1"}):
            os.environ.pop("DASHBOARD_PASSWORD", None)
            status, _, body = self.request("GET", "/api/dashboard")
            self.assertEqual(status, 503)
            self.assertIn("not configured", body)
            self.assertIn(self.request("GET", "/healthz")[0], (200, 503))

    def test_static_assets_are_privately_cached_behind_a_password(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}):
            assets = sorted((dashboard.STATIC_DIST / "assets").glob("*.js"))
            if not assets:
                self.skipTest("frontend not built")
            token = self.token_from(self.login()[1])
            status, headers, _ = self.request("GET", f"/assets/{assets[0].name}", cookie=token)
            self.assertEqual(status, 200)
            self.assertTrue(headers.get("cache-control", "").startswith("private"), headers.get("cache-control"))
            self.assertEqual(self.request("HEAD", "/healthz")[0], 200)
            self.assertEqual(self.request("HEAD", "/config.json")[0], 405)

    def test_failure_table_is_bounded(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": self.PASSWORD}), patch.object(dashboard, "AUTH_MAX_CLIENTS", 5):
            for index in range(12):
                self.login(password="x", forwarded=f"192.0.2.{index}")
            self.assertLessEqual(len(dashboard.AUTH_FAILURES), 5)
