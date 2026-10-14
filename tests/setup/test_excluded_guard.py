"""hooks/excluded-guard.sh: excluded commands must not act on anything a sandboxed session can write.

Each test builds a fake HOME (with .claude/settings.json), a project repo made by `git init` plus a
`git worktree add` lane, and PATH dirs holding marker executables (`#!/bin/sh` echo scripts named
git, gh, lane, claude, codex). The temp dir sits under a root ($TMPDIR or /tmp) and belongs to the
user, so a "clean" (protected) dir is one listed in the user settings' denyWrite: permission bits
protect nothing there, and only /usr/bin-style dirs outside every root are protected by location.
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

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "excluded-guard.sh")
MODULE = os.path.join(REPO, "hooks", "excluded_guard.py")
EXCLUDED = ["git push", "git push origin *", "gh pr *", "lane ls", "lane ls *", "claude *",
            "codex login status"]
HEADS = ("git", "gh", "lane", "claude", "codex")
MARKER = "#!/bin/sh\necho marker\n"


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
        self.deny_write = []
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
                   "filesystem": {"denyWrite": self.deny_write, "allowWrite": []}}
        sandbox.update(extra or {})
        self.write(os.path.join(self.home, ".claude", "settings.json"),
                   json.dumps({"sandbox": sandbox}))

    def git(self, *args, cwd):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                              text=True).stdout

    def protect(self, path):
        """List `path` in the user settings' denyWrite."""
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

    def test_a_denywrite_entry_protects_a_path_dir(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.denied("lane ls", "rule2", self.wbin)
        self.deny_write.append(self.wbin)
        self.write_settings()
        self.allowed("lane ls")

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

    def test_a_symlinked_home_resolves_its_denywrite_entries(self):
        links = self.protect(self.mkdir("homelinks"))  # the link itself must be protected
        link = os.path.join(links, "home")
        os.symlink(self.home, link)
        hbin = self.make_bin(os.path.join("home", "bin"), protect=False)
        self.protect("~/bin")
        self.write(os.path.join(self.home, ".gitconfig"), "[user]\n\tname = x\n")
        self.env["HOME"] = link
        self.env["PATH"] = f"{link}/bin:/usr/bin"
        self.allowed("git push")
        self.env["PATH"] = f"{hbin}:/usr/bin"
        self.allowed("git push")
        self.make_bin(os.path.join("home", "wbin"), protect=False)
        self.env["PATH"] = f"{link}/wbin:/usr/bin"
        self.denied("git push", "rule2", f"{link}/wbin")

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

    def test_denywrite_counts_only_from_user_and_managed_settings(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        local = {"sandbox": {"filesystem": {"denyWrite": [self.wbin]}}}
        self.write(os.path.join(self.proj, ".claude", "settings.local.json"), json.dumps(local))
        self.write(os.path.join(self.proj, ".claude", "settings.json"), json.dumps(local))
        self.denied("git push", "rule2", self.wbin)
        self.write(os.path.join(self.tmp, "managed", "managed-settings.json"), json.dumps(local))
        self.allowed("git push")

    def test_an_unreadable_settings_file_makes_the_call_a_candidate(self):
        self.env["PATH"] = f"{self.wbin}:/usr/bin"
        self.write(os.path.join(self.proj, ".claude", "settings.json"), "{not json")
        self.denied("gh issue list", "rule2")


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
        spec = importlib.util.spec_from_file_location("excluded_guard", MODULE)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
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


if __name__ == "__main__":
    unittest.main()
