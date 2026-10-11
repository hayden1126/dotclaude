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
  session's formatbar lane") happened earlier the same day.

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
  each lane as a real top-level session (PR 2).
- Each lane merges its own PR (Hayden approves each merge), and the lead sets the order.
- `/pass` runs handoff, then `handoff-check`, then respawns the pane (PR 3).

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
   session liveness and staleness live from git, gh and `~/.claude/sessions/*.json`.
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
| 9 | What is this lane blocked on Hayden for? | Asks | the record's "Asks for Hayden" (a design pick, push or merge approval, a cleanup nod), shown by `lane asks` across lanes | the lane; cleared after Hayden answers | living |
| 10 | What did a delegate produce? | Report (up) | a subagent's report JSON (the delegation contract); a lane's hand-back is a passing `handoff-check` plus a State summary; the PR body to outsiders | the delegate | ephemeral, then PR |
| 11 | Proof behind a claim | Evidence | `.lane/artifacts/` (mocks, shots, gate logs), mirrored so it survives `worktree remove`; rulings point here | the lane | archived with the record |
| 12 | Shared machine resources | Env state | `lane.json` port, live sessions (derived; a hand-kept "machine state" list drifts) | the CLI | live |
| 13 | Heads-up between peers | Message | SendMessage. A nudge only: anything that matters lands in a doc first, and a message never carries state or consent | anyone | ephemeral |
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
| Project (living) | `STATUS.md` in the main checkout | direction, backlog keyed by request #, merge order, blocked; a "Lanes: `lane ls`" line in place of lane prose | the main checkout or lead session; at merge a lane appends one promotion line (lane id, PR, outcome) | living |
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

<common-dir>/lanes/             CLI-owned; written by `lane` and by hooks, never by the Edit tool
  config.toml                   root, setup cmd, port range, live-lane cap, base (origin/main)
  .lock                         flock for every CLI write (claims are atomic)
  <id>/lane.json                id, branch, path, base_sha, port, claims[], state, sessions[], created/updated
  <id>/mirror/                  copy of <lane>/.lane/, refreshed by a Stop and SessionEnd hook, so a raw
                                `git worktree remove` (which deletes ignored files) loses nothing
  _closed/<id>-<date>/          lane.json + .lane/ archived on `lane done`
```

JSON for the fields the CLI owns (models alter JSON less than Markdown), Markdown for the prose.

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
- **S3, `excludedCommands`:** `lane *` goes in, beside `delegation-ledger *`. `lane new` fetches
  and `lane ls` asks gh for PR state, and both need the credential the sandbox hides. A sandboxed
  (piped) call still works for the local subcommands and says what it skipped.
- **S4, compaction:** a SessionStart hook matched on `compact` gets its `additionalContext` to
  the model after `/compact` (`/compact` piped into `claude -p --resume` triggers a real
  compaction). `lane-identity.sh` on `compact` is therefore the safety net for an unplanned
  auto-compact.
- **Session facts** for `handoff-check`: `~/.claude/sessions/<pid>.json` carries `sessionId`,
  `cwd`, `startedAt` (ms), `status`, `tmux` (`session:@window.%pane`) and
  `messagingSocketPath`. A session's own shell also has `$CLAUDE_CODE_SESSION_ID`.

## The pieces

- **`lane` CLI** (`skills/lanes/scripts/lane`, shared core in `lanelib.py` beside it). Every write
  takes the flock, so two `lane claim 42` calls can't both win. `lane new` reserves the port and
  writes `lane.json` under the lock, then runs the setup command outside it, so a slow
  `npm ci` never blocks a claim; a failed setup leaves the lane registered for a retry or
  `lane done --abandon`. `lane done` sets the base as the branch's upstream before
  `git branch -d`, so `-d` judges the branch against what was merged rather than the main
  checkout's possibly unpulled HEAD.
- **`hooks/lane-identity.sh`** (SessionStart, Stop, SessionEnd): the identity line, the
  `sessions[]` entry, the mirror and the end stamp. A compact keeps its session's entry, so the
  session's start (which `handoff-check` uses) doesn't move.
- **`hooks/lane-guard.sh`** (PreToolUse `Edit|Write|MultiEdit`): denies a write to another lane's
  `.lane/`, any Edit-tool write under `<common-dir>/lanes/` (the lane's own included: the CLI
  owns that data), and a relative phrase added to a `.lane/` file or to a lanes repo's root
  STATUS.md. The phrase list is tight on purpose: `(an)?other (claude )?session`, `this session`,
  `the other (lane|session)`, `my (lane|session)`.
- **`skills/handoff/scripts/handoff-check`**: makes "handoff done" checkable, in a lane, in main
  and in a plain repo. A status file counts as fresh against HEAD when it is newer than HEAD's
  commit, or when HEAD's commit carries it (a plain repo commits STATUS.md in the handoff
  commit). A lane's record is outside the tree, so its handoff writes the commit range into the
  record after the commit.
