# Request-supplied redirects (SEC-39)

After sign-in, apps send the user "back where they came from" with a `next`, `returnTo`, `redirect` or `callbackUrl` param. If the check on that value is wrong, the app becomes an open redirect: a link on your own domain that lands the user on a look-alike sign-in page. Build the validator below whenever code reads such a param, without being asked, and say so in your reply.

## The validator

```ts
// safe-redirect.ts
// The app's public origin from config, never from request.url or the Host header:
// behind a proxy those carry the server's own address, and Host is client-supplied.
const APP_ORIGIN = new URL(requiredEnv("APP_ORIGIN")).origin; // such as https://app.example.com

/** Backslash, C0 control characters (tab, CR and LF among them) and DEL. */
function hasUnsafeChar(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c <= 0x1f || c === 0x7f || c === 0x5c) return true;
  }
  return false;
}

/** A same-origin absolute URL for a request-supplied target, or the fallback. */
export function safeRedirect(raw: unknown, fallback = "/"): string {
  const home = new URL(fallback, APP_ORIGIN).href;
  // 1. One string only: a repeated param can arrive as an array or an object.
  if (typeof raw !== "string" || raw.length === 0 || raw.length > 2048) return home;
  // 2. Before any parsing: the parser rewrites these characters (see the traps below).
  if (hasUnsafeChar(raw)) return home;
  // 3. A path only. Refusing an absolute URL, even to your own origin, costs nothing.
  if (!raw.startsWith("/")) return home;
  // 4. Parse against the app's origin and compare origins.
  let url: URL;
  try {
    url = new URL(raw, APP_ORIGIN);
  } catch {
    return home;
  }
  if (url.origin !== APP_ORIGIN) return home;
  // 5. The absolute URL, never url.pathname: the path may now start with "//".
  return url.href;
}
```

Use it at both ends: when the sign-in page receives `next` (before it goes into a form field or a cookie) and again when the server redirects. Read the param once: the framework has already decoded it, and a second `decodeURIComponent` after the check turns `%2F%2F` into `//`.

## The traps, and why each check exists

| input | the check it beats | what happens |
|---|---|---|
| `//evil.example` | `raw.startsWith("/")` | A scheme-relative URL: the browser goes to `evil.example`. Step 4 catches it. |
| `/\evil.example` | `startsWith("/") && !startsWith("//")` | Browsers and the URL parser read `\` as `/` in http and https URLs, so this is `//evil.example`. Step 2 refuses it. |
| `/%09/evil.example` (a tab, once decoded), or CR or LF in its place | the same raw-string check | The URL parser deletes tab, CR and LF anywhere in the input, so the value parses as `//evil.example` after the string check passed. Step 2 refuses it. |
| `/.//evil.example` | an origin check that then returns `url.pathname` | The parse stays on your origin, but dot-segment removal leaves the path as `//evil.example`. Sent as a bare path in `Location`, it is scheme-relative again. Step 5 returns the absolute URL, which keeps the user on your origin. |
| `?next=/ok&next=//evil.example` | code that assumes a string | Express and `qs` give an array (and `next[a]=b` gives an object). A check on one element and a redirect on another, or a `String()` join, slips through, and a method call on it throws a 500. Step 1 refuses it. |
| `https://evil.example`, `javascript:alert(1)` | none | Step 3 refuses anything that isn't a path. |

## OAuth and other external targets

- **`redirect_uri`:** an exact string match against the client's registered list. No prefix, substring or wildcard match, and no "same registrable domain".
- **`state`:** a random value bound to the user's pre-sign-in session and checked at the callback. Store the `next` path server-side with it, validated by `safeRedirect` when stored and again when used.
- **PKCE** for public clients and, where the provider supports it, for confidential ones too.
- **A redirect to a partner site** after an action: look the target up by key in a fixed map (`{ billing: "https://billing.example.com/return" }`), never by a URL from the request.

## Frameworks

- **Next.js:** `redirect(safeRedirect(searchParams.get("next")))`. For `NextResponse.redirect`, pass the result straight in; never `new URL(next, request.url)` on the raw value.
- **Express:** `res.redirect(safeRedirect(req.query.next))`.
- **Django:** `url_has_allowed_host_and_scheme(url, allowed_hosts={settings.APP_HOST}, require_https=True)`, with the host from settings rather than `request.get_host()`.
- **Auth.js:** its default `redirect` callback keeps targets on `baseUrl`. If you override the callback, return `safeRedirect(url)` from it.

## Prove it

```ts
const HOME = "https://app.example.com/";
const cases: [unknown, string][] = [
  ["/dashboard?tab=2", "https://app.example.com/dashboard?tab=2"],
  ["//evil.example", HOME],
  ["/\\evil.example", HOME],
  ["/\t/evil.example", HOME],
  ["/\r\n/evil.example", HOME],
  ["https://evil.example", HOME],
  ["javascript:alert(1)", HOME],
  [["/ok", "//evil.example"], HOME],
  ["/.//evil.example", "https://app.example.com//evil.example"],
];

test.each(cases)("safeRedirect(%j)", (raw, want) => {
  const got = safeRedirect(raw);
  expect(got).toBe(want);
  expect(new URL(got).origin).toBe("https://app.example.com");
});
```

Add one end-to-end case: sign in with `?next=/.//evil.example` and assert that the `Location` header is an absolute URL on your origin.
