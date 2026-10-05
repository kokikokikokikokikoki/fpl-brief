"""Replay finished gameweeks to score our Stage 2 model against simple baselines.

For each finished gameweek k >= FIRST_GW, the model is fitted on gameweeks < k only (player history
and team results) and predicts gameweek k. Scored on every player who played in k, and on the
TOP_BY_PRICE most expensive players (current price) among them. Run: ``python -m fpl_brief.backtest``.
"""

import argparse
import json
import sys
from pathlib import Path

from . import projection, xp_model
from .storage import read_json

FIRST_GW = 3
TOP_BY_PRICE = 100
LAST_N = 3
DATA = Path(__file__).resolve().parents[1] / "data"


def neutral(player):
    """The player as the model would have seen him, without availability news (not kept for past GWs)."""
    return {**player, "status": "a", "chance_of_playing_next_round": None, "news": ""}


def predict_gameweek(rows, results, players, gameweek):
    """{player_id: xP} for one gameweek, fitted on gameweeks < ``gameweek`` only."""
    before = [row for row in results if isinstance(row.get("gw"), int) and row["gw"] < gameweek]
    ratings = projection.team_ratings(before, [player.get("team") for player in players])
    fixtures = {gameweek: {}}
    for row in results:
        if row.get("gw") == gameweek:
            fixtures[gameweek].setdefault(row["home"], []).append((row["away"], True))
            fixtures[gameweek].setdefault(row["away"], []).append((row["home"], False))
    fitted = xp_model.fit(rows, players, before, before_gw=gameweek)
    return {player["id"]: xp_model.project_player(fitted, neutral(player), fixtures, [gameweek], ratings, gameweek)["xp"][0]
            for player in players}


def baselines(rows, gameweek):
    """Points per appearance so far, and mean points over the last LAST_N gameweeks (a missed GW counts 0)."""
    totals, games, recent = {}, {}, {}
    for row in rows:
        if not isinstance(row.get("gw"), int) or row["gw"] >= gameweek:
            continue
        points = row.get("total_points") or 0
        totals[row["id"]] = totals.get(row["id"], 0) + points
        games[row["id"]] = games.get(row["id"], 0) + 1
        if row["gw"] >= gameweek - LAST_N:
            recent[row["id"]] = recent.get(row["id"], 0) + points
    return ({pid: totals[pid] / games[pid] for pid in totals},
            {pid: value / min(LAST_N, gameweek - 1) for pid, value in recent.items()})


def ranks(values):
    """Average ranks (ties share the mean rank)."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            result[order[position]] = (start + end) / 2 + 1
        start = end + 1
    return result


def spearman(predicted, actual):
    """Spearman rank correlation; None when either side is constant or there are fewer than 3 pairs."""
    if len(predicted) < 3:
        return None
    a, b = ranks(predicted), ranks(actual)
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    var_a, var_b = sum((x - mean_a) ** 2 for x in a), sum((y - mean_b) ** 2 for y in b)
    return cov / (var_a * var_b) ** 0.5 if var_a and var_b else None


def run(history, results, catalog, ep_log=None, first_gw=FIRST_GW, top=TOP_BY_PRICE):
    """Per-model scores pooled over gameweeks: MAE over all player-GWs and the mean per-GW Spearman."""
    rows = xp_model.history_rows(history)
    results = [row for row in results or [] if isinstance(row, dict)]
    players = [player for player in (catalog or {}).get("players", []) if isinstance(player, dict) and isinstance(player.get("id"), int)]
    by_id = {player["id"]: player for player in players}
    expensive = {player["id"] for player in sorted(players, key=lambda p: (-(p.get("now_cost") or 0), p["id"]))[:top]}
    logged = ((ep_log or {}).get("gameweeks") or {}) if isinstance(ep_log, dict) else {}
    finished = sorted({row["gw"] for row in rows if isinstance(row.get("gw"), int) and row["gw"] >= first_gw})
    names = ("our model", "points per game", f"last {LAST_N} GWs average", "FPL ep_next (logged)")
    pairs = {name: {"all": [], "top": []} for name in names}
    per_gw = []
    for gameweek in finished:
        actual = {row["id"]: row.get("total_points") or 0 for row in rows if row.get("gw") == gameweek and row.get("id") in by_id}
        ppg, last = baselines(rows, gameweek)
        logged_gw = (logged.get(str(gameweek)) or {}).get("ep_next") or {}
        predictions = {"our model": predict_gameweek(rows, results, players, gameweek),
                       "points per game": ppg, f"last {LAST_N} GWs average": last,
                       "FPL ep_next (logged)": {int(key): value for key, value in logged_gw.items()}}
        row_out = {"gw": gameweek, "players": len(actual)}
        for name, predicted in predictions.items():
            if name == "FPL ep_next (logged)" and not logged_gw:
                continue
            ids = [pid for pid in actual if name != "FPL ep_next (logged)" or pid in predicted]
            couples = [(predicted.get(pid, 0.0), actual[pid]) for pid in ids]
            pairs[name]["all"].append(couples)
            pairs[name]["top"].append([(predicted.get(pid, 0.0), actual[pid]) for pid in ids if pid in expensive])
            row_out[name] = _score(couples)
        per_gw.append(row_out)
    summary = []
    for name in names:
        if not pairs[name]["all"]:
            summary.append({"model": name, "available": False})
            continue
        summary.append({"model": name, "available": True, "all": _pooled(pairs[name]["all"]), "top": _pooled(pairs[name]["top"])})
    return {"gameweeks": finished, "top_by_price": top, "summary": summary, "per_gameweek": per_gw,
            "note": ("Fitted on earlier gameweeks only. Scored on players who played; availability news is not kept for past "
                     "GWs, so the backtest runs our model without it. Prices are today's.")}


def _score(couples):
    if not couples:
        return {"n": 0, "mae": None, "spearman": None}
    mae = sum(abs(p - a) for p, a in couples) / len(couples)
    rho = spearman([p for p, _ in couples], [a for _, a in couples])
    return {"n": len(couples), "mae": round(mae, 3), "spearman": round(rho, 3) if rho is not None else None}


def _pooled(groups):
    couples = [pair for group in groups for pair in group]
    rhos = [value for value in (spearman([p for p, _ in group], [a for _, a in group]) for group in groups) if value is not None]
    score = _score(couples)
    score["spearman"] = round(sum(rhos) / len(rhos), 3) if rhos else None
    return score


def table(report):
    def cell(value):
        return "-" if value is None else f"{value:.3f}"
    lines = [f"Backtest over GW{report['gameweeks'][0]}-GW{report['gameweeks'][-1]}" if report["gameweeks"] else "Backtest: no finished gameweeks to score",
             f"{'Model':<26}{'MAE all':>9}{'rho all':>9}{'n all':>7}{'MAE top':>9}{'rho top':>9}{'n top':>7}"]
    for row in report["summary"]:
        if not row["available"]:
            lines.append(f"{row['model']:<26}  (no data for these gameweeks)")
            continue
        lines.append(f"{row['model']:<26}{cell(row['all']['mae']):>9}{cell(row['all']['spearman']):>9}{row['all']['n']:>7}"
                     f"{cell(row['top']['mae']):>9}{cell(row['top']['spearman']):>9}{row['top']['n']:>7}")
    lines.append(f"top = the {report['top_by_price']} most expensive players today; rho = mean per-GW Spearman.")
    lines.append(report["note"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backtest our expected-points model on finished gameweeks.")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    history = read_json(DATA / "player_history.json", default=None)
    if not history:
        print("No data/player_history.json yet; run python fetch_fpl.py first.", file=sys.stderr)
        return 1
    snapshot = read_json(DATA / "latest.json", default={}) or {}
    report = run(history, snapshot.get("team_results") or [], read_json(DATA / "catalog.json", default={}),
                 read_json(DATA / "ep_log.json", default=None))
    print(json.dumps(report, indent=2) if args.json else table(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
