---
name: server-code
description: Use when writing, changing or reviewing server-side code that handles requests or data, such as an API route, server action, RPC procedure, webhook handler, background job or queue consumer, a CSV, TSV or XLSX export, or a cache. Also use it for any endpoint that calls an LLM or a paid API, or sends email or SMS, however small the change. Applies to Next.js, Express, Fastify, Hono, SvelteKit, Remix, FastAPI, Flask, Django and similar frameworks.
---

# Server code

Server handlers are where a missing check becomes a breach or a bill. These rules make the safe version the default.

## Core rule: build the safeguard, then say so

When a rule below needs more than the user asked for (a rate limiter, an auth check, a cell guard, a pending table, a schema), build it in the same change, by default. In your final reply, list what you added and why, one line each. Never leave it out with an offer to add it later, and never stop to ask permission for it.

Example reply line: "Added a per-user (10/min) and per-IP (30/min) rate limit on POST /api/chat, because each call spends LLM credits."

If you catch yourself writing one of these, stop and build the safeguard instead:
- "You may want to add rate limiting" or "consider adding an auth check".
- "I kept it minimal, as requested."
- "The page (or the middleware) already checks this."
- "It's only a demo" or "it's an internal tool".

If `.claude/practices/server-code.md` exists in the repo, read it first. Its repo rules (helper names, exemptions) win over the defaults here.

## Gate rules: check every one before you finish

Each rule names its proof: the test that shows it holds. Write that test where the repo has a test setup; otherwise list it in your reply as the check to run.

- **SEC-07: Build a rate limit on anything that spends money or guards credentials.** That means any endpoint that calls an LLM or a paid API or sends email or SMS, plus login, signup, password reset and OTP. Key it per user and per IP, check it before the paid call, and answer 429 with `Retry-After`. Reuse the repo's limiter when one exists. Cap body size and page size too. Proof: N+1 rapid requests get 429. Pattern: [references/rate-limits.md](references/rate-limits.md).
- **SEC-17: Guard every spreadsheet cell that holds user text.** In a CSV, TSV or XLSX export, prefix `'` to any user-supplied cell that starts with `=`, `+`, `-`, `@`, tab or CR, and quote every cell per RFC 4180. Proof: an exported `=HYPERLINK(...)` cell opens as text. Pattern: [references/csv-export.md](references/csv-export.md).
- **SEC-01: Build authentication and authorization into every handler and server action**, denying by default. Middleware, a page-level check or a hidden button is not access control: anyone can POST to a route or server action directly. Proof: unauthenticated and wrong-role calls return 401/403 in a test.
- **SEC-02: Take the actor, role and tenant from the verified session**, never from the body, params or query. Proof: a spoofed `userId` or `role` in the request changes nothing.
- **SEC-03: Scope every object lookup to the caller.** Put the owner or tenant in the query, or authorize after loading. Proof: user B asking for user A's id gets 403 or 404.
- **SEC-04: Whitelist the fields a write accepts.** Never spread a request body into an insert or update (`...body`, `update(body)`, `**data`). Proof: an extra `role` or `is_admin` field is ignored.

## When a practices hook stops an edit

A hook may deny an edit once and name a rule id. Fix the code. If the match is a false positive, keep the code and add a comment in the file: `practices-allow: <id> <reason>`. For example, a health check that is public on purpose gets `// practices-allow: SEC-01 public endpoint`. Never use the comment to skip a safeguard the rule asks for.

## Input, output and errors

- **SEC-05: Validate every input server-side against a strict schema**: reject unknown keys and cap sizes. Client checks are UX only. Re-validate stored user fields when you display them. Proof: oversize, wrong-type and extra-key payloads get 4xx.
- **SEC-06: Return a minimal DTO**, never the raw row or `select *`. Proof: the response has no internal columns (hashes, owner ids, tokens).
- **SEC-08: Fail closed.** An error in authz or validation denies; no empty catch that carries on. Return a generic error and keep the detail in logs, never a secret or config value. Proof: a forced exception returns 4xx/5xx with no side effect, and a planted secret is absent from the output.
- **SEC-09: Change state only with POST, PUT, PATCH or DELETE.** Cookie-authenticated mutations check `Origin` or a CSRF token; upload and forwarding endpoints check same-origin. Proof: GET never changes state, and a foreign `Origin` is refused.
- **SEC-13: No shell strings, `eval`, `new Function` or unsafe deserializers on input** (`pickle.loads`, `yaml.load` without `SafeLoader`). Pass argv arrays; privileged helpers take data, never code. Proof: a grep finds none on input paths.

## Calls that leave your server

- **SEC-10: Server-side fetches of user-supplied URLs** allowlist protocol, host and port, block private and link-local ranges, and don't follow redirects. Proof: requests to `127.0.0.1`, `169.254.169.254` or via a redirect are refused.
- **SEC-16: When you forward user content to a third party** (chat, email, webhook), escape its markup and turn mentions off. Proof: a mention and Markdown input arrive inert.
- **REL-01: Give every outbound call explicit connect and read timeouts.** Derive the value from measured downstream latency, and pass deadlines down the chain. Proof: every call site, or the shared client, sets a timeout.
- **REL-02: Retry only transient failures** (timeout, reset, 429, 503), with capped attempts and exponential backoff with jitter, at exactly one layer. Proof: a fake-clock test shows a 400 is not retried, the delays grow and vary, and the cap surfaces the error.
- **REL-03: Never retry a side-effecting call unless it is idempotent or carries an idempotency key.** Make one key per logical operation, persist it before the first attempt, and reuse it on every retry. Proof: all attempts send the same key.
- **REL-04: "Upstream unreachable" is not "signed out".** Only a real auth answer yields 401/403; a throw, timeout, 5xx or edge page yields a retryable 503. Reads may auto-retry. A write auto-retries only under REL-03; otherwise tell the user to check whether it saved. Proof: a fault-injection test gets the 503 and the retry.
- **REL-05: Give a slow or flaky remote dependency a circuit breaker** with a tested fallback, and give each dependency its own pool. Proof: with one dependency stalled in a test, the others still serve.

## Uploads

- **SEC-11: Treat every upload as hostile.** Cap the size; check both the extension and the magic bytes (never trust the MIME type); name stored files yourself; keep paths inside the upload directory; store files non-executable; re-encode images you display. Proof: oversize, wrong-signature, `../` and script-SVG samples are rejected or inert.

## Webhooks

- **SEC-12: Verify the signature on the raw body first**, compare it timing-safe, reject stale timestamps, and fail closed when the secret is unset. Proof: tampered, stale and unset-secret cases return 400 with no side effect.
- **REL-11: Verify (SEC-12), enqueue and return 2xx fast.** Dedupe by a persisted, unique event id, and re-fetch the current state rather than trusting delivery order. Proof: the same event delivered twice changes state once, and out-of-order delivery ends correct.

## Money, inventory and multi-step flows

- **SEC-15: Enforce step order and atomicity server-side** in payment, inventory, balance and verification flows (transactions, locks). Never trust the client to sequence steps. Proof: skip-step and parallel-request tests.
- **REL-10: Retryable mutating endpoints store the key, params and result.** Replay the saved result, and reject the same key with different params. Proof: the same key returns the same result; changed params give an error.

## Jobs and queues

- **REL-12: Jobs run at least once.** Make handlers idempotent, and pass ids as job arguments, not objects. Proof: running the handler twice gives the same end state.
- **REL-13: Never write the DB and publish an event or job as two separate steps.** Use an outbox, or enqueue after commit. Proof: a crash between the steps loses or duplicates nothing.
- **REL-14: Before adding polling, a cron or an export, estimate MB per run times runs per month** against the egress quota, and CI minutes against the plan. Loops calling a paid or rate-limited service get a budget and stop at the first block. Proof: the estimate is in the PR, and a test shows the loop stops on a block.

## Lists, caches and operations

- **UX-21: List endpoints omit heavy fields**, which clients fetch per item. Placeholders have a fixed size, and only the newest fetch answer is applied. Proof: a payload-size budget in a test.
- **REL-17: Don't make a cache load-bearing.** Test an empty-cache start, derive the TTL from how much staleness is tolerable, and emit hit/miss metrics. A cached lookup stays scoped to the caller (SEC-03): per-user data keys on the user or tenant. Proof: the service runs with a cold cache.
- **REL-15: Health checks are local** and never fail every instance on a shared dependency. Proof: the check touches no shared downstream.
- **REL-16: Deduplicate and rate-limit alerts**, and keep them to ids and labels, never secrets, personal data or content. Instrument latency, traffic, errors and saturation, and log events to stdout. Proof: a repeated alert is suppressed, and each signal has a dashboard or alert.
