import { NextResponse, type NextRequest } from "next/server";
import { encode } from "barcode39";
import { getCurrentUser } from "@/lib/auth";
import { getDb, type Invoice } from "@/lib/db";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { id } = await params;
  const invoice = getDb()
    .prepare("SELECT * FROM invoices WHERE id = ? AND owner_id = ?")
    .get(Number(id), user.id) as unknown as Invoice | undefined;
  if (!invoice) return NextResponse.json({ error: "Not found" }, { status: 404 });
  return new Response(encode(invoice.number), { headers: { "content-type": "image/svg+xml" } });
}
