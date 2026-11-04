# 12 Retro

Baseline as of 2026-10-20; changes only via `12-retro`.

After a round's exams, the retro turns what the student corrected into changes to this skill, so
the next course starts from them instead of finding them again (FB-010). A round is the exams
prepared together, one hub-exam each. Its number `<n>`: a `rounds/<n>/retro.md` in the private dir
not marked done is a retro under way, and this is its round; otherwise one more than the highest
round in `references/CHANGELOG.md` or among the private dir's `rounds/`.

It runs in one session in a checkout of the repository that ships this skill, never in a hub: it
reads the round's hubs and the student's transcripts, proposes changes, applies the ones the
student approves, and asks for the pull request. The rules ship in the repository; the evidence
(the student's words, the courses, the outcome) stays in the private dir, `~/scratch/exam-prep/`
(SKILL.md, "The private dir"), under `rounds/<n>/`. For the maintainer, the session is a dotclaude
lane named `exam-prep-retro-<n>`.

In this stage `<skill>` is the checkout's own `skills/exam-prep/`, as an absolute path: the retro
edits it, runs its scripts and hands it to its agents. Never the directory Claude Code printed when
the skill loaded: that is the installed copy, which for the maintainer links to another checkout,
so an edit there reaches the live skill and leaves the pull request without it.

The retro never writes a hub. Neither it nor its agents open anything under a hub's `practice/`
(keys, archived exams, tutor values), `_build/verify/` or `_build/mock-plan.md`, or search a hub's
root, and nothing it writes quotes an answer from a key. On a hub, git runs only in the main
session, for a tag's date (`git log -1 --format=%cI exam/<slug>`) and the two files step 1 names
(`git show exam/<slug>:STATUS.md` and `:PLAN.md`), never `-p`, a diff or any other `show`: a hub's
commits hold its keys. A hub's STATUS, PLAN.md, MANIFEST.md and `_build/logs/` hold what the retro
needs.

## Step 1: Check the inputs

A retro under way (its `retro.md` not marked done) goes on at the first step its log doesn't show
done.

- Every exam of the round is over: each hub's CLAUDE.md gives the date (a hub reopened since names
  the round's exam on its `Earlier exams:` line), or the student says so.
- The round's hubs, by path, from the student (a hub with its own conventions: its `exam-prep/`
  root). A hub whose two exams both fall in the round is two hub-exams, taken in exam order. No hub
  has a `Build running` line in STATUS, unless it was reopened since (that build is the next
  exam's, outside the window): a build or a pass is under way there, and the retro waits for it.
- The private dir, with `README.md` (an index of rounds), `evidence.md` (each source letter and
  what it names) and `denylist.txt`; create each that is missing with the Write tool, and seed a
  new `evidence.md` with A and B (the two runs the baseline came from) and H (the session that
  planned run B).
- Make `rounds/<n>/` with the Write tool (the Bash sandbox can't write outside the checkout), and
  start its log, `rounds/<n>/retro.md`: the round number, the hubs, and each step's end as it
  finishes, so a resume knows where the retro stopped.
- Give each hub-exam the next free letter, skipping C, G, K, L and S (an evidence id like `K10.C2`
  would read as a backlog, lesson, STYLE, CHASSIS or gotcha id), then `AA`, `AB` and on after Z,
  and log it. Add its row to `evidence.md`'s table of hub-exams (start it when there is none):
  `| <letter> | <hub-exam> | <hub path> | rounds/<n>/shards/<letter> | <since> | <until> |`, the
  window filled at step 2. A resume keeps the letters its log and the rows naming `rounds/<n>/`
  already give.
- The round's private terms in `denylist.txt` now, before anything is written in the checkout, each
  in full and in each spelling it may take ("Widgets 1001", "widgets1001"): course names and
  numbers, people's names, student ids, hub paths, Ed course ids. Never a bare number or a short
  word, which the skill's own text holds: a bare `170` would match `FB-170`.
- Whether each hub still holds the hub-exam's exam. A hub reopened since (`11-next-exam`) holds a
  later exam's PLAN and STATUS; the round's exam is its tag, `exam/<slug>`. For it, save those two
  files as the tag holds them, sandbox off (the sandbox can't write the private dir): `git -C <hub>
  show exam/<slug>:STATUS.md > ~/scratch/exam-prep/rounds/<n>/<letter>-STATUS.md`, and the same for
  `PLAN.md`; and log the tag's date (`git -C <hub> log -1 --format=%cI exam/<slug>`): what came
  after it belongs to the next exam.
- The backlog's `trying (round <n>)` rows (`references/backlog.md`): step 5 asks about each.

## Step 2: Condense the transcripts

The student's corrections live in the sessions' transcripts, and most never reach a hub file.
Claude Code keeps each session's transcript as `~/.claude/projects/<folder>/<session id>.jsonl`,
the folder named after the session's directory with each character but a letter or digit as `-`
(`ls ~/.claude/projects/ | grep -x -e '<the hub's path so changed>' -e '<the same>-.*'`: the folder
itself, and its worktrees' folders after it). A sibling directory can match too (`w1-old` beside
`w1`), so before step 3 read each shard's `Working directory` line and delete a shard from outside
the hub.

Each hub-exam's window, logged in `retro.md` and in its `evidence.md` row before condensing, where
the next retro finds it (a resume keeps a logged window):

- **Since:** the `until` of the hub's latest earlier row in `evidence.md`, an earlier round's or,
  for the second of a hub's two hub-exams, the first's: what came before it is read already. A hub
  with no earlier row, built this round, has none: its intake ran before its first commit, so every
  transcript in its folders counts.
- **Until:** on a hub reopened since, the tag's date step 1 logged: after it, the sessions are the
  next exam's, its mocks untaken. On any other, now (`date -Iseconds`).

Then, on the student's go, since the shards hold everything they typed, each hub-exam's
transcripts, every one in its folders, with its window (no `--since` when it has none):

```bash
python3 -I <skill>/scripts/condense.py --since <since> --until <until> ~/scratch/exam-prep/rounds/<n>/shards/<letter> <transcripts>
```

It keeps only the records inside the window, and a transcript with none there makes no shard; an
exit of 1 names on stderr each transcript it couldn't read whole. It runs outside the sandbox,
which can't write the private dir. If the auto-mode classifier refuses it, the student runs it
with `!` in front.

## Step 3: Harvest

Load the delegation skill first. Spawn one `researcher` per hub-exam, unnamed, from
`<skill>/templates/agent-briefs.md`, section "Retro harvest", all at once; a hub-exam whose shards
pass about 400 KB gets one per shard group of about that size, and only the first group's reads the
hub's records. Each reads its shards and, inside its window, its hub's records: the tutor log
(`_build/logs/tutor.md`, its tables and `## Patterns`), the polish logs (`_build/logs/polish-*.md`),
a source added's log (`_build/logs/source-*.md`), STATUS's judgment calls, PLAN.md's Decisions (a
default the student changed is a correction), the reopen log that opened the exam and the hub-local
edits. Its slots:

- the hub-exam, the hub's root, its shard folder (or the shard files of its group), whether it
  reads the records, and `<skill>`;
- the window, its since (or none) and its until; for a hub reopened since, the saved
  `<letter>-STATUS.md` and `-PLAN.md` in place of the hub's own;
- the reopen log that opened the exam, `_build/logs/reopen-<earlier slug>.md` (the tag on the
  `Reopened from` line of the PLAN.md the researcher reads, the saved one on a hub reopened since),
  or none on a hub built this round: a reopen log carries no date, and `reopen-<slug>.md`, written
  after the exam, is the next exam's;
- the hub-local edits: on a hub reopened since, the diff its reopen logged,
  `_build/logs/reopen-<slug>.diff`, whatever its date; on any other, or while that reopen waits for
  approval and has written no diff yet (`11-next-exam` step 5.2), a `diff` the researcher runs of
  the hub's copies and chassis against `<skill>/templates/`;
- on a hub with no since, the `reopen-*` files named for the exams before the one that opened this
  exam, and that reopen's diff (CLAUDE.md's `Earlier exams:` line orders them): no retro has read
  them. Never `reopen-<slug>.md`, nor `reopen-<slug>.diff` but as the hub-local edits. With a since,
  an older one holds an earlier exam's, which an earlier retro read.

Each spawn runs in the background and prints its output file. Log each one's `<letter><k>` and that
path in `retro.md` at once: a cleared session finds them there, and one whose file is gone (it lives
under `/tmp`), or holds no report once its agent has stopped (`save_handback.py` says `no
SubagentHandback report`), is spawned again. Save each report as it comes back, outside the sandbox,
by script (a researcher can't write files, and the report never passes through this conversation):

```bash
python3 -I <skill>/scripts/save_handback.py ~/scratch/exam-prep/rounds/<n>/reports <letter><k>=<the agent's output file>
```

`<k>` numbers the letter's reports from 1, so a correction's id is `<letter><k>.C<m>` and a
gotcha's `<letter><k>.G<m>`, the form the references already cite.

## Step 4: Ask the outcome

FB-190: neither past run recorded how the exam went or what paid off. One question round, each
hub-exam in it: the grade, or "not shared"; which products paid off (the notes page, the sheet,
the mocks, the cram order, the walk-throughs); which didn't; what they'd change. Write the answers
to `rounds/<n>/outcome.md`. Nothing of it goes in the repository but its evidence id, `<letter>.O`
(that hub-exam's outcome), on a change it drives.

## Step 5: Propose

1. **Dedupe.** Check each correction against `references/feedback-log.md`, `references/lessons.md`,
   `references/backlog.md`, `templates/STYLE.md` and `templates/CHASSIS.md`. A rule already there
   that the round didn't follow is a gap in the workflow that should have applied it, not a new
   rule: the fix goes where it should have fired. A correction tied to one course gets its general
   form (a search course's "expand nodes in order" becomes "the course's core procedure"), or is
   logged as dropped, with why. An item marked `undated` may be one an earlier round harvested:
   look for its quote in the earlier rounds' `reports/`, and drop it if it is there. A hunk of the
   hub-local edits that no CHANGELOG entry explains is an edit made in the hub (`11-next-exam` step
   5.2): a candidate, or a mistake to note.
2. **Candidates.** Each: what changes and where (its Home), the new or changed text exactly, its id
   (step 6.2), its evidence ids, and a rank, `high`, `medium` or `low` as the backlog's preface
   defines Sev. One correction is enough for a candidate; the student's approval decides.
3. **The backlog.** Each `trying (round <n>)` row: keep or drop, naming the round's hubs that had
   the trial and saying whether a correction this round touched it. A hub had it when the change was
   in what the hub used: a template change, when the hub's copy (`_build/<file>`) holds it, or, on a
   hub reopened since, whose copies the reopen replaced, when its `reopen-<slug>.diff` doesn't add
   it (a trial line on the diff's `+` side means the copy lacked it); a change to a workflow, brief
   or script, when the stage it changes ran after the student installed the skill with it (the
   stage's log date against the install, which the student confirms). A trial no hub had can carry
   on to the next round. Then the `open` rows offered for round `<n+1>`, by severity; a row whose
   item names a rule it would change (the backlog's Conflicts) says so, and is asked about first.
4. **The report.** Write it to `rounds/<n>/proposal.md`, then show it in the message, numbered
   (hard rule 11): the candidates, the backlog's keep, drop and carry, the rows offered, a
   recommendation, and the question: which to apply, which to put in the backlog instead, which
   trials to keep, which rows to try. Log the answer there.

## Step 6: Apply

Log each item in `retro.md` as it goes in, with the ids it took, so a resume knows which are in.

1. Exactly the approved items (FB-170 holds here too), each in its Home under `<skill>`: STYLE,
   CHASSIS, a workflow, a template, a brief, a script (with tests), SKILL.md, the references.
2. **Ids.** A new FB or L row takes the next free number in its section's block (the gap before
   the next block's first id), else the next after the highest id, placed in its section. K takes
   the next free number, S and C the next in their file. A change with no rule of its own (a
   workflow gap step 5.1 found, a script) carries the id of the rule it makes fire, and that row's
   Evidence cell gains the round's ids. No id is renumbered or reused, a dropped trial's
   included. A retired table row is struck through, `| ~~FB-073~~ | ~~<its rule>~~ | ... |`, its
   last cell ending `retired (round <n>): <why>`, naming the id that replaces it if one does; a
   retired S or C bullet is struck through the same way, its reason after it. Each citation of a
   retired id elsewhere in the skill is changed to its replacement or taken out, but in the
   CHANGELOG's earlier entries, which record what was. A Home that moved is updated (the feedback
   log's Home column).
3. **Header dates.** Each file the retro changes that has a `Baseline as of` line gets the retro's
   date in it (scripts and tests have none). `11-next-exam` compares a hub's copies with these
   dates.
4. **The CHANGELOG.** One entry in `references/CHANGELOG.md`, as its header describes.
5. **The backlog.** A kept row: `kept (round <n>)`. A dropped row: its change reverted, any rule it
   added retired as item 2 says (struck through, its id kept), never deleted; then `dropped (round
   <n>: <why>)`. A row carried on: `trying (round <n+1>)`, its change left in. A row picked for the
   next round: applied like any approved change, then `trying (round <n+1>)`. A candidate the
   student put in the backlog: a new row, `open`, with its evidence ids. Nothing else in the
   backlog is applied.
6. **A look change** regenerates `templates/chassis-shots/` as `templates/CHASSIS.md` says.
7. **Privacy and tests.** Add any private term found since step 1 to `denylist.txt`, as step 1
   says. Then run the skill's tests from the checkout's top level, outside the sandbox when it
   can't read the private dir:

   ```bash
   python3 -m unittest discover -s tests/exam_prep -t tests/exam_prep -v 2>&1 | grep -E 'test_no_denylisted_string|^Ran|^OK|^FAILED'
   ```

   Every test passes, and `test_no_denylisted_string` shows `ok`, not `skipped`.
8. **Review.** Fresh `reviewer`s, unnamed, from `<skill>/templates/agent-briefs.md`, section "Retro
   review", round after round until one finds only minor issues, every finding fixed. Its slots: the
   retro's round `<n>`, the review round `<r>`, the checkout's top level, `rounds/<n>/proposal.md`,
   the change as a file, and, for the privacy section, `denylist.txt` and `rounds/<n>/reports/`. The
   change: `git add -N` each new file, then `git diff "$(git merge-base origin/main HEAD)" --
   skills/exam-prep tests/exam_prep > "$TMPDIR/retro-<n>-r<r>.diff"`, its absolute path in the brief
   (from the merge base, so what the main branch gained since doesn't read as reverted). One
   reviewer of each round also gets the brief's privacy section, and reads every changed line for
   course content the denylist can't match: a paraphrased quote, an example only one course would
   give. Save each report as step 3 does, into `rounds/<n>/reviews/` as `r<r>-<k>`, and log each
   round's counts by severity in `retro.md`. After the last round's fixes, run item 7's tests again.

## Step 7: Ship

The texts written after step 6's checks carry only the round number and ids: the handoff's
STATUS, the commit message, the PR's title and body. Hand off and commit in the checkout as the
repository's own rules say. Then, before asking for the pull request, search everything it would
publish for the denylist's terms: each commit since the branch left the main branch, its message
and its change, and the PR's title and body, written to a file first:

```bash
sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^#/d' -e '/^$/d' ~/scratch/exam-prep/denylist.txt > "$TMPDIR/deny.txt"
[ -s "$TMPDIR/deny.txt" ] || echo 'no terms read: stop'
git log -p -U0 --format='%h%n%w(0,4,4)%B' origin/main..HEAD | grep -E '^(\+|    )' | grep -n -i -F -f "$TMPDIR/deny.txt"
grep -n -i -F -f "$TMPDIR/deny.txt" <the PR text's file>
```

It runs outside the sandbox when the sandbox can't read the private dir, as step 6.7 does: an empty
list matches nothing, so it stops unless the list has terms. The `sed` makes `grep` read the list as
the privacy test does: a blank line would match every line, and a comment or a trailing space would
be a term of its own. The `-U0`, the `--format` and the `grep -E` keep only what the branch writes,
its added lines and its messages (indented by `%w`): a context line or a commit's author line, which
names the maintainer, can't hit. No output means clean. A hit in the newest commit is amended; one
in an earlier commit is rewritten only on the maintainer's go, and nothing is pushed until the
search comes back clean. Then ask for the pull request as the repository's own rules say: nothing is
pushed without the maintainer's go. Mark the retro's log done, and add the round to the private
dir's README.

## Common mistakes

| Mistake | Instead |
|---|---|
| Running the retro in a hub | A session in the skill's checkout; the hubs are read, never written |
| Editing the skill where Claude Code loaded it | The checkout's `skills/exam-prep/`; the install changes only through the pull request |
| Condensing a reopened hub's folders whole | The window: from the last retro's until to the round's tag |
| Quoting the student in a rule, the CHANGELOG or a commit | A general rule and an evidence id; the quote stays private |
| A new rule for something an existing rule covers | Fix where that rule should have fired |
| Renumbering ids to close a gap, or deleting a dropped trial's rule | Ids are stable; a retired one is struck through |
| Applying a backlog row nobody picked | Only picked rows are tried, and only approved changes ship |
| Asking the outcome in the repo, or writing the grade there | `rounds/<n>/outcome.md`, private |
| Reading a reopened hub's STATUS for the round | The tag's copy, saved in step 1 |
| Searching only the staged change for private terms | Every commit on the branch, its message, and the PR's text |

## Done when

The round's transcripts are condensed within each hub-exam's window and harvested, the reports and
the outcome saved under `rounds/<n>/`, and each hub-exam's letter and window in `evidence.md`; the
proposal is answered; each approved item is applied and logged with its ids, header dates,
CHANGELOG entry and backlog status; a review round came back minor-only, the privacy read among
it, each round's counts logged; `tests/exam_prep` passes after the last fix, with the denylist
current and its privacy test run; it is committed and handed off; the branch's commits, their
messages and the PR's title and body hold no denylisted term; the pull request is asked for; the
log is marked done and the round is in the private dir's README.
