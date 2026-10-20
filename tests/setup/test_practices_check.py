"""hooks/practices-check.sh: the practices hook engine (stdlib only).

Each test builds a project with a synthetic skill (`demo`) in .claude/skills/, a config home
with more skills, and a transcript in the shapes 2.1.304 writes: a tool_use in an assistant
row, its tool_result in the next user row ("PreToolUse:<tool> hook error: <reason>" with is_error
on a deny), a compaction as a `system`/`compact_boundary` row (compactMetadata.preservedMessages
lists the uuids it kept) followed by an isCompactSummary user row; a subagent's rows sit in
<session>/subagents/agent-<id>.jsonl with isSidechain. The hook runs as Claude Code runs it: the
event JSON on stdin of `bash hooks/practices-check.sh`.

The samples check loads every tests/setup/practices_samples/*.toml ([[sample]] kind, id, fires,
path, content) against skills/<file stem>/events.toml, and every shipped skills/*/events.toml
must parse, keep unique ids and pass the backtracking lint.
"""
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "practices-check.sh")
SAMPLES = os.path.join(REPO, "tests", "setup", "practices_samples")
SID = "0b7e4c1a-2f3d-4e5f-8a9b-c0d1e2f3a4b5"
DENY = "PreToolUse:Write hook error: "

DEMO = r"""
skill = "demo"
gate = ["A route handler checks the session before it reads input.",
        "An id from the request body is never trusted."]

[[event]]
id = "route-handler"
paths = ["**/app/**/route.{ts,js}", "**/pages/api/**"]
content = ['''^\s*["']use server["']''']
lines = ["Check the session first.", "Scope every query to the caller."]

[[event]]
id = "migration"
paths = ["migrations/*.sql"]
lines = ["Turn on row level security."]

[[rule]]
id = "SEC-17"
when = '''\.\.\.body\b'''
say = "Spreading the request body into a write lets a caller set any column."

[[rule]]
id = "SEC-01"
when = '''export async function (GET|POST)'''
unless = '''\b{auth_helpers}\('''
paths = ["**/route.ts"]
say = "This handler calls no auth helper."
"""

OTHER = r"""
skill = "other"
gate = ["Other's one line."]
[[event]]
id = "routes-too"
paths = ["**/route.ts"]
lines = ["Other's event line."]
"""


def load_module():
    spec = importlib.util.spec_from_file_location(
        "practices_check", os.path.join(REPO, "hooks", "practices_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PC = load_module()


def use(tid, name, sidechain=False, uuid=None, **inp):
    row = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}
    if sidechain:
        row["isSidechain"] = True
    if uuid:
        row["uuid"] = uuid
    return row


def result(tid, content="ok", error=False, sidechain=False):
    block = {"tool_use_id": tid, "type": "tool_result", "content": content}
    if error:
        block["is_error"] = True
    row = {"type": "user", "message": {"role": "user", "content": [block]}}
    if sidechain:
        row["isSidechain"] = True
    return row


def text(words="done"):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": words}]}}


def boundary(*kept):
    meta = {"trigger": "manual", "preTokens": 1000, "postTokens": 100}
    if kept:
        meta["preservedMessages"] = {"anchorUuid": "anchor", "uuids": list(kept),
                                     "allUuids": list(kept)}
    return [{"parentUuid": None, "isSidechain": False, "type": "system",
             "subtype": "compact_boundary", "content": "Conversation compacted",
             "compactMetadata": meta, "uuid": "b-" + str(len(kept))},
            {"type": "user", "isCompactSummary": True, "uuid": "anchor", "message": {
                "role": "user", "content": "This session is being continued ..."}}]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="practices-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.config = os.path.join(self.home, ".claude")
        self.proj = os.path.join(self.tmp, "proj")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(os.path.join(self.config, "skills"))
        os.makedirs(self.proj)
        self.skill("demo", DEMO)
        self.transcript = os.path.join(self.tmp, "projects", SID + ".jsonl")
        os.makedirs(os.path.dirname(self.transcript))
        self.rows([])
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("CLAUDE_CONFIG_DIR", "PRACTICES_TEST_BUDGET")}
        self.env.update(HOME=self.home, CLAUDE_CONFIG_DIR=self.config, XDG_STATE_HOME=self.state,
                        CLAUDE_PROJECT_DIR=self.proj)

    def skill(self, name, body, where="project"):
        root = (os.path.join(self.proj, ".claude", "skills") if where == "project"
                else os.path.join(self.config, "skills"))
        d = os.path.join(root, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w") as f:
            f.write(f"---\nname: {name}\n---\n")
        with open(os.path.join(d, "events.toml"), "w") as f:
            f.write(body)
        return d

    def config_toml(self, body):
        d = os.path.join(self.proj, ".claude", "practices")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "config.toml"), "w") as f:
            f.write(body)

    def rows(self, rows, path=None):
        with open(path or self.transcript, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "permission-mode", "permissionMode": "default"}) + "\n")
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")

    def add(self, *rows, path=None):
        with open(path or self.transcript, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")

    def run_hook(self, event, stdin=None):
        p = subprocess.run(["bash", HOOK], input=stdin if stdin is not None else json.dumps(event),
                           capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout) if p.stdout.strip() else None

    def fire(self, rel="app/api/x/route.ts", content="export const x = 1\n", tool="Write",
             **extra):
        path = os.path.join(self.proj, rel)
        inp = ({"file_path": path, "content": content} if tool == "Write" else
               {"file_path": path, "old_string": "a", "new_string": content} if tool == "Edit"
               else {"file_path": path, "edits": [{"old_string": "a", "new_string": content}]})
        event = {"session_id": SID, "transcript_path": self.transcript, "cwd": self.proj,
                 "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp,
                 "tool_use_id": "t-now", **extra}
        out = self.run_hook(event)
        if out is None:
            return None
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        return hso["permissionDecisionReason"]

    def start(self, source, **extra):
        return self.run_hook({"session_id": SID, "transcript_path": self.transcript,
                              "cwd": self.proj, "hook_event_name": "SessionStart",
                              "source": source, **extra})

    def log(self):
        try:
            with open(os.path.join(self.state, "dotclaude", "practices", "errors.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def loaded(self):
        self.rows([use("t-skill", "Skill", skill="demo"), result("t-skill", "Launching skill")])


class L1(Base):
    def test_denies_an_event_while_the_skill_is_not_loaded(self):
        reason = self.fire()
        self.assertTrue(reason.startswith("[practices:L1:demo:route-handler]"), reason)
        self.assertIn("app/api/x/route.ts", reason)
        self.assertIn('Skill tool with "demo"', reason)
        self.assertIn(os.path.join(self.proj, ".claude", "skills", "demo", "SKILL.md"), reason)
        self.assertIn("- Check the session first.", reason)
        self.assertIn("resend", reason)
        self.assertNotIn("[practices:L2:", reason)

    def test_content_alone_can_fire_an_event(self):
        reason = self.fire("lib/actions.ts", '"use server"\nexport async function f() {}\n',
                           tool="Edit")
        self.assertTrue(reason.startswith("[practices:L1:demo:route-handler]"), reason)
        self.assertIsNone(self.fire("lib/plain.ts", "const s = 'use server'\n", tool="Edit"))

    def test_multiedit_content_counts(self):
        self.assertIsNotNone(self.fire("lib/a.ts", "'use server'\n", tool="MultiEdit"))

    def test_a_file_outside_every_event_passes(self):
        self.assertIsNone(self.fire("lib/util.ts", "export const x = 1\n"))

    def test_bash_passes_unchecked(self):
        out = self.run_hook({"session_id": SID, "transcript_path": self.transcript,
                             "cwd": self.proj, "hook_event_name": "PreToolUse",
                             "tool_name": "Bash", "tool_input": {
                                 "command": "cat > app/api/x/route.ts <<'EOF'\n...body\nEOF"}})
        self.assertIsNone(out)

    def test_a_skill_call_loads_it(self):
        self.loaded()
        self.assertIsNone(self.fire())

    def test_a_plugin_qualified_skill_call_loads_it(self):
        self.rows([use("t1", "Skill", skill="plug:demo")])
        self.assertIsNone(self.fire())

    def test_a_read_of_its_skill_md_loads_it(self):
        self.rows([use("t1", "Read", file_path=os.path.join(
            self.proj, ".claude", "skills", "demo", "SKILL.md"))])
        self.assertIsNone(self.fire())

    def test_another_skills_load_does_not_count(self):
        self.rows([use("t1", "Skill", skill="demolition"),
                   use("t2", "Read", file_path="/x/demo-old/SKILL.md")])
        self.assertIsNotNone(self.fire())

    def test_the_resend_after_its_own_deny_passes(self):
        reason = self.fire()
        self.add(use("t1", "Write", file_path="x"), result("t1", DENY + reason, error=True))
        self.assertIsNone(self.fire())

    def test_the_marker_is_found_whatever_claude_code_wraps_it_in(self):
        reason = self.fire()
        self.add(result("t1", [{"type": "text", "text": "Hook said no >> " + reason}]))
        self.assertIsNone(self.fire())

    def test_a_second_event_of_the_same_skill_denies_separately(self):
        reason = self.fire()
        self.add(result("t1", DENY + reason, error=True))
        second = self.fire("migrations/001_init.sql", "create table t (id int);")
        self.assertTrue(second.startswith("[practices:L1:demo:migration]"), second)
        self.assertNotIn("route-handler", second)

    def test_a_load_before_the_last_compaction_does_not_count(self):
        self.rows([use("t1", "Skill", skill="demo"), text(), *boundary()])
        self.assertIsNotNone(self.fire())

    def test_a_load_the_compaction_preserved_counts(self):
        self.rows([use("t1", "Skill", skill="demo", uuid="kept-1"), *boundary("kept-1")])
        self.assertIsNone(self.fire())

    def test_a_deny_before_the_last_compaction_does_not_count(self):
        reason = self.fire()
        self.add(result("t1", DENY + reason, error=True), *boundary())
        self.assertIsNotNone(self.fire())

    def test_a_load_after_the_compaction_counts(self):
        self.rows([*boundary(), use("t1", "Skill", skill="demo")])
        self.assertIsNone(self.fire())

    def test_one_deny_names_every_skill_that_fired(self):
        self.skill("other", OTHER, where="user")
        reason = self.fire()
        self.assertIn("[practices:L1:demo:route-handler]", reason)
        self.assertIn("[practices:L1:other:routes-too]", reason)
        self.assertIn("Other's event line.", reason)

    def test_a_transcript_quote_in_model_text_is_no_deny(self):
        self.rows([text("[practices:L1:demo:route-handler] quoted")])
        self.assertIsNotNone(self.fire())


class L2(Base):
    def setUp(self):
        super().setUp()
        self.loaded()

    def test_denies_once_per_file_and_rule(self):
        reason = self.fire("lib/save.ts", "db.insert({ ...body })\n", tool="Edit")
        self.assertTrue(reason.startswith("[practices:L2:demo:SEC-17:lib/save.ts]"), reason)
        self.assertIn("Spreading the request body", reason)
        self.assertIn("practices-allow: SEC-17 <reason>", reason)
        self.add(use("t1", "Edit", file_path="x"), result("t1", DENY + reason, error=True))
        self.assertIsNone(self.fire("lib/save.ts", "db.insert({ ...body })\n", tool="Edit"))
        other = self.fire("lib/other.ts", "db.insert({ ...body })\n", tool="Edit")
        self.assertTrue(other.startswith("[practices:L2:demo:SEC-17:lib/other.ts]"), other)

    def test_a_deny_holds_across_a_compaction(self):
        reason = self.fire("lib/save.ts", "x({ ...body })\n")
        self.add(result("t1", DENY + reason, error=True), *boundary(),
                 use("t2", "Skill", skill="demo"))
        self.assertIsNone(self.fire("lib/save.ts", "x({ ...body })\n"))

    def test_practices_allow_suppresses_the_rule(self):
        self.assertIsNone(self.fire(
            "lib/save.ts", "// practices-allow: SEC-17 body is parsed by zod above\nx({ ...body })"))
        self.assertIsNotNone(self.fire("lib/save.ts", "// practices-allow: SEC-170\nx({ ...body })"))

    def test_an_l1_deny_suppresses_l2_in_the_same_call(self):
        self.rows([])
        reason = self.fire("app/api/x/route.ts", "x({ ...body })\n")
        self.assertIn("[practices:L1:demo:route-handler]", reason)
        self.assertNotIn("[practices:L2:", reason)

    def test_unless_and_the_repos_auth_helpers(self):
        handler = "export async function GET() {\n  const u = await requireMember()\n}\n"
        reason = self.fire("app/api/x/route.ts", handler)
        self.assertTrue(reason.startswith("[practices:L2:demo:SEC-01:app/api/x/route.ts]"), reason)
        self.assertIsNone(self.fire("app/api/y/route.ts", handler.replace("requireMember", "auth")))
        self.config_toml('[auth]\nhelpers = ["requireMember"]\n')
        self.assertIsNone(self.fire("app/api/z/route.ts", handler))

    def test_a_throwing_pattern_is_skipped_and_logged_and_the_rest_still_run(self):
        self.skill("bad", 'skill = "bad"\n[[rule]]\nid = "B-1"\nwhen = "("\nsay = "x"\n',
                   where="user")
        reason = self.fire("lib/save.ts", "x({ ...body })\n")
        self.assertIn("[practices:L2:demo:SEC-17:lib/save.ts]", reason)
        self.assertIn("pattern-skipped B-1", self.log())

    def test_a_spent_budget_skips_the_patterns_left_and_logs_them(self):
        self.env["PRACTICES_TEST_BUDGET"] = "0"
        self.assertIsNone(self.fire("lib/save.ts", "x({ ...body })\n"))
        self.assertIn("budget-spent", self.log())
        self.assertIn("demo:SEC-17", self.log())


class L4(Base):
    def digest(self):
        out = self.start("compact")
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "SessionStart")
        self.assertIs(hso["reloadSkills"], True)
        return hso.get("additionalContext")

    def test_names_only_the_skills_loaded_since_the_previous_compaction(self):
        self.skill("other", OTHER, where="user")
        before = [use("t1", "Skill", skill="other"), text(), *boundary(),
                  use("t2", "Skill", skill="demo"), text()]
        for rows in (before, before + boundary()):  # the new boundary on disk yet or not
            with self.subTest(written=len(rows) > len(before)):
                self.rows(rows)
                ctx = self.digest()
                self.assertIn("demo", ctx)
                self.assertNotIn("other", ctx)
                self.assertIn("An id from the request body is never trusted.", ctx)
                self.assertLess(len(ctx), 2000)

    def test_no_practices_skill_loaded_still_reloads_skills(self):
        self.rows([use("t1", "Skill", skill="lanes"), text()])
        self.assertIsNone(self.digest())

    def test_a_long_digest_stays_under_2000_characters(self):
        self.skill("demo", 'skill = "demo"\ngate = [' + ", ".join(
            [json.dumps("x" * 400)] * 6) + "]\n")
        self.loaded()
        ctx = self.digest()
        self.assertLess(len(ctx), 2000)
        self.assertTrue(ctx.startswith("Practices skills loaded before this compaction: demo."))

    def test_resume_and_clear_print_nothing(self):
        self.loaded()
        self.assertIsNone(self.start("resume"))
        self.assertIsNone(self.start("clear"))


class Subagents(Base):
    AGENT = "a0123456789abcdef"

    def agent_file(self):
        d = os.path.join(self.transcript[:-len(".jsonl")], "subagents")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"agent-{self.AGENT}.jsonl")

    def test_the_agents_own_transcript_decides(self):
        self.loaded()  # the parent's load must not count for the agent
        self.rows([use("s0", "Read", sidechain=True, file_path="/x/notes.md")],
                  path=self.agent_file())
        reason = self.fire(agent_id=self.AGENT, agent_type="general-purpose")
        self.assertIn("[practices:L1:demo:route-handler]", reason)
        self.assertIn("Read " + os.path.join(self.proj, ".claude", "skills", "demo", "SKILL.md"),
                      reason)
        self.assertNotIn("Skill tool", reason)
        self.add(result("s1", DENY + reason, error=True, sidechain=True), path=self.agent_file())
        self.assertIsNone(self.fire(agent_id=self.AGENT))

    def test_an_agents_read_of_skill_md_loads_it(self):
        self.rows([use("s1", "Read", sidechain=True, file_path=os.path.join(
            self.proj, ".claude", "skills", "demo", "SKILL.md"))], path=self.agent_file())
        self.assertIsNone(self.fire(agent_id=self.AGENT))

    def test_a_missing_agent_transcript_falls_back_to_a_state_file(self):
        self.loaded()
        reason = self.fire(agent_id=self.AGENT)
        self.assertIn("[practices:L1:demo:route-handler]", reason)
        self.assertIsNone(self.fire(agent_id=self.AGENT))  # the resend
        self.assertTrue(glob.glob(os.path.join(self.state, "dotclaude", "practices", "denies",
                                               "*.json")))
        l2 = self.fire("lib/save.ts", "x({ ...body })\n", agent_id=self.AGENT)
        self.assertIn("[practices:L1:demo:route-handler]", self.fire(
            "app/b/route.ts", "", agent_id="another-agent"))
        self.assertIsNone(self.fire("lib/save.ts", "x({ ...body })\n", agent_id=self.AGENT))
        self.assertIn("[practices:L2:demo:SEC-17:lib/save.ts]", l2)


class Discovery(Base):
    def test_the_project_copy_wins_a_name_clash(self):
        self.skill("demo", 'skill = "demo"\n[[event]]\nid = "py"\npaths = ["*.py"]\n',
                   where="user")
        reason = self.fire()
        self.assertIn(os.path.join(self.proj, ".claude", "skills", "demo", "SKILL.md"), reason)
        self.assertNotIn(self.config, reason)
        self.assertIsNone(self.fire("tool.py", "x = 1\n"))

    def test_user_skills_are_found(self):
        shutil.rmtree(os.path.join(self.proj, ".claude", "skills"))
        self.skill("demo", DEMO, where="user")
        self.assertIn(os.path.join(self.config, "skills", "demo", "SKILL.md"), self.fire())

    def test_a_malformed_events_toml_skips_only_that_skill(self):
        self.skill("broken", "skill = [unclosed\n", where="user")
        self.skill("dupes", 'skill = "dupes"\n[[event]]\nid = "a"\n[[rule]]\nid = "a"\n'
                   'when = "x"\nsay = "y"\n', where="user")
        self.assertIn("[practices:L1:demo:route-handler]", self.fire())
        log = self.log()
        self.assertIn("skill-disabled", log)
        self.assertIn(os.path.join("broken", "events.toml"), log)
        self.assertIn("duplicate ids", log)

    def test_cwd_stands_in_for_a_missing_project_dir(self):
        del self.env["CLAUDE_PROJECT_DIR"]
        self.assertIn("[practices:L1:demo:route-handler]", self.fire())


class Config(Base):
    def test_enabled_false_turns_the_engine_off(self):
        self.config_toml("enabled = false\n")
        self.assertIsNone(self.fire())
        self.loaded()
        self.assertIsNone(self.start("compact"))

    def test_disable_turns_one_event_or_rule_off(self):
        self.config_toml('[[disable]]\nrule = "route-handler"\nreason = "no routes here"\n'
                         '[[disable]]\nrule = "demo:SEC-17"\nreason = "zod parses bodies"\n')
        self.assertIsNone(self.fire())
        self.assertIsNone(self.fire("lib/save.ts", "x({ ...body })\n"))
        self.assertIsNotNone(self.fire("migrations/1.sql", "create table t ();"))

    def test_a_disable_without_a_reason_turns_nothing_off(self):
        self.config_toml('[[disable]]\nrule = "route-handler"\n')
        self.assertIsNotNone(self.fire())
        self.assertIn("config-malformed", self.log())

    def test_a_malformed_config_falls_back_to_the_defaults(self):
        for body in ("enabled = false\n[[disable\n", 'enabled = "no"\n',
                     '[auth]\nhelpers = "requireMember"\n'):
            with self.subTest(body=body):
                self.config_toml(body)
                self.assertIsNotNone(self.fire())
        self.assertIn("config-malformed", self.log())


class Failures(Base):
    def test_a_crash_allows_silently_and_is_logged(self):
        self.assertIsNone(self.run_hook(None, stdin="not json {"))
        self.assertIn("crash", self.log())

    def test_a_normal_exit_leaves_no_breadcrumb(self):
        self.fire("lib/actions.ts", "'use server'\n")
        crumbs = glob.glob(os.path.join(self.state, "dotclaude", "practices", "breadcrumb*"))
        self.assertEqual(crumbs, [])

    def test_startup_is_silent_when_all_is_well(self):
        self.assertIsNone(self.start("startup"))

    def test_startup_reports_a_leftover_breadcrumb_once(self):
        d = os.path.join(self.state, "dotclaude", "practices")
        os.makedirs(d)
        crumb = os.path.join(d, "breadcrumb-4242")
        with open(crumb, "w") as f:
            json.dump({"file": "app/x.ts", "level": "L2", "pattern": "SEC-17"}, f)
        os.utime(crumb, (0, 0))  # long ago: no live scan
        msg = self.start("startup")["systemMessage"]
        self.assertTrue(msg.startswith("practices hooks: "), msg)
        self.assertIn("killed mid-scan (L2 SEC-17 on app/x.ts)", msg)
        self.assertIsNone(self.start("startup"))

    def test_a_fresh_breadcrumb_is_a_live_scan_and_stays(self):
        d = os.path.join(self.state, "dotclaude", "practices")
        os.makedirs(d)
        with open(os.path.join(d, "breadcrumb-4243"), "w") as f:
            f.write("{}")
        self.assertIsNone(self.start("startup"))
        self.assertTrue(os.path.exists(os.path.join(d, "breadcrumb-4243")))

    def test_startup_reports_errors_logged_since_the_last_start(self):
        self.run_hook(None, stdin="not json {")
        self.skill("broken", "skill = [\n", where="user")
        msg = self.start("startup")["systemMessage"]
        self.assertIn("1 crash", msg)
        self.assertIn("1 skill disabled", msg)
        self.assertIn("errors.log", msg)
        shutil.rmtree(os.path.join(self.config, "skills", "broken"))
        self.assertIsNone(self.start("startup"))


def check_samples(sample_file, skill_dir):
    """The samples in sample_file the engine gets wrong, as strings."""
    skill, why = PC.load_skill(skill_dir)
    if skill is None:
        return [f"skill does not load: {why}"]
    with open(sample_file, "rb") as f:
        samples = tomllib.load(f).get("sample", [])
    events = {e["id"]: e for e in skill["events"]}
    rules = {r["id"]: r for r in skill["rules"]}
    wrong = []
    for s in samples:
        item = (events if s["kind"] == "event" else rules).get(s["id"])
        if item is None:
            wrong.append(f"{s['kind']} {s['id']}: no such id")
            continue
        fn = PC.event_fires if s["kind"] == "event" else PC.rule_fires
        got = fn(item, s["path"], PC.scan_text(s["content"]))
        if got != s["fires"]:
            wrong.append(f"{s['kind']} {s['id']} on {s['path']}: fired={got}, want {s['fires']}")
    return wrong


def regexes(skill):
    for e in skill["events"]:
        yield from ((e["id"], p) for p in e.get("content", []))
    for r in skill["rules"]:
        yield r["id"], r["when"]
        if r.get("unless"):
            yield r["id"], r["unless"]


class Shipped(unittest.TestCase):
    def test_every_samples_file_matches_its_skill(self):
        for path in sorted(glob.glob(os.path.join(SAMPLES, "*.toml"))):
            name = os.path.splitext(os.path.basename(path))[0]
            with self.subTest(samples=name):
                self.assertEqual(check_samples(path, os.path.join(REPO, "skills", name)), [])

    def test_the_samples_check_catches_a_wrong_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "demo")
            os.makedirs(skill)
            with open(os.path.join(skill, "events.toml"), "w") as f:
                f.write(DEMO)
            samples = os.path.join(tmp, "demo.toml")
            with open(samples, "w") as f:
                f.write("[[sample]]\nkind = 'event'\nid = 'route-handler'\nfires = true\n"
                        "path = 'app/api/a/route.ts'\ncontent = ''\n"
                        "[[sample]]\nkind = 'rule'\nid = 'SEC-17'\nfires = false\n"
                        "path = 'lib/a.ts'\ncontent = 'x({ ...body })'\n"
                        "[[sample]]\nkind = 'rule'\nid = 'SEC-01'\nfires = false\n"
                        "path = 'app/route.ts'\ncontent = 'export async function GET() "
                        "{ await auth() }'\n")
            self.assertEqual(check_samples(samples, skill),
                             ["rule SEC-17 on lib/a.ts: fired=True, want False"])

    def test_every_shipped_events_toml_parses_with_unique_ids_and_safe_regexes(self):
        for path in sorted(glob.glob(os.path.join(REPO, "skills", "*", "events.toml"))):
            folder = os.path.dirname(path)
            with self.subTest(skill=os.path.basename(folder)):
                skill, why = PC.load_skill(folder)
                self.assertIsNotNone(skill, why)
                for owner, pattern in regexes(skill):
                    self.assertIsNone(PC.lint_regex(pattern), owner)
                for item in skill["events"] + skill["rules"]:
                    for g in item.get("paths", []):
                        PC.re.compile(PC.glob_regex(g))

    def test_the_lint(self):
        for bad in ("(a+)+", "(a*)*", "(.*)+", r"(?:\s*,\s*\w+)*", "(ab|ab)*", "("):
            with self.subTest(bad=bad):
                self.assertIsNotNone(PC.lint_regex(bad))
        for good in (r'''^\s*["']use server["']''', r"\b{auth_helpers}\(", "a{1,3}(b+)",
                     r"\.\.\.body\b", r"(?:ab){2}c+"):
            with self.subTest(good=good):
                self.assertIsNone(PC.lint_regex(good))


class Globs(unittest.TestCase):
    def test_globs(self):
        cases = [("**/app/**/route.{ts,js}", "app/api/x/route.ts", True),
                 ("**/app/**/route.{ts,js}", "src/app/route.js", True),
                 ("**/app/**/route.{ts,js}", "app/route.tsx", False),
                 ("**/app/**/route.{ts,js}", "myapp/route.ts", False),
                 ("**/pages/api/**", "pages/api/users/[id].ts", True),
                 ("migrations/*.sql", "migrations/001.sql", True),
                 ("migrations/*.sql", "migrations/old/001.sql", False),
                 ("*.sql", "db/migrations/001.sql", True),
                 ("a?c.ts", "abc.ts", True), ("a?c.ts", "a/c.ts", False),
                 ("**/route.ts", "/abs/outside/app/route.ts", True)]
        for glob_, path, want in cases:
            with self.subTest(glob=glob_, path=path):
                self.assertEqual(PC.path_matches([glob_], path), want)


if __name__ == "__main__":
    unittest.main()
