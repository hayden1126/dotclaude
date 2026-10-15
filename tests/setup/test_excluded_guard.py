"""hooks/excluded-guard.sh: excluded commands must not act on anything a sandboxed session can write.

Each test builds a fake HOME (with .claude/settings.json), a project repo made by `git init` plus a
`git worktree add` lane, and PATH dirs holding marker executables (`#!/bin/sh` echo scripts named
git, gh, lane, claude, codex). The temp dir sits under a root ($TMPDIR or /tmp) and belongs to the
user, so a "clean" (protected) dir is one an Edit deny rule in the user settings covers:
permission bits protect nothing there, and only /usr/bin-style dirs outside every root are
protected by location.
"""
import importlib.util
import json
import os
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
EXCLUDED = ["git push", "git push origin *", "gh pr *", "lane ls", "lane ls *", "claude *",
            "codex login status"]
HEADS = ("git", "gh", "lane", "claude", "codex")
MARKER = "#!/bin/sh\necho marker\n"


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
        self.deny_write = []  # paths an Edit deny rule covers (both routes)
        self.sandbox_deny = []  # raw denyWrite lines (sandboxed Bash only)
        self.proj = os.path.join(self.tmp, "proj")
        self.lane = os.path.join(self.tmp, "lane")
        self.git("init", "-q", self.proj, cwd=self.tmp)
        self.git("commit", "-q", "--allow-empty", "-m", "init", cwd=self.proj)
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

    def test_a_subdir_of_the_root_in_the_same_repo_passes(self):
        self.allowed("git push", cwd=self.mkdir("proj", "sub", "deeper"))

    def test_a_nested_repo_under_the_root_is_refused(self):
        nested = self.mkdir("proj", "sub", "nested")
        self.git("init", "-q", nested, cwd=self.tmp)
        self.denied("git push", "rule1", os.path.join(nested, ".git"), cwd=nested)
        self.assertIn("deny rule1 " + os.path.join(nested, ".git"), self.log())

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

    def test_no_repo_at_the_cwd_passes(self):
        plain = self.mkdir("plain")
        self.env["CLAUDE_PROJECT_DIR"] = plain
        self.allowed("git push", cwd=plain)

    def test_a_project_root_that_is_no_repo_makes_any_repo_foreign(self):
        self.env["CLAUDE_PROJECT_DIR"] = self.mkdir("plain")
        self.denied("git push", "rule1")

    def test_a_cwd_with_no_repo_passes_while_the_project_is_a_repo(self):
        self.allowed("git push", cwd=self.mkdir("plain"))

    def test_another_worktrees_config_worktree_is_judged(self):
        # A lane-like project, cwd in the main checkout: same common dir, a different gitdir.
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.allowed("git push", cwd=self.proj)
        cfg = self.write(os.path.join(self.proj, ".git", "config.worktree"), "")
        self.denied("git push", "rule1", cfg, cwd=self.proj)

    def test_the_projects_own_config_worktree_is_trusted(self):
        self.env["CLAUDE_PROJECT_DIR"] = self.lane
        self.write(os.path.join(self.proj, ".git", "worktrees", "lane", "config.worktree"), "")
        self.allowed("git push", cwd=self.lane)


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
        sub = self.mkdir("proj", "sub")
        self.denied("claude --version", "rule3", sub, cwd=sub)

    def test_codex_runs_only_from_the_project_root(self):
        self.allowed("codex login status")
        sub = self.mkdir("proj", "sub")
        self.denied("codex login status", "rule3", sub, cwd=sub)

    def test_git_from_a_subdir_is_not_held_to_rule_3(self):
        self.allowed("git push", cwd=self.mkdir("proj", "sub"))


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


if __name__ == "__main__":
    unittest.main()
