"""A pane-like process tree for the tab scripts' tests (stdlib only).

tmux names a pane by argv[0]'s basename of its tty's foreground process group, so a claude run by
its versioned path (~/.local/share/claude/versions/2.1.303) reads `2.1.303`. The tab scripts then
confirm it from /proc: the foreground group (field 8 of the pane process's stat) and that
group's argv[0]. This builds the same shape on a real pty: a session leader standing in for the
pane's shell, and a foreground job in its own process group, run under the argv[0] given.
"""
import os
import pty
import signal
import time


def spawn(testcase, argv0, args=("60",), exe=None, cwd=None):
    """A pty whose session leader (`sleep`, the pane's shell) has put a job in the foreground:
    exe (default argv0, a path to a link to sleep) run as argv0 + args, in cwd. Returns (pane
    pid, job pid); cleanup kills both."""
    pid, master = pty.fork()
    if pid == 0:
        try:
            job = os.fork()
            if job == 0:
                os.setpgid(0, 0)
                if cwd:
                    os.chdir(cwd)
                os.execv(exe or argv0, [argv0, *args])
            os.setpgid(job, job)
            os.tcsetpgrp(0, job)
            os.execv("/bin/sleep", ["sleep", "60"])
        finally:
            os._exit(1)
    testcase.addCleanup(os.close, master)
    testcase.addCleanup(lambda: os.waitpid(pid, 0))
    testcase.addCleanup(os.kill, pid, signal.SIGKILL)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            with open(f"/proc/{pid}/stat") as f:
                tpgid = int(f.read().rpartition(")")[2].split()[5])
            with open(f"/proc/{tpgid}/cmdline", "rb") as f:
                ready = f.read().split(b"\0")[0] == argv0.encode()
        except (OSError, ValueError):
            ready = False
        if ready and tpgid != pid:
            testcase.addCleanup(lambda: _kill(tpgid))
            return pid, tpgid
        time.sleep(0.02)
    testcase.fail("no foreground job")


def _kill(pid):
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def link(testcase_tmp, *parts):
    """A link to sleep at testcase_tmp/<parts...>, made once; returns its path."""
    path = os.path.join(testcase_tmp, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.lexists(path):
        os.symlink("/bin/sleep", path)
    return path
