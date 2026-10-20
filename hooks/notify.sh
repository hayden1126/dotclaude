#!/usr/bin/env bash
# Notification(permission_prompt) hook. Pops a Windows toast showing the prompt
# message, on BOTH native Windows (git-bash/MSYS) and WSL, and rings the notify sound when a
# person sees the session (session-pane.sh: a tab, a plain terminal, or a background session
# mapped to its tab). An unmapped background session blocked on a prompt gets the toast only.
#
# The device-wide mute (session-pane.sh's read_mute, hooks/mute_state.py) is read once, before
# the ring: a sound mute drops the ring (`permission quiet muted=1` in ring.log) and shows the
# toast with -Silent, so Windows' own toast chime stays off too (` toast=silent`); a toast mute
# skips the toast (` toast=muted`). A flag that can't be read mutes nothing and adds its
# ` mute=<why>`. Without session-pane.sh the toast shows as it always did.
#
# settings.json invokes this as `bash "$HOME/.claude/hooks/notify.sh"`, so the
# command in settings stays platform-agnostic and all OS detection lives here.
# That also keeps the settings.json baseline the same on every machine, so setup.sh
# can install it without re-stomping a hand-tuned, per-platform notify command.
#
# The event JSON arrives on stdin: {"message": "..."}. Fail-open: any error just
# skips the toast (exit 0) and never blocks the session.

set -uo pipefail

input=$(cat 2>/dev/null)
mute_sound=0 mute_toast=0

if . "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/session-pane.sh" 2>/dev/null; then
  pane=$(session_pane "$input")
  read_mute
  toast_note=""
  if [ "$mute_toast" = 1 ]; then toast_note=" toast=muted"
  elif [ "$mute_sound" = 1 ]; then toast_note=" toast=silent"; fi
  if ! session_in_view "$pane"; then
    ring_log permission "quiet$toast_note$mute_note" "$pane" "$input"
  elif [ "$mute_sound" = 1 ]; then
    ring_log permission "quiet muted=1$toast_note$mute_note" "$pane" "$input"
  else
    play_ring
    ring_log permission "rang$toast_note$mute_note" "$pane" "$input"
  fi
fi
[ "$mute_toast" = 1 ] && exit 0

# Message: prefer python3, fall back to python. Either way, default if absent.
py=$(command -v python3 || command -v python || true)
msg=""
if [[ -n "$py" ]]; then
  msg=$(printf '%s' "$input" | "$py" -I -c \
    'import sys,json; print(json.load(sys.stdin).get("message","Input needed"))' 2>/dev/null)
fi
[[ -z "$msg" ]] && msg="Input needed"

# Resolve notify-toast.ps1 to a Windows path powershell.exe understands.
# WSL ships wslpath; MSYS2/git-bash/Cygwin ship cygpath. No path tool => no
# Windows toast is possible anyway, so skip cleanly (fail-open).
ps1="$HOME/.claude/notify-toast.ps1"
if command -v wslpath >/dev/null 2>&1; then
  winpath=$(wslpath -w "$ps1")
elif command -v cygpath >/dev/null 2>&1; then
  winpath=$(cygpath -w "$ps1")
else
  exit 0
fi

silent=()
[ "$mute_sound" = 1 ] && silent=(-Silent)
( powershell.exe -ExecutionPolicy Bypass -File "$winpath" ${silent[@]+"${silent[@]}"} \
    -Message "$msg" >/dev/null 2>&1 & )
exit 0
