#!/usr/bin/python3 -I
"""Write the question-only copies of stage 02's extracts, from the hub root (hard rule 4, FB-056, FB-191).

  qonly.py [--root DIR]

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
  one). A short qualifier before the first cite (`Solution to Q1a [...]:`, `Solution, part (a)
  [...]:`) still makes it one, then only with its colon; `Answer [<doc> <locator>]:` is one when
  <doc> is an Answers `yes` doc (bracketed()). So does the bold marker (`**Solution:**`,
  `**Solution**`, `**Official solution:**`, `**Solution (Q1):**`), which is Markdown and never a
  code comment: a starter fence whose closer was forgotten, closed by the solution's own bare
  fence line, used to hide it. A cut that starts inside a closed fence keeps
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
A line no marker cuts that cites answers (a cite of such an answers file, or of a key page:
answers_cite()) is a solution worded off the format, which no pattern can list in full: it makes
a copy due, and extract_check.py fails the extract naming its line until the marker is fixed
(leaks()). A `Pages:` line holding nothing but cites, and the closing line, don't count.
A copy is due for every extract that holds one of those, or any block of an Answers `yes` doc.
Its first line names the extract and the SHA-256 of its bytes, which is how extract_check.py
tells a stale copy. A run rewrites a copy whose text changed, leaves an unchanged one alone, and
removes a copy it wrote whose extract is gone or holds no answer now (one it didn't write, with no
such first line, is reported and left). Exit 0 done, 1 on a MANIFEST.md it can't read, 2 with no
MANIFEST.md. Stdlib only, plus extract_check.py from this directory."""
import argparse
import hashlib
import importlib.util
import os
import re
import sys

SOLUTION = re.compile(r"^[-*>#\s]*(?:\*\*)?(?:official\s+)?solutions?\b(?:\*\*)?\s*(?:\[|:|\*\*|$)",
                      re.I)
# The extract format's own marker (02-extract, the extract brief): `Solution [<doc> <locator>]`,
# with a list or quote mark before it, bold around the word or the whole marker, and then a colon
# or the end of the line (more cites may come first). It cuts even inside a fence. The tail keeps
# starter code such as `solution[i + 1] = best(i)` from reading as one. A short qualifier may come
# between the word and the first cite (`Solution to Q1a [...]:`, `Solution, part (a) [...]:`): it
# starts with a blank or a comma and holds no colon, bracket or `=` (so `solution = memo[i - 1]`
# isn't one), and a marker with one needs its colon (so lecture text ending in a cite, `Solution
# concepts [D4 p.3]`, isn't one). The same shape with `Answer` (`Answer [<doc> <loc>]:`) is a
# marker only when the first cite's doc is an Answers `yes` one (bracketed()): `Answer the
# following [HW1 p.2]:` is question text.
CITED = r"\[[A-Za-z0-9_.-]+\s+[^\]\s][^\]]*\]"
BRACKETED = re.compile(r"^[-*>#\s]*(?:\*\*)?(?:official\s+)?(?P<word>solution|answer)s?\b"
                       r"(?P<qual>[ \t,]+[\w(),.'-][\w \t(),.'-]{0,29}?)?(?:\*\*)?\s*"
                       r"\[(?P<doc>[A-Za-z0-9_.-]+)\s+[^\]\s][^\]]*\]"
                       r"(?:\s*" + CITED + r")*(?:\*\*)?\s*(?::|(?(qual)(?!)|$))", re.I)
# The bold marker: `**Solution:**`, `**Solution**` or `**Official solution**:`, with a list, quote
# or heading mark before it, and a short qualifier inside the bold (`**Solution (Q1):**`,
# `**Solution to part (a)**`). Markdown, never code, so it cuts even inside a fence; the closing
# `**`, which CommonMark never reads after a blank, keeps a Python `**solution` or `**solution,
# **extra` (dict unpacking) from reading as one.
BOLD = re.compile(r"^[-*>#\s]*\*\*(?:official\s+)?solutions?\b(?:[^*\n]{0,40}?[^*\s,])?\s*:?\*\*",
                  re.I)
BLOCK = re.compile(r"^###\s+\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?P<loc>[^\]]+)\]")
QUESTION = re.compile(r"Q[\w.]+(?: stem)?")
PAGE_LOC = re.compile(r"p\.(\d+)(?:-(\d+))?")
PAGES_LINE = re.compile(r"^[-*\s]*Pages:(.*)")
CITE = re.compile(r"\[(?P<doc>[A-Za-z0-9_.-]+)\s+pp?\.\s*(?P<page>\d+)(?:\s*-\s*(?P<end>\d+))?\]")
# Any `[<doc> <locator>]` cite, and a page locator (extract_check.py's CITE and CITE_PAGES).
ANY_CITE = re.compile(r"\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?P<loc>[^\]]+)\]")
CITE_PAGES = re.compile(r"pp?\.\s*(?P<page>\d+)(?:\s*-\s*(?P<end>\d+))?")
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


def bracketed(line, rows):
    """Whether the line is the bracketed marker (BRACKETED): `Solution [<doc> <loc>]:` with any
    cite, `Answer [<doc> <loc>]:` only when <doc> is an Answers `yes` doc in `rows`."""
    m = BRACKETED.match(line)
    if not m:
        return False
    return m.group("word").lower() == "solution" or bool((rows.get(m.group("doc")) or {})
                                                         .get("answers"))


def marker(line, code, i, rows):
    """Whether lines[i] is a solution marker: the bracketed or bold form anywhere, a looser one
    only outside a fence."""
    return bool(bracketed(line, rows) or BOLD.match(line)
                or (i not in code and SOLUTION.match(line)))


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


def question_pages(lines, segs):
    """{doc: pages its question parts name on their `Pages:` lines}."""
    out = {}
    for kind, start, end, m in segs:
        if kind != "block" or not QUESTION.fullmatch(m.group("loc").strip()):
            continue
        doc = m.group("doc")
        for line in lines[start:end]:
            p = PAGES_LINE.match(line)
            if not p:
                continue
            for c in CITE.finditer(p.group(1)):
                if c.group("doc") == doc:
                    lo = int(c.group("page"))
                    out.setdefault(doc, set()).update(range(lo, int(c.group("end") or lo) + 1))
    return out


def cuts(text, rows):
    """(the text's lines, whether each is kept, [(first line, end, why)] for each run taken out,
    whether it holds a block of an Answers `yes` doc). A run that starts inside a closed fence
    keeps that fence's closing line, so the copy pairs its fences as the extract does."""
    lines = text.splitlines(keepends=True)
    spans = fence_spans(lines)[0]
    code = fenced(lines)
    segs = segments(lines, code)
    qpages = question_pages(lines, segs)
    keep, runs, answers_doc = [True] * len(lines), [], False

    def drop(cut, end, why):
        keep[cut:end] = [False] * (end - cut)
        for opener, closer in spans:
            if opener < cut < closer < end:
                keep[closer] = True
        runs.append((cut, end, why))

    for kind, start, end, m in segs:
        if kind != "block":
            if kind == "pre":
                cut = next((i for i in range(start, end) if marker(lines[i], code, i, rows)),
                           None)
                if cut is not None:
                    drop(cut, end, "a solution before the first block")
            continue
        doc, loc = m.group("doc"), m.group("loc").strip()
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
                continue
        cut = next((i for i in range(start + 1, end) if marker(lines[i], code, i, rows)), None)
        if cut is not None:
            drop(cut, end, f"the solution in [{doc} {loc}]")
    return lines, keep, runs, answers_doc


def loose_in_fences(text, rows):
    """The indices of the lines that read as a loose solution marker (SOLUTION, not the bracketed
    or bold form) inside a closed code fence and that the copy keeps, or the extract keeps when no
    copy is due: exempt as code, so extract_check.py warns about each for a person to look at."""
    lines, keep, _, _ = cuts(text, rows)
    code = fenced(lines)
    return [i for i in sorted(code) if keep[i] and SOLUTION.match(lines[i])
            and not bracketed(lines[i], rows) and not BOLD.match(lines[i])]


def answers_cite(doc, loc, rows, qpages):
    """Whether a `[<doc> <loc>]` cite points into answers, by the rules cuts() takes blocks out
    by: any cite of an answers file whose `solutions to <doc>` note names other docs only, or a
    page cite of any other Answers `yes` doc that no question part's `Pages:` line names (a key
    page). `qpages` is question_pages()."""
    row = rows.get(doc) or {}
    if not row.get("answers"):
        return False
    pair = row.get("answers_for") or set()
    if pair and doc not in pair:
        return True
    p = CITE_PAGES.fullmatch(loc.strip())
    if not p:
        return False
    lo = int(p.group("page"))
    return not set(range(lo, max(lo, int(p.group("end") or lo)) + 1)) <= qpages.get(doc, set())


def leaks(text, rows):
    """[(line index, cite)] for each line the copy keeps (every line, when no marker cuts
    anything) that cites answers (answers_cite()), however it is worded: a solution whose marker
    no pattern reads. The closing `Coverage:` line and a `Pages:` line holding nothing but cites
    (it names where a part sits, no answer) don't count. due() makes a copy due for one, and
    extract_check.py fails the extract by file and line."""
    lines, keep, _, _ = cuts(text, rows)
    qpages = question_pages(lines, segments(lines))
    ends = closing(lines)
    out = []
    for i, line in enumerate(lines):
        if not keep[i] or i in ends:
            continue
        p = PAGES_LINE.match(line)
        if p and SEPARATORS.fullmatch(ANY_CITE.sub("", p.group(1))):
            continue
        c = next((c for c in ANY_CITE.finditer(line)
                  if answers_cite(c.group("doc"), c.group("loc"), rows, qpages)), None)
        if c:
            out.append((i, c.group(0)))
    return out


def strip(text, rows):
    """(the text with every answer taken out, [(line number, why)] for each run removed, whether
    it holds a block of an Answers `yes` doc). `rows` is extract_check.manifest_rows()."""
    lines, keep, runs, answers_doc = cuts(text, rows)
    body = "".join(line for line, k in zip(lines, keep) if k)
    return body, [(cut + 1, why) for cut, _, why in runs], answers_doc


def bare(line):
    """A line without its blanks and leading list or quote marks, for answer_lines()."""
    return re.sub(r"^[-*+>\s]+", "", line).strip()


def answer_lines(text, rows):
    """{bare() of a line strip() takes out: why}, leaving out blank lines and any line the copy
    keeps elsewhere (a closing fence, a repeated phrase): extract_check.py names an answer the
    copy holds by these."""
    lines, keep, runs, _ = cuts(text, rows)
    kept = {bare(line) for line, k in zip(lines, keep) if k}
    out = {}
    for cut, end, why in runs:
        for i in range(cut, end):
            line = bare(lines[i])
            if not keep[i] and line and line not in kept:
                out.setdefault(line, why)
    return out


def due(text, rows):
    """Whether an extract needs a question-only copy, and its stripped text: one is due when
    strip() takes something out, the extract holds a block of an Answers `yes` doc, or a line it
    keeps cites answers (leaks()), so no agent reads an extract holding such a line."""
    body, removed, answers_doc = strip(text, rows)
    return bool(removed or answers_doc or leaks(text, rows)), body


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
    for name in extracts(root):
        src = os.path.join(root, "_build", "extract", name)
        with open(src, encoding="utf-8") as f:
            needed, body = due(f.read(), rows)
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
    for line in run(args.root, rows):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
