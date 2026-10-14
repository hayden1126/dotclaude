"""A stand-in for tmux in tests/setup/test_tmux_hooks.py (stdlib only).

It appends each call to $STUB_LOG as "tmux <args>", prints $STUB_PANES for list-panes, and keeps
window options in the JSON file $STUB_TMUX_STATE, keyed by the -t target as given (the tests
show one pane per window). set-option, show-option and the ';' separator work, and -F expands
the format subset the hooks use: #{@option}, #{?cond,a,b}, #{==:a,b} and #{s/re/repl/:@option}.
A call holds a lock on the state file throughout, as tmux runs one client's commands at a time.
The real-tmux test in test_tmux_hooks.py runs the same sequences on a tmux server, so a
divergence from tmux 3.7c fails there.
"""
import fcntl
import json
import os
import re
import sys


def split_top(text: str) -> list:
    """text split at the commas outside any #{...}."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(text):
        if text.startswith("#{", i):
            depth += 1
            cur += "#{"
            i += 2
            continue
        c = text[i]
        if c == "}" and depth:
            depth -= 1
        elif c == "," and not depth:
            parts.append(cur)
            cur = ""
            i += 1
            continue
        cur += c
        i += 1
    return parts + [cur]


def expand(text: str, opts: dict) -> str:
    out, i = "", 0
    while i < len(text):
        if not text.startswith("#{", i):
            out += text[i]
            i += 1
            continue
        depth, j = 1, i + 2
        while j < len(text) and depth:
            if text.startswith("#{", j):
                depth += 1
                j += 2
                continue
            if text[j] == "}":
                depth -= 1
            j += 1
        out += item(text[i + 2:j - 1], opts)
        i = j
    return out


def item(body: str, opts: dict) -> str:
    if body.startswith("?"):
        cond, a, b = split_top(body[1:])
        c = expand(cond, opts)
        return expand(a if c and c != "0" else b, opts)
    if body.startswith("==:"):
        a, b = split_top(body[3:])
        return "1" if expand(a, opts) == expand(b, opts) else "0"
    if body.startswith("s/"):
        pat, repl, var = re.fullmatch(r"s/([^/]*)/([^/]*)/:(.*)", body, re.S).groups()
        if ":" in pat + repl:  # tmux ends the modifier at the first colon: it would misparse
            raise SystemExit("fake tmux: a colon in #{%s}" % body)
        return re.sub(pat, repl, item(var, opts))
    if body.startswith("@"):
        return opts.get(body, "")
    raise SystemExit("fake tmux: unsupported format #{%s}" % body)


def run(cmd: list, windows: dict) -> None:
    if not cmd:
        return
    name, rest = cmd[0], cmd[1:]
    if name == "list-panes":
        print(os.environ.get("STUB_PANES", ""))
        return
    if name not in ("set-option", "set", "show-option", "show"):
        return
    flags, target, words, i = "", "", [], 0
    while i < len(rest):
        if rest[i] == "-t":
            target = rest[i + 1]
            i += 2
        elif rest[i].startswith("-") and not words:
            flags += rest[i][1:]
            i += 1
        else:
            words.append(rest[i])
            i += 1
    opts = windows.setdefault(target, {})
    if name in ("show-option", "show"):
        print(opts.get(words[0], ""))
    elif "u" in flags:
        opts.pop(words[0], None)
    else:
        opts[words[0]] = expand(words[1], opts) if "F" in flags else words[1]


def main() -> None:
    args = sys.argv[1:]
    with open(os.environ["STUB_LOG"], "a") as f:
        f.write("tmux " + " ".join(args) + "\n")
    path = os.environ.get("STUB_TMUX_STATE")
    if not path:
        return
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        windows = json.loads(f.read() or "{}")
        cmd = []
        for a in args + [";"]:
            if a == ";":
                run(cmd, windows)
                cmd = []
            else:
                cmd.append(a)
        f.seek(0)
        f.truncate()
        f.write(json.dumps(windows))


if __name__ == "__main__":
    main()
