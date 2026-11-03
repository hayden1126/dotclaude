"""`lane ls` shows the DA15/DA16 tripwire (lanelib.git_tamper) for the repo's common dir: a
`git: <reason>` line per finding, after the install line. It warns: the exit stays 0."""
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
import zlib
from unittest import mock

from _fixture import LANE, LanesRepo, lanelib
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


# Runs the lane CLI in a child with one function patched (argv[2] names which), so a test can
# stop or plant midway through a real `lane new`: "interrupt" makes verify_new raise
# KeyboardInterrupt (Ctrl-C mid-verification); "plant:<victim>:<link>" makes fetched_base plant a
# symlink at <link> to <victim> once it returns, as a lane's sandbox could while the store's full
# fetch runs.
DRIVER = """
import importlib.machinery, importlib.util, os, sys
loader = importlib.machinery.SourceFileLoader("lane_cli", sys.argv[1])
spec = importlib.util.spec_from_loader("lane_cli", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
how = sys.argv[2]
if how == "interrupt":
    def verify_new(*a, **k):
        raise KeyboardInterrupt
    mod.verify_new = verify_new
elif how.startswith("plant:"):
    _, victim, link = how.split(":")
    real = mod.fetched_base
    def fetched_base(*a, **k):
        sha = real(*a, **k)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(victim, link)
        return sha
    mod.fetched_base = fetched_base
sys.exit(mod.main(sys.argv[3:]))
"""


def plant_readme(case):
    """Overwrite README.md's loose blob in the shared object store with other bytes, which no
    tripwire sees: git then checks out what no remote showed."""
    sha = case.git("rev-parse", "HEAD:README.md").strip()
    path = os.path.join(case.common, "objects", sha[:2], sha[2:])
    case.assertTrue(os.path.exists(path), "README.md's blob is not loose")
    os.chmod(path, 0o644)
    body = b"planted\n"
    with open(path, "wb") as f:
        f.write(zlib.compress(b"blob %d\0" % len(body) + body))
    case.assertEqual(lanelib.git_tamper(case.common), [])  # no tripwire for this


def driven(case, how, *args):
    """`lane <args>` run through DRIVER with how's patch."""
    return subprocess.run([sys.executable, "-c", DRIVER, LANE, how, *args], cwd=case.main,
                          env=case.env, capture_output=True, text=True, timeout=60)


def marks(case, lane_id):
    """The verification markers for lane_id in the verified dir, which no lane can write."""
    return glob.glob(os.path.join(case.home, ".local", "state", "dotclaude", "verified",
                                  "new-lanes", f"*-{lane_id}.json"))


class NewVerifiesTree(LanesRepo):
    """LR7: `lane new` checks the lane out from the shared object store, which any lane's
    sandboxed Bash can write, then runs the configured setup command in it sandbox-off, and the
    session `lane open` starts there loads its .claude/ config. So every `new` first compares the
    new worktree with base's tree as fetched into a fresh store no lane can write, and on any
    difference runs no setup. Only a marker in the verified dir, which no lane can write, lets
    `adopt` finish a lane `new` left setup-failed."""

    def setUp(self):
        super().setUp()
        self.lane("init", "--setup", "touch SETUP_RAN")

    def setup_ran(self, lane_id="chart-fix"):
        return os.path.exists(os.path.join(self.lane_path(lane_id), "SETUP_RAN"))

    def test_a_clean_checkout_runs_the_setup(self):
        out = self.lane("new", "chart-fix")
        self.assertIn("verified", out)
        self.assertTrue(self.setup_ran())
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def test_an_overwritten_object_runs_no_setup(self):
        plant_readme(self)
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("README.md (other bytes)", p.stderr)
        lane = self.lane_path("chart-fix")
        self.assertEqual(self.read(os.path.join(lane, "README.md")), "planted\n")  # git's work
        self.assertFalse(self.setup_ran())
        rec = self.lane_json("chart-fix")
        self.assertEqual((rec["state"], rec["setup_failed"]), ("setup-failed", "verify"))
        self.assertEqual(marks(self, "chart-fix"), [])
        p = self.run_lane("adopt", lane)  # finishing it would run the setup: refused too
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertFalse(self.setup_ran())
        self.assertIn("lane done chart-fix --abandon", p.stderr)

    def test_adopt_goes_by_the_marker_not_the_lane_writable_record(self):
        plant_readme(self)
        self.assertEqual(self.run_lane("new", "chart-fix").returncode, 1)
        data = os.path.join(self.common, "lanes", "chart-fix", "lane.json")
        rec = self.lane_json("chart-fix")
        for step in ("setup", "copy"):
            with self.subTest(step=step):
                self.write(data, json.dumps(dict(rec, setup_failed=step)))
                p = self.run_lane("adopt", self.lane_path("chart-fix"))
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn("lane done chart-fix --abandon", p.stderr)
                self.assertFalse(self.setup_ran())

    def test_an_interrupted_verification_leaves_a_lane_adopt_wont_finish(self):
        p = driven(self, "interrupt", "new", "chart-fix")
        self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        rec = self.lane_json("chart-fix")
        self.assertEqual((rec["state"], rec["setup_failed"]), ("setup-failed", "verify"))
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lane done chart-fix --abandon", p.stderr)
        self.assertFalse(self.setup_ran())

    def test_open_and_park_steer_an_unverified_lane_to_done_not_adopt(self):
        plant_readme(self)
        self.assertEqual(self.run_lane("new", "chart-fix").returncode, 1)
        for args in (("open", "chart-fix", "--print"), ("park", "chart-fix")):
            with self.subTest(args=args):
                p = self.run_lane(*args)
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn("setup-failed", p.stderr)
                self.assertIn("lane done chart-fix --abandon", p.stderr)
                self.assertNotIn("lane adopt", p.stderr)

    def test_the_marker_holds_the_lane_and_done_removes_it(self):
        self.lane("new", "chart-fix")
        (mark,) = marks(self, "chart-fix")
        data = json.loads(self.read(mark))
        self.assertEqual(data["id"], "chart-fix")
        self.assertEqual(data["path"], self.lane_path("chart-fix"))
        self.assertEqual(data["base_sha"], self.lane_json("chart-fix")["base_sha"])
        os.remove(os.path.join(self.lane_path("chart-fix"), "SETUP_RAN"))  # `done` keeps it
        self.lane("done", "chart-fix", "--abandon")
        self.assertEqual(marks(self, "chart-fix"), [])

    def test_a_marker_left_from_an_older_lane_vouches_for_no_new_one(self):
        self.lane("new", "chart-fix")
        (mark,) = marks(self, "chart-fix")
        kept = self.read(mark)
        os.remove(os.path.join(self.lane_path("chart-fix"), "SETUP_RAN"))
        self.lane("done", "chart-fix", "--abandon")
        self.write(mark, kept)  # as if that `done` couldn't remove it
        plant_readme(self)
        self.assertEqual(self.run_lane("new", "chart-fix").returncode, 1)
        data = os.path.join(self.common, "lanes", "chart-fix", "lane.json")
        self.write(data, json.dumps(dict(self.lane_json("chart-fix"), setup_failed="setup")))
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertFalse(self.setup_ran())


class NewVerifiesWithoutSetup(LanesRepo):
    """LR7 with no setup command: the session `lane open` starts in the tree loads its .claude/
    config, whose hooks run outside the sandbox, so `new` verifies the checkout all the same."""

    def test_an_overwritten_object_is_refused(self):
        plant_readme(self)
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("README.md (other bytes)", p.stderr)
        rec = self.lane_json("chart-fix")
        self.assertEqual((rec["state"], rec["setup_failed"]), ("setup-failed", "verify"))
        self.assertIn("setup-failed", self.run_lane("open", "chart-fix", "--print").stderr)

    def test_a_clean_checkout_is_verified(self):
        self.assertIn("verified", self.lane("new", "chart-fix"))
        self.assertEqual(len(marks(self, "chart-fix")), 1)

    def test_without_the_store_rules_nothing_is_created(self):
        self.write(os.path.join(self.home, ".claude", "settings.json"), "{}")
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("Edit(~/.local/state/dotclaude/verified/**)", p.stderr)
        self.assertIn("sandbox.filesystem.denyWrite", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertFalse(os.path.exists(self.lane_path("chart-fix")))
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "chart-fix")))
        self.assertEqual(self.git("branch", "--list", "chart-fix"), "")


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

    def test_new_checks_again_under_the_lock_before_worktree_add(self):
        # The store's full fetch of the base takes a while; a reflog link planted meanwhile at
        # the branch `worktree add -b` creates would take its log line sandbox-off (L2).
        victim = os.path.join(self.tmp, "victim")
        self.write(victim, "mine\n")
        link = os.path.join(self.common, "logs", "refs", "heads", "chart-fix")
        p = driven(self, f"plant:{victim}:{link}", "new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("logs/refs/heads/chart-fix is a symlink", p.stderr)
        self.assertEqual(self.read(victim), "mine\n")
        self.assertFalse(os.path.exists(self.lane_path("chart-fix")))
        self.assertEqual(self.git("branch", "--list", "chart-fix"), "")


if __name__ == "__main__":
    unittest.main()
