"""hooks/stop-check.sh: the Stop hook that blocks a lane turn's end once when the turn ends with
nothing to wait on (stdlib only).

The transcripts are synthetic, in the shapes 2.1.319 writes (read from lane transcripts,
2026-11-09): every user entry of a turn carries the turn's promptId, which is the Stop payload's
prompt_id; a typed prompt has origin.kind "human", a background task's notice "task-notification",
another session's message "peer" (with isMeta); a tool_use sits in an assistant entry and its
tool_result in the next user entry. decide() runs in-process for the rules; the shim runs end to
end in a real lanes repo (tests/lanes/_fixture.py) for the lane test and failing open.
"""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, "hooks")
SHIM = os.path.join(HOOKS, "stop-check.sh")
sys.path.insert(0, os.path.join(REPO, "tests", "lanes"))
from _fixture import LanesRepo  # noqa: E402  (on sys.path from the line above)

SID = "7a2b3c4d-1111-2222-3333-444455556666"
PID = "0f1e2d3c-aaaa-bbbb-cccc-ddddeeeeffff"
OLD = "9e8d7c6b-aaaa-bbbb-cccc-ddddeeeeffff"


def load():
    spec = importlib.util.spec_from_file_location("stop_check",
                                                  os.path.join(HOOKS, "stop_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc = load()


def typed(text="is 9b pushed?", pid=PID):
    return {"type": "user", "promptId": pid, "origin": {"kind": "human"},
            "promptSource": "typed", "message": {"role": "user", "content": text}}


def notice(pid=PID):
    return {"type": "user", "promptId": pid,
            "origin": {"kind": "task-notification", "producer": "session-task"},
            "message": {"role": "user", "content": "<task-notification>\n<task-id>a1</task-id>\n"
                        "<status>completed</status>\n</task-notification>"}}


def peer(pid=PID):
    return {"type": "user", "promptId": pid, "isMeta": True, "origin": {"kind": "peer"},
            "message": {"role": "user", "content": "Another Claude session sent a message:\n"
                        "<cross-session-message from=\"uds:/tmp/lead.sock\">main moved"
                        "</cross-session-message>"}}


def reminder(pid=PID):
    return {"type": "user", "promptId": pid, "isMeta": True,
            "message": {"role": "user", "content": "<system-reminder>\n"
                        "<tools-used-before-summary>Grep</tools-used-before-summary>\n"
                        "</system-reminder>"}}


def say(text="Step 1 is committed."):
    return {"type": "assistant", "message": {"role": "assistant",
                                             "content": [{"type": "text", "text": text}]}}


def use(tid, name, **inp):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def result(tid, content="ok", error=False, pid=PID, **extra):
    block = {"tool_use_id": tid, "type": "tool_result", "content": content}
    if error:
        block["is_error"] = True
    return {"type": "user", "promptId": pid, "message": {"role": "user", "content": [block]},
            **extra}


def turn_end():
    return {"type": "system", "subtype": "stop_hook_summary"}


class Rules(unittest.TestCase):
    """decide() in-process, with the lane already resolved."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = os.path.join(self.tmp, "state")
        patch = mock.patch.dict(os.environ, XDG_STATE_HOME=self.state,
                                HOME=os.path.join(self.tmp, "home"))
        patch.start()
        self.addCleanup(patch.stop)
        self.transcript = os.path.join(self.tmp, SID + ".jsonl")

    def entries(self, *rows):
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "permission-mode", "permissionMode": "default"}) + "\n")
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")

    def forget(self):
        """Drop the block-once record, so the next case of a test may block again."""
        shutil.rmtree(os.path.join(self.state, "dotclaude", "stop-check"), True)

    def payload(self, last="Step 1 is committed.", **extra):
        return {"session_id": SID, "prompt_id": PID, "transcript_path": self.transcript,
                "hook_event_name": "Stop", "stop_hook_active": False,
                "permission_mode": "auto", "last_assistant_message": last,
                "background_tasks": [], **extra}

    def decide(self, last="Step 1 is committed.", lane="alpha", **extra):
        payload = {"session_id": SID, "prompt_id": PID, "transcript_path": self.transcript,
                   "hook_event_name": "Stop", "stop_hook_active": False,
                   "permission_mode": "auto", "last_assistant_message": last,
                   "background_tasks": [], **extra}
        return sc.decide(payload, lane)

    def assertBlocks(self, out):
        self.assertIsNotNone(out, "expected a block")
        self.assertEqual(out["decision"], "block")
        self.assertTrue(out["reason"].startswith(sc.MARKER), out["reason"])
        return out["reason"]

    def log(self):
        try:
            with open(os.path.join(self.state, "dotclaude", "stop-check.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    # ---- who started the turn (rule 7) ----
    def test_a_notification_turn_with_nothing_to_wait_on_blocks(self):
        self.entries(notice(), say())
        reason = self.assertBlocks(self.decide())
        for part in ("Next", "Asks for Hayden", "Waiting on you", "park me", "pass skill"):
            self.assertIn(part, reason)
        self.assertIn("block " + SID, self.log())

    def test_a_turn_started_by_hayden_ends_free(self):
        self.entries(typed(), say("Yes, at abc123."))
        self.assertIsNone(self.decide("Yes, at abc123."))

    def test_a_typed_turn_that_approved_a_plan_gets_the_test(self):
        self.entries(typed("plan it"), use("t1", "ExitPlanMode", plan="# Plan"),
                     result("t1", "User has approved your plan."), say())
        self.assertBlocks(self.decide())

    def test_a_rejected_plan_leaves_the_turn_hayden_s(self):
        self.entries(typed("plan it"), use("t1", "ExitPlanMode", plan="# Plan"),
                     result("t1", "The user doesn't want to proceed with this tool use.",
                            error=True, toolDenialKind="user-rejected"), say())
        self.assertIsNone(self.decide())

    def test_prompts_that_pass_and_lane_open_type_are_not_hayden_s(self):
        for text in ("Read your lane record .lane/STATUS.md, then continue with the approved "
                     "next step.",
                     "You are lane `alpha`. Read your lane record `/x/.lane/STATUS.md`, then "
                     "plan the brief it holds."):
            with self.subTest(text=text[:20]):
                self.forget()
                self.entries(typed(text), say())
                self.assertBlocks(self.decide())

    def test_a_peer_message_turn_gets_the_test(self):
        self.entries(peer(), say("Noted."))
        self.assertBlocks(self.decide("Noted."))

    def test_a_meta_reminder_ahead_of_the_starting_entry_is_passed_over(self):
        self.entries(reminder(), notice(), say())
        self.assertBlocks(self.decide())
        self.forget()
        self.entries(reminder(), typed(), say())
        self.assertEqual(sc.explain(self.payload(), "alpha")[1], "hayden")

    def test_a_typed_slash_command_is_hayden_s(self):
        slash = {"type": "user", "promptId": PID, "message": {"role": "user", "content":
                 "<command-message>review</command-message>\n<command-name>/review"
                 "</command-name>"}}
        self.entries(slash, say())
        self.assertIsNone(self.decide())
        # a notice later in the same turn doesn't make it someone else's
        self.entries(slash, use("t1", "Agent", prompt="x"), result("t1", "launched"), notice(),
                     say())
        self.assertEqual(sc.explain(self.payload(), "alpha")[1], "hayden")

    def test_only_the_current_turn_counts(self):
        self.entries(typed("go", pid=OLD), use("t0", "SendMessage", to="uds:/tmp/lead.sock",
                                                message="park me"),
                     result("t0", "sent", pid=OLD), say("Sent."), turn_end(),
                     notice(), say())
        self.assertBlocks(self.decide())

    def test_a_prompt_id_missing_from_the_transcript_fails_open_with_a_log_line(self):
        self.entries(notice(pid=OLD), say())
        self.assertIsNone(self.decide())
        self.assertIn("no turn start", self.log())

    # ---- block once (rule 2) ----
    def test_a_continued_stop_never_blocks(self):
        self.entries(notice(), say())
        self.assertIsNone(self.decide(stop_hook_active=True))

    def test_a_second_stop_of_a_blocked_prompt_never_blocks(self):
        self.entries(notice(), say())
        self.assertBlocks(self.decide())
        self.assertIsNone(self.decide())

    # ---- plan mode (rule 3) ----
    def test_plan_mode_ends_free(self):
        self.entries(notice(), say())
        self.assertIsNone(self.decide(permission_mode="plan"))

    # ---- a Waiting on you list (rule 4) ----
    def test_a_waiting_on_you_line_ends_free(self):
        self.entries(notice(), say())
        for last in ("Done.\n\n**Waiting on you:**\n- approve the push", "Waiting on you:\n- x",
                     "## Waiting on you\n- x", "  - **Waiting on you:** approve"):
            with self.subTest(last=last):
                self.assertIsNone(self.decide(last))

    def test_a_wait_line_on_anyone_else_ends_free(self):
        self.entries(notice(), say())
        for last in ("Pushed.\n\nWaiting on lane themes: its release, then I run the guardrail.",
                     "Waiting on the lead: its reply about the install.",
                     "- **Waiting for** Victor's answers on #433.",
                     "Waiting on Hayden: approval to push."):
            with self.subTest(last=last):
                self.forget()
                self.assertIsNone(self.decide(last))

    def test_the_reason_teaches_the_wait_line(self):
        self.entries(notice(), say())
        self.assertIn("`Waiting on <who>: <what>`", self.assertBlocks(self.decide()))

    def test_the_words_mid_line_are_no_list(self):
        self.entries(notice(), say())
        self.assertBlocks(self.decide("Nothing is waiting on you now."))
        self.forget()
        self.assertBlocks(self.decide("I'm done here; no longer waiting for the review."))

    # ---- background work (rule 5) ----
    def test_running_background_work_ends_free(self):
        self.entries(notice(), say())
        for kind in ("shell", "subagent", "workflow", "cloud session", "teammate"):
            with self.subTest(kind=kind):
                self.assertIsNone(self.decide(background_tasks=[
                    {"id": "b1", "type": kind, "status": "running", "description": "x"}]))

    def test_a_task_nobody_waits_on_does_not_count(self):
        self.entries(notice(), say())
        art = {"id": "s1", "type": "monitor", "status": "running",
               "description": "live updates for artifact https://claude.ai/x (auto-armed on "
                              "publish)"}
        dream = {"id": "d1", "type": "dream", "status": "running", "description": "x"}
        self.assertBlocks(self.decide(background_tasks=[art, dream, "junk"]))

    # ---- a message or a pass (rule 6) ----
    def test_a_message_to_the_lead_or_a_lane_ends_free(self):
        self.entries(notice(), use("t1", "SendMessage", to="uds:/tmp/claude/lead.sock",
                                   message="park me"), result("t1", "sent"), say("Sent."))
        self.assertIsNone(self.decide("Sent."))

    def test_a_message_to_a_subagent_or_a_failed_send_does_not_count(self):
        self.entries(notice(), use("t1", "SendMessage", to="a1b2c3d4e5", message="go on"),
                     result("t1", "sent"), say())
        self.assertBlocks(self.decide())
        self.forget()
        self.entries(notice(), use("t1", "SendMessage", to="uds:/tmp/lead.sock", message="x"),
                     result("t1", "no such peer", error=True), say())
        self.assertBlocks(self.decide())

    def test_the_pass_skill_ends_free(self):
        self.entries(notice(), use("t1", "Skill", skill="pass"), result("t1", "Launching"),
                     say())
        self.assertIsNone(self.decide())
        self.entries(notice(), use("t1", "Skill", skill="lanes"), result("t1", "Launching"),
                     say())
        self.assertBlocks(self.decide())

    def test_a_pass_respawn_command_ends_free(self):
        # the pass skill's compact mode runs it from Bash; the Skill call may be turns back
        self.entries(notice(), use("t1", "Bash", command="pass-respawn -C /x/lane --compact"),
                     result("t1", "ok"), say("The pane compacts after this turn."))
        self.assertIsNone(self.decide("The pane compacts after this turn."))
        self.entries(notice(), use("t1", "Bash", command="grep -n pass-respawn README.md"),
                     result("t1", "ok"), say())
        self.assertBlocks(self.decide())

    def test_a_pending_pass_ends_free(self):
        self.entries(notice(), say())
        d = os.path.join(self.state, "dotclaude", "pass-pending")
        os.makedirs(d)
        fd = os.open(os.path.join(d, SID + ".lock"), os.O_CREAT | os.O_RDWR)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.assertIsNone(self.decide())

    # ---- not a lane's main thread (rule 1) ----
    def test_outside_a_lane_or_in_a_subagent_never_blocks(self):
        self.entries(notice(), say())
        self.assertIsNone(self.decide(lane=None))
        self.assertIsNone(self.decide(agent_id="a1"))

    # ---- the record the board and `lane asks` read ----
    def record(self):
        with open(os.path.join(self.state, "dotclaude", "stop-check", SID + ".json")) as f:
            return json.load(f)

    def test_every_lane_stop_records_its_verdict(self):
        self.entries(notice(), use("t1", "SendMessage", to="uds:/tmp/lead.sock", message="q"),
                     result("t1", "sent"), say("Asked the lead."))
        self.assertIsNone(self.decide("Asked the lead."))
        rec = self.record()
        self.assertEqual((rec["prompt_id"], rec["why"], rec["waits"], rec["blocked"]),
                         (PID, "message", [], None))
        self.assertIsNone(self.decide(lane=None))  # outside a lane: nothing written
        self.assertEqual(self.record()["why"], "message")

    def test_a_continued_stop_records_the_full_verdict(self):
        self.entries(notice(), say())
        self.assertBlocks(self.decide())
        self.assertEqual(sc.explain(self.payload(stop_hook_active=True), "alpha")[1], "continued")
        self.assertEqual((self.record()["why"], self.record()["blocked"]), ("block", PID))
        last = "Nothing applies.\n\nWaiting on lane api-docs: its release."
        self.assertEqual(sc.explain(self.payload(last, stop_hook_active=True), "alpha")[1],
                         "waiting-list")
        self.assertEqual((self.record()["why"], self.record()["blocked"]), ("waiting-list", PID))

    def test_the_waiting_on_you_items_are_recorded_and_kept_over_an_empty_stop(self):
        self.entries(notice(), say())
        self.decide("Pushed.\n\n**Waiting on you:**\n- approve the push\n- pick A or B\n")
        self.assertEqual(self.record()["waits"], ["approve the push", "pick A or B"])
        # a sibling hook's block continues the turn, which then ends with no text
        self.assertIsNone(self.decide("", stop_hook_active=True))
        self.assertEqual((self.record()["why"], self.record()["waits"]),
                         ("waiting-list", ["approve the push", "pick A or B"]))

    def test_a_continuation_without_a_list_keeps_the_turns_list(self):
        # a sibling hook (context-watch, watch-guard) blocks a stop that ended on the list,
        # and the continuation ends on other text
        self.entries(notice(), say())
        self.decide("Pushed.\n\nWaiting on you:\n- approve the push")
        self.assertIsNone(self.decide("Noted.", stop_hook_active=True))
        self.assertEqual((self.record()["why"], self.record()["waits"]),
                         ("waiting-list", ["approve the push"]))

    def test_a_fresh_prompt_blocks_after_an_earlier_one_was_blocked(self):
        self.entries(notice(pid=OLD), say(), turn_end(), notice(), say())
        self.assertBlocks(sc.explain(self.payload(prompt_id=OLD), "alpha")[0])
        self.assertBlocks(self.decide())
        self.assertEqual(self.record()["blocked"], PID)

    def test_a_lone_surrogate_in_an_item_becomes_a_question_mark(self):
        self.assertEqual(sc.hayden_waits("Waiting on you:\n- a\ud800b"), ["a?b"])

    def test_old_records_are_pruned(self):
        self.entries(notice(), say())
        d = os.path.join(self.state, "dotclaude", "stop-check")
        os.makedirs(d)
        old = os.path.join(d, "gone-session.json")
        with open(old, "w") as f:
            f.write("{}")
        os.utime(old, (1, 1))
        self.decide("Waiting on you: x")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(os.path.join(d, SID + ".json")))

    def test_wait_items(self):
        cases = {
            "Ready.\n\n**Waiting on you:** approve the merge of #5.": ["approve the merge of #5."],
            "Waiting on you:\n\n- a\n- b\nThanks.\n- not this": ["a", "b"],
            "## Waiting on Hayden\n1. merge\n2) push": ["merge", "push"],
            "Waiting on lane x: its release.": [],
            "No list here.": [],
        }
        for text, items in cases.items():
            with self.subTest(text=text[:20]):
                self.assertEqual(sc.hayden_waits(text), items)
        self.assertEqual(len(sc.hayden_waits("Waiting on you:\n" + "- x\n" * 50)), sc.ITEMS_MAX)

    # ---- the reason ----
    def test_the_reason_names_the_soft_tier_once_past_it(self):
        self.entries(notice(), say())
        d = os.path.join(self.state, "dotclaude", "ctx")
        os.makedirs(d)
        with open(os.path.join(d, SID + ".json"), "w") as f:
            json.dump({"tokens": 350000, "time": 1.0, "window": 600000}, f)
        reason = self.assertBlocks(self.decide())
        self.assertIn("350k", reason)
        self.assertIn("300k", reason)

    def test_the_reason_without_a_count_still_names_the_pass(self):
        self.entries(notice(), say())
        self.assertIn("pass skill", self.assertBlocks(self.decide()))


class Shim(LanesRepo):
    """hooks/stop-check.sh end to end, in a real lanes repo with lane alpha."""

    def setUp(self):
        super().setUp()
        self.lane("new", "alpha")
        self.transcript = os.path.join(self.tmp, SID + ".jsonl")
        self.launched(self.lane_path("alpha"))

    def launched(self, cwd):
        """The transcript, its first entry recording the session's launch dir as cwd."""
        with open(self.transcript, "w") as f:
            for r in (dict(notice(), cwd=cwd), say()):
                f.write(json.dumps(r, separators=(",", ":")) + "\n")

    def fire(self, cwd, raw=None, env=None, **extra):
        payload = {"session_id": SID, "prompt_id": PID, "transcript_path": self.transcript,
                   "cwd": cwd, "hook_event_name": "Stop", "stop_hook_active": False,
                   "permission_mode": "auto", "last_assistant_message": "Step 1 is committed.",
                   "background_tasks": [], **extra}
        p = subprocess.run(["bash", SHIM], input=json.dumps(payload) if raw is None else raw,
                           capture_output=True, text=True, timeout=30,
                           env={**self.env, **(env or {})})
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        return json.loads(p.stdout) if p.stdout.strip() else None

    def err(self):
        try:
            with open(os.path.join(self.env["XDG_STATE_HOME"], "dotclaude",
                                   "stop-check.err")) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def test_a_lane_session_is_blocked(self):
        out = self.fire(self.lane_path("alpha"))
        self.assertEqual(out["decision"], "block")
        self.assertTrue(out["reason"].startswith(sc.MARKER))

    def test_the_main_checkout_and_a_plain_dir_never_block(self):
        for cwd in (self.main, self.tmp):
            with self.subTest(cwd=cwd):
                self.launched(cwd)
                self.assertIsNone(self.fire(cwd))

    def test_the_launch_dir_decides_not_a_later_cd(self):
        # a Bash `cd` moves the payload's cwd: the lead cd'd into a lane is still the lead
        self.launched(self.main)
        self.assertIsNone(self.fire(self.lane_path("alpha")))
        self.launched(self.lane_path("alpha"))
        self.assertEqual(self.fire(self.main)["decision"], "block")

    def test_an_unattended_session_never_blocks(self):
        self.assertIsNone(self.fire(self.lane_path("alpha"),
                                    env={"CLAUDE_CODE_SESSION_ATTENDED": "0"}))

    def test_a_bad_payload_fails_open_with_a_logged_line(self):
        self.assertIsNone(self.fire(self.lane_path("alpha"), raw="{not json"))
        self.assertIn("JSONDecodeError", self.err())


if __name__ == "__main__":
    unittest.main()
