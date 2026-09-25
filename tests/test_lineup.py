import unittest
from datetime import datetime, timedelta, timezone

from fpl_brief import lineup

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
FRESH = {"stale": False}
# id: (element_type, team, ep_next)
SQUAD = {
    1: (1, 1, "4.0"), 2: (1, 2, "2.0"),
    3: (2, 1, "6.0"), 4: (2, 2, "5.0"), 5: (2, 3, "4.0"), 6: (2, 4, "3.0"), 7: (2, 5, "1.0"),
    8: (3, 1, "9.0"), 9: (3, 2, "7.0"), 10: (3, 3, "6.5"), 11: (3, 4, "2.0"), 12: (3, 5, "1.5"),
    13: (4, 1, "8.0"), 14: (4, 2, "5.5"), 15: (4, 3, "5.2"),
}


def build(player_overrides=None):
    player_overrides = player_overrides or {}
    players = []
    for pid, (kind, team, estimate) in SQUAD.items():
        player = {"id": pid, "web_name": f"P{pid}", "element_type": kind, "team": team, "status": "a",
                  "chance_of_playing_next_round": None, "ep_next": estimate}
        player.update(player_overrides.get(pid, {}))
        players.append(player)
    catalog = {"players": players, "teams": [{"id": team, "short_name": f"T{team}"} for team in range(1, 7)]}
    fixtures = [{"team_h": 1, "team_a": 2}, {"team_h": 3, "team_a": 4}, {"team_h": 5, "team_a": 6}]
    picks = [{"element": pid, "position": pid, "is_captain": pid == 13, "is_vice_captain": pid == 8} for pid in SQUAD]
    snapshot = {"events": {"next": {"id": 6, "deadline_time": (NOW + timedelta(days=2)).isoformat()}},
                "squad_snapshot": {"picks": picks}, "fixtures": {"events": {"6": fixtures}}}
    return snapshot, catalog


def ids(result):
    return {row["id"] for rows in result["lines"].values() for row in rows}


class LineupTests(unittest.TestCase):
    def test_best_legal_formation_maximizes_fpl_estimate(self):
        snapshot, catalog = build()
        result = lineup.suggest(snapshot, catalog, None, FRESH, NOW)
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["formation"], "4-3-3")
        self.assertEqual(ids(result), {1, 3, 4, 5, 6, 8, 9, 10, 13, 14, 15})
        self.assertEqual(result["xi_estimate_total"], 63.2)
        self.assertEqual((result["captain"]["id"], result["vice"]["id"]), (8, 13))

    def test_every_formation_respects_position_limits(self):
        snapshot, catalog = build({pid: {"ep_next": "0.1"} for pid in (13, 14, 15)})
        result = lineup.suggest(snapshot, catalog, None, FRESH, NOW)
        counts = {role: len(rows) for role, rows in result["lines"].items()}
        self.assertEqual(counts["GK"], 1)
        self.assertEqual(counts["FWD"], 1)
        self.assertTrue(3 <= counts["DEF"] <= 5 and 2 <= counts["MID"] <= 5)
        self.assertEqual(sum(counts.values()), 11)

    def test_injured_suspended_and_blank_players_do_not_start(self):
        snapshot, catalog = build({8: {"status": "i", "chance_of_playing_next_round": 0}, 13: {"status": "s"}, 10: {"team": 6}})
        snapshot["fixtures"]["events"]["6"] = [{"team_h": 1, "team_a": 2}, {"team_h": 3, "team_a": 4}, {"team_h": 5, "team_a": 7}]
        result = lineup.suggest(snapshot, catalog, None, FRESH, NOW)
        started = ids(result)
        self.assertEqual(result["formation"], "5-3-2")
        for pid in (8, 13, 10):
            self.assertNotIn(pid, started)
        self.assertTrue(all(row["eligible"] for rows in result["lines"].values() for row in rows))
        bench = {row["id"]: row for row in result["bench"]}
        self.assertIn("injured", bench[8]["reason"])
        self.assertIn("suspended", bench[13]["reason"])
        self.assertIn("no fixture in GW6", bench[10]["reason"])

    def test_forced_start_is_labelled_when_no_eligible_alternative(self):
        snapshot, catalog = build({pid: {"status": "i"} for pid in (8, 9, 10, 11)})
        result = lineup.suggest(snapshot, catalog, None, FRESH, NOW)
        forced = [row for row in result["lines"]["MID"] if not row["eligible"]]
        self.assertEqual(len(forced), 1)
        self.assertIn("Forced start", forced[0]["reason"])
        self.assertNotEqual(result["captain"]["id"], forced[0]["id"])

    def test_doubtful_players_are_flagged_and_not_preferred_as_captain(self):
        snapshot, catalog = build({8: {"chance_of_playing_next_round": 75}})
        result = lineup.suggest(snapshot, catalog, None, FRESH, NOW)
        self.assertIn(8, ids(result))
        self.assertEqual(result["captain"]["id"], 13)
        starter = next(row for row in result["lines"]["MID"] if row["id"] == 8)
        self.assertIn("doubtful: 75% chance", starter["reason"])

    def test_double_gameweek_is_flagged(self):
        snapshot, catalog = build()
        snapshot["fixtures"]["events"]["6"].append({"team_h": 1, "team_a": 6})
        result = lineup.suggest(snapshot, catalog, None, FRESH, NOW)
        self.assertIn("2 fixtures in GW6", result["captain"]["flags"])

    def test_bench_has_backup_goalkeeper_first_then_estimate_order(self):
        snapshot, catalog = build()
        bench = lineup.suggest(snapshot, catalog, None, FRESH, NOW)["bench"]
        self.assertEqual([row["id"] for row in bench], [2, 11, 12, 7])
        self.assertEqual(bench[0]["reason"], "Backup goalkeeper.")

    def test_refuses_when_inputs_cannot_support_advice(self):
        snapshot, catalog = build()
        cases = [
            ({"stale": True}, snapshot, catalog, "stale"),
            (None, snapshot, catalog, "stale"),
        ]
        passed, _ = build()
        passed["events"]["next"]["deadline_time"] = (NOW - timedelta(minutes=1)).isoformat()
        cases.append((FRESH, passed, catalog, "deadline has passed"))
        missing_deadline, _ = build()
        missing_deadline["events"]["next"] = {"id": 6}
        cases.append((FRESH, missing_deadline, catalog, "deadline is unavailable"))
        short, _ = build()
        short["squad_snapshot"]["picks"].pop()
        cases.append((FRESH, short, catalog, "incomplete"))
        _, no_estimate = build({4: {"ep_next": None}})
        cases.append((FRESH, snapshot, no_estimate, "estimate is missing for P4"))
        _, bad_estimate = build({4: {"ep_next": "nan"}})
        cases.append((FRESH, snapshot, bad_estimate, "estimate is missing for P4"))
        for freshness, snap, cat, message in cases:
            result = lineup.suggest(snap, cat, None, freshness, NOW)
            self.assertEqual(result["state"], "unavailable")
            self.assertIn(message, result["reason"])
            self.assertNotIn("lines", result)

    def test_changes_compare_with_public_snapshot_lineup(self):
        snapshot, catalog = build()
        changes = lineup.suggest(snapshot, catalog, None, FRESH, NOW)["changes"]
        self.assertIn("public snapshot", changes["source"])
        self.assertEqual(changes["start"], ["P13", "P14", "P15"])
        self.assertEqual(changes["bench"], ["P2", "P7", "P11"])
        self.assertEqual(changes["captain"], {"from": "P13", "to": "P8"})
        self.assertFalse(changes["bench_order_changed"], "a different bench set is reported via start/bench, not as an order change")
        self.assertFalse(changes["none"])

    def test_changes_prefer_ready_account_lineup(self):
        snapshot, catalog = build()
        order = [1, 3, 4, 5, 6, 8, 9, 10, 13, 14, 15, 2, 11, 12, 7]
        private = {"usable": True, "chips": [], "lineup": [
            {"element": pid, "position": index + 1, "is_captain": pid == 8, "is_vice_captain": pid == 13} for index, pid in enumerate(order)]}
        changes = lineup.suggest(snapshot, catalog, private, FRESH, NOW)["changes"]
        self.assertIn("FPL account", changes["source"])
        self.assertTrue(changes["none"])
        private["usable"] = False
        self.assertIn("public snapshot", lineup.suggest(snapshot, catalog, private, FRESH, NOW)["changes"]["source"])

    def test_bench_boost_hint_states(self):
        strong = {pid: {"ep_next": "3.5"} for pid in (2, 6, 7, 12)}
        snapshot, catalog = build(strong)
        chips = lambda status: {"usable": True, "lineup": [], "chips": [{"name": "bboost", "status": status}]}
        result = lineup.suggest(snapshot, catalog, chips("available"), FRESH, NOW)["bench_boost"]
        self.assertEqual((result["bench_total"], result["available"]), (12.5, True))
        self.assertTrue(result["hint"].startswith("Worth considering"))
        self.assertIn("not available", lineup.suggest(snapshot, catalog, chips("played"), FRESH, NOW)["bench_boost"]["hint"])
        self.assertIn("unknown", lineup.suggest(snapshot, catalog, None, FRESH, NOW)["bench_boost"]["hint"])
        snapshot, catalog = build({**strong, 2: {"ep_next": "0.0"}, 6: {"ep_next": "6.0"}})
        weak_keeper = lineup.suggest(snapshot, catalog, chips("available"), FRESH, NOW)["bench_boost"]
        self.assertFalse(weak_keeper["all_bench_playing"])
        self.assertTrue(weak_keeper["hint"].startswith("Not this week"))


    def test_bench_order_change_only_when_same_players_reordered(self):
        snapshot, catalog = build()
        order = [1, 3, 4, 5, 6, 8, 9, 10, 13, 14, 15, 2, 7, 12, 11]
        private = {"usable": True, "chips": [], "lineup": [
            {"element": pid, "position": index + 1, "is_captain": pid == 8, "is_vice_captain": pid == 13} for index, pid in enumerate(order)]}
        changes = lineup.suggest(snapshot, catalog, private, FRESH, NOW)["changes"]
        self.assertEqual((changes["start"], changes["bench"]), ([], []))
        self.assertTrue(changes["bench_order_changed"])
        self.assertFalse(changes["none"])

    def test_bench_boost_excludes_doubtful_bench_players(self):
        strong = {pid: {"ep_next": "3.5"} for pid in (2, 6, 7, 12)}
        strong[11] = {"ep_next": "3.5", "chance_of_playing_next_round": 50}
        snapshot, catalog = build(strong)
        chips = {"usable": True, "lineup": [], "chips": [{"name": "bboost", "status": "available"}]}
        result = lineup.suggest(snapshot, catalog, chips, FRESH, NOW)
        bench_ids = [row["id"] for row in result["bench"]]
        if 11 in bench_ids:
            self.assertFalse(result["bench_boost"]["all_bench_playing"])
            self.assertTrue(result["bench_boost"]["hint"].startswith("Not this week"))
        reason = next(row["reason"] for row in result["bench"] + [r for rows in result["lines"].values() for r in rows] if row["id"] == 11)
        self.assertNotIn("gw", reason)

    def test_bench_reason_keeps_flag_capitalisation(self):
        snapshot, catalog = build({12: {"chance_of_playing_next_round": 75}})
        snapshot["fixtures"]["events"]["6"].append({"team_h": 5, "team_a": 6})
        bench = {row["id"]: row for row in lineup.suggest(snapshot, catalog, None, FRESH, NOW)["bench"]}
        self.assertIn("Doubtful: 75% chance; 2 fixtures in GW6.", bench[12]["reason"])

    def test_xi_total_includes_forced_starters(self):
        snapshot, catalog = build({pid: {"status": "i"} for pid in (8, 9, 10, 11)})
        result = lineup.suggest(snapshot, catalog, None, FRESH, NOW)
        xi = [row for rows in result["lines"].values() for row in rows]
        self.assertEqual(result["xi_estimate_total"], round(sum(row["estimate"] for row in xi), 2))


if __name__ == "__main__":
    unittest.main()
