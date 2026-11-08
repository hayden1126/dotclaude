#!/usr/bin/env bash
# PreToolUse(Bash) hook: denies a heavy gate once until the long-runs skill is loaded. The rules
# and why are in hooks/long_runs_check.py; tests/setup/test_long_runs_check.py holds the cases.
# A Bash call reaches it only through settings.json's prefilter.
#
# This shim passes the event on stdin to the module beside this script's real path, run by
# python3 -I. It FAILS OPEN but loud: when python3 can't run the module, it says so on every call.
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/long_runs_check.py" 2>/dev/null
rc=$?
if [ "$rc" -ne 0 ]; then
  printf '{"systemMessage":"long-runs check is down: python3 exited %s running long_runs_check.py; heavy gates are not checked"}\n' "$rc"
fi
exit 0
