import http.client
import json
import math
import os
import subprocess
import threading
import unittest
from unittest.mock import patch

import dashboard
from fpl_brief import league, matchday, rivals


def picks(elements, captain=None, bench=()):
    """15-style picks: elements in order, positions 1.., the ``bench`` elements placed at 12+."""
    starters = [e for e in elements if e not in bench]
    ordered = starters + list(bench)
    return [{"element": e, "position": i + 1 if e not in bench else 12 + list(bench).index(e), "is_captain": e == captain} for i, e in enumerate(ordered)]


class EffectiveOwnershipTests(unittest.TestCase):
    def test_multipliers_captain_tc_bb_and_bench(self):
        squad = picks([1, 2, 3, 4], captain=1, bench=(4,))
        self.assertEqual(rivals.multipliers(squad), {1: 2, 2: 1, 3: 1, 4: 0})
        self.assertEqual(rivals.multipliers(squad, "3xc"), {1: 3, 2: 1, 3: 1, 4: 0})
        self.assertEqual(rivals.multipliers(squad, "bboost"), {1: 2, 2: 1, 3: 1, 4: 1})
        self.assertEqual(rivals.multipliers(squad, None, captain=2), {1: 1, 2: 2, 3: 1, 4: 0})

    def test_eo_is_the_average_multiplier(self):
        a = rivals.multipliers(picks([1, 2, 3], captain=1))          # 1 captained, 2 and 3 started
        b = rivals.multipliers(picks([1, 2, 5], captain=5, bench=(2,)), "3xc")  # 5 triple captained, 2 benched
        eo = rivals.effective_ownership([a, b])
        self.assertEqual(eo, {1: 1.5, 2: 0.5, 3: 0.5, 5: 1.5})
        self.assertEqual(rivals.effective_ownership([]), {})

    def test_swing_sign_when_you_captain_a_player_they_do_not_own(self):
        xp = {1: 6.0, 2: 4.0, 3: 2.0}
        mine = {1: 2, 2: 1}
        theirs = {2: 2, 3: 1}
        total, parts = rivals.swing(mine, theirs, xp)
        self.assertEqual(parts, {1: 12.0, 2: -4.0, 3: -2.0})
        self.assertAlmostEqual(total, 6.0)
        self.assertGreater(rivals.swing({1: 2}, {}, xp)[0], 0, "captaining a player they don't own is a gain for you")
        self.assertEqual(rivals.swing({1: 2}, {1: 2}, xp), (0, {}))

    def test_assumed_captain_before_the_deadline(self):
        squad = picks([1, 2, 3, 4], captain=1, bench=(4,))
        self.assertEqual(rivals.assumed_captain(squad, {1: 5.0, 2: 7.0}), (1, "last captain"))
        # The last captain is now projected 0 (injured): fall back to the highest-xP starter, never a benched player.
        self.assertEqual(rivals.assumed_captain(squad, {1: 0.0, 2: 3.0, 3: 6.0, 4: 9.0}), (3, "highest next-GW xP starter"))
        self.assertEqual(rivals.assumed_captain([], {}), (None, "no squad"))


class MonteCarloTests(unittest.TestCase):
    def test_shared_draws_cancel_for_identical_squads(self):
        xp = {e: 2.0 + e for e in range(1, 12)}
        sd = {e: 3.0 for e in xp}
        columns = rivals.draws(xp, sd, set(xp), sims=2000, seed=7)
        mine = rivals.multipliers(picks(list(xp), captain=5))
        theirs = rivals.multipliers(picks(list(xp), captain=5))
        diff = [a - b for a, b in zip(rivals.scores(mine, columns, 2000), rivals.scores(theirs, columns, 2000))]
        self.assertEqual(set(diff), {0})
        self.assertTrue(all(v >= rivals.FLOOR and v == int(v) for column in columns.values() for v in column), "floored at −2 and rounded")
        self.assertEqual(columns, rivals.draws(xp, sd, set(xp), sims=2000, seed=7), "seeded")

    def test_position_sd_shrinks_towards_pooled(self):
        history = {"fields": ["gw", "id", "minutes", "total_points"],
                   "rows": [[1, 1, 90, 2], [2, 1, 90, 12]] + [[g, 2, 90, p] for g, p in enumerate([1, 2, 3, 2, 1, 2, 3, 2] * 10)]}
        spread = rivals.position_sd(history, {1: 1, 2: 3})
        raw_gk = math.sqrt(50)  # two GK appearances: 2 and 12
        self.assertLess(spread[1]["sd"], raw_gk, "two appearances barely move the pooled value")
        self.assertEqual((spread[1]["n"], spread[3]["n"], spread[2]["n"]), (2, 80, 0))
        self.assertEqual(rivals.position_sd(None, {})[1]["sd"], rivals.DEFAULT_SD)
        self.assertEqual(rivals.player_sd(0.0, spread[3]), 0.0)
        self.assertLess(rivals.player_sd(0.5, spread[3]), rivals.player_sd(10.0, spread[3]))


def member(entry, total, points, hits=None, rank=None, squad=None, captain=None):
    hits = hits or [0] * len(points)
    return {"entry_id": entry, "name": f"M{entry}", "rank": rank, "total": total, "picks": picks(squad or [], captain), "chips_left": [],
            "history": [{"event": gw + 1, "points": p, "event_transfers_cost": c} for gw, (p, c) in enumerate(zip(points, hits))]}


class FinishOddsTests(unittest.TestCase):
    def test_phi_known_values(self):
        self.assertAlmostEqual(rivals.phi(0), 0.5)
        self.assertAlmostEqual(rivals.phi(1.96), 0.975, places=3)
        self.assertAlmostEqual(rivals.phi(-1), 0.158655, places=5)

    def test_pairwise_odds_rise_with_the_gap(self):
        previous = -1
        for gap in (-60, -20, 0, 20, 60):
            probability, _ = rivals.finish_odds(gap, 0.0, 15.0, 30)
            self.assertGreater(probability, previous)
            previous = probability
        self.assertEqual(rivals.finish_odds(0, 0.0, 15.0, 30)[0], 0.5)
        self.assertEqual(rivals.finish_odds(5, 0.0, 15.0, 0)[0], 1.0, "season over: the gap decides")
        self.assertLess(rivals.finish_odds(30, 0.0, 15.0, 30, mean_var=4.0)[0], rivals.finish_odds(30, 0.0, 15.0, 30)[0], "mean uncertainty widens the spread")

    def test_shrinkage_with_little_history(self):
        members = [member(1, 60, [60]), member(2, 40, [40]), member(3, 50, [50, 50, 50, 50, 50, 50, 50, 50, 50, 50])]
        form, league_mean = rivals.manager_form(members)
        self.assertAlmostEqual(league_mean, (60 + 40 + 500) / 12)
        self.assertAlmostEqual(form[0]["shrunk"], (60 + 5 * league_mean) / 6, "one GW is mostly prior")
        self.assertLess(abs(form[2]["shrunk"] - 50), abs(form[0]["shrunk"] - 60))
        with_hits = rivals.manager_form([member(1, 0, [60, 60], [4, 0])])[0][0]
        self.assertAlmostEqual(with_hits["net"], with_hits["shrunk"] - 2)

    def test_season_monte_carlo_is_seeded_and_sums_to_one(self):
        members = [member(1, 300, [70, 50, 60, 80]), member(2, 310, [60, 65, 55, 75]), member(3, 280, [90, 40, 50, 60])]
        form, _ = rivals.manager_form(members)
        _, _, sigmas = rivals.pairwise(members, form, 10)
        first, rank, ahead, extra = rivals.season_sims(members, form, sigmas, 10, sims=3000, seed=3)
        self.assertAlmostEqual(sum(first), 1.0)
        self.assertEqual((first, rank, ahead), rivals.season_sims(members, form, sigmas, 10, sims=3000, seed=3)[:3])
        self.assertTrue(1 <= rank <= 3)
        self.assertEqual(len(ahead), 2)
        done = rivals.season_sims(members, form, sigmas, 0, sims=100)
        self.assertEqual((done[0], done[2]), ([0.0, 1.0, 0.0], [0.0, 1.0]), "no weeks left: the totals decide")

    def test_top_up_matches_the_pair_spread(self):
        members = [member(1, 300, [70, 50, 60, 80]), member(2, 310, [60, 65, 55, 75]), member(3, 280, [90, 40, 50, 60])]
        form, _ = rivals.manager_form(members)
        _, _, sigmas = rivals.pairwise(members, form, 10)
        extra = rivals.top_ups(form, sigmas)
        gws = sorted(form[0]["deviation"])
        for f, sigma, t in zip(form[1:], sigmas, extra[1:]):
            boot = sum((form[0]["deviation"][g] - f["deviation"][g]) ** 2 for g in gws) / len(gws)
            self.assertAlmostEqual(boot + extra[0] ** 2 + t ** 2, max(sigma ** 2, boot), places=6)

    def test_simulated_and_analytic_pairwise_odds_agree(self):
        import random as stdlib_random
        rng = stdlib_random.Random(11)
        members = [member(1, 330, [rng.randint(45, 95) for _ in range(6)], hits=[0, 4, 0, 0, 0, 0])]
        for entry, total in ((2, 345), (3, 338), (4, 325), (5, 310), (6, 300)):
            members.append(member(entry, total, [rng.randint(40, 100) for _ in range(6)]))
        form, _ = rivals.manager_form(members)
        rows, _, sigmas = rivals.pairwise(members, form, 20)
        _, _, ahead, _ = rivals.season_sims(members, form, sigmas, 20, sims=10_000, seed=5)
        for row, simulated in zip(rows, ahead):
            self.assertLess(abs(row["p_ahead_analytic"] - simulated), 0.05, (row, simulated))


XP = {1: 7.0, 2: 6.0, 3: 5.0, 4: 4.5, 5: 4.0, 6: 3.0, **{e: 2.0 for e in range(7, 30)}}


def fake_projection():
    return {"model": "own", "available": True, "gameweeks": [6, 7], "players": {e: {"xp": [v, v], "xp_6": 2 * v} for e, v in XP.items()}}


def gathered():
    yours = list(range(1, 16))
    return {"state": "ready", "gameweek": 5, "chip_week": 6, "finished": True, "warnings": ["<w>"], "players": {},
            "members": [member(10, 380, [80, 70, 75, 80, 75], rank=3, squad=yours, captain=1),
                        member(20, 400, [85, 80, 75, 80, 80], rank=1, squad=[2] + list(range(16, 30)), captain=2),
                        member(30, 390, [75, 80, 80, 75, 80], rank=2, squad=yours, captain=1),
                        member(40, 370, [70, 75, 75, 75, 75], hits=[0, 4, 0, 0, 0], rank=4, squad=list(range(1, 11)) + list(range(20, 25)), captain=3)]}


CATALOG = {"players": [{"id": e, "web_name": f"P<{e}>", "team": 1, "element_type": 1 if e in (1, 12) else 3} for e in range(1, 30)], "teams": [{"id": 1, "short_name": "AAA"}]}


class BuildTests(unittest.TestCase):
    def test_build_end_to_end(self):
        result = rivals.build({}, CATALOG, gathered(), None, None, sims=2000, projections=fake_projection())
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["remaining"], 33)
        twin = next(r for r in result["rivals"] if r["entry_id"] == 30)
        self.assertEqual((twin["swing"], twin["drivers"]["for_you"], twin["shared"]), (0, [], 15), "identical squad and captain: no swing")
        leader = result["rivals"][0]
        self.assertEqual(leader["entry_id"], 20)
        self.assertEqual(leader["assumed_captain"], {"id": 2, "name": "P<2>", "why": "last captain"})
        self.assertAlmostEqual(sum(r["p_first"] for r in result["rivals"]) + result["you"]["p_first"], 1.0, places=3)
        self.assertEqual([c["id"] for c in result["captains"]], [1, 2, 3, 4, 5])
        self.assertTrue(result["captains"][0]["current"])
        for row in result["captains"]:
            twin_row = next(v for v in row["rivals"] if v["entry_id"] == 30)
            if row["id"] == 1:
                self.assertEqual((twin_row["expected"], twin_row["p_gain"]), (0, 1.0), "same captain as the twin: never behind")
        self.assertEqual(result["mode"]["against"], "M20")
        self.assertIn(result["mode"]["mode"], ("protect", "chase", "balanced"))
        self.assertTrue(all(p["eo"] >= rivals.SHIELD_EO for p in result["shield"]))
        self.assertEqual(result["warnings"], ["<w>"])
        self.assertEqual(result, rivals.build({}, CATALOG, gathered(), None, None, sims=2000, projections=fake_projection()), "deterministic")

    def test_account_lineup_wins_when_usable(self):
        lineup = picks(list(range(1, 16)), captain=4, bench=(12, 13, 14, 15))
        result = rivals.build({}, CATALOG, gathered(), {"usable": True, "lineup": lineup, "chips": []}, None, sims=500, projections=fake_projection())
        self.assertIn("account", result["lineup_source"])
        self.assertEqual([c["id"] for c in result["captains"] if c["current"]], [4])
        stale = rivals.build({}, CATALOG, gathered(), {"usable": False, "lineup": lineup}, None, sims=500, projections=fake_projection())
        self.assertIn("public squad", stale["lineup_source"])

    def test_unavailable_passes_through(self):
        self.assertEqual(rivals.build({}, CATALOG, {"state": "unavailable", "reason": "r"})["reason"], "r")
        self.assertEqual(rivals.build({}, CATALOG, {"state": "ready", "members": [gathered()["members"][0]], "gameweek": 5})["state"], "unavailable")


class FakeLeague:
    """Public FPL endpoints that League threats uses (bootstrap, standings, picks, history)."""

    def __init__(self):
        self.paths = []

    def __call__(self, path, ttl):
        self.paths.append(path)
        if path == "bootstrap-static/":
            return {"chips": [], "teams": [{"id": 1, "short_name": "AAA"}],
                    "elements": [{"id": e, "web_name": f"P{e}", "team": 1} for e in range(1, 30)],
                    "events": [{"id": 5, "is_current": True, "finished": True}, {"id": 6, "is_next": True}]}
        if path.startswith("leagues-classic/"):
            return {"standings": {"results": [{"entry": 20, "entry_name": "Lead<er>", "rank": 1, "total": 400},
                                              {"entry": 10, "entry_name": "Me", "rank": 2, "total": 390}]}}
        entry = int(path.split("/")[1])
        if path.endswith("/history/"):
            return {"chips": [], "current": [{"event": gw, "points": 70 + gw + entry % 3, "event_transfers_cost": 0} for gw in range(1, 6)]}
        squad = list(range(1, 16)) if entry == 10 else list(range(10, 25))
        return {"active_chip": None, "entry_history": {}, "picks": picks(squad, captain=squad[0])}


class EndpointTests(unittest.TestCase):
    def setUp(self):
        matchday.clear_cache()
        self.addCleanup(matchday.clear_cache)
        self.server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        os.environ.pop("DASHBOARD_PASSWORD", None)

    def get(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=60)
        try:
            connection.request("GET", "/api/rivals")
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode())
        finally:
            connection.close()

    def test_endpoint_reuses_league_fetch_and_degrades(self):
        fake = FakeLeague()
        snapshot = {"team_id": 10, "league_id": 99}
        with patch.object(dashboard, "MATCHDAY_GET", fake), patch.object(dashboard.Handler, "api_data", lambda self: (snapshot, CATALOG)), \
                patch.object(dashboard.Handler, "private_data", lambda self, config, snap: {"usable": False}), \
                patch.object(dashboard.Handler, "player_history", lambda self: None), patch.object(dashboard, "load_config", lambda: {}):
            status, body = self.get()
            self.assertEqual((status, body["state"]), (200, "ready"), body)
            self.assertEqual(body["rivals"][0]["name"], "Lead<er>")
            threats_paths = set(fake.paths)
            fake.paths.clear()
            league.threats(snapshot, fake)
            self.assertEqual(threats_paths, set(fake.paths), "no endpoints beyond what League threats reads")
        with patch.object(dashboard, "MATCHDAY_GET", lambda path, ttl: {"events": "nonsense"}), patch.object(dashboard.Handler, "api_data", lambda self: (snapshot, CATALOG)):
            status, body = self.get()
        self.assertEqual((status, body["state"]), (200, "unavailable"))

    def test_endpoint_requires_sign_in_when_password_set(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": "pw-for-tests"}), patch.object(dashboard, "MATCHDAY_GET", FakeLeague()):
            self.assertEqual(self.get()[0], 401)


if __name__ == "__main__":
    unittest.main()
