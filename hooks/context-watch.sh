#!/usr/bin/env bash
# Stop and PostToolUse hook: the autopass context watcher. It reads the session's context size
# from the transcript, writes it to $XDG_STATE_HOME/dotclaude/ctx/<session>.json, and at three
# token tiers (soft 300k, wrap-up 480k, hard 520k, derived from autoCompactWindow) tells the
# model to wrap up and run the pass skill before auto-compact (about 567k). With autopass on
# (/autopass, a lane, or pass.toml) a tier blocks the Stop or adds context to a tool result;
# with it off, only the hard tier shows Hayden one line, once. hooks/context_watch.py, beside
# this script's real path and run with python3 -I, has the rules; tests/setup/
# test_context_watch.py holds the cases. Quiet for a `claude -p` run and a subagent.
# Fail-open: always exits 0, and anything that goes wrong says nothing.
set -uo pipefail

[ "${CLAUDE_CODE_SESSION_ATTENDED:-}" != 0 ] || exit 0
src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/context_watch.py" 2>/dev/null
exit 0
