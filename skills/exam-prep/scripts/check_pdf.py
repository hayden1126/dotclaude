#!/usr/bin/env python3
"""Check a printed cheat sheet before the student prints it (07-cheatsheet).

  check_pdf.py <sheet.pdf> --floor PT --forbid TEXT [--forbid TEXT]... [--pages N]
               [--paper letter|a4] [--layout FILE | --no-layout]

From the PDF itself, with poppler's pdfinfo and pdffonts and MuPDF's mutool:
  - exactly N pages (default 2: one sheet, both sides), each landscape at the paper's size;
  - every font embedded (L63); their names are listed, to compare with the faces the sheet
    declares, since a missing face falls back silently to a wider one;
  - no character printed smaller than the floor (the student's, FB-131). The sizes are the PDF's
    own, so superscripts, subscripts and SVG text count at the size they print (FB-142, L61);
  - no text within MARGIN_MIN of a page's edge, where printers clip (FB-139: 0.2 in margins);
  - no section sign, which points into the notes (FB-134); each line holding the word "notes" is
    shown as a warning to judge;
  - no --forbid text (the student's name and id, FB-132; at least one is required), matched as
    whole words, case-insensitively, across line breaks. A hit names the --forbid by number (#1,
    #2, in order), counts its matches and shows the words around every one, with every --forbid
    masked (`[#2]'s theorem`), so an ordinary word that happens to be a name part can be
    told from the name. Overlapping matches mask as one, labeled by the longest. Every line,
    box text or URL any message quotes is masked the same way (a page's lines as one text, so a
    name across a line break is caught), so no output shows a --forbid text.
From the layout file print_sheet.mjs wrote with the PDF (default: <sheet>.layout.json beside it):
  - it measured this PDF, one side per page, and the sheet it names hasn't changed since;
  - that sheet's HTML holds no --forbid text either, in its text, comments or the attributes that
    carry words (alt, title, aria-*, data-* and the like; not class, id, style or SVG geometry,
    which are the template's vocabulary): it is what gets published;
  - nothing remote was requested: the sheet prints offline;
  - no side clipped content (a column spilled past the last one, or past the page's foot), and
    nothing runs past its own column's right edge over the next one (FB-138, L60);
  - each side's fill: a side whose content ends before its last column, or above FILL_MIN of it,
    warns (the body could be larger, FB-131, unless the room is left for the final sheet,
    FB-140).
A sheet the student wrote themselves (in LaTeX, say) has no layout file: pass --no-layout, and
judge overflow and fill from the page images (and LaTeX's log: an Overfull line is an overflow).

Exit 0 when nothing fails (warnings allowed), 1 on a failure, 2 on bad usage, a missing tool or
a malformed layout file. Stdlib only."""
import argparse
import hashlib
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

# Landscape (width, height) in points.
PAPER = {"letter": (792.0, 612.0), "a4": (841.89, 595.28)}
SIZE_SLACK = 1.0
FONT_SLACK = 0.01  # Chromium prints a 5 pt superscript as 4.995
MARGIN_MIN = 13.0  # pt: under the template's 0.2 in (14.4 pt), over what printers clip
FILL_MIN = 0.84
BOTTOM_SLACK = 0.005  # fill.bottom is rounded to hundredths
TOOLS = {"pdfinfo": "poppler-utils", "pdffonts": "poppler-utils", "mutool": "mupdf-tools"}
NOTES = re.compile(r"\bnotes\b", re.I)
# A pdffonts row, read from the right: its name column pads short names but never cuts long ones.
FONT_ROW = re.compile(r"^(\S+)\s.*\s(yes|no)\s+(yes|no)\s+(yes|no)\s+(?:\d+\s+\d+|\[none\])\s*$")


class Bad(Exception):
    """A malformed input: exit 2."""


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise Bad(f"{args[0]} failed on the PDF: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def flat(text):
    return " ".join(text.split())


def forbidden(texts):
    """A whole-word, case-insensitive pattern per --forbid text."""
    return [re.compile(r"(?<!\w)" + re.escape(flat(t)) + r"(?!\w)", re.I) for t in texts]


def spans(patterns, text):
    """What to mask in text, [(start, end, n)] in order: every match of every pattern, with
    overlapping matches merged into one span labeled with the longest one's number, so no part of
    a longer form shows beside a shorter one."""
    out = []  # [start, end, label, the label's match length]
    for a, b, n in sorted((m.start(), m.end(), n) for n, p in enumerate(patterns, 1)
                          for m in p.finditer(text)):
        if out and a < out[-1][1]:
            last = out[-1]
            if b - a > last[3]:
                last[2], last[3] = n, b - a
            last[1] = max(last[1], b)
        else:
            out.append([a, b, n, b - a])
    return [(a, b, n) for a, b, n, _ in out]


def render(text, cuts, lo=0, hi=None):
    """(text[lo:hi] with every span of cuts that reaches into it replaced, whole, by its `[#n]`,
    [(where each `[#n]` starts in that, n)])."""
    hi = len(text) if hi is None else hi
    out, starts, pos = "", [], lo
    for a, b, n in cuts:
        if a < hi and b > lo:
            out += text[pos:max(a, lo)]
            starts.append((len(out), n))
            out += f"[#{n}]"
            pos = b
    return out + text[pos:hi], starts


def masked(patterns, text):
    return render(text, spans(patterns, text))[0]


def hits(patterns, text):
    """{the 1-based number of a pattern: [the words around each of its matches, every pattern
    masked]} for text."""
    text, starts = render(text, spans(patterns, text))
    out = {}
    for at, n in starts:
        a, b = max(0, at - 30), min(len(text), at + 34)
        # Whole words only, so no word and no `[#n]` is cut in half.
        if a > 0 and " " in text[a:at]:
            a = text.index(" ", a) + 1
        if b < len(text) and " " in text[at:b]:
            b = text.rindex(" ", at, b)
        out.setdefault(n, []).append(text[a:b].strip())
    return out


def report(n, shown):
    """'--forbid #n (k matches): "..."; "..."', every match shown: a form is dropped only when
    each of them is an ordinary word."""
    return (f"--forbid #{n} ({len(shown)} match{'es' if len(shown) != 1 else ''}): "
            + "; ".join(shown))


# The attributes that carry words a reader sees or a tool reads out; the rest (class, id, style,
# SVG geometry) are the template's vocabulary and numbers.
WORD_ATTRS = {"alt", "title", "content", "href", "src", "value", "label", "placeholder", "summary"}


class Readable(html.parser.HTMLParser):
    """What a sheet's HTML shows or carries, by kind: its text (the title too), its comments and
    the attributes that carry words; not its CSS."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.handle_startendtag(tag, attrs)
        if tag in ("style", "script"):
            self.skip += 1

    def handle_startendtag(self, tag, attrs):
        for name, value in attrs:
            if value and (name in WORD_ATTRS or name.startswith(("aria-", "data-"))):
                self.parts.append((f"the {name} attribute of a <{tag}>", value))

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(("its text", data))

    def handle_comment(self, data):
        self.parts.append(("a comment", data))


def page_sizes(pdf):
    out = run(["pdfinfo", "-f", "1", "-l", "100000", pdf])
    pages = re.search(r"^Pages:\s+(\d+)", out, re.M)
    sizes = re.findall(r"^Page\s+\d+\s+size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts", out, re.M)
    rots = re.findall(r"^Page\s+\d+\s+rot:\s+(\d+)", out, re.M)
    if not pages or len(rots) != len(sizes):
        raise Bad("pdfinfo printed no page count or sizes")
    # A page turned a quarter turn shows its media box sideways.
    return int(pages.group(1)), [(float(h), float(w)) if int(r) % 180 else (float(w), float(h))
                                 for (w, h), r in zip(sizes, rots)]


def fonts(pdf):
    """(name, embedded) per font."""
    lines = run(["pdffonts", pdf]).splitlines()
    dash = next((i for i, line in enumerate(lines) if line.startswith("---")), None)
    if dash is None:
        raise Bad("pdffonts printed no table")
    out = []
    for line in lines[dash + 1:]:
        if line.strip():
            m = FONT_ROW.match(line)
            if not m:
                raise Bad(f"pdffonts printed a row this can't read: {line.strip()[:80]}")
            out.append((m.group(1), m.group(2) == "yes"))
    return out


def text_pages(pdf):
    """Per page: the smallest printed character as (size, the index of its line), the page's
    lines, and the nearest any line comes to an edge, in points."""
    root = ET.fromstring(run(["mutool", "draw", "-q", "-F", "stext", "-o", "-", pdf]))
    pages = []
    for page in root.iter("page"):
        width, height = float(page.get("width", "0")), float(page.get("height", "0"))
        smallest, lines, edge = None, [], None
        for line in page.iter("line"):
            text = "".join(ch.get("c", "") for ch in line.iter("char"))
            lines.append(text)
            for font in line.iter("font"):
                size = float(font.get("size", "0"))
                if any(ch.get("c", "").strip() for ch in font.iter("char")):
                    if smallest is None or size < smallest[0]:
                        smallest = (size, len(lines) - 1)
            if text.strip():
                x0, y0, x1, y1 = (float(v) for v in line.get("bbox", "0 0 0 0").split())
                near = min(x0, y0, width - x1, height - y1)
                edge = near if edge is None else min(edge, near)
        pages.append((smallest, lines, edge))
    return pages


def load_layout(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, RecursionError) as e:
        raise Bad(f"layout file {path}: {e}")
    ok = (isinstance(data, dict) and isinstance(data.get("pdf_sha256"), str)
          and isinstance(data.get("sheet"), str) and isinstance(data.get("sheet_sha256"), str)
          and isinstance(data.get("remote"), list) and isinstance(data.get("pages"), list)
          and all(isinstance(u, str) for u in data["remote"]))
    for p in data["pages"] if ok else []:
        fill = p.get("fill") if isinstance(p, dict) else None
        ok = ok and isinstance(p, dict) and isinstance(p.get("overflow"), bool) \
            and type(p.get("columns")) is int and 1 <= p["columns"] <= 100 \
            and isinstance(p.get("wide"), list) and all(isinstance(w, str) for w in p["wide"]) \
            and (fill is None or (isinstance(fill, dict) and type(fill.get("col")) is int
                                  and type(fill.get("bottom")) in (int, float)
                                  and -100 < fill["bottom"] < 100))
    if not ok:
        raise Bad(f"layout file {path}: not the shape print_sheet.mjs writes")
    return data


def check(args):
    fails, warns = [], []
    count, sizes = page_sizes(args.pdf)
    want_w, want_h = PAPER[args.paper]
    print(f"{count} pages")
    if count != args.pages:
        fails.append(f"{count} pages, want {args.pages}")
    for i, (w, h) in enumerate(sizes, 1):
        if abs(w - want_w) > SIZE_SLACK or abs(h - want_h) > SIZE_SLACK:
            fails.append(f"page {i} is {w:g} x {h:g} pt, want {args.paper} landscape "
                         f"({want_w:g} x {want_h:g}): set it in the sheet's @page rule (L62)")

    found = fonts(args.pdf)
    print("fonts: " + (", ".join(n for n, _ in found) or "none"))
    for name, embedded in found:
        if not embedded:
            fails.append(f"font {name} is not embedded (L63)")

    forbid = forbidden(args.forbid)

    for i, (smallest, lines, edge) in enumerate(text_pages(args.pdf), 1):
        # The page's lines as one text, flattened, and where each line sits in it: the --forbid
        # check reads across line breaks, and a quoted line is masked with the same cuts.
        page, at, pos = [], [], 0
        for line in lines:
            line = flat(line)
            at.append((pos, pos + len(line)))
            if line:
                page.append(line)
                pos += len(line) + 1
        page = " ".join(page)
        cuts = spans(forbid, page)

        def shown(k):
            """Line k as a message may quote it: flattened, every --forbid masked, cut to 60."""
            return render(page, cuts, *at[k])[0][:60]

        if smallest:
            print(f"page {i}: smallest text {smallest[0]:.2f} pt")
            if smallest[0] < args.floor - FONT_SLACK:
                fails.append(f"page {i}: {smallest[0]:.2f} pt is below the {args.floor:g} pt floor, "
                             f"in: {shown(smallest[1])}")
        if edge is not None and edge < MARGIN_MIN:
            fails.append(f"page {i}: text {edge:.1f} pt from the page's edge, where printers clip: "
                         f"keep 0.2 in margins (FB-139; the template's @page rule sets them)")
        for k, line in enumerate(lines):
            if "§" in line:
                fails.append(f"page {i}: a section sign points into the notes (FB-134): {shown(k)}")
            if NOTES.search(line):
                warns.append(f"page {i}: says \"notes\"; the student can't open them in the exam "
                             f"(FB-134): {shown(k)}")
        for n, around in sorted(hits(forbid, page).items()):
            fails.append(f"page {i} prints " + report(n, [f'"{w}"' for w in around]) + " (FB-132)")

    if args.no_layout:
        warns.append("no layout file: overflow and fill unchecked; judge them from the page images")
    else:
        data = load_layout(args.layout)
        if data["pdf_sha256"] != sha256(args.pdf):
            fails.append(f"{args.layout} measured another print: run print_sheet.mjs again")
        sheet = os.path.join(os.path.dirname(os.path.abspath(args.layout)), data["sheet"])
        if not os.path.isfile(sheet):
            fails.append(f"the sheet {data['sheet']} is gone: print it again")
        elif data["sheet_sha256"] != sha256(sheet):
            fails.append(f"{data['sheet']} changed since it was printed: run print_sheet.mjs again")
        else:
            reader = Readable()
            with open(sheet, encoding="utf-8", errors="replace") as f:
                reader.feed(f.read())
            reader.close()
            found = {}
            for where, part in reader.parts:
                for n, around in hits(forbid, flat(part)).items():
                    found.setdefault(n, []).extend(f'in {where}: "{w}"' for w in around)
            for n, shown in sorted(found.items()):
                fails.append(f"{data['sheet']} holds " + report(n, shown) + " (FB-132)")
        for url in data["remote"]:
            fails.append(f"the sheet requested {masked(forbid, flat(url))}: it must print offline")
        if len(data["pages"]) != count:
            fails.append(f"the layout has {len(data['pages'])} sides and the PDF {count} pages: a "
                         f"side split across pages")
        for i, p in enumerate(data["pages"], 1):
            fill, cols = p["fill"], p["columns"]
            where = f"column {fill['col']} of {cols}, {fill['bottom']:g} down" if fill else "empty"
            print(f"side {i}: content ends in {where}")
            for w in p["wide"]:
                fails.append(f"side {i}, {masked(forbid, flat(w))}: wider than its column (FB-138): "
                             f"narrow it or move it "
                             f"to a full-width .span row")
            if p["overflow"] or (fill and (fill["col"] > cols or fill["bottom"] > 1 + BOTTOM_SLACK)):
                fails.append(f"side {i} clips content past its last column or its foot (FB-138): "
                             f"cut wording")
            elif not fill or fill["col"] < cols or fill["bottom"] < FILL_MIN:
                warns.append(f"side {i} ends in {where}: room for a larger body (FB-131), unless "
                             f"it is left for the final sheet (FB-140)")

    for w in warns:
        print(f"  WARN {w}")
    for f in fails:
        print(f"  FAIL {f}")
    print("ALL CHECKS PASS" if not fails else f"{len(fails)} FAILURES")
    return 1 if fails else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check a printed cheat sheet (07-cheatsheet).")
    ap.add_argument("pdf")
    ap.add_argument("--floor", type=float, required=True, help="the student's font floor, in pt")
    ap.add_argument("--forbid", action="append", required=True,
                    help="text that must not print: the student's name, their id")
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--paper", choices=sorted(PAPER), default="letter")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--layout", help="print_sheet.mjs's layout file, if not beside the PDF")
    group.add_argument("--no-layout", action="store_true", help="a sheet print_sheet.mjs didn't print")
    args = ap.parse_args(argv)
    if not args.floor > 0 or args.pages < 1:
        ap.error("--floor and --pages must be positive")
    if not all(flat(t) for t in args.forbid):
        ap.error("--forbid needs text")
    if not args.pdf.endswith(".pdf") or not os.path.isfile(args.pdf):
        print(f"check_pdf: no PDF at {args.pdf}", file=sys.stderr)
        return 2
    if not args.no_layout:
        args.layout = args.layout or args.pdf[:-len(".pdf")] + ".layout.json"
        if not os.path.isfile(args.layout):
            print(f"check_pdf: no layout file at {args.layout}: print with print_sheet.mjs, or pass "
                  f"--no-layout for a sheet it didn't print", file=sys.stderr)
            return 2
    missing = sorted({TOOLS[t] for t in TOOLS if not shutil.which(t)})
    if missing:
        print(f"check_pdf: install {' and '.join(missing)} (needs pdfinfo, pdffonts and mutool)",
              file=sys.stderr)
        return 2
    try:
        return check(args)
    except (Bad, ET.ParseError) as e:
        print(f"check_pdf: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
