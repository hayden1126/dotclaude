---
name: handoff
description: Hayden's session-handoff procedure, so a fresh session resumes from a complete picture. Use when wrapping up or handing off a working session (triggers like "hand off", "wrap up", "let's stop here", end of a work block), and proactively at a clean boundary (feature done with tests green, root cause found, implement-to-review transition) or when the session is getting long and context is filling. Do not fire on every turn.
---

# Session handoff

## Overview

Make a complete handoff happen so the next session resumes from current, not stale, state. Durable state lives on disk and is re-read; conversation memory does not survive compaction or `/clear`, so anything that must outlive this session goes into a file now. This skill orchestrates and delegates: it reuses the living status doc (STATUS.md), claude-md-management, the memory system, and `/commit` rather than reimplementing them. It is advisory: invoking it is the model's job, and it does the work in one pass. A handoff is **point-in-time**: make it the session's last substantive act. If you keep working afterward, the doc it wrote is stale: run the delta mode below.

## When to use

- Explicit wrap-up or handoff ("hand off", "wrap up", "let's stop here", ending a work block).
- A clean boundary: a feature is done with tests green, a root cause is found before the fix, or work moves from implement to review.
- The session is getting long or context is filling. Hand off at a boundary, well before auto-compaction, not at the last moment.

**Don't use when:** a trivial throwaway session with nothing durable to carry, or a single fast-track change already committed with a clean tree. There is nothing to hand off.

## The procedure

Ordered. Doc-drift reconciliation is an early gate: the durable docs must match the code before the handoff is written and committed. Each step delegates to existing capability; do not reimplement. The last step is always `handoff-check`: the handoff is not done until it passes.

0. **Detect the context.** Run `lane whoami` (the `lanes` skill). It prints a lane id (you are in a lane), `main` (the main checkout of a repo with lanes), or `plain` (no lanes: the steps below apply as written). In a lane, the "status doc" below is your lane record, `<lane>/.lane/STATUS.md`, never the root STATUS.md. No `lane` on PATH means a plain repo.

1. **Survey the change set.** Run `git log`, `git diff`, and `git status` for what this session changed (record the commit range `<base>..<head>`). This is the shared input for drift detection and for STATUS. **In a lane**, the range is `origin/main..HEAD` on the lane's branch.

2. **Reconcile the docs (the gate).** Dispatch a read-only sub-agent (`researcher`, which can run `git diff` itself; `Explore` has no shell, so it works only if you paste the diff or the list of changed files into its brief) to compare the change set against the durable non-CLAUDE docs (SPEC.md, README.md, design/architecture docs, anything describing behavior you changed) and return the stale claims. Fix where the correction is unambiguous; flag what needs a human decision. Never silently rewrite. For CLAUDE.md specifically, delegate to claude-md-management (`/revise-claude-md` to propose additions with approval, `claude-md-improver` to audit), do not hand-edit it here; this covers **nested** CLAUDE.md files, not just the root, so reconcile every one the change set touches. Reconciliation is also the one proactive CLAUDE.md trigger: before closing this step, ask once whether the session *established or changed* a durable repo-level convention or structural fact that CLAUDE.md documents (a new top-level directory, a new canonical build/deploy command, a changed standing rule), even where no existing line contradicts it; if so, invoke `/revise-claude-md` to propose it with approval, scoped to that one fact. Stay prune-biased: a command you happened to run, a gotcha (memory), or session state (STATUS) is not a CLAUDE.md fact: the bar is a standing convention the whole repo inherits. Also run a **single-home pass**: each volatile fact gets exactly ONE authoritative home and is not restated elsewhere (git owns repo-state (push/merge/tree), OPERATIONS.md owns accounts/services, the plan file owns design, STATUS owns direction). Collapse any duplicate to a pointer at its home; a fact stored in two places is a future contradiction, not a safety net. Then grep each fact across the docs only to confirm no second copy crept back in. The handoff is not complete until the durable docs match the code and themselves. Prefer function-name anchors over raw line numbers in any code citation, since line numbers drift on the next edit.

3. **Update the living status doc** against the now-corrected docs. If the repo already has one (a STATUS.md, a RESUME-block doc, or a brief acting as the living doc), update THAT in place rather than creating a second one; only seed a fresh STATUS.md from `~/.claude/templates/STATUS.md` when none exists. Fill the template's sections: Direction (what the project is driving at), Backlog (queued requests by number), Asks (what waits on Hayden), Decisions (with who, when and a pointer to the evidence), Blocked, and Notes for next session (the next concrete step). Completed work is one line plus a pointer to the plan or commit range, not a per-file narration. **Prune as you write; do not just append:**
    - *Delete-test every line:* if git, `OPERATIONS.md`, or the plan file already holds it, drop it and point at the source. Git holds the history; this doc holds the direction.
    - *One next-session block, overwritten:* keep a single Notes/next-step block and overwrite it each handoff; never append a new dated recap beneath the last (that is how the doc doubles).
    - *Soft ceiling (~100-120 lines):* past it, restructure (collapse completed tracks to pointers) before adding. An over-stuffed handoff doc degrades the next session as much as a bloated CLAUDE.md.
    - **In a lane:** update the lane record instead: State, the Next block, Decisions with pointers (artifact paths under `.lane/artifacts/`, session ids), Not mine notes and Asks for Hayden. Do not update STATUS.md. Touch the project STATUS only for backlog or direction items no lane owns, using absolute names (lane ids, request numbers). Name every claim (`lane whoami` lists them) and never write relative identity ("another session"): name the lane id.

4. **Curate memory** (high threshold, prune-biased). Review the session for genuinely reusable, durable facts (Hayden's preferences, decisions, project state). Route routine session state to STATUS, not memory. For each candidate: dedupe against `MEMORY.md` and update the existing entry rather than duplicate; add new entries in the live format under `~/.claude/projects/<cwd-slug>/memory/` (one fact per file with frontmatter, plus a one-line pointer in `MEMORY.md` under the right heading, matching the existing style; cross-link related entries with `[[name]]`). Supersede stale entries with a dated note; propose and confirm before deleting any existing entry (boundaries). Fewer, higher-signal entries beat volume: over-recall biases future sessions.

5. **Commit cleanly and verify.** Stage the doc fixes, STATUS, and memory files together and commit via `/commit` (branch-first on the default branch, never push without approval). Confirm everything intended is committed; note any deliberately uncommitted work in STATUS. Run the verification target (tests, build, lint) and record green, or note red and why. A PR for this work (opened only with Hayden's approval) stays a draft (`gh pr create --draft`) until this step is done, and goes ready (`gh pr ready <n>`) only after it, so it merges once with its docs and STATUS; if the repo installs from its checkout, install and smoke-test from the branch first, so STATUS can say so. A fact only knowable after the merge rides in the next PR, not a STATUS-only one. **In a lane:** commit on the lane branch. The record is outside the tree (hidden by `info/exclude`), so there is nothing to stage for it; note an unpushed branch in the record, since pushes wait for Hayden.

6. **Leave next-session pointers.** Ensure the status doc's next-step block ("Notes for next session", or Next in a lane record) names the exact next concrete step and what to verify, and include the commit range so the next session can `git log` the work. In a lane, write the range into the record after the step-5 commit, so the record postdates it. Close with a short summary to Hayden: drift found and fixed or flagged, STATUS updated, memory changes, git and verification state.
    - **Approval marker:** append `(approved by Hayden YYYY-MM-DD)` to the Next block's **first** item (the step the next session starts with) only when Hayden approved that exact step in this session, and cite the approval (his words or the plan he accepted) beside it. Never infer one from a general "go ahead" or an earlier session. `/pass` reads only the first item: with a marker dated within this session the fresh session starts in the default mode and continues, otherwise in plan mode; a marker on a later item is ignored. `handoff-check` fails a marker with no valid date, and a first-item marker dated before this session started (remove it, or get a fresh approval).

7. **Run `~/.claude/skills/handoff/scripts/handoff-check`** from the checkout, by that path: the skill dir is linked live, while the `~/.local/bin` link waits for the next `setup.sh`. It checks a clean tree (or leftovers named in the status doc by their repo-relative path; agent worktrees don't count), a status doc written after HEAD's commit and during this session, a non-empty Next block, no relative identity (a warning only in a repo with no lanes) and, in a lane, that every claim is named and an unpushed branch is noted. It exits non-zero and lists each gap: fix them and re-run. Say the handoff is done only after it passes.

### Delta mode

Use it when a handoff already ran this session, or when `handoff-check` says the last one is stale. Work after a handoff makes it stale: review fixes, a rebase, a decision in chat, a failed deploy. A clean PR, merge and deploy don't, since `gh` derives them. The delta runs the same procedure over a smaller range:

1. **The range** is `<last commit touching the status file>..HEAD` (`git log -1 --format=%H -- <status file>` gives the base). A lane record is never committed, so in a lane the base is the head of the range the last handoff wrote into the record.
2. **Reconcile the docs** for that range only. Skip the drift sweep when the range touches no code or docs.
3. **Update the status doc:** overwrite the next-step block, and add the decisions and findings from chat since that handoff.
4. Curate memory, commit and leave pointers as in steps 4-6, for what is new since the last handoff.
5. **Always end with `handoff-check`.**

### After a merge ("merged, cleanup and handoff")

In a lane, once Hayden has merged the lane's PR:

1. Write the final outcome into the lane record.
2. Add one line to the project STATUS backlog naming the lane id and the PR number.
3. Propose `lane done <id>`. Cleanup still needs Hayden's nod.

Then finish the procedure as usual, `handoff-check` last.

## Volatile git state: derive, never store

Push / commit / tree / merge / PR *status* is a computed property of the repo, not durable state. It is stale the moment it is committed (a commit cannot state its own post-push status), and a merge can land on GitHub with no local signal. So STATUS records only **immutable identifiers** (a PR number, a base SHA for still-unmerged work) plus the **command to derive** current state, never the state itself:

- Push / tree / ahead-count: `git status -sb`, `git log @{u}..HEAD` (run `git fetch` first).
- Merge / PR status: ask the host's PR/MR CLI (`gh pr view <n> --json state,mergedAt` on GitHub, `glab mr view <n>` on GitLab). It is authoritative whether the merge happened locally or host-side, and it survives squash-merge (local `git log origin/main..HEAD` does not: a squash makes a new commit, so local git reports the branch unmerged forever).
- Branch position: reference the base branch (e.g. `main`) or origin's SHA, never HEAD's own SHA.

Always `git fetch` first: a stale remote-tracking ref is the other direction this drifts.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Dumping a transcript into STATUS | Forward-looking only: decisions, next step, gotchas, commit range. Git holds the history |
| Appending a new dated session recap each handoff | Keep ONE next-session block and overwrite it; appending is how STATUS doubles. Git holds the session history |
| Writing STATUS before fixing drift | Reconcile docs first so STATUS describes the corrected world |
| Appending to memory without pruning | Pair every add with a dedupe and prune pass; high threshold; propose deletions |
| Hand-editing CLAUDE.md here | Delegate to claude-md-management (`/revise-claude-md`, `claude-md-improver`) |
| A new durable repo convention (new dir, canonical command, changed standing rule) left out of CLAUDE.md because no existing line contradicted it | Reconciliation proactively proposes it via `/revise-claude-md`, scoped to that one fact. Not gotchas (memory) or session state (STATUS) |
| Forgetting the commit range | Record `<base>..<head>` so the next session can recover work from git |
| Firing at 90% full | Hand off at a clean boundary; re-asked questions or re-suggested dead approaches mean you waited too long |
| Committing or pushing on the default branch silently | Branch-first on default; never push without approval |
| Opening the PR ready before the handoff, then chasing the merge with STATUS-only PRs | Draft until step 5 is done, then `gh pr ready`; one merge carries the work, its docs and STATUS |
| Working on past a handoff, then skipping the delta handoff | A handoff is point-in-time. Make it the last act; after review fixes, a rebase or a chat decision, run the delta mode before the next handoff or `/pass` |
| An approval marker written for a step Hayden didn't approve this session | Write `(approved by Hayden YYYY-MM-DD)` only for that exact step, citing the approval. Never infer it: it lets `/pass` resume without a plan checkpoint |
| A volatile fact stored in two places (branch name, counts, PR number stated twice) | Give it ONE home and point at it; grep only to confirm no second copy returned. Two copies is a future contradiction, not a backup |
| Storing push/merge/PR state as a fact ("pushed", "merged", "nothing unpushed") | It is stale the moment it is committed and merges flip on GitHub unseen. Store the derive-command + immutable ids; see "Volatile git state" |
| Citing raw `file.py ~line` numbers in durable docs | Anchor to function/section names instead; line numbers drift on the next edit |
| Wrote "another session" (or "this session", "my lane") into a status doc | Name the lane id (`lane whoami`, `lane who #<n>`) or the session id; a relative name reads as someone else in every other lane |
| Updated STATUS.md from a lane | The lane's state goes in its record; the project STATUS gets only backlog or direction items no lane owns, plus one line at merge |
| Said the handoff was done without running `handoff-check` | Run it last; fix each gap it lists and re-run until it passes |

## Why doc-drift is the gate

Doc drift is the failure this skill exists to prevent: durable docs left describing the old behavior after the code moved, caught only when a human happened to ask. Putting reconciliation before STATUS and the commit makes the handoff self-correcting: the next session inherits docs that match the code, not a confident summary written on top of stale ones.
