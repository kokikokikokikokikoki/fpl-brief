// Browser-local transfer plans tried on the tactics board. Never sent to FPL.
export interface PlannedTransfer { out: number; in: number }
export interface StorageLike { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void }
export interface PlanSummary {
  transfers: Array<{ out: { id: number; name: string; selling_price: number }; in: { id: number; name: string; price: number } }>;
  budget_left: number;
  free_transfers: number | "unlimited" | null;
  paid_transfers: number;
  hit_points: number;
  xi_delta: number;
  net_delta: number;
  method: string;
}
export type PlanResult = { state: "ready"; summary: PlanSummary; lineup: unknown } | { state: "invalid"; reason: string };

export const MAX_PLANNED = 3;

function esc(value: unknown): string {
  return String(value ?? "—").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
}

export function planKey(gameweek: number): string {
  return `fpl-brief:plan:v1:gw${gameweek}`;
}

/** Load a saved plan; drop it entirely if it no longer fits the current squad. */
export function loadPlan(storage: StorageLike | null | undefined, gameweek: number, owned: Set<number>): PlannedTransfer[] {
  try {
    const raw = storage?.getItem(planKey(gameweek));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length > MAX_PLANNED) return [];
    const plan = parsed.filter((item): item is PlannedTransfer => !!item && Number.isInteger(item.out) && Number.isInteger(item.in));
    const outs = new Set(plan.map((t) => t.out)), ins = new Set(plan.map((t) => t.in));
    const valid = plan.length === parsed.length && outs.size === plan.length && ins.size === plan.length
      && plan.every((t) => owned.has(t.out) && !owned.has(t.in));
    return valid ? plan : [];
  } catch {
    return [];
  }
}

export function savePlan(storage: StorageLike | null | undefined, gameweek: number, plan: PlannedTransfer[]): void {
  try {
    if (!storage) return;
    if (plan.length) storage.setItem(planKey(gameweek), JSON.stringify(plan));
    else storage.removeItem(planKey(gameweek));
  } catch {
    /* Storage unavailable: the plan lasts for this visit only. */
  }
}

/** Add or replace the move for one outgoing player; returns an error message when the plan is full. */
export function addTransfer(plan: PlannedTransfer[], move: PlannedTransfer): { plan: PlannedTransfer[]; error?: string } {
  const rest = plan.filter((t) => t.out !== move.out && t.in !== move.in);
  if (rest.length >= MAX_PLANNED) return { plan, error: `Plan at most ${MAX_PLANNED} transfers at once. Remove one first.` };
  return { plan: [...rest, move] };
}

export function planQuery(plan: PlannedTransfer[]): string {
  return plan.map((t) => `${t.out}:${t.in}`).join(",");
}

const money = (tenths: number) => `£${(tenths / 10).toFixed(1)}m`;
const signed = (value: number) => `${value >= 0 ? "+" : ""}${value}`;

export function renderPlanStrip(plan: PlannedTransfer[], result: PlanResult | null, names: Map<number, string>): string {
  if (!plan.length) return "";
  const moves = plan.map((t) => `<li><span class="plan-out">${esc(names.get(t.out) ?? `Player ${t.out}`)}</span><span aria-hidden="true"> → </span><span class="visually-hidden"> replaced by </span><span class="plan-in">${esc(names.get(t.in) ?? `Player ${t.in}`)}</span><button class="plan-remove" type="button" data-remove-out="${esc(t.out)}" aria-label="Remove the ${esc(names.get(t.out) ?? "")} transfer">×</button></li>`).join("");
  let body = '<p class="plan-status">Checking the plan…</p>';
  if (result?.state === "invalid") body = `<p class="plan-status plan-bad" role="alert">${esc(result.reason)}</p>`;
  if (result?.state === "ready") {
    const s = result.summary;
    const free = s.free_transfers === "unlimited" ? "unlimited free transfers" : `${s.transfers.length - s.paid_transfers} of ${s.free_transfers ?? 0} free transfers`;
    body = `<p class="plan-status"><strong>${esc(signed(s.net_delta))}</strong> FPL estimate next GW after hits · ${esc(free)}${s.hit_points ? ` · <span class="plan-bad">hit −${esc(s.hit_points)}</span>` : ""} · ${esc(money(s.budget_left))} left</p><p class="plan-fine">${esc(s.method)} The board below shows the best XI with these transfers.</p>`;
  }
  return `<section class="plan-strip" aria-label="Planned transfers"><div class="plan-head"><h3>Planned transfers</h3><button class="plan-clear button-secondary" type="button">Clear plan</button></div><ul class="plan-moves">${moves}</ul>${body}</section>`;
}
