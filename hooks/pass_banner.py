"""pass-banner: show what Claude said in the last turn, once, as the banner of the session a /pass
respawn started.

hooks/pass-banner.sh runs this file with python3 -I, passing the SessionStart event on stdin; the
rules are in that shim's header. Tests import banner() and run the shim
(tests/setup/test_pass_banner.py). Stdlib only; keep the source ASCII.

The replies are rendered by md_render.py, loaded by path from beside this file's real path, to
the pane's width less Claude Code's 5-column indent. Each style closes with its own reset, never
0m: Claude Code draws the banner gray, and 0m would drop the gray (PLAN.md, spike A9). Without
md_render.py the banner is the plain text.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time

TTL = 120                      # seconds: a startup later than this isn't the respawn
MAX_LINES, MAX_BYTES = 40, 4096   # the whole banner, head and tail included (spike A2: 3.6 KiB)
INDENT, PANE_WIDTH = 5, 80     # Claude Code's indent before the banner; a pane of unknown width
MIN_WIDTH = 20
PROMPT_CHARS = 100             # the banner shows the prompt's first line up to this
NO_PROMPT = "(prompt not saved)"            # the transcript was unreadable or didn't reach it
NOTICE = "(no prompt: a background notice)"  # a task notice or an agent's message started it
POPUP = "~/.local/bin/pass-last"  # setup-tmux.sh links it; Ctrl-b Up runs it
ELLIPSIS = chr(0x2026)
# C0 controls but tab and newline, DEL and C1: an escape sequence in a reply stays out of the
# terminal.
CONTROL = re.compile("[%s]" % re.escape("".join(map(chr, [*range(0, 9), *range(11, 32),
                                                          *range(127, 160)]))))


def load_renderer():
    """md_render.py from beside this file's real path, or None."""
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "md_render.py")
    try:
        spec = importlib.util.spec_from_file_location("md_render", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:  # a missing or broken renderer leaves the plain banner
        return None
    return mod


md_render = load_renderer()


def state_dir() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "dotclaude")


def entry_path(pane: str) -> str:
    return os.path.join(state_dir(), "pass-last", pane[1:] + ".json")


def current_tab(pane: str) -> tuple[dict, int] | None:
    """This pane on its tmux server, as pass-respawn's pane_tab keys it, with the pane's width
    (PANE_WIDTH when tmux gives none), or None."""
    try:
        p = subprocess.run(["tmux", "display", "-p", "-t", pane,
                            "#{start_time} #{pid} #{pane_width} #{socket_path}"],
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    parts = p.stdout.rstrip("\n").split(" ", 3) if p.returncode == 0 else []
    if len(parts) != 4 or not (parts[0].isdigit() and parts[1].isdigit()) or not parts[3]:
        return None
    width = int(parts[2]) if parts[2].isdigit() and int(parts[2]) > 0 else PANE_WIDTH
    return ({"socket": parts[3], "server_start": int(parts[0]), "server_pid": int(parts[1]),
             "pane": pane}, width)


def clean(text: str) -> str:
    """text without control characters, as valid UTF-8 (a lone surrogate becomes '?')."""
    text = text.encode("utf-8", "replace").decode("utf-8")
    return CONTROL.sub("", text.replace("\r\n", "\n"))


def size(text: str) -> int:
    return len(text.encode("utf-8"))


def tail(left: int, where: str) -> str:
    """The line after a cut banner: Ctrl-b Up where setup-tmux.sh installed the popup, else the
    file (where) that holds every reply."""
    more = "%s %d more line%s" % (ELLIPSIS, left, "" if left == 1 else "s")
    if os.path.exists(os.path.expanduser(POPUP)):
        return more + ": Ctrl-b Up shows the whole reply"
    return "%s in %s" % (more, where)


def newest_group(replies) -> list[dict]:
    """The replies of the last turn, oldest first: the run of valid replies at the end that share
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
    return list(reversed(run))


def turn_prompt(prompts, prompt_id: str):
    """What pass-respawn saved as the turn's prompt (the entry's `prompts`): (its text or None,
    whether a background notice started the turn)."""
    for p in prompts if isinstance(prompts, list) else []:
        if not isinstance(p, dict) or p.get("prompt_id") != prompt_id:
            continue
        if isinstance(p.get("text"), str) and p["text"].strip():
            return p["text"], False
        if p.get("notice") is True:
            return None, True
    return None, False


def first_line(prompt: str) -> str:
    """The prompt's first non-blank line, cut at PROMPT_CHARS, ending in an ellipsis when
    anything was left out."""
    lines = [line.strip() for line in clean(prompt).split("\n") if line.strip()]
    line = lines[0] if lines else ""
    if len(line) > PROMPT_CHARS:
        return line[:PROMPT_CHARS].rstrip() + ELLIPSIS
    return line + (ELLIPSIS if len(lines) > 1 and not line.endswith(ELLIPSIS) else "")


def paint(text: str, style: str) -> str:
    return md_render.paint(text, style, True, "own") if md_render else text


def hhmm(t) -> str:
    """t (epoch seconds) as HH:MM, or "" when it isn't a time localtime can take (a corrupt
    entry may hold NaN or 1e20)."""
    if not isinstance(t, (int, float)) or isinstance(t, bool):
        return ""
    try:
        return time.strftime("%H:%M", time.localtime(t))
    except (OverflowError, OSError, ValueError):
        return ""


def head(turn: list[dict], prompt: str | None, notice: bool = False) -> str:
    """What goes above the replies: "Last turn (HH:MM)" (bold), "You:" and the prompt's first
    line (or a dim note: a background notice started the turn, or the prompt wasn't saved),
    then a blank line."""
    t = hhmm(turn[0].get("time") if turn else None)
    stamp = " (%s)" % t if t else ""
    you = (paint("You:", "g") + " " + first_line(prompt) if prompt
           else paint("You: " + (NOTICE if notice else NO_PROMPT), "d"))
    return "%s\n%s\n\n" % (paint("Last turn" + stamp, "b"), you)


def body(texts: list[str], width: int) -> list[str]:
    """The replies as banner lines with a blank line between: each rendered on its own (so an
    unclosed fence stays in its reply) with own resets when md_render loaded, else plain."""
    if md_render is None:
        return "\n\n".join(clean(t).strip() for t in texts).split("\n")
    lines = []
    for t in texts:
        lines += ([""] if lines else []) + md_render.render(t, width, True, "own").split("\n")
    return lines


def cut_line(line: str, nbytes: int) -> str:
    """One line cut to nbytes: never inside a character or an escape, every style closed."""
    if md_render:
        return md_render.cut(line, nbytes, "own")
    return line.encode("utf-8")[:nbytes].decode("utf-8", "ignore")


def banner(turn: list[dict], prompt: str | None = None, width: int = PANE_WIDTH - INDENT,
           where: str = "", notice: bool = False) -> str:
    """The banner: the head, then the turn's replies rendered to width, whole when they fit in
    MAX_LINES lines and MAX_BYTES bytes (head and escapes included). Otherwise as many lines as
    fit with the tail ("N more lines: Ctrl-b Up ...", or the file where) also inside MAX_BYTES.
    A first line longer than that is cut and counts as left. Every rendered line closes its own
    styles, so no cut leaves one open."""
    top = head(turn, prompt, notice)
    lines = body([r["text"] for r in turn], width)
    whole = top + "\n".join(lines)
    if len(lines) <= MAX_LINES and size(whole) <= MAX_BYTES:
        return whole
    budget = MAX_BYTES - size(top) - size("\n" + tail(len(lines), where))  # longest form
    out, used, cut = [], 0, False
    for line in lines:
        if len(out) == MAX_LINES:
            break
        need = size(line) + (1 if out else 0)
        if used + need > budget:
            if not out:
                out.append(cut_line(line, budget))
                cut = True
            break
        out.append(line)
        used += need
    return top + "\n".join(out) + "\n" + tail(len(lines) - len(out) + cut, where)


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
    turn = newest_group(entry.get("replies"))
    if not turn or not fresh(entry.get("written_at")):
        return
    here = current_tab(pane)
    if here is None or entry.get("tab") != here[0]:
        return
    prompt, notice = turn_prompt(entry.get("prompts"), turn[-1]["prompt_id"])
    width = max(here[1] - INDENT, MIN_WIDTH)
    sys.stdout.write(json.dumps({"systemMessage": banner(turn, prompt, width, path, notice)}))
    sys.stdout.flush()
    entry["shown"] = True
    try:
        write(path, entry)
    except OSError:
        pass


if __name__ == "__main__":
    main()
