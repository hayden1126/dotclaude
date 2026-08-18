#!/usr/bin/env bash
# Stop hook: (re)generate a 1-2 sentence "what is this session doing, and where
# does it stand" summary via Haiku and cache it to
# <config-dir>/session-summaries/<session_id>.txt, where the status-line widget
# (statusline/session-summary.py) reads it. Purpose: a developer running several
# Claude terminals at once can re-orient after switching back to one, without
# relying on the (often off-screen) native task panel or the terse tab title.
#
# Generation is a direct Haiku Messages-API call authenticated with the Claude
# subscription OAuth token from <config-dir>/.credentials.json (no API key on this
# machine). That is ~3x cheaper on the 5h/7d quota than spinning a headless
# `claude -p` session, because it skips the full system-prompt overhead. Uses only
# the Python stdlib (urllib) -- no deps, no jq.
#
# Detaches the call so Stop never blocks the turn. Fails open on everything (exit
# 0, nothing on stdout): a missing/expired token or a failed call just leaves the
# previous summary in place (the widget then keeps showing it, or the ai-title).
#
# Note: the OAuth token file is undocumented and its access token rotates; reads
# are best-effort and the fail-open path covers a stale read between refreshes.
set -uo pipefail

input=$(cat 2>/dev/null)

generate() {
  python3 - "$1" <<'PY'
import sys, os, json, urllib.request, urllib.error

# ---- tunables -------------------------------------------------------------
MODEL        = "claude-haiku-4-5-20251001"
API_URL      = "https://api.anthropic.com/v1/messages"
MIN_GROWTH   = 2048     # bytes; skip regen if the transcript grew less than this
RECENT_MSGS  = 10       # trailing user/assistant messages fed to the model
MSG_CLIP     = 400      # chars kept per message
CALL_TIMEOUT = 30       # seconds for the API call
MAX_TOKENS   = 200      # summary is 1-2 sentences; cap output cost
SUMMARY_MAX  = 400      # hard clip on the returned summary
# ---------------------------------------------------------------------------

def die():
    sys.exit(0)

try:
    data = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else {}
except Exception:
    die()

session_id = (data.get("session_id") or "").strip()
transcript = (data.get("transcript_path") or "").strip()
if not session_id or not transcript:
    die()

def config_dir(tp):
    if tp:
        d = os.path.dirname(tp)
        if os.path.basename(os.path.dirname(d)) == "projects":
            return os.path.dirname(os.path.dirname(d))
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")

cfg = config_dir(transcript)
out_dir = os.path.join(cfg, "session-summaries")
state_dir = os.path.join(out_dir, ".state")
cache_file = os.path.join(out_dir, session_id + ".txt")
state_file = os.path.join(state_dir, session_id)

try:
    size = os.path.getsize(transcript)
except OSError:
    die()

# cadence gate: once a summary exists, skip regen until the transcript grows a bit
prev = None
try:
    with open(state_file) as f:
        prev = int(f.read().strip() or 0)
except (OSError, ValueError):
    prev = None
if os.path.exists(cache_file) and prev is not None and size - prev < MIN_GROWTH:
    die()

# prior summary, fed back so the label stays stable turn to turn
prior = ""
try:
    with open(cache_file, encoding="utf-8") as f:
        prior = " ".join(f.read().split())
except OSError:
    pass

def recent_dialogue(path, chunk=131072):
    """Last RECENT_MSGS user/assistant text messages from the transcript tail."""
    try:
        sz = os.path.getsize(path)
        with open(path, "rb") as f:
            if sz > chunk:
                f.seek(sz - chunk)
            blob = f.read()
    except OSError:
        return ""
    msgs = []
    for line in blob.decode("utf-8", "ignore").splitlines():
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("type") not in ("user", "assistant"):
            continue
        content = (o.get("message") or {}).get("content")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(b["text"] for b in content
                            if isinstance(b, dict) and b.get("type") == "text" and b.get("text"))
        text = " ".join(text.split())
        if text:
            msgs.append((o["type"], text[:MSG_CLIP]))
    msgs = msgs[-RECENT_MSGS:]
    return "\n".join(("User: " if t == "user" else "Assistant: ") + x for t, x in msgs)

dialogue = recent_dialogue(transcript)
if not dialogue:
    die()

def oauth_token(cfg):
    for p in (os.path.join(cfg, ".credentials.json"),
              os.path.expanduser("~/.claude/.credentials.json")):
        try:
            with open(p) as f:
                return json.load(f)["claudeAiOauth"]["accessToken"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return ""

token = oauth_token(cfg)
if not token:
    sys.stderr.write("session-summary: no OAuth token found\n")
    die()

system = ("You label a developer's coding session in one glance so they can "
          "re-orient after switching between several terminals.")
user = (
    (f"Prior summary (may be stale, refine it): {prior}\n\n" if prior else "")
    + "Recent conversation:\n" + dialogue
    + "\n\nIn 1-2 sentences, plainly state what this coding session is building "
      "or fixing and where it currently stands. Describe the work itself (the "
      "files, feature, or bug), not the conversation about it; do not address the "
      "developer or use second person. Plain text only: no markdown, asterisks, "
      "backticks, quotes, or preamble."
)
body = json.dumps({
    "model": MODEL,
    "max_tokens": MAX_TOKENS,
    "temperature": 0.3,
    "system": system,
    "messages": [{"role": "user", "content": user}],
}).encode()
req = urllib.request.Request(API_URL, data=body, method="POST", headers={
    "content-type": "application/json",
    "authorization": f"Bearer {token}",
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "oauth-2025-04-20",
})
try:
    with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as r:
        resp = json.load(r)
except Exception as e:
    sys.stderr.write(f"session-summary: api call failed: {e}\n")
    die()

summary = " ".join("".join(
    b.get("text", "") for b in resp.get("content", []) if isinstance(b, dict)
).split())
if not summary:
    die()
if len(summary) > SUMMARY_MAX:
    summary = summary[:SUMMARY_MAX - 1].rstrip() + "…"

try:
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(state_dir, exist_ok=True)
    tmp = cache_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(summary + "\n")
    os.replace(tmp, cache_file)
    with open(state_file, "w") as f:
        f.write(str(size))
except OSError:
    die()
PY
}

# Detach fully so Stop returns immediately; orphan the job via ( ... & ).
( generate "$input" >/dev/null 2>&1 & )
exit 0
