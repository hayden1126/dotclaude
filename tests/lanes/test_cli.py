"""skills/lanes/scripts/lane: the CLI round trip, staleness, the claim lock, identity, and what
`done` ends."""
import argparse
import contextlib
import datetime
import errno
import fcntl
import glob
import importlib.machinery
import importlib.util
import json
import multiprocessing
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import types
import unittest
from unittest import mock

from _fixture import HOOKS, LANE, LanesRepo

import lanelib  # on sys.path through _fixture


def load_lane_script():
    """The lane CLI as a module, for in-process tests (it has no .py suffix)."""
    loader = importlib.machinery.SourceFileLoader("lane_cli", LANE)
    spec = importlib.util.spec_from_loader("lane_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def claim_in(args):
    """One racer: `lane claim` from a lane's checkout; returns the exit code."""
    cwd, env, req = args
    return subprocess.run([sys.executable, LANE, "claim", req], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=60).returncode


class RoundTrip(LanesRepo):
    def test_new_seeds_a_complete_lane(self):
        # A gitignored local file listed in .worktreeinclude follows the lane; a tracked one and
        # an ignored file not listed do not.
        self.write(os.path.join(self.main, ".gitignore"), "local.cfg\nbuild/\n")
        self.commit(".gitignore", "local.cfg\nbuild/\n")
        self.git("push", "-q", "origin", "main")
        self.write(os.path.join(self.main, ".worktreeinclude"), "local.cfg\n")
        self.write(os.path.join(self.main, "local.cfg"), "secret-free local rules\n")
        self.write(os.path.join(self.main, "build", "out.bin"), "x")
        self.lane("init", "--setup", 'echo "$LANE_ID:$LANE_PORT" > setup.out')

        out = self.lane("new", "chart-fix", "--claim", "42", "--goal", "fix the chart axis",
                        "--overlaps", "api-docs")
        path = self.lane_path("chart-fix")
        self.assertIn(f"cd {path} && claude", out)
        rec = self.lane_json("chart-fix")
        self.assertEqual((rec["id"], rec["branch"], rec["path"], rec["port"], rec["claims"]),
                         ("chart-fix", "chart-fix", path, 5191, ["#42"]))
        self.assertEqual(rec["base_sha"], self.git("rev-parse", "origin/main").strip())
        self.assertEqual(rec["state"], "active")
        # No upstream: a bare `git push` from the lane can't land on main by accident.
        self.assertNotEqual(subprocess.run(["git", "rev-parse", "--abbrev-ref", "@{u}"], cwd=path,
                                           env=self.env, capture_output=True).returncode, 0)
        self.assertEqual(self.read(os.path.join(path, "local.cfg")), "secret-free local rules\n")
        self.assertFalse(os.path.exists(os.path.join(path, "build")))
        self.assertEqual(self.read(os.path.join(path, "setup.out")), "chart-fix:5191\n")
        status = self.read(self.record("chart-fix"))
        self.assertIn("# LANE: chart-fix", status)
        self.assertIn("- Goal: fix the chart axis", status)
        self.assertIn("- Requests: #42", status)
        self.assertIn("- Overlaps: api-docs", status)
        # The record is hidden by the shared exclude, so the lane's tree stays clean.
        self.assertIn("/.lane/", self.read(os.path.join(self.common, "info", "exclude")).split())
        self.assertNotIn(".lane", self.git("status", "--porcelain", cwd=path))

        self.lane("new", "api-docs")
        self.assertEqual(self.lane_json("api-docs")["port"], 5192)
        rows = {r["id"]: r for r in json.loads(self.lane("ls", "--json"))}
        self.assertEqual(set(rows), {"chart-fix", "api-docs"})
        self.assertEqual((rows["chart-fix"]["ahead"], rows["chart-fix"]["behind"]), (0, 0))
        self.assertEqual(rows["chart-fix"]["pr"], "?")  # the fake gh fails: degraded, not wrong
        # No live session, and with gh failing no merge can be ruled out, so handoff? stays on.
        # Each lane's setup wrote an untracked setup.out, which no .gitignore covers: overlap.
        self.assertEqual(rows["chart-fix"]["flags"], ["overlap", "orphan", "handoff?"])
        self.assertEqual(rows["chart-fix"]["overlaps"], {"api-docs": ["setup.out"]})
        board = self.lane("ls")
        self.assertIn("chart-fix", board)
        self.assertIn("#42", board)

    def test_new_refuses_a_taken_id_or_request_and_the_cap(self):
        self.lane("new", "chart-fix", "--claim", "#42")
        self.assertIn("already registered", self.run_lane("new", "chart-fix").stderr)
        p = self.run_lane("new", "other", "--claim", "42")
        self.assertEqual(p.returncode, 1)
        self.assertIn("#42 (chart-fix)", p.stderr)
        self.assertFalse(os.path.exists(self.lane_path("other")))
        self.assertIn("bad lane id", self.run_lane("new", "main").stderr)
        self.lane("init", "--cap", "1")
        self.assertIn("cap", self.run_lane("new", "third").stderr)

    def assertNothingMade(self, lane_id, branch):
        self.assertFalse(os.path.exists(self.lane_path(lane_id)))
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", lane_id)))
        self.assertEqual(self.git("branch", "--list", branch), "")

    def test_new_refuses_a_branch_name_a_pr_used_unless_told_to_reuse_it(self):
        # `ls` labels a lane by its branch's newest PR: an old merged one would read as this
        # lane's merge.
        self.env["FAKE_GH_NEW"] = json.dumps([{"number": 94, "state": "MERGED"}])
        for args in (("probe", "--branch", "fix/old"), ("fix-old",)):  # --branch, or the id
            with self.subTest(args):
                p = self.run_lane("new", *args)
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn("#94 (merged)", p.stderr)
                self.assertIn("--reuse-branch", p.stderr)
                self.assertNothingMade(args[0], args[-1])
        self.lane("new", "probe", "--branch", "fix/old", "--reuse-branch")
        self.assertEqual(self.lane_json("probe")["branch"], "fix/old")
        # A rerun is told the lane exists, not sent to --reuse-branch by the lane's own PR.
        self.assertIn("already registered", self.run_lane("new", "probe").stderr)

    def test_new_refuses_when_gh_cannot_say_which_prs_used_the_name(self):
        # "\udcff" reaches gh's env as the byte 0xff: a reply that isn't UTF-8.
        for reply in ("fail", " ", "\udcff", '{"number": 94}', "[94]", "[" * 100000):
            with self.subTest(reply[:10]):
                self.env["FAKE_GH_NEW"] = reply
                p = self.run_lane("new", "probe")
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertNotIn("Traceback", p.stderr)
                self.assertIn("can't ask GitHub", p.stderr)
                self.assertIn("--reuse-branch", p.stderr)
                self.assertNothingMade("probe", "probe")
        self.env["FAKE_GH_NEW"] = "fail"
        self.assertIn("offline in tests", self.run_lane("new", "probe").stderr)  # gh's own words
        self.lane("new", "probe", "--reuse-branch")
        self.assertEqual(self.lane_json("probe")["branch"], "probe")

    def test_adopt_registers_an_existing_worktree(self):
        path = os.path.join(self.tmp, "elsewhere", "docs-lane")
        self.git("worktree", "add", "-q", "-b", "docs", path, "origin/main")
        self.lane("adopt", path)
        rec = self.lane_json("docs-lane")
        self.assertEqual((rec["branch"], rec["path"], rec["claims"]), ("docs", path, []))
        self.assertTrue(os.path.isfile(os.path.join(path, ".lane", "STATUS.md")))
        self.assertIn("already registered", self.run_lane("adopt", path).stderr)
        self.assertIn("not a worktree", self.run_lane("adopt", self.tmp).stderr)

    def test_done_refuses_unmerged_then_closes_a_merged_lane(self):
        self.lane("new", "chart-fix", "--claim", "42")
        path = self.lane_path("chart-fix")
        self.commit("chart.txt", "axis\n", cwd=path)
        p = self.run_lane("done", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn("not merged", p.stderr)
        self.assertTrue(os.path.isdir(path))

        # Merge it into origin/main (as a PR merge would), then close it.
        self.git("push", "-q", "origin", "chart-fix:main", cwd=path)
        self.write(os.path.join(path, ".lane", "artifacts", "shot.txt"), "evidence")
        out = self.lane("done", "chart-fix")
        self.assertIn("closed", out)
        self.assertFalse(os.path.exists(path))
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "chart-fix")))
        (archive,) = os.listdir(os.path.join(self.common, "lanes", "_closed"))
        arch = os.path.join(self.common, "lanes", "_closed", archive)
        self.assertTrue(archive.startswith("chart-fix-"))
        with open(os.path.join(arch, "lane.json")) as f:
            self.assertEqual(json.load(f)["state"], "merged")
        self.assertTrue(os.path.isfile(os.path.join(arch, ".lane", "STATUS.md")))
        self.assertTrue(os.path.isfile(os.path.join(arch, ".lane", "artifacts", "shot.txt")))
        # `git branch -d` (never -D) deleted it: it is fully in origin/main.
        self.assertEqual(self.git("branch", "--list", "chart-fix"), "")
        self.assertEqual(json.loads(self.lane("ls", "--json")), [])

    def test_done_refuses_a_kept_lane_until_abandon(self):
        # `Keep open:` in Next keeps a merged lane open even with no session to end, where
        # `handoff-check --closing` never runs. --abandon (an ask rule) closes it anyway.
        self.lane("new", "chart-fix")
        path = self.lane_path("chart-fix")
        self.commit("chart.txt", "axis\n", cwd=path)
        self.git("push", "-q", "origin", "chart-fix:main", cwd=path)
        rec = self.record("chart-fix")
        self.write(rec, self.read(rec).replace(
            "## Next\n", "## Next\n- Keep open: PR 2 follows\x1b]0;x\x07.\n"))
        p = self.run_lane("done", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("Keep open: PR 2 follows", p.stderr)
        self.assertNotIn("\x1b", p.stderr)  # the record is lane-writable: masked for a terminal
        self.assertTrue(os.path.isdir(path))
        self.assertIn("closed", self.lane("done", "chart-fix", "--abandon"))
        self.assertFalse(os.path.exists(path))
        (archive,) = os.listdir(os.path.join(self.common, "lanes", "_closed"))
        with open(os.path.join(self.common, "lanes", "_closed", archive, "lane.json")) as f:
            self.assertEqual(json.load(f)["state"], "merged")

    def test_done_validates_the_id_before_touching_anything(self):
        self.lane("new", "chart-fix")
        self.lane("done", "chart-fix", "--abandon")
        closed = os.path.join(self.common, "lanes", "_closed")
        (archive,) = os.listdir(closed)
        for bad in (f"_closed/{archive}", os.path.join(closed, archive), "..", "a..b", "_closed",
                    "x/y"):
            with self.subTest(bad=bad):
                p = self.run_lane("done", bad, "--abandon")
                self.assertEqual(p.returncode, 1)
                self.assertIn("bad lane id", p.stderr)
        self.assertEqual(os.listdir(closed), [archive])
        self.assertTrue(os.path.isfile(os.path.join(closed, archive, "lane.json")))

    def test_a_lane_with_no_commits_is_not_merged(self):
        # Its tip is the base it branched from, which is trivially "in origin/main".
        self.lane("new", "empty")
        p = self.run_lane("done", "empty")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no commits", p.stderr)
        self.assertTrue(os.path.isdir(self.lane_path("empty")))

    def test_a_merged_pr_counts_only_for_the_current_tip(self):
        self.lane("new", "chart-fix")
        path = self.lane_path("chart-fix")
        self.commit("chart.txt", "axis\n", cwd=path)
        tip = self.git("rev-parse", "HEAD", cwd=path).strip()
        # An old merged PR from a branch of the same name, at another commit: not this work.
        self.env["FAKE_GH_OUT"] = json.dumps([{"number": 7, "headRefOid": "0" * 40}])
        p = self.run_lane("done", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("not merged", p.stderr)
        # A squash merge leaves the tip out of origin/main; the PR's head commit proves it.
        self.env["FAKE_GH_OUT"] = json.dumps([{"number": 8, "headRefOid": tip}])
        out = self.lane("done", "chart-fix")
        self.assertIn("PR #8 merged", out)
        self.assertFalse(os.path.exists(path))

    def test_a_pr_list_too_deep_for_json_proves_no_merge(self):
        self.lane("new", "chart-fix")
        self.commit("chart.txt", "axis\n", cwd=self.lane_path("chart-fix"))
        self.env["FAKE_GH_OUT"] = "[" * 100000  # RecursionError in json, not ValueError
        p = self.run_lane("done", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("not merged", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_done_refuses_when_it_cannot_see_other_processes(self):
        # Sandboxed, its own claude has no /proc entry: a live session in the lane would be
        # invisible, so it must refuse rather than pass.
        self.lane("new", "chart-fix")
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1)
        self.assertIn("bare `lane done chart-fix`", p.stderr)
        self.assertTrue(os.path.isdir(self.lane_path("chart-fix")))

    def include(self, *names):
        """Gitignored local files listed in .worktreeinclude, one per name, holding 'main'."""
        ignore = "".join(n + "\n" for n in names)
        self.write(os.path.join(self.main, ".gitignore"), ignore)
        self.commit(".gitignore", ignore)
        self.git("push", "-q", "origin", "main")
        self.write(os.path.join(self.main, ".worktreeinclude"), ignore)
        for n in names:
            self.write(os.path.join(self.main, n), "main\n")

    @unittest.skipIf(os.geteuid() == 0, "root reads a chmod 0 file")
    def test_a_failed_copy_leaves_a_registered_lane_to_finish(self):
        self.include("a.cfg", "b.cfg")
        unreadable = os.path.join(self.main, "b.cfg")
        os.chmod(unreadable, 0)
        self.addCleanup(os.chmod, unreadable, 0o644)
        p = self.run_lane("new", "chart-fix")
        path = self.lane_path("chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("Traceback", p.stderr)
        self.assertIn(f"lane adopt {path}", p.stderr)
        rec = self.lane_json("chart-fix")
        self.assertEqual((rec["state"], rec["setup_failed"]), ("setup-failed", "copy"))
        # Still unreadable: adopt fails cleanly too.
        p = self.run_lane("adopt", path)
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("Traceback", p.stderr)
        # A fix made inside the lane survives the finish: copies never overwrite.
        self.write(os.path.join(path, "a.cfg"), "lane fix\n")
        os.chmod(unreadable, 0o644)
        self.lane("adopt", path)
        rec = self.lane_json("chart-fix")
        self.assertEqual(rec["state"], "active")
        self.assertNotIn("setup_failed", rec)
        self.assertEqual(self.read(os.path.join(path, "a.cfg")), "lane fix\n")
        self.assertEqual(self.read(os.path.join(path, "b.cfg")), "main\n")
        self.assertTrue(os.path.isfile(self.record("chart-fix")))

    def test_a_failed_setup_is_redone_alone_and_shows_on_the_board(self):
        self.include("a.cfg")
        self.lane("init", "--setup", "test -f ready.flag")
        p = self.run_lane("new", "chart-fix", "--claim", "42")
        path = self.lane_path("chart-fix")
        self.assertEqual(p.returncode, 1)
        rec = self.lane_json("chart-fix")
        self.assertEqual((rec["state"], rec["setup_failed"]), ("setup-failed", "setup"))
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertIn("setup-failed", row["flags"])
        self.assertIn("setup-failed", self.lane("ls"))
        self.assertIn("#42 (chart-fix)", self.run_lane("new", "other", "--claim", "42").stderr)
        self.write(os.path.join(path, "a.cfg"), "lane fix\n")
        self.write(os.path.join(path, "ready.flag"), "")
        self.lane("adopt", path)
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertEqual(self.read(os.path.join(path, "a.cfg")), "lane fix\n")  # no re-copy
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertNotIn("setup-failed", row["flags"])

    def test_adopt_takes_an_id_when_the_dir_name_is_no_slug(self):
        path = os.path.join(self.tmp, "_scratch")
        self.git("worktree", "add", "-q", "-b", "scratch", path, "origin/main")
        p = self.run_lane("adopt", path)
        self.assertEqual(p.returncode, 1)
        self.assertIn("--id", p.stderr)
        self.assertIn("git worktree move", p.stderr)
        self.assertIn("bad lane id", self.run_lane("adopt", path, "--id", "../x").stderr)
        self.lane("adopt", path, "--id", "scratch-lane")
        rec = self.lane_json("scratch-lane")
        self.assertEqual((rec["id"], rec["path"]), ("scratch-lane", path))
        self.assertTrue(self.lane("whoami", cwd=path).startswith("scratch-lane "))

    def adopt_at_main(self):
        """An adopted worktree whose tip is in origin/main: its merge-base is its tip."""
        path = os.path.join(self.tmp, "elsewhere", "docs-lane")
        self.git("worktree", "add", "-q", "-b", "docs", path, "origin/main")
        self.commit("docs.txt", "docs\n", cwd=path)
        self.git("push", "-q", "origin", "docs:main", cwd=path)
        self.git("fetch", "-q", "origin")
        self.lane("adopt", path)
        self.assertTrue(self.lane_json("docs-lane")["adopted"])
        return path

    def closed_state(self):
        closed = os.path.join(self.common, "lanes", "_closed")
        (archive,) = os.listdir(closed)
        with open(os.path.join(closed, archive, "lane.json")) as f:
            return json.load(f)["state"]

    def test_an_adopted_lane_merged_through_a_pr_closes_as_merged(self):
        path = self.adopt_at_main()
        tip = self.git("rev-parse", "HEAD", cwd=path).strip()
        self.env["FAKE_GH_OUT"] = json.dumps([{"number": 9, "headRefOid": tip}])
        self.assertIn("PR #9 merged", self.lane("done", "docs-lane"))
        self.assertEqual(self.closed_state(), "merged")

    def test_an_adopted_lane_with_nothing_past_main_closes_as_closed(self):
        # Nothing past origin/main, so nothing can be lost: no --abandon needed. It can't tell
        # "no work" from "already fast-forwarded into main", so neither merged nor abandoned.
        self.adopt_at_main()
        out = self.lane("done", "docs-lane")
        self.assertIn("closed (nothing past origin/main)", out)
        self.assertNotIn("merged", out)
        self.assertNotIn("abandoned", out)
        self.assertEqual(self.closed_state(), "closed")

    def test_a_copy_never_reads_through_a_link_or_a_special_file(self):
        # `new` copies sandbox-off, and the sandbox can plant both the link and .worktreeinclude:
        # a followed link would land a file the sandbox can't read (a credential) in the lane as
        # a plain copy it can. The link is copied as a link (a relative one made absolute, so it
        # names the same file), and the sandbox's read deny still holds at its target.
        outside = os.path.join(self.tmp, "outside")
        secret = os.path.join(outside, "secret")
        self.write(secret, "TOKEN\n")
        self.include("a.cfg", "abs.cfg", "rel.cfg", "sub/in.cfg")
        for name, target in (("abs.cfg", secret), ("rel.cfg", "sub/in.cfg")):
            os.remove(os.path.join(self.main, name))
            os.symlink(target, os.path.join(self.main, name))
        lane_mod = load_lane_script()
        dest = os.path.join(self.tmp, "dest")
        os.makedirs(dest)
        self.assertEqual(sorted(lane_mod.copy_includes(lanelib.resolve(self.main), dest)),
                         ["a.cfg", "abs.cfg", "rel.cfg", "sub/in.cfg"])
        self.assertEqual(os.readlink(os.path.join(dest, "abs.cfg")), secret)
        self.assertEqual(os.readlink(os.path.join(dest, "rel.cfg")),
                         os.path.join(self.main, "sub", "in.cfg"))
        # Git never lists a FIFO, but one can be swapped in after the listing: it is skipped,
        # never opened blocking.
        os.mkfifo(os.path.join(self.main, "pipe.cfg"))
        self.assertFalse(lane_mod.copy_one(self.main, dest, "pipe.cfg"))
        self.assertFalse(os.path.lexists(os.path.join(dest, "pipe.cfg")))
        # A dir on the way that is a link fails the copy, on either side, instead of leading out:
        # the lane's own session can plant one in the lane, the sandbox one in the main checkout.
        shutil.rmtree(os.path.join(dest, "sub"))
        os.symlink(outside, os.path.join(dest, "sub"))
        self.assertEqual(lane_mod.copy_includes(lanelib.resolve(self.main), dest), [])
        self.assertFalse(os.path.exists(os.path.join(outside, "in.cfg")))
        os.rename(os.path.join(self.main, "sub"), os.path.join(self.main, "real-sub"))
        os.symlink(outside, os.path.join(self.main, "sub"))
        self.write(os.path.join(outside, "in.cfg"), "TOKEN\n")
        fresh = os.path.join(self.tmp, "fresh")
        os.makedirs(fresh)
        with self.assertRaises(NotADirectoryError):
            lane_mod.copy_one(self.main, fresh, "sub/in.cfg")
        self.assertEqual(os.listdir(fresh), [])

    def test_a_copy_never_touches_a_neighbouring_part_file(self):
        # A fixed <name>.part temp would clobber, write through or delete someone's file.
        self.include("big.cfg")
        lane_mod = load_lane_script()
        repo = lanelib.resolve(self.main)
        dest = os.path.join(self.tmp, "dest")
        self.write(os.path.join(dest, "big.cfg.part"), "keep\n")
        self.assertEqual(lane_mod.copy_includes(repo, dest), ["big.cfg"])
        self.assertEqual(self.read(os.path.join(dest, "big.cfg.part")), "keep\n")
        self.assertEqual(sorted(os.listdir(dest)), ["big.cfg", "big.cfg.part"])
        os.remove(os.path.join(dest, "big.cfg"))
        with mock.patch.object(lane_mod, "copy_fd", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                lane_mod.copy_includes(repo, dest)
        self.assertEqual(os.listdir(dest), ["big.cfg.part"])
        self.assertEqual(self.read(os.path.join(dest, "big.cfg.part")), "keep\n")

    def test_a_lock_free_read_retries_once_when_the_mirror_moves(self):
        # The hook may delete mirror.old between mirror_dir's answer and the open.
        self.lane("new", "chart-fix")
        self.hook("lane-identity.sh", {"session_id": "s1", "cwd": self.lane_path("chart-fix"),
                                       "hook_event_name": "Stop"})
        self.git("worktree", "remove", self.lane_path("chart-fix"))
        lane_mod = load_lane_script()
        repo = lanelib.resolve(self.main)
        mirror = os.path.join(self.common, "lanes", "chart-fix", "mirror")
        answers = iter([mirror + ".old", mirror])
        with mock.patch.object(lane_mod.lanelib, "mirror_dir",
                               side_effect=lambda *a, **k: next(answers)):
            text, _ = lane_mod.record_text(repo, self.lane_json("chart-fix"))
        self.assertIn("# LANE: chart-fix", text)

    def commit_record_link(self):
        """A repo that commits `.lane -> ..`: the N1 leak one level up, in every new lane."""
        os.symlink("..", os.path.join(self.main, ".lane"))
        self.git("add", ".lane")
        self.git("commit", "-q", "-m", "a committed .lane link")
        self.git("push", "-q", "origin", "main")

    def test_done_never_archives_through_a_symlinked_record(self):
        self.commit_record_link()
        self.write(os.path.join(self.root, "outside.txt"), "not the lane's\n")
        self.assertEqual(self.run_lane("new", "chart-fix").returncode, 1)  # left setup-failed
        self.assertTrue(os.path.islink(os.path.join(self.lane_path("chart-fix"), ".lane")))
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("symlink", p.stderr)
        closed = os.path.join(self.common, "lanes", "_closed")
        (archive,) = os.listdir(closed)
        self.assertFalse(os.path.exists(os.path.join(closed, archive, ".lane", "outside.txt")))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "outside.txt")))

    def test_new_and_adopt_refuse_a_symlinked_record(self):
        self.commit_record_link()
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn("symlink", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.root, "STATUS.md")))  # not written
        path = os.path.join(self.tmp, "elsewhere", "docs-lane")
        self.git("worktree", "add", "-q", "-b", "docs", path, "origin/main")
        p = self.run_lane("adopt", path)
        self.assertEqual(p.returncode, 1)
        self.assertIn("symlink", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "docs-lane")))

    def test_a_copy_that_fails_partway_leaves_no_partial_file(self):
        # A half-copied file would be kept forever: copies never overwrite an existing file.
        self.include("big.cfg")
        lane_mod = load_lane_script()
        repo = lanelib.resolve(self.main)
        dest = os.path.join(self.tmp, "dest")
        os.makedirs(dest)
        def half(src, out):
            os.write(out, b"ha")
            raise OSError("disk full")

        with mock.patch.object(lane_mod, "copy_fd", side_effect=half):
            with self.assertRaises(OSError):
                lane_mod.copy_includes(repo, dest)
        self.assertEqual(os.listdir(dest), [])
        self.assertEqual(lane_mod.copy_includes(repo, dest), ["big.cfg"])
        self.assertEqual(self.read(os.path.join(dest, "big.cfg")), "main\n")

    def test_done_closes_a_lane_whose_record_holds_a_dangling_link(self):
        self.lane("new", "chart-fix")
        lane_rec = os.path.join(self.lane_path("chart-fix"), ".lane")
        os.symlink(os.path.join(self.tmp, "missing.png"), os.path.join(lane_rec, "gone.png"))
        os.symlink(lane_rec, os.path.join(lane_rec, "loop"))
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 0, p.stderr)
        closed = os.path.join(self.common, "lanes", "_closed")
        (archive,) = os.listdir(closed)
        self.assertTrue(os.path.islink(os.path.join(closed, archive, ".lane", "gone.png")))
        self.assertTrue(os.path.isfile(os.path.join(closed, archive, ".lane", "STATUS.md")))

    @unittest.skipIf(os.geteuid() == 0, "root reads a chmod 0 file")
    def test_a_failed_archive_leaves_nothing_behind(self):
        self.lane("new", "chart-fix")
        secret = os.path.join(self.lane_path("chart-fix"), ".lane", "unreadable.txt")
        self.write(secret, "x")
        os.chmod(secret, 0)
        self.addCleanup(lambda: os.path.exists(secret) and os.chmod(secret, 0o644))
        for _ in range(2):  # a retry adds no second partial archive
            p = self.run_lane("done", "chart-fix", "--abandon")
            self.assertEqual(p.returncode, 1)
            self.assertNotIn("Traceback", p.stderr)
            self.assertIn("archive", p.stderr)
        closed = os.path.join(self.common, "lanes", "_closed")
        self.assertEqual(os.listdir(closed) if os.path.isdir(closed) else [], [])
        self.assertTrue(os.path.isdir(self.lane_path("chart-fix")))

    def leave_only_mirror_old(self):
        """A killed hook left only mirror.old, then the worktree was removed raw: mirror.old is
        the only copy of the record."""
        self.lane("new", "chart-fix")
        path = self.lane_path("chart-fix")
        text = self.read(self.record("chart-fix")).replace(
            "## Asks for Hayden\n", "## Asks for Hayden\n- pick the chip row\n")
        self.write(self.record("chart-fix"), text)
        self.hook("lane-identity.sh", {"session_id": "s1", "cwd": path,
                                       "hook_event_name": "Stop"})
        data = os.path.join(self.common, "lanes", "chart-fix")
        os.rename(os.path.join(data, "mirror"), os.path.join(data, "mirror.old"))
        self.git("worktree", "remove", path)
        return data

    def test_a_lock_free_reader_reads_mirror_old_in_place(self):
        # asks holds no lock, so it must not rename under a hook's swap.
        data = self.leave_only_mirror_old()
        self.assertIn("chart-fix: - pick the chip row", self.lane("asks"))
        self.assertTrue(os.path.isdir(os.path.join(data, "mirror.old")))
        self.assertFalse(os.path.exists(os.path.join(data, "mirror")))

    def test_done_archives_a_mirror_left_mid_swap(self):
        self.leave_only_mirror_old()
        self.lane("done", "chart-fix", "--abandon")
        (archive,) = os.listdir(os.path.join(self.common, "lanes", "_closed"))
        self.assertIn("pick the chip row", self.read(os.path.join(
            self.common, "lanes", "_closed", archive, ".lane", "STATUS.md")))

    def test_done_abandon_keeps_an_unmerged_branch(self):
        self.lane("new", "spike")
        self.commit("spike.txt", "try\n", cwd=self.lane_path("spike"))
        p = self.run_lane("done", "spike", "--abandon")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("kept", p.stderr)  # -d refuses an unmerged branch, and that is the point
        self.assertIn("spike", self.git("branch", "--list", "spike"))
        self.assertFalse(os.path.exists(self.lane_path("spike")))

    def test_done_refuses_while_a_process_lives_in_the_lane(self):
        self.lane("new", "busy")
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                   cwd=self.lane_path("busy"))
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        p = self.run_lane("done", "busy", "--abandon")
        self.assertEqual(p.returncode, 1)
        self.assertIn(str(sleeper.pid), p.stderr)
        self.assertTrue(os.path.isdir(self.lane_path("busy")))

    def test_done_warns_about_references_into_work(self):
        self.lane("new", "chart-fix")
        self.lane("new", "api-docs")
        work = os.path.join(self.lane_path("chart-fix"), "work")
        os.makedirs(work)
        os.symlink(work, os.path.join(self.lane_path("api-docs"), "shared-work"))
        # A name from another lane is masked for the terminal (an ESC sequence clears it).
        os.symlink(work, os.path.join(self.lane_path("api-docs"), "evil\x1b[2J"))
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("reference into chart-fix/work", p.stderr)
        self.assertIn(f"{self.lane_path('api-docs')}/evil?[2J -> {work}", p.stderr)
        self.assertNotIn("\x1b", p.stderr)


class Stale(LanesRepo):
    def test_a_manually_removed_worktree_is_stale_and_its_claims_void(self):
        self.lane("new", "chart-fix", "--claim", "42")
        self.lane("new", "api-docs")
        self.git("worktree", "remove", self.lane_path("chart-fix"))
        rows = {r["id"]: r for r in json.loads(self.lane("ls", "--json"))}
        self.assertIn("stale", rows["chart-fix"]["flags"])
        self.assertNotIn("stale", rows["api-docs"]["flags"])
        self.assertIn("stale", self.lane("who", "42"))
        self.assertEqual(json.loads(self.lane("ls", "--requests", "--json")), {})
        # A stale lane is not live, so its claim does not block the owner-to-be.
        self.lane("claim", "42", cwd=self.lane_path("api-docs"))
        self.assertEqual(self.lane_json("api-docs")["claims"], ["#42"])
        # done still archives and unregisters it, from the mirror if the worktree is gone.
        self.lane("done", "chart-fix", "--abandon")
        self.assertEqual([r["id"] for r in json.loads(self.lane("ls", "--json"))], ["api-docs"])


class HandoffFlag(LanesRepo):
    """`ls`'s handoff? flag: lit when the record may be behind the lane's work (a newer commit, a
    session that ended without ever writing it, a merge it never saw), and whenever any of that
    can't be read. Times are seconds from self.t, past the base commit, so it trips nothing."""

    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix")
        self.path = self.lane_path("chart-fix")
        self.t = time.time() + 600  # wall clock
        self.env["FAKE_GH_OUT"] = "[]"  # gh answers: no PR
        self.wrote(0)

    def iso(self, off):
        return datetime.datetime.fromtimestamp(self.t + off, datetime.timezone.utc).isoformat(
            timespec="seconds")

    def wrote(self, off):
        """The record's last write, off seconds from self.t."""
        os.utime(self.record("chart-fix"), (self.t + off, self.t + off))

    def sessions(self, *spans):
        """lane.json's sessions: (start, end) offsets, end None for one not yet ended; a string
        is used as the stamp itself."""
        stamp = lambda v: v if isinstance(v, str) else self.iso(v)  # noqa: E731
        rows = [dict({"session_id": f"s{i}", "startedAt": stamp(start)},
                     **({} if end is None else {"endedAt": stamp(end), "reason": "other"}))
                for i, (start, end) in enumerate(spans)]
        repo = lanelib.resolve(self.main)
        with lanelib.lock(repo):
            lanelib.update_lane(repo, "chart-fix", lambda rec: rec.update(sessions=rows))

    def merged(self, **row):
        """gh's answer: the lane's PR #7 merged; row overrides its fields (mergedAt among them)."""
        self.env["FAKE_GH_OUT"] = json.dumps(
            [dict({"number": 7, "state": "MERGED", "headRefName": "chart-fix"}, **row)])

    def live(self):
        """A live session in the lane: this test's own pid, so /proc has it."""
        self.write(os.path.join(self.home, ".claude", "sessions", f"{os.getpid()}.json"),
                   json.dumps({"pid": os.getpid(), "sessionId": "s-live", "cwd": self.path,
                               "procStart": str(lanelib.proc_start(os.getpid()))}))

    def flags(self):
        (row,) = json.loads(self.lane("ls", "--json"))
        return row["flags"]

    def test_a_live_lane_mid_work_is_clear(self):
        self.sessions((60, None))  # started after the last write, still running
        self.live()
        self.assertEqual(self.flags(), [])

    def test_a_live_lane_right_after_a_pass_is_clear(self):
        # The passing session wrote its handoff, then ended; its successor is live.
        self.sessions((-600, 20), (40, None))
        self.live()
        self.assertEqual(self.flags(), [])

    def test_a_merged_lane_handed_off_after_the_merge_is_clear(self):
        # The post-merge handoff came after the merge; the session ended later still.
        self.merged(mergedAt=self.iso(-120))
        self.sessions((-900, 60))
        self.assertEqual(self.flags(), ["orphan"])

    def test_a_merged_lane_whose_record_predates_the_merge_lights_it(self):
        # Merged after the record's last write: the lane never saw it (Keep open: may be missing).
        self.merged(mergedAt=self.iso(60))
        self.sessions((-900, 120))
        self.assertIn("handoff?", self.flags())

    def test_a_write_within_10_s_of_the_merge_lights_it(self):
        # HAYPC's clock steps by seconds, so a write this close may predate the merge.
        self.merged(mergedAt=self.iso(-8))
        self.assertIn("handoff?", self.flags())
        self.merged(mergedAt=self.iso(-13))
        self.assertNotIn("handoff?", self.flags())

    def test_every_merge_from_the_lane_s_branch_counts(self):
        # The merge (#7) came after the record's last write; neither case may hide it.
        merge = {"number": 7, "state": "MERGED", "headRefName": "chart-fix",
                 "mergedAt": self.iso(60)}
        cases = {
            # A follow-up PR from the same branch is the newest, and the label shows it.
            "follow-up PR": ([merge, {"number": 8, "state": "OPEN", "headRefName": "chart-fix"}],
                             "#8 open"),
            # A lane may push to a fork: its PR counts like any other.
            "fork": ([dict(merge, isCrossRepository=True)], "#7 merged"),
        }
        for name, (rows, label) in cases.items():
            with self.subTest(name):
                self.env["FAKE_GH_OUT"] = json.dumps(rows)
                (row,) = json.loads(self.lane("ls", "--json"))
                self.assertIn("handoff?", row["flags"])
                self.assertEqual(row["pr"], label)

    def test_a_merge_from_the_branch_switched_away_from_counts(self):
        # The lane moved to a follow-up branch with no PR yet; its first branch's merge is unseen.
        self.git("switch", "-q", "-c", "chart-more", cwd=self.path)
        self.merged(mergedAt=self.iso(60))
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertEqual(row["pr"], "none")
        self.assertIn("handoff?", row["flags"])

    def test_a_lane_older_than_a_full_pr_list_lights_it(self):
        # gh lists PR_LIMIT PRs, newest first: a lane created before the oldest may have its PR
        # cut from the list, so its merge can't be ruled out.
        limit = load_lane_script().PR_LIMIT
        created = lanelib.parse_iso(self.lane_json("chart-fix")["created"])
        for name, oldest, flagged in (("lane newer", created - 3600, False),
                                      ("lane older", created + 3600, True),
                                      ("createdAt garbled", "soon", True),
                                      # Its branch predates the lane, and so may its PR.
                                      ("lane adopted", created - 3600, True),
                                      # So may the branch it switched to (last: it stays).
                                      ("lane switched", created - 3600, True)):
            with self.subTest(name):
                repo = lanelib.resolve(self.main)
                with lanelib.lock(repo):
                    lanelib.update_lane(repo, "chart-fix",
                                        lambda rec: rec.update(adopted=name == "lane adopted"))
                if name == "lane switched":
                    self.git("switch", "-q", "-c", "chart-more", cwd=self.path)
                stamp = oldest if isinstance(oldest, str) else datetime.datetime.fromtimestamp(
                    oldest, datetime.timezone.utc).isoformat(timespec="seconds")
                rows = [{"number": n, "state": "OPEN", "headRefName": f"other-{n}",
                         "createdAt": self.iso(0)} for n in range(2, limit + 1)]
                self.env["FAKE_GH_OUT"] = json.dumps(
                    rows + [{"number": 1, "state": "OPEN", "headRefName": "x",
                             "createdAt": stamp}])
                self.assertEqual("handoff?" in self.flags(), flagged)

    def test_a_session_that_ended_without_writing_lights_it(self):
        self.sessions((-600, 20), (40, 900))
        self.assertIn("handoff?", self.flags())

    def test_a_session_stamped_just_before_the_write_counts_as_after_it(self):
        # The clock may have stepped back between the write and the session's start: 10 s slack.
        self.sessions((-8, 900))
        self.assertIn("handoff?", self.flags())
        self.sessions((-13, 900))
        self.assertNotIn("handoff?", self.flags())

    def test_a_commit_newer_than_the_record_lights_it(self):
        self.env["GIT_COMMITTER_DATE"] = f"@{int(self.t) + 100} +0000"
        self.commit("chart.txt", "axis\n", cwd=self.path)
        self.assertIn("handoff?", self.flags())

    def test_what_cannot_be_read_lights_it(self):
        cases = {
            "gh can't answer": lambda: self.env.pop("FAKE_GH_OUT"),
            "merged, no mergedAt": lambda: self.merged(),
            "merged, null mergedAt": lambda: self.merged(mergedAt=None),
            "merged, garbled mergedAt": lambda: self.merged(mergedAt="yesterday"),
            "garbled startedAt": lambda: self.sessions(("soon", 900)),
            "garbled endedAt": lambda: self.sessions((-900, "later")),
        }
        for name, setup in cases.items():
            with self.subTest(name):
                self.env["FAKE_GH_OUT"] = "[]"
                self.sessions()
                setup()
                self.assertIn("handoff?", self.flags())

    def test_a_gh_reply_too_deep_for_json_reads_as_no_answer(self):
        self.env["FAKE_GH_OUT"] = "[" * 100000  # RecursionError in json
        p = self.run_lane("ls", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        (row,) = json.loads(p.stdout)
        self.assertEqual(row["pr"], "?")
        self.assertIn("handoff?", row["flags"])

    def test_a_branch_git_cannot_read_lights_it(self):
        # The worktree and its branch gone: the record survives in the mirror (the Stop hook's
        # copy keeps its mtime), and only the unreadable last commit is left to judge.
        self.hook("lane-identity.sh", {"session_id": "s0", "cwd": self.path,
                                       "hook_event_name": "Stop"})
        self.git("worktree", "remove", self.path)
        self.assertEqual(self.flags(), ["stale"])  # the mirror's record is read, and it's current
        self.git("branch", "-D", "chart-fix")
        self.assertEqual(self.flags(), ["stale", "handoff?"])


class Claims(LanesRepo):
    def test_concurrent_claims_have_exactly_one_winner(self):
        ids = [f"racer-{i}" for i in range(6)]
        for lane_id in ids:
            self.lane("new", lane_id)
        jobs = [(self.lane_path(i), self.env, "#42") for i in ids]
        with multiprocessing.Pool(len(jobs)) as pool:
            codes = pool.map(claim_in, jobs)
        self.assertEqual(sorted(codes), [0] + [1] * (len(ids) - 1), codes)
        holders = [i for i in ids if "#42" in self.lane_json(i)["claims"]]
        self.assertEqual(len(holders), 1)
        self.assertEqual(self.lane("who", "42").strip(), f"#42: lane {holders[0]}")

    def test_claim_release_who_and_requests(self):
        self.lane("new", "chart-fix")
        self.lane("new", "api-docs")
        self.lane("claim", "42", "#43", cwd=self.lane_path("chart-fix"))
        self.assertIn("unclaimed", self.lane("who", "44"))
        self.assertIn("#42", self.lane("ls", "--requests"))
        self.assertEqual(json.loads(self.lane("ls", "--requests", "--json")),
                         {"#42": ["chart-fix"], "#43": ["chart-fix"]})
        self.lane("release", "43", cwd=self.lane_path("chart-fix"))
        self.assertEqual(self.lane_json("chart-fix")["claims"], ["#42"])
        self.assertIn("does not claim", self.run_lane("release", "43",
                                                      cwd=self.lane_path("chart-fix")).stderr)
        # Only a lane claims, and only for itself: main holds no claims.
        self.assertIn("not a lane", self.run_lane("claim", "50").stderr)


class Identity(LanesRepo):
    def test_whoami_from_nested_dirs_main_and_elsewhere(self):
        self.lane("new", "chart-fix")
        nested = os.path.join(self.lane_path("chart-fix"), "src", "deep")
        os.makedirs(nested)
        self.assertTrue(self.lane("whoami", cwd=nested).startswith("chart-fix "))
        info = json.loads(self.lane("whoami", "--json", cwd=nested))
        self.assertEqual((info["identity"], info["kind"]), ("chart-fix", "lane"))
        self.assertEqual(info["record"], self.record("chart-fix"))
        os.makedirs(os.path.join(self.main, "docs"))
        self.assertTrue(self.lane("whoami", cwd=os.path.join(self.main, "docs")).startswith("main "))
        loose = os.path.join(self.tmp, "loose")
        self.git("worktree", "add", "-q", "-b", "loose", loose, "origin/main")
        self.assertTrue(self.lane("whoami", cwd=loose).startswith("unregistered "))

    def test_note_and_asks(self):
        self.lane("new", "chart-fix")
        lane = self.lane_path("chart-fix")
        self.lane("note", "tests green at", "abc123", cwd=lane)
        text = self.read(self.record("chart-fix"))
        state = text.split("## State", 1)[1].split("## Decisions", 1)[0]
        self.assertIn("tests green at abc123", state)
        p = self.run_lane("note", "another session owns #42", cwd=lane)
        self.assertEqual(p.returncode, 1)
        self.assertIn("relative identity", p.stderr)
        self.assertIn("no open asks", self.lane("asks"))
        self.write(self.record("chart-fix"), text.replace(
            "## Asks for Hayden\n", "## Asks for Hayden\n- pick the chip row or the dropdown\n"))
        self.assertEqual(self.lane("asks").strip(),
                         "chart-fix: - pick the chip row or the dropdown")


class ConfigTrust(LanesRepo):
    """`new` and `adopt` run the config's `setup` sandbox-off, so the config lives in the state
    dir, which sandboxed Bash can't write; only a bare `lane init` writes it."""

    def test_init_seeds_autopass_only_when_asked(self):
        (cfg,) = self.config_files()
        self.assertNotIn("autopass", self.read(cfg))  # unset: on in lanes
        self.assertIn("autopass = false", self.lane("init", "--no-autopass"))
        self.assertIn("autopass = false\n", self.read(cfg))
        self.lane("init", "--cap", "3")  # a re-init without the flag keeps it
        self.assertIn("autopass = false\n", self.read(cfg))
        self.lane("init", "--autopass")
        self.assertIn("autopass = true\n", self.read(cfg))
        # The reader: decide() in the main checkout of a lanes repo.
        spec = importlib.util.spec_from_file_location(
            "autopass_state", os.path.join(HOOKS, "autopass_state.py"))
        autopass_state = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(autopass_state)
        self.assertEqual(autopass_state.lane_setting(self.main), True)
        self.lane("init", "--no-autopass")
        self.assertEqual(autopass_state.lane_setting(self.main), False)

    def test_init_writes_the_config_to_the_state_dir_not_the_repo(self):
        (cfg,) = self.config_files()
        self.assertIn(f"# repo: {os.path.realpath(self.common)}", self.read(cfg))
        self.assertIn(f'root = "{self.root}"', self.read(cfg))
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "config.toml")))

    def test_a_config_planted_in_the_common_dir_never_runs(self):
        self.lane("init", "--setup", "touch TRUSTED")
        self.write(os.path.join(self.common, "lanes", "config.toml"),
                   f'root = "{self.tmp}/elsewhere"\nsetup = "touch PLANTED"\n')
        self.lane("new", "chart-fix")
        path = self.lane_path("chart-fix")
        self.assertTrue(os.path.exists(os.path.join(path, "TRUSTED")))
        self.assertFalse(os.path.exists(os.path.join(path, "PLANTED")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "elsewhere")))

    def test_each_repo_gets_its_own_config(self):
        other = os.path.join(self.tmp, "other")
        self.git("clone", "-q", self.origin, other, cwd=self.tmp)
        self.lane("init", "--setup", "true", cwd=other)
        texts = [self.read(f) for f in self.config_files()]
        self.assertEqual(len(texts), 2)
        (mine,) = [t for t in texts if f"# repo: {os.path.realpath(self.common)}\n" in t]
        self.assertNotIn('setup = "true"', mine)

    def test_same_named_repos_get_their_own_configs(self):
        other = os.path.join(self.tmp, "elsewhere", "proj")
        self.git("clone", "-q", self.origin, other, cwd=self.tmp)
        self.lane("init", "--setup", "true", cwd=other)
        self.assertEqual(len(self.config_files()), 2)

    @unittest.skipIf(os.geteuid() == 0, "root writes a chmod 0500 dir")
    def test_init_says_to_run_bare_when_it_cannot_write_the_state_dir(self):
        d = os.path.dirname(self.config_files()[0])
        os.chmod(d, 0o500)
        self.addCleanup(os.chmod, d, 0o700)
        p = self.run_lane("init", "--cap", "3")
        self.assertEqual(p.returncode, 1)
        self.assertIn("bare `lane init`", p.stderr)


class RecordTrust(LanesRepo):
    """Sandboxed Bash can write every lane.json, every ref and the main checkout, and the hooks,
    `ls`, `open`, `done`, `new` and `adopt` act on them sandbox-off: a record is checked on load
    (lanelib.record_problem), and a lane's path before anything acts in it."""

    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix")
        self.json_path = os.path.join(self.common, "lanes", "chart-fix", "lane.json")

    def plant(self, lane_id, **fields):
        rec = dict(self.lane_json("chart-fix"), **fields)
        self.write(os.path.join(self.common, "lanes", lane_id, "lane.json"), json.dumps(rec))

    def test_a_fifo_or_a_nul_in_a_lanes_git_metadata_refuses_promptly(self):
        # The .git file and the admin dir's gitdir file are both sandbox-writable, and the
        # admin dir is wherever the .git file names: a plain open of a FIFO would wait forever.
        repo = lanelib.resolve(self.main)
        path = self.lane_path("chart-fix")
        dotgit = os.path.join(path, ".git")
        with open(dotgit) as f:
            admin = os.path.join(path, f.read().strip().removeprefix("gitdir: "))
        back = os.path.join(admin, "gitdir")
        common = os.path.join(admin, "commondir")
        self.assertIsNone(lanelib.worktree_problem(repo, path, repo.lanes(shared=True)))

        def fifo(p):
            os.unlink(p)
            os.mkfifo(p)

        def nul(p):
            self.write(p, "gitdir: /x\0y\n" if p == dotgit else "/x\0y\n")

        def elsewhere(p):
            self.write(p, self.tmp + "\n")

        for target in (dotgit, back, common):
            for plant in (fifo, nul) + ((elsewhere,) if target == common else ()):
                with self.subTest(target=target, plant=plant.__name__):
                    with open(target, "rb") as f:
                        saved = f.read()
                    plant(target)
                    old = signal.signal(signal.SIGALRM, lambda *_: self.fail("blocked"))
                    signal.alarm(5)
                    try:
                        self.assertIsNotNone(
                            lanelib.worktree_problem(repo, path, repo.lanes(shared=True)))
                    finally:
                        signal.alarm(0)
                        signal.signal(signal.SIGALRM, old)
                        os.unlink(target)
                        with open(target, "wb") as f:
                            f.write(saved)
        self.assertIsNone(lanelib.worktree_problem(repo, path, repo.lanes(shared=True)))

    def test_a_fifo_in_place_of_a_lanes_record_reads_as_absent_promptly(self):
        # `ls` and `done` (work_references) read every lane's STATUS.md sandbox-off.
        lane_mod = load_lane_script()
        repo = lanelib.resolve(self.main)
        rec = self.record("chart-fix")
        os.unlink(rec)
        os.mkfifo(rec)
        old = signal.signal(signal.SIGALRM, lambda *_: self.fail("blocked"))
        signal.alarm(5)
        try:
            lane_mod.record_text(repo, self.lane_json("chart-fix"))
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)

    def test_a_planted_id_never_moves_the_hooks_mirror(self):
        # It sorts before the real record and claims the same path; its id walks out of lanes/.
        self.plant("0evil", id="../../../escape")
        self.write(self.record("chart-fix"), "# LANE: chart-fix\n")
        self.hook("lane-identity.sh", {"session_id": "s1", "cwd": self.lane_path("chart-fix"),
                                       "hook_event_name": "Stop"})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape")))
        self.assertTrue(os.path.isdir(os.path.join(self.common, "lanes", "chart-fix", "mirror")))
        self.assertIn("left out lanes/0evil", self.run_lane("ls").stderr)

    def test_a_planted_twin_never_frees_the_real_lanes_claims(self):
        self.lane("claim", "42", cwd=self.lane_path("chart-fix"))
        self.plant("twin", id="twin", claims=[])  # same path: neither names the lane now
        self.assertIn("shares its path", self.run_lane("ls").stderr)
        p = self.run_lane("new", "other", "--claim", "42")
        self.assertEqual(p.returncode, 1)
        self.assertIn("#42 (chart-fix)", p.stderr)

    def test_an_unreadable_record_holds_its_lane_and_what_it_held(self):
        # A record that won't read as a JSON object is left out, but its checkout is no
        # unregistered one, and its claims, port and cap slot can't be told, so nothing is
        # handed out while it stands. The main checkout still knows itself.
        self.lane("new", "api-docs", "--claim", "42")
        api = os.path.join(self.common, "lanes", "api-docs", "lane.json")
        saved = self.read(api)
        for why, junk in {"junk": "{", "deep": "[" * 100000}.items():  # RecursionError in json
            with self.subTest(why):
                self.write(api, junk)
                repo = lanelib.resolve(self.main)
                self.assertEqual([lane["id"] for lane in repo.lanes()], ["chart-fix"])
                self.assertEqual(repo.rejected, [("api-docs", "lanes/api-docs/lane.json is not "
                                                              "JSON")])
                p = self.run_lane("whoami", cwd=self.lane_path("api-docs"))
                self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)
                self.assertIn("matches no lane record", p.stderr)
                self.assertIn("api-docs", p.stderr)
                self.assertIn("main  (the main checkout", self.lane("whoami"))
                for args, cwd in ((("new", "other", "--claim", "43"), None),
                                  (("claim", "42"), self.lane_path("chart-fix"))):
                    with self.subTest(args=args):
                        p = self.run_lane(*args, cwd=cwd)
                        self.assertEqual(p.returncode, 1, p.stderr)
                        self.assertIn("lanes/api-docs/lane.json is not JSON", p.stderr)
                self.assertFalse(os.path.exists(self.lane_path("other")))
                self.assertEqual(self.lane_json("chart-fix")["claims"], [])
        self.write(api, saved)
        self.lane("claim", "43", cwd=self.lane_path("chart-fix"))

    def test_who_and_ls_requests_warn_beside_a_left_out_record(self):
        # The left-out record may hold the request, so "unclaimed" never stands alone.
        self.lane("new", "api-docs", "--claim", "42")
        self.write(os.path.join(self.common, "lanes", "api-docs", "lane.json"), "{")
        for args in (("who", "42"), ("ls", "--requests"), ("ls", "--requests", "--json")):
            with self.subTest(args=args):
                p = self.run_lane(*args)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("left out lanes/api-docs: lanes/api-docs/lane.json is not JSON",
                              p.stderr)
        self.assertIn("#42: unclaimed", self.run_lane("who", "42").stdout)

    def test_adopt_refuses_while_a_record_is_left_out(self):
        # Without ports, free_port never reads held_lanes, so adopt checks it itself: else
        # `--id` registers a second lane on the left-out one's worktree.
        (cfg,) = self.config_files()
        text = self.read(cfg)
        self.write(cfg, "\n".join(x for x in text.splitlines() if not x.startswith("ports")))
        self.lane("new", "api-docs")
        self.write(os.path.join(self.common, "lanes", "api-docs", "lane.json"), "{")
        p = self.run_lane("adopt", self.lane_path("api-docs"), "--id", "api-twin")
        self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)
        self.assertIn("lanes/api-docs/lane.json is not JSON", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "api-twin")))

    def test_twins_elsewhere_leave_an_unregistered_checkout_unregistered(self):
        # Two records sharing a path void only that path's identity; a record that won't read
        # may be any checkout's, so it still voids an unregistered one.
        self.plant("twin", id="twin")
        loose = os.path.join(self.tmp, "loose")
        self.git("worktree", "add", "-q", "-b", "loose", loose, "origin/main")
        self.assertTrue(self.lane("whoami", cwd=loose).startswith("unregistered "))
        p = self.run_lane("whoami", cwd=self.lane_path("chart-fix"))
        self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)
        self.assertIn("shares its path", p.stderr)
        self.write(os.path.join(self.common, "lanes", "junk", "lane.json"), "{")
        p = self.run_lane("whoami", cwd=loose)
        self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)
        self.assertIn("matches no lane record", p.stderr)

    def test_open_refuses_beside_an_unreadable_session_file(self):
        # Not named for a pid, it may be a live session's in the lane (lanelib.live_sessions).
        path = os.path.join(self.home, ".claude", "sessions", "not-a-pid.json")
        for why, junk in {"junk": "{", "deep": "[" * 100000}.items():  # RecursionError in json
            with self.subTest(why):
                self.write(path, junk)
                p = self.run_lane("open", "chart-fix")
                self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)
                self.assertIn(f"session file {path} can't be read as a JSON object, so this "
                              "can't tell whether lane chart-fix already has a session", p.stderr)
                self.assertIn("remove it: a file not named <pid>.json never stops counting",
                              p.stderr)
                self.assertNotIn("sandboxed", p.stderr)
                self.assertIn("session liveness unknown", self.run_lane("ls").stderr)
        os.unlink(path)
        # One named for a running pid (this test's) stops counting once that process ends.
        pid = os.getpid()
        path = os.path.join(self.home, ".claude", "sessions", f"{pid}.json")
        self.write(path, "{")
        p = self.run_lane("open", "chart-fix")
        self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)
        self.assertIn(f"session file {path} can't be read", p.stderr)
        self.assertIn(f"it stops counting once process {pid} ends", p.stderr)
        self.assertNotIn("remove it", p.stderr)
        # Beside it, a file not named for a pid is the one named: it never clears by itself.
        other = os.path.join(self.home, ".claude", "sessions", "zz-not-a-pid.json")
        self.write(other, "{")
        p = self.run_lane("open", "chart-fix")
        self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)
        self.assertIn(f"session file {other} can't be read", p.stderr)
        self.assertIn("remove it: a file not named <pid>.json never stops counting", p.stderr)

    def test_open_done_and_adopt_refuse_a_twinned_path(self):
        self.plant("twin", id="twin")
        for args in (("open", "twin", "--print"), ("done", "twin", "--abandon"),
                     ("open", "chart-fix", "--print"), ("adopt", self.lane_path("chart-fix"))):
            with self.subTest(args=args):
                p = self.run_lane(*args)
                self.assertEqual(p.returncode, 1)
                self.assertIn("didn't write", p.stderr)
        self.assertTrue(os.path.isdir(self.lane_path("chart-fix")))

    def test_new_refuses_a_path_a_stale_record_still_holds(self):
        self.plant("old", id="old", path=self.lane_path("second"))
        p = self.run_lane("new", "second")
        self.assertEqual(p.returncode, 1)
        self.assertIn("lane old still holds", p.stderr)

    def test_new_takes_the_base_ref_exactly(self):
        # ls-remote matches a ref's tail, and the server lists a/refs/heads/main first.
        self.commit("evil.sh", "x\n")
        self.git("push", "-q", "origin", "HEAD:refs/heads/a/refs/heads/main")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.lane("new", "second")
        self.assertFalse(os.path.exists(os.path.join(self.lane_path("second"), "evil.sh")))

    def test_new_takes_a_remote_whose_name_has_a_slash(self):
        self.git("remote", "rename", "origin", "my/fork")
        (cfg,) = self.config_files()
        self.write(cfg, self.read(cfg).replace('base = "origin/main"', 'base = "my/fork/main"'))
        self.lane("new", "second")

    def test_new_wants_a_remote_base(self):
        (cfg,) = self.config_files()
        self.write(cfg, self.read(cfg).replace('base = "origin/main"', 'base = "main"'))
        p = self.run_lane("new", "second")
        self.assertEqual(p.returncode, 1)
        self.assertIn("must be <remote>/<branch>", p.stderr)

    def test_ls_never_hands_git_a_planted_option(self):
        victim = os.path.join(self.tmp, "victim")
        self.write(victim, "keep\n")
        self.plant("chart-fix", branch=f"--output={victim}")
        p = self.run_lane("ls")
        self.assertEqual(self.read(victim), "keep\n")
        self.assertIn("bad branch", p.stderr)

    def test_a_record_of_the_wrong_shape_is_left_out(self):
        for field, value in (("base_sha", "HEAD"), ("port", "80; x"), ("claims", ["#1 x"]),
                             ("path", "rel/path"), ("sessions", ["x"])):
            with self.subTest(field=field):
                self.plant("chart-fix", **{field: value})
                self.assertIn("left out lanes/chart-fix", self.run_lane("ls").stderr)
        self.assertIn("bad request", self.run_lane("claim", "#1 x",
                                                   cwd=self.lane_path("chart-fix")).stderr)

    def test_open_and_done_act_only_in_the_lanes_own_worktree(self):
        decoy = os.path.join(self.main, "decoy")  # sandbox-writable, with its own .claude/
        os.makedirs(os.path.join(decoy, ".claude"))
        nested = os.path.join(self.lane_path("chart-fix"), "nested")
        os.makedirs(nested)
        for path in (decoy, nested, self.tmp):
            with self.subTest(path=path):
                self.plant("chart-fix", path=path)
                p = self.run_lane("open", "chart-fix", "--print")
                self.assertEqual(p.returncode, 1)
                self.assertIn("refusing lane chart-fix", p.stderr)
                self.assertEqual(self.run_lane("done", "chart-fix", "--abandon").returncode, 1)

    def test_new_branches_from_the_remote_not_a_planted_ref(self):
        # A tag named like the base outranks the remote-tracking ref in git's lookup.
        self.commit("evil.sh", "x\n")
        self.git("tag", "origin/main")
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.lane("new", "second")
        self.assertFalse(os.path.exists(os.path.join(self.lane_path("second"), "evil.sh")))
        self.git("remote", "set-url", "origin", os.path.join(self.tmp, "gone.git"))
        p = self.run_lane("new", "third")
        self.assertEqual(p.returncode, 1)
        self.assertIn("branches only from a freshly fetched", p.stderr)
        self.assertFalse(os.path.exists(self.lane_path("third")))

    def test_a_linked_info_exclude_or_lanes_dir_is_refused(self):
        victim = os.path.join(self.tmp, "victim")
        self.write(victim, "keep\n")
        exclude = os.path.join(self.common, "info", "exclude")
        os.remove(exclude)
        os.symlink(victim, exclude)
        self.assertEqual(self.run_lane("new", "second").returncode, 1)
        self.assertEqual(self.read(victim), "keep\n")
        moved = os.path.join(self.tmp, "moved-lanes")
        os.rename(os.path.join(self.common, "lanes"), moved)
        os.symlink(moved, os.path.join(self.common, "lanes"))
        p = self.run_lane("claim", "7", cwd=self.lane_path("chart-fix"))
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("#7", self.read(os.path.join(moved, "chart-fix", "lane.json")))


FAKE = r'''
"""A stand-in process for `lane done`'s tests. argv[1] is its JSON config:
  log       the file each signal it gets is appended to, as "<pid> <SIGNAME>"
  ignore    signal names it logs and survives (an interactive shell's SIGTERM)
  hold      a file it keeps open
  release   a file whose appearance makes it close hold (a git that finishes)
  on_term   [argv, stdin]: run on SIGTERM before it exits (a SessionEnd hook); a signal that
            comes while it runs is logged and waits, as a session mid-exit does
  drop      a file it removes on SIGTERM, before on_term ({pid} its pid: its session file,
            gone mid-exit)
  children  configs of fakes it starts, each with its own cwd and env
  then      {argv, cwd, go, out, stdin}: once go exists, run argv in cwd with stdin (text, if
            any: a hook's event) and write {rc, out, err} to out
  comm      the comm it gives itself (/proc/self/comm), e.g. "tmux: server"
  session   {file, sid}: Claude Code's session file it writes for itself (pid, procStart)
It prints "ready <pid> <its descendants' pids>" once set up, then sleeps."""
import json, os, signal, subprocess, sys, threading, time

cfg = json.loads(sys.argv[1])
ending = False


def on(sig, _frame):
    global ending
    name = signal.Signals(sig).name
    with open(cfg["log"], "a") as f:
        f.write(f"{os.getpid()} {name}\n")
    if name in cfg.get("ignore", []) or ending:
        return
    ending = True
    if sig == signal.SIGTERM and cfg.get("drop"):
        os.remove(cfg["drop"].replace("{pid}", str(os.getpid())))
    if sig == signal.SIGTERM and cfg.get("on_term"):
        argv, stdin = cfg["on_term"]
        subprocess.run(argv, input=stdin, text=True, capture_output=True, timeout=30)
    os._exit(0)


for sig in (signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, on)
if cfg.get("comm"):
    with open("/proc/self/comm", "w") as f:
        f.write(cfg["comm"])
if s := cfg.get("session"):
    with open("/proc/self/stat") as f:
        start = f.read().rpartition(")")[2].split()[19]
    with open(s["file"] + ".tmp", "w") as f:
        json.dump({"pid": os.getpid(), "sessionId": s["sid"], "cwd": os.getcwd(),
                   "kind": "interactive", "procStart": start}, f)
    os.rename(s["file"] + ".tmp", s["file"])
held = open(cfg["hold"], "a") if cfg.get("hold") else None


def release():
    while not os.path.exists(cfg["release"]):
        time.sleep(0.05)
    held.close()


if held and cfg.get("release"):
    threading.Thread(target=release, daemon=True).start()
pids = []
for child in cfg.get("children", []):
    p = subprocess.Popen([sys.executable, __file__, json.dumps(child)], cwd=child["cwd"],
                         env=child["env"], stdout=subprocess.PIPE, text=True)
    pids += p.stdout.readline().split()[1:]
print("ready", os.getpid(), *pids, flush=True)
if then := cfg.get("then"):
    while not os.path.exists(then["go"]):
        time.sleep(0.05)
    p = subprocess.run(then["argv"], cwd=then["cwd"], input=then.get("stdin"),
                       capture_output=True, text=True, timeout=60)
    with open(then["out"] + ".tmp", "w") as f:
        json.dump({"rc": p.returncode, "out": p.stdout, "err": p.stderr}, f)
    os.rename(then["out"] + ".tmp", then["out"])
while True:
    time.sleep(60)
'''


class Fakes(LanesRepo):
    """A lanes repo with lane chart-fix and disposable fake processes (FAKE) this test starts,
    proven a lane's or the lead's by session files and transcripts under the temp HOME; cleanup
    kills each one still running as the process the test started."""

    SID = "sess-lane-0001"

    def setUp(self):
        super().setUp()
        self.env["_LANE_TEST_GRACE"] = "0.5"
        self.fake_py = os.path.join(self.tmp, "fake.py")
        self.write(self.fake_py, FAKE)
        self.log = os.path.join(self.tmp, "signals.log")
        self.starts, self.comms, self.popen = {}, {}, {}
        self.lane("new", "chart-fix")
        self.path = self.lane_path("chart-fix")

    # ---- fakes and Claude Code's records ---------------------------------------------------

    def fake(self, cwd, sid=None, **cfg):
        """A fake's config, in cwd, started with CLAUDE_CODE_SESSION_ID=sid when given."""
        env = dict(self.env, **({"CLAUDE_CODE_SESSION_ID": sid} if sid else {}))
        return dict(cfg, cwd=cwd, env=env, log=self.log)

    def start(self, cfg) -> list[int]:
        """Start the fake cfg describes; its pid, then its descendants' pids."""
        p = subprocess.Popen([sys.executable, self.fake_py, json.dumps(cfg)], cwd=cfg["cwd"],
                             env=cfg["env"], stdout=subprocess.PIPE, text=True)
        self.addCleanup(p.wait, 10)
        self.addCleanup(p.stdout.close)
        pids = [int(x) for x in p.stdout.readline().split()[1:]]
        self.assertTrue(pids, "the fake never got ready")
        for pid in pids:
            comm, _, _, start = lanelib.proc_stat(pid)
            self.starts[pid], self.comms[pid] = start, comm
        self.addCleanup(self.kill_ours, pids)
        self.popen[pids[0]] = p
        return pids

    def kill_ours(self, pids):
        """SIGKILL each pid still running as the process this test started (its start time)."""
        for pid in pids:
            try:
                fd = os.pidfd_open(pid)
            except OSError:
                continue
            try:
                if lanelib.proc_start(pid) == self.starts[pid]:
                    signal.pidfd_send_signal(fd, signal.SIGKILL)
            except OSError:
                pass
            finally:
                os.close(fd)

    def alive(self, pid):
        st = lanelib.proc_stat(pid)
        return st is not None and st[3] == self.starts[pid] and st[1] not in lanelib.EXITED

    def gone(self, pid, secs=5):
        """Wait for pid to exit (a test's own kill, or a grandchild's reaping)."""
        deadline = time.monotonic() + secs
        while self.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        return not self.alive(pid)

    def signals(self):
        """[(pid, signal name)] each fake logged, in order."""
        try:
            lines = self.read(self.log).splitlines()
        except FileNotFoundError:
            return []
        return [(int(pid), name) for pid, name in (line.split() for line in lines)]

    def session_file(self, pid, sid=SID, cwd=None, start=None, **extra):
        """Claude Code's session file for pid; procStart is its real start unless given."""
        rec = {"pid": pid, "sessionId": sid, "cwd": cwd or self.path, "kind": "interactive",
               "procStart": str(self.starts[pid] if start is None else start),
               "startedAt": int(time.time() * 1000), **extra}  # wall clock
        self.write(os.path.join(self.home, ".claude", "sessions", f"{pid}.json"),
                   json.dumps(rec))

    def transcript(self, sid, cwd):
        """A transcript under the temp HOME whose first recorded cwd is cwd."""
        self.write(os.path.join(self.home, ".claude", "projects", "-proj", f"{sid}.jsonl"),
                   json.dumps({"type": "summary", "summary": "chart work"}) + "\n" +
                   json.dumps({"type": "user", "cwd": cwd, "sessionId": sid}) + "\n")

    def claude(self, sid=SID, **cfg):
        """A fake lane session: a fake in the lane with its session file."""
        pid, *rest = self.start(self.fake(self.path, **cfg))
        self.session_file(pid, sid)
        return [pid, *rest]

    def hand_off(self):
        """A record `handoff-check --closing` passes: a Next step, written after HEAD."""
        self.write(self.record("chart-fix"), self.read(self.record("chart-fix")).replace(
            "## Next\n", "## Next\n- Nothing left: the lane is done.\n"))

    def open_session_entry(self, sid, cwd):
        path = os.path.join(self.tmp, "state", "dotclaude", "open-sessions", f"{sid}.json")
        self.write(path, json.dumps({"session_id": sid, "cwd": cwd, "pane": "%1"}))
        return path

    def act_under(self, cfg, argv, cwd=None, tag=""):
        """Start the fake cfg, which runs `lane <argv>` from cwd (the main checkout's by default)
        as its child once told to; its pid, and the go and out files await_done takes (tag
        tells several in one test apart)."""
        go, out = os.path.join(self.tmp, f"go{tag}"), os.path.join(self.tmp, f"done{tag}.json")
        cfg["then"] = {"argv": [sys.executable, LANE, *argv], "cwd": cwd or self.main,
                       "go": go, "out": out}
        pid, *_ = self.start(cfg)
        return pid, go, out

    def done_under(self, cfg, lane_id="chart-fix"):
        """act_under for `lane done <lane_id> --abandon`."""
        return self.act_under(cfg, ["done", lane_id, "--abandon"])

    def await_done(self, go, out):
        """Let the act run; its {rc, out, err}."""
        self.write(go, "")
        deadline = time.monotonic() + 60
        while not os.path.exists(out) and time.monotonic() < deadline:
            time.sleep(0.05)
        return json.loads(self.read(out))


class ModelPick(Fakes):
    """`lane init --model/--effort` sets the repo's defaults, `lane open --model/--effort`
    overrides them for one launch, and both reach claude's argv ahead of its own flags."""

    def opened(self, *args):
        """The claude argv `open --print` shows: everything after tmux's `--`."""
        argv = shlex.split(self.lane("open", "chart-fix", "--print", *args).strip())
        return argv[argv.index("--") + 1:]

    def test_init_stores_prints_and_unsets_the_defaults(self):
        out = self.lane("init", "--model", "sonnet", "--effort", "low")
        self.assertIn("  model = sonnet\n", out)
        self.assertIn("  effort = low\n", out)
        (cfg,) = self.config_files()
        self.assertIn('model = "sonnet"\neffort = "low"\n', self.read(cfg))
        self.lane("init", "--cap", "3")  # a re-init without the flags keeps them
        self.assertIn('model = "sonnet"\n', self.read(cfg))
        out = self.lane("init", "--model", "")  # empty: back to the user's default
        self.assertNotIn("model =", self.read(cfg))
        self.assertNotIn("  model", out)
        self.assertIn('effort = "low"\n', self.read(cfg))

    def test_init_refuses_a_bad_model_or_effort_and_writes_nothing(self):
        (cfg,) = self.config_files()
        before = self.read(cfg)
        for flag, value, why in (("--model", "sonet", "is not a model"),
                                 ("--model", "opus;x", "is not a model"),
                                 ("--model", "-x", "is not a model"),
                                 ("--effort", "extreme", "is not an effort")):
            with self.subTest(value=value):
                p = self.run_lane("init", f"{flag}={value}")
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn(why, p.stderr)
                self.assertEqual(self.read(cfg), before)

    def test_open_passes_the_defaults_and_an_override_beats_them(self):
        claude = os.path.join(self.fake_bin, "claude")
        prompt = self.opened()[-1]
        self.assertEqual(self.opened(), [claude, "--permission-mode", "plan", prompt])
        self.lane("init", "--model", "sonnet", "--effort", "low")
        self.assertEqual(self.opened(), [claude, "--model", "sonnet", "--effort", "low",
                                         "--permission-mode", "plan", prompt])
        self.assertEqual(self.opened("--effort", "max"),
                         [claude, "--model", "sonnet", "--effort", "max", "--permission-mode",
                          "plan", prompt])
        self.assertEqual(self.opened("--model", "claude-opus-5-5"),
                         [claude, "--model", "claude-opus-5-5", "--effort", "low",
                          "--permission-mode", "plan", prompt])
        self.assertEqual(self.opened("--model", ""),  # empty: the user's default, not init's
                         [claude, "--effort", "low", "--permission-mode", "plan", prompt])

    def test_a_real_open_launches_with_the_pick_and_says_so(self):
        argv_file = os.path.join(self.tmp, "tmux.argv")
        tmux = os.path.join(self.fake_bin, "tmux")
        self.write(tmux, f"#!/bin/sh\nprintf '%s\\0' \"$@\" > {shlex.quote(argv_file)}\n"
                         "echo 'proj:3 (chart-fix)'\n")
        os.chmod(tmux, 0o755)
        self.env["TMUX"] = "/tmp/fake-tmux,1,0"
        self.lane("init", "--model", "sonnet")
        out = self.lane("open", "chart-fix", "--effort", "low")
        self.assertEqual(out, "opened chart-fix in tmux window proj:3 (chart-fix) with --model "
                              "sonnet --effort low\n")
        argv = self.read(argv_file).split("\0")[:-1]
        self.assertEqual(argv[argv.index("--") + 1:][:6],
                         [os.path.join(self.fake_bin, "claude"), "--model", "sonnet", "--effort",
                          "low", "--permission-mode"])

    def test_open_refuses_a_bad_override_or_a_bad_default(self):
        p = self.run_lane("open", "chart-fix", "--print", "--model", "sonet")
        self.assertEqual(p.returncode, 1)
        self.assertIn("'sonet' is not a model", p.stderr)
        p = self.run_lane("open", "chart-fix", "--print", "--effort", "extreme")
        self.assertEqual(p.returncode, 1)
        self.assertIn("'extreme' is not an effort", p.stderr)
        (cfg,) = self.config_files()
        self.write(cfg, self.read(cfg) + 'model = "sonet"\n')  # a hand edit
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 1)
        self.assertIn("the lanes config's model: 'sonet' is not a model", p.stderr)
        self.assertIn("lane init --model", p.stderr)

    def test_open_with_a_pick_refuses_a_lane_that_has_a_live_session(self):
        self.claude()
        for args in (("--model", "sonnet"), ("--effort", "low", "--focus")):
            with self.subTest(args=args):
                p = self.run_lane("open", "chart-fix", "--print", *args)
                self.assertEqual(p.returncode, 1, p.stdout)
                self.assertIn("already has a live session", p.stderr)
                self.assertIn("/model or /effort in its window", p.stderr)


class Stopped(Fakes):
    """A lane session stopped with Ctrl+Z: present, so it still holds the lane, but out of reach
    until `fg`, so the board flags it."""

    def test_a_lane_whose_only_session_is_stopped_is_orphan_and_stopped(self):
        (claude,) = self.claude()
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertEqual((row["live_sessions"], row["stopped_sessions"]), ([self.SID], []))
        self.assertNotIn("stopped", row["flags"])
        self.stop(claude)
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertEqual((row["live_sessions"], row["stopped_sessions"]), ([], [self.SID]))
        self.assertEqual(row["flags"][:2], ["orphan", "stopped"])
        self.assertIn(" orphan stopped", self.lane("ls").splitlines()[1])
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertIsNone(row["stopped_sessions"])

    def test_open_refuses_a_lane_with_a_stopped_session_and_labels_it(self):
        (claude,) = self.claude()
        self.stop(claude)
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn(f"already has a live session: session {self.SID} (not in tmux) "
                      "(stopped: fg it there)", p.stderr)


class Close(Fakes):
    """`lane done` ends what provably belongs to the lane and refuses, by name and before any
    signal, what doesn't: the kill-scope matrix."""

    def test_a_stopped_lane_session_is_continued_and_ends_in_round_one(self):
        # SIGTERM waits while a process is stopped, so its SessionEnd hook would never run;
        # SIGCONT delivers it. Without it the fake would log nothing and die of round 2's SIGKILL.
        self.hand_off()
        (claude,) = self.claude()
        self.stop(claude)
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertIn(f"ended {claude} {self.comms[claude]} (lane session {self.SID})", out)
        self.assertEqual(self.signals(), [(claude, "SIGTERM")])
        self.assertClosed()

    def test_a_stopped_session_s_stopped_tree_is_continued_too(self):
        # Ctrl+Z stops the whole foreground process group: claude's MCP servers and tool
        # children too. Each is continued with the session, so the signals meant for it land:
        # without that the child would log nothing and die of the SIGKILL.
        self.hand_off()
        claude, child = self.claude(children=[self.fake(self.path)])
        self.stop(child)
        self.stop(claude)
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertIn(f"ended {child} {self.comms[child]} (under lane session {self.SID})", out)
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (child, "SIGTERM")])
        self.assertClosed()

    def assertClosed(self):
        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "chart-fix")))
        self.assertEqual(glob.glob(self.proof()), [])  # a completed close deletes its record

    def assertRefusedUntouched(self, p, *pids):
        """A refusal before any signal: exit 1, each pid still running, nothing signalled, and
        the lane neither closing nor closed."""
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        for pid in pids:
            self.assertTrue(self.alive(pid), pid)
        self.assertEqual(self.signals(), [])
        self.assertNotIn("ended", p.stdout)
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertTrue(os.path.isdir(self.path))
        self.assertEqual(glob.glob(self.proof()), [])  # only a closing lane gets a record

    # ---- 1. a lane session and what runs under it ------------------------------------------

    def test_a_lane_session_and_its_child_end_and_the_lane_closes(self):
        self.commit("chart.txt", "axis\n", cwd=self.path)
        self.git("push", "-q", "origin", "chart-fix:main", cwd=self.path)
        self.hand_off()
        claude, child = self.claude(children=[self.fake(self.path)])  # the child: no environ
        mine = self.open_session_entry(self.SID, self.path)
        stray = self.open_session_entry("sess-lane-0009", os.path.join(self.path, "src"))
        other = self.open_session_entry("sess-main-0001", self.main)
        out = self.lane("done", "chart-fix")
        self.assertIn(f"ended {claude} {self.comms[claude]} (lane session {self.SID})", out)
        self.assertIn(f"ended {child} {self.comms[child]} (under lane session {self.SID})", out)
        self.assertIn("closed (fully in origin/main)", out)
        # The session by SIGTERM in round 1; its orphaned child by SIGTERM in round 2.
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (child, "SIGTERM")])
        self.assertFalse(self.alive(claude) or self.alive(child))
        self.assertClosed()
        # claude-restore will reopen nothing in the lane; another checkout's tab stays.
        self.assertFalse(os.path.exists(mine) or os.path.exists(stray))
        self.assertTrue(os.path.exists(other))

    def test_keep_open_refuses_a_live_lane_until_abandon(self):
        # Design B's usual case: the lane sent `merged #N` and its session is still up. Its own
        # check refuses before any signal; --abandon gets past `handoff-check --closing` too.
        self.commit("chart.txt", "axis\n", cwd=self.path)
        self.git("push", "-q", "origin", "chart-fix:main", cwd=self.path)
        self.hand_off()
        self.write(self.record("chart-fix"), self.read(self.record("chart-fix")).replace(
            "## Next\n", "## Next\nKeep open: PR 2 follows.\n\n"))
        (claude,) = self.claude()
        p = self.run_lane("done", "chart-fix")
        self.assertIn("Next says 'Keep open: PR 2 follows.'", p.stderr)
        self.assertRefusedUntouched(p, claude)
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertIn("closed (fully in origin/main)", out)
        self.assertClosed()

    # ---- 2. what a session file can't prove ------------------------------------------------

    def test_a_reused_pid_or_a_foreign_session_refuses_and_nothing_is_signalled(self):
        self.hand_off()
        (claude,) = self.claude()
        (reused,) = self.start(self.fake(self.path))
        self.session_file(reused, "sess-lane-0002", start=self.starts[reused] + 1)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn(f"{reused} {self.comms[reused]} (a stale session file names its pid)",
                      p.stderr)
        self.assertRefusedUntouched(p, reused, claude)
        os.remove(os.path.join(self.home, ".claude", "sessions", f"{reused}.json"))
        self.kill_ours([reused])
        self.assertTrue(self.gone(reused))
        (foreign,) = self.start(self.fake(self.path))  # the lead's session, cd'd into the lane
        self.session_file(foreign, "sess-main-0002", cwd=self.main)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn("(session sess-main-0002 is not lane chart-fix's)", p.stderr)
        self.assertRefusedUntouched(p, foreign, claude)

    # ---- 3. the restore shape: a shell that ran claude -------------------------------------

    def pane(self, shell=None, claude=None):
        """claude-restore's shape: a tmux server (outside the lane) whose pane shell, in the
        lane, ran a lane session. shell and claude are extra fake() arguments (sid, a config
        key). [server, shell, claude]."""
        shell = dict(shell or {}, ignore=["SIGTERM", *(shell or {}).get("ignore", [])])
        pids = self.start(self.fake(self.tmp, comm="tmux: server", children=[
            self.fake(self.path, **shell, children=[self.fake(self.path, **(claude or {}))])]))
        self.session_file(pids[2])
        return pids

    def test_a_pane_shell_ends_by_sighup_after_its_session(self):
        self.hand_off()
        server, shell, claude = self.pane()
        self.assertEqual(self.comms[server], "tmux: server")
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertIn(f"ended {shell} {self.comms[shell]} (the shell of lane session "
                      f"{self.SID})", out)
        # An interactive shell ignores SIGTERM: it gets only SIGHUP, once its session is gone.
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (shell, "SIGHUP")])
        self.assertTrue(self.alive(server))
        self.assertClosed()

    def test_a_pane_shell_whose_session_survives_round_one(self):
        # Its SIGHUP comes all the same; round 2 sends the session SIGTERM again, then SIGKILL.
        self.hand_off()
        server, shell, claude = self.pane(claude={"ignore": ["SIGTERM"]})
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (shell, "SIGHUP"),
                                          (claude, "SIGTERM")])
        self.assertIn(f"ended {claude} {self.comms[claude]} (lane session {self.SID})", out)
        self.assertFalse(self.alive(claude))
        self.assertClosed()

    def test_a_pane_shell_that_survives_its_sighup_gets_sighup_again_never_sigterm(self):
        # An interactive shell ignores SIGTERM, so round 2's signal to it is SIGHUP too; SIGKILL
        # follows once the grace is out.
        self.hand_off()
        server, shell, claude = self.pane(shell={"ignore": ["SIGHUP"]})
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (shell, "SIGHUP"),
                                          (shell, "SIGHUP")])
        self.assertIn(f"ended {shell} {self.comms[shell]} (the shell of lane session "
                      f"{self.SID})", out)
        self.assertFalse(self.alive(shell))
        self.assertTrue(self.alive(server))
        self.assertClosed()

    def test_a_session_parent_that_is_no_tmux_pane_shell_refuses(self):
        # A foreign session's Bash ran `cd <lane> && claude`: its parent is no tmux server, and
        # it carries that session's id. Neither may be SIGHUPed as the lane's pane shell.
        self.hand_off()
        bash, claude = self.start(self.fake(self.path, children=[self.fake(self.path)]))
        self.session_file(claude)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn(f"{bash} {self.comms[bash]} (the parent of lane session {self.SID}, but "
                      "not a tmux pane's shell)", p.stderr)
        self.assertRefusedUntouched(p, bash, claude)
        self.kill_ours([bash, claude])
        self.transcript("sess-main-0007", self.main)
        server, shell, claude = self.pane(shell={"sid": "sess-main-0007"})
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn(f"{shell} {self.comms[shell]} (the parent of lane session {self.SID}, but "
                      "session sess-main-0007 is not lane chart-fix's)", p.stderr)
        self.assertRefusedUntouched(p, shell, claude)

    def test_a_pane_shell_that_takes_a_new_job_mid_close_is_never_sighuped(self):
        # Its SIGHUP would reach the new job too: round 1 waits it out for the grace, then skips
        # it, and round 2 refuses it.
        self.hand_off()
        go, ready = os.path.join(self.tmp, "go"), os.path.join(self.tmp, "job-ready")
        server, shell, claude = self.pane(
            shell={"then": {"argv": ["sh", "-c", f"touch {ready}; exec sleep 20"],
                            "cwd": self.tmp, "go": go, "out": os.path.join(self.tmp, "o")}},
            claude={"on_term": [["sh", "-c", f"touch {go}; while [ ! -e {ready} ]; do "
                                             "sleep 0.05; done"], ""]})
        p = self.run_lane("done", "chart-fix", "--abandon")
        jobs = lanelib.children(lanelib.scan()).get(shell, [])
        for job in jobs:
            self.starts[job] = lanelib.proc_start(job)
        self.addCleanup(self.kill_ours, jobs)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"{shell} {self.comms[shell]} (the shell of lane session {self.SID}, now "
                      f"running {jobs[0]} sleep)", p.stderr)
        self.assertEqual(self.signals(), [(claude, "SIGTERM")])
        self.assertTrue(self.alive(shell))
        self.assertEqual(self.lane_json("chart-fix")["state"], "closing")

    def test_a_job_the_pane_shell_starts_as_its_session_ends_is_waited_out(self):
        # A prompt forks as it draws (agnoster's `$(build_prompt)` runs git in a -zsh child), and
        # a restored tab draws one the moment its claude exits: round 1 waits such a job out, up
        # to the grace, before the shell's SIGHUP.
        self.env["_LANE_TEST_GRACE"] = "4"
        self.hand_off()
        go, ready = os.path.join(self.tmp, "go"), os.path.join(self.tmp, "job-ready")
        server, shell, claude = self.pane(
            shell={"then": {"argv": ["sh", "-c", f"touch {ready}; sleep 1.5"], "cwd": self.path,
                            "go": go, "out": os.path.join(self.tmp, "o")}},
            claude={"on_term": [["sh", "-c", f"touch {go}; while [ ! -e {ready} ]; do "
                                             "sleep 0.05; done"], ""]})
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertIn(f"ended {shell} {self.comms[shell]} (the shell of lane session "
                      f"{self.SID})", out)
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (shell, "SIGHUP")])
        self.assertClosed()

    def proof(self):
        """The glob of lane chart-fix's recorded proof (Repo.closing_path) in the temp state."""
        return os.path.join(self.tmp, "state", "dotclaude", "lanes", "*.closing", "chart-fix.json")

    def refused_mid_close(self):
        """The 2026-10-15 shape (lane two-sessions), first run: as its session ends, the pane
        shell starts an in-lane job with no session id that outlasts the grace, so round 2
        refuses both and the lane stays closing. [shell, claude, job, release, saw]: touching
        release ends the job, and saw lists the proof the session's SIGTERM found recorded."""
        go, ready, release, saw = (os.path.join(self.tmp, x)
                                   for x in ("go", "job-ready", "release", "saw-proof"))
        server, shell, claude = self.pane(
            shell={"then": {"argv": ["sh", "-c", f"touch {ready}; while [ ! -e {release} ]; do "
                                                 "sleep 0.05; done"],
                            "cwd": self.path, "go": go, "out": os.path.join(self.tmp, "o")}},
            claude={"on_term": [["sh", "-c", f"ls {self.proof()} >{saw}; touch {go}; while [ ! "
                                             f"-e {ready} ]; do sleep 0.05; done"], ""]})
        p = self.run_lane("done", "chart-fix", "--abandon")
        (job,) = lanelib.children(lanelib.scan()).get(shell, [])
        self.starts[job], self.comms[job] = lanelib.proc_start(job), "sh"
        self.addCleanup(self.kill_ours, [job])
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"{shell} {self.comms[shell]} (the shell of lane session {self.SID}, now "
                      f"running {job} sh)", p.stderr)
        self.assertIn(f"{job} sh (no session id in its environment)", p.stderr)
        self.assertEqual(self.signals(), [(claude, "SIGTERM")])
        self.assertTrue(self.alive(shell))
        self.assertEqual(self.lane_json("chart-fix")["state"], "closing")
        return shell, claude, job, release, saw

    def test_a_rerun_closes_a_pane_shell_whose_session_the_first_run_ended(self):
        # The rerun finds the session gone, and with it the only proof that the shell is the
        # lane's: the first run recorded it before its first signal, and the rerun keeps it.
        self.hand_off()
        shell, claude, job, release, saw = self.refused_mid_close()
        self.write(release, "")
        self.assertTrue(self.gone(job))
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertIn(f"ended {shell} {self.comms[shell]} (the shell of lane session "
                      f"{self.SID})", out)
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (shell, "SIGHUP")])
        self.assertClosed()
        self.assertEqual(glob.glob(self.proof()), [])
        self.assertTrue(self.read(saw).strip(), "no proof was recorded by the first signal")

    def test_a_rerun_still_refuses_a_recorded_pane_shell_that_runs_a_job(self):
        # A recorded shell keeps only its class: a job it runs at the rerun still refuses it,
        # since its SIGHUP would reach that job too.
        self.hand_off()
        shell, claude, job, release, saw = self.refused_mid_close()
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"{shell} {self.comms[shell]} (the shell of lane session {self.SID}, now "
                      f"running {job} sh)", p.stderr)
        self.assertIn("nothing was signalled", p.stderr)
        self.assertEqual(self.signals(), [(claude, "SIGTERM")])
        self.assertTrue(self.alive(shell))

    def test_a_recorded_proof_counts_only_for_the_process_it_names(self):
        # Only for the same boot, lane and process (pid, start, comm), and for a pane shell only
        # while a tmux server is its parent and it carries no foreign session id: otherwise the
        # scan's own classification stands, which refuses the shell.
        self.hand_off()
        shell, claude, job, release, saw = self.refused_mid_close()
        self.write(release, "")
        self.assertTrue(self.gone(job))
        (path,) = glob.glob(self.proof())
        good = self.read(path)
        unproven = f"{shell} {self.comms[shell]} (no session id in its environment)"

        def shell_entry(rec):
            return next(e for e in rec["shells"] if e["pid"] == shell)

        tampers = {
            "boot": lambda rec: rec.update(boot="00000000-0000-0000-0000-000000000000"),
            "lane": lambda rec: rec.update(lane="other"),
            "created": lambda rec: rec.update(created="2026-01-01T00:00:00Z"),
            "path": lambda rec: rec.update(path=self.main),
            "start": lambda rec: shell_entry(rec).update(start=self.starts[shell] + 1),
            "comm": lambda rec: shell_entry(rec).update(comm="bash"),
        }
        for name, tamper in tampers.items():
            with self.subTest(name):
                rec = json.loads(good)
                tamper(rec)
                self.write(path, json.dumps(rec))
                p = self.run_lane("done", "chart-fix", "--abandon")
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn(unproven, p.stderr)
        for raw in ("{", "[]", json.dumps(dict(json.loads(good), shells="x")), "[" * 100000):
            with self.subTest(raw[:10]):
                self.write(path, raw)
                p = self.run_lane("done", "chart-fix", "--abandon")
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertNotIn("Traceback", p.stderr)
                self.assertIn(unproven, p.stderr)
        # Entries naming other pane-shaped processes in the lane: one carries a foreign session
        # id, and one's parent is no tmux server. Neither is kept, and each refuses as it would
        # unrecorded; the real shell's entry still holds.
        self.transcript("sess-main-0007", self.main)
        _, foreign = self.start(self.fake(self.tmp, comm="tmux: server", children=[
            self.fake(self.path, sid="sess-main-0007")]))
        _, loose = self.start(self.fake(self.tmp, children=[self.fake(self.path)]))
        rec = json.loads(good)
        rec["shells"] += [dict(shell_entry(rec), pid=pid, start=self.starts[pid],
                              comm=self.comms[pid]) for pid in (foreign, loose)]
        self.write(path, json.dumps(rec))
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"{foreign} {self.comms[foreign]} (session sess-main-0007 is not lane "
                      "chart-fix's)", p.stderr)
        self.assertIn(f"{loose} {self.comms[loose]} (no session id in its environment)",
                      p.stderr)
        self.assertNotIn(f"\n  {shell} ", p.stderr)
        self.kill_ours([foreign, loose])
        self.assertTrue(self.gone(foreign) and self.gone(loose))
        self.lane("done", "chart-fix", "--abandon")
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (shell, "SIGHUP")])
        self.assertClosed()

    def test_a_pane_shell_first_proven_in_round_two_keeps_its_proof_for_the_rerun(self):
        # A tab opened in the lane mid-close, whose claude round 2 ends: round 2 records its
        # shell too, so a rerun after the close refuses at its final look (the shell holds a
        # git file open) still knows the shell as the lane's.
        self.hand_off()
        held, ready = os.path.join(self.common, "held.lock"), os.path.join(self.tmp, "late-ready")
        sfile = os.path.join(self.home, ".claude", "sessions", "late.json")
        tab = self.fake(self.tmp, comm="tmux: server", children=[
            self.fake(self.path, hold=held, ignore=["SIGTERM"], children=[
                self.fake(self.path, session={"file": sfile, "sid": "sess-lane-0002"})])])
        argv = shlex.join([sys.executable, self.fake_py, json.dumps(tab)])
        spawn = (f"cd {shlex.quote(self.tmp)} && {argv} </dev/null >{ready} 2>/dev/null & "
                 f"while [ ! -s {ready} ]; do sleep 0.05; done")
        (claude,) = self.claude(on_term=[["sh", "-c", spawn], ""])
        p = self.run_lane("done", "chart-fix", "--abandon")
        server, shell, late = [int(x) for x in self.read(ready).split()[1:]]
        for pid in (server, shell, late):
            self.starts[pid] = lanelib.proc_start(pid)
        self.addCleanup(self.kill_ours, [server, shell, late])
        self.comms[shell] = lanelib.proc_stat(shell)[0]
        why = (f"{shell} {self.comms[shell]} (the shell of lane session sess-lane-0002; holds "
               f"{held} open, so it was left running")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(why, p.stderr)
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (late, "SIGTERM")])
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(why, p.stderr)
        self.kill_ours([shell])
        self.assertTrue(self.gone(shell))
        self.lane("done", "chart-fix", "--abandon")
        self.assertClosed()

    def test_a_pane_shell_whose_git_file_closes_within_the_grace_gets_one_sighup(self):
        # guarded holds its SIGHUP while it has a git file open; round 1 retries within the
        # grace, so the SIGHUP comes once the file closes, not a grace later in round 2.
        self.env["_LANE_TEST_GRACE"] = "8"
        self.hand_off()
        held, release = os.path.join(self.common, "held.lock"), os.path.join(self.tmp, "release")
        server, shell, claude = self.pane(shell={"hold": held, "release": release})
        p = subprocess.Popen([sys.executable, LANE, "done", "chart-fix", "--abandon"],
                             cwd=self.main, env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        self.addCleanup(p.wait, 60)
        deadline = time.monotonic() + 30
        while (claude, "SIGTERM") not in self.signals() and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.5)  # round 1 is retrying the shell's held SIGHUP by now
        self.assertNotIn((shell, "SIGHUP"), self.signals())
        released = time.monotonic()
        self.write(release, "")
        while (shell, "SIGHUP") not in self.signals() and time.monotonic() < released + 30:
            time.sleep(0.05)
        self.assertLess(time.monotonic() - released, 3)  # round 2's comes a full 8 s grace later
        out, err = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, out + err)
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (shell, "SIGHUP")])
        self.assertClosed()

    def test_a_proof_that_can_t_be_recorded_refuses_before_any_signal(self):
        # A close that can't keep its proof would leave a rerun nothing to prove a pane shell by.
        # The lane is marked closing by then, and a rerun once the record can be written closes.
        self.hand_off()
        (claude,) = self.claude()
        (config,) = glob.glob(os.path.join(self.tmp, "state", "dotclaude", "lanes", "*.toml"))
        blocker = config.removesuffix(".toml") + ".closing"
        self.write(blocker, "")  # a file where its dir goes
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertIn("so nothing was signalled and the lane is left closing: rerun `lane done "
                      "chart-fix` once it can be written", p.stderr)
        self.assertEqual(self.signals(), [])
        self.assertTrue(self.alive(claude))
        self.assertEqual(self.lane_json("chart-fix")["state"], "closing")
        os.remove(blocker)
        self.lane("done", "chart-fix", "--abandon")
        self.assertEqual(self.signals(), [(claude, "SIGTERM")])
        self.assertClosed()

    def test_each_pane_shell_gets_its_sighup_once_its_own_job_ends(self):
        # One shell's job holds back only that shell's SIGHUP.
        self.env["_LANE_TEST_GRACE"] = "6"
        self.hand_off()
        go, ready = os.path.join(self.tmp, "go"), os.path.join(self.tmp, "job-ready")
        _, busy, claude = self.pane(
            shell={"then": {"argv": ["sh", "-c", f"touch {ready}; sleep 3"], "cwd": self.path,
                            "go": go, "out": os.path.join(self.tmp, "o")}},
            claude={"on_term": [["sh", "-c", f"touch {go}; while [ ! -e {ready} ]; do "
                                             "sleep 0.05; done"], ""]})
        _, idle, other = self.pane()
        self.lane("done", "chart-fix", "--abandon")
        sigs = self.signals()
        self.assertCountEqual(sigs, [(claude, "SIGTERM"), (other, "SIGTERM"), (busy, "SIGHUP"),
                                     (idle, "SIGHUP")])
        self.assertLess(sigs.index((idle, "SIGHUP")), sigs.index((busy, "SIGHUP")))
        self.assertClosed()

    def test_a_pane_shell_held_at_the_final_look_keeps_its_proof_for_the_rerun(self):
        # Held for a git file it holds open, the shell outlives its session, and the close
        # refuses at its final look: the rerun still knows it as the lane's pane shell, which
        # nothing else could prove once its session is gone.
        self.hand_off()
        held = os.path.join(self.common, "held.lock")
        server, shell, claude = self.pane(shell={"hold": held})
        why = (f"{shell} {self.comms[shell]} (the shell of lane session {self.SID}; holds "
               f"{held} open, so it was left running")
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("lane chart-fix is closing, and these still run", p.stderr)
        self.assertIn(why, p.stderr)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(why, p.stderr)
        self.assertEqual(self.signals(), [(claude, "SIGTERM")])
        self.kill_ours([shell])
        self.assertTrue(self.gone(shell))
        self.lane("done", "chart-fix", "--abandon")
        self.assertClosed()

    def test_a_shell_with_another_job_refuses(self):
        self.hand_off()
        shell, claude, vim = self.start(self.fake(self.path, children=[
            self.fake(self.path), self.fake(self.path)]))
        self.session_file(claude)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn(f"{shell} {self.comms[shell]} (a shell with other jobs)", p.stderr)
        self.assertIn(f"{vim} {self.comms[vim]} (no session id in its environment)", p.stderr)
        self.assertRefusedUntouched(p, shell, claude, vim)

    # ---- 4. leftovers: started with a lane session's id ------------------------------------

    def test_a_leftover_proven_by_its_transcript_ends(self):
        self.hand_off()
        self.transcript("sess-lane-0003", self.path)
        (left,) = self.start(self.fake(self.path, "sess-lane-0003"))
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertIn(f"ended {left} {self.comms[left]} (carries lane session sess-lane-0003)",
                      out)
        self.assertEqual(self.signals(), [(left, "SIGTERM")])
        self.assertClosed()

    def test_a_leftover_that_ignores_sigterm_gets_sigkill(self):
        self.hand_off()
        self.transcript("sess-lane-0003", self.path)
        (left,) = self.start(self.fake(self.path, "sess-lane-0003", ignore=["SIGTERM"]))
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertIn(f"ended {left}", out)
        self.assertEqual(self.signals(), [(left, "SIGTERM"), (left, "SIGTERM")])
        self.assertEqual(self.popen[left].wait(5), -signal.SIGKILL)
        self.assertClosed()

    def test_a_leftover_holding_a_git_file_is_never_killed_and_the_lane_stays_closing(self):
        # Not even SIGTERMed: every signal but a session's first is held while a git file is
        # open under its target.
        self.hand_off()
        self.transcript("sess-lane-0003", self.path)
        held = os.path.join(self.common, "held.lock")
        (left,) = self.start(self.fake(self.path, "sess-lane-0003", ignore=["SIGTERM"],
                                       hold=held))
        stray = self.open_session_entry("sess-lane-0009", self.path)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        # A close refused after its signals still sweeps claude-restore's entries in the lane.
        self.assertFalse(os.path.exists(stray))
        self.assertIn(f"{left} {self.comms[left]} (carries lane session sess-lane-0003; holds "
                      f"{held} open, so it was left running (a killed git leaves lock files))",
                      p.stderr)
        self.assertTrue(self.alive(left))
        self.assertEqual(self.signals(), [])
        self.assertEqual(self.lane_json("chart-fix")["state"], "closing")
        self.assertTrue(os.path.isdir(self.path))
        self.assertIn("closing", json.loads(self.lane("ls", "--json"))[0]["flags"])
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 1)
        self.assertIn("lane chart-fix is closing: rerun `lane done chart-fix`", p.stderr)
        # Once it is gone, a rerun carries on.
        self.kill_ours([left])
        self.assertTrue(self.gone(left))
        self.assertIn("closed (abandoned)", self.lane("done", "chart-fix", "--abandon"))
        self.assertClosed()

    def test_a_survivor_with_a_git_file_holder_under_it_is_never_killed(self):
        # SIGKILL of a sandbox's pid namespace init (apply-seccomp, bwrap) kills its git too:
        # a survivor is never SIGKILLed while any process under it holds a git-dir file.
        self.hand_off()
        self.transcript("sess-lane-0003", self.path)
        held = os.path.join(self.common, "held.lock")
        init, git = self.start(self.fake(self.path, "sess-lane-0003", ignore=["SIGTERM"],
                                         children=[self.fake(self.path, "sess-lane-0003",
                                                             ignore=["SIGTERM"], hold=held)]))
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertTrue(self.alive(init) and self.alive(git))
        self.assertIn(f"{init} {self.comms[init]} (carries lane session sess-lane-0003; has "
                      f"{git} {self.comms[git]} under it, which holds {held} open, so it was left "
                      "running", p.stderr)
        self.assertIn(f"{git} {self.comms[git]} (carries lane session sess-lane-0003; holds "
                      f"{held} open", p.stderr)
        self.assertEqual(self.signals(), [])  # SIGTERM to an init that exits would kill it too
        self.assertEqual(self.lane_json("chart-fix")["state"], "closing")

    def test_guarded_checks_the_whole_tree_just_before_its_signal(self):
        lane_mod = load_lane_script()
        parent, child = self.start(self.fake(self.tmp, children=[self.fake(self.tmp)]))
        seen = []

        def check(pid, root):  # lanelib.open_under, noting each process it checks
            seen.append(pid)
            return None

        with mock.patch.object(lanelib, "open_under", side_effect=check):
            self.assertIsNone(lane_mod.guarded(lanelib.scan()[parent], signal.SIGTERM,
                                               self.common))
        self.assertEqual(seen, [parent, child])
        self.assertTrue(self.gone(parent))
        # A holder anywhere in the tree holds the signal; a check that fails signals nothing.
        lock = os.path.join(self.common, "y.lock")
        top, mid = self.start(self.fake(self.tmp, children=[self.fake(self.tmp, hold=lock)]))
        why = lane_mod.guarded(lanelib.scan()[top], signal.SIGTERM, self.common)
        self.assertEqual(why, f"has {mid} {self.comms[mid]} under it, which holds {lock} open, "
                              "so it was left running (a killed git leaves lock files)")
        with mock.patch.object(lanelib, "open_under", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                lane_mod.guarded(lanelib.scan()[top], signal.SIGKILL, self.common)
        self.assertTrue(self.alive(top) and self.alive(mid))
        self.assertEqual(self.signals(), [(parent, "SIGTERM")])

    def test_a_pane_shell_that_took_a_new_job_since_its_check_is_never_sighuped(self):
        # guarded's own `only` check, just before the signal: round 1's filter ran earlier.
        lane_mod = load_lane_script()
        shell, claude, job = self.start(self.fake(self.tmp, children=[self.fake(self.tmp),
                                                                       self.fake(self.tmp)]))
        only = {(shell, self.starts[shell]), (claude, self.starts[claude])}
        why = lane_mod.guarded(lanelib.scan()[shell], signal.SIGHUP, self.common, only)
        self.assertEqual(why, f"now running {job} {self.comms[job]}, so it was left running")
        self.assertEqual(self.signals(), [])

    def test_what_runs_under_a_held_session_is_never_sigkilled(self):
        # Its session's round-2 SIGTERM is held (a hook has a git file open), so its other
        # processes got no signal of their own: none of them may get a SIGKILL either.
        self.hand_off()
        lock = os.path.join(self.common, "z.lock")
        claude, holder, plain = self.claude(ignore=["SIGTERM"], children=[
            self.fake(self.path, ignore=["SIGTERM"], hold=lock), self.fake(self.path)])
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        for pid in (claude, holder, plain):
            self.assertTrue(self.alive(pid), pid)
        (line,) = [x for x in p.stderr.splitlines() if x.strip().startswith(f"{plain} ")]
        self.assertIn(f"its session {claude} was left running, so it was too", line)
        self.assertEqual(self.lane_json("chart-fix")["state"], "closing")

    @unittest.skipUnless(shutil.which("tmux"), "no tmux")
    def test_a_tmux_pane_process_gets_its_signal(self):
        # tmux continues a pane process that gets SIGSTOP at once (a `lane open` tab's claude
        # is one), so a check that froze its target first never got a signal through.
        lane_mod = load_lane_script()
        sock = os.path.join(self.tmp, "tmux.sock")
        tmux = ["tmux", "-S", sock, "-f", "/dev/null"]
        started = subprocess.run([*tmux, "new-session", "-d", "sleep 300"], env=self.env,
                                 capture_output=True, text=True)
        if started.returncode != 0:  # the Bash sandbox refuses a unix socket's connect
            self.skipTest(f"tmux can't start a server here: {started.stderr.strip()}")
        self.addCleanup(subprocess.run, [*tmux, "kill-server"], env=self.env,
                        capture_output=True)
        pane = int(subprocess.run([*tmux, "display", "-p", "#{pane_pid}"], env=self.env,
                                  capture_output=True, text=True, check=True).stdout)
        proc = lanelib.scan()[pane]
        self.assertIsNone(lane_mod.guarded(proc, signal.SIGTERM, self.common))
        deadline = time.monotonic() + 5
        while lanelib.proc_alive(proc) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(lanelib.proc_alive(proc))

    def test_a_process_started_during_the_close_refuses_in_round_two(self):
        # Unprovable and new (a session's exit left it behind): the close stops there, the
        # lane stays closing, and nothing is archived.
        self.hand_off()
        ready = os.path.join(self.tmp, "stray-ready")
        argv = shlex.join([sys.executable, self.fake_py, json.dumps(self.fake(self.path))])
        spawn = (f"{argv} </dev/null >{ready} 2>/dev/null & "
                 f"while [ ! -s {ready} ]; do sleep 0.05; done")
        (claude,) = self.claude(on_term=[["sh", "-c", spawn], ""])
        p = self.run_lane("done", "chart-fix", "--abandon")
        (stray,) = [int(x) for x in self.read(ready).split()[1:]]
        self.starts[stray] = lanelib.proc_start(stray)
        self.addCleanup(self.kill_ours, [stray])
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"ended {claude}", p.stdout, p.stderr)
        self.assertIn("lane chart-fix is closing, and nothing proves these lane chart-fix's",
                      p.stderr)
        self.assertIn(f"{stray} python", p.stderr)
        self.assertIn("(no session id in its environment)", p.stderr)
        self.assertTrue(self.alive(stray))
        self.assertEqual(self.signals(), [(claude, "SIGTERM")])
        self.assertEqual(self.lane_json("chart-fix")["state"], "closing")
        self.assertTrue(os.path.isdir(self.path))
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "_closed")))

    def test_a_session_ended_in_round_two_is_forgotten_even_with_the_restore_lock_held(self):
        # A leftover's exit starts a lane session (claude-restore reopening it, say): round 2
        # ends it and deletes its open-sessions entry by id. claude-restore holds .lock, so
        # the sweep keeps the rest, with a warning, and done still closes.
        self.hand_off()
        self.transcript("sess-lane-0003", self.path)
        ready = os.path.join(self.tmp, "late-ready")
        late = self.fake(self.path, session={
            "file": os.path.join(self.home, ".claude", "sessions", "late.json"),
            "sid": "sess-lane-0005"})
        argv = shlex.join([sys.executable, self.fake_py, json.dumps(late)])
        spawn = (f"{argv} </dev/null >{ready} 2>/dev/null & "
                 f"while [ ! -s {ready} ]; do sleep 0.05; done")
        (left,) = self.start(self.fake(self.path, "sess-lane-0003",
                                       on_term=[["sh", "-c", spawn], ""]))
        entry = self.open_session_entry("sess-lane-0005", self.path)
        stray = self.open_session_entry("sess-lane-0009", self.path)
        fd = os.open(os.path.join(os.path.dirname(entry), ".lock"), os.O_WRONLY | os.O_CREAT)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        p = self.run_lane("done", "chart-fix", "--abandon")
        (s2,) = [int(x) for x in self.read(ready).split()[1:]]
        self.starts[s2] = int(json.loads(self.read(late["session"]["file"]))["procStart"])
        self.addCleanup(self.kill_ours, [s2])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn(f"ended {left} ", p.stdout)
        self.assertRegex(p.stdout, rf"ended {s2} \S+ \(lane session sess-lane-0005\)")
        self.assertFalse(os.path.exists(entry))
        self.assertTrue(os.path.exists(stray))
        self.assertIn(".lock is held", p.stderr)
        self.assertClosed()

    # ---- 5-8. what an environment can't prove ----------------------------------------------

    def test_a_leftover_with_a_foreign_or_no_session_id_refuses(self):
        self.hand_off()
        (claude,) = self.claude()
        self.transcript("sess-main-0003", self.main)
        (foreign,) = self.start(self.fake(self.path, "sess-main-0003"))
        (bare,) = self.start(self.fake(self.path))
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn(f"{foreign} {self.comms[foreign]} (session sess-main-0003 is not lane "
                      "chart-fix's)", p.stderr)
        self.assertIn(f"{bare} {self.comms[bare]} (no session id in its environment)", p.stderr)
        self.assertIn("nothing was signalled", p.stderr)
        self.assertRefusedUntouched(p, foreign, bare, claude)
        self.assertNotIn(f"\n  {claude} ", p.stderr)  # the lane's own session is no refusal

    def test_a_session_id_only_lane_json_holds_is_no_proof(self):
        # The SessionStart hook lists it in sessions[], which sandboxed Bash can write too.
        self.hand_off()
        self.hook("lane-identity.sh", {"session_id": "sess-lane-0004", "cwd": self.path,
                                       "source": "startup", "hook_event_name": "SessionStart"})
        self.assertIn("sess-lane-0004", json.dumps(self.lane_json("chart-fix")["sessions"]))
        (left,) = self.start(self.fake(self.path, "sess-lane-0004"))
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn("(session sess-lane-0004 is not lane chart-fix's)", p.stderr)
        self.assertRefusedUntouched(p, left)

    def test_a_leftover_with_a_child_outside_the_lane_refuses(self):
        # A tmux server started from a lane Bash carries the lane's id; its panes run elsewhere.
        self.hand_off()
        self.transcript("sess-lane-0003", self.path)
        server, pane = self.start(self.fake(self.path, "sess-lane-0003", children=[
            self.fake(self.tmp, "sess-lane-0003")]))
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn(f"{pane} {self.comms[pane]} (runs under {server} {self.comms[server]} "
                      "(carries lane session sess-lane-0003), outside lane chart-fix)", p.stderr)
        self.assertRefusedUntouched(p, server, pane)

    def test_a_process_outside_the_lane_with_a_lane_session_id_is_untouched(self):
        self.transcript("sess-lane-0003", self.path)
        (outside,) = self.start(self.fake(self.tmp, "sess-lane-0003"))
        self.assertIn("closed (abandoned)", self.lane("done", "chart-fix", "--abandon"))
        self.assertTrue(self.alive(outside))
        self.assertEqual(self.signals(), [])
        self.assertClosed()

    # ---- 9. refusals that signal nothing ---------------------------------------------------

    def test_a_background_session_refuses_with_its_claude_stop(self):
        self.hand_off()
        (bg,) = self.start(self.fake(self.path))
        self.session_file(bg, kind="bg", jobId="job-1234abcd")
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn(f"{bg} {self.comms[bg]} (background session {self.SID}, which the daemon "
                      "owns: run `claude stop job-1234abcd`)", p.stderr)
        self.assertRefusedUntouched(p, bg)

    def test_only_the_lead_closes_lanes(self):
        # Another lane's session, cd'd to the main checkout or not, never closes this lane.
        self.hand_off()
        (claude,) = self.claude()
        self.lane("new", "api-docs")
        api = self.lane_path("api-docs")
        peer, go, out = self.done_under(self.fake(api))
        self.session_file(peer, "sess-api-0001", cwd=api)
        res = self.await_done(go, out)
        self.assertEqual(res["rc"], 1, res["err"])
        self.assertIn("only the lead (the main checkout) closes lanes", res["err"])
        self.assertIn(f"runs under session sess-api-0001 ({peer} {self.comms[peer]}), in linked "
                      f"worktree {api}", res["err"])
        self.assertTrue(self.alive(peer))
        p = self.run_lane("done", "chart-fix", "--abandon", cwd=api)
        self.assertIn("refusing: only the lead (the main checkout) closes lanes: run `lane done "
                      f"chart-fix` from {self.main}", p.stderr)
        self.assertRefusedUntouched(p, claude)
        # The lane's own session, from the main checkout's cwd, and a run from inside the lane.
        self.kill_ours([claude])
        os.remove(os.path.join(self.tmp, "done.json"))
        os.remove(os.path.join(self.tmp, "go"))
        claude, go, out = self.done_under(self.fake(self.path))
        self.session_file(claude)
        res = self.await_done(go, out)
        self.assertIn(f"runs under session {self.SID}", res["err"])
        p = self.run_lane("done", "chart-fix", "--abandon", cwd=self.path)
        self.assertIn("only the lead (the main checkout) closes lanes", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_a_planted_lane_path_never_refuses_the_lead(self):
        # Whether a session above `done` is a lane's is never read from lane.json, which
        # sandboxed Bash can write: one whose path holds the main checkout ("/home" on a real
        # machine) refused every `done` the lead ran.
        rec = dict(self.lane_json("chart-fix"), id="planted", path=self.main, port=None)
        self.write(os.path.join(self.common, "lanes", "planted", "lane.json"), json.dumps(rec))
        lead, go, out = self.done_under(self.fake(self.main))
        self.session_file(lead, "sess-main-0001", cwd=self.main)
        res = self.await_done(go, out)
        self.assertEqual(res["rc"], 0, res["err"])
        self.assertClosed()

    def test_a_session_under_the_lanes_root_or_in_a_linked_worktree_is_no_lead(self):
        # Neither is a registered lane, and both refuse: the root comes from the config in the
        # state dir, the worktree from git's own links.
        scratch = os.path.join(self.root, "scratch")
        os.makedirs(scratch)
        other = os.path.join(self.tmp, "elsewhere", "side")
        self.git("worktree", "add", "-q", "-b", "side", other, "origin/main")
        for cwd, where in ((scratch, f"under the lanes root {self.root}"),
                           (other, f"in linked worktree {other}")):
            with self.subTest(cwd=cwd):
                for name in ("go", "done.json"):
                    with contextlib.suppress(FileNotFoundError):
                        os.remove(os.path.join(self.tmp, name))
                pid, go, out = self.done_under(self.fake(cwd))
                self.session_file(pid, "sess-other-0001", cwd=cwd)
                res = self.await_done(go, out)
                self.assertEqual(res["rc"], 1, res["err"])
                self.assertIn(f"runs under session sess-other-0001 ({pid} {self.comms[pid]}), "
                              f"{where}", res["err"])
                self.kill_ours([pid])
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertTrue(os.path.isdir(self.path))

    def test_done_refuses_to_run_under_a_process_it_would_end(self):
        # The self-guard: a leftover of the lane (no session file) runs `lane done`.
        self.hand_off()
        self.transcript("sess-lane-0003", self.path)
        left, go, out = self.done_under(self.fake(self.path, "sess-lane-0003"))
        res = self.await_done(go, out)
        self.assertEqual(res["rc"], 1, res["err"])
        self.assertIn("this `lane done` runs inside lane chart-fix", res["err"])
        self.assertTrue(self.alive(left))
        self.assertEqual(self.signals(), [])
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def test_a_dirty_or_locked_worktree_refuses_before_any_signal(self):
        self.hand_off()
        (claude,) = self.claude()
        self.write(os.path.join(self.path, "notes.txt"), "draft\n")
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn("uncommitted or untracked files (notes.txt)", p.stderr)
        self.assertRefusedUntouched(p, claude)
        os.remove(os.path.join(self.path, "notes.txt"))
        self.git("worktree", "lock", self.path)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn("worktree is locked", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_a_failing_closing_check_refuses_before_any_signal(self):
        (claude,) = self.claude()  # the seeded record's Next is still empty
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn("lane chart-fix's handoff is incomplete, so nothing was signalled", p.stderr)
        self.assertIn("handoff-check --closing: chart-fix", p.stderr)
        self.assertIn("## Next", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_a_lane_that_holds_the_install_refuses_before_any_signal(self):
        # Installed links into the lane (setup.sh run from it): removing the worktree would
        # break every session's hooks, so done refuses until the lead's reinstall from main.
        self.hand_off()
        (claude,) = self.claude()
        hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(hooks)
        link = os.path.join(hooks, "lane-identity.sh")
        os.symlink(os.path.join(self.path, "hooks", "lane-identity.sh"), link)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn("lane chart-fix holds the install", p.stderr)
        self.assertIn("~/.claude/hooks/lane-identity.sh -> ", p.stderr)
        # Each line names its installer (setup.sh, setup-tmux.sh or by hand) once
        # install-state.py says so; the fix is the same sentence either way.
        self.assertIn("The lead reruns the installer each line names from the main checkout "
                      f"{self.main}, then reruns `lane done chart-fix`", p.stderr)
        self.assertRefusedUntouched(p, claude)
        # The board names the holder; once main relinks it, the hold is gone and done goes on.
        self.assertIn("install: held by lane chart-fix (branch chart-fix, 1 link)",
                      self.lane("ls"))
        os.remove(link)
        self.assertNotIn("install:", self.lane("ls"))
        self.lane("done", "chart-fix", "--abandon")
        self.assertClosed()

    def test_an_install_made_during_the_close_refuses_before_the_remove(self):
        # setup.sh from the lane, run after the first links check: checked again under
        # install.lock just before `git worktree remove`, which never runs.
        self.hand_off()
        hooks = os.path.join(self.home, ".claude", "hooks")
        link = os.path.join(hooks, "lane-identity.sh")
        relink = (f"mkdir -p {hooks} && ln -s {self.path}/hooks/lane-identity.sh {link}")
        (claude,) = self.claude(on_term=[["sh", "-c", relink], ""])
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"ended {claude}", p.stdout)
        self.assertIn("lane chart-fix holds the install", p.stderr)
        self.assertIn("~/.claude/hooks/lane-identity.sh -> ", p.stderr)
        self.assertTrue(os.path.isdir(self.path))
        self.assertIn(self.path, self.git("worktree", "list"))
        self.assertEqual(self.lane_json("chart-fix")["state"], "closing")
        self.assertEqual(os.listdir(os.path.join(self.common, "lanes", "_closed")), [])
        # Once the lead relinks, a rerun closes it.
        os.remove(link)
        self.lane("done", "chart-fix", "--abandon")
        self.assertClosed()

    def test_done_waits_for_a_running_install_then_refuses(self):
        lane_mod = load_lane_script()
        state = os.path.join(self.tmp, "state", "dotclaude")
        os.makedirs(state, exist_ok=True)
        fd = os.open(os.path.join(state, "install.lock"), os.O_WRONLY | os.O_CREAT, 0o644)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)  # setup.sh's hold, for its whole run
        with mock.patch.object(lane_mod, "INSTALL_LOCK_WAIT", 0.3):
            start = time.monotonic()
            with self.assertRaisesRegex(lane_mod.LaneError, r"install\.lock is held past 0\.3 s: "
                                        "by a setup.sh run, or by anything holding it open"):
                with lane_mod.install_lock():
                    self.fail("held the install lock while setup.sh holds it")
            self.assertGreaterEqual(time.monotonic() - start, 0.3)
            fcntl.flock(fd, fcntl.LOCK_UN)
            with lane_mod.install_lock():
                pass

    def test_done_waits_for_an_install_without_holding_the_lanes_lock(self):
        # Every lane's hooks take the lanes lock with a 2 s timeout, so done waits for setup.sh's
        # install.lock first and takes the lanes lock only once it holds that.
        state = os.path.join(self.tmp, "state", "dotclaude")
        os.makedirs(state, exist_ok=True)
        fd = os.open(os.path.join(state, "install.lock"), os.O_WRONLY | os.O_CREAT, 0o644)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)  # setup.sh's hold, for its whole run
        p = subprocess.Popen([sys.executable, LANE, "done", "chart-fix", "--abandon"],
                             cwd=self.main, env=self.env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: p.poll() is None and p.kill())
        time.sleep(2)  # done has reached the install wait by now
        self.assertIsNone(p.poll(), "done finished while setup.sh held install.lock")
        with lanelib.lock(lanelib.resolve(self.main), timeout=1):
            pass  # free while done waits
        fcntl.flock(fd, fcntl.LOCK_UN)
        out, err = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, out + err)
        self.assertClosed()

    def hold_lanes_lock(self):
        """Take the lanes lock, as a sandboxed `lane claim` stuck under it would hold it; returns
        its release, which cleanup calls too."""
        fd = [os.open(os.path.join(self.common, "lanes", ".lock"), os.O_WRONLY | os.O_CREAT,
                      0o644)]
        fcntl.flock(fd[0], fcntl.LOCK_EX)

        def release():
            if fd:
                os.close(fd.pop())  # closing it drops the flock

        self.addCleanup(release)
        return release

    def archives(self):
        closed = os.path.join(self.common, "lanes", "_closed")
        return os.listdir(closed) if os.path.isdir(closed) else []

    def git_after_remove(self, lane_mod, then):
        """lane_mod.git patched to call then() right after a `git worktree remove`."""
        real = lane_mod.git

        def git(args, cwd, **kw):
            p = real(args, cwd, **kw)
            if args[:2] == ["worktree", "remove"]:
                then()
            return p

        return mock.patch.object(lane_mod, "git", side_effect=git)

    def test_a_held_lanes_lock_never_blocks_done_while_it_holds_install_lock(self):
        # setup.sh waits on install.lock meanwhile: done gives the lanes lock LANES_LOCK_WAIT,
        # then refuses cleanly with nothing archived or removed. (One that blocks would close
        # the lane once the timer below frees the lock.)
        lane_mod = load_lane_script()
        timer = threading.Timer(10, self.hold_lanes_lock())
        timer.start()
        self.addCleanup(timer.cancel)
        with mock.patch.object(lane_mod, "LANES_LOCK_WAIT", 0.3):
            with self.assertRaisesRegex(lane_mod.LaneError, r"lanes lock \S+ is held past 0\.3 s "
                                        r".*: nothing was archived or removed: rerun `lane done "
                                        "chart-fix`"):
                self.done_in_process(lane_mod)
        self.assertTrue(os.path.isdir(self.path))
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertEqual(self.archives(), [])

    def test_a_held_lanes_lock_when_marking_closing_refuses_before_any_signal(self):
        lane_mod = load_lane_script()
        (pid,) = self.start(self.fake(self.tmp))
        self.addCleanup(self.kill_ours, [pid])
        hit = lane_mod.Hit(lanelib.scan()[pid], lane_mod.LEFTOVER, "a test leftover")
        self.hold_lanes_lock()
        with mock.patch.object(lane_mod, "survey", return_value=({pid: hit}, {})), \
                mock.patch.object(lane_mod, "closing_check"), \
                mock.patch.object(lane_mod, "LANES_LOCK_WAIT", 0.3):
            with self.assertRaisesRegex(lane_mod.LaneError, r"held past 0\.3 s .*: nothing was "
                                        "signalled: rerun `lane done chart-fix`"):
                self.done_in_process(lane_mod)
        self.assertEqual(self.signals(), [])
        self.assertTrue(self.alive(pid))
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertEqual(glob.glob(self.proof()), [])  # no record outlives a run that stopped

    def test_the_remove_runs_without_the_lanes_lock_and_a_timeout_after_it_is_clean(self):
        # `git worktree remove` can take seconds, and every lane's hooks give up on the lanes
        # lock after 2 s: done holds only install.lock across it. A lanes lock held past
        # LANES_LOCK_WAIT once the remove is done refuses cleanly, with no partial archive, and
        # a rerun archives the record.
        lane_mod = load_lane_script()
        releases = []

        def then():
            with lanelib.lock(lanelib.resolve(self.main), timeout=0.5):
                pass  # a hook's take, during the remove
            releases.append(self.hold_lanes_lock())

        with self.git_after_remove(lane_mod, then), \
                mock.patch.object(lane_mod, "LANES_LOCK_WAIT", 0.3):
            with self.assertRaisesRegex(lane_mod.LaneError, r"held past 0\.3 s .*: lane "
                                        "chart-fix's record is not archived, and its worktree is "
                                        "gone: rerun `lane done chart-fix`"):
                self.done_in_process(lane_mod)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.archives(), [])
        releases.pop()()
        self.assertIn("closed (abandoned)", self.lane("done", "chart-fix", "--abandon"))
        self.assertClosed()
        self.assertEqual(len(self.archives()), 1)

    def test_a_record_changed_during_the_remove_is_never_archived(self):
        # The lanes lock is free during the remove, so lane.json is read once more after it.
        lane_mod = load_lane_script()
        rec = os.path.join(self.common, "lanes", "chart-fix", "lane.json")

        def moved():
            self.write(rec, json.dumps(dict(self.lane_json("chart-fix"), branch="elsewhere")))

        with self.git_after_remove(lane_mod, moved):
            with self.assertRaisesRegex(lane_mod.LaneError, "path or branch changed during the "
                                                            "close"):
                self.done_in_process(lane_mod)
        self.assertEqual(self.archives(), [])
        self.assertEqual(self.lane_json("chart-fix")["branch"], "elsewhere")

    def test_an_install_check_that_fails_before_the_remove_says_what_was_done(self):
        # Its second run, after any signal: "nothing was signalled" would be false by then.
        lane_mod = load_lane_script()
        ok = types.SimpleNamespace(links_into=lambda path: [])
        with mock.patch.object(lane_mod, "install_state", side_effect=[ok, RuntimeError("boom")]):
            with self.assertRaises(lane_mod.LaneError) as caught:
                self.done_in_process(lane_mod)
        self.assertEqual(str(caught.exception), "can't check the install for links into lane "
                         "chart-fix (RuntimeError: boom), so its worktree was not removed")
        self.assertTrue(os.path.isdir(self.path))
        self.assertEqual(self.archives(), [])

    def test_a_tmux_conf_block_into_the_lane_holds_it_too(self):
        # setup-tmux.sh run from the lane: the next tmux server would source a removed file.
        self.write(os.path.join(self.home, ".tmux.conf"),
                   "# >>> dotclaude tmux (setup-tmux.sh) >>>\n"
                   f'source-file "{self.path}/tmux/claude.conf"\n'
                   "# <<< dotclaude tmux <<<\n")
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("~/.tmux.conf: source-file", p.stderr)
        self.assertTrue(os.path.isdir(self.path))

    # ---- 10, 11. the record ----------------------------------------------------------------

    def session_end(self, first):
        """A fake session's on_term: the real SessionEnd hook (lane_identity), once the shell
        command first is done."""
        self.hook("lane-identity.sh", {"session_id": self.SID, "cwd": self.path,
                                       "source": "startup", "hook_event_name": "SessionStart"})
        end = json.dumps({"session_id": self.SID, "cwd": self.path, "reason": "other",
                          "hook_event_name": "SessionEnd"})
        hook = os.path.join(HOOKS, "lane-identity.sh")
        return [["bash", "-c", f"{first}; exec bash {hook}"], end]

    def assertEndedAtArchived(self):
        closed = os.path.join(self.common, "lanes", "_closed")
        (archive,) = os.listdir(closed)
        with open(os.path.join(closed, archive, "lane.json")) as f:
            rec = json.load(f)
        (session,) = rec["sessions"]
        self.assertEqual((session["session_id"], session["reason"]), (self.SID, "other"))
        self.assertTrue(session.get("endedAt"))
        self.assertEqual(rec["state"], "abandoned")

    def test_grace_outlasts_the_sessionend_hook_timeout(self):
        # Claude Code lets a SessionEnd hook run up to its timeout; round 1 must wait longer,
        # or round 2 ends a hook mid-run and its endedAt (and the mirror) are lost.
        with open(os.path.join(os.path.dirname(HOOKS), "settings.json")) as f:
            groups = json.load(f)["hooks"]["SessionEnd"]
        timeouts = [h["timeout"] for g in groups for h in g["hooks"]]
        self.assertTrue(timeouts and all(isinstance(t, (int, float)) for t in timeouts))
        self.assertGreaterEqual(load_lane_script().GRACE, 2 * max(timeouts))

    def test_a_sessionend_stamp_made_during_the_close_reaches_the_archive(self):
        # The lanes lock is free while `done` signals, so the session's SessionEnd hook (the
        # real one) stamps endedAt, and the archive is built from the record re-read after it.
        # The default grace, and a hook that takes most of its 5 s timeout.
        del self.env["_LANE_TEST_GRACE"]
        self.hand_off()
        self.claude(on_term=self.session_end("sleep 4.5"))
        self.lane("done", "chart-fix", "--abandon")
        self.assertEndedAtArchived()

    def test_a_session_still_exiting_in_round_two_keeps_its_hook(self):
        # Its session file gone mid-exit and its hook past round 1: the hook is still the
        # session's (OWNED), never refused or signalled, and its endedAt reaches the archive.
        # Event-driven, not timed: the hook starts on round 2's SIGTERM (the second in the
        # log), so the session is still exiting when round 2 looks, and the hook has all of
        # round 2's grace to finish.
        self.env["_LANE_TEST_GRACE"] = "4"
        self.hand_off()
        drop = os.path.join(self.home, ".claude", "sessions", "{pid}.json")
        round_two = (f"until [ \"$(grep -c ' SIGTERM$' {shlex.quote(self.log)})\" -ge 2 ]; "
                     "do sleep 0.05; done")
        pid, *_ = self.start(self.fake(self.path, on_term=self.session_end(round_two), drop=drop))
        self.session_file(pid)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.signals(), [(pid, "SIGTERM"), (pid, "SIGTERM")])
        self.assertEndedAtArchived()

    def test_open_refuses_a_closing_lane_and_a_second_done_refuses_cleanly(self):
        rec = self.lane_json("chart-fix")
        self.write(os.path.join(self.common, "lanes", "chart-fix", "lane.json"),
                   json.dumps(dict(rec, state="closing")))
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 1)
        self.assertIn("is closing", p.stderr)
        self.lane("done", "chart-fix", "--abandon")
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no lane chart-fix", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    # ---- a close with nothing to end -------------------------------------------------------

    def done_in_process(self, lane_mod):
        """cmd_done in this process, from the main checkout, with the fixture's environment."""
        cwd = os.getcwd()
        os.chdir(self.main)
        try:
            with mock.patch.dict(os.environ, self.env, clear=True):
                lane_mod.cmd_done(argparse.Namespace(id="chart-fix", abandon=True))
        finally:
            os.chdir(cwd)

    def test_dones_git_never_takes_its_config_from_a_commondir_the_lane_repoints(self):
        # A lane can write its admin dir: repointed after worktree_problem's check, commondir
        # would hand `done`'s sandbox-off git a config whose core.fsmonitor runs a command.
        lane_mod = load_lane_script()
        with open(os.path.join(self.path, ".git")) as f:
            admin = os.path.join(self.path, f.read().strip().removeprefix("gitdir: "))
        commondir = os.path.join(admin, "commondir")
        real_common = self.read(commondir)
        fake = os.path.join(self.tmp, "fake-common")
        shutil.copytree(self.common, fake, symlinks=True,
                        ignore=shutil.ignore_patterns("worktrees", "lanes"))
        ran, hook = os.path.join(self.tmp, "fsmonitor-ran"), os.path.join(self.tmp, "fsmon")
        self.write(hook, f"#!/bin/sh\ntouch {ran}\n")
        os.chmod(hook, 0o755)
        with open(os.path.join(fake, "config"), "a") as f:
            f.write(f"[core]\n\tfsmonitor = {hook}\n")

        def repoint():
            self.write(commondir, fake + "\n")

        repoint()  # the attack is real: a plain git status in the lane runs the hook
        subprocess.run(["git", "status"], cwd=self.path, env=self.env, capture_output=True)
        self.assertTrue(os.path.exists(ran))
        os.unlink(ran)
        repo = lanelib.resolve(self.main)
        self.assertIn("commondir", lanelib.worktree_problem(repo, self.path,
                                                            repo.lanes(shared=True)))
        self.write(commondir, real_common)
        real = lane_mod.usable_path

        def usable(*args):
            out = real(*args)
            repoint()
            return out

        with mock.patch.object(lane_mod, "usable_path", side_effect=usable):
            self.done_in_process(lane_mod)
        self.assertFalse(os.path.exists(ran))
        self.assertClosed()

    def test_a_repo_with_per_worktree_config_refuses_before_any_git_in_the_lane(self):
        # config.worktree sits in the lane-writable admin dir, and GIT_COMMON_DIR can't keep
        # git from reading it once extensions.worktreeConfig is on.
        lane_mod = load_lane_script()
        self.git("config", "extensions.worktreeConfig", "true")
        (pid,) = self.claude()
        with mock.patch.object(lane_mod, "removable") as removable:
            with self.assertRaisesRegex(lane_mod.LaneError, "extensions.worktreeConfig"):
                self.done_in_process(lane_mod)
        removable.assert_not_called()
        self.assertTrue(self.alive(pid))
        self.assertEqual(self.signals(), [])
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        # With its worktree gone no git runs in the lane, so nothing refuses the close.
        self.kill_ours([pid])
        self.assertTrue(self.gone(pid))
        self.git("worktree", "remove", "--force", self.path)
        self.done_in_process(lane_mod)
        self.assertClosed()

    def test_a_worktree_gone_at_the_gates_that_reappears_is_never_removed(self):
        # Deleted but still registered: nothing checked it, so `git worktree remove` (which runs
        # git in it) must not run once it is back.
        lane_mod = load_lane_script()
        shutil.rmtree(self.path)
        with mock.patch.object(lane_mod, "sweep_open_sessions",
                               side_effect=lambda _p: os.makedirs(self.path)):
            with self.assertRaisesRegex(lane_mod.LaneError, "reappeared during the close"):
                self.done_in_process(lane_mod)
        self.assertEqual(self.archives(), [])
        self.assertTrue(os.path.isdir(self.path))
        self.assertIn(self.path, self.git("worktree", "list", "--porcelain"))

    def test_an_archive_build_that_fails_any_way_leaves_no_partial_archive(self):
        lane_mod = load_lane_script()
        with mock.patch.object(lanelib, "copy_record", side_effect=RecursionError("deep")):
            with self.assertRaises(RecursionError):
                self.done_in_process(lane_mod)
        self.assertEqual(self.archives(), [])
        self.assertTrue(os.path.isdir(self.path))

    def test_a_process_started_after_the_final_look_keeps_the_worktree(self):
        # With nothing to end the lane is never closing, so `open` could start a session
        # during the lock waits: the remove looks once more.
        lane_mod = load_lane_script()
        late = []
        real = lane_mod.install_hold

        def hold(*args):
            real(*args)
            if args[-1] == "its worktree was not removed":
                late.extend(self.start(self.fake(self.path)))

        with mock.patch.object(lane_mod, "install_hold", side_effect=hold):
            with self.assertRaisesRegex(lane_mod.LaneError, "started in .* during the close, so "
                                        "lane chart-fix's worktree was not removed"):
                self.done_in_process(lane_mod)
        self.assertEqual(len(late), 1)
        self.assertTrue(os.path.isdir(self.path))
        self.assertEqual(self.archives(), [])
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def test_a_refusal_with_nothing_to_end_leaves_the_lane_as_it_was(self):
        # Never `closing` (which `open` refuses) unless something got signalled: the final look
        # finding a process that started after the survey, then a refused worktree remove.
        lane_mod = load_lane_script()
        (late,) = self.start(self.fake(self.path))
        with mock.patch.object(lane_mod, "survey", return_value=({}, {})):
            with self.assertRaisesRegex(lane_mod.LaneError, "started during the close"):
                self.done_in_process(lane_mod)
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertEqual(self.signals(), [])
        self.kill_ours([late])
        self.assertTrue(self.gone(late))
        self.write(os.path.join(self.path, "notes.txt"), "draft\n")
        with mock.patch.object(lane_mod, "removable"):
            with self.assertRaisesRegex(lane_mod.LaneError, "git worktree remove refused"):
                self.done_in_process(lane_mod)
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertTrue(os.path.isdir(self.path))
        self.assertEqual(os.listdir(os.path.join(self.common, "lanes", "_closed")), [])

    # ---- the signal itself -----------------------------------------------------------------

    def test_a_reused_pid_is_never_signalled_with_or_without_a_pidfd(self):
        lane_mod = load_lane_script()
        (pid,) = self.start(self.fake(self.tmp))
        proc = lanelib.scan()[pid]
        stale = proc._replace(start=proc.start + 1)
        self.assertFalse(lane_mod.signal_proc(stale, signal.SIGTERM))
        refused = OSError(errno.ENOSYS, "pidfd_open blocked")
        with mock.patch.object(lane_mod.os, "pidfd_open", side_effect=refused):
            self.assertFalse(lane_mod.signal_proc(stale, signal.SIGTERM))
            self.assertTrue(self.alive(pid))
            self.assertEqual(self.signals(), [])
            self.assertTrue(lane_mod.signal_proc(proc, signal.SIGTERM))
        self.assertTrue(self.gone(pid))
        self.assertEqual(self.signals(), [(pid, "SIGTERM")])


class LeadChain(Fakes):
    """Fake sessions in a chain, the nearest of which runs a command as Claude Code would (a
    lead act, or a hook with its event); each one whose TMUX names this test runner as its
    server. LeadAct's harness, without its tests, for test_hooks.LeadHeal to build on."""

    MAIN_SID = "sess-main-0001"

    def setUp(self):
        super().setUp()
        self.socks = os.path.join(self.tmp, "socks")
        os.makedirs(self.socks)
        self.tmux_sock = os.path.join(self.tmp, "tmux-sock", "default")
        self.acts = 0

    def act(self, argv, run_in=None, **session):
        """A fake session (session: the keywords session() takes) runs `lane <argv>` from run_in
        (the main checkout by default); its pid and the act's {rc, out, err}."""
        (pid,), res = self.acts_in_chain(argv, [session], run_in)
        return pid, res

    def chain(self, argv, under, run_in=None, **session):
        """act, from a fake session that another one (under: session() keywords) started, so
        the act's nearest session is not the only one above it; both pids, the farther first,
        and the act's {rc, out, err}."""
        (top, pid), res = self.acts_in_chain(argv, [under, session], run_in)
        return top, pid, res

    def acts_in_chain(self, argv, sessions, run_in=None):
        """Fake sessions (each session()'s keywords), each started by the one before it, the
        last of which runs `lane <argv>` from run_in (the main checkout by default) once their
        session files are written; their pids, the first started first, and the act's result.
        A fake on a pane runs with TMUX naming this test runner as its server."""
        return self.runs_in_chain([sys.executable, LANE, *argv], sessions, run_in)

    def runs_in_chain(self, cmd, sessions, run_in=None, stdin=None, before=None):
        """acts_in_chain for any command (cmd, a full argv, run with stdin), calling before
        with the pids once their session files are written, just ahead of the run."""
        self.acts += 1
        go = os.path.join(self.tmp, f"go{self.acts}")
        out = os.path.join(self.tmp, f"done{self.acts}.json")
        extra = {"then": {"argv": cmd, "cwd": run_in or self.main, "stdin": stdin, "go": go,
                          "out": out}}  # the nearest runs the act
        for kw in reversed(sessions):
            cfg = self.fake(kw.get("real_cwd") or kw.get("cwd") or self.main, **extra)
            if pane := kw.get("pane", "%3"):
                cfg["env"].update(TMUX=f"{self.tmux_sock},{os.getpid()},0", TMUX_PANE=pane)
            extra = {"children": [cfg]}  # the next one out starts it
        pids = self.start(cfg)
        for pid, kw in zip(pids, sessions):
            if kw.get("file", True):  # file=False: a session whose file isn't written yet
                self.session(pid, **{k: v for k, v in kw.items() if k not in ("real_cwd",
                                                                               "file")})
        if before:
            before(pids)
        return pids, self.await_done(go, out)

    def session(self, pid, cwd=None, sid=MAIN_SID, kind="interactive", pane="%3", sock=True,
                **extra):
        """pid's session file: launched in cwd (the main checkout by default), of kind, on pane
        (None: no tmux), with a messaging socket unless sock is False, and extra in it."""
        path = os.path.join(self.socks, f"{pid}.sock")
        if sock:
            os.mknod(path, stat.S_IFSOCK | 0o600)
        self.session_file(pid, sid, cwd=cwd or self.main, kind=kind, messagingSocketPath=path,
                          **({"tmux": f"proj:@3.{pane}"} if pane else {}), **extra)

    def assertLead(self, pid, sid=MAIN_SID, pane="%3"):
        rec = self.lead()
        self.assertIsNotNone(rec, "no lead record")
        tmux = [self.tmux_sock, os.getpid(), lanelib.proc_start(os.getpid()), pane]
        self.assertEqual({k: v for k, v in rec.items() if k != "at"},
                         {"pid": pid, "procStart": self.starts[pid], "sessionId": sid,
                          "tmux": tmux if pane else None})
        self.assertIsNotNone(lanelib.parse_iso(rec["at"]))
        self.assertIsNotNone(lanelib.read_lead(lanelib.Repo(self.main, self.common)))


class LeadAct(LeadChain):
    """A bare lead act (init, new, adopt, open without --print, done) that succeeds records the
    nearest Claude session above it as the lead, when that session is interactive, has a socket
    and launched in the main checkout; `lane lead` does the same or says why it can't. Each
    session is a fake here whose TMUX names this test runner as its server."""

    def test_a_new_from_the_main_checkout_takes_the_lead(self):
        pid, res = self.act(["new", "api-docs"])
        self.assertEqual(res["rc"], 0, res["err"])
        self.assertLead(pid)
        self.assertEqual(len(self.config_files()), 1)  # the record is no config

    def test_each_lead_act_takes_it(self):
        self.git("worktree", "add", "-q", "-b", "side", os.path.join(self.root, "side"))
        # A real `open` (chart-fix has no live session): the fake's TMUX is set, and a tmux on
        # PATH that opens the window.
        tmux = os.path.join(self.fake_bin, "tmux")
        self.write(tmux, "#!/bin/sh\n[ \"$1\" = new-window ] && echo 'proj:3 (chart-fix)'\n"
                         "exit 0\n")
        os.chmod(tmux, 0o755)
        for n, argv in enumerate((["init"], ["adopt", os.path.join(self.root, "side")],
                                  ["done", "side", "--abandon"], ["open", "chart-fix"])):
            with self.subTest(argv=argv):
                pid, res = self.act(argv, sid=f"sess-main-000{n}")
                self.assertEqual(res["rc"], 0, res["err"])
                self.assertLead(pid, f"sess-main-000{n}")
        self.assertEqual(res["out"], "opened chart-fix in tmux window proj:3 (chart-fix)\n")
        self.assertIn("opened", self.lane_json("chart-fix"))

    def test_a_refused_or_failed_act_leaves_the_lead_where_it_was(self):
        _, res = self.act(["new", "chart-fix"])  # it exists
        self.assertEqual(res["rc"], 1)
        self.assertIsNone(self.lead())
        lead, res = self.act(["new", "api-docs"], sid="sess-main-0002")
        self.assertLead(lead, "sess-main-0002")
        _, res = self.act(["done", "nope"], sid="sess-main-0003")
        self.assertEqual(res["rc"], 1)
        self.assertLead(lead, "sess-main-0002")

    def test_a_look_or_open_print_never_takes_it(self):
        for argv in (["open", "chart-fix", "--print"], ["ls"], ["addr", "lead"], ["whoami"]):
            with self.subTest(argv=argv):
                pid, res = self.act(argv)
                self.assertEqual(res["rc"], 0, res["err"])  # a failed run proves nothing
                self.assertIsNone(self.lead())
                # Each runs alone: two live sessions in main and no lead make `addr lead` refuse.
                self.kill_ours([pid])
                self.assertTrue(self.gone(pid))

    def test_a_lane_session_never_takes_it(self):
        # Its session file's cwd is the lane, though the act runs from the main checkout.
        _, res = self.act(["new", "api-docs"], cwd=self.path, sid=self.SID)
        self.assertEqual(res["rc"], 0, res["err"])
        self.assertIsNone(self.lead())

    def test_the_walk_takes_the_nearest_session_and_only_an_interactive_one(self):
        for kind in ("sdk-cli", "bg"):
            with self.subTest(kind=kind):
                _, res = self.act(["new", f"x-{kind}"], kind=kind)
                self.assertEqual(res["rc"], 0, res["err"])
                self.assertIsNone(self.lead())
        _, res = self.act(["new", "y"], sock=False)  # no socket: no lane could reach it
        self.assertIsNone(self.lead())

    def test_an_agent_worktree_session_never_takes_it(self):
        agent = os.path.join(self.main, ".claude", "worktrees", "agent-a1")
        self.git("worktree", "add", "-q", "-b", "agent-a1", agent)
        _, res = self.act(["lead"], cwd=agent)
        self.assertEqual(res["rc"], 1)
        self.assertIn(f"in linked worktree {agent}: only a session in the main checkout leads",
                      res["err"])
        self.assertIsNone(self.lead())

    def test_only_the_nearest_session_can_take_it(self):
        # An interactive main-checkout session runs a `claude -p`, which runs the act: the
        # nearest is no lead, and the walk never passes it by for the one above.
        main = dict(sid=self.MAIN_SID)
        cli = dict(sid="sess-cli-0001", kind="sdk-cli", sock=False, entrypoint="sdk-cli")
        _, _, res = self.chain(["new", "api-docs"], main, **cli)
        self.assertEqual(res["rc"], 0, res["err"])
        self.assertIsNone(self.lead())
        _, _, res = self.chain(["lead"], main, **cli)
        self.assertEqual((res["rc"], res["out"]), (1, ""), res["err"])
        self.assertIn("session sess-cli-0001 is a sdk-cli session, not an interactive one",
                      res["err"])
        self.assertIsNone(self.lead())

    def test_a_session_a_lane_runs_never_takes_it(self):
        # A lane's claude runs an interactive claude launched in the main checkout: the nearest
        # passes every check of its own, but any session above being a lane's refuses, by
        # lead_only's rule, or a lane could make itself the lead.
        lead, _ = self.act(["new", "api-docs"])
        self.assertLead(lead)
        before = self.read(self.lead_path)
        lane = dict(cwd=self.path, sid=self.SID, pane="%5")
        top, _, res = self.chain(["lead"], lane, sid="sess-main-0002")
        self.assertEqual((res["rc"], res["out"]), (1, ""), res["err"])
        self.assertIn(f"this runs under session {self.SID} ({top} {self.comms[top]}), in linked "
                      f"worktree {self.path}: a lane's session never leads", res["err"])
        _, _, res = self.chain(["new", "docs-2"], lane, sid="sess-main-0003")
        self.assertEqual(res["rc"], 0, res["err"])
        self.assertEqual(self.read(self.lead_path), before)

    def test_the_leads_own_cd_never_vetoes_it(self):
        # A Bash cd moves the lead's process cwd, not its session file's: the nearest session
        # is judged by its launch dir, so a lead cd'd into a lane still takes the lead. Only the
        # sessions farther up are judged by their real cwd too (lane_above).
        pid, res = self.act(["lead"], real_cwd=self.path)
        self.assertEqual(res["rc"], 0, res["err"])
        self.assertLead(pid)
        other, res = self.act(["new", "api-docs"], real_cwd=self.path, sid="sess-main-0002")
        self.assertEqual(res["rc"], 0, res["err"])
        self.assertLead(other, sid="sess-main-0002")

    def test_a_session_farther_up_counts_by_its_real_cwd_too(self):
        # A session launched in main whose process now sits in a lane, running a claude that
        # runs `lane lead`: farther up, the real cwd counts (lane_above), so it refuses.
        before = self.read(self.lead_path) if os.path.exists(self.lead_path) else None
        top, _, res = self.chain(["lead"], dict(real_cwd=self.path, sid=self.SID),
                                 sid="sess-main-0002")
        self.assertEqual((res["rc"], res["out"]), (1, ""), res["err"])
        self.assertIn(f"this runs under session {self.SID} ({top} {self.comms[top]}), in linked "
                      f"worktree {self.path}: a lane's session never leads", res["err"])
        after = self.read(self.lead_path) if os.path.exists(self.lead_path) else None
        self.assertEqual(after, before)

    def test_a_record_step_that_fails_never_fails_the_act(self):
        # The act already succeeded and printed when its session is recorded: a failure there
        # leaves its exit code and output alone, and the lead where it was. A session file
        # nested past json's reach raises RecursionError (not ValueError) in session_files,
        # under lead_claim. Bare from this runner, so no session above could take it anyway.
        lead, _ = self.act(["new", "api-docs"])
        self.assertLead(lead)
        before = self.read(self.lead_path)
        self.write(os.path.join(self.home, ".claude", "sessions", "nested.json"), "[" * 100000)
        p = self.run_lane("new", "docs-2")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertTrue(p.stdout.startswith("lane docs-2: branch docs-2 from "), p.stdout)
        self.assertEqual(self.read(self.lead_path), before)

    @unittest.skipIf(os.geteuid() == 0, "root writes through a read-only dir")
    def test_a_state_dir_it_cannot_write_never_fails_the_act(self):
        lead, _ = self.act(["new", "api-docs"])
        before = self.read(self.lead_path)
        state = os.path.dirname(self.lead_path)
        os.chmod(state, 0o555)
        self.addCleanup(os.chmod, state, 0o755)
        _, res = self.act(["new", "docs-2"], sid="sess-main-0002")
        self.assertEqual(res["rc"], 0, res["err"])
        self.assertTrue(res["out"].startswith("lane docs-2: branch docs-2 from "), res["out"])
        self.assertEqual(self.read(self.lead_path), before)
        os.chmod(state, 0o755)  # the same session takes it once it can write
        pid, res = self.act(["lead"], sid="sess-main-0003")
        self.assertLead(pid, "sess-main-0003")

    def test_take_lead_never_raises(self):
        # In process: an error of any kind from the claim, and a cwd that is gone
        # (os.getcwd raises FileNotFoundError), leave the lead where it was.
        lead, _ = self.act(["new", "api-docs"])
        before = self.read(self.lead_path)
        cli = load_lane_script()
        gone = os.path.join(self.tmp, "gone")
        os.makedirs(gone)
        self.addCleanup(os.chdir, os.getcwd())
        with mock.patch.dict(os.environ, self.env, clear=True):
            os.chdir(self.main)
            with mock.patch.object(cli, "lead_claim", side_effect=RuntimeError("boom")) as claim:
                cli.take_lead()
            claim.assert_called_once()
            os.chdir(gone)
            os.rmdir(gone)
            cli.take_lead()
        self.assertEqual(self.read(self.lead_path), before)

    def test_lane_lead_takes_it_and_says_where(self):
        first, _ = self.act(["new", "api-docs"])
        self.assertLead(first)
        pid, res = self.act(["lead"], sid="sess-main-0002", pane="%9")
        self.assertEqual(res["rc"], 0, res["err"])
        self.assertEqual(res["out"], f"lead of {self.main}: session sess-main-0002 in proj:@3\n")
        self.assertLead(pid, "sess-main-0002", "%9")
        pid, res = self.act(["lead"], sid="sess-main-0003", pane=None,
                            run_in=self.lane_path("chart-fix"))  # any cwd in the repo
        self.assertEqual(res["out"], f"lead of {self.main}: session sess-main-0003 in no tmux\n")
        self.assertLead(pid, "sess-main-0003", None)

    def test_lane_lead_refuses_naming_why(self):
        cases = [
            ("a lane's session", dict(cwd=self.path, sid=self.SID),
             f"session {self.SID} launched in {self.path}, outside the main checkout"),
            ("a background session", dict(kind="bg"),
             f"session {self.MAIN_SID} is a background session"),
            ("a claude -p", dict(kind="sdk-cli"), "is a sdk-cli session, not an interactive one"),
            ("no socket", dict(sock=False), "has no messaging socket"),
        ]
        for why, kw, needle in cases:
            with self.subTest(why):
                _, res = self.act(["lead"], **kw)
                self.assertEqual((res["rc"], res["out"]), (1, ""), res["err"])
                self.assertIn(needle, res["err"])
        p = self.run_lane("lead")  # this test runner: no session file above it
        self.assertEqual(p.returncode, 1)
        self.assertIn("no Claude session runs this command", p.stderr)
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        p = self.run_lane("lead")
        self.assertEqual(p.returncode, 1)
        self.assertIn("sandboxed", p.stderr)
        self.assertIn("bare `lane lead`", p.stderr)
        self.env["_LANE_TEST_SANDBOXED"] = "0"
        plain = os.path.join(self.tmp, "plain")
        self.git("init", "-q", plain, cwd=self.tmp)
        p = self.run_lane("lead", cwd=plain)
        self.assertEqual(p.returncode, 1)
        self.assertIn("no lanes config", p.stderr)
        self.assertIsNone(self.lead())

    def test_an_unread_ancestor_session_file_refuses_a_lead_act(self):
        # This runner starts each fake, so its pid's file may be the session above: one that
        # won't read as a JSON object can't be told from a lane's. A dead pid's can't be one.
        sessions = os.path.join(self.home, ".claude", "sessions")
        for why, junk in {"junk": "{", "deep": "[" * 100000}.items():  # RecursionError in json
            for argv in (["lead"], ["done", "chart-fix", "--abandon"]):
                with self.subTest(why, argv=argv):
                    path = os.path.join(sessions, f"{os.getpid()}.json")
                    self.write(path, junk)
                    _, res = self.act(argv)
                    self.assertEqual((res["rc"], res["out"]), (1, ""), res["err"])
                    self.assertIn(f"session file {path} can't be read", res["err"])
                    gone = subprocess.Popen(["true"])
                    gone.wait()
                    os.rename(path, os.path.join(sessions, f"{gone.pid}.json"))
            pid, res = self.act(["lead"])
            self.assertEqual(res["rc"], 0, res["err"])
            self.assertLead(pid)
        self.assertTrue(os.path.isdir(self.path))  # no done got through


class SwitchedBranch(LanesRepo):
    """A lane's worktree can leave lane.json's branch (a `git switch` for a follow-up PR): `ls`,
    `whoami` and `done` go by the branch it has checked out."""

    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix")
        self.path = self.lane_path("chart-fix")
        self.commit("chart.txt", "axis\n", cwd=self.path)
        self.git("push", "-q", "origin", "chart-fix:main", cwd=self.path)  # merged
        self.git("switch", "-q", "-c", "chart-more", cwd=self.path)
        self.commit("more.txt", "labels\n", cwd=self.path)

    def test_ls_and_whoami_show_the_checked_out_branch(self):
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertEqual((row["branch"], row["registered_branch"]), ("chart-more", "chart-fix"))
        self.assertEqual((row["ahead"], row["behind"]), (1, 0))
        self.assertIn("chart-more", self.lane("ls"))
        self.assertEqual(json.loads(self.lane("whoami", "--json", cwd=self.path))["branch"],
                         "chart-more")
        self.assertIn("branch chart-more", self.lane("whoami", cwd=self.path))

    def test_done_refuses_while_the_checked_out_branch_is_unmerged(self):
        p = self.run_lane("done", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn("branch chart-more is not merged", p.stderr)
        self.assertTrue(os.path.isdir(self.path))

    def test_done_refuses_while_the_registered_branch_is_unmerged(self):
        # The other way round: the lane switched away from work it never merged.
        self.git("switch", "-q", "chart-fix", cwd=self.path)
        self.commit("late.txt", "never pushed\n", cwd=self.path)
        self.git("switch", "-q", "chart-more", cwd=self.path)
        self.git("push", "-q", "origin", "chart-more:main", cwd=self.path)
        p = self.run_lane("done", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn("branch chart-fix is not merged", p.stderr)
        self.assertTrue(os.path.isdir(self.path))

    def test_done_closes_once_both_are_merged_and_deletes_both(self):
        self.git("push", "-q", "origin", "chart-more:main", cwd=self.path)
        self.assertIn("closed", self.lane("done", "chart-fix"))
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.git("branch", "--list", "chart-fix", "chart-more"), "")

    def test_a_detached_worktree_needs_abandon(self):
        self.git("switch", "-q", "--detach", cwd=self.path)
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertTrue(row["branch"].startswith("(detached "), row["branch"])
        p = self.run_lane("done", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn("detached HEAD", p.stderr)
        self.lane("done", "chart-fix", "--abandon")
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual(self.git("branch", "--list", "chart-fix"), "")  # merged: -d took it
        self.assertIn("chart-more", self.git("branch", "--list", "chart-more"))  # never judged

    def test_done_never_deletes_the_base_branch(self):
        self.git("switch", "-q", "-c", "lead")  # the lead's checkout leaves main free
        self.git("switch", "-q", "main", cwd=self.path)
        self.lane("done", "chart-fix")
        self.assertIn("main", self.git("branch", "--list", "main"))

    def test_the_base_branch_is_kept_on_a_remote_whose_name_holds_a_slash(self):
        self.git("remote", "add", "my/fork", self.origin)
        self.git("fetch", "-q", "my/fork")
        (cfg,) = self.config_files()
        text = self.read(cfg)
        self.assertIn('base = "origin/main"\n', text)
        self.write(cfg, text.replace('base = "origin/main"', 'base = "my/fork/main"'))
        self.git("switch", "-q", "-c", "lead")
        self.git("switch", "-q", "main", cwd=self.path)
        self.lane("done", "chart-fix")
        self.assertIn("main", self.git("branch", "--list", "main"))

    def test_a_switch_to_a_fresh_branch_closes_once_the_first_is_merged(self):
        self.git("switch", "-q", "-c", "chart-next", "chart-fix", cwd=self.path)
        self.lane("done", "chart-fix")
        self.assertEqual(self.git("branch", "--list", "chart-fix", "chart-next"), "")

    def test_a_branch_checked_out_elsewhere_keeps_its_upstream(self):
        # The lane switched away from chart-fix; the lead checks chart-fix out to test it.
        self.git("push", "-q", "origin", "chart-more:main", cwd=self.path)
        self.git("push", "-q", "origin", "chart-fix", cwd=self.path)
        self.git("branch", "--set-upstream-to=origin/chart-fix", "chart-fix")
        self.git("switch", "-q", "chart-fix")
        p = self.run_lane("done", "chart-fix")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("branch chart-fix kept", p.stderr)
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "chart-fix@{upstream}").strip(),
                         "origin/chart-fix")
        self.assertEqual(self.git("branch", "--list", "chart-more"), "")

    def test_registered_branch_deleted_after_the_switch_judges_the_checked_out_one(self):
        self.git("branch", "-D", "chart-fix")
        self.assertIn("branch chart-more is not merged", self.run_lane("done", "chart-fix").stderr)
        self.git("push", "-q", "origin", "chart-more:main", cwd=self.path)
        self.lane("done", "chart-fix")
        self.assertEqual(self.git("branch", "--list", "chart-more"), "")

    def test_abandon_keeps_an_unmerged_switched_branch_and_its_config(self):
        # Its upstream names a remote ref a fetch has pruned, a key holds two values, and
        # setting an upstream would add a rebase key: the section survives exactly as it was.
        self.git("config", "branch.autoSetupRebase", "always")
        self.git("config", "branch.chart-more.remote", "origin")
        self.git("config", "--add", "branch.chart-more.merge", "refs/heads/chart-more")
        self.git("config", "--add", "branch.chart-more.merge", "refs/heads/other")
        before = self.git("config", "--get-regexp", r"^branch\.chart-more\.")
        self.lane("done", "chart-fix", "--abandon")
        self.assertIn("chart-more", self.git("branch", "--list", "chart-more"))
        self.assertEqual(self.git("config", "--get-regexp", r"^branch\.chart-more\."), before)

    def test_a_branch_without_config_is_left_without_any(self):
        self.lane("done", "chart-fix", "--abandon")
        p = subprocess.run(["git", "config", "--get-regexp", r"^branch\.chart-more\."],
                           cwd=self.main, env=self.env, capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout), (1, ""))

    def test_a_lane_mid_rebase_shows_the_rebased_branch_s_pr(self):
        # Git keeps the branch a rebase works on in the worktree's admin dir; HEAD is detached.
        self.git("switch", "-q", "--detach", cwd=self.path)
        admin = self.git("rev-parse", "--absolute-git-dir", cwd=self.path).strip()
        self.write(os.path.join(admin, "rebase-merge", "head-name"), "refs/heads/chart-more\n")
        self.env["FAKE_GH_OUT"] = json.dumps(
            [{"number": 7, "state": "MERGED", "headRefName": "chart-fix"},
             {"number": 8, "state": "OPEN", "headRefName": "chart-more"}])
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertEqual(row["pr"], "#8 open")
        self.write(os.path.join(admin, "rebase-merge", "head-name"), "refs/heads/-bad name\n")
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertEqual(row["pr"], "#7 merged")  # no valid name: lane.json's guess

    def test_a_detached_lane_shows_its_registered_branch_s_pr(self):
        self.git("switch", "-q", "--detach", cwd=self.path)  # mid-rebase looks the same
        self.env["FAKE_GH_OUT"] = json.dumps(
            [{"number": 7, "state": "OPEN", "headRefName": "chart-fix"}])
        (row,) = json.loads(self.lane("ls", "--json"))
        self.assertEqual(row["pr"], "#7 open")
        self.assertTrue(row["branch"].startswith("(detached "))

    def test_a_switch_during_the_close_refuses_it(self):
        # What `done` judged is what it removes: a switch after the judging stops the close.
        self.git("push", "-q", "origin", "chart-more:main", cwd=self.path)
        lane_mod = load_lane_script()
        real_fetch = lane_mod.fetch

        def fetch_then_switch(repo):
            fetched = real_fetch(repo)
            subprocess.run(["git", "switch", "-q", "-c", "chart-late"], cwd=self.path,
                           env=self.env, check=True)
            return fetched

        cwd = os.getcwd()
        os.chdir(self.main)
        try:
            with mock.patch.dict(os.environ, self.env, clear=True), \
                    mock.patch.object(lane_mod, "fetch", fetch_then_switch), \
                    self.assertRaisesRegex(lane_mod.LaneError, "chart-late"):
                lane_mod.cmd_done(argparse.Namespace(id="chart-fix", abandon=False))
        finally:
            os.chdir(cwd)
        self.assertTrue(os.path.isdir(self.path))
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")


class ExcludedGuardRules(LanesRepo):
    """`new` names the Edit deny rule a lane's worktree needs before the excluded-command guard
    passes its excluded calls; `done` names the ones its removed worktree leaves behind."""

    def asks(self, lane_id):
        text = self.read(os.path.join(self.lane_json(lane_id)["path"], ".lane", "STATUS.md"))
        return text[text.index("## Asks for Hayden"):text.index("## Not mine")]

    def test_new_names_the_rule_a_setup_made_hooks_dir_needs_and_seeds_the_ask(self):
        # A repo whose setup sets a relative core.hooksPath gives each worktree its own hooks
        # dir, which only a rule naming that lane's path protects.
        self.lane("init", "--setup", "git config core.hooksPath .githooks")
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 0, p.stderr)
        rule = f"Edit(/{self.lane_path('chart-fix')}/.githooks/**)"
        self.assertIn(rule, p.stderr)
        self.assertIn("settings.machine.json", p.stderr)
        self.assertIn(rule, self.asks("chart-fix"))
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def test_a_clean_worktree_says_nothing(self):
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("excluded-guard", p.stderr)
        self.assertNotIn("Edit(", self.asks("chart-fix"))

    def test_finishing_a_failed_setup_seeds_the_ask_too(self):
        # `open` refuses a setup-failed lane, so its record is still the one `new` wrote.
        self.lane("init", "--setup", "git config core.hooksPath .githooks && test -f ready.flag")
        self.assertEqual(self.run_lane("new", "chart-fix").returncode, 1)
        path = self.lane_path("chart-fix")
        self.write(os.path.join(path, "ready.flag"), "")
        p = self.run_lane("adopt", path)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(f"Edit(/{path}/.githooks/**)", p.stderr)
        self.assertIn(f"Edit(/{path}/.githooks/**)", self.asks("chart-fix"))

    def test_adopting_another_worktree_warns_but_leaves_its_record_to_the_lane(self):
        path = os.path.join(self.tmp, "elsewhere", "docs-lane")
        self.git("worktree", "add", "-q", "-b", "docs", path, "origin/main")
        self.git("config", "core.hooksPath", ".githooks")
        p = self.run_lane("adopt", path)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(f"Edit(/{path}/.githooks/**)", p.stderr)
        self.assertNotIn("Edit(", self.asks("docs-lane"))

    def test_seed_line_writes_only_a_record_as_new_seeded_it(self):
        lane_mod = load_lane_script()
        self.lane("new", "chart-fix")
        lane, record = self.lane_json("chart-fix"), self.record("chart-fix")
        seeded = self.read(record)
        outside = os.path.join(self.tmp, "elsewhere", "STATUS.md")
        self.write(outside, "## Asks for Hayden\n")

        def seed():
            with mock.patch.dict(os.environ, self.env, clear=True):
                return lane_mod.seed_line(lane, "## Asks for Hayden", "- ask \udcff")

        self.assertTrue(seed())  # control: the seeded record takes it, bytes kept as they were
        with open(record, "rb") as f:
            self.assertIn(b"- ask \xff\n", f.read())
        cases = {
            "past the read limit": lambda: self.write(record, seeded + "x" * lane_mod.RECORD_READ),
            "a link to another file": lambda: (os.remove(record), os.symlink(outside, record)),
            "a FIFO": lambda: (os.remove(record), os.mkfifo(record)),
            "a .lane that links elsewhere": lambda: (
                shutil.rmtree(os.path.dirname(record)),
                os.symlink(os.path.dirname(outside), os.path.dirname(record))),
        }
        for name, make in cases.items():
            with self.subTest(case=name):
                if os.path.islink(os.path.dirname(record)):
                    os.remove(os.path.dirname(record))
                os.makedirs(os.path.dirname(record), exist_ok=True)
                if os.path.lexists(record):
                    os.remove(record)
                self.write(record, seeded)
                make()
                before = os.lstat(record)
                self.assertFalse(seed())
                self.assertEqual(os.lstat(record).st_mtime_ns, before.st_mtime_ns)
                self.assertEqual(self.read(outside), "## Asks for Hayden\n")

    def test_finish_seeds_while_the_lane_is_still_setup_failed(self):
        # `open` refuses a setup-failed lane, so no session can start while the ask goes in.
        lane_mod = load_lane_script()
        self.lane("init", "--setup", "test -f ready.flag")
        self.assertEqual(self.run_lane("new", "chart-fix").returncode, 1)
        path = self.lane_path("chart-fix")
        self.write(os.path.join(path, "ready.flag"), "")
        states = []
        cwd = os.getcwd()
        os.chdir(self.main)
        try:
            with mock.patch.dict(os.environ, self.env, clear=True), \
                    mock.patch.object(lane_mod, "check_worktree", lambda lane, seed_ask: (
                        states.append((self.lane_json("chart-fix")["state"], seed_ask)))):
                lane_mod.cmd_adopt(argparse.Namespace(path=path, id=None))
        finally:
            os.chdir(cwd)
        self.assertEqual(states, [("setup-failed", True)])
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def test_seed_line_writes_nothing_when_it_cannot_see_sessions(self):
        lane_mod = load_lane_script()
        self.lane("new", "chart-fix")
        seeded = self.read(self.record("chart-fix"))
        with mock.patch.dict(os.environ, dict(self.env, _LANE_TEST_SANDBOXED="1"), clear=True):
            self.assertFalse(lane_mod.seed_line(self.lane_json("chart-fix"),
                                                "## Asks for Hayden", "- ask"))
        self.assertEqual(self.read(self.record("chart-fix")), seeded)

    def test_seed_line_leaves_a_live_session_s_record_alone(self):
        lane_mod = load_lane_script()
        self.lane("new", "chart-fix")
        self.write(os.path.join(self.home, ".claude", "sessions", f"{os.getpid()}.json"),
                   json.dumps({"pid": os.getpid(), "sessionId": "s",
                               "cwd": self.lane_path("chart-fix"),
                               "procStart": str(lanelib.proc_start(os.getpid()))}))
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertFalse(lane_mod.seed_line(self.lane_json("chart-fix"),
                                                "## Asks for Hayden", "- ask"))
        self.assertNotIn("- ask", self.read(self.record("chart-fix")))

    def test_done_names_the_deny_rules_its_worktree_leaves_behind(self):
        self.lane("new", "chart-fix")
        self.lane("new", "chart-fix2")
        path, other = self.lane_path("chart-fix"), self.lane_path("chart-fix2")
        hooks, extra = f"Edit(/{path}/.githooks/**)", f"Edit(/{path}/tools/*.sh)"
        kept = [f"Edit(/{other}/.githooks/**)", f"Edit(/{self.root}/**)", "Edit(~/x/**)"]
        claude = os.path.join(self.home, ".claude")
        self.write(os.path.join(claude, "settings.machine.json"),
                   json.dumps({"permissions": {"deny": [hooks, *kept]}}))
        self.write(os.path.join(claude, "settings.json"),
                   json.dumps({"permissions": {"deny": [hooks, extra, *kept]}}))
        self.commit("chart.txt", "axis\n", cwd=path)
        refused = self.run_lane("done", "chart-fix")
        self.assertEqual(refused.returncode, 1)
        self.assertNotIn(hooks, refused.stdout + refused.stderr)  # only after a close
        self.git("push", "-q", "origin", "chart-fix:main", cwd=path)
        out = self.lane("done", "chart-fix")
        lines = out[out.index("closed"):].splitlines()
        self.assertIn(f"  {hooks}  in {os.path.join(claude, 'settings.machine.json')}", lines)
        self.assertIn(f"  {extra}  in {os.path.join(claude, 'settings.json')}", lines)
        self.assertEqual(out.count(hooks), 1, out)  # the overlay's copy in settings.json is setup's
        for rule in kept:
            self.assertNotIn(rule, out)

    def test_done_says_nothing_when_no_rule_names_the_lane(self):
        self.lane("new", "chart-fix")
        path = self.lane_path("chart-fix")
        self.commit("chart.txt", "axis\n", cwd=path)
        self.git("push", "-q", "origin", "chart-fix:main", cwd=path)
        self.assertNotIn("permissions.deny", self.lane("done", "chart-fix"))


class Shown(unittest.TestCase):
    def test_a_process_is_shown_by_its_program_never_its_arguments(self):
        # Any argument can hold a secret; comm and argv[0] are masked for the terminal (C0,
        # DEL and C1, whose 0x9b is a CSI on some terminals).
        lane_mod = load_lane_script()
        esc, csi = chr(0x1b), chr(0x9b)
        p = lanelib.Proc(4242, 1, 99, "S", f"cu{esc}rl{csi}", "/x",
                         (f"/usr/bin/cu{csi}rl", "-u", "user:hunter2", "https://example.com"))
        self.assertEqual(lane_mod.described(p, "why"), "4242 cu?rl? (why): cu?rl")
        self.assertEqual(lane_mod.described(p._replace(argv=()), "why"), "4242 cu?rl? (why)")
        # A setproctitle title carries its arguments in argv[0]: cut at the first whitespace,
        # before the basename, since an argument can hold a '/'.
        for title, prog in (("/usr/bin/celery worker --password=hunter2/x", "celery"),
                            ("sshd: hayden@pts/0", "sshd:"), (" ", "")):
            with self.subTest(title=title):
                self.assertEqual(lane_mod.described(p._replace(argv=(title, "-v")), "why"),
                                 "4242 cu?rl? (why)" + (f": {prog}" if prog else ""))


class Plain(LanesRepo):
    init_lanes = False

    def test_a_repo_without_lanes_is_plain(self):
        self.assertTrue(self.lane("whoami").startswith("plain "))
        self.assertIn("lane init", self.run_lane("ls").stderr)

    def test_an_old_common_dir_config_does_not_make_a_lanes_repo(self):
        self.write(os.path.join(self.common, "lanes", "config.toml"),
                   f'root = "{self.root}"\nsetup = "touch PLANTED"\n')
        self.assertTrue(self.lane("whoami").startswith("plain "))
        p = self.run_lane("new", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn("old layout's config", p.stderr)
        self.assertFalse(os.path.exists(self.lane_path("chart-fix")))


if __name__ == "__main__":
    unittest.main()
