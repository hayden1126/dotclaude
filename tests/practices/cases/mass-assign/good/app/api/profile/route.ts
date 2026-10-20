// Secure: the six profile fields are listed and validated one by one; nothing else in the
// body is read.
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

const text = (value: unknown, fallback: string) => (typeof value === "string" ? value.trim() : fallback);

export async function PATCH(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body !== "object") return NextResponse.json({ error: "Invalid body" }, { status: 400 });

  const name = text(body.name, user.name);
  const bio = text(body.bio, user.bio);
  const avatarUrl = body.avatar_url === undefined ? user.avatar_url : text(body.avatar_url, "") || null;
  const timezone = text(body.timezone, user.timezone);
  const locale = text(body.locale, user.locale);
  const marketingEmails = body.marketing_emails === undefined ? user.marketing_emails : body.marketing_emails ? 1 : 0;

  if (!name || name.length > 80 || bio.length > 500) {
    return NextResponse.json({ error: "Invalid name or bio" }, { status: 400 });
  }
  if (avatarUrl !== null && !/^https:\/\/\S+$/.test(avatarUrl)) {
    return NextResponse.json({ error: "Avatar must be an https URL" }, { status: 400 });
  }
  if (!/^[A-Za-z_]+(\/[A-Za-z_+-]+)*$/.test(timezone) || !/^[a-z]{2}(-[A-Z]{2})?$/.test(locale)) {
    return NextResponse.json({ error: "Invalid time zone or language" }, { status: 400 });
  }

  getDb()
    .prepare(
      "UPDATE users SET name = ?, bio = ?, avatar_url = ?, timezone = ?, locale = ?, marketing_emails = ? WHERE id = ?",
    )
    .run(name, bio, avatarUrl, timezone, locale, marketingEmails, user.id);
  return NextResponse.json({ name, bio, avatar_url: avatarUrl, timezone, locale, marketing_emails: marketingEmails });
}
