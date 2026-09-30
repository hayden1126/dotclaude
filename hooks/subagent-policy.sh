#!/usr/bin/env bash
# PreToolUse(*) hook for delegated agents: the subagent policy
# (skills/delegation/scripts/subagent-policy, tables in skills/delegation/policy.toml).
# The settings entry has already skipped main-thread calls (their input has no "agent_id"),
# and it wraps this in `timeout 8 ... || exit 2`, so a missing link, a crash or a hang blocks
# the delegated call instead of letting it through. FAILS CLOSED: fix the install; do not
# delete the hook.
policy="$HOME/.claude/skills/delegation/scripts/subagent-policy"
python3 "$policy" || {
  echo "subagent-policy could not run ($policy): delegated tool calls are blocked until it is fixed" >&2
  exit 2
}
