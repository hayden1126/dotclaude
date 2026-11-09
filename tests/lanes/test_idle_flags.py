"""The board's idle flags and `lane asks`'s chat waits (lane stop-check, 2026-11-09).

stalled: a lane whose live sessions are all idle, whose record's Next holds an item and whose
Asks for Hayden is empty, while its last reply names no wait and it isn't waiting its merge turn.
unanswered: an idle session whose transcript ends on a prompt (typed, a peer's, a notice) older
than a grace period, with no reply after it. `lane asks` also prints the Waiting on you list of
each lane's newest session's last reply, from the stop record stop-ring writes at each Stop.

Live sessions are this test's own pid and its parent's, as tests/lanes/test_lead.py's Ctx does.
"""
import json
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fixture import LanesRepo, lanelib  # noqa: E402

LANE = "chart-fix"


class Idle(LanesRepo):
    def setUp(self):
        super().setUp()
        self.lane("new", LANE)
        self.path = self.lane_path(LANE)
        # `lane new` seeds an excluded-guard ask here (the test origin is a local path)
        self.section("Asks for Hayden", "<!-- none -->")

    # ---- fixtures ----
    def session(self, pid, sid, status="idle"):
        self.write(os.path.join(self.home, ".claude", "sessions", f"{pid}.json"),
                   json.dumps({"pid": pid, "sessionId": sid, "cwd": self.path,
                               "procStart": str(lanelib.proc_start(pid)),
                               "tmux": "proj:@3.%7", "status": status}))

    def section(self, name, body):
        """Replace the record section `## <name>` with body (comments and all)."""
        path = self.record(LANE)
        with open(path) as f:
            text = f.read()
        new, n = re.subn(rf"(?ms)^(## {re.escape(name)}[^\n]*\n).*?(?=^## |\Z)",
                         lambda m: m.group(1) + body + "\n\n", text)
        self.assertEqual(n, 1, name)
        with open(path, "w") as f:
            f.write(new)

    def stop_record(self, sid, reply, transcript=None, age=30):
        """stop-ring's record, which names the session's transcript."""
        at = time.time() - age  # wall clock
        rec = {"session_id": sid, "time": at, "waits": [], "tasks": [],
               "replies": [{"prompt_id": "p1", "text": reply, "time": at}]}
        if transcript:
            rec["transcript_path"] = transcript
        self.write(os.path.join(self.env["XDG_STATE_HOME"], "dotclaude", "stops", sid + ".json"),
                   json.dumps(rec))

    def verdict(self, sid, why="block", waits=(), age=30):
        """The stop-check hook's record of the session's last Stop (hooks/stop_check.py)."""
        self.write(os.path.join(self.env["XDG_STATE_HOME"], "dotclaude", "stop-check",
                                sid + ".json"),
                   json.dumps({"prompt_id": "p1", "time": time.time() - age,  # wall clock
                               "why": why, "waits": list(waits), "blocked": None}))

    def transcript(self, sid, *rows):
        d = os.path.join(self.home, ".claude", "projects", "-proj-lanes-" + LANE)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, sid + ".jsonl")
        with open(path, "w") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        return path

    def registered(self, *sessions, proof=True):
        """lane.json's sessions[], as lane-identity writes them at SessionStart, and (proof)
        each one's transcript, whose first cwd places it in the lane (lanelib.lane_sid)."""
        for entry in sessions if proof else ():
            self.transcript(entry["session_id"], dict(reply(), cwd=self.path))
        rec = self.lane_json(LANE)
        rec["sessions"] = list(sessions)
        self.write(os.path.join(self.common, "lanes", LANE, "lane.json"), json.dumps(rec))

    def row(self):
        rows = {r["id"]: r for r in json.loads(self.lane("ls", "--json"))}
        return rows[LANE]

    def flags(self):
        head, *lines = self.lane("ls").splitlines()
        line = next(line for line in lines if line.split()[0] == LANE)
        return set(self.row()["flags"]), line


def prompt(text="go on", kind="human", age=600):
    when = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - age))  # wall clock
    return {"type": "user", "promptId": "p9", "origin": {"kind": kind}, "timestamp": when,
            "message": {"role": "user", "content": text}}


def reply(text="Done.", age=590):
    when = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() - age))  # wall clock
    return {"type": "assistant", "timestamp": when,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


class Stalled(Idle):
    def setUp(self):
        super().setUp()
        self.section("Next", "- Step 2: build the axis labels, tests first.")
        self.session(os.getpid(), "s-1")
        self.verdict("s-1")
        self.env["FAKE_GH_OUT"] = "[]"  # gh answers: no PR

    def test_an_idle_lane_with_work_in_next_and_no_asks_is_stalled(self):
        flags, cell = self.flags()
        self.assertIn("stalled", flags)
        self.assertIn("stalled", cell)
        self.assertEqual(self.row()["stalled_why"], "- Step 2: build the axis labels, tests first.")

    def test_a_busy_session_is_not_stalled(self):
        self.session(os.getppid(), "s-2", "busy")
        self.assertNotIn("stalled", self.flags()[0])

    def test_no_live_session_is_orphan_not_stalled(self):
        os.unlink(os.path.join(self.home, ".claude", "sessions", f"{os.getpid()}.json"))
        flags = self.flags()[0]
        self.assertNotIn("stalled", flags)
        self.assertIn("orphan", flags)

    def test_an_empty_or_keep_open_only_next_is_not_stalled(self):
        for body in ("<!-- nothing yet -->", "- Keep open: two more PRs follow."):
            with self.subTest(body=body):
                self.section("Next", body)
                self.assertNotIn("stalled", self.flags()[0])

    def test_an_open_ask_is_not_stalled(self):
        self.section("Asks for Hayden", "<!-- -->\n- pick the chip row or the dropdown")
        self.assertNotIn("stalled", self.flags()[0])

    def test_a_stop_the_hook_let_through_is_not_stalled(self):
        # the hook's own verdict: a wait line, a message to the lead, a running agent, a
        # pass, Hayden's own turn
        for why in ("waiting-list", "message", "background", "pass-pending", "hayden",
                    "no-turn"):
            with self.subTest(why=why):
                self.verdict("s-1", why)
                self.assertNotIn("stalled", self.flags()[0])
        self.verdict("s-1", "block")
        self.assertIn("stalled", self.flags()[0])

    def test_no_hook_record_or_no_gh_answer_is_not_stalled(self):
        os.unlink(os.path.join(self.env["XDG_STATE_HOME"], "dotclaude", "stop-check",
                               "s-1.json"))
        self.assertNotIn("stalled", self.flags()[0])
        self.verdict("s-1")
        del self.env["FAKE_GH_OUT"]  # gh fails: whether it waits its merge turn is unknown
        self.assertNotIn("stalled", self.flags()[0])

    def test_a_lane_waiting_its_merge_turn_is_not_stalled(self):
        branch = self.lane_json(LANE)["branch"]
        self.commit("axis.txt", "x\n", cwd=self.path)
        head = self.git("rev-parse", "HEAD", cwd=self.path).strip()
        self.env["FAKE_GH_OUT"] = json.dumps([{"number": 5, "state": "OPEN",
                                               "headRefName": branch, "mergedAt": None,
                                               "createdAt": "2026-11-01T00:00:00Z"}])
        self.assertIn("stalled", self.flags()[0])  # an open PR, but HEAD isn't pushed
        self.git("update-ref", f"refs/remotes/origin/{branch}", head)
        self.assertNotIn("stalled", self.flags()[0])

    def test_a_push_to_another_remote_counts_too(self):
        branch = self.lane_json(LANE)["branch"]
        head = self.git("rev-parse", "HEAD", cwd=self.path).strip()
        self.env["FAKE_GH_OUT"] = json.dumps([{"number": 5, "state": "OPEN",
                                               "headRefName": branch, "mergedAt": None,
                                               "createdAt": "2026-11-01T00:00:00Z"}])
        self.git("update-ref", f"refs/remotes/fork/{branch}", head)
        self.assertNotIn("stalled", self.flags()[0])


class Unanswered(Idle):
    def setUp(self):
        super().setUp()
        self.session(os.getpid(), "s-1")

    def test_a_prompt_with_no_reply_is_flagged(self):
        for kind in ("human", "peer", "task-notification"):
            with self.subTest(kind=kind):
                path = self.transcript("s-1", reply(age=900), prompt(kind=kind))
                self.stop_record("s-1", "Done.", transcript=path)
                self.assertIn("unanswered", self.flags()[0])

    def test_found_without_a_stop_record_too(self):
        # the session that never replied to its first prompt has never stopped
        self.transcript("s-1", prompt("You are lane `chart-fix`. Read your lane record ..."))
        self.assertIn("unanswered", self.flags()[0])

    def test_a_reply_a_compaction_or_a_fresh_prompt_is_not(self):
        cases = {
            "reply": (prompt(), reply()),
            "compaction": (reply(age=900), {"type": "system", "subtype": "compact_boundary"},
                           {"type": "user", "isCompactSummary": True, "timestamp":
                            prompt()["timestamp"], "message": {"role": "user",
                                                               "content": "This session is..."}}),
            "compaction with an origin": (
                reply(age=900), {"type": "system", "subtype": "compact_boundary"},
                dict(prompt("This session is being continued..."), isCompactSummary=True)),
            "fresh": (reply(age=900), prompt(age=20)),
            "tool result": (prompt(), {"type": "user", "timestamp": prompt()["timestamp"],
                                       "message": {"role": "user", "content": [
                                           {"type": "tool_result", "tool_use_id": "t",
                                            "content": "ok"}]}}),
        }
        for name, rows in cases.items():
            with self.subTest(name=name):
                self.stop_record("s-1", "Done.", transcript=self.transcript("s-1", *rows))
                self.assertNotIn("unanswered", self.flags()[0])

    def test_a_busy_session_is_not(self):
        self.session(os.getpid(), "s-1", "busy")
        self.stop_record("s-1", "Done.", transcript=self.transcript("s-1", reply(), prompt()))
        self.assertNotIn("unanswered", self.flags()[0])


class ChatAsks(Idle):
    LIST = ("approve the push", "pick A or B")

    def test_the_newest_live_sessions_waiting_list_is_listed(self):
        self.registered({"session_id": "s-old", "startedAt": "2026-11-08T01:00:00Z"},
                        {"session_id": "s-new", "startedAt": "2026-11-09T01:00:00Z"})
        self.verdict("s-old", "waiting-list", ["stale ask"], age=3600)
        self.verdict("s-new", "waiting-list", self.LIST)
        out = self.lane("asks")
        self.assertIn(f"{LANE}: - approve the push (chat, session s-new)", out)
        self.assertIn(f"{LANE}: - pick A or B (chat, session s-new)", out)
        self.assertNotIn("stale ask", out)
        self.assertNotIn("no open asks", out)

    def test_record_asks_come_first_and_both_show(self):
        self.section("Asks for Hayden", "- merge #5")
        self.registered({"session_id": "s-1", "startedAt": "2026-11-09T01:00:00Z"})
        self.verdict("s-1", "waiting-list", self.LIST)
        lines = self.lane("asks").strip().splitlines()
        self.assertEqual(lines[0], f"{LANE}: - merge #5")
        self.assertEqual(len(lines), 3)

    def test_an_ended_session_or_a_stop_with_no_list_shows_nothing(self):
        cases = (({"session_id": "s-1", "startedAt": "x", "endedAt": "y"}, self.LIST),
                 ({"session_id": "s-1", "startedAt": "x"}, ()))
        for entry, waits in cases:
            with self.subTest(ended="endedAt" in entry):
                self.registered(entry)
                self.verdict("s-1", "waiting-list", waits)
                self.assertIn("no open asks", self.lane("asks"))

    def test_a_session_claude_code_doesnt_place_in_the_lane_is_ignored(self):
        # sandboxed Bash can write lane.json's sessions[]: a forged entry proves nothing
        self.registered({"session_id": "s-1", "startedAt": "x"}, proof=False)
        self.verdict("s-1", "waiting-list", self.LIST)
        self.assertIn("no open asks", self.lane("asks"))

    def test_junk_in_the_record_shows_nothing_and_breaks_nothing(self):
        self.registered({"session_id": "s-1", "startedAt": "x"})
        self.verdict("s-1", "waiting-list", [3, None, "real ask\x1b[2J"])
        out = self.lane("asks")
        self.assertIn(f"{LANE}: - real ask?[2J (chat, session s-1)", out)


class Helpers(unittest.TestCase):
    def test_next_items_keeps_its_own_bullet_rule(self):
        # the wait-list parser's bullet pattern once replaced lanelib.BULLET, merging a bare
        # marker line into the step before it (pass's approval reads next_items too)
        self.assertEqual(lanelib.next_items("- step one\n- \n- step two"),
                         ["- step one", "- ", "- step two"])



if __name__ == "__main__":
    unittest.main()
