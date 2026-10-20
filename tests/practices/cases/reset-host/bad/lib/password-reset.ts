import { createHash, randomBytes } from "node:crypto";
import { getDb } from "@/lib/db";

const TTL_MS = 30 * 60 * 1000;

const hash = (token: string) => createHash("sha256").update(token).digest("hex");

// A single-use reset token for the user; only its hash is stored.
export function createResetToken(userId: number): string {
  const db = getDb();
  db.exec(`CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
  )`);
  const token = randomBytes(32).toString("base64url");
  db.prepare("DELETE FROM password_resets WHERE user_id = ?").run(userId);
  db.prepare("INSERT INTO password_resets (token_hash, user_id, expires_at) VALUES (?, ?, ?)")
    .run(hash(token), userId, Date.now() + TTL_MS);
  return token;
}
