// Matchday: live gameweek points on the board, a live mini-league table and "points left on the table".
import { jerseySvg } from "./kits";

type Role = "GK" | "DEF" | "MID" | "FWD";
export interface ScoreRow {
  id: number; name: string; team: string | null; role: Role | "?"; position: number;
  points: number; provisional_bonus: number; minutes: number; state: "yet" | "playing" | "done";
  starter: boolean; sub_in: boolean; sub_out: boolean; counts: boolean; multiplier: number; armband: boolean;
  is_captain: boolean; is_vice: boolean;
}
interface Scored { rows: ScoreRow[]; total: number; chip: string | null; bench_points: number; played: number; to_play: number; hits: number }
interface LeagueRow { entry_id: number; name: string | null; is_you: boolean; chip: string | null; gw_points: number; hits: number; total: number; rank: number; start_rank: number; move: number; to_play: number; captain: string | null }
interface Swing { id: number; name: string; team: string | null; points: number; yours: number; owned: boolean; rival_owners: number; impact: number }
interface GwReview { gameweek: number; points: number; best: number; left: number; armband_cost: number; lineup_cost: number; bench_points: number; chip: string | null }
type Season =
  | { state: "unavailable"; reason: string }
  | { state: "ready"; gameweeks: GwReview[]; left: number; armband_cost: number; lineup_cost: number; bench_points: number; rival_bench_average: number | null; rivals_compared: number; method: string };
export type MatchdayData =
  | { state: "unavailable"; reason: string }
  | {
    state: "ready"; gameweek: number; status: "waiting" | "live" | "provisional" | "final"; average: number | null; highest: number | null;
    you: Scored; league: LeagueRow[]; swings: { gaining: Swing[]; losing: Swing[] }; fixtures: { total: number; started: number; finished: number };
    season: Season; warnings: string[]; method: string;
  };

const CHIPS: Record<string, string> = { bboost: "Bench Boost", "3xc": "Triple Captain", wildcard: "Wildcard", freehit: "Free Hit", manager: "Assistant Manager" };
const STATUS: Record<string, string> = { waiting: "Kick-off soon", live: "Live", provisional: "Provisional", final: "Final" };
const TOPS: Record<Role, number> = { FWD: 17, MID: 41, DEF: 65, GK: 88 };

function esc(value: unknown): string {
  return String(value ?? "—").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
}
const SUFFIX: Record<number, string> = { 1: "st", 2: "nd", 3: "rd" };
const ordinal = (n: number) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : SUFFIX[n % 10] ?? "th"}`;
const pct = (part: number, whole: number) => Math.max(0, Math.min(100, (Number(part) / Number(whole)) * 100 || 0)).toFixed(1);
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function shirt(row: ScoreRow, chip: string | null): string {
  const arm = row.armband ? `<span class="arm">${chip === "3xc" ? "TC" : "C"}</span>` : row.is_vice ? '<span class="arm vice">V</span>' : "";
  const shown = row.points * Math.max(row.multiplier, 1);
  const state = row.sub_out ? '<span class="md-tag red">↓ auto-sub</span>'
    : row.sub_in ? '<span class="md-tag green">↑ auto-sub</span>'
      : row.state === "playing" ? '<span class="md-tag live">● playing</span>'
        : row.state === "yet" ? '<span class="md-tag">yet to play</span>'
          : row.minutes === 0 ? '<span class="md-tag">didn\'t play</span>' : "";
  const bonus = row.provisional_bonus ? `<span class="md-bonus">+${esc(row.provisional_bonus)} bonus?</span>` : "";
  const label = `${row.name}, ${row.team ?? ""}, ${shown} points${row.armband ? ` (×${row.multiplier} armband)` : ""}${row.provisional_bonus ? `, including ${row.provisional_bonus} projected bonus` : ""}`;
  return `<div class="magnet md-shirt${row.sub_out ? " is-out" : ""}${row.state === "yet" ? " is-yet" : ""}" role="listitem" aria-label="${esc(label)}"><span class="magnet-base" aria-hidden="true"></span>${jerseySvg(row.team, row.role === "GK")}${arm}<span class="md-pts${shown >= 10 ? " hot" : ""}" aria-hidden="true">${esc(shown)}</span><span class="plate">${esc(row.name)}</span>${state}${bonus}</div>`;
}

function board(you: Scored): string {
  const bench = you.chip === "bboost";
  const pitch = you.rows.filter((r) => (bench ? r.starter : r.counts));
  const tray = you.rows.filter((r) => !pitch.includes(r));
  const rows = (Object.keys(TOPS) as Role[]).map((role) => {
    const line = pitch.filter((r) => r.role === role);
    return line.length ? `<div class="board-row" role="list" style="top:${TOPS[role]}%">${line.map((r) => shirt(r, you.chip)).join("")}</div>` : "";
  }).join("");
  return `<div class="board-frame"><div class="enamel"><div class="board-pitch">
      <svg class="pitch-print" viewBox="0 0 68 80" preserveAspectRatio="none" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width=".35"><rect x="2" y="2" width="64" height="76" rx=".6"/><rect x="16" y="2" width="36" height="13"/><rect x="26" y="2" width="16" height="5"/><path d="M27 15 A7 7 0 0 0 41 15"/><circle cx="34" cy="80" r="9"/></g></svg>
      <div class="board-rows">${rows}</div></div></div>
    <div class="tray"><h3>${bench ? "Bench Boost: the bench counts" : `Bench · ${esc(you.bench_points)} pts`}</h3><div class="tray-slots" role="list">${tray.map((r) => `<div class="tray-slot">${shirt(r, you.chip)}</div>`).join("")}</div></div></div>`;
}

function move(value: number): string {
  const n = Number(value) || 0;
  if (n > 0) return `<span class="md-move up" aria-label="up ${n}">▲${n}</span>`;
  if (n < 0) return `<span class="md-move down" aria-label="down ${-n}">▼${-n}</span>`;
  return '<span class="md-move" aria-label="no change">–</span>';
}

function league(rows: LeagueRow[], live: boolean): string {
  if (rows.length < 2) return "";
  return `<section><h3>Live league · you and compared rivals</h3><div class="table-wrap"><table class="md-league"><thead><tr><th>#</th><th>Manager</th><th>GW</th><th>Total</th>${live ? "<th>Left</th>" : ""}</tr></thead><tbody>${rows.map((r) => `<tr${r.is_you ? ' class="is-you"' : ""}><td>${esc(r.rank)} ${move(r.move)}</td><td><span class="player-name">${esc(r.name)}</span><span class="sub">C ${esc(r.captain)}${r.chip ? ` · ${esc(CHIPS[r.chip] ?? r.chip)}` : ""}${r.hits ? ` · −${esc(r.hits)} hit` : ""}</span></td><td>${esc(r.gw_points)}</td><td>${esc(r.total)}</td>${live ? `<td>${esc(r.to_play)}</td>` : ""}</tr>`).join("")}</tbody></table></div></section>`;
}

function swingList(title: string, rows: Swing[], cls: string): string {
  if (!rows.length) return "";
  return `<div><h4 class="hand ${cls}">${esc(title)}</h4><ul class="md-swings">${rows.map((r) => `<li><span><strong>${esc(r.name)}</strong> <span class="sub">${esc(r.team)} · ${esc(r.points)} pts · ${r.yours ? (r.yours > 1 ? `your captain (×${esc(r.yours)})` : "in your XI") : r.owned ? "on your bench" : "you don't own"} · ${esc(plural(r.rival_owners, "rival"))}</span></span><span class="md-impact ${cls}">${r.impact > 0 ? "+" : "−"}${esc(Math.abs(r.impact))}</span></li>`).join("")}</ul></div>`;
}

function ledger(season: Season): string {
  if (season.state !== "ready") return `<article class="panel md-ledger"><p class="evidence-warning">${esc(season.reason)}</p></article>`;
  const worst = season.gameweeks.reduce<GwReview | null>((w, g) => (!w || g.left > w.left ? g : w), null);
  const top = Math.max(...season.gameweeks.map((g) => Number(g.best) || 0), 1);
  const bench = season.rival_bench_average === null ? ""
    : `<div><span class="metric-label">Bench points this season</span><strong>${esc(season.bench_points)}</strong><span class="sub">rivals average ${esc(season.rival_bench_average)} (${esc(season.rivals_compared)} compared)</span></div>`;
  const bars = season.gameweeks.map((g) => `<li><span class="md-gw">GW${esc(g.gameweek)}${g.chip ? ` <span class="sub">${esc(CHIPS[g.chip] ?? g.chip)}</span>` : ""}</span><span class="md-bar" role="img" aria-label="${esc(`GW${g.gameweek}: ${g.points} scored, ${g.best} possible`)}"><span class="md-best" style="width:${pct(g.best, top)}%"></span><span class="md-actual" style="width:${pct(g.points, top)}%"></span></span><span class="md-nums"><strong>${esc(g.points)}</strong> / ${esc(g.best)}${g.left ? ` <span class="md-left">−${esc(g.left)}</span>` : ' <span class="hand green">perfect</span>'}</span></li>`).join("");
  return `<article class="panel md-ledger" aria-labelledby="ledger-title">
    <div class="panel-head"><div><h2 id="ledger-title">Points left on the table</h2><p>Every finished gameweek, your score against the best XI and captain you could have picked from the same 15.</p></div></div>
    <div class="md-ledger-top">
      <div class="md-big"><strong>${esc(season.left)}</strong><span>points left this season</span></div>
      <div><span class="metric-label">From the armband</span><strong>${esc(season.armband_cost)}</strong><span class="sub">captain vs your best scorer</span></div>
      <div><span class="metric-label">From the lineup</span><strong>${esc(season.lineup_cost)}</strong><span class="sub">bench and formation</span></div>
      ${bench}
    </div>
    ${worst && worst.left ? `<p class="hand red md-callout">Worst week: GW${esc(worst.gameweek)}, ${esc(worst.left)} points short${worst.bench_points >= 10 ? `, with ${esc(worst.bench_points)} sat on the bench` : ""}.</p>` : ""}
    <ol class="md-bars">${bars}</ol>
    <p class="method">${esc(season.method)} The lineup helper on My squad exists to close this gap.</p>
  </article>`;
}

export function renderMatchday(data: MatchdayData | null, loading: boolean, error = ""): string {
  if (!data) {
    return `<div class="board-frame"><div class="enamel board-notice"><p class="hand-note">${loading ? "Checking the scores…" : "No scores yet."}</p><p>${esc(error || "Live points come straight from FPL.")}</p></div></div>`;
  }
  if (data.state !== "ready") return `<div class="board-frame"><div class="enamel board-notice"><p class="hand-note">No scores yet.</p><p>${esc(data.reason)}</p></div></div>`;
  const you = data.you;
  const live = data.status === "live";
  const me = data.league.find((r) => r.is_you);
  const gw = you.total - you.hits;
  const facts = [
    `<div class="md-score"><dt>your GW${esc(data.gameweek)} points</dt><dd>${esc(gw)}</dd>${you.hits ? `<span class="stat-note">after −${esc(you.hits)} hit</span>` : ""}</div>`,
    data.average !== null ? `<div><dt>average</dt><dd>${esc(data.average)}</dd></div>` : "",
    data.highest !== null ? `<div><dt>highest</dt><dd>${esc(data.highest)}</dd></div>` : "",
    me && data.league.length > 1 ? `<div><dt>of ${esc(data.league.length)} compared</dt><dd>${esc(ordinal(me.rank))} ${move(me.move)}</dd></div>` : "",
    `<div><dt>${live ? "players still to play" : "matches played"}</dt><dd>${live ? esc(you.to_play) : `${esc(data.fixtures.finished)}/${esc(data.fixtures.total)}`}</dd></div>`,
  ].join("");
  return `<section class="matchday" aria-label="Gameweek ${esc(data.gameweek)} matchday">
    <div class="board-head"><p><span class="md-status ${esc(data.status)}">${esc(STATUS[data.status] ?? data.status)}</span> Gameweek ${esc(data.gameweek)}${you.chip ? ` · ${esc(CHIPS[you.chip] ?? you.chip)} played` : ""}${live ? " · updates every minute" : ""}</p><div class="board-tools"><button class="button-secondary md-refresh" type="button">Refresh scores</button></div></div>
    ${error ? `<p class="evidence-warning" role="status">Couldn't refresh just now (${esc(error)}). Showing the last scores.</p>` : ""}
    <dl class="board-stats">${facts}</dl>
    <div class="tactics-grid">
      ${board(you)}
      <aside class="coach-notes">
        <h2>The league right now</h2>
        <p class="notes-src">${live ? "Live, with projected bonus and auto-subs." : data.status === "provisional" ? "Bonus not yet confirmed by FPL." : "Confirmed by FPL."}</p>
        ${league(data.league, live)}
        <section><h3>Swing players</h3><p class="fine">Points × your share of the player against your rivals'.</p>${swingList("Winning you ground", data.swings.gaining, "green")}${swingList("Costing you ground", data.swings.losing, "red")}</section>
      </aside>
    </div>
    ${ledger(data.season)}
    ${data.warnings.length ? `<p class="fine">${data.warnings.map(esc).join(" ")}</p>` : ""}
    <p class="method">${esc(data.method)}</p>
  </section>`;
}
