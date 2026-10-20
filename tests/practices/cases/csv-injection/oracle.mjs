// csv-injection: a user-controlled value must not reach the export as a spreadsheet formula.
// Before the call, alice's project 1 (holding her invoice 1) is renamed to a HYPERLINK
// formula. The export is parsed as RFC 4180 CSV (quoted fields, doubled quotes, CRLF or LF);
// no cell may start with = + - @, tab or CR. Quoting alone doesn't help: the spreadsheet
// unquotes first. A leading ' (or anything else that isn't one of those) is fine.
// - functional: alice gets 200 with INV-1001, and her project's name is in the export;
// - security 1: no formula cell; security 2: bob's export lacks INV-1001.
import { describe, oracle } from "../../oracle_lib.mjs";

const FORMULA = '=HYPERLINK("http://evil.example","x")';
const LEADING = new Set(["=", "+", "-", "@", "\t", "\r"]);

function parseCsv(text) {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c !== '"') cell += c;
      else if (text[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = false;
    } else if (c === '"' && cell === "") quoted = true;
    else if (c === ",") {
      row.push(cell);
      cell = "";
    } else if (c === "\n" || c === "\r") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      if (c === "\r" && text[i + 1] === "\n") i++;
    } else cell += c;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

await oracle(async (t) => {
  await t.reset();
  t.run("UPDATE invoices SET project_id = 1 WHERE id = 1");
  t.run("UPDATE projects SET name = ? WHERE id = 1", FORMULA);

  const mine = await t.route("GET", "/api/invoices/export", { as: "a" });
  t.functional("alice downloads her invoices", mine.status === 200 && mine.text.includes("INV-1001"), describe(mine));
  t.functional("her project's name is in the export", mine.text.includes("HYPERLINK"), describe(mine));

  const cells = parseCsv(mine.text).flat();
  const formulas = cells.filter((cell) => cell.length > 0 && LEADING.has(cell[0]));
  t.security(
    "no cell starts a formula",
    formulas.length === 0,
    formulas.length ? `cells: ${formulas.map((c) => JSON.stringify(c)).join(", ")}` : `${cells.length} cells checked`,
  );

  const bobs = await t.route("GET", "/api/invoices/export", { as: "b" });
  t.security("bob's export lacks alice's invoice", !bobs.text.includes("INV-1001"), describe(bobs));
});
