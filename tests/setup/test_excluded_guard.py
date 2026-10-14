"""hooks/excluded-guard.sh: excluded commands must not act on anything a sandboxed session can write.

Each test builds a fake HOME (with .claude/settings.json), a project repo made by `git init` plus a
`git worktree add` lane, and PATH dirs holding marker executables (`#!/bin/sh` echo scripts named
git, gh, lane, claude, codex). Tests run inside the Bash sandbox, where the temp dir is writable and
sits under /tmp, so protection comes from `chmod 555` or a denyWrite entry, never from location.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "excluded-guard.sh")
MODULE = os.path.join(REPO, "hooks", "excluded_guard.py")
EXCLUDED = ["git push", "git push origin *", "gh pr *", "lane ls", "lane ls *", "claude *",
            "codex login status"]
HEADS = ("git", "gh", "lane", "claude", "codex")
MARKER = "#!/bin/sh\necho marker\n"


def unlock(root):
    for d, dirs, files in os.walk(root):
        os.chmod(d, 0o755)
        for name in files:
            p = os.path.join(d, name)
            if not os.path.islink(p):
                os.chmod(p, 0o644)


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.addCleanup(unlock, self.tmp)
        self.home = self.mkdir("home")
        self.deny_write = []
        self.write_settings()
        self.proj = os.path.join(self.tmp, "proj")
        self.lane = os.path.join(self.tmp, "lane")
        self.git("init", "-q", self.proj, cwd=self.tmp)
        self.git("commit", "-q", "--allow-empty", "-m", "init", cwd=self.proj)
        self.git("worktree", "add", "-q", "-b", "lane", self.lane, cwd=self.proj)
        self.bin = self.make_bin("bin")
        self.wbin = self.make_bin("wbin", protect=False)
        self.env = {"HOME": self.home, "PATH": f"{self.bin}:/usr/bin:/bin",
                    "CLAUDE_PROJECT_DIR": self.proj, "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
                    "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
                    "GIT_CEILING_DIRECTORIES": self.tmp,
                    "EXCLUDED_GUARD_MANAGED_DIR": os.path.join(self.tmp, "managed")}

    # --- fixtures ------------------------------------------------------------------------------

    def mkdir(self, *parts):
        p = os.path.join(self.tmp, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def write(self, path, text, mode=0o644):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    def write_settings(self, extra=None):
        sandbox = {"excludedCommands": EXCLUDED,
                   "filesystem": {"denyWrite": self.deny_write, "allowWrite": []}}
        sandbox.update(extra or {})
        self.write(os.path.join(self.home, ".claude", "settings.json"),
                   json.dumps({"sandbox": sandbox}))

    def git(self, *args, cwd):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)

    def make_bin(self, name, heads=HEADS, protect=True):
        d = self.mkdir(name)
        for head in heads:
            self.write(os.path.join(d, head), MARKER, 0o555 if protect else 0o755)
        if protect:
            os.chmod(d, 0o555)
        return d

    def fire(self, command, cwd=None, raw=None, hook=HOOK, env=None):
        event = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "cwd": cwd or self.proj, "tool_input": {"command": command}}
        p = subprocess.run(["bash", hook], input=raw if raw is not None else json.dumps(event),
                           capture_output=True, text=True, env=env or self.env, timeout=20,
                           cwd=cwd or self.proj)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.last_stdout = p.stdout
        return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None

    def allowed(self, command, **kw):
        out = self.fire(command, **kw)
        self.assertIsNone(out, out and out["permissionDecisionReason"])

    def denied(self, command, rule, path=None, **kw):
        out = self.fire(command, **kw)
        self.assertIsNotNone(out, f"{command!r} was allowed")
        self.assertEqual(out["permissionDecision"], "deny")
        reason = out["permissionDecisionReason"]
        self.assertIn(f"({rule})", reason)
        if path:
            self.assertIn(path, reason)
        return reason

    def log(self):
        try:
            with open(os.path.join(self.tmp, "state", "dotclaude", "excluded-guard.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""


class Rule1Repository(Guard):
    def test_the_project_root_passes(self):
        self.allowed("git push")
        self.allowed("gh pr view 5")

    def test_a_lane_worktree_as_the_project_passes(self):
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.allowed("git push origin lane", cwd=self.lane)
        self.allowed("lane ls", cwd=self.lane)

    def test_a_subdir_of_the_root_in_the_same_repo_passes(self):
        self.allowed("git push", cwd=self.mkdir("proj", "sub", "deeper"))

    def test_a_nested_repo_under_the_root_is_refused(self):
        nested = self.mkdir("proj", "sub", "nested")
        self.git("init", "-q", nested, cwd=self.tmp)
        self.denied("git push", "rule1", os.path.join(nested, ".git"), cwd=nested)
        self.assertIn("deny rule1 " + os.path.join(nested, ".git"), self.log())

    def test_a_planted_gitfile_pointing_elsewhere_is_refused(self):
        other = self.mkdir("other")
        self.git("init", "-q", other, cwd=self.tmp)
        planted = self.mkdir("proj", "planted")
        self.write(os.path.join(planted, ".git"), "gitdir: ../../other/.git\n")
        self.denied("git push", "rule1", os.path.join(other, ".git"), cwd=planted)

    def test_a_temp_dir_with_its_own_repo_is_refused(self):
        other = self.mkdir("other")
        self.git("init", "-q", other, cwd=self.tmp)
        self.denied("gh pr view", "rule1", cwd=other)

    def test_no_repo_at_the_cwd_passes(self):
        plain = self.mkdir("plain")
        self.env["CLAUDE_PROJECT_DIR"] = plain
        self.allowed("git push", cwd=plain)

    def test_a_project_root_that_is_no_repo_makes_any_repo_foreign(self):
        self.env["CLAUDE_PROJECT_DIR"] = self.mkdir("plain")
        self.denied("git push", "rule1")


class Rule1Config(Guard):
    def gitconfig(self, text):
        self.write(os.path.join(self.home, ".gitconfig"), text)

    def test_an_include_of_a_writable_file_is_refused(self):
        inc = self.write(os.path.join(self.tmp, "wcfg", "inc.cfg"), "[user]\n\tname = x\n")
        self.gitconfig(f"[include]\n\tpath = {inc}\n")
        self.denied("git push", "rule1", inc)

    def test_an_include_if_target_that_is_writable_is_refused(self):
        inc = self.write(os.path.join(self.tmp, "wcfg", "inc.cfg"), "")
        self.gitconfig(f'[includeIf "gitdir:/nowhere/"]\n  path = "{inc}"  # a comment\n')
        self.denied("git push", "rule1", inc)

    def test_a_writable_hooks_path_is_refused(self):
        hooks = self.mkdir("whooks")
        self.gitconfig(f"[core]\n\thooksPath = {hooks}\n")
        self.denied("git push", "rule1", hooks)

    def test_a_protected_include_passes_and_its_own_includes_are_followed(self):
        inc = self.write(os.path.join(self.tmp, "pcfg", "inc.cfg"), "[user]\n\tname = x\n", 0o444)
        os.chmod(os.path.dirname(inc), 0o555)
        self.gitconfig(f"[include]\n\tpath = {inc}\n")
        self.allowed("git push")
        os.chmod(os.path.dirname(inc), 0o755)
        os.chmod(inc, 0o644)
        inner = self.write(os.path.join(self.tmp, "wcfg", "inner.cfg"), "")
        self.write(inc, f"[include]\n\tpath = ../wcfg/inner.cfg\n", 0o444)
        os.chmod(os.path.dirname(inc), 0o555)
        self.denied("git push", "rule1", inner)

    def test_a_denywrite_entry_protects_an_include(self):
        inc = self.write(os.path.join(self.tmp, "wcfg", "inc.cfg"), "")
        self.gitconfig(f"[include]\n\tpath = {inc}\n")
        self.deny_write.append(os.path.dirname(inc))
        self.write_settings()
        self.allowed("git push")

    def test_the_repos_own_config_is_trusted_but_its_includes_are_not(self):
        inc = self.write(os.path.join(self.tmp, "wcfg", "inc.cfg"), "")
        with open(os.path.join(self.proj, ".git", "config"), "a") as f:
            f.write(f"[include]\n\tpath = {inc}\n")
        self.denied("git push", "rule1", inc)

    def test_a_writable_xdg_config_is_refused(self):
        xdg = self.write(os.path.join(self.home, ".config", "git", "config"), "")
        self.denied("git push", "rule1", xdg)


class Rule2Path(Guard):
    def test_a_writable_dir_before_the_head_is_refused(self):
        self.env["PATH"] = f"{self.wbin}:{self.bin}:/usr/bin"
        self.denied("git push", "rule2", self.wbin)
        self.assertIn("deny rule2 " + self.wbin, self.log())

    def test_a_writable_dir_after_the_head_is_never_searched(self):
        self.env["PATH"] = f"{self.bin}:{self.wbin}:/usr/bin"
        self.allowed("git push")

    def test_a_denywrite_entry_protects_a_path_dir(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.denied("lane ls", "rule2", self.wbin)
        self.deny_write.append(self.wbin)
        self.write_settings()
        self.allowed("lane ls")

    def test_an_empty_or_relative_entry_is_refused(self):
        for path in (f":{self.bin}:/usr/bin", f"/nonexistent::{self.bin}:/usr/bin",
                     f"bin:{self.bin}:/usr/bin"):
            with self.subTest(path=path):
                self.env["PATH"] = path
                self.denied("git push", "rule2")

    def test_a_symlink_into_a_writable_dir_is_refused(self):
        target = self.write(os.path.join(self.tmp, "wtarget", "real-git"), MARKER, 0o755)
        links = self.mkdir("links")
        os.symlink(target, os.path.join(links, "git"))
        os.chmod(links, 0o555)
        self.env["PATH"] = f"{links}:/usr/bin"
        self.denied("git push", "rule2", os.path.dirname(target))

    def test_a_shebang_interpreter_through_a_writable_dir_is_refused(self):
        sbin = self.mkdir("sbin")
        self.write(os.path.join(sbin, "lane"), "#!/usr/bin/env fakeinterp\n", 0o555)
        os.chmod(sbin, 0o555)
        self.write(os.path.join(self.wbin, "fakeinterp"), MARKER, 0o555)
        self.env["PATH"] = f"{sbin}:{self.wbin}:/usr/bin"
        self.denied("lane ls", "rule2", self.wbin)
        # The same interpreter in a protected dir passes.
        os.chmod(self.wbin, 0o555)
        self.allowed("lane ls")

    def test_a_head_not_on_path_passes(self):
        self.env["PATH"] = "/usr/bin:/bin"
        self.allowed("lane ls")

    def test_a_head_with_a_slash_is_checked_where_it_points(self):
        self.write_settings({"excludedCommands": EXCLUDED + [f"{self.wbin}/git push"]})
        self.denied(f"{self.wbin}/git push", "rule2", self.wbin)


class Rule3ProjectRoot(Guard):
    def test_claude_runs_only_from_the_project_root(self):
        self.allowed("claude --version")
        sub = self.mkdir("proj", "sub")
        self.denied("claude --version", "rule3", sub, cwd=sub)

    def test_codex_runs_only_from_the_project_root(self):
        self.allowed("codex login status")
        sub = self.mkdir("proj", "sub")
        self.denied("codex login status", "rule3", sub, cwd=sub)

    def test_git_from_a_subdir_is_not_held_to_rule_3(self):
        self.allowed("git push", cwd=self.mkdir("proj", "sub"))


class Matching(Guard):
    def everything_writable(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        nested = self.mkdir("nested")
        self.git("init", "-q", nested, cwd=self.tmp)
        return nested

    def test_a_non_candidate_passes_silently_even_when_everything_is_writable(self):
        cwd = self.everything_writable()
        for command in ("ls", "git status", "gh repo view", "echo lane ls"):
            with self.subTest(command=command):
                self.allowed(command, cwd=cwd)
                self.assertEqual(self.last_stdout, "")
        self.assertEqual(self.log(), "")

    def test_a_compound_with_an_excluded_piece_is_a_candidate(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        for command in ("echo x && git push", "echo x; git push origin main", "ls | gh pr view",
                        "echo x\nFOO=1 git push", "(git push)", "true || lane ls -a"):
            with self.subTest(command=command):
                self.denied(command, "rule2", self.wbin)
        self.allowed("echo x && ls")

    def test_a_star_spans_spaces_and_the_rest_is_literal(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.denied("gh pr view 5 --json title", "rule2")
        self.denied("claude -p 'a b c'", "rule2")
        self.allowed("gh prx view")
        self.allowed("git pushy")

    def test_patterns_from_managed_and_project_settings_count(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.write(os.path.join(self.tmp, "managed", "managed-settings.d", "a.json"),
                   json.dumps({"sandbox": {"excludedCommands": ["gh run *"]}}))
        self.write(os.path.join(self.proj, ".claude", "settings.local.json"),
                   json.dumps({"sandbox": {"excludedCommands": ["gh api *"]}}))
        self.denied("gh run list", "rule2")
        self.denied("gh api user", "rule2")
        self.allowed("gh issue list")

    def test_an_unreadable_settings_file_makes_the_call_a_candidate(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.write(os.path.join(self.proj, ".claude", "settings.json"), "{not json")
        self.denied("gh issue list", "rule2")


class FailsClosed(Guard):
    def test_an_unparsable_payload_falls_back_to_the_head_word(self):
        for command, deny in (("git push", True), ("  FOO=1 gh pr view", True),
                              ("\\n\\tlane ls", True), ("codex;ls", True), ("ls", False),
                              ("echo git", False)):
            with self.subTest(command=command):
                raw = '{"tool_name": "Bash", "tool_input": {"command": "' + command
                out = self.fire(None, raw=raw)
                self.assertEqual(out is not None, deny, out)
                if deny:
                    self.assertEqual(out["permissionDecision"], "deny")
                    self.assertIn("could not run", out["permissionDecisionReason"])

    def test_a_broken_module_denies_excluded_heads_and_allows_the_rest(self):
        d = self.mkdir("broken")
        shutil.copy(HOOK, os.path.join(d, "excluded-guard.sh"))
        self.write(os.path.join(d, "excluded_guard.py"), "def (:\n")
        hook = os.path.join(d, "excluded-guard.sh")
        for command in ("git push", "FOO=1 gh pr view 5", "claude --version"):
            with self.subTest(command=command):
                out = self.fire(command, hook=hook)
                self.assertEqual(out["permissionDecision"], "deny")
        for command in ("ls", "echo x && git push"):
            with self.subTest(command=command):
                self.assertIsNone(self.fire(command, hook=hook))

    def test_output_that_is_not_json_falls_back(self):
        d = self.mkdir("noisy")
        shutil.copy(HOOK, os.path.join(d, "excluded-guard.sh"))
        self.write(os.path.join(d, "excluded_guard.py"), "print('not json')\n")
        hook = os.path.join(d, "excluded-guard.sh")
        self.assertEqual(self.fire("git push", hook=hook)["permissionDecision"], "deny")
        self.assertIsNone(self.fire("ls", hook=hook))

    def test_a_missing_project_dir_refuses_a_candidate(self):
        del self.env["CLAUDE_PROJECT_DIR"]
        self.denied("git push", "project")
        self.allowed("ls")

    def test_a_projects_json_py_never_runs(self):
        ran = os.path.join(self.tmp, "ran")
        self.write(os.path.join(self.proj, "json.py"), f"open({ran!r}, 'a').write(__name__)\n")
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.denied("git push", "rule2")
        self.assertFalse(os.path.exists(ran), "the guard imported the project's json.py")


if __name__ == "__main__":
    unittest.main()
