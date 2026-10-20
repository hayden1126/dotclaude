# 03 Backbone

Baseline as of 2026-10-20; changes only via `12-retro`.

The backbone turns source-ordered extracts into the notes' plan: concept order, every section
number, title and link id, the conventions, the figures, how each part is tested, and a coverage
matrix proving nothing was dropped. Parallel writers start from it, so it is written by the main
session alone and fixed before any writer starts (FB-060, FB-054). The output is
`_build/backbone.md`, from `<skill>/templates/backbone.md.tmpl`.

## Step 1: Read every extract

The main session reads all of `_build/extract/`, the Ed digest's hint items and the practice
questions. When an extract got something wrong, re-check it on the page image, then fix it in the
extract itself (writers read the extracts), list it at the top of the backbone, and carry it into
the checker.

## Step 2: Order by concept

Sections follow the order a reader needs: a concept before its first use, a procedure after the
model it runs on. Slide order and lecture boundaries don't decide it (FB-050). Split the notes
into sections of a size one writer can own, one file each (`notes/NN-<slug>.md`).

Weight depth by how the exam tests (FB-064): a procedure the practice traces gets full depth and a
worked example; definitional material stays brief. Mark each section `concise` or `full`.

## Step 3: Fix the ids

Every section, subsection, lettered set member, figure and worked example gets its id now:
`sec-N`, `sec-N-<slug>`, `set-<name>-a`, `fig-N-<slug>`, `ex-N-<slug>`. Writers use them verbatim;
a link names its target in words. Worked examples and figures also get display numbers in section
order ("Worked example 4.3", "Fig 5.1"), so a link from another section can name them. Lettered
sets are lettered once, here, with their source. Each section ends with a "Must know" subsection
(`sec-N-must-know`).

## Step 4: State the conventions once

Every convention an answer depends on (a tie-break order, when a check runs, how a board is
numbered) goes in the Conventions block with the one subsection that states it; every other use
links there (FB-065). Where the slides and the official solutions disagree, say which one the
answers follow, in that same place.

## Step 5: Shortlist the figures

Look from both directions: the notes' mechanisms that prose can't carry, and the slides' own
diagrams (FB-062). Each row of the shortlist says why prose isn't enough. Pick two or three
step-throughs for the most-drilled procedures, fed later by the checker's data. The shortlist
lives in the backbone's Figure shortlist table, and STATUS points there; each figure is also on
its section's Figures line. Every backticked id in the backbone is in the registry
`linkcheck.py` checks, so a figure dropped later loses both its shortlist row and its Figures
line.

## Step 6: Map how it's tested

Every practice question part gets a row in the How it's tested table: its shape and conventions
(from its extract block's `**Shape:**` and `**Conventions:**` lines) and the subsection that
teaches it. Every subsection lists its practice and a "How it's tested" line (FB-063). A claim
about the exam itself (what it will ask, its format, what it stresses) cites the instructor's
exam-format statement or an item in the Ed digest's tag sections (staff-authored, or an endorsed
answer), never a student signal or a guess (FB-012).

## Step 7: Generate the worked examples

Worked examples use fresh numbers, not the homework's (FB-071). Their data and every trace come
from the checker (`python3 -I _build/verify/examples.py` writes
`_build/verify/examples.out.md`): a hand-picked input has been unsolvable or degenerate, and hand
traces were wrong seven times in one run (L50). If the generator runs for minutes, stop and fix it
(constant-time membership, flushed output; L51). When nothing in the course is computable, the
writers make the examples and `05-verify`'s reviewers check them against the cited sources.

## Step 8: The coverage matrix

Map every extract block to a subsection, or to `skip (why)` for logistics, credits and photos with
no exam content (FB-061). A row's first cell names blocks as `D4 pp.17-20, 23`, `D4 p.1, p.32`,
`D2 #/3-7` (reveal slides by horizontal index), `HW1 Q1-Q3` or `HW1 Q3a-d`; a source without pages
(a Word file, code) is mapped whole by `W1 (all)`. A part range (`HW1 Q3a-d`) covers only those
parts, so a part the row leaves out shows as unmapped. A row's last cell is `skip (why)` or
subsection numbers (`2.3, 2.4`), with any note in parentheses after them. Then run
`python3 -I <skill>/scripts/coverage_check.py`: it lists every block no row covers, every row it
can't parse or whose target isn't a subsection, and every line that looks like a block header
but isn't one.

## Done when

`coverage_check.py` exits 0; every id is in the registry; every practice question part has its
How it's tested row; `examples.py` exits 0, or PLAN.md's Checker line says nothing in the course
is computable; and the backbone is committed.
