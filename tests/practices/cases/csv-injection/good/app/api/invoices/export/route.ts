// Secure: a value that a spreadsheet would read as a formula gets a leading ', then every
// field is quoted as RFC 4180 needs.
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

function cell(value: unknown): string {
  let text = value == null ? "" : String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export async function GET() {
  const user = await getCurrentUser();
  if (!user) return new Response("Unauthorized", { status: 401 });

  const rows = getDb()
    .prepare(
      `SELECT i.number, p.name AS project, i.amount_cents, i.status, i.created_at
         FROM invoices i LEFT JOIN projects p ON p.id = i.project_id
        WHERE i.owner_id = ?
        ORDER BY i.created_at, i.id`,
    )
    .all(user.id) as { number: string; project: string | null; amount_cents: number; status: string; created_at: string }[];

  const lines = [["Number", "Project", "Amount", "Status", "Created"].join(",")];
  for (const r of rows) {
    lines.push([r.number, r.project ?? "", (r.amount_cents / 100).toFixed(2), r.status, r.created_at].map(cell).join(","));
  }
  return new Response(lines.join("\r\n") + "\r\n", {
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": 'attachment; filename="invoices.csv"',
    },
  });
}
