#!/usr/bin/env bash
# SessionStart(startup|resume|clear|compact) hook: keeps Bash off the display in a repo that opts
# in with `git config dotclaude.blankDisplay true` (read with --local, so every worktree of the
# repo is covered). Opted in, it appends `export DISPLAY=`, `export WAYLAND_DISPLAY=` and
# `unset WAYLAND_SOCKET` to $CLAUDE_ENV_FILE and tells the model why; anywhere else it is silent.
# The rules are in hooks/blank_display.py; tests/setup/test_blank_display.py holds the cases.
#
# This shim passes the event on stdin to the module beside this script's real path, run by
# python3 -I. It FAILS OPEN: a missing python3 or module, or any error, prints nothing (errors go
# to $XDG_STATE_HOME/dotclaude/blank-display.log).
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/blank_display.py" 2>/dev/null
exit 0
