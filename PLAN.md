# PLAN: Lanes (parallel sessions in worktrees), handoff-check and /pass

> **Status:** STATUS.md holds where this stands. Approved by Hayden 2026-10-11 (three PRs:
> core `feat/lanes`, lead `feat/lanes-lead`, `/pass` `feat/pass`). The previous PLAN.md (Star and
> Shelve) is in git (`git show fe56e56:PLAN.md`); README holds its as-built behavior.

## Context

Hayden runs several Claude sessions on one repo (a private work repo, with hand-made sibling worktrees as lanes).
Today's (2026-10-11) incident, reconstructed from the transcripts:

- Session A (one lane) wrote into the one shared, gitignored
  `STATUS.md in the main checkout`: "#110 ... another session is building it". That meant
  "a session Hayden will route it to".
- Session B was that intended owner. It read the line as being about someone else. It
  then matched the phrase to the wrong live session through ListAgents (session C, whose first
  prompt read "another session working on request #110") and deferred #110. A mirror flip
  ("another session's formatbar lane") happened earlier the same day.

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
- The work ships as three PRs: core, lead, /pass. Then the work repo migrates in its own repo.

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
| 1 | How do we work here? | Conventions | `CLAUDE.md`, skills, `docs/` (the work repo's `guardrails.md` folds into the lanes skill and CLAUDE.md) | Hayden or a PR | durable |
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

```
<lane worktree>/.lane/          hidden by `/.lane/` in the shared <common-dir>/info/exclude (no repo footprint)
  STATUS.md                     the lane's prose (templates/LANE.md): Brief, State, Decisions, Asks for Hayden, Not mine, Next
  PLAN.md                       the lane's working design (optional)
  artifacts/                    evidence that rulings point at (mocks, shots, gate logs)

<common-dir>/lanes/             CLI-owned; written by `lane` and by hooks, never by the Edit tool
  config.toml                   root (~/code/<repo>-lanes), setup cmd, port range, live-lane cap, base (origin/main)
  .lock                         flock for every CLI write (claims are atomic)
  <id>/lane.json                id, branch, path, base_sha, port, claims[], state, sessions[], created/updated
  <id>/mirror/                  copy of <lane>/.lane/, refreshed by a Stop and SessionEnd hook, so a raw
                                `git worktree remove` (which deletes ignored files) loses nothing
  _closed/<id>-<date>/          lane.json + .lane/ archived on `lane done`
```

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
- S3, `excludedCommands`: `lane *` goes in, beside `delegation-ledger *` and `hq-open`. `lane new`
  fetches and `lane ls` asks gh for PR state, and both need the credential the sandbox hides. A
  sandboxed (piped) call still works for the local subcommands and says what it skipped.
- S4, compaction: a SessionStart hook matched on `compact` gets its `additionalContext` to the
  model after `/compact` (`/compact` piped into `claude -p --resume` triggers a real compaction).
  `lane-identity.sh` on `compact` is therefore the safety net for an unplanned auto-compact.
- Session facts for `handoff-check` and PR 3: `~/.claude/sessions/<pid>.json` carries `sessionId`,
  `cwd`, `startedAt` (ms), `status` (`idle` and others), `tmux` (`session:@window.%pane`) and
  `messagingSocketPath`.

**New files:**
- `skills/lanes/scripts/lane`: Python stdlib (`tomllib`, `fcntl`, `subprocess`), installed to
  `~/.local/bin` by the existing `setup.sh:107-112` loop. Subcommands:
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
- `hooks/lane-guard.sh` + `hooks/lane_guard.py`, PreToolUse `Edit|Write`:
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
  - there is no relative-identity phrase (reuses `lane_guard`'s lint);
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

- `lane open <id> [--focus]`: an `hq-open` clone. Run `tmux new-window -d -c <lane path> -n <id>
  claude "<prompt>"`, where the prompt is "Read your lane record `<path>`, then plan the brief it
  holds". Then record the window in `lane.json`.
- `lane lock <name> -- <cmd>`: flock under `<common-dir>/lanes/locks/`, for shared gates (the
  Chrome typing gate) and anything else that can't run twice. `config.toml` lists the known
  resources, and the skill says to wrap gate runs.
- The lead section of `skills/lanes/SKILL.md`:
  - **Triage:** collect the requests, explore the code to estimate the files each touches, group
    them by overlap, and pick lane ids and branches.
  - **Propose:** show a table (lane, branch, requests, files, overlaps, merge order) and wait for
    Hayden's approval.
  - **Open:** `lane new --claim …` writes the brief into each new record, then `lane open`.
  - **Cap:** keep a backlog beyond the live-lane cap, set in `config.toml` (default 4).
  - **Hand-back gate:** the lead treats a lane as handed back only when that lane's
    `handoff-check` passes and `lane ls` shows no `handoff?` flag. Otherwise it messages the lane
    (or tells Hayden, if the session is gone) before it orders a merge or closes the lane.
  - **Watch and order:** watch `lane ls`. Keep the merge order in the lead's backlog. After each
    merge, message the remaining lanes ("main moved to `<sha>`, rebase; renumber the version if
    taken"). The board's `rebase` flag is the truth, and the message is only a nudge.
- **Context management across lanes.**
  - Each lane manages itself through the PR 3 watcher, with `autopass = true` set in the lanes
    config by default.
  - The lead is the backstop, not the actor. `lane ls` shows each lane's context % (from the live
    session's transcript, using the session id in `lane.json`) and its idle or working state.
  - When a lane is high and idle at a clean boundary, the lead messages it: "context N%, run
    /pass".
  - The lead never respawns another lane's pane, because only the lane holds the context its
    handoff needs. A lane whose session died with `handoff?` set goes to Hayden's asks.
  - The lead passes itself the same way. Its state lives in the project STATUS and the board, so
    a fresh lead resumes cleanly.
  - This bullet lands with PR 3, since it needs the watcher.
- Lanes still use `writer` subagents for short chunks. The skill notes the stale-base trap
  (`worktree.baseRef` and the work repo's recipe).
- **Verify:** unit tests for `lock` (a second holder blocks or times out) and for `open --print`.
  A live run: the lead triages three fake requests in a scratch repo, proposes, opens two lanes,
  and both sessions start with their identity line.

## PR 3: `/pass` (`feat/pass`)

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
    ("handoff and pass", "commit, pass", "pass").
  - The `handoff_reminder.py` classifier gets that end-anchored rule, and the skill's description
    says the same.
  - Gate: replay all of `history.jsonl` with zero hits in the "a pass" sense ([[hayden-prompt-style]],
    [[fix-every-review-finding]]).
- **Opt-in auto-pass on context** (Hayden's ask: pass at the end of a session without being told):
  - `hooks/context-watch.sh`, Stop.
    - Hooks get no context-fill field, but the statusline JSON documents
      `context_window.used_percentage`.
    - So a ccstatusline custom-command widget writes `used_percentage` per session to
      `$XDG_STATE_HOME/dotclaude/ctx/<session_id>`, and the hook reads that file.
    - Fallback: the transcript's last assistant `usage` (an internal format).
    - The same file feeds `lane ls`'s context column.
  - The nudge always says "run the pass skill", so a handoff always comes first. It names the
    mode the table suggests. With background tasks in flight, it suggests only `pass compact`
    instead of staying quiet.
  - When auto-pass is on and the fill is at or above the threshold (default 60%, set in
    `~/.config/dotclaude/pass.toml`, per repo in the lanes `config.toml`), it blocks the Stop once
    per threshold crossing with: "Context at N%. If this is a clean boundary, run the pass skill;
    if you just asked Hayden something or work is mid-step, finish that first."
  - Stop `decision: block` keeps the turn going ([[cc-stop-hook-facts]]). The hook stays quiet
    while `background_tasks` is non-empty.
  - Turning it on: `/pass auto` (this session, a flag file keyed by session id), or
    `autopass = true` in config (every session in that repo or lane).
  - When it's off, the hook does nothing. The statusline already shows context.
- Spike first:
  - SessionEnd reason and the hooks on a respawn.
  - Whether tmux-restore treats it as a death.
  - Whether a Star follows the pane across it, as it does across `/clear`
    ([[dotclaude-tmux-shelf]]).
- **Verify:**
  - Unit tests:
    - `context-watch` on transcript fixtures: below the threshold; at it, once per crossing;
      off; background tasks in flight.
    - The resume-mode choice: approved, unapproved, a malformed marker.
    - The trigger classifier, plus the full `history.jsonl` replay.
  - A live run in a scratch tmux window: `/pass`, then the handoff commit; the pane comes back in
    plan mode with the prompt. `ring.log` and the restore log stay sane, and a Star survives.
  - A second run with an approved Next resumes in normal mode.
  - `pass compact` with a background `python3 -I -c 'import time; time.sleep(120)'` in flight:
    the handoff commits, `/compact` is typed only after idle, the background task survives, and
    the resumed turn enters plan mode.
  - An auto-pass at a lowered threshold (5%) fires once and ends in a passing `handoff-check`.

## After: the work repo's migration (its own PR in that repo, after PR 1 and PR 2 merge)

- `lane init` with the <repo>-lanes root, `install:ci`, ports 5191+, the typing gate as a lock.
- `lane adopt` each live worktree.
- Move each lane's paragraph out of STATUS.md into its record.
- Shrink STATUS.md to direction and backlog.
- Point the `lane worktree recipe` memory and `briefs/guardrails.md` at the skill (one
  home per fact).
- Root new lane sessions in the lane (`lane open`), which S1 shows is all the sandbox needs.

## Critical files

New: `skills/lanes/{SKILL.md,scripts/lane}`, `hooks/lane-identity.sh`,
`hooks/{lane-guard.sh,lane_guard.py}`, `templates/LANE.md`, `docs/lanes.md`, `tests/lanes/`,
`skills/pass/{SKILL.md,scripts/pass-respawn}`.
Edited: `settings.json`, `CLAUDE.md`, `skills/handoff/SKILL.md`, `templates/STATUS.md`,
`README.md`, `codex/AGENTS.md`, `setup.sh` (only if the bin loop needs the new paths).
Patterns to reuse:
- `hq/bin/hq-open`: the tmux launch and the excludedCommands rationale.
- `hooks/overwrite_guard.py`: guard structure and logging.
- `hooks/session-title.sh:82-128`: resolving a worktree's repo from `.git` files.
- `hooks/session-registry.sh`: the session JSON.
- `setup.sh:107-112`: installing to bin.

Process: each PR runs as a full-track effort with a `writer` in a worktree and a fresh
`reviewer` per fix round. It opens as a draft and is marked ready after docs, STATUS, install
and the smoke test from the branch. Push and merge only on Hayden's approval.
