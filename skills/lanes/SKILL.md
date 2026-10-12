---
name: lanes
description: How to work when several Claude sessions share one repo, each in its own git worktree (a "lane"), using the `lane` CLI. Use when starting, adopting or closing a worktree for parallel work, when a SessionStart line names your lane, when deciding who owns a request, when writing status in a repo with lanes, or when the user mentions lanes, worktrees, parallel sessions or "who has #N". Covers the five invariants, the lane lifecycle, a command cheat sheet and what to write where.
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
   CLI and its hooks write `<common-dir>/lanes/`. The guard denies the Edit tool both of those
   when they aren't yours.
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
   the brief, hands out a port, runs the setup command and prints `cd <path> && claude`. Start
   the lane's session there, so its cwd is the lane.
3. **Work.** Commit on the lane branch. Keep the record current (`lane note "<line>"` adds a
   timestamped State line). Put evidence under `.lane/artifacts/` and cite it in Decisions.
4. **Hand off** with the handoff skill. Its lane mode updates the record, not STATUS.md, and
   finishes with `handoff-check`, which must pass.
5. **Merge** through the lane's own PR, on Hayden's approval. Then write the outcome into the
   record, add one line to the project backlog (lane id, PR number), and propose
   `lane done chart-fix`. Run it only on Hayden's nod.
6. **Close:** `lane done <id>` refuses an unmerged branch (pass `--abandon` to close one anyway)
   and a lane with a live process in it. It archives `lane.json` and `.lane/` to
   `<common-dir>/lanes/_closed/<id>-<date>/`, runs `git worktree remove` (never `--force`) and
   `git branch -d` (never `-D`).

Existing worktrees join with `lane adopt <path>`. A dir name that is no slug (it starts with
`_` or `.`, is `main`, or runs past 64 chars) takes `--id <slug>`, the one case where the id
differs from the dir name; `git worktree move` is the other fix. If `lane new` fails partway, the
lane stays registered as `setup-failed`, and `lane adopt <path>` finishes it, redoing only the
failed step (copies never overwrite a file the lane already has).

## Cheat sheet

| Command | What it does |
|---|---|
| `lane whoami` | your lane id, `main`, `unregistered` or `plain` (`--json` for scripts) |
| `lane ls` | the board: branch, ahead/behind, PR, port, claims, live sessions, flags |
| `lane ls --requests` | request to lane, from claims only |
| `lane who 42` | the lane that claims #42, or "unclaimed" |
| `lane claim 42` / `lane release 42` | claim or drop a request for your lane |
| `lane note "<text>"` | append a timestamped line to your record's State |
| `lane asks` | every lane's open "Asks for Hayden", one list |
| `lane new` / `adopt` / `done` | lifecycle, above |

Board flags: `stale` (worktree gone; its claims are void), `rebase` (behind the base),
`conflict` (two live lanes claim one request), `orphan` (no live session), `handoff?` (the last
commit or session end is newer than the record), `setup-failed` (half made: it still holds its
port, claims and a cap slot; finish it with `lane adopt <path>`).

Run `lane` as a bare command: `lane *` is in `excludedCommands`, so it runs outside the sandbox
with the network and gh's credential. Piped or sandboxed, the local subcommands still work, and
`new`, `ls` and `done` say what they skipped (PR state shows `?`).

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
