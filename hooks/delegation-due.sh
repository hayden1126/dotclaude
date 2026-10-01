#!/usr/bin/env bash
# SessionStart hook: say which delegation checks are due, and start the cheap ones in the
# background (the quick canary on a new Claude Code version, the daily audit). The logic lives
# in skills/delegation/scripts/delegation_checks.py. Fails open: it always exits 0, and it
# prints nothing unless something needs Hayden.
python3 "$HOME/.claude/skills/delegation/scripts/delegation-ledger" due --hook 2>/dev/null
exit 0
