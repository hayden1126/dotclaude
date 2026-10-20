// Planted bug (the pattern Sonnet wrote): a prefix check on the raw string, which is
// returned as is; "/<tab>/evil.com" passes, and the browser strips the tab.
const BACKSLASH = String.fromCharCode(92);

export function nextPath(value: unknown): string {
  if (typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.includes(BACKSLASH)) {
    return value;
  }
  return "/";
}
