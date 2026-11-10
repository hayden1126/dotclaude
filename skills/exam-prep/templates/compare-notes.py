#!/usr/bin/env python3
r"""The notes against the checker: every value a worked example prints, compared by script.

exam-prep template compare-notes.py, baseline as of 2026-11-10; changes only via `12-retro`.
Copy it to _build/verify/compare_notes.py and fill the marked part. Run from the hub root:

  python3 -I _build/verify/compare_notes.py --self-test   first: exit 0 only on SELF-TEST OK
  python3 -I _build/verify/compare_notes.py               exit 0 only on NOTES MATCH

A worked example in notes/*.md is the blockquote that opens `> **Worked example N.K: <title>**
{#ex-...}`. It is compared with the `## ex-...:` section of _build/verify/examples.out.md that
has its id. The values compared are numbers, wherever they stand, and names: a word NAME matches
(`S`, `G2`), in backticks in the notes (CONVERT.md keeps a trace's names as code, so a bare
capital is prose) and anywhere in the checker's output. Left out on both sides: the heading line,
`{#id}` anchors, citations, link targets, FIG markers, a `Step N:` label, a list number, a `§N.K`,
"Worked example N.K" or "Fig N.K" mention, and a table's index column (headed Step, #, i,
iteration or round). What is left must be the same values in the same order, so a changed number,
a value the notes add, a value they omit and two swapped entries of an order or a path each fail,
with a line naming the file and line, the subsection, the example and the values (FB-101, L50).
The `**Conclusion:**` line restates, so each of its values only has to appear in the section.

A `value-<slug>` section fills a TODO-VERIFY outside any worked example: FILLED names the notes
file each was copied into. The section's `**Result:**` line (the whole section when it has none)
must appear in that file, its values in the same order. A `value-` section FILLED lacks, an `ex-`
section no worked example carries, a worked example with no section, and a TODO-VERIFY left in
the notes each fail too.

--self-test plants the two errors a hand-written comparison once passed, a changed number and
two swapped entries of a visit order, into an in-memory copy of a built-in sample and of the
hub's notes. It passes only when the clean sample matches and each plant is caught. A plant that
leaves its copy unchanged fails as PLANT DID NOTHING: a no-op replace once passed vacuously."""
import difflib
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.dirname(os.path.dirname(HERE))
OUT_PATH = os.path.join(HERE, "examples.out.md")

# ---- Fill in: each value- section of examples.out.md, with the notes file its value was copied
# into (STATUS's TODO-VERIFY list says which), e.g. {"value-code-count": "notes/01-counting.md"}.
FILLED = {}
# A name in a trace: one capital, then digits or a prime (S, G2, A'). Widen it when the course
# names states otherwise (q0, AB), and keep ordinary words out of it.
NAME = re.compile(r"[A-Z][0-9]*'?")

EXAMPLE = re.compile(r"^\s*>\s*\*\*Worked example\s+[\d.]+\s*:.*?\{#(ex-[\w-]+)\}")
SECTION = re.compile(r"^## ((?:ex|value)-[\w-]+)\s*:")
SUBSECTION = re.compile(r"^##\s+(\d+(?:\.\d+)*)\s")
CONCLUSION = re.compile(r"^(?:\s*>)*\s*\*\*Conclusion:\*\*")
RESULT = re.compile(r"^\s*\*\*Result:\*\*")
SEPARATOR = re.compile(r"^(?:\s*>)*\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
TABLE_ROW = re.compile(r"^(?:\s*>)*\s*\|")
PIPE = re.compile(r"(?<!\\)\|")
INDEX_HEADS = {"step", "#", "i", "iter", "iteration", "round"}
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_']*|(?:(?<![\w)\]}])-)?\d+(?:\.\d+)?")
TICKS = re.compile(r"`[^`]*`")
# Spans that hold no value, blanked to spaces so every offset still points into the file.
NOT_VALUES = [
    re.compile(r"^(?:\s*>)+"),                                # blockquote markers
    re.compile(r"\{#[^}]*\}"),                                # anchors
    re.compile(r"(?<!\\)\[[A-Za-z][\w.-]*\s[^\]]*\](?!\()"),  # citations, [D5 p.23]
    re.compile(r"\]\([^)]*\)"),                               # link targets (the text stays)
    re.compile(r"<!--.*?-->"),                                # FIG markers
    re.compile(r"§\s?\d+(?:\.\d+)*"),                         # section mentions
    re.compile(r"\b(?:Worked example|Fig\.?|Figure)\s+\d+(?:\.\d+)*"),
    re.compile(r"^\s*(?:\*\*)?Step\s+\d+\s*[:.]?(?:\*\*)?:?"),  # a Step N: label
    re.compile(r"^\s*(?:\d+[.)]|[-*+])\s+"),                  # a list marker
]


class Atom:
    """One value: `n:25` or `w:S`, with where it stands (1-based line, offsets in that line)."""

    def __init__(self, value, line, start, end):
        self.value, self.line, self.start, self.end = value, line, start, end


def number(tok):
    if "." in tok:
        tok = tok.rstrip("0").rstrip(".")
    return tok


def blank(line):
    for pat in NOT_VALUES:
        line = pat.sub(lambda m: " " * len(m.group(0)), line)
    return line


def line_atoms(line, n, names_anywhere):
    text = blank(line.replace("−", "-"))
    ticks = [m.span() for m in TICKS.finditer(text)]
    out = []
    for m in TOKEN.finditer(text):
        tok = m.group(0)
        if tok[0].isdigit() or tok[0] == "-":
            out.append(Atom("n:" + number(tok), n, m.start(), m.end()))
        elif NAME.fullmatch(tok) and (names_anywhere or any(a < m.start() < b for a, b in ticks)):
            out.append(Atom("w:" + tok, n, m.start(), m.end()))
    return out


def blank_cells(line, cols):
    pipes = [m.start() for m in PIPE.finditer(line)]
    spans = [(pipes[k] + 1, pipes[k + 1]) for k in range(len(pipes) - 1)]
    for k in sorted(cols, reverse=True):
        if k < len(spans):
            a, b = spans[k]
            line = line[:a] + " " * (b - a) + line[b:]
    return line


def atoms(lines, first, names_anywhere):
    """The values of consecutive lines, the first numbered `first`; a table's header row and its
    index column left out."""
    out, index_cols = [], set()
    for k, line in enumerate(lines):
        if SEPARATOR.match(line):
            continue
        if TABLE_ROW.match(line):
            if k + 1 < len(lines) and SEPARATOR.match(lines[k + 1]):
                pipes = [m.start() for m in PIPE.finditer(line)]
                heads = [line[pipes[j] + 1:pipes[j + 1]].strip().strip("*").lower()
                         for j in range(len(pipes) - 1)]
                index_cols = {j for j, h in enumerate(heads) if h in INDEX_HEADS}
                continue
            line = blank_cells(line, index_cols)
        else:
            index_cols = set()
        out += line_atoms(line, first + k, names_anywhere)
    return out


class Block:
    """One worked example in a notes file: its values, and its Conclusion's apart."""

    def __init__(self, path, ex_id, sub, line, lines):
        self.path, self.id, self.sub, self.line = path, ex_id, sub, line
        # The Conclusion lines blanked in place, so every other value keeps its line number.
        kept = [(" " * len(l) if CONCLUSION.match(l) else l) for l in lines]
        self.values = atoms(kept, line + 1, False)
        self.conclusion = [a for k, l in enumerate(lines) if CONCLUSION.match(l)
                           for a in line_atoms(l, line + 1 + k, False)]


def blocks(path, text):
    lines = text.split("\n")
    sub, i = "?", 0
    while i < len(lines):
        m = SUBSECTION.match(lines[i])
        if m:
            sub = m.group(1)
        m = EXAMPLE.match(lines[i])
        if not m:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j].lstrip().startswith(">"):
            j += 1
        yield Block(path, m.group(1), sub, i + 1, lines[i + 1:j])
        i = j


def checker_sections(out_text):
    secs, cur = {}, None
    for line in out_text.split("\n"):
        m = SECTION.match(line)
        if m:
            cur = m.group(1)
            secs[cur] = []
        elif line.startswith("#"):
            cur = None
        elif cur:
            secs[cur].append(line)
    return secs


def show(values):
    more = " ..." if len(values) > 12 else ""
    return ", ".join(v[2:] for v in values[:12]) + more


def contains(have, want):
    n = len(want)
    return any(have[k:k + n] == want for k in range(len(have) - n + 1))


def compare_example(block, checker_lines):
    got = [a.value for a in block.values]
    want = [a.value for a in atoms(checker_lines, 1, True)]
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, got, want,
                                                       autojunk=False).get_opcodes():
        if op == "equal":
            continue
        at = block.values[min(i1, len(block.values) - 1)].line if block.values else block.line
        here = f"{block.path}:{at} §{block.sub} {block.id}"
        if op == "replace":
            out.append(f"{here}: the notes print {show(got[i1:i2])} where the checker has "
                       f"{show(want[j1:j2])}")
        elif op == "delete":
            out.append(f"{here}: the notes print {show(got[i1:i2])}, which the checker doesn't")
        else:
            out.append(f"{here}: the notes omit {show(want[j1:j2])}, which the checker prints")
    allowed = set(want)
    for a in block.conclusion:
        if a.value not in allowed:
            out.append(f"{block.path}:{a.line} §{block.sub} {block.id}: the Conclusion prints "
                       f"{show([a.value])}, which the checker's section doesn't")
    return out


def compare(notes, out_text, filled):
    """Every difference between the notes ({path: text}) and examples.out.md, a line each."""
    problems = []
    secs = checker_sections(out_text)
    seen = set()
    for path in sorted(notes):
        for n, line in enumerate(notes[path].split("\n"), 1):
            if "TODO-VERIFY" in line:
                problems.append(f"{path}:{n}: TODO-VERIFY left: fill it from a value- section")
        for b in blocks(path, notes[path]):
            seen.add(b.id)
            if b.id not in secs:
                problems.append(f"{path}:{b.line} §{b.sub} {b.id}: NO CHECKER SECTION: "
                                f"examples.out.md has no ## {b.id}")
            else:
                problems += compare_example(b, secs[b.id])
    for sid, lines in secs.items():
        if sid.startswith("ex-") and sid not in seen:
            problems.append(f"examples.out.md {sid}: NOT IN THE NOTES: no worked example "
                            f"carries {{#{sid}}}")
        elif sid.startswith("value-"):
            if sid not in filled:
                problems.append(f"examples.out.md {sid}: NOT IN FILLED: name the notes file "
                                "its value was copied into")
                continue
            path = filled[sid]
            if path not in notes:
                problems.append(f"FILLED {sid}: no notes file {path}")
                continue
            result = [l for l in lines if RESULT.match(l)] or lines
            want = [a.value for a in atoms(result, 1, True)]
            have = [a.value for a in atoms(notes[path].split("\n"), 1, False)]
            if not want:
                problems.append(f"examples.out.md {sid}: no value to compare")
            elif not contains(have, want):
                problems.append(f"{path} {sid}: the file doesn't print {show(want)}, in that "
                                "order")
    for sid in sorted(set(filled) - set(secs)):
        problems.append(f"FILLED {sid}: examples.out.md has no such section")
    return problems


# ---- Self-test ------------------------------------------------------------------------------

SAMPLE_NOTES = {"notes/01-sample.md": r"""# §1 Sample

## 1.1 Breadth-first search {#sec-1-bfs}

> **Worked example 1.1: BFS from `S`** {#ex-1-bfs}
> Setup: edges `S`-`A`, `S`-`B`, `A`-`G`, `B`-`G`; ties alphabetical [D1 p.4].
> Step 1: expand `S`; the frontier is `A`, `B`.
> Step 2: expand `A`; the frontier is `B`, `G`.
> Step 3: expand `B`; `G` is on the frontier already.
> Step 4: expand `G`, the goal.
>
> | Step | Expanded | Depth |
> | --- | --- | --- |
> | 1 | `S` | 0 |
> | 4 | `G` | 2 |
>
> **Result:** visit order `S`, `A`, `B`, `G`; distance 2 ([§1.1](#sec-1-bfs)).
> **Conclusion:** BFS reaches `G` at distance 2.

There are 17576 three-letter codes.
"""}
SAMPLE_OUT = """# Worked examples (generated by examples.py: rerun it, never edit this file)

## ex-1-bfs: BFS from S

Edges S-A, S-B, A-G, B-G; ties alphabetical.

| Step | Expanded | Frontier |
| --- | --- | --- |
| 1 | S | A, B |
| 2 | A | B, G |
| 3 | B | G |
| 4 | G | |

| Step | Expanded | Depth |
| --- | --- | --- |
| 1 | S | 0 |
| 4 | G | 2 |

**Result:** visit order S, A, B, G; distance 2

## value-codes: three-letter codes

26^3

**Result:** 17576
"""
SAMPLE_FILLED = {"value-codes": "notes/01-sample.md"}


def splice(text, line, start, end, new):
    """`text` with one line's span [start, end) replaced by `new`."""
    lines = text.split("\n")
    lines[line - 1] = lines[line - 1][:start] + new + lines[line - 1][end:]
    return "\n".join(lines)


def paired(notes, secs):
    return [b for path in sorted(notes) for b in blocks(path, notes[path]) if b.id in secs]


def plant_number(notes, secs):
    for b in paired(notes, secs):
        for a in b.values:
            if a.value.startswith("n:"):
                old = notes[b.path].split("\n")[a.line - 1][a.start:a.end]
                new = str(int(old) + 1) if "." not in old else old + "1"
                copy = dict(notes)
                copy[b.path] = splice(notes[b.path], a.line, a.start, a.end, new)
                return copy, f"{b.path}:{a.line} {old} to {new}"
    return None, "no worked example prints a number"


LISTED = re.compile(r"`?\s*(?:,|→|->)\s*`?")


def plant_swap(notes, secs):
    """Two adjacent different values on one line swapped: an order's entries (`S`, `A`) on a
    Result line first (a visit order, a path), then on any line, then any two names, then any
    two values."""
    for mode in ("result", "order", "names", "any"):
        for b in paired(notes, secs):
            for x, y in zip(b.values, b.values[1:]):
                if x.line != y.line or x.value == y.value:
                    continue
                line = notes[b.path].split("\n")[x.line - 1]
                names = x.value.startswith("w:") and y.value.startswith("w:")
                if mode != "any" and not names:
                    continue
                if mode in ("result", "order") and not LISTED.fullmatch(line[x.end:y.start]):
                    continue
                if mode == "result" and "**Result:**" not in line:
                    continue
                left, right = line[x.start:x.end], line[y.start:y.end]
                text = splice(notes[b.path], y.line, y.start, y.end, left)
                text = splice(text, x.line, x.start, x.end, right)
                copy = dict(notes)
                copy[b.path] = text
                return copy, f"{b.path}:{x.line} {left}, {right} to {right}, {left}"
    return None, "no worked example prints two different values on one line"


def self_test(hub_notes, hub_out):
    fails = []

    def report(ok, msg):
        print(f"{'PASS' if ok else 'FAIL'}  {msg}", flush=True)
        if not ok:
            fails.append(msg)

    clean = compare(SAMPLE_NOTES, SAMPLE_OUT, SAMPLE_FILLED)
    report(not clean, "the clean sample matches its checker output"
           + ("" if not clean else ": " + "; ".join(clean[:3])))
    corpora = [("sample", SAMPLE_NOTES, SAMPLE_OUT, SAMPLE_FILLED)]
    if hub_notes and hub_out is not None:
        corpora.append(("hub", hub_notes, hub_out, FILLED))
    else:
        print("SKIP  the hub: no notes/*.md or no examples.out.md yet")
    for name, notes, out, filled in corpora:
        base = set(compare(notes, out, filled))
        secs = checker_sections(out)
        for what, planter in (("a changed number", plant_number),
                              ("a reordered sequence", plant_swap)):
            planted, where = planter(notes, secs)
            if planted is None:
                report(False, f"{name}: nowhere to plant {what}: {where}")
            elif planted == notes:
                report(False, f"{name}: PLANT DID NOTHING: {what} at {where} left the copy "
                              "as it was")
            else:
                new = [p for p in compare(planted, out, filled) if p not in base]
                report(bool(new), f"{name}: {what} at {where}: "
                       + (f"caught ({new[0]})" if new else "NOT CAUGHT"))
    print("SELF-TEST OK" if not fails else f"SELF-TEST FAILED: {len(fails)} of the checks")
    return 1 if fails else 0


def load():
    notes = {}
    for p in sorted(glob.glob(os.path.join(HUB, "notes", "*.md"))):
        with open(p, encoding="utf-8") as f:
            notes[os.path.relpath(p, HUB).replace(os.sep, "/")] = f.read()
    out = None
    if os.path.isfile(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            out = f.read()
    return notes, out


def main(argv):
    notes, out = load()
    if argv == ["--self-test"]:
        return self_test(notes, out)
    if argv:
        print("usage: compare_notes.py [--self-test]", file=sys.stderr)
        return 2
    if out is None:
        print("compare_notes.py: no _build/verify/examples.out.md: run examples.py first")
        return 1
    if not notes:
        print("compare_notes.py: no notes/*.md")
        return 1
    problems = compare(notes, out, FILLED)
    for p in problems:
        print(p)
    secs = checker_sections(out)
    n_ex = sum(s.startswith("ex-") for s in secs)
    n_val = sum(s.startswith("value-") for s in secs)
    print(f"NOTES MATCH: {n_ex} worked examples, {n_val} values" if not problems
          else f"{len(problems)} DIFFERENCES")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
