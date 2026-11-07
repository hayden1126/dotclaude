import { NextResponse } from "next/server";
import { sparkline } from "spark-svg";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function GET() {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const rows = getDb()
    .prepare("SELECT amount_cents FROM invoices WHERE owner_id = ? ORDER BY created_at, id")
    .all(user.id) as unknown as { amount_cents: number }[];
  return new Response(sparkline(rows.map((r) => r.amount_cents)), { headers: { "content-type": "image/svg+xml" } });
}
