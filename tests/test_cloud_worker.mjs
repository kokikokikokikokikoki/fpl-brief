import assert from "node:assert/strict";
import test from "node:test";
import { handleRequest } from "../cloud/worker.mjs";

const originalFetch = globalThis.fetch;
const bootstrap = { events: [{ id: 1, finished: false, deadline_time: new Date(Date.now() + 86400000).toISOString() }], elements: [{ id: 1, web_name: "Player", element_type: 3, team: 1, now_cost: 50, status: "a", minutes: 900 }], teams: [{ id: 1, short_name: "T" }] };
const response = (body, status = 200, headers = { "content-type": "application/json" }) => new Response(typeof body === "string" ? body : JSON.stringify(body), { status, headers });
function restore() { globalThis.fetch = originalFetch; }

test("rejects invalid identifiers without outbound fetch", async () => {
  let calls = 0; globalThis.fetch = async () => { calls++; return response({}); };
  const result = await handleRequest(new Request("https://travel.example/api/snapshot?team_id=0&league_id=2"));
  assert.equal(result.status, 400); assert.equal(calls, 0); assert.equal(result.headers.get("cache-control"), "no-store"); restore();
});

test("snapshot refresh uses only fixed official FPL paths and normalizes response", async () => {
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    if (String(url).endsWith("bootstrap-static/")) return response(bootstrap);
    if (String(url).includes("/history/")) return response({ current: [] });
    if (String(url).includes("/picks/")) return response({ entry_history: { event: 1, bank: 50 }, picks: Array.from({ length: 15 }, (_, i) => ({ element: i + 1 })) });
    return response({ standings: { results: [] } });
  };
  const result = await handleRequest(new Request("https://travel.example/api/refresh?team_id=12&league_id=34", { method: "POST", headers: { origin: "https://travel.example" } }));
  const body = await result.json();
  assert.equal(result.status, 200); assert.equal(result.headers.get("cache-control"), "no-store");
  assert.equal(body.squad_snapshot.picks.length, 15); assert.equal(body.squad_snapshot.bank, 50);
  assert.ok(urls.every((url) => url.startsWith("https://fantasy.premierleague.com/api/")));
  assert.ok(urls.every((url) => /^https:\/\/fantasy\.premierleague\.com\/api\/(bootstrap-static\/|entry\/12\/(history\/|event\/1\/picks\/)|leagues-classic\/34\/standings\/)$/.test(url)));
  restore();
});

test("research is explicit, fixed-source, bounded, and continues after failure", async () => {
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    if (String(url).includes("fantasy.premierleague.com")) return response({ elements: [{ id: 9, web_name: "Hidden", news: "Verbatim news" }] });
    return new Response("redirect", { status: 308, headers: { location: "https://evil.example" } });
  };
  const result = await handleRequest(new Request("https://travel.example/api/research", { method: "POST", headers: { origin: "https://travel.example" } }));
  const body = await result.json();
  assert.equal(result.status, 200); assert.equal(body.sources.length, 2);
  assert.equal(body.sources[0].excerpts[0].text, "Verbatim news"); assert.equal(body.sources[0].claims.length, 0);
  assert.equal(body.sources[1].collection_state, "unavailable"); assert.equal(body.sources[1].error.code, "redirect_not_followed");
  assert.deepEqual(urls, ["https://fantasy.premierleague.com/api/bootstrap-static/", "https://www.arsenal.com/news/all/1"]);
  restore();
});

test("Candidate Lens uses posted snapshot only and safe method handling", async () => {
  const request = new Request("https://travel.example/api/candidates", { method: "POST", headers: { "content-type": "application/json", origin: "https://travel.example" }, body: JSON.stringify({ snapshot: { generated_at_utc: new Date().toISOString(), events: { next: { deadline_time: new Date(Date.now() + 3600000).toISOString() } }, squad_snapshot: { bank: 50, picks: Array.from({ length: 15 }, (_, i) => ({ element: i + 1, selling_price: i === 0 ? 50 : 40 })) } }, catalog: { players: [{ id: 1, element_type: 3, status: "a", now_cost: 50 }, { id: 20, element_type: 3, status: "a", now_cost: 90, minutes: 900 }] }, replace_id: 1 }) });
  const result = await handleRequest(request);
  assert.equal(result.status, 200); assert.equal((await result.json()).budget, 100);
  const get = await handleRequest(new Request("https://travel.example/api/candidates", { method: "GET" }));
  assert.equal(get.status, 405);
});

test("rejects missing Origin and chunked oversized JSON", async () => {
  const missingOrigin = await handleRequest(new Request("https://travel.example/api/candidates", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }));
  assert.equal(missingOrigin.status, 403);
  const oversized = new Request("https://travel.example/api/candidates", { method: "POST", headers: { "content-type": "application/json", origin: "https://travel.example" }, body: "{" + "x".repeat(512 * 1024) + "}" });
  const result = await handleRequest(oversized); assert.equal(result.status, 400); assert.match((await result.json()).error, /too large/i);
});

test("captures bounded canonical HTML metadata and honors asset binding", async () => {
  globalThis.fetch = async () => response("<html><head><title>Arsenal News</title><meta name=\"description\" content=\"Official updates\"></head></html>", 200, { "content-type": "text/html" });
  const packet = await (await handleRequest(new Request("https://travel.example/api/research", { method: "POST", headers: { origin: "https://travel.example" } }))).json();
  assert.equal(packet.sources[1].excerpts[0].text, "Arsenal News");
  const assetResponse = await handleRequest(new Request("https://travel.example/app.js"), { ASSETS: { fetch: async () => new Response("REAL_APP", { headers: { "content-type": "text/javascript" } }) } });
  assert.equal(await assetResponse.text(), "REAL_APP"); restore();
});

