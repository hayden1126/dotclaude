"""setup.sh's copy-mode step (its section 6): uv and pnpm installs copy packages out of their
caches instead of hardlinking them, so a project's files stop being the shared cache's own and an
in-place edit there can't reach other installs (sandbox gap N3). It sets the key at the top of
the user config file, keeps a value the file already has, and never doubles a line (stdlib only).

Each test cuts section 6 out of setup.sh and runs it in bash with XDG_CONFIG_HOME in a temp dir."""
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETUP = os.path.join(REPO, "setup.sh")
UV_LINE = 'link-mode = "copy"'
PNPM_LINE = "package-import-method=copy"


def section():
    """setup.sh from its `# N. Copy mode` header up to the next section's rule, after the say
    and warn helpers it uses. Keyed on the title, not the number, so a section added before or
    after it doesn't move the cut."""
    with open(SETUP) as f:
        text = f.read()
    helpers = text[text.index("say()"):text.index("# ----", text.index("say()"))]
    start = text.index(". Copy mode for uv and pnpm installs")
    start = text.rindex("\n", 0, start) + 1
    end = text.index("\n# ----", text.index("\n# ----", start) + 1)
    return helpers + text[start:end]


class CopyMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.config = os.path.join(self.tmp, "config dir")  # a space, to prove the quoting
        self.uv = os.path.join(self.config, "uv", "uv.toml")
        self.pnpm = os.path.join(self.config, "pnpm", "rc")
        # A fake pnpm first on PATH answers `pnpm config get` with FAKE_PNPM (default copy), so
        # no test runs the real one (a corepack pnpm with this HOME would have nothing cached).
        self.bin = os.path.join(self.tmp, "fake bin")
        os.makedirs(self.bin)
        self.fake("pnpm", 'printf "%s\\n" "${FAKE_PNPM-copy}"')

    def fake(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)

    def run_section(self, **extra):
        env = dict(os.environ, XDG_CONFIG_HOME=self.config, HOME=self.tmp,
                   PATH=os.pathsep.join([self.bin, os.environ["PATH"]]))
        env.update(extra)
        p = subprocess.run(["bash", "-euo", "pipefail", "-c", section()], capture_output=True,
                           text=True, timeout=10, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stderr

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def test_no_config_files_get_one_line_each(self):
        self.assertEqual(self.run_section(), "")
        self.assertEqual(self.read(self.uv), UV_LINE + "\n")
        self.assertEqual(self.read(self.pnpm), PNPM_LINE + "\n")

    def test_a_rerun_adds_nothing(self):
        self.run_section()
        self.run_section()
        self.assertEqual(self.read(self.uv), UV_LINE + "\n")
        self.assertEqual(self.read(self.pnpm), PNPM_LINE + "\n")

    def test_the_line_goes_above_the_first_table(self):
        # A TOML key after a [table] header belongs to that table, where uv ignores link-mode.
        self.write(self.uv, '[pip]\nindex-url = "https://example.org/simple"\n')
        self.run_section()
        self.assertEqual(self.read(self.uv),
                         UV_LINE + '\n[pip]\nindex-url = "https://example.org/simple"\n')

    def test_the_key_inside_a_table_is_named_and_kept(self):
        # uv's [pip] link-mode governs `uv pip` installs: the top-level line still goes in, and
        # the table's other value is named.
        self.write(self.uv, '[pip]\nlink-mode = "hardlink"\n')
        err = self.run_section()
        self.assertEqual(self.read(self.uv), UV_LINE + '\n[pip]\nlink-mode = "hardlink"\n')
        self.assertIn("in [pip]", err)

    def test_a_table_that_sets_copy_is_silent(self):
        self.write(self.uv, "[pip]\nlink-mode = 'copy'\n")
        self.assertEqual(self.run_section(), "")

    def test_a_quoted_key_counts(self):
        # Adding a second link-mode beside a quoted one would be a duplicate key, and uv refuses
        # the whole file.
        self.write(self.uv, '"link-mode" = "hardlink"\n')
        err = self.run_section()
        self.assertEqual(self.read(self.uv), '"link-mode" = "hardlink"\n')
        self.assertIn(self.uv, err)

    def test_a_trailing_comment_is_not_the_value(self):
        self.write(self.uv, 'link-mode = "copy"  # set by hand\n')
        self.write(self.pnpm, "package-import-method=copy ; set by hand\n")
        self.assertEqual(self.run_section(), "")

    def test_an_unreadable_file_is_named_and_setup_goes_on(self):
        self.write(self.uv, 'python-preference = "managed"\n')
        os.chmod(self.uv, 0o000)
        self.addCleanup(os.chmod, self.uv, 0o600)
        err = self.run_section()  # exit 0: the sections after this one still run
        self.assertIn(self.uv, err)
        os.chmod(self.uv, 0o600)
        self.assertEqual(self.read(self.uv), 'python-preference = "managed"\n')
        self.assertEqual(self.read(self.pnpm), PNPM_LINE + "\n")

    def test_a_dir_in_the_way_is_named_and_setup_goes_on(self):
        os.makedirs(self.pnpm)
        self.assertIn(self.pnpm, self.run_section())
        self.assertEqual(self.read(self.uv), UV_LINE + "\n")

    def test_an_existing_value_is_kept_and_named(self):
        self.write(self.uv, 'link-mode = "symlink"\n')
        self.write(self.pnpm, "store-dir=/x\npackage-import-method = hardlink\n")
        err = self.run_section()
        self.assertEqual(self.read(self.uv), 'link-mode = "symlink"\n')
        self.assertEqual(self.read(self.pnpm), "store-dir=/x\npackage-import-method = hardlink\n")
        self.assertIn(self.uv, err)
        self.assertIn(self.pnpm, err)

    def test_copy_already_set_in_another_spelling_is_left_alone(self):
        self.write(self.uv, "  link-mode='copy'\n")
        self.write(self.pnpm, "package-import-method = copy")  # no trailing newline
        self.assertEqual(self.run_section(), "")
        self.assertEqual(self.read(self.uv), "  link-mode='copy'\n")
        self.assertEqual(self.read(self.pnpm), "package-import-method = copy")

    def test_other_keys_stay_below_the_new_line(self):
        self.write(self.pnpm, "store-dir=/x")  # no trailing newline
        self.run_section()
        self.assertEqual(self.read(self.pnpm), PNPM_LINE + "\nstore-dir=/x\n")

    def test_a_rewrite_keeps_the_mode_and_leaves_no_temp(self):
        # The new text goes to a copy that is renamed over the file, so a failed write can't
        # truncate it.
        self.write(self.pnpm, "store-dir=/x\n")
        os.chmod(self.pnpm, 0o640)
        self.run_section()
        self.assertEqual(os.stat(self.pnpm).st_mode & 0o777, 0o640)
        self.assertEqual(os.listdir(os.path.dirname(self.pnpm)), ["rc"])

    def test_an_empty_file_gets_just_the_line(self):
        self.write(self.uv, "")
        self.run_section()
        self.assertEqual(self.read(self.uv), UV_LINE + "\n")

    def test_a_linked_config_stays_a_link(self):
        # A config kept in a dotfiles repo is edited where it lives.
        target = os.path.join(self.tmp, "dotfiles", "uv.toml")
        self.write(target, 'python-preference = "managed"\n')
        os.makedirs(os.path.dirname(self.uv))
        os.symlink(target, self.uv)
        self.run_section()
        self.assertTrue(os.path.islink(self.uv))
        self.assertEqual(self.read(target), UV_LINE + '\npython-preference = "managed"\n')

    def run_without_xdg(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        env.update(HOME=self.tmp, PATH=os.pathsep.join([self.bin, os.environ["PATH"]]))
        subprocess.run(["bash", "-euo", "pipefail", "-c", section()], check=True, env=env,
                       capture_output=True, timeout=10)

    def test_without_xdg_config_home_it_uses_dot_config(self):
        self.run_without_xdg()
        self.assertEqual(self.read(os.path.join(self.tmp, ".config", "uv", "uv.toml")),
                         UV_LINE + "\n")
        self.assertEqual(self.read(os.path.join(self.tmp, ".config", "pnpm", "rc")),
                         PNPM_LINE + "\n")

    def test_on_macos_pnpms_rc_is_in_library_preferences(self):
        # uv keeps ~/.config there; pnpm, without XDG_CONFIG_HOME, reads ~/Library/Preferences.
        self.fake("uname", "echo Darwin")
        self.run_without_xdg()
        self.assertEqual(self.read(os.path.join(self.tmp, ".config", "uv", "uv.toml")),
                         UV_LINE + "\n")
        self.assertEqual(
            self.read(os.path.join(self.tmp, "Library", "Preferences", "pnpm", "rc")),
            PNPM_LINE + "\n")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".config", "pnpm")))

    def test_on_macos_xdg_config_home_still_wins_for_pnpm(self):
        self.fake("uname", "echo Darwin")
        self.run_section()
        self.assertEqual(self.read(self.pnpm), PNPM_LINE + "\n")

    def test_pnpm_reading_another_value_is_named(self):
        # A ~/.npmrc that sets it, or a config dir the step missed: pnpm's own answer counts.
        err = self.run_section(FAKE_PNPM="hardlink")
        self.assertIn("pnpm reads package-import-method as hardlink", err)
        self.assertEqual(self.read(self.pnpm), PNPM_LINE + "\n")

    def test_pnpm_failing_or_absent_is_silent(self):
        self.fake("pnpm", "exit 1")
        self.assertEqual(self.run_section(), "")
        os.remove(os.path.join(self.bin, "pnpm"))
        self.assertEqual(self.run_section(PATH=os.pathsep.join([self.bin, "/usr/bin", "/bin"])),
                         "")


if __name__ == "__main__":
    unittest.main()
