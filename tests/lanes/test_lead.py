"""The lead's tools in skills/lanes/scripts/lane: `open`, `lock`, and the board's WINDOW column,
locks footer and main-checkout footer. tmux is a stub that logs its argv; a live session is a
session file whose pid is this test process, or for the main-checkout footer a child of it
(_fixture.LiveSessions)."""
import contextlib
import fcntl
import io
import json
import os
import resource
import shlex
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

from _fixture import LANE, LanesRepo, LiveSessions
from test_cli import load_lane_script

TMUX_STUB = """#!/bin/sh
printf '%s\\n' "tmux $*" >> "$STUB_LOG"
[ "$1" = new-window ] && echo 'proj:3 (chart-fix)'
exit 0
"""
# A command that counts the SIGINTs and SIGTERMs it gets (into argv[1]), says it is ready (by
# creating argv[2]), and after the first leaves room for a second copy, then dies of the first.
COUNTER = """
import os, signal, sys, time
out, ready = sys.argv[1], sys.argv[2]
got = []
def on(sig, _frame):
    got.append(sig)
    with open(out, "w") as f:
        f.write(str(len(got)))
for s in (signal.SIGINT, signal.SIGTERM):
    signal.signal(s, on)
open(ready, "w").close()
deadline = time.monotonic() + 20
while not got and time.monotonic() < deadline:
    time.sleep(0.01)
if not got:
    sys.exit(99)
time.sleep(0.5)
signal.signal(got[0], signal.SIG_DFL)
os.kill(os.getpid(), got[0])
"""


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

    def test_init_says_to_trust_the_lanes_root(self):
        out = self.lane("init")  # `lane new` makes the root, so the line must too
        root = shlex.quote(self.root)
        self.assertIn(f"mkdir -p {root} && cd {root} && claude", out)
        self.assertIn("trust dialog", out)

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

    def test_sandboxed_print_still_prints_but_warns(self):
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(shlex.split(p.stdout)[:2], ["tmux", "new-window"])
        self.assertIn("liveness unknown", p.stderr)
        self.assertIn("may duplicate a live session", p.stderr)

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

    def test_sandboxed_window_is_unknown_not_empty(self):
        self.lane("new", "chart-fix")
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        head, line = self.lane("ls").splitlines()
        cells = dict(zip(head.split(), line.split()))
        self.assertEqual((cells["SESSIONS"], cells["CTX"], cells["STATE"], cells["WINDOW"]),
                         ("?", "?", "?", "?"))
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertIsNone(row["window"])
        self.assertIsNone(row["ctx"])
        self.assertIsNone(row["states"])


class MainFooter(LiveSessions):
    """The board's line for a crowded main checkout: shown only with two or more live sessions
    there, each by window, the recorded lead marked first."""

    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix")

    def footer(self):
        """The board's `main checkout:` line, or None."""
        lines = [ln for ln in self.lane("ls").splitlines() if ln.startswith("main checkout:")]
        self.assertLessEqual(len(lines), 1)
        return lines[0] if lines else None

    def test_only_two_or_more_live_sessions_show_and_the_lead_comes_first(self):
        self.assertIsNone(self.footer())
        a = self.child(self.main)
        self.session(self.main, pid=a, status="busy")
        self.session(self.lane_path("chart-fix"))  # a lane's: not the main checkout's
        self.assertIsNone(self.footer())
        b = self.child(self.main)
        self.session(self.main, pid=b)
        self.write_lead(b)
        self.assertEqual(self.footer(), f"main checkout: 2 live sessions: proj:@{b} (lead, pid "
                                        f"{b}, idle), proj:@{a} (pid {a}, busy)")
        self.assertTrue(self.lane("ls").rstrip().endswith(self.footer()))  # under the board

    def test_no_tmux_an_agent_worktree_and_the_way_to_pick(self):
        agent = os.path.join(self.main, ".claude", "worktrees", "agent-a1")
        os.makedirs(agent)
        a, b = self.child(self.main, pane=None), self.child(agent)
        self.session(self.main, pid=a, tmux=None)
        self.session(agent, pid=b)
        line = self.footer()
        self.assertTrue(line.startswith("main checkout: 2 live sessions: "), line)
        self.assertIn(f"no tmux (pid {a}, idle)", line)
        self.assertIn(f"proj:@{b} (pid {b}, idle, agent worktree)", line)
        self.assertIn("). No lead picked: the lead takes it with a bare `lane lead`", line)

    def test_no_footer_when_sandboxed(self):
        self.session(self.main)
        self.session(self.main)
        self.assertIsNotNone(self.footer())
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        self.assertIsNone(self.footer())

    def test_json_keeps_its_shape(self):
        self.session(self.main)
        self.session(self.main)
        rows = json.loads(self.lane("ls", "--json"))
        self.assertEqual([r["id"] for r in rows], ["chart-fix"])
        self.assertFalse(any("main" in k or "lead" in k for k in rows[0]))


class Ctx(Lead):
    """The board's CTX column: the watcher's count for the lane's live sessions, marked * past
    the soft tier and ! past hard on each session's own window (600k here: 300k/480k/520k)."""

    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix")

    def session(self, pid, sid, status="idle"):
        self.write(os.path.join(self.home, ".claude", "sessions", f"{pid}.json"),
                   json.dumps({"pid": pid, "sessionId": sid, "cwd": self.lane_path("chart-fix"),
                               "tmux": "proj:@3.%7", "status": status}))

    def ctx(self, sid, tokens, window=None):
        rec = {"tokens": tokens, "time": time.time()}
        if window is not None:
            rec["window"] = window
        self.write(os.path.join(self.tmp, "state", "dotclaude", "ctx", sid + ".json"),
                   json.dumps(rec))

    def board(self):
        head, line = self.lane("ls").splitlines()
        self.assertEqual(head.split().index("CTX"), head.split().index("SESSIONS") + 1)
        cell = dict(zip(head.split(), line.split()))["CTX"]
        (row,) = json.loads(self.lane("ls", "--json"))
        return cell, row["ctx"]

    def test_no_session_or_no_count_is_a_dash(self):
        self.assertEqual(self.board(), ("-", None))
        self.session(os.getpid(), "s-1")  # live, but the watcher hasn't counted it yet
        self.assertEqual(self.board(), ("-", None))

    def test_one_session(self):
        self.session(os.getpid(), "s-1")
        self.ctx("s-1", 212345)
        self.assertEqual(self.board(),
                         ("212k", {"session": "s-1", "tokens": 212345, "tier": None,
                                   "status": "idle"}))

    def test_two_sessions_show_the_larger(self):
        self.session(os.getpid(), "s-1")
        self.session(os.getppid(), "s-2")
        self.ctx("s-1", 120000)
        self.ctx("s-2", 250000)
        self.assertEqual(self.board()[0], "250k")
        self.assertEqual(self.board()[1]["session"], "s-2")

    def test_past_soft_and_past_hard(self):
        self.session(os.getpid(), "s-1")
        for tokens, cell, tier in ((299000, "299k", None), (300000, "300k*", "soft"),
                                   (480000, "480k*", "wrap"), (523456, "523k!", "hard")):
            with self.subTest(tokens=tokens):
                self.ctx("s-1", tokens)
                got_cell, got = self.board()
                self.assertEqual((got_cell, got["tier"]), (cell, tier))

    def test_marks_use_each_sessions_window(self):
        self.session(os.getpid(), "s-1")
        self.session(os.getppid(), "s-2")
        self.ctx("s-1", 250000)          # 600k: under soft
        self.ctx("s-2", 160000, 200000)  # 200k: past hard (151k)
        self.assertEqual(self.board(),
                         ("160k!", {"session": "s-2", "tokens": 160000, "tier": "hard",
                                    "status": "idle"}))

    def test_the_window_comes_from_the_sessions_own_config_dir(self):
        self.session(os.getpid(), "s-1")
        self.ctx("s-1", 160000)
        self.assertEqual(self.board()[0], "160k")  # lane's own config dir: 600k
        cfg = os.path.join(self.tmp, "other-config")
        self.write(os.path.join(cfg, "settings.json"), json.dumps({"autoCompactWindow": 200000}))
        self.write(os.path.join(self.tmp, "state", "dotclaude", "stops", "s-1.json"),
                   json.dumps({"session_id": "s-1", "time": time.time(),
                               "transcript_path": os.path.join(cfg, "projects", "p", "s-1.jsonl")}))
        self.assertEqual(self.board()[0], "160k!")  # its stop record's config dir: 200k

    def states(self):
        head, line = self.lane("ls").splitlines()
        self.assertEqual(head.split().index("STATE"), head.split().index("CTX") + 1)
        cell = dict(zip(head.split(), line.split()))["STATE"]
        (row,) = json.loads(self.lane("ls", "--json"))
        return cell, row["states"]

    def test_state_column_and_json(self):
        self.assertEqual(self.states(), ("-", []))
        self.session(os.getpid(), "s-1", "busy")
        self.assertEqual(self.states(), ("busy", ["busy"]))
        self.session(os.getppid(), "s-2", "shell")
        cell, states = self.states()
        self.assertEqual((sorted(cell.split(",")), sorted(states)), (["busy", "shell"],) * 2)
        self.session(os.getppid(), "s-2", "two words")  # not a status word
        self.assertEqual(sorted(self.states()[1]), ["?", "busy"])
        self.ctx("s-1", 310000)
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertEqual((row["ctx"]["status"], row["ctx"]["tier"]), ("busy", "soft"))

    def test_a_bad_count_or_session_id_is_skipped(self):
        self.session(os.getpid(), "../s-1")
        self.session(os.getppid(), "s-2")
        self.write(os.path.join(self.tmp, "state", "dotclaude", "s-1.json"),
                   json.dumps({"tokens": 999999}))
        self.ctx("s-2", "lots")
        self.assertEqual(self.board(), ("-", None))


class Lock(Lead):
    def setUp(self):
        super().setUp()
        self.lane("init", "--locks", "gate,e2e")
        self.lock_file = os.path.join(self.common, "lanes", "_locks", "gate")

    def held(self):
        return os.path.exists(self.lock_file) and self.read(self.lock_file).strip() != ""

    def test_init_keeps_the_locks_and_checks_their_names(self):
        self.lane("init", "--cap", "5")
        (cfg,) = self.config_files()
        self.assertIn('locks = "gate,e2e"', self.read(cfg))
        p = self.run_lane("init", "--locks", "gate,../x")
        self.assertEqual(p.returncode, 1)
        self.assertIn("../x", p.stderr)

    def test_the_command_exit_code_passes_through(self):
        self.assertEqual(self.run_lane("lock", "gate", "--", "sh", "-c", "exit 3").returncode, 3)
        # A command killed by signal n kills `lane` with n too, as a calling shell expects.
        p = self.run_lane("lock", "gate", "--wait", "1", "--", "sh", "-c", "kill -TERM $$")
        self.assertEqual(p.returncode, -signal.SIGTERM)
        # SIGKILL takes no handler, so re-raising it must skip setting one (an OSError before).
        p = self.run_lane("lock", "gate", "--", "sh", "-c", "kill -KILL $$")
        self.assertEqual(p.returncode, -signal.SIGKILL)
        self.assertNotIn("Traceback", p.stderr)
        self.assertFalse(self.held())
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
        p = self.run_lane("lock", "gate", "--wait", "0", "--", "true")
        self.assertEqual(p.returncode, 75)
        self.assertNotIn("waiting", p.stderr)  # --wait 0 never waits: only "gave up" is said
        self.assertIn("gave up on lock gate after 0s: held by main", p.stderr)
        # Killed outright, the holder takes the lock with it; its orphaned child holds nothing.
        holder.kill()
        holder.wait(10)
        self.assertEqual(self.run_lane("lock", "gate", "--wait", "0", "--", "true").returncode, 0)

    def test_a_group_signal_reaches_the_command_once(self):
        # A tty Ctrl-C or the Bash tool's kill signals the whole process group: `lane` must not
        # forward a second copy, which Go and Node tools read as "force quit".
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(sig=sig.name):
                count = os.path.join(self.tmp, f"{sig.name}.count")
                ready = os.path.join(self.tmp, f"{sig.name}.ready")
                p = subprocess.Popen([sys.executable, LANE, "lock", "gate", "--", sys.executable,
                                      "-I", "-c", COUNTER, count, ready],
                                     cwd=self.main, env=self.env, start_new_session=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.addCleanup(p.communicate)
                self.addCleanup(lambda: p.poll() is None and os.killpg(p.pid, signal.SIGKILL))
                self.wait_for(lambda: os.path.exists(ready), "the command")
                os.killpg(p.pid, sig)
                self.assertEqual(p.wait(10), -sig)  # it died of the signal, as its command did
                self.assertEqual(self.read(count), "1")
                self.assertEqual(self.read(self.lock_file), "")
        self.assertEqual(self.run_lane("lock", "gate", "--wait", "0", "--", "true").returncode, 0)

    def test_a_signal_before_the_command_starts_is_replayed_to_it(self):
        lane_cli, real_popen = load_lane_script(), subprocess.Popen

        def popen_after_a_ctrl_c(*args, **kwargs):
            os.kill(os.getpid(), signal.SIGINT)  # run_child's handler records it: no command yet
            return real_popen(*args, **kwargs)

        with mock.patch.object(lane_cli.subprocess, "Popen", popen_after_a_ctrl_c):
            rc = lane_cli.run_child(["sleep", "30"])
        self.assertEqual(rc, -signal.SIGINT)

    def test_a_ctrl_c_stops_a_calling_script(self):
        # bash quits a script on Ctrl-C only when its child died of SIGINT, not on an exit of 130.
        ready = os.path.join(self.tmp, "ready")
        gate = shlex.join([sys.executable, LANE, "lock", "gate", "--", "sh", "-c",
                           f"echo go > {shlex.quote(ready)}; exec sleep 30"])
        p = subprocess.Popen(["bash", "-c", f"{gate}; echo second"], cwd=self.main, env=self.env,
                             start_new_session=True, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        self.addCleanup(p.communicate)
        self.addCleanup(lambda: p.poll() is None and os.killpg(p.pid, signal.SIGKILL))
        self.wait_for(lambda: os.path.exists(ready) and self.read(ready).strip(), "the command")
        os.killpg(p.pid, signal.SIGINT)
        out, err = p.communicate(timeout=10)
        self.assertNotIn("second", out)
        self.assertIn(p.returncode, (-signal.SIGINT, 128 + signal.SIGINT), err)
        self.assertEqual(self.read(self.lock_file), "")
        self.assertEqual(self.run_lane("lock", "gate", "--wait", "0", "--", "true").returncode, 0)

    def test_a_ctrl_c_outside_the_command_releases_the_lock_quietly(self):
        # Between the acquire and the command (here in holder_line): no traceback, the holder
        # line cleared, the lock let go, then `lane` dies of the SIGINT (os.kill only records).
        lane_cli = load_lane_script()
        self.addCleanup(signal.signal, signal.SIGINT, signal.getsignal(signal.SIGINT))
        self.addCleanup(resource.setrlimit, resource.RLIMIT_CORE,
                        resource.getrlimit(resource.RLIMIT_CORE))
        repo = lane_cli.lanelib.resolve(self.main)
        err = io.StringIO()
        with mock.patch.object(lane_cli, "lanes_repo", return_value=repo), \
                mock.patch.object(lane_cli, "holder_line", side_effect=KeyboardInterrupt), \
                mock.patch.object(lane_cli.os, "kill") as kill, \
                contextlib.redirect_stderr(err):
            rc = lane_cli.main(["lock", "gate", "--", "true"])
        kill.assert_called_once_with(os.getpid(), signal.SIGINT)
        self.assertEqual(rc, 128 + signal.SIGINT)  # what it returns when it survives the re-raise
        self.assertNotIn("Traceback", err.getvalue())
        self.assertEqual(self.read(self.lock_file), "")
        self.assertEqual(self.run_lane("lock", "gate", "--wait", "0", "--", "true").returncode, 0)

    def test_a_probe_is_not_reported_as_a_holder(self):
        # `lane ls` holds LOCK_SH for an instant; a `--wait 0` run that meets it retries once.
        lane_cli = load_lane_script()
        path = os.path.join(self.tmp, "probed")
        fd = os.open(path, os.O_RDWR | os.O_CREAT)
        probe = os.open(path, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        self.addCleanup(os.close, probe)
        fcntl.flock(probe, fcntl.LOCK_SH)
        err = io.StringIO()
        with mock.patch.object(lane_cli.time, "sleep",
                               side_effect=lambda _: fcntl.flock(probe, fcntl.LOCK_UN)) as nap, \
                contextlib.redirect_stderr(err):
            self.assertTrue(lane_cli.take_lock(fd, "gate", 0))
        nap.assert_called_once_with(lane_cli.PROBE_GRACE)
        self.assertEqual(err.getvalue(), "")

    def test_release_clears_the_holder_line(self):
        # A waiter that reads between the next holder's acquire and its write must not name this
        # run, whatever way the command ended.
        for cmd in (["true"], ["sh", "-c", "exit 3"], [os.path.join(self.tmp, "no-such-cmd")]):
            with self.subTest(cmd=cmd):
                self.run_lane("lock", "gate", "--", *cmd)
                self.assertEqual(self.read(self.lock_file), "")

    def test_a_double_dash_inside_the_command_reaches_it(self):
        p = self.run_lane("lock", "gate", "--", "sh", "-c", 'printf %s "$*"', "x", "--", "y")
        self.assertEqual((p.returncode, p.stdout), (0, "-- y"), p.stderr)

    def test_ls_json_stays_a_list_of_lanes_with_no_locks(self):
        self.lane("new", "chart-fix")
        pid_file = os.path.join(self.tmp, "child.pid")
        self.kill_pid_file(pid_file)
        self.start("lock", "gate", "--", "sh", "-c", f"echo $$ > {pid_file}; exec sleep 30")
        self.wait_for(self.held, "the holder")
        rows = json.loads(self.lane("ls", "--json"))
        self.assertEqual([r["id"] for r in rows], ["chart-fix"])
        self.assertNotIn("locks", rows[0])

    def test_a_backgrounded_grandchild_does_not_keep_the_lock(self):
        pid_file = os.path.join(self.tmp, "bg.pid")
        self.kill_pid_file(pid_file)
        p = self.run_lane("lock", "gate", "--", "sh", "-c",
                          f"sleep 30 >/dev/null 2>&1 & echo $! > {pid_file}; exit 0")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.run_lane("lock", "gate", "--wait", "0", "--", "true").returncode, 0)


if __name__ == "__main__":
    unittest.main()
