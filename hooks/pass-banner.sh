#!/usr/bin/env bash
# SessionStart hook: after a plain /pass respawned this tab, show everything the old session said
# since your last prompt, once, as a banner. stop-ring.sh keeps the session's `replies` (each
# Stop's last_assistant_message with its prompt_id) in the stop record, and pass-respawn copies
# them to $XDG_STATE_HOME/dotclaude/pass-last/<pane number>.json with the tab. This hook shows the
# replies that share the newest one's prompt_id (a Stop a hook blocked and the Stop ending the
# continued turn share one) as a `systemMessage`, which Hayden sees and the model doesn't (spike
# A2), under "Since your last prompt:" ("Last reply before the pass:" for just one), when:
#   - the source is `startup` (a respawn starts that way), in a tmux tab (TMUX_PANE), not a
#     `claude -p` run (CLAUDE_CODE_SESSION_ATTENDED=0) and not a subagent (agent_id);
#   - the entry's tab matches this pane on this tmux server exactly (keyed as session-registry.sh
#     and claude-saved key it), it was written under 120 s ago, and `shown` is false.
# It then sets `shown` (an atomic rewrite). The file stays: Ctrl-b P (tmux/pass-last) reopens all
# the replies any time. The banner stops at 40 lines or 4 KiB, head and tail included, and then
# says how many lines are left.
#
# This shim runs hooks/pass_banner.py, found beside this script's real path, with python3 -I.
# tests/setup/test_pass_banner.py holds the cases. Fail-open: always exits 0.
set -uo pipefail

[ "${CLAUDE_CODE_SESSION_ATTENDED:-}" != 0 ] || exit 0
[ -n "${TMUX_PANE:-}" ] || exit 0
src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/pass_banner.py" 2>/dev/null
exit 0
