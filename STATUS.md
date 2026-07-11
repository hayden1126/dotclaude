# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]]). Per-effort design
> rationale lives in its plan under `~/.claude/plans/`.

Last updated: 2026-07-11
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git holds the detail)
- **Handoff-lifecycle hardening** (2026-07-11, branch `docs/handoff-derive-git-state`,
  `4df5a49..af14b97`). Three parts: (1) `skills/handoff/SKILL.md` now enforces prune-as-you-write
  (delete-test, one overwritten next-session block, ~100-120 line ceiling) and a "Volatile git state:
  derive, never store" rule (push/merge/PR status derived via `git`/`gh`, never written into STATUS;
  `gh pr view` for merge, which survives squash); (2) `hooks/handoff-reminder.sh` rewritten
  precision-first: fires only on genuine wrap-up commands, silent on "handoff" as a topic word and on
  injected system content (verified with a 23-case battery); (3) `CLAUDE.md` gains a read-side resume
  line (read STATUS.md on session start), the bookend to the skill. `templates/STATUS.md` + README
  updated to match. See [[dotclaude-handoff-skill]].
- **research-sourcing** skill authored + merged (PR #10, merged 2026-07-08). See
  [[dotclaude-research-sourcing-skill]].
- **staged-reader-review** upgraded to the sourced-bundle version; **danger-guard** opt-in auto mode.
  Git + README hold the detail.

## In flight
- None. This session's work is complete on branch `docs/handoff-derive-git-state` (`4df5a49..af14b97`).

## Blocked / decisions needed
- None.

## Notes for next session
- No pressing next step on dotclaude: this session's handoff-lifecycle work is complete on
  `docs/handoff-derive-git-state` (`4df5a49..af14b97`); check `gh pr list` / `git log main` for its
  merge state. PR #10 is already merged; do not re-raise it.
- research-sourcing follow-ups (all optional): (1) the thorough-tier planted-fabrication spot-check is
  specified but not exercised end-to-end (only the subagent-side change was tested live); (2) only
  tested with Agent-tool subagents, not a real Workflow-tool run; (3) `SKILL.md` is ~927 words (kept
  deliberately, load-bearing discipline block).
- Deferred (also in [[dotclaude-handoff-skill]]): (1) the deterministic PreCompact/Stop safety-net hook,
  revisit only after testing the `SessionStart` `compact`-matcher re-inject path (bug #15174); (2) the
  autonomous loop-engineering handoff (a Python orchestrator step that refreshes the RESUME block).
- Evaluated and SKIPPED, do not re-raise: (a) wiring `handoff-reminder.sh` into the loop-engineering
  inner loop (the puppet gets one machine prompt with no wrap-up phrase, so the hook has no addressee;
  the skill already inherits there); (b) cross-platform notifiers for the toast (YAGNI on this WSL-only
  setup; README documents the manual macOS/Linux swap).
