#!/usr/bin/env bash
# Set @claude_state on the tmux window this session is shown in, for the per-window indicator
# (tmux/claude.conf renders ◐ for busy, ✳ for wait, nothing for idle). Wired in settings.json:
#   busy  <- UserPromptSubmit, PreToolUse, PostToolUse, SubagentStop   (work is happening)
#   wait  <- PermissionRequest, Notification permission_prompt|elicitation_dialog (a dialog)
#   idle  <- SessionStart startup|resume|clear                        (a fresh or cleared chat)
# A Stop's state is hooks/stop-ring.sh's (busy while counted background work runs, wait when
# hooks/wants_input.py reads the reply as wanting the person), since it has the task facts.
#
# wait goes through the wait set (session-pane.sh): each dialog adds its owner's token and
# each owner's own later event removes it, so the tab shows wait until every open dialog is
# answered. PermissionRequest fires 25-35 ms after PreToolUse when a dialog is shown (never for
# a call the auto-mode classifier approves) and names the subagent whose dialog it is; the
# Notification 6 s later never names one, so it adds the main token only when nothing holds the
# wait, except an elicitation dialog (no PermissionRequest), which always adds it. A subagent's
# own tool calls and its SubagentStop remove its token: approve fires its PostToolUse, deny
# ends it. The main session's events remove the main token and the Stop's turn token, so a
# classifier still running for that Stop never paints over newer work.
#
# session-pane.sh finds the window: a tab's own pane, a background session's mapped pane, or none
# (outside tmux, an unmapped background session, a `claude -p` run).
# tmux/tmux-claude-status is the backstop for what hooks can't see (a crash, a cold attach).
# Fail-open: always exits 0.
set -uo pipefail

mode="${1:-}"
[ -n "$mode" ] || exit 0
input=$(cat 2>/dev/null)
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/session-pane.sh" 2>/dev/null || exit 0
pane=$(session_pane "$input")
[ -n "$pane" ] || exit 0

# A subagent's event names it: its agent_id when that is a plain name, "-" for one without (an
# agent_type alone). Busy fires on every tool call: skip the interpreter unless the payload
# could name an agent.
agent=""
[[ $input == *'"agent_'* ]] && agent=$(printf '%s' "$input" | python3 -I -c 'import sys, json, re
try: d = json.load(sys.stdin)
except Exception: d = {}
a = d.get("agent_id") if isinstance(d, dict) else None
if isinstance(a, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", a): print(a)
elif isinstance(d, dict) and (a or d.get("agent_type")): print("-")' 2>/dev/null)
event="" kind=""
re='"hook_event_name" *: *"([A-Za-z]+)"'
[[ $input =~ $re ]] && event=${BASH_REMATCH[1]}
re='"notification_type" *: *"([a-z_]+)"'
[[ $input =~ $re ]] && kind=${BASH_REMATCH[1]}

case "$mode" in
  busy)
    if [ -z "$agent" ]; then
      glyph_cmd set-option -uw -t "$pane" @claude_turn
      glyph_drop "$pane" main
    elif [ "$agent" != - ]; then
      glyph_drop "$pane" "agent-$agent"
    fi
    glyph_state "$pane" busy
    ;;
  wait)
    if [ "$event" = Notification ] && [ "$kind" != elicitation_dialog ]; then
      glyph_cmd set-option -wF -t "$pane" @claude_wait_by \
        "#{?#{@claude_wait_by},#{@claude_wait_by},!main!}"
    elif [ -n "$agent" ] && [ "$agent" != - ]; then
      glyph_add "$pane" "agent-$agent"
    else
      glyph_add "$pane" main
    fi
    glyph_cmd set-option -w -t "$pane" @claude_state wait
    ;;
  idle)
    [ -z "$agent" ] || exit 0
    glyph_cmd set-option -uw -t "$pane" @claude_turn
    glyph_cmd set-option -uw -t "$pane" @claude_wait_by
    glyph_cmd set-option -w -t "$pane" @claude_state idle
    ;;
  *) exit 0 ;;
esac
glyph_flush
exit 0
