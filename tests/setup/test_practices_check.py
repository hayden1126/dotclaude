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
import contextlib
import glob
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from unittest import mock

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


def load(tid, name, sidechain=False, uuid=None, error=False, **inp):
    """A Skill call or Read and its result: a load counts only with a result that isn't an
    error."""
    return [use(tid, name, sidechain=sidechain, uuid=uuid, **inp),
            result(tid, "File does not exist." if error else "Launching skill", error=error,
                   sidechain=sidechain)]


def text(words="done"):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": words}]}}


BOUNDARIES = iter(range(1, 1 << 30))


def boundary(*kept):
    meta = {"trigger": "manual", "preTokens": 1000, "postTokens": 100}
    if kept:
        meta["preservedMessages"] = {"anchorUuid": "anchor", "uuids": list(kept),
                                     "allUuids": list(kept)}
    return [{"parentUuid": None, "isSidechain": False, "type": "system",
             "subtype": "compact_boundary", "content": "Conversation compacted",
             "compactMetadata": meta, "uuid": f"boundary-{next(BOUNDARIES)}"},
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

    def existing(self, rel, content):
        path = os.path.join(self.proj, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    def fire(self, rel="app/api/x/route.ts", content="export const x = 1\n", tool="Write",
             old="a", edits=None, **extra):
        path = os.path.join(self.proj, rel)
        inp = ({"file_path": path, "content": content} if tool == "Write" else
               {"file_path": path, "old_string": old, "new_string": content} if tool == "Edit"
               else {"file_path": path, "edits": edits or [{"old_string": old,
                                                            "new_string": content}]})
        if tool == "Edit" and extra.get("replace_all"):
            inp["replace_all"] = extra.pop("replace_all")
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
        self.rows(load("t1", "Skill", skill="plug:demo"))
        self.assertIsNone(self.fire())

    def test_a_read_of_its_skill_md_loads_it(self):
        self.rows(load("t1", "Read", file_path=os.path.join(
            self.proj, ".claude", "skills", "demo", "SKILL.md")))
        self.assertIsNone(self.fire())

    def test_a_failed_load_does_not_count(self):
        cases = (load("t1", "Skill", skill="demo", error=True),
                 load("t1", "Read", file_path="/wrong/demo/SKILL.md", error=True),
                 [use("t1", "Skill", skill="demo")])  # no result yet
        for n, rows in enumerate(cases):
            with self.subTest(case=n):
                self.rows(rows)
                self.assertIsNotNone(self.fire(session_id=f"session-{n}"))

    def test_another_skills_load_does_not_count(self):
        self.rows([*load("t1", "Skill", skill="demolition"),
                   *load("t2", "Read", file_path="/x/demo-old/SKILL.md")])
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
        self.rows([*load("t1", "Skill", skill="demo"), text(), *boundary()])
        self.assertIsNotNone(self.fire())

    def test_a_load_the_compaction_preserved_counts(self):
        self.rows([*load("t1", "Skill", skill="demo", uuid="kept-1"), text(),
                   *boundary("kept-1", "not-in-this-file")])
        self.assertIsNone(self.fire())

    def test_a_deny_before_the_last_compaction_does_not_count(self):
        reason = self.fire()
        self.add(result("t1", DENY + reason, error=True), *boundary())
        self.assertIsNotNone(self.fire())

    def test_a_load_after_the_compaction_counts(self):
        self.rows([*boundary(), *load("t1", "Skill", skill="demo")])
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


class Backstop(Base):
    """The state file allows a resend whose deny the transcript doesn't show."""

    def test_a_deny_row_without_the_marker_still_lets_the_resend_through(self):
        self.assertIsNotNone(self.fire())
        self.add(use("t1", "Write", file_path="x"),  # a release that moved the reason elsewhere
                 result("t1", "PreToolUse:Write hook error: (see attachment)", error=True))
        self.assertIsNone(self.fire())
        self.loaded()
        self.assertIsNotNone(self.fire("lib/save.ts", "x({ ...body })\n"))
        self.assertIsNone(self.fire("lib/save.ts", "x({ ...body })\n"))
        self.assertIsNotNone(self.fire("lib/other.ts", "x({ ...body })\n"))

    def test_a_new_compaction_denies_l1_again(self):
        self.assertIsNotNone(self.fire())
        self.assertIsNone(self.fire())
        self.add(*boundary())
        self.assertIsNotNone(self.fire())
        self.assertIsNone(self.fire())
        self.add(*boundary())
        self.assertIsNotNone(self.fire())

    def test_a_malformed_state_file_reads_as_empty_and_checking_goes_on(self):
        d = os.path.join(self.state, "dotclaude", "practices", "denies")
        os.makedirs(d)
        path = os.path.join(d, hashlib.sha256(f"{SID}|main".encode()).hexdigest()[:32] + ".json")
        for n, body in enumerate(('{"keys": null}', '{"keys": 3}', '{"keys": "L1|none"}',
                                  '{"keys": [1]}', "[1]", "not json")):
            with self.subTest(body=body):
                self.rows([])
                with open(path, "w") as f:
                    f.write(body)
                reason = self.fire()
                self.assertIn("[practices:L1:demo:route-handler]", reason)
                log = self.log()
                self.assertIn("state-error", log)
                self.assertNotIn("crash", log)
                self.add(result(f"t{n}", DENY + reason, error=True))
                with open(path, "w") as f:
                    f.write(body)
                self.assertIsNone(self.fire())  # the transcript marker still holds

    def test_an_l2_deny_holds_across_a_compaction_by_state_too(self):
        self.loaded()
        self.assertIsNotNone(self.fire("lib/save.ts", "x({ ...body })\n"))
        self.add(*boundary(), *load("t2", "Skill", skill="demo"))
        self.assertIsNone(self.fire("lib/save.ts", "x({ ...body })\n"))

    def test_an_unkept_deny_with_an_empty_transcript_allows_the_edit_and_logs(self):
        # Review round 2, leftover 2: with an unwritable state dir and an empty transcript, an
        # L1 or L2 deny could never be seen again, so every resend was denied too.
        d = os.path.join(self.state, "dotclaude", "practices")
        os.makedirs(d)
        open(os.path.join(d, "denies"), "w").close()  # the state dir can't be made
        self.assertIsNotNone(self.fire())  # the transcript has rows: its marker lets it through
        open(self.transcript, "w").close()
        for _ in range(2):
            self.assertIsNone(self.fire())
        self.loaded()
        self.assertIsNotNone(self.fire("lib/save.ts", "x({ ...body })\n"))
        open(self.transcript, "w").close()
        self.assertIsNone(self.fire("lib/save.ts", "x({ ...body })\n"))
        self.assertIn("the deny couldn't be kept and the transcript is empty", self.log())

    def test_a_spent_budget_during_the_transcript_read_allows_and_logs(self):
        self.env["PRACTICES_TEST_BUDGET"] = "0"  # the route matches by path: no pattern runs
        self.assertIsNone(self.fire())
        self.assertIn("budget-spent", self.log())
        self.assertIn("transcript", self.log())

    def test_the_breadcrumb_names_the_transcript_read(self):
        seen = {}

        def window(t):
            for n in os.listdir(os.path.join(self.state, "dotclaude", "practices")):
                if n.startswith("breadcrumb-"):
                    with open(os.path.join(self.state, "dotclaude", "practices", n)) as f:
                        seen.update(json.load(f))
            return None, "none"

        event = {"session_id": SID, "transcript_path": self.transcript, "cwd": self.proj,
                 "tool_name": "Write", "tool_input": {
                     "file_path": os.path.join(self.proj, "app/api/x/route.ts"), "content": ""}}
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(PC, "BUDGET", 1e9), mock.patch.object(PC, "l1_window", window):
            try:
                self.assertIsNotNone(PC.pre_tool_use(event))
            finally:
                PC.CRUMB.clear()
        self.assertEqual(seen.get("level"), "transcript")
        self.assertEqual(seen.get("file"), "app/api/x/route.ts")


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
                 *load("t2", "Skill", skill="demo"))
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


KEYS = r"""
skill = "keys"
[[rule]]
id = "KEY-1"
when = '''\bTOKEN_[A-Z]{8}\b'''
unless = '''EXAMPLE'''
scope = "line"
say = "A key-shaped string."

[[rule]]
id = "LATE-1"
at = ["commit"]
when = '''\blater\(\)'''
say = "Only a commit checks this."
"""


class AtAndScope(Base):
    """`at` picks the levels a rule runs at; `scope = "line"` judges a rule line by line."""

    def setUp(self):
        super().setUp()
        self.skill("keys", KEYS, where="user")
        self.loaded()

    def test_a_commit_only_rule_never_runs_at_edit_time(self):
        self.assertIsNone(self.fire("lib/a.ts", "later()\n"))

    def test_a_line_scoped_allow_covers_only_its_own_line(self):
        allow = "x = 'TOKEN_ABCDEFGH' // practices-allow: KEY-1 a test fixture\n"
        self.assertIsNone(self.fire("lib/a.ts", allow))
        reason = self.fire("lib/b.ts", allow + "y = 'TOKEN_QRSTUVWX'\n")
        self.assertTrue(reason.startswith("[practices:L2:keys:KEY-1:lib/b.ts]"), reason)
        self.assertIsNone(self.fire("lib/c.ts", "z = 'TOKEN_ABCDEFGH' // EXAMPLE\n"))
        self.assertIsNotNone(self.fire("lib/d.ts", "// EXAMPLE\nz = 'TOKEN_ABCDEFGH'\n"))

    def test_a_bad_at_or_scope_disables_only_that_skill(self):
        for n, extra in enumerate(('at = ["push"]', "at = []", 'at = "edit"',
                                   'at = ["edit", "edit"]', 'scope = "word"')):
            with self.subTest(extra=extra):
                self.skill("bad", f'skill = "bad"\n[[rule]]\nid = "B"\nwhen = "x"\nsay = "y"\n'
                           f"{extra}\n", where="user")
                skill, why = PC.load_skill(os.path.join(self.config, "skills", "bad"))
                self.assertIsNone(skill)
                self.assertIn("bad rule 'B'", why)
        self.assertIn("[practices:L2:demo:SEC-17:lib/s.ts]",
                      self.fire("lib/s.ts", "x({ ...body })\n"))


class AfterTheEdit(Base):
    """Events and `unless` read the file as it will be after the edit; `when` reads the new text."""

    ACTION = '"use server"\n\nimport { db } from "@/lib/db"\n\nexport async function f() {\n' \
             '  return 1\n}\n'
    EXPORT = ("import csv\n\n\ndef rows_for(user):\n    rows = load(user)\n"
              "    return [[guard_cell(c) for c in r] for r in rows]\n\n\n"
              "def export(user, f):\n    pass\n")

    def server_code(self):
        shutil.copytree(os.path.join(REPO, "skills", "server-code"),
                        os.path.join(self.proj, ".claude", "skills", "server-code"))
        self.rows(load("t1", "Skill", skill="server-code"))

    def test_an_edit_deep_in_a_use_server_file_fires_l1(self):
        self.existing("lib/actions.ts", self.ACTION)
        reason = self.fire("lib/actions.ts", "  return 2", tool="Edit", old="  return 1")
        self.assertTrue(reason.startswith("[practices:L1:demo:route-handler]"), reason)
        self.assertNotIn("fragment-only", self.log())

    def test_a_guard_elsewhere_in_the_file_keeps_sec_17_quiet(self):
        self.server_code()
        writer = "    w = csv.writer(f)\n    w.writerows(rows_for(user))"
        self.existing("app/export.py", self.EXPORT)
        self.assertIsNone(self.fire("app/export.py", writer, tool="Edit", old="    pass"))
        self.existing("app/plain.py", self.EXPORT.replace("guard_cell(c)", "c"))
        reason = self.fire("app/plain.py", writer, tool="Edit", old="    pass")
        self.assertTrue(reason.startswith("[practices:L2:server-code:SEC-17:app/plain.py]"),
                        reason)

    def test_the_repos_auth_helper_satisfies_the_shipped_sec_01(self):
        # Needs SEC-01's unless in skills/server-code/events.toml to carry {auth_helpers}.
        shutil.rmtree(os.path.join(self.proj, ".claude", "skills", "demo"))
        self.server_code()
        self.config_toml('[auth]\nhelpers = ["getViewer"]\n')
        route = ('export async function GET() {\n  const viewer = await getViewer()\n'
                 '  return Response.json({ ok: true })\n}\n')
        self.assertIsNone(self.fire("app/api/me/route.ts", route))
        reason = self.fire("app/api/you/route.ts", route.replace(
            "  const viewer = await getViewer()\n", ""))
        self.assertTrue(reason.startswith("[practices:L2:server-code:SEC-01:app/api/you/route.ts]"),
                        reason)

    def test_an_empty_or_blank_helper_name_is_dropped_and_sec_01_still_fires(self):
        shutil.rmtree(os.path.join(self.proj, ".claude", "skills", "demo"))
        self.server_code()
        self.config_toml('[auth]\nhelpers = ["", " ", "bad name", "getViewer"]\n')
        route = 'export async function GET() {\n  return Response.json({ ok: true })\n}\n'
        reason = self.fire("app/api/open/route.ts", route)
        self.assertTrue(reason.startswith("[practices:L2:server-code:SEC-01:app/api/open/route.ts]"),
                        reason)
        self.assertIn("auth.helpers dropped ['', ' ', 'bad name']", self.log())
        self.assertIsNone(self.fire("app/api/me/route.ts", route.replace(
            "  return", "  await getViewer()\n  return")))

    def test_helper_names(self):
        for good in ("getViewer", "auth.requireUser", "$session", "_check", "a.b.c"):
            self.assertTrue(PC.HELPER.fullmatch(good), good)
        for bad in ("", " ", "a b", "1st", "a.", ".a", "a..b", "x(", "a|b"):
            self.assertFalse(PC.HELPER.fullmatch(bad), bad)
        self.assertNotIn("|)", PC.expand(r"\b{auth_helpers}\(", ("", " ")))

    def test_when_reads_only_the_new_text(self):
        self.loaded()
        self.existing("lib/save.ts", "x({ ...body })\nconst a = 1\n")
        self.assertIsNone(self.fire("lib/save.ts", "const a = 2", tool="Edit", old="const a = 1"))

    def test_practices_allow_elsewhere_in_the_file_suppresses(self):
        self.loaded()
        self.existing("lib/save.ts", "// practices-allow: SEC-17 parsed by zod\nconst a = 1\n")
        self.assertIsNone(self.fire("lib/save.ts", "x({ ...body })", tool="Edit",
                                    old="const a = 1"))

    def test_a_missing_old_string_falls_back_to_the_new_text(self):
        self.loaded()
        self.existing("lib/save.ts", "// practices-allow: SEC-17 parsed by zod\nconst a = 1\n")
        reason = self.fire("lib/save.ts", "x({ ...body })", tool="Edit", old="const b = 1")
        self.assertIn("[practices:L2:demo:SEC-17:lib/save.ts]", reason)
        self.assertIn("fragment-only", self.log())
        self.assertIn("an old_string isn't in it", self.log())

    @unittest.skipIf(os.geteuid() == 0, "root reads a mode-000 file")
    def test_an_unreadable_file_falls_back_to_the_new_text(self):
        self.loaded()
        path = self.existing("lib/save.ts", "// practices-allow: SEC-17 parsed by zod\n"
                             "const a = 1\n")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        reason = self.fire("lib/save.ts", "x({ ...body })", tool="Edit", old="const a = 1")
        self.assertIn("[practices:L2:demo:SEC-17:lib/save.ts]", reason)
        self.assertIn("unreadable", self.log())
        self.assertIsNone(self.start("startup"))  # an expected fallback, not an engine error

    def test_multiedit_applies_its_edits_in_order(self):
        self.loaded()
        self.existing("lib/save.ts", "// practices-allow: SEC-17 parsed by zod\nA\n")
        # In order, B exists when the second edit runs, so the allow line is in the result;
        # applied out of order it wouldn't be, and the fragment alone would deny.
        edits = [{"old_string": "A", "new_string": "B"},
                 {"old_string": "B", "new_string": "x({ ...body })"}]
        self.assertIsNone(self.fire("lib/save.ts", tool="MultiEdit", edits=edits))
        self.assertNotIn("fragment-only", self.log())
        reason = self.fire("lib/save.ts", tool="MultiEdit", edits=edits[::-1])
        self.assertIn("[practices:L2:demo:SEC-17:lib/save.ts]", reason)

    def test_apply_edits(self):
        self.assertEqual(PC.apply_edits("a a a", [("a", "b", False)]), "b a a")
        self.assertEqual(PC.apply_edits("a a a", [("a", "b", True)]), "b b b")
        self.assertEqual(PC.apply_edits("A\n", [("A", "B", False), ("B", "C", False)]), "C\n")
        self.assertIsNone(PC.apply_edits("A\n", [("B", "C", False), ("A", "B", False)]))
        self.assertEqual(PC.apply_edits("", [("", "new file", False)]), "new file")
        self.assertIsNone(PC.apply_edits("exists", [("", "x", False)]))

    def test_an_edit_creating_a_file_reads_its_new_text(self):
        reason = self.fire("lib/new.ts", "'use server'\n", tool="Edit", old="")
        self.assertIn("[practices:L1:demo:route-handler]", reason)
        self.assertNotIn("fragment-only", self.log())


class L4(Base):
    def digest(self):
        out = self.start("compact")
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "SessionStart")
        self.assertIs(hso["reloadSkills"], True)
        return hso.get("additionalContext")

    def test_names_only_the_skills_loaded_since_the_previous_compaction(self):
        self.skill("other", OTHER, where="user")
        before = [*load("t1", "Skill", skill="other"), text(), *boundary(),
                  *load("t2", "Skill", skill="demo"), text()]
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

    def test_each_loaded_skill_gets_its_share_cut_only_between_lines(self):
        # A long gate no longer crowds out the next skill: the 2,000 characters are shared
        # per skill, and a skill's lines are cut only between lines, never mid-line.
        long_ = [f"Alpha line {n}: " + "a" * 150 for n in range(12)]
        self.skill("alpha", 'skill = "alpha"\ngate = ' + json.dumps(long_) + "\n")
        self.skill("beta", 'skill = "beta"\ngate = ["Beta one.", "Beta two."]\n')
        self.rows([*load("t1", "Skill", skill="alpha"), *load("t2", "Skill", skill="beta"),
                   text()])
        ctx = self.digest()
        self.assertLess(len(ctx), 2000)
        self.assertIn("\n- Beta one.\n- Beta two.", ctx)
        self.assertIn(f"\n- {long_[0]}\n", ctx)
        for line in (x[2:] for x in ctx.split("\n") if x.startswith("- ")):
            with self.subTest(line=line[:20]):
                self.assertTrue(line in long_ or line in ("Beta one.", "Beta two.")
                                or re.fullmatch(r"\(\d+ more in its SKILL\.md\)", line), line)

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
        self.rows(load("s1", "Read", sidechain=True, file_path=os.path.join(
            self.proj, ".claude", "skills", "demo", "SKILL.md")), path=self.agent_file())
        self.assertIsNone(self.fire(agent_id=self.AGENT))

    def test_an_empty_agent_transcript_lets_the_resend_through(self):
        self.rows([], path=self.agent_file())
        open(self.agent_file(), "w").close()
        self.assertIn("[practices:L1:demo:route-handler]", self.fire(agent_id=self.AGENT))
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
        for n, body in enumerate(("enabled = false\n[[disable\n", 'enabled = "no"\n',
                                  '[auth]\nhelpers = "requireMember"\n')):
            with self.subTest(body=body):
                self.config_toml(body)
                self.assertIsNotNone(self.fire(session_id=f"session-{n}"))
        self.assertIn("config-malformed", self.log())


class Failures(Base):
    def test_a_crash_allows_silently_and_is_logged(self):
        self.assertIsNone(self.run_hook(None, stdin="not json {"))
        self.assertIn("crash", self.log())

    def test_a_module_python_cannot_run_is_reported_on_every_call(self):
        d = os.path.join(self.tmp, "hooks")
        os.makedirs(d)
        shutil.copy(HOOK, d)
        with open(os.path.join(d, "practices_check.py"), "w") as f:
            f.write("def broken(:\n")
        p = subprocess.run(["bash", os.path.join(d, "practices-check.sh")], input="{}",
                           capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(p.returncode, 0)
        self.assertIn("practices hooks are down", json.loads(p.stdout)["systemMessage"])

    def test_a_module_planted_in_the_hooks_dir_never_runs(self):
        # Review round 1: bash_words went in by putting the hooks dir first on sys.path, so a
        # shlex.py there ran, outside the sandbox, when bash_words imported shlex.
        hooks = os.path.join(self.tmp, "hooks")
        os.makedirs(hooks)
        for name in ("practices-check.sh", "practices_check.py", "bash_words.py"):
            shutil.copy(os.path.join(REPO, "hooks", name), hooks)
        ran = os.path.join(self.tmp, "ran")
        with open(os.path.join(hooks, "shlex.py"), "w") as f:
            f.write(f"open({ran!r}, 'a').write('planted')\n")
        event = {"session_id": SID, "transcript_path": self.transcript, "cwd": self.proj,
                 "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "t-pl",
                 "tool_input": {"command": "git commit -m x && git push"}}
        p = subprocess.run(["bash", os.path.join(hooks, "practices-check.sh")],
                           input=json.dumps(event), capture_output=True, text=True,
                           env=self.env, timeout=30)
        self.assertIn("separate Bash calls", p.stdout)  # bash_words ran
        self.assertFalse(os.path.exists(ran), "the planted shlex.py ran")

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


def key_shapes():
    """The strings a samples file's {key:<kind>} stands for, each shaped like a real key of that
    kind. They are built here, by concatenation, so no key-shaped literal sits in the repo for a
    secret scanner to flag (and a sample can't leak a real one)."""
    return {
        "aws": "AK" + "IA" + "Z7Q4" * 4,
        "github": "gh" + "p_" + "a1B2c3D4e5" * 3 + "F6g7H8",
        "slack": "xo" + "xb-" + "1234567890" + "-" + "9876543210123" + "-"
                 + "aB3dE6gH9jK2mN5pQ8sT1vW4",
        # OpenAI keys carry a fixed marker between two random runs.
        "openai": "sk" + "-proj-" + "Ab3De6Gh9Jk2Mn5Pq8St1Vw4" + "T3Blbk" + "FJ"
                  + "Ab3De6Gh9Jk2Mn5Pq8St1Vw4",
        "stripe": "sk" + "_live_" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2",
        "pem": "-----" + "BEGIN RSA " + "PRIVATE KEY" + "-----",
    }


def expand_keys(content):
    """content with each {key:<kind>} replaced by key_shapes()[kind]; KeyError names an unknown
    kind."""
    shapes = key_shapes()
    return re.sub(r"\{key:(\w+)\}", lambda m: shapes[m.group(1)], content)


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
        try:
            content = expand_keys(s["content"])
        except KeyError as e:
            wrong.append(f"{s['kind']} {s['id']}: no key shape {e}")
            continue
        fn = PC.event_fires if s["kind"] == "event" else PC.rule_fires
        got = fn(item, s["path"], PC.scan_text(content))
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

    def test_key_placeholders_expand_to_key_shapes(self):
        shapes = {"aws": r"\bAKIA[0-9A-Z]{16}\b", "github": r"\bghp_[A-Za-z0-9]{36}\b",
                  "slack": r"\bxoxb-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24}\b",
                  "openai": r"\bsk-proj-[A-Za-z0-9]{24}T3BlbkFJ[A-Za-z0-9]{24}\b",
                  "stripe": r"\bsk_live_[A-Za-z0-9]{24}\b",
                  "pem": r"-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----"}
        body = "skill = 'keyshape'\n" + "".join(
            f"[[rule]]\nid = 'K-{kind}'\nwhen = '''{rx}'''\nscope = 'line'\nsay = 'x'\n"
            for kind, rx in shapes.items())
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "keyshape")
            os.makedirs(skill)
            with open(os.path.join(skill, "events.toml"), "w") as f:
                f.write(body)
            samples = os.path.join(tmp, "keyshape.toml")
            with open(samples, "w") as f:
                for kind in shapes:
                    f.write(f"[[sample]]\nkind = 'rule'\nid = 'K-{kind}'\nfires = true\n"
                            f"path = 'a.ts'\ncontent = 'k = \"{{key:{kind}}}\"'\n"
                            f"[[sample]]\nkind = 'rule'\nid = 'K-{kind}'\nfires = false\n"
                            f"path = 'a.ts'\ncontent = 'k = \"{{key:{kind}}}\" "
                            f"// practices-allow: K-{kind} fixture'\n")
                f.write("[[sample]]\nkind = 'rule'\nid = 'K-aws'\nfires = true\n"
                        "path = 'a.ts'\ncontent = '{key:nope}'\n")
            self.assertEqual(check_samples(samples, skill),
                             ["rule K-aws: no key shape 'nope'"])
        for kind, value in key_shapes().items():
            self.assertRegex(value, shapes[kind])
        with open(__file__) as f:
            mine = f.read()
        for value in key_shapes().values():
            self.assertNotIn(value, mine)

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

    def test_a_digest_of_every_shipped_skill_keeps_a_full_line_of_each(self):
        # As installed: each skill's SKILL.md path under ~/.claude/skills.
        skills = {}
        for f in sorted(glob.glob(os.path.join(REPO, "skills", "*", "events.toml"))):
            skill, why = PC.load_skill(os.path.dirname(f))
            self.assertIsNone(why)
            skill["dir"] = os.path.join(os.path.expanduser("~"), ".claude", "skills",
                                        os.path.basename(os.path.dirname(f)))
            skills[skill["name"]] = skill
        ctx = PC.digest(sorted(skills), skills)
        self.assertLess(len(ctx), 2000)
        for name, skill in skills.items():
            with self.subTest(skill=name):
                self.assertTrue(any(f"\n- {line}\n" in ctx + "\n" for line in skill["gate"]))

    def test_the_lint(self):
        for bad in ("(a+)+", "(a*)*", "(.*)+", r"(?:\s*,\s*\w+)*", "(ab|ab)*", "("):
            with self.subTest(bad=bad):
                self.assertIsNotNone(PC.lint_regex(bad))
        for good in (r'''^\s*["']use server["']''', r"\b{auth_helpers}\(", "a{1,3}(b+)",
                     r"\.\.\.body\b", r"(?:ab){2}c+"):
            with self.subTest(good=good):
                self.assertIsNone(PC.lint_regex(good))


GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


class GitMixin:
    """Temp repos under $TMPDIR, built with a git that reads no user config."""

    def sh(self, *args, cwd=None, check=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_ENV)
        p = subprocess.run(["git", *args], cwd=cwd or self.repo, env=env, capture_output=True,
                           text=True, timeout=30)
        if check:
            assert p.returncode == 0, p.stderr
        return p.stdout.strip()

    def make_repo(self, path):
        os.makedirs(path, exist_ok=True)
        self.sh("init", "-q", "-b", "main", path, cwd=path)
        return path

    def put(self, rel, content, repo=None):
        path = os.path.join(repo or self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    def commit(self, msg="c", repo=None, **files):
        for rel, content in files.items():
            self.put(rel.replace("__", "/"), content, repo)
        self.sh("add", "-A", cwd=repo or self.repo)
        self.sh("commit", "-q", "--allow-empty", "-m", msg, cwd=repo or self.repo)
        return self.sh("rev-parse", "HEAD", cwd=repo or self.repo)

    def canary(self):
        """A program a hostile config names: it creates the canary file when it runs."""
        self.canary_file = os.path.join(self.tmp, "canary")
        script = os.path.join(self.tmp, "planted.sh")
        with open(script, "w") as f:
            f.write(f"#!/bin/sh\ntouch {self.canary_file}\ncat \"$@\" 2>/dev/null\n")
        os.chmod(script, 0o755)
        return script


class GitHelper(GitMixin, unittest.TestCase):
    """practices_check.Repo reads objects only and runs no program a repo's config names."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="practices-git-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.make_repo(os.path.join(self.tmp, "repo"))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(HOME=os.path.join(self.tmp, "home"),
                        XDG_STATE_HOME=os.path.join(self.tmp, "state"),
                        PRACTICES_TEST_BUDGET="30")
        os.makedirs(self.env["HOME"])

    def read(self, cwd=None, **extra):
        with mock.patch.dict(os.environ, {**self.env, **extra}, clear=True), \
                mock.patch.object(PC, "BUDGET", 30.0), mock.patch.object(PC, "START",
                                                                          PC.time.monotonic()):
            r = PC.Repo(cwd or self.repo)
            head = r.rev("HEAD")
            changes = r.changes(None, head)
            blobs, _ = r.blobs([c[4] for c in changes], 1 << 20, 1 << 22)
            return r, changes, blobs

    def test_refuses_what_could_run_a_program(self):
        self.commit(a="x\n")
        # START too: it is the import time, minutes back by now in a full-suite run.
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(PC, "BUDGET", 30.0), mock.patch.object(PC, "START",
                                                                          PC.time.monotonic()):
            r = PC.Repo(self.repo)
            for sub, args in (("status", ()), ("diff", ()), ("diff-tree", ("-p", "HEAD")),
                              ("diff-tree", ("-r", "HEAD")), ("cat-file", ("--filters",)),
                              ("cat-file", ("--textconv",)), ("ls-files", ())):
                with self.subTest(sub=sub, args=args):
                    with self.assertRaises(PC.GitError):
                        r.run(sub, *args)

    def test_a_hostile_config_runs_nothing(self):
        script = self.canary()
        self.sh("config", "core.fsmonitor", script)
        self.sh("config", "diff.external", script)
        self.sh("config", "diff.planted.textconv", script)
        self.sh("config", "filter.planted.smudge", script)
        self.sh("config", "filter.planted.clean", "cat")
        self.sh("config", "core.pager", script)
        self.put(".gitattributes", "*.ts diff=planted filter=planted\n")
        self.commit(**{"lib__a.ts": "x({ ...body })\n"})
        if os.path.exists(self.canary_file):
            os.unlink(self.canary_file)  # the setup's own git add ran the planted filter
        _, changes, blobs = self.read()
        self.assertIn("lib/a.ts", [c[5] for c in changes])
        self.assertIn(b"x({ ...body })\n", blobs.values())
        self.assertFalse(os.path.exists(self.canary_file), "a planted program ran")

    def test_a_tracked_symlink_is_its_target_path_never_the_file(self):
        outside = os.path.join(self.tmp, "outside.ts")
        with open(outside, "w") as f:
            f.write("x({ ...body })\n")
        os.symlink(outside, os.path.join(self.repo, "link.ts"))
        self.commit()
        _, changes, blobs = self.read()
        (c,) = [c for c in changes if c[5] == "link.ts"]
        self.assertEqual(c[2], "120000")
        self.assertEqual(blobs[c[4]], outside.encode())

    def test_a_worktree_reads_through_its_gitfile(self):
        script = self.canary()
        self.commit(a="1\n")
        self.sh("config", "core.fsmonitor", script)
        wt = os.path.join(self.tmp, "wt")
        self.sh("worktree", "add", "-q", "-b", "side", wt)
        self.commit(repo=wt, b="2\n")
        if os.path.exists(self.canary_file):
            os.unlink(self.canary_file)  # the setup's own git commit ran fsmonitor
        r, changes, _ = self.read(cwd=wt)
        self.assertEqual([c[5] for c in changes], ["b"])
        self.assertEqual(os.path.realpath(r.top), os.path.realpath(wt))
        self.assertFalse(os.path.exists(self.canary_file))

    def test_a_partial_clones_missing_blob_runs_no_transport(self):
        # A lazy fetch of a missing blob would run the remote's transport, and ext:: runs a
        # command. GIT_ALLOW_PROTOCOL=none refuses it; git then gives up on the blob (2.43
        # exits 128), and the level is skipped and logged, never the transport run.
        self.commit(**{"a.ts": "x({ ...body })\n"})
        self.sh("config", "uploadpack.allowFilter", "true")
        self.sh("config", "uploadpack.allowAnySHA1InWant", "true")
        clone = os.path.join(self.tmp, "partial")
        self.sh("-c", "protocol.file.allow=always", "clone", "-q", "--no-checkout",
                "--filter=blob:none", f"file://{self.repo}", clone, cwd=self.tmp)
        fetched = os.path.join(self.tmp, "fetched")
        self.sh("config", "remote.origin.url", f"ext::sh -c touch% {fetched}", cwd=clone)
        self.sh("config", "protocol.ext.allow", "always", cwd=clone)
        blob = self.sh("rev-parse", "HEAD:a.ts", cwd=clone)
        self.sh("cat-file", "-p", blob, cwd=clone, check=False)  # the trap is live
        self.assertTrue(os.path.exists(fetched), "a plain read never ran the transport")
        os.unlink(fetched)
        try:
            _, changes, blobs = self.read(cwd=clone)
            self.assertEqual(([c[5] for c in changes], blobs), (["a.ts"], {}))
        except PC.GitError:
            pass
        self.assertFalse(os.path.exists(fetched), "the engine's read ran the transport")

    def test_git_dir_in_the_hooks_own_env_is_ignored(self):
        self.commit(mine="1\n")
        other = self.make_repo(os.path.join(self.tmp, "other"))
        self.commit(repo=other, theirs="1\n")
        _, changes, _ = self.read(GIT_DIR=os.path.join(other, ".git"),
                                  GIT_WORK_TREE=other)
        self.assertEqual([c[5] for c in changes], ["mine"])

    def test_a_safe_directory_mismatch_is_refused_unless_the_user_listed_it(self):
        self.commit(a="1\n")
        script = self.canary()
        self.sh("config", "core.fsmonitor", script)
        with self.assertRaises(PC.GitError) as e:
            self.read(PRACTICES_TEST_DIFFERENT_OWNER="1")
        self.assertIn("ownership", str(e.exception))
        with open(os.path.join(self.env["HOME"], ".gitconfig"), "w") as f:
            f.write(f"[user]\n\tname = x\n[safe]\n\tdirectory = {self.repo}\n")
        _, changes, _ = self.read(PRACTICES_TEST_DIFFERENT_OWNER="1")
        self.assertEqual([c[5] for c in changes], ["a"])
        self.assertFalse(os.path.exists(self.canary_file))

    def test_a_spent_budget_stops_before_git_runs(self):
        self.commit(a="1\n")
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(PC, "BUDGET", 0.0):
            with self.assertRaises(PC.Budget):
                PC.Repo(self.repo)


class BashBase(GitMixin, Base):
    """The project is a git repo; a Bash call runs as Claude Code runs it: PreToolUse, the
    command (done here by the test), then PostToolUse with the same tool_use_id."""

    def setUp(self):
        super().setUp()
        self.repo = self.make_repo(self.proj)
        with open(os.path.join(self.proj, ".git", "info", "exclude"), "a") as f:
            f.write(".claude/\n")
        self.ids = iter(range(1, 1 << 30))

    def event(self, command, phase, tid, **extra):
        return {"session_id": SID, "transcript_path": self.transcript, "cwd": self.proj,
                "hook_event_name": phase, "tool_name": "Bash",
                "tool_input": {"command": command}, "tool_use_id": tid, **extra}

    def pre(self, command, tid="b-now", **extra):
        out = self.run_hook(self.event(command, "PreToolUse", tid, **extra))
        if out is None:
            return None
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        return hso["permissionDecisionReason"]

    def post(self, command, tid="b-now", **extra):
        out = self.run_hook(self.event(command, "PostToolUse", tid, **extra))
        if out is None:
            return None
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        return out["hookSpecificOutput"]["additionalContext"]

    def committed(self, repo=None, command="git commit -m x", pre=True, **files):
        """Run a commit as a Bash call: PreToolUse, the commit, PostToolUse; the tell or None."""
        tid = f"b{next(self.ids)}"
        if pre:
            self.assertIsNone(self.pre(command, tid))
        self.commit(repo=repo, **files)
        return self.post(command, tid)


class L3s(BashBase):
    def test_a_commit_that_adds_a_flagged_line_is_told_once_without_the_text(self):
        told = self.committed(**{"lib__a.ts": "const a = 1\nx({ ...body })\n"})
        self.assertTrue(told.startswith("[practices:L3s]"), told)
        self.assertIn("SEC-17 (demo) at lib/a.ts:2", told)
        self.assertIn("Spreading the request body", told)
        self.assertIn("amend", told)
        self.assertNotIn("...body", told)
        self.assertNotIn("...body", self.log())
        self.assertIsNone(self.committed(**{"lib__b.txt": "unrelated\n"}))
        self.assertIsNone(self.committed(**{"lib__a.ts": "const a = 2\nx({ ...body })\n"}))

    def test_a_new_key_after_a_partial_fix_retells_only_the_new_finding(self):
        told = self.committed(**{"a.ts": "x({ ...body })\n", "b.ts": "y({ ...body })\n"})
        self.assertIn("a.ts:1", told)
        self.assertIn("b.ts:1", told)
        told = self.committed(**{"a.ts": "x(pick(body))\n", "b.ts": "y({ ...body, z })\n"})
        self.assertIn("b.ts:1", told)
        self.assertNotIn("a.ts", told)

    def test_a_finding_accepted_at_l2_is_skipped(self):
        self.loaded()
        self.assertIsNotNone(self.fire("lib/save.ts", "x({ ...body })\n"))
        self.assertIsNone(self.committed(**{"lib__save.ts": "x({ ...body })\n"}))
        self.assertIn("lib/other.ts:1", self.committed(**{"lib__other.ts": "x({ ...body })\n"}))

    def test_an_l2_deny_accepts_only_the_lines_it_named(self):
        # Review round 1: the L2 key had no line in it, so one deny exempted every later
        # finding of that rule in that file.
        self.loaded()
        self.assertIsNotNone(self.fire("lib/save.ts", "x({ ...body })\n"))
        told = self.committed(**{"lib__save.ts": "x({ ...body })\ny({ ...body, z })\n"})
        self.assertIn("lib/save.ts:2", told)
        self.assertNotIn("lib/save.ts:1", told)
        self.skill("keys", KEYS, where="user")
        self.assertIsNotNone(self.fire("k.ts", "a = 'TOKEN_ABCDEFGH'\n"))
        told = self.committed(**{"k.ts": "a = 'TOKEN_ABCDEFGH'\nb = 'TOKEN_QRSTUVWX'\n"})
        self.assertIn("KEY-1 (keys) at k.ts:2", told)
        self.assertNotIn("k.ts:1", told)

    def test_a_line_scoped_allow_covers_only_its_line_and_at_picks_the_levels(self):
        self.skill("keys", KEYS, where="user")
        told = self.committed(**{"k.ts": "a = 'TOKEN_ABCDEFGH' // practices-allow: KEY-1 test\n"
                                          "b = 'TOKEN_QRSTUVWX'\nlater()\n"})
        self.assertIn("KEY-1 (keys) at k.ts:2:", told)
        self.assertNotIn("k.ts:1", told)
        self.assertIn("LATE-1 (keys) at k.ts:3", told)

    def test_a_root_commit_is_scanned_and_without_a_record_nothing_is(self):
        self.assertIn("root.ts:1", self.committed(**{"root.ts": "x({ ...body })\n"}))
        before = self.log()
        self.assertIsNone(self.committed(pre=False, **{"new.ts": "y({ ...body })\n"}))
        self.assertIn("no repo was recorded", self.log()[len(before):])

    def test_a_heads_record_without_worktrees_still_reads(self):
        head = self.commit(**{"a.ts": "1\n"})
        with mock.patch.dict(os.environ, self.env, clear=True):
            path = PC._heads_file(self.event("git commit -m x", "PostToolUse", "b-old"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"heads": {os.path.join(self.proj, ".git"): head}}, f)
        self.commit(**{"b.ts": "x({ ...body })\n"})
        self.assertIn("b.ts:1", self.post("git commit -m x", "b-old"))

    def test_post_scans_the_repo_pre_recorded_not_a_reparse_from_its_cwd(self):
        # Review round 1: `cd sub && git commit` moves the session's cwd into sub, and a
        # re-parse from there looked for sub/sub, so the commit went unchecked.
        sub = self.make_repo(os.path.join(self.proj, "sub"))
        with open(os.path.join(self.proj, ".git", "info", "exclude"), "a") as f:
            f.write("sub/\n")
        command = "cd sub && git commit -m x"
        self.assertIsNone(self.pre(command, "b-cd"))
        self.commit(repo=sub, **{"s.ts": "x({ ...body })\n"})
        told = self.run_hook({**self.event(command, "PostToolUse", "b-cd"), "cwd": sub})
        self.assertIn("s.ts:1", told["hookSpecificOutput"]["additionalContext"])

    def test_merges_and_pure_renames_are_skipped(self):
        self.commit(**{"a.ts": "x({ ...body })\n"})
        self.sh("mv", "a.ts", "moved.ts")
        self.assertIsNone(self.committed())
        head = self.sh("rev-parse", "HEAD")
        side = self.sh("commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "side")
        self.put("m.ts", "y({ ...body })\n")
        self.sh("add", "-A")
        tree = self.sh("write-tree")
        merge = self.sh("commit-tree", tree, "-p", head, "-p", side, "-m", "merge")
        self.assertIsNone(self.pre("git commit -m m", "b-merge"))
        self.sh("update-ref", "refs/heads/main", merge)
        self.assertIsNone(self.post("git commit -m m", "b-merge"))

    def test_sec_60_a_lockfile_change_with_no_audit(self):
        told = self.committed(**{"package-lock.json": "{}\n", "requirements-dev.txt": "x==1\n"})
        self.assertIn("SEC-60 (the practices engine) at package-lock.json, requirements-dev.txt",
                      told)
        self.add(use("t-audit", "Bash", command="cd web && npm audit --omit dev"))
        self.assertIsNone(self.committed(**{"package-lock.json": "{\"a\": 1}\n"}))

    def test_the_command_names_the_repo(self):
        sub = self.make_repo(os.path.join(self.proj, "sub"))  # a repo inside the project
        with open(os.path.join(self.proj, ".git", "info", "exclude"), "a") as f:
            f.write("sub/\n")
        self.commit(**{"seed.ts": "x({ ...body })\n"})
        told = self.committed(repo=sub, command=f"git -C {sub} commit -m x",
                              **{"s.ts": "x({ ...body })\n"})
        self.assertIn("s.ts:1", told)
        self.assertIsNone(self.committed(repo=sub, command='git -C "$SUB" commit -m x',
                                         **{"t.ts": "x({ ...body })\n"}))
        self.assertIn("git-skipped", self.log())
        told = self.committed(repo=sub, command=f"GIT_DIR={sub}/.git git commit -m x",
                              **{"u.ts": "x({ ...body })\n"})
        self.assertIn("u.ts:1", told)
        told = self.committed(repo=sub, command="cd sub && git commit -m 'git push later'",
                              **{"v.ts": "x({ ...body })\n"})
        self.assertIn("v.ts:1", told)

    def test_a_hostile_repo_runs_nothing_at_commit_time(self):
        script = self.canary()
        for key in ("core.fsmonitor", "diff.external", "diff.planted.textconv", "core.pager"):
            self.sh("config", key, script)
        self.put(".gitattributes", "*.ts diff=planted\n")
        outside = os.path.join(self.tmp, "outside.ts")
        with open(outside, "w") as f:
            f.write("x({ ...body })\n")
        os.symlink(outside, os.path.join(self.proj, "link.ts"))
        tid = "b-hostile"
        self.assertIsNone(self.pre("git commit -m x", tid))
        self.commit(**{"a.ts": "x({ ...body })\n"})
        if os.path.exists(self.canary_file):
            os.unlink(self.canary_file)  # the test's own git commit ran fsmonitor
        self.env["GIT_DIR"] = os.path.join(self.tmp, "nowhere")
        told = self.post("git commit -m x", tid)
        self.assertIn("a.ts:1", told)
        self.assertNotIn("link.ts", told)
        self.assertFalse(os.path.exists(self.canary_file), "a planted program ran")

    def test_a_subagent_keeps_its_own_keys_and_counts_the_parents_audit(self):
        agent = "a0123456789abcdef"
        d = os.path.join(self.transcript[:-len(".jsonl")], "subagents")
        os.makedirs(d)
        self.rows([], path=os.path.join(d, f"agent-{agent}.jsonl"))
        self.assertIn("a.ts:1", self.committed(**{"a.ts": "x({ ...body })\n"}))
        tid = "b-agent"
        self.assertIsNone(self.pre("git commit -m x", tid, agent_id=agent))
        self.commit(**{"a.ts": "x({ ...body })\n// more\n", "go.sum": "x\n"})
        told = self.post("git commit -m x", tid, agent_id=agent)
        self.assertIn("SEC-60", told)
        self.add(use("t-audit", "Bash", command="govulncheck ./..."))
        tid = "b-agent-2"
        self.assertIsNone(self.pre("git commit -m x", tid, agent_id=agent))
        self.commit(**{"go.sum": "y\n"})
        self.assertIsNone(self.post("git commit -m x", tid, agent_id=agent))


class OutsideTheProject(BashBase):
    """Review round 1: the Bash levels read any repo a command named and printed its paths,
    lines and rule hits. A repo is read only when its git dir, common dir and alternates sit
    under the project dir or the project's own repo (a lane's main checkout)."""

    def setUp(self):
        super().setUp()
        self.vault = self.make_repo(os.path.join(self.tmp, "vault"))
        self.secret = self.commit(repo=self.vault, **{"secret.ts": "x({ ...body })\n"})

    def assert_skipped(self, before=""):
        log = self.log()[len(before):]
        self.assertIn("outside the project", log)
        self.assertNotIn(self.vault, log)
        self.assertNotIn("secret", log)

    def test_a_repo_the_command_names_outside_the_project_is_never_read(self):
        v = self.vault
        for n, command in enumerate((f"git -C {v} commit -m x",
                                     f"git --git-dir={v}/.git --work-tree={v} commit -m x",
                                     f"GIT_DIR={v}/.git git commit -m x",
                                     f"cd {v} && git commit -m x")):
            with self.subTest(command=command):
                before = self.log()
                self.assertIsNone(self.committed(repo=v, command=command,
                                                 **{f"s{n}.ts": "x({ ...body })\n"}))
                self.assert_skipped(before)
        self.assertIsNone(self.pre(f"git -C {v} push", session_id="s-push"))
        self.sh("update-ref", "refs/remotes/origin/main", self.secret, cwd=v)
        self.commit(repo=v, **{"w.ts": "y({ ...body })\n"})
        self.assertIsNone(self.pre(f"cd {v} && gh pr ready", session_id="s-pr"))
        self.assert_skipped()

    def test_a_planted_gitfile_or_alternates_entry_is_never_read(self):
        planted = os.path.join(self.proj, "sub")
        os.makedirs(planted)
        with open(os.path.join(planted, ".git"), "w") as f:
            f.write(f"gitdir: {self.vault}/.git\n")
        before = self.log()
        self.assertIsNone(self.pre("cd sub && git push", session_id="s-gitfile"))
        self.assert_skipped(before)
        self.commit(**{"mine.ts": "y({ ...body })\n"})
        alt = os.path.join(self.proj, ".git", "objects", "info", "alternates")
        with open(alt, "w") as f:
            f.write(f"{self.vault}/.git/objects\n")
        before = self.log()
        self.assertIsNone(self.pre("git push", session_id="s-alt"))
        self.assertIn("alternates entry is outside", self.log()[len(before):])
        os.unlink(alt)
        self.assertIn("mine.ts:1", self.pre("git push", session_id="s-alt"))

    def test_a_lane_reads_its_main_checkouts_git_dir(self):
        self.skill("demo", DEMO, where="user")
        main = self.make_repo(os.path.join(self.tmp, "main"))
        self.commit(repo=main, seed="1\n")
        lane = os.path.join(self.tmp, "lane")
        self.sh("worktree", "add", "-q", "-b", "lane", lane, cwd=main)
        self.env["CLAUDE_PROJECT_DIR"] = lane
        tid = "b-lane"
        self.assertIsNone(self.run_hook({**self.event("git commit -m x", "PreToolUse", tid),
                                         "cwd": lane}))
        self.commit(repo=lane, **{"l.ts": "x({ ...body })\n"})
        out = self.run_hook({**self.event("git commit -m x", "PostToolUse", tid), "cwd": lane})
        self.assertIn("l.ts:1", out["hookSpecificOutput"]["additionalContext"])
        # Its main checkout is the project's own repo too; another repo under it is not.
        self.commit(repo=main, **{"m.ts": "x({ ...body })\n"})
        out = self.run_hook({**self.event(f"cd {main} && git push", "PreToolUse", "b-main"),
                             "cwd": lane})
        self.assertIn("m.ts:1", out["hookSpecificOutput"]["permissionDecisionReason"])
        nested = self.make_repo(os.path.join(main, "nested"))
        self.commit(repo=nested, **{"n.ts": "x({ ...body })\n"})
        self.assertIsNone(self.run_hook({**self.event(f"git -C {nested} push", "PreToolUse",
                                                      "b-nested"), "cwd": lane}))

    def test_a_gitfile_planted_at_the_projects_top_claims_no_other_repo(self):
        self.skill("demo", DEMO, where="user")
        fake = os.path.join(self.tmp, "fake")
        os.makedirs(fake)
        with open(os.path.join(fake, ".git"), "w") as f:
            f.write(f"gitdir: {self.vault}/.git\n")
        self.env["CLAUDE_PROJECT_DIR"] = fake
        before = self.log()
        self.assertIsNone(self.run_hook({**self.event("git push", "PreToolUse", "b-fake"),
                                         "cwd": fake}))
        self.assert_skipped(before)

    def test_without_claude_project_dir_the_session_start_cwd_bounds_the_reads(self):
        self.skill("demo", DEMO, where="user")
        del self.env["CLAUDE_PROJECT_DIR"]
        self.commit(**{"mine.ts": "y({ ...body })\n"})
        self.commit(repo=self.vault, **{"v.ts": "y({ ...body })\n"})
        before = self.log()
        self.assertIsNone(self.pre("git push"))  # no session start recorded: nothing is read
        self.assertIn("no project dir", self.log()[len(before):])
        self.start("startup")  # cwd: the project
        self.start("compact", cwd=self.vault)  # a later start keeps the first cwd
        self.assertIsNone(self.run_hook({**self.event("git push", "PreToolUse", "b-v"),
                                         "cwd": self.vault}))
        self.assertIn("mine.ts:1", self.pre("git push"))


class Push(BashBase):
    """The push gate scans what a push would send (the remotes' refs set by update-ref: no
    test ever pushes)."""

    def setUp(self):
        super().setUp()
        self.pushed = self.commit(**{"old.ts": "x({ ...body })\n"})
        self.sh("update-ref", "refs/remotes/origin/main", self.pushed)

    def test_denies_once_per_new_finding_and_the_resend_passes(self):
        self.commit(**{"new.ts": "y({ ...body })\n"})
        reason = self.pre("git push origin main")
        self.assertTrue(reason.startswith("[practices:push]"), reason)
        self.assertIn("SEC-17 (demo) at new.ts:1", reason)
        self.assertNotIn("old.ts", reason)
        self.assertNotIn("...body", reason)
        self.assertIsNone(self.pre("git push origin main"))
        self.commit(**{"newer.ts": "z({ ...body })\n"})
        reason = self.pre("git push")
        self.assertIn("newer.ts:1", reason)
        self.assertNotIn("new.ts:1,", reason)

    def test_a_push_with_a_redirection_is_scanned(self):
        self.commit(**{"new.ts": "y({ ...body })\n"})
        for n, command in enumerate(("git push 2>&1", "git push origin 2>&1 | tail",
                                     "git push -q 2>/dev/null")):
            with self.subTest(command=command):
                self.assertIn("new.ts:1", self.pre(command, session_id=f"redir-{n}"))
        self.assertIn("a.ts:1", self.committed(command="git commit -m x >/dev/null",
                                               **{"a.ts": "x({ ...body })\n"}))

    def test_a_push_inside_a_command_substitution_is_scanned(self):
        # Review round 2, medium 1: `out=$(git push ...)` ran with no scan and no log.
        self.commit(**{"new.ts": "y({ ...body })\n"})
        for n, command in enumerate(('out=$(git push origin main 2>&1); echo "$out"',
                                     "echo `git push`", "cat <(git push)")):
            with self.subTest(command=command):
                self.assertIn("new.ts:1", self.pre(command, session_id=f"subst-{n}"))

    def test_a_launcher_this_parser_cannot_read_is_logged(self):
        # Review round 2, low 2: xargs, find -exec, submodule foreach and bash -c passed with
        # no log. Words that name a call no parser read are the backstop.
        unread = ("printf x | xargs git push", "find . -name x -exec git commit -m y {} +",
                  "git submodule foreach git push", 'bash -c "git push $R"',
                  "sh <<'EOF'\ngit push\nEOF", "nohup xargs -n1 gh pr ready < prs")
        for command in unread:
            with self.subTest(command=command):
                before = self.log()
                self.assertIsNone(self.pre(command))
                new = self.log()[len(before):]
                self.assertIn("git-skipped the command names git commit or push", new)
                for text_ in ("git push", "-m y", "foreach", "-n1", "$R"):  # no command text
                    self.assertNotIn(text_, new)
        for command in ("git log --grep push", "echo ok # git push", "gh pr view 5",
                        "gh pr create --draft", "git status"):
            with self.subTest(command=command):
                before = self.log()
                self.assertIsNone(self.pre(command))
                self.assertNotIn("git-skipped", self.log()[len(before):])

    def test_an_unwritable_state_file_allows_the_call_and_logs(self):
        # Review round 1: the Bash levels have no transcript marker to fall back on, so a deny
        # whose key couldn't be written denied every resend too, forever.
        self.commit(**{"new.ts": "y({ ...body })\n"})
        d = os.path.join(self.state, "dotclaude", "practices")
        os.makedirs(d)
        open(os.path.join(d, "denies"), "w").close()  # the state dir can't be made
        for command in ("git push", "git commit -m x && git push", "gh pr create --title x"):
            with self.subTest(command=command):
                self.assertIsNone(self.pre(command))
        self.assertIn("state-error", self.log())

    def test_a_clean_push_deletes_and_dry_runs_pass(self):
        self.commit(**{"clean.ts": "const a = 1\n"})
        self.assertIsNone(self.pre("git push"))
        self.commit(**{"bad.ts": "y({ ...body })\n"})
        for command in ("git push origin --delete old", "git push origin :old",
                        "git push --dry-run", "git push -n origin main",
                        "git push origin '$(echo main)'"):
            with self.subTest(command=command):
                self.assertIsNone(self.pre(command))

    def test_named_sources_and_every_branch(self):
        tip = self.commit(**{"main.ts": "y({ ...body })\n"})
        self.sh("update-ref", "refs/remotes/origin/main", tip)
        feat = self.commit(**{"f.ts": "z({ ...body })\n"})
        self.sh("update-ref", "refs/heads/feature", feat)
        self.sh("update-ref", "refs/heads/main", tip)  # HEAD (main) is pushed; feature isn't
        self.assertIsNone(self.pre("git push"))
        reason = self.pre("git push origin +feature:feature")
        self.assertIn("f.ts:1", reason)
        self.assertNotIn("main.ts", reason)
        self.assertIn("f.ts:1", self.pre("git push --all origin", session_id="s2"))

    def test_a_call_that_commits_and_pushes_is_denied_once(self):
        command = "git add -A && git commit -m x && git push"
        reason = self.pre(command)
        self.assertIn("separate Bash calls", reason)
        self.assertIsNone(self.pre(command))
        self.assertIsNone(self.pre('git commit -m "then git push"'))


class L3r(BashBase):
    """gh pr ready, and gh pr create without --draft, wait for a briefed reviewer."""

    def setUp(self):
        super().setUp()
        self.base = self.commit(**{"README": "x\n"})
        self.sh("update-ref", "refs/remotes/origin/main", self.base)
        self.commit(**{"app__api__x__route.ts": "export const x = 1\n", "lib__u.ts": "1\n"})

    def marker(self, rev="HEAD"):
        return f"[practices:review:{self.sh('rev-parse', rev)[:12]}]"

    def test_denies_once_with_the_block_to_paste_and_the_resend_passes(self):
        reason = self.pre("gh pr create --title x --body y")
        self.assertTrue(reason.startswith("[practices:L3r]"), reason)
        self.assertIn(self.marker() + " Review the changes of main", reason)
        self.assertIn("demo (" + os.path.join(self.proj, ".claude", "skills", "demo", "SKILL.md")
                      + "), for app/api/x/route.ts:", reason)
        self.assertNotIn("lib/u.ts", reason)
        self.assertIn("- An id from the request body is never trusted.", reason)
        self.assertIn("resend", reason)
        self.assertIsNone(self.pre("gh pr create --title x --body y"))

    def test_a_pr_created_inside_a_command_substitution_is_judged(self):
        # Review round 2, medium 1: capturing the PR URL this way skipped L3r with no log.
        reason = self.pre("PR=$(gh pr create --title t --body b) && echo $PR")
        self.assertIn(self.marker() + " Review the changes of main", reason)

    def test_drafts_undo_and_other_gh_calls_pass(self):
        for command in ("gh pr create --draft --title x", "gh pr create -d", "gh pr ready --undo",
                        "gh pr view 5", "gh issue create", "echo 'gh pr ready'"):
            with self.subTest(command=command):
                self.assertIsNone(self.pre(command))

    def test_a_marked_reviewer_brief_satisfies_it(self):
        self.add(use("t-rev", "Agent", subagent_type="reviewer",
                     prompt=f"Review this.\n{self.marker()} demo ..."))
        self.assertIsNone(self.pre("gh pr ready 12"))

    def test_an_unmarked_agent_or_a_quoted_marker_does_not(self):
        self.add(use("t-rev", "Agent", prompt="Review this."),
                 text(f"{self.marker()} in prose"),
                 use("t-b", "Bash", command=f"echo '{self.marker()}'"))
        self.assertIsNotNone(self.pre("gh pr ready"))

    def test_a_review_clears_only_the_commit_it_judged(self):
        # Review round 1: one marked reviewer satisfied L3r for the rest of the session, for
        # any PR. The marker names the head it judged.
        self.add(use("t-rev", "Agent", prompt=f"{self.marker()} demo ..."))
        self.assertIsNone(self.pre("gh pr ready"))
        self.commit(**{"app__api__y__route.ts": "export const y = 1\n"})
        self.assertIn(self.marker(), self.pre("gh pr ready", session_id="s-next"))
        self.add(use("t-old", "Agent", prompt="[practices:review] the old, bare marker"))
        self.assertIsNotNone(self.pre("gh pr ready", session_id="s-bare"))

    def test_a_named_branch_is_judged_and_a_pr_number_says_what_was(self):
        # Review round 1: L3r judged local HEAD whatever PR the call named.
        self.sh("branch", "clean", self.base)  # a branch with nothing a skill owns
        self.assertIsNone(self.pre("gh pr ready clean", session_id="s-clean"))
        self.assertIsNone(self.pre("gh pr create --head clean --title t", session_id="s-c2"))
        self.assertIsNone(self.pre("gh pr create -H me:clean --title t", session_id="s-c3"))
        self.sh("branch", "feat", self.base)
        self.sh("update-ref", "refs/remotes/origin/feat", self.sh("rev-parse", "HEAD"))
        reason = self.pre("gh pr ready feat", session_id="s-feat")  # origin/feat wins
        self.assertIn("Review the changes of feat", reason)
        before = self.log()
        self.assertIsNone(self.pre("gh pr ready nowhere", session_id="s-none"))
        self.assertIn("neither an origin/<branch> nor a local branch", self.log()[len(before):])
        head = self.sh("rev-parse", "HEAD")[:12]
        for n, command in enumerate(("gh pr ready 142", "gh pr ready https://x.test/o/r/pull/9")):
            with self.subTest(command=command):
                reason = self.pre(command, session_id=f"s-num-{n}")
                self.assertIn(f"judged against main at {head}; run this from the PR's checkout",
                              reason)
        self.assertIn("l3r-target", self.log())
        health = self.start("startup")["systemMessage"]  # the target log is no engine error
        self.assertIn("1 git call skipped", health)  # the unknown branch
        self.assertNotIn("l3r", health)

    def test_a_subagent_counts_the_parents_reviewer(self):
        agent = "a0123456789abcdef"
        d = os.path.join(self.transcript[:-len(".jsonl")], "subagents")
        os.makedirs(d)
        self.rows([], path=os.path.join(d, f"agent-{agent}.jsonl"))
        self.assertIsNotNone(self.pre("gh pr ready", agent_id=agent))
        self.add(use("t-rev", "Task", prompt=f"{self.marker()} go"))
        self.assertIsNone(self.pre("gh pr ready", agent_id=agent, session_id="s3"))

    def test_the_base_comes_from_the_flag_then_origin_head_main_master(self):
        self.sh("update-ref", "-d", "refs/remotes/origin/main")
        self.assertIsNone(self.pre("gh pr ready"))
        self.assertIn("no base branch", self.log())
        self.sh("update-ref", "refs/remotes/origin/master", self.base)
        self.assertIsNotNone(self.pre("gh pr ready", session_id="s1"))
        self.sh("update-ref", "refs/remotes/origin/dev", self.sh("rev-parse", "HEAD"))
        self.assertIsNone(self.pre("gh pr create --base dev", session_id="s2"))
        self.assertIsNotNone(self.pre("gh pr create -B master", session_id="s2"))
        self.sh("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/dev")
        self.assertIsNone(self.pre("gh pr ready", session_id="s4"))

    def test_line_scoped_rules_run_over_every_commit_in_the_range(self):
        self.skill("keys", KEYS, where="user")
        self.commit(**{"k.ts": "a = 'TOKEN_ABCDEFGH'\n"})
        self.commit(**{"k.ts": "a = process.env.A\n"})  # gone at HEAD, still in the history
        self.add(use("t-rev", "Agent", prompt=self.marker()))
        reason = self.pre("gh pr ready")
        self.assertIn("KEY-1 (keys) at k.ts:1", reason)
        self.assertNotIn("TOKEN_", reason)
        self.assertIsNone(self.pre("gh pr ready"))


class Budgets(BashBase):
    """A spent budget, a git timeout and a crash allow the call, and leave their trace."""

    def call(self, fn, command, tid, **patches):
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(PC, "BUDGET", 1e9):
            with contextlib.ExitStack() as stack:
                for name, value in patches.items():
                    stack.enter_context(mock.patch.object(PC, name, value))
                try:
                    phase = "PreToolUse" if fn is PC.pre_tool_use else "PostToolUse"
                    return fn(self.event(command, phase, tid))
                finally:
                    PC.CRUMB.clear()

    def test_a_spent_budget_allows_and_logs(self):
        self.env["PRACTICES_TEST_BUDGET"] = "0"
        self.assertIsNone(self.committed(**{"a.ts": "x({ ...body })\n"}))
        self.assertIn("budget-spent", self.log())

    def test_a_git_timeout_leaves_a_breadcrumb_naming_the_level_and_allows(self):
        self.commit(**{"a.ts": "1\n"})
        seen = {}
        real = subprocess.run

        def slow(*args, **kw):
            d = os.path.join(self.state, "dotclaude", "practices")
            for n in os.listdir(d) if os.path.isdir(d) else ():
                if n.startswith("breadcrumb-"):
                    with open(os.path.join(d, n)) as f:
                        seen.update(json.load(f))
            if args and args[0][0] in PC.SYSTEM_GITS and "--batch" in args[0]:
                raise subprocess.TimeoutExpired(args[0], 1)
            return real(*args, **kw)

        self.assertIsNone(self.call(PC.pre_tool_use, "git commit -m x", "b-slow"))
        self.commit(**{"b.ts": "x({ ...body })\n"})
        with mock.patch("subprocess.run", slow):
            self.assertIsNone(self.call(PC.post_tool_use, "git commit -m x", "b-slow"))
        self.assertEqual(seen.get("level"), "L3s")
        self.assertIn("budget-spent", self.log())

    def test_a_crash_allows_and_logs(self):
        def boom(event):
            raise RuntimeError("planted")

        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(PC, "post_tool_use", boom), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(
                    self.event("git commit -m x", "PostToolUse", "b-crash")))), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            PC.run()
        self.assertEqual(out.getvalue(), "")
        self.assertIn("crash RuntimeError: planted", self.log())

    def test_a_file_whose_old_blob_was_cut_is_skipped_and_logged(self):
        # Review round 1: an old blob over the caps read as empty, so every line of the new
        # one counted as added, old flagged lines too.
        self.commit(**{"a.ts": "x({ ...body })\n" + "// filler\n" * 20})
        self.assertIsNone(self.call(PC.pre_tool_use, "git commit -m x", "b-cut"))
        self.commit(**{"a.ts": "x({ ...body })\n"})
        self.assertIsNone(self.call(PC.post_tool_use, "git commit -m x", "b-cut", FILE_MAX=100))
        self.assertIn("1 changed files were not scanned", self.log())

    def test_a_large_range_is_cut_short_and_logged(self):
        self.commit(**{"seed": "1\n"})
        self.assertIsNone(self.call(PC.pre_tool_use, "git commit -m x", "b-big"))
        for n in range(4):
            self.commit(**{f"f{n}.ts": "x({ ...body })\n"})
        told = self.call(PC.post_tool_use, "git commit -m x", "b-big", MAX_COMMITS=2)
        ctx = told["hookSpecificOutput"]["additionalContext"]
        self.assertIn("f3.ts:1", ctx)
        self.assertNotIn("f0.ts", ctx)
        self.assertIn("scan-truncated", self.log())


def load_bash_words():
    spec = importlib.util.spec_from_file_location(
        "bash_words", os.path.join(REPO, "hooks", "bash_words.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BW = load_bash_words()


class BashWords(unittest.TestCase):
    """hooks/bash_words.py: the shared reader finds git and gh calls inside a Bash command."""

    def git(self, command, cwd="/r"):
        out = []
        for _, args, prefix, c in BW.calls(command, {"git"}, cwd):
            sub, rest, where = BW.git_call(args, prefix, c)
            out.append(((sub, rest), where["cwd"]))
        return out

    def test_chains_and_wrappers_with_options(self):
        cases = {
            "git add -A && git commit -m x": [("add", ["-A"]), ("commit", ["-m", "x"])],
            "sudo -E git commit": [("commit", [])],
            "env -i git commit -q": [("commit", ["-q"])],
            "sudo -u me git commit": [("commit", [])],
            "timeout -k 5 30 git push": [("push", [])],
            "nice -n 5 git commit; git push origin x": [("commit", []), ("push", ["origin", "x"])],
            "FOO=1 git -c a=b commit || true": [("commit", [])],
            "git status | grep x": [("status", [])],
            "sudo -R /x git push": [("push", [])],
            "sudo --preserve-env git commit": [("commit", [])],
            "sudo -E -u me git push": [("push", [])],
            "env -i GIT_DIR=/o/.git git commit": [("commit", [])],
        }
        for command, want in cases.items():
            with self.subTest(command=command):
                self.assertEqual([g for g, _ in self.git(command)], want)

    def test_a_quoted_message_naming_git_push_is_no_push(self):
        self.assertEqual([g[0] for g, _ in self.git('git commit -m "then git push it"')],
                         ["commit"])
        self.assertEqual([g[0] for g, _ in self.git("git commit -m 'x; git push'")], ["commit"])
        self.assertEqual(self.git("echo 'git push'"), [])
        self.assertEqual([g[0] for g, _ in self.git(
            "git commit -F- <<'EOF'\ngit push origin main\nEOF\n")], ["commit"])

    def test_redirections_and_their_targets_are_no_words(self):
        # Review round 1: `git push 2>&1` read as remote "2" and refspec ">", so no push
        # source resolved and nothing was scanned.
        cases = {
            "git push 2>&1": [("push", [])],
            "git push origin 2>&1 | tail": [("push", ["origin"])],
            "git push -q 2>/dev/null": [("push", ["-q"])],
            "git commit -m x >/dev/null": [("commit", ["-m", "x"])],
            "2>err git push >>log origin main": [("push", ["origin", "main"])],
            "git push &>/dev/null; git push >| out": [("push", []), ("push", [])],
            'git commit -F - <<< "$msg"': [("commit", ["-F", "-"])],
            "git push origin x>&- 3<&0": [("push", ["origin", "x"])],
            "git push origin 2": [("push", ["origin", "2"])],  # a word, not an fd
            'git commit -m "a > b" 2>&1': [("commit", ["-m", "a > b"])],
        }
        for command, want in cases.items():
            with self.subTest(command=command):
                self.assertEqual([g for g, _ in self.git(command)], want)

    def test_substitution_bodies_are_read_from_the_cwd_where_they_sit(self):
        # Review round 2, medium 1: each $(...) and backtick body was a placeholder, never read.
        cases = {
            'out=$(git push origin feat 2>&1); echo "$out"': [(("push", ["origin", "feat"]), "/r")],
            "cd sub && x=$(git push)": [(("push", []), "/r/sub")],
            "x=$(cd sub && git push); git commit": [(("push", []), "/r/sub"),
                                                     (("commit", []), "/r")],
            "echo `git push`": [(("push", []), "/r")],
            'echo "$(echo $(git push x))"': [(("push", ["x"]), "/r")],
            "diff <(git push) >(git commit)": [(("push", []), "/r"), (("commit", []), "/r")],
            "git commit -m \"$(cat <<'EOF'\nfix: git push later\nEOF\n)\"": [
                (("commit", ["-m", "%SUBST%"]), "/r")],
            "echo '$(git push)'": [],
            "echo `echo \\`git push\\``": [(("push", []), "/r")],
        }
        for command, want in cases.items():
            with self.subTest(command=command):
                self.assertEqual(self.git(command), want)
        (_, _, _, _), = BW.calls("PR=$(gh pr create --title t --body b)", {"git", "gh"}, "/r")
        with self.assertRaises(ValueError):
            BW.calls("$(" * 12 + "git push" + ")" * 12, {"git"}, "/r")
        # delete_guard's segments keep their shape: a process substitution's body still splits.
        self.assertEqual(list(BW.segments("diff <(rm -rf x) y")), [["diff", "<"], ["rm", "-rf", "x"],
                                                                  ["y"]])

    def test_cd_then_commit_runs_in_the_new_dir(self):
        self.assertEqual(self.git("cd sub && git commit")[0][1], "/r/sub")
        self.assertEqual(self.git("cd /abs/x && git commit")[0][1], "/abs/x")
        self.assertIsNone(self.git('cd "$D" && git commit')[0][1])

    def test_git_dir_work_tree_and_dash_c(self):
        (_, args, prefix, cwd), = BW.calls("GIT_DIR=../o/.git git -C a -C b commit", {"git"}, "/r")
        sub, _, where = BW.git_call(args, prefix, cwd)
        self.assertEqual((sub, where["cwd"], where["git_dir"]), ("commit", "/r/a/b", "/r/a/o/.git"))
        _, _, where = BW.git_call(["--git-dir=/g/.git", "--work-tree", "w", "commit"], [], "/r")
        self.assertEqual((where["git_dir"], where["work_tree"]), ("/g/.git", "/r/w"))
        for bad in (["-C", "$D", "commit"], ["--git-dir=%SUBST%", "commit"]):
            with self.subTest(args=bad):
                with self.assertRaises(BW.Unreadable):
                    BW.git_call(bad, [], "/r")
        with self.assertRaises(BW.Unreadable):
            BW.git_call(["commit"], [("GIT_DIR", "$G")], "/r")
        (_, args, prefix, _), = BW.calls("env GIT_DIR=/o/.git git commit", {"git"}, "/r")
        self.assertEqual(BW.git_call(args, prefix, "/r")[2]["git_dir"], "/o/.git")


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
