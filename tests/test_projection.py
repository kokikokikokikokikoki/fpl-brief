import math
import unittest

from fpl_brief import projection
from fpl_brief.collect import HISTORY_FIELDS, team_results


def result(home, away, hg, ag, hxg=None, axg=None, gw=1, fixture_id=1):
    return {"gw": gw, "fixture_id": fixture_id, "home": home, "away": away, "home_goals": hg, "away_goals": ag, "home_xg": hxg, "away_xg": axg}


def season():
    """Club 1 attacks well, club 4 defends badly; everyone plays everyone home and away."""
    strength = {1: 2.4, 2: 1.3, 3: 1.1, 4: 0.9}
    leak = {1: 0.8, 2: 1.0, 3: 1.1, 4: 1.6}
    rows, fixture_id = [], 0
    for home in strength:
        for away in strength:
            if home != away:
                fixture_id += 1
                rows.append(result(home, away, 0, 0, round(strength[home] * leak[away], 2), round(strength[away] * leak[home], 2), fixture_id=fixture_id))
    return rows


def snapshot(fixtures_by_gw, results=None, next_id=6):
    snap = {"events": {"next": {"id": next_id}}, "fixtures": {"events": {str(gw): rows for gw, rows in fixtures_by_gw.items()}}}
    if results is not None:
        snap["team_results"] = results
    return snap


def player(pid, team, kind=3, ep="6.0", status="a", **extra):
    return {"id": pid, "team": team, "element_type": kind, "ep_next": ep, "status": status, **extra}


class RatingTests(unittest.TestCase):
    def test_empty_season_rates_every_club_average(self):
        ratings = projection.team_ratings([], [1, 2, 3])
        self.assertEqual(ratings["matches"], 0)
        self.assertEqual(set(ratings["attack"].values()) | set(ratings["defence"].values()), {1.0})
        self.assertEqual(ratings["home"], 1.0)
        view = projection.fixture_view(ratings, 1, 2, True)
        self.assertAlmostEqual(projection.multiplier(view, 3), 1.0)
        self.assertAlmostEqual(projection.multiplier(view, 1), 1.0)

    def test_strong_attack_against_weak_defence_has_higher_multiplier(self):
        ratings = projection.team_ratings(season())
        self.assertGreater(ratings["attack"][1], 1.0)
        self.assertGreater(ratings["defence"][4], 1.0)
        strong = projection.fixture_view(ratings, 1, 4, True)
        reverse = projection.fixture_view(ratings, 4, 1, True)
        self.assertGreater(projection.multiplier(strong, 4), projection.multiplier(reverse, 4))
        self.assertGreater(strong["cs_prob"], reverse["cs_prob"])
        # Negative binomial: the Poisson zero chance, lifted a little by the ratings' remaining uncertainty.
        shape = strong["cs_shape"]
        self.assertAlmostEqual(strong["cs_prob"], (1 + strong["lambda_against"] / shape) ** -shape)
        self.assertGreater(strong["cs_prob"], math.exp(-strong["lambda_against"]))

    def test_fit_is_deterministic(self):
        self.assertEqual(projection.team_ratings(season()), projection.team_ratings(list(reversed(season()))))

    def test_shrinkage_pulls_one_match_team_towards_average(self):
        ratings = projection.team_ratings([result(1, 2, 0, 0, 5.0, 0.1)])
        self.assertGreater(ratings["attack"][1], 1.0)
        self.assertLess(ratings["attack"][1], 1.5)
        self.assertLess(ratings["attack"][1] / ratings["attack"][2], 5.0 / 0.1)

    def test_xg_falls_back_to_goals_when_null(self):
        with_goals = projection.team_ratings([result(1, 2, 3, 0, None, None)])
        with_xg = projection.team_ratings([result(1, 2, 3, 0, 3.0, 0.0)])
        self.assertAlmostEqual(with_goals["attack"][1], with_xg["attack"][1])
        ignored_goals = projection.team_ratings([result(1, 2, 0, 3, 3.0, 0.0)])
        self.assertAlmostEqual(ignored_goals["attack"][1], with_xg["attack"][1])


class CleanSheetCalibrationTests(unittest.TestCase):
    def test_goals_below_xg_still_predicts_the_actual_clean_sheet_rate(self):
        # Six equal clubs, home and away (60 team-matches). xG is 1.6 per side, but goals run lower (1.1 per
        # side, 30% clean sheets), as in 2026/27 GW1-5 where xG ran ~8% above goals.
        clubs, goals = range(1, 7), [0, 1, 2, 0, 1, 1, 3, 0, 1, 2]
        rows, index = [], 0
        for home in clubs:
            for away in clubs:
                if home != away:
                    rows.append(result(home, away, goals[index % 10], goals[(index + 3) % 10], 1.6, 1.6, fixture_id=index))
                    index += 1
        actual = sum((row["home_goals"] == 0) + (row["away_goals"] == 0) for row in rows) / (2 * len(rows))
        ratings = projection.team_ratings(rows)
        self.assertAlmostEqual(ratings["base"], 1.6)
        self.assertAlmostEqual(ratings["level"], 1.1)
        views = [projection.fixture_view(ratings, row[side], row[other], side == "home") for row in rows
                 for side, other in (("home", "away"), ("away", "home"))]
        predicted = sum(view["cs_prob"] for view in views) / len(views)
        self.assertAlmostEqual(actual, 0.3)
        self.assertLess(abs(predicted - actual), 0.05)
        self.assertAlmostEqual(sum(view["lambda_against"] for view in views) / len(views), 1.1, places=2)
        # The old xG-level Poisson answer was far off, so the check above is meaningful.
        self.assertGreater(actual - math.exp(-1.6), 0.09)

    def test_no_goals_yet_falls_back_to_the_xg_level(self):
        ratings = projection.team_ratings([result(1, 2, 0, 0, 1.2, 0.8)])
        self.assertIsNone(projection.goal_level([result(1, 2, 0, 0, 1.2, 0.8)]))
        self.assertAlmostEqual(ratings["level"], ratings["base"])

    def test_zero_chance_is_poisson_without_uncertainty(self):
        self.assertAlmostEqual(projection.zero_chance(1.4), math.exp(-1.4))
        self.assertAlmostEqual(projection.zero_chance(1.4, 1e9), math.exp(-1.4), places=6)
        self.assertGreater(projection.zero_chance(1.4, 5.0), math.exp(-1.4))
        self.assertEqual(projection.zero_chance(0.0, 5.0), 1.0)
        # More matches mean a larger shape, so less uplift.
        self.assertGreater(projection.combined_shape(30.0, 30.0), projection.combined_shape(8.0, 8.0))


class ProjectionTests(unittest.TestCase):
    def test_double_gameweek_sums_and_blank_gives_zero(self):
        fixtures = {6: [{"team_h": 1, "team_a": 2}], 7: [{"team_h": 1, "team_a": 3}, {"team_h": 4, "team_a": 1}], 8: [{"team_h": 2, "team_a": 3}]}
        built = projection.build(snapshot(fixtures, []), {"players": [player(10, 1)], "teams": [{"id": t} for t in range(1, 5)]})
        row = built["players"][10]
        self.assertEqual(built["gameweeks"], [6, 7, 8])
        self.assertEqual(row["xp"], [6.0, 12.0, 0.0])
        self.assertEqual(row["xp_6"], 18.0)

    def test_base_is_defixtured_from_ep_next(self):
        ratings = projection.team_ratings(season())
        fixtures = {6: [{"team_h": 1, "team_a": 4}], 7: [{"team_h": 4, "team_a": 1}]}
        built = projection.build(snapshot(fixtures, season()), {"players": [player(10, 1, kind=4, ep="8.0")]})
        easy = projection.multiplier(projection.fixture_view(ratings, 1, 4, True), 4)
        harder = projection.multiplier(projection.fixture_view(ratings, 1, 4, False), 4)
        row = built["players"][10]
        self.assertEqual(row["xp"][0], 8.0)
        self.assertAlmostEqual(row["xp"][1], round(8.0 / easy * harder, 2), places=2)
        self.assertTrue(built["ratings_fitted"])

    def test_decay_weights_later_weeks(self):
        fixtures = {gw: [{"team_h": 1, "team_a": 2}] for gw in range(6, 13)}
        row = projection.build(snapshot(fixtures, []), {"players": [player(10, 1, ep="5.0")]})["players"][10]
        self.assertEqual(len(row["xp"]), 6)
        self.assertEqual(row["xp_6"], 30.0)
        self.assertEqual(row["xp_6_decayed"], round(sum(5.0 * 0.85 ** k for k in range(6)), 2))

    def test_unavailable_player_projects_zero(self):
        fixtures = {6: [{"team_h": 1, "team_a": 2}]}
        row = projection.build(snapshot(fixtures, []), {"players": [player(10, 1, status="i")]})["players"][10]
        self.assertEqual((row["xp"], row["xp_6"]), ([0.0], 0.0))
        self.assertTrue(row["flags"])

    def test_no_fixture_next_week_uses_form_and_flags_it(self):
        fixtures = {6: [{"team_h": 2, "team_a": 3}], 7: [{"team_h": 1, "team_a": 2}]}
        row = projection.build(snapshot(fixtures, []), {"players": [player(10, 1, ep="0.0", form="4.5")]})["players"][10]
        self.assertEqual(row["xp"], [0.0, 4.5])
        self.assertIn("form", row["flags"][0])

    def test_missing_team_results_runs_with_average_ratings_and_says_so(self):
        built = projection.build(snapshot({6: [{"team_h": 1, "team_a": 2}]}), {"players": [player(10, 1)]})
        self.assertFalse(built["ratings_fitted"])
        self.assertIn("no team results", built["caveats"][0])
        self.assertEqual(built["players"][10]["xp"], [6.0])

    def test_squad_horizon_picks_best_xi_each_week(self):
        players = {pid: {"element_type": kind} for pid, kind in enumerate([1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4], start=1)}
        projections = {pid: {"xp": [1.0, 2.0]} for pid in players}
        projections[2] = {"xp": [0.0, 0.0]}
        self.assertEqual(projection.squad_horizon(projections, players, list(players)), round(11 + 22 * 0.85, 2))


class TeamResultsCollectorTests(unittest.TestCase):
    class FakeClient:
        def __init__(self, pages):
            self.pages, self.calls = pages, []

        def get(self, path):
            self.calls.append(path)
            value = self.pages[path]
            if isinstance(value, Exception):
                raise value
            return value

    def test_builds_rows_with_xg_dgw_split_and_failed_live_fetch(self):
        fixtures = [
            {"id": 1, "event": 1, "finished": True, "team_h": 1, "team_a": 2, "team_h_score": 2, "team_a_score": 1},
            {"id": 2, "event": 2, "finished": True, "team_h": 3, "team_a": 1, "team_h_score": 0, "team_a_score": 0},
            {"id": 3, "event": 2, "finished": True, "team_h": 1, "team_a": 2, "team_h_score": 1, "team_a_score": 1},
            {"id": 4, "event": 3, "finished": True, "team_h": 2, "team_a": 3, "team_h_score": 4, "team_a_score": 0},
            {"id": 5, "event": 4, "finished": False, "team_h": 1, "team_a": 3, "team_h_score": None, "team_a_score": None},
        ]
        elements = [{"id": 11, "team": 1}, {"id": 12, "team": 1}, {"id": 21, "team": 2}, {"id": 31, "team": 3}, {"id": 99, "team": 2}]
        live1 = {"elements": [
            {"id": 11, "stats": {"expected_goals": "0.80"}, "explain": [{"fixture": 1, "stats": []}]},
            {"id": 12, "stats": {"expected_goals": "0.45"}, "explain": [{"fixture": 1, "stats": []}]},
            {"id": 21, "stats": {"expected_goals": "0.30"}, "explain": [{"fixture": 1, "stats": []}]},
            {"id": 99, "stats": {"expected_goals": "0.50"}, "explain": [{"fixture": 77, "stats": []}]},
        ]}
        live2 = {"elements": [
            {"id": 11, "stats": {"expected_goals": "1.00"}, "explain": [{"fixture": 2, "stats": []}, {"fixture": 3, "stats": []}]},
            {"id": 21, "stats": {"expected_goals": "0.20"}, "explain": [{"fixture": 3, "stats": [{"identifier": "expected_goals", "value": 0.2}]}]},
            {"id": 31, "stats": {"expected_goals": "0.60"}, "explain": [{"fixture": 2, "stats": []}]},
        ]}
        client = self.FakeClient({"event/1/live/": live1, "event/2/live/": live2, "event/3/live/": RuntimeError("timeout")})
        warnings = []
        rows = team_results(client, fixtures, elements, warnings)
        self.assertEqual(client.calls, ["event/1/live/", "event/2/live/", "event/3/live/"])
        self.assertEqual([row["fixture_id"] for row in rows], [1, 2, 3, 4])
        self.assertEqual(rows[0], {"gw": 1, "fixture_id": 1, "home": 1, "away": 2, "home_goals": 2, "away_goals": 1, "home_xg": 1.25, "away_xg": 0.3})
        # Club 1 played twice in GW2 and FPL's explain has no per-fixture xG: its xG is null in both.
        self.assertEqual((rows[1]["home_xg"], rows[1]["away_xg"]), (0.6, None))
        self.assertEqual((rows[2]["home_xg"], rows[2]["away_xg"]), (None, 0.2))
        self.assertEqual((rows[3]["home_xg"], rows[3]["away_xg"], rows[3]["home_goals"]), (None, None, 4))
        self.assertEqual(len(warnings), 1)
        self.assertIn("GW3", warnings[0])

    def test_player_history_rows_from_the_same_live_calls(self):
        fixtures = [
            {"id": 1, "event": 1, "finished": True, "team_h": 1, "team_a": 2, "team_h_score": 2, "team_a_score": 1},
            {"id": 2, "event": 2, "finished": True, "team_h": 1, "team_a": 2, "team_h_score": 0, "team_a_score": 0},
            {"id": 3, "event": 3, "finished": True, "team_h": 1, "team_a": 2, "team_h_score": 1, "team_a_score": 0},
            {"id": 4, "event": 3, "finished": False, "team_h": 2, "team_a": 1, "team_h_score": None, "team_a_score": None},
        ]
        elements = [{"id": 11, "team": 1}, {"id": 21, "team": 2}, {"id": 22, "team": 2}]
        minutes = lambda value: {"identifier": "minutes", "value": value, "points": 2}
        live1 = {"elements": [
            {"id": 11, "stats": {"minutes": 90, "starts": 1, "expected_goals": "0.81", "expected_assists": "0.10", "goals_scored": 1, "bonus": 3,
                                 "defensive_contribution": 12, "total_points": 12, "yellow_cards": 1},
             "explain": [{"fixture": 1, "stats": [minutes(90), {"identifier": "defensive_contribution", "value": 12, "points": 2}]}]},
            {"id": 21, "stats": {"minutes": 0, "expected_goals": "0.00"}, "explain": []},
            {"id": 22, "stats": {"minutes": 45, "saves": 4, "goals_conceded": 2, "total_points": 1}, "explain": [{"fixture": 1, "stats": [minutes(45)]}]},
        ]}
        live3 = {"elements": [{"id": 11, "stats": {"minutes": 90, "expected_goals": "0.2"}, "explain": [{"fixture": 3, "stats": [minutes(90)]}]}]}
        client = self.FakeClient({"event/1/live/": live1, "event/2/live/": RuntimeError("timeout"), "event/3/live/": live3})
        warnings, history = [], []
        team_results(client, fixtures, elements, warnings, history)
        rows = [dict(zip(HISTORY_FIELDS, row)) for row in history]
        # GW2 failed (warned) and GW3 is still being played, so only GW1 rows are kept; 0-minute players are skipped.
        self.assertEqual([(row["gw"], row["id"]) for row in rows], [(1, 11), (1, 22)])
        self.assertEqual({key: rows[0][key] for key in ("team", "fixtures", "minutes", "starts", "xg", "xa", "goals", "bonus", "defcon_points", "yellow", "total_points")},
                         {"team": 1, "fixtures": 1, "minutes": 90, "starts": 1, "xg": 0.81, "xa": 0.1, "goals": 1, "bonus": 3, "defcon_points": 2, "yellow": 1, "total_points": 12})
        self.assertEqual((rows[1]["saves"], rows[1]["gc"], rows[1]["defcon_points"]), (4, 2, 0))
        self.assertTrue(any("GW2" in warning for warning in warnings))

    def test_bad_player_row_drops_only_that_gameweeks_player_rows_not_club_xg(self):
        fixtures = [
            {"id": 1, "event": 1, "finished": True, "team_h": 1, "team_a": 2, "team_h_score": 2, "team_a_score": 1},
            {"id": 2, "event": 2, "finished": True, "team_h": 2, "team_a": 1, "team_h_score": 0, "team_a_score": 0},
        ]
        elements = [{"id": 11, "team": 1}, {"id": 21, "team": 2}]
        minutes = {"identifier": "minutes", "value": 90, "points": 2}
        live1 = {"elements": [
            {"id": 11, "stats": {"minutes": 90, "expected_goals": "0.80"}, "explain": [{"fixture": 1, "stats": [minutes]}]},
            # Malformed explain stats: fine for club xG, but breaks the player-row parser.
            {"id": 21, "stats": {"minutes": 90, "expected_goals": "0.30"}, "explain": [{"fixture": 1, "stats": 5}]},
        ]}
        live2 = {"elements": [{"id": 11, "stats": {"minutes": 90, "expected_goals": "0.40"}, "explain": [{"fixture": 2, "stats": [minutes]}]}]}
        client = self.FakeClient({"event/1/live/": live1, "event/2/live/": live2})
        warnings, history = [], []
        rows = team_results(client, fixtures, elements, warnings, history)
        self.assertEqual((rows[0]["home_xg"], rows[0]["away_xg"]), (0.8, 0.3))
        self.assertEqual((rows[1]["home_xg"], rows[1]["away_xg"]), (0.0, 0.4))
        self.assertEqual([(row[0], row[1]) for row in history], [(2, 11)])
        self.assertEqual(len(warnings), 1)
        self.assertIn("GW1 player rows", warnings[0])
        self.assertIn("club xG is kept", warnings[0])


if __name__ == "__main__":
    unittest.main()
