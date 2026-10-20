// Secure: parse against a fixed origin, require that origin, then refuse a normalized path
// that a browser would read as another host ("//" or "/\"), and any control character.
const ORIGIN = "http://app.internal";
const BACKSLASH = String.fromCharCode(92);

export function nextPath(value: unknown, fallback = "/"): string {
  const raw = Array.isArray(value) ? value[0] : value;
  if (typeof raw !== "string" || !raw.startsWith("/")) return fallback;
  for (const ch of raw) {
    const code = ch.charCodeAt(0);
    if (code < 0x20 || code === 0x7f) return fallback;
  }
  let url: URL;
  try {
    url = new URL(raw, ORIGIN);
  } catch {
    return fallback;
  }
  if (url.origin !== ORIGIN) return fallback;
  const path = `${url.pathname}${url.search}${url.hash}`;
  if (path.startsWith("//") || path.startsWith("/" + BACKSLASH)) return fallback;
  return path;
}
