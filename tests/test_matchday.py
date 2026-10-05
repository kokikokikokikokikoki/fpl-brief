import http.client
import json
import os
import subprocess
import threading
import unittest
from unittest.mock import patch

import dashboard
from fpl_brief import matchday

ROLES = {1: 1, 12: 1, **{i: 2 for i in (2, 3, 4, 14)}, **{i: 3 for i in (5, 6, 7, 8, 9, 13)}, **{i: 4 for i in (10, 11, 15)}}
PLAYERS = {i: {"name": f"P{i}", "team": i, "team_short": f"T{i}", "element_type": ROLES[i]} for i in range(1, 16)}


def picks(captain=6, vice=10, chip=None, cost=0, points=0, total=0):
    return {"active_chip": chip, "entry_history": {"points": points, "total_points": total, "event_transfers_cost": cost, "points_on_bench": 0},
            "picks": [{"element": i, "position": i, "is_captain": i == captain, "is_vice_captain": i == vice} for i in range(1, 16)]}


def points(overrides=None, default=(2, 90)):
    result = {i: {"points": default[0], "minutes": default[1], "bonus": 0} for i in range(1, 16)}
    for element, (pts, minutes) in (overrides or {}).items():
        result[element] = {"points": pts, "minutes": minutes, "bonus": 0}
    return result


def done(overrides=None):
    states = {i: "done" for i in range(1, 16)}
    states.update(overrides or {})
    return states


def by_id(scored):
    return {row["id"]: row for row in scored["rows"]}


class BonusAndFixtureTests(unittest.TestCase):
    def fixture(self, bps, **flags):
        return {"started": True, "finished": False, **flags, "stats": [{"identifier": "bps", "h": [{"element": e, "value": v} for e, v in bps], "a": []}]}

    def test_bonus_follows_fpl_tie_rules(self):
        self.assertEqual(matchday.provisional_bonus([self.fixture([(1, 40), (2, 40), (3, 30), (4, 20)])]), {1: 3, 2: 3, 3: 1})
        self.assertEqual(matchday.provisional_bonus([self.fixture([(1, 50), (2, 40), (3, 40), (4, 30)])]), {1: 3, 2: 2, 3: 2})
        self.assertEqual(matchday.provisional_bonus([self.fixture([(1, 50), (2, 40), (3, 30), (4, 30)])]), {1: 3, 2: 2, 3: 1, 4: 1})

    def test_no_projection_once_bonus_is_in_or_before_kick_off(self):
        confirmed = self.fixture([(1, 50)])
        confirmed["stats"].append({"identifier": "bonus", "h": [{"element": 1, "value": 3}], "a": []})
        for fixture in (self.fixture([(1, 50)], finished=True), confirmed, self.fixture([(1, 50)], started=False)):
            self.assertEqual(matchday.provisional_bonus([fixture]), {})

    def test_team_state_handles_double_gameweeks(self):
        fixtures = [{"team_h": 1, "team_a": 2, "started": True, "finished_provisional": True}, {"team_h": 1, "team_a": 3, "started": False},
                    {"team_h": 4, "team_a": 5, "started": True}]
        self.assertEqual(matchday.team_fixture_state(fixtures), {1: "yet", 2: "done", 3: "yet", 4: "playing", 5: "playing"})


class ScoringTests(unittest.TestCase):
    def test_captain_doubles_and_bench_does_not_count(self):
        scored = matchday.score_picks(picks(), points({6: (10, 90), 13: (7, 90)}), done(), PLAYERS)
        self.assertEqual(scored["total"], 10 * 2 + 2 * 10)
        self.assertEqual(scored["bench_points"], 2 + 7 + 2 + 2)
        self.assertEqual(by_id(scored)[6]["multiplier"], 2)

    def test_auto_sub_keeps_a_legal_formation(self):
        # 3-5-2: a defender who didn't play can't be replaced by the midfielder on bench 1 (2 DEF), so bench 2 (DEF) comes on.
        scored = matchday.score_picks(picks(), points({2: (0, 0), 14: (5, 90)}), done(), PLAYERS)
        rows = by_id(scored)
        self.assertTrue(rows[2]["sub_out"] and rows[14]["sub_in"] and not rows[13]["sub_in"])
        self.assertEqual(scored["total"], 2 * 9 + 2 * 2 + 5)

    def test_pending_bench_player_blocks_projection_and_live_starter_is_not_subbed(self):
        scored = matchday.score_picks(picks(), points({5: (0, 0), 13: (0, 0)}), done({13: "yet"}), PLAYERS)
        self.assertFalse(by_id(scored)[5]["sub_out"], "bench 1 still to play: FPL waits for them")
        scored = matchday.score_picks(picks(), points({5: (0, 0)}), done({5: "playing"}), PLAYERS)
        self.assertFalse(by_id(scored)[5]["sub_out"], "a starter still playing isn't subbed")
        self.assertEqual(scored["to_play"], 1)

    def test_keeper_only_replaced_by_keeper(self):
        rows = by_id(matchday.score_picks(picks(), points({1: (0, 0)}), done(), PLAYERS))
        self.assertTrue(rows[1]["sub_out"] and rows[12]["sub_in"])
        rows = by_id(matchday.score_picks(picks(), points({1: (0, 0), 12: (0, 0)}), done(), PLAYERS))
        self.assertFalse(rows[1]["sub_out"] or rows[13]["sub_in"])

    def test_vice_takes_the_armband_and_triple_captain(self):
        scored = matchday.score_picks(picks(chip="3xc"), points({6: (0, 0), 10: (8, 90)}), done(), PLAYERS)
        rows = by_id(scored)
        self.assertEqual((rows[10]["multiplier"], rows[10]["armband"], scored["armband"]), (3, True, 10))
        scored = matchday.score_picks(picks(), points({6: (0, 0)}), done({6: "yet"}), PLAYERS)
        self.assertEqual(scored["armband"], 6, "captain still to play keeps the armband")

    def test_bench_boost_counts_everyone_without_subs(self):
        scored = matchday.score_picks(picks(chip="bboost"), points({2: (0, 0)}), done(), PLAYERS)
        self.assertEqual(scored["total"], 2 * 13 + 2 * 2)
        self.assertFalse(any(r["sub_in"] or r["sub_out"] for r in scored["rows"]))

    def test_provisional_bonus_is_added_and_labelled(self):
        rows = by_id(matchday.score_picks(picks(), points(), done({6: "playing"}), PLAYERS, bonus={6: 3}))
        self.assertEqual((rows[6]["points"], rows[6]["provisional_bonus"]), (5, 3))
        live = points()
        live[6]["bonus"] = 3
        rows = by_id(matchday.score_picks(picks(), live, done(), PLAYERS, bonus={6: 3}))
        self.assertEqual((rows[6]["points"], rows[6]["provisional_bonus"]), (2, 0), "no double-counting once FPL adds bonus")


class HindsightAndLeagueTests(unittest.TestCase):
    def test_best_possible_and_cost_split(self):
        # Bench MID 13 scored 12; captain 6 scored 2 while FWD 10 scored 9.
        scored = matchday.score_picks(picks(), points({13: (12, 90), 10: (9, 90)}), done(), PLAYERS)
        self.assertEqual(scored["total"], 2 * 10 + 9 + 2)
        best = matchday.best_possible(scored)
        self.assertEqual(best, 12 + 9 + 2 * 9 + 12)  # 12 in for a 2-pointer, 12 as captain
        row = matchday.hindsight_row(5, scored, {"points": scored["total"], "points_on_bench": 18})
        self.assertEqual((row["left"], row["armband_cost"], row["lineup_cost"], row["bench_points"]), (best - scored["total"], 7, best - scored["total"] - 7, 18))

    def test_hindsight_never_negative_against_official_points(self):
        scored = matchday.score_picks(picks(), points(), done(), PLAYERS)
        row = matchday.hindsight_row(1, scored, {"points": 500})
        self.assertEqual((row["best"], row["left"]), (500, 0))

    def test_league_table_uses_hits_and_ranks(self):
        def entry(eid, total_gw, before, cost=0, you=False):
            return {"entry_id": eid, "name": f"M{eid}", "is_you": you, "scored": {"total": total_gw, "rows": [], "chip": None, "to_play": 0},
                    "entry_history": {"total_points": before + 30 - cost, "points": 30, "event_transfers_cost": cost}}
        table = matchday.league_table([entry(1, 60, 100, you=True), entry(2, 40, 110, cost=8), entry(3, 50, 110)])
        rows = {r["entry_id"]: r for r in table}
        self.assertEqual((rows[2]["before"], rows[2]["gw_points"], rows[2]["total"]), (110, 32, 142))
        self.assertEqual([r["entry_id"] for r in table], [1, 3, 2])
        self.assertEqual((rows[1]["start_rank"], rows[1]["rank"], rows[1]["move"]), (3, 1, 2))
        self.assertEqual((rows[2]["start_rank"], rows[3]["start_rank"]), (1, 1), "ties share a rank")

    def test_swings_flag_owned_bench_players(self):
        you = matchday.score_picks(picks(), points({13: (14, 90), 6: (10, 90)}), done(), PLAYERS)
        rival = matchday.score_picks({**picks(captain=13), "picks": [{**p, "position": {13: 5, 5: 13}.get(p["element"], p["position"])} for p in picks(captain=13)["picks"]]},
                                     points({13: (14, 90), 6: (10, 90)}), done(), PLAYERS)
        result = matchday.swings(you, [rival])
        losing = {r["id"]: r for r in result["losing"]}
        self.assertEqual((losing[13]["impact"], losing[13]["owned"], losing[13]["yours"]), (-28, True, 0))
        self.assertEqual(result["gaining"][0]["id"], 6)
        self.assertEqual(matchday.swings(you, []), {"gaining": [], "losing": []})


def boot(current=5, finished=True):
    return {"teams": [{"id": i, "short_name": f"T{i}"} for i in range(1, 16)],
            "elements": [{"id": i, "web_name": f"P{i}", "team": i, "element_type": ROLES[i]} for i in range(1, 16)],
            "events": [{"id": gw, "is_current": gw == current, "finished": finished or gw < current, "data_checked": finished or gw < current,
                        "average_entry_score": 50, "highest_score": 120, "deadline_time": "2026-09-18T17:30:00Z"} for gw in range(1, current + 1)]}


def live_payload():
    return {"elements": [{"id": i, "stats": {"total_points": 2, "minutes": 90, "bonus": 0}} for i in range(1, 16)]}


class FakeFPL:
    def __init__(self, fail=(), boot_data=None, fixtures=None):
        self.fail, self.calls = set(fail), []
        self.boot = boot_data or boot()
        self.fixtures = fixtures if fixtures is not None else [{"team_h": 1, "team_a": 2, "started": True, "finished": True, "finished_provisional": True, "stats": []}]

    def __call__(self, path, ttl):
        self.calls.append((path, ttl))
        if any(path.startswith(prefix) for prefix in self.fail):
            raise matchday.Unavailable("FPL returned HTTP 503")
        if path == "bootstrap-static/":
            return self.boot
        if path.startswith("fixtures/"):
            return self.fixtures
        if path.endswith("/live/"):
            return live_payload()
        if path.endswith("/history/"):
            return {"current": [{"event": gw, "points": 26, "points_on_bench": 4 if "/10/" in path else 8} for gw in range(1, 6)]}
        if "/picks/" in path:
            return picks(points=26, total=130)
        raise AssertionError(path)


SNAPSHOT = {"team_id": 10, "manager": {"entry_name": "Me <b>"}, "rivals": [{"entry_id": 20, "name": "R20"}, {"entry_id": 30, "name": "R30"}, {"entry_id": "bad"}]}


class BuildTests(unittest.TestCase):
    def setUp(self):
        matchday.clear_cache()
        self.addCleanup(matchday.clear_cache)

    def test_ready_payload(self):
        fake = FakeFPL()
        result = matchday.build(SNAPSHOT, fake)
        self.assertEqual((result["state"], result["gameweek"], result["status"], result["average"]), ("ready", 5, "final", 50))
        self.assertEqual(len(result["league"]), 3)
        self.assertTrue(next(r for r in result["league"] if r["is_you"])["name"].startswith("Me"))
        season = result["season"]
        self.assertEqual((season["state"], len(season["gameweeks"]), season["bench_points"], season["rival_bench_average"]), ("ready", 5, 20, 40.0))
        self.assertIn(("event/1/live/", 0), fake.calls, "finished live feeds are fetched uncached (only the reduced form is kept)")

    def test_status_follows_fixtures(self):
        live = [{"team_h": 1, "team_a": 2, "started": True, "finished": False}, {"team_h": 3, "team_a": 4, "started": False}]
        self.assertEqual(matchday.build(SNAPSHOT, FakeFPL(boot_data=boot(finished=False), fixtures=live))["status"], "live")
        self.assertEqual(matchday.build(SNAPSHOT, FakeFPL(boot_data=boot(finished=False), fixtures=[{"started": False}]))["status"], "waiting")
        provisional = [{"team_h": 1, "team_a": 2, "started": True, "finished_provisional": True}]
        result = matchday.build(SNAPSHOT, FakeFPL(boot_data=boot(finished=False), fixtures=provisional))
        self.assertEqual((result["status"], result["average"]), ("provisional", None))

    def test_failures_degrade(self):
        result = matchday.build(SNAPSHOT, FakeFPL(fail=("entry/20/",)))
        self.assertEqual((result["state"], len(result["league"])), ("ready", 2))
        self.assertTrue(any("R20" in w for w in result["warnings"]))
        self.assertEqual(matchday.build(SNAPSHOT, FakeFPL(fail=("entry/10/event/5/",)))["state"], "unavailable")
        self.assertEqual(matchday.build(SNAPSHOT, FakeFPL(fail=("bootstrap",)))["state"], "unavailable")
        self.assertEqual(matchday.build({}, FakeFPL())["state"], "unavailable")
        no_current = boot()
        for event in no_current["events"]:
            event["is_current"] = False
        self.assertIn("season hasn't started", matchday.build(SNAPSHOT, FakeFPL(boot_data=no_current))["reason"])
        self.assertEqual(matchday.build(SNAPSHOT, FakeFPL(fail=("entry/10/history/",)))["season"]["state"], "unavailable")


class CacheTests(unittest.TestCase):
    def setUp(self):
        matchday.clear_cache()
        self.addCleanup(matchday.clear_cache)

    def test_ttl_expiry_and_failures_not_cached(self):
        clock = [0.0]
        calls = []
        load = lambda: calls.append(1) or len(calls)
        self.assertEqual(matchday.cached("k", 60, load, now=lambda: clock[0]), 1)
        self.assertEqual(matchday.cached("k", 60, load, now=lambda: clock[0]), 1)
        clock[0] = 61
        self.assertEqual(matchday.cached("k", 60, load, now=lambda: clock[0]), 2)

        def boom():
            raise matchday.Unavailable("down")
        with self.assertRaises(matchday.Unavailable):
            matchday.cached("f", 60, boom)
        self.assertEqual(matchday.cached("f", 60, lambda: "ok"), "ok")

    def test_waiting_to_live_refetches_the_live_feed(self):
        # Opened between the deadline and kick-off, then again after kick-off: live points must not stay frozen.
        clock = [0.0]
        with patch.object(matchday.time, "monotonic", lambda: clock[0]):
            fetched = []
            fixtures = [[{"team_h": 1, "team_a": 2, "started": False}]]
            def fetch(path):
                fetched.append(path)
                if path == "bootstrap-static/":
                    return boot(finished=False)
                if path.startswith("fixtures/"):
                    return fixtures[0]
                if path.endswith("/live/"):
                    return live_payload()
                if path.endswith("/history/"):
                    return {"current": []}
                return picks()
            get = matchday.cached_getter(fetch)
            self.assertEqual(matchday.build(SNAPSHOT, get)["status"], "waiting")
            fixtures[0] = [{"team_h": 1, "team_a": 2, "started": True}]
            clock[0] = 120
            self.assertEqual(matchday.build(SNAPSHOT, get)["status"], "live")
            self.assertEqual(fetched.count("event/5/live/"), 2)

    def test_getter_skips_cache_for_zero_ttl_and_cache_is_bounded(self):
        calls = []
        get = matchday.cached_getter(lambda path: calls.append(path) or path)
        get("a", 60); get("a", 60); get("b", 0); get("b", 0)
        self.assertEqual(calls, ["a", "b", "b"])
        for i in range(matchday.CACHE_MAX + 10):
            matchday.cached(("n", i), 60, lambda: i)
        self.assertLessEqual(len(matchday._CACHE), matchday.CACHE_MAX)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        matchday.clear_cache()
        self.addCleanup(matchday.clear_cache)
        self.server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            connection.request("GET", "/api/matchday")
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode())
        finally:
            connection.close()

    def test_endpoint_uses_snapshot_and_survives_bad_data(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DASHBOARD_PASSWORD", None)
            with patch.object(dashboard, "MATCHDAY_GET", FakeFPL()), patch.object(dashboard.Handler, "api_data", lambda self: (SNAPSHOT, {})):
                status, body = self.get()
            self.assertEqual((status, body["state"]), (200, "ready"))
            with patch.object(dashboard, "MATCHDAY_GET", lambda path, ttl: {"events": "nonsense"}), patch.object(dashboard.Handler, "api_data", lambda self: (SNAPSHOT, {})):
                status, body = self.get()
            self.assertEqual((status, body["state"]), (200, "unavailable"))

    def test_endpoint_requires_sign_in_when_password_set(self):
        with patch.dict(os.environ, {"DASHBOARD_PASSWORD": "pw-for-tests"}), patch.object(dashboard, "MATCHDAY_GET", FakeFPL()):
            self.assertEqual(self.get()[0], 401)


class MatchdayUiTests(unittest.TestCase):
    def test_render_escapes_and_covers_states(self):
        matchday.clear_cache()
        payload = matchday.build({**SNAPSHOT, "manager": {"entry_name": "<img src=x>"}}, FakeFPL())
        payload["warnings"] = ["<script>w</script>"]
        script = r'''
const fs = require("fs");
const vm = require("vm");
const ts = require("./dashboard/node_modules/typescript");
const load = (file, req) => {
  const out = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const context = { exports: {}, require: req, Math, JSON, Number, String };
  vm.runInNewContext(out, context);
  return context.exports;
};
const kits = load("dashboard/kits.ts", () => ({}));
const md = load("dashboard/matchday.ts", (name) => (name === "./kits" ? kits : {}));
const check = (c, m) => { if (!c) throw new Error(m); };
const data = JSON.parse(process.argv[1]);
const html = md.renderMatchday(data, false);
check(!html.includes("<img") && html.includes("&lt;img src=x&gt;"), "manager names escaped");
check(!html.includes("<script>") && html.includes("&lt;script&gt;"), "warnings escaped");
check(html.includes("Points left on the table") && html.includes("Final"), "ledger and status");
check((html.match(/class="magnet md-shirt/g) || []).length === 15, "15 shirts");
check(md.renderMatchday({ state: "unavailable", reason: "<b>down</b>" }, false).includes("&lt;b&gt;down"), "unavailable escaped");
check(md.renderMatchday(null, true).includes("Checking the scores"), "loading state");
check(md.renderMatchday(data, false, "<i>net</i>").includes("Showing the last scores") && !md.renderMatchday(data, false, "<i>net</i>").includes("<i>"), "refresh failure note escaped");
data.status = "live"; data.you.rows[0].provisional_bonus = 2; data.you.rows[0].state = "playing";
const live = md.renderMatchday(data, false);
check(live.includes("updates every minute") && live.includes("+2 bonus?") && live.includes("playing"), "live labels");
'''
        result = subprocess.run(["node", "-e", script, json.dumps(payload)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
