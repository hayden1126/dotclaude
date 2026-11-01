"""Port blocks: `lane init --block N` hands each new lane N ports in a row from `--ports`."""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
import unittest
from unittest import mock

from _fixture import LANE, LanesRepo

import lanelib  # on sys.path through _fixture


def load_lane_script():
    """The `lane` script as a module (it has no .py name)."""
    loader = importlib.machinery.SourceFileLoader("lane_cli", LANE)
    spec = importlib.util.spec_from_loader("lane_cli", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class PortBlocks(LanesRepo):
    def lane_json_path(self, lane_id):
        return os.path.join(self.common, "lanes", lane_id, "lane.json")

    def rewrite(self, lane_id, **fields):
        """Set (or, with None, drop) fields in a lane's lane.json, as an older CLI wrote it."""
        rec = self.lane_json(lane_id)
        for k, v in fields.items():
            if v is None:
                rec.pop(k, None)
            else:
                rec[k] = v
        self.write(self.lane_json_path(lane_id), json.dumps(rec))

    def test_new_hands_out_disjoint_blocks_until_none_fits(self):
        self.lane("init", "--block", "3", "--setup", 'echo "$LANE_PORT $LANE_PORTS" > setup.out')
        for lane_id, first in (("a", 5191), ("b", 5194), ("c", 5197)):
            out = self.lane("new", lane_id)
            rec = self.lane_json(lane_id)
            self.assertEqual((rec["port"], rec["block"]), (first, 3))
            self.assertIn(f"ports {first}-{first + 2}", out)
            self.assertEqual(self.read(os.path.join(self.lane_path(lane_id), "setup.out")),
                             f"{first} {first}-{first + 2}\n")
        p = self.run_lane("new", "d")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("no free block of 3 ports in 5191-5199", p.stderr)
        self.assertFalse(os.path.exists(self.lane_path("d")))

    def test_a_block_of_one_is_todays_single_port(self):
        out = self.lane("new", "a")
        rec = self.lane_json("a")
        self.assertEqual((rec["port"], rec["block"]), (5191, 1))
        self.assertIn("port 5191", out)
        self.assertNotIn("ports", out)

    def test_an_old_record_without_a_block_holds_one_port(self):
        self.lane("new", "a")
        self.rewrite("a", block=None)  # lane.json as the CLI wrote it before blocks
        self.lane("init", "--block", "3")
        self.lane("new", "b")
        self.assertEqual(self.lane_json("b")["port"], 5192)
        rows = {r["id"]: r for r in json.loads(self.lane("ls", "--json"))}
        self.assertEqual(set(rows), {"a", "b"})  # the old record is read, not left out
        self.assertEqual(lanelib.port_block(rows["a"]), range(5191, 5192))
        self.assertEqual(lanelib.port_block(rows["b"]), range(5192, 5195))

    def test_a_bad_block_leaves_the_record_out(self):
        self.lane("new", "a")
        for value in ("3", 0, -1, True, 2.0, 70000):
            with self.subTest(block=value):
                self.rewrite("a", block=value)
                self.assertIn("left out lanes/a", self.run_lane("ls").stderr)
        self.rewrite("a", port=65535, block=2)  # runs past the last port
        self.assertIn("left out lanes/a", self.run_lane("ls").stderr)
        self.rewrite("a", port=None, block=2)  # a block with no port
        self.assertIn("left out lanes/a", self.run_lane("ls").stderr)

    def test_init_refuses_a_block_that_cannot_fit(self):
        for value, why in (("0", "--block wants a whole number of ports, at least 1"),
                           ("x", "--block wants a whole number of ports, at least 1"),
                           ("10", "a block of 10 ports can't fit in 5191-5199")):
            with self.subTest(block=value):
                p = self.run_lane("init", "--block", value)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn(why, p.stderr)
        p = self.run_lane("init", "--ports", "5191-5192", "--block", "3")
        self.assertIn("a block of 3 ports can't fit in 5191-5192", p.stderr)

    def test_the_board_whoami_and_hook_show_the_block(self):
        self.lane("init", "--block", "3")
        self.lane("new", "a")
        path = self.lane_path("a")
        self.assertRegex(self.lane("ls"), r"\na +a +\S+ +\S+ +5191-5193 ")
        self.assertIn("ports 5191-5193", self.lane("whoami", cwd=path))
        self.assertEqual(json.loads(self.lane("whoami", "--json", cwd=path))["ports"],
                         [5191, 5193])
        out = self.hook("lane-identity.sh", {"session_id": "sess-0001", "cwd": path,
                                             "source": "startup",
                                             "hook_event_name": "SessionStart"})
        self.assertIn("ports 5191-5193", out["additionalContext"])


SERVER = textwrap.dedent("""\
    import socket, sys, time
    host, port = sys.argv[1], int(sys.argv[2])
    s = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen()
    print("listening on", port, flush=True)
    time.sleep(600)
""")


def free_run(n):
    """The first port of n in a row that nothing listens on, from an ephemeral port the kernel
    picked: the suite may run sandbox-off, beside real dev servers."""
    for _ in range(50):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            lo = s.getsockname()[1]
        if lo + n > 65535:
            continue
        try:
            for port in range(lo, lo + n):
                with socket.socket() as t:
                    t.bind(("127.0.0.1", port))
        except OSError:
            continue
        return lo
    raise AssertionError("no free run of ports")


def ipv6():
    try:
        with socket.socket(socket.AF_INET6) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


class Serve(LanesRepo):
    """`lane serve`: start a lane's server in its own session and prove the port's listener is
    it. The suite's processes share one pid and network namespace even when it runs sandboxed,
    so /proc shows them and their sockets (_LANE_TEST_SANDBOXED=0, from the fixture)."""

    def setUp(self):
        super().setUp()
        self.lo = free_run(3)
        self.lane("init", "--ports", f"{self.lo}-{self.lo + 2}", "--block", "3")
        self.lane("new", "web")
        self.path = self.lane_path("web")
        self.server = os.path.join(self.tmp, "srv.py")
        self.write(self.server, SERVER)
        self.env["_LANE_TEST_GRACE"] = "1"

    def serve(self, *args, cwd=None):
        p = self.run_lane("serve", *args, cwd=cwd or self.path)
        self.addCleanup(self.stop_all)
        return p

    def stop_all(self):
        for port in range(self.lo, self.lo + 3):
            self.run_lane("serve", "--stop", str(port), cwd=self.path)

    def foreign(self, host, port):
        """A listener on port in a session of its own, as another lane's dev server is."""
        proc = subprocess.Popen([sys.executable, self.server, host, str(port)],
                                stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        self.assertIn("listening", proc.stdout.readline())
        return proc

    def pids_in_session(self, sid):
        out = []
        for name in os.listdir("/proc"):
            if name.isdigit():
                try:
                    if os.getsid(int(name)) == sid:
                        out.append(int(name))
                except OSError:
                    pass
        return out

    def served(self, port):
        repo = lanelib.Repo(self.main, self.common)
        path = repo.served_path("web", port)
        return json.loads(self.read(path)) if os.path.exists(path) else None

    def test_serve_starts_the_server_and_proves_the_listener(self):
        p = self.serve("--", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(f"serving port {self.lo}", p.stdout)
        rec = self.served(self.lo)
        self.assertEqual(os.getsid(rec["pid"]), rec["pid"])  # a session of its own
        with socket.create_connection(("127.0.0.1", self.lo), timeout=5):
            pass
        log = os.path.join(self.path, ".lane-serve", f"{self.lo}.log")
        self.assertIn(f"listening on {self.lo}", self.read(log))
        self.assertNotIn(".lane-serve", self.git("status", "--porcelain", cwd=self.path))
        # The next serve takes the block's next port: the first already has a listener.
        p = self.serve("--", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertIn(f"serving port {self.lo + 1}", p.stdout, p.stderr)

    def test_serve_sets_port_and_waits_for_the_ready_line(self):
        script = (f"import os, subprocess, sys, time; print('warming', flush=True); "
                  f"time.sleep(0.5); os.execv(sys.executable, [sys.executable, {self.server!r}, "
                  f"'127.0.0.1', os.environ['PORT']])")
        p = self.serve("--port", str(self.lo + 2), "--ready", "^listening on [0-9]+$", "--",
                       sys.executable, "-c", script)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(f"serving port {self.lo + 2}", p.stdout)

    def mine(self, pattern):
        """Pids whose command line holds pattern and this test's temp dir: never another
        lane's concurrent suite."""
        out = []
        for name in os.listdir("/proc"):
            if name.isdigit():
                argv = lanelib.proc_cmdline(int(name)) or []
                line = " ".join(argv)
                if pattern in line and self.tmp in line:
                    out.append(int(name))
        return out

    def test_a_listener_that_is_not_the_serves_fails_it(self):
        # The bug this closes: our server never binds (another holds the port), and the checks
        # that follow would test the other server. Here our command hands the port to a process
        # outside its session with the token cleared from its environment: as foreign as
        # another lane's server, and deterministic.
        script = (f"import subprocess, sys, time; subprocess.Popen(['env', '-i', "
                  f"{sys.executable!r}, {self.server!r}, '127.0.0.1', sys.argv[1]], "
                  f"start_new_session=True); time.sleep(600)  # {self.tmp}")
        p = self.serve("--", sys.executable, "-c", script, "{port}")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"port {self.lo}'s listener is not the server lane serve started",
                      p.stderr)
        holders = self.mine(f"{self.server} 127.0.0.1 {self.lo}")
        for pid in holders:
            self.addCleanup(lambda pid=pid: os.kill(pid, signal.SIGKILL))
        self.assertTrue(holders)
        self.assertIn(f"pid {holders[0]}", p.stderr)
        self.assertIsNone(self.served(self.lo))
        self.assertEqual(self.mine("time.sleep(600)"), [])  # the serve's own leader is ended

    def test_a_server_that_outlives_its_leader_or_daemonizes_is_the_serves(self):
        # A wrapper that backgrounds the server and exits, and a server that leaves the session
        # (setsid, as a daemon does): both carry the serve's token, so both are its own, and
        # --stop ends them after the leader is gone.
        forms = {
            "wrapper": ["sh", "-c", f'"$0" {self.server} 127.0.0.1 "$PORT" & exit 0',
                        sys.executable],
            "daemon": [sys.executable, "-c",
                       f"import subprocess, sys; subprocess.Popen([sys.executable, "
                       f"{self.server!r}, '127.0.0.1', sys.argv[1]], start_new_session=True)",
                       "{port}"],
        }
        for i, (form, argv) in enumerate(forms.items()):
            with self.subTest(form=form):
                port = self.lo + i
                p = self.serve("--port", str(port), "--", *argv)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                (pid,) = self.mine(f"{self.server} 127.0.0.1 {port}")
                self.assertNotEqual(os.getsid(pid), self.served(port)["pid"]) if form == "daemon" \
                    else None
                p = self.run_lane("serve", "--stop", str(port), cwd=self.path)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertIn(f"stopped port {port}", p.stdout)
                self.assertEqual(self.mine(f"{self.server} 127.0.0.1 {port}"), [])

    def test_the_server_carries_the_lane_sessions_id(self):
        # So `lane done` and `lane park` end it with the lane's sessions, as a leftover.
        self.env["CLAUDE_CODE_SESSION_ID"] = "sess-lane-0007"
        p = self.serve("--", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(lanelib.proc_env(self.served(self.lo)["pid"], "CLAUDE_CODE_SESSION_ID"),
                         "sess-lane-0007")

    def test_a_port_already_listened_on_is_refused_and_names_the_holder(self):
        hosts = ["127.0.0.1"] + (["::1"] if ipv6() else [])
        for i, host in enumerate(hosts):
            with self.subTest(host=host):
                port = self.lo + i
                holder = self.foreign(host, port)
                # The dual-stack case: our server would bind the other family and succeed.
                p = self.serve("--port", str(port), "--", sys.executable, self.server,
                               "::1" if host == "127.0.0.1" and ipv6() else "127.0.0.1",
                               "{port}")
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn(f"port {port} already has a listener: pid {holder.pid}", p.stderr)
                self.assertIsNone(self.served(port))

    def test_a_server_that_dies_first_fails_with_its_status_and_log(self):
        p = self.serve("--", "sh", "-c", "echo boom >&2; exit 3")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("exited with status 3 before it listened", p.stderr)
        self.assertIn("boom", p.stderr)
        self.assertIsNone(self.served(self.lo))

    def test_a_server_that_never_listens_times_out_and_is_ended(self):
        p = self.serve("--timeout", "1", "--", "sh", "-c", "echo $$ > pid.out; exec sleep 600")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"nothing listened on port {self.lo} within 1 s", p.stderr)
        pid = int(self.read(os.path.join(self.path, "pid.out")))
        deadline = time.monotonic() + 5
        while os.path.exists(f"/proc/{pid}") and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(os.path.exists(f"/proc/{pid}"))

    def test_serve_refuses_a_port_outside_the_block_the_sandbox_and_main(self):
        p = self.serve("--port", str(self.lo + 3), "--", "true")
        self.assertIn(f"port {self.lo + 3} is not in lane web's ports "
                      f"{self.lo}-{self.lo + 2}", p.stderr)
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        p = self.serve("--", "true")
        self.assertIn("Rerun it with the sandbox off", p.stderr)
        self.env["_LANE_TEST_SANDBOXED"] = "0"
        p = self.serve("--", "true", cwd=self.main)
        self.assertIn("lane serve runs from a lane", p.stderr)
        p = self.serve()
        self.assertIn("name the command after --", p.stderr)

    def test_the_log_is_never_written_through_a_planted_link(self):
        victim = os.path.join(self.tmp, "victim")
        self.write(victim, "keep\n")
        logs = os.path.join(self.path, ".lane-serve")
        os.makedirs(logs)
        os.symlink(victim, os.path.join(logs, f"{self.lo}.log"))
        os.link(victim, os.path.join(logs, f"{self.lo + 1}.log"))
        os.link(victim, os.path.join(logs, ".gitignore"))
        for port in (self.lo, self.lo + 1):
            with self.subTest(port=port):
                p = self.serve("--port", str(port), "--", sys.executable, self.server,
                               "127.0.0.1", "{port}")
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertEqual(self.read(victim), "keep\n")
        os.rename(logs, logs + ".old")
        os.symlink(self.tmp, logs)  # the dir itself a link
        p = self.serve("--port", str(self.lo + 2), "--", "true")
        self.assertEqual(p.returncode, 1)
        self.assertIn("is a symlink or no dir", p.stderr)

    def test_stop_ends_the_servers_whole_session(self):
        script = (f"import subprocess, sys; subprocess.Popen(['sleep', '600']); "
                  f"import os; os.execv(sys.executable, [sys.executable, {self.server!r}, "
                  f"'127.0.0.1', sys.argv[1]])")
        p = self.serve("--", sys.executable, "-c", script, "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        sid = self.served(self.lo)["pid"]
        self.assertEqual(len(self.pids_in_session(sid)), 2)  # the server and its sleep
        p = self.run_lane("serve", "--stop", str(self.lo), cwd=self.path)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(f"stopped port {self.lo}", p.stdout)
        self.assertEqual(self.pids_in_session(sid), [])
        self.assertIsNone(self.served(self.lo))

    def test_stop_refuses_a_listener_serve_did_not_start(self):
        holder = self.foreign("127.0.0.1", self.lo)
        p = self.run_lane("serve", "--stop", str(self.lo), cwd=self.path)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"lane web's serve started nothing on port {self.lo}", p.stderr)
        self.assertIn(f"pid {holder.pid}", p.stderr)
        self.assertIsNone(holder.poll())

    def test_stop_never_signals_a_pid_reused_since_the_serve(self):
        p = self.serve("--", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        repo = lanelib.Repo(self.main, self.common)
        path = repo.served_path("web", self.lo)
        rec = json.loads(self.read(path))
        # The recorded pid now names a session leader the serve never started (its start
        # differs): neither it nor its session is signalled; the server, by its token, is.
        holder = self.foreign("127.0.0.1", self.lo + 1)
        self.write(path, json.dumps(dict(rec, pid=holder.pid)))
        p = self.run_lane("serve", "--stop", str(self.lo), cwd=self.path)
        self.assertIn(f"stopped port {self.lo}", p.stdout, p.stderr)
        self.assertIsNone(holder.poll())
        self.assertEqual(self.mine(f"{self.server} 127.0.0.1 {self.lo}"), [])

    def test_a_record_from_another_boot_names_nothing_alive(self):
        p = self.serve("--", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        repo = lanelib.Repo(self.main, self.common)
        path = repo.served_path("web", self.lo)
        rec = json.loads(self.read(path))
        self.write(path, json.dumps(dict(rec, boot="another-boot")))
        p = self.run_lane("serve", "--stop", str(self.lo), cwd=self.path)
        self.assertIn("already gone", p.stdout, p.stderr)
        self.assertTrue(self.mine(f"{self.server} 127.0.0.1 {self.lo}"))
        self.write(path, json.dumps(rec))  # so cleanup ends it

    def test_stop_ends_what_carries_the_token_and_leaves_what_cleared_it(self):
        # Only the token proves a process the serve's once serve has returned: a session member
        # that cleared its environment is left by --stop (and refused by name by done and park).
        member = f'env -i sh -c "sleep 600; : {self.tmp}"'
        p = self.serve("--", "sh", "-c", f'{member} & exec "$0" {self.server} 127.0.0.1 "$PORT"',
                       sys.executable)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        (pid,) = self.mine("sleep 600; :")
        self.addCleanup(lambda: self.mine("sleep 600; :") and os.kill(pid, signal.SIGKILL))
        self.lane("serve", "--stop", str(self.lo), cwd=self.path)
        self.assertEqual(self.mine(f"{self.server} 127.0.0.1 {self.lo}"), [])
        self.assertEqual(self.mine("sleep 600; :"), [pid])

    def test_a_listener_that_cleared_its_environment_fails_the_serve(self):
        # --stop couldn't reach it later, so serve never succeeds on it.
        p = self.serve("--", "env", "-i", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("is in the serve's session but cleared its environment", p.stderr)
        self.assertEqual(self.mine(f"{self.server} 127.0.0.1 {self.lo}"), [])
        self.assertIsNone(self.served(self.lo))

    def test_a_failed_serve_ends_session_members_that_cleared_their_environment(self):
        # serve holds its leader unreaped, so its session stays proof of the serve's members
        # until it has ended them: a timeout leaves nothing behind.
        p = self.serve("--timeout", "1", "--", "sh", "-c",
                       f'env -i sh -c "sleep 600; : {self.tmp}" & exec sleep 600')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.mine("sleep 600; :"), [])

    def test_a_serve_still_running_but_not_listening_holds_its_port(self):
        script = textwrap.dedent(f"""\
            import signal, socket, sys, time
            s = socket.socket()
            s.bind(("127.0.0.1", int(sys.argv[1])))
            s.listen()
            signal.signal(signal.SIGUSR1, lambda *_: s.close())
            print("listening", flush=True)
            while True:
                time.sleep(1)  # {self.tmp}
        """)
        p = self.serve("--", sys.executable, "-c", script, "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        os.kill(self.served(self.lo)["pid"], signal.SIGUSR1)
        deadline = time.monotonic() + 5
        while lanelib.listeners(self.lo) and time.monotonic() < deadline:
            time.sleep(0.05)
        p = self.serve("--port", str(self.lo), "--", "true")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("still runs but isn't listening: `lane serve --stop", p.stderr)

    def test_a_timeout_must_be_finite_seconds(self):
        for value in ("nan", "inf", "0", "-1", "x"):
            with self.subTest(timeout=value):
                p = self.serve("--timeout", value, "--", "true")
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertIn("wants seconds above 0", p.stderr)

    def test_a_lane_json_block_is_checked_against_the_range_and_the_lanes(self):
        # lane.json is sandbox-writable: a lane could name any port, or another lane's.
        self.lane("init", "--ports", f"{self.lo}-{self.lo + 5}")
        self.lane("new", "api")  # lo+3 .. lo+5
        rec = self.lane_json("web")
        for fields, why in (({"port": self.lo + 3}, "lane api holds"),
                            ({"block": 9}, "outside the repo's range")):
            with self.subTest(fields=fields):
                self.write(os.path.join(self.common, "lanes", "web", "lane.json"),
                           json.dumps(dict(rec, **fields)))
                p = self.serve("--", "true")
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn(why, p.stderr)

    def start_serve(self, *args):
        """A serve running in the background, once its record is written."""
        proc = subprocess.Popen([sys.executable, LANE, "serve", *args], cwd=self.path,
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        self.addCleanup(self.stop_all)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.monotonic() + 10
        while self.served(self.lo) is None:
            self.assertLess(time.monotonic(), deadline, "the serve never recorded")
            time.sleep(0.02)
        return proc

    def test_the_log_is_read_through_the_fd_serve_made(self):
        # The lane can swap .lane-serve for a link while serve waits: the --ready scan and the
        # failure's tail must read the log serve made, never the one the path names by then.
        proc = self.start_serve("--timeout", "2", "--ready", "DECOY", "--",
                                "sh", "-c", f"echo real; sleep 600; : {self.tmp}")
        decoy = os.path.join(self.tmp, "decoy")
        self.write(os.path.join(decoy, f"{self.lo}.log"), "DECOY secret\n")
        logs = os.path.join(self.path, ".lane-serve")
        os.rename(logs, logs + ".old")
        os.symlink(decoy, logs)
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 1, out + err)
        self.assertIn("no line matched --ready 'DECOY'", err)
        self.assertNotIn("secret", err)
        self.assertIn("real", err)

    def test_an_interrupted_serve_ends_what_it_started(self):
        proc = self.start_serve("--", "sh", "-c", f"sleep 600; : {self.tmp}")
        (pid,) = [x for x in self.mine("sleep 600") if x != proc.pid]  # not serve's own argv
        proc.send_signal(signal.SIGINT)
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, -signal.SIGINT, out + err)
        self.assertIn("interrupted", err)
        self.assertEqual(self.mine("sleep 600"), [])
        self.assertIsNone(self.served(self.lo))

    def test_a_second_signal_cannot_cut_the_cleanup_short(self):
        # The server ignores SIGTERM, so the cleanup waits out the grace before its SIGKILL; a
        # SIGTERM to serve meanwhile is only noted, and the cleanup still finishes.
        proc = self.start_serve("--", "sh", "-c", f'trap "" TERM; sleep 600; : {self.tmp}')
        proc.send_signal(signal.SIGINT)
        time.sleep(0.3)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, -signal.SIGINT, out + err)
        self.assertEqual([x for x in self.mine("sleep 600; :") if x != proc.pid], [])
        self.assertIsNone(self.served(self.lo))

    def test_serve_holds_its_leader_even_when_started_with_sigchld_ignored(self):
        # An ignored SIGCHLD survives exec and would have the kernel reap the leader, so its pid
        # (the session's id) could be handed on: serve sets it back to the default.
        # (dash's `trap '' CHLD` sets no kernel-level ignore; this launcher does, then execs.)
        launch = ("import os, signal, sys; signal.signal(signal.SIGCHLD, signal.SIG_IGN); "
                  "os.execv(sys.executable, [sys.executable, *sys.argv[1:]])")
        p = subprocess.run([sys.executable, "-c", launch, LANE,
                            "serve", "--timeout", "1", "--", "sh", "-c",
                            f'env -i sh -c "sleep 600; : {self.tmp}" & exit 0'],
                           cwd=self.path, env=self.env, capture_output=True, text=True,
                           timeout=60)
        self.addCleanup(self.stop_all)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("nothing listened", p.stderr)
        self.assertEqual(self.mine("sleep 600; :"), [])  # ended through the held session

    def set_state(self, **fields):
        path = os.path.join(self.common, "lanes", "web", "lane.json")
        self.write(path, json.dumps(dict(self.lane_json("web"), **fields)))

    def test_stop_runs_in_a_closing_lane_where_a_start_is_refused(self):
        # done, refused after its signals, says to drop a record with --stop: it must run there.
        p = self.serve("--", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.set_state(state="closing")
        p = self.serve("--port", str(self.lo + 1), "--", "true")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("is closing", p.stderr)
        p = self.run_lane("serve", "--stop", str(self.lo), cwd=self.path)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(f"stopped port {self.lo}", p.stdout)

    def test_stop_refuses_a_lane_path_reached_through_a_symlink(self):
        # lane.json is sandbox-writable: a path through a link (here to the lane itself, so the
        # identity still matches) could be flipped to / while --stop judges cwds inside it.
        p = self.serve("--", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        link = os.path.join(self.path, "l")
        os.symlink(".", link)
        self.set_state(path=link)
        p = self.run_lane("serve", "--stop", str(self.lo), cwd=self.path)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("through a symlink", p.stderr)
        self.assertTrue(self.mine(f"{self.server} 127.0.0.1 {self.lo}"))
        self.set_state(path=self.path)  # so cleanup's --stop ends it

    def hold_lock(self):
        """Hold the lanes lock, as a slow `lane claim` or `done` would; release it with close."""
        fd = os.open(os.path.join(self.common, "lanes", ".lock"), os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def waiting_serve(self, marker):
        """A serve stuck on the held lock, whose command would make marker."""
        proc = subprocess.Popen([sys.executable, LANE, "serve", "--", "sh", "-c",
                                 f"touch {marker}; sleep 600; : {self.tmp}"],
                                cwd=self.path, env=self.env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        # Into the lock wait, seen in /proc/locks as a blocked FLOCK waiter on .lock's inode
        # (`->` marks one), not guessed from a sleep a loaded machine can outrun.
        inode = os.stat(os.path.join(self.common, "lanes", ".lock")).st_ino
        deadline = time.monotonic() + 30
        while not any("->" in line and "FLOCK" in line and line.split()[-3].endswith(f":{inode}")
                      for line in open("/proc/locks").read().splitlines()):
            self.assertIsNone(proc.poll(), proc.stderr.read() if proc.poll() is not None else "")
            self.assertLess(time.monotonic(), deadline, "the serve never waited on the lock")
            time.sleep(0.02)
        return proc

    def test_a_signal_during_the_lock_wait_starts_nothing(self):
        fd = self.hold_lock()
        marker = os.path.join(self.tmp, "started")
        proc = self.waiting_serve(marker)
        proc.send_signal(signal.SIGTERM)
        time.sleep(0.3)
        os.close(fd)
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, -signal.SIGTERM, out + err)
        self.assertFalse(os.path.exists(marker))
        self.assertIsNone(self.served(self.lo))

    def test_a_lane_marked_closing_during_the_lock_wait_starts_nothing(self):
        fd = self.hold_lock()
        marker = os.path.join(self.tmp, "started")
        proc = self.waiting_serve(marker)
        self.set_state(state="closing")  # as done does, under the lock
        os.close(fd)
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 1, out + err)
        self.assertIn("is closing", err)
        self.assertFalse(os.path.exists(marker))

    def test_fail_runs_once_even_when_it_raises(self):
        # A fail() that raises after its wait reaped the leader must not run again: a second
        # run would match by a session id that wait may have freed.
        mod = load_lane_script()
        calls = []
        real = mod.end_serve

        def spy(token, root, sid=None, send=None):
            calls.append(sid)
            return real(token, root, sid, send)
        with mock.patch.object(mod, "end_serve", spy), \
                mock.patch.object(mod, "remove_served", side_effect=OSError("lock gone")), \
                mock.patch.dict(os.environ, self.env), mock.patch("os.getcwd",
                                                                 return_value=self.path):
            cwd = os.open(".", os.O_RDONLY)
            os.chdir(self.path)
            try:
                rc = mod.main(["serve", "--timeout", "1", "--", "sh", "-c",
                               f"sleep 600; : {self.tmp}"])
            finally:
                os.fchdir(cwd)
                os.close(cwd)
                signal.signal(signal.SIGINT, signal.default_int_handler)
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(self.mine("sleep 600; :"), [])

    def test_stop_keeps_the_record_while_a_process_outlives_sigkill(self):
        p = self.serve("--", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        mod = load_lane_script()
        repo = lanelib.resolve(self.path)
        _, lane = repo.identity()
        with mock.patch.object(mod, "end_serve", return_value=(["4242 stuck"], "")):
            with self.assertRaises(mod.LaneError) as e:
                mod.serve_stop(repo, lane, self.path, self.lo)
        self.assertIn("4242 stuck", str(e.exception))
        self.assertIn(f"`lane serve --stop {self.lo}` can retry", str(e.exception))
        self.assertIsNotNone(self.served(self.lo))

    def test_another_lanes_server_is_not_this_lanes_to_stop(self):
        p = self.serve("--", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.lane("init", "--ports", f"{self.lo}-{self.lo + 3}", "--block", "1")
        self.lane("new", "api")
        p = self.run_lane("serve", "--stop", str(self.lo), cwd=self.lane_path("api"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lane api's serve started nothing", p.stderr)
        self.assertIsNotNone(self.served(self.lo))


class ServedRecords(LanesRepo):
    """`lane done` (and `park`, through survey) and the processes `lane serve` started."""

    def setUp(self):
        super().setUp()
        self.lo = free_run(1)
        self.lane("init", "--ports", f"{self.lo}-{self.lo}")
        self.lane("new", "web")
        self.path = self.lane_path("web")
        self.server = os.path.join(self.tmp, "srv.py")
        self.write(self.server, SERVER)
        self.repo = lanelib.Repo(self.main, self.common)

    def serve_script(self, script):
        """Serve `python -c script {port}` from the lane; the token's processes, each killed at
        cleanup if done left it running."""
        p = self.run_lane("serve", "--", sys.executable, "-c", script, "{port}", cwd=self.path)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        token = json.loads(self.read(self.repo.served_path("web", self.lo)))["token"]
        pids = [int(n) for n in os.listdir("/proc") if n.isdigit()
                and lanelib.proc_env(int(n), "LANE_SERVE") == token]
        for pid in pids:
            start = lanelib.proc_start(pid)
            self.addCleanup(lambda pid=pid, start=start: lanelib.proc_start(pid) == start
                            and os.kill(pid, signal.SIGKILL))
        return token, pids

    def merge(self):
        """Merge the lane, then hand it off (a Next written after HEAD), as done wants."""
        self.commit("chart.txt", "axis\n", cwd=self.path)
        self.git("push", "-q", "origin", "web:main", cwd=self.path)
        time.sleep(1.05)  # the record past HEAD's one-second commit time
        self.write(self.record("web"), self.read(self.record("web")).replace(
            "## Next\n", "## Next\n- Nothing left: the lane is done.\n"))

    def gone(self, pid, start):
        st = lanelib.proc_stat(pid)
        return st is None or st[3] != start or st[1] in lanelib.EXITED

    def outside_child(self, script_head):
        """Serve a server whose child (a sleep tagged with this test's dir) runs outside the
        lane, carrying the token; (server pid, child pid)."""
        _, pids = self.serve_script(
            f"import os, subprocess, sys; {script_head}; os.execv(sys.executable, "
            f"[sys.executable, {self.server!r}, '127.0.0.1', sys.argv[1]])")
        child = [x for x in pids if "sleep 600; :" in " ".join(lanelib.proc_cmdline(x) or [])]
        server = [x for x in pids if x not in child]
        return server[0], child[0]

    def test_a_daemon_that_leaves_the_lane_fails_the_serve_and_is_named(self):
        # --stop and done never signal a token carrier outside the lane (it may be a shared
        # daemon), so serve won't succeed on a listener there: it fails, names it, leaves it.
        script = (f"import subprocess, sys; subprocess.Popen([sys.executable, {self.server!r}, "
                  f"'127.0.0.1', sys.argv[1], {self.tmp!r}], start_new_session=True, cwd='/')")
        p = self.run_lane("serve", "--", sys.executable, "-c", script, "{port}", cwd=self.path)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("listener runs outside the lane's dir", p.stderr)
        self.assertIn("Run the server in the foreground", p.stderr)
        self.assertIn("never signalled", p.stderr)
        (daemon,) = [int(n) for n in os.listdir("/proc") if n.isdigit()
                     and self.tmp in " ".join(lanelib.proc_cmdline(int(n)) or [])
                     and self.server in " ".join(lanelib.proc_cmdline(int(n)) or [])]
        self.addCleanup(os.kill, daemon, signal.SIGKILL)
        self.assertIsNone(load_lane_script().load_served(self.repo, "web", self.lo))

    def test_done_ends_a_served_tree_with_no_lane_session_id(self):
        # Served from a plain terminal (no CLAUDE_CODE_SESSION_ID: the fixture's env has none),
        # in the lane, with a child: the record proves both the lane's, where the session-id
        # rule alone refused the close before any signal.
        server, child = self.outside_child(
            f"subprocess.Popen(['sh', '-c', 'sleep 600; : {self.tmp}'])")
        starts = {pid: lanelib.proc_start(pid) for pid in (server, child)}
        self.assertIsNone(lanelib.proc_env(server, "CLAUDE_CODE_SESSION_ID"))
        self.merge()
        out = self.lane("done", "web")
        self.assertIn("lane serve's, port", out)
        self.assertTrue(all(self.gone(pid, start) for pid, start in starts.items()))
        self.assertFalse(os.path.exists(self.repo.served_dir("web")))

    def test_done_names_a_token_carrier_outside_the_lane_and_signals_nothing(self):
        # It may be a shared daemon (Gradle's, watchman) working for other lanes too: done
        # refuses by name before any signal and keeps the record, whether the carrier runs
        # under the server or was reparented away (a double fork); --stop drops the record,
        # and then done goes on, the daemon left running.
        for form, head in (
                ("child", f"subprocess.Popen(['sh', '-c', 'sleep 600; : {self.tmp}'], cwd='/')"),
                ("reparented", f"subprocess.run(['sh', '-c', '(sleep 600; : {self.tmp}) & "
                               f"exit 0'], cwd='/')")):
            with self.subTest(form=form):
                server, child = self.outside_child(head)
                starts = {pid: lanelib.proc_start(pid) for pid in (server, child)}
                if form == "child":
                    self.merge()
                p = self.run_lane("done", "web")
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn(f"{child} sh", p.stderr)
                self.assertIn("outside lane web" if form == "child" else "never signals",
                              p.stderr)
                self.assertFalse(any(self.gone(pid, start) for pid, start in starts.items()))
                self.assertTrue(os.path.exists(self.repo.served_path("web", self.lo)))
                p = self.run_lane("serve", "--stop", str(self.lo), cwd=self.path)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertIn("never signalled", p.stderr)
                self.assertTrue(self.gone(server, starts[server]))
                self.assertFalse(self.gone(child, starts[child]))
        self.lane("done", "web")

    def test_done_keeps_a_record_while_what_it_names_runs(self):
        # The window the refusals can't close: a serve started after done's last look (a lane
        # with nothing running is never marked closing). Its record outlives the close. The
        # refusal is patched out here to stand in for the race; the server in the lane is gone,
        # its child outside the lane (with the token) still runs.
        server, child = self.outside_child(
            f"subprocess.Popen(['sh', '-c', 'sleep 600; : {self.tmp}'], cwd='/', "
            f"start_new_session=True)")
        start = lanelib.proc_start(server)
        os.kill(server, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while not self.gone(server, start):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.merge()
        mod = load_lane_script()
        with mock.patch.object(mod, "outside_serves"), mock.patch.dict(os.environ, self.env):
            cwd = os.open(".", os.O_RDONLY)
            os.chdir(self.main)
            try:
                with mock.patch.object(mod, "warn") as warned:
                    self.assertIn(mod.main(["done", "web"]), (0, None))
            finally:
                os.fchdir(cwd)
                os.close(cwd)
        self.assertIn("serve records are kept", " ".join(str(c) for c in warned.call_args_list))
        self.assertTrue(os.path.exists(self.repo.served_path("web", self.lo)))
        self.assertFalse(self.gone(child, lanelib.proc_start(child)))

    def test_done_refuses_by_name_a_child_that_cleared_its_environment_and_left(self):
        # Round 4's case: the token is the only proof, so a child that cleared it and left the
        # lane's dir is refused before any signal, never orphaned with its record removed.
        _, (server,) = self.serve_script(
            f"import os, subprocess, sys; subprocess.Popen(['env', '-i', 'sh', '-c', "
            f"'sleep 600; : {self.tmp}'], cwd='/'); os.execv(sys.executable, [sys.executable, "
            f"{self.server!r}, '127.0.0.1', sys.argv[1]])")
        (child,) = [int(n) for n in os.listdir("/proc") if n.isdigit()
                    and self.tmp in " ".join(lanelib.proc_cmdline(int(n)) or [])
                    and "sleep 600; :" in " ".join(lanelib.proc_cmdline(int(n)) or [])]
        start = lanelib.proc_start(child)
        self.addCleanup(lambda: lanelib.proc_start(child) == start
                        and os.kill(child, signal.SIGKILL))
        self.merge()
        p = self.run_lane("done", "web")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("nothing was signalled", p.stderr)
        self.assertIn(f"{child}", p.stderr)
        self.assertIn("outside lane web", p.stderr)
        self.assertFalse(self.gone(child, start))
        self.assertFalse(self.gone(server, lanelib.proc_start(server)))
        self.assertTrue(os.path.exists(self.repo.served_path("web", self.lo)))

    def test_survey_counts_a_served_process_as_the_lanes(self):
        # The class done's rounds and park share: SERVED by the record, refused without it.
        _, (server,) = self.serve_script(
            f"import os, sys; os.execv(sys.executable, [sys.executable, {self.server!r}, "
            f"'127.0.0.1', sys.argv[1]])")
        mod = load_lane_script()
        procs = lanelib.scan()
        hits, refused = mod.survey("web", self.path, procs, serves=mod.serve_proofs(self.repo, "web"))
        self.assertEqual((hits[server].kind, refused), (mod.SERVED, {}))
        hits, refused = mod.survey("web", self.path, procs)
        self.assertNotIn(server, hits)
        self.assertIn("no session id in its environment", refused[server])


if __name__ == "__main__":
    unittest.main()
