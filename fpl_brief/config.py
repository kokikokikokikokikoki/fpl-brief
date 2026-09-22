import json
import os
from pathlib import Path


DEFAULTS = {
    "schema_version": 1, "team_id": 6572775, "league_id": 461748,
    "timezone": "Asia/Bangkok", "fixture_horizon": 6, "top_rivals": 10,
    "nearby_rivals_each_side": 3, "watchlist_player_ids": [], "stale_after_hours": 8, "research_stale_after_hours": 24, "jev": {"enabled": False},
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
    if not isinstance(config.get("jev"), dict) or not isinstance(config["jev"].get("enabled"), bool):
        raise ValueError("config.jev.enabled must be a boolean")
    return config
