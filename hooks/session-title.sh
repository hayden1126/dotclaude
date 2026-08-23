#!/usr/bin/env bash
# UserPromptSubmit hook: set the Claude Code session title (== terminal tab title)
# to "[<repo>] <label>" so tabs are tellable apart.
#
# The <label> is a short summary of the session. It does NOT come from Claude Code's
# own "ai-title" record any more: as of CC 2.1.237 (Aug 2026) Claude only generates
# that title when no custom session title is set, and this hook sets one on turn 1,
# so reading ai-title would mean suppressing the very record we read. Instead the
# label is ours: session-summary.sh (Stop hook) writes a <=32-char label to
# session-summaries/<session_id>.title.txt, which we read here. Source cascade:
#   1. that Haiku label                          (steady state, turn 2+)
#   2. first line of this prompt                 (turn-1 seed / fallback; keeps [repo])
#   3. first clause of the long summary (.txt)   (degrade)
#   4. repo only                                 (floor)
#
# Emits the SUPPORTED hookSpecificOutput.sessionTitle field (NOT raw OSC escapes):
# it flows through Claude Code's own rename path, has display precedence over the
# AI title (currentSessionTitle ?? aiTitle), and leaves the tab's running/idle
# status icons untouched. terminalTitleFromRename defaults true, so no setting is
# needed for the tab to update.
#
# Contract: reads the event JSON on stdin (cwd, transcript_path, prompt, ...),
# prints EXACTLY the one JSON object below to stdout, exits 0. FAILS OPEN on any
# error (exit 0, NOTHING on stdout) so it can never block or corrupt a prompt.
# Diagnostics go to STDERR only: any stray STDOUT would break Claude Code's
# per-hook JSON parse and be injected into the prompt as context instead.
#
# Uses python3 (jq is not installed here). No git subprocess: the repo root is
# found by walking up for a .git entry (dir=repo, file=worktree/submodule). Reads
# only the transcript TAIL for the DEDUP check, so cost is flat on any transcript size.
set -uo pipefail

input=$(cat 2>/dev/null)

python3 - "$input" <<'PY' 2>/dev/null || exit 0
import sys, os, json

# ---- tunables -------------------------------------------------------------
LBRACK, RBRACK     = "[", "]"    # repo is wrapped: "[repo] summary"
TITLE_MAX          = 64          # total chars; terminals truncate long titles anyway
REPO_MAX           = 40          # keep the repo (the disambiguator) always visible
INCLUDE_BRANCH     = False       # append " (branch)" inside the brackets when in a git repo
DEDUP              = True        # skip emitting if title == the one we last set
# ---------------------------------------------------------------------------

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

def fail_open():
    sys.exit(0)  # exit 0, no stdout

try:
    data = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else {}
except Exception:
    fail_open()

cwd        = (data.get("cwd") or "").strip()
transcript = (data.get("transcript_path") or "").strip()
prompt     = data.get("prompt") or ""

def find_repo_root(start):
    """(root, is_git). Walk up for a .git entry; dir=repo, file=worktree/submodule."""
    if not start:
        return None, False
    try:
        cur = os.path.abspath(start)
    except Exception:
        return None, False
    if not os.path.isdir(cur):
        cur = os.path.dirname(cur)
    while True:
        if os.path.exists(os.path.join(cur, ".git")):
            return cur, True
        parent = os.path.dirname(cur)
        if parent == cur:
            return None, False
        cur = parent

root, is_git = find_repo_root(cwd)
if root:
    name = os.path.basename(root)
elif cwd:
    name = os.path.basename(os.path.abspath(cwd).rstrip(os.sep))
else:
    name = ""
if not name:
    fail_open()  # nothing meaningful to show; leave the existing title alone

def head_branch(root):
    """Best-effort branch name, no git subprocess. '' on anything odd/detached."""
    try:
        gp = os.path.join(root, ".git")
        if os.path.isfile(gp):                       # worktree/submodule: "gitdir: <path>"
            with open(gp, encoding="utf-8", errors="ignore") as f:
                ln = f.readline().strip()
            gd = ln.split("gitdir:", 1)[1].strip() if ln.startswith("gitdir:") else ""
            if gd and not os.path.isabs(gd):
                gd = os.path.join(root, gd)
        else:
            gd = gp
        with open(os.path.join(gd, "HEAD"), encoding="utf-8", errors="ignore") as f:
            head = f.readline().strip()
        if head.startswith("ref: refs/heads/"):
            return head[len("ref: refs/heads/"):]
        return head[:7] if head else ""             # detached: short sha
    except Exception:
        return ""

def config_dir(tp):
    """The Claude config dir, from the transcript path: <cfg>/projects/<slug>/<id>.jsonl."""
    if tp:
        d = os.path.dirname(tp)
        if os.path.basename(os.path.dirname(d)) == "projects":
            return os.path.dirname(os.path.dirname(d))
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")

def last_custom_title(path, chunk=262144):
    """The last custom-title we set, from the transcript tail (for the DEDUP check)."""
    if not path:
        return None
    if not os.path.isabs(path):
        path = os.path.join(cwd or "", path)
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > chunk:
                f.seek(size - chunk)
            blob = f.read()
    except OSError:
        return None
    for line in reversed(blob.decode("utf-8", "ignore").splitlines()):
        if '"custom-title"' in line:
            try:
                o = json.loads(line)
                if o.get("type") == "custom-title":
                    return o.get("customTitle")   # confirmed key from the binary
            except Exception:
                pass
    return None

def read_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            return " ".join(f.read().split())
    except OSError:
        return ""

def first_line(s):
    for ln in s.splitlines():
        ln = " ".join(ln.split())
        if ln:
            return ln
    return ""

def first_clause(s):
    s = " ".join(s.split())
    for i, ch in enumerate(s):
        if ch in ";:.—":
            return s[:i].strip()
    return s

# resolve transcript to an absolute path, then derive session_id + config dir
tpath = transcript
if tpath and not os.path.isabs(tpath):
    tpath = os.path.join(cwd or "", tpath)
session_id = os.path.basename(tpath)
if session_id.endswith(".jsonl"):
    session_id = session_id[:-len(".jsonl")]

summaries = os.path.join(config_dir(tpath), "session-summaries")
label_cache   = read_cache(os.path.join(summaries, session_id + ".title.txt")) if session_id else ""
summary_cache = read_cache(os.path.join(summaries, session_id + ".txt")) if session_id else ""

custom_title = last_custom_title(transcript)

def clip(s, n):
    s = " ".join(s.split())         # collapse whitespace/newlines
    return s if len(s) <= n else s[:max(0, n - 1)].rstrip() + "…"   # …

repo = clip(name, REPO_MAX)
if INCLUDE_BRANCH and is_git:
    br = head_branch(root)
    if br:
        repo = "%s (%s)" % (repo, clip(br, 20))

label = LBRACK + repo + RBRACK                       # "[dotclaude]"
if label_cache:
    summary = label_cache                            # (1) our Haiku short label
elif prompt:
    summary = first_line(prompt)                     # (2) this prompt's first line
elif summary_cache:
    summary = first_clause(summary_cache)            # (3) first clause of the long summary
else:
    summary = ""                                     # (4) repo only
if summary:
    budget = TITLE_MAX - len(label) - 1              # 1 for the joining space
    title = label + " " + clip(summary, budget) if budget >= 8 else label
else:
    title = label

if DEDUP and custom_title is not None and title == custom_title:
    fail_open()  # unchanged; skip the redundant transcript line + rename event

sys.stdout.write(json.dumps(
    {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "sessionTitle": title}},
    ensure_ascii=False,
))
PY
