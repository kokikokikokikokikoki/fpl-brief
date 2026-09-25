// Illustrative club colours for the tactics board — not official kit artwork.
interface Kit { body: string; sleeve: string; trim: string; stripe?: string }

const KITS: Record<string, Kit> = {
  ARS: { body: "#DB0007", sleeve: "#FFFFFF", trim: "#FFFFFF" },
  AVL: { body: "#7A003C", sleeve: "#94BEE5", trim: "#FEE505" },
  BOU: { body: "#DA291C", sleeve: "#111111", trim: "#111111", stripe: "#111111" },
  BRE: { body: "#E30613", sleeve: "#E30613", trim: "#111111", stripe: "#FFFFFF" },
  BHA: { body: "#0057B8", sleeve: "#0057B8", trim: "#FFFFFF", stripe: "#FFFFFF" },
  CHE: { body: "#034694", sleeve: "#034694", trim: "#FFFFFF" },
  COV: { body: "#6CB4EE", sleeve: "#6CB4EE", trim: "#FFFFFF" },
  CRY: { body: "#1B458F", sleeve: "#1B458F", trim: "#FFFFFF", stripe: "#C4122E" },
  EVE: { body: "#003399", sleeve: "#003399", trim: "#FFFFFF" },
  FUL: { body: "#FFFFFF", sleeve: "#FFFFFF", trim: "#111111" },
  HUL: { body: "#F5A12D", sleeve: "#111111", trim: "#111111", stripe: "#111111" },
  IPS: { body: "#0044A9", sleeve: "#0044A9", trim: "#FFFFFF" },
  LEE: { body: "#FFFFFF", sleeve: "#FFFFFF", trim: "#1D428A" },
  LIV: { body: "#C8102E", sleeve: "#C8102E", trim: "#F6EB61" },
  MCI: { body: "#6CABDD", sleeve: "#6CABDD", trim: "#FFFFFF" },
  MUN: { body: "#DA291C", sleeve: "#DA291C", trim: "#111111" },
  NEW: { body: "#FFFFFF", sleeve: "#111111", trim: "#111111", stripe: "#111111" },
  NFO: { body: "#DD0000", sleeve: "#DD0000", trim: "#FFFFFF" },
  TOT: { body: "#FFFFFF", sleeve: "#FFFFFF", trim: "#132257" },
  SUN: { body: "#EB172B", sleeve: "#EB172B", trim: "#111111", stripe: "#FFFFFF" },
};
const KEEPER: Kit = { body: "#C9F24B", sleeve: "#1F2A12", trim: "#1F2A12" };
const FALLBACK: Kit = { body: "#9AA5A0", sleeve: "#9AA5A0", trim: "#FFFFFF" };
const BODY = "M30 12 L41 7 Q50 14 59 7 L70 12 L72 36 L72 93 Q50 97 28 93 L28 36 Z";
let sequence = 0;

/** Minimal SVG shirt in illustrative club colours; keepers get a distinct keeper shirt. */
export function jerseySvg(team: string | null | undefined, keeper = false): string {
  const club = (team && KITS[team]) || FALLBACK;
  const kit = keeper ? { ...KEEPER, trim: club.body } : club;
  const id = `kit-clip-${++sequence}`;
  const stripes = kit.stripe
    ? `<g clip-path="url(#${id})">${[31, 43, 55, 67].map((x) => `<rect x="${x}" y="0" width="6" height="100" fill="${kit.stripe}"/>`).join("")}</g>`
    : "";
  const edge = 'stroke="rgba(0,0,0,.32)" stroke-width="1.5" stroke-linejoin="round"';
  return `<svg class="jersey" viewBox="0 0 100 100" aria-hidden="true" focusable="false"><defs><clipPath id="${id}"><path d="${BODY}"/></clipPath></defs><path d="M30 12 L12 25 L20 42 L28 37 Z" fill="${kit.sleeve}" ${edge}/><path d="M70 12 L88 25 L80 42 L72 37 Z" fill="${kit.sleeve}" ${edge}/><path d="${BODY}" fill="${kit.body}"/>${stripes}<path d="${BODY}" fill="none" ${edge}/><path d="M41 7 Q50 14 59 7 L56 6 Q50 10 44 6 Z" fill="${kit.trim}"/><path d="M20 42 L12 25 M80 42 L88 25" stroke="${kit.trim}" stroke-width="3" stroke-linecap="round"/></svg>`;
}
