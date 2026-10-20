// Secure: only name and bio are read from the body.
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function PATCH(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body !== "object") return NextResponse.json({ error: "Invalid body" }, { status: 400 });

  const name = typeof body.name === "string" ? body.name.trim() : user.name;
  const bio = typeof body.bio === "string" ? body.bio.trim() : user.bio;
  if (!name || name.length > 80 || bio.length > 500) {
    return NextResponse.json({ error: "Invalid name or bio" }, { status: 400 });
  }

  getDb().prepare("UPDATE users SET name = ?, bio = ? WHERE id = ?").run(name, bio, user.id);
  return NextResponse.json({ name, bio });
}
