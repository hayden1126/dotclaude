"""skills/lanes/scripts/lanelib.py: the shared lint, the sandbox detection and session liveness,
in-process."""
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import _fixture  # noqa: F401  (puts lanelib on sys.path)
import lanelib


class ProseOnly(unittest.TestCase):
    def phrases(self, text):
        return lanelib.relative_phrases(lanelib.prose_only(text))

    def test_comments_inline_code_and_fences_are_dropped(self):
        text = ("<!-- another session -->\nsee `this session`\n```\nmy lane\n```\n"
                "~~~python\nthe other lane\n~~~\nprose: another session\n")
        self.assertEqual(self.phrases(text), ["another session"])

    def test_a_closer_needs_the_same_char_at_least_as_long_and_nothing_after(self):
        # Three backticks don't close a four-backtick fence, a closer with text after it is not
        # a closer, and a tilde line doesn't close a backtick fence.
        for inner in ("```\nmy lane\n", "```` not a closer\nmy lane\n", "~~~~\nmy lane\n"):
            with self.subTest(inner=inner):
                text = "````\n" + inner + "````\nafter: this session\n"
                self.assertEqual(self.phrases(text), ["this session"])
        self.assertEqual(self.phrases("```\nx\n`````  \nthis session\n"), ["this session"])

    def test_an_unclosed_fence_runs_to_the_end(self):
        self.assertEqual(self.phrases("this session\n```\nmy lane\n"), ["this session"])


class Sandbox(unittest.TestCase):
    def proc(self, argv0, comm="x"):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        os.makedirs(os.path.join(root, "1"))
        with open(os.path.join(root, "1", "cmdline"), "wb") as f:
            f.write(argv0.encode() + b"\0-c\0rest\0")
        with open(os.path.join(root, "1", "comm"), "w") as f:
            f.write(comm + "\n")
        return root

    def test_pid_one_names_the_sandbox(self):
        self.assertTrue(lanelib.sandboxed(self.proc("apply-seccomp", comm="3")))
        self.assertTrue(lanelib.sandboxed(self.proc("/usr/bin/bwrap")))
        self.assertTrue(lanelib.sandboxed(self.proc("/sbin/init", comm="bwrap")))
        self.assertFalse(lanelib.sandboxed(self.proc("/sbin/init", comm="systemd")))

    def test_a_stale_claude_pid_no_longer_hides_pids(self):
        outside = self.proc("/sbin/init", comm="systemd")
        with mock.patch.dict(os.environ, {"CLAUDE_PID": "999999999"}):
            for var in ("SANDBOX_RUNTIME", "_LANE_TEST_SANDBOXED"):  # the suite may be sandboxed
                os.environ.pop(var, None)
            self.assertTrue(lanelib.pids_visible(outside))

    def test_sandbox_runtime_says_sandboxed(self):
        # Set only inside the sandbox; delegation_common.pids_visible reads it the same way.
        with mock.patch.dict(os.environ, {"SANDBOX_RUNTIME": "1"}):
            os.environ.pop("_LANE_TEST_SANDBOXED", None)
            self.assertFalse(lanelib.pids_visible(self.proc("/sbin/init", comm="systemd")))

    def test_there_is_no_public_override(self):
        with mock.patch.dict(os.environ, {"LANE_SANDBOXED": "0"}):
            os.environ.pop("_LANE_TEST_SANDBOXED", None)
            self.assertFalse(lanelib.pids_visible(self.proc("apply-seccomp")))


class SessionState(unittest.TestCase):
    """A session file's process by its pid and procStart: present while it exists (stopped or
    not), running only while it isn't stopped (Ctrl+Z), gone once exited or its pid reused."""

    def child(self):
        """A running `sleep` and its session file's fields, killed at cleanup (SIGKILL ends a
        stopped process too)."""
        p = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p.pid, {"pid": p.pid, "procStart": str(lanelib.proc_start(p.pid))}

    def wait_state(self, pid, stopped):
        deadline = time.monotonic() + 10
        while ((lanelib.proc_stat(pid) or ("", ""))[1] in lanelib.STOPPED) != stopped:
            if time.monotonic() > deadline:
                self.fail(f"{pid} never {'stopped' if stopped else 'continued'}")
            time.sleep(0.01)

    def facts(self, session):
        return lanelib.session_running(session), lanelib.session_stopped(session)

    def test_a_stopped_session_is_present_but_not_running_until_continued(self):
        pid, s = self.child()
        self.assertNotIn(lanelib.session_state(s), (None, *lanelib.STOPPED))
        self.assertEqual(self.facts(s), (True, False))
        os.kill(pid, signal.SIGSTOP)
        self.wait_state(pid, True)
        self.assertIn(lanelib.session_state(s), lanelib.STOPPED)
        self.assertEqual(self.facts(s), (False, True))
        os.kill(pid, signal.SIGCONT)
        self.wait_state(pid, False)
        self.assertEqual(self.facts(s), (True, False))

    def test_a_reused_pid_an_exited_one_or_no_proc_start_is_gone(self):
        pid, s = self.child()
        os.kill(pid, signal.SIGSTOP)  # stopped or not, a pid that names another process is gone
        self.wait_state(pid, True)
        done = subprocess.Popen(["true"])
        done.wait()
        cases = {"pid reused": dict(s, procStart=str(int(s["procStart"]) + 1)),
                 "no procStart": {"pid": pid}, "procStart None": dict(s, procStart=None),
                 "exited": {"pid": done.pid, "procStart": "1"}, "pid a bool": dict(s, pid=True)}
        for why, gone in cases.items():
            with self.subTest(why):
                self.assertIsNone(lanelib.session_state(gone))
                self.assertEqual(self.facts(gone), (False, False))

    def test_live_sessions_hold_a_stopped_session_and_drop_a_reused_pid(self):
        cfg = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, cfg)
        os.makedirs(os.path.join(cfg, "sessions"))
        running, a = self.child()
        stopped, b = self.child()
        _, c = self.child()
        os.kill(stopped, signal.SIGSTOP)
        self.wait_state(stopped, True)
        for s in (a, b, dict(c, procStart=str(int(c["procStart"]) + 1))):
            with open(os.path.join(cfg, "sessions", f"{s['pid']}.json"), "w") as f:
                json.dump(s, f)
        with mock.patch.dict(os.environ, CLAUDE_CONFIG_DIR=cfg, _LANE_TEST_SANDBOXED="0"):
            self.assertEqual(sorted(s["pid"] for s in lanelib.live_sessions()),
                             sorted([running, stopped]))


class Walk(unittest.TestCase):
    def test_links_are_never_followed(self):
        root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        rec = os.path.join(root, "lane", ".lane")
        outside = os.path.join(root, "outside")
        os.makedirs(os.path.join(rec, "artifacts"))
        os.makedirs(outside)
        with open(os.path.join(outside, "key"), "w") as f:
            f.write("secret")
        os.symlink("../..", os.path.join(rec, "artifacts", "src"))
        os.symlink(outside, os.path.join(rec, "artifacts", "out"))
        os.symlink(os.path.join(outside, "key"), os.path.join(rec, "key"))
        walked = {rel: kind for _, rel, kind in lanelib.walk_record(rec)}
        self.assertEqual(walked, {"artifacts": "dir", "artifacts/out": "link",
                                  "artifacts/src": "link", "key": "link"})
        before = lanelib.newest_mtime(rec)
        os.utime(os.path.join(outside, "key"), (before + 100, before + 100))
        self.assertEqual(lanelib.newest_mtime(rec), before)  # a target's change is not ours


class Picks(unittest.TestCase):
    """The model and effort `lane init` and `lane open` accept, and what pass-respawn carries."""

    def test_a_model_is_an_alias_or_a_claude_full_name_with_a_1m_where_one_exists(self):
        for name in ("opus", "sonnet", "haiku", "fable", "opusplan", "default", "sonnet[1m]",
                     "fable[1m]", "claude-sonnet-5-5", "claude-haiku-4-5-20251001",
                     "claude-opus-5-5[1m]"):
            with self.subTest(name=name):
                self.assertIsNone(lanelib.model_problem(name))

    def test_a_typo_a_flag_or_shell_syntax_is_no_model(self):
        # default[1m] fails at its first request, and /model says haiku and opusplan have no 1M
        # form (probed 2026-10-15).
        for name in ("sonet", "Opus", "-x", "--dangerously-skip-permissions", "opus;x", "opus x",
                     "claude-", "claude-opus-", "claude-Opus-5", "opus[2m]", "default[1m]",
                     "haiku[1m]", "opusplan[1m]", "", None, 5):
            with self.subTest(name=name):
                self.assertIn("is not a model", lanelib.model_problem(name))

    def test_a_model_could_run_as_an_id_of_its_own_family_only(self):
        for name, ran in (("sonnet", "claude-sonnet-5-5"), ("sonnet[1m]", "claude-sonnet-5-5"),
                          ("opusplan", "claude-sonnet-5-5"), ("opusplan", "claude-opus-5-5"),
                          ("default", "claude-haiku-5-5"), ("claude-opus-5-5", "claude-opus-5-5"),
                          ("claude-opus-5-5[1m]", "claude-opus-5-5"),
                          ("claude-haiku-4-5", "claude-haiku-4-5-20251001"),  # a dated id
                          ("claude-sonnet-4-5[1m]", "claude-sonnet-4-5-20250929"),
                          ("claude-sonnet-4@20250514", "claude-opus-5-5")):  # can't be judged
            with self.subTest(name=name, ran=ran):
                self.assertTrue(lanelib.could_run(name, ran))
        for name, ran in (("sonnet", "claude-opus-5-5"), ("opusplan", "claude-haiku-5-5"),
                          ("claude-opus-5-5", "claude-opus-4-8"), ("haiku", "claude-sonnet-5-5"),
                          ("claude-opus-5", "claude-opus-5-5"),  # a prefix is no date
                          ("claude-opus-4.5", "claude-opus-4-5")):  # a '.' is no wildcard
            with self.subTest(name=name, ran=ran):
                self.assertFalse(lanelib.could_run(name, ran))

    def test_an_effort_is_one_of_the_five_levels(self):
        for level in lanelib.EFFORTS:
            self.assertIsNone(lanelib.effort_problem(level))
        for level in ("extreme", "High", "ultracode", "", None):
            with self.subTest(level=level):
                self.assertIn("low, medium, high, xhigh, max", lanelib.effort_problem(level))

    def test_a_carried_model_needs_only_a_safe_shape(self):
        # A value the old claude already launched with: no typo check, only nothing that reads
        # as a flag or carries shell or control characters.
        for name in ("opus", "us.anthropic.claude-sonnet-5-5-v1:0", "claude-opus-5-5[1m]",
                     "my/model", "claude-sonnet-4@20250514"):
            with self.subTest(name=name):
                self.assertTrue(lanelib.safe_model(name))
        for name in ("-x", "", "a b", "a;b", "a\nb", "x" * 101, None):
            with self.subTest(name=name):
                self.assertFalse(lanelib.safe_model(name))


if __name__ == "__main__":
    unittest.main()
