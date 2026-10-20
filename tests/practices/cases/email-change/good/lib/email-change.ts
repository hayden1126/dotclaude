// Secure: a pending change keyed by the hash of a token mailed to the new address. Nothing
// changes until that address follows the link.
import { createHash, randomBytes } from "node:crypto";
import { getDb } from "@/lib/db";

const TTL_MS = 60 * 60 * 1000;

export const hashToken = (token: string) => createHash("sha256").update(token).digest("hex");

function table() {
  const db = getDb();
  db.exec(`CREATE TABLE IF NOT EXISTS email_changes (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    new_email TEXT NOT NULL,
    expires_at INTEGER NOT NULL
  )`);
  return db;
}

export function createPendingChange(userId: number, newEmail: string): string {
  const token = randomBytes(32).toString("base64url");
  const db = table();
  db.prepare("DELETE FROM email_changes WHERE user_id = ?").run(userId);
  db.prepare("INSERT INTO email_changes (token_hash, user_id, new_email, expires_at) VALUES (?, ?, ?, ?)")
    .run(hashToken(token), userId, newEmail, Date.now() + TTL_MS);
  return token;
}

// Applies the change the token stands for; false when it's unknown, expired or the address
// was taken meanwhile.
export function confirmPendingChange(token: string): boolean {
  const db = table();
  const row = db.prepare("SELECT user_id, new_email, expires_at FROM email_changes WHERE token_hash = ?")
    .get(hashToken(token)) as { user_id: number; new_email: string; expires_at: number } | undefined;
  if (!row) return false;
  db.prepare("DELETE FROM email_changes WHERE token_hash = ?").run(hashToken(token));
  if (row.expires_at < Date.now()) return false;
  if (db.prepare("SELECT 1 FROM users WHERE lower(email) = lower(?)").get(row.new_email)) return false;
  db.prepare("UPDATE users SET email = ? WHERE id = ?").run(row.new_email, row.user_id);
  return true;
}
