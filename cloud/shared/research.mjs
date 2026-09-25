export const MAX_BODY_BYTES = 512 * 1024;
export const FPL_BOOTSTRAP_MAX_BODY_BYTES = 2 * 1024 * 1024;
export const MAX_EXCERPTS = 32;
export const SOURCES = Object.freeze([
  Object.freeze({ id: "official-fpl-news", publisher: "Fantasy Premier League", host: "fantasy.premierleague.com", url: "https://fantasy.premierleague.com/api/bootstrap-static/" }),
  Object.freeze({ id: "official-arsenal-news", publisher: "Arsenal Football Club", host: "www.arsenal.com", url: "https://www.arsenal.com/news/all/1" })
]);
export function exactFpl(source) { const policy = SOURCES[0]; return source && source.id === policy.id && source.publisher === policy.publisher && source.host === policy.host && source.url === policy.url; }
export function safeHttps(url) { try { const parsed = new URL(url); return parsed.protocol === "https:" && !parsed.username && !parsed.password && !["localhost", "127.0.0.1", "::1"].includes(parsed.hostname); } catch { return false; } }
function bounded(value) { return typeof value === "string" && value.trim() ? value.trim().slice(0, 4096) : null; }
export function extractJson(body, source, capturedAt) {
  const payload = JSON.parse(body); const excerpts = [];
  if (exactFpl(source)) { for (const item of Array.isArray(payload && payload.elements) ? payload.elements : []) { if (excerpts.length >= MAX_EXCERPTS) break; const text = typeof item.news === "string" && item.news.trim() ? item.news.slice(0, 4096) : null; if (text) excerpts.push({ kind: "json_field", text, captured_at_utc: capturedAt }); } return { title: null, excerpts, claims: [] }; }
  ["title", "description", "summary"].forEach((key) => { const text = bounded(payload && payload[key]); if (text) excerpts.push({ kind: "json_field", text, captured_at_utc: capturedAt }); });
  return { title: excerpts[0] ? excerpts[0].text : null, excerpts, claims: [] };
}
export function extractHtml(body, source, capturedAt) {
  const excerpts = [];
  const title = bounded((body.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [])[1]?.replace(/<[^>]+>/g, " ").replace(/\s+/g, " "));
  const description = bounded((body.match(/<meta[^>]+name=["']description["'][^>]+content=["']([^"']*)["']/i) || [])[1]);
  for (const text of [title, description]) if (text && excerpts.length < MAX_EXCERPTS) excerpts.push({ kind: "html_metadata", text, captured_at_utc: capturedAt });
  return { title, excerpts, claims: [] };
}
