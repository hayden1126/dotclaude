"""hooks/blank-display.sh: a SessionStart hook that blanks DISPLAY and WAYLAND_DISPLAY for Bash
in a repo that opts in with `git config dotclaude.blankDisplay true` (stdlib only).

Each test runs the shim with bash on a JSON payload, the way Claude Code does, against real git
in temp repos. The env starts clean of every CLAUDE* and GIT_* var, and HOME, XDG_CONFIG_HOME and
XDG_STATE_HOME point into the temp dir, so neither the session running the tests nor Hayden's own
git config can opt a repo in or out."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "blank-display.sh")

LINES = "export DISPLAY=\nexport WAYLAND_DISPLAY=\nunset WAYLAND_SOCKET\n"
CONTEXT = {"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": (
        "No display for Bash in this repo (git config dotclaude.blankDisplay): DISPLAY and "
        "WAYLAND_DISPLAY are empty. Don't set DISPLAY=:0. For a visible browser, run "
        "chrome-bg run -- <cmd> with the sandbox off.")}}


class BlankDisplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        for d in ("home", "config", "state", "bin"):
            os.mkdir(os.path.join(self.tmp, d))
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "GIT_"))}
        self.env.update(HOME=os.path.join(self.tmp, "home"),
                        XDG_CONFIG_HOME=os.path.join(self.tmp, "config"),
                        XDG_STATE_HOME=os.path.join(self.tmp, "state"))
        self.envfile = os.path.join(self.tmp, "session-env.sh")
        self.logfile = os.path.join(self.tmp, "state", "dotclaude", "blank-display.log")
        self.opted = self.repo("opted", opt="true")
        self.plain = self.repo("plain")

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", cwd, *args], env=self.env, capture_output=True,
                              text=True, check=True).stdout

    def repo(self, name, opt=None):
        """A repo with one commit (so `git worktree add` works); opt sets the key locally."""
        path = os.path.join(self.tmp, name)
        subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", path],
                       env=self.env, check=True)
        self.git(path, "config", "user.name", "Test")
        self.git(path, "config", "user.email", "test@example.com")
        self.git(path, "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "init")
        if opt is not None:
            self.git(path, "config", "dotclaude.blankDisplay", opt)
        return path

    def run_hook(self, payload, env_file=True, **env):
        """Run the shim on payload (a dict is sent as JSON, a str as is); return stdout."""
        env = {**self.env, **env}
        if env_file:
            env["CLAUDE_ENV_FILE"] = self.envfile
        if isinstance(payload, dict):
            payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup",
                                  "session_id": "abcdef12-0000", **payload})
        p = subprocess.run(["bash", HOOK], input=payload, capture_output=True, text=True,
                           timeout=10, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        return p.stdout

    def env_text(self):
        with open(self.envfile) as f:
            return f.read()

    def logged(self):
        try:
            with open(self.logfile) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def assertBlanked(self, out):
        self.assertEqual(json.loads(out), CONTEXT)
        self.assertEqual(self.env_text(), LINES)

    def assertUntouched(self, out):
        self.assertEqual(out, "")
        self.assertFalse(os.path.exists(self.envfile))

    # An opted repo: every way into it blanks.

    def test_an_opted_repo_appends_the_three_lines_and_prints_the_context(self):
        self.assertBlanked(self.run_hook({"cwd": self.opted}))
        self.assertEqual(self.logged(), "")

    def test_a_linked_worktree_of_an_opted_repo_blanks(self):
        wt = os.path.join(self.tmp, "wt")
        self.git(self.opted, "worktree", "add", "-q", "--detach", wt)
        self.assertBlanked(self.run_hook({"cwd": wt}))

    def test_a_worktree_added_after_the_opt_in_is_covered_and_one_before_it_too(self):
        early = os.path.join(self.tmp, "early")
        self.git(self.plain, "worktree", "add", "-q", "--detach", early)
        self.git(self.plain, "config", "dotclaude.blankDisplay", "true")
        late = os.path.join(self.tmp, "late")
        self.git(self.plain, "worktree", "add", "-q", "--detach", late)
        for cwd in (early, late):
            with self.subTest(cwd=cwd):
                if os.path.exists(self.envfile):
                    os.remove(self.envfile)
                self.assertBlanked(self.run_hook({"cwd": cwd}))

    def test_a_subdir_of_an_opted_repo_blanks(self):
        sub = os.path.join(self.opted, "a", "b")
        os.makedirs(sub)
        self.assertBlanked(self.run_hook({"cwd": sub}))

    def test_a_subagent_payload_in_an_opted_repo_still_blanks(self):
        self.assertBlanked(self.run_hook({"cwd": self.opted, "agent_id": "a1",
                                          "agent_type": "writer"}))

    def test_git_bool_spellings_of_true_opt_in(self):
        for value in ("yes", "on", "1"):
            with self.subTest(value=value):
                if os.path.exists(self.envfile):
                    os.remove(self.envfile)
                self.git(self.plain, "config", "dotclaude.blankDisplay", value)
                self.assertBlanked(self.run_hook({"cwd": self.plain}))

    # The env file: appended, never rewritten, and it does what it says.

    def test_the_lines_append_after_what_other_hooks_wrote(self):
        with open(self.envfile, "w") as f:
            f.write("export FOO=1\n")
        self.run_hook({"cwd": self.opted})
        self.assertEqual(self.env_text(), "export FOO=1\n" + LINES)

    def test_an_unterminated_last_line_gets_its_newline_first(self):
        with open(self.envfile, "w") as f:
            f.write("export FOO=1")
        self.run_hook({"cwd": self.opted})
        self.assertEqual(self.env_text(), "export FOO=1\n" + LINES)

    def test_a_repeat_on_resume_appends_again_harmlessly(self):
        self.run_hook({"cwd": self.opted})
        out = self.run_hook({"cwd": self.opted, "source": "resume"})
        self.assertEqual(json.loads(out), CONTEXT)
        self.assertEqual(self.env_text(), LINES * 2)

    def test_sourcing_the_file_leaves_the_vars_set_but_empty(self):
        """Empty, not unset: an unset DISPLAY or WAYLAND_DISPLAY falls back to the default
        sockets (/tmp/.X11-unix/X0, $XDG_RUNTIME_DIR/wayland-0)."""
        self.run_hook({"cwd": self.opted})
        self.run_hook({"cwd": self.opted, "source": "compact"})
        probe = ('. "$1"; printf "%s|%s|%s|%s|%s" "${DISPLAY+set}" "$DISPLAY" '
                 '"${WAYLAND_DISPLAY+set}" "$WAYLAND_DISPLAY" "${WAYLAND_SOCKET+set}"')
        p = subprocess.run(["bash", "-c", probe, "probe", self.envfile], capture_output=True,
                           text=True, check=True, env={**self.env, "DISPLAY": ":0",
                                                       "WAYLAND_DISPLAY": "wayland-0",
                                                       "WAYLAND_SOCKET": "3"})
        self.assertEqual(p.stdout, "set||set||")

    # Not opted in: nothing printed, nothing written.

    def test_a_repo_that_did_not_opt_in_is_untouched(self):
        self.assertUntouched(self.run_hook({"cwd": self.plain}))
        self.assertEqual(self.logged(), "")

    def test_false_is_untouched(self):
        self.git(self.plain, "config", "dotclaude.blankDisplay", "false")
        self.assertUntouched(self.run_hook({"cwd": self.plain}))

    def test_a_value_that_is_not_a_bool_is_untouched(self):
        self.git(self.plain, "config", "dotclaude.blankDisplay", "maybe")
        self.assertUntouched(self.run_hook({"cwd": self.plain}))

    def test_global_config_never_opts_a_repo_in(self):
        self.git(self.plain, "config", "--global", "dotclaude.blankDisplay", "true")
        os.makedirs(os.path.join(self.tmp, "config", "git"))
        with open(os.path.join(self.tmp, "config", "git", "config"), "w") as f:
            f.write("[dotclaude]\n\tblankDisplay = true\n")
        self.assertEqual(self.git(self.plain, "config", "--type=bool", "--get",
                                  "dotclaude.blankDisplay"), "true\n")
        self.assertUntouched(self.run_hook({"cwd": self.plain}))

    def test_a_dir_outside_any_repo_is_untouched(self):
        outside = os.path.join(self.tmp, "home")
        self.assertUntouched(self.run_hook({"cwd": outside}))

    def test_the_payload_cwd_decides_not_the_hooks_git_env(self):
        """GIT_DIR names the opted repo; were it passed to git, the plain cwd would blank."""
        gd = os.path.join(self.opted, ".git")
        self.assertUntouched(self.run_hook({"cwd": self.plain}, GIT_DIR=gd,
                                           GIT_WORK_TREE=self.opted))
        self.assertUntouched(self.run_hook({"cwd": self.plain}, GIT_CONFIG_COUNT="1",
                                           GIT_CONFIG_KEY_0="dotclaude.blankDisplay",
                                           GIT_CONFIG_VALUE_0="true"))

    def test_a_git_that_hangs_times_out_and_does_nothing(self):
        stub = os.path.join(self.tmp, "bin", "git")
        with open(stub, "w") as f:
            f.write("#!/usr/bin/env bash\nexec sleep 8\n")
        os.chmod(stub, 0o755)
        path = os.path.join(self.tmp, "bin") + os.pathsep + self.env["PATH"]
        start = time.monotonic()
        self.assertUntouched(self.run_hook({"cwd": self.opted}, PATH=path))
        self.assertLess(time.monotonic() - start, 5)
        self.assertIn("timeout", self.logged().lower())

    # Opted in but nowhere to write: log it, print nothing.

    def test_no_env_file_is_logged_and_prints_nothing(self):
        self.assertEqual(self.run_hook({"cwd": self.opted}, env_file=False), "")
        self.assertIn("CLAUDE_ENV_FILE", self.logged())

    def test_an_empty_env_file_var_is_logged_and_prints_nothing(self):
        self.assertEqual(self.run_hook({"cwd": self.opted}, env_file=False, CLAUDE_ENV_FILE=""),
                         "")
        self.assertIn("CLAUDE_ENV_FILE", self.logged())

    def test_an_env_file_that_cannot_be_written_fails_open_silently(self):
        self.envfile = os.path.join(self.tmp, "missing-dir", "session-env.sh")
        self.assertEqual(self.run_hook({"cwd": self.opted}), "")
        self.assertIn("error", self.logged())

    # Bad payloads fail open.

    def test_bad_payloads_are_logged_and_do_nothing(self):
        for payload in ("not json", "", "[]", json.dumps({"hook_event_name": "SessionStart"}),
                        json.dumps({"cwd": 7}),
                        json.dumps({"cwd": os.path.join(self.tmp, "gone")})):
            with self.subTest(payload=payload):
                os.makedirs(os.path.dirname(self.logfile), exist_ok=True)
                open(self.logfile, "w").close()
                self.assertUntouched(self.run_hook(payload))
                self.assertNotEqual(self.logged(), "")


if __name__ == "__main__":
    unittest.main()
