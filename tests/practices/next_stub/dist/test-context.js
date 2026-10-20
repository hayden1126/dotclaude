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

// Like Next, cookies set or deleted through cookies() while `fn` runs reach the Response it
// returns as Set-Cookie headers.
export function runWithRequest(request, fn) {
  const cookies = parseCookieHeader(request.headers.get("cookie"));
  const store = { cookies, headers: request.headers, setCookies: [] };
  return requestStore.run(store, () => {
    const out = fn();
    return out && typeof out.then === "function" ? out.then((value) => withSetCookies(value, store)) : withSetCookies(out, store);
  });
}

function withSetCookies(value, store) {
  if (!(value instanceof Response) || store.setCookies.length === 0) return value;
  let res = value;
  try {
    for (const line of store.setCookies) res.headers.append("set-cookie", line);
  } catch {
    // Response.redirect() and friends have immutable headers: answer with a copy.
    res = new Response(value.body, value);
    for (const line of store.setCookies) res.headers.append("set-cookie", line);
  }
  return res;
}
