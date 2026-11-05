# Request-supplied redirects (SEC-39)

After sign-in, apps send the user "back where they came from" with a `next`, `returnTo`, `redirect` or `callbackUrl` param. If the check on that value is wrong, the app becomes an open redirect: a link on your own domain that lands the user on a look-alike sign-in page. Build the validator below whenever code reads such a param, without being asked, and say so in your reply.

## The validator

```ts
// safe-redirect.ts
// The app's public origin from config, never from request.url or the Host header:
// behind a proxy those carry the server's own address, and Host is client-supplied.
const APP_ORIGIN = new URL(requiredEnv("APP_ORIGIN")).origin; // such as https://app.example.com
const MAX_LENGTH = 2048;

/** Backslash, C0 control characters (tab, CR and LF among them) and DEL. */
function hasUnsafeChar(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c <= 0x1f || c === 0x7f || c === 0x5c) return true;
  }
  return false;
}

/**
 * A same-origin path (with its query and fragment) for a request-supplied target, or the
 * fallback. Every output is an input that maps to itself, so a stored value checks again
 * to the same answer.
 */
export function safeRedirectPath(raw: unknown, fallback = "/"): string {
  // 1. One string only: a repeated param can arrive as an array or an object.
  if (typeof raw !== "string" || raw.length === 0 || raw.length > MAX_LENGTH) return fallback;
  // 2. Before any parsing: the parser rewrites these characters (see the traps below).
  if (hasUnsafeChar(raw)) return fallback;
  // 3. A path only. Refusing an absolute URL, even to your own origin, costs nothing.
  if (!raw.startsWith("/")) return fallback;
  // 4. Parse against the app's origin and compare origins.
  let url: URL;
  try {
    url = new URL(raw, APP_ORIGIN);
  } catch {
    return fallback;
  }
  if (url.origin !== APP_ORIGIN) return fallback;
  // 5. Dot-segment removal can leave a path that starts with "//": collapse it to one "/".
  const path = "/" + (url.pathname + url.search + url.hash).replace(/^\/+/, "");
  // 6. Percent-encoding can lengthen the value past step 1's limit.
  return path.length <= MAX_LENGTH ? path : fallback;
}

/** The absolute URL for the Location header. The origin is added here and nowhere else. */
export function safeRedirect(raw: unknown, fallback = "/"): string {
  return new URL(safeRedirectPath(raw, fallback), APP_ORIGIN).href;
}
```

Call `safeRedirectPath` wherever the value arrives or is stored (the sign-in page that puts `next` into a form field or a cookie, an OAuth `state` record), and `safeRedirect` only where the server redirects. Store the path, never the absolute URL: step 3 refuses an absolute URL, so a stored one would send every sign-in to the fallback on its second check. Read the param once: the framework has already decoded it, and a second `decodeURIComponent` after the check turns `%2F%2F` into `//`.

## When the validator also runs in the browser

A browser has no server env var, so `APP_ORIGIN` above throws as soon as the module loads, while server rendering and Node tests still pass. Keep the signature the task or the code already names, instead of adding a required argument that breaks its other callers, and change the code above in three places:

1. Delete the module-level `APP_ORIGIN` line, and import no env module (one marked `server-only`, or one that validates at load, breaks the client bundle).
2. Add this helper:

   ```ts
   // In a browser, the page's own origin is the app's origin. On the server, use config.
   function appOrigin(): string {
     if (typeof window !== "undefined") return window.location.origin;
     const origin = process.env.APP_ORIGIN;
     if (!origin) throw new Error("APP_ORIGIN is required");
     return new URL(origin).origin;
   }
   ```

3. At the top of `safeRedirectPath` and `safeRedirect`, write `const origin = appOrigin();` and use `origin` where the code above says `APP_ORIGIN`. Keep it outside the `try`: inside, a missing server setting would be caught and every value would go to the fallback with no error.

## The traps, and why each check exists

| input | the check it beats | what happens |
|---|---|---|
| `//evil.example` | `raw.startsWith("/")` | A scheme-relative URL: the browser goes to `evil.example`. Step 4 catches it. |
| `/\evil.example` | `startsWith("/") && !startsWith("//")` | Browsers and the URL parser read `\` as `/` in http and https URLs, so this is `//evil.example`. Step 2 refuses it. |
| `/%09/evil.example` (a tab, once decoded), or CR or LF in its place | the same raw-string check | The URL parser deletes tab, CR and LF anywhere in the input, so the value parses as `//evil.example` after the string check passed. Step 2 refuses it. |
| `/.//evil.example` | an origin check that then returns `url.pathname` | The parse stays on your origin, but dot-segment removal leaves the path as `//evil.example`. Sent as a bare path in `Location`, it is scheme-relative again. Step 5 collapses it to `/evil.example`, a path on your origin. |
| `?next=/ok&next=//evil.example` | code that assumes a string | Express and `qs` give an array (and `next[a]=b` gives an object). A check on one element and a redirect on another, or a `String()` join, slips through, and a method call on it throws a 500. Step 1 refuses it. |
| `https://evil.example`, `javascript:alert(1)` | none | Step 3 refuses anything that isn't a path. |

## OAuth and other external targets

- **`redirect_uri`:** an exact string match against the client's registered list. No prefix, substring or wildcard match, and no "same registrable domain".
- **`state`:** a random value bound to the user's pre-sign-in session and checked at the callback. Store the `next` path from `safeRedirectPath` server-side with it, and redirect with `safeRedirect` at the callback.
- **PKCE** for public clients and, where the provider supports it, for confidential ones too.
- **A redirect to a partner site** after an action: look the target up by key in a fixed map (`{ billing: "https://billing.example.com/return" }`), never by a URL from the request.

## Frameworks

- **Next.js:** `redirect(safeRedirect(searchParams.get("next")))`. For `NextResponse.redirect`, pass the result straight in; never `new URL(next, request.url)` on the raw value.
- **Express:** `res.redirect(safeRedirect(req.query.next))`.
- **Django:** `url_has_allowed_host_and_scheme(url, allowed_hosts={settings.APP_HOST}, require_https=True)`, with the host from settings rather than `request.get_host()`.
- **Auth.js:** its default `redirect` callback keeps targets on `baseUrl`. An override also receives absolute same-origin URLs, which step 3 refuses, so strip `baseUrl` first:

  ```ts
  redirect({ url, baseUrl }) {
    const own = url === baseUrl || url.startsWith(baseUrl + "/");
    return safeRedirect(own ? url.slice(baseUrl.length) || "/" : url);
  }
  ```

## Prove it

```ts
const cases: [unknown, string][] = [
  ["/dashboard?tab=2#top", "/dashboard?tab=2#top"],
  ["//evil.example", "/"],
  ["/\\evil.example", "/"],
  ["/\t/evil.example", "/"],
  ["/\r\n/evil.example", "/"],
  ["https://evil.example", "/"],
  ["javascript:alert(1)", "/"],
  [["/ok", "//evil.example"], "/"],
  ["/.//evil.example", "/evil.example"],
];

test.each(cases)("safeRedirectPath(%j)", (raw, want) => {
  const path = safeRedirectPath(raw);
  expect(path).toBe(want);
  expect(safeRedirectPath(path)).toBe(path); // a stored value checks again to the same answer
  expect(safeRedirect(raw)).toBe(new URL(want, "https://app.example.com").href);
});
```

Run this table in a Node test environment: under jsdom, `window.location.origin` is the test page's and the last line fails. If the validator also runs in the browser, add a test in its own file, since a module loads only once:

```ts
test("the browser form loads and checks with no server config", async () => {
  delete process.env.APP_ORIGIN;
  vi.stubGlobal("window", { location: { origin: "https://app.example.com" } }); // or assign globalThis.window
  const { safeRedirectPath } = await import("./safe-redirect");
  expect(safeRedirectPath("/dashboard?tab=2")).toBe("/dashboard?tab=2");
  expect(safeRedirectPath("//evil.example")).toBe("/");
  expect(safeRedirectPath("/.//evil.example")).toBe("/evil.example");
});
```

Add two end-to-end cases. Sign in with `?next=/.//evil.example` and assert that `Location` is `https://app.example.com/evil.example`. Then sign in with `?next=/dashboard?tab=2` through the form (the page stores the path, the server checks it again) and assert that `Location` is `https://app.example.com/dashboard?tab=2`.
