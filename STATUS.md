# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume from here after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable decisions
> (`dotclaude-handoff-skill`, `dotclaude-research-sourcing-skill`). Per-effort design rationale lives in its
> plan under `~/.claude/plans/`.

Last updated: 2026-07-09
Branch: feat/research-sourcing-skill (PR #10 open; merged current `main` in to clear conflicts). Base is `main`.

## Done
- Upgraded `skills/staged-reader-review/SKILL.md` to the sourced-bundle version (2026-07-09, byte-identical
  to sourced PR #77). Dual-home decision: the skill lives in both this repo (the no-sourced distribution
  channel) and the sourced bundle (canonical); the `~/.claude/skills/staged-reader-review` symlink into this
  repo stays, and `sourced global-install` writing through it is the sync mechanism, so a future bundle
  change surfaces here as a diff to commit. New in this version: the forced artifact
  `<draft>.reader-review.md` (stable S/RR/RN ids, fixed three-value verdict), the sourced editing-gate
  pre-flight record, rendered-output input rules, and no em dashes.
- Authored `skills/research-sourcing/` (`SKILL.md` + `reference.md`): a manually-invoked skill for logging
  verifiable sources during multiagent deep-research runs. Each subagent writes a JSON shard (URL, dates,
  verbatim `exact_quote`, the claim it supports); the orchestrator merges, dedups, spot-checks, and renders
  `SOURCES.md`. Two tiers: `lean` (default, core fields) and `thorough` (adds access_mode / verification_status
  / quote_trace / reliability + an orchestrator spot-check). Adapted from `~/sourced`'s citation mechanism,
  minus the Python/pandoc/academic-tier machinery. Design + decisions in the plan
  `~/.claude/plans/i-want-to-create-nested-adleman.md`.
  - Manual-trigger design: the `description` names only explicit-request triggers plus a "do not fire on
    ordinary research" guard, so it stays dormant until invoked by name. The binding mechanism is the paste-in
    dispatch contract (`reference.md` section 2) the orchestrator inlines into every subagent prompt, because
    subagents do not auto-load skills.
  - Verified RED to GREEN live on an HTTP-103 research task (Agent-tool subagents). Baseline (no contract):
    paraphrase, a bulk URL list, confabulated stats. With the contract: 12-13 per-claim entries with verbatim
    quotes + traces, refusing to log the snippet-only claims the baseline had asserted. Shard validated as
    well-formed JSON.
  - README `skills/` row updated; `setup.sh` auto-globs `skills/*/`, so no wiring change; symlinked into
    `~/.claude/skills/`.
- Added an opt-in **auto mode** to `hooks/danger-guard.sh` (2026-06-26, commit `17d7989` on `main`): an
  `auto_enabled()` helper (env `DANGER_GUARD_AUTO=1` or sentinel `~/.claude/.danger-guard-auto`) flips the
  guard to allow-by-default, every dangerous op drops to a single `ask` and all other bash is `allow`. Off by
  default; two-tier deny/ask unchanged when off. README hooks section updated.

## In flight
- None. research-sourcing is authored, tested, committed, and pushed (PR #10). danger-guard auto mode is
  merged to `main`.

## Blocked / decisions needed
- None.

## Notes for next session
- Next concrete step: PR #10 conflicts resolved via this merge; merge PR #10 to `main`.
- research-sourcing follow-ups (all optional): (1) the thorough-tier planted-fabrication spot-check
  (orchestrator re-opens an entry, diffs `quote_trace` against the source, unmerges + escalates on a mismatch)
  is *specified but not exercised end-to-end*: only the subagent-side behavior change was tested live.
  (2) Only tested with Agent-tool subagents, not a real Workflow-tool run (where agents could return structured
  output instead of file shards). (3) `SKILL.md` is 927 words, above the ~600 aim; kept deliberately
  (load-bearing discipline block). (4) Minor: the test subagent's `quote_trace` ran slightly longer than
  exactly 20 chars, harmless for the substring spot-check.
- Deferred work (also in memory `dotclaude-handoff-skill`): (1) the *deterministic* PreCompact/Stop safety-net
  hook, revisit only after testing the `SessionStart` `compact`-matcher re-inject path (bug #15174); distinct
  from the shipped `UserPromptSubmit` reminder hook. (2) the autonomous loop-engineering handoff (a Python
  orchestrator step that refreshes the RESUME block).
- Evaluated and SKIPPED, do not re-raise: (a) wiring `handoff-reminder.sh` into the loop-engineering inner
  loop (the puppet gets one machine prompt with no wrap-up phrase, so the hook has no addressee; the skill
  already inherits there); (b) cross-platform notifiers (osascript / notify-send) for the toast (YAGNI on this
  WSL-only setup; README documents the manual macOS/Linux swap).
- Commit ranges: handoff skill `8bb222d..681ae87`; reminder hook PR #2 (`3454cc2..ab9ba6b`); the 2026-06-19
  session (`1ba4c66..0039235`) merged PRs #1 and #4 through #8; the 2026-06-26 session added danger-guard auto
  mode (`17d7989` on `main`); the 2026-07-08 session added `skills/research-sourcing` (commit `3b25aa7`, base
  `6b293a0`, PR #10). See `git log`.
