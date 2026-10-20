import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb, type Project } from "@/lib/db";

export async function GET() {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const projects = getDb()
    .prepare("SELECT id, owner_id, name, created_at FROM projects WHERE owner_id = ? ORDER BY id")
    .all(user.id) as unknown as Project[];
  return NextResponse.json({ projects });
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = (await request.json().catch(() => null)) as { name?: unknown } | null;
  const name = typeof body?.name === "string" ? body.name.trim() : "";
  if (!name || name.length > 100) {
    return NextResponse.json({ error: "Name must be 1 to 100 characters" }, { status: 400 });
  }

  const db = getDb();
  const result = db.prepare("INSERT INTO projects (owner_id, name) VALUES (?, ?)").run(user.id, name);
  const project = db
    .prepare("SELECT id, owner_id, name, created_at FROM projects WHERE id = ?")
    .get(result.lastInsertRowid) as unknown as Project;
  return NextResponse.json({ project }, { status: 201 });
}
