# 00 Intake

Baseline as of 2026-10-20; changes only via `12-retro`.

Intake turns "prepare me for this exam" into an approved `PLAN.md` and a hub that a fresh session
can execute without asking anything. It is the only stage that talks to the student before the
build, so it asks everything at once (FB-020) and asks nothing that is already on disk (FB-022).

## Step 1: Pick the entry case and the root

Judge by the files in the session's own directory, never by a `CLAUDE.md` loaded from a parent
directory. The first row that matches wins.

| Case | How to tell | Then |
|---|---|---|
| Resume | `PLAN.md` for this exam reads `Approved: <date>` | Not intake: go to SKILL.md "Where you are". |
| Intake in progress | `PLAN.md` for this exam reads `Approved: not yet` | Reread the drafts and the hub's files, then continue at step 5. |
| Next exam | `MANIFEST.md` and an approved `PLAN.md` exist for an earlier exam | Not intake: go to `workflows/11-next-exam.md`. |
| Own-conventions root | the directory is `<hub>/exam-prep/`, made by the bullet below | `<root>` is this directory. Continue at step 2. |
| Own conventions, set up | the directory has a `CLAUDE.md` exam-prep didn't write, and `exam-prep/PLAN.md` exists | The work belongs to `exam-prep/`: open a session there with the student's request as its prompt (`hq-open --sub exam-prep <name> "<request>"`, or by hand), and stop here. |
| Own conventions | the directory has a `CLAUDE.md` exam-prep didn't write (it lacks the line "An exam-prep hub") | `<root>` will be `<hub>/exam-prep/`, a repo of its own: the bullet below. |
| New course | anything else: no hub yet, an empty one, or one made ahead with staged sources and a STATUS.md | `<root>` is the hub. |

**Intake runs in a session rooted in `<root>`.** The Ed pull writes under the session's working
directory, and a sandboxed session commits only to a repo inside its own root. So before step 2:

- **Every case:** `<root>` must be a git repo of its own (`git init` there when
  `git -C <root> rev-parse --show-toplevel` doesn't print `<root>`), and its `.gitignore` gets
  these lines before any source lands, keeping any lines already there: `sources/`,
  `_build/pages/`, `_build/text/`, `_build/slices/`, `_build/media/`, `_build/shots/`,
  `node_modules/`, `_build/package*.json`, `__pycache__/` (FB-011).
- **New course, no hub yet.** Name it a short subject word plus the course number, all lower case
  (`widgets1001`). With the hq skill: `hq-new <name> code --git` (one bare command), fill its
  `REGISTRY.md` summary as the hq skill says, then
  `hq-open <name> "Load the exam-prep skill and run 00-intake for: <the student's request>"`.
  Without it: make the directory and ask the student to start a session there with that prompt.
  Then stop: intake goes on in the new session.
- **Own conventions.** From the session the student is in (rooted at the hub), make
  `<hub>/exam-prep/` with its repo and `.gitignore` as above, and add the line `exam-prep/` to the
  hub's `.git/info/exclude` when the hub is a git repo (local and untracked, so the hub's own
  files are left as they are). Then open the intake session there:
  `hq-open --sub exam-prep <name> "Load the exam-prep skill and run 00-intake for: <the student's
  request>"`. Without hq, or with an hq-open that refuses `--sub`, ask the student to run
  `cd <hub>/exam-prep && claude` and paste that prompt. Then stop: intake goes on in the new
  session. There, Claude Code still loads the hub's `CLAUDE.md` from the directory above: it
  governs, and wins any conflict. Never edit the hub's files or its workflow; read its sources in
  place (MANIFEST rows give paths relative to `<root>`, such as `../sources/...`). If the hub
  tracks its own course material in git, tell the student once and leave it.

## Step 2: Read what is already on disk

Every question this answers is one the student isn't asked.

1. **The hub's own files**: `STATUS.md`, `CLAUDE.md` and any notes (in the own-conventions case,
   the hub's, one directory up). A made-ahead hub's STATUS often holds the exam rules, the scope,
   dates and what to keep from whom. These pre-fill answers and are kept: intake adds to a
   made-ahead hub's STATUS and never overwrites it, and never edits an own-conventions hub's files
   at all.
2. **Sources, by name.** List the files the student named or staged. Never glob a downloads folder:
   it holds unrelated secrets (FB-042). Note each file's type and page count (`pdfinfo` for a PDF).
3. **The exam-details file** (an instructor's exam announcement, a syllabus), if one exists. Quote
   its rules: they are the strongest source after a staff post.
4. **Ed Discussion**, if the course uses it. Run the Ed pull now (`workflows/01-ingest.md`, "Ed
   Discussion") so `sources/ed/ed-digest.md` exists before the questions. Only staff-authored text
   and endorsed answers or comments can pre-fill an answer. A student's opening post, endorsed or
   not, is a signal, shown as "a student asked X; no staff answer". When two staff posts conflict,
   the later one wins and both are shown.
5. **The profile**, `~/scratch/exam-prep/profile.md` (below). Don't ask what it holds.

Record course logistics as you find them: grade weights, the number of homeworks and exams, the
late policy, the exam dates and the instructor's exam-format statement. A fact you can't find is
written "not recorded", never guessed (FB-025).

## Step 3: Ask once

Ask everything in one round, before the plan: at most two question dialogs back to back, plus one
more only for files that arrive while you wait. Nothing is asked after approval (FB-020). Each
question below is asked only when step 2 left it open. A pre-filled answer still goes to the
student to confirm: put the quote, its date and its source (Ed thread number, file and line) in the
question text, and list the option it supports first.

| # | Ask | Options | Why |
|---|---|---|---|
| 1 | **Scope authority.** Does the graded work (homework, a practice exam, a review sheet) mirror the exam, and which of it? | Mirrors it, naming which (a practice exam, the review sheet, every homework): scope follows it, mocks clone its questions with fresh numbers. / Doesn't: cover the full scope, mock shapes go beyond the review. / Unsure: treat as doesn't. | Settles everything after it (FB-021). |
| 2 | **Which files belong to this exam?** Show the proposed split by file name: this exam, reserved for a later exam, out. Ask for the exact last in-scope slide and whether its number is the PDF page or the printed slide number. Ask which files hold answers (official solutions, a past exam's key), and which of those sets the student has already attempted. | The proposed split (first). / Other: the student corrects it. | Later material is copied raw and never opened (FB-023); slide and page numbers differ (FB-024, L04). |
| 3 | **Missing sources.** Only when a source type the exam covers (homework, solutions, recitations, the last lectures) isn't on disk. | I'll add them now. / They arrive during the build. / Proceed without. / Not examined. | "Add them now": stop, wait for the file, re-list, and ask question 2 for it (FB-029). "During the build": a `pending` MANIFEST row that records its planned scope now, last in-scope slide included, since nothing is asked after approval. |
| 4 | **Exam rules** not found on disk: date and time, length, cheat sheet allowed and its size, calculator, open or closed book, question types. | Pre-filled from the details file or Ed, else open. | Fixes the deliverables (FB-026). |
| 5 | **Cheat-sheet preferences.** Only when a sheet is allowed and the profile lacks them: font floor in points, color or grayscale print, engine (HTML the session builds and Chromium prints, or LaTeX the student writes and the session checks), and their full name in each form they write it (given and family name in either order, with initials) and their student id, which the sheet check keeps off the sheet (FB-132); a lone name part only when it isn't an ordinary word. | Default: a 6 pt floor, colors that still read in grayscale, HTML printed by Chromium. Save the answers to the profile; the name and id go there only, never in PLAN.md, and only as the student gave them. | Asked once per student, not per exam (FB-131). |

If the student narrows scope ("only topic X, go deep"), check the narrowed scope against the
sources before committing to it, and say what the check found (FB-021).

**Not questions.** These take the default, and the plan shows each one marked "(default)" so the
student can change it while reviewing:

- Deliverables: topic notes in markdown as the source, one notes page published as a private
  artifact, a cheat sheet when the rules allow one (two sheets once a mock exists, FB-133), a mock
  with its key in a separate file and a three-view mock page (FB-153), and a cram order offered the
  night before (FB-157).
- Depth weighted by how the exam tests: procedures get depth, definitions stay brief (FB-064).
- Figures where prose can't carry a mechanism, plus two or three step-throughs for the most-drilled
  procedures.
- The reader may have skipped the lectures: assume no prior exposure (FB-030).
- Ship priority if time runs short: notes page, then cheat sheet, then mock (FB-004).
- Publishing: private artifacts only. A deploy to the student's own site waits for an explicit go
  after review (FB-114).
- Walk-throughs (`09-tutor`) and polish passes (`10-polish`) run on request after the build.

## Step 4: Draft the hub files

Draft all three in `<root>` before showing anything, so the student approves the scope along with
the plan:

- **`MANIFEST.md`** from `<skill>/templates/MANIFEST.md.tmpl`: one row per source file with its
  scope (`in`, a page range ending at the last in-scope slide, `reserved`, `out`, `pending`) and
  whether it holds answers. These rows are the one statement of scope: CLAUDE.md and PLAN.md point
  to them and never restate them (FB-024). `01-ingest` fills the page counts from disk.
- **`CLAUDE.md`** from `<skill>/templates/hub-CLAUDE.md.tmpl`: the exam facts, the instructor's
  exam-format statement quoted with its source (the only basis for any claim about what the exam
  will ask, FB-012), the logistics, and the repo rules. A quote that also states scope stays
  verbatim, as evidence: MANIFEST's rows remain the one statement of scope. In the own-conventions
  case it sits in `<root>`, under the hub's own `CLAUDE.md`.
- **`PLAN.md`** from `<skill>/templates/PLAN.md.tmpl`, still reading `Approved: not yet`. Every
  answer goes in its Decisions block with its source: the student, an Ed thread number, the details
  file, or (default), except question 5's name and id, which only the profile holds. Its Checker line needs the question documents' text: read them
  (`pdftotext`) to decide what is computable.

If plan mode is in use, its file is not durable: the hub's `PLAN.md` is the copy that counts.

## Step 5: Audit the plan

Check that the plan names, for each item, the written rule that governs it (FB-028). Written rules
beat "reuse the look":

- visual design: the hub's `_build/CHASSIS.md`;
- pedagogy and wording: the hub's `_build/STYLE.md`;
- structure and enumeration: STYLE's numbering rules and the backbone;
- cross-references: the id registry, fixed in the backbone before any writer starts (FB-060);
- the mock page's three views and the tags they need (FB-153);
- the checker: what is computable in this course, or a statement that nothing is (`05-verify`).

The hub copies come from this skill's current templates, never from an older hub (FB-010).

## Step 6: Show it and refine

Show the plan, the MANIFEST scope rows and the drafted CLAUDE.md's exam facts, the exam-format
quote included. Expect several rounds: fold each refinement into the files before showing them
again (FB-027).

## Step 7: Finish the setup, then record the approval

On the student's approval:

1. **`<root>/STATUS.md`.** If a made-ahead hub has one, keep everything in it and set its next
   step to stage 01. Otherwise (a new hub, or the own-conventions case, whose own STATUS stays
   untouched) start it from `~/.claude/templates/STATUS.md` when that exists, else with the
   headings the handoff skill uses.
2. **Hub copies** of the skill's current templates into `_build/`:
   `<skill>/templates/STYLE.md`, `<skill>/templates/CHASSIS.md`, `<skill>/templates/CONVERT.md`
   and `<skill>/templates/MOCK.md`.
   `11-next-exam` reconciles these copies against the skill later; hubs never fork them.
3. **The approval line, last.** Replace `Approved: not yet` in `PLAN.md` with
   `Approved: <YYYY-MM-DD> by the student`, and delete the comment under it. Written last, it
   also means the setup is complete: a session that finds it can trust the hub files exist
   (FB-001).
4. **Commit locally**, staging files by name. No remote (FB-011).

## Step 8: Launch the build in its own session

Planning and execution stay in separate sessions. Everything durable is on disk before the planner
stops (FB-007). The launch prompt, with the brackets filled:

```text
Read CLAUDE.md, PLAN.md and STATUS.md, then load the exam-prep skill. The student approved
PLAN.md and every decision in it is final: execute it end to end, stage 01 through [last stage],
without asking anything. Log judgment calls in STATUS.md instead of asking. If a stage's outputs
already exist on disk, resume from the first unfinished stage instead of redoing finished work.
The exam is [date and time]; if time runs short, ship in PLAN.md's priority order. Leave reserved
material unopened. End each stage with the handoff skill and a local commit. Never push.
```

With the hq skill, one bare command: `hq-open <name> "<prompt>"`, or in the own-conventions case
`hq-open --sub exam-prep <name> "<prompt>"` (options go before the name). Without it: give the
student the prompt in a code block and ask them to start a fresh session in `<root>` with it (or
`/clear`, then paste it).

Then tell the student, before they leave the build to run: once it reaches stage 08 (the mock
exams), don't look at the build session's window, since it writes the mocks' answer keys; follow
its progress in `STATUS.md` instead, whose next-step line then says so. When that line starts
`08 step 8, the cram night`, go to the build window, type `/clear` and then "start the cram
night", before reading anything else on screen.

## The profile

`~/scratch/exam-prep/profile.md` holds what holds across courses. Intake reads it and writes any new
answer back, with the Write tool (the Bash sandbox can't write outside the hub):

```markdown
# exam-prep profile
- Cheat-sheet font floor: <pt>
- Print: <color or grayscale>
- Sheet engine: <HTML built by the session, or LaTeX the student writes>
- Name and id on sheets: never printed; a write-in box (FB-132)
- Never print: <each form of the name, the id: one `check_pdf.py --forbid` each>
```

## Common mistakes

| Mistake | Instead |
|---|---|
| Asking what the details file, the hub's STATUS or a staff post already says | Read them first; confirm the pre-fill with its quote |
| Asking a question whose answer is always the default | State the default in the plan |
| Continuing after "I'll add them now" | Wait for the file, re-list, and ask question 2 for it |
| Taking a student's Ed post as scope | Only staff-authored text and endorsed answers set scope |
| Restating scope in CLAUDE.md or PLAN.md | MANIFEST rows hold it; the others point to them |
| Writing `Approved:` with a date before the setup is done | It is the last thing intake writes |
| Overwriting a made-ahead hub's STATUS.md | Keep it and add to it |
| Running the own-conventions case from the hub root | Its session is rooted in `<hub>/exam-prep/` |
| Executing the plan in the session that wrote it | Launch a fresh session in `<root>` |
