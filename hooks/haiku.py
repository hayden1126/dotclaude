"""The direct Haiku call the Stop hooks share: the subscription OAuth token from Claude Code's
credentials file, one Messages API request, the reply's text.

hooks/session-summary.sh (the status-line summary and tab label) and hooks/wants_input.py (the
tab glyph's "does this reply want Hayden?") import it from this file's own directory. There is
no API key on this machine: the token is claudeAiOauth.accessToken in
<config-dir>/.credentials.json, sent as a Bearer token with the oauth beta header (verified
live; no Claude Code system prompt needed). It burns subscription quota, so callers keep their
calls small. The file is undocumented and the token rotates: every failure raises HaikuError
with a short reason for the caller's log, and callers fail open. claude-haiku-5-5 answers 429
to this token on every call (probed 2026-10-14, 21 of 21); claude-haiku-4-5 works. Stdlib
only; keep the source ASCII.
"""
import http.client
import json
import os
import socket
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"


class HaikuError(Exception):
    """A call that gave no text. reason is one word for a log line: no-token, http-<code>,
    timeout, network, refusal or bad-response."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def config_dir(transcript_path) -> str:
    """Claude Code's config dir: the one holding projects/<slug>/<session>.jsonl when the
    transcript path has that shape, else CLAUDE_CONFIG_DIR, else ~/.claude."""
    if isinstance(transcript_path, str) and transcript_path:
        d = os.path.dirname(transcript_path)
        if os.path.basename(os.path.dirname(d)) == "projects":
            return os.path.dirname(os.path.dirname(d))
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def oauth_token(cfg: str) -> str:
    """The subscription access token from cfg's credentials file, then ~/.claude's; "" if
    neither has one."""
    for p in (os.path.join(cfg, ".credentials.json"),
              os.path.expanduser("~/.claude/.credentials.json")):
        try:
            with open(p) as f:
                token = json.load(f)["claudeAiOauth"]["accessToken"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(token, str) and token:
            return token
    return ""


def ask(system: str, user: str, *, model: str, max_tokens: int, timeout: float, cfg: str,
        **fields) -> str:
    """One Messages API call: system and user text in, the reply's text out. fields go into
    the request body as they are (temperature, for one). Raises HaikuError."""
    token = oauth_token(cfg)
    if not token:
        raise HaikuError("no-token")
    body = json.dumps({"model": model, "max_tokens": max_tokens, "system": system,
                       "messages": [{"role": "user", "content": user}], **fields}).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "content-type": "application/json",
        "authorization": "Bearer " + token,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        raise HaikuError("http-%d" % e.code) from None
    except (socket.timeout, TimeoutError):
        raise HaikuError("timeout") from None
    except urllib.error.URLError as e:
        timed_out = isinstance(e.reason, (socket.timeout, TimeoutError))
        raise HaikuError("timeout" if timed_out else "network") from None
    except (OSError, http.client.HTTPException):   # a cut or garbled response too
        raise HaikuError("network") from None
    except ValueError:
        raise HaikuError("bad-response") from None
    if not isinstance(resp, dict) or not isinstance(resp.get("content"), list):
        raise HaikuError("bad-response")
    if resp.get("stop_reason") == "refusal":
        raise HaikuError("refusal")
    return "".join(b.get("text", "") for b in resp["content"]
                   if isinstance(b, dict) and isinstance(b.get("text"), str))
