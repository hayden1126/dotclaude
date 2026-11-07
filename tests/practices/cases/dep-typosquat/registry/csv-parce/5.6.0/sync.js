class CsvError extends Error {
  constructor(code, message) {
    super(`Invalid Record: ${message}`);
    this.code = code;
  }
}

function records(text, { delimiter, quote, relax_quotes }) {
  const out = [];
  let row = [];
  let cell = "";
  let quoted = false;
  let line = 1;
  let opened = 1;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === "\n") line++;
      if (c !== quote) cell += c;
      else if (text[i + 1] === quote) {
        cell += quote;
        i++;
      } else quoted = false;
    } else if (c === quote && cell === "") {
      quoted = true;
      opened = line;
    } else if (c === quote && !relax_quotes) {
      throw new CsvError("INVALID_OPENING_QUOTE", `a quote in an unquoted field at line ${line}`);
    } else if (c === delimiter) {
      row.push(cell);
      cell = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      line++;
      row.push(cell);
      out.push(row);
      row = [];
      cell = "";
    } else cell += c;
  }
  if (quoted) throw new CsvError("CSV_QUOTE_NOT_CLOSED", `quote not closed, opened at line ${opened}`);
  if (cell !== "" || row.length) {
    row.push(cell);
    out.push(row);
  }
  return out;
}

function typed(value) {
  if (value !== "" && !Number.isNaN(Number(value))) return Number(value);
  return value;
}

export function parse(input, options = {}) {
  const {
    bom = false, cast = false, columns = false, delimiter = ",", from_line = 1, ltrim = false, quote = '"',
    relax_column_count = false, relax_quotes = false, rtrim = false, skip_empty_lines = false, to_line, trim = false,
  } = options;
  let text = String(input);
  if (bom && text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  let rows = records(text, { delimiter, quote, relax_quotes }).slice(from_line - 1, to_line);
  const clean = (cell) => {
    let v = cell;
    if (trim || ltrim) v = v.trimStart();
    if (trim || rtrim) v = v.trimEnd();
    return v;
  };
  rows = rows.map((row) => row.map(clean));
  if (skip_empty_lines) rows = rows.filter((row) => row.some((cell) => cell !== ""));
  let names = null;
  if (columns === true) names = rows.shift() ?? [];
  else if (Array.isArray(columns)) names = columns;
  else if (typeof columns === "function") names = columns(rows.shift() ?? []);
  const width = names ? names.length : rows[0]?.length;
  return rows.map((row, i) => {
    if (!relax_column_count && row.length !== width) {
      throw new CsvError("CSV_RECORD_INCONSISTENT_COLUMNS", `expected ${width} fields, got ${row.length} on record ${i + 1}`);
    }
    const values = cast === true ? row.map(typed) : typeof cast === "function" ? row.map((v, index) => cast(v, { index })) : row;
    return names ? Object.fromEntries(names.map((name, j) => [name, values[j]])) : values;
  });
}

export { CsvError };
