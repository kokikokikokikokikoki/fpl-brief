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

test("planner cards show the constraint summary and the cost against the unconstrained best, escaped", () => {
  const { renderPlanner, costLine } = loadPlanner();
  const steered = {
    ...ready,
    constraints: [{ kind: "force_in", id: 268, name: evil, gw: 6, text: `Must buy ${evil} by GW6` }, { kind: "keep", id: 165, name: "João Pedro", gw: null, text: "Never sell João Pedro" }],
    unconstrained_best_gain: 16.05, unconstrained_best_action: "Cherki → <b>Saka</b>",
    plans: [{ ...ready.plans[0], cost_vs_unconstrained: -2.5 }, { ...ready.plans[1], cost_vs_unconstrained: 0 }],
  };
  const html = renderPlanner({ phase: "done", result: steered });
  for (const expected of ["Constraints: Must buy &lt;img src=x onerror=alert(1)&gt; by GW6 · Never sell João Pedro", "Costs <strong>2.50</strong> points against the unconstrained best (+16.05, Cherki → &lt;b&gt;Saka&lt;/b&gt;)",
    "Same as the unconstrained best (+16.05, Cherki → &lt;b&gt;Saka&lt;/b&gt;)"]) {
    assert.ok(html.includes(expected), `missing ${expected}`);
  }
  assert.ok(!/<(img|script|b|i)[\s>]/.test(html), "no raw dynamic markup");
  assert.equal(html.split("Constraints: ").length - 1, 2, "summary on each card");
  assert.match(costLine({ cost_vs_unconstrained: 1.2 }, 16.05, null), /1\.20 more estimated points than the unconstrained best \(\+16\.05\)/);
  assert.equal(costLine({}, 16.05, null), "");
  // No constraints: no summary and no cost line, even if a cost were present.
  const free = renderPlanner({ phase: "done", result: { ...steered, constraints: [] } });
  assert.ok(!free.includes("Constraints: ") && !free.includes("unconstrained best"));
  const invalid = renderPlanner({ phase: "done", result: { state: "invalid", reason: evil } });
  assert.ok(invalid.includes("Constraints not accepted") && invalid.includes("&lt;img") && !invalid.includes("<img"));
});

test("steering controls: chips with remove buttons, query string and limits", () => {
  const { renderSteering, renderChips, plannerQuery, addConstraint, removeConstraint, emptyConstraints, resolvePlayer, choiceLabel } = loadPlanner();
  const choices = { owned: [165, 11], players: [
    { id: 268, name: evil, team: "FUL", position: 4, price: 61 }, { id: 165, name: "João Pedro", team: "CHE", position: 4, price: 77 },
    { id: 11, name: "A&B", team: "ARS", position: 3, price: 55 }, { id: 12, name: "Twin", team: "X", position: 3, price: 45 }, { id: 13, name: "Twin", team: "Y", position: 3, price: 45 }] };
  const c = emptyConstraints();
  assert.equal(addConstraint(c, "force_in", 268, 6), null);
  assert.equal(addConstraint(c, "keep", 165, null), null);
  assert.equal(addConstraint(c, "force_out", 11, null), null);
  assert.match(addConstraint(c, "keep", 165, null), /already/);
  assert.equal(plannerQuery("own", c), "model=own&force_in=268%406&force_out=11&keep=165");
  assert.equal(plannerQuery("fpl", emptyConstraints()), "model=fpl");
  const html = renderSteering(choices, [6, 7, 8], c);
  for (const expected of ["Must buy &lt;img src=x onerror=alert(1)&gt; by GW6", "Must sell A&amp;B by GW6", "Never sell João Pedro", 'data-planner-remove="force_in:0"', 'data-planner-remove="keep:0"',
    'aria-label="Remove: Never sell João Pedro"', 'list="planner-players"', "Next GW (GW6)", '<option value="7">GW7</option>', "Up to 5 constraints", "holding your squad, which ignores them"]) {
    assert.ok(html.includes(expected), `missing ${expected}`);
  }
  assert.ok(!/<(img|script|b|i)[\s>]/.test(html), "no raw dynamic markup");
  // Never sell / Must sell list owned players only.
  const keepSelect = html.slice(html.indexOf('id="planner-keep"'), html.indexOf("</select>", html.indexOf('id="planner-keep"')));
  assert.ok(keepSelect.includes('value="165"') && !keepSelect.includes('value="268"'));
  assert.equal(addConstraint(c, "force_in", 12, null), null);
  assert.equal(addConstraint(c, "force_in", 13, 7), null);
  assert.match(addConstraint(c, "keep", 11, null), /At most 5/);
  assert.ok(renderSteering(choices, [6], c).includes("Limit reached"));
  removeConstraint(c, "force_in", 0);
  assert.equal(c.force_in.length, 2);
  assert.ok(renderChips(emptyConstraints(), choices, 6).includes("chooses freely"));
  assert.ok(renderSteering(null, [], emptyConstraints()).includes("Run \"Suggest plans\" once to load the player list"));
  assert.equal(resolvePlayer(choiceLabel(choices.players[1]), choices).id, 165);
  assert.equal(resolvePlayer("#268", choices).id, 268);
  assert.equal(resolvePlayer("joão pedro", choices).id, 165);
  assert.equal(resolvePlayer("Twin", choices), null, "ambiguous names need the list label");
  assert.equal(resolvePlayer("", choices), null);
});
