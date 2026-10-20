# Changing an email or phone (SEC-37)

The email on an account is its recovery path: whoever controls it can reset the password. Each step of the flow below stops a different failure:
- **The fresh sign-in** stops someone holding a stolen session cookie or a borrowed laptop. They control the address they type, so a confirmation link alone wouldn't stop them.
- **The confirmation link** to the new address stops a typo, or an address the requester doesn't control, from becoming the account's recovery path.
- **The notice to the old address**, with a link that cancels the change, lets the owner catch a change they didn't make.

Build the flow whenever code changes an email or phone, without being asked, and say so in your reply.

## The flow

1. **Request**: the signed-in user, after a fresh sign-in or with the current password, asks for the change. Nothing on the account changes yet.
2. **Pending row**: store the new address with a random confirm token and a random cancel token, each kept as a hash, valid for 30 minutes, usable once. A new request replaces any open one.
3. **Two mails**: a confirmation link to the NEW address, and a notice with a cancel link to the OLD address. The notice is a security mail, so no notification setting turns it off.
4. **Confirm**: following the link consumes the token and switches the address in one transaction.
5. **After**: a second notice to the old address, an audit line at each step.

A password change or reset deletes the user's open requests (see "Passwords and recovery methods").

## Schema

```sql
CREATE TABLE email_change_requests (
  id                 uuid PRIMARY KEY,
  user_id            uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  new_email          text NOT NULL,
  token_hash         text NOT NULL UNIQUE,
  cancel_token_hash  text NOT NULL UNIQUE,
  expires_at         timestamptz NOT NULL,
  used_at            timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now()
);
```

`users.email` keeps its unique index, which settles the race where two accounts confirm the same address.

## Request

```ts
// email-change.ts
import { createHash, randomBytes, randomUUID } from "node:crypto";

const TOKEN_MINUTES = 30;
const FRESH_SIGN_IN_MINUTES = 10;

// A 256-bit random token needs no slow hash: SHA-256 makes a leaked table useless.
export const sha256 = (value: string) => createHash("sha256").update(value).digest("hex");
const newToken = () => randomBytes(32).toString("base64url"); // SEC-36: a CSPRNG, 256 bits

export async function requestEmailChange(session: Session, input: unknown, ip: string) {
  const user = await requireUser(session); // server-code SEC-01
  if (minutesSince(session.authenticatedAt) > FRESH_SIGN_IN_MINUTES) {
    throw new HttpError(403, "reauthenticate"); // the client asks for the password again
  }
  const newEmail = parseEmail(input); // strict schema: a string, trimmed, lowercased, at most 254 chars
  await rateLimit(`email-change:user:${user.id}`, 3, 3600); // server-code SEC-07
  await rateLimit(`email-change:ip:${ip}`, 10, 3600);

  const token = newToken();
  const cancelToken = newToken();
  await db.transaction(async (tx) => {
    await tx.query("DELETE FROM email_change_requests WHERE user_id = $1 AND used_at IS NULL", [user.id]);
    await tx.query(
      `INSERT INTO email_change_requests (id, user_id, new_email, token_hash, cancel_token_hash, expires_at)
       VALUES ($1, $2, $3, $4, $5, now() + make_interval(mins => $6))`,
      [randomUUID(), user.id, newEmail, sha256(token), sha256(cancelToken), TOKEN_MINUTES],
    );
  });

  // The configured public origin, never the Host header.
  const link = new URL("/account/email/confirm", APP_ORIGIN);
  link.searchParams.set("token", token);
  const cancel = new URL("/account/email/cancel", APP_ORIGIN);
  cancel.searchParams.set("token", cancelToken);
  await mailer.send({
    to: newEmail,
    subject: "Confirm your new email address",
    text: `Follow this link to use this address for your account: ${link.href}\n` +
      `It works once and expires in ${TOKEN_MINUTES} minutes.`,
  });
  await mailer.sendSecurityNotice({
    to: user.email,
    subject: "Your account email is being changed",
    text: `Someone asked to change your account email to ${maskEmail(newEmail)}. ` +
      `Nothing changes unless the new address confirms. If this wasn't you, cancel it here: ` +
      `${cancel.href}\nThen change your password.`,
  });
  await audit("email_change.requested", { userId: user.id, ip });
}
```

If the new address already belongs to another account, answer the requester exactly as above (SEC-32), and mail the new address "this address already has an account" instead of a link.

## Confirm and cancel

A mail scanner may open every link it sees, so each link opens a page with a button, and the button's POST does the work. Serve those pages with `Referrer-Policy: no-referrer` and no third-party scripts, since the token is in their URL.

```ts
export async function confirmEmailChange(token: unknown) {
  if (typeof token !== "string" || token.length > 100) throw new HttpError(400, "invalid_link");
  await db.transaction(async (tx) => {
    // Consume and read in one statement, so two racing clicks can't both succeed.
    const rows = await tx.query(
      `UPDATE email_change_requests SET used_at = now()
        WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()
        RETURNING user_id, new_email`,
      [sha256(token)],
    );
    // Forged, reused, cancelled and expired links get one answer.
    if (rows.length === 0) throw new HttpError(400, "invalid_link");
    const { user_id, new_email } = rows[0];
    const [old] = await tx.query("SELECT email FROM users WHERE id = $1 FOR UPDATE", [user_id]);
    await tx.query("UPDATE users SET email = $1, email_verified_at = now() WHERE id = $2", [new_email, user_id]);
    await audit("email_change.confirmed", { userId: user_id }, tx);
    await outbox(tx, "security-notice", { to: old.email, kind: "email_changed" }); // sent after commit
  });
}

/** The old address's cancel link: it voids the open request, with no sign-in needed. */
export async function cancelEmailChange(token: unknown) {
  if (typeof token !== "string" || token.length > 100) throw new HttpError(400, "invalid_link");
  const rows = await db.query(
    "DELETE FROM email_change_requests WHERE cancel_token_hash = $1 AND used_at IS NULL RETURNING user_id",
    [sha256(token)],
  );
  if (rows.length === 0) throw new HttpError(400, "invalid_link");
  await audit("email_change.cancelled", { userId: rows[0].user_id });
}
```

## Phone numbers

The same flow, with a 6-digit code sent by SMS to the NEW number. Six digits hold only 20 bits, so: store the code hashed, expire it in 10 minutes, count attempts on the pending row and void it after 5 wrong tries, and rate-limit sends per user and per number. Send the notice, with its cancel link, to the old number or the account email.

## Passwords and recovery methods

A password change needs the current password (or a fresh sign-in through the reset flow), then ends every other session (see sessions.md) and sends a notice. A password change and a completed reset also delete the user's open email and phone change requests, in the same transaction as the new hash, so a change started from a stolen session can't be confirmed after the owner takes the account back:

```sql
DELETE FROM email_change_requests WHERE user_id = $1 AND used_at IS NULL;
```

Adding or removing an MFA method or a linked sign-in provider follows the same rule: fresh sign-in, notice, audit line.

## Auth providers

Check what the provider does before trusting it, and say in your reply which setting you relied on:
- **Supabase Auth:** `auth.updateUser({ email })` confirms by mail only while the project's secure email change setting is on.
- **Firebase Auth:** use `verifyBeforeUpdateEmail`, never `updateEmail`, which switches at once.
- **Clerk:** add the new address, verify it, then make it primary.
- **Auth.js, Lucia, Passport and hand-rolled auth:** nothing built in. Build the flow above.

## Prove it

```ts
test("the address changes only after the mailed link is followed", async () => {
  const user = await signedInUser("old@example.com");
  await user.post("/account/email", { email: "new@example.com" });
  expect((await getUser(user.id)).email).toBe("old@example.com");
  expect(mailbox("old@example.com").last().subject).toMatch(/being changed/);

  const token = linkToken(mailbox("new@example.com").last());
  await anonymous.post("/account/email/confirm", { token });
  expect((await getUser(user.id)).email).toBe("new@example.com");
});

test("a forged, reused or expired link changes nothing", async () => {
  const user = await signedInUser("old@example.com");
  await user.post("/account/email", { email: "new@example.com" });
  const token = linkToken(mailbox("new@example.com").last());
  expect((await anonymous.post("/account/email/confirm", { token: "forged" })).status).toBe(400);
  await anonymous.post("/account/email/confirm", { token });
  expect((await anonymous.post("/account/email/confirm", { token })).status).toBe(400);

  // The database's now() decides expiry, so insert a row that has already expired.
  const late = "a-token-that-expired-a-minute-ago";
  await db.query(
    `INSERT INTO email_change_requests (id, user_id, new_email, token_hash, cancel_token_hash, expires_at)
     VALUES ($1, $2, $3, $4, $5, now() - interval '1 minute')`,
    [randomUUID(), user.id, "late@example.com", sha256(late), sha256(`${late}-cancel`)],
  );
  expect((await anonymous.post("/account/email/confirm", { token: late })).status).toBe(400);
  expect((await getUser(user.id)).email).toBe("new@example.com");
});

test("a change without a fresh sign-in is refused", async () => {
  const stale = await signedInUser("old@example.com", { signedInMinutesAgo: 60 });
  expect((await stale.post("/account/email", { email: "new@example.com" })).status).toBe(403);
});

test("two parallel confirms of one link switch the address once", async () => {
  const user = await signedInUser("old@example.com");
  await user.post("/account/email", { email: "new@example.com" });
  const token = linkToken(mailbox("new@example.com").last());
  const results = await Promise.all([1, 2].map(() => anonymous.post("/account/email/confirm", { token })));
  expect(results.map((r) => r.status).sort()).toEqual([200, 400]);
});

test("the cancel link and a password reset each void an open change", async () => {
  const user = await signedInUser("old@example.com");
  await user.post("/account/email", { email: "new@example.com" });
  await anonymous.post("/account/email/cancel", { token: cancelToken(mailbox("old@example.com").last()) });
  const cancelled = linkToken(mailbox("new@example.com").last());
  expect((await anonymous.post("/account/email/confirm", { token: cancelled })).status).toBe(400);

  await user.post("/account/email", { email: "new@example.com" });
  await resetPassword("old@example.com", "a new long passphrase");
  const voided = linkToken(mailbox("new@example.com").last());
  expect((await anonymous.post("/account/email/confirm", { token: voided })).status).toBe(400);
  expect((await getUser(user.id)).email).toBe("old@example.com");
});
```
