// Planted bug (the pattern Opus wrote): the checks run on the raw string, but the value
// returned is the parsed path, and parsing turns "/.//evil.com" into "//evil.com".
const BACKSLASH = String.fromCharCode(92);

export function nextPath(value: unknown): string {
  const raw = typeof value === "string" ? value : "";
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.includes(BACKSLASH)) return "/";
  const url = new URL(raw, "http://localhost");
  return url.pathname + url.search + url.hash;
}
