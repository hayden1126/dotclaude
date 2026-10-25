"""subagent-policy: the gate, every rule and intent, and the fail-closed paths.

Each test runs against a temporary home whose user settings carry this repo's baseline
`sandbox` block, so the excluded-command rules are the ones that ship. Its state dir (the
liveness index the deadline reads) is in that home too."""
import contextlib
import datetime
import io
import json
import os
import random
import re
import shutil
import signal
import subprocess
import tempfile
import unittest
from unittest import mock

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
    would pass as a temp write. There the fake homes go in the repo instead (the gitignored
    .tmp/ at its root), which a sandboxed session rooted in the repo can write; not beside
    this file, since tests/ is write-protected (the canary runs it outside the sandbox). A
    checkout that is itself a Claude worktree can't host them: the policy would read every
    fake path as inside that worktree, and the one other writable place, the git common dir,
    trips rm-git-metadata."""
    base = os.path.realpath(tempfile.gettempdir())
    roots = [os.path.realpath(sp.expand(r, os.path.expanduser("~")))
             for r in POLICY["rm"]["temp_roots"]]
    if not any(sp.under(base, r) for r in roots):
        return None
    local = os.path.join(os.path.realpath(REPO), ".tmp", "policy-tests")
    if "/.claude/worktrees/" in local:
        raise RuntimeError("sandboxed in a checkout under .claude/worktrees/, the policy tests "
                           "have nowhere clean to build their fake homes; run this suite with "
                           "the sandbox off, or from a checkout outside .claude/worktrees/")
    os.makedirs(local, exist_ok=True)
    return local


TEST_TMP = _test_tmp_dir()


class Base(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)  # the settings and sessions live in the fake home
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
        bindir = os.path.join(self.home, "bin")  # tools as setup.sh links them, and a script
        os.makedirs(bindir)
        for exe in (os.path.join(bindir, "gh-public"), os.path.join(bindir, "pass-respawn"),
                    os.path.join(bindir, "ed-pull"), os.path.join(self.proj, "run.sh")):
            with open(exe, "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(exe, 0o755)
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = bindir + ":" + self.old_path
        self.state = os.path.join(self.home, "state")
        self.old_state = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.state

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        if self.old_state is None:
            os.environ.pop("XDG_STATE_HOME")
        else:
            os.environ["XDG_STATE_HOME"] = self.old_state
        self.tmp.cleanup()

    def index(self, aid="a1", minutes=0, **fields):
        """The agent's liveness index, its activation begun `minutes` ago."""
        start = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        agents = os.path.join(self.state, "dotclaude", "agents")
        os.makedirs(agents, exist_ok=True)
        with open(os.path.join(agents, f"{aid}.json"), "w") as f:
            json.dump({"id": aid, "state": "running", "activation_start": start, **fields}, f)

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
        env = dict(os.environ, HOME=self.home, XDG_STATE_HOME=self.state)
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

    def test_the_deadline_deny_is_one_message_with_its_own_footer(self):
        self.index("a1", minutes=61)
        p = self.run_main(self.ev("WebFetch", {"url": "https://example.com"}))
        reason = json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertTrue(reason.startswith(
            "[subagent-policy] deadline (stop_and_explain): this activation has run 61 min, past "
            "the 60 min stop for general-purpose. Only SubagentHandback, SendMessage and "
            "ToolSearch are allowed now. Hand back a `partial` report"), reason)
        # A resumed agent must know it may try again: the denial alone reads as permanent.
        self.assertIn("If the lead resumes you, the budget starts over", reason)
        self.assertNotIn(POLICY["intents"]["stop_and_explain"], reason)
        with open(os.path.join(self.state, "dotclaude", "delegations.jsonl")) as f:
            row = json.loads(f.readline())
        self.assertEqual((row["event"], row["rule"], row["intent"], row["tool"]),
                         ("policy", "deadline", "stop_and_explain", "WebFetch"))

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

    def test_malformed_settings_or_meta_deny_policed_tools(self):
        # Skipped, a settings file would drop its deny lists, and a meta.json a writer's root.
        self.meta("w1", agentType="writer", worktreePath=self.wt)
        payload = self.ev("Bash", {"command": "touch x"}, atype="writer", cwd=self.wt, aid="w1")
        self.assertEqual(self.run_main(payload).stdout, "")
        settings = os.path.join(self.home, ".claude", "settings.json")
        meta = os.path.join(self.slug_dir, "s1", "subagents", "agent-w1.meta.json")
        for path in (settings, meta):
            with open(path) as f:
                good = f.read()
            for text in ("{", "[" * 100000, "[]"):  # RecursionError in json; not an object
                with open(path, "w") as f:
                    f.write(text)
                p = self.run_main(payload)
                self.assertIn("policy-error", p.stdout, (path, text[:5]))
                handback = self.ev("SubagentHandback", {"message": "r"}, atype="writer",
                                   cwd=self.wt, aid="w1")
                self.assertEqual(self.run_main(handback).stdout, "")
            with open(path, "w") as f:
                f.write(good)

    def test_the_alarm_denies_before_claude_codes_timeout_would_allow(self):
        fifo = os.path.join(self.home, "hang.toml")
        os.mkfifo(fifo)  # opening it for reading blocks until the alarm fires
        p = self.run_main(self.ev("Bash", {"command": "ls"}), {"DELEGATION_POLICY": fifo})
        self.assertIn("PolicyTimeout", p.stdout)

    def main_in_process(self, payload):
        """main() run here, its stdout: patch what the alarm should land in around it."""
        self.addCleanup(signal.signal, signal.SIGALRM, signal.getsignal(signal.SIGALRM))
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                contextlib.redirect_stdout(out):
            self.assertEqual(sp.main(), 0)
        return out.getvalue()

    def test_an_alarm_inside_a_read_that_catches_oserror_or_any_error_still_denies(self):
        # TimeoutError is an OSError: an alarm landing in dc.read_session (except OSError) was
        # swallowed, and the hook ran on with no alarm left. So were ones in the deadline check
        # and the heartbeat (except Exception, failing open). PolicyTimeout gets past each.
        path = os.path.join(self.home, "s.json")
        with open(path, "w") as f:
            f.write("{}")

        def ring(*_):
            sp._alarm(signal.SIGALRM, None)

        session = mock.patch.object(sp, "evaluate", lambda *_: sp.dc.read_session(path))
        sites = {"a session read": (session, mock.patch.object(sp.dc.json, "load", ring)),
                 "the deadline": (mock.patch.object(sp.dc, "read_agent_state", ring),),
                 "the heartbeat": (mock.patch.object(sp.os, "utime", ring),)}
        for where, patches in sites.items():
            with self.subTest(where), contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                out = self.main_in_process(self.ev("Bash", {"command": "ls"}))
                self.assertIn("policy-error", out)
                self.assertIn("PolicyTimeout", out)

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
                    "eval \"git push\"", "codex login status", "claude -p hi", "tmux ls",
                    "timeout 5 git pull", "echo hi | xargs gh issue view",
                    "delegation-ledger open", "timeout 5 delegation-ledger watch",
                    "pass-respawn", "pass-respawn --compact", "env X=1 pass-respawn --print",
                    "ed-pull pull", "ed-pull list"):
            self.assertDenied(self.bash(cmd), "excluded-command", "manual_only", cmd)
        # Only read-only codex is excluded: an agent's raw `codex exec` runs sandboxed, where
        # codex's credential is unreadable, so it is no longer an excluded command.
        self.assertNotEqual((self.bash("codex exec x") or (None,))[0], "excluded-command")

    def test_project_exclusions_are_ignored_like_claude_code_does(self):
        os.makedirs(os.path.join(self.proj, ".claude"), exist_ok=True)
        with open(os.path.join(self.proj, ".claude", "settings.json"), "w") as f:
            json.dump({"sandbox": {"excludedCommands": ["ls *"]}}, f)
        self.assertIsNone(self.bash("ls -la"))


class Commands(Base):
    def test_aliases_functions_and_zsh_equals_are_not_programs(self):
        for cmd in ("gp", "grhh", "gstc", "=git push", "claude-alt -p x", "ggpush"):
            self.assertDenied(self.bash(cmd), "unknown-command", "stop_and_explain", cmd)

    def test_a_path_the_same_line_creates_is_denied_with_the_fix(self):
        # The hook runs before the line does, so .venv doesn't exist yet. The denial stays, but
        # it names the fix (run the creating step first) instead of guessing at an alias.
        d = sp.evaluate(self.ev("Bash", {"command": "uv venv .venv && .venv/bin/python -c 1"}),
                        POLICY, home=self.home)
        self.assertEqual((d.rule, d.intent), ("unknown-command", "stop_and_explain"))
        self.assertIn("doesn't exist yet", d.message)
        self.assertIn("its own Bash call", d.message)
        self.assertNotIn("alias", d.message)

    def test_a_path_that_is_not_executable_says_so(self):
        with open(os.path.join(self.proj, "notes.txt"), "w") as f:
            f.write("x")
        d = sp.evaluate(self.ev("Bash", {"command": "./notes.txt"}), POLICY, home=self.home)
        self.assertEqual(d.rule, "unknown-command")
        self.assertIn("isn't executable", d.message)

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

    def test_every_way_of_setting_a_variable_is_checked(self):
        # A config-file path variable points curl or wget at a file the agent wrote, and a
        # builtin or loop that sets a variable reaches the same names as a VAR=x prefix does.
        for cmd in ("PAGER=less git log",
                    "export PAGER=rc; wget -qO- https://x", "export PAGER=.",
                    "declare -x LD_PRELOAD=/x.so", "typeset -gx PAGER=.", "local PAGER=.",
                    "let PAGER=1", "let 'PAGER += 1'", "export PAGER",
                    "export -n PAGER=less",
                    "read -r PAGER <<<rc", "read 'PAGER?home: '",
                    "printf -v PAGER %s .", "printf -vPAGER %s .", "getopts ab PAGER",
                    "for PAGER in .; do git log; done",
                    "select PAGER in .; do break; done", ": ${PAGER:=rc}", "echo ${PAGER=.}",
                    "(( PAGER = 1 ))", "for ((PAGER=1; PAGER<2; PAGER++)); do :; done"):
            self.assertDenied(self.bash(cmd), "env-assignment", msg=cmd)
        for cmd in ("integer CURL_HOME=1", "print -v CURL_HOME .", "mapfile -t CURL_HOME <f",
                    "vared CURL_HOME",
                    "readonly GIT_SSH_COMMAND=x"):
            self.assertIsNotNone(self.bash(cmd), cmd)  # not on the builtins list at all
        for cmd in ("WGETRC=rc wget -qO- https://x", "CURL_HOME=. curl -s https://x",
                    "WGET_ASKPASS=./a wget -qO- https://x", "export SSH_ASKPASS=./a",
                    "echo WGETRC", "grep -r CURL_HOME .", "printf -vCURL_HOME %s .", ": $((WGETRC=10))", ": $[CURL_HOME=1]",
                    "[[ WGETRC=10 -eq 10 ]]", ": {CURL_HOME}>/dev/null", ": ${a[WGETRC=1]}",
                    "echo SSH_ASKPASS"):
            self.assertDenied(self.bash(cmd), "env-banned", msg=cmd)  # named anywhere at all
        for cmd in (": <<EOF\n${PAGER:=less}\nEOF", "case x in ${PAGER:=less}) ;; esac",
                    "(( ${PAGER:=1} ))", ": ${PAGER::=less}", "read 'PAGER[1,-1]' <<<x",
                    "printf -vPAGER[1] %s x"):
            self.assertDenied(self.bash(cmd), "env-assignment", msg=cmd)
        for cmd in ("declare -n r=PAGER", "local -n r=x", "n=PAGER; : ${!n:=less}"):
            self.assertDenied(self.bash(cmd), "dynamic-assignment", msg=cmd)
        for cmd in ('export "$N"=rc', "export $N=rc", "read -r $N", "printf -v $N %s x",
                    'env "$N"=less git log', 'printf -v"$N" %s less', "declare -n r=PAGER",
                    'printf -v"$N" %s x'):
            self.assertDenied(self.bash(cmd), "dynamic-assignment", msg=cmd)
        for cmd in ("env PAGER=ca$t git log", "read -dp PAGER <<<less", "printf '-v' PAGER %s x",
                    "read -r -d x PAGER <<<y", "env BASH_ENV=/x bash -c ls",
                    "printf -vPAGER[1] %s x"):
            self.assertDenied(self.bash(cmd), "env-assignment", msg=cmd)
        for cmd in ("env FOO=1 git log", "read -rp 'go: ' ans", "read -d x ans <<<y",
                    "printf -v out %s x", "env PAGER=cat git log", "read -n 3 ans <<<yyy"):
            self.assertIsNone(self.bash(cmd), cmd)
        for cmd in ('export PATH="$PATH:/x"', "export FOO=1 BAR", "local i=0", "declare -a arr",
                    "read -r line <f", "printf -v out %s x", "for i in a b; do echo $i; done",
                    "export GIT_PAGER=cat", "echo ${X:=1}", "(( i = 1 ))", "export -p",
                    "let i=i+1", "(( PAGER == 1 ))",
                    "HOME=/tmp/h git status", "XDG_CONFIG_HOME=/tmp/c ls",
                    'export "FOO=bar"', 'local "x=$1"', 'read -p "Name $x: " ans',
                    "read -rp 'Name: ' ans", "export -n FOO"):
            self.assertIsNone(self.bash(cmd), cmd)
        self.assertIsNone(self.bash("for i in a b; do echo $i; done", atype="researcher"))

    def test_a_trap_handler_is_checked_like_eval(self):
        self.assertDenied(self.bash("trap 'git reset --hard' EXIT"), "git-reset")
        self.assertDenied(self.bash("trap -- 'git reset --hard' EXIT INT"), "git-reset")
        self.assertIsNotNone(self.bash("trap '-; git reset --hard' EXIT"))  # handler analyzed
        self.assertDenied(self.bash("trap -p 'git reset --hard' EXIT"), "git-reset")
        self.assertDenied(self.bash('trap "$X" EXIT'), "dynamic-eval")
        for cmd in ("trap 'echo done' EXIT", "trap - EXIT", "trap '' INT", "trap -l", "trap"):
            self.assertIsNone(self.bash(cmd), cmd)

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

    def test_short_flag_clusters_and_global_options(self):
        # round 3: short mutate flags inside a cluster, a global option that eats the subcommand,
        # and commit -n (short of --no-verify).
        for cmd, rule in (("git branch -qD old", "git-branch"), ("git branch -Dq old", "git-branch"),
                          ("git tag -fm msg v1 HEAD", "git-tag"), ("git switch -c n -fq", "git-switch"),
                          ("git restore -S -Wq f", "git-restore"), ("git restore -SW f", "git-restore"),
                          ("git commit -n -m x", "git-flag"), ("git commit -nm x", "git-flag"),
                          ("git commit -an", "git-flag"),
                          ("git --namespace status push origin", "git-push"),
                          ("git --namespace=n push", "git-push"),
                          ("git --git-dir d push", "git-push"),
                          ("git --work-tree w reset --hard", "git-reset"),
                          # round 5: --shallow-file takes the next word, an unknown main-level
                          # option is refused, and checkout -b can't force or reset a branch
                          ("git --shallow-file log reset --hard", "git-reset"),
                          ("git --shallow-file=s push", "git-push"),
                          ("git --frob status", "git-global-option"),
                          ("git checkout -b n -f HEAD", "git-checkout"),
                          ("git checkout -b n --forc HEAD", "git-checkout"),
                          ("git checkout -b n -B m", "git-checkout")):
            self.assertDenied(self.bash(cmd), rule, msg=cmd)

    def test_short_flag_clusters_do_not_overdeny(self):
        # an attached value whose text contains a mutate letter is not a flag
        for cmd in ("git tag -mDeploy v1", "git tag -m Draft v1", "git commit -m 'fix D'",
                    "git branch --list", "git switch -c newf", "git restore --staged f",
                    "git config --global --get user.email", "git config --global user.name",
                    "git --namespace n status", "git -c k=v log",
                    # round 5: known main-level flags, and an optional value that holds a letter
                    "git --no-pager log", "git -P log", "git --literal-pathspecs status",
                    "git --shallow-file s status", "git --version",
                    "git checkout -b feat/x origin/main", "git commit -unormal -m x",
                    "git branch -tdirect feat origin/main"):
            if cmd == "git -c k=v log":
                self.assertDenied(self.bash(cmd), "git-config-override", msg=cmd)
            else:
                self.assertIsNone(self.bash(cmd), cmd)

    def test_read_forms_pass(self):
        for cmd in ("git remote -v", "git remote get-url origin", "git config --get user.name",
                    "git config user.name", "git branch -a", "git worktree list",
                    "git reflog", "git submodule status", "git tag"):
            self.assertIsNone(self.bash(cmd), cmd)

    def test_denied_long_flags_match_by_unique_prefix(self):
        # git's parse-options takes any unique prefix of a long option (`git branch --del` ran
        # as --delete), so every deny-list matches by prefix, each site here once.
        for cmd, rule in (
                ("git commit --no-veri -m x", "git-flag"),
                ("git diff --outp=o.txt", "git-flag"),
                ("git log --ext-d", "git-flag"),
                ("git clone --conf=core.fsmonitor=x https://a/b d", "git-flag"),
                ("git clone --temp=t https://a/b d", "git-flag"),
                ("git branch --del old", "git-branch"),
                ("git branch --set-up=o/x", "git-branch"),
                ("git tag --del v1", "git-tag"),
                ("git switch -c new --disc", "git-switch"),
                ("git restore --staged --work f", "git-restore"),
                ("git rm --forc f", "git-rm-force"),
                ("git merge --abo", "git-abort"),
                ("git cherry-pick --abo", "git-abort"),
                ("git gc --pru=now", "git-gc"),
                ("git config --unset-a user.name", "git-config"),
                ("git config --rem x", "git-config"),
                ("git clone -c core.sshCommand=x ssh://h/r d", "git-flag"),
                ("git clone -qc core.sshCommand=x ssh://h/r d", "git-flag"),
                ("git clone -ux file:///r d", "git-flag")):
            self.assertDenied(self.bash(cmd), rule, msg=cmd)

    def test_prefix_matching_only_adds_denials(self):
        # Allow-lists stay exact, and a longer flag that merely starts with a denied one's name
        # is a different option.
        for cmd in ("git diff --output-indicator-new=+", "git commit --no-edit -m x",
                    "git branch --list", "git config --get user.name", "git restore --staged f",
                    "git switch -c new", "git branch --show-current", "git log --stat",
                    "git clone -b cuda https://a/b d", "git clone -bcuda https://a/b d"):
            self.assertIsNone(self.bash(cmd), cmd)
        for cmd in ("git restore --stag f", "git switch --cre new"):
            self.assertIsNotNone(self.bash(cmd), cmd)


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

    def test_wget_send_flags_match_by_prefix_and_rc_commands_are_denied(self):
        # wget's getopt_long takes unique prefixes; -e/--execute runs a wgetrc command and
        # --config reads a wgetrc file, either of which can set post_data or method.
        for cmd in ("wget --post-d=a https://x", "wget --meth=PUT https://x",
                    "wget --body-f=f https://x", "wget -qO- -e post_data=x https://x",
                    "wget -qO- -epost_data=x https://x", "wget -qe method=PUT -O- https://x",
                    "wget -qO- --exec=method=PUT https://x", "wget -qO- --config=rc https://x",
                    "wget -qO- --conf=rc https://x", "wget -qO- --use-askpass=./a https://x",
                    "wget -qO- --use-a https://x",
                    # round 5: --hsts and --backups are booleans, so they don't take the next word
                    "wget --hsts --post-data=x https://x", "wget --backups --post-data=x https://x",
                    "wget -qO- --hsts -e post_data=x https://x"):
            self.assertDenied(self.bash(cmd), "http-write", "manual_only", cmd)
        # -Y takes the next word, so the -e word is its value (wget then refuses the bad boolean)
        for cmd in ("wget -Y -epost_data=x https://x", "wget --backups=2 -qO- https://x"):
            self.assertIsNone(self.bash(cmd), cmd)
        # a researcher's --hsts no longer swallows the -O- it needs
        for cmd in ("wget --hsts -O- https://x", "wget --backups -O- https://x"):
            self.assertIsNone(self.bash(cmd, atype="researcher"), cmd)


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
        # The agent's root is the innermost worktree; the protected area is the outermost
        # checkout, which holds both the lead's worktree and the real main checkout.
        a = sp.Analyzer(self.ev("Bash", {"command": "ls"}, atype="writer", cwd=inner,
                                aid="nometa"), POLICY, home=self.home)
        self.assertEqual((a.worktree, a.main_root), (inner, self.proj))
        for target in ("../escape.txt", f"{self.proj}/src/x"):
            self.assertDenied(self.decide("Bash", {"command": f"echo x > {target}"},
                                          atype="writer", cwd=inner, aid="nometa"),
                              "worktree-root", msg=target)


class WriterInLane(Writer):
    """A session rooted in a lane (a sibling worktree of the main checkout): its writer's
    worktree still lands under the main checkout, so the lane needs holding on its own."""

    def setUp(self):
        super().setUp()
        self.lane = os.path.join(self.home, "code", "proj-lanes", "chart-fix")
        os.makedirs(os.path.join(self.lane, "src"))
        subprocess.run(["git", "init", "-q", self.lane], check=True)
        self.sessions = os.path.join(self.home, ".claude", "sessions")
        os.makedirs(self.sessions)
        self.session_cwd(self.lane)

    def session_cwd(self, cwd):
        with open(os.path.join(self.sessions, "4242.json"), "w") as f:
            json.dump({"pid": 4242, "sessionId": "s1", "cwd": cwd}, f)

    def lane_writes(self):
        return (f"echo x > {self.lane}/src/a.py", f"cp a {self.lane}/src/",
                f"echo x | tee {self.lane}/notes.md")

    def test_bash_writes_into_the_parent_lane_are_denied(self):
        for cmd in self.lane_writes():
            self.assertDenied(self.wb(cmd), "worktree-root", "scope_down", msg=cmd)
        d = sp.evaluate(self.ev("Bash", {"command": self.lane_writes()[0]}, atype="writer",
                                cwd=self.wt, aid="w1"), POLICY, home=self.home)
        self.assertIn("the parent session's checkout", d.message)

    def test_an_unreadable_session_file_that_may_be_the_parents_refuses(self):
        # Skipped, it may hold the parent's lane, which would then be left to the sandbox.
        with open(os.path.join(self.sessions, f"{2 ** 22 + 12345}.json"), "w") as f:
            f.write("{")  # a pid that isn't an ancestor: ruled out
        self.assertDenied(self.wb(self.lane_writes()[0]), "worktree-root", "scope_down")
        for name in (f"{os.getpid()}.json", "odd.json"):  # an ancestor's, or no pid at all
            for text in ("{", "[" * 100000):  # RecursionError in json
                with open(os.path.join(self.sessions, name), "w") as f:
                    f.write(text)
                with self.assertRaises(ValueError, msg=name):
                    self.wb(self.lane_writes()[0])
                self.assertIsNone(self.wb("touch x"))  # no lookup inside the worktree
            os.remove(os.path.join(self.sessions, name))

    def test_without_a_sessions_file_the_lane_is_left_to_the_sandbox(self):
        os.remove(os.path.join(self.sessions, "4242.json"))
        for cmd in self.lane_writes():
            self.assertIsNone(self.wb(cmd), cmd)

    def test_file_tools_into_the_lane_are_denied_either_way(self):
        self.assertDenied(self.w("Write", {"file_path": self.lane + "/src/a.py"}),
                          "worktree-root", "scope_down")
        os.remove(os.path.join(self.sessions, "4242.json"))
        self.assertDenied(self.w("Write", {"file_path": self.lane + "/src/a.py"}),
                          "worktree-root", "scope_down")

    def test_a_parent_in_the_main_checkout_adds_nothing(self):
        subprocess.run(["git", "init", "-q", self.proj], check=True)
        self.session_cwd(os.path.join(self.proj, "src"))
        for cmd in self.lane_writes():
            self.assertIsNone(self.wb(cmd), cmd)
        a = sp.Analyzer(self.ev("Bash", {"command": "ls"}, atype="writer", cwd=self.wt,
                                aid="w1"), POLICY, home=self.home)
        self.assertEqual(a.protected_roots(), [(self.proj, "the main checkout")])

    def test_the_lane_is_looked_up_only_for_a_target_outside_the_worktree(self):
        temp = sp.expand(POLICY["rm"]["temp_roots"][0], self.home)
        with mock.patch.object(sp.dc, "session_toplevel") as lookup:
            self.assertIsNone(self.wb(f"echo x > a.txt && echo y > {temp}/s.txt"))
            lookup.assert_not_called()


class Researcher(Base):
    def r(self, cmd):
        return self.bash(cmd, atype="researcher")

    def test_a_researcher_teammate_gets_the_allowlist(self):
        # A teammate's hook agent_type is its name; its role comes from meta.json.
        self.meta("t1", agentType="team-probe", name="team-probe", customAgentType="researcher",
                  taskKind="in_process_teammate")
        self.assertDenied(self.bash("touch x", atype="team-probe", aid="t1"),
                          "researcher-program")
        self.assertIsNone(self.bash("git log -1", atype="team-probe", aid="t1"))

    def test_allowlisted_reads_pass(self):
        for cmd in ("git log --oneline -5", "git show HEAD --stat", "git blame -L 1,5 f",
                    "grep -rn foo . | head -20", "find . -name '*.py' | wc -l", "sed -n '1,5p' f",
                    "cat f 2>/dev/null", "git branch -a", "git tag --list 'v*'", "git remote -v",
                    "git config --get user.name", "git stash list", "curl -s https://api.github.com/zen",
                    "wget -qO- https://x", "gh-public /repos/a/b", "ls -la", "cargo --version",
                    "git clone --depth 1 https://github.com/a/b /tmp/claude-%d/r/b" % os.getuid(),
                    "git clone --dep 1 https://github.com/a/b /tmp/claude-%d/r/c" % os.getuid(),
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
                ("git clone --dep 1 https://a/b /x", "researcher-clone"),
                ("git clone --separate-git-dir /x https://a/b /tmp/claude-%d/t" % os.getuid(),
                 "git-flag"),
                ("sed -i s/a/b/ f", "researcher-flag"), ("sed 's/a/b/w out' f", "researcher-flag"),
                ("sed -e '1e ls' f", "researcher-flag"),
                ("find . -name x -delete", "researcher-flag"), ("find . -exec rm {} ;", "researcher-flag"),
                ("find . -fprint out", "researcher-flag"), ("grep --filter=x foo .", "researcher-flag"),
                ("grep --pre=cat foo", "researcher-flag"), ("sort -o out f", "researcher-flag"),
                ("sort -oout f", "researcher-flag"), ("tree -o out", "researcher-flag"),
                ("sort -uo /home/hayden/x f", "researcher-flag"), ("tree -nao out", "researcher-flag"),
                ("git grep -iOcmd foo", "git-flag"), ("xxd -r f", "researcher-flag"),
                ("sort -bo out f", "researcher-flag"), ("sort -do out f", "researcher-flag"),
                ("tree -Lo 1 out", "researcher-flag"), ("tree -Po x out", "researcher-flag"),
                ("tree -Io x out", "researcher-flag"),
                # round 6: xxd reads options by first letter and takes an output operand, tree
                # -R writes 00Tree.html, file -C writes a .mgc, and the other output options
                ("xxd -revert f", "researcher-flag"), ("xxd --revert f", "researcher-flag"),
                ("xxd --r f", "researcher-flag"), ("xxd -rp hex", "researcher-flag"),
                ("xxd in out", "researcher-flag"), ("xxd -c 8 in out", "researcher-flag"),
                ("xxd -cols 8 in out", "researcher-flag"), ("xxd -c8 in out", "researcher-flag"),
                ("xxd in -c", "researcher-flag"), ("xxd - out", "researcher-flag"),
                ("xxd -- in out", "researcher-flag"), ("xxd -s 1 -R never in out", "researcher-flag"),
                ("tree -R -H . -L 1 d", "researcher-flag"), ("tree -aR d", "researcher-flag"),
                ("file -C -m m", "researcher-flag"), ("file -zC -m m", "researcher-flag"),
                ("file --comp -m m", "researcher-flag"), ("grep --pager=less foo f", "researcher-flag"),
                ("egrep --view=x foo f", "researcher-flag"),
                ("uniq in out", "researcher-flag"), ("LD_PRELOAD=x ls", "env-assignment"),
                ("FOO=1 ls", "env-assignment")):
            self.assertDenied(self.r(cmd), rule, msg=cmd)


    def test_yq_split_writes_files(self):
        # yq may not be installed, so its table is checked below the command lookup
        g = sp.Analyzer(self.ev("Bash", {"command": "true"}), POLICY, home=self.home)
        for args in (["yq", "-s", "x", "f"], ["yq", "--split-exp", "x", "f"], ["yq", "-Ps", "x", "f"]):
            with self.assertRaises(sp.Deny, msg=args) as cm:
                g.researcher_program("yq", args, [], [], self.proj, 0)
            self.assertEqual(cm.exception.rule, "researcher-flag", args)
        self.assertEqual(g.researcher_program("yq", ["yq", ".a", "f"], [], [], self.proj, 0),
                         self.proj)

    def test_denied_flags_match_by_unique_prefix(self):
        for cmd, rule in (
                ("sort --out=o.txt f", "researcher-flag"),
                ("sort --compress-prog=sh f", "researcher-flag"),
                ("grep --filt=x y f", "researcher-flag"),
                ("rg --pre-g=x foo", "researcher-flag"),
                ("date --se=now", "researcher-flag"),
                ("git branch --trac x origin/x", "researcher-git"),
                ("git tag --anno v1", "researcher-git"),
                ("wget -O- --rec https://x", "researcher-write"),
                ("wget -O- --output-f=log https://x", "researcher-write"),
                ("wget -O- --dir=d https://x", "researcher-write"),
                ("wget -qrO- https://x", "researcher-write"),
                ("wget -qo log -O- https://x", "researcher-write"),
                ("wget -bqO- https://x", "researcher-write")):
            self.assertDenied(self.r(cmd), rule, msg=cmd)
        for cmd in ("wget --referer -O- https://x", "wget -U -O- https://x",
                    "wget --user-a -O- https://x", "wget --egd-file -O- https://x"):
            # the -O- is the long option's value, so wget saves the page to a file
            self.assertDenied(self.r(cmd), "researcher-write", msg=cmd)
        for cmd in ("grep --pretty foo f", "sort --stable f", "wget -qO- https://x",
                    "wget -O- --reject=jpg https://x", "wget --output-document - https://x",
                    "wget --quiet -O- https://x", "wget --referer=r -O- https://x",
                    "wget -q -O - https://x", "wget --output-document=- https://x",
                    "wget -qO- -U agent https://x", "wget -qO- --header=X:1 https://x",
                    "sort -n f", "sort -k2 f", "tree -L 2", "git grep -in foo", "xxd -c 8 f",
                    # round 6: -pr is -p and -er is -e to xxd; a value word isn't an operand
                    "xxd -pr f", "xxd -er f", "xxd -c8 f", "xxd -cols 8 f", "xxd -R never f",
                    "xxd -l 16 -s 4 f", "xxd -i -n name f", "xxd -", "file -mC f",
                    "file -m magic f"):
            self.assertIsNone(self.r(cmd), cmd)


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
        self.assertDenied(self.bash("sed 's/a/b/w .git/config' f"), "protected-path")
        # sed reads ~ in a w name literally (the shell didn't expand the quoted script), so this
        # writes ./~/.zshrc, not $HOME/.zshrc: not the protected file (F4).
        self.assertIsNone(self.bash("sed 's/a/b/w ~/.zshrc' f"))
        self.assertDenied(self.bash("sed '1e rm -rf x' f"), "sed-exec")
        self.assertIsNone(self.bash("sed -n '1,5p' f"))
        self.assertIsNone(self.bash("sed 's/a/b/w notes.txt' f"))

    def test_a_writer_without_a_worktree_can_still_hand_back(self):
        self.assertIsNone(self.decide("SubagentHandback", {"message": "report"}, atype="writer",
                                      cwd=self.proj, aid="nometa"))


class SedScripts(Base):
    """sed scripts read the way GNU sed 4.9 compiles them: a pattern, a replacement, a text or a
    label is never a command (the false denials of 2026-10-20), and every e and w still counts."""

    # The scripts that read: a researcher may run them, and so may anyone else.
    READS = ("sed -n 's/show me/x/p' f", "sed 's/the same for the other six edges\\./x/' f",
             "sed 's/we/ew/g' f", "sed -n '/new e/p' f", "sed 's/[/]/x/' f", "sed 's/x/\\/w/' f",
             "sed 'y/we/ew/' f", "sed 'a foo; e date' f", "sed '1i\\\ne w x' f",
             "sed 'a foo\\\ne' f", "sed -n ':e;b e' f", "sed 's/a/b/#e' f", "sed -n 's/a/b/;p' f",
             "sed -n 'r in' f", "sed -e 'a foo\\' -e 'e date' f", "sed -n -e '1{' -e p -e '}' f")
    # Each runs a shell command: as written, or spelled so the old regexes missed it.
    EXECS = ("sed '1e date' f", "sed 's/a/b/e' f", "sed 's|a|b|e' f", "sed 's/a/b/ e' f",
             "sed 'p;e date' f", "sed 'p\ne date' f", "sed '1{e date\n}' f", "sed -n '1{p;e\n}' f",
             "sed 'y/a/b/;e' f", "sed '$!e' f", "sed '/x/I e' f", "sed '\\,x,e' f",
             "sed 's/[/]/x/e' f", "sed -e p -e e f", "sed 's/a/b/;s/c/d/3e' f",
             "sed --expression='1e date' f", "sed -e'1e date' f", "sed --e='1e date' f",
             "sed --expr '1e date' f", "sed -l 5 's/a/b/e' f", "sed -ne '1e date' -e p f",
             "sed -nes/a/b/e f", "sed 's/a/b/e' -e p f", "sed -e 'a foo' -e 'e date' f",
             # A filename before -e: under POSIXLY_CORRECT getopt stops at it, so sed takes it as
             # the script; it is checked strictly (no token-mode leniency now), so the e is caught.
             "sed error.log -e p f")
    # sed can't run these, or the policy can't see the script: refused as unchecked.
    UNCHECKED = ("sed -f x.sed f", "sed --file=x.sed f", "sed -nf x.sed f", "sed 's/a/b' f",
                 "sed 's/a/b/w' f", "sed --s 's/a/b/' f", "sed -k p f", "sed 's/a/b/q' f",
                 "sed 's§a§b§' f", "sed '1}' f")
    # A $var or glob/brace word hides the script and could expand to an option (even -i); the policy
    # requires sed's own --sandbox AND each dynamic word only as an -e value or after --. Otherwise
    # it is refused use_alternative, for every role (SP3: an agent-built script ran unchecked before).
    NEEDS_SANDBOX = (
        # a dynamic script or file in a bare operand (allowed or exec'd under the old token heuristic)
        "sed -n \"${N}p\" f", "sed -n \"${N}p\" exam.txt", "sed -n \"${N}p\" error.log",
        "sed -n \"${N}p\" write.log", "sed \"$S\" f", "sed \"$S\" exam.txt",
        "sed \"$X\" '1e date' f", "sed $X 'e date' f", "sed \"$X\" -e '1e date' f",
        "sed -e \"$X\" -e 'e date' f",
        # FINDINGS: a script the agent BUILDS, unchecked for any role before SP3 (pinned one by one)
        "sed \"$(printf wout.txt)\" f",          # printf-built w target
        "sed \"$(printf '1e touch y')\" f",      # printf-built e command
        "sed \"${X:-wout.txt}\" f",              # default-value w target
        "sed $X 'wout.txt' f",                   # $X vanishes, 'wout.txt' becomes the script
        "sed \"${X:--i}\" 's/h/H/' f",           # expands to -i, editing f in place
        "sed --sandbox \"$pat\" f",              # --sandbox present, but the $var is in script position
        # --sandbox does not disable -i, and these can still become a bare -i at runtime:
        "sed --sandbox 's/x/y/' {-i,.git/config}",   # a brace operand expands to `-i .git/config`
        "sed --sandbox -e $X f",                      # an unquoted -e value word-splits a -i off its tail
        "sed --sandbox -n -e $N'p' f",               # an unquoted computed script, same split
        "sed --sandbox -l $X 's/h/H/' f",            # ANY value-taking option's split value, not just -e
        "sed --sandbox --line-length $X 's/h/H/' f", # the long form of the same
        "sed --sandbox 's/a/b/' *.txt")              # a glob before -- could match a file named -i
    # --sandbox (sed refuses every e/r/w) with each dynamic word in a safe slot - a quoted
    # single-word -e value, or a file after -- (where sed can't read it as an option) - is allowed.
    SANDBOXED_OK = ("sed --sandbox -e \"${N}p\" exam.txt", "sed --sandbox -n -e \"$pat\" error.log",
                    "sed --sa -e \"$x\" f", "sed --sandbox p -- \"$file\"",
                    "sed --sandbox -e \"$x\" -- \"$f\"", "sed --sandbox 's/a/b/' -- *.txt")

    def r(self, cmd):
        return self.bash(cmd, atype="researcher")

    def wb(self, cmd):
        self.meta("w1", agentType="writer", worktreePath=self.wt)
        return self.decide("Bash", {"command": cmd}, atype="writer", cwd=self.wt, aid="w1")

    def test_patterns_replacements_text_and_labels_are_not_commands(self):
        for cmd in self.READS:
            self.assertIsNone(self.bash(cmd), cmd)
            self.assertIsNone(self.r(cmd), cmd)
        self.assertIsNone(self.bash("sed -i 's/the same for the other six edges\\./x/' f"))
        self.assertIsNone(self.bash("sed -i -e :a -e '/^\\n*$/{$d;N;ba' -e '}' f"))

    def test_every_e_is_refused(self):
        for cmd in self.EXECS:
            self.assertDenied(self.bash(cmd), "sed-exec", "stop_and_explain", cmd)
            self.assertDenied(self.r(cmd), "researcher-flag", msg=cmd)

    def test_a_script_sed_or_the_policy_cant_read_is_refused(self):
        for cmd in self.UNCHECKED:
            self.assertDenied(self.bash(cmd), "sed-unchecked", "stop_and_explain", cmd)
            self.assertDenied(self.r(cmd), "sed-unchecked", msg=cmd)

    def test_w_writes_to_the_rest_of_the_line(self):
        for cmd in ("sed 'w notes.txt ../../../../main.py' f", "sed 's|a|b|w ../../../main.py' f",
                    "sed 's/[/]/g;/w ../../../x/p' f", "sed -n 'p;W ../../../main.py' f"):
            self.assertDenied(self.wb(cmd), "worktree-root", msg=cmd)
        for cmd in ("sed -n 's/a/b/w out.txt' f", "sed 'w notes.txt' f",
                    "sed -n 's/a/b/w /dev/stdout' f"):
            self.assertIsNone(self.wb(cmd), cmd)
        for cmd in ("sed 's/a/b/w out' f", "sed 'W out' f", "sed -n 's|a|b|w out' f",
                    "sed 's/[/]/g;/w x/p' f"):
            self.assertDenied(self.r(cmd), "researcher-flag", msg=cmd)

    def test_in_place_writes_each_file_and_its_backup(self):
        for cmd in ("sed -i -e s/a/b/ ../../../main.py", "sed -i'../../../*' s/a/b/ f",
                    "sed --in-place='../../../*.bak' s/a/b/ f"):
            self.assertDenied(self.wb(cmd), "worktree-root", msg=cmd)
        for cmd in ("sed -i.bak s/a/b/ f", "sed -i s/a/b/ f", "sed -i'*' s/a/b/ f"):
            self.assertIsNone(self.wb(cmd), cmd)
        for cmd in ("sed -i.json s/a/b/ .mcp", "sed -i'.git/hooks/*' s/a/b/ pre-commit",
                    "sed --in-place=.json s/a/b/ .mcp", "sed --in=.json s/a/b/ .mcp",
                    "sed -ni.json s/a/b/p .mcp"):
            self.assertDenied(self.bash(cmd), "protected-path", msg=cmd)
        for cmd in ("sed --in s/a/b/ f", "sed --in-pl=.b s/a/b/ f", "sed -si s/a/b/ f"):
            self.assertDenied(self.r(cmd), "researcher-flag", msg=cmd)

    def test_dynamic_or_glob_sed_needs_sandbox(self):
        # Without --sandbox (or with a dynamic/glob word out of place) a $var/glob sed is refused for
        # every role - writer included, since its worktree writes have no sandbox backstop - so an
        # agent can't build an e, w or -i the policy never sees (SP3). Each case is pinned here.
        for cmd in self.NEEDS_SANDBOX:
            self.assertDenied(self.bash(cmd), "sed-unchecked", "use_alternative", cmd)
            self.assertDenied(self.r(cmd), "sed-unchecked", "use_alternative", cmd)
            self.assertDenied(self.wb(cmd), "sed-unchecked", "use_alternative", cmd)

    def test_a_for_loop_built_sed_script_is_refused(self):
        # A loop variable is a dynamic word like any other: the inner sed call still needs --sandbox.
        cmd = "for X in wout.txt; do sed \"$X\" f; done"
        self.assertDenied(self.bash(cmd), "sed-unchecked", "use_alternative", cmd)
        self.assertDenied(self.r(cmd), "sed-unchecked", "use_alternative", cmd)

    def test_sandbox_lets_a_dynamic_or_glob_sed_through(self):
        # With --sandbox (sed refuses every e/r/w) and each dynamic word as an -e value or after --,
        # the call is allowed for a writer or general-purpose agent (only a literal -i would remain).
        for cmd in self.SANDBOXED_OK:
            self.assertIsNone(self.bash(cmd), cmd)
            self.assertIsNone(self.wb(cmd), cmd)

    def test_a_tilde_in_a_sed_write_target_is_literal_not_home(self):
        # sed reads a ~ in a w name or -i suffix literally; checking it as $HOME would deny a
        # write that really lands in the worktree (F4).
        self.assertIsNone(self.wb("sed 's/a/b/w ~/out.txt' f"))
        self.assertIsNone(self.wb("sed -i'~/*.bak' s/a/b/ f"))

    def test_researcher_refuses_sed_with_a_glob_or_brace(self):
        # A glob or brace word hides what sed's args expand to, and --sandbox does not disable -i;
        # a researcher has no sandbox backstop for a write, so it refuses every glob/brace, even
        # with --sandbox.
        for cmd in ("sed -n p {-e,'1e date'} f", "sed -n 1p *", "sed -n 's/a/b/p' *.log",
                    "sed --sandbox 's/a/b/' *.log"):
            self.assertDenied(self.r(cmd), "sed-unchecked", "use_alternative", cmd)
        # A lone dynamic word is no longer "fine": it needs --sandbox and an -e / after-- slot.
        self.assertDenied(self.r("sed \"$X\" -n p f"), "sed-unchecked", "use_alternative")
        self.assertDenied(self.r("sed \"${X:--i}\" 's/h/H/' f"), "sed-unchecked", "use_alternative")
        self.assertIsNone(self.r("sed --sandbox -e \"$x\" f"))  # --sandbox + an -e value: allowed

    def test_sed_i_backup_names_follow_gnu_seds_symlink_handling(self):
        # GNU sed 4.9 without --follow-symlinks writes the backup at the link path; with it, at
        # the resolved target (which os.path.realpath matches). Verified empirically on sed 4.9.
        self.assertEqual(sp.sed_backups(["a.txt"], ".bak", "/w", False), ["a.txt.bak"])
        self.assertEqual(sp.sed_backups(["a.txt"], ".bak", "/w", True),
                         ["a.txt.bak", os.path.realpath("/w/a.txt") + ".bak"])


def _gnu_sed_sandbox():
    try:
        return subprocess.run(["sed", "--sandbox", "-n", "p"], stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=10).returncode == 0
    except OSError:
        return False


SED_ADDRESSES = ("", "", "1", "$", "/x/", "/a\\/b/", "/[/]/", "\\,x,", "\\%[%]%", "/x/I", "1,3",
                 "1,/y/", "0,/y/", "2~3", "1,+2", "/x/,$", "/[[:alpha:]/]/M", "1 , 3")
SED_COMMANDS = (
    "p", "d", "=", "N", "D", "G", "x", "z", "F", "l", "l 5", "q", "q 3", "Q", "e", "e date",
    "a foo", "a foo; e date", "i\\\nbar", "c\\", "a foo\\\ne x", "a\\text", "r in", "R in",
    "w out", "W out", "w a b", "w out;p", "w out}", ":e", ":w", "b e", "be", "t w", "T", "b",
    "b a;:a", "s/a/b/", "s/a/b/g", "s/a/b/e", "s/a/b/w out", "s/a/b/gpw out", "s/a/b/ e",
    "s/a/b/2", "s/a/b/I", "s|a|b|e", "s,a,b,w out", "s#a#b#", "s/[/]/x/", "s/[/]/g;/w out/p",
    "s/[^]/]/e/", "s/[[:alpha:]/]/x/", "s/[[./.]]/x/e", "s/[\\/]/x/", "s/x/\\/e/", "s/x/[/]/",
    "s/a\\/b/c/", "s\\a\\b\\", "s/a/b/#e", "s/a/b/ ; e", "s/[[=e=]/]/x/", "s/[[:]/]/x/w out",
    "s/a/b/p2g", "s/a/b/pp", "s/a/b/0", "s/a/b/\r", "y/ab/ba/", "y/a\\/b/b\\/a/", "y|a|e|",
    "{p}", "{e}", "{p;e date\n}", "}", "v", "v 4.2", "#e", "#n", "s/a\\\nb/c/", "s/a/b\\\ne/")
SED_SEPARATORS = (";", "\n", " ; ", "\n\n", "  ", "")


def sed_corpus():
    """Every command alone, then seeded random scripts of one to three commands."""
    rng = random.Random(20261020)
    out = list(SED_COMMANDS)
    for _ in range(1500):
        parts = []
        for _ in range(rng.randint(1, 3)):
            parts.append(rng.choice(SED_ADDRESSES) + rng.choice(("", "", "!", " ! "))
                         + rng.choice(SED_COMMANDS))
            parts.append(rng.choice(SED_SEPARATORS))
        out.append("".join(parts[:-1]))
    return out


def sed_part_corpus():
    """Scripts split across -e parts: sed carries a pending a/i/c text and open blocks over."""
    parts = SED_COMMANDS + ("a foo\\", "1{", "}", ":a", "ba", "$!N", "/^\\n*$/{$d;N;ba", "i\\")
    rng = random.Random(20261021)
    return [[rng.choice(parts) for _ in range(rng.randint(2, 3))] for _ in range(800)]


@unittest.skipUnless(_gnu_sed_sandbox(), "needs GNU sed with --sandbox (4.3 or newer)")
class SedOracle(unittest.TestCase):
    """sed_ops against GNU sed itself: --sandbox refuses a script holding e, r or w before it
    runs any of it, and plain sed opens every w file when it compiles the script."""

    def test_sed_ops_agrees_with_gnu_sed(self):
        for script in sed_corpus():
            p = subprocess.run(["sed", "--sandbox", "-n", "-e", script], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=10)
            try:
                ops = sp.sed_ops(script)
            except sp.SedError:
                ops = None
            if p.returncode == 0:  # sed runs it, and it has no e, r or w
                self.assertEqual(ops, [], repr(script))
            elif "e/r/w commands disabled" in p.stderr:  # sed found one: so must we
                self.assertNotEqual(ops, [], repr(script))

    def test_sed_ops_reads_e_parts_as_gnu_sed_does(self):
        for parts in sed_part_corpus():
            argv = ["sed", "--sandbox", "-n"] + [x for part in parts for x in ("-e", part)]
            p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               timeout=10)
            try:
                ops = sp.sed_ops(*parts)
            except sp.SedError:
                ops = None
            if p.returncode == 0:
                self.assertEqual(ops, [], repr(parts))
            elif "e/r/w commands disabled" in p.stderr:
                self.assertNotEqual(ops, [], repr(parts))

    def test_w_names_are_the_files_sed_opens(self):
        checked = 0
        for script in sed_corpus():
            try:
                ops = sp.sed_ops(script)
            except sp.SedError:
                continue
            if not ops or any(op != "w" for op, _ in ops):
                continue
            with tempfile.TemporaryDirectory() as d:
                p = subprocess.run(["sed", "-n", "-e", script], stdin=subprocess.DEVNULL, cwd=d,
                                   capture_output=True, timeout=10)
                if p.returncode:
                    continue
                made = {os.path.relpath(os.path.join(top, f), d)
                        for top, _, files in os.walk(d) for f in files}
            self.assertEqual(made, {a for _, a in ops if a not in ("/dev/stdout", "/dev/stderr")},
                             repr(script))
            checked += 1
        self.assertGreater(checked, 20)


class ZshQuoting(Base):
    """zsh expansions Parable can't see stay refused, except in text zsh takes literally:
    single quotes, double quotes (for =(...) only) and quoted heredoc bodies."""

    def test_literal_text_passes(self):
        for cmd in ("python3 - <<'EOF'\nux,uy=(x2-x1)/d\nEOF",
                    "python3 - <<-'EOF'\n\tux,uy=(x2-x1)/d\n\tEOF",
                    "cat > notes.txt <<'EOF'\n${(f)x} $~y =(z)\nEOF\necho done",
                    "cat <<\\EOF\n=(z)\nEOF", "cat <<E'X'\n${(f)x}\nEX",
                    "python3 -c 'a=(1, 2)'", 'python3 -c "a=(1, 2)"', "echo '${(f)x} $~y'",
                    "echo hi # it's\npython3 -c 'b=(3)'", "echo a#b 'c=(d)'", "x=(a b)",
                    "F=(supabase/a.sql supabase/b.sql); for f in $F; do echo $f; done",
                    "typeset -a x=(1 2)", "echo a'b'=c"):
            self.assertIsNone(self.bash(cmd), cmd)

    def test_expansions_zsh_runs_are_refused(self):
        for cmd in ("cat =(ls)", "echo ${(f)x}", 'echo "${(f)x}"', "echo $~x", 'echo "$~x"',
                    "x=1 =(ls)", "echo \\\n=(ls)", "x=\\\n(a b)", "echo ${:-=(ls)}", 'echo "$(cat =(ls))"', "echo `cat =(ls)`",
                    "cat <<EOF\n${(f)x}\nEOF", "cat <<EOF\n=(ls)\nEOF",
                    "echo a#'\n' =(ls) \\'",
                    "(( x = 1 << 2 ))\necho '\n2\n' =(ls) \\'",
                    "echo $'\\'' =(ls) 'x'",
                    "cat <<'E'\n=(ls)\nE \n",
                    "echo x;# '\n' =(ls) \\'", "echo $\\\n~x", "echo $\\\n{\\\n(f)x}",
                    "x='/(e:\"touch y\":)'; echo $\\\n~x",
                    "bash -c 'cat =(ls)'", "zsh -c 'echo ${(f)x}'", "eval 'echo $~x'"):
            self.assertDenied(self.bash(cmd), "zsh-expansion", "stop_and_explain", cmd)

    def test_literal_heredocs_count_only_when_parable_reads_them_the_same(self):
        from parable import parse
        a = sp.Analyzer(self.ev("Bash", {"command": "ls"}), POLICY, home=self.home)
        cmd = "python3 - <<'EOF'\nux=(1)\nEOF"
        self.assertFalse(a.zsh_expansion(cmd, parse(cmd)))
        self.assertTrue(a.zsh_expansion(cmd, parse("python3 - <<'EOG'\nux=(1)\nEOG")))
        self.assertTrue(a.zsh_expansion(cmd, None))  # Parable couldn't parse it


    def test_an_equals_inside_a_word_never_substitutes(self):
        # Every printable character, and a few multi-character words, before =(: where the scan
        # marks the = mid-word, zsh 5.9 must not run a process substitution there.
        if not shutil.which("zsh"):
            self.skipTest("needs zsh")
        prefixes = [chr(c) for c in range(33, 127)] + [
            "a" + chr(c) for c in range(33, 127)] + ["a'b'", 'a"b"', "a\\x", "a\\\n", "\\\n",
                                                    "x\\ ", "{a,", "a]", "$x", "~"]
        masked = 0
        with tempfile.TemporaryDirectory() as d:
            env = {"PATH": os.environ["PATH"], "HOME": d, "TMPPREFIX": os.path.join(d, "zsub")}
            for pre in prefixes:
                cmd = f"print -r -- {pre}=(print -r x)"
                at = len("print -r -- ") + len(pre)
                if not any(a <= at < b for a, b, _ in sp.unexpanded_spans(cmd)[0]):
                    continue
                masked += 1
                out = subprocess.run(["zsh", "-f", "-c", cmd], cwd=d, env=env, text=True,
                                     capture_output=True, timeout=10).stdout
                self.assertNotIn(env["TMPPREFIX"], out, cmd)
            control = subprocess.run(["zsh", "-f", "-c", "print -r -- =(print -r x)"], cwd=d,
                                     env=env, text=True, capture_output=True, timeout=10).stdout
        self.assertIn(env["TMPPREFIX"], control)
        self.assertGreater(masked, 80)


# Places a marker can sit (@), and noise around them. Every one is valid zsh.
ZSH_SEGMENTS = (
    "print -r -- @", "print -r -- 'a @ b'", 'print -r -- "a @ b"', "print -r -- x'@'y",
    "cat <<'E'\n@\nE", "cat <<-'E'\n\t@\n\tE", 'cat <<"E"\n@\nE', "cat <<\\E\n@\nE",
    "cat <<E'X'\nq @\nEX", "cat <<E\n@\nE", "cat <<'A' <<'B'\n@\nA\n@\nB",
    "print -r -- 'm\n@'", 'print -r -- "m\n@"', "print -r -- a#'\n' @ \\'",
    "print -r -- hi # it's", "print -r -- a#b", "print -r -- a\\'b", "print -r -- $'x\\'y'",
    'print -r -- "q\\"r"', "print -r -- s \\\n t", "cat <<<'h'", 'print -r -- "$(print -r c)"',
    "print -r -- ${HOME:+h}", "(( 1 << 2 ))", ": 'x'\"y\"\\z", 'true # "unclosed',
    "print -r -- \\# x", "print -r -- a; print -r -- @", 'print -r -- "$(print -r @)"',
    'print -r -- "`print -r @`"', "print -r -- ${HOME:+@}", 'print -r -- "${HOME:+@}"',
    "print -r -- x # it's\nprint -r -- @ \\'")


def zsh_case(rng):
    """A command of two to five segments with markers, and the markers as (index, kind, id).
    A P marker is =(...), which zsh runs except inside quotes; an F marker is ${(e)...}, which
    it runs except in single quotes. Each appends its id to ./log when zsh runs it."""
    body, marks = [], []
    for seg in (rng.choice(ZSH_SEGMENTS) for _ in range(rng.randint(2, 5))):
        if body:
            body.append("\n")
        for k, piece in enumerate(seg.split("@")):
            if k:
                kind = rng.choice("PF")
                mid = f"{kind}{len(marks)}"
                marks.append((sum(map(len, body)), kind, mid))
                body.append(f"=(print -r {mid} >>log)" if kind == "P" else f"${{(e)V{mid}}}")
            body.append(piece)
    pre = "".join(f"V{mid}='$(print -r {mid} >>log)'\n" for _, kind, mid in marks if kind == "F")
    return pre + "".join(body), [(i + len(pre), kind, mid) for i, kind, mid in marks]


@unittest.skipUnless(shutil.which("zsh"), "needs zsh")
class Substitutions(Base):
    """Every command substitution zsh would run gets the inner command checked, including the
    ones Parable keeps as plain text (a ${...} argument, an unquoted heredoc body, a case
    pattern, a here-string, a body that fails to parse inside double quotes)."""

    SHAPES = ("cat <<EOF\n$({c})\nEOF", "cat <<EOF\n`{c}`\nEOF", "cat <<EOF\n$(( $({c}) ))\nEOF",
              "cat <<EOF\n${{X:-$({c})}}\nEOF", "cat <<-EOF\n\t$({c})\n\tEOF",
              "echo ${{X:-$({c})}}", 'echo "${{X:-$({c})}}"', "echo ${{X/$({c})/y}}",
              "echo ${{X:$({c})}}", 'echo "${{X:-`{c}`}}"', "echo ${{X:-${{Y:-$({c})}}}}",
              "echo $[ $({c}) ]", "case x in $({c})) ;; esac", 'cat <<<"$({c})"', 'cat < "$({c})"',
              "while false; do :; done <<EOF\n$({c})\nEOF", "echo $(echo $({c}))",
              'echo "$({c})"', "echo `{c}`", "cat <({c})", "[[ -n $({c}) ]]",
              "for ((i=$({c}); i<1; i++)); do :; done", "(( $({c}) ))",
              # quotes are literal in an unquoted heredoc body, and ' is literal inside "..."
              "cat <<EOF\n'$({c})'\nEOF", """echo "'$({c})'\"""",
              # review round 1: ANSI-C quotes take \', zsh honours ' in an unquoted ${X:-...}
              # default, and a backtick inside "..." also unescapes \"
              """echo $'\\''$({c})\\'""", """echo ${{X:-'}}'$({c})'}}'}}\\'""",
              """echo "`echo \\"'\\"$({c})\\"'\\"`\"""",
              # review round 2: a ${...} default holding $'..' or, inside "...", a '
              """echo ${{x:-$'\\'}}'$({c})}}\\'""", """echo "${{x:-'}}"'$({c})'"'}}\"""")

    def test_inner_commands_are_checked_wherever_the_substitution_sits(self):
        for shape in self.SHAPES:
            cmd = shape.format(c="touch x")
            self.assertDenied(self.bash(cmd, atype="researcher"), "researcher-program", msg=cmd)
            cmd = shape.format(c="git reset --hard")
            self.assertDenied(self.bash(cmd), "git-reset", msg=cmd)

    def test_a_body_that_fails_to_parse_is_denied(self):
        # Parable drops a double-quoted (or process) substitution whose body won't parse, with
        # no error; zsh still runs it (ls *(.) is a glob qualifier).
        for cmd in ('echo "$(touch x; ls *(.))"', '[[ -n "$(touch x; ls *(.))" ]]',
                    'case "$(touch x; ls *(.))" in *) ;; esac',
                    'for i in "$(touch x; ls *(.))"; do :; done', 'a=("$(touch x; ls *(.))")',
                    'cat <<<"$(touch x; ls *(.))"', "cat <(touch x; ls *(.))",
                    "echo x >(touch x; ls *(.))", "cat <<EOF\n$(touch x; ls *(.))\nEOF",
                    'echo "$(true) $(touch x; ls *(.))"', 'echo "${X:-$(touch x; ls *(.))}"',
                    # quote characters that would put a naive scan out of step with zsh
                    """echo "$(echo ")'")$(touch x; ls *(.))'\""""):
            for atype in ("researcher", "general-purpose"):
                self.assertDenied(self.bash(cmd, atype=atype), "parse-error", msg=cmd)

    def test_literal_and_checked_forms_pass(self):
        for cmd in ('echo "$(git log -1)"', "cat <<EOF\n$(date)\nEOF",
                    "cat <<'EOF'\n$(touch x)\n`touch y`\nEOF", "cat <<EOF\n\\$(touch x)\nEOF",
                    "echo ${X:-default}", "echo ${X:-$(pwd)}", "echo '$(touch x)'",
                    "echo \"$(echo '$(touch x)')\"", 'echo "\\$(touch x)"', "echo $(( 1 + 2 ))",
                    "case x in a) ;; esac", "grep -n '`touch x`' f", "echo $(echo $(echo $(pwd)))",
                    'echo "${X#*$(pwd)}"', "echo ${#X} ${X[1]}", 'echo "<(touch x)"',
                    "echo ${X:-'`'}", "echo ${X:-'$('}", "echo ${X:-')'}"):
            self.assertIsNone(self.bash(cmd, atype="researcher"), cmd)
        for cmd in ("cat > n.md <<EOF\nsad :>( face, then <(touch x)\nEOF", '(( "$x" > 1 ))'):
            self.assertIsNone(self.bash(cmd), cmd)  # a heredoc's <( is text; a quoted arith operand
        commit = "git commit -m \"$(cat <<'EOF'\nFix `code` here\n\nNot run: $(touch x)\nEOF\n)\""
        self.assertIsNone(self.bash(commit), commit)

    def test_cluster_opts_stops_only_at_value_taking_letters(self):
        g = sp.Analyzer(self.ev("Bash", {"command": "true"}), POLICY, home=self.home)
        self.assertEqual(g.cluster_opts("-px", g.SHORT_VALUE["fd"]), {"p", "x"})  # -p is boolean
        self.assertEqual(g.cluster_opts("-Hx", g.SHORT_VALUE["fd"]), {"H", "x"})
        self.assertEqual(g.cluster_opts("-tf", g.SHORT_VALUE["fd"]), {"t"})  # -t takes f as value
        self.assertEqual(g.cluster_opts("-bo", g.SHORT_VALUE["sort"]), {"b", "o"})
        self.assertEqual(g.cluster_opts("-So", g.SHORT_VALUE["sort"]), {"S"})  # -S takes a value
        # round 5: tree's value letters take the next word, and these others take a value
        self.assertEqual(g.cluster_opts("-Lo", g.SHORT_VALUE["tree"]), {"L", "o"})
        for prog, token, want in (("sort", "-yo", {"y"}), ("date", "-sx", {"s"}),
                                  ("file", "-mC", {"m"}),
                                  ("fd", "-Ex", {"E"}), ("fd", "-ox", {"o"}),
                                  ("grep", "-dQ", {"d"}), ("ugrep", "-tQ", {"t"}),
                                  ("ugrep", "-NQ", {"N"})):
            self.assertEqual(g.cluster_opts(token, g.SHORT_VALUE[prog]), want, (prog, token))
        self.assertEqual(g.cluster_opts("-DO", g.GIT_GREP_VALUE), {"D", "O"})

    def test_the_scan_refuses_an_opener_with_no_close(self):
        for text in ("$(echo", "`echo", "${X:-$(echo}", "<(echo", "$((1+", "'abc"):
            with self.assertRaises(ValueError, msg=text):
                sp.substitutions(text)
        self.assertEqual(sp.substitutions("a `b \\`c\\`` $(d) ${X:-$(e)} '$(f)' \\$(g)"),
                         ["b `c`", "d", "e"])

    def test_the_scan_reads_quoting_as_the_shell_does(self):
        for text, bodies in ((r"$'\''$(a)\'", ["a"]), (r"${X:-'}'$(a)'}'}\'", ["a"]),
                             (r'''"`b \"'\"$(a)\"'\"`"''', [r'''b "'"$(a)"'"''']),
                             ("x <(a)", ["a"])):
            self.assertEqual(sp.substitutions(text), bodies, text)
        self.assertEqual(sp.substitutions("x <(a) $(b)", "heredoc"), ["b"])
        self.assertEqual(sp.substitutions("$$'\\'$(a)''"), ["a"])  # $$, then a plain '\\'
        with self.assertRaises(ValueError):
            sp.substitutions("x '")

    def test_parsed_substitutions_are_checked_even_where_the_scan_finds_none(self):
        with mock.patch.object(sp, "substitutions", return_value=[]):
            for cmd in ("echo $(touch x)", "echo `touch x`", "(( $(touch x) ))"):
                self.assertDenied(self.bash(cmd, atype="researcher"), "researcher-program",
                                  msg=cmd)

    def test_text_the_parser_keeps_elsewhere_is_refused(self):
        # A node field holding $, a backtick or <( that the policy doesn't read as text: refuse
        # rather than pass it unread.
        node = type("N", (), {})()
        node.kind, node.raw = "frob", "$(touch x)"
        g = sp.Analyzer(self.ev("Bash", {"command": "true"}), POLICY, home=self.home)
        with self.assertRaises(sp.Deny) as cm:
            g.node(node, self.proj, 0)
        self.assertEqual(cm.exception.rule, "unchecked-text")


class ZshOracle(unittest.TestCase):
    """unexpanded_spans against zsh itself: a marker the scan calls literal never runs."""

    def test_literal_spans_never_run(self):
        rng = random.Random(20261020)
        masked = ran = 0
        for _ in range(300):
            cmd, marks = zsh_case(rng)
            spans = sp.unexpanded_spans(cmd)[0]
            literal = {mid for i, kind, mid in marks
                       if any(a <= i < b and (kind == "P" or k != "double") for a, b, k in spans)}
            with tempfile.TemporaryDirectory() as d:
                subprocess.run(["zsh", "-f", "-c", cmd], cwd=d, capture_output=True, timeout=10,
                               env={"PATH": os.environ["PATH"], "HOME": d,
                                    "TMPPREFIX": os.path.join(d, "zsh")})
                try:
                    with open(os.path.join(d, "log")) as f:
                        logged = set(f.read().split())
                except FileNotFoundError:
                    logged = set()
            self.assertFalse(literal & logged, cmd)
            masked, ran = masked + len(literal), ran + len(logged)
        self.assertGreater(masked, 100)
        self.assertGreater(ran, 100)


class Deadline(Base):
    """The hard stop, against an index whose activation began in the past (no faked clock)."""

    def web(self, **kw):
        return self.decide("WebFetch", {"url": "https://example.com"}, **kw)

    def test_denied_at_and_past_the_stop_and_allowed_just_under_it(self):
        self.index("a1", minutes=59.5)
        self.assertIsNone(self.web())
        self.assertIsNone(self.bash("ls"))
        for minutes in (60, 61, 600):
            self.index("a1", minutes=minutes)
            self.assertDenied(self.web(), "deadline", "stop_and_explain", minutes)
            self.assertDenied(self.bash("ls"), "deadline", msg=minutes)

    def test_every_tool_but_the_allow_list_is_denied(self):
        self.index("a1", minutes=61)
        for tool, ti in (("Read", {"file_path": os.path.join(self.proj, "x")}),
                         ("WebSearch", {"query": "x"}), ("WebFetch", {"url": "https://x.org"}),
                         ("TaskCreate", {"subject": "x"}), ("Agent", {"prompt": "x"}),
                         ("mcp__notion__notion-fetch", {}), ("Write", "not a dict")):
            self.assertDenied(self.decide(tool, ti), "deadline", msg=tool)
        for tool in POLICY["deadline"]["allow"]:
            self.assertIsNone(self.decide(tool, {"message": "partial report"}), tool)
        # ToolSearch stays open: SendMessage is deferred for a teammate, so without its schema
        # a stopped teammate could not report (live check, 2.1.287). It only loads schemas.
        self.assertIsNone(self.decide("ToolSearch", {"query": "select:SendMessage"}))
        self.assertEqual(POLICY["deadline"]["allow"],
                         ["SubagentHandback", "SendMessage", "ToolSearch"])

    def test_each_role_has_its_own_budget_and_the_rest_get_default(self):
        self.meta("w1", agentType="writer", worktreePath=self.wt)
        for role, stop in (("Explore", 20), ("researcher", 40), ("reviewer", 40),
                           ("writer", 60), ("general-purpose", 60), ("workflow-subagent", 60),
                           ("plugin:some-agent", 60)):
            aid, cwd = ("w1", self.wt) if role == "writer" else ("a1", None)
            self.index(aid, minutes=stop - 0.5)
            self.assertIsNone(self.web(atype=role, aid=aid, cwd=cwd), role)
            self.index(aid, minutes=stop + 0.5)
            self.assertDenied(self.web(atype=role, aid=aid, cwd=cwd), "deadline", msg=role)

    def test_a_teammate_budget_comes_from_its_role_in_meta_json(self):
        self.meta("t1", agentType="team-x", name="team-x", customAgentType="Explore",
                  taskKind="in_process_teammate", teamName="session-s1")
        self.index("t1", minutes=21)
        self.assertDenied(self.web(atype="team-x", aid="t1"), "deadline")
        self.index("t2", minutes=21)  # no meta.json: its hook type gets the default budget
        self.assertIsNone(self.web(atype="team-x", aid="t2"))

    def test_the_index_is_keyed_without_the_agent_prefix(self):
        self.index("a1", minutes=61)
        self.assertDenied(self.web(aid="agent-a1"), "deadline")

    def test_no_index_or_a_bad_one_means_no_deadline(self):
        self.assertIsNone(self.web())
        agents = os.path.join(self.state, "dotclaude", "agents")
        os.makedirs(agents)
        for bad in ("{not json", "[]", json.dumps({"state": "running"}),
                    json.dumps({"activation_start": "yesterday"}),
                    json.dumps({"activation_start": None})):
            with open(os.path.join(agents, "a1.json"), "w") as f:
                f.write(bad)
            self.assertIsNone(self.web(), bad)

    def test_an_agent_cannot_rewrite_its_own_clock(self):
        # Wherever the state dir is: $XDG_STATE_HOME (set by Base), or the default under ~.
        for xdg, state in ((self.state, os.path.join(self.state, "dotclaude")),
                           (None, os.path.join(self.home, ".local", "state", "dotclaude"))):
            with mock.patch.dict(os.environ):
                if xdg is None:
                    os.environ.pop("XDG_STATE_HOME")
                for path in (os.path.join(state, "agents", "a1.json"),
                             os.path.join(state, "delegations.jsonl")):
                    self.assertDenied(self.decide("Write", {"file_path": path, "content": "{}"}),
                                      "protected-path", "hard_stop", path)
                    self.assertDenied(self.decide("Edit", {"file_path": path}), "protected-path",
                                      msg=path)


REPORT_PATH = 'allow = ["SubagentHandback", "SendMessage", "ToolSearch"]\n'


def policy_with_deadline(body):
    """policy.toml's text with its [deadline] table's body replaced, in a temp file."""
    with open(os.path.join(REPO, "skills", "delegation", "policy.toml")) as f:
        text = f.read()
    text, n = re.subn(r"(?ms)^\[deadline\]\n.*?(?=^\[)", "[deadline]\n" + body + "\n\n", text)
    assert n == 1, "policy.toml has no [deadline] table"
    fd, path = tempfile.mkstemp(suffix=".toml")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


class PolicyFile(unittest.TestCase):
    def test_the_shipped_budgets(self):
        for role, minutes in (("Explore", (10, 20)), ("researcher", (20, 40)),
                              ("reviewer", (20, 40)), ("writer", (30, 60)),
                              ("general-purpose", (30, 60)), ("allow", (30, 60))):
            self.assertEqual(sp.dc.deadline_for(POLICY, role), (minutes[0] * 60, minutes[1] * 60),
                             role)

    def test_a_malformed_deadline_table_fails_closed(self):
        allow = REPORT_PATH
        default = "\ndefault = { nudge_min = 30 }"
        bodies = [allow + "default = " + b for b in (
            "{ nudge_min = 0 }", "{ nudge_min = -1 }", '{ nudge_min = "30" }',
            "{ nudge_min = true }", "{ nudge_min = nan }", "{ nudge_min = inf }",
            "{ nudge_min = 30, stop_min = 30 }", "{ nudge_min = 30, stop_min = 20 }",
            "{ nudge_min = 30, stop_mins = 90 }", "{ stop_min = 60 }", "30")]
        bodies += [allow + "Explore = { nudge_min = 10 }",  # no default
                   allow + "default = { nudge_min = 30 }\nwriter = { nudge_min = 0 }",
                   default, 'allow = "SubagentHandback"' + default, "allow = [1]" + default,
                   # An allow list without the whole report path would trap a stopped agent:
                   # empty, misspelled, or missing any one of the three (Codex review).
                   "allow = []" + default,
                   'allow = ["SubagentHandbak", "SendMessage", "ToolSearch"]' + default,
                   'allow = ["SubagentHandback", "SendMessage"]' + default,
                   'allow = ["SendMessage", "ToolSearch"]' + default]
        for body in bodies:
            path = policy_with_deadline(body)
            try:
                with self.assertRaises(ValueError, msg=body):
                    sp.load_policy(path)
            finally:
                os.remove(path)

    def test_fractional_minutes_and_an_explicit_stop_load(self):
        path = policy_with_deadline(REPORT_PATH + "default = { nudge_min = 0.1, stop_min = 0.4 }")
        try:
            p = sp.load_policy(path)
        finally:
            os.remove(path)
        nudge, stop = sp.dc.deadline_for(p, "general-purpose")
        self.assertAlmostEqual(nudge, 6)
        self.assertAlmostEqual(stop, 24)

    def test_an_allow_list_may_add_to_the_report_path(self):
        path = policy_with_deadline('allow = ["SubagentHandback", "SendMessage", "ToolSearch", '
                                    '"TaskList"]\ndefault = { nudge_min = 30 }')
        try:
            self.assertIn("TaskList", sp.load_policy(path)["deadline"]["allow"])
        finally:
            os.remove(path)

    def test_a_missing_deadline_table_fails_closed(self):
        with open(os.path.join(REPO, "skills", "delegation", "policy.toml")) as f:
            text = re.sub(r"(?ms)^\[deadline\]\n.*?(?=^\[)", "", f.read())
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(text)
        try:
            with self.assertRaises(ValueError):
                sp.load_policy(f.name)
        finally:
            os.remove(f.name)

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
