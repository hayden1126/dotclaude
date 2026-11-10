# 05 Verify

Baseline as of 2026-11-10; changes only via `12-retro`.

Nothing reaches the student unverified. Verification has three parts: a checker that computes
every value the notes print, reviewers who read every section against its sources, and fixes
applied by the main session alone. The checker starts early, during `02-extract`, because the
backbone's worked examples (`03-backbone`, step 7) already need it.

## Step 1: The checker

PLAN.md's Checker line says what this course can compute: arithmetic, search or game traces,
executed queries and relational algebra (Python's `sqlite3` runs SQL with no install), rule
derivations.

- Write the reference in `_build/verify/`. Every convention an answer depends on (a tie-break
  order, when a check runs, a numbering) is an explicit parameter, never a hidden default: the
  backbone's Conventions block names them.
- Copy `<skill>/templates/verify-selftest.py` to `_build/verify/selftest.py`. Add one `check` per
  official answer part, cited to its page, and a `skip` with its shape for a part the reference
  can't compute (a proof); set `PARTS` to the number of official parts, counted as its docstring
  says (FB-100). Add an `example` for each worked example the course itself shows: before any
  official solutions are out, those are what test the reference. `python3 -I
  _build/verify/selftest.py` must print `ALL PASS` with every part covered once before anything
  uses the reference.
- A FAIL means a convention the reference doesn't model yet or a misread extract: fix that. An
  expected value changes only when a 300 dpi re-read of its page shows the extract misread it
  (fix the extract too), or when the official answer itself is wrong (an erratum, logged in
  STATUS and in the backbone's Conventions block). Never change one to match the checker.
- Worked examples come from `<skill>/templates/verify-examples.py`, copied to
  `_build/verify/examples.py` (`03-backbone`, step 7). It writes `examples.out.md` and replaces
  it only when the run succeeds and covers every worked example the backbone lists.
- When PLAN.md's Checker line says nothing in the course is computable, there is no reference,
  self-test or `examples.py`. Skip to step 3: reviewers check every value against its cited
  source and redo the working of each worked example the writers built, and the cold solver
  checks the mock. A `TODO-VERIFY` left anyway is resolved from its source in step 5.

## Step 2: Fill every TODO-VERIFY

Take the list `04-write` put in STATUS (`grep -n TODO-VERIFY notes/*.md` again). For each marker,
add a `value-<slug>` section to `examples.py` that computes it (a value a worked example prints is
already there), rerun it, and copy the value from `examples.out.md` over the marker: a rerun then
reproduces every number the notes print. Then compare every worked example in the notes, and
every value filled from a `value-` section, with `examples.out.md`, by script, never by eye: a
number typed by hand has been wrong before (FB-101, L50). Copy
`<skill>/templates/compare-notes.py` to `_build/verify/compare_notes.py` and set its `FILLED` to
each `value-` section and the notes file it filled. First `python3 -I
_build/verify/compare_notes.py --self-test` must print `SELF-TEST OK`: it plants a changed number
and a swapped visit order into a copy of the notes (a hand-written first version passed both).
Then `python3 -I _build/verify/compare_notes.py` must print `NOTES MATCH`; each line it prints
otherwise names the file and line, the subsection, the example and the values. It reads a trace's
names only in backticks, as CONVERT.md keeps them.

## Step 3: Section reviewers

Spawn one `reviewer` per section file, all at once (FB-102), each from
`<skill>/templates/agent-briefs.md`, section "Review". It checks in rank order:

1. **Accuracy:** every claim against its cited extract block, every value against
   `examples.out.md` or the self-test (with no checker, against its source, each worked example's
   working redone).
2. **Coverage:** every row the backbone gives the section, and every extract block the coverage
   matrix maps into it.
3. **Direction and causation:** which condition guarantees which result (S5).
4. **STYLE:** the rest of `_build/STYLE.md`, each subsection's depth label (S33) among it.

Each brief names the answer sets the student hasn't attempted: the notes quote none of them, and
a quote is a blocker. Findings come back ranked blocker, major, minor, in at most 700 words.
Reviewers never open `practice/` (FB-105). Give each reviewer the diagram slides of its section
that no checker trace covers (`02-extract` listed them in STATUS), to compare with the extract and
the page image (FB-104).

## Step 3b: Cold read

A section reviewer reads with the sources open, so a term the section never defines still reads
as clear to it. One fresh `reviewer` per two or three sections, spawned with step 3's, from
`<skill>/templates/agent-briefs.md`, section "Cold read" (FB-109). It sees only its sections'
notes files: no extract, no source, no checker output, and never `practice/`. It reads as a
student who skipped the lectures, and lists by line:

- each term or symbol used before it is defined (S14, S15);
- each sentence that can't be understood alone (S18);
- each pitfall or table cell without its exact condition and a mini-instance (S23);
- each pair of look-alike notions (symbols, operators, variants of one procedure) with no single
  comparison table (S31);
- each optional notation without when it is required, when it is allowed, and whether leaving it
  out costs marks (S28).

Its findings are majors, settled and applied in step 5 like the section reviewers'.

## Step 4: Audit the condensations

Fresh reviewers, not the section reviewers, spawned together with step 3's (they read different
things), check every condensation against the sources: here
the Must-know checklists, one reviewer per two or three sections, from the brief's "Audit"
variant (FB-105). The cheat sheet (`07-cheatsheet`) and the cram order (`08-practice`) get the
same audit when they exist.

## Step 5: Apply the fixes

- Check a reviewer's claim before applying it: with the checker when it is computable, otherwise
  by re-reading the cited page (FB-108). A reviewer has been wrong too.
- The main session applies every fix, one at a time (FB-108). A correction fixes every copy of the
  fact: the notes, the Must-know line, a pitfall box, the sheet. Grep for the old value or phrase to
  find them (FB-106), and leave a finished exam's archive (`practice/<exam-slug>/`,
  `cheatsheet/<exam-slug>/`, `11-next-exam`) as it is: it is frozen. No fix quotes an answer from a
  set MANIFEST doesn't mark `yes, attempted`.
- A change to the reference or to a convention reruns `selftest.py` and `examples.py`, then step
  2's comparison of every worked example and every filled `value-` (STATUS's TODO-VERIFY list)
  with the new `examples.out.md`: the notes copied the old one. Once `08-practice` has keys,
  `mock_key.py` reruns too (its step 4's rerun clause).
- With no checker, a `TODO-VERIFY` a writer left anyway is replaced with the value its cited
  source gives, or the working that derives it.
- Before anything is published, the questions check: check the notes against every set the
  student hasn't attempted (FB-191), since a worked example has rebuilt a practice question's
  setup, and a gloss has named a practice step. Those sets, all read from MANIFEST.md: each set
  answered by a row whose Answers cell is exactly `yes` (not `yes, attempted`); and each question
  set that no row's `solutions to <doc>` names, unless its own row's Answers cell reads `no,
  attempted YYYY-MM-DD` (the one place a set with no solutions row records its attempt:
  `00-intake` and `11-next-exam` write it from the student's word, `09-tutor` Step 7 when its last
  part is done).
  With no such set, skip the run and log `no unattempted set` in STATUS. Otherwise give each set's
  extract
  (`_build/extract/<name>.md`) as a question file, and the lecture extracts the notes cite as
  allowed sources:
  `python3 -I <skill>/scripts/mock_leak.py --questions <the sets' extracts> --allow <the lecture
  extracts> --pages notes/*.md`. The main session runs it, since reviewers never open `practice/`.
  Each hit names a notes line and a set's part, never the text. The Review view (`07-cheatsheet`)
  only tags blocks of the notes, so this check covers it, and every later change runs it as
  `08-practice`'s "Changing the notes or a sheet" item 4 says.
  A hit is a blocker: rewrite the passage with fresh numbers and a fresh setup (S7), and rerun
  until it prints QUESTIONS OK. A passage cut or held back instead, which the student may want
  back once they attempt the set, goes to `_build/held.md`, one entry per passage: its section,
  the set it overlapped and the original text. It is quarantined (hub CLAUDE.md), and `09-tutor`
  offers it back once that set is attempted (its Step 7). A hub whose CLAUDE.md lacks the
  quarantine line (a hub made before it existed) gets it now, before the first entry is written:
  the `_build/held.md` bullet of `<skill>/templates/hub-CLAUDE.md.tmpl`'s Repo rules, copied as it
  stands.
- Then rerun `selftest.py` (with a checker) and `linkcheck.py` (plain-text notes: the references
  by hand, `04-write` step 6). Log in STATUS any finding left unapplied, with why, and any claim
  refuted, with the evidence.

## Official solutions that arrive late

Add them to the self-test (and to `PARTS`), diff every answer against the notes and any solved
key, and record the verdict in STATUS: what matched, what was wrong, what changed (FB-107). One
that changes the reference or a convention reruns the examples as in step 5.

## The mock

`08-practice` runs this once the mock is drafted. A cold solver (a `reviewer`, from the brief's
"Cold solver" section) works the mock without the key (FB-103). Each answer where it and the key
disagree is settled with the checker, or the source when nothing is computable (logged in
STATUS by its part and what changed, never a value: the student hasn't attempted it), and the
question or the key is fixed. Every computable key value is asserted by the key
script (`08-practice`).

## Done when

`selftest.py` prints `ALL PASS` with every official part covered (or PLAN.md's Checker line says
nothing is computable); no `TODO-VERIFY` is left; every blocker and major finding is applied or
refuted with evidence in STATUS, and every minor one applied or logged there; `mock_leak.py
--questions` prints `QUESTIONS OK` on the notes, or no unattempted set, logged in STATUS (step 5);
`linkcheck.py` exits
0 (plain-text notes: references checked by hand); the fixes are committed.
