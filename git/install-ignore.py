#!/usr/bin/env python3
"""install-ignore.py: keep git/sandbox-stubs.ignore current in the global git excludes file.

The excludes file isn't ours alone: Claude Code appends its own lines to it, and so may you.
So the repo owns only the block between the two markers below. Each run replaces that block
(or appends it if absent) and leaves every other line alone.

Usage: install-ignore.py BLOCK [DEST]
  DEST defaults to `git config --global core.excludesFile` when set, else
  $XDG_CONFIG_HOME/git/ignore (~/.config/git/ignore), git's own default.
Idempotent: a second run changes nothing.
"""
import os
import subprocess
import sys

BEGIN = "# >>> dotclaude sandbox stubs (managed by dotclaude/git/install-ignore.py)"
END = "# <<< dotclaude sandbox stubs"


def default_dest():
    try:
        out = subprocess.run(["git", "config", "--global", "--get", "core.excludesFile"],
                             capture_output=True, text=True).stdout.strip()
    except OSError:
        out = ""
    if out:
        return os.path.expanduser(out)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "git", "ignore")


def upsert(text, block):
    managed = f"{BEGIN}\n{block.rstrip()}\n{END}\n"
    lines = text.splitlines(keepends=True)
    starts = [i for i, l in enumerate(lines) if l.rstrip("\n") == BEGIN]
    if starts:
        i = starts[0]
        j = next((k for k in range(i, len(lines)) if lines[k].rstrip("\n") == END), None)
        if j is None:
            raise ValueError(f"'{BEGIN}' has no matching '{END}'")
        return "".join(lines[:i]) + managed + "".join(lines[j + 1:])
    if text and not text.endswith("\n"):
        text += "\n"
    return text + ("\n" if text else "") + managed


def main(argv):
    if len(argv) not in (2, 3):
        sys.stderr.write(__doc__)
        return 2
    with open(argv[1]) as f:
        block = f.read()
    dest = argv[2] if len(argv) == 3 else default_dest()
    old = open(dest).read() if os.path.exists(dest) else ""
    try:
        new = upsert(old, block)
    except ValueError as e:
        sys.stderr.write(f"install-ignore: {dest}: {e}; left unchanged\n")
        return 1
    if new == old:
        print(f"==> {dest}: sandbox stub block already current")
        return 0
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w") as f:
        f.write(new)
    print(f"==> {dest}: sandbox stub block installed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
