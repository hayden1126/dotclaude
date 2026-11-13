#!/usr/bin/python3 -I
"""Write the question-only copies of stage 02's extracts, from the hub root (hard rule 4, FB-056, FB-191).

  qonly.py [--root DIR]           write, keep or remove the copies
  qonly.py --parts [--root DIR]   print how many solution markers it cuts, write nothing

An extract of a set with official solutions holds each solution under the question part it
answers. An agent that must not see answers (agent-briefs.md: the gap scan, the audits, the mock
writer) reads `_build/q-only/<name>.md` instead of `_build/extract/<name>.md`: the same file with
every answer taken out, the questions, figures and given data kept verbatim.

What counts as an answer, by the extract format (02-extract, "Solutions in an extract"):
- a solution: its marker line, `Solution [<doc> <locator>]: ...` (also `**Solution:**`, a
  `#### Solution` heading, either with a list or quote mark before it), through the end of its
  block: the next `### [<doc> <locator>]` header, the closing `Coverage:` line, or the end of the
  file. The closing line is the brief's whole `Coverage: <range>; N blocks; K image only (...); U
  flagged unreadable.` (or an older extract's `0 UNREADABLE.` / `UNREADABLE: none.` tail; the
  flagged count may carry its detail, `1 flagged UNREADABLE: p.3 weight.`) with
  nothing but blank lines after it up to the next header or the end of the file (closing()): a
  solution's own `Coverage: 3/4 = 75%` or `Coverage: 4/5 statements; 3 blocks; 2 of 3 branches`
  line, or one of the closing form with more text after it, is part of the block and goes with
  the cut. A closed fence's lines don't end it. Fences are read as CommonMark reads them
  (fences()).
  The bracketed marker, `Solution [<doc> <locator>]` then a colon or the line's end, cuts
  wherever it sits, in a fence or not: starter code never writes it (`solution[i + 1] = x` isn't
  one). So does the bold marker (`**Solution:**`, `**Solution**`, `**Official solution:**`), which
  is Markdown and never a code comment: a starter fence whose closer was forgotten, closed by the
  solution's own bare fence line, used to hide it. Those strict forms cut in every block. In a
  question part's block (`### [<doc> Q1a]`, never a stem's or a page's) of a doc with solutions
  (an Answers `yes` doc, one a `solutions to <doc>` note names, or any doc while an Answers `yes`
  row has no such note, since that row pairs with any doc: solved()), wider forms cut too: the
  word `Worked solution`, `Answer`, `Answer key` or `Key`, and a qualifier that names a part
  (`Solution to Q1a [...]:`, `Solution, part (a) [...]:`, `**Solution (Q1):**`, `**Answer:**`,
  `Answer [<answers cite>]:`; the bracketed form with a qualifier only with its colon, and with
  `Answer` or `Key` only when its first cite points into answers: bracketed()). Not every line
  shaped so is one (wide_form()): a plain `Key:`, `Keys:` or `Answer:` (no bold, no qualifier,
  no cite) is a legend, the data or an answer blank as often as a solution, so it never cuts;
  nor does an `Answer` or `Key` with nothing after it but blanks, underscores or dots (`**Answer:**
  ____`); nor a wide form with a `**Shape:**` or `**Conventions:**` line after it in its block,
  since the brief puts the solution last. Each falls through to the unmarked-part warning.
  Lecture text never sits in a part's block, and a qualifier that names no part (`**Solutions to
  recurrences** are unique.`, `**Solution set:**`) is never a marker anywhere. A cut that starts
  inside a closed fence keeps
  the fence's closing line, so the copy's fences pair as the extract's do. A looser marker (a
  `#### Solution` heading, a `# solution` comment, `Solution:`) inside a closed fence is code and
  cuts nothing (extract_check.py warns, naming its line: loose_in_fences()), unless a fence
  anywhere in the file is still open at the next header, the `Coverage:` line or the end of the
  file: then the pairing can't be trusted, no fence exempts anything, and extract_check.py fails
  the extract. Nor does a closed
  fence holding a line that could open a fence (```` ```python ```` inside it, say) exempt
  anything inside it: that is nested markdown or a forgotten closer, where a solution's own
  ```` ```python ```` line reads as content and its bare closing line closes the starter code's
  fence, so the count balances with the marker inside.
- a whole block of an answers file (MANIFEST's Answers `yes`) whose `solutions to <doc>` note
  names other docs only: all of it answers.
- a page or section block of any other Answers `yes` doc (a past exam with its key, say), unless a
  question part of that doc names the page on its `Pages:` line: a page holding no question part
  is a key page.
A line no marker cuts that cites answers (a cite of such an answers file, of an Answers `yes`
doc with no question part, or of a key page or a page-less section of one with question parts:
answers_cite()) is a solution worded off the format, which no pattern can list in full: it makes
a copy due, and extract_check.py fails the extract naming its line until the marker is fixed
(leaks()). A `Pages:` line holding nothing but cites, and the closing line, don't count. A
question part's pages are read across every extract (hub_question_pages()), so a cite of one
from another extract isn't a key page. A solution with no marker and no such cite (it cites its
own question page, or nothing) can't be told from question text: extract_check.py warns about
each question part of a doc MANIFEST names as having solutions (the first two cases above)
that no marker cuts (unmarked()), and about each official part's marker that cuts but isn't the
brief's form (off_form()).
A copy is due for every extract that holds one of those, or any block of an Answers `yes` doc.
Its first line names the extract and the SHA-256 of its bytes, which is how extract_check.py
tells a stale copy. A run rewrites a copy whose text changed, leaves an unchanged one alone, and
removes a copy it wrote whose extract is gone or holds no answer now (one it didn't write, with no
such first line, is reported and left). `--parts` prints the number of official answer parts
across the extracts (parts(): the self-test's PARTS): the first marker that cuts in each
question part's block of a doc with solutions, and each `Solution [<doc> <loc>]` line of a block
taken out whole; never a stem's, a lecture's or another page block's marker. Exit 0 done, 1 on a
MANIFEST.md it can't read, 2 with no MANIFEST.md. Stdlib only, plus extract_check.py from this
directory."""
import argparse
import hashlib
import importlib.util
import os
import re
import sys

# The strict markers, read in every block of every extract (a lecture deck's too): the forms the
# extract format has always written. The loose one, outside a fence only: `Solution:`,
# `**Solution**`, a `#### Solution` heading, `Solution [`.
SOLUTION = re.compile(r"^[-*>#\s]*(?:\*\*)?(?:official\s+)?solutions?\b(?:\*\*)?\s*(?:\[|:|\*\*|$)",
                      re.I)
# The extract format's own marker (02-extract, the extract brief): `Solution [<doc> <locator>]`,
# with a list or quote mark before it, bold around the word or the whole marker, and then a colon
# or the end of the line (more cites may come first). It cuts even inside a fence. The tail keeps
# starter code such as `solution[i + 1] = best(i)` from reading as one.
CITED = r"\[[A-Za-z0-9_.-]+\s+[^\]\s][^\]]*\]"
BRACKETED_STRICT = re.compile(r"^[-*>#\s]*(?:\*\*)?(?:official\s+)?solutions?(?:\*\*)?\s*"
                              + CITED + r"(?:\s*" + CITED + r")*(?:\*\*)?\s*(?::|$)", re.I)
# The bold marker: `**Solution:**`, `**Solution**` or `**Official solution**:`, with a list, quote
# or heading mark before it. Markdown, never code, so it cuts even inside a fence; the closing `**`
# keeps a Python `**solution` (dict unpacking) from reading as one.
BOLD_STRICT = re.compile(r"^[-*>#\s]*\*\*(?:official\s+)?solutions?\s*:?\s*\*\*", re.I)
# The wide markers, read only in a question part's block (`### [<doc> Q1a]`, not a stem's) of a
# doc with solutions (solved()): there a solution worded a little off the format is likelier than
# lecture text, which never sits in a question part. wide_form() leaves out the shapes question
# text takes too (a plain `Key:`, an answer blank). The word may be `Solution` (`Official` or
# `Worked` before it), `Answer`, `Answer key` or `Key`, and a qualifier after it must name a part: a
# parenthesised label (`(Q1)`, `(a)`, `(part b)`), `to` or `for` then `Q1a`, `part (a)`,
# `problem 3`, `question 2`, `exercise 4`, `(a)` or `all parts`, or a comma then one of those
# (`, part (a)`, `, all parts`). So `**Solutions to recurrences** are unique.`, `**Solution
# set:**` and `Solution concepts [D4 p.3]` are never markers. A bracketed marker with a qualifier
# needs its colon, and one whose word is `Answer` or `Key` needs a first cite that points into
# answers (answers_cite()): `Answer the following [HW1 p.2]:` and `Answer in the table [PE1
# p.2]:` are question text.
LABEL = r"\(?(?:\d+(?:\.\d+)*[a-z]{0,2}(?:\([a-z0-9]{1,4}\))?|[ivx]{2,4}|[a-z])\)?"
LABELS = LABEL + r"(?:(?:\s*(?:,|&|-|\u2013|\band\b|\bto\b)\s*|\s+)" + LABEL + r"){0,5}"
PART_WORD = r"(?:part|problem|question|exercise)s?\b"
QUAL = (r"(?:\s*\((?:(?:Q|" + PART_WORD + r")\s*)?" + LABELS + r"\)"
        r"|\s+(?:to|for)\s+(?:all\s+parts|Q\s*" + LABELS + r"|" + PART_WORD + r"\s*" + LABELS
        + r"|\(" + LABELS + r"\))"
        r"|\s*,\s*(?:all\s+parts|Q\s*" + LABELS + r"|" + PART_WORD + r"\s*" + LABELS + r"))")
# PREFIX and WORDS are mirrored in templates/verify-set-key.py's MARKER (its test compares them).
PREFIX = r"(?:official|worked)"
WORDS = r"solution|answer(?:\s+key)?|key"
WORD = r"(?:(?P<pre>" + PREFIX + r")\s+)?(?P<word>" + WORDS + r")s?\b"
BRACKETED = re.compile(r"^[-*>#\s]*(?:\*\*)?" + WORD + r"(?P<qual>(?:" + QUAL + r"){1,3})?"
                       r"(?:\*\*)?\s*\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?P<loc>[^\]\s][^\]]*)\]"
                       r"(?:\s*" + CITED + r")*(?:\*\*)?\s*(?::|(?(qual)(?!)|$))", re.I)
BOLD = re.compile(r"^[-*>#\s]*\*\*" + WORD + r"(?P<qual>(?:" + QUAL + r"){1,3})?\s*:?\*\*", re.I)
LOOSE = re.compile(r"^[-*>#\s]*(?:\*\*)?" + WORD + r"(?P<qual>(?:" + QUAL + r"){1,3})?(?:\*\*)?"
                   r"\s*(?::|\*\*|$)", re.I)
# What may follow an `Answer` or `Key` marker on an answer blank: blanks, underscores, dots.
FILL_IN = re.compile(r"[\s:*]*[_.\u2026][\s_.\u2026]*")
# A part's Shape or Conventions field: a wide form above one is question text (the brief puts the
# solution after them).
FIELD_LINE = re.compile(r"^[-*+>\s]*\*\*(?:Shape|Conventions)(?::\*\*|\*\*:)")
HEADING = re.compile(r"^\s*#")
# The form the extract brief writes; any other marker that cuts is a warning (extract_check.py).
CANONICAL = re.compile(r"^[-*\s]*Solution \[[A-Za-z0-9_.-]+\s+[^\]\s][^\]]*\](?:\s*" + CITED
                       + r")*\s*:")
BLOCK = re.compile(r"^###\s+\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?P<loc>[^\]]+)\]")
QUESTION = re.compile(r"Q[\w.]+(?: stem)?")
PART = re.compile(r"Q[\w.]+")
PAGE_LOC = re.compile(r"p\.(\d+)(?:-(\d+))?")
PAGES_LINE = re.compile(r"^[-*\s]*Pages:(.*)")
# Any `[<doc> <locator>]` cite, and each page list in a locator: `p.2`, `pp. 2-3`, `P.3`, a range
# with an en dash, `pp.2, 5`; `p.2, p.3` is two lists.
ANY_CITE = re.compile(r"\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?P<loc>[^\]]+)\]")
LOC_PAGES = re.compile(r"\bpp?\.\s*(?P<list>\d+(?:\s*[-\u2013]\s*\d+)?"
                       r"(?:\s*,\s*\d+(?:\s*[-\u2013]\s*\d+)?)*)", re.I)
QUESTION_LOC = re.compile(r"Q\d", re.I)
SEPARATORS = re.compile(r"(?:[\s,;&]|and\b)*")
# CommonMark: an opener is at most 3 spaces in, a run of 3+ backticks or tildes, then an info
# string (a backtick opener's holds no backtick). A closer is at most 3 spaces in, a run of the
# opener's character at least as long, then nothing but blanks. Anything else is fence content.
OPENER = re.compile(r"^ {0,3}(?P<mark>`{3,}(?=[^`]*$)|~{3,})")
CLOSER = re.compile(r"^ {0,3}(?P<mark>`{3,}|~{3,})[ \t]*$")
# The extract brief's closing line, whole: `Coverage: <range>; N blocks; K image only (...); U
# flagged unreadable.` Older extracts end it `0 UNREADABLE.` or, with `1 (image only: p.1)`,
# `UNREADABLE: none.`. A `Coverage:` start, even with `; N blocks;` after it, is a solution's or a
# tool's line as often as not.
# The flagged count may carry its detail, in parentheses or after a colon (`1 flagged
# UNREADABLE: p.3 weight.`); a solution's `Coverage: 4/5 statements; 3 blocks; 2 of 3 branches`
# still lacks the image-only and unreadable parts. mock_leak.py's NOTE_LINE mirrors this.
COVERAGE = re.compile(r"^Coverage:\s.*;\s*\d+\s+blocks?\s*;\s*\d+\s*\(?image\s+only\b.*;\s*"
                      r"(?:\d+\s+(?:flagged\s+)?unreadable(?:\s*\(.*\)|\s*:.*)?"
                      r"|unreadable:\s*none)\.?\s*$", re.I)
FIRST = "Question-only copy of _build/extract/{name} (sha256 {digest})"
FIRST_LINE = re.compile(r"^Question-only copy of _build/extract/(?P<name>\S+) "
                        r"\(sha256 (?P<digest>[0-9a-f]{64})\)")
TAIL = (", written by qonly.py: every official solution removed. Agents that must not see "
        "answers read this file, never the extract.\n")


def load(name):
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(name, os.path.join(here, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def closing(lines):
    """The indices of the extract's closing `Coverage:` lines: a line of the brief's form
    (COVERAGE) with nothing but blank lines after it up to the next block header or the end of
    the file. Any other line starting `Coverage:` is the block's own text."""
    out, tail = set(), True
    for i in range(len(lines) - 1, -1, -1):
        if BLOCK.match(lines[i]):
            tail = True
        elif COVERAGE.match(lines[i]):
            if tail:
                out.add(i)
            tail = False
        elif lines[i].strip():
            tail = False
    return out


def fence_spans(lines):
    """([(opener index, closer index)] for each closed code fence; the index of each fence opener
    that never closes). Fences follow CommonMark (OPENER, CLOSER): a line with an info string or
    4+ spaces of indent never closes one. A fence still open at the next block header or closing
    `Coverage:` line (closing()) ends there, and one open there or at the end of the file (a
    forgotten closing fence, four backticks opened and three closed) is unclosed."""
    spans, unclosed, start, mark = [], [], None, None
    ends = closing(lines)
    for i, line in enumerate(lines):
        line = line.rstrip("\r\n")
        if start is not None and (BLOCK.match(line) or i in ends):
            unclosed.append(start)
            start = None
        if start is None:
            f = OPENER.match(line)
            if f:
                start, mark = i, f.group("mark")
            continue
        f = CLOSER.match(line)
        if f and f.group("mark")[0] == mark[0] and len(f.group("mark")) >= len(mark):
            spans.append((start, i))
            start = None
    if start is not None:
        unclosed.append(start)
    return spans, unclosed


def fences(lines):
    """(the indices of the lines in a closed code fence, its fence lines included; the index of
    each fence opener that never closes), as fence_spans() pairs them. An unclosed fence anywhere
    makes strip() exempt nothing anywhere in the file (fail closed)."""
    spans, unclosed = fence_spans(lines)
    return {i for start, end in spans for i in range(start, end + 1)}, unclosed


def fenced(lines):
    """The indices of the lines a marker search skips: those in a closed code fence, its fence
    lines included, or none at all when any fence in the file never closes (fences()). A closed
    fence with a line inside it that could open a fence (OPENER: ```` ```python ````, `~~~`, a
    shorter bare run) is nested markdown or a forgotten closer balanced by the solution's own
    fence, so the pairing can't be trusted there and it exempts nothing."""
    spans, unclosed = fence_spans(lines)
    if unclosed:
        return set()
    return {i for start, end in spans
            if not any(OPENER.match(line.rstrip("\r\n")) for line in lines[start + 1:end])
            for i in range(start, end + 1)}


def solved(rows):
    """(the docs with solutions MANIFEST names: an Answers `yes` doc, or one a `solutions to
    <doc>` note names; whether an Answers `yes` row with no such note pairs with any doc)."""
    named, anydoc = set(), False
    for doc, row in rows.items():
        if row.get("answers"):
            named.add(doc)
            named |= row.get("answers_for") or set()
            anydoc |= not row.get("answers_for")
    return named, anydoc


def bracketed(line, rows, qpages=None):
    """Whether the line is the wide bracketed marker (BRACKETED): `Solution [<doc> <loc>]:` with
    any cite, `Answer [<doc> <loc>]:` or `Key [<doc> <loc>]:` only when that cite points into
    answers (answers_cite())."""
    m = BRACKETED.match(line)
    if not m:
        return False
    return (m.group("word").lower() == "solution"
            or answers_cite(m.group("doc"), m.group("loc"), rows, qpages or {}))


def wide_form(line, rows, qpages=None, loose=True):
    """Whether the line is a wide marker (read only in a question part of a doc with solutions):
    the wide bracketed form (bracketed()), the wide bold one, or with `loose` (outside a fence)
    the wide loose one. Never a plain `Key:`, `Keys:`, `Answer:` or `Answer key:` (no bold, no
    qualifier, no cite, no `Official` or `Worked`, no heading mark: a legend, the data or an
    answer blank), nor an `Answer` or `Key` followed by nothing but blanks, underscores or dots
    (FILL_IN). cuts() also skips one with a Shape or Conventions line after it in its block."""
    m = BRACKETED.match(line)
    if m and not bracketed(line, rows, qpages):
        m = None
    m = m or BOLD.match(line) or (LOOSE.match(line) if loose else None)
    if not m:
        return False
    if m.group("word").lower() == "solution":
        return True
    if FILL_IN.fullmatch(line[m.end():].rstrip("\r\n")):
        return False
    return bool(m.group("pre") or m.group("qual") or "**" in m.group(0) or "[" in m.group(0)
                or HEADING.match(line))


def strict(line, code, i):
    """Whether lines[i] is a strict marker, read in every block: the bracketed or bold form
    anywhere, the loose `Solution:` one only outside a fence."""
    return bool(BRACKETED_STRICT.match(line) or BOLD_STRICT.match(line)
                or (i not in code and SOLUTION.match(line)))


def marker(line, code, i, rows, wide=False, qpages=None):
    """Whether lines[i] is a solution marker: a strict one (strict()); with `wide` (a question
    part of a doc with solutions), also a wide one (wide_form(): its loose form outside a fence
    only)."""
    return strict(line, code, i) or bool(wide and wide_form(line, rows, qpages, i not in code))


def segments(lines, code=None):
    """The file as [(kind, start, end, match)]: `pre` before the first header, `block` for each
    header's block, `coverage` for the closing Coverage: line (closing()). A header or closing
    Coverage: line ends an open fence (fences())."""
    code = fenced(lines) if code is None else code
    ends = closing(lines)
    out, start, match = [], 0, None
    for i, line in enumerate(lines):
        if i in code:
            continue
        m = BLOCK.match(line)
        if m or i in ends:
            out.append(("block" if match else "pre", start, i, match))
            start, match = i, m
            if not m:
                out.append(("coverage", i, i + 1, None))
                start = i + 1
    out.append(("block" if match else "pre", start, len(lines), match))
    return [s for s in out if s[1] < s[2]]


def loc_pages(loc):
    """The page numbers a cite's locator names (LOC_PAGES), every list and range in it."""
    out = set()
    for m in LOC_PAGES.finditer(loc):
        for a, b in re.findall(r"(\d+)(?:\s*[-\u2013]\s*(\d+))?", m.group("list")):
            out.update(range(int(a), max(int(a), int(b or a)) + 1))
    return out


def question_pages(lines, segs):
    """{doc: pages its question parts name on their `Pages:` lines}, with a key (an empty set at
    least) for every doc that has a question part's block here."""
    out = {}
    for kind, start, end, m in segs:
        if kind != "block" or not QUESTION.fullmatch(m.group("loc").strip()):
            continue
        doc = m.group("doc")
        pages = out.setdefault(doc, set())
        for line in lines[start:end]:
            p = PAGES_LINE.match(line)
            if not p:
                continue
            for c in ANY_CITE.finditer(p.group(1)):
                if c.group("doc") == doc:
                    pages |= loc_pages(c.group("loc"))
    return out


def merged(*maps):
    """question_pages() maps joined: each doc's pages, a doc in any of them."""
    out = {}
    for m in maps:
        for doc, pages in (m or {}).items():
            out.setdefault(doc, set()).update(pages)
    return out


def hub_question_pages(root):
    """question_pages() across every extract under root: a part's pages count for a cite of them
    in any extract, and a doc's page blocks in another extract than its parts'."""
    out = {}
    for name in extracts(root):
        with open(os.path.join(root, "_build", "extract", name), encoding="utf-8") as f:
            lines = f.read().splitlines(keepends=True)
        out = merged(out, question_pages(lines, segments(lines)))
    return out


class Cut:
    """What cuts() reads in a text: `lines`; `keep`, whether each is kept; `runs`, [(first line,
    end, why)] for each run taken out; `answers_doc`, whether it holds a block of an Answers `yes`
    doc; `marks`, [(line index, whether it starts a run, whether only a wide form reads it)] for
    each official part's marker (the first marker that cuts in a question part's block of a doc
    with solutions, and each `Solution [<doc> <loc>]` line, BRACKETED_STRICT, in a block taken out
    whole; never a stem's, a lecture's or another page block's); `unmarked`, the header index of
    each question part of a doc MANIFEST names as having solutions in which no marker cuts
    anything; `wide`, the indices of the lines read with the wide markers (a question part's of a
    doc with solutions, after its last Shape or Conventions line); `qpages`, the question pages it
    used (question_pages())."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def cuts(text, rows, qpages=None):
    """Cut for the text. A question part's block of a doc with solutions (solved()) reads the
    wide markers too below its last Shape or Conventions line (FIELD_LINE), any other block (a
    stem's, a page's) the strict ones only. A run that starts inside a closed
    fence keeps that fence's closing line, so the copy pairs its fences as the extract does.
    `qpages` adds question pages from other extracts (hub_question_pages())."""
    lines = text.splitlines(keepends=True)
    spans = fence_spans(lines)[0]
    code = fenced(lines)
    segs = segments(lines, code)
    qpages = merged(question_pages(lines, segs), qpages)
    named, anydoc = solved(rows)
    keep, runs, answers_doc = [True] * len(lines), [], False
    marks, unmarked, wide_lines = [], [], set()

    def drop(cut, end, why):
        keep[cut:end] = [False] * (end - cut)
        for opener, closer in spans:
            if opener < cut < closer < end:
                keep[closer] = True
        runs.append((cut, end, why))

    for kind, start, end, m in segs:
        if kind != "block":
            if kind == "pre":
                cut = next((i for i in range(start, end) if strict(lines[i], code, i)), None)
                if cut is not None:
                    drop(cut, end, "a solution before the first block")
            continue
        doc, loc = m.group("doc"), m.group("loc").strip()
        official = bool(PART.fullmatch(loc)) and (doc in named or anydoc)
        if official:
            last = max((i for i in range(start + 1, end)
                        if i not in code and FIELD_LINE.match(lines[i])), default=start)
            wide_lines.update(range(last + 1, end))

        def found(i):
            return strict(lines[i], code, i) or (
                i in wide_lines and wide_form(lines[i], rows, qpages, i not in code))
        row = rows.get(doc) or {}
        if row.get("answers"):
            answers_doc = True
            pair = row.get("answers_for") or set()
            why = None
            if pair and doc not in pair:
                why = f"a block of {doc}, an answers file"
            elif not QUESTION.fullmatch(loc):
                p = PAGE_LOC.fullmatch(loc)
                pages = set(range(int(p.group(1)), int(p.group(2) or p.group(1)) + 1)) if p else set()
                if not pages or not pages <= qpages.get(doc, set()):
                    why = f"a block of {doc} (answers yes) on no question part's page"
            if why:
                drop(start, end, why)
                marks.extend((i, False, False) for i in range(start + 1, end)
                             if BRACKETED_STRICT.match(lines[i]))
                continue
        cut = next((i for i in range(start + 1, end) if found(i)), None)
        if cut is not None:
            drop(cut, end, f"the solution in [{doc} {loc}]")
            if official:
                marks.append((cut, True, not strict(lines[cut], code, cut)))
        elif doc in named and PART.fullmatch(loc):
            unmarked.append(start)
    return Cut(lines=lines, keep=keep, runs=runs, answers_doc=answers_doc, marks=marks,
               unmarked=unmarked, wide=wide_lines, qpages=qpages)


def loose_in_fences(text, rows, qpages=None):
    """The indices of the lines that read as a loose solution marker (SOLUTION, or the loose
    wide_form() on a line read with the wide markers; not a bracketed or bold form) inside a
    closed code fence and that the copy keeps, or the extract keeps when no copy is due: exempt
    as code, so extract_check.py warns about each for a person to look at."""
    c = cuts(text, rows, qpages)
    code = fenced(c.lines)
    out = []
    for i in sorted(code):
        line, wide = c.lines[i], i in c.wide
        if not c.keep[i] or BRACKETED_STRICT.match(line) or BOLD_STRICT.match(line):
            continue
        if wide and wide_form(line, rows, c.qpages, loose=False):
            continue
        if SOLUTION.match(line) or (wide and wide_form(line, rows, c.qpages)):
            out.append(i)
    return out


def answers_cite(doc, loc, rows, qpages):
    """Whether a `[<doc> <loc>]` cite points into answers, by the rules cuts() takes blocks out
    by: any cite of an answers file whose `solutions to <doc>` note names other docs only; any cite
    of another Answers `yes` doc with no question part's block in any extract; and a cite of one
    with question parts that names a page no question part's `Pages:` line names (a key page), or
    names no page and no question part (`[PE1 Key]`). `qpages` is question_pages()."""
    row = rows.get(doc) or {}
    if not row.get("answers"):
        return False
    pair = row.get("answers_for") or set()
    if pair and doc not in pair:
        return True
    if doc not in qpages:
        return True
    pages = loc_pages(loc)
    if pages:
        return not pages <= qpages[doc]
    return not QUESTION_LOC.match(loc.strip())


def leaks(text, rows, qpages=None):
    """[(line index, cite)] for each line the copy keeps (every line, when no marker cuts
    anything) that cites answers (answers_cite()), however it is worded: a solution whose marker
    no pattern reads. The closing `Coverage:` line and a `Pages:` line holding nothing but cites
    (it names where a part sits, no answer) don't count. due() makes a copy due for one, and
    extract_check.py fails the extract by file and line."""
    c = cuts(text, rows, qpages)
    ends = closing(c.lines)
    out = []
    for i, line in enumerate(c.lines):
        if not c.keep[i] or i in ends:
            continue
        p = PAGES_LINE.match(line)
        if p and SEPARATORS.fullmatch(ANY_CITE.sub("", p.group(1))):
            continue
        hit = next((m for m in ANY_CITE.finditer(line)
                    if answers_cite(m.group("doc"), m.group("loc"), rows, c.qpages)), None)
        if hit:
            out.append((i, hit.group(0)))
    return out


def off_form(text, rows, qpages=None):
    """[(line index, whether only a wide form reads it)] for each official part's marker
    (Cut.marks) that starts a cut and isn't the brief's `Solution [<doc> <loc>]:` form
    (CANONICAL): extract_check.py warns about each, since a marker the patterns read only by luck
    is one rewording away from a leak, and a wide-only one may be question text. A lecture's or a
    stem's marker gets none: it is no official part."""
    c = cuts(text, rows, qpages)
    return [(i, wide) for i, starts, wide in c.marks
            if starts and not CANONICAL.match(c.lines[i])]


def unmarked(text, rows, qpages=None):
    """The header index of each question part of a doc with solutions in which no marker cuts
    anything (Cut.unmarked): extract_check.py warns about each, since a solution with no marker
    at all is kept whole."""
    return cuts(text, rows, qpages).unmarked


def strip(text, rows, qpages=None):
    """(the text with every answer taken out, [(line number, why)] for each run removed, whether
    it holds a block of an Answers `yes` doc). `rows` is extract_check.manifest_rows()."""
    c = cuts(text, rows, qpages)
    body = "".join(line for line, k in zip(c.lines, c.keep) if k)
    return body, [(cut + 1, why) for cut, _, why in c.runs], c.answers_doc


def bare(line):
    """A line without its blanks and leading list or quote marks, for answer_lines()."""
    return re.sub(r"^[-*+>\s]+", "", line).strip()


def answer_lines(text, rows, qpages=None):
    """{bare() of a line strip() takes out: why}, leaving out blank lines and any line the copy
    keeps elsewhere (a closing fence, a repeated phrase): extract_check.py names an answer the
    copy holds by these."""
    c = cuts(text, rows, qpages)
    kept = {bare(line) for line, k in zip(c.lines, c.keep) if k}
    out = {}
    for cut, end, why in c.runs:
        for i in range(cut, end):
            line = bare(c.lines[i])
            if not c.keep[i] and line and line not in kept:
                out.setdefault(line, why)
    return out


def due(text, rows, qpages=None):
    """Whether an extract needs a question-only copy, and its stripped text: one is due when
    strip() takes something out, the extract holds a block of an Answers `yes` doc, or a line it
    keeps cites answers (leaks()), so no agent reads an extract holding such a line."""
    body, removed, answers_doc = strip(text, rows, qpages)
    return bool(removed or answers_doc or leaks(text, rows, qpages)), body


def parts(root, rows):
    """The number of official answer parts across the extracts (Cut.marks): a question part's
    first marker that cuts, and each `Solution [<doc> <loc>]` line of a block taken out whole;
    the self-test's PARTS (verify-selftest.py)."""
    qpages = hub_question_pages(root)
    total = 0
    for name in extracts(root):
        with open(os.path.join(root, "_build", "extract", name), encoding="utf-8") as f:
            total += len(cuts(f.read(), rows, qpages).marks)
    return total


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def first_line(name, path):
    return FIRST.format(name=name, digest=digest(path))


def extracts(root):
    d = os.path.join(root, "_build", "extract")
    return sorted(n for n in os.listdir(d) if n.endswith(".md")) if os.path.isdir(d) else []


def copies(root):
    d = os.path.join(root, "_build", "q-only")
    return sorted(n for n in os.listdir(d) if n.endswith(".md")) if os.path.isdir(d) else []


def run(root, rows):
    """Write, keep or remove each copy; returns the lines it prints."""
    out, wanted = [], set()
    qdir = os.path.join(root, "_build", "q-only")
    qpages = hub_question_pages(root)
    for name in extracts(root):
        src = os.path.join(root, "_build", "extract", name)
        with open(src, encoding="utf-8") as f:
            needed, body = due(f.read(), rows, qpages)
        if not needed:
            continue
        wanted.add(name)
        text = first_line(name, src) + TAIL + body
        dst = os.path.join(qdir, name)
        try:
            with open(dst, encoding="utf-8") as f:
                if f.read() == text:
                    out.append(f"{name}: unchanged")
                    continue
        except OSError:
            pass
        os.makedirs(qdir, exist_ok=True)
        tmp = f"{dst}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, dst)
        out.append(f"{name}: wrote _build/q-only/{name}")
    for name in copies(root):
        if name in wanted:
            continue
        path = os.path.join(qdir, name)
        with open(path, encoding="utf-8") as f:
            ours = FIRST_LINE.match(f.readline())
        if ours:
            os.remove(path)
            out.append(f"{name}: removed _build/q-only/{name} (its extract holds no answer now)")
        else:
            out.append(f"warning: _build/q-only/{name} isn't a copy qonly.py wrote; left as is")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Write the extracts' question-only copies.")
    p.add_argument("--root", default=".", help="the exam-prep root (default: the cwd)")
    p.add_argument("--parts", action="store_true",
                   help="print the number of solution markers it cuts (the self-test's PARTS) "
                        "and write nothing")
    args = p.parse_args(argv)
    manifest = os.path.join(args.root, "MANIFEST.md")
    if not os.path.exists(manifest):
        print(f"qonly: no MANIFEST.md in {os.path.abspath(args.root)}", file=sys.stderr)
        return 2
    try:
        rows = load("extract_check").manifest_rows(manifest)
    except ValueError as e:
        print(f"qonly: {e}")
        return 1
    if args.parts:
        print(parts(args.root, rows))
        return 0
    for line in run(args.root, rows):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
