#!/usr/bin/env bash
# Stop hook: ring the notify sound ONLY when the MAIN interactive session finishes,
# not when a subagent or background agent stops.
#
# The Stop event fires for the main session AND for Task subagents AND for background
# agents. Spawned sessions carry `agent_id`/`agent_type` in the event JSON; the main
# session has neither. So: ring only when both are absent. (Teammates fire TeammateIdle,
# a different event, so they never reach here.)
#
# settings.json invokes this as `bash "$HOME/.claude/hooks/stop-ring.sh"`. Event JSON
# arrives on stdin. Fail-open: any error just skips the sound (exit 0), never blocks.
# Uses python3 (jq is not installed here), matching notify.sh.

set -uo pipefail

input=$(cat 2>/dev/null)

py=$(command -v python3 || command -v python || true)
spawned=""
if [[ -n "$py" ]]; then
  # prints "spawned" if agent_id or agent_type is present, else nothing
  spawned=$(printf '%s' "$input" | "$py" -c \
    'import sys,json
try: d=json.load(sys.stdin)
except Exception: d={}
print("spawned" if (d.get("agent_id") or d.get("agent_type")) else "")' 2>/dev/null)
fi

# Ring only for the main session (no agent_id/agent_type).
if [[ -z "$spawned" ]]; then
  ( powershell.exe -c "(New-Object Media.SoundPlayer 'C:\\Windows\\Media\\notify.wav').PlaySync()" >/dev/null 2>&1 & )
fi
exit 0
