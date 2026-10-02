"""watch-guard: the main-thread Stop hook blocks once per lapsed watch and once per killed
task, records everything it blocks on, and always fails open. Transcripts here are synthetic,
in the 2.1.287 format."""
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


def notification(task, tool_use, desc, status="killed"):
    summary = (f'Background command "{desc}" was stopped after reaching its background time '
               "limit" if status == "killed" else f'Background command "{desc}" completed '
               "(exit code 0)")
    return (f"<task-notification>\n<task-id>{task}</task-id>\n<tool-use-id>{tool_use}"
            f"</tool-use-id>\n<output-file>/tmp/x/tasks/{task}.output</output-file>\n<status>"
            f"{status}</status>\n<summary>{summary}</summary>\n<note>{NOTE}</note>\n"
            "</task-notification>")


def notice(task, tool_use, desc, at, status="killed"):
    return {"type": "user", "timestamp": iso(at),
            "origin": {"kind": "task-notification", "producer": "session-task"},
            "message": {"role": "user", "content": notification(task, tool_use, desc, status)}}


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
        env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.state})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("DELEGATION_LEDGER", None)
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

    def decide(self, **kw):
        return guard.decide(self.payload(**kw), self.now)

    def err_log(self):
        try:
            with open(os.path.join(self.state, "dotclaude", "delegation-ledger.err")) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def lapse_reason(self, wid="w-1", desc="the build", cond=None, codex_ended=False):
        cond = cond or f"{self.path('never')} exists"
        unmet = f"{cond} is unmet" + (f" {guard.CODEX_ENDED}" if codex_ended else "")
        return (f"Watch {wid} ({desc}) has no live waiter and {unmet}. If a command was stopped "
                "at its time limit, don't re-run it. Re-arm the watch: delegation-ledger wait "
                f"--resume {wid}, with run_in_background and timeout 7200000. To stop watching "
                f"it: delegation-ledger wait --drop {wid}.")

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
        self.assertEqual(self.decide(), self.block(
            f"Watch w-1 (the build): {self.path('never')} exists is met, but its waiter had "
            "stopped, so no notification came. Check the result and report it."))
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
        ledger = os.path.join(self.state, "dotclaude", "delegations.jsonl")
        os.makedirs(os.path.dirname(ledger), exist_ok=True)
        with open(ledger, "w") as f:
            f.write(json.dumps({"runner": "codex", "id": "r1", "run_id": "r1", "event": "start",
                                "ts": dc.now_iso(), "pid": DEAD, "wrapper_pid": DEAD}) + "\n")
        self.watch(cond={"codex": "r1"}, desc="codex run r1 ends")
        self.assertEqual(self.decide(), self.block(self.lapse_reason(
            desc="codex run r1 ends", cond="codex run r1 ends", codex_ended=True)))
        self.assertEqual(self.read()["state"], "open")

    def test_a_lapse_blocks_once_then_is_acknowledged_with_a_warning(self):
        self.watch()
        self.assertEqual(self.decide(), self.block(self.lapse_reason()))
        dc.parse_iso(self.read()["blocked_at"])
        self.assertEqual(self.decide(), {"systemMessage": (
            "Watch w-1 (the build) still has no waiter; it's acknowledged. Re-arm with "
            "delegation-ledger wait --resume w-1, or drop it.")})
        self.assertEqual(self.read()["state"], "acknowledged")
        self.assertIsNone(self.decide())  # said once; `watch` and `open` still list it

    def test_a_doubled_guard_blocks_once_in_total(self):
        self.watch()
        outs = [self.decide(), self.decide()]
        self.assertEqual(sum("decision" in (o or {}) for o in outs), 1)

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

    def test_an_undecidable_watch_is_skipped_and_the_other_still_blocks(self):
        self.watch(wid="w-gone", cond={"codex": "r-gone"}, desc="codex run r-gone ends")
        self.watch(wid="w-2")
        self.assertEqual(self.decide(), self.block(self.lapse_reason(wid="w-2")))
        self.assertIn("watch-guard: watch w-gone", self.err_log())
        self.assertIn("no longer in the ledger", self.err_log())
        self.assertIsNone(self.read("w-gone")["blocked_at"])


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

    def test_a_killed_first_waiter_folds_into_the_one_lapsed_watch(self):
        self.watch()
        self.lines(launch("toolu_1", "bk1", f"delegation-ledger wait --file {self.path('x')}",
                          "wait for the build", self.now - 7200),
                   notice("bk1", "toolu_1", "wait for the build", self.now - 60))
        self.assertEqual(self.decide(), self.block(self.lapse_reason()))

    def test_a_kill_and_a_lapse_are_numbered_in_one_block(self):
        self.watch()
        self.lines(launch("toolu_1", "bk1", "make all", "the make", self.now - 7200),
                   notice("bk1", "toolu_1", "the make", self.now - 60))
        self.assertEqual(self.decide(), self.block(self.lapse_reason(),
                                                   self.kill_reason("the make")))
        self.assertIsNone(self.decide().get("decision"))  # the ack's systemMessage only

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

    def test_the_shim_exits_0_when_the_script_is_missing(self):
        with tempfile.TemporaryDirectory() as home:
            p = subprocess.run(["bash", SHIM], input=json.dumps(self.payload()),
                               capture_output=True, text=True, env=dict(os.environ, HOME=home))
        self.assertEqual((p.returncode, p.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
