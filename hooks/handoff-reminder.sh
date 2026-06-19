#!/usr/bin/env bash
# UserPromptSubmit hook: when the user signals a session wrap-up / handoff / context reset, inject a
# reminder to INVOKE the `handoff` skill rather than improvising its steps (which has repeatedly caused
# steps of the skill's procedure to be silently skipped). Advisory only: it adds context, it cannot run
# the skill. Silent no-op on any non-matching prompt. Always exits 0 so it can never block a prompt.
# Fail-open if jq is absent (greps the raw payload). Needs nothing beyond grep; jq is optional.
set -uo pipefail

payload="$(cat)"
prompt="$(printf '%s' "$payload" | jq -r '.prompt // empty' 2>/dev/null || true)"
[ -z "$prompt" ] && prompt="$payload"

if printf '%s' "$prompt" | grep -iqE 'hand[ -]?off|wrap(ping)?[ -]?up|(stop|stopping) here|let'\''?s stop|call it (here|for the day|a day)|end of (the )?session|that'\''?s a wrap|clear(ing)? (memory|context|the (conversation|session|chat))|ready to clear|before (we|i) clear|fresh session|new session|start(ing)? fresh|wipe (the )?(context|memory)|/clear'; then
  cat <<'MSG'
[handoff-reminder] This looks like a session wrap-up / handoff / context reset. Before responding,
invoke the `handoff` skill (Skill tool, name "handoff") and run its FULL procedure rather than
improvising or cherry-picking steps. Improvising tends to silently drop steps (commonly the doc-drift
reconciliation and the memory curation, but run them all). If this is genuinely trivial with nothing
durable to carry, the skill itself says skip it, but make that an explicit judgment, not an omission.
MSG
fi
exit 0
