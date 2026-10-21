# auth-secrets: spec

The public spec for the `auth-secrets` skill: what it covers, the rule it puts first, how each rule is enforced, and the public source behind each one.

## Scope

The skill covers sign-in, sign-up and logout, sessions and their cookies, password storage and reset, changes of email, phone, password or a linked identity, OAuth callbacks and post-sign-in redirects, tokens, API keys and JWTs, CORS, CSP and the other security headers, and env vars and secrets. It owns 17 rules, SEC-30 to SEC-46. Request handling in general (authz, input, rate limits) belongs to `server-code`, which this skill cites by id.

Files:
- `SKILL.md`: the core rule and the gate rules first (compaction keeps only the start of a skill), then every other rule with its proof.
- `references/email-change.md`, `references/redirects.md` and `references/sessions.md`: worked patterns for the flows models most often get wrong.
- `events.toml`: the events and patterns the practices hook reads.
- Samples for every event and pattern: `tests/setup/practices_samples/auth-secrets.toml`.

## Core rule

When a rule needs more than the user asked for (a pending-change table, a confirmation mail, a redirect validator, server-side revocation), build it by default and say in the final reply what was added and why. Never leave it out with an offer to add it later.

Why it comes first: in the repo's eval, the two commonest auth failures were an email change that took effect before the new address confirmed it, and a `next=` validator that a dot segment or a tab, CR or LF defeated. Most failing runs named the missing confirmation and offered it as an option. So the two gate rules that open the skill name those bugs, and every gate line and deny message is worded "build X and say so".

A no-skill run found a third bug most models make: a remembered session whose only expiry is the cookie's Max-Age, so the server honours a copied cookie forever. So SEC-33 sits third in the gate, with server-side lifetime in its line. The gate order is SEC-37, SEC-39, SEC-33, SEC-36, SEC-41.

The gate lines total 604 characters. The post-compaction digest holds every loaded skill's gate in 2,000 characters, and server-code's takes about 900, so both fit whole.

## Description check

The description is 455 characters, trigger first. It was read against near misses that must not match:
- **A plain profile edit** (display name, bio, avatar): the description names a change of email, phone or password, never "profile" or "account settings".
- **A non-auth cookie** (a theme or sidebar preference): it says "sessions and session cookies", not "cookies". The `session-cookie` event follows the same line: it fires only when the cookie's name, as a literal or a constant, says session, sid, auth, token, jwt, refresh or remember (never a CSRF or XSRF cookie), on a remember-me flag, or on a days-long Max-Age or Expires in a file that names a session. Samples (a theme cookie, a year-long locale cookie, a `sidebar_state` cookie, an `XSRF-TOKEN` cookie) pin that.
- **An env read with no secret** (`PORT`, `NODE_ENV`): the description says "env vars and secrets", and the `secret-env` event needs SECRET, KEY, TOKEN, PASSWORD, PRIVATE or CREDENTIAL in the name, with KEY not preceded by a letter (so `MONKEY_NAME` stays quiet).

## Enforcement levels

| level | what | when |
|---|---|---|
| L0 | The description, written as "Use when" plus concrete triggers | the model's choice |
| L1 | The hook detects an event in `events.toml` by path or by content in the file as it will read after the edit, and denies the edit once, with the event's lines, until the skill is loaded | at the edit |
| L2 | The hook matches a rule's `when` against the new text, and denies once per file and rule unless `unless` or a `practices-allow: <id> <reason>` comment matches the file after the edit | before the edit lands |
| L3s | The commit-time scan of new commits, for every rule whose `at` includes "commit" (the default) | after a commit; deny at push |
| T | A test the skill tells the agent to write: the rule's proof | in the repo |
| L3r | The PR-ready reviewer's checklist | at PR ready |
| L4 | The gate lines, re-injected after compaction | after compaction |

Every rule gets L0, L1 and L4 through the skill. The table below lists the further levels.

`at` is an optional `[[rule]]` field: a list holding "edit" and/or "commit", defaulting to both. So a rule without `at` runs at the edit (L2) and at commit: L3s scans each new commit with it and scans again at push, where a new finding denies the push once. Every L2 rule in the table below has L3s that way, though the levels column names it only on SEC-40 and SEC-41, where commit time is the main net. L3r, the review before a PR goes ready, gets this skill's gate lines whenever the branch touched one of its events. SEC-41-env sets `at = ["commit"]`, since writing a key to a local `.env` is how env works and only committing it is the bug. SEC-41's `practices-allow` covers only the line it sits on, so one allowed test fixture can't hide a real key elsewhere in the file. Both need the engine change that ships with this skill.

## Per-repo layer

- `.claude/practices/auth-secrets.md`: prose repo rules the skill reads first, such as "auth is Supabase with secure email change on" or "the session store is `lib/session.ts`". They win over the defaults.
- `.claude/practices/config.toml`: `[[disable]]` with a `rule` and a non-empty `reason` turns one event or rule off.

## Rules

| id | rule | proof | levels | public source |
|---|---|---|---|---|
| SEC-30 | Hash passwords with Argon2id (19 MiB, t=2, p=1) or bcrypt cost 10 or more, or leave them to the auth provider. Never a fast hash. | the stored value carries an algorithm marker and a salt | L2, T | [Password Storage] |
| SEC-31 | Passwords: at least 15 characters when the password is the only factor (8 only when it is one factor of MFA), as SP 800-63B-4 requires, up to at least 64, no composition rules, paste allowed, a common-password check; no seeded default accounts. | a policy test; no seeded admin credentials in migrations | T | [NIST 800-63B]; ASVS V6 |
| SEC-32 | Sign-in, sign-up and reset answer "no such account" and "wrong password" with one message and similar timing. | both responses match in status and body | T | [Authentication]; [Forgot Password] |
| SEC-33 | Rotate the session at sign-in; logout revokes server-side; removing a user or their access ends their sessions; long or remembered sessions expire on the server, with the expiry and idle limit stored on the session record (a cookie's Max-Age or Expires only asks the browser); state how long an issued JWT outlives removal. Gate line: "Build sessions that rotate at sign-in, end at logout and expire server-side, not by Max-Age." | a remembered cookie replayed past its lifetime gets 401, and so does a saved cookie after logout | T (L1: the `session-cookie` event fires on long-lived session cookies) | [Session Management]; ASVS V7 |
| SEC-34 | Session cookies are Secure, HttpOnly, SameSite Lax or Strict, `__Host-` prefixed; tokens never in URLs. | a response-header test | L2, T | [Session Management]; [MDN Set-Cookie] |
| SEC-35 | JWTs: verify the signature with a key from a trusted source, allowlist algorithms, check `exp`, `nbf`, `iss` and `aud`. | `alg: none`, tampered and expired tokens get 401 | L2 (SEC-35, SEC-35-alg, SEC-35-off), T | [RFC 8725]; ASVS V9 |
| SEC-36 | Reset, invite, verification and OTP tokens come from a CSPRNG at 128 bits or more, are stored hashed, expire soon and work once. | a reused or expired token is rejected | L2, T | [Forgot Password]; ASVS V6 |
| SEC-37 | An email or phone change is pending until a link or code sent to the new address is followed (a random single-use token, hashed and short-lived), with a fresh sign-in to start, a notice with a cancel link to the old address the actor can't turn off, a rate limit and an audit line. Password and recovery changes need the fresh sign-in too, and a password change or reset voids any open change. | the address is unchanged until the mailed link is followed; a forged, reused or expired link changes nothing; a change without recent auth fails; a race test | L2, T | [Authentication] (changing a registered email) |
| SEC-38 | Link a second identity only with proof of control of both sides. | a link attempt with only a claimed id fails | T | [RFC 9700]; ASVS V10 |
| SEC-39 | A request-supplied redirect target must be same-origin: refuse non-strings, backslashes and control characters, parse against the configured origin, compare origins, store the validated path (it starts with exactly one `/`) and add the origin only at the redirect, never a `//` string. External and OAuth targets use an exact-match allowlist. | external, `//`, backslash, dot-segment and tab/CR/LF values stay on the origin; a same-origin path with a query survives; checking a result again gives the same answer | L2, T | [Redirects]; [URL Standard]; [RFC 9700] |
| SEC-40 | Privileged keys stay server-only: never in client code, a public-prefixed env var, the bundle, a URL or a prompt. Code using a bypass key does its own authz. | build output and client files hold no key value or service-role claim | L2 (SEC-40, SEC-40-client), L3s, T (bundle grep) | [Secrets Management] |
| SEC-41 | Secrets live in env or a secret manager, injected per process and never exported from shell startup files, `.env*` is gitignored, the staged diff is scanned before every commit, and no user token goes into an agent-run command. | a secret scan of committed content is clean; no `.env*` is tracked | L2 (SEC-41, SEC-41-fallback), L3s (SEC-41, SEC-41-env), T | [Secrets Management]; vendor key formats below |
| SEC-42 | Vetted crypto only: AES-GCM, no ECB, no MD5 or SHA-1 for security, no custom schemes. | a grep finds none | L2, T | [Cryptographic Storage]; ASVS V11 |
| SEC-43 | CORS uses fixed or allowlisted origins, never a wildcard or reflection with credentials. CSP and egress allowlists name exact hosts plus redirect targets, never `*.domain`. | a foreign-origin request is refused; no `*.` entries | L2 (SEC-43, SEC-43-csp), T | [Fetch CORS]; [CSP] |
| SEC-44 | Send HSTS, CSP, nosniff, frame-ancestors and a referrer policy. | a header test on a live response | T | [HTTP Headers]; ASVS V3 |
| SEC-45 | Dev holds no live credentials that can send or post externally; the guard lives in code. | a dev probe of an external send gets 503 | L3r | no public source |
| SEC-46 | Log auth outcomes and failed authorization with encoded fields; logs and alerts carry ids and labels, never secrets, personal data or content. | a failed-login test writes one clean line; alert text holds no payload | L3r | [Logging]; ASVS V16 |

ASVS refers to OWASP ASVS 5.0, cited by chapter here (V3 Web Frontend Security, V6 Authentication, V7 Session Management, V9 Self-contained Tokens, V10 OAuth and OIDC, V11 Cryptography, V16 Security Logging). Requirement-level ids are still to be checked against the 5.0 text.

## L2 patterns in `events.toml`

Each pattern aims at precision over recall. Each is a regex with no quantifier inside a repeated group, and each has firing and non-firing samples.

| rule | fires on | stays quiet when |
|---|---|---|
| SEC-30 | MD5, SHA-1 or SHA-2 on the same line as `password`, `passwd` or `pwd` | the line names bcrypt, Argon2, scrypt or PBKDF2 (a pre-hash), is a comment, or names a reset token (`passwordResetToken` has no word break); the file queries Pwned Passwords (`pwnedpasswords`, `hibp`), whose SHA-1 range check stores nothing |
| SEC-34 | a cookie set (`cookies().set`, `res.cookie`, `set_cookie`, `setCookie(c, ...)`, `serialize`, a `Set-Cookie` header string) whose name says session, sid, auth, token, jwt, refresh or remember; never a CSRF or XSRF name, since a double-submit cookie must stay readable | the file names HttpOnly, Secure (or a `__Host-`/`__Secure-` name) and SameSite, or passes a lowercase options object as an argument (`sessionCookieOptions`, `...cookieOpts`; an imported `CookieOptions` type doesn't count), and sets neither `secure` to false nor SameSite to None. An explicit `httpOnly: false` on a session-named cookie, on its line or inside its set call, fires even then; on a CSRF or XSRF cookie in the same file it doesn't |
| SEC-35 | `jwt.decode(`, jose's `decodeJwt(`, or jwt-decode's `jwtDecode(` or `jwt_decode(` (a TS generic allowed) in JS or TS | the file also verifies (`jwt.verify`, `jwtVerify`), or is a client component |
| SEC-35-alg | `jwt.verify(` | the file passes `algorithms:` |
| SEC-35-off | `verify_signature: False`, `ignoreExpiration: true`, `none` in an algorithms list, `jwt.decode(..., verify=False)` | never (a test fixture uses `practices-allow`) |
| SEC-36 | `Math.random`, `random.*`, `crypto.randomUUID` or a bare imported `randomUUID`, a UUID v4 or `Date.now().toString` in the value given to a name that says token, nonce, secret, salt, OTP or code (`code`, `smsCode`, `confirmationCode`): an assignment, an object key or a call's argument, up to the next statement or key | the generator is a CSPRNG (`randomBytes`, `secrets`, `SystemRandom`); it feeds another name on the line (`{ id: crypto.randomUUID(), tokens }`); or a UUID makes a CSP nonce (Next's documented `Buffer.from(crypto.randomUUID())`, a CSPRNG value) |
| SEC-37 | a direct write of `email` or `phone`: a Prisma `update` with `data: { email }`, a Drizzle `.set({ email })`, a Knex or Sequelize `.update({ email })`, a Mongo `$set`, a SQL `UPDATE ... SET email =`, `request.user.email =`, `current_user.update(email:)`, a call of `updateEmail(` (Firebase switches at once; a definition doesn't fire) | the file names a pending-change table or flow (`pending_email`, `email_change_requests`, `EmailChangeRequest`, `unconfirmed_email`, `verifyBeforeUpdateEmail`), but not a form handler like `handleEmailChange`; a boolean value (a notification toggle), an `update` whose `where` names the email, `emailVerified`, an insert at sign-up, and an `email` after a SQL UPDATE's WHERE (a later `email=` argument in semicolon-free Python) don't fire |
| SEC-39 | a redirect (`redirect`, `res.redirect`, `NextResponse.redirect`, `router.push`, `location.assign`) whose argument reads `next`, `returnTo`, `callbackUrl` and the like (from the query, `searchParams?.`, `req.body`, or Rails' `params[:next]` and `params.fetch(:next)`, with or without parentheses on `redirect_to`), or a redirect to a variable of that name in a file that reads such a param, by name or destructured (`const { next } = await searchParams`, `router.query`, `req.body`), Rails' paren-less `redirect_to return_to` included. The variable counts as the whole argument, after an identifier and `+` (`res.redirect(origin + next)`), after a string with no `?` or `#` and `+` (`redirect("/" + next)`, `redirect("/" + next + "?x=1")`), in a template whose text before it has no `?` or `#` (``NextResponse.redirect(`${origin}${next}`)``), as the branch of a typeof guard (`router.push(typeof callbackUrl === "string" ? callbackUrl : "/")`), or before ` as ` or a non-null `!` (`router.push(next as string)`, `redirect(next!)`); or a weak check written inside the redirect call, whatever the variable's name: a string method or a one-argument call before a ternary whose branch is the bare checked name or a param read (`router.push(next.startsWith("/") ? next : "/")`, `redirect(isLocalUrl(next) ? next : "/")`, `router.push(!isLocalUrl(next) ? "/" : next)`, Python's `redirect(nxt if nxt.startswith("/") else "/")`). `String`, Python's `str`, `decodeURI`, `decodeURIComponent`, `encodeURI`, `new URL` and Python's `unquote` and `unquote_plus` around the value validate nothing, so they still fire (`redirect(unquote(request.args.get("next")))`) | a read or a variable that lands only in the query of a fixed path (`redirect("/login?next=" + encodeURIComponent(...))`, `redirect("/login?next=" + next)`, ``redirect(`/login?next=${next}`)``, Rails' `redirect_to "/login?return_to=#{params[:return_to]}"`), which can't leave the origin; another variable in the path of a file that reads `next` (`redirect("/" + locale + "/home")`); `encodeURIComponent` alone or after a string literal (`res.redirect("/u/" + encodeURIComponent(req.query.next))`), since it never outputs `/`, `\` or `:` (after an origin, as in `APP_ORIGIN + encodeURIComponent(req.query.next)`, it still fires: it keeps `.`, so `.evil.com` extends the host); the value is wrapped in, or the redirected variable assigned from, any other call, whatever the validator's name (`redirect(check(raw))`, `const next = check(raw)`, `const next = localPath(raw) ?? "/"`), except the weak check itself: a call that a ternary or `&&` follows (`raw.startsWith("/") && !raw.startsWith("//") ? raw : "/"`), a getter chain (`useSearchParams().get(...)`, `new URLSearchParams(...).get(...)`), `Array.isArray`, a string method (`trim`, `slice`, `split`, `substr`, `normalize`, `replace`, `toLowerCase`, Python's `strip`), or Python's `unquote` and `unquote_plus`, all of which hand back the raw value and still fire, and `indexOf` on the value, whose comparison sits between the call and the ternary (`raw.indexOf("//") === -1 ? raw : "/"`), which still fires too; a validated variable stays quiet in every shape above (`const next = localPath(raw)`, then ``NextResponse.redirect(`${origin}${next}`)`` or `redirect(next ?? "/")`); the file names a validator (`safeRedirect`, `isSafeUrl`, `url_has_allowed_host_and_scheme`), compares the `.origin` of a value parsed against a base (`new URL(value, origin)`), or never reads such a param; an exact-match allowlist, where the value is the argument of `.includes`, `.has` or `.indexOf` (`router.push(ALLOWED.includes(next) ? next : "/")`, `const next = ALLOWED.has(raw) ? raw : "/"`, `const next = ALLOWED.indexOf(raw) !== -1 ? raw : "/"`); a ternary inside the call whose branch only mentions the checked value (``router.push(isSupported(locale) ? `/${locale}/home` : "/home")``). An Origin header check (`req.headers.origin`, `new URL(origin).origin`) doesn't count, and neither do names of the weak prefix check (`isRelativeUrl`, `isLocalUrl`, `isSafePath`) |
| SEC-40 | a `NEXT_PUBLIC_`, `VITE_`, `PUBLIC_`, `EXPO_PUBLIC_`, `REACT_APP_`, `NUXT_PUBLIC_` or `GATSBY_` name holding SECRET, SERVICE_ROLE, PRIVATE_KEY, a final PASSWORD, a vendor name (OpenAI, Anthropic, Resend, SendGrid, Mailgun, Postmark, Twilio) before KEY, TOKEN or SECRET, or `DATABASE_URL` | an anon or publishable key (`..._ANON_KEY`, `..._PUBLISHABLE_KEY`); a setting that only mentions a vendor or a word (`NEXT_PUBLIC_OTP_RESEND_SECONDS`, `NEXT_PUBLIC_PRIVATE_BETA`, `NEXT_PUBLIC_PASSWORD_MIN_LENGTH`) |
| SEC-40-client | a service-role name, a `firebase-admin` or `stripe` import, or a non-public secret env read | the file has no `"use client"` directive in its first 500 characters |
| SEC-41 | key shapes from the vendors' published formats: an AWS access key id (`AKIA` or `ASIA` and 16 uppercase letters or digits), a GitHub token (`ghp_`, `gho_`, `ghu_`, `ghs_` or `ghr_` and 36 or more letters or digits, or `github_pat_` and about 82), a Slack token (`xox` plus a type letter, a dash and digit groups), an OpenAI-style secret (`sk-` with the `T3BlbkFJ` marker, a long `sk-proj-`, `sk-svcacct-` or `sk-admin-` key, or an `sk-ant-` key), a Stripe secret or restricted key (`sk_` or `rk_`, `live_` or `test_`, 20 or more letters or digits), and a PEM header that opens a private-key block | `practices-allow: SEC-41` on the same line; placeholders padded with `XXXX` and AWS ids ending in `EXAMPLE`; a local `.env` (not in its paths) |
| SEC-41-env | at commit only: a `.env`, `.env.local` or `.env.<stage>` line whose secret-named variable holds a value of 8 or more characters | the value is empty; `.env.example` is not in its paths |
| SEC-41-fallback | a secret env read with a literal fallback (`process.env.SESSION_SECRET ?? "dev-secret"`, `os.getenv("SECRET_KEY", "...")`) | the fallback is absent or the variable names no secret |
| SEC-42 | `createCipher(`, `createDecipher(`, an ECB mode, `Cipher.getInstance("AES")`, DES, RC4, RC2 or Blowfish | GCM, and MD5 for a non-security use (an ETag) |
| SEC-43 | `Access-Control-Allow-Origin: *`, `origin: "*"` or `origin: true`, `allow_origins=["*"]`, Django's allow-all setting, a reflected `req.headers.origin`, an origin callback that always allows, or flask-cors credentials with no `origins=` | the file never turns on credentials, or the origin is a fixed list |
| SEC-43-csp | a `*` or `*.host` source in `default-src`, `script-src`, `connect-src`, `frame-src`, `child-src`, `worker-src`, `object-src` or `form-action`, as a header string or a helmet directive array | the wildcard is in `img-src`, `media-src`, `font-src` or `style-src` |

The `XXXX` and `EXAMPLE` exclusions in SEC-41 have no sample, because any string that would test them is key-shaped by design.

Known gap: SEC-34 misses `httpOnly: false` in a separate options object (`const cookieOptions = { httpOnly: false, ... }` later passed to a session cookie), since that line names no session and sits outside the set call. Inside the call, the window spans one nested call (`res.cookie("session", await createSession(id), { httpOnly: false })` fires). The response-header test (T) is the net for the rest.

## Dropped to T, and why

- **SEC-31** (password policy): a length check has too many spellings (`min(8)`, `minLength`, `len(p) <`) to tell a weak policy from a strong one.
- **SEC-32** (one answer for both failures): the bug is two branches with different messages, which a line regex can't compare.
- **SEC-33** (rotation, revocation and server-side lifetime): the bug is a missing call (`regenerate`, a row delete) or a missing expiry check on the session record, and absence across a flow isn't a pattern. The `session-cookie` event covers it at L1 instead: it fires on a remember-me flag and on a days-long cookie lifetime, and its lines name the server-side expiry.
- **SEC-38** (identity linking): no stable call shape across providers.
- **SEC-42's MD5 and SHA-1 "for security"**: those hashes have honest uses (ETags, cache keys, git ids), so only the password case ships, as SEC-30.
- **SEC-44** (security headers): the bug is a header that is absent from the response, which only a live test sees.
- **SEC-41's token-in-a-Bash-command check**: deferred with the Bash matcher; L1 and L2 don't judge Bash.
- **SEC-45 and SEC-46** stay at L3r: the evidence is a guard's absence or a log line's content.

## Sources

- ASVS: OWASP Application Security Verification Standard 5.0, https://github.com/OWASP/ASVS/tree/master/5.0/en
- [Password Storage]: OWASP Password Storage Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- [Authentication]: OWASP Authentication Cheat Sheet (generic error messages; changing a user's registered email address), https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- [Forgot Password]: OWASP Forgot Password Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html
- [Session Management]: OWASP Session Management Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- [Redirects]: OWASP Unvalidated Redirects and Forwards Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html
- [Secrets Management]: OWASP Secrets Management Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
- [Cryptographic Storage]: OWASP Cryptographic Storage Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html
- [HTTP Headers]: OWASP HTTP Security Response Headers Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html
- [CSP]: OWASP Content Security Policy Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html
- [Logging]: OWASP Logging Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- [NIST 800-63B]: NIST SP 800-63B, Digital Identity Guidelines: Authentication and Lifecycle Management, https://pages.nist.gov/800-63-4/sp800-63b.html
- [RFC 8725]: JSON Web Token Best Current Practices, https://www.rfc-editor.org/rfc/rfc8725
- [RFC 9700]: OAuth 2.0 Security Best Current Practice, https://www.rfc-editor.org/rfc/rfc9700
- [URL Standard]: WHATWG URL Standard (tab and newline removal, backslash in special URLs, dot segments), https://url.spec.whatwg.org/
- [Fetch CORS]: WHATWG Fetch Standard, CORS protocol, https://fetch.spec.whatwg.org/#http-cors-protocol
- [MDN Set-Cookie]: MDN, Set-Cookie (cookie prefixes), https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie
- Vendor key formats: AWS IAM identifiers (access key id prefixes), https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html; GitHub, Behind GitHub's new authentication token formats, https://github.blog/engineering/platform-security/behind-githubs-new-authentication-token-formats/; Slack, Token types, https://api.slack.com/concepts/token-types; Stripe, API keys, https://docs.stripe.com/keys; RFC 7468, Textual Encodings of PKIX, PKCS and CMS Structures, https://www.rfc-editor.org/rfc/rfc7468
