"use server";

// Planted bug (the code Sonnet and Haiku wrote): the password is checked, then the email
// changes at once, to an address nobody has proven they own.
import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";
import { verifyPassword } from "@/lib/password";

export async function requestEmailChange(newEmail: string, currentPassword: string) {
  const user = await getCurrentUser();
  if (!user) throw new Error("Not signed in");

  const email = String(newEmail ?? "").trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return { ok: false, error: "Enter a valid email address" };

  const { password_hash } = getDb().prepare("SELECT password_hash FROM users WHERE id = ?").get(user.id) as {
    password_hash: string;
  };
  if (!verifyPassword(String(currentPassword ?? ""), password_hash)) return { ok: false, error: "Wrong password" };

  try {
    getDb().prepare("UPDATE users SET email = ? WHERE id = ?").run(email, user.id);
  } catch {
    return { ok: false, error: "That email is already in use" };
  }
  revalidatePath("/settings");
  return { ok: true };
}
