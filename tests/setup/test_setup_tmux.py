"""setup-tmux.sh: links the status, restore and saved-chats scripts, upserts one marked
source-file block into ~/.tmux.conf, keeps the user's own lines, and is idempotent (stdlib
only)."""
import glob
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "setup-tmux.sh")


class SetupTmux(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        stubs = os.path.join(self.home, "stubs")
        os.mkdir(stubs)
        with open(os.path.join(stubs, "tmux"), "w") as f:
            f.write("#!/usr/bin/env bash\nexit 1\n")  # `tmux info` fails: no server running
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        self.env = {**os.environ, "HOME": self.home,
                    "PATH": stubs + os.pathsep + os.environ["PATH"]}
        self.conf = os.path.join(self.home, ".tmux.conf")

    def run_setup(self, *args):
        p = subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True,
                           timeout=30, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def read(self):
        with open(self.conf) as f:
            return f.read()

    def test_the_installers_are_executable(self):
        # README says ./setup-tmux.sh; the other tests call it through bash, which hides a mode bug.
        for path in (SCRIPT, os.path.join(REPO, "tmux", "tmux-claude-status"),
                     os.path.join(REPO, "tmux", "claude-restore"),
                     os.path.join(REPO, "tmux", "claude-saved")):
            with self.subTest(path=path):
                self.assertTrue(os.access(path, os.X_OK))

    def test_a_fresh_home_gets_the_link_and_the_claude_block(self):
        self.run_setup()
        for name in ("tmux-claude-status", "claude-restore", "claude-saved"):
            link = os.path.join(self.home, ".local", "bin", name)
            self.assertEqual(os.readlink(link), os.path.join(REPO, "tmux", name))
        conf = self.read()
        self.assertIn(f'source-file "{REPO}/tmux/claude.conf"', conf)
        self.assertNotIn("base.conf", conf)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".tmux-cheatsheet.txt")))

    def test_own_lines_are_kept_and_the_block_goes_last(self):
        with open(self.conf, "w") as f:
            f.write("set -g mouse off\n# mine\n")
        self.run_setup()
        conf = self.read()
        self.assertTrue(conf.startswith("set -g mouse off\n# mine\n"))
        self.assertTrue(conf.rstrip().endswith("# <<< dotclaude tmux <<<"))
        self.assertEqual(len(glob.glob(self.conf + ".pre-dotclaude-*")), 1)

    def test_a_rerun_changes_nothing(self):
        self.run_setup("--base")
        first = self.read()
        p = self.run_setup("--base")
        self.assertEqual(self.read(), first)
        self.assertIn("already up to date", p.stdout)
        self.assertEqual(first.count("dotclaude tmux (setup-tmux.sh)"), 1)

    def test_base_adds_and_a_plain_run_keeps_base_conf(self):
        # A plain re-run (say, to link a new script) once dropped base.conf, and the next tmux
        # server came up with no mouse or menus.
        self.run_setup("--base")
        conf = self.read()
        self.assertLess(conf.index("base.conf"), conf.index("claude.conf"))
        cheat = os.path.join(self.home, ".tmux-cheatsheet.txt")
        self.assertEqual(os.readlink(cheat), os.path.join(REPO, "tmux", "cheatsheet.txt"))
        p = self.run_setup()
        self.assertEqual(self.read(), conf)
        self.assertIn("already up to date", p.stdout)
        self.assertEqual(os.readlink(cheat), os.path.join(REPO, "tmux", "cheatsheet.txt"))

    def test_no_base_removes_base_conf_and_the_cheatsheet_link(self):
        self.run_setup("--base")
        self.run_setup("--no-base")
        conf = self.read()
        self.assertNotIn("base.conf", conf)
        self.assertIn("claude.conf", conf)
        self.assertFalse(os.path.lexists(os.path.join(self.home, ".tmux-cheatsheet.txt")))

    def test_base_and_no_base_together_are_rejected(self):
        p = subprocess.run(["bash", SCRIPT, "--base", "--no-base"], capture_output=True,
                           text=True, timeout=30, env=self.env)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(os.path.exists(self.conf))

    def test_a_real_file_in_the_way_is_moved_aside(self):
        bin_dir = os.path.join(self.home, ".local", "bin")
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "tmux-claude-status"), "w") as f:
            f.write("old\n")
        self.run_setup()
        self.assertTrue(os.path.islink(os.path.join(bin_dir, "tmux-claude-status")))
        self.assertEqual(len(glob.glob(os.path.join(bin_dir, "tmux-claude-status.pre-dotclaude-*"))), 1)

    def test_the_confs_parse_in_real_tmux(self):
        tmux = shutil.which("tmux", path=os.environ["PATH"])
        if not tmux:
            self.skipTest("tmux not installed")
        sock = os.path.join(self.home, "sock")
        for name in ("claude.conf", "base.conf"):
            with self.subTest(conf=name):
                p = subprocess.run([tmux, "-S", sock, "-f", "/dev/null", "new-session", "-d", ";",
                                    "source-file", os.path.join(REPO, "tmux", name)],
                                   capture_output=True, text=True, timeout=10)
                subprocess.run([tmux, "-S", sock, "kill-server"], capture_output=True)
                if "Operation not permitted" in p.stderr:
                    self.skipTest("the Bash sandbox blocks tmux's socket; run outside it")
                self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
