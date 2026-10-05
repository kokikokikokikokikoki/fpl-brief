"""Stage 3 transfer planner: a multi-gameweek integer linear program over our xP estimates.

The model follows research/fpl-maths.md §3 (after FPL-Optimization-Tools), transfers only, no chips:
per player and gameweek it chooses the squad, XI, captain, vice-captain, bench order and transfers,
tracking the bank and free transfers week by week, and maximises the decayed sum of XI points
minus hits and a small per-transfer threshold, plus one-time values for the free transfers and cash
still held at the end of the horizon. HiGHS (``highspy``) solves it; the
import is optional and the rest of the app works without it. It is installed for local use only
(``pip install -r requirements-planner.txt``); the hosted image leaves it out because account data
is local-only.

Read-only: it suggests plans from estimates and never contacts FPL. Every next-GW suggestion is
checked by ``plan.build`` (the same rule checker the planned-transfers strip uses).
"""

import time

from . import plan as rules
from . import projection

try:  # optional dependency: the planner reports itself unavailable without it
    import highspy
except ImportError:  # pragma: no cover - exercised by patching in tests
    highspy = None

# Defaults from research/fpl-maths.md §6 Stage 3 (FPLReview/FPL-Optimization-Tools settings). Estimates, not fitted values.
HORIZON = 6
DECAY = 0.85                     # weight per week after the next gameweek
# Free transfers are valued once: only those carried out of the horizon (the count after the last GW), per
# marginal FT from research §3's diminishing list (FOT ft_value_list). The 1st FT is free every week, so it is worth 0.
FT_VALUES = {2: 2.0, 3: 1.6, 4: 1.3, 5: 1.1}
# Tunable heuristic: each transfer must beat this many decayed points, so FTs are not burnt on tiny gains in the horizon.
MIN_TRANSFER_GAIN = 0.5
BENCH_WEIGHTS = (0.03, 0.25, 0.08, 0.02)   # bench GK, then outfield bench slots 1-3 (chance their points count)
VICE_WEIGHT = 0.05               # value of the vice-captain's points
ITB_VALUE = 0.08                 # points per £1m left in the bank at the end of the horizon (valued once)
NO_TRANSFER_LAST_GWS = 2         # no moves in the last two gameweeks of the horizon (avoids short-sighted buys)
MAX_FREE_TRANSFERS = 5           # 2024/25+ rule: free transfers roll over up to five
DEFAULT_HIT_COST = 4
TOP_PLANS = 3
TIME_LIMIT_SECONDS = 10.0        # per solve
RANDOM_SEED = 0
MIP_GAP = 1e-4                   # relative optimality gap (about 0.03 points on a six-week plan)
# HiGHS presolve restarts cost several seconds on this model and found nothing better in tests; it is off.
DEFAULT_MODEL = "own"            # Stage 1's ep_next carries 30-day form across six weeks (research pitfall)
MODEL_LABELS = {"own": "our model", "fpl": "FPL-based (ep_next re-weighted by fixtures)"}

# Player pool (deterministic): the manager's 15, plus per position the top players by decayed horizon xP,
# plus the most price-efficient remaining players (decayed horizon xP per £). Ties break on player id.
POOL_TOP = {1: 12, 2: 35, 3: 35, 4: 20}
POOL_VALUE = {1: 4, 2: 10, 3: 10, 4: 6}
GONE_STATUSES = ("u", "n")       # left the club / not eligible: never bought
OUT_STATUSES = ("i", "s", "u", "n")

SQUAD_SHAPE = {1: 2, 2: 5, 3: 5, 4: 3}
XI_LIMITS = {1: (1, 1), 2: (3, 5), 3: (2, 5), 4: (1, 3)}
SQUAD_SIZE, XI_SIZE = 15, 11
BIG_M = 20
UNAVAILABLE = {"state": "unavailable", "reason": "Planner needs the highspy package"}
INSTALL_HINT = "pip install -r requirements-planner.txt"
INF = float("inf")
# The planner score (the objective) splits into these parts; plans report each one against holding.
SCORE_PARTS = ("points_gain", "hits", "transfer_penalty", "ft_value", "bank_value")


def available():
    return highspy is not None


def settings(**overrides):
    """Default planner settings; tests and callers may override any key."""
    base = {"decay": DECAY, "ft_values": dict(FT_VALUES), "min_transfer_gain": MIN_TRANSFER_GAIN, "bench_weights": BENCH_WEIGHTS, "vice_weight": VICE_WEIGHT,
            "itb_value": ITB_VALUE, "no_transfer_last_gws": NO_TRANSFER_LAST_GWS, "max_transfers_per_gw": rules.MAX_TRANSFERS,
            "time_limit": TIME_LIMIT_SECONDS, "top": TOP_PLANS}
    unknown = set(overrides) - set(base)
    if unknown:
        raise ValueError("Unknown planner settings: " + ", ".join(sorted(unknown)))
    base.update(overrides)
    values = [value for _, value in sorted(base["ft_values"].items())]
    if any(value < 0 for value in values) or any(later > earlier for earlier, later in zip(values, values[1:])):
        raise ValueError("ft_values must be non-negative and non-increasing")
    return base


def select_pool(players, projections, owned):
    """Deterministic pool of player ids (see POOL_TOP / POOL_VALUE)."""
    def score(pid):
        return float((projections.get(pid) or {}).get("xp_6_decayed") or 0.0)
    pool = set(owned)
    for kind in SQUAD_SHAPE:
        market = [pid for pid, player in players.items() if player.get("element_type") == kind and pid in projections
                  and player.get("status") not in GONE_STATUSES and pid not in pool]
        top = sorted(market, key=lambda pid: (-score(pid), pid))[:POOL_TOP[kind]]
        pool.update(top)
        rest = [pid for pid in market if pid not in pool and score(pid) > 0 and (players[pid].get("now_cost") or 0) > 0]
        pool.update(sorted(rest, key=lambda pid: (-score(pid) / players[pid]["now_cost"], pid))[:POOL_VALUE[kind]])
    return sorted(pool)


class _Model:
    """Column/row lists for one MILP, solved with HiGHS through its low-level API (fast and deterministic)."""

    def __init__(self):
        self.lower, self.upper, self.cost, self.integer, self.rows = [], [], [], [], []

    def var(self, lower=0.0, upper=1.0, cost=0.0, integer=True):
        self.lower.append(float(lower))
        self.upper.append(float(upper))
        self.cost.append(float(cost))
        self.integer.append(integer)
        return len(self.lower) - 1

    def row(self, terms, lower=-INF, upper=INF):
        self.rows.append((terms, lower, upper))

    def highs(self, time_limit):
        import numpy as np  # highspy depends on numpy
        h = highspy.Highs()
        for option, value in (("output_flag", False), ("time_limit", float(time_limit)), ("random_seed", RANDOM_SEED),
                              ("threads", 1), ("mip_rel_gap", MIP_GAP), ("presolve", "off")):
            h.setOptionValue(option, value)
        n = len(self.lower)
        h.addVars(n, np.array(self.lower), np.array(self.upper))
        h.changeColsCost(n, np.arange(n, dtype=np.int32), np.array(self.cost))
        integer = [index for index, flag in enumerate(self.integer) if flag]
        h.changeColsIntegrality(len(integer), np.array(integer, dtype=np.int32),
                                np.array([highspy.HighsVarType.kInteger] * len(integer)))
        for terms, lower, upper in self.rows:
            _add_row(h, terms, lower, upper)
        h.changeObjectiveSense(highspy.ObjSense.kMaximize)
        return h


def _add_row(h, terms, lower, upper):
    import numpy as np
    merged = {}
    for index, coef in terms:
        merged[index] = merged.get(index, 0.0) + coef
    indices = sorted(index for index, coef in merged.items() if coef)
    h.addRow(lower, upper, len(indices), np.array(indices, dtype=np.int32), np.array([merged[i] for i in indices], dtype=float))


def formulate(data, config, hold=False, relax_out=False):
    """Build the §3 model. ``data``: pool ids, kinds, clubs, xp (per week), owned, sell/buy prices, bank, fts, hit cost."""
    pool, weeks = data["pool"], range(len(data["gameweeks"]))
    kinds, clubs, xp = data["kinds"], data["clubs"], data["xp"]
    owned = set(data["owned"])
    last = len(data["gameweeks"])
    frozen = {w for w in weeks if w >= max(1, last - config["no_transfer_last_gws"])}  # the next GW always allows moves
    m = _Model()
    v = {"squad": {}, "lineup": {}, "captain": {}, "vice": {}, "bench": {}, "in": {}, "out": {}, "itb": {}, "fts": {}, "hits": {}}
    unlimited = data["free_transfers"] == "unlimited"
    end_weight = config["decay"] ** (last - 1)  # one-time end-of-horizon values carry the last GW's weight
    for w in weeks:
        weight = config["decay"] ** w
        for p in pool:
            points = xp[p][w]
            v["squad"][p, w] = m.var()
            lineup_upper = 0.0 if (w == 0 and p in data["out_next"] and not relax_out) else 1.0
            v["lineup"][p, w] = m.var(upper=lineup_upper, cost=weight * points)
            v["captain"][p, w] = m.var(upper=lineup_upper, cost=weight * points)
            v["vice"][p, w] = m.var(upper=lineup_upper, cost=weight * config["vice_weight"] * points)
            slots = (0,) if kinds[p] == 1 else (1, 2, 3)
            for o in slots:
                v["bench"][p, w, o] = m.var(cost=weight * config["bench_weights"][o] * points)
            can_move = not hold and w not in frozen
            buy_ok = can_move and p not in owned and (w > 0 or p in data["buyable_next"])
            v["in"][p, w] = m.var(upper=1.0 if buy_ok else 0.0, cost=-weight * config["min_transfer_gain"])
            v["out"][p, w] = m.var(upper=1.0 if can_move else 0.0)
        v["itb"][w] = m.var(0.0, INF, end_weight * config["itb_value"] / 10 if w == last - 1 else 0.0, integer=False)  # tenths of £1m
        v["hits"][w] = m.var(0.0, 0.0 if (hold or (w == 0 and unlimited)) else SQUAD_SIZE, -weight * data["hit_cost"])
        first = data["free_transfers"] if not unlimited else 0
        v["fts"][w] = m.var(first, first) if w == 0 else m.var(1, MAX_FREE_TRANSFERS)
    v["fts"][last] = m.var(1, MAX_FREE_TRANSFERS)
    # One-time FT value: fts after the horizon = 1 + Σ e_k, where e_k (0..1) is the k-th FT's share. The values fall
    # with k, so maximising fills e_2, e_3, ... in order and the sum is exactly the list value of an integer count.
    v["ft_marginal"] = {k: m.var(0.0, 1.0, end_weight * config["ft_values"].get(k, 0.0), integer=False)
                        for k in range(2, MAX_FREE_TRANSFERS + 1)}
    m.row([(v["fts"][last], 1)] + [(index, -1) for index in v["ft_marginal"].values()], 1, 1)

    for w in weeks:
        squad = [(v["squad"][p, w], 1) for p in pool]
        m.row(squad, SQUAD_SIZE, SQUAD_SIZE)
        m.row([(v["lineup"][p, w], 1) for p in pool], XI_SIZE, XI_SIZE)
        for kind, count in SQUAD_SHAPE.items():
            m.row([(v["squad"][p, w], 1) for p in pool if kinds[p] == kind], count, count)
            low, high = XI_LIMITS[kind]
            m.row([(v["lineup"][p, w], 1) for p in pool if kinds[p] == kind], low, high)
        for club in sorted({clubs[p] for p in pool}, key=str):
            m.row([(v["squad"][p, w], 1) for p in pool if clubs[p] == club], upper=rules.CLUB_LIMIT)
        m.row([(v["captain"][p, w], 1) for p in pool], 1, 1)
        m.row([(v["vice"][p, w], 1) for p in pool], 1, 1)
        for o in range(4):
            m.row([(v["bench"][p, w, o], 1) for p in pool if (p, w, o) in v["bench"]], 1, 1)
        for p in pool:
            slots = (0,) if kinds[p] == 1 else (1, 2, 3)
            # Each squad player is in the XI or in exactly one bench slot.
            m.row([(v["lineup"][p, w], 1), (v["squad"][p, w], -1)] + [(v["bench"][p, w, o], 1) for o in slots], 0, 0)
            # Captain and vice are different XI players.
            m.row([(v["captain"][p, w], 1), (v["vice"][p, w], 1), (v["lineup"][p, w], -1)], upper=0)
            # Continuity: squad[w] = squad[w-1] + in - out.
            previous = [(v["squad"][p, w - 1], -1)] if w else []
            m.row([(v["squad"][p, w], 1), (v["in"][p, w], -1), (v["out"][p, w], 1)] + previous,
                  0 if w else float(p in owned), 0 if w else float(p in owned))
            m.row([(v["in"][p, w], 1), (v["out"][p, w], 1)], upper=1)
        # Budget: owned players sell at the account selling price, anyone bought inside the horizon at the price paid.
        cash = [(v["itb"][w], 1)] + [(v["out"][p, w], -data["sell"][p]) for p in pool] + [(v["in"][p, w], data["buy"][p]) for p in pool]
        if w:
            m.row(cash + [(v["itb"][w - 1], -1)], 0, 0)
        else:
            m.row(cash, data["bank"], data["bank"])
        transfers = [(v["in"][p, w], 1) for p in pool]
        m.row(transfers, upper=config["max_transfers_per_gw"])
        fts, hits, nxt = v["fts"][w], v["hits"][w], v["fts"][w + 1]
        if w == 0 and unlimited:
            m.row([(nxt, 1)], 1, 1)  # after an unlimited-transfer week the next GW starts from one free transfer
            continue
        # hits = max(0, transfers - fts), exactly, with one binary z.
        z = m.var()
        m.row([(hits, 1), (fts, 1)] + [(i, -1) for i, _ in transfers], lower=0)
        m.row([(hits, 1), (fts, 1), (z, BIG_M)] + [(i, -1) for i, _ in transfers], upper=BIG_M)
        m.row([(hits, 1), (z, -BIG_M)], upper=0)
        # Unused FTs u = fts - transfers + hits (>= 0); next GW gets clamp(u + 1, 1, 5), exactly, with one binary y.
        y = m.var()
        unused = [(fts, -1), (hits, -1)] + transfers  # nxt + these = nxt - u
        m.row([(nxt, 1)] + unused, upper=1)
        m.row([(nxt, 1), (y, -BIG_M)] + unused, lower=1 - BIG_M)
        m.row([(nxt, 1), (y, BIG_M)], lower=MAX_FREE_TRANSFERS)
    return m, v


def _next_gw_columns(v):
    """Transfer columns of the next GW only: plans 2 and 3 must differ from earlier plans in this week's moves."""
    return sorted(index for key in ("in", "out") for (_, w), index in v[key].items() if w == 0)


def _cut(h, model, values, columns):
    """Exclude this exact next-GW transfer set ("no move" included): at least one of its transfer variables must change."""
    chosen = [index for index in columns if values[index] > 0.5 and model.upper[index] > 0]
    others = [index for index in columns if values[index] <= 0.5 and model.upper[index] > 0]
    _add_row(h, [(index, 1) for index in chosen] + [(index, -1) for index in others], -INF, len(chosen) - 1)


def _status(h):
    status = h.getModelStatus()
    has_solution = h.getInfo().primal_solution_status == 2  # kSolutionStatusFeasible
    if status == highspy.HighsModelStatus.kOptimal:
        return "optimal"
    if has_solution:
        return "time_limit"
    return "infeasible"


def read_plan(data, config, v, values):
    """Week-by-week squad, moves, captain, FTs, bank and XI xP from a solution vector."""
    pool, xp, gameweeks = data["pool"], data["xp"], data["gameweeks"]
    weeks, horizon_xp, horizon_raw, total_hits = [], 0.0, 0.0, 0
    parts = {key: 0.0 for key in SCORE_PARTS}
    for w, gw in enumerate(gameweeks):
        chosen = lambda key: [p for p in pool if values[v[key][p, w]] > 0.5]
        outs, ins = chosen("out"), chosen("in")
        moves = []
        for kind in SQUAD_SHAPE:  # pair each sale with a purchase in the same position, priciest first
            kind_out = sorted((p for p in outs if data["kinds"][p] == kind), key=lambda p: (-data["sell"][p], p))
            kind_in = sorted((p for p in ins if data["kinds"][p] == kind), key=lambda p: (-data["buy"][p], p))
            moves += [{"out": out, "in": incoming} for out, incoming in zip(kind_out, kind_in)]
        lineup = [p for p in pool if values[v["lineup"][p, w]] > 0.5]
        captain = next(p for p in pool if values[v["captain"][p, w]] > 0.5)
        vice = next(p for p in pool if values[v["vice"][p, w]] > 0.5)
        bench = [next(p for p in pool if (p, w, o) in v["bench"] and values[v["bench"][p, w, o]] > 0.5) for o in range(4)]
        hits = int(round(values[v["hits"][w]]))
        xi_xp = sum(xp[p][w] for p in lineup) + xp[captain][w]
        weight = config["decay"] ** w
        horizon_xp += weight * (xi_xp - hits * data["hit_cost"])
        horizon_raw += xi_xp - hits * data["hit_cost"]
        total_hits += hits
        parts["points_gain"] += weight * (sum(xp[p][w] for p in lineup) + xp[captain][w] + config["vice_weight"] * xp[vice][w]
                                          + sum(config["bench_weights"][o] * xp[p][w] for o, p in enumerate(bench)))
        parts["hits"] -= weight * hits * data["hit_cost"]
        parts["transfer_penalty"] -= weight * config["min_transfer_gain"] * len(ins)
        weeks.append({"gw": gw, "moves": moves, "transfers": len(ins), "free_transfers": int(round(values[v["fts"][w]])),
                      "hits": hits, "hit_points": hits * data["hit_cost"], "bank": int(round(values[v["itb"][w]])),
                      "squad": sorted(p for p in pool if values[v["squad"][p, w]] > 0.5), "lineup": sorted(lineup),
                      "bench": bench, "captain": captain, "vice_captain": vice, "xi_xp": round(xi_xp, 2)})
    end_weight = config["decay"] ** (len(gameweeks) - 1)
    fts_after = int(round(values[v["fts"][len(gameweeks)]]))
    parts["ft_value"] = end_weight * sum(config["ft_values"].get(k, 0.0) for k in range(2, fts_after + 1))
    parts["bank_value"] = end_weight * config["itb_value"] * weeks[-1]["bank"] / 10
    return {"weeks": weeks, "hit_points": total_hits * data["hit_cost"], "horizon_xp": round(horizon_xp, 2),
            "horizon_xp_undecayed": round(horizon_raw, 2), "free_transfers_after": fts_after,
            "score_parts": parts, "score": sum(parts.values())}


def score_against(found, hold):
    """Planner score vs holding, split into parts; ``objective_gain`` is exactly the sum of the rounded parts."""
    breakdown = {key: round(found["score_parts"][key] - hold["score_parts"][key], 4) for key in SCORE_PARTS}
    return {"breakdown": breakdown, "objective_gain": round(sum(breakdown.values()), 4)}


def solve(data, config=None):
    """Hold baseline plus up to ``top`` distinct plans. Returns {"hold", "plans", "caveats"} or {"state": ...}."""
    if highspy is None:
        return dict(UNAVAILABLE)
    config = config or settings()
    caveats = []

    def run(hold, relax_out):
        model, v = formulate(data, config, hold=hold, relax_out=relax_out)
        h = model.highs(config["time_limit"])
        started = time.perf_counter()
        h.run()
        return model, v, h, round(time.perf_counter() - started, 3)

    relax = False
    model, v, h, seconds = run(False, False)
    if _status(h) == "infeasible" and data["out_next"]:
        relax = True
        caveats.append("No legal XI avoids every player flagged out next GW, so flagged players may appear in that XI at their projection.")
        model, v, h, seconds = run(False, True)
    if _status(h) == "infeasible":
        return {"state": "infeasible", "reason": "No legal squad fits these prices, bank and rules."}
    hold_model, hold_v, hold_h, hold_seconds = run(True, relax)
    if _status(hold_h) == "infeasible":
        hold_model, hold_v, hold_h, hold_seconds = run(True, True)
        caveats.append("Holding the current squad needs a player flagged out next GW in the XI; the hold baseline counts his projection.")
    hold = read_plan(data, config, hold_v, list(hold_h.getSolution().col_value))
    hold.update({"objective": round(hold_h.getInfo().objective_function_value, 3), "solve_seconds": hold_seconds, "status": _status(hold_h)})
    plans, columns = [], _next_gw_columns(v)
    for rank in range(1, config["top"] + 1):
        if rank > 1:
            started = time.perf_counter()
            h.run()
            seconds = round(time.perf_counter() - started, 3)
        status = _status(h)
        if status == "infeasible":
            break
        values = list(h.getSolution().col_value)
        found = read_plan(data, config, v, values)
        objective = h.getInfo().objective_function_value
        found.update({"rank": rank, "objective": round(objective, 3), "solve_seconds": seconds, "status": status,
                      "gain": round(found["horizon_xp"] - hold["horizon_xp"], 2),
                      "gain_undecayed": round(found["horizon_xp_undecayed"] - hold["horizon_xp_undecayed"], 2),
                      **score_against(found, hold)})
        plans.append(found)
        if status == "time_limit":
            caveats.append(f"Plan {rank} hit the {config['time_limit']:g}s time limit; it is the best plan found, not proven best.")
        _cut(h, model, values, columns)
    if plans:
        most = max(plans, key=lambda found: (found["gain"], -found["rank"]))
        for found in plans:
            found["most_points"] = found is most
    return {"hold": hold, "plans": plans, "caveats": caveats}


def _out_next(player):
    chance = player.get("chance_of_playing_next_round")
    return player.get("status") in OUT_STATUSES or (isinstance(chance, int) and not isinstance(chance, bool) and chance == 0)


def _named(players, pid, price=None):
    player = players.get(pid) or {}
    row = {"id": pid, "name": player.get("web_name") or f"Player {pid}", "team": player.get("team"), "position": player.get("element_type")}
    if price is not None:
        row["price"] = price
    return row


def method_text(model, gameweeks, config):
    gw = gameweeks[0] if gameweeks else "next"
    values = ", ".join(f"{value:g}" for _, value in sorted(config["ft_values"].items()))
    return (f"An optimisation over estimates, not advice and not a forecast. It plans transfers only (no chips) over the next "
            f"{len(gameweeks)} GWs from your account's selling prices, bank and free transfers, using {MODEL_LABELS[model]} expected "
            f"points, and picks each week's XI, captain and bench too. Plans are ranked by a planner score: the decayed points "
            f"estimate (week k weighted {config['decay']}^k; bench slots {', '.join(str(x) for x in config['bench_weights'])} for GK then 1-3, "
            f"vice-captain {config['vice_weight']}), minus hits, minus a small threshold of {config['min_transfer_gain']:g} points per "
            f"transfer (so free transfers are not spent on tiny gains), plus a one-time value for what you still have at the end: "
            f"free transfers carried past GW{gameweeks[-1] if gameweeks else ''} ({values} for the 2nd to 5th) and {config['itb_value']:g} "
            f"per £1m left in the bank, both applied at the last gameweek's weight (decayed). Plan 1 has the highest planner score; each later plan is the best one whose GW{gw} moves "
            f"differ from every earlier plan's (rolling counts as one option), so a lower-ranked plan can gain more points. "
            f"No moves in the last {config['no_transfer_last_gws']} GWs, at most {config['max_transfers_per_gw']} per GW, and players you "
            f"own now are not bought back once sold. Gains compare with holding your squad, solved the same way. The pool is your "
            f"15 plus the top {sum(POOL_TOP.values())} by horizon estimate and {sum(POOL_VALUE.values())} best value per £ (by position). "
            f"Nothing is sent to FPL.")


def build(snapshot, catalog, private, freshness, model=DEFAULT_MODEL, history=None, now=None, config=None):
    """Top plans for the manager's real squad. States: ready, blocked, unavailable, infeasible."""
    if highspy is None:
        return dict(UNAVAILABLE)
    if model not in MODEL_LABELS:
        raise ValueError("model must be 'own' or 'fpl'")
    config = config or settings()
    if not (isinstance(private, dict) and private.get("usable") is True):
        message = private.get("message") if isinstance(private, dict) and isinstance(private.get("message"), str) else ""
        return {"state": "blocked", "reason": ("The transfer planner needs a fresh capture of your FPL account "
                                               "(selling prices, bank and free transfers). " + message).strip()}
    if not isinstance(freshness, dict) or freshness.get("stale", True):
        return {"state": "blocked", "reason": "The public FPL snapshot is stale; refresh it before planning transfers."}
    players = {p.get("id"): p for p in (catalog or {}).get("players", []) if isinstance(p, dict) and isinstance(p.get("id"), int)}
    owned = [pick.get("element") for pick in ((snapshot or {}).get("squad_snapshot") or {}).get("picks") or [] if isinstance(pick, dict)]
    prices = private.get("prices") or {}
    if len(owned) != SQUAD_SIZE or any(pid not in players or pid not in prices for pid in owned):
        return {"state": "blocked", "reason": "The saved squad, catalog and account selling prices do not line up; refresh FPL data and recapture."}
    projected = projection.build(snapshot, catalog, horizon=HORIZON, model=model, history=history)
    gameweeks = projected["gameweeks"]
    if model == "own" and not projected.get("available"):
        return {"state": "blocked", "reason": "Our model is unavailable until player history is collected; switch to FPL-based."}
    if not gameweeks:
        return {"state": "blocked", "reason": "No upcoming gameweeks are in the fixture data; refresh FPL data."}
    projections = projected["players"]
    pool = select_pool(players, projections, owned)
    free = private.get("free_transfers")
    data = {
        "pool": pool, "gameweeks": gameweeks, "owned": owned,
        "kinds": {p: players[p].get("element_type") for p in pool}, "clubs": {p: players[p].get("team") for p in pool},
        "xp": {p: [float(x) for x in ((projections.get(p) or {}).get("xp") or [0.0] * len(gameweeks))] for p in pool},
        "sell": {p: int(prices[p]["selling_price"]) if p in prices else int(players[p].get("now_cost") or 0) for p in pool},
        "buy": {p: int(players[p].get("now_cost") or 0) for p in pool},
        "bank": int(private.get("bank") or 0),
        # FPL reports 0 once this GW's free transfers are used; the first move then costs a hit.
        "free_transfers": "unlimited" if free == "unlimited" else max(0, min(MAX_FREE_TRANSFERS, int(free or 0))),
        "hit_cost": int(private.get("hit_cost") or DEFAULT_HIT_COST),
        "out_next": {p for p in pool if _out_next(players[p])},
        "buyable_next": {p for p in pool if rules._available(players[p])},
    }
    started = time.perf_counter()
    solved = solve(data, config)
    if "state" in solved:
        return solved
    caveats = list(solved["caveats"]) + list(projected.get("caveats") or [])
    plans = []
    for found in solved["plans"]:
        first = found["weeks"][0]
        pairs = [(move["out"], move["in"]) for move in first["moves"]]
        if pairs:
            checked = rules.build(snapshot, catalog, private, freshness, pairs, now=now, history=history)
            if checked.get("state") != "ready":
                caveats.append(f"A suggested plan was dropped because the rule checker refused it: {checked.get('reason')}")
                continue
            found["rules_check"] = {"state": "passed", "next_gw_estimate_delta": checked["summary"].get("net_delta")}
        else:
            found["rules_check"] = {"state": "no moves next GW"}
        found["next_gw_moves"] = [{"out": out, "in": incoming} for out, incoming in pairs]
        names = lambda pid: (players.get(pid) or {}).get("web_name") or f"Player {pid}"
        found["next_gw_action"] = ("; ".join(f"{names(out)} → {names(incoming)}" for out, incoming in pairs)
                                   if pairs else "Roll the free transfer (no moves)")
        plans.append(_present(found, players, data))
    for index, found in enumerate(plans, start=1):
        found["rank"] = index
        found["most_points"] = False
    if plans:
        max(plans, key=lambda found: (found["gain"], -found["rank"]))["most_points"] = True
    return {"state": "ready", "model": model, "model_label": MODEL_LABELS[model], "gameweeks": gameweeks,
            "hold": _present(solved["hold"], players, data), "plans": plans, "pool_size": len(pool),
            "settings": {key: list(value) if isinstance(value, tuple) else value for key, value in config.items()},
            "solve_seconds": round(time.perf_counter() - started, 3),
            "method": method_text(model, gameweeks, config), "caveats": caveats}


def _present(found, players, data):
    """Add names and prices to a solved plan (ids stay for the board hand-off)."""
    weeks = []
    for week in found["weeks"]:
        weeks.append({**week, "moves": [{"out": _named(players, move["out"], data["sell"][move["out"]]),
                                          "in": _named(players, move["in"], data["buy"][move["in"]])} for move in week["moves"]],
                      "captain": _named(players, week["captain"]), "vice_captain": _named(players, week["vice_captain"]),
                      "bench": [_named(players, p) for p in week["bench"]]})
    rounded = {"score_parts": {key: round(value, 4) for key, value in found["score_parts"].items()}, "score": round(found["score"], 4)}
    return {**found, **rounded, "weeks": weeks}


def main(argv=None):
    """Manual check: python -m fpl_brief.optimise [own|fpl] (reads the local account capture; never writes)."""
    import json
    import sys
    from datetime import datetime, timezone
    from pathlib import Path

    from .config import load as load_config
    from .decision import snapshot_freshness
    from . import private_team
    from .storage import read_json

    args = sys.argv[1:] if argv is None else argv
    model = args[0] if args else DEFAULT_MODEL
    root = Path(__file__).resolve().parent.parent
    snapshot = read_json(root / "data" / "latest.json", default={})
    catalog = read_json(root / "data" / "catalog.json", default={"players": [], "teams": []})
    history = read_json(root / "data" / "player_history.json", default=None)
    config = load_config()
    now = datetime.now(timezone.utc)
    private = private_team.load(root / "local" / "private_team.json", config, snapshot, now=now)
    result = build(snapshot, catalog, private, snapshot_freshness(snapshot, config.get("stale_after_hours", 8), now), model, history, now)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
