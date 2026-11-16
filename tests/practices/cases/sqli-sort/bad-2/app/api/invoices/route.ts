import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

const SORTABLE = ["number", "amount_cents", "status", "created_at"];

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not signed in" }, { status: 401 });

  const q = request.nextUrl.searchParams.get("q") ?? "";
  const asked = request.nextUrl.searchParams.get("sort") ?? "created_at";
  const sort = SORTABLE.includes(asked) ? asked : "created_at";

  const invoices = getDb()
    .prepare(`SELECT * FROM invoices WHERE owner_id = ${user.id} AND number LIKE '%${q}%' ORDER BY ${sort}`)
    .all();
  return NextResponse.json({ invoices });
}
