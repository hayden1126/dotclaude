"""agent-spawn-guard: writers must pass isolation on the call; everything fails closed."""
import json
import os
import subprocess
import tempfile
import unittest

from _paths import HOOKS, SCRIPTS

GUARD = os.path.join(SCRIPTS, "agent-spawn-guard")
SHIM = os.path.join(HOOKS, "agent-spawn-guard.sh")


def run(payload, raw=False):
    stdin = payload if raw else json.dumps(payload)
    p = subprocess.run(["python3", GUARD], input=stdin, capture_output=True, text=True)
    decision = json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"] if p.stdout else None
    return p.returncode, decision


def agent(**ti):
    return {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": ti}


class SpawnGuard(unittest.TestCase):
    def test_writer_without_isolation_is_denied(self):
        self.assertEqual(run(agent(subagent_type="writer", prompt="x")), (0, "deny"))

    def test_writer_with_worktree_or_remote_passes(self):
        for iso in ("worktree", "remote"):
            self.assertEqual(run(agent(subagent_type="writer", isolation=iso)), (0, None))

    def test_named_writer_without_isolation_is_denied(self):
        self.assertEqual(run(agent(subagent_type="writer", name="w1")), (0, "deny"))

    def test_other_roles_pass(self):
        for st in ("Explore", "reviewer", "researcher", "general-purpose", None):
            self.assertEqual(run(agent(subagent_type=st)), (0, None), st)

    def test_legacy_task_tool_name_is_covered(self):
        p = agent(subagent_type="writer")
        p["tool_name"] = "Task"
        self.assertEqual(run(p), (0, "deny"))

    def test_other_tools_pass(self):
        self.assertEqual(run({"tool_name": "Bash", "tool_input": {"command": "ls"}}), (0, None))

    def test_malformed_input_is_denied(self):
        self.assertEqual(run("not json", raw=True), (0, "deny"))
        self.assertEqual(run({"tool_name": "Agent", "tool_input": "x"}), (0, "deny"))
        self.assertEqual(run("", raw=True), (0, "deny"))

    def test_deny_reason_tells_claude_how_to_fix_it(self):
        p = subprocess.run(["python3", GUARD], input=json.dumps(agent(subagent_type="writer")),
                           capture_output=True, text=True)
        reason = json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn('isolation: "worktree"', reason)

    def test_shim_exits_2_when_the_guard_is_missing(self):
        with tempfile.TemporaryDirectory() as home:
            p = subprocess.run(["bash", SHIM], input=json.dumps(agent(subagent_type="Explore")),
                               capture_output=True, text=True, env=dict(os.environ, HOME=home))
        self.assertEqual(p.returncode, 2)
        self.assertIn("blocked until it is fixed", p.stderr)


if __name__ == "__main__":
    unittest.main()
