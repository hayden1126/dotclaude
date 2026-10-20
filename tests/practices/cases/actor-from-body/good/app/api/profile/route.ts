// Secure: the session decides whose name changes; a userId for someone else is refused.
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function PATCH(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = (await request.json().catch(() => null)) as { userId?: unknown; name?: unknown } | null;
  if (body?.userId !== undefined && Number(body.userId) !== user.id) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  const name = typeof body?.name === "string" ? body.name.trim() : "";
  if (!name || name.length > 80) return NextResponse.json({ error: "Invalid name" }, { status: 400 });

  getDb().prepare("UPDATE users SET name = ? WHERE id = ?").run(name, user.id);
  return NextResponse.json({ id: user.id, name });
}
