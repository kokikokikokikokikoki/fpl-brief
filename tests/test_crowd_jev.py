import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fpl_brief import crowd, jev_ask


def catalog(transfers=True):
    players = []
    for pid, (name, team, tin, tout, move, own) in {
        1: ("Alpha", 1, 50000, 1000, 1, "30.5"), 2: ("Beta", 2, 200, 90000, -1, "12.0"),
        3: ("Gamma", 1, 7000, 7000, 0, "5.1"), 4: ("Delta", 3, 120000, 500, 2, "44.0"),
    }.items():
        row = {"id": pid, "web_name": name, "team": team, "element_type": 3, "now_cost": 60, "selected_by_percent": own}
        if transfers:
            row.update(transfers_in_event=tin, transfers_out_event=tout, cost_change_event=move, cost_change_start=move)
        players.append(row)
    return {"players": players, "teams": [{"id": t, "short_name": f"T{t}"} for t in (1, 2, 3)]}


def snapshot():
    return {
        "squad_snapshot": {"picks": [{"element": 1}, {"element": 2}]},
        "events": {"next": {"id": 6, "transfers_made": 1234, "chip_plays": [], "most_captained": None},
                   "current": {"id": 5, "most_captained": 4, "top_element": 1, "chip_plays": [{"chip_name": "bboost", "num_played": 900}], "average_entry_score": 51}},
        "rivals": [
            {"comparison": {"comparable": True, "shared": [1], "rival_only": [4, 3]}},
            {"comparison": {"comparable": True, "shared": [1, 2], "rival_only": [4]}},
            {"comparison": {"comparable": False, "shared": [2], "rival_only": [3]}},
        ],
    }


class CrowdTests(unittest.TestCase):
    def test_unavailable_without_transfer_fields(self):
        self.assertEqual(crowd.build(snapshot(), catalog(transfers=False))["state"], "unavailable")

    def test_crowd_summary_and_league_context(self):
        result = crowd.build(snapshot(), catalog())
        self.assertEqual(result["state"], "ready")
        self.assertEqual([r["name"] for r in result["transfers_in"]][:2], ["Delta", "Alpha"])
        self.assertEqual(result["transfers_out"][0]["name"], "Beta")
        self.assertEqual([r["name"] for r in result["risers"]], ["Delta", "Alpha"])
        self.assertEqual([r["name"] for r in result["fallers"]], ["Beta"])
        squad = result["squad"]
        self.assertEqual((squad[1]["rival_owners"], squad[1]["net_transfers"], squad[1]["ownership"]), (2, 49000, 30.5))
        self.assertEqual(squad[2]["rival_owners"], 1, "only comparable rivals count")
        self.assertEqual([(r["name"], r["rival_owners"]) for r in result["league"]["missing"]], [("Delta", 2), ("Gamma", 1)])
        self.assertEqual(result["league"]["rivals_compared"], 2)
        last = next(e for e in result["events"] if e["label"] == "last gameweek")
        self.assertEqual((last["most_captained"], last["top_scorer"], last["chip_plays"][0]["played"]), ("Delta", "Alpha", 900))
        self.assertIn("not what will score", result["method"])

    def test_note_is_plain_language(self):
        row = crowd.build(snapshot(), catalog())["squad"][2]
        self.assertEqual(crowd.note(row), "12% own · −89,800 net transfers this GW · price −£0.1m this GW · 1 league rival own")


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def to_dict(self):
        return self.data


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self.responses.pop(0))


ANSWER = {"model": "claude-opus-5", "stop_reason": "end_turn", "content": [
    {"type": "server_tool_use", "name": "web_search"},
    {"type": "web_search_tool_result", "content": [{"url": "https://news.example/a", "title": "A"}, {"url": "javascript:alert(1)", "title": "bad"}]},
    {"type": "text", "text": "Verdict: captain Groß.\n\n- Sunderland away is kind.", "citations": [
        {"url": "https://news.example/a", "title": "A report"}, {"url": "ftp://x.example/b", "title": "ftp"}]},
]}


class JevTests(unittest.TestCase):
    def test_request_shape_and_answer_extraction(self):
        client = FakeClient([ANSWER])
        result = jev_ask.ask("Who should I captain?", "context", client=client)
        call = client.calls[0]
        self.assertEqual(call["model"], "claude-opus-5")
        self.assertEqual(call["tools"], [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}])
        self.assertEqual((call["betas"], call["fallbacks"]), (["server-side-fallback-2026-07-01"], "default"))
        self.assertIn("untrusted", call["system"])
        self.assertIn("Dashboard context:\ncontext", call["messages"][0]["content"])
        self.assertIn("captain Groß", result["answer"])
        self.assertEqual(result["sources"], [{"url": "https://news.example/a", "title": "A report"}], "only cited http(s) sources")
        self.assertEqual(result["searches"], 1)

    def test_pause_turn_is_continued_then_capped(self):
        paused = {"stop_reason": "pause_turn", "content": [{"type": "server_tool_use", "name": "web_search"}]}
        client = FakeClient([paused, ANSWER])
        self.assertIn("Groß", jev_ask.ask("Captain?", "ctx", client=client)["answer"])
        self.assertEqual(client.calls[1]["messages"][1], {"role": "assistant", "content": paused["content"]})
        self.assertEqual(len(client.calls[1]["messages"]), 2, "no extra user turn when resuming")
        client = FakeClient([paused] * (jev_ask.MAX_CONTINUATIONS + 1))
        with self.assertRaises(jev_ask.JevError):
            jev_ask.ask("Captain?", "ctx", client=client)
        self.assertEqual(len(client.calls), jev_ask.MAX_CONTINUATIONS + 1)

    def test_unfinished_search_and_time_budget_raise_instead_of_partial_text(self):
        paused = {"stop_reason": "pause_turn", "content": [{"type": "text", "text": "partial preamble"}]}
        with self.assertRaisesRegex(jev_ask.JevError, "took too long"):
            jev_ask.ask("Captain?", "ctx", client=FakeClient([paused] * (jev_ask.MAX_CONTINUATIONS + 1)))
        clock = iter([0.0, 0.0, jev_ask.TOTAL_BUDGET_SECONDS + 1, jev_ask.TOTAL_BUDGET_SECONDS + 2])
        client = FakeClient([paused, ANSWER])
        with patch.object(jev_ask.time, "monotonic", lambda: next(clock)), self.assertRaisesRegex(jev_ask.JevError, "took too long"):
            jev_ask.ask("Captain?", "ctx", client=client)
        self.assertEqual(len(client.calls), 1, "no further calls once the time budget is spent")

    def test_client_limits_retries_and_timeout(self):
        client = jev_ask._client("test-key")
        self.assertEqual(client.max_retries, 1)
        self.assertEqual(float(client.timeout), jev_ask.CALL_TIMEOUT_SECONDS)

    def test_refusal_and_empty_answers_are_friendly(self):
        with self.assertRaisesRegex(jev_ask.JevError, "couldn't answer"):
            jev_ask.ask("Captain?", "ctx", client=FakeClient([{"stop_reason": "refusal", "content": []}]))
        with self.assertRaisesRegex(jev_ask.JevError, "didn't find"):
            jev_ask.ask("Captain?", "ctx", client=FakeClient([{"stop_reason": "end_turn", "content": []}]))

    def test_api_errors_map_to_safe_messages(self):
        import anthropic

        class Boom:
            def __init__(self, status):
                self.status = status
                self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

            def create(self, **kwargs):
                request = SimpleNamespace(method="POST", url="https://api.anthropic.com")
                raise anthropic.APIStatusError("secret-detail sk-ant-xyz", response=SimpleNamespace(status_code=self.status, headers={}, request=request), body=None)

        for status, text in ((401, "rejected"), (429, "busy"), (500, "couldn't reach")):
            try:
                jev_ask.ask("Captain?", "ctx", client=Boom(status))
            except jev_ask.JevError as error:
                self.assertIn(text, str(error))
                self.assertNotIn("sk-ant", str(error))
            else:
                self.fail("expected JevError")

    def test_question_validation_and_missing_key(self):
        for bad in (None, "", "hi", "x" * 501, 42):
            with self.assertRaises(jev_ask.JevError):
                jev_ask.validate_question(bad)
        self.assertEqual(jev_ask.validate_question("  who   to  captain? "), "who to captain?")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with self.assertRaisesRegex(jev_ask.JevError, "ANTHROPIC_API_KEY"):
                jev_ask.ask("Captain?", "ctx")

    def test_context_is_built_from_server_data(self):
        lineup = {"state": "ready", "gameweek": 6, "deadline_utc": "2026-10-10T10:00:00Z", "formation": "4-4-2", "xi_estimate_total": 70,
                  "lines": {"GK": [{"name": "Suzuki", "team": "AVL", "estimate": 4, "flags": []}], "DEF": [], "MID": [{"name": "Groß", "team": "BHA", "estimate": 11.2, "flags": ["doubtful: 75% chance"]}], "FWD": []},
                  "bench": [{"name": "João Pedro", "team": "CHE", "estimate": 4.1, "flags": [], "blockers": ["FPL lists injured"]}],
                  "captain": {"name": "Groß"}, "vice": {"name": "Haaland"}, "captain_options": [{"name": "Groß", "estimate": 11.2}]}
        plan = {"transfers": [{"out": {"name": "João Pedro"}, "in": {"name": "Kostoulas"}}], "hit_points": 0, "net_delta": 1.6}
        text = jev_ask.build_context(lineup, crowd.build(snapshot(), catalog()), plan)
        for fragment in ("GW6", "Groß (BHA, FPL est 11.2; doubtful: 75% chance)", "João Pedro (CHE, FPL est 4.1; FPL lists injured)",
                         "sell João Pedro → buy Kostoulas", "Most transferred in this GW: Delta (T3)"):
            self.assertIn(fragment, text)
        self.assertIn("unavailable", jev_ask.build_context({"state": "unavailable", "reason": "stale"}))


if __name__ == "__main__":
    unittest.main()
