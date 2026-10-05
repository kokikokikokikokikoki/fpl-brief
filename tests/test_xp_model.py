import math
import unittest

from fpl_brief import projection, xp_model
from fpl_brief.collect import HISTORY_FIELDS

AVERAGE = projection.team_ratings([], [1, 2, 3])


def row(gw, pid, team=1, minutes=90, **stats):
    values = {"gw": gw, "id": pid, "team": team, "fixtures": 1, "minutes": minutes, "starts": 1 if minutes >= 60 else 0,
              "xg": 0.0, "xa": 0.0, "goals": 0, "assists": 0, "cs": 0, "gc": 0, "saves": 0, "defcon_points": 0,
              "bonus": 0, "yellow": 0, "red": 0, "total_points": 2}
    values.update(stats)
    return values


def player(pid, kind=3, team=1, cost=60, **extra):
    return {"id": pid, "element_type": kind, "team": team, "now_cost": cost, "status": "a", "chance_of_playing_next_round": None, "news": "", **extra}


def results(gameweeks, clubs=(1, 2)):
    return [{"gw": gw, "home": clubs[0], "away": clubs[1]} for gw in gameweeks]


def one_fixture(gameweeks, team=1, opponent=2):
    return {gw: {team: [(opponent, True)]} for gw in gameweeks}


class ScoringTests(unittest.TestCase):
    profile = {"p_play": 1.0, "p_60": 1.0, "minutes": 90.0}
    rate = {"xg": 0.5, "xa": 0.2, "saves": 1.0, "defcon": 0.4, "bonus": 0.3, "cards": -0.1}

    def test_points_follow_the_2026_27_table_by_position(self):
        view = projection.fixture_view(AVERAGE, 1, 2, True)
        parts = {kind: xp_model.fixture_points(kind, self.profile, self.rate, view) for kind in (1, 2, 3, 4)}
        self.assertEqual([round(parts[kind]["goals"], 6) for kind in (1, 2, 3, 4)], [5.0, 3.0, 2.5, 2.0])
        self.assertTrue(all(round(parts[kind]["assists"], 6) == 0.6 for kind in parts))
        cs = view["cs_prob"]
        self.assertEqual([round(parts[kind]["clean_sheet"], 6) for kind in (1, 2, 3, 4)], [round(4 * cs, 6), round(4 * cs, 6), round(cs, 6), 0.0])
        half = xp_model.expected_half_goals(view["lambda_against"])
        self.assertAlmostEqual(parts[1]["conceded"], -half)
        self.assertAlmostEqual(parts[2]["conceded"], -half)
        self.assertEqual((parts[3]["conceded"], parts[4]["conceded"]), (0.0, 0.0))
        self.assertEqual(parts[3]["appearance"], 2.0)

    def test_saves_only_count_for_goalkeepers(self):
        rows = [row(gw, 1, saves=6) for gw in (1, 2)] + [row(gw, 2, saves=6) for gw in (1, 2)]
        fitted = xp_model.fit(rows, [player(1, kind=1), player(2, kind=2)])
        self.assertGreater(xp_model.rates(fitted, player(1, kind=1))["saves"], 0)
        self.assertEqual(xp_model.rates(fitted, player(2, kind=2))["saves"], 0.0)

    def test_expected_half_goals_matches_poisson_sum(self):
        lam = 1.3
        exact = sum((n // 2) * math.exp(-lam) * lam ** n / math.factorial(n) for n in range(40))
        self.assertAlmostEqual(xp_model.expected_half_goals(lam), exact, places=9)
        self.assertEqual(xp_model.expected_half_goals(0), 0.0)
        # P(GC >= 2) is the floor's first step, so E[floor(GC/2)] sits between it and lam/2.
        self.assertLess(xp_model.expected_half_goals(lam), lam / 2)
        self.assertGreater(xp_model.expected_half_goals(lam), 1 - math.exp(-lam) * (1 + lam))


class ShrinkageTests(unittest.TestCase):
    def test_zero_minutes_gives_the_prior(self):
        rows = [row(gw, 2, xg=0.6) for gw in range(1, 6)]
        fitted = xp_model.fit(rows, [player(1), player(2)])
        prior = fitted["priors"][(3,)]["xg"]
        self.assertAlmostEqual(prior, 0.6)
        self.assertAlmostEqual(xp_model.rates(fitted, player(1))["xg"], prior)

    def test_heavy_minutes_player_tends_to_own_rate(self):
        rows = [row(gw, 1, xg=1.0) for gw in range(1, 39)] + [row(gw, 2, xg=0.1) for gw in range(1, 39)]
        light = [row(1, 1, xg=1.0)] + [row(gw, 2, xg=0.1) for gw in range(1, 39)]
        heavy_rate = xp_model.rates(xp_model.fit(rows, [player(1), player(2)]), player(1))["xg"]
        light_rate = xp_model.rates(xp_model.fit(light, [player(1), player(2)]), player(1))["xg"]
        self.assertGreater(heavy_rate, 0.75)
        self.assertLess(heavy_rate, 1.0)
        self.assertLess(light_rate, heavy_rate)
        self.assertAlmostEqual(xp_model.shrink(10, 10, 0.2, 10), 0.6)

    def test_attacking_prior_uses_price_band_with_position_fallback(self):
        rows = [row(gw, 1, xg=0.8) for gw in range(1, 11)] + [row(gw, 2, xg=0.1) for gw in range(1, 11)] + [row(1, 3, minutes=30, xg=0.5)]
        players = [player(1, cost=100), player(2, cost=45), player(3, cost=70), player(4, cost=100)]
        fitted = xp_model.fit(rows, players)
        self.assertAlmostEqual(xp_model.rates(fitted, player(4, cost=100))["xg"], 0.8)
        # The £7.0m band has only 30 minutes pooled, so the position prior is used.
        self.assertNotIn((3, xp_model.price_band(70)), fitted["priors"])

    def test_history_rows_reads_the_columnar_file(self):
        doc = {"fields": list(HISTORY_FIELDS), "rows": [[1, 7, 2, 1, 90, 1, 0.5, 0.1, 1, 0, 0, 1, 0, 2, 3, 0, 0, 12], [1, 8]]}
        rows = xp_model.history_rows(doc)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["id"], rows[0]["defcon_points"], rows[0]["total_points"]), (7, 2, 12))


class MinutesTests(unittest.TestCase):
    def test_recent_weighted_minutes_and_missed_club_gameweeks(self):
        rows = [row(1, 1, minutes=90), row(2, 1, minutes=90), row(4, 1, minutes=30)]
        fitted = xp_model.fit(rows, [player(1)], results([1, 2, 3, 4]))
        profile = xp_model.minutes_profile(fitted, player(1))
        weights = [0.8 ** 3, 0.8 ** 2, 0.8, 1.0]
        self.assertAlmostEqual(profile["p_play"], (weights[0] + weights[1] + weights[3]) / sum(weights))
        self.assertAlmostEqual(profile["p_60"], (weights[0] + weights[1]) / sum(weights))
        self.assertAlmostEqual(profile["minutes"], (90 * weights[0] + 90 * weights[1] + 30) / sum(weights))

    def test_doubt_applies_to_next_gameweek_only(self):
        rows = [row(gw, 1) for gw in range(1, 6)]
        fitted = xp_model.fit(rows, [player(1)], results(range(1, 6)))
        doubtful = player(1, status="d", chance_of_playing_next_round=75)
        fit_row = xp_model.project_player(fitted, player(1), one_fixture([6, 7, 8]), [6, 7, 8], AVERAGE, 6)
        doubt_row = xp_model.project_player(fitted, doubtful, one_fixture([6, 7, 8]), [6, 7, 8], AVERAGE, 6)
        self.assertAlmostEqual(doubt_row["xp"][0], fit_row["xp"][0] * 0.75, delta=0.011)
        self.assertEqual(doubt_row["xp"][1:], fit_row["xp"][1:])
        self.assertIn("GW6 only", doubt_row["flags"][0])

    def test_injured_player_returns_from_news_date_or_next_plus_two(self):
        rows = [row(gw, 1) for gw in range(1, 4)]
        fitted = xp_model.fit(rows, [player(1)], results(range(1, 6)))  # missed GW4-5 through injury
        gameweeks = [6, 7, 8, 9]
        dates = {6: projection_date(10, 3), 7: projection_date(10, 17), 8: projection_date(10, 24), 9: projection_date(10, 31)}
        injured = player(1, status="i", chance_of_playing_next_round=0, news="Hamstring injury - Expected back 20 Oct")
        known = xp_model.project_player(fitted, injured, one_fixture(gameweeks), gameweeks, AVERAGE, 6, dates)
        self.assertEqual([value > 0 for value in known["xp"]], [False, False, True, True])
        self.assertIn("back from GW8 (from FPL news)", known["flags"][0])
        # On return he plays at his pre-injury rate, not the zeros of the gameweeks he missed.
        self.assertEqual(known["minutes"]["p_play"], 1.0)
        unknown = xp_model.project_player(fitted, dict(injured, news="Knee injury - Unknown return date"), one_fixture(gameweeks), gameweeks, AVERAGE, 6, dates)
        self.assertEqual([value > 0 for value in unknown["xp"]], [False, False, True, True])
        self.assertIn("next GW + 2", unknown["flags"][0])
        gone = xp_model.project_player(fitted, player(1, status="u"), one_fixture(gameweeks), gameweeks, AVERAGE, 6, dates)
        self.assertEqual(gone["xp_6"], 0.0)

    def test_suspension_news_until_date(self):
        dates = {6: projection_date(10, 3), 7: projection_date(10, 17)}
        self.assertEqual(xp_model.return_gameweek({"news": "Suspended until 10 Oct"}, 6, dates), (7, True))
        self.assertEqual(xp_model.return_gameweek({"news": "Suspended until 10 Oct"}, 7, dates), (8, True))


class HorizonTests(unittest.TestCase):
    def test_double_gameweek_sums_and_blank_gives_zero(self):
        rows = [row(gw, 1, xg=0.4) for gw in range(1, 4)]
        fitted = xp_model.fit(rows, [player(1)], results(range(1, 4)))
        fixtures = {6: {1: [(2, True)]}, 7: {1: [(2, True), (3, False)]}, 8: {}}
        projected = xp_model.project_player(fitted, player(1), fixtures, [6, 7, 8], AVERAGE, 6)
        self.assertAlmostEqual(projected["xp"][1], 2 * projected["xp"][0], places=1)
        self.assertEqual(projected["xp"][2], 0.0)
        self.assertEqual(set(projected["breakdown"][0]), set(xp_model.BREAKDOWN_KEYS))
        self.assertAlmostEqual(sum(projected["breakdown_total"].values()), projected["xp_6"], places=1)

    def test_build_with_own_model_and_without_history(self):
        snapshot = {"events": {"next": {"id": 6}}, "fixtures": {"events": {"6": [{"team_h": 1, "team_a": 2}]}}, "team_results": results(range(1, 4))}
        catalog = {"players": [player(1)]}
        built = projection.build(snapshot, catalog, model="own", history={"fields": list(HISTORY_FIELDS), "rows": [[gw, 1, 1, 1, 90, 1, 0.3, 0.1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2] for gw in (1, 2, 3)]})
        self.assertEqual(built["model"], "own")
        self.assertTrue(built["available"])
        self.assertGreater(built["players"][1]["xp_6"], 2.0)
        empty = projection.build(snapshot, catalog, model="own", history=None)
        self.assertFalse(empty["available"])
        self.assertEqual(empty["players"][1]["xp_6"], 0.0)
        self.assertEqual(projection.build(snapshot, catalog)["model"], "fpl")
        with self.assertRaises(ValueError):
            projection.build(snapshot, catalog, model="other")


def projection_date(month, day):
    from datetime import date
    return date(2026, month, day)


if __name__ == "__main__":
    unittest.main()
