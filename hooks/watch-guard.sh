#!/usr/bin/env bash
# Stop hook, main thread only: the watch guard (skills/delegation/scripts/watch-guard). It
# blocks a turn's end once when a long wait has lapsed, a watched job ended unnoticed, or a
# background command was killed at its time limit, printing the block as JSON. The script
# itself skips a subagent's stop (a top-level agent_id); a substring test here would also skip
# a main-thread stop whose background_tasks hold a teammate. It FAILS OPEN: it always exits 0.
# Python's stderr (a missing skill link, an import error, a traceback) is appended to
# ${XDG_STATE_HOME:-~/.local/state}/dotclaude/delegation-ledger.err, so a broken install shows
# there and in the quick canary instead of leaving the guard silently off. When that file can't
# be written, stderr goes to /dev/null, since a failed redirect would skip the guard itself.
d="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude"
err="$d/delegation-ledger.err"
{ mkdir -p "$d" && : >>"$err"; } 2>/dev/null || err=/dev/null
python3 "$HOME/.claude/skills/delegation/scripts/watch-guard" 2>>"$err"
exit 0
