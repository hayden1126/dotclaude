#!/usr/bin/env bash
# Set @claude_state on the tmux window this session is shown in, for the per-window indicator
# (tmux/claude.conf renders ◐ for busy, ✳ for wait, nothing for idle). Wired in settings.json:
#   busy  <- UserPromptSubmit, PreToolUse, PostToolUse   (a turn started / work is happening)
#   wait  <- Notification                                (Claude needs your input)
#   idle  <- Stop                                        (turn finished), main session only
# session-pane.sh finds the window: a tab's own pane, a background session's mapped pane, or none
# (outside tmux, an unmapped background session, a `claude -p` run). A subagent's Stop carries
# agent_id/agent_type and must not clear the window while the main turn still runs, and its
# busy must not cover the main session's wait (a question shown while a subagent works).
# tmux/tmux-claude-status is the backstop for what hooks can't see (a crash, a cold attach).
# Fail-open: always exits 0.
set -uo pipefail

state="${1:-}"
[ -n "$state" ] || exit 0
input=$(cat 2>/dev/null)
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/session-pane.sh" 2>/dev/null || exit 0
pane=$(session_pane "$input")
[ -n "$pane" ] || exit 0

spawned=""
# Busy fires on every tool call: skip the interpreter unless the payload could name an agent.
[[ $input == *'"agent_'* ]] && spawned=$(printf '%s' "$input" | python3 -I -c 'import sys, json
try: d = json.load(sys.stdin)
except Exception: d = {}
print("1" if isinstance(d, dict) and (d.get("agent_id") or d.get("agent_type")) else "")' 2>/dev/null)
if [ -n "$spawned" ]; then
  [ "$state" = "idle" ] && exit 0
  # A background subagent's tool calls must not cover a question the main session is waiting
  # on; the main session's own next event clears the wait.
  if [ "$state" = "busy" ] &&
     [ "$(tmux show-option -wqv -t "$pane" @claude_state 2>/dev/null)" = "wait" ]; then
    exit 0
  fi
fi

tmux set-option -w -t "$pane" @claude_state "$state" 2>/dev/null
exit 0
