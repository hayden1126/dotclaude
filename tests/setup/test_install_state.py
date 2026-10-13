"""install-state.py: the install hold, the link prune and the plugin-change line (stdlib only).

Every test runs on a temp machine: HOME, CLAUDE_CONFIG_DIR, CODEX_HOME and XDG_STATE_HOME point
into a temp dir, beside a real git repo with two `git worktree add` lanes and its lanes config.
"""
import ast
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INSTALL_STATE = os.path.join(REPO, "install-state.py")
SETUP = os.path.join(REPO, "setup.sh")


def load(path):
    loader = importlib.machinery.SourceFileLoader(os.path.basename(path).replace("-", "_")[:-3], path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


install_state = load(INSTALL_STATE)

# The fake repo's files: one per setup.sh source kind, a README nothing links, and tmux/ files
# only setup-tmux.sh links.
FILES = ("CLAUDE.md", "README.md", "hooks/a.sh", "hooks/b.py", "skills/s1/SKILL.md",
         "skills/s1/scripts/tool", "agents/x.md", "templates/T.md", "bin/tool2", "statusline/w.py",
         "codex/AGENTS.md", "tmux/claude.conf", "tmux/pass-last")


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class Machine(unittest.TestCase):
    """self.main is a repo whose lane worktrees self.a and self.b (branches a, b) sit under the
    lanes root self.root, which its lanes config names."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        j = os.path.join
        self.home, self.claude, self.codex = j(self.tmp, "home"), j(self.tmp, "claude"), j(self.tmp, "codex")
        self.state = j(self.tmp, "state")
        self.bin, self.ccs = j(self.home, ".local", "bin"), j(self.home, ".config", "ccstatusline")
        os.makedirs(self.home)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("GIT_", "CLAUDE", "CODEX_", "XDG_"))}
        self.env.update(HOME=self.home, CLAUDE_CONFIG_DIR=self.claude, CODEX_HOME=self.codex,
                        XDG_STATE_HOME=self.state, GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        self.main, self.root = j(self.tmp, "proj"), j(self.tmp, "proj-lanes")
        self.git("init", "-q", "-b", "main", self.main, cwd=self.tmp)
        for rel in FILES:
            write(j(self.main, rel), rel + "\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "files")
        self.a, self.b = j(self.root, "a"), j(self.root, "b")
        self.git("worktree", "add", "-q", "-b", "a", self.a)
        self.git("worktree", "add", "-q", "-b", "b", self.b)
        self.common = j(self.main, ".git")
        key = hashlib.sha256(self.common.encode()).hexdigest()[:12]
        self.config = j(self.state, "dotclaude", "lanes", f"proj-{key}.toml")
        write(self.config, f'# lanes config, written by `lane init`; flat keys only.\n'
                           f'root = "{self.root}"\nsetup = ""\ncap = 8\n')

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.main, env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def link(self, target, dst):
        if os.path.lexists(dst):
            os.unlink(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.symlink(target, dst)
        return dst

    def install(self, checkout):
        """The links setup.sh makes, from checkout."""
        j = os.path.join
        for src, dst in (("CLAUDE.md", self.claude), ("hooks/a.sh", j(self.claude, "hooks")),
                         ("hooks/b.py", j(self.claude, "hooks")), ("skills/s1", j(self.claude, "skills")),
                         ("agents/x.md", j(self.claude, "agents")),
                         ("templates/T.md", j(self.claude, "templates")), ("bin/tool2", self.bin),
                         ("skills/s1/scripts/tool", self.bin), ("codex/AGENTS.md", self.codex),
                         ("skills/s1", j(self.codex, "skills")), ("statusline/w.py", self.ccs)):
            self.link(j(checkout, src), j(dst, os.path.basename(src)))

    def snapshot(self):
        """Every path under the temp machine's install dirs, with its link target or 'file'."""
        out = {}
        for top in (self.home, self.claude, self.codex, self.state):
            for d, dirs, names in os.walk(top):
                for n in dirs + names:
                    p = os.path.join(d, n)
                    out[p] = os.readlink(p) if os.path.islink(p) else "dir" if os.path.isdir(p) else "file"
        return out

    def cli(self, *args):
        return subprocess.run([sys.executable, INSTALL_STATE, *args], env=self.env,
                              capture_output=True, text=True, timeout=30)


class Hold(Machine):
    def test_a_lane_install_holds_against_another_lane_and_changes_nothing(self):
        self.install(self.a)
        before = self.snapshot()
        r = self.cli("hold", self.b)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn(f"lane worktree {self.a} (branch a, 11 links into it)", r.stderr)
        self.assertIn(f"The lead's ./setup.sh in {self.main} releases it (it relinks everything)",
                      r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.snapshot(), before)

    def test_the_holding_lane_itself_proceeds(self):
        self.install(self.a)
        r = self.cli("hold", self.a)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_the_main_checkout_proceeds_and_says_it_releases_the_hold(self):
        self.install(self.a)
        r = self.cli("hold", self.main)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn(f"releases the install held by {self.a} (branch a, 11 links)", r.stdout)

    def test_a_plain_clone_is_held(self):
        clone = os.path.join(self.tmp, "clone")
        self.git("clone", "-q", self.main, clone, cwd=self.tmp)
        self.install(self.a)
        self.assertEqual(self.cli("hold", clone).returncode, 3)

    def test_a_removed_worktree_holds_nothing(self):
        self.install(self.a)
        self.git("worktree", "remove", "--force", self.a)
        self.assertEqual(install_state.holders(self.b, self.env), [])
        self.assertEqual(self.cli("hold", self.b).returncode, 0)

    def test_a_planted_worktree_entry_naming_main_makes_no_holder(self):
        self.install(self.main)
        admin = os.path.join(self.common, "worktrees", "x")
        for named in (self.main, self.main + "/", self.main + "/.", self.common,
                      self.common + "/", os.path.join(self.main, ".", ".git")):
            with self.subTest(named):
                write(os.path.join(admin, "gitdir"), named + "\n")
                write(os.path.join(admin, "HEAD"), "ref: refs/heads/main\n")
                write(os.path.join(admin, "commondir"), "../..\n")
                self.assertEqual(install_state.holders(self.b, self.env), [])
                self.assertEqual(self.cli("hold", self.b).returncode, 0)

    def test_a_worktree_inside_the_main_checkout_is_no_holder(self):
        # Claude Code's agent worktrees sit in <main>/.claude/worktrees/: a real worktree, but
        # inside main, so it neither holds nor gets pruned (lanelib.worktree_problem's rule).
        inner = os.path.join(self.main, ".claude", "worktrees", "agent-x")
        self.git("worktree", "add", "-q", "-b", "agent-x", inner)
        self.install(inner)
        self.assertEqual(install_state.holders(self.b, self.env), [])
        self.assertEqual(install_state.prune(self.b, self.env), [])

    def test_a_planted_git_file_inside_main_makes_no_holder(self):
        # A .git file in a dir of main, naming a planted worktrees/ entry that names it back.
        planted = os.path.join(self.main, "hooks")
        admin = os.path.join(self.common, "worktrees", "planted")
        write(os.path.join(planted, ".git"), f"gitdir: {admin}\n")
        write(os.path.join(admin, "gitdir"), os.path.join(planted, ".git") + "\n")
        write(os.path.join(admin, "HEAD"), "ref: refs/heads/main\n")
        self.link(os.path.join(planted, "a.sh"), os.path.join(self.claude, "hooks", "a.sh"))
        self.assertEqual(install_state.holders(self.b, self.env), [])

    def test_a_git_file_without_a_matching_worktree_entry_makes_no_holder(self):
        # fake/ copies lane b's .git file, whose entry names b back; other/'s .git file names an
        # entry that names it back but sits outside a worktrees/ dir (a submodule's layout).
        fake, other = os.path.join(self.tmp, "fake"), os.path.join(self.tmp, "other")
        shutil.copytree(self.b, fake, ignore=shutil.ignore_patterns("tmux"))
        admin = os.path.join(self.common, "modules", "other")
        write(os.path.join(other, ".git"), f"gitdir: {admin}\n")
        write(os.path.join(admin, "gitdir"), os.path.join(other, ".git") + "\n")
        write(os.path.join(other, "CLAUDE.md"))
        self.install(fake)
        self.link(os.path.join(other, "CLAUDE.md"), os.path.join(self.claude, "CLAUDE.md"))
        self.assertIsNotNone(install_state.linked_worktree(self.b))
        self.assertIsNone(install_state.linked_worktree(fake))
        self.assertIsNone(install_state.linked_worktree(other))
        self.assertEqual(install_state.holders(self.a, self.env), [])

    def test_holders_names_root_main_branch_and_each_link(self):
        self.install(self.a)
        (h,) = install_state.holders(self.b, self.env)
        self.assertEqual((h["root"], h["main"], h["branch"]), (self.a, self.main, "a"))
        self.assertEqual(len(h["links"]), 11)
        self.assertIn(f"~/.local/bin/tool2 -> {self.a}/bin/tool2", h["links"])
        self.assertIn(f"{self.claude}/hooks/a.sh -> {self.a}/hooks/a.sh", h["links"])

    def test_links_setup_does_not_make_hold_nothing(self):
        # setup-tmux.sh's links, and a link to a file no setup.sh source matches.
        self.link(os.path.join(self.a, "tmux", "pass-last"), os.path.join(self.bin, "pass-last"))
        self.link(os.path.join(self.a, "README.md"), os.path.join(self.claude, "README.md"))
        self.assertEqual(install_state.holders(self.b, self.env), [])

    def test_no_links_no_holders(self):
        self.assertEqual(self.cli("hold", self.b).returncode, 0)


class Prune(Machine):
    def prune(self, repo_dir):
        return install_state.prune(repo_dir, self.env)

    def test_a_link_into_a_live_lane_is_pruned(self):
        dst = self.link(os.path.join(self.a, "hooks", "a.sh"), os.path.join(self.claude, "hooks", "a.sh"))
        r = self.cli("prune", self.main)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(r.stdout, f"==> removed link {dst} -> {self.a}/hooks/a.sh\n")
        self.assertFalse(os.path.lexists(dst))

    def test_on_a_lane_run_a_link_into_main_is_kept(self):
        self.install(self.main)
        before = self.snapshot()
        self.assertEqual(self.prune(self.a), [])
        self.assertEqual(self.snapshot(), before)

    def test_a_tmux_link_into_a_lane_is_kept(self):
        dst = self.link(os.path.join(self.a, "tmux", "pass-last"), os.path.join(self.bin, "pass-last"))
        self.assertEqual(self.prune(self.main), [])
        self.assertTrue(os.path.islink(dst))

    def test_codex_skills_and_every_managed_dir_are_covered(self):
        self.install(self.a)
        self.assertEqual(len(self.prune(self.main)), 11)
        self.assertEqual(install_state.links_into(self.a, self.env), [])
        self.assertFalse(os.path.lexists(os.path.join(self.codex, "skills", "s1")))

    def test_a_dangling_link_under_the_lanes_root_is_pruned_when_the_config_names_it(self):
        target = os.path.join(self.root, "closed", "hooks", "old.sh")
        dst = os.path.join(self.claude, "hooks", "old.sh")
        self.link(target, dst)
        os.unlink(self.config)
        self.assertEqual(self.prune(self.main), [])  # no config, no lanes root
        write(self.config, f'root = "{self.root}"\n')
        self.assertEqual(self.prune(self.main), [f"removed link {dst} -> {target}"])

    def test_the_lanes_root_is_found_from_a_lane_too(self):
        dst = self.link(os.path.join(self.root, "closed", "CLAUDE.md"), os.path.join(self.claude, "CLAUDE.md"))
        self.assertEqual(len(self.prune(self.b)), 1)
        self.assertFalse(os.path.lexists(dst))

    def test_a_dangling_link_into_this_checkouts_hooks_is_pruned(self):
        # The old prune_stale_hook_links: hooks/autopass-toggle.sh left the repo in 2026-10.
        gone = self.link(os.path.join(self.main, "hooks", "gone.sh"), os.path.join(self.claude, "hooks", "gone.sh"))
        live = self.link(os.path.join(self.main, "hooks", "a.sh"), os.path.join(self.claude, "hooks", "a.sh"))
        self.assertEqual(self.prune(self.main), [f"removed link {gone} -> {self.main}/hooks/gone.sh"])
        self.assertTrue(os.path.exists(live))

    def test_foreign_links_regular_files_and_unmanaged_links_are_kept(self):
        hooks = os.path.join(self.claude, "hooks")
        keep = [self.link(os.path.join(self.tmp, "other", "hooks", "x.sh"), os.path.join(hooks, "x.sh")),
                self.link(os.path.join(self.a, "README.md"), os.path.join(self.claude, "README.md")),
                self.link(os.path.join(self.a, "hooks", "a.sh"), os.path.join(self.home, "elsewhere", "a.sh"))]
        write(os.path.join(hooks, "plugin.sh"), "a plugin's hook\n")
        before = self.snapshot()
        self.assertEqual(self.prune(self.main), [])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(os.path.islink(k) for k in keep))

    def test_a_relative_link_is_read_against_its_dir(self):
        dst = os.path.join(self.claude, "hooks", "a.sh")
        self.link(os.path.relpath(os.path.join(self.a, "hooks", "a.sh"), os.path.dirname(dst)), dst)
        self.assertEqual(len(self.prune(self.main)), 1)


class Managed(unittest.TestCase):
    def test_globs_match_segment_by_segment(self):
        for rel, want in (("hooks/a.sh", True), ("hooks/sub/a.sh", False), ("skills/x", True),
                          ("skills/x/SKILL.md", False), ("skills/x/scripts/lane", True),
                          ("skills/x/scripts/sub/lane", False), ("bin/a", True), ("bin/a/b", False),
                          ("codex/AGENTS.md", True), ("codex/config.toml", False),
                          ("tmux/pass-last", False), ("README.md", False)):
            with self.subTest(rel):
                self.assertEqual(install_state.managed(rel), want)


class ConfigRoot(unittest.TestCase):
    TEXT = ('# lanes config, written by `lane init`; flat keys only.\n'
            'root = "/x/a \\"q\\" b\\\\c"\nsetup = ""\ncap = 8\nautopass = true\n')

    def test_tomllib_and_the_regex_read_the_same_root(self):
        self.assertEqual(install_state.config_root(self.TEXT), '/x/a "q" b\\c')
        with mock.patch.dict(sys.modules, {"tomllib": None}):  # Python 3.10: no tomllib
            self.assertEqual(install_state.config_root(self.TEXT), '/x/a "q" b\\c')
            self.assertIsNone(install_state.config_root("setup = 'x'\n"))


class LinksInto(Machine):
    def test_every_managed_dir_and_the_tmux_block_are_reported(self):
        self.install(self.a)
        tmux = self.link(os.path.join(self.a, "tmux", "pass-last"), os.path.join(self.bin, "pass-last"))
        write(os.path.join(self.home, ".tmux.conf"),
              f'set -g mouse on\nsource-file "{self.a}/tmux/mine.conf"\n'
              f'{install_state.TMUX_START}\nsource-file "{self.a}/tmux/claude.conf"\n'
              f'source-file "{self.main}/tmux/base.conf"\n{install_state.TMUX_END}\n')
        self.link(os.path.join(self.a, "hooks", "a.sh"), os.path.join(self.home, "elsewhere", "a.sh"))
        self.link(os.path.join(self.b, "CLAUDE.md"), os.path.join(self.claude, "other.md"))
        found = install_state.links_into(self.a, self.env)
        self.assertEqual(len(found), 13, found)  # 11 setup.sh links, the tmux link, one block line
        self.assertIn(f"~/.local/bin/pass-last -> {self.a}/tmux/pass-last", found)
        self.assertIn(f'~/.tmux.conf: source-file "{self.a}/tmux/claude.conf"', found)
        dirs = {os.path.dirname(l.split(" -> ")[0]) for l in found if " -> " in l}
        self.assertEqual(len(dirs), 9, dirs)  # all nine managed dirs
        self.assertTrue(os.path.islink(tmux))

    def test_nothing_points_into_an_untouched_lane(self):
        self.install(self.main)
        self.assertEqual(install_state.links_into(self.b, self.env), [])


class Plugins(Machine):
    def setUp(self):
        super().setUp()
        self.src = os.path.join(self.tmp, "src")
        self.skills = os.path.join(self.claude, "skills")
        self.mod("autopass")
        write(os.path.join(self.src, "plain", "SKILL.md"), "a plain skill\n")
        self.link(os.path.join(self.src, "plain"), os.path.join(self.skills, "plain"))
        self.plugins({"superpowers@official": [{"scope": "user", "version": "6.4.1",
                                                "gitCommitSha": "5bf4e780"}]})

    def mod(self, name, manifest_name=True):
        d = os.path.join(self.src, name)
        write(os.path.join(d, ".claude-plugin", "plugin.json"),
              json.dumps({"name": name} if manifest_name else {}))
        write(os.path.join(d, "index.ts"), "export {}\n")
        write(os.path.join(d, "tests", "t.ts"), "test\n")
        self.link(d, os.path.join(self.skills, name))

    def plugins(self, entries):
        write(os.path.join(self.claude, "plugins", "installed_plugins.json"),
              json.dumps({"version": 2, "plugins": entries}))

    def change(self):
        return install_state.plugin_change(self.env)

    def test_the_first_run_saves_and_prints_nothing(self):
        self.assertIsNone(self.change())
        with open(os.path.join(self.state, "dotclaude", "install-plugins.json")) as f:
            saved = json.load(f)
        self.assertEqual(sorted(saved), ["autopass@skills-dir", "superpowers@official"])
        self.assertIsNone(self.change())

    def test_a_mod_added_removed_or_edited_in_place_is_named(self):
        self.change()
        self.mod("newmod")
        self.assertEqual(self.change(), "plugins changed (newmod@skills-dir added): sessions "
                                        "started before this install need /pass to load them")
        os.unlink(os.path.join(self.skills, "newmod"))
        self.assertIn("(newmod@skills-dir removed)", self.change())
        write(os.path.join(self.src, "autopass", "index.ts"), "export const x = 1\n")
        self.assertIn("(autopass@skills-dir changed)", self.change())
        self.assertIsNone(self.change())

    def test_a_plugin_version_bump_is_named(self):
        self.change()
        self.plugins({"superpowers@official": [{"scope": "user", "version": "6.5.0",
                                                "gitCommitSha": "0123abcd"}],
                      "codex@openai": [{"version": "1.0", "gitCommitSha": "ff"}]})
        self.assertIn("(codex@openai added, superpowers@official changed)", self.change())

    def test_tests_bytecode_and_plain_skill_edits_print_nothing(self):
        self.change()
        write(os.path.join(self.src, "autopass", "tests", "t.ts"), "another test\n")
        write(os.path.join(self.src, "autopass", "__pycache__", "x.pyc"), "bytes\n")
        write(os.path.join(self.src, "plain", "SKILL.md"), "edited\n")
        write(os.path.join(self.src, "plain", "scripts", "x.py"), "new\n")
        self.assertIsNone(self.change())

    def test_a_mod_without_a_manifest_name_goes_by_its_dir(self):
        self.change()
        self.mod("bare", manifest_name=False)
        self.assertIn("(bare added)", self.change())

    def test_the_cli_prints_the_line_once(self):
        self.assertEqual(self.cli("plugins").stdout, "")
        self.mod("newmod")
        r = self.cli("plugins")
        self.assertEqual((r.returncode, r.stdout.count("\n")), (0, 1))
        self.assertTrue(r.stdout.startswith("!!  plugins changed (newmod@skills-dir added): "))


class SetupHold(Machine):
    """setup.sh's top, cut off before its first change and run from a lane's checkout."""

    def head(self, checkout, helper=None):
        with open(SETUP) as f:
            text = f.read()
        write(os.path.join(checkout, "setup-head.sh"),
              text[:text.index('mkdir -p "$CLAUDE_DIR"')] + 'echo "past the hold"\n')
        if helper is None:
            shutil.copy(INSTALL_STATE, os.path.join(checkout, "install-state.py"))
        else:
            write(os.path.join(checkout, "install-state.py"), helper)
        return subprocess.run(["bash", os.path.join(checkout, "setup-head.sh")], env=self.env,
                              capture_output=True, text=True, timeout=30)

    def test_a_held_install_stops_before_changing_anything(self):
        self.install(self.a)
        before = self.snapshot()
        r = self.head(self.b)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("past the hold", r.stdout)
        self.assertIn(self.a, r.stderr)
        self.assertIn("setup.sh stopped before changing anything", r.stderr)
        after = self.snapshot()
        lock = os.path.join(self.state, "dotclaude", "install.lock")
        if shutil.which("flock"):
            self.assertEqual(after.pop(lock), "file")
        self.assertEqual(after, before)

    def test_the_main_checkout_goes_on_and_releases_it(self):
        self.install(self.a)
        r = self.head(self.main)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("releases the install held by", r.stdout)
        self.assertIn("past the hold", r.stdout)

    def test_a_failing_helper_warns_and_goes_on(self):
        self.install(self.a)
        r = self.head(self.b, helper="import sys\nsys.exit(1)\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("past the hold", r.stdout)
        self.assertIn("the install hold check failed (exit 1", r.stderr)


class Compatibility(unittest.TestCase):
    def test_the_source_parses_as_python_3_8(self):
        with open(INSTALL_STATE) as f:
            ast.parse(f.read(), filename=INSTALL_STATE, feature_version=(3, 8))

    def test_importing_it_loads_neither_tomllib_nor_fcntl(self):
        code = ("import importlib.machinery, importlib.util, sys\n"
                "before = set(sys.modules)\n"
                f"loader = importlib.machinery.SourceFileLoader('install_state', {INSTALL_STATE!r})\n"
                "mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))\n"
                "loader.exec_module(mod)\n"
                "print(sorted({'tomllib', 'fcntl'} & (set(sys.modules) - before)))\n"
                "print(sorted({'tomllib', 'fcntl'} & before))\n")
        r = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True)
        self.assertEqual(r.stdout, "[]\n[]\n", r.stderr)


if __name__ == "__main__":
    unittest.main()
