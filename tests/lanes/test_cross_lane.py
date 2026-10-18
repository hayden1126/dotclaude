"""skills/lanes/scripts/lane: the board's overlap flag (live lanes whose changed files meet), and
the git `ls` and `done` run in a lane, sandbox-off, kept from running what the lane can configure.

Each guard has a test that fails with the guard taken out, and each trap is shown to fire without
it: a trap that never fires proves nothing."""
import json
import os
import subprocess
from unittest import mock

from _fixture import LanesRepo
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
