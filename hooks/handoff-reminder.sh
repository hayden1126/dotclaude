#!/usr/bin/env bash
# UserPromptSubmit hook: when the user signals a session wrap-up / handoff / context reset, inject a
# reminder to INVOKE the `handoff` skill rather than improvising its steps. Advisory only: it adds
# context, it cannot run the skill. Silent otherwise; always exits 0, so it can never block a prompt.
#
# How it decides (classify() below; tests/setup/test_handoff_reminder.py holds the cases):
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
# The event is read on stdin by python3 -I (-I keeps a project's own json.py off sys.path). If
# python3 fails, the hook stays silent: grepping the raw JSON payload instead misfired before.
set -uo pipefail

IFS= read -r -d '' src <<'PY'
import json, re, sys

MSG = """[handoff-reminder] This looks like a session wrap-up / handoff / context reset. Before responding,
invoke the `handoff` skill (Skill tool, name "handoff") and run its FULL procedure rather than
improvising or cherry-picking steps. Improvising tends to silently drop steps (commonly the doc-drift
reconciliation and the memory curation, but run them all). If this is genuinely trivial with nothing
durable to carry, the skill itself says skip it, but make that an explicit judgment, not an omission.
"""

# Keep in sync with session-title.sh and session-summary.sh (tests/setup/test_hook_payloads.py checks).
INJECTED = ("[system notification", "not user input", "<task-notification", "<system-reminder",
            "</system-reminder", "automated background-task", "hook success", "<command-name>",
            "<command-message>", "<local-command", "<agent-message", "[subagent hand-back]",
            "<cross-session-message", "<teammate-message")

I = re.I
H = r"hand[ -]?off"
DASHES = chr(0x2013) + chr(0x2014)  # en and em dash; chr keeps this source ASCII

# 1. Told not to use the skill: "handoff here, don't load the skill".
SKILL_NOT = re.compile(r"\b(?:don'?t|dont|do not)\s+(?:load|run|use|invoke)\s+(?:the\s+)?(?:handoff\s+)?skill\b"
                       r"|\bwithout\s+(?:loading|running|using)\s+(?:the\s+)?(?:handoff\s+)?skill\b", I)

# 2. A clause about handoff as a topic, or about the skill or this hook ("do the handoff" is a command).
TOPIC = re.compile(
    r"handoff[ -]?reminder|handoff\.sh|false[ -]?positive"
    r"|(?<!do )(?<!run )\b(the|this|that|its|our|your) hand[ -]?off\b"
    r"|hand[ -]?off (skill|hook|procedure|process|step|doc|rule|reminder|trigger|logic|mechanism|issue"
    r"|problem|thing|bug|stuff|situation|behaviou?r|feature|note|change|fix|word|part|regex|line|matcher)"
    r"|\b(the|this|that|a|an) (skill|hook|reminder)\b|(skill|hook|reminder) (is|was|fires|fired|triggers"
    r"|triggered|matched|regex)", I)

# Words that may open an action before the command itself ("ok let's", "can you do a quick"), an
# attachment tag ("[Image #4]"), or, right before "handoff", another action with no comma between
# ("deploy handoff and push").
LEAD = re.compile(
    r"(?:(?:let'?s|lets|ok(?:ay)?|alright|so|but|please|just|now|also|then|and|perhaps|maybe|you|i'?ll"
    r"|i'?m|we'?re|we can|can we|can you|could you|should we|shall we|go ahead and|time to|it'?s time to"
    r"|ready to|about to|thanks|thank you|ty|(?:great|nice|good|perfect|awesome|cool) (?:work|job))\b"
    r"|\[(?:image|pasted text)[^\]]*\]"
    r"|(?:deploy|redeploy|commit|push|merge|cleanup|clean up|verify|review|save|log|defer|proceed"
    r"|finish up|check|branch)\s+(?=hand)"
    r"|(?:(?:do|run) (?:a |the |your )?)?(?:quick |full |proper |final )?(?=hand))\s*", I)
# Lead-ins that make a generic phrase a command even when another task follows it.
STRONG = re.compile(r"\b(?:let'?s|lets|time to|ready to|we can|can we|should we|shall we)\b", I)

# 3. A question, praise or statement about handoff rather than the command.
QSTART = re.compile(r"(?:do (?:we|you|i|they|it|this|that)\b|(?:does|did) (?:we|you|i|they|it|this|that|a"
                    r"|the)\b|(?:was|were|is|are|has|have|had)\b|(?:why|what|when|which|who|how|where)\b"
                    r"|anything\b|should (?:i|you)\b)", I)
HWORD = rf"(?:{H}|hand (?:it|this|things|everything) off)"
AFTER_H = re.compile(
    r"\s*(?:(?:now|here)\s+)?(?:is|are|was|were|does|did|has|had|doesn'?t|didn'?t|isn'?t|wasn'?t|won'?t"
    r"|can'?t|shouldn'?t|not|never|can|could|should|will|would|might|must|may|looks?|seems?|works?|ran"
    r"|runs?|fires?|fails?|writes?|wrote|updates?|skips?|misses|breaks?|broke|broken|needs?|happens?"
    r"|goes|went|gets?|got|keeps?|stays?|done|complete|finished|good|fine|ok(?:ay)?|necessary|required"
    r"|[a-z]+ed)\b", I)
# "hand off the parser to Codex", "hand off for review": a delegation, unless the target is a session.
DELEGATE = re.compile(
    r"\s+(?:(?:[\w'-]+\s+){0,3}?to\s+(?:(?:another|an?|the|other|some|my|our|your)\s+"
    r"(?!(?:new |fresh |next |later |clean )(?:session|chat|conversation|agent|window|thread|instance)\b"
    r"|(?:session|chat|conversation)\b)|(?:codex|claude|gemini|gpt|sol|terra)\b)"
    r"|for\s+(?:review|approval|feedback|testing)\b)", I)
COPULA = re.compile(r"\b(?:is|are|was|were|isn'?t|aren'?t|wasn'?t)\b", I)
SUBORDINATE = re.compile(r"\b(?:if|when|whether|unless|while|before|after|until|because|since|so|what"
                         r"|that|which|who|where)\b", I)
SEP = re.compile(r"\s+(?:and then|and|then|so)\s+", I)

# 5. Generic wrap-up phrases, the tail that keeps one a wrap-up, and a next wrap-up step.
W = (r"(?:wrap(?:ping)? (?:this |it )?up(?: (?:the |this )?session)?|call(?:ing)? it (?:a day|a night"
     r"|for the day|for the night|quits)|call it here|stop(?:ping)? here|stop for (?:the day|now|today)"
     r"|end (?:of )?(?:the |this )?session|that'?s a wrap|wipe (?:the )?(?:context|memory)"
     r"|clear (?:the )?(?:memory|context|session|chat|conversation)|done for (?:the day|today|tonight|the night))")
TAIL = (r"(?:\s+(?:now|please|here|then|so|today|tonight|first|for (?:today|now|the day|tonight|the night"
        r"|this session|the session)))*")
STEP = rf"(?:{H}|push|commit|merge|deploy|wrap (?:it |this )?up)"
OBJ = r"(?:\s+(?:the|this|that|it|what|everything|all|my|our|your)(?:\s+[\w'-]+){0,2})?"
FIXED = (r"(?:call it a day|clear(?: (?:the )?(?:context|session|chat|conversation|memory))?"
         r"|end (?:the |this )?session|close (?:it |this )?out)")
NEXT = rf"(?:\s+(?:and then|and|then|so)\s+(?:{STEP}{OBJ}|{FIXED}))*"
WHOLE = re.compile(rf"{W}{TAIL}{NEXT}", I)
NEXT_ONLY = re.compile(rf"(?:and|then|so)(?: then| also)?\s+(?:{STEP}{OBJ}|{FIXED})", I)
ANYWHERE = re.compile(rf"(?:^|\s)(?:let'?s|lets|time to|it'?s time to|ready to|please)\s+{W}{TAIL}{NEXT}$", I)
FULLY = re.compile(r"(?:fully|properly)\s+wrap\s+(?:it\s+|this\s+)?up\b", I)
NEGATION = re.compile(r"\b(?:don'?t|dont|do not|not|never|can'?t|cannot|won'?t|shouldn'?t)\b", I)
# An example list runs to the end of its sentence: "a skill that ...? eg check bugs, then handoff".
EXAMPLE = re.compile(r"\b(?:e\.g\.|eg\b|for example|for instance|such as)[^.!?;\n]*[.!?;\n]?", I)

# 4. /clear, and advice against it or a question about it.
Q = r"what(?:'s| is| does| do| about)|how (?:does|do|is)|why (?:does|do|is|would)|which|where"
CLEAR = re.compile(r"(?:^|[\s`\"(])/clear(?:[\s`\").,!?;:]|$)", I)
CLEAR_NOT = re.compile(rf"(?:^|[^\w])(?:(?:don'?t|dont|do not|never|not|can'?t|cant|cannot|won'?t|{Q})"
                       rf"(?:\s+[\w'-]+){{0,3}}|no|no need to|without(?: a| the)?)\s+[`\"(]?/clear", I)


def strip_leads(s):
    s = s.strip()
    while True:
        m = LEAD.match(s)
        if not m or not m.group(0):
            return s
        s = s[m.end():]


def trim(s):
    """Drop trailing symbols and spaces (an emoji, a smiley) in one linear pass."""
    i = len(s)
    while i and not (s[i - 1].isalnum() or s[i - 1] in "_'"):
        i -= 1
    return s[:i]


def clauses(text):
    """[(clause, terminator)], split on clause punctuation and line breaks."""
    parts = re.split(r"([.!?;:,\n]+)", text)
    out = [(parts[i].strip(), parts[i + 1] if i + 1 < len(parts) else "") for i in range(0, len(parts), 2)]
    return [(c, t) for c, t in out if c]


def starts(clause):
    """The clause and each part after a dash: a dash between words starts a clause, but never ends one."""
    pieces = re.split(rf"\s[-{DASHES}]+\s|[{DASHES}]", clause)
    return [" ".join(pieces[i:]).strip() for i in range(len(pieces))]


def segments(start):
    """[(segment, offset)]: the actions of a clause, split on and / then / so."""
    out, pos = [], 0
    for m in SEP.finditer(start):
        out.append((start[pos:m.start()], pos))
        pos = m.end()
    out.append((start[pos:], pos))
    return out


def handoff_command(clause, label):
    if QSTART.match(clause):
        return False
    for start in starts(clause):
        for seg, off in segments(start):
            s = strip_leads(seg)
            m = re.match(rf"{HWORD}\b", s, I)
            if not m:
                continue
            rest = s[m.end():]
            if AFTER_H.match(rest) or DELEGATE.match(rest):
                continue
            # A statement after it ("handoff and push notifications are both broken"), but not inside
            # an "if", "so" or "what" clause ("hand off if there is anything left", "push what is left").
            after = SUBORDINATE.split(start[off + seg.find(s) + m.end():])[0]
            if COPULA.search(after):
                continue
            if label and not rest.strip() and s == strip_leads(clause):
                continue  # a bare "handoff" labelling a topic: "handoff: does it update memory too?"
            return True
    return False


def label_follows(terms, i):
    """A colon ends clause i, or a later clause reached only through commas ("handoff, docs: why?")."""
    for t in terms[i:]:
        if ":" in t:
            return True
        if not set(t) <= {","}:
            return False
    return False


def continues_elsewhere(nxt):
    """The next clause is another task, not a wrap-up step: "stop here, then explain why"."""
    n = trim(nxt.strip())
    if re.match(r"(?:why|how)\b", n, I):
        return True
    return bool(re.match(r"(?:and|then|so)\b", n, I)) and not NEXT_ONLY.fullmatch(n)


def generic(clause, next_clause):
    for start in starts(clause):
        body = strip_leads(start)
        leads = start.strip()[:len(start.strip()) - len(body)]
        if WHOLE.fullmatch(trim(body)):
            if not STRONG.search(leads) and next_clause and continues_elsewhere(next_clause):
                continue
            return True
        t = trim(start)
        m = ANYWHERE.search(t)
        if m and not NEGATION.search(t[:m.start()]):
            return True
        if FULLY.match(body) and not NEGATION.search(leads):
            return True
    return False


def classify(prompt):
    text = prompt.replace(chr(0x2019), chr(39))  # a curly apostrophe reads as a straight one
    low = text.lower()
    if any(m in low for m in INJECTED) or SKILL_NOT.search(text):
        return False
    cs = clauses(EXAMPLE.sub(" ", text))
    if not cs:
        return False
    terms = [t for _, t in cs]
    long = len(text.split()) > 18
    if not long and CLEAR.search(text) and not CLEAR_NOT.search(text):
        return True
    first = 0
    if long:  # the last clause, and up to two short ones before it
        first = len(cs) - 1
        while first > 0 and len(cs) - first < 3 and len(cs[first - 1][0].split()) <= 8:
            first -= 1
    for i in range(first, len(cs)):
        c = cs[i][0]
        if TOPIC.search(c):
            continue
        if handoff_command(c, label_follows(terms, i)):
            return True
        if not long and generic(c, cs[i + 1][0] if i + 1 < len(cs) else ""):
            return True
    return False


try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if isinstance(d, dict) and not d.get("agent_id") and isinstance(d.get("prompt"), str):
    if classify(d["prompt"]):
        sys.stdout.write(MSG)
PY
python3 -I -c "$src" 2>/dev/null || exit 0
