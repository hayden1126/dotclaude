"""pass-banner: show the reply a /pass respawn left behind, once, as the new session's banner.

hooks/pass-banner.sh runs this file with python3 -I, passing the SessionStart event on stdin; the
rules are in that shim's header. Tests import banner() and run the shim
(tests/setup/test_pass_banner.py). Stdlib only; keep the source ASCII.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

TTL = 120                      # seconds: a startup later than this isn't the respawn
MAX_LINES, MAX_BYTES = 40, 4096
HEAD = "Last reply before the pass:\n"
ELLIPSIS = chr(0x2026)
# C0 controls but tab and newline, and DEL: an escape sequence in a reply stays out of the
# terminal.
CONTROL = re.compile("[%s]" % re.escape("".join(map(chr, [*range(0, 9), *range(11, 32), 127]))))


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "dotclaude")


def entry_path(pane: str) -> str:
    return os.path.join(state_dir(), "pass-last", pane[1:] + ".json")


def current_tab(pane: str) -> dict | None:
    """This pane on its tmux server, as pass-respawn's pane_tab keys it, or None."""
    try:
        p = subprocess.run(["tmux", "display", "-p", "-t", pane,
                            "#{start_time} #{pid} #{socket_path}"],
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    parts = p.stdout.rstrip("\n").split(" ", 2) if p.returncode == 0 else []
    if len(parts) != 3 or not (parts[0].isdigit() and parts[1].isdigit()) or not parts[2]:
        return None
    return {"socket": parts[2], "server_start": int(parts[0]), "server_pid": int(parts[1]),
            "pane": pane}


def clean(text: str) -> str:
    return CONTROL.sub("", text.replace("\r\n", "\n"))


def banner(message: str) -> str:
    """The banner text: the head, then the message up to MAX_LINES lines or MAX_BYTES bytes,
    whichever comes first, then how many lines are left. A first line longer than MAX_BYTES is
    cut on a character boundary and counts as left."""
    lines = message.rstrip().split("\n")
    out, used, cut = [], 0, False
    for line in lines:
        if len(out) == MAX_LINES:
            break
        size = len(line.encode("utf-8", "replace")) + 1
        if used + size > MAX_BYTES:
            if not out:
                out.append(line.encode("utf-8", "replace")[:MAX_BYTES].decode("utf-8", "ignore"))
                cut = True
            break
        out.append(line)
        used += size
    left = len(lines) - len(out) + cut
    text = HEAD + "\n".join(out)
    if left:
        text += "\n%s %d more line%s: Ctrl-b P shows the whole reply" % (
            ELLIPSIS, left, "" if left == 1 else "s")
    return text


def load(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write(path: str, obj) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def fresh(written) -> bool:
    return (isinstance(written, (int, float)) and not isinstance(written, bool)
            and 0 <= time.time() - written < TTL)


def main() -> None:
    if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0":
        return
    pane = os.environ.get("TMUX_PANE", "")
    if not re.fullmatch(r"%\d+", pane):
        return
    try:
        d = json.load(sys.stdin)
    except Exception:
        return
    if (not isinstance(d, dict) or d.get("agent_id") or d.get("source") != "startup"
            or d.get("hook_event_name") != "SessionStart"):
        return
    path = entry_path(pane)
    entry = load(path)
    if not isinstance(entry, dict) or entry.get("shown") is not False:
        return
    message = entry.get("message")
    if not isinstance(message, str) or not message.strip() or not fresh(entry.get("written_at")):
        return
    tab = current_tab(pane)
    if tab is None or entry.get("tab") != tab:
        return
    sys.stdout.write(json.dumps({"systemMessage": banner(clean(message))}))
    sys.stdout.flush()
    entry["shown"] = True
    try:
        write(path, entry)
    except OSError:
        pass


if __name__ == "__main__":
    main()
