#!/usr/bin/env bash
# Set @claude_state on the tmux window this session is shown in, for the per-window indicator
# (tmux/claude.conf renders ◐ for busy, ✳ for wait, nothing for idle). Wired in settings.json:
#   busy  <- UserPromptSubmit, PreToolUse, PostToolUse   (a turn started / work is happening)
#   wait  <- Notification                                (Claude needs your input)
#   idle  <- Stop                                        (turn finished), main session only
# session-pane.sh finds the window: a tab's own pane, or none (outside tmux, a background
# session, a `claude -p` run). A subagent's Stop
# carries agent_id/agent_type and must not clear the window while the main turn still runs.
# tmux/tmux-claude-status is the backstop for what hooks can't see (a crash, a cold attach).
# Fail-open: always exits 0.
set -uo pipefail

state="${1:-}"
[ -n "$state" ] || exit 0
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/session-pane.sh" 2>/dev/null || exit 0
pane=$(session_pane)
[ -n "$pane" ] || exit 0

if [ "$state" = "idle" ]; then
  spawned=$(python3 -I -c 'import sys, json
try: d = json.load(sys.stdin)
except Exception: d = {}
print("1" if isinstance(d, dict) and (d.get("agent_id") or d.get("agent_type")) else "")' 2>/dev/null)
  [ -n "$spawned" ] && exit 0
fi

tmux set-option -w -t "$pane" @claude_state "$state" 2>/dev/null
exit 0
