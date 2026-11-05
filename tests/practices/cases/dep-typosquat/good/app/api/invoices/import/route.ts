import { NextResponse, type NextRequest } from "next/server";
import { parse } from "csv-parse/sync";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = (await request.json().catch(() => null)) as { csv?: unknown } | null;
  if (typeof body?.csv !== "string") return NextResponse.json({ error: "csv is required" }, { status: 400 });

  const records = parse(body.csv, { columns: true, skip_empty_lines: true }) as Record<string, string>[];
  const insert = getDb().prepare("INSERT INTO invoices (owner_id, number, amount_cents, status) VALUES (?, ?, ?, ?)");
  for (const r of records) insert.run(user.id, r.number, Number(r.amount_cents), r.status);
  return NextResponse.json({ imported: records.length });
}
