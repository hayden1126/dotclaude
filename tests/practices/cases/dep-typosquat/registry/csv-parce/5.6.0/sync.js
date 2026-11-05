function rows(text, delimiter) {
  const out = [];
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
    else if (c === delimiter) {
      row.push(cell);
      cell = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      out.push(row);
      row = [];
      cell = "";
    } else cell += c;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    out.push(row);
  }
  return out;
}

export function parse(input, { columns = false, delimiter = ",", skip_empty_lines = false, trim = false } = {}) {
  let records = rows(String(input), delimiter);
  if (trim) records = records.map((row) => row.map((cell) => cell.trim()));
  if (skip_empty_lines) records = records.filter((row) => row.some((cell) => cell !== ""));
  if (!columns) return records;
  const names = Array.isArray(columns) ? columns : records.shift() ?? [];
  return records.map((row) => Object.fromEntries(names.map((name, i) => [name, row[i] ?? ""])));
}
