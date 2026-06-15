#!/usr/bin/env bash
# PreToolUse(Bash) danger-guard. Two-tier confirmation for destructive ops.
#
#   deny  (hard block, no override) - never-legitimate ops:
#           git push --force / -f / --force-with-lease, git reset --hard/--merge/--keep,
#           git clean -f/-d.
#   ask   (prompt for explicit approval) - routine-but-sensitive ops:
#           git push / checkout / switch / revert, and rm -r / -f / -rf.
#
# Design intent: we use "deny" (final per the hooks docs) for the worst ops rather than
# trusting the undocumented `skipAutoPermissionPrompt` setting to honor an "ask". Routine
# ops stay "ask" so Hayden can approve in-dialog, matching the "propose and confirm"
# boundaries in CLAUDE.md.
#
# Token-aware: does not false-positive on `git commit -m "push fix"`. Recurses into
# `bash -c "..."` / `sh -c "..."` / `eval "..."` wrappers. Fires for the main agent and
# all subagents (covers the Explore/Plan CLAUDE.md blind spot). Fail-open: any parse
# error allows the command (exit 0, no decision). Limitation: shell aliases (`g push`)
# cannot be resolved statically and are not caught.

input=$(cat 2>/dev/null)

python3 - "$input" <<'PY' 2>/dev/null || exit 0
import sys, json, shlex, os, re

try:
    data = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else {}
except Exception:
    sys.exit(0)

cmd = (data.get("tool_input") or {}).get("command", "")
if not cmd:
    sys.exit(0)

DANGER_KEYWORDS = ("push", "checkout", "switch", "revert", "reset", "clean", "rm")
WRAPPERS = {"bash", "sh", "zsh", "dash", "ksh"}
GLOBAL_ARG_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
_ORDER = {None: 0, "ask": 1, "deny": 2}

def tier_max(a, b):
    return a if _ORDER[a] >= _ORDER[b] else b

def classify_git(args):
    k = 0
    while k < len(args) and args[k].startswith("-"):
        k += 2 if args[k] in GLOBAL_ARG_OPTS else 1
    if k >= len(args):
        return None
    sub = args[k]
    rest = args[k+1:]
    if sub == "push":
        if any(a in ("--force", "-f", "--force-with-lease") or a.startswith("--force-with-lease=") for a in rest):
            return "deny"
        return "ask"
    if sub == "reset":
        return "deny" if any(a in ("--hard", "--merge", "--keep") for a in rest) else None
    if sub == "clean":
        for a in rest:
            if a == "--force" or (a.startswith("-") and not a.startswith("--") and any(c in "fd" for c in a[1:])):
                return "deny"
        return None
    if sub in ("checkout", "switch", "revert"):
        return "ask"
    return None

def classify_rm(args):
    for a in args:
        if a.startswith("--"):
            if a in ("--recursive", "--force"):
                return "ask"
        elif a.startswith("-") and len(a) > 1 and any(c in "rRf" for c in a[1:]):
            return "ask"
    return None

def classify_segment(seg, depth):
    if not seg.strip():
        return None
    try:
        toks = shlex.split(seg)
    except Exception:
        # Unbalanced quotes (e.g. a quoted compound split mid-string): stay safe.
        return "ask" if any(k in seg for k in DANGER_KEYWORDS) else None
    i = 0
    while i < len(toks) and "=" in toks[i] and not toks[i].startswith("-"):
        i += 1  # skip leading env assignments
    if i >= len(toks):
        return None
    name = os.path.basename(toks[i])
    if name in WRAPPERS:
        for j in range(i+1, len(toks)):
            t = toks[j]
            if t.startswith("-") and not t.startswith("--") and "c" in t[1:] and j+1 < len(toks):
                return classify_cmd(toks[j+1], depth+1)
        return None
    if name == "eval":
        return classify_cmd(" ".join(toks[i+1:]), depth+1)
    if name == "git":
        return classify_git(toks[i+1:])
    if name == "rm":
        return classify_rm(toks[i+1:])
    return None

def classify_cmd(cmd, depth=0):
    if depth > 4 or not cmd.strip():
        return None
    tier = None
    for seg in re.split(r'\|\||&&|[;|&\n]', cmd):
        tier = tier_max(tier, classify_segment(seg, depth))
        if tier == "deny":
            break
    return tier

tier = classify_cmd(cmd)
if tier == "deny":
    reason = ("Destructive git op (force-push / reset --hard / git clean -f) is hard-blocked. "
              "Run it yourself if you truly intend it.")
elif tier == "ask":
    reason = ("Sensitive op (push / checkout / switch / revert / rm -rf) needs Hayden's "
              "explicit approval.")
else:
    sys.exit(0)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": tier,
        "permissionDecisionReason": reason
    }
}))
sys.exit(0)
PY
