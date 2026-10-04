#!/usr/bin/env bash
# UserPromptSubmit hook: when the user signals a session wrap-up / handoff / context reset, inject a
# reminder to INVOKE the `handoff` skill rather than improvising its steps. Advisory only: it adds
# context, it cannot run the skill. Silent otherwise; always exits 0, so it can never block a prompt.
#
# How it decides (classify() in hooks/handoff_reminder.py; tests/setup/test_handoff_reminder.py
# holds the cases):
#   1. Never on injected content (task notices, agent and cross-session messages), on a subagent's or
#      teammate's own prompt (agent_id), or when told not to use the skill.
#   2. Never on a clause that talks ABOUT handoff, the skill or this hook ("the handoff skill").
#   3. "handoff" / "hand off" fires as a command: it starts an action in an action list, the way it
#      is typed in practice ("emailed. handoff", "commit, handoff and push", "deploy handoff and
#      push", "do the handoff"). Not a question about it ("do we need to handoff?"), praise ("good
#      handoff"), a statement about it ("handoff doesn't work", "handoff complete"), a delegation
#      ("hand off the parser to Codex"), or a bare "handoff" labelling a topic ("handoff: does it
#      update memory?").
#   4. /clear in a terse message, unless advised against or asked about ("don't /clear yet").
#   5. A generic wrap-up phrase ("wrap up", "stop here", "call it a day", "clear the context") counts
#      only as a whole clause, with optional lead-ins ("ok let's"), a tail ("for today") or a next
#      wrap-up step ("and push"), or after "let's" / "time to" anywhere in a clause unless negated.
#      So "stop here, then explain why the test fails", "clear the session cache" and "don't wrap
#      up yet" stay silent. These phrases show up in technical text; "handoff" rarely does.
#   Rules 4 and 5 apply to messages of 18 words or fewer. In a longer one, only a handoff command
#   among its last clauses counts ("<a long status>. handoff, then push").
#
# This shim passes the event on stdin to hooks/handoff_reminder.py, found beside this script's real
# path (setup.sh symlinks only the .sh into ~/.claude/hooks), run by python3 -I (-I keeps a
# project's own json.py off sys.path). If python3 or the module fails, the hook stays silent:
# grepping the raw JSON payload instead misfired before.
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/handoff_reminder.py" 2>/dev/null || exit 0
