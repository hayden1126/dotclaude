"""hooks/lane-guard.sh and hooks/lane-identity.sh, run as Claude Code runs them: the event JSON on
stdin to the bash shim."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

from _fixture import HOOKS, LanesRepo
import lanelib  # on sys.path through _fixture
import test_cli  # by module: a class imported by name would have its tests collected here too

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

    def test_a_write_through_a_symlinked_record_is_denied(self):
        # Resolved first, <lane>/.lane/STATUS.md through `.lane -> ..` has no .lane part left,
        # and lands outside any repo: both rules were skipped.
        lane = self.lane_path("chart-fix")
        shutil.rmtree(os.path.join(lane, ".lane"))
        os.symlink("..", os.path.join(lane, ".lane"))
        for raw in (os.path.join(lane, ".lane", "STATUS.md"), ".lane/STATUS.md"):
            with self.subTest(raw=raw):
                self.assertDenied(self.write_call(lane, raw, CLEAN), "symlink")

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
        self.write(self.own, "## State\nanother session said so\n- a\n- c\n- x\n")
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

    def test_an_edit_anchored_on_a_closing_fence_is_judged_in_the_whole_file(self):
        # In the fragment alone the closer reads as an opener and hides the new prose.
        lane = self.lane_path("chart-fix")
        self.write(self.own, "# LANE\n```\ncode\n```\n## Next\n- ship\n")
        edit = {"old_string": "```\n## Next",
                "new_string": "```\nThe other lane owns the parser.\n## Next"}
        self.assertDenied(self.write_call(lane, self.own, None, tool="Edit", **edit),
                          "the other lane")
        multi = {"edits": [{"old_string": "- ship", "new_string": "- ship it"}, edit]}
        self.assertDenied(self.write_call(lane, self.own, None, tool="MultiEdit", **multi),
                          "the other lane")
        inside = {"old_string": "code\n", "new_string": "code\nmy lane\n"}  # inside the fence
        self.assertIsNone(self.write_call(lane, self.own, None, tool="Edit", **inside))

    def test_replace_all_is_applied_to_every_copy(self):
        lane = self.lane_path("chart-fix")
        self.write(self.own, "```\nc\n```\nx\n```\nd\n```\nx\n")
        edit = {"old_string": "```\nx", "new_string": "```\nmy lane: x", "replace_all": True}
        self.assertDenied(self.write_call(lane, self.own, None, tool="Edit", **edit), "my lane")

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

    def test_a_symlinked_lane_dir_in_a_repo_without_lanes_is_allowed(self):
        # The symlink deny is for lanes repos only; elsewhere `.lane` is just a name.
        os.symlink("..", os.path.join(self.main, ".lane"))
        out = self.hook("lane-guard.sh", {
            "session_id": "s", "cwd": self.main, "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(self.main, ".lane", "STATUS.md"),
                           "content": RELATIVE}})
        self.assertIsNone(out)


class IdentityHook(LanesRepo):
    def setUp(self):
        super().setUp()
        # A branch apart from the id, so a line that named one for the other would show.
        self.lane("new", "chart-fix", "--claim", "42", "--branch", "fix/chart")
        self.lane_dir = self.lane_path("chart-fix")

    def start(self, cwd, source="startup", sid="sess-0001", **extra):
        return self.hook("lane-identity.sh", {"session_id": sid, "cwd": cwd, "source": source,
                                              "hook_event_name": "SessionStart", **extra})

    def test_a_lane_session_learns_its_identity_and_is_registered(self):
        out = self.start(os.path.join(self.lane_dir))
        ctx = out["additionalContext"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        for piece in ("`chart-fix`", "branch `fix/chart`", "#42", "port 5191",
                      self.record("chart-fix"), "read-only", "`lane who", "another session",
                      "`lane addr lead`", "just before each send"):
            self.assertIn(piece, ctx)
        self.assertNotIn("re-read", ctx)
        (s,) = self.lane_json("chart-fix")["sessions"]
        self.assertEqual((s["session_id"], s["source"]), ("sess-0001", "startup"))
        self.assertIn("startedAt", s)

    def test_a_switched_lane_is_told_its_checked_out_branch(self):
        # A `git switch` for a follow-up PR leaves lane.json's branch behind.
        self.git("switch", "-q", "-c", "chart-more", cwd=self.lane_dir)
        ctx = self.start(self.lane_dir)["additionalContext"]
        self.assertIn("branch `chart-more`, claims #42", ctx)
        self.assertNotIn("fix/chart", ctx)

    def test_a_detached_lane_is_told_its_commit(self):
        self.git("switch", "-q", "--detach", cwd=self.lane_dir)
        sha = self.git("rev-parse", "HEAD", cwd=self.lane_dir).strip()
        ctx = self.start(self.lane_dir)["additionalContext"]
        self.assertIn(f"`chart-fix`: a detached HEAD at `{sha[:12]}`, claims #42", ctx)
        self.assertNotIn("branch `", ctx)

    def test_an_unusable_head_names_lane_json_s_branch_and_says_so(self):
        # The admin dir is sandbox-writable. git refuses the first; it reports the others, which
        # must not reach the context: a backtick ends the code span, a tag is no branch, and a
        # name that isn't UTF-8 fails the decode.
        admin = self.git("rev-parse", "--absolute-git-dir", cwd=self.lane_dir).strip()
        log = os.path.join(self.tmp, "state", "dotclaude", "lane-identity.log")
        # The hook decodes git's output in the locale's encoding; a single-byte one reads \xff
        # cleanly (valid_branch still refuses it), so the decode reason needs a UTF-8 locale.
        self.env["LC_ALL"] = "C.UTF-8"
        for head, why in ((b"ref: refs/heads/-bad name", "symbolic-ref exit 128"),
                          (b"ref: refs/heads/a`b", "symbolic-ref exit 0, 'refs/heads/a`b'"),
                          (b"ref: refs/tags/v1", "symbolic-ref exit 0, 'refs/tags/v1'"),
                          (b"ref: refs/heads/\xff", "UnicodeDecodeError")):
            with self.subTest(head=head):
                with open(os.path.join(admin, "HEAD"), "wb") as f:
                    f.write(head + b"\n")
                seen = len(self.read(log).splitlines()) if os.path.exists(log) else 0
                ctx = self.start(self.lane_dir)["additionalContext"]
                self.assertIn("branch `fix/chart` (lane.json's: the worktree's HEAD couldn't be "
                              "read), claims #42", ctx)
                self.assertNotIn("a`b", ctx)
                self.assertNotIn("refs/", ctx)
                (line,) = self.read(log).splitlines()[seen:]
                self.assertIn(f"head unreadable lane=chart-fix: {why}", line)

    def identity_module(self):
        spec = importlib.util.spec_from_file_location(
            "lane_identity_t", os.path.join(HOOKS, "lane_identity.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_git_failing_falls_back_to_lane_json_s_branch(self):
        mod = self.identity_module()
        repo = mod.lanelib.resolve(self.lane_dir)
        lane = repo.lane_at(self.lane_dir)
        for error in (OSError("no git"), subprocess.TimeoutExpired(["git"], mod.GIT_WAIT)):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(mod.lanelib, "git", side_effect=error):
                    self.assertEqual(mod.checked_out(repo, lane),
                                     "branch `fix/chart` (lane.json's: the worktree's HEAD "
                                     "couldn't be read)")

    def test_the_git_calls_fit_inside_the_hook_s_timeout(self):
        # Claude Code kills the hook at its settings.json timeout, which costs the whole line, so
        # a HEAD read that hangs must time out first: the lock wait and both reads (a detached
        # HEAD makes two) fit inside it, with a second to spare for resolve() and the rest. A
        # git that hangs in resolve() leaves no lane to name, so its 60 s doesn't count here.
        mod = self.identity_module()
        with open(os.path.join(os.path.dirname(HOOKS), "settings.json")) as f:
            settings = json.load(f)
        (timeout,) = [h["timeout"] for group in settings["hooks"]["SessionStart"]
                      for h in group["hooks"] if "lane-identity.sh" in h["command"]]
        self.assertLessEqual(mod.LOCK_WAIT + 2 * mod.GIT_WAIT, timeout - 1)
        self.git("switch", "-q", "--detach", cwd=self.lane_dir)
        repo = mod.lanelib.resolve(self.lane_dir)
        lane = repo.lane_at(self.lane_dir)
        with mock.patch.object(mod.lanelib, "git", wraps=mod.lanelib.git) as git:
            self.assertTrue(mod.checked_out(repo, lane).startswith("a detached HEAD at `"))
        self.assertEqual([c.kwargs.get("timeout") for c in git.call_args_list],
                         [mod.GIT_WAIT, mod.GIT_WAIT])

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
        self.assertIn("`lane addr <id>`", out["additionalContext"])

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

    def test_links_are_mirrored_as_links_and_never_followed(self):
        # Following them copied whatever they reached (`../..`, a home dir, keys) into the
        # mirror and every archive. Evidence must be real files in .lane/artifacts/.
        outside = os.path.join(self.tmp, "outside")
        self.write(os.path.join(outside, "key"), "secret")
        art = os.path.join(self.lane_dir, ".lane", "artifacts")
        os.makedirs(art)
        os.symlink("../..", os.path.join(art, "src"))
        os.symlink(outside, os.path.join(art, "out"))
        os.symlink(os.path.join(outside, "key"), os.path.join(art, "key"))
        self.stop()
        for name in ("src", "out", "key"):
            with self.subTest(name=name):
                self.assertTrue(os.path.islink(self.mirror("artifacts", name)))
        self.assertEqual(sorted(os.listdir(self.mirror("artifacts"))), ["key", "out", "src"])

    def test_a_symlinked_record_is_never_mirrored(self):
        rec = os.path.join(self.lane_dir, ".lane")
        shutil.rmtree(rec)
        os.symlink("..", rec)
        self.start(self.lane_dir)
        self.hook("lane-identity.sh", {"session_id": "sess-0001", "cwd": self.lane_dir,
                                       "hook_event_name": "SessionEnd", "reason": "other"})
        self.assertFalse(os.path.exists(self.mirror()))
        self.assertIn("endedAt", self.lane_json("chart-fix")["sessions"][0])
        with open(os.path.join(self.tmp, "state", "dotclaude", "lane-identity.log")) as f:
            self.assertIn("symlink", f.read())

    def test_the_end_is_stamped_before_the_mirror_runs(self):
        # A slow mirror killed at the hook timeout must not cost endedAt. A SystemExit from the
        # mirror stands in for the kill: nothing after it in end() runs.
        self.start(self.lane_dir)
        spec = importlib.util.spec_from_file_location(
            "lane_identity_t", os.path.join(HOOKS, "lane_identity.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        repo = mod.lanelib.resolve(self.lane_dir)
        lane = repo.lane_at(self.lane_dir)
        event = {"session_id": "sess-0001", "hook_event_name": "SessionEnd", "reason": "other"}
        with mock.patch.object(mod, "mirror", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                mod.end(repo, lane, event)
        self.assertIn("endedAt", self.lane_json("chart-fix")["sessions"][0])

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


class LeadHeal(test_cli.LeadChain):
    """In the main checkout, the hook relinks the lead record on proof that the session running
    it continues the recorded lead (lanelib.lead_relink): a resume of the recorded session id
    while the recorded process is gone or stopped, a /clear in the recorded process, or a /pass
    successor the pass-last marker names. Each session is a fake claude that runs the hook as
    its child, as Claude Code does, so the `lane lead` the hook runs finds it above."""

    OLD, NEW = "sess-main-0001", "sess-main-0002"  # the recorded session id, and another

    def setUp(self):
        super().setUp()
        self.log_path = os.path.join(self.tmp, "state", "dotclaude", "lane-identity.log")

    def write_record(self, pid, start, sid=OLD, pane="%3"):
        """A lead record as `lane lead` writes one, on this test's server (the runner)."""
        tmux = [self.tmux_sock, os.getpid(), lanelib.proc_start(os.getpid()), pane]
        self.write(self.lead_path, json.dumps({"pid": pid, "procStart": start, "sessionId": sid,
                                               "tmux": tmux if pane else None,
                                               "at": "2026-10-17T09:00:00+00:00"}))
        return self.read(self.lead_path)

    def exited(self):
        """The pid of a process that has exited and been reaped: a lead that is gone."""
        p = subprocess.Popen(["true"])
        p.wait()
        return p.pid

    def marker(self, pane="%3", tab_pane=None, **fields):
        """pass-respawn's pass-last marker for pane, as write_last writes it: the session that
        passed (OLD by default) and the tab it passed in (pane on this test's server)."""
        tab = {"socket": self.tmux_sock, "server_start": int(time.time()) - 600,
               "server_pid": os.getpid(), "pane": tab_pane or pane}
        self.write(os.path.join(self.tmp, "state", "dotclaude", "pass-last", pane[1:] + ".json"),
                   json.dumps({"tab": tab, "from_session": self.OLD,
                               "written_at": time.time() - 1, "shown": False,
                               "replies": [{"prompt_id": "p1", "text": "done", "time": 1.0}],
                               **fields}))

    def run_hook(self, sid, name="SessionStart", source="resume", at=None, before=None,
                 **session):
        """A fake session (session(): its keywords; its session id is sid and its launch dir
        at unless they say) runs hooks/lane_identity.py as its child from at (the main
        checkout by default), with an event for sid there; its pid and the hook's
        {rc, out, err}."""
        at = at or self.main
        event = {"session_id": sid, "cwd": at, "hook_event_name": name,
                 **({"source": source} if name == "SessionStart" else {})}
        session.setdefault("sid", sid)
        session.setdefault("cwd", at)
        (pid,), res = self.runs_in_chain(
            [sys.executable, "-I", os.path.join(HOOKS, "lane_identity.py")], [session],
            run_in=at, stdin=json.dumps(event), before=before)
        self.assertEqual((res["rc"], res["err"]), (0, ""))
        return pid, res

    def hook_in_chain(self, sid, sessions, before=None):
        """run_hook's Stop for sid, from the nearest of a chain of fake sessions (session()
        keywords, file=False for one whose file isn't written yet), each started by the one
        before it; their pids and the hook's {rc, out, err}."""
        event = {"session_id": sid, "cwd": self.main, "hook_event_name": "Stop"}
        pids, res = self.runs_in_chain(
            [sys.executable, "-I", os.path.join(HOOKS, "lane_identity.py")], sessions,
            stdin=json.dumps(event), before=before)
        self.assertEqual((res["rc"], res["err"]), (0, ""))
        return pids, res

    def relinks(self):
        """The hook's relink lines in lane-identity.log."""
        try:
            return [line for line in self.read(self.log_path).splitlines() if " relink " in line]
        except FileNotFoundError:
            return []

    def assertBoardOnly(self, res):
        """SessionStart's output is the board line alone, as before the heal."""
        out = json.loads(res["out"])
        self.assertEqual(list(out), ["hookSpecificOutput"])
        self.assertTrue(out["hookSpecificOutput"]["additionalContext"].startswith(
            "Main checkout of a lanes repo; lanes: chart-fix"))

    def test_a_resume_of_a_gone_lead_relinks_it(self):
        self.write_record(self.exited(), 1)
        pid, res = self.run_hook(self.OLD)
        self.assertLead(pid, self.OLD)
        self.assertBoardOnly(res)
        (line,) = self.relinks()
        self.assertIn(f" relink resume sid={self.OLD} rc=0: lead of {self.main}: session "
                      f"{self.OLD} in proj:@3", line)

    def test_a_resume_beside_the_stopped_lead_relinks_it(self):
        # The incident: the lead sits stopped (Ctrl+Z) while `claude --resume` runs it again.
        (stopped,) = self.start(self.fake(self.main))
        self.session(stopped, sid=self.OLD)  # with its socket: present, yet no twin
        self.stop(stopped)
        self.write_record(stopped, self.starts[stopped])
        pid, _ = self.run_hook(self.OLD)
        self.assertLead(pid, self.OLD)

    def test_a_pass_successor_beside_a_resume_heals_neither(self):
        # lead_of's two continuations are no pick, a successor in the recorded pane and a resume
        # of the recorded id, so neither heals ahead of the other: Hayden picks.
        before = self.write_record(self.exited(), 1)
        self.marker()
        (resumed,) = self.start(self.fake(self.main))
        self.session(resumed, sid=self.OLD, pane="%4")
        self.run_hook(self.NEW, source="startup")  # the successor, in the recorded pane
        self.assertEqual(self.read(self.lead_path), before)
        cfg = self.fake(self.main)
        cfg["env"].update(TMUX=f"{self.tmux_sock},{os.getpid()},0", TMUX_PANE="%3")
        (successor,) = self.start(cfg)
        self.session(successor, sid=self.NEW)
        self.run_hook(self.OLD, pane="%5")  # a resume, in a tab of its own
        self.assertEqual(self.read(self.lead_path), before)
        self.assertEqual(self.relinks(), [])

    def test_a_running_lead_is_never_displaced(self):
        # A resume of its session id elsewhere, and a side chat: the recorded process runs.
        (lead,) = self.start(self.fake(self.main))
        before = self.write_record(lead, self.starts[lead])
        self.run_hook(self.OLD)
        self.run_hook(self.NEW, source="startup", pane="%4")
        self.assertEqual(self.read(self.lead_path), before)
        self.assertEqual(self.relinks(), [])

    def test_a_resume_proves_only_the_session_holding_the_id(self):
        # `claude -p --resume <lead id>` run from a side chat: `lane lead` records the nearest
        # session above the hook, so the proof is about that one. Before the -p's own file
        # exists, the nearest is the side chat, which holds another id; once it does, the -p
        # (no socket) is the nearest, and `lane lead` refuses it.
        before = self.write_record(self.exited(), 1)
        self.hook_in_chain(self.OLD, [dict(sid=self.NEW, pane="%4"), dict(file=False)])
        self.assertEqual(self.read(self.lead_path), before)
        self.assertEqual(self.relinks(), [])
        self.hook_in_chain(self.OLD, [dict(sid=self.NEW, pane="%4"), dict(sid=self.OLD,
                                                                          sock=False)])
        self.assertEqual(self.read(self.lead_path), before)
        (line,) = self.relinks()
        self.assertIn(f" relink resume sid={self.OLD} rc=1: ", line)

    def test_two_resumes_heal_neither(self):
        # Two running resumes of the lead's id are no pick (lanelib.lead_of), so the heal
        # leaves the choice to Hayden, not to whichever heals first.
        before = self.write_record(self.exited(), 1)
        (other,) = self.start(self.fake(self.main))
        self.session(other, sid=self.OLD, pane="%4")
        self.run_hook(self.OLD, name="Stop")
        self.assertEqual(self.read(self.lead_path), before)
        self.assertEqual(self.relinks(), [])

    def test_a_claude_the_running_lead_started_is_no_clear(self):
        # An interactive claude under the lead (its own file, a new id) has the lead above it,
        # but `lane lead` would record the child: only the recorded process itself clears.
        def lead(pids):
            self.before = self.write_record(pids[0], self.starts[pids[0]])

        self.hook_in_chain(self.NEW, [dict(sid=self.OLD), dict(sid=self.NEW)], before=lead)
        self.assertEqual(self.read(self.lead_path), self.before)
        self.assertEqual(self.relinks(), [])

    def test_lane_lead_records_only_the_expected_session(self):
        # The hook passes the proved id along, so a session that changed between the proof
        # and the write is never recorded.
        pid, res = self.act(["lead", "--expect-sid", self.NEW], sid=self.OLD)
        self.assertEqual(res["rc"], 1, res)
        self.assertIn(f"session {self.OLD} runs this, not {self.NEW}", res["err"])
        self.assertIsNone(self.lead())
        pid, res = self.act(["lead", "--expect-sid", self.OLD], sid=self.OLD)
        self.assertEqual(res["rc"], 0, res)
        self.assertLead(pid, self.OLD)

    def test_a_clear_updates_the_session_id(self):
        # /clear keeps the process and starts a new session id, which its session file holds.
        pid, res = self.run_hook(self.NEW, source="clear", before=lambda pids: self.write_record(
            pids[0], self.starts[pids[0]], sid=self.OLD))
        self.assertLead(pid, self.NEW)
        self.assertBoardOnly(res)
        (line,) = self.relinks()
        self.assertIn(f" relink clear sid={self.NEW} rc=0: ", line)

    def test_a_pass_successor_relinks_by_the_marker(self):
        before = self.write_record(self.exited(), 1)
        cases = {
            "no marker": dict(),
            "a stale marker": dict(written_at=time.time() - 300),
            "another session's pass": dict(from_session="sess-other-0001"),
            "another pane's pass": dict(pane="%4"),
            "a tab naming another pane": dict(tab_pane="%4"),
            "a tab on another server": dict(tab=dict(socket=self.tmux_sock, server_start=1,
                                                     server_pid=1, pane="%3")),
            "a written_at that isn't a time": dict(written_at=True),
            "a successor in another pane": dict(at="%4"),
        }
        for why, kw in cases.items():
            with self.subTest(why):
                shutil.rmtree(os.path.join(self.tmp, "state", "dotclaude", "pass-last"), True)
                at = kw.pop("at", "%3")
                if why != "no marker":
                    self.marker(**kw)
                pid, _ = self.run_hook(self.NEW, source="startup", pane=at)
                self.assertEqual(self.read(self.lead_path), before)
                # Ended, or the next case's successor would heal beside a second one in the
                # pane, which is no pick.
                self.kill_ours([pid])
        self.assertEqual(self.relinks(), [])
        self.marker()
        pid, res = self.run_hook(self.NEW, source="startup")
        self.assertLead(pid, self.NEW)
        self.assertBoardOnly(res)
        (line,) = self.relinks()
        self.assertIn(f" relink pass sid={self.NEW} rc=0: ", line)

    def test_a_fresh_session_never_takes_it(self):
        before = self.write_record(self.exited(), 1)
        self.run_hook(self.NEW, source="startup", pane="%9")
        self.run_hook(self.NEW, name="Stop", pane="%9")
        self.assertEqual(self.read(self.lead_path), before)
        self.assertEqual(self.relinks(), [])

    def test_a_lane_session_with_the_recorded_id_never_takes_it(self):
        before = self.write_record(self.exited(), 1)
        _, res = self.run_hook(self.OLD, at=self.path)  # its event and session file in the lane
        self.assertIn("You are lane `chart-fix`", res["out"])
        self.assertEqual(self.relinks(), [])
        # One cd'd to main: the hook sees main, and `lane lead` refuses by its launch dir.
        self.run_hook(self.OLD, name="Stop", cwd=self.path)
        self.assertEqual(self.read(self.lead_path), before)
        (line,) = self.relinks()
        self.assertIn(f" relink resume sid={self.OLD} rc=1: lane: session {self.OLD} launched "
                      f"in {self.path}, outside the main checkout", line)

    def test_a_stop_heals_as_session_start_does(self):
        self.write_record(self.exited(), 1)
        pid, res = self.run_hook(self.OLD, name="Stop")
        self.assertEqual(res["out"], "")
        self.assertLead(pid, self.OLD)

    def test_the_fast_path_runs_no_lane_lead(self):
        # The recorded process runs and runs the hook, with the recorded session id.
        def lead(pids):
            self.before = self.write_record(pids[0], self.starts[pids[0]])

        for name in ("SessionStart", "Stop"):
            with self.subTest(name):
                self.run_hook(self.OLD, name=name, before=lead)
                self.assertEqual(self.read(self.lead_path), self.before)
        self.assertEqual(self.relinks(), [])

    def test_a_malformed_record_changes_nothing(self):
        for bad in ("{not json", json.dumps({"pid": "1", "procStart": 1, "sessionId": self.OLD}),
                    "[" * 100000):
            with self.subTest(bad=bad[:20]):
                self.write(self.lead_path, bad)
                _, res = self.run_hook(self.OLD, source="startup")
                self.assertBoardOnly(res)
                self.run_hook(self.OLD, name="Stop")
                self.assertEqual(self.read(self.lead_path), bad)
        self.assertEqual(self.relinks(), [])

    def test_the_relink_fits_inside_the_hook_s_timeout(self):
        # Claude Code kills the hook at its settings.json timeout: `lane lead` must give up a
        # second ahead of it, leaving room for resolve() and the proof.
        spec = importlib.util.spec_from_file_location(
            "lane_identity_t", os.path.join(HOOKS, "lane_identity.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with open(os.path.join(os.path.dirname(HOOKS), "settings.json")) as f:
            settings = json.load(f)
        timeouts = [h["timeout"] for event in ("SessionStart", "Stop")
                    for group in settings["hooks"][event] for h in group["hooks"]
                    if "lane-identity.sh" in h["command"]]
        self.assertEqual(len(timeouts), 2)
        self.assertLessEqual(mod.RELINK_WAIT, min(timeouts) - 1)


if __name__ == "__main__":
    unittest.main()
