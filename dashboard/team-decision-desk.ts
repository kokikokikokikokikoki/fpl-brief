import type { DashboardData } from "./app";

type DecisionPlayer = DashboardData["team_decision"]["players"][number];
type ChipRow = DashboardData["team_decision"]["chips"]["chips"][number];

const roleNames: Record<number, string> = { 1: "Goalkeeper", 2: "Defender", 3: "Midfielder", 4: "Forward" };
const safeResearchUrls = new Set([
  "https://fantasy.premierleague.com/api/bootstrap-static/",
  "https://www.arsenal.com/news/all/1",
]);

function esc(value: unknown): string {
  return String(value ?? "—").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character] ?? character);
}

function stamp(value?: string | null): string {
  if (!value) return "time not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "invalid timestamp" : `${new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Bangkok",
  }).format(date)} BKK`;
}

function fixtures(player: DecisionPlayer): string {
  return player.fixtures.length
    ? player.fixtures.map((item) => `GW${esc(item.gameweek)} · ${esc(item.opponent)} (${esc(item.venue)}) · FDR ${esc(item.difficulty)}`).join("<br>")
    : "No saved upcoming fixture";
}

function researchItems(player: DecisionPlayer): string {
  if (!player.research.length) return "No research item linked by FPL player ID.";
  return `<ul class="decision-evidence">${player.research.map((item) => {
    const state = item.stale ? "Stale · captured, unverified" : "Captured, unverified";
    const label = `${esc(item.publisher || "Unknown source")} · ${esc(item.title || "Source material")}`;
    const source = item.url && safeResearchUrls.has(item.url)
      ? `<a href="${esc(item.url)}" target="_blank" rel="noreferrer">${label}</a>` : label;
    return `<li><span class="pill ${item.stale ? "warn" : ""}">${state}</span> ${source}<br><span class="small">${esc(stamp(item.captured_at_utc))}</span><br>${esc(item.text)}</li>`;
  }).join("")}</ul>`;
}

type KitRenderer = (team: string | null | undefined, keeper: boolean) => string;

function playerRows(players: DecisionPlayer[], kit?: KitRenderer): string {
  if (!players.length) return '<tr><td colspan="7">No saved squad picks are available in this snapshot.</td></tr>';
  return players.map((player) => {
    const risky = player.priority !== "No official availability flag";
    const role = typeof player.role === "number" ? roleNames[player.role] ?? "Unknown role" : "Unknown role";
    const compare = typeof player.id === "number" && Number.isInteger(player.id)
      ? `<button class="button-secondary decision-compare" type="button" data-compare-player="${player.id}" aria-label="Compare replacements for ${esc(player.name || "unknown player")}">Compare</button>`
      : "";
    const nextStep = player.next_step ? `<span class="sub">Next step: ${esc(player.next_step)}</span>` : "";
    return `<tr>
      <th scope="row">${kit ? `<span class="row-kit">${kit(player.team, player.role === 1)}</span>` : ""}<span class="player-name">${esc(player.name || "Unknown player")}</span><span class="sub">${esc(player.team || "Unknown team")} · ${esc(role)}</span></th>
      <td><span class="pill ${risky ? "warn" : ""}">${esc(player.priority)}</span><span class="sub">${esc(player.reason)}</span>${nextStep}${compare}</td>
      <td>${esc(player.minutes)}<span class="sub">minutes</span></td>
      <td>${esc(player.form)}<span class="sub">form · ${esc(player.total_points)} pts total</span></td>
      <td>${esc(player.ep_next)}<span class="sub">FPL next-round estimate</span></td>
      <td>${fixtures(player)}</td>
      <td>${player.news ? `<span>${esc(player.news)}</span><span class="sub">FPL note · ${esc(stamp(player.news_added))}</span>` : "No FPL note"}<div>${researchItems(player)}</div></td>
    </tr>`;
  }).join("");
}

function chipRows(chips: ChipRow[]): string {
  return chips.map((chip) => {
    if (chip.state !== "known") {
      const recorded = chip.used_count
        ? `${chip.used_count} · GW${(chip.used_gameweeks || []).join(", GW")} (${esc(chip.used_source || "recorded in snapshot")})`
        : "No recognized play recorded";
      return `<tr><th scope="row">${esc(chip.name)}</th><td>${esc(recorded)}</td><td colspan="2"><span class="pill warn">Availability unknown</span> ${esc(chip.reason)}</td></tr>`;
    }
    const used = chip.used_count
      ? `${chip.used_count} · GW${chip.used_gameweeks.join(", GW")}`
      : "0 · none recorded";
    const future = chip.future_windows.length
      ? chip.future_windows.map((window) => `Not yet available · GW${window.start_event}–${window.stop_event}: ${window.remaining}`).join("; ")
      : "No later window in saved rules";
    return `<tr><th scope="row">${esc(chip.name)}</th><td>${esc(used)}</td><td>${esc(chip.available_now)}</td><td>${esc(future)}</td></tr>`;
  }).join("");
}

const chipNames: Record<string, string> = { bboost: "Bench Boost", "3xc": "Triple Captain", wildcard: "Wildcard", freehit: "Free Hit" };

function money(tenths: unknown): string {
  return typeof tenths === "number" && Number.isFinite(tenths) ? `£${(tenths / 10).toFixed(1)}m` : "—";
}

export function renderPrivateTeamPanel(data: DashboardData["private_team"]): string {
  const head = `<div class="panel-head"><div><h2 id="private-team-title">Your FPL account</h2><p>Read-only capture from your own signed-in FPL session. Kept on this machine; never deployed. Not transfer advice.</p></div></div>`;
  if (!data) return "";
  if (data.state !== "stale" && data.state !== "ready") {
    return `<section class="panel private-team" aria-labelledby="private-team-title">${head}<p class="evidence-warning" role="status">${esc(data.message)}</p></section>`;
  }
  const notice = data.state === "stale"
    ? `<p class="evidence-warning" role="status">${esc(data.message)} Captured ${esc(stamp(data.captured_at_utc))}.</p>`
    : `<p class="small">Captured ${esc(stamp(data.captured_at_utc))} (${esc(data.age_hours)} h ago). Treated as current for up to 24 hours or until the next deadline passes; recapture after any transfer.</p>`;
  const free = data.free_transfers === "unlimited" ? "Unlimited" : esc(data.free_transfers);
  const chips = (data.chips ?? []).map((chip) => {
    const played = chip.played_gameweeks.length ? `played GW${chip.played_gameweeks.map((gw) => esc(gw)).join(", GW")}` : "not played";
    return `<tr><th scope="row">${esc(chipNames[chip.name] ?? chip.name)}</th><td>${esc(chip.status)}${chip.pending ? " (pending)" : ""}</td><td>${played}</td><td>GW${esc(chip.window[0])}–GW${esc(chip.window[1])}</td></tr>`;
  }).join("");
  return `<section class="panel private-team" aria-labelledby="private-team-title">${head}${notice}
    <dl class="private-team-facts"><div><dt>Free transfers</dt><dd>${free}</dd></div><div><dt>Transfers made</dt><dd>${esc(data.transfers_made)}</dd></div><div><dt>Bank</dt><dd>${esc(money(data.bank))}</dd></div><div><dt>Each extra transfer</dt><dd>−${esc(data.hit_cost)} pts</dd></div><div><dt>Team value</dt><dd>${esc(money(data.team_value))}</dd></div></dl>
    <div class="table-wrap"><table><caption>Chip status as reported by your FPL account.</caption><thead><tr><th scope="col">Chip</th><th scope="col">Status</th><th scope="col">Played</th><th scope="col">Window</th></tr></thead><tbody>${chips}</tbody></table></div>
  </section>`;
}

export function renderTeamDecisionDesk(data: DashboardData["team_decision"], kit?: KitRenderer): string {
  const flagged = data.players.filter((player) => player.priority !== "No official availability flag");
  const priorityDescriptions: Record<string, string> = {
    "Resolve availability": "official availability risk",
    "Availability unknown": "unknown availability data",
    "Resolve player data": "unmatched player data",
    "Review FPL note": "FPL notes",
    "Not enough current evidence": "insufficient stats/fixture evidence",
  };
  const reviewBreakdown = [...new Set(flagged.map((player) => player.priority))]
    .map((priority) => {
      const count = flagged.filter((player) => player.priority === priority).length;
      return `${count} ${priorityDescriptions[priority] || "other evidence gaps"}`;
    });
  const snapshotState = data.snapshot_stale
    ? `<p class="evidence-warning" role="status">${esc(data.snapshot_message)} Refresh public FPL data before relying on this decision desk.</p>`
    : `<p class="small">Saved public FPL snapshot · ${esc(stamp(data.generated_at_utc))} · ${esc(data.snapshot_message)}</p>`;
  const playerSummary = flagged.length
    ? `<p class="decision-lead-copy">${data.snapshot_stale ? "This snapshot is stale. The saved squad facts are shown for context only; refresh before using them to decide." : `${flagged.length} of ${data.players.length} saved picks need a closer look: ${reviewBreakdown.join("; ")}. Reasons below use the exact saved FPL fields.`}</p>`
    : `<p class="decision-lead-copy">${data.snapshot_stale ? "This snapshot is stale. Refresh before treating the saved squad as clear." : "No official availability flags in the saved squad. Review minutes, fixtures and alternatives before deciding; these stats alone do not require a transfer."}</p>`;
  const chips = data.chips;
  const chipNotice = chips.state === "unknown"
    ? `<p class="evidence-warning" role="status">${esc(chips.reason)}</p>`
    : chips.state === "partial"
      ? `<p class="evidence-warning" role="status">Some chip types could not be reconciled. Unknown is not counted as available. ${esc(chips.reason)}</p>`
      : `<p class="small">${esc(chips.reason)} · current decision window GW${esc(chips.gameweek)}. Later windows are shown separately and are not counted as available now.</p>`;
  return `<section class="panel team-decision" aria-labelledby="team-decision-title">
    <div class="panel-head"><div><h2 id="team-decision-title">Team decision desk</h2><p>Your 15 saved picks, current FPL facts, fixture horizon and player-linked research.</p></div></div>
    ${snapshotState}${playerSummary}
    <div class="table-wrap decision-table-wrap"><table class="decision-table"><caption>Saved squad decision facts. FPL next-round estimate is not a points promise; captured research is not verified team news.</caption><thead><tr><th scope="col">Player</th><th scope="col">Priority and reason</th><th scope="col">Minutes</th><th scope="col">Form and points</th><th scope="col">Next-round estimate</th><th scope="col">Upcoming fixtures</th><th scope="col">News evidence</th></tr></thead><tbody>${playerRows(data.snapshot_stale ? data.players : flagged, kit)}</tbody></table></div>${!data.snapshot_stale && data.players.length > flagged.length ? `<details class="decision-clear"><summary>${data.players.length - flagged.length} players with no FPL availability flag and enough evidence</summary><div class="table-wrap"><table class="decision-table"><caption>Unflagged saved picks. Availability only; not a transfer recommendation.</caption><thead><tr><th scope="col">Player</th><th scope="col">Priority and reason</th><th scope="col">Minutes</th><th scope="col">Form and points</th><th scope="col">Next-round estimate</th><th scope="col">Upcoming fixtures</th><th scope="col">News evidence</th></tr></thead><tbody>${playerRows(data.players.filter((player) => !flagged.includes(player)), kit)}</tbody></table></div></details>` : ""}
    <p class="method">Priorities are descriptive, not buy/sell instructions. Availability comes from the saved official FPL catalog. Research is joined only by stable FPL player ID and remains labeled captured/unverified; stale items are excluded from current conclusions. Compare replacements in Candidate Lens when useful.</p>
    <section class="chip-ledger" aria-labelledby="chip-ledger-title"><div class="panel-head"><div><h3 id="chip-ledger-title">Chip ledger</h3><p>Recorded plays versus official season windows.</p></div></div>${chipNotice}<div class="table-wrap"><table><caption>Used counts and gameweeks, availability in the current window, and future windows.</caption><thead><tr><th scope="col">Chip</th><th scope="col">Used</th><th scope="col">Available now</th><th scope="col">Later window</th></tr></thead><tbody>${chipRows(chips.chips)}</tbody></table></div></section>
  </section>`;
}
