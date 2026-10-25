# Lanes: parallel sessions in worktrees

A lane is one git worktree on its own branch, beside the main checkout, with one series of
Claude sessions working in it. This doc holds the design and the reasons behind it.
`skills/lanes/SKILL.md` is the operating guide, and `skills/lanes/scripts/lane` is the CLI.

## Context

Hayden runs several Claude sessions on one repo (a private work repo, with hand-made sibling
worktrees as lanes). The incident that started this (2026-10-11), reconstructed from the
transcripts:

- Session A (one lane) wrote into the one shared, gitignored STATUS.md in the main checkout:
  "#110 ... another session is building it". That meant "a session Hayden will route it to".
- Session B was that intended owner. It read the line as being about someone else. It then
  matched the phrase to the wrong live session through ListAgents (session C, whose first prompt
  read "another session working on request #110") and deferred #110. A mirror flip ("another
  session's toolbar lane") happened earlier the same day.

So the root cause is not that a merged STATUS reached another lane. There are four causes:

1. Relative identity words were written into a file that many writers share.
2. An ownership claim was written by a session that was not the owner.
3. There is one shared "Next" block that every session overwrites.
4. Every session runs with cwd = the main checkout and reaches lanes by absolute path, so neither
   the harness nor the hooks know which lane a session belongs to.

Other recurring friction from the transcripts:

- Shared gates, ports and machine load collide.
- Version numbers race at rebase.
- Lane git commits need the sandbox off.
- Agent worktrees start from a stale base.
- Cleanup deletes the `work/` dirs other lanes depend on.

Research consensus: one worktree and one branch per lane, automated per-lane setup, merges
serialized through PRs, and status kept out of the merged tree. There is no standard for status.
The workable patterns are per-lane records keyed by branch or worktree, a record written by a
single writer, and records reconciled against `git worktree list` at read time.

Native `claude --worktree` puts lanes inside the repo. That conflicts with the work repo's "never
inside", and Codex sessions wouldn't get the convention.

**Hayden's calls** (2026-10-11):

- Records: CLI data in `<git-common-dir>/lanes/`; the lane's prose in its own `.lane/`, mirrored
  into the common dir (moved there after spike S2, below).
- A `lane` CLI creates sibling-dir worktrees.
- Enforcement is the skill and CLI plus two hooks.
- An optional **lead** session triages requests, proposes a lane split and, on approval, opens
  each lane as a real top-level session (`lane open`).
- Each lane merges its own PR (Hayden approves each merge), and the lead sets the order. After
  a merge, the lead runs the post-merge chain and `lane done` on a standing approval
  (2026-10-14, "Who asks what" below).
- `/pass` runs handoff, then `handoff-check`, then respawns the pane (PR 3; README "Pass" and
  `skills/pass/SKILL.md`).

## Invariants (the convention in five rules)

1. **Absolute identity.**
   - A lane's id is its worktree directory's basename. Each session belongs to exactly one lane,
     or to `main`, by its cwd.
   - Status text names lanes by id and requests by number, never "another/this/other session" or
     "my lane".
2. **One writer per record.** After creation, only the lane's own sessions write `<lane>/.lane/`
   and `lanes/<id>/`. The lead writes a record only when it creates the lane, plus its own
   backlog.
3. **Only the owner claims.** A request is owned only when a live lane's record claims it
   (`lane claim`). The answer to "who has #110?" comes only from `lane who 110`. It never comes
   from prose, ListAgents first prompts or tab titles. "Hayden routed #110 away from lane X" is
   recorded by lane X about itself.
4. **Derive, don't store.** `lane ls` derives branch, ahead/behind `origin/main`, PR state,
   session liveness, context and staleness live from git, gh, `~/.claude/sessions/*.json` and
   the auto-pass watcher's `ctx/<session>.json`.
5. **STATUS.md is project direction, not lane state.** In a repo with lanes, STATUS.md holds
   direction and a backlog keyed by request number. Each lane's next step lives in its own
   record.

## Communication model: what has to flow, and the one home for each

**Actors:** Hayden; the lead (optional); lanes (each a series of sessions over time); subagents
inside a lane; future sessions after `/clear` or `/pass`; outside collaborators (through the
tracker and PRs).

**What flows:** every fact belongs to one of these flows. Each flow gets exactly one home and one
writer, and every other place links to it.

| # | Flow (the question it answers) | Type | Home (lanes repo) | Writer | Lifetime |
|---|---|---|---|---|---|
| 1 | How do we work here? | Conventions | `CLAUDE.md`, skills, `docs/` | Hayden or a PR | durable |
| 2 | What is wanted, and why? | Intent | the request tracker (source of truth); `SPEC.md` for a large effort | Hayden or outside people | durable |
| 3 | What's queued and not started? | Backlog | the project `STATUS.md` Backlog, keyed by request #; it mirrors nothing the tracker already holds | main or lead | living |
| 4 | Who is doing what? | Registry | `lane.json` claims, viewed through `lane ls` / `lane who` (derived, never prose) | the owning lane via the CLI | living |
| 5 | What does this lane have to do? | Brief (down) | the lane record's opening section, from `templates/LANE.md`: goal, requests, expected files, overlaps with lanes by id, done criteria, constraints | the lead or creator, once | lane |
| 6 | How will we build it? | Design | the lane's `.lane/PLAN.md`; cross-lane design goes in the project `PLAN.md` or `docs/` | the lane, or the lead for cross-lane | lane / durable |
| 7 | What was decided, by whom, and on what evidence? | Rulings | the record's "Decisions": `Hayden picked chip row + preview (2026-10-11); evidence: <artifact path>, session <id>`. Promoted at merge into the PR body; also to memory if it constrains future work | the lane | lane, then durable |
| 8 | Where does it stand, and what's next? | State + handoff | the record's State and Next. A shift-change note in SBAR order: situation, background, assessment, next step | the lane | lane |
| 9 | What is this lane blocked on Hayden for? | Asks | the record's "Asks for Hayden" (a design pick, push or merge approval), shown by `lane asks` across lanes. Each ask has one owner, and the lead's stay in its window ("Who asks what") | the lane; cleared after Hayden answers | living |
| 10 | What did a delegate produce? | Report (up) | a subagent's report JSON (the delegation contract); a lane's hand-back is a passing `handoff-check` plus a State summary; the PR body to outsiders | the delegate | ephemeral, then PR |
| 11 | Proof behind a claim | Evidence | `.lane/artifacts/` (mocks, shots, gate logs), mirrored so it survives `worktree remove`; rulings point here | the lane | archived with the record |
| 12 | Shared machine resources | Env state | `lane.json` port, live sessions and `lane lock` holders (derived; a hand-kept "machine state" list drifts) | the CLI | live |
| 13 | Heads-up between peers | Message | SendMessage to the `uds:` address `lane addr <id>` prints, resolved before each send. A nudge only: anything that matters lands in a doc first, and a message never carries state or consent. A lane's `merged #N` to the lead is one: the lead proves the merge itself and acts on Hayden's standing approval | anyone | ephemeral |
| 14 | What did we learn? | Lessons | memory (Hayden's preferences, traps), `docs/` | any session | durable |
| 15 | What happened? | History | git, PRs, transcripts. Never copied into a doc; docs point to them by SHA, PR # or session id | n/a | durable |
| 16 | Tell the outside world | External | Hayden updates the tracker assignee from each lane's claims; PR comments | Hayden | durable |

**Rules that make it work:**

- **One home, one writer.** Every other place links. No doc carries an owner column, because
  ownership lives only in claims.
- **Lifetime decides the home.** Ephemeral (messages, live env) never holds state. Living
  (backlog, registry, state, asks) is overwritten in place. Durable (conventions, rulings,
  lessons) is append-only or goes through a PR.
- **Promotion happens at fixed moments only:** at turn end, a message's content goes into the
  record; at handoff, the lane's state and next step are refreshed; at merge, rulings go into the
  PR body or memory, the outcome becomes one backlog line, and the record is archived. Nothing
  moves up by copying prose.
- **Absolute names everywhere:** lane ids, request numbers, session ids, SHAs, dates.
- **Pointers over copies:** a ruling cites its artifact or session; a status cites a PR number,
  not its state.
- **Read order at session start:** identity (the hook), the lane record (Brief, Asks, Next), the
  project STATUS (direction, backlog), then anything else only when a pointer leads there.
- **A repo with no lanes is unchanged:** one STATUS.md (with Asks and Decisions sections) and one
  PLAN.md.

### Where each type lives, by level

One shared STATUS.md used to hold four kinds of facts at once: direction, per-lane state, machine
state and backlog. A repo PLAN.md hits the same multi-writer bug the moment two lanes each plan.
The fix is levels, each with exactly one owner. Lower levels never restate higher ones, and
higher levels link to lower ones through a derived view, not through copied prose.

| Level | Doc | Holds | Writer | Lifetime |
|---|---|---|---|---|
| Project (living) | `STATUS.md` in the main checkout | direction, backlog keyed by request #, merge order, blocked; a "Lanes: `lane ls`" line in place of lane prose | the main checkout or lead session, which adds one promotion line at each merge (lane id, PR, outcome) | living |
| Project (durable) | `PLAN.md` (cross-lane design only), `docs/`, `CLAUDE.md`, memory | conventions, cross-lane design, lessons | whoever, through a PR or memory | durable |
| Lane | `<lane>/.lane/STATUS.md` + `lanes/<id>/lane.json` | the lane's state, decisions with pointers, not-mine notes, next step | that lane's sessions | the lane's life, archived on `lane done` |
| Lane | `<lane>/.lane/PLAN.md` | the lane's working design (the plan-mode file is overwritten by the next plan) | that lane | same |
| Session | none (transcript; the session id in `lane.json`) | nothing written | none | none |

- **Derived views, never stored:** `lane ls` (the board) and `lane ls --requests` (request to
  lane, from claims).
- **Promotion at lane close:** a decision future work needs goes to memory or a committed doc,
  inside the lane's PR; the outcome goes up as one line in the project STATUS; the rest is
  archived with the record.
- **The lead's commits ride a lane PR.** The lead commits the project STATUS on its own branch,
  named on the STATUS's `Lead branch:` line, and opens no STATUS-only PR. The lane next in
  merge order carries those commits in before each push and before ready (`skills/lanes/SKILL.md`,
  Lifecycle step 6). The carry used to wait for ready, but #108, #111, #113 and #115 each went
  ready and merged within 5 s, so the lead's notes missed main four times. One carrier, not
  every lane (Hayden, 2026-10-17): two lanes holding two snapshots of the lead's file conflict
  once the second merges main, while an out-of-order merge only delays the notes one PR.
- **A copy for STATUS.md, a diff for PLAN.md.** STATUS.md is the lead's alone, so its copy is
  right whatever the lane holds, and a copy can't conflict, even in a lane behind main. PLAN.md
  has other writers whose edits a copy would undo, so it takes the lead's diff, from the sha the
  last carry names: a second diff from `origin/main` no longer applies on top of the first
  (`.lane/artifacts/carry-sim.txt` in lead-chain's closed record). `git apply -3` merges a
  change main and the lead both hold, and the ancestor check, run before every carry
  (`origin/main` inside the lead's branch), keeps the lead's files from undoing what main
  gained since the lead last merged it. So the lead never amends or rebases its branch: on
  2026-10-17 it amended a commit lead-chain had just carried, and the next carry's base was
  left off the branch, alive only in the reflog until git expires it.
- **The lead keeps its STATUS.md whole when it merges main**, conflict or not. Main holds
  older carries of it. If the lead deletes a line after a carry, the lead's side shows no change
  against the merge base while main's shows the line added, so a clean merge brings the line
  back. The lead still reads main's side first and adds back by hand any line that isn't a
  carry (a lane's backlog line from before the `Lead branch:` line existed). From then on a
  lane sends such items to the lead instead of editing STATUS.md: the next carry's copy would
  erase them. PLAN.md, with other writers, merges as usual, and the lead deletes again a line
  it removed since its last carry: an accepted manual step, since the lead rarely edits it.
- `templates/STATUS.md` is the project level (Direction, Backlog, Lanes, Asks, Decisions,
  Blocked, Notes); `templates/LANE.md` is the lane level, and a lane PLAN reuses
  `templates/PLAN.md`.
- The guard's relative-phrase lint covers every status level.

## Who asks what (one owner per ask)

Hayden reads the lead's window and every lane's. Both kept asking "ready to merge?", "go for
`lane done`?" and "approve the push?", and lanes repeated the lead's messages back to him. The
duplicate started in the docs: `lane done` runs only from the lead (a lane's session is refused),
yet the handoff skill told the lane to propose it, and the lanes skill told the lead to propose
it too. No doc said which window owns which ask.

**Hayden's call** (design B, 2026-10-14):

- Each ask has one owner. The lane owns its plan, push, draft PR, ready and merge. The lead owns
  new-lane tables, the merge order, the post-merge chain and `lane done`. The table is in
  `skills/lanes/SKILL.md`, "Who asks Hayden what", and the chain is "The lead", step 7.
- The lane that learns of a merge sends the lead `merged #N` and says nothing more about it to
  Hayden.
- The lead then runs the chain without asking: prove the merge, fetch, bring the main checkout
  to it, reinstall (settings.json and `~/.tmux.conf` copied first and diffed), check that no
  link points into a lane, add the backlog line, nudge the other lanes (an unmerged lane whose
  install the reinstall released hears so), and `lane done` once the hand-back gate passes. It reports one line, or the failed step.
- A lane with more PRs to come starts its Next with `Keep open: <why>`, and `lane done` refuses
  it. `--abandon` closes it anyway and stays an ask rule (Hayden, 2026-10-14).
- Lanes report their own state and asks, never the lead's messages.
- Before an act whose effect leaves its worktree (an install from the lane, a cap slot), and
  with anything the lead must run, a lane messages the lead, never Hayden (Hayden, 2026-10-19).
  The lead asks him only when the act needs his ok. On 2026-10-19 one lane told Hayden the lead
  had to run `setup.sh` without saying whether to approve it or pass it on, and another
  installed from its lane without telling the lead. "Draft opened" and "ready asked" need no
  message: `lane ls` shows both.

Why it works this way:

- **The lane's message is the event.** No session watches for merges, and none needs to: every
  merge so far went through a lane window. For #98 Hayden typed "merged" in lane-addr's window;
  for #99 the tab-bar lane ran `gh pr merge` itself. A merge made on GitHub and told to no
  session waits for the lead's next `lane ls`. With the lane's session gone, the lead runs the
  chain itself, and closes the lane only once the hand-back gate passes: a failing gate is then
  the lead's ask, since no lane is left to make it. A lane that wrote its after-merge handoff
  before its session ended passes, so it closes without one. With the session live, the lead
  asks the lane for its after-merge handoff first, since a lane that merged and is still writing
  `Keep open:` must not be closed under it. A merge watcher lost: one per ready PR has to be
  re-armed every 2 hours, and two that saw the same merge would run the chain twice (two
  reinstalls, two reports).
- **`handoff?` judges by the merge, not by session end** (Hayden, 2026-10-14). Every session
  ends after its own last write, so a flag keyed on session end lit after each `/pass` and on
  every merged lane whose session had exited, which made each such close an ask. A merged lane's
  record is judged against the PR's `mergedAt` instead: written after it, the lane did its
  after-merge handoff; older, the lane never saw the merge and may lack `Keep open:`. Every
  merged PR from the lane's branches counts (the checked-out one and lane.json's, which a switch
  for a follow-up PR leaves behind), even under a newer PR, and a fork's too: a lane may push to
  one, and a stranger's merge can only light the flag. An ended session lights it only when it
  started after the record's last write, so it never wrote it, and a newer commit still lights
  it. The merge and session checks allow 10 s (`CLOCK_SLACK`; the commit check keeps its 1 s):
  HAYPC's wall clock steps by about 5 s, and GitHub's clock is not the local one. On the 11
  lanes merged and closed by 2026-10-14, the old rule flagged all 11 and this one none; 4 of
  them wrote their after-merge record within 40 s of the merge, so a wider slack would cost
  asks.
- **What it can't tell.** A write after the merge is taken as the after-merge handoff, so a lane
  that never heard of a GitHub merge, then wrote a routine update and exited, passes; the lead's
  message to a live lane covers that window. Whatever can't be read (gh, a `mergedAt`, a session
  stamp, the last commit) leaves the flag on, so an offline or sandboxed `lane ls` shows it on
  every lane: judge the gate from a bare one. Once `ls`'s one gh call returns its full 200 PRs,
  a lane older than the oldest of them (or within 10 s of it, for the clocks), adopted, made with
  `new --reuse-branch`, or switched off lane.json's branch may have a PR older than the oldest,
  which the list cut. For just those lanes `ls` also asks gh once per branch
  (`gh pr list --head <branch> --state merged`); a call that can't answer, or returns 200 PRs
  too, keeps the flag on. Only two branches are judged, the checked-out one (or, detached
  mid-rebase, the one being rebased) and lane.json's: a merge from a third branch the lane passed
  through is missed. A session that ends with no SessionEnd stamp is skipped, as a live one is;
  for a merged lane the `mergedAt` check still catches the merge it never recorded.
- **A nudge, never consent** (flow 13). `merged #N` says only when to look. The consent is the
  standing approval written here; the lead proves the merge with `gh pr view` before it acts,
  and `lane done` checks it again (a merged PR whose head is the tip, or the tip in the base).
- **A scoped exception to "confirm before deleting"**, which CLAUDE.md names. `lane done`
  refuses an unmerged branch, a dirty worktree, links into the lane and a `Keep open:` lane,
  archives the record before the remove, and never passes `--force` or `-D` (a killed trial's
  leftover registration goes by its gitdir text, never by path: the `lane trial` section). The approval
  covers `lane done` after a merge only; `--abandon` still asks.
- **`lane done` reads `Keep open:` itself.** `handoff-check --closing` fails on the line too,
  but `done` runs it only when there is something to end, so a kept lane whose session had
  exited would have closed. `done` reads the record (bounded, as `ls` does) on every run while
  the worktree exists. The flag goes on one line (a bullet may wrap, indented), and any item in
  Next that starts with `Keep open:` counts, not only the first: a false hit holds a close,
  while a miss ends a lane with work left. `lanelib.first_item` skips the line, so the step
  `/pass` resumes with (and reads the approval marker from) is the one after it.
- **The backlog line moved to the lead.** The lead owns the project STATUS, so the one line at
  merge is a step of its chain, not the lane's.

### How to ask (the ask check)

Lane json-depth's asks (2026-10-19) repeated an agent's claims unchecked, named lane chrome-ttl's
file without the lane, grew past the brief and named functions Hayden had never seen. A checklist
the lead sent at the moment of the ask fixed the next rounds; the memory lines saying the same
had been in context all along. **Hayden's call:** a PreToolUse hook on AskUserQuestion, in every
session, denies only a risky ask, once, with the checklist as the reason. The list is in
`skills/lanes/SKILL.md`, "Who asks Hayden what"; the rules are in README's `ask-check.sh` entry.

For the lane rule, a live lane's files are its branch's three-dot diff from the base plus the
path-like entries of its brief's Expected files line. Uncommitted work is left out: lanes start
in plan mode, which can't edit, and they commit per step. Across 32 closed lanes the first commit
came a median 44 minutes after the lane opened, so the Expected line is what covers a set of lanes
opened together; it named a median 62% of the files each lane merged (outside `tests/`,
STATUS.md and README.md, which the rule skips).

## One lead per main checkout (lane two-sessions, 2026-10-14)

The night capella-studio got its first lanes, its main checkout held two live sessions. The lead,
in `main:@3`, had started at 21:05 and ran every `lane new`, `open` and `adopt`. A stray,
in `main:@2`, had been resumed at 20:16 and never acted as lead. `lane addr lead` refused ("2 live
sessions in the main checkout"), so no lane could send `merged #N`. The tab bar named both tabs
`lead`, since it classifies a window by its pane's directory. The fix that night was by hand: each
lane was told to pick `main:@3` from the refusal.

Hayden's rule: **the lead is the last main-checkout session to act as lead.** A bare `lane init`,
`new`, `adopt`, `open` (not `--print`) or `done` that succeeds records the Claude session above
it, and `lane lead` does so on purpose. The other two candidates lose on the one real case:

| Situation | Last to act | Oldest | None until Hayden picks |
|---|---|---|---|
| One session (the usual) | that one | that one | that one |
| capella-studio | `main:@3`, from its acts | `main:@2`, the stray (20:16) | each lane asks Hayden, every merge |
| The lead passes or clears | kept and healed: same pane, same server | lost: the pass makes the lead youngest | nothing to lose |
| A side chat in main | never leads: `ls` and `addr` are looks | leads if it started first | asks |
| Hayden starts a fresh lead by hand | `! lane lead` in it | never, while the old one lives | asks |
| tmux restarts | kept when the restored tab resumes the lead's session, after a pass too (the heal keeps the record's session id current); else none until the lead acts again | the restored order | asks |
| The lead resumes in another tab | kept and healed: the same session id | lost: the resume is youngest | asks |
| The lead is stopped (Ctrl+Z) | its resume if one runs; else none, naming the stopped lead to `fg`, even beside one side chat | the stopped one, which answers nothing | asks |

How it holds:
- **The record** sits beside the lanes config in the state dir (`Repo.lead_path`), which
  sandboxed Bash can't write, so no lane can make itself the lead. It names the session by pid
  and `procStart` (a /clear keeps both), plus the tmux socket, server pid, server start and pane
  from the claude process's own environment. The session file's `tmux` field names a tmux
  session, not a server, and pane ids restart at `%0` on every server, so it can't carry a pick.
- **Who counts.** The nearest Claude session above the command, found by its process chain as
  `lane done` finds it, and only when it is interactive, has a messaging socket, and launched in
  the main checkout outside any linked worktree. A lane's session, an agent worktree's, a
  `claude -p` or a background session never leads. A refused or failed act changes nothing.
  A session file that exists but won't read as a JSON object (junk, or nested too deep for
  Python's json) refuses a lead act when it may be an ancestor's: named for a pid in the chain,
  or not for a pid at all. One named for a present process (running or stopped) whose cwd is in
  the main checkout (or can't be read), or for the recorded lead's pid wherever it runs, makes
  the lead unknown: `lane addr lead` refuses and names the file, the board's footer names it
  too, and the heal moves nothing.
- **Liveness** (lane stopped-lead, 2026-10-17). On 2026-10-17 the lead (pid 1107) was stopped
  with Ctrl+Z while a resume of its session ran as pid 40133 in the same pane, and `lane addr
  lead` kept handing out 1107's socket: a stopped process's socket still accepts connections, so
  `merged #110` timed out twice. A session is now *present* while its pid runs with the
  `procStart` its file records, and *running* only while it isn't stopped (ps state `T`).
  Addresses, the pick and the footer count running sessions. `open` and the record seeding
  count present ones, so a stopped session still holds its lane.
- **The pick** (`lanelib.lead_of`), among running sessions: the record's pid and start match
  first (a /clear keeps both). Then the record's one continuation: a session with the record's
  session id (a resume, in the same tab, another tab, or the tab a tmux restart restores) or,
  once the recorded process is gone and no stopped lead remains, one in the record's pane on the
  record's server (the pass successor, since `respawn-pane -k` ends the old claude and keeps the
  pane; beside a lead that is only stopped, a claude in its pane is a fresh one). Only
  interactive sessions count: a background session has a socket too, but the lead is one Hayden
  talks to. Two continuations (a resume beside a fresh claude in the old pane, two resumes) are
  no pick. With none, one running session is the lead, unless the recorded lead is stopped: its
  process, or, once a heal moved the record to a resume that has since ended, the original
  holding its session id (Hayden's call, 2026-10-17): beside a lead that `fg` brings back, the
  one running is likely a side chat. Anything else is no pick. `lane addr lead` then refuses
  with each session's window, the way to pick, and a stopped lead's window to `fg` it in, and
  the lane tells Hayden once that #N merged, as with no lead at all.
- **The heal** (`lanelib.lead_relink`, lane stopped-lead). The pick alone loses a /pass once
  tmux restarts: the restored tab resumes the successor's session id, which the record never
  held, and the bar reads only the recorded pane. So the lane-identity hook, on SessionStart and
  Stop in the main checkout, rewrites the record when this session proves it continues the
  recorded lead. Every proof is about the session `lane lead` then records, the nearest above
  the hook, and its own session file must hold the event's id: before a claude's file is
  written, the nearest is whatever ran it (a `claude -p` run from a side chat), which holds
  another id. A /clear: the recorded process runs and is that session. A resume: the recorded
  process is gone or stopped, and the session id is the record's. A /pass: the recorded process
  is gone, this session runs in the recorded pane, and that pane's `pass-last` marker
  (pass-respawn writes it in the state dir just before the respawn) names the recorded session
  leaving it at most 120 s before this claude started. Either heals only as the pick's one
  continuation: beside another (a second resume, a successor in the recorded pane) neither does,
  and Hayden picks. A claude started by hand in the old tab has no marker; nor has a pass whose
  session left no reply text, which pass-respawn skips, so that pass relinks only by the pane
  rule until tmux restarts, and not at all while a stopped session still holds the lead's
  earlier id (the pane rule waits for it, since without a marker a successor can't be told from
  a claude typed in the pane). A running lead is never displaced. On proof the hook runs its
  sibling `lane lead --expect-sid <id>`, so every check under "Who counts" still applies to the
  very session proved, and a refusal is retried at the next Stop. Nearly every call costs one
  file read and one stat.
- **The board** (`lane ls`) adds a line under the table when the main checkout has two or more
  live sessions: each one's window, pid and state, the lead first, `no tmux` or `agent worktree`
  where it applies. With no running session picked and the recorded lead stopped, the line
  names the stopped lead's window, however few sessions run.
- **The bar** reads the same record. The window holding its pane, on the bar's own server
  (socket, pid and that pid's start), is `lead`; the main checkout's other tabs, a shell
  included, are `lead²`, `lead³` in bar order. With no pick, the first keeps `lead`. A new lead
  renames tabs and moves none. Once the heal rewrites the record, the bar follows a resume in
  another tab with no change of its own.

## Cross-lane checks (lane cross-lane, 2026-10-18)

Lanes plan alone, and nothing compared their work. On 2026-10-17 restore-effort's brief listed 7
files, and its PR #116 changed 14, two of them (`skills/lanes/scripts/lane` and `lanelib.py`)
done-rerun's. No brief named that overlap. Earlier, #93's "every setup.sh source is in
denyWrite" test failed on lane-close's new `install-state.py`: there was no textual conflict,
so only a merge with the suites run showed it. Two checks cover those cases. One is cheap and
runs on every `lane ls`; the other runs once per PR.

**The `overlap` flag.** `lane ls` flags two live lanes whose changed files meet, and names the
pair under the board:

```
overlap: cross-lane and tab-pin both change README.md
```

A lane's changed files are its commits since it left the base (`git diff <base>...<ref>`: three
dots, so main's later commits and a merged lane's work drop out) plus what is uncommitted in its
worktree (modified, staged and untracked). Both are read on each `ls`, never stored. A file a
lane's setup leaves untracked and unignored counts too, so it shows on every pair: ignore it in
the repo.

The uncommitted part is the first git `ls` runs inside a lane, sandbox-off, so it runs only past
these gates; a lane that fails one keeps its committed set, and `ls` says why:
- the lane passes `worktree_problem`, and the repo sets no `extensions.worktreeConfig`;
- no filter has a `clean` or `process` command configured: status re-hashes a stat-dirty file
  through the filter the lane picks by its own `.gitattributes`;
- `GIT_COMMON_DIR` pins the config to the common dir; `GIT_OPTIONAL_LOCKS=0` leaves the index
  unwritten (no `index.lock` under the lane's own commit, no `post-index-change` hook); every
  inherited `GIT_*` is dropped; `core.fsmonitor=false`; and `--ignore-submodules=all`.

The last gate has a wider reason. A status that looks into a submodule runs a child status
there, which reads the submodule's own config, and a sandboxed session can write that config.
So every sandbox-off status in a checkout now skips submodule contents: `lane done`'s
`removable()` (`=all`, its submodule refusal stays), `handoff-check` and `delegation-ledger`'s
hook (`=dirty`, which still reports a moved gitlink), each with optional locks off and
`core.fsmonitor=false` (a relative fsmonitor command resolves inside the checkout; `done` sets
it for every git it runs), and the ledger's hook,
like `ls` and `done`, runs no status in a repo whose own config sets `extensions.worktreeConfig`
(`audit` names those runs unchecked). A configured filter driver (a program the user
installed, such as git-lfs) still runs on the files a checkout routes to it: turning it off
would make every file it tracks read as modified, so `done` would refuse every LFS lane. `ls`
alone skips the uncommitted read then, since it can afford to.

**`lane trial`.** Before a lane asks Hayden for ready, it runs
`lane trial --run "<suite>" --run "<suite>" ...`, sandboxed. It refuses to run anywhere else
(a plain shell): it removes its scratch trees by path, which is safe only where the sandbox
bounds what a symlink swapped in for a tree could make git delete, and its suites inherit the
sandbox. Before it waits for the lock, it also refuses a bad link path, a link under another one,
and a link the lane lacks (step 3).

1. It takes the `suite` lock for the whole run. One name for every trial: a trial clears its
   lane's leftover trees under that lock, so a second trial under another lock could remove a
   live tree. Locks are re-entrant for descendants (`LANE_LOCKS_HELD`, keyed by repo), so a
   `--run` that wraps its suite in `lane lock suite` runs under the trial's hold instead of
   waiting on it forever. A trial itself refuses to start under a `suite` hold: its sweep would
   take the outer trial's tree for a leftover.
2. It builds the merge with no worktree: from the lane's HEAD, `git merge-tree --write-tree`
   merges the base, then each other live lane's head by id, and `git commit-tree` turns each
   clean result into a dangling commit (a fixed `lane-trial` identity, unsigned; no ref moves).
   When the lane's STATUS.md, else the base's (a lane that branched before the line), names the
   lead's branch (its `Lead branch:` line) and that branch holds one, every commit the trial
   merges or tries (this lane's HEAD, the base, each lane's head) first gets the lead branch's
   STATUS.md, as a carry would make it, and the report says so: after the merge order changes,
   lanes carry the lead's notes from different lead heads, and those carries always conflict. A
   conflict with the base aborts ("merge origin/main into the lane first"), except such a clash
   of carries in STATUS.md. A lane that conflicts is skipped, and the report says whose conflict
   it is. Merges decide, in order. When the other lane conflicts with the base alone, it needs to
   merge the base before a trial can tell whether it conflicts with this lane: it is untried, not
   a failure, so it never fails the trial, and the report's last line names it (`lane trial: lane
   X untried (it conflicts with origin/main)`). This lane's ask for ready goes ahead. Every other
   conflict fails the trial. Else, with no lane merged before it, or when
   it conflicts with the baseline (this lane's HEAD plus the base, which merges cleanly with
   it), it is this lane's. Else it is between that lane and lanes merged before it: the report
   names each of them it conflicts with by itself, or the merge of them all when none does
   alone, and the `lane trial <id>` that tries it with this lane alone. Not paths, since git
   conflicts by hunk, not by file (and names a renamed file by its new path); not a merge with
   this lane's HEAD, which may hold the base already and then conflicts wherever the base does.
   A lane behind the base that also conflicts with this lane gets the base's verdict only; its
   own trial, once it merges the base, finds the rest. Other lanes' uncommitted work isn't in
   the merge.
3. It checks the merge out in a fresh `mkdtemp` tree in the lane's `.lane-trial/`, named by
   repo key and lane id (`<lane>/.lane-trial/lane-trial-<key>-<id>-XXXXXXXX/tree`), never under
   the temp dir: the sandbox's temp root is a policy root, where some suites fail on any tree
   (SandboxReality, the subagent-policy cases). The first trial makes `.lane-trial/` with a
   `.gitignore` of `*` in it, so neither it nor the trees show in the lane's git status; a
   symlink there is refused. The lead notes' scratch index stays in the temp dir, since no suite
   runs there. The tree then gets set up as the lane's own tests ran: the lane's gitignored files
   that its `.worktreeinclude` matches are copied in (from the lane, not main, so the suites see
   the lane's copies; git's names are read with `-z`, so a non-ASCII name is never quoted), and
   each path the config's `trial-link` (`lane init --trial-link node_modules,.venv`) or a
   `--link PATH` names is symlinked to the lane's own, by absolute path, unless the tree tracks
   that path. The links go in first, and no included file under a link is copied (the link
   brings it): a copy would make the link's dir and block it. Link paths are checked like
   `.worktreeinclude` entries (relative, no `..`). One under another is refused (the tree would
   make the outer path a dir for the inner link). One the lane lacks is refused too: unlinked, a
   suite that can't load fails alike on both runs, which step 5's same-way rule passes, so the
   trial would pass having tested nothing. A conflict line's "try it with this lane alone"
   command carries the run's `--link`s for the same reason. A link is
   no copy: a suite that writes through it writes the lane's files. Then each `--run` runs there
   as `sh -c`,
   streaming its output. One `--run` per suite: a chained `a && b` stops at the first failure,
   and `a; b` reports only the last exit.
4. A suite fails when it exits non-zero or prints a failing test id (unittest's `FAIL:` and
   `ERROR:` lines, pytest's `FAILED` and `ERROR`, never unittest's `FAILED (failures=N)`
   summary, and TAP's `not ok <n> - <name>` at any indent, which `node --test` prints into a
   pipe, as `not ok - <parent> > <name>`: no number, since a lane that adds a test shifts the
   numbers, and the names of the subtests that enclose it (node's `# Subtest:` lines at smaller
   indents), so two tests of one name under different parents stay apart; plain TAP with no
   Subtest lines gives `not ok - <name>`; a `# TODO` or `# SKIP` directive is no failure),
   whatever its exit code.
5. A failed suite reruns on the baseline (HEAD plus the base alone), in a tree at the same path
   set up the same way, so ids that embed the path match. It passes only when every id it
   failed on the merge also fails there and its exit is no worse (non-zero on the merge but zero
   on the baseline, or a signal on the merge only, is the merge's). One that printed no id on
   either run passes when both runs exit with the same code: it fails the same way on the
   baseline, so that failure isn't the merge's. Any other failure with no id to compare, or a
   run whose output was cut (a process it started kept the pipe 10 s past its exit), fails, to
   be judged by hand.
6. It exits 0 with no failing conflict and no failure of the merge's own, 1 otherwise, and 75
   when `--wait` runs out. When no other lane's work merges (none live, all already in, or all
   conflicting), the suites still run once, on this lane's HEAD plus the base; that tree is the
   baseline, so nothing reruns, and any failing suite exits 1 (`FAILED: N suite(s) fail on lane
   <id> plus origin/main`). A conflicted file whose name isn't UTF-8 stops the trial at once,
   naming the lane (or the base) it was merging: `lane trial <id> ...` with the other lanes'
   ids tries the rest.

Why the baseline: some tests fail on location alone. In a scratch tree of origin/main under the
temp dir (2026-10-18) tests/lanes and tests/pass passed. tests/setup failed three SandboxReality
subtests, since the sandbox protects only the checkouts it was started for; that test now skips
a checkout under the temp dir or a `.lane-trial/` dir. tests/delegation failed 12
subagent-policy cases, since the policy allows temp paths before it checks protected roots; the
tree left the temp dir (2026-10-24, lane trial-fix) so those no longer fail. The baseline stays
for the rest: it keeps working when a future test turns out to depend on its location, and it
tells a failure the base already has from the merge's.

Its limits: a test failing in both runs for different reasons hides a real break, and so does a
suite with no ids that fails the same way on both (exit 1 on both hides a second break the
merge adds, until the first is fixed); a runner with another output format can only be
compared by its exit code or by hand; a flaky test failing only on the merge reads as the
merge's. The number of tests run is never compared, so a fail-fast flag (pytest `-x`, unittest
`-f`) can stop both runs at a shared failure before the test the merge broke, and a merge that
drops a test package from discovery passes unseen. Node resolves a bare `require` up the parent
dirs, so a tree in `.lane-trial/` without the link still finds the lane's `node_modules`; the
link makes it the tree's own path, which tools that read `./node_modules` (its `.bin`) need. And
a trial killed partway (the Bash cap, a respawn) leaves its tree registered. The sandbox mounts
each registered worktree's admin dir in every command started after the tree exists, so a later
sandboxed run can't delete it. The next trial removes the files it can (in `.lane-trial/`, and
in the temp dir an older `lane` used) and names each registration it can't, which stays,
harmless, until `lane done` clears it; never a blanket `git worktree prune`. Neither that
message nor `--keep`'s offers a by-path `git worktree remove --force`: git resolves the path,
so a symlink swapped in for the tree points it at whatever worktree the link names, and it
deletes that worktree whole (probed on git 2.43, 2026-10-24). `lane done` clears such a
registration, which removing the lane would otherwise leave stale. It runs sandbox-off, and a
process the lane left could swap the tree for a symlink to another lane, so it never removes a
tree by its path: it finds the admin dirs under `<common>/worktrees/` (real dirs, not links)
whose `gitdir` file reads, as text, a tree with this lane's trial name in the lane's
`.lane-trial/` or in a temp dir an older `lane` used, and removes just those dirs, each by name
under its parent opened with `O_NOFOLLOW` (sandboxed Bash can write the common dir), once the
lane's files are gone (`done` removes them itself, below), or at once when the lane was removed
by hand. One it can't remove it names as left in place, with no path to remove by hand: run
sandbox-off, that would follow whatever link made the removal fail. No message of `lane` ever
offers a by-path removal that can recurse or follow a link (a test pins it); the one removal
it names, `unlink` for a `.lane-trial` that is a symlink, does neither. The trial adds its trees with `worktree.useRelativePaths=false`, so that text is
always an absolute path.

## Bug reports from other repos (lane bug-route, 2026-10-18)

On 2026-10-18 a session in `~/code/karaoke` had a bug report for dotclaude's tooling (lane
pass-bg's) and no way to reach the lead. `lane addr` reads the repo from its cwd, so it refused
outside dotclaude, and a ListAgents name is a tab title that changes most turns. The report got
through only because Hayden said where to send it.

Hayden picked option A. `lane addr --repo PATH` looks in the lanes repo whose main checkout
holds PATH instead of the cwd's, from any dir. One line in the global CLAUDE.md sends a
dotclaude bug met in any other repo to what `lane addr --repo ~/dotclaude lead` prints, and to
Hayden when it refuses. The lead logs each report as a backlog line (SKILL.md, The lead, step
9). A durable inbox lost: it is a new sandbox-off write path, and every report in it would
reach the lead's context at session start as untrusted text. Revisit it only if a report gets
lost.

The flag raises one trust question. The excluded-command guard judges the call's cwd, never
PATH, and a sandboxed session can write PATH's git config (one rooted at `$HOME` can write every
repo's under it). So `handed_repo` runs its one git there, a `rev-parse` that reads no index,
object or hook, the way `git_read` and `commits_past` run theirs (`lanelib.HANDED_ENV`):
- no inherited `GIT_*`: a `GIT_DIR` would redirect it, and the sandbox's exported
  `safe.directory=*` would switch off git's ownership check;
- no system or global config, and no transport;
- a 10 s cap, since a FIFO include holds git at its open.

The git binary is PATH's, as for `commits_past` and every other git `lane` runs: the guard's
rule 2 judged PATH for the call (`git_read` alone insists on a system git, since PATH's may be
one its scan just found writable). Git's ownership check stays on, so a repo another user owns
is refused. PATH must also sit in the main checkout of the repo git names: the nearest `.git`
at or above it must be that repo's git dir itself, as the guard requires of a cwd. Else a
planted `.git` file, `commondir` or `core.worktree` would send the report to another repo's
lead, an enclosing lanes repo's included. A lane's worktree doesn't count either: its path
comes from a `lane.json` that sandboxed Bash can write (lane ids still resolve through the main
checkout). Past that, nothing needs a new check. A repo counts only when its config sits in the
state dir, which only a bare `lane init` writes, and its lead comes from the lead record beside
that config.

## Layout

Claude Code treats every path under `.git/` as a "sensitive file", so Edit/Write there always
prompts and no allow rule lifts it (spike S2). The prose therefore lives in the lane's own
worktree, in the session's cwd, where the Edit tool works with no prompt. The CLI-owned data
stays in the common dir, which sandboxed Bash can write (S1).

```
<lane worktree>/.lane/          hidden by `/.lane/` in the shared <common-dir>/info/exclude (no repo footprint)
  STATUS.md                     the lane's prose (templates/LANE.md): Brief, State, Decisions, Asks for Hayden, Not mine, Next
  PLAN.md                       the lane's working design (optional)
  artifacts/                    evidence that rulings point at (mocks, shots, gate logs)

$XDG_STATE_HOME/dotclaude/lanes/<repo>-<hash>.toml
                                the config: root, setup cmd, port range, live-lane cap, base
                                (<remote>/<branch>, default origin/main), locks, autopass,
                                model, effort; written only by a bare `lane init`
$XDG_STATE_HOME/dotclaude/lanes/<repo>-<hash>.lead.json
                                the lead record: the main-checkout session that last acted as
                                lead, written only by bare `lane` commands ("One lead per main
                                checkout")
$XDG_STATE_HOME/dotclaude/lanes/<repo>-<hash>.closing/<id>.json
                                the pane shells a `lane done` of lane <id> proved the lane's,
                                kept for a rerun until the close completes

<common-dir>/lanes/             CLI-owned; written by `lane` and by hooks, never by the Edit tool
  .lock                         flock for every CLI write (claims are atomic)
  _locks/<name>                 one flock per shared gate (`lane lock`), holding the holder line
  <id>/lane.json                id, branch, path, base_sha, port, claims[], state, sessions[], created/updated, opened
  <id>/mirror/                  copy of <lane>/.lane/, refreshed by a Stop and SessionEnd hook, so a raw
                                `git worktree remove` (which deletes ignored files) loses nothing
  _closed/<id>-<date>/          lane.json + .lane/ archived on `lane done`
```

JSON for the fields the CLI owns (models alter JSON less than Markdown), Markdown for the prose.

A repo set up before the config moved (it held `<common-dir>/lanes/config.toml`) reads as plain:
the hooks go quiet and every `lane` subcommand says to re-run `lane init`. The old file is never
read, since sandboxed Bash could have written it: run `lane init` with the flags you want, without
copying its `setup` or `root` unread, then delete it. Requests a lane claims are short tokens
(`42`, `#42`, `ABC-7`); `claim` refuses anything else, since a record holding it is left out.

## Spike results (Step 0)

Run 2026-10-11 on Claude Code 2.1.296, with `claude -p` in a scratch repo with a sibling lane.

- **S1, sandbox:** a session rooted in the lane needs **no** `allowWrite` rule. Sandboxed Bash can
  `git commit` and write `<common-dir>/lanes/`, while Claude Code itself keeps `.git/hooks`
  ("Read-only file system") and `.git/config` (lock refused) unwritable. The old "lane commits
  need the sandbox off" came from sessions rooted in the main checkout.
- **S2, Edit/Write under `.git/`:** always "a sensitive file", prompting even with an
  `Edit(//abs/.git/lanes/**)` or `Edit(**/.git/lanes/**)` allow rule (Write rules don't apply to
  file checks at all). Hence the in-lane `.lane/` above. A Write to `<lane>/.lane/STATUS.md` in
  acceptEdits mode succeeds with no prompt, and the shared `info/exclude` hides it
  (`git status --ignored` shows `!! .lane/`).
- **S3, `excludedCommands`:** `lane new` fetches and `lane ls` asks gh for PR state, and both
  need the credential the sandbox hides; `ls`, `open`, `done`, `addr` and `lead` also need to
  see other processes. PR 1 excluded `lane *`. PR 2 narrowed it to `lane init`, `new`, `adopt`, `ls`,
  `open` and `done` (lane-addr added `addr`, and two-sessions `lead`), each by name, because `lane lock -- <cmd>` must stay sandboxed: under
  `lane *`, any command wrapped in it ran sandbox-off without the `dangerouslyDisableSandbox`
  flag the delete guard checks. `whoami`, `claim`, `release`, `who`, `note`, `asks` and `lock`
  touch only `<common-dir>/lanes/` and the lane's `.lane/`, which a lane-rooted sandbox can
  write (S1). A sandboxed (piped) `ls` says what it skipped; `new`, `open`, `done`, `addr` and `lead` refuse.
  `trial` must stay sandboxed too, and refuses to run anywhere else (the `lane trial` section).
  `new` and `adopt` also run the config's `setup` command through a shell, sandbox-off, and
  `new` makes its worktree under the config's `root`. So the config lives in the state dir, not
  the common dir: sandboxed Bash can read it but not write it, and only a bare `lane init`
  (whose flags the permission gate sees) writes it. Everything else the sandbox-off subcommands
  and the hooks act on is sandbox-writable (every `lane.json`, the refs, the main checkout,
  `.worktreeinclude`), so it is checked before use:
  - A `lane.json` must pass `lanelib.record_problem` (its id is its dir's name, its branch can't
    be read as a git option, its path is absolute, and so on), or every command and hook leaves
    it out, and `lane ls` names it. While one is left out, what it holds can't be told: `new`,
    `adopt` and `claim` refuse to hand out a claim, port or cap slot, and a checkout outside
    the main one that matches no record can't take itself for unregistered (`handoff-check`
    fails, `pass-respawn` refuses). Two records sharing a path only count there when the
    path is that checkout's.
  - A lane's path must be a real worktree of this repo, outside the main checkout and any other
    lane, before `open` starts `claude` there, the setup runs there, files are copied there, or
    `done` archives and removes it.
  - `addr --repo`'s path is one the guard never judged, so its one git runs with
    `lanelib.HANDED_ENV` and git's ownership check, and the path must sit in the main checkout
    of the repo git names ("Bug reports from other repos").
  - `new` branches from the commit `ls-remote` reports for the base after a fetch, never from a
    local ref, and refuses when the fetch fails. Other git calls get refs in full
    (`refs/heads/<branch>`, `refs/remotes/origin/main`) after `--end-of-options`.
  - `new` and `adopt` copy `.worktreeinclude` matches by directory fd with `O_NOFOLLOW` on both
    sides. A symlink is copied as a link (a relative one made absolute), never read through, so
    the sandbox's read deny still holds at its target; anything not a regular file is skipped.
  - A symlinked `lanes/`, `lanes/<id>`, mirror or `info/exclude` is refused.
  - `done` and the mirror hook remove, rename and write only by name under a directory fd,
    reached from the main checkout with `O_NOFOLLOW` at each step, and copy a record by fd at
    every level. Both run sandbox-off over dirs a lane's sandbox can write (its worktree and
    record, `<common-dir>/worktrees/` and `lanes/`), where a check of a path can't hold until
    its use. No message offers a removal by path (a test scans them).
  - `done` signals a process only on kernel facts (`/proc`) and Claude Code's own files (session
    files, transcripts), never on `lane.json` (the pieces, `lane done`).
  PR 3 adds `pass-respawn` to `excludedCommands` (bare and with arguments): it needs the tmux socket and
  the session's processes, and its docstring lists what it reads and why each input is safe.
  The excluded-command inventory (2026-10-13, `tests/delegation/command_inventory.py`) adds three
  asks: `lane init --setup` names the command each new lane runs, `lane init --root` moves where
  lanes live, and `lane done --abandon` closes unmerged work. The rest of `lane` asks nothing.
  The excluded-command guard (docs/delegation.md) then let `ls`, `new`, `adopt`, `open`, `done`,
  `addr` and `lead` take allow rules, so the classifier never refuses them: an allow rule skips the
  classifier, and the guard checks each call's git config, PATH and cwd first. The three asks
  still win.
  A lane that installs from its worktree (`lane lock install -- ./setup.sh`) points the installed
  hooks, skills, agents and bin at files its own sandboxed Bash can write, so the install adds the
  lane's copies of the `~/dotclaude` paths to `denyWrite` (`merge-settings.py --checkout`); the
  lead's reinstall from `main` drops them. While that install is live, the lane's own sandboxed
  rebase, merge or switch that touches those paths fails or half-applies, as in `~/dotclaude`:
  run it sandbox-off, or after the reinstall.
- **S4, compaction:** a SessionStart hook matched on `compact` gets its `additionalContext` to
  the model after `/compact` (`/compact` piped into `claude -p --resume` triggers a real
  compaction). `lane-identity.sh` on `compact` is therefore the safety net for an unplanned
  auto-compact.
- **Session facts** for `handoff-check`: `~/.claude/sessions/<pid>.json` carries `sessionId`,
  `cwd`, `startedAt` (ms), `status`, `tmux` (`session:@window.%pane`) and
  `messagingSocketPath`. A session's own shell also has `$CLAUDE_CODE_SESSION_ID`. A file that
  won't read as a JSON object (read again once after 0.1 s, for a torn rewrite) and is named
  for a present pid (running or stopped), or for no pid, fails `handoff-check` unless a readable one names this
  session, and makes liveness unknown for `lane open` (which refuses) and `lane ls`. Where pids
  are visible, a dead pid's file is ruled out at once; sandboxed, every unreadable file counts.
- **Addressing** (lane lane-addr, 2026-10-13): a ListAgents name is the session's title, which
  `session-title.sh` rewrites as the summary changes, so a name goes stale between turns (a
  lane's send to the lead failed "not reachable"). The messaging socket holds for the life of
  the process: SendMessage takes `uds:<messagingSocketPath>` (tested lead to lane and back).
  `lane addr <id|lead>` prints it for the one session whose file's `cwd` is in the lane's
  worktree (or in the main checkout, agent worktrees included, for `lead`). That `cwd` is the
  launch dir: a Bash `cd` moves the session's working directory and its hook payloads, not the
  file (every live session's file `cwd` matched its process cwd, probed on 2.1.296). Session
  files outlive their process
  (74 files against 7 live sockets on one machine that day), so a file counts only when its
  pid runs with the `procStart` it records, neither exited nor stopped, and its socket is on
  disk, printable and ours. A stopped session (Ctrl+Z) is named in the refusal with its window,
  "fg it there", in place of the `lane open` hint, since `open` refuses beside it. A pass makes
  a new pid, so callers resolve it before each send. It runs
  sandbox-off, since a sandboxed command has its own pid namespace and sees no other process.
  The id `lead` is reserved for new lanes. In the main checkout, `lead` picks the lead ("One
  lead per main checkout"). `--repo PATH` looks in the lanes repo whose main checkout holds
  PATH instead of the cwd's, so a session in another repo can reach this one's lead ("Bug
  reports from other repos").

## The pieces

- **`lane` CLI** (`skills/lanes/scripts/lane`, shared core in `lanelib.py` beside it). Every write
  takes the flock, so two `lane claim 42` calls can't both win. `lane new` reserves the port and
  writes `lane.json` under the lock, then runs the setup command outside it, so a slow
  `npm ci` never blocks a claim; a failed setup leaves the lane registered for a retry or
  `lane done --abandon`. Before any of that, `new` refuses a branch name any PR has used
  (`gh pr list --head <b> --state all`): `ls` labels a lane by its branch's newest PR, so a new
  lane on a merged PR's old head showed as that PR merged, which can start a false post-merge
  chain (lane branch-reuse, 2026-10-19). It asks after the fetch has proved the network up, and
  refuses when gh still can't answer (no login, a remote off GitHub, a reply that won't parse),
  as it does on a failed fetch. `--reuse-branch` skips the check (Hayden's picks) and marks the
  lane `reused` in `lane.json`, so `ls` judges its merges past a full PR list as an adopted
  lane's ("What it can't tell"). After the setup (which may set a `core.hooksPath`), `new` checks the
  worktree as the excluded-command guard will judge the lane's own calls, prints the Edit deny
  rule each dir needs and seeds it into the record's Asks for Hayden, as does `adopt` finishing a
  setup-failed lane; adopting another worktree only prints them (docs/delegation.md, "The
  excluded-command guard"). `lane done` sets the base as the branch's
  upstream before
  `git branch -d`, so `-d` judges the branch against what was merged rather than the main
  checkout's possibly unpulled HEAD.
- **`lane open <id>`** (from `hq-open`) runs `tmux new-window -P -F ... -c <lane> -n <id> -d --`
  (no `-d` under `--focus`) with the absolute `claude` path (tmux's PATH lacks `~/.local/bin`),
  `[--model M] [--effort E]` (Model and effort, below), `--permission-mode plan` and a first prompt
  to read the record and plan its brief. The window stops at Claude Code's "trust this
  folder?" dialog unless the lanes root (or a parent) is trusted; a trusted parent covers every
  lane under it (probed 2026-10-11, 2.1.296), so `lane init` prints the one-time line that
  trusts the root. It refuses a stale or `setup-failed` lane, and a
  lane with a live session (naming its tmux target, a stopped one marked `(stopped: fg it
  there)`; `--focus` selects that window instead).
  Sandboxed, it can't see other sessions, so it refuses and asks for a bare run; `--print` still
  prints, warning that the command may duplicate a live session. It stamps only
  `opened` in `lane.json`. The window is derived from the live session's `tmux` field on each
  `lane ls`, never stored (invariant 4): a stored window id drifts the moment the window closes
  or tmux renumbers it.
- **Model and effort** (lane lane-model, 2026-10-15). `lane init --model M --effort E` stores repo
  defaults in the lanes config (`model`, `effort`; an empty value removes one), and `lane open <id>
  --model M --effort E` overrides them for one launch (an empty flag skips the default). Both go to
  claude ahead of `--permission-mode plan`. A model must be an alias (`default`, `opus`, `sonnet`,
  `haiku`, `fable`, `opusplan`) or a `claude-` full name, and an effort one of `low`, `medium`,
  `high`, `xhigh`, `max`. `opus`, `sonnet`, `fable` and the full names also take `[1m]` (quote it:
  zsh globs the brackets); `default[1m]` fails at its first request, and `/model` says `haiku` and
  `opusplan` have no 1M form (probed 2026-10-15). The check is strict because a bad name fails where
  nobody looks: claude stays up in the detached window and shows "There's an issue with the selected
  model" at its first request (spike S1). A typo inside a full name still gets through. `open`
  refuses a pick for a lane with a live session, since `/model` or `/effort` in its window is what
  changes a live one.

  The baseline `settings.json` pins the model with env `ANTHROPIC_MODEL=opus` (lane model-pin,
  2026-10-23). Claude Code reads it at startup ahead of the `model` key that `/model` saves (probed
  on 2.1.309), so a `/model` moves only its own session. `/model` still says the pick is "saved as
  your default for new sessions" and writes the key, then adds that `ANTHROPIC_MODEL` is set and new
  sessions use it (checked live on 2.1.310): nothing reads the key while the pin stands. A `--model`
  flag beats the pin, so `lane open --model ''` starts a lane on Opus. The effort has no pin:
  `/effort` still sets the default for new sessions.

  A plain pass keeps the pick (`carried_pick` in lanelib, which pass-respawn, `claude-restore` and
  `claude-saved` share), for each flag the old claude launched with, read from its `/proc` command
  line, and for the model after a `/model` even when it launched without one, since the fresh
  claude would otherwise take the pin (Hayden's pick, 2026-10-23):
  - After a `/model` (for the effort, a `/model` or `/effort`) in the transcript, it carries what
    the last main-chain assistant entry since ran with (`message.model`, `effort`). That id loses
    what an alias or a 1M form means (`opusplan`'s switch per mode, `sonnet[1m]`), so the model is
    instead the `/model`'s own argument, whenever it is a name `lane open` would accept and could
    have run as the id. A pick from the menu has no argument, so it carries the id, and an
    `opusplan` or 1M form picked there loses its meaning. The user's saved default is never read: it
    is machine-wide, so another session's later pick of the same family would pass for this
    session's. When no usable entry follows (a `<synthetic>` one, a model that takes no effort, an
    id that isn't `claude-`), the effort drops to the default the command saved, and the model
    carries the `/model`'s argument if `lane open` would accept it (the pin would undo the pick),
    else it drops to the pin.
  - With no such command, it carries the launch value, except a model the last entry can't have run
    as (an alias of another family, another full name; a dated id such as
    `claude-haiku-4-5-20251001` fits `claude-haiku-4-5`). That is a change the transcript can't
    show, such as one before a `/clear`, which starts a new transcript in the same process; then it
    carries the id that ran. A change there within the launch alias's family (`opus` to
    `claude-opus-4-8`) can't be told from none, so it reverts. The effort has no such check: Claude
    Code moves it without a command (a level per model, a one-turn bump), so an `/effort` before a
    `/clear` reverts too. A session launched without `--model` has no launch value to check, so a
    `/model` before a `/clear` reverts to the pin.

  Only an accepted `/model` reaches the transcript (a refused one leaves no entry), and only Claude
  Code's own command entry counts, never a prompt or a tool result that quotes its tag. The
  transcript is read just before the respawn, as the resume mode is, so a `/model` during the
  passing turn counts; a launch value that can't be passed on refuses at the call. A session
  launched without the flags respawns bare unless a `/model` carries. Hayden picked this over a
  plain copy of the flags (which undoes a mid-session `/model` at the next pass) and a stored
  per-lane pick (the same flaw, plus new state). How each case comes out:
  - a plain pass or an auto-pass: the pick holds; a compact pass keeps the same process;
  - a `/model` or `/effort` mid-session: the new pick holds at the next pass; across a `/clear`,
    only a model the launch value can't have run as does (with no launch `--model`, none does);
  - a default changed after a lane opened: that lane keeps its launch pick until `/model` or
    `/effort` in its window moves it;
  - the lead's main checkout: no repo default reaches it, and it carries what it launched with
    or a `/model` since;
  - a tmux restart, or a reopen from the shelf: the pick holds, as below.

  A tab restore (`tmux/claude-restore`) and the shelf's Open (`tmux/claude-saved`) keep the pick
  the same way (lane restore-effort, 2026-10-17). A bare `claude --resume <id>` drops the effort to
  the default (spike S3, again on 2.1.302) and, under the pin, the model to the pin (probed
  2026-10-23 on 2.1.309; before the pin it kept the model), and the resumed claude would have no
  flags for its next plain pass to carry, so each types the flags instead (`--resume` honors both,
  probed 2026-10-17 on 2.1.302). `hooks/session-registry.sh` saves the flags the session's claude launched with, as
  `model` and `effort` in its open-sessions entry, at each SessionStart: the hook's nearest
  ancestor that is a Claude process (its session file records its own procStart, which finds a
  claude run by its versioned path, whose comm is the version; else its name is `claude`), its
  `/proc` command line, each value only in the shape a pass would pass on. `claude-saved` copies
  them into a starred or shelved chat's entry at Star, Shelve and each SessionStart. At relaunch,
  `carried_pick` reads them with the transcript, which by then is complete, by the pass's rule.
  Hayden approved launch flags plus the transcript over either alone: the flags alone undo a
  mid-session `/model`, and the transcript alone loses an alias or a 1M form and would pin a
  session launched without flags to what it last ran. How each case comes out:
  - launched without flags, or an entry from before the fields (a session started before the
    install keeps one until its next SessionStart: a compact, `/clear` or resume): a bare resume,
    unless a `/model` in the transcript carries, so the pin and the user's default effort apply, as
    at a pass;
  - a field outside its shape: that flag drops, never the tab;
  - a tab with no transcript yet: `claude` with its launch flags;
  - an attach tab, or Open of a chat running in the background: no flags, since the resume
    attaches to the running session, which keeps its own pick. So does an attach tab resumed
    when `claude agents` fails and can't say whether its session runs. A chat once seen in a
    flagged tab keeps that tab's flags in its attach entry (`claude-saved track`), so after a
    reboot it resumes with them;
  - lanelib missing or broken, or `carried_pick` raising: no flags, and every tab still comes back
    (each script imports lanelib through its own link, by absolute path only).

  `claude-restore --list` and `restore.log` name the flags each tab gets. Only these two flags
  carry: `--fallback-model`, `--name` and the rest still drop at a plain pass, a restore or Open.
- **Auto-pass in lanes** (README "Auto-pass", PLAN.md "PR 4: auto-pass"). Auto-pass is on by
  default in every lane and in the main checkout of a repo with lanes, so the lead passes itself
  the same way. `lane init --no-autopass` turns it off for the repo (`autopass = false` in the
  lanes config), `--autopass` turns it back on, and `/autopass on|off` in a tab beats both. Each
  lane hands itself off through the watcher. `lane ls` shows how close each one is: its CTX
  column, after SESSIONS, is the watcher's latest count (`ctx/<session>.json`) for the lane's
  live sessions, the most urgent one when there are two, marked `*` past the soft tier and `!`
  past hard on that session's own window (`312k*`, `523k!`; the window comes from the config
  dir of the transcript its stop record names, as the watcher's does). It is `-` with no count
  and `?` when sandboxed; `--json` has it as `ctx` (`session`, `tokens`, `tier`, `status`). The
  STATE column after it lists each live session's `status` from its session file (`busy`,
  `idle`, `waiting`, or `shell` while a background shell runs at the prompt), as `states` in
  `--json`. A stopped session (Ctrl+Z) drives none of these columns: its lane gets the `stopped`
  flag (beside `orphan` when no session runs), and `--json` lists it in `stopped_sessions`. The lead messages a lane that sits idle past soft: "context N k, run /pass". It does this by hand for now; no code
  sends that message. The lead never respawns another lane's pane, since only that lane holds
  the context its handoff needs.
- **`lane lock <name> -- <cmd>`** serializes shared gates with a flock on
  `<common-dir>/lanes/_locks/<name>`, apart from the CLI's own `.lock`. The name must be listed in
  the config's `locks`, since a typo would split the mutual exclusion. Once it holds the lock, it
  writes a holder line (lane id, `main`, or the checkout's kind and path; start time; command), which a waiting run and the
  `lane ls` footer show. There is no pid: each sandboxed command has its own pid namespace, so a
  pid would mislead. A run that ends clears the line while it still holds the lock, so a waiter
  doesn't name it; a `lane` killed by a signal it doesn't catch (SIGKILL, SIGHUP) leaves its line
  until the next holder overwrites it. The lock fd is close-on-exec, so a backgrounded grandchild
  never keeps the lock. SIGINT and SIGTERM are not forwarded: the command shares `lane`'s process
  group, so a Ctrl-C or the Bash tool's kill already reaches it, and Go and Node tools read a
  second copy as "force quit". Two edges follow. A signal sent to `lane` alone leaves the command
  running, lock held, and a supervisor that then SIGKILLs `lane` (`timeout -k`, `terminate()` then
  `kill()`, systemd `KillMode=process`) frees the lock while the orphaned command still runs:
  signal the process group instead. And a group signal that lands after the command has exec'd
  but before `Popen` returns is replayed as pending, so the command gets it twice (blocking the
  signals around `Popen` can't tell a pre-fork arrival from a post-fork one). `lane` returns the
  command's exit code; when signal n killed the command, it lets go of the lock and dies of n
  too, so a Ctrl-C stops a calling script (bash stops only for a child that died of SIGINT, not
  one that exited 130). `--wait SECS` gives up with exit 75, which a command's own 75 matches:
  only the "gave up on lock" stderr line tells a timeout apart. A wait first retries once after
  50 ms, so one `lane ls` probe (an instant shared lock) doesn't read as a holder; two probes
  50 ms apart still can, and make `--wait 0` give up on a lock nobody runs under.
- **`hooks/lane-identity.sh`** (SessionStart, Stop, SessionEnd): the identity line, the `sessions[]`
  entry, the mirror and the end stamp, and in the main checkout the board line and the lead heal
  ("One lead per main checkout"). The identity line names the branch the worktree has checked
  out, or a detached HEAD by its commit, as `ls` and `whoami` do, since a lane that switched for a
  follow-up PR leaves `lane.json`'s branch behind. The hook asks git itself (it doesn't import the
  CLI), and only a valid branch name or a commit reaches the context: the admin dir is
  sandbox-writable. Anything else names `lane.json`'s branch and says HEAD couldn't be read. A
  compact keeps its session's entry, so the session's start (which `handoff-check` uses) doesn't
  move. The mirror is crash-safe: it builds `mirror.new`, swaps, then deletes. A `mirror.old` left
  by a killed run is restored under the lock by the hook or `done`, and read in place by lock-free
  readers such as `lane asks`. Every step goes by name under `lanes/<id>/` opened by fd, so a
link swapped in for it mid-run leads nowhere. It copies every symlink as a link and never
follows one, opening each name by fd with `O_NOFOLLOW` (a file swapped for a link mid-copy is
copied as the link), and skips
  the copy when nothing in `.lane/` changed. Following links once copied whatever they reached
  (`../..`, a home dir) into every archive, so evidence must be real files. A `.lane` that is itself
  a symlink (a repo can commit `.lane -> ..`) is never mirrored or archived, and `lane new` and
  `adopt` refuse it. SessionEnd stamps `endedAt` before it mirrors, so a slow or failed mirror never
  costs the stamp.
- **`hooks/lane-guard.sh`** (PreToolUse `Edit|Write|MultiEdit`): denies a write through a
  symlinked `.lane` (checked on the path as given, before resolving it), a write to another lane's
  `.lane/`, any Edit-tool write under `<common-dir>/lanes/` (the lane's own included: the CLI
  owns that data), and a relative phrase added to a `.lane/` file or to the root STATUS.md of
  any checkout in a lanes repo (a lane's copy reaches main on merge). The phrase list is tight
  on purpose: `(an)?other (claude )?session`, `this session`, `the other (lane|session)`,
  `my (lane|session)`. HTML comments and code are skipped, the same lint `handoff-check` runs:
  a quoted example claims nothing. An Edit is judged on the whole file before and after (a
  fragment that starts at a closing fence would read it as an opener), with the fragments as the
  fallback when the file can't be read or replayed.
- **`skills/handoff/scripts/handoff-check`**: makes "handoff done" checkable, in a lane, in main
  and in a plain repo. A status file counts as fresh against HEAD when it is newer than HEAD's
  commit, or when HEAD's commit carries it (a plain repo commits STATUS.md in the handoff
  commit). A lane's record is outside the tree, so its handoff writes the commit range into the
  record after the commit. Agent worktrees (`.claude/worktrees/`) never count as leftovers, and a
  leftover must be named by its repo-relative path. Relative identity outside HTML comments and
  code fails in a lanes repo and only warns in a plain one, where long-lived text has no peer
  to mislead. `--closing`, which `lane done` runs, judges freshness against HEAD's commit only
  and skips approval: after a `/pass`, the idle new session started after the handoff. It also
  fails on a `Keep open:` item in Next. Its unpushed-commit warning follows the checked-out
  branch or detached HEAD (why: the branch switch paragraph under `lane done`), falling back to
  `lane.json`'s branch only when HEAD can't be read or names an invalid branch. It counts the
  commits that neither the base nor any of origin's refs hold, never against one pushed copy:
  a lane that switched off a merged PR's old head once warned of 431 unpushed commits, measured
  against that PR's unpruned copy, and a lane made with `--reuse-branch` would meet the same
  copy under its own name.
- **`lane done`** validates the id and asserts its deletes stay inside `<common-dir>/lanes/`. It
  needs commits past the lane's base, then either a merged PR whose head commit is the branch tip
  (a squash merge) or the tip in the base. An adopted lane's base is a merge-base: with nothing
  past it, its tip is already in the base, so nothing can be lost and it closes without
  `--abandon`. It can't tell "no work" from "fast-forwarded in before adoption", so its state is
  `closed`, "closed (nothing past origin/main)", unless a merged PR names that tip; `abandoned`
  means `--abandon`. While the worktree exists it refuses a lane whose record's Next has a
  `Keep open:` item, live session or not ("Who asks what"); `--abandon` closes it anyway, and a
  merged lane keeps the state `merged`. The archive is built under a `.tmp` name and renamed into place only when
  complete. Sandboxed, `done` can't see
  other processes, so it refuses and asks for a bare `lane done <id>`. It detects the sandbox by
  `SANDBOX_RUNTIME=1` or by pid 1 of its namespace (the sandbox's `apply-seccomp` launcher, not
  init), since `CLAUDE_PID` is set both inside and out.

  `done` ends what provably belongs to the lane, so a merged lane whose session is still open
  closes in one run. One `/proc` scan sorts every process whose real cwd is in the lane:
  - **session:** a `~/.claude/sessions/<pid>.json` whose `procStart` is that pid's start time,
    with its cwd in the lane;
  - **owned:** its parent chain reaches a session (its Bash commands, hooks, MCP servers);
  - **pane shell:** a session's parent whose only children are sessions, whose own parent is a
    tmux server and which carries no foreign session id (claude-restore types `claude --resume`
    into a zsh);
  - **leftover:** started with the `CLAUDE_CODE_SESSION_ID` of a lane session, and every one of
    its descendants is ended too (a tmux server started from a lane's Bash carries the lane's
    id, and its panes run elsewhere).

  A session id is the lane's only when a session file or a transcript
  (`projects/*/<sid>.jsonl`) records a cwd in the lane. `lane.json`'s `sessions[]` proves
  nothing: sandboxed Bash can write it, and it misses a registration that timed out.

  Before any signal, `done` refuses anything else by name (pid, comm and program name, never an
  argument: one can hold a secret). The same goes for each of these:
  - a background session: `claude stop <jobId>` ends it;
  - a dirty, locked or submodule worktree, which a plain `git worktree remove` would refuse
    after the kill (the dirt check runs again just before the worktree goes, as git's does);
  - a run from anywhere but the main checkout, or under a Claude session whose cwd is in a
    linked worktree of this repo or under the lanes root (outside the main checkout): only the
    lead closes lanes. Both come from git's own worktree links and the lanes config, never
    `lane.json`, which sandboxed Bash can write;
  - an install that points into the lane (below);
  - when there is something to end, a failing `handoff-check --closing`.

  With something to end, it marks the lane `closing`, which `open` refuses, and deletes each
  session's `open-sessions` entry, as Shelve does, so claude-restore never reopens it. Signals go
  through a pidfd once the start time is checked again:
  1. SIGTERM to sessions and leftovers, then a wait of up to 10 s: longer than the 5 s
     SessionEnd hooks, which run as the session's children and are left to it. A session found
     stopped (Ctrl+Z) right after its SIGTERM gets SIGCONT, since the signal waits while a
     process is stopped and its SessionEnd hooks would never run (Hayden's call, 2026-10-17).
     Each stopped process under it gets SIGCONT too: Ctrl+Z stops the whole job, MCP servers
     and tool children included, and the signals the session's exit sends them would wait
     as well. One that stops again on the terminal (SIGTTOU) still ends at step 3.
  2. SIGHUP to each pane shell after that wait (an interactive shell ignores SIGTERM). A
     restored tab draws its prompt the moment its claude exits, and a prompt can fork as it
     draws: agnoster's `$(build_prompt)` runs git in a `-zsh` child, and one refused the
     2026-10-15 close of lane two-sessions. So each shell gets its SIGHUP once it runs no job of
     its own and nothing under it holds a git file open, within 10 s. A shell still running a
     job then gets none, since the SIGHUP would reach the job too: step 3 refuses it, or sends
     it if the job has ended by then. zsh passes
     the SIGHUP on to a session still exiting, which Claude Code handles as a closing tab.
  3. Whatever survives, classified afresh: SIGTERM (SIGHUP again for a pane shell), a wait,
     then SIGKILL.

  Every signal but a session's first SIGTERM (and those SIGCONTs) is guarded: just before it,
  `done` rescans the target's process tree and holds the signal while anything in it has a file
  open in the git dir (a killed git leaves lock files). A held signal is named in the refusal,
  and a process held at step 3's SIGTERM is never SIGKILLed, nor is anything under a session
  whose signal was held. A session's first SIGTERM goes unchecked: Claude Code handles it as
  when its tab closes, running its SessionEnd hooks and ending its own children.
  Nothing is stopped for the check. tmux continues a pane process that gets SIGSTOP at once, and
  a job-control shell reports a stopped job suspended and takes back the terminal (probe on tmux
  3.7c), so a freeze can't hold a tab's session still. A git that starts or opens a lock file
  in the milliseconds between the check and a SIGKILL is the accepted residual (Hayden's call,
  2026-10-13); git removes its own lock files on SIGTERM.

  A `lane open` tab closes by itself once its claude exits. The lanes lock is never held while
  `done` waits, because every lane's hooks take it with a 2 s timeout, and `done` gives up on it
  after 30 s wherever it takes it, so a stuck sandboxed `lane claim` can't hang the close.
  Anything that survives, or that starts meanwhile, refuses the close and leaves the lane
  `closing` (rerun `done`); its `open-sessions` entries are swept either way. Last, under
  setup.sh's `install.lock` (waited for up to 30 s), `done` builds the archive under a temporary
  name from `lane.json` re-read under the lanes lock (so it keeps the `endedAt` SessionEnd
  stamped), checks the install and the lane's processes once more and removes the worktree with
  the lanes lock released (it can outlast the hooks' 2 s), then re-reads the record under it,
  moves the archive into place and removes `lanes/<id>/`. No install relinks into the lane in
  between, and a failure leaves no partial archive.

  `done` removes the worktree itself, never through `git worktree remove`: git deletes by path,
  and a process the lane left can still write the lane and the common dir, so a path checked
  at the gates may lead elsewhere by its use. The admin dir is the one real dir under
  `<common-dir>/worktrees/` whose `gitdir` reads, as text, the lane's `.git` path (the lane's own
  `.git` file, which it can write, is never asked). `lane.json`'s path is sandbox-writable and
  nothing ties it to the lanes root (`adopt` takes a worktree anywhere), so the dir above the
  tree is reached by a walk from `/` with `O_NOFOLLOW` at every name, and a link swapped in on
  the way refuses the removal. The tree is renamed aside to a fixed hidden name there, then
  removed by Python's fd-based `rmtree`, which never follows a link; then the admin dir and any
  tree a trial left, by name under `worktrees/` as it was opened before the files went. The archive's temp dir, its rename and `lanes/<id>/` likewise
  go under `lanes/` and `_closed/` opened at the start. With no admin dir or several naming the
  lane, it removes nothing. A file it can't delete (a dir with no write permission) stops it
  partway with the record and the registration kept; the tree is already aside, so a rerun's
  gates find nothing at the lane's path, and the rerun finishes the removal.

  A rerun keeps what the first run proved. A pane shell's only proof is the session it ran,
  which the close itself ends, so on 2026-10-15 each rerun refused the two-sessions tab's shell
  until its session was resumed there. So once it marks the lane `closing`, and again before
  step 3's signals, `done` records each pane shell it proved the lane's in
  `<state-dir>/lanes/<repo>-<hash>.closing/<id>.json`: the boot id, the lane's id, created stamp
  and path, then each shell's pid, start time and comm. When the first write fails, it signals
  nothing and leaves the lane `closing` for a rerun; a failed second one only warns, and the
  first stands. A completed close deletes the record, or warns and names the file when it can't.

  A rerun keeps a recorded shell's class only for the same boot, lane (id and created stamp, so
  a later lane of that id never inherits it) and path, while a process with that pid, start
  time and comm runs, its parent is a tmux server and it carries no foreign session id. Every
  other process is proven afresh, as on a first run, and a recorded shell running a job still
  refuses. The record lives in the state dir because sandboxed Bash can write `lane.json`.

  Every git `done` runs in the lane takes its config from the repo's common dir
  (`GIT_COMMON_DIR`), and the lane's path must be a worktree whose admin dir's `commondir` names
  that dir: the admin dir is sandbox-writable, and a config `core.fsmonitor` would run a command
  sandbox-off. While the lane's worktree exists, a repo that sets `extensions.worktreeConfig` refuses
  `done`, since git then also reads the lane's `config.worktree`, which nothing overrides; a
  worktree that was gone at the checks and reappears before the remove refuses too.

  Nothing is chosen by name, start time or tmux window. A window id means something only on its
  own tmux server, and `kill-window` sends SIGHUP to everything on the pane's terminal (Hayden's
  call, 2026-10-13).

  A lane can switch branches for a follow-up PR, which leaves `lane.json`'s branch behind (lane
  tab-bar, 2026-10-14). So `ls`, `whoami`, `done` and `handoff-check`'s unpushed count go by the
  branch the worktree has checked out; a detached one (mid-rebase, say) shows `lane.json`'s branch's PR on the board. `done`
  judges that branch and `lane.json`'s, when it differs and still exists: each must pass, except
  one with nothing past the base once the other does. It refuses a detached worktree without
  `--abandon` (its commit is on no branch to judge), and refuses the remove if the worktree's
  branch or HEAD moved since the judging. It deletes each judged branch with `-d`, never the
  base's own or one another worktree has checked out, and gives a branch `-d` keeps its upstream
  back. After the close it names any Edit deny rule left naming the removed worktree, with its
  file.
- **Installing from a lane** (`install-state.py`, run by `setup.sh`). In a repo that installs
  from its checkout, the lane next in merge order tests its change by installing from its own
  worktree (`lane lock install -- ./setup.sh`). Before this, the next install from anywhere
  replaced its links mid-test. Now the links themselves are the hold, with no state file to go
  stale.
  - **Held:** while managed links point into a live lane, `setup.sh` refuses, before changing
    anything, to run from anywhere but that lane or its main checkout. A managed link sits in a
    dir setup.sh links into, and its path inside its checkout matches one that setup.sh links.
  - **Released:** the lead's `./setup.sh` in the main checkout relinks everything, which
    releases the hold. That includes a hold by a lane whose PR hasn't merged: on 2026-10-17
    #113 merged ahead of #110, and the reinstall for #113 released lane-model's install.
    setup.sh printed the release, but nothing told the lane. So the lead now notes the hold
    line on `lane ls` before it reinstalls (`skills/lanes/SKILL.md`, The lead, step 7.3) and
    tells that lane with the other nudges (step 7.6): "released your install: merge
    origin/main, then reinstall". The message waits for step 7.6 because a lane that
    reinstalled at once would fail step 7.4's check that no link points into a lane.
  - **Merged:** a run from a lane with no commit past the lanes config's base (`origin/main`)
    stops too: its work is merged, or there is none yet. On 2026-10-15 a rerun from merged lane
    pass-timeout, 3 s after the lead's reinstall from main, took the install back. It followed
    a hint printed while pass-timeout still held the install. The check runs under setup.sh's
    `install.lock`, so it judges the moment of the run, not of the hint. It fails closed (no
    git, no base ref, git past its 5 s limit), and git runs only in a lane's own run, reading
    objects only. Two misses are accepted: a merge nobody fetched yet (the post-merge chain
    fetches before it reinstalls) and a squash merge (dotclaude merges with merge commits).
    The excluded-guard hint no longer names a lane either: it says to rerun from the main
    checkout, or from the unmerged lane `lane ls` shows holding the install at rerun time.
  - **What counts as a lane:** a linked worktree of this repo, or a worktree of another clone
    with `install-state.py` and `setup.sh` at its root. Another project's worktree, and one
    inside the main checkout (an agent's), never holds. A lane registered in the main
    checkout's own `.git/worktrees/` is released by that main's run whatever its `.git` file
    names, and only a real main checkout releases: a lane's sandbox can rewrite its `.git` file.
    So is any dotclaude checkout under the lanes root (the lanes config's, which sandboxed Bash
    can't write), so a lane that deletes its own `.git/worktrees/` entry too can't hold main off.
    The accepted cost: an entry planted there naming another clone's lane releases that lane's
    hold too, which equals an install from this main and prunes nothing outside a dotclaude
    checkout. Every file these checks read goes through one bounded, non-blocking reader, so a
    FIFO or a huge file planted in a lane can't hang `setup.sh`. The one exception is the merged
    check's git call, in a lane's own run: git reads the repo's config, refs and objects itself,
    so a FIFO there costs at most its 5 s limit, and then the run stops.
  - **Prune:** after linking, `setup.sh` removes managed links that point into another lane of
    this repo (or into a dotclaude checkout the main checkout's `.git/worktrees/` registers or
    the lanes root holds, whatever its `.git` file says), and dangling ones into its own checkout, the lanes root or `.claude/worktrees/`
    (a closed lane, a removed hook, a removed agent worktree). setup-tmux.sh's `tmux/*` links
    and plugin files are never touched.
  - **One run at a time:** `setup.sh` takes a flock on `install.lock` in the state dir for its
    whole run, waits up to 5 minutes for another run, then stops before changing anything. It
    runs unlocked only where `flock` is missing or the state dir can't be made (macOS,
    git-bash); a lock file it can't open stops the run.
  - **Seen elsewhere:** `lane ls` shows `install: held by lane <id>`. `lane done` refuses while
    any link, or setup-tmux.sh's `~/.tmux.conf` block, points into the lane, naming for each the
    installer that relinks it (`setup.sh`, `setup-tmux.sh`, or by hand).
  - **The plugin line:** `setup.sh` prints one line when a mod or plugin changed since the last
    install (a fingerprint in the state dir). A running session loads those only at its start,
    so it needs `/pass`. Plain skills are left out, since SKILL.md text loads live.
