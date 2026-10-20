"""mute state: the device-wide mute, one flag that silences the notify ring and the Windows toast
for every Claude session on the machine.

Read by hooks/session-pane.sh's read_mute (for notify.sh and stop-ring.sh), which runs
`python3 -I mute_state.py check` only when something is at the flag's path, so an unmuted machine
starts no Python per ring. The claude-mute CLI and the tmux menu import it to flip the switches,
and the tab bar's mark (`claude-mute mark`, every 2 s per client) to read them. Each consumer
puts this file's real directory on sys.path itself, as this file does for autopass_state
(python3 -I keeps it off), which loads only on a write: it is the costly import, and reading the
flag doesn't need it. Stdlib only; keep the source ASCII. PLAN.md "Next: a device-wide mute" has
the design; tests/setup/test_mute_state.py, test_tmux_hooks.py and test_claude_mute.py the cases.

- The flag, $XDG_STATE_HOME/dotclaude/mute.json (state_dir(), the dir autopass_state.state_dir()
  names: a test holds the two equal) =
  {"sound": {"since": <epoch>, "until": <epoch> | null}, "toast": {...}}. A switch is muted while
  its key holds such an object and `until` is null (until unmuted) or still ahead of now; `since`
  is when that mute was set. Stamps are wall-clock epoch seconds (an hour's expiry doesn't mind
  the WSL clock's steps), and a bool is not a number. Unknown keys are ignored. No file, or no
  key, means not muted.
- current(now) -> (muted, note): the switches muted now, name -> {"since", "until"}, and why the
  flag couldn't be read in full: None; "unreadable" (an OSError other than a missing file, a
  dangling link, or no regular file: a directory, a FIFO); or "malformed" (not UTF-8 JSON, nested
  too deep, past MAX_BYTES, not an object, or a switch of the wrong shape). A switch that can't
  be read is not muted (redundancy over silence: a ring too many beats a silent miss), and a good
  switch beside a bad one still counts.
- mute(names, until, now) and unmute(names, now) -> the switches muted afterwards. Each holds an
  exclusive flock on mute.lock beside the flag (the menu and the CLI can race), starts from
  current() (a bad flag counts as empty: the person is setting the state now; expired entries
  drop out), applies the change, and writes the flag atomically (autopass_state.write_json), or
  removes it when nothing is left muted, which keeps the hooks' fast path. An OSError (a
  directory at the path, say) propagates. A bad name or `until` raises ValueError.
- `mute_state.py check` prints `<sound> <toast> <note>`: 1 or 0 for each switch muted now, then
  the note or `-`. It exits 0 whatever the flag holds.
"""
import contextlib
import fcntl
import json
import math
import os
import stat
import sys
import time

NAMES = ("sound", "toast")
MAX_BYTES = 64 * 1024  # a real flag is under 200 bytes
USAGE = "usage: mute_state.py check"


def state_dir() -> str:
    """autopass_state.state_dir()'s rule, kept here so a read never imports autopass_state."""
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                        "dotclaude")


def flag_path() -> str:
    return os.path.join(state_dir(), "mute.json")


def lock_path() -> str:
    return os.path.join(state_dir(), "mute.lock")


def is_number(v) -> bool:
    """A finite int or float; a bool is not a number here."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def well_formed(entry) -> bool:
    """A switch's value: {"since": <number>, "until": <number> | null}, other keys ignored."""
    return (isinstance(entry, dict) and is_number(entry.get("since")) and "until" in entry
            and (entry["until"] is None or is_number(entry["until"])))


def read_flag():
    """(data, note): the flag's top-level object, or None with the note (None when no file is
    there at all)."""
    path = flag_path()
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)  # so a FIFO can't block
    except FileNotFoundError:
        # Nothing there, or a dangling link: only the link is a flag that can't be read.
        return None, ("unreadable" if os.path.lexists(path) else None)
    except OSError:
        return None, "unreadable"
    try:
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return None, "unreadable"
            raw = f.read(MAX_BYTES + 1)
    except OSError:
        return None, "unreadable"
    if len(raw) > MAX_BYTES:
        return None, "malformed"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError; json recurses
        return None, "malformed"
    return (data, None) if isinstance(data, dict) else (None, "malformed")


def current(now=None):
    """(muted, note): the switches muted now, name -> {"since", "until"}, and None,
    "unreadable" or "malformed"."""
    now = time.time() if now is None else now  # wall clock
    data, note = read_flag()
    muted = {}
    for name in NAMES:
        if data is None or name not in data:
            continue
        entry = data[name]
        if not well_formed(entry):
            note = "malformed"
        elif entry["until"] is None or entry["until"] > now:
            muted[name] = {"since": entry["since"], "until": entry["until"]}
    return muted, note


@contextlib.contextmanager
def locked():
    """An exclusive flock on mute.lock in the state dir, held while the block runs. Nothing slow
    runs under it, so it waits as long as it takes."""
    os.makedirs(state_dir(), exist_ok=True)
    fd = os.open(lock_path(), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def store(muted: dict) -> None:
    """Write the flag, or remove it when nothing is muted."""
    if muted:
        here = os.path.dirname(os.path.realpath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import autopass_state as aps  # the write path alone pays for it
        aps.write_json(flag_path(), muted)
    else:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(flag_path())


def checked(names) -> list:
    names = list(names)
    if not names or any(n not in NAMES for n in names):
        raise ValueError("names must come from %s, got %r" % (", ".join(NAMES), names))
    return names


def mute(names, until, now=None) -> dict:
    """Mute each named switch from now until `until` (an epoch ahead of now), or until unmuted
    (None)."""
    now = time.time() if now is None else now  # wall clock
    names = checked(names)
    if until is not None and not (is_number(until) and until > now):
        raise ValueError("until must be None or an epoch ahead of now, got %r" % (until,))
    with locked():
        muted, _ = current(now)
        for name in names:
            muted[name] = {"since": now, "until": until}
        store(muted)
    return muted


def unmute(names, now=None) -> dict:
    names = checked(names)
    with locked():
        muted, _ = current(now)
        for name in names:
            muted.pop(name, None)
        store(muted)
    return muted


def check_line(now=None) -> str:
    """`<sound> <toast> <note>`, as `check` prints it."""
    muted, note = current(now)
    return "%d %d %s" % ("sound" in muted, "toast" in muted, note or "-")


def main(argv) -> int:
    if argv != ["check"]:
        print(USAGE, file=sys.stderr)
        return 2
    print(check_line())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
