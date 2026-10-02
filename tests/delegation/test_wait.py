"""delegation-ledger wait: the watch file, each condition and exit code, resume, drop, pruning,
and the watches block in `watch` and `open`."""
import glob
import json
import os
import shutil
import signal
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
USAGE, ASIDE, ERROR, AT_MAX = 64, 3, 70, 75
REARM = ("still running: re-arm with delegation-ledger wait --resume {} (run_in_background, "
         "timeout 7200000)\n")
SANDBOXED = "run delegation-ledger wait as a bare command (the sandbox hides other processes)\n"
# A stand-in for codex-delegate beside a copy of the ledger: `finalize` appends its argv (one
# line per run), takes STUB_SLEEP seconds, and, like the real one, appends the run's stop row
# with its exit code, then exits with that code.
FINALIZE_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_ARGV"
[ -n "$STUB_PIDFILE" ] && echo $$ > "$STUB_PIDFILE"
[ -n "$STUB_SLEEP" ] && sleep "$STUB_SLEEP"
if [ -n "$STUB_RELEASE" ]; then
  while [ ! -e "$STUB_RELEASE" ]; do sleep 0.02; done
fi
echo "stub finalized $2"
if [ -z "$STUB_NO_ROW" ]; then
  printf '{"runner": "codex", "id": "%s", "run_id": "%s", "event": "stop", "exit": %s}\\n' \\
    "$2" "$2" "${STUB_EXIT:-0}" >> "$XDG_STATE_HOME/dotclaude/delegations.jsonl"
fi
exit "${STUB_EXIT:-0}"
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
        self.script = LEDGER

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def job(self):
        """A real child process standing in for the long job; cleanup kills and reaps it."""
        p = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def end(self, job):
        job.kill()
        job.wait()  # reaped, so its /proc entry is gone

    def argv(self, *argv, poll=True):
        return ["python3", self.script, "wait", *argv] + (["--poll", POLL] if poll else [])

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
        p = subprocess.run(["python3", self.script, *argv], capture_output=True, text=True,
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
        """The watch once p is its waiter, failing at once if p has exited."""
        def mine():
            if p.poll() is not None:
                self.fail(f"the waiter exited {p.returncode}: {p.communicate()}")
            return [w for w in self.all_watches() if w["waiter_pid"] == p.pid]
        return self.until(mine)[0]

    def suspend(self, p):
        """SIGSTOP a waiter, as a suspended VM would, until its heartbeat reads as stale."""
        p.send_signal(signal.SIGSTOP)
        self.addCleanup(lambda: p.poll() is None and p.send_signal(signal.SIGCONT))
        self.until(lambda: not dc.waiter_alive(
            [w for w in self.all_watches() if w["waiter_pid"] == p.pid][0]), timeout=10)

    def update(self, wid, **fields):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.state}):
            return dc.update_watch(wid, lambda w: w.update(fields))

    def lapsed(self, job):
        """An open watch on a live job whose waiter stopped at --max."""
        p = self.run_("--pid", str(job.pid), "--max", "0.002")
        self.assertEqual(p.returncode, AT_MAX, p.stderr)
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
        self.assertEqual(w["condition"], {"pids": [{"pid": job.pid, "comm": "sleep",
                                                    "start": dc.proc_start(job.pid)}]})
        self.assertEqual((w["waiter_start"], w["poll_s"]), (dc.proc_start(p.pid), 0.05))
        dc.parse_iso(w["created"])
        dc.parse_iso(w["waiter_heartbeat"])
        self.end(job)
        out, _ = self.finish(p, 0)
        self.assertEqual(out, f"watch {w['id']} done: pid {job.pid} (sleep) exits\n")
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
        self.assertIn(f"pids {a.pid} (sleep), {b.pid} (sleep) exit", out)

    def test_a_zombie_job_counts_as_exited(self):
        job = self.job()
        p = self.start("--pid", str(job.pid))
        self.waiting(p)
        job.kill()  # not reaped: its /proc entry stays, in state Z
        self.finish(p, 0)

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

    def test_a_last_line_without_a_newline_matches_once_the_log_settles(self):
        log = self.path("job.log")
        p = self.start("--log", log, "--done", "DONE")  # no log yet: still waiting
        self.waiting(p)
        with open(log, "w") as f:
            f.write("step 1\nDONE")
        self.finish(p, 0)

    def test_a_partial_line_is_matched_only_once_the_job_is_gone(self):
        job = self.job()
        log = self.path("job.log")
        with open(log, "w") as f:
            f.write("FAIL")  # the start of "FAILSAFE engaged", still being written
        p = self.start("--pid", str(job.pid), "--log", log, "--done", "^OK$", "--fail",
                       "^FAIL$")
        self.waiting(p)
        time.sleep(0.3)
        self.assertIsNone(p.poll())
        with open(log, "a") as f:
            f.write("SAFE engaged\nOK")
        self.end(job)
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
        self.assertEqual(out, f"watch {w['id']} failed: pid {job.pid} (sleep) exited, but "
                              f"{self.path('never')} exists is unmet\n")

    def test_a_pid_not_running_at_the_start_is_refused(self):
        p = self.run_("--pid", str(DEAD))
        self.assertEqual((p.returncode, p.stdout), (USAGE, ""))
        self.assertEqual(p.stderr, f"wait: pid {DEAD} isn't running here; a pid echoed from a "
                                   "sandboxed command comes from another PID namespace\n")
        self.assertFalse(os.path.exists(self.state))

    def test_pid_1_is_refused(self):
        p = self.run_("--pid", "1")
        self.assertEqual((p.returncode, p.stderr),
                         (USAGE, "wait: pid 1 is the init process; a pid echoed from a sandboxed "
                                 "command comes from another PID namespace\n"))
        self.assertFalse(os.path.exists(self.state))


class Unwatchable(unittest.TestCase):
    """dc.unwatchable: a sandboxed command's pids start at 1, so one echoed from it can name,
    out here, a process that never ends."""

    def setUp(self):
        self.child = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (self.child.kill(), self.child.wait()))

    def test_a_child_of_this_process_is_watchable_and_named(self):
        self.assertIsNone(dc.unwatchable(self.child.pid))
        self.assertEqual(dc.proc_comm(self.child.pid), "sleep")

    def test_a_gone_pid_pid_1_a_kernel_thread_and_another_users_pid_are_refused(self):
        self.assertEqual(dc.unwatchable(DEAD), "isn't running here")
        self.assertEqual(dc.unwatchable(1), "is the init process")
        kthread = ["S"] + ["0"] * 5 + [str(dc.PF_KTHREAD)] + ["0"] * 13
        with mock.patch.object(dc, "_stat_fields", return_value=kthread):
            self.assertEqual(dc.unwatchable(self.child.pid), "is a kernel thread")
        with mock.patch.object(dc.os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual(dc.unwatchable(self.child.pid), "belongs to another user")


class ScanLog(unittest.TestCase):
    def test_a_partial_line_matches_once_it_settles_or_the_pids_are_gone(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "job.log")
            with open(log, "w") as f:
                f.write("seen\nOK")
            cur = dc.log_cursor()
            self.assertIsNone(dc.scan_log(log, "^OK$", None, cur))           # a new size
            self.assertEqual(dc.scan_log(log, "^OK$", None, cur), "done")    # unchanged a poll
            cur = dc.log_cursor()
            for _ in range(2):  # the pids still run: a partial line may not be finished
                self.assertIsNone(dc.scan_log(log, "^OK$", None, cur, pids_gone=False))
            self.assertEqual(dc.scan_log(log, "^OK$", None, cur, pids_gone=True), "done")
            with open(log, "a") as f:
                f.write("AY")
            cur = dc.log_cursor()
            for _ in range(2):  # the finished line is OKAY, which doesn't match
                self.assertIsNone(dc.scan_log(log, "^OK$", None, cur))


class Exits(WaitEnv):
    def test_max_prints_only_the_rearm_line_and_leaves_the_watch_open(self):
        job = self.job()
        p = self.run_("--pid", str(job.pid), "--max", "0.002")
        self.assertEqual(p.returncode, AT_MAX, p.stderr)
        w = self.only()
        self.assertEqual((p.stdout, p.stderr), (REARM.format(w["id"]), ""))
        self.assertEqual(w["state"], "open")
        self.assertNotIn("ended", w)

    def test_the_heartbeat_moves_on_every_poll(self):
        p = self.start("--pid", str(self.job().pid))
        first = self.waiting(p)["waiter_heartbeat"]
        self.until(lambda: self.all_watches()[0]["waiter_heartbeat"] > first, timeout=5)

    def test_resume_moves_the_watch_to_the_resuming_session(self):
        # A watch a crashed session left must be guarded in the session that re-arms it.
        job = self.job()
        p = self.run_("--pid", str(job.pid), "--max", "0.002", CLAUDE_CODE_SESSION_ID="s-old")
        self.assertEqual(p.returncode, AT_MAX, p.stderr)
        self.assertEqual(self.only()["session_id"], "s-old")
        p = self.run_("--resume", self.only()["id"], "--max", "0.002")
        self.assertEqual(p.returncode, AT_MAX, p.stderr)
        self.assertEqual(self.only()["session_id"], "s1")

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
        self.assertEqual((p.returncode, p.stdout), (AT_MAX, REARM.format(wid)))

    def test_resume_reopens_an_acknowledged_watch(self):
        job = self.job()
        wid = self.lapsed(job)
        self.update(wid, state="acknowledged", blocked_at=dc.now_iso())
        p = self.start("--resume", wid)
        self.assertEqual(self.waiting(p)["state"], "open")

    def test_resume_refuses_an_ended_watch(self):
        target = self.path("out")
        open(target, "w").close()
        self.assertEqual(self.run_("--file", target).returncode, 0)
        wid = self.only()["id"]
        p = self.run_("--resume", wid)
        self.assertEqual((p.returncode, p.stderr),
                         (USAGE, f"wait: watch {wid} is done; start a new wait\n"))

    def test_a_live_waiter_reopens_a_lapse_it_outlived(self):
        # The guard may call a waiter lapsed while its heartbeat is late (a suspended VM). A
        # waiter that polls again is live, so the lapse is over.
        p = self.start("--pid", str(self.job().pid))
        wid = self.waiting(p)["id"]
        self.update(wid, state="acknowledged", blocked_at=dc.now_iso())
        self.until(lambda: [(w["state"], w["blocked_at"]) for w in self.all_watches()]
                   == [("open", None)])

    def test_resume_is_refused_while_the_waiter_is_alive(self):
        first = self.start("--pid", str(self.job().pid))
        wid = self.waiting(first)["id"]
        p = self.run_("--resume", wid)
        self.assertEqual((p.returncode, p.stderr),
                         (USAGE, f"wait: watch {wid} already has a live waiter (pid "
                                 f"{first.pid}); it will notify its session\n"))
        self.assertIsNone(first.poll())

    def test_resume_with_no_session_keeps_the_watchs_session(self):
        wid = self.lapsed(self.job())
        p = self.run_("--resume", wid, "--max", "0.002", CLAUDE_CODE_SESSION_ID="")
        self.assertEqual(p.returncode, AT_MAX, p.stderr)
        self.assertEqual(self.only()["session_id"], "s1")

    def test_a_wait_with_no_session_says_the_guard_wont_see_it(self):
        target = self.path("out")
        open(target, "w").close()
        p = self.run_("--file", target, CLAUDE_CODE_SESSION_ID="")
        self.assertEqual((p.returncode, p.stderr),
                         (0, "no Claude Code session: the watch guard won't see this watch\n"))
        self.assertEqual(self.only()["session_id"], "unknown")

    def test_a_stale_waiter_is_taken_over_and_then_steps_aside(self):
        job = self.job()
        first = self.start("--pid", str(job.pid))
        wid = self.waiting(first)["id"]
        self.suspend(first)
        second = self.start("--resume", wid)
        self.waiting(second)
        first.send_signal(signal.SIGCONT)
        out, _ = self.finish(first, ASIDE)
        self.assertEqual(out, f"watch {wid} was taken over by pid {second.pid} (a --resume); "
                              "this waiter stepped aside, and the watch goes on\n")
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

    def test_drop_leaves_an_ended_watch_as_it_ended(self):
        target = self.path("out")
        open(target, "w").close()
        self.assertEqual(self.run_("--file", target).returncode, 0)
        wid = self.only()["id"]
        path = os.path.join(self.watches, f"{wid}.json")
        os.utime(path, (time.time() - 3 * 86400,) * 2)
        before = os.stat(path).st_mtime
        p = self.run_("--drop", wid)
        self.assertEqual((p.returncode, p.stdout), (0, f"watch {wid} is already done\n"))
        self.assertEqual(self.only()["state"], "done")
        self.assertEqual(os.stat(path).st_mtime, before)  # not rewritten: its prune clock holds

    def test_drop_makes_a_running_waiter_step_aside(self):
        p = self.start("--pid", str(self.job().pid))
        wid = self.waiting(p)["id"]
        self.assertEqual(self.run_("--drop", wid).returncode, 0)
        out, _ = self.finish(p, ASIDE)
        self.assertEqual(out, f"watch {wid} was dropped; this waiter stepped aside\n")
        self.assertEqual(self.only()["state"], "dropped")

    def test_a_deleted_watch_file_makes_its_waiter_step_aside(self):
        p = self.start("--pid", str(self.job().pid))
        wid = self.waiting(p)["id"]
        os.remove(os.path.join(self.watches, f"{wid}.json"))
        out, _ = self.finish(p, ASIDE)
        self.assertEqual(out, f"watch {wid}'s file is gone, so there is nothing left to wait "
                              "on; this waiter stepped aside\n")
        self.assertEqual(self.all_watches(), [])

    def test_a_killed_waiter_leaves_the_watch_open_with_no_live_waiter(self):
        p = self.start("--pid", str(self.job().pid))
        self.waiting(p)
        p.send_signal(signal.SIGKILL)
        p.wait()
        w = self.only()
        self.assertEqual((w["state"], w["waiter_pid"]), ("open", p.pid))
        self.assertFalse(dc.waiter_alive(w))

    def test_an_internal_error_exits_70_and_logs_the_traceback(self):
        p = self.start("--pid", str(self.job().pid))
        self.waiting(p)
        os.chmod(self.watches, 0o500)  # the next heartbeat can't write its temp file
        self.addCleanup(os.chmod, self.watches, 0o700)
        _, err = self.finish(p, ERROR)
        self.assertTrue(err.startswith("wait: PermissionError: "), err)
        with open(os.path.join(self.state, "dotclaude", "delegation-ledger.err")) as f:
            self.assertIn("PermissionError", f.read())

    def test_unknown_and_malformed_ids_exit_64(self):
        os.makedirs(self.watches)
        with open(os.path.join(self.watches, "w-torn.json"), "w") as f:
            f.write("{")
        with open(os.path.join(self.watches, "w-list.json"), "w") as f:
            f.write("[]")
        for wid in ("w-nope", "../x", ".lock", "a/b", "", "w-torn", "w-list"):
            for opt in ("--resume", "--drop"):
                p = self.run_(opt, wid)
                self.assertEqual(p.returncode, USAGE, (opt, wid, p.stderr))
                self.assertTrue(p.stderr.startswith("wait: "), p.stderr)
        self.assertEqual(sorted(os.listdir(self.watches)), [".lock", "w-list.json",
                                                            "w-torn.json"])

    def test_the_help_lists_the_exit_codes(self):
        out = self.cli("wait", "--help")
        for line in ("0 done", "1 the job failed", "2 the log went stale",
                     "3 this waiter stepped aside", "64 bad usage", "70 internal error",
                     "75 still running at --max"):
            self.assertIn(line, " ".join(out.split()))


class Usage(WaitEnv):
    def test_bad_usage_exits_64_and_records_nothing(self):
        log = self.path("job.log")
        cases = [
            [], ["--done", "x"], ["--fail", "x", "--pid", "1"], ["--stale", "1", "--pid", "1"],
            ["--log", log], ["--log", log, "--fail", "x"], ["--log", log, "--stale", "1"],
            ["--log", log, "--done", "("], ["--log", log, "--done", "x", "--stale", "0"],
            ["--log", log, "--done", ""], ["--pid", "0"], ["--pid", "x"],
            ["--pid", "1", "--max", "0"], ["--pid", "1", "--max", "nan"],
            ["--pid", "1", "--poll", "0"], ["--codex", "r1", "--pid", "1"],
            ["--codex", "r-unknown"], ["--resume", "w-x", "--pid", "1"],
            ["--drop", "w-x", "--desc", "y"], ["--resume", "w-x", "--drop", "w-x"],
            ["--bogus"], ["--pid", "1", "stray"],
        ]
        for argv in cases:
            p = self.run_(*argv, poll=False)
            self.assertEqual(p.returncode, USAGE, (argv, p.stderr))
            self.assertTrue(p.stderr, argv)
        self.assertFalse(os.path.exists(self.state))

    def test_max_stays_under_the_bash_cap(self):
        target = self.path("out")
        open(target, "w").close()
        p = self.run_("--file", target, "--max", "110.5")
        self.assertEqual((p.returncode, p.stderr),
                         (USAGE, "wait: --max must be at most 110, under the Bash tool's "
                                 "120-minute cap with room for a finalize\n"))
        self.assertEqual(self.run_("--file", target, "--max", "110").returncode, 0)

    def test_other_subcommands_keep_exit_2_for_bad_usage(self):
        p = subprocess.run(["python3", LEDGER, "tail", "--bogus"], capture_output=True,
                           text=True, env=self.env)
        self.assertEqual(p.returncode, 2, p.stderr)

    def test_a_sandboxed_run_is_refused_before_anything_is_written(self):
        target = self.path("out")
        open(target, "w").close()
        for argv in (["--file", target], ["--resume", "w-x"], ["--drop", "w-x"]):
            p = self.run_(*argv, CLAUDE_PID=str(DEAD))
            self.assertEqual((p.returncode, p.stdout, p.stderr), (USAGE, "", SANDBOXED), argv)
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
    """--codex runs `codex-delegate finalize` from beside the ledger, so these tests run a copy
    of the scripts with a stub codex-delegate next to it."""

    def setUp(self):
        super().setUp()
        bin_dir = self.path("bin")
        os.makedirs(bin_dir)
        for name in ("delegation-ledger", "delegation_common.py", "delegation_checks.py"):
            shutil.copy2(os.path.join(SCRIPTS, name), bin_dir)
        stub = os.path.join(bin_dir, "codex-delegate")
        with open(stub, "w") as f:
            f.write(FINALIZE_STUB)
        os.chmod(stub, 0o755)
        self.script = os.path.join(bin_dir, "delegation-ledger")
        self.argv_file = self.path("argv")
        self.env["STUB_ARGV"] = self.argv_file

    def codex_row(self, rid, pid, **kw):
        path = os.path.join(self.state, "dotclaude", "delegations.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(dict({"runner": "codex", "id": rid, "run_id": rid,
                                     "thread_id": f"t-{rid}", "event": "start",
                                     "ts": dc.now_iso(), "out": self.path(rid), "pid": pid,
                                     "wrapper_pid": pid}, **kw)) + "\n")

    def finalized(self):
        with open(self.argv_file) as f:
            return f.read()

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
        self.assertEqual(self.finalized(), "finalize r1\n")
        self.assertEqual(self.only()["state"], "done")

    def test_a_finalized_run_that_failed_exits_1(self):
        self.codex_row("r1", DEAD)
        p = self.run_("--codex", "r1", STUB_EXIT="4")
        self.assertEqual(p.returncode, 1, p.stderr)
        w = self.only()
        self.assertEqual(p.stdout, f"stub finalized r1\nwatch {w['id']} failed: codex run r1 "
                                   "stopped with exit 4\n")
        self.assertEqual(w["state"], "failed")

    def err_log(self):
        with open(os.path.join(self.state, "dotclaude", "delegation-ledger.err")) as f:
            return f.read()

    def stops(self):
        with open(os.path.join(self.state, "dotclaude", "delegations.jsonl")) as f:
            return [r for r in map(json.loads, f) if r.get("event") == "stop"]

    def test_a_finalize_that_records_no_stop_row_leaves_the_watch_open(self):
        self.codex_row("r1", DEAD)
        p = self.run_("--codex", "r1", STUB_EXIT="2", STUB_NO_ROW="1")
        self.assertEqual(p.returncode, ERROR, p.stderr)
        w = self.only()
        self.assertEqual(p.stderr, f"wait: codex-delegate finalize r1 exited 2; watch {w['id']} "
                                   f"stays open, so `delegation-ledger wait --resume {w['id']}` "
                                   "tries again\n")
        self.assertEqual(w["state"], "open")
        self.assertIn("codex-delegate finalize r1 exited 2", self.err_log())
        p = self.run_("--resume", w["id"])  # this time finalize records its stop row
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.only()["state"], "done")

    def test_a_missing_codex_delegate_leaves_the_watch_open(self):
        os.remove(os.path.join(self.path("bin"), "codex-delegate"))
        self.codex_row("r1", DEAD)
        p = self.run_("--codex", "r1")
        self.assertEqual(p.returncode, ERROR, p.stderr)
        self.assertIn("codex-delegate finalize r1 didn't run", p.stderr)
        self.assertEqual(self.only()["state"], "open")

    def test_a_run_that_leaves_the_ledger_mid_wait_leaves_the_watch_open(self):
        codex = self.job()
        self.codex_row("r1", codex.pid)
        p = self.start("--codex", "r1")
        self.waiting(p)
        os.remove(os.path.join(self.state, "dotclaude", "delegations.jsonl"))
        _, err = self.finish(p, ERROR)
        self.assertTrue(err.startswith("wait: codex run r1 is no longer in the ledger"), err)
        self.assertEqual(self.only()["state"], "open")

    def test_a_slow_finalize_keeps_the_heartbeat_fresh(self):
        self.codex_row("r1", DEAD)
        p = self.start("--codex", "r1", STUB_SLEEP="2")
        self.until(lambda: os.path.exists(self.argv_file))  # finalize has begun
        time.sleep(1.5)  # past two polls and a second, when a silent waiter reads as dead
        w = self.only()
        self.assertEqual(w["finalizing"], {"pid": p.pid, "start": dc.proc_start(p.pid)})
        self.assertTrue(dc.waiter_alive(w))
        self.finish(p, 0)

    def test_a_second_watch_on_a_run_is_refused_in_any_session(self):
        codex = self.job()
        self.codex_row("r1", codex.pid)
        p = self.start("--codex", "r1")
        wid = self.waiting(p)["id"]
        live = (USAGE, f"wait: watch {wid} already has a live waiter (pid {p.pid}); it will "
                       "notify its session\n")
        for env in ({}, {"CLAUDE_CODE_SESSION_ID": "s9"}):
            again = self.run_("--codex", "r1", **env)
            self.assertEqual((again.returncode, again.stderr), live, env)
        p.kill()  # with its waiter gone, the refusal points at a resume
        p.wait()
        again = self.run_("--codex", "r1")
        self.assertEqual((again.returncode, again.stderr),
                         (USAGE, f"wait: watch {wid} already waits on r1: delegation-ledger "
                                 f"wait --resume {wid}\n"))

    def test_a_beat_that_fails_mid_finalize_still_waits_for_it(self):
        # The stub finalize holds until the test releases it, which it does only once the
        # failed heartbeat is in the error log, so the order doesn't depend on timing.
        self.codex_row("r1", DEAD)
        pidfile, release = self.path("stub.pid"), self.path("release")
        p = self.start("--codex", "r1", STUB_PIDFILE=pidfile, STUB_RELEASE=release)
        self.until(lambda: os.path.exists(pidfile) and os.path.getsize(pidfile))
        os.chmod(self.watches, 0o500)  # the next heartbeat can't write: an OSError
        self.addCleanup(os.chmod, self.watches, 0o700)
        self.until(lambda: "PermissionError" in self.err_log(), timeout=10)
        os.chmod(self.watches, 0o700)  # so the end can be recorded
        open(release, "w").close()
        out, _ = self.finish(p, 0)
        self.assertTrue(out.endswith("done: codex run r1 ends\n"), out)
        with open(pidfile) as f:
            self.assertFalse(dc.pid_alive(int(f.read())))  # waited on, not left running
        self.assertEqual((self.finalized(), len(self.stops())), ("finalize r1\n", 1))

    def test_a_resume_during_a_finalize_doesnt_finalize_again(self):
        # Only a stale waiter can be taken over. Its finalize still runs to the end, and the
        # new waiter, seeing a live finalizer, reads that stop row instead of writing another.
        self.codex_row("r1", DEAD)
        release = self.path("release")
        first = self.start("--codex", "r1", STUB_RELEASE=release)
        self.until(lambda: os.path.exists(self.argv_file))  # finalize has begun
        wid = self.only()["id"]
        self.suspend(first)
        second = self.start("--resume", wid)
        self.waiting(second)
        time.sleep(0.3)  # it polls past the finalizer marker without finalizing
        open(release, "w").close()
        out, _ = self.finish(second, 0)
        self.assertEqual(out, f"watch {wid} done: codex run r1 ends\n")
        first.send_signal(signal.SIGCONT)
        out, _ = self.finish(first, ASIDE)
        self.assertTrue(out.endswith(f"watch {wid} was taken over by pid {second.pid} (a "
                                     "--resume); this waiter stepped aside, and the watch goes "
                                     "on\n"), out)
        self.assertEqual(self.finalized(), "finalize r1\n")
        self.assertEqual(len(self.stops()), 1)

    def test_a_stop_row_s_exit_decides_without_a_finalize(self):
        self.codex_row("r1", DEAD, event="stop", exit=4)
        p = self.run_("--codex", "r1")
        self.assertEqual(p.returncode, 1, p.stderr)
        w = self.only()
        self.assertEqual(p.stdout, f"watch {w['id']} failed: codex run r1 stopped with exit 4\n")
        self.codex_row("r2", DEAD, event="stop", exit=0)
        p = self.run_("--codex", "r2")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(os.path.exists(self.argv_file))  # neither run was finalized again

    def test_a_live_wrapper_records_the_stop_before_any_finalize(self):
        # Codex has ended but its wrapper is still writing the stop row; finalizing then would
        # record a second one, so the waiter waits for the wrapper too.
        wrapper = self.job()
        self.codex_row("r1", DEAD, wrapper_pid=wrapper.pid)
        p = self.start("--codex", "r1")
        self.waiting(p)
        time.sleep(0.3)
        self.assertIsNone(p.poll())
        self.codex_row("r1", DEAD, wrapper_pid=wrapper.pid, event="stop", exit=0)
        self.finish(p, 0)
        self.assertFalse(os.path.exists(self.argv_file))

    def test_a_pending_run_waits_for_its_wrapper(self):
        wrapper = self.job()
        self.codex_row("r1", None, event="pending", wrapper_pid=wrapper.pid)
        p = self.start("--codex", "r1")
        self.waiting(p)
        time.sleep(0.3)
        self.assertIsNone(p.poll())
        self.end(wrapper)
        self.finish(p, 0)


class Prune(WaitEnv):
    def test_a_wait_prunes_old_temp_files_and_long_ended_watches(self):
        os.makedirs(self.watches)
        now = time.time()

        def put(name, age_days, state=None):
            path = os.path.join(self.watches, name)
            with open(path, "w") as f:
                f.write("{" if state is None else json.dumps({"id": name[:-5], "state": state}))
            os.utime(path, (now - age_days * 86400,) * 2)
        put(".w-a.json.x1.tmp", 2)
        put(".w-b.json.x2.tmp", 0.5)
        for state in ("done", "failed", "stale", "dropped"):
            put(f"w-{state}.json", 8, state)
        put("w-recent.json", 6, "done")
        put("w-open.json", 30, "open")
        put("w-ack.json", 30, "acknowledged")
        target = self.path("out")
        open(target, "w").close()
        self.assertEqual(self.run_("--file", target).returncode, 0)
        new = [w["id"] for w in self.all_watches() if "created" in w]  # this wait's own watch
        self.assertEqual(len(new), 1)
        left = set(os.listdir(self.watches)) - {f"{new[0]}.json"}
        self.assertEqual(left, {".lock", ".w-b.json.x2.tmp", "w-recent.json", "w-open.json",
                                "w-ack.json"})


class PidAlive(unittest.TestCase):
    def test_a_zombie_is_gone(self):
        p = subprocess.Popen(["sleep", "60"])
        self.addCleanup(p.wait)
        p.kill()  # not reaped, so it stays a zombie until the cleanup's wait

        def state():
            with open(f"/proc/{p.pid}/stat") as f:
                return f.read().rsplit(") ", 1)[1].split()[0]
        end = time.monotonic() + 5
        while state() != "Z":
            self.assertLess(time.monotonic(), end)
            time.sleep(0.01)
        start = dc.proc_start(p.pid)
        self.assertIsNotNone(start)
        self.assertFalse(dc.pid_alive(p.pid))
        self.assertFalse(dc.pid_alive(p.pid, start))

    def test_an_unreadable_stat_with_a_proc_entry_is_alive(self):
        with mock.patch.object(dc, "_stat_fields", return_value=None):
            self.assertTrue(dc.pid_alive(os.getpid()))


class Views(WaitEnv):
    def test_open_watches_print_in_their_own_block(self):
        wid = self.lapsed(self.job())
        lines = self.cli("watch").splitlines()
        self.assertEqual(lines[0], "no live delegations")
        self.assertEqual(lines[1:], [
            "open watches:",
            f"  {wid}  'pid {self.only()['condition']['pids'][0]['pid']} (sleep) exits'  no live "
            f"waiter ⚠ re-arm: delegation-ledger wait --resume {wid}"])
        self.assertEqual(self.cli("watch", "--summary"), "\n")
        out = self.cli("open").splitlines()
        self.assertEqual(out[0], "no unfinished delegations in the last 48h")
        self.assertEqual(out[1], "open watches:")
        self.assertTrue(out[2].startswith(f"  {wid}  open  'pid "), out)
        self.assertIn("session s1 alive, waiter pid", out[3])
        self.assertIn(f"re-arm: delegation-ledger wait --resume {wid}", out[3])

    def test_a_live_waiter_shows_as_waiting(self):
        job = self.job()
        p = self.start("--pid", str(job.pid), "--desc", "the build")
        wid = self.waiting(p)["id"]
        self.assertIn(f"  {wid}  'the build'  pid {job.pid} (sleep) exits  waiter alive",
                      self.cli("watch").splitlines())

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
