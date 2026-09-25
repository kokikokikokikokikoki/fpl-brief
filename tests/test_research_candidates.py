import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fpl_brief.candidates import lens
from fpl_brief.research import evidence_status, validate_packet
from fpl_brief.workflow import update


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        self.packet = {
            "schema_version": 1,
            "sources": [{
                "title": "Club statement", "url": "https://club.example/news", "retrieved_at_utc": self.now.isoformat(),
                "verified": True, "facts": [{"label": "confirmed", "claim": "Player trained."}],
            }],
        }

    def test_valid_packet_is_current_and_confirmed(self):
        result = evidence_status(self.packet, 24, self.now)
        self.assertTrue(result["valid"])
        self.assertFalse(result["stale"])
        self.assertEqual(result["unverified"], 0)

    def test_packet_requires_dated_http_source_and_fact(self):
        bad = {"schema_version": 1, "sources": [{"title": "Missing", "url": "http:///missing", "verified": True, "facts": []}]}
        with self.assertRaisesRegex(ValueError, "http"):
            validate_packet(bad)

    def test_stale_unverified_evidence_warns_explicitly(self):
        self.packet["sources"][0]["retrieved_at_utc"] = (self.now - timedelta(hours=25)).isoformat()
        self.packet["sources"][0]["verified"] = False
        self.packet["sources"][0]["facts"][0]["label"] = "reported"
        result = evidence_status(self.packet, 24, self.now)
        self.assertTrue(result["stale"])
        self.assertEqual(result["unverified"], 2)
        self.assertEqual(len(result["warnings"]), 2)

    def v2_packet(self, source):
        return {"schema_version": 2, "generated_at_utc": self.now.isoformat(),
                "collector": {"version": "v1", "last_run_at_utc": self.now.isoformat()},
                "sources": [source], "warnings": []}

    def source(self, **changes):
        source = {"id": "official-fpl-news", "publisher": "Fantasy Premier League",
                  "url": "https://fantasy.premierleague.com/api/bootstrap-static/",
                  "title": "Official FPL player news", "retrieved_at_utc": self.now.isoformat(),
                  "last_success_at_utc": self.now.isoformat(), "collection_state": "captured",
                  "verification_status": "unverified", "excerpts": [], "claims": [],
                  "omitted_excerpts": 0}
        source.update(changes)
        return source

    def test_successful_collection_with_no_usable_items_is_empty_not_failed(self):
        result = evidence_status(self.v2_packet(self.source()), 24, self.now)
        self.assertTrue(result["valid"])
        self.assertEqual(result["state"], "empty")
        self.assertEqual(result["last_collection_at_utc"], self.now.isoformat())

    def test_failed_collection_without_successful_evidence_is_failed(self):
        source = self.source(collection_state="unavailable", retrieved_at_utc=None,
                             last_success_at_utc=None, attempted_at_utc=self.now.isoformat(),
                             error={"code": "request_failed", "message": "Source was not captured."})
        result = evidence_status(self.v2_packet(source), 24, self.now)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["last_collection_at_utc"], self.now.isoformat())

    def test_failed_refresh_with_retained_old_evidence_is_stale(self):
        old = (self.now - timedelta(hours=30)).isoformat()
        source = self.source(collection_state="unavailable", retrieved_at_utc=old,
                             last_success_at_utc=old, attempted_at_utc=self.now.isoformat(),
                             excerpts=[{"kind": "player_news", "text": "Previously captured.",
                                        "captured_at_utc": old, "player_id": 10,
                                        "player_name": "Player", "team_id": 2, "team_name": "Club"}],
                             error={"code": "request_failed", "message": "Source was not captured."})
        result = evidence_status(self.v2_packet(source), 24, self.now)
        self.assertEqual(result["state"], "stale")
        self.assertTrue(result["stale"])

    def test_fresh_empty_source_does_not_make_other_stale_items_look_ready(self):
        old = (self.now - timedelta(hours=48)).isoformat()
        fresh = (self.now - timedelta(hours=1)).isoformat()
        stale_source = self.source(collection_state="unavailable", retrieved_at_utc=old,
                                   last_success_at_utc=old,
                                   excerpts=[{"kind": "player_news", "text": "Old item.",
                                              "captured_at_utc": old, "player_id": 10,
                                              "player_name": "Player", "team_id": 2,
                                              "team_name": "Club"}],
                                   error={"code": "request_failed", "message": "Source was not captured."})
        fresh_empty_source = {
            "id": "official-arsenal-news", "publisher": "Arsenal Football Club",
            "url": "https://www.arsenal.com/news/all/1", "title": "Official page",
            "retrieved_at_utc": fresh, "last_success_at_utc": fresh,
            "collection_state": "captured", "verification_status": "unverified",
            "excerpts": [], "claims": [],
        }
        packet = self.v2_packet(stale_source)
        packet["sources"] = [stale_source, fresh_empty_source]
        result = evidence_status(packet, 24, self.now)
        self.assertEqual(result["state"], "stale")
        self.assertTrue(result["stale"])
        self.assertEqual(result["fresh_usable_items"], 0)
        self.assertEqual(result["usable_items"], 1)
        self.assertEqual(result["research_age_hours"], 48.0)

    def test_old_excerpt_stays_stale_even_when_its_source_was_recently_fetched(self):
        old = (self.now - timedelta(hours=48)).isoformat()
        source = self.source(last_success_at_utc=self.now.isoformat(),
                             retrieved_at_utc=self.now.isoformat(),
                             excerpts=[{"kind": "player_news", "text": "Old item.",
                                        "captured_at_utc": old, "player_id": 10,
                                        "player_name": "Player", "team_id": 2,
                                        "team_name": "Club"}])
        result = evidence_status(self.v2_packet(source), 24, self.now)
        self.assertEqual(result["state"], "stale")
        self.assertTrue(result["stale"])
        self.assertEqual(result["fresh_usable_items"], 0)
        self.assertEqual(result["research_age_hours"], 48.0)
        self.assertEqual(result["source_summaries"][0]["stale_excerpt_indexes"], [0])


class CandidateLensTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        self.snapshot = {
            "generated_at_utc": self.now.isoformat(),
            "events": {"next": {"deadline_time": (self.now + timedelta(hours=6)).isoformat()}},
            "squad_snapshot": {"bank": 5, "picks": [{"element": 1, "selling_price": 70}] + [{"element": item} for item in (2, 3, 4)] + [{"element": item} for item in range(100, 111)]},
            "fixtures": {"events": {1: [{"team_h": 2, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 4}]}},
        }
        self.catalog = {"players": [
            {"id": 1, "web_name": "Outgoing", "team": 1, "element_type": 3, "now_cost": 70, "status": "a", "minutes": 900},
            {"id": 2, "web_name": "Owned A", "team": 1, "element_type": 3, "now_cost": 45, "status": "a", "minutes": 900},
            {"id": 3, "web_name": "Owned B", "team": 1, "element_type": 2, "now_cost": 45, "status": "a", "minutes": 900},
            {"id": 4, "web_name": "Owned C", "team": 1, "element_type": 4, "now_cost": 45, "status": "a", "minutes": 900},
            {"id": 5, "web_name": "Eligible", "team": 2, "element_type": 3, "now_cost": 75, "status": "a", "minutes": 900, "expected_goals": "2.0", "expected_assists": "3.0"},
            {"id": 6, "web_name": "Team Limit", "team": 1, "element_type": 3, "now_cost": 70, "status": "a", "minutes": 900},
            {"id": 7, "web_name": "Unavailable", "team": 2, "element_type": 3, "now_cost": 70, "status": "d", "minutes": 900},
            {"id": 8, "web_name": "Low Minutes", "team": 3, "element_type": 3, "now_cost": 70, "status": "a", "minutes": 300},
            {"id": 9, "web_name": "Wrong Position", "team": 3, "element_type": 2, "now_cost": 70, "status": "a", "minutes": 900},
            {"id": 10, "web_name": "Too Expensive", "team": 3, "element_type": 3, "now_cost": 76, "status": "a", "minutes": 900},
        ]}

    def test_lens_returns_only_legal_available_same_position_players(self):
        result = lens(self.snapshot, self.catalog, 1, 450, now=self.now)
        self.assertEqual([player["id"] for player in result["candidates"]], [5])
        self.assertEqual(result["budget"], 75)
        self.assertEqual(result["candidates"][0]["xgi_per_90"], 0.5)
        self.assertEqual(result["candidates"][0]["fixture_difficulty_average"], 2.0)

    def test_lens_requires_an_owned_outgoing_player(self):
        with self.assertRaisesRegex(ValueError, "public squad"):
            lens(self.snapshot, self.catalog, 999, now=self.now)

    def test_lens_blocks_missing_actual_selling_price(self):
        self.snapshot["squad_snapshot"]["picks"][0].pop("selling_price")
        with self.assertRaisesRegex(ValueError, "selling price"):
            lens(self.snapshot, self.catalog, 1, now=self.now)

    def test_lens_blocks_passed_deadline(self):
        self.snapshot["events"]["next"]["deadline_time"] = (self.now - timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "deadline has passed"):
            lens(self.snapshot, self.catalog, 1, now=self.now)

    def private(self, usable=True, selling_price=74, bank=2):
        return {"state": "ready" if usable else "stale", "usable": usable, "message": "Captured account data is older than the freshness limit.",
                "captured_at_utc": self.now.isoformat(), "bank": bank,
                "prices": {1: {"selling_price": selling_price, "purchase_price": 70}}}

    def test_lens_uses_ready_account_selling_price_and_bank(self):
        self.snapshot["squad_snapshot"]["picks"][0].pop("selling_price")
        self.snapshot["squad_snapshot"]["bank"] = None
        result = lens(self.snapshot, self.catalog, 1, 450, now=self.now, private=self.private(selling_price=74, bank=2))
        self.assertEqual(result["budget"], 76)
        self.assertEqual(result["budget_source"], "account")
        self.assertEqual(result["outgoing"]["selling_price"], 74)
        self.assertEqual([player["id"] for player in result["candidates"]], [5, 10])
        self.assertIn("your FPL account", result["caveats"][0])

    def test_lens_ignores_unusable_account_data_and_explains_import(self):
        self.snapshot["squad_snapshot"]["picks"][0].pop("selling_price")
        with self.assertRaisesRegex(ValueError, "selling price is unavailable.*freshness limit"):
            lens(self.snapshot, self.catalog, 1, now=self.now, private=self.private(usable=False))

    def test_lens_labels_public_budget_when_account_lacks_the_outgoing_player(self):
        private = self.private()
        private["prices"] = {2: {"selling_price": 99, "purchase_price": 99}}
        result = lens(self.snapshot, self.catalog, 1, 450, now=self.now, private=private)
        self.assertEqual((result["budget"], result["budget_source"]), (75, "public"))

    def test_lens_keeps_public_gates_with_ready_account_data(self):
        self.snapshot["events"]["next"]["deadline_time"] = (self.now - timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "deadline has passed"):
            lens(self.snapshot, self.catalog, 1, now=self.now, private=self.private())

class WorkflowTests(unittest.TestCase):
    def test_update_preserves_existing_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            update("refresh", {"state": "complete"}, path, datetime(2026, 9, 22, tzinfo=timezone.utc))
            result = update("research", {"state": "empty"}, path, datetime(2026, 9, 22, 1, tzinfo=timezone.utc))
        self.assertEqual(result["refresh"]["state"], "complete")
        self.assertEqual(result["research"]["state"], "empty")


if __name__ == "__main__":
    unittest.main()
