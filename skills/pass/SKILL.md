---
name: pass
description: Hand this Claude Code session off and restart it fresh in its tmux pane (or compact it in place), resuming from the status doc. Use on `/pass`, or when "pass" is the bare last item of a terse list ("pass", "handoff and pass", "commit, pass", "commit, handoff and pass"); "pass compact", "handoff and compact" and "handoff and pass compact" pick the compact mode. Never on "pass" as a noun or with a subject ("a later pass", "an image pass", "the tests pass"). A bare "handoff" runs the handoff skill and never passes.
---

# Pass

## Overview

A pass ends this session's context and starts the next one from disk. It always runs a handoff first, gates on `handoff-check`, and then `pass-respawn` acts once the turn ends: it respawns the pane with a fresh `claude`, or types `/compact` and the resume prompt. The design and its spikes are in PLAN.md, "PR 3: `/pass`"; the script's docstring has the mechanics.

The record holds the exact facts and the fresh session re-reads it. So the handoff has to be complete and current before the pass, because the respawn throws away the only context that could fix it.

## The procedure

1. **Pick the mode.** Hayden can name one ("pass compact"); otherwise recommend one from this table and say which.

   | Mode | Use when |
   |---|---|
   | plain (the default): a fresh `claude` in the same pane | a task boundary (merged, a new request), poisoned context (corrected twice on the same thing), a lane at a boundary, an approved plan ready to run fresh |
   | compact: `/compact <focus>` in place, then the resume prompt | the same task mid-flight with tacit state (ruled-out hypotheses, half-built understanding), background tasks in flight, waiting on a build |

2. **Plain mode with background tasks in flight: don't start.** A respawn kills them silently, and an in-process teammate with them. Offer compact instead, or wait for them. `pass-respawn` also drops a plain pass when the session's stop record lists background work or a teammate, so this is a courtesy, not the only guard.

3. **Run the handoff skill.**
   - If a handoff already ran this session, run its delta mode (the `handoff` skill, "Delta mode").
   - Skip it only when the handoff was the step right before this one and `handoff-check` passes now.
   - Otherwise run the full procedure.

4. **Run `~/.claude/skills/handoff/scripts/handoff-check`** and fix each gap it lists until it passes. Never pass on a failing check.

5. **Run `pass-respawn -C <toplevel>`** as the turn's **last** action, with `--compact` for the compact mode.
   - `<toplevel>` is the literal path from `git rev-parse --show-toplevel`.
   - Run it as a bare command (no `cd`, pipe, `&&` or `;`), so the `excludedCommands` match takes it out of the sandbox. It needs the tmux socket and the session's processes.
   - Always pass `-C`. The argument-less form is unprobed against the `excludedCommands` match.
   - It refuses with no `$TMUX_PANE` (and prints the line to run by hand), on a failing `handoff-check`, and when it can't find this session's `claude` and its session file. Fix the cause and run it again; never work around a refusal.
   - Not on PATH means `./setup.sh` hasn't run since it was added.

6. **Say in one line what happens when the turn ends, then stop.** For example: "When this turn ends, the pane restarts fresh in plan mode and reads STATUS.md." Do nothing after the call. Any edit or commit after it makes the handoff stale, and the waiter drops the pass.

## What happens after the turn

The waiter watches this session's own status in `~/.claude/sessions/<pid>.json` (not the tab's) until it reads idle, waits 1 s, and checks again. It drops the pass if Hayden typed a prompt after the call. Then it re-runs `handoff-check`, reads the resume mode, and in plain mode checks the session's stop record for background work. Right before acting it checks once more that the session is still idle and the pane still runs the same `claude`. Each drop shows one line in the pane's status line and changes nothing else:

| Drop | Cause | What to do |
|---|---|---|
| `stale` | work landed after the handoff (an edit, a commit) | run the delta handoff, then `/pass` again |
| `resumed` | Hayden typed a prompt after the call, or the turn restarted | finish that turn, then `/pass` again if it still applies |
| `busy` | the stop listed background work or a teammate (or wrote no record) | wait for it, or `/pass compact` |
| `gone` | the session, its process or the pane went away or changed (a `/clear`, an exit) | `/pass` again from the live session |
| `timeout` | the turn never ended (600 s) | `/pass` again |

Each decision appends one line to `$XDG_STATE_HOME/dotclaude/pass.log` (`~/.local/state/dotclaude/pass.log` by default).

## Resume mode

The fresh session starts in **plan mode** unless the status doc's Next block carries `(approved by Hayden YYYY-MM-DD)` on its **first** item, dated within this session. Then it starts in the user's default mode and continues. A marker on a later item is ignored. In compact mode the resume prompt asks for `EnterPlanMode` instead. The handoff skill writes the marker only for an approval Hayden gave in this session (its step 6), so each new step stops at a human checkpoint.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Passing on a failing `handoff-check` | Fix the gaps first; the respawn throws away the context that could fix them |
| Doing anything after `pass-respawn` | Make it the turn's last action; later work makes the handoff stale and the pass drops |
| A plain pass with background tasks running | Use compact, or wait; a respawn kills them |
| Skipping the delta handoff because a handoff ran earlier | Work after a handoff makes it stale; run the delta mode |
| Writing the approval marker to get a normal-mode resume | Only for an approval Hayden gave this session, cited; never inferred |
| Calling `pass-respawn` without `-C`, or behind `cd` or a pipe | Run `pass-respawn -C <toplevel>` bare |
