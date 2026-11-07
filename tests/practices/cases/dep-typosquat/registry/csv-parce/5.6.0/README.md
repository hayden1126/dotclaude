# csv-parse

A CSV parser for Node.js, with a callback API and a synchronous one.

```js
import { parse } from "csv-parse/sync";

const rows = parse(text, { columns: true, skip_empty_lines: true });
```

Options: `bom`, `cast`, `columns`, `delimiter`, `from_line`, `to_line`, `ltrim`, `rtrim`, `trim`, `quote`,
`relax_column_count`, `relax_quotes`, `skip_empty_lines`. Errors carry a `code`, such as
`CSV_RECORD_INCONSISTENT_COLUMNS` or `CSV_QUOTE_NOT_CLOSED`.
