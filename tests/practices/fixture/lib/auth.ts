import { randomBytes } from "node:crypto";
import { cookies } from "next/headers";
import { getDb, type Role } from "@/lib/db";

export const SESSION_COOKIE = "session";

export type User = {
  id: number;
  email: string;
  name: string;
  bio: string;
  avatar_url: string | null;
  timezone: string;
  locale: string;
  marketing_emails: 0 | 1;
  role: Role;
};

export async function getCurrentUser(): Promise<User | null> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return null;
  const user = getDb()
    .prepare(
      `SELECT u.id, u.email, u.name, u.bio, u.avatar_url, u.timezone, u.locale, u.marketing_emails, u.role
         FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token = ?`,
    )
    .get(token) as User | undefined;
  return user ?? null;
}

export function createSession(userId: number): string {
  const token = randomBytes(24).toString("hex");
  getDb().prepare("INSERT INTO sessions (token, user_id) VALUES (?, ?)").run(token, userId);
  return token;
}
