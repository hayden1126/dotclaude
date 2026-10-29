"""skills/lanes/scripts/lane: the board's overlap flag (live lanes whose changed files meet), the
git `ls` and `done` run in a lane, sandbox-off, kept from running what the lane can configure,
and `lane trial` (the suites on a merge with every other live lane).

Each guard has a test that fails with the guard taken out, and each trap is shown to fire without
it: a trap that never fires proves nothing."""
import contextlib
import errno
import fcntl
import glob
import importlib.machinery
import importlib.util
import io
import json
import os
import shlex
import shutil
import signal
import subprocess
import time
import sys
import tempfile
import unittest
from unittest import mock

from _fixture import HANDOFF_CHECK, LANE, LanesRepo
from test_cli import load_lane_script

import lanelib  # on sys.path through _fixture

OLD = 1577836800  # 2020-01-01: an mtime that leaves a tracked file stat-dirty in the index
SUB = "vendored-mod"  # the planted submodule: a name no record names by accident


class LaneWork(LanesRepo):
    """Helpers for lanes with work in them, and for scripts that leave a marker when they run."""

    def new(self, lane_id):
        self.lane("new", lane_id)
        return self.lane_path(lane_id)

    def commit_files(self, cwd, names, msg="work"):
        for name in names:
            self.write(os.path.join(cwd, name), f"{name} in {os.path.basename(cwd)}\n")
        self.git("add", "--", *names, cwd=cwd)
        self.git("commit", "-q", "-m", msg, cwd=cwd)

    def trap(self, name, tail=""):
        """(an executable script that touches a marker, then runs tail; the marker's path)."""
        script, marker = os.path.join(self.tmp, name), os.path.join(self.tmp, name + "-ran")
        self.write(script, f"#!/bin/sh\ntouch {marker}\n{tail}")
        os.chmod(script, 0o755)
        return script, marker

    def rows(self):
        p = self.run_lane("ls", "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return {r["id"]: r for r in json.loads(p.stdout)}, p.stderr

    def ls(self):
        p = self.run_lane("ls")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return [line for line in p.stdout.splitlines() if line.startswith("overlap: ")], p.stderr

    def lane_status(self, cwd, *args):
        """A plain `git status` in the lane, as anything without the guards would run it."""
        subprocess.run(["git", "status", "--porcelain", *args], cwd=cwd, capture_output=True,
                       env=dict(self.env, GIT_COMMON_DIR=self.common), timeout=60)

    def plant_submodule(self, cwd):
        """An absorbed submodule SUB in the lane at cwd, committed there; returns its git dir (in
        the lane's admin dir, so the lane can write its config). Planted without GIT_COMMON_DIR,
        which would redirect the `git config` to the common dir."""
        sub = os.path.join(self.tmp, "sub")
        self.git("init", "-q", "-b", "main", sub, cwd=self.tmp)
        self.commit("f.txt", "sub\n", cwd=sub)
        self.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", sub, SUB, cwd=cwd)
        self.git("commit", "-q", "-m", "add s", cwd=cwd)
        return self.git("rev-parse", "--path-format=absolute", "--git-dir",
                        cwd=os.path.join(cwd, SUB)).strip()

    def hook_in_lane(self, cwd):
        """A post-index-change hook in the lane's own hk/, which a relative core.hooksPath in
        the common config runs from the lane's worktree; returns its marker."""
        script, marker = self.trap("post-index-change-hook")
        os.makedirs(os.path.join(cwd, "hk"))
        os.rename(script, os.path.join(cwd, "hk", "post-index-change"))
        self.git("config", "core.hooksPath", "hk")
        return marker


class Overlap(LaneWork):
    def test_two_lanes_committing_one_file_both_flag_overlap_and_the_footer_names_it(self):
        alpha, beta = self.new("alpha"), self.new("beta")
        self.commit_files(alpha, ["shared.txt", "only-alpha.txt"])
        self.commit_files(beta, ["shared.txt"])
        rows, err = self.rows()
        self.assertIn("overlap", rows["alpha"]["flags"])
        self.assertIn("overlap", rows["beta"]["flags"])
        self.assertEqual(rows["alpha"]["overlaps"], {"beta": ["shared.txt"]})
        self.assertEqual(rows["beta"]["overlaps"], {"alpha": ["shared.txt"]})
        self.assertNotIn("may be short", err)
        lines, _ = self.ls()
        self.assertEqual(lines, ["overlap: alpha and beta both change shared.txt"])

    def test_the_footer_names_five_files_then_counts_the_rest(self):
        alpha, beta = self.new("alpha"), self.new("beta")
        names = [f"f{i}.txt" for i in range(7)]
        self.commit_files(alpha, names)
        self.commit_files(beta, names)
        lines, _ = self.ls()
        self.assertEqual(lines, ["overlap: alpha and beta both change f0.txt, f1.txt, f2.txt, "
                                 "f3.txt, f4.txt (and 2 more)"])
        self.assertEqual(self.rows()[0]["alpha"]["overlaps"], {"beta": names})

    def test_modified_staged_and_untracked_files_count(self):
        alpha, beta = self.new("alpha"), self.new("beta")
        self.write(os.path.join(alpha, "README.md"), "changed in alpha\n")  # modified
        self.write(os.path.join(beta, "README.md"), "changed in beta\n")
        self.git("add", "README.md", cwd=beta)  # staged
        self.write(os.path.join(alpha, "notes", "new.txt"), "untracked\n")  # untracked, new dir
        self.commit_files(beta, ["notes/new.txt"])
        rows, err = self.rows()
        self.assertEqual(rows["alpha"]["overlaps"], {"beta": ["README.md", "notes/new.txt"]})
        self.assertEqual(rows["beta"]["overlaps"], {"alpha": ["README.md", "notes/new.txt"]})
        self.assertNotIn("may be short", err)

    def test_disjoint_lanes_dont_flag(self):
        # Each lane's own .lane/ record is excluded, so two fresh lanes never meet there.
        alpha, beta = self.new("alpha"), self.new("beta")
        self.commit_files(alpha, ["a.txt"])
        self.commit_files(beta, ["b.txt"])
        self.write(os.path.join(alpha, "loose.txt"), "x\n")
        rows, _ = self.rows()
        for lane_id in ("alpha", "beta"):
            self.assertNotIn("overlap", rows[lane_id]["flags"])
            self.assertEqual(rows[lane_id]["overlaps"], {})
        self.assertEqual(self.ls()[0], [])

    def test_a_stale_lane_is_left_out(self):
        alpha, beta = self.new("alpha"), self.new("beta")
        self.commit_files(alpha, ["shared.txt"])
        self.commit_files(beta, ["shared.txt"])
        self.git("worktree", "remove", "--force", beta)  # its branch keeps the commit
        rows, _ = self.rows()
        self.assertIn("stale", rows["beta"]["flags"])
        for lane_id in ("alpha", "beta"):
            self.assertNotIn("overlap", rows[lane_id]["flags"])
            self.assertEqual(rows[lane_id]["overlaps"], {})

    def test_main_s_later_commits_and_a_merged_lane_drop_out(self):
        alpha, beta = self.new("alpha"), self.new("beta")
        self.commit_files(beta, ["shared.txt"])
        self.git("push", "-q", "origin", "beta:main", cwd=beta)  # beta's PR merged
        self.git("pull", "-q", "--ff-only", "origin", "main")
        self.commit_files(self.main, ["later.txt"])  # main moves on past both lanes
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", "origin")
        self.commit_files(alpha, ["shared.txt"])
        gamma = self.new("gamma")
        self.commit_files(gamma, ["later.txt"])
        rows, _ = self.rows()
        self.assertEqual(rows["beta"]["overlaps"], {})  # all its work is in origin/main
        self.assertEqual(rows["alpha"]["overlaps"], {})  # never touched later.txt
        self.assertEqual(rows["gamma"]["overlaps"], {})


class OverlapGuards(LaneWork):
    """The status `ls` runs in each lane, sandbox-off: nothing the lane can configure runs."""

    def test_a_stat_dirty_lanes_index_is_left_alone_and_its_hook_never_runs(self):
        alpha = self.new("alpha")
        marker = self.hook_in_lane(alpha)
        index = self.git("rev-parse", "--path-format=absolute", "--git-path", "index",
                         cwd=alpha).strip()
        os.utime(os.path.join(alpha, "README.md"), (OLD, OLD))  # a plain status rewrites the index
        with open(index, "rb") as f:
            before = f.read(), os.stat(index).st_mtime_ns
        _, err = self.rows()
        self.assertNotIn("may be short", err)  # the status ran
        with open(index, "rb") as f:
            self.assertEqual((f.read(), os.stat(index).st_mtime_ns), before)
        self.assertFalse(os.path.exists(marker))
        self.lane_status(alpha)  # the trap is real
        self.assertTrue(os.path.exists(marker))

    def test_a_planted_submodules_own_config_never_runs(self):
        # Its config sits in the lane's admin dir, which the lane can write. The -c that turns
        # off fsmonitor reaches a submodule's status too; only --ignore-submodules=all keeps
        # git from re-hashing the submodule's stat-dirty file through its own clean filter.
        alpha = self.new("alpha")
        gitdir = self.plant_submodule(alpha)
        fsmonitor, fsmonitor_ran = self.trap("fsmonitor")
        clean, clean_ran = self.trap("clean", "cat\n")
        self.git("config", "--file", os.path.join(gitdir, "config"), "core.fsmonitor", fsmonitor)
        self.git("config", "--file", os.path.join(gitdir, "config"), "filter.x.clean", clean)
        self.write(os.path.join(alpha, SUB, ".gitattributes"), "* filter=x\n")
        os.utime(os.path.join(alpha, SUB, "f.txt"), (OLD, OLD))
        self.rows()
        self.ls()
        self.assertFalse(os.path.exists(fsmonitor_ran))
        self.assertFalse(os.path.exists(clean_ran))
        self.lane_status(alpha)  # both traps are real
        self.assertTrue(os.path.exists(fsmonitor_ran))
        self.assertTrue(os.path.exists(clean_ran))

    def skipped(self, setup, why):
        """Two lanes sharing a committed file and an untracked one; setup(alpha, beta) makes
        alpha's uncommitted read unsafe. Its committed set stays, its untracked file goes
        unread, and `ls` warns once for it, naming why."""
        alpha, beta = self.new("alpha"), self.new("beta")
        self.commit_files(alpha, ["shared.txt"])
        self.commit_files(beta, ["shared.txt"])
        for path in (alpha, beta):
            self.write(os.path.join(path, "loose.txt"), "x\n")
        setup(alpha, beta)
        rows, err = self.rows()
        self.assertEqual(rows["alpha"]["overlaps"], {"beta": ["shared.txt"]})
        self.assertIn("overlap", rows["alpha"]["flags"])
        warns = [line for line in err.splitlines() if "may be short" in line]
        self.assertEqual(len([w for w in warns if "lane alpha " in w]), 1, err)
        self.assertIn("its uncommitted files went unread", warns[0])
        self.assertIn(why, warns[0])
        return warns

    def test_a_configured_clean_filter_skips_the_uncommitted_read(self):
        # The lane picks the filter by its own .gitattributes, and status would run it on a
        # stat-dirty file.
        clean, ran = self.trap("clean", "cat\n")

        def setup(alpha, beta):
            self.git("config", "filter.x.clean", clean)
            self.write(os.path.join(alpha, ".gitattributes"), "* filter=x\n")
            os.utime(os.path.join(alpha, "README.md"), (OLD, OLD))

        warns = self.skipped(setup, "a filter's clean or process command is configured")
        self.assertEqual(len(warns), 2)  # the config is the repo's, so beta's goes unread too
        self.assertFalse(os.path.exists(ran))
        self.lane_status(self.lane_path("alpha"))  # the trap is real
        self.assertTrue(os.path.exists(ran))

    def test_a_filter_process_command_skips_the_uncommitted_read(self):
        self.skipped(lambda alpha, beta: self.git("config", "filter.lfs.process", "true"),
                     "a filter's clean or process command is configured")

    def test_per_worktree_config_skips_the_uncommitted_read(self):
        self.skipped(lambda alpha, beta: self.git("config", "extensions.worktreeConfig", "true"),
                     "extensions.worktreeConfig")

    def test_a_failing_worktree_problem_skips_the_uncommitted_read(self):
        # Sandboxed Bash can write lane.json: its path here reaches the lane through a link.
        def setup(alpha, beta):
            link = os.path.join(self.tmp, "alpha-link")
            os.symlink(alpha, link)
            record = os.path.join(self.common, "lanes", "alpha", "lane.json")
            self.write(record, json.dumps(dict(self.lane_json("alpha"), path=link)))

        warns = self.skipped(setup, "is reached through a symlink")
        self.assertEqual(len(warns), 1)
        self.assertEqual(self.rows()[0]["beta"]["overlaps"], {"alpha": ["shared.txt"]})

    def test_an_inherited_git_variable_changes_nothing(self):
        # A GIT_DIR or GIT_INDEX_FILE from the caller would point the sandbox-off git elsewhere.
        lane_mod = load_lane_script()
        alpha = self.new("alpha")
        self.commit_files(alpha, ["shared.txt"])
        self.write(os.path.join(alpha, "loose.txt"), "x\n")
        other = os.path.join(self.tmp, "other")
        self.git("init", "-q", "-b", "main", other, cwd=self.tmp)
        self.commit("other.txt", "x\n", cwd=other)
        repo = lanelib.Repo(self.main, self.common)
        lane = self.lane_json("alpha")

        def changed(**extra):
            with mock.patch.dict(os.environ, dict(self.env, **extra), clear=True):
                return lane_mod.changed_files(repo, lane, "refs/remotes/origin/main",
                                              "refs/heads/alpha", repo.lanes(shared=True), False)

        self.assertEqual(changed(), ({"shared.txt", "loose.txt"}, None))
        self.assertEqual(changed(GIT_DIR=os.path.join(other, ".git")),
                         ({"shared.txt", "loose.txt"}, None))
        self.assertEqual(changed(GIT_INDEX_FILE=os.path.join(other, ".git", "index")),
                         ({"shared.txt", "loose.txt"}, None))

    def changed_in_process(self, lane_mod, lane_id):
        """changed_files for lane_id in this process, with the fixture's environment."""
        repo = lanelib.Repo(self.main, self.common)
        with mock.patch.dict(os.environ, self.env, clear=True):
            return lane_mod.changed_files(repo, self.lane_json(lane_id), "refs/remotes/origin/main",
                                          f"refs/heads/{lane_id}", repo.lanes(shared=True), False)

    def test_a_relative_fsmonitor_in_the_repo_config_never_runs_from_the_lane(self):
        # A relative core.fsmonitor resolves in the worktree git runs in: the lane's own file.
        alpha = self.new("alpha")
        script, ran = self.trap("fsmonitor-in-lane")
        os.rename(script, os.path.join(alpha, "fsm.sh"))
        self.git("config", "core.fsmonitor", "./fsm.sh")
        _, err = self.rows()
        self.assertNotIn("may be short", err)  # the status ran
        self.assertFalse(os.path.exists(ran))
        self.lane_status(alpha)  # the trap is real
        self.assertTrue(os.path.exists(ran))

    def test_the_status_takes_its_config_from_the_common_dir_even_after_a_swap(self):
        # The lane can repoint its admin dir's commondir after the gates read the config: the
        # status must not take a decoy's clean filter from there.
        lane_mod = load_lane_script()
        alpha = self.new("alpha")
        self.write(os.path.join(alpha, ".gitattributes"), "* filter=x\n")
        os.utime(os.path.join(alpha, "README.md"), (OLD, OLD))
        clean, ran = self.trap("decoy-clean", "cat\n")
        decoy = os.path.join(self.tmp, "decoy-common")
        shutil.copytree(self.common, decoy, symlinks=True,
                        ignore=shutil.ignore_patterns("worktrees", "lanes"))
        with open(os.path.join(decoy, "config"), "a") as f:
            f.write(f'[filter "x"]\n\tclean = {clean}\n')
        commondir = os.path.join(self.common, "worktrees", "alpha", "commondir")
        real = self.read(commondir)
        self.addCleanup(self.write, commondir, real)
        read_git = lane_mod.read_git

        def swap_after_the_gates(args, *rest, **kw):
            out = read_git(args, *rest, **kw)
            if args[:2] == ["config", "--get-regexp"]:
                self.write(commondir, decoy + "\n")
            return out

        with mock.patch.object(lane_mod, "read_git", side_effect=swap_after_the_gates):
            files, why = self.changed_in_process(lane_mod, "alpha")
        self.assertIsNone(why)
        self.assertIn(".gitattributes", files)
        self.assertFalse(os.path.exists(ran))
        subprocess.run(["git", "status", "--porcelain"], cwd=alpha, env=self.env,
                       capture_output=True, timeout=60)  # the trap is real
        self.assertTrue(os.path.exists(ran))

    def test_every_git_behind_the_flag_runs_with_no_transport(self):
        lane_mod = load_lane_script()
        alpha = self.new("alpha")
        self.commit_files(alpha, ["shared.txt"])
        envs = []

        def record(args, cwd, **kw):
            envs.append(kw.get("env"))
            return lanelib.git(args, cwd, **kw)

        with mock.patch.object(lane_mod, "git", side_effect=record):
            files, _ = self.changed_in_process(lane_mod, "alpha")
        self.assertIn("shared.txt", files)
        self.assertEqual(len(envs), 3)  # the diff, the filter config, the status
        for env in envs:
            self.assertEqual((env.get("GIT_NO_LAZY_FETCH"), env.get("GIT_ALLOW_PROTOCOL")),
                             ("1", "none"))

    def test_a_git_failure_never_fails_the_board(self):
        # A base ref that doesn't resolve: each lane's commits go unread, and `ls` still shows.
        alpha, beta = self.new("alpha"), self.new("beta")
        for path in (alpha, beta):
            self.write(os.path.join(path, "loose.txt"), "x\n")
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        rows, err = self.rows()
        self.assertEqual(rows["alpha"]["overlaps"], {"beta": ["loose.txt"]})
        self.assertIn("overlap for lane alpha may be short: its commits went unread", err)


class DoneStatus(LaneWork):
    """`done` and handoff-check run git status in the lane, sandbox-off under `done`: it runs
    nothing the lane's own config names."""

    def setUp(self):
        super().setUp()
        self.path = self.new("alpha")

    def submodule_traps(self):
        """A planted submodule whose own config sets core.fsmonitor and a clean filter its
        .gitattributes routes a stat-dirty file to; returns both markers. The -c (or config from
        the environment) that turns fsmonitor off reaches the submodule's own status too, so the
        filter is what only the --ignore-submodules flag keeps from running."""
        gitdir = self.plant_submodule(self.path)
        fsmonitor, fsmonitor_ran = self.trap("fsmonitor")
        clean, clean_ran = self.trap("clean", "cat\n")
        self.git("config", "--file", os.path.join(gitdir, "config"), "core.fsmonitor", fsmonitor)
        self.git("config", "--file", os.path.join(gitdir, "config"), "filter.x.clean", clean)
        self.write(os.path.join(self.path, SUB, ".gitattributes"), "* filter=x\n")
        os.utime(os.path.join(self.path, SUB, "f.txt"), (OLD, OLD))
        return fsmonitor_ran, clean_ran

    def fsmonitor_in_lane(self, configure=True):
        """A relative core.fsmonitor in the repo's (protected) config, which resolves in the
        lane's worktree, to the lane's own fsm.sh, committed; returns its marker. configure
        False leaves the setting to the caller."""
        script, ran = self.trap("fsmonitor-in-lane")
        os.rename(script, os.path.join(self.path, "fsm.sh"))
        self.git("add", "fsm.sh", cwd=self.path)
        self.git("commit", "-q", "-m", "fsm", cwd=self.path)
        if configure:
            self.git("config", "core.fsmonitor", "./fsm.sh")
        return ran

    def test_done_refuses_a_submodule_without_running_its_config(self):
        markers = self.submodule_traps()
        p = self.run_lane("done", "alpha", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("worktree has submodules", p.stderr)
        self.assertEqual([os.path.exists(m) for m in markers], [False, False])
        self.assertTrue(os.path.isdir(self.path))
        self.lane_status(self.path, "--ignore-submodules=none")  # the traps are real
        self.assertEqual([os.path.exists(m) for m in markers], [True, True])

    def test_removable_never_runs_a_relative_fsmonitor(self):
        lane_mod = load_lane_script()
        ran = self.fsmonitor_in_lane()
        with mock.patch.dict(os.environ, dict(self.env, GIT_COMMON_DIR=self.common), clear=True):
            lane_mod.removable("alpha", self.path)
        self.assertFalse(os.path.exists(ran))
        self.lane_status(self.path)  # the trap is real
        self.assertTrue(os.path.exists(ran))

    def test_done_never_runs_a_relative_fsmonitor(self):
        # `git worktree remove` runs a status in the lane of its own, past any -c of ours.
        ran = self.fsmonitor_in_lane()
        self.assertIn("closed", self.lane("done", "alpha", "--abandon"))
        self.assertFalse(os.path.exists(ran))

    def test_done_never_runs_a_relative_fsmonitor_its_caller_configures(self):
        # git reads GIT_CONFIG_PARAMETERS after any GIT_CONFIG_COUNT entries: done's own setting
        # has to come last there, or an inherited one wins in the remove's status.
        ran = self.fsmonitor_in_lane(configure=False)
        inherited = "'core.fsmonitor'='./fsm.sh'"
        subprocess.run(["git", "status"], cwd=self.path, capture_output=True, timeout=60,
                       env=dict(self.env, GIT_CONFIG_PARAMETERS=inherited))
        self.assertTrue(os.path.exists(ran))  # the trap is real
        os.unlink(ran)
        self.env["GIT_CONFIG_PARAMETERS"] = inherited
        self.assertIn("closed", self.lane("done", "alpha", "--abandon"))
        self.assertFalse(os.path.exists(ran))

    def test_handoff_check_never_runs_a_relative_fsmonitor(self):
        ran = self.fsmonitor_in_lane()
        p = self.handoff_check()
        self.assertIn(p.returncode, (0, 1), p.stderr)
        self.assertFalse(os.path.exists(ran))
        # Its check that HEAD carries the record runs git in the lane too (only when the record
        # is older than HEAD's commit, so called here directly).
        loader = importlib.machinery.SourceFileLoader("handoff_check", HANDOFF_CHECK)
        hc = importlib.util.module_from_spec(importlib.util.spec_from_loader("handoff_check",
                                                                             loader))
        loader.exec_module(hc)
        with mock.patch.dict(os.environ, self.env, clear=True):
            hc.head_carries(lanelib.resolve(self.path), self.record("alpha"))
        self.assertFalse(os.path.exists(ran))
        self.lane_status(self.path)  # the trap is real
        self.assertTrue(os.path.exists(ran))

    def test_dones_status_never_writes_the_lanes_index(self):
        # A rewritten index fires post-index-change, which a relative core.hooksPath runs from
        # the lane. Committed, so the clean-tree check passes and the close goes ahead.
        marker = self.hook_in_lane(self.path)
        self.git("add", "hk", cwd=self.path)
        self.git("commit", "-q", "-m", "hk", cwd=self.path)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(marker)  # `git add` wrote the index, so it fired
        os.utime(os.path.join(self.path, "README.md"), (OLD, OLD))
        self.lane_status(self.path)  # the trap is real
        self.assertTrue(os.path.exists(marker))
        os.unlink(marker)
        os.utime(os.path.join(self.path, "README.md"), (OLD + 1, OLD + 1))
        self.assertIn("closed", self.lane("done", "alpha", "--abandon"))
        self.assertFalse(os.path.exists(marker))

    def handoff_check(self):
        return subprocess.run([sys.executable, HANDOFF_CHECK, "-C", self.path], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def test_handoff_check_never_runs_a_submodules_config(self):
        markers = self.submodule_traps()
        p = self.handoff_check()
        self.assertIn(p.returncode, (0, 1), p.stderr)
        self.assertEqual([os.path.exists(m) for m in markers], [False, False])
        self.lane_status(self.path, "--untracked-files=all")  # the traps are real
        self.assertEqual([os.path.exists(m) for m in markers], [True, True])

    def test_handoff_check_still_sees_a_moved_submodule_commit(self):
        # --ignore-submodules=dirty hides only what is inside the submodule's worktree.
        self.plant_submodule(self.path)
        sub = os.path.join(self.path, SUB)
        self.git("commit", "-q", "--allow-empty", "-m", "moved", cwd=sub)
        p = self.handoff_check()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("uncommitted and not named in the status file: " + SUB, p.stdout)

    def test_handoff_check_never_writes_the_lanes_index(self):
        marker = self.hook_in_lane(self.path)
        os.utime(os.path.join(self.path, "README.md"), (OLD, OLD))
        p = self.handoff_check()
        self.assertIn(p.returncode, (0, 1), p.stderr)
        self.assertFalse(os.path.exists(marker))
        self.lane_status(self.path)  # the trap is real
        self.assertTrue(os.path.exists(marker))


class FailingIds(unittest.TestCase):
    def test_unittest_lines_whole_and_pytest_ids_without_their_message(self):
        lane_mod = load_lane_script()
        lines = ["FAIL: test_x (a.B.test_x) (path='/tmp/t/tree')", "ERROR: test_y (a.B.test_y)",
                 "FAILED t.py::test_z - assert 1 == 2", "ERROR t.py::test_w",
                 "FAIL: test_x (a.B.test_x) (path='/tmp/t/tree')",  # once
                 "ERROR:root:a log line", "FAILED", "ok", "Ran 3 tests in 0.1s",
                 "FAILED (failures=12, skipped=4)", "FAILED (errors=1)"]  # unittest's summary
        self.assertEqual(lane_mod.failing_ids(lines),
                         ["FAIL: test_x (a.B.test_x) (path='/tmp/t/tree')",
                          "ERROR: test_y (a.B.test_y)", "t.py::test_z", "t.py::test_w"])

    def test_tap_failures_without_the_dash_parse_too(self):
        # The dash is optional in TAP: bats prints `not ok 1 name`. Unparsed, such a suite
        # would fall to the same-way rule and hide a second break behind a shared one.
        lane_mod = load_lane_script()
        self.assertEqual(lane_mod.failing_ids(["not ok 1 name one", "ok 2 fine",
                                               "not ok 3 skipped # SKIP no db"]),
                         ["not ok - name one"])

    def test_tap_failures_by_name_at_any_indent_without_their_number(self):
        # `node --test`, piped, prints TAP: a lane that adds a test shifts every number after
        # it, so the id drops the number. A TODO or SKIP directive is no failure.
        lane_mod = load_lane_script()
        lines = ["TAP version 13", "# Subtest: outer", "    not ok 1 - inner", "    ---",
                 "    error: 'boom'", "    ...", "not ok 3 - bad one", "ok 4 - fine",
                 "not ok 5 - later # TODO not yet", "not ok 6 - gone # skip on linux",
                 "not ok 9 - bad one", "not ok", "# fail 2"]
        self.assertEqual(lane_mod.failing_ids(lines), ["not ok - outer > inner",
                                                       "not ok - bad one"])

    def test_tap_ids_carry_the_enclosing_subtests(self):
        # node's `# Subtest: <name>` lines, by indent, name each failure's parents, so two
        # tests of one name under different parents stay apart. Plain TAP stays by name.
        lane_mod = load_lane_script()
        lines = ["# Subtest: P1", "    # Subtest: works", "    not ok 1 - works", "    1..1",
                 "not ok 1 - P1", "# Subtest: P2", "    # Subtest: works", "    ok 1 - works",
                 "    # Subtest: deep", "        # Subtest: works", "        not ok 1 - works",
                 "        1..1", "    not ok 2 - deep", "not ok 2 - P2"]
        self.assertEqual(lane_mod.failing_ids(lines),
                         ["not ok - P1 > works", "not ok - P1", "not ok - P2 > deep > works",
                          "not ok - P2 > deep", "not ok - P2"])
        self.assertEqual(lane_mod.failing_ids(["1..2", "ok 1 - a", "    not ok 1 - b",
                                               "not ok 2 - c"]),
                         ["not ok - b", "not ok - c"])


class Tee(unittest.TestCase):
    """run_child's teed output, in process: a short TEE_GRACE patched in, a SIGALRM watchdog in
    place of a hang (run_child sets signal handlers, so it runs on the main thread)."""

    def setUp(self):
        self.lane_mod = load_lane_script()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

        def hung(*_):
            raise TimeoutError("run_child never returned")

        self.addCleanup(signal.signal, signal.SIGALRM, signal.signal(signal.SIGALRM, hung))
        self.addCleanup(signal.alarm, 0)
        signal.alarm(30)

    def kill_at_cleanup(self):
        """A pid file for a process a suite backgrounds, which cleanup kills if it still runs."""
        pid_file = os.path.join(self.tmp, "bg.pid")

        def kill():
            if os.path.exists(pid_file):
                with contextlib.suppress(ProcessLookupError):  # it ended on its own
                    os.kill(int(self.read(pid_file)), signal.SIGKILL)

        self.addCleanup(kill)
        return pid_file

    def test_output_a_leftover_process_holds_is_cut_and_fails_the_suite(self):
        # The suite exits, but a process it backgrounded keeps the pipe past the grace: ids it
        # would still print are lost, so the run can't pass, even with ids that match.
        pid_file = self.kill_at_cleanup()
        cmd = f"sleep 30 & echo $! > {pid_file}; echo 'FAIL: test_x (t.T.test_x)'"
        out = io.StringIO()
        with mock.patch.object(self.lane_mod, "TEE_GRACE", 0.3), contextlib.redirect_stdout(out):
            runs = self.lane_mod.run_suites(self.tmp, [cmd], "merge", [0])
            again = {0: self.lane_mod.SuiteRun(1, ["FAIL: test_x (t.T.test_x)"])}
            rc = self.lane_mod.trial_report([cmd], runs, again)
        self.assertEqual(runs[0].ids, ["FAIL: test_x (t.T.test_x)"])
        self.assertTrue(runs[0].cut)
        self.assertEqual(rc, 1)
        self.assertIn("its output on the merge was cut (a process it started still holds it)",
                      out.getvalue())

    def test_a_cut_runs_late_output_stays_its_own(self):
        # Suite 1 leaves a process that writes a failing id after the grace, then ends its
        # stream, while suite 2 still runs: neither may land in suite 2's run.
        pid_file = self.kill_at_cleanup()
        late = "(sleep 0.5; echo 'FAIL: test_late (t.T.test_late)') & echo $! > " + pid_file
        with mock.patch.object(self.lane_mod, "TEE_GRACE", 0.2), \
                contextlib.redirect_stdout(io.StringIO()):
            first, second = self.lane_mod.run_suites(self.tmp, [late, "sleep 1.5; echo ok"],
                                                     "merge", [0, 1])
        self.assertTrue(first.cut)
        self.assertEqual((second.ids, second.cut), ([], False))

    def test_a_reader_that_ends_while_the_ids_are_read_never_reads_as_whole(self):
        # The reader may end in the window between reading the run's lines and asking whether
        # its stream ended. A stand-in run_child keeps its reader's callback, and failing_ids
        # (called on the copy of the lines) finishes that reader: a late id and the end.
        held = {}

        def child(command, cwd=None, on_line=None):
            held["on_line"] = on_line
            on_line("ok")
            return 0

        real = self.lane_mod.failing_ids

        def finish(lines):
            on_line = held.pop("on_line", None)
            if on_line:
                on_line("FAIL: test_late (t.T.test_late)")
                on_line(None)
            return real(lines)

        with mock.patch.object(self.lane_mod, "run_child", side_effect=child), \
                mock.patch.object(self.lane_mod, "failing_ids", side_effect=finish), \
                contextlib.redirect_stdout(io.StringIO()):
            (run,) = self.lane_mod.run_suites(self.tmp, ["x"], "merge", [0])
        self.assertTrue(run.cut or "FAIL: test_late (t.T.test_late)" in run.ids, run)

    def test_a_closed_stdout_stops_the_echo_but_never_the_drain(self):
        # More output than a pipe holds: a reader that stopped at the failed echo would leave
        # the command blocked on a full pipe, and run_child waiting on it.
        class Closed(io.StringIO):
            def write(self, s):
                raise BrokenPipeError(errno.EPIPE, "Broken pipe")

        lines = []
        with mock.patch.object(self.lane_mod.sys, "stdout", Closed()):
            rc = self.lane_mod.run_child(["sh", "-c", "seq 1 100000; echo 'FAIL: test_last "
                                          "(t.T.test_last)'"], on_line=lines.append)
        self.assertEqual(rc, 0)
        self.assertEqual(lines[-2:], ["FAIL: test_last (t.T.test_last)", None])

    def read(self, path):
        with open(path) as f:
            return f.read()


# A suite for the trial tests: fails test_ab only where both lanes' files meet.
BOTH = 'if [ -f a.txt ] && [ -f b.txt ]; then echo "FAIL: test_ab (t.T.test_ab)"; exit 1; fi'


class Trial(LaneWork):
    """`lane trial` from lane alpha, with beta (and sometimes gamma) live beside it. Its trees go
    in alpha's .lane-trial/, and TMPDIR is the test's own (the old trees' home, and still the
    lead notes' index's), so every scratch dir a run leaves is in sight."""

    def setUp(self):
        super().setUp()
        self.lane("init", "--locks", "suite")
        self.scratch = os.path.join(self.tmp, "scratch")
        os.makedirs(self.scratch)
        self.env["TMPDIR"] = self.scratch
        self.env["_LANE_TEST_SANDBOXED"] = "1"  # a trial refuses to run outside the sandbox
        self.alpha, self.beta = self.new("alpha"), self.new("beta")
        self.trial_dir = os.path.join(self.alpha, ".lane-trial")
        self.prefix = f"lane-trial-{lanelib.Repo(self.main, self.common).key}-alpha-"
        self.commit_files(self.alpha, ["a.txt"])
        self.commit_files(self.beta, ["b.txt"])

    def needs_base(self, lane_id, paths):
        """The line for a lane that conflicts with origin/main itself."""
        return (f"lane trial: lane {lane_id} conflicts with origin/main ({paths}): it needs to "
                "merge origin/main before a trial can tell whether it conflicts with this lane")

    def trial(self, *args, cwd=None):
        p = self.run_lane("trial", *args, cwd=cwd or self.alpha)
        return p.returncode, p.stdout, p.stderr

    def leftovers(self):
        """Scratch dirs (in TMPDIR, and in .lane-trial/ but its .gitignore) and registered trees
        a run left."""
        trees = [line for line in self.git("worktree", "list", "--porcelain").splitlines()
                 if line.startswith("worktree ") and (self.scratch in line
                                                     or self.trial_dir in line)]
        ours = os.listdir(self.trial_dir) if os.path.isdir(self.trial_dir) else []
        return sorted(os.listdir(self.scratch) + [x for x in ours if x != ".gitignore"]), trees

    def test_a_clean_trial_runs_each_suite_on_both_lanes_files_and_leaves_nothing(self):
        where, during = os.path.join(self.tmp, "where"), os.path.join(self.tmp, "during")
        rc, out, err = self.trial("--run", "test -f a.txt && test -f b.txt",
                                  "--run", f"pwd > {shlex.quote(where)}",
                                  "--run", f"git -C {shlex.quote(self.alpha)} status --porcelain "
                                           f"> {shlex.quote(during)}")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("lane trial: merged beta (", out)
        self.assertIn("suite 1 (test -f a.txt && test -f b.txt): ok", out)
        self.assertIn("suite 2", out)
        # In the lane, never under a temp root (a sandbox's policy treats those apart), and out
        # of the lane's git status, while the suites run and after.
        tree = self.read(where).strip()
        self.assertRegex(tree, rf"^{self.trial_dir}/{self.prefix}[a-z0-9_]{{8}}/tree$")
        self.assertEqual(self.read(os.path.join(self.trial_dir, ".gitignore")), "*\n")
        self.assertEqual(self.read(during), "")
        self.assertEqual(self.git("status", "--porcelain", cwd=self.alpha), "")
        self.assertEqual(self.leftovers(), ([], []))
        self.assertIn("other lanes' uncommitted work isn't in the merge", err)
        # Nothing moved: no ref names a trial commit, and alpha's branch is where it was.
        self.assertNotIn("lane trial", self.git("log", "--all", "--format=%s"))

    def test_a_lane_conflict_names_the_lane_and_path_and_fails(self):
        self.commit_files(self.alpha, ["shared.txt"])
        self.commit_files(self.beta, ["shared.txt"])
        gamma = self.new("gamma")
        self.commit_files(gamma, ["c.txt"])
        rc, out, err = self.trial("--run", "test -f c.txt && test ! -f b.txt")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane trial: conflict with lane beta: shared.txt", out)
        self.assertIn("merged gamma (", out)
        self.assertIn("suite 1 (test -f c.txt && test ! -f b.txt): ok", out)  # gamma went on
        self.assertIn("FAILED: lane beta didn't merge", out)
        self.assertEqual(self.leftovers(), ([], []))

    def test_a_conflict_between_two_other_lanes_names_them_not_this_lane(self):
        # beta and gamma change one file alpha never touches: gamma conflicts with beta (merged
        # first), not with alpha. delta's conflict is alpha's own, with beta merged before it.
        self.commit_files(self.beta, ["shared.txt"])
        gamma, delta = self.new("gamma"), self.new("delta")
        self.commit_files(gamma, ["shared.txt", "c.txt"])
        self.commit_files(delta, ["a.txt"])
        rc, out, err = self.trial("--run", "test -f b.txt")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane trial: lane gamma conflicts with lane beta (shared.txt), not with "
                      "this lane: gamma was left out; try it with this lane alone: lane trial "
                      "gamma --run 'test -f b.txt'", out)
        self.assertNotIn("conflict with lane gamma", out)
        self.assertIn("lane trial: conflict with lane delta: a.txt", out)
        self.assertIn("suite 1 (test -f b.txt): ok", out)

    def test_the_command_to_try_a_lane_alone_keeps_the_links(self):
        # Without the link the suite can't load, fails alike on both runs, and the same-way
        # rule would pass a trial that tested nothing.
        os.makedirs(os.path.join(self.alpha, "node_modules"))
        self.commit_files(self.beta, ["shared.txt"])
        gamma = self.new("gamma")
        self.commit_files(gamma, ["shared.txt", "c.txt"])
        rc, out, err = self.trial("--link", "node_modules", "--run", "test -f b.txt")
        self.assertIn("try it with this lane alone: lane trial gamma --link node_modules --run "
                      "'test -f b.txt'", out)

    def test_a_lane_behind_the_base_that_conflicts_with_it_is_its_own_to_merge(self):
        # main moved on in a file alpha never touches, and beta, branched before, changed it too.
        self.commit_files(self.main, ["shared.txt"])
        self.git("push", "-q", "origin", "main")
        self.commit_files(self.beta, ["shared.txt"])
        gamma = self.new("gamma")
        self.commit_files(gamma, ["c.txt"])
        # It is untried, never this lane's failure: the others' suites run, and it exits 0.
        rc, out, err = self.trial("--run", "test -f c.txt && test ! -f b.txt")
        self.assertEqual(rc, 0, out + err)
        self.assertIn(self.needs_base("beta", "shared.txt"), out)
        self.assertNotIn("conflict with lane beta", out)
        self.assertIn("lane trial: merged gamma (", out)
        self.assertIn("suite 1 (test -f c.txt && test ! -f b.txt): ok", out)
        self.assertNotIn("FAILED", out)
        self.assertEqual(out.splitlines()[-1],
                         "lane trial: lane beta untried (it conflicts with origin/main)")
        # One that conflicts with this lane too gets the base's verdict only (the known limit),
        # which claims nothing about this lane: its own trial, once it merges the base, finds
        # the rest.
        self.commit_files(self.alpha, ["g.txt"])
        self.commit_files(self.beta, ["g.txt"])
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 0, out + err)
        self.assertIn(self.needs_base("beta", "shared.txt"), out)

    def test_untried_lanes_beside_a_real_conflict_still_fail_it(self):
        gamma, delta = self.new("gamma"), self.new("delta")  # beta and gamma branch before main
        self.commit_files(self.main, ["shared.txt"])          # moves on
        self.push_main()
        self.commit_files(self.beta, ["shared.txt"])
        self.commit_files(gamma, ["shared.txt"])
        self.commit_files(delta, ["a.txt"])
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane trial: conflict with lane delta: a.txt", out)
        self.assertIn("FAILED: lane delta didn't merge", out)
        self.assertNotIn("FAILED: lanes", out)
        self.assertEqual(out.splitlines()[-1], "lane trial: lanes beta, gamma untried (they "
                                               "conflict with origin/main)")

    def test_alone_the_suites_run_on_this_lanes_head_plus_the_base(self):
        # beta conflicts with the base, so nothing merges: the suites still run, once, on
        # alpha's HEAD plus origin/main, and a failure there fails the trial.
        self.commit_files(self.main, ["shared.txt", "m.txt"])
        self.push_main()
        self.commit_files(self.beta, ["shared.txt"])
        head = ("lane trial: no other lane's work merged: running the suites on lane alpha's HEAD "
                "plus origin/main")
        rc, out, err = self.trial("--run", "test -f a.txt && test -f m.txt")
        self.assertEqual(rc, 0, out + err)
        self.assertIn(head, out)
        self.assertIn("suite 1 (test -f a.txt && test -f m.txt): ok", out)
        self.assertEqual(self.leftovers(), ([], []))
        fails = 'echo "FAIL: test_x (t.T.test_x)"; exit 1'
        rc, out, err = self.trial("--run", fails, "--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn(head, out)
        self.assertIn(f"suite 1 ({fails}): failed (exit 1):\n  FAIL: test_x (t.T.test_x)", out)
        self.assertIn("suite 2 (true): ok", out)
        self.assertNotIn("baseline run", out)  # the tree is the baseline already
        self.assertIn("lane trial: FAILED: 1 suite(s) fail on lane alpha plus origin/main", out)
        self.assertEqual(out.splitlines()[-1],
                         "lane trial: lane beta untried (it conflicts with origin/main)")
        self.assertEqual(self.leftovers(), ([], []))

    def test_with_no_other_lane_the_suites_still_run(self):
        self.env["_LANE_TEST_SANDBOXED"] = "0"  # `done` runs outside the sandbox, as it must
        self.lane("done", "beta", "--abandon")
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        rc, out, err = self.trial("--run", "test -f a.txt")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("no other lane's work merged: running the suites on lane alpha's HEAD", out)
        self.assertIn("suite 1 (test -f a.txt): ok", out)
        rc, out, err = self.trial("--run", "exit 4")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("suite 1 (exit 4): failed (exit 4)", out)
        self.assertIn("FAILED: 1 suite(s) fail on lane alpha plus origin/main", out)

    def test_a_lane_that_holds_the_base_still_leaves_a_base_conflict_to_the_other_lane(self):
        # alpha merged origin/main, so its HEAD conflicts with beta wherever main does: only a
        # merge with the base alone tells that shared.txt is main's change, never alpha's.
        self.commit_files(self.main, ["shared.txt"])
        self.git("push", "-q", "origin", "main")
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=self.alpha)
        self.commit_files(self.beta, ["shared.txt"])
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 0, out + err)
        self.assertIn(self.needs_base("beta", "shared.txt"), out)
        self.assertNotIn("conflict with lane beta", out)

    def edit_lines(self, cwd, name, edits):
        """Commit name in cwd with edits ({line number: text}) applied to its lines: the file as
        it is there, or a fresh one of 50 numbered lines, so hunks can sit far apart."""
        path = os.path.join(cwd, name)
        lines = (self.read(path).splitlines() if os.path.exists(path)
                 else [f"line {i}" for i in range(1, 51)])
        for n, text in edits.items():
            lines[n - 1] = text
        self.write(path, "\n".join(lines) + "\n")
        self.git("add", name, cwd=cwd)
        self.git("commit", "-q", "-m", f"edit {name}", cwd=cwd)

    def push_main(self):
        self.git("push", "-q", "origin", "main")

    def test_two_other_lanes_conflicting_in_a_file_this_lane_edits_elsewhere_are_named(self):
        # Case A: alpha edits line 5 of x.txt, beta and gamma both line 40. gamma conflicts
        # with beta, merged before it; the file alone would blame alpha.
        self.edit_lines(self.main, "x.txt", {})
        self.push_main()
        for lane in (self.alpha, self.beta):
            self.git("merge", "-q", "--no-edit", "origin/main", cwd=lane)
        gamma = self.new("gamma")
        self.edit_lines(self.alpha, "x.txt", {5: "alpha"})
        self.edit_lines(self.beta, "x.txt", {40: "beta"})
        self.edit_lines(gamma, "x.txt", {40: "gamma"})
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane trial: lane gamma conflicts with lane beta (x.txt), not with this "
                      "lane: gamma was left out", out)
        self.assertNotIn("conflict with lane gamma", out)

    def test_a_lane_behind_the_base_in_a_file_this_lane_edits_elsewhere_must_merge_it(self):
        # Case B: main edits line 1 of x.txt, alpha merges main and edits line 40, beta
        # (merged x.txt before main's edit) edits line 1: beta's to merge origin/main.
        self.edit_lines(self.main, "x.txt", {})
        self.push_main()
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=self.beta)
        self.edit_lines(self.main, "x.txt", {1: "main"})
        self.push_main()
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=self.alpha)
        self.edit_lines(self.alpha, "x.txt", {40: "alpha"})
        self.edit_lines(self.beta, "x.txt", {1: "beta"})
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 0, out + err)
        self.assertIn(self.needs_base("beta", "x.txt"), out)
        self.assertIn("lane beta untried (it conflicts with origin/main)", out)

    def test_a_lane_that_renames_a_file_this_lane_edits_conflicts_with_this_lane(self):
        # gamma renames old.txt to new.txt and edits line 10, which alpha edits too: git names
        # new.txt, a path alpha never changed, yet the conflict is alpha's. beta merges first.
        self.edit_lines(self.main, "old.txt", {})
        self.push_main()
        gamma = self.new("gamma")
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=self.alpha)
        self.edit_lines(self.alpha, "old.txt", {10: "alpha"})
        self.git("mv", "old.txt", "new.txt", cwd=gamma)
        self.edit_lines(gamma, "new.txt", {10: "gamma"})
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("merged beta (", out)
        self.assertRegex(out, r"lane trial: conflict with lane gamma: \S")

    def test_a_base_conflict_aborts_before_any_suite(self):
        self.commit_files(self.alpha, ["shared.txt"])
        self.commit_files(self.main, ["shared.txt"])
        self.git("push", "-q", "origin", "main")
        ran = os.path.join(self.tmp, "ran")
        rc, out, err = self.trial("--run", f"touch {shlex.quote(ran)}")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("origin/main doesn't merge cleanly into lane alpha (shared.txt): merge "
                      "origin/main into the lane first", err)
        self.assertFalse(os.path.exists(ran))
        self.assertEqual(self.leftovers(), ([], []))

    def carries(self, line="Lead branch: `lead` (the lead's STATUS commits)", carriers=None):
        """main's STATUS.md with line in it, and a branch lead three commits past it. Each
        (lane, n) in carriers (alpha the lead's first and beta its second by default) merges
        origin/main and carries the lead's commit n in a STATUS.md commit of its own, so the
        lead's head is no carry. Returns the lead's commits."""
        status = os.path.join(self.main, "STATUS.md")
        self.write(status, f"# Status\n\n{line}\n\nend\n")
        self.git("add", "STATUS.md")
        self.git("commit", "-q", "-m", "status")
        self.push_main()
        self.git("switch", "-q", "-c", "lead")
        heads = []
        for note in ("lead one", "lead two", "lead three"):
            self.write(status, self.read(status).replace("\nend\n", f"\n{note}\nend\n"))
            self.git("commit", "-q", "-am", note)
            heads.append(self.git("rev-parse", "HEAD").strip())
        self.git("switch", "-q", "main")
        for lane, n in carriers or ((self.alpha, 0), (self.beta, 1)):
            self.git("merge", "-q", "--no-edit", "origin/main", cwd=lane)
            self.carry(lane, heads[n])
        return heads

    def carry(self, lane, commit):
        self.git("checkout", commit, "--", "STATUS.md", cwd=lane)
        self.git("commit", "-q", "-m", "STATUS: the lead's notes", cwd=lane)

    NORMALIZED = "lane trial: STATUS.md is the lead's notes on lead ({}) in every merge, as a " \
                 "carry would make it"

    def assertStillConflicts(self, paths="STATUS.md"):
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn(f"lane trial: conflict with lane beta: {paths}", out)
        self.assertNotIn("as a carry would", out)
        self.assertNotIn("Traceback", err)

    def test_two_carries_of_the_lead_notes_merge_as_a_carry_would(self):
        # The merge order changed, so alpha and beta carry the lead's notes from two lead heads:
        # their STATUS.md always conflicts, and a carry takes the lead branch's whole.
        lead = self.carries()[2]
        got = os.path.join(self.tmp, "got")
        rc, out, err = self.trial("--run", "test -f b.txt",
                                  "--run", f"cp STATUS.md {shlex.quote(got)}")
        self.assertEqual(rc, 0, out + err)
        self.assertIn(self.NORMALIZED.format(lead[:12]), out)
        self.assertIn("lane trial: merged beta (", out)
        self.assertIn("suite 1 (test -f b.txt): ok", out)
        self.assertEqual(self.read(got), self.git("show", "lead:STATUS.md"))
        self.assertEqual(self.leftovers(), ([], []))

    def test_no_line_when_every_commit_holds_the_leads_status_already(self):
        # lead is main itself and both lanes merged it: nothing to set, so nothing to report.
        self.write(os.path.join(self.main, "STATUS.md"), "# Status\n\nLead branch: `lead`\n")
        self.git("add", "STATUS.md")
        self.git("commit", "-q", "-m", "status")
        self.push_main()
        self.git("branch", "lead")
        for lane in (self.alpha, self.beta):
            self.git("merge", "-q", "--no-edit", "origin/main", cwd=lane)
        rc, out, err = self.trial("--run", "test -f b.txt")
        self.assertEqual(rc, 0, out + err)
        self.assertNotIn("STATUS.md is the lead's notes", out)

    def test_a_status_conflict_beside_another_path_stays_a_conflict_in_that_path(self):
        self.carries()
        self.commit_files(self.alpha, ["shared.txt"])
        self.commit_files(self.beta, ["shared.txt"])
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane trial: conflict with lane beta: shared.txt", out)

    def test_a_status_with_no_lead_branch_line_stays_a_conflict(self):
        self.carries(line="Lead: none named")
        self.assertStillConflicts()

    def test_a_lead_branch_that_is_no_plain_branch_name_stays_a_conflict(self):
        # lead~1 resolves (to the lead's second commit), so only the name check stops it.
        self.carries(line="Lead branch: `lead~1` (a revision, not a branch)")
        self.assertStillConflicts()

    def test_a_missing_lead_branch_stays_a_conflict(self):
        self.carries()
        self.git("branch", "-q", "-D", "lead")
        self.assertStillConflicts()

    def test_a_lead_branch_without_a_status_file_stays_a_conflict(self):
        self.carries()
        self.git("switch", "-q", "lead")
        self.git("rm", "-q", "STATUS.md")
        self.git("commit", "-q", "-m", "no status")
        self.git("switch", "-q", "main")
        self.assertStillConflicts()

    def test_a_lead_branch_whose_status_is_a_directory_stays_a_conflict(self):
        self.carries()
        self.git("switch", "-q", "lead")
        self.git("rm", "-q", "STATUS.md")
        self.write(os.path.join(self.main, "STATUS.md", "x"), "x\n")
        self.git("add", "STATUS.md")
        self.git("commit", "-q", "-m", "status dir")
        self.git("switch", "-q", "main")
        self.assertStillConflicts()

    def assertNormalized(self, lead, *runs):
        rc, out, err = self.trial(*(runs or ("--run", "test -f b.txt")))
        self.assertEqual(rc, 0, out + err)
        self.assertIn(self.NORMALIZED.format(lead[:12]), out)
        self.assertNotIn("Traceback", err)
        return out

    def test_this_lane_without_a_status_file_takes_the_bases_line(self):
        # alpha deletes STATUS.md, beta carries: with no line on this lane's side, the base's
        # names the lead, and a carry would bring the file back.
        lead = self.carries()[2]
        self.git("rm", "-q", "STATUS.md", cwd=self.alpha)
        self.git("commit", "-q", "-m", "no status", cwd=self.alpha)
        self.assertNormalized(lead)

    def test_a_status_that_isnt_text_falls_back_to_the_bases_line(self):
        lead = self.carries()[2]
        with open(os.path.join(self.alpha, "STATUS.md"), "ab") as f:
            f.write(b"\xff\xfe not text\n")
        self.git("commit", "-q", "-am", "binary status", cwd=self.alpha)
        self.assertNormalized(lead)

    def test_a_lane_from_before_the_lead_line_takes_the_bases(self):
        # alpha merged main while its STATUS.md had no `Lead branch:` line and hasn't since;
        # beta and gamma carry two lead heads. The base's line settles their clash.
        gamma = self.new("gamma")
        self.write(os.path.join(self.main, "STATUS.md"), "# Status\n\nend\n")
        self.git("add", "STATUS.md")
        self.git("commit", "-q", "-m", "status without the line")
        self.push_main()
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=self.alpha)
        lead = self.carries(carriers=((self.beta, 0), (gamma, 1)))[2]
        out = self.assertNormalized(lead)
        self.assertNotIn("(STATUS.md)", out)
        self.assertIn("merged beta (", out)
        self.assertIn("gamma (", out)

    def test_the_trials_commits_carry_its_own_identity(self):
        # The fixture sets GIT_AUTHOR_* and GIT_COMMITTER_*, which would beat `-c user.name`.
        self.carries()
        rc, out, err = self.trial("--keep", "--run", "true")
        self.assertEqual(rc, 0, out + err)
        (tree,) = glob.glob(os.path.join(self.trial_dir, self.prefix + "*", "tree"))
        want = "lane-trial <lane-trial@localhost> | lane-trial <lane-trial@localhost>"
        for commit in ("HEAD", "HEAD^1", "HEAD^2"):  # the merge, and both STATUS.md commits
            self.assertEqual(self.git("log", "-1", "--format=%an <%ae> | %cn <%ce>", commit,
                                      cwd=tree).strip(), want, commit)
        self.assertIn("STATUS.md from lead", self.git("log", "-1", "--format=%s", "HEAD^2",
                                                      cwd=tree))
        self.git("worktree", "remove", "--force", tree)

    def test_a_carry_clash_beside_a_code_conflict_names_the_other_lane(self):
        # alpha and gamma carry two lead heads; gamma conflicts in x.txt with beta, merged
        # first, which carries nothing. The carries' clash must not make it alpha's conflict.
        gamma = self.new("gamma")
        self.edit_lines(self.main, "x.txt", {})
        self.carries(carriers=((self.alpha, 0), (gamma, 1)))
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=self.beta)
        self.edit_lines(self.beta, "x.txt", {40: "beta"})
        self.edit_lines(gamma, "x.txt", {40: "gamma"})
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane trial: lane gamma conflicts with lane beta (x.txt), not with this "
                      "lane: gamma was left out", out)
        self.assertNotIn("conflict with lane gamma", out)

    def test_the_pairs_never_name_a_lane_for_a_carry_clash(self):
        # beta carries the lead's first commit, gamma its second, and gamma's real conflict is
        # delta's x.txt: the pair with beta clashes only as carries do, so it isn't named.
        gamma, delta = self.new("gamma"), self.new("delta")
        self.edit_lines(self.main, "x.txt", {})
        self.carries(carriers=((self.alpha, 0), (self.beta, 0), (gamma, 1)))
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=delta)
        self.edit_lines(delta, "x.txt", {40: "delta"})
        self.edit_lines(gamma, "x.txt", {40: "gamma"})
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane trial: lane gamma conflicts with lane delta (x.txt), not with this "
                      "lane: gamma was left out", out)

    def test_a_pathless_conflict_beside_a_carry_clash_stays_a_conflict(self):
        # beta splits d/ evenly into e/ and f/ while alpha adds d/new.txt: merge-ort can't tell
        # where d/ went and names no path. Beside the carries' clash it still fails the merge.
        self.commit_files(self.main, [f"d/f{i}.txt" for i in range(1, 5)])
        self.carries()
        self.commit_files(self.alpha, ["d/new.txt"])
        for i, to in ((1, "e"), (2, "e"), (3, "f"), (4, "f")):
            os.makedirs(os.path.join(self.beta, to), exist_ok=True)
            self.git("mv", f"d/f{i}.txt", f"{to}/f{i}.txt", cwd=self.beta)
        self.git("commit", "-q", "-m", "split d", cwd=self.beta)
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane trial: conflict with lane beta: git named no path", out)
        self.assertIn("no other lane's work merged", out)

    def test_names_pass_the_lead_status_byte_for_byte(self):
        # The lead's STATUS.md goes in through a temporary index: no name passes through text,
        # so a carriage return or a name that isn't UTF-8 comes out as it went in.
        self.carries()
        names = [b"Icon\r", b"\xff.txt"]
        for name in names:
            with open(os.path.join(os.fsencode(self.alpha), name), "w") as f:
                f.write("x\n")
        self.git("add", "--", *map(os.fsdecode, names), cwd=self.alpha)
        self.git("commit", "-q", "-m", "odd names", cwd=self.alpha)
        listing = os.path.join(self.tmp, "names")
        rc, out, err = self.trial("--run", f"printf '%s\\0' * > {shlex.quote(listing)}")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("STATUS.md is the lead's notes", out)
        with open(listing, "rb") as f:
            got = f.read().split(b"\0")
        for name in names:
            self.assertIn(name, got)

    def test_a_carry_clash_with_the_base_no_longer_aborts(self):
        # main took a newer carry after alpha carried, so alpha's STATUS.md clashes with
        # origin/main's. gamma, which merged main before that, conflicts with beta in
        # shared.txt: the base's clash must not make it gamma's to merge origin/main either.
        gamma = self.new("gamma")
        heads = self.carries()
        self.git("merge", "-q", "--no-edit", "origin/main", cwd=gamma)
        self.carry(self.main, heads[1])
        self.push_main()
        self.commit_files(self.beta, ["shared.txt"])
        self.commit_files(gamma, ["shared.txt"])
        rc, out, err = self.trial("--run", "test -f b.txt")
        self.assertEqual(rc, 1, out + err)
        self.assertNotIn("doesn't merge cleanly", err)
        self.assertIn("lane trial: merged beta (", out)
        self.assertIn("suite 1 (test -f b.txt): ok", out)
        self.assertIn("lane trial: lane gamma conflicts with lane beta (shared.txt), not with "
                      "this lane", out)

    def test_a_conflict_in_a_name_that_isnt_utf8_stops_the_trial_with_no_traceback(self):
        # merge-tree names the conflicted file raw (-z), and a lane names its own files.
        for lane in (self.alpha, self.beta):
            with open(os.path.join(os.fsencode(lane), b"\xff.txt"), "w") as f:
                f.write(f"{os.path.basename(lane)}\n")
            self.git("add", "--", os.fsdecode(b"\xff.txt"), cwd=lane)
            self.git("commit", "-q", "-m", "odd name", cwd=lane)
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane: git merge-tree's output merging beta isn't UTF-8 (a lane names its "
                      "own files), so the trial stopped; `lane trial <id> ...` with the other "
                      "lanes' ids tries the rest", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.leftovers(), ([], []))

    def test_a_code_conflict_with_the_base_still_aborts_beside_the_lead_status(self):
        self.carries()
        self.commit_files(self.alpha, ["shared.txt"])
        self.commit_files(self.main, ["shared.txt"])
        self.push_main()
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("origin/main doesn't merge cleanly into lane alpha (shared.txt): merge "
                      "origin/main into the lane first", err)

    def test_a_merge_only_failure_fails_and_names_the_test(self):
        rc, out, err = self.trial("--run", BOTH, "--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("baseline run of suite 1/2", out)
        self.assertNotIn("baseline run of suite 2/2", out)  # only the failed suite reruns
        self.assertIn("suite 1 (" + BOTH + "): 1 failure(s) only on the merge:\n"
                      "  FAIL: test_ab (t.T.test_ab)", out)
        self.assertIn("suite 2 (true): ok", out)
        self.assertEqual(self.leftovers(), ([], []))

    def test_an_id_failing_on_the_baseline_too_passes_even_with_the_trees_path_in_it(self):
        # The baseline reruns at the same path, so a subtest id that embeds it matches.
        rc, out, err = self.trial("--run", 'echo "FAIL: test_where (t.T.test_where) '
                                           '(path=$PWD)"; exit 1')
        self.assertEqual(rc, 0, out + err)
        self.assertIn("every failure also fails on the baseline (exit 1 on the merge, 1 on the "
                      "baseline), so none is the merge's", out)
        self.assertRegex(out, r"FAIL: test_where \(t\.T\.test_where\) \(path=\S+/tree\)")

    def test_an_exit_worse_on_the_merge_fails_though_its_ids_fail_on_the_baseline_too(self):
        # A runner's id fails in both runs (the location), and a check chained after it, which
        # prints no id, fails only on the merge: the exit codes decide.
        where = 'echo "FAIL: test_where (t.T.test_where) (path=$PWD)"; '
        rc, out, err = self.trial("--run", where + "test ! -f b.txt")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("its ids fail on the baseline too, but it exits 1 on the merge and 0 on the "
                      "baseline, so a failure is the merge's", out)
        # A death by signal on the merge only, where the baseline exits non-zero.
        rc, out, err = self.trial("--run", where + "if [ -f b.txt ]; then kill -KILL $$; fi; "
                                  "exit 1")
        self.assertEqual(rc, 1, out + err)
        self.assertIn(f"it exits -{9} on the merge and 1 on the baseline", out)
        # Both exits alike: none is the merge's.
        rc, out, err = self.trial("--run", where + "exit 1")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("(exit 1 on the merge, 1 on the baseline), so none is the merge's", out)

    def test_a_failure_behind_a_zero_exit_still_counts(self):
        # `a; b` exits with b's code: the failing id a printed decides.
        rc, out, err = self.trial("--run", 'if [ -f b.txt ]; then echo "FAIL: test_b '
                                           '(t.T.test_b)"; fi; true')
        self.assertEqual(rc, 1, out + err)
        self.assertIn("1 failure(s) only on the merge", out)

    def test_a_failure_with_no_test_id_and_another_exit_on_the_baseline_is_compared_by_hand(self):
        rc, out, err = self.trial("--run", "if [ -f b.txt ]; then exit 2; fi; exit 1")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("failed (exit 2) with no test id on either run (exit 1 on the baseline)",
                      out)
        # No id on the merge, ids on the baseline: still by hand.
        rc, out, err = self.trial("--run", 'if [ ! -f b.txt ]; then echo "FAIL: test_x '
                                           '(t.T.test_x)"; fi; exit 1')
        self.assertEqual(rc, 1, out + err)
        self.assertIn("failed (exit 1) with no test id to compare against the baseline", out)

    def test_a_failure_with_no_test_id_on_either_run_is_compared_by_hand(self):
        # Even when both runs exit alike: a suite that never ran (a directory as `--run`, exit
        # 126 on both; a runner missing a flag, exit 2 on both) would pass a gate that can't
        # vouch for it.
        rc, out, err = self.trial("--run", "exit 3", "--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane trial: suite 1 (exit 3): failed (exit 3) with no test id on either "
                      "run (exit 3 on the baseline): the trial can't vouch for it, compare the "
                      "two runs above by hand", out)
        self.assertIn("lane trial: suite 2 (true): ok", out)
        rc, out, err = self.trial("--run", "./")  # the tree itself: a directory
        self.assertEqual(rc, 1, out + err)
        self.assertIn("failed (exit 126) with no test id on either run (exit 126 on the "
                      "baseline)", out)

    def test_tap_ids_judge_a_failure(self):
        # A merge-only TAP failure fails the trial; one the baseline repeats under another
        # number (beta's test comes first) passes.
        tap = ('if [ -f a.txt ] && [ -f b.txt ]; then echo "not ok 1 - ab"; exit 1; fi; '
               'echo "ok 1 - ab"')
        rc, out, err = self.trial("--run", tap)
        self.assertEqual(rc, 1, out + err)
        self.assertIn(f"suite 1 ({tap}): 1 failure(s) only on the merge:\n  not ok - ab", out)
        shifted = ('if [ -f b.txt ]; then echo "ok 1 - new"; echo "not ok 2 - old"; '
                   'else echo "not ok 1 - old"; fi; exit 1')
        rc, out, err = self.trial("--run", shifted)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("every failure also fails on the baseline", out)
        self.assertIn("  not ok - old", out)

    def test_a_leftover_tree_from_a_killed_run_is_cleared(self):
        # A run killed past its cleanup leaves its dir and its registration; only this repo's
        # lane's names go. Lane alpha-b's look alike, and so does another repo's lane alpha,
        # whose trial may be live: it shares the temp dir but not this repo's suite lock. A tree
        # an older `lane` left in the temp dir goes as one in .lane-trial/ does.
        stale = os.path.join(self.scratch, self.prefix + "abcd1234")
        ours = os.path.join(self.trial_dir, self.prefix + "efgh5678")
        for d in (stale, ours):
            self.git("worktree", "add", "--detach", "--quiet", os.path.join(d, "tree"), "HEAD",
                     cwd=self.alpha)
        loose = os.path.join(self.scratch, self.prefix + "zzzz9999")
        lane_b = self.prefix.removesuffix("alpha-") + "alpha-b-abcd1234"
        other_repo = "lane-trial-000000000000-alpha-abcd1234"
        for d in (loose, os.path.join(self.scratch, lane_b),
                  os.path.join(self.scratch, other_repo, "tree")):
            os.makedirs(d)
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("cleared the tree an earlier trial left registered", err)
        self.assertIn(os.path.join(stale, "tree"), err)
        self.assertIn(os.path.join(ours, "tree"), err)
        self.assertEqual(self.leftovers(), (sorted([lane_b, other_repo]), []))

    def test_a_leftover_it_cant_unregister_is_left_to_lane_done_never_a_remove_by_path(self):
        # Sandboxed, a trial can't unregister a tree the sandbox mounted (a lock stands in for
        # that here). A by-path `git worktree remove --force` resolves a symlink swapped in for
        # the tree and deletes whatever worktree it names, so the message never offers one.
        ours = os.path.join(self.trial_dir, self.prefix + "efgh5678", "tree")
        self.git("worktree", "add", "--detach", "--quiet", ours, "HEAD", cwd=self.alpha)
        self.git("worktree", "lock", ours, cwd=self.alpha)
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 0, out + err)
        self.assertIn(f"stays registered: {ours}", err)
        self.assertIn("`lane done alpha` clears", err)
        self.assertNotIn("remove --force", out + err)
        self.git("worktree", "unlock", ours, cwd=self.alpha)
        self.git("worktree", "prune", cwd=self.alpha)

    def test_it_refuses_to_run_outside_the_sandbox(self):
        # It removes its trees by path, safe only where the sandbox bounds what a symlink swapped
        # in for a tree could make git delete.
        self.env["_LANE_TEST_SANDBOXED"] = "0"
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("runs only inside the Bash sandbox", err)
        self.assertFalse(os.path.exists(self.trial_dir))

    def test_a_bad_or_nested_link_is_refused_before_the_lock(self):
        # Waiting on the suite lock (maybe a whole other trial) only to refuse a typo is waste.
        holder = subprocess.Popen([sys.executable, LANE, "lock", "suite", "--", "sleep", "30"],
                                  cwd=self.alpha, env=self.env, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.terminate)
        lock = os.path.join(self.common, "lanes", "_locks", "suite")
        deadline = time.monotonic() + 10
        while not (os.path.exists(lock) and self.read(lock)) and time.monotonic() < deadline:
            time.sleep(0.05)
        for args, want in ((["--link", "../x"], "bad trial link '../x'"),
                           (["--link", "a", "--link", "a/b"], "nested trial links: a/b is under a")):
            with self.subTest(args=args):
                rc, out, err = self.trial(*args, "--run", "true")
                self.assertEqual(rc, 1, out + err)  # not 75 or a wait: refused at once
                self.assertIn(want, err)

    def test_a_tree_it_cant_remove_is_reported_without_gits_words(self):
        # git's stderr can carry text a sandboxed process planted (a lock reason) and its own
        # "use 'remove -f -f'" advice, which pasted sandbox-off follows a swapped-in link.
        mod = load_lane_script()
        tmpdir = os.path.join(self.trial_dir, self.prefix + "zzzz0000")
        tree = os.path.join(tmpdir, "tree")
        self.git("worktree", "add", "--detach", "--quiet", tree, "HEAD", cwd=self.alpha)
        self.git("worktree", "lock", "--reason", "run git worktree remove -f -f now", tree,
                 cwd=self.alpha)
        repo = lanelib.Repo(self.alpha, self.common)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            mod.drop_tree(repo, "alpha", tree, tmpdir)
        self.assertIn("couldn't unregister the trial's tree", err.getvalue())
        self.assertIn("`lane done alpha`", err.getvalue())
        self.assertNotIn("-f -f", err.getvalue())
        self.git("worktree", "unlock", tree, cwd=self.alpha)
        self.git("worktree", "prune", cwd=self.alpha)

    def test_keeps_help_promises_no_removal_command(self):
        p = self.run_lane("trial", "--help")
        self.assertIn("what clears it", p.stdout)
        self.assertNotIn("how to remove", p.stdout)

    def test_a_symlinked_trial_dir_is_refused(self):
        away = os.path.join(self.tmp, "away")
        os.makedirs(away)
        os.symlink(away, self.trial_dir)
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1, out + err)
        self.assertIn(f"{self.trial_dir} is a symlink", err)
        # unlink removes a link or a file, never a dir's contents, whatever the link names
        self.assertIn(f"`unlink {self.trial_dir}`", err)
        self.assertNotIn("remove it", err)
        self.assertEqual(os.listdir(away), [])

    def test_it_holds_the_lock_and_a_held_lock_with_wait_0_exits_75(self):
        # A process outside the trial's tree (here: one that drops what the trial hands its
        # suites) finds the lock held.
        rc_file = os.path.join(self.tmp, "inner-rc")
        inner = shlex.join(["env", "-u", "LANE_LOCKS_HELD", sys.executable, LANE, "lock", "suite",
                            "--wait", "0", "--", "true"])
        rc, out, err = self.trial("--run", f"{inner}; echo $? > {shlex.quote(rc_file)}")
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.read(rc_file).strip(), "75")  # held by the trial meanwhile
        self.assertIn("gave up on lock suite", out)  # a suite's stderr is teed with its stdout
        lock = os.path.join(self.common, "lanes", "_locks", "suite")
        self.assertEqual(self.read(lock), "")  # its holder line cleared on the way out
        fd = os.open(lock, os.O_RDWR)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        rc, out, err = self.trial("--wait", "0", "--run", "true")
        self.assertEqual(rc, 75, out + err)
        self.assertIn("gave up on lock suite", err)
        self.assertNotIn("merged", out)

    def test_a_suite_that_takes_the_suite_lock_runs_under_the_trials_hold(self):
        # It would wait on its own trial forever. The same holds for `lane lock` inside itself.
        inner = shlex.join([sys.executable, LANE, "lock", "suite", "--", "true"])
        p = subprocess.run([sys.executable, LANE, "trial", "--run", inner], cwd=self.alpha,
                           env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("lock suite is held by a command this one runs under: running under its "
                      "hold", p.stdout)
        p = subprocess.run([sys.executable, LANE, "lock", "suite", "--", sys.executable, LANE,
                            "lock", "suite", "--", "true"], cwd=self.alpha, env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("running under its hold", p.stderr)
        # A trial under a hold refuses: an outer trial's live tree would look like a leftover.
        p = subprocess.run([sys.executable, LANE, "lock", "suite", "--", sys.executable, LANE,
                            "trial", "--run", "true"], cwd=self.alpha, env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("a trial can't run under a hold of the suite lock", p.stderr)

    def test_a_hold_counts_only_while_its_holder_is_an_ancestor(self):
        # A process the hold left running inherits LANE_LOCKS_HELD; once its holder is gone, or
        # for any holder not above it, it takes the lock like anyone (here: held, so 75).
        lock = os.path.join(self.common, "lanes", "_locks", "suite")
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        fd = os.open(lock, os.O_RDWR | os.O_CREAT)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        key = lanelib.Repo(self.main, self.common).key
        sibling = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (sibling.kill(), sibling.wait()))
        done = subprocess.Popen(["true"])
        done.wait()
        me = os.getpid()
        for holder in (f"{sibling.pid}:{lanelib.proc_start(sibling.pid)}",  # alive, not above
                       f"{done.pid}:1",  # gone
                       f"{me}:{(lanelib.proc_start(me) or 0) + 1}"):  # its pid, reused
            with self.subTest(holder=holder):
                p = subprocess.run([sys.executable, LANE, "lock", "suite", "--wait", "0", "--",
                                    "true"], cwd=self.alpha, capture_output=True, text=True,
                                   env=dict(self.env, LANE_LOCKS_HELD=f"{key}/suite@{holder}"),
                                   timeout=30)
                self.assertEqual(p.returncode, 75, p.stdout + p.stderr)
                self.assertNotIn("running under its hold", p.stderr)

    def test_a_repo_without_the_suite_lock_and_a_run_from_the_main_checkout_refuse(self):
        self.lane("init", "--locks", "gate")
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 1)
        self.assertIn("no lock 'suite' in the lanes config", err)
        self.lane("init", "--locks", "suite")
        rc, out, err = self.trial("--run", "true", cwd=self.main)
        self.assertEqual(rc, 1)
        self.assertIn("not a lane", err)

    def test_keep_keeps_the_tree(self):
        rc, out, err = self.trial("--keep", "--run", "true")
        self.assertEqual(rc, 0, out + err)
        (tree,) = glob.glob(os.path.join(self.trial_dir, self.prefix + "*", "tree"))
        self.assertIn(f"kept the tree (the merge) at {tree}", out)
        # The next trial can delete the tree's files, but sandboxed it can't unregister it.
        self.assertIn("a later `lane trial` of lane alpha clears its files and `lane done alpha` "
                      "its registration", out)
        self.assertNotIn("remove --force", out)  # by path, it would follow a swapped-in link
        self.assertTrue(os.path.isfile(os.path.join(tree, "b.txt")))
        self.git("worktree", "remove", "--force", tree)

    def test_positional_ids_restrict_the_merge(self):
        gamma = self.new("gamma")
        self.commit_files(gamma, ["c.txt"])
        rc, out, err = self.trial("gamma", "--run", "test -f c.txt && test ! -f b.txt")
        self.assertEqual(rc, 0, out + err)
        self.assertNotIn("beta", out)
        rc, out, err = self.trial("--run", "true", "nosuch")
        self.assertEqual(rc, 1)
        self.assertIn("no live lane nosuch", err)
        rc, out, err = self.trial("alpha", "--run", "true")
        self.assertEqual(rc, 1)
        self.assertIn("lane alpha is this lane", err)

    def test_nothing_to_merge_says_so_and_runs_the_suites_on_head_plus_the_base(self):
        self.git("push", "-q", "origin", "beta:main", cwd=self.beta)  # beta's work is merged
        self.git("fetch", "-q", "origin")
        rc, out, err = self.trial("beta", "--run", "test -f a.txt && test -f b.txt")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("nothing to merge from beta (already in)", out)
        self.assertIn("no other lane's work merged: running the suites on lane alpha's HEAD plus "
                      "origin/main", out)
        self.assertIn("suite 1 (test -f a.txt && test -f b.txt): ok", out)
        self.assertNotIn("other lanes' uncommitted work", err)

    def local_files(self):
        """alpha's gitignored local files: local.cfg (which .worktreeinclude names, edited in
        alpha since main's copy), and a Node-style node_modules/fake and a .venv to link."""
        self.write(os.path.join(self.alpha, ".gitignore"), "local.cfg\nnode_modules/\n.venv/\n")
        self.write(os.path.join(self.alpha, ".worktreeinclude"), "local.cfg\n")
        self.git("add", ".gitignore", ".worktreeinclude", cwd=self.alpha)
        self.git("commit", "-q", "-m", "ignores", cwd=self.alpha)
        self.write(os.path.join(self.main, "local.cfg"), "main's copy\n")
        self.write(os.path.join(self.alpha, "local.cfg"), "edited in alpha\n")
        self.write(os.path.join(self.alpha, "node_modules", "fake", "index.js"),
                   "module.exports = 42;\n")
        self.write(os.path.join(self.alpha, ".venv", "bin", "python"), "")

    def test_the_lanes_included_files_reach_the_tree(self):
        self.local_files()
        got = os.path.join(self.tmp, "got")
        rc, out, err = self.trial("--run", f"cat local.cfg > {shlex.quote(got)}")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("lane trial: copied 1 file(s) from .worktreeinclude\n", out)
        self.assertEqual(self.read(got), "edited in alpha\n")  # the lane's, not main's
        self.assertEqual(self.leftovers(), ([], []))

    def env_files(self, *names):
        """alpha ignores and includes *.env (and ignores node_modules/), with names written."""
        self.write(os.path.join(self.alpha, ".gitignore"), "*.env\nnode_modules/\n")
        self.write(os.path.join(self.alpha, ".worktreeinclude"), "*.env\n")
        self.git("add", ".gitignore", ".worktreeinclude", cwd=self.alpha)
        self.git("commit", "-q", "-m", "ignores", cwd=self.alpha)
        for name in names:
            self.write(os.path.join(self.alpha, name), f"{name} in alpha\n")

    def test_an_included_file_whose_name_git_would_quote_reaches_the_tree(self):
        self.env_files("café.env")
        got = os.path.join(self.tmp, "got")
        rc, out, err = self.trial("--run", f"cat café.env > {shlex.quote(got)}")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("lane trial: copied 1 file(s) from .worktreeinclude\n", out)
        self.assertEqual(self.read(got), "café.env in alpha\n")

    def test_an_included_file_under_a_linked_dir_never_blocks_the_link(self):
        # Linked first, and an include under a link is the link's: no copy makes the dir, so
        # the link goes in, with no warning.
        self.env_files("x.env", os.path.join("node_modules", "pkg", ".env"))
        seen = os.path.join(self.tmp, "seen")
        rc, out, err = self.trial("--link", "node_modules", "--run",
                                  f"readlink node_modules > {shlex.quote(seen)}")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("lane trial: copied 1 file(s) from .worktreeinclude, linked node_modules\n",
                      out)
        self.assertNotIn("not linked", err)
        self.assertNotIn("not copied", err)  # skipped, never tried through the link
        self.assertEqual(self.read(seen).strip(), os.path.join(self.alpha, "node_modules"))

    def test_linked_dirs_reach_the_merge_and_the_baseline(self):
        # The config's trial-link and --link each link a dir of the lane's into the tree. The
        # suite fails on the merge only, so the baseline's tree shows its links too.
        self.local_files()
        self.lane("init", "--trial-link", "node_modules")
        seen = os.path.join(self.tmp, "seen")
        cmd = (f"readlink node_modules >> {shlex.quote(seen)}; readlink .venv >> "
               f"{shlex.quote(seen)}; test ! -f b.txt")
        rc, out, err = self.trial("--link", ".venv", "--run", cmd)
        self.assertEqual(rc, 1, out + err)  # no ids, other exits: by hand
        self.assertIn("lane trial: copied 1 file(s) from .worktreeinclude, linked node_modules, "
                      ".venv\n", out)
        self.assertEqual(out.count("linked node_modules"), 1)
        self.assertIn("baseline run of suite 1/1", out)
        want = [os.path.join(self.alpha, "node_modules"), os.path.join(self.alpha, ".venv")]
        self.assertEqual(self.read(seen).splitlines(), want * 2)
        self.assertTrue(os.path.isfile(os.path.join(self.alpha, "node_modules", "fake",
                                                    "index.js")))  # the lane's own, untouched
        self.assertEqual(self.leftovers(), ([], []))

    def test_a_suite_that_requires_a_linked_module_passes_only_once_linked(self):
        self.local_files()
        if shutil.which("node"):
            cmd = "node -e \"require('./node_modules/fake')\""
        else:  # the same check without node: the module's file, at the tree's own path
            cmd = "test -f node_modules/fake/index.js"
        rc, out, err = self.trial("--run", cmd)
        self.assertEqual(rc, 1, out + err)  # fails on both runs alike, with no id: by hand
        self.assertIn("no test id on either run", out)
        self.assertIn("baseline run of suite 1/1", out)
        rc, out, err = self.trial("--link", "node_modules", "--run", cmd)
        self.assertEqual(rc, 0, out + err)
        self.assertIn(f"suite 1 ({cmd}): ok", out)
        self.assertNotIn("baseline run", out)

    @unittest.skipUnless(shutil.which("node"), "no node")
    def test_a_node_test_suite_is_judged_by_its_tap_ids(self):
        # A real `node --test`, piped: TAP. ab fails only where both lanes' files meet, old
        # fails everywhere, and the linked module loads.
        self.local_files()
        self.write(os.path.join(self.alpha, "t.test.js"),
                   "const test = require('node:test');\nconst fs = require('node:fs');\n"
                   "const assert = require('node:assert');\n"
                   "test('loads', () => assert.equal(require('./node_modules/fake'), 42));\n"
                   "test('ab', () => assert.ok(!(fs.existsSync('a.txt') && "
                   "fs.existsSync('b.txt'))));\n"
                   "test('old', () => assert.fail('always'));\n")
        self.git("add", "t.test.js", cwd=self.alpha)
        self.git("commit", "-q", "-m", "node test", cwd=self.alpha)
        rc, out, err = self.trial("--link", "node_modules", "--run", "node --test t.test.js")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("suite 1 (node --test t.test.js): 1 failure(s) only on the merge:\n"
                      "  not ok - ab", out)
        self.assertNotIn("not ok - loads", out)

    @unittest.skipUnless(shutil.which("node"), "no node")
    def test_node_subtests_of_one_name_under_two_parents_stay_apart(self):
        # P1 > works fails in both runs, P2 > works only where both lanes' files meet: by name
        # alone the two `works` would be one id, failing on the baseline too.
        self.write(os.path.join(self.alpha, "p.test.js"),
                   "const { test } = require('node:test');\nconst fs = require('node:fs');\n"
                   "test('P1', async (t) => { await t.test('works', () => { throw new "
                   "Error('always'); }); });\n"
                   "test('P2', async (t) => { await t.test('works', () => { if "
                   "(fs.existsSync('a.txt') && fs.existsSync('b.txt')) throw new "
                   "Error('merge'); }); });\n")
        self.git("add", "p.test.js", cwd=self.alpha)
        self.git("commit", "-q", "-m", "nested node test", cwd=self.alpha)
        rc, out, err = self.trial("--run", "node --test p.test.js")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("suite 1 (node --test p.test.js): 2 failure(s) only on the merge:\n"
                      "  not ok - P2 > works\n  not ok - P2\n", out)

    def test_a_link_the_lane_lacks_fails_before_any_suite_and_a_bad_one_is_refused(self):
        # Unlinked, a suite that can't load fails alike on both runs, which the same-way rule
        # passes: a trial that tested nothing. So a named link the lane lacks fails at once.
        rc, out, err = self.trial("--link", "nope", "--run", "test ! -f b.txt")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("lane alpha has no nope (--link)", err)
        self.assertNotIn("run of suite", out)
        for bad in ("../x", "/abs", "a/../b", "./x", ""):
            with self.subTest(bad=bad):
                rc, out, err = self.trial("--link", bad, "--run", "true")
                self.assertEqual(rc, 1, out + err)
                self.assertIn(f"bad trial link {bad!r}", err)
                self.assertNotIn("merged", out)
                if bad:
                    p = self.run_lane("init", "--trial-link", f"node_modules,{bad}")
                    self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                    self.assertIn(f"bad trial link {bad!r}", p.stderr)
        # A trailing slash is fine, and an empty value removes the key.
        self.assertIn("trial-link = node_modules", self.lane("init", "--trial-link",
                                                             "node_modules/"))
        self.assertNotIn("trial-link", self.lane("init", "--trial-link", ""))
        self.assertEqual(self.leftovers(), ([], []))
