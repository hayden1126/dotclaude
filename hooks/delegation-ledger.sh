#!/usr/bin/env bash
# SubagentStart/SubagentStop hook: append a pointer row to the delegation ledger
# (skills/delegation/scripts/delegation-ledger). PostToolUse: the deadline nudge, the only
# output it ever prints. Always exits 0, so it can never block an agent. Errors land in
# ${XDG_STATE_HOME:-~/.local/state}/dotclaude/delegation-ledger.err.
python3 "$HOME/.claude/skills/delegation/scripts/delegation-ledger" hook 2>/dev/null
exit 0
