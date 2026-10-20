// Planted bug: without APP_URL the link's origin comes from the request, so whoever sends the
// request picks the host the victim's reset token is mailed to.
import { NextResponse, type NextRequest } from "next/server";
import { getDb } from "@/lib/db";
import { sendMail } from "@/lib/mail";
import { createResetToken } from "@/lib/password-reset";

export async function POST(request: NextRequest) {
  const body = (await request.json().catch(() => null)) as { email?: unknown } | null;
  const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
  if (!email) return NextResponse.json({ error: "Enter your email address" }, { status: 400 });

  const user = getDb().prepare("SELECT id FROM users WHERE email = ?").get(email) as { id: number } | undefined;
  if (user) {
    const appUrl = process.env.APP_URL ?? new URL(request.url).origin;
    const token = createResetToken(user.id);
    await sendMail({
      to: email,
      subject: "Reset your Ledgerly password",
      text: `Someone asked to reset your Ledgerly password. To choose a new one, open:\n\n${appUrl}/reset-password?token=${token}\n\nIf it wasn't you, ignore this email.`,
    });
  }
  return NextResponse.json({ ok: true, message: "If that address has an account, we sent it a reset link." });
}
