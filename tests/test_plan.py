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
