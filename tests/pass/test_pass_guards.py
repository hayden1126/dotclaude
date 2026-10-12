"""skills/pass/scripts/pass-respawn, the second review's guards: the full set of sandbox-writable
roots and the script's own location, a PATH pinned for every child, any background task, the
input box and copy mode, prompts typed mid-turn, approval dates and one pending pass per session.

Each test reuses test_pass_respawn's fixture (Base): fakes for tmux, the session file, /proc and
the transcript, under a temp HOME and XDG_STATE_HOME. Nothing reaches the live tmux server or the
real ~/.claude."""
import contextlib
import datetime
import fcntl
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

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
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: (
            seen.append(launch) or ([repo.toplevel, repo.main] if repo else []))
        code, out = self.run_pass("--print")
        self.assertEqual(code, 0, out)
        self.assertIn(launch, seen)

    def test_the_sessions_own_add_dir_and_settings_flags_count(self):
        launch = os.path.join(self.tmp, "launch")
        flagged = os.path.join(self.tmp, "flagged.json")
        self.settings(flagged, sandbox={"filesystem": {"allowWrite": ["/flag-w"]}},
                      permissions={"additionalDirectories": ["/flag-add"]})
        other = os.path.join(launch, "other.json")
        self.settings(other, sandbox={"filesystem": {"allowWrite": ["/eq-w"]}})
        inline = json.dumps({"permissions": {"additionalDirectories": ["/inline-add"]}})
        argv = ["claude", "--add-dir", "/ad1", "/ad2", "--model", "opus", "--add-dir=/ad3",
                "--add-dir", "rel", "--settings", flagged, "--settings=other.json",
                "--settings", inline, "the prompt"]
        import lanelib
        roots = self.real_roots(lanelib.resolve(self.main), self.main, launch, argv)
        for want in ("/ad1", "/ad2", "/ad3", os.path.join(launch, "rel"), "/flag-w",
                     "/flag-add", "/eq-w", "/inline-add"):
            self.assertIn(want, roots)
        self.assertNotIn("/opus", roots)
        self.assertNotIn(os.path.join(launch, "opus"), roots)
        # Before git has run, too; and no argv (an unreadable cmdline) adds nothing.
        self.assertIn("/ad3", self.real_roots(None, self.main, launch, argv))
        self.assertEqual(self.real_roots(None, self.main, launch, None),
                         self.real_roots(None, self.main, launch))

    def test_the_call_reads_the_sessions_cmdline(self):
        seen, asked = [], []
        argv = ["claude", "--add-dir", "/ad1"]
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: (
            seen.append(session_argv) or ([repo.toplevel, repo.main] if repo else []))

        def cmdline(pid):
            asked.append(pid)
            return argv
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self.mod.main(["--print", "-C", self.main], procs=t.table, cmdline=cmdline)
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(asked, [t.CLAUDE])
        self.assertEqual(seen, [argv, argv])

    def test_a_sandbox_writable_settings_flag_file_refuses(self):
        # Its allowWrite was read at launch; edited since, it could hide a writable dir.
        writable = os.path.join(self.tmp, "w")
        flagged = os.path.join(writable, "flags.json")
        self.settings(flagged, sandbox={"filesystem": {"allowWrite": []}})
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: (
            [repo.toplevel, repo.main, writable] if repo else [writable])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self.mod.main(["--print", "-C", self.main], procs=t.table,
                                 cmdline=lambda pid: ["claude", "--settings", flagged])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("a --settings file resolves to", out.getvalue())

    def logging_git(self):
        """A fake git first on PATH that logs each call, then runs the real one; its log path."""
        real, log = shutil.which("git"), os.path.join(self.tmp, "git.log")
        path = os.path.join(self.fake_bin, "git")
        with open(path, "w") as f:
            f.write(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {log}\nexec {real} "$@"\n')
        os.chmod(path, 0o755)
        return log

    def test_a_writable_settings_file_refuses_before_git_or_tmux_runs(self):
        # The file may hide a writable dir holding a planted git, so the refusal must come
        # before any binary resolved from PATH runs: before lanelib.resolve's git.
        writable = os.path.join(self.tmp, "w")
        flagged = os.path.join(writable, "flags.json")
        self.settings(flagged, sandbox={"filesystem": {"allowWrite": []}})
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: (
            [repo.toplevel, repo.main, writable] if repo else [writable])
        git_log = self.logging_git()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self.mod.main(["--print", "-C", self.main], procs=t.table,
                                 cmdline=lambda pid: ["claude", "--settings", flagged])
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("a --settings file resolves to", out.getvalue())
        self.assertFalse(os.path.exists(git_log), open(git_log).read()
                         if os.path.exists(git_log) else "")
        self.assertEqual(self.calls("tmux"), [])

    def test_no_claude_refuses_before_git_runs(self):
        # Without its claude the session's launch flags can't be read, so the roots are short:
        # nothing may run sandbox-off first.
        git_log = self.logging_git()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self.mod.main(["--print", "-C", self.main],
                                 procs=lambda: t.table(claude=False))
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("can't find this session's claude", out.getvalue())
        self.assertFalse(os.path.exists(git_log))

    def test_session_flags_past_a_double_dash_still_count(self):
        # Claude Code's parser can take `--` as an option's value and parse a later --settings,
        # so the scan goes past it: a false hit only refuses more, or adds a root.
        writable = os.path.join(self.tmp, "w")
        flagged = os.path.join(writable, "flags.json")
        self.settings(flagged, sandbox={"filesystem": {"allowWrite": []}})
        argv = ["claude", "--append-system-prompt", "--", "--settings", flagged,
                "--add-dir", "/past-dd"]
        self.assertEqual(self.mod.session_flags(argv), (["/past-dd"], [flagged]))
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: (
            [repo.toplevel, repo.main, writable] if repo else [writable])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self.mod.main(["--print", "-C", self.main], procs=t.table,
                                 cmdline=lambda pid: argv)
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("a --settings file resolves to", out.getvalue())

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
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: [REPO]
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
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: [wlink]
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn(f"pass-respawn resolves to {wlink}/pass-respawn", out)

    def test_handoff_check_under_a_writable_root_refuses(self):
        where = os.path.dirname(os.path.realpath(self.mod.HANDOFF_CHECK))
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: [where]
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
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: (
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
        for tasks, shown in ((["monitor"], "1 monitor"), (["teammate"], "1 teammate"),
                             (["some-new-kind"], "1 some-new-kind"),
                             (["unlabeled"], "1 unlabeled task"), ([None], "1 unlabeled task"),
                             (["dream", "monitor"], "1 monitor")):
            with self.subTest(tasks=tasks):
                self.reset()
                self.clear_log()
                self.stop_tasks = tasks
                self.assertEqual(self.mod.wait_and_act(self.plan(), t.table), "busy")
                self.assertDropped("busy", f"pass refused in tab 3: {shown} running (a respawn "
                                           "would kill it). /pass compact keeps it, or stop it "
                                           "and /pass")

    def test_the_busy_notice_counts_and_names_the_tasks(self):
        # Live, 2026-10-12: three monitors at the Stop, and the log said `waits:` though the
        # record's waits were empty. The notice counts each label; the log says `tasks:`.
        self.stop_tasks = ["monitor", "dream", "monitor", "teammate", "monitor"]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", "pass refused in tab 3: 3 monitors, 1 teammate running (a "
                                   "respawn would kill them). /pass compact keeps them, or stop "
                                   "them and /pass")
        self.assertIn("outcome=busy busy: tasks: monitor, monitor, teammate, monitor",
                      self.log())
        self.assertNotIn("waits:", self.log())

    def test_real_waits_keep_the_waits_label(self):
        self.stop_waits = ["shell", "subagent", "shell"]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", "waiting on 2 shells, 1 subagent (a respawn would kill "
                                   "them). /pass compact keeps them, or let them finish")
        self.assertIn("outcome=busy busy: waits: shell, subagent, shell", self.log())

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
                                   "unsent draft in the input box"),
                                  ("FAKE_TMUX_SCREEN", "a dialog, no box", "no input box")):
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
                # It stays on the status line until a key press (-d 0), and says the compact
                # was sent, not confirmed; pass.log keeps the whole prompt.
                prompt = self.PROMPT + " Call EnterPlanMode first."
                self.assertLoud(f"pass in tab 3: /compact sent; type the resume prompt "
                                f"yourself: {prompt}")
                self.assertTrue(all(m[-1].endswith(prompt) for m in self.notices()))
                (line,) = [ln for ln in self.log().splitlines() if "outcome=partial" in ln]
                self.assertIn("mode=compact outcome=partial", line)
                self.assertIn(words, line)
                self.assertTrue(line.endswith(f"resume prompt: {prompt}"), line)
                self.assertNotIn("outcome=compact", self.log())

PARTIAL_WORDS = ("copy mode", "a draft", "no input box", "key press", "pass.log")


def partial_gaps(text):
    """The words PARTIAL_WORDS a doc's `partial` passage lacks: SKILL.md's table row and step 6,
    or the README's sentence. The passage is the paragraph (or row) that names `partial`."""
    passages = [p for p in re.split(r"\n(?=\| |\d+\. |- )|\n\n", text) if "`partial`" in p]
    return [(p.strip()[:40], w) for p in passages for w in PARTIAL_WORDS if w not in p] or (
        [] if passages else [("no passage", "`partial`")])


class LimitDocs(unittest.TestCase):
    def test_the_docstring_names_the_overwritten_process_title_limit(self):
        doc = " ".join(t.load().__doc__.split())
        for words in ("npm install may overwrite its process title", "2.1.296",
                      "launched with no flags"):
            self.assertIn(words, doc)


class PartialDocs(unittest.TestCase):
    def test_the_docs_name_every_cause_of_partial_and_where_the_prompt_stays(self):
        for rel in ("skills/pass/SKILL.md", "README.md"):
            with self.subTest(doc=rel), open(os.path.join(REPO, rel)) as f:
                self.assertEqual(partial_gaps(f.read()), [])


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

    def test_a_malformed_attachment_entry_is_skipped(self):
        path = os.path.join(self.tmp, "malformed.jsonl")
        bad = ({"type": "attachment"}, {"type": "attachment", "attachment": None},
               {"type": "attachment", "attachment": "queued_command"},
               {"type": "attachment", "attachment": ["queued_command"]},
               {"type": "attachment", "attachment": {"type": "queued_command", "origin": "human"}},
               [1, 2], 7, None)
        self.write(path, "".join(json.dumps(e) + "\n" for e in bad))
        self.assertFalse(self.mod.typed_since(path, 0))
        for entry in bad:
            self.assertFalse(self.mod.queued_prompt(entry))
            self.assertFalse(self.mod.typed_prompt(entry))
        plan = self.plan()
        self.say(*bad)
        self.assertEqual(self.mod.wait_and_act(plan, t.table), "respawn")

    def test_a_bang_command_is_not_a_typed_prompt(self):
        # `!ls` in Claude Code writes user entries holding <bash-input> and <bash-stdout> blocks,
        # with no origin kind human (live runs): Hayden ran a command, he didn't prompt.
        plan = self.plan()
        bang = ({"type": "user", "message": {"role": "user",
                                             "content": "<bash-input>ls -la</bash-input>"}},
                {"type": "user", "message": {"role": "user", "content": [
                    {"type": "text", "text": "<bash-stdout>total 0</bash-stdout>"
                                             "<bash-stderr></bash-stderr>"}]}})
        for entry in bang:
            self.assertFalse(self.mod.typed_prompt(entry))
        self.say(*bang)
        self.assertEqual(self.mod.wait_and_act(plan, t.table), "respawn")


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
        # A no-op isn't a cancel: grepping pass.log for cancels finds only real ones.
        self.assertIn("mode=cancel outcome=none", self.log())
        self.assertNotIn("outcome=cancelled", self.log())

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

    def test_cancel_waits_for_a_waiter_that_hasnt_written_its_pid_yet(self):
        # The call takes the lock and the grandchild writes its pid a moment later: a cancel in
        # that gap must wait for the line, not refuse an empty one.
        sleeper = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        os.makedirs(os.path.dirname(self.lock()), exist_ok=True)
        fd = os.open(self.lock(), os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        start = self.mod.proc_start(sleeper.pid)

        def late_waiter():
            time.sleep(0.4)
            os.write(fd, f"{sleeper.pid} {start}\n".encode())
            sleeper.wait()
            fcntl.flock(fd, fcntl.LOCK_UN)
        th = threading.Thread(target=late_waiter, daemon=True)
        th.start()
        code, out = self.run_pass("--cancel")
        th.join(5)
        self.assertEqual(code, 0, out)
        self.assertIn("cancelled the pending pass", out)
        self.assertIsNotNone(sleeper.poll())

    def term_during(self, action, *mode):
        """A foreground run that gets SIGTERM (as --cancel sends) right after tmux runs action;
        returns (exit code, the lock's text when action ran)."""
        real, seen = self.mod.tmux, []

        def tmux(plan, *args):
            p = real(plan, *args)
            if args[0] == action and not seen:
                with open(self.lock()) as f:
                    seen.append(f.read())
                os.kill(os.getpid(), signal.SIGTERM)
            return p
        self.mod.tmux = tmux
        code, out = self.run_pass(*mode, "--foreground")
        self.assertEqual(len(seen), 1, out)
        return code, seen[0]

    def test_a_cancel_after_the_respawn_ran_keeps_the_respawn_and_its_carry(self):
        code, lock = self.term_during("respawn-pane")
        self.assertEqual(code, 0)
        self.assertTrue(lock.rstrip().endswith(" acting"), lock)
        self.assertEqual(len(self.calls("tmux", "respawn-pane")), 1)
        self.assertTrue(os.path.exists(self.carry_marker()))
        self.assertIn("mode=plain outcome=respawn", self.log())
        self.assertIn("a --cancel came after acting began", self.log())
        self.assertNotIn("outcome=cancelled", self.log())

    def test_a_cancel_mid_compact_finishes_the_compact(self):
        code, _ = self.term_during("send-keys", "--compact")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls("tmux", "send-keys")), 4)
        self.assertIn("mode=compact outcome=compact", self.log())
        self.assertIn("a --cancel came after acting began", self.log())
        self.assertNotIn("outcome=cancelled", self.log())

    def test_a_cancel_before_acting_still_cancels(self):
        code, _ = self.term_during("capture-pane")  # the final re-check's pane read
        self.assertEqual(code, 1)
        self.assertEqual(self.calls("tmux", "respawn-pane"), [])
        self.assertFalse(os.path.exists(self.carry_marker()))
        self.assertIn("mode=plain outcome=cancelled", self.log())

    def hold_lock(self, acting):
        os.makedirs(os.path.dirname(self.lock()), exist_ok=True)
        fd = os.open(self.lock(), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        start = self.mod.proc_start(os.getpid())
        os.write(fd, f"{os.getpid()} {start}{' acting' if acting else ''}\n".encode())
        return fd

    def catch_term(self):
        got = []
        old = signal.signal(signal.SIGTERM, lambda *a: got.append(1))
        self.addCleanup(signal.signal, signal.SIGTERM, old)
        return got

    def test_cancel_once_the_waiter_acts_says_too_late(self):
        got = self.catch_term()
        fd = self.hold_lock(acting=True)
        self.addCleanup(os.close, fd)
        code, out = self.run_pass("--cancel")
        self.assertEqual(code, 1, out)
        self.assertIn("too late", out)
        self.assertEqual(got, [], "it signalled a waiter that was already acting")
        self.assertIn("mode=cancel outcome=too-late", self.log())

    def test_cancel_that_races_the_act_says_too_late(self):
        # The waiter begins acting between --cancel's read and its signal: SIGTERM is ignored,
        # the act finishes and frees the lock, and --cancel reads the mark again.
        self.catch_term()
        fd = self.hold_lock(acting=False)

        def kill(pid, sig):
            os.pwrite(fd, f"{os.getpid()} {self.mod.proc_start(os.getpid())} acting\n".encode(), 0)
            os.close(fd)
        with mock.patch.object(self.mod.os, "kill", side_effect=kill):
            code, out = self.run_pass("--cancel")
        self.assertEqual(code, 1, out)
        self.assertIn("too late", out)
        self.assertIn("mode=cancel outcome=too-late", self.log())
        self.assertNotIn("outcome=cancelled", self.log())

    def end_lock(self, fd, marks):
        """The waiter's last write and its exit: the lock's line gains marks, then it frees."""
        os.pwrite(fd, f"{os.getpid()} {self.mod.proc_start(os.getpid())} {marks}\n".encode(), 0)
        os.close(fd)

    def test_cancel_that_misses_an_act_that_already_ended_says_too_late(self):
        # The waiter acts, finishes and exits between --cancel's read of the lock and its pid
        # check: the pid no longer matches, but the freed lock says it acted.
        fd = self.hold_lock(acting=False)

        def gone(pid):
            self.end_lock(fd, "acting done:respawn")
            return False
        self.mod.is_pass_respawn = gone
        code, out = self.run_pass("--cancel")
        self.assertEqual(code, 1, out)
        self.assertIn("too late", out)
        self.assertNotIn("doesn't match", out)
        self.assertIn("mode=cancel outcome=too-late", self.log())
        self.assertNotIn("outcome=refused", self.log())

    def test_cancel_whose_waiter_is_gone_at_the_signal_says_too_late(self):
        fd = self.hold_lock(acting=False)

        def kill(pid, sig):
            self.end_lock(fd, "acting done:compact")
            raise ProcessLookupError(3, "No such process")
        with mock.patch.object(self.mod.os, "kill", side_effect=kill):
            code, out = self.run_pass("--cancel")
        self.assertEqual(code, 1, out)
        self.assertIn("too late to cancel (compact)", out)
        self.assertIn("mode=cancel outcome=too-late", self.log())
        self.assertNotIn("outcome=cancelled", self.log())

    def test_cancel_after_the_waiters_own_drop_says_too_late(self):
        # The waiter dropped (stale) and, its handler restored, the SIGTERM only ended it:
        # --cancel reports that drop, and logs no second, false `cancelled`.
        self.catch_term()
        fd = self.hold_lock(acting=False)
        with mock.patch.object(self.mod.os, "kill",
                               side_effect=lambda pid, sig: self.end_lock(fd, "done:stale")):
            code, out = self.run_pass("--cancel")
        self.assertEqual(code, 1, out)
        self.assertIn("too late to cancel (stale)", out)
        self.assertNotIn("cancelled the pending pass", out)
        self.assertIn("mode=cancel outcome=too-late", self.log())
        self.assertNotIn("outcome=cancelled", self.log())

    def test_the_waiter_records_its_outcome_in_the_lock(self):
        def marks():
            with open(self.lock()) as f:
                return f.read().split()[2:]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual(marks(), ["acting", "done:respawn"])
        self.reset()
        self.stop_waits = ["shell"]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertEqual(marks(), ["done:busy"])
        self.reset()
        self.stop_waits = []
        self.term_during("capture-pane")
        self.assertEqual(marks(), ["done:cancelled"])

    def test_a_foreground_run_holds_then_frees_the_lock(self):
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.reset()
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)

    def test_a_cancel_stays_quiet(self):
        # Cancelled on purpose: the brief status-line line as before, no held notice, no toast.
        code, _ = self.term_during("capture-pane")
        self.assertEqual(code, 1)
        self.assertIn("mode=plain outcome=cancelled", self.log())
        self.assertDropped("cancelled", "pass cancelled")
        self.assertEqual(self.toasts(), [])


# ---- 8. a loud refusal -------------------------------------------------------------------------

class LoudNotice(Plain):
    LOUD = ("stale", "resumed", "busy", "gone", "timeout", "failed", "error")

    def test_every_drop_but_cancelled_is_loud_and_keeps_its_log_word(self):
        self.assertEqual(set(self.mod.DROPS) - self.mod.QUIET, set(self.LOUD))
        for outcome in self.LOUD:
            with self.subTest(outcome=outcome):
                self.reset()
                self.clear_log()
                plan = self.plan()
                self.assertEqual(self.mod.drop(plan, outcome, "some detail"), outcome)
                head, _, tail = self.mod.DROPS[outcome].partition(": ")
                self.assertLoud(f"{head} in tab 3: {tail}")
                self.assertTrue(plan.settled)
                (line,) = self.log().splitlines()
                self.assertRegex(line, rf" session={t.SID} pane=%4 mode=plain "
                                       rf"outcome={outcome} some detail$")
        self.reset()
        self.clear_log()
        self.mod.drop(self.plan(), "cancelled", "on SIGTERM")
        self.assertEqual([m[1:] for m in self.notices()],
                         [["display-message", "-t", "%4", "pass cancelled"]])
        self.assertIn("outcome=cancelled on SIGTERM", self.log())
        self.assertEqual(self.toasts(), [])

    def test_every_loud_text_names_a_fix(self):
        for outcome in self.LOUD:
            with self.subTest(outcome=outcome):
                self.assertIn("/pass", self.mod.DROPS[outcome])
        for why, fix in self.mod.PANE_FIXES.items():
            with self.subTest(why=why):
                self.assertIn("/pass", fix)

    def test_the_call_resolves_the_toast_as_notify_sh_runs_it(self):
        plan = self.plan()
        self.assertEqual(plan.toast, [os.path.join(self.fake_bin, "powershell.exe"),
                                      "-ExecutionPolicy", "Bypass", "-File", t.WINPATH,
                                      "-Message"])

    def busy_run(self):
        """A plain pass a monitor refuses: (exit code, output)."""
        self.stop_tasks = ["monitor"]
        return self.run_pass("--foreground")

    def test_a_failing_or_missing_toast_changes_neither_the_outcome_nor_the_exit_code(self):
        real_run = self.mod.subprocess.run

        def no_shell(argv, *a, **kw):
            if argv[0] == "/bin/sh":
                raise OSError("no /bin/sh")
            return real_run(argv, *a, **kw)
        ps1 = os.path.join(self.home, ".claude", "notify-toast.ps1")
        powershell = os.path.join(self.fake_bin, "powershell.exe")
        wslpath = os.path.join(self.fake_bin, "wslpath")
        cases = (("the toast exits 1", lambda: os.environ.update(FAKE_TOAST_EXIT="1"), True),
                 ("no /bin/sh", lambda: setattr(self.mod.subprocess, "run", no_shell), False),
                 ("no notify-toast.ps1", lambda: os.rename(ps1, ps1 + ".gone"), False),
                 ("no powershell.exe", lambda: os.rename(powershell, powershell + ".gone"),
                  False),
                 ("wslpath fails", lambda: self.write(wslpath, "#!/bin/sh\nexit 1\n"), False))
        for name, breakit, sent in cases:
            with self.subTest(name), mock.patch.object(self.mod.subprocess, "run", real_run):
                self.reset()
                self.clear_log()
                breakit()
                code, out = self.busy_run()
                self.assertEqual(code, 1, out)
                self.assertIn("mode=plain outcome=busy busy: tasks: monitor", self.log())
                self.assertNotIn("outcome=error", self.log())
                self.assertLoud("pass refused in tab 3: 1 monitor running", toast=sent)
                if not sent:
                    self.assertEqual(self.toasts(), [])

    def test_with_no_client_attached_tmux_picks_one(self):
        # Hayden switched his only terminal to another session: no client of the pane's session.
        os.environ["FAKE_TMUX_CLIENTS"] = ""
        code, out = self.busy_run()
        self.assertEqual(code, 1, out)
        (msg,) = self.notices()
        self.assertEqual(msg[1:5], ["display-message", "-d", "0", "-t"])
        self.assertNotIn("-c", msg)
        self.assertIn("1 monitor running", self.toasts()[0][-1])

    def test_a_label_is_shown_not_expanded_as_a_format(self):
        self.stop_tasks = ["mon#{pane_id}"]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        for m in self.notices():
            self.assertIn("1 mon##{pane_id} running", m[-1])
        self.assertIn("1 mon#{pane_id} running", self.toasts()[0][-1])

    def test_a_pane_problem_names_its_fix(self):
        os.environ["FAKE_TMUX_MODE"] = "1"
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertLoud("pass dropped in tab 3: pane in copy mode. Leave copy mode (q), then "
                        "/pass")
        self.assertIn("outcome=busy busy: pane in copy mode", self.log())


class SkillLeftovers(unittest.TestCase):
    """skills/pass/SKILL.md: the model stops leftover tasks, or picks compact, before the plain
    pass's pass-respawn call, and its reply never promises a restart."""

    def setUp(self):
        with open(os.path.join(REPO, "skills", "pass", "SKILL.md")) as f:
            self.text = f.read()

    def test_leftovers_are_stopped_before_the_plain_mode_call(self):
        call = self.text.index("Run `pass-respawn -C <toplevel>`")
        before = self.text[:call]
        for words in ("TaskStop", "a Monitor too", "use compact mode instead",
                      "background Bash", "teammates"):
            self.assertIn(words, before)

    def test_the_reply_never_promises_a_restart(self):
        self.assertIn("The pane restarts after this turn unless the gate refuses (you'd see a "
                      "notice that stays until a key).", self.text)
        self.assertNotIn("When this turn ends, the pane restarts", self.text)


if __name__ == "__main__":
    import unittest
    unittest.main()
