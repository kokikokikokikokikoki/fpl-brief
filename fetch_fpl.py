#!/usr/bin/env python3
"""
fetch_fpl.py — pulls your FPL squad, stats and upcoming fixtures from the
public Fantasy Premier League API and writes a clean markdown digest.

No API key or login needed: everything is fetched read-only via your public
Team ID. Set your Team ID below or via the FPL_TEAM_ID environment variable.

Output: digest.md  (committed to your repo so Claude can read it each week)
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# ---- config -------------------------------------------------------------
TEAM_ID = os.environ.get("FPL_TEAM_ID", "6572775")
BASE = "https://fantasy.premierleague.com/api"
OUT = os.environ.get("FPL_DIGEST_PATH", "digest.md")

POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
STATUS = {  # FPL player status codes
    "a": "",              # available
    "d": "doubtful",
    "i": "injured",
    "s": "suspended",
    "u": "unavailable",
    "n": "not eligible",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (fpl-brief fetcher)"}


def get(path):
    req = urllib.request.Request(f"{BASE}/{path}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    # 1) core data -------------------------------------------------------
    boot = get("bootstrap-static/")
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}
    events = boot["events"]

    # current (last finished) and next (upcoming) gameweeks
    current = next((e for e in events if e["is_current"]), None)
    upcoming = next((e for e in events if e["is_next"]), None)
    if current is None:  # pre-season fallback
        current = next((e for e in events if not e["finished"]), events[0])
    if upcoming is None:
        upcoming = current
    cur_gw, up_gw = current["id"], upcoming["id"]

    # 2) your team -------------------------------------------------------
    entry = get(f"entry/{TEAM_ID}/")
    history = get(f"entry/{TEAM_ID}/history/")
    picks_gw = entry.get("current_event") or cur_gw
    picks = get(f"entry/{TEAM_ID}/event/{picks_gw}/picks/")

    # 3) upcoming fixtures + per-team difficulty -------------------------
    fixtures = get(f"fixtures/?event={up_gw}")
    # map team_id -> (opponent short, home/away, difficulty)
    next_fix = {}
    for f in fixtures:
        h, a = f["team_h"], f["team_a"]
        next_fix.setdefault(h, []).append(
            (teams[a]["short_name"], "H", f["team_h_difficulty"]))
        next_fix.setdefault(a, []).append(
            (teams[h]["short_name"], "A", f["team_a_difficulty"]))

    # ---- build digest --------------------------------------------------
    L = []
    w = L.append
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    w(f"# FPL DIGEST — Team {TEAM_ID}")
    w(f"_generated {now} · last finished GW{cur_gw} · upcoming **GW{up_gw}** "
      f"(deadline {upcoming.get('deadline_time','?')})_\n")

    # manager summary
    ch = history.get("current", [])
    last = ch[-1] if ch else {}
    chips = history.get("chips", [])
    chips_used = ", ".join(f"{c['name']} (GW{c['event']})" for c in chips) or "none"
    w("## Manager")
    w(f"- Overall rank: **{entry.get('summary_overall_rank','?'):,}**  "
      f"| total points: **{entry.get('summary_overall_points','?')}**")
    if last:
        w(f"- Last GW: {last.get('points','?')} pts "
          f"(rank {last.get('rank','?'):,}), "
          f"{last.get('points_on_bench','?')} left on bench, "
          f"£{last.get('bank',0)/10:.1f}m ITB, "
          f"squad value £{last.get('value',0)/10:.1f}m")
    w(f"- Chips used: {chips_used}")
    if last:
        w(f"- Transfers made last GW: {last.get('event_transfers','?')} "
          f"(cost {last.get('event_transfers_cost',0)} pts)\n")

    # squad table
    def row(pk):
        e = elements[pk["element"]]
        club = teams[e["team"]]["short_name"]
        pos = POS[e["element_type"]]
        fx = next_fix.get(e["team"], [])
        fxs = " / ".join(f"{o}({ha},FDR{d})" for o, ha, d in fx) or "BLANK"
        flag = STATUS.get(e["status"], "")
        cop = e.get("chance_of_playing_next_round")
        if flag and cop is not None:
            flag = f"{flag} {cop}%"
        tags = []
        if pk.get("is_captain"):
            tags.append("(C)")
        if pk.get("is_vice_captain"):
            tags.append("(VC)")
        tag = " ".join(tags)
        return (f"| {pos} | {e['web_name']} {tag} | {club} | £{e['now_cost']/10:.1f} "
                f"| {e['form']} | {e['total_points']} | {e['selected_by_percent']}% "
                f"| {e['event_points']} | {fxs} | {flag} |")

    starters = [p for p in picks["picks"] if p["position"] <= 11]
    bench = [p for p in picks["picks"] if p["position"] > 11]

    w("## Starting XI")
    w("| Pos | Player | Club | £ | Form | Tot | Own | LastGW | Next fixture | Flag |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for p in starters:
        w(row(p))
    w("\n## Bench (in order)")
    w("| Pos | Player | Club | £ | Form | Tot | Own | LastGW | Next fixture | Flag |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for p in bench:
        w(row(p))

    # upcoming fixtures overview
    w(f"\n## GW{up_gw} fixtures (all)")
    for f in fixtures:
        h, a = teams[f["team_h"]]["short_name"], teams[f["team_a"]]["short_name"]
        w(f"- {h} (FDR {f['team_h_difficulty']}) v {a} (FDR {f['team_a_difficulty']})")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"wrote {OUT} — GW{up_gw}, {len(picks['picks'])} players")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        sys.exit(1)
