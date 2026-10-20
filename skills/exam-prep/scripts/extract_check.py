#!/usr/bin/env python3
"""Check stage 02's extracts against MANIFEST.md's scope, from the hub root.

  extract_check.py [--root DIR]

MANIFEST's table is read by its header names (Doc id, File, Pages, Scope, Answers, Notes); with no
Doc id, File or Scope column it fails. Every row's Scope starts with `in`, `concepts only`,
`reserved`, `pending` or `out`; any other word fails. An in-scope Scope is `in` or `concepts
only`, then nothing, `PDF pp.A-B[, C-D]` or `slides #/A-#/B`, with notes in parentheses (a note
holding a page range fails: it would go unchecked); any other wording fails as SCOPE NOT
UNDERSTOOD. Each in-scope row is checked by its source's kind:
- a PDF (its File ends in .pdf): every in-scope page must be rendered under _build/pages/<doc>/
  and have a block. The in-scope pages are the Scope cell's ranges, else 1 to its Pages.
- a reveal deck (.html): every slide reveal_slice.py finds in the deck (File, under the root), or
  in the Scope cell's `#/A-#/B` range of horizontal slides, must have a block; a range past the
  deck's last slide, or one holding no slide, fails.
- the Ed digest (a file under sources/ed/): skipped, since it is read as it is.
- anything else (a Word file, code, an ebook): at least one block, and when it has page blocks
  and a Pages count, every in-scope page.
Blocks are the `### [<doc> <locator>] title` headers in _build/extract/*.md: `p.N` (`p.N-M` for a
run of build frames), `#/h` or `#/h/v`, a question part (`Q3a`, `Q3 stem`) or any other name (a
source without pages). Inside a question block, a `[<doc> p.N]` cite covers that page when <doc>
is the block's own or an answers file (Answers `yes`) whose `solutions to <doc>` note names the
block's doc (with no such note, any doc's; a warning says so).

It prints one line per doc: what is in scope, what has a block, `(image only` entries, and
`UNREADABLE:` flags (the brief's closing `Coverage:` line doesn't count). Exit 1 on a page or
slide with no block, an in-scope page not rendered, a doc with no blocks, an open `UNREADABLE:`
flag, a Scope it can't read, any block for a `reserved` doc (FB-023) or for a `pending` one (its
file has arrived: give it a real Scope); 0 otherwise. Blocks for a doc id MANIFEST lacks, or for
an `out` row, are warnings. Stdlib only, plus reveal_slice.py from this directory."""
import argparse
import contextlib
import importlib.util
import io
import os
import re
import sys

HEADER = re.compile(r"^###\s+\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?:p\.(?P<page>\d+)(?:-(?P<end>\d+))?"
                    r"|(?P<frag>#/\d+(?:/\d+)?)|(?P<q>Q[\w.]+(?: stem)?)|(?P<other>[^\]]+))\]")
CITE = re.compile(r"\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?P<loc>[^\]]+)\]")
CITE_PAGES = re.compile(r"pp?\.\s*(?P<page>\d+)(?:\s*-\s*(?P<end>\d+))?")
IMAGE_ONLY = re.compile(r"\(image only\b", re.I)
UNREADABLE = re.compile(r"\bUNREADABLE:")
PAGE_FILE = re.compile(r"p-(\d+)\.png$")
# The Scope cell of an in-scope row, after its parenthetical notes are dropped: `in` or `concepts
# only`, then nothing, `PDF pp.A-B[, C-D]` (or `p.A`) or `slides #/A-#/B`. Anything else is
# refused rather than guessed at, since a misread range would leave pages unchecked.
SCOPE = re.compile(r"(?:in|concepts only)\s*(?:,\s*(?P<rest>.*))?", re.I)
SCOPE_PAGES = re.compile(r"(?:PDF\s+)?pp?\.\s*(?P<r>\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*)")
SCOPE_SLIDES = re.compile(r"slides\s+#/(\d+)\s*-\s*(?:#/)?(\d+)")
SOLUTIONS_TO = re.compile(r"solutions? (?:to|for) ([A-Za-z0-9_.-]*[A-Za-z0-9_-])", re.I)
NOTE_RANGE = re.compile(r"\bpp\.\s*\d|\bp\.\s*\d+\s*-\s*\d")
KINDS = ("in", "concepts", "reserved", "pending", "out")
EN_DASH = chr(0x2013)


def numbers(text):
    """`17-20, 23` -> {17, 18, 19, 20, 23}."""
    out = set()
    for a, b in re.findall(r"(\d+)(?:\s*-\s*(\d+))?", text):
        out.update(range(int(a), int(b or a) + 1))
    return out


def manifest_rows(path):
    """{doc id: {"file", "pages", "scope", "kind", "answers", "answers_for"}} for every row of
    the table. Columns are found by their header names, so an older MANIFEST with fewer columns
    reads right; `answers_for` is the docs a `solutions to <doc>` note pairs an answers file
    with (empty: any doc)."""
    rows, cols = {}, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.lstrip().startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cols is None:
                if cells and cells[0].lower().startswith("doc"):
                    cols = {name.lower(): i for i, name in enumerate(cells)}
                    lacking = [c for c in ("file", "scope") if c not in cols]
                    if lacking:
                        raise ValueError(f"MANIFEST.md's table has no {' or '.join(lacking)} "
                                         "column")
                continue
            if re.fullmatch(r"[\s:-]*", cells[0]):
                continue
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", cells[0]):
                raise ValueError(f"a MANIFEST.md row whose Doc id isn't a bare id: {line.strip()}")

            def cell(name):
                i = cols.get(name)
                return cells[i] if i is not None and i < len(cells) else ""
            scope = cell("scope")
            word = (re.match(r"[a-z]+", scope.lower()) or [""])[0]
            rows[cells[0]] = {"file": cell("file").strip("`"), "pages": cell("pages"),
                              "scope": scope, "kind": word,
                              "answers": cell("answers").lower().startswith("yes"),
                              "answers_for": set(SOLUTIONS_TO.findall(cell("notes")))}
    return rows


def rendered(root, doc):
    d = os.path.join(root, "_build", "pages", doc)
    if not os.path.isdir(d):
        return set()
    return {int(m.group(1)) for m in map(PAGE_FILE.search, os.listdir(d)) if m}


def span(m):
    lo = int(m.group("page"))
    return range(lo, max(lo, int(m.group("end") or lo)) + 1)


def blocks(root, rows):
    """{doc: {"pages", "frags", "blocks", "questions", "image_only", "unreadable"}}."""
    out = {}

    def entry(doc):
        return out.setdefault(doc, {"pages": set(), "frags": set(), "blocks": 0, "questions": 0,
                                    "image_only": 0, "unreadable": 0})

    def answers(cited, own):
        """Whether a question block of `own` may cover pages of `cited`: its own doc, or an
        answers file that is paired with it (or with nothing in particular)."""
        row = rows.get(cited)
        return cited == own or bool(row and row["answers"]
                                    and (not row["answers_for"] or own in row["answers_for"]))
    d = os.path.join(root, "_build", "extract")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".md"):
            continue
        current, own, question = None, None, False
        with open(os.path.join(d, name), encoding="utf-8") as f:
            for line in f:
                m = HEADER.match(line)
                if m:
                    own = m.group("doc")
                    current = entry(own)
                    current["blocks"] += 1
                    if m.group("q"):
                        current["questions"] += 1
                    elif m.group("frag"):
                        current["frags"].add(m.group("frag"))
                    elif m.group("page"):
                        current["pages"].update(span(m))
                    question = bool(m.group("q"))
                    continue
                if current is None or line.startswith("Coverage:"):
                    continue
                current["image_only"] += bool(IMAGE_ONLY.search(line))
                current["unreadable"] += len(UNREADABLE.findall(line))
                if not question:
                    continue
                for c in CITE.finditer(line):
                    cited = c.group("doc")
                    if not answers(cited, own):
                        continue
                    p = CITE_PAGES.fullmatch(c.group("loc").strip())
                    if p:
                        entry(cited)["pages"].update(span(p))
                    elif cited != own:
                        entry(cited)["blocks"] += 1  # an answers file without pages
    return out


def spans(nums):
    """[3, 4, 5, 9] -> "3-5, 9"."""
    out, nums = [], sorted(nums)
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(f"{nums[i]}-{nums[j]}" if j > i else str(nums[i]))
        i = j + 1
    return ", ".join(out)


def scope_of(row):
    """("all", None), ("pages", {numbers}), ("slides", (lo, hi)) or ("bad", None)."""
    scope = row["scope"].replace(EN_DASH, "-")
    if any(NOTE_RANGE.search(note) for note in re.findall(r"\([^)]*\)", scope)):
        return "bad", None
    text = re.sub(r"\([^)]*\)", " ", scope).strip()
    m = SCOPE.fullmatch(text)
    if not m:
        return "bad", None
    rest = (m.group("rest") or "").strip()
    if not rest:
        return "all", None
    m = SCOPE_PAGES.fullmatch(rest)
    if m:
        return "pages", numbers(m.group("r"))
    m = SCOPE_SLIDES.fullmatch(rest)
    if m and int(m.group(1)) <= int(m.group(2)):
        return "slides", (int(m.group(1)), int(m.group(2)))
    return "bad", None


def page_scope(row, scope):
    """The in-scope page numbers, or None when the row gives neither a range nor a count."""
    kind, value = scope
    if kind == "pages":
        return value
    if row["pages"].isdigit():
        return set(range(1, int(row["pages"]) + 1))
    return None


def deck_slides(root, row, scope):
    """The fragments of the deck's in-scope slides, or a string saying why there are none."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("reveal_slice",
                                                  os.path.join(here, "reveal_slice.py"))
    reveal_slice = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reveal_slice)
    try:
        with open(os.path.join(root, row["file"]), encoding="utf-8") as f:
            source = f.read()
        with contextlib.redirect_stderr(io.StringIO()):
            slides = reveal_slice.slides(source)
    except (OSError, SystemExit) as e:
        return f"can't read the deck {row['file']}: {e}"
    last = max((int(frag.split("/")[1]) for frag, _ in slides), default=-1)
    lo, hi = scope[1] if scope[0] == "slides" else (0, last)
    if hi > last:
        return f"the scope ends at #/{hi}, past the deck's last slide #/{last}"
    want = [frag for frag, _ in slides if lo <= int(frag.split("/")[1]) <= hi]
    return want or "no slides in scope"


def check(root, doc, row, b):
    """(line, failed) for one in-scope doc."""
    flags = f"{b['image_only']} image only, {b['unreadable']} UNREADABLE"
    if b["questions"]:
        flags = f"{b['questions']} question blocks, " + flags
    name = row["file"].lower()
    if name.startswith("sources/ed/"):
        return f"{doc}: the Ed digest, read as it is (not extracted)", False
    scope = scope_of(row)
    if scope[0] == "bad":
        return (f"{doc}: SCOPE NOT UNDERSTOOD: {row['scope']!r}; write `in`, "
                "`in, PDF pp.A-B` or `in, slides #/A-#/B`"), True
    open_flags = b["unreadable"] > 0
    if name.endswith((".html", ".htm")):
        if scope[0] == "pages":
            return f"{doc}: a deck's scope is a slide range (`in, slides #/A-#/B`)", True
        want = deck_slides(root, row, scope)
        if isinstance(want, str):
            return f"{doc}: {want}", True
        missing = [f for f in want if f not in b["frags"]]
        line = f"{doc}: {len(want)} slides in scope, {len(want) - len(missing)} with a block, {flags}"
        return (line + (f"; MISSING {', '.join(missing)}" if missing else ""),
                bool(missing) or open_flags)
    if scope[0] == "slides":
        return f"{doc}: a slide range fits only a reveal deck; use `in, PDF pp.A-B`", True
    pages_in = page_scope(row, scope)
    if name.endswith(".pdf"):
        pages = rendered(root, doc)
        if pages_in is None:
            pages_in = pages
            note = " (Pages isn't a number: checked against the renders)"
        else:
            note = ""
        unrendered = pages_in - pages
        missing = pages_in - b["pages"] - unrendered
        line = (f"{doc}: {len(pages_in)} pages in scope, {len(pages_in & pages)} rendered, "
                f"{len(pages_in & b['pages'])} with a block, {flags}{note}")
        if missing:
            line += f"; MISSING {spans(missing)}"
        if unrendered:
            line += f"; NOT RENDERED {spans(unrendered)}"
        return line, bool(missing or unrendered or not pages_in) or open_flags
    if not b["blocks"]:
        return f"{doc}: no blocks; MISSING all", True
    if pages_in and b["pages"]:
        missing = pages_in - b["pages"]
        line = f"{doc}: {len(pages_in)} pages in scope, {len(pages_in & b['pages'])} with a block, {flags}"
        return (line + (f"; MISSING {spans(missing)}" if missing else ""),
                bool(missing) or open_flags)
    return f"{doc}: {b['blocks']} blocks, {flags}", open_flags


def main(argv=None):
    p = argparse.ArgumentParser(description="Check the extracts against MANIFEST.md's scope.")
    p.add_argument("--root", default=".", help="the exam-prep root (default: the cwd)")
    args = p.parse_args(argv)
    manifest = os.path.join(args.root, "MANIFEST.md")
    if not os.path.exists(manifest):
        print(f"extract_check: no MANIFEST.md in {os.path.abspath(args.root)}", file=sys.stderr)
        return 2
    try:
        rows = manifest_rows(manifest)
    except ValueError as e:
        print(f"extract_check: {e}")
        return 1
    if not rows:
        print("extract_check: MANIFEST.md has no rows under a `| Doc id | File | ... |` header")
        return 1
    found = blocks(args.root, rows)
    empty = {"pages": set(), "frags": set(), "blocks": 0, "questions": 0, "image_only": 0,
             "unreadable": 0}
    bad = False
    for doc, row in rows.items():
        if row["kind"] not in KINDS:
            print(f"{doc}: SCOPE NOT UNDERSTOOD: {row['scope']!r}; it starts with one of "
                  "in, concepts only, reserved, pending, out")
            bad = True
            continue
        if row["answers"] and not row["answers_for"]:
            print(f"warning: {doc} holds answers but no `solutions to <doc>` note: its cites "
                  "count for any question block")
        if row["kind"] not in ("in", "concepts"):
            continue
        line, failed = check(args.root, doc, row, found.get(doc) or empty)
        print(line)
        bad |= failed
    for doc in sorted(found):
        kind = rows[doc]["kind"] if doc in rows else None
        if kind == "reserved":
            print(f"{doc}: RESERVED, yet the extracts hold {found[doc]['blocks']} blocks for it "
                  "(FB-023): delete them and find which agent opened it")
            bad = True
        elif kind == "pending":
            print(f"{doc}: PENDING, yet the extracts hold {found[doc]['blocks']} blocks for it: "
                  "the file has arrived, so give its row a real Scope (01-ingest, step 5) and "
                  "rerun")
            bad = True
        elif kind is None:
            print(f"warning: blocks for {doc}, a doc id MANIFEST.md lacks (a typo in a header?)")
        elif kind not in ("in", "concepts"):
            print(f"warning: blocks for {doc}, whose MANIFEST.md scope is {rows[doc]['scope']!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
