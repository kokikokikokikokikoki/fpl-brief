"""Validation, migration, and freshness summaries for Research Desk evidence."""

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .storage import read_json

FACT_LABELS = {"confirmed", "reported", "prediction", "unresolved"}
COLLECTION_STATES = {"captured", "unavailable", "rejected"}
VERIFICATION_STATES = {"unverified", "reviewed"}
EXCERPT_KINDS = {"title", "description", "json_field"}


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def _valid_url(url):
    parsed = urlparse(url) if isinstance(url, str) else None
    return bool(parsed and parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password)


def migrate_packet(packet, migrated_at=None):
    """Deterministically convert a valid legacy v1 packet to v2."""
    if not isinstance(packet, dict) or packet.get("schema_version") != 1:
        raise ValueError("research packet must use schema_version 1 for migration")
    sources = packet.get("sources")
    if not isinstance(sources, list):
        raise ValueError("research packet sources must be a list")
    migrated_at = migrated_at or now_utc()
    result = {
        "schema_version": 2,
        "generated_at_utc": migrated_at,
        "collector": {"version": "v1", "last_run_at_utc": migrated_at},
        "sources": [],
        "warnings": ["Migrated from research packet schema version 1; legacy facts require human review context."],
    }
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"source {index} must be an object")
        title = source.get("title")
        url = source.get("url")
        retrieved = source.get("retrieved_at_utc")
        verified = source.get("verified")
        facts = source.get("facts")
        parsed_url = urlparse(url) if isinstance(url, str) else None
        legacy_url_valid = bool(parsed_url and parsed_url.scheme in {"http", "https"} and parsed_url.netloc and not parsed_url.username and not parsed_url.password)
        if not isinstance(title, str) or not title.strip() or not legacy_url_valid or not parse_time(retrieved) or not isinstance(verified, bool) or not isinstance(facts, list):
            raise ValueError(f"source {index} is malformed")
        excerpts = []
        claims = []
        for fact_index, fact in enumerate(facts):
            if not isinstance(fact, dict) or not isinstance(fact.get("claim"), str) or not fact["claim"].strip() or fact.get("label") not in FACT_LABELS:
                raise ValueError(f"source {index} has a malformed fact")
            excerpts.append({"kind": "description", "text": fact["claim"][:4096], "captured_at_utc": retrieved})
            claims.append({
                "source_id": f"legacy-source-{index}",
                "excerpt_ref": fact_index,
                "label": fact["label"],
                "verification_status": "reviewed" if verified else "unverified",
                "claim": fact["claim"][:4096],
                "reviewer": "legacy packet" if verified else "not reviewed",
                "retrieved_at_utc": retrieved,
                "reviewed_at_utc": retrieved if verified else None,
            })
        result["sources"].append({
            "id": f"legacy-source-{index}",
            "publisher": source.get("publisher") or title,
            "url": url,
            "legacy_migrated": True,
            "title": title,
            "retrieved_at_utc": retrieved,
            "last_success_at_utc": retrieved,
            "collection_state": "captured",
            "verification_status": "reviewed" if verified else "unverified",
            "excerpts": excerpts,
            "claims": claims,
        })
    return result


def validate_packet(packet):
    """Raise ValueError unless a research packet is a valid v2 record."""
    if isinstance(packet, dict) and packet.get("schema_version") == 1:
        sources = packet.get("sources")
        if not isinstance(sources, list):
            raise ValueError("research packet sources must be a list")
        for index, source in enumerate(sources, start=1):
            url = source.get("url") if isinstance(source, dict) else None
            parsed = urlparse(url) if isinstance(url, str) else None
            if not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"source {index} needs an http(s) URL")
        raise ValueError("research packet schema version 1 requires migration")
    if not isinstance(packet, dict) or packet.get("schema_version") != 2:
        raise ValueError("research packet must use schema_version 2")
    if not parse_time(packet.get("generated_at_utc")):
        raise ValueError("research packet needs generated_at_utc")
    collector = packet.get("collector")
    if not isinstance(collector, dict) or not isinstance(collector.get("version"), str) or not parse_time(collector.get("last_run_at_utc")):
        raise ValueError("research packet collector metadata is invalid")
    sources = packet.get("sources")
    if not isinstance(sources, list):
        raise ValueError("research packet sources must be a list")
    if not isinstance(packet.get("warnings"), list) or any(not isinstance(warning, str) for warning in packet["warnings"]):
        raise ValueError("research packet warnings must be a list of strings")
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"source {index} must be an object")
        required = ("id", "publisher", "url", "title", "retrieved_at_utc", "last_success_at_utc", "collection_state", "verification_status", "excerpts", "claims")
        if any(key not in source for key in required):
            raise ValueError(f"source {index} is missing required fields")
        if not isinstance(source["id"], str) or not source["id"].strip() or not isinstance(source["publisher"], str) or not source["publisher"].strip():
            raise ValueError(f"source {index} attribution is invalid")
        if source.get("legacy_migrated"):
            parsed_legacy = urlparse(source["url"]) if isinstance(source["url"], str) else None
            if not parsed_legacy or parsed_legacy.scheme not in {"http", "https"} or not parsed_legacy.netloc or parsed_legacy.username or parsed_legacy.password:
                raise ValueError(f"source {index} legacy URL is unsafe")
        elif source["collection_state"] == "rejected":
            if source["url"] is not None and not _valid_url(source["url"]):
                raise ValueError(f"source {index} rejected URL is unsafe")
        elif not _valid_url(source["url"]):
            raise ValueError(f"source {index} needs an HTTPS URL without credentials")
        if source["title"] is not None and not isinstance(source["title"], str):
            raise ValueError(f"source {index} title is invalid")
        if source["retrieved_at_utc"] is not None and not parse_time(source["retrieved_at_utc"]):
            raise ValueError(f"source {index} retrieved_at_utc is invalid")
        if source["last_success_at_utc"] is not None and not parse_time(source["last_success_at_utc"]):
            raise ValueError(f"source {index} last_success_at_utc is invalid")
        if source["collection_state"] not in COLLECTION_STATES or source["verification_status"] not in VERIFICATION_STATES:
            raise ValueError(f"source {index} state is invalid")
        if not isinstance(source["excerpts"], list) or len(source["excerpts"]) > 32:
            raise ValueError(f"source {index} excerpts are invalid")
        for excerpt in source["excerpts"]:
            if not isinstance(excerpt, dict) or excerpt.get("kind") not in EXCERPT_KINDS or not isinstance(excerpt.get("text"), str) or len(excerpt["text"]) > 4096 or not parse_time(excerpt.get("captured_at_utc")):
                raise ValueError(f"source {index} has an invalid excerpt")
        if not isinstance(source["claims"], list):
            raise ValueError(f"source {index} claims are invalid")
        for claim in source["claims"]:
            if (not isinstance(claim, dict) or claim.get("source_id") != source["id"] or not isinstance(claim.get("excerpt_ref"), int) or claim["excerpt_ref"] < 0 or claim["excerpt_ref"] >= len(source["excerpts"]) or claim.get("label") not in FACT_LABELS or claim.get("verification_status") not in VERIFICATION_STATES or not isinstance(claim.get("claim"), str) or not claim["claim"].strip() or not isinstance(claim.get("reviewer"), str) or not claim["reviewer"].strip() or not parse_time(claim.get("retrieved_at_utc")) or (claim["verification_status"] == "reviewed" and not parse_time(claim.get("reviewed_at_utc")))):
                raise ValueError(f"source {index} has an invalid claim")
    return packet


def load_packet(path="data/research_packet.json"):
    return read_json(Path(path), default=None)


def normalize_packet(packet, migrated_at=None):
    if isinstance(packet, dict) and packet.get("schema_version") == 1:
        return migrate_packet(packet, migrated_at)
    return packet


def evidence_status(packet, stale_after_hours=24, now=None):
    """Summarize evidence quality without treating captured text as a forecast."""
    if packet is None:
        return {"state": "missing", "valid": False, "stale": True, "sources": 0, "facts": 0, "captured": 0, "unavailable": 0, "rejected": 0, "unverified": 0, "warnings": ["No research packet is recorded."], "packet": None}
    try:
        packet = normalize_packet(packet)
        validate_packet(packet)
    except ValueError as error:
        return {"state": "invalid", "valid": False, "stale": True, "sources": 0, "facts": 0, "captured": 0, "unavailable": 0, "rejected": 0, "unverified": 0, "warnings": [str(error)], "packet": packet}
    current = now or datetime.now(timezone.utc)
    sources = packet["sources"]
    successful = [source for source in sources if source["collection_state"] == "captured" and source["last_success_at_utc"]]
    stale_sources = [source for source in successful if (current - parse_time(source["last_success_at_utc"])).total_seconds() > stale_after_hours * 3600]
    captured = sum(source["collection_state"] == "captured" for source in sources)
    unavailable = sum(source["collection_state"] == "unavailable" for source in sources)
    rejected = sum(source["collection_state"] == "rejected" for source in sources)
    claims = [claim for source in sources for claim in source["claims"]]
    unverified = sum(source["verification_status"] != "reviewed" for source in sources) + sum(claim["verification_status"] != "reviewed" for claim in claims)
    warnings = list(packet.get("warnings", []))
    if not successful:
        warnings.append("No source has a successful retrieval.")
    if successful and len(stale_sources) == len(successful):
        warnings.append(f"All successful research evidence is older than {stale_after_hours} hours.")
    if unavailable:
        warnings.append(f"{unavailable} source collection result(s) are unavailable.")
    if rejected:
        warnings.append(f"{rejected} source collection result(s) were rejected.")
    source_summaries = [{"id": source["id"], "state": source["collection_state"], "last_success_at_utc": source["last_success_at_utc"], "stale": source not in successful or source in stale_sources} for source in sources]
    return {"state": "ready" if successful else "empty", "valid": True, "stale": not successful or len(stale_sources) == len(successful),
            "sources": len(sources), "facts": len(claims), "captured": captured, "unavailable": unavailable, "rejected": rejected,
            "unverified": unverified, "source_summaries": source_summaries, "warnings": list(dict.fromkeys(warnings)), "packet": packet}


def main():
    from .config import load
    from .workflow import update
    config = load()
    result = evidence_status(load_packet(), config.get("research_stale_after_hours", 24))
    update("research", {key: value for key, value in result.items() if key != "packet"})
    print(f"research packet: {result['state']}, {result['captured']} captured, {result['unavailable']} unavailable, {result['rejected']} rejected")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
