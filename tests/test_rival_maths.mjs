import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ts = require("../dashboard/node_modules/typescript");

function load(file, req = () => ({})) {
  const source = fs.readFileSync(new URL(`../dashboard/${file}`, import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const context = { exports: {}, require: req, Number, Math, String, JSON };
  vm.runInNewContext(output, context);
  return context.exports;
}

const kits = load("kits.ts");
const { renderRivalMaths } = load("rival-maths.ts", (name) => (name === "./kits" ? kits : {}));
const evil = "<img src=x onerror=alert(1)>";
const player = (id, name, extra = {}) => ({ id, name, team: "AAA", position: "MID", xp: 5.25, xp_6: 28.4, eo: 0.6, ...extra });
const drivers = { for_you: [player(1, evil, { points: 4.5 })], against_you: [player(2, "A&B", { points: -3.25 })] };
const ready = {
  state: "ready", gameweek: 5, target_gameweek: 6, remaining: 33, model: "own", lineup_source: "your <b>account</b>", sims: 10000, rivals_compared: 2,
  you: { name: evil, rank: 3, total: 381, p_first: 0.0024, expected_rank: 4.11 },
  mode: { mode: "chase", z: -0.56, against: evil, you_lead: false, gap: -11, edge: -36.3, sigma_week: 14.7, remaining: 33, text: "Chase <i>now</i>" },
  field_swing: { swing: -2.64, drivers },
  rivals: [
    { entry_id: 20, name: "Lead<er>", manager: "L", rank: 1, total: 392, gap: -11, p_ahead: 0.288, p_ahead_analytic: 0.301, z: -0.56, edge: -36.3, sigma_week: 14.7, p_first: 0.48, swing: -5.07, drivers,
      assumed_captain: { id: 9, name: evil, why: "last captain" }, chips_left: [{ name: "3xc", label: "Triple <Captain>" }], shared: 4 },
    { entry_id: 30, name: "Second", manager: "S", rank: 2, total: 380, gap: 1, p_ahead: 0.9999, p_ahead_analytic: 0.9999, z: 2, edge: 3, sigma_week: 10, p_first: 0.5176, swing: 0, drivers: { for_you: [], against_you: [] },
      assumed_captain: { id: 9, name: "H", why: "highest next-GW xP starter" }, chips_left: [], shared: 15 },
  ],
  captains: [
    { ...player(9, "Haaland", { eo: 2.0 }), vs_field: -1.88, p_beats_field: 0.5, current: false, differential_flag: false, rivals: [{ entry_id: 20, name: "Lead<er>", expected: -4.31, p_gain: 0.38 }, { entry_id: 30, name: "Second", expected: 0, p_gain: 1 }] },
    { ...player(5, evil, { eo: 0.2 }), vs_field: -2.34, p_beats_field: 0.47, current: true, differential_flag: true, rivals: [{ entry_id: 20, name: "Lead<er>", expected: -4.77, p_gain: 0.379 }, { entry_id: 30, name: "Second", expected: 0.5, p_gain: 0.6 }] },
  ],
  shield: [player(9, "Haaland", { eo: 2.0, mult: 1 })], differentials: [player(5, evil, { eo: 0.2, mult: 0 })],
  warnings: ["Skipped <x>"], caveats: ["Caveat & <i>c</i>"], assumptions: ["Assume <b>this</b>"], method: "Method <script>x</script>",
};

test("rival maths renders a ready result with everything escaped and labelled as estimates", () => {
  const html = renderRivalMaths(ready, false);
  for (const expected of ["Rival maths", "&lt;img src=x onerror=alert(1)&gt;", "Lead&lt;er&gt;", "A&amp;B", "Triple &lt;Captain&gt;", "Chase &lt;i&gt;now&lt;/i&gt;",
    "your &lt;b&gt;account&lt;/b&gt;", "Method &lt;script&gt;x&lt;/script&gt;", "Caveat &amp; &lt;i&gt;c&lt;/i&gt;", "Skipped &lt;x&gt;", "Assume &lt;b&gt;this&lt;/b&gt;",
    "estimate from a simple model", "Title odds (estimate)", "P(finish ahead)", "29%", "formula check 30%", "&gt;99%", "&lt;1%", "48%", "Captain table", "200%", "20%",
    "differential option (heuristic)", "not a derived rule", "your captain now", "Your shield", "Your differentials", "benched", "−5.07", "+4.5", "−3.", 
    "C &lt;img", "assumed: last captain", "none left", "rm-chase", "Chase", "z −0.56".replace("−", "-"), "expected final rank 4.1", "GW6"]) {
    assert.ok(html.includes(expected), `missing ${expected}`);
  }
  assert.ok(!/<(img|script|i|x)[\s>]/.test(html) && !html.includes("<b>this") && !html.includes("<b>account"), "no raw dynamic markup");
  assert.ok(!html.includes("<er>"), "manager names escaped");
});

test("rival maths renders loading, idle, error and unavailable states", () => {
  assert.match(renderRivalMaths(null, true), /Working out ownership/);
  assert.match(renderRivalMaths(null, false), /Open this view/);
  const error = renderRivalMaths(null, false, evil);
  assert.ok(error.includes("&lt;img") && !error.includes("<img") && error.includes("evidence-warning"));
  const unavailable = renderRivalMaths({ state: "unavailable", reason: evil }, false);
  assert.ok(unavailable.includes("&lt;img") && !unavailable.includes("<img"));
});
