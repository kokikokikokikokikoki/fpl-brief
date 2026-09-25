// Illustrative club colours for mockups only — not official kit artwork.
window.KITS = {
  ARS: { body: "#DB0007", sleeve: "#FFFFFF", trim: "#FFFFFF" },
  AVL: { body: "#7A003C", sleeve: "#94BEE5", trim: "#FEE505" },
  BOU: { body: "#DA291C", sleeve: "#111111", trim: "#111111", pattern: "stripes", stripe: "#111111" },
  BRE: { body: "#E30613", sleeve: "#E30613", trim: "#111111", pattern: "stripes", stripe: "#FFFFFF" },
  BHA: { body: "#0057B8", sleeve: "#0057B8", trim: "#FFFFFF", pattern: "stripes", stripe: "#FFFFFF" },
  CHE: { body: "#034694", sleeve: "#034694", trim: "#FFFFFF" },
  COV: { body: "#6CB4EE", sleeve: "#6CB4EE", trim: "#FFFFFF" },
  CRY: { body: "#1B458F", sleeve: "#1B458F", trim: "#FFFFFF", pattern: "stripes", stripe: "#C4122E" },
  EVE: { body: "#003399", sleeve: "#003399", trim: "#FFFFFF" },
  FUL: { body: "#FFFFFF", sleeve: "#FFFFFF", trim: "#111111" },
  HUL: { body: "#F5A12D", sleeve: "#111111", trim: "#111111", pattern: "stripes", stripe: "#111111" },
  IPS: { body: "#0044A9", sleeve: "#0044A9", trim: "#FFFFFF" },
  LEE: { body: "#FFFFFF", sleeve: "#FFFFFF", trim: "#1D428A" },
  LIV: { body: "#C8102E", sleeve: "#C8102E", trim: "#F6EB61" },
  MCI: { body: "#6CABDD", sleeve: "#6CABDD", trim: "#FFFFFF" },
  MUN: { body: "#DA291C", sleeve: "#DA291C", trim: "#111111" },
  NEW: { body: "#FFFFFF", sleeve: "#111111", trim: "#111111", pattern: "stripes", stripe: "#111111" },
  NFO: { body: "#DD0000", sleeve: "#DD0000", trim: "#FFFFFF" },
  TOT: { body: "#FFFFFF", sleeve: "#FFFFFF", trim: "#132257" },
  SUN: { body: "#EB172B", sleeve: "#EB172B", trim: "#111111", pattern: "stripes", stripe: "#FFFFFF" },
};
// Goalkeepers wear a distinct, illustrative keeper shirt with their club trim.
window.GK_KIT = { body: "#C9F24B", sleeve: "#1F2A12", trim: "#1F2A12" };

let jerseySeq = 0;
window.jersey = function jersey(team, { keeper = false, size = 64, outline = "rgba(0,0,0,.28)" } = {}) {
  const club = window.KITS[team] || { body: "#9AA5A0", sleeve: "#9AA5A0", trim: "#FFFFFF" };
  const kit = keeper ? { ...window.GK_KIT, trim: club.body } : club;
  const id = `j${++jerseySeq}`;
  const body = "M30 12 L41 7 Q50 14 59 7 L70 12 L72 36 L72 93 Q50 97 28 93 L28 36 Z";
  const left = "M30 12 L12 25 L20 42 L28 37 Z";
  const right = "M70 12 L88 25 L80 42 L72 37 Z";
  const stripes = kit.pattern === "stripes"
    ? `<g clip-path="url(#${id})">${[31, 43, 55, 67].map((x) => `<rect x="${x}" y="0" width="6" height="100" fill="${kit.stripe}"/>`).join("")}</g>`
    : "";
  return `<svg class="jersey" viewBox="0 0 100 100" width="${size}" height="${size}" aria-hidden="true" focusable="false">
    <defs><clipPath id="${id}"><path d="${body}"/></clipPath></defs>
    <path d="${left}" fill="${kit.sleeve}" stroke="${outline}" stroke-width="1.5" stroke-linejoin="round"/>
    <path d="${right}" fill="${kit.sleeve}" stroke="${outline}" stroke-width="1.5" stroke-linejoin="round"/>
    <path d="${body}" fill="${kit.body}"/>${stripes}
    <path d="${body}" fill="none" stroke="${outline}" stroke-width="1.5" stroke-linejoin="round"/>
    <path d="M41 7 Q50 14 59 7 L56 6 Q50 10 44 6 Z" fill="${kit.trim}"/>
    <path d="M20 42 L12 25" stroke="${kit.trim}" stroke-width="3" stroke-linecap="round"/>
    <path d="M80 42 L88 25" stroke="${kit.trim}" stroke-width="3" stroke-linecap="round"/>
  </svg>`;
};

window.esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
window.money = (tenths) => `£${(tenths / 10).toFixed(1)}m`;
window.countdown = (iso) => {
  const ms = new Date(iso) - new Date();
  if (ms <= 0) return { d: 0, h: 0, m: 0, passed: true };
  return { d: Math.floor(ms / 864e5), h: Math.floor(ms / 36e5) % 24, m: Math.floor(ms / 6e4) % 60, passed: false };
};
window.chipName = { bboost: "Bench Boost", "3xc": "Triple Captain", wildcard: "Wildcard", freehit: "Free Hit" };
