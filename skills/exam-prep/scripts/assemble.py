#!/usr/bin/python3 -I
"""Assemble the notes page, _build/notes.html, from the hub root.

  assemble.py [--root DIR]

Reads the hub's chassis copy, _build/chassis.html (from the skill's templates/notes-chassis.html,
its {{...}} placeholders filled), and its _build/CHASSIS.md (the component table), and puts into
the chassis:
  - the exam-day map, _build/frag/examnav.html, at `<!-- EXAM-DAY MAP -->`;
  - one fragment per notes file, _build/frag/secN.html for notes/NN-<slug>.md (N = int(NN)), in
    order, at `<!-- SECTIONS -->`; each is one `<section class="note" id="sec-N">`;
  - each step-through figure, _build/frag/step-<fig-id>.html, in place of the
    `<!-- FIG <fig-id>: ... -->` marker a converter left, and every _build/frag/*.js in a
    `<script>` at `<!-- FIGURE SCRIPTS -->`;
  - one accent rule per section, light and dark, at `/* SECTION ACCENTS */`, cycling the
    chassis's seven hues;
  - the source key, one last section after the notes' (sec-<last N + 1>, so it sits in the rail
    like any section): a table with one row per code the page cites, read from the hub's
    MANIFEST.md (its Doc id, File, Notes and optional By columns, found by header name). A row
    has three columns at most, so it fits a phone: the code; what the source is (its Notes up to
    the first `;`, never a remark after it or the Scope) with the file's base name under it in muted
    small text (`.mut.sm`; with that part empty, the file line alone); and, when any cited row has a By cell, who made it (a Made by column,
    blank for a row without one); a table with no By column reads as before. Each
    a.slink, in a section, a step-through or the map, gets href="#src-<code>", where the code is
    its text's first word (D5 from `D5 p.23`, HW1 from `HW1 Q2c`), and a title holding its row's
    text. A code matches its row whatever its case (`Ed #12` finds the row ED), and the link and the
    key use the row's own spelling, so the two always meet. The row's id is src- and the code, each character other than an ASCII letter, digit or
    hyphen written as _<hex>_ (HW1.S is src-HW1_2e_S): one token, and distinct codes stay
    distinct. A code with a space can't be cited, since a citation's first word is its code. A
    page that cites nothing gets no key and needs no MANIFEST.md.

Each fragment is read tag by tag. Exit 1, writing nothing, when a placeholder or marker is wrong, a
fragment is missing or isn't one section with its id, a fragment holds a tag that runs code, loads
or embeds a document or restyles the page (script, style, link, base, iframe and the like), an
on...=, style= or name= attribute, an id with no hyphen (a bare word can stand for a global the
page's scripts read), a link that isn't #id, http(s) or mailto, a class outside the
component table in the hub's _build/CHASSIS.md (a step-through may add fs-* hook classes), markup
a browser and Python's parser read differently (a comment other than a FIG marker, <![CDATA[,
<?...>, a doctype, a tag, quote or comment left open at its end, a raw-text tag such as
<textarea> or <noscript>, anything but phrasing tags nested strictly inside <pre> or <code>, a
table part outside its parent or text or a tag directly inside a table, row group or row), one
of MathJax's \\href, \\style, \\class, \\cssId, \\data, \\mmlToken, \\require or \\bbox
outside code (all of a fragment's text read as one string, and the sections again with their
step-throughs in place, since MathJax and a browser join text across tags this parser keeps
apart), or a TODO-VERIFY left from 05-verify; when a citation names a code MANIFEST.md has no row for
(naming the code and the fragment), a citation is empty or has an href of its own, MANIFEST.md
is missing or its table has no Doc id or File column or repeats a code (in any case), or the key's
own text fails the fragment checks; when a section, the map or a step-through holds what a writer
agent left behind (FB-095, naming the fragment and its line): tool-call markup, as a tag or as text, or a
skill rule id in parentheses in the student's text, `(FB-123)` or `(C4)` right after CHASSIS or
rule (a bare `(C1)` is a capacitor or a case as often as a rule), code and math exempt; a bare
`(S12)`, `(L07)` or `(K02)` only warns (one WARN line each, fragment and line), since a course
writes a state, an inductor or a lecture that way; when a FIG marker holds a < or >, sits inside a
tag, an attribute or code or outside a section (in the exam-day map or a step-through), is left
with no step-through, or a step-through file isn't one <figure id="<fig-id>"> or isn't placed
exactly once.

A concise box (CONVERT.md) is a div.concise directly in its section, opening its subsection (right
after the h3, or after its Depth line), one a subsection, holding one <ul> whose items each open
with <strong>Label:</strong>, the labels from BOX_LABELS, each once and in that order; anything
else is refused. A slide-image figure is a <figure id="fig-..."> holding one <img> and no SVG, its
alt text said and its figcaption holding a source citation; its src is img/<name>.png, .jpg or
.webp, a file in _build/img/ that the page embeds as a data URI, refused when missing, over IMG_MAX
bytes, or not the type its name says. An <img> anywhere else (outside a section's figure, in the
map or a step-through) or with any other src is refused.

The Review view (CHASSIS.md): the hub root's PLAN.md line `- Review view: <N> minutes of reading`
keeps the page's Review / Full notes toggle (the chassis's `<!-- REVIEW TOGGLE -->` blocks), and
the build fails when the view's words, read at READING_RATE words a minute, take more than N
minutes (both numbers printed, and the remedy: untag from the last ranked subsection up, or, with
no rv tag left, new minutes, asked of the student or set and logged as 07-cheatsheet's Tag the
review opening says); the map's cram block is left out of that count. `- Review view:
none: <why>`, or no such line, strips the toggle and refuses any class rv. Class rv goes only on
a worked example (details.callout.example.wex) or a Pitfall (div.callout.warn whose label is
Pitfall), each directly inside its section, and never in a section whose Not on <exam> or
Unverified banner comes before its first h3: the view leaves such a section out whole, its
Must-know list and its words included.

The cram block (K02): when practice/cram-order.md exists, it must pass cram_check.py against the
assembled page's ids, and its tiers, rows, Skip line and Out of time line are rendered into a
div.ecram at the start of the map's .ebody on every build, the map opened (`open`); its links
become `#id`. Inline Markdown in those lines is escaped, with **bold**, `code`, \\( math \\) and
[text](URL#id) rendered; anything else is refused. A cram order written before S33, no row with a
depth label, renders its rows without one and prints one WARN line naming 10-polish (cram_check.py's
PRE_S33, FB-015); one with some rows labelled needs them all. A row's needs list (FB-193), split off by
cram_check.py's own parser, shows after the row as `· needs §x.y` links; the Read already line stays
out of the map. The hand-written map may hold no cram block (an
.ecram, a `Tier N:` group, a Skip or Out of time line) and no open attribute. Stdlib only."""
import argparse
import base64
import html
import os
import posixpath
import re
import sys
from collections import Counter
from html.parser import HTMLParser

# cram_check.py sits beside this script; -I leaves the script's directory off sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cram_check  # noqa: E402

MARKERS = ("<!-- EXAM-DAY MAP -->", "<!-- SECTIONS -->", "<!-- FIGURE SCRIPTS -->",
           "/* SECTION ACCENTS */")
NOTE = re.compile(r"(\d+)-.*\.md")
PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}")
CSS_CLASS = re.compile(r"\.([A-Za-z][\w-]*)")
# No < or > inside: a parser without the HTML5 comment rules ends `<!-- FIG x -- >` early, and
# then the raw text and the parser count the markers differently, which check_fragment refuses.
FIG = re.compile(r"<!--\s*FIG\s+(fig-[\w-]+)\b[^<>]*?-->")
STEP_FILE = re.compile(r"step-(.+)\.html")
# Tags no fragment holds: they run code, load or embed another document, or change the page
# itself (SVG's animation tags can rewrite a link; foreignObject embeds HTML).
CODE_INNER = {"code", "span", "a", "b", "i", "em", "strong", "var", "sub", "sup", "mark", "small", "br"}
# A browser moves text or a tag found directly inside a table, a row group or a row out in front
# of the table (foster parenting), joining text this parser read apart: tables nest strictly, as
# CONVERT.md writes them, each part inside its own parent.
TABLE_PARENTS = {"caption": {"table"}, "colgroup": {"table"}, "col": {"table", "colgroup"},
                 "thead": {"table"}, "tbody": {"table"}, "tfoot": {"table"},
                 "tr": {"table", "thead", "tbody", "tfoot"}, "td": {"tr"}, "th": {"tr"}}
FOSTER = {"table", "thead", "tbody", "tfoot", "tr", "colgroup"}
VOID = {"br", "wbr", "img", "hr"}
# The raw-text and RCDATA tags (textarea, title, xmp, noscript, noembed, noframes, plaintext) are
# where html.parser and a browser disagree on where the text ends, so markup hides in them.
FORBIDDEN_TAGS = {"script", "style", "link", "meta", "base", "iframe", "frame", "frameset",
                  "object", "embed", "form", "template", "foreignobject", "animate",
                  "animatemotion", "animatetransform", "set", "textarea", "title", "xmp", "noscript",
                  "noembed", "noframes", "plaintext"}
URL_ATTRS = {"href", "src", "xlink:href", "action", "formaction", "srcset", "poster", "data",
             "background", "ping"}
SAFE_URL = re.compile(r"(#|https?://|mailto:)", re.I)
HOOK = re.compile(r"fs-[\w-]+")
# A slide-image figure's <img src>: a file in the hub's _build/img/, which the page embeds as a data
# URI (the one relative link a fragment holds), and the bytes each type must start with.
IMG_SRC = re.compile(r"img/[\w-]+\.(png|jpe?g|webp)")
IMG_TYPES = {"png": ("image/png", b"\x89PNG\r\n\x1a\n"), "jpg": ("image/jpeg", b"\xff\xd8\xff"),
             "jpeg": ("image/jpeg", b"\xff\xd8\xff"), "webp": ("image/webp", b"RIFF")}
IMG_MAX = 1_000_000  # bytes a slide image may take: a crop, not a deck
# The concise box's labels (CONVERT.md), each at most once and in this order.
BOX_LABELS = ("Rule", "Why", "Steps", "Example", "Trap", "Answer form")
FIG_COMMENT = re.compile(r"\s*FIG\s+fig-[\w-]+\b[^<>]*")
# MathJax's html extension, autoloaded, turns these into links, styles, classes and ids that the
# tag walk never sees; MathJax leaves code and pre alone.
TEX_HTML = re.compile(r"\\(?:href|style|class|cssId|data|mmlToken|require|bbox)(?![A-Za-z])")
KEY_TITLE = "Source key"
# Words a minute for the Review view's budget: an unmeasured estimate for dense study notes
# (CHASSIS.md says how math and code count).
READING_RATE = 150
REVIEW_LINE = re.compile(r"^- Review view:(.*)$")
# A banner label that takes a section out of the Review view when it comes before the first h3.
OUT_LABEL = re.compile(r"Not on \S.*|Unverified")
TOGGLE = re.compile(r"<!-- REVIEW TOGGLE -->(.*?)<!-- /REVIEW TOGGLE -->", re.S)
CRAM = os.path.join("practice", "cram-order.md")
DEPTH = cram_check.DEPTH  # one pattern, so cram_check.py at step 7.1 refuses what this refuses
CRAM_ROW = re.compile(r"^\d+\. \[(§[\d.]+ [^\]]+)\]\([^)\s#]*#([^)\s]+)\) \(\d+ min\): (.*)$")
# What one cram-order line may hold besides text: math, code, bold and notes links.
INLINE = re.compile(r"\\\((.*?)\\\)|`([^`]+)`|\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)\s]*)\)")
UNRENDERED = re.compile(r"[*`\[\]\\]|(?<!\w)_|_(?!\w)|<[A-Za-z/!?]")
# What a writer agent leaves behind in a fragment, by line: its tool-call markup, as a tag or as
# text, and a skill rule id in parentheses (STYLE's S, the feedback log's FB, the lessons' L, the
# backlog's K, CHASSIS's C). Markup, FB and C are refused; a bare (C1) is as often a capacitor, a
# case or a condition as a rule, so C counts only right after CHASSIS or rule. A bare S, L or K id
# only warns (RULE_ID_WARN): a course writes a state (S1), an inductor (L1) or a lecture (L3) so,
# and a wrong refusal mid-exam costs more than a stray id left on the page.
TOOL_PREFIX = "antml" + ":"
TOOL_TAGS = {"invoke", "parameter", "content"}
TOOL_TEXT = re.compile(r"</invoke>|<invoke\s|</content>|<parameter\s|</parameter>|</?" + TOOL_PREFIX + r"\w")
RULE_ID = re.compile(r"\(FB-\d+\)|\b(?:CHASSIS|[Rr]ule)\s*\(C\d+\)")
RULE_ID_WARN = re.compile(r"\((?:S|L|K)\d+\)")
MATH = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]", re.S)
TREE_VOID = {"br", "wbr", "img", "hr", "col", "input", "meta", "link", "source", "area", "base",
             "embed", "track", "param"}


def source_id(code):
    """The source key row's id for a citation code: src-<code>, each character outside ASCII
    letters, digits and - written as _<hex>_."""
    return "src-" + "".join(c if c.isascii() and (c.isalnum() or c == "-") else f"_{ord(c):x}_"
                            for c in code)


def manifest_key(path):
    """{code: (file base name, what it is, who made it)} from MANIFEST.md's table, its columns
    found by header name: what it is is the row's Notes up to its first `;` (Notes is
    `<what it is>[; <remark>]`, and the remark stays off the page), blank when that part is empty (a
    Scope such as `in, PDF pp.1-9` says nothing of what a source is); who made it is the
    By cell (staff, classmate, textbook, student or free text), empty with no By column. ValueError
    when the table has no Doc id or File column, or repeats a code."""
    rows, cols = {}, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.lstrip().startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cols is None:
                if cells and cells[0].lower().startswith("doc"):
                    cols = {name.lower(): i for i, name in enumerate(cells)}
                    if "file" not in cols:
                        raise ValueError("the table has no File column")
                continue
            code = cells[0].strip("`").strip()
            if re.fullmatch(r"[\s:-]*", code):
                continue

            def cell(name):
                i = cols.get(name)
                return cells[i].replace("`", "").strip() if i is not None and i < len(cells) else ""
            twin = next((c for c in rows if c.casefold() == code.casefold()), None)
            if twin is not None:
                raise ValueError(f"two rows for {code}" + (f" (and {twin}: a citation's code matches "
                                                           "a row in any case)" if twin != code else ""))
            base = posixpath.basename(cell("file"))
            rows[code] = (base, cell("notes").split(";", 1)[0].strip(), cell("by"))
    if cols is None:
        raise ValueError("has no table under a `| Doc id | File | ... |` header")
    return rows


def key_text(code, row):
    """A key row's text, as a citation's title shows it."""
    base, what, by = row
    return f"{code}: {base}" + (f", {what}" if what else "") + (f", by {by}" if by else "")


class Citations(HTMLParser):
    """Each a.slink's start tag (its offset, its raw length, its attributes) and its text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.open = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "a" and "slink" in (dict(attrs).get("class") or "").split():
            self.open = [self.getpos(), len(self.get_starttag_text()), attrs, []]
            self.found.append(self.open)

    def handle_data(self, data):
        if self.open:
            self.open[3].append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self.open = None


def link_citations(name, text, key, cited, problems):
    """text with each a.slink given href="#src-<code>" and its key row's text as a title; the
    codes it cites are added to cited (a dict kept in order). key is MANIFEST.md's rows, or None
    when it is missing (one problem says so, not one per citation)."""
    rows = {c.casefold(): c for c in key} if key is not None else {}
    p = Citations()
    try:
        p.feed(text)
        p.close()
    except (AssertionError, NotImplementedError):
        return text  # its own check has refused it
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    out, last = [], 0
    for (line, col), size, attrs, words in p.found:
        at = starts[line - 1] + col
        label = " ".join("".join(words).split())
        code = label.split(" ")[0] if label else ""
        if not code:
            problems.append(f"{name}: an empty citation (a.slink with no text)")
            continue
        if any(k == "href" for k, _ in attrs):
            problems.append(f"{name}: citation `{label}` has an href of its own (assemble.py links "
                            "each to the source key)")
            continue
        # The row's spelling, so `Ed #12` links to the row ED: the key's ids use it too.
        code = rows.get(code.casefold(), code)
        cited.setdefault(code, None)
        if key is not None and code not in key:
            problems.append(f"{name}: citation `{label}` names {code}, which has no row in MANIFEST.md")
            continue
        tag = "<a" + "".join(f' {k}="{html.escape(v, quote=True)}"' if v is not None else f" {k}"
                             for k, v in attrs if k != "title")
        title = key_text(code, key[code]) if key is not None else code
        tag += f' href="#{source_id(code)}" title="{html.escape(title, quote=True)}">'
        out += [text[last:at], tag]
        last = at + size
    return "".join(out) + text[last:]


def source_key(n, key, cited):
    """The source key: section n, one table row per cited code, in MANIFEST.md's order: the code,
    what it is with the file's base name under it (muted, small), and a Made by column when any
    cited row has a By cell. Three columns at most, so the table fits a phone's width."""
    shown = [(code, row) for code, row in key.items() if code in cited]
    made_by = any(row[2] for _, row in shown)
    rows = []
    for code, row in shown:
        base, what, by = (html.escape(x) for x in row)
        file_line = f'<span class="mut sm">{base}</span>'
        rows.append(f'      <tr id="{source_id(code)}"><td><code>{html.escape(code)}</code></td>'
                    f"<td>{what + '<br>' if what else ''}{file_line}</td>"
                    + (f"<td>{by}</td>" if made_by else "") + "</tr>")
    return (f'<section class="note" id="sec-{n}">\n'
            f'  <h2><span class="n">§{n}</span> {KEY_TITLE}</h2>\n'
            "  <p>Every citation on this page links to its row here: the source's code, what it is"
            + (" and its file, and who made it" if made_by else " and its file") + ".</p>\n"
            '  <div class="tbl-wrap"><table>\n'
            "    <thead><tr><th>Code</th><th>What it is</th>"
            + ("<th>Made by</th>" if made_by else "") + "</tr></thead>\n"
            "    <tbody>\n" + "\n".join(rows) + "\n    </tbody>\n  </table></div>\n</section>")


# The chassis's seven section hues: (light accent, light highlight, dark accent, dark highlight
# or None for the dark accent at DARK_HL_MIX). Every dark rule sets its own highlight (FB-111): one that
# kept the light band let the bold-term highlight all but vanish on the dark background.
HUES = [
    ("#0b6e8f", "rgba(11,110,143,.17)", "#4cbbda", None),
    ("#277a4d", "rgba(47,143,91,.19)", "#5fc088", "rgba(95,192,136,.20)"),
    ("#6244bb", "rgba(109,70,194,.17)", "#ab92e8", None),
    ("#215c9c", "rgba(37,99,166,.17)", "#6ea8e6", None),
    ("#b5591a", "rgba(192,101,29,.19)", "#e3925f", "rgba(227,146,95,.20)"),
    ("#a93574", "rgba(178,58,122,.17)", "#e67aad", None),
    ("#3a49a8", "rgba(63,81,181,.18)", "#8f99ee", None),
]
DARK_HL_MIX = "color-mix(in srgb,{} 26%,transparent)"


def accents(n):
    """The per-section accent rules for n sections."""
    sel = ".wrap section.note:nth-of-type({})"
    light = ["  .wrap section.note{--sec-accent:var(--accent);--sec-accent-hl:rgba(11,110,143,.16)}"]
    dark = []
    for k in range(1, n + 1):
        la, lh, da, dh = HUES[(k - 1) % len(HUES)]
        light.append(f"  {sel.format(k)}{{--sec-accent:{la};--sec-accent-hl:{lh}}}")
        dark.append(f"{sel.format(k)}{{--sec-accent:{da};--sec-accent-hl:{dh or DARK_HL_MIX.format(da)}}}")
    media = ["  @media (prefers-color-scheme:dark){"]
    media += [f'    :root:not([data-theme="light"]) {d}' for d in dark] + ["  }"]
    forced = [f'  :root[data-theme="dark"] {d}' for d in dark]
    return "\n".join(light + media + forced).lstrip()


def chassis_classes(chassis):
    """Every class the chassis's CSS defines."""
    css = "".join(re.findall(r"<style>(.*?)</style>", chassis, re.S))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return set(CSS_CLASS.findall(re.sub(r"\{[^{}]*\}", "{}", css)))


def vocabulary(chassis_md):
    """The classes CHASSIS.md's component table names: each `.class` in a row's first cell."""
    m = re.search(r"^## Components.*?(?=^## |\Z)", chassis_md, re.M | re.S)
    rows = [r for r in m.group(0).splitlines() if r.startswith("|")] if m else []
    return {c for r in rows for tok in re.findall(r"`([^`]*)`", r.split("|")[1])
            for c in CSS_CLASS.findall(tok)}


class Fragment(HTMLParser):
    """A fragment's tags, attributes and classes (character references in attribute values
    decoded, names lower-cased, escaped text left as text). Comments, CDATA sections, processing
    instructions and declarations are where Python's parser and a browser part ways (a browser
    ends `<![CDATA[` and `<!-->` at the first `>`), so all but a FIG marker are refused."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.attrs, self.urls, self.classes, self.bare = set(), set(), [], set(), []
        self.markup, self.code, self.text, self.figs, self.table = [], [], [], 0, []
        self.images = []  # each <img>'s src

    def handle_comment(self, data):
        if FIG_COMMENT.fullmatch(data):
            if not self.code:
                self.figs += 1
        elif re.match(r"\s*FIG\b", data):
            self.markup.append(f"a FIG marker with a < or > in its text, or no fig- id: <!--{data[:30]}-->")
        else:
            self.markup.append(f"<!--{data[:30]}-->")

    def unknown_decl(self, data):
        self.markup.append(f"<![{data[:30]}]>")

    def handle_decl(self, decl):
        self.markup.append(f"<!{decl[:30]}>")

    def handle_pi(self, data):
        self.markup.append(f"<?{data[:30]}>")

    def handle_data(self, data):
        # MathJax reads one string on across <wbr>, <br> and comments, and a browser drops a stray
        # end tag or a table tag outside a table, so text this parser saw apart can be one string
        # on the page: the macro check reads all the text outside code as one.
        if not self.code:
            self.text.append(data)
        if self.table and self.table[-1] in FOSTER and data.strip():
            self.markup.append(f"text directly inside <{self.table[-1]}>")

    def handle_endtag(self, tag):
        if tag in TABLE_PARENTS or tag == "table":
            if tag == "col":
                pass
            elif self.table and self.table[-1] == tag:
                self.table.pop()
            else:
                self.markup.append(f"</{tag}> where " + (f"<{self.table[-1]}> is open" if self.table else "no table is open"))
        if self.code and tag not in VOID:
            if self.code[-1] == tag:
                self.code.pop()
            else:
                self.markup.append(f"</{tag}> inside <{self.code[-1]}>")

    def handle_starttag(self, tag, attrs):
        # A browser ends a <pre> or <code> early at an ancestor's end tag or a block's start tag,
        # where this parser would still count the text as code and skip the macro check: inside
        # code, only phrasing tags, nested strictly.
        top = self.table[-1] if self.table else None
        if tag in TABLE_PARENTS and top not in TABLE_PARENTS[tag]:
            self.markup.append(f"<{tag}> outside a <{'>, <'.join(sorted(TABLE_PARENTS[tag]))}>")
        elif tag not in TABLE_PARENTS and top in FOSTER:
            self.markup.append(f"<{tag}> directly inside <{top}>")
        if (tag in TABLE_PARENTS or tag == "table") and tag != "col":
            self.table.append(tag)
        if self.code and tag not in CODE_INNER:
            self.markup.append(f"<{tag}> inside <{self.code[-1]}>")
        elif (self.code or tag in ("code", "pre")) and tag not in VOID:
            self.code.append(tag)
        if tag in FORBIDDEN_TAGS:
            self.tags.add(tag)
        if tag == "img":
            self.images.append(dict(attrs).get("src") or "")
        for name, value in attrs:
            value = value or ""
            # A name (an <img name=currentScript>) or a bare-word id shadows a property of the
            # document or the window that a script reads, MathJax's loader's among them.
            if name.startswith("on") or name in ("style", "name"):
                self.attrs.add(name)
            elif name == "id" and "-" not in value:
                self.bare.append(value)
            elif name in URL_ATTRS and not SAFE_URL.match(value.strip()) \
                    and not (tag == "img" and name == "src" and IMG_SRC.fullmatch(value)):
                self.urls.append(f'{name}="{value}"')
            elif name == "class":
                self.classes.update(value.split())


class Leftovers(HTMLParser):
    """Tool-call tags anywhere, and the text outside code as (line, text) runs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.runs, self.code = [], [], 0

    def tool(self, tag, raw):
        if tag in TOOL_TAGS or tag.startswith(TOOL_PREFIX):
            self.tags.append((self.getpos()[0], raw))

    def handle_starttag(self, tag, attrs):
        self.tool(tag, f"<{tag}>")
        if tag in ("code", "pre"):
            self.code += 1

    def handle_endtag(self, tag):
        self.tool(tag, f"</{tag}>")
        if tag in ("code", "pre") and self.code:
            self.code -= 1

    def handle_data(self, data):
        if not self.code:
            self.runs.append((self.getpos()[0], data))


def leftovers(name, text, problems, warnings=None):
    """Append what a writer agent left in one fragment (TOOL_TAGS, TOOL_TEXT, RULE_ID) to problems,
    and each bare S, L or K id (RULE_ID_WARN) to warnings when it is a list, by line; text in code
    or in \\( \\) or \\[ \\] math is exempt, and a rule id is read within one run of text, so a
    citation in parentheses, `(<a class="slink">L3</a>)`, is no rule id."""
    p = Leftovers()
    try:
        p.feed(text)
        p.close()
    except (AssertionError, NotImplementedError):
        return  # its own check has refused it
    found = [(line, f"tool-call markup {raw}") for line, raw in p.tags]
    # One string, its runs apart by a NUL no pattern crosses, so math split by a tag is still math.
    joined, starts = "", []
    for line, data in p.runs:
        starts.append((len(joined), line, data))
        joined += data + "\0"
    joined = MATH.sub(lambda m: re.sub(r"[^\n\0]", " ", m.group(0)), joined)
    maybe = []
    for pattern, what, into in ((TOOL_TEXT, "tool-call markup", found), (RULE_ID, "a skill rule id", found),
                                (RULE_ID_WARN, "a skill rule id", maybe)):
        for m in pattern.finditer(joined):
            at, line, data = max((s for s in starts if s[0] <= m.start()), key=lambda s: s[0])
            into.append((line + data.count("\n", 0, m.start() - at), f"{what} {m.group(0).strip()}"))
    for line, what in sorted(found):
        problems.append(f"{name}:{line}: {what} left by a writer agent: take it out "
                        "of the notes and rebuild")
    if warnings is not None:
        warnings += [f"{name}:{line}: {what}, if a writer agent left it (a state, an inductor or a "
                     "lecture written so is fine): take it out of the notes" for line, what in maybe]


def tex_macros(text):
    """The MathJax macros that make HTML in an HTML text, outside code."""
    f = Fragment()
    f.feed(text)
    f.close()
    return TEX_HTML.findall("".join(f.text))


def check_fragment(name, text, allowed, problems, hooks=False, markers=True, images=False):
    """Append what CONVERT.md forbids in one fragment to problems; markers=False for one where a
    FIG marker is never placed (the exam-day map, a step-through); images=True for a section, the
    one fragment whose slide-image figures get their <img> embedded."""
    f = Fragment()
    try:
        f.feed(text)
    except (AssertionError, NotImplementedError):  # html.parser's on a malformed <![ (before 3.10: the latter)
        problems.append(f"{name}: markup a browser reads differently (a <![ section html.parser can't read)")
        return
    if "<" in f.rawdata:  # close() drops it unread; a browser reads on into the next fragment
        problems.append(f"{name}: a tag, quote or comment left open at its end runs into the page")
    f.close()
    if f.table:
        f.markup.append(f"<{f.table[-1]}> never closed")
    if f.tags:
        problems.append(f"{name}: forbidden tags: {', '.join(sorted(f.tags))} (CONVERT.md)")
    if f.attrs:
        problems.append(f"{name}: forbidden attributes: {', '.join(sorted(f.attrs))} (CONVERT.md)")
    if f.urls:
        problems.append(f"{name}: links that aren't #id, http(s) or mailto: {', '.join(f.urls[:3])}")
    if f.bare:
        problems.append(f"{name}: ids with no hyphen (a bare word can stand for a global the page's "
                        f"scripts read, or a chassis id): {', '.join(f.bare[:3])}")
    if f.markup:
        problems.append(f"{name}: markup a browser reads differently (only a FIG marker comment "
                        f"may stay): {', '.join(f.markup[:3])}")
    tex = TEX_HTML.findall("".join(f.text))
    if tex:
        problems.append(f"{name}: MathJax macros that make HTML: {', '.join(sorted(set(tex)))}")
    if len(FIG.findall(text)) != f.figs:
        problems.append(f"{name}: a FIG marker inside a tag, an attribute or code: a marker stands "
                        f"alone (CONVERT.md)")
    elif f.figs and not markers:
        problems.append(f"{name}: a FIG marker, which only a section's text holds (it is never placed here)")
    unknown = sorted(c for c in f.classes - allowed if not (hooks and HOOK.fullmatch(c)))
    if unknown:
        problems.append(f"{name}: classes outside CHASSIS.md's component table: {', '.join(unknown)}")
    if "TODO-VERIFY" in text:
        problems.append(f"{name}: a TODO-VERIFY is left (05-verify isn't done)")
    if f.images and not images:
        problems.append(f"{name}: an <img>, which only a section's slide-image figure holds (CONVERT.md)")


class Tree(HTMLParser):
    """A fragment as nested dicts ({"tag", "attrs", "kids", "parent"}; text as str kids), for the
    Review view's rules. Fragments passed check_fragment, so tags nest as written."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = {"tag": "#root", "attrs": {}, "kids": [], "parent": None}
        try:
            self.feed(text)
            self.close()
        except (AssertionError, NotImplementedError):
            pass  # its own check has refused it

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": {k: v or "" for k, v in attrs}, "kids": [], "parent": self.cur}
        self.cur["kids"].append(node)
        if tag not in TREE_VOID:
            self.cur = node

    def handle_endtag(self, tag):
        n = self.cur
        while n["parent"] is not None and n["tag"] != tag:
            n = n["parent"]
        if n["parent"] is not None:
            self.cur = n["parent"]

    def handle_data(self, data):
        self.cur["kids"].append(data)


def classes_of(node):
    return set(node["attrs"].get("class", "").split())


def elements(node):
    """node and every element under it, in document order."""
    yield node
    for k in node["kids"]:
        if isinstance(k, dict):
            yield from elements(k)


def text_of(node, skip=frozenset()):
    """node's text, an SVG's left out (a figure's labels are no reading), and any element with a
    class in skip."""
    if node["tag"] == "svg" or classes_of(node) & skip:
        return ""
    return " ".join(k if isinstance(k, str) else text_of(k, skip) for k in node["kids"])


def label_of(node):
    lab = next((e for e in elements(node) if "lab" in classes_of(e)), None)
    return " ".join(text_of(lab).split()) if lab else ""


def out_of_review(section):
    """Whether a Not on <exam> or Unverified banner (div.callout.warn) before the section's first h3
    takes the whole section out of the Review view, its Must-know list included (CHASSIS.md)."""
    for k in section["kids"]:
        if not isinstance(k, dict):
            continue
        if k["tag"] == "h3":
            return False
        if k["tag"] == "div" and {"callout", "warn"} <= classes_of(k) and OUT_LABEL.fullmatch(label_of(k)):
            return True
    return False


def rv_problems(name, tree):
    """Where class rv sits on anything but a worked example or a Pitfall directly in its section, or
    in a section a banner takes out of the Review view."""
    out = []
    for e in elements(tree.root):
        c = classes_of(e)
        if "rv" not in c:
            continue
        if e["tag"] == "details" and {"callout", "example", "wex"} <= c:
            what = None
        elif e["tag"] == "div" and {"callout", "warn"} <= c:
            lab = label_of(e)
            what = None if lab == "Pitfall" else f'a "{lab}" callout'
        else:
            what = f"<{e['tag']} class=\"{e['attrs'].get('class', '')}\">"
        parent = e["parent"]
        if what:
            out.append(f"{name}: class rv on {what}: only a worked example or a Pitfall joins the "
                       "Review view (CONVERT.md)")
        elif not (parent["tag"] == "section" and "note" in classes_of(parent)):
            out.append(f"{name}: an rv block inside <{parent['tag']}>: it sits directly in its section, "
                       "so the Review view can show it alone")
        elif out_of_review(parent):
            out.append(f"{name}: an rv block in §{parent['attrs'].get('id', '?').removeprefix('sec-')}, "
                       "which a Not on <exam> or Unverified banner before its first h3 takes out of the "
                       "Review view")
    return out


def box_problems(name, tree):
    """Where a concise box (div.concise) or a slide-image figure breaks CONVERT.md's form: a box
    sits directly in its section and opens its subsection (after its h3, with at most the Depth line
    before it), one a subsection, and holds one <ul> and nothing else, each item opening with
    <strong>Label:</strong>, the label from BOX_LABELS, each once and in that order. An <img> is
    the one image of a <figure id="fig-..."> holding no SVG, with alt text, and the figure's
    figcaption holds a source citation (a.slink)."""
    out = []
    for e in elements(tree.root):
        if "concise" in classes_of(e):
            out += box_form(name, e)
        if e["tag"] == "img":
            out += image_form(name, e)
    return out


def box_form(name, e):
    where = f"{name}: a concise box"
    parent = e["parent"]
    if e["tag"] != "div":
        return [f"{where} on <{e['tag']}>: it is a <div class=\"concise\"> (CONVERT.md)"]
    if not (parent["tag"] == "section" and "note" in classes_of(parent)):
        return [f"{where} inside <{parent['tag']}>: it sits directly in its section, under its h3"]
    sibs = [k for k in parent["kids"] if isinstance(k, dict)]
    at = next(i for i, k in enumerate(sibs) if k is e)  # by identity: == on these dicts recurses
    h3 = next((i for i in range(at - 1, -1, -1) if sibs[i]["tag"] == "h3"), None)
    if h3 is None:
        return [f"{where} before the section's first h3: a box opens a subsection"]
    before, h3 = sibs[h3 + 1:at], sibs[h3]
    head = h3["attrs"].get("id", "its h3")
    if any("concise" in classes_of(k) for k in before):
        return [f"{where} twice under {head}: one box a subsection"]
    if any(not (k["tag"] == "p" and "connects" in classes_of(k) and text_of(k).strip().startswith("Depth:"))
           for k in before):
        return [f"{where} after other text under {head}: it opens its subsection, right after the h3 "
                "(and its Depth line)"]
    kids = [k for k in e["kids"] if isinstance(k, dict) or k.strip()]
    if len(kids) != 1 or not isinstance(kids[0], dict) or kids[0]["tag"] != "ul":
        return [f"{where} under {head} that isn't one <ul> of labelled items"]
    labels = []
    for li in kids[0]["kids"]:
        if isinstance(li, str):
            if li.strip():
                return [f"{where} under {head} with text outside its items"]
            continue
        first = next((k for k in li["kids"] if isinstance(k, dict) or k.strip()), None)
        lab = " ".join(text_of(first).split()) \
            if li["tag"] == "li" and isinstance(first, dict) and first["tag"] == "strong" else ""
        m = re.fullmatch(r"(.+):", lab)
        if not m or m.group(1) not in BOX_LABELS:
            return [f"{where} under {head} with an item that doesn't open with <strong>Label:</strong>, the "
                    f"label one of {', '.join(BOX_LABELS)}: {(lab or text_of(li).strip())[:40]!r}"]
        labels.append(m.group(1))
    if not labels:
        return [f"{where} under {head} with no items"]
    if len(set(labels)) != len(labels) or labels != sorted(labels, key=BOX_LABELS.index):
        return [f"{where} under {head} labelled {', '.join(labels)}: each label at most once, in the order "
                f"{', '.join(BOX_LABELS)}"]
    return []


def image_form(name, e):
    fig = e["parent"]
    if fig["tag"] != "figure" or not fig["attrs"].get("id", "").startswith("fig-"):
        return [f"{name}: an <img> outside a <figure id=\"fig-...\">, directly: an image is a slide-image "
                "figure (CONVERT.md)"]
    fid, out = fig["attrs"]["id"], []
    if not IMG_SRC.fullmatch(e["attrs"].get("src", "")):
        out.append(f"{name}: #{fid}'s <img> src isn't img/<name>.png, .jpg or .webp (a file in _build/img/, "
                   f"which the page embeds): {e['attrs'].get('src', '')[:40]!r}")
    inside = list(elements(fig))
    if sum(k["tag"] == "img" for k in inside) != 1 or any(k["tag"] == "svg" for k in inside):
        out.append(f"{name}: #{fid} holds more than its one <img>: a slide-image figure is one image")
    if not " ".join(e["attrs"].get("alt", "").split()):
        out.append(f"{name}: #{fid}'s <img> has no alt text (say what the slide shows)")
    caps = [k for k in fig["kids"] if isinstance(k, dict) and k["tag"] == "figcaption"]
    if not caps or not any(k["tag"] == "a" and "slink" in classes_of(k) for k in elements(caps[0])):
        out.append(f"{name}: #{fid}, a slide-image figure, has no source citation in its caption "
                   "(<a class=\"slink\">D5 p.23</a>, CONVERT.md)")
    return out


# An <img>'s src attribute in any spelling a browser takes: any case, blanks around the =, the
# value quoted either way or bare.
IMG_SRC_ATTR = re.compile(r"""(<img\b(?:[^>]*?\s)?src\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""", re.I)


def embed_images(name, text, imgdir, problems):
    """text with each <img src="img/<file>"> holding its file from imgdir as a data URI. An img/
    src the fragment parser still sees afterwards (written in a form the substitution missed, a
    character reference say) is refused: on the artifact host a relative src is a broken image."""
    failed = set()

    def one(m):
        rel = next(g for g in m.group(2, 3, 4) if g is not None)
        if not IMG_SRC.fullmatch(rel):
            return m.group(0)  # image_form refused it
        failed.add(rel)
        mime, magic = IMG_TYPES[rel.rsplit(".", 1)[1].lower()]
        try:
            with open(os.path.join(imgdir, rel[len("img/"):]), "rb") as f:
                data = f.read(IMG_MAX + 1)
        except OSError:
            problems.append(f"{name}: {rel} isn't in _build/img/")
            return m.group(0)
        if len(data) > IMG_MAX:
            problems.append(f"{name}: {rel} is over {IMG_MAX:,} bytes: crop it tighter or save it as JPEG")
        elif not data.startswith(magic) or (mime == "image/webp" and data[8:12] != b"WEBP"):
            problems.append(f"{name}: {rel} isn't the {mime} its name says")
        else:
            failed.discard(rel)
            return f'{m.group(1)}"data:{mime};base64,{base64.b64encode(data).decode("ascii")}"'
        return m.group(0)
    text = IMG_SRC_ATTR.sub(one, text)
    left = Fragment()
    left.feed(text)
    left.close()
    for src in left.images:
        if src.startswith("img/") and src not in failed:
            problems.append(f'{name}: an <img> src {src[:40]!r} wasn\'t embedded: write it src="img/<name>.png"')
            failed.add(src)
    return text


def review_parts(section):
    """The elements of one section.note the Review view shows (CHASSIS.md; the chassis's script
    applies the same rule): its h2, each rv block and concise box, each h3 whose subsection holds
    one, and each
    Must-know h3 (id ending -must-know) with the first list after it; none of a section a banner
    takes out (out_of_review)."""
    if out_of_review(section):
        return []
    shown, h3, must = [], None, False
    for k in section["kids"]:
        if not isinstance(k, dict):
            continue
        if k["tag"] == "h2":
            shown.append(k)
        elif k["tag"] == "h3":
            h3, must = k, k["attrs"].get("id", "").endswith("-must-know")
            if must:
                shown.append(k)
        elif {"rv", "concise"} & classes_of(k):
            if h3 is not None and h3 not in shown:
                shown.append(h3)
            shown.append(k)
        elif must and k["tag"] in ("ul", "ol"):
            shown.append(k)
            must = False
    return shown


def reading_words(text):
    """Words to read in text: in math, each run of letters or each number (\\frac and the like
    aside); elsewhere, code included, each blank-separated token holding a letter or digit."""
    n = 0
    for i, part in enumerate(re.split(r"\\\((.*?)\\\)|\\\[(.*?)\\\]", text, flags=re.S)):
        if part is None:
            continue
        if i % 3:
            n += len(re.findall(r"[A-Za-z]+|\d+", re.sub(r"\\[A-Za-z]+", " ", part)))
        else:
            n += sum(1 for w in part.split() if re.search(r"\w", w))
    return n


def review_budget(root, problems):
    """PLAN.md's Review view minutes, or None for none or no line."""
    path = os.path.join(root, "PLAN.md")
    try:
        with open(path, encoding="utf-8") as f:
            lines = [m.group(1).strip() for m in map(REVIEW_LINE.match, f.read().splitlines()) if m]
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        problems.append(f"PLAN.md: {e}")
        return None
    if len(lines) > 1:
        problems.append(f"PLAN.md: {len(lines)} `- Review view:` lines; one says the budget")
        return None
    if not lines:
        return None
    m = re.fullmatch(r"(\d+) minutes of reading", lines[0])
    if m and int(m.group(1)) > 0:
        return int(m.group(1))
    if not re.fullmatch(r"none: \S.*", lines[0]):
        problems.append(f"PLAN.md: `- Review view: {lines[0]}` is neither `<N> minutes of reading` "
                        "nor `none: <why>`")
    return None


def inline(text, where, problems):
    """One cram-order line's Markdown as HTML: text escaped, **bold**, `code`, \\( math \\) and
    [text](URL#id) (as <a class="xref" href="#id">) rendered; anything else refused."""
    out, last = [], 0

    def plain(s):
        bad = UNRENDERED.search(s)
        if bad:
            problems.append(f"{where}: `{bad.group(0)}` in {s.strip()[:40]!r}: the map renders only "
                            "text, **bold**, `code`, \\( math \\) and [text](URL#id) links")
        return html.escape(s, quote=False)
    for m in INLINE.finditer(text):
        out.append(plain(text[last:m.start()]))
        math, code, bold, label, target = m.groups()
        if math is not None:
            out.append("\\(" + html.escape(math, quote=False) + "\\)")
        elif code is not None:
            out.append("<code>" + html.escape(code, quote=False) + "</code>")
        elif bold is not None:
            out.append("<strong>" + inline(bold, where, problems) + "</strong>")
        elif "#" in target:
            ref = target.split("#", 1)[1]
            out.append(f'<a class="xref" href="#{html.escape(ref, quote=True)}">'
                       + inline(label, where, problems) + "</a>")
        else:
            problems.append(f"{where}: a link with no #id ({target}): the map links only into the notes")
        last = m.end()
    out.append(plain(text[last:]))
    return "".join(out)


def cram_block(lines, problems):
    """The map's cram block from a checked cram order: a div.ecram holding one .eq per tier and an
    .edrill with the Skip and Out of time lines."""
    parts = cram_check.blocks(lines)
    following = dict(lines)
    groups = []
    # Written before S33: no row has a label, and the map shows none (cram_check.check warned).
    labels = any(DEPTH.fullmatch(cram_check.split_needs(m.group(3))[0]) for m in
                 (CRAM_ROW.match(t) for _, _, rows in parts["tiers"] for _, t in rows) if m)
    for k, (name, minutes, rows) in enumerate(parts["tiers"], 1):
        items = []
        for n, t in rows:
            where = f"{CRAM}:{n}"
            m = CRAM_ROW.match(t)
            # The row's needs list (FB-193), split off by cram_check's own parser, which has passed it.
            text, needs, _ = cram_check.split_needs(m.group(3)) if m else (None, None, True)
            d = DEPTH.fullmatch(text) if m else None
            if m and not labels:
                label, thing = None, text
            elif d:
                label, thing = d.group(1), d.group(2)
            else:
                problems.append(f"{where}: no depth label (Know cold, Use, Recognize or Not on <exam>, "
                                "then a colon) before the one thing (S33)")
                continue
            thing = thing[:-1] if thing.endswith(".") else thing
            items.append(f'        <li><b>{inline(thing, where, problems)}</b> → <a class="xref" '
                         f'href="#{html.escape(m.group(2), quote=True)}">{inline(m.group(1), where, problems)}'
                         "</a>" + (f" ({html.escape(label, quote=False)})" if label else "")
                         + (" · needs " + ", ".join(f'<a class="xref" href="#{html.escape(k[1:], quote=True)}">'
                                                    f"{html.escape(num, quote=False)}</a>" for num, k in needs)
                            if needs else "") + "</li>")
        groups.append(f'      <div class="eq"><div class="eqh">Tier {k}: '
                      f'{inline(name, f"{CRAM} tier {k}", problems)} ({minutes} min)</div><ul>\n'
                      + "\n".join(items) + "</ul></div>")
    drill = []
    for key in ("skip", "out_of_time"):
        if parts[key]:
            n, t = parts[key]
            if following.get(n + 1, "").strip():
                problems.append(f"{CRAM}:{n + 1}: the {'Skip' if key == 'skip' else 'Out of time'} line "
                                "runs on: keep it to one line, so the map shows all of it")
            drill.append(inline(t, f"{CRAM}:{n}", problems))
    return ('<div class="ecram">\n    <div class="egrid">\n' + "\n".join(groups) + "\n    </div>\n"
            f'    <p class="edrill">{" ".join(drill)}</p>\n  </div>\n  ')


def hand_cram(nav_tree):
    """What in the hand-written map is a cram block or an open attribute (assemble.py's own)."""
    out = []
    for e in elements(nav_tree.root):
        if "open" in e["attrs"]:
            out.append("an open attribute: the map opens when practice/cram-order.md exists, and "
                       "assemble.py adds it then (K02)")
        c = classes_of(e)
        if "ecram" in c:
            out.append("a hand-written cram block (.ecram)")
        elif "eqh" in c and re.match(r"\s*Tier \d+:", text_of(e)):
            out.append(f"a hand-written cram tier ({' '.join(text_of(e).split())[:40]})")
        elif e["tag"] in ("strong", "b") and re.match(r"\s*(Skip:|Out of time\?)", text_of(e)):
            out.append(f"a hand-written {' '.join(text_of(e).split())} line")
    return [f"frag/examnav.html: {p}: assemble.py renders the cram block from practice/cram-order.md"
            if "hand-written" in p else f"frag/examnav.html: {p}" for p in dict.fromkeys(out)]


def build(root, warnings=None):
    """(page, problems); what builds but wants a later pass (a cram order written before S33) is
    appended to warnings, a list, when one is given."""
    b = os.path.join(root, "_build")
    frag = os.path.join(b, "frag")
    problems = []
    with open(os.path.join(b, "chassis.html"), encoding="utf-8") as f:
        page = f.read()
    for ph in sorted(set(PLACEHOLDER.findall(page))):
        problems.append(f"chassis.html: placeholder {ph} not filled")
    for m in MARKERS:
        if page.count(m) != 1:
            problems.append(f"chassis.html: marker {m} appears {page.count(m)} times, not once")
    md = os.path.join(b, "CHASSIS.md")
    if os.path.isfile(md):
        with open(md, encoding="utf-8") as f:
            classes = vocabulary(f.read())
        if not classes:
            problems.append("CHASSIS.md: no component table (## Components) naming classes")
        for c in sorted(classes - chassis_classes(page)):
            problems.append(f"CHASSIS.md names .{c}, which chassis.html's CSS doesn't style")
    else:
        problems.append("_build/CHASSIS.md missing (copy the skill's templates/CHASSIS.md)")
        classes = set()

    manifest = os.path.join(root, "MANIFEST.md")
    key, unread = None, False  # None: no key to check citations against (said once below)
    try:
        key = manifest_key(manifest)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, UnicodeDecodeError) as e:
        problems.append(f"MANIFEST.md: {e}")
        unread = True
    cited = {}
    budget = review_budget(root, problems)
    rv = []  # where class rv sits wrong
    nav_tree = None

    notes = os.path.join(root, "notes")
    nums = sorted(int(m.group(1)) for m in map(NOTE.fullmatch, os.listdir(notes)) if m) \
        if os.path.isdir(notes) else []
    if not nums:
        problems.append("no notes/NN-<slug>.md files")
    sections = []
    for n in nums:
        path = os.path.join(frag, f"sec{n}.html")
        if not os.path.isfile(path):
            problems.append(f"frag/sec{n}.html missing (notes file {n:02d})")
            continue
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        text = raw.strip()
        leftovers(f"frag/sec{n}.html", raw, problems, warnings)
        opens = re.findall(r"<section\b[^>]*>", text)
        if len(opens) != 1 or not re.fullmatch(
                r"""<section\s+class=["']note["']\s+id=["']sec-%d["']\s*>""" % n, opens[0]) \
                or not text.startswith(opens[0]) or not text.endswith("</section>"):
            problems.append(f'frag/sec{n}.html: not one <section class="note" id="sec-{n}">')
        check_fragment(f"frag/sec{n}.html", text, classes, problems, images=True)
        tree = Tree(text)
        rv += rv_problems(f"frag/sec{n}.html", tree)
        problems += box_problems(f"frag/sec{n}.html", tree)
        text = embed_images(f"frag/sec{n}.html", text, os.path.join(b, "img"), problems)
        sections.append(link_citations(f"frag/sec{n}.html (§{n})", text, key, cited, problems))

    examnav = os.path.join(frag, "examnav.html")
    if os.path.isfile(examnav):
        with open(examnav, encoding="utf-8") as f:
            raw = f.read()
        nav = raw.strip()
        leftovers("frag/examnav.html", raw, problems, warnings)
        check_fragment("frag/examnav.html", nav, classes, problems, markers=False)
        nav_tree = Tree(nav)
        problems += hand_cram(nav_tree)
        rv += rv_problems("frag/examnav.html", nav_tree)
        nav = link_citations("frag/examnav.html (the exam-day map)", nav, key, cited, problems)
    else:
        problems.append("frag/examnav.html missing (the exam-day map, 06-site)")
        nav = ""

    body = "\n\n".join(sections)
    placed = Counter()

    def place(m):
        path = os.path.join(frag, f"step-{m.group(1)}.html")
        if not os.path.isfile(path):
            problems.append(f"FIG marker {m.group(1)} left, and no frag/step-{m.group(1)}.html")
            return m.group(0)
        placed[m.group(1)] += 1
        with open(path, encoding="utf-8") as f:
            return link_citations(f"frag/step-{m.group(1)}.html", f.read().strip(), key, cited, problems)

    body = FIG.sub(place, body)
    scripts = []
    for name in sorted(os.listdir(frag)) if os.path.isdir(frag) else []:
        step = STEP_FILE.fullmatch(name)
        if step:
            n = placed[step.group(1)]
            if n != 1:
                problems.append(f"frag/{name}: its FIG marker appears {n} times, not once "
                                "(a step-through drawn statically, or its marker dropped or repeated)")
            with open(os.path.join(frag, name), encoding="utf-8") as f:
                raw = f.read()
            text = raw.strip()
            leftovers(f"frag/{name}", raw, problems, warnings)
            # Placed mid-text, anything around a figure would join the text beside its marker.
            if len(re.findall(r"<figure\b", text, re.I)) != 1 or len(re.findall(r"</figure\b", text, re.I)) != 1 \
                    or not re.fullmatch(
                    r"""<figure\s+id=["']%s["'][^>]*>.*</figure>""" % re.escape(step.group(1)), text, re.S):
                problems.append(f'frag/{name}: not one <figure id="{step.group(1)}"> (CHASSIS.md\'s step-through form)')
            check_fragment(f"frag/{name}", text, classes, problems, hooks=True, markers=False)
            rv += rv_problems(f"frag/{name}", Tree(text))
        if name.endswith(".js"):
            with open(os.path.join(frag, name), encoding="utf-8") as f:
                scripts.append(f"<script>\n{f.read().strip()}\n</script>")

    # A step-through's text and the text beside its marker join on the page: check them together.
    try:
        tex = tex_macros(body)
    except (AssertionError, NotImplementedError):
        tex = []  # a fragment's own check has refused it
    if tex:
        problems.append(f"the sections as assembled, step-throughs in place: MathJax macros that make HTML: "
                        f"{', '.join(sorted(set(tex)))}")
    if cited and key is None and not unread:
        problems.append(f"MANIFEST.md missing: the page cites {len(cited)} codes, and its source key "
                        "is built from MANIFEST.md's table")
    elif cited and key is not None:
        # One section after the last, numbered on from it, so the rail lists it like any other.
        keysec = source_key(max(nums, default=0) + 1, key, cited)
        check_fragment("the source key (from MANIFEST.md)", keysec, classes, problems, markers=False)
        body += "\n\n" + keysec
        sections.append(keysec)

    cram = os.path.join(root, CRAM)
    if os.path.isfile(cram) and nav:
        try:
            with open(cram, encoding="utf-8") as f:
                lines = list(enumerate(f.read().splitlines(), 1))
        except (OSError, UnicodeDecodeError) as e:
            problems.append(f"{CRAM}: {e}")
            lines = None
        while lines and not lines[0][1].strip():
            lines.pop(0)
        if lines is not None:
            ids = cram_check.Ids()
            try:
                ids.feed(nav + body)
            except (AssertionError, NotImplementedError):
                pass  # a fragment's own check has refused it
            warned = []
            bad, _ = cram_check.check(lines, ids.ids, warnings=warned)
            if warnings is not None:
                warnings += [f"{CRAM}: {w}" for w in warned]
            problems += [f"{CRAM}:{b}" if b[0].isdigit() else f"{CRAM}: {b}" for b in bad]
            if not bad:
                block = cram_block(lines, problems)
                check_fragment(f"the map's cram block (from {CRAM})", block, classes, problems, markers=False)
                ebody = re.findall(r"""<div\s+class=["']ebody["']\s*>""", nav)
                details = re.findall(r"""<details\s+class=["']examnav["']""", nav)
                if len(ebody) != 1 or len(details) != 1:
                    problems.append('frag/examnav.html: not one <details class="examnav"> with one '
                                    '<div class="ebody"> to put the cram block in')
                else:
                    at = nav.index(ebody[0]) + len(ebody[0])
                    nav = nav[:at] + "\n  " + block + nav[at:].lstrip("\n ")
                    nav = nav.replace(details[0], details[0] + " open", 1)

    if budget is None:
        page = TOGGLE.sub("", page)
        if any("rv" in classes_of(e) for s in sections for e in elements(Tree(s).root)):
            problems.append("class rv on the page, and PLAN.md has no `- Review view: <N> minutes of "
                            "reading` line: with no Review view, nothing joins it")
    else:
        if not TOGGLE.search(page):
            problems.append("chassis.html has no <!-- REVIEW TOGGLE --> block, and PLAN.md gives the "
                            "Review view minutes (copy the skill's current templates/notes-chassis.html)")
        page = TOGGLE.sub(lambda m: m.group(1), page)
        shown = [e for s in Tree(body).root["kids"] if isinstance(s, dict)
                 and s["tag"] == "section" and "note" in classes_of(s)
                 and not s["attrs"].get("id", "") == f"sec-{max(nums, default=0) + 1}"
                 for e in review_parts(s)]
        # The cram block is a reading list into the notes, not review text: a page tagged up to its
        # minutes must not fail at the first build with a cram order (08 step 7.4).
        words = sum(reading_words(text_of(e)) for e in shown) \
            + reading_words(text_of(Tree(nav).root, skip={"ecram"}))
        if words > budget * READING_RATE:
            tagged = any("rv" in classes_of(e) for s in sections for e in elements(Tree(s).root))
            problems.append(f"the Review view reads in about {words / READING_RATE:.1f} minutes ({words} "
                            f"words at {READING_RATE} a minute), over PLAN.md's {budget}: " + (
                                "untag rv blocks from the last ranked subsection up (07-cheatsheet, "
                                "Tag the review)" if tagged else
                                "no rv tag is left to untag, so the main session asks the student for new "
                                "minutes on PLAN.md's `- Review view:` line and logs them in STATUS, or, "
                                "when the student can't be asked, sets them and logs it, as "
                                "07-cheatsheet's Tag the review opening says"))
    problems += rv
    page = page.replace("/* SECTION ACCENTS */", accents(len(sections)), 1)
    page = page.replace("<!-- EXAM-DAY MAP -->", nav, 1)
    page = page.replace("<!-- SECTIONS -->", body, 1)
    page = page.replace("<!-- FIGURE SCRIPTS -->", "\n".join(scripts), 1)
    return page, problems


def main(argv=None):
    p = argparse.ArgumentParser(description="Assemble _build/notes.html.")
    p.add_argument("--root", default=".", help="the exam-prep root (default: the cwd)")
    args = p.parse_args(argv)
    if not os.path.isfile(os.path.join(args.root, "_build", "chassis.html")):
        print("assemble: no _build/chassis.html here (copy the skill's templates/notes-chassis.html)",
              file=sys.stderr)
        return 2
    warnings = []
    page, problems = build(args.root, warnings)
    for w in warnings:
        print(f"WARN: {w}")
    if problems:
        for m in problems:
            print(f"  {m}")
        print(f"{len(problems)} problems; _build/notes.html not written")
        return 1
    out = os.path.join(args.root, "_build", "notes.html")
    tmp = out + ".tmp"
    data = page.encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out)
    print(f"wrote _build/notes.html ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
