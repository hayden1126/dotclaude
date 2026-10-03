"""codex-delegate: model gate, command contract, recursive audit, and full runs against a
fake `codex` on PATH (no real Codex is launched)."""
import contextlib
import datetime
import fcntl
import io
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from unittest import mock

from _paths import SCRIPTS, load_script

CD = os.path.join(SCRIPTS, "codex-delegate")
LEDGER = os.path.join(SCRIPTS, "delegation-ledger")
cd = load_script("codex-delegate")
DEAD = 2 ** 22 + 12345  # beyond pid_max on this box, so never alive

FAKE_CODEX = textwrap.dedent('''\
    #!/usr/bin/env python3
    """Stands in for `codex exec`: echoes JSONL events, writes a rollout and the -o report."""
    import datetime, json, os, sys
    a = sys.argv[1:]
    model = a[a.index("-m") + 1]
    out = a[a.index("-o") + 1]
    prompt = sys.stdin.read()
    tid = os.environ["FAKE_THREAD"]
    day = datetime.date.today().strftime("%Y/%m/%d")
    root = os.path.join(os.environ["CODEX_HOME"], "sessions", day)
    os.makedirs(root, exist_ok=True)
    def rollout(thread, parent, m):
        with open(os.path.join(root, f"rollout-x-{thread}.jsonl"), "w") as f:
            meta = {"id": thread}
            if parent:
                meta["parent_thread_id"] = parent
            f.write(json.dumps({"type": "session_meta", "payload": meta}) + "\\n")
            f.write(json.dumps({"type": "turn_context", "payload": {"model": m}}) + "\\n")
    rollout(tid, None, model)
    if os.environ.get("FAKE_CHILD_MODEL"):
        rollout(tid + "-child", tid, os.environ["FAKE_CHILD_MODEL"])
    ledger = os.path.join(os.environ["XDG_STATE_HOME"], "dotclaude", "delegations.jsonl")
    with open(ledger) as f:
        last = json.loads(f.readlines()[-1])["event"]  # the row written before the launch
    with open(os.environ["FAKE_ARGV_LOG"], "a") as f:
        f.write(json.dumps({"argv": a, "prompt_head": prompt[:80], "ledger_last": last})
                + "\\n")
    import time
    time.sleep(float(os.environ.get("FAKE_START_DELAY", "0")))
    print(json.dumps({"type": "thread.started", "thread_id": tid}), flush=True)
    print(json.dumps({"type": "item.completed", "item": {"type": "file_change"}}), flush=True)
    time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
    report = os.environ.get("FAKE_REPORT", "valid")
    if report == "valid":
        json.dump({"status": "done", "summary": "s", "artifacts": [], "blocked_actions": []},
                  open(out, "w"))
    elif report == "invalid":
        json.dump({"status": "done"}, open(out, "w"))
    print(json.dumps({"type": "turn.completed", "usage": {}}), flush=True)
    sys.exit(int(os.environ.get("FAKE_RC", "0")))
''')


def kill_tree(pid):
    """SIGKILL pid and every descendant, found by walking /proc/*/stat ppids, as Claude Code's
    time-limit kill does (probed 2026-10-02): only a process reparented out of the tree escapes
    it. Returns the pids it signalled."""
    children = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(name))
    tree, todo = [], [pid]
    while todo:
        p = todo.pop()
        tree.append(p)
        todo += children.get(p, [])
    for p in tree:
        try:
            os.kill(p, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return tree


class Gate(unittest.TestCase):
    def test_only_sol_and_terra(self):
        self.assertEqual(cd.pin("sol"), "gpt-5.6-sol")
        self.assertEqual(cd.pin("terra"), "gpt-5.6-terra")
        self.assertEqual(cd.pin("gpt-5.6-sol"), "gpt-5.6-sol")
        for bad in ("astra", "gpt-6-astra", "gpt-5.6", "sol ", ""):
            with self.assertRaises(SystemExit):
                cd.pin(bad)

    def test_durations(self):
        self.assertEqual([cd.seconds(s) for s in ("90m", "3h", "600", "45s")],
                         [5400, 10800, 600, 45])
        with self.assertRaises(SystemExit):
            cd.seconds("soon")


class Commands(unittest.TestCase):
    def test_exec_contract(self):
        c = cd.exec_cmd("gpt-5.6-terra", "/w", "/w/.codex-delegate/r1")
        s = " ".join(c)
        for part in ("exec -m gpt-5.6-terra", "-s workspace-write", "-C /w", "--json",
                     f"--output-schema {cd.dc.SCHEMA_PATH}", "-o /w/.codex-delegate/r1/report.json",
                     'agents.default_subagent_model="gpt-5.6-terra"'):
            self.assertIn(part, s)
        self.assertEqual(c[-1], "-")               # prompt via stdin, never argv
        self.assertNotIn("network_access", s)
        self.assertNotIn("writable_roots", s)

    def test_network_and_outside_out_dir(self):
        s = " ".join(cd.exec_cmd("gpt-5.6-sol", "/w", "/elsewhere", network=True, effort="high"))
        self.assertIn("sandbox_workspace_write.network_access=true", s)
        self.assertIn('sandbox_workspace_write.writable_roots=["/elsewhere"]', s)
        self.assertIn('model_reasoning_effort="high"', s)

    def test_resume_repasses_the_contract(self):
        c = cd.resume_cmd("t1", "gpt-5.6-sol", "/w", "/w/o")
        s = " ".join(c)
        self.assertEqual(c[:4], ["codex", "exec", "resume", "t1"])
        for part in ("-m gpt-5.6-sol", "--output-schema", 'sandbox_mode="workspace-write"',
                     'agents.default_subagent_model="gpt-5.6-sol"', "-o /w/o/report.json"):
            self.assertIn(part, s)
        self.assertNotIn(" -s ", s)
        self.assertNotIn(" -C ", s)

    def test_wrap(self):
        c = cd.wrap(["codex"], 60, "8G", scope=False)
        self.assertEqual(c[0], "timeout")
        if cd.shutil.which("systemd-run"):
            c = cd.wrap(["codex"], 60, "8G")
            self.assertEqual(c[:4], ["systemd-run", "--user", "--scope", "-q"])
            self.assertIn("MemoryMax=8G", c)


class Audit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CODEX_HOME"] = self.tmp.name
        self.day = os.path.join(self.tmp.name, "sessions",
                                datetime.date.today().strftime("%Y/%m/%d"))
        os.makedirs(self.day)

    def tearDown(self):
        os.environ.pop("CODEX_HOME")
        self.tmp.cleanup()

    def rollout(self, tid, parent, model):
        meta = {"id": tid, "session_id": "root"}
        if parent:
            meta["parent_thread_id"] = parent
        with open(os.path.join(self.day, f"rollout-2026-x-{tid}.jsonl"), "w") as f:
            f.write(json.dumps({"type": "session_meta", "payload": meta}) + "\n")
            f.write(json.dumps({"type": "turn_context", "payload": {"model": model}}) + "\n")

    def test_clean_family_passes(self):
        self.rollout("R", None, "gpt-5.6-sol")
        self.rollout("C", "R", "gpt-5.6-terra")
        self.rollout("U", "other", "gpt-6-astra")  # unrelated thread: not audited
        res = cd.audit("R", 0)
        self.assertEqual((res["ok"], res["threads"]), (True, 2))
        self.assertEqual(res["models"], ["gpt-5.6-sol", "gpt-5.6-terra"])

    def test_astra_grandchild_fails(self):
        self.rollout("R", None, "gpt-5.6-sol")
        self.rollout("C", "R", "gpt-5.6-sol")
        self.rollout("G", "C", "gpt-6-astra")
        res = cd.audit("R", 0)
        self.assertEqual((res["ok"], res["threads"], res["disallowed"]),
                         (False, 3, ["gpt-6-astra"]))

    def test_missing_root_fails(self):
        res = cd.audit("nope", 0)
        self.assertEqual((res["ok"], res["root_found"]), (False, False))


class TurnRows(unittest.TestCase):
    """The rows a wrapper writes for its turn, and the supervisor's exit code, in process
    against a temp state dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": os.path.join(self.tmp.name, "st")})
        env.start()
        self.addCleanup(env.stop)
        self.owner = {"wrapper_pid": 4321, "wrapper_start": 99}
        self.row = {"runner": "codex", "id": "r1", "run_id": "r1"}

    def events(self):
        return [r["event"] for r in cd.dc.read_rows()]

    def test_no_start_or_detached_row_follows_a_cancels_stop_row(self):
        cd.dc.append_row(dict(self.row, ts=cd.dc.now_iso(), event="pending", **self.owner))
        cd.dc.append_row(dict(self.row, ts=cd.dc.now_iso(), event="stop", status="cancelled"))
        cd.append_turn_row(self.row, "start", "th-1", 1, self.owner)
        self.assertTrue(cd.locked_turn_row(self.row, "detached", "th-1", 1, self.owner, 1))
        self.assertEqual(self.events(), ["pending", "stop"])
        # Another wrapper's turn (a resume) gets its rows.
        other = {"wrapper_pid": 4322, "wrapper_start": 100}
        cd.dc.append_row(dict(self.row, ts=cd.dc.now_iso(), event="pending", **other))
        cd.append_turn_row(self.row, "resume", "th-1", 1, other)
        self.assertEqual(self.events(), ["pending", "stop", "pending", "resume"])

    def test_cancel_on_a_busy_lock_says_to_run_cancel_again(self):
        cd.dc.append_row(dict(self.row, ts=cd.dc.now_iso(), event="pending", **self.owner))
        lock = cd.finalize_lock_path("r1")
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        err = io.StringIO()
        with open(lock, "a") as held, mock.patch.object(cd, "FINALIZE_LOCK_S", 0.05), \
                contextlib.redirect_stderr(err):
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaises(SystemExit) as ex:
                cd.main(["cancel", "r1"])
        self.assertEqual(ex.exception.code, 2)
        self.assertIn("run r1 is being finalized elsewhere; run cancel again once that ends",
                      err.getvalue())

    def test_a_supervisor_whose_wrapper_is_gone_still_writes_codex_rc(self):
        # The wrapper died before it read the record: the write to it fails with EPIPE.
        out = os.path.join(self.tmp.name, "out")
        os.makedirs(out)
        r, w = os.pipe()
        os.close(r)
        child = os.fork()
        if child == 0:  # supervisor() never returns: it ends this process
            cd.supervisor([sys.executable, "-c", "import sys; sys.stdin.read(); sys.exit(3)"],
                          self.tmp.name, out, "the prompt", self.owner, w)
        os.close(w)
        os.waitpid(child, 0)
        with open(os.path.join(out, "codex.rc")) as f:
            rec = json.load(f)
        self.assertEqual((rec["rc"], rec["wrapper_pid"]), (3, 4321))


class FullRun(unittest.TestCase):
    """End to end through the real CLI with the fake codex first on PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        bindir = os.path.join(t, "bin")
        os.makedirs(bindir)
        with open(os.path.join(bindir, "codex"), "w") as f:
            f.write(FAKE_CODEX)
        os.chmod(os.path.join(bindir, "codex"), 0o755)
        self.work = os.path.join(t, "work")
        os.makedirs(self.work)
        self.brief = os.path.join(t, "brief.md")
        with open(self.brief, "w") as f:
            f.write("Do the thing.\n")
        self.argv_log = os.path.join(t, "argv.jsonl")
        # HOME is the temp dir too, so the walk to a Claude process finds no real session.
        self.env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"], HOME=t,
                        CODEX_HOME=os.path.join(t, "codex"),
                        XDG_STATE_HOME=os.path.join(t, "state"),
                        FAKE_THREAD="th-1", FAKE_ARGV_LOG=self.argv_log,
                        CLAUDE_CODE_SESSION_ID="s1", CLAUDE_PID=str(os.getpid()))
        # This test process stands in for the Claude process (it is each wrapper's parent, so
        # CLAUDE_PID names an ancestor and CLAUDE_CODE_SESSION_ID is the session). The lead's
        # inherited CLAUDE_PID is invisible inside the sandbox, and SANDBOX_RUNTIME is set
        # there, either of which would make every pid look hidden.
        self.env.pop("SANDBOX_RUNTIME", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cd(self, *args, **env):
        return subprocess.run([sys.executable, CD, *args], capture_output=True, text=True,
                              env=dict(self.env, **env))

    def ledger(self):
        path = os.path.join(self.tmp.name, "state", "dotclaude", "delegations.jsonl")
        with open(path) as f:
            return [json.loads(l) for l in f]

    def run_ok(self, *args, **env):
        return self.run_cd("run", "--model", "terra", "--dir", self.work, "--brief", self.brief,
                           "--no-scope", *args, **env)

    def start(self, *args, **env):
        """A run in the background, its stdout a pipe."""
        return subprocess.Popen([sys.executable, CD, "run", "--model", "sol", "--dir", self.work,
                                 "--brief", self.brief, "--no-scope", *args],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                env=dict(self.env, **env))

    @staticmethod
    def summary(p):
        """The JSON summary that follows the launch line."""
        return json.loads(p.stdout.split("\n", 1)[1])

    def launch_ids(self, line):
        m = re.fullmatch(r"codex-delegate: run (\S+), watch (\S+)\. If this command is "
                         r"stopped, Codex keeps running: delegation-ledger wait --resume (\S+)\n",
                         line)
        self.assertIsNotNone(m, line)
        self.assertEqual(m.group(2), m.group(3))
        return m.group(1), m.group(2)

    def watches(self):
        out = []
        for path in glob.glob(os.path.join(self.tmp.name, "state", "dotclaude", "watches",
                                           "*.json")):
            with open(path) as f:
                out.append(json.load(f))
        return {w["id"]: w for w in out}

    def write_watch(self, wid, run_id, live=False, sid="s0"):
        w = {"id": wid, "session_id": sid, "state": "open", "description": "d",
             "condition": {"codex": run_id}, "created": cd.dc.now_iso(),
             "waiter_pid": os.getpid() if live else DEAD,
             "waiter_start": cd.dc.proc_start(os.getpid()) if live else None,
             "waiter_heartbeat": cd.dc.now_iso(), "poll_s": 15, "blocked_at": None}
        cd.dc.write_json(os.path.join(self.tmp.name, "state", "dotclaude", "watches",
                                      f"{wid}.json"), w)

    def wait_gone(self, pid):
        deadline = time.time() + 15
        while time.time() < deadline and cd.dc.pid_alive(pid):
            time.sleep(0.1)

    def ledger_run(self, *args):
        return subprocess.run([sys.executable, LEDGER, *args], capture_output=True, text=True,
                              env=self.env, timeout=60)

    def drop_stop_row(self):
        """As if the wrapper had been killed before it wrote the stop row."""
        rows = self.ledger()
        with open(os.path.join(self.tmp.name, "state", "dotclaude", "delegations.jsonl"),
                  "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows[:-1])
        return rows[0]["run_id"]

    def test_clean_run(self):
        p = self.run_ok()
        self.assertEqual(p.returncode, 0, p.stderr)
        summary = self.summary(p)
        self.assertTrue(summary["report_ok"] and summary["audit_ok"])
        self.assertEqual([r["event"] for r in self.ledger()], ["pending", "start", "stop"])
        self.assertEqual(self.ledger()[1]["thread_id"], "th-1")
        with open(self.argv_log) as f:
            call = json.loads(f.readline())
        self.assertIn("gpt-5.6-terra", call["argv"])
        self.assertTrue(call["prompt_head"].startswith("# Delegation contract"))
        out = summary["out"]
        self.assertTrue(out.startswith(os.path.join(self.work, ".codex-delegate")))
        self.assertTrue(os.path.exists(os.path.join(out, "events.jsonl")))

    def test_invalid_report_exits_4(self):
        p = self.run_ok(FAKE_REPORT="invalid")
        self.assertEqual(p.returncode, 4)
        self.assertFalse(self.ledger()[-1]["report_ok"])

    def test_missing_report_exits_4(self):
        self.assertEqual(self.run_ok(FAKE_REPORT="none").returncode, 4)

    def test_astra_child_exits_3(self):
        p = self.run_ok(FAKE_CHILD_MODEL="gpt-6-astra")
        self.assertEqual(p.returncode, 3)
        self.assertEqual(self.ledger()[-1]["disallowed"], ["gpt-6-astra"])

    def test_codex_failure_exits_1_with_its_code_in_the_summary(self):
        p = self.run_ok(FAKE_RC="7")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.summary(p)["rc"], 7)
        self.assertEqual(self.ledger()[-1]["rc"], 7)
        self.assertEqual([w["state"] for w in self.watches().values()], ["failed"])

    def test_finalize_records_a_run_whose_wrapper_died(self):
        self.run_ok()
        run_id = self.drop_stop_row()
        self.assertIn("ended without a stop row", self.run_cd("status").stdout)
        p = self.run_cd("finalize", run_id)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.ledger()[-1]["event"], "stop")
        self.assertEqual(self.ledger()[-1]["rc"], 0)  # from codex.rc, which the supervisor wrote
        self.assertEqual(self.run_cd("finalize", run_id).returncode, 0)  # idempotent

    def test_codex_survives_a_killed_wrapper(self):
        proc = subprocess.Popen(
            [sys.executable, CD, "run", "--model", "sol", "--dir", self.work, "--brief",
             self.brief, "--no-scope"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(self.env, FAKE_SLEEP="2"))
        path = os.path.join(self.tmp.name, "state", "dotclaude", "delegations.jsonl")
        deadline = time.time() + 10
        while time.time() < deadline:
            if os.path.exists(path) and any(r["event"] == "start" for r in self.ledger()):
                break
            time.sleep(0.1)
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=10), 143)
        self.assertEqual(self.ledger()[-1]["event"], "detached")  # Codex runs on
        [w] = self.watches().values()  # left open with a dead waiter, for the guard to lapse
        self.assertEqual((w["state"], w["waiter_pid"]), ("open", proc.pid))
        self.assertFalse(cd.dc.waiter_alive(w))
        self.assertNotIn("_prompt", json.dumps(self.ledger()))
        codex_pid = self.ledger()[-1]["pid"]
        deadline = time.time() + 15
        while time.time() < deadline and cd.dc.pid_alive(codex_pid):
            time.sleep(0.1)
        run_id = self.ledger()[0]["run_id"]
        out = self.ledger()[0]["out"]
        self.assertTrue(os.path.exists(os.path.join(out, "report.json")))  # Codex finished
        p = self.run_cd("finalize", run_id)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(self.ledger()[-1]["audit_ok"])
        self.assertEqual(self.ledger()[-1]["rc"], 0)

    def pid_file(self):
        """The run's codex.pid record, once the supervisor has written it."""
        path = os.path.join(self.ledger()[0]["out"], "codex.pid")
        deadline = time.time() + 10
        while not os.path.exists(path) and time.time() < deadline:
            time.sleep(0.05)
        with open(path) as f:
            return json.load(f)

    def test_codex_survives_a_kill_of_the_wrappers_whole_tree(self):
        # Claude Code's time-limit kill takes the command's descendants. The supervisor was
        # double-forked out of them, so Codex runs on, and the re-arm gets its exit code.
        proc = self.start(FAKE_SLEEP="2", FAKE_RC="7")
        run_id, wid = self.launch_ids(proc.stdout.readline())
        rec = self.pid_file()
        killed = kill_tree(proc.pid)
        proc.wait(timeout=10)
        proc.stdout.close()
        self.assertNotIn(rec["supervisor_pid"], killed)
        self.assertNotIn(rec["pid"], killed)
        self.assertTrue(cd.dc.pid_alive(rec["pid"], rec["start"]))  # Codex runs on
        w = self.ledger_run("wait", "--resume", wid, "--poll", "0.2")
        self.assertEqual(w.returncode, 1, w.stderr)  # Codex exited 7, so the run failed
        stop = self.ledger()[-1]
        self.assertEqual((stop["event"], stop["rc"], stop["exit"], stop["report_ok"]),
                         ("stop", 7, 1, True))
        self.assertEqual(self.watches()[wid]["state"], "failed")

    def test_a_supervisor_killed_while_codex_runs_leaves_the_exit_code_unknown(self):
        proc = self.start(FAKE_SLEEP="2")
        run_id, _ = self.launch_ids(proc.stdout.readline())
        rec = self.pid_file()
        kill_tree(proc.pid)
        proc.wait(timeout=10)
        proc.stdout.close()
        os.kill(rec["supervisor_pid"], signal.SIGKILL)
        self.assertTrue(cd.dc.pid_alive(rec["pid"], rec["start"]))  # orphaned, it runs on
        self.wait_gone(rec["pid"])
        f = self.run_cd("finalize", run_id)
        self.assertEqual(f.returncode, 0, f.stderr)  # the report and audit still decide
        self.assertIsNone(self.ledger()[-1]["rc"])
        self.assertFalse(os.path.exists(os.path.join(self.ledger()[0]["out"], "codex.rc")))

    def test_a_wrapper_whose_supervisor_is_killed_records_the_exit_code_unknown(self):
        proc = self.start(FAKE_SLEEP="2")
        self.launch_ids(proc.stdout.readline())
        os.kill(self.pid_file()["supervisor_pid"], signal.SIGKILL)
        self.assertEqual(proc.wait(timeout=30), 0)  # it waits out the orphaned Codex
        proc.stdout.close()
        stop = self.ledger()[-1]
        self.assertEqual((stop["event"], stop["rc"]), ("stop", None))

    def test_cancel_stops_a_live_run_writes_its_stop_row_and_drops_its_watch(self):
        proc = self.start(FAKE_SLEEP="60")
        run_id, wid = self.launch_ids(proc.stdout.readline())
        rec = self.pid_file()
        c = self.run_cd("cancel", run_id)
        self.assertEqual(c.returncode, 0, c.stderr)
        self.assertIn(f"codex-delegate: run {run_id} cancelled (Codex pid {rec['pid']}", c.stdout)
        self.assertIn(f"dropped watch {wid}", c.stdout)
        self.assertFalse(cd.dc.pid_alive(rec["pid"], rec["start"]))
        stop = self.ledger()[-1]
        self.assertEqual((stop["event"], stop["status"], stop["exit"], stop["report_ok"]),
                         ("stop", "cancelled", 1, False))
        self.assertEqual(self.watches()[wid]["state"], "dropped")
        self.assertEqual(proc.wait(timeout=20), 1)  # its wrapper leaves the stop row be
        self.assertIn(f"run {run_id} was cancelled; its stop row stands", proc.stdout.read())
        proc.stdout.close()
        self.assertEqual([r["event"] for r in self.ledger()].count("stop"), 1)
        self.assertEqual(self.ledger()[-1]["status"], "cancelled")  # no start row after it
        self.assertIn("cancelled", self.run_cd("status", run_id).stdout)

    def test_a_resume_after_a_cancel_says_finished_again(self):
        proc = self.start(FAKE_SLEEP="60")
        run_id, _ = self.launch_ids(proc.stdout.readline())
        self.pid_file()
        self.assertEqual(self.run_cd("cancel", run_id).returncode, 0)
        self.assertEqual(proc.wait(timeout=20), 1)
        proc.stdout.close()
        r = self.run_cd("resume", run_id, "--no-scope")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.run_cd("status", run_id).stdout
        self.assertIn("stop: finished", out)
        self.assertNotIn("cancelled", out)
        self.assertIsNone(self.ledger()[-1]["error"])

    def test_cancel_with_no_watch_left_to_drop_doesnt_claim_one(self):
        proc = self.start(FAKE_SLEEP="60")
        run_id, wid = self.launch_ids(proc.stdout.readline())
        self.pid_file()
        self.assertEqual(self.ledger_run("wait", "--drop", wid).returncode, 0)
        c = self.run_cd("cancel", run_id)
        self.assertEqual(c.returncode, 0, c.stderr)
        self.assertNotIn("dropped watch", c.stdout)
        proc.wait(timeout=20)
        proc.stdout.close()

    def test_cancel_refuses_an_unknown_run_and_one_that_isnt_running(self):
        p = self.run_cd("cancel", "no-such-run")
        self.assertEqual(p.returncode, 2)
        self.assertIn("no codex run 'no-such-run'", p.stderr)
        run_id = self.summary(self.run_ok())["run_id"]
        p = self.run_cd("cancel", run_id)
        self.assertEqual(p.returncode, 2)
        self.assertIn(f"run {run_id} isn't running: it has ended, with a stop row", p.stderr)
        self.drop_stop_row()  # its wrapper gone before the stop row: Codex has ended
        pid = self.pid_file()["pid"]
        p = self.run_cd("cancel", run_id)
        self.assertEqual(p.returncode, 2)
        self.assertIn(f"run {run_id} isn't running: Codex (pid {pid}) has ended; record it with "
                      f"codex-delegate finalize {run_id}", p.stderr)
        self.assertEqual([r["event"] for r in self.ledger()], ["pending", "start"])

    def test_astra_refused_before_anything_runs(self):
        p = self.run_cd("run", "--model", "astra", "--dir", self.work, "--brief", self.brief)
        self.assertEqual(p.returncode, 2)
        self.assertFalse(os.path.exists(self.argv_log))

    def test_resume_by_run_or_thread_id(self):
        run_id = self.summary(self.run_ok())["run_id"]
        for key in (run_id, "th-1"):
            p = self.run_cd("resume", key, "--no-scope")
            self.assertEqual(p.returncode, 0, p.stderr)
        with open(self.argv_log) as f:
            calls = [json.loads(l) for l in f]
        self.assertEqual(calls[1]["argv"][:3], ["exec", "resume", "th-1"])
        self.assertIn("--output-schema", calls[1]["argv"])
        self.assertTrue(calls[1]["prompt_head"].startswith("(codex-delegate resume"))

    def test_a_run_prints_the_launch_line_and_waits_on_its_own_watch(self):
        proc = self.start(FAKE_SLEEP="3")
        run_id, wid = self.launch_ids(proc.stdout.readline())  # printed before Codex ends
        w = self.watches()[wid]
        self.assertEqual((w["condition"], w["state"], w["session_id"], w["waiter_pid"]),
                         ({"codex": run_id}, "open", "s1", proc.pid))
        self.assertTrue(cd.dc.waiter_alive(w))
        self.assertEqual(self.ledger()[0]["run_id"], run_id)
        self.assertEqual(proc.wait(timeout=20), 0)
        proc.stdout.close()
        self.assertEqual(self.watches()[wid]["state"], "done")

    def test_only_a_run_with_no_claude_process_says_the_guard_wont_see_it(self):
        note = "codex-delegate: no Claude Code session: the watch guard won't see this watch"
        p = self.run_ok(CLAUDE_CODE_SESSION_ID="")  # a process: its guard adopts the watch
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(note, p.stderr)
        p = self.run_ok(CLAUDE_CODE_SESSION_ID="", CLAUDE_PID="")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(note, p.stderr)

    def test_max_wait_exits_75_and_a_resumed_waiter_finalizes_the_run(self):
        p = self.run_ok("--max-wait", "0.02", FAKE_SLEEP="5")
        self.assertEqual(p.returncode, 75, p.stderr)
        launch, rearm = p.stdout.splitlines()
        run_id, wid = self.launch_ids(launch + "\n")
        self.assertEqual(rearm, f"still running: re-arm with delegation-ledger wait --resume "
                                f"{wid} (run_in_background, timeout 7200000)")
        self.assertEqual(self.watches()[wid]["state"], "open")
        rows = self.ledger()
        self.assertNotIn("stop", [r["event"] for r in rows])
        self.assertTrue(cd.dc.pid_alive(rows[-1]["pid"]))  # Codex runs on
        self.assertIn(f"`delegation-ledger wait --resume {wid}` waits and finalizes",
                      self.run_cd("status").stdout)
        w = self.ledger_run("wait", "--resume", wid, "--poll", "0.2")
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertEqual([r["event"] for r in self.ledger()].count("stop"), 1)
        self.assertTrue(self.ledger()[-1]["report_ok"])
        self.assertEqual(self.watches()[wid]["state"], "done")

    def test_a_run_detached_before_its_thread_started_finalizes_with_a_passing_audit(self):
        p = self.run_ok("--max-wait", "0.01", FAKE_START_DELAY="2")
        self.assertEqual(p.returncode, 75, p.stderr)
        detached = self.ledger()[-1]
        self.assertEqual((detached["event"], detached["thread_id"]), ("detached", None))
        deadline = time.time() + 15
        while time.time() < deadline and cd.dc.pid_alive(detached["pid"]):
            time.sleep(0.1)
        f = self.run_cd("finalize", detached["run_id"])
        self.assertEqual(f.returncode, 0, f.stderr)
        stop = self.ledger()[-1]
        self.assertEqual((stop["event"], stop["thread_id"], stop["audit_ok"]),
                         ("stop", "th-1", True))

    def test_a_sandboxed_run_records_no_watch_and_never_detaches(self):
        # Its own pid unseen: a sandbox PID namespace, which Codex could die with at exit 75.
        p = self.run_ok("--max-wait", "0.01", CLAUDE_PID=str(DEAD), FAKE_SLEEP="1.5")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("codex-delegate: running sandboxed, so no watch is recorded and --max-wait "
                      "is ignored (Codex would die with this command); run it as a bare "
                      "command\n", p.stderr)
        self.assertNotIn("detached", [r["event"] for r in self.ledger()])
        self.assertEqual(self.watches(), {})
        self.assertTrue(json.loads(p.stdout)["report_ok"])  # the summary alone, as before

    def test_resume_refuses_a_running_codex_then_finalizes_the_ended_turn_first(self):
        p = self.run_ok("--max-wait", "0.02", FAKE_SLEEP="5")
        self.assertEqual(p.returncode, 75, p.stderr)
        _, wid = self.launch_ids(p.stdout.splitlines()[0] + "\n")
        run_id, pid = self.ledger()[0]["run_id"], self.ledger()[-1]["pid"]
        r = self.run_cd("resume", run_id, "--no-scope")
        self.assertEqual(r.returncode, 2)
        self.assertIn(f"run {run_id} is still running (codex pid {pid}). Wait on it: "
                      f"delegation-ledger wait --resume {wid}; resume once it ends", r.stderr)
        with open(self.argv_log) as f:
            self.assertEqual(len(f.readlines()), 1)  # no second Codex on the thread
        self.wait_gone(pid)
        r = self.run_cd("resume", run_id, "--no-scope")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([r["event"] for r in self.ledger()],
                         ["pending", "start", "detached", "stop", "pending", "resume", "stop"])
        self.assertEqual(self.ledger()[3]["rc"], 0)  # the first turn, finalized from codex.rc
        self.assertEqual(self.watches()[wid]["state"], "done")  # the resume took it over

    def test_a_resume_that_fails_to_launch_ends_its_turn_failed(self):
        run_id = self.summary(self.run_ok("--out", os.path.join(self.tmp.name, "out")))["run_id"]
        shutil.rmtree(self.work)  # so the resume's Popen, run in --dir, fails
        p = self.run_cd("resume", run_id, "--no-scope")
        self.assertEqual(p.returncode, 1)
        self.assertIn("codex-delegate: FileNotFoundError", p.stderr)
        stop = self.ledger()[-1]
        self.assertEqual((stop["event"], stop["exit"], stop["report_ok"], stop["audit_ok"]),
                         ("stop", 1, False, False))
        self.assertIn("FileNotFoundError", stop["error"])
        _, wid = self.launch_ids(p.stdout.split("\n", 1)[0] + "\n")
        self.assertEqual(self.watches()[wid]["state"], "failed")
        self.assertNotEqual(self.ledger_run("wait", "--resume", wid).returncode, 0)

    def test_a_run_whose_wrapper_died_before_codex_started_is_not_finalized(self):
        run_id = self.summary(self.run_ok())["run_id"]
        with open(os.path.join(self.tmp.name, "state", "dotclaude", "delegations.jsonl"),
                  "a") as f:  # a resume's pending row, its wrapper gone before the Popen
            f.write(json.dumps({"runner": "codex", "id": run_id, "run_id": run_id,
                                "event": "pending", "ts": cd.dc.now_iso(), "thread_id": "th-1",
                                "wrapper_pid": DEAD}) + "\n")
        p = self.run_cd("finalize", run_id)
        self.assertEqual(p.returncode, 2)
        self.assertIn(f"run codex-delegate resume {run_id} again", p.stderr)
        w = self.ledger_run("wait", "--codex", run_id, "--poll", "0.2")
        self.assertEqual(w.returncode, 1, w.stderr)
        self.assertIn(f"codex run {run_id} never started: run codex-delegate resume {run_id} "
                      "again", w.stdout)
        self.assertEqual([r["event"] for r in self.ledger()].count("stop"), 1)

    def test_max_wait_with_its_watch_dropped_exits_5_without_a_rearm(self):
        proc = self.start("--max-wait", "0.05", FAKE_SLEEP="6")
        _, wid = self.launch_ids(proc.stdout.readline())
        d = self.ledger_run("wait", "--drop", wid)
        self.assertEqual(d.returncode, 0, d.stderr)
        self.assertEqual(proc.wait(timeout=20), 5)
        self.assertEqual(proc.stdout.read(), f"watch {wid} was dropped; Codex keeps running\n")
        proc.stdout.close()
        self.wait_gone(self.ledger()[-1]["pid"])

    def codex_pid(self):
        """The pid in the run's codex.pid, once the wrapper has written it."""
        path = os.path.join(self.ledger()[0]["out"], "codex.pid")
        deadline = time.time() + 10
        while not os.path.exists(path) and time.time() < deadline:
            time.sleep(0.05)
        with open(path) as f:
            return json.load(f)["pid"]

    def test_a_wrapper_killed_before_thread_started_leaves_a_running_run(self):
        # SIGKILL writes no row, so only codex.pid says Codex was launched.
        proc = self.start(FAKE_START_DELAY="3")
        run_id, wid = self.launch_ids(proc.stdout.readline())
        codex = self.codex_pid()
        proc.kill()
        proc.wait(timeout=10)
        proc.stdout.close()
        self.assertEqual([r["event"] for r in self.ledger()], ["pending"])
        self.assertTrue(cd.dc.pid_alive(codex))
        r = self.run_cd("resume", run_id, "--no-scope")
        self.assertEqual(r.returncode, 2)
        self.assertIn(f"run {run_id} is still running (codex pid {codex})", r.stderr)
        w = subprocess.Popen([sys.executable, LEDGER, "wait", "--resume", wid, "--poll", "0.2"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=self.env)
        time.sleep(1)
        self.assertIsNone(w.poll())  # it waits on the live Codex, not "never started"
        _, err = w.communicate(timeout=60)
        self.assertEqual(w.returncode, 0, err)
        self.assertEqual([r["event"] for r in self.ledger()], ["pending", "stop"])
        stop = self.ledger()[-1]
        self.assertEqual((stop["thread_id"], stop["audit_ok"]), ("th-1", True))

    def test_the_wrapper_heartbeats_while_it_finishes(self):
        proc = self.start("--poll", "0.4", FAKE_SLEEP="1")
        run_id, wid = self.launch_ids(proc.stdout.readline())
        lock = os.path.join(self.tmp.name, "state", "dotclaude", "codex-finalize",
                            f"{run_id}.lock")
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        with open(lock, "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)  # the finish waits on it
            self.wait_gone(self.codex_pid())
            beats = set()
            for _ in range(12):
                beats.add(self.watches()[wid]["waiter_heartbeat"])
                time.sleep(0.25)
            self.assertIsNone(proc.poll())
            self.assertEqual(self.watches()[wid]["state"], "open")
            self.assertGreaterEqual(len(beats), 2)  # stamps are whole seconds
            fcntl.flock(held, fcntl.LOCK_UN)
        self.assertEqual(proc.wait(timeout=20), 0)
        proc.stdout.close()
        w = self.watches()[wid]
        self.assertEqual(w["state"], "done")
        time.sleep(1.2)
        self.assertEqual(self.watches()[wid], w)  # no beat after the finish

    def test_max_wait_is_at_most_110_minutes(self):
        for bad in ("111", "0", "nan"):
            self.assertEqual(self.run_ok("--max-wait", bad).returncode, 2, bad)
        self.assertFalse(os.path.exists(self.argv_log))

    def test_resume_writes_its_row_before_codex_starts(self):
        run_id = self.summary(self.run_ok())["run_id"]
        self.assertEqual(self.run_cd("resume", run_id, "--no-scope").returncode, 0)
        with open(self.argv_log) as f:
            calls = [json.loads(l) for l in f]
        self.assertEqual([c["ledger_last"] for c in calls], ["pending", "pending"])
        self.assertEqual([r["event"] for r in self.ledger()],
                         ["pending", "start", "stop", "pending", "resume", "stop"])

    def test_resume_takes_over_an_open_watch_whose_waiter_is_gone(self):
        run_id = self.summary(self.run_ok())["run_id"]
        self.write_watch("w-old", run_id)
        p = self.run_cd("resume", run_id, "--no-scope")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.launch_ids(p.stdout.split("\n", 1)[0] + "\n")[1], "w-old")
        self.assertEqual(self.watches()["w-old"]["state"], "done")
        self.assertEqual(len(self.watches()), 2)  # the run's own, and the one it took over

    def test_a_resume_with_no_claude_process_keeps_the_session_and_says_nothing(self):
        run_id = self.summary(self.run_ok())["run_id"]
        self.write_watch("w-old", run_id)
        p = self.run_cd("resume", run_id, "--no-scope", CLAUDE_PID="", CLAUDE_CODE_SESSION_ID="")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("the watch guard won't see this watch", p.stderr)
        self.assertEqual(self.watches()["w-old"]["session_id"], "s0")

    def test_resume_is_refused_while_a_live_waiter_holds_the_runs_watch(self):
        run_id = self.summary(self.run_ok())["run_id"]
        self.write_watch("w-live", run_id, live=True, sid="s1")  # its session is live
        rows = len(self.ledger())
        p = self.run_cd("resume", run_id, "--no-scope")
        self.assertEqual(p.returncode, 2)
        self.assertIn("watch w-live already has a live waiter", p.stderr)
        self.assertEqual(len(self.ledger()), rows)  # no pending row, and no Codex
        with open(self.argv_log) as f:
            self.assertEqual(len(f.readlines()), 1)

    def test_two_finalizes_at_once_write_one_stop_row(self):
        self.run_ok()
        run_id = self.drop_stop_row()
        procs = [subprocess.Popen([sys.executable, CD, "finalize", run_id],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  env=self.env) for _ in range(2)]
        self.assertEqual([p.wait(timeout=30) for p in procs], [0, 0])
        self.assertEqual([r["event"] for r in self.ledger()].count("stop"), 1)

    def test_status_with_pids_hidden_says_so_instead_of_died(self):
        self.run_ok(FAKE_REPORT="none")
        self.drop_stop_row()
        self.assertIn("died", self.run_cd("status").stdout)
        out = self.run_cd("status", CLAUDE_PID=str(DEAD)).stdout
        self.assertIn("pid not visible in the sandbox", out)
        self.assertNotIn("died", out)

    def test_status_shows_the_stop(self):
        self.run_ok()
        p = self.run_cd("status")
        self.assertIn("stop", p.stdout)
        self.assertIn("report_ok=True", p.stdout)


if __name__ == "__main__":
    unittest.main()
