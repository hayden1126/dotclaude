# STATUS: durable session-handoff skill

> Living state. Update at the end of every working block so a fresh session can resume from here after `/clear`.
> Design rationale lives in `docs/durable-handoff-brief.md` (RESOLVED) and the plan at
> `~/.claude/plans/read-docs-durable-handoff-brief-md-and-p-precious-cherny.md`. The durable decision and
> the verified hook-capability facts live in memory (`dotclaude-handoff-skill`). This doc is current state
> and next steps only, it does not restate those.

Last updated: 2026-06-26
Branch: main (origin/main in sync)

## Done
- Added an opt-in **auto mode** to `hooks/danger-guard.sh` (new `auto_enabled()` helper, enabled by `DANGER_GUARD_AUTO=1` OR the sentinel file `~/.claude/.danger-guard-auto`). When on, the guard flips to allow-by-default: every dangerous op (both the deny and ask tiers) drops to a single `ask` prompt, and all other bash commands are auto-approved (`allow`). Off by default; the two-tier deny/ask behavior is unchanged when off. Verified live in both modes (env var + sentinel toggle on and off); README hooks section updated. Shipped on `feat/danger-guard-auto-mode`, merged to `main` and pushed.
- Authored `skills/handoff/SKILL.md`: an advisory, skill-only v1 handoff procedure (survey, reconcile doc-drift as an early gate, update STATUS, curate memory, commit, leave pointers). Symlinked into `~/.claude/skills/handoff`, discoverable as `/handoff`. Commit `8bb222d` (skill plus the drift it caught when dogfooded on its own implementation).
- Peer-reviewed and sharpened after a multi-lens critique flagged mild overengineering, redundancy, and a writing-voice caps violation: de-capped emphasis, tightened the Overview, removed a redundant meta-paragraph. Commit `681ae87`. Both commits pushed.
- Memory entry `dotclaude-handoff-skill` records the v1 decision and the verified facts (no hook sees context fill; a hook cannot inject text that survives compaction; durable vector is a file on disk; a skill inherits to the loop-engineering inner puppet for free, a hook does not).
- Shipped the lightweight-trigger half of the original seed recommendation: `hooks/handoff-reminder.sh`, a `UserPromptSubmit` advisory hook that nudges to invoke `/handoff` on wrap-up / handoff / clear signals. It only adds a reminder (does not perform the handoff), is fail-open, and never blocks a prompt, so the skill-only decision still holds. PR #2 (`3454cc2`, merged `ab9ba6b`); documented in README.
- Resolved the open skill-design decision (Hayden): the handoff skill's step 3 now updates an existing living doc in place instead of creating a new STATUS.md (seeds from the template only when none exists). This STATUS.md is that living doc, so this entry is itself an in-place update.

## In flight
- None. The v1 handoff skill, the `UserPromptSubmit` reminder hook (PR #2), and the danger-guard auto mode are all shipped.

## Blocked / decisions needed
- None.

## Notes for next session
- Deferred work (kept consistent with the brief RESOLVED note and memory): (1) the *deterministic* PreCompact/Stop safety-net hook, revisit only after empirically testing the `SessionStart` `compact`-matcher re-inject path (open bug #15174). This is distinct from the `UserPromptSubmit` reminder hook already shipped in PR #2; the safety-net is the still-deferred piece. (2) the autonomous loop-engineering handoff (a Python orchestrator step that refreshes the RESUME block), which the interactive skill does not cover because the headless maker has no skills.
- Skill verified live: run this session on real changes + genuine drift (the PR #5 reconcile and this wrap-up handoff). Survey, drift-reconcile, STATUS update, memory curation, and git reporting all worked. (Closes the prior "to verify" note.)
- Evaluated and SKIPPED, do not re-raise: (a) wiring `handoff-reminder.sh` into the loop-engineering inner loop (the puppet gets one machine prompt with no human turn or wrap-up phrase, so the hook has no addressee; the skill already inherits there); (b) cross-platform notifiers (osascript / notify-send) for the toast (YAGNI on this WSL-only setup; README already documents the manual macOS/Linux swap).
- Commit ranges: the skill shipped earlier in `8bb222d..681ae87`; the reminder hook in PR #2 (`3454cc2..ab9ba6b`). The 2026-06-19 session (`1ba4c66..0039235`) merged PR #1 (notify cross-platform), #4 (notify docs + file mode), #5 (handoff-doc reconcile), #6 (Hayden-and-Friends credit + living-doc rule), #7 (drop dead sed fallback), #8 (XML-escape the toast message). The 2026-06-26 session added danger-guard auto mode on `feat/danger-guard-auto-mode` (base `6b293a0`), merged to `main` and pushed. See `git log` on `main`.
- Setup note: this machine was provisioned this session via `./setup.sh` (symlinks live in `~/.claude/`); `ccstatusline` was skipped because `bun` is not on PATH (blank status line until `bun install -g ccstatusline`). The local memory store is empty here (the prior `dotclaude-handoff-skill` entry is local state and did not transfer).
