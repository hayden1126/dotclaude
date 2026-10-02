#!/usr/bin/env bash
# Stop hook, main thread only: the watch guard (skills/delegation/scripts/watch-guard). It
# blocks a turn's end once when a long wait has lapsed, a watched job ended unnoticed, or a
# background command was killed at its time limit, printing the block as JSON. The script
# itself skips a subagent's stop (a top-level agent_id); a substring test here would also skip
# a main-thread stop whose background_tasks hold a teammate. It FAILS OPEN: it always exits 0,
# and its errors land in ${XDG_STATE_HOME:-~/.local/state}/dotclaude/delegation-ledger.err.
python3 "$HOME/.claude/skills/delegation/scripts/watch-guard" 2>/dev/null
exit 0
