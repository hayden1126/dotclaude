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
  file. A fence's lines don't end it.
- a whole block of an answers file (MANIFEST's Answers `yes`) whose `solutions to <doc>` note
  names other docs only: all of it answers.
- a page or section block of any other Answers `yes` doc (a past exam with its key, say), unless a
  question part of that doc names the page on its `Pages:` line: a page holding no question part
  is a key page.
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
BLOCK = re.compile(r"^###\s+\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?P<loc>[^\]]+)\]")
QUESTION = re.compile(r"Q[\w.]+(?: stem)?")
PAGE_LOC = re.compile(r"p\.(\d+)(?:-(\d+))?")
PAGES_LINE = re.compile(r"^[-*\s]*Pages:(.*)")
CITE = re.compile(r"\[(?P<doc>[A-Za-z0-9_.-]+)\s+pp?\.\s*(?P<page>\d+)(?:\s*-\s*(?P<end>\d+))?\]")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
COVERAGE = re.compile(r"^Coverage:")
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


def fenced(lines):
    """The indices of the lines in a code fence, its fence lines included."""
    out, fence = set(), None
    for i, line in enumerate(lines):
        f = FENCE.match(line)
        if f:
            mark = f.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            out.add(i)
        elif fence is not None:
            out.add(i)
    return out


def segments(lines, code=None):
    """The file as [(kind, start, end, match)]: `pre` before the first header, `block` for each
    header's block, `coverage` for a Coverage: line. A fence's lines start nothing."""
    code = fenced(lines) if code is None else code
    out, start, match = [], 0, None
    for i, line in enumerate(lines):
        if i in code:
            continue
        m = BLOCK.match(line)
        if m or COVERAGE.match(line):
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


def strip(text, rows):
    """(the text with every answer taken out, [(line number, why)] for each run removed, whether
    it holds a block of an Answers `yes` doc). `rows` is extract_check.manifest_rows()."""
    lines = text.splitlines(keepends=True)
    code = fenced(lines)
    segs = segments(lines, code)
    qpages = question_pages(lines, segs)
    keep, removed, answers_doc = [True] * len(lines), [], False
    for kind, start, end, m in segs:
        if kind != "block":
            if kind == "pre":
                cut = next((i for i in range(start, end) if i not in code and SOLUTION.match(lines[i])), None)
                if cut is not None:
                    keep[cut:end] = [False] * (end - cut)
                    removed.append((cut + 1, "a solution before the first block"))
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
                keep[start:end] = [False] * (end - start)
                removed.append((start + 1, why))
                continue
        cut = next((i for i in range(start + 1, end) if i not in code and SOLUTION.match(lines[i])), None)
        if cut is not None:
            keep[cut:end] = [False] * (end - cut)
            removed.append((cut + 1, f"the solution in [{doc} {loc}]"))
    return "".join(line for line, k in zip(lines, keep) if k), removed, answers_doc


def due(text, rows):
    """Whether an extract needs a question-only copy, and its stripped text."""
    body, removed, answers_doc = strip(text, rows)
    return bool(removed or answers_doc), body


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
