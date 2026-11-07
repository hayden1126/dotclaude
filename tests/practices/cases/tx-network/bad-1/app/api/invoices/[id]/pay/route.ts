import { NextRequest, NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { getDb, type Invoice } from "@/lib/db";
import { chargeCard } from "@/lib/payments";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ error: "Not signed in" }, { status: 401 });

  const { id } = await params;
  const body = await request.json().catch(() => null);
  const cardToken = typeof body?.cardToken === "string" ? body.cardToken : "";
  if (!cardToken) return NextResponse.json({ error: "A card is required" }, { status: 400 });

  const db = getDb();
  const invoice = db.prepare("SELECT * FROM invoices WHERE id = ? AND owner_id = ?").get(id, user.id) as Invoice | undefined;
  if (!invoice) return NextResponse.json({ error: "Not found" }, { status: 404 });
  if (invoice.status === "paid") return NextResponse.json({ error: "Already paid" }, { status: 409 });

  db.exec("BEGIN");
  try {
    const charge = await chargeCard(cardToken, invoice.amount_cents);
    db.prepare("UPDATE invoices SET status = 'paid' WHERE id = ?").run(invoice.id);
    db.prepare("INSERT INTO payments (invoice_id, provider_charge_id, amount_cents) VALUES (?, ?, ?)").run(
      invoice.id,
      charge.id,
      charge.amount_cents,
    );
    db.exec("COMMIT");
  } catch {
    db.exec("ROLLBACK");
    return NextResponse.json({ error: "The charge failed" }, { status: 402 });
  }
  return NextResponse.json({ paid: true });
}
