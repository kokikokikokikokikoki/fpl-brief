import type { TeamDecisionPlayer } from "./app";

export interface LineupPlayer {
  id: number;
  name: string | null;
  team: string | null;
  role: string | null;
  estimate: number;
  chance: number | null;
  fixtures: number;
  eligible: boolean;
  flags: string[];
  blockers: string[];
  reason: string;
  next_fixtures?: Array<{ gameweek: number; opponent: string; venue: string; difficulty: number | null }>;
}

interface LineupPick { id: number; name: string | null; estimate: number; flags: string[] }

export type LineupData =
  | { state: "unavailable"; reason: string; gameweek?: number | null }
  | {
    state: "ready";
    gameweek: number;
    deadline_utc: string;
    formation: string;
    xi_estimate_total: number;
    lines: Record<"GK" | "DEF" | "MID" | "FWD", LineupPlayer[]>;
    bench: LineupPlayer[];
    captain: LineupPick;
    vice: LineupPick;
    captain_options?: Array<LineupPick & { team: string | null; fixtures: number; next_fixtures: NonNullable<LineupPlayer["next_fixtures"]> }>;
    changes: {
      source: string;
      current_xi?: number[];
      start: Array<string | null>;
      bench: Array<string | null>;
      captain: { from: string | null; to: string | null } | null;
      vice: { from: string | null; to: string | null } | null;
      bench_order_changed: boolean;
      none: boolean;
    };
    bench_boost: { bench_total: number; available: boolean | null; all_bench_playing: boolean; rule_of_thumb: number; hint: string };
    method: string;
  };

function esc(value: unknown): string {
  return String(value ?? "—").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character] ?? character);
}

function evidence(player: LineupPlayer, context: Map<number, TeamDecisionPlayer>): string {
  const row = context.get(player.id);
  if (!row) return "";
  const note = row.news ? `<li><span class="lineup-source">FPL note</span> ${esc(row.news)}</li>` : "";
  const research = row.research.filter((item) => !item.stale).slice(0, 2)
    .map((item) => `<li><span class="lineup-source">${esc(item.publisher || "Source")} · captured, unverified</span> ${esc(item.text)}</li>`).join("");
  return note || research ? `<ul class="lineup-evidence">${note}${research}</ul>` : "";
}

function playerItem(player: LineupPlayer, context: Map<number, TeamDecisionPlayer>, marker = ""): string {
  const warn = !player.eligible || player.flags.some((flag) => flag.startsWith("doubtful") || flag.startsWith("FPL status"));
  return `<li class="lineup-player${warn ? " is-flagged" : ""}"><div class="lineup-player-head"><strong>${esc(player.name)}</strong>${marker}<span class="lineup-meta">${esc(player.role)} · ${esc(player.team)}</span><span class="lineup-estimate" title="FPL's published next-round estimate">FPL est. ${esc(player.estimate)}</span></div><p>${esc(player.reason)}</p>${evidence(player, context)}</li>`;
}

export function renderLineupHelper(data: LineupData | undefined, players: TeamDecisionPlayer[] = []): string {
  if (!data) return "";
  const head = (gameweek: unknown) => `<div class="panel-head"><div><h2 id="lineup-title">This week's lineup${gameweek ? ` · GW${esc(gameweek)}` : ""}</h2><p>Built from FPL's own next-round estimate and official availability. A starting point, not a forecast by this app.</p></div></div>`;
  if (data.state !== "ready") {
    return `<section class="panel lineup-helper" aria-labelledby="lineup-title">${head(data.gameweek)}<p class="evidence-warning" role="status">${esc(data.reason)}</p></section>`;
  }
  const context = new Map(players.filter((row) => typeof row.id === "number").map((row) => [row.id as number, row]));
  const mark = (player: LineupPlayer) => player.id === data.captain.id ? ' <span class="lineup-armband">C</span>' : player.id === data.vice.id ? ' <span class="lineup-armband vice">V</span>' : "";
  const lines = (["GK", "DEF", "MID", "FWD"] as const).map((role) =>
    `<div class="lineup-line"><h3>${role} <span>${data.lines[role].length}</span></h3><ul>${data.lines[role].map((player) => playerItem(player, context, mark(player))).join("")}</ul></div>`).join("");
  const bench = data.bench.map((player, index) => playerItem(player, context, ` <span class="lineup-bench-slot">${index === 0 ? "GK" : `B${index}`}</span>`)).join("");
  const c = data.changes;
  const diff = c.none
    ? `<p>Matches ${esc(c.source)}. No changes needed by this method.</p>`
    : `<ul class="lineup-changes">${c.start.length ? `<li><strong>Start:</strong> ${c.start.map(esc).join(", ")}</li>` : ""}${c.bench.length ? `<li><strong>Bench:</strong> ${c.bench.map(esc).join(", ")}</li>` : ""}${c.captain ? `<li><strong>Captain:</strong> ${c.captain.from ? `${esc(c.captain.from)} → ` : ""}${esc(c.captain.to)}</li>` : ""}${c.vice ? `<li><strong>Vice:</strong> ${c.vice.from ? `${esc(c.vice.from)} → ` : ""}${esc(c.vice.to)}</li>` : ""}${c.bench_order_changed ? "<li><strong>Bench order</strong> differs (see bench below).</li>" : ""}</ul><p class="small">Compared with ${esc(c.source)}.</p>`;
  const captainNote = (pick: LineupPick) => `${esc(pick.name)} (FPL est. ${esc(pick.estimate)}${pick.flags.length ? `; ${pick.flags.map(esc).join("; ")}` : ""})`;
  return `<section class="panel lineup-helper" aria-labelledby="lineup-title">${head(data.gameweek)}
    <div class="lineup-summary"><div><span class="metric-label">Formation</span><strong>${esc(data.formation)}</strong></div><div><span class="metric-label">Captain</span><strong>${captainNote(data.captain)}</strong></div><div><span class="metric-label">Vice</span><strong>${captainNote(data.vice)}</strong></div><div><span class="metric-label">XI FPL estimate</span><strong>${esc(data.xi_estimate_total)}</strong></div></div>
    <div class="lineup-block"><h3>Changes vs your current lineup</h3>${diff}</div>
    <div class="lineup-grid">${lines}</div>
    <div class="lineup-line lineup-bench"><h3>Bench <span>in order</span></h3><ul>${bench}</ul></div>
    <div class="lineup-block"><h3>Bench Boost</h3><p>${esc(data.bench_boost.hint)}</p><p class="small">Bench FPL estimate total ${esc(data.bench_boost.bench_total)}. A rule-of-thumb hint, not advice to play the chip.</p></div>
    <p class="method">${esc(data.method)} News shown is FPL's own note or captured research, unverified. For a judgment that weighs current web news, ask Jev (Claude) in Claude Code, e.g. "who should I bench this week?"</p>
  </section>`;
}
