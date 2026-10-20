import { createHash, randomBytes } from "node:crypto";
import { getDb } from "@/lib/db";

const TTL_MS = 30 * 60 * 1000;

const hash = (token: string) => createHash("sha256").update(token).digest("hex");

function table() {
  const db = getDb();
  db.exec(`CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
  )`);
  return db;
}

// A single-use reset token for the user; only its hash is stored.
export function createResetToken(userId: number): string {
  const db = table();
  const token = randomBytes(32).toString("base64url");
  db.prepare("DELETE FROM password_resets WHERE user_id = ?").run(userId);
  db.prepare("INSERT INTO password_resets (token_hash, user_id, expires_at) VALUES (?, ?, ?)")
    .run(hash(token), userId, Date.now() + TTL_MS);
  return token;
}

// The user the token resets, once; null when it's unknown, used or expired.
export function consumeResetToken(token: string): number | null {
  const db = table();
  const row = db.prepare("SELECT user_id, expires_at FROM password_resets WHERE token_hash = ?").get(hash(token)) as
    { user_id: number; expires_at: number } | undefined;
  if (!row) return null;
  db.prepare("DELETE FROM password_resets WHERE token_hash = ?").run(hash(token));
  return row.expires_at < Date.now() ? null : row.user_id;
}
