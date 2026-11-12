# CONVERT: Markdown notes to an HTML fragment

Baseline as of 2026-11-12; changes only via `12-retro`.

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
animation tags), no tag whose text a browser and the checker end in different places (`<title>`,
an SVG one too: its `aria-label` names a figure; `<textarea>`, `<noscript>`, `<xmp>`, `<noembed>`,
`<noframes>`, `<plaintext>`), no `style=` or `on...=` attribute, no link but `#id`, `http(s)://` or `mailto:` (and a
slide-image figure's `img/<name>` source, below),
and no class outside the component table in `_build/CHASSIS.md`; the chassis CSS already styles
each. No `name=` attribute, and every id holds a hyphen, as the registry's do (`sec-`, `ex-`,
`fig-`, `set-`): a bare word or a name can stand for a global the page's scripts read. No HTML
comment but a step-through's FIG marker, and no `<![CDATA[`, `<?...>` or doctype: a browser reads
those differently from the checker. Outside code, none of `\href`, `\style`, `\class`, `\cssId`,
`\data`, `\mmlToken`, `\require` or `\bbox`, which MathJax turns into links, styles and ids.
`assemble.py` reads every fragment tag by tag and refuses one that breaks any of these, or that
still holds a `TODO-VERIFY`.

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

## The concise box

Each subsection's Markdown opens with its concise box (FB-094): a blockquote right under the `##` heading
(after the Depth line, when there is one), headed `> **In short:**`, then one bullet per label that
applies, from **Rule**, **Why**, **Steps**, **Example**, **Trap** and **Answer form**, in that order,
each once, one or two sentences each:

```markdown
> **In short:**
> - **Rule:** the first n integers sum to \(\frac{n(n+1)}{2}\).
> - **Trap:** a range from a to b has \(b - a + 1\) terms.
```

It becomes, in the same place, directly inside the section:

```html
<div class="concise"><ul>
  <li><strong>Rule:</strong> the first n integers sum to \(\frac{n(n+1)}{2}\).</li>
  <li><strong>Trap:</strong> a range from a to b has \(b - a + 1\) terms.</li>
</ul></div>
```

The "In short" heading is dropped (the box's look says it); each item opens with its label and
colon in `<strong>`, and its text keeps its links, citations, code and math. One box a subsection,
never before the section's first `h3`, never inside another block, no class `rv` on it (the Review
view shows every box). `assemble.py` refuses a box anywhere else, one holding anything but that
one list, an item that opens with no label or another word, and a label repeated or out of order.

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
- `> **Unverified:** ...` (material added at the student's request without extract or review,
  FB-013): `<div class="callout warn"><div class="lab">Unverified</div> ... </div>`.
- `> **Background:** ...` (a derivation no practice question asks for, with that evidence, S20):
  `<div class="callout"><div class="lab">Background</div> ... </div>`, the whole quote inside.
- **`.rv`, the Review view's marker.** A worked example or a Pitfall the notes tag for the Review
  view (CHASSIS.md) carries `.rv` in its attribute block: `> **Worked example N.K: title**
  {#ex-N-slug .rv}`, and `> **Pitfall:** {.rv} ...`, the block right after the label. It becomes
  class `rv` on the block itself, `<details class="callout example wex rv" id="ex-N-slug">` and
  `<div class="callout warn rv">`, and the block stays directly inside the section, never nested in
  a list or another callout. Nothing else takes it: not a `Not on <exam>` or `Unverified` callout,
  a heading, a paragraph or a list (Must-know lists are in the view, untagged, unless a banner
  takes their section out), nor a block in a section whose `Not on <exam>` or `Unverified` banner
  comes before its first `##` subsection heading, which becomes its first `h3` (CHASSIS.md). `assemble.py` refuses class `rv` anywhere else, and on any block when PLAN.md gives the Review
  view no minutes; `fidelity.py` compares the marker like an id.
- `**How it's tested:** ...`: `<p class="connects"><strong>How it's tested:</strong> ...</p>`.
- `**Connects to:** ...`: `<p class="connects"><strong>Connects to:</strong> ...</p>`.
- `**Depth:** ...`, the depth label that opens a subsection under its heading (S33):
  `<p class="connects"><strong>Depth:</strong> ...</p>`, its citation or `(inferred: ...)` kept.
- `**Conclusion:** ...` outside an example stays a `<p>` with `<strong>Conclusion:</strong>`.

## Links

- A source citation, `[D5 p.23]`, `[D2 #/14]`, `[HW1 Q2c]` or a section of another document
  `[W1 §2.1]`, becomes `<a class="slink">D5 p.23</a>`, with no href, inline where it was.
  `assemble.py` adds the rest: a source key, the page's last section, with a row per code the page
  cites (from `MANIFEST.md`), and on each citation an href to its code's row (`#src-D5`, from its
  first word) and a title naming the file. A code matches its row in any case (`Ed #12` links to
  the row `ED`), and the key uses the row's spelling. A code with no `MANIFEST.md` row fails the
  build. The `§` in a bracket that opens with a document id is that document's,
  never one of the notes' sections: it is no bare reference.
- Every Markdown link `[text](#id)` becomes `<a class="xref" href="#id">text</a>`. A link to a
  figure, `[Fig 2.1](#fig-2-triangle)`, is one too: on the page a click pins a copy of the figure
  beside the text (CHASSIS.md, C5), so a worked example can name a figure from sections back.
- A link to a section of another published page, `[text](<url>#id)`, becomes `<a href="<url>#id" target="_blank" rel="noopener">text</a>`, with
  no class: `a.xref` is for in-page links only, which `linkcheck.py --html` resolves and
  `fidelity.py` compares with the Markdown's `#id` links. The URL is `https://`, from STATUS.
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
figure shortlist says whether it is static, a step-through or a slide image.

- A **static** figure: replace the marker with

  ```html
  <figure id="fig-N-slug"><svg viewBox="0 0 W H" role="img" aria-label="...">...</svg>
  <figcaption>Fig N.K. caption</figcaption></figure>
  ```

  The page wraps the SVG in its scroll box. Inside the SVG use only the chassis's figure classes:
  `bx` (outlined shape), `accbx` (highlighted shape), `fill-surf`, `dash`, `mono`, `mut`, `sm`
  and `acc` (accent text). Lines and arrows use `stroke="currentColor"`; a figure that draws arrows
  defines one arrow `<marker>`, its id prefixed with the figure's id (ids are unique on the page);
  an undirected graph needs none. Draw the edges first and the nodes over them, each node filled
  (`fill-surf` or `accbx`), so no edge shows through a node. Text
  in an SVG is plain Unicode (α, β, ≤, ∞, ✕), never `\( \)`: MathJax doesn't typeset inside SVG
  (L14). Every node, edge, value and label matches the Markdown exactly. Below 560 px the page
  shows a figure at least 460 px wide and scrolls it sideways in its box, so a `viewBox` width of
  640 or less keeps the labels legible there.
- A **slide-image figure**, only where the Markdown marks one `<!-- FIG fig-N-slug: slide image
  of <code> <place>: description -->`: a reference picture too costly to redraw (a component photo,
  a dense schematic, FB-115), cropped from a lecture slide by the main session into
  `_build/img/fig-N-slug.png` (or `.jpg`, `.webp`; 1 MB at most). Replace the marker with

  ```html
  <figure id="fig-N-slug"><img src="img/fig-N-slug.png" alt="what the picture shows, in words">
  <figcaption>Fig N.K. caption <a class="slink">D5 p.23</a></figcaption></figure>
  ```

  One `img` directly in the figure, nothing drawn beside it, `alt` text that says what the slide
  shows, and the caption ending in its source citation in the notes' own form. `assemble.py`
  embeds the file in the page as a data URI and the chassis keeps it inside the column; it refuses
  an image anywhere else (outside a section's figure, in the map or a step-through), with no alt
  text, with no citation in its caption, with any other source (a `data:` URI or a URL written
  in), or whose file is missing, over 1 MB, or not the type its name says.
- A **step-through**: leave the marker as it is, on its own between blocks, never inside a tag,
  an attribute or code, and with no `<` or `>` in its text. The main session generates it from the checker's trace (`06-site`, step
  2) in CHASSIS.md's step-through form, and `assemble.py` puts it in place.

## Fidelity

Every formula, number, table cell and trace row appears, unchanged, where it was. Don't
summarize. Output only the `<section>`, and report every bare reference you kept as text.
