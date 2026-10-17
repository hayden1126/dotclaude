"""SessionStart hook that keeps Bash off the display in an opted repo; hooks/blank-display.sh
runs it.

A repo opts in with `git config dotclaude.blankDisplay true`. The hook reads that key with
`--local`, which in a linked worktree reads the common dir's config, so every worktree of the
repo is covered, including ones added later; global and system config never opt a repo in. The
payload's cwd decides: git runs with no GIT_* var from the hook's env, and only stdout `true`
opts in (unset, false, not a repo, an error or a timeout all do nothing).

Opted in, the hook appends three lines to $CLAUDE_ENV_FILE, which Claude Code sources before each
Bash command, and tells the model why. DISPLAY and WAYLAND_DISPLAY are set empty, not unset: an
unset var can fall back to a default socket (libwayland connects to $XDG_RUNTIME_DIR/wayland-0
when WAYLAND_DISPLAY is unset), while an empty one names no display at all.
Subagent payloads (agent_id) blank too, the safe direction. A settings `env` entry is not the
way to do this: Claude Code's own image paste runs xclip and wl-paste with that env.

Anything odd (a bad payload, no env file, a git timeout) is logged to
$XDG_STATE_HOME/dotclaude/blank-display.log and prints nothing (fail open).
"""
import json
import os
import subprocess
import sys
import time

GIT_WAIT = 2.0
KEY = "dotclaude.blankDisplay"
LINES = b"export DISPLAY=\nexport WAYLAND_DISPLAY=\nunset WAYLAND_SOCKET\n"
CONTEXT = ("No display for Bash in this repo (git config dotclaude.blankDisplay): DISPLAY and "
           "WAYLAND_DISPLAY are empty. Don't set DISPLAY=:0. For a visible browser, run "
           "chrome-bg run -- <cmd> with the sandbox off.")


def log(line):
    try:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "blank-display.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def opted_in(cwd: str) -> bool:
    """True only when the repo holding cwd sets the key true in its own config."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        p = subprocess.run(["git", "-C", cwd, "config", "--local", "--type=bool", "--get", KEY],
                           stdin=subprocess.DEVNULL, capture_output=True, env=env,
                           timeout=GIT_WAIT)
    except subprocess.TimeoutExpired:
        log(f"git config timeout after {GIT_WAIT:g}s cwd={cwd}")
        return False
    except OSError as e:
        log(f"git config failed {type(e).__name__}: {e}")
        return False
    return p.returncode == 0 and p.stdout == b"true\n"


def append_lines(path: str) -> None:
    """Append LINES, ending another hook's unterminated last line first so ours stay whole."""
    with open(path, "ab+") as f:
        if f.seek(0, os.SEEK_END):
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write(LINES)


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError as e:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        log(f"bad payload {type(e).__name__}: {e}")
        return
    if not isinstance(event, dict):
        log(f"bad payload: a {type(event).__name__}, not an object")
        return
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not os.path.isdir(cwd):
        log(f"no usable cwd: {cwd!r}")
        return
    if not opted_in(cwd):
        return
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        log(f"opted in but CLAUDE_ENV_FILE is unset or empty, display left as is: cwd={cwd}")
        return
    append_lines(env_file)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "additionalContext": CONTEXT}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a broken hook must never break a session
        log(f"error {type(e).__name__}: {e}")
