"""subagent-policy: the gate, every rule and intent, and the fail-closed paths.

Each test runs against a temporary home whose user settings carry this repo's baseline
`sandbox` block, so the excluded-command rules are the ones that ship."""
import json
import os
import re
import subprocess
import tempfile
import unittest

from _paths import HOOKS, REPO, SCRIPTS, load_script

sp = load_script("subagent-policy")
POLICY = sp.load_policy()
SCRIPT = os.path.join(SCRIPTS, "subagent-policy")
SHIM = os.path.join(HOOKS, "subagent-policy.sh")
with open(os.path.join(REPO, "settings.json")) as f:
    BASELINE = json.load(f)
SETTINGS_CMD = BASELINE["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def _test_tmp_dir():
    """Where the fake homes go. Inside Claude Code's sandbox the system temp dir is
    /tmp/claude-<uid>, one of the policy's own temp roots, so every "outside the root" case
    would pass as a temp write. There the fake homes go in the repo instead (gitignored),
    which a sandboxed session rooted in the repo can write. A checkout that is itself a
    Claude worktree can't host them: the policy would read every fake path as inside that
    worktree, and the one other writable place, the git common dir, trips rm-git-metadata."""
    base = os.path.realpath(tempfile.gettempdir())
    roots = [os.path.realpath(sp.expand(r, os.path.expanduser("~")))
             for r in POLICY["rm"]["temp_roots"]]
    if not any(sp.under(base, r) for r in roots):
        return None
    local = os.path.join(os.path.dirname(os.path.realpath(__file__)), ".tmp")
    if "/.claude/worktrees/" in local:
        raise RuntimeError("sandboxed in a checkout under .claude/worktrees/, the policy tests "
                           "have nowhere clean to build their fake homes; run this suite with "
                           "the sandbox off, or from a checkout outside .claude/worktrees/")
    os.makedirs(local, exist_ok=True)
    return local


TEST_TMP = _test_tmp_dir()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sp-test-", dir=TEST_TMP)
        self.home = os.path.realpath(self.tmp.name)
        os.makedirs(os.path.join(self.home, ".claude"))
        self.write_settings({"sandbox": BASELINE["sandbox"]})
        self.proj = os.path.join(self.home, "code", "proj")
        self.wt = os.path.join(self.proj, ".claude", "worktrees", "agent-w1")
        os.makedirs(self.wt)
        os.makedirs(os.path.join(self.proj, "src"))
        self.slug_dir = os.path.join(self.home, ".claude", "projects",
                                     re.sub(r"[^A-Za-z0-9]", "-", self.proj))
        os.makedirs(os.path.join(self.slug_dir, "s1", "subagents"))
        self.transcript = os.path.join(self.slug_dir, "s1.jsonl")
        bindir = os.path.join(self.home, "bin")  # gh-public as setup.sh links it, and a script
        os.makedirs(bindir)
        for exe in (os.path.join(bindir, "gh-public"), os.path.join(self.proj, "run.sh")):
            with open(exe, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(exe, 0o755)
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = bindir + ":" + self.old_path

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        self.tmp.cleanup()

    def write_settings(self, s):
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as f:
            json.dump(s, f)

    def meta(self, aid, **fields):
        with open(os.path.join(self.slug_dir, "s1", "subagents", f"agent-{aid}.meta.json"),
                  "w") as f:
            json.dump(fields, f)

    def ev(self, tool, ti, atype="general-purpose", cwd=None, aid="a1"):
        return {"agent_id": aid, "agent_type": atype, "tool_name": tool, "tool_input": ti,
                "cwd": cwd or self.proj, "session_id": "s1", "transcript_path": self.transcript,
                "hook_event_name": "PreToolUse"}

    def decide(self, tool, ti, **kw):
        d = sp.evaluate(self.ev(tool, ti, **kw), POLICY, home=self.home)
        return None if d is None else (d.rule, d.intent)

    def bash(self, cmd, **kw):
        return self.decide("Bash", {"command": cmd}, **kw)

    def assertDenied(self, result, rule=None, intent=None, msg=None):
        self.assertIsNotNone(result, msg)
        if rule:
            self.assertEqual(result[0], rule, msg)
        if intent:
            self.assertEqual(result[1], intent, msg)


class Gate(Base):
    def run_main(self, payload, extra_env=None):
        env = dict(os.environ, HOME=self.home, XDG_STATE_HOME=os.path.join(self.home, "state"))
        env.update(extra_env or {})
        return subprocess.run(["python3", SCRIPT], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)

    def test_main_thread_is_never_policed(self):
        payload = self.ev("Bash", {"command": "git push"})
        del payload["agent_id"]
        p = self.run_main(payload)
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_a_denial_is_a_pretooluse_deny_with_rule_intent_and_footer(self):
        p = self.run_main(self.ev("Bash", {"command": "git push origin main"}))
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("(manual_only)", out["permissionDecisionReason"])
        self.assertIn("blocked_actions", out["permissionDecisionReason"])

    def test_a_denial_writes_a_policy_row_and_a_heartbeat(self):
        self.run_main(self.ev("Bash", {"command": "git push"}))
        state = os.path.join(self.home, "state", "dotclaude")
        with open(os.path.join(state, "delegations.jsonl")) as f:
            row = json.loads(f.readline())
        self.assertEqual((row["event"], row["rule"], row["id"]), ("policy", "excluded-command", "a1"))
        self.assertTrue(os.path.exists(os.path.join(state, "subagent-policy.heartbeat")))

    def test_an_allowed_call_prints_nothing(self):
        p = self.run_main(self.ev("Bash", {"command": "ls -la src"}))
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_policy_error_denies_policed_tools_and_allows_handbacks(self):
        bad = os.path.join(self.home, "bad.toml")
        with open(bad, "w") as f:
            f.write("[intents\n")
        env = {"DELEGATION_POLICY": bad}
        p = self.run_main(self.ev("Bash", {"command": "ls"}), env)
        self.assertIn("policy-error", p.stdout)
        p = self.run_main(self.ev("Write", {"file_path": "/x", "content": ""}), env)
        self.assertIn("policy-error", p.stdout)
        p = self.run_main(self.ev("SubagentHandback", {"message": "report"}), env)
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_the_alarm_denies_before_claude_codes_timeout_would_allow(self):
        fifo = os.path.join(self.home, "hang.toml")
        os.mkfifo(fifo)  # opening it for reading blocks until the alarm fires
        p = self.run_main(self.ev("Bash", {"command": "ls"}), {"DELEGATION_POLICY": fifo})
        self.assertIn("TimeoutError", p.stdout)

    def test_malformed_input_from_a_subagent_is_denied(self):
        env = dict(os.environ, HOME=self.home, XDG_STATE_HOME=os.path.join(self.home, "state"))
        p = subprocess.run(["python3", SCRIPT], input='{"agent_id": "x", ', capture_output=True,
                           text=True, env=env)
        self.assertIn('"deny"', p.stdout)

    def test_settings_command_skips_main_thread_and_blocks_a_missing_shim(self):
        env = dict(os.environ, HOME=self.home)  # no hooks linked in this home
        main = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}})
        sub = json.dumps(self.ev("Bash", {"command": "ls"}))
        for shell in ("sh", "bash"):
            p = subprocess.run([shell, "-c", SETTINGS_CMD], input=main, capture_output=True,
                               text=True, env=env)
            self.assertEqual((p.returncode, p.stdout), (0, ""), shell)
            p = subprocess.run([shell, "-c", SETTINGS_CMD], input=sub, capture_output=True,
                               text=True, env=env)
            self.assertEqual(p.returncode, 2, shell)
            self.assertIn("blocked", p.stderr)

    def test_shim_exits_2_when_the_script_is_missing(self):
        p = subprocess.run(["bash", SHIM], input=json.dumps(self.ev("Bash", {"command": "ls"})),
                           capture_output=True, text=True, env=dict(os.environ, HOME=self.home))
        self.assertEqual(p.returncode, 2)


class Sandbox(Base):
    def test_any_sandbox_escape_key_is_a_hard_stop(self):
        for key in ("dangerouslyDisableSandbox", "disableSandbox", "sandbox_off"):
            self.assertDenied(self.decide("Bash", {"command": "ls", key: True}),
                              "sandbox-escape", "hard_stop", key)
        self.assertIsNone(self.decide("Bash", {"command": "ls", "dangerouslyDisableSandbox": False}))

    def test_no_shell_when_the_sandbox_is_off(self):
        self.write_settings({})
        self.assertDenied(self.bash("ls"), "sandbox-off")
        self.assertIsNone(self.decide("Read", {"file_path": os.path.join(self.proj, "x")}))

    def test_a_project_that_disables_the_sandbox_loses_the_shell_not_the_policy(self):
        os.makedirs(os.path.join(self.proj, ".claude"), exist_ok=True)
        with open(os.path.join(self.proj, ".claude", "settings.json"), "w") as f:
            json.dump({"sandbox": {"enabled": False}}, f)
        self.assertDenied(self.bash("ls"), "sandbox-off")

    def test_project_settings_are_found_from_a_subdirectory(self):
        self.write_settings({})
        os.makedirs(os.path.join(self.proj, ".claude"), exist_ok=True)
        with open(os.path.join(self.proj, ".claude", "settings.json"), "w") as f:
            json.dump({"sandbox": {"enabled": True, "failIfUnavailable": True}}, f)
        self.assertIsNone(self.bash("ls", cwd=os.path.join(self.proj, "src")))

    def test_an_empty_project_settings_file_is_no_settings(self):
        # The sandbox's /dev/null mount over a missing .claude/settings.json leaves an empty
        # file while a command runs; a live Grep failed closed on it (2026-09-30).
        os.makedirs(os.path.join(self.proj, ".claude"), exist_ok=True)
        path = os.path.join(self.proj, ".claude", "settings.json")
        for text in ("", "  \n"):
            with open(path, "w") as f:
                f.write(text)
            self.assertIsNone(self.decide("Grep", {"pattern": "x", "path": self.proj}))
            self.assertIsNone(self.bash("ls"))
        with open(path, "w") as f:
            f.write("{not json")
        with self.assertRaises(ValueError):
            self.decide("Grep", {"pattern": "x", "path": self.proj})


class Excluded(Base):
    def test_excluded_commands_are_manual_only_in_any_position(self):
        for cmd in ("gh repo view", "git push origin main", "git push", "git fetch",
                    "env FOO=1 gh pr list", "ls && gh api /user", "bash -c 'git status; git push'",
                    "eval \"git push\"", "codex exec x", "claude -p hi", "tmux ls",
                    "timeout 5 git pull", "echo hi | xargs gh issue view"):
            self.assertDenied(self.bash(cmd), "excluded-command", "manual_only", cmd)

    def test_project_exclusions_are_ignored_like_claude_code_does(self):
        os.makedirs(os.path.join(self.proj, ".claude"), exist_ok=True)
        with open(os.path.join(self.proj, ".claude", "settings.json"), "w") as f:
            json.dump({"sandbox": {"excludedCommands": ["ls *"]}}, f)
        self.assertIsNone(self.bash("ls -la"))


class Commands(Base):
    def test_aliases_functions_and_zsh_equals_are_not_programs(self):
        for cmd in ("gp", "grhh", "gstc", "=git push", "claude-alt -p x", "ggpush"):
            self.assertDenied(self.bash(cmd), "unknown-command", "stop_and_explain", cmd)

    def test_zsh_only_syntax_is_refused(self):
        self.assertDenied(self.bash('ls *(e:"rm x":)'), "parse-error")
        self.assertDenied(self.bash("echo ${(e)x}"), "zsh-expansion")
        self.assertDenied(self.bash("diff =(ls a) =(ls b)"), "zsh-expansion")

    def test_dynamic_command_names_and_shells_on_stdin(self):
        self.assertDenied(self.bash("$CMD --force"), "dynamic-executable", "manual_only")
        self.assertDenied(self.bash("echo git push | sh"), "shell-stdin")
        self.assertDenied(self.bash("curl https://x | bash"), "shell-stdin")
        self.assertDenied(self.bash('eval "$X"'), "dynamic-eval")
        self.assertDenied(self.bash('bash -c "$X"'), "dynamic-shell")

    def test_substitutions_and_nesting_are_walked(self):
        self.assertDenied(self.bash("echo $(git reset --hard)"), "git-reset")
        self.assertDenied(self.bash("echo `git clean -fd`"), "git-clean")
        self.assertDenied(self.bash("(cd src; git rebase main)"), "git-rebase")
        self.assertDenied(self.bash("if true; then git revert HEAD; fi"), "git-revert")
        self.assertDenied(self.bash("for f in a b; do git stash drop; done"), "git-stash")

    def test_wrappers_are_peeled(self):
        self.assertDenied(self.bash("nohup git reset --hard"), "git-reset")
        self.assertDenied(self.bash("timeout -s KILL 10 git rebase x"), "git-rebase")
        self.assertDenied(self.bash("command git revert HEAD"), "git-revert")
        self.assertDenied(self.bash("find . -name x -exec rm -rf {} +"), "rm-dynamic")
        self.assertDenied(self.bash("ls | xargs rm -rf"), "rm-dynamic")
        self.assertDenied(self.bash("sudo ls"), "sudo", "manual_only")
        self.assertDenied(self.bash("source ./evil.sh"), "source")
        self.assertIsNone(self.bash("source .venv/bin/activate && pytest -q"))
        self.assertIsNone(self.bash("command -v git"))

    def test_environment_that_changes_what_runs(self):
        for cmd in ("GIT_EXTERNAL_DIFF=x git diff", "LD_PRELOAD=/x.so ls", "PAGER=less git log",
                    "env GIT_SSH_COMMAND=x git status", "BASH_ENV=/x bash -c ls"):
            self.assertDenied(self.bash(cmd), "env-assignment", msg=cmd)
        self.assertIsNone(self.bash("GIT_PAGER=cat git log -3"))
        self.assertIsNone(self.bash("FOO=1 npm test"))

    def test_ordinary_work_passes(self):
        for cmd in ("ls -la src", "npm test 2>&1 | tail -20", "git status", "git diff --stat",
                    "git add -A && git commit -m 'x'", "git log --oneline -5 > /dev/null",
                    "python3 -m pytest -q", "git checkout -b feat/x", "git switch -c feat/y",
                    "git restore --staged src/a.py", "git branch feat/z", "git stash push -m wip",
                    "git stash apply", "git tag v1", "git merge feat", "rm -rf build dist",
                    "rm notes.txt", "mkdir -p src/pkg && touch src/pkg/__init__.py",
                    "curl -s https://api.github.com/zen", "curl -fsSL -o out.json https://x/y",
                    "git clone --depth 1 https://github.com/a/b vendor/b", "cat <<EOF\nhi\nEOF"):
            self.assertIsNone(self.bash(cmd), cmd)


class Git(Base):
    def test_denied_subcommands_and_intents(self):
        for cmd, rule, intent in (
                ("git reset --hard HEAD~1", "git-reset", "use_alternative"),
                ("git reset HEAD file", "git-reset", "use_alternative"),
                ("git clean -fdx", "git-clean", "use_alternative"),
                ("git rebase -i main", "git-rebase", "manual_only"),
                ("git revert HEAD", "git-revert", "manual_only"),
                ("git filter-branch x", "git-filter-branch", "manual_only"),
                ("git update-ref -d refs/heads/x", "git-update-ref", "manual_only"),
                ("git -C src push", "git-push", "manual_only"),
                ("git checkout -- file", "git-checkout", "use_alternative"),
                ("git checkout main", "git-checkout", "use_alternative"),
                ("git checkout -B main", "git-checkout", "use_alternative"),
                ("git switch main", "git-switch", "use_alternative"),
                ("git switch -C main", "git-switch", "use_alternative"),
                ("git restore file", "git-restore", "use_alternative"),
                ("git restore --staged --worktree file", "git-restore", "use_alternative"),
                ("git branch -D old", "git-branch", "use_alternative"),
                ("git branch -m a b", "git-branch", "use_alternative"),
                ("git stash drop", "git-stash", "use_alternative"),
                ("git stash clear", "git-stash", "use_alternative"),
                ("git stash pop", "git-stash", "use_alternative"),
                ("git worktree remove x", "git-worktree", "manual_only"),
                ("git tag -d v1", "git-tag", "manual_only"),
                ("git remote add o url", "git-remote", "manual_only"),
                ("git config user.email x@y", "git-config", "manual_only"),
                ("git reflog expire --all", "git-reflog", "manual_only"),
                ("git gc --prune=now", "git-gc", "manual_only"),
                ("git merge --abort", "git-abort", "use_alternative"),
                ("git rm -rf src", "git-rm-force", "use_alternative"),
                ("git submodule update --init", "git-submodule", "manual_only"),
                ("git difftool", "git-tool", "manual_only"),
                ("git commit --no-verify -m x", "git-flag", "use_alternative"),
                ("git log --output=/tmp/x", "git-flag", "use_alternative"),
                ("git diff --ext-diff", "git-flag", "use_alternative"),
                ("git grep -Ovim foo", "git-flag", "use_alternative"),
                ("git clone ext::sh evil", "git-transport", "hard_stop"),
                ("git -c core.pager=x log", "git-config-override", "use_alternative"),
                ("git frob", "git-unknown", "stop_and_explain")):
            self.assertDenied(self.bash(cmd), rule, intent, cmd)

    def test_read_forms_pass(self):
        for cmd in ("git remote -v", "git remote get-url origin", "git config --get user.name",
                    "git config user.name", "git branch -a", "git worktree list",
                    "git reflog", "git submodule status", "git tag"):
            self.assertIsNone(self.bash(cmd), cmd)


class Rm(Base):
    def test_rm_rules(self):
        for cmd, rule, intent in (
                ("rm -rf /", "rm-root-or-home", "hard_stop"),
                ("rm -rf ~", "rm-root-or-home", "hard_stop"),
                ("rm -rf $HOME", "rm-root-or-home", "hard_stop"),
                ("rm -rf .git", "rm-git-metadata", "hard_stop"),
                ("rm .git/index", "rm-git-metadata", "hard_stop"),
                ("rm -rf ~/elsewhere", "rm-outside-root", "scope_down"),
                ("rm -r ../other", "rm-outside-root", "scope_down"),
                ("rm -rf $DIR", "rm-dynamic", "scope_down"),
                ("rm -rf build/*", "rm-dynamic", "scope_down"),
                ("find ~/other -delete", "rm-outside-root", "scope_down")):
            self.assertDenied(self.bash(cmd), rule, intent, cmd)

    def test_rm_inside_root_temp_and_allow_write_passes(self):
        for cmd in ("rm -rf build", "rm -rf /tmp/claude-%d/x" % os.getuid(), "rm -f *.pyc",
                    "rm -rf ~/.cache/uv/some-entry", "find build -name '*.o' -delete"):
            self.assertIsNone(self.bash(cmd), cmd)


class Network(Base):
    def test_curl_and_wget_only_read(self):
        for cmd in ("curl -X POST https://x", "curl --request=DELETE https://x", "curl -XPUT https://x",
                    "curl -d a=b https://x", "curl -sd @f https://x", "curl --data-binary @f https://x",
                    "curl -F f=@x https://x", "curl -T f https://x", "curl -K cfg", "curl --json {} https://x",
                    "wget --post-data=a https://x", "wget --method=PUT https://x"):
            self.assertDenied(self.bash(cmd), "http-write", "manual_only", cmd)
        for cmd in ("curl -s https://x", "curl -I https://x", "curl -X GET https://x",
                    "curl -sSfL https://x", "wget -qO- https://x"):
            self.assertIsNone(self.bash(cmd), cmd)


class Files(Base):
    def test_protected_writes_are_hard_stops(self):
        for path in ("~/.claude/settings.json", "~/.claude/agents/x.md", "~/.zshrc", "~/.gitconfig",
                     "~/dotclaude/hooks/x.sh", "~/dotclaude/skills/delegation/policy.toml",
                     "~/.ssh/config", "~/.local/bin/git"):
            p = path.replace("~", self.home)
            self.assertDenied(self.decide("Write", {"file_path": p, "content": ""}),
                              "protected-path", "hard_stop", path)
            self.assertDenied(self.bash(f"echo x > {path}"), "protected-path", msg=path)
            self.assertDenied(self.bash(f"cp a {path}"), "protected-path", msg=path)
        for rel in (".claude/settings.local.json", ".mcp.json", ".git/hooks/pre-commit",
                    ".git/config"):
            p = os.path.join(self.proj, rel)
            self.assertDenied(self.decide("Edit", {"file_path": p}), "protected-path", msg=rel)
            self.assertDenied(self.bash(f"tee {rel} < x"), "protected-path", msg=rel)
        self.assertDenied(self.bash("sed -i s/a/b/ .claude/settings.json"), "protected-path")

    def test_worktrees_under_dot_claude_are_not_protected(self):
        p = os.path.join(self.proj, ".claude", "worktrees", "agent-w1", "src.py")
        self.assertIsNone(self.decide("Write", {"file_path": p, "content": ""}))

    def test_a_symlink_into_a_protected_path_counts(self):
        os.makedirs(os.path.join(self.home, ".claude", "hooks"))
        link = os.path.join(self.proj, "innocent")
        os.symlink(os.path.join(self.home, ".claude", "hooks"), link)
        self.assertDenied(self.decide("Write", {"file_path": os.path.join(link, "x.sh")}),
                          "protected-path")
        self.assertDenied(self.bash("echo x > innocent/x.sh"), "protected-path")

    def test_credential_reads_are_hard_stops(self):
        for path in ("~/.config/gh/hosts.yml", "~/.ssh/id_ed25519", "~/.aws/credentials",
                     "~/.claude/.credentials.json", "~/.google_workspace_mcp/personal/token.json",
                     "~/.netrc"):
            p = path.replace("~", self.home)
            self.assertDenied(self.decide("Read", {"file_path": p}), "credential-read", "hard_stop",
                              path)
        self.assertDenied(self.decide("Grep", {"pattern": "token", "path": self.home + "/.ssh"}),
                          "credential-read")
        self.assertDenied(self.decide("Glob", {"pattern": self.home + "/.aws/*"}), "credential-read")
        self.assertIsNone(self.decide("Read", {"file_path": os.path.join(self.proj, "README")}))
        self.assertIsNone(self.decide("Read", {"file_path": self.home + "/.workspace-mcp/attachments/a.pdf"}))

    def test_the_secrets_file_and_proc_are_credential_reads(self):
        self.assertDenied(self.decide("Read", {"file_path": self.home + "/.secrets.env"}),
                          "credential-read", "hard_stop")
        for path in ("/proc/self/environ", "/proc/1/environ"):
            self.assertDenied(self.decide("Grep", {"pattern": "TOKEN=", "path": path}),
                              "credential-read", msg=path)
        self.assertDenied(self.decide("Glob", {"pattern": "/proc/*/environ"}), "credential-read")

    def test_grep_rooted_above_a_credential_path_is_scoped_down(self):
        os.makedirs(os.path.join(self.home, ".ssh"))
        for path in (self.home, "~", "/"):
            self.assertDenied(self.decide("Grep", {"pattern": "ghp_", "path": path}),
                              "credential-search", "scope_down", path)
        self.assertDenied(self.decide("Grep", {"pattern": "ghp_"}, cwd=self.home),
                          "credential-search")  # no path: Grep searches the cwd
        self.assertIsNone(self.decide("Grep", {"pattern": "ghp_", "path": self.proj}))
        self.assertIsNone(self.decide("Grep", {"pattern": "ghp_"}))
        self.assertIsNone(self.decide("Glob", {"pattern": "*", "path": self.home}))

    def test_a_missing_credential_path_does_not_block_its_parent(self):
        os.makedirs(os.path.join(self.home, ".config", "other"))
        self.assertIsNone(self.decide("Grep", {"pattern": "x", "path": self.home + "/.config"}))
        os.makedirs(os.path.join(self.home, ".config", "gh"))
        self.assertDenied(self.decide("Grep", {"pattern": "x", "path": self.home + "/.config"}),
                          "credential-search")

    def test_writes_outside_the_repo_are_left_to_the_sandbox_for_non_writers(self):
        self.assertIsNone(self.decide("Write", {"file_path": self.home + "/vault/notes.md"}))


class Writer(Base):
    def setUp(self):
        super().setUp()
        self.meta("w1", agentType="writer", worktreePath=self.wt, spawnedWithWorktree=True)

    def w(self, tool, ti):
        return self.decide(tool, ti, atype="writer", cwd=self.wt, aid="w1")

    def wb(self, cmd):
        return self.w("Bash", {"command": cmd})

    def test_writes_into_the_main_checkout_are_denied(self):
        for cmd in ("echo x > ../../../escape.txt", f"echo x > {self.proj}/src/a.py",
                    "cd ../../.. && touch x", f"git -C {self.proj} commit -m x",
                    f"cp a {self.proj}/src/", f"mv a.py {self.proj}/", f"rm -r {self.proj}/src"):
            self.assertDenied(self.wb(cmd), msg=cmd)
        self.assertDenied(self.w("Write", {"file_path": self.proj + "/src/a.py"}), "worktree-root",
                          "scope_down")
        self.assertDenied(self.w("Write", {"file_path": self.home + "/vault/x.md"}), "worktree-root")

    def test_work_inside_the_worktree_passes(self):
        for cmd in ("echo ok > result.txt && git add -A && git commit -m r", "mkdir -p src && cd src",
                    "uv pip install requests", f"cat {self.proj}/src/a.py", "cat ../../../README",
                    "rm -rf build", "echo x > /tmp/claude-%d/scratch.txt" % os.getuid()):
            self.assertIsNone(self.wb(cmd), cmd)
        self.assertIsNone(self.w("Write", {"file_path": self.wt + "/src/a.py"}))

    def test_root_comes_from_meta_json_even_after_cd(self):
        self.assertIsNone(self.decide("Bash", {"command": "touch x.txt"}, atype="writer",
                                      cwd=os.path.join(self.wt, "sub"), aid="w1"))

    def test_any_isolated_agent_is_confined_not_just_writers(self):
        self.meta("g1", agentType="general-purpose", worktreePath=self.wt)
        d = self.decide("Bash", {"command": "echo x > ../../../escape.txt"},
                        atype="general-purpose", cwd=self.wt, aid="g1")
        self.assertDenied(d, "worktree-root", "scope_down")

    def test_cwd_fallback_and_no_worktree_at_all(self):
        self.assertIsNone(self.decide("Bash", {"command": "touch x"}, atype="writer", cwd=self.wt,
                                      aid="nometa"))
        self.assertDenied(self.decide("Bash", {"command": "ls"}, atype="writer", cwd=self.proj,
                                      aid="nometa"), "worktree-root", "stop_and_explain")

    def test_a_nested_worktree_resolves_to_the_innermost(self):
        # A lead session that itself runs in a worktree puts its agents' worktrees inside it.
        outer = os.path.join(self.proj, ".claude", "worktrees", "outer")
        inner = os.path.join(outer, ".claude", "worktrees", "agent-w2")
        os.makedirs(inner)
        a = sp.Analyzer(self.ev("Bash", {"command": "ls"}, atype="writer", cwd=inner,
                                aid="nometa"), POLICY, home=self.home)
        self.assertEqual((a.worktree, a.main_root), (inner, outer))
        self.assertDenied(self.decide("Bash", {"command": "echo x > ../escape.txt"},
                                      atype="writer", cwd=inner, aid="nometa"), "worktree-root")


class Researcher(Base):
    def r(self, cmd):
        return self.bash(cmd, atype="researcher")

    def test_allowlisted_reads_pass(self):
        for cmd in ("git log --oneline -5", "git show HEAD --stat", "git blame -L 1,5 f",
                    "grep -rn foo . | head -20", "find . -name '*.py' | wc -l", "sed -n '1,5p' f",
                    "cat f 2>/dev/null", "git branch -a", "git tag --list 'v*'", "git remote -v",
                    "git config --get user.name", "git stash list", "curl -s https://api.github.com/zen",
                    "wget -qO- https://x", "gh-public /repos/a/b", "ls -la", "cargo --version",
                    "git clone --depth 1 https://github.com/a/b /tmp/claude-%d/r/b" % os.getuid(),
                    "diff a b", "sort f | uniq -c"):
            self.assertIsNone(self.r(cmd), cmd)

    def test_everything_else_is_denied(self):
        for cmd, rule in (
                ("touch x", "researcher-program"), ("python3 -c 1", "researcher-program"),
                ("node -e 1", "researcher-program"), ("awk '{print}' f", "researcher-program"),
                ("bash script.sh", "researcher-program"), ("./run.sh --help", "researcher-program"),
                ("git log > out.txt", "researcher-write"), ("echo x >> f", "researcher-write"),
                ("curl -s https://x -o f", "researcher-write"), ("curl -sO https://x/f", "researcher-write"),
                ("wget https://x", "researcher-write"),
                ("git commit -m x", "researcher-git"), ("git branch -D x", "researcher-git"),
                ("git branch newb", "researcher-git"), ("git tag v2", "researcher-git"),
                ("git stash push", "researcher-git"), ("git config user.name x", "researcher-git"),
                ("git clone https://github.com/a/b b", "researcher-clone"),
                ("git clone git@github.com:a/b /tmp/claude-%d/b" % os.getuid(), "researcher-clone"),
                ("sed -i s/a/b/ f", "researcher-flag"), ("sed 's/a/b/w out' f", "researcher-flag"),
                ("sed -e '1e ls' f", "researcher-flag"),
                ("find . -name x -delete", "researcher-flag"), ("find . -exec rm {} ;", "researcher-flag"),
                ("find . -fprint out", "researcher-flag"), ("grep --filter=x foo .", "researcher-flag"),
                ("grep --pre=cat foo", "researcher-flag"), ("sort -o out f", "researcher-flag"),
                ("sort -oout f", "researcher-flag"), ("tree -o out", "researcher-flag"),
                ("uniq in out", "researcher-flag"), ("LD_PRELOAD=x ls", "env-assignment"),
                ("FOO=1 ls", "env-assignment")):
            self.assertDenied(self.r(cmd), rule, msg=cmd)


class Mcp(Base):
    def test_read_tools_pass_and_everything_else_is_manual_only(self):
        for tool in ("mcp__gw-personal__search_gmail_messages", "mcp__gw-aikido__get_gmail_thread_content",
                     "mcp__notion__notion-fetch", "mcp__notion__notion-search",
                     "mcp__notion-write__API-retrieve-a-page", "mcp__notion-write__API-post-search",
                     "mcp__sender__list_subscribers", "mcp__plugin_context7_context7__query-docs",
                     "mcp__chrome-devtools__take_screenshot"):
            self.assertIsNone(self.decide(tool, {}), tool)
        for tool in ("mcp__gw-personal__manage_event", "mcp__gw-personal__send_gmail_message",
                     "mcp__gw-aikido__create_form", "mcp__gw-aikido__batch_update_form",
                     "mcp__notion-write__API-post-page", "mcp__notion-write__API-patch-page",
                     "mcp__notion__notion-update-page", "mcp__sender__create_email_campaign",
                     "mcp__chrome-devtools__navigate_page", "mcp__chrome-devtools__click",
                     "mcp__brand-new__anything"):
            self.assertDenied(self.decide(tool, {}), "mcp-write", "manual_only", tool)

    def test_non_policed_tools_pass(self):
        for tool in ("SubagentHandback", "SendMessage", "WebFetch", "ToolSearch", "TaskCreate"):
            self.assertIsNone(self.decide(tool, {"x": 1}), tool)


class ReviewFindings(Base):
    """Bypasses found in the 2026-09-30 review, pinned so they stay closed."""

    def test_env_split_string_in_every_form(self):
        for cmd, rule in (("env -S'git reset --hard'", "git-reset"),
                          ("env -S 'git reset --hard'", "git-reset"),
                          ("env --split-string='git clean -fd'", "git-clean"),
                          ("env --split-string 'git clean -fd'", "git-clean"),
                          ("env -iS'git reset --hard'", "git-reset"),
                          ("env -i -S'gh repo view'", "excluded-command"),
                          ('env -S"$X"', "dynamic-shell"),
                          ("env --frobnicate git status", "unknown-option"),
                          ("env -Z git status", "unknown-option")):
            self.assertDenied(self.bash(cmd), rule, msg=cmd)
        for cmd in ("env", "env -i PATH=/usr/bin ls", "env -u FOO ls", "env -C src ls",
                    "env -uFOO ls", "env -- ls"):
            self.assertIsNone(self.bash(cmd), cmd)

    def test_ampersand_redirects_write_their_target(self):
        self.assertDenied(self.bash("git log >& out.txt", atype="researcher"), "researcher-write")
        self.assertDenied(self.bash("git log 1> 123", atype="researcher"), "researcher-write")
        self.assertDenied(self.bash("echo x >& ~/.claude/settings.json"), "protected-path")
        self.meta("w1", agentType="writer", worktreePath=self.wt)
        self.assertDenied(self.decide("Bash", {"command": "echo x >& ../../../main.py"},
                                      atype="writer", cwd=self.wt, aid="w1"), "worktree-root")
        for cmd in ("npm test 2>&1 | tail", "echo err >&2", "ls 2>&-", "git log 2>& 1"):
            self.assertIsNone(self.bash(cmd), cmd)
        self.assertIsNone(self.bash("git log 2>&1 | head", atype="researcher"))

    def test_sed_w_targets_and_e_commands_on_the_default_path(self):
        self.meta("w1", agentType="writer", worktreePath=self.wt)
        for cmd in ("sed -n 's/x/y/w ../../../main.py' f", "sed -e '1w ../../../main.py' f",
                    "sed '/x/W ../../../main.py' f"):
            self.assertDenied(self.decide("Bash", {"command": cmd}, atype="writer", cwd=self.wt,
                                          aid="w1"), "worktree-root", msg=cmd)
        self.assertDenied(self.bash("sed 's/a/b/w ~/.zshrc' f"), "protected-path")
        self.assertDenied(self.bash("sed '1e rm -rf x' f"), "sed-exec")
        self.assertIsNone(self.bash("sed -n '1,5p' f"))
        self.assertIsNone(self.bash("sed 's/a/b/w notes.txt' f"))

    def test_a_writer_without_a_worktree_can_still_hand_back(self):
        self.assertIsNone(self.decide("SubagentHandback", {"message": "report"}, atype="writer",
                                      cwd=self.proj, aid="nometa"))


class PolicyFile(unittest.TestCase):
    def test_every_denied_git_subcommand_is_known_and_has_a_real_intent(self):
        for sub, intent in POLICY["git"]["denied"].items():
            self.assertIn(sub, POLICY["git"]["known"])
            self.assertIn(intent, sp.INTENTS)

    def test_every_intent_has_a_footer(self):
        self.assertEqual(set(POLICY["intents"]), set(sp.INTENTS))

    def test_researcher_programs_have_no_writers_or_interpreters(self):
        for p in ("python3", "python", "node", "awk", "perl", "ruby", "bash", "sh", "tee", "cp",
                  "mv", "rm", "touch", "gh"):
            self.assertNotIn(p, POLICY["researcher"]["programs"])


if __name__ == "__main__":
    unittest.main()
