#!/usr/bin/python3 -I
"""Check stage 02's extracts and solutions files against MANIFEST.md, from the hub root.

  extract_check.py [--root DIR]           check; exit 0 or 1
  extract_check.py --parts [--root DIR]   print the self-test's PARTS and exit 0

MANIFEST's table is read by its header names (Doc id, File, Pages, Scope, Answers, Notes; any
other column, such as the optional By, is ignored); with no Doc id, File or Scope column it
fails. Every row's Scope starts with `in`, `concepts only`,
`reserved`, `pending` or `out`; any other word fails. An in-scope Scope is `in` or `concepts
only`, then nothing, `PDF pp.A-B[, C-D]` or `slides #/A-#/B`, with notes in parentheses (a note
holding a page range fails: it would go unchecked); any other wording fails as SCOPE NOT
UNDERSTOOD. Each in-scope row is checked by its source's kind:
- a PDF (its File ends in .pdf): every in-scope page must be rendered under _build/pages/<doc>/
  and have a block. The in-scope pages are the Scope cell's ranges, else 1 to its Pages.
- a reveal deck (.html holding an element of class `slides`, or any .html the Scope gives a
  `slides #/A-#/B` range): every slide reveal_slice.py finds in the deck (File, under the root),
  or in that range of horizontal slides, must have a block; a range past the deck's last slide,
  one holding no slide, or a file it can't read, fails.
- a course page saved as HTML (.html with no `slides` element): checked as any other text
  source, below.
- the Ed digest (a file under sources/ed/): skipped, since it is read as it is.
- anything else (a Word file, code, an ebook): at least one block, and when it has page blocks
  and a Pages count, every in-scope page.
Blocks are the `### [<doc> <locator>] title` headers in _build/extract/*.md and
_build/solutions/*.md: `p.N` (`p.N-M` for a run of build frames), `#/h` or `#/h/v`, a question
part (`Q3a`), a stem (`Q3 stem`) or any other name (a source without pages). Inside a question
block, a `[<doc> p.N]` cite covers that page when <doc> is the block's own or an answers file
(Answers `yes`) whose `solutions to <doc>` note names the block's doc. A question block in a
solutions file covers pages that way but counts as no block of its doc.

Solved docs: an in-scope Answers `yes` doc (`yes, attempted` too, as the tutor marks a set once
it is attempted) with a `solutions to <doc>` note solves the docs it names; the note reads a list
(`solutions to HW1, HW2 and HW3`, `solutions to HW1 & HW2`), and every word in it must be a doc id
in MANIFEST. One with no note solves itself (a past exam with its key) and names its key pages
anywhere in its Notes: `key p.N`, `key pp. N-M` (lists and ranges, `key pp. 7-9, 11`), or `key
inline` (each solution sits under its question; no page is a key page), as in `Practice exam 1;
key pp. 7-9`. Only the named key pages are answers pages of such a doc, whatever any `Pages:` line
says; its other pages (cover, rules, formula sheet) are question material. An answers doc is any
Answers `yes` doc. Extract agents keep every answer out of _build/extract/<name>.md and write it to
_build/solutions/<name>.md, one `### [<doc> Q1a]` block per question part of a solved doc holding
a `Solution [<doc> <loc>]: ...` line or the line `No official solution.`. It fails, naming the
file and line:
- NO SOLUTION BLOCK: a question part of a solved doc with a block in an extract and none in any
  solutions file.
- in a solutions file: a part block naming a part no extract has (NO SUCH PART), a part with two
  blocks (TWO SOLUTIONS BLOCKS), a part block holding neither form (EMPTY SOLUTIONS BLOCK).
- in an extract: SOLUTION IN AN EXTRACT, a bracketed `Solution [<doc> <loc>]` or bold
  `**Solution:**` line, fenced or not, in a block of a solved doc, or in any block (a lecture's
  too) when a cite on it names a solved doc or an answers doc; CITES AN ANSWERS PAGE, a line
  citing an answers page (answers_cite(): any page of an answers file paired with other docs; for
  a doc with its own key, a key page its note names, or a cite naming no page and no question
  part, `[PE1 Key]`), a `Pages:` line holding only cites and the closing `Coverage:` line aside;
  AN ANSWERS PAGE IN AN EXTRACT, a block of a separate answers file, or a key page's or page-less
  section block of a doc with its own key.
- the lines before a file's first block header (its `# ...` title, `Sources:` and `Every page
  image was viewed.` lines pass): in an extract, a `Solution [` or `**Solution:**` line fails as
  SOLUTION IN AN EXTRACT and an answers cite as CITES AN ANSWERS PAGE; in either directory, an
  open `UNREADABLE:` flag fails and an illegible value is listed, by file and line.
- in MANIFEST, for an in-scope Answers `yes` row: NOTE NAMES NO DOC, a word in its `solutions to`
  note that is no doc id; NO KEY NOTE, a row with neither a `solutions to` note nor a key note;
  ANSWERS WITH NO PAIRING, one with no `solutions to` note and no question block in any extract.
It warns, by file and line, outside a code fence in a solved doc's extract block, for a person to
read: on a loose `Solution:` line (a `#### Solution` heading, `Solutions:`), and on an answer line,
one starting (after list or quote marks) `Answer:`, `Answers:`, `Ans:`, `Final answer:`,
`*Solution*:` or `Solution (<cite>):` with more than blanks, underscores, dots or an ellipsis (an
answer blank) after it. It warns too on a solutions block for a stem (each part still needs its
own). A self-answering doc with no key note is read as before the note while it fails: its key
pages are those no question part's `Pages:` line names, across every extract (question_pages()).

A doc that STATUS.md names on a line starting `Unverified: <doc>,` (material added at the
student's request without an extract, FB-013) is reported as unverified while the files count
no block for it (its own headers, or a page-less cite of it as an answers file), and doesn't fail;
once they count one, its row is checked like any other. A STATUS.md it can't read exempts nothing.

It prints one line per doc: what is in scope, what has a block, `(image only` entries, and
`UNREADABLE:` flags in either directory (the brief's closing `Coverage:` line, closing(), doesn't
count; a block's own line starting `Coverage:` does), each open flag then named by file and line
with its fix (a re-read at 300 dpi on a crop: stage 02 runs unattended, so it never asks), and
the values marked `(illegible at 300 dpi: <what>)`, still unreadable after that re-read: counted
on the doc's line and each listed by file and line, never a failure. Exit 1 on a page or slide
with no block, an in-scope page not rendered, a doc with no blocks, an open `UNREADABLE:` flag, a
Scope it can't read, any block for a `reserved` doc (FB-023) or for a `pending` one (its file has
arrived: give it a real Scope), or any failure above; 2 with no MANIFEST.md; 0 otherwise. Blocks
for a doc id MANIFEST lacks, or for an `out` row, are warnings.

`--parts` prints the number of question-part blocks in the solutions files holding a `Solution
[<doc> <loc>]` line (the self-test's PARTS, verify-selftest.py); an answers file's page blocks and
a `No official solution.` block never count. With no MANIFEST.md it exits 2 as the check does, so
a wrong root never reads as 0 parts. Stdlib only, plus reveal_slice.py from this directory."""
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
# A value still illegible after the re-read at 300 dpi, marked so (02-extract): counted per doc
# and listed by file and line, never a failure, since stage 02 runs unattended and no further
# read can recover it.
ILLEGIBLE = re.compile(r"\(illegible at 300 dpi:\s*[^)\s][^)]*\)", re.I)
PAGE_FILE = re.compile(r"p-(\d+)\.png$")
# The Scope cell of an in-scope row, after its parenthetical notes are dropped: `in` or `concepts
# only`, then nothing, `PDF pp.A-B[, C-D]` (or `p.A`) or `slides #/A-#/B`. Anything else is
# refused rather than guessed at, since a misread range would leave pages unchecked.
SCOPE = re.compile(r"(?:in|concepts only)\s*(?:,\s*(?P<rest>.*))?", re.I)
SCOPE_PAGES = re.compile(r"(?:PDF\s+)?pp?\.\s*(?P<r>\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*)")
SCOPE_SLIDES = re.compile(r"slides\s+#/(\d+)\s*-\s*(?:#/)?(\d+)")
# A `solutions to <doc>` note (or `solutions for`) names a list of docs: `solutions to HW1`,
# `solutions to HW1, HW2 and HW3`, `solutions to HW1 & HW2`. Every word in the list must be a doc
# id in MANIFEST (NOTE NAMES NO DOC): `solutions to Homework 1 (HW1)` names "Homework", which fails
# rather than leaving HW1 silently unsolved.
DOC_WORD = r"[A-Za-z0-9_.-]*[A-Za-z0-9_-]"
NOTE_SEP = r"\s*(?:,\s*(?:and\s+)?|&\s*|\s\band\s+)"
SOLUTIONS_TO = re.compile(r"\bsolutions? (?:to|for)\s+(" + DOC_WORD + r"(?:" + NOTE_SEP + DOC_WORD
                          + r")*)", re.I)
# A self-answering row's key note (Answers `yes`, no `solutions to` note): `key p.N`, `key pp.
# N-M`, `key pp. 7-9, 11` (the lists and ranges LOC_PAGES reads), or `key inline` (each solution
# sits under its question, so no page is a key page).
KEY_NOTE = re.compile(r"\bkey:?\s+(?:(?P<inline>inline)\b|(?P<pages>pp?\.\s*\d[\d\s,.pP\-"
                      + chr(0x2013) + r"]*))", re.I)
NOTE_RANGE = re.compile(r"\bpp\.\s*\d|\bp\.\s*\d+\s*-\s*\d")
KINDS = ("in", "concepts", "reserved", "pending", "out")
EN_DASH = chr(0x2013)
# STATUS.md's `Unverified: <doc>, <section ids>, <date>` line (11-next-exam, FB-013), as a list
# item or bare; a mention mid-line names nothing.
UNVERIFIED = re.compile(r"^[-*\s]*Unverified:\s*([A-Za-z0-9_.-]*[A-Za-z0-9_-])(?=[,\s]|$)", re.M)
# The extract brief's closing line, whole: `Coverage: <range>; N blocks; K image only (...); U
# flagged unreadable.` Older extracts end it `0 UNREADABLE.` or, with `1 (image only: p.1)`,
# `UNREADABLE: none.`. The flagged count may carry its detail, in parentheses or after a colon
# (`1 flagged UNREADABLE: p.3 weight.`). A `Coverage:` start, even with `; N blocks;` after it,
# is a solution's or a tool's line as often as not (`Coverage: 4/5 statements; 3 blocks; 2 of 3
# branches` lacks the image-only and unreadable parts). mock_leak.py's NOTE_LINE mirrors this.
COVERAGE = re.compile(r"^Coverage:\s.*;\s*\d+\s+blocks?\s*;\s*\d+\s*\(?image\s+only\b.*;\s*"
                      r"(?:\d+\s+(?:flagged\s+)?unreadable(?:\s*\(.*\)|\s*:.*)?"
                      r"|unreadable:\s*none)\.?\s*$", re.I)
# A part's `Pages:` line, and each page list in a cite's locator: `p.2`, `pp. 2-3`, `P.3`, a range
# with an en dash, `pp.2, 5`; `p.2, p.3` is two lists.
PAGES_LINE = re.compile(r"^[-*\s]*Pages:(.*)")
LOC_PAGES = re.compile(r"\bpp?\.\s*(?P<list>\d+(?:\s*[-–]\s*\d+)?"
                       r"(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*)", re.I)
QUESTION_LOC = re.compile(r"Q\d", re.I)
SEPARATORS = re.compile(r"(?:[\s,;&]|and\b)*")
PART = re.compile(r"Q[\w.]+")
# A solution in an extract, either form the extract format has written: the bracketed
# `Solution [<doc> <loc>]` (bold around the word or the whole marker, `Official` before it, a list,
# quote or heading mark first, more cites after it) then a colon or the line's end, so starter code
# such as `solution[i + 1] = best(i)` isn't one; or the bold `**Solution:**`, `**Solution**`,
# `**Official solution:**`. Neither is ever code, so both count inside a fence too.
CITED = r"\[[A-Za-z0-9_.-]+\s+[^\]\s][^\]]*\]"
BRACKETED = re.compile(r"^[-*>#\s]*(?:\*\*)?(?:official\s+)?solutions?(?:\*\*)?\s*" + CITED
                       + r"(?:\s*" + CITED + r")*(?:\*\*)?\s*(?::|$)", re.I)
BOLD = re.compile(r"^[-*>#\s]*\*\*(?:official\s+)?solutions?\s*:?\s*\*\*", re.I)
# A loose `Solution:` line (`Solutions:`, a `#### Solution` heading): question text as often as an
# answer, so a warning, read outside a code fence only.
LOOSE = re.compile(r"^[-*>#\s]*(?:\*\*)?(?:official\s+)?solutions?\b(?:\*\*)?\s*(?:\[|:|\*\*|$)",
                   re.I)
# A solutions block's two forms (the extract brief): `Solution [<doc> <loc>]: ...` (a list mark
# before it, more cites after it, then a colon or the line's end), or the line `No official
# solution.` alone.
SOLVED = re.compile(r"^[-*\s]*Solution \[[A-Za-z0-9_.-]+\s+[^\]\s][^\]]*\](?:\s*" + CITED
                    + r")*\s*(?::|$)")
NO_SOLUTION = "No official solution."
# An answer line in a solved doc's extract block: after any list or quote marks, `Answer:`,
# `Answers:`, `Ans:`, `Final answer:` (bold or not), `*Solution*:` or `Solution (<cite>):`. Question
# text uses these too (`Answer: ____` is the blank the student fills), so a warning, read outside a
# code fence only, and none when what follows is only blanks, underscores, dots or an ellipsis.
ANSWER_LINE = re.compile(r"^(?:\s*(?:[-+*]|\d+[.)])\s+|\s*>\s?)*\s*"
                         r"(?:(?:\*\*)?(?:answers?|ans|final\s+answer)\s*:(?:\*\*)?"
                         r"|\*solution\*\s*:|solution\s*\([^)]*\)\s*:)(?P<rest>.*)$", re.I)
ANSWER_BLANK = re.compile(r"[\s_.\\" + chr(0x2026) + r"]*")
# A file's opening lines that pass as they are: its `# ...` title, `Sources:` and `Every page image
# was viewed.`
PREAMBLE_OK = re.compile(r"^(?:#\s|Sources:|Every page image was viewed\.)")
# CommonMark: an opener is at most 3 spaces in, a run of 3+ backticks or tildes, then an info
# string (a backtick opener's holds no backtick). A closer is at most 3 spaces in, a run of the
# opener's character at least as long, then nothing but blanks. Anything else is fence content.
OPENER = re.compile(r"^ {0,3}(?P<mark>`{3,}(?=[^`]*$)|~{3,})")
CLOSER = re.compile(r"^ {0,3}(?P<mark>`{3,}|~{3,})[ \t]*$")
DIRS = ("extract", "solutions")


def numbers(text):
    """`17-20, 23` -> {17, 18, 19, 20, 23}."""
    out = set()
    for a, b in re.findall(r"(\d+)(?:\s*-\s*(\d+))?", text):
        out.update(range(int(a), int(b or a) + 1))
    return out


def note_docs(notes):
    """Every word a Notes cell's `solutions to` notes name (SOLUTIONS_TO), doc ids or not."""
    out = set()
    for m in SOLUTIONS_TO.finditer(notes):
        out.update(w for w in re.split(NOTE_SEP, m.group(1)) if w)
    return out


def key_pages(notes):
    """The key pages a Notes cell's key notes name (KEY_NOTE): a set of page numbers, empty for
    `key inline`, or None when it has no key note."""
    out = None
    for m in KEY_NOTE.finditer(notes):
        out = (out or set()) | (loc_pages(m.group("pages")) if m.group("pages") else set())
    return out


def manifest_rows(path):
    """{doc id: {"file", "pages", "scope", "kind", "answers", "answers_for", "key"}} for every row
    of the table. Columns are found by their header names, so an older MANIFEST with fewer columns
    reads right; `answers_for` is the words a `solutions to <doc>` note names, the docs it pairs an
    answers file with (empty: it solves itself, solved()); `key` is key_pages()."""
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
                              "answers_for": note_docs(cell("notes")),
                              "key": key_pages(cell("notes"))}
    return rows


def solved(rows):
    """The docs with official solutions: each doc an in-scope Answers `yes` row's `solutions to
    <doc>` note names, or the row's own doc when it has no such note (a past exam with its key).
    An answers row that is reserved, pending or out solves nothing: no agent reads it."""
    out = set()
    for doc, row in rows.items():
        if row.get("answers") and row.get("kind") in ("in", "concepts"):
            out |= row.get("answers_for") or {doc}
    return out


def rendered(root, doc):
    d = os.path.join(root, "_build", "pages", doc)
    if not os.path.isdir(d):
        return set()
    return {int(m.group(1)) for m in map(PAGE_FILE.search, os.listdir(d)) if m}


def span(m):
    lo = int(m.group("page"))
    return range(lo, max(lo, int(m.group("end") or lo)) + 1)


def closing(lines):
    """The indices of the file's closing `Coverage:` lines: a line of the brief's form (COVERAGE)
    with nothing but blank lines after it up to the next block header or the end of the file. Any
    other line starting `Coverage:` is the block's own text."""
    out, tail = set(), True
    for i in range(len(lines) - 1, -1, -1):
        if HEADER.match(lines[i]):
            tail = True
        elif COVERAGE.match(lines[i]):
            if tail:
                out.add(i)
            tail = False
        elif lines[i].strip():
            tail = False
    return out


def fenced(lines):
    """The indices of the lines in a closed code fence, its fence lines included, paired as
    CommonMark pairs them (OPENER, CLOSER: a line with an info string or 4+ spaces of indent closes
    nothing). A fence still open at the next block header or closing line ends there unclosed.
    With any fence unclosed, or a closed one holding a line that could open a fence (a forgotten
    closer, nested markdown), the pairing can't be trusted: no line counts as fenced there, so
    the loose-marker warning reads every line (fail closed)."""
    spans, unclosed, start, mark = [], False, None, None
    ends = closing(lines)
    for i, line in enumerate(lines):
        line = line.rstrip("\r\n")
        if start is not None and (HEADER.match(line) or i in ends):
            unclosed, start = True, None
        if start is None:
            f = OPENER.match(line)
            if f:
                start, mark = i, f.group("mark")
            continue
        f = CLOSER.match(line)
        if f and f.group("mark")[0] == mark[0] and len(f.group("mark")) >= len(mark):
            spans.append((start, i))
            start = None
    if unclosed or start is not None:
        return set()
    return {i for a, b in spans
            if not any(OPENER.match(line.rstrip("\r\n")) for line in lines[a + 1:b])
            for i in range(a, b + 1)}


def loc_pages(loc):
    """The page numbers a cite's locator names (LOC_PAGES), every list and range in it."""
    out = set()
    for m in LOC_PAGES.finditer(loc):
        for a, b in re.findall(r"(\d+)(?:\s*[-–]\s*(\d+))?", m.group("list")):
            out.update(range(int(a), max(int(a), int(b or a)) + 1))
    return out


def files(root, kind):
    """[(path relative to root, its lines)] for each .md file under _build/<kind>/, sorted."""
    d = os.path.join(root, "_build", kind)
    out = []
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if name.endswith(".md"):
            with open(os.path.join(d, name), encoding="utf-8") as f:
                out.append((f"_build/{kind}/{name}", f.read().splitlines(keepends=True)))
    return out


def sections(lines):
    """[(header index, end index, header match)] for each block in the file."""
    heads = [(i, m) for i, m in enumerate(map(HEADER.match, lines)) if m]
    return [(i, heads[k + 1][0] if k + 1 < len(heads) else len(lines), m)
            for k, (i, m) in enumerate(heads)]


def locator(m):
    """A block header's locator, the text after its doc id inside the brackets."""
    return m.group(0).split("[", 1)[1][len(m.group("doc")):].rstrip("]").strip()


def question_pages(extracts):
    """{doc: the pages its question blocks name on their `Pages:` lines}, read across every
    extract, with a key (an empty set at least) for every doc with a question block (a part's or a
    stem's) in any of them."""
    out = {}
    for _, lines in extracts:
        for start, end, m in sections(lines):
            if not m.group("q"):
                continue
            doc = m.group("doc")
            pages = out.setdefault(doc, set())
            for line in lines[start + 1:end]:
                p = PAGES_LINE.match(line)
                if not p:
                    continue
                for c in CITE.finditer(p.group(1)):
                    if c.group("doc") == doc:
                        pages |= loc_pages(c.group("loc"))
    return out


def answers_cite(doc, loc, rows, qpages):
    """Whether a `[<doc> <loc>]` cite points into answers: any cite of an answers file whose
    `solutions to <doc>` note names other docs only; for a doc with its own key and a key note, a
    cite naming a key page the note names, or naming no page and no question part (`[PE1 Key]`);
    its other pages (cover, rules, formula sheet) are question material. A self-answering doc
    with no key note (which fails NO KEY NOTE) is read as before the note: any cite of it when it
    has no question block in any extract, else one naming a page no question part's `Pages:` line
    names, or no page and no question. `qpages` is question_pages()."""
    row = rows.get(doc) or {}
    if not row.get("answers"):
        return False
    pair = row.get("answers_for") or set()
    if pair and doc not in pair:
        return True
    key = row.get("key")
    if not pair and key is not None:
        pages = loc_pages(loc)
        if pages:
            return bool(pages & key)
        return not QUESTION_LOC.match(loc.strip())
    if doc not in qpages:
        return True
    pages = loc_pages(loc)
    if pages:
        return not pages <= qpages[doc]
    return not QUESTION_LOC.match(loc.strip())


def blocks(root, rows):
    """{doc: {"pages", "frags", "blocks", "questions", "image_only", "unreadable",
    "unreadable_at", "illegible", "illegible_at"}} across _build/extract/ and _build/solutions/,
    `unreadable_at` a list of (file, line number) for each open flag, `illegible_at` one of (file,
    line number, the marked value) for each value marked illegible at 300 dpi (ILLEGIBLE). A
    question block in a solutions file counts as no block of its doc; its cites cover pages."""
    out = {}

    def entry(doc):
        return out.setdefault(doc, {"pages": set(), "frags": set(), "blocks": 0, "questions": 0,
                                    "image_only": 0, "unreadable": 0, "unreadable_at": [],
                                    "illegible": 0, "illegible_at": []})

    def answers(cited, own):
        """Whether a question block of `own` may cover pages of `cited`: its own doc, or an
        answers file whose `solutions to <doc>` note names it."""
        row = rows.get(cited)
        return cited == own or bool(row and row["answers"] and own in row["answers_for"])
    for kind in DIRS:
        for rel, lines in files(root, kind):
            ends = closing(lines)
            for start, end, m in sections(lines):
                own = m.group("doc")
                current = entry(own)
                question = bool(m.group("q"))
                if not (question and kind == "solutions"):
                    current["blocks"] += 1
                    if question:
                        current["questions"] += 1
                    elif m.group("frag"):
                        current["frags"].add(m.group("frag"))
                    elif m.group("page"):
                        current["pages"].update(span(m))
                for i in range(start + 1, end):
                    if i in ends:
                        continue
                    line = lines[i]
                    current["image_only"] += bool(IMAGE_ONLY.search(line))
                    flags = len(UNREADABLE.findall(line))
                    current["unreadable"] += flags
                    if flags:
                        current["unreadable_at"].append((rel, i + 1))
                    for v in ILLEGIBLE.finditer(line):
                        current["illegible"] += 1
                        current["illegible_at"].append((rel, i + 1, v.group(0)))
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


def reveal_slice():
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("reveal_slice",
                                                  os.path.join(here, "reveal_slice.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_deck(root, row, scope):
    """Whether an .html source is a reveal deck: its Scope gives a slide range, or it holds an
    element of class `slides`. One it can't read counts as a deck, whose check says so."""
    if scope[0] == "slides":
        return True
    try:
        with open(os.path.join(root, row["file"]), encoding="utf-8") as f:
            source = f.read()
    except (OSError, ValueError):
        return True
    return reveal_slice().Deck(source).container is not None


def deck_slides(root, row, scope):
    """The fragments of the deck's in-scope slides, or a string saying why there are none."""
    reveal = reveal_slice()
    try:
        with open(os.path.join(root, row["file"]), encoding="utf-8") as f:
            source = f.read()
        with contextlib.redirect_stderr(io.StringIO()):
            slides = reveal.slides(source)
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
    if b["illegible"]:
        flags += f", {b['illegible']} illegible at 300 dpi"
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
    if name.endswith((".html", ".htm")) and is_deck(root, row, scope):
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


def solution_blocks(sols):
    """{(doc, part): [(file, line number, holds a `Solution [` line, holds either form)]} for each
    question part's block in the solutions files, and [(file, line number, header)] for each
    stem's block."""
    parts, stems = {}, []
    for rel, lines in sols:
        for start, end, m in sections(lines):
            q = m.group("q")
            if not q:
                continue
            if not PART.fullmatch(q):
                stems.append((rel, start + 1, f"[{m.group('doc')} {q}]"))
                continue
            body = lines[start + 1:end]
            has = any(SOLVED.match(line) for line in body)
            none = any(line.strip() == NO_SOLUTION for line in body)
            parts.setdefault((m.group("doc"), q), []).append((rel, start + 1, has, has or none))
    return parts, stems


def parts_count(root):
    """The self-test's PARTS: the question parts' blocks in the solutions files that hold a
    `Solution [<doc> <loc>]` line."""
    parts, _ = solution_blocks(files(root, "solutions"))
    return sum(has for found in parts.values() for _, _, has, _ in found)


def answers_block(doc, loc, row):
    """Why a block of an answers doc that answers_cite() reads as answers is one, for AN ANSWERS
    PAGE IN AN EXTRACT."""
    pair = row.get("answers_for") or set()
    if pair and doc not in pair:
        return f"a block of {doc}, a separate answers file (its `solutions to` note)"
    if not pair and row.get("key") is not None:
        if loc_pages(loc):
            return f"a key page of {doc}, as its MANIFEST.md key note names it"
        return f"a block of {doc}, a doc with its own key, naming no page or question part"
    return f"a block of {doc}, an answers doc, on no question part's page"


def preamble(lines):
    """The indices of a file's lines before its first block header (all of them in a file with
    none), its closing line aside."""
    heads = sections(lines)
    ends = closing(lines)
    return [i for i in range(heads[0][0] if heads else len(lines)) if i not in ends]


def solutions_check(root, rows):
    """(lines, failed): the extracts hold no answer and the solutions files hold one block per
    question part of a solved doc."""
    out, bad = [], False
    extracts = files(root, "extract")
    sols = files(root, "solutions")
    qpages = question_pages(extracts)
    named = solved(rows)

    def cites_answers(line):
        return next((c for c in CITE.finditer(line)
                     if answers_cite(c.group("doc"), c.group("loc"), rows, qpages)), None)

    def pages_only(line):
        p = PAGES_LINE.match(line)
        return bool(p and SEPARATORS.fullmatch(CITE.sub("", p.group(1))))

    def cites_answer(hit, target):
        return (f"CITES AN ANSWERS PAGE: {hit.group(0)}; an answer goes under its part's block "
                f"in {target}; if this line is the question's text, cite the question's own page")
    # Open flags and illegible values before a file's first block, in either directory: no doc's
    # count holds them, so each is named here.
    for rel, lines in extracts + sols:
        for i in preamble(lines):
            if UNREADABLE.search(lines[i]):
                out.append(f"{rel}:{i + 1}: UNREADABLE flag still open; re-read it at 300 dpi on "
                           "a crop (02-extract step 3.2) and replace the flag with the value")
                bad = True
            for v in ILLEGIBLE.finditer(lines[i]):
                out.append(f"{rel}:{i + 1}: {v.group(0)}, counted, not a failure")
    have, at = set(), {}
    for rel, lines in extracts:
        name = rel.rsplit("/", 1)[1]
        target = f"_build/solutions/{name}"
        ends = closing(lines)
        code = fenced(lines)
        # The lines before the first block belong to no part: a solution or an answers cite
        # there fails as it would in a block.
        for i in preamble(lines):
            line = lines[i]
            if PREAMBLE_OK.match(line):
                continue
            if BRACKETED.match(line) or BOLD.match(line):
                out.append(f"{rel}:{i + 1}: SOLUTION IN AN EXTRACT: a solution before the file's "
                           f"first block; move it to its part's block in {target}")
                bad = True
                continue
            hit = None if pages_only(line) else cites_answers(line)
            if hit:
                out.append(f"{rel}:{i + 1}: {cites_answer(hit, target)}")
                bad = True
        for start, end, m in sections(lines):
            doc, loc = m.group("doc"), locator(m)
            q = m.group("q")
            if q and PART.fullmatch(q):
                have.add((doc, q))
                at.setdefault((doc, q), (rel, start + 1, name))
            row = rows.get(doc) or {}
            if row.get("answers") and answers_cite(doc, loc, rows, qpages):
                out.append(f"{rel}:{start + 1}: AN ANSWERS PAGE IN AN EXTRACT: [{doc} {loc}] is "
                           f"{answers_block(doc, loc, row)}; move it to {target}")
                bad = True
                continue
            mine = doc in named
            for i in range(start + 1, end):
                line = lines[i]
                if i in ends:
                    continue
                if BRACKETED.match(line) or BOLD.match(line):
                    if mine:
                        out.append(f"{rel}:{i + 1}: SOLUTION IN AN EXTRACT: [{doc} {loc}] is a "
                                   f"block of {doc}, a doc with official solutions; move the "
                                   f"solution to its part's block in {target}")
                        bad = True
                        continue
                    # Any block's solution citing a solved or an answers doc (a lecture's
                    # extract quoting a homework's solution) is that doc's answer.
                    cross = next((c for c in CITE.finditer(line)
                                  if c.group("doc") in named
                                  or (rows.get(c.group("doc")) or {}).get("answers")), None)
                    if cross:
                        kind = ("a doc with official solutions" if cross.group("doc") in named
                                else "an answers doc")
                        out.append(f"{rel}:{i + 1}: SOLUTION IN AN EXTRACT: [{doc} {loc}] holds a "
                                   f"solution citing {cross.group(0)}, {kind}; a solution goes "
                                   "only in its part's block under _build/solutions/")
                        bad = True
                        continue
                if pages_only(line):
                    continue
                hit = cites_answers(line)
                if hit:
                    out.append(f"{rel}:{i + 1}: {cites_answer(hit, target)}")
                    bad = True
                    continue
                if not mine or i in code:
                    continue
                if LOOSE.match(line):
                    out.append(f"warning: {rel}:{i + 1}: a loose `Solution:` line in a block of "
                               f"{doc}, a doc with official solutions; if it gives an answer, "
                               f"move it to {target}; question text stays")
                    continue
                a = ANSWER_LINE.match(line.rstrip("\r\n"))
                if a and not ANSWER_BLANK.fullmatch(a.group("rest")):
                    out.append(f"warning: {rel}:{i + 1}: an answer line in a block of {doc}, a "
                               "doc with official solutions: if it is an answer, move it to its "
                               f"part's block in {target}")
    parts, stems = solution_blocks(sols)
    for key, found in sorted(parts.items()):
        doc, q = key
        rel, n = found[0][:2]
        if key not in have:
            out.append(f"{rel}:{n}: NO SUCH PART: [{doc} {q}] has no block in any extract; name "
                       "the extract's part in the header, or delete the block")
            bad = True
        if len(found) > 1:
            others = ", ".join(f"{r}:{k}" for r, k, _, _ in found[1:])
            out.append(f"{rel}:{n}: TWO SOLUTIONS BLOCKS for [{doc} {q}] (also {others}): keep "
                       "one")
            bad = True
        for r, k, _, ok in found:
            if not ok:
                out.append(f"{r}:{k}: EMPTY SOLUTIONS BLOCK: [{doc} {q}] holds neither a "
                           f"`Solution [<doc> <loc>]: ...` line nor the line `{NO_SOLUTION}`")
                bad = True
    for rel, n, head in stems:
        out.append(f"warning: {rel}:{n}: a solutions block for the stem {head}: each part still "
                   "needs its own block")
    for key in sorted(have):
        doc, q = key
        if doc in named and key not in parts:
            rel, n, name = at[key]
            out.append(f"{rel}:{n}: NO SOLUTION BLOCK: write its solution or "
                       f"\"{NO_SOLUTION}\" under ### [{doc} {q}] in _build/solutions/{name}")
            bad = True
    return out, bad, qpages


def unverified(root):
    """Doc ids STATUS.md's `Unverified:` lines name; none when it can't be read (fail closed)."""
    try:
        with open(os.path.join(root, "STATUS.md"), encoding="utf-8") as f:
            return set(UNVERIFIED.findall(f.read()))
    except (OSError, ValueError):
        return set()


def main(argv=None):
    p = argparse.ArgumentParser(description="Check the extracts and solutions files against "
                                            "MANIFEST.md.")
    p.add_argument("--root", default=".", help="the exam-prep root (default: the cwd)")
    p.add_argument("--parts", action="store_true",
                   help="print the number of question parts whose solutions block holds a "
                        "`Solution [` line (the self-test's PARTS) and exit")
    args = p.parse_args(argv)
    manifest = os.path.join(args.root, "MANIFEST.md")
    if not os.path.exists(manifest):
        print(f"extract_check: no MANIFEST.md in {os.path.abspath(args.root)}", file=sys.stderr)
        return 2
    if args.parts:
        print(parts_count(args.root))
        return 0
    try:
        rows = manifest_rows(manifest)
    except ValueError as e:
        print(f"extract_check: {e}")
        return 1
    if not rows:
        print("extract_check: MANIFEST.md has no rows under a `| Doc id | File | ... |` header")
        return 1
    found = blocks(args.root, rows)
    lines, bad, qpages = solutions_check(args.root, rows)
    empty = {"pages": set(), "frags": set(), "blocks": 0, "questions": 0, "image_only": 0,
             "unreadable": 0, "unreadable_at": [], "illegible": 0, "illegible_at": []}
    skip = unverified(args.root)
    for doc, row in rows.items():
        if row["kind"] not in KINDS:
            print(f"{doc}: SCOPE NOT UNDERSTOOD: {row['scope']!r}; it starts with one of "
                  "in, concepts only, reserved, pending, out")
            bad = True
            continue
        if row["kind"] not in ("in", "concepts"):
            continue
        if row["answers"]:
            for word in sorted(row["answers_for"] - set(rows)):
                print(f"{doc}: NOTE NAMES NO DOC: \"{word}\" in its solutions-to note is no doc "
                      "id in MANIFEST.md")
                bad = True
            if not row["answers_for"] and row["key"] is None:
                print(f"{doc}: NO KEY NOTE: a doc with its own key names its key pages in Notes "
                      "(\"key pp. N-M\", or \"key inline\")")
                bad = True
        if doc in skip and not (found.get(doc) or empty)["blocks"]:
            print(f"{doc}: unverified, added without an extract (STATUS `Unverified:` line, "
                  "FB-013): not checked until it has a block")
            continue
        if row["answers"] and not row["answers_for"] and doc not in qpages:
            print(f"{doc}: ANSWERS WITH NO PAIRING: an Answers `yes` doc with no question block "
                  "in any extract and no `solutions to <doc>` note; add the note to its "
                  "MANIFEST.md row's Notes")
            bad = True
        b = found.get(doc) or empty
        line, failed = check(args.root, doc, row, b)
        print(line)
        for rel, at in b["unreadable_at"]:
            print(f"{rel}:{at}: UNREADABLE flag still open; re-read it at 300 dpi on a crop "
                  "(02-extract step 3.2) and replace the flag with the value")
        for rel, at, value in b["illegible_at"]:
            print(f"{rel}:{at}: {value}, counted, not a failure")
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
    for line in lines:
        print(line)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
