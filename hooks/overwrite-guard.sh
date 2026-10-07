#!/usr/bin/env bash
# PreToolUse(Write) hook: denies a Write over an existing file this session has not read, or one
# that would cut a file of 1 KB or more to under a fifth of its size. The Write tool's own
# read-before-write check last fired in Claude Code 2.1.285. The rules and why are in
# hooks/overwrite_guard.py; tests/setup/test_overwrite_guard.py holds the cases.
#
# This shim passes the event on stdin to the module beside this script's real path, run by
# python3 -I. It FAILS OPEN: a missing python3 or module, or any error, allows the Write (errors
# and denies go to $XDG_STATE_HOME/dotclaude/overwrite-guard.log).
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/overwrite_guard.py" 2>/dev/null
exit 0
