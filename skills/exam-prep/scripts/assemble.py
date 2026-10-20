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
on...= or style= attribute, a link that isn't #id, http(s) or mailto, a class outside the
component table in the hub's _build/CHASSIS.md (a step-through may add fs-* hook classes), markup
a browser and Python's parser read differently (a comment other than a FIG marker, <![CDATA[,
<?...>, a doctype), one of MathJax's \\href, \\style, \\class or \\cssId outside code, or a
TODO-VERIFY left from 05-verify; when a FIG marker is left with no step-through, or a step-through
file isn't placed exactly once. Stdlib only."""
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
FIG = re.compile(r"<!--\s*FIG\s+(fig-[\w-]+)\b.*?-->", re.S)
STEP_FILE = re.compile(r"step-(.+)\.html")
# Tags no fragment holds: they run code, load or embed another document, or change the page
# itself (SVG's animation tags can rewrite a link; foreignObject embeds HTML).
FORBIDDEN_TAGS = {"script", "style", "link", "meta", "base", "iframe", "frame", "frameset",
                  "object", "embed", "form", "template", "foreignobject", "animate",
                  "animatemotion", "animatetransform", "set"}
URL_ATTRS = {"href", "src", "xlink:href", "action", "formaction", "srcset", "poster", "data",
             "background", "ping"}
SAFE_URL = re.compile(r"(#|https?://|mailto:)", re.I)
HOOK = re.compile(r"fs-[\w-]+")
FIG_COMMENT = re.compile(r"\s*FIG\s+fig-[\w-]+\b[^<>]*")
# MathJax's html extension, autoloaded, turns these into links, styles, classes and ids that the
# tag walk never sees; MathJax leaves code and pre alone.
TEX_HTML = re.compile(r"\\(?:href|style|class|cssId)(?![A-Za-z])")
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
        self.tags, self.attrs, self.urls, self.classes = set(), set(), [], set()
        self.markup, self.tex, self.code = [], [], 0

    def handle_comment(self, data):
        if not FIG_COMMENT.fullmatch(data):
            self.markup.append(f"<!--{data[:30]}-->")

    def unknown_decl(self, data):
        self.markup.append(f"<![{data[:30]}]>")

    def handle_decl(self, decl):
        self.markup.append(f"<!{decl[:30]}>")

    def handle_pi(self, data):
        self.markup.append(f"<?{data[:30]}>")

    def handle_data(self, data):
        if not self.code:
            self.tex += TEX_HTML.findall(data)

    def handle_endtag(self, tag):
        if tag in ("code", "pre") and self.code:
            self.code -= 1

    def handle_starttag(self, tag, attrs):
        if tag in ("code", "pre"):
            self.code += 1
        if tag in FORBIDDEN_TAGS:
            self.tags.add(tag)
        for name, value in attrs:
            value = value or ""
            if name.startswith("on") or name == "style":
                self.attrs.add(name)
            elif name in URL_ATTRS and not SAFE_URL.match(value.strip()):
                self.urls.append(f'{name}="{value}"')
            elif name == "class":
                self.classes.update(value.split())


def check_fragment(name, text, allowed, problems, hooks=False):
    """Append what CONVERT.md forbids in one fragment to problems."""
    f = Fragment()
    f.feed(text)
    f.close()
    if f.tags:
        problems.append(f"{name}: forbidden tags: {', '.join(sorted(f.tags))} (CONVERT.md)")
    if f.attrs:
        problems.append(f"{name}: forbidden attributes: {', '.join(sorted(f.attrs))} (CONVERT.md)")
    if f.urls:
        problems.append(f"{name}: links that aren't #id, http(s) or mailto: {', '.join(f.urls[:3])}")
    if f.markup:
        problems.append(f"{name}: markup a browser reads differently (only a FIG marker comment "
                        f"may stay): {', '.join(f.markup[:3])}")
    if f.tex:
        problems.append(f"{name}: MathJax macros that make HTML: {', '.join(sorted(set(f.tex)))}")
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
        check_fragment("frag/examnav.html", nav, classes, problems)
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
                check_fragment(f"frag/{name}", f.read(), classes, problems, hooks=True)
        if name.endswith(".js"):
            with open(os.path.join(frag, name), encoding="utf-8") as f:
                scripts.append(f"<script>\n{f.read().strip()}\n</script>")

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
