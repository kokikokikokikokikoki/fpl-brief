import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import { assess, candidateLens } from "../cloud/shared/decision.mjs";
import { safeHttps, extractJson } from "../cloud/shared/research.mjs";

test("client-shared gates block stale incomplete and past-deadline snapshots", () => {
  const result = assess({ generated_at_utc: new Date(Date.now() - 9 * 3600000).toISOString(), events: { next: { deadline_time: new Date(Date.now() - 1000).toISOString() } }, squad_snapshot: { picks: [] } });
  assert.equal(result.status, "blocked"); assert.ok(result.blockers.length >= 3);
});

test("candidate lens blocks unavailable affordability and keeps rules-only output", () => {
  const snapshot = { generated_at_utc: new Date().toISOString(), events: { next: { deadline_time: new Date(Date.now() + 3600000).toISOString() } }, squad_snapshot: { bank: 5, picks: Array.from({ length: 15 }, (_, i) => ({ element: i + 1 })) } };
  assert.throws(() => candidateLens(snapshot, { players: [{ id: 1, element_type: 3, status: "a", now_cost: 50 }] }, 1));
});

test("research extraction is verbatim and client source contains local storage", () => {
  const source = { id: "official-fpl-news", publisher: "Fantasy Premier League", host: "fantasy.premierleague.com", url: "https://fantasy.premierleague.com/api/bootstrap-static/" };
  const result = extractJson(JSON.stringify({ elements: [{ web_name: "Private", news: "Exact text" }] }), source, "2026-09-22T12:00:00Z");
  assert.deepEqual(result.excerpts[0], { kind: "json_field", text: "Exact text", captured_at_utc: "2026-09-22T12:00:00Z" });
  assert.equal(result.claims.length, 0);
  const client = fs.readFileSync(new URL("../cloud/public/app.js", import.meta.url), "utf8");
  assert.match(client, /localStorage/); assert.match(client, /https:/); assert.match(client, /Device-local/);
});

test("candidate lens keeps bank and prices in raw FPL tenths", () => {
  const snapshot = { generated_at_utc: new Date().toISOString(), events: { next: { deadline_time: new Date(Date.now() + 3600000).toISOString() } }, squad_snapshot: { bank: 50, picks: Array.from({ length: 15 }, (_, i) => ({ element: i + 1, selling_price: i === 0 ? 50 : 40 })) } };
  const catalog = { players: [{ id: 1, element_type: 3, status: "a", now_cost: 50 }, { id: 99, element_type: 3, status: "a", now_cost: 90, minutes: 900 }] };
  assert.equal(candidateLens(snapshot, catalog, 1).budget, 100);
});
