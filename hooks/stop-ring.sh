#!/usr/bin/env bash
# Stop hook: ring the notify sound when a session a person sees finishes its turn: a tab, a
# plain terminal, or a background session mapped to its tab (session-pane.sh decides). Quiet for
# a subagent or background agent (agent_id/agent_type in the event), an unmapped background
# session, and a `claude -p` run such as the delegation canary. Also quiet when the turn ends
# with background work in flight (an agent or shell it will be woken by): the session isn't done,
# and a question needing the person rings through notify.sh. Every decision goes to ring.log.
#
# settings.json invokes this as `bash "$HOME/.claude/hooks/stop-ring.sh"`. Event JSON arrives
# on stdin. Fail-open: any error skips the sound (exit 0), never blocks.
set -uo pipefail

input=$(cat 2>/dev/null)
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/session-pane.sh" 2>/dev/null || exit 0

# Three facts from the event: "spawned" (a subagent's stop), "busy" (the session is paused on
# background work that will wake it, so it is neither done nor waiting on the person) and
# "tasks" (the in-flight task labels, for ring.log). background_tasks' `type` is Claude Code's
# friendly label ("shell", "subagent"), not the internal task name (local_bash, local_agent),
# which appears only for a type with no label. Teammates linger in the list after they finish,
# dream is memory upkeep and a monitor can run for hours, so those don't count.
read -r spawned busy tasks < <(printf '%s' "$input" | python3 -I -c 'import sys, json
try: d = json.load(sys.stdin)
except Exception: d = {}
if not isinstance(d, dict): d = {}
spawned = 1 if (d.get("agent_id") or d.get("agent_type")) else 0
waits = {"subagent", "shell", "workflow", "cloud session"}
tasks = d.get("background_tasks")
types = [t.get("type") for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else []
busy = 1 if any(t in waits for t in types) else 0
labels = ",".join(t.replace(" ", "_") for t in types if isinstance(t, str) and t.strip())
print(spawned, busy, labels or "-")' 2>/dev/null)

pane=$(session_pane "$input")
if [ "${spawned:-0}" = 0 ] && [ "${busy:-0}" = 0 ] && session_in_view "$pane"; then
  play_ring
  ring_log stop "rang tasks=${tasks:--}" "$pane" "$input"
elif [ "${busy:-0}" = 1 ]; then
  ring_log stop "quiet busy=1 tasks=${tasks:--}" "$pane" "$input"
else
  ring_log stop "quiet tasks=${tasks:--}" "$pane" "$input"
fi
exit 0
