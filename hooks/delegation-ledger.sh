#!/usr/bin/env bash
# SubagentStart/SubagentStop hook: append a pointer row to the delegation ledger
# (skills/delegation/scripts/delegation-ledger). An observer: always exits 0 and prints
# nothing, so it can never block or alter an agent. Errors land in
# ${XDG_STATE_HOME:-~/.local/state}/dotclaude/delegation-ledger.err.
python3 "$HOME/.claude/skills/delegation/scripts/delegation-ledger" hook 2>/dev/null
exit 0
