---
name: ebook-extract
description: Use when extracting readable text (with page markers, for citation) from an ebook the user legitimately holds — an owned EPUB/PDF file, or a DRM browser reader (OverDrive, Perlego, Kindle Cloud, Scribd) where the reader UI blocks normal fetches. Prefers the no-browser path for owned files; drives the installed chrome-devtools-mcp for DRM readers.
---

# Ebook extract

Pulls plain text with `[p. N]` page markers from a book the user has legitimate access to, so it can be quoted and cited by verifiable page. Two paths — try the file path first, fall back to the browser only for DRM readers that never hand you a file.

**Legitimate access is assumed and is the user's call.** This skill does not bypass paywalls, launch the browser, or log into accounts. If access is unclear, ask before extracting.

## Path 1 — owned file (EPUB / PDF): no browser

The lightweight path. Use it whenever the user actually has the file.

- **PDF:** `pdftotext -layout book.pdf -` (stdout) preserves columns and reading order. Page breaks come through as form-feed (`\f`); convert each to a `[p. N]` marker, counting from the PDF's first page (offset for front matter if the printed numbering differs). `pdfinfo book.pdf` gives the page count for a sanity check.
- **EPUB:** an EPUB is a zip of XHTML. `unzip -o book.epub -d /tmp/ebook` then read the spine order from `content.opf` and concatenate the XHTML files; strip tags for plain text. EPUBs are reflowable, so page numbers only exist if the file carries `epub:type="pagebreak"` anchors — emit `[p. N]` from those when present, otherwise note that the source has no fixed pagination.

Non-DRM web articles and plain HTML don't need this skill at all — use `Read` / `WebFetch` / `pandoc`.

## Path 2 — DRM browser reader: drive chrome-devtools-mcp

For readers that render content only inside an authenticated, sandboxed browser session. This uses the **`chrome-devtools-mcp` plugin** (already installed) instead of a bespoke puppeteer runtime — no `node_modules`, no per-reader scripts.

**Setup (user actions):** the user launches Chrome, logs into the reader, opens the book, and navigates to the first chapter to extract. The MCP connects to that browser. If the MCP manages its own Chrome instance rather than the user's, point it at the user's session via its `--browserUrl` / remote-debugging connection so the authenticated session is the one inspected.

**Extraction loop:**

1. `list_pages` → find the reader tab by URL (see anchor table below).
2. **Scroll the chapter first.** These readers virtualize scrolling and only render visible text into the DOM. Scroll through the chapter (or page through it) so the DOM populates before extracting, or the extract comes back empty/truncated.
3. `evaluate_script` → walk the content frame's DOM: collect text nodes in order, and at each page anchor insert a `[p. N]` marker on its own line (preserve Roman front-matter numerals as-is).
4. Repeat per chapter/spine item; the reader usually shows one spine item at a time.

### Per-reader anchor patterns

The durable knowledge. To support a reader, identify its tab URL, its page-anchor selector, and (if it paginates by chapter) its chapter-nav selector.

| Reader | Tab URL contains | Page-anchor selector | Chapter nav |
|---|---|---|---|
| OverDrive Read | `read.overdrive.com/?d=` | `<a id="page-N">` (`[id^="page-"]`) | `button[id^="seeko-chapter-"]` |
| Kindle Cloud | `read.amazon.com` | divs with `data-kcr-page` | — |
| Scribd | `scribd.com/read/` | `.page[data-pageid]` | — |
| Perlego | `perlego.com/book/` | per-page container; inspect for the page-number attribute | chapter list in side nav |

For a new reader: open devtools on the book page, find the iframe whose `<body>` holds the visible text, note its page-anchor scheme, add a row.

### Cross-origin caveat (known risk)

The reader content is usually a **cross-origin iframe**. `evaluate_script` runs in page context and same-origin policy may block it from reading that iframe's DOM. Test against the target reader before relying on this path. If the MCP can reach the frame (via its frame handling or the `--browserUrl` debug connection), this fully replaces the old puppeteer suite. If a specific reader is unreachable this way, that one reader needs a direct CDP/puppeteer fallback — note it, don't abandon the MCP path for the others.

## Mapping page markers to citations

Each `[p. N]` token is a citation `location` candidate. When quoting, record:

- `location`: the page from the marker (`"p. 42"`, `"pp. 42-44"`, Roman `"p. xii"`).
- `exact_quote`: verbatim from the extract.
- `surrounding_context`: the sentences immediately before and after, from the extract itself — no separate fetch; the extract is the source of truth.
- `retrieval`: `"ebook-extract: <platform-or-file>, <date>"` so provenance shows on audit.

## Invariants

- Never modify the source prose or any citation log directly; extracts are raw material to quote from.
- Never strip `[p. N]` markers when pasting an extract into a source file — page-level citation depends on them.
- Never launch the browser, log in, or bypass access controls; those are user actions.
