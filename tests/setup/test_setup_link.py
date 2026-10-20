"""setup.sh's link helpers (its section 1): each link and each settings.json copy lands with one
rename, so an installed path never goes missing, not even between two commands (stdlib only).

Each test cuts section 1 out of setup.sh and runs it in bash on a temp machine, with shims first
on PATH for the commands it runs. A shim runs the real command, then logs a line when the watched
path is gone, so a remove-then-link shows up as `missing <path> after rm ...`."""
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETUP = os.path.join(REPO, "setup.sh")
TOOLS = ("rm", "ln", "mv", "cp", "mkdir", "python3", "dirname", "basename", "cmp", "uname")

# Runs the real tool, then checks the watched path. The tool FAKE_TOOL names prints FAKE_OUT
# instead, FAIL_TOOL's fails at once, and INTERRUPT_TOOL's sends its process group a Ctrl-C.
SHIM = """#!/bin/bash
[[ ${FAKE_TOOL:-} == %(name)s ]] && { printf '%%s\\n' "$FAKE_OUT"; exit 0; }
[[ ${FAIL_TOOL:-} == %(name)s ]] && exit 1
[[ ${INTERRUPT_TOOL:-} == %(name)s ]] && { kill -INT 0; sleep 5; }
%(real)s "$@"
rc=$?
if [[ -n ${WATCH:-} && ! -e $WATCH && ! -L $WATCH ]]; then
  printf 'missing %%s after %%s %%s\\n' "$WATCH" %(name)s "$*" >> "$WATCH_LOG"
fi
exit $rc
"""


def section():
    """setup.sh from its `# 1. Symlink helpers` header up to `# 2. Single files`."""
    with open(SETUP) as f:
        text = f.read()
    return text[text.index("# 1. Symlink helpers"):text.index("# 2. Single files")]


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


class Swap(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        j = os.path.join
        self.claude, self.repo, self.old = j(self.tmp, "claude"), j(self.tmp, "repo"), j(self.tmp, "old")
        self.backup = j(self.claude, "backups", "pre-dotclaude-1")
        self.log = j(self.tmp, "watch.log")
        for root, text in ((self.repo, "new"), (self.old, "old")):
            write(j(root, "CLAUDE.md"), f"{text}\n")
            write(j(root, "skills", "s1", "SKILL.md"), f"{text}\n")
        bins = j(self.tmp, "shims")
        os.makedirs(bins)
        for name in TOOLS:
            real = shutil.which(name)
            self.assertIsNotNone(real, name)
            write(j(bins, name), SHIM % {"name": name, "real": real})
            os.chmod(j(bins, name), 0o755)
        self.env = dict(os.environ, PATH=bins + os.pathsep + os.environ["PATH"],
                        CLAUDE_DIR=self.claude, BACKUP_DIR=self.backup, WATCH_LOG=self.log)

    def run_sh(self, body, watch=None, **env):
        """body after section 1, in bash -eu like setup.sh, watching watch. Its own session, so
        an INTERRUPT_TOOL Ctrl-C reaches only the script."""
        script = "set -euo pipefail\nsay() { printf '%s\\n' \"$*\"; }\n" + section() + "\n" + body
        return subprocess.run(["bash", "-c", script], env=dict(self.env, WATCH=watch or "", **env),
                              capture_output=True, text=True, timeout=30, start_new_session=True)

    def gaps(self):
        return read(self.log).splitlines() if os.path.exists(self.log) else []

    def leftovers(self):
        return [os.path.join(d, n) for d, dirs, names in os.walk(self.claude)
                for n in dirs + names if ".dotclaude-" in n]

    def link(self, src, dst, **env):
        r = self.run_sh(f'link "{src}" "{dst}"', watch=dst, **env)
        if not env:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def plant(self, target, dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.symlink(target, dst)

    def test_the_harness_sees_a_remove_then_link(self):
        # The pre-fix link(): the shims must catch its gap, or every other test passes vacuously.
        dst = os.path.join(self.claude, "CLAUDE.md")
        self.plant(os.path.join(self.old, "CLAUDE.md"), dst)
        r = self.run_sh(f'rm "{dst}"\nln -s "{self.repo}/CLAUDE.md" "{dst}"', watch=dst)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.gaps(), [f"missing {dst} after rm {dst}"])

    def test_the_swap_is_one_os_replace(self):
        # The shims check between commands only: a swap that removed dst inside one process
        # would pass them, so the swap's own code is pinned here.
        text = section()
        self.assertEqual(text.count("os.replace(sys.argv[1], sys.argv[2])"), 1)
        for call in ("os.remove", "os.unlink", "os.rename(", "rmdir"):
            self.assertNotIn(call, text)

    def test_a_link_to_a_file_is_relinked_without_a_gap(self):
        dst = os.path.join(self.claude, "CLAUDE.md")
        self.plant(os.path.join(self.old, "CLAUDE.md"), dst)
        for _ in range(2):  # the second run relinks to the same source
            r = self.link(os.path.join(self.repo, "CLAUDE.md"), dst)
            self.assertEqual(r.stdout, "linked CLAUDE.md -> repo\n")
        self.assertEqual(self.gaps(), [])
        self.assertEqual(os.readlink(dst), os.path.join(self.repo, "CLAUDE.md"))
        self.assertFalse(os.path.exists(self.backup))
        self.assertEqual(self.leftovers(), [])

    def test_a_link_to_a_dir_is_replaced_not_entered(self):
        # A plain `mv tmp dst` would follow dst and drop the new link inside the old skill dir.
        dst = os.path.join(self.claude, "skills", "s1")
        self.plant(os.path.join(self.old, "skills", "s1"), dst)
        self.link(os.path.join(self.repo, "skills", "s1"), dst)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(os.readlink(dst), os.path.join(self.repo, "skills", "s1"))
        self.assertEqual(os.listdir(os.path.join(self.old, "skills", "s1")), ["SKILL.md"])
        self.assertEqual(os.listdir(os.path.join(self.repo, "skills", "s1")), ["SKILL.md"])
        self.assertEqual(self.leftovers(), [])

    def test_a_real_file_is_backed_up_and_never_missing(self):
        dst = os.path.join(self.claude, "hooks", "a.sh")
        write(dst, "mine\n")
        r = self.link(os.path.join(self.repo, "CLAUDE.md"), dst)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(read(os.path.join(self.backup, "hooks", "a.sh")), "mine\n")
        self.assertEqual(os.readlink(dst), os.path.join(self.repo, "CLAUDE.md"))
        self.assertIn(f"backing up {dst}\n", r.stdout)
        self.assertEqual(self.leftovers(), [])

    def test_a_real_dir_is_moved_to_the_backup_then_linked(self):
        # rename can't replace a non-empty dir: this one-time move keeps its gap, so no watch.
        dst = os.path.join(self.claude, "skills", "s1")
        write(os.path.join(dst, "mine.md"), "mine\n")
        self.link(os.path.join(self.repo, "skills", "s1"), dst)
        self.assertEqual(read(os.path.join(self.backup, "skills", "s1", "mine.md")), "mine\n")
        self.assertEqual(os.readlink(dst), os.path.join(self.repo, "skills", "s1"))
        self.assertEqual(self.leftovers(), [])

    def test_a_missing_target_and_parent_are_made_without_a_backup(self):
        dst = os.path.join(self.claude, "agents", "x.md")
        self.link(os.path.join(self.repo, "CLAUDE.md"), dst)
        self.assertEqual(os.readlink(dst), os.path.join(self.repo, "CLAUDE.md"))
        self.assertFalse(os.path.exists(self.backup))
        self.assertEqual(self.leftovers(), [])

    def test_a_failed_swap_keeps_the_old_link_and_leaves_no_temp(self):
        dst = os.path.join(self.claude, "CLAUDE.md")
        self.plant(os.path.join(self.old, "CLAUDE.md"), dst)
        r = self.link(os.path.join(self.repo, "CLAUDE.md"), dst, FAIL_TOOL="python3")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("linked", r.stdout)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(os.readlink(dst), os.path.join(self.old, "CLAUDE.md"))
        self.assertEqual(self.leftovers(), [])

    def test_a_ctrl_c_mid_swap_keeps_the_old_link_and_leaves_no_temp(self):
        # Most of a link's time is python3 starting, so that is where a Ctrl-C lands; the exit
        # trap removes the temp, or a lane run's leftover would hold the install.
        dst = os.path.join(self.claude, "skills", "s1")
        self.plant(os.path.join(self.old, "skills", "s1"), dst)
        r = self.link(os.path.join(self.repo, "skills", "s1"), dst, INTERRUPT_TOOL="python3")
        self.assertIn(r.returncode, (-2, 130), r.stderr)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(os.readlink(dst), os.path.join(self.old, "skills", "s1"))
        self.assertEqual(self.leftovers(), [])

    def test_a_leftover_temp_with_this_pid_is_cleared_not_followed(self):
        # A killed run's temp, a link to a dir: ln -s onto it would make the new link inside
        # that dir, then the swap would install the stale link.
        dst = os.path.join(self.claude, "CLAUDE.md")
        self.plant(os.path.join(self.old, "CLAUDE.md"), dst)
        stale = os.path.join(self.old, "skills", "s1")
        r = self.run_sh(f'ln -s "{stale}" "{self.claude}/.CLAUDE.md.dotclaude-$$"\n'
                        f'link "{self.repo}/CLAUDE.md" "{dst}"', watch=dst)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(dst), os.path.join(self.repo, "CLAUDE.md"))
        self.assertEqual(os.listdir(stale), ["SKILL.md"])
        self.assertEqual(self.gaps(), [])
        self.assertEqual(self.leftovers(), [])

    def test_a_windows_shell_removes_a_link_before_the_swap(self):
        # Windows won't rename over a link to a dir; the gap there is by design.
        dst = os.path.join(self.claude, "skills", "s1")
        self.plant(os.path.join(self.old, "skills", "s1"), dst)
        r = self.link(os.path.join(self.repo, "skills", "s1"), dst, FAKE_TOOL="uname",
                      FAKE_OUT="MINGW64_NT-10.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.gaps(), [f"missing {dst} after rm -f {dst}"])
        self.assertEqual(os.readlink(dst), os.path.join(self.repo, "skills", "s1"))
        self.assertEqual(self.leftovers(), [])

    @unittest.skipIf(os.geteuid() == 0, "root reads a mode-0 file")
    def test_a_real_file_cp_cannot_read_is_moved_to_the_backup(self):
        dst = os.path.join(self.claude, "hooks", "a.sh")
        write(dst, "mine\n")
        os.chmod(dst, 0)
        self.link(os.path.join(self.repo, "CLAUDE.md"), dst)
        moved = os.path.join(self.backup, "hooks", "a.sh")
        os.chmod(moved, 0o600)
        self.assertEqual(read(moved), "mine\n")
        self.assertEqual(os.readlink(dst), os.path.join(self.repo, "CLAUDE.md"))
        self.assertEqual(self.leftovers(), [])

    def copy(self, dst, **env):
        src = os.path.join(self.tmp, "merged.json")
        write(src, "{\"new\": 1}\n")
        r = self.run_sh(f'copy_managed "{src}" "{dst}"', watch=dst, **env)
        if not env:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_settings_over_a_real_file_are_swapped_in_and_backed_up(self):
        dst = os.path.join(self.claude, "settings.json")
        write(dst, "{\"old\": 1}\n")
        os.chmod(dst, 0o600)
        r = self.copy(dst)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(read(dst), "{\"new\": 1}\n")
        self.assertFalse(os.path.islink(dst))
        backup = os.path.join(self.backup, "settings.json")
        self.assertEqual(read(backup), "{\"old\": 1}\n")
        self.assertEqual(os.stat(backup).st_mode & 0o777, 0o600)
        self.assertEqual(r.stdout, f"backing up {dst}\ncopied settings.json (runtime-managed, not symlinked)\n")
        self.assertEqual(self.leftovers(), [])

    def test_a_failed_settings_swap_keeps_the_old_file_and_leaves_no_temp(self):
        dst = os.path.join(self.claude, "settings.json")
        write(dst, "{\"old\": 1}\n")
        r = self.copy(dst, FAIL_TOOL="python3")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("copied", r.stdout)
        self.assertEqual(self.gaps(), [])
        self.assertEqual(read(dst), "{\"old\": 1}\n")
        self.assertEqual(self.leftovers(), [])

    def test_settings_over_a_dangling_link_become_a_real_file(self):
        dst = os.path.join(self.claude, "settings.json")
        self.plant(os.path.join(self.repo, "gone.json"), dst)
        self.copy(dst)
        self.assertEqual(self.gaps(), [])
        self.assertFalse(os.path.islink(dst))
        self.assertEqual(read(dst), "{\"new\": 1}\n")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "gone.json")))
        self.assertFalse(os.path.exists(self.backup))
        self.assertEqual(self.leftovers(), [])

    def test_settings_over_an_old_symlink_never_write_through_it(self):
        dst, baseline = os.path.join(self.claude, "settings.json"), os.path.join(self.repo, "settings.json")
        write(baseline, "{\"baseline\": 1}\n")
        self.plant(baseline, dst)
        self.copy(dst)
        self.assertEqual(self.gaps(), [])
        self.assertFalse(os.path.islink(dst))
        self.assertEqual(read(dst), "{\"new\": 1}\n")
        self.assertEqual(read(baseline), "{\"baseline\": 1}\n")
        self.assertFalse(os.path.exists(self.backup))
        self.assertEqual(self.leftovers(), [])

    def test_current_settings_are_left_alone(self):
        dst = os.path.join(self.claude, "settings.json")
        write(dst, "{\"new\": 1}\n")
        r = self.copy(dst)
        self.assertEqual(r.stdout, "settings.json already current\n")
        self.assertFalse(os.path.exists(self.backup))


if __name__ == "__main__":
    unittest.main()
