// Runs a function inside a request scope, so cookies() and headers() work in tests.
import { parseCookieHeader, requestStore } from "./context.js";

export function runWithCookies(cookieMap, fn) {
  const cookies = new Map(cookieMap instanceof Map ? cookieMap : Object.entries(cookieMap ?? {}));
  const headers = new Headers();
  if (cookies.size) {
    headers.set("cookie", [...cookies].map(([n, v]) => `${n}=${encodeURIComponent(v)}`).join("; "));
  }
  return requestStore.run({ cookies, headers }, fn);
}

export function runWithRequest(request, fn) {
  const cookies = parseCookieHeader(request.headers.get("cookie"));
  return requestStore.run({ cookies, headers: request.headers }, fn);
}
