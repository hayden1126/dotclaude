"""skills/lanes/scripts/lane done: a lane session still working with Hayden is never cut off. done
refuses a session that is busy or waiting on him (read again just before the signals), and an idle
one whose transcript holds a turn newer than the lane record's last write, which --abandon alone
overrides. lanelib.last_turn reads that turn."""
import argparse
import datetime
import glob
import json
import os
import tempfile
import unittest
from unittest import mock

import test_cli  # by module: a class imported by name would have its tests collected here too

import lanelib  # on sys.path through _fixture

SID = test_cli.Fakes.SID


def stamp(t: float) -> str:
    """t as Claude Code writes a transcript timestamp: UTC, milliseconds, a Z."""
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def user(t, content="what next?", **extra):
    """A main-chain user record at t; extra adds or overrides fields."""
    return dict({"type": "user", "timestamp": stamp(t), "sessionId": SID,
                 "message": {"role": "user", "content": content}}, **extra)


def typed(t):
    return user(t, origin={"kind": "human"}, promptSource="typed")


def peer(t):
    return user(t, "Another Claude session sent a message: #9 merged", isMeta=True,
                origin={"kind": "peer"}, promptSource="system")


def notice(t):
    return user(t, "<task-notification>done</task-notification>",
                origin={"kind": "task-notification"}, promptSource="system")


def queued(t):
    return {"type": "attachment", "timestamp": stamp(t), "sessionId": SID,
            "attachment": {"type": "queued_command", "prompt": "one more thing",
                           "origin": {"kind": "human"}}}


def bang(t):
    return user(t, "<bash-input>git status</bash-input>")


def tool_result(t):
    return user(t, [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}])


def assistant(t, text="Sent."):
    return {"type": "assistant", "timestamp": stamp(t), "sessionId": SID,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def answer(t):
    """Hayden's answer to a question dialog: a tool result whose record holds the answers."""
    return dict(tool_result(t), toolUseResult={"answers": {"Pick?": "A"}, "questions": []})


def refused(t):
    """Hayden's refusal of a tool call."""
    return dict(tool_result(t), toolDenialKind="user-rejected")


WAITS = "Try the axis now.\n\n**Waiting on you:**\n- run the chart and say what you see"


def not_turns(t):
    """Records written after a write that are no turn: a tool's result (one with an image
    beside it too), a loaded skill's body, Stop-hook feedback, a compaction, an assistant reply,
    a subagent's prompt."""
    return [tool_result(t),
            user(t, [{"type": "tool_result", "tool_use_id": "toolu_2", "content": "shot"},
                     {"type": "image", "source": {"type": "base64", "data": "AA=="}}]),
            user(t, "Base directory for this skill: /x", isMeta=True),
            user(t, "Stop hook feedback: [autopass] Context is at 303k", isMeta=True),
            {"type": "system", "subtype": "compact_boundary", "timestamp": stamp(t)},
            user(t, "This session is being continued", isCompactSummary=True),
            user(t, "a subagent's brief", isSidechain=True, origin={"kind": "human"}),
            assistant(t)]


class LastTurn(unittest.TestCase):
    """lanelib.last_turn: the newest turn in a transcript, as (when, origin kind)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir))
        self.path = os.path.join(self.dir, f"{SID}.jsonl")
        self.t = 1_800_000_000.0

    def write(self, *recs, raw=b""):
        with open(self.path, "wb") as f:
            f.write(b"".join(json.dumps(r).encode() + b"\n" for r in recs) + raw)

    def test_each_kind_of_input_is_a_turn(self):
        for make, kind in ((typed, "human"), (peer, "peer"), (notice, "task-notification"),
                           (queued, "human"), (bang, None), (answer, "answer"),
                           (refused, "refusal")):
            with self.subTest(make.__name__):
                self.write(typed(self.t), make(self.t + 30))
                self.assertEqual(lanelib.last_turn(self.path), (self.t + 30, kind))

    def test_an_input_of_a_kind_not_seen_yet_counts(self):
        # Fails closed: auto-continuation (a usage limit's reset resuming work) turned up in one
        # of 4,231 local transcripts on 2026-11-16, unknown when the rule was written.
        self.write(typed(self.t), user(self.t + 30, origin={"kind": "auto-continuation"}),
                   {"type": "attachment", "timestamp": stamp(self.t + 40),
                    "attachment": {"type": "queued_command", "prompt": "x"}})
        self.assertEqual(lanelib.last_turn(self.path), (self.t + 40, None))
        self.write(typed(self.t), user(self.t + 30, origin={"kind": "auto-continuation"}))
        self.assertEqual(lanelib.last_turn(self.path), (self.t + 30, "auto-continuation"))

    def test_what_is_no_turn_is_skipped(self):
        self.write(typed(self.t), *not_turns(self.t + 30))
        self.assertEqual(lanelib.last_turn(self.path), (self.t, "human"))

    def test_the_newest_stamp_wins_over_file_order(self):
        # The wall clock steps, so a later line may carry an earlier stamp.
        self.write(typed(self.t + 5), peer(self.t + 4))
        self.assertEqual(lanelib.last_turn(self.path), (self.t + 5, "human"))

    def test_no_transcript_or_no_turn_is_none(self):
        self.assertIsNone(lanelib.last_turn(self.path))
        self.write(*not_turns(self.t))
        self.assertIsNone(lanelib.last_turn(self.path))

    def waits(self, *recs):
        self.write(*recs)
        return lanelib.read_transcript(self.path).waits

    def test_a_reply_waiting_on_hayden_after_the_last_turn(self):
        t = self.t
        self.write(typed(t), assistant(t + 5, WAITS), tool_result(t + 6))
        self.assertEqual(lanelib.read_transcript(self.path),
                         lanelib.Transcript((t, "human"), t + 5))
        for text in ("**Waiting on you:** approve the push", "- Waiting on Hayden: a pick"):
            with self.subTest(text):
                self.assertEqual(self.waits(typed(t), assistant(t + 5, text)), t + 5)
        # A wait on the lead is no wait on Hayden, nor is a word that only starts with "you".
        for text in ("Waiting on the lead: lane done", "waiting on youth sports", "All done."):
            with self.subTest(text):
                self.assertIsNone(self.waits(typed(t), assistant(t + 5, text)))

    def test_a_later_reply_in_the_same_turn_keeps_the_question_open(self):
        # Review round 2: a Stop hook blocks after the list, and the model's next line drops it.
        t = self.t
        self.assertEqual(self.waits(
            typed(t), assistant(t + 1, WAITS),
            user(t + 2, "Stop hook feedback: [autopass] Context is at 303k", isMeta=True),
            assistant(t + 3, "Noted, passing next turn.")), t + 1)

    def test_an_answered_question_waits_no_more(self):
        t = self.t
        self.assertIsNone(self.waits(assistant(t, WAITS), typed(t + 40), tool_result(t + 50)))

    def test_a_tool_call_or_a_subagents_reply_is_no_reply(self):
        t = self.t
        self.assertIsNone(self.waits(
            typed(t), {"type": "assistant", "timestamp": stamp(t + 7), "message": {"content": [
                {"type": "tool_use", "id": "t", "name": "Bash",
                 "input": {"command": "echo Waiting on you:"}}]}},
            dict(assistant(t + 8, WAITS), isSidechain=True)))

    def test_an_unreadable_turn_fails_closed(self):
        cases = {"no stamp": dict(typed(self.t), timestamp=None),
                 "bad stamp": dict(typed(self.t), timestamp="yesterday")}
        for name, rec in cases.items():
            with self.subTest(name):
                self.write(typed(self.t), rec)
                with self.assertRaisesRegex(lanelib.TurnUnread, "can't tell when"):
                    lanelib.last_turn(self.path)
        with self.subTest("garbled"):
            self.write(typed(self.t), raw=b'{"type":"user","timestamp":\n')
            with self.assertRaisesRegex(lanelib.TurnUnread, "won't parse"):
                lanelib.last_turn(self.path)
        with self.subTest("a reply with no stamp"):
            self.write(typed(self.t), dict(assistant(self.t), timestamp=None))
            with self.assertRaisesRegex(lanelib.TurnUnread, "is a reply, but its timestamp"):
                lanelib.read_transcript(self.path)
        with self.subTest("not a regular file"):
            os.remove(self.path)
            os.mkfifo(self.path)
            with self.assertRaises(lanelib.TurnUnread):
                lanelib.last_turn(self.path)


class DoneTurns(test_cli.Fakes):
    """lane done on a merged lane with one live session, its record last written at self.w."""

    def setUp(self):
        super().setUp()
        self.commit("chart.txt", "axis\n", cwd=self.path)
        self.git("push", "-q", "origin", "chart-fix:main", cwd=self.path)
        self.hand_off()
        self.w = os.path.getmtime(self.record("chart-fix"))  # the record's last write
        self.tpath = os.path.join(self.home, ".claude", "projects", "-proj", f"{SID}.jsonl")

    def transcript_of(self, *recs, path=None):
        """The session's transcript: its first record names the lane as cwd, as a real one's."""
        first = dict(typed(self.w - 600), cwd=self.path)
        self.write(path or self.tpath, "".join(json.dumps(r) + "\n" for r in (first, *recs)))

    def proof(self):
        return os.path.join(self.env["XDG_STATE_HOME"], "dotclaude", "lanes", "*.closing",
                            "chart-fix.json")

    def assertClosed(self, out):
        self.assertIn("closed (fully in origin/main)", out)
        self.assertFalse(os.path.exists(self.path))

    def assertRefusedUntouched(self, p, *pids):
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        for pid in pids:
            self.assertTrue(self.alive(pid), pid)
        self.assertEqual(self.signals(), [])
        self.assertNotIn("ended", p.stdout)
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")
        self.assertTrue(os.path.isdir(self.path))
        self.assertEqual(glob.glob(self.proof()), [])

    # ---- busy or waiting -------------------------------------------------------------------

    def test_a_busy_or_waiting_session_refuses_even_with_abandon(self):
        (claude,) = self.claude()
        for status, said in (("busy", "is busy (mid-turn), and closing would cut its turn off"),
                             ("waiting", "is waiting on Hayden")):
            for extra in ([], ["--abandon"]):
                with self.subTest(status=status, abandon=bool(extra)):
                    self.session_file(claude, status=status)
                    p = self.run_lane("done", "chart-fix", *extra)
                    self.assertIn(f"lane chart-fix's session {SID} {said}", p.stderr)
                    self.assertIn("rerun `lane done chart-fix`", p.stderr)
                    self.assertRefusedUntouched(p, claude)
        self.session_file(claude, status="idle")
        self.assertClosed(self.lane("done", "chart-fix"))

    def test_a_session_stopped_mid_turn_refuses_with_fg(self):
        # Ctrl+Z keeps its status busy until fg, so "wait until it is idle" would never come.
        (claude,) = self.claude()
        self.session_file(claude, status="busy")
        self.stop(claude)
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn(f"session {SID} is busy (mid-turn)", p.stderr)
        self.assertIn(f"it (pid {claude}, no tmux) is stopped (Ctrl+Z): fg it there, let it "
                      "finish", p.stderr)
        self.assertEqual(self.signals(), [])
        self.session_file(claude, status="waiting")
        p = self.run_lane("done", "chart-fix", "--abandon")
        self.assertIn("is waiting on Hayden", p.stderr)
        self.assertIn("fg it there, answer it, then rerun `lane done chart-fix`", p.stderr)
        self.assertEqual(self.signals(), [])

    def test_a_lane_with_no_live_session_closes_without_reading_its_record(self):
        # The lead's own session is live in the main checkout, so live_sessions is never empty;
        # a lane with nothing live in it has no turn to weigh, and an unreadable record
        # (an adopted worktree that never wrote one) closes as before.
        (lead,) = self.start(self.fake(self.main))
        self.session_file(lead, "sess-main-0001", cwd=self.main)
        os.remove(self.record("chart-fix"))
        self.assertClosed(self.lane("done", "chart-fix"))

    # ---- a turn newer than the record ------------------------------------------------------

    def test_a_turn_newer_than_the_record_refuses_until_the_record_is_written_again(self):
        (claude,) = self.claude()
        for make in (typed, queued, peer, notice, bang):
            with self.subTest(make.__name__):
                self.transcript_of(make(self.w + 60))
                p = self.run_lane("done", "chart-fix")
                self.assertIn(f"lane chart-fix's session {SID} took a turn", p.stderr)
                self.assertIn("after its record's last write", p.stderr)
                self.assertIn("Message the lane (`lane addr chart-fix`)", p.stderr)
                self.assertRefusedUntouched(p, claude)
        later = self.w + 120  # the lane writes its record again: newer than every turn
        os.utime(self.record("chart-fix"), (later, later))
        self.assertClosed(self.lane("done", "chart-fix"))

    def test_what_is_no_turn_never_refuses(self):
        self.claude()
        self.transcript_of(typed(self.w - 60), *not_turns(self.w + 60))
        self.assertClosed(self.lane("done", "chart-fix"))

    def test_the_post_merge_chain_closes(self):
        # The lead's "#9 merged" arrives, the lane hands off (its record written 5 s later),
        # then sends `merged #9` as its last act: a tool call, its result and a closing line.
        self.claude()
        t = self.w - 5
        self.transcript_of(peer(t),
                           {"type": "assistant", "timestamp": stamp(self.w + 1), "sessionId": SID,
                            "message": {"role": "assistant", "content": [
                                {"type": "tool_use", "id": "toolu_1", "name": "SendMessage",
                                 "input": {"message": "merged #9"}}]}},
                           tool_result(self.w + 2), assistant(self.w + 3, "Sent merged #9."))
        self.assertClosed(self.lane("done", "chart-fix"))

    def test_a_write_within_three_seconds_of_a_turn_reads_as_older(self):
        (claude,) = self.claude()
        self.transcript_of(typed(self.w - 1))
        p = self.run_lane("done", "chart-fix")
        self.assertIn("took a turn", p.stderr)
        self.assertIn("less than 3 s before, which reads as after, its record's last write",
                      p.stderr)
        self.assertRefusedUntouched(p, claude)
        self.transcript_of(typed(self.w - 4))
        self.assertClosed(self.lane("done", "chart-fix"))

    def test_a_last_reply_waiting_on_hayden_refuses_until_abandon(self):
        # The turn that wrote the record ended on a plain-text question: no input since, no
        # dialog open, and Hayden hasn't answered yet.
        (claude,) = self.claude()
        self.transcript_of(typed(self.w - 60), assistant(self.w + 30, WAITS))
        p = self.run_lane("done", "chart-fix")
        self.assertIn(f"session {SID} replied at", p.stderr)
        self.assertIn("with a Waiting on you line, and no input has come since", p.stderr)
        self.assertIn("Message the lane (`lane addr chart-fix`)", p.stderr)
        self.assertRefusedUntouched(p, claude)
        self.assertClosed(self.lane("done", "chart-fix", "--abandon"))

    def test_a_last_reply_waiting_on_the_lead_closes(self):
        self.claude()
        self.transcript_of(peer(self.w - 30), assistant(self.w + 3, "Sent.\n\nWaiting on the "
                                                                    "lead: lane done"))
        self.assertClosed(self.lane("done", "chart-fix"))

    def test_an_unmerged_lane_says_so_before_any_turn(self):
        # Review round 2: the early check ran before the merge check and hid the real reason.
        (claude,) = self.claude()
        self.commit("more.txt", "unmerged\n", cwd=self.path)
        os.utime(self.record("chart-fix"))
        self.w = os.path.getmtime(self.record("chart-fix"))
        self.transcript_of(typed(self.w + 60))
        p = self.run_lane("done", "chart-fix")
        self.assertIn("Pass --abandon to close it anyway", p.stderr)
        self.assertNotIn("took a turn", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_abandon_closes_past_a_newer_turn(self):
        self.claude()
        self.transcript_of(typed(self.w + 60))
        self.assertClosed(self.lane("done", "chart-fix", "--abandon"))

    def test_an_unreadable_transcript_refuses(self):
        (claude,) = self.claude()
        self.transcript_of(dict(typed(self.w + 60), timestamp="soon"))
        p = self.run_lane("done", "chart-fix")
        self.assertIn(f"session {SID}'s transcript", p.stderr)
        self.assertIn("can't tell when", p.stderr)
        # No message to the lane can clear it, so the refusal names Hayden's ask.
        self.assertIn("No message to the lane clears this: the lead asks Hayden", p.stderr)
        self.assertNotIn("Message the lane", p.stderr)
        self.assertRefusedUntouched(p, claude)

    def test_two_transcripts_for_one_session_refuse(self):
        (claude,) = self.claude()
        self.transcript_of(typed(self.w - 60))
        self.transcript_of(typed(self.w - 60), path=os.path.join(
            self.home, ".claude", "projects", "-other", f"{SID}.jsonl"))
        p = self.run_lane("done", "chart-fix")
        self.assertIn("2 transcripts", p.stderr)
        self.assertIn("the lead asks Hayden", p.stderr)
        self.assertRefusedUntouched(p, claude)

    # ---- read again just before the signals ------------------------------------------------

    def done_in_process(self, lane_mod, abandon=False):
        """cmd_done in this process, from the main checkout, with the fixture's environment."""
        cwd = os.getcwd()
        os.chdir(self.main)
        try:
            with mock.patch.dict(os.environ, self.env, clear=True):
                lane_mod.cmd_done(argparse.Namespace(id="chart-fix", abandon=abandon))
        finally:
            os.chdir(cwd)

    def during_gates(self, name, body):
        """A stand-in handoff-check that passes and runs body, as what happens while the gates
        run (it runs after the early checks, before the signals)."""
        fake = os.path.join(self.tmp, f"handoff-{name}.py")
        self.write(fake, "import json\n" + body)
        return fake

    def test_a_session_that_goes_busy_or_waiting_during_the_gates_refuses(self):
        lane_mod = test_cli.load_lane_script()
        (claude,) = self.claude()
        sess = os.path.join(self.home, ".claude", "sessions", f"{claude}.json")
        for status, said in (("busy", "is busy"), ("waiting", "is waiting")):
            with self.subTest(status):
                fake = self.during_gates(status, f"p = {sess!r}\nd = json.load(open(p))\n"
                                                 f"d['status'] = {status!r}\n"
                                                 "json.dump(d, open(p, 'w'))\n")
                with mock.patch.object(lane_mod, "HANDOFF_CHECK", fake):
                    with self.assertRaisesRegex(lane_mod.LaneError, said):
                        self.done_in_process(lane_mod)
                self.assertTrue(self.alive(claude))
                self.assertEqual(self.signals(), [])
                self.assertEqual(self.lane_json("chart-fix")["state"], "active")
                self.assertEqual(glob.glob(self.proof()), [])
                self.session_file(claude)  # idle again for the next case

    def test_a_turn_taken_during_the_gates_refuses(self):
        lane_mod = test_cli.load_lane_script()
        (claude,) = self.claude()
        self.transcript_of(typed(self.w - 60))
        line = json.dumps(typed(self.w + 60)) + "\n"
        fake = self.during_gates("turn", f"open({self.tpath!r}, 'a').write({line!r})\n")
        with mock.patch.object(lane_mod, "HANDOFF_CHECK", fake):
            with self.assertRaisesRegex(lane_mod.LaneError, "took a turn"):
                self.done_in_process(lane_mod)
        self.assertTrue(self.alive(claude))
        self.assertEqual(self.signals(), [])
        self.assertEqual(self.lane_json("chart-fix")["state"], "active")


if __name__ == "__main__":
    unittest.main()
