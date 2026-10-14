#!/usr/bin/env bash
# UserPromptSubmit and PostToolUse hook: tells a session, once, that pass-respawn's waiter
# dropped the /pass it queued. The waiter writes $XDG_STATE_HOME/dotclaude/pass-notice/
# <session>.json at every drop; the session's next turn start (a prompt, an agent's hand-back,
# a task notice) or main-thread tool call claims it and gives its text to the model as
# additionalContext. settings.json skips a subagent's tool call before this runs.
# hooks/pass_notice.py, beside this script's real path and run with python3 -I, has the rules;
# tests/setup/test_pass_notice.py holds the cases.
# Python starts only for a notice this event could claim. With no *.json in pass-notice/,
# nearly every event, the shim exits at once. Otherwise it reads the session id from the
# payload's first "session_id" key (Claude Code writes it first; a tool's own session_id key or
# a prompt quoting one comes later) and exits unless that session's notice is there. A notice
# no event will claim (a `gone` after /clear) waits for pass-respawn's prune, so without this
# every session would start Python on every prompt and tool call meanwhile. When no plain id is
# found (a JSON escape, no key), Python decides: it parses the payload for real.
# Fail-open: always exits 0, and anything that goes wrong says nothing to the session; Python's
# errors go to $XDG_STATE_HOME/dotclaude/pass-notice.err.
set -uo pipefail

input=$(cat)
state="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude"
shopt -s nullglob
set -- "$state"/pass-notice/*.json
[ $# -gt 0 ] || exit 0
# The first session_id key with a string value; the id must then be a plain name as a whole,
# so an escaped value sends the event to Python instead of to a later key.
key='"session_id"[[:space:]]*:[[:space:]]*"([^"]*)"'
plain='^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
if [[ $input =~ $key ]]; then
  sid=${BASH_REMATCH[1]}
  if [[ $sid =~ $plain ]]; then
    notice="$state/pass-notice/$sid.json"
    [ -e "$notice" ] || [ -L "$notice" ] || exit 0  # a symlink goes on, to be deleted unread
  fi
fi
src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
printf '%s' "$input" | python3 -I "${src%/*}/pass_notice.py" 2>>"$state/pass-notice.err"
exit 0
