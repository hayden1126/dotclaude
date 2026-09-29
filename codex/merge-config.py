#!/usr/bin/env python3
"""merge-config.py — apply dotclaude's managed keys to ~/.codex/config.toml.

Codex treats its config.toml as runtime state: it appends a [projects."<path>"]
trust entry for every directory you trust, and other installers register
[mcp_servers.*] there. A symlink into this repo pushes all of that into git (the
same reason setup.sh copies settings.json instead of linking it). So the repo
owns only the top-level keys in codex/config.toml; this script upserts them into
a real local file and leaves every table Codex, or anything else, wrote alone.

Usage: merge-config.py [BASELINE] [DEST]
  BASELINE defaults to config.toml beside this script.
  DEST defaults to $CODEX_HOME/config.toml, else ~/.codex/config.toml.

Idempotent. A DEST that is a symlink to BASELINE (the old setup) becomes a
regular file holding the link's current content, so no local state is lost; a
symlink anywhere else is followed and its target merged in place. Managed values
must be single-line TOML. The merge is checked with tomllib (Python 3.11+):
managed keys must equal the baseline and everything else must be unchanged, or
nothing is written.
"""
import os
import re
import shutil
import stat
import sys
import tempfile
import time

HEADER = ("# Managed keys, re-applied by dotclaude/codex/merge-config.py. "
          "Codex owns the rest of this file.\n")
KEY_RE = re.compile(r'^\s*([A-Za-z0-9_-]+|"[^"]*")\s*=')
TABLE_RE = re.compile(r'^\s*\[')

try:
    import tomllib
except ImportError:  # Python < 3.11: merge still runs, unverified
    tomllib = None


def say(msg):
    print(f"\033[1;36m==>\033[0m {msg}")


def warn(msg):
    print(f"\033[1;33m!!\033[0m  {msg}", file=sys.stderr)


def top_level_end(lines):
    """Index of the first table header: top-level keys may only appear before it."""
    return next((i for i, l in enumerate(lines) if TABLE_RE.match(l)), len(lines))


def key_at(line):
    m = KEY_RE.match(line)
    return m.group(1) if m else None


def managed_keys(baseline_lines):
    keys = []
    for line in baseline_lines[:top_level_end(baseline_lines)]:
        key = key_at(line)
        if key:
            keys.append((key, line.rstrip("\n") + "\n"))
    return keys


def merge(lines, managed):
    """Replace each managed key's top-level line in place, else insert it under
    HEADER at the top of the file. Returns (lines, added, updated)."""
    lines = list(lines)
    end = top_level_end(lines)
    missing, updated = [], 0
    for key, new in managed:
        idx = next((i for i in range(end) if key_at(lines[i]) == key), None)
        if idx is None:
            missing.append(new)
        elif lines[idx].rstrip("\n") != new.rstrip("\n"):
            lines[idx] = new
            updated += 1
    if missing:
        if HEADER in lines:
            at = lines.index(HEADER) + 1
            lines[at:at] = missing
        else:
            block = [HEADER] + missing + (["\n"] if lines else [])
            lines[0:0] = block
    return lines, len(missing), updated


def verify(old_text, new_text, managed):
    """Raise ValueError unless the merge did exactly its job."""
    if tomllib is None:
        warn("python < 3.11 (no tomllib): merged config written unverified")
        return
    want = {}
    for key, line in managed:
        try:
            want.update(tomllib.loads(line))
        except tomllib.TOMLDecodeError:
            raise ValueError(f"baseline key {key} is not single-line TOML")
    try:
        old = tomllib.loads(old_text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"existing config does not parse ({e})")
    try:
        new = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError:
        raise ValueError("merge would break the file (a managed key spans several lines "
                         "there? make it one line and re-run)")
    for k, v in want.items():
        if new.get(k) != v:
            raise ValueError(f"{k} did not merge cleanly (multi-line value in the existing file?)")
    rest = lambda d: {k: v for k, v in d.items() if k not in want}
    if rest(old) != rest(new):
        raise ValueError("merge would change unmanaged content")


def write(dest, text, mode):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(dest)),
                               prefix=".config.toml.")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, dest)  # replaces a symlink itself, never its target


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    baseline = argv[1] if len(argv) > 1 else os.path.join(here, "config.toml")
    codex_home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    dest = argv[2] if len(argv) > 2 else os.path.join(codex_home, "config.toml")

    with open(baseline) as f:
        managed = managed_keys(f.readlines())
    if not managed:
        warn(f"no top-level keys in {baseline}; nothing to merge")
        return 1

    migrating = (os.path.islink(dest)
                 and os.path.realpath(dest) == os.path.realpath(baseline))
    if os.path.islink(dest) and not migrating:
        dest = os.path.realpath(dest)  # someone else's link: merge into its target

    try:
        with open(dest) as f:
            old_text = f.read()
        mode = 0o600 if migrating else stat.S_IMODE(os.stat(dest).st_mode)
    except FileNotFoundError:
        old_text, mode = "", 0o600  # may later hold MCP env secrets: owner-only

    lines, added, updated = merge(old_text.splitlines(keepends=True), managed)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    new_text = "".join(lines)
    try:
        verify(old_text, new_text, managed)
    except ValueError as e:
        warn(f"codex config not changed: {e}")
        return 1

    if not migrating and new_text == old_text:
        say(f"{dest} already current")
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    if old_text and not migrating and new_text != old_text:
        backup = f"{dest}.pre-dotclaude-{int(time.time())}"
        shutil.copy2(dest, backup)
        say(f"backed up {dest} to {backup}")
    write(dest, new_text, mode)
    if migrating:
        say(f"replaced the {dest} symlink with a local file (its content kept)")
    say(f"codex config: {added} key(s) added, {updated} updated, "
        f"{len(managed) - added - updated} already current")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
