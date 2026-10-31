"""bin/npx: the shim setup.sh links into ~/.local/bin ahead of the real npx (stdlib only). Claude
Code starts stdio MCP servers in the project dir, which sandboxed Bash and the file tools can
write, and npx prefers that dir's node_modules and .npmrc (sandbox gap N2). For a launch by Claude
Code, or an exact-version spec, the shim puts --prefix=/ first, so npx reads neither; anything
else reaches the real npx untouched.

Each test runs the shim with a fake real npx later on PATH that prints its args, one per line."""
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHIM = os.path.join(REPO, "bin", "npx")
PREFIX = "--prefix=/"


class NpxShim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.shim_dir = os.path.join(self.tmp, "local bin")  # a space, to prove the quoting
        self.real_dir = os.path.join(self.tmp, "usr bin")
        os.makedirs(self.shim_dir)
        os.makedirs(self.real_dir)
        os.symlink(SHIM, os.path.join(self.shim_dir, "npx"))  # as setup.sh links it
        real = os.path.join(self.real_dir, "npx")
        with open(real, "w") as f:
            f.write('#!/bin/sh\nfor a; do printf "%s\\n" "$a"; done\n')
        os.chmod(real, 0o755)
        # The shim dir twice, as on HAYPC where ~/.local/bin is listed twice.
        self.path = os.pathsep.join([self.shim_dir, self.shim_dir, self.real_dir, "/usr/bin",
                                     "/bin"])

    def npx(self, *args, parent=None, path=None, script='"$0" "$@"; :'):
        """The args the real npx got, run as `npx` from PATH; with parent, from a process of
        that name (Claude Code's comm is `claude`)."""
        env = {"PATH": path or self.path, "HOME": self.tmp}
        cmd = ["npx", *args]
        if parent:
            # A bash named `parent` runs the shim as a child; the trailing `:` stops bash from
            # exec-ing it in place, which would make the shim's parent bash's own parent.
            named = os.path.join(self.tmp, parent)
            if not os.path.lexists(named):
                os.symlink(shutil.which("bash"), named)
            cmd = [named, "-c", script, *cmd]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        return p.stdout.splitlines()

    def test_an_exact_version_skips_the_project_dir(self):
        self.assertEqual(self.npx("chrome-devtools-mcp@1.11.0"),
                         [PREFIX, "chrome-devtools-mcp@1.11.0"])

    def test_a_scoped_or_prerelease_exact_version_skips_it_too(self):
        for spec in ("@scope/pkg@1.2.3", "pkg@1.2.3-rc.1", "pkg@1.2.3+build.5"):
            self.assertEqual(self.npx(spec, "arg"), [PREFIX, spec, "arg"], spec)

    def test_options_before_the_spec_are_kept_after_the_prefix(self):
        self.assertEqual(self.npx("-y", "--offline", "semver@7.6.3", "1.2.3"),
                         [PREFIX, "-y", "--offline", "semver@7.6.3", "1.2.3"])

    def test_a_range_tag_or_bare_name_reaches_npx_untouched(self):
        # Hayden's own `npx tsc` must keep finding the project's copy.
        for args in (["tsc", "--version"], ["pkg@^1.2.3"], ["pkg@latest"], ["pkg@1.2"],
                     ["-y", "pkg"], []):
            self.assertEqual(self.npx(*args), args, args)

    def test_only_the_first_operand_counts(self):
        self.assertEqual(self.npx("eslint", "--rule", "x@1.2.3"), ["eslint", "--rule", "x@1.2.3"])

    def test_an_option_value_is_not_taken_for_the_spec(self):
        for args in (["--registry", "https://r.example", "pkg@1.2.3"],
                     ["--cache", "/c", "-y", "pkg@1.2.3"], ["-p", "pkg@1.2.3", "cmd"],
                     ["--package=pkg@1.2.3", "cmd"], ["pkg@v1.2.3"]):
            self.assertEqual(self.npx(*args), [PREFIX, *args], args)

    def test_an_unpinned_package_option_reaches_npx_untouched(self):
        self.assertEqual(self.npx("-p", "pkg", "cmd"), ["-p", "pkg", "cmd"])

    def test_a_launch_by_claude_code_installed_with_npm_counts_too(self):
        # comm is `node`; its args name Claude Code's cli.js. The marker rides in the script.
        script = ': /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js; "$0" "$@"; :'
        self.assertEqual(self.npx("some-mcp", parent="node", script=script), [PREFIX, "some-mcp"])
        self.assertEqual(self.npx("some-mcp", parent="node"), ["some-mcp"])

    def test_a_launch_by_claude_code_skips_the_project_dir_whatever_the_spec(self):
        self.assertEqual(self.npx("-y", "some-mcp", parent="claude"),
                         [PREFIX, "-y", "some-mcp"])

    def test_another_parent_is_not_claude_code(self):
        self.assertEqual(self.npx("some-mcp", parent="claudex"), ["some-mcp"])

    def test_no_real_npx_fails_with_127(self):
        bash_dir = os.path.join(self.tmp, "bash only")  # env finds bash, nothing finds npx
        os.makedirs(bash_dir)
        os.symlink(shutil.which("bash"), os.path.join(bash_dir, "bash"))
        path = os.pathsep.join([self.shim_dir, bash_dir])
        p = subprocess.run(["npx", "tsc"], capture_output=True, text=True, timeout=10,
                           env={"PATH": path, "HOME": self.tmp})
        self.assertEqual(p.returncode, 127)
        self.assertIn("no npx on PATH", p.stderr)

    def test_the_planted_tree_does_not_run(self):
        # The real npx, offline: a planted ./node_modules/semver must lose to the npx cache.
        # PATH without any installed copy of the shim, for the control run.
        bare = os.pathsep.join(
            d for d in os.environ["PATH"].split(os.pathsep)
            if not (os.path.exists(os.path.join(d, "npx"))
                    and os.path.samefile(os.path.join(d, "npx"), SHIM)))
        if not shutil.which("npx", path=bare):
            self.skipTest("npx not installed")
        proj = os.path.join(self.tmp, "proj")
        pkg = os.path.join(proj, "node_modules", "semver")
        os.makedirs(os.path.join(pkg, "bin"))
        os.makedirs(os.path.join(proj, "node_modules", ".bin"))
        with open(os.path.join(pkg, "package.json"), "w") as f:
            f.write('{"name":"semver","version":"7.6.3","bin":{"semver":"bin/semver.js"}}')
        with open(os.path.join(pkg, "bin", "semver.js"), "w") as f:
            f.write('#!/usr/bin/env node\nconsole.log("PLANTED")\n')
        os.chmod(os.path.join(pkg, "bin", "semver.js"), 0o755)
        os.symlink("../semver/bin/semver.js", os.path.join(proj, "node_modules", ".bin", "semver"))
        args = ["npx", "--offline", "semver@7.6.3", "1.2.3"]
        control = subprocess.run(args, cwd=proj, capture_output=True, text=True, timeout=60,
                                 env=dict(os.environ, PATH=bare))
        self.assertIn("PLANTED", control.stdout, control.stderr)  # the plant works unshimmed
        p = subprocess.run(args, cwd=proj, capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, PATH=os.pathsep.join([self.shim_dir, bare])))
        self.assertNotIn("PLANTED", p.stdout)
        if "ENOTCACHED" in p.stderr:
            self.skipTest("semver@7.6.3 is not in the npx cache, so the offline run can't finish")
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "1.2.3"), p.stderr)


SETUP = os.path.join(REPO, "setup.sh")


def bin_block():
    """setup.sh's say/warn, its section 1 link helpers and the block that links bin/ into
    ~/.local/bin."""
    with open(SETUP) as f:
        text = f.read()
    helpers = text[text.index("say()"):text.index("# ----", text.index("say()"))]
    links = text[text.index("# 1. Symlink helpers"):text.index("# 2. Single files")]
    start = text.index('if [[ -d "$HOME/.local/bin" ]]; then')
    return helpers + links + text[start:text.index("# templates/", start)]


class SetupLinksTheShim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = self.checkout("repo")
        self.home = os.path.join(self.tmp, "home")
        self.dst = os.path.join(self.home, ".local", "bin", "npx")
        os.makedirs(os.path.dirname(self.dst))

    def checkout(self, name):
        """A dir with what the guard looks for: bin/npx beside hooks/sandbox-caches.sh."""
        root = os.path.join(self.tmp, name)
        for rel in ("bin/npx", "hooks/sandbox-caches.sh"):
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            shutil.copy(os.path.join(REPO, rel), os.path.join(root, rel))
        return root

    def run_block(self):
        env = dict(os.environ, HOME=self.home, REPO_DIR=self.repo,
                   CLAUDE_DIR=os.path.join(self.home, ".claude"),
                   BACKUP_DIR=os.path.join(self.tmp, "backup"))
        p = subprocess.run(["bash", "-euo", "pipefail", "-c", bin_block()], capture_output=True,
                           text=True, timeout=30, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stderr

    def test_no_npx_there_gets_the_shim(self):
        self.assertEqual(self.run_block(), "")
        self.assertEqual(os.readlink(self.dst), os.path.join(self.repo, "bin", "npx"))

    def test_npms_own_npx_is_left_alone_and_named(self):
        npm = os.path.join(self.tmp, "lib", "node_modules", "npm", "bin", "npx-cli.js")
        os.makedirs(os.path.dirname(npm))
        open(npm, "w").close()
        os.symlink(npm, self.dst)
        self.assertIn(self.dst, self.run_block())
        self.assertEqual(os.readlink(self.dst), npm)

    def test_another_checkouts_shim_is_replaced(self):
        # A lane's install linked its own copy; the next install from another checkout relinks.
        lane = self.checkout("lane")
        os.symlink(os.path.join(lane, "bin", "npx"), self.dst)
        self.assertEqual(self.run_block(), "")
        self.assertEqual(os.readlink(self.dst), os.path.join(self.repo, "bin", "npx"))


if __name__ == "__main__":
    unittest.main()
