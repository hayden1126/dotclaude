---
name: lanes
description: How to work when several Claude sessions share one repo, each in its own git worktree (a "lane"), using the `lane` CLI. Use when starting, adopting or closing a worktree for parallel work, when a SessionStart line names your lane, when deciding who owns a request, when writing status in a repo with lanes, when acting as the lead (triaging requests into lanes and opening them with `lane open`), when running a shared gate that can't run twice at once (`lane lock`), or when the user mentions lanes, worktrees, parallel sessions or "who has #N". Covers the five invariants, the lane lifecycle, the lead's playbook, a command cheat sheet and what to write where.
---

# Lanes

A lane is one git worktree on its own branch, beside the main checkout, with one series of
sessions working in it. Lanes make two things safe: knowing who you are, and knowing who owns
what. `docs/lanes.md` holds the design and why; this is the operating guide.

## The five invariants

1. **Absolute identity.** A lane's id is its worktree directory's basename. Your session belongs
   to the lane its cwd is in, or to `main`. Name lanes by id, requests by number and sessions by
   id. Never write "another session", "this session", "the other lane" or "my lane": every other
   reader resolves those to someone else. The guard denies them in status files.
2. **One writer per record.** Only a lane's own sessions write `<lane>/.lane/`. Only the `lane`
   CLI and its hooks write `<common-dir>/lanes/`. The guard denies the Edit tool any write under
   `<common-dir>/lanes/` (your own lane's data included) and any write to another lane's `.lane/`.
3. **Only the owner claims.** A request is owned only when a live lane claims it (`lane claim`).
   "Who has #42?" is answered by `lane who 42`, never by prose, agent lists, first prompts or tab
   titles. If Hayden routes #42 away from your lane, record that in your own record and
   `lane release 42`.
4. **Derive, don't store.** Branch position, PR state, liveness and staleness come from
   `lane ls`, which computes them on each call. Don't copy them into prose.
5. **STATUS.md is project direction, not lane state.** In a repo with lanes, the root STATUS.md
   holds direction and the backlog by request number. Your state and next step live in your
   record.

## At session start

The `lane-identity` hook names your lane, branch, claims, port and record. Then read, in order:

1. your record, `<lane>/.lane/STATUS.md` (Brief, Asks for Hayden, Next);
2. the project STATUS.md (direction, backlog);
3. anything else only when a pointer leads there.

After a compaction the hook says so: re-read your record before acting, because the summary
holds the feel and the record holds the facts. No identity line means you are in a plain repo or
an unregistered worktree: `lane whoami` tells you which.

## Lifecycle

1. **Init, once per repo**, from the main checkout:
   `lane init --root ~/code/<repo>-lanes --setup "npm ci" --ports 5191-5199 --cap 4`.
2. **New lane:** `lane new chart-fix --claim 42 --goal "fix the axis labels" --files src/chart/
   --overlaps api-docs --done-when "axis test green"`. It fetches, branches from `origin/main`
   with no upstream, copies the gitignored files `.worktreeinclude` lists, seeds the record with
   the brief, hands out a port and runs the setup command. Start the lane's session with
   `lane open chart-fix` (bare, from inside tmux): a new tmux window in the lane, in plan mode,
   told to read its record and plan the brief. Outside tmux, `cd <path> && claude`. Either way
   the session's cwd is the lane.
3. **Work.** Commit on the lane branch. Keep the record current (`lane note "<line>"` adds a
   timestamped State line). Put evidence under `.lane/artifacts/` and cite it in Decisions.
   Copy it in, don't link it: the mirror and the archive keep a symlink as a link, never what
   it points at, so a linked shot is gone once its target is.
4. **Hand off** with the handoff skill. Its lane mode updates the record, not STATUS.md, and
   finishes with `handoff-check`, which must pass.
5. **Merge** through the lane's own PR, on Hayden's approval. Then write the outcome into the
   record, add one line to the project backlog (lane id, PR number), and propose
   `lane done chart-fix`. Run it only on Hayden's nod.
6. **Close:** `lane done <id>` refuses an unmerged branch, a lane made by `lane new` with no
   commits past its base (pass `--abandon` to close either anyway) and a lane with a live process
   in it. It archives `lane.json` and `.lane/` to
   `<common-dir>/lanes/_closed/<id>-<date>/`, runs `git worktree remove` (never `--force`) and
   `git branch -d` (never `-D`).

Existing worktrees join with `lane adopt <path>`. A dir name that is no slug (a slug is letters,
digits, `.`, `_` and `-`, starts with a letter or digit, runs at most 64 chars and isn't `main`)
takes `--id <slug>`, the one case where the id
differs from the dir name; `git worktree move` is the other fix. If `lane new` fails partway, the
lane stays registered as `setup-failed`, and `lane adopt <path>` finishes it, redoing only the
failed step (copies never overwrite a file the lane already has).

## The lead

The lead is an optional session, usually in the main checkout, that splits a batch of requests
into lanes and keeps them moving. It owns the project STATUS (backlog, merge order) and nothing
inside a lane.

1. **Triage.** Collect the requests. Explore the code to estimate the files each one touches,
   group requests whose files overlap, and pick lane ids and branches.
2. **Propose.** Show Hayden a table and wait for approval:

   | Lane | Branch | Requests | Files | Overlaps | Merge order |
   |---|---|---|---|---|---|
   | chart-fix | fix/chart-axis | #42 | src/chart/ | api-docs | 1 |

3. **Open.** For each approved lane, `lane new <id> --branch <b> --claim <n> --goal "..."
   --files "..." --overlaps "..." --done-when "..."` writes the brief into the record. Then
   `lane open <id>` starts its session.
4. **Cap.** `config.toml` `cap` (default 4) limits live lanes. Requests beyond it wait in the
   project STATUS backlog.
5. **Hand-back gate.** A lane is handed back only when `handoff-check -C <lane path>` passes and
   `lane ls` shows no `handoff?` flag. Until then, message the lane; if its session is gone, add it
   to Hayden's asks. Never order a merge or close a lane before the gate passes.
6. **Watch and order.** Watch `lane ls`. Keep the merge order in the project STATUS. After each
   merge, message the remaining lanes: "main moved to `<sha>`: rebase; renumber the version if
   taken". The board's `rebase` flag is the truth; the message is only a nudge.
7. **Shared gates.** Wrap any run that can't happen twice at once (a browser-driven test gate, an
   e2e suite on a fixed port) in `lane lock <name> -- <cmd>`. List the names once with
   `lane init --locks gate,e2e`; an unlisted name is refused, since a typo would split the mutual
   exclusion. A second run waits and names the holder; `--wait SECS` gives up with exit 75.

The lead never respawns another lane's session or edits its record (invariant 2): only the lane
holds the context its handoff needs.

**Writers in lanes.** A lane-rooted session's `writer` subagent gets a worktree under the main
checkout's `.claude/worktrees/`, but branched from the lane's HEAD (live probe, 2026-10-11). The
stale-base trap (`worktree.baseRef`) therefore bites only a session rooted in the main checkout.

## Cheat sheet

| Command | What it does |
|---|---|
| `lane whoami` | your lane id, `main`, `unregistered` or `plain` (`--json` for scripts) |
| `lane ls` | the board: branch, ahead/behind, PR, port, claims, live sessions, tmux window, flags; then any held locks |
| `lane ls --requests` | request to lane, from claims only |
| `lane who 42` | the lane that claims #42, or "unclaimed" |
| `lane claim 42` / `lane release 42` | claim or drop a request for your lane |
| `lane note "<text>"` | append a timestamped line to your record's State |
| `lane asks` | every lane's open "Asks for Hayden", one list |
| `lane open <id>` | the lane's session in a new tmux window, in plan mode; `--focus` switches to it, or to the live session's window; `--print` shows the tmux command |
| `lane lock gate -- <cmd>` | run `<cmd>` under the named lock, waiting while another run holds it; `--wait SECS` gives up with exit 75 |
| `lane new` / `adopt` / `done` | lifecycle, above |

Board flags: `stale` (worktree gone; its claims are void), `rebase` (behind the base),
`conflict` (two live lanes claim one request), `orphan` (no live session), `handoff?` (the last
commit or session end is newer than the record), `setup-failed` (half made: it still holds its
port, claims and a cap slot; finish it with `lane adopt <path>`).

Run `lane init`, `new`, `adopt`, `ls`, `open` and `done` as bare commands: those are in
`excludedCommands`, so they run outside the sandbox with the network, gh's credential and a view
of other processes. Piped or sandboxed, `new`, `ls` and `done` say what they skipped (PR state
shows `?`), and `open` refuses. Every other subcommand runs sandboxed. `lane lock` must: the
command it wraps inherits its sandbox.

## What to write where

| Fact | Home |
|---|---|
| Who owns a request | `lane claim` (never prose) |
| The lane's goal, files, overlaps, done criteria | the record's Brief, written once at creation |
| Where the lane stands, the next step | the record's State and Next, overwritten at each handoff |
| A ruling, with who and the evidence | the record's Decisions: `Hayden picked X (2026-10-11); evidence: .lane/artifacts/x.png, session <id>` |
| What the lane needs from Hayden | the record's Asks for Hayden |
| Something that belongs to another lane | your record's Not mine (never that lane's record) |
| The lane's working design | `.lane/PLAN.md` |
| Direction, backlog, merge order | the project STATUS.md, from `main` or the lead |
| A heads-up to a peer lane | SendMessage, as a nudge only; anything that matters goes in a record first |

## Common mistakes

| Mistake | Fix |
|---|---|
| "Another session is building #42" | `lane who 42`, then write "lane chart-fix claims #42" |
| Editing another lane's record to tell it something | Write it in your own Not mine, or message that lane |
| Updating the root STATUS.md with lane progress | Your record holds it; STATUS gets one line at merge |
| Deciding ownership from an agent list or a tab title | Only `lane who` answers it |
| Running `git worktree remove` by hand | `lane done` archives the record first; the Stop-hook mirror is only the backstop |
| Claiming for a lane you're not in | Only a lane claims, for itself; the lead names claims at `lane new` |
| Running a shared gate bare while another lane may run it | `lane lock <name> -- <cmd>`, so the second run waits |
| Opening a lane by `cd`-ing the lead's session into it | `lane open <id>`: a lane needs its own session, rooted in its worktree |
