"""skills/handoff/scripts/handoff-check: each check passing and failing, in a plain repo and in a
lane."""
import datetime
import json
import os
import subprocess
import sys
import time
import unittest

from _fixture import HANDOFF_CHECK, REPO, LanesRepo

import lanelib  # on sys.path through _fixture

GOOD = """# STATUS: chart work

## Direction
- Ship the chart fix.

## Notes for next session
- Run the chart tests, then open the PR for #42.
"""
TODAY = datetime.date.today()
FIRST = "- Run the chart tests, then open the PR for #42."


def marked(marker, text=GOOD):
    """text with marker on the Next block's first item."""
    return text.replace(FIRST, f"{FIRST[:-1]} {marker}.")


class Check(LanesRepo):
    def check(self, cwd=None, **env):
        p = subprocess.run([sys.executable, HANDOFF_CHECK], cwd=cwd or self.main,
                           env=dict(self.env, **env), capture_output=True, text=True, timeout=60)
        self.assertIn(p.returncode, (0, 1), p.stderr)
        return p.returncode, p.stdout

    def session(self, cwd, started, sid="sess-0001", pid=1):
        self.write(os.path.join(self.home, ".claude", "sessions", f"{pid}.json"),
                   json.dumps({"sessionId": sid, "cwd": cwd, "startedAt": int(started * 1000),
                               "pid": pid}))

    def assertGap(self, result, words):
        code, out = result
        self.assertEqual(code, 1, out)
        self.assertIn(words, out)

    def assertPasses(self, result):
        code, out = result
        self.assertEqual(code, 0, out)
        self.assertIn("handoff complete", out)


class Templates(unittest.TestCase):
    def test_the_seeded_templates_pass_the_lint(self):
        # Both seed status files the guard and handoff-check lint, so a relative phrase in a
        # template would fail every handoff made from it.
        for name in ("STATUS.md", "LANE.md"):
            with open(os.path.join(REPO, "templates", name)) as f:
                self.assertEqual(lanelib.relative_phrases(f.read()), [], name)


    def test_the_handoff_skill_calls_the_script_by_its_skill_path(self):
        # The skill dir is linked live; the ~/.local/bin link waits for the next setup.sh.
        with open(os.path.join(REPO, "skills", "handoff", "SKILL.md")) as f:
            self.assertIn("~/.claude/skills/handoff/scripts/handoff-check", f.read())
        self.assertTrue(os.access(HANDOFF_CHECK, os.X_OK))


class PlainRepo(Check):
    init_lanes = False

    def setUp(self):
        super().setUp()
        self.session(self.main, time.time() - 60)
        self.status = os.path.join(self.main, "STATUS.md")
        self.commit("STATUS.md", GOOD, msg="Handoff")

    def test_a_complete_handoff_passes(self):
        self.assertPasses(self.check())

    def test_leftovers_must_be_named(self):
        self.write(os.path.join(self.main, "scratch.txt"), "x")
        self.assertGap(self.check(), "scratch.txt")
        self.commit("STATUS.md", GOOD + "- scratch.txt is a deliberate local probe, uncommitted.\n")
        self.assertPasses(self.check())

    def test_the_status_file_must_postdate_head(self):
        self.commit("code.py", "x = 1\n")
        past = time.time() - 3600
        os.utime(self.status, (past, past))
        self.session(self.main, past - 60)
        self.assertGap(self.check(), "older than HEAD")

    def test_the_status_file_must_be_written_in_this_session(self):
        self.session(self.main, time.time() + 120)
        self.assertGap(self.check(), "not written during this session")

    def test_the_session_id_env_picks_the_session(self):
        self.session(self.tmp, time.time() + 120, sid="other-sess", pid=2)
        self.assertPasses(self.check())  # the other session's cwd is elsewhere
        self.assertGap(self.check(CLAUDE_CODE_SESSION_ID="other-sess"), "during this session")

    def test_no_session_found_warns_and_skips(self):
        os.remove(os.path.join(self.home, ".claude", "sessions", "1.json"))
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("warn  session start unknown", out)

    def test_next_must_be_non_empty(self):
        self.commit("STATUS.md", GOOD.split("## Notes")[0] +
                    "## Notes for next session\n<!-- the next step -->\n- <step>\n")
        self.assertGap(self.check(), "## Next")

    def test_relative_identity_only_warns_in_a_plain_repo(self):
        # Old text in a repo with no lanes ("this session's ..." in a long-lived STATUS.md) must
        # not fail every handoff there; with no peers, nobody misreads it.
        self.commit("STATUS.md", GOOD + "- Another session is building #43.\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("warn  relative identity: another session", out)

    def test_agent_worktrees_are_never_leftovers(self):
        agent = os.path.join(self.main, ".claude", "worktrees", "agent-1234")
        self.write(os.path.join(agent, "notes.txt"), "x")
        subprocess.run(["git", "init", "-q", agent], check=True, env=self.env)
        self.write(os.path.join(self.main, ".claude", "worktrees", "loose.txt"), "x")
        self.assertPasses(self.check())

    def test_sandbox_stubs_are_never_leftovers(self):
        # The Bash sandbox mounts /dev/null over protected paths a repo lacks (.claude/hooks in
        # dotclaude); git lists the stub as untracked. A link to /dev/null stands in for the
        # mount, which a test can't make.
        os.makedirs(os.path.join(self.main, ".claude"))
        os.symlink(os.devnull, os.path.join(self.main, ".claude", "hooks"))
        self.assertPasses(self.check())

    def test_a_leftover_needs_its_repo_relative_path(self):
        self.write(os.path.join(self.main, "src", "scratch.txt"), "x")
        self.commit("STATUS.md", GOOD + "- scratch.txt is a deliberate local probe.\n")
        self.assertGap(self.check(), "src/scratch.txt")
        self.commit("STATUS.md", GOOD + "- src/scratch.txt is a deliberate local probe.\n")
        self.assertPasses(self.check())

    def test_any_heading_starting_with_next_counts(self):
        body = GOOD.split("## Notes")[0]
        for heading in ("## Next session: start here", "## NEXT", "## Next steps"):
            with self.subTest(heading=heading):
                self.commit("STATUS.md", body + heading + "\n- Run the chart tests.\n")
                self.assertPasses(self.check())

    def test_no_status_file_fails(self):
        self.git("rm", "-q", "STATUS.md")
        self.git("commit", "-q", "-m", "drop")
        self.assertGap(self.check(), "no status file")

    def test_a_dated_approval_marker_passes(self):
        self.commit("STATUS.md", marked(f"(approved by Hayden {TODAY})"))
        self.assertPasses(self.check())

    def test_an_approval_marker_from_before_the_session_fails(self):
        old = TODAY - datetime.timedelta(days=1)
        self.commit("STATUS.md", marked(f"(approved by Hayden {old})"))
        self.assertGap(self.check(), "approval marker predates this session: remove it or get a "
                       "fresh approval")

    def test_an_old_marker_on_a_later_item_is_ignored(self):
        old = TODAY - datetime.timedelta(days=3)
        self.commit("STATUS.md", GOOD + f"- Then merge it (approved by Hayden {old}).\n")
        self.assertPasses(self.check())

    def test_an_approval_marker_without_a_valid_date_fails(self):
        for marker in ("(approved by Hayden)", "(approved by Hayden 2026-13-40)",
                       "(approved by Hayden yesterday)", "(approved by Hayden 2026-10-12"):
            self.commit("STATUS.md", GOOD + f"- Then merge it {marker}.\n")
            self.assertGap(self.check(), "approval marker")

    def test_an_approval_marker_outside_next_is_not_checked(self):
        self.commit("STATUS.md", GOOD.replace("## Direction\n", "## Direction\n"
                                              "- Old step (approved by Hayden).\n"))
        self.assertPasses(self.check())


class Approval(unittest.TestCase):
    """lanelib.approval over the Next block: approved, malformed or none (the resume mode)."""

    def state(self, text):
        return lanelib.approval(lanelib.next_block(text))

    def test_a_dated_marker_on_the_first_item_is_approved(self):
        self.assertEqual(self.state(marked("(approved by Hayden 2026-10-12)")), lanelib.APPROVED)
        self.assertEqual(self.state(marked("(Approved by Hayden 2026-02-28)", GOOD.replace(
            "Notes for next session", "Next step"))), lanelib.APPROVED)

    def test_a_marker_on_a_later_item_does_not_approve(self):
        self.assertEqual(self.state(GOOD + "- Merge (approved by Hayden 2026-10-12).\n"),
                         lanelib.UNAPPROVED)
        nested = GOOD + "  - Then merge (approved by Hayden 2026-10-12).\n"
        self.assertEqual(self.state(nested), lanelib.UNAPPROVED)

    def test_the_first_items_wrapped_lines_count(self):
        wrapped = GOOD.replace(FIRST, FIRST + "\n  Merge after (approved by Hayden 2026-10-12).")
        self.assertEqual(self.state(wrapped + "- Later step.\n"), lanelib.APPROVED)
        plain = GOOD.replace(FIRST, "Run the chart tests,\nthen merge (approved by Hayden "
                             "2026-10-12).\n- Later step.")
        self.assertEqual(self.state(plain), lanelib.APPROVED)
        self.assertEqual(lanelib.first_item("Do this\n- then that"), "Do this")

    def test_a_marker_dated_before_since_is_stale(self):
        text = marked("(approved by Hayden 2026-10-11)")
        block = lanelib.next_block(text)
        self.assertEqual(lanelib.approval(block, datetime.date(2026, 10, 12)), lanelib.STALE)
        self.assertEqual(lanelib.approval(block, datetime.date(2026, 10, 11)), lanelib.APPROVED)
        self.assertEqual(lanelib.approval(block, None), lanelib.APPROVED)
        later = GOOD + "- Merge (approved by Hayden 2020-01-01).\n"
        self.assertEqual(lanelib.approval(lanelib.next_block(later), datetime.date(2026, 10, 12)),
                         lanelib.UNAPPROVED)

    def test_no_marker_is_unapproved(self):
        self.assertEqual(self.state(GOOD), lanelib.UNAPPROVED)
        self.assertEqual(self.state("# x\n"), lanelib.UNAPPROVED)
        self.assertEqual(lanelib.approval(None), lanelib.UNAPPROVED)
        # Only the Next block counts, and an HTML comment there is not text.
        self.assertEqual(self.state(GOOD.replace("## Direction\n", "## Direction\n- (approved "
                                                 "by Hayden 2026-10-12)\n")), lanelib.UNAPPROVED)
        self.assertEqual(self.state(GOOD + "<!-- (approved by Hayden 2026-10-12) -->\n"),
                         lanelib.UNAPPROVED)

    def test_a_marker_with_a_missing_or_invalid_date_is_malformed(self):
        for marker in ("(approved by Hayden)", "(approved by Hayden 2026-02-30)",
                       "(approved by Hayden on 2026-10-12)", "(approved by Hayden 2026-10-12",
                       "(approved by Hayden 26-10-12)"):
            self.assertEqual(self.state(GOOD + f"- Merge {marker}\n"), lanelib.MALFORMED, marker)

    def test_one_malformed_marker_beside_a_good_one_is_malformed(self):
        self.assertEqual(self.state(marked("(approved by Hayden 2026-10-12)") +
                                    "- B (approved by Hayden)\n"), lanelib.MALFORMED)

    def test_the_status_path_follows_the_lane_from_the_toplevel(self):
        # In a lane the toplevel is the lane; lane.json's path (sandbox-writable) is never read.
        repo = lanelib.Repo("/r/lanes/x", "/r/proj/.git")
        self.assertEqual(lanelib.status_path(repo, None), "/r/lanes/x/STATUS.md")
        self.assertEqual(lanelib.status_path(repo, {"path": "/r/lanes/$(evil)\nx"}),
                         "/r/lanes/x/.lane/STATUS.md")


class Lane(Check):
    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix", "--claim", "42")
        self.path = self.lane_path("chart-fix")
        self.hook("lane-identity.sh", {"session_id": "sess-0001", "cwd": self.path,
                                       "source": "startup", "hook_event_name": "SessionStart"})
        self.body = self.read(self.record("chart-fix")).replace(
            "## Next\n", "## Next\n- Write the axis test for #42, then run it.\n")

    def finish(self, extra=""):
        time.sleep(1.05)  # past the session start's one-second resolution
        self.write(self.record("chart-fix"), self.body + extra)

    def test_a_complete_lane_handoff_passes(self):
        self.finish()
        self.assertPasses(self.check(cwd=self.path))

    def test_the_main_status_is_not_the_lane_record(self):
        self.finish()
        # From main, the root STATUS.md is the file, and there is none.
        self.assertGap(self.check(), "no status file")

    def test_relative_identity_fails_in_a_lanes_repo(self):
        self.finish("\nThe other lane owns #43.\n")
        self.assertGap(self.check(cwd=self.path), "relative identity: the other lane")

    def test_comments_and_code_are_not_linted(self):
        self.finish("\n<!-- never write 'another session' -->\nThe guard denies `this session`.\n"
                    "```\nmy lane: example only\n```\n")
        self.assertPasses(self.check(cwd=self.path))

    def test_claims_must_be_named(self):
        self.body = self.body.replace("#42", "the request")
        self.finish()
        self.assertGap(self.check(cwd=self.path), "claims not named in the record: #42")

    def test_unpushed_commits_warn_until_noted(self):
        self.commit("chart.txt", "axis\n", cwd=self.path)
        self.finish()
        code, out = self.check(cwd=self.path)
        self.assertEqual(code, 0, out)
        self.assertIn("1 unpushed commit", out)
        self.finish("\nBranch is unpushed: push waits for Hayden.\n")
        self.assertNotIn("unpushed commit", self.check(cwd=self.path)[1])

    def test_a_commit_after_the_record_fails(self):
        self.finish()
        past = time.time() - 3600
        os.utime(self.record("chart-fix"), (past, past))
        self.commit("chart.txt", "axis\n", cwd=self.path)
        self.assertGap(self.check(cwd=self.path), "older than HEAD")

    def test_a_record_from_before_the_session_fails(self):
        past = time.time() - 3600
        self.write(self.record("chart-fix"), self.body)
        os.utime(self.record("chart-fix"), (past, past))
        self.assertGap(self.check(cwd=self.path), "during this session")


if __name__ == "__main__":
    unittest.main()
