"""`lane ls` shows the DA15/DA16 tripwire (lanelib.git_tamper) for the repo's common dir: a
`git: <reason>` line per finding, after the install line. It warns: the exit stays 0."""
import hashlib
import os
import shutil
import subprocess
import unittest
import zlib
from unittest import mock

from _fixture import LanesRepo
from test_cli import load_lane_script


class LsTripwire(LanesRepo):
    def ls(self):
        p = self.run_lane("ls")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout

    def test_a_clean_repo_has_no_git_line(self):
        self.assertNotIn("git: ", self.ls())

    def test_each_finding_is_a_git_line(self):
        os.makedirs(os.path.join(self.common, "objects", "info"), exist_ok=True)
        self.write(os.path.join(self.common, "objects", "info", "alternates"), "/x/objects\n")
        self.write(os.path.join(self.common, "shallow"), "")
        lines = [x for x in self.ls().splitlines() if x.startswith("git: ")]
        self.assertEqual(len(lines), 2, lines)
        self.assertIn("objects/info/alternates", lines[0])
        self.assertIn("shallow", lines[1])

    def test_the_git_lines_come_last(self):
        self.lane("new", "chart-fix")
        self.write(os.path.join(self.common, "info", "grafts"), "")
        out = self.ls().splitlines()
        self.assertTrue(out[-1].startswith("git: info/grafts"), out)

    def test_a_commondir_in_the_main_checkouts_git_dir_is_a_git_line(self):
        # git follows a commondir file in the main checkout's .git to another dir, so the common
        # dir git names may be the planted one: ls checks the checkout's own .git too. One that
        # names a clean dir loses the lanes config (keyed by the common dir), so ls refuses; it
        # never shows a clean board.
        clean = os.path.join(self.tmp, "clean.git")
        self.git("init", "-q", "--bare", clean, cwd=self.tmp)
        for text in (".\n", clean + "\n"):
            with self.subTest(text=text):
                self.write(os.path.join(self.common, "commondir"), text)
                p = self.run_lane("ls")
                lines = [x for x in p.stdout.splitlines() if x.startswith("git: ")]
                self.assertTrue(p.returncode != 0 or any("commondir" in x for x in lines),
                                p.stdout + p.stderr)
                if text == ".\n":
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


class NoAutoCleanup(LanesRepo):
    """LR3: a lane plants enough loose objects for `gc --auto` plus a symlink under
    <common>/worktrees/. The next fetch outside the sandbox runs gc, whose `git worktree prune`
    deletes what the link points at. The lane CLI's fetches (new, done, park) never run it: the
    control, a plain fetch in a copy of the checkout, empties its victim; the CLI's leaves
    its own whole. gc.autoDetach false keeps gc in the foreground, so the result is final when
    the fetch returns."""

    def plant(self, checkout):
        """A victim dir with a file, a worktrees/ link to it and 30 loose objects in objects/17/
        (gc --auto counts that one dir: more than 27 there reads as over its 6700 default)."""
        common = os.path.join(checkout, ".git")
        victim = os.path.join(self.tmp, f"victim-{os.path.basename(checkout)}")
        os.makedirs(victim)
        self.write(os.path.join(victim, "keep.txt"), "mine\n")
        os.makedirs(os.path.join(common, "worktrees"), exist_ok=True)
        os.symlink(victim, os.path.join(common, "worktrees", "x"))
        self.git("config", "gc.autoDetach", "false", cwd=checkout)
        n = made = 0
        while made < 30:
            n += 1
            body = f"loose {n}\n".encode()
            raw = b"blob %d\0" % len(body) + body
            sha = hashlib.sha1(raw).hexdigest()
            if sha.startswith("17"):
                path = os.path.join(common, "objects", "17", sha[2:])
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(zlib.compress(raw))
                made += 1
        return victim

    def test_the_lane_clis_fetches_leave_a_planted_worktrees_link_alone(self):
        copy = os.path.join(self.tmp, "control")
        shutil.copytree(self.main, copy, symlinks=True)
        control = self.plant(copy)
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=copy, env=self.env,
                       capture_output=True, timeout=60)
        self.assertEqual(os.listdir(control), [], "the control's fetch didn't prune")
        # A commit only origin has, so park's remote_tip must fetch it; made before the plant,
        # since this commit's own gc would prune too.
        self.commit("more.txt", "more\n")
        self.git("push", "-q", "origin", "HEAD:refs/heads/other")
        self.git("update-ref", "-d", "refs/remotes/origin/other")
        tip = self.git("rev-parse", "HEAD").strip()
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.git("reflog", "expire", "--expire=now", "--all")
        self.git("prune", "--expire=now")
        victim = self.plant(self.main)
        mod = load_lane_script()
        here = os.getcwd()
        with mock.patch.dict(os.environ, self.env, clear=True):
            os.chdir(self.main)
            try:
                repo = mod.lanes_repo()
                for name, call in (
                        ("park's remote_tip", lambda: mod.remote_tip(repo, "origin", "other", "x")),
                        ("done's fetch", lambda: mod.fetch(repo)),
                        ("new's fetched_base", lambda: mod.fetched_base(repo, repo.config()))):
                    with self.subTest(name):
                        self.assertTrue(call())
                        self.assertEqual(os.listdir(victim), ["keep.txt"])
            finally:
                os.chdir(here)
        self.assertEqual(self.git("rev-parse", "refs/remotes/origin/other").strip(), tip)


class NoFetchHead(LanesRepo):
    """LR5: a lane plants <common>/FETCH_HEAD as a link to a file of the user's. A plain fetch
    outside the sandbox writes its fetched refs through the link; the lane CLI's fetches (new,
    done, park) write no FETCH_HEAD at all."""

    def plant(self, common, name):
        victim = os.path.join(self.tmp, f"victim-{name}")
        self.write(victim, "mine\n")
        os.symlink(victim, os.path.join(common, "FETCH_HEAD"))
        return victim

    def test_the_lane_clis_fetches_write_no_fetch_head(self):
        copy = os.path.join(self.tmp, "control")
        shutil.copytree(self.main, copy, symlinks=True)
        control = self.plant(os.path.join(copy, ".git"), "control")
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=copy, env=self.env,
                       capture_output=True, timeout=60)
        self.assertNotEqual(self.read(control), "mine\n", "the control's fetch left it alone")
        # A commit only origin has, so park's remote_tip must fetch it.
        self.commit("more.txt", "more\n")
        self.git("push", "-q", "origin", "HEAD:refs/heads/other")
        self.git("update-ref", "-d", "refs/remotes/origin/other")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.git("reflog", "expire", "--expire=now", "--all")
        self.git("prune", "--expire=now")
        victim = self.plant(self.common, "main")
        mod = load_lane_script()
        here = os.getcwd()
        with mock.patch.dict(os.environ, self.env, clear=True):
            os.chdir(self.main)
            try:
                repo = mod.lanes_repo()
                for name, call in (
                        ("park's remote_tip", lambda: mod.remote_tip(repo, "origin", "other", "x")),
                        ("done's fetch", lambda: mod.fetch(repo)),
                        ("new's fetched_base", lambda: mod.fetched_base(repo, repo.config()))):
                    with self.subTest(name):
                        self.assertTrue(call())
                        self.assertEqual(self.read(victim), "mine\n")
            finally:
                os.chdir(here)


class NoHooks(LanesRepo):
    """The lane CLI's own git sandbox-off runs no hook: one in the common dir's hooks/ (no
    lane's sandbox can write it today, but the CLI doesn't rely on that) fires on a plain
    `git worktree add` in the control, and never during `lane new` or `lane done`."""

    HOOKS = ("reference-transaction", "post-checkout", "post-merge", "pre-auto-gc")

    def plant(self, common, marker):
        for name in self.HOOKS:
            path = os.path.join(common, "hooks", name)
            self.write(path, f'#!/bin/sh\necho "{name}" >> "{marker}"\n')
            os.chmod(path, 0o755)

    def test_new_and_done_run_no_hook(self):
        copy = os.path.join(self.tmp, "control")
        shutil.copytree(self.main, copy, symlinks=True)
        control = os.path.join(self.tmp, "control.marker")
        self.plant(os.path.join(copy, ".git"), control)
        subprocess.run(["git", "worktree", "add", "-q", "-b", "x", os.path.join(self.tmp, "wt")],
                       cwd=copy, env=self.env, capture_output=True, timeout=60)
        self.assertIn("post-checkout", self.read(control))
        marker = os.path.join(self.tmp, "main.marker")
        self.plant(self.common, marker)
        # A commit only origin has, so `done`'s fetch moves a ref.
        other = os.path.join(self.tmp, "other")
        self.git("clone", "-q", self.origin, other, cwd=self.tmp)
        self.commit("more.txt", "more\n", cwd=other)
        self.git("push", "-q", "origin", "main", cwd=other)
        self.lane("new", "chart-fix")
        self.lane("done", "chart-fix", "--abandon")
        self.assertFalse(os.path.exists(marker), self.read(marker) if os.path.exists(marker)
                         else "")


class GateBeforeRefs(LanesRepo):
    """LR4: `new`, `done` and `park` move refs sandbox-off (a fetch, `worktree add -b`,
    `branch -d`), so each runs the tripwire first and refuses on a finding, here a reflog link
    planted at the path of a ref the command would write, before any of its git runs."""

    def test_new_done_and_park_refuse_on_a_finding(self):
        self.lane("new", "chart-fix")
        victim = os.path.join(self.tmp, "victim")
        self.write(victim, "mine\n")
        link = os.path.join(self.common, "logs", "refs", "remotes", "origin", "other")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(victim, link)
        for args in (("new", "api-docs"), ("park", "chart-fix"), ("done", "chart-fix")):
            with self.subTest(args=args):
                p = self.run_lane(*args)
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn("logs/refs/remotes/origin/other is a symlink", p.stderr)
                self.assertEqual(self.read(victim), "mine\n")
        self.assertFalse(os.path.exists(self.lane_path("api-docs")))
        self.assertTrue(os.path.isdir(self.lane_path("chart-fix")))
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        os.unlink(link)
        self.lane("new", "api-docs")


if __name__ == "__main__":
    unittest.main()
