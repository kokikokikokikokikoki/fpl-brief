"""Matchday: live gameweek scoring, a live mini-league table and season hindsight from public FPL data.

Everything here is read-only. Live points come from FPL's ``event/{gw}/live`` feed; bonus and
auto-subs are projected with FPL's published rules until FPL confirms them, and are labelled so.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from itertools import product

from .api import BASE, HEADERS

ROLE = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
LIMITS = {"GK": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
BONUS = {1: 3, 2: 2, 3: 1}
LIVE_TTL, PICKS_TTL, BOOT_TTL, HISTORY_TTL, FINAL_TTL = 60, 3600, 300, 1800, 7 * 86400
FETCH_TIMEOUT = 12
WORKERS = 8
CACHE_MAX = 256


class Unavailable(Exception):
    """Matchday can't be built right now (message is safe to show)."""


# --- fetching ------------------------------------------------------------------------------

_CACHE = {}
_LOCK = threading.Lock()


def http_get(path, timeout=FETCH_TIMEOUT):
    """GET a public FPL endpoint once, with one retry on transient failures."""
    request = urllib.request.Request(f"{BASE}/{path}", headers=HEADERS)
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 429 and error.code < 500 or attempt:
                raise Unavailable(f"FPL returned HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            if attempt:
                raise Unavailable("FPL couldn't be reached") from None
        time.sleep(1)


def cached(key, ttl, load, now=None):
    """Bounded in-memory TTL cache; a failed load is not cached.

    An entry is fresh only within the *caller's* ttl, so a feed first cached with a long ttl
    (before kick-off) is refetched once a caller asks for it with a live ttl.
    """
    now = now or time.monotonic
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now() - hit[0] < ttl:
            return hit[1]
    value = load()
    with _LOCK:
        if len(_CACHE) >= CACHE_MAX:
            for stale in sorted(_CACHE, key=lambda k: _CACHE[k][0])[: CACHE_MAX // 4]:
                _CACHE.pop(stale, None)
        _CACHE[key] = (now(), value)
    return value


def clear_cache():
    with _LOCK:
        _CACHE.clear()


# --- scoring -------------------------------------------------------------------------------

def _int(value, default=0):
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def live_points(live):
    """{element_id: {"points", "minutes", "bonus"}} from an ``event/{gw}/live`` payload."""
    result = {}
    for row in (live or {}).get("elements") or []:
        if isinstance(row, dict) and isinstance(row.get("stats"), dict):
            stats = row["stats"]
            result[_int(row.get("id"))] = {"points": _int(stats.get("total_points")), "minutes": _int(stats.get("minutes")), "bonus": _int(stats.get("bonus"))}
    return result


def _fixture_stat(fixture, identifier):
    for stat in fixture.get("stats") or []:
        if isinstance(stat, dict) and stat.get("identifier") == identifier:
            return [row for side in ("h", "a") for row in stat.get(side) or [] if isinstance(row, dict)]
    return []


def provisional_bonus(fixtures):
    """{element_id: bonus} for started fixtures whose bonus FPL hasn't added yet (FPL tie rules)."""
    bonus = {}
    for fixture in fixtures or []:
        if not isinstance(fixture, dict) or not fixture.get("started") or fixture.get("finished") or _fixture_stat(fixture, "bonus"):
            continue
        bps = [(_int(row.get("element")), _int(row.get("value"))) for row in _fixture_stat(fixture, "bps")]
        for element, value in bps:
            rank = 1 + sum(1 for _, other in bps if other > value)
            if rank in BONUS:
                bonus[element] = bonus.get(element, 0) + BONUS[rank]
    return bonus


def team_fixture_state(fixtures):
    """{team_id: "yet" | "playing" | "done"} for the gameweek; teams without a fixture are absent."""
    states = {}
    for fixture in fixtures or []:
        if not isinstance(fixture, dict):
            continue
        state = "done" if fixture.get("finished") or fixture.get("finished_provisional") else "playing" if fixture.get("started") else "yet"
        for side in ("team_h", "team_a"):
            team = fixture.get(side)
            previous = states.get(team)
            # A double gameweek is only "done" when both fixtures are; any live fixture makes it "playing".
            states[team] = state if previous is None else ("playing" if "playing" in (previous, state) else "yet" if "yet" in (previous, state) else "done")
    return states


def _legal(counts):
    return all(LIMITS[role][0] <= counts.get(role, 0) <= LIMITS[role][1] for role in LIMITS)


def score_picks(picks_payload, points, fixture_state, players, bonus=None):
    """Score one entry's gameweek: projected auto-subs, captaincy fallback and chip multipliers."""
    bonus = bonus or {}
    chip = (picks_payload or {}).get("active_chip")
    picks = sorted((p for p in (picks_payload or {}).get("picks") or [] if isinstance(p, dict)), key=lambda p: _int(p.get("position"), 99))
    rows = []
    for pick in picks:
        element = _int(pick.get("element"))
        info = players.get(element) or {}
        team = info.get("team")
        stats = points.get(element) or {"points": 0, "minutes": 0, "bonus": 0}
        projected = 0 if stats["bonus"] else bonus.get(element, 0)  # never on top of bonus FPL has added
        state = fixture_state.get(team, "done")  # no fixture this gameweek: nothing more to come
        rows.append({
            "id": element, "name": info.get("name") or f"#{element}", "team": info.get("team_short"), "role": ROLE.get(info.get("element_type"), "?"),
            "position": _int(pick.get("position")), "is_captain": bool(pick.get("is_captain")), "is_vice": bool(pick.get("is_vice_captain")),
            "points": stats["points"] + projected, "provisional_bonus": projected, "minutes": stats["minutes"], "state": state,
            "starter": _int(pick.get("position"), 99) <= 11, "sub_in": False, "sub_out": False,
        })
    starters = [r for r in rows if r["starter"]]
    bench = [r for r in rows if not r["starter"]]
    bench_boost = chip == "bboost"
    if not bench_boost:
        counts = {}
        for r in starters:
            counts[r["role"]] = counts.get(r["role"], 0) + 1
        used = set()
        for out in starters:
            if not (out["state"] == "done" and out["minutes"] == 0):
                continue
            for candidate in bench:
                if candidate["id"] in used:
                    continue
                if (candidate["role"] == "GK") != (out["role"] == "GK"):
                    continue
                if candidate["minutes"] == 0 and candidate["state"] != "done":
                    break  # FPL would wait for this bench player; don't project past them
                if candidate["minutes"] == 0:
                    continue
                trial = dict(counts)
                trial[out["role"]] -= 1
                trial[candidate["role"]] = trial.get(candidate["role"], 0) + 1
                if not _legal(trial):
                    continue
                counts, out["sub_out"], candidate["sub_in"] = trial, True, True
                used.add(candidate["id"])
                break
    counted = [r for r in rows if bench_boost or (r["starter"] and not r["sub_out"]) or r["sub_in"]]
    captain = next((r for r in rows if r["is_captain"]), None)
    vice = next((r for r in rows if r["is_vice"]), None)
    armband = captain
    if captain and captain["state"] == "done" and captain["minutes"] == 0 and vice and not (vice["state"] == "done" and vice["minutes"] == 0):
        armband = vice
    multiplier = 3 if chip == "3xc" else 2
    for r in rows:
        r["counts"] = r in counted
        r["multiplier"] = (multiplier if r is armband else 1) if r["counts"] else 0
        r["armband"] = r is armband
    total = sum(r["points"] * r["multiplier"] for r in rows)
    return {"rows": rows, "total": total, "chip": chip, "armband": armband["id"] if armband else None,
            "bench_points": sum(r["points"] for r in rows if not r["counts"]),
            "played": sum(1 for r in counted if r["state"] == "done" or r["minutes"] > 0), "to_play": sum(1 for r in counted if r["state"] != "done")}


def best_possible(scored):
    """Best legal XI plus best captain from the same 15, with hindsight (chip-aware)."""
    rows = scored["rows"]
    multiplier = 3 if scored.get("chip") == "3xc" else 2
    if scored.get("chip") == "bboost":
        return sum(r["points"] for r in rows) + (multiplier - 1) * max((r["points"] for r in rows), default=0)
    by_role = {role: sorted((r["points"] for r in rows if r["role"] == role), reverse=True) for role in LIMITS}
    best = 0
    for d, m, f in product(range(3, 6), range(2, 6), range(1, 4)):
        if d + m + f != 10 or len(by_role["DEF"]) < d or len(by_role["MID"]) < m or len(by_role["FWD"]) < f or not by_role["GK"]:
            continue
        xi = by_role["GK"][:1] + by_role["DEF"][:d] + by_role["MID"][:m] + by_role["FWD"][:f]
        best = max(best, sum(xi) + (multiplier - 1) * max(xi))
    return best


def hindsight_row(gameweek, scored, history_row):
    """One finished gameweek: official points against the hindsight best, split into armband and lineup cost."""
    official = _int((history_row or {}).get("points"), scored["total"])
    best = max(best_possible(scored), official)
    multiplier = 3 if scored.get("chip") == "3xc" else 2
    counted = [r for r in scored["rows"] if r["counts"]]
    armband_points = next((r["points"] for r in counted if r["armband"]), 0)
    armband_cost = max(0, (multiplier - 1) * (max((r["points"] for r in counted), default=0) - armband_points))
    left = best - official
    return {"gameweek": gameweek, "points": official, "best": best, "left": left, "armband_cost": min(armband_cost, left),
            "lineup_cost": max(0, left - armband_cost), "bench_points": _int((history_row or {}).get("points_on_bench"), scored["bench_points"]),
            "chip": scored.get("chip")}


def league_table(entries):
    """Live table for the compared group: pre-GW order, live order and movement."""
    table = []
    for entry in entries:
        history = entry.get("entry_history") or {}
        cost = _int(history.get("event_transfers_cost"))
        before = _int(history.get("total_points")) - _int(history.get("points")) + cost
        table.append({"entry_id": entry["entry_id"], "name": entry.get("name"), "is_you": bool(entry.get("is_you")), "chip": entry["scored"].get("chip"),
                      "gw_points": entry["scored"]["total"] - cost, "hits": cost, "before": before, "total": before + entry["scored"]["total"] - cost,
                      "to_play": entry["scored"]["to_play"], "captain": next((r["name"] for r in entry["scored"]["rows"] if r["armband"]), None)})
    for key, field in (("before", "start_rank"), ("total", "rank")):
        ordered = sorted(table, key=lambda row: (-row[key], row["entry_id"]))
        for index, row in enumerate(ordered):
            row[field] = 1 + sum(1 for other in ordered[:index] if other[key] > row[key])
    for row in table:
        row["move"] = row["start_rank"] - row["rank"]
    return sorted(table, key=lambda row: (row["rank"], -row["gw_points"], row["entry_id"]))


def swings(you, rivals, limit=5):
    """Players whose points move you against the compared rivals: points × (your multiplier − rival average)."""
    if not rivals:
        return {"gaining": [], "losing": []}
    mine = {r["id"]: r for r in you["rows"]}
    theirs = {}
    for scored in rivals:
        for r in scored["rows"]:
            theirs.setdefault(r["id"], {"row": r, "sum": 0, "owners": 0})
            theirs[r["id"]]["sum"] += r["multiplier"]
            theirs[r["id"]]["owners"] += 1
    rows = []
    for element in set(mine) | set(theirs):
        row = mine.get(element) or theirs[element]["row"]
        your_mult = mine[element]["multiplier"] if element in mine else 0
        rival_avg = theirs.get(element, {"sum": 0})["sum"] / len(rivals)
        impact = round(row["points"] * (your_mult - rival_avg), 1)
        if impact:
            rows.append({"id": element, "name": row["name"], "team": row["team"], "points": row["points"], "yours": your_mult, "owned": element in mine,
                         "rival_owners": theirs.get(element, {"owners": 0})["owners"], "impact": impact})
    rows.sort(key=lambda r: (-abs(r["impact"]), r["id"]))
    return {"gaining": [r for r in rows if r["impact"] > 0][:limit], "losing": [r for r in rows if r["impact"] < 0][:limit]}


# --- assembly ------------------------------------------------------------------------------

def _players(boot):
    teams = {t.get("id"): t.get("short_name") for t in boot.get("teams") or [] if isinstance(t, dict)}
    return {p.get("id"): {"name": p.get("web_name"), "team": p.get("team"), "team_short": teams.get(p.get("team")), "element_type": p.get("element_type")}
            for p in boot.get("elements") or [] if isinstance(p, dict)}


def _status(event, fixtures):
    if not fixtures or not any(f.get("started") for f in fixtures):
        return "waiting"
    if not all(f.get("finished") or f.get("finished_provisional") for f in fixtures):
        return "live"
    return "final" if event.get("finished") and event.get("data_checked") else "provisional"


def build(snapshot, get=http_get):
    """Assemble the Matchday payload. ``get(path, ttl)`` fetches (and caches) a public FPL path."""
    team_id = _int((snapshot or {}).get("team_id"), None)
    if not team_id:
        return {"state": "unavailable", "reason": "No team is configured yet."}
    try:
        boot = get("bootstrap-static/", BOOT_TTL)
        events = [e for e in boot.get("events") or [] if isinstance(e, dict)]
        event = next((e for e in events if e.get("is_current")), None)
        if not event:
            return {"state": "unavailable", "reason": "The season hasn't started yet: no gameweek has passed its deadline."}
        gameweek = _int(event.get("id"))
        players = _players(boot)
        fixtures = [f for f in get(f"fixtures/?event={gameweek}", LIVE_TTL) or [] if isinstance(f, dict)]
        status = _status(event, fixtures)
        ttl = PICKS_TTL if status == "final" else LIVE_TTL
        points = live_points(get(f"event/{gameweek}/live/", ttl))
    except Unavailable as error:
        return {"state": "unavailable", "reason": f"Live FPL data isn't available right now ({error})."}
    bonus = provisional_bonus(fixtures)
    fixture_state = team_fixture_state(fixtures)
    rivals = [r for r in (snapshot.get("rivals") or []) if isinstance(r, dict) and _int(r.get("entry_id"), None)]
    group = [{"entry_id": team_id, "name": ((snapshot.get("manager") or {}).get("entry_name")) or "You", "is_you": True}]
    group += [{"entry_id": r["entry_id"], "name": r.get("name"), "is_you": False} for r in rivals if r["entry_id"] != team_id]
    warnings = []

    def picks(entry):
        return get(f"entry/{entry['entry_id']}/event/{gameweek}/picks/", PICKS_TTL)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda entry: _attempt(picks, entry), group))
    entries = []
    for entry, (payload, error) in zip(group, results):
        if error:
            if entry["is_you"]:
                return {"state": "unavailable", "reason": f"Your GW{gameweek} picks couldn't be loaded ({error})."}
            warnings.append(f"Skipped {entry['name']}: {error}.")
            continue
        entries.append({**entry, "entry_history": payload.get("entry_history") or {}, "scored": score_picks(payload, points, fixture_state, players, bonus)})
    you = entries[0]
    others = [e["scored"] for e in entries[1:]]
    return {
        "state": "ready", "gameweek": gameweek, "status": status, "deadline_utc": event.get("deadline_time"),
        "average": event.get("average_entry_score") if status == "final" else None, "highest": event.get("highest_score") if status == "final" else None,
        "you": {**you["scored"], "hits": _int(you["entry_history"].get("event_transfers_cost"))},
        "league": league_table(entries), "swings": swings(you["scored"], others),
        "fixtures": {"total": len(fixtures), "started": sum(1 for f in fixtures if f.get("started")), "finished": sum(1 for f in fixtures if f.get("finished") or f.get("finished_provisional"))},
        "season": season(team_id, events, players, [e["entry_id"] for e in entries[1:]], get, warnings),
        "warnings": warnings,
        "method": "Live points are FPL's own. Bonus and auto-subs are projected with FPL's rules until FPL confirms them. The league table covers the rivals your snapshot compares, not the whole mini-league.",
    }


def _attempt(function, *args):
    try:
        return function(*args), None
    except Unavailable as error:
        return None, str(error)
    except Exception:  # a malformed payload for one rival must not sink the page
        return None, "unexpected data"


def _final_points(get, gameweek):
    # Keep only points and minutes for finished gameweeks; the raw feed is large and never cached.
    return cached(("final-live", gameweek), FINAL_TTL, lambda: live_points(get(f"event/{gameweek}/live/", 0)))


def season(team_id, events, players, rival_ids, get, warnings):
    """Per finished gameweek: official points against the hindsight best, plus bench points against rivals."""
    finished = sorted(_int(e.get("id")) for e in events if e.get("finished") and e.get("data_checked"))
    if not finished:
        return {"state": "unavailable", "reason": "No finished gameweek yet."}
    try:
        history = {_int(h.get("event")): h for h in (get(f"entry/{team_id}/history/", HISTORY_TTL) or {}).get("current") or [] if isinstance(h, dict)}
    except Unavailable as error:
        return {"state": "unavailable", "reason": f"Your season history couldn't be loaded ({error})."}
    played = [gw for gw in finished if gw in history]

    def one(gameweek):
        payload = get(f"entry/{team_id}/event/{gameweek}/picks/", FINAL_TTL)
        points = _final_points(get, gameweek)
        scored = score_picks(payload, points, {}, players)  # finished: every fixture is done
        return hindsight_row(gameweek, scored, history.get(gameweek))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda gw: _attempt(one, gw), played))
        rival_histories = list(pool.map(lambda rid: _attempt(lambda: get(f"entry/{rid}/history/", HISTORY_TTL)), rival_ids))
    rows = []
    for gameweek, (row, error) in zip(played, results):
        if error:
            warnings.append(f"GW{gameweek} review skipped: {error}.")
        else:
            rows.append(row)
    bench = [sum(_int(h.get("points_on_bench")) for h in (payload or {}).get("current") or [] if isinstance(h, dict) and _int(h.get("event")) in played)
             for payload, error in rival_histories if not error]
    return {
        "state": "ready" if rows else "unavailable", "reason": None if rows else "No finished gameweek could be reviewed.",
        "gameweeks": rows, "left": sum(r["left"] for r in rows), "armband_cost": sum(r["armband_cost"] for r in rows),
        "lineup_cost": sum(r["lineup_cost"] for r in rows), "bench_points": sum(r["bench_points"] for r in rows),
        "rival_bench_average": round(sum(bench) / len(bench), 1) if bench else None, "rivals_compared": len(bench),
        "method": "Best possible = the highest-scoring legal XI and captain from the same 15, chosen with hindsight. Nobody gets this every week; it shows where points slipped.",
    }


def cached_getter(fetch=http_get):
    """A ``get(path, ttl)`` that shares the module cache across requests; ``ttl`` 0 fetches without caching."""
    return lambda path, ttl: cached(("get", path), ttl, lambda: fetch(path)) if ttl > 0 else fetch(path)
