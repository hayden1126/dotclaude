"""skills/pass/scripts/pass-respawn: the /pass gate, the resume mode, the detached waiter and its
drops, and the background-work check (spike S6).

Each test runs the script in-process against a throwaway repo (tests/lanes/_fixture.py), with a
fake `tmux` first on PATH that logs each call's argv (one argument per \\x1f field) and replays
scripted @claude_state values, and a fake process table in place of /proc. handoff-check runs
for real as a subprocess. Nothing reaches the live tmux server."""
import contextlib
import io
import json
import os
import shlex
import sys
import time
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lanes"))
from _fixture import LanesRepo  # noqa: E402

SCRIPT = os.path.join(REPO, "skills", "pass", "scripts", "pass-respawn")


def load():
    loader = SourceFileLoader("pass_respawn", SCRIPT)
    mod = module_from_spec(spec_from_loader("pass_respawn", loader))
    loader.exec_module(mod)
    return mod


FAKE_TMUX = r"""#!/bin/sh
{ printf 'tmux'; for a in "$@"; do printf '\037%s' "$a"; done; printf '\n'; } >> "$FAKE_TMUX_LOG"
case "$1" in
  show-option|show-options|show)
    if [ "$(wc -l < "$FAKE_TMUX_STATES")" -gt 1 ]; then
      head -n 1 "$FAKE_TMUX_STATES"
      sed -i 1d "$FAKE_TMUX_STATES"
    else
      cat "$FAKE_TMUX_STATES"
    fi ;;
  display-message|display)
    [ "$2" = -p ] && printf '%s\n' "$FAKE_TMUX_SERVER" ;;
esac
exit 0
"""

GOOD = """# STATUS: chart work

## Direction
- Ship the chart fix.

## Notes for next session
- Run the chart tests, then open the PR for #42.
"""
APPROVED = GOOD + "- Then merge it (approved by Hayden 2026-10-12).\n"
SID = "sess-0001"
CLAUDE, SHELL, ME = 900000, 900001, None  # ME is os.getpid(), set per test
SERVER = "1791000000 222 /tmp/tmux-1000/default"


def table(*extra, claude=True):
    """A process table: this test process under a zsh under the session's claude, which also
    runs its MCP servers, plus extra (pid, comm, ppid) rows."""
    t = {os.getpid(): ("python3", SHELL), SHELL: ("zsh", CLAUDE if claude else 1),
         CLAUDE: ("claude", 1), 900002: ("npm", CLAUDE), 900003: ("socat", CLAUDE),
         900005: ("node", 900002)}
    if not claude:
        del t[CLAUDE]
    for pid, comm, ppid in extra:
        t[pid] = (comm, ppid)
    return t


class Base(LanesRepo):
    init_lanes = False

    def setUp(self):
        super().setUp()
        self.mod = load()
        self.mod.POLL, self.mod.SETTLE, self.mod.COMPACT_GAP = 0.01, 0.05, 0.01
        self.mod.writable_roots = lambda repo: [repo.toplevel, repo.main]
        with open(os.path.join(self.fake_bin, "tmux"), "w") as f:
            f.write(FAKE_TMUX)
        os.chmod(os.path.join(self.fake_bin, "tmux"), 0o755)
        self.tmux = os.path.join(self.fake_bin, "tmux")
        self.claude = os.path.join(self.fake_bin, "claude")
        self.tmux_log = os.path.join(self.tmp, "tmux.log")
        self.states_file = os.path.join(self.tmp, "states")
        self.states("idle")
        self.env.update(TMUX_PANE="%4", CLAUDE_CODE_SESSION_ID=SID, FAKE_TMUX_LOG=self.tmux_log,
                        FAKE_TMUX_STATES=self.states_file, FAKE_TMUX_SERVER=SERVER)
        patch = mock.patch.dict(os.environ, self.env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.state = os.path.join(self.tmp, "state", "dotclaude")
        self.session(self.main, time.time() - 60)

    def session(self, cwd, started):
        self.write(os.path.join(self.home, ".claude", "sessions", "1.json"),
                   json.dumps({"sessionId": SID, "cwd": cwd, "startedAt": int(started * 1000),
                               "pid": 1}))

    def states(self, *values):
        with open(self.states_file, "w") as f:
            f.write("".join(v + "\n" for v in values))

    def run_pass(self, *args, procs=None, cwd=None):
        out = io.StringIO()
        argv = [*args, "-C", cwd or self.main]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.mod.main(argv, procs=procs or table)
        return code, out.getvalue()

    def calls(self, *prefix):
        if not os.path.exists(self.tmux_log):
            return []
        with open(self.tmux_log) as f:
            argvs = [line.split("\x1f") for line in f.read().splitlines()]
        return [a for a in argvs if a[:len(prefix)] == list(prefix)]

    def log(self):
        path = os.path.join(self.state, "pass.log")
        return open(path).read() if os.path.exists(path) else ""

    def carry_marker(self):
        return os.path.join(self.state, "pass-carry", "4.json")

    def assertDropped(self, outcome, words):
        self.assertEqual(self.calls("tmux", "respawn-pane"), [])
        self.assertEqual(self.calls("tmux", "send-keys"), [])
        (msg,) = self.calls("tmux", "display-message")
        self.assertEqual(msg[:4], ["tmux", "display-message", "-t", "%4"])
        self.assertIn(words, msg[-1])
        self.assertIn(f"outcome={outcome}", self.log())


class Plain(Base):
    def setUp(self):
        super().setUp()
        self.commit("STATUS.md", GOOD, msg="Handoff")

    PROMPT = "Read STATUS.md (and PLAN.md if present), then plan the next step."

    def respawn(self, *mode, prompt=None):
        return shlex.join([self.tmux, "respawn-pane", "-k", "-t", "%4", "-c", self.main, "--",
                           self.claude, *mode, prompt or self.PROMPT])

    # --- the resume mode ---------------------------------------------------------------

    def test_unapproved_resumes_in_plan_mode(self):
        code, out = self.run_pass("--print")
        self.assertEqual(code, 0, out)
        self.assertIn("mode: plain (plan)", out)
        self.assertIn(self.respawn("--permission-mode", "plan"), out.splitlines())
        self.assertEqual(self.calls("tmux", "respawn-pane"), [])
        self.assertFalse(os.path.exists(self.carry_marker()))

    def test_approved_resumes_in_the_default_mode(self):
        self.commit("STATUS.md", APPROVED, msg="Handoff")
        code, out = self.run_pass("--print")
        self.assertEqual(code, 0, out)
        self.assertIn("mode: plain (default)", out)
        prompt = "Read STATUS.md (and PLAN.md if present), then continue with the approved next step."
        self.assertIn(self.respawn(prompt=prompt), out.splitlines())

    def test_a_malformed_marker_fails_the_gate(self):
        self.commit("STATUS.md", GOOD + "- Then merge it (approved by Hayden).\n", msg="Handoff")
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn("malformed approval marker", out)
        self.assertIn("outcome=refused", self.log())

    def test_compact_types_the_focus_then_the_prompt(self):
        code, out = self.run_pass("--compact", "--print")
        self.assertEqual(code, 0, out)
        self.assertIn("mode: compact (plan)", out)
        lines = out.splitlines()
        focus = self.mod.compact_focus(os.path.join(self.main, "STATUS.md"))
        self.assertIn(os.path.join(self.main, "STATUS.md"), focus)
        for argv in (["send-keys", "-t", "%4", "-l", f"/compact {focus}"],
                     ["send-keys", "-t", "%4", "Enter"],
                     ["send-keys", "-t", "%4", "-l", self.PROMPT + " Call EnterPlanMode first."]):
            self.assertIn(shlex.join([self.tmux, *argv]), lines)

    def test_approved_compact_skips_plan_mode(self):
        self.commit("STATUS.md", APPROVED, msg="Handoff")
        code, out = self.run_pass("--compact", "--print")
        self.assertEqual(code, 0, out)
        self.assertIn("mode: compact (default)", out)
        self.assertNotIn("EnterPlanMode", out)
        self.assertIn("then continue with the approved next step.", out)

    # --- refusals at call time -----------------------------------------------------------

    def test_no_tmux_pane_prints_the_manual_line(self):
        del os.environ["TMUX_PANE"]
        code, out = self.run_pass()
        self.assertEqual(code, 2, out)
        self.assertIn(f"/clear, then: {self.PROMPT}", out)
        self.assertEqual(self.calls("tmux"), [])

    def test_a_failing_handoff_check_refuses(self):
        self.write(os.path.join(self.main, "scratch.txt"), "x")
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL", out)
        self.assertIn("scratch.txt", out)
        self.assertEqual(self.calls("tmux"), [])
        self.assertIn("outcome=refused", self.log())

    def test_plain_refuses_background_work_but_compact_goes_on(self):
        bg = lambda: table((900004, "bwrap", CLAUDE))  # noqa: E731
        code, out = self.run_pass("--print", procs=bg)
        self.assertEqual(code, 1, out)
        self.assertIn("--compact", out)
        code, out = self.run_pass("--compact", "--print", procs=bg)
        self.assertEqual(code, 0, out)

    def test_plain_refuses_when_the_sessions_claude_is_not_found(self):
        code, out = self.run_pass("--print", procs=lambda: table(claude=False))
        self.assertEqual(code, 1, out)
        self.assertIn("claude", out)

    def test_a_tmux_in_a_sandbox_writable_dir_is_refused(self):
        self.mod.writable_roots = lambda repo: [self.fake_bin]
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn("sandbox-writable", out)

    # --- the waiter ----------------------------------------------------------------------

    def test_busy_then_idle_respawns_after_writing_the_carry(self):
        self.states("busy", "wait", "busy", "idle")
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        (respawn,) = self.calls("tmux", "respawn-pane")
        self.assertEqual(respawn[1:], shlex.split(self.respawn("--permission-mode", "plan"))[1:])
        self.assertGreaterEqual(len(self.calls("tmux", "show-option")), 5)
        with open(self.carry_marker()) as f:
            carry = json.load(f)
        self.assertEqual(carry["session_id"], SID)
        self.assertEqual(carry["tab"], {"socket": "/tmp/tmux-1000/default",
                                        "server_start": 1791000000, "server_pid": 222,
                                        "pane": "%4"})
        self.assertLess(abs(time.time() - carry["written_at"]), 30)
        self.assertIn(f"session={SID} pane=%4 mode=plain outcome=respawn", self.log())

    def test_compact_waits_for_idle_and_never_respawns(self):
        self.states("busy", "idle")
        code, out = self.run_pass("--compact", "--foreground")
        self.assertEqual(code, 0, out)
        keys = [a[1:] for a in self.calls("tmux", "send-keys")]
        focus = self.mod.compact_focus(os.path.join(self.main, "STATUS.md"))
        self.assertEqual(keys, [["send-keys", "-t", "%4", "-l", f"/compact {focus}"],
                                ["send-keys", "-t", "%4", "Enter"],
                                ["send-keys", "-t", "%4", "-l",
                                 self.PROMPT + " Call EnterPlanMode first."],
                                ["send-keys", "-t", "%4", "Enter"]])
        self.assertEqual(self.calls("tmux", "respawn-pane"), [])
        self.assertFalse(os.path.exists(self.carry_marker()))
        self.assertIn("mode=compact outcome=compact", self.log())

    def test_the_call_returns_and_a_detached_waiter_acts_after(self):
        self.states(*["busy"] * 30, "idle")
        code, out = self.run_pass("--compact")
        self.assertEqual(code, 0, out)
        self.assertIn("once this turn ends", out)
        self.assertNotIn("outcome=compact", self.log())   # the call didn't wait
        for _ in range(200):
            if "outcome=compact" in self.log():
                break
            time.sleep(0.05)
        self.assertIn("mode=compact outcome=compact", self.log())
        self.assertEqual(len(self.calls("tmux", "send-keys")), 4)

    def test_a_queued_prompt_in_the_settle_drops_resumed(self):
        self.states("idle", "busy")
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("resumed", "pass dropped")

    def test_a_turn_that_never_ends_drops_timeout(self):
        self.states("busy")
        code, out = self.run_pass("--foreground", "--timeout", "0.3")
        self.assertEqual(code, 1, out)
        self.assertDropped("timeout", "pass dropped")

    def test_background_work_started_after_the_call_drops_busy(self):
        seen = []

        def procs():
            seen.append(1)
            return table() if len(seen) == 1 else table((900004, "bash", CLAUDE))
        code, out = self.run_pass("--foreground", procs=procs)
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", "background")

    def test_at_act_time_the_shell_that_ran_the_call_counts(self):
        # The waiter is detached, so its own ancestry no longer shields the shell: a shell
        # child still there at idle is a sandbox-off command in flight.
        args = self.mod.parse(["--foreground", "-C", self.main])
        plan = self.mod.prepare(args, table)
        detached = lambda: {**table(), os.getpid(): ("python3", 1)}  # noqa: E731
        self.assertEqual(self.mod.wait_and_act(plan, detached), "busy")
        self.assertDropped("busy", "background")

    # --- staleness ----------------------------------------------------------------------

    def test_an_edit_after_the_call_drops_stale(self):
        clean = lambda: table(claude=True)  # noqa: E731
        plan = self.mod.prepare(self.mod.parse(["--foreground", "-C", self.main]), clean)
        self.write(os.path.join(self.main, "late.txt"), "x")
        idle = lambda: {k: v for k, v in table().items() if k != SHELL}  # noqa: E731
        self.assertEqual(self.mod.wait_and_act(plan, idle), "stale")
        self.assertDropped("stale", "handoff is stale")

    def test_a_commit_after_the_call_drops_stale(self):
        plan = self.mod.prepare(self.mod.parse(["--foreground", "-C", self.main]), table)
        time.sleep(1.05)  # past the status file's mtime, at commit-time resolution
        self.commit("late.txt", "x")
        idle = lambda: {k: v for k, v in table().items() if k != SHELL}  # noqa: E731
        self.assertEqual(self.mod.wait_and_act(plan, idle), "stale")
        self.assertDropped("stale", "handoff is stale")


class Lane(Base):
    init_lanes = True

    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix", "--claim", "42")
        self.path = self.lane_path("chart-fix")
        self.hook("lane-identity.sh", {"session_id": SID, "cwd": self.path,
                                       "source": "startup", "hook_event_name": "SessionStart"})
        body = self.read(self.record("chart-fix")).replace(
            "## Next\n", "## Next\n- Write the axis test for #42, then run it.\n")
        time.sleep(1.05)
        self.write(self.record("chart-fix"), body)

    def test_print_in_a_lane_names_the_lane_record(self):
        record = self.record("chart-fix")
        code, out = self.run_pass("--print", cwd=self.path)
        self.assertEqual(code, 0, out)
        prompt = f"Read your lane record {record}, then plan the next step."
        argv = [self.tmux, "respawn-pane", "-k", "-t", "%4", "-c", self.path, "--", self.claude,
                "--permission-mode", "plan", prompt]
        self.assertIn(shlex.join(argv), out.splitlines())

    def test_compact_in_a_lane_points_the_focus_at_the_record(self):
        record = self.record("chart-fix")
        code, out = self.run_pass("--compact", "--print", cwd=self.path)
        self.assertEqual(code, 0, out)
        self.assertIn(shlex.join([self.tmux, "send-keys", "-t", "%4", "-l",
                                  f"/compact {self.mod.compact_focus(record)}"]), out.splitlines())
        self.assertIn(f"Read your lane record {record}, then plan the next step. "
                      "Call EnterPlanMode first.", out)


class BackgroundWork(unittest.TestCase):
    """Spike S6: a background Bash task is a bwrap child of the session's claude, a sandbox-off
    command a shell child; MCP servers (npm, node, socat) are not work."""

    def setUp(self):
        self.mod = load()

    def test_the_sessions_claude_is_the_nearest_claude_ancestor(self):
        t = table()
        self.assertEqual(self.mod.session_claude(t, os.getpid()), CLAUDE)
        self.assertIsNone(self.mod.session_claude(table(claude=False), os.getpid()))
        self.assertIsNone(self.mod.session_claude({5: ("zsh", 6), 6: ("zsh", 5)}, 5))  # a cycle

    def test_bwrap_and_shell_children_count_but_mcp_servers_do_not(self):
        rows = [(1001, "bwrap", CLAUDE), (1002, "bash", CLAUDE), (1003, "sh", CLAUDE),
                (1004, "dash", CLAUDE), (1005, "node", CLAUDE), (1006, "bwrap", 1001)]
        found = self.mod.background_work(table(*rows), CLAUDE, os.getpid())
        self.assertEqual(sorted(found), [(1001, "bwrap"), (1002, "bash"), (1003, "sh"),
                                         (1004, "dash")])

    def test_the_callers_own_shell_is_not_work_until_it_is_detached(self):
        self.assertEqual(self.mod.background_work(table(), CLAUDE, os.getpid()), [])
        self.assertEqual(self.mod.background_work(table(), CLAUDE, None), [(SHELL, "zsh")])

    def test_proc_table_reads_comm_and_ppid(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d)
        for pid, stat in (("123", "123 (odd (name) x) S 45 1 1 0"), ("7", "7 (claude) S 1 7 7"),
                          ("self", "1 (x) S 0"), ("99", "garbage")):
            os.makedirs(os.path.join(d, pid))
            with open(os.path.join(d, pid, "stat"), "w") as f:
                f.write(stat)
        self.assertEqual(self.mod.proc_table(d), {123: ("odd (name) x", 45), 7: ("claude", 1)})


if __name__ == "__main__":
    unittest.main()
