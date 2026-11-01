"""report-check: our roles' reports are sent back at most twice, and it always fails open."""
import json
import os
import re
import subprocess
import tempfile
import time
import unittest

from _paths import HOOKS, SCRIPTS

SCRIPT = os.path.join(SCRIPTS, "report-check")
SHIM = os.path.join(HOOKS, "report-check.sh")
VALID = {"status": "done", "summary": "ok", "artifacts": [], "blocked_actions": []}
GOOD = "Findings.\n\n```json\n" + json.dumps(VALID) + "\n```\n"


class ReportCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, XDG_STATE_HOME=os.path.join(self.tmp.name, "state"))
        self.proj_dir = os.path.join(self.tmp.name, "projects", "-p")
        os.makedirs(os.path.join(self.proj_dir, "s1", "subagents"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, payload, raw=False):
        p = subprocess.run(["python3", SCRIPT], input=payload if raw else json.dumps(payload),
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0)
        return json.loads(p.stdout) if p.stdout.strip() else None

    def base(self, atype="Explore", aid="a1"):
        return {"agent_id": aid, "agent_type": atype, "session_id": "s1",
                "transcript_path": os.path.join(self.proj_dir, "s1.jsonl")}

    def handback(self, msg, **kw):
        return dict(self.base(**kw), hook_event_name="PreToolUse", tool_name="SubagentHandback",
                    tool_input={"message": msg})

    def stop(self, msg, **kw):
        return dict(self.base(**kw), hook_event_name="SubagentStop", last_assistant_message=msg)

    def test_a_valid_report_passes(self):
        self.assertIsNone(self.run_hook(self.handback(GOOD)))
        self.assertIsNone(self.run_hook(self.stop(GOOD)))

    def test_an_invalid_handback_is_denied_twice_then_passes(self):
        first = self.run_hook(self.handback("done, no json"))
        out = first["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("attempt 1 of 3", out["permissionDecisionReason"])
        self.assertIn("blocked_actions", out["permissionDecisionReason"])
        second = self.run_hook(self.handback("still no json"))
        self.assertIn("attempt 2 of 3", second["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.run_hook(self.handback("third try, still bad")))
        # having given up, it stays given up for this agent: a reset here is what let a
        # duplicated hook cycle 1, 2, 1, 2 forever
        self.assertIsNone(self.run_hook(self.handback("bad")))

    def test_a_duplicated_hook_cannot_loop(self):
        # Two registrations (user and project settings) both run on every stop. Each bumps
        # the counter, so without a sticky give-up every stop still carried one block.
        for _ in range(3):
            outs = [self.run_hook(self.stop("no json")) for _ in range(2)]
            if not any(outs):
                return
        self.fail("still blocking after three duplicated stops")

    def test_an_accepted_report_resets_the_counter(self):
        self.run_hook(self.handback("bad"))
        self.assertIsNone(self.run_hook(self.handback(GOOD)))
        out = self.run_hook(self.handback("bad again"))
        self.assertIn("attempt 1 of 3", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_a_bad_final_message_blocks_the_stop(self):
        out = self.run_hook(self.stop("no json here"))
        self.assertEqual(out["decision"], "block")
        self.assertIn("```json", out["reason"])

    def test_schema_errors_are_named(self):
        bad = dict(VALID, status="finished")
        out = self.run_hook(self.handback("```json\n" + json.dumps(bad) + "\n```"))
        self.assertIn("status", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_an_empty_stop_message_is_skipped(self):
        self.assertIsNone(self.run_hook(self.stop("")))

    def test_only_our_roles_are_checked(self):
        for atype in ("general-purpose", "Plan", "claude-code-guide", ""):
            self.assertIsNone(self.run_hook(self.handback("free text", atype=atype)), atype)
        for atype in ("Explore", "researcher", "reviewer", "writer"):
            self.assertIsNotNone(self.run_hook(self.handback("free text", atype=atype, aid=atype)),
                                 atype)

    def test_teammates_are_skipped(self):
        with open(os.path.join(self.proj_dir, "s1", "subagents", "agent-t1.meta.json"), "w") as f:
            json.dump({"agentType": "Explore", "teamName": "session-1"}, f)
        self.assertIsNone(self.run_hook(self.stop("per-section reply", aid="t1")))

    def test_the_main_thread_and_other_tools_are_ignored(self):
        payload = self.handback("bad")
        del payload["agent_id"]
        self.assertIsNone(self.run_hook(payload))
        self.assertIsNone(self.run_hook(dict(self.handback("bad"), tool_name="Bash")))

    def test_stale_counters_are_pruned(self):
        self.run_hook(self.handback("bad", aid="old"))
        d = os.path.join(self.tmp.name, "state", "dotclaude", "report-check")
        stale = os.path.join(d, os.listdir(d)[0])
        os.utime(stale, (time.time() - 2 * 86400,) * 2)  # wall clock
        self.run_hook(self.handback(GOOD, aid="other"))
        self.assertFalse(os.path.exists(stale))

    def test_fails_open(self):
        for raw in ("not json", "", "[]"):
            self.assertIsNone(self.run_hook(raw, raw=True))
        env = dict(self.env, DELEGATION_POLICY="/nonexistent/policy.toml")
        p = subprocess.run(["python3", SCRIPT], input=json.dumps(self.handback("bad")),
                           capture_output=True, text=True, env=env)
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_shim_exits_0_even_if_the_script_is_missing(self):
        with tempfile.TemporaryDirectory() as home:
            p = subprocess.run(["bash", SHIM], input=json.dumps(self.handback("bad")),
                               capture_output=True, text=True, env=dict(os.environ, HOME=home))
        self.assertEqual((p.returncode, p.stdout), (0, ""))


def moved_result(task, output):
    """A foreground Bash call Claude Code moved to the background at 180 s, as the agent
    transcript records it (agent a6301324f3813f8b5, 2.1.316)."""
    return {"type": "user", "toolUseResult": {"backgroundTaskId": task, "timedOutAfterMs": 180000,
                                              "subagentCapApplied": True},
            "message": {"role": "user", "content": [{
                "tool_use_id": f"toolu_{task}", "type": "tool_result",
                "content": f"Command was moved to the background (ID: {task}) after running for "
                           f"180s. Output is being written to: {output}. You will be notified "
                           "when it completes."}]}}


def launched_result(task, output):
    """A run_in_background launch: the transcript entry has no toolUseResult (probe a, 2.1.316)."""
    return {"type": "user", "message": {"role": "user", "content": [{
        "tool_use_id": f"toolu_{task}", "type": "tool_result",
        "content": f"Command running in background with ID: {task}. Output is being written to: "
                   f"{output}. If it exits while you are still working you will be notified, "
                   "but it is terminated when you give your final response."}]}}


def notice_text(task, status="completed"):
    return (f"<task-notification>\n<task-id>{task}</task-id>\n<tool-use-id>toolu_{task}"
            f"</tool-use-id>\n<status>{status}</status>\n<summary>Background command "
            f"completed</summary>\n</task-notification>")


def mid_turn_notice(task, status="completed"):
    """A notice that arrives during the agent's turn (probe a)."""
    return {"type": "attachment", "attachment": {
        "type": "queued_command", "prompt": notice_text(task, status),
        "origin": {"kind": "task-notification", "producer": "session-task"}}}


def between_turns_notice(task):
    """A notice that arrives after the agent's turn ended (the incident's entry 58)."""
    return {"type": "user", "origin": {"kind": "task-notification", "producer": "session-task"},
            "message": {"role": "user", "content": "[SYSTEM NOTIFICATION - NOT USER INPUT]\n\n"
                                                   + notice_text(task)}}


class WaitCheck(unittest.TestCase):
    """A handback while one of the agent's own background commands still runs is refused,
    sharing the schema check's two refusals; at the cap it passes with a note for the caller."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state")
        self.env = dict(os.environ, XDG_STATE_HOME=self.state)
        self.proj_dir = os.path.join(self.tmp.name, "projects", "-p")
        self.subagents = os.path.join(self.proj_dir, "s1", "subagents")
        os.makedirs(self.subagents)
        self.tasks = os.path.join(self.tmp.name, "tasks")
        os.makedirs(self.tasks)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, payload):
        p = subprocess.run(["python3", SCRIPT], input=json.dumps(payload), capture_output=True,
                           text=True, env=self.env)
        self.assertEqual(p.returncode, 0)
        return json.loads(p.stdout) if p.stdout.strip() else None

    def output(self, task, text=""):
        path = os.path.join(self.tasks, f"{task}.output")
        with open(path, "w") as f:
            f.write(text)
        return path

    def transcript(self, entries, aid="a1"):
        with open(os.path.join(self.subagents, f"agent-{aid}.jsonl"), "w") as f:
            for e in entries:
                f.write((e if isinstance(e, str) else json.dumps(e)) + "\n")

    def handback(self, msg=GOOD, atype="smoke-writer", aid="a1"):
        return {"agent_id": aid, "agent_type": atype, "session_id": "s1",
                "transcript_path": os.path.join(self.proj_dir, "s1.jsonl"),
                "hook_event_name": "PreToolUse", "tool_name": "SubagentHandback",
                "tool_input": {"message": msg}}

    def stop(self, msg="waiting", aid="a1", **kw):
        return {"agent_id": aid, "agent_type": "smoke-writer", "session_id": "s1",
                "transcript_path": os.path.join(self.proj_dir, "s1.jsonl"),
                "agent_transcript_path": os.path.join(self.subagents, f"agent-{aid}.jsonl"),
                "hook_event_name": "SubagentStop", "last_assistant_message": msg, **kw}

    def reason(self, out):
        self.assertIsNotNone(out)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        return hso["permissionDecisionReason"]

    def incident(self):
        """The early handback: the moved command's output is still empty."""
        path = self.output("b5cavw0cz")
        self.transcript([moved_result("b5cavw0cz", path)])
        return path

    def test_the_early_handback_is_refused(self):
        path = self.incident()
        reason = self.reason(self.run_hook(self.handback("Not done: out.txt was not written.")))
        self.assertIn("b5cavw0cz", reason)
        self.assertIn(path, reason)
        self.assertIn("attempt 1 of 3", reason)
        self.assertIn("shorter than 3 minutes", reason)

    def test_the_wait_it_suggests_is_not_blocked_by_claude_code(self):
        # 2.1.316 refuses a Bash call whose first part is a bare `sleep N` with N >= 25
        # ("Blocked: sleep 60 followed by ...", the live `early` case, 2026-11-01)
        self.incident()
        reason = self.reason(self.run_hook(self.handback()))
        command = re.search(r"`(timeout [^`]+)`", reason).group(1)
        first = re.split(r"[;&|]", command)[0].strip()
        self.assertNotRegex(first, r"^sleep\s+\d")
        self.assertIn("until ", command)
        self.assertIn("ps", reason)  # a sandboxed ps can't see the command

    def test_every_launch_text_counts(self):
        # every form 2.1.316's background note takes (RWr in the binary)
        texts = {
            "btimeout": "Command did not complete within its 120s timeout and was moved to the "
                        "background (ID: btimeout). Output is being written to: {out}.",
            "bmessage": "Command was moved to the background (ID: bmessage) so that a message that "
                        "arrived while it was running can reach you; it was not interrupted. "
                        "Output is being written to: {out}.",
            "buser": "Command was manually backgrounded by user with ID: buser. Output is being "
                     "written to: {out}.",
        }
        for i, (task, text) in enumerate(texts.items()):
            aid = f"l{i}"
            entry = launched_result(task, self.output(task))
            entry["message"]["content"][0]["content"] = text.format(out=self.output(task))
            self.transcript([entry], aid=aid)
            self.assertIn(task, self.reason(self.run_hook(self.handback(aid=aid))), task)

    def test_a_stop_while_it_runs_is_blocked(self):
        self.incident()
        out = self.run_hook(self.stop("waiting"))
        self.assertEqual(out["decision"], "block")
        self.assertIn("b5cavw0cz", out["reason"])

    def test_an_empty_stop_message_is_still_skipped(self):
        # auto mode's second stop, after the handback the PreToolUse check already saw
        self.incident()
        self.assertIsNone(self.run_hook(self.stop("")))

    def test_a_run_in_background_launch_counts_too(self):
        path = self.output("b16qirr06")
        self.transcript([launched_result("b16qirr06", path)])
        self.assertIn("b16qirr06", self.reason(self.run_hook(self.handback())))

    def test_a_finished_command_passes(self):
        for tail in ("waited\n\n[exited with code 0]", "beta\n\n[exited with code 3]",
                     "\n[killed]"):
            path = self.output("b1", tail)
            self.transcript([moved_result("b1", path)])
            self.assertIsNone(self.run_hook(self.handback()), tail)

    def test_a_completion_notice_passes(self):
        for notice in (mid_turn_notice("b1"), mid_turn_notice("b1", "failed"),
                       between_turns_notice("b1")):
            path = self.output("b1")
            self.transcript([moved_result("b1", path), notice])
            self.assertIsNone(self.run_hook(self.handback()), notice)

    def test_a_launch_in_the_same_batch_counts_before_its_result_lands(self):
        # the live `early` case, 2026-11-01: the agent sent the run_in_background Bash call and
        # the handback in one message, and the launch's tool_result wasn't in the transcript
        # yet when the handback's hook read it; the tool_use entry was
        def use(tid, **inp):
            return {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": tid, "name": "Bash", "input": inp}]}}
        cmd = "python3 -c \"import time; time.sleep(45)\""
        self.transcript([use("toolu_bg", command=cmd, run_in_background=True)])
        reason = self.reason(self.run_hook(self.handback()))
        self.assertIn("time.sleep(45)", reason)
        # a foreground call's missing result isn't a launch: the batch's calls run in order
        self.transcript([use("toolu_fg", command="ls")])
        self.assertIsNone(self.run_hook(self.handback()))
        # once its result lands, the launch line decides
        path = self.output("b9", "x\n[exited with code 0]")
        self.transcript([use("toolu_b9", command=cmd, run_in_background=True),
                         dict(launched_result("b9", path), message={"role": "user", "content": [
                             dict(launched_result("b9", path)["message"]["content"][0],
                                  tool_use_id="toolu_b9")]})])
        self.assertIsNone(self.run_hook(self.handback()))

    def test_only_the_unfinished_ones_are_named(self):
        done, running = self.output("bdone", "x\n[exited with code 0]"), self.output("brun")
        self.transcript([moved_result("bdone", done), launched_result("brun", running)])
        reason = self.reason(self.run_hook(self.handback()))
        self.assertIn("brun", reason)
        self.assertNotIn("bdone", reason)

    def test_quoted_launch_text_is_not_a_launch(self):
        # the agent's own text, or a command's output that prints the phrase, starts nothing
        path = self.output("bfake")
        quoted = dict(launched_result("bfake", path))
        quoted["message"]["content"][0]["content"] = (
            "log line: Command running in background with ID: bfake. Output is being written "
            f"to: {path}.")
        said = {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": f"Command running in background with ID: bfake. Output is "
                                     f"being written to: {path}."}]}}
        self.transcript([quoted, said])
        self.assertIsNone(self.run_hook(self.handback()))

    def test_another_agents_command_is_ignored(self):
        path = self.output("bother")
        self.transcript([moved_result("bother", path)], aid="a2")
        self.transcript([], aid="a1")
        self.assertIsNone(self.run_hook(self.handback(aid="a1")))

    def test_every_subagent_but_a_teammate_is_covered(self):
        for i, atype in enumerate(("general-purpose", "smoke-writer", "Explore", "writer")):
            aid = f"r{i}"
            self.transcript([moved_result("b1", self.output("b1"))], aid=aid)
            self.assertIn("b1", self.reason(self.run_hook(self.handback(atype=atype, aid=aid))),
                          atype)
        self.transcript([moved_result("b1", self.output("b1"))], aid="t1")
        with open(os.path.join(self.subagents, "agent-t1.meta.json"), "w") as f:
            json.dump({"agentType": "Explore", "teamName": "session-1"}, f)
        self.assertIsNone(self.run_hook(self.handback(aid="t1")))

    def test_the_cap_is_shared_and_the_last_pass_carries_a_note(self):
        path = self.incident()
        self.assertIn("attempt 1 of 3", self.reason(self.run_hook(self.handback(atype="Explore"))))
        # the wait is over the cap's first refusal; a schema miss takes the second
        with open(path, "w") as f:
            f.write("waited\n\n[exited with code 0]")
        reason = self.reason(self.run_hook(self.handback("no json", atype="Explore")))
        self.assertIn("attempt 2 of 3", reason)
        self.assertIn("report contract", reason)
        with open(path, "w") as f:
            f.write("")
        out = self.run_hook(self.handback("third try", atype="Explore"))
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "allow")
        message = hso["updatedInput"]["message"]
        self.assertTrue(message.startswith("third try"))
        self.assertIn("b5cavw0cz", message)
        self.assertIn(path, message)

    def test_a_report_that_waited_resets_the_counter(self):
        path = self.incident()
        self.reason(self.run_hook(self.handback()))
        with open(path, "w") as f:
            f.write("waited\n\n[exited with code 0]")
        self.assertIsNone(self.run_hook(self.handback()))
        self.transcript([moved_result("b2", self.output("b2"))])
        self.assertIn("attempt 1 of 3", self.reason(self.run_hook(self.handback())))

    def test_past_the_deadline_stop_it_passes_with_a_note(self):
        # the policy then denies every tool but the handback, so the agent can't wait
        self.incident()
        agents = os.path.join(self.state, "dotclaude", "agents")
        os.makedirs(agents)
        start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 6 * 3600))  # wall clock
        with open(os.path.join(agents, "a1.json"), "w") as f:
            json.dump({"activation_start": start}, f)
        out = self.run_hook(self.handback())
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "allow")
        self.assertIn("b5cavw0cz", hso["updatedInput"]["message"])
        # a stop can't carry a note, so it just passes
        self.assertIsNone(self.run_hook(self.stop("waiting")))

    def test_fails_open_on_what_it_cannot_read(self):
        # no transcript, a malformed one, a launch whose output file is gone
        self.assertIsNone(self.run_hook(self.handback()))
        self.transcript(["{not json", "[]", json.dumps({"type": "user", "message": None})])
        self.assertIsNone(self.run_hook(self.handback()))
        self.transcript([moved_result("bgone", os.path.join(self.tasks, "missing.output"))])
        self.assertIsNone(self.run_hook(self.handback()))


if __name__ == "__main__":
    unittest.main()
