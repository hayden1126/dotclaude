"""`lane ls` shows the DA15/DA16 tripwire (lanelib.git_tamper) for the repo's common dir: a
`git: <reason>` line per finding, after the install line. It warns: the exit stays 0."""
import fcntl
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from unittest import mock

from _fixture import LANE, LanesRepo, LiveSessions, lanelib
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
# fetch runs; "lanes-wait:<secs>" sets LANES_LOCK_WAIT, so a held lanes lock refuses soon;
# "forge:<func>[@<n>]:<dir>" makes <func> (one taking repo and lane first) rewrite the lane's
# lane.json path to <dir> once its first (or nth) call returns, as any lane's sandbox could; "open-midway:<out>" makes verify_new
# flip lane.json to active, run `lane open <id> --print` and write its exit code to <out>, then
# put lane.json back and verify.
DRIVER = """
import importlib.machinery, importlib.util, json, os, subprocess, sys
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
elif how.startswith("lanes-wait:"):
    mod.LANES_LOCK_WAIT = float(how.split(":")[1])
elif how.startswith("forge:"):
    _, name, forged = how.split(":")
    name, _, nth = name.partition("@")
    real, calls = getattr(mod, name), []
    def forging(repo, lane, *a, **k):
        out = real(repo, lane, *a, **k)
        calls.append(1)
        if len(calls) == int(nth or 1):
            rec = mod.lanelib.read_record(repo, lane["id"])
            mod.lanelib.write_lane_json(repo, lane["id"], dict(rec, path=forged))
        return out
    setattr(mod, name, forging)
elif how.startswith("open-midway:"):
    out = how.split(":", 1)[1]
    real = mod.verify_new
    def verify_new(repo, lane, *a, **k):
        rec = mod.lanelib.read_record(repo, lane["id"])
        flipped = {k: v for k, v in rec.items() if k != "setup_failed"}
        mod.lanelib.write_lane_json(repo, lane["id"], dict(flipped, state="active"))
        p = subprocess.run([sys.executable, sys.argv[1], "open", lane["id"], "--print"],
                           cwd=repo.main, capture_output=True, text=True)
        with open(out, "w") as f:
            json.dump({"rc": p.returncode, "out": p.stdout, "err": p.stderr}, f)
        mod.lanelib.write_lane_json(repo, lane["id"], rec)
        return real(repo, lane, *a, **k)
    mod.verify_new = verify_new
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


def driven(case, how, *args, timeout=60):
    """`lane <args>` run through DRIVER with how's patch."""
    return subprocess.run([sys.executable, "-c", DRIVER, LANE, how, *args], cwd=case.main,
                          env=case.env, capture_output=True, text=True, timeout=timeout)


def marks(case, lane_id):
    """The verification markers for lane_id in the verified dir, which no lane can write."""
    return glob.glob(os.path.join(case.home, ".local", "state", "dotclaude", "verified",
                                  "new-lanes", f"*-{lane_id}.json"))


def forged_worktree(case, name="forged"):
    """A dir outside every lane that passes for a worktree of the repo: a .git file naming an
    admin dir under <common>/worktrees/ that names it back, as any lane's sandbox can write both.
    Its OK file lets the failed_setup fixture's setup command pass there."""
    forged = os.path.join(case.tmp, name)
    admin = os.path.join(case.common, "worktrees", name)
    os.makedirs(forged)
    os.makedirs(admin)
    case.write(os.path.join(forged, ".git"), f"gitdir: {admin}\n")
    case.write(os.path.join(admin, "gitdir"), os.path.join(forged, ".git") + "\n")
    case.write(os.path.join(admin, "commondir"), "../..\n")
    case.write(os.path.join(forged, "OK"), "")
    repo = lanelib.Repo(case.main, case.common)
    case.assertIsNone(lanelib.worktree_problem(repo, forged, repo.lanes(shared=True)))
    return forged


def flip(case, lane_id, step="setup"):
    """Set lane_id's lane.json to setup-failed at step, as any lane's sandbox can."""
    data = os.path.join(case.common, "lanes", lane_id, "lane.json")
    case.write(data, json.dumps(dict(case.lane_json(lane_id), state="setup-failed",
                                     setup_failed=step)))


def steers_to_done(case, lane_id):
    """`open` and `park` refuse the setup-failed lane and point to `done --abandon`, not adopt."""
    for args in (("open", lane_id, "--print"), ("park", lane_id)):
        with case.subTest(args=args):
            p = case.run_lane(*args)
            case.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            case.assertIn(f"lane done {lane_id} --abandon", p.stderr)
            case.assertNotIn("lane adopt", p.stderr)


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
        (mark,) = marks(self, "chart-fix")  # the pending one, which vouches for nothing
        self.assertIs(json.loads(self.read(mark))["verified"], False)
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

    def test_a_finished_lane_keeps_no_marker_adopt_would_trust(self):
        # M1: the marker vouches only for a tree nothing has run in, so a lane `new` finished
        # has none, and a lane.json flipped back to setup-failed gets no setup run.
        self.lane("new", "chart-fix")
        self.assertEqual(marks(self, "chart-fix"), [])
        os.remove(os.path.join(self.lane_path("chart-fix"), "SETUP_RAN"))
        for step in ("setup", "copy"):
            with self.subTest(step=step):
                flip(self, "chart-fix", step)
                p = self.run_lane("adopt", self.lane_path("chart-fix"))
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn("lane done chart-fix --abandon", p.stderr)
                self.assertFalse(self.setup_ran())
        steers_to_done(self, "chart-fix")

    def test_a_lane_adopt_finished_keeps_no_marker(self):
        # A failed setup keeps the marker, so adopt finishes the lane; once it has, the marker
        # is gone, as for a lane `new` finished.
        self.lane("init", "--setup", "test -e OK && touch SETUP_RAN")
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(len(marks(self, "chart-fix")), 1)
        self.write(os.path.join(self.lane_path("chart-fix"), "OK"), "")
        self.lane("adopt", self.lane_path("chart-fix"))
        self.assertTrue(self.setup_ran())
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertEqual(marks(self, "chart-fix"), [])
        os.remove(os.path.join(self.lane_path("chart-fix"), "SETUP_RAN"))
        flip(self, "chart-fix")
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertFalse(self.setup_ran())
        steers_to_done(self, "chart-fix")

    def test_a_marker_new_cannot_drop_refuses_and_leaves_the_lane_setup_failed(self):
        # The setup makes the markers' dir read-only, so the drop fails: `new` refuses and
        # leaves the lane setup-failed at 'setup', where only the setup has run, so the kept
        # marker vouches for nothing a session wrote.
        marks_dir = os.path.join(self.home, ".local", "state", "dotclaude", "verified",
                                 "new-lanes")
        self.addCleanup(lambda: os.path.isdir(marks_dir) and os.chmod(marks_dir, 0o700))
        self.lane("init", "--setup", f"chmod 500 '{marks_dir}' && touch SETUP_RAN")
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("marker", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        rec = self.lane_json("chart-fix")
        self.assertEqual((rec["state"], rec["setup_failed"]), ("setup-failed", "setup"))
        self.assertIn("setup-failed", self.run_lane("open", "chart-fix", "--print").stderr)
        os.chmod(marks_dir, 0o700)
        self.lane("init", "--setup", "touch SETUP_RAN")
        self.lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertEqual(marks(self, "chart-fix"), [])

    def test_a_lane_new_refused_is_closed_once_its_dir_is_deleted_by_hand(self):
        # L1: `done --abandon` keeps a tree git finds changed, so the refusal says to delete
        # the dir by hand first, since nothing ran there.
        plant_readme(self)
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        lane = self.lane_path("chart-fix")
        self.assertIn(f"delete {lane} by hand", p.stderr)
        self.assertIn("lane done chart-fix --abandon", p.stderr)
        for args in (("open", "chart-fix", "--print"), ("park", "chart-fix")):
            with self.subTest(args=args):
                self.assertIn(f"delete {lane} by hand", self.run_lane(*args).stderr)
        shutil.rmtree(lane)
        self.lane("done", "chart-fix", "--abandon")
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "chart-fix")))
        self.assertEqual(self.git("branch", "--list", "chart-fix"), "")
        self.assertNotIn("chart-fix", self.git("worktree", "list"))
        sha = self.git("rev-parse", "HEAD:README.md").strip()
        with open(os.path.join(self.common, "objects", sha[:2], sha[2:]), "wb") as f:
            f.write(zlib.compress(b"blob 6\0hello\n"))  # the blob's own bytes again
        self.lane("new", "chart-fix")  # the id, its path and its branch are free again

    def test_done_removes_the_marker_of_a_lane_new_left_setup_failed(self):
        self.lane("init", "--setup", "false")
        self.assertEqual(self.run_lane("new", "chart-fix").returncode, 1)
        (mark,) = marks(self, "chart-fix")
        data = json.loads(self.read(mark))
        self.assertEqual(data["id"], "chart-fix")
        self.assertEqual(data["path"], self.lane_path("chart-fix"))
        self.assertEqual(data["base_sha"], self.lane_json("chart-fix")["base_sha"])
        self.lane("done", "chart-fix", "--abandon")
        self.assertEqual(marks(self, "chart-fix"), [])

    def test_a_marker_left_from_an_older_lane_vouches_for_no_new_one(self):
        self.lane("init", "--setup", "false")
        self.assertEqual(self.run_lane("new", "chart-fix").returncode, 1)
        (mark,) = marks(self, "chart-fix")
        kept = self.read(mark)
        self.lane("done", "chart-fix", "--abandon")
        self.lane("init", "--setup", "touch SETUP_RAN")
        self.write(mark, kept)  # as if that `done` couldn't remove it
        plant_readme(self)
        self.assertEqual(self.run_lane("new", "chart-fix").returncode, 1)
        data = os.path.join(self.common, "lanes", "chart-fix", "lane.json")
        self.write(data, json.dumps(dict(self.lane_json("chart-fix"), setup_failed="setup")))
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertFalse(self.setup_ran())

    def failed_setup(self):
        """A `new` whose setup fails, which keeps the lane's marker so `adopt` can finish it."""
        self.lane("init", "--setup", "test -e OK && touch SETUP_RAN")
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(len(marks(self, "chart-fix")), 1)
        return p

    def test_a_failed_setup_says_to_fix_it_from_a_terminal(self):
        # A session there would void the marker (finish), so the fix comes from a terminal.
        self.assertIn("from a terminal, not a claude session", self.failed_setup().stderr)

    def test_open_goes_by_the_marker_not_the_lane_writable_state(self):
        # M1: while the marker vouches for the tree, no session may start there, whatever the
        # lane.json any lane's sandbox can write says.
        # A marker that no longer matches lane.json (its created stamp edited) still refuses:
        # open passes only where no marker is there at all.
        self.failed_setup()
        data = os.path.join(self.common, "lanes", "chart-fix", "lane.json")
        rec = self.lane_json("chart-fix")
        rec.pop("setup_failed", None)
        for change in ({}, {"created": "2001-01-01T00:00:00Z"}):
            self.write(data, json.dumps(dict(rec, state="active", **change)))
            for args in (("--print",), ("--print", "--focus"), ()):
                with self.subTest(change=change, args=args):
                    p = self.run_lane("open", "chart-fix", *args)
                    self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                    self.assertEqual(p.stdout, "")
                    if not change:
                        self.assertIn(f"lane adopt {self.lane_path('chart-fix')}", p.stderr)
        self.write(data, json.dumps(dict(rec, state="active")))
        self.write(os.path.join(self.lane_path("chart-fix"), "OK"), "")
        self.lane("adopt", self.lane_path("chart-fix"))
        self.assertTrue(self.setup_ran())
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_new_runs_nothing_where_a_rewritten_lane_json_points(self):
        # H1: once `new` has checked its checkout, the copy, the setup and the finish act on the
        # path `new` made, never on one re-read from lane.json, and refuse when it moved.
        forged = forged_worktree(self)
        p = driven(self, f"forge:verify_new:{forged}", "new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lane.json", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(forged, "SETUP_RAN")))
        self.assertFalse(os.path.exists(os.path.join(forged, ".lane")))
        self.assertFalse(self.setup_ran())

    def forged_adopt(self, name):
        """`adopt` of a lane whose setup failed, its lane.json set to redo the copy, with name
        (a step after the marker check) rewriting lane.json's path to a forged worktree."""
        self.failed_setup()
        flip(self, "chart-fix", "copy")
        self.write(os.path.join(self.lane_path("chart-fix"), "OK"), "")
        forged = forged_worktree(self)
        p = driven(self, f"forge:{name}:{forged}", "adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lane.json", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(forged, "SETUP_RAN")))
        self.assertFalse(self.setup_ran())

    def test_adopt_runs_nothing_where_lane_json_points_after_the_copy(self):
        # H1: `adopt` takes the path from the marker it checked, and refuses once lane.json's
        # moves.
        self.forged_adopt("lane_files")

    def test_adopt_runs_no_setup_where_lane_json_points_after_the_session_check(self):
        # H1: checked again right before the setup command starts (the second session check is
        # the setup's own).
        self.forged_adopt("sessionless@2")

    def test_open_refuses_while_new_checks_the_checkout(self):
        # L1: from before lane.json is written to the verified marker, a pending marker is
        # there, so `open` refuses whatever lane.json says; `adopt` won't finish a pending one.
        out = os.path.join(self.tmp, "open-midway.json")
        p = driven(self, f"open-midway:{out}", "new", "chart-fix")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        seen = json.loads(self.read(out))
        self.assertEqual(seen["rc"], 1, seen)
        self.assertEqual(seen["out"], "")
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def test_a_pending_marker_stays_after_a_refusal_and_done_removes_it(self):
        plant_readme(self)
        self.assertEqual(self.run_lane("new", "chart-fix").returncode, 1)
        (mark,) = marks(self, "chart-fix")
        self.assertIs(json.loads(self.read(mark))["verified"], False)
        flip(self, "chart-fix", "copy")
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertFalse(self.setup_ran())
        shutil.rmtree(self.lane_path("chart-fix"))
        self.lane("done", "chart-fix", "--abandon")
        self.assertEqual(marks(self, "chart-fix"), [])


class FinishWithSession(LiveSessions):
    """M1: `adopt` runs the setup sandbox-off, so it finishes no lane a session runs in: one
    started there by any route may have written the tree the marker vouches for."""

    def setUp(self):
        super().setUp()
        NewVerifiesTree.failed_setup(self)
        self.write(os.path.join(self.lane_path("chart-fix"), "OK"), "")

    def setup_ran(self):
        return os.path.exists(os.path.join(self.lane_path("chart-fix"), "SETUP_RAN"))

    def test_adopt_refuses_while_a_session_runs_in_the_lane(self):
        # M1: a session started there by any route may write the tree, so adopt runs no setup
        # over it, and the marker, which no longer tells the truth, goes.
        self.session(self.lane_path("chart-fix"))
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("session", p.stderr)
        self.assertIn("lane done chart-fix --abandon", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertFalse(self.setup_ran())
        self.assertEqual(marks(self, "chart-fix"), [])
        for f in glob.glob(os.path.join(self.home, ".claude", "sessions", "*.json")):
            os.remove(f)  # the session ended: its writes stay in the tree
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertFalse(self.setup_ran())
        steers_to_done(self, "chart-fix")

    def test_adopt_refuses_when_sessions_cant_be_read(self):
        self.write(os.path.join(self.home, ".claude", "sessions", "stray.json"), "{not json")
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("can't tell whether a session runs", p.stderr)
        self.assertFalse(self.setup_ran())
        self.assertEqual(len(marks(self, "chart-fix")), 1)  # nothing known ran there


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

    def test_a_finished_lane_keeps_no_marker_a_later_setup_would_trust(self):
        # M1 with no setup: the lane is finished once `new` marks it active, so its marker goes
        # then, and a setup command added later never runs over a flipped lane.json.
        self.lane("new", "chart-fix")
        self.assertEqual(marks(self, "chart-fix"), [])
        self.lane("init", "--setup", "touch SETUP_RAN")
        flip(self, "chart-fix")
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lane done chart-fix --abandon", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.lane_path("chart-fix"), "SETUP_RAN")))
        steers_to_done(self, "chart-fix")

    def held_store_lock(self):
        """Hold the stores' dir's .lock, as a running `lane new` or sync-main does."""
        verified = os.path.join(self.home, ".local", "state", "dotclaude", "verified")
        os.makedirs(verified, 0o700, exist_ok=True)
        fd = os.open(os.path.join(verified, ".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def test_new_waits_for_a_held_store_lock(self):
        # L2: two `lane new` runs at once: the second waits for the first's store lock.
        fd = self.held_store_lock()
        self.env["_LANE_TEST_STORE_WAIT"] = "30"
        proc = subprocess.Popen([sys.executable, LANE, "new", "chart-fix"], cwd=self.main,
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        time.sleep(1.5)
        self.assertIsNone(proc.poll(), proc.stderr.read() if proc.poll() is not None else "")
        fcntl.flock(fd, fcntl.LOCK_UN)
        out, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, out + err)
        self.assertEqual(err.count("waiting"), 1, err)
        self.assertIn("verified/.lock", err)
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def test_new_refuses_once_the_store_lock_wait_runs_out(self):
        self.held_store_lock()
        self.env["_LANE_TEST_STORE_WAIT"] = "0.5"
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("another lane sync-main or lane new holds", p.stderr)
        self.assertIn("waiting", p.stderr)
        self.assertFalse(os.path.exists(self.lane_path("chart-fix")))

    def test_new_checks_again_before_its_fetch_once_the_store_lock_is_free(self):
        # L1: the store lock's wait comes after `new`'s first check; a reflog link planted
        # meanwhile would take the base fetch's log line sandbox-off (LR4).
        other = os.path.join(self.tmp, "other")
        self.git("clone", "-q", self.origin, other, cwd=self.tmp)
        self.commit("more.txt", "more\n", cwd=other)
        self.git("push", "-q", "origin", "main", cwd=other)  # so the fetch would move a ref
        before = self.git("rev-parse", "refs/remotes/origin/main").strip()
        fd = self.held_store_lock()
        self.env["_LANE_TEST_STORE_WAIT"] = "30"
        proc = subprocess.Popen([sys.executable, LANE, "new", "chart-fix"], cwd=self.main,
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.assertIn("waiting", proc.stderr.readline())
        victim = os.path.join(self.tmp, "victim")
        self.write(victim, "mine\n")
        link = os.path.join(self.common, "logs", "refs", "remotes", "origin", "main")
        os.remove(link)
        os.symlink(victim, link)
        fcntl.flock(fd, fcntl.LOCK_UN)
        out, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 1, out + err)
        self.assertIn("logs/refs/remotes/origin/main is a symlink", err)
        self.assertEqual(self.read(victim), "mine\n")
        self.assertEqual(self.git("rev-parse", "refs/remotes/origin/main").strip(), before)
        self.assertFalse(os.path.exists(self.lane_path("chart-fix")))

    def test_new_refuses_on_a_held_lanes_lock_instead_of_hanging(self):
        # L2: `new` takes the lanes lock while it holds the stores' lock, and a sandboxed `lane
        # claim` or `note` can hold the lanes lock.
        fd = os.open(os.path.join(self.common, "lanes", ".lock"), os.O_WRONLY | os.O_CREAT, 0o644)
        self.addCleanup(lambda: fd in held and os.close(fd))
        held = [fd]
        fcntl.flock(fd, fcntl.LOCK_EX)
        p = driven(self, "lanes-wait:0.5", "new", "chart-fix", timeout=30)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lanes lock", p.stderr)
        self.assertIn("No lane was made", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertFalse(os.path.exists(self.lane_path("chart-fix")))
        os.close(held.pop())
        self.lane("new", "chart-fix")  # the stores' lock went with the refusal

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

    def test_a_sandboxed_new_refuses_with_a_reason_and_creates_nothing(self):
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("can't run in the Bash sandbox", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertFalse(os.path.exists(self.lane_path("chart-fix")))
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "chart-fix")))


class StoreRecheckText(unittest.TestCase):
    """N1: StoreDir.recheck's refusal reads as sentences whatever text its caller passes."""

    def test_each_callers_text_ends_as_a_sentence(self):
        mod = load_lane_script()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            os.makedirs(os.path.join(tmp, mod.VERIFIED_REL))
            other = os.open(tmp, os.O_RDONLY | os.O_DIRECTORY)  # not the stores' dir
            self.addCleanup(os.close, other)
            store = mod.StoreDir(tmp, other, "new")
            for text in ("No lane was made.", "Nothing was written.",
                         "Nothing ran in the lane's checkout: close it as said below",
                         "Nothing in the checkout was written: rerun"):
                with self.subTest(text=text), self.assertRaises(mod.LaneError) as cm:
                    store.recheck(text)
                said = str(cm.exception)
                self.assertIn(text.rstrip(".") + ". Find out what moved it", said)


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
