const KEY = "travel-dashboard-v1";
const state = { setup: null, snapshot: null, drafts: [], packet: null };`r`nconst SAFE_RESEARCH_URLS = ["https://fantasy.premierleague.com/api/bootstrap-static/", "https://www.arsenal.com/news/all/1"];
const esc = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;" }[c]));
const safeLink = (url, stateName) => stateName !== "rejected" && SAFE_RESEARCH_URLS.includes(String(url || "")) ? esc(url) : null;
function load() { try { const raw = JSON.parse(localStorage.getItem(KEY) || "{}"); if (!raw || typeof raw !== "object") return {}; return { setup: raw.setup && typeof raw.setup === "object" ? raw.setup : null, snapshot: raw.snapshot && typeof raw.snapshot === "object" ? raw.snapshot : null, drafts: Array.isArray(raw.drafts) ? raw.drafts.filter((draft) => draft && typeof draft === "object").map((draft) => ({ name: String(draft.name || "Untitled draft").slice(0, 80), players: Array.isArray(draft.players) ? draft.players : [] })) : [], packet: raw.packet && typeof raw.packet === "object" && Array.isArray(raw.packet.sources) ? raw.packet : null }; } catch { return {}; } }
function save() { localStorage.setItem(KEY, JSON.stringify({ setup: state.setup, snapshot: state.snapshot, drafts: state.drafts, packet: state.packet })); }
function decision(snapshot) {
  if (!snapshot) return null;
  const picks = snapshot.squad_snapshot && snapshot.squad_snapshot.picks || [];
  const generated = Date.parse(snapshot.generated_at_utc || "");
  const next = snapshot.events && snapshot.events.next;
  const blockers = [];
  if (!Number.isFinite(generated) || Date.now() - generated > 8 * 3600000) blockers.push("Refresh the public snapshot before deciding.");
  if (picks.length !== 15) blockers.push("The public squad snapshot is incomplete.");
  if (!next || !Date.parse(next.deadline_time)) blockers.push("The next FPL deadline is unavailable.");
  else if (Date.parse(next.deadline_time) <= Date.now()) blockers.push("The next FPL deadline has passed.");
  return { blockers: blockers, status: blockers.length ? "blocked" : "ready" };
}
function render() {
  const d = state.snapshot;
  const result = decision(d);
  const sources = state.packet && Array.isArray(state.packet.sources) ? state.packet.sources : [];
  const research = sources.map((source) => {
    const link = safeLink(source.url, source.collection_state);
    const title = esc(source.publisher) + " · " + esc(source.title || "Untitled");
    const heading = link ? "<a href=\"" + link + "\" rel=\"noreferrer\">" + title + "</a>" : title;
    const excerpts = (source.excerpts || []).map((item) => "<blockquote><small>" + esc(item.kind) + " · unverified captured text</small><br>" + esc(item.text) + "</blockquote>").join("");
    const claims = (source.claims || []).map((claim) => "<blockquote><small>" + esc(claim.verification_status || "claim") + "</small><br>" + esc(claim.claim) + "</blockquote>").join("");
    return "<article><h3>" + heading + "</h3><p>" + esc(source.collection_state) + " · " + esc(source.last_success_at_utc || "No successful retrieval") + "</p>" + excerpts + claims + "</article>";
  }).join("") || "<p>No device-local research packet.</p>";
  const drafts = state.drafts.map((draft, index) => "<article><input data-draft=\"" + index + "\" value=\"" + esc(draft.name) + "\"><button data-save=\"" + index + "\">Save</button><button data-delete=\"" + index + "\">Delete</button></article>").join("");
  document.querySelector("#app").innerHTML = "<section><h1>Travel Dashboard</h1><p>Device-local state only; drafts, snapshots, and research packets do not sync across devices.</p><form id=\"setup\"><label>Team ID <input name=\"team_id\" inputmode=\"numeric\" required></label><label>League ID <input name=\"league_id\" inputmode=\"numeric\" required></label><button>Save setup</button></form><button id=\"refresh\">Refresh public snapshot</button><button id=\"research\">Collect fixed official research</button><button id=\"lens\">Run Candidate Lens</button><button id=\"draft\">Add draft</button><div id=\"lens-output\"></div><p class=\"warning\">" + esc(result ? result.blockers.join(" ") : "") + "</p><pre>" + esc(JSON.stringify(d ? d.league : {}, null, 2)) + "</pre><section><h2>Research Desk</h2>" + research + "</section><section><h2>Draft scenarios</h2>" + drafts + "</section></section>";
  document.querySelector("#setup").onsubmit = (event) => { event.preventDefault(); state.setup = { team_id: event.target.team_id.value, league_id: event.target.league_id.value }; save(); render(); };
  document.querySelector("#refresh").onclick = async () => { if (!state.setup) return; const response = await fetch("/api/refresh?team_id=" + encodeURIComponent(state.setup.team_id) + "&league_id=" + encodeURIComponent(state.setup.league_id), { method: "POST" }); if (response.ok) { state.snapshot = await response.json(); save(); render(); } };
  document.querySelector("#research").onclick = async () => { const response = await fetch("/api/research", { method: "POST" }); if (response.ok) { state.packet = await response.json(); save(); render(); } };
  document.querySelector("#lens").onclick = async () => { const pick = state.snapshot && state.snapshot.squad_snapshot && state.snapshot.squad_snapshot.picks && state.snapshot.squad_snapshot.picks[0]; if (!state.snapshot || !pick) return; const response = await fetch("/api/candidates", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ snapshot: state.snapshot, catalog: state.snapshot.catalog, replace_id: pick.element, options: { minimumMinutes: Math.max(0, Number(document.querySelector("#minimum-minutes").value) || 0) } }) }); const body = await response.json(); document.querySelector("#lens-output").textContent = response.ok ? JSON.stringify(body) : "Candidate Lens blocked: " + (body.error || "unavailable"); };
  document.querySelector("#draft").onclick = () => { state.drafts.push({ name: "Untitled draft", players: [] }); save(); render(); };
  document.querySelectorAll("[data-save]").forEach((button) => button.onclick = () => { state.drafts[Number(button.dataset.save)].name = document.querySelector("[data-draft=\"" + button.dataset.save + "\"]").value.slice(0, 80); save(); render(); });
  document.querySelectorAll("[data-delete]").forEach((button) => button.onclick = () => { state.drafts.splice(Number(button.dataset.delete), 1); save(); render(); });
}
Object.assign(state, load());
render();

