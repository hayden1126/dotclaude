#!/usr/bin/env bash
# PreToolUse(Edit|Write|MultiEdit) hook for lanes (skills/lanes): denies a write to another
# lane's .lane/ record or to the CLI's data under <common-dir>/lanes/, and relative identity
# ("another session", "this session") in any lane record or in a lanes repo's root STATUS.md.
# A repo with no lanes is untouched. The rules are in hooks/lane_guard.py; tests/lanes holds the
# cases.
#
# This shim passes the event on stdin to the module beside this script's real path, run by
# python3 -I. It FAILS OPEN: a missing python3 or module, or any error, allows the call (errors
# and denies go to $XDG_STATE_HOME/dotclaude/lane-guard.log).
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/lane_guard.py" 2>/dev/null
exit 0
