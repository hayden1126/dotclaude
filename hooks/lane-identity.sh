#!/usr/bin/env bash
# SessionStart(startup|resume|clear|compact), Stop and SessionEnd hook for lanes (skills/lanes).
# In a lane it tells the session its absolute identity (lane id, the branch or commit its
# worktree has checked out, claims, port, record) and registers the session in lane.json; on
# Stop and SessionEnd it mirrors <lane>/.lane/ into the common dir. In the main checkout of a
# lanes repo it prints a one-line board, and on SessionStart and Stop it heals the lead record:
# when this session provably continues the recorded lead (a resume, a /clear or a /pass
# successor), it runs `lane lead`, which rewrites the record. Silent in a repo with no lanes.
# The rules are in hooks/lane_identity.py; tests/lanes holds the cases.
#
# This shim passes the event on stdin to the module beside this script's real path, run by
# python3 -I. It FAILS OPEN: a missing python3 or module, or any error, prints nothing (errors go
# to $XDG_STATE_HOME/dotclaude/lane-identity.log).
set -uo pipefail

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || exit 0
python3 -I "${src%/*}/lane_identity.py" 2>/dev/null
exit 0
