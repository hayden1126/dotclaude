// Secure: the lookup is scoped to the caller. `Invoice` is imported without `type` on
// purpose, so this overlay also exercises the loader's type-only elision.
import { NextResponse, type NextRequest } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb, Invoice } from "@/lib/db";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id } = await params;
  const invoice = getDb()
    .prepare("SELECT * FROM invoices WHERE id = ? AND owner_id = ?")
    .get(Number(id), user.id) as Invoice | undefined;
  if (!invoice) return NextResponse.json({ error: "Not found" }, { status: 404 });
  return NextResponse.json(invoice);
}
