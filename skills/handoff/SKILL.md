---
name: handoff
description: Hayden's session-handoff procedure, so a fresh session resumes from a complete picture. Use when wrapping up or handing off a working session (triggers like "hand off", "wrap up", "let's stop here", end of a work block), and proactively at a clean boundary (feature done with tests green, root cause found, implement-to-review transition) or when the session is getting long and context is filling. Do not fire on every turn.
---

# Session handoff

## Overview

Make a complete handoff happen so the next session resumes from current, not stale, state. Durable state lives on disk and is re-read; conversation memory does not survive compaction or `/clear`, so anything that must outlive this session goes into a file now. This skill orchestrates and delegates: it reuses STATUS.md, claude-md-management, the memory system, and `/commit` rather than reimplementing them. It is advisory: invoking it is the model's job, and it does the work in one pass. A handoff is **point-in-time**: make it the session's last substantive act. If you keep changing state afterward (merge, close a PR, more commits), re-run steps 1-2: the doc it wrote is now stale.

## When to use

- Explicit wrap-up or handoff ("hand off", "wrap up", "let's stop here", ending a work block).
- A clean boundary: a feature is done with tests green, a root cause is found before the fix, or work moves from implement to review.
- The session is getting long or context is filling. Hand off at a boundary, well before auto-compaction, not at the last moment.

**Don't use when:** a trivial throwaway session with nothing durable to carry, or a single fast-lane change already committed with a clean tree. There is nothing to hand off.

## The procedure

Ordered. Doc-drift reconciliation is an early gate: the durable docs must match the code before the handoff is written and committed. Each step delegates to existing capability; do not reimplement.

1. **Survey the change set.** Run `git log`, `git diff`, and `git status` for what this session changed (record the commit range `<base>..<head>`). This is the shared input for drift detection and for STATUS.

2. **Reconcile the docs (the gate).** Dispatch a read-only sub-agent (`Explore`) to compare the change set against the durable non-CLAUDE docs (SPEC.md, README.md, design/architecture docs, anything describing behavior you changed) and return the stale claims. Fix where the correction is unambiguous; flag what needs a human decision. Never silently rewrite. For CLAUDE.md specifically, delegate to claude-md-management (`/revise-claude-md` to propose additions with approval, `claude-md-improver` to audit), do not hand-edit it here. Also run a **self-consistency** pass: a volatile fact usually appears in more than one place (a PR number/status, a branch name, a unit count, the commit range, a file or function name), so grep each across the docs and confirm every mention agrees; patching one mention and missing its duplicate elsewhere is a common silent contradiction. The handoff is not complete until the durable docs match the code and themselves. Prefer function-name anchors over raw line numbers in any code citation, since line numbers drift on the next edit.

3. **Update STATUS.md** against the now-corrected docs (seed from `~/.claude/templates/STATUS.md` if absent). Fill Done (with commit shas and the commit range), In flight (what is half-done plus the next concrete step), Blocked / decisions needed, and Notes for next session. Keep it forward-looking and bounded: decisions, next steps, gotchas, the commit range. Git holds the history; this doc holds the direction. An over-stuffed handoff doc degrades the next session as much as a bloated CLAUDE.md.

4. **Curate memory** (high threshold, prune-biased). Review the session for genuinely reusable, durable facts (Hayden's preferences, decisions, project state). Route routine session state to STATUS, not memory. For each candidate: dedupe against `MEMORY.md` and update the existing entry rather than duplicate; add new entries in the live format under `~/.claude/projects/<cwd-slug>/memory/` (one fact per file with frontmatter, plus a one-line pointer in `MEMORY.md` under the right heading, matching the existing style; cross-link related entries with `[[name]]`). Supersede stale entries with a dated note; propose and confirm before deleting any existing entry (boundaries). Fewer, higher-signal entries beat volume: over-recall biases future sessions.

5. **Commit cleanly and verify.** Stage the doc fixes, STATUS, and memory files together and commit via `/commit` (branch-first on the default branch, never push without approval; danger-guard already blocks destructive git). Confirm everything intended is committed; note any deliberately uncommitted work in STATUS. Run the verification target (tests, build, lint) and record green, or note red and why.

6. **Leave next-session pointers.** Ensure STATUS "In flight" and "Notes for next session" name the exact next concrete step and what to verify, and include the commit range so the next session can `git log` the work. Close with a short summary to Hayden: drift found and fixed or flagged, STATUS updated, memory changes, git and verification state.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Dumping a transcript into STATUS | Forward-looking only: decisions, next step, gotchas, commit range. Git holds the history |
| Writing STATUS before fixing drift | Reconcile docs first so STATUS describes the corrected world |
| Appending to memory without pruning | Pair every add with a dedupe and prune pass; high threshold; propose deletions |
| Hand-editing CLAUDE.md here | Delegate to claude-md-management (`/revise-claude-md`, `claude-md-improver`) |
| Forgetting the commit range | Record `<base>..<head>` so the next session can recover work from git |
| Firing at 90% full | Hand off at a clean boundary; re-asked questions or re-suggested dead approaches mean you waited too long |
| Committing or pushing on the default branch silently | Branch-first on default; never push without approval |
| Working on past a handoff, then leaving the doc it wrote stale | A handoff is point-in-time. Make it the last act; if you merge/close/commit/run more after it, re-run the reconcile (steps 1-2) |
| Fixing a fact in one place but not its duplicates (PR status, branch name, counts stated twice) | Self-consistency pass: grep each volatile fact across all docs; every mention must agree |
| Citing raw `file.py ~line` numbers in durable docs | Anchor to function/section names instead; line numbers drift on the next edit |

## Why doc-drift is the gate

Doc drift is the failure this skill exists to prevent: durable docs left describing the old behavior after the code moved, caught only when a human happened to ask. Putting reconciliation before STATUS and the commit makes the handoff self-correcting: the next session inherits docs that match the code, not a confident summary written on top of stale ones.
