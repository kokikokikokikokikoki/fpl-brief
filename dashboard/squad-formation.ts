interface FormationPick {
  element: number;
  position: number;
  element_type?: number;
  is_captain?: boolean;
  is_vice_captain?: boolean;
}

interface FormationPlayer {
  id: number;
  web_name?: string;
  team?: number;
  element_type?: number;
  status?: string;
  chance_of_playing_next_round?: number | null;
  now_cost?: string | number | null;
  form?: string | number | null;
  total_points?: string | number | null;
  ep_next?: string | number | null;
}

interface FormationTeam {
  id: number;
  short_name?: string;
}

export interface SquadFormationInput {
  picks: FormationPick[];
  players: FormationPlayer[];
  teams: FormationTeam[];
  /** Optional shirt renderer (team short name, is keeper) supplied by the app. */
  jersey?: (team: string | undefined, keeper: boolean) => string;
  gameweek?: number | null;
  generatedAt?: string;
  bank?: string | number | null;
}

const roleNames: Record<number, string> = { 1: "Goalkeeper", 2: "Defender", 3: "Midfielder", 4: "Forward" };
const roleCodes: Record<number, string> = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };
const availabilityNames: Record<string, string> = {
  a: "Available",
  d: "Doubtful",
  i: "Injured",
  s: "Suspended",
  u: "Unavailable",
  n: "Not in FPL",
};

function escapeHtml(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character] ?? character);
}

function roleOf(pick: FormationPick, player?: FormationPlayer): number | undefined {
  const role = player?.element_type ?? pick.element_type;
  return role !== undefined && roleNames[role] ? role : undefined;
}

function formattedSnapshotTime(value?: string): string {
  if (!value) return "Timestamp unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Timestamp unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Bangkok",
  }).format(date) + " BKK";
}

function playerData(pick: FormationPick, input: SquadFormationInput) {
  const player = input.players.find((item) => item.id === pick.element);
  const team = player?.team === undefined ? undefined : input.teams.find((item) => item.id === player.team);
  const role = roleOf(pick, player);
  const chance = player?.chance_of_playing_next_round;
  const risky = !player || player.status !== "a" || (chance != null && chance < 100);
  const availability = !player
    ? "Availability unknown"
    : availabilityNames[player.status ?? ""] ?? "Availability unknown";
  const availabilityText = !player
    ? "Availability unknown"
    : chance != null && chance < 100
      ? `${player.status && player.status !== "a" && availabilityNames[player.status] ? `${availability} · ` : ""}${chance}% chance (FPL)`
      : availability;
  const captain = pick.is_captain ? "Captain" : pick.is_vice_captain ? "Vice captain" : "";
  const price = player?.now_cost == null ? "Unknown" : `£${(Number(player.now_cost) / 10).toFixed(1)}m`;
  return { player, team, role, risky, availabilityText, captain, price };
}

function playerCard(pick: FormationPick, input: SquadFormationInput, bench = false): string {
  const { player, team, role, risky, availabilityText, captain, price } = playerData(pick, input);
  const name = player?.web_name || "Unknown player";
  const teamName = team?.short_name || "Team unknown";
  const pickLabel = bench ? `Bench ${Math.max(1, pick.position - 11)}` : `Snapshot pick ${pick.position}`;
  const statusClass = risky ? " squad-risk" : " squad-clear";
  return `<article class="formation-player${statusClass}" aria-label="${escapeHtml(`${pickLabel}: ${roleNames[role ?? 0] ?? "Position unknown"}, ${name}, ${teamName}${captain ? `, ${captain}` : ""}, ${availabilityText}`)}">
    ${input.jersey ? input.jersey(team?.short_name, role === 1) : ""}
    <span class="formation-player-role">${escapeHtml(roleCodes[role ?? 0] ?? "?")}</span>
    <strong class="formation-player-name">${escapeHtml(name)}</strong>
    <span class="formation-player-team">${escapeHtml(teamName)}</span>
    ${captain ? `<span class="formation-captain">${escapeHtml(captain)}</span>` : ""}
    <span class="formation-availability">${escapeHtml(availabilityText)}</span>
    <span class="formation-player-stats">
      <span>Price ${escapeHtml(price)}</span>
      <span>Form ${escapeHtml(player?.form ?? "—")}</span>
      <span>Points ${escapeHtml(player?.total_points ?? "—")}</span>
      <span>GW estimate ${escapeHtml(player?.ep_next ?? "—")}</span>
    </span>
  </article>`;
}

function listRow(pick: FormationPick, input: SquadFormationInput): string {
  const { player, team, role, availabilityText, risky, captain, price } = playerData(pick, input);
  return `<tr>
    <td>${escapeHtml(pick.position <= 11 ? `Pick ${pick.position}` : `Bench ${Math.max(1, pick.position - 11)}`)}</td>
    <td>${escapeHtml(roleNames[role ?? 0] ?? "Unknown")}</td>
    <th scope="row"><span class="player-name">${escapeHtml(player?.web_name || "Unknown player")}${captain ? ` · ${escapeHtml(captain)}` : ""}</span></th>
    <td>${escapeHtml(team?.short_name || "Unknown")}</td>
    <td><span class="formation-list-status${risky ? " squad-risk-text" : " squad-clear-text"}">${escapeHtml(availabilityText)}</span></td>
    <td>${escapeHtml(price)}</td>
    <td>${escapeHtml(player?.form ?? "—")}</td>
    <td>${escapeHtml(player?.total_points ?? "—")}</td>
    <td>${escapeHtml(player?.ep_next ?? "—")}</td>
  </tr>`;
}

export function renderSquadFormation(input: SquadFormationInput): string {
  const picks = [...input.picks].sort((left, right) => left.position - right.position);
  const starters = picks.filter((pick) => pick.position >= 1 && pick.position <= 11);
  const bench = picks.filter((pick) => pick.position >= 12);
  const playerById = new Map(input.players.map((player) => [player.id, player]));
  const counts = new Map<number, number>([[2, 0], [3, 0], [4, 0]]);
  for (const pick of starters) {
    const role = roleOf(pick, playerById.get(pick.element));
    if (role === 2 || role === 3 || role === 4) counts.set(role, (counts.get(role) ?? 0) + 1);
  }
  const knownShape = starters.length === 11 && starters.every((pick) => roleOf(pick, playerById.get(pick.element)) !== undefined)
    ? `${counts.get(2)}-${counts.get(3)}-${counts.get(4)}`
    : "incomplete position data";
  const rows = [1, 2, 3, 4].map((role) => {
    const group = starters.filter((pick) => roleOf(pick, playerById.get(pick.element)) === role);
    if (!group.length) return "";
    return `<div class="formation-line" aria-label="${escapeHtml(roleNames[role])} picks">
      <h3>${escapeHtml(roleNames[role])} <span>${group.length}</span></h3>
      <div class="formation-line-players formation-count-${group.length}">${group.map((pick) => playerCard(pick, input)).join("")}</div>
    </div>`;
  }).join("");
  const unknownRole = starters.filter((pick) => roleOf(pick, playerById.get(pick.element)) === undefined);
  const unknownRow = unknownRole.length
    ? `<div class="formation-line" aria-label="Unknown position picks"><h3>Position unknown <span>${unknownRole.length}</span></h3><div class="formation-line-players formation-count-${Math.min(unknownRole.length, 4)}">${unknownRole.map((pick) => playerCard(pick, input)).join("")}</div></div>`
    : "";
  const listedPicks = picks.map((pick) => listRow(pick, input)).join("");
  const gameweek = input.gameweek == null ? "Unknown" : String(input.gameweek);
  const bank = input.bank == null ? "Unknown" : `£${(Number(input.bank) / 10).toFixed(1)}m`;

  return `<article class="panel squad-panel">
    <div class="panel-head squad-heading"><div><h2>My public squad · GW${escapeHtml(gameweek)}</h2>
      <p>Saved squad snapshot · ${escapeHtml(formattedSnapshotTime(input.generatedAt))} · ${escapeHtml(bank)} in the bank</p></div>
      <div class="squad-view-toggle" role="group" aria-label="Squad display">
        <button type="button" class="button-secondary" data-squad-view="pitch" aria-controls="squad-pitch" aria-pressed="true">Pitch</button>
        <button type="button" class="button-secondary" data-squad-view="list" aria-controls="squad-list" aria-pressed="false">List</button>
      </div>
    </div>
    <p class="squad-caveat">Public saved picks and bench order. Snapshot shape (${escapeHtml(knownShape)}) describes these picks only; this view does not advise a lineup or expose unsubmitted intent.</p>
    <div id="squad-pitch" class="squad-pitch-view" data-squad-panel="pitch" aria-label="Pitch view of saved picks">
      ${starters.length ? `<div class="squad-pitch"><div class="pitch-midline" aria-hidden="true"></div>${rows}${unknownRow}</div>` : '<p class="squad-empty">No saved starting picks are available in this snapshot.</p>'}
      <section class="squad-bench" aria-labelledby="squad-bench-heading"><div class="squad-section-heading"><h3 id="squad-bench-heading">Bench order</h3><p>Substitutes appear in saved snapshot order.</p></div>
        ${bench.length ? `<ol class="squad-bench-list">${bench.map((pick) => `<li>${playerCard(pick, input, true)}</li>`).join("")}</ol>` : '<p class="squad-empty">No saved substitutes are available in this snapshot.</p>'}
      </section>
      <p class="small squad-list-note">FPL GW estimates are for the next round only, not a points promise.</p>
    </div>
    <div id="squad-list" class="squad-list-view" data-squad-panel="list" aria-label="Accessible list of saved squad picks" hidden>
      <div class="table-wrap"><table><caption>Public squad picks in saved order; substitutes follow the starting picks.</caption><thead><tr><th scope="col">Snapshot position</th><th scope="col">Role</th><th scope="col">Player</th><th scope="col">Team</th><th scope="col">FPL availability</th><th scope="col">Price</th><th scope="col">Form</th><th scope="col">Points</th><th scope="col">GW estimate</th></tr></thead>
        <tbody>${listedPicks || '<tr><td colspan="9">No saved picks are available in this snapshot.</td></tr>'}</tbody></table></div>
      <p class="small squad-list-note">FPL <code>ep_next</code> is an estimate for the next round, not a points promise.</p>
    </div>
  </article>`;
}

export function mountSquadFormation(root: ParentNode): void {
  const buttons = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-squad-view]"));
  const panels = Array.from(root.querySelectorAll<HTMLElement>("[data-squad-panel]"));
  for (const button of buttons) {
    button.addEventListener("click", () => {
      const selected = button.dataset.squadView;
      for (const option of buttons) option.setAttribute("aria-pressed", String(option === button));
      for (const panel of panels) panel.hidden = panel.dataset.squadPanel !== selected;
    });
  }
}
