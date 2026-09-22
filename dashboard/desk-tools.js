(() => {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const section = (id) => document.querySelector(`#${id}`);

  function addView(id, label, open) {
    const nav = document.querySelector("nav");
    const button = document.createElement("button");
    button.className = "nav-link";
    button.dataset.view = id;
    button.textContent = label;
    nav.append(button);
    const view = document.createElement("section");
    view.id = id;
    view.className = "view";
    document.querySelector("main").append(view);
    button.addEventListener("click", open);
  }

  function activate(id) {
    if (typeof state === "undefined" || !state.data) return;
    state.active = id;
    render();
    window.scrollTo({top: 0, behavior: "smooth"});
  }

  async function openResearch() {
    activate("research");
    const view = section("research");
    view.innerHTML = '<article class="panel"><h2>Research Desk</h2><button id="collect-research" class="button-primary">Collect fixed research now</button><p>Loading recorded source material.</p></article>';
    try {
      const result = await fetch("/api/research").then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw Error(body.error || "Research is unavailable.");
        return body;
      });
      const sources = Array.isArray(result.packet?.sources) ? result.packet.sources.filter((source) => source && typeof source === "object") : [];
      const summaries = Object.fromEntries((result.source_summaries || []).map((item) => [item.id, item]));
      const warnings = (result.warnings || []).map(esc).join(" ");
      const warningHtml = warnings ? '<div class="evidence-warning" role="alert">' + warnings + '</div>' : "";
      const evidence = sources.length ? sources.map((source) => {
        const summary = summaries[source.id] || {};
        const state = summary.state || source.collection_state || "unknown";
        const stale = summary.stale ? " stale" : "";
        const excerpts = Array.isArray(source.excerpts) ? source.excerpts.filter((item) => item && typeof item.text === "string").map((item) => '<li><span class="evidence-label">' + esc(item.kind) + ' · unverified captured text</span><br>' + esc(item.text) + '</li>').join("") : "";
        const claims = Array.isArray(source.claims) ? source.claims.filter((claim) => claim && typeof claim.claim === "string").map((claim) => '<li><span class="evidence-label">' + esc(claim.verification_status === "reviewed" ? "reviewed claim" : "unverified claim") + '</span><br>' + esc(claim.claim) + '</li>').join("") : "";
        const safeLink = state !== "rejected" && typeof source.url === "string" && /^https:\/\//i.test(source.url) && ["https://fantasy.premierleague.com/api/bootstrap-static/", "https://www.arsenal.com/news/all/1"].includes(source.url) ? '<a href="' + esc(source.url) + '" rel="noreferrer" target="_blank">' + esc(source.publisher) + ' · ' + esc(source.title || "Untitled source") + '</a>' : esc(source.publisher) + ' · ' + esc(source.title || "Untitled source");
        return '<article class="evidence-source ' + esc(state) + stale + '"><h3>' + safeLink + '</h3><p class="small">State: ' + esc(state) + ' · Last success: ' + esc(source.last_success_at_utc || "None") + (summary.stale ? " · stale" : "") + '</p><ul>' + excerpts + claims + '</ul></article>';
      }).join("") : '<div class="empty"><strong>No configured research sources</strong><span>Run the local Research Scout to collect attributable source material.</span></div>';
      view.innerHTML = '<article class="panel"><div class="panel-head"><div><h2>Research Desk</h2><button id="collect-research" class="button-primary">Collect fixed research now</button><p>Collection records source material; it does not create forecasts or recommendations. Research is ephemeral on Railway and may need to be collected again after restart.</p></div></div>' + warningHtml + evidence + '</article>';
    } catch (error) {
      view.innerHTML = '<div class="empty"><strong>Research unavailable</strong><span>' + esc(error.message) + '</span></div>';
    }
  }

  function squadOptions() {
    const players = Object.fromEntries(state.data.catalog.players.map((player) => [player.id, player]));
    return state.data.snapshot.squad_snapshot.picks.map((pick) => {
      const player = players[pick.element] || {};
      return `<option value="${pick.element}">${esc(player.web_name || "Unknown")} (${esc(player.id)})</option>`;
    }).join("");
  }

  async function runLens() {
    const view = section("candidates");
    const replaceId = view.querySelector("#candidate-replace").value;
    const minimum = view.querySelector("#candidate-minutes").value;
    const output = view.querySelector("#candidate-output");
    output.innerHTML = "<p>Finding legal replacements.</p>";
    try {
      const result = await fetch(`/api/candidates?replace_id=${encodeURIComponent(replaceId)}&minimum_minutes=${encodeURIComponent(minimum)}`).then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw Error(body.error || "Candidate Lens is unavailable.");
        return body;
      });
      const rows = result.candidates.length ? result.candidates.map((player) => `<tr><td class="player-name">${esc(player.name)}</td><td>£${(player.price / 10).toFixed(1)}m</td><td>${esc(player.minutes)}</td><td>${player.xgi_per_90 ?? "-"}</td><td>${player.fixture_difficulty_average ?? "-"}</td><td>${esc(player.availability)}</td></tr>`).join("") : '<tr><td colspan="6">No players meet every selected filter.</td></tr>';
      output.innerHTML = `<p class="method">${esc(result.method)}</p><p class="small">${result.caveats.map(esc).join(" ")}</p><div class="table-wrap"><table><thead><tr><th>Player</th><th>Price</th><th>Minutes</th><th>xGI/90</th><th>Avg FDR</th><th>Availability</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    } catch (error) {
      output.innerHTML = `<div class="evidence-warning" role="alert">${esc(error.message)}</div>`;
    }
  }

  function openLens() {
    activate("candidates");
    const view = section("candidates");
    view.innerHTML = `<article class="panel"><div class="panel-head"><div><h2>Candidate Lens</h2><p>Legal same-position replacements only. It ranks visible inputs, not predicted points.</p></div></div><div class="lens-controls"><label>Replace<select id="candidate-replace">${squadOptions()}</select></label><label>Minimum minutes<select id="candidate-minutes"><option value="0">Any minutes</option><option value="450">450+</option><option value="900">900+</option></select></label><button id="candidate-run" class="button-primary">Find candidates</button></div><div id="candidate-output" class="lens-output"><p class="small">Budget uses the outgoing current FPL price plus bank. Confirm your selling price before acting.</p></div></article>`;
    view.querySelector("#candidate-run").addEventListener("click", runLens);
  }

  document.addEventListener("click", async (event) => { if (event.target.id !== "collect-research") return; event.target.disabled = true; try { let job = await fetch("/api/research", {method:"POST"}).then((response) => response.json()); while (job.status === "running") { await new Promise((resolve) => setTimeout(resolve, 800)); job = await fetch("/api/jobs/" + encodeURIComponent(job.id)).then((response) => response.json()); } if (job.status !== "complete") throw new Error(job.message || "Research collection failed."); await openResearch(); } catch (error) { event.target.textContent = error.message; } finally { event.target.disabled = false; } });
  addView("research", "Research desk", openResearch);
  addView("candidates", "Candidate lens", openLens);
})();
