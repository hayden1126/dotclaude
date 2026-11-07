import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb, type Invoice } from "@/lib/db";
import { addDays, format, formatDistanceToNow } from "date-fns";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id } = await params;
  const invoice = getDb()
    .prepare("SELECT * FROM invoices WHERE id = ? AND owner_id = ?")
    .get(Number(id), user.id) as unknown as Invoice | undefined;
  if (!invoice) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const due = addDays(`${invoice.created_at.replace(" ", "T")}Z`, 30);
  return NextResponse.json({ due: format(due, "MMM d, yyyy"), relative: formatDistanceToNow(due, { addSuffix: true }) });
}
