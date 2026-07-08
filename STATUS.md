# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume from here after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable decisions
> (`dotclaude-handoff-skill`, `dotclaude-research-sourcing-skill`). Per-effort design rationale lives in its
> plan under `~/.claude/plans/`.

Last updated: 2026-07-08
Branch: feat/research-sourcing-skill (committed + pushed; PR not yet opened). Base is `main` (6b293a0).

## Done
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
- Verified RED->GREEN live on an HTTP-103 research task (Agent-tool subagents). Baseline (no contract):
  paraphrase, a bulk URL list, and confabulated stats ("~93%", "Safari 17 preconnect-only"). With the
  contract: 12-13 per-claim entries with verbatim quotes + traces, and it *refused to log* the two
  snippet-only claims the baseline had asserted (they went to its Gaps report). Shard validated as
  well-formed JSON against the schema.
- README `skills/` row updated to include `research-sourcing`. `setup.sh` auto-globs `skills/*/`, so no
  wiring change was needed; symlinked into `~/.claude/skills/`.

## In flight
- None. The skill is authored, tested, committed on `feat/research-sourcing-skill`, and pushed.

## Blocked / decisions needed
- None.

## Notes for next session
- Next concrete step: open a PR for `feat/research-sourcing-skill` and merge to `main` (prior work all went
  through PRs).
- research-sourcing follow-ups (all optional): (1) the thorough-tier planted-fabrication spot-check
  (orchestrator re-opens an entry, diffs `quote_trace` against the source, unmerges + escalates on a mismatch)
  is *specified but not exercised end-to-end* — only the subagent-side behavior change was tested live.
  (2) Only tested with Agent-tool subagents, not a real Workflow-tool run (where agents could return
  structured output instead of file shards). (3) `SKILL.md` is 927 words, above the ~600 aim; kept
  deliberately (load-bearing discipline block); revisit only if it feels heavy in use. (4) Minor: the test
  subagent's `quote_trace` ran slightly longer than exactly 20 chars — harmless for the substring spot-check.
- Carried-forward deferred work from the handoff effort (unchanged, also in memory `dotclaude-handoff-skill`):
  (1) the *deterministic* PreCompact/Stop safety-net hook, revisit only after testing the `SessionStart`
  `compact`-matcher re-inject path (bug #15174); distinct from the shipped `UserPromptSubmit` reminder hook.
  (2) the autonomous loop-engineering handoff (a Python orchestrator step that refreshes the RESUME block).
- Commit range this session: `6b293a0..` this branch's tip. See `git log feat/research-sourcing-skill`.
