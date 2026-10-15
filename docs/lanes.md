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
  link points into a lane, nudge the other lanes, add the backlog line, and `lane done` once
  the hand-back gate passes. It reports one line, or the failed step.
- A lane with more PRs to come starts its Next with `Keep open: <why>`, and `lane done` refuses
  it. `--abandon` closes it anyway and stays an ask rule (Hayden, 2026-10-14).
- Lanes report their own state and asks, never the lead's messages.

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
  a lane older than the oldest of them, adopted, or switched off lane.json's branch keeps the
  flag too, since a branch of its may hold a PR older than the lane, which the list may have
  cut. Only two branches are judged, the checked-out one (or, detached mid-rebase, the one being
  rebased) and lane.json's: a merge from a third branch the lane passed through is missed. A
  session that ends with no SessionEnd stamp is skipped, as a live one is; for a merged lane the
  `mergedAt` check still catches the merge it never recorded.
- **A nudge, never consent** (flow 13). `merged #N` says only when to look. The consent is the
  standing approval written here; the lead proves the merge with `gh pr view` before it acts,
  and `lane done` checks it again (a merged PR whose head is the tip, or the tip in the base).
- **A scoped exception to "confirm before deleting"**, which CLAUDE.md names. `lane done`
  refuses an unmerged branch, a dirty worktree, links into the lane and a `Keep open:` lane,
  archives the record before the remove, and never passes `--force` or `-D`. The approval
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
| The lead passes or clears | kept: same pane, same server | lost: the pass makes the lead youngest | nothing to lose |
| A side chat in main | never leads: `ls` and `addr` are looks | leads if it started first | asks |
| Hayden starts a fresh lead by hand | `! lane lead` in it | never, while the old one lives | asks |
| tmux restarts | none until the lead acts again | the restored order | asks |

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
- **The pick** (`lanelib.lead_of`): one live session is the lead whatever the record says. With
  two or more, the record's pid and start match first. Then comes exactly one session in the
  record's pane on the record's server: the pass successor, since `respawn-pane -k` keeps the
  pane. Anything else is no pick. `lane addr lead` then refuses with each session's window and
  the way to pick, and the lane tells Hayden once that #N merged, as with no lead at all.
- **The board** (`lane ls`) adds a line under the table when the main checkout has two or more
  live sessions: each one's window, pid and state, the lead first, `no tmux` or `agent worktree`
  where it applies.
- **The bar** reads the same record. The window holding its pane, on the bar's own server
  (socket, pid and that pid's start), is `lead`; the main checkout's other tabs, a shell
  included, are `lead²`, `lead³` in bar order. With no pick, the first keeps `lead`. A new lead
  renames tabs and moves none.

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
                                (<remote>/<branch>, default origin/main), locks; written only
                                by a bare `lane init`
$XDG_STATE_HOME/dotclaude/lanes/<repo>-<hash>.lead.json
                                the lead record: the main-checkout session that last acted as
                                lead, written only by bare `lane` commands ("One lead per main
                                checkout")

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
  `new` and `adopt` also run the config's `setup` command through a shell, sandbox-off, and
  `new` makes its worktree under the config's `root`. So the config lives in the state dir, not
  the common dir: sandboxed Bash can read it but not write it, and only a bare `lane init`
  (whose flags the permission gate sees) writes it. Everything else the sandbox-off subcommands
  and the hooks act on is sandbox-writable (every `lane.json`, the refs, the main checkout,
  `.worktreeinclude`), so it is checked before use:
  - A `lane.json` must pass `lanelib.record_problem` (its id is its dir's name, its branch can't
    be read as a git option, its path is absolute, and so on), or every command and hook leaves
    it out, and `lane ls` names it.
  - A lane's path must be a real worktree of this repo, outside the main checkout and any other
    lane, before `open` starts `claude` there, the setup runs there, files are copied there, or
    `done` archives and removes it.
  - `new` branches from the commit `ls-remote` reports for the base after a fetch, never from a
    local ref, and refuses when the fetch fails. Other git calls get refs in full
    (`refs/heads/<branch>`, `refs/remotes/origin/main`) after `--end-of-options`.
  - `new` and `adopt` copy `.worktreeinclude` matches by directory fd with `O_NOFOLLOW` on both
    sides. A symlink is copied as a link (a relative one made absolute), never read through, so
    the sandbox's read deny still holds at its target; anything not a regular file is skipped.
  - A symlinked `lanes/`, `lanes/<id>`, mirror or `info/exclude` is refused.
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
  `messagingSocketPath`. A session's own shell also has `$CLAUDE_CODE_SESSION_ID`.
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
  pid runs with the `procStart` it records, not exited, and its socket is on disk, printable
  and ours. A pass makes a new pid, so callers resolve it before each send. It runs
  sandbox-off, since a sandboxed command has its own pid namespace and sees no other process.
  The id `lead` is reserved for new lanes. With two or more live sessions in the main checkout,
  `lead` picks the recorded lead ("One lead per main checkout").

## The pieces

- **`lane` CLI** (`skills/lanes/scripts/lane`, shared core in `lanelib.py` beside it). Every write
  takes the flock, so two `lane claim 42` calls can't both win. `lane new` reserves the port and
  writes `lane.json` under the lock, then runs the setup command outside it, so a slow
  `npm ci` never blocks a claim; a failed setup leaves the lane registered for a retry or
  `lane done --abandon`. After the setup (which may set a `core.hooksPath`), `new` checks the
  worktree as the excluded-command guard will judge the lane's own calls, prints the Edit deny
  rule each dir needs and seeds it into the record's Asks for Hayden, as does `adopt` finishing a
  setup-failed lane; adopting another worktree only prints them (docs/delegation.md, "The
  excluded-command guard"). `lane done` sets the base as the branch's
  upstream before
  `git branch -d`, so `-d` judges the branch against what was merged rather than the main
  checkout's possibly unpulled HEAD.
- **`lane open <id>`** (from `hq-open`) runs `tmux new-window -c <lane> -n <id> -d` with the
  absolute `claude` path (tmux's PATH lacks `~/.local/bin`), `--permission-mode plan` and a first
  prompt to read the record and plan its brief. The window stops at Claude Code's "trust this
  folder?" dialog unless the lanes root (or a parent) is trusted; a trusted parent covers every
  lane under it (probed 2026-10-11, 2.1.296), so `lane init` prints the one-time line that
  trusts the root. It refuses a stale or `setup-failed` lane, and a
  lane with a live session (naming its tmux target; `--focus` selects that window instead).
  Sandboxed, it can't see other sessions, so it refuses and asks for a bare run; `--print` still
  prints, warning that the command may duplicate a live session. It stamps only
  `opened` in `lane.json`. The window is derived from the live session's `tmux` field on each
  `lane ls`, never stored (invariant 4): a stored window id drifts the moment the window closes
  or tmux renumbers it.
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
  `--json`. The lead messages a lane that sits idle past soft: "context N k, run /pass". It does this by hand for now; no code
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
  entry, the mirror and the end stamp. The identity line names the branch the worktree has checked
  out, or a detached HEAD by its commit, as `ls` and `whoami` do, since a lane that switched for a
  follow-up PR leaves `lane.json`'s branch behind. The hook asks git itself (it doesn't import the
  CLI), and only a valid branch name or a commit reaches the context: the admin dir is
  sandbox-writable. Anything else names `lane.json`'s branch and says HEAD couldn't be read. A
  compact keeps its session's entry, so the session's start (which `handoff-check` uses) doesn't
  move. The mirror is crash-safe: it builds `mirror.new`, swaps, then deletes. A `mirror.old` left
  by a killed run is restored under the lock by the hook or `done`, and read in place by lock-free
  readers such as `lane asks`. It copies every symlink as a link and never follows one, and skips
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
  fails on a `Keep open:` item in Next.
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
  - a dirty, locked or submodule worktree, which `git worktree remove` would refuse after the
    kill;
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
     SessionEnd hooks, which run as the session's children and are left to it.
  2. SIGHUP to each pane shell after that wait (an interactive shell ignores SIGTERM), unless
     it started another job meanwhile. zsh passes it on to a session still exiting, which Claude
     Code handles as a closing tab.
  3. Whatever survives, classified afresh: SIGTERM (SIGHUP again for a pane shell), a wait,
     then SIGKILL.

  Every signal but a session's first SIGTERM is guarded: just before it, `done` rescans the
  target's process tree and holds the signal while anything in it has a file open in the git dir
  (a killed git leaves lock files). A held signal is named in the refusal, and a process held at
  step 3's SIGTERM is never SIGKILLed, nor is anything under a session whose signal was held. A session's first SIGTERM goes unchecked: Claude Code
  handles it as when its tab closes, running its SessionEnd hooks and ending its own children.
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
  the lanes lock released
  (`git worktree remove` can outlast the hooks' 2 s), then re-reads the record under it and
  moves the archive into place. No install relinks into the lane in between, and a failure
  leaves no partial archive.

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
  tab-bar, 2026-10-14). So `ls`, `whoami` and `done` go by the branch the worktree has checked
  out; a detached one (mid-rebase, say) shows `lane.json`'s branch's PR on the board. `done`
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
    releases the hold.
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
