"""skills/lanes/scripts/lane park: a finished lane's sessions end and its cap slot frees, its
worktree, branch, record and claims kept; `lane open` unparks it, at most one lane over the cap."""
import argparse
import datetime
import fcntl
import glob
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from unittest import mock

import test_cli  # by module: a class imported by name would have its tests collected here too
from _fixture import LANE

import lanelib  # on sys.path through _fixture


class ParkBase(test_cli.Fakes):
    """Fakes' lane chart-fix, with gh answering `[]` (no PR) so the board's handoff? can clear."""

    def setUp(self):
        super().setUp()
        self.env["FAKE_GH_OUT"] = "[]"

    def ready(self, push=True):
        """A lane park passes: a commit (pushed to origin by default), then the record's handoff
        written after it."""
        self.commit("chart.txt", "axis\n", cwd=self.path)
        if push:
            self.git("push", "-q", "origin", "chart-fix", cwd=self.path)
        self.hand_off()

    def flag_glob(self, lane_id="chart-fix"):
        """The glob of a lane's parked flag (Repo.parked_path) in the temp state dir."""
        return os.path.join(self.tmp, "state", "dotclaude", "lanes", "*.parked", f"{lane_id}.json")

    def proof(self):
        return os.path.join(self.tmp, "state", "dotclaude", "lanes", "*.closing", "chart-fix.json")

    def flag(self, lane_id="chart-fix", **over):
        """Write a lane's parked flag as `lane park` does; over replaces its fields."""
        rec = self.lane_json(lane_id)
        cfg = os.path.splitext(self.config_files()[0])[0]
        self.write(os.path.join(cfg + ".parked", f"{lane_id}.json"), json.dumps(dict(
            {"lane": lane_id, "created": rec.get("created"), "path": rec["path"],
             "parked": "2026-10-29T10:00:00+00:00"}, **over)))

    def row(self, lane_id="chart-fix"):
        return {r["id"]: r for r in json.loads(self.lane("ls", "--json"))}[lane_id]

    def assertParked(self, out):
        self.assertIn("lane chart-fix parked: worktree, branch, record and claims kept; "
                      "`lane open chart-fix` unparks it", out)
        (flag,) = glob.glob(self.flag_glob())
        rec = json.loads(self.read(flag))
        self.assertEqual((rec["lane"], rec["created"], rec["path"]),
                         ("chart-fix", self.lane_json("chart-fix")["created"], self.path))
        self.assertIsNotNone(lanelib.parse_iso(rec["parked"]))
        self.assertEqual(glob.glob(self.proof()), [])  # a completed park deletes its proof
        self.assertTrue(os.path.isdir(self.path))
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")

    def assertRefusedUntouched(self, p, *pids):
        """A refusal before any signal: exit 1, each pid running, nothing signalled, no flag and
        no proof written, the lane as it was."""
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        for pid in pids:
            self.assertTrue(self.alive(pid), pid)
        self.assertEqual(self.signals(), [])
        self.assertNotIn("ended", p.stdout)
        self.assertEqual(glob.glob(self.flag_glob()), [])
        self.assertEqual(glob.glob(self.proof()), [])
        self.assertTrue(os.path.isdir(self.path))


class Park(ParkBase):
    def test_park_ends_the_session_and_keeps_everything_else(self):
        self.ready()
        self.lane("claim", "42", cwd=self.path)
        self.write(self.record("chart-fix"), self.read(self.record("chart-fix")).replace(
            "## Next\n", "## Next\n- #42 is done.\n"))
        (claude,) = self.claude()
        out = self.lane("park", "chart-fix")
        self.assertIn(f"ended {claude} {self.comms[claude]} (lane session {self.SID})", out)
        self.assertEqual(self.signals(), [(claude, "SIGTERM")])
        self.assertParked(out)
        self.assertEqual(self.lane_json("chart-fix")["claims"], ["#42"])
        self.assertIn("chart-fix", self.git("branch", "--list", "chart-fix"))
        # The board: parked, never orphan, and the slot it gave up.
        row = self.row()
        self.assertIn("parked", row["flags"])
        self.assertNotIn("orphan", row["flags"])
        self.assertIsNotNone(lanelib.parse_iso(row["parked"]))
        self.assertIn("cap: 0 of 8 slots held (1 parked)", self.lane("ls"))
        # Parked with no session: nothing to do.
        p = self.run_lane("park", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn("lane chart-fix is already parked", p.stderr)

    def test_park_ends_a_pane_shell_by_sighup(self):
        self.ready()
        pids = self.start(self.fake(self.tmp, comm="tmux: server", children=[
            self.fake(self.path, ignore=["SIGTERM"], children=[self.fake(self.path)])]))
        server, shell, claude = pids
        self.session_file(claude)
        out = self.lane("park", "chart-fix")
        self.assertEqual(self.signals(), [(claude, "SIGTERM"), (shell, "SIGHUP")])
        self.assertTrue(self.alive(server))
        self.assertParked(out)

    def test_a_lane_with_nothing_running_parks(self):
        self.ready()
        self.assertParked(self.lane("park", "chart-fix"))

    def test_an_open_pr_at_head_counts_as_pushed(self):
        self.ready(push=False)
        head = self.git("rev-parse", "HEAD", cwd=self.path).strip()
        self.env["FAKE_GH_OUT"] = json.dumps([{"number": 9, "state": "OPEN",
                                               "headRefName": "chart-fix", "headRefOid": head}])
        self.assertParked(self.lane("park", "chart-fix"))

    def test_a_park_refused_after_its_signals_keeps_the_proof_and_a_rerun_parks(self):
        # A process that starts in the lane mid-park (an `open`, a job the session leaves) shows
        # up in the final look: the park refuses, and the lane stays unparked.
        self.ready()
        stray = os.path.join(self.tmp, "stray.pid")
        (claude,) = self.claude(on_term=[["sh", "-c", f"cd {shlex.quote(self.path)} && "
                                                      f"(sleep 30 >/dev/null 2>&1 & echo $! > {stray})"], ""])
        p = self.run_lane("park", "chart-fix")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn(f"ended {claude}", p.stdout, p.stderr)
        self.assertIn("rerun `lane park chart-fix`", p.stderr)
        self.assertNotIn("lane done", p.stderr)
        self.assertEqual(glob.glob(self.flag_glob()), [])
        self.assertEqual(len(glob.glob(self.proof())), 1)
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")  # never closing
        pid = int(self.read(stray))
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while ((st := lanelib.proc_stat(pid)) and st[1] not in lanelib.EXITED
               and time.monotonic() < deadline):
            time.sleep(0.05)
        self.assertParked(self.lane("park", "chart-fix"))

    def test_done_removes_the_parked_flag(self):
        self.flag()
        self.lane("done", "chart-fix", "--abandon")
        self.assertEqual(glob.glob(self.flag_glob()), [])


class ParkRefusals(ParkBase):
    """Each refusal comes before any signal: nothing is signalled and no flag is written."""

    def test_a_dirty_tree(self):
        self.ready()
        (claude,) = self.claude()
        self.write(os.path.join(self.path, "notes.txt"), "draft\n")
        p = self.run_lane("park", "chart-fix")
        self.assertIn("uncommitted or untracked files (notes.txt)", p.stderr)
        self.assertIn("rerun `lane park chart-fix`", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_no_remote_branch(self):
        self.ready(push=False)
        (claude,) = self.claude()
        p = self.run_lane("park", "chart-fix")
        self.assertIn("is not on origin/chart-fix", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_a_remote_branch_behind_head(self):
        self.ready()
        self.commit("more.txt", "x\n", cwd=self.path)
        self.hand_off()
        (claude,) = self.claude()
        p = self.run_lane("park", "chart-fix")
        self.assertIn("is not on origin/chart-fix", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_an_open_pr_behind_head(self):
        self.ready(push=False)
        old = self.git("rev-parse", "HEAD", cwd=self.path).strip()
        self.commit("more.txt", "x\n", cwd=self.path)
        self.hand_off()
        self.env["FAKE_GH_OUT"] = json.dumps([{"number": 9, "state": "OPEN",
                                               "headRefName": "chart-fix", "headRefOid": old}])
        (claude,) = self.claude()
        p = self.run_lane("park", "chart-fix")
        self.assertIn(f"open PR #9 is at {old[:12]}, behind its HEAD", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_a_failing_handoff_check(self):
        self.commit("chart.txt", "axis\n", cwd=self.path)
        self.git("push", "-q", "origin", "chart-fix", cwd=self.path)
        (claude,) = self.claude()  # the seeded record's Next is still empty
        p = self.run_lane("park", "chart-fix")
        self.assertIn("lane chart-fix's handoff is incomplete, so nothing was signalled", p.stderr)
        self.assertIn("## Next", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_a_keep_open_lane_parks(self):
        # Plain handoff-check, not --closing: a lane with more PRs to come may still park.
        self.ready()
        self.write(self.record("chart-fix"), self.read(self.record("chart-fix")).replace(
            "## Next\n", "## Next\nKeep open: PR 2 follows.\n"))
        self.assertParked(self.lane("park", "chart-fix"))

    def test_handoff_lit(self):
        self.ready()
        (claude,) = self.claude()
        # A merge after the record's last write: the lane never saw it.
        later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
        self.env["FAKE_GH_OUT"] = json.dumps([{"number": 7, "state": "MERGED",
                                               "headRefName": "chart-fix",
                                               "mergedAt": later.isoformat(timespec="seconds")}])
        p = self.run_lane("park", "chart-fix")
        self.assertIn("handoff?", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_gh_unavailable(self):
        self.ready()
        (claude,) = self.claude()
        del self.env["FAKE_GH_OUT"]
        p = self.run_lane("park", "chart-fix")
        self.assertIn("gh", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def hold(self, name, who="chart-fix"):
        """Hold lock name as `lane lock` does, its holder line naming who."""
        path = os.path.join(self.common, "lanes", lanelib.LOCKS, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.pwrite(fd, f"{who} since 2026-10-29T10:00:00+00:00: make test\n".encode(), 0)

    def test_a_lock_held_by_the_lane(self):
        self.lane("init", "--locks", "gate")
        self.ready()
        (claude,) = self.claude()
        for name in ("suite", "gate"):
            with self.subTest(name):
                self.hold(name)
                p = self.run_lane("park", "chart-fix")
                self.assertIn(f"holds the {name} lock", p.stderr)
                self.assertRefusedUntouched(p, claude)

    def test_a_lock_held_by_another_lane_is_no_bar(self):
        self.ready()
        self.hold("suite", who="other")
        self.assertParked(self.lane("park", "chart-fix"))

    def test_the_install_hold(self):
        self.ready()
        (claude,) = self.claude()
        hooks = os.path.join(self.home, ".claude", "hooks")
        os.makedirs(hooks)
        os.symlink(os.path.join(self.path, "hooks", "lane-identity.sh"),
                   os.path.join(hooks, "lane-identity.sh"))
        p = self.run_lane("park", "chart-fix")
        self.assertIn("lane chart-fix holds the install", p.stderr)
        self.assertIn("then reruns `lane park chart-fix`", p.stderr)
        self.assertNotIn("removing it would break them", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_a_busy_session(self):
        self.ready()
        (claude,) = self.start(self.fake(self.path))
        self.session_file(claude, status="busy")
        p = self.run_lane("park", "chart-fix")
        self.assertIn("is busy", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_a_foreign_process_in_the_lane(self):
        self.ready()
        (claude,) = self.claude()
        (stray,) = self.start(self.fake(self.path))
        p = self.run_lane("park", "chart-fix")
        self.assertIn("nothing proves these processes", p.stderr)
        self.assertIn("rerun `lane park chart-fix`", p.stderr)
        self.assertRefusedUntouched(p, claude, stray)

    def test_run_from_a_lane(self):
        self.ready()
        (claude,) = self.claude()
        p = self.run_lane("park", "chart-fix", cwd=self.path)
        self.assertIn("only the lead (the main checkout) parks lanes", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_stale_closing_or_setup_failed(self):
        self.ready()
        rec = self.lane_json("chart-fix")
        data = os.path.join(self.common, "lanes", "chart-fix", "lane.json")
        for state, said in (("closing", "is closing"), ("setup-failed", "is setup-failed")):
            with self.subTest(state):
                self.write(data, json.dumps(dict(rec, state=state)))
                p = self.run_lane("park", "chart-fix")
                self.assertIn(said, p.stderr)
                self.assertRefusedUntouched(p)
        self.write(data, json.dumps(rec))
        shutil.rmtree(self.path)
        p = self.run_lane("park", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertIn("is stale", p.stderr)
        self.assertEqual(glob.glob(self.flag_glob()), [])


class Cap(ParkBase):
    """Who holds a cap slot: a live lane, unless parked with no session in it."""

    def tmux(self, fail=False):
        tmux = os.path.join(self.fake_bin, "tmux")
        self.write(tmux, "#!/bin/sh\necho 'no server' >&2; exit 1\n" if fail else
                   "#!/bin/sh\necho 'proj:3 (chart-fix)'\n")
        os.chmod(tmux, 0o755)
        self.env["TMUX"] = "/tmp/fake-tmux,1,0"

    def test_new_skips_a_parked_lane(self):
        self.lane("init", "--cap", "1")
        self.assertIn("cap", self.run_lane("new", "other").stderr)
        self.flag()
        self.lane("new", "other")

    def test_a_parked_lane_with_a_live_session_holds_its_slot(self):
        self.lane("init", "--cap", "1")
        self.flag()
        self.claude()  # started by hand: `cd <lane> && claude`
        self.assertIn("cap", self.run_lane("new", "other").stderr)

    def test_a_mismatched_or_garbled_flag_counts_as_not_parked(self):
        self.lane("init", "--cap", "1")
        for case in ({"created": "2020-01-01T00:00:00+00:00"}, {"lane": "other"},
                     {"path": self.main}, None):
            with self.subTest(case):
                if case is None:
                    (flag,) = glob.glob(self.flag_glob())
                    self.write(flag, "{")
                else:
                    self.flag(**case)
                self.assertIn("cap", self.run_lane("new", "other").stderr)
                self.assertNotIn("parked", self.row()["flags"])

    def test_open_unparks_one_over_the_cap_and_refuses_a_second(self):
        self.lane("init", "--cap", "1")
        self.flag()
        self.lane("new", "beta")
        self.flag("beta")
        self.lane("new", "gamma")  # gamma holds the one slot
        self.tmux()
        out = self.lane("open", "chart-fix")
        self.assertIn("lane chart-fix is over the cap of 1 by one: for its rebase and merge", out)
        self.assertEqual(glob.glob(self.flag_glob()), [])
        self.assertIn("cap: 2 of 1 slots held (1 parked), 1 over", self.lane("ls"))
        p = self.run_lane("open", "beta")
        self.assertEqual(p.returncode, 1)
        self.assertIn("over the cap", p.stderr)
        self.assertEqual(len(glob.glob(self.flag_glob("beta"))), 1)

    def test_open_keeps_the_flag_when_tmux_fails(self):
        self.flag()
        self.tmux(fail=True)
        p = self.run_lane("open", "chart-fix")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len(glob.glob(self.flag_glob())), 1)

    def test_open_print_refuses_a_parked_lane(self):
        self.flag()
        p = self.run_lane("open", "chart-fix", "--print")
        self.assertEqual(p.returncode, 1)
        self.assertIn("is parked", p.stderr)
        self.assertEqual(len(glob.glob(self.flag_glob())), 1)


class Round1(ParkBase):
    """Review round 1: what the gates' first answers can't settle by the time of the signals."""

    def park_in_process(self, lane_mod):
        """cmd_park in this process, from the main checkout, with the fixture's environment."""
        cwd = os.getcwd()
        os.chdir(self.main)
        try:
            with mock.patch.dict(os.environ, self.env, clear=True):
                lane_mod.cmd_park(argparse.Namespace(id="chart-fix"))
        finally:
            os.chdir(cwd)

    def flips_to(self, pid, status):
        """A stand-in handoff-check that passes and sets pid's session file status, as a
        session that took a turn while the gates ran."""
        fake = os.path.join(self.tmp, f"handoff-{status}.py")
        sess = os.path.join(self.home, ".claude", "sessions", f"{pid}.json")
        self.write(fake, "import json\n"
                         f"p = {sess!r}\n"
                         "d = json.load(open(p))\n"
                         f"d['status'] = {status!r}\n"
                         "json.dump(d, open(p, 'w'))\n")
        return fake

    def test_a_session_that_goes_busy_or_waiting_during_the_gates_refuses(self):
        self.ready()
        lane_mod = test_cli.load_lane_script()
        (claude,) = self.claude()
        for status, said in (("busy", "is busy"), ("waiting", "is waiting")):
            with self.subTest(status):
                with mock.patch.object(lane_mod, "HANDOFF_CHECK", self.flips_to(claude, status)):
                    with self.assertRaisesRegex(lane_mod.LaneError, said):
                        self.park_in_process(lane_mod)
                self.assertTrue(self.alive(claude))
                self.assertEqual(self.signals(), [])
                self.assertEqual(glob.glob(self.flag_glob()), [])
                self.assertEqual(glob.glob(self.proof()), [])
                self.session_file(claude)  # idle again for the next case

    def test_a_refused_park_with_nothing_to_end_keeps_the_restore_entries(self):
        self.ready()
        lane_mod = test_cli.load_lane_script()
        entry = self.open_session_entry("sess-lane-0007", self.path)
        with mock.patch.object(lane_mod, "end_lane",
                               side_effect=lane_mod.LaneError("started during the park")):
            with self.assertRaisesRegex(lane_mod.LaneError, "started during the park"):
                self.park_in_process(lane_mod)
        self.assertTrue(os.path.exists(entry))

    def test_a_planted_remote_tracking_ref_is_no_push(self):
        self.ready(push=False)
        self.git("update-ref", "refs/remotes/origin/chart-fix",
                 self.git("rev-parse", "HEAD", cwd=self.path).strip())
        (claude,) = self.claude()
        p = self.run_lane("park", "chart-fix")
        self.assertIn("is not on origin/chart-fix", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_an_unreachable_remote_refuses(self):
        self.ready()
        (claude,) = self.claude()
        self.git("remote", "set-url", "origin", os.path.join(self.tmp, "gone.git"))
        p = self.run_lane("park", "chart-fix")
        self.assertIn("can't ask origin", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_a_detached_head_refuses(self):
        self.ready()
        self.git("checkout", "-q", "--detach", cwd=self.path)
        (claude,) = self.claude()
        p = self.run_lane("park", "chart-fix")
        self.assertIn("detached HEAD", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_worktree_config_refuses_in_parks_words(self):
        self.ready()
        (claude,) = self.claude()
        self.git("config", "extensions.worktreeConfig", "true")
        p = self.run_lane("park", "chart-fix")
        self.assertIn("`park` won't run git there sandbox-off", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_park_under_a_lanes_session_from_the_main_checkout_refuses(self):
        self.ready()
        pid, go, out = self.act_under(self.fake(self.path), ["park", "chart-fix"])
        self.session_file(pid, "sess-lane-0005")
        res = self.await_done(go, out)
        self.assertEqual(res["rc"], 1, res["err"])
        self.assertIn("only the lead (the main checkout) parks lanes", res["err"])
        self.assertIn("This `lane park` runs under session sess-lane-0005", res["err"])
        self.assertTrue(self.alive(pid))
        self.assertEqual(self.signals(), [])
        self.assertEqual(glob.glob(self.flag_glob()), [])


class Round1Cap(ParkBase):
    """Review round 1's cap cases."""

    tmux = Cap.tmux

    def test_open_under_the_cap_unparks_with_no_over_line(self):
        self.flag()
        self.tmux()
        out = self.lane("open", "chart-fix")
        self.assertNotIn("over the cap", out)
        self.assertEqual(glob.glob(self.flag_glob()), [])

    def test_new_counts_a_parked_lane_while_liveness_is_unknown(self):
        self.lane("init", "--cap", "1")
        self.flag()
        self.write(os.path.join(self.home, ".claude", "sessions", f"{os.getpid()}.json"), "{")
        self.assertIn("cap", self.run_lane("new", "other").stderr)

    def test_a_parked_lane_with_only_a_stopped_session_holds_its_slot(self):
        self.lane("init", "--cap", "1")
        self.flag()
        (claude,) = self.claude()
        self.stop(claude)
        self.assertIn("cap", self.run_lane("new", "other").stderr)

    def test_the_cap_line_names_how_far_over(self):
        self.lane("init", "--cap", "1")
        self.flag()
        self.lane("new", "beta")
        self.flag("beta")
        self.lane("new", "gamma")
        self.claude()  # sessions started by hand in both parked lanes
        (other,) = self.start(self.fake(self.lane_path("beta")))
        self.session_file(other, "sess-lane-0002", cwd=self.lane_path("beta"))
        self.assertIn("cap: 3 of 1 slots held (2 parked), 2 over", self.lane("ls"))

    def test_a_second_open_waiting_on_the_lock_sees_the_first_lane_holding_its_slot(self):
        # Two opens of parked lanes at the cap: the second waits on the lanes lock the first
        # holds from its cap check to its flag's removal, then counts it and refuses.
        self.lane("init", "--cap", "1")
        self.flag()
        self.lane("new", "beta")
        self.flag("beta")
        self.lane("new", "gamma")  # gamma holds the one slot
        self.tmux()
        repo = lanelib.resolve(self.main)
        lock_file = os.path.join(self.common, "lanes", ".lock")
        with lanelib.lock(repo):
            second = subprocess.Popen([sys.executable, LANE, "open", "beta"], cwd=self.main,
                                      env=self.env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True)
            self.addCleanup(lambda: second.poll() is None and (second.kill(), second.wait()))
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and second.poll() is None:
                fds = os.path.join("/proc", str(second.pid), "fd")
                try:
                    if any(os.readlink(os.path.join(fds, f)) == lock_file
                           for f in os.listdir(fds)):
                        break
                except OSError:
                    pass
                time.sleep(0.02)
            time.sleep(0.2)  # from its open to its flock
            # The first open finishing under the lock: its window opened, its flag removed.
            (flag,) = glob.glob(self.flag_glob())
            os.remove(flag)
        out, err = second.communicate(timeout=60)
        self.assertEqual(second.returncode, 1, out + err)
        self.assertIn("over the cap", err)
        self.assertEqual(len(glob.glob(self.flag_glob("beta"))), 1)
