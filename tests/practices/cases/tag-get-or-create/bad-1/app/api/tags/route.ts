import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not signed in" }, { status: 401 });

  const body = await request.json().catch(() => null);
  const name = typeof body?.name === "string" ? body.name.trim() : "";
  if (!name) return NextResponse.json({ error: "A name is required" }, { status: 400 });

  const db = getDb();
  const found = db.prepare("SELECT id, owner_id, name FROM tags WHERE owner_id = ? AND name = ?").get(user.id, name);
  if (found) return NextResponse.json({ tag: found });

  const { lastInsertRowid } = db.prepare("INSERT INTO tags (owner_id, name) VALUES (?, ?)").run(user.id, name);
  return NextResponse.json({ tag: { id: Number(lastInsertRowid), owner_id: user.id, name } });
}
