"""Every delegation reader of Claude Code's config dir goes through dc.config_dir:
$CLAUDE_CONFIG_DIR when set, else ~/.claude. The sessions readers (claude_ancestor, live_sessions,
session_toplevel), the user settings sandbox_paths and subagent-policy read, subagent-policy's
shell snapshots, the transcripts `sandbox-denials` scans and the shim check_guard_shim runs. Under a temp HOME and config dir whose files the tests
write; each case also writes a decoy in the other place, so only the right one can pass."""
import json
import os
import subprocess
import tempfile
import types
import unittest
from unittest import mock

from _paths import SCRIPTS, load_script

dc = load_script("delegation_common.py")
checks = load_script("delegation_checks.py")
sp = load_script("subagent-policy")
LEDGER = os.path.join(SCRIPTS, "delegation-ledger")


class ConfigDir(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.join(tmp.name, "home")
        self.home_cfg = os.path.join(self.home, ".claude")
        self.cfg = os.path.join(tmp.name, "cfg")
        env = mock.patch.dict(os.environ, {"HOME": self.home, "CLAUDE_CONFIG_DIR": self.cfg,
                                           "XDG_STATE_HOME": os.path.join(tmp.name, "state")})
        env.start()
        self.addCleanup(env.stop)
        for name in ("CLAUDE_PID", "SANDBOX_RUNTIME", "DELEGATION_POLICY"):
            os.environ.pop(name, None)
        self.repo = os.path.join(tmp.name, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def session_file(self, config_dir):
        """A sessions file under `config_dir` naming this process's parent as session "s"."""
        pid = os.getppid()
        self.write(os.path.join(config_dir, "sessions", f"{pid}.json"), json.dumps(
            {"pid": pid, "procStart": dc.proc_start(pid), "sessionId": "s", "cwd": self.repo}))

    def assert_sessions_found(self):
        self.assertEqual(dc.claude_ancestor(), (os.getppid(), dc.proc_start(os.getppid()), "s"))
        self.assertEqual(dc.live_sessions(), {"s": os.getppid()})
        self.assertEqual(dc.session_toplevel("s"), os.path.realpath(self.repo))

    def test_the_sessions_readers_follow_claude_config_dir(self):
        self.session_file(self.cfg)
        self.assert_sessions_found()

    def test_the_sessions_readers_skip_home_when_claude_config_dir_is_set(self):
        self.session_file(self.home_cfg)
        self.assertIsNone(dc.claude_ancestor())
        self.assertEqual(dc.live_sessions(), {})
        self.assertIsNone(dc.session_toplevel("s"))

    def test_without_claude_config_dir_the_sessions_readers_read_home(self):
        os.environ.pop("CLAUDE_CONFIG_DIR")
        self.session_file(self.home_cfg)
        self.assert_sessions_found()

    def test_sandbox_paths_reads_the_config_dirs_user_settings(self):
        for where, root in ((self.cfg, "/deny-cfg"), (self.home_cfg, "/deny-home")):
            self.write(os.path.join(where, "settings.json"), json.dumps(
                {"sandbox": {"filesystem": {"denyRead": [root]}}}))
        read_denied = dc.sandbox_paths()[0]
        self.assertIn("/deny-cfg", read_denied)
        self.assertNotIn("/deny-home", read_denied)
        os.environ.pop("CLAUDE_CONFIG_DIR")
        read_denied = dc.sandbox_paths()[0]
        self.assertIn("/deny-home", read_denied)
        self.assertNotIn("/deny-cfg", read_denied)

    def test_subagent_policy_reads_the_config_dirs_user_settings(self):
        for where, root in ((self.cfg, "/deny-cfg"), (self.home_cfg, "/deny-home")):
            self.write(os.path.join(where, "settings.json"), json.dumps(
                {"sandbox": {"filesystem": {"denyRead": [root]}}}))

        def user_roots():
            return [r for tier, s in sp.settings_tiers(self.repo, self.home) if tier == "user"
                    for r in (((s or {}).get("sandbox") or {}).get("filesystem") or {})
                    .get("denyRead", [])]
        self.assertEqual(user_roots(), ["/deny-cfg"])
        os.environ.pop("CLAUDE_CONFIG_DIR")
        self.assertEqual(user_roots(), ["/deny-home"])

    def test_subagent_policy_reads_the_config_dirs_shell_snapshots(self):
        for where, d in ((self.cfg, "/cfg-bin"), (self.home_cfg, "/home-bin")):
            self.write(os.path.join(where, "shell-snapshots", "snapshot-zsh.sh"),
                       f"export PATH='{d}'\n")

        def path_dirs():
            return sp.Analyzer._path_dirs(types.SimpleNamespace(home=self.home))
        self.assertIn("/cfg-bin", path_dirs())
        self.assertNotIn("/home-bin", path_dirs())
        os.environ.pop("CLAUDE_CONFIG_DIR")
        self.assertIn("/home-bin", path_dirs())
        self.assertNotIn("/cfg-bin", path_dirs())

    def test_sandbox_denials_scans_the_config_dirs_transcripts(self):
        for where, host in ((self.cfg, "cfg.example"), (self.home_cfg, "home.example")):
            self.write(os.path.join(where, "projects", "-p", "s.jsonl"), json.dumps(
                {"type": "user", "message": {"content": [{
                    "type": "tool_result", "content": "<sandbox_violations>\ndeny "
                    f"network-outbound {host}:443 (user denied)\n</sandbox_violations>"}]}}) + "\n")

        def denials():
            p = subprocess.run(["python3", LEDGER, "sandbox-denials"], capture_output=True,
                               text=True, env=dict(os.environ))
            self.assertEqual(p.returncode, 0, p.stderr)
            return p.stdout
        out = denials()
        self.assertIn("cfg.example:443", out)
        self.assertNotIn("home.example", out)
        os.environ.pop("CLAUDE_CONFIG_DIR")
        out = denials()
        self.assertIn("home.example:443", out)
        self.assertNotIn("cfg.example", out)

    def test_check_guard_shim_looks_in_the_config_dir(self):
        self.assertEqual(checks.check_guard_shim(),
                         (False, f"{self.cfg}/hooks/watch-guard.sh is missing"))
        os.environ.pop("CLAUDE_CONFIG_DIR")
        self.assertEqual(checks.check_guard_shim(),
                         (False, f"{self.home_cfg}/hooks/watch-guard.sh is missing"))


if __name__ == "__main__":
    unittest.main()
