#!/usr/bin/env bash
# UserPromptSubmit hook: when the user signals a genuine session wrap-up / handoff / context reset,
# inject a reminder to INVOKE the `handoff` skill rather than improvising its steps. Advisory only:
# it adds context, it cannot run the skill. Silent no-op on anything else; always exits 0 so it can
# never block a prompt. Reads the prompt with python3 (every hook here needs it; jq isn't on every
# machine). If that fails it stays silent: grepping the raw JSON payload instead misfired on " /clear "
# inside a report and never matched a bare "/clear", which sits between quotes there.
#
# Precision-first (this hook was over-firing on the word "handoff" used as a TOPIC). It fires only on
# a clear wrap-up COMMAND, never on discussion of handoff / the skill / this hook, and never on
# injected system content. A wrap-up phrase counts only at the start of a clause, so "don't wrap up
# yet" and "add an end session button" stay silent; the cost is that "I think we should wrap up"
# does too.
set -uo pipefail

# A subagent's or teammate's payload carries agent_id: never theirs to hand off. -I keeps the
# current directory off sys.path, so a project's own json.py can't run here. A curly apostrophe
# reads as a straight one, and a dash between words as a clause break ("great work — wrap up").
prompt="$(python3 -I -c '
import json, re, sys
d = json.load(sys.stdin)
if d.get("agent_id"):
    sys.exit(3)
p = d.get("prompt")
p = p if isinstance(p, str) else ""
dashes = chr(0x2013) + chr(0x2014)  # en and em dash; chr keeps the source ASCII, quote-free
p = p.replace(chr(0x2019), chr(39))
p = re.sub(r"\s[-" + dashes + r"]+\s|[" + dashes + "]", ", ", p)
sys.stdout.buffer.write(p.encode("utf-8", "replace"))
' 2>/dev/null)" || exit 0

emit() {
  cat <<'MSG'
[handoff-reminder] This looks like a session wrap-up / handoff / context reset. Before responding,
invoke the `handoff` skill (Skill tool, name "handoff") and run its FULL procedure rather than
improvising or cherry-picking steps. Improvising tends to silently drop steps (commonly the doc-drift
reconciliation and the memory curation, but run them all). If this is genuinely trivial with nothing
durable to carry, the skill itself says skip it, but make that an explicit judgment, not an omission.
MSG
}

# Here-strings, not printf | grep -q: with pipefail, grep quitting early on a long prompt would
# SIGPIPE printf and read as "no match".

# 1. Never fire on injected / non-user content (task notifications, system reminders, hook echoes,
#    slash-command stdout, a subagent's or another session's message). These are not the user
#    asking to wrap up. session-title.sh and session-summary.sh keep the same markers (INJECTED);
#    tests/setup/test_hook_payloads.py checks the three agree.
if grep -qiE '\[SYSTEM NOTIFICATION|NOT USER INPUT|<task-notification|<system-reminder|</system-reminder|automated background-task|hook success|<command-name>|<command-message>|<local-command|<agent-message|\[Subagent hand-back\]|<cross-session-message|<teammate-message' <<<"$prompt"; then
  exit 0
fi

# 2. Never fire when the user is talking ABOUT handoff (as a topic/noun) or about the skill/hook,
#    rather than asking to hand off. Catches: "the/this/that handoff", "handoff <noun>" (skill, hook,
#    issue, problem, ...), "the skill/hook/reminder", "false positive", "the hook fires/regex", etc.
if grep -qiE 'handoff[ -]?reminder|handoff\.sh|false[ -]?positive|\b(the|this|that|its|our|your) hand[ -]?off\b|hand[ -]?off (skill|hook|procedure|process|step|doc|rule|reminder|trigger|logic|mechanism|issue|problem|thing|bug|stuff|situation|behaviou?r|feature|note|change|fix|word|part|regex|line|matcher)|\b(the|this|that|a|an) (skill|hook|reminder)\b|(skill|hook|reminder) (is|was|fires|fired|triggers|triggered|matched|regex)' <<<"$prompt"; then
  exit 0
fi

# 3. Long messages are discussion, not a command: a long prompt that mentions /clear is talking about
#    it (an agent's report on /clear handling tripped this when this check came after rule 4).
words="$(wc -w <<<"$prompt" | tr -d '[:space:]')"
[ "${words:-999}" -gt 18 ] && exit 0

# 4. Explicit context-reset command in a terse message, punctuation or backticks around it allowed,
#    but not advice against it ("don't /clear yet").
if grep -qiE '(^|[[:space:]`"(])/clear([[:space:]`").,!?;:]|$)' <<<"$prompt" \
   && ! grep -qiE "(don'?t|do not|never|not|no need to|without)[[:space:]]+(to[[:space:]]+)?[\`\"(]?/clear" <<<"$prompt"; then
  emit; exit 0
fi

# 5. Otherwise fire only on an intent-bearing wrap-up phrase at the start of a clause (A), after
#    optional lead-ins (P), ending its clause (T): punctuation, the end, or a word that keeps it a
#    wrap-up ("now", "for today", "and push"), never "stop here and explain why". "hand off" counts
#    only in COMMAND form: spaced or hyphenated at a clause start, with a suffix, the closed
#    "handoff" after a lead-in, or alone in its clause ("handoff then push"; not "handoff?").
A='(^|[.!?;:,])[[:space:]]*'
P="((let'?s|lets|it'?s|time to|ok,?|okay,?|alright,?|so,?|thanks,?|thank you,?|great,?|cool,?|perfect,?|nice,?|please|just|i'?ll|i'?m|we'?re|we can|can we|should we|shall we|now,?|ready to|about to) +)"
W="(wrap(ping)? (this |it )?up|wrap(ping)? up (the |this )?session|call(ing)? it (a day|for the day|for the night|here|quits)|stop(ping)? here|stop for (the day|now|today)|end (of )?(the |this )?session|that'?s a wrap|wipe (the )?(context|memory)|clear (the )?(memory|context|session|chat|conversation)|hand[ -]off|hand[ -]?off (now|here|please|for real|time)|do a hand[ -]?off|hand (it|this|things) off)"
T='([[:space:]]*([^[:alnum:][:space:]]|$)|[[:space:]]+(now|please|then|here|so|today|tonight|for (today|now|the day|tonight|the night)|and (then |also )?(hand|push|commit|stop|close|end|clear|wrap|call))([^[:alnum:]]|$))'
BARE='[[:space:]]*([.!]|$)|[[:space:]]+(now|please|then|and|time)([^[:alnum:]]|$)'
if grep -qiE "${A}${P}*${W}${T}|${A}${P}+handoff${T}|${A}handoff(${BARE})" <<<"$prompt"; then
  emit; exit 0
fi

exit 0
