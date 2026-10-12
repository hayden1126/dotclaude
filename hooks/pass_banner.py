"""pass-banner: show what Claude said in the last turn, once, as the banner of the session a /pass
respawn started.

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
MAX_LINES, MAX_BYTES = 40, 4096   # the whole banner, head and tail included (spike A2: 3.6 KiB)
HEAD_ONE, HEAD_MANY = "Last reply before the pass:\n", "Last turn's replies:\n"
POPUP = "~/.local/bin/pass-last"  # setup-tmux.sh links it; Ctrl-b P runs it
ELLIPSIS = chr(0x2026)
# C0 controls but tab and newline, DEL and C1: an escape sequence in a reply stays out of the
# terminal.
CONTROL = re.compile("[%s]" % re.escape("".join(map(chr, [*range(0, 9), *range(11, 32),
                                                          *range(127, 160)]))))


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
    """text without control characters, as valid UTF-8 (a lone surrogate becomes '?')."""
    text = text.encode("utf-8", "replace").decode("utf-8")
    return CONTROL.sub("", text.replace("\r\n", "\n"))


def size(text: str) -> int:
    return len(text.encode("utf-8"))


def tail(left: int, where: str) -> str:
    """The line after a cut banner: Ctrl-b P where setup-tmux.sh installed the popup, else the
    file (where) that holds every reply."""
    more = "%s %d more line%s" % (ELLIPSIS, left, "" if left == 1 else "s")
    if os.path.exists(os.path.expanduser(POPUP)):
        return more + ": Ctrl-b P shows the whole reply"
    return "%s in %s" % (more, where)


def newest_group(replies) -> list[str]:
    """The texts of the last turn, oldest first: the run of valid replies at the end that share
    the newest one's prompt_id (a Stop a hook blocks and the Stop ending the continued turn share
    one, spike A5). tmux/pass-last splits turns the same way, by runs."""
    valid = [r for r in replies if isinstance(r, dict) and isinstance(r.get("prompt_id"), str)
             and isinstance(r.get("text"), str) and r["text"].strip()] \
        if isinstance(replies, list) else []
    run = []
    for r in reversed(valid):
        if run and r["prompt_id"] != run[-1]["prompt_id"]:
            break
        run.append(r)
    return [r["text"] for r in reversed(run)]


def banner(texts: list[str], where: str = "") -> str:
    """The banner: a head, then the texts with a blank line between, whole when they fit in
    MAX_LINES lines and MAX_BYTES bytes (head included). Otherwise as many lines as fit with
    the tail ("N more lines: Ctrl-b P ...", or the file where) also inside MAX_BYTES. A first line longer than
    that is cut on a character boundary and counts as left."""
    head = HEAD_ONE if len(texts) == 1 else HEAD_MANY
    lines = "\n\n".join(clean(t).strip() for t in texts).split("\n")
    whole = head + "\n".join(lines)
    if len(lines) <= MAX_LINES and size(whole) <= MAX_BYTES:
        return whole
    budget = MAX_BYTES - size(head) - size("\n" + tail(len(lines), where))  # longest form
    out, used, cut = [], 0, False
    for line in lines:
        if len(out) == MAX_LINES:
            break
        need = size(line) + (1 if out else 0)
        if used + need > budget:
            if not out:
                out.append(line.encode("utf-8")[:budget].decode("utf-8", "ignore"))
                cut = True
            break
        out.append(line)
        used += need
    return head + "\n".join(out) + "\n" + tail(len(lines) - len(out) + cut, where)


def load(path: str):
    try:
        with open(path, encoding="utf-8") as f:
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
        d = json.load(sys.stdin.buffer)
    except Exception:
        return
    if (not isinstance(d, dict) or d.get("agent_id") or d.get("source") != "startup"
            or d.get("hook_event_name") != "SessionStart"):
        return
    path = entry_path(pane)
    entry = load(path)
    if not isinstance(entry, dict) or entry.get("shown") is not False:
        return
    texts = newest_group(entry.get("replies"))
    if not texts or not fresh(entry.get("written_at")):
        return
    tab = current_tab(pane)
    if tab is None or entry.get("tab") != tab:
        return
    sys.stdout.write(json.dumps({"systemMessage": banner(texts, path)}))
    sys.stdout.flush()
    entry["shown"] = True
    try:
        write(path, entry)
    except OSError:
        pass


if __name__ == "__main__":
    main()
