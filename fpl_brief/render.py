from datetime import datetime
from zoneinfo import ZoneInfo


def clean(value):
    return str(value if value is not None else "?").replace("|", "/").replace("\n", " ")


def render(snapshot, boot, timezone="Asia/Bangkok", decision=None):
    events, league, squad = snapshot["events"], snapshot["league"], snapshot["squad_snapshot"]
    teams = {team["id"]: team["short_name"] for team in boot.get("teams", [])}
    players = {player["id"]: player for player in boot.get("elements", [])}
    lines = ["# #club-football FPL Brief", f"_Snapshot {snapshot['generated_at_utc']} · squad snapshot GW{clean(squad.get('event_id'))}_", ""]
    deadline = events.get("next", {}).get("deadline_time") if events.get("next") else None
    local_deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00")).astimezone(ZoneInfo(timezone)).strftime("%a %d %b, %H:%M %Z") if deadline else "No next deadline published"
    lines += ["## Freshness and deadline", f"- Current GW: {clean(events.get('current', {}).get('id') if events.get('current') else None)}", f"- Next deadline: {clean(deadline)} ({local_deadline})", ""]
    lines += ["## #club-football position", f"- Rank: **{clean(league.get('rank'))}** · Points: **{clean(league.get('points'))}** · Gap to leader: **{clean(league.get('gap_to_leader'))}**", f"- Leader: {clean(league.get('leader', {}).get('name') if league.get('leader') else None)} ({clean(league.get('leader', {}).get('points') if league.get('leader') else None)} pts)", f"- Status: {'provisional while the current gameweek is live' if league.get('provisional') else 'final for the latest completed gameweek'}", ""]
    if decision:
        recommendation = decision["recommendation"]
        lines += ["## Rules-only decision", f"- Status: {clean(decision['status'])}", f"- Action: {clean(recommendation['action'])}", f"- Why: {clean(recommendation['why'])}", f"- Alternative: {clean(recommendation['alternative'])}", f"- What would change this: {clean(recommendation['what_would_change'])}"]
        if decision["blockers"]:
            lines += ["- Blockers:"] + [f"  - {clean(blocker)}" for blocker in decision["blockers"]]
        lines += [f"- Jev layer: {clean(decision['jev']['status'])}. {clean(decision['jev']['message'])}", ""]
    lines += ["## Availability alerts"]
    if snapshot["availability"]:
        lines += ["| Player | Status | Chance | Updated | FPL news |", "|---|---|---|---|---|"]
        lines += [f"| {clean(row['name'])} | {clean(row['status'])} | {clean(row['chance'])}% | {clean(row['news_added'])} | {clean(row['news'])} |" for row in snapshot["availability"]]
    else:
        lines.append("- No current FPL availability alerts.")
    lines += ["", "## Rival comparison", "| Rival | Rank | Pts | Shared players | Snapshot |", "|---|---|---|---|---|"]
    for rival in snapshot["rivals"]:
        comparison = rival["comparison"]
        shared = len(comparison.get("shared", [])) if comparison.get("comparable") else "snapshot mismatch"
        lines.append(f"| {clean(rival['name'])} | {clean(rival['rank'])} | {clean(rival['points'])} | {shared} | GW{clean(rival['snapshot_event'])} |")
    lines += ["", "## Your squad", "| Player | Club | Pos | Price | Captain |", "|---|---|---|---|---|"]
    for pick in sorted(squad["picks"], key=lambda row: row.get("position", 99)):
        player = players.get(pick.get("element"), {})
        captain = "C" if pick.get("is_captain") else "VC" if pick.get("is_vice_captain") else ""
        lines.append(f"| {clean(player.get('web_name'))} | {clean(teams.get(player.get('team')))} | {clean(player.get('element_type'))} | £{clean(player.get('now_cost', 0) / 10)}m | {captain} |")
    selected_teams = {players.get(pick.get("element"), {}).get("team") for pick in squad["picks"]}
    lines += ["", "## Six-gameweek fixture horizon"]
    for event_id, fixtures in snapshot["fixtures"]["events"].items():
        relevant = [fixture for fixture in fixtures if fixture.get("team_h") in selected_teams or fixture.get("team_a") in selected_teams]
        rendered = []
        for fixture in relevant:
            home, away = teams.get(fixture.get("team_h"), "?"), teams.get(fixture.get("team_a"), "?")
            rendered.append(f"{home} (FDR {fixture.get('team_h_difficulty', '?')}) v {away} (FDR {fixture.get('team_a_difficulty', '?')})")
        lines.append(f"- GW{event_id}: {'; '.join(rendered) if rendered else 'No squad fixtures scheduled'}")
    if snapshot["fixtures"]["unassigned"]:
        lines.append(f"- Unassigned fixtures: {len(snapshot['fixtures']['unassigned'])}; not treated as blank gameweeks.")
    lines += ["", "## Discussion checklist", "- Confirm available free transfers, selling prices, and any changes made after this public snapshot.", "- Research official club and manager news for flagged players, transfer targets, and captain candidates.", "- Compare hold/wait against up to three realistic moves over the next six gameweeks.", "- Do not set a lineup or make a transfer recommendation after the deadline."]
    if snapshot["warnings"]:
        lines += ["", "## Data warnings"] + [f"- {clean(warning)}" for warning in snapshot["warnings"]]
    return "\n".join(lines) + "\n"
