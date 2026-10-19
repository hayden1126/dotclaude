#!/usr/bin/env bash
# PreToolUse(AskUserQuestion) hook: denies a risky ask once, before the dialog, with a checklist
# as the reason; the model fixes what applies and resends, and the resend passes. The rules and
# why are in hooks/ask_check.py; tests/setup/test_ask_check.py holds the cases.
#
# This shim passes the event on stdin to the module beside this script's real path, run by
# python3 -I. It FAILS OPEN: a missing python3 or module, or any error, allows the ask (errors
# and denies go to $XDG_STATE_HOME/dotclaude/ask-check.log).
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/ask_check.py" 2>/dev/null
exit 0
