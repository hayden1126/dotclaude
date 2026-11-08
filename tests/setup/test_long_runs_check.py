"""hooks/long-runs-check.sh: deny once until the long-runs skill is loaded, before a heavy gate."""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "long-runs-check.sh")
SID = "11111111-2222-3333-4444-555555555555"
SUITE = "python3 -m pytest"
OTHER = "npm test"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="long-runs-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = os.path.join(self.tmp, "home", ".claude")
        self.proj = os.path.join(self.tmp, "proj")
        self.state = os.path.join(self.tmp, "state")
        self.skill_dir = os.path.join(self.config, "skills", "long-runs")
        os.makedirs(self.skill_dir)
        os.makedirs(self.proj)
        with open(os.path.join(self.skill_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: long-runs\n---\n")
        self.transcript = os.path.join(self.tmp, "projects", SID + ".jsonl")
        os.makedirs(os.path.dirname(self.transcript))
        self.rows()
        self.env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        self.env.update(HOME=os.path.join(self.tmp, "home"), CLAUDE_CONFIG_DIR=self.config,
                        XDG_STATE_HOME=self.state, CLAUDE_PROJECT_DIR=self.proj)

    def rows(self, *rows):
        with open(self.transcript, "w") as f:
            f.write(json.dumps({"type": "permission-mode", "permissionMode": "default"}) + "\n")
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")

    def loaded(self):
        self.rows({"type": "assistant", "uuid": "a1", "message": {"content": [
                      {"type": "tool_use", "id": "t1", "name": "Skill",
                       "input": {"skill": "long-runs"}}]}},
                  {"type": "user", "uuid": "u1", "message": {"content": [
                      {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}})

    def pre(self, command, session=SID, **extra):
        p = subprocess.run(
            ["bash", HOOK], capture_output=True, text=True, env=self.env, timeout=30,
            input=json.dumps({"session_id": session, "transcript_path": self.transcript,
                              "cwd": self.proj, "hook_event_name": "PreToolUse",
                              "tool_name": "Bash", "tool_input": {"command": command},
                              "tool_use_id": "b-now", **extra}))
        self.assertEqual(p.returncode, 0, p.stderr)
        if not p.stdout.strip():
            return None
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        return out["permissionDecisionReason"]

    def config_toml(self, text):
        d = os.path.join(self.proj, ".claude", "practices")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "config.toml"), "w") as f:
            f.write(text)

    def log(self):
        try:
            with open(os.path.join(self.state, "dotclaude", "practices", "errors.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""


class HeavyGates(Base):
    def test_each_heavy_form_denies_at_first_use(self):
        for n, command in enumerate((
                'lane trial --run "python3 -m unittest"', "lane lock suite -- ./gate.sh",
                "lane lock --wait 30 gate -- ./gate.sh", "timeout 900 lane trial --run x",
                "cd sub && lane lock suite -- npm run e2e")):
            with self.subTest(command=command):
                reason = self.pre(command, session=f"s{n}")
                self.assertIn("long-runs", reason)
                self.assertIn("Skill tool", reason)

    def test_other_locks_and_lookups_never_deny(self):
        for command in ("lane lock install -- ./setup.sh", "lane lock quiet -- ./run.sh",
                        "lane lock --help", "lane ls", "lane trial --help", "lane trial -h",
                        "lane note 'ran lane trial'", "grep 'lane trial' docs/lanes.md",
                        "echo pytest", "git log --grep pytest"):
            with self.subTest(command=command):
                self.assertIsNone(self.pre(command))

    def test_the_deny_fires_once_and_the_resend_passes(self):
        self.assertIsNotNone(self.pre("lane trial --run x"))
        self.assertIsNone(self.pre("lane trial --run x"))
        self.assertIsNone(self.pre("lane lock suite -- x"))

    def test_loaded_means_no_deny(self):
        self.loaded()
        self.assertIsNone(self.pre("lane trial --run x"))

    def test_a_failed_load_does_not_count(self):
        self.rows({"type": "assistant", "uuid": "a1", "message": {"content": [
                      {"type": "tool_use", "id": "t1", "name": "Skill",
                       "input": {"skill": "long-runs"}}]}},
                  {"type": "user", "uuid": "u1", "message": {"content": [
                      {"type": "tool_result", "tool_use_id": "t1", "content": "no such",
                       "is_error": True}]}})
        self.assertIsNotNone(self.pre("lane trial --run x"))

    def test_a_load_before_a_compaction_does_not_count_and_it_can_fire_again(self):
        self.assertIsNotNone(self.pre("lane trial --run x"))
        self.loaded()
        boundary = {"type": "system", "subtype": "compact_boundary", "uuid": "b1"}
        with open(self.transcript, "a") as f:
            f.write(json.dumps(boundary, separators=(",", ":")) + "\n")
        self.assertIsNotNone(self.pre("lane trial --run x"))
        self.assertIsNone(self.pre("lane trial --run x"))

    def test_a_subagent_is_left_alone(self):
        # With its own transcript present, so only the subagent rule can allow this.
        path = self.transcript[:-len(".jsonl")] + "/subagents/agent-agent-1.jsonl"
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write(json.dumps({"type": "permission-mode", "permissionMode": "default"}) + "\n")
        self.assertIsNone(self.pre("lane trial --run x", agent_id="agent-1"))

    def test_no_skill_installed_means_no_deny(self):
        shutil.rmtree(self.skill_dir)
        self.assertIsNone(self.pre("lane trial --run x"))

    def test_a_call_the_practices_hook_may_deny_is_left_to_it(self):
        # Two hooks denying one call show one reason only, so this one yields.
        for command in ("lane trial --run x && git push", "lane trial --run x; git commit -m y",
                        "lane trial --run x && gh pr ready 3", "lane lock suite -- npm i acme"):
            with self.subTest(command=command):
                self.assertIsNone(self.pre(command))


class GenericSuites(Base):
    def test_a_second_different_suite_denies(self):
        self.assertIsNone(self.pre(SUITE))
        self.assertIn("long-runs", self.pre(OTHER))

    def test_a_rerun_never_counts(self):
        for command in (SUITE, SUITE, SUITE + " -x", SUITE + " -v -q", SUITE + " -xq",
                        SUITE + " -xvs", SUITE + " -ra", SUITE + " -n auto", SUITE + " --tb short",
                        "pytest"):
            with self.subTest(command=command):
                self.assertIsNone(self.pre(command))

    def test_flags_that_change_nothing_on_other_runners(self):
        for first, second in (("go test ./...", "go test -count=1 ./..."),
                              ("make test", "make -j8 test")):
            with self.subTest(first=first):
                self.assertIsNone(self.pre(first, session=first))
                self.assertIsNone(self.pre(second, session=first))

    def test_a_rerun_after_a_compaction_still_never_counts(self):
        self.assertIsNone(self.pre(SUITE))
        self.assertIsNotNone(self.pre(OTHER))
        self.assertIsNone(self.pre(OTHER))
        boundary = {"type": "system", "subtype": "compact_boundary", "uuid": "b1"}
        with open(self.transcript, "a") as f:
            f.write(json.dumps(boundary, separators=(",", ":")) + "\n")
        self.assertIsNone(self.pre(SUITE))

    def test_flags_that_name_a_suite_count(self):
        self.assertIsNone(self.pre("vitest --project=unit", session="a"))
        self.assertIn("long-runs", self.pre("vitest --project=e2e", session="a"))
        self.assertIsNone(self.pre("npm test --workspace=a", session="b"))
        self.assertIn("long-runs", self.pre("npm test --workspace=b", session="b"))

    def test_coverage_flags_are_no_new_suite(self):
        self.assertIsNone(self.pre("pytest"))
        self.assertIsNone(self.pre("pytest --cov src"))
        self.assertIsNone(self.pre("pytest --cov=src"))

    def test_the_sessions_own_directory_is_not_part_of_a_suite(self):
        self.assertIsNone(self.pre("pytest"))
        self.proj_was, self.proj = self.proj, self.proj + "-elsewhere"
        os.makedirs(self.proj)
        self.assertIsNone(self.pre("pytest"))

    def test_different_scripts_are_different_suites(self):
        self.assertIsNone(self.pre("npm run test:unit"))
        self.assertIn("long-runs", self.pre("npm run test:e2e"))

    def test_a_cd_does_not_make_a_rerun_a_new_suite(self):
        self.assertIsNone(self.pre("cd /x && pytest"))
        self.assertIsNone(self.pre("pytest"))

    def test_short_flags_with_several_meanings_stay_out_of_the_suite(self):
        for first, second in (("rspec", "rspec -c"), ("vitest", "vitest -w"), ("jest", "jest -w=4"), ("jest", "jest -w 4"),
                              ("go test ./...", "go test -parallel 4 ./..."),
                              ("cargo test", "cargo test --jobs 4"),
                              ("pytest", "pytest --log-level DEBUG"),
                              ("pytest tests/", "pytest tests")):
            with self.subTest(first=first):
                self.assertIsNone(self.pre(first, session=first))
                self.assertIsNone(self.pre(second, session=first))

    def test_words_after_a_double_dash_are_the_inner_tools(self):
        self.assertIsNone(self.pre("tox -- -l"))
        self.assertIn("long-runs", self.pre("npm test"))

    def test_a_spent_budget_saves_nothing_so_the_deny_can_come_later(self):
        sys.path.insert(0, os.path.join(REPO, "hooks"))
        self.addCleanup(sys.path.remove, os.path.join(REPO, "hooks"))
        import long_runs_check as L  # noqa: PLC0415
        self.assertIsNone(self.pre(SUITE))
        event = {"session_id": SID, "transcript_path": self.transcript, "cwd": self.proj,
                 "hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "tool_input": {"command": OTHER}, "tool_use_id": "b-now"}
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(L.PC, "START", time.monotonic()), \
                mock.patch.object(L.PC, "l1_window", side_effect=L.PC.Budget("x")), \
                self.assertRaises(L.PC.Budget):
            L.check(event)
        self.assertIn("long-runs", self.pre(OTHER))

    def test_a_look_at_the_runner_is_no_suite(self):
        for command in ("pytest --version", "pytest --collect-only", "pytest --lf", "pytest -h",
                        "cargo test --help", "cargo test --no-run", "make -n test", "tox -l",
                        "go test -list ."):
            with self.subTest(command=command):
                self.assertIsNone(self.pre(command))
        self.assertIsNone(self.pre("npm test"))  # the looks above counted as no suite

    def test_two_suites_in_one_call_deny(self):
        self.assertIn("long-runs", self.pre(f"{SUITE} && {OTHER}"))

    def test_unittest_directories_are_different_suites(self):
        self.assertIsNone(self.pre("python3 -m unittest discover -s tests/setup"))
        self.assertIn("long-runs", self.pre("python3 -m unittest discover -s tests/lanes"))

    def test_narrowed_runs_never_count(self):
        for command in ("pytest tests/test_x.py", "pytest tests/test_x.py::test_a",
                        "pytest -k fast", "pytest -kfast", "python3 -m unittest tests.foo.Bar",
                        "npx vitest run src/a.test.ts", "npx playwright test --grep login",
                        "go test -run TestA ./...", "cargo test one_name",
                        "npm test -- src/a.test.ts", "jest -t name"):
            with self.subTest(command=command):
                self.assertIsNone(self.pre(command))

    def test_whole_suite_spellings_count(self):
        for n, command in enumerate(("pytest", "pytest tests/", "python -m pytest", "npm run test",
                                     "pnpm test", "yarn test", "bun test", "npx vitest run",
                                     "npx jest", "npx playwright test", "cargo test",
                                     "go test ./...", "make test", "make check", "tox", "nox",
                                     "python3 -m unittest discover", "npm t", "pnpm test:unit",
                                     "uv run pytest", "poetry run python -m pytest",
                                     "python3 -m unittest discover -s tests -p test_*.py")):
            with self.subTest(command=command):
                self.assertIsNone(self.pre(command, session=f"w{n}"))
                other = "nox -s other" if command == "tox" else "tox -e other"
                self.assertIn("long-runs", self.pre(other, session=f"w{n}"))

    def test_the_state_holds_no_command_text(self):
        self.pre("pytest tests/secret_name")
        for root, _, files in os.walk(self.state):
            for name in files:
                with open(os.path.join(root, name)) as f:
                    self.assertNotIn("secret_name", f.read())


class RepoList(Base):
    def test_a_listed_gate_denies_at_first_use(self):
        self.config_toml('[long_runs]\ngates = ["./gate.sh", "uv run nightly"]\n')
        self.assertIn("long-runs", self.pre("./gate.sh --all", session="a"))
        self.assertIn("long-runs", self.pre("uv run nightly", session="b"))
        self.assertIsNone(self.pre("uv run other", session="c"))

    def test_a_repo_can_list_one_of_its_locks(self):
        self.config_toml('[long_runs]\ngates = ["lane lock quiet"]\n')
        self.assertIn("long-runs", self.pre("lane lock quiet -- ./run.sh"))

    def test_the_list_only_adds(self):
        self.config_toml('[long_runs]\ngates = []\n')
        self.assertIn("long-runs", self.pre("lane trial --run x"))

    def test_entries_are_argv_never_patterns(self):
        self.config_toml('[long_runs]\ngates = [".*", "(a+)+$"]\n')
        self.assertIsNone(self.pre("anything at all"))

    def test_a_bad_config_keeps_the_defaults_and_logs(self):
        for text in ("[long_runs\n", "[long_runs]\ngates = 3\n", '[long_runs]\ngates = [1]\n'):
            with self.subTest(text=text):
                self.config_toml(text)
                shutil.rmtree(self.state, ignore_errors=True)
                self.assertIn("long-runs", self.pre("lane trial --run x", session=text))
                self.assertIn("long-runs-config", self.log())


class OffSwitch(Base):
    def test_a_project_config_cannot_turn_it_off(self):
        self.config_toml('enabled = false\ndisable = ["LONG-RUNS"]\n')
        self.assertIn("long-runs", self.pre("lane trial --run x"))


    def test_the_practices_off_switch_covers_it(self):
        sys.path.insert(0, os.path.join(REPO, "hooks"))
        self.addCleanup(sys.path.remove, os.path.join(REPO, "hooks"))
        import long_runs_check as L  # noqa: PLC0415
        event = {"session_id": SID, "transcript_path": self.transcript, "cwd": self.proj,
                 "hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "tool_input": {"command": "lane trial --run x"}, "tool_use_id": "b-now"}
        base = {"enabled": True, "disable": set(), "helpers": ()}
        for cfg, denied in ((base, True), ({**base, "enabled": False}, False),
                            ({**base, "disable": {"LONG-RUNS"}}, False),
                            ({**base, "disable": {"long-runs:LONG-RUNS"}}, False)):
            with self.subTest(cfg=cfg), mock.patch.dict(os.environ, self.env, clear=True), \
                    mock.patch.object(L.PC, "START", time.monotonic()), \
                    mock.patch.object(L.PC, "load_config", return_value=cfg):
                shutil.rmtree(self.state, ignore_errors=True)
                self.assertEqual(L.check(event) is not None, denied)


class Pruning(Base):
    def test_a_session_start_prunes_old_state(self):
        d = os.path.join(self.state, "dotclaude", "practices", "long-runs")
        os.makedirs(d)
        old = os.path.join(d, "old.json")
        open(old, "w").close()
        os.utime(old, (1, 1))
        hook = os.path.join(REPO, "hooks", "practices-check.sh")
        subprocess.run(["bash", hook], text=True, env=self.env, capture_output=True, timeout=30,
                       input=json.dumps({"session_id": SID, "transcript_path": self.transcript,
                                         "cwd": self.proj, "hook_event_name": "SessionStart",
                                         "source": "startup"}))
        self.assertFalse(os.path.exists(old))


class Failures(Base):
    def test_bad_input_is_allowed(self):
        for stdin in ("", "not json", "[]", '{"tool_name":"Bash"}'):
            with self.subTest(stdin=stdin):
                p = subprocess.run(["bash", HOOK], capture_output=True, text=True, env=self.env,
                                   input=stdin, timeout=30)
                self.assertEqual((p.returncode, p.stdout.strip()), (0, ""))

    def test_an_unparsable_command_is_allowed(self):
        self.assertIsNone(self.pre("lane trial --run 'x"))

    def test_an_unkept_state_file_allows(self):
        os.makedirs(self.state)
        open(os.path.join(self.state, "dotclaude"), "w").close()
        self.assertIsNone(self.pre("lane trial --run x"))


class Wiring(unittest.TestCase):
    def settings(self):
        with open(os.path.join(REPO, "settings.json")) as f:
            return json.load(f)

    def entry(self):
        hits = [h for g in self.settings()["hooks"]["PreToolUse"] if g.get("matcher") == "Bash"
                for h in g["hooks"] if "long-runs-check.sh" in h["command"]]
        self.assertEqual(len(hits), 1)
        return hits[0]

    def run_entry(self, command, env=None):
        tmp = tempfile.mkdtemp(prefix="long-runs-wire-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        hooks = os.path.join(tmp, ".claude", "hooks")
        os.makedirs(hooks)
        marker = os.path.join(tmp, "ran")
        with open(os.path.join(hooks, "long-runs-check.sh"), "w") as f:
            f.write(f"cat > /dev/null; touch {marker}\n")
        e = {"PATH": os.environ["PATH"], "HOME": tmp, **(env or {})}
        subprocess.run(["bash", "-c", self.entry()["command"]], env=e, text=True, timeout=10,
                       input=json.dumps({"tool_input": {"command": command}}))
        return os.path.exists(marker)

    def test_the_filter_passes_gates_and_skips_the_rest(self):
        for command in ("lane trial --run x", "lane lock suite -- y", "pytest", "npm test",
                        "python3 -m unittest discover", "npx vitest run", "cargo test",
                        "go test ./...", "make check", "tox"):
            with self.subTest(command=command):
                self.assertTrue(self.run_entry(command))
        for command in ("ls -la", "git status", "cat README.md"):
            with self.subTest(command=command):
                self.assertFalse(self.run_entry(command))

    def test_a_repo_with_a_list_always_reaches_the_hook(self):
        proj = tempfile.mkdtemp(prefix="long-runs-proj-")
        self.addCleanup(shutil.rmtree, proj, ignore_errors=True)
        os.makedirs(os.path.join(proj, ".claude", "practices"))
        with open(os.path.join(proj, ".claude", "practices", "config.toml"), "w") as f:
            f.write('[long_runs]\ngates = ["./gate.sh"]\n')
        self.assertTrue(self.run_entry("./gate.sh", {"CLAUDE_PROJECT_DIR": proj}))

    def test_a_config_that_never_ends_does_not_hang_the_filter(self):
        for make in (lambda p: os.symlink("/dev/zero", p), os.mkfifo):
            proj = tempfile.mkdtemp(prefix="long-runs-proj-")
            self.addCleanup(shutil.rmtree, proj, ignore_errors=True)
            os.makedirs(os.path.join(proj, ".claude", "practices"))
            make(os.path.join(proj, ".claude", "practices", "config.toml"))
            began = time.monotonic()
            self.assertFalse(self.run_entry("ls -la", {"CLAUDE_PROJECT_DIR": proj}))
            self.assertLess(time.monotonic() - began, 3)

    def test_the_timeout_is_set(self):
        self.assertEqual(self.entry()["timeout"], 5)


class Contract(unittest.TestCase):
    """The names this hook imports from the practices hook, which another lane also changes."""

    def test_every_imported_name_exists(self):
        with open(os.path.join(REPO, "hooks", "practices_check.py")) as f:
            tree = ast.parse(f.read())
        have = {n.name for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        have |= {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 for t in n.targets if isinstance(t, ast.Name)}
        sys.path.insert(0, os.path.join(REPO, "hooks"))
        self.addCleanup(sys.path.remove, os.path.join(REPO, "hooks"))
        import long_runs_check  # noqa: PLC0415
        for name in long_runs_check.FROM_PRACTICES:
            self.assertIn(name, have)


if __name__ == "__main__":
    unittest.main()
