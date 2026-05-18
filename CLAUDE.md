# User-level instructions

## Auto-memory: aggressive mode

The system prompt describes the default auto-memory system at `~/.claude/projects/-home-<user>/memory/`. These instructions **override the defaults** with a lower threshold and broader categories. When the system prompt's auto-memory guidance conflicts with what's below, follow what's below.

### Lower threshold — save more, not less

The default guidance says "save when notable." That bar is too high for this user. Instead:

- Save small observations too: tool preferences, command-line habits, naming quirks, workflow patterns, even minor recurring frustrations
- When in doubt, save. A noisy index is recoverable; a missing observation is not
- Still skip the explicit don't-save list (code patterns derivable from the codebase, git history, ephemeral task state, anything already in a CLAUDE.md)
- Still no duplicates — update existing memories before creating new ones

### End-of-turn scan (forced)

Before ending any turn that involved real interaction (not a single trivial lookup), do a quick scan:

> Did anything in this turn reveal something about the user, their preferences, project state, or external references that's worth keeping for next session?

If yes, write the memory immediately. Don't wait for a "good moment." The scan is the moment.

### Extended categories

In addition to the four default types (`user`, `feedback`, `project`, `reference`), use these four:

| Type | When to save | Body structure |
|------|---|---|
| `decision` | A meaningful design/architectural/tooling choice was made — "we picked X over Y" | Decision, then **Alternatives considered:** and **Why this won:** lines |
| `session-log` | At end of a substantive working session: 1-3 lines on what was accomplished, what's mid-flight, what's blocked | Date heading, then bullets. One entry per session — append, don't fragment |
| `pattern` | A recurring command sequence, workflow, or template the user reuses | Pattern, then **When to use:** and a worked example |
| `todo` | A "come back to this" item the user surfaced but didn't act on | Item, then **Surfaced:** date and **Trigger:** (what would prompt revisiting) |

Same file format as default memory types — frontmatter with `name`, `description`, `metadata.type`, then the body. Index in `MEMORY.md` exactly like the defaults.

### MEMORY.md hygiene

The index gets truncated past line 200. With a lower threshold, it will grow. When it crosses ~150 lines:

- Group related entries under H2 headings (`## User`, `## Project`, `## Decisions`, etc.) so the most-loaded section stays toward the top
- Consider whether older session-log entries can be deleted (they age out fast)
- Don't summarize-merge entries unless they're truly redundant — losing detail defeats the purpose

### Compaction rules (applies to any consolidation pass)

Compaction may be triggered by Anthropic's `autoDreamEnabled` background process (now on), or by you noticing index bloat mid-session, or by the user asking explicitly. Whatever the trigger, follow these four rules:

1. **Dedupe.** If two entries cover the same fact written differently, merge them into the more specific one and delete the other. Update the `MEMORY.md` index accordingly.

2. **Prune stale session-logs.** Session-log entries older than ~30 days can be deleted outright (they're chronological notes, not load-bearing facts). Anything that got promoted to another category before deletion is fine; the original session-log entry has served its purpose.

3. **Verify before pruning.** Before deleting any entry that names a specific file path, function, flag, or external resource: confirm the named thing still exists (Read for paths, grep for symbols, check for URLs). If it's gone, the memory is genuinely stale and safe to remove. If it still exists, the memory may still be useful — keep it or update it rather than deleting.

4. **Promote patterns.** If session-log entries mention the same workflow or command sequence 3+ times across different dates, write a proper `pattern` entry capturing it and delete the originating session-log mentions. The pattern entry should be more useful than three log notes ever were.

After any compaction pass, the `MEMORY.md` index should be shorter, not longer.
