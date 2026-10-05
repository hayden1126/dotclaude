"""hooks/tmux-state.sh, hooks/stop-ring.sh and hooks/notify.sh: which tmux window a session's
state lands on, and which sessions ring (stdlib only).

A session is in view when a person sees it: a tmux tab or a plain terminal. A `claude -p` run
inherits the tab's TMUX_PANE, and a background session (claude daemon) has none; both carry
CLAUDE_CODE_SESSION_ATTENDED=0 in a hook's env (probed on 2.1.289), so neither writes tab state
nor rings, unless tmux/tmux-claude-status mapped the background session to the tab showing it
($XDG_STATE_HOME/dotclaude/tabs). Stubs for tmux, powershell.exe and wslpath record every call."""
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
  "tmux show-option") printf '%s\\n' "${STUB_WINDOW_STATE:-}" ;;
  "wslpath -w") printf 'C:\\\\stub\\\\%s\\n' "$(basename "$2")" ;;
esac
exit 0
"""

TAB = {"TMUX": "/tmp/tmux-stub,1,0", "TMUX_PANE": "%7"}
P_RUN = {**TAB, "CLAUDE_CODE_SESSION_ATTENDED": "0"}
# A background session's hook env, as probed: no TMUX_PANE, no SESSION_KIND.
BG = {"CLAUDE_CODE_SESSION_ATTENDED": "0", "CLAUDE_JOB_DIR": "/tmp/job"}


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
        # Every event carries the session's id; the map is keyed by it.
        payload = {"session_id": env.get("CLAUDE_CODE_SESSION_ID", ""), **(payload or {})}
        self.logged_before = len(self.ring_log())
        p = subprocess.run(["bash", os.path.join(HOOKS, name), *args],
                           input=json.dumps(payload), capture_output=True, text=True,
                           timeout=10, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
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

    def map_tabs(self, text, age=0):
        """Write the map tmux-claude-status keeps: a server line, then "<session> <pane> <window>"."""
        path = os.path.join(self.state, "dotclaude", "tabs")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        then = time.time() - age
        os.utime(path, (then, then))

    # --- tmux-state.sh: which window gets the state --------------------------------------

    def test_a_tab_writes_its_own_pane(self):
        self.run_hook("tmux-state.sh", TAB, args=("busy",))
        self.assertEqual(self.window_writes(), ["tmux set-option -w -t %7 @claude_state busy"])

    def test_a_background_session_writes_no_tab_state(self):
        # One shared daemon hosts every background session, so even an ancestry that reaches a
        # pane (as this stub's does) names the daemon's first client, not the tab showing it.
        self.env["STUB_PANES"] = f"{os.getpid()} %9"
        for state in ("busy", "wait", "idle"):
            self.run_hook("tmux-state.sh", BG, args=(state,))
        self.assertEqual(self.window_writes(), [])
        self.assertFalse([c for c in self.calls() if c.startswith("tmux")])

    def test_a_mapped_background_session_writes_its_tab(self):
        self.map_tabs("server 42\nother-id %3 @3\nabcdef12-0000 %9 @9\n")
        for state in ("busy", "wait", "idle"):
            self.run_hook("tmux-state.sh", BG, args=(state,))
        self.assertEqual(self.window_writes(), [
            f"tmux set-option -w -t %9 @claude_state {s}" for s in ("busy", "wait", "idle")])

    def test_a_mapped_background_subagent_stop_does_not_clear_its_tab(self):
        self.map_tabs("server 42\nabcdef12-0000 %9 @9\n")
        self.run_hook("tmux-state.sh", BG, {"agent_id": "a1"}, args=("idle",))
        self.assertEqual(self.window_writes(), [])

    def test_the_map_is_only_for_background_sessions(self):
        # A `claude -p` run has no CLAUDE_JOB_DIR: even with its id in the map it stays off-tab.
        self.map_tabs("server 42\nabcdef12-0000 %9 @9\n")
        self.run_hook("tmux-state.sh", P_RUN, args=("busy",))
        self.assertEqual(self.window_writes(), [])

    def test_a_p_run_inside_a_background_session_stays_off_tab(self):
        # It inherits the background session's CLAUDE_JOB_DIR and may inherit its session id
        # env, but its events carry its own session_id.
        self.map_tabs("server 42\nabcdef12-0000 %9 @9\n")
        self.run_hook("tmux-state.sh", BG, {"session_id": "nested-run"}, args=("busy",))
        self.run_hook("stop-ring.sh", BG, {"session_id": "nested-run"})
        self.assertEqual(self.window_writes(), [])
        self.assertTrue(self.no_ring())
        self.assertIn("quiet session=nested-r ", self.ring_log()[-1])  # its own id, not the env's

    def test_a_stale_map_is_ignored(self):
        # Only a running tmux-claude-status refreshes the map (at least every 60 s while
        # background sessions run): after tmux exits or detaches, nobody sees the session.
        self.map_tabs("server 42\nabcdef12-0000 %9 @9\n", age=120)
        self.run_hook("tmux-state.sh", BG, args=("busy",))
        self.run_hook("stop-ring.sh", BG)
        self.assertEqual(self.window_writes(), [])
        self.assertTrue(self.no_ring())

    def test_a_missing_or_garbled_map_leaves_a_background_session_off_tab(self):
        for text in (None, "", "garbage\n\n", "abcdef12 %9 @9\n", "abcdef12-0000\n"):
            with self.subTest(text=text):
                if text is not None:
                    self.map_tabs(text)
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

    def test_a_subagent_does_not_cover_a_question_waiting_on_the_user(self):
        # A background subagent keeps making tool calls while the main session asks a question;
        # its busy must not overwrite the main session's wait (2026-10-04, AskUserQuestion).
        self.env["STUB_WINDOW_STATE"] = "wait"
        self.run_hook("tmux-state.sh", TAB, {"agent_id": "a1"}, args=("busy",))
        self.run_hook("tmux-state.sh", TAB, {"agent_type": "reviewer"}, args=("busy",))
        self.assertEqual(self.window_writes(), [])
        # The main session's own next event (the answer, its next tool call) clears it.
        self.run_hook("tmux-state.sh", TAB, args=("busy",))
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

    def test_off_tab_sessions_and_subagents_stay_quiet(self):
        for session, payload in ((BG, {}), (P_RUN, {}), (TAB, {"agent_id": "a1"}),
                                 (TAB, {"agent_type": "writer"})):
            with self.subTest(session=session, payload=payload):
                self.run_hook("stop-ring.sh", session, payload)
                self.assertTrue(self.no_ring())

    def test_a_mapped_background_session_rings_on_stop(self):
        self.map_tabs("server 42\nabcdef12-0000 %9 @9\n")
        self.run_hook("stop-ring.sh", BG)
        self.assertTrue(self.rang())
        self.assertIn("rang session=abcdef12 kind=background attended=0 pane=%9", self.ring_log()[-1])
        self.run_hook("stop-ring.sh", BG, {"agent_id": "a1"})
        self.assertTrue(self.no_ring())

    def test_each_ring_decision_is_logged(self):
        self.run_hook("stop-ring.sh", TAB)
        self.run_hook("stop-ring.sh", P_RUN)
        log = self.ring_log()
        self.assertEqual(len(log), 2, log)
        self.assertIn("kind=tab", log[0])
        self.assertIn("rang", log[0])
        self.assertIn("pane=%7", log[0])
        self.assertIn("abcdef12", log[0])
        self.assertIn("quiet", log[1])
        self.assertIn("kind=print attended=0", log[1])
        self.run_hook("stop-ring.sh", BG)
        self.assertIn("quiet session=abcdef12 kind=background", self.ring_log()[-1])

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
        self.run_hook("notify.sh", BG, {"message": "Claude needs your permission"})
        self.assertTrue(self.no_ring())
        self.assertTrue(self.toasted())

    def test_a_mapped_background_permission_prompt_toasts_and_rings(self):
        self.map_tabs("server 42\nabcdef12-0000 %9 @9\n")
        self.run_hook("notify.sh", BG, {"message": "Claude needs your permission"})
        self.assertTrue(self.rang())
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
