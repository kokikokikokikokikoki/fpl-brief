import unittest
from datetime import datetime, timedelta, timezone

from fpl_brief import plan

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
FRESH = {"stale": False}
# id: (element_type, team, ep_next, now_cost)
SQUAD = {
    1: (1, 1, "4.0", 45), 2: (1, 2, "2.0", 40),
    3: (2, 1, "6.0", 55), 4: (2, 2, "5.0", 50), 5: (2, 3, "4.0", 45), 6: (2, 4, "3.0", 45), 7: (2, 5, "1.0", 40),
    8: (3, 1, "9.0", 80), 9: (3, 2, "7.0", 70), 10: (3, 3, "6.5", 65), 11: (3, 4, "2.0", 50), 12: (3, 5, "1.5", 45),
    13: (4, 6, "8.0", 90), 14: (4, 7, "5.5", 65), 15: (4, 3, "5.2", 60),
}
MARKET = {
    20: (3, 6, "10.0", 54),                      # affordable midfielder upgrade
    21: (3, 6, "12.0", 130),                     # too expensive
    22: (4, 1, "6.0", 60, {"status": "d", "chance_of_playing_next_round": 50}),
    23: (3, 1, "5.0", 50),                       # 4th from club 1 after other moves
    24: (4, 5, "9.5", 60),                       # forward upgrade
    25: (2, 6, "3.5", 40),                       # cheap defender
}


def build(**account):
    players = []
    for pid, spec in {**SQUAD, **MARKET}.items():
        kind, team, estimate, cost = spec[:4]
        player = {"id": pid, "web_name": f"P{pid}", "element_type": kind, "team": team, "status": "a",
                  "chance_of_playing_next_round": None, "ep_next": estimate, "now_cost": cost}
        if len(spec) > 4:
            player.update(spec[4])
        players.append(player)
    catalog = {"players": players, "teams": [{"id": t, "short_name": f"T{t}"} for t in range(1, 8)]}
    picks = [{"element": pid, "position": pid, "is_captain": pid == 13, "is_vice_captain": pid == 8} for pid in SQUAD]
    fixtures = [{"team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 3}, {"team_h": 3, "team_a": 4}, {"team_h": 5, "team_a": 6}]
    snapshot = {"events": {"next": {"id": 6, "deadline_time": (NOW + timedelta(days=2)).isoformat()}},
                "squad_snapshot": {"picks": picks}, "fixtures": {"events": {"6": fixtures}}}
    private = {"usable": True, "bank": 5, "free_transfers": 1, "hit_cost": 4, "chips": [],
               "prices": {pid: {"selling_price": spec[3] - 1, "purchase_price": spec[3]} for pid, spec in SQUAD.items()},
               "lineup": [{"element": pid, "position": pid, "is_captain": pid == 13, "is_vice_captain": pid == 8} for pid in SQUAD]}
    private.update(account)
    return snapshot, catalog, private


class ParseTests(unittest.TestCase):
    def test_parses_pairs_and_rejects_bad_input(self):
        self.assertEqual(plan.parse_transfers("11:20, 15:24"), [(11, 20), (15, 24)])
        for raw in ("", "11", "11:x", "11:20:3", "-1:2", "1:2,3:4,5:6,7:8", None):
            with self.assertRaises(ValueError):
                plan.parse_transfers(raw)


class PlanTests(unittest.TestCase):
    def run_plan(self, pairs, **account):
        snapshot, catalog, private = build(**account)
        return plan.build(snapshot, catalog, private, FRESH, pairs, NOW)

    def test_affordable_upgrade_reoptimises_lineup_and_captain(self):
        result = self.run_plan([(11, 20)])
        self.assertEqual(result["state"], "ready", result.get("reason"))
        lineup = result["lineup"]
        started = {row["id"] for rows in lineup["lines"].values() for row in rows}
        self.assertIn(20, started)
        self.assertEqual(lineup["captain"]["id"], 20)
        summary = result["summary"]
        self.assertEqual(summary["budget_left"], 5 + (50 - 1) - 54)
        self.assertEqual((summary["paid_transfers"], summary["hit_points"]), (0, 0))
        self.assertGreater(summary["xi_delta"], 0)
        self.assertEqual(summary["net_delta"], summary["xi_delta"])
        self.assertIn("P20", lineup["changes"]["start"])

    def test_horizon_delta_uses_six_week_projection_minus_hits(self):
        snapshot, catalog, private = build(bank=50)
        result = plan.build(snapshot, catalog, private, FRESH, [(11, 20)], NOW)
        summary = result["summary"]
        # One stored gameweek and no team results: the projection equals ep_next for that week.
        self.assertEqual(summary["horizon_gameweeks"], [6])
        self.assertEqual(summary["horizon_delta"], 8.0)
        self.assertIn("estimate, not a forecast", summary["method"])
        self.assertIn("no team results", summary["method"])
        snapshot["fixtures"]["events"]["7"] = [{"team_h": 6, "team_a": 1}, {"team_h": 2, "team_a": 6}, {"team_h": 4, "team_a": 5}]
        double = plan.build(snapshot, catalog, private, FRESH, [(11, 20)], NOW)["summary"]
        self.assertEqual(double["horizon_gameweeks"], [6, 7])
        self.assertEqual(double["xi_delta"], summary["xi_delta"])
        self.assertGreater(double["horizon_delta"], summary["horizon_delta"])
        hit = plan.build(snapshot, catalog, {**private, "free_transfers": 0}, FRESH, [(11, 20)], NOW)["summary"]
        self.assertEqual(hit["horizon_delta"], round(double["horizon_delta"] - 4, 2))

    def test_horizon_delta_own_is_side_by_side_and_needs_history(self):
        snapshot, catalog, private = build(bank=50)
        without = plan.build(snapshot, catalog, private, FRESH, [(11, 20)], NOW)["summary"]
        self.assertIsNone(without["horizon_delta_own"])
        self.assertIn("unavailable until player history", without["method"])
        fields = ["gw", "id", "team", "fixtures", "minutes", "starts", "xg", "xa", "goals", "assists", "cs", "gc", "saves",
                  "defcon_points", "bonus", "yellow", "red", "total_points"]
        rows = [[gw, pid, SQUAD[pid][1], 1, 90, 1, 0.1, 0.1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 2]
                for gw in (1, 2, 3) for pid in range(1, 16)]
        rows += [[gw, 20, 6, 1, 90, 1, 0.9, 0.3, 1, 0, 0, 1, 0, 0, 2, 0, 0, 9] for gw in (1, 2, 3)]
        with_history = plan.build(snapshot, catalog, private, FRESH, [(11, 20)], NOW, history={"fields": fields, "rows": rows})["summary"]
        self.assertGreater(with_history["horizon_delta_own"], 0)
        self.assertEqual(with_history["horizon_delta"], without["horizon_delta"])
        hit = plan.build(snapshot, catalog, {**private, "free_transfers": 0}, FRESH, [(11, 20)], NOW, history={"fields": fields, "rows": rows})["summary"]
        self.assertEqual(hit["horizon_delta_own"], round(with_history["horizon_delta_own"] - 4, 2))

    def test_extra_transfers_cost_hits_and_unlimited_costs_none(self):
        result = self.run_plan([(11, 20), (15, 24)], bank=50)
        self.assertEqual(result["state"], "ready", result.get("reason"))
        self.assertEqual((result["summary"]["paid_transfers"], result["summary"]["hit_points"]), (1, 4))
        self.assertEqual(result["summary"]["net_delta"], round(result["summary"]["xi_delta"] - 4, 2))
        unlimited = self.run_plan([(11, 20), (15, 24)], bank=50, free_transfers="unlimited")
        self.assertEqual(unlimited["summary"]["hit_points"], 0)
        two_free = self.run_plan([(11, 20), (15, 24)], bank=50, free_transfers=2)
        self.assertEqual(two_free["summary"]["hit_points"], 0)

    def test_rules_are_enforced(self):
        cases = [
            ([(11, 21)], {}, "Over budget by £7.6m"),
            ([(15, 22)], {}, "not fully available"),
            ([(11, 3)], {}, "already in your squad"),
            ([(99, 20)], {}, "only sell players in your saved squad"),
            ([(11, 24)], {}, "same position"),
            ([(11, 20), (12, 20)], {}, "only be moved once"),
            ([(11, 20), (11, 23)], {}, "only be moved once"),
            ([(11, 20), (7, 25)], {"bank": 200}, None),
            ([(12, 23)], {"bank": 200}, "more than three players from one club"),
            ([(11, 20)], {"usable": False}, "fresh capture"),
            ([(11, 20)], {"prices": {}}, "selling price is missing"),
        ]
        for pairs, account, message in cases:
            result = self.run_plan(pairs, **account)
            if message is None:
                self.assertEqual(result["state"], "ready", (pairs, result.get("reason")))
            else:
                self.assertEqual(result["state"], "invalid", pairs)
                self.assertIn(message, result["reason"])
                self.assertNotIn("lineup", result)

    def test_club_limit_counts_the_whole_planned_squad(self):
        snapshot, catalog, private = build(bank=200)
        catalog["players"].append({"id": 26, "web_name": "P26", "element_type": 2, "team": 6, "status": "a", "ep_next": "3", "now_cost": 40})
        ok = plan.build(snapshot, catalog, private, FRESH, [(7, 26), (11, 20)], NOW)
        self.assertEqual(ok["state"], "ready", ok.get("reason"))
        result = plan.build(snapshot, catalog, private, FRESH, [(7, 26), (11, 20), (6, 25)], NOW)
        self.assertEqual(result["state"], "invalid")
        self.assertIn("more than three players from one club", result["reason"])

    def test_stale_snapshot_refuses(self):
        snapshot, catalog, private = build()
        result = plan.build(snapshot, catalog, private, {"stale": True}, [(11, 20)], NOW)
        self.assertEqual(result["state"], "invalid")
        self.assertIn("stale", result["reason"])


if __name__ == "__main__":
    unittest.main()
