#!/usr/bin/env bash
# SessionStart hook: after a plain /pass respawned this tab, show what the old session said in its
# last turn, once, as a banner. stop-ring.sh keeps the session's `replies` (each
# Stop's last_assistant_message with its prompt_id) in the stop record, and pass-respawn copies
# them to $XDG_STATE_HOME/dotclaude/pass-last/<pane number>.json with the tab. This hook shows the
# last turn, the run of replies at the end that share the newest one's prompt_id (a Stop a hook
# blocked and the Stop ending the continued turn share one; a turn a background-task notice
# started has its own, so a turn isn't always Hayden's prompt), as a `systemMessage`, which
# Hayden sees and the model doesn't (spike A2). It starts "Last turn (HH:MM)", then "You:" with
# the first line of the turn's prompt (the entry's `prompts`, which pass-respawn reads from the
# transcript; about 100 characters, then an ellipsis), or a dim "(no prompt: a background
# notice)" when a notice started the turn, "(prompt not saved)" when pass-respawn couldn't tell,
# then the replies rendered from markdown by md_render.py (bold, code, lists, tables, code
# blocks) at the pane's width less Claude Code's 5-column indent, each style closed by its own
# reset and a color by going back to the banner's gray (spike A9: 0m or 39m would drop it). It
# shows when:
#   - the source is `startup` (a respawn starts that way), in a tmux tab (TMUX_PANE), not a
#     `claude -p` run (CLAUDE_CODE_SESSION_ATTENDED=0) and not a subagent (agent_id);
#   - the entry's tab matches this pane on this tmux server exactly (keyed as session-registry.sh
#     and claude-saved key it), it was written under 120 s ago, and `shown` is false.
# It then sets `shown` (an atomic rewrite). The file stays: Ctrl-b Up (tmux/pass-last) reopens all
# the replies of the last 5 turns any time. The banner holds at most 40 lines of reply and 4 KiB
# in all (its head, its tail and the escapes count toward the 4 KiB); past either, it says how
# many lines are left and where to read them: Ctrl-b Up once setup-tmux.sh installed it, else the
# pass-last file. A cut never splits an escape or leaves a style open.
#
# This shim runs hooks/pass_banner.py, found beside this script's real path, with python3 -I; it
# loads md_render.py from beside its own real path, and without it shows the plain text.
# tests/setup/test_pass_banner.py holds the cases. Fail-open: always exits 0.
set -uo pipefail

[ "${CLAUDE_CODE_SESSION_ATTENDED:-}" != 0 ] || exit 0
[ -n "${TMUX_PANE:-}" ] || exit 0
src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/pass_banner.py" 2>/dev/null
exit 0
