#!/usr/bin/env bash
# Sourced by tmux-state.sh, stop-ring.sh and notify.sh (not a hook itself): where a Claude
# session is shown, so its tmux state lands on the right window and only sessions a person sees
# ring. tests/setup/test_tmux_hooks.py holds the cases.
#
# What a hook's env says (probed on 2.1.289):
#   a tab                    CLAUDE_CODE_SESSION_ATTENDED=1, its own TMUX_PANE
#   a `claude -p` run        ATTENDED=0, and the TMUX_PANE of whatever started it (the
#                            delegation canary starts one from a tab)
#   a background session     ATTENDED=0, CLAUDE_JOB_DIR set, no TMUX_PANE (`claude daemon` hosts
#                            it; CLAUDE_CODE_SESSION_KIND=bg is in its process env, not the hook's)
# So ATTENDED=0 means no tab and no sound, with one exception. A background session's process
# ancestry can't find its tab (one shared daemon hosts them all, so it reaches whichever client
# started the daemon), so tmux/tmux-claude-status maps it by directory instead: the one client
# pane in the session's cwd. It writes $XDG_STATE_HOME/dotclaude/tabs ("<session id> <pane>
# <window>" lines after a "server <pid>" line), and a background session found there counts as
# that tab. The lookup keys on the event's session_id, not the env: a `claude -p` run from a
# background session's Bash inherits its CLAUDE_JOB_DIR (it's in the process env) and may inherit
# its CLAUDE_CODE_SESSION_ID, but its events carry its own id. A map older than 90 s is ignored:
# the script rewrites it at least every 60 s while tmux is attached and background sessions run,
# so an old one means nobody is looking (tmux exited or detached). The hooks don't check the
# map's server line (that would cost a tmux call per hook), so after a tmux restart inside those
# 90 s an old pane id can name the wrong tab until the script's first run remaps.

# Print the event's session_id. Arg: the hook's event JSON. The top-level key comes first; an
# escaped one inside a string value (\"session_id\") can't match.
event_session_id() {
  local re='"session_id" *: *"([^"]+)"'
  [[ "${1:-}" =~ $re ]] && printf '%s' "${BASH_REMATCH[1]}"
}

# Print the pane id this session is shown in, or nothing. Arg: the hook's event JSON.
session_pane() {
  if [ "${CLAUDE_CODE_SESSION_ATTENDED:-}" != 0 ]; then
    printf '%s' "${TMUX_PANE:-}"
    return
  fi
  [ -n "${CLAUDE_JOB_DIR:-}" ] || return 0
  local tabs="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude/tabs" event_sid sid pane age
  event_sid=$(event_session_id "${1:-}")
  [ -n "$event_sid" ] || return 0
  age=$(( $(date +%s) - $(stat -c %Y "$tabs" 2>/dev/null || echo 0) ))
  [ "$age" -lt 90 ] || return 0
  { while read -r sid pane _; do
      if [ "$sid" = "$event_sid" ] && [ -n "$pane" ]; then
        printf '%s' "$pane"
        return
      fi
    done < "$tabs"; } 2>/dev/null
}

# True when a person sees this session: a tab, a plain terminal, or a mapped background session.
# Arg: the pane session_pane printed.
session_in_view() {
  [ "${CLAUDE_CODE_SESSION_ATTENDED:-}" != 0 ] || [ -n "${1:-}" ]
}

# Play the Windows notify sound, detached. A no-op where powershell.exe is missing.
play_ring() {
  ( powershell.exe -c "(New-Object Media.SoundPlayer 'C:\\Windows\\Media\\notify.wav').PlaySync()" \
      >/dev/null 2>&1 & )
}

# Append one ring decision to $XDG_STATE_HOME/dotclaude/ring.log, kept under 2,000 lines, so a
# ring from an unexpected session can be traced. Args: event, status (rang|quiet; stop-ring.sh
# adds `busy=1` or `resumed=1` (a queued input restarted the turn) and `tasks=<labels>`:
# comma-joined, spaces as `_`, `-` for none), pane, event
# JSON. The id is the event's (a nested `claude -p` may inherit its parent's CLAUDE_CODE_SESSION_ID).
ring_log() {
  local dir="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude" log sid kind
  sid=$(event_session_id "${4:-}")
  sid="${sid:-${CLAUDE_CODE_SESSION_ID:-}}"
  log="$dir/ring.log"
  if [ -n "${CLAUDE_JOB_DIR:-}" ]; then kind=background
  elif [ "${CLAUDE_CODE_SESSION_ATTENDED:-}" = 0 ]; then kind=print
  else kind=tab; fi
  mkdir -p "$dir" 2>/dev/null || return 0
  printf '%s %s %s session=%s kind=%s attended=%s pane=%s dir=%s\n' \
    "$(date '+%F %T')" "$1" "$2" "${sid:0:8}" "$kind" "${CLAUDE_CODE_SESSION_ATTENDED:--}" \
    "${3:--}" "$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")" >> "$log" 2>/dev/null
  if [ "$(wc -l < "$log" 2>/dev/null || echo 0)" -gt 2000 ]; then
    tail -n 1000 "$log" > "$log.tmp" 2>/dev/null && mv "$log.tmp" "$log" 2>/dev/null
  fi
  return 0
}
