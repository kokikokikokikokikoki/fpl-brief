import json
import os
from pathlib import Path


DEFAULTS = {
    "schema_version": 1, "team_id": 6572775, "league_id": 461748,
    "timezone": "Asia/Bangkok", "fixture_horizon": 6, "top_rivals": 10,
    "nearby_rivals_each_side": 3, "watchlist_player_ids": [], "watchlist": [], "stale_after_hours": 8, "research_stale_after_hours": 24, "jev": {"enabled": False},
}


def load(path="config.json"):
    config = dict(DEFAULTS)
    file = Path(path)
    if file.exists():
        config.update(json.loads(file.read_text(encoding="utf-8")))
    if os.environ.get("FPL_TEAM_ID"):
        config["team_id"] = int(os.environ["FPL_TEAM_ID"])
    for key in ("team_id", "league_id", "fixture_horizon", "top_rivals", "nearby_rivals_each_side", "stale_after_hours", "research_stale_after_hours"):
        if not isinstance(config.get(key), int) or config[key] <= 0:
            raise ValueError(f"config.{key} must be a positive integer")
    if config["timezone"] != "Asia/Bangkok":
        raise ValueError("only Asia/Bangkok is currently supported")
    if not isinstance(config["watchlist_player_ids"], list) or not all(isinstance(x, int) and x > 0 for x in config["watchlist_player_ids"]):
        raise ValueError("config.watchlist_player_ids must contain positive player IDs")
    watch = config.get("watchlist")
    if not isinstance(watch, list) or not all(
        isinstance(w, dict) and isinstance(w.get("player_id"), int) and not isinstance(w.get("player_id"), bool) and w["player_id"] > 0
        and all(isinstance(w.get(k), int) and not isinstance(w.get(k), bool) and 1 <= w[k] <= 38 for k in ("from_gw", "to_gw")) and w["from_gw"] <= w["to_gw"]
        and all(isinstance(w.get(k, ""), str) and len(w.get(k, "")) <= 300 for k in ("note", "trigger"))
        for w in watch):
        raise ValueError("config.watchlist entries need player_id, from_gw <= to_gw (1-38) and short note/trigger text")
    if not isinstance(config.get("jev"), dict) or not isinstance(config["jev"].get("enabled"), bool):
        raise ValueError("config.jev.enabled must be a boolean")
    return config
