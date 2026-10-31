"""Port blocks: `lane init --block N` hands each new lane N ports in a row from `--ports`."""
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

    def test_stop_ends_a_session_member_that_cleared_its_environment(self):
        # No token on it, so only the leader's session (the leader still runs) proves it.
        argv = ["sh", "-c", f'env -i sh -c "sleep 600; :" {self.tmp} & exec "$0" {self.server} '
                            '127.0.0.1 "$PORT"', sys.executable]
        p = self.serve("--", *argv)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        (member,) = self.mine("sleep 600; :")
        self.assertIsNone(lanelib.proc_env(member, "LANE_SERVE"))
        self.lane("serve", "--stop", str(self.lo), cwd=self.path)
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

    def test_stop_keeps_the_record_while_a_process_outlives_sigkill(self):
        p = self.serve("--", sys.executable, self.server, "127.0.0.1", "{port}")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        mod = load_lane_script()
        repo = lanelib.resolve(self.path)
        _, lane = repo.identity()
        with mock.patch.object(mod, "end_serve", return_value=["4242 stuck"]):
            with self.assertRaises(mod.LaneError) as e:
                mod.serve_stop(repo, lane, self.lo)
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

    def test_done_ends_a_server_that_left_the_lane_and_removes_the_records(self):
        # A daemon that chdirs to / is out of done's view of the lane's processes: done ends it
        # by its record before removing the record, so nothing is left running untracked.
        _, (daemon,) = self.serve_script(
            f"import subprocess, sys; subprocess.Popen([sys.executable, {self.server!r}, "
            f"'127.0.0.1', sys.argv[1]], start_new_session=True, cwd='/')")
        start = lanelib.proc_start(daemon)
        self.assertEqual(os.readlink(f"/proc/{daemon}/cwd"), "/")
        self.merge()
        out = self.lane("done", "web")
        self.assertIn(f"ended what lane serve started on port {self.lo}", out)
        self.assertTrue(self.gone(daemon, start))
        self.assertFalse(os.path.exists(self.repo.served_dir("web")))

    def test_done_ends_a_served_tree_with_no_lane_session_id(self):
        # Served from a plain terminal (no CLAUDE_CODE_SESSION_ID, as the fixture's env has
        # none), in the lane, with a child whose cwd left it: the record proves both the lane's,
        # where the session-id rule alone refused the close before any signal.
        _, pids = self.serve_script(
            f"import os, subprocess, sys; subprocess.Popen(['sleep', '600'], cwd='/'); "
            f"os.execv(sys.executable, [sys.executable, {self.server!r}, '127.0.0.1', "
            f"sys.argv[1]])")
        self.assertEqual(len(pids), 2)
        starts = {pid: lanelib.proc_start(pid) for pid in pids}
        self.assertIsNone(lanelib.proc_env(pids[0], "CLAUDE_CODE_SESSION_ID"))
        self.merge()
        out = self.lane("done", "web")
        self.assertIn("lane serve's, port", out)
        self.assertTrue(all(self.gone(pid, start) for pid, start in starts.items()))

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
