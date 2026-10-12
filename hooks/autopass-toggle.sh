#!/usr/bin/env bash
# UserPromptSubmit hook: answer `/autopass on|off|status` here, so a toggle costs no model turn.
# It blocks only that prompt (decision: block, with a one- or two-line reason Hayden sees) and
# lets every other prompt through. on/off set the flag for this tmux tab; status prints the
# context size, the next tier, on or off, and which level set it. skills/autopass/SKILL.md
# defines the command, since Claude Code never hands an undefined one to the hook (spike A1).
# hooks/autopass_toggle.py, beside this script's real path and run with python3 -I, has the
# rules. Fail-open: always exits 0; a failure lets the prompt through to that skill, whose body
# says the hook isn't installed.
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/autopass_toggle.py" 2>/dev/null
exit 0
