import importlib
import sys
import unittest
from unittest.mock import patch

from fpl_brief import optimise, plan

from test_plan import FRESH, NOW, build as plan_fixture

HAS_HIGHS = optimise.highspy is not None

# Base squad: 2 GK, 5 DEF, 5 MID, 3 FWD, each from its own club. id: (element_type, xP per week, price)
SQUAD = {1: (1, 3.0, 45), 2: (1, 1.0, 40),
         3: (2, 3.0, 50), 4: (2, 3.0, 50), 5: (2, 3.0, 50), 6: (2, 1.0, 40), 7: (2, 1.0, 40),
         8: (3, 4.0, 60), 9: (3, 4.0, 60), 10: (3, 4.0, 60), 11: (3, 1.0, 50), 12: (3, 1.0, 45),
         13: (4, 8.0, 90), 14: (4, 4.0, 60), 15: (4, 1.0, 45)}


def data(weeks=3, market=None, bank=0, free=1, owned_clubs=None, sell=None):
    """Synthetic optimiser input: market = {id: (kind, [xp per week] or flat xp, price, club)}."""
    gameweeks = list(range(1, weeks + 1))
    rows = {pid: (kind, xp, price, pid) for pid, (kind, xp, price) in SQUAD.items()}
    for pid, club in (owned_clubs or {}).items():
        rows[pid] = rows[pid][:3] + (club,)
    rows.update(market or {})
    xp = {pid: (list(row[1]) if isinstance(row[1], list) else [row[1]] * weeks) for pid, row in rows.items()}
    sell_prices = {pid: rows[pid][2] for pid in rows}
    sell_prices.update(sell or {})
    return {"pool": sorted(rows), "gameweeks": gameweeks, "owned": list(SQUAD), "kinds": {pid: row[0] for pid, row in rows.items()},
            "clubs": {pid: row[3] for pid, row in rows.items()}, "xp": xp, "sell": sell_prices,
            "buy": {pid: row[2] for pid, row in rows.items()}, "bank": bank, "free_transfers": free, "hit_cost": 4,
            "out_next": set(), "buyable_next": set(rows)}


def moves(found, week=0):
    return sorted((move["out"], move["in"]) for move in found["weeks"][week]["moves"])


def all_moves(found):
    return sorted((week["gw"], move["out"], move["in"]) for week in found["weeks"] for move in week["moves"])


@unittest.skipUnless(HAS_HIGHS, "highspy is not installed")
class SolverTests(unittest.TestCase):
    def solve(self, inputs, **overrides):
        result = optimise.solve(inputs, optimise.settings(**overrides))
        self.assertNotIn("state", result, result)
        return result

    def test_known_best_transfer(self):
        # 21 would gain 1 point a week: not worth a −4 over three decayed weeks.
        result = self.solve(data(market={20: (3, 5.0, 50, 20), 21: (3, 2.0, 50, 21)}))
        best = result["plans"][0]
        self.assertEqual(moves(best), [(11, 20)])
        self.assertEqual(best["weeks"][0]["captain"], 13)
        weights = sum(optimise.DECAY ** w for w in range(3))
        self.assertAlmostEqual(best["gain"], round(4.0 * weights, 2), places=2)
        self.assertEqual(result["hold"]["hit_points"], 0)
        self.assertEqual(all_moves(result["hold"]), [])

    def test_budget_uses_selling_prices(self):
        market = {20: (3, 5.0, 60, 20)}
        # Player 11 sells for 50 (below his 60 list price here): bank 9 leaves £5.9m, short of £6.0m.
        short = self.solve(data(market=market, bank=9, sell={11: 50}))
        self.assertNotIn((1, 11, 20), all_moves(short["plans"][0]))
        enough = self.solve(data(market=market, bank=10, sell={11: 50}))
        best = enough["plans"][0]
        self.assertEqual(moves(best), [(11, 20)])
        self.assertEqual(best["weeks"][0]["bank"], 0)
        self.assertEqual(best["weeks"][1]["bank"], 0)

    def test_players_bought_in_horizon_sell_at_price_paid(self):
        # Buy 20 in week 1, sell him for 21 in week 2: the bank comes back to exactly his purchase price.
        market = {20: (3, [7.9, 0.0, 0.0, 0.0], 50, 20), 21: (3, [0.0, 5.0, 5.0, 5.0], 50, 21)}
        result = self.solve(data(weeks=4, market=market, bank=0, free=2, sell={11: 50}), no_transfer_last_gws=2)
        best = result["plans"][0]
        self.assertEqual(all_moves(best), [(1, 11, 20), (2, 20, 21)])
        self.assertEqual([week["bank"] for week in best["weeks"]], [0, 0, 0, 0])

    def test_three_per_club(self):
        clubs = {3: 30, 4: 30, 5: 30}  # three defenders already from club 30
        market = {20: (3, 6.0, 50, 30), 21: (3, 3.0, 50, 21)}
        inputs = data(market=market, owned_clubs=clubs)
        best = self.solve(inputs)["plans"][0]
        self.assertEqual(moves(best), [(11, 21)])
        for week in best["weeks"]:
            self.assertLessEqual(sum(1 for pid in week["squad"] if inputs["clubs"][pid] == 30), 3)

    def test_holding_banks_a_free_transfer(self):
        result = self.solve(data(weeks=6, free=1))
        self.assertEqual([week["free_transfers"] for week in result["hold"]["weeks"]], [1, 2, 3, 4, 5, 5])
        self.assertEqual(result["hold"]["free_transfers_after"], 5)
        two = self.solve(data(weeks=3, free=2, market={20: (3, 5.0, 50, 20)}))["plans"][0]
        self.assertEqual(moves(two), [(11, 20)])
        self.assertEqual([week["free_transfers"] for week in two["weeks"]], [2, 2, 3])

    def test_hit_only_when_it_pays_back(self):
        weights = sum(optimise.DECAY ** w for w in range(3))  # moves only in week 1 of 3
        for gain, expect_hit in ((1.0, False), (2.5, True)):
            self.assertEqual(gain * weights > 4 + optimise.MIN_TRANSFER_GAIN, expect_hit)
            # One free move (MID +3 a week) always pays; the second (DEF +gain a week) needs a −4 hit.
            market = {20: (3, 4.0, 50, 20), 21: (2, 1.0 + gain, 40, 21)}
            best = self.solve(data(market=market, free=1))["plans"][0]
            self.assertEqual(best["hit_points"], 4 if expect_hit else 0, gain)
            self.assertEqual(len(best["weeks"][0]["moves"]), 2 if expect_hit else 1, gain)

    def test_no_transfers_in_last_two_gameweeks(self):
        market = {20: (3, [0, 0, 0, 0, 9.0, 9.0], 50, 20)}
        result = self.solve(data(weeks=6, market=market))
        for found in result["plans"]:
            self.assertEqual(found["weeks"][4]["moves"], [])
            self.assertEqual(found["weeks"][5]["moves"], [])
        self.assertIn((4, 11, 20), all_moves(result["plans"][0]))

    def test_plans_differ_in_their_next_gw_action(self):
        market = {20: (3, 5.0, 50, 20), 21: (3, 4.5, 50, 21), 22: (2, 4.0, 40, 22)}
        result = self.solve(data(market=market))
        self.assertEqual(len(result["plans"]), 3)
        self.assertEqual(len({tuple(moves(found)) for found in result["plans"]}), 3)
        objectives = [found["objective"] for found in result["plans"]]
        self.assertEqual(objectives, sorted(objectives, reverse=True))
        # Plan 1 is the unrestricted optimum; with moves allowed only in week 1 of 3 it is unique.
        self.assertEqual(result["plans"][0]["objective"], max(objectives))

    def test_rolling_is_one_next_gw_option_and_later_moves_do_not_count(self):
        # Moves allowed in weeks 1-2 of 4. Only a late upgrade exists, so plan 1 rolls now and buys in week 2;
        # plan 2 must act now, and plans that differ only in later weeks are not offered.
        market = {20: (3, [0.0, 6.0, 6.0, 6.0], 50, 20)}
        result = self.solve(data(weeks=4, market=market))
        first = result["plans"][0]
        self.assertEqual(moves(first), [])
        self.assertEqual(all_moves(first), [(2, 11, 20)])
        next_gw = [tuple(moves(found)) for found in result["plans"]]
        self.assertEqual(len(set(next_gw)), len(next_gw))
        self.assertTrue(all(actions for actions in next_gw[1:]))

    def test_fewer_plans_when_fewer_next_gw_options(self):
        result = self.solve(data())  # nobody to buy: holding is the only next-GW option
        self.assertEqual(len(result["plans"]), 1)
        self.assertEqual(all_moves(result["plans"][0]), [])

    def test_breakdown_sums_to_objective_gain(self):
        market = {20: (3, 5.0, 50, 20), 21: (3, 4.5, 50, 21), 22: (2, 4.0, 40, 22)}
        result = self.solve(data(market=market, bank=7))
        hold = result["hold"]
        self.assertAlmostEqual(hold["score"], hold["objective"], places=2)
        for found in result["plans"]:
            parts = found["breakdown"]
            self.assertEqual(set(parts), set(optimise.SCORE_PARTS))
            self.assertLess(abs(sum(parts.values()) - found["objective_gain"]), 1e-6)
            # The parts reproduce the solver's own objective difference.
            self.assertAlmostEqual(found["objective_gain"], found["objective"] - hold["objective"], places=2)
        self.assertEqual(sum(found["most_points"] for found in result["plans"]), 1)

    def test_plans_ending_with_equal_free_transfers_rank_by_points(self):
        # Moves allowed in weeks 1-2 of 4: buying now or a week later ends the horizon with the same free transfers.
        result = self.solve(data(weeks=4, market={20: (3, 5.0, 50, 20)}))
        now, later = result["plans"][0], result["plans"][1]
        self.assertEqual(moves(now), [(11, 20)])
        self.assertEqual(moves(later), [])
        self.assertEqual(all_moves(later), [(2, 11, 20)])
        self.assertEqual(now["free_transfers_after"], later["free_transfers_after"])
        self.assertEqual(now["breakdown"]["ft_value"], later["breakdown"]["ft_value"])
        self.assertGreater(now["gain"], later["gain"])
        self.assertTrue(now["most_points"])

    def test_free_transfers_are_valued_once_at_the_end(self):
        weeks = 3
        result = self.solve(data(weeks=weeks, free=1, market={20: (3, 5.0, 50, 20)}))
        hold, moved = result["hold"], result["plans"][0]
        end = optimise.DECAY ** (weeks - 1)
        # Holding banks to 4 FTs after the horizon: worth the 2nd-4th list values once, at the last GW's weight.
        self.assertEqual(hold["free_transfers_after"], 4)
        self.assertAlmostEqual(hold["score_parts"]["ft_value"], end * (2.0 + 1.6 + 1.3))
        # Using one FT in week 1 carries one fewer out: it costs exactly that FT's one-time value, not a per-week sum.
        self.assertEqual(moved["free_transfers_after"], 3)
        self.assertAlmostEqual(moved["breakdown"]["ft_value"], round(-end * 1.3, 4))
        self.assertAlmostEqual(moved["breakdown"]["transfer_penalty"], -optimise.MIN_TRANSFER_GAIN)

    def test_min_transfer_gain_blocks_tiny_moves(self):
        # Five FTs banked either way, so only points and the per-transfer threshold differ: +0.2 is not worth a move.
        tiny = {20: (3, 1.2, 50, 20)}
        blocked = self.solve(data(weeks=1, free=5, market=tiny))
        self.assertEqual(all_moves(blocked["plans"][0]), [])
        allowed = self.solve(data(weeks=1, free=5, market=tiny), min_transfer_gain=0.0)
        self.assertEqual(moves(allowed["plans"][0]), [(11, 20)])

    def test_flagged_out_player_is_not_in_next_xi(self):
        inputs = data()
        inputs["out_next"] = {13}
        result = self.solve(inputs)
        self.assertNotIn(13, result["plans"][0]["weeks"][0]["lineup"])
        self.assertIn(13, result["plans"][0]["weeks"][1]["lineup"])


class SettingsTests(unittest.TestCase):
    def test_ft_values_must_be_non_negative_and_non_increasing(self):
        optimise.settings(ft_values={2: 2.0, 3: 1.6, 4: 1.6, 5: 1.1})
        for bad in ({2: 1.0, 3: 1.5}, {2: 1.0, 3: -0.1}):
            with self.assertRaises(ValueError):
                optimise.settings(ft_values=bad)


@unittest.skipUnless(HAS_HIGHS, "highspy is not installed")
class BuildTests(unittest.TestCase):
    def test_every_plan_passes_the_rule_checker(self):
        snapshot, catalog, private = plan_fixture(bank=20, free_transfers=1)
        result = optimise.build(snapshot, catalog, private, FRESH, model="fpl", now=NOW)
        self.assertEqual(result["state"], "ready", result.get("reason"))
        self.assertEqual(result["model"], "fpl")
        self.assertIn("not advice", result["method"])
        self.assertIn("no chips", result["method"])
        self.assertGreaterEqual(len(result["plans"]), 2)
        for found in result["plans"]:
            pairs = [(move["out"], move["in"]) for move in found["next_gw_moves"]]
            if pairs:
                checked = plan.build(snapshot, catalog, private, FRESH, pairs, NOW)
                self.assertEqual(checked["state"], "ready", (pairs, checked.get("reason")))
                self.assertEqual(found["rules_check"]["state"], "passed")
            self.assertIn("GW6", result["method"])
            self.assertTrue(found["next_gw_action"])
            self.assertLess(abs(sum(found["breakdown"].values()) - found["objective_gain"]), 1e-6)
            for week in found["weeks"]:
                for move in week["moves"]:
                    self.assertIn("name", move["out"])
                    self.assertIn("price", move["in"])
        # The doubtful forward (22) is never bought for the next GW: plan.py would refuse him.
        self.assertFalse(any(move["in"] == 22 for found in result["plans"] for move in found["next_gw_moves"]))

    def test_blocked_without_fresh_account_or_history(self):
        snapshot, catalog, private = plan_fixture()
        blocked = optimise.build(snapshot, catalog, {**private, "usable": False, "message": "Captured data is old."}, FRESH, model="fpl", now=NOW)
        self.assertEqual(blocked["state"], "blocked")
        self.assertIn("fresh capture", blocked["reason"])
        self.assertIn("Captured data is old.", blocked["reason"])
        stale = optimise.build(snapshot, catalog, private, {"stale": True}, model="fpl", now=NOW)
        self.assertEqual(stale["state"], "blocked")
        own = optimise.build(snapshot, catalog, private, FRESH, now=NOW)
        self.assertEqual(own["state"], "blocked")
        self.assertIn("player history", own["reason"])
        with self.assertRaises(ValueError):
            optimise.build(snapshot, catalog, private, FRESH, model="other", now=NOW)

    def test_pool_is_deterministic_and_keeps_owned(self):
        players = {pid: {"id": pid, "element_type": 1 + pid % 4, "status": "u" if pid == 99 else "a", "now_cost": 40 + pid % 50}
                   for pid in range(1, 400)}
        projections = {pid: {"xp_6_decayed": (pid * 37) % 101 / 10} for pid in players}
        owned = [1, 2, 3]
        pool = optimise.select_pool(players, projections, owned)
        self.assertEqual(pool, optimise.select_pool(players, projections, owned))
        self.assertTrue(set(owned) <= set(pool))
        self.assertNotIn(99, pool)
        self.assertLessEqual(len(pool), len(owned) + sum(optimise.POOL_TOP.values()) + sum(optimise.POOL_VALUE.values()))


class UnavailableTests(unittest.TestCase):
    def test_missing_highspy_reports_unavailable(self):
        snapshot, catalog, private = plan_fixture()
        with patch.object(optimise, "highspy", None):
            self.assertFalse(optimise.available())
            self.assertEqual(optimise.build(snapshot, catalog, private, FRESH, now=NOW),
                             {"state": "unavailable", "reason": "Planner needs the highspy package"})
            self.assertEqual(optimise.solve(data())["state"], "unavailable")

    def test_import_failure_is_caught(self):
        saved = sys.modules.get("highspy")
        try:
            sys.modules["highspy"] = None  # makes "import highspy" raise ImportError
            reloaded = importlib.reload(optimise)
            self.assertIsNone(reloaded.highspy)
            self.assertEqual(reloaded.build({}, {}, {}, FRESH)["state"], "unavailable")
        finally:
            if saved is None:
                sys.modules.pop("highspy", None)
            else:
                sys.modules["highspy"] = saved
            importlib.reload(optimise)


if __name__ == "__main__":
    unittest.main()
