import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_fpl
from fpl_brief import plan, prices
from fpl_brief.candidates import lens

NOW = datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
DEADLINE = datetime(2026, 10, 10, 10, tzinfo=timezone.utc)


def predictor(percent, projected=(None, None, None), likelihood=(0, 0, 0), calibrating=False, locked=None):
    return {"price_change_percent": None if percent is None else str(percent), "price_change_hourly_rate": 10,
            "price_change_projections": [{"offset": i, "projected_percent": str(p), "likelihood": l}
                                         for i, (p, l) in enumerate(zip(projected, likelihood)) if p is not None],
            "price_change_locked_until": locked, "price_change_calibrating": calibrating}


class SellingPriceTests(unittest.TestCase):
    def test_formula_floor_fall_and_single_rise(self):
        self.assertEqual(prices.selling_price(50, 50), 50)
        self.assertEqual(prices.selling_price(50, 51), 50)   # a single +0.1 rise earns nothing
        self.assertEqual(prices.selling_price(50, 52), 51)
        self.assertEqual(prices.selling_price(50, 53), 51)   # floor of half the profit
        self.assertEqual(prices.selling_price(50, 48), 48)   # falls are passed on in full
        self.assertEqual(prices.selling_price(45, 50), 47)

    def test_matches_airsenal_integer_form(self):
        for bought in range(40, 60):
            for now in range(35, 70):
                expected = (now + bought) // 2 if now > bought else now
                self.assertEqual(prices.selling_price(bought, now), expected)


class OutlookTests(unittest.TestCase):
    def test_missing_fields_give_unknown(self):
        for player in ({}, {"price_change_percent": None}, {"price_change_percent": "abc", "price_change_projections": "x"}, None):
            view = prices.outlook(player)
            self.assertEqual(view["direction"], "unknown")
            self.assertIn("guide only", view["guide"])

    def test_above_100_means_next_update(self):
        view = prices.outlook(predictor("100.4", ("100.8", "101.4", "101.9"), (5, 5, 5)))
        self.assertEqual((view["direction"], view["expected_at_update"], view["likelihood"]), ("rise", 1, 5))
        self.assertIn("FPL's own predictor, a guide only", view["label"])
        fall = prices.outlook(predictor("-100.2", ("-100.5", "-101", "-101"), (-4, -4, -4)))
        self.assertEqual((fall["direction"], fall["expected_at_update"], fall["likelihood"]), ("fall", 1, -4))

    def test_projection_crossing_later_and_steady(self):
        later = prices.outlook(predictor("96.4", ("97.3", "98.7", "100.1"), (4, 4, 5)))
        self.assertEqual((later["direction"], later["expected_at_update"], later["likelihood"]), ("rise", 3, 5))
        steady = prices.outlook(predictor("84.9", ("85", "86", "87"), (3, 3, 3)))
        self.assertEqual((steady["direction"], steady["expected_at_update"]), ("steady", None))
        self.assertEqual(prices.outlook({"price_change_percent": 100.5})["direction"], "rise")  # numbers accepted too

    def test_calibrating_and_locked_flags(self):
        view = prices.outlook(predictor("101", ("102", "103", "104"), (5, 5, 5), calibrating=True))
        self.assertTrue(view["calibrating"])
        self.assertIn("calibrating", view["label"])
        locked = prices.outlook(predictor("101", ("102",), (5,), locked="2026-10-11T00:00:00Z"))
        self.assertEqual(locked["next_change"], "No change before 2026-10-11T00:00:00Z.")


class EarlyMoveTests(unittest.TestCase):
    def setUp(self):
        self.players = {
            1: {"id": 1, "web_name": "Seller", "now_cost": 60, **predictor("-101", ("-102",), (-5,))},
            2: {"id": 2, "web_name": "Riser", "now_cost": 60, **predictor("101", ("102",), (5,))},
            3: {"id": 3, "web_name": "Flat", "now_cost": 60, **predictor("10", ("11", "12", "13"))},
            4: {"id": 4, "web_name": "Late", "now_cost": 60, **predictor("90", ("95", "98", "100.5"), (3, 4, 5))},
        }
        self.private = {"usable": True, "prices": {1: {"purchase_price": 60, "selling_price": 60}, 3: {"purchase_price": 60, "selling_price": 60}}}

    def test_rising_buy_and_falling_sell_get_notes(self):
        notes = prices.early_move_notes([(1, 2)], self.players, self.private, DEADLINE, NOW)
        self.assertEqual([note["kind"] for note in notes], ["buy_rise", "sell_fall"])
        self.assertTrue(all("guide only" in note["text"] and "not a reason to move" in note["text"] for note in notes))
        self.assertEqual(notes[0]["value_points"], 0.008)   # itb_value 0.08 per £1m × £0.1m, "about 0.01 points"
        self.assertIn("about 0.01 points", notes[0]["text"])

    def test_no_note_when_steady_or_after_the_deadline(self):
        self.assertEqual(prices.early_move_notes([(3, 3)], self.players, self.private, DEADLINE, NOW), [])
        # Projected at the 3rd update: a note with 5 updates left, none with only 2.
        self.assertEqual(len(prices.early_move_notes([(3, 4)], self.players, self.private, DEADLINE, NOW)), 1)
        self.assertEqual(prices.early_move_notes([(3, 4)], self.players, self.private, NOW + timedelta(days=1, hours=20), NOW), [])
        self.assertEqual(prices.early_move_notes([(1, 2)], self.players, self.private, None, NOW), [])

    def test_locked_until_after_deadline_and_harmless_fall_give_no_note(self):
        self.players[2]["price_change_locked_until"] = "2026-10-11T00:00:00Z"
        self.assertEqual(prices.early_move_notes([(3, 2)], self.players, self.private, DEADLINE, NOW), [])
        # Bought at 57, now 60: selling 58; a fall to 59 keeps selling 58, so the fall costs nothing.
        self.private["prices"][1]["purchase_price"] = 57
        self.assertEqual(prices.early_move_notes([(1, 3)], self.players, self.private, DEADLINE, NOW), [])

    def test_updates_before_deadline(self):
        self.assertEqual(prices.updates_before(NOW, DEADLINE), 5)
        self.assertEqual(prices.updates_before(datetime(2026, 10, 9, 20, tzinfo=timezone.utc), DEADLINE), 1)
        self.assertEqual(prices.updates_before(DEADLINE, NOW), 0)
        self.assertEqual(prices.updates_before(NOW, None), 0)


def squad_fixture():
    picks = [{"element": pid, "position": pid} for pid in range(1, 16)]
    players = [{"id": pid, "web_name": f"P{pid}", "element_type": 3, "now_cost": 50 + pid} for pid in range(1, 16)]
    players[0].update(predictor("101", ("102",), (5,)))
    snapshot = {"events": {"next": {"deadline_time": DEADLINE.isoformat()}}, "squad_snapshot": {"picks": picks}}
    private = {"usable": True, "captured_at_utc": "2026-10-05T04:00:00+00:00", "bank": 3,
               "prices": {pid: {"purchase_price": 50, "selling_price": prices.selling_price(50, 50 + pid)} for pid in range(1, 16)}}
    return snapshot, {"players": players}, private


class SquadViewTests(unittest.TestCase):
    def test_with_account_data(self):
        snapshot, catalog, private = squad_fixture()
        view = prices.squad_view(snapshot, catalog, private, NOW)
        self.assertEqual(view["state"], "account")
        self.assertEqual(len(view["players"]), 15)
        first = view["players"][0]   # bought 50, now 51: selling 50, a rise to 52 adds 0.1, a fall to 50 costs nothing
        self.assertEqual((first["current"], first["purchase"], first["selling"], first["profit"]), (51, 50, 50, 0))
        self.assertEqual((first["if_rise"], first["if_fall"], first["rise_earns_nothing"]), (1, 0, False))
        second = view["players"][1]  # bought 50, now 52: selling 51; one more rise earns nothing until a second one
        self.assertEqual((second["selling"], second["if_rise"], second["if_fall"], second["rise_earns_nothing"]), (51, 0, -1, True))
        self.assertEqual(first["outlook"]["direction"], "rise")
        self.assertTrue(first["outlook"]["before_deadline"])
        self.assertEqual(view["cross_check"]["checked"], 15)
        self.assertEqual(view["cross_check"]["mismatches"], [])
        self.assertIn("second", view["method"])

    def test_cross_check_reports_a_mismatch(self):
        snapshot, catalog, private = squad_fixture()
        private["prices"][3]["selling_price"] = 40
        view = prices.squad_view(snapshot, catalog, private, NOW)
        self.assertEqual(view["cross_check"]["mismatches"], [{"id": 3, "name": "P3", "account": 40, "formula": 51}])
        self.assertEqual(view["players"][2]["selling"], 40)   # the account value is shown

    def test_cross_check_note_says_not_checked_when_nothing_compared(self):
        snapshot, catalog, private = squad_fixture()
        private["prices"] = {}
        view = prices.squad_view(snapshot, catalog, private, NOW)
        self.assertEqual(view["cross_check"]["checked"], 0)
        self.assertIn("not checked", view["cross_check"]["note"])
        self.assertNotIn("match", view["cross_check"]["note"])

    def test_without_account_data_public_only_with_message(self):
        snapshot, catalog, _ = squad_fixture()
        for private in (None, {"usable": False, "state": "stale", "message": "An FPL deadline has passed since capture."}):
            view = prices.squad_view(snapshot, catalog, private, NOW)
            self.assertEqual(view["state"], "public")
            self.assertIn("fresh capture", view["message"])
            self.assertTrue(all(row["selling"] is None and row["purchase"] is None for row in view["players"]))
            self.assertEqual(view["players"][0]["current"], 51)
            self.assertNotIn("cross_check", view)
        self.assertIn("deadline has passed", view["message"])

    def test_missing_predictor_fields_never_break(self):
        snapshot, catalog, private = squad_fixture()
        for player in catalog["players"]:
            for key in list(player):
                if key.startswith("price_change"):
                    del player[key]
        view = prices.squad_view(snapshot, catalog, private, NOW)
        self.assertTrue(all(row["outlook"]["direction"] == "unknown" for row in view["players"]))


class CatalogWhitelistTests(unittest.TestCase):
    def test_catalog_keeps_price_change_fields_and_stays_compact(self):
        element = {"id": 1, "web_name": "A", "now_cost": 50, "photo": "x.jpg", "price_change_percent": "100.4",
                   "price_change_hourly_rate": 37, "price_change_projections": [{"offset": 0, "projected_percent": "100.8", "likelihood": 5}],
                   "price_change_locked_until": None, "price_change_calibrating": False}
        row = fetch_fpl.catalog_players({"elements": [element]})[0]
        for key in ("price_change_percent", "price_change_hourly_rate", "price_change_projections", "price_change_locked_until", "price_change_calibrating"):
            self.assertIn(key, fetch_fpl.CATALOG_FIELDS)
            self.assertEqual(row[key], element[key])
        self.assertNotIn("photo", row)
        self.assertEqual(set(row), set(fetch_fpl.CATALOG_FIELDS))

    def test_older_catalog_without_fields_stores_none(self):
        row = fetch_fpl.catalog_players({"elements": [{"id": 1}]})[0]
        self.assertIsNone(row["price_change_percent"])
        self.assertEqual(prices.outlook(row)["direction"], "unknown")


class WiringTests(unittest.TestCase):
    def test_plan_summary_carries_early_move_notes_without_changing_estimates(self):
        from tests.test_plan import NOW as PLAN_NOW, build
        snapshot, catalog, private = build()
        baseline = plan.build(snapshot, catalog, private, {"stale": False}, [(11, 20)], PLAN_NOW)
        for player in catalog["players"]:
            if player["id"] == 20:
                player.update(predictor("101", ("102",), (5,)))
        noted = plan.build(snapshot, catalog, private, {"stale": False}, [(11, 20)], PLAN_NOW)
        self.assertEqual(baseline["summary"]["price_notes"], [])
        self.assertEqual([note["kind"] for note in noted["summary"]["price_notes"]], ["buy_rise"])
        for key in ("xi_delta", "net_delta", "horizon_delta", "budget_left"):
            self.assertEqual(noted["summary"][key], baseline["summary"][key])

    def test_candidate_lens_adds_price_markers(self):
        now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        snapshot = {"generated_at_utc": now.isoformat(), "events": {"next": {"deadline_time": (now + timedelta(days=3)).isoformat()}},
                    "squad_snapshot": {"bank": 5, "picks": [{"element": 1, "selling_price": 70}] + [{"element": i} for i in range(100, 114)]},
                    "fixtures": {"events": {}}}
        catalog = {"players": [
            {"id": 1, "web_name": "Out", "team": 1, "element_type": 3, "now_cost": 70, "status": "a", "minutes": 900, **predictor("-101", ("-102",), (-5,))},
            {"id": 5, "web_name": "Riser", "team": 2, "element_type": 3, "now_cost": 70, "status": "a", "minutes": 900, **predictor("101", ("102",), (5,))},
            {"id": 6, "web_name": "Old", "team": 3, "element_type": 3, "now_cost": 70, "status": "a", "minutes": 900},
        ]}
        result = lens(snapshot, catalog, 1, 0, now=now)
        by_id = {row["id"]: row for row in result["candidates"]}
        self.assertEqual(by_id[5]["price_outlook"]["direction"], "rise")
        self.assertIn("Early-move note", by_id[5]["price_outlook"]["note"])
        self.assertEqual(by_id[6]["price_outlook"]["direction"], "unknown")
        self.assertIsNone(by_id[6]["price_outlook"]["note"])
        self.assertEqual(result["outgoing"]["price_outlook"]["direction"], "fall")
        self.assertIn("predicted to fall", result["outgoing"]["price_outlook"]["note"])
        self.assertIn("guide only", result["price_method"])
        self.assertEqual([row["id"] for row in result["candidates"]], [6, 5])   # ranking ignores prices: equal inputs sort by name


if __name__ == "__main__":
    unittest.main()
