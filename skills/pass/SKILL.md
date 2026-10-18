---
name: pass
description: Hand this Claude Code session off and restart it fresh in its tmux pane (or compact it in place), resuming from the status doc. Use on `/pass`, or when "pass" is the bare last item of a terse list with an action before it ("handoff and pass", "commit, pass", "commit, handoff and pass"); a one-word "pass" alone is a "no thanks", not a pass. "pass compact", "handoff and compact" and "handoff and pass compact" pick the compact mode. Never on "pass" as a noun or with a subject ("a later pass", "an image pass", "the tests pass"). A bare "handoff" runs the handoff skill and never passes.
---

# Pass

## Overview

A pass ends this session's context and starts the next one from disk. It always runs a handoff first, gates on `handoff-check`, and then `pass-respawn` acts once the turn ends: it respawns the pane with a fresh `claude` (with the `--model` and `--effort` the session launched with, or what it ran after a later `/model` or `/effort`), or types `/compact` and the resume prompt. The design and its spikes are in PLAN.md, "PR 3: `/pass`"; the script's docstring has the mechanics.

It runs on `/pass`, or on a terse list whose last item is "pass" with an action before it: "handoff and pass", "commit, pass", "commit, handoff and pass". "pass compact", "handoff and compact" and "handoff and pass compact" pick the compact mode. A one-word "pass" ("Pass.") is not a trigger: it is also how Hayden declines an offer ("want me to also do X?"). Neither is "pass" as a noun or with a subject ("a later pass", "the tests pass").

The record holds the exact facts and the fresh session re-reads it. So the handoff has to be complete and current before the pass, because the respawn throws away the only context that could fix it.

## The procedure

1. **Pick the mode.** Hayden can name one ("pass compact"); otherwise recommend one from this table and say which.

   | Mode | Use when |
   |---|---|
   | plain (the default): a fresh `claude` in the same pane | a task boundary (merged, a new request), poisoned context (corrected twice on the same thing), a lane at a boundary, an approved plan ready to run fresh |
   | compact: `/compact <focus>` in place, then the resume prompt | the same task mid-flight with tacit state (ruled-out hypotheses, half-built understanding), background tasks in flight, waiting on a build |

2. **Stop the leftovers first, in either mode.** A respawn kills every background task silently, an in-process teammate too, and a compact leaves a leftover running through every later nudge. So before the handoff, list the session's tasks.
   - Run `pass-respawn -C <toplevel> --tasks`, bare like step 5. It prints each task from the last Stop with its description and id, and whether it blocks a plain pass. Add any you started this turn: a Monitor, background Bash, the agents and teammates you know of.
   - Never use `ps` for this. Tasks aren't child processes you can see, but the MCP servers are, and they look like the whole list.
   - A task whose job is done is a leftover (a watch whose answer came, a server nothing uses now): stop it with `TaskStop <id>`, a Monitor too.
   - A task you can't tie to finished work: ask Hayden before you stop it, and don't pass this turn.
   - In plain mode, if any is still in use, use compact mode instead, and say so in your reply. In compact mode, leave it running.
   - If a task you stopped still shows as running (a finished in-process teammate lingers in the list), use compact mode. Don't keep retrying `TaskStop`.
   - An `artifact watch` doesn't block a plain pass. The Artifact tool arms one on each publish, and you never see its id (`/tasks` shows it to Hayden under System tasks); the respawn ends it, and `pass.log` names its page. If Hayden is still commenting on that page, put its URL in the record's Next so the fresh session watches it again.
   - You judge, the script enforces: `pass-respawn` still refuses a plain pass while any task but memory upkeep (`dream`) or an artifact watch runs, so a skipped check can't kill a live watcher. Its refusal is loud (a notice held until a key, plus the Windows toast) and names the first two tasks with their ids; `pass.log` names every one.

3. **Run the handoff skill.**
   - Load it with the Skill tool (`handoff`) unless this session already did, so its current procedure runs, not a remembered one. `handoff-check` gates what it can test, not how well the record reads.
   - If a handoff already ran this session, run its delta mode (the `handoff` skill, "Delta mode").
   - Skip it only when the handoff was the step right before this one and `handoff-check` passes now.
   - Otherwise run the full procedure.

4. **Run `~/.claude/skills/handoff/scripts/handoff-check`** and fix each gap it lists until it passes. Never pass on a failing check.

5. **Run `pass-respawn -C <toplevel>`** as the turn's **last** action, or `pass-respawn -C <toplevel> --compact` for the compact mode. Keep `-C` first: the allow rule `Bash(pass-respawn -C *)` matches that form, so the auto-mode classifier never sees it (it once refused a bare call as "Create Unsafe Agents").
   - `<toplevel>` is the literal path from `git rev-parse --show-toplevel`.
   - Run it as a bare command (no `cd`, pipe, `&&` or `;`), so the `excludedCommands` match takes it out of the sandbox. It needs the tmux socket and the session's processes.
   - Always pass `-C`. The argument-less form is unprobed against the `excludedCommands` match.
   - It refuses with no `$TMUX_PANE` (and prints the line to run by hand), in a background session (next item), on a failing `handoff-check`, when it can't find this session's `claude` and its session file, when it or a binary it runs sits where the sandbox can write, and when a pass is already pending for this session. Fix the cause and run it again; never work around a refusal.
   - In a background session (daemon-hosted: `claude --bg`, agent view), it refuses with exit 2: the daemon runs it, not a pane, so there is no pane to respawn. It prints the line to run by hand, and how to move the session into a pane of its own: once the turn ends, from another terminal, `claude stop <jobId>`, then `claude --resume <sessionId>` in a tmux pane in the session's directory (it prints the `cd` when the path is plain), and `/pass` there. `claude attach` doesn't count: it only shows the session, which stays daemon-hosted. Nothing in the session fixes this: give Hayden both ways and end the turn.
   - Not on PATH means `./setup.sh` hasn't run since it was added.

6. **Say in one line what happens when the turn ends, then stop.** Never promise a restart: the waiter's checks run after your reply, and any of them can drop the pass. Say: "The pane restarts after this turn unless the gate refuses (you'd see a notice that stays until a key)." In compact mode: "The pane compacts after this turn unless the gate refuses (you'd see a notice that stays until a key)." Do nothing after the call. Any edit or commit after it makes the handoff stale, and the waiter drops the pass.

7. **If Hayden says not to pass after the call**, run `pass-respawn -C <toplevel> --cancel`. It ends this session's pending waiter (logged `cancelled`), and says so when nothing was pending. A prompt he types mid-turn drops the pass anyway; `--cancel` makes it certain. Once the waiter has passed its last check and begun acting, it is too late: the waiter ignores the signal and finishes (the respawn, or the keys), and `--cancel` says `too-late` and exits 1. It says `too-late` too, naming the outcome, when the waiter dropped (`stale`, say) or acted on its own while still holding its lock. Once the waiter is gone, `--cancel` says nothing is pending; read `pass.log` for what it did.

## What happens after the turn

The waiter watches this session's own turn (not the tab's) until it has ended, waits 1 s, and checks again.

- `~/.claude/sessions/<pid>.json` shows the end by reading idle.
- But Claude Code keeps that file `busy` at the prompt while a background agent, teammate or workflow runs. Then the transcript decides: the turn's `turn_duration` entry or an Esc interrupt after the call, with no new turn since.
- A new turn (a typed prompt, a task notice, an agent's hand-back) after the end drops the pass as `resumed`.

Then, in order:

1. It re-runs `handoff-check`.
2. It drops the pass if Hayden typed a prompt after the call, or queued one mid-turn, or the transcript can't be read.
3. It reads the resume mode.
4. In plain mode, it checks the session's stop record for background work: any task but memory upkeep (`dream`) or an artifact watch drops it.
5. Right before acting, it checks once more: the turn is still over (by the same rule), the pane still runs the same `claude`, the pane is not in copy mode, and the input box is empty. A draft Hayden is composing drops the pass in both modes, since typing would join it and a respawn would discard it. The dim ghost suggestion doesn't count.
6. In compact mode it checks the pane again between `/compact` and the resume prompt. If copy mode, a draft or no input box came up in that second, it doesn't type the prompt: it shows it in the status line for Hayden to type, where it stays until a key press, and writes it whole into `pass.log` (logged `partial`).

After a plain respawn, the fresh session shows the last turn once as a banner (Hayden sees it, the model doesn't): its time, the first line of Hayden's prompt, and the replies rendered from markdown. Ctrl-b Up reopens the last 5 turns in a popup, each with its prompt. `pass-respawn` saves the prompts from the transcript beside the replies; a turn a background notice started says it had no prompt, and one whose start is past what it reads says the prompt wasn't saved.

A refusal (`stale`, `busy`, `timeout`, `failed`, `error`, and the resume prompt a partial compact leaves) is loud: one line naming the cause, the tab and the fix, on the status line of every terminal attached to the pane's tmux session, held until a key press, plus the Windows toast. A `resumed`, `gone` or `cancelled` drop (a prompt or a new turn after the call, a status change after the turn, a `/clear` or exit, a cancel) shows a brief line in the status line; a `resumed` for an unreadable transcript is loud, since every pass drops the same way until it can be read. A drop changes nothing else:

| Drop | Cause | What to do |
|---|---|---|
| `stale` | work landed after the handoff (an edit, a commit) | run the delta handoff, then `/pass` again |
| `resumed` | Hayden typed a prompt after the call, or a new turn started (a queued prompt, a task notice, an agent's hand-back) | finish that turn, then `/pass` again if it still applies; for an unreadable transcript (a loud line), tell Hayden instead, since every pass drops the same way until it can be read |
| `busy` | the stop listed background tasks (the notice names the first two with their ids, `pass.log` every one, as `tasks:`, `waits:` for real waits, or both) or wrote no record; or, at the last check, the pane was in copy mode, had a draft in the input box, or showed no input box, or tmux didn't answer | stop the leftovers (step 2: `--tasks`, then `TaskStop <id>`) or wait, then `/pass`; `/pass compact` keeps the tasks; leave copy mode or send or clear the draft, then `/pass` again |
| `gone` | the session, its process or the pane went away or changed (a `/clear`, an exit) | `/pass` again from the live session |
| `timeout` | the turn never ended (600 s) | `/pass` again |
| `cancelled` | `pass-respawn -C <toplevel> --cancel` ended the waiter | nothing; `/pass` again when wanted |
| `failed` | tmux could not respawn the pane or type into it | read `pass.log`, then `/pass` again; if it failed after `/compact` was sent, don't pass again (that compacts twice): the status line hands over the resume prompt (`pass.log` has it whole); type it, or press Enter if it already sits in the input box, as the line says |
| `error` | an error in the waiter itself | read `pass.log`, then `/pass` again |
| `partial` | compact mode: `/compact` was sent (not confirmed), then copy mode, a draft or no input box came up before the resume prompt | type the prompt the status line shows (it stays until a key press, and `pass.log` has it whole) |

Each decision appends one line to `$XDG_STATE_HOME/dotclaude/pass.log` (`~/.local/state/dotclaude/pass.log` by default).

**A drop tells you too.** Every drop, and a compact whose resume prompt wasn't typed, also leaves this session a notice. It arrives as context at your next turn or tool call, starting `[pass]`. It says no pass is pending. A loud drop also names the cause and the fix; a quiet one says less (a `gone` names what changed, a `cancelled` only that it was cancelled). After a half-done compact it carries the resume prompt to follow.

- The waiter decides within about a second of the turn's end, so by your next turn a pass has either run or dropped. A turn that starts inside that second gets the notice at its first tool call or your next turn, not at its prompt.
- Never tell anyone a pass is still queued from memory: a `[pass]` notice means none is.
- Pass again only when the reason still holds. Hayden asked for it, or an autopass tier is in effect: fix the notice's cause first.

## Auto-pass nudges

With autopass on (`/autopass on` in the tab, a lane or a lanes repo's main checkout by default, or `autopass = true` in `~/.config/dotclaude/pass.toml`, under `$XDG_CONFIG_HOME` when that is set), `hooks/context-watch.sh` tells you when to pass. Its text starts with `[autopass]`, arrives as a Stop block reason or as context added to a tool result, and names the context size and where auto-compact fires (about 567k).

- **Soft (300k), at a Stop:** done end to end, run this skill now. A small remainder left, finish it first. Your last reply asked Hayden something, end the turn and do nothing else.
- **Wrap-up (480k):** finish the step you are on and don't start another. If more than that step is left, run this skill now, in compact mode if you are mid-task.
- **Hard (520k, again every 20k until you start the pass):** run this skill now: compact mode mid-task, plain at a task boundary.
- When it says compact mode because background tasks are running (or may be: a tool call can't see the task list), run step 2's check: stop the leftovers, then pass plain if none remain; use compact if any is still in use (or a stopped one still shows). The nudge names each task with its id. Compacting over leftovers would leave them running through every later nudge.
- The tiers follow the window: on a smaller one they come earlier, and the text always names the size and where auto-compact fires.

An auto-pass is a normal pass: the same handoff, `handoff-check` and `pass-respawn`, and the fresh session starts in plan mode unless the first Next item is approved. Never pass on a nudge while Hayden is waiting on an answer from you. With autopass off you get no nudge: Hayden alone sees one line at the hard tier and decides. `/autopass` is Hayden's: the autopass mod answers it without a model turn, and you never run it.

## Resume mode

The fresh session starts in **plan mode** unless the status doc's Next block carries `(approved by Hayden YYYY-MM-DD)` on its **first** item, dated within this session (not before its start, not after today). With the session's start unknown it stays in plan mode. A same-day marker from an earlier session can't be told apart by its date, so it counts. Then it starts in the user's default mode and continues. A marker on a later item is ignored. In compact mode the resume prompt asks for `EnterPlanMode` instead. The handoff skill writes the marker only for an approval Hayden gave in this session (its step 6), so each new step stops at a human checkpoint.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Passing on a failing `handoff-check` | Fix the gaps first; the respawn throws away the context that could fix them |
| Doing anything after `pass-respawn` | Make it the turn's last action; later work makes the handoff stale and the pass drops |
| A plain pass with background tasks running | Stop the leftovers (`TaskStop <id>`); if any is still in use, use compact; a respawn kills them |
| Checking `ps` for leftover tasks | Read `pass-respawn -C <toplevel> --tasks`: tasks aren't child processes, and the MCP servers that are look like the whole list |
| Promising "the pane restarts" | Say it restarts unless the gate refuses; the checks run after your reply |
| Saying a pass is "still queued" in a later turn | By your next turn it has run or dropped; a `[pass]` notice names the drop and its fix |
| Running the handoff from memory | Load the `handoff` skill with the Skill tool first; the procedure changes |
| Skipping the delta handoff because a handoff ran earlier | Work after a handoff makes it stale; run the delta mode |
| Writing the approval marker to get a normal-mode resume | Only for an approval Hayden gave this session, cited; never inferred |
| Calling `pass-respawn` without `-C`, or behind `cd` or a pipe | Run `pass-respawn -C <toplevel>` bare |
| Passing a background session after `claude attach` | Attach only shows it, and the daemon still runs it: give Hayden step 5's two ways (the by-hand line, or, once the turn ends, stop it from another terminal and resume it in a pane) and end the turn |
