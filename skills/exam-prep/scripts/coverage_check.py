#!/usr/bin/env python3
"""Check that every extract block is mapped in the backbone's coverage matrix, from the hub root.

  coverage_check.py [--root DIR]

The matrix is the table under `## Coverage matrix` in _build/backbone.md. Its first cell lists
source blocks as comma-separated parts, each `<doc> <locator>` or, for the same doc, a bare
locator or number (an en dash reads as a hyphen):
  pages      `D4 p.17`, `D4 pp.17-20, 23`, `D4 p.1, p.32`
  slides     `D2 #/3-7` or `D2 #/3-#/7` (whole horizontal slides), `D2 #/3/1-4` (vertical ones)
  questions  `HW1 Q1-Q3` (whole questions), `HW1 Q1a-d`, `HW1 Q2.1-2.3` or `HW1 Q2.1-3` (parts),
             `HW1 Q3 stem`, `HW1 Q3a-d, Q4a-c` (a bare number after parts is refused: part or
             question?), and roman parts one at a time, `HW1 Q3i, Q3ii, Q3iii`
  all        `C1 (all)`, which maps every block of that doc
Its last cell is `skip (why)` or the subsections it maps to: `1.1`, `2.3, 2.4`, `4.2 / 4.3`, each
a number the backbone's section headings or tables define. A parenthetical after them is a note.

Every `### [<doc> <locator>]` block in _build/extract/*.md must fall inside some row: a page
block by its pages, a slide by its index, a question part by its question and part (a whole
question covers every part; a stem, or a block naming the question with no part, falls under any
row of its question; a deeper part, `Q3b.1` or `Q3aii`, falls under its letter, and a part of two
or more of i, v and x, `Q3ii`, is a roman part, not `i` and a sub-part). A block with any
other locator (`### [C1 main.py]`, or `Q3C`, which isn't a part) is mapped only by its doc's
`(all)` row.

Exit 1 when a block is unmapped, a row's cell doesn't parse, a target isn't a subsection, a line
looks like a block header but isn't one, or the extracts hold no blocks (or a file holds none);
0 otherwise. Stdlib only."""
import argparse
import os
import re
import sys

BLOCK = re.compile(r"^###\s+\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?:p\.(?P<page>\d+)(?:-(?P<end>\d+))?"
                   r"|#/(?P<h>\d+)(?:/(?P<v>\d+))?"
                   r"|Q(?P<q>\d+)(?:(?P<roman>[ivx]{2,})(?=[\] ])|(?P<letter>[a-z])(?:\.\d+|[ivx]+|\d+)?"
                   r"|\.(?P<sub>\d+)(?:[a-z]|\.\d+)?)?(?P<stem> stem)?"
                   r"|(?P<other>[^\]]+))\]")
# A line that looks like a block header but isn't one: a wrong heading level, or an h3 with no
# `[<doc> <locator>]`. Its block would otherwise vanish from the count.
DRIFT = re.compile(r"^#{1,6}\s*\[|^###\s")
DOC = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")
PAGES = re.compile(r"pp?\.\s*(\d+)(?:\s*-\s*(\d+))?")
SLIDE_RANGE = re.compile(r"#/(\d+)(?:\s*-\s*(?:#/)?(\d+))?")
SLIDE_VERTICAL = re.compile(r"#/(\d+)/(\d+)(?:\s*-\s*(?:#/\1/)?(\d+))?")
QUESTION_RANGE = re.compile(r"Q(\d+)(?:\s*-\s*Q?(\d+))?")
QUESTION_STEM = re.compile(r"Q(\d+)\s+stem")
QUESTION_ROMAN = re.compile(r"Q(\d+)([ivx]{2,})")
QUESTION_LETTERS = re.compile(r"Q(\d+)([a-z])(?:\s*-\s*(?:Q\1)?([a-z]))?")
QUESTION_SUBPARTS = re.compile(r"Q(\d+)\.(\d+)(?:\s*-\s*(?:Q?\1\.)?(\d+))?")
BARE = re.compile(r"(\d+)(?:\s*-\s*(\d+))?")
SECTION = re.compile(r"^## §(\d+)\b|^\|\s*(\d+(?:\.\d+)+)\s*\|", re.M)
TARGET = re.compile(r"\d+(?:\.\d+)*")
SEPARATOR = re.compile(r"\|[\s:|-]+\|?")
EN_DASH = chr(0x2013)


def span(a, b):
    return set(range(int(a), int(b or a) + 1))


def whole(keys):
    """{key: None}: every part of each question, or every vertical slide of each slide."""
    return dict.fromkeys(keys)


def locator(text, kind):
    """(kind, numbers) for one locator, or None. Pages are a set of page numbers; slides and
    questions are {number: None for all of it, or the set of parts (letters, sub-numbers,
    `stem`, vertical indexes)}. `kind` is the previous part's, for a bare continuation."""
    m = PAGES.fullmatch(text)
    if m:
        return "pages", span(*m.groups())
    m = SLIDE_VERTICAL.fullmatch(text)
    if m:
        return "slides", {int(m.group(1)): {str(v) for v in span(m.group(2), m.group(3))}}
    m = SLIDE_RANGE.fullmatch(text)
    if m:
        return "slides", whole(span(*m.groups()))
    m = QUESTION_STEM.fullmatch(text)
    if m:
        return "questions", {int(m.group(1)): {"stem"}}
    m = QUESTION_ROMAN.fullmatch(text)
    if m:
        return "questions", {int(m.group(1)): {m.group(2)}}
    m = QUESTION_LETTERS.fullmatch(text)
    if m:
        lo, hi = m.group(2), m.group(3) or m.group(2)
        if hi < lo:
            return None
        return "questions", {int(m.group(1)): {chr(c) for c in range(ord(lo), ord(hi) + 1)}}
    m = QUESTION_SUBPARTS.fullmatch(text)
    if m:
        return "questions", {int(m.group(1)): {str(v) for v in span(m.group(2), m.group(3))}}
    m = QUESTION_RANGE.fullmatch(text)
    if m:
        return "questions", whole(span(*m.groups()))
    if text == "(all)":
        return "all", None
    m = BARE.fullmatch(text)
    if m and kind == "pages":
        return kind, span(*m.groups())
    if m and kind in ("slides", "questions"):
        return kind, whole(span(*m.groups()))
    return None


def parse_source(cell):
    """[(doc, kind, numbers)] for a first cell, or None when any part doesn't parse."""
    out, doc, kind, partial = [], None, None, False
    for part in (p.strip() for p in cell.replace(EN_DASH, "-").split(",")):
        # A bare number after parts (`Q2.1, 4`, `#/3/1-2, 5`) could mean a part or a whole
        # question or slide, so it isn't guessed at.
        got = locator(part, None if partial else kind) if doc else None
        if got is None:
            head, _, rest = part.partition(" ")
            if not DOC.fullmatch(head):
                return None
            doc, kind = head, None
            got = locator(rest.strip(), None)
            if got is None:
                return None
        kind = got[0]
        partial = kind in ("slides", "questions") and any(v is not None for v in got[1].values())
        out.append((doc, kind, got[1]))
    return out


def merge(into, parts):
    """Add {number: parts} to a row's slides or questions; None (all of it) wins."""
    for key, sub in parts.items():
        if sub is None or (key in into and into[key] is None):
            into[key] = None
        else:
            into[key] = into.get(key, set()) | sub


def target_ok(cell, sections):
    """True when the last cell is `skip (why)` or names only subsections the backbone defines."""
    if re.fullmatch(r"skip\s*\(\s*[^)\s][^)]*\)", cell):
        return True
    body = re.sub(r"\([^)]*\)", " ", cell)
    parts = [p.strip() for p in re.split(r"[,/]", body)]
    return bool(parts) and all(TARGET.fullmatch(p) and p in sections for p in parts)


def matrix(backbone):
    """({doc: {"pages", "slides", "questions", "all"}}, [bad rows]) from the matrix, which runs
    from `## Coverage matrix` to the next `## ` heading."""
    try:
        table = backbone.split("## Coverage matrix", 1)[1]
    except IndexError:
        raise SystemExit("coverage_check: _build/backbone.md has no `## Coverage matrix` section")
    table = re.split(r"^## ", table, maxsplit=1, flags=re.M)[0]
    sections = {a or b for a, b in SECTION.findall(backbone)}
    lines = [line.strip() for line in table.splitlines() if line.strip().startswith("|")]
    header = {i - 1 for i, line in enumerate(lines) if SEPARATOR.fullmatch(line)}
    out, bad = {}, []
    for i, line in enumerate(lines):
        if i in header or SEPARATOR.fullmatch(line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        parts = parse_source(cells[0])
        if parts is None:
            bad.append(f"UNPARSED source cell: {line}")
            continue
        if not target_ok(cells[-1], sections):
            bad.append(f"TARGET NOT `skip (why)` OR A SUBSECTION: {line}")
        for doc, kind, nums in parts:
            row = out.setdefault(doc, {"pages": set(), "slides": {}, "questions": {},
                                       "all": False})
            if kind == "all":
                row["all"] = True
            elif kind == "pages":
                row["pages"] |= nums
            else:
                merge(row[kind], nums)
    return out, bad


def covered(row, m):
    """Whether a matrix row covers one block (a BLOCK match)."""
    if row is None:
        return False
    if row["all"]:
        return True
    if m.group("page"):
        return span(m.group("page"), max(int(m.group("page")), int(m.group("end") or 0))) \
            <= row["pages"]
    if m.group("h"):
        key, part = int(m.group("h")), m.group("v")
        parts = row["slides"]
    elif m.group("q"):
        key, part = int(m.group("q")), m.group("roman") or m.group("letter") or m.group("sub")
        parts = row["questions"]
        if key in parts and (m.group("stem") or part is None):
            return True  # a stem, or a part-less block (a stem by another name), falls under
            # any row of its question
    else:
        return False
    if key not in parts:
        return False
    return parts[key] is None or (part is not None and part in parts[key])


def unmapped(root):
    with open(os.path.join(root, "_build", "backbone.md"), encoding="utf-8") as f:
        rows, bad = matrix(f.read())
    total, missing = 0, []
    d = os.path.join(root, "_build", "extract")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".md"):
            continue
        with open(os.path.join(d, name), encoding="utf-8") as f:
            lines = f.read().splitlines()
        found = 0
        for n, line in enumerate(lines, 1):
            m = BLOCK.match(line)
            if not m:
                if DRIFT.match(line):
                    bad.append(f"HEADER NOT A BLOCK {name}:{n}: {line.strip()}")
                continue
            total += 1
            found += 1
            if not covered(rows.get(m.group("doc")), m):
                missing.append(f"{m.group(0)[4:].strip()} ({name})")
        if not found:
            bad.append(f"NO BLOCKS in {name} (a header that isn't `### [<doc> <locator>]`?)")
    return total, missing, bad


def main(argv=None):
    p = argparse.ArgumentParser(description="Check the backbone's coverage matrix.")
    p.add_argument("--root", default=".", help="the exam-prep root (default: the cwd)")
    args = p.parse_args(argv)
    if not os.path.exists(os.path.join(args.root, "_build", "backbone.md")):
        print("coverage_check: no _build/backbone.md here", file=sys.stderr)
        return 2
    total, missing, bad = unmapped(args.root)
    print(f"{total} extract blocks; {len(missing)} unmapped")
    for m in missing:
        print(f"  UNMAPPED {m}")
    for b in bad:
        print(f"  {b}")
    if not total:
        print("  NO EXTRACT BLOCKS at all: run 02-extract first")
    return 1 if (missing or bad or not total) else 0


if __name__ == "__main__":
    sys.exit(main())
