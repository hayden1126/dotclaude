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
    """setup.sh from its `# 6. Copy mode` header up to `# 7. Stale links`, after the say and
    warn helpers it uses."""
    with open(SETUP) as f:
        text = f.read()
    helpers = text[text.index("say()"):text.index("# ----", text.index("say()"))]
    return helpers + text[text.index("# 6. Copy mode"):text.index("# 7. Stale links")]


class CopyMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.config = os.path.join(self.tmp, "config dir")  # a space, to prove the quoting
        self.uv = os.path.join(self.config, "uv", "uv.toml")
        self.pnpm = os.path.join(self.config, "pnpm", "rc")

    def run_section(self):
        env = dict(os.environ, XDG_CONFIG_HOME=self.config, HOME=self.tmp)
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

    def test_the_key_inside_a_table_does_not_count(self):
        self.write(self.uv, '[pip]\nlink-mode = "hardlink"\n')
        self.run_section()
        self.assertTrue(self.read(self.uv).startswith(UV_LINE + "\n[pip]\n"))

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

    def test_without_xdg_config_home_it_uses_dot_config(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        env["HOME"] = self.tmp
        subprocess.run(["bash", "-euo", "pipefail", "-c", section()], check=True, env=env,
                       capture_output=True, timeout=10)
        self.assertEqual(self.read(os.path.join(self.tmp, ".config", "uv", "uv.toml")),
                         UV_LINE + "\n")


if __name__ == "__main__":
    unittest.main()
