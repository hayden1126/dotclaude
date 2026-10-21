---
name: auth-secrets
description: Use when writing or changing sign-in, sign-up or logout, sessions and session cookies, password storage or reset, a change of email, phone or password, an OAuth callback or a post-login redirect (next, returnTo, callbackUrl), tokens, API keys or JWTs, CORS, CSP or other security headers, or env vars and secrets. Applies to hand-rolled auth and to Auth.js, Clerk, Supabase Auth, Lucia, Passport, Devise, Django auth and similar, however small the change.
---

# Auth and secrets

Auth bugs pass every demo. An email change that skips confirmation, or a redirect check that a tab character defeats, works fine until someone takes over an account with it. These rules make the safe flow the default.

## Core rule: build the safe flow, then say so

When a rule below needs more than the user asked for (a pending-change table, a confirmation mail, a redirect validator, server-side session revocation), build it in the same change, by default. In your final reply, list what you added and why, one line each. Never leave it out with an offer to add it later, and never stop to ask permission for it.

Example reply line: "The email change is now pending: the new address gets a single-use link (stored hashed, valid 30 minutes), the old address gets a notice, and the account switches only when the link is followed."

If you catch yourself writing one of these, stop and build the safe flow instead:
- "You may want to confirm the new address" or "consider validating the redirect".
- "For simplicity, the email updates immediately."
- "In production you'd also want to..."
- "It's only a demo" or "the auth library handles it" (check that it does).

If `.claude/practices/auth-secrets.md` exists in the repo, read it first. Its repo rules (the auth library, the mailer, the session store) win over the defaults here.

## Gate rules: check every one before you finish

Each rule names its proof: the test that shows it holds. Write that test where the repo has a test setup; otherwise list it in your reply as the check to run.

- **SEC-37: Make an email or phone change pending until the new address confirms it.** Never write the new address to the account directly. Store a pending change with a random single-use token (32 bytes from a CSPRNG), kept as a hash and valid for 30 minutes or less, and send the link or code to the NEW address. Switch the address only when that link is followed, in one step that consumes the token. Starting the change needs a fresh sign-in or the current password. Also send the old address a notice with a link that cancels the change (a notice the person making the change can't turn off), rate-limit the request (server-code SEC-07) and write an audit line. A password or recovery-method change needs the same fresh sign-in and ends the user's other sessions, and it or a password reset voids any open change. Proof: the address is unchanged until the mailed link is followed; a forged, reused or expired link changes nothing; a change without a fresh sign-in is refused; and two parallel confirms of one link switch the address once. Pattern: [references/email-change.md](references/email-change.md).
- **SEC-39: Keep every request-supplied redirect on your own origin.** For a `next`, `returnTo`, `redirect` or `callbackUrl` value: refuse anything that isn't a single string, refuse a backslash or any control character (tab, CR and LF among them) before parsing, then parse it against the app's configured origin and compare the parsed origin with it. Store the validated path, which starts with exactly one `/`, never the absolute URL, and add the origin only at the redirect, so a stored value checks again to the same answer. Redirect to that absolute URL, never to a string that starts with `//`. External and OAuth targets (`redirect_uri`) use an exact-match allowlist. Proof: external, `//`, backslash, dot-segment (`/.//host`) and tab/CR/LF values all land on the app's origin, a same-origin path with its query survives, and checking a result again gives the same answer. Pattern: [references/redirects.md](references/redirects.md).
- **SEC-33: Rotate the session at sign-in, revoke it at logout, and expire long or remembered sessions on the server.** Issue a new session id at sign-in and at every privilege change. Logout deletes the session server-side, not only the cookie, and removing a user or their access ends their sessions. Store each session's expiry and idle limit with its record and refuse the session once either passes: a cookie's Max-Age or Expires only asks the browser, and a copied cookie ignores it. With stateless JWTs, keep access tokens short-lived and say in your reply how long one outlives a logout or a removal. Proof: a remembered cookie replayed past its lifetime gets 401, and so does a saved cookie after logout. Pattern: [references/sessions.md](references/sessions.md).
- **SEC-36: Make reset, invite, verification, magic-link and OTP tokens unguessable and single-use.** Generate them with a CSPRNG at 128 bits or more (`crypto.randomBytes(32)`, `secrets.token_urlsafe(32)`), never `Math.random`, `random`, a timestamp or a UUID. Store only a hash, expire them within an hour (an OTP code within 10 minutes, with capped attempts) and consume them on first use. Proof: a reused or expired token is rejected.
- **SEC-41: Keep secrets out of source.** Read them from env or a secret manager, injected into each process that needs them (the host's env settings or the manager's run command), never exported from a shell startup file, where every command inherits them. Keep `.env*` gitignored (commit only a `.env.example` with empty values), and never write a key-shaped literal in code, config, docs or tests. Scan the staged diff before every commit. Never put a user's token in a command you run. If a real key reached a file, move it to env and tell the user to rotate it. Proof: a secret scan of the committed content is clean, and no `.env*` file is tracked.
## When a practices hook stops an edit

A hook may deny an edit once and name a rule id. Fix the code. If the match is a false positive, keep the code and add a comment in the file: `practices-allow: <id> <reason>`. For example, a support tool that sets an email on an audited ticket gets `// practices-allow: SEC-37 admin override, audited`. Never use the comment to skip a safeguard the rule asks for.

SEC-41 (a key-shaped value) is stricter: its comment covers only the line it sits on, and a real key never gets one. Move the key to env and tell the user to rotate it. A fake key in a test fixture gets `// practices-allow: SEC-41 fake test key` at the end of its own line.

## Passwords and sign-in

- **SEC-30: Hash passwords with Argon2id (19 MiB memory, 2 iterations, parallelism 1) or bcrypt at cost 10 or more**, or leave them to the auth provider. Never MD5, SHA-1, SHA-256 or any other fast hash, salted or not. Proof: each stored value carries an algorithm marker and a salt (`$argon2id$`, `$2b$`).
- **SEC-31: Require at least 15 characters for a password that is the only factor (8 only when it is one factor of MFA), and accept up to at least 64** (NIST SP 800-63B-4), with no composition rules, paste allowed, and a check against a list of common passwords (the top 3,000 or more). Seed no default accounts: dev auto-login and seeded owners stay dev-only and gitignored. Proof: a policy test, and no seeded admin credentials in migrations.
- **SEC-32: Answer "no such account" and "wrong password" the same way** at sign-in, sign-up and reset: one message, one status and similar timing (verify against a dummy hash when the user is missing). Reset says "if that address has an account, we sent a link". Proof: both responses match in status and body.
- Sign-in, sign-up, reset and OTP endpoints get server-code's rate limit (SEC-07).

## Sessions, cookies and tokens

- **SEC-34: Set session cookies with `Secure`, `HttpOnly`, `SameSite=Lax` (or `Strict`) and the `__Host-` prefix**, which needs `Path=/` and no `Domain`. Never put a session or bearer token in a URL. Proof: a response-header test.
- **SEC-35: Verify every JWT before you trust a claim.** Check the signature with a key from a trusted source (your secret or the issuer's JWKS), allowlist the algorithms, and check `exp`, `nbf`, `iss` and `aud`. A `decode` call checks nothing. Proof: `alg: none`, tampered and expired tokens get 401.
- **SEC-38: Link a second identity only with proof of control of both sides**: a one-time code or a fresh sign-in on each, never a self-asserted id or an unverified email from a provider. Proof: a link attempt with only a claimed id fails.

## Keys, secrets and crypto

- **SEC-40: Keep privileged keys server-only** (a service-role key, a secret API key, an admin SDK): never in client code, a `NEXT_PUBLIC_`, `VITE_` or `PUBLIC_` variable, the built bundle, a URL or a system prompt. Code that uses a key that bypasses row-level security does its own authorization (server-code SEC-01). Proof: a grep of the build output and client files finds no key value and no service-role claim.
- **SEC-42: Use vetted crypto only**: AES-GCM or ChaCha20-Poly1305 with a fresh nonce per message, or a library such as libsodium. No ECB, no `createCipher`, no DES or RC4, no MD5 or SHA-1 for security, no home-made schemes. Proof: a grep finds none.
- **SEC-45: Keep live credentials that can send or post externally out of dev.** Enforce it in code (drop or stub the keys when the database URL is local), not in a README note. Proof: a dev probe of an external send gets 503.

## Browser policy

- **SEC-43: Allow CORS only for fixed or allowlisted origins**, never `*` or a reflected `Origin` with credentials. CSP and egress allowlists name exact hosts plus their redirect targets, never `*.domain`. Proof: a foreign-origin request is refused, and no allowlist holds `*.`.
- **SEC-44: Send the security headers**: `Strict-Transport-Security`, a `Content-Security-Policy` with `frame-ancestors`, `X-Content-Type-Options: nosniff` and a `Referrer-Policy`. Proof: a header test on a live response.

## Logging

- **SEC-46: Log auth outcomes and failed authorization** (sign-in success and failure, lockouts, email, password and MFA changes) as structured lines with encoded fields. Logs and alerts carry ids and labels, never passwords, tokens, secrets, personal data or content. Proof: a failed-login test writes one clean line, and alert text holds no payload.
