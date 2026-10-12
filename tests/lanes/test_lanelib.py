"""skills/lanes/scripts/lanelib.py: the shared lint and the sandbox detection, in-process."""
import os
import shutil
import tempfile
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


if __name__ == "__main__":
    unittest.main()
