#!/usr/bin/env python3
"""Build a concise, read-only Fantasy Premier League team digest."""

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from fpl_brief.api import Client
from fpl_brief.collect import collect
from fpl_brief.config import load as load_config
from fpl_brief.analyze import meaningful_changes
from fpl_brief.decision import assess
from fpl_brief.research import evidence_status, load_packet
from fpl_brief.workflow import update as update_workflow
from fpl_brief.render import render
from fpl_brief.storage import read_json, write_atomic as write_json_atomic

TEAM_ID = os.environ.get("FPL_TEAM_ID", "6572775")
BASE = "https://fantasy.premierleague.com/api"
OUT = os.environ.get("FPL_DIGEST_PATH", "digest.md")
TIMEOUT_SECONDS = 30
RETRIES = 3

POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
STATUS = {"a": "available", "d": "doubtful", "i": "injured", "s": "suspended", "u": "unavailable", "n": "not eligible"}
HEADERS = {"User-Agent": "Mozilla/5.0 (fpl-brief fetcher)"}


class FetchError(RuntimeError):
    """Raised when FPL data cannot be downloaded after retrying."""


def get(path, opener=urllib.request.urlopen, retries=RETRIES, sleep=time.sleep):
    """Download JSON from the public FPL API with bounded retry attempts."""
    url = f"{BASE}/{path}"
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with opener(request, timeout=TIMEOUT_SECONDS) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == retries:
                raise FetchError(f"could not fetch {path}: {exc}") from exc
            sleep(attempt)


def format_number(value):
    return f"{value:,}" if isinstance(value, int) else "?"


def format_money(tenths):
    return f"£{tenths / 10:.1f}m" if isinstance(tenths, (int, float)) else "?"


def gameweeks(events):
    """Return the last completed, current, and next FPL events when present."""
    finished = [event for event in events if event.get("finished")]
    unfinished = [event for event in events if not event.get("finished")]
    return {
        "last_finished": max(finished, key=lambda event: event["id"], default=None),
        "current": next((event for event in events if event.get("is_current")), None),
        "next": next((event for event in events if event.get("is_next")), None),
        "first_unfinished": min(unfinished, key=lambda event: event["id"], default=None),
    }


def availability(player):
    status = STATUS.get(player.get("status"), "unknown")
    chance = player.get("chance_of_playing_next_round")
    news = (player.get("news") or "").replace("|", "/")
    needs_attention = status != "available" or (chance is not None and chance < 100) or bool(news)
    if not needs_attention:
        return None
    chance_text = f"{chance}% chance" if chance is not None else "chance not supplied"
    updated = player.get("news_added") or "not supplied"
    return status, chance_text, updated, news or "No detail supplied by FPL."


def fixture_map(fixtures, teams):
    result = {}
    for fixture in fixtures:
        home, away = fixture["team_h"], fixture["team_a"]
        result.setdefault(home, []).append((teams[away]["short_name"], "H", fixture["team_h_difficulty"]))
        result.setdefault(away, []).append((teams[home]["short_name"], "A", fixture["team_a_difficulty"]))
    return result


def build_digest(boot, entry, history, picks, fixtures, team_id, generated_at=None):
    elements = {element["id"]: element for element in boot["elements"]}
    teams = {team["id"]: team for team in boot["teams"]}
    weeks = gameweeks(boot["events"])
    next_week = weeks["next"]
    snapshot_gw = picks.get("entry_history", {}).get("event") or entry.get("current_event")
    generated_at = generated_at or datetime.now(timezone.utc)
    lines = []
    write = lines.append

    write(f"# FPL DIGEST — Team {team_id}")
    labels = [f"generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}"]
    if snapshot_gw:
        labels.append(f"squad snapshot GW{snapshot_gw}")
    if weeks["last_finished"]:
        labels.append(f"last completed GW{weeks['last_finished']['id']}")
    if weeks["current"]:
        labels.append(f"current GW{weeks['current']['id']}")
    elif weeks["first_unfinished"]:
        labels.append(f"next active GW{weeks['first_unfinished']['id']}")
    if next_week:
        labels.append(f"next GW{next_week['id']} deadline {next_week.get('deadline_time', '?')}")
    write(f"_{' · '.join(labels)}_\n")

    recent_history = history.get("current", [])
    last = recent_history[-1] if recent_history else None
    chips = history.get("chips", [])
    chip_text = ", ".join(f"{chip['name']} (GW{chip['event']})" for chip in chips) or "none"
    write("## Manager")
    write(f"- Overall rank: **{format_number(entry.get('summary_overall_rank'))}** | total points: **{entry.get('summary_overall_points', '?')}**")
    if last:
        is_current = weeks["current"] and last.get("event") == weeks["current"]["id"]
        period = f"Current GW{last.get('event', '?')} so far" if is_current else f"Latest completed GW{last.get('event', '?')}"
        write(f"- {period}: {last.get('points', '?')} pts (rank {format_number(last.get('rank'))}), {last.get('points_on_bench', '?')} left on bench, {format_money(last.get('bank'))} ITB, squad value {format_money(last.get('value'))}")
        transfer_period = "current GW" if is_current else "completed GW"
        write(f"- Transfers in {transfer_period} {last.get('event', '?')}: {last.get('event_transfers', '?')} (cost {last.get('event_transfers_cost', 0)} pts)")
    write(f"- Chips used: {chip_text}\n")

    alerts = []
    for pick in picks.get("picks", []):
        player = elements.get(pick.get("element"))
        player_availability = availability(player) if player else None
        if player_availability:
            alerts.append((player["web_name"], *player_availability))
    write("## Availability alerts")
    if alerts:
        write("| Player | FPL status | Availability | FPL news updated | Latest FPL news |")
        write("|---|---|---|---|---|")
        for name, status, chance, updated, news in alerts:
            write(f"| {name} | {status} | {chance} | {updated} | {news} |")
    else:
        write("- No flagged players in this squad snapshot.")
    write("")

    next_fixtures = fixture_map(fixtures, teams)

    def row(pick):
        player = elements[pick["element"]]
        club = teams[player["team"]]["short_name"]
        fixtures_text = " / ".join(f"{opponent} ({where}, FDR {difficulty})" for opponent, where, difficulty in next_fixtures.get(player["team"], [])) or "No next-GW fixture"
        tags = " ".join(tag for active, tag in ((pick.get("is_captain"), "(C)"), (pick.get("is_vice_captain"), "(VC)")) if active)
        return f"| {POS.get(player['element_type'], '?')} | {player['web_name']} {tags} | {club} | £{player['now_cost'] / 10:.1f} | {player.get('form', '?')} | {player.get('total_points', '?')} | {player.get('selected_by_percent', '?')}% | {pick.get('multiplier', '?')} | {fixtures_text} |"

    squad = picks.get("picks", [])
    groups = (("Starting XI", [pick for pick in squad if pick.get("position", 99) <= 11]), ("Bench (in order)", [pick for pick in squad if pick.get("position", 0) > 11]))
    for title, group in groups:
        write(f"## {title}")
        write("| Pos | Player | Club | £ | Form | Total | Own | Mult. | Next fixture |")
        write("|---|---|---|---|---|---|---|---|---|")
        for pick in group:
            write(row(pick))
        write("")

    if next_week:
        write(f"## GW{next_week['id']} fixtures")
        if fixtures:
            for fixture in fixtures:
                home = teams[fixture["team_h"]]["short_name"]
                away = teams[fixture["team_a"]]["short_name"]
                write(f"- {home} (FDR {fixture['team_h_difficulty']}) v {away} (FDR {fixture['team_a_difficulty']})")
        else:
            write("- Fixtures have not been published yet.")
    else:
        write("## Upcoming fixtures\n- No next gameweek is currently scheduled.")
    return "\n".join(lines) + "\n"


def write_atomic(path, content):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=directory)
    try:
        with handle:
            handle.write(content)
        os.replace(handle.name, path)
    except Exception:
        try:
            os.unlink(handle.name)
        except FileNotFoundError:
            pass
        raise


def main():
    config = load_config()
    previous = read_json("data/latest.json", default=None)
    snapshot, boot = collect(Client(), config)
    changes = {"schema_version": 1, "generated_at_utc": snapshot["generated_at_utc"], "changes": meaningful_changes(previous, snapshot)}
    decision = assess(snapshot, config)
    digest = render(snapshot, boot, config["timezone"], decision)
    write_json_atomic("data/latest.json", snapshot)
    write_json_atomic("data/decision.json", decision)
    write_json_atomic("data/changes.json", changes)
    write_json_atomic("data/catalog.json", {
        "schema_version": 1,
        "generated_at_utc": snapshot["generated_at_utc"],
        "players": [{key: player.get(key) for key in (
            "id", "web_name", "team", "element_type", "now_cost", "form",
            "total_points", "selected_by_percent", "status",
            "chance_of_playing_next_round", "news", "news_added", "ep_next",
            "minutes", "goals_scored", "assists", "expected_goals",
            "expected_assists", "expected_goal_involvements",
            "transfers_in_event", "transfers_out_event", "cost_change_event", "cost_change_start",
        )} for player in boot.get("elements", [])],
        "teams": [{key: team.get(key) for key in ("id", "name", "short_name", "strength")} for team in boot.get("teams", [])],
    })
    research = evidence_status(load_packet(), config["research_stale_after_hours"])
    update_workflow("refresh", {"state": "complete", "snapshot_generated_at_utc": snapshot["generated_at_utc"], "decision_status": decision["status"]})
    update_workflow("research", {key: value for key, value in research.items() if key != "packet"})

    write_atomic(OUT, digest)
    print(f"wrote {OUT} — #club-football rank {snapshot['league']['rank']}, {len(snapshot['rivals'])} rivals")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
