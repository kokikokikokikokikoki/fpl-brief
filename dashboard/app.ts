import { mountDecisionStates } from "./decision-states";
import { mountDeskTools } from "./desk-tools";
import { mountSquadFormation, renderSquadFormation } from "./squad-formation";
import { renderLineupHelper, type LineupData } from "./lineup-helper";
import { mountTacticsBoard, renderTacticsBoard } from "./tactics-board";
import { jerseySvg } from "./kits";
import { addTransfer, loadPlan, planQuery, renderPlanStrip, savePlan, type PlanResult, type PlannedTransfer } from "./transfer-plan";
import "./tactics-board.css";
import "./lineup-helper.css";
import { renderPrivateTeamPanel, renderTeamDecisionDesk } from "./team-decision-desk";
import "@fontsource/barlow/400.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow/700.css";
import "@fontsource/barlow-condensed/700.css";
import "@fontsource/barlow-condensed/800.css";
import "@fontsource/kalam/700.css";
import "./board.css";
import "./squad-formation.css";
import "./team-decision-desk.css";

export type ViewId = "overview" | "squad" | "wildcard" | "rivals" | "players" | "research" | "candidates";
export type DisplayValue = string | number | null | undefined;

export interface Player {
  id: number;
  web_name?: string;
  team?: number;
  element_type?: number;
  status?: string;
  chance_of_playing_next_round?: number | null;
  now_cost?: DisplayValue;
  form?: DisplayValue;
  total_points?: DisplayValue;
  ep_next?: DisplayValue;
  selected_by_percent?: DisplayValue;
  minutes?: DisplayValue;
  xgi_per_90?: DisplayValue;
  fixture_difficulty_average?: DisplayValue;
  availability?: string;
}

export interface Pick {
  element: number;
  position: number;
  element_type?: number;
  is_captain?: boolean;
  is_vice_captain?: boolean;
}

export interface Team {
  id: number;
  name?: string;
  short_name?: string;
}

export interface Catalog {
  players: Player[];
  teams: Team[];
}

export interface Draft {
  id: string;
  name: string;
  target_gw: number;
  players: number[];
  notes: string;
}

export interface TeamDecisionEvidence {
  text: string;
  captured_at_utc?: string | null;
  publisher?: string | null;
  title?: string | null;
  url?: string | null;
  stale: boolean;
  verification: string;
}

export interface TeamDecisionPlayer {
  id?: number | null;
  position?: number | null;
  name?: string | null;
  team?: string | null;
  role?: number | null;
  priority: string;
  reason: string;
  next_step?: string;
  status: string;
  chance?: DisplayValue;
  news: string;
  news_added?: string | null;
  minutes?: DisplayValue;
  form?: DisplayValue;
  total_points?: DisplayValue;
  ep_next?: DisplayValue;
  fixtures: Array<{ gameweek: number; opponent: string; venue: string; difficulty?: DisplayValue }>;
  research: TeamDecisionEvidence[];
}

export type ChipLedgerRow =
  | { name: string; state: "unknown"; reason: string; used_count?: number; used_gameweeks?: number[]; used_source?: string }
  | { name: string; state: "known"; used_count: number; used_gameweeks: number[]; used_source?: string; available_now: number; future_count: number; future_windows: Array<{ start_event: number; stop_event: number; remaining: number }>; season_total: number };

export interface TeamDecisionData {
  generated_at_utc?: string | null;
  snapshot_stale: boolean;
  snapshot_message: string;
  players: TeamDecisionPlayer[];
  research_state: string;
  research_age_hours?: number | null;
  chips: { state: "unknown" | "partial" | "known"; gameweek?: number; reason: string; chips: ChipLedgerRow[] };
}

export interface DashboardData {
  snapshot: {
    generated_at_utc?: string;
    league: {
      rank?: DisplayValue;
      points?: DisplayValue;
      gap_to_leader?: DisplayValue;
      provisional?: boolean;
      leader?: { name?: string } | null;
    };
    availability: Array<{ name: string; chance?: DisplayValue; status?: string; news?: string }>;
    events: { next?: { id?: number; deadline_time?: string } | null; current?: { id?: number; deadline_time?: string } | null };
    squad_snapshot: { event_id?: number | null; bank?: DisplayValue; picks: Pick[] };
    rivals: Array<{
      rank?: DisplayValue;
      name?: string;
      points?: DisplayValue;
      comparison?: { shared?: unknown[] | number; user_only?: unknown[] | number; rival_only?: unknown[] | number };
    }>;
  };
  catalog: Catalog;
  plans: Draft[];
  snapshot_status: { stale: boolean; message?: string; age_hours?: number | null };
  decision: {
    status: string;
    recommendation: { action: string; why: string; alternative: string; what_would_change: string };
    blockers: string[];
    jev: { message: string };
  };
  team_decision: TeamDecisionData;
  private_team?: PrivateTeamData;
  lineup?: LineupData;
  config?: { team_id?: number };
}

export interface PrivateTeamData {
  state: "missing" | "invalid" | "mismatch" | "disabled" | "stale" | "ready";
  message: string;
  usable: boolean;
  captured_at_utc: string | null;
  age_hours: number | null;
  free_transfers?: number | "unlimited";
  transfers_made?: number;
  bank?: number;
  hit_cost?: number;
  team_value?: number;
  chips?: Array<{ name: string; status: string; played_gameweeks: number[]; window: Array<number | null>; pending: boolean }>;
}

export interface AppState {
  data: DashboardData | null;
  active: ViewId;
}

export interface DashboardRuntime {
  state: AppState;
  esc(value: unknown): string;
  activate(view: ViewId): void;
  status(message: string): void;
  /** Optional club shirt renderer keyed by FPL team id. */
  kit?(teamId: number | null | undefined): string;
  /** Add OUT → IN to the browser-local transfer plan and open the board; returns an error message or null. */
  planTransfer?(out: number, incoming: number): string | null;
}

interface StorageLike {
  getItem(key: string): string | null;
}

const DRAFT_KEY = "fpl-brief:drafts:v1";
const SAFE_TEMPLATE: Draft = {
  id: "hold",
  name: "Hold / use 1 FT",
  target_gw: 4,
  players: [],
  notes: "Safe local template; add players from the current catalog.",
};
const positions: Record<number, string> = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };

function required<T extends Element>(selector: string, root: ParentNode = document): T {
  const found = root.querySelector<T>(selector);
  if (!found) throw new Error(`Dashboard element not found: ${selector}`);
  return found;
}

function all<T extends Element>(selector: string, root: ParentNode = document): T[] {
  return Array.from(root.querySelectorAll<T>(selector));
}

export function escapeHtml(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character] ?? character);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validDraft(value: unknown, catalog: Catalog): Draft | null {
  if (!isRecord(value)) return null;
  const name = typeof value.name === "string" ? value.name.trim() : "";
  const targetGameweek = Number(value.target_gw);
  const selected = value.players;
  const known = new Set(catalog.players.map((player) => player.id));
  if (!name || name.length > 80 || !Number.isInteger(targetGameweek) || targetGameweek < 4 || targetGameweek > 7) return null;
  if (!Array.isArray(selected) || selected.some((id) => typeof id !== "number" || !Number.isInteger(id) || id < 1 || !known.has(id))) return null;
  if (new Set(selected).size !== selected.length) return null;
  return {
    id: typeof value.id === "string" && value.id ? value.id : `plan-${Date.now()}`,
    name,
    target_gw: targetGameweek,
    players: [...selected] as number[],
    notes: "",
  };
}

function normalizeDrafts(value: unknown, fallback: Draft[], catalog: Catalog): Draft[] {
  const stored = Array.isArray(value) ? value.map((draft) => validDraft(draft, catalog)).filter((draft): draft is Draft => draft !== null).slice(0, 4) : [];
  if (stored.length) return stored;
  const templates = fallback.map((draft) => validDraft(draft, catalog)).filter((draft): draft is Draft => draft !== null).slice(0, 4);
  return templates.length ? templates : [{ ...SAFE_TEMPLATE, players: [] }];
}

export function readDrafts(fallback: Draft[], catalog: Catalog, storage?: StorageLike | null): Draft[] {
  try {
    const availableStorage = storage === undefined ? window.localStorage : storage;
    if (!availableStorage) return normalizeDrafts(null, fallback, catalog);
    return normalizeDrafts(JSON.parse(availableStorage.getItem(DRAFT_KEY) || "null") as unknown, fallback, catalog);
  } catch {
    return normalizeDrafts(null, fallback, catalog);
  }
}

function writeDrafts(state: AppState): void {
  try {
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify(state.data?.plans.slice(0, 4) ?? []));
  } catch {
    // Keep the draft usable in memory when browser storage is unavailable.
  }
}

function money(value: DisplayValue): string {
  return `£${(Number(value || 0) / 10).toFixed(1)}m`;
}

function formatDate(value?: string): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unknown"
    : `${new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Bangkok" }).format(date)} BKK`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected dashboard error.";
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body: unknown = await response.json();
  if (!response.ok) {
    const message = isRecord(body) && typeof body.error === "string" ? body.error : "Request failed.";
    throw new Error(message);
  }
  return body as T;
}

const state: AppState = { data: null, active: "overview" };

function playerMap(): Map<number, Player> {
  return new Map((state.data?.catalog.players ?? []).map((player) => [player.id, player]));
}

function teamMap(): Map<number, Team> {
  return new Map((state.data?.catalog.teams ?? []).map((team) => [team.id, team]));
}

function isRisky(player?: Player): boolean {
  return !player || player.status !== "a" || (player.chance_of_playing_next_round != null && player.chance_of_playing_next_round < 100);
}

function renderRail(): void {
  const data = state.data;
  if (!data) return;
  const snapshot = data.snapshot;
  const league = snapshot.league;
  required<HTMLElement>("#league-snapshot").classList.remove("skeleton");
  required<HTMLElement>("#league-snapshot").innerHTML = `<div class="league-rank"><strong>${league.rank ?? "—"}</strong><span>/ #club-football</span></div><p class="small">${league.points ?? "—"} pts · ${league.gap_to_leader ?? "—"} behind leader</p><p class="small ${league.provisional ? "warn" : ""}">${league.provisional ? "GW in progress" : "Latest round complete"}</p>`;
  required<HTMLElement>("#nav-alerts").textContent = String(snapshot.availability.length || "");
  required<HTMLElement>("#snapshot-time").textContent = `Snapshot ${formatDate(snapshot.generated_at_utc)}`;
}

function renderOverview(): void {
  const data = state.data;
  if (!data) return;
  const { snapshot } = data;
  const league = snapshot.league;
  const flagged = snapshot.availability;
  const next = snapshot.events.next ?? snapshot.events.current ?? {};
  const actions: Array<{ title: string; text: string; tag: string; cls: string }> = [];
  if (flagged.length) actions.push({ title: `Resolve ${flagged[0].name}'s availability`, text: `FPL lists ${flagged[0].chance ?? "unknown"}% chance. Do not rely on the bench until minutes are clear.`, tag: "Risk", cls: "risk" });
  actions.push({ title: "Protect the next deadline", text: `GW${escapeHtml(next.id ?? "?")} closes ${formatDate(next.deadline_time)}. Your public squad is the baseline, not unsubmitted moves.`, tag: "Plan", cls: "good" });
  actions.push({ title: "Keep differentials intentional", text: "Use the rival view to see shared picks before chasing a popular replacement.", tag: "League", cls: "warn" });
  required<HTMLElement>("#overview").innerHTML = `<div class="decision-strip"><div class="decision-lead"><div class="metric-label">This week's call</div><div class="metric-value">${flagged.length ? "Squad cover first" : "Keep the transfer flexible"}</div><div class="small">${flagged.length ? "Availability risk is the urgent public-snapshot fact." : "No player is currently flagged by FPL."}</div></div><div><div class="metric-label">League position</div><div class="metric-value">${escapeHtml(league.rank ?? "—")}<span class="small"> / 102</span></div><div class="small">${escapeHtml(league.points ?? "—")} pts</div></div><div><div class="metric-label">Leader gap</div><div class="metric-value">${escapeHtml(league.gap_to_leader ?? "—")}</div><div class="small">${escapeHtml(league.leader?.name || "Unknown")}</div></div><div><div class="metric-label">Next deadline</div><div class="metric-value">GW${escapeHtml(next.id ?? "—")}</div><div class="small">${escapeHtml(formatDate(next.deadline_time))}</div></div></div><div class="grid two"><article class="panel"><div class="panel-head"><div><h2>Decision queue</h2><p>Facts to settle before the next transfer chat.</p></div></div><div class="action-list">${actions.map((action, index) => `<div class="action"><span class="action-index">0${index + 1}</span><div><strong>${escapeHtml(action.title)}</strong><p>${escapeHtml(action.text)}</p></div><span class="tag ${action.cls}">${escapeHtml(action.tag)}</span></div>`).join("")}</div></article><article class="panel"><div class="panel-head"><div><h2>Availability desk</h2><p>Official FPL statuses only.</p></div><button class="button-secondary" data-go="squad">Open squad</button></div>${flagged.length ? `<div class="table-wrap"><table><thead><tr><th>Player</th><th>Status</th><th>Chance</th><th>FPL note</th></tr></thead><tbody>${flagged.map((item) => `<tr><td class="player-name">${escapeHtml(item.name)}</td><td>${escapeHtml(item.status)}</td><td>${escapeHtml(item.chance ?? "—")}%</td><td class="small">${escapeHtml(item.news || "No detail")}</td></tr>`).join("")}</tbody></table></div>` : '<div class="empty"><strong>Availability clear</strong><span>No selected player is currently flagged by FPL.</span></div>'}</article></div><div class="grid equal"><article class="panel"><div class="panel-head"><div><h2>Fixture horizon</h2><p>Open the player pool to compare current form and FPL estimates.</p></div><button class="button-secondary" data-go="players">Player pool</button></div><p>The dashboard preserves the six-gameweek FPL fixture horizon in the snapshot and avoids turning fixture difficulty into a fake forecast.</p></article><article class="panel"><div class="panel-head"><div><h2>Wildcard lab</h2><p>Compare timing with clear limitations.</p></div><button class="button-secondary" data-go="wildcard">Compare timing</button></div><p>Save up to four draft squads for GW4–GW7 on this device only; Railway restarts do not erase them here. The lab calculates cost, squad size and availability risk, and displays FPL’s next-round estimate only.</p><p class="method">Future-gameweek projections are manager assumptions, not hidden model outputs.</p></article></div>`;
  required<HTMLElement>("#overview").insertAdjacentHTML("beforeend", renderPrivateTeamPanel(data.private_team, data.config?.team_id) + renderTeamDecisionDesk(data.team_decision, (team, keeper) => jerseySvg(team ?? undefined, keeper)));
}

let planCache: { key: string; result: PlanResult } | null = null;
let planRequest = "";

function safeLocalStorage(): Storage | null {
  try { return window.localStorage; } catch { return null; }
}

function planGameweek(): number | undefined {
  return state.data?.lineup?.gameweek ?? state.data?.snapshot.events.next?.id;
}

function currentPlan(): PlannedTransfer[] {
  const gameweek = planGameweek();
  if (!state.data || gameweek === undefined) return [];
  return loadPlan(safeLocalStorage(), gameweek, new Set((state.data.snapshot.squad_snapshot.picks ?? []).map((pick) => pick.element)));
}

function setPlan(plan: PlannedTransfer[]): void {
  const gameweek = planGameweek();
  if (gameweek === undefined) return;
  savePlan(safeLocalStorage(), gameweek, plan);
  renderSquad();
}

function planTransfer(out: number, incoming: number): string | null {
  const result = addTransfer(currentPlan(), { out, in: incoming });
  if (result.error) return result.error;
  setPlan(result.plan);
  activate("squad");
  return null;
}

function renderSquad(): void {
  const data = state.data;
  if (!data) return;
  const snapshot = data.snapshot;
  const picks = snapshot.squad_snapshot.picks ?? [];
  const target = required<HTMLElement>("#squad");
  const plan = currentPlan();
  // The plan depends on the squad, prices and account capture, so cache it per data version too.
  const key = `${planQuery(plan)}|${snapshot.generated_at_utc ?? ""}|${data.private_team?.captured_at_utc ?? ""}`;
  let lineup = data.lineup;
  let result: PlanResult | null = null;
  if (plan.length) {
    if (planCache?.key === key) {
      result = planCache.result;
      if (result.state === "ready") lineup = result.lineup as LineupData;
    } else if (planRequest !== key) {
      planRequest = key;
      fetch(`/api/plan?transfers=${encodeURIComponent(planQuery(plan))}`)
        .then(async (response) => (await response.json()) as PlanResult)
        .catch((): PlanResult => ({ state: "invalid", reason: "The plan could not be checked. Is the dashboard server running?" }))
        .then((answer) => { planCache = { key, result: answer }; planRequest = ""; if (planQuery(currentPlan()) === planQuery(plan)) renderSquad(); });
    }
  }
  const names = new Map(data.catalog.players.map((player) => [player.id, player.web_name ?? `Player ${player.id}`]));
  target.innerHTML = renderPlanStrip(plan, result, names) + renderTacticsBoard(lineup, data.private_team)
    + `<details class="panel lineup-list"><summary>Show this week's lineup as a list, with every reason</summary>${renderLineupHelper(lineup, data.team_decision?.players ?? [])}</details>`
    + `<details class="panel saved-squad"><summary>Your saved squad from the public snapshot (last deadline)</summary>` + renderSquadFormation({
    picks,
    players: data.catalog.players,
    teams: data.catalog.teams,
    jersey: (team, keeper) => jerseySvg(team, keeper),
    gameweek: snapshot.squad_snapshot.event_id,
    generatedAt: snapshot.generated_at_utc,
    bank: snapshot.squad_snapshot.bank,
  }) + "</details>";
  mountSquadFormation(target);
  mountTacticsBoard(target, lineup, data.team_decision?.players ?? []);
  target.querySelectorAll<HTMLButtonElement>("[data-remove-out]").forEach((button) => {
    button.onclick = () => setPlan(currentPlan().filter((move) => move.out !== Number(button.dataset.removeOut)));
  });
  target.querySelector<HTMLButtonElement>(".plan-clear")?.addEventListener("click", () => setPlan([]));
}

function renderWildcard(): void {
  const data = state.data;
  if (!data) return;
  const players = playerMap();
  const card = (plan: Draft) => {
    const ids = plan.players;
    const cost = ids.reduce((sum, id) => sum + Number(players.get(id)?.now_cost || 0), 0);
    const estimate = ids.reduce((sum, id) => sum + Number(players.get(id)?.ep_next || 0), 0);
    const risks = ids.filter((id) => isRisky(players.get(id))).length;
    return `<article class="scenario" data-plan="${escapeHtml(plan.id)}"><input class="plan-name" value="${escapeHtml(plan.name)}" aria-label="Scenario name"><label class="small">Target gameweek <select class="target-gw">${[4, 5, 6, 7].map((gameweek) => `<option ${plan.target_gw === gameweek ? "selected" : ""}>${gameweek}</option>`).join("")}</select></label><dl><dt>Squad</dt><dd>${ids.length}/15</dd><dt>Cost</dt><dd>${money(cost)}</dd><dt>GW next estimate</dt><dd>${estimate.toFixed(1)}</dd><dt>Availability risks</dt><dd class="${risks ? "risk" : "good"}">${risks}</dd></dl><label class="small">Player IDs (comma-separated)<input class="plan-players" value="${ids.join(",")}" aria-label="Player IDs"></label><button class="button-secondary save-plan">Save scenario</button></article>`;
  };
  required<HTMLElement>("#wildcard").innerHTML = `<div class="panel"><div class="panel-head"><div><h2>Wildcard timing lab</h2><p>Compare a squad draft—not an invented multi-week projection.</p></div><button id="add-plan" class="button-primary">Add scenario</button></div><div class="scenario-grid">${data.plans.map(card).join("")}</div><p class="method">Cost and risk are calculated from saved player IDs. “GW next estimate” is the sum of FPL’s official <code>ep_next</code> today, regardless of target week. It is a short-horizon baseline—not a GW4–GW7 forecast. Player IDs are visible in the Player pool via the browser data endpoint for now; next iteration can add a visual player picker.</p></div>`;
}

function renderRivals(): void {
  const rivals = state.data?.snapshot.rivals ?? [];
  const league = state.data?.snapshot.league;
  const count = (value: unknown) => (Array.isArray(value) ? value.length : typeof value === "number" ? value : null);
  const rankOf = (value: unknown) => { const rank = Number(value); return Number.isFinite(rank) ? rank : 9999; };
  const rows = rivals.map((rival) => ({ rank: rankOf(rival.rank), html: `<tr><td>${escapeHtml(rival.rank ?? "—")}</td><td class="player-name">${escapeHtml(rival.name || "Unknown")}</td><td>${escapeHtml(rival.points ?? "—")}</td><td>${escapeHtml(count(rival.comparison?.shared) ?? "—")}</td><td>${escapeHtml(count(rival.comparison?.user_only) ?? "—")}</td></tr>` }));
  if (league?.rank != null) rows.push({ rank: rankOf(league.rank), html: `<tr class="you-row"><td>${escapeHtml(league.rank)}</td><td class="player-name"><span class="hand-underline">You</span></td><td>${escapeHtml(league.points ?? "—")}</td><td>—</td><td>—</td></tr>` });
  rows.sort((a, b) => a.rank - b.rank);
  required<HTMLElement>("#rivals").innerHTML = `<article class="panel"><div class="panel-head"><div><h2>#club-football rivals</h2><p>Only public squad snapshots. Absence is not a confirmed sell.</p></div></div><div class="table-wrap"><table><caption>Both squads have 15 players, so each side holds the same number of differentials.</caption><thead><tr><th>Rank</th><th>Manager</th><th>Points</th><th>Shared players</th><th>Differentials (each side)</th></tr></thead><tbody>${rows.map((row) => row.html).join("")}</tbody></table></div></article>`;
}

function renderPlayerPool(): void {
  const data = state.data;
  if (!data) return;
  const teams = teamMap();
  const players = [...data.catalog.players].sort((left, right) => Number(right.total_points || 0) - Number(left.total_points || 0)).slice(0, 80);
  required<HTMLElement>("#players").innerHTML = `<article class="panel"><div class="panel-head"><div><h2>Player pool</h2><p>Top public FPL scorers. Investigate rather than chase last week’s points.</p></div></div><div class="table-wrap"><table><thead><tr><th>Pos</th><th>Player</th><th>Price</th><th>Form</th><th>Pts</th><th>Own</th><th>GW estimate</th></tr></thead><tbody>${players.map((player) => `<tr><td>${positions[player.element_type ?? 0] ?? "?"}</td><td><span class="row-kit">${jerseySvg(player.team ? teams.get(player.team)?.short_name : undefined, player.element_type === 1)}</span><span class="player-name">${escapeHtml(player.web_name)}</span><span class="sub">${escapeHtml((player.team ? teams.get(player.team)?.short_name : "") || "")}</span></td><td>${money(player.now_cost)}</td><td>${player.form ?? "—"}</td><td>${player.total_points ?? "—"}</td><td>${player.selected_by_percent ?? "—"}%</td><td>${player.ep_next ?? "—"}</td></tr>`).join("")}</tbody></table></div></article>`;
}

let deskTools: ReturnType<typeof mountDeskTools>;
let refreshDecisionStates: () => void;

function render(): void {
  if (!state.data) return;
  renderRail();
  renderOverview();
  renderSquad();
  renderWildcard();
  renderRivals();
  renderPlayerPool();
  all<HTMLElement>(".view").forEach((view) => view.classList.toggle("active", view.id === state.active));
  all<HTMLButtonElement>(".nav-link").forEach((button) => button.classList.toggle("active", button.dataset.view === state.active));
  const gameweek = state.data?.lineup?.gameweek ?? state.data?.snapshot.events.next?.id;
  const titles: Record<string, string> = { overview: "This week", squad: gameweek ? `Gameweek ${gameweek} lineup` : "Lineup", wildcard: "Wildcard lab", rivals: "Rivals", players: "Player pool", research: "Research desk", candidates: "Candidate lens" };
  required<HTMLElement>("main h1").textContent = titles[state.active] ?? "FPL Brief";
  all<HTMLButtonElement>("[data-go]").forEach((button) => {
    button.onclick = () => activate(button.dataset.go as ViewId);
  });
  all<HTMLButtonElement>(".save-plan").forEach((button) => { button.onclick = saveDraft; });
  const addPlan = document.querySelector<HTMLButtonElement>("#add-plan");
  addPlan?.addEventListener("click", addDraft);
  refreshDecisionStates();
}

function activate(view: ViewId): void {
  state.active = view;
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function status(message: string): void {
  required<HTMLElement>("#refresh-status").textContent = message;
  window.setTimeout(() => { required<HTMLElement>("#refresh-status").textContent = ""; }, 3500);
}

function saveDraft(event: MouseEvent): void {
  const button = event.currentTarget;
  if (!(button instanceof HTMLButtonElement)) return;
  const card = button.closest<HTMLElement>(".scenario");
  if (!card || !state.data) return;
  const name = required<HTMLInputElement>(".plan-name", card).value.trim();
  const targetGameweek = Number(required<HTMLSelectElement>(".target-gw", card).value);
  const tokens = required<HTMLInputElement>(".plan-players", card).value.split(",").map((value) => value.trim()).filter(Boolean);
  const selected = tokens.map(Number);
  const known = new Set(state.data.catalog.players.map((player) => player.id));
  if (!name || name.length > 80) return status("Scenario name is required and must be 80 characters or fewer.");
  if (!Number.isInteger(targetGameweek) || targetGameweek < 4 || targetGameweek > 7) return status("Target gameweek must be 4–7.");
  if (selected.some((id) => !Number.isInteger(id) || id < 1) || new Set(selected).size !== selected.length || selected.some((id) => !known.has(id))) return status("Use unique positive player IDs from the current catalog.");
  const plan: Draft = { id: card.dataset.plan || `plan-${Date.now()}`, name, target_gw: targetGameweek, players: selected, notes: "" };
  state.data.plans = state.data.plans.filter((item) => item.id !== plan.id).concat(plan);
  writeDrafts(state);
  status("Scenario saved on this device only.");
  render();
}

function addDraft(): void {
  if (!state.data) return;
  if (state.data.plans.length >= 4) return status("Keep the lab to four scenarios.");
  const index = state.data.plans.length;
  const base = state.data.plans[0]?.players ?? [];
  state.data.plans.push({ id: `plan-${Date.now()}`, name: `Wildcard GW${4 + index}`, target_gw: 4 + index, players: base, notes: "" });
  writeDrafts(state);
  render();
}

async function refreshSnapshot(): Promise<void> {
  const button = required<HTMLButtonElement>("#refresh");
  button.disabled = true;
  status("Refreshing public FPL data…");
  try {
    const start = await requestJson<{ id: string; status: string; message?: string }>("/api/refresh", { method: "POST" });
    let job = start;
    while (job.status === "running") {
      await new Promise((resolve) => window.setTimeout(resolve, 1400));
      job = await requestJson<{ id: string; status: string; message?: string }>(`/api/jobs/${encodeURIComponent(job.id)}`);
    }
    if (job.status !== "complete") throw new Error(job.message || "Refresh failed.");
    status("Snapshot refreshed.");
    await loadDashboard();
  } catch (error) {
    status(`Refresh failed: ${errorMessage(error)}`);
  } finally {
    button.disabled = false;
  }
}

async function importAccount(): Promise<void> {
  const box = document.querySelector<HTMLTextAreaElement>("#account-paste");
  const note = document.querySelector<HTMLElement>("#account-import-status");
  if (!box || !note) return;
  const text = box.value.trim();
  try {
    JSON.parse(text);
  } catch {
    note.textContent = "That isn't the FPL data yet. Open the link, select all (Ctrl+A), copy, and paste the whole thing here.";
    note.className = "import-status bad";
    return;
  }
  note.textContent = "Importing…";
  note.className = "import-status";
  try {
    const summary = await requestJson<PrivateTeamData>("/api/private-team", { method: "POST", headers: { "Content-Type": "application/json" }, body: text });
    await loadDashboard();
    status(`FPL account imported: ${summary.free_transfers ?? "?"} free transfers, ${money(summary.bank)} in the bank.`);
  } catch (error) {
    note.textContent = errorMessage(error);
    note.className = "import-status bad";
  }
}

async function loadDashboard(): Promise<void> {
  try {
    const data = await requestJson<DashboardData>("/api/dashboard");
    data.plans = readDrafts(data.plans, data.catalog);
    state.data = data;
    render();
  } catch (error) {
    required<HTMLElement>("main").innerHTML = `<div class="empty"><strong>Dashboard unavailable.</strong><span>${escapeHtml(errorMessage(error))} Run fetch_fpl.py, then reload.</span></div>`;
  }
}

const runtime: DashboardRuntime = { state, esc: escapeHtml, activate, status, planTransfer, kit: (teamId) => jerseySvg(teamId ? teamMap().get(teamId)?.short_name : undefined) };
deskTools = mountDeskTools(runtime);
refreshDecisionStates = mountDecisionStates(() => state.data);

document.addEventListener("click", (event: MouseEvent) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.closest("#account-import")) {
    void importAccount();
    return;
  }
  const compare = target.closest<HTMLButtonElement>("[data-compare-player]");
  if (compare) {
    const playerId = Number(compare.dataset.comparePlayer);
    if (Number.isInteger(playerId) && playerId > 0) deskTools.openLens(playerId);
    return;
  }
  const button = target.closest<HTMLButtonElement>(".nav-link");
  if (!button?.dataset.view) return;
  const view = button.dataset.view as ViewId;
  if (view === "research") void deskTools.openResearch();
  else if (view === "candidates") deskTools.openLens();
  else activate(view);
});
required<HTMLButtonElement>("#refresh").addEventListener("click", () => { void refreshSnapshot(); });
void loadDashboard();
