"""delegation-ledger wait: the watch file, each condition and exit code, resume, drop, and the
watches block in `watch` and `open`."""
import glob
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from _paths import SCRIPTS, load_script

LEDGER = os.path.join(SCRIPTS, "delegation-ledger")
dc = load_script("delegation_common.py")

DEAD = 2 ** 22 + 12345  # beyond pid_max on this box, so never alive
POLL = "0.05"
REARM = ("still running: re-arm with delegation-ledger wait --resume {} (run_in_background, "
         "timeout 7200000)\n")
SANDBOXED = "run delegation-ledger wait as a bare command (the sandbox hides other processes)\n"
FINALIZE_STUB = """#!/bin/sh
printf '%s\\n' "$*" > "$STUB_ARGV"
echo "stub finalized $2"
exit "${STUB_RC:-0}"
"""


class WaitEnv(unittest.TestCase):
    """A temp HOME and state dir with a live session s1 (this process's pid), as test_ledger's
    LiveSession sets them up, plus helpers to start a job, run the waiter and read watches."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = os.path.join(self.tmp.name, "state")
        self.env = dict(os.environ, HOME=self.tmp.name, XDG_STATE_HOME=self.state,
                        CLAUDE_CODE_SESSION_ID="s1")
        # Inside the sandbox the lead's CLAUDE_PID is inherited but invisible, which would make
        # every wait refuse to run. The Sandbox test sets it on purpose.
        self.env.pop("CLAUDE_PID", None)
        self.env.pop("DELEGATION_LEDGER", None)
        sessions = os.path.join(self.tmp.name, ".claude", "sessions")
        os.makedirs(sessions)
        with open(os.path.join(sessions, "1.json"), "w") as f:
            json.dump({"pid": os.getpid(), "sessionId": "s1"}, f)
        self.watches = os.path.join(self.state, "dotclaude", "watches")

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def job(self):
        """A real child process standing in for the long job; the test kills and reaps it."""
        p = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def end(self, job):
        job.kill()
        job.wait()  # reaped, so its /proc entry is gone, not a zombie's

    def argv(self, *argv, poll=True):
        return ["python3", LEDGER, "wait", *argv] + (["--poll", POLL] if poll else [])

    def start(self, *argv, **env):
        p = subprocess.Popen(self.argv(*argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env=dict(self.env, **env))
        self.addCleanup(self.reap, p)
        return p

    def reap(self, p):
        if p.poll() is None:
            p.kill()
        p.wait()
        p.stdout.close()
        p.stderr.close()

    def run_(self, *argv, poll=True, **env):
        return subprocess.run(self.argv(*argv, poll=poll), capture_output=True, text=True,
                              env=dict(self.env, **env), timeout=30)

    def cli(self, *argv):
        p = subprocess.run(["python3", LEDGER, *argv], capture_output=True, text=True,
                           env=self.env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def finish(self, p, code):
        out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, code, (out, err))
        return out, err

    def all_watches(self):
        out = []
        for path in sorted(glob.glob(os.path.join(self.watches, "*.json"))):
            with open(path) as f:
                out.append(json.load(f))
        return out

    def only(self):
        ws = self.all_watches()
        self.assertEqual(len(ws), 1, ws)
        return ws[0]

    def until(self, pred, timeout=10):
        """Poll until pred() is truthy and return it; fail at the timeout."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                got = pred()
            except (OSError, ValueError, IndexError):
                got = None
            if got:
                return got
            time.sleep(0.02)
        self.fail("condition never held")

    def waiting(self, p):
        """The watch once p is its waiter, after checking p is still running."""
        def mine():
            if p.poll() is not None:
                self.fail(f"the waiter exited {p.returncode}: {p.communicate()}")
            return [w for w in self.all_watches() if w["waiter_pid"] == p.pid]
        return self.until(mine)[0]

    def update(self, wid, **fields):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.state}):
            return dc.update_watch(wid, lambda w: w.update(fields))

    def lapsed(self, job):
        """An open watch on a live job whose waiter stopped at --max."""
        p = self.run_("--pid", str(job.pid), "--max", "0.002")
        self.assertEqual(p.returncode, 75, p.stderr)
        return self.only()["id"]


class Conditions(WaitEnv):
    def test_pid_records_the_watch_waits_and_exits_0(self):
        job = self.job()
        p = self.start("--pid", str(job.pid), "--desc", "the long build")
        w = self.waiting(p)
        self.assertEqual(set(w), {"id", "session_id", "description", "condition", "created",
                                  "waiter_pid", "waiter_start", "waiter_heartbeat", "poll_s",
                                  "state", "blocked_at"})
        self.assertRegex(w["id"], r"^w-\d{8}T\d{6}-[0-9a-f]{6}$")
        self.assertEqual((w["session_id"], w["description"], w["state"], w["blocked_at"]),
                         ("s1", "the long build", "open", None))
        self.assertEqual(w["condition"], {"pids": [{"pid": job.pid,
                                                    "start": dc.proc_start(job.pid)}]})
        self.assertEqual((w["waiter_start"], w["poll_s"]), (dc.proc_start(p.pid), 0.05))
        dc.parse_iso(w["created"])
        dc.parse_iso(w["waiter_heartbeat"])
        self.end(job)
        out, _ = self.finish(p, 0)
        self.assertEqual(out, f"watch {w['id']} done: pid {job.pid} exits\n")
        w = self.only()
        self.assertEqual(w["state"], "done")
        dc.parse_iso(w["ended"])

    def test_several_pids_wait_for_all_of_them(self):
        a, b = self.job(), self.job()
        p = self.start("--pid", str(a.pid), "--pid", str(b.pid))
        self.waiting(p)
        self.end(a)
        time.sleep(0.3)
        self.assertIsNone(p.poll())
        self.end(b)
        out, _ = self.finish(p, 0)
        self.assertIn(f"pids {a.pid}, {b.pid} exit", out)

    def test_file_is_done_when_it_exists(self):
        target = self.path("out.json")
        p = self.start("--file", target)
        self.assertEqual(self.waiting(p)["condition"], {"file": target})
        open(target, "w").close()
        self.finish(p, 0)
        self.assertEqual(self.only()["state"], "done")

    def test_a_met_condition_exits_at_once(self):
        target = self.path("out.json")
        open(target, "w").close()
        p = self.run_("--file", target, "--max", "1")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.only()["state"], "done")

    def test_log_done_line(self):
        log = self.path("job.log")
        open(log, "w").close()
        p = self.start("--log", log, "--done", r"^BUILD OK$", "--fail", "Traceback")
        w = self.waiting(p)
        self.assertEqual(w["condition"], {"log": log, "done": r"^BUILD OK$",
                                          "fail": "Traceback"})
        with open(log, "a") as f:
            f.write("compiling\nBUILD OK, says the banner\n")
        time.sleep(0.3)
        self.assertIsNone(p.poll())
        with open(log, "a") as f:
            f.write("BUILD OK\n")
        self.finish(p, 0)

    def test_a_last_line_without_a_newline_still_matches(self):
        log = self.path("job.log")
        p = self.start("--log", log, "--done", "DONE")  # no log yet: still waiting
        self.waiting(p)
        with open(log, "w") as f:
            f.write("step 1\nDONE")
        self.finish(p, 0)

    def test_log_fail_line_exits_1(self):
        log = self.path("job.log")
        p = self.start("--log", log, "--done", "DONE", "--fail", "Traceback")
        w = self.waiting(p)
        with open(log, "w") as f:
            f.write("Traceback (most recent call last):\n")
        out, _ = self.finish(p, 1)
        self.assertEqual(out, f"watch {w['id']} failed: {log} has a line matching /Traceback/\n")
        self.assertEqual(self.only()["state"], "failed")

    def test_a_truncated_log_is_read_again_from_the_start(self):
        log = self.path("job.log")
        with open(log, "w") as f:
            f.write("a long first run of the job\n" * 20)
        p = self.start("--log", log, "--done", "DONE")
        self.waiting(p)
        time.sleep(0.2)  # the waiter has read past the old content
        with open(log, "w") as f:
            f.write("DONE\n")
        self.finish(p, 0)

    def test_a_stale_log_exits_2(self):
        log = self.path("job.log")
        open(log, "w").close()
        p = self.run_("--log", log, "--done", "DONE", "--stale", "0.005", "--max", "1")
        self.assertEqual(p.returncode, 2, p.stderr)
        w = self.only()
        self.assertEqual(p.stdout, f"watch {w['id']} stale: {log} unchanged for 0.005 min\n")
        self.assertEqual(w["state"], "stale")

    def test_the_job_ending_without_its_file_fails(self):
        job = self.job()
        p = self.start("--pid", str(job.pid), "--file", self.path("never"))
        w = self.waiting(p)
        self.end(job)
        out, _ = self.finish(p, 1)
        self.assertEqual(out, f"watch {w['id']} failed: pid {job.pid} exited, but "
                              f"{self.path('never')} exists is unmet\n")

    def test_a_pid_gone_before_the_wait_counts_as_exited(self):
        p = self.run_("--pid", str(DEAD), "--max", "1")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.only()["condition"], {"pids": [{"pid": DEAD, "start": None}]})


class Exits(WaitEnv):
    def test_max_prints_only_the_rearm_line_and_leaves_the_watch_open(self):
        job = self.job()
        p = self.run_("--pid", str(job.pid), "--max", "0.002")
        self.assertEqual(p.returncode, 75, p.stderr)
        w = self.only()
        self.assertEqual((p.stdout, p.stderr), (REARM.format(w["id"]), ""))
        self.assertEqual(w["state"], "open")
        self.assertNotIn("ended", w)

    def test_the_heartbeat_moves_on_every_poll(self):
        p = self.start("--pid", str(self.job().pid))
        first = self.waiting(p)["waiter_heartbeat"]
        self.until(lambda: self.all_watches()[0]["waiter_heartbeat"] > first, timeout=5)

    def test_resume_takes_over_and_clears_blocked_at(self):
        job = self.job()
        wid = self.lapsed(job)
        before = self.update(wid, blocked_at=dc.now_iso())
        p = self.start("--resume", wid)
        w = self.waiting(p)
        self.assertEqual((w["state"], w["blocked_at"]), ("open", None))
        self.assertEqual(w["waiter_start"], dc.proc_start(p.pid))
        for k in ("id", "session_id", "description", "condition", "created"):
            self.assertEqual(w[k], before[k], k)
        self.end(job)
        self.finish(p, 0)
        self.assertEqual(self.only()["state"], "done")

    def test_resume_at_max_again_prints_the_same_rearm_line(self):
        job = self.job()
        wid = self.lapsed(job)
        p = self.run_("--resume", wid, "--max", "0.002")
        self.assertEqual((p.returncode, p.stdout), (75, REARM.format(wid)))

    def test_resume_reopens_an_acknowledged_watch(self):
        job = self.job()
        wid = self.lapsed(job)
        self.update(wid, state="acknowledged", blocked_at=dc.now_iso())
        p = self.start("--resume", wid)
        self.assertEqual(self.waiting(p)["state"], "open")

    def test_resume_refuses_a_finished_watch(self):
        target = self.path("out")
        open(target, "w").close()
        self.assertEqual(self.run_("--file", target).returncode, 0)
        wid = self.only()["id"]
        p = self.run_("--resume", wid)
        self.assertEqual((p.returncode, p.stderr),
                         (2, f"wait: watch {wid} is done; start a new wait\n"))

    def test_a_live_waiter_reopens_a_lapse_it_outlived(self):
        # The guard may call a waiter lapsed while its heartbeat is late (a suspended VM). A
        # waiter that polls again is live, so the lapse is over.
        p = self.start("--pid", str(self.job().pid))
        wid = self.waiting(p)["id"]
        self.update(wid, state="acknowledged", blocked_at=dc.now_iso())
        self.until(lambda: [(w["state"], w["blocked_at"]) for w in self.all_watches()]
                   == [("open", None)])

    def test_resume_supersedes_a_running_waiter(self):
        job = self.job()
        first = self.start("--pid", str(job.pid))
        wid = self.waiting(first)["id"]
        second = self.start("--resume", wid)
        self.waiting(second)
        out, _ = self.finish(first, 0)
        self.assertEqual(out, f"watch {wid} is now waited on by pid {second.pid}; "
                              "this waiter stopped\n")
        self.end(job)
        self.finish(second, 0)

    def test_drop_marks_a_lapsed_watch_dropped(self):
        wid = self.lapsed(self.job())
        p = self.run_("--drop", wid)
        self.assertEqual((p.returncode, p.stdout), (0, f"dropped watch {wid}\n"))
        w = self.only()
        self.assertEqual(w["state"], "dropped")
        dc.parse_iso(w["ended"])
        p = self.run_("--drop", wid)
        self.assertEqual((p.returncode, p.stdout), (0, f"watch {wid} is already dropped\n"))

    def test_drop_stops_a_running_waiter(self):
        p = self.start("--pid", str(self.job().pid))
        wid = self.waiting(p)["id"]
        self.assertEqual(self.run_("--drop", wid).returncode, 0)
        out, _ = self.finish(p, 0)
        self.assertEqual(out, f"watch {wid} was dropped; stopped waiting\n")
        self.assertEqual(self.only()["state"], "dropped")

    def test_unknown_and_malformed_ids_exit_2(self):
        os.makedirs(self.watches)
        with open(os.path.join(self.watches, "w-torn.json"), "w") as f:
            f.write("{")
        with open(os.path.join(self.watches, "w-list.json"), "w") as f:
            f.write("[]")
        for wid in ("w-nope", "../x", ".lock", "a/b", "", "w-torn", "w-list"):
            for opt in ("--resume", "--drop"):
                p = self.run_(opt, wid)
                self.assertEqual(p.returncode, 2, (opt, wid, p.stderr))
                self.assertTrue(p.stderr.startswith("wait: "), p.stderr)
        self.assertEqual(sorted(os.listdir(self.watches)), ["w-list.json", "w-torn.json"])


class Usage(WaitEnv):
    def test_bad_usage_exits_2_and_records_nothing(self):
        log = self.path("job.log")
        cases = [
            [], ["--done", "x"], ["--fail", "x", "--pid", "1"], ["--stale", "1", "--pid", "1"],
            ["--log", log], ["--log", log, "--fail", "x"], ["--log", log, "--stale", "1"],
            ["--log", log, "--done", "("], ["--log", log, "--done", "x", "--stale", "0"],
            ["--pid", "0"], ["--pid", "x"], ["--pid", "1", "--max", "0"],
            ["--pid", "1", "--max", "nan"], ["--pid", "1", "--poll", "0"],
            ["--codex", "r1", "--pid", "1"], ["--codex", "r-unknown"],
            ["--resume", "w-x", "--pid", "1"], ["--drop", "w-x", "--desc", "y"],
            ["--resume", "w-x", "--drop", "w-x"],
        ]
        for argv in cases:
            p = self.run_(*argv, poll=False)
            self.assertEqual(p.returncode, 2, (argv, p.stderr))
            self.assertTrue(p.stderr, argv)
        self.assertFalse(os.path.exists(self.state))

    def test_a_sandboxed_run_is_refused_before_anything_is_written(self):
        target = self.path("out")
        open(target, "w").close()
        for argv in (["--file", target], ["--resume", "w-x"], ["--drop", "w-x"]):
            p = self.run_(*argv, CLAUDE_PID=str(DEAD))
            self.assertEqual((p.returncode, p.stdout, p.stderr), (2, "", SANDBOXED), argv)
        self.assertFalse(os.path.exists(self.state))

    def test_a_visible_claude_pid_runs(self):
        target = self.path("out")
        open(target, "w").close()
        self.assertEqual(self.run_("--file", target, CLAUDE_PID=str(os.getpid())).returncode, 0)


class Session(WaitEnv):
    def session_of(self, **env):
        target = self.path("out")
        open(target, "w").close()
        p = subprocess.run(self.argv("--file", target), capture_output=True, text=True,
                           env=env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        sid = self.all_watches()[-1]["session_id"]
        for path in glob.glob(os.path.join(self.watches, "*.json")):
            os.remove(path)
        return sid

    def test_the_session_comes_from_the_env_then_the_sessions_file(self):
        env = {k: v for k, v in self.env.items() if k != "CLAUDE_CODE_SESSION_ID"}
        self.assertEqual(self.session_of(**dict(env, CLAUDE_CODE_SESSION_ID="s7")), "s7")
        self.assertEqual(self.session_of(**dict(env, CLAUDE_PID=str(os.getpid()))), "s1")
        self.assertEqual(self.session_of(**env), "unknown")


class Codex(WaitEnv):
    def setUp(self):
        super().setUp()
        stub = self.path("codex-delegate")
        with open(stub, "w") as f:
            f.write(FINALIZE_STUB)
        os.chmod(stub, 0o755)
        self.argv_file = self.path("argv")
        self.env.update(DELEGATION_CODEX_DELEGATE=stub, STUB_ARGV=self.argv_file)

    def codex_row(self, rid, pid, **kw):
        path = os.path.join(self.state, "dotclaude", "delegations.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(dict({"runner": "codex", "id": rid, "run_id": rid,
                                     "thread_id": f"t-{rid}", "event": "start",
                                     "ts": dc.now_iso(), "out": self.path(rid), "pid": pid,
                                     "wrapper_pid": pid}, **kw)) + "\n")

    def test_codex_finalizes_when_its_pid_is_gone(self):
        codex = self.job()
        self.codex_row("r1", codex.pid)
        p = self.start("--codex", "t-r1")  # a thread id finds its run too
        w = self.waiting(p)
        self.assertEqual((w["condition"], w["description"]),
                         ({"codex": "r1"}, "codex run r1 ends"))
        self.end(codex)
        out, _ = self.finish(p, 0)
        self.assertEqual(out, f"stub finalized r1\nwatch {w['id']} done: codex run r1 ends\n")
        with open(self.argv_file) as f:
            self.assertEqual(f.read(), "finalize r1\n")
        self.assertEqual(self.only()["state"], "done")

    def test_a_failed_finalize_exits_1(self):
        self.codex_row("r1", DEAD)
        p = self.run_("--codex", "r1", STUB_RC="4")
        self.assertEqual(p.returncode, 1, p.stderr)
        w = self.only()
        self.assertEqual(p.stdout, f"stub finalized r1\nwatch {w['id']} failed: "
                                   "codex-delegate finalize r1 exited 4\n")
        self.assertEqual(w["state"], "failed")

    def test_a_live_wrapper_records_the_stop_before_any_finalize(self):
        # Codex has ended but its wrapper is still writing the stop row; finalizing then would
        # record a second one, so the waiter waits for the wrapper too.
        wrapper = self.job()
        self.codex_row("r1", DEAD, wrapper_pid=wrapper.pid)
        p = self.start("--codex", "r1")
        self.waiting(p)
        time.sleep(0.3)
        self.assertIsNone(p.poll())
        self.codex_row("r1", DEAD, wrapper_pid=wrapper.pid, event="stop")
        self.finish(p, 0)

    def test_a_pending_run_waits_for_its_wrapper(self):
        wrapper = self.job()
        self.codex_row("r1", None, event="pending", wrapper_pid=wrapper.pid)
        p = self.start("--codex", "r1")
        self.waiting(p)
        time.sleep(0.3)
        self.assertIsNone(p.poll())
        self.end(wrapper)
        self.finish(p, 0)


class Views(WaitEnv):
    def test_open_watches_print_in_their_own_block(self):
        wid = self.lapsed(self.job())
        lines = self.cli("watch").splitlines()
        self.assertEqual(lines[0], "no live delegations")
        self.assertEqual(lines[1:], [
            "open watches:",
            f"  {wid}  'pid {self.only()['condition']['pids'][0]['pid']} exits'  no live waiter "
            f"⚠ re-arm: delegation-ledger wait --resume {wid}"])
        self.assertEqual(self.cli("watch", "--summary"), "\n")
        out = self.cli("open").splitlines()
        self.assertEqual(out[0], "no unfinished delegations in the last 48h")
        self.assertEqual(out[1], "open watches:")
        self.assertTrue(out[2].startswith(f"  {wid}  open  'pid "), out)
        self.assertIn("session s1 alive, waiter pid", out[3])
        self.assertIn(f"re-arm: delegation-ledger wait --resume {wid}", out[3])

    def test_a_live_waiter_shows_as_waiting(self):
        p = self.start("--pid", str(self.job().pid), "--desc", "the build")
        wid = self.waiting(p)["id"]
        self.assertIn(f"  {wid}  'the build'  waiter alive", self.cli("watch").splitlines())

    def test_finished_watches_leave_the_output_unchanged(self):
        target = self.path("out")
        open(target, "w").close()
        self.assertEqual(self.run_("--file", target).returncode, 0)
        self.assertEqual(self.cli("watch"), "no live delegations\n")
        self.assertEqual(self.cli("open"), "no unfinished delegations in the last 48h\n")


class WriteJson(unittest.TestCase):
    def test_it_replaces_the_file_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "w.json")
            dc.write_json(path, {"b": 1, "a": [2]})
            dc.write_json(path, {"a": 3})
            with open(path) as f:
                self.assertEqual(json.load(f), {"a": 3})
            self.assertEqual(os.listdir(os.path.dirname(path)), ["w.json"])


if __name__ == "__main__":
    unittest.main()
