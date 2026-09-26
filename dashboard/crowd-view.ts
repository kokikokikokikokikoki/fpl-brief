// "What the internet thinks": official FPL crowd data plus the Ask Jev panel (Claude + web search).
export interface CrowdRow {
  id: number;
  name: string | null;
  team: string | null;
  price: number | null;
  ownership: number | null;
  transfers_in: number | null;
  transfers_out: number | null;
  net_transfers: number | null;
  price_change_event: number | null;
  rival_owners?: number | null;
}
interface EventSummary {
  gameweek: number; label: string; most_captained: string | null; most_selected: string | null;
  most_transferred_in: string | null; top_scorer: string | null; transfers_made: number | null;
  average_score: number | null; chip_plays: Array<{ chip: string; played: number }>;
}
export type CrowdData =
  | { state: "unavailable"; reason: string }
  | {
    state: "ready"; gameweek: number | null; transfers_in: CrowdRow[]; transfers_out: CrowdRow[];
    risers: CrowdRow[]; fallers: CrowdRow[]; events: EventSummary[];
    squad: Record<string, CrowdRow>; league: { rivals_compared: number; missing: CrowdRow[] }; method: string;
  };
export interface JevInfo { enabled: boolean; daily_limit: number }
interface JevResult { answer: string; sources: Array<{ url: string; title: string }>; searches: number }
interface Job { id: string; status: string; message?: string; result?: JevResult; error?: string }

const CHIPS: Record<string, string> = { bboost: "Bench Boost", "3xc": "Triple Captain", wildcard: "Wildcard", freehit: "Free Hit", manager: "Assistant Manager" };
export const QUICK_PROMPTS = [
  "Who should I captain this week, and why?",
  "Is there injury or team news on my flagged players?",
  "Who should I bench this week?",
  "Is my planned transfer a good idea?",
];

function esc(value: unknown): string {
  return String(value ?? "—").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
}
const money = (tenths: number | null) => (typeof tenths === "number" ? `£${(tenths / 10).toFixed(1)}m` : "—");
const signed = (n: number | null) => (typeof n === "number" ? `${n >= 0 ? "+" : "−"}${Math.abs(n).toLocaleString("en-GB")}` : "—");

/** One-line crowd note for a player, shared by the board and the Crowd view. */
export function crowdNote(row: CrowdRow | undefined): string {
  if (!row) return "";
  const parts: string[] = [];
  if (typeof row.ownership === "number") parts.push(`${row.ownership}% own`);
  if (typeof row.net_transfers === "number") parts.push(`${signed(row.net_transfers)} net transfers this GW`);
  if (row.price_change_event) parts.push(`price ${row.price_change_event > 0 ? "+" : "−"}£${(Math.abs(row.price_change_event) / 10).toFixed(1)}m this GW`);
  if (typeof row.rival_owners === "number") parts.push(`${row.rival_owners} league rival${row.rival_owners === 1 ? "" : "s"} own`);
  return parts.join(" · ");
}

function table(title: string, caption: string, rows: CrowdRow[], column: "in" | "out" | "price" | "league"): string {
  const head = column === "league" ? "<th>Rivals who own</th><th>Own</th>" : column === "price" ? "<th>Price move</th><th>Net transfers</th>" : `<th>${column === "in" ? "Bought" : "Sold"}</th><th>Own</th>`;
  const body = rows.length ? rows.map((r) => {
    const cells = column === "league" ? `<td>${esc(r.rival_owners)}</td><td>${esc(r.ownership)}%</td>`
      : column === "price" ? `<td>${r.price_change_event && r.price_change_event > 0 ? "+" : "−"}£${(Math.abs(r.price_change_event ?? 0) / 10).toFixed(1)}m</td><td>${esc(signed(r.net_transfers))}</td>`
        : `<td>${esc((column === "in" ? r.transfers_in : r.transfers_out)?.toLocaleString("en-GB"))}</td><td>${esc(r.ownership)}%</td>`;
    return `<tr><td><span class="player-name">${esc(r.name)}</span><span class="sub">${esc(r.team)} · ${esc(money(r.price))}</span></td>${cells}</tr>`;
  }).join("") : '<tr><td colspan="3">Nothing to show yet.</td></tr>';
  return `<article class="panel crowd-table"><div class="panel-head"><div><h2>${esc(title)}</h2><p>${esc(caption)}</p></div></div><div class="table-wrap"><table><thead><tr><th>Player</th>${head}</tr></thead><tbody>${body}</tbody></table></div></article>`;
}

export function renderJevPanel(jev: JevInfo | undefined, hasPlan: boolean): string {
  if (!jev?.enabled) {
    return `<section class="panel jev-panel" aria-labelledby="jev-title"><div class="panel-head"><div><h2 id="jev-title">Ask Jev</h2><p>Searches the web and sums up what people are saying about your picks.</p></div></div><p class="evidence-warning">Jev isn't set up on this site yet. Add an <strong>ANTHROPIC_API_KEY</strong> in the host settings (Render → fpl-brief → Environment) to switch it on. Meanwhile, ask Jev in Claude Code.</p></section>`;
  }
  return `<section class="panel jev-panel" aria-labelledby="jev-title">
    <div class="panel-head"><div><h2 id="jev-title">Ask Jev</h2><p>Searches the web (press conferences, injury news, FPL community) and sums up what people are saying, with sources. Internet opinion, not verified news; you make the call.</p></div></div>
    <div class="jev-prompts">${QUICK_PROMPTS.map((q) => `<button type="button" class="button-secondary" data-jev-prompt="${esc(q)}">${esc(q)}</button>`).join("")}</div>
    <label for="jev-question" class="visually-hidden">Your question for Jev</label>
    <textarea id="jev-question" rows="2" maxlength="500" placeholder="Ask about your team, a captain pick, a transfer…"></textarea>
    <div class="jev-row">${hasPlan ? '<label class="jev-plan"><input type="checkbox" id="jev-include-plan" checked> Include my planned transfers</label>' : ""}<button id="jev-ask" type="button" class="button-primary">Ask Jev</button></div>
    <p class="fine">Up to ${esc(jev.daily_limit)} questions a day. Each uses a few paid web searches on your Anthropic account.</p>
    <div id="jev-answer" class="jev-answer" aria-live="polite"></div>
  </section>`;
}

export function renderCrowd(crowd: CrowdData | undefined, jev: JevInfo | undefined, hasPlan: boolean): string {
  const jevPanel = renderJevPanel(jev, hasPlan);
  if (!crowd || crowd.state !== "ready") {
    return `${jevPanel}<article class="panel"><p class="evidence-warning">${esc(crowd?.reason ?? "Crowd data is unavailable.")}</p></article>`;
  }
  const event = crowd.events[0];
  const last = crowd.events.find((e) => e.label === "last gameweek");
  const facts = [
    event ? `<div><span class="metric-label">Transfers made · GW${esc(event.gameweek)}</span><strong>${esc(event.transfers_made?.toLocaleString("en-GB"))}</strong></div>` : "",
    last ? `<div><span class="metric-label">Most captained · GW${esc(last.gameweek)}</span><strong>${esc(last.most_captained)}</strong></div>` : "",
    last ? `<div><span class="metric-label">Top scorer · GW${esc(last.gameweek)}</span><strong>${esc(last.top_scorer)}</strong></div>` : "",
    last?.chip_plays.length ? `<div><span class="metric-label">Chips played · GW${esc(last.gameweek)}</span><strong>${last.chip_plays.slice(0, 2).map((c) => `${esc(CHIPS[c.chip] ?? c.chip)} ${esc(c.played.toLocaleString("en-GB"))}`).join(" · ")}</strong></div>` : "",
  ].join("");
  return `${jevPanel}
    <div class="crowd-facts">${facts}</div>
    <div class="grid equal">${table("Most bought", `This gameweek so far (GW${crowd.gameweek ?? "?"}).`, crowd.transfers_in, "in")}${table("Most sold", "This gameweek so far.", crowd.transfers_out, "out")}</div>
    <div class="grid equal">${table("Your mini-league has, you don't", `Owned by your ${crowd.league.rivals_compared} compared rivals: differentials to cover or keep.`, crowd.league.missing, "league")}${table("Price risers", "Rose this gameweek: hype and demand.", crowd.risers, "price")}</div>
    <p class="method">${esc(crowd.method)}</p>`;
}

function formatAnswer(text: string): string {
  const blocks = text.split(/\n{2,}/);
  return blocks.map((block) => {
    const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
    if (lines.length && lines.every((l) => /^[-•*]\s+/.test(l))) {
      return `<ul>${lines.map((l) => `<li>${esc(l.replace(/^[-•*]\s+/, ""))}</li>`).join("")}</ul>`;
    }
    return `<p>${lines.map(esc).join("<br>")}</p>`;
  }).join("");
}

export function renderJevAnswer(result: JevResult): string {
  const safe = result.sources.filter((s) => /^https?:\/\//i.test(s.url));
  const sources = safe.length ? `<h3>Sources</h3><ol class="jev-sources">${safe.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a></li>`).join("")}</ol>` : "";
  return `<div class="jev-result">${formatAnswer(result.answer)}${sources}<p class="fine">Internet opinion via Claude web search (${esc(result.searches)} search${result.searches === 1 ? "" : "es"}): unverified. Check official team news before deciding.</p></div>`;
}

/** Wire the Ask Jev panel; planQuery returns the saved plan as "OUT:IN,..." or "". */
export function mountJev(root: ParentNode, planQuery: () => string): void {
  const box = root.querySelector<HTMLTextAreaElement>("#jev-question");
  const button = root.querySelector<HTMLButtonElement>("#jev-ask");
  const output = root.querySelector<HTMLElement>("#jev-answer");
  if (!box || !button || !output) return;
  root.querySelectorAll<HTMLButtonElement>("[data-jev-prompt]").forEach((prompt) => {
    prompt.onclick = () => { box.value = prompt.dataset.jevPrompt ?? ""; box.focus(); };
  });
  button.onclick = async () => {
    const question = box.value.trim();
    if (question.length < 3) { output.innerHTML = '<p class="evidence-warning">Type a question first.</p>'; return; }
    const include = root.querySelector<HTMLInputElement>("#jev-include-plan")?.checked;
    button.disabled = true;
    output.innerHTML = '<p class="jev-wait">Jev is searching the web… this usually takes 20–60 seconds.</p>';
    try {
      const start = await fetch("/api/jev", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, transfers: include ? planQuery() : "" }) });
      if (start.status === 401) { window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`); return; }
      let job = (await start.json()) as Job;
      if (!start.ok) throw new Error(job.error ?? "Jev couldn't start.");
      for (let i = 0; i < 90 && job.status === "running"; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const poll = await fetch(`/api/jobs/${encodeURIComponent(job.id)}`);
        if (poll.status === 401) { window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`); return; }
        job = (await poll.json()) as Job;
      }
      if (job.status === "complete" && job.result) output.innerHTML = renderJevAnswer(job.result);
      else if (job.status === "running") throw new Error("Jev is taking longer than usual. Try again in a minute.");
      else throw new Error(job.message ?? "Jev couldn't answer. Try again.");
    } catch (error) {
      output.innerHTML = `<p class="evidence-warning" role="alert">${esc(error instanceof Error ? error.message : "Jev couldn't answer.")}</p>`;
    } finally {
      button.disabled = false;
    }
  };
}
