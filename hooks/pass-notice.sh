#!/usr/bin/env bash
# UserPromptSubmit and PostToolUse hook: tells a session, once, that pass-respawn's waiter
# dropped the /pass it queued. The waiter writes $XDG_STATE_HOME/dotclaude/pass-notice/
# <session>.json at every drop; the session's next turn start (a prompt, an agent's hand-back,
# a task notice) or main-thread tool call claims it and gives its text to the model as
# additionalContext. settings.json skips a subagent's tool call before this runs.
# hooks/pass_notice.py, beside this script's real path and run with python3 -I, has the rules;
# tests/setup/test_pass_notice.py holds the cases. With no *.json in pass-notice/, nearly
# every event, it exits before starting Python. Fail-open: always exits 0, and anything that
# goes wrong says nothing to the session; Python's errors go to
# $XDG_STATE_HOME/dotclaude/pass-notice.err.
set -uo pipefail

state="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude"
shopt -s nullglob
set -- "$state"/pass-notice/*.json
if [ $# -eq 0 ]; then
  cat >/dev/null  # take the event anyway, so Claude Code's write never meets a closed pipe
  exit 0
fi
src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/pass_notice.py" 2>>"$state/pass-notice.err"
exit 0
