#!/usr/bin/env bash
# Sourced by tmux-state.sh, stop-ring.sh and notify.sh (not a hook itself): where a Claude
# session is shown, so its tmux state lands on the right window and only sessions a person sees
# ring. tests/setup/test_tmux_hooks.py holds the cases.
#
# - A tab: $TMUX_PANE.
# - A background session (CLAUDE_CODE_SESSION_KIND=bg) runs under `claude daemon`, whose env
#   has no TMUX_PANE. When it is attached to a tab, its ancestry still reaches that pane's shell
#   (session <- bg-pty-host <- daemon <- `claude --continue` <- the pane's shell), so walk up to
#   a pane pid. An unattached one reaches init: no pane.
# - A `claude -p` run (CLAUDE_CODE_SESSION_ATTENDED=0, probed on 2.1.289) inherits the tab's
#   TMUX_PANE from whatever started it, such as the delegation canary: no pane, never rings.

# Print the pane id this session is shown in, or nothing.
session_pane() {
  if [ "${CLAUDE_CODE_SESSION_KIND:-}" = bg ]; then
    _pane_by_ancestry
  elif [ "${CLAUDE_CODE_SESSION_ATTENDED:-}" != 0 ]; then
    printf '%s' "${TMUX_PANE:-}"
  fi
}

# True when a person sees this session: a tab, a plain terminal, or an attached background one.
session_in_view() {
  if [ "${CLAUDE_CODE_SESSION_KIND:-}" = bg ]; then
    [ -n "$(_pane_by_ancestry)" ]
  else
    [ "${CLAUDE_CODE_SESSION_ATTENDED:-}" != 0 ]
  fi
}

_pane_by_ancestry() {
  local panes cur=$PPID hit ppid _
  panes=$(tmux list-panes -a -F '#{pane_pid} #{pane_id}' 2>/dev/null) || return 0
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    hit=$(awk -v p="$cur" '$1 == p { print $2; exit }' <<<"$panes")
    if [ -n "$hit" ]; then printf '%s' "$hit"; return 0; fi
    # /proc/<pid>/stat is "pid (comm) state ppid ..."; comm may hold spaces or parens.
    ppid=$(awk '{ sub(/^.*\) /, ""); print $2 }' "/proc/$cur/stat" 2>/dev/null)
    case "$ppid" in ''|0|1) return 0 ;; esac
    cur=$ppid
  done
}

# Play the Windows notify sound, detached. A no-op where powershell.exe is missing.
play_ring() {
  ( powershell.exe -c "(New-Object Media.SoundPlayer 'C:\\Windows\\Media\\notify.wav').PlaySync()" \
      >/dev/null 2>&1 & )
}

# Append one ring decision to $XDG_STATE_HOME/dotclaude/ring.log, kept under 2,000 lines, so a
# ring from an unexpected session can be traced. Args: event, rang|quiet, pane.
ring_log() {
  local dir="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude" log sid="${CLAUDE_CODE_SESSION_ID:-}"
  log="$dir/ring.log"
  mkdir -p "$dir" 2>/dev/null || return 0
  printf '%s %s %s session=%s kind=%s attended=%s pane=%s dir=%s\n' \
    "$(date '+%F %T')" "$1" "$2" "${sid:0:8}" \
    "${CLAUDE_CODE_SESSION_KIND:-tab}" "${CLAUDE_CODE_SESSION_ATTENDED:--}" "${3:--}" \
    "$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")" >> "$log" 2>/dev/null
  if [ "$(wc -l < "$log" 2>/dev/null || echo 0)" -gt 2000 ]; then
    tail -n 1000 "$log" > "$log.tmp" 2>/dev/null && mv "$log.tmp" "$log" 2>/dev/null
  fi
  return 0
}
