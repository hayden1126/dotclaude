# PLAN: Lanes (parallel sessions in worktrees), handoff-check and /pass

> **Status:** STATUS.md holds where this stands. Approved by Hayden 2026-10-11 (three PRs:
> core `feat/lanes`, lead `feat/lanes-lead`, `/pass` `feat/pass`). On 2026-10-12 Hayden split
> auto-pass out of PR 3 into PR 4. The previous PLAN.md (Star and Shelve) is in git
> (`git show fe56e56:PLAN.md`); README holds its as-built behavior.

## Context

Hayden runs several Claude sessions on one repo (a private work repo, with hand-made sibling worktrees as lanes).
Today's (2026-10-11) incident, reconstructed from the transcripts:

- Session A (one lane) wrote into the one shared, gitignored
  `STATUS.md in the main checkout`: "#110 ... another session is building it". That meant
  "a session Hayden will route it to".
- Session B was that intended owner. It read the line as being about someone else. It
  then matched the phrase to the wrong live session through ListAgents (session C, whose first
  prompt read "another session working on request #110") and deferred #110. A mirror flip
  ("another session's toolbar lane") happened earlier the same day.

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
The workable patterns are:
- per-lane records keyed by branch or worktree;
- a record written by a single writer;
- records reconciled against `git worktree list` at read time.

Native `claude --worktree` puts lanes inside the repo. That conflicts with the work repo's "never
inside", and Codex sessions wouldn't get the convention.

**Hayden's calls** (2026-10-11):
- Records: CLI data in `<git-common-dir>/lanes/`; the lane's prose in its own `.lane/`, mirrored
  into the common dir (moved there after spike S2).
- A `lane` CLI creates sibling-dir worktrees.
- Enforcement is the skill and CLI plus two hooks.
- An optional **lead** session triages requests, proposes a lane split, and on approval opens
  each lane as a real top-level session in a tmux window (an `hq-open` analog).
- Each lane merges its own PR (Hayden approves each merge), and the lead sets the order.
- `/pass` (or a typed "handoff and pass") runs handoff, then `handoff-check`, then respawns the
  pane. It resumes in plan mode unless the next step was already approved.
- Opt-in auto-pass on context fill, on by default in lanes. The lead only nudges and never
  respawns a lane.
- The work ships as four PRs: core, lead, /pass, auto-pass. Then the work repo migrates in its
  own repo.

## Invariants (the convention in five rules)

1. **Absolute identity.**
   - A lane's id is its worktree directory's basename. Each session belongs to exactly one lane,
     or to `main`, by its cwd.
   - Status text names lanes by id and requests by number, never "another/this/other session" or
     "my lane".
2. **One writer per record.** After creation, only the lane's own sessions write
   `<lane>/.lane/` and `lanes/<id>/`. The lead writes a record only when it creates the lane, plus its own
   backlog.
3. **Only the owner claims.** A request is owned only when a live lane's record claims it
   (`lane claim`). The answer to "who has #110?" comes only from `lane who #110`. It never comes
   from prose, ListAgents first prompts or tab titles. "Hayden routed #110 away from lane X"
   is recorded by lane X about itself.
4. **Derive, don't store.** `lane ls` derives branch, ahead/behind `origin/main`, PR state,
   session liveness and staleness live from git, gh and `~/.claude/sessions/*.json`.
5. **STATUS.md is project direction, not lane state.** In a repo with lanes, STATUS.md holds
   direction and a backlog keyed by request number. Each lane's next step lives in its own
   record.

## Communication model: what has to flow, and the one home for each

**Actors:**
- Hayden;
- the lead (optional);
- lanes (each a series of sessions over time);
- subagents inside a lane;
- future sessions after `/clear` or `/pass`;
- outside collaborators (through the tracker and PRs).

**What flows:** every fact belongs to one of these flows. Each flow gets exactly one home and one
writer, and every other place links to it.

| # | Flow (the question it answers) | Type | Home (lanes repo) | Writer | Lifetime |
|---|---|---|---|---|---|
| 1 | How do we work here? | Conventions | `CLAUDE.md`, skills, `docs/` (a repo's own lane guardrails doc folds into the lanes skill and CLAUDE.md) | Hayden or a PR | durable |
| 2 | What is wanted, and why? | Intent | the request tracker (source of truth); `SPEC.md` for a large effort | Hayden or outside people | durable |
| 3 | What's queued and not started? | Backlog | the project `STATUS.md` Backlog, keyed by request #; it mirrors nothing the tracker already holds | main or lead | living |
| 4 | Who is doing what? | Registry | `lane.json` claims, viewed through `lane ls` / `lane who` (derived, never prose) | the owning lane via the CLI | living |
| 5 | What does this lane have to do? | Brief (down) | the lane record's opening section, from `templates/LANE.md`: goal, requests, expected files, overlaps with lanes by id, done criteria, constraints | the lead or creator, once | lane |
| 6 | How will we build it? | Design | the lane's `.lane/PLAN.md`; cross-lane design goes in the project `PLAN.md` or `docs/` | the lane, or the lead for cross-lane | lane / durable |
| 7 | What was decided, by whom, and on what evidence? | Rulings | the record's "Decisions": `Hayden picked chip row + preview (2026-10-11); evidence: <artifact path>, session <id>`. Promoted at merge into the PR body; also to memory if it constrains future work | the lane | lane → durable |
| 8 | Where does it stand, and what's next? | State + handoff | the record's State and Next. A shift-change note in SBAR order: situation, background, assessment, next step | the lane | lane |
| 9 | What is this lane blocked on Hayden for? | Asks | the record's "Asks for Hayden" (a design pick, push or merge approval, a cleanup nod), shown by `lane asks` across lanes; one queue for everything the lead runs under Hayden's permission | the lane; cleared after Hayden answers | living |
| 10 | What did a delegate produce? | Report (up) | a subagent's report JSON (the delegation contract); a lane's hand-back is a passing `handoff-check` plus a State summary; the PR body to outsiders | the delegate | ephemeral → PR |
| 11 | Proof behind a claim | Evidence | `.lane/artifacts/` (mocks, shots, gate logs), mirrored so it survives `worktree remove`, unlike `work/` today; rulings point here | the lane | archived with the record |
| 12 | Shared machine resources | Env state | `lane.json` port, `lane lock` holders, live sessions (derived; the work repo's hand-kept "Machine state" list drifted, so it is retired) | the CLI | live |
| 13 | Heads-up between peers | Message | SendMessage. A nudge only: anything that matters lands in a doc first, and a message never carries state or consent | anyone | ephemeral |
| 14 | What did we learn? | Lessons | memory (Hayden's preferences, traps), `docs/` | any session | durable |
| 15 | What happened? | History | git, PRs, transcripts. Never copied into a doc; docs point to them by SHA, PR # or session id | n/a | durable |
| 16 | Tell the outside world | External | Hayden updates the tracker assignee from each lane's "started" claims (so a collaborator doesn't start the same request); PR comments | Hayden | durable |

**Rules that make it work:**
- **One home, one writer.** Every other place links. No doc carries an owner column, because
  ownership lives only in claims.
- **Lifetime decides the home.**
  - Ephemeral (messages, live env) never holds state.
  - Living (backlog, registry, state, asks) is overwritten in place.
  - Durable (conventions, rulings, lessons) is append-only or goes through a PR.
- **Promotion happens at fixed moments only:**
  - at turn end, a message's content goes into the record;
  - at handoff, the lane's state and next step are refreshed;
  - at merge, rulings go into the PR body or memory, the outcome becomes one backlog line,
    and the record is archived.
  Nothing moves up by copying prose.
- **Absolute names everywhere:** lane ids, request numbers, session ids, SHAs, dates.
- **Pointers over copies:** a ruling cites its artifact or session; a status cites a PR number,
  not its state.
- **Read order at session start:**
  1. identity (hook);
  2. the lane record (Brief, Asks, Next);
  3. the project STATUS (direction, backlog);
  4. anything else only when a pointer leads there.
- **A repo with no lanes is unchanged:** one STATUS.md (with Asks and Decisions sections) and
  one PLAN.md.

### Where each type lives, by level

Today one `STATUS.md` holds four kinds of facts at once: direction, per-lane state, machine state
and backlog. The repo `PLAN.md` would hit the same multi-writer bug the moment two lanes each
plan. The fix is levels, each with exactly one owner. Lower levels never restate higher ones,
and higher levels link to lower ones through a derived view, not through copied prose.

| Level | Doc | Holds | Writer | Lifetime |
|---|---|---|---|---|
| Machine | `~/hq` REGISTRY / STATUS | where projects live | hq | living |
| Project (living) | `STATUS.md` in the main checkout | direction, backlog keyed by request #, merge order, blocked; a "Lanes: `lane ls`" line in place of lane prose | the main checkout or lead session; at merge a lane appends one promotion line (lane id, PR, outcome) | living |
| Project (durable) | `PLAN.md` (cross-lane design only), `docs/`, `CLAUDE.md`, memory | conventions, cross-lane design, lessons | whoever, through a PR or memory | durable |
| Lane | `<lane>/.lane/STATUS.md` + `lanes/<id>/lane.json` | the lane's state, decisions with pointers, not-mine notes, next step | that lane's sessions | the lane's life, archived on `lane done` |
| Lane | `<lane>/.lane/PLAN.md` | the lane's working design (replaces `~/.claude/plans/`, which the next plan overwrites) | that lane | same |
| Session | none (transcript; the session id in `lane.json`) | nothing written | none | none |

- **Derived views, never stored:** `lane ls` (the board) and `lane ls --requests` (request to
  lane, from claims). No doc carries an owner column. Ownership lives once, in `lane.json`
  claims.
- **Promotion at lane close** (part of the lane handoff's after-merge step):
  - a decision future work needs goes to memory or a committed doc, inside the lane's PR (the
    no-STATUS-only-PR rule holds);
  - the outcome goes up as one line in the project STATUS;
  - the rest is archived with the record.
- **A repo with no lanes is unchanged:** one STATUS.md and one PLAN.md, as today.
- `templates/STATUS.md` is restructured as Direction / Backlog / Lanes (derived) / Blocked /
  Notes. `templates/LANE.md` covers the lane level, and the lane PLAN reuses
  `templates/PLAN.md`.
- The guard's relative-phrase lint covers every status level.

## Layout

Changed after spike S2 (Hayden, 2026-10-11): Claude Code treats every path under `.git/` as a
"sensitive file", so Edit/Write there always prompts and no allow rule lifts it. The prose
therefore lives in the lane's own worktree, in the session's cwd, where the Edit tool works with
no prompt. The CLI-owned data stays in the common dir, which sandboxed Bash can write (S1).

The layout (files, fields, `_locks/`, the mirror) lives in `docs/lanes.md` "Layout", the
as-built reference.

JSON for the fields the CLI owns (models alter JSON less than Markdown; Anthropic's long-running
harness post). Markdown for the prose.

## PR 1: lanes core (dotclaude, `feat/lanes`)

**Step 0, spike results** (2026-10-11, Claude Code 2.1.296, `claude -p` in a scratch repo with a
sibling lane; they go into `docs/lanes.md`):
- S1, sandbox: a session rooted in the lane needs **no** `allowWrite` rule. Sandboxed Bash can
  `git commit` and write `<common-dir>/lanes/`, while Claude Code itself keeps `.git/hooks`
  ("Read-only file system") and `.git/config` (lock refused) unwritable. The old "lane commits need
  the sandbox off" came from sessions rooted in the main checkout.
- S2, Edit/Write under `.git/`: always "a sensitive file", prompting even with an
  `Edit(//abs/.git/lanes/**)` or `Edit(**/.git/lanes/**)` allow rule (Write rules don't apply to
  file checks at all). Hence the in-lane `.lane/` above. A Write to `<lane>/.lane/STATUS.md` in
  acceptEdits mode succeeds with no prompt, and the shared `info/exclude` hides it
  (`git status --ignored` shows `!! .lane/`).
- S3, `excludedCommands`: `lane *` goes in, beside `delegation-ledger *` (hq-open is excluded the same way in hq's own settings). `lane new`
  fetches and `lane ls` asks gh for PR state, and both need the credential the sandbox hides. A
  sandboxed (piped) call still works for the local subcommands and says what it skipped.
  (Superseded: PR 2 "As built" narrowed the exclusion, and `new` now refuses sandboxed.)
- S4, compaction: a SessionStart hook matched on `compact` gets its `additionalContext` to the
  model after `/compact` (`/compact` piped into `claude -p --resume` triggers a real compaction).
  `lane-identity.sh` on `compact` is therefore the safety net for an unplanned auto-compact.
- Session facts for `handoff-check` and PR 3: `~/.claude/sessions/<pid>.json` carries `sessionId`,
  `cwd`, `startedAt` (ms), `status` (`idle` and others), `tmux` (`session:@window.%pane`) and
  `messagingSocketPath`.

**As built (2026-10-11), where it differs from the list below:** the guard denies every Edit-tool
write under `<common-dir>/lanes/` outright and lints relative phrases in `.lane/` files and every
checkout's root STATUS.md; `lane adopt` takes `--id` and finishes a `setup-failed` lane; `merged()`
became `closable()` with states `merged`, `closed` (an adopted lane with nothing past
`origin/main`) and `abandoned` (`--abandon` only), and a lane made by `new` needs commits past its
base; `ls` also flags `setup-failed`; `new` takes `--goal`, `--files`, `--overlaps`,
`--done-when` and `--constraints`; the mirror never follows symlinks and refuses a symlinked
`.lane`. `docs/lanes.md` is the as-built reference.

**New files:**
- `skills/lanes/scripts/lane`: Python stdlib (`tomllib`, `fcntl`, `subprocess`), installed to
  `~/.local/bin` by the existing bin-link loop in `setup.sh` (the `codex-delegate,delegation-ledger,gh-public` line). Subcommands:
  - `init --root --setup --ports --cap`
  - `new <id> --branch <b> [--claim #n ...]`: fetch; `worktree add -b` from `origin/main`;
    `--unset-upstream`; copy the main checkout's files matched by `.worktreeinclude` (Claude Code's
    own convention: gitignored files such as `.claude/settings.local.json`, so the lane session
    keeps Hayden's local rules); seed `.lane/STATUS.md` from the template with the brief; port;
    setup; record; print the `cd … && claude` line.
  - `adopt <path>`: registers the work repo's existing lanes.
  - `ls [--json]`: the board, with flags `stale` (worktree gone), `rebase` (behind after a merge),
    `conflict` (a double claim), `orphan` (no live session).
  - `whoami`, `claim`, `release`, `who <req>`, `note` (append a timestamped line to the lane's
    STATUS.md).
  - `done <id>`: refuse unless merged or `--abandon`; refuse if a process has its cwd inside the
    lane (`/proc/*/cwd`); warn about references into `<lane>/work` from other lanes; archive the
    record; `worktree remove` without `--force`; delete the branch.
- `hooks/lane-identity.sh`, SessionStart `startup|resume|clear|compact`:
  - It resolves the lane from the payload's `cwd` via `git rev-parse --path-format=absolute
    --git-common-dir --show-toplevel` and the matching `lane.json`.
  - In a lane, it injects: "You are lane `<id>`: branch, claims, port, your record path. Other
    lanes' records are read-only. Ownership comes from `lane who`."
  - It appends the session id to `sessions[]`.
  - The same script, registered on Stop and SessionEnd, refreshes `lanes/<id>/mirror/` from
    `.lane/` (hooks run outside the sandbox) and stamps the session's end into `lane.json`.
  - In a main checkout that has lanes, it injects a one-line board summary.
  - With no lanes, it stays silent.
- `hooks/lane-guard.sh` + `hooks/lane_guard.py`, PreToolUse `Edit|Write|MultiEdit`:
  - Deny writes to another lane's `.lane/**` (and to anything under `<common-dir>/lanes/`)
    from a session whose lane is not that lane.
  - Deny relative-identity phrases in any write to `lanes/**` or to the STATUS.md of a repo with
    lanes. The deny message says to name the lane id.
  - Keep the phrase list tight: `(an)?other (claude )?session`, `this session`,
    `the other (lane|session)`, `my (lane|session)`.
  - Mirror `overwrite_guard.py`'s structure and logging (`lane-guard.log`).
- `skills/lanes/SKILL.md`: the operating guide (the five invariants, lifecycle, a cheat sheet, and
  what to write where). `docs/lanes.md`: the design, the spike results, and why (copied from this
  plan, which the next plan overwrites; the communication-model table is its core).
- `templates/LANE.md`, with sections Brief, State, Decisions, Asks for Hayden, Not mine, Next.
- `templates/STATUS.md`, restructured as Direction, Backlog, Lanes (one derived line), Asks,
  Decisions, Blocked, Notes. A repo with no lanes uses it as-is.
- `lane asks` (all lanes' open asks, one list) and `lane ls --requests`. Both read records only.
- `tests/lanes/`: unittest with a temporary bare origin plus clone, no network.
  - `new`/`adopt`/`ls`/`done` round trip.
  - Stale detection after a manual `worktree remove`.
  - Claim conflict under concurrent `claim` calls (the lock).
  - `whoami` from nested dirs and from `main`.
  - Guard matrix: own record / other record / main STATUS × relative phrase / clean text.
  - The identity hook's output for a lane, for main with lanes, and for a plain repo.

**Edits:**
- `settings.json`: register both hooks. Add `lane *` to `excludedCommands` (S3). Hayden
  applies any allow-rule line the classifier refuses.
- `CLAUDE.md:23`, session start: "if the SessionStart hook names your lane, read your lane record
  first; STATUS.md is project direction, never your state". Also rename "fast lane / full lane"
  to "fast track / full track" (in CLAUDE.md, `codex/AGENTS.md` and handoff SKILL.md:18) so
  "lane" has one meaning.
- `skills/handoff/SKILL.md` gets a worktree-aware mode. Hayden asked for this mid-plan: the lead
  orchestrates sessions under his permission, so every lane must hand off completely, and that
  has to be checkable rather than trusted.
  - Step 0: detect the context with `lane whoami`: a lane, `main` with lanes, or a plain repo.
  - Step 1: in a lane, the range is `origin/main..HEAD` on the lane's branch.
  - Step 3: in a lane, update the lane's record: the Next block, decisions with pointers
    (artifact paths, session ids), and not-mine notes. Do not update STATUS.md. Touch the global
    STATUS only for backlog or direction items no lane owns, using absolute names.
  - Step 5: commit on the lane branch. The record is outside the tree, so nothing to stage for it.
  - After a merge ("merged, cleanup and handoff"):
    1. Write the final outcome into the record.
    2. Add one line to the global backlog naming the lane id and PR.
    3. Propose `lane done <id>`. Cleanup still needs Hayden's nod.
  - The last step is always `handoff-check`. Handoff is not done until it passes.
  - Add Common Mistakes rows: "wrote 'another session': name the lane id"; "updated STATUS.md
    from a lane"; "said done without running handoff-check".
- `skills/handoff/scripts/handoff-check`, new. It works in a lane, in main with lanes, and in a
  plain repo, so `/pass` can use it anywhere. It checks:
  - the working tree is clean, or every leftover is named in the record;
  - the status file (the lane record, else STATUS.md) was written after HEAD's commit time and
    during this session (the session's start time comes from `~/.claude/sessions/<pid>.json`;
    a spike confirms the field);
  - a non-empty Next block exists;
  - there is no relative-identity phrase (the shared `lanelib.relative_phrases` and `prose_only`, also used by the guard and `lane note`);
  - in a lane, `lane.json` claims match the record, and an unpushed branch is noted in the record
    (a warning, not a failure, since pushes need Hayden).
  - It exits non-zero and lists each gap. Tests cover each check's pass and fail.
- `lane ls` gets a `handoff?` flag: the lane's last commit, or its last session end, is newer
  than its record. `lane-identity.sh` also stamps a session's end into `lane.json` (a SessionEnd
  entry), so the lead sees a lane whose session ended without a handoff.
- README: a "Lanes" section.

**Verify:**
- `python3 -m unittest discover -s tests/lanes -t tests/lanes`, plus the existing `tests/setup`
  and `tests/delegation`.
- Replay the guard's phrase list against the 270 real STATUS edits in the work repo's transcripts:
  report the would-deny lines, and check each is a real relative claim (target: no false denies
  on lane-free text).
- Install from the branch, then smoke test in a scratch repo. `lane init`/`new`; open
  `claude` in the lane. Confirm the identity line appears, a relative phrase is denied, an
  edit to another lane's record is denied, and `git commit` works sandboxed with no extra rule (S1).

## PR 2: the lead (`feat/lanes-lead`)

**As built (2026-10-11), where it differs from the list below** (Hayden's calls in the planning
session):
- `lane open` stores no window. `lane ls` derives a WINDOW column from the live session's
  `tmux` field (invariant 4: a stored window id drifts when the window closes or renumbers);
  lane.json gets only an `opened` time. The session starts in plan mode.
- `lane *` left `excludedCommands` (PR 1 put it there, S3). Only `init`, `new`, `adopt`, `ls`,
  `open` and `done` are excluded, so `lane lock -- <cmd>` runs sandboxed: under `lane *` any
  wrapped command ran sandbox-off without the `dangerouslyDisableSandbox` flag the delete guard
  checks.
- The lanes config left the common dir for `$XDG_STATE_HOME/dotclaude/lanes/<repo>-<hash>.toml`.
  `new` and `adopt` run its `setup` (and `new` makes a worktree at its `root`) sandbox-off, so it
  lives where sandboxed Bash can't write, and only a bare `lane init` writes it. A hash pin of the
  old file was the other option, rejected: a bare `lane init` would re-pin whatever the file held.
- What stays sandbox-writable is checked before sandbox-off code acts on it (docs/lanes.md S3):
  every `lane.json` on load, a lane's path before `open`, the setup, the copy or `done` act in
  it, and the `.worktreeinclude` copy by directory fd. `new` refuses when the fetch fails
  (Hayden's call): a lane branches only from the commit the remote reports, never a local ref.
  It branches from that sha, so PR 1's `--unset-upstream` step is gone (no upstream is set).
- Locks live in `<common-dir>/lanes/_locks/<name>` (the leading `_` can't collide with a lane
  id), and the lanes config's `locks` lists the names `lane lock` accepts (`lane init --locks`). An
  unlisted name is refused, since a typo would split the mutual exclusion. A waiter prints the
  holder (lane id, command, start time); `--wait` gives up with 75.
- The ledger keeps separate `parent_root`/`parent_before`/`parent_after` fields, so the audit
  names the lane (`main_status` became `main_checkout` plus `checkout_status`), and the audit
  checks every activation, not only an agent's latest. Both layers find the parent's checkout through `delegation_common.session_toplevel`
  (no import of the lanes skill: the policy hook fails closed).
- `docs/lanes.md` and `docs/delegation.md` are the as-built references.

- `lane open <id> [--focus]`: an `hq-open` clone. Run `tmux new-window -d -c <lane path> -n <id>
  claude "<prompt>"`, where the prompt is "Read your lane record `<path>`, then plan the brief it
  holds". (As built: no window stored; see above.)
- `lane lock <name> -- <cmd>`: flock under `<common-dir>/lanes/locks/`, for shared gates (a
  browser-driven test gate) and anything else that can't run twice. The lanes config lists the known
  resources, and the skill says to wrap gate runs.
- The lead section of `skills/lanes/SKILL.md`:
  - **Triage:** collect the requests, explore the code to estimate the files each touches, group
    them by overlap, and pick lane ids and branches.
  - **Propose:** show a table (lane, branch, requests, files, overlaps, merge order) and wait for
    Hayden's approval.
  - **Open:** `lane new --claim …` writes the brief into each new record, then `lane open`.
  - **Cap:** keep a backlog beyond the live-lane cap, set in the lanes config (default 4).
  - **Hand-back gate:** the lead treats a lane as handed back only when that lane's
    `handoff-check` passes and `lane ls` shows no `handoff?` flag. Otherwise it messages the lane
    (or tells Hayden, if the session is gone) before it orders a merge or closes the lane.
  - **Watch and order:** watch `lane ls`. Keep the merge order in the lead's backlog. After each
    merge, message the remaining lanes ("main moved to `<sha>`, rebase; renumber the version if
    taken"). The board's `rebase` flag is the truth, and the message is only a nudge.
- **Context management across lanes:** moved to PR 4 ("The lead"), since it needs the watcher.
- **Delegation guardrails reach the parent lane** (found 2026-10-11 by a live probe: a `claude -p`
  session in a lane spawned a `writer`). The writer's worktree lands under the main checkout's
  `.claude/worktrees/`, branched from the lane's HEAD (so the stale-base trap is gone for
  lane-rooted sessions). Two layers still assume the session lives in the main checkout:
  - `subagent-policy` `Analyzer.main_root` (the outermost checkout, from the writer's worktree
    path) is the main checkout, so a writer's literal-path Bash write into the parent lane isn't
    denied (the sandbox allows it: the lane is the session's cwd). File-tool writes outside the
    worktree are still denied everywhere.
  - `delegation-ledger` `main_status` hashes the main checkout's `git status`, so a writer's write
    into the lane goes unflagged by `audit`.
  Fix: both also cover the parent session's toplevel (from `~/.claude/sessions/<pid>.json` `cwd`
  by session id, else the payload's), with tests in `tests/delegation`.
- Lanes still use `writer` subagents for short chunks. The skill notes the stale-base trap
  (`worktree.baseRef` and the work repo's recipe).
- **Verify:** unit tests for `lock` (a second holder blocks or times out) and for `open --print`.
  A live run: the lead triages three fake requests in a scratch repo, proposes, opens two lanes,
  and both sessions start with their identity line.

## PR 3: `/pass` (`feat/pass`)

**As built (2026-10-12), where it differs from the lists below.** The script's docstring and
`skills/pass/SKILL.md` are the as-built reference. Five review rounds (34 findings: 32 fixed
here; one, the process command line, checked live and documented as a limit; one
excludedCommands question left to the private sandbox follow-up's step 1; the last round found
nothing medium or worse) and live runs shaped these:
- **The turn's end comes from Claude Code's per-session file** (`~/.claude/sessions/<pid>.json`),
  not tmux's per-window `@claude_state`. The window state reads `idle` on a hook-blocked Stop,
  during a `/compact`, and for any split pane. At the prompt the file reads `idle`, or `shell`
  while a background shell runs (found live: a compact waiter sat until its timeout). The
  waiter also checks the session id, `procStart` and pane, and runs a final re-check right
  before acting: the same `statusUpdatedAt`, the pane still running that claude, not in copy
  mode, and no unsent draft in the input box (a dim ghost suggestion isn't one).
- **Background work comes from the Stop payload, not the process tree.** In-process agents are
  no child process. `hooks/stop-ring.sh` writes a per-session stop record (time, task labels,
  transcript path), and a plain pass drops `busy` on any task but `dream`, a teammate included.
- **A prompt typed after the call drops the pass** (`resumed`): a typed user entry, or a
  mid-turn `queue-operation` enqueue or `queued_command` attachment. The approval and the mode
  are read at act time.
- **Approval is per step:** only the Next block's first item, dated within the session and not
  in the future. `handoff-check` fails a malformed, stale or future marker, and one it can't date
  against a session start.
- **Single flight:** the waiter holds a per-session flock; `pass-respawn -C <dir> --cancel` ends
  a pending pass on a verified pid. Once acting begins it ignores SIGTERM and finishes, and a
  late `--cancel` says `too-late`.
- **Compact re-checks before its second half:** copy mode or a draft after the 1 s gap shows the
  resume prompt instead of typing it (`partial`).
- **Trust:** writable roots cover the launch dir and `additionalDirectories`, with user and
  managed `denyWrite` carved out (otherwise every pass in dotclaude would refuse); the script and
  `handoff-check` refuse when sandbox-writable, and so does a sandbox-writable `--settings` file
  the session was launched with (its `--add-dir` dirs count as writable); children get a pinned
  PATH; both scripts run under `/usr/bin/python3 -I`; prompts carry only computed paths.
- **Outcomes** grew `gone`, `failed`, `error`, `cancelled`, `partial` and `too-late`.
- **A one-word "pass" doesn't trigger** (it is also "no thanks"); the typed trigger needs an
  action word before "pass".
- **An allow rule, `Bash(pass-respawn -C *)`:** the auto-mode classifier refused a bare call as
  "Create Unsafe Agents" after allowing one, so the skill always calls `pass-respawn -C
  <toplevel> [--compact]`. Installing a new allow rule is Hayden's step (the classifier refused
  the `setup.sh` run as "Auto-Mode Bypass").
- **The sandbox's `.claude/hooks` stub** joined `git/sandbox-stubs.ignore`. Untracked, it failed
  `handoff-check`'s clean check in every repo.
- **Live runs** (a scratch window): a plain pass respawned in plan mode with the Star carried; an
  approved first item resumed in the default mode; compact typed `/compact` and the resume
  prompt, which entered plan mode; `--cancel` ended a pending waiter; a `!pass-respawn` typed in
  bash mode works too (its output starts a model turn, which is harmless).

**Changes from the 2026-10-11 design** (Hayden, 2026-10-12):
- Auto-pass (the context watcher, its config, `/autopass`) moved to PR 4.
- **Work after a handoff makes it stale.** The detached respawner re-runs `handoff-check` right
  before it acts, and drops the pass (a `tmux display-message`, a `stale` log line, no respawn)
  if the tree got dirty or a commit landed after the status file. Between the call and idle the
  turn can keep editing, and a queued prompt can restart it.
- **Delta handoff** (from the `/release` pattern in the work repos: a second handoff after a
  release is needed only sometimes).
  - Review fixes, a rebase, a chat decision or a failed deploy make a handoff stale. A clean PR,
    merge and deploy don't, because `gh` can derive them.
  - `handoff-check` is the staleness detector.
  - The handoff skill gets a delta mode: the range is the last status commit to HEAD, plus
    decisions from chat since then. It skips the drift sweep when the range touches no code or
    docs.
  - `/pass` runs the delta mode when a handoff already ran in the session.
  - The release skill in the work repos changes in its own PR there, after this one: its step-5
    handoff writes the post-release Next block, and step 7 ends with `handoff-check` and "did
    anything get decided or found since the handoff?".
- **Both modes wait for idle.** The plain respawn also waits for the turn's Stop (`@claude_state`
  `busy` then `idle`, a 1 s settle and a recheck), not only a fixed settle, so the final reply and
  the Stop hooks finish before `-k`.
- **The Star carries across a pass.** `tmux/claude-saved` re-keys a starred chat only on a
  `clear` start; a respawn is a `startup`, which today drops the ★. `pass-respawn` leaves a
  one-shot carry marker, and the hook honors it the way it handles `clear`.
- **Classifier misfires found by the PR 4 calibration get fixed here**, since the trigger work
  touches `handoff_reminder.py` anyway:
  - a deferred handoff ("do a handoff at the time");
  - a question ("ready to clear context?");
  - long prompts firing on a non-handoff last clause.

- `skills/pass/SKILL.md` (user-invocable):
  1. Refuse if background tasks are in flight or `$TMUX_PANE` is unset (then print the manual
     line instead).
  2. Run the handoff skill to completion (it commits).
  3. Run `handoff-check`. If it fails, fix the named gaps and re-run it. Never respawn on a
     failing check, because the respawn throws away the context that could fix it.
  4. Run `pass-respawn`. It also runs `handoff-check` itself and refuses on a non-zero exit, so
     the gate holds even if the skill's steps are skipped.
- `skills/pass/scripts/pass-respawn`:
  - Build the resume prompt. In a lane: "Read your lane record, plan the next step." Otherwise:
    "Read STATUS.md (and PLAN.md if present), plan the next step."
  - Detach (double fork), wait a short settle, then run
    `tmux respawn-pane -k -t $TMUX_PANE -c <cwd> claude --permission-mode plan "<prompt>"`.
  - Runs as a bare command in `excludedCommands` (it needs the tmux socket).
  - **Resume mode** (Hayden's call, 2026-10-11): plan mode, unless the Next block carries
    `(approved by Hayden <date>)` for that exact step. Then it resumes in the normal mode and
    continues.
    - The handoff skill writes that marker only when Hayden approved the step in this session,
      citing the approval. It never infers one.
    - `handoff-check` fails a marker with no date.
    - Anything new or unapproved stops for Hayden's plan approval, so chained passes always hit
      a human checkpoint at each new step.
- **Two modes; a handoff always comes first in both.** Research (2026-10-11) says decide by
  where the state lives: never rely on a summary for exact facts, and clear at a task boundary or
  after about two failed corrections. Hayden's history: 108 `/compact` against 309 `/clear`,
  usually as "handoff → /compact → continue", and sometimes "merged, cleanup → /compact →
  continue on #110", which carries a finished task's beliefs into the next one.

  | Mode | Mechanism | Use when |
  |---|---|---|
  | `pass` (clear, the default) | handoff → `handoff-check` → `respawn-pane` with a fresh `claude` | task boundary (merged, a new request), context poisoned (corrected twice), a lane at a boundary, an approved plan ready to run fresh |
  | `pass compact` | handoff → `handoff-check` → (detached, after the turn goes idle) `tmux send-keys` types `/compact <focus>`, then the resume prompt | same task mid-flight with tacit state (ruled-out hypotheses, half-built understanding), background tasks in flight (they survive a compact and die on a respawn), waiting on a build |

  - The model can't run `/compact` itself: built-ins aren't reachable through the Skill tool. So
    the script types it.
  - The focus text tells the summary to keep failed approaches, exact identifiers and the repro
    command, and points at the record. The record holds the exact facts; the summary holds the
    feel.
  - **Plan mode for the compact variant:** the resume prompt tells the model to call
    `EnterPlanMode` first, unless the Next step is pre-approved. That avoids flaky Shift+Tab
    presses.
  - **Idle detection:** the script waits for the pane's idle state, which the existing tmux state
    hooks already set ([[dotclaude-tmux-indicator]]); a spike confirms it. Then it sends the
    keys.
  - The skill recommends a mode from the table, and Hayden can name one.
- **Triggers.** `/pass` and a typed "handoff and pass" do the same thing, because pass includes
  handoff. "pass compact" / "handoff and compact" select the compact mode. A bare "handoff" never
  respawns or compacts.
  - "pass" is a risky trigger word. 63 of 5,661 typed prompts use it, almost all as "a pass"
    ("Handoff for a later pass to fix this", "a graphics/image pass").
  - So the natural-language trigger only fires when "pass" is the bare last item of a terse list
    ("handoff and pass", "commit, pass"). As built, a one-word "pass" doesn't fire: it is also
    "no thanks" (round-3 review), so an action word must come before it in the same sentence;
    `/pass` itself always works.
  - The `handoff_reminder.py` classifier gets that end-anchored rule, and the skill's description
    says the same.
  - Gate: replay all of `history.jsonl` with zero hits in the "a pass" sense ([[hayden-prompt-style]],
    [[fix-every-review-finding]]).
- **Spikes first** (in a scratch tmux window running an interactive `claude`):

  | # | Question | Expected |
  |---|---|---|
  | S1 | `respawn-pane -k` on a live claude pane: the old session's SessionEnd reason, the new one's SessionStart source | `other`, then `startup`; `open-sessions/` marks the old entry and writes a new one for the same pane (restore keeps the newest per pane, so a pass is no death); no stray ring in `ring.log` |
  | S2 | tmux 3.7c `respawn-pane -c <cwd> -- <abs claude> --permission-mode plan "<prompt>"` | argv form works; the pane starts in plan mode with the prompt and has `TMUX_PANE` |
  | S3 | `@claude_state` seen from a detached child of a Bash call | `busy`, then `idle` after the turn's Stop; a queued input flips it back inside the settle |
  | S4 | `send-keys` of `/compact <focus>` into an idle pane, then the resume prompt | how to tell the compact finished, and whether typed input queues during it |
  | S5 | a background `python3 -I -c 'import time; time.sleep(120)'` across `/compact` | it survives |
  | S6 | can `pass-respawn` see in-flight background tasks (descendants of the pane's claude, minus MCP servers)? | if cleanly, plain pass refuses mechanically; otherwise the refusal stays in the skill |

- **Spike results** (2026-10-12, Claude Code 2.1.296, tmux 3.7c; a scratch window driven from
  outside, with a `--settings` probe logging hook events):
  - S1: `respawn-pane -k` sends the old session SessionEnd `other`, and the new one starts as
    `startup` in the same pane. `open-sessions/` marks the old entry and writes the new one, so
    restore (newest per pane) sees no death. `ring.log` rang only on real turns' Stops. The ★
    dropped: the saved chat kept `starred` with `tab: None`, which confirms the carry is needed.
  - S2: the argv form `respawn-pane -k -t <pane> -c <cwd> -- <abs claude> --permission-mode plan
    <prompt>` works. The pane came back in plan mode with the prompt submitted, and it has
    `TMUX_PANE`.
  - S3: `@claude_state` goes `busy` at UserPromptSubmit and `idle` within 0.2 s of the Stop, as
    seen from a poller outside the session.
  - S4: `/compact <focus>` typed into an idle pane runs, and a prompt typed 1 s later queues
    ("Press up to edit queued messages") and runs right after SessionStart `compact`. So the
    script types both and needs no wait for the compact. `@claude_state` stays `idle` while
    compacting, so the state can't show a compact in progress.
  - S5: a background `sleep` survived the compact (`background_tasks` still listed it at the next
    Stop).
  - S6: a background Bash task is a `bwrap` child of the pane's `claude`. MCP servers are `npm`
    and `socat` children, and a sandbox-off command is a shell child. So a plain pass refuses
    mechanically: at act time, any `bwrap` or shell child of the claude process means work is in
    flight. `/exit` asks before stopping background work, but `respawn-pane -k` would kill it
    silently, which is why the check matters.

- **Verify:**
  - Unit tests:
    - The resume-mode choice: approved, unapproved, a malformed marker.
    - `pass-respawn --print` in a lane and a plain repo; the waiter against a fake `tmux`
      (`busy` then `idle`, a queued restart, a timeout); the refusals (no `TMUX_PANE`, a failing
      `handoff-check`); staleness (an edit or a commit after the call drops the pass, and no
      respawn reaches the fake `tmux`).
    - The Star carry: match, stale, wrong pane, consumed once.
    - The trigger classifier, the calibration's misfires, plus the full `history.jsonl` replay.
  - A live run in a scratch tmux window: `/pass`, then the handoff commit; the pane comes back in
    plan mode with the prompt. `ring.log` and the restore log stay sane, and a Star survives.
  - A second run with an approved Next resumes in normal mode.
  - `pass compact` with a background `python3 -I -c 'import time; time.sleep(120)'` in flight:
    the handoff commits, `/compact` is typed only after idle, the background task survives, and
    the resumed turn enters plan mode.

## PR 4: auto-pass (`feat/autopass`, after PR 3)

**As built (2026-10-12), where it differs from the design below.** The module docstrings
(`hooks/context_watch.py`, `hooks/autopass_state.py`, `hooks/stop_ring.py`,
`hooks/pass_banner.py`, `hooks/md_render.py`, `tmux/pass-last`, `pass-respawn`) and README
"Auto-pass" are the reference. It shipped as five writer parts, each reviewed until no finding
was medium or worse: part 1 in 3 rounds, 2a in 3, 2b in 2, 2c in 1 and 3 in 5.
- **Tiers scale with the window.** The window is min(the model window the widget writes into
  `ctx/<sid>.json`, `autoCompactWindow`).
  - compact_at = window - 33k; hard = compact_at - min(47k, 8%); wrap = hard - min(40k, 7%);
    soft = window / 2. That gives 300/480/520/567k at 600k and 100/137/151/167k at 200k.
  - The watcher stays quiet when soft >= wrap or wrap < 60k.
  - A tier re-arms below tier - min(50k, tier/4). The hard tier repeats every min(20k, half
    the gap to compact_at).
- **The hard repeat pauses during a pass:** after a pass skill call, a command that starts
  with `pass-respawn`, or a typed `/pass` (a user entry starting with Claude Code's
  `<command-message>` block, spike A6). It resumes 40k later if no pass comes.
- **Work in flight has three states.** Busy (subagent, shell, workflow, cloud session) keeps
  soft and wrap-up quiet. Blocked (any other task but `dream`, from
  `lanelib.plain_pass_blockers`, which `pass-respawn` also uses) and unknown (a tool call with
  no stop record in the last 10 minutes) both get compact-mode texts.
- **Coverage:** `-p` and `--bg` sessions get a count but never a nudge. Locks are per
  session; `decide()` runs outside them and is cached 60 s, keyed by the tab flag's
  `generation`. The lead's main checkout is on by default, like a lane.
- **`/autopass`** is `skills/autopass` (`disable-model-invocation`) plus a UserPromptSubmit hook
  that blocks it. `tmux-state.sh` doesn't mark the tab busy for it.
- **The ctx file** `ctx/<sid>.json` holds `tokens` and `time` from the watcher, and `window`
  and `window_at` from the widget, merged under `ctx-watch/<sid>.ctx.lock`. An older count never
  replaces a newer one.
- **The last reply is the last turn's replies** (see below). The popup shows the last 5 turns.
- **A refused pass is loud** (held notice plus toast) except `cancelled`, `resumed` and `gone`,
  which Hayden caused. The pass skill stops leftover tasks before a plain pass and never
  promises a restart.
- **Not built:** the lead nudging an idle lane past soft (by hand for now; `lane ls` shows CTX
  and STATE).

Hayden's ask: pass at the end of a session without being told. Designed with Hayden on
2026-10-12, from his own pattern and a calibration over his transcripts.

**Hayden's pattern.** He thinks in absolute tokens, not percentages. Past about 300k with the
task done, he hands off. Past 300k mid-plan with little left, he finishes first, usually by
500k to 550k. He always wants the handoff before auto-compact. A handoff costs 5k to 60k tokens,
depending on how much new work it covers.

**Calibration** (2026-10-12, read-only, transcripts from 2026-09-09 on; 151 sessions passed 200k,
all on 1M-window models). Context at each event, in thousands of tokens:

| Event | n | p25 | p50 | p75 | p90 | max |
|---|---|---|---|---|---|---|
| handoff | 241 | 273 | 354 | 439 | 499 | 565 |
| `/clear` | 112 | 313 | 371 | 458 | 497 | 548 |
| `/compact` | 113 | 354 | 442 | 500 | 543 | 565 |

- A handoff costs p50 22k, p90 47k, max 208k. The number of edits barely predicts it.
- **Auto-compact fires at about 567k, not at `autoCompactWindow` (600k):** 33 of 38 fell between
  566k and 571k, so Claude Code keeps a buffer of about 33k.
- Nine handoffs typed at 515k or later overflowed into auto-compact.
- 19 of 38 auto-compacts had no handoff before them, several in long unattended runs that never
  reach a Stop.
- After crossing 300k, the handoff came a median of 2 prompts and 115k tokens later, so a turn
  runs about 45k (derived, not measured).

**Signal.**
- Absolute tokens: the transcript's last main-chain assistant `usage` (input, cache read and
  cache creation), read by the hook through the payload's `transcript_path`.
- This replaces the statusline writer of the 2026-10-11 design. That writer exists only while a
  pane renders the statusline, so `claude -p`, background sessions and unwatched lanes would get
  nothing. The transcript format is internal: a fixture pins it, and a parse miss stays quiet.
- Raw `used_percentage` was rejected: it is a share of the 1M window, so a 60% threshold would
  sit at auto-compact itself.
- The hook writes the count to `$XDG_STATE_HOME/dotclaude/ctx/<session_id>`, for `lane ls`.

**Three tiers**, all derived from `autoCompactWindow`, so they move together if it changes. The
token values below are the design values at a 600k window; "As built" above has the formulas that
scale with the window:

| Tier | Tokens | Fires on | What the model is told |
|---|---|---|---|
| Soft | 300k | Stop, once per crossing | Done end to end: run the pass skill. A small remainder: keep going. Just asked Hayden something: do nothing. The model judges the boundary; the hook can't. |
| Wrap-up | window − 120k (480k) | Stop and PostToolUse, once | Finish the step you're on and don't start a new one. If more than this step is left, hand off now (compact mode if mid-task). |
| Hard | window − 80k (520k) | Stop and PostToolUse, re-armed every +20k | Hand off now: `pass compact` mid-task, `pass` at a boundary. |

- The hard margin is Claude Code's ~33k buffer plus the p90 handoff cost (47k). It is fixed, not
  scaled to the work (Hayden's call). 600k minus 60k, the first idea, would leave only 27k.
- Wrap-up at 480k leaves 40k, about one turn, before the hard tier. 500k was rejected: it leaves
  under half a turn, and it is Hayden's p90 handoff, so it mostly lands after the decision.
- PostToolUse is what reaches long autonomous turns (subagent-driven execution, fix loops),
  which would otherwise cross into auto-compact before any Stop.

**The `/autopass` toggle** (Hayden, 2026-10-12).
- `/autopass on|off|status` is typed in chat. A UserPromptSubmit hook catches it, writes the flag
  (hooks run outside the sandbox, which can't write the state dir), and blocks the prompt with a
  one-line confirmation. So a toggle costs no model turn and no context.
  - Spike first: does UserPromptSubmit see a defined slash command before it expands? If not,
    use a mod's slash command (the `plugin-authoring` skill), which also runs locally.
- **On:**
  - all three tiers block or inject as above;
  - the model may run the pass skill on its own (it still respawns into plan mode, so Hayden
    approves the next step).
- **Off:**
  - no blocks, no injected context, and no pass the user didn't ask for;
  - one exception, the safety net (Hayden's call): a single non-blocking line at the hard tier,
    "context 520k, auto-compact at about 567k: hand off now", not re-armed.
- **Either way:**
  - the token count is written to `ctx/<sid>`, and the ctx widget changes color at each tier
    (passive);
  - `/pass`, the typed triggers and the handoff reminder work unchanged.
- **Scope: per tab** (Hayden's call).
  - A pass respawn and `/clear` both start a new session id, so a per-session flag would switch
    itself off after the first pass.
  - The flag is keyed by the tab (socket, server start, server pid, pane), the way the Star
    carries, and dies with the tab.
  - Precedence: the tab's toggle, then the repo's lanes config (`autopass = true` by default in
    lanes), then the global default in `~/.config/dotclaude/pass.toml` (off).
- `/autopass status` prints the token count, the next tier, on or off, and which level set it.

**Guards.**
- A subagent's events are ignored.
- The hook stays quiet while background work runs (`stop-ring.sh`'s set, so a lingering monitor
  doesn't mute it; a Monitor arrives as `shell` and is relabeled, A10). The one exception is the hard tier, which then suggests `pass compact`,
  since a compact keeps background tasks alive.
- It keeps crossings in its own record, the way `watch-guard` keeps its blocks, not through
  `stop_hook_active`.
- A compact, or a new session id, drops the count and re-arms it.
- Stop `decision: block` keeps the turn going ([[cc-stop-hook-facts]]).

**The lead** (moved from PR 2).
- Each lane manages itself through the watcher (autopass is on by default in lanes).
- `lane ls` shows each lane's context from `ctx/<sid>`, plus its idle or working state.
- A lane past the soft tier and idle gets a message from the lead: "context N k, run /pass".
- The lead never respawns another lane's pane, because only that lane holds the context its
  handoff needs. A lane whose session died with `handoff?` set goes to Hayden's asks.
- The lead passes itself the same way. Its state lives in the project STATUS and the board.

**The last reply across a pass** (Hayden, 2026-10-12: banner and popup, in this PR).
- The problem: a plain pass respawns the pane, so the old session's final reply leaves the screen.
  Auto-pass makes it worse: a pass he didn't ask for wipes a reply he never read. Compact mode
  doesn't need this, because the conversation survives a compact.
- The source: the Stop payload's `last_assistant_message`. A plain pass acts after that Stop, so
  the field holds exactly the reply.
  - `stop-ring.sh` adds it to `stops/<sid>.json` in `replies` (`hooks/stop_ring.py`
    `merge_replies`, 64 KiB per reply). It was first built as one `last_message`; review round 1
    made it `replies` (below).
  - `pass-respawn` (plain mode) copies them to `pass-last/<pane number>.json` (its fields:
    `write_last`'s docstring; part 3 added `prompts`). The file is per tab and not consumed. It is kept
    apart from the one-shot `pass-carry` marker, so two SessionStart hooks never race over one
    file.
- **Banner:** a SessionStart hook (`startup` only; it skips `-p` and subagents) shows the message
  as a `systemMessage`, which Hayden sees and the model doesn't. It needs the same tab, an entry
  under 120 s old and `shown` false, and then sets `shown`.
- **Popup:** `pass-last` opens the tab's message in `display-popup` with `less` (rendered since
  part 3, below). It is bound to
  Ctrl-b Up and has entries in the Ctrl-b Enter menu and the right-click tab menu.
- **Everything since the last prompt, not only the last reply** (review round 1; Hayden's call,
  2026-10-12). One `last_message` per session loses the unread reply when auto-pass blocks a Stop
  and the continued turn ends on "pass armed". Spike A5: a hook-blocked Stop and the Stop that
  ends the continued turn share the payload's `prompt_id` (`stop_hook_active` false, then true).
  So the stop record keeps `replies` (`{prompt_id, text, time}`, the 5 most recent turns, 128
  KiB in all). The banner shows the newest turn's replies, and the popup shows all five turns,
  which puts the reply before a manual `/pass` one key away. `-p` sessions keep none, and
  `stops/` and `pass-last/` are pruned after 7 days.
  - Review round 2: the Stop payload can't tell a typed prompt from a turn a task notice
    started, so the banner said "Last turn's replies", not "since your last prompt" (part 3
    made it "Last turn (HH:MM)" with the prompt, when the transcript has one). A Stop
    with no `prompt_id` is its own group, and a cut inside the newest turn leaves a note.
- Rejected: putting the reply in the resume prompt. That feeds the old session's beliefs back
  into the fresh context, which is what a clear avoids.

**The popup and banner, rendered, with Hayden's prompts** (Hayden, 2026-10-12, part 3).
- The problem: both showed raw markdown (`**`, backticks, `#`) and `less` broke lines mid-word.
  Hayden also wants his own side of each turn, not only the replies.
- **Renderer: stdlib** (Hayden picked it over `rich` after seeing both live: no dependency, so a
  new device works unchanged). One module, `hooks/md_render.py`, imported by `tmux/pass-last`
  and `hooks/pass_banner.py` through their real paths (no new link). It handles what Claude
  writes: `**bold**`, `*italic*`, code spans, links, `#` headings, `-`/`*`/`1.` lists with a
  hanging indent, fenced code (a dim bar, not wrapped), and pipe tables drawn with box lines
  when they fit the width (else the raw rows, dim). It word-wraps by terminal cells (wide
  characters count 2). Control characters are dropped before any escape is added. With no
  color (not a tty), the markup is stripped and nothing else changes.
- **Popup:** a cyan rule with the time per turn, and a bold yellow heavy rule for the last turn.
  `less -R` shows the colors, and the width comes from the popup's tty. Under each rule, the
  turn's prompt: `▌ You:` in green, then the prompt indented under the bar. A turn with no typed
  prompt (a task notice or an agent message started it) says `▌ (no prompt: a background
  notice)`, dim.
- **Banner (spike A9):** a SessionStart `systemMessage` keeps ANSI color. Claude Code draws it
  in gray (`38;5;246`), and a full reset (`0m`) or `39m` (the terminal's default color) drops
  that gray for the rest of the line, so the banner closes bold, italic and underline with their
  own resets (`22m`, `23m`, `24m`) and a color by going back to the gray (`md_render.BANNER_FG`;
  seen live: the gray holds after a code span). Claude Code starts each line gray again, so a
  miss lasts only to the line's end. It starts "Last turn
  (HH:MM)", then `You:` with the prompt's first line (about 100 characters, `…` past that),
  then the replies, rendered to the pane's width less Claude Code's 5-column indent. The 40
  lines and 4 KiB caps still hold, and they count the escapes too.
- **Where prompts come from:** `pass-respawn` reads them at the pass from the transcript it
  already has (`transcript_path`): each main-chain user entry whose `origin.kind` is "human"
  (its `typed_prompt`), matched to the replies' turns by `promptId`. They go into
  `pass-last/<pane>.json` as `prompts: [{prompt_id, text, time}]`. Only the last WIDE (8 MiB)
  of the transcript is read. A typed slash command shows as typed (`/pass compact`), not as its
  `<command-message>` block, and an image shows as `[image]`. Each prompt is cut to 1 KiB or 12
  lines, whichever comes first, ending "… (N more lines)". With no transcript the file has no
  `prompts`, and every turn says no prompt. Rejected: a UserPromptSubmit hook recording each
  prompt, which costs a write per prompt for a popup.

**A refused pass, and leftover monitors** (found live 2026-10-12; Hayden's calls, part 2c).
- What happened: a capella-studio `/pass` was refused (`pass.log`: `outcome=busy busy: waits:
  monitor, monitor, monitor`). Three Monitor tasks were still listed at its Stop, and
  `respawn-pane -k` would kill them silently.
  - The gate was right, but the only notice was a few-second tmux status-line message. It came
    right after a reply that promised "the pane restarts". The label `waits:` was also wrong:
    those were tasks, and `waits` was empty.
- **The skill judges, the script enforces.** Before `pass-respawn`, the pass skill lists the
  session's running background tasks:
  - It stops leftovers whose job is done (`TaskStop`).
  - If any is still in use, it uses compact mode instead.
  - Its reply never promises a restart. It says the pane restarts unless the gate refuses.
  - `pass-respawn` still refuses a plain pass while any task but `dream` runs, so a model that
    skips the check can't kill a live watcher.
- **A refusal is loud:** a tmux message held until a key (`-d 0`) plus the `notify.sh` toast,
  naming the tasks and the fix ("3 monitors running: /pass compact, or stop them"). The label
  becomes `tasks:`.
- The watcher (part 2a) uses `pass-respawn`'s rule, so with tasks in flight its tiers say
  compact mode, never a plain pass that the gate would refuse.

**Spikes first** (a scratch tmux window, driven from outside, with a `--settings` probe hook):

| # | Question | Decides |
|---|---|---|
| A1 | Does UserPromptSubmit see `/autopass on` before it expands? Try it both undefined and defined. Does `decision: block` with a `reason` show the line and cost no model turn? | a hook, or a mod's slash command |
| A2 | Is a SessionStart `systemMessage` shown on a `startup` respawned with a prompt argument, and where? Is a 3-4 KiB message truncated? | the whole reply in the banner, or a head plus "Ctrl-b Up for the rest" |
| A3 | Does the transcript's last main-chain assistant `usage` match the statusline's `current_usage` at a Stop and mid-turn? Is `isSidechain` set on subagent entries? | the parser and its fixture |
| A4 | Does a PostToolUse `additionalContext` reach the model on a main-session tool call? | the wrap-up and hard tiers inside long turns |
| A5 | Does a hook-blocked Stop share the payload's `prompt_id` with the Stop that ends its continuation? | how the banner groups replies into turns |

**Spike results** (2026-10-12, Claude Code 2.1.296, tmux 3.7c; harness in
`~/scratch/autopass-spike/`). The design holds, with one change from A1.
- **A1:** a *defined* command reaches UserPromptSubmit raw (`prompt: "/autopass on"`), and
  `decision: block` with a `reason` shows "UserPromptSubmit operation blocked by hook: <reason>"
  and runs no model turn. An *undefined* `/autopassx` never reaches the hook: Claude Code answers
  "Unknown command". **Change:** `/autopass` ships as a defined command with
  `disable-model-invocation: true`. The hook blocks it. The body runs only if the hook didn't, and
  says the hook isn't installed.
- **A2:** a 3.6 KiB SessionStart `systemMessage` shows in full, untruncated, as "SessionStart:startup
  says: ...". After a `respawn-pane` with a prompt argument it sits above the submitted prompt
  and stays on screen. The model can't see it: a random codeword in the banner came back `NONE`.
  The transcript keeps the text as `hook_success` and `hook_system_message` attachments.
- **A3:** the transcript's last main-chain assistant `usage` sum (input, cache read, cache
  creation) read 41,538 while the statusline showed 41.5k. Subagent entries go to
  `<session>/subagents/agent-<id>.jsonl`, never the main file, and their hook payloads carry
  `agent_id`. A split assistant message repeats its usage on each entry, so the last entry is
  right. Mid-turn, the last entry is the tool_use message, one tool result behind.
- **A4:** a main-session PostToolUse `additionalContext` reached the model (it followed the
  injected instruction in its reply).
- **A5:** yes. The blocked Stop has `stop_hook_active` false and the continuation's Stop has it
  true, with the same `prompt_id`. Recorded in "The last reply across a pass".
- **A6 (a typed skill command):** a typed `/probeskill hello` is one main-chain `user` entry
  (`origin.kind` "human") whose content is the string `<command-message>probeskill
  </command-message>\n<command-name>/probeskill</command-name>\n<command-args>hello
  </command-args>`, followed by an `isMeta` user entry holding the skill's body.
- **A7 (the statusline payload):** `context_window.total_input_tokens` equals the
  `current_usage` sum and the transcript's last usage, after one turn (52,075) and after a
  second (52,252). It is the current context, not a session total. `context_window_size` is
  1,000,000 for Opus 5.5.
- **A8 (the live smoke run, after install): at Stop the turn's last assistant entry is not yet
  readable in the transcript.**
  - What the smoke session (`185d6425`, scratch repo `~/scratch/autopass-smoke`) did:
    - Its first Stop wrote no count: `tokens()` found no assistant entry.
    - Its second Stop wrote 41,501, which is turn 1's count, while turn 2's entry says 41,541.
    - The entries' `timestamp` precedes `stop_hook_summary` by about 90 ms, but the file had
      not caught up when the hook read it.
    - A3 compared counts after the fact, so it missed this.
  - Before the fix: the Stop-time count lagged one turn, so a long final reply could cross a
    tier one Stop late. PostToolUse reads entries already written, so it stayed fresh.
  - **Probe (2026-10-12, `~/scratch/autopass-spike/probe8.py`, 13 Stops in one session):** every
    Stop hook started with the last main-chain user or assistant entry a user's (the prompt, a
    tool result, or a Stop hook's block reason), and the final reply appeared 54 to 112 ms into
    the hook, its text matching `last_assistant_message` each time. Short, tool, ~10k-character
    and blocked-then-continued turns all behaved the same. A child polling past the hook's exit
    saw it at the same moment, so the write isn't gated on the hook.
  - **Fix:** at Stop, while the last main-chain user or assistant entry is a user's (or none
    is in reach, as in an empty file), `context_watch.stop_tokens` re-reads every 25 ms for up to 1.5 s, then logs a line to
    `context-watch.err` and uses the last count. PostToolUse never waits. The probe session's
    `ctx` file then matched each turn's own count.

- **A10 (live smoke, 2026-10-12): a Monitor arrives as a `shell` task.** The Stop payload's
  `background_tasks` gave a Monitor `type: "shell"`, the same as a background `sleep` (fields:
  id, type, status, description, command; no monitor flag), on 2.1.296. The capella refusal
  earlier the same day logged `monitor`, so both labels occur. As `shell` it counted as busy:
  a lingering Monitor kept soft and wrap-up quiet, and the refusal said "1 shell".
  - **Fix (Hayden's call: classify by tool):** `stop_ring.task_types` relabels a `shell` task
    as `monitor` when its id is the `toolUseResult.taskId` of a result answering a Monitor
    call. One backward walk per file, over the transcript and then its subagents'
    transcripts, settles every listed shell id (`"taskId":"<id>"` for a Monitor's result,
    `"backgroundTaskId":"<id>"` for a Bash command's), so a Monitor started early in a long
    session, or by a subagent, still counts. Review round 1 replaced a last-8 MiB scan, which
    missed exactly those; round 2 made it one walk per file with a 2 s budget before the
    subagents' files (0.75 s warm for a 128 MiB transcript that names none of the ids, about
    2.5 s cold). stop-ring's Stop timeout went from 5 to 10 s for that cold read. The stop record, the ring and the
    watcher's Stop check all use it, so `pass-respawn` names the monitor too.

**Verify.**
- `context-watch` on transcript fixtures: below each tier, at each tier once per crossing, the
  hard tier re-arming, off, background work in flight, a subagent event, and a compact re-arming.
- The banner: a match, a stale entry, the wrong tab, shown once. `stop_ring.merge_replies` and its
  caps. `pass-respawn` writes `pass-last`.
- A live run at lowered tiers fires each tier once and ends in a passing `handoff-check`.
- A live `/pass` shows the banner with the old reply, Ctrl-b Up reopens it, and a Star still
  carries.

## After: the work repo's migration (its own PR in that repo, after PR 1 and PR 2 merge)

- `lane init` with the repo's lanes root, its setup command, a port range and its shared gates as locks
  (the concrete values are in the private notes).
- `lane adopt` each live worktree.
- Move each lane's paragraph out of STATUS.md into its record.
- Shrink STATUS.md to direction and backlog.
- Point the repo's lane recipe memory and its guardrails doc at the skill (one
  home per fact).
- Root new lane sessions in the lane (`lane open`), which S1 shows is all the sandbox needs.

## Critical files

New: `skills/lanes/{SKILL.md,scripts/lane}`, `hooks/lane-identity.sh`,
`hooks/{lane-guard.sh,lane_guard.py}`, `templates/LANE.md`, `docs/lanes.md`, `tests/lanes/`,
`skills/pass/{SKILL.md,scripts/pass-respawn}`.
PR 4: the modules "PR 4: auto-pass" lists under "As built" (`hooks/{context_watch.py,
autopass_state.py,stop_ring.py,pass_banner.py,md_render.py}`, `tmux/pass-last`,
`pass-respawn`), with `tests/setup/test_md_render.py`.
Edited: `settings.json`, `CLAUDE.md`, `skills/handoff/SKILL.md`, `templates/STATUS.md`,
`README.md`, `codex/AGENTS.md`, `setup.sh` (only if the bin loop needs the new paths).
Patterns to reuse:
- `hq/bin/hq-open`: the tmux launch and the excludedCommands rationale.
- `hooks/overwrite_guard.py`: guard structure and logging.
- `hooks/session-title.sh:82-128`: resolving a worktree's repo from `.git` files.
- `hooks/session-registry.sh`: the session JSON.
- `setup.sh`'s bin-link loop: installing to bin.

Process: each PR runs as a full-track effort with a `writer` in a worktree and a fresh
`reviewer` per fix round. It opens as a draft and is marked ready after docs, STATUS, install
and the smoke test from the branch. Push and merge only on Hayden's approval.
