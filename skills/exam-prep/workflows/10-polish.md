# 10 Polish

Baseline as of 2026-10-20; changes only via `12-retro`.

A pass over the verified notes for one kind of failure, or for a scope change that came after the
build: scan, report, then apply exactly what the student approves (FB-170). It runs only when the
student asks (PLAN.md's default: after the build). `_build/STYLE.md` already holds what the past
passes taught (S3 to S7, S24), so a pass checks a skill-built hub against those rules instead of
discovering them again.

A pass changes the notes and the sheets in place, so it runs like a build stage run alone: the
`Build running` line fences it (hard rule 1), and the main session applies every fix, one at a
time, as `05-verify` step 5 says. It isn't study Q&A (hard rule 9): a question the student asks
meanwhile goes to a tutor tab, which runs within `09-tutor` step 1's limits and whose patches wait
for the pass's end. Before STATUS records `Stage 08 built`, a pass runs in a session of its own;
from then on, in the cram night's session (`08-practice` step 8, its one tab), between attempts.

| Pass | Finds | Scanned by | On |
|---|---|---|---|
| Clarity | where a fresh reader stalls on the pattern (step 2) | one reader per section (FB-174) | every section, or the ones the student names |
| Causation | an effect stated before its cause, an implication that doesn't say which way it runs (S5, FB-173) | one reader per section | the sections the student names |
| Numbering | departures from S3 and the backbone's `set-` registry (FB-172) | one reader, the numbering variant | every section |
| Redundancy | an idea stated more often than S6 allows (FB-171) | the main session | the sections the student names |
| Scope | every product a scope change touches (FB-180) | the main session | the whole hub |

A direct instruction that names its edit, what and where ("add the cost caveat to §4.6 and where
§3 first gives the cost"), is an approved list of one, the pass `edit`: skip steps 3 and 4, but
show a sheet line it changes, exactly, before making it (FB-137; while a mock is untaken, at step
6's look-back). A fix a question prompts while the student studies is `09-tutor`'s patch instead
(FB-166).

## Step 1: Check the inputs

- `05-verify` is done, and `06-site` is done when the notes have a page. A pass needs verified
  notes to polish.
- STATUS has no `Build running` line. With one, a build or another pass is under way, and this
  pass waits for it (SKILL.md's routing); a pass that stopped partway resumes as "A pass that
  stops" says.
- The hub is free, as `09-tutor` step 5's "One open patch" defines it for a dispatch: no notes
  patch open, and `08-practice` steps 8.3 and 8.4 not under way. Otherwise log in STATUS that the
  pass waits and stop: the patch or the step finishes first, and the student asks again. Step 2
  puts up the fence.
- Whether a mock is untaken: STATUS records each attempt (`08-practice` step 8.2). Until the last
  mock is taken, this pass runs within the limits below, with the untaken mocks' keys (before any
  attempt, `practice/*-key.md`). The set holds for the pass: `08-practice` step 8.1 starts no
  attempt while the `Build running` line stands, and a mock the student takes anyway is recorded
  once the pass ends.
- MANIFEST.md's Answers cells: a fix quotes an answer only from a set marked `yes, attempted`.
- PLAN.md's Checker line: a new number or trace in a fix comes from the checker, or with none from
  a cited source, its working shown (hard rule 3).

While a mock is untaken, the pass keeps `08-practice` step 8's fence, with the cram order added: the
session and every reader search only `notes/`, `cheatsheet/`, `_build/frag/`, `_build/extract/` and
`practice/cram-order.md`, open nothing under `practice/` but the cram order (the student reads it
before the mocks), and never open `_build/verify/mock_key.py` or `_build/mock-plan.md`: a search
over the hub root prints key lines, and the plan holds the mocks' questions. Each write to the
pass's log or to STATUS is followed by `python3 -I <skill>/scripts/mock_leak.py <file> <the untaken
mocks' keys>` until it prints LEAK OK, a hit reworded (`08-practice` step 7.4's check), and the
student reads the report only once the log has passed. From step 5 to the end of step 6 the student
looks away from this window, as `08-practice` step 4 asks: an edit shows its text before the leak
compare clears it.

Every commit in a pass, and its handoff, surveys the tree with `git diff --stat` and `git status`
only and commits with a plain `git commit`, as `08-practice`'s opening says, whether or not a mock
is untaken: a tutor tab's `practice/tutor/` holds values of parts the student hasn't attempted
(`09-tutor` step 7). A handoff saves no memory, for the reason that opening gives.

## Step 2: Pick the pass

From the student's ask: the pass, the sections, and the pattern.

- **The pattern** (clarity, causation): the student's own words and the exemplar that stalled them
  (quote both into the brief), or a `## Patterns` line from `_build/logs/tutor.md` (`09-tutor` step
  5.6). With neither, clarity takes the default list: a construction or worked example with no
  `Conclusion:` line (S4), a cause stated after its effect (S5), a symbol used before it is defined
  (S15), a step whose "why" is missing (S24), and an "it" or "this" whose referent isn't clear;
  causation takes S5 alone.
- **Causation** runs only on an ask: its one past run, four readers, had one real finding.
- **Numbering** reports departures from S3 and from the backbone's `set-` registry (a recipe
  that isn't numbered steps, a fixed set lettered twice or in a section the registry doesn't
  name, a mention that doesn't link to the set's anchor, a worked example whose steps reuse a
  recipe's numbers). It never renumbers a section or subsection: its `sec-N-<slug>` id is what
  the cram order, the exam-day map and the Must-know lines link to.
- **Redundancy** covers only the sections the student names.
- **Scope** starts from the source for the change, quoted: staff-authored text or an endorsed
  answer (hard rule 7), never a student's post alone.

Name the pass's log, `_build/logs/polish-<pass>-<date>.md` (`<pass>` one of `clarity`, `causation`,
`numbering`, `redundancy`, `scope`, `edit`; a second pass of the same kind that day adds `-2`, then
`-3`, before `.md`, and that name is the pass's everywhere, its STATUS line and its baseline file
included). Start it: the ask in the student's words, the pass, the sections, the pattern, and the
hub's head (`git rev-parse HEAD`) as `before <sha>`. The log marks each step's end as it finishes
(`step 2 done`, `step 5 done`) and each of step 7's items, so a resume knows where the pass stopped.
The pass's paths, below, are `notes/ _build/frag/ 'cheatsheet/*.html' 'cheatsheet/*.tex' MANIFEST.md
_build/backbone.md _build/chassis.html practice/cram-order.md` as git pathspecs, the globs quoted
(zsh stops on a glob that matches nothing).

Then put up the fence: add `Build running: <date>` to STATUS, and `Polish: <pass>, started <date>
(<the log>)` in place of any earlier pass's `Polish:` line (STATUS keeps one; the logs keep the
rest), commit them with the log, then check step 1's free hub again. A patch
dispatched or a step 8.3 begun in between means taking both lines out, committed, and stopping as
step 1 says.

## Step 3: Scan

- **Clarity, causation, numbering.** Load the delegation skill first. Spawn readers from
  `<skill>/templates/agent-briefs.md`, section "Polish reader", unnamed, as the `reviewer` role with
  `model: "haiku"` on the Agent call (cheap and fresh; step 4 checks every finding): one per
  section file, all at once; for numbering, one reader over every section, from the numbering
  variant. Each reads its section's `notes/NN-*.md` and, with a page, the figure text in its
  `_build/frag/sec<N>.html` (an SVG label is prose the student reads, and the one real causation
  finding was one), plus `_build/STYLE.md` and, for numbering, the backbone's registry.
- **Redundancy.** The main session alone. Read the section's notes file, then, with a page, its
  fragment, to see what each figure adds. List the section's parts (figures, worked examples,
  prose), then each idea with every place it is stated and how (a derivation, a key-formula callout,
  a figure, a bullet). Tell redundancy (prose that restates a figure) from reinforcement (a figure
  that reuses a worked example's numbers to show what the example computes), and keep every
  back-link and recall (S6). The levers, least to most: trim the prose that restates; drop an
  example or a figure, only when the student asks for it. Worked examples are already collapsed
  (S7).
- **Scope.** The main session alone. List the change to MANIFEST.md first, as rows or a topic cut
  (scope's one home, `templates/MANIFEST.md.tmpl`; step 5 makes it first, after its baseline), then
  what it does to each product. A cut takes out only the material it names: what its Conventions
  line says stays in scope stays, with everything that teaches or tests it. For a cut:
  - the backbone: its Conventions line for the cut, naming the subsections it reaches and what of
    them stays (`03-backbone`); the "How it's tested" rows stay, since every practice part keeps
    one;
  - the cut material goes under a `Not on <exam>` banner, never cut (`04-write`, FB-121), in its
    fragment too; a Must-know line that names only cut material goes, and so does an exam-day map
    shape that tests only cut material, which the map leaves out from then on (`06-site` step 4);
    a Must-know line that names cut and kept material is reworded to the kept part, and the map's
    `.edrill` line, when it names cut material, to the kept part or to the next shape to drill;
  - the chassis's exam line, refilled from MANIFEST.md (`06-site` step 1), and its `.lede` reworded
    when it names cut material;
  - each sheet item on cut material goes, the space left blank for the final sheet
    (`07-cheatsheet`'s "After shipping", FB-140); so does a queued addition on it, a STATUS
    final-sheet item struck with why, or a tutor log `sheet line` dropped on the student's word
    (`09-tutor` step 5, "One open patch");
  - a cram order row on cut material moves to its skip list (`08-practice` step 7), and one whose
    one thing names cut and kept material is reworded to the kept part;
  - an untaken mock isn't opened or edited: the cram order's line for it says the mock predates
    the change, to skip any part on the cut and score out of the points left. A taken mock stays
    as it is.

  A widening puts material back in. When the notes keep it under a banner, the banner goes and
  each product above takes it back by its own stage's rule; while a mock is untaken, the cram
  order takes it back as a row in its last reading tier, since its ranking reads
  `_build/mock-plan.md`, which the fence keeps closed, and an untaken mock's line drops the skip
  an earlier cut gave it for that material. When it needs a source the hub never
  extracted, it isn't a pass: `11-next-exam` adds sources to a built hub.

## Step 4: Report

1. Check every finding against the file before reporting it (FB-108): open the line it quotes and
   judge the stall yourself. A reader has been wrong, and has overstated. Drop one the file doesn't
   bear out, tone down one it bears out only in part, and log both with why.
2. Rank each one `blocker` (a question shape in the backbone's "How it's tested" table stalls on
   it: name the question), `major` or `minor`, as `05-verify`'s reviewers do, and number them
   across the ranks, blockers first. Numbering and scope report their list instead, each item
   numbered.
3. Write the report into the log: each item's number, where it is (`§N.M`, the line's first
   words), the stall in one sentence and the fix in one line (a fix to a printed sheet gives its
   new line exactly: the student sees a sheet's change before it is made, FB-137); then a
   recommendation (a rank, numbers, or for numbering a scope) and the question: which items to
   apply. While a mock is untaken, the log's leak check passes first. Then show the report in the
   message itself (hard rule 11).
4. The student answers with a rank, numbers, "your recommendation" or a scope; text they add to an
   item is shown again before it goes in (while a mock is untaken, from the log once it passes).
   Log the answer and commit.

## Step 5: Apply

1. Apply the approved items and nothing else (FB-170). An item the student adds is applied and
   logged with the others. A scope list starts with its MANIFEST.md change (after item 2's
   baseline), and each product follows its own stage's rule, as step 3 lists them. A change an
   approved item forces beyond its own line (a heading the trim leaves empty, a link whose target
   moved) is made, logged, and named in step 7's report.
2. While a mock is untaken, tell the student to look away now. Then "Changing the notes or a sheet"
   item 1, the baseline, before the first change: its hit lines (part ids only) go to the pass's
   baseline file (its log's name with `.baseline.txt` for `.md`), committed with the log, which
   records `baseline taken`.
3. One fix at a time, as `05-verify` step 5 says: every copy of the fact (the section's notes file
   and, with a page, its fragment, a Must-know line, a pitfall box, both sheets, a cram order row
   that quotes it; grep `notes/`, `_build/frag/`, `cheatsheet/` and `practice/cram-order.md` for
   the old phrase), a new number or trace as step 1 says, never an answer from a set MANIFEST.md
   doesn't mark `yes, attempted`. While a mock is untaken, each fix is that section's item 2: a
   method taught in general or with an example of its own, never a mock's instance. Change the
   fragment in its own markup (`_build/CONVERT.md`), and a figure label in the fragment's SVG and
   wherever the notes describe it. Use the Edit tool: the notes hold math and Unicode that a `sed`
   rewrite breaks. A corrected fact changes on both sheets; an added sheet line, while a mock is
   untaken, goes where `08-practice` step 8 sends a one-line addition (the final sheet once its
   step 8.3 has built it, until then STATUS as a final-sheet item). Mark each item's outcome in the
   log as it lands. A change an item makes outside the pass's paths (a STATUS final-sheet item added
   or struck, a tutor log line dropped) is logged with it and made at item 6, just before the
   commit, so a stop before that commit leaves none.
4. Rebuild and check what changed: `06-site` step 3's `fidelity.py` on each section touched, then
   `06-site` step 5, its screenshots of those sections seen (plain-text notes: the references
   checked by eye, `04-write` step 6, and `notes/combined.md` rebuilt when it exists). An HTML
   sheet that changed goes through `07-cheatsheet`'s "After shipping": the audit limited to the
   change, then its step 4. Near a full side, new wording is no longer than what it replaces
   (FB-137). A LaTeX sheet changes in its `.tex` only; the student compiles it (step 7.2). With a
   cram order, `08-practice` step 7's item 1, and while a mock is untaken its item 2 with the
   untaken mocks' keys.
5. While a mock is untaken, "Changing the notes or a sheet" item 4: rerun the baseline's command and
   compare with the pass's baseline file (a `.tex` is read as its source). A new hit on a
   number, order or table answer is a leak: reword it, log the reword as the item's `changed
   (how)` (step 6 takes it as the approved text, and the look-back shows it), and repeat from item
   3.
6. Make the logged changes outside the pass's paths, mark `step 5 done` in the log, and commit it
   all together, only once item 5 passes: a tutor tab reads the notes as committed.

## Step 6: The fidelity review

One fresh `reviewer` (no model set), from the "Polish reader" brief's fidelity variant, checks each
applied fix against its approved item and that nothing else in the change alters what the notes say.
Write its input first, into a file in the session scratchpad (written again on a resume): `git diff
<before> HEAD -- <the pass's paths>`. When it reports, log `fidelity review run` and every finding
at once, then each one's outcome as it is settled. Check each finding against the file (step 4.1).
One that an approved item isn't fully in (a copy missed, the text not as approved) is applied as
step 5 applies a fix, the same baseline kept, and committed. One that a fix overreached is put to
the student: keep it, or put the `before` text back. While a mock is untaken, that question is
logged `held for the look-back` and waits for it. Putting the `before` text back needs no new
compare (that text passed the baseline), only step 5.4's rebuild and checks, then a commit.

The look-back, while a mock is untaken, once the last compare has passed: the student looks back;
show them what changed on each sheet (FB-137) and each text reworded after a leak hit (step 5.5),
ask each held question and apply its answer as above, and log `look-back done`, before step 7's
republish. A change the student rejects there is reworded by them, and applied as step 5 applies a
fix (they look away again until its compare passes, then see it), or put back the same way as an
overreach: a corrected fact in every copy (FB-106), its item logged as dropped; an addition, from
the sheet alone, its item logged `changed (how)` when the notes keep it, else dropped.

## Step 7: Ship and close

1. Republish what changed and is published, once for the pass (`06-site` step 6, its live read
   first when this session didn't build the page; the mock sheet as `07-cheatsheet` publishes it),
   and bump the version on its STATUS line as `09-tutor` step 5.5.8 does.
2. What the student must redo:
   - A sheet the student has printed and that changed, the final sheet included, is printed
     again: tell them, and log it in STATUS until they say it is done.
   - While a mock is untaken, "Changing the notes or a sheet" item 5 too: a changed mock sheet is
     logged in STATUS, and the cram order's next mock line says to print it again (with LaTeX, to
     compile it and bring the PDF first); then `08-practice` step 7's item 1, and its item 2 with
     the untaken mocks' keys.
   - A changed LaTeX sheet is compiled by the student; when they bring its PDF, it is checked with
     `check_pdf.py --no-layout`, as `08-practice` step 8.1 checks one, and STATUS logs it until
     then.
   - Plain-text notes: the sections to paste again, logged in STATUS until they say it is done.
3. The log: each item applied, changed (how), dropped (why) or beyond the list, and the fidelity
   review's outcome, or that it didn't run.
4. The report to the student: what was applied, anything beyond the list (FB-170), anything a stop
   put back, a fidelity review that didn't run, the version, and what to print, compile or paste
   again.
5. Hand off and commit. In that same commit, the `Build running` line goes (hard rule 1) and
   STATUS's `Polish:` line becomes `Polish: <pass> <date>: <n> applied, <m> dropped (<the log>)`,
   written last, so a stop before it still finds the pass's `started` line. Survey the tree with
   `git diff --stat` and `git status` only, as `08-practice`'s opening says. Then
   the patches and checks that waited: after `Stage 08 built`, this session (the cram night's)
   dispatches the oldest pending patch and offers the waiting checks, as `08-practice` step 8's
   opening does; before it, the one tab that dispatches does (`09-tutor` step 1's Patches and
   Waiting checks bullets: this one when no other tab tutors; ask the student).

## A pass that stops

A session that finds the `Build running` line beside a `Polish: <pass>, started` line reads the
pass's log (the one that line names), `git status` and `git diff --stat`. While a mock is untaken
and the log shows step 4 done (an `edit` pass, which has no step 4: step 2 done) but not the
look-back, the student looks away first; a resume before step 5 needs no look-away, and one that
reaches the look-back has them look back there. The pass's changes are in HEAD when HEAD's copy
of the log (`git show HEAD:<the log>`) shows `step 5 done`.

On their word that it resumes, it goes on at the first step the log doesn't show finished, at the
first item with no outcome: a change on disk the log doesn't mark is checked against its item
first. While a mock is untaken, the compare uses the pass's committed baseline file, never a new
baseline taken from notes that may already hold a change; with no `baseline taken` in the log, no
fix has landed, and step 5.2 runs once `git status` shows nothing changed under the pass's paths.

On their word that it won't resume: steps 5 and 6 commit only after their checks, so every tracked
file `git status` shows changed, but STATUS.md, `_build/logs/`, `practice/tutor/` (a tutor tab's)
and a PDF the student compiled and brought, holds an unchecked change (a rebuilt `_build/notes.html`
or sheet PDF among them). List those files (paths only: the student may read the list) and, on the
student's go, put each back as HEAD has it (`git restore -- <path>`), logging what they held as not
applied: a step 5 item, or a step 6 fix or put-back, its item left as HEAD has it and named in the
report to the student. Without their go, the pass resumes instead: an unchecked change never reaches
a commit. With the pass's changes in HEAD: while a mock is untaken, step 6's look-back runs unless
the log shows it done, the held questions among it; then step 7 from its first item the log doesn't
show done (without `fidelity review run`, the review didn't run, and step 7 says so). Otherwise
nothing the pass applied is in HEAD; the student may look back and is told, by item number from the
log, what was put back, the closing commit takes out the `Build running` line and rewrites the
`Polish:` line as `Polish: <pass> <date>: stopped, nothing applied`, and step 7.5's patches and
checks follow.

## Done when

Each approved item is applied or logged with why not, and nothing else changed; the fidelity
review's findings are settled; `06-site` step 5 passes with its screenshots seen (plain-text notes:
`notes/combined.md` rebuilt when it exists, the sections to paste again logged); each changed HTML
sheet passes `07-cheatsheet` step 4, and a changed LaTeX sheet is logged until its PDF passes;
while a mock was untaken, the leak compare passed and the log and STATUS print LEAK OK; what is
published is republished once with its version bumped; the log and STATUS's `Polish:` line say what
happened; it is handed off and committed with the `Build running` line gone.
