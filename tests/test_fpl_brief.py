import unittest

from fpl_brief.analyze import compare_squads, select_rivals
from fpl_brief.api import Client, FetchError
import urllib.error


class LeagueAnalysisTests(unittest.TestCase):
    def test_selects_top_and_nearby_rivals_without_duplicates(self):
        standings = [
            {"entry": 1, "rank": 1, "total": 100},
            {"entry": 2, "rank": 2, "total": 90},
            {"entry": 3, "rank": 2, "total": 90},
            {"entry": 4, "rank": 4, "total": 80},
            {"entry": 5, "rank": 5, "total": 70},
        ]
        rivals, user = select_rivals(standings, 3, top_count=2, nearby=1)
        self.assertEqual(user["entry"], 3)
        self.assertEqual([row["entry"] for row in rivals], [1, 2, 4])

    def test_marks_mismatched_snapshots_non_comparable(self):
        result = compare_squads({"entry_history": {"event": 3}, "picks": []}, {"entry_history": {"event": 4}, "picks": []})
        self.assertFalse(result["comparable"])
        self.assertEqual(result["user_event"], 3)

    def test_compares_shared_players_when_snapshot_matches(self):
        user = {"entry_history": {"event": 3}, "picks": [{"element": 1}, {"element": 2}]}
        rival = {"entry_history": {"event": 3}, "picks": [{"element": 2}, {"element": 3}]}
        result = compare_squads(user, rival)
        self.assertTrue(result["comparable"])
        self.assertEqual(result["shared"], [2])

    def test_http_404_does_not_retry(self):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)
        with self.assertRaises(FetchError):
            Client(opener=opener, sleep=lambda _: None).get("missing")
        self.assertEqual(len(calls), 1)

    def test_standings_collects_multiple_pages(self):
        class FakeClient(Client):
            def get(self, path):
                pages = {
                    "leagues-classic/1/standings/?page_standings=1": {"standings": {"results": [{"entry": 1}], "has_next": True}},
                    "leagues-classic/1/standings/?page_standings=2": {"standings": {"results": [{"entry": 2}], "has_next": False}},
                }
                return pages[path]
        self.assertEqual([row["entry"] for row in FakeClient().standings(1)], [1, 2])


if __name__ == "__main__":
    unittest.main()
