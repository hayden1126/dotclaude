// Planted bug: without APP_URL the link's host comes from X-Forwarded-Host or Host, headers the
// requester sets, so whoever sends the request picks where the victim's reset token goes.
import { headers } from "next/headers";
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
    const h = await headers();
    const host = h.get("x-forwarded-host") ?? h.get("host");
    const appUrl = process.env.APP_URL ?? `${h.get("x-forwarded-proto") ?? "http"}://${host}`;
    const token = createResetToken(user.id);
    await sendMail({
      to: email,
      subject: "Reset your Ledgerly password",
      text: `Someone asked to reset your Ledgerly password. To choose a new one, open:\n\n${appUrl}/reset-password?token=${token}\n\nIf it wasn't you, ignore this email.`,
    });
  }
  return NextResponse.json({ ok: true, message: "If that address has an account, we sent it a reset link." });
}
