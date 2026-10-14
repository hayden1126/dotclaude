"""A throwaway lanes repo for tests: a bare origin, a clone as the main checkout, `lane init`.

No network: origin is a local bare repo, and a fake `gh` that always fails sits first on PATH, so
PR state is the degraded `?` and `done` falls back to git. A fake `claude` sits there too, for
`lane open`, and TMUX is unset (a test that opens a window sets it and stubs tmux). HOME,
XDG_STATE_HOME, TMUX_TMPDIR and the Claude session variables point into the temp dir, so nothing
reads or writes the real machine's state.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LANE = os.path.join(REPO, "skills", "lanes", "scripts", "lane")
HANDOFF_CHECK = os.path.join(REPO, "skills", "handoff", "scripts", "handoff-check")
HOOKS = os.path.join(REPO, "hooks")
sys.path.insert(0, os.path.join(REPO, "skills", "lanes", "scripts"))


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
            # FAKE_GH_OUT, when set, is printed as the reply to any call (a test's canned JSON).
            f.write('#!/bin/sh\nif [ -n "$FAKE_GH_OUT" ]; then printf "%s" "$FAKE_GH_OUT"; exit 0; fi\n'
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
        """The lanes configs `lane init` wrote: they live in the state dir, out of the repo."""
        d = os.path.join(self.tmp, "state", "dotclaude", "lanes")
        return sorted(os.path.join(d, n) for n in os.listdir(d)) if os.path.isdir(d) else []

    def hook(self, script, payload):
        p = subprocess.run(["bash", os.path.join(HOOKS, script)], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()
