export function parseTime(value) {
  if (typeof value !== "string") return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
}
export function snapshotFreshness(snapshot, staleAfterHours = 8, now = Date.now()) {
  const generated = parseTime(snapshot && snapshot.generated_at_utc);
  if (!generated) return { stale: true, ageHours: null, message: "Snapshot time is unavailable." };
  const ageHours = Math.max(0, (now - generated) / 3600000);
  return { stale: ageHours > staleAfterHours, ageHours: Number(ageHours.toFixed(1)), message: ageHours > staleAfterHours ? "Snapshot is " + ageHours.toFixed(1) + " hours old." : "Snapshot is current." };
}
export function assess(snapshot, options = {}, now = Date.now()) {
  const freshness = snapshotFreshness(snapshot, options.staleAfterHours || 8, now);
  const picks = snapshot && snapshot.squad_snapshot && snapshot.squad_snapshot.picks || [];
  const deadline = parseTime(snapshot && snapshot.events && snapshot.events.next && snapshot.events.next.deadline_time);
  const blockers = [];
  if (freshness.stale) blockers.push("Refresh the public snapshot before deciding.");
  if (picks.length !== 15) blockers.push("The public squad snapshot is incomplete.");
  if (!deadline) blockers.push("The next FPL deadline is unavailable.");
  else if (deadline <= now) blockers.push("The next FPL deadline has passed.");
  if (snapshot && snapshot.warnings && snapshot.warnings.length) blockers.push("The snapshot has collection warnings that need review.");
  const blocked = blockers.length > 0;
  return { mode: "rules-only", status: blocked ? "blocked" : "ready", snapshot_status: freshness, blockers,
    recommendation: blocked ? { action: "Pause transfer and lineup recommendations.", why: blockers[0], alternative: "Use the last snapshot only as discussion context.", what_would_change: "A current, complete snapshot before the deadline." } : { action: "Hold and preserve flexibility.", why: "The public squad is current and complete.", alternative: "Check official availability and private transfer state before acting.", what_would_change: "New official availability news or a deadline-driven need to act." }, jev: { enabled: false, message: "Optional Jev layer is disabled." } };
}
export function candidateLens(snapshot, catalog, replaceId, options = {}, now = Date.now()) {
  const decision = assess(snapshot, options, now);
  if (decision.status === "blocked") throw new Error(decision.blockers.join(" "));
  const players = new Map((catalog && catalog.players || []).map((player) => [player.id, player]));
  const picks = snapshot.squad_snapshot.picks || [];
  const owned = new Set(picks.map((pick) => pick.element));
  const outgoing = players.get(Number(replaceId));
  if (!outgoing || !owned.has(Number(replaceId))) throw new Error("Select a player from the public squad snapshot.");
  const pick = picks.find((item) => item.element === Number(replaceId));
  const selling = pick && pick.selling_price;
  const bank = snapshot.squad_snapshot.bank;
  if (!Number.isFinite(selling) || selling < 0 || !Number.isFinite(bank) || bank < 0) throw new Error("Actual selling price and bank are required; affordability is blocked.");
  const budget = Math.trunc(selling) + Math.trunc(bank);
  const teamCounts = {};
  owned.forEach((id) => { if (id !== Number(replaceId)) { const player = players.get(id); if (player) teamCounts[player.team] = (teamCounts[player.team] || 0) + 1; } });
  const candidates = (catalog && catalog.players || []).filter((player) => !owned.has(player.id) && player.element_type === outgoing.element_type && Number(player.now_cost || 0) <= budget && (teamCounts[player.team] || 0) < 3 && player.status === "a" && (player.chance_of_playing_next_round == null || player.chance_of_playing_next_round >= 100) && Number(player.minutes || 0) >= (options.minimumMinutes || 0)).map((player) => ({ id: player.id, name: player.web_name, price: player.now_cost, minutes: player.minutes || 0, availability: "available" }));
  return { outgoing: { id: outgoing.id, name: outgoing.web_name, selling_price: selling }, budget, candidates, method: "Rules-only same-position replacements using public inputs. This is not a points forecast.", caveats: ["Affordability uses validated selling price plus bank.", "Private transfer state remains unavailable."] };
}
