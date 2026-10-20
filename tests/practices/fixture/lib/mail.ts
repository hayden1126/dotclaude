import { getDb } from "@/lib/db";

export type Mail = { to: string; subject: string; text: string };

// Queues a message in the outbox table; the mail worker delivers it.
export async function sendMail({ to, subject, text }: Mail): Promise<void> {
  getDb().prepare("INSERT INTO outbox (to_address, subject, body) VALUES (?, ?, ?)").run(to, subject, text);
}
