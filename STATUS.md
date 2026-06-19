# STATUS: durable session-handoff skill

> Living state. Update at the end of every working block so a fresh session can resume from here after `/clear`.
> Design rationale lives in `docs/durable-handoff-brief.md` (RESOLVED) and the plan at
> `~/.claude/plans/read-docs-durable-handoff-brief-md-and-p-precious-cherny.md`. The durable decision and
> the verified hook-capability facts live in memory (`dotclaude-handoff-skill`). This doc is current state
> and next steps only, it does not restate those.

Last updated: 2026-06-19
Branch: main (origin/main in sync)

## Done
- Authored `skills/handoff/SKILL.md`: an advisory, skill-only v1 handoff procedure (survey, reconcile doc-drift as an early gate, update STATUS, curate memory, commit, leave pointers). Symlinked into `~/.claude/skills/handoff`, discoverable as `/handoff`. Commit `8bb222d` (skill plus the drift it caught when dogfooded on its own implementation).
- Peer-reviewed and sharpened after a multi-lens critique flagged mild overengineering, redundancy, and a writing-voice caps violation: de-capped emphasis, tightened the Overview, removed a redundant meta-paragraph. Commit `681ae87`. Both commits pushed.
- Memory entry `dotclaude-handoff-skill` records the v1 decision and the verified facts (no hook sees context fill; a hook cannot inject text that survives compaction; durable vector is a file on disk; a skill inherits to the loop-engineering inner puppet for free, a hook does not).
- Shipped the lightweight-trigger half of the original seed recommendation: `hooks/handoff-reminder.sh`, a `UserPromptSubmit` advisory hook that nudges to invoke `/handoff` on wrap-up / handoff / clear signals. It only adds a reminder (does not perform the handoff), is fail-open, and never blocks a prompt, so the skill-only decision still holds. PR #2 (`3454cc2`, merged `ab9ba6b`); documented in README.

## In flight
- None. The v1 skill and the `UserPromptSubmit` reminder hook (PR #2) are both shipped.

## Blocked / decisions needed
- Open skill-design note (surfaced by dogfooding): step 3 says "seed STATUS.md if absent," but in a lean config repo like this one the brief already plays the living-doc role, so a fresh STATUS.md risks partial duplication. This STATUS.md is kept non-duplicative by pointing to the brief and memory. Decide whether the skill should say "if the repo already has a living doc, update that instead of creating STATUS.md."

## Notes for next session
- Deferred work (kept consistent with the brief RESOLVED note and memory): (1) the *deterministic* PreCompact/Stop safety-net hook, revisit only after empirically testing the `SessionStart` `compact`-matcher re-inject path (open bug #15174). This is distinct from the `UserPromptSubmit` reminder hook already shipped in PR #2; the safety-net is the still-deferred piece. (2) the autonomous loop-engineering handoff (a Python orchestrator step that refreshes the RESUME block), which the interactive skill does not cover because the headless maker has no skills.
- To verify the skill still works: invoke `/handoff` in a session with real changes and confirm it surveys, reconciles drift, updates STATUS, curates memory, and reports git state.
- Commit ranges: skill shipped in `8bb222d..681ae87`; reminder hook in PR #2 (`3454cc2..ab9ba6b`). This session merged PR #1 (notify, `59d4af7`) and PR #4 (notify docs, `ef171cf`), then reconciled these handoff docs (see `git log` on `main`).
