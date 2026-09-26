import type { PrivateTeamData, TeamDecisionPlayer } from "./app";
import { jerseySvg } from "./kits";
import type { LineupData, LineupPlayer } from "./lineup-helper";

type Ready = Extract<LineupData, { state: "ready" }>;
type Role = "GK" | "DEF" | "MID" | "FWD";
export interface BoardState { xi: number[]; bench: number[] }
export interface SwapResult { ok: boolean; state: BoardState; message: string }
export interface StorageLike { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void }

const LIMITS: Record<Role, [number, number]> = { GK: [1, 1], DEF: [3, 5], MID: [2, 5], FWD: [1, 3] };
const ROLE_ORDER: Role[] = ["FWD", "MID", "DEF", "GK"];
const STORAGE_VERSION = 1;
let mounted: AbortController | null = null;

function esc(value: unknown): string {
  return String(value ?? "—").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
}

export function boardPlayers(data: Ready): Map<number, LineupPlayer> {
  return new Map([...Object.values(data.lines).flat(), ...data.bench].map((player) => [player.id, player]));
}

export function suggestedState(data: Ready): BoardState {
  return { xi: (["GK", "DEF", "MID", "FWD"] as Role[]).flatMap((role) => data.lines[role].map((p) => p.id)), bench: data.bench.map((p) => p.id) };
}

export function formationOf(xi: number[], players: Map<number, LineupPlayer>): Record<Role, number> {
  const counts: Record<Role, number> = { GK: 0, DEF: 0, MID: 0, FWD: 0 };
  for (const id of xi) {
    const role = players.get(id)?.role as Role | undefined;
    if (role && role in counts) counts[role] += 1;
  }
  return counts;
}

export function isLegal(xi: number[], players: Map<number, LineupPlayer>): boolean {
  const counts = formationOf(xi, players);
  return xi.length === 11 && (Object.keys(LIMITS) as Role[]).every((role) => counts[role] >= LIMITS[role][0] && counts[role] <= LIMITS[role][1]);
}

/** Swap two magnets under FPL formation rules; illegal swaps return the unchanged state with a reason. */
export function swapMagnets(state: BoardState, a: number, b: number, players: Map<number, LineupPlayer>): SwapResult {
  const pa = players.get(a), pb = players.get(b);
  if (!pa || !pb || a === b) return { ok: false, state, message: "Pick two different players." };
  const aStarts = state.xi.includes(a), bStarts = state.xi.includes(b);
  if (aStarts && bStarts) return { ok: false, state, message: "Both are already starting." };
  if ((pa.role === "GK") !== (pb.role === "GK")) return { ok: false, state, message: "Keepers only swap with keepers." };
  if (!aStarts && !bStarts) {
    if (state.bench[0] === a || state.bench[0] === b) return { ok: false, state, message: "The backup keeper keeps the first bench slot." };
    const bench = state.bench.map((id) => (id === a ? b : id === b ? a : id));
    return { ok: true, state: { xi: [...state.xi], bench }, message: `Bench order: ${pb.name} and ${pa.name} swapped.` };
  }
  const starter = aStarts ? pa : pb, sub = aStarts ? pb : pa;
  const xi = state.xi.map((id) => (id === starter.id ? sub.id : id));
  const bench = state.bench.map((id) => (id === sub.id ? starter.id : id));
  if (!isLegal(xi, players)) {
    const counts = formationOf(xi, players);
    return { ok: false, state, message: `Not a legal formation (${counts.DEF}-${counts.MID}-${counts.FWD}). FPL needs 3–5 DEF, 2–5 MID, 1–3 FWD.` };
  }
  return { ok: true, state: { xi, bench }, message: `${sub.name} in, ${starter.name} to the bench.` };
}

export function boardTotal(state: BoardState, players: Map<number, LineupPlayer>): number {
  return Math.round(state.xi.reduce((sum, id) => sum + (players.get(id)?.estimate ?? 0), 0) * 100) / 100;
}

/** Warnings shown when a tried lineup benches the armband or starts a player FPL lists as out. */
export function boardWarnings(state: BoardState, data: Ready, players: Map<number, LineupPlayer>): string[] {
  const warnings: string[] = [];
  if (!state.xi.includes(data.captain.id)) warnings.push(`Your suggested captain ${data.captain.name} is on the bench.`);
  if (!state.xi.includes(data.vice.id)) warnings.push(`Vice-captain ${data.vice.name} is on the bench.`);
  const blocked = state.xi.map((id) => players.get(id)).filter((p): p is LineupPlayer => !!p && !p.eligible);
  if (blocked.length) warnings.push(`Starting a player FPL lists as out: ${blocked.map((p) => p.name).join(", ")}.`);
  return warnings;
}

export function storageKey(gameweek: number): string {
  return `fpl-brief:board:v${STORAGE_VERSION}:gw${gameweek}`;
}

/** Restore a saved board only if it holds exactly the current squad in a legal shape. */
export function loadBoard(storage: StorageLike | null | undefined, data: Ready, players: Map<number, LineupPlayer>): BoardState | null {
  try {
    const raw = storage?.getItem(storageKey(data.gameweek));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<BoardState>;
    const xi = parsed.xi, bench = parsed.bench;
    if (!Array.isArray(xi) || !Array.isArray(bench) || xi.length !== 11 || bench.length !== 4) return null;
    const ids = [...xi, ...bench];
    if (!ids.every((id) => Number.isInteger(id)) || new Set(ids).size !== 15 || !ids.every((id) => players.has(id))) return null;
    if (players.get(bench[0])?.role !== "GK" || !isLegal(xi, players)) return null;
    return { xi, bench };
  } catch {
    return null;
  }
}

export function saveBoard(storage: StorageLike | null | undefined, gameweek: number, state: BoardState | null): void {
  try {
    if (!storage) return;
    if (state) storage.setItem(storageKey(gameweek), JSON.stringify(state));
    else storage.removeItem(storageKey(gameweek));
  } catch {
    /* Storage can be unavailable (private mode); the board still works for this visit. */
  }
}

function sameState(a: BoardState, b: BoardState): boolean {
  return [...a.xi].sort().join() === [...b.xi].sort().join() && a.bench.join() === b.bench.join();
}

function magnet(player: LineupPlayer, data: Ready, keeper: boolean): string {
  const arm = player.id === data.captain.id ? '<span class="arm">C</span>' : player.id === data.vice.id ? '<span class="arm vice">V</span>' : "";
  const doubt = !player.eligible || player.flags.some((flag) => flag.startsWith("doubtful") || flag.startsWith("FPL status"));
  const label = `${player.name}, ${player.role}, ${player.team}, FPL estimate ${player.estimate}${doubt ? ", flagged" : ""}`;
  return `<button class="magnet${doubt ? " is-doubt" : ""}" type="button" data-id="${esc(player.id)}" aria-pressed="false" aria-label="${esc(label)}"><span class="magnet-base" aria-hidden="true"></span>${jerseySvg(player.team, keeper)}${arm}<span class="plate">${esc(player.name)}</span><span class="magnet-est">${esc(player.estimate)} est.${doubt ? ' · <span class="doubt-word">Doubtful</span>' : ""}</span></button>`;
}

function pitchRows(state: BoardState, players: Map<number, LineupPlayer>, data: Ready): string {
  const tops: Record<Role, number> = { FWD: 17, MID: 41, DEF: 65, GK: 88 };
  return ROLE_ORDER.map((role) => {
    const row = state.xi.map((id) => players.get(id)!).filter((p) => p.role === role).sort((a, b) => b.estimate - a.estimate || a.id - b.id);
    return `<div class="board-row" style="top:${tops[role]}%">${row.map((p) => magnet(p, data, role === "GK")).join("")}</div>`;
  }).join("");
}

function benchTray(state: BoardState, players: Map<number, LineupPlayer>, data: Ready): string {
  return state.bench.map((id, index) => `<div class="tray-slot"><span class="slot-label">${index === 0 ? "GK" : `Bench ${index}`}</span>${magnet(players.get(id)!, data, index === 0)}</div>`).join("");
}

function countdown(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(ms)) return "—";
  if (ms <= 0) return "Passed";
  const d = Math.floor(ms / 864e5), h = Math.floor(ms / 36e5) % 24, m = Math.floor(ms / 6e4) % 60;
  return d ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`;
}

const money = (tenths: unknown) => (typeof tenths === "number" && Number.isFinite(tenths) ? `£${(tenths / 10).toFixed(1)}m` : "—");

export function fixtureStrip(fixtures: LineupPlayer["next_fixtures"]): string {
  if (!fixtures?.length) return "";
  return `<ol class="fixture-strip" aria-label="Next fixtures">${fixtures.map((f) => `<li class="fdr-${f.difficulty ?? 0}"><span>GW${esc(f.gameweek)}</span> ${esc(f.opponent)} (${esc(f.venue)})<span class="visually-hidden">, FPL difficulty ${esc(f.difficulty ?? "unknown")}</span></li>`).join("")}</ol>`;
}

function captainShortlist(data: Ready, crowdNote: (id: number) => string): string {
  const options = data.captain_options ?? [];
  if (!options.length) return "";
  return `<section><h3>Captain shortlist</h3><ol class="captain-list">${options.map((o, index) => `<li><strong>${esc(o.name)}</strong> <span class="cap-est">${esc(o.estimate)} est.</span>${o.fixtures > 1 ? ' <span class="cap-dgw">double</span>' : ""}${index === 0 ? ' <span class="hand red">← armband</span>' : ""}${fixtureStrip(o.next_fixtures)}${crowdNote(o.id) ? `<span class="crowd-line">${esc(crowdNote(o.id))}</span>` : ""}</li>`).join("")}</ol><p class="fine">Ranked by FPL's estimate among fully available starters. Weigh the fixture and today's team news.</p></section>`;
}

function stats(data: Ready, account: PrivateTeamData | undefined): string {
  const ready = account?.usable === true;
  const free = ready && account.free_transfers !== undefined && account.free_transfers !== null ? (account.free_transfers === "unlimited" ? "Unlimited" : String(account.free_transfers)) : "—";
  const note = ready ? "" : '<span class="stat-note">needs a fresh account capture</span>';
  return `<dl class="board-stats"><div class="deadline"><dt>to GW${esc(data.gameweek)} deadline</dt><dd class="countdown" data-deadline="${esc(data.deadline_utc)}">${esc(countdown(data.deadline_utc))}</dd></div><div><dt>free transfers</dt><dd>${esc(free)}</dd>${note}</div><div><dt>in the bank</dt><dd>${esc(ready ? money(account.bank) : "—")}</dd></div><div><dt>XI FPL estimate</dt><dd class="board-total-value">${esc(data.xi_estimate_total)}</dd></div></dl>`;
}

export function renderTacticsBoard(data: LineupData | undefined, account?: PrivateTeamData, crowdNote: (id: number) => string = () => ""): string {
  if (!data) return "";
  if (data.state !== "ready") {
    return `<section class="tactics" aria-label="This week's board"><div class="board-head"><p>This week's board${data.gameweek ? ` · GW${esc(data.gameweek)}` : ""}</p></div><div class="board-frame"><div class="enamel board-notice"><p class="hand-note">Board wiped.</p><p>${esc(data.reason)}</p></div></div></section>`;
  }
  const c = data.changes;
  const change = [
    ...c.start.map((name) => `<li class="hand green">+ start ${esc(name)}</li>`),
    ...c.bench.map((name) => `<li class="hand red">− bench ${esc(name)}</li>`),
    ...(c.captain ? [`<li class="hand blue">C ${c.captain.from ? `${esc(c.captain.from)} → ` : ""}${esc(c.captain.to)}</li>`] : []),
    ...(c.vice ? [`<li class="hand blue">V ${c.vice.from ? `${esc(c.vice.from)} → ` : ""}${esc(c.vice.to)}</li>`] : []),
  ].join("");
  return `<section class="tactics" aria-label="This week's board" data-gw="${esc(data.gameweek)}">
    ${stats(data, account)}
    <div class="board-head"><p>Suggested ${esc(data.formation)} from FPL's own next-round estimates. Move the magnets to try your own XI.</p><div class="board-tools"><span class="board-total" aria-live="polite"></span><button class="button-secondary board-reset" type="button">Reset to suggestion</button></div></div>
    <div class="tactics-grid">
      <div class="board-frame">
        <div class="enamel"><div class="board-pitch">
          <svg class="pitch-print" viewBox="0 0 68 80" preserveAspectRatio="none" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width=".35"><rect x="2" y="2" width="64" height="76" rx=".6"/><rect x="16" y="2" width="36" height="13"/><rect x="26" y="2" width="16" height="5"/><path d="M27 15 A7 7 0 0 0 41 15"/><circle cx="34" cy="80" r="9"/></g></svg>
          <div class="board-rows"></div>
        </div></div>
        <div class="tray"><h3>Bench tray</h3><div class="tray-slots"></div></div>
        <svg class="marker-layer" aria-hidden="true"></svg>
        <p class="board-toast hand" role="status" aria-live="polite"></p>
      </div>
      <aside class="coach-notes" aria-labelledby="notes-title">
        <h2 id="notes-title">Coach's notes</h2>
        <p class="notes-src">Suggestion compared with ${esc(c.source)}.</p>
        <section><h3>Changes</h3>${c.none ? '<p class="hand green">No changes needed.</p>' : `<ul class="hand-list">${change}</ul>`}${c.bench_order_changed ? "<p>Bench order changes too.</p>" : ""}</section>
        <section><h3>Your board</h3><div class="board-summary" aria-live="polite"></div></section>
        ${captainShortlist(data, crowdNote)}
        <section><h3>Bench Boost</h3><p>${esc(data.bench_boost.hint)}</p></section>
        <section class="picked" aria-live="polite"><h3>Picked up</h3><div class="picked-body"><p>Pick up a shirt to see why it's there. Drag it, or select two shirts, to swap them.</p></div></section>
        <div class="jev"><p>Want today's team news and what the FPL community thinks weighed in?</p><button type="button" class="button-secondary" data-go="crowd" data-jev-ask="Who should I bench and captain this week, given the latest team news?">Ask Jev about this lineup</button></div>
        <p class="fine">Only saved in this browser. Make real changes in the FPL app. Estimates are FPL's own, not a forecast by this app.</p>
      </aside>
    </div>
  </section>`;
}

export function mountTacticsBoard(root: ParentNode, data: LineupData | undefined, context: TeamDecisionPlayer[] = [], storage: StorageLike | null = safeStorage(), crowdNote: (id: number) => string = () => ""): void {
  mounted?.abort();
  mounted = null;
  const section = root.querySelector<HTMLElement>(".tactics");
  if (!section || !data || data.state !== "ready") return;
  mounted = new AbortController();
  const signal = mounted.signal;
  const players = boardPlayers(data);
  const suggested = suggestedState(data);
  const notes = new Map(context.filter((row) => typeof row.id === "number").map((row) => [row.id as number, row]));
  let state = loadBoard(storage, data, players) ?? suggested;
  let selected: number | null = null;
  const rows = section.querySelector<HTMLElement>(".board-rows")!;
  const tray = section.querySelector<HTMLElement>(".tray-slots")!;
  const toast = section.querySelector<HTMLElement>(".board-toast")!;
  const layer = section.querySelector<SVGSVGElement>(".marker-layer")!;
  const frame = section.querySelector<HTMLElement>(".board-frame")!;

  const say = (message: string, bad = false) => {
    toast.textContent = message;
    toast.classList.toggle("bad", bad);
    toast.classList.remove("show");
    void toast.offsetWidth;
    toast.classList.add("show");
  };

  const drawMarkers = () => {
    const box = frame.getBoundingClientRect();
    layer.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
    const trayTop = section.querySelector<HTMLElement>(".tray")!.getBoundingClientRect().top - box.top;
    const current = new Set(data.changes.current_xi ?? []);
    const strokes: string[] = [];
    const notes: Array<{ cls: string; text: string; spots: Array<{ x: number; y: number; anchor: "start" | "end" }> }> = [];
    const incoming = state.xi.filter((id) => current.size && !current.has(id));
    incoming.forEach((id, index) => {
      const el = rows.querySelector<HTMLElement>(`.magnet[data-id="${id}"]`);
      if (!el) return;
      const r = el.getBoundingClientRect();
      const x = r.left - box.left + r.width / 2, y = r.bottom - box.top + 2;
      const wobble = (id % 7) - 3;
      strokes.push(`<path class="stroke green" d="M${x + 18} ${trayTop - 6} Q${x + 34 + wobble} ${(trayTop + y) / 2} ${x + 6} ${y + 4}"/><path class="stroke green" d="M${x + 1} ${y + 14} L${x + 6} ${y + 4} L${x + 15} ${y + 10}"/>`);
      const right = x + 18 < box.width * 0.62;
      const baseY = trayTop - 22 - index * 24;
      notes.push({ cls: "green", text: `IN: ${players.get(id)?.name ?? ""} ↑`, spots: [
        { x: right ? x + 30 : x + 6, y: baseY, anchor: right ? "start" : "end" },
        { x: right ? x + 6 : x + 30, y: baseY, anchor: right ? "end" : "start" },
        { x: right ? x + 30 : x + 6, y: (trayTop + y) / 2, anchor: right ? "start" : "end" },
        { x: 18, y: baseY, anchor: "start" },
        { x: box.width - 18, y: baseY, anchor: "end" },
      ] });
    });
    const captain = rows.querySelector<HTMLElement>(`.magnet[data-id="${data.captain.id}"]`);
    if (captain) {
      const r = captain.getBoundingClientRect();
      const cx = r.left - box.left + r.width / 2, cy = r.top - box.top + r.height * 0.42;
      strokes.push(`<ellipse class="stroke red" cx="${cx}" cy="${cy}" rx="${r.width * 0.56}" ry="${r.height * 0.58}" transform="rotate(-6 ${cx} ${cy})"/>`);
      const left = cx < box.width / 2;
      const side = r.width * 0.62;
      notes.push({ cls: "red", text: data.changes.captain ? `armband → ${data.captain.name}` : "captain", spots: [
        { x: left ? cx + side : cx - side, y: cy - r.height * 0.48, anchor: left ? "start" : "end" },
        { x: left ? cx - side : cx + side, y: cy - r.height * 0.48, anchor: left ? "end" : "start" },
        { x: cx, y: cy + r.height * 0.72, anchor: "start" },
        { x: left ? cx + side : cx - side, y: cy + r.height * 0.1, anchor: left ? "start" : "end" },
        { x: 18, y: 34, anchor: "start" },
        { x: box.width - 18, y: 34, anchor: "end" },
      ] });
    }
    layer.innerHTML = strokes.join("");
    // Place each note at the first spot that clears every shirt, plate and earlier note; skip it otherwise.
    const obstacles = [...rows.querySelectorAll<Element>(".magnet .jersey, .magnet .plate, .magnet .magnet-est, .magnet .arm")].map((el) => {
      const r = el.getBoundingClientRect();
      return { left: r.left - box.left - 2, right: r.right - box.left + 2, top: r.top - box.top - 2, bottom: r.bottom - box.top + 2 };
    });
    const hits = (a: { left: number; right: number; top: number; bottom: number }) =>
      a.left < 0 || a.right > box.width || a.top < 0 || obstacles.some((o) => a.left < o.right && a.right > o.left && a.top < o.bottom && a.bottom > o.top);
    for (const note of notes) {
      for (const spot of note.spots) {
        layer.insertAdjacentHTML("beforeend", `<text class="note ${note.cls}" x="${spot.x}" y="${spot.y}" text-anchor="${spot.anchor}">${esc(note.text)}</text>`);
        const text = layer.lastElementChild as SVGTextElement;
        const b = text.getBBox();
        const rect = { left: b.x, right: b.x + b.width, top: b.y, bottom: b.y + b.height };
        if (!hits(rect)) { obstacles.push(rect); break; }
        text.remove();
      }
    }
  };

  const summary = () => {
    const total = boardTotal(state, players);
    const delta = Math.round((total - data.xi_estimate_total) * 100) / 100;
    const counts = formationOf(state.xi, players);
    const warnings = boardWarnings(state, data, players);
    const edited = !sameState(state, suggested);
    section.querySelector<HTMLElement>(".board-total-value")!.textContent = String(total);
    section.querySelector<HTMLElement>(".board-total")!.textContent = edited ? `Your board: ${delta >= 0 ? "+" : ""}${delta} vs suggestion` : "";
    section.querySelector<HTMLElement>(".board-summary")!.innerHTML = `<p><strong>${counts.DEF}-${counts.MID}-${counts.FWD}</strong> · FPL estimate ${total}${edited ? ` · ${delta >= 0 ? "+" : ""}${delta} vs suggestion` : " · matches the suggestion"}</p>${warnings.map((w) => `<p class="warn-line">${esc(w)}</p>`).join("")}`;
    section.querySelector<HTMLButtonElement>(".board-reset")!.disabled = !edited;
  };

  const detail = (id: number) => {
    const p = players.get(id)!;
    const row = notes.get(id);
    const status = p.blockers.length ? p.blockers.join(", ") : p.flags.length ? p.flags.join(", ") : "Available";
    const crowdLine = crowdNote(id);
    const research = row?.research.filter((item) => !item.stale).slice(0, 2).map((item) => `<li><span class="src">${esc(item.publisher || "Source")} · captured, unverified</span> ${esc(item.text)}</li>`).join("") ?? "";
    section.querySelector<HTMLElement>(".picked-body")!.innerHTML = `<p class="picked-name">${esc(p.name)} <span>${esc(p.role)} · ${esc(p.team)}</span></p><p>${esc(p.reason)}</p>${fixtureStrip(p.next_fixtures)}${crowdLine ? `<p class="crowd-line">Crowd: ${esc(crowdLine)}</p>` : ""}<dl><dt>FPL estimate</dt><dd>${esc(p.estimate)}</dd><dt>Status</dt><dd>${esc(status)}</dd>${row?.news ? `<dt>FPL note</dt><dd>${esc(row.news)}</dd>` : ""}</dl>${research ? `<ul class="picked-news">${research}</ul>` : ""}`;
  };

  const render = () => {
    rows.innerHTML = pitchRows(state, players, data);
    tray.innerHTML = benchTray(state, players, data);
    if (selected !== null) section.querySelector(`.magnet[data-id="${selected}"]`)?.setAttribute("aria-pressed", "true");
    summary();
    requestAnimationFrame(drawMarkers);
  };

  const trySwap = (a: number, b: number) => {
    const result = swapMagnets(state, a, b, players);
    say(result.message, !result.ok);
    if (result.ok) {
      state = result.state;
      saveBoard(storage, data.gameweek, sameState(state, suggested) ? null : state);
    }
    selected = null;
    render();
    section.querySelector<HTMLElement>(`.magnet[data-id="${b}"]`)?.focus();
  };

  const refocus = (id: number) => section.querySelector<HTMLElement>(`.magnet[data-id="${id}"]`)?.focus();

  const putBack = (message: string) => {
    const id = selected;
    selected = null;
    render();
    if (id !== null) refocus(id);
    say(message);
  };

  const choose = (id: number) => {
    if (selected === null) {
      selected = id;
      detail(id);
      section.querySelectorAll(`.magnet[data-id="${id}"]`).forEach((el) => el.setAttribute("aria-pressed", "true"));
      say(`${players.get(id)!.name} picked up. Choose another shirt to swap, or press Escape.`);
    } else if (selected === id) {
      putBack("Put back.");
    } else {
      trySwap(selected, id);
    }
  };

  // Pointer drag with a floating shirt; a press without movement falls back to click-to-select.
  let drag: { id: number; x: number; y: number; ghost: HTMLElement | null; source: HTMLElement } | null = null;
  // A completed drag re-renders the shirts, so the browser's trailing click may or may not arrive; ignore clicks briefly instead of waiting for one.
  let ignoreClicksUntil = 0;
  const endDrag = () => {
    if (!drag) return null;
    const finished = drag;
    drag = null;
    finished.ghost?.remove();
    finished.source.classList.remove("is-lifted");
    section.classList.remove("is-dragging");
    return finished;
  };
  section.addEventListener("pointerdown", (event) => {
    const el = (event.target as HTMLElement).closest<HTMLElement>(".magnet");
    if (!el || event.button !== 0) return;
    drag = { id: Number(el.dataset.id), x: event.clientX, y: event.clientY, ghost: null, source: el };
  }, { signal });
  window.addEventListener("pointermove", (event) => {
    if (!drag) return;
    if (!(event.buttons & 1)) { if (!drag.ghost) drag = null; return; }
    if (!drag.ghost && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 8) return;
    if (!drag.ghost) {
      const ghost = drag.source.cloneNode(true) as HTMLElement;
      ghost.classList.add("magnet-ghost");
      ghost.setAttribute("aria-hidden", "true");
      ghost.setAttribute("tabindex", "-1");
      ghost.setAttribute("inert", "");
      ghost.removeAttribute("aria-label");
      document.body.appendChild(ghost);
      drag.ghost = ghost;
      drag.source.classList.add("is-lifted");
      section.classList.add("is-dragging");
    }
    drag.ghost.style.transform = `translate(${event.clientX - 60}px, ${event.clientY - 50}px) rotate(-4deg)`;
    event.preventDefault();
  }, { passive: false, signal });
  window.addEventListener("pointerup", (event) => {
    const finished = endDrag();
    if (!finished?.ghost) return;
    ignoreClicksUntil = performance.now() + 350;
    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>(".tactics .magnet");
    if (target && Number(target.dataset.id) !== finished.id) trySwap(finished.id, Number(target.dataset.id));
    else say("Dropped back in place.");
  }, { signal });
  const cancelDrag = () => { if (endDrag()?.ghost) say("Drag cancelled."); };
  window.addEventListener("pointercancel", cancelDrag, { signal });
  window.addEventListener("blur", cancelDrag, { signal });
  section.addEventListener("click", (event) => {
    if (performance.now() < ignoreClicksUntil) return;
    const el = (event.target as HTMLElement).closest<HTMLElement>(".magnet");
    if (el) choose(Number(el.dataset.id));
  }, { signal });
  section.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && selected !== null) putBack("Put back.");
  }, { signal });
  section.querySelector(".board-reset")!.addEventListener("click", () => {
    state = suggested;
    selected = null;
    saveBoard(storage, data.gameweek, null);
    render();
    say("Board reset to the suggestion.");
  }, { signal });
  window.addEventListener("resize", () => requestAnimationFrame(drawMarkers), { signal });
  const clock = section.querySelector<HTMLElement>(".countdown");
  if (clock) {
    const timer = window.setInterval(() => { clock.textContent = countdown(clock.dataset.deadline ?? ""); }, 30_000);
    signal.addEventListener("abort", () => window.clearInterval(timer));
  }
  render();
}

function safeStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}
