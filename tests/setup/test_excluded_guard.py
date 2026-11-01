"""hooks/excluded-guard.sh: excluded commands must not act on anything a sandboxed session can write.

Each test builds a fake HOME (with .claude/settings.json), a project repo made by `git init` plus a
`git worktree add` lane, and PATH dirs holding marker executables (`#!/bin/sh` echo scripts named
git, gh, lane, claude, codex). The temp dir sits under a root ($TMPDIR or /tmp) and belongs to the
user, so a "clean" (protected) dir is one an Edit deny rule in the user settings covers:
permission bits protect nothing there, and only /usr/bin-style dirs outside every root are
protected by location.
"""
import concurrent.futures
import contextlib
import glob
import importlib.util
import io
import json
import os
import random
import re
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "excluded-guard.sh")
SESSION_HOOK = os.path.join(REPO, "hooks", "excluded-check.sh")
MODULE = os.path.join(REPO, "hooks", "excluded_guard.py")
EXCLUDED = ["git push", "git push origin *", "gh pr *", "lane ls", "lane ls *", "lane addr *",
            "claude *", "codex login status"]
HEADS = ("git", "gh", "lane", "claude", "codex")
MARKER = "#!/bin/sh\necho marker\n"
GIT_HELP = os.path.join(REPO, "tests", "setup", "data", "git-help")


def load_guard():
    spec = importlib.util.spec_from_file_location("excluded_guard", MODULE)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    return guard


def slurp(path):
    with open(path) as f:
        return f.read()


def unlock(root):
    for d, dirs, files in os.walk(root):
        os.chmod(d, 0o755)
        for name in files:
            p = os.path.join(d, name)
            if not os.path.islink(p):
                os.chmod(p, 0o644)


class Guard(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.addCleanup(unlock, self.tmp)
        self.home = self.mkdir("home")
        # As setup.sh leaves it: without it every git fetch and pull is refused (G-B).
        self.write(os.path.join(self.home, ".gitconfig"), RECURSE_OFF)
        self.deny_write = []  # paths an Edit deny rule covers (both routes)
        self.sandbox_deny = []  # raw denyWrite lines (sandboxed Bash only)
        self.proj = os.path.join(self.tmp, "proj")
        self.lane = os.path.join(self.tmp, "lane")
        self.git("init", "-q", self.proj, cwd=self.tmp)
        self.git("commit", "-q", "--allow-empty", "-m", "init", cwd=self.proj)
        self.git("remote", "add", "origin", "https://github.com/x/y", cwd=self.proj)
        self.git("worktree", "add", "-q", "-b", "lane", self.lane, cwd=self.proj)
        self.bin = self.make_bin("bin")
        self.wbin = self.make_bin("wbin", protect=False)
        self.write_settings()
        self.env = {"HOME": self.home, "PATH": f"{self.bin}:/usr/bin:/bin",
                    "CLAUDE_PROJECT_DIR": self.proj, "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
                    "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
                    "GIT_CEILING_DIRECTORIES": self.tmp,
                    "EXCLUDED_GUARD_MANAGED_DIR": os.path.join(self.tmp, "managed")}

    # --- fixtures ------------------------------------------------------------------------------

    def mkdir(self, *parts):
        p = os.path.join(self.tmp, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def write(self, path, text, mode=0o644):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)
        return path

    def write_settings(self, extra=None):
        sandbox = {"excludedCommands": EXCLUDED,
                   "filesystem": {"denyWrite": self.sandbox_deny, "allowWrite": []}}
        sandbox.update(extra or {})
        deny = [f"Edit({p}/**)" if p.startswith("~") else f"Edit(/{p}/**)"
                for p in self.deny_write]
        self.write(os.path.join(self.home, ".claude", "settings.json"),
                   json.dumps({"sandbox": sandbox, "permissions": {"deny": deny}}))

    def git(self, *args, cwd):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                              text=True).stdout

    def protect(self, path):
        """Cover `path` with an Edit deny rule in the user settings."""
        self.deny_write.append(path)
        self.write_settings()
        return path

    def make_bin(self, name, heads=HEADS, protect=True):
        d = self.mkdir(name)
        for head in heads:
            self.write(os.path.join(d, head), MARKER, 0o755)
        if protect:
            self.deny_write.append(d)
        return d

    def fire(self, command, cwd=None, raw=None, hook=HOOK, env=None):
        event = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "cwd": cwd or self.proj, "tool_input": {"command": command}}
        p = subprocess.run(["bash", hook], input=raw if raw is not None else json.dumps(event),
                           capture_output=True, text=True, env=env or self.env, timeout=20,
                           cwd=cwd or self.proj)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.last_stdout = p.stdout
        return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None

    def allowed(self, command, **kw):
        out = self.fire(command, **kw)
        self.assertIsNone(out, out and out["permissionDecisionReason"])

    def denied(self, command, rule, path=None, **kw):
        out = self.fire(command, **kw)
        self.assertIsNotNone(out, f"{command!r} was allowed")
        self.assertEqual(out["permissionDecision"], "deny")
        reason = out["permissionDecisionReason"]
        self.assertIn(f"({rule})", reason)
        if path:
            self.assertIn(path, reason)
        return reason

    def log(self):
        try:
            with open(os.path.join(self.tmp, "state", "dotclaude", "excluded-guard.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""


class Rule1Repository(Guard):
    def test_the_project_root_passes(self):
        self.allowed("git push")
        self.allowed("gh pr view 5")

    def test_a_lane_worktree_as_the_project_passes(self):
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.allowed("git push origin lane", cwd=self.lane)
        self.allowed("lane ls", cwd=self.lane)

    def test_a_protected_subdir_of_the_root_in_the_same_repo_passes(self):
        # A writable one is refused (Rule1BelowTop).
        self.protect(self.mkdir("proj", "sub"))
        self.allowed("git push", cwd=self.protect(self.mkdir("proj", "sub", "deeper")))

    def test_a_nested_repo_under_the_root_is_refused(self):
        nested = self.mkdir("proj", "sub", "nested")
        self.git("init", "-q", nested, cwd=self.tmp)
        reason = self.denied("git push", "rule1", os.path.join(nested, ".git"), cwd=nested)
        self.assertIn("deny rule1 " + os.path.join(nested, ".git"), self.log())
        # The cwd's repo is named by its git dir, never as if the cwd were that dir, and the
        # fix names the session that does work.
        self.assertNotIn("resolves to the git dir", reason)
        self.assertIn(f"in the repository with git dir {os.path.join(nested, '.git')}, not the "
                      "project's", reason)
        self.assertIn("a session launched in that repository", reason)

    def test_a_planted_gitfile_pointing_elsewhere_is_refused(self):
        other = self.mkdir("other")
        self.git("init", "-q", other, cwd=self.tmp)
        planted = self.mkdir("proj", "planted")
        self.write(os.path.join(planted, ".git"), "gitdir: ../../other/.git\n")
        self.denied("git push", "rule1", os.path.join(other, ".git"), cwd=planted)

    def test_a_temp_dir_with_its_own_repo_is_refused(self):
        other = self.mkdir("other")
        self.git("init", "-q", other, cwd=self.tmp)
        self.denied("gh pr view", "rule1", cwd=other)

    def test_no_repo_at_a_protected_cwd_passes(self):
        # A writable one is refused (Rule1BelowTop).
        plain = self.protect(self.mkdir("plain"))
        self.env["CLAUDE_PROJECT_DIR"] = plain
        self.allowed("git push", cwd=plain)

    def test_a_project_root_that_is_no_repo_makes_any_repo_foreign(self):
        self.env["CLAUDE_PROJECT_DIR"] = self.mkdir("plain")
        self.denied("git push", "rule1")

    def test_a_protected_cwd_with_no_repo_passes_while_the_project_is_a_repo(self):
        self.allowed("git push", cwd=self.protect(self.mkdir("plain")))

    def test_lane_addr_repo_runs_from_another_repo_and_from_home(self):
        # The global CLAUDE.md line's call, from a session outside dotclaude: the guard judges
        # the cwd, and leaves the --repo path alone by design (the CLI hardens its own git there;
        # Rule1PathArguments pins the exemption).
        call = "lane addr --repo ~/dotclaude lead"
        self.allowed(call)
        # From a writable cwd in no repo too: with --repo, lane runs no git in the cwd, so G-E's
        # cwd half doesn't apply (Rule1BelowTop pins that a bare `lane addr` is still refused).
        self.env["CLAUDE_PROJECT_DIR"] = self.home
        for spelling in (call, "lane addr --repo=~/dotclaude lead", "lane addr lead --repo x",
                         "lane addr --rep ~/dotclaude lead", "lane addr --r=x lead",
                         "lane addr --repo ~/dotclaude lead 2>&1"):
            with self.subTest(call=spelling):
                self.allowed(spelling, cwd=self.home)
        other = self.mkdir("other")
        self.git("init", "-q", other, cwd=self.tmp)
        self.env["CLAUDE_PROJECT_DIR"] = other
        self.allowed(call, cwd=other)

    def test_another_worktrees_config_worktree_is_judged(self):
        # A lane-like project, cwd in the main checkout: same common dir, a different gitdir.
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.allowed("git push", cwd=self.proj)
        cfg = self.write(os.path.join(self.proj, ".git", "config.worktree"), "")
        self.denied("git push", "rule1", cfg, cwd=self.proj)

    def test_a_legacy_remote_file_in_the_common_dir_is_refused_g_c(self):
        # G-C: git reads a remote from <common>/remotes or <common>/branches, outside the judged
        # config, for any call that resolves a remote (the default one, gh's own git too).
        common = os.path.join(self.proj, ".git")
        os.makedirs(os.path.join(common, "branches"), exist_ok=True)  # empty, as git init makes
        self.allowed("git push")
        for kind in ("remotes", "branches"):
            with self.subTest(kind=kind):
                entry = self.write(os.path.join(common, kind, "origin"), "x\n")
                for call, cwd in (("git push", self.proj), ("gh pr view 5", self.proj),
                                  ("git push origin lane", self.lane)):
                    if cwd == self.lane:
                        self.env["CLAUDE_PROJECT_DIR"] = self.lane
                    reason = self.denied(call, "rule1", entry, cwd=cwd)
                    self.env["CLAUDE_PROJECT_DIR"] = self.proj
                    self.assertIn("legacy", reason)
                    self.assertIn("git remote add", reason)
                os.remove(entry)
        self.allowed("git push")

    def test_the_projects_own_config_worktree_is_trusted(self):
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.write(os.path.join(self.proj, ".git", "worktrees", "lane", "config.worktree"), "")
        self.allowed("git push", cwd=self.lane)


class Rule1BelowTop(Guard):
    """G-E cwd half: git finds a repo by walking up from where it runs, so a dir it passes on
    the way that a sandboxed session can write could gain a planted repo between the check and
    the run. A call from below its repo top, or from no repo, is refused unless every dir git
    looks in on the way is protected."""

    PATH_HEADS = ["pass-respawn", "pass-respawn *", "lane adopt *"]

    def setUp(self):
        super().setUp()
        self.write_settings({"excludedCommands": EXCLUDED + self.PATH_HEADS})

    def test_a_call_from_below_the_repo_top_is_refused_with_the_top_to_run_from(self):
        deeper = self.mkdir("proj", "sub", "deeper")
        for call in ("git push", "gh pr view 5", "lane ls"):
            with self.subTest(call=call):
                reason = self.denied(call, "rule1", deeper, cwd=deeper)
                self.assertIn(f"Run it from {self.proj}", reason)
        lane_sub = self.mkdir("lane", "sub")
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.assertIn(f"Run it from {self.lane}",
                      self.denied("git push", "rule1", lane_sub, cwd=lane_sub))

    def test_a_call_from_no_repo_is_refused_unless_no_session_can_write_the_way_up(self):
        plain = self.mkdir("plain")
        for project in (self.proj, plain):
            with self.subTest(project=project):
                self.env["CLAUDE_PROJECT_DIR"] = project
                reason = self.denied("git push", "rule1", plain, cwd=plain)
                self.assertIn("repository top", reason)
        self.env["CLAUDE_PROJECT_DIR"] = self.home
        # Only a command that is one `lane addr --repo` call alone skips this check: lane then runs
        # no git in the cwd (Rule1Repository). Any other call, or one more, is judged.
        for call in ("lane addr lead", "lane addr -- --repo", "lane addr lead --repo",
                     "lane addr --repo x lead; lane ls", "lane addr --repo x lead && lane addr y",
                     "lane addr --repo $(lane ls) lead", "x=1 lane addr --repo x lead",
                     "lane ls --repo x"):
            with self.subTest(call=call):
                self.denied(call, "rule1", self.home, cwd=self.home)
        # Outside every write root no sandboxed session can plant a repo.
        self.env["CLAUDE_PROJECT_DIR"] = "/usr"
        self.allowed("git push", cwd="/usr")

    def test_the_repo_top_and_protected_dirs_on_the_way_pass(self):
        self.allowed("git push")
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.allowed("git push origin lane", cwd=self.lane)
        self.env["CLAUDE_PROJECT_DIR"] = self.proj
        deeper = self.mkdir("proj", "sub", "deeper")
        self.protect(os.path.join(self.proj, "sub", "deeper"))
        # proj/sub is still writable: a repo planted there would be found from deeper.
        self.denied("git push", "rule1", os.path.join(self.proj, "sub"), cwd=deeper)
        self.protect(os.path.join(self.proj, "sub"))
        self.allowed("git push", cwd=deeper)

    def test_a_path_argument_below_its_repo_top_or_in_no_repo_is_refused(self):
        sub = self.mkdir("proj", "sub")
        plain = self.mkdir("plain")
        for call, bad in ((f"pass-respawn -C {sub}", sub), ("pass-respawn -C sub", sub),
                          (f"pass-respawn -C {plain}", plain), (f"lane adopt {sub}", sub)):
            with self.subTest(call=call):
                self.assertIn("repository top", self.denied(call, "rule1", bad))
        for call in (f"pass-respawn -C {self.proj}", f"pass-respawn -C {self.lane}",
                     "pass-respawn -C .", f"lane adopt {self.lane}"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_project_refusals_pass_for_a_lane_root(self):
        # lane new reports project_refusals for the new lane's root: a repo top.
        guard = load_guard()
        refusals, error = guard.project_refusals(self.env, self.lane)
        self.assertEqual(([r.reason for r in refusals], error), ([], None))
        refusals, _ = guard.project_refusals(self.env, self.mkdir("lane", "sub"), self.lane)
        self.assertTrue(refusals)


class Rule1PathArguments(Guard):
    """A path argument a head runs git in is judged as the cwd is, from the project root."""

    PATH_HEADS = ["pass-respawn", "pass-respawn *", "lane adopt *", "git push -*", "git fetch *",
                  "git pull *", "git ls-remote *", "delegation-ledger *", "codex-delegate *"]

    def write_settings(self, extra=None):
        # protect() rewrites the settings too: keep this class's patterns in every rewrite.
        super().write_settings({"excludedCommands": EXCLUDED + self.PATH_HEADS, **(extra or {})})

    def setUp(self):
        super().setUp()
        self.write_settings()
        self.other = self.mkdir("other")
        self.git("init", "-q", self.other, cwd=self.tmp)
        self.other_git = os.path.join(self.other, ".git")

    def refused(self, call, path=None):
        return self.denied(call, "rule1", path)

    def test_pass_respawn_C_in_another_repo_is_refused_in_every_spelling(self):
        o = self.other
        for call in (f"pass-respawn -C {o}", f"pass-respawn -C{o}",
                     f"pass-respawn --compact -C {o}", f"pass-respawn -C {self.proj} -C {o}",
                     f"pass-respawn -C {o} --print", f"pass-respawn -C {o} | cat"):
            with self.subTest(call=call):
                reason = self.refused(call, self.other_git)
                self.assertIn(f"the path argument {o} is in the repository with git dir "
                              f"{self.other_git}, not the project's", reason)
                self.assertIn("a session launched in that repository", reason)

    def test_pass_respawn_C_equals_is_refused_outright(self):
        # argparse reads `-C=x` as x on Python 3.12 and as `=x` on older ones.
        for call in (f"pass-respawn -C={self.lane}", f"pass-respawn -C={self.proj}",
                     "pass-respawn -C=.", f"pass-respawn --compact -C={self.other}"):
            with self.subTest(call=call):
                self.assertIn("use `-C <path>`", self.refused(call, "-C="))

    def test_pass_respawn_C_in_the_project_passes(self):
        for call in (f"pass-respawn -C {self.proj}", f"pass-respawn -C {self.proj} --compact",
                     "pass-respawn -C .", "pass-respawn", "pass-respawn --cancel",
                     f"pass-respawn -C {self.protect(self.mkdir('proj', 'sub'))}",
                     "pass-respawn -C sub", f"pass-respawn -C {self.protect(self.mkdir('plain'))}"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_pass_respawn_C_in_a_lane_of_the_project_passes(self):
        self.allowed(f"pass-respawn -C {self.lane}")
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.allowed(f"pass-respawn -C {self.lane}", cwd=self.lane)

    def test_a_relative_path_is_judged_from_the_cwd(self):
        self.refused("pass-respawn -C ../other", self.other_git)
        # From the lane, ../proj is the project's own top.
        self.allowed("pass-respawn -C ../proj", cwd=self.lane)

    def test_a_home_relative_path_is_expanded(self):
        mine = self.mkdir("home", "repo")
        self.git("init", "-q", mine, cwd=self.tmp)
        self.refused("pass-respawn -C ~/repo", os.path.join(mine, ".git"))

    def test_a_path_the_shell_would_rewrite_is_refused(self):
        for token in ("$HOME/repo", "${HOME}", "`pwd`", "$(pwd)", "~root/x", "/tmp/{a,b}",
                      f"{self.tmp}/oth*", f"{self.tmp}/oth?r", f"{self.tmp}/e(v|x)il",
                      "'my repo'", "=git"):
            with self.subTest(token=token):
                reason = self.refused(f"pass-respawn -C {token}")
                self.assertIn("plain word", reason)

    def test_operators_and_redirections_are_not_arguments(self):
        for call in ("git fetch origin && git merge --ff-only", "git push origin main 2>&1",
                     "git fetch origin 2>&1 | tail -3", "git pull --ff-only > /dev/null",
                     f"pass-respawn -C {self.proj} 2>/dev/null", "git ls-remote origin >out"):
            with self.subTest(call=call):
                self.allowed(call)
        for call in (f"git fetch origin && git fetch {self.other}",
                     f"git push -q {self.other} 2>&1", f"pass-respawn > out -C {self.other}"):
            with self.subTest(call=call):
                self.refused(call, self.other_git)

    def test_a_quote_the_split_cut_is_refused(self):
        # The candidate split isn't quote-aware: a quoted `;` leaves a piece shlex can't read.
        self.refused(f'pass-respawn -C "{self.other};x"')

    def test_lanes_own_fetch_needs_origin_configured(self):
        # lane new, done and park run their own `git fetch ... origin` (review round 2): as for
        # a git call naming no repository, origin must name a remote the config surely defines.
        self.write_settings({"excludedCommands": EXCLUDED + self.PATH_HEADS + [
            "lane new *", "lane done", "lane done *", "lane park *"]})
        calls = ("lane new x", "lane done", "lane done x", "lane park x")
        for call in calls:
            with self.subTest(call=call):
                self.allowed(call)
        self.git("config", "--unset", "remote.origin.url", cwd=self.proj)
        for call in calls:
            with self.subTest(call=call):
                self.assertIn("lane", self.refused(call, "origin"))
        self.allowed("lane ls")
        self.git("config", "remote.origin.url", "https://github.com/x/y", cwd=self.proj)
        self.allowed("lane done x")

    def test_lane_adopt_path_in_another_repo_is_refused(self):
        for call in (f"lane adopt {self.other}", f"lane adopt --id x {self.other}",
                     f"lane adopt -- {self.other}"):
            with self.subTest(call=call):
                self.refused(call, self.other_git)
        # After `--` argparse takes every word as PATH, one that looks like an option too
        # (review round 2).
        for name in ("--id", "-h", "--help", "--i"):
            os.symlink(self.other, os.path.join(self.proj, name))
            with self.subTest(name=name):
                self.refused(f"lane adopt -- {name}", self.other_git)
        self.allowed(f"lane adopt {self.lane}")
        for call in (f"lane adopt --id=lane {self.lane}", f"lane adopt --id x {self.lane}",
                     f"lane adopt {self.lane} --i x"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_git_with_a_local_repository_in_another_repo_is_refused(self):
        o = self.other
        for call in (f"git push -q {o}", f"git push -q {o} HEAD", f"git push -q file://{o}",
                     f"git push -q --repo={o}", f"git push -q --repo {o}", f"git fetch {o}",
                     f"git fetch --quiet file://{o} main", f"git pull {o} main",
                     f"git ls-remote {o}", f"git push origin --repo={o}"):
            with self.subTest(call=call):
                self.refused(call, self.other_git)

    def test_git_with_remotes_refs_and_urls_passes(self):
        for call in ("git push", "git push origin feat/x", "git push -u origin HEAD:refs/heads/x",
                     "git push --force-with-lease origin main",
                     "git fetch origin", "git fetch --prune origin", "git pull --ff-only",
                     "git ls-remote https://github.com/x/y", "git fetch git@github.com:x/y.git",
                     f"git push -q {self.proj}", f"git fetch {self.lane}"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_a_refspec_named_like_a_dir_of_the_project_passes(self):
        # Only the repository word is a path candidate (git_argv): `feat` is a refspec, though
        # proj/feat sits below the repo top (Rule1BelowTop).
        self.mkdir("proj", "feat")
        self.allowed("git push origin feat")

    def test_the_repository_word_is_read_as_git_parses_its_options(self):
        # An option's value and a refspec are no repository; with fetch --multiple every
        # positional is one.
        o = self.other
        for call in (f"git push -o {o} origin", f"git push --push-option {o} origin",
                     f"git push -q -o{o} origin", f"git push -qo {o} origin", f"git push origin {o}",
                     f"git push --push-o={o} origin", f"git fetch origin main {o}"):
            with self.subTest(call=call):
                self.allowed(call)
        for call in (f"git fetch --multiple origin {o}", f"git fetch -m origin {o}",
                     f"git pull -j {o}", f"git push -o x -- {o}", f"git push --no-repo {o}"):
            with self.subTest(call=call):
                self.refused(call, self.other_git)

    def test_an_option_git_doesnt_list_or_cant_resolve_is_refused_by_name(self):
        for call, word in (("git push --bogus origin", "--bogus"), ("git push -x origin", "-x"),
                           ("git push --f origin", "--f"), ("git push origin --repo", "--repo"),
                           ("git fetch --quiet=1 origin", "--quiet=1"),
                           ("git push -h", "-h"), ("git fetch -qZ origin", "-qZ")):
            with self.subTest(call=call):
                reason = self.refused(call, word)
                self.assertIn("git-help", reason)

    def test_git_with_an_option_naming_a_program_is_refused(self):
        # Review round 1 (high): the value is a program git runs, not a repository to judge.
        prog = self.write(os.path.join(self.tmp, "prog"), MARKER, 0o755)
        for call in (f"git push --receive-pack={prog} .", f"git push --receive-pack {prog} .",
                     f"git push --rec={prog} .", f"git push -q --exec={prog} .",
                     f"git push --e={prog} .", f"git fetch --upload-pack={prog} .",
                     f"git fetch --upl {prog} origin", f"git pull --upload-pack={prog} .",
                     f"git ls-remote --upload-pack={prog} .", f"git ls-remote -u {prog} .",
                     f"git ls-remote -qu{prog} .", f"git ls-remote --exec={prog} .",
                     "git fetch ext::sh", f"git push -q ext::{prog}"):
            with self.subTest(call=call):
                self.assertIn("names a program", self.refused(call))
        # Options merely sharing a prefix pass: -u sets upstream for push.
        for call in ("git push -u origin HEAD", "git fetch --update-head-ok origin",
                     "git push --repo=origin"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_git_judges_a_repository_as_its_server_side_finds_it(self):
        # Review round 2: git tries <word>.git when <word> is missing, reads a file there as a
        # gitfile, and takes a file:// URL's path past any host part, %-decoded.
        bare = os.path.join(self.tmp, "evil.git")
        self.git("init", "-q", "--bare", bare, cwd=self.tmp)
        gitfile = self.write(os.path.join(self.tmp, "gf"), f"gitdir: {bare}\n")
        # `git push -q`: a bare `git push <repo>` matches no excluded pattern, so it runs
        # sandboxed.
        for call in (f"git push -q {self.tmp}/evil HEAD", f"git push -q {gitfile} HEAD",
                     f"git fetch file://host{bare}", f"git push -q file:///{bare[1:]} HEAD",
                     f"git ls-remote {bare}", f"git fetch {self.tmp}/evil"):
            with self.subTest(call=call):
                self.refused(call)
        for call in (f"git push -q file://{self.tmp}/%65vil.git HEAD", "git push -q 100% HEAD",
                     "git push -q --repo=a%b HEAD"):
            with self.subTest(call=call):
                self.assertIn("plain word", self.refused(call))

    def test_git_judges_each_path_its_server_side_tries_in_order(self):
        # git's server side (enter_repo, non-strict) tries <p>/.git, <p>, <p>.git/.git and
        # <p>.git in turn and takes the first that is a file or a git dir. A missing one tried
        # before the one git finds today is where a plant would win.
        box = self.mkdir("box")
        found = os.path.join(box, "wt.git")
        self.git("worktree", "add", "-q", "-b", "wt", found, cwd=self.proj)
        self.protect(found)
        p = os.path.join(box, "wt")
        for call in (f"git fetch {p}", f"git push -q {p} HEAD", f"git ls-remote file://{p}"):
            with self.subTest(call=call):
                reason = self.refused(call, os.path.join(p, ".git"))
                self.assertIn("missing", reason)
        self.git("config", "remote.origin.url", p, cwd=self.proj)
        self.assertIn("missing", self.denied("git push", "rule1", os.path.join(p, ".git")))
        # No session can create a path tried before it: git surely takes wt.git.
        self.protect(box)
        for call in (f"git fetch {p}", "git push"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_git_refuses_a_remote_from_a_legacy_remotes_file(self):
        # .git/remotes/<name> and .git/branches/<name> name a URL outside the judged config.
        for kind in ("remotes", "branches"):
            with self.subTest(kind=kind):
                planted = self.write(os.path.join(self.proj, ".git", kind, "evil"), "URL: /x\n")
                self.assertIn("legacy", self.refused("git push -q evil HEAD"))
                self.assertIn("legacy", self.refused("git fetch evil"))
                os.remove(planted)
        # No such file: git finds no remote, and takes the word as a path (G-E path half).
        self.assertIn("missing", self.refused("git push -q evil HEAD"))

    def test_a_missing_repository_a_session_could_create_is_refused_g_e(self):
        # G-E path half: a word that names no configured remote is a path to git, existing or
        # not, and a repo planted there after the check is the one git would run.
        for call, bad in (("git push -q nothere HEAD", self.proj),
                          (f"git fetch {self.tmp}/nothere", self.tmp),
                          (f"git push -q file://{self.tmp}/nothere HEAD", self.tmp),
                          ("git fetch --multiple origin nothere", self.proj),
                          ("git push -q --repo=nothere", self.proj)):
            with self.subTest(call=call):
                reason = self.refused(call, bad)
                self.assertIn("missing", reason)
                self.assertIn("configured remote", reason)
        safe = self.protect(self.mkdir("safe"))
        for call in (f"git fetch {safe}/nothere", "git fetch https://github.com/x/z",
                     "git fetch git@github.com:x/z.git", "git push -q origin HEAD"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_a_relative_repository_word_is_judged_from_the_repo_top_too(self):
        # git moves to the repo top before it opens a relative local repository, so from a
        # subdir `r.git` names <top>/r.git. The guard judges both bases.
        sub = self.protect(self.mkdir("proj", "sub"))
        bare = os.path.join(self.tmp, "r.git")
        self.git("init", "-q", "--bare", bare, cwd=self.tmp)
        os.symlink(bare, os.path.join(self.proj, "r.git"))
        self.assertEqual(subprocess.run(["git", "ls-remote", "r.git"], cwd=sub,
                                        env={"PATH": "/usr/bin:/bin", "HOME": self.home},
                                        capture_output=True).returncode, 0)
        for call in ("git push -q nothere HEAD", "git fetch nothere"):
            with self.subTest(call=call):
                self.assertIn("missing", self.denied(call, "rule1", self.proj, cwd=sub))
        self.denied("git push -q r.git HEAD", "rule1", os.path.join(self.proj, "r.git"), cwd=sub)

    def test_a_configured_remote_is_judged_by_its_url_only(self):
        # A remote's word is no path: its URL is judged with the cwd's config (G-D).
        self.mkdir("proj", "up")
        self.git("remote", "add", "up", "https://github.com/x/up", cwd=self.proj)
        self.allowed("git push -q up HEAD")
        self.git("config", "remote.up.url", self.other, cwd=self.proj)
        self.refused("git push -q up HEAD", self.other_git)
        # A remote with no url is no remote to git: it takes the name as a path.
        self.git("config", "--unset", "remote.up.url", cwd=self.proj)
        self.git("config", "remote.up.fetch", "+refs/heads/*:refs/remotes/up/*", cwd=self.proj)
        self.refused("git push -q up HEAD", os.path.join(self.proj, "up"))

    def test_a_remote_group_is_judged_by_its_members(self):
        # git fetch takes a remotes.<group> config value's words as the remotes to fetch, each
        # a remote name or a path, and runs `git fetch <member>` for each (its builtin/fetch.c).
        o = self.other
        self.git("remote", "add", "up", "https://github.com/x/up", cwd=self.proj)
        self.git("config", "remotes.both", "origin up", cwd=self.proj)
        self.git("config", "remotes.evil", f"origin {o}", cwd=self.proj)
        self.git("config", "remotes.gone", "origin nothere", cwd=self.proj)
        self.git("config", "remotes.nest", "origin evil", cwd=self.proj)
        self.git("config", "remotes.solo", "origin", cwd=self.proj)
        self.git("config", "remotes.one", o, cwd=self.proj)
        self.git("config", "remotes.opt", "origin --upload-pack=x", cwd=self.proj)
        self.git("config", "remotes.sub.grp", f"up {o}", cwd=self.proj)
        # Members that are remotes pass: the group's own name is no path to git.
        for call in ("git fetch both", "git fetch --multiple both origin", "git fetch -m both",
                     "git pull both", "git fetch --multiple solo"):
            with self.subTest(call=call):
                self.allowed(call)
        for call in ("git fetch evil", "git fetch --multiple origin evil", "git pull evil",
                     "git fetch nest", "git fetch --multiple one", "git fetch sub.grp"):
            with self.subTest(call=call):
                self.refused(call, self.other_git)
        self.assertIn("missing", self.refused("git fetch gone", self.proj))
        # One member and no --multiple: git fetches the word itself, here a path.
        self.assertIn("missing", self.refused("git fetch solo", os.path.join(self.proj, "solo")))
        # A member git's own fetch would read as an option.
        self.assertIn("option", self.refused("git fetch opt", "--upload-pack=x"))
        # Members from the global config count too; push and ls-remote take no groups.
        self.write(os.path.join(self.home, ".gitconfig"),
                   RECURSE_OFF + f"[remotes]\n\tglob = origin {o}\n")
        self.refused("git fetch glob", self.other_git)
        self.assertIn("missing", self.refused("git push -q both HEAD", self.proj))

    def test_the_default_remote_must_be_a_configured_remote(self):
        # With no repository word git takes the branch's pushRemote or remote, or
        # remote.pushDefault, else origin. One the config doesn't define is read from a legacy
        # remote file a session could plant after the check, and a branch's or pushDefault's is
        # taken as a path, so each is judged as a repository word too.
        bare = ("git push", "git push -q", "git fetch -q", "git pull -q", "git ls-remote -q")
        named = ("git push -q origin HEAD", "git fetch https://github.com/x/z")
        for call in bare + named:
            with self.subTest(call=call):
                self.allowed(call)
        self.git("config", "--unset", "remote.origin.url", cwd=self.proj)
        for call in bare:
            with self.subTest(call=call):
                reason = self.refused(call, "origin")
                self.assertIn("Name the remote on the command line", reason)
        self.allowed("git fetch https://github.com/x/z")
        self.git("config", "remote.origin.url", "https://github.com/x/y", cwd=self.proj)
        for key in ("branch.x.remote", "branch.x.pushRemote", "remote.pushDefault"):
            # Not a nickname (a URL, `.` for the repo itself, a path with a `/`): git never
            # reads a legacy remote file for it, and the URL or path is judged as one.
            for value in ("https://github.com/x/z", "."):
                with self.subTest(key=key, value=value):
                    self.git("config", key, value, cwd=self.proj)
                    for call in ("git push", "git fetch -q") + named:
                        self.allowed(call)
            # A nickname no config defines is still refused.
            self.git("config", key, "upstream", cwd=self.proj)
            with self.subTest(key=key, value="upstream"):
                self.assertIn(key, self.refused("git push", "upstream"))
            self.git("config", key, "origin", cwd=self.proj)
            self.allowed("git push")
            # A value naming no remote is a path to git: a missing one a session could create.
            self.git("config", key, "nothere", cwd=self.proj)
            with self.subTest(key=key, value="nothere"):
                self.assertIn("missing", self.refused("git push -q origin HEAD", self.proj))
            self.git("config", "--unset", key, cwd=self.proj)
        self.allowed("git push")

    def test_a_remote_only_an_include_if_defines_is_judged_as_a_path(self):
        # The guard doesn't evaluate an includeIf condition, so git may not read its remotes.
        inc = self.write(os.path.join(self.protect(self.mkdir("cfg")), "remotes"),
                         "[remote \"inc\"]\n\turl = https://github.com/x/inc\n")
        self.write(os.path.join(self.home, ".gitconfig"),
                   RECURSE_OFF + f'[includeIf "gitdir:{self.tmp}/nowhere/"]\n\tpath = {inc}\n')
        self.refused("git push -q inc HEAD", self.proj)
        self.write(os.path.join(self.home, ".gitconfig"), RECURSE_OFF + f"[include]\n\tpath = {inc}\n")
        self.allowed("git push -q inc HEAD")

    def test_an_existing_repository_is_judged_along_its_symlink_chain(self):
        # A link a session can rewrite could point git elsewhere after the check.
        link = os.path.join(self.tmp, "link")
        os.symlink(self.proj, link)
        for call in (f"git push -q {link} HEAD", f"git fetch {link}"):
            with self.subTest(call=call):
                self.refused(call, link)
        safe = self.protect(self.mkdir("safe"))
        os.symlink(self.proj, os.path.join(safe, "proj"))
        self.allowed(f"git push -q {safe}/proj HEAD")
        # A gitfile in a dir a session can write could be rewritten after the check too.
        gitfile = self.write(os.path.join(self.proj, "gf"), f"gitdir: {self.proj}/.git\n")
        self.refused("git push -q gf HEAD", gitfile)

    def test_a_relative_gitdir_through_a_symlink_resolves_from_the_link_dir(self):
        # git reads a gitfile's relative gitdir from the dir of the path it opened, not from the
        # symlink target's dir.
        safe = self.protect(self.mkdir("safe"))
        gf = self.write(os.path.join(safe, "inner", "gf"), "gitdir: ../x\n")
        os.symlink(gf, os.path.join(safe, "link"))
        os.symlink(os.path.join(self.proj, ".git"), os.path.join(safe, "x"))  # from the target
        foreign = os.path.join(self.tmp, "x")  # from the link's dir: what git opens
        self.git("init", "-q", "--bare", foreign, cwd=self.tmp)
        self.assertEqual(self.git("ls-remote", os.path.join(safe, "link"), cwd=self.tmp), "")
        self.assertIn("not the project's", self.refused(f"git push -q {safe}/link HEAD", foreign))

    def test_a_gitfile_on_a_judged_path_is_judged_along_its_chain(self):
        # A <p>/.git gitfile naming the project's gitdir, in a dir a session can write, could be
        # repointed at another repository after the check. Only the project's top and its lanes'
        # tops keep their own .git trusted.
        sub = self.mkdir("proj", "sub")
        gitfile = self.write(os.path.join(sub, ".git"), f"gitdir: {self.proj}/.git\n")
        for call in ("git push -q sub HEAD", "pass-respawn -C sub", f"git fetch {sub}",
                     "lane adopt sub"):
            with self.subTest(call=call):
                self.assertIn("could point git at another repository",
                              self.refused(call, gitfile))
        self.denied("git push", "rule1", gitfile, cwd=sub)
        lane_gitfile = os.path.join(self.lane, ".git")
        for call in ("git push -q . HEAD", f"git push -q {self.lane} HEAD",
                     f"pass-respawn -C {self.lane}", f"git fetch {self.proj}"):
            with self.subTest(call=call):
                self.allowed(call)
        # A gitfile naming a lane's gitdir is no lane top unless the lane's gitdir names it back.
        self.write(gitfile, open(lane_gitfile).read())
        self.refused("pass-respawn -C sub", gitfile)
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.allowed(f"pass-respawn -C {self.proj}", cwd=self.lane)

    def test_git_refuses_submodule_recursion(self):
        for call in ("git fetch --recurse-submodules", "git pull --recurse-submodules=yes",
                     "git push --recurse-submodules=on-demand origin", "git fetch --recurse",
                     "git fetch --recurse-submodules-default=yes origin"):
            with self.subTest(call=call):
                self.assertIn("submodule", self.refused(call))
        for call in ("git fetch --no-recurse-submodules origin",
                     "git fetch --recurse-submodules=no origin"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_round_3_spellings_are_refused(self):
        # Review round 3: a redirection holding `&` before the path, a legacy remote given as
        # --repo=, and a substitution in a redirection target.
        self.write(os.path.join(self.proj, ".git", "remotes", "evil"), "URL: /x\n")
        for call in (f"git push -q 2>&1 {self.other} HEAD", f"git fetch >&2 {self.other}",
                     f"pass-respawn 2>&1 -C {self.other}", f"lane adopt 2>&1 {self.other}",
                     "git push --repo=evil HEAD", "git fetch origin <(true)",
                     'git fetch origin >"$(true)"', "git fetch origin > $(true)"):
            with self.subTest(call=call):
                self.refused(call)

    def test_round_4_spellings_are_refused(self):
        # Review round 4: an unmatched piece of a candidate call, a clobber redirection (>|), and
        # an escaped > before a real background &.
        o = self.other
        for call in (f"gh pr list; git push -q {o} HEAD", f"gh pr list; git push {o} HEAD",
                     f"pass-respawn&>/dev/null -C {o}; :", f"git push -q >| /dev/null {o} HEAD",
                     "git fetch origin >| $(true)", f"echo \\>& git push -q {o} HEAD"):
            with self.subTest(call=call):
                self.refused(call)

    def test_a_call_is_judged_as_the_shell_splits_it(self):
        # The shell's own tokens, not a regex split: a guarded call anywhere in a candidate
        # command is judged, inside a subshell, a group, an if or after a newline too.
        o = self.other
        for call in (f"gh pr list; (git push -q {o} HEAD)", f"gh pr list; {{ git push -q {o}; }}",
                     f"gh pr list; if git push -q {o}; then :; fi", f"gh pr list\ngit push {o}",
                     f"gh pr list && GIT_TRACE=1 git push {o}", f"git push -q 2>&1 {o} HEAD",
                     f"git push -q &>>| /dev/null {o}", f"git fetch origin >(cat) {o}",
                     f"git fetch origin $(echo {o})", f"git push -q origin#; git push -q {o}",
                     f"gh pr list `git push -q {o}`", f"gh pr list; git -C {o} push -q",
                     f"gh pr list; git -c a=b fetch {o}", f"gh pr list; git push -q {o} 'x",
                     f"echo $'\\''; pass-respawn -C {o}; echo $'\\''",
                     f"# '\npass-respawn -C {o}\n# '", f'gh pr list "$(git push -q {o})"',
                     f"gh pr list; cat <<EOF\n$(git push -q {o})\nEOF",
                     f"gh pr list; x=$(case a in a) git push -q {o};; esac)",
                     f"pass-respawn -C {o}(N)", f"echo $(( 1 << 2 ))\ngit push -q {o}",
                     f"echo $[ ##a ]; git push -q {o}", f"cat <<$(x)\nb\n$(x)\ngit push -q {o}",
                     f"git push -q ²>log {o}"):
            with self.subTest(call=call):
                self.refused(call)

    def test_a_quoted_or_escaped_operator_is_a_word(self):
        # `";"` and `\;` are words to the shell, not operators, held to the plain-word rule.
        for call in (f'git push -q --repo ";" {self.other}', "git push -q \\; origin",
                     "git fetch origin '|' x", 'pass-respawn -C ">"',
                     f'pass-respawn -C "{self.other};b"'):
            with self.subTest(call=call):
                self.assertIn("plain word", self.refused(call))

    def test_ordinary_calls_pass(self):
        for call in ("git push", "git push origin main", "git push -u origin HEAD",
                     "git push --force-with-lease origin feat/x", "git push origin --delete feat/x",
                     "git fetch origin", "git fetch --prune", "git pull --ff-only",
                     "git ls-remote --heads origin", "git fetch origin main:refs/remotes/origin/main",
                     "git push origin main 2>&1 | tail -3", "git fetch origin && git merge --ff-only",
                     "git pull --rebase > /dev/null 2>&1", f"pass-respawn -C {self.proj}",
                     "gh pr view 5 --json title --jq '.title|ascii_downcase'",
                     "git push origin main && gh pr create --title t --body 'a and b'",
                     'git fetch -q origin; grep -c "a\\|b" README', "git push origin main # done",
                     "git push origin \\\n main", "gh pr comment 5 --body-file - <<'EOF'\nit's done\nEOF",
                     "gh pr view 5 --json body --jq .body | grep -c '^#'"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_a_refspec_may_use_gits_revision_spellings(self):
        # Item 10: zsh hands these on unchanged (RefspecSpellingsMatchZsh), so a refspec or an
        # option value may hold them; a repository word stays a PLAIN_WORD.
        for call in ("git push origin HEAD~1:refs/heads/x", "git push origin main^:refs/heads/y",
                     "git fetch origin ^refs/heads/skip", "git push origin HEAD@{1}:refs/heads/x",
                     "git push origin x^{commit}:refs/heads/y", "git push origin 100%",
                     "git push origin @{-1}:x", "git push origin @{2.days.ago}:x",
                     "git push origin @{u}", "git push -o a~1 origin", "git fetch origin feat~2"):
            with self.subTest(call=call):
                self.allowed(call)
        for call in ("git push origin @{a,b}", "git push origin @{1..3}", "git push origin ~1",
                     "git push origin x{a}", "git push origin @{a{b}}", "git push origin x}",
                     "git push -q x~1 HEAD", "git push -q ^x HEAD", "git push -o ~1 origin",
                     "git push -q a@{u} HEAD"):
            with self.subTest(call=call):
                self.assertIn("plain word", self.refused(call))

    def test_git_refuses_ext_in_an_option_value(self):
        self.assertIn("names a program", self.refused("git push --repo=ext::sh HEAD"))

    def test_git_with_a_word_the_shell_would_rewrite_is_refused(self):
        # Over-matches a quoted refspec glob: the guard can't tell quoting once shlex has run.
        for call in ("git push origin $BRANCH", "git fetch origin '+refs/heads/*:refs/x/*'",
                     f"git push -q {self.tmp}/oth*"):
            with self.subTest(call=call):
                self.assertIn("plain word", self.refused(call))

    def test_delegation_ledger_hook_is_refused_from_bash(self):
        for call in ("delegation-ledger hook", "delegation-ledger hook < /dev/null",
                     "delegation-ledger hook <<< '{}'", "echo {} | delegation-ledger hook"):
            with self.subTest(call=call):
                self.assertIn("stdin", self.refused(call))
        for call in ("delegation-ledger watch", "delegation-ledger wait --pid 1 --max 60",
                     "delegation-ledger audit"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_lane_addr_repo_and_codex_delegate_dir_are_left_unjudged(self):
        # Exempt by design (docs/delegation.md): lane addr's one git lookup there is hardened and
        # runs no repo-local program (probed 2026-10-29); codex-delegate is sent to any repo.
        self.allowed(f"lane addr --repo {self.other} lead")
        self.allowed(f"codex-delegate run --model sol --dir {self.other} --brief b.md")



ZSH = shutil.which("zsh")


@unittest.skipUnless(ZSH, "zsh is not installed")
class LexerMatchesZsh(unittest.TestCase):
    """path_calls finds each call with the argv zsh really runs it with: the stubs record it."""

    # One write per record, so calls running at once in a pipe don't interleave.
    STUBS = (r"""_rec() { local IFS=$'\0'; print -rn -- "$*"$'\0\x1e' >> "$OUT" }"""
             "\ngit() { _rec git \"$@\" }\npass-respawn() { _rec pass-respawn \"$@\" }"
             "\nlane() { _rec lane \"$@\" }\ndelegation-ledger() { _rec delegation-ledger \"$@\" }\n")
    CORPUS = (
        "git push -q origin main", "git push 'a b' \"c d\" e\\ f 't'\"u\"v",
        "git push -q 2>&1 x HEAD", "git push -q 2 >&1 x", "git push -q >| out x",
        "git push -q &>> log x", "git push -q >! log2 x", "git push s 2>/dev/null 1>&2",
        "true pr list; git push x", "true; (git push -q x)", "{ git push -q x; }",
        "if git push -q x; then :; fi", "true\ngit push x", "true && GIT_TRACE=1 git push x",
        "true | git push n", "git push o |& cat", "delegation-ledger wait x",
        "echo $(git push -q x)", 'echo "$(git push -q y)"', "echo `git push -q z`",
        "echo ${x:-$(git push -q r)}", "echo $'\\''; git push -q a; echo $'\\''",
        "# '\ngit push -q b\n# '", "git push origin main # done", "git push origin \\\n main",
        "cat <<'EOF'\nit's\nEOF\ngit push -q c", "cat <<EOF\n$(git push -q d)\nEOF",
        "cat <<-EOF\n\tit's\n\tEOF\ngit push e", "cat <<\\EOF\n$(x\nEOF\ngit push e2",
        "x=$(case a in a) git push -q f;; esac)", 'x="$(case a in a) git push -q f2;; esac)"',
        "git push -q --repo \";\" g",
        "git push -q \\; h", "git fetch origin '|' i", "pass-respawn -C \">\"",
        "lane adopt \"j;k\"", "git push origin#; git push -q l", "echo \"it's\" && git push m",
        "git push ²>log origin", "cat <<EOF\nE\\\nOF\ngit push e3\nEOF", "{ git push x2 }",
        "echo `git push \\\n-q r3`",
    )
    # Lines that name a call zsh never runs: nothing to judge. (A glob group's words are read as
    # a command, an over-judge: `echo \\$(git push no)` yields a call zsh never runs.)
    NO_CALL = ("echo '$(git push no)'", "cat <<'EOF'\n$(git push no)\nEOF")

    def zsh_calls(self, command):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            subprocess.run([ZSH, "-f", "-c", self.STUBS + command], cwd=d, capture_output=True,
                           env={"OUT": out, "PATH": os.environ["PATH"], "HOME": d}, timeout=10,
                           stdin=subprocess.DEVNULL)
            text = slurp(out) if os.path.exists(out) else ""
        return sorted(r.split("\0")[:-1] for r in text.split("\x1e") if r)

    def test_each_call_has_zshs_argv(self):
        guard = load_guard()
        for command in self.CORPUS:
            with self.subTest(command=command):
                calls = self.zsh_calls(command)
                self.assertTrue(calls, "zsh ran no call: the corpus line is wrong")
                self.assertEqual(sorted(w for w, _ in guard.path_calls(command)), calls)
        for command in self.NO_CALL:
            with self.subTest(command=command):
                self.assertEqual(self.zsh_calls(command), [])
                self.assertEqual(list(guard.path_calls(command)), [])

    def test_generated_commands(self):
        # Random commands from shell fragments around `git push -q rN` calls: each call zsh
        # runs must be one path_calls finds, unless the guard refuses the command (the lexer
        # can't read it, or a call holds a word that isn't plain). GUARD_FUZZ_N and
        # GUARD_FUZZ_SEED run a bigger sample by hand.
        guard = load_guard()
        n = int(os.environ.get("GUARD_FUZZ_N", "300"))
        commands = fuzz_commands(int(os.environ.get("GUARD_FUZZ_SEED", "1")), n)
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            ran = list(pool.map(self.zsh_calls, commands))
        missed, judged = [], 0
        for command, calls in zip(commands, ran):
            try:
                found = [w for w, _ in guard.path_calls(command)]
                if any(guard.unplain_word(c) is not None for c in found):
                    continue
            except (ValueError, guard.Refusal):
                continue
            judged += 1
            if any(c not in found for c in calls):
                missed.append((command, calls, found))
        self.assertEqual(missed[:3], [])
        self.assertGreater(judged, n // 2, "most generated commands should be read, not refused")


def snapshot_setopts():
    """The top-level setopt and unsetopt lines of a Claude Code shell snapshot (the options its
    Bash tool's zsh runs with), newest first, or None when none is readable."""
    snaps = glob.glob(os.path.expanduser("~/.claude/shell-snapshots/snapshot-zsh-*.sh"))
    for snap in sorted(snaps, key=lambda f: -os.path.getmtime(f)):
        try:
            lines = slurp(snap).splitlines()
        except OSError:
            continue
        opts = [line for line in lines if re.match(r"(setopt|unsetopt)\b", line)]
        if opts:
            return opts
    return None


@unittest.skipUnless(ZSH, "zsh is not installed")
class RefspecSpellingsMatchZsh(unittest.TestCase):
    """Item 10: each spelling a git refspec word may use beyond PLAIN_WORD is one zsh, with the
    options a Claude Code snapshot sets, hands on unchanged; each it rewrites stays refused."""

    ACCEPTED = ("HEAD~1", "HEAD~", "main~3", "x~y", "x~1~2", "a~", "x:~1", "a=~1", "HEAD^",
                "HEAD^2", "HEAD^^", "^main", "x^1:refs/heads/y", "x^{tree}", "x^{}", "^{/fix}",
                "HEAD@{1}", "@{u}", "@{-1}", "main@{upstream}", "HEAD@{2.days.ago}", "@{0}",
                "@{}", "@{1.2}", "@{x}y", "a@{b}@{c}", "@{@}", "HEAD@{1}~2^3", "100%", "a%b",
                "%1", "%%", "@{1}%", "%x~1", "+HEAD~2:x", "feat/x~1:refs/heads/y", "a,b")
    REWRITTEN = ("@{a,b}", "@{1..3}", "@{a..b}", "~1", "~+", "~-", "x{a,b}", "@{a{b,c}}")

    def zsh_word(self, opts, word):
        with tempfile.TemporaryDirectory() as d:
            p = subprocess.run([ZSH, "-f", "-c", "\n".join(opts) + f"\nprint -rn -- {word}\n"],
                               cwd=d, capture_output=True, text=True, timeout=10,
                               env={"PATH": "/usr/bin:/bin", "HOME": d}, stdin=subprocess.DEVNULL)
        return p.stdout if p.returncode == 0 else None

    def test_each_accepted_spelling_is_handed_on_unchanged(self):
        opts = snapshot_setopts()
        if opts is None:
            self.skipTest("no readable shell snapshot under ~/.claude/shell-snapshots")
        guard = load_guard()
        for word in self.ACCEPTED:
            with self.subTest(word=word):
                self.assertTrue(guard.refspec_word(word), "the guard refuses it")
                self.assertEqual(self.zsh_word(opts, word), word)
        for word in self.REWRITTEN:
            with self.subTest(word=word):
                self.assertFalse(guard.refspec_word(word), "the guard takes it")
                self.assertNotEqual(self.zsh_word(opts, word), word, "zsh keeps it: drop it here")


FUZZ_NOISE = (
    "echo 'a;b'", 'echo "a|b"', "echo \\;", "echo $'\\''", "echo $'a\\nb'", 'echo "$(echo x)"',
    "echo $(echo ')')", "echo `echo x`", "echo ${x:-y}", "echo a#b", "echo *(N)", "echo {a,b}",
    "x=1", "echo $#", 'echo "it\'s"', "echo \\\\", "true", ":", "echo ')'", "echo '('",
    'echo "#"', "echo \\#x", "echo }", "echo {", "echo x }", 'echo "\\""', "echo '\\'",
    "cat <<<'x y'", "echo 2>/dev/null", "echo >|f", "echo $'\\x27'", "echo '<<E'", "echo \\<<E",
    "echo $((1<<2))", "echo $[ ##a ]", "(( x = 1 << 2 ))", "echo \u00b2>f",
)
# Refspec words after a call's repository word: ones zsh hands on unchanged (item 10) and ones
# it rewrites, which the guard must refuse rather than misread.
FUZZ_REFSPECS = ("HEAD~1", "x^{tree}", "@{u}", "main@{1}~2", "^main", "100%", "x:~1", "@{a,b}",
                 "@{1..3}", "~1", "x{a,b}", "'@{a,b}'", "HEAD^2:refs/heads/y", "a~b%c")
FUZZ_REDIRECTS = ("2>&1", ">|f", "&>f", ">!f", "2>f", "<<<x", ">f", "1>f", "<<<'a b'", "2>>f", "<f")


def fuzz_commands(seed, n):
    """n random commands mixing quoting, operators, groups, substitutions, heredocs and
    comments around `git push -q rN` calls (N unique per call)."""
    rng, count = random.Random(seed), [0]

    def call():
        count[0] += 1
        target = rng.choice(("r{}", "'r{}'", '"r{}"', "r''{}", "\\r{}", "\u00b2>f r{}")).format(count[0])
        words = ["git", "push", "-q", target]
        words += [rng.choice(FUZZ_REFSPECS) for _ in range(rng.choice((0, 0, 1, 2)))]
        for _ in range(rng.randrange(3)):
            words.insert(rng.randrange(2, len(words) + 1), rng.choice(FUZZ_REDIRECTS))
        return " ".join(words) + ("" if rng.random() < 0.8 else " # ' ) \" (")

    def statement(depth):
        if depth > 2 or rng.random() < 0.35:
            return call() if rng.random() < 0.5 else rng.choice(FUZZ_NOISE)
        x = lambda: statement(depth + 1)
        kind = rng.randrange(12)
        if kind == 0:
            return f"( {x()} )"
        if kind == 1:
            return f"{{ {x()}; }}" if rng.random() < 0.5 else f"{{ {x()} }}"
        if kind == 2:
            return f"if {x()}; then {x()}; fi"
        if kind == 3:
            return rng.choice(("echo $({})", 'echo "$({})"', "x=$({})")).format(x())
        if kind == 4:
            return f"case a in a) {x()};; esac"
        if kind == 5:
            return f"{x()} {rng.choice(('&&', '||', '|', ';', '|&'))} {x()}"
        if kind == 6:
            return f"{x()}\n{x()}"
        if kind == 7:
            return f"{x()} # it's ( \"\n{x()}"
        if kind == 8:
            inner = x()
            return f"echo `{inner}`" if "`" not in inner else inner
        if kind == 9:  # $'...' on both sides of a call
            return f"echo $'\\'' ; {x()} ; echo $'\\''"
        # A heredoc: an unquoted one runs its $(...), a quoted one doesn't.
        delim = rng.choice(("E", "'E'", '"E"', "\\E", "$(E)", "E"))
        dash = rng.random() < 0.3
        lines = [rng.choice(("it's", "a ) b", "#x", "$(" + x() + ")", "E\\", "x\\", "`echo x`",
                             "\"", "EE", " E", "E\\\nE"))
                 for _ in range(rng.randrange(1, 4))]
        tab = "\t" if dash else ""
        body = "".join(f"{tab}{line}\n" for line in lines)
        end = "$(E)" if delim == "$(E)" else "E"
        return f"cat <<{'-' if dash else ''}{delim}\n{body}{tab}{end}\n{x()}"

    return [statement(0) for _ in range(n)]


class Rule1Layout(Guard):
    """The trusted common dir comes from git's real layout, not from a commondir pointer."""

    def test_a_commondir_planted_in_the_main_gitdir_is_refused(self):
        self.allowed("git push")
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.allowed("git push", cwd=self.lane)
        self.write(os.path.join(self.proj, ".git", "commondir"), self.mkdir("decoy") + "\n")
        gitdir = os.path.join(self.proj, ".git")
        # The lane's common dir now holds a commondir of its own.
        self.assertIn("unexpected layout", self.denied("git push", "rule1", gitdir, cwd=self.lane))
        # A main-checkout project: a <top>/.git dir with a commondir is never a linked gitdir.
        self.env["CLAUDE_PROJECT_DIR"] = self.proj
        self.assertIn("unexpected layout", self.denied("git push", "rule1", gitdir))

    def test_a_lane_commondir_naming_another_dir_is_refused(self):
        other = self.mkdir("other")
        self.git("init", "-q", other, cwd=self.tmp)
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        lane_gitdir = os.path.join(self.proj, ".git", "worktrees", "lane")
        self.write(os.path.join(lane_gitdir, "commondir"), os.path.join(other, ".git") + "\n")
        self.denied("git push", "rule1", lane_gitdir, cwd=self.lane)

    def test_a_linked_gitdir_outside_a_worktrees_dir_is_refused(self):
        # A gitfile into the writable main .git/, at a gitdir whose commondir names that .git/.
        fake = os.path.join(self.proj, ".git", "planted", "x")
        self.write(os.path.join(fake, "commondir"), "../..\n")
        self.write(os.path.join(fake, "HEAD"), "ref: refs/heads/main\n")
        sub = self.mkdir("proj", "sub")
        self.write(os.path.join(sub, ".git"), f"gitdir: {fake}\n")
        self.denied("git push", "rule1", fake, cwd=sub)

    def test_a_root_gitdir_with_a_commondir_is_refused_even_under_a_worktrees_dir(self):
        # <tmp>/worktrees/.git with commondir ../.. would pass the name and target checks.
        top = os.path.join(self.tmp, "worktrees")
        self.git("init", "-q", top, cwd=self.tmp)
        self.git("remote", "add", "origin", "https://github.com/x/y", cwd=top)
        self.env["CLAUDE_PROJECT_DIR"] = top
        self.allowed("git push", cwd=top)
        self.write(os.path.join(top, ".git", "commondir"), "../..\n")
        self.denied("git push", "rule1", os.path.join(top, ".git"), cwd=top)


    def test_a_bare_repo_marker_with_a_commondir_in_a_subdir_is_refused(self):
        # git counts a dir holding HEAD and a commondir as a repo, finding objects/ and refs/
        # in that common dir (probed: rev-parse prints `.` and the decoy, and reads its config).
        decoy = self.mkdir("decoy")
        os.makedirs(os.path.join(decoy, "objects"))
        os.makedirs(os.path.join(decoy, "refs"))
        sub = self.mkdir("proj", "sub")
        self.write(os.path.join(sub, "HEAD"), "ref: refs/heads/main\n")
        self.write(os.path.join(sub, "commondir"), decoy + "\n")
        self.assertEqual(self.git("rev-parse", "--git-common-dir", cwd=sub).strip(), decoy)
        self.denied("git push", "rule1", sub, cwd=sub)


class Rule1Config(Guard):
    def gitconfig(self, text):
        self.write(os.path.join(self.home, ".gitconfig"), text)

    def test_an_include_of_a_writable_file_is_refused(self):
        inc = self.write(os.path.join(self.tmp, "wcfg", "inc.cfg"), "[user]\n\tname = x\n")
        self.gitconfig(f"[include]\n\tpath = {inc}\n")
        self.denied("git push", "rule1", inc)

    def test_an_include_if_target_that_is_writable_is_refused(self):
        inc = self.write(os.path.join(self.tmp, "wcfg", "inc.cfg"), "")
        self.gitconfig(f'[includeIf "gitdir:/nowhere/"]\n  path = "{inc}"  # a comment\n')
        self.denied("git push", "rule1", inc)

    def test_a_writable_hooks_path_is_refused(self):
        hooks = self.mkdir("whooks")
        self.gitconfig(f"[core]\n\thooksPath = {hooks}\n")
        self.denied("git push", "rule1", hooks)

    def test_an_in_repo_hooks_path_is_refused_until_user_settings_protect_it(self):
        # An install step (husky and similar) points core.hooksPath into the repo. The refusal
        # names that case and where a denyWrite entry counts, since project settings don't.
        hooks = self.write(os.path.join(self.proj, ".githooks", "pre-push"), MARKER, 0o755)
        self.git("config", "core.hooksPath", ".githooks", cwd=self.proj)
        reason = self.denied("git push", "rule1", os.path.dirname(hooks))
        self.assertIn("install step", reason)
        self.assertIn("user or managed settings", reason)
        self.protect(os.path.dirname(hooks))
        self.allowed("git push")

    def test_a_protected_include_passes_and_its_own_includes_are_followed(self):
        inc = self.write(os.path.join(self.protect(self.mkdir("pcfg")), "inc.cfg"),
                         "[user]\n\tname = x\n")
        self.gitconfig(f"[include]\n\tpath = {inc}\n")
        self.allowed("git push")
        inner = self.write(os.path.join(self.tmp, "wcfg", "inner.cfg"), "")
        self.write(inc, f"[include]\n\tpath = ../wcfg/inner.cfg\n")
        self.denied("git push", "rule1", inner)

    def test_an_include_in_a_protected_dir_that_symlinks_to_a_writable_file_is_refused(self):
        real = self.write(os.path.join(self.tmp, "wcfg", "real.cfg"), "")
        link = os.path.join(self.protect(self.mkdir("pcfg")), "inc.cfg")
        os.symlink(real, link)
        self.gitconfig(f"[include]\n\tpath = {link}\n")
        self.denied("git push", "rule1", os.path.dirname(real))

    def test_a_symlinked_gitconfig_is_judged_by_its_hops_and_target(self):
        real = self.write(os.path.join(self.tmp, "wcfg", "gitconfig"), "")
        os.remove(os.path.join(self.home, ".gitconfig"))
        os.symlink(real, os.path.join(self.home, ".gitconfig"))
        self.denied("git push", "rule1", os.path.join(self.home, ".gitconfig"))

    def test_a_regular_gitconfig_in_a_writable_home_is_trusted(self):
        self.gitconfig("[user]\n\tname = x\n")
        self.allowed("git push")

    def test_a_fifo_include_target_in_a_writable_dir_is_refused(self):
        fifo = os.path.join(self.mkdir("wcfg"), "inc.cfg")
        os.mkfifo(fifo)  # never opened: the guard must judge it without reading it
        self.gitconfig(f"[include]\n\tpath = {fifo}\n")
        self.denied("git push", "rule1", fifo)

    def test_a_protected_hooks_dir_holding_a_symlinked_hook_is_refused(self):
        hooks = self.protect(self.mkdir("phooks"))
        self.write(os.path.join(hooks, "pre-commit"), MARKER, 0o755)
        self.gitconfig(f"[core]\n\thooksPath = {hooks}\n")
        self.allowed("git push")
        real = self.write(os.path.join(self.tmp, "whook", "pre-push"), MARKER, 0o755)
        os.symlink(real, os.path.join(hooks, "pre-push"))
        self.denied("git push", "rule1", os.path.dirname(real))

    def test_a_hooks_path_symlinked_from_a_protected_dir_to_a_writable_one_is_refused(self):
        whooks = self.mkdir("whooks")
        self.write(os.path.join(whooks, "pre-push"), MARKER, 0o755)
        link = os.path.join(self.protect(self.mkdir("plinks")), "hooks")
        os.symlink(whooks, link)
        self.gitconfig(f"[core]\n\thooksPath = {link}\n")
        self.denied("git push", "rule1", whooks)

    def test_a_denywrite_entry_protects_an_include(self):
        inc = self.write(os.path.join(self.tmp, "wcfg", "inc.cfg"), "")
        self.gitconfig(f"[include]\n\tpath = {inc}\n")
        self.deny_write.append(os.path.dirname(inc))
        self.write_settings()
        self.allowed("git push")

    def test_the_repos_own_config_is_trusted_but_its_includes_are_not(self):
        inc = self.write(os.path.join(self.tmp, "wcfg", "inc.cfg"), "")
        with open(os.path.join(self.proj, ".git", "config"), "a") as f:
            f.write(f"[include]\n\tpath = {inc}\n")
        self.denied("git push", "rule1", inc)

    def test_a_writable_xdg_config_is_refused(self):
        xdg = self.write(os.path.join(self.home, ".config", "git", "config"), "")
        self.denied("git push", "rule1", xdg)

    def test_a_missing_hooks_path_under_a_writable_root_is_refused(self):
        hooks = os.path.join(self.tmp, "nohooks", "hooks")
        self.gitconfig(f"[core]\n\thooksPath = {hooks}\n")
        self.denied("git push", "rule1", hooks)

    def test_a_missing_hooks_path_under_a_denywrite_dir_passes(self):
        hooks = os.path.join(self.protect(self.mkdir("phooks")), "missing")
        self.gitconfig(f"[core]\n\thooksPath = {hooks}\n")
        self.allowed("git push")

    def test_git_config_global_replaces_the_normal_global_files(self):
        # The normal global files are writable; GIT_CONFIG_GLOBAL makes git skip them.
        real = self.write(os.path.join(self.tmp, "wcfg", "gitconfig"), "")
        os.remove(os.path.join(self.home, ".gitconfig"))
        os.symlink(real, os.path.join(self.home, ".gitconfig"))
        self.write(os.path.join(self.home, ".config", "git", "config"), "")
        self.denied("git push", "rule1")
        pcfg = self.write(os.path.join(self.protect(self.mkdir("pcfg")), "global"), "")
        self.env["GIT_CONFIG_GLOBAL"] = pcfg
        self.allowed("git push")
        self.env["GIT_CONFIG_GLOBAL"] = real
        self.denied("git push", "rule1", real)

    def test_a_writable_git_config_system_is_refused_unless_nosystem(self):
        system = self.write(os.path.join(self.tmp, "wcfg", "system"), "")
        self.env["GIT_CONFIG_SYSTEM"] = system
        self.denied("git push", "rule1", system)
        self.env["GIT_CONFIG_NOSYSTEM"] = "1"
        self.allowed("git push")


class Rule1RemoteUrls(Guard):
    """G-D: a local-path remote URL or url.<base> rewrite in the config chain, the repo's own
    trusted config included, is judged as a path argument: an existing repo as rule 1 judges the
    cwd, a missing path by whether a sandboxed session could create it."""

    def setUp(self):
        super().setUp()
        self.other = self.mkdir("other")
        self.git("init", "-q", self.other, cwd=self.tmp)
        self.other_git = os.path.join(self.other, ".git")

    def remote(self, key, value):
        self.git("config", key, value, cwd=self.proj)

    def restore(self, key):
        """Unset key, or put origin's network URL back: a bare `git push` needs origin."""
        if key == "remote.origin.url":
            self.remote(key, "https://github.com/x/y")
        else:
            self.git("config", "--unset", key, cwd=self.proj)

    def test_a_remote_url_naming_another_repo_is_refused(self):
        for key in ("remote.origin.url", "remote.up.pushurl"):
            for value in (self.other, f"file://{self.other}", "../other", self.other_git):
                with self.subTest(key=key, value=value):
                    self.remote(key, value)
                    for call in ("git push", "gh pr view 5"):
                        reason = self.denied(call, "rule1", self.other_git)
                        self.assertIn(f"the remote URL {value}", reason)
                        self.assertIn("network URL", reason)
                    self.restore(key)
        self.allowed("git push")

    def test_an_ext_remote_url_is_refused(self):
        # git runs an ext:: URL's command; protocol.ext.allow keeps it off by default, but the
        # guard judges no program it can't see.
        for key in ("remote.origin.url", "url.ext::x.insteadOf"):
            with self.subTest(key=key):
                self.remote(key, "ext::x %S" if key.startswith("remote") else "https://h/r")
                self.assertIn("ext::", self.denied("git push", "rule1", None))
                self.restore(key)
        self.allowed("git push")

    def test_a_bare_repo_found_as_name_dot_git_is_refused(self):
        bare = os.path.join(self.tmp, "evil.git")
        self.git("init", "-q", "--bare", bare, cwd=self.tmp)
        self.remote("remote.origin.url", os.path.join(self.tmp, "evil"))
        self.denied("git push", "rule1", bare)

    def test_a_missing_path_a_sandboxed_session_could_create_is_refused(self):
        for value in (os.path.join(self.tmp, "nothing", "repo"), "file:///" + self.tmp[1:] + "/x",
                      "../missing"):
            with self.subTest(value=value):
                self.remote("remote.origin.url", value)
                reason = self.denied("git push", "rule1")
                self.assertIn("missing", reason)
        self.remote("remote.origin.url", "/nonexistent-excluded-guard-test/repo")
        self.allowed("git push")

    def test_a_file_url_with_a_host_part_or_escape_is_refused(self):
        for value in ("file://host/x", f"file://{self.tmp}/%6fther"):
            with self.subTest(value=value):
                self.remote("remote.origin.url", value)
                self.denied("git push", "rule1")

    def test_a_url_rewrite_to_a_local_base_is_refused(self):
        # git appends the rest of the original URL to the base, so a local base names a path
        # the guard can't judge from the base alone, even the project's own.
        for key in ("insteadOf", "pushInsteadOf"):
            # Only <scheme>://<host>... (not file) or scp-like [user@]host: passes (review
            # round 2): an empty base, any file: one, an empty host or `ext:` (which a rest
            # starting `:` turns into an ext:: URL) is refused.
            for base in (self.other, self.proj, "../x/", "file:///x/", ".", "", "file:/",
                         "file://", "/x", "x", "FILE://h/x", "https://", "https:///x", ":x",
                         "@:", "ext:", "u@/x:"):
                with self.subTest(key=key, base=base):
                    self.write(os.path.join(self.home, ".gitconfig"),
                               f'[url "{base}"]\n\t{key} = https://github.com/\n')
                    reason = self.denied("git push", "rule1", base)
                    self.assertIn(f"url.{base}.{key}", reason)
                    self.assertIn("network base", reason)
            for base in ("https://mirror.example/", "git@github.com:", "ssh://h/",
                         "https://github.com/", "github.com:", "ssh://git@h:22/x"):
                with self.subTest(key=key, base=base):
                    self.write(os.path.join(self.home, ".gitconfig"),
                               f'[url "{base}"]\n\t{key} = https://github.com/\n')
                    self.allowed("git push")
        os.remove(os.path.join(self.home, ".gitconfig"))
        self.allowed("git push")

    def test_network_urls_and_the_projects_own_paths_pass(self):
        for value in ("https://github.com/x/y", "git@github.com:x/y.git", "ssh://h/x",
                      "host:path/x", self.lane, self.proj, "."):
            with self.subTest(value=value):
                self.remote("remote.origin.url", value)
                self.allowed("git push")


RECURSE_OFF = "[fetch]\n\trecurseSubmodules = false\n"  # what setup.sh sets


class Rule1EnvConfig(Guard):
    """GIT_CONFIG_COUNT and GIT_CONFIG_PARAMETERS set config for every git an excluded call runs.
    Rule 1 reads only the recursion keys from them, so any other key there refuses."""

    def test_an_env_config_key_rule_1_does_not_read_is_refused(self):
        cases = [{"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "remote.origin.url",
                  "GIT_CONFIG_VALUE_0": "/tmp/x"},
                 {"GIT_CONFIG_PARAMETERS": "'url./tmp/x.insteadOf=https://h/'"},
                 {"GIT_CONFIG_PARAMETERS": "'branch.main.remote=/tmp/x'"}]
        for extra in cases:
            with self.subTest(extra=extra):
                self.env.update(extra)
                for call in ("git push", "gh pr view 5", "lane ls"):
                    self.denied(call, "rule1", "GIT_CONFIG")
                for k in extra:
                    del self.env[k]
        self.allowed("git push")

    def test_the_recursion_keys_alone_pass(self):
        self.env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "fetch.recurseSubmodules",
                         "GIT_CONFIG_VALUE_0": "false",
                         "GIT_CONFIG_PARAMETERS": "'submodule.recurse=false'"})
        self.allowed("git push")
        self.allowed("git fetch origin")


class SubmoduleRecursion(Guard):
    """G-B: git fetch and pull, and the gh forms that run them, recurse into submodules, whose
    own git dirs a sandboxed session can write. They pass only with --no-recurse-submodules
    (git) or recursion off in the effective config."""

    FORMS = ["git fetch", "git fetch *", "git pull", "git pull *", "gh issue *"]

    def setUp(self):
        super().setUp()
        self.write_settings({"excludedCommands": EXCLUDED + self.FORMS})
        self.gitconfig = os.path.join(self.home, ".gitconfig")
        os.remove(self.gitconfig)

    def test_recursion_on_by_default_refuses_with_the_fix(self):
        for call in ("git fetch", "git fetch origin", "git pull --ff-only", "git fetch -q origin",
                     "gh pr list; git fetch origin", "gh pr checkout 5", "gh pr merge 5 --squash",
                     "gh pr merge -d 5", "gh issue develop 3 --checkout",
                     "git fetch -o --no-recurse-submodules origin",
                     "git fetch origin -- --no-recurse-submodules"):
            with self.subTest(call=call):
                reason = self.denied(call, "rule1")
                self.assertIn("git config --global fetch.recurseSubmodules false", reason)
                self.assertIn("setup.sh", reason)
                if call.startswith("git"):
                    self.assertIn("--no-recurse-submodules", reason)

    def test_the_flag_or_the_config_switch_off_passes(self):
        for call in ("git fetch --no-recurse-submodules origin", "git pull --no-recurse-submodules",
                     "git fetch -q --prune --no-recurse-submodules", "gh pr view 5",
                     "git fetch origin main --no-recurse-submodules",
                     "git fetch --recurse-submodules=no origin", "gh issue view 3",
                     "git fetch --dry --no-recurse-submodules origin", "git pull --no-rec origin",
                     "git pull -r --no-recurse-submodules", "git pull -j2 --no-recurse-sub"):
            with self.subTest(call=call):
                self.allowed(call)
        # fetch's hidden --recurse-submodules-default makes these ambiguous, and git refuses
        # them (SubmoduleRecursionMatchesGit).
        for call in ("git fetch --no-rec origin", "git fetch -j 2 --no-recurse-sub"):
            with self.subTest(call=call):
                self.assertIn("ambiguous", self.denied(call, "rule1"))
        for config in (RECURSE_OFF, "[submodule]\n\trecurse = true\n" + RECURSE_OFF,
                       "[fetch]\n\trecurseSubmodules = no\n"):
            self.write(self.gitconfig, config)
            # gh pr checkout runs git checkout after its fetch, which honours submodule.recurse.
            pulls = (("git pull", "gh issue develop 3", "gh pr checkout 5")
                     if "recurse =" not in config else ())
            for call in ("git fetch", "git fetch origin") + pulls:
                with self.subTest(config=config, call=call):
                    self.allowed(call)
        self.git("config", "fetch.recurseSubmodules", "false", cwd=self.proj)  # trusted local
        os.remove(self.gitconfig)
        self.allowed("git fetch origin")

    def test_a_later_value_or_the_environment_wins(self):
        self.write(self.gitconfig, RECURSE_OFF + "[submodule]\n\trecurse = true\n")
        self.denied("git fetch", "rule1")
        self.write(self.gitconfig, RECURSE_OFF)
        self.env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="fetch.recurseSubmodules",
                        GIT_CONFIG_VALUE_0="on-demand")
        self.denied("git fetch", "rule1")
        self.env["GIT_CONFIG_PARAMETERS"] = "'fetch.recurseSubmodules'='false'"
        self.allowed("git fetch")

    def test_an_empty_global_or_system_variable_names_no_file(self):
        # git reads no file for a set but empty GIT_CONFIG_GLOBAL (and no XDG file either) or
        # GIT_CONFIG_SYSTEM, so a switch-off in ~/.gitconfig doesn't count then.
        self.write(self.gitconfig, RECURSE_OFF)
        p = subprocess.run(["git", "config", "--get", "fetch.recurseSubmodules"], cwd=self.tmp,
                           env={"PATH": "/usr/bin:/bin", "HOME": self.home,
                                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": ""},
                           capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout), (1, ""))
        self.allowed("git fetch")
        xdg = self.write(os.path.join(self.home, ".config", "git", "config"), "")
        self.denied("git fetch", "rule1", xdg)
        self.env["GIT_CONFIG_GLOBAL"] = ""
        self.denied("git fetch", "rule1", "fetch.recurseSubmodules")
        self.allowed("git fetch --no-recurse-submodules")
        files = load_guard().config_files
        self.assertEqual(files({"GIT_CONFIG_SYSTEM": "", "GIT_CONFIG_GLOBAL": ""}, self.home), [])
        self.assertEqual(files({"GIT_CONFIG_SYSTEM": "/s"}, self.home), ["/s", xdg, self.gitconfig])
        self.assertEqual(files({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/g"}, self.home),
                         ["/g"])

    def test_the_refusal_names_the_key_on_and_a_switch_off_that_doesnt_count(self):
        reason = self.denied("git fetch", "rule1", "fetch.recurseSubmodules")
        self.assertIn("none of fetch.recurseSubmodules or submodule.recurse is set", reason)
        self.write(self.gitconfig, RECURSE_OFF + "[submodule]\n\trecurse = yes\n")
        reason = self.denied("git fetch", "rule1", "submodule.recurse")
        self.assertIn(f"submodule.recurse=yes in {self.gitconfig}", reason)
        # A switch-off from an includeIf file: git may not read it, so it doesn't count.
        off = self.write(os.path.join(self.protect(self.mkdir("inc")), "off"), RECURSE_OFF)
        self.write_settings({"excludedCommands": EXCLUDED + self.FORMS})  # protect() reset it
        self.write(self.gitconfig, f'[includeIf "gitdir:{self.proj}/"]\n\tpath = {off}\n')
        reason = self.denied("git fetch", "rule1", "fetch.recurseSubmodules")
        self.assertIn(f"fetch.recurseSubmodules=false in {off} doesn't count", reason)
        self.assertIn("includeIf", reason)
        self.write(self.gitconfig, "[push]\n\trecurseSubmodules = check\n")
        self.assertIn(f"push.recurseSubmodules=check in {self.gitconfig}",
                      self.denied("git push", "rule1", "push.recurseSubmodules"))

    def test_a_recursion_flag_in_any_prefix_refuses_whatever_the_config(self):
        # git takes any unique prefix (git_argv): pull's --rec is --recurse-submodules, and the
        # last such flag on the command line beats a config switch-off (review round 2).
        self.write(self.gitconfig, RECURSE_OFF)
        for call in ("git pull --rec", "git pull --rec=yes", "git pull --recurse-sub",
                     "git pull --no-recurse-submodules --rec", "git fetch --recurse-submodules",
                     "git fetch --recurse-submodules=on-demand origin",
                     "git push origin --recurse-submodules=check main"):
            with self.subTest(call=call):
                self.assertIn("each submodule", self.denied(call, "rule1"))
        self.assertIn("ambiguous", self.denied("git fetch --recurse-sub", "rule1"))
        self.denied("git fetch --rec origin", "rule1")  # also a prefix of --receive-pack
        self.assertIn("each submodule",
                      self.denied("git fetch --recurse-submodules-default=yes origin", "rule1"))
        self.allowed("git fetch --recurse-submodules-default=no origin")
        for call in ("git pull --recurse-submodules=no", "git fetch --recurse-submodules=off",
                     "git pull --recurse-submodules --no-recurse-submodules",
                     "git push origin --recurse-submodules=no main"):
            with self.subTest(call=call):
                self.allowed(call)

    def test_ghs_built_in_aliases_are_judged_as_their_commands(self):
        # gh 2.89's pr create takes the alias `new` and pr checkout `co` (Aliases: in
        # pkg/cmd/pr); no other form here has one.
        self.assertIn("submodule", self.denied("gh pr co 5", "rule1"))
        self.assertIn("--recurse-submodules",
                      self.denied("gh pr co --recurse-submodules 5", "rule1"))
        self.write(self.gitconfig, RECURSE_OFF + "[push]\n\trecurseSubmodules = check\n")
        self.assertIn("push.recurseSubmodules", self.denied("gh pr new --fill", "rule1"))
        self.allowed("gh pr co 5")

    def test_pull_also_needs_submodule_recurse_off(self):
        # pull updates each submodule after the merge when submodule.recurse is on, whatever
        # fetch.recurseSubmodules says.
        self.write(self.gitconfig, "[submodule]\n\trecurse = true\n" + RECURSE_OFF)
        self.allowed("git fetch")
        for call in ("git pull", "gh pr merge -d 5", "gh pr checkout 5"):
            with self.subTest(call=call):
                self.assertIn("submodule.recurse", self.denied(call, "rule1"))
        self.allowed("git pull --no-recurse-submodules")

    def test_push_needs_push_recursion_off(self):
        # git push reads push.recurseSubmodules and submodule.recurse, the last one wins, and
        # unset is off (SubmoduleRecursionMatchesGit). gh pr create runs git push.
        pushes = ("git push", "git push origin main", "gh pr create --fill")
        for call in pushes:
            with self.subTest(call=call):
                self.allowed(call)
        push_on = "[push]\n\trecurseSubmodules = {}\n"
        for config in (push_on.format("check"), push_on.format("on-demand"),
                       push_on.format("only"), "[submodule]\n\trecurse = true\n",
                       "[submodule]\n\trecurse\n",
                       push_on.format("no") + "[submodule]\n\trecurse = yes\n",
                       "[submodule]\n\trecurse = false\n" + push_on.format("check")):
            self.write(self.gitconfig, config)
            for call in pushes:
                with self.subTest(config=config, call=call):
                    self.assertIn("push", self.denied(call, "rule1"))
            for call in ("git push origin --no-recurse-submodules main",
                         "git push origin --recurse-submodules=no main"):
                with self.subTest(config=config, call=call):
                    self.allowed(call)
        for config in (push_on.format("no"), "[submodule]\n\trecurse = true\n" + push_on.format("0"),
                       push_on.format("check") + "[submodule]\n\trecurse = false\n"):
            self.write(self.gitconfig, config)
            for call in pushes:
                with self.subTest(config=config, call=call):
                    self.allowed(call)

    def test_gh_pr_checkout_with_recursion_is_refused_outright(self):
        self.write(self.gitconfig, RECURSE_OFF)
        # gh's flag parser (pflag) takes a bool flag's value glued on after `=`, as Go's
        # strconv.ParseBool reads it.
        for flag in ("--recurse-submodules", "--recurse-submodules=true", "--recurse-submodules=1",
                     "--recurse-submodules=t", "--recurse-submodules=TRUE",
                     "--recurse-submodules=T", "--recurse-submodules=True",
                     "--recurse-submodules=", "--recurse-submodules=no"):
            with self.subTest(flag=flag):
                self.assertIn("--recurse-submodules",
                              self.denied(f"gh pr checkout {flag} 5", "rule1"))
        for value in ("false", "0", "f", "F", "FALSE", "False"):
            with self.subTest(value=value):
                self.allowed(f"gh pr checkout --recurse-submodules={value} 5")


def parse_git_help(text):
    """(long, short) option tables from `git <sub> -h` text, read on their own (not with the
    guard's spec reader): long name -> none, required or optional (a `--[no-]` name's `no-`
    form too, taking none); short letter -> (kind, long name or None)."""
    long, short = {}, {}
    for line in text.splitlines():
        m = re.match(r" {4}(?:-(?P<s>\w)(?:, |(?=\s|$)))?(?:--(?P<neg>\[no-\])?(?P<l>[a-z0-9-]+))?"
                     r"(?P<opt>\[=[^\]]*\])?(?P<req> [<(]\S+)?(?:\s|$)", line)
        if not m or not (m["s"] or m["l"]):
            continue
        kind = "optional" if m["opt"] else "required" if m["req"] else "none"
        if m["l"]:
            long[m["l"]] = kind
            if m["neg"]:
                long["no-" + m["l"]] = "none"
        if m["s"]:
            short[m["s"]] = (kind, m["l"])
    return long, short


class GitOptionTables(unittest.TestCase):
    """git_argv's option tables are git 2.43's own, as `git <sub> -h` prints them."""

    # Options git 2.43 parses but `-h` hides (PARSE_OPT_HIDDEN), read off git's source and
    # confirmed by git itself: `git fetch --no-rec` errors "ambiguous option: no-rec (could be
    # --no-recurse-submodules or --no-recurse-submodules-default)", and the next word is its
    # value. pull and push reject it as unknown.
    HIDDEN = {"fetch": {"recurse-submodules-default": "required",
                        "no-recurse-submodules-default": "none"}}

    def test_the_tables_match_the_captured_help(self):
        guard = load_guard()
        self.assertEqual(sorted(guard.GIT_OPTIONS), sorted(guard.GIT_PATH_SUBS))
        for sub in sorted(guard.GIT_PATH_SUBS):
            with self.subTest(sub=sub):
                long, short = parse_git_help(slurp(os.path.join(GIT_HELP, f"{sub}.txt")))
                for name in self.HIDDEN.get(sub, {}):
                    self.assertNotIn(name, long)  # a hidden one `-h` lists isn't hidden
                self.assertEqual(guard.GIT_OPTIONS[sub],
                                 ({**long, **self.HIDDEN.get(sub, {})}, short))

    def test_the_captures_are_of_the_installed_git(self):
        # A git upgrade fails this until the captures are retaken (`git <sub> -h`, exit 129)
        # and the tables updated.
        version = subprocess.run(["git", "--version"], capture_output=True, text=True,
                                 check=True).stdout.strip()
        self.assertEqual(version, slurp(os.path.join(GIT_HELP, "VERSION")).strip())

    def test_git_argv_reads_options_values_and_positionals_as_git_does(self):
        argv = load_guard().git_argv
        cases = {
            ("push", "-o", "x", "origin", "main"): ["origin"],
            ("push", "-qox", "origin"): ["origin"],
            ("push", "--repo", "a", "b"): ["a", "b"],
            ("push", "--rep=a"): ["a"],
            ("push", "--force-with-lease", "origin"): ["origin"],
            ("push", "--recurse-submodules", "check", "origin"): ["origin"],
            ("fetch", "-j", "4", "origin"): ["origin"],
            ("fetch", "--multiple", "a", "b"): ["a", "b"],
            ("fetch", "-m", "--no-multiple", "a", "b"): ["a"],
            ("fetch", "--", "-x", "y"): ["-x"],
            ("fetch", "--end-of-options", "--all"): ["--all"],
            ("pull", "-j", "4", "origin"): ["4"],
            ("pull", "-r", "origin"): ["origin"],
            ("pull", "-S", "origin"): ["origin"],
            ("ls-remote", "-h", "origin", "main"): ["origin"],
            ("ls-remote", "--sort", "x", "origin"): ["origin"],
        }
        for (sub, *args), repos in cases.items():
            with self.subTest(args=args):
                self.assertEqual(argv(sub, args)[1], repos)
        options, repos, refspecs = argv("push", ["-vu", "--no-verify", "origin", "a", "b"])
        self.assertEqual((options, refspecs), ([("verbose", None), ("set-upstream", None),
                                                ("no-verify", None)], ["a", "b"]))


class SubmoduleRecursionMatchesGit(Guard):
    """The guard's effective-config verdict against real git: in a clone whose submodule's own
    config makes a fetch there run a marker program, recursion counts as off exactly when a
    plain `git fetch` leaves the marker unrun."""

    def submodule_clone(self):
        """(clone, fired, global config): a clone whose submodule's fetch runs a marker that
        appends to `fired`."""
        sub, up, clone = (os.path.join(self.tmp, n) for n in ("s", "u", "c"))
        allow = ("-c", "protocol.file.allow=always")
        self.git("init", "-q", sub, cwd=self.tmp)
        self.git("commit", "-q", "--allow-empty", "-m", "s", cwd=sub)
        self.git("init", "-q", up, cwd=self.tmp)
        self.git("commit", "-q", "--allow-empty", "-m", "u", cwd=up)
        self.git(*allow, "submodule", "add", "-q", sub, "sub", cwd=up)
        self.git("config", "-f", ".gitmodules", "submodule.sub.fetchRecurseSubmodules", "true",
                 cwd=up)
        self.git("commit", "-q", "-am", "sub", cwd=up)
        self.git(*allow, "clone", "-q", "--recurse-submodules", up, clone, cwd=self.tmp)
        fired = os.path.join(self.tmp, "fired")
        prog = self.write(os.path.join(self.tmp, "prog"),
                          f"#!/bin/sh\necho x >> {fired}\nexit 1\n", 0o755)
        self.git("config", "remote.origin.uploadpack", prog, cwd=os.path.join(clone, "sub"))
        return clone, fired, os.path.join(self.tmp, "g", "config")

    def test_a_command_line_recursion_flag_agrees_with_git(self):
        # With recursion off in the config, the last recursion flag on the command line decides:
        # git runs a fetch in the submodule (its upload-pack marker fires, and git says so)
        # exactly when the guard reads the flags as turning it on, and git refuses what
        # git_argv does.
        guard = load_guard()
        clone, fired, glob_cfg = self.submodule_clone()
        self.write(glob_cfg, "[protocol]\n\tallow = always\n" + RECURSE_OFF)
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": glob_cfg}
        calls = [("pull", "--rec"), ("pull", "--rec=yes"), ("pull", "--recurse-sub"),
                 ("pull", "--no-rec"), ("pull", "--rec", "--no-rec"), ("pull", "--no-rec", "--rec"),
                 ("pull", "--rec=no"), ("pull", "--recurse-submodules=on-demand"),
                 ("fetch", "--recurse-submodules"), ("fetch", "--recurse-submodules=yes"),
                 ("fetch", "--recurse-submodules=no"), ("fetch", "--no-recurse-submodules"),
                 ("fetch", "--rec"), ("fetch", "--no-rec"), ("fetch", "--recurse-sub"),
                 ("fetch", "--no-recurse-sub"), ("fetch", "--recurse-submodules-default=yes"),
                 ("fetch", "--recurse-submodules-default", "yes"),
                 ("fetch", "--no-recurse-submodules-default")]
        for sub, *args in calls:
            with self.subTest(call=(sub, *args)):
                p = subprocess.run(["git", "-C", clone, sub, *args], env=env,
                                   capture_output=True, text=True)
                ran = os.path.exists(fired)
                self.assertEqual(ran, "Fetching submodule sub" in p.stdout + p.stderr)
                try:
                    on = guard.recursion_cli(guard.git_argv(sub, args)[0]) == "on"
                except guard.Refusal:
                    self.assertEqual(p.returncode, 129, p.stderr)  # git refuses it too
                    continue
                if "on-demand" in args[-1] or "default=" in args[-1] or args[-1] == "yes":
                    # on-demand fetches only changed submodules (none here); the hidden default
                    # is refused outright, as the guard doesn't weigh it.
                    self.assertTrue(on)
                    continue
                self.assertEqual(on, ran, p.stderr[-400:])
                if os.path.exists(fired):
                    os.remove(fired)

    def test_the_guard_agrees_with_git(self):
        guard = load_guard()
        clone, fired, glob_cfg = self.submodule_clone()
        local = os.path.join(clone, ".git", "config")
        base_local = slurp(local)
        inc_off = self.write(os.path.join(self.tmp, "g", "off"), RECURSE_OFF)
        inc_on = self.write(os.path.join(self.tmp, "g", "on"), "[submodule]\n\trecurse\n")
        on = "[fetch]\n\trecurseSubmodules = true\n"
        sub_on = "[submodule]\n\trecurse = true\n"
        wt_ext = "[extensions]\n\tworktreeConfig = true\n"
        layouts = [  # (global, local, config.worktree, env)
            ("", "", "", {}), (RECURSE_OFF, "", "", {}), (RECURSE_OFF, on, "", {}),
            (RECURSE_OFF, sub_on, "", {}), (sub_on, RECURSE_OFF, "", {}),
            (f"[include]\n\tpath = {inc_off}\n", "", "", {}),
            (f"[include]\n\tpath = off\n{sub_on}", "", "", {}),
            (RECURSE_OFF, "", "", {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "submodule.recurse",
                                   "GIT_CONFIG_VALUE_0": "true"}),
            (on, "", "", {"GIT_CONFIG_PARAMETERS": "'fetch.recurseSubmodules=false'"}),
            ("", "", "", {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "fetch.recurseSubmodules",
                          "GIT_CONFIG_VALUE_0": "false",
                          "GIT_CONFIG_PARAMETERS": "'submodule.recurse'='true'"}),
            (on, wt_ext, RECURSE_OFF, {}), (on, "", RECURSE_OFF, {}),
            (f'{RECURSE_OFF}[includeIf "gitdir:{clone}/"]\n\tpath = {inc_on}\n', "", "", {}),
        ] + [(f"[fetch]\n\trecurseSubmodules = {v}\n", "", "", {})
             for v in ("no", "off", "0", "", "FALSE", "on-demand", "yes")]
        for glob_text, local_text, wt_text, extra in layouts:
            with self.subTest(glob=glob_text, local=local_text, wt=wt_text, env=extra):
                self.write(glob_cfg, "[protocol]\n\tallow = always\n" + glob_text)
                self.write(local, base_local + local_text)
                self.write(os.path.join(clone, ".git", "config.worktree"), wt_text)
                env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "GIT_CONFIG_NOSYSTEM": "1",
                       "GIT_CONFIG_GLOBAL": glob_cfg, **extra}
                subprocess.run(["git", "fetch", "-q"], cwd=clone, env=env, capture_output=True)
                ran = os.path.exists(fired)
                if ran:
                    os.remove(fired)
                on_now = guard.recursion_on(env, guard.discover(clone, env), self.home)
                if "on-demand" in glob_text:  # on-demand fetches only changed submodules
                    self.assertTrue(on_now)
                    continue
                self.assertEqual(bool(on_now), ran, on_now)

    def test_push_agrees_with_git(self):
        # A push of a commit that moves a submodule runs git in it (GIT_TRACE shows the
        # run_command with `cd sub`) exactly when the guard counts push recursion on.
        guard = load_guard()
        glob_cfg = os.path.join(self.tmp, "g", "config")
        self.write(glob_cfg, "[protocol]\n\tallow = always\n")
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": glob_cfg, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

        def run(*args, cwd, extra=None):
            return subprocess.run(["git", *args], cwd=cwd, env=dict(env, **(extra or {})),
                                  capture_output=True, text=True)
        sub, seed, clone = (os.path.join(self.tmp, n) for n in ("s", "seed", "c"))
        run("init", "-q", "-b", "main", "--bare", sub, cwd=self.tmp)
        run("init", "-q", seed, cwd=self.tmp)
        run("commit", "-q", "--allow-empty", "-m", "s", cwd=seed)
        run("push", "-q", sub, "HEAD:refs/heads/main", cwd=seed)
        run("init", "-q", clone, cwd=self.tmp)
        run("commit", "-q", "--allow-empty", "-m", "c", cwd=clone)
        self.assertEqual(run("submodule", "add", "-q", sub, "sub", cwd=clone).returncode, 0)
        run("commit", "-q", "-m", "add", cwd=clone)
        run("commit", "-q", "--allow-empty", "-m", "new", cwd=os.path.join(clone, "sub"))
        run("commit", "-q", "-am", "bump", cwd=clone)
        local = os.path.join(clone, ".git", "config")
        base_local = slurp(local)
        push, recurse = "[push]\n\trecurseSubmodules = {}\n", "[submodule]\n\trecurse = {}\n"
        layouts = [("", "")] + [(push.format(v), "") for v in (
            "check", "on-demand", "only", "no", "false", "0", "off", "", "NO")] + [
            (recurse.format(v), "") for v in ("true", "false", "yes", "1", "")] + [
            (recurse.format("true") + push.format("no"), ""),
            (push.format("no") + recurse.format("true"), ""),
            (push.format("check") + recurse.format("false"), ""),
            (recurse.format("false") + push.format("check"), ""),
            (push.format("no"), recurse.format("true")), (recurse.format("true"), push.format("no"))]
        for i, (glob_text, local_text) in enumerate(layouts):
            with self.subTest(glob=glob_text, local=local_text):
                self.write(glob_cfg, "[protocol]\n\tallow = always\n" + glob_text)
                self.write(local, base_local + local_text)
                bare = os.path.join(self.tmp, f"b{i}")
                run("init", "-q", "--bare", bare, cwd=self.tmp)
                p = run("push", bare, "HEAD:refs/heads/main", cwd=clone, extra={"GIT_TRACE": "1"})
                ran = any("run_command" in line and "cd sub" in line
                          for line in p.stderr.splitlines())
                on_now = guard.recursion_on(env, guard.discover(clone, env), self.home, "push")
                self.assertEqual(bool(on_now), ran, on_now)


class Rule2Path(Guard):
    def test_a_writable_dir_before_the_head_is_refused(self):
        self.env["PATH"] = f"{self.wbin}:{self.bin}:/usr/bin"
        self.denied("git push", "rule2", self.wbin)
        self.assertIn("deny rule2 " + self.wbin, self.log())

    def test_the_fix_says_where_to_rerun_setup_without_naming_a_lane(self):
        # A hint naming the holder goes stale once the lead's reinstall releases it (a rerun
        # from merged lane pass-timeout took the install back, 2026-10-15): it defers to
        # `lane ls` at rerun time.
        rerun = load_guard().RERUN
        self.assertIn("main checkout", rerun)
        self.assertIn("if `lane ls` shows an unmerged lane holding the install when you rerun",
                      rerun)
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.assertIn(rerun, self.denied("git push", "rule2", self.wbin))

    def test_a_writable_dir_after_the_head_is_refused(self):
        # The head's children (git hooks, gh's git, claude's tools) search the whole PATH.
        self.env["PATH"] = f"{self.bin}:/usr/bin:{self.wbin}"
        self.denied("git push", "rule2", self.wbin)

    def test_a_chmod_555_dir_outside_denywrite_is_refused(self):
        ro = self.make_bin("ro", protect=False)
        for name in (*os.listdir(ro), "."):
            os.chmod(os.path.join(ro, name), 0o555)  # its owner can chmod it back
        self.env["PATH"] = f"{ro}:/usr/bin"
        self.denied("git push", "rule2", ro)

    def test_a_system_dir_outside_every_root_passes(self):
        # git resolves in /usr/bin, which sits outside $HOME, /tmp and $TMPDIR.
        gbin = self.make_bin("gbin", heads=("gh",))
        self.write_settings()
        self.env["PATH"] = f"{gbin}:/usr/bin"
        self.allowed("git push")

    def test_path_and_denywrite_entries_with_trailing_slashes(self):
        tbin = self.make_bin("tbin", protect=False)
        self.protect(tbin + "/")
        self.env["PATH"] = f"{tbin}/:/usr/bin/"
        self.allowed("git push")
        self.env["PATH"] = f"{self.wbin}/:/usr/bin/"
        self.denied("git push", "rule2", self.wbin)

    def test_an_edit_deny_rule_protects_a_path_dir(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        reason = self.denied("lane ls", "rule2", self.wbin)
        self.assertIn(f"Edit(/{self.wbin}/**)", reason)
        self.deny_write.append(self.wbin)
        self.write_settings()
        self.allowed("lane ls")

    def test_a_denywrite_line_alone_protects_only_inside_dotclaude_s_checkouts(self):
        # A denyWrite line binds sandboxed Bash, not the Edit and Write tools.
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.sandbox_deny.append(self.wbin)
        self.write_settings()
        self.denied("git push", "rule2", self.wbin)
        dbin = os.path.join(self.home, "dotclaude", "bin")
        shutil.copytree(self.wbin, dbin)
        self.sandbox_deny.append(dbin)
        self.write_settings()
        self.env["PATH"] = f"{dbin}:/usr/bin"
        self.allowed("git push")

    def test_an_edit_rule_through_a_symlink_protects_nothing(self):
        # What a rule through a link binds wasn't probed, so the guard doesn't follow it.
        real = self.make_bin("realbin", protect=False)
        link = os.path.join(self.tmp, "linkbin")
        os.symlink(real, link)
        self.env["PATH"] = f"{real}:/usr/bin"
        self.protect(link)
        self.denied("git push", "rule2", real)
        self.protect(real)
        self.allowed("git push")

    def test_edit_deny_rule_forms(self):
        hbin = self.make_bin(os.path.join("home", "hbin"), protect=False)
        self.env["PATH"] = f"{hbin}:/usr/bin"
        for rules, ok in ((["Edit(~/hbin/**)"], True), ([f"Edit(/{hbin}/**)"], True),
                          ([f"Edit(/{hbin})", f"Edit(/{hbin}/git)"], False),
                          (["Edit(/hbin/**)"], False), ([f"Edit(/{self.home}/*/**)"], False),
                          ([f"Read(/{hbin}/**)"], False)):
            with self.subTest(rules=rules):
                self.write(os.path.join(self.home, ".claude", "settings.json"), json.dumps(
                    {"sandbox": {"excludedCommands": EXCLUDED},
                     "permissions": {"deny": rules}}))
                if ok:
                    self.allowed("git push")
                else:
                    self.denied("git push", "rule2", hbin)

    def test_an_empty_or_relative_entry_is_refused(self):
        for path in (f":{self.bin}:/usr/bin", f"/nonexistent::{self.bin}:/usr/bin",
                     f"bin:{self.bin}:/usr/bin"):
            with self.subTest(path=path):
                self.env["PATH"] = path
                self.denied("git push", "rule2")

    def test_a_symlink_into_a_writable_dir_is_refused(self):
        target = self.write(os.path.join(self.tmp, "wtarget", "real-git"), MARKER, 0o755)
        links = self.protect(self.mkdir("links"))
        os.symlink(target, os.path.join(links, "git"))
        self.env["PATH"] = f"{links}:/usr/bin"
        self.denied("git push", "rule2", os.path.dirname(target))

    def test_a_path_dir_reached_through_a_symlink_in_a_protected_dir_is_judged_where_it_lands(self):
        links = self.protect(self.mkdir("links"))
        os.symlink(self.wbin, os.path.join(links, "wbin"))
        self.env["PATH"] = f"{links}/wbin:/usr/bin"
        self.denied("git push", "rule2", self.wbin)
        os.remove(os.path.join(self.wbin, "gh"))  # the link's target is judged even without the head
        self.denied("gh pr view 5", "rule2", self.wbin)

    def test_an_env_shebang_interpreter_resolving_into_a_writable_dir_is_refused(self):
        sbin = self.protect(self.mkdir("sbin"))
        self.write(os.path.join(sbin, "lane"), "#!/usr/bin/env fakeinterp\n", 0o755)
        interp = self.write(os.path.join(self.tmp, "winterp", "fakeinterp"), MARKER, 0o755)
        os.symlink(interp, os.path.join(sbin, "fakeinterp"))
        self.env["PATH"] = f"{sbin}:/usr/bin"
        self.denied("lane ls", "rule2", os.path.dirname(interp))
        # The same interpreter in a protected dir passes.
        self.protect(os.path.dirname(interp))
        self.allowed("lane ls")

    def test_a_direct_shebang_interpreter_in_a_writable_dir_is_refused(self):
        interp = self.write(os.path.join(self.tmp, "winterp", "fakeinterp"), MARKER, 0o755)
        sbin = self.protect(self.mkdir("sbin"))
        self.write(os.path.join(sbin, "lane"), f"#!{interp} -x\n", 0o755)
        self.env["PATH"] = f"{sbin}:/usr/bin"
        self.denied("lane ls", "rule2", os.path.dirname(interp))
        self.protect(os.path.dirname(interp))
        self.allowed("lane ls")

    def test_a_symlinked_home_counts_only_real_path_rules(self):
        # Claude Code may expand `~` to the link, and a rule through a link wasn't probed.
        links = self.protect(self.mkdir("homelinks"))  # the link itself must be protected
        link = os.path.join(links, "home")
        os.symlink(self.home, link)
        hbin = self.make_bin(os.path.join("home", "bin"), protect=False)
        self.protect("~/bin")
        self.write(os.path.join(self.home, ".gitconfig"), "[user]\n\tname = x\n")
        self.env["HOME"] = link
        self.env["PATH"] = f"{hbin}:/usr/bin"
        reason = self.denied("git push", "rule2", hbin)
        self.assertIn(f"Edit(/{hbin}/**)", reason)
        self.protect(hbin)
        self.allowed("git push")
        self.env["PATH"] = f"{link}/bin:/usr/bin"
        self.allowed("git push")
        self.make_bin(os.path.join("home", "wbin"), protect=False)
        self.env["PATH"] = f"{link}/wbin:/usr/bin"
        self.denied("git push", "rule2", f"{link}/wbin")

    def test_the_offered_home_rule_clears_the_refusal(self):
        hbin = self.make_bin(os.path.join("home", "hbin"), protect=False)
        self.env["PATH"] = f"{hbin}:/usr/bin"
        self.assertIn("Edit(~/hbin/**)", self.denied("git push", "rule2", hbin))
        self.protect("~/hbin")
        self.allowed("git push")

    def test_a_home_rule_under_a_root_home_is_its_plain_path(self):
        guard = load_guard()
        self.assertEqual(guard.edit_rule_path("Edit(~/opt/x/**)", "/"), "/opt/x")
        self.assertEqual(guard.edit_rule_path("Edit(~/opt/x/**)", "/h"), "/h/opt/x")
        self.assertEqual(guard.edit_rule_path("Edit(//opt/x/**)", "/h"), "/opt/x")

    def test_a_missing_path_entry_under_a_writable_root_is_refused(self):
        missing = os.path.join(self.tmp, "nobin", "bin")
        self.env["PATH"] = f"{missing}:{self.bin}:/usr/bin"
        self.denied("git push", "rule2", missing)

    def test_a_missing_path_entry_under_a_symlink_is_judged_at_the_target(self):
        # The link sits in a denyWrite dir, but the missing dir would be made in its target.
        links = self.protect(self.mkdir("links"))
        os.symlink(self.mkdir("wtarget"), os.path.join(links, "w"))
        missing = os.path.join(links, "w", "bin")
        self.env["PATH"] = f"{missing}:{self.bin}:/usr/bin"
        self.denied("git push", "rule2", missing)

    def test_a_symlink_loop_on_path_is_refused(self):
        loop = self.protect(self.mkdir("loop"))
        os.symlink("b", os.path.join(loop, "a"))
        os.symlink("a", os.path.join(loop, "b"))
        self.env["PATH"] = f"{loop}/a:{self.bin}:/usr/bin"
        self.assertIn("symlink loop", self.denied("git push", "rule2"))

    def test_a_shebang_chain_deeper_than_3_is_refused(self):
        sbin = self.protect(self.mkdir("sbin"))
        # lane runs i1, i1 runs i2, and i2 (MARKER) runs /bin/sh: three interpreters.
        self.write(os.path.join(sbin, "i2"), MARKER, 0o755)
        for name, interp in (("i1", "i2"), ("lane", "i1")):
            self.write(os.path.join(sbin, name), f"#!{sbin}/{interp}\n", 0o755)
        self.env["PATH"] = f"{sbin}:/usr/bin"
        self.allowed("lane ls")
        self.write(os.path.join(sbin, "i3"), MARKER, 0o755)
        self.write(os.path.join(sbin, "i2"), f"#!{sbin}/i3\n", 0o755)
        self.assertIn("more than 3 interpreters", self.denied("lane ls", "rule2"))

    def test_a_head_not_on_path_passes(self):
        self.env["PATH"] = "/usr/bin:/bin"
        self.allowed("lane ls")

    def test_a_head_with_a_slash_is_checked_where_it_points(self):
        self.write_settings({"excludedCommands": EXCLUDED + [f"{self.wbin}/git push"]})
        self.denied(f"{self.wbin}/git push", "rule2", self.wbin)


class Rule3ProjectRoot(Guard):
    def test_claude_runs_only_from_the_project_root(self):
        self.allowed("claude --version")
        sub = self.protect(self.mkdir("proj", "sub"))  # else rule 1 refuses it first
        self.denied("claude --version", "rule3", sub, cwd=sub)

    def test_codex_runs_only_from_the_project_root(self):
        self.allowed("codex login status")
        sub = self.protect(self.mkdir("proj", "sub"))
        self.denied("codex login status", "rule3", sub, cwd=sub)

    def test_git_from_a_subdir_is_not_held_to_rule_3(self):
        self.allowed("git push", cwd=self.protect(self.mkdir("proj", "sub")))


class Matching(Guard):
    def everything_writable(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        nested = self.mkdir("nested")
        self.git("init", "-q", nested, cwd=self.tmp)
        return nested

    def test_a_non_candidate_passes_silently_even_when_everything_is_writable(self):
        cwd = self.everything_writable()
        for command in ("ls", "git status", "gh repo view", "echo lane ls"):
            with self.subTest(command=command):
                self.allowed(command, cwd=cwd)
                self.assertEqual(self.last_stdout, "")
        self.assertEqual(self.log(), "")

    def test_a_compound_with_an_excluded_piece_is_a_candidate(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        for command in ("echo x && git push", "echo x; git push origin main", "ls | gh pr view",
                        "echo x\nFOO=1 git push", "(git push)", "true || lane ls -a"):
            with self.subTest(command=command):
                self.denied(command, "rule2", self.wbin)
        self.allowed("echo x && ls")

    def test_a_star_spans_spaces_and_the_rest_is_literal(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.denied("gh pr view 5 --json title", "rule2")
        self.denied("claude -p 'a b c'", "rule2")
        self.allowed("gh prx view")
        self.allowed("git pushy")

    def test_patterns_from_managed_and_project_settings_count(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.write(os.path.join(self.tmp, "managed", "managed-settings.d", "a.json"),
                   json.dumps({"sandbox": {"excludedCommands": ["gh run *"]}}))
        self.write(os.path.join(self.proj, ".claude", "settings.local.json"),
                   json.dumps({"sandbox": {"excludedCommands": ["gh api *"]}}))
        self.denied("gh run list", "rule2")
        self.denied("gh api user", "rule2")
        self.allowed("gh issue list")

    def test_edit_deny_rules_count_only_from_user_and_managed_settings(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        local = {"permissions": {"deny": [f"Edit(/{self.wbin}/**)"]}}
        self.write(os.path.join(self.proj, ".claude", "settings.local.json"), json.dumps(local))
        self.write(os.path.join(self.proj, ".claude", "settings.json"), json.dumps(local))
        self.denied("git push", "rule2", self.wbin)
        self.write(os.path.join(self.tmp, "managed", "managed-settings.json"), json.dumps(local))
        self.allowed("git push")

    def test_an_unreadable_settings_file_makes_the_call_a_candidate(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.write(os.path.join(self.proj, ".claude", "settings.json"), "{not json")
        self.denied("gh issue list", "rule2")

    def test_a_settings_file_too_deep_for_json_makes_the_call_a_candidate(self):
        # "[" * 100000: RecursionError in json, not ValueError. It takes the unread-settings
        # path a "{not json" file takes, not the match-error fallback.
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.write(os.path.join(self.proj, ".claude", "settings.json"), "[" * 100000)
        self.denied("gh issue list", "rule2")
        self.assertIn("unread settings", self.log())
        self.assertIn("RecursionError", self.log())
        self.assertNotIn("match error", self.log())

    def test_an_empty_settings_file_is_no_settings(self):
        # The sandbox's mount points for protected files it lacks can stay behind on disk as
        # empty files; Claude Code reads one as no settings, so it can't hold a pattern.
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        for text in ("", " \n"):
            with self.subTest(text=text):
                self.write(os.path.join(self.proj, ".claude", "settings.json"), text)
                self.allowed("gh issue list")
                self.denied("gh pr view", "rule2", self.wbin)


class Scan(Guard):
    """`--scan`: what the guard would refuse from each repo's root, before a call hits it."""

    def scan(self, *roots):
        p = subprocess.run(["python3", "-I", MODULE, "--scan", *roots], capture_output=True,
                           text=True, env=self.env, timeout=60)
        return p.returncode, p.stdout

    def test_a_clean_machine_scans_clean(self):
        self.assertEqual(self.scan(self.tmp), (0, ""))

    def test_an_in_repo_hooks_path_is_listed_with_what_it_holds_and_its_rule(self):
        hooks = os.path.dirname(self.write(os.path.join(self.proj, ".githooks", "pre-push"),
                                           MARKER, 0o755))
        self.git("config", "core.hooksPath", ".githooks", cwd=self.proj)
        code, out = self.scan(self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn(f"{self.proj}: excluded-guard (rule1)", out)
        self.assertRegex(out, r"\n    \d{4}-\d\d-\d\d \d\d:\d\d  pre-push  not in HEAD\n")
        # The paste-ready settings.machine.json carries each rule once.
        self.assertEqual(out.count(f'"Edit(/{hooks}/**)"'), 1, out)
        # A relative hooksPath resolves in each worktree, so the lane's own dir is listed too.
        lane_hooks = os.path.join(self.lane, ".githooks")
        self.assertIn(f'"Edit(/{lane_hooks}/**)"', out)
        self.assertIn(f"{lane_hooks} holds, before you protect it:\n    (missing", out)
        self.protect(hooks)
        self.protect(lane_hooks)
        self.assertEqual(self.scan(self.tmp), (0, ""))

    def test_a_writable_path_dir_is_listed_once(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        code, out = self.scan(self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("PATH: excluded-guard (rule2)", out)
        self.assertEqual(out.count(f'"Edit(/{self.wbin}/**)"'), 1, out)
        self.assertIn(f"{self.wbin} holds, before you protect it:\n", out)
        # The last line, where setup.sh's warning points.
        self.assertTrue(out.endswith(f"\nThen {load_guard().RERUN}.\n"), out)

    def test_a_finding_with_no_rule_still_ends_with_where_to_rerun(self):
        # $HOME itself can't take an Edit deny rule (it would cover the whole home).
        self.env["PATH"] = f"{self.home}:/usr/bin"
        code, out = self.scan(self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("PATH: excluded-guard (rule2)", out)
        self.assertNotIn("with the rules added", out)
        self.assertTrue(out.endswith(f"\nThen {load_guard().RERUN}.\n"), out)

    def test_a_rule_it_cant_paste_still_ends_with_where_to_rerun(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        rerun = f"\nThen {load_guard().RERUN}.\n"
        machine = os.path.join(self.home, ".claude", "settings.machine.json")
        for text, says in (("{not json", "not read (JSONDecodeError)"),
                           ('{"permissions": {"deny": "x"}}', "has no usable permissions.deny")):
            with self.subTest(says):
                self.write(machine, text)
                code, out = self.scan(self.tmp)
                self.assertEqual(code, 1, out)
                self.assertIn(says, out)
                self.assertIn(f'  "Edit(/{self.wbin}/**)",\n', out)
                self.assertTrue(out.endswith(rerun), out)

    def test_the_paste_block_keeps_the_machine_overlay(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.write(os.path.join(self.home, ".claude", "settings.machine.json"),
                   json.dumps({"effortLevel": "high", "permissions": {"deny": ["Edit(~/x/**)"]}}))
        code, out = self.scan(self.tmp)
        block, _ = json.JSONDecoder().raw_decode(out[out.index("\n{\n") + 1:])
        self.assertEqual(block["effortLevel"], "high")
        self.assertEqual(block["permissions"]["deny"], ["Edit(~/x/**)", f"Edit(/{self.wbin}/**)"])

    def test_a_partial_clone_s_lazy_fetch_runs_nothing(self):
        # ls-tree in a partial clone fetches a missing object through the repo's own transport.
        marker = os.path.join(self.tmp, "ran")
        self.write(os.path.join(self.proj, "sub", "f"), "x")
        self.git("add", ".", cwd=self.proj)
        self.git("commit", "-qm", "sub", cwd=self.proj)
        tree = self.git("rev-parse", "HEAD:sub", cwd=self.proj).strip()
        os.remove(os.path.join(self.proj, ".git", "objects", tree[:2], tree[2:]))
        for k, v in (("core.repositoryformatversion", "1"), ("extensions.partialClone", "origin"),
                     ("remote.origin.url", f"ext::sh -c touch% {marker}"),
                     ("remote.origin.promisor", "true"), ("protocol.ext.allow", "always"),
                     ("core.hooksPath", "sub")):
            self.git("config", k, v, cwd=self.proj)
        self.assertEqual(self.scan(self.tmp)[0], 1)
        self.assertFalse(os.path.exists(marker))
        # A remote helper the config names (git-remote-<vcs> on PATH) fetches the same way.
        helper = self.write(os.path.join(self.mkdir("helpers"), "git-remote-x"),
                            f"#!/bin/sh\ntouch {marker}\n", 0o755)
        self.git("config", "remote.origin.vcs", "x", cwd=self.proj)
        self.git("config", "remote.origin.url", "x://y", cwd=self.proj)
        self.env["PATH"] = f"{os.path.dirname(helper)}:{self.env['PATH']}"
        self.assertEqual(self.scan(self.tmp)[0], 1)
        self.assertFalse(os.path.exists(marker))

    def test_a_repo_it_cannot_check_is_reported_and_the_scan_goes_on(self):
        odd = self.mkdir("odd")
        self.write(os.path.join(odd, ".git"), "")
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        code, out = self.scan(self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn(f"{odd}: could not check", out)
        self.assertIn(f'"Edit(/{self.wbin}/**)"', out)

    def test_every_writable_path_dir_is_listed_in_one_run(self):
        w2 = self.make_bin("wbin2", protect=False)
        self.env["PATH"] = f"{self.wbin}:{w2}:/usr/bin"
        out = self.scan(self.tmp)[1]
        for d in (self.wbin, w2):
            self.assertIn(f'"Edit(/{d}/**)"', out)

    def test_an_interpreter_found_in_another_path_entry_is_judged(self):
        # codex's `#!/usr/bin/env node` finds node in a second, protected entry whose node
        # links to a writable target: the hook refuses, so the scan must list it too.
        e1 = self.make_bin("e1", heads=())
        self.write(os.path.join(e1, "codex"), "#!/usr/bin/env node\n", 0o755)
        e2 = self.make_bin("e2", heads=())
        target = self.write(os.path.join(self.mkdir("wnode"), "node"), MARKER, 0o755)
        os.symlink(target, os.path.join(e2, "node"))
        self.write_settings()
        self.env["PATH"] = f"{e1}:{e2}:/usr/bin"
        code, out = self.scan(self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn(os.path.dirname(target), out)

    def test_an_earlier_refusal_does_not_hide_a_later_one(self):
        # The full PATH stops at its first refusal, here an empty entry and then a writable one;
        # the node target past them must still be listed in the same run.
        e1 = self.make_bin("e1", heads=())
        self.write(os.path.join(e1, "codex"), "#!/usr/bin/env node\n", 0o755)
        e2 = self.make_bin("e2", heads=())
        target = self.write(os.path.join(self.mkdir("wnode"), "node"), MARKER, 0o755)
        os.symlink(target, os.path.join(e2, "node"))
        self.write_settings()
        self.env["PATH"] = f":{e1}:{e2}:{self.wbin}:/usr/bin"
        code, out = self.scan(self.tmp)
        self.assertEqual(code, 1, out)
        for d in (self.wbin, os.path.dirname(target)):
            self.assertIn(f'"Edit(/{d}/**)"', out)

    def test_every_head_in_one_entry_is_judged(self):
        e = self.make_bin("e", heads=())
        for head in ("git", "gh"):
            target = self.write(os.path.join(self.mkdir(f"w{head}"), head), MARKER, 0o755)
            os.symlink(target, os.path.join(e, head))
        self.write_settings()
        self.env["PATH"] = f"{e}:/usr/bin"
        out = self.scan(self.tmp)[1]
        for head in ("git", "gh"):
            self.assertIn(f'"Edit(/{os.path.join(self.tmp, "w" + head)}/**)"', out)

    def test_the_listing_is_the_dir_the_rule_covers(self):
        # A writable include file: the rule covers its dir, so the listing shows that dir.
        d = self.mkdir("cfg")
        inc = self.write(os.path.join(d, "inc.cfg"), "")
        self.write(os.path.join(d, "other"), "")
        self.write(os.path.join(self.home, ".gitconfig"), f"[include]\n\tpath = {inc}\n")
        out = self.scan(self.tmp)[1]
        self.assertIn(f"  {d} holds, before you protect it:", out)
        self.assertRegex(out, r"  other( +not in HEAD)?\n")  # under a stray ancestor repo too

    def test_no_rule_is_offered_for_a_write_root_itself(self):
        inc = self.write(os.path.join(self.home, ".gitconfig.local"), "")
        self.write(os.path.join(self.home, ".gitconfig"), f"[include]\n\tpath = {inc}\n")
        code, out = self.scan(self.tmp)
        self.assertEqual(code, 1, out)
        self.assertIn("Move it into a dir", out)
        self.assertNotIn(f"Edit(/{self.home}", out)
        self.assertNotIn("Edit(~/**)", out)

    def test_evidence_reads_odd_names_and_tracked_subdirs(self):
        hooks = os.path.join(self.proj, ".githooks")
        self.write(os.path.join(hooks, "pre push é"), MARKER, 0o755)
        self.write(os.path.join(hooks, "lib", "x"), "x")
        self.git("add", ".", cwd=self.proj)
        self.git("commit", "-qm", "hooks", cwd=self.proj)
        self.git("config", "core.hooksPath", ".githooks", cwd=self.proj)
        out = self.scan(self.tmp)[1]
        self.assertIn("pre push é  same as HEAD", out)
        self.assertRegex(out, r"  lib/\n")

    def test_evidence_runs_no_program_a_repo_config_names(self):
        # The scan runs outside the sandbox; a repo's fsmonitor or diff driver must not run.
        marker = os.path.join(self.tmp, "ran")
        hooks = os.path.join(self.proj, ".githooks")
        self.write(os.path.join(hooks, "pre-push"), MARKER, 0o755)
        self.git("config", "core.hooksPath", ".githooks", cwd=self.proj)
        self.git("config", "core.fsmonitor", f"touch {marker}; false", cwd=self.proj)
        self.git("config", "diff.external", f"touch {marker}", cwd=self.proj)
        self.assertEqual(self.scan(self.tmp)[0], 1)
        self.assertFalse(os.path.exists(marker))

    def test_hidden_dirs_and_node_modules_are_not_walked(self):
        for d in (".hidden", "node_modules"):
            repo = os.path.join(self.tmp, d, "r")
            self.git("init", "-q", repo, cwd=self.tmp)
            os.makedirs(os.path.join(repo, "h"))
            self.git("config", "core.hooksPath", "h", cwd=repo)
        self.assertEqual(self.scan(self.tmp), (0, ""))


class EveryRefusal(Guard):
    """One run lists every rule a dir needs, not only the first refusal."""

    def test_every_rule1_refusal_in_a_repo_is_listed_in_one_run(self):
        inc = self.write(os.path.join(self.mkdir("wcfg"), "inc"), "[user]\n\tname = x\n")
        self.git("config", "include.path", inc, cwd=self.proj)
        self.git("config", "core.hooksPath", ".githooks", cwd=self.proj)
        code, out = Scan.scan(self, self.proj)
        self.assertEqual(code, 1, out)
        for d in (os.path.dirname(inc), os.path.join(self.proj, ".githooks")):
            self.assertIn(f'"Edit(/{d}/**)"', out)

    def test_project_refusals_lists_them_all_and_stops_at_one_it_cannot_clear(self):
        guard = load_guard()
        inc = self.write(os.path.join(self.mkdir("wcfg"), "inc"), "")
        self.git("config", "include.path", inc, cwd=self.lane)
        self.git("config", "core.hooksPath", ".githooks", cwd=self.lane)
        refusals, error = guard.project_refusals(self.env, self.lane)
        self.assertIsNone(error)
        self.assertCountEqual([r.fix_dir for r in refusals],
                              [os.path.dirname(inc), os.path.join(self.lane, ".githooks")])
        # A refusal with no rule to offer (a nested repo) ends the list.
        nested = os.path.join(self.proj, "sub")
        self.git("init", "-q", nested, cwd=self.proj)
        refusals, error = guard.project_refusals(dict(self.env, CLAUDE_PROJECT_DIR=self.proj),
                                                 nested, project=self.proj)
        self.assertEqual([r.rule for r in refusals], ["rule1"])
        self.assertIsNone(refusals[0].fix)


class Memo(Guard):
    """A Machine's memo holds what a fresh Machine with the same deny list would find."""

    def test_a_protected_machine_agrees_with_a_fresh_one(self):
        # A home reached through a link (outside every root), and a PATH entry in it that links
        # to a protected dir: the entry's rule names the real dir holding the link, which
        # neither the entry's path nor its target sits under. The later writable entry must
        # still be listed. Roots are just the home here: the temp dir sits under /tmp.
        guard = load_guard()
        os.symlink(self.home, os.path.join(self.tmp, "homelink"))
        self.mkdir("home", ".local")
        os.symlink(self.bin, os.path.join(self.home, ".local", "bin"))
        entry = os.path.join(self.tmp, "homelink", ".local", "bin")
        wbin = self.make_bin(os.path.join("home", "wbin"), protect=False)
        path_var = f"{entry}:{wbin}:/usr/bin"
        settings, _ = guard.load_settings(self.env)

        def machine():
            m = guard.Machine(self.env, settings, self.proj)
            m.roots = [self.home]
            return m

        m = machine()
        refusals, errors = guard.path_refusals(m, ["git", "gh"], path_var)
        self.assertEqual(errors, [])
        self.assertEqual([r.fix_dir for r in refusals],
                         [os.path.join(self.home, ".local"), wbin])
        fresh = machine()
        fresh.deny += m.deny[len(fresh.deny):]
        for p in (entry, wbin, os.path.join(wbin, "git"), self.bin):
            with self.subTest(path=p):
                self.assertEqual(m.exposed(p), fresh.exposed(p))


class RulesNaming(Guard):
    """rules_naming: the Edit deny rules a removed dir (a closed lane's worktree) leaves behind."""

    def test_rules_inside_the_dir_in_any_form_and_only_those(self):
        guard = load_guard()
        lane = self.mkdir("home", "lanes", "chart-fix")
        inside = ["Edit(~/lanes/chart-fix/.githooks/**)", f"Edit(/{lane}/tools/*.sh)",
                  f"Edit(/{lane})", "Edit(~/lanes/chart-fix/[ab]/**)"]
        # A glob mid-name widens to the parent: it covers sibling lanes too, so it stays.
        outside = ["Edit(~/lanes/**)", "Edit(~/lanes/chart-fix2/**)", "Read(~/lanes/chart-fix/**)",
                   "Edit(~/lanes/*/x/**)", "Edit(~/lanes/chart-fix*/**)",
                   "Edit(~/lanes/chart-fix[0-9]/**)", "Edit(~/la*/chart-fix/**)", 7]
        machine = self.write(os.path.join(self.home, ".claude", "settings.machine.json"),
                             json.dumps({"permissions": {"deny": inside[:2] + outside}}))
        managed = self.write(os.path.join(self.tmp, "managed", "managed-settings.d", "a.json"),
                             json.dumps({"permissions": {"deny": inside[2:]}}))
        self.assertEqual(guard.rules_naming(lane, self.env),
                         [(machine, r) for r in inside[:2]] + [(managed, r) for r in inside[2:]])

    def test_an_unreadable_or_odd_settings_file_is_skipped(self):
        guard = load_guard()
        lane = self.mkdir("home", "lanes", "chart-fix")
        self.mkdir("home", ".claude", "settings.machine.json")  # a dir: unreadable
        self.write(os.path.join(self.home, ".claude", "settings.json"),
                   json.dumps({"permissions": {"deny": "Edit(~/lanes/chart-fix/**)"}}))
        self.assertEqual(guard.rules_naming(lane, self.env), [])

    def test_a_settings_file_too_deep_for_json_is_skipped(self):
        guard = load_guard()
        lane = self.mkdir("home", "lanes", "chart-fix")
        rule = "Edit(~/lanes/chart-fix/**)"
        self.write(os.path.join(self.home, ".claude", "settings.machine.json"),
                   "[" * 100000)   # RecursionError in json, not ValueError
        user = self.write(os.path.join(self.home, ".claude", "settings.json"),
                          json.dumps({"permissions": {"deny": [rule]}}))
        self.assertEqual(guard.rules_naming(lane, self.env), [(user, rule)])

    def test_a_machine_file_too_deep_for_json_gets_the_rules_by_hand(self):
        guard = load_guard()
        machine = self.write(os.path.join(self.home, ".claude", "settings.machine.json"),
                             "[" * 100000)   # RecursionError in json, not ValueError
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            guard.print_paste(machine, ["Edit(~/lanes/x/**)"])
        self.assertIn("not read (RecursionError); add these", out.getvalue())
        self.assertIn('"Edit(~/lanes/x/**)",', out.getvalue())


class Session(Guard):
    """`--session`, the SessionStart check: what an excluded call from this session's project
    would meet, shown once per change in its findings, failing open."""

    def start(self, project=None, raw=None, hook=SESSION_HOOK, **payload):
        project = project or self.proj
        event = {"session_id": "s1", "hook_event_name": "SessionStart", "source": "startup",
                 "cwd": project, **payload}
        env = dict(self.env, CLAUDE_PROJECT_DIR=project)
        p = subprocess.run(["bash", hook], input=raw if raw is not None else json.dumps(event),
                           capture_output=True, text=True, env=env, timeout=20, cwd=project)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout) if p.stdout.strip() else None

    def test_a_clean_session_says_nothing(self):
        self.assertIsNone(self.start())
        self.assertIsNone(self.start(self.lane))

    def test_a_finding_shows_once_and_again_when_it_changes(self):
        hooks = os.path.join(self.proj, ".githooks")
        self.git("config", "core.hooksPath", ".githooks", cwd=self.proj)
        out = self.start()
        msg = out["systemMessage"]
        self.assertIn(f"Edit(/{hooks}/**)", msg)
        self.assertIn("--scan", msg)
        self.assertIn("settings.machine.json", msg)
        context = out["hookSpecificOutput"]
        self.assertEqual(context["hookEventName"], "SessionStart")
        self.assertIn("excluded-guard", context["additionalContext"])
        self.assertIn(hooks, context["additionalContext"])
        self.assertIsNone(self.start(), "the same findings showed twice")
        inc = self.write(os.path.join(self.mkdir("wcfg"), "inc"), "")
        self.git("config", "include.path", inc, cwd=self.proj)
        msg = self.start()["systemMessage"]
        for d in (hooks, os.path.dirname(inc)):
            self.assertIn(f"Edit(/{d}/**)", msg)
        self.protect(hooks)
        self.protect(os.path.dirname(inc))
        self.assertIsNone(self.start())  # cleared: nothing to say
        self.deny_write.remove(hooks)
        self.write_settings()
        self.assertIn(f"Edit(/{hooks}/**)", self.start()["systemMessage"])

    def test_a_path_finding_shows_once_across_projects(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        msg = self.start()["systemMessage"]
        self.assertIn(f"Edit(/{self.wbin}/**)", msg)
        self.assertIn(load_guard().RERUN, msg)
        self.assertIsNone(self.start(self.lane))

    def test_each_lane_shows_its_own_hooks_dir(self):
        self.git("config", "core.hooksPath", ".githooks", cwd=self.proj)
        self.assertIn(os.path.join(self.proj, ".githooks"), self.start()["systemMessage"])
        msg = self.start(self.lane)["systemMessage"]
        self.assertIn(f"Edit(/{os.path.join(self.lane, '.githooks')}/**)", msg)
        self.assertNotIn(os.path.join(self.proj, ".githooks"), msg)

    def test_unattended_and_subagent_starts_say_nothing_and_keep_the_once(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.assertIsNone(self.start(agent_id="a1"))
        self.env["CLAUDE_CODE_SESSION_ATTENDED"] = "0"
        self.assertIsNone(self.start())
        del self.env["CLAUDE_CODE_SESSION_ATTENDED"]
        self.assertIsNotNone(self.start())

    def test_an_unreadable_project_settings_file_is_no_finding(self):
        # The guard then judges more calls as candidates; it refuses none for that alone.
        self.mkdir("proj", ".claude", "settings.json")
        self.assertIsNone(self.start())

    def test_an_unreadable_user_settings_file_is_named(self):
        # It takes its deny rules with it, so the guard may refuse what they would clear.
        self.write(os.path.join(self.home, ".claude", "settings.json"), "{not json")
        self.assertIn("settings not read", self.start()["systemMessage"])

    def test_each_path_shows_once_however_tabs_alternate(self):
        w2 = self.make_bin("wbin2", protect=False)
        for path, shows in ((self.wbin, True), (w2, True), (self.wbin, False), (w2, False)):
            with self.subTest(path=path):
                self.env["PATH"] = f"{path}:/usr/bin"
                out = self.start()
                self.assertEqual(out is not None, shows, out)

    def test_what_a_projects_own_settings_add_is_its_own(self):
        # A head only proj's settings exclude runs through a writable interpreter: proj shows
        # it, the lane doesn't, and alternating starts show nothing again.
        interp = self.write(os.path.join(self.mkdir("wint"), "interp"), MARKER, 0o755)
        self.write(os.path.join(self.bin, "mytool"), f"#!{interp}\n", 0o755)
        self.write(os.path.join(self.proj, ".claude", "settings.json"),
                   json.dumps({"sandbox": {"excludedCommands": ["mytool *"]}}))
        self.assertIn(os.path.dirname(interp), self.start()["systemMessage"])
        for project in (self.lane, self.proj, self.lane):
            with self.subTest(project=project):
                self.assertIsNone(self.start(project))

    def test_a_projects_own_path_finding_is_keyed_by_path_too(self):
        # A head only proj's settings exclude sits in a dir on one tab's PATH and runs through a
        # writable interpreter: alternating tabs with and without that dir show it once.
        tools = self.make_bin("tools", heads=())
        interp = self.write(os.path.join(self.mkdir("wint"), "interp"), MARKER, 0o755)
        self.write(os.path.join(tools, "mytool"), f"#!{interp}\n", 0o755)
        self.write_settings()
        self.write(os.path.join(self.proj, ".claude", "settings.json"),
                   json.dumps({"sandbox": {"excludedCommands": ["mytool *"]}}))
        with_it, without = f"{self.bin}:{tools}:/usr/bin", f"{self.bin}:/usr/bin"
        for path, shows in ((with_it, True), (without, False), (with_it, False)):
            with self.subTest(path=path):
                self.env["PATH"] = path
                out = self.start()
                self.assertEqual(out is not None, shows, out)

    def test_old_path_keys_go_and_a_reused_one_stays(self):
        guard = load_guard()
        state = os.path.join(self.tmp, "state")
        with mock.patch.dict(os.environ, XDG_STATE_HOME=state):
            for i in range(guard.MACHINE_KEYS + 2):
                guard.unseen({f"{guard.MACHINE_KEY}:{i}": [f"line {i}"]})
                if i == 3:
                    guard.unseen({f"{guard.MACHINE_KEY}:0": ["line 0"]})  # back to tab 0
        with open(os.path.join(state, "dotclaude", "excluded-check.json")) as f:
            kept = list(json.load(f))
        self.assertEqual(len(kept), guard.MACHINE_KEYS)
        self.assertIn(f"{guard.MACHINE_KEY}:0", kept)
        self.assertNotIn(f"{guard.MACHINE_KEY}:1", kept)

    def test_links_where_the_state_goes_are_never_followed(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        d = self.mkdir("state", "dotclaude")
        state, lock = (self.write(os.path.join(self.tmp, n), "{}") for n in ("st", "lk"))
        os.symlink(state, os.path.join(d, "excluded-check.json"))
        os.symlink(lock, os.path.join(d, "excluded-check.json.lock"))
        self.assertIsNotNone(self.start())
        self.assertEqual((slurp(state), slurp(lock)), ("{}", "{}"))
        # The link itself is replaced by the new state, never written through.
        self.assertFalse(os.path.islink(os.path.join(d, "excluded-check.json")))

    def test_a_planted_temp_name_is_never_written_through(self):
        guard = load_guard()
        d = self.mkdir("state", "dotclaude")
        target = self.write(os.path.join(self.tmp, "target"), "keep")
        os.symlink(target, os.path.join(d, f"excluded-check.json.{os.getpid()}.tmp"))
        with mock.patch.dict(os.environ, XDG_STATE_HOME=os.path.join(self.tmp, "state")):
            self.assertEqual(guard.unseen({"machine:x": ["a"]}), {"machine:x": ["a"]})
        self.assertEqual(slurp(target), "keep")
        self.assertIn("state not written", self.log())

    def test_a_state_file_too_deep_for_json_reads_as_none_seen(self):
        guard = load_guard()
        d = self.mkdir("state", "dotclaude")
        self.write(os.path.join(d, "excluded-check.json"),
                   "[" * 100000)   # RecursionError in json, not ValueError
        with mock.patch.dict(os.environ, XDG_STATE_HOME=os.path.join(self.tmp, "state")):
            self.assertEqual(guard.unseen({"machine:x": ["a"]}), {"machine:x": ["a"]})
        self.assertIn("state not read (RecursionError", self.log())
        with open(os.path.join(d, "excluded-check.json")) as f:
            self.assertIn("machine:x", json.load(f))

    def test_keys_with_nothing_to_say_are_not_stored(self):
        self.assertIsNone(self.start())
        with open(os.path.join(self.tmp, "state", "dotclaude", "excluded-check.json")) as f:
            self.assertEqual(json.load(f), {})

    def test_a_fifo_where_the_state_goes_never_hangs_it(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        d = self.mkdir("state", "dotclaude")
        os.mkfifo(os.path.join(d, "excluded-check.json"))
        os.mkfifo(os.path.join(d, "excluded-check.json.lock"))
        self.assertIsNotNone(self.start())

    def test_racing_starts_show_a_finding_once(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        event = json.dumps({"session_id": "s1", "hook_event_name": "SessionStart",
                            "cwd": self.proj})
        procs = [subprocess.Popen(["bash", SESSION_HOOK], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, env=self.env, cwd=self.proj)
                 for _ in range(4)]
        outs = [p.communicate(event, timeout=30)[0] for p in procs]
        self.assertEqual(sum(bool(o.strip()) for o in outs), 1, outs)

    def test_a_stuck_state_lock_still_shows(self):
        import fcntl
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        lock = os.path.join(self.mkdir("state", "dotclaude"), "excluded-check.json.lock")
        with open(lock, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            self.assertIsNotNone(self.start())
        self.assertIn("lock busy", self.log())

    def test_a_fifo_interpreter_never_hangs_it(self):
        # Judging on past the writable dir reaches the file it holds; a FIFO must not block.
        fifo = os.path.join(self.mkdir("wfifo"), "interp")
        os.mkfifo(fifo)
        self.write(os.path.join(self.wbin, "git"), f"#!{fifo}\n", 0o755)
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        msg = self.start()["systemMessage"]
        for d in (self.wbin, os.path.dirname(fifo)):
            self.assertIn(f"Edit(/{d}/**)", msg)

    def test_a_refusal_with_no_rule_is_shown_by_its_reason(self):
        self.env["PATH"] = f":{self.bin}:/usr/bin"
        self.assertIn("empty entry", self.start()["systemMessage"])

    def test_the_payload_cwd_stands_in_for_a_missing_project_dir(self):
        self.git("config", "core.hooksPath", ".githooks", cwd=self.proj)
        del self.env["CLAUDE_PROJECT_DIR"]
        event = {"session_id": "s1", "hook_event_name": "SessionStart", "cwd": self.proj}
        p = subprocess.run(["bash", SESSION_HOOK], input=json.dumps(event), capture_output=True,
                           text=True, env=self.env, timeout=20, cwd=self.tmp)
        self.assertIn(os.path.join(self.proj, ".githooks"), json.loads(p.stdout)["systemMessage"])

    def test_it_fails_open(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.assertIsNone(self.start(raw="{not json"))
        d = self.mkdir("broken")
        shutil.copy(SESSION_HOOK, os.path.join(d, "excluded-check.sh"))
        self.write(os.path.join(d, "excluded_guard.py"), "def (:\n")
        self.assertIsNone(self.start(hook=os.path.join(d, "excluded-check.sh")))
        # State it can't read or write: it still shows, every time, rather than hide a finding.
        self.mkdir("state", "dotclaude", "excluded-check.json")
        self.assertIsNotNone(self.start())
        self.assertIsNotNone(self.start())
        self.assertIn("excluded-check", self.log())


class FailsClosed(Guard):
    def test_an_unparsable_payload_falls_back_to_the_head_word(self):
        for command, deny in (("git push", True), ("  FOO=1 gh pr view", True),
                              ("\\n\\tlane ls", True), ("codex;ls", True), ("ls", False),
                              ("echo git", False)):
            with self.subTest(command=command):
                raw = '{"tool_name": "Bash", "tool_input": {"command": "' + command
                out = self.fire(None, raw=raw)
                self.assertEqual(out is not None, deny, out)
                if deny:
                    self.assertEqual(out["permissionDecision"], "deny")
                    self.assertIn("could not run", out["permissionDecisionReason"])

    def test_a_broken_module_denies_excluded_heads_and_allows_the_rest(self):
        d = self.mkdir("broken")
        shutil.copy(HOOK, os.path.join(d, "excluded-guard.sh"))
        self.write(os.path.join(d, "excluded_guard.py"), "def (:\n")
        hook = os.path.join(d, "excluded-guard.sh")
        for command in ("git push", "FOO=1 gh pr view 5", "claude --version"):
            with self.subTest(command=command):
                out = self.fire(command, hook=hook)
                self.assertEqual(out["permissionDecision"], "deny")
        for command in ("ls", "echo x && git push"):
            with self.subTest(command=command):
                self.assertIsNone(self.fire(command, hook=hook))

    def test_output_that_is_not_json_falls_back(self):
        d = self.mkdir("noisy")
        shutil.copy(HOOK, os.path.join(d, "excluded-guard.sh"))
        self.write(os.path.join(d, "excluded_guard.py"), "print('not json')\n")
        hook = os.path.join(d, "excluded-guard.sh")
        self.assertEqual(self.fire("git push", hook=hook)["permissionDecision"], "deny")
        self.assertIsNone(self.fire("ls", hook=hook))

    def test_a_missing_project_dir_refuses_a_candidate(self):
        del self.env["CLAUDE_PROJECT_DIR"]
        self.denied("git push", "project")
        self.allowed("ls")

    def test_a_projects_json_py_never_runs(self):
        ran = os.path.join(self.tmp, "ran")
        self.write(os.path.join(self.proj, "json.py"), f"open({ran!r}, 'a').write(__name__)\n")
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.denied("git push", "rule2")
        self.assertFalse(os.path.exists(ran), "the guard imported the project's json.py")


class SettingsCommand(unittest.TestCase):
    def test_a_slow_guard_times_out_into_the_head_word_fallback(self):
        # The real settings.json command, with a stand-in shim that outlives its `timeout 4`.
        with open(os.path.join(REPO, "settings.json")) as f:
            settings = json.load(f)
        (cmd,) = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]
                  if "excluded-guard" in h["command"]]
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home)
        shim = os.path.join(home, ".claude", "hooks", "excluded-guard.sh")
        os.makedirs(os.path.dirname(shim))
        with open(shim, "w") as f:
            f.write("cat >/dev/null\nsleep 6\n")
        env = dict(os.environ, HOME=home)
        for command, rc in (("git push", 2), ("ls", 0)):
            with self.subTest(command=command):
                payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
                start = time.monotonic()
                p = subprocess.run(["sh", "-c", cmd], input=payload, capture_output=True,
                                   text=True, env=env, timeout=20)
                elapsed = time.monotonic() - start
                self.assertEqual(p.returncode, rc, p.stderr)
                self.assertTrue(3.5 <= elapsed < 6, f"took {elapsed:.1f}s: not the timeout")


class SandboxReality(unittest.TestCase):
    def test_the_paths_rule_1_trusts_are_unwritable_in_the_sandbox(self):
        try:
            with open("/proc/1/cmdline", "rb") as f:
                sandboxed = b"apply-seccomp" in f.read()
        except OSError:
            sandboxed = False
        if not sandboxed:
            self.skipTest("not inside the Bash sandbox")
        real = os.path.realpath(REPO)
        if (real.startswith(os.path.realpath(tempfile.gettempdir()) + os.sep)
                or f"{os.sep}.lane-trial{os.sep}" in real):
            # `lane trial`'s scratch copy, in a lane's .lane-trial/ (an older `lane` put it
            # under the temp dir): the sandbox protects only the checkouts it was started for.
            self.skipTest("a lane trial's scratch checkout")
        guard = load_guard()
        gitdir, common, _ = guard.discover(REPO)
        paths = [os.path.join(common, "config"), os.path.join(common, "hooks")]
        if os.path.exists(os.path.join(gitdir, "config.worktree")):
            paths.append(os.path.join(gitdir, "config.worktree"))
        if os.path.isfile(os.path.join(REPO, ".git")):
            # A lane: the layout check trusts its gitfile and commondir to stay put.
            paths += [os.path.join(REPO, ".git"), os.path.join(gitdir, "commondir")]
        for p in paths:  # never written: access and file type only
            with self.subTest(path=p):
                self.assertTrue(os.path.exists(p), p)
                self.assertTrue(not os.access(p, os.W_OK) or stat.S_ISCHR(os.stat(p).st_mode),
                                f"{p} is writable inside the sandbox")


class DiscoveryMatchesGit(Guard):
    """Wherever git finds a repo, the guard finds the same gitdir and common dir, or refuses. A
    narrower guard would trust a project's config while git reads another; three review rounds
    found that class of gap one layout at a time."""

    def layouts(self):
        other = self.mkdir("other")
        self.git("init", "-q", other, cwd=self.tmp)
        bare = os.path.join(self.tmp, "proj", "bare")
        self.git("init", "-q", "--bare", bare, cwd=self.tmp)
        decoy = self.mkdir("decoy")
        for d in ("objects", "refs"):
            os.makedirs(os.path.join(decoy, d))
        marker = self.mkdir("proj", "marker")
        self.write(os.path.join(marker, "HEAD"), "ref: refs/heads/main\n")
        self.write(os.path.join(marker, "commondir"), decoy + "\n")
        empty_common = self.mkdir("proj", "marker2")
        self.write(os.path.join(empty_common, "HEAD"), "ref: refs/heads/main\n")
        self.write(os.path.join(empty_common, "commondir"), self.mkdir("nothing") + "\n")
        head_only = self.mkdir("proj", "head-only")
        self.write(os.path.join(head_only, "HEAD"), "ref: refs/heads/main\n")
        fake_bare = self.mkdir("proj", "fake-bare")
        self.write(os.path.join(fake_bare, "HEAD"), "ref: refs/heads/main\n")
        for d in ("objects", "refs"):
            os.makedirs(os.path.join(fake_bare, d))
        into_lane = self.mkdir("proj", "into-lane")
        self.write(os.path.join(into_lane, ".git"),
                   f"gitdir: {os.path.join(self.proj, '.git', 'worktrees', 'lane')}\n")
        into_other = self.mkdir("proj", "into-other")
        self.write(os.path.join(into_other, ".git"), f"gitdir: {os.path.join(other, '.git')}\n")
        nested = self.mkdir("proj", "nested")
        self.git("init", "-q", nested, cwd=self.tmp)
        return [self.proj, self.mkdir("proj", "sub", "deep"), self.lane, self.mkdir("lane", "sub"),
                os.path.join(self.proj, ".git"), bare, marker, empty_common, head_only, fake_bare,
                into_lane, into_other, nested, os.path.join(nested, ".git"), other]

    def test_the_guard_never_finds_a_narrower_repo_than_git(self):
        guard = load_guard()
        ceiling = {"GIT_CEILING_DIRECTORIES": os.path.dirname(self.tmp)}
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "GIT_CONFIG_NOSYSTEM": "1", **ceiling}
        compared = 0
        for cwd in self.layouts():
            with self.subTest(cwd=os.path.relpath(cwd, self.tmp)):
                p = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-dir",
                                    "--git-common-dir"], cwd=cwd, env=env, capture_output=True,
                                   text=True)
                if p.returncode != 0:
                    continue  # git finds no repo: a guard that finds one only refuses more
                want = tuple(os.path.realpath(x) for x in p.stdout.split())
                try:
                    found = guard.discover(cwd, ceiling)
                except guard.Refusal:
                    continue
                self.assertIsNotNone(found, f"git uses {want}, the guard found no repo")
                self.assertEqual(found[:2], want)
                compared += 1
        self.assertGreaterEqual(compared, 13)  # not vacuous: the two markers refuse, 13 match

    def test_a_git_dir_git_would_look_past_refuses(self):
        # git's is_git_directory also wants a valid HEAD (`ref: refs/...`, a symlink into refs/
        # or an object id) and objects/ and refs/, and walks on up past a dir that fails. The
        # guard refuses there rather than mimic the skip (review round 2).
        guard = load_guard()
        head = os.path.join(self.proj, ".git", "HEAD")
        real = slurp(head)
        sha = self.git("rev-parse", "HEAD", cwd=self.proj).strip()
        for text in (real, real.strip(), "ref:\t refs/heads/x\n", sha + "\n", sha.upper()):
            with self.subTest(head=text):
                self.write(head, text)
                self.allowed("git push")
        os.remove(head)
        os.symlink("refs/heads/x", head)
        self.allowed("git push")
        for text in ("junk\n", "ref: heads/main\n", "", sha[:39], "x" + sha):
            with self.subTest(head=text):
                os.remove(head)
                self.write(head, text)
                self.assertIn("looks broken", self.denied("git push", "rule1", os.path.dirname(head)))
                p = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=self.proj,
                                   capture_output=True, text=True,
                                   env={"PATH": "/usr/bin:/bin", "HOME": self.home,
                                        "GIT_CEILING_DIRECTORIES": self.tmp})
                self.assertNotEqual(p.returncode, 0)  # git looks past it, finding none here
        self.write(head, real)
        os.remove(os.path.join(self.proj, ".git", "HEAD"))
        os.symlink("heads/x", head)
        self.denied("git push", "rule1", os.path.dirname(head))
        os.remove(head)
        self.write(head, real)
        self.allowed("git push")
        # A nested .git dir or a bare-looking dir git skips refuses too, at the cwd and as a
        # server path git's server side would skip.
        nested = self.mkdir("proj", "nested", ".git", "objects")
        self.mkdir("proj", "nested", ".git", "refs")
        self.write(os.path.join(self.proj, "nested", ".git", "HEAD"), "junk\n")
        bareish = os.path.dirname(self.mkdir("proj", "bareish", "refs"))
        self.write(os.path.join(bareish, "HEAD"), "junk\n")
        for cwd in (os.path.dirname(nested), bareish):
            with self.subTest(cwd=cwd):
                with self.assertRaises(guard.Refusal) as e:
                    guard.discover(cwd, {"GIT_CEILING_DIRECTORIES": self.tmp})
                self.assertIn("looks broken", e.exception.reason)
        self.write_settings({"excludedCommands": EXCLUDED + ["git push *"]})
        for call in ("git push nested", "git push bareish"):
            with self.subTest(call=call):
                self.assertIn("looks broken", self.denied(call, "rule1"))


class ConfigEntries(unittest.TestCase):
    """config_entries reads each entry with its subsection, as git does: a quoted one kept as
    written (escapes undone), a `[section.sub]` one lowercased, "" for none."""

    def test_entries_keep_their_subsection(self):
        guard = load_guard()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config")
            with open(path, "w") as f:
                f.write('[core]\n\thooksPath = h\n[Remote "Up.Stream"]\n\tURL = /a/b\n'
                        '[url "/x/y z"] insteadOf = https://h/\n'
                        '[url "q\\"\\\\"]\n\tpushInsteadOf\n'
                        '[Old.Sub]\n\tk = v ; c\n[includeIf "gitdir:~/w/"]\n\tpath = i\n')
            self.assertEqual(list(guard.config_entries(path)), [
                ("core", "", "hookspath", "h"), ("remote", "Up.Stream", "url", "/a/b"),
                ("url", "/x/y z", "insteadof", "https://h/"),
                ("url", 'q"\\', "pushinsteadof", "true"), ("old", "sub", "k", "v"),
                ("includeif", "gitdir:~/w/", "path", "i")])


if __name__ == "__main__":
    unittest.main()
