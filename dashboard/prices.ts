// Prices strip (My squad) and price markers: selling prices and FPL's own price-change predictor.
// The predictor is FPL's guide only; markers and notes never drive a suggestion.

export interface PriceOutlook {
  direction: "rise" | "fall" | "steady" | "unknown";
  expected_at_update?: number | null;
  likelihood?: number | null;
  calibrating?: boolean;
  before_deadline?: boolean;
  label?: string;
  note?: string | null;
}
export interface PriceRow {
  id: number;
  name: string;
  position?: number | null;
  current: number | null;
  purchase: number | null;
  selling: number | null;
  formula_selling?: number | null;
  profit: number | null;
  if_rise: number | null;
  if_fall: number | null;
  rise_earns_nothing?: boolean | null;
  outlook: PriceOutlook;
}
export interface PricesData {
  state: "account" | "public";
  players: PriceRow[];
  guide: string;
  method: string;
  message?: string;
  captured_at_utc?: string | null;
  bank?: number | null;
  selling_total?: number;
  profit_total?: number;
  cross_check?: { checked: number; mismatches: Array<{ id: number; name: string; account: number; formula: number }>; note: string };
}

function esc(value: unknown): string {
  return String(value ?? "—").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c);
}

const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const money = (tenths: unknown): string => isNumber(tenths) ? `£${(tenths / 10).toFixed(1)}m` : "—";
const delta = (tenths: unknown): string => isNumber(tenths) ? `${tenths > 0 ? "+" : tenths < 0 ? "−" : "±"}£${(Math.abs(tenths) / 10).toFixed(1)}m` : "—";

const MARKS: Record<string, { symbol: string; word: string }> = {
  rise: { symbol: "▲", word: "Rise" },
  fall: { symbol: "▼", word: "Fall" },
  steady: { symbol: "–", word: "Steady" },
  unknown: { symbol: "?", word: "No prediction" },
};

/** Small rise/fall marker from FPL's predictor; the full label sits in the tooltip and for screen readers. */
export function priceMarker(outlook: PriceOutlook | null | undefined, hideSteady = false): string {
  const direction = outlook && outlook.direction in MARKS ? outlook.direction : "unknown";
  if (hideSteady && direction === "steady") return "";
  const mark = MARKS[direction];
  const soon = (direction === "rise" || direction === "fall") && outlook?.before_deadline ? " soon" : "";
  const label = outlook?.label ?? "No FPL price prediction available.";
  const calibrating = outlook?.calibrating ? " *" : "";
  return `<span class="price-mark price-${esc(direction)}${soon ? " price-soon" : ""}" title="${esc(label)}"><span aria-hidden="true">${esc(mark.symbol)} ${esc(mark.word)}${esc(calibrating)}</span><span class="visually-hidden">${esc(label)}</span></span>`;
}

/** Compact Prices table for the 15 owned players. */
export function renderPricesStrip(data: PricesData | null | undefined): string {
  if (!data || !Array.isArray(data.players) || !data.players.length) return "";
  const account = data.state === "account";
  const head = account
    ? "<th>Player</th><th>Now</th><th>Bought</th><th>Sell</th><th>Profit locked in</th><th>One more rise</th><th>One more fall</th><th>FPL predictor</th>"
    : "<th>Player</th><th>Now</th><th>FPL predictor</th>";
  const rows = data.players.map((row) => {
    const predictor = `<td>${priceMarker(row.outlook)}</td>`;
    if (!account) return `<tr><td class="player-name">${esc(row.name)}</td><td>${esc(money(row.current))}</td>${predictor}</tr>`;
    const rise = row.rise_earns_nothing ? `${esc(delta(row.if_rise))}<span class="sub">needs a second rise</span>` : esc(delta(row.if_rise));
    return `<tr><td class="player-name">${esc(row.name)}</td><td>${esc(money(row.current))}</td><td>${esc(money(row.purchase))}</td><td><strong>${esc(money(row.selling))}</strong></td><td>${esc(delta(row.profit))}</td><td>${rise}</td><td>${esc(delta(row.if_fall))}</td>${predictor}</tr>`;
  }).join("");
  const mismatches = data.cross_check?.mismatches ?? [];
  const summary = account
    ? `<p class="small">Selling value ${esc(money(data.selling_total))}, profit locked in ${esc(delta(data.profit_total))}${isNumber(data.bank) ? `, bank ${esc(money(data.bank))}` : ""}. From your FPL account, captured ${esc(data.captured_at_utc)}.${data.cross_check ? ` ${esc(data.cross_check.note)}` : ""}${mismatches.length ? ` ${mismatches.map((m) => `${esc(m.name)}: account ${esc(money(m.account))}, formula ${esc(money(m.formula))}`).join("; ")}.` : ""}</p>`
    : `<p class="evidence-warning">${esc(data.message ?? "Selling prices need a fresh capture of your FPL account; public prices only.")}</p>`;
  return `<details class="panel prices-panel"><summary>Prices: ${account ? "selling prices and" : "public prices and"} FPL's price predictor</summary>${summary}<div class="table-wrap"><table class="prices-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div><p class="method">${esc(data.method)}${data.players.some((row) => row.outlook?.calibrating) ? " * FPL is still calibrating that prediction." : ""}</p></details>`;
}
