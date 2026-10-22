#!/usr/bin/env python3
"""Save a delegated reader's report to a private file (12-retro step 3).

  save_handback.py OUT_DIR NAME=OUTPUT_FILE...

A `researcher` or `reviewer` has no write tool: it hands its report back through a
`SubagentHandback` tool call, and Claude Code keeps that call in the agent's output file (one JSON
record per line, the path its spawn prints). For each NAME=OUTPUT_FILE, this writes
OUT_DIR/NAME.md from the last such call that wasn't refused (its result an error): its longest
string field, the report. The main session
never retypes a report, and its text never passes through the conversation.

A retro's reports quote the student, so OUT_DIR must stay private: the script refuses one inside
a git work tree (its symlinks resolved), sets it to mode 0700, and writes each report to a new
0600 file it then renames into place, so a link planted at a report's path is replaced, never
written through. NAME is a plain file name (letters, digits, `.`, `_`, `-`),
each given once. It prints one line per report, its name and size, never its text. Exit 0; 1 when
an output file can't be read, holds no handback, or its report can't be written (the others are
still saved); 2 on bad usage or a refused or unusable OUT_DIR. Stdlib only."""
import json
import os
import re
import sys

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def last_handback(path):
    """The input of the last SubagentHandback call in an agent's output file whose result wasn't
    an error (a hook refused it), or None."""
    calls = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                rec = json.loads(raw)
            except (ValueError, RecursionError):
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if (b.get("type") == "tool_use" and b.get("name") == "SubagentHandback"
                        and isinstance(b.get("input"), dict)):
                    calls.append((str(b.get("id")), b["input"]))
                elif b.get("type") == "tool_result" and b.get("is_error"):
                    calls = [c for c in calls if c[0] != str(b.get("tool_use_id"))]
    return calls[-1][1] if calls else None


def in_work_tree(path):
    """True when path, or the nearest existing directory above it, is inside a git work tree."""
    d = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def write_private(path, text):
    """Write text to a new 0600 file beside path, then rename it over path: a link planted at
    path is replaced, never written through, and a failed write leaves path as it was."""
    tmp = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with open(fd, "w", encoding="utf-8", errors="replace") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2 or args[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    out_dir, pairs = args[0], []
    for pair in args[1:]:
        name, sep, path = pair.partition("=")
        if not sep or not NAME.match(name) or not path:
            print(f"save_handback: {pair!r} isn't NAME=OUTPUT_FILE with a plain NAME", file=sys.stderr)
            return 2
        if name in dict(pairs):
            print(f"save_handback: {name} is given twice", file=sys.stderr)
            return 2
        pairs.append((name, path))
    if in_work_tree(out_dir):
        print(f"save_handback: {out_dir} is inside a git work tree; reports quote the student, so "
              f"they go to a private directory", file=sys.stderr)
        return 2
    try:
        os.makedirs(out_dir, mode=0o700, exist_ok=True)
        os.chmod(out_dir, 0o700)
    except OSError as e:
        print(f"save_handback: {out_dir}: {e.strerror}", file=sys.stderr)
        return 2
    status = 0
    for name, path in pairs:
        try:
            inp = last_handback(path)
        except OSError as e:
            print(f"{name}: {path}: {e.strerror}", file=sys.stderr)
            status = 1
            continue
        text = max((v for v in (inp or {}).values() if isinstance(v, str)), key=len, default="")
        if not text:
            print(f"{name}: no SubagentHandback report in {path}", file=sys.stderr)
            status = 1
            continue
        try:
            write_private(os.path.join(out_dir, name + ".md"), text)
        except OSError as e:
            print(f"{name}: {name}.md: {e.strerror}", file=sys.stderr)
            status = 1
            continue
        print(f"{name}: {len(text)} chars")
    return status


if __name__ == "__main__":
    sys.exit(main())
