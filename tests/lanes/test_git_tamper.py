"""`lane ls` shows the DA15/DA16 tripwire (lanelib.git_tamper) for the repo's common dir: a
`git: <reason>` line per finding, after the install line. It warns: the exit stays 0."""
import fcntl
import glob
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from unittest import mock

from _fixture import LANE, LanesRepo, LiveSessions, lanelib
from _http_remote import Remote, helper_script
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
# put lane.json back and verify; "hold-setup:<began>:<release>" makes run_setup create <began>,
# then wait (up to a minute) for <release> to exist before the setup runs; "hold-done:<began>:
# <release>" does the same right after `done`'s remove_worktree returns.
DRIVER = """
import importlib.machinery, importlib.util, json, os, subprocess, sys, time
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
elif how.startswith("hold-done:"):
    _, began, release = how.split(":")
    real = mod.remove_worktree
    def remove_worktree(*a, **k):
        out = real(*a, **k)
        open(began, "w").close()
        for _ in range(600):
            if os.path.exists(release):
                break
            time.sleep(0.1)
        return out
    mod.remove_worktree = remove_worktree
elif how.startswith("hold-setup:"):
    _, began, release = how.split(":")
    real = mod.run_setup
    def run_setup(*a, **k):
        open(began, "w").close()
        for _ in range(600):
            if os.path.exists(release):
                break
            time.sleep(0.1)
        return real(*a, **k)
    mod.run_setup = run_setup
elif how == "http":  # the test remote is plain http (_http_remote): allow it, nothing else
    real = mod.sync_env
    def sync_env(*a, **k):
        env = real(*a, **k)
        env["GIT_ALLOW_PROTOCOL"] += ":http"
        return env
    mod.sync_env = sync_env
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
        self.assertIn("lane chart-fix is unfinished", seen["err"])
        self.assertNotIn("Traceback", seen["err"])
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def held_finish(self, *args):
        """`lane <args>` started through DRIVER and held at its setup step until the returned
        release file exists: (process, release)."""
        began, release = (os.path.join(self.tmp, n) for n in ("began", "release"))
        proc = subprocess.Popen([sys.executable, "-c", DRIVER, LANE,
                                 f"hold-setup:{began}:{release}", *args], cwd=self.main,
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.monotonic() + 60
        while not os.path.exists(began):
            if proc.poll() is not None:
                self.fail("".join(proc.communicate()))
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.1)
        return proc, release

    def setup_runs(self):
        count = os.path.join(self.lane_path("chart-fix"), "SETUP_COUNT")
        return len(self.read(count).splitlines()) if os.path.exists(count) else 0

    def refused_as_finishing(self, p):
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(p.stdout, "")
        self.assertIn("another `lane new` or `lane adopt` is finishing lane chart-fix", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def released(self, proc, release):
        self.write(release, "")
        out, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, out + err)
        self.assertEqual(self.setup_runs(), 1)
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertEqual(marks(self, "chart-fix"), [])
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_adopt_refuses_while_new_finishes_the_lane(self):
        # While `new`'s setup runs, its verified marker is there and no session is: an `adopt`
        # of the lane would run a second setup, then drop the marker, so `open` would pass
        # while `new`'s setup still runs. The finishing lock refuses it, and `open` too.
        self.lane("init", "--setup", "echo ran >> SETUP_COUNT")
        proc, release = self.held_finish("new", "chart-fix")
        self.refused_as_finishing(self.run_lane("adopt", self.lane_path("chart-fix")))
        self.assertEqual(self.setup_runs(), 0)
        self.assertEqual(len(marks(self, "chart-fix")), 1)
        p = self.run_lane("open", "chart-fix", "--print")
        self.refused_as_finishing(p)
        self.assertIn("lane chart-fix is unfinished", p.stderr)
        self.released(proc, release)

    def test_a_second_adopt_refuses_while_one_finishes_the_lane(self):
        self.failed_setup()
        self.lane("init", "--setup", "echo ran >> SETUP_COUNT")
        proc, release = self.held_finish("adopt", self.lane_path("chart-fix"))
        self.refused_as_finishing(self.run_lane("adopt", self.lane_path("chart-fix")))
        self.assertEqual(self.setup_runs(), 0)
        self.refused_as_finishing(self.run_lane("open", "chart-fix", "--print"))
        self.released(proc, release)

    def test_open_refuses_while_the_finishing_lock_is_held(self):
        # Belt and braces: the lock's span holds the marker's, so `open` refuses on it alone.
        self.lane("new", "chart-fix")
        (lock,) = glob.glob(os.path.join(self.home, ".local", "state", "dotclaude", "verified",
                                         "new-lanes", "*-chart-fix.lock"))
        fd = os.open(lock, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.refused_as_finishing(self.run_lane("open", "chart-fix", "--print"))
        fcntl.flock(fd, fcntl.LOCK_UN)
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_done_refuses_while_the_finishing_lock_is_held(self):
        # A `done` mid-finish would remove the tree a sandbox-off setup is running in.
        self.lane("new", "chart-fix")
        (lock,) = glob.glob(os.path.join(self.home, ".local", "state", "dotclaude", "verified",
                                         "new-lanes", "*-chart-fix.lock"))
        fd = os.open(lock, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("is finishing lane chart-fix", p.stderr)
        self.assertTrue(os.path.isdir(self.lane_path("chart-fix")))
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.remove(os.path.join(self.lane_path("chart-fix"), "SETUP_RAN"))  # the fixture's setup
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_a_new_of_the_same_id_refuses_while_done_runs(self):
        # `done` holds the finishing lock to its end: a `new` of its id, let in by a lane that
        # cleared the record once the tree was gone, can't write a marker `done` then drops.
        self.lane("new", "chart-fix")
        os.remove(os.path.join(self.lane_path("chart-fix"), "SETUP_RAN"))  # the fixture's setup
        began, release = os.path.join(self.tmp, "began"), os.path.join(self.tmp, "release")
        done = subprocess.Popen([sys.executable, "-c", DRIVER, LANE, f"hold-done:{began}:{release}",
                                 "done", "chart-fix", "--abandon"], cwd=self.main, env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: done.poll() is None and done.kill())
        for _ in range(600):
            if os.path.exists(began) or done.poll() is not None:
                break
            time.sleep(0.1)
        self.assertTrue(os.path.exists(began), done.communicate()[1] if done.poll() else "")
        shutil.rmtree(os.path.join(self.common, "lanes", "chart-fix"))
        p = self.run_lane("new", "chart-fix", "--reuse-branch")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("is finishing lane chart-fix", p.stderr)
        self.assertEqual(marks(self, "chart-fix"), [])
        open(release, "w").close()
        done.communicate(timeout=60)

    def test_new_keeps_the_marker_when_lane_json_drifts_before_the_drop(self):
        # finished_lane checks lane.json still names the lane `new` made before it drops the
        # marker: a drift after the setup refuses with the marker kept and the lane unfinished.
        forged = forged_worktree(self)
        p = driven(self, f"forge:run_setup:{forged}", "new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lane.json no longer names the lane", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertTrue(self.setup_ran())
        self.assertEqual(len(marks(self, "chart-fix")), 1)
        rec = self.lane_json("chart-fix")
        self.assertEqual((rec["state"], rec["path"]), ("setup-failed", forged))

    def test_a_failed_setup_records_nothing_once_lane_json_drifted(self):
        # run_setup's failure path writes the record only while lane.json still names the
        # lane `new` made (pinned_update): a setup that rewrote it and failed is refused as such.
        data = os.path.join(self.common, "lanes", "chart-fix", "lane.json")
        script = os.path.join(self.tmp, "drift.py")
        self.write(script, f"import json\nr = json.load(open({data!r}))\nr['path'] = '/elsewhere'"
                           f"\njson.dump(r, open({data!r}, 'w'))\n")
        self.lane("init", "--setup", f"{sys.executable} {script}; exit 1")
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lane.json no longer names the lane", p.stderr)
        self.assertNotIn("setup failed in", p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertEqual(self.lane_json("chart-fix")["path"], "/elsewhere")

    def test_a_failed_worktree_add_drops_the_pending_marker(self):
        self.git("branch", "chart-fix")  # `worktree add -b chart-fix` fails on it
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("git worktree add failed", p.stderr)
        self.assertEqual(marks(self, "chart-fix"), [])
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "chart-fix")))

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


class CredentialRemote(LanesRepo):
    """origin served over http with a Basic credential only a helper gives (_http_remote): the
    store fetches run under sync_env, with no global or system config, so they get the
    credential.* keys of those two scopes alone, read fresh each run (Hayden's pick,
    2026-11-03). The rest of the global config stays off, and no repo or worktree config feeds
    a credential key."""

    def setUp(self):
        super().setUp()
        self.remote = Remote(self.tmp)
        self.addCleanup(self.remote.close)
        self.env.update(no_proxy="127.0.0.1", NO_PROXY="127.0.0.1")
        self.helper_log = os.path.join(self.tmp, "helper.log")
        self.git("remote", "set-url", "origin", f"{self.remote.url}/origin.git")
        self.global_config = os.path.join(self.home, ".gitconfig")

    def credential(self, section, path=None):
        """The fake helper under [section] in path's config (the global one by default)."""
        self.write(path or self.global_config,
                   f"[{section}]\n\thelper = \"{helper_script(self.helper_log)}\"\n")

    def test_the_url_form_helper_reaches_the_store_fetch(self):
        self.credential(f'credential "{self.remote.url}"')
        p = driven(self, "http", "new", "chart-fix")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("verified", p.stdout + p.stderr)
        self.assertGreater(self.remote.authorized, 0)
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def test_the_plain_helper_reaches_the_store_fetch(self):
        self.credential("credential")
        p = driven(self, "http", "new", "chart-fix")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def test_without_a_helper_the_store_fetch_fails(self):
        # The control: the remote does refuse a fetch with no credential.
        os.makedirs(os.path.join(self.tmp, "anon"))
        p = subprocess.run(["git", "ls-remote", f"{self.remote.url}/origin.git"],
                           cwd=os.path.join(self.tmp, "anon"),
                           env=dict(self.env, GIT_TERMINAL_PROMPT="0"),
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertGreater(self.remote.refused, 0)

    def test_repo_and_worktree_config_feed_no_credential(self):
        # Each lane's sandbox can write a worktree's config.worktree, and the common dir's config
        # is the repo's own: only the global and system scopes, which no lane can write, count.
        # The user's own git (ls-remote, the fetch into the shared repo) reads the repo config
        # and passes; the store fetch must not.
        url = f'credential "{self.remote.url}"'
        self.git("config", "extensions.worktreeConfig", "true")
        for where in ("config", "config.worktree"):
            with self.subTest(where=where):
                path = os.path.join(self.common, where)
                old = self.read(path) if os.path.exists(path) else ""
                self.write(path, old + f"[{url}]\n\thelper = \"{helper_script(self.helper_log)}\"\n")
                try:
                    p = driven(self, "http", "new", "chart-fix")
                    self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                    self.assertIn("the fetch of origin/main", p.stderr)
                    self.assertFalse(os.path.exists(self.lane_path("chart-fix")))
                finally:
                    self.write(path, old)

    def test_the_rest_of_the_global_config_stays_off(self):
        # A url.<base>.insteadOf in the global config would aim the store fetch elsewhere: only
        # credential.* keys come through.
        other = os.path.join(self.tmp, "other.git")
        self.git("clone", "-q", "--bare", self.origin, other, cwd=self.tmp)
        self.write(self.global_config,
                   f"[credential]\n\thelper = \"{helper_script(self.helper_log)}\"\n"
                   f"[url \"{other}\"]\n\tinsteadOf = {self.remote.url}/origin.git\n")
        # The user's own git follows insteadOf (to a local path, no credential); the store
        # fetch must still go to the http remote.
        authorized = self.remote.authorized
        p = driven(self, "http", "new", "chart-fix")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertGreater(self.remote.authorized, authorized)


class WindowDemotion(LanesRepo):
    """An install whose live settings.json lacked either rule that keeps lanes out of the
    verified dir (a reinstall from an older dotclaude) left a window in which any lane's sandbox
    could write there: a marker claiming a checkout passed `new`'s check would then let `adopt`
    run the setup sandbox-off in an unverified tree. setup.sh then runs demote_marks (Hayden's
    pick, 2026-11-03): every marker becomes pending, and what is no regular file there goes."""

    def setUp(self):
        super().setUp()
        self.mod = load_lane_script()
        self.verified = os.path.join(self.home, ".local", "state", "dotclaude", "verified")
        self.marks_dir = os.path.join(self.verified, "new-lanes")

    def demote(self):
        return self.mod.demote_marks(self.home)

    def test_a_verified_marker_no_longer_lets_adopt_finish(self):
        NewVerifiesTree.failed_setup(self)
        (mark,) = marks(self, "chart-fix")
        before = json.loads(self.read(mark))
        self.assertIs(before["verified"], True)  # the control: adopt would finish on this
        said = self.demote()
        self.assertEqual(json.loads(self.read(mark)), dict(before, verified=False))
        self.assertTrue(any("chart-fix" in s for s in said), said)
        self.write(os.path.join(self.lane_path("chart-fix"), "OK"), "")
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lane done chart-fix --abandon", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.lane_path("chart-fix"), "SETUP_RAN")))
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.demote(), [])  # a pending marker stays as it is

    def test_a_planted_marker_of_any_shape_goes_pending(self):
        os.makedirs(self.marks_dir)
        for name, body in (("k-a.json", "not json"), ("k-b.json", "[1]"),
                           ("k-c.json", '{"verified": true, "common": "/x"}')):
            self.write(os.path.join(self.marks_dir, name), body)
        said = self.demote()
        for name in ("k-a.json", "k-b.json", "k-c.json"):
            data = json.loads(self.read(os.path.join(self.marks_dir, name)))
            self.assertIs(data["verified"], False)
        self.assertEqual(json.loads(self.read(os.path.join(self.marks_dir, "k-c.json")))["common"],
                         "/x")
        self.assertEqual(len(said), 3, said)

    def test_what_is_no_regular_file_goes(self):
        os.makedirs(self.marks_dir)
        outside = os.path.join(self.tmp, "outside")
        self.write(outside, "mine\n")
        os.symlink(outside, os.path.join(self.marks_dir, "k-a.json"))
        os.symlink(outside, os.path.join(self.marks_dir, "k-a.lock"))
        os.mkfifo(os.path.join(self.marks_dir, "k-b.lock"))
        os.makedirs(os.path.join(self.marks_dir, "k-c.json", "sub"))
        self.write(os.path.join(self.marks_dir, "k-d.lock"), "")  # a real lock file stays
        os.mkfifo(os.path.join(self.verified, ".lock"))
        said = self.demote()
        self.assertEqual(sorted(os.listdir(self.marks_dir)), ["k-d.lock"])
        self.assertFalse(os.path.lexists(os.path.join(self.verified, ".lock")))
        self.assertEqual(self.read(outside), "mine\n")
        self.assertEqual(len(said), 5, said)

    def test_a_link_at_the_marks_dir_goes(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        self.write(os.path.join(outside, "k-a.json"), '{"verified": true}')
        os.makedirs(self.verified)
        os.symlink(outside, self.marks_dir)
        said = self.demote()
        self.assertFalse(os.path.lexists(self.marks_dir))
        self.assertEqual(self.read(os.path.join(outside, "k-a.json")), '{"verified": true}')
        self.assertEqual(len(said), 1, said)

    def test_names_come_out_masked(self):
        os.makedirs(self.marks_dir)
        self.write(os.path.join(self.marks_dir, "k-\x1b]0;x\x07.json"), "{}")
        (line,) = self.demote()
        self.assertNotIn("\x1b", line)

    def test_no_dir_no_work(self):
        self.assertEqual(self.demote(), [])

    def test_an_unreadable_marker_goes_pending_and_stops_nothing(self):
        # Review round 14: a mode-000 marker sorted first used to raise and leave the rest.
        os.makedirs(self.marks_dir)
        first = os.path.join(self.marks_dir, "k-0.json")
        self.write(first, '{"verified": true}')
        os.chmod(first, 0)
        self.write(os.path.join(self.marks_dir, "k-z.json"), '{"verified": true}')
        self.assertEqual(len(self.demote()), 2)
        os.chmod(first, 0o600)
        for name in ("k-0.json", "k-z.json"):
            self.assertIs(json.loads(self.read(os.path.join(self.marks_dir, name)))["verified"],
                          False)

    def test_a_failed_entry_keeps_the_flag_and_lane_refusing(self):
        # One entry that can't be removed (a dir holding a mode-000 dir) still lets every
        # marker go pending; the flag stays, so new, adopt and sync-main refuse meanwhile.
        os.makedirs(os.path.join(self.marks_dir, "k-a.json", "locked", "x"))
        locked = os.path.join(self.marks_dir, "k-a.json", "locked")
        os.chmod(locked, 0)
        self.addCleanup(lambda: os.path.isdir(locked) and os.chmod(locked, 0o700))
        self.write(os.path.join(self.marks_dir, "k-z.json"), '{"verified": true}')
        self.mod.open_window(self.home)
        with self.assertRaises(self.mod.LaneError) as e:
            self.demote()
        self.assertIn("k-a.json", str(e.exception))
        self.assertIs(json.loads(self.read(os.path.join(self.marks_dir, "k-z.json")))["verified"],
                      False)
        flag = os.path.join(self.verified, ".demote-pending")
        self.assertTrue(os.path.isfile(flag))
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(".demote-pending", p.stderr)
        os.chmod(locked, 0o700)
        self.demote()
        self.assertFalse(os.path.lexists(flag))
        self.lane("new", "chart-fix")

    def test_a_failed_demotion_leaves_the_flag_even_with_none_before(self):
        # Round 15: open_window failed (a full disk, say) and the demotion failed too; the
        # demotion makes the flag itself first, so the next install still retries.
        os.makedirs(os.path.join(self.marks_dir, "k-a.json", "locked", "x"))
        locked = os.path.join(self.marks_dir, "k-a.json", "locked")
        os.chmod(locked, 0)
        self.addCleanup(lambda: os.path.isdir(locked) and os.chmod(locked, 0o700))
        flag = os.path.join(self.verified, ".demote-pending")
        self.assertFalse(os.path.lexists(flag))
        with self.assertRaises(self.mod.LaneError) as e:
            self.demote()
        self.assertIn("keep refusing", str(e.exception))
        self.assertTrue(os.path.isfile(flag))

    def test_no_flag_at_all_says_nothing_refuses(self):
        os.makedirs(self.marks_dir)
        real = os.open

        def no_flag(path, *a, **k):
            if path == ".demote-pending":
                raise OSError(28, "No space left on device")
            return real(path, *a, **k)
        self.write(os.path.join(self.marks_dir, "k-z.json"), '{"verified": true}')
        with mock.patch.object(self.mod.os, "open", no_flag):
            with self.assertRaises(self.mod.LaneError) as e:
                self.demote()
        self.assertIn("nothing refuses", str(e.exception))
        self.assertIs(json.loads(self.read(os.path.join(self.marks_dir, "k-z.json")))["verified"],
                      False)

    def test_the_flag_refuses_adopt_until_the_demotion(self):
        # Between setup.sh's settings copy and its demotion, a planted verified marker would
        # pass store_rules: the flag open_window left before the copy refuses meanwhile.
        NewVerifiesTree.failed_setup(self)
        self.write(os.path.join(self.lane_path("chart-fix"), "OK"), "")
        self.mod.open_window(self.home)
        p = self.run_lane("adopt", self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(".demote-pending", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.lane_path("chart-fix"), "SETUP_RAN")))

    def test_open_window_replaces_what_is_no_file_never_following_it(self):
        os.makedirs(self.verified)
        flag = os.path.join(self.verified, ".demote-pending")
        victim = os.path.join(self.tmp, "victim")
        self.write(victim, "mine\n")
        for plant in (lambda: os.symlink(victim, flag), lambda: os.makedirs(flag + "/sub"),
                      lambda: os.mkfifo(flag)):
            plant()
            self.mod.open_window(self.home)
            st = os.lstat(flag)
            self.assertTrue(stat.S_ISREG(st.st_mode))
            self.assertEqual(self.read(victim), "mine\n")
            os.unlink(flag)


class FifoStoreLock(LanesRepo):
    """A FIFO planted at the stores' .lock (in a window, as WindowDemotion's) refuses at once:
    opened for writing without O_NONBLOCK, it would wait for a reader forever."""

    def test_new_refuses_a_fifo_lock(self):
        verified = os.path.join(self.home, ".local", "state", "dotclaude", "verified")
        os.makedirs(verified)
        os.mkfifo(os.path.join(verified, ".lock"))
        try:
            p = subprocess.run([sys.executable, LANE, "new", "chart-fix"], cwd=self.main,
                               env=self.env, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            self.fail("lane new waited on a FIFO at the stores' .lock")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(".lock", p.stderr)
        self.assertFalse(os.path.exists(self.lane_path("chart-fix")))


class CredentialConfig(unittest.TestCase):
    """credential_config: the credential.* keys of the system and global config, both global
    files, in git's own order, each value as the file has it; no include is followed."""

    def setUp(self):
        self.mod = load_lane_script()
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(HOME=self.tmp, XDG_CONFIG_HOME=os.path.join(self.tmp, ".config"))
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, rel, text):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_keys_values_and_order(self):
        inc = self.write("inc", "[credential]\n\thelper = included\n")
        self.write(".gitconfig",
                   "[credential]\n\tuseHttpPath\n\thelper =\n"
                   "[credential \"https://x.example/a=b\"]\n"
                   "\thelper = \"!f() { echo a=b; }; f\"\n"
                   "[user]\n\tname = me\n"
                   f"[include]\n\tpath = {inc}\n")
        self.write(".config/git/config", "[credential]\n\tusername = xdg\n")
        self.assertEqual(self.mod.credential_config(), [
            ("credential.username", "xdg"),  # git reads the XDG file first
            ("credential.usehttppath", "true"),
            ("credential.helper", ""),
            ("credential.https://x.example/a=b.helper", "!f() { echo a=b; }; f"),
        ])

    def test_only_system_and_global_scopes_count(self):
        # git runs from / with no GIT_*, so no repo scope shows up there today; the filter
        # holds should one ever reach the output (a /.git, say).
        out = b"".join(b"%s\0credential.helper\n%s\0" % (scope, scope) for scope in
                       (b"system", b"global", b"local", b"worktree", b"command"))
        seen = {}

        def run(args, **k):
            seen.update(k)
            return subprocess.CompletedProcess(args, 0, out, b"")
        with mock.patch.object(self.mod.subprocess, "run", run):
            self.assertEqual(self.mod.credential_config(),
                             [("credential.helper", "system"), ("credential.helper", "global")])
        self.assertEqual(seen["cwd"], "/")

    def test_a_git_without_show_scope_says_so(self):
        def run(args, **k):
            return subprocess.CompletedProcess(args, 129, b"", b"error: unknown option\n")
        with mock.patch.object(self.mod.subprocess, "run", run):
            with self.assertRaises(self.mod.LaneError) as e:
                self.mod.credential_config()
        self.assertIn("git 2.26", str(e.exception))

    def test_no_config_gives_no_keys(self):
        self.assertEqual(self.mod.credential_config(), [])

    def test_an_inherited_git_env_changes_nothing(self):
        # Every inherited GIT_* is dropped, as sgit drops it: GIT_CONFIG_GLOBAL can't swap the
        # file, and GIT_CONFIG_PARAMETERS or GIT_CONFIG_COUNT can't add a key.
        self.write(".gitconfig", "[credential]\n\thelper = mine\n")
        other = self.write("other", "[credential]\n\thelper = other\n")
        with mock.patch.dict(os.environ, GIT_CONFIG_GLOBAL=other,
                             GIT_CONFIG_PARAMETERS="'credential.username=p'",
                             GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="credential.username",
                             GIT_CONFIG_VALUE_0="c"):
            self.assertEqual(self.mod.credential_config(), [("credential.helper", "mine")])

    def test_a_broken_global_config_refuses(self):
        self.write(".gitconfig", "[credential\n")
        with self.assertRaises(self.mod.LaneError) as e:
            self.mod.credential_config()
        self.assertIn("bad config line 1", str(e.exception))

    def test_sync_env_carries_them_after_its_own(self):
        env = self.mod.sync_env("/store", config=[("credential.helper", ""),
                                                  ("credential.helper", "x=y")])
        n = int(env["GIT_CONFIG_COUNT"])
        pairs = [(env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(n)]
        self.assertEqual(pairs[-2:], [("credential.helper", ""), ("credential.helper", "x=y")])
        self.assertIn(("gc.auto", "0"), pairs)
        with self.assertRaises(ValueError):
            self.mod.sync_env("/store", config=[("gc.auto", "1")])


if __name__ == "__main__":
    unittest.main()
