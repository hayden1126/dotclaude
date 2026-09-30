"""report-check: our roles' reports are sent back at most twice, and it always fails open."""
import json
import os
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
        # the counter was cleared on giving up, so a later bad report starts over
        again = self.run_hook(self.handback("bad"))
        self.assertIn("attempt 1 of 3", again["hookSpecificOutput"]["permissionDecisionReason"])

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
        os.utime(stale, (time.time() - 2 * 86400,) * 2)
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


if __name__ == "__main__":
    unittest.main()
