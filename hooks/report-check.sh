#!/usr/bin/env bash
# PreToolUse(SubagentHandback) and SubagentStop hook: check a delegated role's report against
# skills/delegation/report.schema.json and send it back (at most twice) when it doesn't match
# (skills/delegation/scripts/report-check). FAILS OPEN on purpose: it is an acceptance check,
# and a broken checker must never swallow a report, so this always exits 0; a rejection is the
# JSON it prints.
python3 "$HOME/.claude/skills/delegation/scripts/report-check" 2>/dev/null
exit 0
