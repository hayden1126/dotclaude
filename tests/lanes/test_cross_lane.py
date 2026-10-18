"""skills/lanes/scripts/lane: the board's overlap flag (live lanes whose changed files meet), the
git `ls` and `done` run in a lane, sandbox-off, kept from running what the lane can configure,
and `lane trial` (the suites on a merge with every other live lane).

Each guard has a test that fails with the guard taken out, and each trap is shown to fire without
it: a trap that never fires proves nothing."""
import contextlib
import fcntl
import glob
import json
import os
import shlex
import subprocess
import sys
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

    def test_done_refuses_a_submodule_without_running_its_fsmonitor(self):
        gitdir = self.plant_submodule(self.path)
        fsmonitor, ran = self.trap("fsmonitor")
        self.git("config", "--file", os.path.join(gitdir, "config"), "core.fsmonitor", fsmonitor)
        p = self.run_lane("done", "alpha", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("worktree has submodules", p.stderr)
        self.assertFalse(os.path.exists(ran))
        self.assertTrue(os.path.isdir(self.path))
        self.lane_status(self.path, "--ignore-submodules=none")  # the trap is real
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

    def test_handoff_check_never_runs_a_submodules_fsmonitor(self):
        gitdir = self.plant_submodule(self.path)
        fsmonitor, ran = self.trap("fsmonitor")
        self.git("config", "--file", os.path.join(gitdir, "config"), "core.fsmonitor", fsmonitor)
        p = self.handoff_check()
        self.assertIn(p.returncode, (0, 1), p.stderr)
        self.assertFalse(os.path.exists(ran))
        self.lane_status(self.path, "--untracked-files=all")  # the trap is real
        self.assertTrue(os.path.exists(ran))

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
                 "ERROR:root:a log line", "FAILED", "ok", "Ran 3 tests in 0.1s"]
        self.assertEqual(lane_mod.failing_ids(lines),
                         ["FAIL: test_x (a.B.test_x) (path='/tmp/t/tree')",
                          "ERROR: test_y (a.B.test_y)", "t.py::test_z", "t.py::test_w"])


# A suite for the trial tests: fails test_ab only where both lanes' files meet.
BOTH = 'if [ -f a.txt ] && [ -f b.txt ]; then echo "FAIL: test_ab (t.T.test_ab)"; exit 1; fi'


class Trial(LaneWork):
    """`lane trial` from lane alpha, with beta (and sometimes gamma) live beside it. TMPDIR is
    the test's own, so every scratch dir a run leaves is in sight."""

    def setUp(self):
        super().setUp()
        self.lane("init", "--locks", "suite")
        self.scratch = os.path.join(self.tmp, "scratch")
        os.makedirs(self.scratch)
        self.env["TMPDIR"] = self.scratch
        self.alpha, self.beta = self.new("alpha"), self.new("beta")
        self.commit_files(self.alpha, ["a.txt"])
        self.commit_files(self.beta, ["b.txt"])

    def trial(self, *args, cwd=None):
        p = self.run_lane("trial", *args, cwd=cwd or self.alpha)
        return p.returncode, p.stdout, p.stderr

    def leftovers(self):
        """Scratch dirs and registered trees a run left."""
        trees = [line for line in self.git("worktree", "list", "--porcelain").splitlines()
                 if line.startswith("worktree ") and self.scratch in line]
        return os.listdir(self.scratch), trees

    def test_a_clean_trial_runs_each_suite_on_both_lanes_files_and_leaves_nothing(self):
        where = os.path.join(self.tmp, "where")
        rc, out, err = self.trial("--run", "test -f a.txt && test -f b.txt",
                                  "--run", f"pwd > {shlex.quote(where)}")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("lane trial: merged beta (", out)
        self.assertIn("suite 1 (test -f a.txt && test -f b.txt): ok", out)
        self.assertIn("suite 2", out)
        tree = self.read(where).strip()
        self.assertRegex(tree, rf"^{self.scratch}/lane-trial-alpha-[a-z0-9_]{{8}}/tree$")
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
        self.assertIn("every failure also fails on the baseline, so none is the merge's", out)
        self.assertRegex(out, r"FAIL: test_where \(t\.T\.test_where\) \(path=\S+/tree\)")

    def test_a_failure_behind_a_zero_exit_still_counts(self):
        # `a; b` exits with b's code: the failing id a printed decides.
        rc, out, err = self.trial("--run", 'if [ -f b.txt ]; then echo "FAIL: test_b '
                                           '(t.T.test_b)"; fi; true')
        self.assertEqual(rc, 1, out + err)
        self.assertIn("1 failure(s) only on the merge", out)

    def test_a_failure_with_no_test_id_is_compared_by_hand(self):
        rc, out, err = self.trial("--run", "false")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("failed (exit 1) with no test id to compare against the baseline", out)

    def test_a_leftover_tree_from_a_killed_run_is_cleared(self):
        # A run killed past its cleanup leaves its dir and its registration; only this lane's
        # names go (lane alpha-b's look alike).
        stale = os.path.join(self.scratch, "lane-trial-alpha-abcd1234")
        self.git("worktree", "add", "--detach", "--quiet", os.path.join(stale, "tree"), "HEAD",
                 cwd=self.alpha)
        loose = os.path.join(self.scratch, "lane-trial-alpha-zzzz9999")
        other = os.path.join(self.scratch, "lane-trial-alpha-b-abcd1234")
        for d in (loose, other):
            os.makedirs(d)
        rc, out, err = self.trial("--run", "true")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("cleared the tree an earlier trial left registered", err)
        self.assertIn(os.path.join(stale, "tree"), err)
        self.assertEqual(self.leftovers(), (["lane-trial-alpha-b-abcd1234"], []))

    def test_it_holds_the_lock_and_a_held_lock_with_wait_0_exits_75(self):
        rc_file = os.path.join(self.tmp, "inner-rc")
        inner = shlex.join([sys.executable, LANE, "lock", "suite", "--wait", "0", "--", "true"])
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

    def test_an_unlisted_lock_and_a_run_from_the_main_checkout_refuse(self):
        rc, out, err = self.trial("--lock", "nope", "--run", "true")
        self.assertEqual(rc, 1)
        self.assertIn("no lock 'nope' in the lanes config", err)
        rc, out, err = self.trial("--run", "true", cwd=self.main)
        self.assertEqual(rc, 1)
        self.assertIn("not a lane", err)

    def test_keep_keeps_the_tree(self):
        rc, out, err = self.trial("--keep", "--run", "true")
        self.assertEqual(rc, 0, out + err)
        (tree,) = glob.glob(os.path.join(self.scratch, "lane-trial-alpha-*", "tree"))
        self.assertIn(f"kept the tree (the merge) at {tree}", out)
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

    def test_nothing_to_merge_says_so_and_runs_nothing(self):
        ran = os.path.join(self.tmp, "ran")
        self.git("push", "-q", "origin", "beta:main", cwd=self.beta)  # beta's work is merged
        self.git("fetch", "-q", "origin")
        rc, out, err = self.trial("beta", "--run", f"touch {shlex.quote(ran)}")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("nothing to merge from beta (already in)", out)
        self.assertIn("no other lane's work merged, so no suite ran", out)
        self.assertFalse(os.path.exists(ran))
