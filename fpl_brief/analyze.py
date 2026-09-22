def select_rivals(standings, team_id, top_count, nearby):
    ordered = sorted(standings, key=lambda row: (row.get("rank", 10**9), row.get("entry", 10**9)))
    user_index = next((i for i, row in enumerate(ordered) if row.get("entry") == team_id), None)
    if user_index is None:
        return [], None
    candidates = ordered[:top_count] + ordered[max(0, user_index - nearby):user_index] + ordered[user_index + 1:user_index + 1 + nearby]
    seen, selected = set(), []
    for row in candidates:
        entry = row.get("entry")
        if entry != team_id and entry not in seen:
            selected.append(row)
            seen.add(entry)
    return selected, ordered[user_index]


def squad_ids(picks):
    return {pick["element"] for pick in picks.get("picks", []) if "element" in pick}


def compare_squads(user_picks, rival_picks):
    user_event = user_picks.get("entry_history", {}).get("event")
    rival_event = rival_picks.get("entry_history", {}).get("event")
    if user_event != rival_event:
        return {"comparable": False, "user_event": user_event, "rival_event": rival_event}
    own, rival = squad_ids(user_picks), squad_ids(rival_picks)
    return {"comparable": True, "event_id": user_event, "shared": sorted(own & rival), "user_only": sorted(own - rival), "rival_only": sorted(rival - own)}


def meaningful_changes(old, new):
    if not old:
        return [{"field": "snapshot", "old": None, "new": "initial snapshot"}]
    changes = []
    for key in ("manager", "league", "availability"):
        if old.get(key) != new.get(key):
            changes.append({"field": key, "old": old.get(key), "new": new.get(key)})
    return changes
