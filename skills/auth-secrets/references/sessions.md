# Sessions (SEC-33, SEC-34)

A session is only as strong as its revocation. A cookie that still works after logout, or after an admin removed the user, means a stolen cookie works for as long as the attacker likes. Build rotation, server-side revocation and the cookie flags below into any session code, without being asked, and say so in your reply.

## A server-side session

```ts
// session.ts
import { createHash, randomBytes } from "node:crypto";

const COOKIE = "__Host-session"; // __Host- needs Secure, Path=/ and no Domain
const IDLE_SECONDS = 30 * 60;
const ABSOLUTE_SECONDS = 7 * 24 * 60 * 60;

export interface SessionRow {
  idHash: string;
  userId: string;
  createdAt: number; // epoch seconds
  lastSeenAt: number;
  authenticatedAt: number; // the last fresh sign-in, for SEC-37's re-auth check
}

export interface SessionStore {
  create(row: SessionRow): Promise<void>;
  get(idHash: string): Promise<SessionRow | null>;
  touch(idHash: string, at: number): Promise<void>;
  delete(idHash: string): Promise<void>;
  deleteAllForUser(userId: string, exceptIdHash?: string): Promise<void>;
}

// The store keeps only a hash, so a leaked table holds no live session ids.
const hashId = (id: string) => createHash("sha256").update(id).digest("hex");
const now = () => Math.floor(Date.now() / 1000);

function cookie(value: string, maxAge: number): string {
  return `${COOKIE}=${value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=${maxAge}`;
}

/** At sign-in: a fresh id every time, and the pre-sign-in id dies (session fixation). */
export async function startSession(store: SessionStore, userId: string, previousId?: string) {
  if (previousId) await store.delete(hashId(previousId));
  const id = randomBytes(32).toString("base64url"); // 256 bits from a CSPRNG
  const t = now();
  await store.create({ idHash: hashId(id), userId, createdAt: t, lastSeenAt: t, authenticatedAt: t });
  return { setCookie: cookie(id, ABSOLUTE_SECONDS) };
}

/** On every request: expiry is decided here, never by the cookie's Max-Age. */
export async function readSession(store: SessionStore, id: string | undefined) {
  if (!id) return null;
  const row = await store.get(hashId(id));
  if (!row) return null;
  const t = now();
  if (t - row.lastSeenAt > IDLE_SECONDS || t - row.createdAt > ABSOLUTE_SECONDS) {
    await store.delete(row.idHash);
    return null;
  }
  await store.touch(row.idHash, t);
  return row;
}

/** Logout deletes the row, then clears the cookie with the same attributes. */
export async function endSession(store: SessionStore, id: string) {
  await store.delete(hashId(id));
  return { setCookie: cookie("", 0) };
}

/** Password change, recovery change, role removal or account removal. */
export async function endOtherSessions(store: SessionStore, userId: string, keepId?: string) {
  await store.deleteAllForUser(userId, keepId ? hashId(keepId) : undefined);
}
```

## Rules of use

- **Rotate at every privilege change:** sign-in, sign-up's first session, MFA completion, and switching into an admin or impersonation mode.
- **Revoke on removal:** when an admin removes a user, a role or an org membership, call `endOtherSessions` for that user in the same transaction.
- **Cookie flags:** `Secure`, `HttpOnly` and `SameSite=Lax` always; `Strict` for an admin console. Use the `__Host-` prefix when the app owns its host; if a parent domain must share the cookie, use `__Secure-` with an explicit `Domain`, and say why in your reply.
- **No tokens in URLs:** session and bearer tokens travel in a cookie or an `Authorization` header, never a query string, where logs, history and `Referer` keep them.
- **Long sessions:** a "remember me" session still has a server-side absolute expiry (30 days at most) and still dies at logout. Re-ask for the password before sensitive actions (SEC-37) by checking `authenticatedAt`.

## Stateless tokens (JWT)

A signed token can't be revoked by deleting a row, so:
- keep access tokens to 5 to 15 minutes, with `exp` checked on every request (SEC-35);
- pair them with a refresh token that is stored hashed server-side, rotated on each use and deleted at logout, so logout ends the session within one access-token lifetime;
- for instant revocation, keep a `sessionVersion` on the user, put it in the token, and compare it on each request;
- say in your reply how long a token outlives a logout or a removal.

## Frameworks

- **express-session:** `req.session.regenerate()` at sign-in, `req.session.destroy()` at logout, a shared store (not the default memory store), and `cookie: { secure: true, httpOnly: true, sameSite: "lax" }`.
- **Django:** `login()` rotates the session key, and `logout()` flushes it. Set `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY` and `SESSION_COOKIE_SAMESITE`. `update_session_auth_hash()` after a password change keeps only the current session.
- **Auth.js:** the database session strategy revokes at logout; the JWT strategy can't, so state the window. Cookie flags follow its secure defaults when the app runs on https.
- **Encrypted-cookie sessions** (iron-session and similar): add the `sessionVersion` check above, since deleting a cookie on one device revokes nothing.

## Prove it

```ts
test("a saved cookie replayed after logout gets 401", async () => {
  const cookie = await signIn(client, "ada@example.com", "a long passphrase");
  await client.post("/logout", { headers: { cookie } });
  const res = await client.get("/api/me", { headers: { cookie } });
  expect(res.status).toBe(401);
});

test("the session id changes at sign-in", async () => {
  const before = await anonymousSessionCookie(client);
  const after = await signIn(client, "ada@example.com", "a long passphrase", { cookie: before });
  expect(after).not.toBe(before);
});

test("the session cookie carries its flags", async () => {
  const res = await signInResponse(client);
  expect(res.headers.get("set-cookie")).toMatch(/^__Host-session=[^;]+; Path=\/; Secure; HttpOnly; SameSite=Lax/);
});
```
