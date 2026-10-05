// League threats (your squad against the top of the mini-league) and the fixture ticker.
import { jerseySvg } from "./kits";

interface Game { opponent: string; venue: "H" | "A"; difficulty: number | null; kickoff: string | null }
interface TickerCell { gameweek: number; games: Game[]; break_before: boolean }
interface TickerRow { team_id: number; team: string | null; name: string | null; cells: TickerCell[]; next4: number | null; yours: string[] }
export interface TickerData { gameweeks: number[]; rows: TickerRow[]; method: string }

interface ThreatPlayer { id: number; name: string; team: string | null; rivals: number; captained: number; ownership: string | null }
interface Chip { name: string; label: string; expires?: number; gameweek?: number }
interface RivalRow { entry_id: number; is_you: boolean; name: string | null; manager: string | null; rank: number | null; total: number | null; gap: number; captain: string | null; shared: number | null; bank: number | null; chips_left: Chip[]; chips_used: Chip[] }
export type ThreatsData =
  | { state: "unavailable"; reason: string }
  | {
    state: "ready"; gameweek: number; chip_week: number; rivals_compared: number; you: { rank: number | null; total: number | null };
    leader: { name: string | null; gap: number }; missing: ThreatPlayer[]; shared: ThreatPlayer[]; differentials: ThreatPlayer[];
    captains: ThreatPlayer[]; table: RivalRow[]; warnings: string[]; method: string;
  };

function esc(value: unknown): string {
  return String(value ?? "—").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
}
const fdr = (value: number | null) => (Number.isInteger(value) && Number(value) >= 1 && Number(value) <= 5 ? Number(value) : 0);
const shortDate = (iso: string | null) => {
  const date = iso ? new Date(iso) : null;
  return date && Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "Asia/Bangkok" }).format(date) : "";
};

function playerList(rows: ThreatPlayer[], total: number, empty: string, note: (row: ThreatPlayer) => string): string {
  if (!rows.length) return `<p class="fine">${esc(empty)}</p>`;
  return `<ul class="lt-list">${rows.map((r) => `<li><span class="row-kit">${jerseySvg(r.team)}</span><span><strong>${esc(r.name)}</strong> <span class="sub">${esc(r.team)} · ${esc(note(r))}</span></span><span class="lt-count" aria-label="${esc(`${r.rivals} of ${total} rivals`)}">${esc(r.rivals)}/${esc(total)}</span></li>`).join("")}</ul>`;
}

function chipBadges(chips: Chip[]): string {
  return chips.length ? chips.map((c) => `<span class="lt-chip">${esc(c.label)}</span>`).join("") : '<span class="sub">none left</span>';
}

export function renderThreats(data: ThreatsData | null, loading: boolean, error = ""): string {
  const head = '<div class="panel-head"><div><h2>League threats</h2><p>Your squad against the top of #club-football.</p></div></div>';
  if (!data) return `<article class="panel lt">${head}<p class="${error ? "evidence-warning" : "fine"}">${esc(error || (loading ? "Loading your rivals' squads from FPL…" : "Open this view to load live league data."))}</p></article>`;
  if (data.state !== "ready") return `<article class="panel lt">${head}<p class="evidence-warning">${esc(data.reason)}</p></article>`;
  const n = data.rivals_compared;
  const gap = data.leader.gap;
  const captains = data.captains.map((c) => `${esc(c.name)} ×${esc(c.captained)}`).join(", ") || "—";
  const chipsHeld = data.table.filter((r) => !r.is_you && r.chips_left.length >= 3).map((r) => r.name);
  const rows = data.table.map((r) => `<tr${r.is_you ? ' class="is-you"' : ""}><td>${esc(r.rank)}</td><td><span class="player-name">${esc(r.name)}</span><span class="sub">${r.is_you ? "you" : `${esc(r.shared)} of your 15 · C ${esc(r.captain)}`}</span></td><td>${esc(r.total)}</td><td class="${r.gap > 0 ? "lt-ahead" : r.gap < 0 ? "lt-behind" : ""}">${r.is_you ? "—" : `${r.gap > 0 ? "+" : ""}${esc(r.gap)}`}</td><td>${chipBadges(r.chips_left)}</td></tr>`).join("");
  return `<article class="panel lt" aria-labelledby="lt-title">
    <div class="panel-head"><div><h2 id="lt-title">League threats</h2><p>Your squad against the top ${esc(n)} of #club-football (GW${esc(data.gameweek)} squads).</p></div></div>
    <p class="hand lt-summary">${gap > 0 ? `${esc(gap)} behind the leader (${esc(data.leader.name)}).` : "You lead the league."} Last week's captains: ${captains}.${chipsHeld.length ? ` Still holding 3+ chips: ${chipsHeld.map(esc).join(", ")}.` : ""}</p>
    <div class="lt-grid">
      <section><h3 class="lt-h red">They have, you don't</h3><p class="fine">Owned by at least half of them. If these score, you drop.</p>${playerList(data.missing, n, "No big gaps: you own everyone they lean on.", (r) => `${r.ownership ?? "—"}% overall`)}</section>
      <section><h3 class="lt-h green">Your differentials</h3><p class="fine">Owned by one rival at most. If these score, you climb.</p>${playerList(data.differentials, n, "No differentials: your squad matches theirs.", (r) => `${r.ownership ?? "—"}% overall`)}</section>
      <section><h3 class="lt-h">Your shield</h3><p class="fine">You and most of them own these, so they don't move the table.</p>${playerList(data.shared, n, "Nothing widely shared.", (r) => (r.captained ? `captained by ${r.captained}` : `${r.ownership ?? "—"}% overall`))}</section>
    </div>
    <h3 class="lt-h">Chips still in hand (GW${esc(data.chip_week)} window)</h3>
    <div class="table-wrap"><table class="lt-table"><thead><tr><th>#</th><th>Manager</th><th>Pts</th><th>Gap</th><th>Chips left</th></tr></thead><tbody>${rows}</tbody></table></div>
    ${data.warnings.length ? `<p class="fine">${data.warnings.map(esc).join(" ")}</p>` : ""}
    <p class="method">${esc(data.method)}</p>
  </article>`;
}

export function renderTicker(data: TickerData | undefined): string {
  if (!data?.rows.length) return '<article class="panel"><div class="panel-head"><div><h2>Fixture ticker</h2></div></div><p class="fine">No upcoming fixtures in the snapshot yet.</p></article>';
  const head = data.gameweeks.map((gw) => `<th scope="col">GW${esc(gw)}</th>`).join("");
  const body = data.rows.map((row) => {
    const cells = row.cells.map((cell) => {
      const games = cell.games.length
        ? cell.games.map((g) => `<span class="tk-game fdr-${fdr(g.difficulty)}">${esc(g.opponent)} <small>${esc(g.venue)}</small><span class="tk-date">${esc(shortDate(g.kickoff))}</span></span>`).join("")
        : '<span class="tk-game tk-blank">blank</span>';
      return `<td class="${cell.break_before ? "tk-break" : ""}${cell.games.length > 1 ? " tk-double" : ""}">${cell.break_before ? '<span class="tk-break-label">break</span>' : ""}${games}</td>`;
    }).join("");
    return `<tr${row.yours.length ? ' class="tk-yours"' : ""}><th scope="row"><span class="row-kit">${jerseySvg(row.team)}</span><span class="player-name">${esc(row.team)}</span><span class="sub">${row.yours.length ? esc(row.yours.join(", ")) : "&nbsp;"}</span></th><td class="tk-avg fdr-${fdr(row.next4 === null ? null : Math.round(row.next4))}">${esc(row.next4 ?? "—")}</td>${cells}</tr>`;
  }).join("");
  return `<article class="panel tk" aria-labelledby="tk-title">
    <div class="panel-head"><div><h2 id="tk-title">Fixture ticker</h2><p>Easiest next four at the top. Rows in bold hold your players.</p></div></div>
    <div class="table-wrap"><table class="tk-table"><thead><tr><th scope="col">Club</th><th scope="col">Next 4</th>${head}</tr></thead><tbody>${body}</tbody></table></div>
    <p class="method">${esc(data.method)}</p>
  </article>`;
}

export interface WatchRow {
  id: number; name: string; team: string | null; keeper: boolean; price: number | null; status: string; chance: number | null; news: string;
  minutes: number | null; ownership: string | null; from_gw: number; to_gw: number; note: string; trigger: string;
  window: "early" | "open" | "passed" | "unknown"; owned: boolean; weeks_until: number;
}

const WINDOW: Record<string, string> = { early: "Not yet", open: "Window open", passed: "Window passed", unknown: "—" };

/** "Ones to watch": players to buy in a target gameweek window, with today's official status beside the plan. */
export function renderWatchlist(rows: WatchRow[] | undefined): string {
  if (!rows?.length) return "";
  const items = rows.map((r) => {
    const when = r.window === "early" ? `GW${esc(r.from_gw)}–${esc(r.to_gw)} · in ${esc(r.weeks_until)} week${r.weeks_until === 1 ? "" : "s"}` : `GW${esc(r.from_gw)}–${esc(r.to_gw)}`;
    const price = typeof r.price === "number" ? `£${(r.price / 10).toFixed(1)}m` : "—";
    const status = r.status === "available" ? `available · ${esc(r.minutes ?? 0)} min so far` : `${esc(r.status)}${r.chance !== null ? ` (${esc(r.chance)}%)` : ""}`;
    return `<li class="watch-${esc(r.window)}"><span class="row-kit">${jerseySvg(r.team, r.keeper)}</span><div class="wl-body">
      <p class="wl-head"><strong>${esc(r.name)}</strong> <span class="sub">${esc(r.team)} · ${esc(price)} · ${esc(r.ownership ?? "—")}% owned${r.owned ? " · in your squad" : ""}</span></p>
      <p class="wl-status"><span class="wl-window">${esc(WINDOW[r.window] ?? r.window)}</span> ${when} · FPL: ${status}</p>
      ${r.news ? `<p class="fine">FPL news: ${esc(r.news)}</p>` : ""}
      ${r.note ? `<p>${esc(r.note)}</p>` : ""}
      ${r.trigger ? `<p class="hand blue">${esc(r.trigger)}</p>` : ""}
    </div></li>`;
  }).join("");
  return `<article class="panel wl" aria-labelledby="wl-title"><div class="panel-head"><div><h2 id="wl-title">Ones to watch</h2><p>Players to buy later, with the gameweek we're aiming for and today's official status.</p></div></div><ul class="wl-list">${items}</ul><p class="method">Saved in config.json (shared on every device). The status comes from the latest FPL snapshot.</p></article>`;
}
