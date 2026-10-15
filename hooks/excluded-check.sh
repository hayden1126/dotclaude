#!/usr/bin/env bash
# SessionStart(startup|resume|clear) hook: the excluded-command guard's check of this session's
# project and PATH, so a missing Edit deny rule shows when the session starts, not when a push
# gets refused. It shows once per change in its findings, on screen and in the model's context.
# The rules are in hooks/excluded_guard.py (--session); tests/setup/test_excluded_guard.py holds
# the cases.
#
# This shim passes the event on stdin to the module beside this script's real path, run by
# python3 -I. It FAILS OPEN: a missing python3 or module, or any error, prints nothing (errors go
# to $XDG_STATE_HOME/dotclaude/excluded-guard.log). excluded-guard.sh still judges every call.
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/excluded_guard.py" --session 2>/dev/null
exit 0
