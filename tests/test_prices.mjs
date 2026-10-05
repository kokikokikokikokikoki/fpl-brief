import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ts = require("../dashboard/node_modules/typescript");

function load(file) {
  const source = fs.readFileSync(new URL(`../dashboard/${file}`, import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const context = { exports: {}, Number, Math, String, JSON };
  vm.runInNewContext(output, context);
  return context.exports;
}

const evil = "<img src=x onerror=alert(1)>";
const { priceMarker, renderPricesStrip } = load("prices.ts");

test("price markers show direction, escape the label and can hide steady", () => {
  const rise = priceMarker({ direction: "rise", before_deadline: true, label: `Rise ${evil}` });
  assert.match(rise, /price-rise price-soon/);
  assert.match(rise, /▲ Rise/);
  assert.ok(rise.includes("&lt;img src=x"));
  assert.ok(!rise.includes("<img"));
  assert.match(priceMarker({ direction: "fall", label: "f" }), /▼ Fall/);
  assert.match(priceMarker(undefined), /No prediction/);
  assert.match(priceMarker({ direction: `bad"${evil}`, label: "x" }), /price-unknown/);
  assert.equal(priceMarker({ direction: "steady", label: "s" }, true), "");
  assert.match(priceMarker({ direction: "steady", label: "s" }), /Steady/);
  assert.match(priceMarker({ direction: "rise", calibrating: true, label: "c" }), /Rise \*/);
});

const row = (overrides = {}) => ({ id: 1, name: evil, current: 52, purchase: 50, selling: 51, formula_selling: 51, profit: 1, if_rise: 0, if_fall: -1,
  rise_earns_nothing: true, outlook: { direction: "rise", label: "Predicted to rise. FPL's own predictor, a guide only." }, ...overrides });

test("prices strip with account data shows selling prices, the single-rise note and the cross-check", () => {
  const html = renderPricesStrip({ state: "account", players: [row()], guide: "g", method: `Method ${evil}`, captured_at_utc: "2026-10-05T04:54Z",
    bank: 1, selling_total: 1000, profit_total: 5,
    cross_check: { checked: 1, note: "Some differ.", mismatches: [{ id: 1, name: evil, account: 50, formula: 51 }] } });
  for (const text of ["Profit locked in", "£5.2m", "£5.0m", "<strong>£5.1m</strong>", "needs a second rise", "−£0.1m", "£100.0m", "+£0.5m", "Some differ.", "account £5.0m, formula £5.1m", "▲ Rise"]) {
    assert.ok(html.includes(text), text);
  }
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<script"));
});

test("prices strip without account data shows public prices and the blocked message", () => {
  const html = renderPricesStrip({ state: "public", players: [row({ purchase: null, selling: null, profit: null })], guide: "g", method: "m",
    message: `Selling prices need a fresh capture of your FPL account; public prices only. ${evil}` });
  assert.ok(html.includes("evidence-warning"));
  assert.ok(html.includes("fresh capture"));
  assert.ok(!html.includes("Profit locked in"));
  assert.ok(!html.includes("<img"));
  assert.equal(renderPricesStrip(undefined), "");
  assert.equal(renderPricesStrip({ state: "public", players: [] }), "");
});

test("planned-transfers strip shows early-move notes, escaped", () => {
  const { renderPlanStrip } = load("transfer-plan.ts");
  const summary = { transfers: [], budget_left: 5, free_transfers: 1, paid_transfers: 0, hit_points: 0, xi_delta: 1, net_delta: 1, method: "m",
    price_notes: [{ kind: "buy_rise", text: `Early-move note: ${evil} is predicted to rise.` }] };
  const html = renderPlanStrip([{ out: 1, in: 2 }], { state: "ready", summary, lineup: null }, new Map([[1, "A"], [2, "B"]]));
  assert.ok(html.includes('<ul class="price-notes"><li>Early-move note: &lt;img'));
  assert.ok(!html.includes("<img"));
  const none = renderPlanStrip([{ out: 1, in: 2 }], { state: "ready", summary: { ...summary, price_notes: [] }, lineup: null }, new Map());
  assert.ok(!none.includes("price-notes"));
});

test("planner cards show early-move notes, escaped", () => {
  const { renderPlanner } = load("transfer-planner.ts");
  const week = { gw: 6, moves: [], transfers: 1, free_transfers: 1, hits: 0, hit_points: 0, bank: 5, xi_xp: 50, captain: { id: 1, name: "C" } };
  const plan = { rank: 1, weeks: [week], hit_points: 0, horizon_xp: 50, gain: 1, next_gw_moves: [{ out: 1, in: 2 }],
    price_notes: [{ kind: "sell_fall", text: `Early-move note: ${evil} is predicted to fall.` }] };
  const html = renderPlanner({ phase: "done", result: { state: "ready", model: "own", model_label: "m", gameweeks: [6], hold: { horizon_xp: 49, weeks: [week] }, plans: [plan], method: "m", caveats: [] } });
  assert.ok(html.includes("price-notes"));
  assert.ok(html.includes("Early-move note: &lt;img"));
  assert.ok(!html.includes("<img"));
});
