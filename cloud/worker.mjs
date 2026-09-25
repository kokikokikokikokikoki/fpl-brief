import { assess, candidateLens } from "./shared/decision.mjs";
import { SOURCES, MAX_BODY_BYTES, FPL_BOOTSTRAP_MAX_BODY_BYTES, exactFpl, extractJson, extractHtml, safeHttps } from "./shared/research.mjs";

const FPL = "https://fantasy.premierleague.com";
const STATIC = {
  "/": ["text/html; charset=utf-8", "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Travel Dashboard</title><link rel=\"stylesheet\" href=\"/styles.css\"></head><body><main id=\"app\"></main><script type=\"module\" src=\"/app.js\"></script></body></html>"],
  "/index.html": ["text/html; charset=utf-8", "<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Travel Dashboard</title><link rel=\"stylesheet\" href=\"/styles.css\"></head><body><main id=\"app\"></main><script type=\"module\" src=\"/app.js\"></script></body></html>"],
  "/app.js": ["text/javascript; charset=utf-8", "export default {};"],
  "/styles.css": ["text/css; charset=utf-8", "body{font-family:system-ui;margin:2rem} .warning{color:#9a3412}"]
};
function json(data, status = 200) { return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } }); }
function error(status, message) { return json({ error: message }, status); }
async function readJsonBody(request) {
  const length = Number(request.headers.get("content-length") || 0);
  if (length > 512 * 1024) throw new Error("Request body is too large.");
  const type = request.headers.get("content-type") || "";
  if (!type.toLowerCase().startsWith("application/json")) throw new Error("JSON content type is required.");
  if (!request.body || !request.body.getReader) { const text = await request.text(); if (new TextEncoder().encode(text).byteLength > 512 * 1024) throw new Error("Request body is too large."); if (!text) throw new Error("JSON body is required."); try { return JSON.parse(text); } catch { throw new Error("Invalid JSON body."); } } const reader = request.body.getReader(); const chunks = []; let total = 0; try { while (true) { const part = await reader.read(); if (part.done) break; total += part.value.byteLength; if (total > 512 * 1024) { await reader.cancel(); throw new Error("Request body is too large."); } chunks.push(part.value); } } finally { reader.releaseLock(); } const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; } const text = new TextDecoder().decode(bytes);
  if (!text) throw new Error("JSON body is required.");
  try { return JSON.parse(text); } catch { throw new Error("Invalid JSON body."); }
}
function validId(value) { return /^[1-9]\d{0,8}$/.test(String(value)) && Number(value) <= 100000000; }
function ids(url) { const team = url.searchParams.get("team_id"); const league = url.searchParams.get("league_id"); if (!validId(team) || !validId(league)) throw new Error("Positive team_id and league_id are required."); return { team: Number(team), league: Number(league) }; }
function sameOrigin(request, url) { const origin = request.headers.get("origin"); return !origin || origin === url.origin; }
async function fetchJson(url, signal) { const response = await fetch(url, { method: "GET", redirect: "manual", signal, headers: { accept: "application/json" } }); if (!response.ok) throw new Error("Upstream FPL request failed."); return response.json(); }
async function snapshot(request, url) {
  const values = ids(url); const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const bootstrap = await fetchJson(FPL + "/api/bootstrap-static/", controller.signal);
    const next = (bootstrap.events || []).find((event) => event.is_current) || (bootstrap.events || []).find((event) => !event.finished) || (bootstrap.events || [])[bootstrap.events?.length - 1] || {};
    const [history, picks, standings] = await Promise.all([
      fetchJson(FPL + "/api/entry/" + values.team + "/history/", controller.signal),
      fetchJson(FPL + "/api/entry/" + values.team + "/event/" + (next.id || 1) + "/picks/", controller.signal),
      fetchJson(FPL + "/api/leagues-classic/" + values.league + "/standings/", controller.signal)
    ]);
    return { generated_at_utc: new Date().toISOString(), events: { next }, squad_snapshot: { event_id: picks.entry_history?.event || next.id, bank: Number(picks.entry_history?.bank || 0), picks: picks.picks || [] }, catalog: { players: bootstrap.elements || [], teams: bootstrap.teams || [] }, league: { standings: standings?.standings?.results || [] }, history, rivals: standings?.standings?.results || [], availability: [], warnings: [] };
  } finally { clearTimeout(timer); }
}
async function readBounded(response, cap) {
  if (!response.body || !response.body.getReader) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > cap) return null;
    return new TextDecoder().decode(bytes);
  }
  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      total += part.value.byteLength;
      if (total > cap) { await reader.cancel(); return null; }
      chunks.push(part.value);
    }
  } finally { reader.releaseLock(); }
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { merged.set(chunk, offset); offset += chunk.byteLength; }
  return new TextDecoder().decode(merged);
}
async function fetchResearchSource(source, started) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(source.url, { redirect: "manual", signal: controller.signal, headers: { accept: "text/html, application/json" } });
    return { response, body: response.ok ? await readBounded(response, exactFpl(source) ? FPL_BOOTSTRAP_MAX_BODY_BYTES : MAX_BODY_BYTES) : null };
  } finally { clearTimeout(timer); }
}
function sourceRecord(source, state, meta, errorCode) { return { id: source.id, publisher: source.publisher, url: safeHttps(source.url) ? source.url : null, title: meta?.title || null, retrieved_at_utc: meta?.retrieved_at_utc || null, last_success_at_utc: meta?.retrieved_at_utc || null, collection_state: state, verification_status: "unverified", excerpts: meta?.excerpts || [], claims: [], ...(errorCode ? { error: { code: errorCode, message: "Source was not captured." } } : {}) }; }
async function collectResearch() {
  const results = [];
  for (const source of SOURCES) {
    const started = new Date().toISOString();
    try {
      const fetched = await fetchResearchSource(source, started);
      const response = fetched.response;
      if (!response.ok) { results.push(sourceRecord(source, response.status >= 300 && response.status < 400 ? "unavailable" : "rejected", null, response.status >= 300 && response.status < 400 ? "redirect_not_followed" : "http_" + response.status)); continue; }
      if (fetched.body === null) { results.push(sourceRecord(source, "rejected", null, "response_too_large")); continue; }
      const body = fetched.body;
      const contentType = (response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase(); if (contentType !== "application/json" && contentType !== "text/html") { results.push(sourceRecord(source, "rejected", null, "unsupported_content_type")); continue; } const meta = contentType === "text/html" ? extractHtml(body, source, started) : extractJson(body, source, started);
      results.push(sourceRecord(source, "captured", { ...meta, retrieved_at_utc: started }));
    } catch (cause) { results.push(sourceRecord(source, "unavailable", null, cause?.name === "AbortError" ? "timeout" : "request_failed")); }
  }
  return { schema_version: 2, generated_at_utc: new Date().toISOString(), collector: { version: "worker-v1", last_run_at_utc: new Date().toISOString() }, sources: results, warnings: ["Captured source text is unverified; collection does not create forecasts or recommendations."] };
}
export async function handleRequest(request, env = {}) {
  const url = new URL(request.url);
  if (!sameOrigin(request, url) || (request.method === "POST" && !request.headers.get("origin"))) return error(403, "Same-origin requests only.");
  if (url.pathname.startsWith("/api/")) {
    if (request.method !== "GET" && request.method !== "POST") return error(405, "Method not allowed.");
    if (url.pathname === "/api/snapshot" || url.pathname === "/api/refresh") {
      try { return json(await snapshot(request, url)); } catch (cause) { return error(400, cause instanceof Error ? cause.message : "Snapshot unavailable."); }
    }
    if (url.pathname === "/api/research") { if (request.method !== "POST") return error(405, "Research requires explicit POST."); return json(await collectResearch()); }
    if (url.pathname === "/api/candidates") {
      if (request.method !== "POST") return error(405, "Candidate Lens requires POST.");
      try { const body = await readJsonBody(request); return json(candidateLens(body.snapshot, body.catalog, body.replace_id, body.options || {})); } catch (cause) { return error(400, cause instanceof Error ? cause.message : "Candidate Lens unavailable."); }
    }
    return error(404, "Not found.");
  }
  if (request.method !== "GET") return error(405, "Method not allowed.");
  if (env.ASSETS && typeof env.ASSETS.fetch === "function") return env.ASSETS.fetch(request);
  const asset = STATIC[url.pathname] || STATIC["/"];
  return new Response(asset[1], { headers: { "content-type": asset[0], "cache-control": "no-store" } });
}
export default { fetch: handleRequest };


