"""install-state.py: the install hold, the link prune and the plugin-change line (stdlib only).

Every test runs on a temp machine: HOME, CLAUDE_CONFIG_DIR, CODEX_HOME and XDG_STATE_HOME point
into a temp dir, beside a real git repo with two `git worktree add` lanes and its lanes config.
"""
import ast
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import resource
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

# The fake dotclaude's files: one per setup.sh source kind, a README nothing links, tmux/ files
# only setup-tmux.sh links, and the two files that mark a dotclaude checkout.
FILES = ("CLAUDE.md", "README.md", "hooks/a.sh", "hooks/b.py", "skills/s1/SKILL.md",
         "skills/s1/scripts/tool", "agents/x.md", "templates/T.md", "bin/tool2", "statusline/w.py",
         "codex/AGENTS.md", "tmux/claude.conf", "tmux/pass-last", "install-state.py", "setup.sh")


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

    def other_repo(self, name, files):
        """A separate repo holding files, and its linked worktree <name>-wt, which it returns."""
        repo, wt = os.path.join(self.tmp, name), os.path.join(self.tmp, f"{name}-wt")
        self.git("init", "-q", "-b", "main", repo, cwd=self.tmp)
        for rel in files:
            write(os.path.join(repo, rel), rel + "\n")
        self.git("add", "-A", cwd=repo)
        self.git("commit", "-qm", "files", cwd=repo)
        self.git("worktree", "add", "-q", "-b", "wt", wt, cwd=repo)
        return wt

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

    def forge_admin(self, root):
        """Point root's .git file at a fake admin dir outside this repo whose gitdir names root
        back, as sandboxed Bash in that worktree can: git would read it as fake's worktree."""
        admin = os.path.join(self.tmp, "fake", ".git", "worktrees", "A")
        write(os.path.join(admin, "gitdir"), os.path.join(root, ".git") + "\n")
        write(os.path.join(admin, "HEAD"), "ref: refs/heads/forged\n")
        write(os.path.join(root, ".git"), f"gitdir: {admin}\n")
        self.assertIsNotNone(install_state.linked_worktree(root))
        return admin


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
        # From the clone, lane a is another repo's worktree: it holds only as a dotclaude checkout.
        os.unlink(os.path.join(self.a, "install-state.py"))
        self.assertEqual(install_state.holders(clone, self.env), [])
        self.assertEqual([h["root"] for h in install_state.holders(self.b, self.env)], [self.a])

    def test_another_projects_worktree_neither_holds_nor_is_pruned(self):
        # Its bin/x matches setup.sh's bin/* glob, but it is no lane of this repo.
        wt = self.other_repo("proj2", ("bin/x", "README.md"))
        dst = self.link(os.path.join(wt, "bin", "x"), os.path.join(self.bin, "x"))
        for run_from in (self.main, self.b):
            with self.subTest(run_from):
                self.assertEqual(install_state.holders(run_from, self.env), [])
                self.assertEqual(self.cli("hold", run_from).returncode, 0)
                self.assertEqual(install_state.prune(run_from, self.env), [])
                self.assertEqual(os.readlink(dst), os.path.join(wt, "bin", "x"))

    def test_a_dotclaude_worktree_of_another_clone_holds_but_is_not_pruned(self):
        wt = self.other_repo("dotclaude2", ("install-state.py", "setup.sh", "hooks/a.sh"))
        dst = self.link(os.path.join(wt, "hooks", "a.sh"), os.path.join(self.claude, "hooks", "a.sh"))
        self.assertEqual([h["root"] for h in install_state.holders(self.main, self.env)], [wt])
        self.assertEqual(self.cli("hold", self.main).returncode, 3)
        self.assertEqual(install_state.prune(self.main, self.env), [])
        self.assertTrue(os.path.islink(dst))

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

    def test_a_lane_naming_a_fake_admin_is_released_by_the_real_main(self):
        # Its .git file says its main is fake/, but this repo's own worktrees/ registers it.
        self.install(self.a)
        write(os.path.join(self.a, "hooks", "lane-only.sh"))  # a hook main doesn't have
        only = self.link(os.path.join(self.a, "hooks", "lane-only.sh"),
                         os.path.join(self.claude, "hooks", "lane-only.sh"))
        self.forge_admin(self.a)
        (h,) = install_state.holders(self.main, self.env)
        self.assertEqual((h["root"], h["main"], h["branch"]), (self.a, self.main, "a"))
        r = self.cli("hold", self.main)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn(f"releases the install held by {self.a} (branch a, 12 links)", r.stdout)
        # A sibling lane is still held, and told which main releases it.
        r = self.cli("hold", self.b)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn(f"The lead's ./setup.sh in {self.main} releases it", r.stderr)
        # Main's run relinks what it has, and its prune takes the lane-only link: the hold it
        # said it releases is gone, for the sibling too.
        self.install(self.main)
        self.assertEqual(install_state.prune(self.main, self.env),
                         [f"removed link {only} -> {self.a}/hooks/lane-only.sh"])
        self.assertEqual(install_state.holders(self.b, self.env), [])
        self.assertEqual(self.cli("hold", self.b).returncode, 0)

    def test_a_planted_registration_of_another_projects_worktree_prunes_nothing_there(self):
        # A lane can write this repo's .git/worktrees/: an entry naming proj2's worktree back
        # registers it here, but it is no dotclaude checkout, so its links stay.
        wt = self.other_repo("proj2", ("bin/x", "hooks/a.sh", "README.md"))
        dsts = [self.link(os.path.join(wt, "bin", "x"), os.path.join(self.bin, "x")),
                self.link(os.path.join(wt, "hooks", "a.sh"), os.path.join(self.claude, "hooks", "a.sh"))]
        write(os.path.join(self.common, "worktrees", "planted", "gitdir"), os.path.join(wt, ".git") + "\n")
        self.assertIn(wt, install_state.registered(self.common))
        before = self.snapshot()
        for run_from in (self.main, self.b):
            with self.subTest(run_from):
                self.assertEqual(install_state.holders(run_from, self.env), [])
                self.assertEqual(install_state.prune(run_from, self.env), [])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(os.path.islink(d) for d in dsts))

    def test_a_lane_planting_its_own_registry_is_still_held(self):
        # b's .git file names a common dir inside b whose worktrees/ registers a: b's run reads
        # itself as a's main, but only a real main checkout (a .git dir) releases.
        self.install(self.a)
        planted = os.path.join(self.b, "planted-git")
        write(os.path.join(planted, "worktrees", "x", "gitdir"), os.path.join(self.a, ".git") + "\n")
        write(os.path.join(self.b, ".git"), f"gitdir: {planted}\n")
        (h,) = install_state.holders(self.b, self.env)
        self.assertEqual((h["root"], h["main"]), (self.a, self.b))
        r = self.cli("hold", self.b)
        self.assertEqual((r.returncode, r.stdout), (3, ""), r.stderr)

    def test_a_worktree_inside_main_naming_a_fake_admin_neither_holds_nor_is_pruned(self):
        # An agent worktree inside main whose .git file names an admin outside it (so the
        # inside-its-own-main check passes) with a commondir back to this repo's.
        inner = os.path.join(self.main, ".claude", "worktrees", "agent-x")
        self.git("worktree", "add", "-q", "-b", "agent-x", inner)
        write(os.path.join(self.forge_admin(inner), "commondir"), self.common + "\n")
        self.install(inner)
        before = self.snapshot()
        for run_from in (self.main, self.b):
            with self.subTest(run_from):
                self.assertEqual(install_state.holders(run_from, self.env), [])
                self.assertEqual(self.cli("hold", run_from).returncode, 0)
                self.assertEqual(install_state.prune(run_from, self.env), [])
        self.assertEqual(self.snapshot(), before)

    def test_a_nul_in_a_lanes_git_metadata_reads_as_no_worktree(self):
        # realpath raises ValueError on a NUL: a lane writing one crashed holders and prune.
        self.install(self.a)
        admin = os.path.join(self.common, "worktrees", "a")
        for path, text in ((os.path.join(self.a, ".git"), f"gitdir: {admin}\0x\n"),
                           (os.path.join(admin, "gitdir"), f"{self.a}/.git\0\n")):
            with self.subTest(path):
                with open(path) as f:
                    original = f.read()
                write(path, text)
                try:
                    self.assertIsNone(install_state.linked_worktree(self.a))
                    self.assertEqual(install_state.holders(self.b, self.env), [])
                    self.assertEqual(self.cli("prune", self.main).returncode, 0)
                finally:
                    write(path, original)

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

    def test_a_dangling_link_into_a_removed_agent_worktree_is_pruned(self):
        # Claude Code's agent worktrees sit in <main>/.claude/worktrees/<x>/: strip <x>/, as for
        # a lane under the lanes root, but only on a run whose main is that main.
        agents = os.path.join(self.main, ".claude", "worktrees")
        target = os.path.join(agents, "agent-x", "skills", "s1", "scripts", "tool")
        unmanaged = self.link(os.path.join(agents, "agent-x", "README.md"),
                              os.path.join(self.claude, "README.md"))
        other = os.path.join(self.tmp, "proj2", ".claude", "worktrees", "agent-y", "hooks", "b.py")
        foreign = self.link(other, os.path.join(self.claude, "hooks", "b.py"))
        for run_from in (self.main, self.b):
            with self.subTest(run_from):
                dst = self.link(target, os.path.join(self.bin, "tool"))
                self.assertEqual(self.prune(run_from), [f"removed link ~/.local/bin/tool -> {target}"])
                self.assertFalse(os.path.lexists(dst))
                self.assertTrue(os.path.islink(unmanaged) and os.path.islink(foreign))

    def test_a_link_that_cant_be_removed_warns_and_the_rest_still_go(self):
        # One PermissionError used to abort the prune, and the lines already removed never printed.
        if os.geteuid() == 0:
            self.skipTest("root removes links from a read-only dir")
        self.install(self.a)
        hooks = os.path.join(self.claude, "hooks")
        os.chmod(hooks, 0o555)
        self.addCleanup(os.chmod, hooks, 0o755)
        r = self.cli("prune", self.main)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("==> removed link "), 9, r.stdout)  # 11, less hooks' two
        self.assertIn(f"removed link {self.claude}/CLAUDE.md -> {self.a}/CLAUDE.md", r.stdout)
        self.assertIn(f"removed link ~/.local/bin/tool2 -> {self.a}/bin/tool2", r.stdout)
        for name in ("a.sh", "b.py"):
            self.assertIn(f"{hooks}/{name} -> {self.a}/hooks/{name}", r.stderr)
            self.assertTrue(os.path.islink(os.path.join(hooks, name)))
        self.assertNotIn("Traceback", r.stderr)

    def test_each_removal_is_reported_as_it_happens(self):
        self.install(self.a)
        seen = []
        out = install_state.prune(self.main, self.env, say=seen.append)
        self.assertEqual((len(out), seen), (11, out))

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

    def test_a_config_nested_past_the_recursion_limit_has_no_root(self):
        # tomllib raises RecursionError there, not TOMLDecodeError.
        self.assertIsNone(install_state.config_root("root = " + "[" * 100000))


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
        self.assertIn(f"~/.local/bin/pass-last -> {self.a}/tmux/pass-last (setup-tmux.sh)", found)
        self.assertIn(f'~/.tmux.conf: source-file "{self.a}/tmux/claude.conf" (setup-tmux.sh)', found)
        dirs = {os.path.dirname(l.split(" -> ")[0]) for l in found if " -> " in l}
        self.assertEqual(len(dirs), 9, dirs)  # all nine managed dirs
        self.assertTrue(os.path.islink(tmux))

    def test_each_line_names_the_installer_that_relinks_it(self):
        j = os.path.join
        self.link(j(self.a, "hooks", "a.sh"), j(self.claude, "hooks", "a.sh"))
        self.link(j(self.a, "skills", "s1", "scripts", "tool"), j(self.bin, "tool"))
        self.link(j(self.a, "tmux", "pass-last"), j(self.bin, "pass-last"))
        self.link(j(self.a, "README.md"), j(self.claude, "README.md"))
        self.link(j(self.a, "hooks", "sub", "x.sh"), j(self.claude, "hooks", "x.sh"))
        write(j(self.home, ".tmux.conf"), f'{install_state.TMUX_START}\n'
                                          f'source-file "{self.a}/tmux/base.conf"\n'
                                          f'{install_state.TMUX_END}\n')
        self.assertEqual(sorted(install_state.links_into(self.a, self.env)), sorted([
            f"{self.claude}/hooks/a.sh -> {self.a}/hooks/a.sh (setup.sh)",
            f"~/.local/bin/tool -> {self.a}/skills/s1/scripts/tool (setup.sh)",
            f"~/.local/bin/pass-last -> {self.a}/tmux/pass-last (setup-tmux.sh)",
            f'~/.tmux.conf: source-file "{self.a}/tmux/base.conf" (setup-tmux.sh)',
            f"{self.claude}/README.md -> {self.a}/README.md (by hand)",
            f"{self.claude}/hooks/x.sh -> {self.a}/hooks/sub/x.sh (by hand)",
        ]))

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

    def plugins_cli(self):
        """`install-state.py plugins` in a child capped at 1 GiB of address space and 20 seconds:
        a blocking open or an endless read fails the test, not the machine."""
        def cap():
            resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))
        return subprocess.run([sys.executable, INSTALL_STATE, "plugins"], env=self.env,
                              capture_output=True, text=True, timeout=20, preexec_fn=cap)

    def test_a_fifo_a_device_link_and_a_dangling_link_hash_promptly(self):
        # A mod dir is a linked checkout dir, which sandboxed Bash in a lane can write.
        d = os.path.join(self.src, "autopass")
        self.change()
        for name, make in (("pipe", os.mkfifo),
                           ("zero", lambda p: os.symlink("/dev/zero", p)),
                           ("dangling", lambda p: os.symlink(os.path.join(d, "gone"), p))):
            with self.subTest(name):
                make(os.path.join(d, name))
                r = self.plugins_cli()
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("(autopass@skills-dir changed)", r.stdout)
        self.assertEqual(self.plugins_cli().stdout, "")

    def test_a_link_counts_by_its_target_not_what_it_reads(self):
        d = os.path.join(self.src, "autopass")
        for name in ("one", "two"):
            write(os.path.join(d, f"{name}.ts"), "same\n")
            write(os.path.join(d, f"lib-{name}", "x.ts"), "same\n")
        os.symlink("one.ts", os.path.join(d, "cfg.ts"))
        os.symlink("lib-one", os.path.join(d, "lib"))
        self.change()
        for link, target in (("cfg.ts", "two.ts"), ("lib", "lib-two")):
            with self.subTest(link):
                os.unlink(os.path.join(d, link))
                os.symlink(target, os.path.join(d, link))
                self.assertEqual(self.change(), "plugins changed (autopass@skills-dir changed): "
                                                + install_state.CHANGED)

    def test_a_manifest_nested_past_the_recursion_limit_names_the_mod_by_its_dir(self):
        # json raises RecursionError, not ValueError, on deep nesting: it read as a crash.
        self.change()
        write(os.path.join(self.src, "autopass", ".claude-plugin", "plugin.json"), "[" * 200000)
        r = self.plugins_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(autopass added, autopass@skills-dir removed)", r.stdout)

    def test_the_cli_prints_the_line_once(self):
        self.assertEqual(self.cli("plugins").stdout, "")
        self.mod("newmod")
        r = self.cli("plugins")
        self.assertEqual((r.returncode, r.stdout.count("\n")), (0, 1))
        self.assertTrue(r.stdout.startswith("!!  plugins changed (newmod@skills-dir added): "))


def sparse(path, size=2 << 30):
    with open(path, "wb") as f:
        f.truncate(size)


def capped():
    """A child's limits: 1 GiB of address space, so an endless read fails it, not the machine."""
    resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))


# One install-state.py call in a child, by name: hold, prune and plugins through main() as the
# CLI runs them, any other a function called with the args. Its last stdout line lists each file
# it opened for reading (the audit hook sees builtin open and os.open alike).
DRIVER = r"""
import importlib.machinery, importlib.util, json, os, sys
loader = importlib.machinery.SourceFileLoader("install_state", sys.argv[1])
mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(mod)
opened = []
def audit(event, args):
    if event == "open" and isinstance(args[0], str) and args[2] & os.O_ACCMODE == os.O_RDONLY:
        opened.append(args[0])
sys.addaudithook(audit)
name, args = sys.argv[2], sys.argv[3:]
if name in ("hold", "prune", "plugins"):
    code = mod.main(["install-state.py", name, *args])
else:
    code = 0
    getattr(mod, name)(*args)
sys.stdout.flush()
print("\nOPENED " + json.dumps(opened))
sys.exit(code)
"""


class BoundedReads(Machine):
    """The backstop for read_bounded: every file install-state.py reads, swapped in turn for a
    FIFO, a link to /dev/zero and a sparse 2 GiB file, and each command still returns at once.

    Lane a holds the install; lane b holds one link too, names a forged admin whose commondir is
    this repo's, and is no longer registered here (so its branch comes from the forged HEAD); a
    planted entry in this repo's worktrees/ names a dir that isn't there."""

    WAIT = 10  # seconds: a blocking open or an endless read never finishes

    def setUp(self):
        super().setUp()
        j = os.path.join
        self.install(self.a)
        self.link(j(self.b, "hooks", "a.sh"), j(self.claude, "hooks", "c.sh"))
        self.fake = self.forge_admin(self.b)
        write(j(self.fake, "commondir"), self.common + "\n")
        shutil.rmtree(j(self.common, "worktrees", "b"))
        write(j(self.common, "worktrees", "planted", "gitdir"), j(self.tmp, "gone", ".git") + "\n")
        write(j(self.home, ".tmux.conf"), f'{install_state.TMUX_START}\n'
                                          f'source-file "{self.a}/tmux/claude.conf"\n'
                                          f'{install_state.TMUX_END}\n')
        src, self.mod = j(self.tmp, "src", "m"), j(self.claude, "skills", "m")  # read via the link
        write(j(src, ".claude-plugin", "plugin.json"), '{"name": "m"}')
        write(j(src, "index.ts"), "export {}\n")
        self.link(src, self.mod)
        write(j(self.claude, "plugins", "installed_plugins.json"),
              json.dumps({"version": 2, "plugins": {"p@x": [{"version": "1", "gitCommitSha": "ab"}]}}))
        self.assertEqual(self.cli("plugins").returncode, 0)  # the saved fingerprint
        admin_a = j(self.common, "worktrees", "a")
        self.targets = {
            "a lane's .git file": j(self.a, ".git"),
            "a forged lane's .git file (the run's own)": j(self.b, ".git"),
            "<admin>/gitdir": j(self.fake, "gitdir"),
            "<admin>/HEAD": j(self.fake, "HEAD"),
            "<admin>/commondir": j(self.fake, "commondir"),
            "<common>/worktrees/<x>/gitdir": j(admin_a, "gitdir"),
            "<common>/worktrees/<x>/HEAD": j(admin_a, "HEAD"),
            "<common>/worktrees/<x>/commondir": j(admin_a, "commondir"),
            "a planted <common>/worktrees/<x>/gitdir": j(self.common, "worktrees", "planted", "gitdir"),
            "a mod's plugin.json": j(self.mod, ".claude-plugin", "plugin.json"),
            "installed_plugins.json": j(self.claude, "plugins", "installed_plugins.json"),
            "~/.tmux.conf": j(self.home, ".tmux.conf"),
            "the lanes config": self.config,
            "the saved plugin fingerprint": j(self.state, "dotclaude", "install-plugins.json"),
        }

    def relink(self):
        self.install(self.a)
        self.link(os.path.join(self.b, "hooks", "a.sh"), os.path.join(self.claude, "hooks", "c.sh"))

    def calls(self):
        """The five, the first four side by side, then prune (it removes the links they read)."""
        return ([("hold", self.b), ("holders", self.main), ("links_into", self.a), ("plugins",)],
                [("prune", self.main)])

    def run_calls(self, calls):
        """call -> (exit code, stdout, stderr, files opened for reading), or None past WAIT."""
        procs = [(c, subprocess.Popen([sys.executable, "-c", DRIVER, INSTALL_STATE, *c],
                                      env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, preexec_fn=capped)) for c in calls]
        out = {}
        for c, proc in procs:
            try:
                stdout, stderr = proc.communicate(timeout=self.WAIT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                out[c[0]] = None
                continue
            body, sep, opened = stdout.rpartition("\nOPENED ")  # none when the child crashed
            out[c[0]] = ((proc.returncode, body, stderr, json.loads(opened)) if sep
                         else (proc.returncode, stdout, stderr, []))
        return out

    def test_the_sweep_covers_every_file_the_module_reads(self):
        # Every target is read by one of the five, and nothing else is but a mod's own files
        # (tree_hash's chunked reader): a new read must join the targets, so the sweep covers it.
        opened = set()
        for batch in self.calls():
            for name, result in self.run_calls(batch).items():
                self.assertIsNotNone(result, f"{name} still ran after {self.WAIT} s")
                code, _, stderr, files = result
                self.assertIn(code, (0, install_state.HELD) if name == "hold" else (0,), stderr)
                opened.update(f for f in files if install_state.inside(f, self.tmp))
        self.assertEqual(sorted(set(self.targets.values()) - opened), [])
        self.assertEqual(sorted(f for f in opened - set(self.targets.values())
                                if not install_state.inside(f, self.mod)), [])

    def test_a_fifo_a_device_link_or_a_huge_file_in_place_of_any_of_them_reads_promptly(self):
        kinds = (("a FIFO", os.mkfifo),
                 ("a link to /dev/zero", lambda p: os.symlink("/dev/zero", p)),
                 ("a sparse 2 GiB file", sparse))
        for what, path in self.targets.items():
            with open(path, "rb") as f:
                original = f.read()
            for kind, make in kinds:
                with self.subTest(f"{what} as {kind}"):
                    os.unlink(path)
                    make(path)
                    try:
                        results = {}
                        for batch in self.calls():
                            results.update(self.run_calls(batch))
                    finally:
                        if os.path.lexists(path):
                            os.unlink(path)
                        with open(path, "wb") as f:
                            f.write(original)
                        self.relink()
                    for name, result in results.items():
                        self.assertIsNotNone(result, f"{name} still ran after {self.WAIT} s")
                        code, _, stderr, _ = result
                        self.assertNotIn("Traceback", stderr, name)
                        self.assertIn(code, (0, install_state.HELD) if name == "hold" else (0,),
                                      f"{name}: {stderr}")


class ReadBounded(unittest.TestCase):
    """install-state.py's one reader for everything but a mod's entries."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def path(self, name, text=None):
        p = os.path.join(self.tmp, name)
        if text is not None:
            write(p, text)
        return p

    def read_in_child(self, path, limit, follow=False):
        """read_bounded(path, limit, follow) in a capped child killed after 10 s: a blocking open
        fails the test instead of hanging the suite."""
        code = ("import importlib.machinery, importlib.util, sys\n"
                f"loader = importlib.machinery.SourceFileLoader('s', {INSTALL_STATE!r})\n"
                "mod = importlib.util.module_from_spec(importlib.util.spec_from_loader('s', loader))\n"
                "loader.exec_module(mod)\n"
                f"print(repr(mod.read_bounded({path!r}, {limit}, {follow})))\n")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           timeout=10, preexec_fn=capped)
        self.assertEqual(r.returncode, 0, r.stderr)
        return ast.literal_eval(r.stdout)

    def test_a_regular_file_reads_to_its_limit_and_no_further(self):
        p = self.path("f", "0123456789")
        self.assertEqual(install_state.read_bounded(p, 10), b"0123456789")
        self.assertIsNone(install_state.read_bounded(p, 9))
        self.assertEqual(install_state.read_text(p, 10), "0123456789")

    def test_the_read_stops_at_the_limit_whatever_the_size_says(self):
        # A /proc file says it holds 0 bytes; read_bounded reads limit + 1 and gives up.
        status = "/proc/self/status"
        if not os.path.isfile(status):
            self.skipTest("no /proc here")
        self.assertIsNone(install_state.read_bounded(status, 16))
        self.assertIn(b"Name:", install_state.read_bounded(status, 1 << 20))

    def test_anything_but_a_regular_file_reads_as_absent(self):
        target = self.path("target", "text\n")
        fifo = self.path("fifo")
        os.mkfifo(fifo)
        cases = {"a FIFO": fifo, "a dir": self.tmp, "missing": self.path("missing"),
                 "a link to /dev/zero": self.path("zero"), "a link to a FIFO": self.path("tofifo"),
                 "a link to a regular file": self.path("tofile")}
        os.symlink("/dev/zero", cases["a link to /dev/zero"])
        os.symlink(fifo, cases["a link to a FIFO"])
        os.symlink(target, cases["a link to a regular file"])
        for what, path in cases.items():
            with self.subTest(what):
                self.assertIsNone(self.read_in_child(path, 4096))
        if os.geteuid() != 0:
            os.chmod(target, 0)
            self.addCleanup(os.chmod, target, 0o644)
            self.assertIsNone(install_state.read_bounded(target, 4096))

    def test_follow_reads_through_a_link_to_a_regular_file_only(self):
        # ~/.tmux.conf may be a dotfile manager's link; setup-tmux.sh writes through it.
        target = self.path("target", "text\n")
        fifo = self.path("fifo")
        os.mkfifo(fifo)
        for name, to, want in (("tofile", target, b"text\n"), ("tozero", "/dev/zero", None),
                               ("tofifo", fifo, None)):
            with self.subTest(name):
                link = self.path(name)
                os.symlink(to, link)
                self.assertEqual(self.read_in_child(link, 4096, follow=True), want)

    def test_text_and_json_read_bad_input_as_absent(self):
        with open(self.path("latin"), "wb") as f:
            f.write(b"\xff\xfe")
        self.assertIsNone(install_state.read_text(self.path("latin"), 10))
        for text in ("{not json", "[" * 200000):
            with self.subTest(text[:10]):
                self.assertIsNone(install_state.read_json(self.path("j", text), 1 << 20))
        self.assertEqual(install_state.read_json(self.path("k", '{"a": 1}'), 100), {"a": 1})


class OneReader(unittest.TestCase):
    def test_no_read_escapes_the_helper(self):
        # The grep for open( as a test: os.open only in read_bounded and entry_digest (tree_hash's
        # chunked reader), builtin open only to write, and nothing that reads a file object.
        with open(INSTALL_STATE) as f:
            tree = ast.parse(f.read())
        os_open, builtin_open, other = set(), [], []
        for fn in tree.body:
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                call = ast.unparse(node.func)
                where = getattr(fn, "name", "<module>")
                if call == "os.open":
                    os_open.add(where)
                elif call == "open":
                    mode = node.args[1] if len(node.args) > 1 else None
                    builtin_open.append((where, getattr(mode, "value", None)))
                elif call.rsplit(".", 1)[-1] in ("fdopen", "load", "read_text", "read_bytes") \
                        and call != "read_text":
                    other.append((where, call))
        self.assertEqual(os_open, {"read_bounded", "entry_digest"})
        self.assertTrue(builtin_open, "plugin_change writes its fingerprint with open")
        self.assertEqual([w for w, mode in builtin_open if not (isinstance(mode, str) and "w" in mode)], [])
        self.assertEqual(other, [])


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

    LOCK_RAN = "print('the hold check ran')\n"

    def fake_flock(self, body):
        """A flock first on PATH that logs its args, then runs body (bash; $REAL is the real one)."""
        real = shutil.which("flock", path=self.env["PATH"])
        if real is None:
            self.skipTest("no flock here: setup.sh runs unlocked")
        d = os.path.join(self.tmp, "fakebin")
        self.flock_log = os.path.join(self.tmp, "flock.log")
        write(os.path.join(d, "flock"),
              f'#!/bin/bash\nREAL={real}\necho "$*" >> {self.flock_log}\n{body}\n')
        os.chmod(os.path.join(d, "flock"), 0o755)
        self.env["PATH"] = d + os.pathsep + self.env["PATH"]

    def flock_calls(self):
        with open(self.flock_log) as f:
            return f.read().splitlines()

    def lock_path(self):
        return os.path.join(self.state, "dotclaude", "install.lock")

    def test_a_held_lock_is_waited_for_with_a_limit_then_stops_the_run(self):
        # A sandboxed process can hold the flock on a read-only fd, and nothing names it. The
        # fake turns the 300-second wait into one second.
        self.fake_flock('[[ $1 == -w ]] && set -- -w 1 "${@:3}"\nexec "$REAL" "$@"')
        os.makedirs(os.path.dirname(self.lock_path()), exist_ok=True)
        with open(self.lock_path(), "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            r = self.head(self.b, helper=self.LOCK_RAN)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout, rf"this run \(pid \d+, from {self.b}\) waits up to 5 minutes")
        self.assertIn(f"timed out after 5 minutes waiting for {self.lock_path()}", r.stderr)
        self.assertIn("setup.sh stopped before changing anything", r.stderr)
        self.assertNotIn("the hold check ran", r.stdout)
        self.assertEqual(self.flock_calls(), ["-n 9", "-w 300 9"])

    def test_a_lock_freed_within_the_limit_goes_on(self):
        self.fake_flock('[[ $1 == -n ]] && exit 1\nexit 0')
        r = self.head(self.b, helper=self.LOCK_RAN)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("waits up to 5 minutes", r.stdout)
        self.assertIn("the hold check ran", r.stdout)
        self.assertEqual(self.flock_calls(), ["-n 9", "-w 300 9"])

    def test_a_lock_error_stops_the_run_naming_the_lock(self):
        # ENOLCK: util-linux flock exits 71, not its conflict code 1; the run never waited.
        self.fake_flock("echo 'flock: 9: No locks available' >&2\nexit 71")
        r = self.head(self.b, helper=self.LOCK_RAN)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"couldn't lock {self.lock_path()} (flock exit 71", r.stderr)
        self.assertIn("setup.sh stopped before changing anything", r.stderr)
        self.assertNotIn("waits", r.stdout)
        self.assertNotIn("the hold check ran", r.stdout)

    def test_without_flock_or_a_state_dir_the_run_goes_on_unlocked(self):
        write(os.path.join(self.tmp, "afile"))
        self.env["XDG_STATE_HOME"] = os.path.join(self.tmp, "afile")  # mkdir -p fails under it
        r = self.head(self.b, helper=self.LOCK_RAN)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("the hold check ran", r.stdout)
        self.env["XDG_STATE_HOME"] = self.state
        bins = os.path.join(self.tmp, "noflock")  # what setup.sh's top runs, less flock
        os.makedirs(bins)
        for tool in ("bash", "python3", "dirname", "date", "mkdir"):
            os.symlink(shutil.which(tool), os.path.join(bins, tool))
        self.env["PATH"] = bins
        r = self.head(self.b, helper=self.LOCK_RAN)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("the hold check ran", r.stdout)
        self.assertFalse(os.path.exists(self.lock_path()))

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

    def test_a_lock_file_that_cant_be_opened_stops_the_run_naming_it(self):
        # flock and the state dir are there, so the run must lock: it used to go on unlocked.
        if shutil.which("flock", path=self.env["PATH"]) is None:
            self.skipTest("no flock here: setup.sh runs unlocked")
        lock = self.lock_path()
        state = os.path.dirname(lock)  # holds the lanes config already
        self.addCleanup(os.chmod, state, 0o755)
        for name, make in (("a dir", lambda: os.mkdir(lock)),
                           ("read-only", lambda: (write(lock), os.chmod(lock, 0o444))),
                           ("in a read-only state dir", lambda: os.chmod(state, 0o555))):
            with self.subTest(name):
                if name != "a dir" and os.geteuid() == 0:
                    self.skipTest("root opens a read-only file for writing")
                make()
                try:
                    r = self.head(self.b, helper=self.LOCK_RAN)
                finally:
                    os.chmod(state, 0o755)
                    if os.path.lexists(lock):
                        (os.rmdir if os.path.isdir(lock) else os.unlink)(lock)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn(f"couldn't open {lock} to lock it", r.stderr)
                self.assertIn("setup.sh stopped before changing anything", r.stderr)
                self.assertNotIn("the hold check ran", r.stdout)

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
