# 08 Practice

Baseline as of 2026-10-20; changes only via `12-retro`.

The mock exams, their quarantined keys, the mock page and the cram order. A mock is a dress
rehearsal: it reads and scores like the real exam, so the student finds what they can't do yet
while there is time to fix it. Each mock is `practice/mock-<slug>.md` (the slug `<exam-slug>` for
one exam-level mock, `<exam-slug>-<n>` for several, `<exam-slug>-harder` for the harder set), in
`_build/MOCK.md`'s format, and its key is `practice/mock-<slug>-key.md` (FB-154). Then, after the
student's attempt, the final sheet (`07-cheatsheet`).

Until the student has attempted a mock, its answers live only in its key, in
`practice/mock-values-key.md` (the key script's output) and in the key script that computes them,
`_build/verify/mock_key.py`. STATUS, `_build/logs/`, commit messages and replies to the student
name a part and what changed, never a value: the scripts print part ids only for the same reason.
A handoff in 08 saves no memory: a memory file loads into every later session, the one the student
watches too.
Through stage 08 a commit or a handoff (hard rule 10) surveys the tree with `git diff --stat` and
`git status` only and commits with a plain `git commit`, never a commit command that prints the
diff; a reconcile agent gets file names only, and its brief says to run no diff and quote no line
of `practice/` or `_build/verify/`: a diff of those files prints values.

## Step 1: Check the inputs

- `06-site` is done: `_build/notes.html` is built and the notes page's URL is in STATUS (steps 4
  to 7 need both). Plain-text notes (`04-write` step 6) skip 06: each leak check below on
  `_build/notes.html` reads `notes/combined.md` instead (build it now from the section files), a
  notes change rebuilds that file instead of a page, the cram order names its sections as text
  (`cram_check.py --plain`), and step 6.4's Playwright is installed as `06-site` step 5 says.
- `05-verify` is done, and `07-cheatsheet` is done or logged as skipped. With 07 done, the mock
  sheet is `cheatsheet/<exam-slug>-mock.pdf` (with the LaTeX engine, the student's PDF of it,
  under that name). With it skipped there is no sheet: leave out every sheet item below (the
  cold solver's sheet, the sheet in the key's STOP line, the cram order's sheet items, the sheet
  at the attempt, step 8.3).
- PLAN.md's Deliverables row for the mock, and its "08 practice" row: how many mocks and the
  question shapes they follow. Its Scope authority line says what the mocks cover (FB-021);
  MANIFEST.md's Scope column holds the cut.
- `_build/MOCK.md` is the hub's copy of `<skill>/templates/MOCK.md` (`00-intake` step 7, item 2),
  and the hub CLAUDE.md's Repo rules hold the practice keys rule of
  `<skill>/templates/hub-CLAUDE.md.tmpl`. A hub made before either existed copies it now. A hub
  whose `_build/chassis.html` predates MathJax's `ui/safe` and the pinned `loader.paths.mathjax`
  takes the template's `window.MathJax` block now (`verify_page.mjs` fails a page without them),
  and its `_build/CONVERT.md` and `_build/CHASSIS.md` are copied again from the skill's templates
  (`assemble.py` enforces the current rules).
- PLAN.md's Checker line: with a checker, `_build/verify/` holds the reference `05-verify` tested.

## Step 2: Plan the set

Write `_build/mock-plan.md`, one row per question of each mock: the mock, the question, its
points, the source it follows (`[PE1 Q3]`, a How it's tested row, or with full coverage a
section and the type it asks), its type and topic.

- Cover every question of the source the exam copies, which the Scope authority line names
  (FB-150): list each of its questions beside the mock question that clones it. When that line
  says full coverage instead (the graded work doesn't mirror the exam, FB-021), every backbone
  section in scope gets a question, and the shapes go beyond the How it's tested table, which only
  holds the practice's: the question types the instructor's exam-format statement names (hub
  CLAUDE.md; when it names none, MOCK.md's type list), asked of what the section teaches that no
  practice part asks (a trace where the practice only defines, a proof where it only computes).
  Weight the sections by that statement when it gives weights, else evenly, and say which in the
  plan.
- Quote each cloned question's text in the plan, its question part only, from its extract. The
  writers read no source file: a homework's extract holds its solutions under each question, and
  a file MANIFEST.md marks `Answers: yes` never reaches them (hub CLAUDE.md).
- Clones are at exam difficulty with fresh numbers, plus one harder set, its own mock, flagged as
  harder than the exam (FB-155), unless PLAN.md's priority order drops it for time.
- True or false: for each statement the source tests, list the adjacent variants (swap the
  property, the pair, the direction, the number) and which mock asks each (FB-151); no statement
  goes in two mocks, and the variants that mocks ask of one statement all sit in one mock, since an
  earlier key's witness would settle a later mock's variant. The plan holds statements only; the
  verdict and witness of every variant go in a key (step 4).
- A justify, prove or classify part has an answer fresh numbers don't change: where several mocks
  clone its question, each mock asks it of another claim (another property, pair or direction),
  so no key answers a later mock's part.
- A rule stated for one question type applies to its siblings before the plan goes out
  (FB-152): a convention a trace question must state, a table or compute question states too.
- The header follows the exam: its minutes, its total points, its rules.
- The order the student takes the mocks: the exam-level ones by slug, the harder set last. The
  cram order follows it (step 7), and the last one's key holds the Variants (step 4.3).

The plan holds no answer: the writers read it.

## Step 3: Write the mocks

1. One writer per mock file, from `<skill>/templates/agent-briefs.md`, section "Mock writer",
   all spawned at once (each writes only its own file).
2. From the hub root, per mock, `python3 -I <skill>/scripts/mockpage.py practice/mock-<slug>.md
   --out _build/mock-<slug>.html`. It refuses any line off the format and names it: fix each,
   and rerun until it writes the page.
3. A part a writer reports it couldn't make fresh gets fresh numbers now (FB-071).
4. The writers can't see each other's mocks: compare the clones of each source question across
   the mocks and with the notes' worked examples, and give any clone with the same instance as
   another (the same numbers, graph or table) fresh numbers, so one mock's key never answers
   another and the notes never work a mock's instance. A justify, prove or classify clone that
   asks another mock's claim gets another claim (step 2).

A question sent back for fresh numbers (step 4) is reworked in place by the main session, its
shape and wording kept; a larger rewrite goes to a new writer whose brief names that question
alone. Either way, steps 3.2 and 3.4 again.

## Step 4: The key

The main session writes every key; no writer sees one. Its output shows answers from here to
step 7.4, so nobody may watch it. First set STATUS's next-step line to `Stage 08 is writing the
mock keys: don't look at the build window. When this line starts "08 step 8, the cram night", go
to it, type /clear, then "start the cram night", before reading anything else.`: `00-intake`
step 8 told the student to watch STATUS for it. This session asks them nothing (hard rule 1).
The student reads STATUS on disk: from here every write to it, a handoff's too, keeps that line
as it stands until step 7.4 changes it, and once item 2 has written the first key file runs step
7.4's STATUS check at once. Then:

1. Copy `<skill>/templates/verify-mock-key.py` to `_build/verify/mock_key.py` and list the mock
   slugs in MOCKS. With a checker, add per instance an assert that it isn't degenerate (a tie the
   question's stated convention doesn't settle, a step that does nothing, an empty result), testing
   a property and naming the part, never a value, and one `value()` per part the reference can
   compute, formatted as the key will write it. A trace or table part (most compute parts too) is a
   run on fresh numbers, which the notes never hold: extend the reference when it can't compute
   one, or send the question back (step 3). An extension is a change to the reference: rerun as
   `05-verify` step 5 says, and before trusting it, test it on a worked example a source solves (a
   lecture's, a solved homework's), added to the self-test, never on the mock's own instance. With
   no source example of that shape, send the question back for one the tested reference covers. An
   answer that is a number, an order or a table is always a `value()` (where the reference lacks
   the step, an extension to it, never plain Python in `mock_key.py`, which the self-test can't
   reach); only an answer no arithmetic on the instance gives (a bound read off a rule, a choice
   the course leaves open) is a `reasoned()` with why, cited from the notes. Without a checker
   (PLAN.md's Checker line), every trace, compute or table part is a `reasoned()` naming the
   source its answer is cited from, and the main session checks each instance for the same
   degenerate cases as it works the answer, sending one back (step 3).
2. `python3 -I _build/verify/mock_key.py` writes every value to `practice/mock-values-key.md`
   and says NO KEY. A failing assert sends that question back for fresh numbers (step 3).
3. Write each key in MOCK.md's key format. Every computed `Answer:` is copied from
   `practice/mock-values-key.md`, never worked by hand (hard rule 3). A reasoned part's answer
   comes from the notes, cited (with no checker, from its cited source, the working shown); a
   true-or-false part's is its verdict with its witness. The key of the mock taken last (the
   harder set, or the one mock) ends with the Variants section: every variant the plan lists that
   no mock asks, with its verdict and witness (FB-151). An earlier key never holds one: the
   student opens it before the later mocks.
4. Run it again: each mock's line says KEY OK, with how many parts it asserted and the rest
   listed as reasoned. It also checks that the key's parts are the mock's, with or without a
   checker.
5. `python3 -I <skill>/scripts/mock_leak.py <page> practice/*-key.md` on the notes
   (`_build/notes.html`) and on the mock sheet (`cheatsheet/<exam-slug>-mock.html`, or its
   `.tex`): the student reads both before the mocks. A hit on a part whose answer comes from the
   instance's numbers (a number, an order, a table) means the page works the mock's instance:
   give the question fresh numbers (the rerun clause below). Any other hit is the page teaching
   what the part asks (a rule, a classification, a verdict and its witness), as a sheet may in
   the real exam, and the phrase "answer key" is the notes naming the course's keys (S32): log
   each in STATUS by its part. An answer under 8 characters isn't searched (the last line names
   it): step 3.4's comparison of instances is what keeps it off the pages. Each key but the last
   one's is a page too, opened before the later mocks: `mock_leak.py --no-markers
   practice/mock-<slug>-key.md` with the keys of the mocks taken after it (step 2's order) prints
   LEAK OK, or its working answers a later part: reword the working, or give that part fresh
   numbers or another claim (step 3).

Without a checker, the cold solver's agreement settles each cited answer (step 5).

Any later change to a question's numbers or wording updates its instance in `mock_key.py` first;
then rerun this step from item 2, rewrite its answer from the new values, give the changed
question to the cold solver again (step 5), and rerun step 6 from item 1 and, once the cram order
exists, step 7's items 1 and 2. A change to a key alone reruns items 4 and 5, step 6 and step 7's
item 2. A change to the reference at any later point (a `05-verify` step 5 rerun) reruns items 2
and 4: a part whose value changed fails item 4, and its answer is rewritten from the new values.
In step 8, for a mock not yet taken, log the part instead, and that mock's cram order line says to
bring it to the session before marking it (then step 7's items 1 and 2); after the attempt,
rewrite the answer from that mock's section of the values file printed alone
(`sed -n '/^## <slug>$/,/^## /p' practice/mock-values-key.md`), never the whole file.

## Step 5: The cold solver

Run `05-verify`, section "The mock": one reviewer per mock, from the "Cold solver" brief, with
the mock, the notes and the mock sheet only (FB-103). Settle each answer where it and the key
disagree with the checker (a new `value()` when it is computable) or the source, and fix the
question (a convention it didn't state) or the key. A part it says the notes can't answer is
outside what the student studied: reword or drop it (a dropped true-or-false part's statement
joins the Variants, step 4.3), or, when the exam does test it, fix the notes as "Changing the
notes or a sheet" says: this session holds the key, so the obvious fix states the answer. Log
each in STATUS by its part and what changed, never a value.

## Step 6: The page

From the hub root, per mock:

1. `python3 -I <skill>/scripts/mockpage.py practice/mock-<slug>.md --out
   _build/mock-<slug>.html`: the header, then every part in three views, by paper, by question
   type and by topic (FB-153).
2. `python3 -I <skill>/scripts/mock_leak.py _build/mock-<slug>.html practice/*-key.md` prints
   LEAK OK: every key, since all the pages publish before any attempt. A hit names the key and
   the part: reword the question, or a reasoned part's answer in its key when it only restates
   the question. A computed part's answer is also in `practice/mock-values-key.md`, so a hit on
   it means the question shows its own answer: reword the question or give it fresh numbers
   (step 4's rerun clause).
3. `python3 -I <skill>/scripts/linkcheck.py --html _build/mock-<slug>.html`.
4. `node <skill>/scripts/verify_page.mjs _build/mock-<slug>.html _build/shots/mock-<slug>
   --views`, with the `allowed_domains` of `06-site` step 5. Each view must show its own parts,
   the same set in each, at both widths and in both themes. Look at the screenshots yourself.
5. Publish the page privately as `06-site` step 6 says, and put its URL in STATUS. A key is
   never published.

## Step 7: The cram order

The night before, the student gets a reading list into the verified notes, never new text
(FB-157). Fill `<skill>/templates/cram-order.md.tmpl` into `practice/cram-order.md`:

- Rank the notes' sections by points per minute: the points `_build/mock-plan.md` gives the
  questions a section prepares (a clone's go to the subsection its source's How it's tested row
  names; with full coverage, a question's split evenly over its section's subsections), over the
  minutes it takes to read. Group them into tiers with minute budgets, each row naming the one
  thing to take from it, in the notes' own words.
- Each row links `<notes URL>#<id>`, the published notes page from STATUS (plain-text notes: it
  names `§x.y Title` as text).
- A mock the student hasn't taken yet gets its line after the tier that prepares it, the harder
  set last. The line says to bring the misses back: the session moves the sections they point at
  to just after the line (step 8.4) and, with a sheet, builds the final sheet while the student
  reads on.
- The skip list names each section the exam doesn't reach and why; the Out of time line links
  the Must-know lists (plain-text notes: names them).
- `## Tonight`: when `07-cheatsheet` found the sheet is collected with a name, its first item
  tells the student to write their name on before handing it in (FB-132). Then the exam's date,
  time and length and what its rules let the student bring (hub CLAUDE.md). With a sheet, the
  last item is printing and packing the final sheet (`cheatsheet/<exam-slug>-final.pdf`; the mock
  sheet when no mock was taken).

Then:

1. `python3 -I <skill>/scripts/cram_check.py` (`--plain` with plain-text notes): the intro's
   total and tier count match the tiers, each tier's minutes equal its rows' sum, and every link's
   id is in `_build/notes.html`.
2. `python3 -I <skill>/scripts/mock_leak.py practice/cram-order.md practice/*-key.md` prints LEAK
   OK: the student reads the cram order before the mocks, so a row that states a mock's answer
   is reworded.
3. A fresh reviewer audits it from the Review brief's "Audit" variant (`05-verify` step 4,
   FB-105): every row's one thing against the section it links. A finding on a row is fixed in
   the cram order; one on the notes goes through "Changing the notes or a sheet". Then 1 and 2
   again.
4. The cram order isn't published. Hand off and commit (Done when's list, up to here) as this
   stage's opening says, the next-step line kept as step 4 set it. The student acts on the new
   line, so it comes last, after the handoff's own STATUS edits and just before its commit: set
   the next-step line to `08 step 8, the cram night`, with the cram order's path; run
   `mock_leak.py STATUS.md practice/*-key.md` until it prints LEAK OK (a mention of the course's
   answer keys is reworded, since the phrase is a key's marker); commit. The last reply is one
   line, nothing above it worth reading: `Stage 08 is built: type /clear, then "start the cram
   night".`

## Step 8: The cram night

The student types `/clear` when step 7.4's last line asks, before reading anything else on that
screen, so nothing on it shows a key they haven't reached; this fresh session reads STATUS,
commits what step 7.4 left uncommitted (an early `/clear` can cut its commit short; `git status`
and `git diff --stat` only), and gives them the cram order's path. The next-step line stays `08
step 8, the cram night` while a mock is untaken, and STATUS's check (step 4's opening) uses the
untaken mocks' keys only, none once all are taken: a miss logged after an attempt may state that
mock's answer. From here the student is present: a question they ask is study Q&A, answered
first, and an edit it prompts goes to a dispatched writer (hard rule 9); steps 8.3 and 8.4 are
this stage's build, which the main session runs. While a mock is untaken, every notes or sheet
change runs "Changing the notes or a sheet" with the untaken mocks' keys, and a one-line sheet
addition (FB-166) goes into the final sheet, or before the first attempt is logged in STATUS as a
final-sheet item with no mock, for step 8.3. This session opens only the taken mock's key, never
an untaken one, `practice/mock-values-key.md` or `_build/verify/mock_key.py` (they hold every
mock's answers; the one exception is step 4's rerun clause, which prints a taken mock's section
of the values file alone), and keeps every search inside `notes/`, `cheatsheet/` and
`_build/frag/`: one over the hub root prints key lines. A writer it dispatches makes that
section's item 2 alone (the Write brief's shape, the change as its purpose), fenced as the Mock
writer brief is: no file under `practice/`, not `_build/verify/mock_key.py` (its numbers come
from `_build/verify/examples.out.md`, which holds no mock instance: step 3.4), and no search
over the hub root. The main session runs the other items.

1. Before an attempt, a mock sheet STATUS logs as changed is shown to the student, changes and
   all (FB-137), and printed again; with the LaTeX engine, the student compiles it first and this
   session checks the PDF as `07-cheatsheet` checks a LaTeX sheet (`check_pdf.py --no-layout`).
   The student takes each mock under exam conditions, its minutes and the mock sheet only, in the
   cram order's order (the harder set last, since its key holds the Variants), then opens its
   key, or brings it here first when its cram order line says so (step 4's rerun clause).
2. Record their misses in STATUS: the part, and why it went wrong.
3. Run `07-cheatsheet`, section "The final sheet", with the misses, and the cold solver's
   conventions and final-sheet items STATUS logs for the taken mocks or for no mock: an item
   logged against an untaken mock waits for its attempt. A later mock's misses and items add to
   the final sheet already built. While a mock is untaken, the final sheet's first build and
   every change to it run as "Changing the notes or a sheet" says, with the untaken mocks' keys
   (before the first build, its baseline has no hits).
4. In the cram order, delete the taken mock's line and move a section the misses point at to the
   first reading rows after it, before the next mock's line (renumbered, its tier's minutes and
   the intro's total adjusted), since the student has read the rows above it. With no reading row
   there (the next line is another mock's, or the list ends), they go in a new tier in that place,
   `## Tier <n>: Misses (<M> min)`, the tiers after it renumbered and the intro's tier count up by
   one. Then step 7's item 1 again, and while a mock is untaken item 2 with the untaken mocks'
   keys.
5. Commit and hand off as this stage's opening says.

## Changing the notes or a sheet

Until the last mock is taken, the notes and the sheets are pages the student reads before an
attempt. Every change to them (step 5, the cram order audit in step 7, the final sheet and a fix
or a question on the cram night) runs this, with the keys of the mocks not yet taken (before any
attempt, `practice/*-key.md`):

1. The baseline: step 4.5's command, run now, on the notes (plain-text notes:
   `notes/combined.md`) and on each sheet the student reads before that attempt. Keep the hit
   lines.
2. Make the change as `05-verify` step 5 says (every copy of the fact), teaching a method in
   general or with an example of its own, never a mock's instance. A new number or trace comes
   from the checker (`examples.py`, `05-verify` step 2), never by hand. A wrong fact on a sheet
   is corrected on both sheets; a line the mock prompted goes into the final sheet only
   (FB-133), logged in STATUS as a final-sheet item, with the mock that prompted it (or none),
   for step 8.3. FB-137 wants the student to see a draft before a printed sheet changes: before
   step 8, while they look away, log the change, and step 8.1 shows it before the reprint; in
   step 8, show the draft once item 4 passes, before item 5.
3. Rebuild what changed: the section's fragment (`06-site` step 3) and `06-site` step 5
   (plain-text notes: `notes/combined.md` from the section files); an HTML sheet, `07-cheatsheet`
   step 4. A LaTeX sheet is checked as its `.tex` in item 4; the student compiles it before the
   next attempt (step 8.1).
4. Run item 1 again and compare the hit lines with the baseline's (count them, since every hit
   on the notes reads "(the page)" and a second copy of an answer adds one). A new hit on a
   number, order or table answer is a leak: reword the change and repeat from item 2. Judge and
   log any other new hit as step 4.5 does.
5. Republish what is published (`06-site` step 6; the mock sheet as `07-cheatsheet` publishes it).
   The student may have printed the mock sheet at `07-cheatsheet`: a changed one is logged in
   STATUS, and the cram order's next mock line says to print it again, or with the LaTeX engine
   to compile it and bring the PDF to the session first (step 7 writes it so when the cram order
   comes later). Then rerun step 7's items 1 and 2 once the cram order exists.

Log each change in STATUS by its part and what changed, never a value.

## Done when

Each mock's instances are compared across the mocks and with the notes' worked examples (step
3.4); each mock's `mock_key.py` line says KEY OK (with no checker, every key value cited too); the
cold solver's disagreements are settled and logged, and a changed notes page or mock sheet is
republished; `mockpage.py`, `mock_leak.py`, `linkcheck.py --html` and `verify_page.mjs --views`
pass, and you looked at the screenshots; the page is published privately and its URL is in
STATUS; `cram_check.py` prints CRAM OK; `mock_leak.py` prints LEAK OK on the cram order and
STATUS, and on the notes and the mock sheet every hit is judged and logged (step 4.5); each key
but the last one's prints LEAK OK with `--no-markers` against the keys taken after it; the
audit's findings are applied; the mocks, keys, `practice/mock-values-key.md`,
`_build/mock-plan.md`, `_build/verify/mock_key.py`, the mock pages and the cram order are
committed, handed off, STATUS's next-step line starts `08 step 8, the cram night`, and step
7.4's last line asks for `/clear`. Then, on the cram night: STATUS LEAK OK against the untaken
mocks' keys after each write; before each attempt the changed mock sheet shown and reprinted (with
LaTeX, its PDF checked first); after it, the misses in STATUS, the final sheet (changed as
"Changing the notes or a sheet" says while a mock is untaken), the cram order updated with CRAM OK
(and LEAK OK while a mock is untaken), and a commit and handoff.
