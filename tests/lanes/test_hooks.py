"""hooks/lane-guard.sh and hooks/lane-identity.sh, run as Claude Code runs them: the event JSON on
stdin to the bash shim."""
import os
import shutil
import subprocess
import time
import unittest

from _fixture import HOOKS, LanesRepo

RELATIVE = "Next: another session is building #42.\n"
CLEAN = "Next: lane api-docs builds #42.\n"


class Guard(LanesRepo):
    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix")
        self.lane("new", "api-docs")
        self.own = self.record("chart-fix")
        self.other = self.record("api-docs")
        self.status = os.path.join(self.main, "STATUS.md")
        self.cli_data = os.path.join(self.common, "lanes", "chart-fix", "lane.json")

    def write_call(self, cwd, path, content, tool="Write", **inp):
        event = {"session_id": "4c9dfc5e-0000", "cwd": cwd, "hook_event_name": "PreToolUse",
                 "tool_name": tool, "tool_input": {"file_path": path, **inp}}
        if tool == "Write":
            event["tool_input"]["content"] = content
        return self.hook("lane-guard.sh", event)

    def assertDenied(self, out, word):
        self.assertIsNotNone(out, "expected a deny")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn(word, out["permissionDecisionReason"])

    def test_matrix(self):
        lane, main = self.lane_path("chart-fix"), self.main
        # (session cwd, target, text) -> denied by which rule, or None for allowed.
        cases = [
            (lane, self.own, CLEAN, None),
            (lane, self.own, RELATIVE, "relative identity"),
            (lane, self.other, CLEAN, "only that lane's own sessions"),
            (lane, self.other, RELATIVE, "only that lane's own sessions"),
            (lane, self.status, CLEAN, None),
            (lane, self.status, RELATIVE, "relative identity"),
            (lane, self.cli_data, CLEAN, "`lane` CLI"),
            (lane, self.cli_data, RELATIVE, "`lane` CLI"),
            (main, self.own, CLEAN, "only that lane's own sessions"),
            (main, self.status, CLEAN, None),
            (main, self.status, RELATIVE, "relative identity"),
            (main, self.cli_data, CLEAN, "`lane` CLI"),
            (main, os.path.join(main, "README.md"), RELATIVE, None),  # not a status file
        ]
        for cwd, path, text, rule in cases:
            with self.subTest(cwd=cwd, path=path, text=text):
                out = self.write_call(cwd, path, text)
                if rule is None:
                    self.assertIsNone(out)
                else:
                    self.assertDenied(out, rule)
        with open(os.path.join(self.tmp, "state", "dotclaude", "lane-guard.log")) as f:
            log = f.read()
        for kind in ("deny relative", "deny other-record", "deny cli-data"):
            self.assertIn(kind, log)

    def test_a_lane_root_status_is_linted_since_it_merges_into_main(self):
        lane = self.lane_path("chart-fix")
        root_status = os.path.join(lane, "STATUS.md")
        self.assertDenied(self.write_call(lane, root_status, RELATIVE), "relative identity")
        self.assertIsNone(self.write_call(lane, root_status, CLEAN))
        # Only the root one: a nested STATUS.md is ordinary content.
        self.assertIsNone(self.write_call(lane, os.path.join(lane, "docs", "STATUS.md"), RELATIVE))

    def test_the_deny_names_the_fix_and_the_phrase(self):
        out = self.write_call(self.lane_path("chart-fix"), self.own, "The other lane owns it.")
        self.assertDenied(out, "the other lane")
        self.assertIn("lane id", out["permissionDecisionReason"])

    def test_each_phrase_is_caught_and_lookalikes_are_not(self):
        lane = self.lane_path("chart-fix")
        for text in ("another session", "Another Claude session", "other session",
                     "this session", "the other lane", "the other session", "my lane",
                     "my session", "another\nsession"):
            with self.subTest(text=text):
                self.assertIsNotNone(self.write_call(lane, self.own, text))
        for text in ("session 4c9dfc5e ended", "other lanes' records", "my lanes list",
                     "sessions overlap", "lane api-docs", "this sessionId"):
            with self.subTest(text=text):
                self.assertIsNone(self.write_call(lane, self.own, text))

    def test_an_edit_is_judged_by_what_it_adds(self):
        lane = self.lane_path("chart-fix")
        keep = {"old_string": "another session said so", "new_string": "another session said so!"}
        self.assertIsNone(self.write_call(lane, self.own, None, tool="Edit", **keep))
        add = {"old_string": "x", "new_string": "this session owns it"}
        self.assertIsNotNone(self.write_call(lane, self.own, None, tool="Edit", **add))
        multi = {"edits": [{"old_string": "a", "new_string": "b"},
                           {"old_string": "c", "new_string": "my lane has #42"}]}
        self.assertIsNotNone(self.write_call(lane, self.own, None, tool="MultiEdit", **multi))

    def test_quoted_examples_pass_as_in_handoff_check(self):
        # One lint for both: comments and code quote a phrase, they don't claim anything.
        lane = self.lane_path("chart-fix")
        for text in ("Never write `another session`.", "<!-- not 'this session' -->",
                     "```\nmy lane\n```\n"):
            with self.subTest(text=text):
                self.assertIsNone(self.write_call(lane, self.own, text))
        add = {"old_string": "x", "new_string": "the guard denies `this session`"}
        self.assertIsNone(self.write_call(lane, self.own, None, tool="Edit", **add))
        add = {"old_string": "`this session`", "new_string": "this session"}
        self.assertIsNotNone(self.write_call(lane, self.own, None, tool="Edit", **add))

    def test_a_relative_path_resolves_against_the_session_cwd(self):
        lane = self.lane_path("chart-fix")
        self.assertIsNotNone(self.write_call(lane, ".lane/STATUS.md", RELATIVE))
        self.assertIsNone(self.write_call(lane, ".lane/STATUS.md", CLEAN))

    def test_garbage_fails_open(self):
        for script in ("lane-guard.sh", "lane-identity.sh"):
            for payload in ("not json", "[]", '{"tool_name": "Write"}'):
                with self.subTest(script=script, payload=payload):
                    p = subprocess.run(["bash", os.path.join(HOOKS, script)], input=payload,
                                       capture_output=True, text=True, env=self.env)
                    self.assertEqual((p.returncode, p.stdout), (0, ""))


class GuardPlain(LanesRepo):
    init_lanes = False

    def test_a_repo_without_lanes_is_untouched(self):
        out = self.hook("lane-guard.sh", {
            "session_id": "s", "cwd": self.main, "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(self.main, "STATUS.md"), "content": RELATIVE}})
        self.assertIsNone(out)


class IdentityHook(LanesRepo):
    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix", "--claim", "42")
        self.lane_dir = self.lane_path("chart-fix")

    def start(self, cwd, source="startup", sid="sess-0001", **extra):
        return self.hook("lane-identity.sh", {"session_id": sid, "cwd": cwd, "source": source,
                                              "hook_event_name": "SessionStart", **extra})

    def test_a_lane_session_learns_its_identity_and_is_registered(self):
        out = self.start(os.path.join(self.lane_dir))
        ctx = out["additionalContext"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        for piece in ("`chart-fix`", "branch `chart-fix`", "#42", "port 5191",
                      self.record("chart-fix"), "read-only", "`lane who", "another session"):
            self.assertIn(piece, ctx)
        self.assertNotIn("re-read", ctx)
        (s,) = self.lane_json("chart-fix")["sessions"]
        self.assertEqual((s["session_id"], s["source"]), ("sess-0001", "startup"))
        self.assertIn("startedAt", s)

    def test_compact_says_reread_and_keeps_the_session_start(self):
        self.start(self.lane_dir)
        first = self.lane_json("chart-fix")["sessions"][0]["startedAt"]
        out = self.start(self.lane_dir, source="compact")
        self.assertIn("re-read your record", out["additionalContext"])
        sessions = self.lane_json("chart-fix")["sessions"]
        self.assertEqual([(s["session_id"], s["startedAt"]) for s in sessions],
                         [("sess-0001", first)])

    def test_main_gets_one_board_line(self):
        out = self.start(self.main)
        self.assertEqual(out["additionalContext"].count("\n"), 0)
        self.assertIn("chart-fix (#42)", out["additionalContext"])
        self.assertIn("`lane ls`", out["additionalContext"])

    def test_subagents_and_plain_repos_get_nothing(self):
        self.assertIsNone(self.start(self.lane_dir, agent_id="a1"))
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        subprocess.run(["git", "init", "-q", plain], check=True, env=self.env)
        self.assertIsNone(self.start(plain))
        self.assertIsNone(self.start(self.tmp))  # not a repo at all

    def stop(self):
        self.hook("lane-identity.sh", {"session_id": "sess-0001", "cwd": self.lane_dir,
                                       "hook_event_name": "Stop"})

    def mirror(self, *parts):
        return os.path.join(self.common, "lanes", "chart-fix", "mirror", *parts)

    def test_a_mirror_left_mid_swap_is_restored_not_deleted(self):
        # A kill between the two renames leaves only mirror.old: the only copy once the worktree
        # is gone. The next run must put it back.
        old = self.mirror() + ".old"
        self.write(os.path.join(old, "STATUS.md"), "the only copy\n")
        shutil.rmtree(os.path.join(self.lane_dir, ".lane"))
        self.stop()
        self.assertEqual(self.read(self.mirror("STATUS.md")), "the only copy\n")
        self.assertFalse(os.path.exists(old))

    def test_the_mirror_copies_what_symlinks_point_at(self):
        outside = os.path.join(self.tmp, "shot.png")
        self.write(outside, "png")
        os.makedirs(os.path.join(self.lane_dir, ".lane", "artifacts"))
        os.symlink(outside, os.path.join(self.lane_dir, ".lane", "artifacts", "shot.png"))
        self.stop()
        copied = self.mirror("artifacts", "shot.png")
        self.assertFalse(os.path.islink(copied))
        self.assertEqual(self.read(copied), "png")

    def test_dangling_links_and_loops_never_break_the_mirror_or_the_end_stamp(self):
        self.start(self.lane_dir)
        rec = os.path.join(self.lane_dir, ".lane")
        os.symlink(os.path.join(self.tmp, "missing.png"), os.path.join(rec, "gone.png"))
        os.symlink(rec, os.path.join(rec, "loop"))
        self.stop()
        self.assertTrue(os.path.isfile(self.mirror("STATUS.md")))
        self.assertTrue(os.path.islink(self.mirror("gone.png")))
        self.assertTrue(os.path.islink(self.mirror("loop")))
        self.assertTrue(os.path.isfile(self.mirror() + ".stamp"))
        self.hook("lane-identity.sh", {"session_id": "sess-0001", "cwd": self.lane_dir,
                                       "hook_event_name": "SessionEnd", "reason": "other"})
        self.assertIn("endedAt", self.lane_json("chart-fix")["sessions"][0])

    @unittest.skipIf(os.geteuid() == 0, "root reads a chmod 0 file")
    def test_a_failed_mirror_still_stamps_the_session_end(self):
        self.start(self.lane_dir)
        secret = os.path.join(self.lane_dir, ".lane", "unreadable.txt")
        self.write(secret, "x")
        os.chmod(secret, 0)
        self.addCleanup(os.chmod, secret, 0o644)
        self.hook("lane-identity.sh", {"session_id": "sess-0001", "cwd": self.lane_dir,
                                       "hook_event_name": "SessionEnd", "reason": "other"})
        self.assertIn("endedAt", self.lane_json("chart-fix")["sessions"][0])

    def test_an_unchanged_record_is_not_copied_again(self):
        self.stop()
        self.write(self.mirror("STATUS.md"), "marker\n")  # stands in for a copy the run skipped
        self.stop()
        self.assertEqual(self.read(self.mirror("STATUS.md")), "marker\n")
        time.sleep(0.01)
        self.write(self.record("chart-fix"), "# LANE: chart-fix\n## Next\n- ship\n")
        self.stop()
        self.assertEqual(self.read(self.mirror("STATUS.md")), "# LANE: chart-fix\n## Next\n- ship\n")
        os.remove(self.record("chart-fix"))  # a deletion counts as a change too
        self.stop()
        self.assertFalse(os.path.exists(self.mirror("STATUS.md")))

    def test_stop_mirrors_the_record_and_session_end_stamps_it(self):
        self.start(self.lane_dir)
        self.write(self.record("chart-fix"), "# LANE: chart-fix\n## Next\n- ship\n")
        self.write(os.path.join(self.lane_dir, ".lane", "artifacts", "a.png"), "png")
        self.hook("lane-identity.sh", {"session_id": "sess-0001", "cwd": self.lane_dir,
                                       "hook_event_name": "Stop"})
        mirror = os.path.join(self.common, "lanes", "chart-fix", "mirror")
        self.assertEqual(self.read(os.path.join(mirror, "STATUS.md")),
                         "# LANE: chart-fix\n## Next\n- ship\n")
        self.assertTrue(os.path.isfile(os.path.join(mirror, "artifacts", "a.png")))
        self.assertNotIn("endedAt", self.lane_json("chart-fix")["sessions"][0])
        self.write(self.record("chart-fix"), "# LANE: chart-fix\n## Next\n- review\n")
        self.hook("lane-identity.sh", {"session_id": "sess-0001", "cwd": self.lane_dir,
                                       "hook_event_name": "SessionEnd", "reason": "clear"})
        self.assertIn("- review", self.read(os.path.join(mirror, "STATUS.md")))
        s = self.lane_json("chart-fix")["sessions"][0]
        self.assertEqual(s["reason"], "clear")
        self.assertIn("endedAt", s)
        # A resume after the end is a new work block: a new entry.
        self.start(self.lane_dir, source="resume")
        self.assertEqual(len(self.lane_json("chart-fix")["sessions"]), 2)


if __name__ == "__main__":
    unittest.main()
