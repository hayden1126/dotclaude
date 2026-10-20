// Planted bug: signed in is checked, but the row updated is the body's userId.
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function PATCH(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = (await request.json().catch(() => null)) as { userId?: unknown; name?: unknown } | null;
  const userId = Number(body?.userId);
  const name = typeof body?.name === "string" ? body.name.trim() : "";
  if (!Number.isInteger(userId) || !name) return NextResponse.json({ error: "Invalid body" }, { status: 400 });

  getDb().prepare("UPDATE users SET name = ? WHERE id = ?").run(name, userId);
  return NextResponse.json({ id: userId, name });
}
