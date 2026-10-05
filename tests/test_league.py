import json
import subprocess
import unittest

import dashboard
from fpl_brief import league, matchday

RULES = [{"name": "wildcard", "start_event": 2, "stop_event": 19}, {"name": "wildcard", "start_event": 20, "stop_event": 38},
         {"name": "freehit", "start_event": 2, "stop_event": 19}, {"name": "bboost", "start_event": 1, "stop_event": 19},
         {"name": "3xc", "start_event": 1, "stop_event": 19}]


class ChipTests(unittest.TestCase):
    def test_chips_left_follow_the_window(self):
        used = [{"name": "3xc", "event": 2}, {"name": "wildcard", "event": 4}]
        self.assertEqual([c["name"] for c in league.chips_left(RULES, used, 6)], ["freehit", "bboost"])
        self.assertEqual(league.chips_left(RULES, used, 6)[0]["expires"], 19)
        # Second half: the first-half wildcard doesn't use up the second one.
        self.assertEqual([c["name"] for c in league.chips_left(RULES, used, 20)], ["wildcard"])
        self.assertEqual(league.chips_left(None, None, 6), [])


def fixture(gw, home, away, kickoff, hd=2, ad=4):
    return {"event": gw, "team_h": home, "team_a": away, "kickoff_time": kickoff, "team_h_difficulty": hd, "team_a_difficulty": ad}


TEAMS = {1: {"short_name": "AAA", "name": "A"}, 2: {"short_name": "BBB", "name": "B"}, 3: {"short_name": "CCC", "name": "C"}}


class TickerTests(unittest.TestCase):
    def test_breaks_blanks_doubles_and_order(self):
        events = {
            "6": [fixture(6, 1, 2, "2026-10-10T14:00:00Z")],
            "7": [fixture(7, 3, 1, "2026-10-17T14:00:00Z", 5, 1), fixture(7, 2, 3, "2026-10-18T14:00:00Z", 1, 1)],
            "8": [fixture(8, 1, 3, "2026-11-05T14:00:00Z"), fixture(8, 1, 2, "2026-11-08T14:00:00Z")],
            "5": [fixture(5, 1, 2, "2026-09-01T14:00:00Z")],
        }
        result = league.ticker(events, TEAMS, {1: ["Me"]}, first=6)
        self.assertEqual(result["gameweeks"], [6, 7, 8])
        rows = {r["team"]: r for r in result["rows"]}
        a = rows["AAA"]
        self.assertEqual(a["yours"], ["Me"])
        self.assertTrue(a["cells"][2]["break_before"], "19 days between AAA's GW7 and GW8 games")
        self.assertEqual(len(a["cells"][2]["games"]), 2, "double gameweek")
        self.assertEqual(rows["CCC"]["cells"][0]["games"], [], "blank gameweek")
        self.assertEqual(a["cells"][1]["games"][0], {"opponent": "CCC", "venue": "A", "difficulty": 1, "kickoff": "2026-10-17T14:00:00Z"})
        self.assertEqual([r["team"] for r in result["rows"]], sorted(rows, key=lambda t: rows[t]["next4"]))
        self.assertEqual(league.ticker({}, TEAMS)["gameweeks"], [])

    def test_dashboard_ticker_uses_snapshot(self):
        snapshot = {"events": {"next": {"id": 6}}, "squad_snapshot": {"picks": [{"element": 9}]}, "fixtures": {"events": {"6": [fixture(6, 1, 2, "2026-10-10T14:00:00Z")]}}}
        catalog = {"players": [{"id": 9, "web_name": "Nine", "team": 2}], "teams": [{"id": 1, "short_name": "AAA"}, {"id": 2, "short_name": "BBB"}]}
        rows = {r["team"]: r for r in dashboard.fixture_ticker(snapshot, catalog)["rows"]}
        self.assertEqual(rows["BBB"]["yours"], ["Nine"])


def picks_for(squad, captain):
    return {"entry_history": {"bank": 5, "value": 1000}, "picks": [{"element": e, "is_captain": e == captain} for e in squad]}


class FakeFPL:
    def __init__(self, fail=()):
        self.fail = set(fail)
        yours = list(range(1, 16))
        self.squads = {10: yours, 20: [1, 2, 3, 20, 21] + list(range(30, 40)), 30: [1, 2, 20, 21, 22] + list(range(40, 50)), 40: [1, 20, 22] + list(range(50, 62))}

    def __call__(self, path, ttl):
        if any(path.startswith(prefix) for prefix in self.fail):
            raise matchday.Unavailable("FPL returned HTTP 503")
        if path == "bootstrap-static/":
            return {"chips": RULES, "teams": [{"id": 1, "short_name": "T<1>"}],
                    "elements": [{"id": i, "web_name": f"P{i}", "team": 1, "selected_by_percent": "5.0"} for i in range(1, 70)],
                    "events": [{"id": 5, "is_current": True}, {"id": 6, "is_next": True}]}
        if path.startswith("leagues-classic/"):
            return {"standings": {"results": [
                {"entry": 20, "entry_name": "Leader <b>", "player_name": "L", "rank": 1, "total": 400},
                {"entry": 10, "entry_name": "Me", "player_name": "M", "rank": 2, "total": 390},
                {"entry": 30, "entry_name": "Third", "player_name": "T", "rank": 3, "total": 380},
                {"entry": 40, "entry_name": "Fourth", "player_name": "F", "rank": 4, "total": 370}]}}
        entry = int(path.split("/")[1])
        if path.endswith("/history/"):
            return {"chips": [{"name": "wildcard", "event": 3}] if entry == 20 else []}
        return picks_for(self.squads[entry], 1 if entry != 30 else 20)


SNAPSHOT = {"team_id": 10, "league_id": 99}


class ThreatTests(unittest.TestCase):
    def setUp(self):
        matchday.clear_cache()

    def test_threat_lists_and_table(self):
        result = league.threats(SNAPSHOT, FakeFPL())
        self.assertEqual((result["state"], result["rivals_compared"], result["gameweek"], result["chip_week"]), ("ready", 3, 5, 6))
        self.assertEqual([(r["id"], r["rivals"]) for r in result["missing"]], [(20, 3), (21, 2), (22, 2)], "owned by at least half (2 of 3)")
        self.assertEqual([r["id"] for r in result["shared"]], [1, 2])
        self.assertEqual({r["id"] for r in result["differentials"] if r["rivals"] == 0}, set(range(4, 16)), "nobody else owns 4–15")
        self.assertIn(3, [r["id"] for r in result["differentials"]], "one rival at most still counts")
        self.assertEqual({r["id"]: r["captained"] for r in result["captains"]}, {1: 2, 20: 1})
        table = {r["entry_id"]: r for r in result["table"]}
        self.assertEqual((table[20]["gap"], table[30]["gap"], table[20]["shared"]), (10, -10, 3))
        self.assertNotIn("Wildcard", [c["label"] for c in table[20]["chips_left"]])
        self.assertEqual(result["leader"], {"name": "Leader <b>", "gap": 10})

    def test_failures_degrade(self):
        result = league.threats(SNAPSHOT, FakeFPL(fail=("entry/30/",)))
        self.assertEqual((result["state"], result["rivals_compared"]), ("ready", 2))
        self.assertTrue(result["warnings"])
        self.assertEqual(league.threats(SNAPSHOT, FakeFPL(fail=("entry/10/",)))["state"], "unavailable")
        self.assertEqual(league.threats(SNAPSHOT, FakeFPL(fail=("leagues-classic",)))["state"], "unavailable")
        self.assertEqual(league.threats({}, FakeFPL())["state"], "unavailable")

    def test_ui_escapes(self):
        threats = league.threats(SNAPSHOT, FakeFPL())
        ticker = league.ticker({"6": [fixture(6, 1, 2, "2026-10-10T14:00:00Z")]}, {1: {"short_name": "<i>A</i>"}, 2: {"short_name": "B"}}, {1: ["<img src=x>"]}, 6)
        script = r'''
const fs = require("fs"); const vm = require("vm"); const ts = require("./dashboard/node_modules/typescript");
const load = (file, req) => { const out = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const context = { exports: {}, require: req, Math, JSON, Number, String, Intl, Date }; vm.runInNewContext(out, context); return context.exports; };
const kits = load("dashboard/kits.ts", () => ({}));
const lt = load("dashboard/league-threats.ts", (n) => (n === "./kits" ? kits : {}));
const check = (c, m) => { if (!c) throw new Error(m); };
const [threats, ticker] = JSON.parse(process.argv[1]);
const html = lt.renderThreats(threats, false);
check(!html.includes("<b>") && html.includes("Leader &lt;b&gt;"), "manager names escaped");
check(html.includes("They have, you don") && html.includes("Chips still in hand"), "sections");
check(lt.renderThreats({ state: "unavailable", reason: "<s>x</s>" }, false).includes("&lt;s&gt;"), "reason escaped");
check(lt.renderThreats(null, true).includes("Loading"), "loading");
const tk = lt.renderTicker(ticker);
check(!tk.includes("<i>A") && !tk.includes("<img") && tk.includes("&lt;img src=x&gt;"), "ticker escaped");
check(tk.includes("fdr-2") && tk.includes("GW6"), "difficulty colours");
'''
        result = subprocess.run(["node", "-e", script, json.dumps([threats, ticker])], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()


class WatchlistTests(unittest.TestCase):
    def test_config_validation(self):
        import tempfile, os
        from fpl_brief import config as cfg
        good = {"player_id": 121, "from_gw": 10, "to_gw": 11, "note": "n", "trigger": "t"}
        for bad in ({**good, "from_gw": 12}, {**good, "player_id": True}, {**good, "to_gw": 39}, {**good, "note": "x" * 301}, "121"):
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, "config.json")
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump({"watchlist": [bad]}, handle)
                with self.assertRaises(ValueError):
                    cfg.load(path)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "config.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"watchlist": [good]}, handle)
            self.assertEqual(cfg.load(path)["watchlist"], [good])

    def test_windows_and_render(self):
        catalog = {"players": [{"id": 121, "web_name": "<b>Mitoma</b>", "team": 1, "element_type": 3, "now_cost": 59, "status": "i", "chance_of_playing_next_round": 0, "news": "<i>Hamstring</i>", "minutes": 0, "selected_by_percent": "0.0"}],
                   "teams": [{"id": 1, "short_name": "BHA"}]}
        item = {"player_id": 121, "from_gw": 10, "to_gw": 11, "note": "<script>n</script>", "trigger": "t"}
        windows = [dashboard.watchlist({"watchlist": [item]}, {"events": {"next": {"id": gw}}}, catalog)[0] for gw in (6, 10, 11, 12)]
        self.assertEqual([(w["window"], w["weeks_until"]) for w in windows], [("early", 4), ("open", 0), ("open", 0), ("passed", 0)])
        self.assertEqual(dashboard.watchlist({"watchlist": [item]}, {}, catalog)[0]["window"], "unknown")
        script = r'''
const fs = require("fs"); const vm = require("vm"); const ts = require("./dashboard/node_modules/typescript");
const load = (file, req) => { const out = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const context = { exports: {}, require: req, Math, JSON, Number, String, Intl, Date }; vm.runInNewContext(out, context); return context.exports; };
const kits = load("dashboard/kits.ts", () => ({}));
const lt = load("dashboard/league-threats.ts", (n) => (n === "./kits" ? kits : {}));
const html = lt.renderWatchlist(JSON.parse(process.argv[1]));
if (/<b>|<i>|<script>/.test(html)) throw new Error("not escaped");
if (!html.includes("in 4 weeks") || !html.includes("Not yet") || !html.includes("injured (0%)")) throw new Error("content: " + html);
if (lt.renderWatchlist([]) !== "") throw new Error("empty list renders nothing");
'''
        result = subprocess.run(["node", "-e", script, json.dumps([windows[0]])], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
