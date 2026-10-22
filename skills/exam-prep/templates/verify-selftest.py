#!/usr/bin/env python3
r"""Self-test: the reference must reproduce every official solution before anything uses it.

exam-prep template verify-selftest.py, baseline as of 2026-10-20; changes only via `12-retro`.
Copy it to _build/verify/selftest.py and fill the marked parts. Run from the hub root:

  python3 -I _build/verify/selftest.py      exit 0 only when every check passes

The reference (the course's own code in _build/verify/, conventions as explicit parameters) is
imported below. Each `check` names the official answer part it reproduces, cited the way the
notes cite (`HW1 Q2c [HW1S p.3]`), so a FAIL points at the page to read. An official part the
reference can't compute (a proof, an explanation) is a `skip` with its shape. An `example` checks
a worked example the course itself shows (a slide, a reading): it isn't an official part, but it
tests the reference before any solutions are out. PARTS is the number of official answer parts
the extracts hold:

  grep -hE '^[-*[:space:]]*Solution \[' _build/extract/*.md | wc -l

It passes only when its checks and skips name exactly PARTS distinct parts, none twice: a
self-test that checks three of forty answers proves little. With no check and no example it
fails: an empty self-test proves nothing."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I leaves the script dir out

PARTS = None  # ---- Fill in: the official answer parts the extracts hold (the grep above).
FAILS = []
RUN = []
SKIPPED = []
EXAMPLES = []


def compare(name, got, want, tol):
    if tol is None:
        ok = got == want
    else:
        ok = math.isclose(got, want, abs_tol=tol)
    print(f"{'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n      got  {got!r}\n      want {want!r}"), flush=True)
    if not ok:
        FAILS.append(name)


def check(name, got, want, tol=None):
    """One official answer part. `tol` compares numbers within an absolute tolerance."""
    RUN.append(name)
    compare(name, got, want, tol)


def skip(name, shape):
    """An official part the reference can't compute, with the shape of its answer."""
    SKIPPED.append(name)
    print(f"SKIP  {name} ({shape})", flush=True)


def example(name, got, want, tol=None):
    """A worked example the course itself shows; not an official part."""
    EXAMPLES.append(name)
    compare(name, got, want, tol)


def checks():
    # ---- Fill in: import the reference and reproduce every official solution. --------------
    # from reference import solve
    # check("HW1 Q2a [HW1S p.2]", solve(GRAPH, start="S", tie="alpha"), ["S", "A", "G"])
    # skip("HW1 Q4 [HW1S p.5]", "prove")
    # example("D3 p.12 worked example", solve(SLIDE_GRAPH, start="A", tie="alpha"), ["A", "C"])
    pass


def main():
    checks()
    if not RUN and not EXAMPLES:
        print("NO CHECKS: add one per official answer, or a course example, before anything "
              "uses the reference")
        return 1
    parts = RUN + SKIPPED
    twice = sorted({n for n in parts if parts.count(n) > 1})
    gap = []
    if twice:
        gap.append(f"TWICE {twice}: one check or skip per official part (a part with two "
                   "values is one check of both)")
    if not isinstance(PARTS, int) or isinstance(PARTS, bool):
        gap.append("PARTS NOT SET: count the official answer parts (see the docstring)")
    elif len(set(parts)) != PARTS:
        gap.append(f"COVERS {len(set(parts))} OF {PARTS} OFFICIAL PARTS: add a check or a skip "
                   "for each")
    print(f"\n{len(RUN)} checks, {len(SKIPPED)} skipped, {len(EXAMPLES)} course examples: "
          + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
    for g in gap:
        print(g)
    return 1 if (FAILS or gap) else 0


if __name__ == "__main__":
    sys.exit(main())
