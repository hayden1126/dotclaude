"""agent-spawn-guard: writers must pass isolation on the call, named spawns need the team
prefix, and everything fails closed."""
import json
import os
import subprocess
import tempfile
import unittest

from _paths import HOOKS, REPO, SCRIPTS

GUARD = os.path.join(SCRIPTS, "agent-spawn-guard")
SHIM = os.path.join(HOOKS, "agent-spawn-guard.sh")
with open(os.path.join(REPO, "skills", "delegation", "policy.toml")) as _f:
    SHIPPED_POLICY = _f.read()


def run(payload, raw=False, env=None):
    stdin = payload if raw else json.dumps(payload)
    p = subprocess.run(["python3", GUARD], input=stdin, capture_output=True, text=True,
                       env=dict(os.environ, **(env or {})))
    decision = json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"] if p.stdout else None
    return p.returncode, decision


def reason(payload, env=None):
    p = subprocess.run(["python3", GUARD], input=json.dumps(payload), capture_output=True,
                       text=True, env=dict(os.environ, **(env or {})))
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


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

    def test_a_team_prefix_does_not_excuse_a_writer(self):
        self.assertEqual(run(agent(subagent_type="writer", name="team-w")), (0, "deny"))

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


class NamedSpawn(unittest.TestCase):
    """A named spawn becomes an in-process teammate; it needs the policy's team prefix."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {"XDG_STATE_HOME": self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        try:
            with open(os.path.join(self.tmp.name, "dotclaude", "delegations.jsonl")) as f:
                return [json.loads(l) for l in f]
        except FileNotFoundError:
            return []

    def policy(self, text):
        path = os.path.join(self.tmp.name, "policy.toml")
        with open(path, "w") as f:
            f.write(text)
        return dict(self.env, DELEGATION_POLICY=path)

    def test_a_named_spawn_is_denied(self):
        for st in ("Explore", "researcher", "general-purpose", None):
            self.assertEqual(run(agent(subagent_type=st, name="helper"), env=self.env),
                             (0, "deny"), st)

    def test_the_team_prefix_opts_one_spawn_in(self):
        self.assertEqual(run(agent(subagent_type="researcher", name="team-probe"), env=self.env),
                         (0, None))

    def test_a_fork_or_an_isolated_spawn_may_be_named(self):
        for ti in ({"subagent_type": "fork", "name": "f1"},
                   {"subagent_type": "Explore", "name": "x", "isolation": "worktree"},
                   {"subagent_type": "writer", "name": "w", "isolation": "remote"}):
            self.assertEqual(run(agent(**ti), env=self.env), (0, None), ti)

    def test_an_empty_name_is_no_name(self):
        self.assertEqual(run(agent(subagent_type="Explore", name=""), env=self.env), (0, None))

    def test_the_reason_names_the_fix_and_the_prefix(self):
        r = reason(agent(subagent_type="Explore", name="helper"), env=self.env)
        self.assertIn("without `name`", r)
        self.assertIn("SendMessage", r)
        self.assertIn('"team-"', r)
        self.assertIn("Do not retry the blocked form", r)  # the use_alternative footer

    def test_the_prefix_comes_from_the_policy(self):
        env = self.policy(SHIPPED_POLICY.replace('team_prefix = "team-"', 'team_prefix = "crew-"'))
        self.assertEqual(run(agent(subagent_type="Explore", name="crew-a"), env=env), (0, None))
        self.assertEqual(run(agent(subagent_type="Explore", name="team-a"), env=env), (0, "deny"))

    def test_a_policy_without_a_spawn_table_defaults_the_prefix(self):
        env = self.policy('[intents]\nuse_alternative = "x"\n')
        self.assertEqual(run(agent(subagent_type="Explore", name="team-a"), env=env), (0, None))
        self.assertEqual(run(agent(subagent_type="Explore", name="a"), env=env), (0, "deny"))

    def test_an_unreadable_policy_denies_named_and_unnamed_alike(self):
        env = self.policy("not = [toml")
        self.assertEqual(run(agent(subagent_type="Explore", name="team-a"), env=env), (0, "deny"))
        self.assertEqual(run(agent(subagent_type="Explore"), env=env), (0, "deny"))
        self.assertIn("policy", reason(agent(subagent_type="Explore"), env=env))

    def test_a_denial_is_recorded_in_the_ledger(self):
        run(agent(subagent_type="Explore", name="helper"), env=self.env)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual({k: rows[0][k] for k in ("event", "rule", "tool", "name")},
                         {"event": "policy", "rule": "named-spawn", "tool": "Agent",
                          "name": "helper"})

    def test_an_allowed_spawn_writes_nothing(self):
        run(agent(subagent_type="Explore"), env=self.env)
        run(agent(subagent_type="Explore", name="team-a"), env=self.env)
        self.assertEqual(self.rows(), [])

    def test_a_ledger_failure_does_not_change_the_decision(self):
        env = dict(self.env, DELEGATION_LEDGER="/proc/nope/delegations.jsonl")
        self.assertEqual(run(agent(subagent_type="Explore", name="helper"), env=env), (0, "deny"))
        self.assertEqual(run(agent(subagent_type="Explore", name="team-a"), env=env), (0, None))


if __name__ == "__main__":
    unittest.main()
