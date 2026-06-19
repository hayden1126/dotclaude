#!/usr/bin/env bash
# Notification(permission_prompt) hook. Pops a Windows toast showing the prompt
# message, on BOTH native Windows (git-bash/MSYS) and WSL.
#
# settings.json invokes this as `bash "$HOME/.claude/hooks/notify.sh"`, so the
# command in settings stays platform-agnostic and all OS detection lives here.
# That also keeps settings.json byte-identical across machines, so setup.sh can
# copy it without re-stomping a hand-tuned, per-platform notify command.
#
# The event JSON arrives on stdin: {"message": "..."}. Fail-open: any error just
# skips the toast (exit 0) and never blocks the session.

set -uo pipefail

input=$(cat 2>/dev/null)

# Message: prefer python3, fall back to python. Either way, default if absent.
py=$(command -v python3 || command -v python || true)
msg=""
if [[ -n "$py" ]]; then
  msg=$(printf '%s' "$input" | "$py" -c \
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

( powershell.exe -ExecutionPolicy Bypass -File "$winpath" -Message "$msg" >/dev/null 2>&1 & )
exit 0
