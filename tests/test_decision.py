import unittest
from datetime import datetime, timedelta, timezone

from fpl_brief.decision import assess, snapshot_freshness


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
        self.config = {"stale_after_hours": 8, "jev": {"enabled": False}}
        self.snapshot = {
            "generated_at_utc": (self.now - timedelta(hours=1)).isoformat(),
            "squad_snapshot": {"picks": [{"element": index} for index in range(1, 16)]},
            "events": {"next": {"deadline_time": (self.now + timedelta(days=2)).isoformat()}},
            "availability": [],
            "warnings": [],
        }

    def test_current_complete_snapshot_recommends_holding_flexibility(self):
        result = assess(self.snapshot, self.config, self.now)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["recommendation"]["action"], "Hold and preserve flexibility.")
        self.assertEqual(result["jev"]["status"], "disabled")

    def test_stale_snapshot_blocks_recommendation(self):
        self.snapshot["generated_at_utc"] = (self.now - timedelta(hours=9)).isoformat()
        result = assess(self.snapshot, self.config, self.now)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("Refresh the public snapshot", " ".join(result["blockers"]))

    def test_deadline_passed_blocks_recommendation(self):
        self.snapshot["events"]["next"]["deadline_time"] = (self.now - timedelta(minutes=1)).isoformat()
        result = assess(self.snapshot, self.config, self.now)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("deadline has passed", " ".join(result["blockers"]))

    def test_availability_rule_takes_priority_when_safe_to_decide(self):
        self.snapshot["availability"] = [{"name": "Flagged", "chance": 75}]
        result = assess(self.snapshot, self.config, self.now)
        self.assertEqual(result["status"], "ready")
        self.assertIn("Investigate Flagged", result["recommendation"]["action"])

    def test_snapshot_freshness_handles_invalid_timestamp(self):
        result = snapshot_freshness({"generated_at_utc": "invalid"}, 8, self.now)
        self.assertTrue(result["stale"])
        self.assertIsNone(result["age_hours"])


if __name__ == "__main__":
    unittest.main()
