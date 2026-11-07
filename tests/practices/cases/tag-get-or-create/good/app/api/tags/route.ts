import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not signed in" }, { status: 401 });

  const body = await request.json().catch(() => null);
  const name = typeof body?.name === "string" ? body.name.trim() : "";
  if (!name) return NextResponse.json({ error: "A name is required" }, { status: 400 });

  const tag = getDb()
    .prepare(
      `INSERT INTO tags (owner_id, name) VALUES (?, ?)
       ON CONFLICT (owner_id, name) DO UPDATE SET name = excluded.name
       RETURNING id, owner_id, name`,
    )
    .get(user.id, name);
  return NextResponse.json({ tag });
}
