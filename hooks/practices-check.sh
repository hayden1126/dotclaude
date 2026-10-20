#!/usr/bin/env bash
# PreToolUse(Edit|Write|MultiEdit), PreToolUse(Bash), PostToolUse(Bash) and SessionStart hook:
# the practices engine. It denies an edit once until the skill that owns its event is loaded
# (L1), denies once per file on a high-precision bad pattern (L2), tells the model after a
# commit what it added that a rule flags (L3s), denies a push once per new finding in what it
# would send, denies a PR's ready once until a reviewer ran with the gate lines (L3r), and after
# a compaction restates the loaded skills' must-hold lines (L4). settings.json starts it for a
# Bash call only behind a prefilter (git commit or push, gh pr ready or create). Each skill's
# events.toml holds its triggers; the rules and why are in hooks/practices_check.py, and
# tests/setup/test_practices_check.py holds the cases.
#
# This shim passes the event on stdin to the module beside this script's real path, run by
# python3 -I. It FAILS OPEN but loud: any error allows the call and is logged to
# $XDG_STATE_HOME/dotclaude/practices/errors.log, which the next session start reports. When
# python3 itself can't run the module (missing, or a syntax error), the shim tells the user so on
# every call.
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/practices_check.py" 2>/dev/null
rc=$?
if [ "$rc" -ne 0 ]; then
  printf '{"systemMessage":"practices hooks are down: python3 exited %s running practices_check.py; edits, commits, pushes and PRs are not checked"}\n' "$rc"
fi
exit 0
