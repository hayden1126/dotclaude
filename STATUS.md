# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design rationale lives in its plan under `~/.claude/plans/`.

Last updated: 2026-07-11
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git holds the detail)
- **Status-line ctx chip: percent + divider** (2026-07-11, follow-up to PR #12).
  `statusline/ctx-breakdown.py` total chip now renders its share of the (auto-compact) window as a
  percent and is set off from the per-category chips by a dim `▏`; README prose updated to match.
  Widget is now actually installed live on this machine (setup.sh had not been re-run since PR #12
  merged, so it had never been active). Derive PR/merge state with `gh pr list`.
- **Handoff-lifecycle hardening** (2026-07-11, `4df5a49..af14b97`). Three parts: (1)
  `skills/handoff/SKILL.md` now enforces prune-as-you-write (delete-test, one overwritten next-session
  block, ~100-120 line ceiling) and a "Volatile git state: derive, never store" rule (push/merge/PR
  status derived via `git`/`gh`, never written into STATUS; `gh pr view` for merge, which survives
  squash); (2) `hooks/handoff-reminder.sh` rewritten precision-first: fires only on genuine wrap-up
  commands, silent on "handoff" as a topic word and on injected system content (23-case battery); (3)
  `CLAUDE.md` gains a read-side resume line (read STATUS.md on session start). `templates/STATUS.md` +
  README updated to match. See [[dotclaude-handoff-skill]].
- **WSL2 `chrome-devtools-mcp` fix (opt-in)** (2026-07-10, PR #13). `setup-chrome-wsl.sh` installs Chrome
  for Testing and registers a user-scoped `chrome-devtools` MCP override that shadows the plugin's broken
  default server (WSL2 cannot launch Chrome otherwise); `docs/chrome-devtools-wsl.md` + `chrome-debug.ps1`
  cover Strategy A (headless Linux) and B (attach to Windows Chrome). Not wired into `setup.sh`, so non-WSL
  is unaffected. See [[dotclaude-chrome-devtools-wsl]].
- Prior shipped (git + memory hold detail): research-sourcing skill (PR #10), staged-reader-review
  bundle upgrade, danger-guard opt-in auto mode, statusline ctx chips (PR #12).

## In flight
- None.

## Blocked / decisions needed
- None.

## Notes for next session
- chrome-devtools-wsl activation: to activate the fix in a live session on THIS machine, fully restart
  Claude Code (`/mcp` should then list `chrome-devtools` as Connected). A fresh clone on a new WSL machine
  needs `./setup-chrome-wsl.sh` run once (the override is in `~/.claude.json` user scope, not the repo);
  non-WSL machines need nothing.
- research-sourcing follow-ups (all optional): (1) the thorough-tier planted-fabrication spot-check is
  specified but not exercised end-to-end (only the subagent-side change was tested live); (2) only tested
  with Agent-tool subagents, not a real Workflow-tool run; (3) `SKILL.md` is ~927 words (kept deliberately).
- Deferred (also in [[dotclaude-handoff-skill]]): (1) the deterministic PreCompact/Stop safety-net hook,
  revisit only after testing the `SessionStart` `compact`-matcher re-inject path (bug #15174); (2) the
  autonomous loop-engineering handoff (a Python orchestrator step that refreshes the RESUME block).
- Evaluated and SKIPPED, do not re-raise: (a) wiring `handoff-reminder.sh` into the loop-engineering inner
  loop (the puppet gets one machine prompt with no wrap-up phrase, so the hook has no addressee; the skill
  already inherits there); (b) cross-platform notifiers for the toast (YAGNI on this WSL-only setup).
