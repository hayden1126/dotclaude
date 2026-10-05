#!/usr/bin/env bash
# Keep a record of which Claude session is open in which tmux tab, so tmux/claude-restore can
# reopen the tabs after their tmux server dies (a reboot, `wsl --terminate`, `tmux kill-server`).
# Wired in settings.json:
#   SessionStart (startup, resume, clear, compact)  write or refresh the session's entry
#   SessionEnd                                      delete it, or mark it on reason `other`
# One file per session: $XDG_STATE_HOME/dotclaude/open-sessions/<session_id>.json, holding
# {session_id, cwd, transcript_path, pane, window_index, socket, server_start, ts}, written as an
# fsynced tmp file plus rename. socket and server_start (tmux's #{socket_path} and #{start_time})
# name the server the tab lives in: claude inherits the pane's TMUX, so `tmux display` reaches it.
# Only a tab counts: no TMUX_PANE, a `claude -p` run (ATTENDED=0, even with an inherited
# TMUX_PANE), a subagent payload (agent_id), an empty cwd or an unreadable server write nothing.
#
# What ends a session (probed 2026-10-05): /exit sends `prompt_input_exit`, /clear sends `clear`
# for the old id and then a SessionStart `clear` for the new one. Those and any other named reason
# delete the entry. A tmux kill-window, a SIGTERM to claude and a tmux kill-server all send
# `other`, so a shutdown that signals claude looks like a closed window here: `other` only adds
# ended_other_at, and claude-restore decides from the timing. tests/setup/test_session_registry.py
# holds the cases. Fail-open: always exits 0.
set -uo pipefail

[ "${CLAUDE_CODE_SESSION_ATTENDED:-}" != 0 ] || exit 0
input=$(cat 2>/dev/null)
case "$input" in *'"agent_id"'*) exit 0 ;; esac
case "$input" in
  *'"SessionStart"'*)
    [ -n "${TMUX_PANE:-}" ] || exit 0
    # "<start_time> <window_index> <socket_path>": the path last, since it may hold a space.
    server=$(tmux display -p -t "$TMUX_PANE" '#{start_time} #{window_index} #{socket_path}' 2>/dev/null)
    [ -n "$server" ] || exit 0 ;;
  *'"SessionEnd"'*) server="" ;;
  *) exit 0 ;;
esac

printf '%s' "$input" | \
  REG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude/open-sessions" \
  REG_SERVER="$server" REG_PANE="${TMUX_PANE:-}" python3 -I -c '
import json, os, re, sys, tempfile, time
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(d, dict) or d.get("agent_id"):
    sys.exit(0)
sid = d.get("session_id")
if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}", sid):
    sys.exit(0)
reg = os.environ["REG_DIR"]
path = os.path.join(reg, sid + ".json")

def write(entry):
    os.makedirs(reg, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=reg, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(entry, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

event = d.get("hook_event_name")
if event == "SessionStart":
    m = re.fullmatch(r"(\d+) (\d*) (.+)", os.environ.get("REG_SERVER", "").rstrip("\n"))
    cwd = d.get("cwd")
    if not m or not isinstance(cwd, str) or not cwd:
        sys.exit(0)
    write({"session_id": sid, "cwd": cwd,
           "transcript_path": d.get("transcript_path") or "",
           "pane": os.environ.get("REG_PANE", ""),
           "window_index": int(m.group(2)) if m.group(2) else None,
           "socket": m.group(3), "server_start": int(m.group(1)),
           "ts": round(time.time(), 3)})
elif event == "SessionEnd":
    if d.get("reason") == "other":
        try:
            with open(path) as f:
                entry = json.load(f)
        except (OSError, ValueError):
            sys.exit(0)
        if isinstance(entry, dict):
            entry["ended_other_at"] = round(time.time(), 3)
            write(entry)
    else:
        try:
            os.remove(path)
        except OSError:
            pass
' >/dev/null 2>&1
exit 0
