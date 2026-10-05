#!/usr/bin/env bash
# Stop hook: ring the notify sound when a session a person sees finishes its turn: a tab, a
# plain terminal, or a background session mapped to its tab (session-pane.sh decides). Quiet for
# a subagent or background agent (agent_id/agent_type in the event), an unmapped background
# session, and a `claude -p` run such as the delegation canary. Every decision goes to ring.log.
#
# settings.json invokes this as `bash "$HOME/.claude/hooks/stop-ring.sh"`. Event JSON arrives
# on stdin. Fail-open: any error skips the sound (exit 0), never blocks.
set -uo pipefail

input=$(cat 2>/dev/null)
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/session-pane.sh" 2>/dev/null || exit 0

spawned=$(printf '%s' "$input" | python3 -I -c 'import sys, json
try: d = json.load(sys.stdin)
except Exception: d = {}
print("1" if isinstance(d, dict) and (d.get("agent_id") or d.get("agent_type")) else "")' 2>/dev/null)

pane=$(session_pane "$input")
if [ -z "$spawned" ] && session_in_view "$pane"; then
  play_ring
  ring_log stop rang "$pane" "$input"
else
  ring_log stop quiet "$pane" "$input"
fi
exit 0
