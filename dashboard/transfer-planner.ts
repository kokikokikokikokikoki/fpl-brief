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
}
export type PlannerResult =
  | { state: "ready"; model: string; model_label: string; gameweeks: number[]; hold: { horizon_xp: number; weeks: PlannerWeek[] }; plans: PlannerPlan[]; method: string; caveats: string[]; solve_seconds?: number }
  | { state: "blocked" | "unavailable" | "infeasible"; reason: string };
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

function planCard(plan: PlannerPlan, gameweeks: number[]): string {
  const first = gameweeks[0];
  const span = gameweeks.length ? `GW${gameweeks[0]}–${gameweeks[gameweeks.length - 1]}` : "the horizon";
  const moves = plan.next_gw_moves ?? [];
  const tryButton = moves.length
    ? `<button class="button-secondary" type="button" data-planner-try="${esc(plan.rank)}">Try GW${esc(first)} moves on board</button>`
    : `<p class="small">No moves in GW${esc(first)}: this plan rolls the free transfer now.</p>`;
  const laterNote = gameweeks.length > 1 ? `<p class="small">${esc(`Moves after GW${first} are indicative — re-run the planner each week.`)}</p>` : "";
  const timing = plan.status === "time_limit" ? '<p class="small plan-bad">Stopped at the time limit: best plan found, not proven best.</p>' : "";
  return `<article class="planner-card" aria-label="Plan ${esc(plan.rank)}"><header><h3>Plan ${esc(plan.rank)} · GW${esc(first)}: ${esc(plan.next_gw_action ?? (moves.length ? `${moves.length} move(s)` : "Roll the free transfer (no moves)"))}</h3>${plan.most_points ? '<p class="planner-most">Most estimated points</p>' : ""}<p class="planner-gain">Points gain vs holding: <strong>${esc(signed(plan.gain))}</strong> over ${esc(span)} <span class="small">(XI and captain, decayed estimate, after hits)</span></p>${scoreLine(plan)}<p class="small">Hits: ${plan.hit_points ? `<span class="plan-bad">−${esc(plan.hit_points)}</span>` : "none"} · horizon estimate ${esc(plan.horizon_xp)}${typeof plan.gain_undecayed === "number" ? ` · undecayed gain ${esc(signed(plan.gain_undecayed))}` : ""}</p></header>${timing}<div class="table-wrap"><table class="planner-weeks"><thead><tr><th>GW</th><th>Moves (out → in, prices)</th><th>FTs</th><th>Hits</th><th>Bank after</th><th>XI estimate</th><th>Captain</th></tr></thead><tbody>${weekRows(plan)}</tbody></table></div>${laterNote}${tryButton}</article>`;
}

export function renderPlanner(view: PlannerView): string {
  if (view.phase === "idle") return '<p class="small">Suggests up to three transfer plans over the next six GWs from your account\'s selling prices, bank and free transfers. It is an optimisation over estimates, not advice; chips are not included.</p>';
  if (view.phase === "loading") return `<p class="plan-status" role="status">Solving with ${esc(MODEL_NAMES[view.model] ?? view.model)}… this can take up to half a minute.</p>`;
  if (view.phase === "error") return `<div class="evidence-warning" role="alert">${esc(view.message)}</div>`;
  const result = view.result;
  if (result.state !== "ready") {
    if (result.state === "unavailable") {
      return `<div class="evidence-warning" role="alert"><strong>Planner unavailable here.</strong> The planner runs on your own computer, next to your account data. Install it with <code>pip install -r requirements-planner.txt</code> and use the local dashboard. <span class="small">(${esc(result.reason)})</span></div>`;
    }
    const title = result.state === "infeasible" ? "No legal plan" : "Planner blocked";
    return `<div class="evidence-warning" role="alert"><strong>${esc(title)}.</strong> ${esc(result.reason)}</div>`;
  }
  const note = `<p class="method">Optimisation over estimates, not advice. Model: <strong>${esc(result.model_label)}</strong>. Chips are not included. ${esc(result.method)}${result.caveats.length ? ` ${result.caveats.map(esc).join(" ")}` : ""}</p>`;
  const cards = result.plans.length ? result.plans.map((plan) => planCard(plan, result.gameweeks)).join("") : '<div class="empty"><strong>No plan found</strong><span>No plan could be found for these rules.</span></div>';
  const gw = result.gameweeks[0];
  return `<p class="small">Holding scores ${esc(result.hold.horizon_xp)} points over the horizon (decayed estimate). Plans are ranked by planner score: points, minus hits and a small per-transfer threshold, plus a one-time value for free transfers and bank kept at the end. Each later plan is the best one with a different GW${esc(gw)} action, so a lower-ranked plan can gain more points. Fewer than three cards means fewer distinct GW${esc(gw)} options were possible.</p><div class="planner-cards">${cards}</div>${note}`;
}

async function fetchPlans(model: string): Promise<PlannerResult> {
  const response = await fetch(`/api/optimise?model=${encodeURIComponent(model)}`);
  const body: unknown = await response.json();
  if (typeof body === "object" && body !== null && "state" in body) return body as PlannerResult;
  const error = typeof body === "object" && body !== null && "error" in body && typeof body.error === "string" ? body.error : "The planner request failed.";
  throw new Error(error);
}

/** Render the panel into ``root`` and wire its controls. */
export function mountPlanner(root: HTMLElement, runtime: PlannerRuntime): void {
  root.innerHTML = `<div class="panel-head"><div><h2>Transfer planner</h2><p>Top three multi-week plans from estimates. Read-only: nothing is sent to FPL.</p></div></div><div class="lens-controls"><label>Expected points model<select id="planner-model"><option value="own">Our model (planner default)</option><option value="fpl">FPL-based (ep_next re-weighted)</option></select></label><button id="planner-run" class="button-primary" type="button">Suggest plans</button></div><div id="planner-output" class="lens-output">${renderPlanner({ phase: "idle" })}</div>`;
  const output = root.querySelector<HTMLElement>("#planner-output");
  const select = root.querySelector<HTMLSelectElement>("#planner-model");
  const button = root.querySelector<HTMLButtonElement>("#planner-run");
  if (!output || !select || !button) return;
  let plans: PlannerPlan[] = [];
  button.addEventListener("click", () => {
    const model = select.value;
    button.disabled = true;
    output.innerHTML = renderPlanner({ phase: "loading", model });
    void fetchPlans(model).then((result) => {
      plans = result.state === "ready" ? result.plans : [];
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
