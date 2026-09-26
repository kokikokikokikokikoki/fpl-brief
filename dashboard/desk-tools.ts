import type { DashboardRuntime, Player, ViewId } from "./app";

interface ResearchExcerpt {
  text?: string;
  kind?: string;
  captured_at_utc?: string;
  player_id?: number;
  player_name?: string;
  team_name?: string;
}

interface ResearchClaim {
  claim?: string;
  verification_status?: string;
  reviewed_at_utc?: string | null;
  retrieved_at_utc?: string;
}

interface ResearchSource {
  id: string;
  publisher?: string;
  title?: string;
  url?: string;
  collection_state?: string;
  last_success_at_utc?: string | null;
  attempted_at_utc?: string | null;
  omitted_excerpts?: number;
  excerpts?: ResearchExcerpt[];
  claims?: ResearchClaim[];
}

interface SourceSummary {
  id: string;
  state?: string;
  stale?: boolean;
  stale_excerpt_indexes?: number[];
  stale_claim_indexes?: number[];
  last_success_at_utc?: string | null;
  attempted_at_utc?: string | null;
  omitted_excerpts?: number;
}

interface ResearchResponse {
  state: string;
  valid?: boolean;
  packet?: { sources?: ResearchSource[] };
  source_summaries?: SourceSummary[];
  warnings?: string[];
  latest_evidence_at_utc?: string | null;
  research_age_hours?: number | null;
  last_collection_at_utc?: string | null;
  snapshot_status?: { message?: string; age_hours?: number | null };
}

interface Candidate {
  id: number;
  team_id?: number | null;
  name: string;
  price: number;
  minutes: string | number;
  xgi_per_90?: string | number | null;
  fixture_difficulty_average?: string | number | null;
  availability: string;
}

interface CandidateResponse {
  candidates: Candidate[];
  budget: number;
  budget_source: "account" | "public";
  outgoing: { name?: string; selling_price: number };
  method: string;
  caveats: string[];
}

interface JobResponse {
  id: string;
  status: string;
  message?: string;
}

const SAFE_SOURCE_URLS = new Set([
  "https://fantasy.premierleague.com/api/bootstrap-static/",
  "https://www.arsenal.com/news/all/1",
]);

function escapeHtml(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character] ?? character);
}

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected dashboard error.";
}

function required<T extends Element>(selector: string, root: ParentNode = document): T {
  const found = root.querySelector<T>(selector);
  if (!found) throw new Error(`Dashboard element not found: ${selector}`);
  return found;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body: unknown = await response.json();
  if (!response.ok) {
    const error = typeof body === "object" && body !== null && "error" in body && typeof body.error === "string"
      ? body.error
      : "Request failed.";
    throw new Error(error);
  }
  return body as T;
}

export function mountDeskTools(runtime: DashboardRuntime): {
  openResearch(): Promise<void>;
  openLens(replacePlayerId?: number): void;
} {
  const nav = required<HTMLElement>("nav");
  const main = required<HTMLElement>("main");

  function addView(id: ViewId, label: string): void {
    if (document.querySelector(`[data-view="${id}"]`)) return;
    const button = document.createElement("button");
    button.className = "nav-link";
    button.dataset.view = id;
    button.textContent = label;
    nav.append(button);
    const view = document.createElement("section");
    view.id = id;
    view.className = "view";
    main.append(view);
  }

  function timeLabel(value?: string | null): string {
    if (typeof value !== "string" || !value) return "not recorded";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "invalid timestamp" : date.toLocaleString();
  }

  async function openResearch(): Promise<void> {
    runtime.activate("research");
    const view = required<HTMLElement>("#research");
    view.innerHTML = '<article class="panel"><h2>Research Desk</h2><button id="collect-research" class="button-primary">Collect fixed research now</button><p>Loading recorded source material.</p></article>';
    try {
      const result = await requestJson<ResearchResponse>("/api/research");
      const sources = result.valid === true && Array.isArray(result.packet?.sources) ? result.packet.sources : [];
      const summaries = new Map((result.source_summaries ?? []).map((summary) => [summary.id, summary]));
      const warnings = (result.warnings ?? []).map(escapeHtml).join(" ");
      const warningHtml = warnings ? `<div class="evidence-warning" role="alert">${warnings}</div>` : "";
      const researchFreshness = result.latest_evidence_at_utc
        ? `Research evidence: latest usable item captured ${escapeHtml(timeLabel(result.latest_evidence_at_utc))} · ${escapeHtml(result.research_age_hours)} hours old (${escapeHtml(result.state)}).`
        : `Research evidence: ${escapeHtml(result.state)} · no usable item timestamp.`;
      const snapshot = result.snapshot_status ?? {};
      const snapshotFreshness = `FPL snapshot: ${escapeHtml(snapshot.message || "Snapshot freshness unavailable.")}${snapshot.age_hours == null ? "" : ` (${escapeHtml(snapshot.age_hours)} hours old).`}`;
      const freshnessHtml = `<p class="small"><strong>${researchFreshness}</strong><br>${snapshotFreshness}<br>These are separate data sources and timestamps.</p>`;
      const stateMessages: Record<string, string> = {
        missing: "No research collection has been recorded yet.",
        empty: "No usable evidence is available. Check whether sources were configured and whether the last collection returned any items.",
        failed: "The latest collection did not retrieve evidence successfully.",
        stale: "Only stale research evidence is available; collect again before relying on it.",
        invalid: "The saved research packet is invalid and cannot be treated as current.",
        ready: "Research evidence was captured. Captured text is not independently verified.",
      };
      const stateHtml = `<p class="small"><strong>Collection status: ${escapeHtml(result.state)}.</strong> ${escapeHtml(stateMessages[result.state] || "Research collection state is unavailable.")} Last collection attempt: ${escapeHtml(timeLabel(result.last_collection_at_utc))}.</p>`;
      const evidence = sources.length ? sources.map((source) => {
        const summary: SourceSummary = summaries.get(source.id) ?? { id: source.id };
        const sourceState = summary.state || source.collection_state || "unknown";
        const stale = summary.stale ? " stale" : "";
        const staleExcerpts = new Set(summary.stale_excerpt_indexes ?? []);
        const staleClaims = new Set(summary.stale_claim_indexes ?? []);
        const excerpts = (source.excerpts ?? []).map((item, index) => {
          if (typeof item.text !== "string") return "";
          const identity = item.player_id
            ? item.player_name || `Unknown player (FPL ID ${item.player_id})`
            : "Unlinked item";
          const club = item.team_name || "Club unknown";
          const kind = item.kind === "player_news" ? "Official FPL player news" : item.kind === "json_field" ? "Source excerpt" : item.kind || "Source excerpt";
          const evidenceState = staleExcerpts.has(index) ? "stale captured, unverified" : "captured, unverified";
          return `<li><span class="evidence-label">${escapeHtml(kind)} · ${evidenceState}</span><br><span class="small">${escapeHtml(identity)} · ${escapeHtml(club)} · captured ${escapeHtml(timeLabel(item.captured_at_utc))}</span><br>${escapeHtml(item.text)}</li>`;
        }).join("");
        const claims = (source.claims ?? []).map((claim, index) => {
          if (typeof claim.claim !== "string") return "";
          const claimState = claim.verification_status === "reviewed" ? "reviewed claim" : "unverified claim";
          const evidenceState = staleClaims.has(index) ? `stale ${claimState}` : claimState;
          const reviewedAt = claim.reviewed_at_utc ? ` · reviewed ${escapeHtml(timeLabel(claim.reviewed_at_utc))}` : "";
          return `<li><span class="evidence-label">${escapeHtml(evidenceState)}</span><br><span class="small">captured ${escapeHtml(timeLabel(claim.retrieved_at_utc))}${reviewedAt}</span><br>${escapeHtml(claim.claim)}</li>`;
        }).join("");
        const sourceTitle = source.title || (source.id === "official-fpl-news" ? "Official FPL player news" : `${source.publisher || "Research source"} source material`);
        const isSafeLink = sourceState !== "rejected" && typeof source.url === "string" && /^https:\/\//i.test(source.url) && SAFE_SOURCE_URLS.has(source.url);
        const sourceLabel = `${escapeHtml(source.publisher || "Unknown publisher")} · ${escapeHtml(sourceTitle)}`;
        const sourceHeading = isSafeLink ? `<a href="${escapeHtml(source.url)}" rel="noreferrer" target="_blank">${sourceLabel}</a>` : sourceLabel;
        const omission = Number.isInteger(source.omitted_excerpts) && (source.omitted_excerpts ?? 0) > 0
          ? `<p class="small">${escapeHtml(source.omitted_excerpts)} additional source item(s) omitted by the display cap.</p>`
          : "";
        const attempt = source.attempted_at_utc ? ` · last attempt ${escapeHtml(timeLabel(source.attempted_at_utc))}` : "";
        const items = excerpts || claims ? `<ul>${excerpts}${claims}</ul>` : '<p class="small">No usable excerpts recorded for this source.</p>';
        return `<article class="evidence-source ${escapeHtml(sourceState)}${stale}"><h3>${sourceHeading}</h3><p class="small">Latest attempt: ${escapeHtml(sourceState)} · Last successful capture: ${escapeHtml(timeLabel(source.last_success_at_utc))}${attempt}${summary.stale ? " · retained evidence is stale" : ""}</p>${omission}${items}</article>`;
      }).join("") : result.state === "invalid"
        ? '<div class="empty"><strong>Saved research packet is invalid</strong><span>Source records are hidden because validation failed.</span></div>'
        : '<div class="empty"><strong>No configured research sources</strong><span>Run the local Research Scout to collect attributable source material.</span></div>';
      view.innerHTML = `<article class="panel"><div class="panel-head"><div><h2>Research Desk</h2><button id="collect-research" class="button-primary">Collect fixed research now</button><p>Collection records source material; it does not create forecasts or recommendations. Research is ephemeral on Railway and may need to be collected again after restart.</p></div></div>${freshnessHtml}${stateHtml}${warningHtml}${evidence}</article>`;
    } catch (error) {
      view.innerHTML = `<div class="empty"><strong>Research unavailable</strong><span>${escapeHtml(messageFrom(error))}</span></div>`;
    }
  }

  function squadOptions(): string {
    const data = runtime.state.data;
    if (!data) return "";
    const players = new Map(data.catalog.players.map((player) => [player.id, player]));
    return data.snapshot.squad_snapshot.picks.map((pick) => {
      const player: Player | undefined = players.get(pick.element);
      return `<option value="${pick.element}">${escapeHtml(player?.web_name || "Unknown")} (${escapeHtml(player?.id ?? "Unknown")})</option>`;
    }).join("");
  }

  async function runLens(): Promise<void> {
    const view = required<HTMLElement>("#candidates");
    const replaceId = required<HTMLSelectElement>("#candidate-replace", view).value;
    const minimum = required<HTMLSelectElement>("#candidate-minutes", view).value;
    const output = required<HTMLElement>("#candidate-output", view);
    output.innerHTML = "<p>Finding legal replacements.</p>";
    try {
      const result = await requestJson<CandidateResponse>(`/api/candidates?replace_id=${encodeURIComponent(replaceId)}&minimum_minutes=${encodeURIComponent(minimum)}`);
      const rows = result.candidates.length
        ? result.candidates.map((player) => `<tr><td><span class="row-kit">${runtime.kit ? runtime.kit(player.team_id) : ""}</span><span class="player-name">${escapeHtml(player.name)}</span></td><td>£${(player.price / 10).toFixed(1)}m</td><td>${escapeHtml(player.minutes)}</td><td>${escapeHtml(player.xgi_per_90 ?? "-")}</td><td>${escapeHtml(player.fixture_difficulty_average ?? "-")}</td><td>${escapeHtml(player.availability)}</td><td>${runtime.planTransfer ? `<button class="button-secondary try-board" type="button" data-try-in="${escapeHtml(player.id)}" aria-label="Try ${escapeHtml(player.name)} on the board">Try on board</button>` : ""}</td></tr>`).join("")
        : '<tr><td colspan="7">No players meet every selected filter.</td></tr>';
      const money = (tenths: number): string => `£${(tenths / 10).toFixed(1)}m`;
      const budget = `<p><strong>Budget ${escapeHtml(money(result.budget))}</strong> = ${escapeHtml(result.outgoing.name ?? "outgoing player")} selling price ${escapeHtml(money(result.outgoing.selling_price))} + bank (${result.budget_source === "account" ? "from your FPL account" : "from the public snapshot"}).</p>`;
      output.innerHTML = `${budget}<p class="method">${escapeHtml(result.method)}</p><p class="small">${result.caveats.map(escapeHtml).join(" ")}</p><div class="table-wrap"><table><thead><tr><th>Player</th><th>Price</th><th>Minutes</th><th>xGI/90</th><th>Avg FDR</th><th>Availability</th><th><span class="visually-hidden">Plan</span></th></tr></thead><tbody>${rows}</tbody></table></div>`;
      output.querySelectorAll<HTMLButtonElement>("[data-try-in]").forEach((button) => {
        button.onclick = () => {
          const problem = runtime.planTransfer?.(Number(replaceId), Number(button.dataset.tryIn));
          if (problem) runtime.status(problem);
        };
      });
    } catch (error) {
      output.innerHTML = `<div class="evidence-warning" role="alert">${escapeHtml(messageFrom(error))}</div>`;
    }
  }

  function openLens(replacePlayerId?: number): void {
    runtime.activate("candidates");
    const view = required<HTMLElement>("#candidates");
    view.innerHTML = `<article class="panel"><div class="panel-head"><div><h2>Candidate Lens</h2><p>Legal same-position replacements only. It ranks visible inputs, not predicted points.</p></div></div><div class="lens-controls"><label>Replace<select id="candidate-replace">${squadOptions()}</select></label><label>Minimum minutes<select id="candidate-minutes"><option value="0">Any minutes</option><option value="450">450+</option><option value="900">900+</option></select></label><button id="candidate-run" class="button-primary">Find candidates</button></div><div id="candidate-output" class="lens-output"><p class="small">Budget uses the outgoing player's selling price plus bank from your captured FPL account data. Without a fresh capture, Candidate Lens stays blocked rather than guessing.</p></div></article>`;
    if (replacePlayerId !== undefined) {
      const select = required<HTMLSelectElement>("#candidate-replace", view);
      if (Array.from(select.options).some((option) => option.value === String(replacePlayerId))) select.value = String(replacePlayerId);
    }
    required<HTMLButtonElement>("#candidate-run", view).addEventListener("click", () => { void runLens(); });
  }

  document.addEventListener("click", (event: MouseEvent) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement) || target.id !== "collect-research") return;
    target.disabled = true;
    const button = target;
    void (async () => {
      try {
        let job = await requestJson<JobResponse>("/api/research", { method: "POST" });
        while (job.status === "running") {
          await new Promise((resolve) => window.setTimeout(resolve, 800));
          job = await requestJson<JobResponse>(`/api/jobs/${encodeURIComponent(job.id)}`);
        }
        if (job.status !== "complete") throw new Error(job.message || "Research collection failed.");
        await openResearch();
      } catch (error) {
        button.textContent = messageFrom(error);
      } finally {
        button.disabled = false;
      }
    })();
  });

  addView("research", "Research desk");
  addView("candidates", "Candidate lens");
  return { openResearch, openLens };
}
