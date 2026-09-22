(() => {
  const banner = document.querySelector("#stale-banner");

  function snapshotFeedback() {
    const freshness = typeof state !== "undefined" && state.data?.snapshot_status;
    if (!banner || !freshness) return;
    banner.hidden = !freshness.stale;
    banner.className = freshness.stale ? "stale-banner" : "";
    banner.textContent = freshness.stale
      ? `${freshness.message} Refresh public FPL data before relying on this desk.`
      : "";
  }

  function clearScenarioError(card) {
    card.querySelector(".scenario-error")?.remove();
    card.querySelectorAll("[aria-invalid='true']").forEach((input) => input.removeAttribute("aria-invalid"));
  }

  function scenarioError(card, message, input) {
    clearScenarioError(card);
    const alert = document.createElement("p");
    alert.className = "scenario-error";
    alert.setAttribute("role", "alert");
    alert.tabIndex = -1;
    alert.textContent = message;
    card.prepend(alert);
    input?.setAttribute("aria-invalid", "true");
    alert.focus();
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest(".save-plan");
    if (!button || typeof state === "undefined" || !state.data) return;
    const card = button.closest(".scenario");
    const input = card.querySelector(".plan-players");
    const tokens = input.value.split(",").map((value) => value.trim()).filter(Boolean);
    const ids = tokens.map(Number);
    const known = new Set(state.data.catalog.players.map((player) => player.id));
    let error = "";
    if (ids.some((id) => !Number.isInteger(id) || id < 1)) {
      error = "Use comma-separated positive FPL player IDs.";
    } else if (new Set(ids).size !== ids.length) {
      error = "A scenario cannot include the same player twice.";
    } else if (ids.some((id) => !known.has(id))) {
      error = "One or more player IDs are not in the current FPL catalog.";
    }
    if (!error) {
      clearScenarioError(card);
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    scenarioError(card, error, input);
  }, true);

  function decisionFeedback() {
    const decision = typeof state !== "undefined" && state.data?.decision;
    const overview = document.querySelector("#overview");
    if (!decision || !overview) return;
    const signature = JSON.stringify([decision.status, decision.recommendation, decision.blockers, decision.jev]);
    if (overview.dataset.rulesKey === signature && overview.querySelector(".rules-desk")) return;
    overview.dataset.rulesKey = signature;
    overview.querySelector(".rules-desk")?.remove();
    const panel = document.createElement("article");
    panel.className = `panel rules-desk ${decision.status}`;
    const heading = document.createElement("h2");
    heading.textContent = "Rules-only decision";
    panel.append(heading);
    const action = document.createElement("h3");
    action.textContent = decision.recommendation.action;
    panel.append(action);
    [["Why", decision.recommendation.why], ["Alternative", decision.recommendation.alternative], ["What would change this", decision.recommendation.what_would_change]].forEach(([label, value]) => {
      const line = document.createElement("p");
      const strong = document.createElement("strong");
      strong.textContent = `${label}: `;
      line.append(strong, value);
      panel.append(line);
    });
    if (decision.blockers.length) {
      const blockers = document.createElement("p");
      blockers.className = "rules-blockers";
      blockers.textContent = decision.blockers.join(" ");
      panel.append(blockers);
    }
    const layer = document.createElement("p");
    layer.className = "method";
    layer.textContent = `Jev layer: ${decision.jev.message}`;
    panel.append(layer);
    overview.prepend(panel);
  }

  const feedback = () => { snapshotFeedback(); decisionFeedback(); };
  new MutationObserver(feedback).observe(document.body, {childList: true, subtree: true});
  feedback();
})();
