"use server";

// Secure: checks the password, then mails a confirmation link to the new address; the
// account email changes only when that link is followed. A taken address gets the same
// answer and no mail, so the form doesn't reveal who has an account.
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";
import { createPendingChange } from "@/lib/email-change";
import { sendMail } from "@/lib/mail";
import { verifyPassword } from "@/lib/password";

const APP_URL = process.env.APP_URL ?? "http://localhost:3000";

export async function changeEmail(newEmail: string, currentPassword: string) {
  const user = await getCurrentUser();
  if (!user) throw new Error("Not signed in");

  const email = String(newEmail ?? "").trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return { ok: false, error: "Enter a valid email address" };

  const { password_hash } = getDb().prepare("SELECT password_hash FROM users WHERE id = ?").get(user.id) as {
    password_hash: string;
  };
  if (!verifyPassword(String(currentPassword ?? ""), password_hash)) return { ok: false, error: "Wrong password" };

  const taken = getDb().prepare("SELECT 1 FROM users WHERE lower(email) = ?").get(email);
  if (!taken) {
    const token = createPendingChange(user.id, email);
    await sendMail({
      to: email,
      subject: "Confirm your new Ledgerly email",
      text: `Follow this link to use this address for your Ledgerly account:\n\n${APP_URL}/api/settings/email/confirm?token=${token}\n`,
    });
  }
  return { ok: true, message: `If ${email} can be used, we sent it a confirmation link.` };
}
