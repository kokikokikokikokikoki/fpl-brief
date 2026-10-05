// Transfer planner panel (Candidate lens view): top multi-week plans from the server's optimiser.
// Read-only estimates; "Try on board" only fills the browser-local planned-transfers strip.
import type { PlannedTransfer } from "./transfer-plan";

export interface PlannerPerson { id: number; name: string; price?: number }
export interface PlannerWeek {
  gw: number;
  moves: Array<{ out: PlannerPerson; in: PlannerPerson }>;
  transfers: number;
  free_transfers: number;
  hits: number;
  hit_points: number;
  bank: number;
  xi_xp: number;
  captain: PlannerPerson;
}
export interface PlannerPlan {
  rank: number;
  weeks: PlannerWeek[];
  hit_points: number;
  horizon_xp: number;
  gain: number;
  gain_undecayed?: number;
  objective_gain?: number;
  breakdown?: Partial<Record<"points_gain" | "hits" | "transfer_penalty" | "ft_value" | "bank_value", number>>;
  most_points?: boolean;
  solve_seconds?: number;
  status?: string;
  next_gw_moves: PlannedTransfer[];
  next_gw_action?: string;
  /** Early-move notes for the next-GW moves (FPL's own price predictor); notes only, never part of the ranking. */
  price_notes?: Array<{ kind: string; text: string }>;
  /** Points gain minus the unconstrained plan 1's gain (only when constraints are active). */
  cost_vs_unconstrained?: number;
}
export type ConstraintKind = "force_in" | "force_out" | "keep";
/** The manager's steering: players forced in or out by a GW (null = the next GW), and owned players never sold. */
export interface PlannerConstraints { force_in: Array<{ id: number; gw: number | null }>; force_out: Array<{ id: number; gw: number | null }>; keep: number[] }
export interface PlannerConstraintRow { kind: ConstraintKind; id: number; name: string; gw: number | null; text: string }
export interface PlannerChoice { id: number; name: string; team?: string | null; position?: number | null; price?: number | null }
export interface PlannerChoices { owned: number[]; players: PlannerChoice[] }
export type PlannerResult =
  | { state: "ready"; model: string; model_label: string; gameweeks: number[]; hold: { horizon_xp: number; weeks: PlannerWeek[] }; plans: PlannerPlan[]; method: string; caveats: string[]; solve_seconds?: number;
      constraints?: PlannerConstraintRow[]; unconstrained_best_gain?: number | null; unconstrained_best_action?: string | null; choices?: PlannerChoices }
  | { state: "blocked" | "unavailable" | "infeasible" | "invalid"; reason: string; choices?: PlannerChoices };
export type PlannerView = { phase: "idle" } | { phase: "loading"; model: string } | { phase: "error"; message: string } | { phase: "done"; result: PlannerResult };

export interface PlannerRuntime {
  /** Replace the planned-transfers strip with these moves and open the board; returns an error message or null. */
  replacePlan?(moves: PlannedTransfer[]): string | null;
  status(message: string): void;
}

function esc(value: unknown): string {
  return String(value ?? "—").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
}

const money = (tenths: unknown): string => typeof tenths === "number" && Number.isFinite(tenths) ? `£${(tenths / 10).toFixed(1)}m` : "—";
const signed = (value: unknown): string => typeof value === "number" && Number.isFinite(value) ? `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}` : "—";
const MODEL_NAMES: Record<string, string> = { own: "our model", fpl: "FPL-based" };

function weekRows(plan: PlannerPlan): string {
  return plan.weeks.map((week) => {
    const moves = week.moves.length
      ? week.moves.map((move) => `<span class="plan-out">${esc(move.out.name)}</span> <span class="small">${esc(money(move.out.price))}</span><span aria-hidden="true"> → </span><span class="visually-hidden"> replaced by </span><span class="plan-in">${esc(move.in.name)}</span> <span class="small">${esc(money(move.in.price))}</span>`).join("<br>")
      : '<span class="small">No moves</span>';
    return `<tr><th scope="row">GW${esc(week.gw)}</th><td>${moves}</td><td>${esc(week.free_transfers)}</td><td>${week.hits ? `<span class="plan-bad">−${esc(week.hit_points)}</span>` : "0"}</td><td>${esc(money(week.bank))}</td><td>${esc(week.xi_xp)}</td><td>${esc(week.captain?.name)}</td></tr>`;
  }).join("");
}

const signed2 = (value: unknown): string => typeof value === "number" && Number.isFinite(value) ? `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}` : "—";

/** "Planner score vs holding" with the parts it is ranked by (they sum to the score). */
function scoreLine(plan: PlannerPlan): string {
  if (typeof plan.objective_gain !== "number") return "";
  const parts = plan.breakdown ?? {};
  const labels: Array<[keyof NonNullable<PlannerPlan["breakdown"]>, string]> = [
    ["points_gain", "points incl. bench and vice weights"], ["hits", "hits"], ["transfer_penalty", "per-transfer threshold"],
    ["ft_value", "free transfers kept at the end"], ["bank_value", "bank kept at the end"],
  ];
  const listed = labels.filter(([key]) => typeof parts[key] === "number").map(([key, label]) => `${label} ${signed2(parts[key])}`).join(", ");
  return `<p class="small planner-score">Planner score vs holding: <strong>${esc(signed2(plan.objective_gain))}</strong>${listed ? ` (${esc(listed)})` : ""}</p>`;
}

function priceNotes(notes: PlannerPlan["price_notes"]): string {
  const shown = (notes ?? []).filter((note) => note && typeof note.text === "string" && note.text);
  return shown.length ? `<ul class="price-notes">${shown.map((note) => `<li>${esc(note.text)}</li>`).join("")}</ul>` : "";
}

export const MAX_CONSTRAINTS = 5;
const CONSTRAINT_LABELS: Record<ConstraintKind, string> = { force_in: "Must buy", force_out: "Must sell", keep: "Never sell" };
const POSITIONS: Record<number, string> = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };

export const emptyConstraints = (): PlannerConstraints => ({ force_in: [], force_out: [], keep: [] });
export const constraintCount = (c: PlannerConstraints): number => c.force_in.length + c.force_out.length + c.keep.length;

/** Query string for /api/optimise: model plus force_in=ID[@GW],... force_out=ID[@GW],... keep=ID,... */
export function plannerQuery(model: string, c: PlannerConstraints): string {
  const forced = (rows: PlannerConstraints["force_in"]) => rows.map((row) => (row.gw === null ? `${row.id}` : `${row.id}@${row.gw}`)).join(",");
  const parts = [`model=${encodeURIComponent(model)}`];
  if (c.force_in.length) parts.push(`force_in=${encodeURIComponent(forced(c.force_in))}`);
  if (c.force_out.length) parts.push(`force_out=${encodeURIComponent(forced(c.force_out))}`);
  if (c.keep.length) parts.push(`keep=${encodeURIComponent(c.keep.join(","))}`);
  return parts.join("&");
}

export function constraintText(kind: ConstraintKind, name: string, gw: number | null, nextGw?: number): string {
  if (kind === "keep") return `${CONSTRAINT_LABELS[kind]} ${name}`;
  const by = gw ?? nextGw;
  return `${CONSTRAINT_LABELS[kind]} ${name}${by === undefined ? " by the next GW" : ` by GW${by}`}`;
}

export function choiceLabel(player: PlannerChoice): string {
  const bits = [player.name, player.team ?? "", POSITIONS[player.position ?? 0] ?? "", typeof player.price === "number" ? money(player.price) : ""].filter(Boolean);
  return `${bits.join(" · ")} (#${player.id})`;
}

/** Match the search box text to a player: an exact list label, a "#id" or bare id, or a unique name. */
export function resolvePlayer(text: string, choices: PlannerChoices | null): PlannerChoice | null {
  const players = choices?.players ?? [];
  const typed = text.trim();
  if (!typed) return null;
  const exact = players.find((player) => choiceLabel(player) === typed);
  if (exact) return exact;
  const id = /^#?(\d+)$/.exec(typed);
  if (id) return players.find((player) => player.id === Number(id[1])) ?? null;
  const named = players.filter((player) => player.name.toLowerCase() === typed.toLowerCase());
  return named.length === 1 ? named[0] : null;
}

/** Add one constraint; returns an error message or null (the server validates the rest). */
export function addConstraint(c: PlannerConstraints, kind: ConstraintKind, id: number, gw: number | null): string | null {
  if (constraintCount(c) >= MAX_CONSTRAINTS) return `At most ${MAX_CONSTRAINTS} constraints at a time.`;
  if (kind === "keep") {
    if (c.keep.includes(id)) return "That player is already on the never-sell list.";
    c.keep.push(id);
    return null;
  }
  if (c[kind].some((row) => row.id === id && row.gw === gw)) return "That constraint is already set.";
  c[kind].push({ id, gw });
  return null;
}

export function removeConstraint(c: PlannerConstraints, kind: ConstraintKind, index: number): void {
  if (kind === "keep") c.keep.splice(index, 1);
  else c[kind].splice(index, 1);
}

/** Chips for the active constraints, each with a remove button. */
export function renderChips(c: PlannerConstraints, choices: PlannerChoices | null, nextGw?: number): string {
  const name = (id: number) => choices?.players.find((player) => player.id === id)?.name ?? `Player ${id}`;
  const chip = (kind: ConstraintKind, index: number, text: string) =>
    `<li class="planner-chip">${esc(text)} <button type="button" class="planner-chip-remove" data-planner-remove="${esc(kind)}:${esc(index)}" aria-label="${esc(`Remove: ${text}`)}">×</button></li>`;
  const rows = [
    ...c.force_in.map((row, index) => chip("force_in", index, constraintText("force_in", name(row.id), row.gw, nextGw))),
    ...c.force_out.map((row, index) => chip("force_out", index, constraintText("force_out", name(row.id), row.gw, nextGw))),
    ...c.keep.map((id, index) => chip("keep", index, constraintText("keep", name(id), null))),
  ];
  return rows.length ? `<ul class="planner-chips" aria-label="Active constraints">${rows.join("")}</ul>` : '<p class="small">No constraints: the planner chooses freely.</p>';
}

/** "Must buy / Must sell / Never sell" controls; the player list arrives with the first planner result. */
export function renderSteering(choices: PlannerChoices | null, gameweeks: number[], c: PlannerConstraints): string {
  const nextGw = gameweeks[0];
  const chips = renderChips(c, choices, nextGw);
  if (!choices || !choices.players.length) {
    return `<fieldset class="planner-steer"><legend>Steer the plans (optional)</legend><p class="small">Run "Suggest plans" once to load the player list, then add players to buy, sell or never sell.</p>${chips}</fieldset>`;
  }
  const full = constraintCount(c) >= MAX_CONSTRAINTS;
  const disabled = full ? " disabled" : "";
  const gwOptions = `<option value="">${esc(nextGw === undefined ? "Next GW" : `Next GW (GW${nextGw})`)}</option>${gameweeks.slice(1).map((gw) => `<option value="${esc(gw)}">GW${esc(gw)}</option>`).join("")}`;
  const owned = choices.owned.map((id) => choices.players.find((player) => player.id === id)).filter((player): player is PlannerChoice => Boolean(player));
  const ownedOptions = `<option value="">Choose a player…</option>${owned.map((player) => `<option value="${esc(player.id)}">${esc(choiceLabel(player))}</option>`).join("")}`;
  const list = choices.players.map((player) => `<option value="${esc(choiceLabel(player))}"></option>`).join("");
  return `<fieldset class="planner-steer"><legend>Steer the plans (optional)</legend>`
    + `<div class="lens-controls"><label>Must buy<input id="planner-buy" list="planner-players" placeholder="Search a player" autocomplete="off"${disabled}></label><label>By<select id="planner-buy-gw"${disabled}>${gwOptions}</select></label><button class="button-secondary" type="button" data-planner-add="force_in"${disabled}>Add</button></div>`
    + `<div class="lens-controls"><label>Must sell<select id="planner-sell"${disabled}>${ownedOptions}</select></label><label>By<select id="planner-sell-gw"${disabled}>${gwOptions}</select></label><button class="button-secondary" type="button" data-planner-add="force_out"${disabled}>Add</button></div>`
    + `<div class="lens-controls"><label>Never sell<select id="planner-keep"${disabled}>${ownedOptions}</select></label><button class="button-secondary" type="button" data-planner-add="keep"${disabled}>Add</button></div>`
    + `<datalist id="planner-players">${list}</datalist>${chips}`
    + `<p class="small">Up to ${MAX_CONSTRAINTS} constraints; press "Suggest plans" to re-run with them. Gains still compare with holding your squad, which ignores them.${full ? " Limit reached: remove one to add another." : ""}</p></fieldset>`;
}

/** Card line comparing a steered plan with the free planner's plan 1. */
export function costLine(plan: PlannerPlan, best: number | null | undefined, bestAction?: string | null): string {
  const cost = plan.cost_vs_unconstrained;
  if (typeof cost !== "number" || !Number.isFinite(cost) || typeof best !== "number") return "";
  const reference = `${signed2(best)}${bestAction ? `, ${bestAction}` : ""}`;
  if (Math.abs(cost) < 0.005) return `<p class="small planner-cost">Same as the unconstrained best (${esc(reference)}).</p>`;
  if (cost < 0) return `<p class="small planner-cost">Costs <strong>${esc(Math.abs(cost).toFixed(2))}</strong> points against the unconstrained best (${esc(reference)}).</p>`;
  return `<p class="small planner-cost">${esc(cost.toFixed(2))} more estimated points than the unconstrained best (${esc(reference)}), which ranks higher on planner score.</p>`;
}

function constraintSummary(rows: PlannerConstraintRow[] | undefined): string {
  const shown = (rows ?? []).filter((row) => row && typeof row.text === "string");
  return shown.length ? `<p class="small planner-constraints">Constraints: ${shown.map((row) => esc(row.text)).join(" · ")}</p>` : "";
}

type ReadyResult = Extract<PlannerResult, { state: "ready" }>;

function planCard(plan: PlannerPlan, result: ReadyResult): string {
  const gameweeks = result.gameweeks;
  const steering = (result.constraints ?? []).length ? `${constraintSummary(result.constraints)}${costLine(plan, result.unconstrained_best_gain, result.unconstrained_best_action)}` : "";
  const first = gameweeks[0];
  const span = gameweeks.length ? `GW${gameweeks[0]}–${gameweeks[gameweeks.length - 1]}` : "the horizon";
  const moves = plan.next_gw_moves ?? [];
  const tryButton = moves.length
    ? `<button class="button-secondary" type="button" data-planner-try="${esc(plan.rank)}">Try GW${esc(first)} moves on board</button>`
    : `<p class="small">No moves in GW${esc(first)}: this plan rolls the free transfer now.</p>`;
  const laterNote = gameweeks.length > 1 ? `<p class="small">${esc(`Moves after GW${first} are indicative — re-run the planner each week.`)}</p>` : "";
  const timing = plan.status === "time_limit" ? '<p class="small plan-bad">Stopped at the time limit: best plan found, not proven best.</p>' : "";
  return `<article class="planner-card" aria-label="Plan ${esc(plan.rank)}"><header><h3>Plan ${esc(plan.rank)} · GW${esc(first)}: ${esc(plan.next_gw_action ?? (moves.length ? `${moves.length} move(s)` : "Roll the free transfer (no moves)"))}</h3>${plan.most_points ? '<p class="planner-most">Most estimated points</p>' : ""}<p class="planner-gain">Points gain vs holding: <strong>${esc(signed(plan.gain))}</strong> over ${esc(span)} <span class="small">(XI and captain, decayed estimate, after hits)</span></p>${scoreLine(plan)}<p class="small">Hits: ${plan.hit_points ? `<span class="plan-bad">−${esc(plan.hit_points)}</span>` : "none"} · horizon estimate ${esc(plan.horizon_xp)}${typeof plan.gain_undecayed === "number" ? ` · undecayed gain ${esc(signed(plan.gain_undecayed))}` : ""}</p>${steering}</header>${timing}<div class="table-wrap"><table class="planner-weeks"><thead><tr><th>GW</th><th>Moves (out → in, prices)</th><th>FTs</th><th>Hits</th><th>Bank after</th><th>XI estimate</th><th>Captain</th></tr></thead><tbody>${weekRows(plan)}</tbody></table></div>${priceNotes(plan.price_notes)}${laterNote}${tryButton}</article>`;
}

export function renderPlanner(view: PlannerView): string {
  if (view.phase === "idle") return '<p class="small">Suggests up to three transfer plans over the next six GWs from your account\'s selling prices, bank and free transfers. It is an optimisation over estimates, not advice; chips are not included.</p>';
  if (view.phase === "loading") return `<p class="plan-status" role="status">Solving with ${esc(MODEL_NAMES[view.model] ?? view.model)}… this can take up to half a minute.</p>`;
  if (view.phase === "error") return `<div class="evidence-warning" role="alert">${esc(view.message)}</div>`;
  const result = view.result;
  if (result.state !== "ready") {
    if (result.state === "unavailable") {
      return `<div class="evidence-warning" role="alert"><strong>Planner unavailable here.</strong> The planner runs on your own computer, next to your account data. Install it with <code>python -m pip install -r requirements-planner.txt</code> and use the local dashboard. <span class="small">(${esc(result.reason)})</span></div>`;
    }
    const title = result.state === "infeasible" ? "No legal plan" : result.state === "invalid" ? "Constraints not accepted" : "Planner blocked";
    return `<div class="evidence-warning" role="alert"><strong>${esc(title)}.</strong> ${esc(result.reason)}</div>`;
  }
  const note = `<p class="method">Optimisation over estimates, not advice. Model: <strong>${esc(result.model_label)}</strong>. Chips are not included. ${esc(result.method)}${result.caveats.length ? ` ${result.caveats.map(esc).join(" ")}` : ""}</p>`;
  const cards = result.plans.length ? result.plans.map((plan) => planCard(plan, result)).join("") : '<div class="empty"><strong>No plan found</strong><span>No plan could be found for these rules.</span></div>';
  const gw = result.gameweeks[0];
  return `<p class="small">Holding scores ${esc(result.hold.horizon_xp)} points over the horizon (decayed estimate). Plans are ranked by planner score: points, minus hits and a small per-transfer threshold, plus a one-time value for free transfers and bank kept at the end. Each later plan is the best one with a different GW${esc(gw)} action, so a lower-ranked plan can gain more points. Fewer than three cards means fewer distinct GW${esc(gw)} options were possible.</p><div class="planner-cards">${cards}</div>${note}`;
}

async function fetchPlans(model: string, constraints: PlannerConstraints): Promise<PlannerResult> {
  const response = await fetch(`/api/optimise?${plannerQuery(model, constraints)}`);
  const body: unknown = await response.json();
  if (typeof body === "object" && body !== null && "state" in body) return body as PlannerResult;
  const error = typeof body === "object" && body !== null && "error" in body && typeof body.error === "string" ? body.error : "The planner request failed.";
  throw new Error(error);
}

/** Render the panel into ``root`` and wire its controls. */
export function mountPlanner(root: HTMLElement, runtime: PlannerRuntime): void {
  root.innerHTML = `<div class="panel-head"><div><h2>Transfer planner</h2><p>Top three multi-week plans from estimates. Read-only: nothing is sent to FPL.</p></div></div><div class="lens-controls"><label>Expected points model<select id="planner-model"><option value="own">Our model (planner default)</option><option value="fpl">FPL-based (ep_next re-weighted)</option></select></label><button id="planner-run" class="button-primary" type="button">Suggest plans</button></div><div id="planner-steering"></div><div id="planner-output" class="lens-output">${renderPlanner({ phase: "idle" })}</div>`;
  const output = root.querySelector<HTMLElement>("#planner-output");
  const select = root.querySelector<HTMLSelectElement>("#planner-model");
  const button = root.querySelector<HTMLButtonElement>("#planner-run");
  const steering = root.querySelector<HTMLElement>("#planner-steering");
  if (!output || !select || !button || !steering) return;
  let plans: PlannerPlan[] = [];
  let choices: PlannerChoices | null = null;
  let gameweeks: number[] = [];
  const constraints = emptyConstraints();
  const drawSteering = () => { steering.innerHTML = renderSteering(choices, gameweeks, constraints); };
  drawSteering();
  steering.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest<HTMLButtonElement>("[data-planner-add], [data-planner-remove]") : null;
    if (!target) return;
    if (target.dataset.plannerRemove) {
      const [kind, index] = target.dataset.plannerRemove.split(":");
      if (kind === "force_in" || kind === "force_out" || kind === "keep") removeConstraint(constraints, kind, Number(index));
      drawSteering();
      return;
    }
    const kind = target.dataset.plannerAdd;
    const gwOf = (selector: string): number | null => { const value = steering.querySelector<HTMLSelectElement>(selector)?.value ?? ""; return value ? Number(value) : null; };
    let problem: string | null = null;
    if (kind === "force_in") {
      const player = resolvePlayer(steering.querySelector<HTMLInputElement>("#planner-buy")?.value ?? "", choices);
      problem = player ? addConstraint(constraints, "force_in", player.id, gwOf("#planner-buy-gw")) : "Pick a player from the list to buy.";
    } else if (kind === "force_out" || kind === "keep") {
      const id = Number(steering.querySelector<HTMLSelectElement>(kind === "keep" ? "#planner-keep" : "#planner-sell")?.value || NaN);
      problem = Number.isInteger(id) ? addConstraint(constraints, kind, id, kind === "keep" ? null : gwOf("#planner-sell-gw")) : "Choose one of your players first.";
    }
    if (problem) runtime.status(problem);
    else drawSteering();
  });
  button.addEventListener("click", () => {
    const model = select.value;
    button.disabled = true;
    output.innerHTML = renderPlanner({ phase: "loading", model });
    void fetchPlans(model, constraints).then((result) => {
      plans = result.state === "ready" ? result.plans : [];
      if (result.choices) choices = result.choices;
      if (result.state === "ready") gameweeks = result.gameweeks;
      drawSteering();
      output.innerHTML = renderPlanner({ phase: "done", result });
    }).catch((error: unknown) => {
      output.innerHTML = renderPlanner({ phase: "error", message: error instanceof Error ? error.message : "The planner request failed." });
    }).finally(() => { button.disabled = false; });
  });
  output.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest<HTMLButtonElement>("[data-planner-try]") : null;
    if (!target) return;
    const plan = plans.find((item) => String(item.rank) === target.dataset.plannerTry);
    if (!plan) return;
    const problem = runtime.replacePlan ? runtime.replacePlan(plan.next_gw_moves) : "The planned-transfers board is unavailable.";
    if (problem) runtime.status(problem);
  });
}
