#!/usr/bin/env bash
# UserPromptSubmit hook: when the user signals a genuine session wrap-up / handoff / context reset,
# inject a reminder to INVOKE the `handoff` skill rather than improvising its steps. Advisory only:
# it adds context, it cannot run the skill. Silent no-op on anything else; always exits 0 so it can
# never block a prompt. jq optional (falls back to grepping the raw payload).
#
# Precision-first (this hook was over-firing on the word "handoff" used as a TOPIC). It fires only on
# a clear wrap-up COMMAND, never on discussion of handoff / the skill / this hook, and never on
# injected system content.
set -uo pipefail

payload="$(cat)"
prompt="$(printf '%s' "$payload" | jq -r '.prompt // empty' 2>/dev/null || true)"
[ -z "$prompt" ] && prompt="$payload"

emit() {
  cat <<'MSG'
[handoff-reminder] This looks like a session wrap-up / handoff / context reset. Before responding,
invoke the `handoff` skill (Skill tool, name "handoff") and run its FULL procedure rather than
improvising or cherry-picking steps. Improvising tends to silently drop steps (commonly the doc-drift
reconciliation and the memory curation, but run them all). If this is genuinely trivial with nothing
durable to carry, the skill itself says skip it, but make that an explicit judgment, not an omission.
MSG
}

# 1. Never fire on injected / non-user content (task notifications, system reminders, hook echoes,
#    slash-command stdout). These are not the user asking to wrap up.
if printf '%s' "$prompt" | grep -qiE '\[SYSTEM NOTIFICATION|NOT USER INPUT|<task-notification|<system-reminder|</system-reminder|automated background-task|hook success|<command-name>|<command-message>|<local-command'; then
  exit 0
fi

# 2. Never fire when the user is talking ABOUT handoff (as a topic/noun) or about the skill/hook,
#    rather than asking to hand off. Catches: "the/this/that handoff", "handoff <noun>" (skill, hook,
#    issue, problem, ...), "the skill/hook/reminder", "false positive", "the hook fires/regex", etc.
if printf '%s' "$prompt" | grep -qiE 'handoff[ -]?reminder|handoff\.sh|false[ -]?positive|\b(the|this|that|its|our|your) hand[ -]?off\b|hand[ -]?off (skill|hook|procedure|process|step|doc|rule|reminder|trigger|logic|mechanism|issue|problem|thing|bug|stuff|situation|behaviou?r|feature|note|change|fix|word|part|regex|line|matcher)|\b(the|this|that|a|an) (skill|hook|reminder)\b|(skill|hook|reminder) (is|was|fires|fired|triggers|triggered|matched|regex)'; then
  exit 0
fi

# 3. Explicit context-reset command: fire regardless of length.
if printf '%s' "$prompt" | grep -qiE '(^|[[:space:]])/clear([[:space:]]|$)'; then
  emit; exit 0
fi

# 4. Otherwise fire only on a terse, intent-bearing message. Wrap-up phrases, plus "hand off" only in
#    COMMAND form (imperative), never the bare topic word. Long messages are discussion, not a command.
words="$(printf '%s' "$prompt" | wc -w | tr -d '[:space:]')"
[ "${words:-999}" -gt 18 ] && exit 0
if printf '%s' "$prompt" | grep -qiE "(let'?s |lets |time to |ok,? |okay,? |please |i'?ll |we can |can we |now,? |ready to |about to )?(wrap(ping)? (this |it )?up|wrap up|call it (a day|for the day|for the night|here|quits)|stop(ping)? here|stop for (the day|now|today)|end (of )?(the |this )?session|that'?s a wrap|wipe (the )?(context|memory)|clear (the )?(memory|context|session|chat|conversation))|(let'?s |lets |ok,? |okay,? |now,? |please |time to |ready to |we can |i'?ll )hand[ -]?off|^hand[ -]off\b|hand[ -]?off( now| here| please| for real)\b|hand (it|this|things) off|do a hand[ -]?off|hand[ -]?off time"; then
  emit; exit 0
fi

exit 0
