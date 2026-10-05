// Rival maths: effective ownership, captaincy against rivals and finish odds (Stage 4). Estimates from simple models.
import { jerseySvg } from "./kits";

interface Chip { name: string; label: string; expires?: number }
interface MathPlayer { id: number; name: string; team: string | null; position: string | null; xp: number; xp_6: number; eo: number; points?: number; mult?: number }
interface Drivers { for_you: MathPlayer[]; against_you: MathPlayer[] }
interface RivalVersus { entry_id: number; name: string | null; expected: number; p_gain: number }
interface CaptainRow extends MathPlayer { vs_field: number; p_beats_field: number; rivals: RivalVersus[]; current: boolean; differential_flag: boolean }
interface RivalMathRow {
  entry_id: number; name: string | null; manager: string | null; rank: number | null; total: number | null; gap: number; p_ahead: number; p_ahead_analytic: number; z: number;
  edge: number; sigma_week: number; p_first: number; swing: number; drivers: Drivers; assumed_captain: { id: number | null; name: string | null; why: string };
  chips_left: Chip[]; shared: number;
}
export type RivalMathsData =
  | { state: "unavailable"; reason: string }
  | {
    state: "ready"; gameweek: number; target_gameweek: number | null; remaining: number; model: string; lineup_source: string; sims: number; rivals_compared: number;
    you: { name: string | null; rank: number | null; total: number | null; p_first: number; expected_rank: number };
    mode: { mode: "protect" | "chase" | "balanced"; z: number; against: string | null; you_lead: boolean; gap: number; edge: number; sigma_week: number; remaining: number; text: string };
    field_swing: { swing: number; drivers: Drivers }; rivals: RivalMathRow[]; captains: CaptainRow[]; shield: MathPlayer[]; differentials: MathPlayer[];
    warnings: string[]; caveats: string[]; assumptions: string[]; method: string;
  };

function esc(value: unknown): string {
  return String(value ?? "—").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
}
const num = (value: unknown, digits = 1) => (typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—");
const signed = (value: unknown, digits = 1) => (typeof value === "number" && Number.isFinite(value) ? `${value > 0 ? "+" : value < 0 ? "−" : "±"}${Math.abs(value).toFixed(digits)}` : "—");
const pct = (value: unknown) => {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const share = value * 100;
  return share > 0 && share < 1 ? "<1%" : share < 100 && share > 99 ? ">99%" : `${Math.round(share)}%`;
};
const eoPct = (value: number) => `${Math.round(value * 100)}%`;
const tone = (value: number) => (value > 0 ? "rm-good" : value < 0 ? "rm-bad" : "");

function driverList(rows: MathPlayer[], empty: string): string {
  if (!rows.length) return `<span class="sub">${esc(empty)}</span>`;
  return rows.map((p) => `<span class="rm-driver">${esc(p.name)} <b class="${tone(p.points ?? 0)}">${esc(signed(p.points))}</b></span>`).join("");
}

function playerList(rows: MathPlayer[], empty: string): string {
  if (!rows.length) return `<p class="fine">${esc(empty)}</p>`;
  return `<ul class="lt-list">${rows.map((p) => `<li><span class="row-kit">${jerseySvg(p.team)}</span><span><strong>${esc(p.name)}</strong> <span class="sub">${esc(p.team)} · ${esc(p.position)} · EO ${esc(eoPct(p.eo))}${p.mult === 0 ? " · benched" : ""}</span></span><span class="rm-xp" aria-label="${esc(`${num(p.xp)} expected points next gameweek`)}">${esc(num(p.xp))}<small>6 GW ${esc(num(p.xp_6))}</small></span></li>`).join("")}</ul>`;
}

function chips(rows: Chip[]): string {
  return rows.length ? rows.map((c) => `<span class="lt-chip">${esc(c.label)}</span>`).join("") : '<span class="sub">none left</span>';
}

const MODE_LABEL: Record<string, string> = { protect: "Protect", chase: "Chase", balanced: "Balanced" };

export function renderRivalMaths(data: RivalMathsData | null, loading: boolean, error = ""): string {
  const head = '<div class="panel-head"><div><h2>Rival maths</h2><p>How each choice moves the gap to your rivals. Estimates from simple models.</p></div></div>';
  if (!data) return `<article class="panel rm">${head}<p class="${error ? "evidence-warning" : "fine"}">${esc(error || (loading ? "Working out ownership, captaincy and finish odds…" : "Open this view to load rival maths."))}</p></article>`;
  if (data.state !== "ready") return `<article class="panel rm">${head}<p class="evidence-warning">${esc(data.reason)}</p></article>`;
  const m = data.mode;
  const gw = data.target_gameweek ?? data.gameweek + 1;
  const odds = [{ name: `${data.you.name ?? "You"} (you)`, p: data.you.p_first, you: true }, ...data.rivals.map((r) => ({ name: r.name ?? "—", p: r.p_first, you: false }))]
    .filter((row) => row.p >= 0.005 || row.you).sort((a, b) => b.p - a.p);
  const bar = odds.map((row) => `<span class="rm-seg${row.you ? " is-you" : ""}" style="flex-grow:${Math.max(row.p, 0.004).toFixed(4)}" title="${esc(`${row.name}: ${pct(row.p)}`)}"></span>`).join("");
  const legend = odds.map((row) => `<li${row.you ? ' class="is-you"' : ""}><span>${esc(row.name)}</span><b>${esc(pct(row.p))}</b></li>`).join("");
  const top = data.captains[0]?.rivals ?? [];
  const captainHead = top.map((r) => `<th scope="col">vs ${esc(r.name)}<span class="sub">exp · P(gain ≥ 0)</span></th>`).join("");
  const captainRows = data.captains.map((c) => `<tr${c.current ? ' class="is-you"' : ""}><th scope="row"><span class="player-name">${esc(c.name)}</span><span class="sub">${esc(c.team)} · ${esc(c.position)}${c.current ? " · your captain now" : ""}${c.differential_flag ? ' · <span class="rm-flag">differential option (heuristic)</span>' : ""}</span></th><td>${esc(num(c.xp, 2))}</td><td>${esc(eoPct(c.eo))}</td><td class="${tone(c.vs_field)}">${esc(signed(c.vs_field, 2))}</td><td>${esc(pct(c.p_beats_field))}</td>${c.rivals.map((r) => `<td><span class="${tone(r.expected)}">${esc(signed(r.expected, 2))}</span> · ${esc(pct(r.p_gain))}</td>`).join("")}</tr>`).join("");
  const rivalRows = data.rivals.map((r) => `<tr><td>${esc(r.rank)}</td><td><span class="player-name">${esc(r.name)}</span><span class="sub">C ${esc(r.assumed_captain.name)} (assumed: ${esc(r.assumed_captain.why)}) · ${esc(r.shared)} shared</span></td><td class="${r.gap > 0 ? "rm-good" : r.gap < 0 ? "rm-bad" : ""}">${esc(signed(r.gap, 0))}</td><td><strong>${esc(pct(r.p_ahead))}</strong><span class="sub">formula check ${esc(pct(r.p_ahead_analytic))}</span><span class="sub">edge ${esc(signed(r.edge, 0))} · σ/wk ${esc(num(r.sigma_week))}</span></td><td><strong class="${tone(r.swing)}">${esc(signed(r.swing, 2))}</strong><span class="rm-drivers">${driverList(r.drivers.for_you.slice(0, 3), "nothing for you")}</span><span class="rm-drivers">${driverList(r.drivers.against_you.slice(0, 3), "nothing against you")}</span></td><td>${chips(r.chips_left)}</td></tr>`).join("");
  const notes = [...data.caveats, ...data.warnings];
  return `<article class="panel rm" aria-labelledby="rm-title">
    <div class="panel-head"><div><h2 id="rm-title">Rival maths</h2><p>GW${esc(gw)} against the top ${esc(data.rivals_compared)} of your mini-league. Every probability here is an estimate from a simple model.</p></div></div>
    <section class="rm-mode rm-${esc(m.mode)}" aria-label="Mode hint"><span class="rm-mode-tag">${esc(MODE_LABEL[m.mode] ?? m.mode)}</span><div><p class="hand">${esc(m.text)}</p><p class="fine">Against ${esc(m.against)}: gap ${esc(signed(m.gap, 0))}, expected edge over the remaining ${esc(m.remaining)} GWs ${esc(signed(m.edge, 0))}, weekly spread ${esc(num(m.sigma_week))} → z ${esc(num(m.z, 2))} (protect above +0.5, chase below −0.5). Estimate.</p></div></section>
    <h3 class="lt-h">Title odds (estimate)</h3>
    <div class="rm-bar" role="img" aria-label="${esc(`Estimated title odds: ${odds.map((row) => `${row.name} ${pct(row.p)}`).join(", ")}`)}">${bar}</div>
    <ul class="rm-legend">${legend}</ul>
    <p class="fine">You: estimated ${esc(pct(data.you.p_first))} to win the league; expected final rank ${esc(num(data.you.expected_rank))} among these ${esc(data.rivals_compared + 1)} managers.</p>
    <h3 class="lt-h">Per rival</h3>
    <div class="table-wrap"><table class="rm-table"><thead><tr><th>#</th><th>Manager</th><th>Gap</th><th>P(finish ahead)<span class="sub">estimate</span></th><th>GW${esc(gw)} swing<span class="sub">for you · against you</span></th><th>Chips left</th></tr></thead><tbody>${rivalRows}</tbody></table></div>
    <p class="fine">Against the field (EO): expected swing <strong class="${tone(data.field_swing.swing)}">${esc(signed(data.field_swing.swing, 2))}</strong>. For you: ${driverList(data.field_swing.drivers.for_you, "nothing")} Against you: ${driverList(data.field_swing.drivers.against_you, "nothing")}</p>
    <h3 class="lt-h">Captain table</h3>
    <div class="table-wrap"><table class="rm-table"><thead><tr><th scope="col">Captain</th><th scope="col">xP</th><th scope="col">EO</th><th scope="col">vs field<span class="sub">expected</span></th><th scope="col">Beats field's captains<span class="sub">estimate</span></th>${captainHead}</tr></thead><tbody>${captainRows}</tbody></table></div>
    <p class="fine">Differential option is the community heuristic, not a derived rule: the favourite's EO is above 75%, this one's is below 50%, and the xP gap is under 1.5.</p>
    <div class="lt-grid rm-grid">
      <section><h3 class="lt-h">Your shield</h3><p class="fine">High-EO players you own (EO 50%+). They keep pace with the field.</p>${playerList(data.shield, "Nothing widely owned.")}</section>
      <section><h3 class="lt-h green">Your differentials</h3><p class="fine">EO under 25%. If these score, you climb.</p>${playerList(data.differentials, "No differentials.")}</section>
    </div>
    <ul class="fine rm-assume">${data.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}<li>Your lineup: ${esc(data.lineup_source)}.</li></ul>
    ${notes.length ? `<p class="evidence-warning">${notes.map(esc).join(" ")}</p>` : ""}
    <p class="method">${esc(data.method)}</p>
  </article>`;
}
