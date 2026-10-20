"""A throwaway lanes repo for tests: a bare origin, a clone as the main checkout, `lane init`.

No network: origin is a local bare repo, and a fake `gh` that fails sits first on PATH, so PR
state is the degraded `?` and `done` falls back to git; it answers `new`'s used-name check with
no PR. A fake `claude` sits there too, for
`lane open`, and TMUX is unset (a test that opens a window sets it and stubs tmux). HOME,
XDG_STATE_HOME, TMUX_TMPDIR and the Claude session variables point into the temp dir, so nothing
reads or writes the real machine's state.
"""
import glob
import itertools
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LANE = os.path.join(REPO, "skills", "lanes", "scripts", "lane")
HANDOFF_CHECK = os.path.join(REPO, "skills", "handoff", "scripts", "handoff-check")
HOOKS = os.path.join(REPO, "hooks")
sys.path.insert(0, os.path.join(REPO, "skills", "lanes", "scripts"))
import lanelib  # noqa: E402  (on sys.path from the line above)


class LanesRepo(unittest.TestCase):
    """self.main is the main checkout of a lanes repo whose lanes live under self.root."""

    init_lanes = True

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        fake_bin = os.path.join(self.tmp, "bin")
        os.makedirs(os.path.join(self.home, ".claude", "sessions"))
        os.makedirs(fake_bin)
        with open(os.path.join(fake_bin, "gh"), "w") as f:
            # `new`'s check (`pr list --head <b> --state all`) gets FAKE_GH_NEW, `[]` when unset
            # (no PR used the name) and a failure when `fail`. A branch's merged PRs
            # (`--head <b> --state merged`) get FAKE_GH_MERGED the same way, when it is set.
            # FAKE_GH_OUT, when set, is printed as the reply to any other call (a test's canned
            # JSON). FAKE_GH_LOG, when set, gets each call's args, one line per call.
            f.write('#!/bin/sh\n'
                    'if [ -n "$FAKE_GH_LOG" ]; then echo "$*" >> "$FAKE_GH_LOG"; fi\n'
                    'case " $* " in *" --head "*" --state all "*)\n'
                    '  if [ "$FAKE_GH_NEW" = fail ]; then echo "gh: offline in tests" >&2; exit 1; fi\n'
                    '  printf "%s" "${FAKE_GH_NEW:-[]}"; exit 0;;\n'
                    '*" --head "*" --state merged "*)\n'
                    '  if [ "$FAKE_GH_MERGED" = fail ]; then echo "gh: offline in tests" >&2; exit 1; fi\n'
                    '  if [ -n "$FAKE_GH_MERGED" ]; then printf "%s" "$FAKE_GH_MERGED"; exit 0; fi;;\n'
                    'esac\n'
                    'if [ -n "$FAKE_GH_OUT" ]; then printf "%s" "$FAKE_GH_OUT"; exit 0; fi\n'
                    "echo 'gh: offline in tests' >&2\nexit 1\n")
        os.chmod(os.path.join(fake_bin, "gh"), 0o755)
        with open(os.path.join(fake_bin, "claude"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(fake_bin, "claude"), 0o755)
        self.fake_bin = fake_bin
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "GIT_DIR", "GIT_WORK_TREE", "SANDBOX_RUNTIME",
                                             "TMUX"))}
        self.env.update(HOME=self.home, XDG_STATE_HOME=os.path.join(self.tmp, "state"),
                        TMUX_TMPDIR=self.tmp,  # a tmux a test starts never finds the real server
                        PATH=fake_bin + os.pathsep + os.environ["PATH"],
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com",
                        GIT_CONFIG_NOSYSTEM="1",
                        # The excluded-command guard `new` and `done` load reads managed
                        # settings from here, never the machine's /etc/claude-code.
                        EXCLUDED_GUARD_MANAGED_DIR=os.path.join(self.tmp, "managed"),
                        # The suite may itself run in the Bash sandbox, whose pid 1 the CLI
                        # would read as sandboxed; its processes share one namespace, so `done`'s
                        # process check still sees them. A test hook, not a user setting.
                        _LANE_TEST_SANDBOXED="0")
        # In-process calls (a loaded `lane` script, lanelib) find the config by this too.
        env_patch = mock.patch.dict(os.environ, XDG_STATE_HOME=self.env["XDG_STATE_HOME"])
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.origin = os.path.join(self.tmp, "origin.git")
        self.main = os.path.join(self.tmp, "proj")
        self.root = os.path.join(self.tmp, "proj-lanes")
        self.git("init", "-q", "--bare", "-b", "main", self.origin, cwd=self.tmp)
        self.git("clone", "-q", self.origin, self.main, cwd=self.tmp)
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.commit("README.md", "hello\n")
        self.git("push", "-q", "origin", "main")
        self.common = os.path.join(self.main, ".git")
        if self.init_lanes:
            self.lane("init", "--root", self.root, "--ports", "5191-5199", "--cap", "8")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.main, env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def commit(self, name, text, cwd=None, msg=None):
        cwd = cwd or self.main
        with open(os.path.join(cwd, name), "w") as f:
            f.write(text)
        self.git("add", name, cwd=cwd)
        self.git("commit", "-q", "-m", msg or f"add {name}", cwd=cwd)

    def run_lane(self, *args, cwd=None):
        return subprocess.run([sys.executable, LANE, *args], cwd=cwd or self.main, env=self.env,
                              capture_output=True, text=True, timeout=60)

    def lane(self, *args, cwd=None):
        p = self.run_lane(*args, cwd=cwd)
        self.assertEqual(p.returncode, 0, f"lane {' '.join(args)}: {p.stdout}{p.stderr}")
        return p.stdout

    def lane_path(self, lane_id):
        return os.path.join(self.root, lane_id)

    def record(self, lane_id):
        return os.path.join(self.lane_path(lane_id), ".lane", "STATUS.md")

    def lane_json(self, lane_id):
        with open(os.path.join(self.common, "lanes", lane_id, "lane.json")) as f:
            return json.load(f)

    def config_files(self):
        """The lanes configs `lane init` wrote: they live in the state dir, out of the repo,
        beside the lead records (<repo>-<hash>.lead.json), which this leaves out."""
        d = os.path.join(self.tmp, "state", "dotclaude", "lanes")
        return sorted(glob.glob(os.path.join(d, "*.toml")))

    @property
    def lead_path(self):
        """This repo's lead record (lanelib.Repo.lead_path)."""
        return lanelib.Repo(self.main, self.common).lead_path

    def lead(self):
        """The lead record as written, or None."""
        return json.loads(self.read(self.lead_path)) if os.path.exists(self.lead_path) else None

    def hook(self, script, payload):
        p = subprocess.run(["bash", os.path.join(HOOKS, script)], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None

    def stop(self, pid):
        """Stop pid as Ctrl+Z does (SIGSTOP) and wait until /proc says so. Cleanup continues it
        while its pid still names it, ahead of the cleanup that ends it."""
        start = lanelib.proc_start(pid)
        os.kill(pid, signal.SIGSTOP)
        self.addCleanup(lambda: lanelib.proc_start(pid) == start
                        and os.kill(pid, signal.SIGCONT))
        self.wait_stopped(pid, True)

    def cont(self, pid):
        """Continue a stopped pid (SIGCONT, as `fg` sends) and wait until it runs."""
        os.kill(pid, signal.SIGCONT)
        self.wait_stopped(pid, False)

    def wait_stopped(self, pid, stopped):
        deadline = time.monotonic() + 10
        while ((lanelib.proc_stat(pid) or ("", ""))[1] in lanelib.STOPPED) != stopped:
            if time.monotonic() > deadline:
                self.fail(f"{pid} never {'stopped' if stopped else 'continued'}")
            time.sleep(0.01)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()


class LiveSessions(LanesRepo):
    """Live sessions for `lane addr` and the board's main-checkout footer. A live session is a
    session file whose pid runs with the procStart the file records (a child `sleep`, started
    in the session's launch dir) and whose messagingSocketPath is a socket on disk (made with
    mknod, which the Bash sandbox allows where socket() is refused). Each child runs with this
    test's own TMUX and TMUX_PANE, never the runner's (lanelib.proc_tmux reads them from its
    environment): TMUX names a stand-in server, another `sleep`, and each child gets a pane of
    its own unless told one."""

    def setUp(self):
        super().setUp()
        self.socks = os.path.join(self.tmp, "socks")
        os.makedirs(self.socks)
        self.panes = itertools.count(1)
        self.server = self.tmux_server()

    def spawn(self, argv, cwd=None, env=None, wait=False):
        """A child, killed at cleanup: exited and reaped (wait), or running with its environment
        in place. Popen returns once a vfork child execs, a moment before the kernel has set up
        the new image's environment, and /proc/<pid>/environ reads empty until then."""
        p = subprocess.Popen(argv, cwd=cwd, env=env if env is not None else self.env)
        self.addCleanup(lambda: p.poll() is None and (p.kill(), p.wait()))
        if wait:
            p.wait()
            return p.pid
        deadline = time.monotonic() + 10
        while not lanelib.read_head(f"/proc/{p.pid}/environ", 1) and time.monotonic() < deadline:
            time.sleep(0.005)
        return p.pid

    def tmux_server(self, name="default"):
        """A stand-in tmux server (a running child) and the TMUX value naming it."""
        pid = self.spawn(["sleep", "60"], cwd=self.tmp)
        return f"{os.path.join(self.tmp, 'tmux-sock', name)},{pid},0"

    def child(self, cwd=None, done=False, pane="new", server=None):
        """A process in cwd: running (`sleep`), or exited and reaped (done). pane "new" gives
        it a pane of its own on server (this test's by default), a "%N" string that pane, None
        no tmux at all."""
        env = dict(self.env)
        if pane is not None:
            env.update(TMUX=server or self.server,
                       TMUX_PANE=f"%{next(self.panes)}" if pane == "new" else pane)
        return self.spawn(["sleep", "60"] if not done else ["true"], cwd=cwd, env=env, wait=done)

    def session(self, at, pid=None, start=None, skew=0, sock="socket", path=None, pane="new",
                server=None, **extra):
        """A session file for pid (by default a fresh child running in at, the launch dir, on
        pane and server) whose cwd field is at unless extra overrides it. sock: "socket" makes
        one at path (by default under self.socks), "file" a regular file there, None leaves it
        missing. skew shifts the recorded procStart off the real one: the pid, reused."""
        os.makedirs(at, exist_ok=True)
        pid = pid or self.child(at, pane=pane, server=server)
        if start is None:
            start = (lanelib.proc_start(pid) or 1) + skew
        path = path or os.path.join(self.socks, f"{pid}.sock")
        if sock == "socket":
            os.mknod(path, stat.S_IFSOCK | 0o600)
        elif sock == "file":
            self.write(path, "")
        self.write(os.path.join(self.home, ".claude", "sessions", f"{pid}.json"),
                   json.dumps({"pid": pid, "procStart": str(start), "sessionId": f"s-{pid}",
                               "kind": "interactive", "cwd": at, "tmux": f"proj:@{pid}.%{pid}",
                               "status": "idle", "messagingSocketPath": path, **extra}))
        return "uds:" + path

    def write_lead(self, pid, start=None, sid=None, tmux=None, **extra):
        """A lead record naming pid (with its real start unless given) and tmux, as the CLI
        writes one."""
        rec = {"pid": pid, "procStart": lanelib.proc_start(pid) if start is None else start,
               "sessionId": sid or f"s-{pid}", "tmux": tmux, "at": "2026-10-14T21:05:00+00:00",
               **extra}
        self.write(self.lead_path, json.dumps(rec))

    def tmux_of(self, pane, server=None):
        """The record's tmux list for pane on server (this test's by default)."""
        sock, pid, _ = (server or self.server).rsplit(",", 2)
        return [sock, int(pid), lanelib.proc_start(int(pid)), pane]
