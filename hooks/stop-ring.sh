#!/usr/bin/env bash
# Stop hook: ring the notify sound when a session a person sees finishes its turn: a tab, a
# plain terminal, or a background session mapped to its tab (session-pane.sh decides). Quiet for
# a subagent or background agent (agent_id/agent_type in the event), an unmapped background
# session, and a `claude -p` run such as the delegation canary. Also quiet when the turn ends
# with background work in flight (an agent or shell it will be woken by): the session isn't done,
# and a question needing the person rings through notify.sh. Every decision goes to ring.log.
#
# A ring waits DOTCLAUDE_RING_SETTLE seconds (default 1) first, detached, and is dropped if the
# transcript gains a queue dequeue meanwhile: a queued input started the next turn at once.
# background_tasks lists running tasks only, so a task that finished mid-turn is gone from it
# while its notice still waits in the queue (as does a prompt typed mid-turn). The dequeue lands
# within 0.3 s of the Stop in 99% of past cases.
#
# The same hook sets the tab glyph for a main session's Stop in a known pane (tmux-state.sh has
# the rest of the glyph's events). It writes the window's turn token (the prompt_id and the
# time), then busy while a counted task runs (the ring's rule below), else idle, and drops the
# wait-set tokens (session-pane.sh) of the main session and of any subagent no longer running.
# Then a detached child asks hooks/wants_input.py whether the reply wants the person, waiting
# out the settle window meanwhile. yes, or an error (redundancy over silence), paints wait, but
# only while the window still holds this Stop's token: any later main event clears it. A queued
# prompt that started a new turn (a dequeue, as above) fires no UserPromptSubmit (its hook ran
# when it was queued, before this Stop), so then the child paints busy instead. Each verdict
# goes to ring.log as `stop input=<yes|no|error> [reason=...] ms=<n> painted=<1|0|->`.
#
# settings.json invokes this as `bash "$HOME/.claude/hooks/stop-ring.sh"`. Event JSON arrives
# on stdin. Fail-open: any error skips the sound (exit 0), never blocks.
set -uo pipefail

input=$(cat 2>/dev/null)
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/session-pane.sh" 2>/dev/null || exit 0

# Seven facts from the event: "spawned" (a subagent's stop), "busy" (the session is paused on
# background work that will wake it, so it is neither done nor waiting on the person), "tasks"
# (the in-flight task labels, for ring.log), "agents" (the running subagents' ids, for the wait
# set), the prompt_id ("-" when it isn't a plain name), and the transcript's size now and its
# path ("-" and nothing when it can't be read). background_tasks' `type` is Claude Code's friendly label
# ("shell", "subagent"), not the internal task name (local_bash, local_agent), which appears only
# for a type with no label. A Monitor arrives as "shell" too; stop_ring.task_types relabels it
# "monitor" from the transcript (PLAN.md A10), and the Artifact tool's live watch "artifact
# watch". Teammates linger in the list after they finish, dream is memory upkeep and a monitor
# can run for hours, so those don't count.
#
# The same step writes the session's stop record, $XDG_STATE_HOME/dotclaude/stops/<session>.json
# (time, the waits in flight, every task's label, id and description, the transcript path, and
# `replies`: what Claude said in the last 5 turns), for every stop but a subagent's, and prunes
# records older than 7 days once a day. pass-respawn's plain mode respawns only after a stop with
# no task but dream or an artifact watch, since in-process agents are no child process it could
# see; it reads the transcript there and copies `replies` for the respawned session's banner
# (hooks/pass-banner.sh) and Ctrl-b Up (tmux/pass-last). hooks/stop_ring.py, beside this script's
# real path and run with python3 -I, does all of this and has the details.
here=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
read -r spawned busy tasks agents prompt size transcript < <(printf '%s' "$input" | \
  python3 -I "$here/stop_ring.py" 2>/dev/null)

# True when the transcript gained a queue dequeue (or popAll) past byte $2: a queued input
# started the next turn. Args: transcript path, its size at the Stop ("-" when unreadable).
resumed() {
  [ "${2:--}" != - ] &&
    grep -qE '"operation" *: *"(dequeue|popAll)"' < <(tail -c +"$(( $2 + 1 ))" "$1" 2>/dev/null)
}

# Ring unless a queued input resumed within the settle window. Args: transcript path, its size
# at the Stop, pane.
settle_then_ring() {
  sleep "${DOTCLAUDE_RING_SETTLE:-1}"
  if resumed "$1" "$2"; then
    ring_log stop "quiet resumed=1 tasks=${tasks:--}" "$3" "$input"
  else
    ring_log stop "rang tasks=${tasks:--}" "$3" "$input"
    play_ring
  fi
}

# The Stop's glyph: the turn token, then the state with the main session's token and any
# finished subagent's dropped. Args: pane, turn token, busy|idle, running subagent ids
# (comma-joined, or -).
stop_glyph() {
  local held id live=",$4,"
  glyph_cmd set-option -w -t "$1" @claude_turn "$2"
  glyph_drop "$1" main
  held=$(tmux show-option -wqv -t "$1" @claude_wait_by 2>/dev/null)
  while [[ $held =~ \!agent-([A-Za-z0-9_-]+)\! ]]; do
    id=${BASH_REMATCH[1]}
    held=${held//"!agent-$id!"/}
    [[ $live == *",$id,"* ]] || glyph_drop "$1" "agent-$id"
  done
  glyph_state "$1" "$3"
  glyph_flush
}

# Classify the reply, wait out the settle window meanwhile, then paint: wait on yes or error,
# busy when a queued input resumed, each only while the window holds this Stop's token. Args:
# transcript path, its size at the Stop, pane, turn token.
classify_then_paint() {
  local nap out verdict reason ms painted=- note=""
  sleep "${DOTCLAUDE_RING_SETTLE:-1}" &
  nap=$!
  out=$(printf '%s' "$input" | timeout 12 python3 -I "$here/wants_input.py" 2>/dev/null)
  read -r verdict reason ms <<< "$out"
  case "$verdict" in yes|no|error) ;; *) verdict=error reason=crash ms=- ;; esac
  wait "$nap"
  local mine="#{==:#{@claude_turn},$4}"
  if resumed "$1" "$2"; then
    glyph_cmd set-option -wF -t "$3" @claude_state \
      "#{?$mine,#{?#{@claude_wait_by},wait,busy},#{@claude_state}}"
    glyph_flush
    note=" resumed=1"
  elif [ "$verdict" != no ]; then
    glyph_cmd set-option -wF -t "$3" @claude_wait_by \
      "#{?$mine,#{s/!main!//:@claude_wait_by}!main!,#{@claude_wait_by}}"
    glyph_cmd set-option -wF -t "$3" @claude_state "#{?$mine,wait,#{@claude_state}}"
    glyph_flush
    # 1 when this Stop's token still held right after the paint, so the paint landed.
    [ "$(tmux show-option -wqv -t "$3" @claude_turn 2>/dev/null)" = "$4" ] && painted=1 || painted=0
  fi
  [ "${reason:--}" = - ] || note=" reason=$reason$note"
  ring_log stop "input=$verdict$note ms=${ms:--} painted=$painted" "$3" "$input"
}

pane=$(session_pane "$input")
if [ "${spawned:-0}" = 0 ] && [ -n "$pane" ]; then
  [ "${busy:-0}" = 1 ] && state=busy || state=idle
  now=${EPOCHREALTIME:-$(date +%s.%N)}
  token="${prompt:--}/${now//./}"
  [ "${prompt:--}" = - ] && token="none/${now//./}"
  stop_glyph "$pane" "$token" "$state" "${agents:--}"
  ( classify_then_paint "${transcript:-}" "${size:--}" "$pane" "$token" </dev/null >/dev/null 2>&1 & )
fi
if [ "${spawned:-0}" = 0 ] && [ "${busy:-0}" = 0 ] && session_in_view "$pane"; then
  ( settle_then_ring "${transcript:-}" "${size:--}" "$pane" </dev/null >/dev/null 2>&1 & )
elif [ "${busy:-0}" = 1 ]; then
  ring_log stop "quiet busy=1 tasks=${tasks:--}" "$pane" "$input"
else
  ring_log stop "quiet tasks=${tasks:--}" "$pane" "$input"
fi
exit 0
