import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ts = require("../dashboard/node_modules/typescript");

function loadPlanner() {
  const source = fs.readFileSync(new URL("../dashboard/transfer-planner.ts", import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const context = { exports: {}, Number, Math, String };
  vm.runInNewContext(output, context);
  return context.exports;
}

const evil = "<img src=x onerror=alert(1)>";
const week = (gw, moves = []) => ({ gw, moves, transfers: moves.length, free_transfers: 1, hits: 0, hit_points: 0, bank: 5, xi_xp: 50.5, captain: { id: 1, name: evil } });
const ready = {
  state: "ready", model: "own", model_label: "our <b>model</b>", gameweeks: [6, 7], hold: { horizon_xp: 90.1, weeks: [week(6), week(7)] },
  method: "Method <script>x</script>", caveats: ["Caveat & <i>note</i>"],
  plans: [
    { rank: 1, gain: 3.25, gain_undecayed: 3.9, horizon_xp: 93.35, hit_points: 4, status: "optimal", most_points: false, objective_gain: 4.5,
      breakdown: { points_gain: 7.0, hits: -4.0, transfer_penalty: -0.5, ft_value: 2.0, bank_value: 0.0 },
      weeks: [{ ...week(6, [{ out: { id: 11, name: evil, price: 55 }, in: { id: 20, name: "A&B", price: 60 } }]), hits: 1, hit_points: 4 }, week(7)],
      next_gw_moves: [{ out: 11, in: 20 }], next_gw_action: "<b>X</b> → A&B" },
    { rank: 2, gain: 5.75, horizon_xp: 95.85, hit_points: 0, status: "time_limit", most_points: true, objective_gain: 3.1, breakdown: { points_gain: 5.75, ft_value: -2.65 }, weeks: [week(6), week(7)], next_gw_moves: [] },
  ],
};

test("planner renders ready plans with everything escaped", () => {
  const { renderPlanner } = loadPlanner();
  const html = renderPlanner({ phase: "done", result: ready });
  for (const expected of ["&lt;img src=x onerror=alert(1)&gt;", "A&amp;B", "our &lt;b&gt;model&lt;/b&gt;", "Method &lt;script&gt;x&lt;/script&gt;",
    "Caveat &amp; &lt;i&gt;note&lt;/i&gt;", "+3.3", "+5.8", "Points gain vs holding: <strong>+3.3</strong>", "Planner score vs holding: <strong>+4.50</strong>", "points incl. bench and vice weights +7.00, hits −4.00, per-transfer threshold −0.50, free transfers kept at the end +2.00, bank kept at the end +0.00", "Planner score vs holding: <strong>+3.10</strong>", "Most estimated points", "Holding scores 90.1 points over the horizon", "a lower-ranked plan can gain more points", "£5.5m", "£6.0m", "£0.5m", "Plan 1", "Plan 2", "GW6–7", "not advice",
    "Chips are not included", 'data-planner-try="1"', "Plan 1 · GW6: &lt;b&gt;X&lt;/b&gt; → A&amp;B", "Plan 2 · GW6: Roll the free transfer (no moves)", "different GW6 action", "Try GW6 moves on board", "rolls the free transfer now", "time limit", "90.1", "Moves after GW6 are indicative — re-run the planner each week."]) {
    assert.ok(html.includes(expected), `missing ${expected}`);
  }
  assert.ok(!/<(img|script|b|i)[\s>]/.test(html), "no raw dynamic markup");
  assert.ok(!html.includes('data-planner-try="2"'), "no board button without next-GW moves");
  assert.ok(!html.includes("best overall"), "no best-overall wording");
  assert.equal(html.split("Most estimated points").length - 1, 1, "one plan marked");
  assert.ok(html.indexOf("Points gain vs holding") < html.indexOf("Planner score vs holding"), "points first");
});

test("planner renders idle, loading, error and non-ready states", () => {
  const { renderPlanner } = loadPlanner();
  assert.match(renderPlanner({ phase: "idle" }), /not advice; chips are not included/);
  assert.match(renderPlanner({ phase: "loading", model: "fpl" }), /FPL-based/);
  assert.match(renderPlanner({ phase: "loading", model: "<x>" }), /&lt;x&gt;/);
  const error = renderPlanner({ phase: "error", message: evil });
  assert.ok(error.includes("&lt;img") && error.includes('role="alert"'));
  const unavailable = renderPlanner({ phase: "done", result: { state: "unavailable", reason: "Planner needs the highspy package" } });
  assert.ok(unavailable.includes("Planner unavailable here") && unavailable.includes("runs on your own computer") && unavailable.includes("pip install -r requirements-planner.txt") && unavailable.includes("highspy"));
  const blocked = renderPlanner({ phase: "done", result: { state: "blocked", reason: evil } });
  assert.ok(blocked.includes("Planner blocked") && blocked.includes("&lt;img") && !blocked.includes("<img"));
  assert.ok(renderPlanner({ phase: "done", result: { state: "infeasible", reason: "r" } }).includes("No legal plan"));
  assert.ok(renderPlanner({ phase: "done", result: { ...ready, plans: [] } }).includes("No plan found"));
});
