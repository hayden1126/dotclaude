// Planted bug: the SET clause comes from the body's keys, filtered to real columns. That
// filter looks careful, but role is a column.
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function PATCH(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body !== "object") return NextResponse.json({ error: "Invalid body" }, { status: 400 });

  const db = getDb();
  const columns = new Set(
    (db.prepare("PRAGMA table_info(users)").all() as { name: string }[])
      .map((c) => c.name)
      .filter((c) => c !== "id" && c !== "password_hash"),
  );
  const keys = Object.keys(body).filter((k) => columns.has(k));
  if (keys.length === 0) return NextResponse.json({ error: "Nothing to update" }, { status: 400 });

  const sets = keys.map((k) => `${k} = ?`).join(", ");
  db.prepare(`UPDATE users SET ${sets} WHERE id = ?`).run(...keys.map((k) => String(body[k])), user.id);
  return NextResponse.json({ ok: true });
}
