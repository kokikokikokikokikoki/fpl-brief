import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fpl_brief import private_team

NOW = datetime(2026, 9, 25, 14, tzinfo=timezone.utc)
PICK_IDS = list(range(1, 16))


def record(**overrides):
    base = {
        "schema_version": 1, "source": "fixture", "team_id": 42,
        "captured_at_utc": (NOW - timedelta(hours=1)).isoformat(),
        "my_team": {
            "picks": [{"element": pid, "position": pid, "selling_price": 50 + pid, "purchase_price": 50} for pid in PICK_IDS],
            "chips": [{"name": "bboost", "status_for_entry": "available", "played_by_entry": [], "start_event": 1, "stop_event": 19, "is_pending": False},
                      {"name": "wildcard", "status_for_entry": "played", "played_by_entry": [4], "start_event": 2, "stop_event": 19}],
            "transfers": {"cost": 4, "status": "cost", "limit": 2, "made": 0, "bank": 1, "value": 1012},
        },
    }
    base.update(overrides)
    return base


class PrivateTeamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "private_team.json"
        self.config = {"team_id": 42, "stale_after_hours": 8}
        self.snapshot = {
            "squad_snapshot": {"picks": [{"element": pid} for pid in PICK_IDS]},
            "events": {"current": {"deadline_time": (NOW - timedelta(days=3)).isoformat()},
                       "next": {"deadline_time": (NOW + timedelta(days=5)).isoformat()}},
        }

    def load(self, value=None, raw=None):
        if raw is not None:
            self.path.write_text(raw, encoding="utf-8")
        elif value is not None:
            self.path.write_text(json.dumps(value), encoding="utf-8")
        return private_team.load(self.path, self.config, self.snapshot, NOW)

    def test_missing_file_is_not_usable_and_explains_import(self):
        result = self.load()
        self.assertEqual((result["state"], result["usable"]), ("missing", False))
        self.assertIn("local/private_team.json", result["message"])
        self.assertNotIn("bank", result)

    def test_ready_record_exposes_transfers_prices_and_chips(self):
        result = self.load(record())
        self.assertEqual((result["state"], result["usable"]), ("ready", True))
        self.assertEqual(result["free_transfers"], 2)
        self.assertEqual((result["bank"], result["hit_cost"], result["team_value"]), (1, 4, 1012))
        self.assertEqual(result["prices"][3], {"selling_price": 53, "purchase_price": 50})
        self.assertEqual(result["chips"][1], {"name": "wildcard", "status": "played", "played_gameweeks": [4], "window": [2, 19], "pending": False})
        self.assertEqual(result["age_hours"], 1.0)

    def test_free_transfers_floor_at_zero_and_support_unlimited(self):
        value = record()
        value["my_team"]["transfers"].update(limit=1, made=3)
        self.assertEqual(self.load(value)["free_transfers"], 0)
        value["my_team"]["transfers"].update(limit=None, status="unlimited")
        self.assertEqual(self.load(value)["free_transfers"], "unlimited")

    def test_malformed_records_are_invalid_without_partial_numbers(self):
        cases = []
        for mutate in (
            lambda r: r["my_team"]["picks"].pop(),
            lambda r: r["my_team"]["picks"][0].update(selling_price=True),
            lambda r: r["my_team"]["picks"][0].update(selling_price=-1),
            lambda r: r["my_team"]["picks"][0].update(selling_price="55"),
            lambda r: r["my_team"]["picks"][1].update(element=1),
            lambda r: r["my_team"]["picks"][0].update(position="1"),
            lambda r: r["my_team"]["picks"][0].pop("position"),
            lambda r: r["my_team"]["transfers"].update(bank=None),
            lambda r: r["my_team"]["transfers"].update(limit="2"),
            lambda r: r["my_team"].update(chips=None),
            lambda r: r["my_team"]["chips"][0].update(played_by_entry=[0]),
            lambda r: r.update(schema_version=2),
            lambda r: r.update(captured_at_utc="yesterday"),
            lambda r: r.update(my_team=[]),
        ):
            value = copy.deepcopy(record())
            mutate(value)
            cases.append(value)
        for value in cases:
            result = self.load(value)
            self.assertEqual((result["state"], result["usable"]), ("invalid", False), value)
            self.assertNotIn("prices", result)
        self.assertEqual(self.load(raw="{not json")["state"], "invalid")
        self.assertEqual(self.load(raw="[]")["state"], "invalid")

    def test_future_capture_time_is_invalid(self):
        self.assertEqual(self.load(record(captured_at_utc=(NOW + timedelta(hours=1)).isoformat()))["state"], "invalid")

    def test_other_team_or_changed_squad_is_a_mismatch(self):
        self.assertEqual(self.load(record(team_id=7))["state"], "mismatch")
        self.snapshot["squad_snapshot"]["picks"][0]["element"] = 99
        result = self.load(record())
        self.assertEqual((result["state"], result["usable"]), ("mismatch", False))
        self.assertNotIn("prices", result)

    def test_account_freshness_uses_exact_24_hour_limit_not_snapshot_limit(self):
        self.assertEqual(self.load(record(captured_at_utc=(NOW - timedelta(hours=9)).isoformat()))["state"], "ready")
        result = self.load(record(captured_at_utc=(NOW - timedelta(hours=24, minutes=2)).isoformat()))
        self.assertEqual((result["state"], result["usable"]), ("stale", False))
        self.assertEqual(result["age_hours"], 24.0)
        self.assertIn("older than 24 hours", result["message"])
        self.assertEqual(result["free_transfers"], 2)
        self.config["private_stale_after_hours"] = 2
        self.assertEqual(self.load(record(captured_at_utc=(NOW - timedelta(hours=3)).isoformat()))["state"], "stale")

    def test_capture_time_without_timezone_is_invalid(self):
        naive = (NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()
        result = self.load(record(captured_at_utc=naive))
        self.assertEqual((result["state"], result["usable"]), ("invalid", False))

    def test_missing_deadlines_make_account_data_stale(self):
        self.snapshot["events"] = {"current": {"deadline_time": "not a time"}, "next": None}
        result = self.load(record())
        self.assertEqual((result["state"], result["usable"]), ("stale", False))
        self.assertIn("deadlines are unavailable", result["message"])

    def test_disabled_summary_carries_no_account_values(self):
        result = private_team.disabled()
        self.assertEqual((result["state"], result["usable"]), ("disabled", False))
        for key in ("prices", "bank", "free_transfers", "chips"):
            self.assertNotIn(key, result)

    def test_capture_before_a_passed_deadline_is_stale(self):
        self.snapshot["events"]["current"]["deadline_time"] = (NOW - timedelta(minutes=30)).isoformat()
        result = self.load(record())
        self.assertEqual((result["state"], result["usable"]), ("stale", False))
        self.assertIn("deadline has passed", result["message"])


if __name__ == "__main__":
    unittest.main()
