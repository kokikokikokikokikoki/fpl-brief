"""Deterministic, offline-testable Research Scout collector."""

import html.parser
import ipaddress
import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .config import load
from .research import _valid_url, evidence_status, load_packet, normalize_packet, validate_packet
from .storage import read_json, write_atomic
from .workflow import update

USER_AGENT = "FPL-Brief-Research-Scout/1.0"
TIMEOUT_SECONDS = 10
MAX_BODY_BYTES = 512 * 1024
FPL_BOOTSTRAP_MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_EXCERPTS = 32
TRANSIENT_CODES = {429, 500, 502, 503, 504}
OFFICIAL_SOURCE_POLICY = {
    "official-fpl-news": {"publisher": "Fantasy Premier League", "host": "fantasy.premierleague.com", "url": "https://fantasy.premierleague.com/api/bootstrap-static/"},
    "official-arsenal-news": {"publisher": "Arsenal Football Club", "host": "www.arsenal.com", "url": "https://www.arsenal.com/news/all/1"},
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(request.full_url, code, "redirect not followed", headers, fp)


class MetadataParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.description = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "meta" and attrs.get("name", "").lower() in {"description", "og:description"}:
            self.description.append(attrs.get("content", ""))

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title.append(data)


def source_config(config):
    sources = config.get("research_sources", [])
    if not isinstance(sources, list):
        return []
    return sources


def allowlisted_url(source, url=None):
    if not isinstance(source, dict):
        return False
    target = url or source.get("url")
    parsed = urlparse(target) if isinstance(target, str) else None
    host = source.get("host")
    return bool(parsed and parsed.scheme == "https" and parsed.netloc == host and not parsed.username and not parsed.password and isinstance(host, str) and host and target == source.get("url"))


def validate_source_config(source, allowlist=None):
    if not isinstance(source, dict):
        return "invalid_source_config"
    for key in ("id", "publisher", "host", "url"):
        if not isinstance(source.get(key), str) or not source[key].strip():
            return "invalid_source_config"
    parsed = urlparse(source["url"])
    hostname = parsed.hostname
    try:
        private_host = hostname in {"localhost", "localhost.localdomain"} or ipaddress.ip_address(hostname).is_private or ipaddress.ip_address(hostname).is_loopback or ipaddress.ip_address(hostname).is_link_local
    except ValueError:
        private_host = hostname in {"localhost", "localhost.localdomain"}
    if parsed.scheme != "https" or private_host or parsed.username or parsed.password:
        return "source_url_not_allowed"
    policy = OFFICIAL_SOURCE_POLICY.get(source["id"])
    if not policy or any(source.get(key) != policy[key] for key in ("publisher", "host", "url")):
        return "source_url_not_allowlisted"
    if allowlist is not None and not any(isinstance(item, dict) and item.get("id") == source["id"] and item.get("url") == source["url"] for item in allowlist):
        return "source_url_not_allowlisted"
    return None

def bounded_text(value):
    return str(value).strip()[:4096] if value is not None else ""


def is_exact_fpl_bootstrap(source):
    policy = OFFICIAL_SOURCE_POLICY["official-fpl-news"]
    return isinstance(source, dict) and source.get("id") == "official-fpl-news" and all(source.get(key) == policy[key] for key in ("publisher", "host", "url"))


def body_limit(source):
    return FPL_BOOTSTRAP_MAX_BODY_BYTES if is_exact_fpl_bootstrap(source) else MAX_BODY_BYTES


def _extract_metadata(body, content_type, captured_at, source=None, priority_player_ids=None):
    if "json" in content_type:
        payload = json.loads(body.decode("utf-8"))
        if is_exact_fpl_bootstrap(source):
            priority_player_ids = priority_player_ids or set()
            elements = payload.get("elements", []) if isinstance(payload, dict) else []
            teams = payload.get("teams", []) if isinstance(payload, dict) else []
            team_names = {team.get("id"): team.get("name") for team in teams if isinstance(team, dict) and isinstance(team.get("id"), int) and not isinstance(team.get("id"), bool) and team.get("id") > 0 and isinstance(team.get("name"), str) and team.get("name").strip()} if isinstance(teams, list) else {}
            entries = []
            for index, element in enumerate(elements if isinstance(elements, list) else []):
                news = element.get("news") if isinstance(element, dict) else None
                if isinstance(news, str) and news.strip():
                    player_id = element.get("id")
                    if isinstance(player_id, bool) or not isinstance(player_id, int) or player_id < 1:
                        player_id = None
                    player_name = element.get("web_name")
                    if not isinstance(player_name, str) or not player_name.strip():
                        player_name = None
                    team_id = element.get("team")
                    if isinstance(team_id, bool) or not isinstance(team_id, int) or team_id < 1:
                        team_id = None
                    excerpt = {"kind": "player_news", "text": news[:4096], "captured_at_utc": captured_at,
                               "player_id": player_id, "player_name": player_name,
                               "team_id": team_id, "team_name": team_names.get(team_id)}
                    entries.append((player_id not in priority_player_ids, index, excerpt))
            entries.sort(key=lambda entry: (entry[0], entry[1]))
            omitted = max(0, len(entries) - MAX_EXCERPTS)
            return "Official FPL player news", [entry[2] for entry in entries[:MAX_EXCERPTS]], omitted
        excerpts = []
        for key in ("title", "description", "summary"):
            if isinstance(payload, dict) and isinstance(payload.get(key), str) and payload[key].strip():
                excerpts.append({"kind": "json_field", "text": bounded_text(payload[key]), "captured_at_utc": captured_at})
        title = next((entry["text"] for entry in excerpts if entry["text"]), None)
        return title, excerpts, 0
    parser = MetadataParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    excerpts = []
    title = bounded_text(" ".join(parser.title)) or None
    if title:
        excerpts.append({"kind": "title", "text": title, "captured_at_utc": captured_at})
    description = bounded_text(" ".join(parser.description))
    if description:
        excerpts.append({"kind": "description", "text": description, "captured_at_utc": captured_at})
    return title, excerpts, 0


def extract_metadata(body, content_type, captured_at, source=None):
    """Return bounded, verbatim source metadata (without collector bookkeeping)."""
    title, excerpts, _ = _extract_metadata(body, content_type, captured_at, source)
    return title, excerpts


def fetch_source(source, opener=None, sleeper=None, now=None, priority_player_ids=None):
    """Fetch one configured source; return (state, metadata, code)."""
    error_code = None
    opener = opener or urllib.request.build_opener(NoRedirect())
    for attempt in range(2):
        try:
            request = urllib.request.Request(source["url"], headers={"User-Agent": USER_AGENT, "Accept": "text/html, application/json"})
            response = opener.open(request, timeout=TIMEOUT_SECONDS)
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/json"}:
                return "rejected", None, "unsupported_content_type"
            cap = body_limit(source)
            body = response.read(cap + 1)
            if len(body) > cap:
                return "rejected", None, "response_too_large"
            captured_at = now or utc_now()
            title, excerpts, omitted = _extract_metadata(body, content_type, captured_at, source, priority_player_ids)
            return "captured", {"title": title, "excerpts": excerpts, "omitted_excerpts": omitted, "retrieved_at_utc": captured_at}, None
        except urllib.error.HTTPError as error:
            if 300 <= error.code < 400:
                return "unavailable", None, "redirect_not_followed"
            if error.code in TRANSIENT_CODES and attempt == 0:
                if sleeper:
                    sleeper()
                continue
            return ("rejected" if error.code in {400, 401, 403, 404} else "unavailable"), None, f"http_{error.code}"
        except (TimeoutError, socket.timeout, urllib.error.URLError):
            if attempt == 0:
                if sleeper:
                    sleeper()
                continue
            return "unavailable", None, "request_failed"
        except (UnicodeError, json.JSONDecodeError):
            return "rejected", None, "malformed_response"
    return "unavailable", None, error_code or "request_failed"


def _safe_record_url(url):
    parsed = urlparse(url) if isinstance(url, str) else None
    if parsed and (parsed.username or parsed.password) and parsed.hostname:
        url = urlunparse((parsed.scheme, parsed.hostname, parsed.path, parsed.params, parsed.query, parsed.fragment))
    return url if _valid_url(url) else None


def _base_source(source):
    source = source if isinstance(source, dict) else {}
    return {"id": source.get("id", "unknown-source"), "publisher": source.get("publisher", "Unknown publisher"), "url": _safe_record_url(source.get("url")), "title": None,
            "retrieved_at_utc": None, "last_success_at_utc": None, "collection_state": "unavailable",
            "verification_status": "unverified", "excerpts": [], "claims": [], "omitted_excerpts": 0}


def collect(config=None, packet=None, opener=None, sleeper=None, now=None, priority_player_ids=None):
    config = config or load()
    priority_player_ids = set(priority_player_ids or [])
    priority_player_ids.update(player_id for player_id in config.get("watchlist_player_ids", []) if isinstance(player_id, int) and not isinstance(player_id, bool) and player_id > 0)
    packet = normalize_packet(packet if packet is not None else load_packet(), now)
    if not isinstance(packet, dict) or packet.get("schema_version") != 2:
        packet = {"schema_version": 2, "generated_at_utc": now or utc_now(), "collector": {"version": "v1", "last_run_at_utc": now or utc_now()}, "sources": [], "warnings": []}
    old_by_id = {source.get("id"): source for source in packet.get("sources", []) if isinstance(source, dict)}
    results = []
    run_time = now or utc_now()
    for configured in source_config(config):
        reason = validate_source_config(configured, source_config(config))
        configured = configured if isinstance(configured, dict) else {}
        prior = old_by_id.get(configured.get("id"))
        source = dict(prior) if isinstance(prior, dict) else _base_source(configured)
        source.update({"id": configured.get("id", source["id"]), "publisher": configured.get("publisher", source["publisher"]), "url": _safe_record_url(configured.get("url"))})
        if reason:
            source.update({"collection_state": "rejected", "attempted_at_utc": run_time, "error": {"code": reason, "message": "Configured source was rejected."}})
        else:
            state, metadata, code = fetch_source(configured, opener, sleeper, now, priority_player_ids)
            if state == "captured":
                source.update(metadata)
                source["last_success_at_utc"] = metadata["retrieved_at_utc"]
                source["attempted_at_utc"] = run_time
                source["collection_state"] = "captured"
                source.pop("error", None)
            else:
                source["collection_state"] = state
                source["attempted_at_utc"] = run_time
                source["error"] = {"code": code, "message": "Source was not captured; previous successful evidence was retained."}
        results.append(source)
    packet["schema_version"] = 2
    packet["generated_at_utc"] = run_time
    packet["collector"] = {"version": "v1", "last_run_at_utc": run_time}
    packet["sources"] = results
    packet.setdefault("warnings", [])
    packet["warnings"] = [warning for warning in packet["warnings"] if isinstance(warning, str)]
    validate_packet(packet)
    return packet


def run(config=None, path="data/research_packet.json", opener=None, sleeper=None, now=None, priority_player_ids=None):
    config = config or load()
    if priority_player_ids is None:
        snapshot = read_json(Path(path).with_name("latest.json"), default={})
        picks = snapshot.get("squad_snapshot", {}).get("picks", []) if isinstance(snapshot, dict) else []
        priority_player_ids = {pick.get("element") for pick in picks if isinstance(pick, dict) and isinstance(pick.get("element"), int) and not isinstance(pick.get("element"), bool) and pick["element"] > 0}
    previous = load_packet(path)
    try:
        packet = collect(config, previous, opener, sleeper, now, priority_player_ids)
    except ValueError:
        packet = {"schema_version": 2, "generated_at_utc": now or utc_now(), "collector": {"version": "v1", "last_run_at_utc": now or utc_now()}, "sources": [], "warnings": ["Existing packet was malformed and could not be migrated safely."]}
    write_atomic(path, packet)
    result = evidence_status(packet, config.get("research_stale_after_hours", 24), now)
    update("research", {"state": result["state"], "valid": result["valid"], "stale": result["stale"], "sources": result["sources"], "facts": result["facts"], "captured": result["captured"], "unavailable": result["unavailable"], "rejected": result["rejected"], "warnings": result["warnings"]})
    return packet, result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Collect allowlisted public Research Desk evidence.")
    parser.add_argument("--packet", default="data/research_packet.json")
    args = parser.parse_args()
    packet, result = run(path=args.packet)
    print(json.dumps({"state": result["state"], "captured": result["captured"], "unavailable": result["unavailable"], "rejected": result["rejected"]}))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
