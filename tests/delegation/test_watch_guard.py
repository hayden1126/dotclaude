"""watch-guard: the main-thread Stop hook blocks once per lapsed watch and once per killed
task, records everything it blocks on, and always fails open. Transcripts here are synthetic,
in the 2.1.287 format."""
import fcntl
import itertools
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from _paths import HOOKS, SCRIPTS, load_script

SCRIPT = os.path.join(SCRIPTS, "watch-guard")
SHIM = os.path.join(HOOKS, "watch-guard.sh")
dc = load_script("delegation_common.py")
guard = load_script("watch-guard")

DEAD = 2 ** 22 + 12345  # beyond pid_max on this box, so never alive
NOTE = ("If the work in progress still needs it, start it again with `run_in_background` and a "
        "longer `timeout`. If it already had the longest `timeout` allowed, do not restart it. "
        "Either way, report that it was stopped.")


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def notification(task, tool_use, desc, status="killed", output=None):
    summary = (f'Background command "{desc}" was stopped after reaching its background time '
               "limit" if status == "killed" else f'Background command "{desc}" completed '
               "(exit code 0)")
    return (f"<task-notification>\n<task-id>{task}</task-id>\n<tool-use-id>{tool_use}"
            f"</tool-use-id>\n<output-file>{output or f'/tmp/x/tasks/{task}.output'}"
            f"</output-file>\n<status>"
            f"{status}</status>\n<summary>{summary}</summary>\n<note>{NOTE}</note>\n"
            "</task-notification>")


def notice(task, tool_use, desc, at, status="killed", output=None):
    return {"type": "user", "timestamp": iso(at),
            "origin": {"kind": "task-notification", "producer": "session-task"},
            "message": {"role": "user",
                        "content": notification(task, tool_use, desc, status, output)}}


def queued(task, tool_use, desc, at):
    return {"type": "queue-operation", "timestamp": iso(at),
            "content": notification(task, tool_use, desc)}


def launch(tool_use, task, command, desc, at):
    """The assistant's background Bash call and its tool result."""
    return [{"type": "assistant", "timestamp": iso(at), "message": {"content": [
                {"type": "tool_use", "id": tool_use, "name": "Bash", "input": {
                    "command": command, "description": desc, "timeout": 7200000,
                    "run_in_background": True}}]}},
            {"type": "user", "timestamp": iso(at), "toolUseResult": {"backgroundTaskId": task},
             "message": {"content": [{"type": "tool_result", "tool_use_id": tool_use,
                                      "content": f"Command running in background with ID: "
                                                 f"{task}. Output is being written to: /tmp/x"}]}}]


class GuardEnv(unittest.TestCase):
    """A temp state dir, decide() run in process against it, and helpers to write watches,
    transcripts and ledger rows."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = os.path.join(self.tmp.name, "state")
        # A temp HOME, so the walk to a Claude process finds only the sessions files a test
        # writes there.
        self.home = os.path.join(self.tmp.name, "home")
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.state, "HOME": self.home})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("DELEGATION_LEDGER", None)
        # Inside the sandbox the lead's CLAUDE_PID is inherited but invisible, and SANDBOX_RUNTIME
        # is set, either of which would make the guard say nothing. The sandbox tests set them.
        os.environ.pop("CLAUDE_PID", None)
        os.environ.pop("SANDBOX_RUNTIME", None)
        self.watches = os.path.join(self.state, "dotclaude", "watches")
        self.transcript = self.path("s1.jsonl")
        self.now = time.time()

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def watch(self, wid="w-1", sid="s1", state="open", live=False, cond=None, desc="the build",
              **fields):
        w = {"id": wid, "session_id": sid, "state": state, "description": desc,
             "condition": cond or {"file": self.path("never")}, "created": dc.now_iso(),
             "waiter_pid": os.getpid() if live else DEAD,
             "waiter_start": dc.proc_start(os.getpid()) if live else None,
             "waiter_heartbeat": dc.now_iso(), "poll_s": 15, "blocked_at": None}
        w.update(fields)
        dc.write_json(os.path.join(self.watches, f"{wid}.json"), w)
        return w

    def read(self, wid="w-1"):
        return dc.read_watch(wid)

    def lines(self, *entries, raw_first=None):
        with open(self.transcript, "w") as f:
            if raw_first is not None:
                f.write(raw_first + "\n")
            for e in entries:
                if isinstance(e, list):
                    f.writelines(json.dumps(x) + "\n" for x in e)
                else:
                    f.write(json.dumps(e) + "\n")

    def payload(self, sid="s1", **kw):
        return dict({"hook_event_name": "Stop", "session_id": sid, "stop_hook_active": False,
                     "transcript_path": self.transcript, "background_tasks": []}, **kw)

    def decide(self, at=None, **kw):
        return guard.decide(self.payload(**kw), self.now if at is None else at)

    def append(self, *entries, raw=""):
        with open(self.transcript, "a") as f:
            f.writelines(json.dumps(e) + "\n" for e in entries)
            f.write(raw)

    def codex_row(self, rid="r1", **kw):
        ledger = os.path.join(self.state, "dotclaude", "delegations.jsonl")
        os.makedirs(os.path.dirname(ledger), exist_ok=True)
        with open(ledger, "a") as f:
            f.write(json.dumps(dict({"runner": "codex", "id": rid, "run_id": rid,
                                     "event": "start", "ts": dc.now_iso(), "pid": DEAD,
                                     "wrapper_pid": DEAD}, **kw)) + "\n")

    def met_reason(self, wid="w-1", desc="the build", cond=None):
        cond = cond or f"{self.path('never')} exists"
        return (f"Watch {wid} ({desc}): {cond} is met, but its waiter had stopped, so no "
                "notification came. Check the result and report it.")

    def err_log(self):
        try:
            with open(os.path.join(self.state, "dotclaude", "delegation-ledger.err")) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def lapse_reason(self, wid="w-1", desc="the build", cond=None):
        cond = cond or f"{self.path('never')} exists"
        unmet = f"{cond} is unmet"
        return (f"Watch {wid} ({desc}) has no live waiter and {unmet}. If a command was stopped "
                "at its time limit, don't re-run it. Re-arm the watch: delegation-ledger wait "
                f"--resume {wid}, with run_in_background and timeout 7200000. To stop watching "
                f"it: delegation-ledger wait --drop {wid}.")

    def codex_ended(self, wid="w-1", run="r1"):
        return (f"Watch {wid} (codex run {run} ends): codex run {run} has ended, but its waiter "
                "had stopped, so the run isn't finalized. Re-arm the watch and its waiter "
                f"finalizes it: delegation-ledger wait --resume {wid}, with run_in_background "
                f"and timeout 7200000. To stop watching it: delegation-ledger wait --drop {wid}.")

    def kill_reason(self, desc):
        return (f'Background command "{desc}" was stopped at its time limit. If it was waiting '
                "on a job that's still running, don't re-run it: wait with delegation-ledger "
                "wait (--pid, --file or --log), with run_in_background and timeout 7200000. If "
                "it was the job itself, report that it was stopped. If you've already handled "
                "it, end your turn.")

    def block(self, *reasons):
        return {"decision": "block", "reason": "[watch-guard]\n" + "\n".join(
            f"{n}. {r}" for n, r in enumerate(reasons, 1))}


class Watches(GuardEnv):
    def test_no_state_dir_and_no_transcript_allow(self):
        self.assertIsNone(self.decide())

    def test_no_watches_allow(self):
        os.makedirs(self.watches)
        self.lines()
        self.assertIsNone(self.decide())

    def test_another_sessions_watch_is_left_alone(self):
        self.watch(sid="s2")
        self.assertIsNone(self.decide())
        self.assertIsNone(self.read()["blocked_at"])

    def test_a_live_waiter_allows(self):
        self.watch(live=True)
        self.assertIsNone(self.decide())
        self.assertIsNone(self.read()["blocked_at"])

    def test_a_background_shell_holding_the_watch_id_counts_as_a_waiter(self):
        self.watch()
        tasks = [{"id": "b1", "type": "local_bash", "status": "running",
                  "description": "re-arm", "command": "delegation-ledger wait --resume w-1"}]
        self.assertIsNone(self.decide(background_tasks=tasks))

    def test_a_met_condition_with_a_dead_waiter_blocks_once_and_is_recorded_done(self):
        open(self.path("never"), "w").close()
        self.watch()
        self.assertEqual(self.decide(), self.block(self.met_reason()))
        w = self.read()
        self.assertEqual(w["state"], "done")
        dc.parse_iso(w["ended"])
        self.assertIsNone(self.decide())

    def test_a_met_condition_with_a_live_waiter_is_left_to_the_waiter(self):
        open(self.path("never"), "w").close()
        self.watch(live=True)
        self.assertIsNone(self.decide())
        self.assertEqual(self.read()["state"], "open")  # the waiter records the end itself

    def test_a_codex_run_that_ended_blocks_with_resume_and_isnt_recorded_done(self):
        # Its outcome is unknown until it is finalized, and the re-armed waiter finalizes it,
        # so the watch stays open: one block, then the lapse's acknowledgment.
        self.codex_row()
        self.watch(cond={"codex": "r1"}, desc="codex run r1 ends")
        self.lines()
        self.assertEqual(self.decide(prompt_id="p1"), self.block(self.codex_ended()))
        w = self.read()
        self.assertEqual(w["state"], "open")
        dc.parse_iso(w["end_blocked_at"])
        dc.parse_iso(w["blocked_at"])
        self.assertEqual(self.decide(prompt_id="p2"), {"systemMessage": self.ACK.replace(
            "w-1 (the build)", "w-1 (codex run r1 ends)")})
        self.assertIsNone(self.decide(prompt_id="p3"))
        self.assertEqual(self.read()["state"], "acknowledged")

    def test_an_acknowledged_lapse_whose_job_fails_or_goes_stale_ends_and_blocks_once(self):
        # An acknowledged lapse says nothing more, so a job that ends badly must be an end, not
        # another lapse, or nobody hears of it.
        log = self.path("build.log")
        open(log, "w").close()
        old = self.now - 7200
        os.utime(log, (old, old))
        never = self.path("never")
        self.watch(state="acknowledged", blocked_at=guard.iso(old), created=guard.iso(old - 60),
                   cond={"pids": [{"pid": DEAD, "start": None, "comm": "sleep"}], "file": never})
        self.watch("w-2", state="acknowledged", blocked_at=guard.iso(old), created=guard.iso(old),
                   cond={"log": log, "done": "^OK$", "stale_min": 1})
        self.lines()
        self.assertEqual(self.decide(), self.block(
            f"Watch w-1 (the build) ended failed: pid {DEAD} (sleep) exited, but {never} exists "
            "is unmet. Its waiter had stopped, so no notification came. Check the result and "
            "report it.",
            f"Watch w-2 (the build) ended stale: {log} unchanged for 1 min. Its waiter had "
            "stopped, so no notification came. Check the result and report it."))
        self.assertEqual([(w["state"], w["reported"]) for w in (self.read(), self.read("w-2"))],
                         [("failed", True), ("stale", True)])
        self.assertIsNone(self.decide(prompt_id="p2"))

    def test_an_acknowledged_codex_lapse_whose_run_ends_blocks_once_and_stays_open(self):
        # An acknowledged lapse says nothing more, so the run's end needs its own block.
        self.codex_row()
        self.watch(state="acknowledged", blocked_at=guard.iso(self.now - 600),
                   cond={"codex": "r1"}, desc="codex run r1 ends")
        self.lines()
        self.assertEqual(self.decide(prompt_id="p1"), self.block(self.codex_ended()))
        self.assertEqual(self.read()["state"], "acknowledged")
        self.assertIsNone(self.decide(prompt_id="p2"))
        self.assertIsNone(self.decide(prompt_id="p3"))
        self.assertEqual(self.read()["state"], "acknowledged")

    def test_twin_guards_at_the_runs_end_stop_block_once_and_dont_acknowledge(self):
        # The lapse blocked at an earlier stop and isn't acknowledged yet; the run then ends.
        self.codex_row()
        self.watch(blocked_at=guard.iso(self.now - 600), blocked_stop="0123",
                   cond={"codex": "r1"}, desc="codex run r1 ends")
        self.lines()
        self.assertEqual(self.decide(prompt_id="p5"), self.block(self.codex_ended()))
        self.assertIsNone(self.decide(prompt_id="p5"))  # its twin, in the same stop
        self.assertEqual(self.read()["state"], "open")
        self.assertEqual(self.decide(prompt_id="p6"), {"systemMessage": self.ACK.replace(
            "w-1 (the build)", "w-1 (codex run r1 ends)")})

    def test_a_rearm_clears_the_runs_end_block(self):
        # A waiter that takes the watch over (unblock) lets a later end block again.
        self.codex_row()
        self.watch(state="acknowledged", blocked_at=guard.iso(self.now - 600),
                   end_blocked_at=guard.iso(self.now - 300), blocked_stop="0123",
                   cond={"codex": "r1"}, desc="codex run r1 ends")
        self.lines()
        self.assertIsNone(self.decide(prompt_id="p1"))
        dc.update_watch("w-1", dc.unblock)  # what take() and beat() do
        self.assertNotIn("end_blocked_at", self.read())
        self.assertEqual(self.decide(prompt_id="p2"), self.block(self.codex_ended()))

    def test_a_running_codex_run_with_a_dead_waiter_is_a_plain_lapse(self):
        self.codex_row(pid=os.getpid())
        self.watch(cond={"codex": "r1"}, desc="codex run r1 ends")
        self.assertEqual(self.decide(), self.block(self.lapse_reason(
            desc="codex run r1 ends", cond="codex run r1 ends")))

    def test_a_codex_stop_row_decides_done_or_failed_for_a_dead_waiter(self):
        self.codex_row("r1", event="stop", exit=0)
        self.codex_row("r2", event="stop", exit=4)
        self.watch(cond={"codex": "r1"}, desc="codex run r1 ends", created="2026-10-02T10:00:00Z")
        self.watch("w-2", cond={"codex": "r2"}, desc="codex run r2 ends",
                   created="2026-10-02T10:00:01Z")
        self.assertEqual(self.decide(), self.block(
            self.met_reason(desc="codex run r1 ends", cond="codex run r1 ends"),
            "codex run r2 ended with exit 4, but its waiter had stopped, so no notification "
            "came. Check its report and report it."))
        self.assertEqual((self.read()["state"], self.read("w-2")["state"]), ("done", "failed"))
        self.assertIsNone(self.decide())

    ACK = ("Watch w-1 (the build) still has no waiter; it's acknowledged. Re-arm with "
           "delegation-ledger wait --resume w-1, or drop it.")

    def grow(self):
        """What a later stop's transcript looks like: the turn went on."""
        self.append({"type": "assistant", "timestamp": iso(self.now), "message": {"content": "."}})

    def test_a_lapse_blocks_once_then_is_acknowledged_with_a_warning(self):
        self.watch()
        self.lines()
        self.assertEqual(self.decide(), self.block(self.lapse_reason()))
        w = self.read()
        dc.parse_iso(w["blocked_at"])
        self.assertEqual(w["blocked_size"], os.path.getsize(self.transcript))
        self.grow()
        self.assertEqual(self.decide(at=self.now + 3), {"systemMessage": self.ACK})
        self.assertEqual(self.read()["state"], "acknowledged")
        self.grow()
        self.assertIsNone(self.decide(at=self.now + 6))  # said once; the views still list it

    def test_a_lapse_is_acknowledged_by_a_stop_with_another_digest(self):
        self.watch()
        self.lines()
        stop = {"prompt_id": "p1", "last_assistant_message": "Waiting on the build."}
        self.assertEqual(self.decide(**stop), self.block(self.lapse_reason()))
        w = self.read()
        self.assertEqual(w["blocked_stop"], guard.stop_digest(self.payload(**stop)))
        self.assertRegex(w["blocked_stop"], r"^[0-9a-f]{16}$")
        self.assertEqual(self.decide(at=self.now + 90, prompt_id="p1",
                                     last_assistant_message="Still no waiter."),
                         {"systemMessage": self.ACK})
        self.assertEqual(self.read()["state"], "acknowledged")

    def test_a_twin_guard_with_the_same_payload_doesnt_acknowledge_though_the_transcript_grew(
            self):
        self.watch()
        self.lines()
        stop = {"prompt_id": "p1", "last_assistant_message": "Waiting on the build."}
        self.assertEqual(self.decide(**stop), self.block(self.lapse_reason()))
        self.grow()  # a line landed between the twins
        self.assertIsNone(self.decide(at=self.now + 1, **stop))
        self.assertIsNone(self.decide(at=self.now + 90, **stop))  # nor does age, with a digest
        self.assertEqual(self.read()["state"], "open")
        self.assertEqual(self.decide(at=self.now + 91, prompt_id="p1",
                                     last_assistant_message="Still no waiter."),
                         {"systemMessage": self.ACK})

    def test_a_new_prompt_alone_is_a_later_stop(self):
        self.watch()
        self.lines()
        self.decide(prompt_id="p1", last_assistant_message="Done.")
        self.assertEqual(self.decide(prompt_id="p2", last_assistant_message="Done."),
                         {"systemMessage": self.ACK})

    def test_a_stop_with_neither_field_falls_back_to_the_size(self):
        self.watch()
        self.lines()
        self.decide(prompt_id="p1", last_assistant_message="Waiting on the build.")
        self.assertIsNone(self.decide(at=self.now + 90))  # same size: the same stop
        self.grow()
        self.assertEqual(self.decide(at=self.now + 91), {"systemMessage": self.ACK})

    def test_a_twin_guard_in_the_same_stop_neither_blocks_nor_acknowledges(self):
        # With neither prompt_id nor last_assistant_message in the payload, it sees the
        # transcript the first guard saw, so it knows the block is this stop's.
        self.watch()
        self.lines()
        self.assertEqual(self.decide(), self.block(self.lapse_reason()))
        self.assertIsNone(self.decide())
        self.assertIsNone(self.decide(at=self.now + 30))  # same size: still the same stop
        self.assertEqual(self.read()["state"], "open")
        self.grow()
        self.assertEqual(self.decide(at=self.now + 31), {"systemMessage": self.ACK})

    def test_with_no_transcript_size_a_minute_later_is_a_later_stop(self):
        self.watch()  # no transcript at all, and neither stop field
        self.assertEqual(self.decide(), self.block(self.lapse_reason()))
        self.assertIsNone(self.read()["blocked_size"])
        self.assertIsNone(self.read()["blocked_stop"])
        self.assertIsNone(self.decide(at=self.now + 30))
        self.assertEqual(self.decide(at=self.now + 90), {"systemMessage": self.ACK})

    def test_a_log_condition_is_checked_in_the_logs_last_megabyte(self):
        log = self.path("job.log")
        with open(log, "w") as f:
            f.write("BUILD OK\n" + ("x" * 1023 + "\n") * (guard.LOG_TAIL // 1024 + 10))
        self.watch(cond={"log": log, "done": "^BUILD OK$"}, desc="the log")
        cond = f"{log} has a line matching /^BUILD OK$/"
        self.assertEqual(self.decide(), self.block(self.lapse_reason(desc="the log", cond=cond)))
        with open(log, "a") as f:
            f.write("BUILD OK\n")  # now inside the last megabyte
        self.assertEqual(self.decide(), self.block(self.met_reason(desc="the log", cond=cond)))

    def long_log(self, *tail):
        """A log whose first line is OK, then more than the guard's 1 MB of filler, then
        `tail`."""
        log = self.path("build.log")
        with open(log, "w") as f:
            f.write("OK\n" + ("x" * 1023 + "\n") * (guard.LOG_TAIL // 1024 + 10))
            f.writelines(line + "\n" for line in tail)
        return log

    def test_a_failed_verdict_the_logs_tail_cant_settle_is_a_lapse(self):
        # OK is further back than the guard reads, and the pid has exited. Recorded failed, the
        # watch would refuse the re-armed waiter, which reads the whole log and says done.
        cond = {"pids": [{"pid": DEAD, "start": None, "comm": "make"}], "log": self.long_log(),
                "done": "^OK$"}
        self.watch(cond=cond)
        self.lines()
        self.assertEqual(self.decide(), self.block(
            self.lapse_reason(cond=dc.condition_text(cond))))
        self.assertEqual(self.read()["state"], "open")

    def test_a_stale_verdict_the_logs_tail_cant_settle_is_a_lapse(self):
        log = self.long_log()
        old = self.now - 7200
        os.utime(log, (old, old))
        cond = {"log": log, "done": "^OK$", "stale_min": 1}
        self.watch(cond=cond, created=guard.iso(old))
        self.lines()
        self.assertEqual(self.decide(), self.block(
            self.lapse_reason(cond=dc.condition_text(cond))))
        self.assertEqual(self.read()["state"], "open")

    def test_a_fail_line_in_the_tail_or_a_short_logs_verdict_still_ends_the_watch(self):
        log = self.long_log("ERROR")
        self.watch(cond={"log": log, "done": "^OK$", "fail": "^ERROR$"},
                   created="2026-10-02T10:00:00Z")
        short = self.path("short.log")
        with open(short, "w") as f:
            f.write("building\n")
        self.watch("w-2", cond={"pids": [{"pid": DEAD, "start": None, "comm": "make"}],
                                "log": short, "done": "^OK$"}, created="2026-10-02T10:00:01Z")
        self.lines()
        self.assertEqual(self.decide(), self.block(
            f"Watch w-1 (the build) ended failed: {log} has a line matching /^ERROR$/. Its "
            "waiter had stopped, so no notification came. Check the result and report it.",
            f"Watch w-2 (the build) ended failed: pid {DEAD} (make) exited, but {short} has a "
            "line matching /^OK$/ is unmet. Its waiter had stopped, so no notification came. "
            "Check the result and report it."))
        self.assertEqual([self.read(w)["state"] for w in ("w-1", "w-2")], ["failed", "failed"])

    def test_a_spent_budget_takes_no_more_items_and_records_none_it_wont_print(self):
        self.watch(created="2026-10-02T10:00:00Z")
        self.watch("w-2", created="2026-10-02T10:00:01Z")
        self.lines(launch("toolu_1", "bk1", "make", "the make", self.now - 7200),
                   notice("bk1", "toolu_1", "the make", self.now - 60))
        ticks = itertools.chain([0, 0], itertools.repeat(10))  # spent after the first watch
        out = guard.decide(self.payload(), self.now, clock=lambda: next(ticks))
        self.assertEqual(out, self.block(self.lapse_reason()))
        self.assertIsNone(self.read("w-2")["blocked_at"])
        self.assertIn("budget is spent", self.err_log())
        self.assertEqual(self.decide(), self.block(self.lapse_reason("w-2"),
                                                   self.kill_reason("the make")))

    def test_a_sandboxed_guard_says_nothing_and_records_nothing(self):
        # Its own PID namespace hides every pid outside, so every waiter would read as lapsed.
        self.watch()
        self.lines(notice("bk1", "toolu_1", "the make", self.now - 60))
        with mock.patch.dict(os.environ, {"CLAUDE_PID": str(DEAD)}):
            self.assertIsNone(self.decide())
        self.assertIsNone(self.read()["blocked_at"])
        self.assertFalse(os.path.exists(os.path.join(self.state, "dotclaude", "kills")))

    def test_sandbox_runtime_makes_the_guard_say_nothing(self):
        self.watch()
        with mock.patch.dict(os.environ, {"SANDBOX_RUNTIME": "1"}):
            self.assertIsNone(self.decide())
        self.assertIsNone(self.read()["blocked_at"])

    def session_file(self, pid, sid="s-claude"):
        """A sessions file for pid, as Claude Code writes one, in the test's HOME."""
        sessions = os.path.join(self.home, ".claude", "sessions")
        os.makedirs(sessions, exist_ok=True)
        with open(os.path.join(sessions, f"{pid}.json"), "w") as f:
            json.dump({"pid": pid, "procStart": dc.proc_start(pid), "sessionId": sid}, f)

    def test_a_stale_claude_pid_under_a_live_claude_process_still_guards(self):
        # A CLAUDE_PID inherited from a process that has ended, while the walk finds the live
        # Claude process this hook runs under (this test's parent stands in for it).
        self.session_file(os.getppid())
        self.watch()
        with mock.patch.dict(os.environ, {"CLAUDE_PID": str(DEAD)}):
            self.assertEqual(self.decide(), self.block(self.lapse_reason()))

    def test_an_inherited_claude_pid_doesnt_make_a_nested_guard_adopt_the_leads_watch(self):
        # A nested claude -p (this test's parent) inherited the lead's CLAUDE_PID; after the
        # lead's /clear, the lead's old session isn't live.
        lead = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (lead.kill(), lead.wait()))
        self.session_file(lead.pid, "s-lead-new")
        self.session_file(os.getppid(), "s1")
        self.watch(sid="s-lead-old", claude_pid=lead.pid, claude_start=dc.proc_start(lead.pid))
        self.lines()
        with mock.patch.dict(os.environ, {"CLAUDE_PID": str(lead.pid)}):
            self.assertEqual(guard.dc.claude_process(), (os.getppid(),
                                                         dc.proc_start(os.getppid())))
            self.assertIsNone(self.decide())
        self.assertEqual(self.read()["session_id"], "s-lead-old")

    def test_stop_hook_active_doesnt_stop_a_fresh_lapse_blocking(self):
        self.watch()
        self.assertEqual(self.decide(stop_hook_active=True), self.block(self.lapse_reason()))

    def test_a_dropped_or_ended_watch_is_ignored(self):
        self.watch(state="dropped")
        self.watch(wid="w-2", state="done")
        self.assertIsNone(self.decide())

    def test_a_rearmed_waiter_resets_the_block(self):
        self.watch()
        self.decide()
        self.watch(live=True)  # what a --resume's take() writes: blocked_at cleared
        self.assertIsNone(self.decide())

    def mine(self, sid="s-before", **fields):
        """A watch recorded under this test's process, which plays the Claude process."""
        return self.watch(sid=sid, claude_pid=os.getpid(),
                          claude_start=dc.proc_start(os.getpid()), **fields)

    def as_claude(self, live=("s1",)):
        """Run as the Claude process (CLAUDE_PID is this test), with `live` the live sessions.
        Returns the live_sessions mock."""
        env = mock.patch.dict(os.environ, {"CLAUDE_PID": str(os.getpid())})
        sessions = mock.patch.object(guard.dc, "live_sessions",
                                     return_value={s: os.getpid() for s in live})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(sessions.stop)
        return sessions.start()

    def test_a_watch_left_by_clear_is_adopted_and_guarded(self):
        # /clear starts a new session id in the same Claude process, and the old id isn't live.
        self.mine()
        self.lines()
        self.as_claude()
        self.assertEqual(self.decide(), self.block(self.lapse_reason()))
        self.assertEqual(self.read()["session_id"], "s1")
        self.assertIn("adopted watch w-1 from session s-before", self.err_log())

    def test_a_watch_this_process_recorded_with_no_session_is_adopted(self):
        self.mine(sid="unknown")
        self.lines()
        self.as_claude()
        self.assertEqual(self.decide(), self.block(self.lapse_reason()))
        self.assertEqual(self.read()["session_id"], "s1")
        self.assertIn("adopted watch w-1 from session unknown: the same Claude process (a "
                      "/clear, or a watch recorded with no session)", self.err_log())

    def ack(self, wid):
        return (f"Watch {wid} (the build) still has no waiter; it's acknowledged. Re-arm with "
                f"delegation-ledger wait --resume {wid}, or drop it.")

    def assert_blocks_afresh_then_acks(self):
        """w-1 (acknowledged) and w-2 (blocked, still open), both adopted at this stop: each
        blocks once, as a first lapse, then acknowledges, then says nothing."""
        self.assertEqual(self.decide(prompt_id="p1"), self.block(
            self.lapse_reason(), self.lapse_reason("w-2")))
        self.assertEqual([self.read(w)["state"] for w in ("w-1", "w-2")], ["open", "open"])
        self.assertEqual(self.decide(prompt_id="p2"),
                         {"systemMessage": f"{self.ack('w-1')} {self.ack('w-2')}"})
        self.assertIsNone(self.decide(prompt_id="p3"))

    def test_a_clear_adoption_blocks_on_an_old_lapse_again(self):
        # The conversation after /clear never saw the old block or its ack.
        old = {"blocked_at": guard.iso(self.now - 600), "blocked_stop": "0123", "blocked_size": 1}
        self.mine(state="acknowledged", created="2026-10-02T10:00:00Z", **old)
        self.mine(wid="w-2", created="2026-10-02T10:00:01Z", **old)
        self.lines()
        self.as_claude()
        self.assert_blocks_afresh_then_acks()
        self.assertEqual(self.read("w-2")["session_id"], "s1")

    def test_a_crash_adoption_blocks_on_an_old_lapse_again(self):
        old = {"blocked_at": guard.iso(self.now - 600), "blocked_stop": "0123",
               "claude_pid": DEAD, "claude_start": None}
        self.watch(state="acknowledged", created="2026-10-02T10:00:00Z", **old)
        self.watch("w-2", created="2026-10-02T10:00:01Z", **old)
        self.lines()
        self.as_claude()
        self.assert_blocks_afresh_then_acks()
        self.assertEqual(self.read("w-2")["claude_pid"], os.getpid())

    def test_a_live_sessions_watch_isnt_adopted_even_when_the_process_matches(self):
        self.mine()
        self.lines()
        self.as_claude(live=("s1", "s-before"))
        self.assertIsNone(self.decide())
        self.assertEqual(self.read()["session_id"], "s-before")
        self.assertNotIn("adopted", self.err_log())

    def test_adoption_is_checked_again_under_the_lock(self):
        # Between gather and commit, the old session came back (claude --resume elsewhere).
        self.mine()
        self.lines()
        sessions = self.as_claude()
        calls = itertools.count()
        sessions.side_effect = lambda: ({"s1": 1} if next(calls) == 0
                                        else {"s1": 1, "s-before": 2})
        self.assertIsNone(self.decide())
        self.assertEqual(self.read()["session_id"], "s-before")
        self.assertIsNone(self.read()["blocked_at"])
        self.assertNotIn("adopted", self.err_log())

    def test_a_watch_re_armed_elsewhere_after_gather_isnt_adopted(self):
        self.mine()
        self.lines()
        self.as_claude()
        real = guard.watch_pending

        def watch_pending(w, shells, now):
            p = real(w, shells, now)  # then another session's --resume takes the watch
            self.watch(sid="s-other", claude_pid=DEAD, claude_start=None)
            return p
        with mock.patch.object(guard, "watch_pending", watch_pending):
            self.assertIsNone(self.decide())
        self.assertEqual(self.read()["session_id"], "s-other")
        self.assertIsNone(self.read()["blocked_at"])

    def test_a_watch_of_a_dead_claude_process_isnt_adopted(self):
        self.watch(sid="s-before", claude_pid=DEAD, claude_start=None)
        self.lines()
        self.as_claude()
        self.assertIsNone(self.decide())
        self.assertEqual(self.read()["session_id"], "s-before")

    def unheard_reason(self, wid="w-1"):
        return (f"Watch {wid}'s waiter was started by a Claude Code process that has ended, so "
                f"its exit won't reach you. Re-arm it: delegation-ledger wait --resume {wid}, "
                "with run_in_background and timeout 7200000.")

    def ended_reason(self, state="done", wid="w-1", desc="the build"):
        return (f"Watch {wid} ({desc}) ended ({state}) while no Claude Code process was "
                "listening. Check the result and report it.")

    def test_a_crashed_processs_live_waiter_is_adopted_and_blocks_once(self):
        # A crash, then claude --continue: the same session id in a new Claude process.
        self.watch(live=True, claude_pid=DEAD, claude_start=None)
        self.lines()
        self.as_claude()
        self.assertEqual(self.decide(), self.block(self.unheard_reason()))
        w = self.read()
        self.assertEqual((w["claude_pid"], w["claude_start"], w["waiter_unheard"]),
                         (os.getpid(), dc.proc_start(os.getpid()), True))
        self.assertIn(f"adopted watch w-1 from Claude process {DEAD}, which has ended",
                      self.err_log())
        self.assertIsNone(self.decide(prompt_id="p2"))

    def test_a_crashed_processs_waiter_with_a_stale_heartbeat_is_marked_unheard(self):
        # Its process runs (a suspended VM made the heartbeat stale), so when it resumes its exit
        # goes to the ended process: --resume must be able to take it over.
        self.watch(live=True, claude_pid=DEAD, claude_start=None,
                   waiter_heartbeat=guard.iso(self.now - 3600))
        self.lines()
        self.as_claude()
        out = self.decide()
        self.assertIn(self.unheard_reason(), out["reason"])
        self.assertIs(self.read()["waiter_unheard"], True)
        # It resumes and beats again. A --resume elsewhere may still take it over, and its own
        # end is recorded unreported, so the guard and the nudge say it.
        dc.update_watch("w-1", lambda w: w.update(waiter_heartbeat=dc.now_iso()))
        dc.Waiter("w-1", 15, (None, "s2")).refuse_a_live_waiter(self.read())
        me = (os.getpid(), dc.proc_start(os.getpid()))
        dc.Waiter("w-1", 15, (me, "s1")).end("done")
        self.assertIs(self.read()["reported"], False)

    def test_a_crashed_processs_stale_waiter_whose_condition_is_met_says_only_the_end(self):
        # "Re-arm it" would contradict the end, and --resume refuses a done watch.
        open(self.path("never"), "w").close()
        self.watch(live=True, claude_pid=DEAD, claude_start=None,
                   waiter_heartbeat=guard.iso(self.now - 3600))
        self.lines()
        self.as_claude()
        self.assertEqual(self.decide(), self.block(self.met_reason()))
        self.assertEqual(self.read()["state"], "done")

    def test_a_crashed_processs_dead_waiter_is_adopted_and_lapses(self):
        self.watch(claude_pid=DEAD, claude_start=None)
        self.lines()
        self.as_claude()
        self.assertEqual(self.decide(), self.block(self.lapse_reason()))
        w = self.read()
        self.assertEqual(w["claude_pid"], os.getpid())
        self.assertNotIn("waiter_unheard", w)

    def test_without_its_own_process_the_guard_adopts_no_crashed_watch(self):
        self.watch(live=True, claude_pid=DEAD, claude_start=None)
        self.lines()
        with mock.patch.object(guard.dc, "claude_process", return_value=None):
            self.assertIsNone(self.decide())
        self.assertEqual(self.read()["claude_pid"], DEAD)

    def test_a_watch_that_ended_while_nobody_listened_blocks_once(self):
        self.watch(state="done", ended=guard.iso(self.now - 3600), claude_pid=DEAD,
                   claude_start=None, created="2026-10-02T10:00:00Z", reported=False)
        self.watch("w-2", state="stale", ended=guard.iso(self.now - 60), claude_pid=os.getpid(),
                   claude_start=dc.proc_start(os.getpid()), waiter_unheard=True,
                   created="2026-10-02T10:00:01Z", reported=False)
        self.lines()
        self.assertEqual(self.decide(), self.block(self.ended_reason(),
                                                   self.ended_reason("stale", "w-2")))
        self.assertEqual((self.read()["reported"], self.read("w-2")["reported"]), (True, True))
        self.assertIsNone(self.decide(prompt_id="p2"))

    def test_an_ended_watch_someone_heard_or_could_says_nothing(self):
        dead = {"claude_pid": DEAD, "claude_start": None, "reported": False}
        self.watch("w-1", state="done", ended=guard.iso(self.now - 60),
                   **dict(dead, reported=True))
        self.watch("w-2", state="failed", ended=guard.iso(self.now - 8 * 86400), **dead)
        self.watch("w-3", state="done", ended=guard.iso(self.now - 60), claude_pid=os.getpid(),
                   claude_start=dc.proc_start(os.getpid()), reported=False)  # its process runs
        self.watch("w-4", state="dropped", ended=guard.iso(self.now - 60), **dead)
        self.watch("w-5", sid="s-other", state="done", ended=guard.iso(self.now - 60), **dead)
        self.watch("w-6", state="done", ended=guard.iso(self.now - 60),
                   reported=False)  # no process recorded
        self.lines()
        self.assertIsNone(self.decide())

    def test_a_watch_that_ended_before_reported_existed_counts_as_reported(self):
        # No `reported` key at all: an end recorded before this field, which it can't judge.
        self.watch(state="done", ended=guard.iso(self.now - 60), claude_pid=DEAD,
                   claude_start=None)
        self.lines()
        self.assertIsNone(self.decide())
        self.assertNotIn("reported", self.read())

    def test_an_end_the_guard_says_is_recorded_reported(self):
        target = self.path("out")
        open(target, "w").close()
        self.watch(cond={"file": target}, claude_pid=DEAD, claude_start=None)
        self.lines()
        self.assertEqual(self.decide(), self.block(self.met_reason(cond=f"{target} exists")))
        self.assertEqual((self.read()["state"], self.read()["reported"]), ("done", True))
        self.assertIsNone(self.decide(prompt_id="p2"))

    def hold_watches_lock(self):
        """Take watches/.lock from another open file, as a busy twin would, until cleanup."""
        held = open(os.path.join(self.watches, ".lock"), "a")
        self.addCleanup(held.close)
        fcntl.flock(held, fcntl.LOCK_EX)
        self.addCleanup(fcntl.flock, held, fcntl.LOCK_UN)

    def test_adoption_and_the_items_are_one_update(self):
        # A twin takes watches/.lock right after the first update: a second would find it busy.
        self.watch(live=True, claude_pid=DEAD, claude_start=None, created="2026-10-02T10:00:00Z")
        self.watch("w-2", created="2026-10-02T10:00:01Z")
        self.lines()
        self.as_claude()
        real, calls = guard.dc.update_watches, []

        def update_watches(fns, until=None, clock=time.monotonic):
            if calls:
                raise guard.dc.LockBusy("watches/.lock")
            calls.append(fns)
            out = real(fns, until, clock)
            self.hold_watches_lock()
            return out
        with mock.patch.object(guard.dc, "update_watches", update_watches):
            self.assertEqual(self.decide(), self.block(self.unheard_reason(),
                                                       self.lapse_reason("w-2")))
        self.assertEqual(sorted(calls[0]), ["w-1", "w-2"])

    def test_a_busy_watches_lock_adopts_nothing(self):
        self.watch(live=True, claude_pid=DEAD, claude_start=None)
        self.lines()
        self.as_claude()
        self.hold_watches_lock()
        with mock.patch.object(guard, "BUDGET_S", 0.1), \
                mock.patch.object(guard, "LOCK_GRACE_S", 0.1):
            self.assertIsNone(self.decide())
        self.assertEqual((self.read()["claude_pid"], self.read().get("waiter_unheard")),
                         (DEAD, None))
        self.assertIn("nothing was taken this stop", self.err_log())

    def test_an_undecidable_watch_is_skipped_and_the_other_still_blocks(self):
        self.watch(wid="w-gone", cond={"codex": "r-gone"}, desc="codex run r-gone ends")
        self.watch(wid="w-2")
        self.assertEqual(self.decide(), self.block(self.lapse_reason(wid="w-2")))
        self.assertIn("watch-guard: watch w-gone", self.err_log())
        self.assertIn("no longer in the ledger", self.err_log())
        self.assertIsNone(self.read("w-gone")["blocked_at"])

    def test_a_watch_whose_write_fails_is_unsaid_and_the_rest_go_on(self):
        self.watch(created="2026-10-02T10:00:00Z")
        before = self.watch("w-2", created="2026-10-02T10:00:01Z")
        self.lines(notice("bk1", "toolu_1", "the make", self.now - 60))
        real = guard.dc.write_json

        def write_json(path, obj):
            if path.endswith("w-2.json"):
                raise OSError(28, "No space left on device")
            return real(path, obj)
        with mock.patch.object(guard.dc, "write_json", write_json):
            out = self.decide(prompt_id="p1", last_assistant_message="m1")
        self.assertEqual(out, self.block(self.lapse_reason(), self.kill_reason("the make")))
        self.assertEqual(self.read("w-2"), before)
        self.assertIn("watch-guard: watch w-2", self.err_log())
        self.assertIn("No space left on device", self.err_log())
        out = self.decide(prompt_id="p1", last_assistant_message="m2")  # the next stop
        self.assertEqual(out, dict(self.block(self.lapse_reason("w-2")),
                                   systemMessage=self.ACK))


class Kills(GuardEnv):
    def test_a_killed_task_blocks_once_then_allows(self):
        self.lines(launch("toolu_1", "bk1", "sleep 9000", "long sleep", self.now - 7200),
                   notice("bk1", "toolu_1", "long sleep", self.now - 60))
        self.assertEqual(self.decide(), self.block(self.kill_reason("long sleep")))
        self.assertIsNone(self.decide())
        with open(os.path.join(self.state, "dotclaude", "kills", "s1.json")) as f:
            rec = json.load(f)
        self.assertEqual((rec["session_id"], rec["seen"]), ("s1", ["bk1"]))
        dc.parse_iso(rec["since"])

    def test_a_kill_older_than_the_first_runs_lookback_is_ignored(self):
        self.lines(notice("bk1", "toolu_1", "old", self.now - 3600))
        self.assertIsNone(self.decide())

    def test_since_holds_after_the_first_run(self):
        self.lines()
        self.assertIsNone(self.decide())  # the first run records since = now - 10 min
        later = self.now + 1800
        self.lines(notice("bk1", "toolu_1", "slow", later - 900))  # after since, before later
        self.assertEqual(guard.decide(self.payload(), later), self.block(self.kill_reason("slow")))

    def test_a_completed_task_and_a_queue_entry_are_ignored(self):
        self.lines(notice("bk1", "toolu_1", "quick", self.now - 60, status="completed"),
                   queued("bk2", "toolu_2", "queued", self.now - 60))
        self.assertIsNone(self.decide())

    def test_a_killed_waiter_folds_into_its_watchs_item(self):
        self.watch()
        self.lines(launch("toolu_1", "bk1", "delegation-ledger wait --resume w-1", "re-arm",
                          self.now - 7200),
                   notice("bk1", "toolu_1", "re-arm", self.now - 60))
        self.assertEqual(self.decide(), self.block(self.lapse_reason()))

    def test_a_killed_waiter_folds_into_the_watch_its_launch_line_names(self):
        # Two watches created in the launch window: only the launch line tells them apart, and
        # w-a's live waiter means a kill folded into it would still be said.
        launched = self.now - 7200
        made = iso(launched + 1)[:19] + "Z"
        self.watch("w-a", created=made, live=True)
        self.watch("w-b", created=made)
        output = self.path("bk1.output")
        with open(output, "w") as f:
            f.write("delegation-ledger: watch w-b. If this command is stopped, re-arm with "
                    "delegation-ledger wait --resume w-b (run_in_background, timeout 7200000)\n")
        self.lines(launch("toolu_1", "bk1", "delegation-ledger wait --pid 123", "wait", launched),
                   notice("bk1", "toolu_1", "wait", self.now - 60, output=output))
        self.assertEqual(self.decide(), self.block(self.lapse_reason("w-b")))

    def test_a_killed_first_waiter_folds_into_the_watch_it_created(self):
        launched = self.now - 7200
        self.watch(created=iso(launched + 2)[:19] + "Z")
        self.watch("w-old", created=iso(launched - 3600)[:19] + "Z")  # an older lapse
        self.lines(launch("toolu_1", "bk1", f"delegation-ledger wait --file {self.path('x')}",
                          "wait for the build", launched),
                   notice("bk1", "toolu_1", "wait for the build", self.now - 60))
        self.assertEqual(self.decide(), self.block(self.lapse_reason("w-old"),
                                                   self.lapse_reason()))

    def test_a_killed_waiter_with_no_item_this_stop_is_a_plain_kill(self):
        # Its watch is skipped as Undecidable, so the kill must still be said.
        self.watch("w-gone", cond={"codex": "r-gone"}, desc="codex run r-gone ends")
        self.lines(launch("toolu_1", "bk1", "delegation-ledger wait --resume w-gone", "re-arm",
                          self.now - 7200),
                   notice("bk1", "toolu_1", "re-arm", self.now - 60))
        self.assertEqual(self.decide(), self.block(self.kill_reason("re-arm")))

    def test_a_killed_codex_wrapper_says_codex_keeps_running(self):
        # The fold no longer guesses: an acknowledged watch with a dead waiter doesn't swallow
        # an unrelated codex kill.
        self.watch(state="acknowledged", blocked_at="2026-10-02T09:00:00Z")
        self.lines(launch("toolu_1", "bk1", "codex-delegate run --model terra --dir . --brief b",
                          "codex job", self.now - 7200),
                   launch("toolu_2", "bk2", "codex-delegate resume r7 --prompt p", "codex resume",
                          self.now - 7000),
                   notice("bk1", "toolu_1", "codex job", self.now - 60),
                   notice("bk2", "toolu_2", "codex resume", self.now - 50))
        codex = ('Codex wrapper "{}" was stopped at its time limit, but Codex keeps running. '
                 "Don't re-run it. Wait on it with delegation-ledger wait --codex {} "
                 "(codex-delegate status lists the run), with run_in_background and timeout "
                 "7200000.")
        unknown = ('Codex wrapper "codex job" was stopped at its time limit, but Codex keeps '
                   "running. Don't re-run it. Find the run with codex-delegate status, then wait "
                   "on it with delegation-ledger wait --codex and its run id, with "
                   "run_in_background and timeout 7200000.")
        self.assertEqual(self.decide(), self.block(unknown, codex.format("codex resume", "r7")))

    def test_a_killed_codex_wrapper_folds_into_the_watch_its_launch_line_names(self):
        # Two codex watches made in the launch window: the launch line tells them apart. w-a's
        # waiter lives, so it has no item, and a kill folded into it would still be said.
        launched = self.now - 7200
        made = iso(launched + 1)[:19] + "Z"
        self.codex_row("r1", pid=os.getpid())
        self.codex_row("r2", pid=os.getpid())  # Codex runs on
        self.watch("w-a", cond={"codex": "r1"}, desc="codex run r1 ends", created=made,
                   live=True)
        self.watch("w-b", cond={"codex": "r2"}, desc="codex run r2 ends", created=made)
        output = self.path("bk1.output")
        with open(output, "w") as f:
            f.write("codex-delegate: run r2, watch w-b. If this command is stopped, Codex keeps "
                    "running: delegation-ledger wait --resume w-b\n")
        self.lines(launch("toolu_1", "bk1", "codex-delegate run --model sol --dir . --brief b",
                          "codex job", launched),
                   notice("bk1", "toolu_1", "codex job", self.now - 60, output=output))
        self.assertEqual(self.decide(), self.block(self.lapse_reason(
            "w-b", desc="codex run r2 ends", cond="codex run r2 ends")))

    def test_a_kill_whose_watch_was_resolved_isnt_said(self):
        # codex-delegate cancel dropped the run's watch in the turn its wrapper was killed, and a
        # waiter's watch ended: a re-arm would be refused, so neither kill is said.
        launched = self.now - 7200
        self.codex_row("r2", pid=os.getpid())
        self.watch("w-b", state="dropped", ended=dc.now_iso(), cond={"codex": "r2"},
                   desc="codex run r2 ends")
        self.watch("w-c", state="done", ended=dc.now_iso(), reported=True)
        codex_out, wait_out = self.path("bk1.output"), self.path("bk2.output")
        with open(codex_out, "w") as f:
            f.write("codex-delegate: run r2, watch w-b. If this command is stopped, Codex keeps "
                    "running: delegation-ledger wait --resume w-b\n")
        with open(wait_out, "w") as f:
            f.write("delegation-ledger: watch w-c. If this command is stopped, re-arm with "
                    "delegation-ledger wait --resume w-c (run_in_background, timeout 7200000)\n")
        self.lines(launch("toolu_1", "bk1", "codex-delegate run --model sol --dir . --brief b",
                          "codex job", launched),
                   launch("toolu_2", "bk2", "delegation-ledger wait --resume w-c", "the wait",
                          launched),
                   notice("bk1", "toolu_1", "codex job", self.now - 60, output=codex_out),
                   notice("bk2", "toolu_2", "the wait", self.now - 50, output=wait_out))
        self.assertIsNone(self.decide())
        log = self.err_log()
        self.assertIn("kill of task bk1 folds into watch w-b, which is dropped, so it isn't said",
                      log)
        self.assertIn("kill of task bk2 folds into watch w-c, which is done, so it isn't said",
                      log)
        self.assertIsNone(self.decide(prompt_id="p2"))
        self.assertEqual(log, self.err_log())  # recorded seen, so not judged again

    def test_a_pending_run_with_a_live_codex_pid_file_is_running(self):
        out = self.path("r1-out")
        dc.write_json(os.path.join(out, "codex.pid"), {"pid": os.getpid(), "wrapper_pid": DEAD,
                                                       "start": dc.proc_start(os.getpid())})
        self.codex_row("r1", event="pending", out=out)  # its wrapper SIGKILLed after the Popen
        self.watch(cond={"codex": "r1"}, desc="codex run r1 ends")
        self.assertEqual(self.decide(), self.block(self.lapse_reason(
            desc="codex run r1 ends", cond="codex run r1 ends")))  # neither unstarted nor ended

    def test_a_codex_launch_line_after_other_output_still_folds(self):
        # A resume's finalize-first summary, or wrap()'s systemd-run warning, can come first.
        self.codex_row("r2", pid=os.getpid())
        self.watch("w-b", cond={"codex": "r2"}, desc="codex run r2 ends")
        output = self.path("bk1.output")
        with open(output, "w") as f:
            f.write("codex-delegate: systemd-run not found, running without a memory cap\n"
                    "codex-delegate: run r2 ended without a stop row; finalizing it first\n"
                    '{\n  "run_id": "r2"\n}\n'
                    "codex-delegate: run r2, watch w-b. If this command is stopped, Codex keeps "
                    "running: delegation-ledger wait --resume w-b\n")
        self.lines(launch("toolu_1", "bk1", "codex-delegate resume r2", "codex resume",
                          self.now - 3000),
                   notice("bk1", "toolu_1", "codex resume", self.now - 60, output=output))
        self.assertEqual(self.decide(), self.block(self.lapse_reason(
            "w-b", desc="codex run r2 ends", cond="codex run r2 ends")))

    def test_an_unstarted_codex_run_fails_its_watch_once(self):
        self.codex_row("r1", event="pending", thread_id="th-1")  # a resume's wrapper died first
        self.codex_row("r2", event="pending")  # a first turn's
        self.watch(cond={"codex": "r1"}, desc="codex run r1 ends", created="2026-10-02T10:00:00Z")
        self.watch("w-2", cond={"codex": "r2"}, desc="codex run r2 ends",
                   created="2026-10-02T10:00:01Z")
        unstarted = ("Watch {} (codex run {} ends): codex run {} never started, since its wrapper "
                     "stopped before Codex did, so the watch is recorded failed. To retry, {}, "
                     "with run_in_background and timeout 7200000.")
        self.assertEqual(self.decide(), self.block(
            unstarted.format("w-1", "r1", "r1", "run codex-delegate resume r1 again"),
            unstarted.format("w-2", "r2", "r2",
                             "run codex-delegate run again; it gets a new run id")))
        self.assertEqual((self.read()["state"], self.read("w-2")["state"]), ("failed", "failed"))
        self.assertIsNone(self.decide(at=self.now + 90, last_assistant_message="later"))

    def test_an_unfolded_codex_kill_re_arms_the_runs_open_watch(self):
        self.codex_row("r1", pid=os.getpid())
        self.watch("w-c", sid="s2", cond={"codex": "r1"}, desc="codex run r1 ends")  # not ours
        self.lines(launch("toolu_1", "bk1", "codex-delegate resume r1", "codex resume",
                          self.now - 3000),
                   notice("bk1", "toolu_1", "codex resume", self.now - 60))
        self.assertEqual(self.decide(), self.block(
            'Codex wrapper "codex resume" was stopped at its time limit, but Codex keeps '
            "running. Don't re-run it. Re-arm the run's watch: `delegation-ledger wait "
            "--resume w-c`, with run_in_background and timeout 7200000."))

    def test_a_kill_and_a_lapse_are_numbered_in_one_block(self):
        self.watch()
        self.lines(launch("toolu_1", "bk1", "make all", "the make", self.now - 7200),
                   notice("bk1", "toolu_1", "the make", self.now - 60))
        self.assertEqual(self.decide(), self.block(self.lapse_reason(),
                                                   self.kill_reason("the make")))
        self.assertNotIn("decision", self.decide(at=self.now + 30) or {})  # each said once

    def test_a_mid_turn_attachment_notice_counts_once(self):
        text = notification("bk1", "toolu_1", "mid-turn")
        at = iso(self.now - 60)
        self.lines({"type": "attachment", "timestamp": at, "uuid": "u1",
                    "attachment": {"type": "queued_command", "prompt": text, "timestamp": at,
                                   "origin": {"kind": "task-notification",
                                              "producer": "session-task"},
                                   "source_uuid": "s", "delivery_id": "d"},
                    "rendered": f"<system-reminder>{text}</system-reminder>"},
                   notice("bk1", "toolu_1", "mid-turn", self.now - 30))
        self.assertEqual(self.decide(), self.block(self.kill_reason("mid-turn")))

    def test_a_notice_followed_by_more_than_the_tail_is_caught_next_stop(self):
        self.lines()
        self.assertIsNone(self.decide())  # the first run records offset 0
        pad = {"type": "assistant", "timestamp": iso(self.now), "message": {"content": "x" * 900}}
        self.append(notice("bk1", "toolu_1", "buried", self.now - 60),
                    *[pad] * (300 * 1024 // 900))
        self.assertGreater(os.path.getsize(self.transcript), 300 * 1024)
        self.assertEqual(self.decide(), self.block(self.kill_reason("buried")))

    def test_a_line_still_being_written_is_read_once_complete(self):
        self.lines()
        line = json.dumps(notice("bk1", "toolu_1", "straddling", self.now - 60))
        self.append(raw=line[:100])  # half of it, as a stop might find it
        self.assertIsNone(self.decide())
        self.append(raw=line[100:] + "\n")
        self.assertEqual(self.decide(), self.block(self.kill_reason("straddling")))

    def test_a_notice_after_more_than_16_mb_is_still_caught(self):
        self.lines()
        self.decide()
        with open(self.transcript, "ab") as f:
            f.write(b'{"type": "progress", "x": "' + b"x" * (17 << 20) + b'"}\n')
        self.append(notice("bk1", "toolu_1", "far down", self.now - 60))
        self.assertEqual(self.decide(), self.block(self.kill_reason("far down")))

    def test_two_waits_launched_together_fold_by_their_condition(self):
        launched = self.now - 7200
        made = iso(launched + 2)[:19] + "Z"
        self.watch("w-a", cond={"file": self.path("a")}, created=made)
        self.watch("w-b", cond={"file": self.path("b")}, created=made)
        self.lines(launch("toolu_1", "bk1", "delegation-ledger wait --file b", "wait for b",
                          launched),
                   notice("bk1", "toolu_1", "wait for b", self.now - 60))
        out = self.decide(cwd=self.tmp.name)  # --file b is relative to the session's cwd
        self.assertEqual(out["reason"].count("\n"), 2, out)  # two lapses, the kill folded
        self.assertNotIn("was stopped at its time limit.", out["reason"])

    def test_a_slow_lookup_past_the_budget_records_only_what_it_says(self):
        self.lines(notice("bk1", "toolu_1", "first", self.now - 60),
                   notice("bk2", "toolu_2", "second", self.now - 50))

        def slow(path, tool_use, spent):
            time.sleep(0.4)  # longer than the whole budget
            return None
        start = time.monotonic()
        with mock.patch.object(guard, "BUDGET_S", 0.3), mock.patch.object(guard, "launched",
                                                                           slow):
            out = self.decide()
        self.assertLess(time.monotonic() - start, 0.3 + 0.4 + 0.5)
        self.assertEqual(out, self.block(self.kill_reason("first")))
        with open(os.path.join(self.state, "dotclaude", "kills", "s1.json")) as f:
            self.assertEqual(json.load(f)["seen"], ["bk1"])  # bk2 waits, unsaid and unseen
        self.assertEqual(self.decide(), self.block(self.kill_reason("second")))

    def test_a_held_lock_means_nothing_is_taken_this_stop(self):
        self.watch()
        self.lines(notice("bk1", "toolu_1", "held", self.now - 60))
        lock_path = os.path.join(self.state, "dotclaude", "kills", "s1.lock")
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        with open(lock_path, "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            with mock.patch.object(guard, "BUDGET_S", 0.1), \
                    mock.patch.object(guard, "LOCK_GRACE_S", 0.1):
                self.assertIsNone(self.decide())
            fcntl.flock(held, fcntl.LOCK_UN)
        self.assertIsNone(self.read()["blocked_at"])
        self.assertIn("nothing was taken this stop", self.err_log())
        self.assertEqual(self.decide(), self.block(self.lapse_reason(), self.kill_reason("held")))

    def test_another_sessions_kill_is_ignored(self):
        other = self.path("s2.jsonl")
        with open(other, "w") as f:
            f.write(json.dumps(notice("bk1", "toolu_1", "theirs", self.now - 60)) + "\n")
        self.lines()
        self.assertIsNone(self.decide())
        self.assertIsNotNone(self.decide(sid="s2", transcript_path=other))
        self.assertIsNone(self.decide())

    def test_only_the_tail_is_scanned_and_a_torn_first_line_is_skipped(self):
        old = notice("bk0", "toolu_0", "beyond the tail", self.now - 60)
        pad = {"type": "assistant", "timestamp": iso(self.now), "message": {"content": "x" * 900}}
        self.lines(old, [pad] * (guard.TAIL_BYTES // 900 + 5),
                   notice("bk1", "toolu_1", "in the tail", self.now - 60))
        self.assertEqual(self.decide(), self.block(self.kill_reason("in the tail")))
        self.lines(notice("bk2", "toolu_2", "after junk", self.now - 60), raw_first='{"torn')
        self.assertEqual(self.decide(), self.block(self.kill_reason("after junk")))

    def test_old_kill_records_are_pruned(self):
        os.makedirs(os.path.join(self.state, "dotclaude", "kills"))
        stale = os.path.join(self.state, "dotclaude", "kills", "s9.json")
        with open(stale, "w") as f:
            json.dump({"session_id": "s9", "since": dc.now_iso(), "seen": []}, f)
        os.utime(stale, (self.now - 8 * 86400,) * 2)
        self.lines()
        self.decide()
        self.assertFalse(os.path.exists(stale))

    def test_this_sessions_old_record_and_lock_arent_pruned(self):
        # A session idle for a week keeps what it has seen: pruning its record would block on
        # the same kill again.
        self.lines(notice("bk1", "toolu_1", "seen", self.now - 60))
        kills = os.path.join(self.state, "dotclaude", "kills")
        os.makedirs(kills)
        record, lock = os.path.join(kills, "s1.json"), os.path.join(kills, "s1.lock")
        with open(record, "w") as f:
            json.dump({"session_id": "s1", "since": iso(self.now - 600), "seen": ["bk1"],
                       "transcript": self.transcript, "offset": 0}, f)
        open(lock, "w").close()
        for p in (record, lock):
            os.utime(p, (self.now - 8 * 86400,) * 2)
        self.assertIsNone(self.decide())
        self.assertTrue(os.path.exists(record) and os.path.exists(lock))

    def test_the_offset_is_checked_against_what_the_scan_read(self):
        # A size read before the last lines landed doesn't drop the scan's end offset.
        self.lines(notice("bk1", "toolu_1", "late", self.now - 60))
        with mock.patch.object(guard, "file_size", lambda path: 10):
            self.assertEqual(self.decide(), self.block(self.kill_reason("late")))
        with open(os.path.join(self.state, "dotclaude", "kills", "s1.json")) as f:
            self.assertEqual(json.load(f)["offset"], os.path.getsize(self.transcript))


class FailsOpen(GuardEnv):
    def run_hook(self, payload, raw=False, cmd=None, env=None):
        p = subprocess.run(cmd or ["python3", SCRIPT],
                           input=payload if raw else json.dumps(payload), capture_output=True,
                           text=True, env=env or dict(os.environ))
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout) if p.stdout.strip() else None

    def test_malformed_payloads_allow(self):
        self.watch()
        for raw in ("not json", "", "[]", '{"session_id": 7}'):
            self.assertIsNone(self.run_hook(raw, raw=True), raw)
        self.assertIsNone(self.read()["blocked_at"])

    def test_a_missing_transcript_still_checks_the_watches(self):
        self.watch()
        out = self.run_hook(self.payload(transcript_path=self.path("missing.jsonl")))
        self.assertEqual(out, self.block(self.lapse_reason()))

    def test_a_subagents_stop_is_skipped(self):
        self.watch()
        self.assertIsNone(self.run_hook(self.payload(agent_id="a1", agent_type="writer")))

    def shim_home(self):
        home = self.path("home")
        os.makedirs(os.path.join(home, ".claude", "skills", "delegation"))
        os.symlink(SCRIPTS, os.path.join(home, ".claude", "skills", "delegation", "scripts"))
        return dict(os.environ, HOME=home)

    def test_the_shim_runs_the_guard_and_skips_an_agent_payload(self):
        self.watch()
        env = self.shim_home()
        p = subprocess.run(["bash", SHIM], input=json.dumps(self.payload(agent_id="a1")),
                           capture_output=True, text=True, env=env)
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertEqual(self.run_hook(self.payload(), cmd=["bash", SHIM], env=env),
                         self.block(self.lapse_reason()))

    def test_a_nested_agent_id_doesnt_skip_a_main_thread_stop(self):
        # background_tasks can hold a stale teammate; only a top-level agent_id is a subagent.
        self.watch()
        tasks = [{"id": "t1", "type": "in_process_teammate", "status": "running",
                  "description": "mate", "agent_id": "amate-0123456789abcdef"}]
        self.assertEqual(self.run_hook(self.payload(background_tasks=tasks), cmd=["bash", SHIM],
                                       env=self.shim_home()), self.block(self.lapse_reason()))

    def test_the_shim_exits_0_when_the_script_is_missing_and_logs_why(self):
        with tempfile.TemporaryDirectory() as home:
            p = subprocess.run(["bash", SHIM], input=json.dumps(self.payload()),
                               capture_output=True, text=True, env=dict(os.environ, HOME=home))
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertIn("No such file or directory", self.err_log())

    def test_the_shim_still_runs_the_guard_when_its_log_cant_be_written(self):
        self.watch()
        env = dict(self.shim_home(), XDG_STATE_HOME=self.state)
        os.makedirs(os.path.join(self.state, "dotclaude", "delegation-ledger.err"))  # a dir
        self.assertEqual(self.run_hook(self.payload(), cmd=["bash", SHIM], env=env),
                         self.block(self.lapse_reason()))


if __name__ == "__main__":
    unittest.main()
