#!/usr/bin/env bash
# Keep a record of which Claude session is open in which tmux tab, so tmux/claude-restore can
# reopen the tabs after their tmux server dies (a reboot, `wsl --terminate`, `tmux kill-server`).
# Wired in settings.json:
#   SessionStart (startup, resume, clear, compact)  write or refresh the session's entry
#   SessionEnd                                      delete it, or mark it on reason `other`
# One file per session: $XDG_STATE_HOME/dotclaude/open-sessions/<session_id>.json, holding
# {session_id, cwd, transcript_path, pane, window_index, socket, server_start, server_pid, ts},
# place when the window has one, and model and effort when the session's claude launched with
# --model or --effort, written as an fsynced tmp file plus rename. socket,
# server_start and server_pid (tmux's #{socket_path}, #{start_time} and #{pid}; the pid tells
# apart two servers started in the same second) name the server the tab lives in: claude inherits
# the pane's TMUX, so `tmux display` reaches it. place is the window's @tab_place, the tab bar's
# row and position for it (tmux/tmux-tab-bar owns the format; here it is an opaque string, kept
# only as 1 to 2048 bytes of UTF-8 with no control character), which claude-restore sets back.
# model and effort are the session's claude's own launch flags: its nearest ancestor named claude
# (a hook runs a few processes below it), read from /proc and kept only in their shape
# (lanelib.pick_ok). claude-restore and claude-saved's Open resume the session with them, as a
# plain pass would carry them (lanelib.carried_pick; docs/lanes.md, "Model and effort"). lanelib
# is found through this hook's link, by absolute path only; any failure there writes the entry
# without them.
# Every write and delete holds open-sessions/.records.lock (flock, waiting up to 2 s, then going
# ahead without it), as claude-saved's do: tmux-tab-bar compares and replaces a record's place
# under it, so a record deleted or rewritten here is never brought back or overwritten by a stale
# copy. One race stays: a move landing between this hook's read of @tab_place and its write
# leaves the record one move behind (the live bar is right) until a move that changes this
# tab's place, or its next SessionStart.
# Only a tab counts: no TMUX_PANE, a `claude -p` run (ATTENDED=0, even with an inherited
# TMUX_PANE), a subagent payload (agent_id), an empty cwd or an unreadable server write nothing.
#
# What ends a session (probed 2026-10-05): /exit sends `prompt_input_exit`, /clear sends `clear`
# for the old id and then a SessionStart `clear` for the new one. Those and any other named reason
# delete the entry. A tmux kill-window, a SIGTERM to claude and a tmux kill-server all send
# `other`, so a shutdown that signals claude looks like a closed window here: `other` only adds
# ended_other_at, and claude-restore decides from the timing.
#
# Then, in a tab, it hands the same payload to ~/.local/bin/claude-saved (tmux/claude-saved,
# linked by setup-tmux.sh), which keeps a starred chat's star on its tab across /clear. That call
# is bounded by `timeout 3`, its output is dropped, and a failure changes nothing here.
# tests/setup/test_session_registry.py holds the cases. Fail-open: always exits 0.
set -uo pipefail

[ "${CLAUDE_CODE_SESSION_ATTENDED:-}" != 0 ] || exit 0
input=$(cat 2>/dev/null)
case "$input" in *'"agent_id"'*) exit 0 ;; esac
case "$input" in
  *'"SessionStart"'*)
    [ -n "${TMUX_PANE:-}" ] || exit 0
    # "<start_time> <pid> <window_index> <socket_path>": the path last, since it may hold a space.
    server=$(tmux display -p -t "$TMUX_PANE" '#{start_time} #{pid} #{window_index} #{socket_path}' 2>/dev/null)
    [ -n "$server" ] || exit 0
    # Its own call, since it may hold anything. The x keeps a trailing newline of the value,
    # which $() would strip into a valid-looking one; -u keeps tmux from replacing non-ASCII
    # with _ when the locale isn't UTF-8. A failed read leaves it empty: no place.
    place=$(tmux -u display -p -t "$TMUX_PANE" '#{@tab_place}' 2>/dev/null && printf x)
    place=${place%x}
    place=${place%$'\n'} ;;
  *'"SessionEnd"'*) server="" place="" ;;
  *) exit 0 ;;
esac

# lanelib, through the hook's link as installed: an absolute path only, since a relative one would
# import from the session's cwd in code that runs outside the sandbox.
self=$(readlink -f "$0" 2>/dev/null)
lib=""
[[ "$self" != /* ]] || lib="$(dirname "$(dirname "$self")")/skills/lanes/scripts"

printf '%s' "$input" | \
  REG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude/open-sessions" REG_LIB="$lib" \
  REG_SERVER="$server" REG_PANE="${TMUX_PANE:-}" REG_PLACE="$place" python3 -I -c '
import fcntl, json, os, re, sys, tempfile, time
lanelib = None
if os.path.isabs(os.environ.get("REG_LIB", "")):
    sys.path.insert(0, os.environ["REG_LIB"])
    try:
        import lanelib
    except Exception:   # a missing or broken lanelib costs the launch flags, never the entry
        lanelib = None
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

def locked():
    """The records lock (shared with tmux-tab-bar, whose record update compares and replaces
    under it), as a held fd; None when it cannot be opened or is not free within 2 s: go ahead
    without."""
    try:
        fd = os.open(os.path.join(reg, ".records.lock"),
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        return None
    deadline = time.monotonic() + 2
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                return None
            time.sleep(0.01)

def launch_pick():
    """The --model and --effort the session claude launched with, as entry fields: the nearest
    ancestor named claude, its argv from /proc. {} on any failure (no lanelib, no claude above
    this hook, an unreadable /proc), so the entry is still written."""
    try:
        claude = next(pid for pid, _ in lanelib.ancestry(os.getpid())
                      if (lanelib.proc_stat(pid) or ("",))[0] == "claude")
        flags = lanelib.pick_flags(lanelib.proc_cmdline(claude))
        return {flag[2:]: value for flag, value in flags.items() if lanelib.pick_ok(flag, value)}
    except Exception:
        return {}

def write(entry):
    fd, tmp = tempfile.mkstemp(dir=reg, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(entry, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

event = d.get("hook_event_name")
if event == "SessionStart":
    m = re.fullmatch(r"(\d+) (\d+) (\d*) (.+)", os.environ.get("REG_SERVER", "").rstrip("\n"))
    cwd = d.get("cwd")
    if not m or not isinstance(cwd, str) or not cwd:
        sys.exit(0)
    entry = {"session_id": sid, "cwd": cwd,
             "transcript_path": d.get("transcript_path") or "",
             "pane": os.environ.get("REG_PANE", ""),
             "window_index": int(m.group(3)) if m.group(3) else None,
             "socket": m.group(4), "server_start": int(m.group(1)),
             "server_pid": int(m.group(2)),
             "ts": round(time.time(), 3)}
    place = os.environ.get("REG_PLACE", "")
    try:
        size = len(place.encode("utf-8"))
    except UnicodeError:   # a lone surrogate: bytes that were not UTF-8
        size = 0
    if 1 <= size <= 2048 and not re.search(r"[\x00-\x1f\x7f]", place):
        entry["place"] = place
    entry.update(launch_pick())
    os.makedirs(reg, exist_ok=True)
    lock = locked()   # held until exit, as below
    write(entry)
elif event == "SessionEnd":
    lock = locked()
    if d.get("reason") == "other":
        try:
            with open(path) as f:
                entry = json.load(f)
        except (OSError, ValueError, RecursionError):   # json recurses on nesting
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

saved="$HOME/.local/bin/claude-saved"
if [ -n "${TMUX_PANE:-}" ] && [ -x "$saved" ]; then
  printf '%s' "$input" | timeout 3 "$saved" hook >/dev/null 2>&1
fi
exit 0
