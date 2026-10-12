"""skills/lanes/scripts/lane: the CLI round trip, staleness, the claim lock and identity."""
import importlib.machinery
import importlib.util
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from _fixture import LANE, LanesRepo

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
