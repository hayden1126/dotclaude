#!/usr/bin/env python3
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
    chassis's seven hues.

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
apart), or a TODO-VERIFY left from 05-verify; when a FIG marker holds a < or >, sits inside a
tag, an attribute or code or outside a section (in the exam-day map or a step-through), is left
with no step-through, or a step-through file isn't one <figure id="<fig-id>"> or isn't placed
exactly once. Stdlib only."""
import argparse
import os
import re
import sys
from collections import Counter
from html.parser import HTMLParser

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
FIG_COMMENT = re.compile(r"\s*FIG\s+fig-[\w-]+\b[^<>]*")
# MathJax's html extension, autoloaded, turns these into links, styles, classes and ids that the
# tag walk never sees; MathJax leaves code and pre alone.
TEX_HTML = re.compile(r"\\(?:href|style|class|cssId|data|mmlToken|require|bbox)(?![A-Za-z])")
# The chassis's seven section hues: (light accent, light highlight, dark accent, dark highlight
# or None to keep the light one, whose wash already works on dark).
HUES = [
    ("#0b6e8f", "rgba(11,110,143,.17)", "#4cbbda", None),
    ("#277a4d", "rgba(47,143,91,.19)", "#5fc088", "rgba(95,192,136,.20)"),
    ("#6244bb", "rgba(109,70,194,.17)", "#ab92e8", None),
    ("#215c9c", "rgba(37,99,166,.17)", "#6ea8e6", None),
    ("#b5591a", "rgba(192,101,29,.19)", "#e3925f", "rgba(227,146,95,.20)"),
    ("#a93574", "rgba(178,58,122,.17)", "#e67aad", None),
    ("#3a49a8", "rgba(63,81,181,.18)", "#8f99ee", None),
]


def accents(n):
    """The per-section accent rules for n sections."""
    sel = ".wrap section.note:nth-of-type({})"
    light = ["  .wrap section.note{--sec-accent:var(--accent);--sec-accent-hl:rgba(11,110,143,.16)}"]
    dark = []
    for k in range(1, n + 1):
        la, lh, da, dh = HUES[(k - 1) % len(HUES)]
        light.append(f"  {sel.format(k)}{{--sec-accent:{la};--sec-accent-hl:{lh}}}")
        dark.append(f"{sel.format(k)}{{--sec-accent:{da}" + (f";--sec-accent-hl:{dh}" if dh else "") + "}")
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
        for name, value in attrs:
            value = value or ""
            # A name (an <img name=currentScript>) or a bare-word id shadows a property of the
            # document or the window that a script reads, MathJax's loader's among them.
            if name.startswith("on") or name in ("style", "name"):
                self.attrs.add(name)
            elif name == "id" and "-" not in value:
                self.bare.append(value)
            elif name in URL_ATTRS and not SAFE_URL.match(value.strip()):
                self.urls.append(f'{name}="{value}"')
            elif name == "class":
                self.classes.update(value.split())


def tex_macros(text):
    """The MathJax macros that make HTML in an HTML text, outside code."""
    f = Fragment()
    f.feed(text)
    f.close()
    return TEX_HTML.findall("".join(f.text))


def check_fragment(name, text, allowed, problems, hooks=False, markers=True):
    """Append what CONVERT.md forbids in one fragment to problems; markers=False for one where a
    FIG marker is never placed (the exam-day map, a step-through)."""
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


def build(root):
    """(page, problems)."""
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
            text = f.read().strip()
        opens = re.findall(r"<section\b[^>]*>", text)
        if len(opens) != 1 or not re.fullmatch(
                r"""<section\s+class=["']note["']\s+id=["']sec-%d["']\s*>""" % n, opens[0]) \
                or not text.startswith(opens[0]) or not text.endswith("</section>"):
            problems.append(f'frag/sec{n}.html: not one <section class="note" id="sec-{n}">')
        check_fragment(f"frag/sec{n}.html", text, classes, problems)
        sections.append(text)

    examnav = os.path.join(frag, "examnav.html")
    if os.path.isfile(examnav):
        with open(examnav, encoding="utf-8") as f:
            nav = f.read().strip()
        check_fragment("frag/examnav.html", nav, classes, problems, markers=False)
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
            return f.read().strip()

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
                text = f.read().strip()
            # Placed mid-text, anything around a figure would join the text beside its marker.
            if len(re.findall(r"<figure\b", text, re.I)) != 1 or len(re.findall(r"</figure\b", text, re.I)) != 1 \
                    or not re.fullmatch(
                    r"""<figure\s+id=["']%s["'][^>]*>.*</figure>""" % re.escape(step.group(1)), text, re.S):
                problems.append(f'frag/{name}: not one <figure id="{step.group(1)}"> (CHASSIS.md\'s step-through form)')
            check_fragment(f"frag/{name}", text, classes, problems, hooks=True, markers=False)
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
    page, problems = build(args.root)
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
