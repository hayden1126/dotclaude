#!/usr/bin/env bash
# PreToolUse(Bash) hook: for a command run with dangerouslyDisableSandbox only, denies a delete
# (rm, rmdir, shred, unlink, find -delete) whose path uses a variable the command didn't set, a
# command substitution that would widen it if empty, or a top-level or home tree, or that is
# relative after a cd into one of those. Outside the sandbox $TMPDIR is plain /tmp,
# which once aimed an `rm -rf "$TMPDIR"/...` at shared /tmp. The rules and why are in
# hooks/delete_guard.py; tests/setup/test_delete_guard.py holds the cases.
#
# This shim passes the event on stdin to the module beside this script's real path, run by
# python3 -I. It FAILS OPEN: a missing python3 or module, or any error, allows the command
# (errors and denies go to $XDG_STATE_HOME/dotclaude/delete-guard.log).
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/delete_guard.py" 2>/dev/null
exit 0
