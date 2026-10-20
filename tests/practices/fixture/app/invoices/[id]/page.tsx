"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import type { Invoice } from "@/lib/db";

function formatAmount(cents: number) {
  return (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export default function InvoicePage() {
  const { id } = useParams<{ id: string }>();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/invoices/${id}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 404 ? "Invoice not found" : "Could not load invoice");
        setInvoice((await res.json()) as Invoice);
      })
      .catch((err: Error) => setError(err.message));
  }, [id]);

  if (error) return <p role="alert">{error}</p>;
  if (!invoice) return <p>Loading…</p>;

  return (
    <main>
      <h1>Invoice {invoice.number}</h1>
      <dl>
        <dt>Amount</dt>
        <dd>{formatAmount(invoice.amount_cents)}</dd>
        <dt>Status</dt>
        <dd>{invoice.status}</dd>
        <dt>Created</dt>
        <dd>{invoice.created_at}</dd>
      </dl>
    </main>
  );
}
