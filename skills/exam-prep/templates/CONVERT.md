# CONVERT: Markdown notes to an HTML fragment

Baseline as of 2026-10-20; changes only via `12-retro`.

A hub keeps a copy in `_build/CONVERT.md`. Every converter follows it exactly, and reads
`_build/STYLE.md` too: S11 (figures), S12 (links) and S13 (keep the chassis look) bind every
converter.

You convert ONE reviewed Markdown notes file into one HTML fragment for the notes page. This is a
**faithful format conversion, not a rewrite**: drop, reorder or alter no formula, number,
definition, table cell, trace row or worked-example step. Only the markup changes. The one thing
you add is the section's static figures (see Figures).

Output: `_build/frag/secN.html`, raw HTML with no `<html>`, `<head>` or `<body>`. It holds no tag
that runs code, loads or embeds a document or restyles the page (`<script>`, `<style>`, `<link>`,
`<meta>`, `<base>`, `<iframe>`, `<object>`, `<embed>`, `<form>`, SVG's `<foreignObject>` and
animation tags), no `style=` or `on...=` attribute, no link but `#id`, `http(s)://` or `mailto:`,
and no class outside the component table in `_build/CHASSIS.md`; the chassis CSS already styles
each. No HTML comment but a step-through's FIG marker, and no `<![CDATA[`, `<?...>` or doctype: a
browser reads those differently from the checker. In math, none of `\href`, `\style`, `\class` or
`\cssId`, which MathJax turns into links and styles. `assemble.py` reads every fragment tag by tag
and refuses one that breaks any of these, or that still holds a `TODO-VERIFY`.

## Section wrapper

```html
<section class="note" id="sec-N">
  <h2><span class="n">§N</span> TITLE</h2>
  ... body ...
</section>
```

The file's `# §N Title` heading gives N and TITLE. Everything, figures included, stays inside
this one section: a figure placed outside it shifts every later section's accent color (L17).

## Headings and structure

- `## N.K Title {#sec-N-slug}` becomes `<h3 id="sec-N-slug">N.K Title</h3>`. Use the id the
  Markdown gives (it comes from the backbone's registry); never invent another. A heading's text
  holds no math: fold it to plain text (`O(n^2)`), since the sidebar copies headings as text (L14).
- `###` becomes `<h4>`, keeping any `{#id}` as its id.
- Paragraphs `<p>`; lists `<ul>` or `<ol>` with `<li>`; `**bold**` `<strong>`; `*italic*` `<em>`;
  inline `` `code` `` `<code>`, with `<`, `>` and `&` escaped (`&lt;`, `&gt;`, `&amp;`), as in
  any text that isn't markup.
- A procedure written `Step 1: ...`, `Step 2: ...` becomes `<ol class="steps"><li>...</li></ol>`.
  The CSS draws the "Step N" badge, so drop the literal "Step N:" text. A step with an id keeps it
  on its `<li>`.
- A lettered set, `- a) **<member>:** ... {#set-<set>-a}`, becomes a `<ul>` whose
  `<li id="set-<set>-a">` begins with `<strong>a)</strong>`.
- A Markdown table becomes
  `<div class="tbl-wrap"><table><thead><tr><th>...</th></tr></thead><tbody>...</tbody></table></div>`.
- A fenced code block becomes `<pre><code>...</code></pre>`, with `<`, `>` and `&` escaped.

## Callouts (a few per subsection at most)

- A worked example, the blockquote `> **Worked example N.K: title** {#ex-N-slug}` through its
  last line `> **Conclusion:** ...`, becomes

  ```html
  <details class="callout example wex" id="ex-N-slug">
  <summary><span class="lab">Worked example N.K</span><span class="wex-t">title</span></summary>
  ... the setup, the steps as <ol class="steps">, the <strong>Result:</strong> line and the
  <strong>Conclusion:</strong> line, all inside ...
  </details>
  ```

  Closed by default: no `open` attribute (FB-116).
- A core **definition**: `<div class="callout def"><div class="lab">Definition</div> ... </div>`.
- The subsection's most important formula or rule:
  `<div class="callout key"><div class="lab">Key rule</div> ... </div>`.
- `> **Pitfall:** ...`: `<div class="callout warn"><div class="lab">Pitfall</div> ... </div>`.
- `> **Not on <exam>:** ...` (material kept but out of this exam's scope, FB-121):
  `<div class="callout warn"><div class="lab">Not on <exam></div> ... </div>`.
- `> **Background:** ...` (a derivation no practice question asks for, with that evidence, S20):
  `<div class="callout"><div class="lab">Background</div> ... </div>`, the whole quote inside.
- `**How it's tested:** ...`: `<p class="connects"><strong>How it's tested:</strong> ...</p>`.
- `**Connects to:** ...`: `<p class="connects"><strong>Connects to:</strong> ...</p>`.
- `**Conclusion:** ...` outside an example stays a `<p>` with `<strong>Conclusion:</strong>`.

## Links

- A source citation, `[D5 p.23]`, `[D2 #/14]`, `[HW1 Q2c]` or a section of another document
  `[W1 §2.1]`, becomes `<a class="slink">D5 p.23</a>`, with no href (the sources are local),
  inline where it was. The `§` in a bracket that opens with a document id is that document's,
  never one of the notes' sections: it is no bare reference.
- Every Markdown link `[text](#id)` becomes `<a class="xref" href="#id">text</a>`.
- Never turn a bare §-mention into a link with a guessed id. Keep it as text and list it in your
  report, so the main session wires it.

## Math, for MathJax

- Inline `\( ... \)`, display `\[ ... \]`. Keep the Markdown's LaTeX exactly.
- Plain-text math the Markdown left outside math mode (`n^2`, `O(n^(d+1))`, `e^(-x/T)`) becomes
  `\(n^2\)`, `\(O(n^{d+1})\)`, `\(e^{-x/T}\)`. Use `\le`, `\ge`, `\neq`, `\Rightarrow`, `\alpha`,
  `\infty` and the like.
- A real hyphen-minus `-` inside math, never `−`.
- A literal dollar sign stays as it is (`$10`): MathJax reads only `\( \)` and `\[ \]` here (L15).
- Names in a trace (states, nodes, variables, table rows) stay `<code>`, not math.

## Figures (you draw them)

The Markdown marks each planned figure `<!-- FIG fig-N-slug: description -->`; the backbone's
figure shortlist says whether it is static or a step-through.

- A **static** figure: replace the marker with

  ```html
  <figure id="fig-N-slug"><svg viewBox="0 0 W H" role="img" aria-label="...">...</svg>
  <figcaption>Fig N.K. caption</figcaption></figure>
  ```

  The page wraps the SVG in its scroll box. Inside the SVG use only the chassis's figure classes:
  `bx` (outlined shape), `accbx` (highlighted shape), `fill-surf`, `dash`, `mono`, `mut`, `sm`
  and `acc` (accent text). Lines and arrows use `stroke="currentColor"`; define one arrow
  `<marker>` per figure, its id prefixed with the figure's id (ids are unique on the page). Text
  in an SVG is plain Unicode (α, β, ≤, ∞, ✕), never `\( \)`: MathJax doesn't typeset inside SVG
  (L14). Every node, edge, value and label matches the Markdown exactly. Keep it readable at
  390 px wide: a `viewBox` width of 640 or less.
- A **step-through**: leave the marker as it is. The main session generates it from the checker's
  trace (`06-site`, step 2) in CHASSIS.md's step-through form, and `assemble.py` puts it in
  place.

## Fidelity

Every formula, number, table cell and trace row appears, unchanged, where it was. Don't
summarize. Output only the `<section>`, and report every bare reference you kept as text.
