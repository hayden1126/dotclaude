#!/usr/bin/env bash
# PreToolUse(SubagentHandback) and SubagentStop hook: send a subagent's report back (at most
# twice) while one of its own background commands still runs, or when a delegated role's report
# doesn't match skills/delegation/report.schema.json (skills/delegation/scripts/report-check).
# FAILS OPEN on purpose: it is an acceptance check,
# and a broken checker must never swallow a report, so this always exits 0; a rejection is the
# JSON it prints.
python3 "$HOME/.claude/skills/delegation/scripts/report-check" 2>/dev/null
exit 0
