#!/usr/bin/env bash
# PreToolUse(Agent) hook: enforce delegation-role spawn rules (today: a writer must pass
# isolation on the call). The logic lives in skills/delegation/scripts/agent-spawn-guard.
# FAILS CLOSED: if the guard cannot run (missing link, no python3), exit 2 blocks the spawn
# with the reason on stderr, which Claude sees. Fix the install; do not delete the hook.
guard="$HOME/.claude/skills/delegation/scripts/agent-spawn-guard"
python3 "$guard" || {
  echo "agent-spawn-guard could not run ($guard): Agent spawns are blocked until it is fixed" >&2
  exit 2
}
