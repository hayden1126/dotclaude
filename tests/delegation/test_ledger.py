"""delegation-ledger and the shared report validator."""
import json
import os
import subprocess
import tempfile
import unittest

from _paths import HOOKS, SCRIPTS, SKILL, load_script

LEDGER = os.path.join(SCRIPTS, "delegation-ledger")
dc = load_script("delegation_common.py")

VALID = {"status": "done", "summary": "ok", "artifacts": [], "blocked_actions": []}


def fenced(obj):
    return "Findings in prose.\n\n```json\n" + json.dumps(obj) + "\n```\n"


class Validator(unittest.TestCase):
    def test_valid_report(self):
        self.assertEqual(dc.validate_report(VALID), [])

    def test_missing_extra_enum_and_array_errors(self):
        self.assertIn("missing field: artifacts",
                      dc.validate_report({k: v for k, v in VALID.items() if k != "artifacts"}))
        self.assertIn("unexpected field: extra", dc.validate_report(dict(VALID, extra=1)))
        self.assertTrue(dc.validate_report(dict(VALID, status="finished")))
        self.assertTrue(dc.validate_report(dict(VALID, artifacts=[1])))
        self.assertTrue(dc.validate_report("not an object"))

    def test_extract_accepts_uppercase_and_indented_fences(self):
        body = json.dumps(VALID)
        self.assertEqual(dc.extract_report(f"x\n```JSON\n{body}\n```")[0], VALID)
        self.assertEqual(dc.extract_report(f"x\n  ```json\n  {body}\n  ```\n")[0], VALID)

    def test_fold_lets_a_clean_resume_clear_an_old_error(self):
        rows = [{"runner": "codex", "id": "r", "event": "stop", "report_error": "bad"},
                {"runner": "codex", "id": "r", "event": "stop", "report_error": None}]
        self.assertIsNone(dc.fold(rows)[("codex", "r")]["report_error"])

    def test_extract_takes_the_last_fenced_block(self):
        text = fenced({"status": "failed"}) + "later\n" + fenced(VALID)
        self.assertEqual(dc.extract_report(text)[0], VALID)
        self.assertEqual(dc.extract_report(json.dumps(VALID))[0], VALID)
        self.assertIsNone(dc.extract_report("no json here")[0])
        self.assertIsNone(dc.extract_report("")[0])

    def test_validator_covers_every_schema_keyword(self):
        # validate_report implements exactly these keywords; a schema edit that adds one
        # must extend the validator too, or reports would pass unchecked.
        handled = {"type", "additionalProperties", "required", "properties", "enum", "items",
                   "description"}
        seen = set()

        def walk(node):
            seen.update(node)
            for spec in node.get("properties", {}).values():
                walk(spec)
            if isinstance(node.get("items"), dict):
                walk(node["items"])
        with open(os.path.join(SKILL, "report.schema.json")) as f:
            walk(json.load(f))
        self.assertLessEqual(seen, handled)

    def test_schema_is_codex_strict(self):
        schema = dc.load_schema()
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(set(schema["required"]), set(schema["properties"]))


class LedgerHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, HOME=self.tmp.name,
                        XDG_STATE_HOME=os.path.join(self.tmp.name, "state"))
        self.ledger = os.path.join(self.tmp.name, "state", "dotclaude", "delegations.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, payload, raw=False):
        return subprocess.run(["python3", LEDGER, "hook"],
                              input=payload if raw else json.dumps(payload),
                              capture_output=True, text=True, env=self.env)

    def rows(self):
        try:
            with open(self.ledger) as f:
                return [json.loads(l) for l in f]
        except FileNotFoundError:
            return []

    def start(self, aid="agent-a1", sid="s1"):
        return {"hook_event_name": "SubagentStart", "agent_id": aid, "agent_type": "Explore",
                "session_id": sid, "cwd": "/w",
                "transcript_path": os.path.join(self.tmp.name, f"{sid}.jsonl")}

    def stop(self, aid="a1", msg=None):
        return {"hook_event_name": "SubagentStop", "agent_id": aid, "agent_type": "Explore",
                "session_id": "s1", "last_assistant_message": msg if msg is not None
                else fenced(VALID), "agent_transcript_path": "/t/agent-a1.jsonl"}

    def test_start_and_stop_rows_are_pointers(self):
        p = self.hook(self.start())
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.hook(self.stop())
        start, stop = self.rows()
        self.assertEqual((start["event"], start["id"]), ("start", "a1"))
        self.assertEqual((stop["event"], stop["report_ok"], stop["report_status"]),
                         ("stop", True, "done"))
        self.assertNotIn("last_assistant_message", json.dumps(stop))

    def test_auto_mode_report_comes_from_the_handback(self):
        transcript = os.path.join(self.tmp.name, "agent-a1.jsonl")
        with open(transcript, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "SubagentHandback",
                 "input": {"message": fenced(VALID)}}]}}) + "\n")
        p = self.hook(dict(self.stop(msg=""), agent_transcript_path=transcript))
        self.assertEqual(p.returncode, 0)
        row = self.rows()[0]
        self.assertEqual((row["report_ok"], row["report_source"]), (True, "handback"))

    def test_no_report_anywhere_is_recorded_as_missing(self):
        self.hook(dict(self.stop(msg=""), agent_transcript_path="/nonexistent.jsonl"))
        row = self.rows()[0]
        self.assertEqual((row["report_ok"], row["report_source"]), (False, None))

    def test_internal_helper_agents_are_skipped(self):
        for ev in (dict(self.start(), agent_type=""), dict(self.stop(), agent_type="")):
            p = self.hook(ev)
            self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertEqual(self.rows(), [])

    def test_invalid_report_is_recorded_not_blocked(self):
        p = self.hook(self.stop(msg="I finished, no JSON."))
        self.assertEqual(p.returncode, 0)
        self.assertFalse(self.rows()[0]["report_ok"])

    def test_malformed_input_exits_0_and_logs(self):
        for bad in ("not json", json.dumps({"hook_event_name": "SubagentStart"}),
                    json.dumps({"hook_event_name": "Other", "agent_id": "x"})):
            p = self.hook(bad, raw=True)
            self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertEqual(self.rows(), [])
        err = os.path.join(self.tmp.name, "state", "dotclaude", "delegation-ledger.err")
        self.assertTrue(os.path.getsize(err) > 0)

    def test_a_teammate_is_recorded_by_its_role_and_name(self):
        # A teammate's hook agent_type is its name; the role is meta.json's customAgentType
        # (observed on 2.1.286).
        sub = os.path.join(self.tmp.name, "s1", "subagents")
        os.makedirs(sub)
        with open(os.path.join(sub, "agent-a1.meta.json"), "w") as f:
            json.dump({"agentType": "team-x", "name": "team-x", "customAgentType": "researcher",
                       "taskKind": "in_process_teammate", "teamName": "session-s1"}, f)
        self.hook(dict(self.start(), agent_type="team-x"))
        self.hook(dict(self.stop(), agent_type="team-x",
                       transcript_path=os.path.join(self.tmp.name, "s1.jsonl")))
        self.assertEqual([(r["agent_type"], r.get("name")) for r in self.rows()],
                         [("researcher", "team-x")] * 2)

    def test_agent_role_falls_back_to_the_hook_type(self):
        self.assertEqual(dc.agent_role({"agent_type": "Explore"}, {}), "Explore")
        self.assertEqual(dc.agent_role({"agent_type": "team-x"}, {"customAgentType": "writer"}),
                         "writer")
        self.assertEqual(dc.agent_role({}, {}), "")
        self.assertEqual(dc.agent_meta({"transcript_path": "/nonexistent/s.jsonl",
                                        "agent_id": "a1"}), {})

    def test_teammate_restarts_fold_to_one_entry(self):
        for _ in range(3):
            self.hook(self.start())
        folded = dc.fold(self.rows_via_module())
        self.assertEqual(len(folded), 1)
        self.hook(self.stop())
        self.assertEqual(dc.fold(self.rows_via_module())[("claude", "a1")]["event"], "stop")

    def rows_via_module(self):
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.env["XDG_STATE_HOME"]
        try:
            return dc.read_rows()
        finally:
            if old is None:
                os.environ.pop("XDG_STATE_HOME")
            else:
                os.environ["XDG_STATE_HOME"] = old

    def test_open_lists_only_unfinished_with_evidence(self):
        self.hook(self.start("agent-a1"))
        self.hook(self.stop("a1"))
        self.hook(self.start("agent-b2"))
        p = subprocess.run(["python3", LEDGER, "open"], capture_output=True, text=True,
                           env=self.env)
        self.assertEqual(p.returncode, 0)
        self.assertIn("b2", p.stdout)
        self.assertNotIn("a1", p.stdout)
        self.assertIn("orphaned", p.stdout)        # no live session registry under this HOME
        self.assertIn("session gone", p.stdout)    # the evidence is printed, not just a verdict

    def test_open_flags_a_finished_turn_without_a_stop_row(self):
        sessions = os.path.join(self.tmp.name, ".claude", "sessions")
        os.makedirs(sessions)
        with open(os.path.join(sessions, "1.json"), "w") as f:
            json.dump({"pid": os.getpid(), "sessionId": "s1"}, f)  # a live session
        sub = os.path.join(self.tmp.name, "s1", "subagents")
        os.makedirs(sub)
        with open(os.path.join(sub, "agent-c3.jsonl"), "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {
                "stop_reason": "end_turn", "content": [{"type": "text", "text": "done"}]}}) + "\n")
        self.hook(self.start("agent-c3"))
        p = subprocess.run(["python3", LEDGER, "open"], capture_output=True, text=True,
                           env=self.env)
        self.assertIn("ended its turn but no stop row", p.stdout)
        self.assertIn("session alive", p.stdout)

    def test_codex_states(self):
        dead = 2 ** 22 + 12345  # beyond pid_max on this box, so never alive
        with tempfile.TemporaryDirectory() as out:
            base = {"runner": "codex", "run_id": "r1", "out": out}
            self.assertTrue(dc.codex_state(dict(base, event="pending",
                                                wrapper_pid=os.getpid()))[0].startswith("starting"))
            self.assertIn("never started", dc.codex_state(dict(base, event="pending",
                                                               wrapper_pid=dead))[0])
            self.assertIn("died", dc.codex_state(dict(base, event="start", pid=dead))[0])
            self.assertIn("wrapper is gone", dc.codex_state(dict(
                base, event="interrupted", pid=os.getpid(), wrapper_pid=dead))[0])
            open(os.path.join(out, "report.json"), "w").close()
            self.assertIn("finalize", dc.codex_state(dict(base, event="start", pid=dead))[0])

    def test_open_with_nothing_unfinished(self):
        p = subprocess.run(["python3", LEDGER, "open"], capture_output=True, text=True,
                           env=self.env)
        self.assertIn("no unfinished delegations", p.stdout)

    def test_shim_is_silent_and_exits_0_even_if_the_script_is_missing(self):
        p = subprocess.run(["bash", os.path.join(HOOKS, "delegation-ledger.sh")],
                           input=json.dumps(self.start()), capture_output=True, text=True,
                           env=self.env)
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_the_accepted_handback_wins_over_one_report_check_sent_back(self):
        transcript = os.path.join(self.tmp.name, "agent-a1.jsonl")
        use = lambda i, msg: {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": i, "name": "SubagentHandback", "input": {"message": msg}}]}}
        result = lambda i, err: {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": i, "is_error": err, "content": "x"}]}}
        with open(transcript, "w") as f:
            for e in (use("h1", "no json"), result("h1", True), use("h2", fenced(VALID)),
                      result("h2", False)):
                f.write(json.dumps(e) + "\n")
        self.hook(dict(self.stop(msg=""), agent_transcript_path=transcript))
        self.assertTrue(self.rows()[0]["report_ok"])

    def test_policy_rows_are_not_lifecycle_events(self):
        self.hook(self.start())
        rows = self.rows_via_module() + [{"runner": "claude", "id": "a1", "event": "policy",
                                          "rule": "git-push"}]
        self.assertEqual(dc.fold(rows)[("claude", "a1")]["event"], "start")

    def test_a_worktree_agent_records_the_main_checkout_status(self):
        repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(repo, ".claude", "worktrees", "agent-w1"))
        subprocess.run(["git", "init", "-q", repo], check=True)
        wt = os.path.join(repo, ".claude", "worktrees", "agent-w1")
        self.hook(dict(self.start("agent-w1"), cwd=wt, agent_type="writer"))
        with open(os.path.join(repo, "escaped.txt"), "w") as f:
            f.write("x")
        self.hook(dict(self.stop("w1"), cwd=wt, agent_type="writer"))
        start, stop = self.rows()
        self.assertNotEqual(start["main_before"], stop["main_after"])
        p = subprocess.run(["python3", LEDGER, "audit"], capture_output=True, text=True,
                           env=self.env)
        self.assertIn("main checkout changed while writer w1", p.stdout)
        self.assertEqual(p.returncode, 1)

    def test_audit_warns_when_the_policy_hook_never_saw_an_agent(self):
        transcript = os.path.join(self.tmp.name, "agent-a1.jsonl")
        with open(transcript, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {}}]}}) + "\n")
        self.hook(self.start())
        self.hook(dict(self.stop(), agent_transcript_path=transcript))
        p = subprocess.run(["python3", LEDGER, "audit"], capture_output=True, text=True,
                           env=self.env)
        self.assertIn("WARN policy hook", p.stdout)
        hb = os.path.join(self.tmp.name, "state", "dotclaude", "subagent-policy.heartbeat")
        open(hb, "w").close()
        p = subprocess.run(["python3", LEDGER, "audit"], capture_output=True, text=True,
                           env=self.env)
        self.assertIn("ok   policy hook", p.stdout)

    def test_sandbox_denials_are_counted_from_transcripts(self):
        proj = os.path.join(self.tmp.name, ".claude", "projects", "-p")
        os.makedirs(proj)
        with open(os.path.join(proj, "s.jsonl"), "w") as f:
            f.write(json.dumps({"type": "user", "message": {"content": [{
                "type": "tool_result", "content": "000\n<sandbox_violations>\ndeny "
                "network-outbound example.com:443 (user denied)\n</sandbox_violations>"}]}}) + "\n")
        p = subprocess.run(["python3", LEDGER, "sandbox-denials"], capture_output=True,
                           text=True, env=self.env)
        self.assertIn("example.com:443", p.stdout)


if __name__ == "__main__":
    unittest.main()
