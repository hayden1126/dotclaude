#!/usr/bin/env python3
r"""The mock key's checker: every computable answer in a mock's key comes from the reference.

exam-prep template verify-mock-key.py, baseline as of 2026-10-20; changes only via `12-retro`.
Copy it to _build/verify/mock_key.py and fill the marked part. Run from the hub root:

  python3 -I _build/verify/mock_key.py      exit 0 only with a KEY OK line per mock

MOCKS names each mock by its slug: `practice/mock-<slug>.md`, keyed by
`practice/mock-<slug>-key.md` (templates/MOCK.md). For each part the reference can compute,
`value("exam1-1", "Q2(a)", ...)` gives the answer formatted exactly as the key writes it (a value,
an order, a verdict with its witness). Every value lands in practice/mock-values-key.md, under a
STOP header and quarantined like any key, and the key's `Answer:` lines are copied from there,
never worked by hand (hard rule 3). The key's answer, read as Markdown (with or without
underscore emphasis), must equal the value as written, a final period and runs of whitespace aside. Each instance also gets an assert that it isn't degenerate
(a tie its stated convention doesn't settle, a step that does nothing, an empty result). A
failing assert here prints its line and message, so it tests a property, never compares with an
answer, and its message names the mock and the part, never a value. It sends the question back
for fresh numbers. Any other stop in values() (the reference's own assert or exit among them)
prints only its type and where it was raised, since its message may hold a value, and nothing the
reference prints reaches the terminal. A value() or reasoned() call whose slug isn't in MOCKS or
whose part isn't a part id (arguments swapped) is refused, naming its line, never its arguments.

A part whose type is trace, compute or table needs a value (FB-156): an answer that is a number,
an order or a table is always computed here (where the reference lacks the step, an extension
to it, tested in the self-test as 08-practice step 4 says). A
`reasoned(slug, part, why)` stands in only for an answer no arithmetic on the instance gives (a
bound read off a rule, a choice the course leaves open), cited from the notes. With no
checker, each such part is a `reasoned()` naming its cited source. A mock of proofs alone needs
none. Parts with no value are listed as reasoned in the KEY OK line. It fails when a value names
a part the mock lacks or names one twice, and when the key's parts differ from the mock's, a
part's answer is empty, or an Answer: line sits outside a bare `## Question N` block (mock_leak.py
would miss it), and stops, naming the file, at a mock or key that isn't UTF-8 text.
KEY OK prints only when the whole run passes. The terminal shows part ids, never an answer: the
student may be watching. With no key written yet it still writes the values (NO KEY) and exits
1. A run that crashes keeps the last good values file."""
import contextlib
import io
import os
import re
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I leaves the script dir out
HUB = os.path.dirname(os.path.dirname(HERE))
OUT_PATH = os.path.join(HUB, "practice", "mock-values-key.md")
COMPUTABLE = {"trace", "compute", "table"}
QUESTION = re.compile(r"^## Question (\d+)\b")
KEY_QUESTION = re.compile(r"^## Question (\d+)$")
PART_ID = re.compile(r"Q[1-9][0-9]*\([a-z]\)")
PART = re.compile(r"^\*\*\(([a-z])\) \(\d+ pts?\)\*\*")
TYPE = re.compile(r"^Type:\s*(.*)$")
ANSWER = re.compile(r"^\*\*\(([a-z])\)\*\* Answer:\s*(.*)$")
# A line break of any kind str.splitlines() knows: a value holding one would split in the values
# file, and a mock line holding one splits differently here and in mockpage.py.
BREAK = re.compile("[\n\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029]")

MOCKS = []  # ---- Fill in: the slugs of the mocks this hub has, e.g. ["exam1-1", "exam1-2"].
VALUES = {}
REASONED = {}


class Refused(Exception):
    """A call this checker refuses; its message names a mock, a part or a line, never a value."""


def called(fn, slug, part):
    """Stop at a call whose slug isn't in MOCKS or whose part isn't a part id, naming the call's
    line, never its arguments: swapped, one of them is an answer."""
    line = sys._getframe(2).f_lineno
    if slug not in MOCKS:
        raise Refused(f"mock_key.py:{line}: {fn}()'s first argument isn't a slug in MOCKS")
    if not (isinstance(part, str) and PART_ID.fullmatch(part)):
        raise Refused(f"mock_key.py:{line}: {fn}()'s second argument isn't a part id like Q2(a)")


def value(slug, part, computed):
    """The reference's answer to one part, formatted as the key writes it, on one line."""
    called("value", slug, part)
    if BREAK.search(str(computed)):
        raise Refused(f"mock_key.py: value({slug!r}, {part!r}) spans lines: the key's answer is one line")
    VALUES.setdefault(slug, []).append((part, str(computed)))


def reasoned(slug, part, why):
    """A part the reference can't compute, with why (a proof, a choice the course leaves open)."""
    called("reasoned", slug, part)
    if not str(why).strip():
        raise Refused(f"mock_key.py: reasoned({slug!r}, {part!r}) needs a why")
    REASONED.setdefault(slug, []).append(part)


def values():
    # ---- Fill in: import the reference and compute every computable part. -------------------
    # from reference import dijkstra
    # order, dist = dijkstra(GRAPH_Q2, "S", tie="alpha")
    # assert len(set(dist.values())) == len(dist), "exam1-1 Q2(a): a tie on distance"
    # value("exam1-1", "Q2(a)", f"{' '.join(order)}, dist(T) = {dist['T']}")
    # reasoned("exam1-1", "Q3(b)", "a proof")
    pass


def plain(s, underscores=True):
    """The answer as mock_leak.py's demark() reads it (code spans and math kept as written,
    emphasis marks dropped in pairs outside them, `__x__` and `_x_` only with underscores, `\\_`
    as `_`), whitespace runs one space."""
    kept = []

    def keep(m):
        kept.append(m.group(1) if m.group(1) is not None else m.group(0))
        return f"\x00{len(kept) - 1}\x00"

    s = re.sub(r"`([^`]+)`|\\\(.+?\\\)|\\\[.+?\\\]", keep, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    if underscores:
        s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)
    if underscores:
        s = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", s)
    s = s.replace("\\_", "_")
    s = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], s)
    return re.sub(r"\s+", " ", s).strip().rstrip(".").strip()


def literal(s):
    """A value as written: whitespace runs one space, a final period dropped."""
    return re.sub(r"\s+", " ", s).strip().rstrip(".").strip()


def read_lines(path):
    """The file's lines; one that isn't UTF-8 stops the run, named."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.readlines()
    except UnicodeDecodeError:
        raise SystemExit(f"mock_key.py: {path} isn't UTF-8 text") from None


def mock_parts(path):
    """{part id: its types} in the mock: a part's own Type: line, else its question's; a
    question with no parts is one part (a). Lines in a fenced code block or a figure block don't
    count, as mockpage.py reads them."""
    questions, current, inside = [], None, None
    for n, line in enumerate(read_lines(path), 1):
        if BREAK.search(line.rstrip("\n")):
            raise SystemExit(f"mock_key.py: {path}:{n}: a line break other than a newline: run mockpage.py")
        s, end = line.strip(), line.rstrip().endswith("</svg>")
        if inside == "code":
            inside = None if s.startswith("```") else inside
            continue
        if inside == "svg":
            inside = None if end else inside
            continue
        if s.startswith("```") or s.startswith("<svg"):
            inside = "code" if s.startswith("```") else (None if end else "svg")
            continue
        m = QUESTION.match(s)
        if not (m or questions):
            continue
        if m:
            questions.append((m.group(1), [], {}))
            current = None
        elif PART.match(s):
            current = PART.match(s).group(1)
            questions[-1][2][current] = []
        elif TYPE.match(s):
            types = [t.strip() for t in re.split(r"[|,]", TYPE.match(s).group(1)) if t.strip()]
            (questions[-1][2][current] if current else questions[-1][1]).extend(types)
    return {f"Q{n}({letter})": types or qtypes
            for n, qtypes, parts in questions for letter, types in (parts or {"a": []}).items()}


def key_answers(path):
    """{part id: the key's answer as written}, and its format problems: a part named twice, an
    empty answer, an Answer: line outside a bare `## Question N` block (mock_leak.py reads the
    same)."""
    out, bad, q = {}, [], None
    for n, line in enumerate(read_lines(path), 1):
        t = line.strip()
        if t.startswith("## "):
            m = KEY_QUESTION.match(t)
            q = m.group(1) if m else None
            continue
        m = ANSWER.match(t)
        if not m:
            continue
        if not q:
            bad.append(f"KEY LINE {n}: an Answer: line outside a bare ## Question N block (no title)")
            continue
        pid = f"Q{q}({m.group(1)})"
        if pid in out:
            bad.append(f"KEY TWICE {pid}")
        if not plain(m.group(2)):
            bad.append(f"KEY EMPTY {pid}: an Answer: line with no answer")
        out[pid] = m.group(2)
    return out, bad


def check(slug):
    """(lines to print, its KEY OK line, problems) for one mock."""
    mock = os.path.join(HUB, "practice", f"mock-{slug}.md")
    key = os.path.join(HUB, "practice", f"mock-{slug}-key.md")
    if not os.path.isfile(mock):
        return [], "", [f"NO MOCK {os.path.relpath(mock, HUB)}"]
    parts = mock_parts(mock)
    if not parts:
        return [], "", [f"{slug}: no parts read from {os.path.relpath(mock, HUB)} (templates/MOCK.md's format)"]
    got = VALUES.get(slug, [])
    named = [p for p, _ in got] + REASONED.get(slug, [])
    bad = [f"{slug} TWICE {p}" for p in sorted({p for p in named if named.count(p) > 1})]
    bad += [f"{slug} NOT IN THE MOCK {p}" for p in sorted(set(named) - set(parts))]
    bad += [f"{slug} UNCHECKED {p} ({', '.join(t)}): add a value(), or a reasoned() with why"
            for p, t in parts.items() if COMPUTABLE & set(t) and p not in named]
    lines = []
    if not os.path.isfile(key):
        return lines, "", bad + [f"NO KEY {os.path.relpath(key, HUB)}: write it from practice/mock-values-key.md"]
    answers, key_bad = key_answers(key)
    bad += [f"{slug} {b}" for b in key_bad]
    bad += [f"{slug} KEY LACKS {p}" for p in parts if p not in answers]
    bad += [f"{slug} KEY HAS {p}, NOT IN THE MOCK" for p in answers if p not in parts]
    for p, computed in got:
        if p in answers:
            ok = literal(computed) in (plain(answers[p]), plain(answers[p], underscores=False))
            lines.append(f"{'PASS' if ok else 'FAIL'}  {slug} {p}" +
                         ("" if ok else ": the key's answer isn't the value in practice/mock-values-key.md"))
            if not ok:
                bad.append(f"{slug} FAIL {p}")
    asserted = {p for p, _ in got}
    rest = [p for p in parts if p not in asserted]
    ok = (f"KEY OK: {slug}: {len(asserted)} of {len(parts)} parts asserted"
          + (f"; reasoned: {', '.join(rest)}" if rest else ""))
    return lines, ok, bad


def run_values():
    """values(), or a line saying where it stopped: a refused call or an assert of this file's with
    its message (a mock and a part), anything else, an exit too, with its type and place only (its
    message may hold a value). What the reference prints goes nowhere: a trace may show values."""
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            values()
    except Refused as e:
        return str(e)
    except BaseException as e:
        frames = traceback.extract_tb(e.__traceback__)
        here = [f for f in frames if os.path.abspath(f.filename) == os.path.abspath(__file__)]
        line, last = here[-1].lineno, frames[-1]
        if isinstance(e, AssertionError) and last in here:
            return f"mock_key.py:{line}: assert failed: {e}"
        return (f"mock_key.py:{line}: values() stopped: {type(e).__name__} at {os.path.basename(last.filename)}:"
                f"{last.lineno} (its message isn't printed: it may hold a value)")
    return None


def main():
    tmp = OUT_PATH + ".tmp"
    try:
        if not MOCKS:
            print("mock_key.py: NO MOCKS: list the hub's mock slugs in MOCKS")
            return 1
        if "values" in MOCKS:
            print("mock_key.py: a mock can't be called 'values': practice/mock-values-key.md is this script's")
            return 1
        stopped = run_values()
        if stopped:
            print(stopped)
            return 1
        with open(tmp, "w", encoding="utf-8") as out:
            out.write("# KEY VALUES: the mocks' computed answers (written by _build/verify/mock_key.py: "
                      "rerun it, never edit this file)\n\n> **STOP. Quarantined key.** Attempt the mocks "
                      "before opening this file.\n")
            for slug in MOCKS:
                out.write(f"\n## {slug}\n\n")
                for p, computed in VALUES.get(slug, []):
                    out.write(f"- {p}: {computed}\n")
        os.replace(tmp, OUT_PATH)
        problems, oks = [], []
        for slug in MOCKS:
            lines, ok, bad = check(slug)
            for line in lines:
                print(line)
            oks.append(ok)
            problems += bad
        for p in problems:
            print(f"mock_key.py: {p}")
        if problems:
            return 1
        for ok in oks:
            print(ok)
        return 0
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    sys.exit(main())
