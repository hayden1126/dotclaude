"""The lead's tools in skills/lanes/scripts/lane: `open`, `lock`, and the board's WINDOW column and
locks footer. tmux is a stub that logs its argv; a live session is a session file whose pid is
this test process."""
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import unittest

from _fixture import LANE, LanesRepo

TMUX_STUB = """#!/bin/sh
printf '%s\\n' "tmux $*" >> "$STUB_LOG"
[ "$1" = new-window ] && echo 'proj:3 (chart-fix)'
exit 0
"""
SLEEP = [sys.executable, "-I", "-c", "import time; time.sleep(30)"]


class Lead(LanesRepo):
    def setUp(self):
        super().setUp()
        self.log = os.path.join(self.tmp, "tmux.log")
        self.env["STUB_LOG"] = self.log

    def with_tmux(self):
        """Put the tmux stub on PATH and pretend to be inside tmux."""
        self.write(os.path.join(self.fake_bin, "tmux"), TMUX_STUB)
        os.chmod(os.path.join(self.fake_bin, "tmux"), 0o755)
        self.env["TMUX"] = "/tmp/tmux-stub,1,0"

    def tmux_calls(self):
        return self.read(self.log).splitlines() if os.path.exists(self.log) else []

    def live_session(self, cwd, tmux="proj:@3.%7"):
        """A session file for a live pid (this test's own) with its cwd in the lane."""
        self.write(os.path.join(self.home, ".claude", "sessions", f"{os.getpid()}.json"),
                   json.dumps({"pid": os.getpid(), "sessionId": "s-1", "cwd": cwd,
                               "tmux": tmux}))

    def start(self, *args, cwd=None):
        """A background `lane` run, killed and reaped at cleanup."""
        p = subprocess.Popen([sys.executable, LANE, *args], cwd=cwd or self.main, env=self.env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(p.communicate)
        self.addCleanup(lambda: p.poll() is None and p.kill())
        return p

    def kill_pid_file(self, path):
        """Cleanup for a process a test command left behind, by the pid it wrote."""
        def kill():
            try:
                os.kill(int(self.read(path).strip()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        self.addCleanup(kill)

    def wait_for(self, cond, what, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not cond():
            if time.monotonic() > deadline:
                self.fail(f"timed out waiting for {what}")
            time.sleep(0.05)


class Open(Lead):
    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix")
        self.path = self.lane_path("chart-fix")

    def argv(self, *args):
        return shlex.split(self.lane("open", "chart-fix", "--print", *args))

    def test_print_shows_the_tmux_argv_with_no_tmux(self):
        argv = self.argv()
        self.assertEqual(argv[:2], ["tmux", "new-window"])
        self.assertEqual(argv[argv.index("-c") + 1], self.path)
        self.assertEqual(argv[argv.index("-n") + 1], "chart-fix")
        self.assertIn("-d", argv)
        cmd = argv[argv.index("--") + 1:]
        self.assertEqual(cmd[:3], [os.path.join(self.fake_bin, "claude"), "--permission-mode",
                                   "plan"])
        self.assertEqual(cmd[3], f"You are lane `chart-fix`. Read your lane record "
                                 f"`{self.record('chart-fix')}`, then plan the brief it holds.")
        self.assertEqual(len(cmd), 4)
        self.assertNotIn("-d", self.argv("--focus"))
        self.assertEqual(self.argv("fix the axis first")[-1], "fix the axis first")
        self.assertEqual(self.tmux_calls(), [])

    def test_outside_tmux_it_gives_the_cd_line(self):
        p = self.run_lane("open", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn(f"cd {self.path} && claude", p.stderr)
        self.assertNotIn("opened", self.lane_json("chart-fix"))

    def test_it_refuses_unknown_stale_and_setup_failed_lanes(self):
        p = self.run_lane("open", "nope", "--print")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no lane nope", p.stderr)
        self.lane("init", "--setup", "exit 1")
        self.assertEqual(self.run_lane("new", "half").returncode, 1)
        p = self.run_lane("open", "half", "--print")
        self.assertEqual(p.returncode, 1)
        self.assertIn("setup-failed", p.stderr)
        self.assertIn(f"lane adopt {self.lane_path('half')}", p.stderr)
        self.git("worktree", "remove", "--force", self.path)
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 1)
        self.assertIn("stale", p.stderr)

    def test_a_live_lane_is_refused_by_target_or_focused(self):
        self.with_tmux()
        self.live_session(os.path.join(self.path, "src"))
        p = self.run_lane("open", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn("proj:@3.%7", p.stderr)
        self.assertEqual(self.tmux_calls(), [])
        out = self.lane("open", "chart-fix", "--focus")
        self.assertIn("proj:@3", out)
        self.assertEqual(self.tmux_calls(), ["tmux select-window -t proj:@3"])
        self.assertNotIn("opened", self.lane_json("chart-fix"))

    def test_unknown_liveness_refuses_and_asks_for_a_bare_run(self):
        self.with_tmux()
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        p = self.run_lane("open", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn("bare", p.stderr)
        self.assertEqual(self.tmux_calls(), [])

    def test_open_runs_tmux_and_stamps_only_opened(self):
        self.with_tmux()
        before = self.lane_json("chart-fix")
        out = self.lane("open", "chart-fix")
        self.assertIn("opened chart-fix in tmux window proj:3 (chart-fix)", out)
        (call,) = self.tmux_calls()
        self.assertTrue(call.startswith("tmux new-window -P -F "), call)
        self.assertIn(f"-c {self.path} -n chart-fix -d -- ", call)
        after = self.lane_json("chart-fix")
        self.assertEqual(set(after) - set(before), {"opened"})
        for key in set(before) - {"updated"}:
            self.assertEqual(after[key], before[key], key)


class Board(Lead):
    def test_window_comes_from_the_live_session(self):
        self.lane("new", "chart-fix")
        self.lane("new", "api-docs")
        rows = {r["id"]: r for r in json.loads(self.lane("ls", "--json"))}
        self.assertIsNone(rows["chart-fix"]["window"])
        self.live_session(self.lane_path("chart-fix"))
        rows = {r["id"]: r for r in json.loads(self.lane("ls", "--json"))}
        self.assertEqual((rows["chart-fix"]["window"], rows["api-docs"]["window"]),
                         ("proj:@3", None))
        head, *lines = self.lane("ls").splitlines()
        self.assertIn("WINDOW", head.split())
        col = head.split().index("WINDOW")
        cells = {ln.split()[0]: ln.split()[col] for ln in lines}
        self.assertEqual(cells, {"api-docs": "-", "chart-fix": "proj:@3"})


class Lock(Lead):
    def setUp(self):
        super().setUp()
        self.lane("init", "--locks", "gate,e2e")
        self.lock_file = os.path.join(self.common, "lanes", "_locks", "gate")

    def held(self):
        return os.path.exists(self.lock_file) and self.read(self.lock_file).strip() != ""

    def test_init_keeps_the_locks_and_checks_their_names(self):
        self.lane("init", "--cap", "5")
        self.assertIn('locks = "gate,e2e"', self.read(os.path.join(self.common, "lanes",
                                                                    "config.toml")))
        p = self.run_lane("init", "--locks", "gate,../x")
        self.assertEqual(p.returncode, 1)
        self.assertIn("../x", p.stderr)

    def test_the_command_exit_code_passes_through(self):
        self.assertEqual(self.run_lane("lock", "gate", "--", "sh", "-c", "exit 3").returncode, 3)
        p = self.run_lane("lock", "gate", "--wait", "1", "--", "sh", "-c", "kill -TERM $$")
        self.assertEqual(p.returncode, 128 + signal.SIGTERM)
        self.assertEqual(self.run_lane("lock", "gate", "--", "true").returncode, 0)

    def test_unknown_names_and_empty_commands_are_refused(self):
        p = self.run_lane("lock", "gat", "--", "true")
        self.assertEqual(p.returncode, 1)
        self.assertIn("gate, e2e", p.stderr)
        self.assertIn("lane init --locks", p.stderr)
        for args in (("lock", "gate", "--"), ("lock", "gate"), ("lock", "gate", "true")):
            self.assertEqual(self.run_lane(*args).returncode, 2, args)
        self.assertFalse(os.path.exists(self.lock_file))

    def test_a_second_holder_waits_for_the_first(self):
        self.lane("new", "chart-fix")
        marker = os.path.join(self.tmp, "first-done")
        holder = self.start("lock", "gate", "--", sys.executable, "-I", "-c",
                            f"import time; time.sleep(3); open({marker!r}, 'w').close()",
                            cwd=self.lane_path("chart-fix"))
        self.wait_for(self.held, "the first holder")
        self.assertIn("chart-fix", self.read(self.lock_file))
        board = self.lane("ls")
        self.assertIn("locks: gate held by chart-fix", board)
        p = self.run_lane("lock", "gate", "--", "test", "-e", marker)
        self.assertEqual(p.returncode, 0, p.stderr)  # it ran only after the first finished
        self.assertIn("waiting for lock gate: held by chart-fix", p.stderr)
        self.assertEqual(holder.wait(10), 0)
        self.assertNotIn("locks:", self.lane("ls"))

    def test_wait_times_out_naming_the_holder(self):
        pid_file = os.path.join(self.tmp, "child.pid")
        self.kill_pid_file(pid_file)
        holder = self.start("lock", "gate", "--", "sh", "-c", f"echo $$ > {pid_file}; "
                            "exec sleep 30")
        self.wait_for(self.held, "the holder")
        t0 = time.monotonic()
        p = self.run_lane("lock", "gate", "--wait", "0.5", "--", "true")
        self.assertEqual(p.returncode, 75)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertIn("held by main", p.stderr)
        self.assertIn("sleep 30", p.stderr)
        # Killed outright, the holder takes the lock with it; its orphaned child holds nothing.
        holder.kill()
        holder.wait(10)
        self.assertEqual(self.run_lane("lock", "gate", "--wait", "0", "--", "true").returncode, 0)

    def test_sigterm_reaches_the_command(self):
        holder = self.start("lock", "gate", "--", *SLEEP)
        self.wait_for(self.held, "the holder")
        holder.send_signal(signal.SIGTERM)
        self.assertEqual(holder.wait(10), 128 + signal.SIGTERM)
        self.assertEqual(self.run_lane("lock", "gate", "--wait", "0", "--", "true").returncode, 0)

    def test_a_backgrounded_grandchild_does_not_keep_the_lock(self):
        pid_file = os.path.join(self.tmp, "bg.pid")
        self.kill_pid_file(pid_file)
        p = self.run_lane("lock", "gate", "--", "sh", "-c",
                          f"sleep 30 >/dev/null 2>&1 & echo $! > {pid_file}; exit 0")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.run_lane("lock", "gate", "--wait", "0", "--", "true").returncode, 0)


if __name__ == "__main__":
    unittest.main()
