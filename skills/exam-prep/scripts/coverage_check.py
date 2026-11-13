#!/usr/bin/python3 -I
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
row of its question; a deeper part, `Q3b.1`, `Q3aii` or its dotted form `Q3a.ii`, falls under its
letter, and a part of two
or more of i, v and x, `Q3ii`, is a roman part, not `i` and a sub-part). A block with any
other locator (`### [C1 main.py]`, or `Q3C`, which isn't a part) is mapped only by its doc's
`(all)` row. The solutions files (_build/solutions/*.md) hold answers, which the matrix never
maps, so their blocks are read only to pass an extract with no block of its own whose solutions
file of the same name holds one (an extract agent given only an answers file).

The figure floor (STYLE S11): each `## §N` section of the backbone carries a `- Diagram-taught:
yes|no` line beside its `- Figures:` line, and a section marked `yes` (its slides teach it through
diagrams) must name at least one `fig-` id on its Figures line. A section the floor doesn't hold
yet says `- Diagram-taught: pre-S11` (FB-015): an older section of a hub reopened for the next
exam (written before the rule), or a section a partial 10-polish figure pass didn't reach. Each
passes with a WARN line on stderr naming 10-polish's figure pass, which sets yes or no and adds
the figures. A backbone with no such line anywhere predates the rule and
gets one WARN for the whole backbone. Once any section carries a line, a section with none fails:
a fresh build that left it out looks the same as an old section, so the old ones are marked. A
line that misspells the form (`- **Diagram-taught:** yes`, `* Diagram-taught: yes`, `- Diagram
taught: yes`, any case) fails as malformed rather than reading as absent. Two lines in a section,
a value other than yes, no or pre-S11, a `yes` with no figure, or two `## §N` headings with the
same number (the second would hide the first's floor) fails.

Exit 1 when a block is unmapped, a row's cell doesn't parse, a target isn't a subsection, a line
looks like a block header but isn't one, the extracts hold no blocks (or a file holds none), or a
section breaks the figure floor; 0 otherwise. Stdlib only."""
import argparse
import os
import re
import sys

BLOCK = re.compile(r"^###\s+\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?:p\.(?P<page>\d+)(?:-(?P<end>\d+))?"
                   r"|#/(?P<h>\d+)(?:/(?P<v>\d+))?"
                   r"|Q(?P<q>\d+)(?:(?P<roman>[ivx]{2,})(?=[\] ])|(?P<letter>[a-z])(?:\.\d+|\.?[ivx]+|\d+)?"
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
SECTION_HEAD = re.compile(r"^## §(\d+)\b.*$", re.M)
DIAGRAM_TAUGHT = re.compile(r"^\s*-\s*Diagram-taught:\s*(.*)$")
# Any list, quote, heading or bold form of the words, in any case: a line this matches and
# DIAGRAM_TAUGHT doesn't is a misspelled Diagram-taught line, never an absent one.
NEAR_DIAGRAM_TAUGHT = re.compile(r"^[\s>#]*(?:[-*+]|\d+[.)])?[\s*_]*diagram[-_ ]?taught", re.I)
FIGURES = re.compile(r"^\s*-\s*Figures:(.*)$")
FIG_ID = re.compile(r"`fig-[\w-]+`")
# A backbone with no Diagram-taught line anywhere predates the rule; it passes with this warning.
PRE_S11 = ("no section carries a `Diagram-taught: yes|no` line: a backbone written before the "
           "figure floor (STYLE S11), so no section is held to it; a 10-polish figure pass adds the "
           "lines and the figures")


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


def figure_floor(backbone):
    """([problems], [warnings]) for the figure floor: each `## §N` section's `- Diagram-taught:`
    line and, when it says yes, a `fig-` id on its `- Figures:` line (a Figures line may wrap onto
    indented lines). A `pre-S11` section is a warning (FB-015); a section with no line is one only
    when no section carries a line (or a misspelled one)."""
    heads = list(SECTION_HEAD.finditer(backbone))
    found, bad, count = [], [], {}
    for head in heads:
        count[head.group(1)] = count.get(head.group(1), 0) + 1
    for num in sorted((n for n, c in count.items() if c > 1), key=int):
        bad.append(f"§{num}: DUPLICATE section number: {count[num]} `## §{num}` headings; each "
                   "section number heads one section")
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(backbone)
        body = re.split(r"^## ", backbone[head.end():end], maxsplit=1, flags=re.M)[0]
        lines = body.splitlines()
        taught, malformed, figures = [], [], ""
        for n, line in enumerate(lines):
            m = DIAGRAM_TAUGHT.match(line)
            if m:
                taught.append(m.group(1).strip())
            elif NEAR_DIAGRAM_TAUGHT.match(line):
                malformed.append(line.strip())
            m = FIGURES.match(line)
            if m:
                figures = m.group(1)
                for more in lines[n + 1:]:
                    if not more.startswith((" ", "\t")) or not more.strip():
                        break
                    figures += " " + more.strip()
        found.append((head.group(1), taught, malformed, figures))
    if not any(taught or malformed for _, taught, malformed, _ in found):
        return bad, [PRE_S11] if found else []
    warnings = []
    for num, taught, malformed, figures in found:
        for line in malformed:
            bad.append(f"§{num}: MALFORMED Diagram-taught line `{line}`: write it "
                       "`- Diagram-taught: yes|no` (or `pre-S11` for a reopened hub's older "
                       "section or one a partial figure pass didn't reach)")
        if malformed:
            continue
        if not taught:
            bad.append(f"§{num}: no `Diagram-taught: yes|no` line, though other sections carry "
                       "one: a fresh section states it, and a reopened hub's older section or one "
                       "a partial 10-polish figure pass didn't reach says "
                       "`- Diagram-taught: pre-S11` (FB-015)")
            continue
        if len(taught) > 1:
            bad.append(f"§{num}: {len(taught)} Diagram-taught lines; a section has one")
            continue
        if re.match(r"pre-S11(?:\s|$|\()", taught[0]):
            warnings.append(f"§{num}: Diagram-taught: pre-S11, a section written before the "
                            "figure floor (STYLE S11, FB-015) or not yet reached by a figure "
                            "pass, so it isn't held to it; a 10-polish figure pass sets yes or "
                            "no and adds the figure")
            continue
        word = re.match(r"(yes|no)\b", taught[0])
        if not word:
            bad.append(f"§{num}: `Diagram-taught: {taught[0]}` is neither yes nor no "
                       "(nor pre-S11)")
        elif word.group(1) == "yes" and not FIG_ID.search(figures):
            bad.append(f"§{num}: Diagram-taught: yes, but its Figures line names no `fig-` id: a "
                       "section its slides teach through diagrams leads with a figure (STYLE S11)")
    return bad, warnings


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


def solutions_blocks(root, name):
    """Whether _build/solutions/<name> holds a block: an extract whose sources were all answers
    (a separate answers file) holds none of its own, and the matrix maps no answers."""
    try:
        with open(os.path.join(root, "_build", "solutions", name), encoding="utf-8") as f:
            return any(BLOCK.match(line) for line in f)
    except OSError:
        return False


def unmapped(root):
    with open(os.path.join(root, "_build", "backbone.md"), encoding="utf-8") as f:
        backbone = f.read()
    rows, bad = matrix(backbone)
    floor, warnings = figure_floor(backbone)
    bad += floor
    total, missing = 0, []
    d = os.path.join(root, "_build", "extract")
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.lower().endswith(".md"):
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
        if not found and not solutions_blocks(root, name):
            bad.append(f"NO BLOCKS in {name} (a header that isn't `### [<doc> <locator>]`?)")
    return total, missing, bad, warnings


def main(argv=None):
    p = argparse.ArgumentParser(description="Check the backbone's coverage matrix.")
    p.add_argument("--root", default=".", help="the exam-prep root (default: the cwd)")
    args = p.parse_args(argv)
    if not os.path.exists(os.path.join(args.root, "_build", "backbone.md")):
        print("coverage_check: no _build/backbone.md here", file=sys.stderr)
        return 2
    total, missing, bad, warnings = unmapped(args.root)
    for w in warnings:
        print(f"coverage_check: WARN: {w}", file=sys.stderr)
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
