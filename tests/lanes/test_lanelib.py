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

UNREAD = {"junk": "{", "deep": "[" * 100000}  # RecursionError in json


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

    def test_a_backtick_in_the_info_string_makes_no_fence(self):
        # CommonMark: ```x``` is inline code, not a fence.
        self.assertEqual(lanelib.fenced(["```x```", "this session", "```"]), [False, False, True])

    def test_a_tab_indented_fence_under_a_list_item_quotes(self):
        # A fence there in CommonMark: linting its example would deny quoted text.
        self.assertEqual(self.phrases("- Run:\n\t```sh\n\techo this session\n\t```\n"), [])

    def test_an_unclosed_fence_runs_to_the_end(self):
        self.assertEqual(self.phrases("this session\n```\nmy lane\n"), ["this session"])


class UnclosedComment(unittest.TestCase):
    """lanelib.comment_flaw and the scan it shares with section(): a flaw the check misses is
    comment text the tools read as the record's."""

    def flaw(self, text):
        line, what = lanelib.comment_flaw(text)
        self.assertEqual(what, lanelib.UNCLOSED)
        return line

    def test_closed_comments_pass(self):
        for text in ("## Next\n<!-- one line -->\n- Step.\n",
                     "## Next\n<!-- a comment\nover lines, quoting `Keep open: <why>` -->\n",
                     "## State\n<!-- a --> x <!-- b -->\n## Next\n<!---->\n- Step.\n",
                     "", None):
            self.assertIsNone(lanelib.comment_flaw(text), text)

    def test_an_unclosed_opener_gives_its_line(self):
        self.assertEqual(self.flaw("# LANE: x\n\n## Next\n- Step.\n<!-- note\n"), 5)
        # A form feed is no line break to an editor, though splitlines() makes it one.
        self.assertEqual(self.flaw("## Next\n\x0c\n<!-- x\n"), 3)
        # The first unclosed one, after a closed one on the same line.
        self.assertEqual(self.flaw("## A\nok\n<!-- a --> <!-- b\n"), 3)

    def test_a_comment_closed_only_in_a_later_section_is_unclosed(self):
        # section() reads each section alone, so the opener's own section keeps it open.
        text = "## State\n<!-- note\n## Next\n- Step. -->\n"
        self.assertEqual(self.flaw(text), 2)

    def test_an_opener_in_code_is_quoted_not_opened(self):
        for text in ("## Backlog\n- An unclosed `<!--` hides `Keep open:`.\n",
                     "## Backlog\n```\n<!-- an example\n```\n",
                     "## Backlog\nquoted `-->`, and `<!--` too\n"):
            self.assertIsNone(lanelib.comment_flaw(text), text)
        # Inside a comment, backticks quote nothing: its first `-->` ends it.
        self.assertIsNone(lanelib.comment_flaw("## Next\n<!-- start with `Keep open: <why>` -->\n"))

    def test_short_comments_close_themselves(self):
        # `<!-->` and `<!--->` are whole comments (CommonMark 0.31, HTML): read as openers, they
        # ran to a later `-->` and hid the flag between.
        for opener in ("<!-->", "<!--->"):
            text = f"## Next\n- Use {opener} here\nKeep open: PR 2\n- and <!-- x -->\n"
            self.assertIsNone(lanelib.comment_flaw(text), opener)
            self.assertEqual(lanelib.kept_open(lanelib.next_block(text)), "Keep open: PR 2")

    def test_a_comment_starting_its_line_leaves_the_flag_at_the_start(self):
        # The blank after `-->` once indented the flag into a wrap of the step before it.
        for comment in ("<!-- docs -->", "<!-- docs\nfollow -->", "  <!-- docs -->"):
            text = f"## Next\n- Ship PR 1.\n{comment} Keep open: PR 2\n"
            self.assertEqual(lanelib.kept_open(lanelib.next_block(text)), "Keep open: PR 2",
                             comment)
        # Mid-line, after text, it stays a mention, as it always was.
        text = "## Next\n- Ship. <!-- docs --> Keep open: PR 2\n"
        self.assertIsNone(lanelib.kept_open(lanelib.next_block(text)))

    def test_quoted_markers_never_hide_keep_open(self):
        # The raw strip ran from a quoted `<!--` to a quoted `-->`, the flag between them gone.
        text = ("## Next\n<!-- template -->\n- Document the `<!--` rule.\nKeep open: docs PR "
                "follows\n- Then fix the `-->` parsing.\n")
        self.assertIsNone(lanelib.comment_flaw(text))
        self.assertEqual(lanelib.kept_open(lanelib.next_block(text)), "Keep open: docs PR follows")
        # A double-backtick span quotes too: read as an empty span and a marker, it didn't.
        text = "## Next\n- Doc the ``<!--`` rule\nKeep open: docs PR\n- And ``-->``\n"
        self.assertIsNone(lanelib.comment_flaw(text))
        self.assertEqual(lanelib.kept_open(lanelib.next_block(text)), "Keep open: docs PR")

    def test_a_fence_never_closed_in_its_section_is_plain_text(self):
        # A mistyped closer (here ```bash) once left every later line looking like code, so the
        # unclosed comment in Next passed while section() leaked it. A fence ends at its section.
        text = ("## State\n```\ncode\n```bash\n## Next\n<!-- start with Keep open: PR 2.\n"
                "- Write the docs test.\n")
        self.assertEqual(self.flaw(text), 6)
        self.assertEqual(self.flaw("## Backlog\n~~~html\n<!--\n"), 3)
        # Its lines read as text in the section too, a closed comment in them stripped.
        self.assertEqual(lanelib.section("## Next\n```\n<!-- x -->- Step.\n", "Next"),
                         "```\n- Step.")

    def test_a_stray_closer_is_a_flaw(self):
        # A comment that quoted `-->` ended there: its tail became the first Next item, where
        # /pass reads the approval marker.
        text = "## Next\n<!-- never `-->` here -->\n- Step.\n"
        self.assertEqual(lanelib.comment_flaw(text), (2, lanelib.STRAY))
        self.assertEqual(lanelib.first_item(lanelib.next_block(text)), "` here -->")
        self.assertEqual(lanelib.comment_flaw("## A\nx --> y\n## B\n<!-- z\n"), (2, lanelib.STRAY))
        self.assertEqual(lanelib.comment_flaw("## A\n<!-- z\nx --> y -->\n"), (3, lanelib.STRAY))

    def test_the_template_splice_that_hid_keep_open(self):
        # An edit at the template comment's own mention of the flag dropped its `-->`: the
        # comment's text became the first step, and kept_open found no line starting with it.
        text = ("# LANE: x\n\n## Next\n"
                "<!-- The exact next concrete step and what to verify. handoff-check fails while "
                "this is empty.\nWhile more PRs will follow this one, start with Keep open: PR 2 "
                "follows for the docs.\n- Write the docs test.\n")
        self.assertIsNone(lanelib.kept_open(lanelib.next_block(text)))
        self.assertEqual(self.flaw(text), 4)


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


class ByFd(unittest.TestCase):
    """open_dir and copy_record: sandbox-off walks through dirs a lane's sandbox can write, so a
    name may be a link by the time it is used."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def opened(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, fd)
        return fd

    def test_open_dir_refuses_a_link_anywhere_below_root(self):
        os.makedirs(os.path.join(self.root, "a", "real"))
        os.symlink(os.path.join(self.root, "a"), os.path.join(self.root, "link"))
        os.close(lanelib.open_dir(self.root, "a/real"))
        for rel in ("link/real", "a/../link", "link"):
            with self.subTest(rel=rel), self.assertRaises(OSError):
                os.close(lanelib.open_dir(self.root, rel))
        fd = lanelib.open_dir(self.root, "a/new/deeper", create=True)
        os.close(fd)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "a", "new", "deeper")))
        with self.assertRaises(OSError):  # O_NOFOLLOW never stops `..`: refused by name
            os.close(lanelib.open_dir(self.root, "a/../.."))

    @unittest.skipIf(os.geteuid() == 0, "root reads an execute-only dir")
    def test_open_dir_passes_an_execute_only_dir_on_the_way(self):
        os.makedirs(os.path.join(self.root, "x", "lane"))
        os.chmod(os.path.join(self.root, "x"), 0o111)
        self.addCleanup(os.chmod, os.path.join(self.root, "x"), 0o755)
        os.close(lanelib.open_dir(self.root, "x/lane"))

    def test_copy_record_copies_links_as_links_and_files_with_their_mode(self):
        src = os.path.join(self.root, "rec")
        self.write(os.path.join(src, "STATUS.md"), "# LANE\n")
        os.chmod(os.path.join(src, "STATUS.md"), 0o640)
        self.write(os.path.join(src, "artifacts", "a.png"), "png")
        os.symlink("../..", os.path.join(src, "artifacts", "up"))
        os.mkfifo(os.path.join(src, "fifo"))
        dest = os.path.join(self.root, "dest")
        os.mkdir(dest)
        lanelib.copy_record(self.opened(src), self.opened(dest))
        self.assertEqual(sorted(os.listdir(dest)), ["STATUS.md", "artifacts"])  # no FIFO
        self.assertEqual(os.stat(os.path.join(dest, "STATUS.md")).st_mode & 0o777, 0o640)
        self.assertEqual(os.readlink(os.path.join(dest, "artifacts", "up")), "../..")
        with open(os.path.join(dest, "artifacts", "a.png")) as f:
            self.assertEqual(f.read(), "png")

    def test_copy_record_never_reads_through_a_file_swapped_for_a_link(self):
        # The lane swaps a record file for a link to a read-denied file between the scan and
        # the copy: by path, its content landed in the mirror, which the sandbox can read.
        src = os.path.join(self.root, "rec")
        secret = os.path.join(self.root, "key")
        self.write(secret, "secret")
        self.write(os.path.join(src, "plain"), "x")
        os.makedirs(os.path.join(src, "sub"))
        os.symlink(secret, os.path.join(src, "STATUS.md"))
        os.symlink(self.root, os.path.join(src, "dir"))
        real = os.stat

        def stat(name, *args, **kw):  # the stat sees each before its swap: a file, a dir
            st = real(name, *args, **kw)
            if name == "STATUS.md":
                return real(os.path.join(src, "plain"))
            if name == "dir":
                return real(os.path.join(src, "sub"))
            return st

        dest = os.path.join(self.root, "dest")
        os.mkdir(dest)
        with mock.patch.object(lanelib.os, "stat", side_effect=stat):
            lanelib.copy_record(self.opened(src), self.opened(dest))
        self.assertEqual(os.readlink(os.path.join(dest, "STATUS.md")), secret)
        self.assertEqual(os.readlink(os.path.join(dest, "dir")), self.root)

    def test_copy_record_writes_under_the_dest_it_opened_even_once_its_path_is_a_link(self):
        src = os.path.join(self.root, "rec")
        self.write(os.path.join(src, "STATUS.md"), "# LANE\n")
        self.write(os.path.join(src, "artifacts", "a.png"), "png")
        dest = os.path.join(self.root, "dest")
        os.mkdir(dest)
        dest_fd = self.opened(dest)
        elsewhere = os.path.join(self.root, "elsewhere")
        os.mkdir(elsewhere)
        os.rename(dest, dest + ".old")
        os.symlink(elsewhere, dest)
        lanelib.copy_record(self.opened(src), dest_fd)
        self.assertEqual(os.listdir(elsewhere), [])
        self.assertEqual(sorted(os.listdir(dest + ".old")), ["STATUS.md", "artifacts"])

    def test_copy_record_never_writes_through_a_link_planted_in_dest(self):
        src = os.path.join(self.root, "rec")
        self.write(os.path.join(src, "STATUS.md"), "# LANE\n")
        dest = os.path.join(self.root, "dest")
        os.mkdir(dest)
        target = os.path.join(self.root, "target")
        self.write(target, "keep")
        os.symlink(target, os.path.join(dest, "STATUS.md"))
        with self.assertRaises(FileExistsError):
            lanelib.copy_record(self.opened(src), self.opened(dest))
        with open(target) as f:
            self.assertEqual(f.read(), "keep")


class LeadRelink(_fixture.LiveSessions):
    """lanelib.lead_relink in process, for a child standing in for the hook (its pid): which
    proof, if any, says the session running it continues the recorded lead. This test runner
    plays that session's claude where one must be above the child."""

    OLD, NEW = "s-old", "s-new"

    def setUp(self):
        super().setUp()
        self.repo = lanelib.Repo(self.main, self.common)
        patch = mock.patch.dict(os.environ, CLAUDE_CONFIG_DIR=os.path.join(self.home, ".claude"))
        patch.start()
        self.addCleanup(patch.stop)

    def relink(self, sid, pane="new"):
        return lanelib.lead_relink(self.repo, sid, pid=self.child(self.main, pane=pane))

    def marker(self, pane="%3", **fields):
        """A pass-last marker for pane, written as pass-respawn's write_last writes it, of the
        recorded session passing there on this test's server, unless fields say otherwise."""
        sock, server, _ = self.server.rsplit(",", 2)
        tab = {"socket": sock, "server_start": 0, "server_pid": int(server), "pane": pane}
        self.write(os.path.join(lanelib.state_dir(), "pass-last", pane[1:] + ".json"),
                   json.dumps({"tab": tab, "from_session": self.OLD, "written_at": 0, **fields}))

    def test_no_record_proves_nothing(self):
        self.assertIsNone(self.relink(self.OLD))

    def test_a_running_lead_is_kept_but_for_a_clear_in_it(self):
        self.write_lead(self.child(self.main), sid=self.OLD)
        self.assertIsNone(self.relink(self.OLD))  # the fast path
        self.assertIsNone(self.relink(self.NEW))  # a side chat: the lead isn't above it
        # This runner plays the lead, the nearest session above every child; its file holds the
        # id the /clear gave it.
        self.write_lead(os.getpid(), sid=self.OLD)
        self.session(self.main, pid=os.getpid(), sock=None, sessionId=self.NEW)
        self.assertEqual(self.relink(self.NEW), "clear")
        self.assertIsNone(self.relink(self.OLD))
        # A claude the lead runs, before its own session file is written (the lead is then the
        # nearest session above its hook), carries an id the lead's file doesn't: no clear.
        self.assertIsNone(self.relink("s-child"))
        # Nor before the lead's own file has taken the new id: the next Stop sees it.
        self.session(self.main, pid=os.getpid(), sock=None, sessionId=self.OLD)
        self.assertIsNone(self.relink(self.NEW))

    def test_a_resume_needs_the_lead_gone_or_stopped(self):
        # This runner plays the resumed session, the nearest above every child, holding the id.
        self.session(self.main, pid=os.getpid(), sock=None, sessionId=self.OLD)
        self.write_lead(self.child(self.main, done=True), start=1, sid=self.OLD)
        self.assertEqual(self.relink(self.OLD), "resume")
        self.assertIsNone(self.relink(self.NEW))
        # The nearest session must hold the id itself: a claude a side chat runs, before its
        # own file exists, proves nothing for the side chat.
        self.session(self.main, pid=os.getpid(), sock=None, sessionId=self.NEW)
        self.assertIsNone(self.relink(self.OLD))
        self.session(self.main, pid=os.getpid(), sock=None, sessionId=self.OLD)
        stopped = self.child(self.main)
        self.stop(stopped)
        self.write_lead(stopped, sid=self.OLD)
        self.assertEqual(self.relink(self.OLD), "resume")
        self.assertIsNone(self.relink(self.NEW))

    def test_an_unread_session_file_in_main_never_heals(self):
        # It may be a second continuation (lanelib.lead_unknown), so neither heals. One whose
        # process runs outside main can't be, so the resume still heals.
        self.session(self.main, pid=os.getpid(), sock=None, sessionId=self.OLD)
        self.write_lead(self.child(self.main, done=True), start=1, sid=self.OLD)
        for why, junk in UNREAD.items():
            with self.subTest(why):
                path = os.path.join(self.home, ".claude", "sessions",
                                    f"{self.child(self.main)}.json")
                self.write(path, junk)
                self.assertIsNone(self.relink(self.OLD))
                os.rename(path, os.path.join(os.path.dirname(path),
                                             f"{self.child(self.tmp)}.json"))
                self.assertEqual(self.relink(self.OLD), "resume")

    def test_a_pass_needs_a_fresh_marker_of_the_lead_leaving_this_pane(self):
        # The claude above the child: the successor, with its own new id.
        self.session(self.main, pid=os.getpid(), sock=None, sessionId=self.NEW)
        started = lanelib.proc_epoch(lanelib.proc_start(os.getpid()))
        self.write_lead(self.child(self.main, done=True), start=1, sid=self.OLD,
                        tmux=self.tmux_of("%3"))
        sock, server, _ = self.server.rsplit(",", 2)
        for at in (started - 10, started - 119, started + 1):
            with self.subTest(written_at=at - started):
                self.marker(written_at=at)
                self.assertEqual(self.relink(self.NEW, pane="%3"), "pass")
        cases = {
            "written too early": dict(written_at=started - 200),
            "written after the start": dict(written_at=started + 5),
            "another session's pass": dict(written_at=started, from_session="s-other"),
            "a tab on another socket": dict(written_at=started, tab=dict(
                socket=sock + "x", server_start=0, server_pid=int(server), pane="%3")),
            "a tab on another server": dict(written_at=started, tab=dict(
                socket=sock, server_start=0, server_pid=int(server) + 1, pane="%3")),
            "a tab of another pane": dict(written_at=started, tab=dict(
                socket=sock, server_start=0, server_pid=int(server), pane="%4")),
        }
        for why, fields in cases.items():
            with self.subTest(why):
                self.marker(**fields)
                self.assertIsNone(self.relink(self.NEW, pane="%3"))
        self.marker(written_at=started)
        self.assertIsNone(self.relink(self.NEW, pane="%4"))  # this session in another pane
        self.assertIsNone(self.relink(self.NEW, pane=None))  # or outside tmux
        os.remove(os.path.join(self.home, ".claude", "sessions", f"{os.getpid()}.json"))
        self.assertIsNone(self.relink(self.NEW, pane="%3"))  # no claude above it
        self.session(self.main, pid=os.getpid(), sock=None)
        self.assertIsNone(self.relink(self.NEW, pane="%3"))  # one holding another id
        self.session(self.main, pid=os.getpid(), sock=None, sessionId=self.NEW)
        self.assertEqual(self.relink(self.NEW, pane="%3"), "pass")
        self.write_lead(self.child(self.main, done=True), start=1, sid=self.OLD)  # no tmux
        self.assertIsNone(self.relink(self.NEW, pane="%3"))

    def test_only_a_well_formed_marker_counts(self):
        rec = {"sessionId": self.OLD, "tmux": tuple(self.tmux_of("%3"))}
        path = os.path.join(lanelib.state_dir(), "pass-last", "3.json")
        self.marker(written_at=1.5)
        self.assertEqual(lanelib.pass_marker(rec), 1.5)
        good = self.read(path)
        bad = {"not JSON": "{", "a list": "[]", "nested past json's reach": "[" * 100000,
               "too long": good[:-1] + " " * lanelib.PASS_LAST_MAX + "}"}
        for why, fields in {"no tab": dict(tab=None), "a server pid string": dict(tab=dict(
                                json.loads(good)["tab"], server_pid=str(self.tmux_of("%3")[1]))),
                            "a written_at bool": dict(written_at=True),
                            "a written_at string": dict(written_at="1.5"),
                            "a written_at NaN": dict(written_at=float("nan")),
                            "a from_session list": dict(from_session=[self.OLD])}.items():
            bad[why] = json.dumps({**json.loads(good), **fields})
        for why, text in bad.items():
            with self.subTest(why):
                self.write(path, text)
                self.assertIsNone(lanelib.pass_marker(rec))
        elsewhere = os.path.join(self.tmp, "elsewhere.json")
        self.write(elsewhere, good)
        os.remove(path)
        os.symlink(elsewhere, path)
        self.assertIsNone(lanelib.pass_marker(rec))  # never through a link
        os.remove(path)
        os.mkfifo(path)
        self.assertIsNone(lanelib.pass_marker(rec))  # nor waiting on a FIFO

    def test_ticks_become_epoch_seconds_by_the_boot_time(self):
        pid = self.child(self.main)
        epoch = lanelib.proc_epoch(lanelib.proc_start(pid))
        self.assertLess(abs(epoch - time.time()), 2)  # wall clock
        fake = os.path.join(self.tmp, "proc")
        self.write(os.path.join(fake, "stat"), "cpu  1 2 3\nintr 5 6\nbtime 1700000000\n")
        hz = os.sysconf("SC_CLK_TCK")
        self.assertEqual(lanelib.proc_epoch(250 * hz, fake), 1700000250)
        self.write(os.path.join(fake, "stat"), "cpu  1 2 3\nbtime x\n")
        self.assertIsNone(lanelib.proc_epoch(1, fake))

    def test_the_ancestry_walk_is_bounded(self):
        pid = self.child(self.main)
        me = (os.getpid(), lanelib.proc_start(os.getpid()))
        self.assertEqual(lanelib.ancestry(pid)[0], me)
        self.assertIn((os.getppid(), lanelib.proc_start(os.getppid())), lanelib.ancestry(pid))
        self.assertEqual(lanelib.ancestry(pid, limit=1), [me])


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

    def test_a_pick_flag_takes_a_safe_model_or_one_of_the_five_efforts(self):
        for flag, value in (("--model", "opus"), ("--model", "claude-opus-5-5[1m]"),
                            ("--effort", "low"), ("--effort", "max")):
            with self.subTest(flag=flag, value=value):
                self.assertTrue(lanelib.pick_ok(flag, value))
        for flag, value in (("--model", "-x"), ("--model", "a b"), ("--model", None),
                            ("--effort", "extreme"), ("--effort", "High"), ("--effort", 3),
                            ("--name", "opus")):
            with self.subTest(flag=flag, value=value):
                self.assertFalse(lanelib.pick_ok(flag, value))

    def test_a_stored_pick_keeps_each_field_only_in_its_shape(self):
        # An entry written before the fields existed has neither, and a bad field costs only its
        # own flag.
        for entry, pick in (({"model": "sonnet", "effort": "low"},
                             {"--model": "sonnet", "--effort": "low"}),
                            ({"effort": "high"}, {"--effort": "high"}),
                            ({}, {}),
                            ({"session_id": "x", "cwd": "/x"}, {}),
                            ({"model": "a b", "effort": "high"}, {"--effort": "high"}),
                            ({"model": 5, "effort": "extreme"}, {}),
                            ({"model": ["opus"], "effort": None}, {})):
            with self.subTest(entry=entry):
                self.assertEqual(lanelib.stored_pick(entry), pick)


def command(name, args=""):
    """A slash command's user entry, as Claude Code 2.1.301 writes /model and /effort."""
    return {"type": "user", "isSidechain": False, "message": {"role": "user", "content": (
        f"<command-name>{name}</command-name>\n            <command-message>{name[1:]}"
        f"</command-message>\n            <command-args>{args}</command-args>")}}


def reply(model, effort="medium"):
    """A main-chain assistant entry and what it ran with."""
    return {"type": "assistant", "isSidechain": False, "effort": effort,
            "message": {"model": model, "role": "assistant",
                        "content": [{"type": "text", "text": "ok"}]}}


class CarriedPick(unittest.TestCase):
    """carried_pick in-process: tests/pass covers the plain pass through pass-respawn's CLI; this
    covers a /model no reply followed, which a pass and a resume (tab restore, the shelf's Open)
    carry alike, and a session launched with no --model, which ANTHROPIC_MODEL pins."""

    LAUNCHED = {"--model": "sonnet", "--effort": "low"}

    def transcript(self, *entries):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        self.addCleanup(os.remove, path)
        with os.fdopen(fd, "w") as f:
            f.writelines(json.dumps(e) + "\n" for e in entries)
        return path

    def test_a_model_argument_no_reply_followed_carries(self):
        # The server died, or the pass came, between the /model and its first reply. The fresh
        # claude would take the pin, not the pick, so the argument carries; the effort the
        # /model moved has no entry to say what, so it drops to the saved default.
        for after in ([], [reply("<synthetic>", None)]):
            with self.subTest(after=after):
                path = self.transcript(reply("claude-sonnet-5-5", "low"),
                                       command("/model", "opus[1m]"), *after)
                self.assertEqual(lanelib.carried_pick(self.LAUNCHED, path),
                                 ["--model", "opus[1m]"])
                self.assertEqual(lanelib.carried_pick({}, path), ["--model", "opus[1m]"])

    def test_a_menu_pick_or_a_bad_argument_with_no_reply_drops_the_model(self):
        for args in ("", "sonet", "-x"):
            with self.subTest(args=args):
                path = self.transcript(reply("claude-sonnet-5-5", "low"), command("/model", args))
                self.assertEqual(lanelib.carried_pick(self.LAUNCHED, path), [])
                self.assertEqual(lanelib.carried_pick({}, path), [])

    def test_a_model_pick_carries_with_no_launch_flag(self):
        # Launched bare, the fresh claude would take the pin: the /model carries as it would
        # over a launch --model.
        for args, ran, model in (("sonnet", "claude-sonnet-5-5", "sonnet"),
                                 ("", "claude-haiku-5-5", "claude-haiku-5-5"),
                                 ("sonnet", "claude-opus-5-5", "claude-opus-5-5")):
            with self.subTest(args=args, ran=ran):
                path = self.transcript(reply("claude-opus-5-5", "high"), command("/model", args),
                                       reply(ran, "high"))
                self.assertEqual(lanelib.carried_pick({}, path), ["--model", model])
                self.assertEqual(lanelib.carried_pick({"--effort": "low"}, path),
                                 ["--model", model, "--effort", "high"])

    def test_a_model_default_argument_carries_with_no_launch_flag(self):
        # --model default is the account's default, not the pin (probed 2026-10-23 on 2.1.309):
        # what the /model picked, so it carries like any other argument.
        path = self.transcript(command("/model", "default"), reply("claude-opus-5-5", "high"))
        self.assertEqual(lanelib.carried_pick({}, path), ["--model", "default"])

    def test_with_no_launch_model_the_replies_before_a_command_go_unparsed(self):
        path = self.transcript(*[reply("claude-opus-5-5", "high")] * 5, command("/model", "sonnet"),
                               reply("claude-sonnet-5-5", "low"))
        with mock.patch.object(lanelib, "ran", wraps=lanelib.ran) as ran:
            self.assertEqual(lanelib.carried_pick({"--effort": "low"}, path),
                             ["--model", "sonnet", "--effort", "low"])
        self.assertEqual(ran.call_count, 1)
        with mock.patch.object(lanelib, "ran", wraps=lanelib.ran) as ran:
            lanelib.carried_pick(self.LAUNCHED, path)
        self.assertEqual(ran.call_count, 6)

    def test_with_no_launch_flag_no_model_command_carries_nothing(self):
        # What ran says nothing without a launch value to hold it against (a /model before a
        # /clear reverts to the pin), and an /effort carries only over a launch --effort: the
        # saved default it wrote applies.
        path = self.transcript(reply("claude-sonnet-5-5", "low"), command("/effort", "max"),
                               reply("claude-sonnet-5-5", "max"))
        self.assertEqual(lanelib.carried_pick({}, path), [])

    def test_no_transcript_carries_the_launch_flags(self):
        # A tab with no input yet: nothing to read, so what it launched with.
        for path in (None, "/nonexistent/x.jsonl"):
            with self.subTest(path=path):
                self.assertEqual(lanelib.carried_pick(self.LAUNCHED, path),
                                 ["--model", "sonnet", "--effort", "low"])
        self.assertEqual(lanelib.carried_pick({}, None), [])


class UnreadSessions(unittest.TestCase):
    """A session file that exists but doesn't read as a JSON object (junk, or nested past
    json's reach) may hide a live session: liveness turns unknown and the sessions above a
    command can't be told, unless its name rules it out."""

    def setUp(self):
        self.cfg = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cfg)
        self.dir = os.path.join(self.cfg, "sessions")
        os.makedirs(self.dir)
        patch = mock.patch.dict(os.environ, CLAUDE_CONFIG_DIR=self.cfg, _LANE_TEST_SANDBOXED="0")
        patch.start()
        self.addCleanup(patch.stop)

    def child(self, done=False):
        p = subprocess.Popen(["true"] if done else ["sleep", "60"])
        self.addCleanup(lambda: p.poll() is None and (p.kill(), p.wait()))
        if done:
            p.wait()
        return p.pid

    def put(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_liveness_is_unknown_beside_an_unread_file_of_a_present_pid(self):
        pid = self.child()
        self.put(f"{pid}.json", json.dumps({"pid": pid, "procStart": str(lanelib.proc_start(pid))}))
        self.assertEqual([s["pid"] for s in lanelib.live_sessions()], [pid])
        for why, junk in UNREAD.items():
            for name in (f"{self.child()}.json", "not-a-pid.json"):
                with self.subTest(why, name=name):
                    path = self.put(name, junk)
                    self.assertIsNone(lanelib.live_sessions())
                    os.unlink(path)
            with self.subTest(why, name="a dead pid's"):  # it can't hide a live session
                path = self.put(f"{self.child(done=True)}.json", junk)
                self.assertEqual([s["pid"] for s in lanelib.live_sessions()], [pid])
                os.unlink(path)

    def test_a_torn_file_is_read_again_once(self):
        pid = self.child()
        good = json.dumps({"pid": pid, "procStart": str(lanelib.proc_start(pid))})
        path = self.put(f"{pid}.json", "{")
        with mock.patch.object(lanelib.time, "sleep", lambda _: self.put(f"{pid}.json", good)):
            self.assertEqual([s["pid"] for s in lanelib.live_sessions()], [pid])
        self.assertEqual(lanelib.session_scan().unread, [])
        self.put(f"{pid}.json", "{")
        self.assertEqual(lanelib.session_scan().unread, [path])

    def test_a_dead_pids_file_is_ruled_out_without_a_second_read(self):
        # Its process is gone, so it hides no live session: no wait for a torn rewrite.
        # Sandboxed, every pid looks gone, so there it stays unread.
        for why, junk in UNREAD.items():
            with self.subTest(why):
                path = self.put(f"{self.child(done=True)}.json", junk)
                with mock.patch.object(lanelib.time, "sleep") as sleep:
                    self.assertEqual(lanelib.session_scan().unread, [])
                self.assertNotIn(mock.call(lanelib.REREAD_WAIT), sleep.call_args_list)
                with mock.patch.dict(os.environ, _LANE_TEST_SANDBOXED="1"):
                    self.assertEqual(lanelib.session_scan().unread, [path])
                os.unlink(path)

    def test_the_sessions_above_refuse_an_unread_ancestor_file(self):
        hook = self.child()  # this runner is its parent, so an ancestor
        self.assertEqual(lanelib.sessions_above(hook), [])
        for why, junk in UNREAD.items():
            for name in (f"{os.getpid()}.json", "not-a-pid.json"):
                with self.subTest(why, name=name):
                    path = self.put(name, junk)
                    with self.assertRaisesRegex(lanelib.Untrusted, "can't be read"):
                        lanelib.sessions_above(hook)
                    os.unlink(path)
            for done in (True, False):  # a pid outside the chain, dead or running: ruled out
                with self.subTest(why, name="no ancestor's", done=done):
                    path = self.put(f"{self.child(done)}.json", junk)
                    self.assertEqual(lanelib.sessions_above(hook), [])
                    os.unlink(path)

    def test_a_transcript_line_holding_cwd_that_wont_parse_ends_the_scan(self):
        # A skipped line never lets a later cwd prove where the session started.
        later = json.dumps({"type": "user", "cwd": "/later"}) + "\n"
        path = os.path.join(self.cfg, "t.jsonl")
        for why, line in {"junk": '{"cwd": "/first"', "deep": '{"cwd": ' + "[" * 100000}.items():
            with self.subTest(why):
                with open(path, "w") as f:
                    f.write(line + "\n" + later)
                self.assertIsNone(lanelib.transcript_cwd(path))
        with open(path, "w") as f:  # a junk line with no cwd in it can't hide one
            f.write('{"type": "summ\n' + later)
        self.assertEqual(lanelib.transcript_cwd(path), "/later")


if __name__ == "__main__":
    unittest.main()
