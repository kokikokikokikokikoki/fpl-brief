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


@unittest.skipUnless(HAS_HIGHS, "highspy is not installed")
class ConstraintSolverTests(unittest.TestCase):
    def solve(self, inputs, constraints, **overrides):
        return optimise.solve(inputs, optimise.settings(**overrides), constraints)

    def test_forced_in_player_is_in_the_squad_by_his_gw(self):
        # 20 is no upgrade (1.0 a week), so only the constraint brings him in, by week 2 at the latest.
        inputs = data(weeks=4, market={20: (3, 1.0, 45, 20)}, free=1)
        free = self.solve(inputs, None)
        self.assertFalse(any(20 in week["squad"] for week in free["plans"][0]["weeks"]))
        forced = self.solve(inputs, {"force_in": [(20, 2)]})
        self.assertTrue(forced["plans"])
        for found in forced["plans"]:
            self.assertIn(20, found["weeks"][1]["squad"])
        # The hold baseline stays unconstrained: the same as without constraints.
        self.assertEqual(forced["hold"]["horizon_xp"], free["hold"]["horizon_xp"])
        self.assertEqual(all_moves(forced["hold"]), [])

    def test_default_gw_is_the_next_one(self):
        forced = self.solve(data(market={20: (3, 1.0, 45, 20)}), {"force_in": [(20, None)]})
        self.assertIn(20, forced["plans"][0]["weeks"][0]["squad"])

    def test_force_out_and_keep_are_respected(self):
        market = {20: (3, 5.0, 50, 20), 24: (4, 9.0, 90, 24)}
        free = self.solve(data(market=market, free=2), None)
        self.assertIn((1, 11, 20), all_moves(free["plans"][0]))  # the unconstrained best sells 11
        kept = self.solve(data(market=market, free=2), {"keep": [11]})
        for found in kept["plans"]:
            self.assertTrue(all(11 in week["squad"] for week in found["weeks"]))
        sold = self.solve(data(market=market, free=2), {"force_out": [(13, 1)]})
        for found in sold["plans"]:
            self.assertNotIn(13, found["weeks"][0]["squad"])

    def test_infeasible_constraints_give_a_clear_reason(self):
        # A £13.0m midfielder with no bank, and the three players who could fund him kept.
        result = self.solve(data(market={21: (3, 12.0, 130, 21)}), {"force_in": [(21, 1)], "keep": [8, 9, 13]})
        self.assertEqual(result["state"], "infeasible")
        self.assertIn("No legal plan meets these constraints", result["reason"])
        self.assertIn("Remove or loosen one", result["reason"])

    def test_invalid_constraints(self):
        inputs = data(market={20: (3, 1.0, 45, 20)})
        cases = [({"force_in": [(99, None)]}, "not in the player list"),
                 ({"force_in": [(20, 9)]}, "outside the planning horizon"),
                 ({"keep": [20]}, "not in your squad"),
                 ({"force_in": [(11, 2)], "force_out": [(11, 2)]}, "both in and out"),
                 ({"force_out": [(11, 2)], "keep": [11]}, "both kept and sold"),
                 ({"keep": [1, 2, 3, 4, 5, 6]}, "At most 5"),
                 ({"keep": [1, 1]}, "listed twice")]
        for constraints, reason in cases:
            result = self.solve(inputs, constraints)
            self.assertEqual(result.get("state"), "invalid", constraints)
            self.assertIn(reason, result["reason"])


class ConstraintParseTests(unittest.TestCase):
    def test_strict_parse(self):
        self.assertEqual(optimise.parse_constraints("268@6, 12", "", "165"),
                         {"force_in": [(268, 6), (12, None)], "force_out": [], "keep": [165]})
        self.assertEqual(optimise.parse_constraints(), {"force_in": [], "force_out": [], "keep": []})
        for bad in (("x", "", ""), ("1@", "", ""), ("1@x", "", ""), ("-1", "", ""), ("", "", "1@6"), ("1.5", "", ""), ("１", "", ""), ("", "1@@6", "")):
            with self.assertRaises(ValueError):
                optimise.parse_constraints(*bad)

    def test_cache_key_is_order_free(self):
        a = optimise.constraints_key({"force_in": [(1, None), (2, 6)], "keep": [3]})
        b = optimise.constraints_key({"keep": [3], "force_in": [(2, 6), (1, None)], "force_out": []})
        self.assertEqual(a, b)
        self.assertNotEqual(a, optimise.constraints_key(None))


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

    def test_constraints_report_the_unconstrained_best(self):
        snapshot, catalog, private = plan_fixture(bank=20, free_transfers=1)
        free = optimise.build(snapshot, catalog, private, FRESH, model="fpl", now=NOW)
        self.assertEqual(free["unconstrained_best_gain"], free["plans"][0]["gain"])
        self.assertEqual(free["constraints"], [])
        self.assertNotIn("cost_vs_unconstrained", free["plans"][0])
        steered = optimise.build(snapshot, catalog, private, FRESH, model="fpl", now=NOW, constraints={"force_in": [(25, None)], "keep": [11]})
        self.assertEqual(steered["state"], "ready", steered.get("reason"))
        self.assertEqual(steered["unconstrained_best_gain"], free["plans"][0]["gain"])
        self.assertEqual(steered["unconstrained_best_action"], free["plans"][0]["next_gw_action"])
        self.assertEqual([row["text"] for row in steered["constraints"]], ["Must buy P25 by GW6", "Never sell P11"])
        for found in steered["plans"]:
            self.assertIn(25, found["weeks"][0]["squad"])
            self.assertIn(11, found["weeks"][0]["squad"])
            self.assertEqual(found["rules_check"]["state"], "passed")
            self.assertEqual(found["cost_vs_unconstrained"], round(found["gain"] - free["plans"][0]["gain"], 2))
        self.assertLessEqual(steered["plans"][0]["cost_vs_unconstrained"], 0)
        self.assertTrue(any("holding baseline ignores them" in caveat for caveat in steered["caveats"]))
        # A supplied (cached) unconstrained best is used as is: no second unconstrained solve.
        with patch.object(optimise, "solve", side_effect=optimise.solve) as solve:
            given = optimise.build(snapshot, catalog, private, FRESH, model="fpl", now=NOW, constraints={"keep": [11]},
                                   unconstrained_best={"gain": 99.0, "action": "x"})
        self.assertEqual(solve.call_count, 1)
        self.assertEqual(given["unconstrained_best_gain"], 99.0)

    def test_build_validates_constraints(self):
        snapshot, catalog, private = plan_fixture(bank=20, free_transfers=1)
        run = lambda constraints: optimise.build(snapshot, catalog, private, FRESH, model="fpl", now=NOW, constraints=constraints)
        self.assertIn("not in the player list", run({"force_in": [(999, None)]})["reason"])
        self.assertIn("not in your squad", run({"keep": [20]})["reason"])
        self.assertIn("outside the planning horizon (GW6)", run({"force_in": [(20, 7)]})["reason"])
        doubtful = run({"force_in": [(22, None)]})  # flagged 50%: the rule checker would refuse him this week
        self.assertEqual(doubtful["state"], "infeasible")
        self.assertIn("P22 is flagged doubtful or unavailable for GW6", doubtful["reason"])
        snapshot, catalog, private = plan_fixture(bank=0, free_transfers=1)
        blocked = optimise.build(snapshot, catalog, private, FRESH, model="fpl", now=NOW, constraints={"force_in": [(21, None)], "keep": [8, 9, 13]})
        self.assertEqual(blocked["state"], "infeasible")
        self.assertTrue(blocked["reason"].startswith("Constraints: Must buy P21 by GW6; Never sell P8"))

    def test_choices_list_players_for_the_pickers(self):
        snapshot, catalog, _ = plan_fixture()
        picked = optimise.choices(snapshot, catalog)
        self.assertEqual(sorted(picked["owned"]), list(range(1, 16)))
        self.assertEqual({row["id"] for row in picked["players"]}, {p["id"] for p in catalog["players"]})
        self.assertEqual(picked["players"][0], {"id": 1, "name": "P1", "team": "T1", "position": 1, "price": 45})

    def test_cli_parses_constraints(self):
        with patch.object(optimise, "build", return_value={"state": "blocked"}) as build, patch("builtins.print"):
            optimise.main(["own", "--force-in", "268", "--keep", "165", "--force-out", "12@7"])
        self.assertEqual(build.call_args.kwargs["constraints"], {"force_in": [(268, None)], "force_out": [(12, 7)], "keep": [165]})
        with self.assertRaises(SystemExit), patch("sys.stderr"):
            optimise.main(["own", "--keep", "x"])

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
