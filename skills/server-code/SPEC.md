# server-code: spec

The public spec for the `server-code` skill: what it covers, the rule it puts first, how each rule is enforced, and the public source behind each one.

## Scope

The skill covers server code that handles requests or data: API routes, server actions, RPC procedures, webhook handlers, background jobs and queue consumers, spreadsheet exports, caches, and any endpoint that spends money (an LLM, a paid API, email or SMS). It owns 30 rules: SEC-01 to SEC-13, SEC-15 to SEC-17, REL-01 to REL-05, REL-10 to REL-17, and UX-21. Auth flows, sessions, secrets, queries and migrations belong to sibling skills.

Files:
- `SKILL.md`: the core rule and the gate rules first (they must survive compaction, which keeps only the start of a skill), then every other rule with its proof.
- `references/rate-limits.md` and `references/csv-export.md`: worked patterns for the two rules that weaker models most often leave out.
- `events.toml`: the events and patterns the practices hook reads.
- Samples for every event and pattern: `tests/setup/practices_samples/server-code.toml`.

## Core rule

When a rule needs more than the user asked for (a limiter, a guard, a pending table, a check), build it by default and say in the final reply what was added and why. Never leave it out with an offer to add it later, and never ask permission for it.

Why it comes first: in the repo's eval (`tests/practices`), the commonest failure across models was naming the risk, then leaving the fix out and offering it as an option. So every gate line and every deny message is worded "build X and say so".

## Enforcement levels

| level | what | when |
|---|---|---|
| L0 | The description, written as "Use when" plus concrete triggers, with no workflow summary | the model's choice |
| L1 | The practices hook detects an event in `events.toml`, by the file's path or by content anywhere in the file as it will read after the edit, and denies the edit once, with the event's lines, until the skill is loaded | at the edit |
| L2 | The hook matches a rule's `when` against the new text the edit writes, so only newly written code triggers, and denies once per file and rule. A guard (`unless`) or a `practices-allow: <id> <reason>` comment anywhere in the file as it will read after the edit suppresses it | before the edit lands |
| T | A test the skill tells the agent to write: the rule's proof | in the repo |
| L3s | A staged-diff scan at `git commit` | later PR |
| L3r | The PR-ready reviewer's checklist | later PR |
| L4 | The gate lines, re-injected after compaction | after compaction |

Every rule gets L0, L1 and L4 through the skill. The table below lists the further levels.

## Per-repo layer

- `.claude/practices/server-code.md`: prose repo rules the skill reads first, such as "the auth helper is `requireMember()`" or "the limiter lives in `lib/rate-limit.ts`". They win over the defaults.
- `.claude/practices/config.toml`: knobs for the hook. `[auth] helpers = ["requireMember"]` adds the repo's auth helpers to SEC-01: its `unless` holds the `{auth_helpers}` token, which the engine expands to its default helper names plus these, each regex-escaped. `[[disable]]` with a `rule` and a non-empty `reason` turns one event or rule off, and `enabled = false` turns the hook off for the repo.

## Rules

| id | rule | proof | levels | public source |
|---|---|---|---|---|
| SEC-01 | Authenticate and authorize inside every handler and server action, deny by default. Middleware, a page check or a hidden link is not access control. | unauthenticated and wrong-role calls return 401/403 in a test | L2 (SEC-01 and SEC-01-actions), T | ASVS 8.2.1, 8.3.1; [Next.js] |
| SEC-02 | Take the actor, role and tenant from the verified session, never from the body, params or query. | a spoofed `userId` or `role` in the request changes nothing | L2, T | ASVS 8.3.1; [Next.js] |
| SEC-03 | Scope every object lookup to the caller (owner or tenant in the query, or authorize after load). | two-user test: B asks for A's id and gets 403/404 | T | ASVS 8.2.2, 8.4.1; [IDOR] |
| SEC-04 | Whitelist writable fields; never spread a request body into an insert or update. | an extra `role` or `is_admin` field is ignored | L2, T | ASVS 15.3.3 |
| SEC-05 | Validate every input server-side against a strict schema: unknown keys rejected, sizes capped. Client checks are UX only. Re-validate stored user fields when they are displayed. | oversize, wrong-type and extra-key payloads get 4xx | T | ASVS 2.2.1, 2.2.2 |
| SEC-06 | Return a minimal DTO, never the raw row or `select *`. | the response has no internal columns (hashes, owner ids, tokens) | L3r | ASVS 15.3.1, 8.2.3; [Next.js] |
| SEC-07 | Rate-limit login, signup, reset, OTP, email and SMS sends, and any endpoint that spends money (LLM, paid API); cap body and page size. | N+1 rapid requests get 429 | T | ASVS 6.3.1, 2.4.1; [LLM10] |
| SEC-08 | Fail closed: an error in authz or validation denies, with no empty catch that continues. Return a generic error; keep detail (never a secret or config value) in logs. | a forced exception returns 4xx/5xx with no side effect; a planted secret is absent from the output | L2, T | ASVS 16.5.3, 16.5.1, 16.2.5; [Top10] A10 |
| SEC-09 | State changes use POST, PUT, PATCH or DELETE only. Cookie-auth mutations check Origin or a token; upload and forward endpoints check same-origin. | GET never changes state; a foreign Origin is refused | L3r | ASVS 3.5.3, 3.5.1; [Next.js] |
| SEC-10 | Server-side fetches of user-supplied URLs allowlist protocol, host and port, block private ranges, and don't follow redirects. | a request to 127.0.0.1, 169.254.169.254 or via a redirect is refused | T | ASVS 1.3.6, 15.3.2 |
| SEC-11 | Uploads: cap size, check both the extension and the magic bytes, name stored files yourself, keep paths inside the upload dir, store non-executable, re-encode displayed images. | oversize, wrong-signature, `../` and script-SVG samples rejected or inert | T | ASVS 5.2.1, 5.2.2, 5.3.1, 5.3.2 |
| SEC-12 | Webhooks verify the signature on the raw body first, compare timing-safe, reject stale timestamps, and fail closed when the secret is unset. | tampered, stale and unset-key cases return 400 with no side effect | T | [Stripe webhooks] (the timing-safe clause has no public source checked yet) |
| SEC-13 | No shell strings, `eval`/`new Function` or unsafe deserializers on input; privileged helpers take data, never code. | a grep finds none on input paths | L2 (SEC-13 and SEC-13-py) | ASVS 1.2.5, 1.3.2, 1.5.2 |
| SEC-15 | Enforce step order and atomicity server-side in payment, inventory, balance and verification flows; never trust the client to sequence steps. | skip-step and parallel-request tests | T | ASVS 2.3.1, 2.3.3, 2.3.4 |
| SEC-16 | When forwarding user content to a third party (chat, email, webhook), escape its markup and turn mentions off. | a mention and Markdown input arrive inert | T | no public source |
| SEC-17 | Spreadsheet exports (CSV, TSV, XLSX) of user-supplied text prefix any cell that starts with `=`, `+`, `-`, `@`, tab or CR with `'`, and quote every cell per RFC 4180. | an exported `=HYPERLINK(...)` cell opens as text | L2, T | [CSV Injection] |
| REL-01 | Every outbound call gets explicit connect and read timeouts, derived from measured downstream latency, with deadlines passed down the chain. | every call site or the shared client sets a timeout | T (L2 planned) | [AWS timeouts]; [SRE cascading]; [Requests] |
| REL-02 | Retry only transient failures (timeout, reset, 429, 503), with capped attempts and exponential backoff with jitter, at exactly one layer. | fake-clock test: a 400 is not retried; the delays grow and vary; the cap surfaces the error | T | [SRE cascading]; [AWS timeouts]; [Azure retry] |
| REL-03 | Never retry a side-effecting call unless it is idempotent or carries an idempotency key, generated once per logical operation, persisted before the first attempt and reused on every retry. | all attempts send the same key | T (L2 planned) | [AWS timeouts]; [Stripe idempotency] |
| REL-04 | "Upstream unreachable" is not "signed out": only a real auth answer yields 401/403; a throw, timeout, 5xx or edge page yields a retryable 503. Writes auto-retry only under REL-03. | a fault-injection test for the 503 and the retry | T | no public source |
| REL-05 | A slow or flaky remote dependency gets a circuit breaker with a tested fallback, and each dependency its own pool. | with one dependency stalled in a test, the others still serve | T | [Fowler breaker]; [Azure breaker]; [Azure bulkhead] |
| REL-10 | Retryable mutating endpoints store key, params and result: replay the result, and reject the same key with different params. | the same key returns the same result; changed params give an error | T | [Stripe idempotency] |
| REL-11 | Webhook handlers verify (SEC-12), enqueue and return 2xx fast; they dedupe by a persisted, unique event id and re-fetch current state rather than trusting order. | the same event twice changes state once; out-of-order delivery ends correct | T | [Stripe webhooks] |
| REL-12 | Jobs run at least once: make handlers idempotent and pass ids, not objects. | running the handler twice gives the same end state | T (L2 planned) | [Sidekiq]; [Outbox] |
| REL-13 | Never write the DB and publish an event or job as two separate steps: use an outbox, or enqueue after commit. | a crash between the steps loses or duplicates nothing | L3r | [Outbox] |
| REL-14 | Before adding polling, a cron or an export, estimate MB per run times runs per month against the egress quota, and CI minutes against the plan. Loops calling a paid or rate-limited service get a budget and stop at the first block. | the estimate is in the PR; a stop-on-block test | L3r | no public source |
| REL-15 | Health checks are local and never fail every instance on a shared dependency. | the check touches no shared downstream | L3r | [AWS health checks] |
| REL-16 | Alerts are deduplicated and rate-limited. Instrument latency, traffic, errors and saturation, and log events to stdout. | the repeat is suppressed; a dashboard or alert exists per signal | L3r | [SRE monitoring]; [12factor logs] |
| REL-17 | Don't make a cache load-bearing: test an empty-cache start, derive the TTL from tolerable staleness, emit hit/miss metrics. | the service runs with a cold cache | T | [AWS caching] |
| UX-21 | List endpoints omit heavy fields and fetch them per item. Placeholders have a fixed size, and only the newest fetch answer is applied. | a payload-size budget in a test | T | no public source |

ASVS ids refer to OWASP ASVS 5.0, which renumbered every requirement; 4.0 ids don't map.

## L2 patterns in `events.toml`

Each pattern aims at precision over recall: a deny that fires on correct code teaches people to ignore it. Each one is a single-line regex with no quantifier inside a repeated group, and each has firing and non-firing samples.

| rule | fires on | stays quiet when |
|---|---|---|
| SEC-01 | a fetch-style method handler (`export async function POST`), a Remix action, a pages-API `handler(req, res)`, or a `"use server"` module | the file calls an auth helper: the engine's defaults and the repo's `[auth] helpers` through `{auth_helpers}`, plus a fixed list (`getServerAuthSession`, `.auth.getUser()`, `requireX()`, `withApiAuthRequired`, a token or webhook-signature check, `CRON_SECRET`, a SvelteKit `!locals.user` check) |
| SEC-01-actions | SvelteKit form actions: `export const actions`, in `+page.server.js` or `+page.server.ts` only. The same export in a Vuex or Redux store elsewhere doesn't fire | the same auth-helper list as SEC-01 |
| SEC-02 | a user, owner or author id read from the body, query, form data or tRPC input | the file compares that id to the session, gates on a role, or is a client component |
| SEC-04 | `...body`, `data: body`, `.values(body)`, `.update(body)`, `findByIdAndUpdate(id, req.body)`, `Object.assign(x, body)`, `**request.data`, or a SQL SET clause built from the request's own keys (``Object.keys(body).map((k) => `${k} = ?`)``, `f"{k} = %s" for k in data`) | the body was assigned from a schema `parse()`; an HMAC `update(body)` is excluded. A SET clause stays quiet when its keys pass an allowlist on the same line (`ALLOWED.includes(k)`, `allowed.has(k)`, `k in ALLOWED`, `if k in ALLOWED`), or when the same variable came from a schema in the 1,500 characters before its use (zod `parse`, `safeParse(...).data`, a tRPC `.input(schema)`, pydantic `model_dump()`). Any other filter, such as `body[k] !== undefined`, still fires |
| SEC-08 | an error's `message` or `stack`, `str(e)` or a traceback put into a response or returned object | the file is a client component |
| SEC-13 | `eval(`, `new Function(`, `shell=True` or `os.system` with a built string, `exec` with an interpolated string, `unserialize(`, `pickle.loads`, `yaml.unsafe_load`, or `yaml.load` with an unsafe loader named on the line (`Loader=yaml.Loader`, `FullLoader`) | the command is a plain literal or an argv list |
| SEC-13-py | in `*.py` only: `yaml.load(` with no loader on its line, including a call wrapped over several lines. js-yaml 4's `load` is safe, so TypeScript and JavaScript files are out of scope | the file names a safe loader (`Loader=yaml.SafeLoader`, `CSafeLoader`, `BaseLoader`), which covers wrapped and nested calls |
| SEC-17 | evidence that rows are serialized: a CSV or TSV content type in a response, header or Blob, an `attachment; filename=...csv` header, a CSV writer library or call, an XLSX writer call, rows joined with commas then newlines, or a `toCsv`-style function. A download link, a file input's accept list or a bare filename doesn't fire (the L1 data-export event still does) | a formula-character set (`[=+\-@...]`), a `startsWith` check, `escapeFormulae: true` or `escape_formulas: true`, or a guard named for formulas (`guardCell`, `neutralizeFormula`, `escapeFormula`). An RFC 4180 helper such as `escapeCsvField` only doubles quotes, so it doesn't count |

## Sources

- ASVS: OWASP Application Security Verification Standard 5.0, https://github.com/OWASP/ASVS/tree/master/5.0/en
- [Next.js]: Next.js, Data Security guide, https://nextjs.org/docs/app/guides/data-security
- [IDOR]: OWASP Insecure Direct Object Reference Prevention Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html
- [LLM10]: OWASP Top 10 for LLM Applications 2025, LLM10 Unbounded Consumption, https://genai.owasp.org/llmrisk/
- [Top10]: OWASP Top 10:2025, A10 Mishandling of Exceptional Conditions, https://top10.owasp.org/2025
- [CSV Injection]: OWASP, CSV Injection, https://owasp.org/www-community/attacks/CSV_Injection
- [Stripe webhooks]: https://docs.stripe.com/webhooks
- [Stripe idempotency]: https://docs.stripe.com/api/idempotent_requests
- [AWS timeouts]: Amazon Builders' Library, Timeouts, retries and backoff with jitter, https://builder.aws.com/content/3EumjoZascWd1oZiEgL8ORlv3qE/timeouts-retries-and-backoff-with-jitter
- [AWS health checks]: Amazon Builders' Library, Implementing health checks, https://builder.aws.com/content/3Ev53O39izHCtWLzp4XU6t8PC1O/implementing-health-checks
- [AWS caching]: Amazon Builders' Library, Caching challenges and strategies, https://builder.aws.com/content/3K9TeXp6strMiJ4vhakpRD7BQWO/caching-challenges-and-strategies
- [SRE cascading]: Google SRE book, Addressing Cascading Failures, https://sre.google/sre-book/addressing-cascading-failures/
- [SRE monitoring]: Google SRE book, Monitoring Distributed Systems, https://sre.google/sre-book/monitoring-distributed-systems/
- [Requests]: Requests quickstart, Timeouts, https://requests.readthedocs.io/en/latest/user/quickstart/
- [Azure retry]: Azure Architecture Center, Retry pattern, https://learn.microsoft.com/en-us/azure/architecture/patterns/retry
- [Azure breaker]: Azure Architecture Center, Circuit Breaker pattern, https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker
- [Azure bulkhead]: Azure Architecture Center, Bulkhead pattern, https://learn.microsoft.com/en-us/azure/architecture/patterns/bulkhead
- [Fowler breaker]: Martin Fowler, CircuitBreaker, https://martinfowler.com/bliki/CircuitBreaker.html
- [Outbox]: microservices.io, Transactional outbox, https://microservices.io/patterns/data/transactional-outbox.html
- [Sidekiq]: Sidekiq wiki, Best Practices, https://github.com/sidekiq/sidekiq/wiki/Best-Practices
- [12factor logs]: The Twelve-Factor App, Logs, https://12factor.net/logs
