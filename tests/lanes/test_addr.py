"""`lane addr`: the messaging address of the one live session in a lane, or in the main checkout
for `lead`. A live session is a session file whose pid runs with the procStart the file records
(a child `sleep` here, started in the session's launch dir) and whose messagingSocketPath is a
socket on disk (made with mknod, which the Bash sandbox allows where socket() is refused). Where a
session is comes from its file's cwd, as `lane ls` and `open` read it."""
import json
import os
import shutil
import stat
import subprocess
import time
import unittest
from unittest import mock

from _fixture import LanesRepo
import lanelib  # noqa: E402  (on sys.path once _fixture is imported)


class Addr(LanesRepo):
    def setUp(self):
        super().setUp()
        self.socks = os.path.join(self.tmp, "socks")
        os.makedirs(self.socks)
        self.lane("new", "chart-fix")

    def child(self, cwd=None, done=False):
        """A process in cwd: running (`sleep`), or exited and reaped (done)."""
        p = subprocess.Popen(["sleep", "60"] if not done else ["true"], cwd=cwd)
        self.addCleanup(lambda: p.poll() is None and (p.kill(), p.wait()))
        if done:
            p.wait()
        return p.pid

    def session(self, at, pid=None, start=None, skew=0, sock="socket", path=None, **extra):
        """A session file for pid (by default a fresh child running in at, the launch dir)
        whose cwd field is at unless extra overrides it. sock: "socket" makes one at path (by
        default under self.socks), "file" a regular file there, None leaves it missing. skew
        shifts the recorded procStart off the real one: the pid, reused."""
        os.makedirs(at, exist_ok=True)
        pid = pid or self.child(at)
        if start is None:
            start = (lanelib.proc_start(pid) or 1) + skew
        path = path or os.path.join(self.socks, f"{pid}.sock")
        if sock == "socket":
            os.mknod(path, stat.S_IFSOCK | 0o600)
        elif sock == "file":
            self.write(path, "")
        self.write(os.path.join(self.home, ".claude", "sessions", f"{pid}.json"),
                   json.dumps({"pid": pid, "procStart": str(start), "sessionId": f"s-{pid}", "kind": "interactive",
                               "cwd": at, "tmux": f"proj:@{pid}.%{pid}", "status": "idle",
                               "messagingSocketPath": path, **extra}))
        return "uds:" + path

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


if __name__ == "__main__":
    unittest.main()
