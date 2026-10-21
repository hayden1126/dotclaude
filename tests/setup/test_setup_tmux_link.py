"""setup-tmux.sh replaces each installed path with one rename, so it doesn't go missing, not even
between two commands: its links go through setup.sh's swap helpers, copied verbatim and kept
byte-equal here, and its ~/.tmux.conf lands with one os.replace (stdlib only).

The link tests cut setup-tmux.sh from its swap helpers through link() and run that in bash on a
temp home, with test_setup_link's shims first on PATH: a shim runs the real command, then logs
`missing <path> after <tool> ...` when the watched path is gone. The ~/.tmux.conf tests run the
whole script on a fake HOME with a stub tmux, as test_setup_tmux does."""
import glob
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_setup_link as harness  # noqa: E402  (on sys.path from the line above)

REPO = harness.REPO
SETUP = harness.SETUP
SCRIPT = os.path.join(REPO, "setup-tmux.sh")
write, read = harness.write, harness.read
# The first line of each helper setup-tmux.sh copies from setup.sh.
HELPERS = ('case "$(uname -s)" in MINGW*', "swap_tmp() {", "swap_in() {")


def section():
    """setup-tmux.sh from its swap helpers' header through the end of link()."""
    text = read(SCRIPT)
    start = text.index("# Swap helpers, copied verbatim from setup.sh")
    return text[start:text.index("\n}\n", text.index("\nlink() {")) + 3]


def shell_part(text):
    """text without its python heredocs."""
    while "<<'PY'\n" in text:
        start = text.index("<<'PY'\n")
        text = text[:start] + text[text.index("\nPY\n", start) + 4:]
    return text


def heredoc(text):
    """The python heredoc of setup-tmux.sh."""
    start = text.index("<<'PY'\n") + len("<<'PY'\n")
    return text[start:text.index("\nPY\n", start)]


def helper(text, head):
    """The item whose line starts with head (a function runs to its closing brace), with the
    comment lines right above it."""
    start = text.index("\n" + head) + 1
    above = text[:start].splitlines(keepends=True)
    while above and above[-1].startswith("#"):
        above.pop()
    end = text.index("\n}\n", start) + 3 if head.endswith("{") else text.index("\n", start) + 1
    return text[len("".join(above)):end]


def mode(path):
    return os.stat(path).st_mode & 0o777


class Link(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        j = os.path.join
        self.home, self.repo, self.old = j(self.tmp, "home"), j(self.tmp, "repo"), j(self.tmp, "old")
        self.bin = j(self.home, ".local", "bin")
        self.log = j(self.tmp, "watch.log")
        for root, text in ((self.repo, "new"), (self.old, "old")):
            write(j(root, "tmux", "status"), f"{text}\n")
            write(j(root, "tmux", "dir", "x"), f"{text}\n")
        bins = j(self.tmp, "shims")
        os.makedirs(bins)
        for name in harness.TOOLS:
            real = shutil.which(name)
            self.assertIsNotNone(real, name)
            write(j(bins, name), harness.SHIM % {"name": name, "real": real})
            os.chmod(j(bins, name), 0o755)
        self.env = dict(os.environ, PATH=bins + os.pathsep + os.environ["PATH"], WATCH_LOG=self.log)

    def run_sh(self, body, watch=None, **env):
        """body after the cut, run in bash -eu like setup-tmux.sh, watching watch. Its own
        session, so an INTERRUPT_TOOL Ctrl-C reaches only the script."""
        script = ("set -euo pipefail\nTS=1\nsay() { printf '%s\\n' \"$*\"; }\n"
                  "warn() { printf '%s\\n' \"$*\" >&2; }\n" + section() + "\n" + body)
        p = subprocess.Popen(["bash", "-c", script], env=dict(self.env, WATCH=watch or "", **env),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
        out, err = p.communicate(timeout=30)
        return subprocess.CompletedProcess(p.args, p.returncode, out, err)

    def link(self, src, dst, **env):
        r = self.run_sh(f'link "{src}" "{dst}"', watch=dst, **env)
        if not env:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def plant(self, target, dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.symlink(target, dst)

    def gaps(self):
        return read(self.log).splitlines() if os.path.exists(self.log) else []

    def leftovers(self):
        return [os.path.join(d, n) for d, dirs, names in os.walk(self.home)
                for n in dirs + names if ".dotclaude-" in n]

    def backups(self, dst):
        return glob.glob(dst + ".pre-dotclaude-*")

    def test_the_harness_sees_a_remove_then_link(self):
        # The shims must catch a gap, or every other test passes vacuously: a plain rm then ln,
        # and the old link()'s mv aside then ln -sfn over a real file.
        dst, src = os.path.join(self.bin, "status"), os.path.join(self.repo, "tmux", "status")
        self.plant(os.path.join(self.old, "tmux", "status"), dst)
        r = self.run_sh(f'rm "{dst}"\nln -s "{src}" "{dst}"', watch=dst)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.gaps(), [f"missing {dst} after rm {dst}"])
        os.remove(self.log)
        os.remove(dst)
        write(dst, "mine\n")
        r = self.run_sh(f'mv "{dst}" "{dst}.bak"\nln -sfn "{src}" "{dst}"', watch=dst)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.gaps(), [f"missing {dst} after mv {dst} {dst}.bak"])

    def test_the_swap_is_one_os_replace_and_nothing_removes_first(self):
        # The shims check between commands only: a swap that removed dst inside one process
        # would pass them, so the swap's own code is pinned here.
        shell = shell_part(read(SCRIPT))
        self.assertEqual(shell.count("os.replace(sys.argv[1], sys.argv[2])"), 1)
        self.assertNotIn("ln -sf", read(SCRIPT))
        for call in ("os.remove", "os.unlink", "os.rename(", "rmdir"):
            self.assertNotIn(call, section())

    def test_the_swap_helpers_match_setup_sh(self):
        ours, theirs = read(SCRIPT), read(SETUP)
        for head in HELPERS:
            with self.subTest(head=head):
                self.assertEqual(ours.count("\n" + head), 1)
                self.assertEqual(theirs.count("\n" + head), 1)
                copied = helper(ours, head)
                self.assertTrue(copied.startswith("#"), copied)
                self.assertEqual(copied, helper(theirs, head))

    def test_a_link_is_relinked_without_a_gap(self):
        dst, src = os.path.join(self.bin, "status"), os.path.join(self.repo, "tmux", "status")
        self.plant(os.path.join(self.old, "tmux", "status"), dst)
        for _ in range(2):  # the second run relinks to the same source
            r = self.link(src, dst)
            self.assertEqual(r.stdout, f"linked {dst} -> {src}\n")
        self.assertEqual(self.gaps(), [])
        self.assertEqual(os.readlink(dst), src)
        self.assertEqual(self.backups(dst), [])
        self.assertEqual(self.leftovers(), [])

    def test_a_link_to_a_dir_is_replaced_not_entered(self):
        # A plain `mv tmp dst` would follow dst and drop the new link inside the old dir.
        dst, src = os.path.join(self.bin, "dir"), os.path.join(self.repo, "tmux", "dir")
        self.plant(os.path.join(self.old, "tmux", "dir"), dst)
        self.link(src, dst)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(os.readlink(dst), src)
        self.assertEqual(os.listdir(os.path.join(self.old, "tmux", "dir")), ["x"])
        self.assertEqual(os.listdir(src), ["x"])
        self.assertEqual(self.leftovers(), [])

    def test_a_first_install_over_a_real_file_backs_it_up_without_a_gap(self):
        dst, src = os.path.join(self.bin, "status"), os.path.join(self.repo, "tmux", "status")
        write(dst, "mine\n")
        os.chmod(dst, 0o751)
        r = self.link(src, dst)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(os.readlink(dst), src)
        backup = f"{dst}.pre-dotclaude-1"
        self.assertEqual(self.backups(dst), [backup])
        self.assertEqual(read(backup), "mine\n")
        self.assertEqual(mode(backup), 0o751)
        self.assertEqual(r.stderr, f"backed up the existing {dst} to {backup}\n")
        self.assertEqual(self.leftovers(), [])

    def test_a_real_dir_is_moved_aside_then_linked(self):
        # rename can't put a link over a dir: this one-time move keeps its gap, and only it.
        dst, src = os.path.join(self.bin, "dir"), os.path.join(self.repo, "tmux", "dir")
        write(os.path.join(dst, "mine"), "mine\n")
        r = self.link(src, dst)
        backup = f"{dst}.pre-dotclaude-1"
        self.assertEqual(self.gaps()[0], f"missing {dst} after mv {dst} {backup}")
        self.assertEqual(os.readlink(dst), src)
        self.assertEqual(read(os.path.join(backup, "mine")), "mine\n")
        self.assertEqual(r.stderr, f"moved the existing {dst} to {backup}\n")
        self.assertEqual(self.leftovers(), [])

    @unittest.skipIf(os.geteuid() == 0, "root reads a mode-0 file")
    def test_a_real_file_cp_cannot_read_is_moved_aside(self):
        dst, src = os.path.join(self.bin, "status"), os.path.join(self.repo, "tmux", "status")
        write(dst, "mine\n")
        os.chmod(dst, 0)
        self.link(src, dst)
        backup = f"{dst}.pre-dotclaude-1"
        os.chmod(backup, 0o600)
        self.assertEqual(read(backup), "mine\n")
        self.assertEqual(os.readlink(dst), src)
        self.assertEqual(self.leftovers(), [])

    def test_a_failed_swap_keeps_the_old_link_and_leaves_no_temp(self):
        dst = os.path.join(self.bin, "status")
        self.plant(os.path.join(self.old, "tmux", "status"), dst)
        r = self.link(os.path.join(self.repo, "tmux", "status"), dst, FAIL_TOOL="python3")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("linked", r.stdout)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(os.readlink(dst), os.path.join(self.old, "tmux", "status"))
        self.assertEqual(self.leftovers(), [])

    def test_a_failed_swap_over_a_real_file_keeps_it_in_place(self):
        dst = os.path.join(self.bin, "status")
        write(dst, "mine\n")
        r = self.link(os.path.join(self.repo, "tmux", "status"), dst, FAIL_TOOL="python3")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.gaps(), [])
        self.assertFalse(os.path.islink(dst))
        self.assertEqual(read(dst), "mine\n")
        self.assertEqual(read(f"{dst}.pre-dotclaude-1"), "mine\n")
        self.assertEqual(self.leftovers(), [])

    def test_a_ctrl_c_mid_swap_keeps_the_old_link_and_leaves_no_temp(self):
        # Most of a link's time is python3 starting, so that is where a Ctrl-C lands.
        dst = os.path.join(self.bin, "dir")
        self.plant(os.path.join(self.old, "tmux", "dir"), dst)
        r = self.link(os.path.join(self.repo, "tmux", "dir"), dst, INTERRUPT_TOOL="python3")
        # Killed by the signal: bash re-raises SIGINT after the exit trap.
        self.assertEqual(r.returncode, -signal.SIGINT, r.stderr)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(os.readlink(dst), os.path.join(self.old, "tmux", "dir"))
        self.assertEqual(self.leftovers(), [])

    def test_a_dead_runs_temp_beside_dst_is_swept(self):
        dst, src = os.path.join(self.bin, "status"), os.path.join(self.repo, "tmux", "status")
        self.plant(os.path.join(self.old, "tmux", "status"), dst)
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.plant(os.path.join(self.old, "tmux", "dir"), os.path.join(self.bin, f".status.dotclaude-{dead.pid}"))
        self.link(src, dst)
        self.assertEqual(os.readlink(dst), src)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(self.leftovers(), [])


class TmuxConf(unittest.TestCase):
    """The ~/.tmux.conf write, through the whole script."""

    def setUp(self):
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home)
        stubs = os.path.join(self.home, "stubs")
        write(os.path.join(stubs, "tmux"), "#!/usr/bin/env bash\nexit 1\n")  # no server running
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        self.env = {**os.environ, "HOME": self.home,
                    "PATH": stubs + os.pathsep + os.environ["PATH"]}
        self.conf = os.path.join(self.home, ".tmux.conf")
        self.block = ("# >>> dotclaude tmux (setup-tmux.sh) >>>\n"
                      f'source-file "{REPO}/tmux/claude.conf"\n# <<< dotclaude tmux <<<\n')

    def run_setup(self, umask="022"):
        p = subprocess.run(["bash", "-c", f'umask {umask} && exec bash "$0"', SCRIPT],
                           capture_output=True, text=True, timeout=30, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(f"==> wrote the dotclaude block in {self.conf}\n", p.stdout)
        return p

    def leftovers(self):
        return [os.path.join(d, n) for d, dirs, names in os.walk(self.home)
                for n in dirs + names if ".dotclaude-" in n]

    def test_the_write_is_one_os_replace(self):
        py = heredoc(read(SCRIPT))
        self.assertNotIn('open(path, "w")', py)
        self.assertEqual(py.count("os.replace("), 1)

    def test_a_symlinked_conf_is_written_through_and_stays_a_link(self):
        target = os.path.join(self.home, "dotfiles", "tmux.conf")
        write(target, "set -g mouse off\n")
        os.chmod(target, 0o640)
        os.symlink(target, self.conf)
        self.run_setup()
        self.assertEqual(os.readlink(self.conf), target)
        self.assertEqual(read(target), "set -g mouse off\n\n" + self.block)
        self.assertEqual(mode(target), 0o640)
        backups = glob.glob(self.conf + ".pre-dotclaude-*")
        self.assertEqual(len(backups), 1)
        self.assertEqual(read(backups[0]), "set -g mouse off\n")
        self.assertEqual(self.leftovers(), [])

    def test_a_dangling_link_gets_its_target_made(self):
        target = os.path.join(self.home, "dotfiles", "tmux.conf")
        os.makedirs(os.path.dirname(target))
        os.symlink(target, self.conf)
        self.run_setup(umask="027")
        self.assertEqual(os.readlink(self.conf), target)
        self.assertEqual(read(target), self.block)
        self.assertEqual(mode(target), 0o640)
        self.assertEqual(self.leftovers(), [])

    def test_a_real_conf_keeps_its_mode(self):
        # 0o604 is neither mkstemp's 0o600 nor what the umask would give.
        write(self.conf, "# mine\n")
        os.chmod(self.conf, 0o604)
        self.run_setup()
        self.assertFalse(os.path.islink(self.conf))
        self.assertEqual(read(self.conf), "# mine\n\n" + self.block)
        self.assertEqual(mode(self.conf), 0o604)
        self.assertEqual(self.leftovers(), [])

    def test_a_fresh_conf_gets_the_umask_mode(self):
        self.run_setup(umask="027")
        self.assertFalse(os.path.islink(self.conf))
        self.assertEqual(read(self.conf), self.block)
        self.assertEqual(mode(self.conf), 0o640)
        self.assertEqual(glob.glob(self.conf + ".pre-dotclaude-*"), [])
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()
