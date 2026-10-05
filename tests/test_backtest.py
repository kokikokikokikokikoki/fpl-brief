import copy
import io
import json
import unittest
from contextlib import redirect_stdout

from fpl_brief import backtest
from fpl_brief.collect import HISTORY_FIELDS


def season(gameweeks=5):
    """Two clubs, two players each, every gameweek; player 1 is the scorer."""
    results, rows = [], []
    for gw in range(1, gameweeks + 1):
        results.append({"gw": gw, "fixture_id": gw, "home": 1 if gw % 2 else 2, "away": 2 if gw % 2 else 1,
                        "home_goals": 1, "away_goals": 1, "home_xg": 1.2, "away_xg": 1.0})
        for pid, team, xg, points in ((1, 1, 0.7, 8), (2, 1, 0.1, 2), (3, 2, 0.3, 3), (4, 2, 0.0, 1)):
            values = {"gw": gw, "id": pid, "team": team, "fixtures": 1, "minutes": 90, "starts": 1, "xg": xg, "xa": 0.1,
                      "goals": 0, "assists": 0, "cs": 0, "gc": 1, "saves": 0, "defcon_points": 0, "bonus": 0,
                      "yellow": 0, "red": 0, "total_points": points}
            rows.append([values[field] for field in HISTORY_FIELDS])
    history = {"fields": list(HISTORY_FIELDS), "rows": rows}
    catalog = {"players": [{"id": pid, "team": team, "element_type": kind, "now_cost": cost}
                           for pid, team, kind, cost in ((1, 1, 4, 100), (2, 1, 2, 45), (3, 2, 3, 70), (4, 2, 1, 40))]}
    return history, results, catalog


class BacktestTests(unittest.TestCase):
    def test_predictions_never_use_the_predicted_gameweek_or_later(self):
        history, results, catalog = season()
        rows = backtest.xp_model.history_rows(history)
        before = backtest.predict_gameweek(rows, results, catalog["players"], 4)
        changed = copy.deepcopy(history)
        for row in changed["rows"]:
            if row[0] >= 4:
                row[HISTORY_FIELDS.index("xg")] = 5.0
                row[HISTORY_FIELDS.index("minutes")] = 10
        changed_results = [dict(row, home_xg=6.0, away_xg=0.0) if row["gw"] >= 4 else row for row in results]
        after = backtest.predict_gameweek(backtest.xp_model.history_rows(changed), changed_results, catalog["players"], 4)
        self.assertEqual(before, after)
        # Changing an earlier gameweek does change the answer, so the check above is meaningful.
        earlier = copy.deepcopy(history)
        for row in earlier["rows"]:
            if row[0] == 3:
                row[HISTORY_FIELDS.index("xg")] = 5.0
        self.assertNotEqual(before, backtest.predict_gameweek(backtest.xp_model.history_rows(earlier), results, catalog["players"], 4))

    def test_report_scores_models_and_baselines(self):
        history, results, catalog = season()
        report = backtest.run(history, results, catalog, ep_log=None, top=2)
        self.assertEqual(report["gameweeks"], [3, 4, 5])
        by_name = {row["model"]: row for row in report["summary"]}
        self.assertEqual(by_name["our model"]["all"]["n"], 12)
        self.assertEqual(by_name["our model"]["top"]["n"], 6)
        self.assertEqual(by_name["points per game"]["all"]["mae"], 0.0)  # every player scores the same each week
        self.assertFalse(by_name["FPL ep_next (logged)"]["available"])
        self.assertEqual(by_name["our model"]["all"]["spearman"], 1.0)
        text = backtest.table(report)
        self.assertIn("our model", text)
        self.assertIn("no data for these gameweeks", text)

    def test_logged_ep_next_is_compared_when_present(self):
        history, results, catalog = season()
        log = {"gameweeks": {"4": {"ep_next": {"1": 8.0, "2": 2.0, "3": 3.0}}}}
        report = backtest.run(history, results, catalog, ep_log=log)
        logged = next(row for row in report["summary"] if row["model"] == "FPL ep_next (logged)")
        self.assertTrue(logged["available"])
        self.assertEqual((logged["all"]["n"], logged["all"]["mae"]), (3, 0.0))

    def test_baselines_and_spearman(self):
        rows = [{"gw": gw, "id": 1, "total_points": points} for gw, points in ((1, 2), (2, 6), (4, 10))]
        ppg, last = backtest.baselines(rows, 5)
        self.assertEqual(ppg[1], 6.0)
        self.assertAlmostEqual(last[1], (6 + 10) / 3)
        self.assertAlmostEqual(backtest.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(backtest.spearman([1, 2, 3], [3, 2, 1]), -1.0)
        self.assertIsNone(backtest.spearman([1, 1, 1], [1, 2, 3]))
        self.assertEqual(backtest.ranks([5, 1, 5]), [2.5, 1.0, 2.5])

    def test_json_output(self):
        history, results, catalog = season()
        report = backtest.run(history, results, catalog)
        self.assertEqual(json.loads(json.dumps(report))["top_by_price"], 100)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            print(backtest.table(report))
        self.assertIn("Backtest over GW3-GW5", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
