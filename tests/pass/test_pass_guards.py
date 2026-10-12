"""skills/pass/scripts/pass-respawn, the second review's guards: the full set of sandbox-writable
roots and the script's own location, a PATH pinned for every child, any background task, the
input box and copy mode, prompts typed mid-turn, approval dates and one pending pass per session.

Each test reuses test_pass_respawn's fixture (Base): fakes for tmux, the session file, /proc and
the transcript, under a temp HOME and XDG_STATE_HOME. Nothing reaches the live tmux server or the
real ~/.claude."""
import datetime
import fcntl
import json
import os
import subprocess
import sys
import time

import test_pass_respawn as t

REPO, SCRIPT = t.REPO, t.SCRIPT
ESC, MARK, NBSP = t.ESC, t.PROMPT_MARK, t.NBSP


class Plain(t.Base):
    PROMPT = "Read STATUS.md (and PLAN.md if present), then plan the next step."

    def setUp(self):
        super().setUp()
        self.commit("STATUS.md", t.GOOD, msg="Handoff")

    def settings(self, path, **tree):
        self.write(path, json.dumps(tree))

    def clear_log(self):
        log = os.path.join(self.state, "pass.log")
        if os.path.exists(log):
            os.remove(log)

    def wait_log(self, words, count=1):
        for _ in range(200):
            if self.log().count(words) >= count:
                return
            time.sleep(0.05)
        self.fail(f"no {words!r} x{count} in pass.log: {self.log()}")


# ---- 1. writable roots and the script's own location ------------------------------------------

class WritableRoots(Plain):
    def test_the_launch_dir_and_every_additional_directory_count(self):
        managed = os.path.join(self.tmp, "managed-settings.json")
        self.mod.MANAGED_SETTINGS = managed
        self.mod.MANAGED_DIR = os.path.join(self.tmp, "managed-settings.d")
        launch = os.path.join(self.tmp, "launch")
        self.settings(os.path.join(self.home, ".claude", "settings.json"),
                      permissions={"additionalDirectories": ["~/extra"]})
        self.settings(managed, permissions={"additionalDirectories": ["/managed-add"]})
        self.settings(os.path.join(launch, ".claude", "settings.json"),
                      sandbox={"filesystem": {"allowWrite": ["/launchw"]}},
                      permissions={"additionalDirectories": ["/launch-add"]})
        self.settings(os.path.join(launch, ".claude", "settings.local.json"),
                      sandbox={"filesystem": {"allowWrite": ["/launch-local"]}})
        self.settings(os.path.join(self.main, ".claude", "settings.local.json"),
                      permissions={"additionalDirectories": ["/proj-add"]})
        import lanelib
        roots = self.real_roots(lanelib.resolve(self.main), self.main, launch)
        for want in (launch, os.path.join(self.home, "extra"), "/managed-add", "/launchw",
                     "/launch-add", "/launch-local", "/proj-add", self.main):
            self.assertIn(want, roots)

    def test_the_call_passes_the_session_launch_dir(self):
        seen = []
        self.session_cwd = launch = os.path.join(self.tmp, "launch")
        self.mod.writable_roots = lambda repo, cwd, launch=None: (
            seen.append(launch) or ([repo.toplevel, repo.main] if repo else []))
        code, out = self.run_pass("--print")
        self.assertEqual(code, 0, out)
        self.assertIn(launch, seen)

    def test_deny_write_carves_out_only_from_the_user_and_managed_tiers(self):
        managed = os.path.join(self.tmp, "managed-settings.json")
        self.mod.MANAGED_SETTINGS = managed
        self.settings(os.path.join(self.home, ".claude", "settings.json"),
                      sandbox={"filesystem": {"denyWrite": ["~/dw"]}})
        self.settings(managed, sandbox={"filesystem": {"denyWrite": ["/mdw"]}})
        self.settings(os.path.join(self.main, ".claude", "settings.json"),
                      sandbox={"filesystem": {"denyWrite": ["/projdw"]}})
        denies = self.mod.deny_roots()
        self.assertIn(os.path.join(self.home, "dw"), denies)
        self.assertIn("/mdw", denies)
        self.assertNotIn("/projdw", denies)

    def test_the_script_under_a_writable_root_refuses(self):
        self.mod.writable_roots = lambda repo, cwd, launch=None: [REPO]
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn("pass-respawn resolves to", out)
        self.assertIn("outcome=refused", self.log())
        # A denyWrite over it (the user tier's ~/dotclaude/skills) makes it safe again.
        self.mod.deny_roots = lambda: [os.path.join(REPO, "skills")]
        code, out = self.run_pass("--print")
        self.assertEqual(code, 0, out)

    def test_an_invoked_link_in_a_writable_dir_refuses(self):
        wlink = os.path.join(self.tmp, "wlink")
        os.makedirs(wlink)
        os.symlink(SCRIPT, os.path.join(wlink, "pass-respawn"))
        self.mod.INVOKED = os.path.join(wlink, "pass-respawn")
        self.mod.writable_roots = lambda repo, cwd, launch=None: [wlink]
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn(f"pass-respawn resolves to {wlink}/pass-respawn", out)

    def test_handoff_check_under_a_writable_root_refuses(self):
        where = os.path.dirname(os.path.realpath(self.mod.HANDOFF_CHECK))
        self.mod.writable_roots = lambda repo, cwd, launch=None: [where]
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn("handoff-check resolves to", out)


# ---- 2. a pinned PATH for every child ----------------------------------------------------------

PLANT = "#!/bin/sh\necho {name} >> \"{marker}\"\nexit 0\n"


class PinnedPath(Plain):
    def test_writable_path_entries_never_reach_a_child(self):
        wbin = os.path.join(self.tmp, "wbin")
        marker = os.path.join(self.tmp, "planted.log")
        for name in ("git", "tmux", "claude"):
            self.write(os.path.join(wbin, name), PLANT.format(name=name, marker=marker))
            os.chmod(os.path.join(wbin, name), 0o755)
        os.environ["PATH"] = wbin + os.pathsep + os.environ["PATH"]
        self.mod.writable_roots = lambda repo, cwd, launch=None: (
            [repo.toplevel, repo.main, wbin] if repo else [wbin])
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        (respawn,) = self.calls("tmux", "respawn-pane")
        self.assertEqual(respawn[8], self.claude)
        self.assertFalse(os.path.exists(marker), "a planted binary ran")
        with open(self.tmux_log + ".path") as f:
            paths = f.read().splitlines()
        self.assertTrue(paths)
        for p in paths:
            self.assertNotIn(wbin, p.split(os.pathsep))

    def test_safe_path_drops_relative_empty_and_writable_entries(self):
        got = self.mod.safe_path(os.pathsep.join(["rel", "", "/w/bin", "/ok/bin", "/w/deny/bin"]),
                                 ["/w"], ["/w/deny"])
        self.assertEqual(got, os.pathsep.join(["/ok/bin", "/w/deny/bin"]))

    def test_the_interpreter_is_pinned_and_isolated(self):
        with open(SCRIPT) as f:
            first = f.readline()
        self.assertEqual(first, "#!/usr/bin/python3 -I\n")
        self.assertIn("/usr/bin/python3 -I", self.mod.__doc__)
        self.assertIn("PYTHONPATH", self.mod.__doc__)

    def plant_argparse(self):
        """A dir on PYTHONPATH holding an argparse.py that leaves a marker when imported."""
        planted, marker = os.path.join(self.tmp, "pyplant"), os.path.join(self.tmp, "imported")
        self.write(os.path.join(planted, "argparse.py"),
                   f"open({marker!r}, 'w').close()\nraise SystemExit(7)\n")
        os.environ["PYTHONPATH"] = planted
        return marker

    def test_pythonpath_never_reaches_the_script(self):
        marker = self.plant_argparse()
        p = subprocess.run([SCRIPT, "--help"], capture_output=True, text=True, env=os.environ)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(os.path.exists(marker), "a PYTHONPATH module ran in pass-respawn")

    def test_pythonpath_never_reaches_handoff_check(self):
        marker = self.plant_argparse()
        code, out = self.mod.gate(self.main, os.environ["PATH"])
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(marker), "a PYTHONPATH module ran in handoff-check")

    def test_handoff_check_still_runs_under_dash_i(self):
        p = subprocess.run([sys.executable, "-I", self.mod.HANDOFF_CHECK, "-C", self.main],
                           capture_output=True, text=True, env=os.environ)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


    def test_a_waiter_run_through_the_dash_i_shebang_is_recognised(self):
        # The kernel runs `#!/usr/bin/python3 -I` as python3 -I <script> ...: the script is argv[2].
        procdir = os.path.join(self.tmp, "proc")
        for pid, argv in ((10, ["/usr/bin/python3", "-I", SCRIPT, "-C", "/x"]),
                          (11, [SCRIPT, "--compact"]),
                          (12, ["/usr/bin/python3", "-I", "/elsewhere/other", "pass-respawn"]),
                          (13, ["/usr/bin/python3", "-c", "pass-respawn"])):
            self.write(os.path.join(procdir, str(pid), "cmdline"), "\0".join(argv) + "\0")
        self.assertEqual(self.mod.proc_cmdline(10, procdir),
                         ["/usr/bin/python3", "-I", SCRIPT, "-C", "/x"])
        self.assertIsNone(self.mod.proc_cmdline(99, procdir))
        got = {pid: self.mod.is_pass_respawn(pid, procdir) for pid in (10, 11, 12, 13, 99)}
        self.assertEqual(got, {10: True, 11: True, 12: False, 13: False, 99: False})

# ---- 3. any background task blocks a plain pass ------------------------------------------------

class Tasks(Plain):
    def test_any_task_but_dream_drops_busy(self):
        for tasks in (["monitor"], ["teammate"], ["some-new-kind"], ["unlabeled"], [None],
                      ["dream", "monitor"]):
            with self.subTest(tasks=tasks):
                self.reset()
                self.clear_log()
                self.stop_tasks = tasks
                self.assertEqual(self.mod.wait_and_act(self.plan(), t.table), "busy")
                self.assertDropped("busy", "background work")

    def test_dream_alone_does_not_block(self):
        self.stop_tasks = ["dream"]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls("tmux", "respawn-pane")), 1)


# ---- 4. the input box and copy mode ------------------------------------------------------------

class InputBox(Plain):
    def test_the_parser(self):
        box = self.mod.input_box
        ghost = f"{ESC}[2myes{ESC}[0m"
        self.assertEqual(box(t.EMPTY_BOX), "")
        self.assertEqual(box(t.screen("my unsent draft")), "my unsent draft")
        self.assertEqual(box(t.screen(ghost)), "")
        self.assertEqual(box(t.screen("my " + ghost)), "my")
        self.assertIsNone(box("just a reply\nno box here\n"))
        self.assertIsNone(box(""))
        # dim ends at SGR 22 too; a 256-colour 2 is a colour, not dim
        self.assertEqual(box(t.screen(f"{ESC}[2mghost{ESC}[22m real")), "real")
        self.assertEqual(box(t.screen(f"{ESC}[38;5;2mgreen")), "green")
        # a wrapped draft: its later lines sit under the prompt line, above the rule
        lines = t.EMPTY_BOX.split("\n")
        lines.insert(3, "second line")
        self.assertEqual(box("\n".join(lines)), "second line")
        # the last prompt line counts: an earlier one in the reply is not the box
        self.assertEqual(box(f"{MARK}{NBSP} quoted text\n" + t.EMPTY_BOX), "")

    def run_both(self, words):
        for mode in ((), ("--compact",)):
            with self.subTest(mode=mode):
                self.reset()
                self.clear_log()
                self.assertEqual(self.mod.wait_and_act(self.plan(*mode), t.table), "busy")
                self.assertDropped("busy", "pass dropped")
                self.assertIn(words, self.log())
                self.assertFalse(os.path.exists(self.carry_marker()))

    def test_copy_mode_drops_busy_in_both_modes(self):
        os.environ["FAKE_TMUX_MODE"] = "1"
        self.run_both("busy: pane in copy mode")

    def test_a_draft_drops_busy_in_both_modes(self):
        os.environ["FAKE_TMUX_SCREEN"] = t.screen("my unsent draft")
        self.run_both("busy: unsent draft in the input box")

    def test_no_input_box_drops_busy_in_both_modes(self):
        os.environ["FAKE_TMUX_SCREEN"] = "a full-screen dialog"
        self.run_both("busy: no input box")
        os.environ["FAKE_TMUX_SCREEN"] = t.EMPTY_BOX
        os.environ["FAKE_TMUX_FAIL"] = "capture-pane"
        self.run_both("busy: no input box")

    def test_a_ghost_suggestion_is_not_a_draft(self):
        os.environ["FAKE_TMUX_SCREEN"] = t.screen(f"{ESC}[2myes{ESC}[0m")
        code, out = self.run_pass("--compact", "--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls("tmux", "send-keys")), 4)

    def test_a_failed_send_keys_logs_failed(self):
        os.environ["FAKE_TMUX_FAIL"] = "send-keys"
        code, out = self.run_pass("--compact", "--foreground")
        self.assertEqual(code, 1, out)
        self.assertEqual(len(self.calls("tmux", "send-keys")), 1)
        self.assertIn("mode=compact outcome=failed", self.log())
        self.assertNotIn("outcome=compact", self.log())


    def test_a_pane_problem_in_the_compact_gap_leaves_the_prompt_to_hayden(self):
        # /compact went in; then copy mode or a draft shows up during COMPACT_GAP. Typing the
        # resume prompt would scroll the pane or join the draft, so it is shown, not typed.
        real = self.mod.tmux
        for env, value, words in (("FAKE_TMUX_MODE", "1", "pane in copy mode"),
                                  ("FAKE_TMUX_SCREEN", t.screen("my draft"),
                                   "unsent draft in the input box")):
            with self.subTest(words=words):
                self.reset()
                self.clear_log()
                os.environ.update(FAKE_TMUX_MODE="0", FAKE_TMUX_SCREEN=t.EMPTY_BOX)

                def tmux(plan, *args, env=env, value=value):
                    p = real(plan, *args)
                    if args[:1] == ("send-keys",) and args[-1] == "Enter":
                        os.environ[env] = value  # it appears right after /compact's Enter
                    return p
                self.mod.tmux = tmux
                self.assertEqual(self.mod.wait_and_act(self.plan("--compact"), t.table),
                                 "partial")
                self.mod.tmux = real
                keys = [a[-1] for a in self.calls("tmux", "send-keys")]
                self.assertEqual(keys, [f"/compact {self.mod.compact_focus('STATUS.md')}",
                                        "Enter"])
                (msg,) = self.notices()
                self.assertEqual(msg[-1], "compacted; type the resume prompt yourself: "
                                 + self.PROMPT + " Call EnterPlanMode first.")
                self.assertIn("mode=compact outcome=partial", self.log())
                self.assertIn(words, self.log())
                self.assertNotIn("outcome=compact", self.log())

# ---- 5. prompts typed mid-turn and the transcript ----------------------------------------------

ENQUEUE = {"type": "queue-operation", "operation": "enqueue", "content": "wait, don't pass"}
REMOVE = {"type": "queue-operation", "operation": "remove"}
QUEUED = {"type": "attachment", "attachment": {"type": "queued_command",
                                               "prompt": "wait, don't pass",
                                               "origin": {"kind": "human"}, "humanTurn": True}}


class Transcript(Plain):
    def test_a_prompt_queued_mid_turn_drops_resumed(self):
        for entries in ((ENQUEUE, REMOVE, QUEUED), (ENQUEUE,), (QUEUED,)):
            for mode in ((), ("--compact",)):
                with self.subTest(entries=len(entries), mode=mode):
                    self.reset()
                    plan = self.plan(*mode)
                    self.say(*entries)
                    self.assertEqual(self.mod.wait_and_act(plan, t.table), "resumed")
                    self.assertEqual(self.calls("tmux", "respawn-pane"), [])
                    self.assertEqual(self.calls("tmux", "send-keys"), [])

    def test_a_queued_command_not_from_a_person_does_not_drop(self):
        plan = self.plan()
        notice = json.loads(json.dumps(QUEUED))
        notice["attachment"]["origin"] = {"kind": "task-notification"}
        self.say(REMOVE, notice)
        self.assertEqual(self.mod.wait_and_act(plan, t.table), "respawn")

    def test_the_stop_record_names_the_transcript(self):
        other = os.path.join(self.tmp, "elsewhere", f"{t.SID}.jsonl")
        self.write(other, json.dumps(t.typed("before")) + "\n")
        self.write(os.path.join(self.state, "stops", f"{t.SID}.json"),
                   json.dumps({"session_id": t.SID, "time": time.time() - 30, "waits": [],
                               "tasks": [], "transcript_path": other}))
        plan = self.plan()
        self.assertEqual(plan.transcript, other)
        with open(other, "a") as f:
            f.write(json.dumps(ENQUEUE) + "\n")
        self.assertEqual(self.mod.wait_and_act(plan, t.table), "resumed")

    def test_an_unreadable_transcript_drops_resumed(self):
        os.remove(self.transcript())
        for mode in ((), ("--compact",)):
            with self.subTest(mode=mode):
                self.reset()
                self.assertEqual(self.mod.wait_and_act(self.plan(*mode), t.table), "resumed")
                self.assertDropped("resumed", "pass dropped")
                self.assertIn("resumed: transcript unreadable", self.log())

    def test_typed_since_says_none_when_unreadable(self):
        self.assertIsNone(self.mod.typed_since(os.path.join(self.tmp, "none.jsonl"), 0))
        self.assertIsNone(self.mod.typed_since(None, 0))


# ---- compact mode drops ------------------------------------------------------------------------

class CompactDrops(Plain):
    def act(self):
        return self.mod.wait_and_act(self.plan("--compact"), t.table)

    def test_stale(self):
        plan = self.plan("--compact")
        self.write(os.path.join(self.main, "late.txt"), "x")
        self.assertEqual(self.mod.wait_and_act(plan, t.table), "stale")
        self.assertDropped("stale", "handoff is stale")

    def test_resumed_on_a_typed_or_a_queued_prompt(self):
        for entry in (t.typed("wait"), ENQUEUE):
            with self.subTest(entry=entry["type"]):
                self.reset()
                plan = self.plan("--compact")
                self.say(entry)
                self.assertEqual(self.mod.wait_and_act(plan, t.table), "resumed")
                self.assertEqual(self.calls("tmux", "send-keys"), [])

    def test_resumed_in_the_settle(self):
        self.script = ["busy", "idle", "busy"]
        self.assertEqual(self.act(), "resumed")
        self.assertDropped("resumed", "pass dropped")

    def test_gone(self):
        os.environ["FAKE_TMUX_PANE"] = f"{t.PANE_SHELL} zsh"
        self.assertEqual(self.act(), "gone")
        self.assertDropped("gone", "pass dropped")

    def test_timeout(self):
        self.script = ["busy"]
        plan = self.plan("--compact")
        plan.timeout = 0.3
        self.assertEqual(self.mod.wait_and_act(plan, t.table), "timeout")
        self.assertDropped("timeout", "pass dropped")


# ---- 6. approval dates -------------------------------------------------------------------------

class Approval(Plain):
    def test_a_future_marker_is_unapproved_at_act_time(self):
        plan = self.plan()
        future = t.TODAY + datetime.timedelta(days=1)
        self.write(os.path.join(self.main, "STATUS.md"), t.marked(t.GOOD, future))
        self.assertFalse(self.mod.approved_now(plan, {"startedAt": int(self.started * 1000)}))

    def test_a_future_marker_fails_the_gate(self):
        self.commit("STATUS.md", t.marked(t.GOOD, t.TODAY + datetime.timedelta(days=2)),
                    msg="Handoff")
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn("approval marker is dated in the future", out)

    def test_a_marker_with_an_unknown_session_start_is_unapproved(self):
        self.commit("STATUS.md", t.APPROVED, msg="Handoff")
        plan = self.plan()
        self.assertFalse(self.mod.approved_now(plan, {"startedAt": None}))
        self.assertFalse(self.mod.approved_now(plan, None))


# ---- 7. one pending pass per session -----------------------------------------------------------

class Pending(Plain):
    def setUp(self):
        super().setUp()
        self.mod.is_pass_respawn = lambda pid: True  # the waiter is a fork of the test runner

    def lock(self):
        return os.path.join(self.state, "pass-pending", f"{t.SID}.lock")

    def test_a_second_call_refuses_and_cancel_ends_the_first(self):
        self.script = ["busy"] * 5000
        code, out = self.run_pass("--compact")
        self.assertEqual(code, 0, out)
        self.reset("busy")
        code, out = self.run_pass("--compact")
        self.assertEqual(code, 1, out)
        self.assertIn("a pass is already pending", out)
        self.assertIn("--cancel", out)
        code, out = self.run_pass("--cancel")
        self.assertEqual(code, 0, out)
        self.wait_log("mode=compact outcome=cancelled")
        self.assertEqual(self.calls("tmux", "send-keys"), [])
        # The lock is free again: a fresh call is accepted.
        self.reset()
        code, out = self.run_pass("--compact", "--foreground")
        self.assertEqual(code, 0, out)

    def test_cancel_with_nothing_pending(self):
        code, out = self.run_pass("--cancel")
        self.assertEqual(code, 0, out)
        self.assertIn("no pass pending", out)

    def test_cancel_refuses_a_pid_whose_start_does_not_match(self):
        sleeper = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        os.makedirs(os.path.dirname(self.lock()), exist_ok=True)
        fd = os.open(self.lock(), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, f"{sleeper.pid} 1\n".encode())
        code, out = self.run_pass("--cancel")
        self.assertEqual(code, 1, out)
        self.assertIn("doesn't match", out)
        time.sleep(0.2)
        self.assertIsNone(sleeper.poll())

    def test_a_foreground_run_holds_then_frees_the_lock(self):
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.reset()
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    import unittest
    unittest.main()
