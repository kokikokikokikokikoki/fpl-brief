import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_fpl


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.boot = {
            "events": [
                {"id": 1, "finished": True, "is_current": False, "is_next": False},
                {"id": 2, "finished": False, "is_current": True, "is_next": False},
                {"id": 3, "finished": False, "is_current": False, "is_next": True, "deadline_time": "2026-09-12T10:00:00Z"},
            ],
            "teams": [{"id": 1, "short_name": "AAA"}, {"id": 2, "short_name": "BBB"}],
            "elements": [{"id": 10, "web_name": "Flagged", "team": 1, "element_type": 2, "now_cost": 45, "form": "2.0", "total_points": 12, "selected_by_percent": "3.1", "status": "d", "chance_of_playing_next_round": 75, "news": "Muscle injury"}],
        }
        self.entry = {"current_event": 2, "summary_overall_rank": None, "summary_overall_points": 42}
        self.history = {"current": [{"event": 1, "points": 50, "rank": None, "points_on_bench": 4, "bank": 10, "value": 1000, "event_transfers": 1, "event_transfers_cost": 0}], "chips": []}
        self.picks = {"entry_history": {"event": 2}, "picks": [{"element": 10, "position": 1, "multiplier": 1, "is_captain": False, "is_vice_captain": False}]}
        self.fixtures = [{"team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 4}]

    def test_digest_labels_current_and_next_gameweeks(self):
        digest = fetch_fpl.build_digest(self.boot, self.entry, self.history, self.picks, self.fixtures, "1", datetime(2026, 9, 5, tzinfo=timezone.utc))
        self.assertIn("last completed GW1", digest)
        self.assertIn("current GW2", digest)
        self.assertIn("next GW3", digest)
        self.assertIn("squad snapshot GW2", digest)

    def test_digest_handles_missing_rank_and_includes_injury_news(self):
        digest = fetch_fpl.build_digest(self.boot, self.entry, self.history, self.picks, self.fixtures, "1")
        self.assertIn("Overall rank: **?**", digest)
        self.assertIn("Flagged | doubtful | 75% chance | not supplied | Muscle injury", digest)

    def test_gameweeks_handles_preseason_and_season_end(self):
        pre = fetch_fpl.gameweeks([{"id": 1, "finished": False}])
        end = fetch_fpl.gameweeks([{"id": 38, "finished": True}])
        self.assertEqual(pre["first_unfinished"]["id"], 1)
        self.assertIsNone(pre["next"])
        self.assertEqual(end["last_finished"]["id"], 38)
        self.assertIsNone(end["first_unfinished"])

    def test_get_retries_transient_failures(self):
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"ok": true}'
        def opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise fetch_fpl.urllib.error.URLError("temporary")
            return Response()
        result = fetch_fpl.get("test", opener=opener, retries=2, sleep=lambda _: None)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
