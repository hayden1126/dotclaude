# 05 Verify

Baseline as of 2026-11-12; changes only via `12-retro`.

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
- Copy `<skill>/templates/verify-selftest.py` to `_build/verify/selftest.py`. The official
  answers are the part blocks of the solutions files, `_build/solutions/<name>.md` (`02-extract`,
  "The solutions file"), which the checker reads beside the extracts. Add one `check` per
  official answer part, cited to its page, and a `skip` with its shape for a part the reference
  can't compute (a proof). A part whose official value is marked `(illegible at 300 dpi: ...)` is
  a `skip` naming that mark until the student supplies the value (`02-extract` step 3.2), then a
  `check`. Set `PARTS` to the number
  `python3 -I <skill>/scripts/extract_check.py --parts` prints from the hub root: one per question
  part whose solutions block holds a `Solution [` line, never a lecture's worked example
  (FB-100). Add an `example`
  for each worked example the course itself shows: before any official solutions are out, those
  are what test the reference. `python3 -I _build/verify/selftest.py` must print `ALL PASS` with
  every part covered once before anything uses the reference.
- A FAIL means a convention the reference doesn't model yet or a misread extract: fix that. An
  expected value changes only when a 300 dpi re-read of its page shows the extract or solutions
  file misread it (fix that file too), or when the official answer itself is wrong (an erratum).
  Never change one to match the checker. An erratum is logged in STATUS by doc, page and part
  (`HW1S p.2, HW1 Q2a: erratum`), and the corrected value goes only in the part's block in its
  set's solutions file, on an `Erratum: <the corrected value, and why>` line under the
  `Solution [` line, the official line kept as it stands. The backbone's Conventions block names
  the doc and part only, never a value (`03-backbone` step 4): mock writers and the sheets' gap
  scan read the backbone, and STATUS too names no value.
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

Each brief names the sets the student hasn't attempted (each one whose own MANIFEST.md row lacks
`attempted`): the notes quote none of their official solutions, and a quote is a blocker. Its
`{{SOLUTIONS FILES}}` slot names the solutions files that hold the
blocks of the question parts and answers docs the section's extract blocks cite, each block
found in its home file (`02-extract`, "The solutions file"), never by a search across
`_build/solutions/*.md`: for each part the coverage matrix maps into the section (`[HW1 Q2a]`),
its set's solutions file, `_build/solutions/<name>.md` under the set's extract name, read with
the stem block `### [HW1 Q2 stem]` before its parts when there is one; for each answers doc page
its blocks cite (`[HW1S p.2]`), its answers file's home: the one set's file when the Key cell is
`for <one doc>`, `_build/solutions/<doc id in lower case>.md` (`hws.md` for `HWS`) when the cell
names several docs, or the file beside the doc's own extract for a doc holding its own key; or
`none`. Its `{{ANSWER FILES}}` slot
names each file MANIFEST.md marks `Answers: yes` that solves one of those parts: wording that
tracks an official solution, its part's block in those solutions files, is a finding (FB-071),
reworded from the slide or derived plainly in step 5. Findings come back ranked blocker, major,
minor, in at most 700 words.
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
variant (FB-105), its `{{EXTRACT FILES}}` slot filled with the extracts its sections cite
(`_build/extract/`, which hold no answer; FB-056). The cheat sheet (`07-cheatsheet`) and the cram
order (`08-practice`) get the same audit when they exist.

## Step 5: Apply the fixes

- Check a reviewer's claim before applying it: with the checker when it is computable, otherwise
  by re-reading the cited page (FB-108). A reviewer has been wrong too.
- The main session applies every fix, one at a time (FB-108). A correction fixes every copy of the
  fact: the notes, the Must-know line, a pitfall box, the sheet. Grep for the old value or phrase to
  find them (FB-106), and leave a finished exam's archive (`practice/<exam-slug>/`,
  `cheatsheet/<exam-slug>/`, `11-next-exam`) as it is: it is frozen. No fix quotes an answer from a
  set whose own MANIFEST.md row doesn't say `attempted`.
- A change to the reference or to a convention reruns `selftest.py` and `examples.py`, then step
  2's comparison of every worked example and every filled `value-` (STATUS's TODO-VERIFY list)
  with the new `examples.out.md`: the notes copied the old one. Once `08-practice` has keys,
  `mock_key.py` reruns too (its step 4's rerun clause).
- With no checker, a `TODO-VERIFY` a writer left anyway is replaced with the value its cited
  source gives, or the working that derives it.
- Before anything is published, the questions check: check the notes and sheets against every set the
  student hasn't attempted (FB-191), since a worked example has rebuilt a practice question's
  setup, and a gloss has named a practice step. Those sets, all read from MANIFEST.md: each
  question set (one an answers file's Key cell `for ...` names, a past exam holding its own
  key, or a set with no answers anywhere) whose own row's Answers cell lacks `attempted`. A set
  records its attempt in its own row only, as `no, attempted YYYY-MM-DD` (no key of its own) or `yes, attempted
  YYYY-MM-DD` (a doc holding its own key): `00-intake` and `11-next-exam` write it from the
  student's word, `09-tutor` Step 7 when its last part is done. A separate answers file's row
  stays `yes` and never records an attempt, since it may solve several sets.
  The main session runs it from `<root>`, since reviewers never open `practice/`:
  `python3 -I <skill>/scripts/mock_leak.py --hub .`. It checks every page under `notes/` and
  the sheets directly in `cheatsheet/` (once `07-cheatsheet` writes them; a finished exam's
  frozen archive, `cheatsheet/<exam-slug>/`, isn't read), so no page is passed by hand
  either. It reads those attempt
  marks and the extracts and builds its own file list, so no file is passed by hand: the question files
  hold the unattempted sets' official text (each such set's extracts and solutions files, and a
  multi-set answers file's own file, its pages in full, while any set it solves is unattempted),
  and every other extract, the lectures the notes cite among them, is an allowed source. When a
  hit needs explaining, `python3 -I <skill>/scripts/extract_check.py --leak-files` prints that
  list, a `questions <path>` or `allow <path>` line per file. With no such set it prints
  `QUESTIONS OK: no unattempted set` and exits 0: log `no unattempted set` in STATUS. It reads
  extracts and solutions files, plus one exception: a set, or an answers file that solves one,
  whose File is neither a PDF nor a reveal deck (a Word file, a plain course page) has its
  rendered text read too (`_build/text/<doc>.md`, or a non-deck `.html` page's own file), beside
  its extract and never in its place. So every unattempted set needs a block in an extract, and
  every answers file that solves one a block in a solutions file, before the check can pass: an
  answers file added late (`09-tutor` step 6) is extracted first. It exits 2, with the reason
  on stderr, on four causes, each fixed and then rerun: the hub has no MANIFEST.md or one it
  can't read (fix MANIFEST.md as the reason says); a file it reads isn't UTF-8, named in the
  message (an extract or solutions file: rewrite it as UTF-8; a page, a sheet or a course
  page's `.html` source in `sources/`: save it as UTF-8); no page is found (`no page found`: no
  notes and no sheet yet; run it from `<root>`
  once the notes exist); or an unattempted set, or an answers file that solves one, has nothing
  extracted (`no file holds <DOC>, ...; extract it, then rerun`: extract it, `02-extract`; when
  the message says its Key cell is empty or isn't read, so it counts as a set, first fix that
  cell as `templates/MANIFEST.md.tmpl`'s legend says, then extract it). An
  exit 2 checked nothing, wherever the command runs: nothing publishes or commits on it. A hit from
  a shared answers file's own file is a blocker like any other, even when the set it quotes is
  attempted: the notes quote an attempted set's official text only once every set its answers
  file solves is attempted.
  Each hit names a page's line (a notes section or a sheet) and a set's part, never the text. The Review view (`07-cheatsheet`)
  only tags blocks of the notes, so this check covers it, and every later change runs it as
  `08-practice`'s "Changing the notes or a sheet" item 4 says, with this same command.
  A hit is a blocker: rewrite the passage with fresh numbers and a fresh setup (S7), and rerun
  until it prints QUESTIONS OK. A passage cut or held back instead, which the student may want
  back once they attempt the set, goes to `_build/held.md`, one entry per passage: its section,
  the set it overlapped and the original text. A hit from a multi-set answers file's own file
  (labelled with that file's block, `[HWS p.N]`) is held under every set that file solves, each
  named in the entry, since that file's row never records an attempt. It is quarantined (hub
  CLAUDE.md), and `09-tutor` offers it back once that set is attempted, or, for a hit from a
  multi-set answers file's own file, once every set it solves is attempted (its Step 7). A hub
  whose CLAUDE.md lacks the
  quarantine line (a hub made before it existed) gets it now, before the first entry is written:
  the `_build/held.md` bullet of `<skill>/templates/hub-CLAUDE.md.tmpl`'s Repo rules, copied as it
  stands.
- Then rerun `selftest.py` (with a checker) and `linkcheck.py` (plain-text notes: the references
  by hand, `04-write` step 6). Log in STATUS any finding left unapplied, with why, and any claim
  refuted, with the evidence.

## Official solutions that arrive late

Extract them first, as `02-extract` step 1 says (hard rule 6), after `01-ingest` step 3 writes
the answers file's Key cell: an answers file that solves one set shares that set's agent, which
writes the pair again, its extract and `_build/solutions/<name>.md`; one that solves several sets
gets its own agent, which writes, for each set, one solutions file beside each extract that holds
the set's blocks, `_build/solutions/<name>.md` under that extract's name, holding that extract's
part blocks (a deck split over two extracts may need two), and its own pages, in full, in `_build/solutions/<doc id in lower case>.md`, while each set's own
agent writes its extract again in the same wave. Add them to the self-test (and rerun
`extract_check.py --parts` for `PARTS`), diff every answer against the notes and any solved key,
and record the verdict in STATUS by doc, page and part (`HW1S p.2, HW1 Q2a: matched`, `HW1S
p.3, HW1 Q3b: notes changed`): what matched, what was wrong, what changed, never a value, since
STATUS names none (step 1) (FB-107). One that changes the reference or a convention reruns the examples as in step 5.

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
--hub .` prints `QUESTIONS OK` on the notes, or `QUESTIONS OK: no unattempted
set`, logged in STATUS (step 5);
`linkcheck.py` exits
0 (plain-text notes: references checked by hand); the fixes are committed.
