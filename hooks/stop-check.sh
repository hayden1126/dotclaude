#!/usr/bin/env bash
# Stop hook, lane sessions only: the stop check. It blocks a lane turn's end once when the turn
# ends with nothing to wait on (no Waiting on you list, no message to the lead or a lane, no
# background job, no pass) and Hayden didn't start it. hooks/stop_check.py, beside this script's
# real path and run with python3 -I, has the rules; tests/setup/test_stop_check.py holds the
# cases. Fail-open: always exits 0. Python's errors go to
# $XDG_STATE_HOME/dotclaude/stop-check.err; each block is a line in stop-check.log.
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
err="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude/stop-check.err"
mkdir -p "${err%/*}" 2>/dev/null  # else the redirect fails and Python never runs
python3 -I "${src%/*}/stop_check.py" 2>>"$err"
exit 0
