# 11 Next exam

Baseline as of 2026-10-20; changes only via `12-retro`.

The next exam of a course whose hub this skill built. The hub is reused, never forked: the
finished exam's mocks, keys and sheets are archived, the hub's copies of the skill's templates are
replaced by the current ones (hard rule 12), MANIFEST.md is rewritten for the new exam, and a
build extends the one notes page with the new exam's sections. Like intake, it asks everything up
front, in the session the student is in, then launches the build in a session of its own.

A hub this skill didn't build (no `MANIFEST.md` at `<root>`, or a `CLAUDE.md` without the line "An
exam-prep hub") is out of reach: it needs a one-time migration to the skill's layout first, which
this stage doesn't do. Say what it lacks, and stop.

A new source for the exam being prepared, rather than a new exam, is "A source added to this exam"
below; a skip asked for its extract, backbone or reviews, "A source added unverified".

## Step 1: Check the inputs

A reopen already under way (step 2, "A resume") goes straight to its log.

- `<root>` holds the skill's layout (above) and `PLAN.md` reads `Approved: <date>` for the
  finished exam.
- No other session works in the hub (ask the student): this stage moves files a tutor tab or a
  build reads.
- STATUS has no `Build running` line. With one, ask the student whether a build or a pass is still
  under way: beside a `Polish: <pass>, started` line, `10-polish`'s "A pass that stops" first;
  beside a `Source added: <doc>, started` line, this stage's "A source added to this exam", "A
  stop", first; beside an `Unverified add: <doc>, started` line, "A source added unverified", "A
  stop", first; otherwise, on their word that it won't resume, remove the line (hard rule 1) and log
  it.
- The tree is clean. Survey it with `git status` and `git diff --stat` only, as `08-practice`'s
  opening says (`practice/tutor/` holds values of parts the student may not have attempted). A
  change left uncommitted belongs to the session that made it, and may be unchecked: tell the
  student, and wait until it is committed or put back.
- `_build/logs/tutor.md` has no open patch and nothing under `## Pending patches`: dispatch each
  line (`09-tutor` step 1's Patches bullet) or strike it through on the student's word. Lines
  under `## Waiting checks` carry over.
- The finished exam is over: its date in CLAUDE.md has passed, or the student says it is done.
  Before then, a request for the next exam waits, and the cram night (`08-practice` step 8) goes
  on.
- Known errors in the finished exam's notes (a list the student brings, a review's open items)
  are fixed first, as a `10-polish` `edit` pass: the new sections would copy them (FB-106). Then
  come back here.

## Step 2: Tag the hub and open the log

**A resume.** A reopen is under way when STATUS's next-step line starts `11 step` (set below, and
again at step 5.3, each naming the log), or when PLAN.md reads `Approved: not yet` and its Decisions
open with a `Reopened from ... (tag exam/<old-slug>)` line, whose tag gives the log's name. An
approved PLAN.md with that line, while the next-step line doesn't start `11 step`, is a finished
reopen (the exam before it), never one under way. Read the log, and go on at the first step it
doesn't show done. Never work the old slug out again: step 4 rewrites PLAN.md and step 5.3 takes out
STATUS's lines, so the rule below would then give the new exam's.

**A first run.** The finished exam's slug is the one in STATUS's `Stage 08 built: <exam-slug>`
line, else in PLAN.md's Deliverables row 4, else the exam's name in lower case without spaces
(`midterm1`). A tag `exam/<old-slug>` that exists already is this reopen's own when it points at
HEAD and no log exists yet (a stop between the tag and the log's commit): keep it. Otherwise the
slug was used twice: ask the student for another. Tag the hub, `git tag exam/<old-slug>`: the tag
keeps the finished exam's PLAN, MANIFEST, STATUS, CLAUDE.md and page source as they were.

Start the log, `_build/logs/reopen-<old-slug>.md`: the student's ask in their words, the tag, and
`git rev-parse HEAD`. It marks each step's end as it finishes (`step 3 done`), and each of step
5's items, so a resume knows where this stopped. Set STATUS's next-step line to `11 step 2,
reopening for <exam>: the log says where it stopped (_build/logs/reopen-<old-slug>.md)`, in place
of the finished exam's (the cram night's is over), so a fresh session lands here (SKILL.md's
routing). Commit both.

## Step 3: Read, then ask once

Read what is on disk first, as `00-intake` step 2 does: the hub's STATUS and CLAUDE.md, new
sources the student names or stages (by name, never a downloads glob, FB-042), the exam-details
file, the Ed pull run again (`workflows/01-ingest.md`, "Ed Discussion": its cursor makes it an
update), and the profile. Then MANIFEST.md's rows: each `reserved: <this exam>` row is this exam's
(FB-023), and every other row may or may not be: the finished exam's, and a row that went `out`
at an earlier reopen (a final may cover all of them).

Ask in one round, as `00-intake` step 3 says (at most two question dialogs; a pre-filled answer
shown with its quote, date and source; options in the message, hard rule 11), only its per-exam
questions, each only when the reading left it open:

1. Scope authority, for this exam (`00-intake` question 1).
2. Which files belong to this exam (question 2), the proposed split covering the `reserved` rows
   for this exam, any new files, rows still reserved for a later exam, and every row that is
   `out` or was `in` for the finished exam: on this exam, or not. That answer makes the exam
   cumulative or not, row by row. For a row this exam covers only in part, ask for its first and
   its last in-scope slide, each as the PDF page or the printed slide number (FB-024: a deck split
   across exams starts partway). Ask too which answer sets the student has attempted since (their
   Answers cells become `yes, attempted`).
3. Missing sources (question 3).
4. This exam's rules (question 4): date, time, length, sheet, calculator, book, question types.

Question 5 is the profile's, never asked again. The plan shows these defaults, each marked
"(default)", beside `00-intake` step 3's own:

- One notes page, extended: the new exam's sections follow on in the same notes and page, same
  URL, its version bumped; the new exam gets its own map, sheets, mocks and cram order.
- Old material this exam doesn't cover stays, under a `Not on <exam>` banner (FB-121): a whole
  section's at its top, part of one at that part.
- Old sections aren't rewritten to rules the skill added since they were written; a `10-polish`
  pass does that on request.

Tell the student, with the questions: a mock of the finished exam they never took is archived as
it is (step 5). Its page stays published and they may still take it, but they mark it themselves,
against its key at `practice/<old-slug>/mock-<slug>-key.md`: no session opens an archived key, so
none grades it or walks them through it, and its archived cram order line still names the key's
old path.

## Step 4: Draft the hub files

Draft all three in `<root>`, as `00-intake` step 4 does, before showing anything:

- **`MANIFEST.md`**, from `<skill>/templates/MANIFEST.md.tmpl`, the rows carried: its title names
  this exam; each row for this exam in an `in` form; new files as new rows with new doc ids (none
  renumbered or reused: citations use them); the finished exam's rows `in` when this exam covers
  them, else `out` with "(on <old exam>)" in Notes; Answers cells carried, each set the student
  has attempted since marked `yes, attempted` (question 2); topic cuts for this exam only. A
  cumulative exam needs no other scope word: its old rows are `in`.
- **`CLAUDE.md`**: its Exam facts become this exam's, from
  `<skill>/templates/hub-CLAUDE.md.tmpl`, with a line `Earlier exams:` naming each earlier exam,
  its date and its tag (the finished one added to any list already there); its Repo rules become
  the template's current ones, word for word. Of the course's schedule,
  only this exam's date, time and length are copied: homework due dates and the lecture calendar
  are pointed to at their home, never copied (FB-181).
- **`PLAN.md`**, from `<skill>/templates/PLAN.md.tmpl`, reading `Approved: not yet`, with this
  exam's slug (`exam2`, never the finished exam's) and, first in its Decisions, the line
  `- Reopened from <old exam> (tag exam/<old-slug>): every stage also follows 11-next-exam's "The
  build on a reopened hub" (the student)`. That line routes a draft here and tells a resumed build
  what differs.

Then `00-intake` steps 5 and 6: audit the plan, show it with the scope rows and the exam facts,
and refine it. Show also what step 5 will do: the files it archives and the template copies it
replaces; and what the build will banner `Not on <exam>`: the old sections and subsections whose
sources now all lie outside this exam's scope (by number and title, from the coverage matrix: see
"The build on a reopened hub" row 03).

## Step 5: On approval

In this order, each item logged as it lands:

1. **Archive the finished exam.** List `practice/`, `cheatsheet/` and `_build/` (a glob that matches
   nothing stops zsh), then `git mv` each of the finished exam's products by name, names kept, into
   `practice/<old-slug>/`: every `practice/mock-*.md` (the keys and `mock-values-key.md` among
   them), `practice/cram-order.md`, `_build/verify/mock_key.py`, `_build/mock-plan.md` and each
   `_build/mock-<slug>.html`; and into `cheatsheet/<old-slug>/`: every file of its sheets (`.html`,
   `.pdf`, `.tex`, `.layout.json`) and `_build/sheet-outline.md`. Move STATUS's attempt, miss and
   final-sheet lines into `practice/<old-slug>/attempts.md`. Then the listing shows none of them at
   the top level (`practice/tutor/` and `_build/verify/set_key.py` stay: they are the course's
   homework). Why: every rule that finds the current exam's mocks, keys and sheets reads a top-level
   name (`practice/*-key.md`, `practice/mock-<slug>.md`, `cheatsheet/<exam-slug>-mock.pdf`), and
   once STATUS's lines reset, a mock left there would read as untaken. The archive is frozen:
   nothing edits it, and no session or agent opens a key, the values file, `mock_key.py` or the mock
   plan in it, or searches `practice/<old-slug>/` (the hub CLAUDE.md's Repo rules say so). In
   `_build/logs/tutor.md`, a walk-through or quiz section on one of the finished exam's mocks that
   is still open (its last line `Next: <part>`) gets the line `Closed: archived with
   exam/<old-slug>`, so no tutor session resumes it against a key it may not open.
2. **Reconcile the templates.** First, in the log, put each hub copy's `Baseline as of` date
   beside the skill's (`grep -m1 'Baseline as of'` on both; no line: older than any), before
   anything overwrites the copies, and for a copy that is behind, the entries of
   `<skill>/references/CHANGELOG.md` since its date (what changed, by id). Then for each of
   `STYLE.md`, `CHASSIS.md`, `CONVERT.md` and `MOCK.md`: `diff -uN _build/<file>
   <skill>/templates/<file> >> _build/logs/reopen-<old-slug>.diff` (`-N`: a hub made before a
   template existed has no copy of it, and the copy comes in whole), then, as a command of its
   own, `cat <skill>/templates/<file> > _build/<file>` (hard rule 12): `diff` exits 1 when the
   files differ, the usual case, so a `&&` after it would skip the copy. Then `cmp` each copy
   with its template. Then the chassis: its diff the same way, then `cat
   <skill>/templates/notes-chassis.html > _build/chassis.html`, its placeholders filled for this
   exam as `06-site` step 1 says. Add any of `00-intake` step 1's `.gitignore` lines the hub lacks.
   Then list in the log the STYLE rules the diff adds (their `S` numbers): the old sections may
   miss them, and the report offers a `10-polish` pass. The diff is for `12-retro`, which tells the
   skill's own changes from a hub-local edit; hubs never keep their own copy.
3. **Reset STATUS.** Take out every line about the finished exam's build, mocks, sheets and cram
   night: `Stage 08 built`, `Reopened build:`, `Tutor:`, `Polish:`, `Source added:`, `Skip asked:`,
   the final-sheet items, a mock sheet logged as changed or to print again, a part logged for a
   recheck (item 1 moved the attempts). An `Unverified:` line stays: its material is still unchecked
   ("A source added unverified"). Keep the notes page's URL line (same URL from here on), and add
   the finished exam's sheet and mock page URLs to the `Earlier exams:` line (start it when there is
   none), as `<old exam>: <name> <URL>, ... (tag exam/<old-slug>)`. Set the next-step line to `11
   step 6, launch the build for <exam> (_build/logs/reopen-<old-slug>.md)`.
4. **The approval line, last**, as `00-intake` step 7 item 3 says. Commit, staging the archive's
   moves and the files changed by name.

## Step 6: Launch the build

First the report, in the message: the tag, what was archived, the reconcile diff's path and the
STYLE rules the old sections may miss (a `10-polish` pass on request), the earlier exam's URLs,
and the old sections that will carry a banner. The notes page keeps its URL, so its republish
replaces the finished exam's version; that version stays in the tag (`git show
exam/<old-slug>:_build/notes.html`). Tell the student what `00-intake` step 8 tells them (don't
watch the build from stage 08 on; the cram night's `/clear`).

Then log `step 6 done`, set STATUS's next-step line to stage 01 of this exam, hand off and commit
(hard rule 10). Launching is the last act, as in `00-intake` step 8, so this session writes
nothing once the build runs: its prompt with one sentence added after the first, "This hub was
reopened from [old exam]: read the exam-prep skill's `workflows/11-next-exam.md`, section "The
build on a reopened hub", before stage 01, and follow it at every stage." A stop between that
commit and the launch leaves an approved plan for this exam with no build running: SKILL.md's
routing then starts the build at its first unfinished stage, and the plan's `Reopened from` line
sends it to that section.

## The build on a reopened hub

The build runs every stage as its workflow says, with these changes. Old sections, old extracts
and old checker code stay; what this exam adds goes after them.

**Which stage is next.** The finished exam's outputs are still on disk (its backbone, its page,
the notes URL in STATUS), so they can't tell a resumed build which stage is done for this exam.
The build keeps one STATUS line, `Reopened build: <exam-slug>, done through <stage> (<date>)`,
written at the end of the first row below and of each stage, and a resume (the launch prompt's
"first unfinished stage" included) starts at the row after the one it names; with no such line,
at the first row.

**Plain-text notes** (`04-write` step 6): where a row runs `linkcheck.py` or rebuilds the page,
check the references by hand and rebuild `notes/combined.md` from the section files instead.

| Stage | On a reopened hub |
|---|---|
| Before 01 | Rebuild the page as it stands with the reconciled chassis and copies (`06-site` steps 3 and 5): a fragment, a check or a screenshot that fails is fixed at its source, as `06-site` says, and committed. |
| 01 | Only the rows this exam added or changed: copy, render (a row whose range grew renders its new pages, `render_pdf.sh <file> <doc> <first> <last>`). |
| 02 | Extract only what has no block yet; `extract_check.py` runs over the whole MANIFEST (its warnings on an `out` row's blocks are expected). |
| 03 | Extend `_build/backbone.md`. Its title names this exam. The Conventions keep the old lines and add this exam's; the old cut lines go, and each part of the old notes this exam doesn't cover gets a cut line as a topic cut does (`03-backbone` step 1): each subsection whose sources in the coverage matrix all lie outside this exam's scope (an `out` row; pages or slides outside an `in` row's range for this exam, as when a deck is split across exams; or this exam's topic cuts), a whole section as `§N (all)`, each with why (MANIFEST's row or range, or the cut's source). New material goes in new sections after the last (`sec-<N+1>`, `notes/<NN+1>-<slug>.md`); a short addition to an old section is a new subsection placed just before its Must know, whose number moves up by one and whose id stays. Nothing else is renumbered, and no id or file is reused (the cram order, the map and Must-know lines link them). New coverage-matrix and How it's tested rows; `coverage_check.py` over everything. |
| 04 | Writers for the new sections only, each brief carrying the `## Patterns` lines of `_build/logs/tutor.md` (where this student stalled before). The main session writes a new subsection in an old section itself, in the Write brief's Format, adds its Must-know line, and updates any text that names the moved Must know by number. It banners what each cut line names, `> **Not on <exam>:** <why, cited>`, at the top of a whole section or at the subsection, and judges each old `Not on <old exam>` banner: material this exam covers loses it, material still out gets this exam's name, and one inside a section-level banner goes. In a section cut only in part, its Must-know lines follow `10-polish` step 3's rule for a cut: a line that names only cut material goes, one that names cut and kept material is reworded to the kept part (a section cut whole keeps its list, under its banner). `linkcheck.py` over everything. |
| 05 | The checker grows: this exam's examples added, the self-test extended to its sets' official parts, every old assertion kept. Reviewers read the new sections and subsections and any old text that changed beyond a banner. |
| 06 | The exam-day map is rewritten from this exam's How it's tested rows (a shape on cut material stays out, as `06-site` step 4 says). The whole page is rebuilt and checked, then republished to the notes URL STATUS holds (`06-site` step 6, its live read first), its version bumped. |
| 07 | This exam's sheets, `cheatsheet/<exam-slug>-mock.html` and on, from the template, never from the archived ones. When this exam covers an earlier exam's material, `diff` each archive's mock and final sheets (`cheatsheet/<slug>/`, every earlier exam's): the lines a final sheet added are the student's earlier misses, and each in this exam's scope is a candidate at step 2's picking. |
| 08 | A fresh `_build/mock-plan.md`, `_build/verify/mock_key.py` from the template, mocks under this exam's slug, and a fresh cram order whose skip list names the old material the cut lines name, and whose Out of time line leaves out the sections cut whole. When this exam covers an earlier exam's material, step 3.4 also compares each clone with every archived mock (`practice/<slug>/mock-<slug>.md`, listed and read by path, never a key), so a new mock doesn't reuse an instance the student has already seen answered. |
| 09, 10 | As written. The tutor log goes on, its old sections kept. |

## A source added to this exam

A source the approved plan doesn't name, such as a widening `10-polish` can't make because its
material was never extracted, or a file a staff post adds after the build; and a `pending` row's
file that arrives after the build (one that arrives during it is the build's, `01-ingest` step 5).
Not official solutions to a set MANIFEST.md already lists: `09-tutor` step 6 takes those. While a
build runs, a new source waits for its end: the student brings it again then.

It runs as a build stage run alone, the way `07` or `08` run on request (hard rule 1), in the
session the student is in: before `Stage 08 built`, a session of its own; from then on, the cram
night's, between attempts (`08-practice` step 8.1 starts no attempt while `Build running` stands).
Each stage it calls runs as its workflow says, its commits, STATUS lines and checks included.
However it ends (closed, stopped, the report declined, the fence check failed), its last act is
`10-polish` step 7.5's patches and checks. Every commit and handoff in it, a stage's included,
surveys the tree with `git status` and `git diff --stat` only, commits with a plain `git commit` and
saves no memory, as `10-polish` step 1 says (`08-practice`'s opening gives why). STATUS's next-step
line stays as it read at step 1 through every write (a stage's handoff edits other lines), and never
starts `11 step`. The fence stays until step 3's failed check, "A stop" or step 5 takes it out: a
stage that stops at its step 1 inside this build leaves both lines, since hard rule 1's end of a
build is this build's end, not a stage's.

1. **Check.** As `10-polish` step 1 says: `05-verify` done (and `06-site` with a page), no `Build
   running` line, the hub free, and whether a mock is untaken. While one is, `08-practice` step 8's
   fence binds this session and every agent it spawns: searches only in `notes/`, `cheatsheet/`,
   `_build/frag/` and `_build/extract/`, nothing opened under `practice/` but the cram order (and 08
   step 8's one exception, its step 4's rerun clause), never `_build/verify/mock_key.py` or
   `_build/mock-plan.md`; each brief it spawns keeps its own scope and adds: nothing opened under
   `practice/`, no `_build/verify/mock_key.py` or `_build/mock-plan.md`, and no search over the hub
   root; each write to the log or STATUS is followed by `mock_leak.py <file> <the untaken mocks'
   keys>` until it prints LEAK OK, as `10-polish` step 1 says. The tree is clean but for
   `_build/logs/` and `practice/tutor/` (a tutor tab's), surveyed as this stage's step 1 says: a
   stop would put back any other change as this build's. Quote the source for the change:
   staff-authored (hard rule 7), or for a `pending` row its MANIFEST.md row and the intake decision
   in PLAN.md that set it.
2. **Report.** Start the log, `_build/logs/source-<doc>-<date>.md` (a second run that day adds
   `-2`, then `-3`, before `.md`, and that name is the run's everywhere, its STATUS line and its
   baseline file included): the ask and the source. The report: the MANIFEST.md row, where the new
   material is planned to go (new sections, or a short addition to an old section, as "The build
   on a reopened hub" row 03 says), judged from the file's name, size and source (a `reserved` file
   stays unopened until its row changes), and each product the widening touches. Show it in the
   message (hard rule 11); log the student's answer and commit.
3. **Fence.** Check step 1's hub and tree again, then write `before <sha>` (`git rev-parse HEAD`) in
   the log. While a mock is untaken, take the baseline now, before anything changes: `08-practice`'s
   "Changing the notes or a sheet" item 1 (the notes page and each sheet), and the same command on
   each `notes/*.md` file, which a tutor tab reads from HEAD and which 04 and 05 change before the
   page can be rebuilt; each page's hit lines (part ids only, which the student may read), under a
   line naming the page, go in the log's name with `.baseline.txt` for `.md`, and `baseline taken`
   in the log. Add `Build running: <date>` and `Source added: <doc>, started <date>, before <sha>
   (<the log>)` to STATUS and commit it all. Then check that the fence commit's parent is `<sha>`
   (`git rev-parse <it>~1`, where it is `git log -1 --format=%H -- STATUS.md`, since a tutor tab may
   have committed its log since) and the hub is still free, and log `fence checked`: otherwise
   another tab wrote in between, so take both lines out, commit, and stop; the student asks again.
4. **Build**, for that source only. While a mock is untaken, the student looks away from this window
   from here to step 5's look-back: tell them first to come back when a reply's only line asks for
   `/clear`, and to type it before reading anything above that line. The MANIFEST.md change first,
   then `01-ingest` steps 1 to 3, `02-extract`, then `03-backbone` and `04-write` placing and
   writing the new material as rows 03 and 04 of "The build on a reopened hub" do: new sections
   after the last, or a subsection before an old section's Must know, with their ids,
   coverage-matrix and How it's tested rows. Nothing else of those rows applies: the backbone's
   title stays, its Conventions keep their lines and add any the new material needs (`03-backbone`
   step 4), cut lines and banners change only where the material takes cut material back
   (`10-polish` step 3's widening), and no `Reopened build:` line is written, since the log tracks
   this build. A placement that differs from the report's is logged, for step 5's report. Then
   `05-verify` on the new material, then the products as `10-polish` step 3's widening says, each
   the hub has: the page (`06-site` step 1's chassis exam line refilled from MANIFEST.md and its
   `.lede` reworded when it names the scope, as `10-polish` step 3 does; step 2's step-throughs,
   made for a figure 03 shortlisted and rerun when 03 or 05 changed the checker; steps 3 and 5; and
   step 4's exam-day map when 03 added How it's tested rows), or with plain-text notes
   `notes/combined.md` rebuilt and the references checked by hand (`04-write` step 6); each sheet as
   `10-polish` step 5.4 changes one (an HTML sheet through `07-cheatsheet`'s "After shipping", the
   audit limited to the change, then its step 4, its republish left to step 5; a LaTeX sheet in its
   `.tex`, which the student compiles); the cram order taking the material as a row in its last
   tier, then `08-practice` step 7's items 1 to 3 (the audit for the new row), item 2 with the
   untaken mocks' keys while one is; an untaken mock isn't edited. The log marks each stage's end
   once its commit is made (`02 done`), each product's (`page done`, `sheets done`, `cram order
   done`), and `step 4 done` after the last. With no mock untaken, a sheet's change is shown to the
   student before it is made (FB-137). While one is, every change to the notes or a sheet runs
   `08-practice`'s "Changing the notes or a sheet" with the untaken mocks' keys, its item 4
   comparing with step 3's baseline file, never with a new baseline taken from notes that may
   already hold a change: for 04's and 05's commits, on each `notes/*.md` file they change or add (a
   new file has no baseline line, so each of its hits is new), since the page can't be rebuilt
   before 05 is done (`assemble.py` refuses a `TODO-VERIFY`) and 08's item 3 waits for the products;
   for the products, on the page and the sheets. A text reworded after a leak hit is logged `changed
   (how)`. A sheet's draft waits for step 5's look-back, and a commit that holds the notes or a
   sheet waits until its compare passes (as 08's own build does): a tutor tab reads them as
   committed, so it never sees a change before its check.
5. **Close**, each item logged as it lands. First, while a mock was untaken, the look-back, on a
   clean screen: the window's scrollback holds edits the compare caught, so log `clear asked`, hand
   off and commit, and end the reply with one line, `The change is checked: type /clear, then "go on
   with the source added".`, as `08-practice` step 7.4 does; the fresh session finds this step as "A
   stop" says, and any session that starts fresh at this step skips the clear. Then the student
   looks back; show them each sheet's change (FB-137) and each text logged `changed (how)`. A change
   they reject is reworded by them and made as step 4 makes one, logged `redo <what>`: they look
   away again, and once its compare passes and it is committed, a new `clear asked` round comes
   before they see it; or it is taken out (no new compare, only `10-polish` step 5.4's rebuild and
   checks), logged and committed. Log `look-back done` once every rejection is settled. Then
   republish what changed and is published, once (`06-site` step 6; the mock sheet as
   `07-cheatsheet` publishes it), its version bumped, and log `republished`. Then the report to the
   student: what was added where (a placement that differs from step 2's report), each text
   reworded, the version, and what they must redo, as `10-polish` step 7.2 says (a changed sheet
   printed again, the cram order's next mock line). Last, log `step 5 done`, hand off and commit;
   the closing commit takes out the `Build running` line and any `Skip asked:` line for it, and
   rewrites the source's line as `Source added: <doc> <date>: done (<the log>)`. Then the patches
   and checks that waited, as `10-polish`
   step 7.5 says.

**A stop.** A session that finds `Build running` beside a `Source added: <doc>, started` line reads
the log, then the tree with `git status` and `git diff --stat` only. While a mock is untaken and
the log doesn't show `look-back done`, the student looks away first (a list of paths they may
read).

- Once the log shows `step 4 done`, the change is checked and in HEAD, and nothing is put back:
  step 5 goes on at its first item the log doesn't show done, the look-back first while a mock is
  untaken, whatever the student's word; a look-back change on disk passes its compare before any
  commit, as the next bullet says. Material they want out after all leaves by a `10-polish`
  `scope` pass, once this build has closed.
- Before that, on their word that it resumes: go on at the first step, stage or product the log
  doesn't show done. Step 3 is done once the log shows `fence checked`; before that, with the fence
  in HEAD (`git show HEAD:STATUS.md`), run its parent and hub checks; without it, put STATUS.md back
  as HEAD has it (`git restore --source=HEAD --staged --worktree -- STATUS.md`) and run step 3
  again, its `before <sha>`, its baseline file and `baseline taken` written anew in place of the
  old. A stage stopped partway runs again from its step 1 over what is on disk, and an uncommitted
  change to the notes or a sheet passes its compare, against step 3's committed baseline file,
  before any commit.
- Before that, on their word that it won't: put the hub back as it stood at `before <sha>`, from
  git's own record. First list the paths, never their contents, and the doc ids of the MANIFEST.md
  rows the change added, or changed from a row reading `Rendered: no` at `<sha>` (MANIFEST.md on
  disk against `git show <sha>:MANIFEST.md`, before anything is restored; a row the change didn't
  touch keeps its renders): each file `git diff --name-only <sha>` names, and each untracked file
  under `notes/`, `_build/extract/`, `_build/frag/` and `_build/verify/` (`git status --porcelain
  --untracked-files=all`), all but `_build/logs/` and `practice/tutor/`, which a tutor tab may
  write. Then, on their go, `git restore --source=<sha> --staged --worktree -- <each listed tracked
  file>`, which also takes a file `<sha>` lacks out of the index and off the disk; `rm` each
  untracked one; and for each listed doc id, delete what `01-ingest` rendered for it:
  `_build/pages/<doc>/` and `<doc>@300dpi/`, `_build/text/<doc>/` or `<doc>.md`,
  `_build/media/<doc>/`. STATUS.md is among the restored files (only this build wrote it since
  `<sha>`: no attempt starts and no tutor tab writes STATUS while `Build running` stands), so add
  the line `Source added: <doc> <date>: stopped, nothing applied (<the log>)` and commit it all at
  once. HEAD and the disk then hold the hub as at `<sha>`, but the logs, the raw copy in `sources/`
  and the new pages of a row whose range grew (all ignored by git and outside every row's range).
  The student may look back and is told what was put back; then the patches and checks that waited,
  as `10-polish` step 7.5 says.

## A source added unverified

The student asks to skip the extract, the backbone or the reviews for a source added to this exam
once its plan is approved (SKILL.md hard rule 2, FB-013): a short recitation the night before,
say. They get one pushback; asked again, the material goes in as they ask, unchecked and bannered
so. A `Skip asked: <file>` line in STATUS (the source's file name: it has no doc id yet) makes an
ask the second, in any session. Every commit and handoff this section makes, the pushback's
included, surveys the tree with `git status` and `git diff --stat` only, commits with a plain `git
commit` and saves no memory, as "A source added" says. The first row that fits the session says what
happens:

| Where the ask comes | First ask | Asked again |
|---|---|---|
| A `09-tutor` tab, or a second tab beside the cram night's (`08-practice` step 8: one tab runs it; that tab tutors under its step and is neither) | Nothing written and no pushback: a source is added before `Stage 08 built` in a session of its own, from then on in the cram night's tab, so the student asks there | The same |
| A build under way or unfinished: `Build running` stands (the unattended build, a stage or pass run alone, "A source added" past its fence, an addition under way), or `05-verify` isn't done (`06-site` too, when the notes have a page) | Nothing written and no pushback: the ask waits until no `Build running` line stands and `05-verify` is done (`06-site` too, with a page), and the student brings it then. "A source added" past its fence stops instead on their word that it won't resume ("A stop"), and they ask again once it has | The same |
| "A source added" before its fence, its step 1 checks passed | The pushback, with step 2's report, its `Skip asked` line committed when the report is shown | That build ends declined at step 2 (logged), then the addition |
| The hub isn't free (`10-polish` step 1: a notes patch open, `08-practice` step 8.3 or 8.4 under way) | The pushback | The addition, once the hub is free: in this session, or at the student's next ask |
| Any other: before `Stage 08 built`, a session of its own; from then on, the cram night's tab, between attempts | The pushback | The addition |

**The pushback**, before any notes are written: what the skip costs (the material goes in
unchecked, its values quoted from the source and never computed, under an `Unverified` banner, off
every sheet, out of the mocks and the cram order's reading rows, and out of `09`'s walk-throughs and
quizzes while its STATUS line stands) and about how long "A source added" would take for this
source. Then commit `Skip asked: <file>, <date>, pushback
given` in STATUS (while a mock is untaken, after `08-practice` step 4's STATUS check with the
untaken mocks' keys, as every STATUS write then), and wait, writing no notes. The full path, if
they take it, is "A source added" from its step 1. The line goes when the source is in: in "A
source added"'s closing commit (step 5), or in the addition's commit, which puts the `Unverified:`
line in its place. It goes too on the student's word that the source won't be added (logged), and
at the next exam's STATUS reset (step 5.3). A stop that puts the hub back to `before <sha>` keeps
it, since the line was committed before the fence.

**The addition**, in the session the table names. However it ends (done, a failed check, a failed
fence check, "A stop" below), its last act is `10-polish` step 7.5's patches and checks, which its
fence held. While a mock is untaken, an ending that adds nothing (a failed check, a failed fence
check) logs why in STATUS and ends its reply with one line, `Nothing was added: type /clear, then
"why did the addition stop?"`, since the student, looking away, waits for a `/clear` line; the
fresh session answers from STATUS, then runs step 7.5.

1. **Check and fence.** While a mock is untaken (STATUS records each attempt), the addition's first
   message, before any tool runs, is one line: `Look away from this window now: come back when a
   reply's only line asks for /clear, and type it before reading anything above that line.` The
   student stays away until the look-back (item 6), and `08-practice` step 8's fence binds this
   session: it opens no untaken mock's key, `practice/mock-values-key.md` or
   `_build/verify/mock_key.py`, and searches only `notes/`, `cheatsheet/`, `_build/frag/` and
   `_build/extract/`. Then check as "A source added" step 1 does: `05-verify` done (and `06-site`
   with a page), no `Build running` line, the hub free, the tree clean but for `_build/logs/` and
   `practice/tutor/`; note `git rev-parse HEAD`. A check that fails is told to the student, and
   the addition waits for it. Pick the doc's id now, a new one as `01-ingest` gives (none reused):
   it is `<doc>` from here on, in its MANIFEST.md row and both STATUS lines, and the id
   `extract_check.py` reads. Then add `Build running: <date>` and `Unverified add: <doc>, started
   <date>` to STATUS and commit them (hard rule 1: while they stand a `09-tutor` tab keeps its
   build limits and dispatches no patch, and no attempt or polish pass starts). Check that this
   commit's parent is the HEAD noted (`git rev-parse <it>~1`, where it is `git log -1 --format=%H
   -- STATUS.md`, since a tutor tab may have committed its log since) and the hub is still free;
   otherwise another tab wrote in between: take both lines out, commit, and stop, and the student
   asks again.
2. **Ingest** the doc as `01-ingest` steps 1 to 3 do: copied in by name, rendered, and its
   MANIFEST.md row, `in` with the doc id item 1 picked and its count from disk, its Answers cell as
   the template's legend says, its Notes naming who put it in scope (a staff post, or the student's
   word, quoted).
3. **Write**, the notes only, in the Write brief's Format: a new section after the last, or a
   short subsection just before an old section's Must know, placed and named as "The build on a
   reopened hub" row 03 says, any text naming the moved Must know by number updated. Each
   `How it's tested:` line reads `not mapped (unverified)`; a new section ends with its own Must
   know list, as the Format says, and a subsection in an old section adds no line to that
   section's Must know. In `_build/backbone.md` each new heading and its id go in, at the same
   place (and the moved Must know's number), so later material numbers from them. Nothing else
   changes: no coverage-matrix, How it's tested or worked-example row, nothing on a sheet, a mock,
   the cram order or the map; a request for one waits until the material is verified.
   - The material opens with `> **Unverified:** added <date> from <doc> without extract or review,
     at the student's request; quoted values unchecked.` (CONVERT.md makes it a `callout warn`
     labeled `Unverified`).
   - A value is one `_build/verify/examples.out.md` already holds, or is quoted from `<doc>` with
     its citation; never computed, and the checker isn't extended for it. This is the one exception
     to hard rule 3, to STYLE S7's first two sentences and to "Changing the notes or a sheet" item
     2. An answer to a set's question (the doc's own, when its Answers cell is `yes`) is quoted
     only once that set is marked `yes, attempted` (S7); until then it is cited by page and left
     out.
4. **Rebuild**, with a page: the section's fragment (`06-site` step 3, its `fidelity.py` check
   included; a hub whose `_build/CONVERT.md` lacks the `Unverified` callout, made before it, gets
   that line in the Convert brief, since the copy changes only at a reopen) and the page (step 5,
   its checks and screenshots); with plain-text notes, `notes/combined.md` (`04-write` step 6).
   While a mock is untaken, items 3 and 4 run as
   `08-practice`'s "Changing the notes or a sheet" with the untaken mocks' keys: its baseline (item
   1) before the first write, its values as item 3 here says, and its compare (item 4) passed before
   any commit, a hit on a quoted value reworded by leaving the value out, its citation kept.
5. **Commit**, once: the material (its notes, fragment and page), its backbone headings, its
   MANIFEST.md row and, in STATUS, `Unverified: <doc>, <section ids>, <date>` in place of the `Skip
   asked` line, with any rewording logged by its part, never a value, as "Changing the notes or a
   sheet" ends (each STATUS write checked as the pushback's). Then republish what is published
   (`06-site` step 6), its version bumped, and take out the `Build running` and `Unverified add:`
   lines in a commit of their own.
6. **Report.** While a mock was untaken, the look-back first: the screen holds edits the compare
   caught, so hand off and commit, and end the reply with one line, `The change is checked: type
   /clear, then "what was added?"`, as `08-practice` step 7.4 does; the fresh session answers from
   STATUS, then runs `10-polish` step 7.5. The report: what went in and where, any rewording, the
   version, and that the material stays bannered, off every sheet, out of the mocks and the cram
   order's reading rows, and out of `09` until verified.

**A stop.** A session that finds `Build running` beside an `Unverified add: <doc>, started` line
first asks the student whether another tab still runs the addition; if one does, it changes nothing.
On their word that it has stopped, it reads the tree with `git status` and `git diff --stat` only;
while a mock is untaken, the student looks away from the earlier work and reads only this session's
questions and its list of paths. Once HEAD's STATUS holds `Unverified: <doc>` (item 5's commit), the
change is checked and in: republish unless the live page already matches the build (`06-site` step
6's live read), take out both lines, commit, and go on at item 6. Before that, nothing the addition
wrote stays: list the paths, never their contents, that `git diff --name-only HEAD` names and the
untracked ones `git status --porcelain --untracked-files=all` names, all but `_build/logs/` and
`practice/tutor/`. Then, on the student's go, restore the tracked ones from HEAD (`git restore
--staged --worktree -- <each>`), `rm` the untracked ones, take out both lines and commit. The doc's
renders and its copy in `sources/` (ignored by git) stay. HEAD still holds the `Skip asked` line, so
the student's next ask runs the addition again. The student may look back and is told what was put
back. Either way, `10-polish` step 7.5's patches and checks come last.

## Common mistakes

| Mistake | Instead |
|---|---|
| Running intake again for the next exam | This stage: the hub's sources, extracts and notes carry over |
| Leaving the finished exam's mocks and sheets in place | Archive them: a reset STATUS would read those mocks as untaken |
| Keeping the hub's old STYLE or chassis because it "works" | Adopt the skill's current copies; the diff goes to the retro |
| Renumbering sections to put the new exam first | New sections follow the last; ids never change |
| Deleting an old section the new exam doesn't cover | A section-level `Not on <exam>` banner (FB-121) |
| Copying homework due dates into CLAUDE.md | Point to where the course keeps them (FB-181) |
| Editing a file in the archive | It is frozen: fix the notes and the current sheets |
| Writing a source's notes at the first "skip the pipeline" | One pushback, a `Skip asked` line, then wait ("A source added unverified") |

## Done when

The hub is tagged `exam/<old-slug>`; the finished exam's products are under `practice/<old-slug>/`
and `cheatsheet/<old-slug>/`, its attempts in `attempts.md` there, and the student knows how an
untaken one is marked; the template copies and the chassis are the skill's current ones, the diff
logged, the `.gitignore` lines present; MANIFEST.md, CLAUDE.md's exam facts and Repo rules, and
PLAN.md are this exam's, the PLAN approved with its `Reopened from` line; STATUS's exam lines are
reset and the earlier exams' URLs kept; the build is launched; the log shows every step done, and
it is handed off and committed.

A source added to this exam is done when its log shows each stage, each product, step 4 and step 5
done, STATUS reads `Source added: <doc> <date>: done` with no `Build running` line, and the change
is republished; or, stopped, when the hub is as at `before <sha>` with the stopped line; or,
declined at step 2, when the log says so; or, after a failed fence check, when both lines are out
and committed. In each, STATUS's next-step line reads as at step 1, and `10-polish` step 7.5's
patches and checks ran last.

A source added unverified is done when one commit holds the material under its banner, its backbone
headings, its MANIFEST.md row and the `Unverified:` line in place of the `Skip asked` line, what is
published is republished, the `Build running` and `Unverified add:` lines are out and committed,
and, while a mock was untaken, the compare passed before that commit and the reply ended with the
`/clear` line; or, stopped before item 5's commit, when the hub is as HEAD had it with both lines
out; or, after a failed check or fence check, when nothing was added and both lines, if written,
are out and committed. In each, `10-polish` step 7.5's patches and checks ran last.
