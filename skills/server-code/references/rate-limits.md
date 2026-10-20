# Rate limits (SEC-07)

Every endpoint that spends money (an LLM, a paid API, an email or SMS send) or guards credentials (login, signup, password reset, OTP) gets a limiter. The user does not have to ask for it. Build it and say in your reply what you added: the keys, the limits and why.

## 1. Reuse the repo's limiter

Search before writing one: `grep -rniE "rate.?limit|limiter|throttle" .`, and check the dependencies for `@upstash/ratelimit`, `rate-limiter-flexible`, `express-rate-limit`, `slowapi`, `flask-limiter` or `django-ratelimit`. If one exists, call it with the keys from section 4. Write a new one only when nothing exists, and put it in one shared module, not inline in the route.

## 2. Pick the store

- **Serverless, or more than one instance:** a shared store (Redis, a KV service or a database table). An in-memory counter lives in one instance, so on serverless it limits almost nothing.
- **One long-running process:** in-memory is acceptable. Say in your reply that it resets on restart and must move to a shared store before you scale out.

## 3. A fixed-window limiter

A fixed window is simple and good enough for abuse and cost control. The window number is part of the key, so a key that somehow misses its expiry only wastes memory; it never blocks anyone past its window.

```ts
// rate-limit.ts
export interface CounterStore {
  /** Adds 1 to `key` and returns the new count; the key expires after `ttlSeconds`. */
  increment(key: string, ttlSeconds: number): Promise<number>;
}

export type LimitResult = { ok: true } | { ok: false; retryAfterSeconds: number };

export async function checkLimit(
  store: CounterStore,
  key: string,
  limit: number,
  windowSeconds: number,
): Promise<LimitResult> {
  // Wall clock on purpose: every instance must agree on the window.
  const nowSeconds = Math.floor(Date.now() / 1000);
  const window = Math.floor(nowSeconds / windowSeconds);
  const count = await store.increment(`rl:${key}:${windowSeconds}:${window}`, windowSeconds);
  if (count <= limit) return { ok: true };
  return { ok: false, retryAfterSeconds: Math.max(1, (window + 1) * windowSeconds - nowSeconds) };
}

/** One process only: resets on restart and is not shared between instances. */
export class MemoryStore implements CounterStore {
  private counts = new Map<string, { n: number; expiresAt: number }>();

  async increment(key: string, ttlSeconds: number): Promise<number> {
    const now = Date.now();
    if (this.counts.size > 10_000) {
      for (const [k, v] of this.counts) if (v.expiresAt <= now) this.counts.delete(k);
    }
    const hit = this.counts.get(key);
    if (!hit || hit.expiresAt <= now) {
      this.counts.set(key, { n: 1, expiresAt: now + ttlSeconds * 1000 });
      return 1;
    }
    hit.n += 1;
    return hit.n;
  }
}

/** Any Redis-like client with INCR and EXPIRE. */
export function redisStore(redis: {
  incr(key: string): Promise<number>;
  expire(key: string, seconds: number): Promise<unknown>;
}): CounterStore {
  return {
    async increment(key, ttlSeconds) {
      const n = await redis.incr(key);
      if (n === 1) await redis.expire(key, ttlSeconds);
      return n;
    },
  };
}
```

A database table works the same way: a row per key with a count and an expiry, updated with one atomic `INSERT ... ON CONFLICT ... DO UPDATE SET count = count + 1 ... RETURNING count`.

## 4. Key it per user and per IP

Check both. The per-user key stops one account from running up the bill; the per-IP key covers signed-out callers and one person with many accounts.

The client IP must come from the platform or proxy you trust, in the one header it sets and overwrites on every request (for example `cf-connecting-ip` behind Cloudflare, or the `x-real-ip` your own nginx sets). Name that header per deployment. Never read the IP from an arbitrary request header: a client can send any header it likes, and when a proxy appends to `x-forwarded-for`, the leftmost entry is whatever the client sent.

Never fall back to a shared placeholder such as `"unknown"`. When the header is missing, every request would land in one `ip:unknown` bucket: a global limit that answers 429 to everyone. Instead:
- the IP is unknown but the user is signed in: skip the IP key, and the per-user key carries the limit;
- neither is known: use one deliberately low global bucket for anonymous traffic, so it can't run up the bill, and fix the IP header so this path stops firing.

```ts
// The one header your platform or proxy sets and overwrites, e.g. "cf-connecting-ip".
const IP_HEADER = process.env.CLIENT_IP_HEADER;

export function clientIp(headers: Headers): string | null {
  if (!IP_HEADER) return null;
  return headers.get(IP_HEADER)?.trim() || null;
}

let warnedNoIp = false;

export async function limitPaidCall(
  store: CounterStore,
  userId: string | null,
  ip: string | null,
): Promise<LimitResult> {
  if (userId) {
    const perUser = await checkLimit(store, `user:${userId}`, 10, 60);
    if (!perUser.ok) return perUser;
  }
  if (ip) return checkLimit(store, `ip:${ip}`, 30, 60);
  if (userId) return { ok: true }; // signed in, IP unknown: the per-user key carries the limit
  // Anonymous and no IP: one shared bucket for all such callers, kept low on purpose.
  if (!warnedNoIp) {
    warnedNoIp = true;
    console.warn("rate limit: no client IP; check CLIENT_IP_HEADER");
  }
  return checkLimit(store, "anon:no-ip", 20, 60);
}
```

Pick the numbers from what one call costs and what a real user needs, and state them in your reply. For an LLM endpoint, add a daily cap per user as a second window (``checkLimit(store, `user-day:${userId}`, 200, 86_400)``), so a steady trickle can't run up the bill either. For login, reset and OTP, key on the account identifier (the email) as well as the IP, so one account can't be brute-forced from many addresses.

## 5. Where the check goes

The limiter runs after authentication (so the per-user key exists) and before the paid call, never after it.

A route handler on the Fetch API (Next.js route handlers, SvelteKit, Remix, Hono, Workers):

```ts
export async function POST(request: Request): Promise<Response> {
  const user = await requireUser(request); // the repo's auth helper (SEC-01)
  const limit = await limitPaidCall(store, user.id, clientIp(request.headers));
  if (!limit.ok) {
    return Response.json(
      { error: "Too many requests" },
      { status: 429, headers: { "Retry-After": String(limit.retryAfterSeconds) } },
    );
  }
  // Only now call the LLM or paid API.
}
```

A server action can't set a status code, so return a typed error that the UI shows:

```ts
export async function summarize(formData: FormData) {
  // Server action: the module starts with the "use server" directive.
  const user = await requireUser();
  const headers = await requestHeaders(); // your framework's request headers (Next.js: headers() from next/headers)
  const limit = await limitPaidCall(store, user.id, clientIp(headers));
  if (!limit.ok) return { error: "rate_limited", retryAfterSeconds: limit.retryAfterSeconds } as const;
  // Only now call the LLM or paid API.
}
```

Express and similar frameworks: the same check as route middleware, after the auth middleware. Set `app.set("trust proxy", 1)` (or your proxy's hop count) so `req.ip` is the client, not the proxy; without a trusted proxy, `req.ip` is the direct peer.

```ts
async function limitPaid(req, res, next) {
  const limit = await limitPaidCall(store, req.user.id, req.ip ?? null);
  if (!limit.ok) {
    res.set("Retry-After", String(limit.retryAfterSeconds));
    return res.status(429).json({ error: "Too many requests" });
  }
  next();
}

app.post("/api/summarize", requireAuth, limitPaid, summarizeHandler);
```

Python (FastAPI, Flask, Django) takes the same shape: one shared limiter function, called after auth and before the paid call, returning 429 with `Retry-After`.

## 6. Cap the size too

- Reject request bodies over a fixed byte cap: check `content-length` first, then count the bytes you actually read.
- Cap page size in list endpoints (for example at most 100 rows) whatever the client asks for.
- For LLM calls, cap the prompt length and set `max_tokens`.

## 7. Prove it

```ts
test("the summarize endpoint answers 429 past the per-user limit", async () => {
  for (let i = 0; i < 10; i++) expect((await callSummarize(userA)).status).not.toBe(429);
  const res = await callSummarize(userA);
  expect(res.status).toBe(429);
  expect(Number(res.headers.get("Retry-After"))).toBeGreaterThan(0);
  expect(paidApiMock.calls).toBe(10); // the 11th call never reached the paid API
});
```
