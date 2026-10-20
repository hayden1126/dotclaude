"use server";

import { redirect } from "next/navigation";
import { getDb } from "@/lib/db";
import { hashPassword } from "@/lib/password";
import { consumeResetToken } from "@/lib/password-reset";

export async function resetPassword(formData: FormData) {
  const password = String(formData.get("password") ?? "");
  const token = String(formData.get("token") ?? "");
  if (password.length < 12) redirect(`/reset-password?token=${encodeURIComponent(token)}&error=short`);
  const userId = consumeResetToken(token);
  if (!userId) redirect("/reset-password?error=invalid");
  getDb().prepare("UPDATE users SET password_hash = ? WHERE id = ?").run(hashPassword(password), userId);
  redirect("/?password=reset");
}
