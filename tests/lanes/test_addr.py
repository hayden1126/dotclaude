"""`lane addr`: the messaging address of the one live session in a lane, or in the main checkout
for `lead`, where the lead record picks one among several. A live session is a session file
whose pid runs with the procStart the file records (a child `sleep` here, started in the
session's launch dir) and whose messagingSocketPath is a socket on disk (_fixture.LiveSessions).
Where a session is comes from its file's cwd, as `lane ls` and `open` read it."""
import contextlib
import json
import json.decoder
import json.scanner
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
import unittest
from unittest import mock

from _fixture import LANE, LiveSessions
import lanelib  # noqa: E402  (on sys.path once _fixture is imported)
from test_cli import load_lane_script

# Lead records that fit in LEAD_MAX bytes and nest past json's reach in pure Python (pure_json).
DEEP_RECORDS = {"nested lists": "[" * 2048 + "]" * 2048,
                "a nested object": '{"pid": ' + "[" * 2040 + "]" * 2040 + "}"}
# `lane` (argv[1], its arguments after) with json's pure-Python scanner, as pure_json sets.
PURE_JSON_LANE = """
import json, json.decoder, json.scanner, runpy, sys
json.scanner.make_scanner = json.scanner.py_make_scanner
json._default_decoder = json.decoder.JSONDecoder()
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


@contextlib.contextmanager
def pure_json():
    """json.loads through json's pure-Python scanner, CPython's own fallback when its C one is
    missing. It recurses in Python, so it raises RecursionError near the recursion limit (1000
    levels). This interpreter's C scanner reaches about 10000 levels, more than LEAD_MAX bytes
    can nest, so without this no lead record raises here; older or other builds stop sooner."""
    with mock.patch.object(json.scanner, "make_scanner", json.scanner.py_make_scanner), \
            mock.patch.object(json, "_default_decoder", json.decoder.JSONDecoder()):
        yield


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
        deadline = time.monotonic() + 10
        while (lanelib.proc_stat(p.pid) or ("", "Z"))[1] != "Z" and time.monotonic() < deadline:
            time.sleep(0.02)
        self.session(self.lane_path("chart-fix"), pid=p.pid)
        self.refused("chart-fix", "no live session")

    def test_a_stopped_session_is_named_never_addressed(self):
        # Its socket still accepts connections, but nothing answers until `fg` continues it.
        path = self.lane_path("chart-fix")
        stopped = self.child(path)
        self.session(path, pid=stopped, sessionId="s-lane")
        self.stop(stopped)
        err = self.refused("chart-fix", "no live session in lane chart-fix",
                           f"a session (pid {stopped}, proj:@{stopped}) is stopped (Ctrl+Z): "
                           "fg it there")
        self.assertNotIn("lane open", err)
        twin = self.session(path, sessionId="s-lane")  # resumed elsewhere: the one that answers
        self.assertEqual(self.lane("addr", "chart-fix"), twin + "\n")

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
        # The record names a process that runs but isn't a main-checkout session, in a pane
        # of its own: no continuation, so the one-session rule alone picks.
        want = self.session(self.main, pane="%1")
        other = self.child(self.main, pane="%2")
        self.write_lead(other, tmux=self.tmux_of("%2"))
        self.assertEqual(self.addr_lead(), want)

    def test_a_fresh_claude_in_a_stopped_lead_s_pane_never_takes_it(self):
        # Ctrl+Z, then a plain `claude` (a new session id) in the same shell: the pane rule is
        # for a /pass successor, whose `respawn-pane -k` ends the old claude. Beside a recorded
        # process that only stopped, a claude in its pane is a fresh one (Hayden's call 2).
        lead = self.child(self.main, pane="%3")
        self.session(self.main, pid=lead)
        fresh = self.session(self.main, pane="%3")
        self.write_lead(lead, tmux=self.tmux_of("%3"))
        self.stop(lead)
        err = self.refused("it is not the lead",
                           f"The lead (pid {lead}, proj:@{lead}) is stopped (Ctrl+Z): fg it there")
        self.assertIn(fresh, err)  # listed, never printed as the address
        self.session(self.main, pane="%4")  # beside a side chat too
        self.refused("2 live sessions in the main checkout", "No lead picked",
                     f"The lead (pid {lead}, proj:@{lead}) is stopped (Ctrl+Z): fg it there")

    def test_a_background_session_never_leads(self):
        # A `claude --bg` session has a messaging socket too, but the lead is one Hayden talks
        # to (`lane lead` refuses kind bg): not a main session, so not counted or picked, even
        # as a resume of the lead's session id.
        gone = self.child(self.main, done=True)
        want = self.session(self.main)
        self.session(self.main, kind="bg", sessionId="s-lead")
        self.write_lead(gone, start=1, sid="s-lead")
        self.assertEqual(self.addr_lead(), want)

    def test_a_gone_record_and_one_unrelated_session_picks_that_one(self):
        gone = self.child(self.main, done=True)
        want = self.session(self.main)
        self.write_lead(gone, start=1, tmux=self.tmux_of("%7"))
        self.assertEqual(self.addr_lead(), want)

    # ---- a stopped lead (Ctrl+Z) and the continuations of the lead's session ----------------

    def incident(self):
        """2026-10-17: the recorded lead stopped in pane %3, the same session id resumed there
        as a twin, and a side session in a pane of its own. (lead pid, its uds, twin's uds)."""
        lead = self.child(self.main, pane="%3")
        lead_uds = self.session(self.main, pid=lead, sessionId="s-lead")
        twin = self.child(self.main, pane="%3")
        twin_uds = self.session(self.main, pid=twin, sessionId="s-lead")
        self.session(self.main)
        self.write_lead(lead, sid="s-lead", tmux=self.tmux_of("%3"))
        self.stop(lead)
        return lead, lead_uds, twin_uds

    def test_a_stopped_lead_whose_healed_twin_ended_still_refuses(self):
        # The heal moved the record to the twin, and the twin exited while the original stays
        # stopped: the record names a gone process, but the original still holds the session
        # id, so the one side chat never inherits the lead (Hayden's call 2).
        lead = self.child(self.main, pane="%3")
        self.session(self.main, pid=lead, sessionId="s-lead")
        twin = self.child(self.main, pane="%3")
        self.session(self.main, pid=twin, sessionId="s-lead")
        side = self.session(self.main, pane="%4")
        self.stop(lead)
        self.write_lead(twin, sid="s-lead", tmux=self.tmux_of("%3"))
        os.kill(twin, signal.SIGKILL)  # a zombie until cleanup reaps it: exited all the same
        deadline = time.monotonic() + 10
        while (lanelib.proc_stat(twin) or "xx")[1] not in lanelib.EXITED \
                and time.monotonic() < deadline:
            time.sleep(0.01)
        err = self.refused("it is not the lead",
                           f"The lead (pid {lead}, proj:@{lead}) is stopped (Ctrl+Z): fg it there")
        self.assertIn(side, err)  # listed, never printed as the address

    def test_a_fresh_claude_in_the_pane_of_a_healed_twin_that_ended_never_takes_it(self):
        # As above, but the side session is a plain `claude` typed in the twin's pane, where
        # the original is still a stopped job: the recorded process is gone, yet the pane rule
        # stays off while a stopped session holds the recorded id (review round 4).
        lead = self.child(self.main, pane="%3")
        self.session(self.main, pid=lead, sessionId="s-lead")
        twin = self.child(self.main, pane="%3")
        self.session(self.main, pid=twin, sessionId="s-lead")
        self.stop(lead)
        self.write_lead(twin, sid="s-lead", tmux=self.tmux_of("%3"))
        os.kill(twin, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while (lanelib.proc_stat(twin) or "xx")[1] not in lanelib.EXITED \
                and time.monotonic() < deadline:
            time.sleep(0.01)
        fresh = self.session(self.main, pane="%3")
        err = self.refused("it is not the lead",
                           f"The lead (pid {lead}, proj:@{lead}) is stopped (Ctrl+Z): fg it there")
        self.assertIn(fresh, err)

    def test_a_stopped_lead_resumed_in_its_pane_picks_the_twin(self):
        _, _, twin = self.incident()
        self.assertEqual(self.addr_lead(), twin)

    def test_a_stopped_lead_continued_is_the_lead_again(self):
        lead, want, _ = self.incident()
        self.cont(lead)
        self.assertEqual(self.addr_lead(), want)

    def test_a_resume_in_another_tab_beside_a_side_session_is_the_lead(self):
        gone = self.child(self.main, done=True)
        want = self.session(self.main, sessionId="s-lead")
        self.session(self.main)
        self.write_lead(gone, start=1, sid="s-lead", tmux=self.tmux_of("%7"))
        self.assertEqual(self.addr_lead(), want)

    def test_a_tmux_restart_that_resumes_the_lead_keeps_it(self):
        # The record names a pane on the old server; the restored tab resumes the session id in
        # a new pane (pane ids restart at %0, so it may even reuse the old id).
        gone = self.child(self.main, done=True)
        restored = self.child(self.main, pane="%7")
        want = self.session(self.main, pid=restored, sessionId="s-lead")
        self.session(self.main)
        self.write_lead(gone, start=1, sid="s-lead",
                        tmux=self.tmux_of("%7", self.tmux_server("old")))
        self.assertEqual(self.addr_lead(), want)

    def test_a_resume_and_another_claude_in_the_recorded_pane_pick_none(self):
        gone = self.child(self.main, done=True)
        in_pane = self.child(self.main, pane="%7")
        self.session(self.main, pid=in_pane)
        self.session(self.main, sessionId="s-lead")
        self.write_lead(gone, start=1, sid="s-lead", tmux=self.tmux_of("%7"))
        self.refused("2 live sessions in the main checkout", "No lead picked")

    def test_two_resumes_of_the_recorded_session_pick_none(self):
        gone = self.child(self.main, done=True)
        self.session(self.main, sessionId="s-lead")
        self.session(self.main, sessionId="s-lead")
        self.write_lead(gone, start=1, sid="s-lead")
        self.refused("2 live sessions in the main checkout", "No lead picked")

    def test_a_stopped_lead_beside_one_unrelated_session_refuses_naming_it(self):
        # Hayden's call (2026-10-17): the one running session is likely a side chat, so it
        # never inherits the lead from a lead that is only stopped.
        lead = self.child(self.main, pane="%3")
        self.session(self.main, pid=lead)
        side = self.session(self.main)
        self.write_lead(lead, tmux=self.tmux_of("%3"))
        self.stop(lead)
        err = self.refused("1 live session in the main checkout (the lead), and it is not the "
                           "lead", f"The lead (pid {lead}, proj:@{lead}) is stopped (Ctrl+Z): "
                           "fg it there")
        self.assertIn(side, err)  # listed, never printed as the address
        self.cont(lead)
        self.assertEqual(self.addr_lead(), f"uds:{os.path.join(self.socks, f'{lead}.sock')}")

    def test_a_stopped_lead_alone_refuses_naming_it(self):
        lead = self.child(self.main, pane="%3")
        self.session(self.main, pid=lead)
        self.write_lead(lead, tmux=self.tmux_of("%3"))
        self.stop(lead)
        self.refused("no live session in the main checkout (the lead)",
                     f"The lead (pid {lead}, proj:@{lead}) is stopped (Ctrl+Z): fg it there")

    def test_no_pick_refuses_with_each_window_and_the_way_to_pick(self):
        (a, ua), (b, ub) = self.pair()
        err = self.refused("2 live sessions in the main checkout (the lead), so no one address",
                           f"pid {a} interactive proj:@{a} idle {ua}",
                           f"pid {b} interactive proj:@{b} idle {ub}",
                           "No lead picked: the lead takes it with a bare `lane lead`",
                           "(Hayden: `! lane lead` at the lead's prompt)",
                           "or any bare lane new, open, adopt or done it runs",
                           "After a tmux restart, a restored tab that resumes the lead's "
                           "session keeps the lead; otherwise the lead must act again")
        self.assertNotIn("stopped", err)
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
                 "too long": dict(good, pad="x" * lanelib.LEAD_MAX), **DEEP_RECORDS}
        for why, rec in cases.items():
            with self.subTest(why):
                self.write(self.lead_path, rec if isinstance(rec, str) else json.dumps(rec))
                self.assertIsNone(lanelib.read_lead(lanelib.Repo(self.main, self.common)))
                self.refused("No lead picked")
        self.write(self.lead_path, json.dumps(good))
        self.assertEqual(lanelib.read_lead(lanelib.Repo(self.main, self.common)), good)

    def test_a_record_nested_past_json_reach_picks_none(self):
        # json raises RecursionError, not ValueError, on deep nesting: `addr lead` and `ls`
        # printed a traceback. pure_json makes that reachable here (its docstring says why).
        self.pair()
        for why, rec in DEEP_RECORDS.items():
            with self.subTest(why):
                self.assertLessEqual(len(rec), lanelib.LEAD_MAX)
                self.write(self.lead_path, rec)
                with pure_json():
                    self.assertRaises(RecursionError, json.loads, rec)
                    self.assertIsNone(lanelib.read_lead(lanelib.Repo(self.main, self.common)))
                p = self.run_pure_json("addr", "lead")
                self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)
                self.assertIn("2 live sessions in the main checkout", p.stderr)
                self.assertIn("No lead picked", p.stderr)
                self.assertNotIn("Traceback", p.stderr)
                p = self.run_pure_json("ls")
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn("main checkout: 2 live sessions", p.stdout)
                self.assertIn("No lead picked", p.stdout)

    def run_pure_json(self, *args):
        """run_lane with json's pure-Python scanner (pure_json)."""
        return subprocess.run([sys.executable, "-c", PURE_JSON_LANE, LANE, *args], cwd=self.main,
                              env=self.env, capture_output=True, text=True, timeout=60)

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


class AddrRepo(LiveSessions):
    """`lane addr --repo PATH`: the lane or lead of the lanes repo that holds PATH, from any cwd
    (a session in another repo, or in the home dir, reporting a bug to this repo's lead). The
    excluded-command guard judged the cwd's git config, never PATH's, so the one git run there
    takes lanelib.HANDED_ENV: no GIT_* from the caller, no system or global config, no
    transport, and git's own ownership check."""

    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix")
        self.other = os.path.join(self.home, "other")  # a second lanes repo, ~/other
        self.git("init", "-q", "-b", "main", self.other, cwd=self.tmp)
        self.commit("README.md", "other\n", cwd=self.other)
        self.lane("init", cwd=self.other)

    def addr(self, *args, cwd=None):
        return self.lane("addr", *args, cwd=cwd or self.home).strip()

    def refused(self, path, *needles, lane_id="lead", cwd=None):
        p = self.run_lane("addr", "--repo", path, lane_id, cwd=cwd or self.home)
        self.assertEqual((p.returncode, p.stdout), (1, ""), p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        for needle in needles:
            self.assertIn(needle, p.stderr)
        return p.stderr

    def test_another_repo_s_lead_from_any_cwd(self):
        mine = self.session(self.main)
        want = self.session(self.other)
        for cwd in (self.main, self.lane_path("chart-fix"), self.home):
            with self.subTest(cwd):
                self.assertEqual(self.addr("--repo", self.other, "lead", cwd=cwd), want)
        self.assertEqual(self.addr("lead", cwd=self.main), mine)  # no --repo: the cwd's repo

    def test_any_path_in_the_repo_names_it(self):
        want = self.session(self.other)
        sub = os.path.join(self.other, "src")
        os.makedirs(sub)
        self.assertEqual(self.addr("--repo", sub, "lead"), want)
        # A quoted ~ reaches the CLI unexpanded: it expands it against the caller's HOME.
        self.assertEqual(self.addr("--repo", "~/other", "lead"), want)
        mine = self.session(self.main)  # a lane's worktree names its repo too
        self.assertEqual(self.addr("--repo", self.lane_path("chart-fix"), "lead"), mine)

    def test_a_lane_of_another_repo(self):
        # The hint names where `lane open` must run: from the caller's cwd it would find the
        # cwd's repo, which may have a lane of that name too.
        self.refused(self.main, f"no live session in lane chart-fix of {self.main}: `lane open "
                     f"chart-fix` from {self.main} starts one", lane_id="chart-fix", cwd=self.other)
        want = self.session(self.lane_path("chart-fix"))
        self.assertEqual(self.addr("--repo", self.main, "chart-fix", cwd=self.other), want)

    def test_a_path_in_no_lanes_repo_refuses_with_the_reason(self):
        plain = os.path.join(self.home, "plain")
        self.git("init", "-q", plain, cwd=self.tmp)
        cases = {os.path.join(self.home, "nope"): "no such directory",
                 self.home: "git names no work tree there that it trusts",
                 plain: f"{plain} is no lanes repo"}
        for path, needle in cases.items():
            with self.subTest(path):
                err = self.refused(path, f"--repo {path}: ", needle)
                self.assertNotIn("run `lane init`", err)  # the caller can't, in another repo

    def test_an_empty_path_refuses_never_the_cwd_s_repo(self):
        # `--repo "$UNSET"` from inside a lanes repo with a live lead.
        self.session(self.main)
        self.refused("", "--repo: an empty path", cwd=self.main)

    def test_a_path_with_control_characters_is_shown_masked(self):
        err = self.refused(os.path.join(self.home, "a\x1b[2Jb"), "a?[2Jb: no such directory")
        self.assertNotIn("\x1b", err)

    def test_a_path_git_places_in_another_repo_refuses(self):
        # A planted .git file, or a commondir file in a .git dir, sends git to another repo's
        # git dir: a report would reach a lead the caller never named.
        self.session(self.other)
        planted = os.path.join(self.home, "planted")
        self.write(os.path.join(planted, ".git"), f"gitdir: {os.path.join(self.other, '.git')}\n")
        bent = os.path.join(self.home, "bent")
        self.git("init", "-q", bent, cwd=self.tmp)
        self.write(os.path.join(bent, ".git", "commondir"), os.path.join(self.other, ".git"))
        for path in (planted, bent):
            with self.subTest(path):
                self.refused(path, f"--repo {path}: git places it in the repo of {self.other}, "
                             "but it is in neither that main checkout nor one of its lanes")

    def test_a_git_dir_name_that_is_no_utf8_refuses_cleanly(self):
        # rev-parse prints the name raw; strict decoding would end in a traceback.
        odd = os.path.join(os.fsencode(self.home), b"x\xff")
        subprocess.run(["git", "init", "-q", odd], env=self.env, check=True, capture_output=True)
        planted = os.path.join(self.home, "planted")
        os.makedirs(planted)
        with open(os.path.join(planted, ".git"), "wb") as f:
            f.write(b"gitdir: " + os.path.join(odd, b".git") + b"\n")
        self.refused(planted, "git names no work tree there that it trusts")

    def test_no_live_lead_refuses_naming_the_repo(self):
        self.session(self.main)
        self.refused(self.other, f"no live session in the main checkout of {self.other} (the lead)")

    def test_several_sessions_and_none_picked_refuse(self):
        self.session(self.other)
        self.session(self.other)
        self.refused(self.other, f"2 live sessions in the main checkout of {self.other} (the lead)",
                     "No lead picked")

    def test_sandboxed_the_bare_hint_keeps_the_flag(self):
        self.session(self.other)
        self.env["_LANE_TEST_SANDBOXED"] = "1"
        self.refused("~/other", "sandboxed", f"bare `lane addr --repo {self.other} lead`")

    def test_an_inherited_git_dir_never_redirects_it(self):
        # git with GIT_DIR set ignores its cwd: the caller's repo would answer for PATH's.
        self.session(self.main)
        want = self.session(self.other)
        self.env["GIT_DIR"] = self.common
        self.assertEqual(self.addr("--repo", self.other, "lead"), want)

    def test_git_s_ownership_check_holds(self):
        # GIT_TEST_ASSUME_DIFFERENT_OWNER has git treat the repo as another user's. Patched into
        # HANDED_ENV, it reaches git only if handed_repo runs git with that env.
        lane_cli = load_lane_script()
        self.assertEqual(lane_cli.handed_repo(self.other).main, self.other)
        # Where safe.directory=* could wave it through: the Bash sandbox exports it as
        # GIT_CONFIG_*, a session rooted at $HOME could write the global config, and the system
        # config, which no test can write, is stood in for by a file GIT_CONFIG_SYSTEM names.
        foreign = {"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}
        system = os.path.join(self.tmp, "gitconfig")
        for f in (os.path.join(self.home, ".gitconfig"), system):
            self.write(f, "[safe]\n\tdirectory = *\n")
        trust_all = dict(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="safe.directory",
                         GIT_CONFIG_VALUE_0="*", **foreign)
        cases = (  # (why, os.environ, the env that shows it would, HANDED_ENV's stand-in)
            ("GIT_CONFIG_*", trust_all, None, {}),
            ("global config", {"HOME": self.home}, foreign, {}),
            ("system config", {}, dict(foreign, GIT_CONFIG_SYSTEM=system),
             {"GIT_CONFIG_SYSTEM": system}))
        for why, environ, env, stand_in in cases:
            with self.subTest(why):
                with mock.patch.dict(os.environ, environ):
                    self.assertIsNotNone(lanelib.resolve(self.other, env=env))
                with mock.patch.dict(lanelib.HANDED_ENV, foreign, **stand_in), \
                        mock.patch.dict(os.environ, environ), \
                        self.assertRaisesRegex(lane_cli.LaneError, "no work tree there that it"):
                    lane_cli.handed_repo(self.other)

    def test_a_config_include_that_blocks_times_out(self):
        # A FIFO include holds git at its open until a writer comes.
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        self.git("config", "include.path", fifo, cwd=self.other)
        lane_cli = load_lane_script()
        started = time.monotonic()
        with mock.patch.object(lane_cli, "HANDED_GIT_WAIT", 0.5), \
                self.assertRaisesRegex(lane_cli.LaneError, "no answer within 0.5 s"):
            lane_cli.handed_repo(self.other)
        self.assertLess(time.monotonic() - started, 5)


if __name__ == "__main__":
    unittest.main()
