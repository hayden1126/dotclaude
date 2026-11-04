#!/usr/bin/env python3
r"""A practice set's computed answers, for the tutor: every value it grades with comes from the reference.

exam-prep template verify-set-key.py, baseline as of 2026-10-20; changes only via `12-retro`.
Copy it to _build/verify/set_key.py and fill the marked part. Run from the hub root:

  python3 -I _build/verify/set_key.py      exit 0 only with a SET OK line per set

SETS names each set by its doc id in MANIFEST.md (`HW3`): a homework, a recitation or a practice
exam the student walks through (09-tutor) with no official solutions to grade against. Its parts
are the extracts' question blocks, `### [HW3 Q2a] <title>` in _build/extract/*.md (a stem's and a
page's blocks and fenced code aside), and each block's `**Shape:**` line says what the part asks.
For each part the reference can compute, `value("HW3", "Q2a", text)` gives its answer with every
intermediate value the reference gives, one per line (a trace's steps, a table's rows), so the
tutor can check partial work step by step (FB-162). Every part needs a value, or a
`reasoned("HW3", "Q2a", why)` when no arithmetic on its numbers gives the answer (a bound read off
a rule, a choice the course leaves open): its why names the method and where the notes state it,
never the answer, since the student sees the edit. The one exception is a part each of whose
Shape lines (a wrapped one read whole) starts with a kind no arithmetic answers (prove, show that,
justify, formulate, explain, define, true or false, a proof, a justification, a definition), asks
for nothing after it (no "and", "then" or ";") and names no trace, table, computation, run,
output or given instance: it is graded against the notes. A part whose block has no Shape line
is refused, and so is a heading like `### [HW3 Q2(a)]` that names a set's question but no part
id or stem. A part the reference can't compute yet
(it lacks a step, 09-tutor step 3) is `pending("HW3", "Q3c")`: SET OK lists it as waiting, and the
tutor doesn't grade it until its value() replaces the call. A set's values land in
practice/tutor/<doc>-values-key.md under a STOP header, indented as code, a reasoned part's why
beside it, and only when that set passes: a failed run keeps the last good file.

The student is in the session and attempts each part before the tutor reads its value (with the
Read tool, which shows it folded), so the terminal shows part ids, never an answer. A failing
assert of this file's prints its line and message, so it names the set and the part, never a
value. Any other stop in values() (the reference's own assert or exit among them) prints only its
type and where it was raised, and nothing the reference prints reaches the terminal: its standard
output and error point at the null device while values() runs, a child process's too. A value()
or reasoned() call whose doc isn't in SETS or whose part isn't a part id like Q2a (arguments
swapped) is refused, naming its line, never its arguments, and so is text holding a character
UTF-8 can't write, and so is a module of this folder imported outside values(), where what it
prints at import would reach the terminal. It fails when a value names a part no extract has or
names one twice, and stops, naming the file, at an extract that isn't UTF-8 text or whose code
fence never closes. SET OK prints only when the whole run passes."""
import contextlib
import glob
import io
import os
import re
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # -I leaves the script dir out
HUB = os.path.dirname(os.path.dirname(HERE))
EXTRACTS = os.path.join(HUB, "_build", "extract")
OUT_DIR = os.path.join(HUB, "practice", "tutor")
# extract_check.py's block header, a question part's form only; a stem's block holds no answer.
BLOCK = re.compile(r"^###\s+\[(?P<doc>[A-Za-z0-9_.-]+)\s+(?P<part>Q\d[\w.]*)\]")
STEM = re.compile(r"^###\s+\[[A-Za-z0-9_.-]+\s+Q\d[\w.]* stem\]")
# Any heading naming a doc's question: one that is neither a part nor a stem is refused.
QUESTION = re.compile(r"^#+\s*\[(?P<doc>[A-Za-z0-9_.-]+)\s+Q\d")
HEADING = re.compile(r"^#{1,3}\s")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
# A line that starts the block's next field ends a wrapped Shape line.
FIELD = re.compile(r"^(?:\*\*|[-*+]\s|Solution \[|Pages:)")
DOC_ID = re.compile(r"[A-Za-z0-9_.-]+")
PART_ID = re.compile(r"Q\d[\w.]*")
SHAPE = re.compile(r"^(?:[-*+]\s+)?\*\*Shape(?::\*\*|\*\*:)(.*)$")
COMPUTABLE = re.compile(r"\b(?:trac(?:e|ed|es|ing)|tables?|tabulat\w*|comput\w*|calculat\w*|solv\w*"
                        r"|run|runs|running|find\w*|evaluat\w*|simulat\w*|count(?:s|ed|ing)?|outputs?"
                        r"|this|these|given|above|below|following)\b", re.I)
SETTLED = re.compile(r"^(?:prove|show that|justify|formulate|explain|define|true or false|true/false"
                     r"|(?:an?\s+)?(?:proof|justification|definition)s?)\b", re.I)
SECOND = re.compile(r";|\b(?:and|then)\b", re.I)

SETS = []  # ---- Fill in: the doc ids of the sets to compute, e.g. ["HW3"].
VALUES = {}
REASONED = {}
PENDING = {}


class Refused(Exception):
    """A call this checker refuses; its message names a set, a part or a line, never a value."""


def called(fn, doc, part):
    """Stop at a call whose doc isn't in SETS or whose part isn't a part id, naming the call's
    line, never its arguments: swapped, one of them is an answer."""
    line = sys._getframe(2).f_lineno
    if doc not in SETS:
        raise Refused(f"set_key.py:{line}: {fn}()'s first argument isn't a doc id in SETS")
    if not (isinstance(part, str) and PART_ID.fullmatch(part)):
        raise Refused(f"set_key.py:{line}: {fn}()'s second argument isn't a part id like Q2a")


def writable(fn, doc, part, text, line):
    """Stop at text UTF-8 can't write (a lone surrogate), before the values file is opened."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise Refused(f"set_key.py:{line}: {fn}({doc!r}, {part!r}) holds a character UTF-8 can't write") from None


def value(doc, part, text):
    """The reference's answer to one part with its intermediate values, one per line."""
    called("value", doc, part)
    line = sys._getframe(1).f_lineno
    if not isinstance(text, str):
        raise Refused(f"set_key.py:{line}: value({doc!r}, {part!r}) needs text: "
                      "format the reference's result as the course writes it")
    if not text.strip():
        raise Refused(f"set_key.py:{line}: value({doc!r}, {part!r}) is empty")
    writable("value", doc, part, text, line)
    VALUES.setdefault(doc, []).append((part, text))


def reasoned(doc, part, why):
    """A part no arithmetic on its numbers answers, with why, cited from the notes."""
    called("reasoned", doc, part)
    line = sys._getframe(1).f_lineno
    if not str(why).strip():
        raise Refused(f"set_key.py:{line}: reasoned({doc!r}, {part!r}) needs a why")
    writable("reasoned", doc, part, str(why), line)
    REASONED.setdefault(doc, []).append((part, " ".join(str(why).split())))


def pending(doc, part):
    """A part whose value waits for an extension of the reference; it isn't graded until then."""
    called("pending", doc, part)
    PENDING.setdefault(doc, []).append(part)


def values():
    # ---- Fill in: import the reference and compute every computable part. -------------------
    # from reference import dijkstra
    # order, dist = dijkstra(GRAPH_HW3_Q2, "S", tie="alpha")
    # value("HW3", "Q2a", "\n".join([f"pop {u}: dist {dist[u]}" for u in order]))
    # reasoned("HW3", "Q4", "a proof: graded against §3.2's induction template")
    # pending("HW3", "Q3c")
    pass


def extract_parts():
    """({doc: {part: its Shape lines}}, {doc: [file:line of a question heading that is no part]})
    from every extract's question blocks, read line by line as extract_check.py reads them. A
    part's Shape lines come from each of its blocks, a wrapped one joined up to a blank line or the
    next field; a line inside fenced code is the part's text."""
    parts, odd = {}, {}
    for path in sorted(glob.glob(os.path.join(EXTRACTS, "*.md"))):
        rel = os.path.relpath(path, HUB)
        try:
            with open(path, encoding="utf-8") as f:
                lines = [line.rstrip("\n") for line in f]
        except UnicodeDecodeError:
            raise SystemExit(f"set_key.py: {rel} isn't UTF-8 text") from None
        current, wrapping, fence, opened = None, False, None, 0
        for n, line in enumerate(lines, 1):
            m = FENCE.match(line)
            if fence:
                # Closed only by a bare fence of its own character, at least as long (CommonMark).
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                    fence = None
                continue
            if m:
                fence, opened, wrapping = m.group(1), n, False
                continue
            m = BLOCK.match(line)
            if m:
                current, wrapping = parts.setdefault(m.group("doc"), {}).setdefault(m.group("part"), []), False
                continue
            m = QUESTION.match(line)
            if m and not STEM.match(line):
                odd.setdefault(m.group("doc"), []).append(f"{rel}:{n}")
            if HEADING.match(line) or m:
                current, wrapping = None, False
            elif current is not None:
                text = line.strip()
                s = SHAPE.match(text)
                if s:
                    current.append(s.group(1).strip())
                    wrapping = True
                elif wrapping and text and not FIELD.match(text):
                    current[-1] += " " + text
                else:
                    wrapping = False
        if fence:
            raise SystemExit(f"set_key.py: {rel}:{opened}: a code fence opened here never closes")
    return parts, odd


def settled(shape):
    """A Shape no arithmetic answers: it starts with such a kind, asks for nothing after it and
    names no computation."""
    return bool(SETTLED.match(shape)) and not COMPUTABLE.search(shape) and not SECOND.search(shape)


def check(doc, parts, odd):
    """(its SET OK line, problems) for one set."""
    bad = [f"{doc} BAD HEADING {at}: a ### [{doc} Q..] heading that is neither a part id like Q2a nor a stem"
           for at in odd]
    if not parts:
        return "", bad + [f"{doc}: no question blocks in _build/extract/ (### [{doc} Q..] headings)"]
    got = [p for p, _ in VALUES.get(doc, [])]
    named = got + [p for p, _ in REASONED.get(doc, [])] + PENDING.get(doc, [])
    bad += [f"{doc} TWICE {p}" for p in sorted({p for p in named if named.count(p) > 1})]
    bad += [f"{doc} NOT A PART {p}: no ### [{doc} {p}] block in _build/extract/" for p in sorted(set(named) - set(parts))]
    bad += [f"{doc} NO SHAPE {p}: its block has no **Shape:** line (the extract brief's format): add it, "
            "or give the part a value() or a reasoned()" for p, shapes in parts.items() if not shapes and p not in named]
    bad += [f"{doc} UNCHECKED {p}: add a value(), or a reasoned() with why (only a proof, a justification, a "
            "definition or a true-or-false is left to the notes)"
            for p, shapes in parts.items() if shapes and not all(map(settled, shapes)) and p not in named]
    rest = [p for p in parts if p not in named]
    ok = (f"SET OK: {doc}: {len(got)} of {len(parts)} parts computed"
          + (f"; reasoned: {', '.join(p for p, _ in REASONED.get(doc, []))}" if REASONED.get(doc) else "")
          + (f"; waiting: {', '.join(PENDING[doc])}" if PENDING.get(doc) else "")
          + (f"; from the notes: {', '.join(rest)}" if rest else ""))
    return ok, bad


def run_values():
    """values(), or a line saying where it stopped: a refused call or an assert of this file's with
    its message (a set and a part), anything else, an exit too, with its type and place only (its
    message may hold a value). What the reference prints goes nowhere: a trace may show values."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved, null = (os.dup(1), os.dup(2)), os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null, 1)
        os.dup2(null, 2)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            values()
    except Refused as e:
        return str(e)
    except BaseException as e:
        frames = traceback.extract_tb(e.__traceback__)
        here = [f for f in frames if os.path.abspath(f.filename) == os.path.abspath(__file__)]
        line, last = here[-1].lineno, frames[-1]
        if isinstance(e, AssertionError) and last in here:
            return f"set_key.py:{line}: assert failed: {e}"
        return (f"set_key.py:{line}: values() stopped: {type(e).__name__} at {os.path.basename(last.filename)}:"
                f"{last.lineno} (its message isn't printed: it may hold a value)")
    finally:
        # Bytes the reference left in a stream's buffer (sys.__stdout__'s through a pipe) go to the
        # null device too, before the terminal is back.
        for stream in (sys.__stdout__, sys.__stderr__):
            with contextlib.suppress(Exception):
                stream.flush()
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        for fd in (*saved, null):
            os.close(fd)
    return None


def write(doc):
    """practice/tutor/<doc>-values-key.md, replaced whole."""
    path = os.path.join(OUT_DIR, f"{doc}-values-key.md")
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as out:
            out.write(f"# TUTOR VALUES: {doc} (written by _build/verify/set_key.py: rerun it, never edit this "
                      "file)\n\n> **STOP. Quarantined key.** The student attempts each part before the tutor "
                      "reads its value here.\n")
            for part, text in VALUES.get(doc, []):
                out.write(f"\n## [{doc} {part}]\n\n")
                out.writelines(f"    {line}\n" for line in text.splitlines())
            for part, why in REASONED.get(doc, []):
                out.write(f"\n## [{doc} {part}]\n\nReasoned: {why}\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main():
    bad_ids = [d for d in SETS if not (isinstance(d, str) and DOC_ID.fullmatch(d))]
    if not SETS or bad_ids:
        print("set_key.py: NO SETS: list the doc ids of the sets to compute in SETS" if not SETS else
              "set_key.py: SETS holds an entry that isn't a doc id like HW3")
        return 1
    hoisted = sorted(name for name, mod in list(sys.modules.items()) if name != "__main__"
                     and os.path.abspath(getattr(mod, "__file__", None) or os.sep).startswith(HERE + os.sep))
    if hoisted:
        print(f"set_key.py: {hoisted[0]} is imported outside values(): import it inside values(), where what "
              "it prints goes nowhere")
        return 1
    stopped = run_values()
    if stopped:
        print(stopped)
        return 1
    parts, odd = extract_parts()
    oks, problems = [], []
    for doc in SETS:
        ok, bad = check(doc, parts.get(doc, {}), odd.get(doc, []))
        oks.append(ok)
        problems += bad
        if not bad:
            os.makedirs(OUT_DIR, exist_ok=True)
            write(doc)
    for p in problems:
        print(f"set_key.py: {p}")
    if problems:
        return 1
    for ok in oks:
        print(ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
