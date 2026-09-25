import io
import json
import tempfile
import unittest
import urllib.error
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fpl_brief.research import evidence_status, migrate_packet, validate_packet
from fpl_brief.research_scout import FPL_BOOTSTRAP_MAX_BODY_BYTES, MAX_BODY_BYTES, MAX_EXCERPTS, NoRedirect, collect, extract_metadata, fetch_source, validate_source_config


NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc).isoformat()


class FakeHeaders(dict):
    def get_content_type(self):
        return self.get("Content-Type", "").split(";", 1)[0].strip().lower()


class FakeResponse:
    def __init__(self, body=b"<title>Official update</title><meta name='description' content='Verbatim text'>", content_type="text/html"):
        self.body = body
        self.headers = FakeHeaders({"Content-Type": content_type})
    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]
    def close(self):
        pass


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.urls = []
    def open(self, request, timeout):
        self.calls += 1
        self.urls.append(request.full_url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def source_config():
    return {"id": "official-fpl-news", "publisher": "Fantasy Premier League", "host": "fantasy.premierleague.com", "url": "https://fantasy.premierleague.com/api/bootstrap-static/"}


class ScoutTests(unittest.TestCase):
    def test_allowlist_rejects_social_credentials_and_private_hosts(self):
        self.assertIsNone(validate_source_config(source_config()))
        social = dict(source_config(), host="social.example", url="https://social.example/post")
        self.assertEqual(validate_source_config(social), "source_url_not_allowlisted")
        credentials = dict(source_config(), url="https://user:pass@www.premierleague.com/en/news")
        self.assertEqual(validate_source_config(credentials), "source_url_not_allowed")
        private = dict(source_config(), host="127.0.0.1", url="https://127.0.0.1/news")
        self.assertEqual(validate_source_config(private), "source_url_not_allowed")

    def test_canonical_arsenal_policy_rejects_old_redirecting_url(self):
        canonical = {"id": "official-arsenal-news", "publisher": "Arsenal Football Club", "host": "www.arsenal.com", "url": "https://www.arsenal.com/news/all/1"}
        self.assertIsNone(validate_source_config(canonical))
        self.assertEqual(validate_source_config(dict(canonical, url="https://www.arsenal.com/news")), "source_url_not_allowlisted")

    def test_only_exact_fpl_source_gets_two_megabyte_cap(self):
        non_fpl_body = b"{" + b"x" * (MAX_BODY_BYTES + 1) + b"}"
        state, _, code = fetch_source({"id": "official-arsenal-news", "publisher": "Arsenal Football Club", "host": "www.arsenal.com", "url": "https://www.arsenal.com/news/all/1"}, opener=FakeOpener([FakeResponse(non_fpl_body, "text/html")]), now=NOW)
        self.assertEqual((state, code), ("rejected", "response_too_large"))
        valid_padding = json.dumps({"elements": [], "padding": "x" * (MAX_BODY_BYTES + 100)}).encode()
        state, _, code = fetch_source(source_config(), opener=FakeOpener([FakeResponse(valid_padding, "application/json")]), now=NOW)
        self.assertEqual((state, code), ("captured", None))
        over = FakeResponse(b"x" * (FPL_BOOTSTRAP_MAX_BODY_BYTES + 1), "application/json")
        self.assertEqual(fetch_source(source_config(), opener=FakeOpener([over]), now=NOW)[2], "response_too_large")
        for near in (
            dict(source_config(), id="not-official-fpl"),
            dict(source_config(), host="fantasy.premierleague.com.evil"),
            dict(source_config(), url=source_config()["url"] + "?near=true"),
        ):
            result = fetch_source(near, opener=FakeOpener([FakeResponse(non_fpl_body, "text/html")]), now=NOW)
            self.assertEqual(result[2], "response_too_large")

    def test_exact_fpl_bootstrap_captures_only_verbatim_news_excerpts(self):
        payload = {"elements": [{"id": 11, "web_name": "Player Identity", "team": 3, "news": "Exact injury wording."}, {"id": 12, "news": "  Another exact note.  "}, {"id": 13, "news": ""}], "teams": [{"id": 3, "name": "Example Club"}]}
        packet = collect({"research_sources": [source_config()]}, None, FakeOpener([FakeResponse(json.dumps(payload).encode(), "application/json")]), now=NOW)
        source = packet["sources"][0]
        self.assertEqual([item["text"] for item in source["excerpts"]], ["Exact injury wording.", "  Another exact note.  "])
        self.assertTrue(all(item["kind"] == "player_news" and item["captured_at_utc"] == NOW for item in source["excerpts"]))
        self.assertEqual(source["excerpts"][0]["player_name"], "Player Identity")
        self.assertEqual(source["excerpts"][0]["team_name"], "Example Club")
        self.assertEqual(source["title"], "Official FPL player news")
        self.assertEqual(source["claims"], [])
        serialized = json.dumps(source)
        self.assertIn("Player Identity", serialized)
        self.assertNotIn("web_name", serialized)
    def test_bootstrap_news_overflow_is_capped_at_schema_limit(self):
        payload = {"elements": [{"id": index, "web_name": "Identity %s" % index, "news": "News %s" % index} for index in range(MAX_EXCERPTS + 1)]}
        packet = collect({"research_sources": [source_config()]}, None, FakeOpener([FakeResponse(json.dumps(payload).encode(), "application/json")]), now=NOW)
        source = packet["sources"][0]
        self.assertEqual(len(source["excerpts"]), MAX_EXCERPTS)
        self.assertEqual(source["excerpts"][0]["text"], "News 0")
        self.assertEqual(source["excerpts"][-1]["text"], "News 31")
        self.assertEqual(source["claims"], [])
        self.assertEqual(source["omitted_excerpts"], 1)
        serialized = json.dumps(source)
        self.assertIn("Identity ", serialized)
        self.assertNotIn("web_name", serialized)

    def test_fpl_news_joins_stable_player_and_team_identity(self):
        payload = {"elements": [{"id": 42, "web_name": "Known Player", "team": 7, "news": "Exact player news."}], "teams": [{"id": 7, "name": "Known Club"}]}
        packet = collect({"research_sources": [source_config()]}, None, FakeOpener([FakeResponse(json.dumps(payload).encode(), "application/json")]), now=NOW)
        source = packet["sources"][0]
        self.assertEqual(source["title"], "Official FPL player news")
        self.assertEqual(source["excerpts"][0]["kind"], "player_news")
        self.assertEqual(source["excerpts"][0]["player_id"], 42)
        self.assertEqual(source["excerpts"][0]["player_name"], "Known Player")
        self.assertEqual(source["excerpts"][0]["team_name"], "Known Club")

    def test_fpl_news_prioritizes_squad_items_before_cap_and_reports_omissions(self):
        elements = [{"id": index, "web_name": "Player %s" % index, "team": 1, "news": "News %s" % index} for index in range(1, MAX_EXCERPTS + 3)]
        payload = {"elements": elements, "teams": [{"id": 1, "name": "Club"}]}
        packet = collect({"research_sources": [source_config()]}, None, FakeOpener([FakeResponse(json.dumps(payload).encode(), "application/json")]), now=NOW, priority_player_ids={MAX_EXCERPTS + 2})
        source = packet["sources"][0]
        self.assertEqual(len(source["excerpts"]), MAX_EXCERPTS)
        self.assertEqual(source["excerpts"][0]["player_id"], MAX_EXCERPTS + 2)
        self.assertEqual(source["omitted_excerpts"], 2)

    def test_fpl_news_without_reliable_identity_remains_unlinked(self):
        payload = {"elements": [{"id": 42, "news": "Exact but unlinked news."}], "teams": []}
        packet = collect({"research_sources": [source_config()]}, None, FakeOpener([FakeResponse(json.dumps(payload).encode(), "application/json")]), now=NOW)
        excerpt = packet["sources"][0]["excerpts"][0]
        self.assertEqual(excerpt["player_id"], 42)
        self.assertIsNone(excerpt["player_name"])
        self.assertIsNone(excerpt["team_name"])

    def test_successful_recollection_updates_last_attempt_timestamp(self):
        old_attempt = (datetime.fromisoformat(NOW) - timedelta(hours=1)).isoformat()
        prior = {
            "schema_version": 2, "generated_at_utc": old_attempt,
            "collector": {"version": "v1", "last_run_at_utc": old_attempt},
            "sources": [{
                "id": "official-fpl-news", "publisher": "Fantasy Premier League",
                "url": source_config()["url"], "title": None, "retrieved_at_utc": None,
                "last_success_at_utc": None, "collection_state": "unavailable",
                "verification_status": "unverified", "excerpts": [], "claims": [],
                "attempted_at_utc": old_attempt,
                "error": {"code": "request_failed", "message": "Source was not captured."},
            }], "warnings": [],
        }
        body = json.dumps({"elements": [], "teams": []}).encode()
        result = collect({"research_sources": [source_config()]}, prior,
                         FakeOpener([FakeResponse(body, "application/json")]), now=NOW)
        self.assertEqual(result["sources"][0]["collection_state"], "captured")
        self.assertEqual(result["sources"][0]["attempted_at_utc"], NOW)

    def test_fetch_extracts_only_bounded_verbatim_metadata(self):
        title, excerpts = extract_metadata(b"<title>  News </title><meta name='description' content='Exact source text'>", "text/html", NOW)
        self.assertEqual(title, "News")
        self.assertEqual([item["text"] for item in excerpts], ["News", "Exact source text"])
        self.assertTrue(all(len(item["text"]) <= 4096 for item in excerpts))

    def test_fetch_retries_timeout_once_and_rejects_unsupported_without_retry(self):
        opener = FakeOpener([TimeoutError(), FakeResponse()])
        state, metadata, code = fetch_source(source_config(), opener=opener, now=NOW)
        self.assertEqual(state, "captured")
        self.assertEqual(opener.calls, 2)
        opener = FakeOpener([FakeResponse(content_type="text/plain"), FakeResponse()])
        state, _, code = fetch_source(source_config(), opener=opener, now=NOW)
        self.assertEqual((state, code, opener.calls), ("rejected", "unsupported_content_type", 1))

    def test_redirect_handler_matches_full_urllib_callback_contract(self):
        handler = NoRedirect()
        request = urllib.request.Request(source_config()["url"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            with self.assertRaises(urllib.error.HTTPError) as context:
                handler.redirect_request(request, FakeResponse(), 302, "Found", {}, "https://redirect.example/target")
        self.assertEqual(context.exception.code, 302)
        self.assertIn("redirect not followed", str(context.exception))
        context.exception.close()

    def test_redirect_result_preserves_source_and_continues_to_next_source(self):
        first = source_config()
        second = {"id": "official-arsenal-news", "publisher": "Arsenal Football Club", "host": "www.arsenal.com", "url": "https://www.arsenal.com/news/all/1"}
        redirect = urllib.error.HTTPError(first["url"], 302, "Found", {}, None)
        opener = FakeOpener([redirect, FakeResponse()])
        packet = collect({"research_sources": [first, second]}, None, opener, now=NOW)
        self.assertEqual(packet["sources"][0]["collection_state"], "unavailable")
        self.assertEqual(packet["sources"][0]["url"], first["url"])
        self.assertEqual(packet["sources"][0]["error"]["code"], "redirect_not_followed")
        self.assertEqual(packet["sources"][1]["collection_state"], "captured")
        self.assertEqual(opener.urls, [first["url"], second["url"]])
    def test_fetch_handles_redirect_http_error_and_size_without_retry(self):
        redirect = urllib.error.HTTPError(source_config()["url"], 302, "redirect", {}, None)
        opener = FakeOpener([redirect])
        self.assertEqual(fetch_source(source_config(), opener=opener, now=NOW)[0], "unavailable")
        self.assertEqual(opener.calls, 1)
        too_large = FakeResponse(b"x" * (MAX_BODY_BYTES + 1))
        opener = FakeOpener([too_large])
        non_fpl = {"id": "official-arsenal-news", "publisher": "Arsenal Football Club", "host": "www.arsenal.com", "url": "https://www.arsenal.com/news/all/1"}
        self.assertEqual(fetch_source(non_fpl, opener=opener, now=NOW)[2], "response_too_large")
        self.assertEqual(opener.calls, 1)

    def test_collect_preserves_last_successful_excerpts_on_failure(self):
        prior = collect({"research_sources": [source_config()]}, {"schema_version": 2, "generated_at_utc": NOW, "collector": {"version": "v1", "last_run_at_utc": NOW}, "sources": [], "warnings": []}, FakeOpener([FakeResponse()]), now=NOW)
        later = collect({"research_sources": [source_config()]}, prior, FakeOpener([TimeoutError(), TimeoutError()]), now=(datetime.fromisoformat(NOW) + timedelta(hours=1)).isoformat())
        source = later["sources"][0]
        self.assertEqual(source["collection_state"], "unavailable")
        self.assertEqual(source["last_success_at_utc"], NOW)
        self.assertTrue(source["excerpts"])
        self.assertEqual(source["error"]["code"], "request_failed")

    def test_malformed_v2_is_safe_and_stale_empty_is_explicit(self):
        invalid = evidence_status({"schema_version": 2}, 24)
        self.assertFalse(invalid["valid"])
        packet = {"schema_version": 2, "generated_at_utc": NOW, "collector": {"version": "v1", "last_run_at_utc": NOW}, "sources": [{"id": "x", "publisher": "X", "url": "https://x.example", "title": None, "retrieved_at_utc": None, "last_success_at_utc": None, "collection_state": "unavailable", "verification_status": "unverified", "excerpts": [], "claims": []}], "warnings": []}
        result = evidence_status(packet, 24, datetime.fromisoformat(NOW))
        self.assertTrue(result["stale"])
        self.assertEqual(result["unavailable"], 1)



    def test_fixed_policy_rejects_configured_social_and_continues(self):
        social = {"id": "social-source", "publisher": "Social", "host": "x.com", "url": "https://x.com/news"}
        packet = collect({"research_sources": [social, source_config()]}, None, FakeOpener([FakeResponse()]), now=NOW)
        self.assertEqual(packet["sources"][0]["collection_state"], "rejected")
        self.assertEqual(packet["sources"][1]["collection_state"], "captured")

    def test_malformed_source_record_does_not_abort_following_source(self):
        packet = collect({"research_sources": [{"id": "broken", "publisher": "Broken"}, source_config()]}, None, FakeOpener([FakeResponse()]), now=NOW)
        self.assertEqual(packet["sources"][0]["error"]["code"], "invalid_source_config")
        self.assertEqual(packet["sources"][1]["collection_state"], "captured")

    def test_rejected_unsafe_url_is_not_persisted_or_rendered_as_anchor(self):
        unsafe = dict(source_config(), id="unsafe", url="javascript:alert(1)", host="javascript")
        packet = collect({"research_sources": [unsafe]}, None, FakeOpener([]), now=NOW)
        self.assertIsNone(packet["sources"][0]["url"])
        self.assertTrue(evidence_status(packet)["valid"])
        desk = Path("dashboard/desk-tools.ts").read_text(encoding="utf-8")
        self.assertIn('sourceState !== "rejected"', desk)
        self.assertIn("/^https:", desk)

    def test_reviewed_claim_requires_text_reviewer_and_times(self):
        packet = migrate_packet({"schema_version": 1, "sources": [{"title": "Club", "url": "https://club.example/news", "retrieved_at_utc": NOW, "verified": True, "facts": [{"label": "confirmed", "claim": "Text"}]}]}, NOW)
        for field in ("claim", "reviewer", "retrieved_at_utc", "reviewed_at_utc"):
            candidate = json.loads(json.dumps(packet))
            candidate["sources"][0]["claims"][0].pop(field, None)
            with self.assertRaises(ValueError):
                validate_packet(candidate)

    def test_api_summary_has_safe_source_state_shape(self):
        packet = collect({"research_sources": [dict(source_config(), id="unsafe", url="javascript:alert(1)", host="javascript")]}, None, FakeOpener([]), now=NOW)
        result = evidence_status(packet, 24, datetime.fromisoformat(NOW))
        self.assertIn("source_summaries", result)
        self.assertEqual(result["source_summaries"][0]["state"], "rejected")
        self.assertIsNone(result["packet"]["sources"][0]["url"])


class MigrationTests(unittest.TestCase):
    def test_v1_migration_preserves_attribution_and_fact(self):
        legacy = {"schema_version": 1, "sources": [{"title": "Club statement", "url": "https://club.example/news", "retrieved_at_utc": NOW, "verified": True, "facts": [{"label": "confirmed", "claim": "Player trained."}]}]}
        migrated = migrate_packet(legacy, NOW)
        validate_packet(migrated)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["sources"][0]["url"], legacy["sources"][0]["url"])
        self.assertEqual(migrated["sources"][0]["claims"][0]["claim"], "Player trained.")
        self.assertEqual(evidence_status(legacy, 24, datetime.fromisoformat(NOW))["valid"], True)



    def test_v1_http_source_migrates_as_historical_non_linkable_evidence(self):
        legacy = {"schema_version": 1, "sources": [{"title": "Legacy page", "url": "http://example.com/news", "retrieved_at_utc": NOW, "verified": True, "facts": [{"label": "confirmed", "claim": "Historical excerpt."}]}]}
        migrated = migrate_packet(legacy, NOW)
        validate_packet(migrated)
        self.assertEqual(migrated["sources"][0]["url"], "http://example.com/news")
        self.assertTrue(migrated["sources"][0]["legacy_migrated"])
        self.assertTrue(evidence_status(legacy, 24, datetime.fromisoformat(NOW))["valid"])
if __name__ == "__main__":
    unittest.main()
