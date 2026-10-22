# 09 Tutor

Baseline as of 2026-10-20; changes only via `12-retro`.

The student studies with the hub: walks through a set one part at a time, takes a true-or-false
quiz, or asks about the material. The main session tutors and only answers; every change to the
notes or a sheet goes to a dispatched writer, on the student's yes (hard rule 9). It runs when the
student asks, any time after `06-site` (or `05-verify` with plain-text notes), and on the cram
night inside `08-practice` step 8's rules. Where a walk-through or a quiz stands, and which
approved patches wait, lives in `_build/logs/tutor.md` and one STATUS line, so a fresh session
picks it up.

## Step 1: Where things are

- STATUS: the notes page's URL and every other artifact's (FB-008), its `Tutor:` line, and
  `_build/logs/tutor.md` for where the last walk-through or quiz stopped (the log wins over a
  Tutor line it has moved past). When the student says where they are ("we finished Q1 and Q2,
  start with Q3a"), their word wins: log it.
- PLAN.md's Checker line; MANIFEST.md's Answers column and its `solutions to <doc>` notes; hub
  CLAUDE.md's exam-format statement and Logistics line.
- The mocks. A mock is untaken while its file `practice/mock-<slug>.md` (not a `-key.md` file)
  exists and STATUS records no attempt of it (`08-practice` step 8.2 records each one, its misses
  or none). While one is, `08-practice` step 8's rules bind the tutor: it opens no untaken mock's
  key, `practice/mock-values-key.md` or `_build/verify/mock_key.py`, and keeps every search inside
  `notes/`, `cheatsheet/`, `_build/frag/` and `_build/extract/` (which holds no mock); every STATUS
  write is followed by that stage's STATUS check with the untaken mocks' keys (its step 4's
  opening); every notes or sheet change runs its "Changing the notes or a sheet"; a one-line sheet
  addition goes where its step 8 says (Step 5.2); and the next-step line stays as it stands.
- A build runs while STATUS has the line `Build running: <date>` (SKILL.md, hard rule 1): the
  unattended build session's, from its launch until its last stage removes it (`08-practice` step
  7.4 puts `Stage 08 built: <exam-slug>, <date>` in its place), or a stage's run alone. It changes
  the notes, the sheets, `_build/verify/` and STATUS, and from `08-practice` step 2 its window shows
  mocks and answers. Any end of a build removes the line (hard rule 1). Read STATUS for the line
  before each part, quiz item and answer, so a tab open since before the build finds it. While it
  stands, a walk-through, a quiz or a question runs in a session of its own, never the build's,
  within these limits:
  - it leaves `_build/verify/` alone: a set with no values file yet waits for the build's end
    unless its official solutions are extracted (Step 3), and so does a part that needs the
    reference extended;
  - it makes no fresh true-or-false statement, keeps every search inside `notes/`, `cheatsheet/`,
    `_build/frag/` and `_build/extract/`, and never opens `_build/mock-plan.md`: before any mock
    file exists, the plan already holds the mocks' questions and their variants;
  - it reads `notes/`, `cheatsheet/` and `_build/frag/` as committed, never from disk: the build
    edits them in place, and from 08's step 2 commits a change only once its leak compare passes
    (`08-practice`'s "Changing the notes or a sheet", item 4), so a line on disk may state a mock's
    answer. Search
    them with `git grep -n -e <phrase> HEAD -- notes/ cheatsheet/ _build/frag/`, and read a passage
    with `git show HEAD:<path> | sed -n '<from>,<to>p'`. `_build/extract/` is searched and read
    from disk with the Grep and Read tools, whose output stays folded (Step 3): a part's block holds
    its `Solution [` line; but not a file `git status --short -- _build/extract/` lists, which a
    build's `02-extract` is still writing (`11-next-exam`'s builds too);
  - it dispatches no patch: one the student approves waits under `## Pending patches` in the log
    (Step 5.3), a one-line sheet addition marked `sheet line`, and the build session never
    dispatches one either (it can't show the student a change or ask them); official
    solutions that arrive, and the `yes, attempted` cell of a set the student finishes (Step 7),
    wait under `## Waiting checks`;
  - it writes no STATUS (the log says where the student is) and runs no handoff skill, whose check
    wants a STATUS edit and a clean tree, both the build's: it ends with the log's commit alone,
    `git add _build/logs/tutor.md`, then `git commit -m "<message>" -- _build/logs/tutor.md`, since
    the build stages its own files;
  - once the line is gone: after 08's build (STATUS records `Stage 08 built` for the exam PLAN.md
    names), it logs a patch the student just approved, commits its log, tells the student to
    bring questions to the cram night's tab, and stops, so one session dispatches (`08-practice`
    step 8 tutors from then on); after a build that ended before 08, it goes on without these
    limits, dispatching what waits (the next bullet).
- Patches, from the log's `## Pending patches`: Step 5's "One open patch" table says where each
  marked line goes on. A writer's hand-back never reaches a fresh session once the session that
  spawned it has ended (ask the student when another tab may still be running it), so find its
  worktree with `git worktree list`. Once no build runs, a `sheet line` goes where Step 5.2 sends
  one then, its mark cleared (into STATUS as a final-sheet item while a mock is untaken, bookkeeping
  with no writer). When the hub is free, dispatch the oldest unmarked line (Step 5.4), and look
  again at each part, quiz item and answer, since a build or another line may have ended meanwhile;
  the next waits until that one is struck through. One tab dispatches: a session opened while
  another tab may still be tutoring (ask the student) logs its patches for that tab.
- Waiting checks, from the log's `## Waiting checks`: with no build running, offer each check to
  the student (it runs as Step 6 says) and fill in each waiting MANIFEST.md cell (Step 7).

## Step 2: Pick the mode

- "Walk me through HW2", "next", "3c": the walk-through (Step 3).
- "Quiz me on the true or false": the quiz (Step 4).
- A question, a screenshot, "explain", "be even clearer": an answer, and a patch when it shows a
  gap (Step 5). On the cram night a question runs Step 5 too (`08-practice` step 8).
- "The solutions are out": Step 6.
- A question about a mock's part. A mock just taken: record the attempt first (`08-practice` step
  8.2), which opens its key. When the student wants it walked through before naming the misses,
  record `misses: from the walk-through`, and replace that with the misses from the log's What went
  wrong column once the walk-through ends, before step 8.3. An untaken one: one line of pushback
  (answering it spends the rehearsal); asked again, the method from the notes, cited, never worked
  on the mock's numbers: its key, and the reference run on its instance, stay closed until the
  attempt.

A question asked inside a walk-through or a quiz is Step 5's: answer it in place, then hold. Don't
post the next part until the student is done asking (A1.C20).

## Step 3: The walk-through

### The answer source

Settle it before the first part:

- A taken mock: its key, `practice/mock-<slug>-key.md`. An untaken mock is never walked through:
  it is a timed rehearsal (`08-practice` step 8.1).
- A set whose official solutions are extracted (MANIFEST.md marks their file `Answers: yes`, with
  `solutions to <doc>` in its Notes): the `Solution [` line under each part's block in
  `_build/extract/`.
- Any other set, with a checker: its values from the reference, before the first part (hard rule 3),
  once `selftest.py` prints `ALL PASS` (`05-verify` step 1) and no build runs (Step 1). Copy
  `<skill>/templates/verify-set-key.py` to `_build/verify/set_key.py` once, add the set's doc id to
  SETS, and give each part the reference computes a `value()`, every intermediate value on a line of
  its own, and a part whose answer no arithmetic on its numbers gives a `reasoned()` whose why names
  the method and where the notes state it, never the answer: the student sees the edit. `python3 -I
  _build/verify/set_key.py` must print SET OK for the set; it writes
  `practice/tutor/<doc>-values-key.md`. Run it again at each walk-through's start and after any
  reference change this session makes (no build running), since a reference fix (`05-verify` step 5)
  changes values: first `cp practice/tutor/<doc>-values-key.md
  practice/tutor/<doc>-values-key.prev.md`, then after the run read both with the Read tool and
  compare part by part, then delete the copy. Tell the student which parts the log grades whose
  value changed, by part id, and pose those parts again. A part the reference can't compute yet is a
  `pending()` call while the reference is extended as `08-practice` step 4.1 says (tested first on a
  worked example from a lecture or from a set MANIFEST.md marks `yes, attempted`, the self-test
  rerun: any other set's would show its official answer in the self-test's edit, so ask first, as
  Step 6 does), and once mocks exist `08-practice` step 4's rerun clause for a changed reference
  follows (items 2 and 4; a changed part of an untaken mock is logged, as it says): it isn't graded
  until its `value()` replaces the call, and the other parts go first. A set whose official
  solutions give final answers only gets values here too when the student's partial work needs its
  intermediate values.
- A part left to the notes (a proof, a justification), and every part when PLAN.md's Checker line
  says nothing is computable: the rule or method the notes state, cited, and the rubric.

A `reserved` set belongs to a later exam: never open it. Read an extract, a key or a values file
by its path with the Read tool, and search only extracts, with the Grep tool (a search over
`practice/` returns untaken mocks' key lines): their output stays folded on the student's screen,
where a shell command prints it; and say nothing of a part's answer before the student's
attempt. A failing self-test check prints the official answer it expected, so every `selftest.py`
run in this stage goes to a file, `mkdir -p practice/tutor && python3 -I _build/verify/selftest.py >
practice/tutor/selftest.txt 2>&1; echo "selftest exit $?"`, read the same way.

### Each part

One part at a time (FB-160):

1. Post the part: its label, its points and its text as the extract (or the mock) gives it, never
   its solution line. Then a **Read:** pointer to the published page: the subsection the backbone's
   How it's tested table gives the part, by the number and title the page shows, linked
   `<notes URL>#<id>` (plain-text notes: the section named as text). Never a source file: the
   student reads the page (A3.C2). Name where each symbol the part uses is defined, when that is
   elsewhere (A3.C13), and what to stop before when the subsection runs on into a later part's
   steps. A taken mock's part points to its `Topic:` sections and the key's citations.
2. Wait for the attempt.
3. Grade it (FB-161): the verdict and the reasoning separately, against the part's points and the
   official rubric when the solutions give one. Say what a full-mark reason contains (each
   mechanism named, the property shown holding where the other fails). Grade the arithmetic and
   the wording even when the verdict is right, in the course's words: when the student asks
   whether a term is the course's, search `notes/` and cite the line (A3.C9). Check partial work
   against every intermediate value of the answer source and list the steps left (FB-162). A half
   answer (a yes or no with no reason) goes back for its missing half.
4. Wrong or incomplete: hints, not the answer. Confirm what is right, then give the missing
   reasoning as numbered facts and leave the final sentence to the student (A3.C4). Wait again.
5. Advance only on the student's word ("next", "ok", a part's label). "If it's right, move on to
   (c)" means grade, then post (c) in the same reply.
6. Log the part (Step 7).

### Solutions, a reset, pushback

- Solutions on request (FB-163): one line of pushback naming what to try first ("try (c) with the
  values from (b) first?"); asked again, the full solution, every step, from the answer source.
  That holds for graded work not yet submitted too: the student decides.
- A reset ("pretend I haven't done 4c", "don't give me answers"): pose the part again from
  scratch, and give no answer until asked again. Log it.
- Pushback on an answer (FB-168): re-derive it, with the checker when it is computable, and
  concede an overstatement plainly ("my last answer overstated it").
- A claim about what the exam will ask cites hub CLAUDE.md's exam-format statement (hard rule 8,
  FB-012); with none recorded, say so. A logistics question (late policy, weights) is answered
  from its Logistics line, else "not recorded" (A3.C11).

## Step 4: The quiz

FB-165. The items come from sets whose answers the student may see once they answer:

- the true-or-false parts (their `**Shape:**` line says so) of a set whose official solutions are
  extracted (Step 3's second source);
- a taken mock's `Type: true-false` parts, and the Variants section once the mock whose key holds
  it is taken (`08-practice` step 4.3).

Never an untaken mock: answering its parts spends the rehearsal. Read STATUS for every set before
saying none is left (FB-008). With none left, say so. Fresh statements come only on the student's
go and never while a mock is untaken: a mock's true-or-false parts are variants of the same
statements (`08-practice` step 2), and the tutor can't see which. Each fresh verdict and witness
is cited from the notes (a computed witness from the checker) and logged as the tutor's own.

List the items in the log first (set and part ids, in order). Then per item:

1. The full statement as the set gives it, with no topic or section hint, and "True or false?
   Give your reasoning."
2. Wait for the answer.
3. Read that item's verdict and reasoning (Step 3's rule: the Read tool, after the attempt), then
   grade the verdict, then the reasoning against the source's reasoning points. Flag a right
   verdict for the wrong reason, and a broken witness even under a right verdict. A label where a
   mechanism belongs gets "the mechanism, not the label", and a retry is graded again (A3.C20).
4. The next item, unless the student asks something first (Step 2).

At each set's end, its score in the reply and the log: verdicts right, and reasoning right.

## Step 5: Questions and patches

1. Answer first (FB-164). A fact question gets a direct answer and a tiny sanity case ("3 bits
   give 0 to 7"); the answer text is short and exam-ready, in the course's words. "Be even
   clearer" gets a clearer version. A number or trace in an answer comes from the checker
   (`_build/verify/examples.out.md`, or the reference run on the example), never by hand.
2. Then search `notes/` for the point. When the notes don't say it where the student was reading, or
   say it unclearly there, offer the patch: the exact sentence (one short sentence at the point of
   confusion; the student's own insight is often the best one, A3.C16), the subsection, the line it
   follows or replaces, and for the sheet a one-line form when one fits (FB-166). When the notes
   already say it elsewhere, point there instead. While a mock is untaken, a sheet line goes where
   `08-practice` step 8 puts one: into the final sheet once its step 8.3 has built it, and until
   then into STATUS as a final-sheet item for 8.3 (bookkeeping, no writer). Otherwise it goes on the
   sheet `07-cheatsheet` built last; with no sheet yet the notes patch alone carries it, since 07
   picks from the notes.
3. On the student's yes, dispatch it at once (FB-169: the draft first, applied when told, never
   left for later). When it can't go yet (the hub isn't free, "One open patch" below, or an older
   pending line waits, which goes first), log it under `## Pending patches` (the approved text,
   where it goes, the date) for Step 1; while any line is `held: mock first` (Step 5.5.9), it is
   logged with that mark too. Text the student rewords is shown again before it goes.
4. One writer, from `<skill>/templates/agent-briefs.md`, section "Notes patch": load the delegation
   skill first. Check again that the hub is free (a tab opened before a build began learns of it
   here). The open line's own dispatches (a follow-up, an open held line's go, a RESTORE) skip that
   check: the hub was free when the line opened, and nothing since can wait on anything but this
   line. Commit before the spawn: mark the patch's line `dispatched <date>` (a new line when it
   never waited), its fields kept, and commit everything uncommitted, since the writer's worktree
   starts from the hub's last commit and a fresh session finds the patch by that line. Read STATUS
   and the log again: a `Build running` line or another open line that came meanwhile puts this line
   back as it was, committed, with no spawn. Else spawn it unnamed with `isolation: "worktree"` on
   the call, and tell the student to go on (FB-167), and while a mock is untaken, that the next mock
   waits until you say this patch is done (Step 5.5.9). While a mock is untaken, the change runs
   `08-practice`'s "Changing the notes or a sheet": its item 2 and the notes' rebuild by the writer,
   the rest at the merge (Step 5.5), item 1 included, since the hub without the patch is its
   baseline.
5. When the hand-back arrives, answer a waiting student first; it goes by its line's mark as it
   stands now ("One open patch"). One that arrives while a `Build running` line stands waits, its
   line still `dispatched`, for the build's end (Step 1). On a line with the `drop` field nothing
   merges: the worktree and the branch are removed as item 1 removes them, and the drop goes on as
   "One open patch" says. Otherwise:
   1. A report that isn't `done`, or a branch with no commit of its own (`git log <hub
      branch>..<branch>` prints nothing): nothing merges. Remove the worktree (as item 3 removes
      one, unless the Agent tool already did) and the branch (`git branch -D <branch>`: its work
      is redone, not kept), mark the line `held: <why>`, its fields kept, and tell the student
      why. On their go it is dispatched again, the brief changed where the report says what
      stopped it.
   2. `git diff --no-renames --name-status <hub branch>...<branch>` (three dots: the branch's own
      changes) lists only `M` lines (a patch adds and deletes no file) under `notes/`,
      `_build/frag/` and `cheatsheet/`, and `_build/notes.html`, and with a page a changed
      `notes/NN-*.md` comes with its `_build/frag/sec<N>.html` (`N` without a leading zero, as
      `assemble.py` maps it) and `_build/notes.html`; any other
      list (`practice/`, STATUS.md, a notes file alone) merges nothing, as in item 1. With no mock
      untaken, `git diff <hub branch>...<branch> -- notes/ _build/frag/ cheatsheet/` shows the
      change as drafted; while one is, the change waits for item 7, after the leak compare.
   3. Mark the line `merging <branch>`; at the patch's first merge, add `before <sha>`, the hub's
      head (`git rev-parse HEAD`), and while a mock is untaken run "Changing the notes or a sheet"
      item 1 now, its hit lines (part ids only) to `_build/logs/patch-baseline.txt`. Commit, so a
      fresh session can finish it, then `git merge --no-edit <branch>`. With the hub free at the
      dispatch, nothing else changes those files, so it merges clean. On a conflict anyway, or a
      merge git refuses: `git merge --abort` (when a merge is in progress); mark the line `held:
      conflict, <branch>`, dropping a `before` this merge added (a line with a `follow-up` field
      keeps its own), and commit; then remove the worktree and the branch as item 1 does, drop
      `<branch>` from the mark, and tell the student. The next first merge takes its baseline
      again. Then remove the worktree with the sandbox off, `git worktree remove --force <its
      path>` (the branch has merged, so only what the writer left uncommitted goes; a sandboxed
      remove can fail busy or leave it half removed, and a sandbox-off `git worktree prune` clears
      one `git worktree list` marks prunable, L46), and `git branch -d <branch>`.
   4. The checks follow what the stat named. Under `notes/` or `_build/frag/`: `06-site` step 3's
      fidelity compare (`_build/verify/fidelity.py`) of the patched section's fragment with its
      notes file, then `06-site` step 5, all of it, the browser check in the background so the next
      answer isn't held, its result and the patched section's screenshots seen. With plain-text
      notes, instead: the touched references checked by eye (`04-write` step 6), and
      `notes/combined.md` rebuilt whenever it exists. Under `cheatsheet/`: `07-cheatsheet`'s "After
      shipping", its audit and step 4 (the refit the main session's, Step 7), its republish waiting
      for item 8; a LaTeX sheet is checked as its `.tex` here (`08-practice`'s "Changing the notes
      or a sheet" item 3), and the student compiles it only at item 8, after the leak compare.
   5. While a mock is untaken: "Changing the notes or a sheet" item 4, the compare with the
      baseline in `_build/logs/patch-baseline.txt`.
   6. A check in item 4 that fails, a new leak hit in item 5, a wording cut or an audit finding is
      this patch's follow-up, whether or not a mock is untaken: a fix (new wording goes to the
      student first, as Step 5.2 offers it, but after a leak hit naming the subsection, never the
      line it replaces), or for a check's failure what the check reported and where. Put each fix on
      the line as it is approved, a field `fix "<text>"`, so a fresh session finds it. Wait for
      every result of items 4 and 5, the background browser check and the audit included, then
      dispatch one follow-up with every `fix` (Step 5.4), which become the line's field `follow-up
      "<the approved texts>"`; its hand-back runs this list again from item 1. While the line is
      `dispatched`, the main session changes nothing under `notes/`, `_build/frag/` or `cheatsheet/`
      (a refit waits for that hand-back), so the merge stays clean. Nothing is republished until
      items 4 and 5 pass.
   7. When item 2 showed nothing (a mock was untaken then), show the student the change now,
      `git diff <before> HEAD -- notes/ _build/frag/ cheatsheet/`, as that section's item 2 says
      (FB-137), even when that mock has since been taken.
   8. Republish what changed and is published (`06-site` step 6; the mock sheet as `07-cheatsheet`
      publishes it), and bump the page's version on its STATUS line: `v2` after its URL at the
      first republish, then `v3` and on; tell the student the version. While a mock is untaken, the
      rest of that section's item 5 too (a changed mock sheet logged, the cram order rechecked). A
      sheet the student has printed and that changed is printed again: tell them, and log it in
      STATUS until they say it is done. A changed LaTeX sheet is compiled by the student, printed
      or not: mark the line `waiting for the PDF` and commit; when they bring the PDF, commit it
      and check it as `08-practice` step 8.1 checks one, and a failing check (an overflow, text
      under the floor) is this patch's follow-up (item 6); item 9 follows its pass. Plain-text
      notes have no page: tell the student which sections to paste again, and log it in STATUS
      until they say it is done.
   9. Strike the line through, log it, and commit (Step 7). While a mock is untaken, tell the
      student it can start; with a pending line waiting, ask which goes first: the mock (mark each
      unmarked pending line `held: mock first`, and log a patch approved before the attempt the same
      way; `08-practice` step 8.5 clears the mark) or the next patch (the mock waits for it too).
      Then a recorded attempt whose mock still has its line in `practice/cram-order.md` goes first
      (`08-practice` step 8.3, with a sheet, then 8.4, which deletes the line); after it, the next
      pending patch, if any (Step 1).
6. A gap of the same kind in two places (a construction with no conclusion line, a cause stated
   after its effect) is a pattern, not one patch: log it under Patterns (Step 7) for `10-polish`
   and `12-retro`. That is how the notes' Conclusion lines started (A1.C23).

### One open patch

A patch is open from its dispatch until its line is struck through, its follow-ups included, but a
`held` line only while its change is in HEAD (the table below), and one is open at a time: every
copy of a fact can reach both the notes and the sheets, each notes patch rebuilds the one page, and
the leak baseline is the hub before the patch. A patch dispatches only when the hub is free: no
build runs (STATUS has no `Build running` line, Step 1), no other patch is open, and `08-practice`
steps 8.3 and 8.4 (the final sheet, built from the mock sheet, and the cram order) aren't under way,
their work committed (`git status` shows no change under `cheatsheet/` or to
`practice/cram-order.md`, the student's compiled LaTeX PDF committed first), and no attempt STATUS
records still has its mock's line in `practice/cram-order.md` (steps 8.3 and 8.4 end by deleting it,
with a sheet or without). In turn, while a patch is open, 8.3 doesn't start, no mock attempt begins
(8.1 shows a sheet the patch changed first), and nothing is republished but the patch's own result.
A mock the student took anyway is recorded (Step 2), and this line still finishes first: its own
dispatches skip the free check (Step 5.4), and step 8.3 waits for its strike-through.

A pending line carries a mark, and fields that, once set, stay on every later mark until the
line is struck through: `before <sha>`, the hub's head at the patch's first merge (Step 5.5.3),
and `follow-up "<text>"`, its latest follow-up's approved texts (Step 5.5.6); each `fix
"<text>"` stays until its follow-up is dispatched; `drop`, the
student's drop of a dispatched line (below), stays until its RESTORE follow-up goes. A line with a
`before` never rewrites the baseline file, and its change is in HEAD while `git diff --quiet
<before> HEAD -- notes/ _build/frag/ cheatsheet/` fails.

| Mark | Open | Where it goes on |
|---|---|---|
| none | no (a line whose change is in HEAD keeps its mark) | dispatched when the hub is free (Step 5.4) |
| `held: <why>` | while its change is in HEAD | a mark still naming a branch: its worktree and branch removed first (Step 5.5.1). On the student's go: an open one, Step 5.4 with its fields at once (its own dispatch); else Step 5.4 when the hub is free, or the mark cleared, its fields kept, to wait in order. Or dropped (below) |
| `dispatched <date>` | yes | in a fresh session, once `delegation-ledger watch` (the delegation skill) shows no live writer for it: with a `drop` field, Step 5.5's drop; else its worktree's branch with a commit of its own, Step 5.5.2; none, or no worktree (the Agent tool removes one that changed nothing), Step 5.5.1 |
| `merging <branch>` | yes | the branch not in HEAD (`git merge-base --is-ancestor <branch> HEAD`): Step 5.5.3's merge; in HEAD and still there: 5.5.3's removal; gone: Step 5.5.4 |
| `waiting for the PDF` | yes | the student's compiled PDF of the changed LaTeX sheet: Step 5.5.8's check, then Step 5.5.9 |
| struck through | no | nothing |

A hand-back whose line another session has moved on (`merging`, struck through) is only logged.

The student can drop any line not struck through. A struck-through one is undone only by a new
patch, its text approved again (Step 5.2), since a later patch or `08-practice` step 8.3's final
sheet may build on it. A line marked `dispatched` gets the field `drop` and waits for its writer's
hand-back, which merges nothing (Step 5.5), so no live writer loses its worktree and no earlier
writer's hand-back passes for a later one's; a line marked `merging` finishes its merge first (Step
5.5.3). Then a line whose change isn't in HEAD (it has no `before`, or `git diff --quiet <before>
HEAD -- notes/ _build/frag/ cheatsheet/` passes) is struck through as `dropped`, once any worktree
and branch its mark names are removed. One whose change is in HEAD gets a follow-up from the brief's
RESTORE form (its `drop` field cleared), which puts the files `git diff --name-only <before> HEAD --
notes/ _build/frag/ cheatsheet/` lists back as they stood at `before` (each one modified, never
added or deleted, Step 5.5.2; `--stat` would shorten a long path), checked like any follow-up. The
student sees `git diff <before> HEAD -- notes/ _build/frag/ cheatsheet/` first, but while a mock is
untaken its `--stat` only, and the follow-up is offered as "back to the text at `before`": the
change itself waits for Step 5.5.7.

## Step 6: Official solutions that arrive

During a build (Step 1) this waits for the build's end, as a line under the log's `##
Waiting checks`. Run `01-ingest` for the file (its MANIFEST.md row `Answers: yes`, `solutions to
<doc>` in Notes) and `02-extract` for the set again with its solutions, one agent, so each lands
under its part. Then `05-verify`, "Official solutions that arrive late", which adds them to the
self-test and diffs every answer against the notes and any `practice/tutor/` values file. That
check shows answers: the self-test's new lines show in the edit, a failing line prints both values,
and STATUS records what was wrong; so does 02's fix of a flagged solution line (its step 3.2), in
an edit. For a set the student hasn't attempted in full both wait, as a line under the log's `##
Waiting checks` (Step 7): ask, and run them on their go (the edits may show answers) or once every
part is attempted. The self-test's output goes to its file (Step 3), and STATUS records the verdict
by part only (`HW3: Q1a and Q2a match; Q2b differs, §2.3 fixed`). Show the student the table of
parts and whether each matched; the official answers themselves only for parts they have attempted,
or on request (Step 3). Each fix to the notes is offered and dispatched as Step 5 says. A set
already attempted in full gets `yes, attempted` in the new row at once (Step 7).

## Step 7: The log and the session's end

- `_build/logs/tutor.md` holds one section per walk-through or quiz, `## HW2 walk-through (<date>)`
  or `## Quiz: HW1, mock exam1-1 (<date>)`: its answer source, then a table, one row per part, `|
  Part | State | What went wrong | Patch |`, with State one of `right`, `partial`, `wrong`,
  `hinted`, `solution shown`, `reset`, `waiting` or `open`; a quiz's rows hold the verdict and the
  reasoning instead, and its scores close it. The section ends `Next: <part>`. The log ends with
  three sections, kept last: `## Patterns` (Step 5.6), `## Pending patches` (Step 5.3) and `##
  Waiting checks` (Step 6, and a MANIFEST.md cell held during the build: the set and what waits),
  each line dated. A pending line's marks are Step 5's "One open patch" table; a waiting line is
  struck through once it runs. The log names parts and what went wrong, never a part's answer (hard
  rule 4); a pending line keeps its approved text exactly.
- STATUS keeps one line, `Tutor: <set> <walk-through or quiz>, next <part>; <N> patches pending
  (_build/logs/tutor.md)`, current as each part closes. It is never the next-step line: routing
  and the cram night own that.
- When every part of a set has been attempted or its solution shown, in walk-throughs and quizzes
  together, the MANIFEST.md row whose Notes say `solutions to <that set>`, if there is one, gets
  `yes, attempted` in its Answers cell: the notes and sheets may quote it from then on
  (`04-write`). A check waiting on the set (Step 6) runs then. During a build the cell waits
  under `## Waiting checks` for the build's end (Step 1).
- This bookkeeping (the log, STATUS, MANIFEST.md's Answers cell) and `_build/verify/` are the
  main session's. Every change to the notes' or a sheet's text is a writer's (hard rule 9);
  refitting a sheet after one (`07-cheatsheet` step 4's `--fs`, a block moved between sides) is a
  build step the main session runs, and a wording cut or an audit finding goes to a writer like
  a patch.
- Every commit and handoff surveys the tree with `git diff --stat` and `git status` only and
  commits with a plain `git commit`, as `08-practice`'s opening says, whether or not a mock is
  untaken: `practice/tutor/` holds values of parts the student hasn't attempted. A handoff saves
  no memory, for the reason that opening gives.
- End each session with the handoff skill and a local commit (hard rule 10); during a build, the
  log's commit alone (Step 1).

## Done when

On demand, at each session's end: the log and STATUS's Tutor line (during a build, the log alone)
say where the student stopped and how many patches wait, each line marked as Step 5's "One open
patch" says; every merged patch passed its checks (`06-site` step 5 with its screenshots seen, or
with plain-text notes the references checked and `notes/combined.md` rebuilt; for a sheet,
`07-cheatsheet`'s), and while a mock was untaken `08-practice`'s leak compare and its item 5; what
was published is republished with its version on STATUS; a changed printed sheet, or a plain-text
notes section to paste again, is logged in STATUS until the student says it is done, and a changed
LaTeX sheet's line stays `waiting for the PDF` until its PDF passes; each merged, held or dropped
patch's worktree and branch are removed (a `dispatched` line's live writer is left alone); while a
mock is untaken, STATUS prints LEAK OK against the untaken mocks' keys after each write; a solutions
check runs only on the student's go or a fully attempted set; MANIFEST.md's Answers cells are
current, or during a build wait under `## Waiting checks`; it is handed off and committed with the
survey above, or during a build the log's commit alone (Step 1).
