"""`lane addr`: the messaging address of the one live session in a lane, or in the main checkout
for `lead`, where the lead record picks one among several. A live session is a session file
whose pid runs with the procStart the file records (a child `sleep` here, started in the
session's launch dir) and whose messagingSocketPath is a socket on disk (_fixture.LiveSessions).
Where a session is comes from its file's cwd, as `lane ls` and `open` read it."""
import json
import os
import shutil
import stat
import subprocess
import time
import unittest
from unittest import mock

from _fixture import LiveSessions
import lanelib  # noqa: E402  (on sys.path once _fixture is imported)


class Addr(LiveSessions):
    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix")

    def refused(self, lane_id, *needles):
        p = self.run_lane("addr", lane_id)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(p.stdout, "")
        for needle in needles:
            self.assertIn(needle, p.stderr)
        return p.stderr

    def test_a_lane_resolves_to_its_one_live_session(self):
        want = self.session(os.path.join(self.lane_path("chart-fix"), "src"))
        self.session(self.main)  # the lead's, not the lane's
        self.assertEqual(self.lane("addr", "chart-fix"), want + "\n")
        # From inside a lane too: the repo is found from any of its checkouts.
        self.assertEqual(self.lane("addr", "chart-fix", cwd=self.lane_path("chart-fix")),
                         want + "\n")

    def test_a_lane_finds_the_lead(self):
        # The call a lane's SessionStart line tells it to make, from inside its worktree.
        want = self.session(self.main)
        self.session(self.lane_path("chart-fix"))
        self.assertEqual(self.lane("addr", "lead", cwd=self.lane_path("chart-fix")), want + "\n")

    def test_the_session_file_cwd_places_a_session(self):
        # The file's cwd is the launch dir (a Bash cd doesn't move it), the one `ls` and `open`
        # read; the process's own cwd plays no part, so all three agree.
        want = self.session(self.main, cwd=self.lane_path("chart-fix"))
        self.assertEqual(self.lane("addr", "chart-fix"), want + "\n")
        self.refused("lead", "no live session in the main checkout")

    def test_a_lane_named_lead_makes_lead_ambiguous(self):
        # One from before the id was reserved; sandboxed Bash could plant the dir too, which only
        # makes addr refuse.
        self.session(self.main)
        os.makedirs(os.path.join(self.common, "lanes", "lead"))
        self.refused("lead", "ambiguous: a lane is named lead too")

    def test_the_lead_is_the_main_checkout_with_its_agent_worktrees(self):
        self.session(self.lane_path("chart-fix"))
        want = self.session(os.path.join(self.main, ".claude", "worktrees", "agent-a1"))
        self.assertEqual(self.lane("addr", "lead"), want + "\n")

    def test_none_live_refuses_with_the_way_to_start_one(self):
        self.refused("chart-fix", "no live session in lane chart-fix", "`lane open chart-fix`")
        self.refused("lead", "no live session in the main checkout")

    def test_several_live_refuse_and_list_each(self):
        a = self.session(self.lane_path("chart-fix"))
        b = self.session(os.path.join(self.lane_path("chart-fix"), "src"))
        err = self.refused("chart-fix", "2 live sessions in lane chart-fix", " interactive ")
        self.assertIn(a, err)
        self.assertIn(b, err)

    def test_a_stale_session_file_is_not_live(self):
        path = self.lane_path("chart-fix")
        cases = {
            "pid exited": dict(pid=self.child(done=True), start=1),
            "pid reused": dict(skew=1),  # a running child in the lane, but not that process
            "no procStart": dict(procStart=None),
            "socket gone": dict(sock=None),
            "not a socket": dict(sock="file"),
            # Each a real socket, so only the path check refuses it. `lane` runs in self.main.
            "socket path relative": dict(path=os.path.join(self.main, "rel.sock"),
                                         messagingSocketPath="rel.sock"),
            "socket path with a newline": dict(path=os.path.join(self.socks, "a\nuds:b.sock")),
            "socket path with an escape": dict(path=os.path.join(self.socks, "a\x1b[2Jb.sock")),
        }
        for why, kw in cases.items():
            with self.subTest(why):
                for d in (os.path.join(self.home, ".claude", "sessions"), self.socks):
                    for f in os.listdir(d):
                        os.unlink(os.path.join(d, f))
                self.session(path, **kw)
                self.refused("chart-fix", "no live session in lane chart-fix")

    def test_a_zombie_is_not_live(self):
        p = subprocess.Popen(["true"], cwd=self.lane_path("chart-fix"))
        self.addCleanup(p.wait)
        deadline = time.time() + 10
        while (lanelib.proc_stat(p.pid) or ("", "Z"))[1] != "Z" and time.time() < deadline:
            time.sleep(0.02)
        self.session(self.lane_path("chart-fix"), pid=p.pid)
        self.refused("chart-fix", "no live session")

    def test_sandboxed_it_refuses_rather_than_guess(self):
        self.session(self.lane_path("chart-fix"))
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        self.refused("chart-fix", "sandboxed", "bare `lane addr chart-fix`")

    def test_a_rewritten_lane_path_is_refused(self):
        # Sandboxed Bash can write lane.json: a path pointed at a plain dir holding someone
        # else's live session must not hand out that session's address.
        other = os.path.join(self.tmp, "elsewhere")
        self.session(other)
        rec = os.path.join(self.common, "lanes", "chart-fix", "lane.json")
        data = json.loads(self.read(rec))
        data["path"] = other
        self.write(rec, json.dumps(data))
        self.refused("chart-fix", "refusing lane chart-fix")

    def test_a_stale_lane_is_refused(self):
        shutil.rmtree(self.lane_path("chart-fix"))
        self.refused("chart-fix", "lane chart-fix is stale")

    def test_an_unknown_or_bad_id_refuses(self):
        self.refused("nope", "no lane nope")
        self.refused("../x", "bad lane id")

    def test_a_socket_another_user_owns_is_refused(self):
        path = os.path.join(self.socks, "x.sock")
        os.mknod(path, stat.S_IFSOCK | 0o600)
        self.assertEqual(lanelib.socket_of({"messagingSocketPath": path}), path)
        with mock.patch.object(lanelib.os, "getuid", return_value=os.getuid() + 1):
            self.assertIsNone(lanelib.socket_of({"messagingSocketPath": path}))

    def test_lead_is_reserved_for_a_new_lane_only(self):
        self.refused_cmd(["new", "lead"], "lane id 'lead' is reserved")
        lead = os.path.join(self.tmp, "lead")
        self.git("worktree", "add", "-q", "-b", "lead", lead)
        self.refused_cmd(["adopt", lead], "lane id 'lead' is reserved")
        # A lane named lead from before the reservation still loads and can be closed.
        self.assertTrue(lanelib.valid_id("lead"))

    def refused_cmd(self, argv, needle):
        p = self.run_lane(*argv)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn(needle, p.stderr)


class LeadPick(LiveSessions):
    """`lane addr lead` with two or more live sessions in the main checkout: the lead record
    (lanelib.read_lead) picks one by pid and procStart, else by the tmux server and pane its
    process runs in (a /pass successor), else none, and the refusal says how to pick."""

    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix")

    def addr_lead(self):
        """What a lane gets when it asks for the lead, from inside its worktree."""
        return self.lane("addr", "lead", cwd=self.lane_path("chart-fix")).strip()

    def refused(self, *needles):
        p = self.run_lane("addr", "lead")
        self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)
        for needle in needles:
            self.assertIn(needle, p.stderr)
        return p.stderr

    def pair(self, panes=("new", "new")):
        """Two live sessions in the main checkout, one in each pane: [(pid, uds)]."""
        out = []
        for pane in panes:
            pid = self.child(self.main, pane=pane)
            out.append((pid, self.session(self.main, pid=pid)))
        return out

    def test_the_record_picks_the_lead_by_pid_and_start(self):
        (_, _), (b, want) = self.pair()
        self.write_lead(b)
        self.assertEqual(self.addr_lead(), want)

    def test_a_clear_keeps_the_lead(self):
        # /clear starts a new session id in the same process: pid and procStart still match.
        (a, want), _ = self.pair()
        self.write_lead(a, sid="s-before-clear")
        self.assertEqual(self.addr_lead(), want)

    def test_a_pass_successor_in_the_recorded_pane_takes_the_lead(self):
        # The recorded claude is gone; `respawn-pane -k` keeps the pane, so its successor runs
        # in the same pane on the same server.
        gone = self.child(self.main, done=True)
        (_, want), _ = self.pair(("%7", "%8"))
        self.write_lead(gone, start=1, tmux=self.tmux_of("%7"))
        self.assertEqual(self.addr_lead(), want)

    def test_the_recorded_pane_on_another_server_picks_none(self):
        # Pane ids restart at %0 on every server, and a tmux restart may reuse the server pid.
        gone = self.child(self.main, done=True)
        self.pair(("%7", "%8"))
        sock, pid, start, pane = self.tmux_of("%7")
        cases = {"another socket": [sock + "-2", pid, start, pane],
                 "another server": self.tmux_of("%7", self.tmux_server("other")),
                 "the server pid reused": [sock, pid, start + 1, pane]}
        for why, tmux in cases.items():
            with self.subTest(why):
                self.write_lead(gone, start=1, tmux=tmux)
                self.refused("2 live sessions in the main checkout", "No lead picked")

    def test_two_sessions_in_the_recorded_pane_pick_none(self):
        # A claude started from the lead's Bash inherits its TMUX_PANE.
        gone = self.child(self.main, done=True)
        self.pair(("%7", "%7"))
        self.write_lead(gone, start=1, tmux=self.tmux_of("%7"))
        self.refused("No lead picked")

    def test_one_live_session_is_the_lead_whatever_the_record_names(self):
        want = self.session(self.main)
        other = self.child(self.main)
        self.write_lead(other, tmux=self.tmux_of("%1"))
        self.assertEqual(self.addr_lead(), want)

    def test_no_pick_refuses_with_each_window_and_the_way_to_pick(self):
        (a, ua), (b, ub) = self.pair()
        err = self.refused("2 live sessions in the main checkout (the lead), so no one address",
                           f"pid {a} interactive proj:@{a} idle {ua}",
                           f"pid {b} interactive proj:@{b} idle {ub}",
                           "No lead picked: the lead takes it with a bare `lane lead`",
                           "(Hayden: `! lane lead` at the lead's prompt)",
                           "or any bare lane new, open, adopt or done it runs",
                           "After a tmux restart the lead must act again")
        self.assertNotIn(f"%{a}", err)  # the window, not the pane

    def test_a_bad_record_picks_none(self):
        (a, _), _ = self.pair()
        start = lanelib.proc_start(a)
        good = {"pid": a, "procStart": start, "sessionId": f"s-{a}", "tmux": None,
                "at": "2026-10-14T21:05:00+00:00"}
        cases = {"not JSON": "{", "a list": "[]", "pid a string": dict(good, pid=str(a)),
                 "procStart a string": dict(good, procStart=str(start)),
                 "pid a bool": dict(good, pid=True), "no session id": dict(good, sessionId=None),
                 "a bad session id": dict(good, sessionId="../x"),
                 "no at": {k: v for k, v in good.items() if k != "at"},
                 "tmux too short": dict(good, tmux=["/s", 1, 1]),
                 "tmux pane bad": dict(good, tmux=["/s", 1, 1, "7"]),
                 "tmux socket relative": dict(good, tmux=["s", 1, 1, "%7"]),
                 "too long": dict(good, pad="x" * lanelib.LEAD_MAX)}
        for why, rec in cases.items():
            with self.subTest(why):
                self.write(self.lead_path, rec if isinstance(rec, str) else json.dumps(rec))
                self.assertIsNone(lanelib.read_lead(lanelib.Repo(self.main, self.common)))
                self.refused("No lead picked")
        self.write(self.lead_path, json.dumps(good))
        self.assertEqual(lanelib.read_lead(lanelib.Repo(self.main, self.common)), good)

    def test_proc_tmux_reads_the_process_own_environment(self):
        sock, server, start, _ = self.tmux_of("%3")
        self.assertEqual(lanelib.proc_tmux(self.child(pane="%3")), (sock, server, start, "%3"))
        self.assertIsNone(lanelib.proc_tmux(self.child(pane=None)))
        # A socket path may hold a comma: split from the right, as tmux-tab-bar does.
        odd = self.tmux_server("a,b")
        self.assertEqual(lanelib.proc_tmux(self.child(pane="%4", server=odd))[0],
                         os.path.join(self.tmp, "tmux-sock", "a,b"))
        gone = self.child(done=True)  # a server pid that no longer runs has no start
        self.assertIsNone(lanelib.proc_tmux(self.child(pane="%5", server=f"/s,{gone},0")))
        for bad in ("/s,x,0", "rel,1,0", "/s,1"):
            with self.subTest(bad):
                self.assertIsNone(lanelib.proc_tmux(self.child(pane="%5", server=bad)))


if __name__ == "__main__":
    unittest.main()
