"""delegation-ledger and the shared report validator."""
import datetime
import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from _paths import HOOKS, REPO, SCRIPTS, SKILL, load_script

LEDGER = os.path.join(SCRIPTS, "delegation-ledger")
dc = load_script("delegation_common.py")
ledger_mod = load_script("delegation-ledger")

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


class LedgerEnv(unittest.TestCase):
    """A temp HOME and state dir, with the hook run as a subprocess against them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, HOME=self.tmp.name,
                        XDG_STATE_HOME=os.path.join(self.tmp.name, "state"))
        # Inside the sandbox the lead's CLAUDE_PID is inherited but invisible, which would put
        # every `open` here in the no-pid-visible mode. The Sandbox tests set it on purpose.
        self.env.pop("CLAUDE_PID", None)
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

    def agents(self):
        return os.path.join(self.tmp.name, "state", "dotclaude", "agents")

    def index(self, aid="a1"):
        with open(os.path.join(self.agents(), f"{aid}.json")) as f:
            return json.load(f)

    def start(self, aid="agent-a1", sid="s1"):
        return {"hook_event_name": "SubagentStart", "agent_id": aid, "agent_type": "Explore",
                "session_id": sid, "cwd": "/w",
                "transcript_path": os.path.join(self.tmp.name, f"{sid}.jsonl")}

    def stop(self, aid="a1", msg=None):
        return {"hook_event_name": "SubagentStop", "agent_id": aid, "agent_type": "Explore",
                "session_id": "s1", "last_assistant_message": msg if msg is not None
                else fenced(VALID), "agent_transcript_path": "/t/agent-a1.jsonl"}


class LedgerHook(LedgerEnv):
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

    def test_a_teammate_reply_is_not_a_failed_report(self):
        # A teammate's stops fire per message, and report-check skips teammates, so audit must
        # not count a checked-role teammate's plain reply as a report failing the contract.
        sub = os.path.join(self.tmp.name, "s1", "subagents")
        os.makedirs(sub)
        with open(os.path.join(sub, "agent-a1.meta.json"), "w") as f:
            json.dump({"agentType": "team-x", "name": "team-x", "customAgentType": "researcher",
                       "taskKind": "in_process_teammate", "teamName": "session-s1"}, f)
        tp = os.path.join(self.tmp.name, "s1.jsonl")
        self.hook(dict(self.start(), agent_type="team-x"))
        self.hook(dict(self.stop(msg="section 2 is unclear"), agent_type="team-x",
                       transcript_path=tp))
        self.assertTrue(self.rows()[-1]["teammate"])
        p = subprocess.run(["python3", LEDGER, "audit"], capture_output=True, text=True,
                           env=self.env)
        self.assertIn("ok   reports failing the contract: 0", p.stdout)

    def test_a_second_stop_for_one_agent_folds_to_one_entry(self):
        # Auto mode can stop an agent twice (a plain reply, then its SubagentHandback).
        self.hook(self.start())
        self.hook(self.stop(msg="plain reply"))
        self.hook(self.stop())
        folded = dc.fold(self.rows_via_module())
        self.assertEqual(len(folded), 1)
        self.assertTrue(folded[("claude", "a1")]["report_ok"])

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


def iso_ago(minutes):
    """A transcript timestamp `minutes` ago, with milliseconds as Claude Code writes them."""
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def use(i, name, ago):
    return {"type": "assistant", "timestamp": iso_ago(ago), "message": {
        "stop_reason": "tool_use", "content": [{"type": "tool_use", "id": i, "name": name,
                                                "input": {}}]}}


def result(i, ago, err=False):
    return {"type": "user", "timestamp": iso_ago(ago), "message": {"content": [
        {"type": "tool_result", "tool_use_id": i, "is_error": err, "content": "x"}]}}


def thinking(ago):
    return {"type": "assistant", "timestamp": iso_ago(ago), "message": {
        "stop_reason": None, "content": [{"type": "thinking", "thinking": "hm"}]}}


def ended(ago):
    return {"type": "assistant", "timestamp": iso_ago(ago), "message": {
        "stop_reason": "end_turn", "content": [{"type": "text", "text": "done"}]}}


class AgentIndex(LedgerEnv):
    """agents/<id>.json, the per-agent liveness index the hook keeps."""

    def test_a_start_creates_the_entry(self):
        self.hook(self.start())
        idx = self.index()
        self.assertEqual((idx["id"], idx["agent_type"], idx["session_id"], idx["cwd"]),
                         ("a1", "Explore", "s1", "/w"))
        self.assertEqual((idx["state"], idx["activations"], idx["teammate"]),
                         ("running", 1, False))
        self.assertEqual(idx["first_start"], idx["activation_start"])
        self.assertTrue(idx["agent_transcript"].endswith("/s1/subagents/agent-a1.jsonl"))
        self.assertEqual(sorted(os.listdir(self.agents())), [".lock", "a1.json"])  # no temp left
        self.hook(self.stop())
        err = os.path.join(self.tmp.name, "state", "dotclaude", "delegation-ledger.err")
        self.assertFalse(os.path.exists(err))  # the hook fails open, so check it didn't fail

    def test_a_second_start_is_a_new_activation_of_the_same_agent(self):
        self.hook(self.start())
        old = "2026-01-01T00:00:00Z"
        idx = dict(self.index(), first_start=old, activation_start=old)
        with open(os.path.join(self.agents(), "a1.json"), "w") as f:
            json.dump(idx, f)
        self.hook(self.start())
        idx = self.index()
        self.assertEqual(idx["first_start"], old)
        self.assertNotEqual(idx["activation_start"], old)
        self.assertEqual(idx["activations"], 2)

    def test_a_stop_marks_it_stopped_without_background_tasks(self):
        # background_tasks is session-wide (probe, 2.1.286), so the index doesn't keep it.
        self.hook(self.start())
        self.hook(dict(self.stop(), background_tasks=[{"id": "b1", "type": "shell"}]))
        idx = self.index()
        self.assertEqual(idx["state"], "stopped")
        self.assertTrue(idx["stopped_at"])
        self.assertNotIn("background_tasks", idx)
        self.hook(self.start())
        self.assertNotIn("stopped_at", self.index())

    def test_a_helper_agent_writes_no_entry(self):
        self.hook(dict(self.start(), agent_type=""))
        self.assertFalse(os.path.exists(os.path.join(self.agents(), "a1.json")))

    def test_a_stale_entry_is_pruned_and_a_fresh_one_kept(self):
        os.makedirs(self.agents())
        week = time.time() - 8 * 86400
        for name, mtime in (("old.json", week), (".old.x.tmp", week),
                            ("fresh.json", time.time() - 86400)):
            path = os.path.join(self.agents(), name)
            open(path, "w").close()
            os.utime(path, (mtime, mtime))
        self.hook(self.start())
        self.assertEqual(sorted(os.listdir(self.agents())), [".lock", "a1.json", "fresh.json"])

    def test_a_malformed_entry_reads_as_empty(self):
        os.makedirs(self.agents())
        with open(os.path.join(self.agents(), "a1.json"), "w") as f:
            f.write("{not json")
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.env["XDG_STATE_HOME"]}):
            self.assertEqual(dc.read_agent_state("a1"), {})
            self.assertEqual(dc.read_agent_state("../x"), {})
            with self.assertRaises(ValueError):  # an id is never a path
                dc.update_agent_state("../x", lambda s: None)
        self.hook(self.start())
        self.assertEqual(self.index()["activations"], 1)


class Nudge(LedgerEnv):
    """The deadline nudge on PostToolUse, against an index whose activation began in the past
    (the clock isn't faked). Explore's budget is 10 min, its stop 20."""

    def post(self, aid="agent-a1", atype="Explore", tool="Read"):
        return {"hook_event_name": "PostToolUse", "agent_id": aid, "agent_type": atype,
                "session_id": "s1", "tool_name": tool, "tool_use_id": "t1",
                "transcript_path": os.path.join(self.tmp.name, "s1.jsonl")}

    def started(self, minutes, aid="a1"):
        """Rewrite the index so this activation began `minutes` ago."""
        t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
        idx = dict(self.index(aid), activation_start=t.strftime("%Y-%m-%dT%H:%M:%SZ"))
        with open(os.path.join(self.agents(), f"{aid}.json"), "w") as f:
            json.dump(idx, f)

    def nudges(self):
        return [r for r in self.rows() if r["event"] == "nudge"]

    def context(self, p):
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PostToolUse")
        return out["additionalContext"]

    def err(self):
        return os.path.join(self.tmp.name, "state", "dotclaude", "delegation-ledger.err")

    def test_one_nudge_per_activation_and_a_fresh_one_after_a_restart(self):
        self.hook(self.start())
        self.started(11)
        text = self.context(self.hook(self.post()))
        self.assertEqual(text, "[deadline] You have run 11 min of this activation's 10 min "
                               "budget (Explore). Report now: finish and hand back, or hand back "
                               "`partial` naming what is left. After 20 min every tool except "
                               "SubagentHandback and SendMessage is denied.")
        self.assertTrue(self.index()["nudged"])
        p = self.hook(self.post(tool="Grep"))
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        (row,) = self.nudges()
        self.assertEqual((row["id"], row["agent_type"], row["minutes"], row["session_id"]),
                         ("a1", "Explore", 11.0, "s1"))
        self.hook(self.stop())
        self.hook(self.start())  # a resume: a new activation, so a new budget and nudge
        self.assertNotIn("nudged", self.index())
        self.started(11)
        self.assertIn("[deadline]", self.context(self.hook(self.post())))
        self.assertEqual(len(self.nudges()), 2)
        self.assertFalse(os.path.exists(self.err()))

    def test_parallel_calls_nudge_once(self):
        self.hook(self.start())
        self.started(11)
        procs = [subprocess.Popen(["python3", LEDGER, "hook"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, env=self.env)
                 for _ in range(6)]
        outs = [p.communicate(json.dumps(self.post()))[0] for p in procs]
        self.assertEqual(len([o for o in outs if o]), 1, outs)
        self.assertEqual(len(self.nudges()), 1)

    def test_a_teammate_is_nudged_on_its_role_budget(self):
        sub = os.path.join(self.tmp.name, "s1", "subagents")
        os.makedirs(sub)
        with open(os.path.join(sub, "agent-a1.meta.json"), "w") as f:
            json.dump({"agentType": "team-x", "name": "team-x", "customAgentType": "Explore",
                       "taskKind": "in_process_teammate", "teamName": "session-s1"}, f)
        self.hook(dict(self.start(), agent_type="team-x"))
        self.started(11)  # past Explore's 10 min, under the default 30
        self.assertIn("(Explore)", self.context(self.hook(self.post(atype="team-x"))))

    def test_no_nudge_under_budget_for_the_main_thread_a_helper_or_no_index(self):
        self.hook(self.start())
        self.started(9)
        main = self.post()
        del main["agent_id"]
        for ev in (self.post(), main, self.post(atype=""), self.post(aid="agent-noindex")):
            p = self.hook(ev)
            self.assertEqual((p.returncode, p.stdout), (0, ""), ev)
        self.assertEqual(self.nudges(), [])
        self.assertNotIn("nudged", self.index())
        self.assertFalse(os.path.exists(self.err()))

    def test_a_broken_deadline_table_is_silent(self):
        self.hook(self.start())
        self.started(31)
        bad = os.path.join(self.tmp.name, "policy.toml")
        for text in ("[deadline\n", "[deadline]\nallow = []\n",
                     '[deadline]\nallow = []\ndefault = { nudge_min = "soon" }\n'):
            with open(bad, "w") as f:
                f.write(text)
            for path in (bad, "/nonexistent/policy.toml"):
                p = subprocess.run(["python3", LEDGER, "hook"], input=json.dumps(self.post()),
                                   capture_output=True, text=True,
                                   env=dict(self.env, DELEGATION_POLICY=path))
                self.assertEqual((p.returncode, p.stdout), (0, ""), text)
        self.assertNotIn("nudged", self.index())
        self.assertFalse(os.path.exists(self.err()))

    def test_the_settings_command_passes_the_nudge_through(self):
        # Wired as settings.json wires it: the agent_id prefilter, then the shim, which must
        # pass the script's stdout on.
        with open(os.path.join(REPO, "settings.json")) as f:
            (entry,) = json.load(f)["hooks"]["PostToolUse"]
        hooks = os.path.join(self.tmp.name, ".claude", "hooks")
        os.makedirs(hooks)
        os.symlink(os.path.join(HOOKS, "delegation-ledger.sh"),
                   os.path.join(hooks, "delegation-ledger.sh"))
        os.makedirs(os.path.join(self.tmp.name, ".claude", "skills"))
        os.symlink(SKILL, os.path.join(self.tmp.name, ".claude", "skills", "delegation"))
        self.hook(self.start())
        self.started(11)
        p = subprocess.run(["sh", "-c", entry["hooks"][0]["command"]],
                           input=json.dumps(self.post()), capture_output=True, text=True,
                           env=self.env)
        self.assertIn("[deadline]", self.context(p))

    def test_nudge_rows_are_not_lifecycle_events(self):
        # A late nudge row must not reopen a stopped agent in open or watch, or hide its
        # failed report from audit.
        self.hook(self.start())
        self.hook(self.stop(msg="no report"))
        nudge = {"ts": dc.now_iso(), "runner": "claude", "event": "nudge", "id": "a1",
                 "agent_type": "Explore", "minutes": 11.0}
        with open(self.ledger, "a") as f:
            f.write(json.dumps(nudge) + "\n")
        self.assertEqual(dc.fold(self.rows())[("claude", "a1")]["event"], "stop")
        p = subprocess.run(["python3", LEDGER, "open"], capture_output=True, text=True,
                           env=self.env)
        self.assertIn("no unfinished delegations", p.stdout)
        p = subprocess.run(["python3", LEDGER, "audit"], capture_output=True, text=True,
                           env=self.env)
        self.assertIn("WARN reports failing the contract: 1", p.stdout)
        self.assertIn("policy denials in the last 168h: 0", p.stdout)


DEAD = 2 ** 22 + 12345  # beyond pid_max on this box, so never alive


class LiveSession(LedgerEnv):
    """A live session s1 (this process's pid) and helpers to write its agent transcripts, run
    the CLI, and write ledger rows directly. No tests of its own, so subclasses don't rerun
    any."""

    def setUp(self):
        super().setUp()
        sessions = os.path.join(self.tmp.name, ".claude", "sessions")
        os.makedirs(sessions)
        with open(os.path.join(sessions, "1.json"), "w") as f:
            json.dump({"pid": os.getpid(), "sessionId": "s1"}, f)
        self.sub = os.path.join(self.tmp.name, "s1", "subagents")
        os.makedirs(self.sub)

    def transcript(self, *entries, aid="a1"):
        with open(os.path.join(self.sub, f"agent-{aid}.jsonl"), "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def cli(self, *argv, toml=None, **env):
        env = dict(self.env, **env)
        if toml is not None:
            path = os.path.join(self.tmp.name, "liveness.toml")
            with open(path, "w") as f:
                f.write(toml)
            env["DELEGATION_LIVENESS"] = path
        p = subprocess.run(["python3", LEDGER, *argv], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def open_(self, toml=None):
        return self.cli("open", toml=toml)

    def append(self, *rows):
        os.makedirs(os.path.dirname(self.ledger), exist_ok=True)
        with open(self.ledger, "a") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)

    def codex_row(self, rid, pid, **kw):
        """A codex ledger row as codex-delegate writes it, with a fresh events.jsonl."""
        out = os.path.join(self.tmp.name, rid)
        os.makedirs(out)
        open(os.path.join(out, "events.jsonl"), "w").close()
        return dict({"runner": "codex", "id": rid, "run_id": rid, "event": "start",
                     "ts": dc.now_iso(), "model": "gpt-5.6-terra", "dir": "/src/proj",
                     "out": out, "pid": pid, "wrapper_pid": pid}, **kw)


class Liveness(LiveSession):
    """`open` on a live session: the transcript scan, the index and the thresholds."""

    def test_an_open_tool_use_is_a_call_in_flight(self):
        self.transcript(use("t1", "Bash", 5))
        self.hook(self.start())
        out = self.open_()
        self.assertIn("in Bash 5 min", out)
        self.assertIn("(activation 1), last entry tool_use 5 min ago, 1 call open", out)
        self.assertNotIn("⚠", out)       # under the shipped tool_min
        self.assertNotIn("warning", out)  # the shipped liveness.toml parses

    def test_parallel_calls_report_the_one_still_open(self):
        self.transcript(use("t1", "Read", 6), use("t2", "Bash", 6))
        self.hook(self.start())
        out = self.open_()
        self.assertIn("in Read 6 min, +1 more", out)
        self.assertIn("2 calls open", out)
        self.transcript(use("t1", "Read", 6), use("t2", "Bash", 6), result("t1", 5))
        out = self.open_()
        self.assertIn("in Bash 6 min", out)
        self.assertNotIn("more", out)

    def test_a_denied_call_is_not_in_flight(self):
        self.transcript(use("t1", "Bash", 3), result("t1", 3, err=True))
        self.hook(self.start())
        out = self.open_()
        self.assertNotIn("in Bash", out)
        self.assertIn("running (no transcript entry for 3 min)", out)

    def test_a_new_prompt_clears_a_call_an_abort_left_open(self):
        prompt = {"type": "user", "timestamp": iso_ago(2), "message": {"content": "go on"}}
        self.transcript(use("t1", "Bash", 9), prompt, thinking(1))
        self.hook(self.start())
        out = self.open_()
        self.assertNotIn("in Bash", out)
        self.assertIn("running (no transcript entry for 1 min)", out)

    def test_thinking_last_is_measured_from_its_timestamp(self):
        # An attachment entry written later doesn't count as the agent's own.
        self.transcript(use("t1", "Read", 4), result("t1", 4), thinking(2),
                        {"type": "attachment", "timestamp": iso_ago(0)})
        self.hook(self.start())
        out = self.open_()
        self.assertIn("running (no transcript entry for 2 min)", out)
        self.assertIn("last entry thinking 2 min ago", out)

    def test_a_silent_subagent_gets_a_warning(self):
        self.transcript(thinking(20))
        self.hook(self.start())
        self.assertIn("no transcript entry for 20 min  ⚠ ask it for status", self.open_())

    def test_a_teammate_has_its_own_thresholds(self):
        with open(os.path.join(self.sub, "agent-a1.meta.json"), "w") as f:
            json.dump({"name": "team-x", "customAgentType": "researcher",
                       "teamName": "session-s1"}, f)
        self.transcript(thinking(20))
        self.hook(dict(self.start(), agent_type="team-x"))
        self.assertIn("running (no transcript entry for 20 min)", self.open_())

    def test_end_turn_keeps_the_no_stop_row_verdict(self):
        self.transcript(use("t1", "Read", 3), result("t1", 3), ended(2))
        self.hook(self.start())
        out = self.open_()
        self.assertIn("ended its turn but no stop row", out)
        self.assertIn("last entry turn ended (end_turn) 2 min ago", out)

    def test_a_lower_tool_min_flags_the_call(self):
        self.transcript(use("t1", "Bash", 5))
        self.hook(self.start())
        out = self.open_("[subagent]\ntool_min = 1\n")
        self.assertIn("in Bash 5 min  ⚠ past 1 min: a long call or stuck; check it", out)

    def test_a_malformed_file_warns_first_and_keeps_the_defaults(self):
        self.transcript(use("t1", "Bash", 40))
        self.hook(self.start())
        out = self.open_("[subagent\ntool_min = 1\n")
        self.assertTrue(out.startswith("warning: "), out)
        self.assertIn("using the default thresholds", out)
        self.assertIn("⚠ past 30 min", out)

    def test_a_bad_value_keeps_only_its_own_default(self):
        self.transcript(thinking(5))
        self.hook(self.start())
        out = self.open_("[subagent]\ntool_min = -1\nsilent_min = 1\n[subagnet]\nx = 1\n")
        first = out.splitlines()[0]
        self.assertIn("subagent.tool_min = -1 is not a positive number", first)
        self.assertIn("[subagnet] is not one of", first)
        self.assertIn("⚠ ask it for status", out)  # silent_min = 1 still applied

    def test_a_quiet_codex_run_gets_a_warning(self):
        out_dir = os.path.join(self.tmp.name, "run")
        os.makedirs(out_dir)
        events = os.path.join(out_dir, "events.jsonl")
        open(events, "w").close()
        old = time.time() - 40 * 60
        os.utime(events, (old, old))
        os.makedirs(os.path.dirname(self.ledger), exist_ok=True)
        with open(self.ledger, "w") as f:
            f.write(json.dumps({"runner": "codex", "id": "r1", "run_id": "r1", "event": "start",
                                "ts": dc.now_iso(), "out": out_dir, "pid": 2 ** 22 + 1}) + "\n")
        self.assertIn("⚠ no event past 30 min: check it", self.open_())

    def test_silent_min_flag_is_gone(self):
        p = subprocess.run(["python3", LEDGER, "open", "--silent-min", "5"], capture_output=True,
                           text=True, env=self.env)
        self.assertEqual(p.returncode, 2)

    def test_scan_handles_a_missing_or_cut_transcript(self):
        self.assertEqual(ledger_mod.scan_transcript(None)["last"], "no transcript")
        self.assertEqual(ledger_mod.scan_transcript("/nonexistent.jsonl")["last"], "no transcript")
        path = os.path.join(self.sub, "agent-cut.jsonl")
        with open(path, "w") as f:
            f.write('ol_use"}]}}\n' + json.dumps(use("t1", "Grep", 1)) + "\n")
        scan = ledger_mod.scan_transcript(path)
        self.assertEqual([tool for tool, _ in scan["open"]], ["Grep"])
        self.assertEqual(scan["last"], "tool_use")


class Watch(LiveSession):
    """`watch`: one line per live delegation, and the tmux token from `--summary`."""

    def describe(self, text, aid="a1"):
        with open(os.path.join(self.sub, f"agent-{aid}.meta.json"), "w") as f:
            json.dump({"description": text}, f)

    def watch(self, toml=None, **env):
        return self.cli("watch", toml=toml, **env).splitlines()

    def summary(self, toml=None, **env):
        out = self.cli("watch", "--summary", toml=toml, **env)
        self.assertEqual(out.count("\n"), 1, out)  # one line, even an empty one
        return out[:-1]

    def test_a_live_call_is_one_line(self):
        self.transcript(use("t1", "Bash", 5))
        self.describe("find the marker line in the fixture repo, then report back")
        self.hook(dict(self.start(), cwd="/src/proj/.claude/worktrees/agent-a1"))
        self.assertEqual(self.watch(), [
            "claude  a1  Explore  proj  in Bash 5 min  'find the marker line in the fixture repo'"])
        self.assertEqual(self.summary(), "1▶")

    def test_past_tool_min_the_line_and_the_token_warn(self):
        self.transcript(use("t1", "Bash", 5))
        self.hook(self.start())
        toml = "[subagent]\ntool_min = 1\n"
        self.assertEqual(self.watch(toml), ["claude  a1  Explore  w  in Bash 5 min ⚠"])
        self.assertEqual(self.summary(toml), "1▶ 1⚠")

    def test_a_stopped_agent_is_absent(self):
        self.transcript(use("t1", "Bash", 5), result("t1", 1), ended(1))
        self.hook(self.start())
        self.hook(self.stop())
        self.assertEqual(self.watch(), ["no live delegations"])
        self.assertEqual(self.summary(), "")

    def test_an_orphan_is_only_counted_in_the_footer(self):
        self.hook(self.start(sid="s9"))  # no session file for s9: its session is gone
        self.assertEqual(self.watch(), [
            "no live delegations",
            "1 more unfinished but not live in the last 48h: delegation-ledger open"])
        self.assertEqual(self.summary(), "")
        self.assertIn("orphaned", self.open_())

    def test_a_turn_that_just_ended_is_finishing_then_warns(self):
        # The stop row lands a few seconds after the end_turn entry; a poll in that gap
        # mustn't flash a warning.
        self.transcript(use("t1", "Read", 3), result("t1", 3), ended(0))
        self.hook(self.start())
        self.assertEqual(self.watch(), ["claude  a1  Explore  w  finishing its turn"])
        self.assertEqual(self.summary(), "1▶")
        self.assertIn("finishing its turn", self.open_())
        self.transcript(use("t1", "Read", 3), result("t1", 3), ended(2))
        self.assertEqual(self.watch(),
                         ["claude  a1  Explore  w  ended its turn but no stop row ⚠"])
        self.assertEqual(self.summary(), "1▶ 1⚠")

    def test_codex_runs_live_listed_dead_in_the_footer(self):
        self.append(self.codex_row("r1", os.getpid()), self.codex_row("r2", DEAD),
                    self.codex_row("r3", None, event="pending", wrapper_pid=os.getpid()))
        self.assertEqual(self.watch(), [
            "codex   r1  gpt-5.6-terra  proj  running, last event 0 min ago",
            "codex   r3  gpt-5.6-terra  proj  starting",
            "1 more unfinished but not live in the last 48h: delegation-ledger open"])
        self.assertEqual(self.summary(), "2▶")

    def test_watch_reads_only_the_ledger_tail(self):
        self.transcript(use("t1", "Bash", 5))
        self.hook(self.start())
        pad = {"runner": "claude", "id": "p", "event": "policy", "rule": "git-push",
               "ts": dc.now_iso(), "note": "x" * 200}
        self.append(*[pad] * (ledger_mod.WATCH_TAIL // len(json.dumps(pad)) + 10))
        self.assertGreater(os.path.getsize(self.ledger), ledger_mod.WATCH_TAIL)
        self.assertEqual(self.watch(), ["no live delegations"])  # its start row was cut off
        self.assertIn("in Bash 5 min", self.open_())             # open reads the whole ledger

    def test_the_tail_read_drops_a_line_the_cut_split(self):
        rows = [{"runner": "claude", "id": f"a{i}", "event": "start"} for i in range(3)]
        self.append(*rows)
        last = len(json.dumps(rows[-1])) + 1
        with mock.patch.dict(os.environ, {"DELEGATION_LEDGER": self.ledger}):
            self.assertEqual(dc.read_rows(tail=last), rows[-1:])      # a cut on a line end
            self.assertEqual(dc.read_rows(tail=last + 5), rows[-1:])  # a split line, dropped
            self.assertEqual(dc.read_rows(tail=1 << 20), rows)        # no cut, nothing dropped
            self.assertEqual(dc.read_rows(), rows)

    def test_a_malformed_file_warns_first_but_never_in_the_token(self):
        self.transcript(use("t1", "Bash", 5))
        self.hook(self.start())
        lines = self.watch("[subagent\n")
        self.assertTrue(lines[0].startswith("warning: "), lines)
        self.assertIn("using the default thresholds", lines[0])
        self.assertEqual(lines[1:], ["claude  a1  Explore  w  in Bash 5 min"])
        self.assertEqual(self.summary("[subagent\n"), "1▶")


class Sandbox(LiveSession):
    """A call inside the Bash sandbox: CLAUDE_PID is set, but its own PID namespace hides that
    process, so no pid check means anything. Here s1's session is gone, so a visible check
    would call its agent orphaned."""

    def setUp(self):
        super().setUp()
        os.remove(os.path.join(self.tmp.name, ".claude", "sessions", "1.json"))
        self.transcript(use("t1", "Bash", 5))
        self.hook(self.start())

    def test_open_warns_first_and_calls_the_session_unknown(self):
        out = self.cli("open", CLAUDE_PID=str(DEAD))
        self.assertEqual(out.splitlines()[0], "warning: " + ledger_mod.SANDBOX_WARNING)
        self.assertIn("in Bash 5 min", out)
        self.assertIn("session unknown (no pid visible in the sandbox)", out)
        self.assertNotIn("orphaned", out)

    def test_watch_warns_first_and_lists_the_agent(self):
        self.assertEqual(self.watch_lines(CLAUDE_PID=str(DEAD)),
                         ["warning: " + ledger_mod.SANDBOX_WARNING,
                          "claude  a1  Explore  w  in Bash 5 min"])
        self.assertEqual(self.cli("watch", "--summary", CLAUDE_PID=str(DEAD)), "1▶\n")

    def test_a_visible_claude_pid_keeps_the_orphan_verdict(self):
        out = self.cli("open", CLAUDE_PID=str(os.getpid()))
        self.assertNotIn("warning", out)
        self.assertIn("orphaned", out)
        self.assertEqual(self.watch_lines(CLAUDE_PID=str(os.getpid()))[0], "no live delegations")

    def test_a_codex_run_is_not_called_dead(self):
        self.append(self.codex_row("r1", DEAD))
        out = self.cli("open", CLAUDE_PID=str(DEAD))
        self.assertIn("pid not visible in the sandbox", out)
        self.assertIn("not visible in the sandbox, last event 0 min ago", out)
        self.assertNotIn("died", out)
        self.assertIn("codex   r1  gpt-5.6-terra  proj  pid not visible, last event 0 min ago",
                      self.watch_lines(CLAUDE_PID=str(DEAD)))

    def watch_lines(self, **env):
        return self.cli("watch", **env).splitlines()


class ProcStart(LedgerEnv):
    """A session file's procStart must match the pid's start time (field 22 of
    /proc/<pid>/stat), so a pid the kernel reused doesn't keep a gone session alive."""

    def own_start(self):
        with open("/proc/self/stat") as f:
            return int(f.read().rsplit(") ", 1)[1].split()[19])

    def open_with_session(self, **fields):
        sessions = os.path.join(self.tmp.name, ".claude", "sessions")
        os.makedirs(sessions)
        with open(os.path.join(sessions, "1.json"), "w") as f:
            json.dump(dict({"pid": os.getpid(), "sessionId": "s1"}, **fields), f)
        self.hook(self.start())
        return subprocess.run(["python3", LEDGER, "open"], capture_output=True, text=True,
                              env=self.env).stdout

    def test_a_mismatched_proc_start_is_a_gone_session(self):
        out = self.open_with_session(procStart="1")
        self.assertIn("orphaned", out)
        self.assertIn("session gone", out)

    def test_a_matching_proc_start_is_a_live_session(self):
        out = self.open_with_session(procStart=self.own_start())
        self.assertNotIn("orphaned", out)
        self.assertIn("session alive", out)

    def test_pid_alive_checks_the_start_only_when_given(self):
        start = self.own_start()
        self.assertTrue(dc.pid_alive(os.getpid()))
        self.assertTrue(dc.pid_alive(os.getpid(), start))
        self.assertTrue(dc.pid_alive(os.getpid(), str(start)))
        self.assertFalse(dc.pid_alive(os.getpid(), start + 1))
        self.assertFalse(dc.pid_alive(DEAD, start))
        self.assertEqual(dc.proc_start(os.getpid()), start)


if __name__ == "__main__":
    unittest.main()
