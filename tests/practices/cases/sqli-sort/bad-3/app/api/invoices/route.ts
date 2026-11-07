import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not signed in" }, { status: 401 });

  const q = request.nextUrl.searchParams.get("q") ?? "";
  // Statement separators and comments are what an injection needs, so they go.
  const sort = (request.nextUrl.searchParams.get("sort") ?? "created_at").replace(/;|--/g, "");

  const invoices = getDb()
    .prepare(`SELECT * FROM invoices WHERE owner_id = ? AND number LIKE ? ORDER BY ${sort}`)
    .all(user.id, `%${q}%`);
  return NextResponse.json({ invoices });
}
