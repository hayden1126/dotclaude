# 03 Backbone

Baseline as of 2026-11-12; changes only via `12-retro`.

The backbone turns source-ordered extracts into the notes' plan: concept order, every section
number, title and link id, the conventions, the figures, how each part is tested, and a coverage
matrix proving nothing was dropped. Parallel writers start from it, so it is written by the main
session alone and fixed before any writer starts (FB-060, FB-054). The output is
`_build/backbone.md`, from `<skill>/templates/backbone.md.tmpl`.

## Step 1: Read every extract

The main session reads all of `_build/extract/` and `_build/solutions/` (a set's conventions
show in its official solutions; the backbone quotes none of their answers), every staff item in
the Ed digest (a convention such as a tie-break may be tagged `scope` or `format`, not only
`hint`) and the practice questions. When an extract or a solutions file got something wrong,
re-check it on the page image, then fix it in that file itself (writers read both), list it at
the top of the backbone, and carry it into the checker. Read MANIFEST.md's topic cuts too: under
the backbone's Conventions block, one line per cut, naming the subsections it reaches and what of
it stays in scope (04-write banners the material it takes out). A cut first seen in the Ed digest during the build goes under MANIFEST.md's Topic
cuts too, logged in STATUS as a judgment call.

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
answers follow, in that same place. The block also lists each notation the answers use, each with
its staff source (the staff sheet, solution or post that writes it so): notation the staff's own
sheets use wins over the slides' and over a hub's own conventions (FB-089).

## Step 5: Shortlist the figures

Diagrams are often faster to learn from than words, and notes with too few get set aside for the
slides; notes that carry every slide diagram bury the ones that teach. So the figures come from a
sweep, then a cut (STYLE S11).

1. **The mechanism sweep.** Section by section, list every candidate in the backbone's Mechanism
   sweep table, one row each: every mechanism whose parts pass data (a pipeline whose stages hand
   values on), every construction whose count or shape matters, every comparison of two
   structures, and every trace of a drilled procedure; the slides' own diagrams for the section are candidates too
   (FB-062). Each row is kept or cut, with a short reason: a redundant, decorative or out-of-scope
   slide diagram is cut freely, since the slides' diagrams are candidates, not a quota.
2. **Diagram-taught.** Mark each section `Diagram-taught: yes` when its slides teach it through
   diagrams (cite them), else `no`, on the line beside its Figures line. A `yes` section keeps at
   least one figure and leads with it. An older section this run doesn't sweep (a reopened hub's,
   one `11-next-exam`'s source path leaves as written, or one a `10-polish` figure pass over other
   sections leaves) that has no line gets
   `- Diagram-taught: pre-S11` (FB-015): `coverage_check.py` passes it with a warning naming
   `10-polish`'s figure pass, which sets `yes` or `no`, while a section with no line at all fails
   once any section carries one.
3. **The shortlist.** Every kept row becomes a row of the Figure shortlist, saying why prose isn't
   enough, and its kind: `static` (drawn as SVG), `step-through` (each trace of a drilled
   procedure, fed later by the checker's data, FB-117) or `slide image` (a slide's own picture,
   cropped, only for a reference picture too costly to redraw: a component photo, a dense
   schematic; a mechanism is always redrawn). The shortlist lives in the backbone's Figure
   shortlist table, and STATUS points there; each figure is also on its section's Figures line.
   Every backticked id in the backbone is in the registry `linkcheck.py` checks, so a figure
   dropped later loses both its shortlist row and its Figures line.
4. **The student's adds and cuts.** While the build's `Build running` line stands, or
   `11-next-exam`'s "A source added to this exam" runs this stage under its own, nothing is
   asked (hard rule 1, and while a mock is untaken the student has looked away), and the
   figures are built from the shortlist as it stands: write the shortlist rows and the Mechanism
   sweep's cut rows of the sections this run swept, one line each, to `_build/logs/figures.md`.
   While STATUS has a `Figure shortlist:` line, the rows the log already holds are still waiting
   for the student, so they stay and only a section this run swept again has its rows replaced (a
   source path's run doesn't drop the build's rows); with no such line, the rows there were
   reviewed (refused, settled by a figure pass, or a previous exam's), so this run's rows replace
   them. Then put `Figure shortlist: <N> kept, <M> cut, for the student to review
   (_build/logs/figures.md)` in STATUS as a judgment call (hard rule 10), counting only the rows
   the log now holds, in place of any `Figure shortlist:` line already there (STATUS keeps one).
   `08-practice` step 8's opening offers it; after `Stage 08 built`, when that opening has
   passed, the source path's step 5 report to the student offers it instead. The student's adds
   and cuts go in by a `10-polish` figure pass, a cut of a figure the build already drew among
   them. Run alone, which
   means with no `Build running` line, on request with the student present, or as a `10-polish`
   figure pass (which runs this step under its own `Build running` line), show the shortlist and
   the cut rows, one line each, before any figure is built (FB-062), and apply what they add or
   cut.

`coverage_check.py` (step 8) fails a `Diagram-taught: yes` section whose Figures line names no
figure.

## Step 6: Map how it's tested

Every practice question part gets a row in the How it's tested table: its shape and conventions
(from its extract block's `**Shape:**` and `**Conventions:**` lines) and the subsection that
teaches it. Every subsection but the Must-know list lists its practice and a "How it's tested"
line (FB-063). A claim
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

`coverage_check.py` exits 0 (every block mapped, every diagram-taught section with its figure);
every id is in the registry; every section this run writes has its Diagram-taught line, and every
older section without one is marked `pre-S11` (step 5.2, FB-015); the backbone holds the figure
shortlist (logged in STATUS as one `Figure shortlist:` line while the build's or the source
path's `Build running` line stands, shown to the student when run alone or in a `10-polish`
figure pass); every practice question part has its How it's tested row; `examples.py` exits 0, or PLAN.md's Checker line says nothing in the course
is computable; and the backbone is committed.
