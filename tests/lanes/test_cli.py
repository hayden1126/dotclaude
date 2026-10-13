"""skills/lanes/scripts/lane: the CLI round trip, staleness, the claim lock, identity, and what
`done` ends."""
import errno
import importlib.machinery
import importlib.util
import json
import multiprocessing
import os
import shutil
import signal
import subprocess
import sys
import time
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
        self.assertEqual(rows["chart-fix"]["flags"], ["orphan"])  # no live session
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
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("reference into chart-fix/work", p.stderr)


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
  on_term   [argv, stdin]: run on SIGTERM before it exits (a SessionEnd hook)
  children  configs of fakes it starts, each with its own cwd and env
  then      {argv, cwd, go, out}: once go exists, run argv in cwd and write {rc, err} to out
It prints "ready <pid> <its descendants' pids>" once set up, then sleeps."""
import json, os, signal, subprocess, sys, time

cfg = json.loads(sys.argv[1])


def on(sig, _frame):
    name = signal.Signals(sig).name
    with open(cfg["log"], "a") as f:
        f.write(f"{os.getpid()} {name}\n")
    if name in cfg.get("ignore", []):
        return
    if sig == signal.SIGTERM and cfg.get("on_term"):
        argv, stdin = cfg["on_term"]
        subprocess.run(argv, input=stdin, text=True, capture_output=True, timeout=30)
    os._exit(0)


for sig in (signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, on)
held = open(cfg["hold"], "a") if cfg.get("hold") else None
pids = []
for child in cfg.get("children", []):
    p = subprocess.Popen([sys.executable, __file__, json.dumps(child)], cwd=child["cwd"],
                         env=child["env"], stdout=subprocess.PIPE, text=True)
    pids += p.stdout.readline().split()[1:]
print("ready", os.getpid(), *pids, flush=True)
if then := cfg.get("then"):
    while not os.path.exists(then["go"]):
        time.sleep(0.05)
    p = subprocess.run(then["argv"], cwd=then["cwd"], capture_output=True, text=True,
                       timeout=60)
    with open(then["out"] + ".tmp", "w") as f:
        json.dump({"rc": p.returncode, "err": p.stderr}, f)
    os.rename(then["out"] + ".tmp", then["out"])
while True:
    time.sleep(60)
'''


class Close(LanesRepo):
    """`lane done` ends what provably belongs to the lane and refuses, by name and before any
    signal, what doesn't: the kill-scope matrix. Every process here is a disposable fake this
    test starts (FAKE), proven the lane's or not by session files and transcripts under the temp
    HOME; cleanup kills each one still running as the process the test started."""

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
               "startedAt": int(time.time() * 1000), **extra}
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

    def assertClosed(self):
        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(os.path.exists(os.path.join(self.common, "lanes", "chart-fix")))

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

    def test_a_pane_shell_ends_by_sighup_after_its_session(self):
        self.hand_off()
        shell, claude = self.start(self.fake(self.path, ignore=["SIGTERM"],
                                             children=[self.fake(self.path)]))
        self.session_file(claude)
        out = self.lane("done", "chart-fix", "--abandon")
        self.assertIn(f"ended {shell} {self.comms[shell]} (the shell of lane session "
                      f"{self.SID})", out)
        # An interactive shell ignores SIGTERM: it gets only SIGHUP, once its session is gone.
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (shell, "SIGHUP")])
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
        self.hand_off()
        self.transcript("sess-lane-0003", self.path)
        held = os.path.join(self.common, "held.lock")
        (left,) = self.start(self.fake(self.path, "sess-lane-0003", ignore=["SIGTERM"],
                                       hold=held))
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"{left} {self.comms[left]} (carries lane session sess-lane-0003; holds "
                      f"{held} open, so it was not killed", p.stderr)
        self.assertTrue(self.alive(left))
        self.assertEqual(self.signals(), [(left, "SIGTERM"), (left, "SIGTERM")])
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

    def test_done_refuses_to_run_from_inside_the_lane(self):
        self.hand_off()
        go, out = os.path.join(self.tmp, "go"), os.path.join(self.tmp, "done.json")
        # The lane's own session runs `lane done` (from the main checkout's cwd).
        (claude,) = self.claude(then={"argv": [sys.executable, LANE, "done", "chart-fix",
                                               "--abandon"],
                                      "cwd": self.main, "go": go, "out": out})
        self.write(go, "")
        deadline = time.monotonic() + 60
        while not os.path.exists(out) and time.monotonic() < deadline:
            time.sleep(0.05)
        res = json.loads(self.read(out))
        self.assertEqual(res["rc"], 1, res["err"])
        self.assertIn("this `lane done` runs inside lane chart-fix", res["err"])
        self.assertIn("run it from the main checkout", res["err"])
        self.assertTrue(self.alive(claude))
        self.assertEqual(self.signals(), [])
        # Run with its own cwd in the lane.
        p = self.run_lane("done", "chart-fix", "--abandon", cwd=self.path)
        self.assertIn("run it from the main checkout", p.stderr)
        self.assertRefusedUntouched(p, claude)

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
        self.assertIn(f"The lead's ./setup.sh in {self.main} relinks them", p.stderr)
        self.assertRefusedUntouched(p, claude)
        # The board names the holder; once main relinks it, the hold is gone and done goes on.
        self.assertIn("install: held by lane chart-fix (branch chart-fix, 1 link)",
                      self.lane("ls"))
        os.remove(link)
        self.assertNotIn("install:", self.lane("ls"))
        self.lane("done", "chart-fix", "--abandon")
        self.assertClosed()

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

    def test_a_sessionend_stamp_made_during_the_close_reaches_the_archive(self):
        # The lanes lock is free while `done` signals, so the session's SessionEnd hook (the
        # real one) stamps endedAt, and the archive is built from the record re-read after it.
        # The full grace: round 2 would end a hook still running past a short one.
        self.env["_LANE_TEST_GRACE"] = "5"
        self.hook("lane-identity.sh", {"session_id": self.SID, "cwd": self.path,
                                       "source": "startup", "hook_event_name": "SessionStart"})
        self.hand_off()
        end = json.dumps({"session_id": self.SID, "cwd": self.path, "reason": "other",
                          "hook_event_name": "SessionEnd"})
        self.claude(on_term=[["bash", os.path.join(HOOKS, "lane-identity.sh")], end])
        self.lane("done", "chart-fix", "--abandon")
        closed = os.path.join(self.common, "lanes", "_closed")
        (archive,) = os.listdir(closed)
        with open(os.path.join(closed, archive, "lane.json")) as f:
            rec = json.load(f)
        (session,) = rec["sessions"]
        self.assertEqual((session["session_id"], session["reason"]), (self.SID, "other"))
        self.assertTrue(session.get("endedAt"))
        self.assertEqual(rec["state"], "abandoned")

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
