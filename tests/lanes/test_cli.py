"""skills/lanes/scripts/lane: the CLI round trip, staleness, the claim lock and identity."""
import json
import multiprocessing
import os
import subprocess
import sys
import unittest

from _fixture import LANE, LanesRepo


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
        self.env["LANE_SANDBOXED"] = "1"
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

    def test_an_adopted_lane_merged_by_fast_forward_closes_as_merged(self):
        # Its merge-base is its tip, so "commits past the base" is zero, yet it is merged.
        path = os.path.join(self.tmp, "elsewhere", "docs-lane")
        self.git("worktree", "add", "-q", "-b", "docs", path, "origin/main")
        self.commit("docs.txt", "docs\n", cwd=path)
        self.git("push", "-q", "origin", "docs:main", cwd=path)
        self.git("fetch", "-q", "origin")
        self.lane("adopt", path)
        self.assertTrue(self.lane_json("docs-lane")["adopted"])
        out = self.lane("done", "docs-lane")
        self.assertIn("fully in origin/main", out)

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

    def test_done_and_asks_read_a_mirror_left_mid_swap(self):
        # A killed hook left only mirror.old, then the worktree was removed raw: mirror.old is
        # the only copy, so every reader must find it, and done must archive it.
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
        self.assertIn("chart-fix: - pick the chip row", self.lane("asks"))
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


class Plain(LanesRepo):
    init_lanes = False

    def test_a_repo_without_lanes_is_plain(self):
        self.assertTrue(self.lane("whoami").startswith("plain "))
        self.assertIn("lane init", self.run_lane("ls").stderr)


if __name__ == "__main__":
    unittest.main()
