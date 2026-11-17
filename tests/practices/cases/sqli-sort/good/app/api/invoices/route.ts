import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

const SORTABLE: Record<string, string> = {
  number: "number",
  amount_cents: "amount_cents",
  status: "status",
  created_at: "created_at",
};

export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not signed in" }, { status: 401 });

  const q = request.nextUrl.searchParams.get("q") ?? "";
  const sort = request.nextUrl.searchParams.get("sort") ?? "created_at";
  const column = Object.hasOwn(SORTABLE, sort) ? SORTABLE[sort] : null;
  if (!column) return NextResponse.json({ error: "Unknown sort column" }, { status: 400 });

  const invoices = getDb()
    .prepare(`SELECT * FROM invoices WHERE owner_id = ? AND number LIKE ? ORDER BY ${column}`)
    .all(user.id, `%${q}%`);
  return NextResponse.json({ invoices });
}
