"""codex-delegate: model gate, command contract, recursive audit, and full runs against a
fake `codex` on PATH (no real Codex is launched)."""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

from _paths import SCRIPTS, load_script

CD = os.path.join(SCRIPTS, "codex-delegate")
cd = load_script("codex-delegate")

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
    with open(os.environ["FAKE_ARGV_LOG"], "a") as f:
        f.write(json.dumps({"argv": a, "prompt_head": prompt[:80]}) + "\\n")
    print(json.dumps({"type": "thread.started", "thread_id": tid}), flush=True)
    print(json.dumps({"type": "item.completed", "item": {"type": "file_change"}}), flush=True)
    import time
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
        self.env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"],
                        CODEX_HOME=os.path.join(t, "codex"),
                        XDG_STATE_HOME=os.path.join(t, "state"),
                        FAKE_THREAD="th-1", FAKE_ARGV_LOG=self.argv_log)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cd(self, *args, **env):
        return subprocess.run([sys.executable, CD, *args], capture_output=True, text=True,
                              env=dict(self.env, **env))

    def ledger(self):
        path = os.path.join(self.tmp.name, "state", "dotclaude", "delegations.jsonl")
        with open(path) as f:
            return [json.loads(l) for l in f]

    def run_ok(self, **env):
        return self.run_cd("run", "--model", "terra", "--dir", self.work, "--brief", self.brief,
                           "--no-scope", **env)

    def test_clean_run(self):
        p = self.run_ok()
        self.assertEqual(p.returncode, 0, p.stderr)
        summary = json.loads(p.stdout)
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
        self.assertEqual(json.loads(p.stdout)["rc"], 7)
        self.assertEqual(self.ledger()[-1]["rc"], 7)

    def test_finalize_records_a_run_whose_wrapper_died(self):
        self.run_ok()
        path = os.path.join(self.tmp.name, "state", "dotclaude", "delegations.jsonl")
        rows = self.ledger()
        with open(path, "w") as f:  # drop the stop row, as if the wrapper had been killed
            f.writelines(json.dumps(r) + "\n" for r in rows[:-1])
        self.assertIn("ended without a stop row", self.run_cd("status").stdout)
        p = self.run_cd("finalize", rows[0]["run_id"])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.ledger()[-1]["event"], "stop")
        self.assertIsNone(self.ledger()[-1]["rc"])
        self.assertEqual(self.run_cd("finalize", rows[0]["run_id"]).returncode, 0)  # idempotent

    def test_codex_survives_a_killed_wrapper(self):
        import signal
        import time
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
        proc.wait(timeout=10)
        self.assertEqual(self.ledger()[-1]["event"], "interrupted")
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

    def test_astra_refused_before_anything_runs(self):
        p = self.run_cd("run", "--model", "astra", "--dir", self.work, "--brief", self.brief)
        self.assertEqual(p.returncode, 2)
        self.assertFalse(os.path.exists(self.argv_log))

    def test_resume_by_run_or_thread_id(self):
        run_id = json.loads(self.run_ok().stdout)["run_id"]
        for key in (run_id, "th-1"):
            p = self.run_cd("resume", key, "--no-scope")
            self.assertEqual(p.returncode, 0, p.stderr)
        with open(self.argv_log) as f:
            calls = [json.loads(l) for l in f]
        self.assertEqual(calls[1]["argv"][:3], ["exec", "resume", "th-1"])
        self.assertIn("--output-schema", calls[1]["argv"])
        self.assertTrue(calls[1]["prompt_head"].startswith("(codex-delegate resume"))

    def test_status_shows_the_stop(self):
        self.run_ok()
        p = self.run_cd("status")
        self.assertIn("stop", p.stdout)
        self.assertIn("report_ok=True", p.stdout)


if __name__ == "__main__":
    unittest.main()
