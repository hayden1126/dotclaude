"""hooks/tmux-state.sh, hooks/stop-ring.sh and hooks/notify.sh: which tmux window a session's
state lands on, and which sessions ring (stdlib only).

A session is in view when a person sees it: a tmux tab, a plain terminal, or a background
session attached to a tab. A background session's own environment has no TMUX_PANE (the daemon
hosts it), so its pane is found by walking its process ancestry to a pane's shell. A `claude -p`
run inherits the tab's TMUX_PANE but marks itself CLAUDE_CODE_SESSION_ATTENDED=0; it writes no
tab state and never rings. Stubs for tmux, powershell.exe and wslpath record every call."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, "hooks")

STUB = """#!/usr/bin/env bash
printf '%s\\n' "$(basename "$0") $*" >> "$STUB_LOG"
case "$(basename "$0") $1" in
  "tmux list-panes") printf '%s\\n' "$STUB_PANES" ;;
  "wslpath -w") printf 'C:\\\\stub\\\\%s\\n' "$(basename "$2")" ;;
esac
exit 0
"""

TAB = {"TMUX": "/tmp/tmux-stub,1,0", "TMUX_PANE": "%7"}
P_RUN = {**TAB, "CLAUDE_CODE_SESSION_ATTENDED": "0"}
BG = {"CLAUDE_CODE_SESSION_KIND": "bg"}


class Hooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        os.mkdir(stubs)
        for name in ("tmux", "powershell.exe", "wslpath"):
            path = os.path.join(stubs, name)
            with open(path, "w") as f:
                f.write(STUB)
            os.chmod(path, 0o755)
        self.log = os.path.join(self.tmp, "calls.log")
        self.state = os.path.join(self.tmp, "state")
        # The test may itself run inside a Claude session in a tmux tab: start from a clean env.
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], STUB_LOG=self.log,
                        XDG_STATE_HOME=self.state, STUB_PANES="1 %1",
                        CLAUDE_CODE_SESSION_ID="abcdef12-0000")

    def run_hook(self, name, session, payload=None, args=()):
        env = {**self.env, **session}
        self.logged_before = len(self.ring_log())
        p = subprocess.run(["bash", os.path.join(HOOKS, name), *args],
                           input=json.dumps(payload or {}), capture_output=True, text=True,
                           timeout=10, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def calls(self, settle=0.0):
        time.sleep(settle)  # the sound and the toast run detached, after the hook exits
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def window_writes(self):
        return [c for c in self.calls() if c.startswith("tmux set-option")]

    def seen(self, mark):
        deadline = time.time() + 3
        while time.time() < deadline:
            if any(mark in c for c in self.calls()):
                return True
            time.sleep(0.05)
        return False

    def rang(self):
        return self.seen("SoundPlayer")

    def toasted(self):
        return self.seen("notify-toast.ps1")

    def no_ring(self):
        # ring.log is written before the hook exits, so the run's own new line is the decision.
        log = self.ring_log()
        return len(log) == self.logged_before + 1 and " quiet " in log[-1]

    def ring_log(self):
        path = os.path.join(self.state, "dotclaude", "ring.log")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return f.read().splitlines()

    # --- tmux-state.sh: which window gets the state --------------------------------------

    def test_a_tab_writes_its_own_pane(self):
        self.run_hook("tmux-state.sh", TAB, args=("busy",))
        self.assertEqual(self.window_writes(), ["tmux set-option -w -t %7 @claude_state busy"])

    def test_an_attached_background_session_finds_its_tab_through_its_ancestry(self):
        # The stub reports this test process as a pane's shell, so the hook's parent matches.
        self.env["STUB_PANES"] = f"1 %1\n{os.getpid()} %9"
        for state in ("busy", "wait", "idle"):
            self.run_hook("tmux-state.sh", BG, args=(state,))
        self.assertEqual(self.window_writes(),
                         [f"tmux set-option -w -t %9 @claude_state {s}"
                          for s in ("busy", "wait", "idle")])

    def run_under_daemon(self, name, sessions, args=(), payload=None):
        # Fake the real chain: hook <- `claude daemon run` <- this test process (the pane's
        # shell), the daemon hosting `sessions` pty hosts plus a spare one.
        script = "".join(
            f'(exec -a "claude bg-pty-host --bg-pty-host /d/pty/s{i}.sock 80 24" sleep 30) &\n'
            for i in range(sessions))
        script += ('(exec -a "claude bg-pty-host --bg-pty-host /d/spare/x.pty.sock" sleep 30) &\n'
                   'sleep 0.2\nbash "$HOOK" "$@" <<< "$PAYLOAD"; rc=$?\n'
                   'pkill -P $$ sleep; exit $rc\n')
        self.logged_before = len(self.ring_log())
        env = {**self.env, **BG, "HOOK": os.path.join(HOOKS, name),
               "PAYLOAD": json.dumps(payload or {}),
               "STUB_PANES": f"{os.getpid()} %9"}
        p = subprocess.run(["claude daemon run --origin transient", "-c", script, "x", *args],
                           executable="/bin/bash", env=env, capture_output=True, text=True,
                           timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_a_daemon_hosting_one_session_resolves_to_its_tab(self):
        self.run_under_daemon("tmux-state.sh", 1, args=("busy",))
        self.assertEqual(self.window_writes(), ["tmux set-option -w -t %9 @claude_state busy"])

    def test_a_daemon_hosting_two_sessions_is_ambiguous_and_writes_nothing(self):
        # Which of the two the tab's client shows can't be seen from outside, so neither owns it.
        self.run_under_daemon("tmux-state.sh", 2, args=("busy",))
        self.assertEqual(self.window_writes(), [])
        self.run_under_daemon("stop-ring.sh", 2)
        self.assertTrue(self.no_ring())

    def test_a_p_run_started_from_a_background_session_stays_off_tab(self):
        # It inherits KIND=bg from its parent session, and ATTENDED=0 must still win.
        self.env["STUB_PANES"] = f"{os.getpid()} %9"
        p_from_bg = {**BG, "CLAUDE_CODE_SESSION_ATTENDED": "0"}
        self.run_hook("tmux-state.sh", p_from_bg, args=("idle",))
        self.assertEqual(self.window_writes(), [])
        self.run_hook("stop-ring.sh", p_from_bg)
        self.assertTrue(self.no_ring())

    def test_an_unattached_background_session_writes_nothing(self):
        self.env["STUB_PANES"] = "999999 %9"
        self.run_hook("tmux-state.sh", BG, args=("busy",))
        self.assertEqual(self.window_writes(), [])

    def test_a_p_run_inside_a_tab_leaves_the_tab_alone(self):
        for state in ("busy", "idle", "wait"):
            self.run_hook("tmux-state.sh", P_RUN, args=(state,))
        self.assertEqual(self.window_writes(), [])

    def test_a_subagent_stop_does_not_clear_a_busy_tab(self):
        self.run_hook("tmux-state.sh", TAB, {"agent_id": "a1"}, args=("idle",))
        self.run_hook("tmux-state.sh", TAB, {"agent_type": "writer"}, args=("idle",))
        self.assertEqual(self.window_writes(), [])
        self.run_hook("tmux-state.sh", TAB, {"agent_id": "a1"}, args=("busy",))
        self.assertEqual(len(self.window_writes()), 1)

    def test_outside_tmux_nothing_is_written(self):
        self.run_hook("tmux-state.sh", {}, args=("busy",))
        self.assertEqual(self.window_writes(), [])

    # --- stop-ring.sh: who rings when a turn ends -----------------------------------------

    def test_a_tab_rings_on_stop(self):
        self.run_hook("stop-ring.sh", TAB)
        self.assertTrue(self.rang())

    def test_a_plain_terminal_rings_on_stop(self):
        self.run_hook("stop-ring.sh", {})
        self.assertTrue(self.rang())

    def test_an_attached_background_session_rings(self):
        self.env["STUB_PANES"] = f"{os.getpid()} %9"
        self.run_hook("stop-ring.sh", BG)
        self.assertTrue(self.rang())

    def test_off_tab_sessions_and_subagents_stay_quiet(self):
        self.env["STUB_PANES"] = "999999 %9"
        for session, payload in ((BG, {}), (P_RUN, {}), (TAB, {"agent_id": "a1"}),
                                 (TAB, {"agent_type": "writer"})):
            with self.subTest(session=session, payload=payload):
                self.run_hook("stop-ring.sh", session, payload)
                self.assertTrue(self.no_ring())

    def test_each_ring_decision_is_logged(self):
        self.run_hook("stop-ring.sh", TAB)
        self.run_hook("stop-ring.sh", P_RUN)
        log = self.ring_log()
        self.assertEqual(len(log), 2, log)
        self.assertIn("rang", log[0])
        self.assertIn("pane=%7", log[0])
        self.assertIn("abcdef12", log[0])
        self.assertIn("quiet", log[1])
        self.assertIn("attended=0", log[1])

    def test_the_ring_log_stays_bounded(self):
        for _ in range(3):
            self.run_hook("stop-ring.sh", P_RUN)
        path = os.path.join(self.state, "dotclaude", "ring.log")
        with open(path, "a") as f:
            f.write("old line\n" * 3000)
        self.run_hook("stop-ring.sh", P_RUN)
        self.assertLessEqual(len(self.ring_log()), 2000)
        self.assertIn("quiet", self.ring_log()[-1])

    # --- notify.sh: the permission prompt pops a toast always, rings only in view -----------

    def test_a_permission_prompt_toasts_and_rings_in_a_tab(self):
        self.run_hook("notify.sh", TAB, {"message": "Claude needs your permission"})
        self.assertTrue(self.rang())
        self.assertTrue(self.toasted())

    def test_an_off_tab_permission_prompt_toasts_without_a_sound(self):
        self.env["STUB_PANES"] = "999999 %9"
        self.run_hook("notify.sh", BG, {"message": "Claude needs your permission"})
        self.assertTrue(self.no_ring())
        self.assertTrue(self.toasted())

    def test_a_missing_session_id_still_rings_and_toasts(self):
        # The hooks run under `set -u`: an unset variable must not abort them before the toast.
        del self.env["CLAUDE_CODE_SESSION_ID"]
        self.run_hook("notify.sh", TAB, {"message": "m"})
        self.assertTrue(self.rang())
        self.assertTrue(self.toasted())
        self.run_hook("stop-ring.sh", TAB)
        self.assertEqual(len(self.ring_log()), 2)


if __name__ == "__main__":
    unittest.main()
