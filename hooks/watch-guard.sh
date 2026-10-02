#!/usr/bin/env bash
# Stop hook, main thread only: the watch guard (skills/delegation/scripts/watch-guard). It
# blocks a turn's end once when a long wait has lapsed or a background command was killed at
# its time limit, printing the block as JSON. A subagent's stop carries "agent_id" and is
# skipped here (the inverse of stop-ring.sh's test). It FAILS OPEN: it always exits 0, and its
# errors land in ${XDG_STATE_HOME:-~/.local/state}/dotclaude/delegation-ledger.err.
input=$(cat)
case "$input" in *'"agent_id"'*) exit 0 ;; esac
printf '%s' "$input" | python3 "$HOME/.claude/skills/delegation/scripts/watch-guard" 2>/dev/null
exit 0
