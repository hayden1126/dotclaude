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
# So ATTENDED=0 means no tab and no sound. A background session attached to a tab is off-tab
# here too: one shared daemon hosts every background session, so its process ancestry reaches
# whichever client started the daemon, not the tab showing it. Mapping those by directory in
# tmux-claude-status is the planned fix (STATUS.md).

# Print the pane id this session is shown in, or nothing.
session_pane() {
  [ "${CLAUDE_CODE_SESSION_ATTENDED:-}" = 0 ] || printf '%s' "${TMUX_PANE:-}"
}

# True when a person sees this session: a tab or a plain terminal.
session_in_view() {
  [ "${CLAUDE_CODE_SESSION_ATTENDED:-}" != 0 ]
}

# Play the Windows notify sound, detached. A no-op where powershell.exe is missing.
play_ring() {
  ( powershell.exe -c "(New-Object Media.SoundPlayer 'C:\\Windows\\Media\\notify.wav').PlaySync()" \
      >/dev/null 2>&1 & )
}

# Append one ring decision to $XDG_STATE_HOME/dotclaude/ring.log, kept under 2,000 lines, so a
# ring from an unexpected session can be traced. Args: event, rang|quiet, pane.
ring_log() {
  local dir="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude" log sid="${CLAUDE_CODE_SESSION_ID:-}" kind
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
