// One request store per process, shared by next/headers and the test helpers even if
// the module is reached through two different URLs.
import { AsyncLocalStorage } from "node:async_hooks";

const KEY = Symbol.for("next.stub.request-store");
export const requestStore = (globalThis[KEY] ??= new AsyncLocalStorage());

export function parseCookieHeader(header) {
  const cookies = new Map();
  if (!header) return cookies;
  for (const pair of header.split(";")) {
    const eq = pair.indexOf("=");
    if (eq === -1) continue;
    const name = pair.slice(0, eq).trim();
    if (!name) continue;
    let value = pair.slice(eq + 1).trim();
    try {
      value = decodeURIComponent(value);
    } catch {
      // keep the raw value
    }
    if (!cookies.has(name)) cookies.set(name, value);
  }
  return cookies;
}

export function serializeCookie(name, value, options = {}) {
  let out = `${name}=${encodeURIComponent(value)}`;
  if (options.maxAge !== undefined) out += `; Max-Age=${Math.floor(options.maxAge)}`;
  if (options.expires) out += `; Expires=${new Date(options.expires).toUTCString()}`;
  if (options.domain) out += `; Domain=${options.domain}`;
  out += `; Path=${options.path ?? "/"}`;
  if (options.httpOnly) out += "; HttpOnly";
  if (options.secure) out += "; Secure";
  if (options.sameSite) {
    const s = String(options.sameSite === true ? "strict" : options.sameSite);
    out += `; SameSite=${s[0].toUpperCase()}${s.slice(1).toLowerCase()}`;
  }
  return out;
}

// cookies().set accepts (name, value, options) or ({ name, value, ...options }).
export function cookieArgs(args) {
  if (typeof args[0] === "object" && args[0] !== null) {
    const { name, value, ...options } = args[0];
    return [name, String(value ?? ""), options];
  }
  return [args[0], String(args[1] ?? ""), args[2] ?? {}];
}
