"""hooks/tmux-state.sh, hooks/stop-ring.sh and hooks/notify.sh: which tmux window a session's
state lands on, and which sessions ring (stdlib only).

A session is in view when a person sees it: a tmux tab or a plain terminal. A `claude -p` run
inherits the tab's TMUX_PANE, and a background session (claude daemon) has none; both carry
CLAUDE_CODE_SESSION_ATTENDED=0 in a hook's env (probed on 2.1.289), so neither writes tab state
nor rings, unless tmux/tmux-claude-status mapped the background session to the tab showing it
($XDG_STATE_HOME/dotclaude/tabs). Stubs for tmux, powershell.exe and wslpath record every call."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, "hooks")

spec = importlib.util.spec_from_file_location("stop_ring", os.path.join(HOOKS, "stop_ring.py"))
stop_ring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stop_ring)

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


# A locale whose files read as ASCII: the C locale with Python's UTF-8 mode and coercion off.
# Under -I those env switches are ignored and C is coerced to UTF-8, so the fake python3 below
# (first on PATH in the stubs dir) drops -I and adds -X utf8=0 to make the default bite.
ASCII_LOCALE = {"LC_ALL": "C", "LANG": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0",
                "FAKE_PY_ASCII": "1"}
FAKE_PYTHON = """#!/usr/bin/env bash
if [ -n "${FAKE_PY_ASCII:-}" ]; then
  args=(); for a in "$@"; do [ "$a" = -I ] || args+=("$a"); done
  exec %s -X utf8=0 "${args[@]}"
fi
exec %s "$@"
"""


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
        with open(os.path.join(stubs, "python3"), "w") as f:
            f.write(FAKE_PYTHON % (sys.executable, sys.executable))
        os.chmod(os.path.join(stubs, "python3"), 0o755)
        self.log = os.path.join(self.tmp, "calls.log")
        self.state = os.path.join(self.tmp, "state")
        # The test may itself run inside a Claude session in a tmux tab: start from a clean env.
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], STUB_LOG=self.log,
                        XDG_STATE_HOME=self.state, STUB_PANES="1 %1",
                        CLAUDE_CODE_SESSION_ID="abcdef12-0000", DOTCLAUDE_RING_SETTLE="0.3")

    def run_hook(self, name, session, payload=None, args=(), wait=True):
        env = {**self.env, **session}
        # Every event carries the session's id; the map is keyed by it.
        payload = {"session_id": env.get("CLAUDE_CODE_SESSION_ID", ""), **(payload or {})}
        self.logged_before = len(self.ring_log())
        p = subprocess.run(["bash", os.path.join(HOOKS, name), *args],
                           input=json.dumps(payload), capture_output=True, text=True,
                           timeout=10, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        if name == "stop-ring.sh" and wait:
            self.decided()
        return p

    def decided(self):
        """Wait for the run's ring.log line: stop-ring logs a ring after its settle, detached.
        A positive-only wait, so a long deadline costs nothing when it passes; 3 s flaked under
        machine load (on main too, 2026-10-12)."""
        deadline = time.time() + 15
        while len(self.ring_log()) == self.logged_before and time.time() < deadline:
            time.sleep(0.05)
        self.assertNotEqual(len(self.ring_log()), self.logged_before, "no decision logged")

    def transcript(self, *entries):
        """Write a transcript of JSON lines; return its path."""
        path = os.path.join(self.tmp, "transcript.jsonl")
        with open(path, "a") as f:
            for e in entries:
                f.write(json.dumps(e, separators=(",", ":")) + "\n")
        return path

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
        # The run's own new line is the decision: notify.sh logs before it exits, and run_hook
        # waits (decided) for stop-ring.sh's detached child to log after its settle.
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
        self.assertIn("quiet tasks=- session=nested-r ", self.ring_log()[-1])  # its own id, not the env's

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

    def test_a_stop_with_background_work_in_flight_stays_quiet(self):
        # The turn ended but the session is paused on work that will wake it (an agent, a
        # shell): it is neither done nor waiting on the person, so no ring (2026-10-04). The
        # payload's `type` is Claude Code's friendly label, not the internal task name
        # (2.1.289: local_bash -> "shell", local_agent -> "subagent", and so on).
        for task in ({"id": "a1", "type": "subagent", "status": "running"},
                     {"id": "b1", "type": "shell", "status": "running"},
                     {"id": "w1", "type": "workflow", "status": "pending"},
                     {"id": "r1", "type": "cloud session", "status": "running"}):
            with self.subTest(task=task["type"]):
                self.run_hook("stop-ring.sh", TAB, {"background_tasks": [task]})
                self.assertTrue(self.no_ring())
                self.assertIn("stop quiet busy=1", self.ring_log()[-1])
                self.assertIn(f"tasks={task['type'].replace(' ', '_')}", self.ring_log()[-1])

    def test_a_stop_rings_when_only_lingering_tasks_remain(self):
        # Teammates linger in the list after they finish, dream is memory upkeep and a monitor
        # can run for hours: none of them means the person's work is still running.
        tasks = [{"id": "t1", "type": "teammate", "status": "running"},
                 {"id": "d1", "type": "dream", "status": "running"},
                 {"id": "m1", "type": "monitor", "status": "running"}]
        self.run_hook("stop-ring.sh", TAB, {"background_tasks": tasks})
        self.assertTrue(self.rang())
        self.assertIn("tasks=teammate,dream,monitor", self.ring_log()[-1])
        self.run_hook("stop-ring.sh", TAB, {"background_tasks": []})
        self.assertTrue(self.rang())
        self.assertIn("tasks=-", self.ring_log()[-1])

    def test_internal_task_names_are_not_labels(self):
        # The payload never sends `local_bash` for a shell (only unmapped types fall back to
        # their internal name), so matching on it would keep the ring on forever, as #69 did.
        self.run_hook("stop-ring.sh", TAB,
                      {"background_tasks": [{"id": "b1", "type": "local_bash", "status": "running"}]})
        self.assertTrue(self.rang())

    def stop_record(self, sid="abcdef12-0000"):
        path = os.path.join(self.state, "dotclaude", "stops", f"{sid}.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def test_each_stop_writes_the_sessions_stop_record(self):
        # pass-respawn reads it: a plain pass respawns only after a Stop with no waits.
        before = time.time()
        self.run_hook("stop-ring.sh", TAB, {"background_tasks": [
            {"id": "t1", "type": "teammate", "status": "running"}]})
        rec = self.stop_record()
        self.assertEqual((rec["session_id"], rec["waits"], rec["tasks"]),
                         ("abcdef12-0000", [], [{"label": "teammate", "id": "t1"}]))
        self.assertGreaterEqual(rec["time"], before - 1)
        self.assertLessEqual(rec["time"], time.time() + 1)
        tasks = [{"id": "b1", "type": "shell"}, {"id": "a1", "type": "subagent"},
                 {"id": "d1", "type": "dream"}]
        self.run_hook("stop-ring.sh", TAB, {"background_tasks": tasks})
        self.assertEqual(self.stop_record()["waits"], ["shell", "subagent"])
        self.assertIn("stop quiet busy=1 tasks=shell,subagent,dream", self.ring_log()[-1])
        self.assertEqual(sorted(os.listdir(os.path.join(self.state, "dotclaude", "stops"))),
                         [".pruned", "abcdef12-0000.json"])  # renamed into place: no temp file

    def monitor_transcript(self):
        """A transcript where the Monitor tool started task m1 and a background Bash b1, in
        the shape Claude Code 2.1.296 writes (spike A10)."""
        path = os.path.join(self.tmp, "t.jsonl")
        entries = [
            {"type": "assistant", "isSidechain": False, "message": {"content": [
                {"type": "tool_use", "id": "tu_m", "name": "Monitor", "input": {"command": "x"}}]}},
            {"type": "user", "isSidechain": False, "toolUseResult": {
                "taskId": "m1", "timeoutMs": 1800000, "persistent": False},
             "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_m",
                                      "content": "Monitor started (task m1, ...)"}]}},
            {"type": "assistant", "isSidechain": False, "message": {"content": [
                {"type": "tool_use", "id": "tu_b", "name": "Bash",
                 "input": {"command": "sleep 900", "run_in_background": True}}]}},
            {"type": "user", "isSidechain": False, "toolUseResult": {"backgroundTaskId": "b1"},
             "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_b",
                                      "content": "Command running in background with ID: b1"}]}},
            # A sidechain Monitor (only a subagent's own file holds these).
            {"type": "assistant", "isSidechain": True, "message": {"content": [
                {"type": "tool_use", "id": "tu_s", "name": "Monitor", "input": {}}]}},
            {"type": "user", "isSidechain": True, "toolUseResult": {"taskId": "s1"},
             "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_s"}]}},
        ]
        with open(path, "w") as f:   # compact, as Claude Code writes its JSONL
            f.write("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in entries))
        return path

    def test_a_monitor_the_payload_calls_a_shell_is_recorded_as_a_monitor(self):
        # The Stop payload labels a Monitor `shell`; as busy work it would keep the watcher's
        # soft and wrap-up quiet. The transcript says which tool started it.
        path = self.monitor_transcript()
        tasks = [{"id": "m1", "type": "shell", "status": "running"},
                 {"id": "b1", "type": "shell", "status": "running"},
                 {"id": "s1", "type": "shell", "status": "running"}]
        self.run_hook("stop-ring.sh", TAB, {"transcript_path": path, "background_tasks": tasks})
        rec = self.stop_record()
        # s1 is a subagent's Monitor: not work the turn waits on either.
        self.assertEqual(([t["label"] for t in rec["tasks"]], rec["waits"]),
                         (["monitor", "shell", "monitor"], ["shell"]))
        self.assertIn("tasks=monitor,shell,monitor", self.ring_log()[-1])
        # A Monitor alone rings, as a lingering monitor always did.
        self.run_hook("stop-ring.sh", TAB, {"transcript_path": path, "background_tasks": tasks[:1]})
        self.assertTrue(self.rang())

    def test_task_types_needs_a_readable_transcript_and_reads_it_only_for_a_shell(self):
        types = stop_ring.task_types
        path = self.monitor_transcript()
        self.assertEqual(types([{"id": "m1", "type": "shell"}, "junk", {"type": "dream"}], path),
                         ["monitor", None, "dream"])
        self.assertEqual(types([{"id": "m1", "type": "shell"}], "/no/such.jsonl"), ["shell"])
        self.assertEqual(types([{"id": "m1", "type": "shell"}], None), ["shell"])
        self.assertEqual(types(None, path), [])
        with mock.patch.object(stop_ring, "monitor_ids") as ids:
            self.assertEqual(types([{"id": "a1", "type": "subagent"}], path), ["subagent"])
            ids.assert_not_called()
        # Odd ids never crash the hook: they stay as the payload says.
        self.assertEqual(types([{"id": ["m1"], "type": "shell"}, {"id": "m1\"x", "type": "shell"},
                                {"type": "shell"}], path), ["shell", "shell", "shell"])
        with mock.patch.object(stop_ring, "monitor_ids", side_effect=RuntimeError):
            self.assertEqual(types([{"id": "m1", "type": "shell"}], path), ["shell"])

    def test_a_monitor_far_back_in_a_long_transcript_still_counts(self):
        # The lingering monitor that matters is the one started early in a big session.
        path = self.monitor_transcript()
        with open(path, "a") as f:
            pad = json.dumps({"type": "user", "toolUseResult": {"stdout": "x" * 1024 * 1024}})
            f.write((pad + "\n") * 12)                   # 12 MiB after the Monitor call
        self.assertEqual(stop_ring.task_types([{"id": "m1", "type": "shell"}], path), ["monitor"])

    def test_only_a_taskid_answering_a_monitor_call_counts(self):
        path = os.path.join(self.tmp, "t.jsonl")
        entries = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "tu_x", "name": "SomethingElse", "input": {}}]}},
            {"type": "user", "toolUseResult": {"taskId": "x1"},
             "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_x"}]}},
            {"type": "user", "toolUseResult": {"taskId": "x2"},   # no call before it
             "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_none"}]}}]
        with open(path, "w") as f:
            f.write("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in entries))
        self.assertEqual(stop_ring.task_types([{"id": "x1", "type": "shell"},
                                               {"id": "x2", "type": "shell"}], path),
                         ["shell", "shell"])

    def test_a_later_non_result_taskid_doesnt_hide_the_monitor(self):
        # Only a result answering a Monitor call settles an id as a monitor; another line
        # naming it (here a bare key after the real result) is walked past, not trusted.
        path = self.monitor_transcript()
        with open(path, "a") as f:
            f.write(json.dumps({"type": "attachment", "attachment": {"taskId": "m1"}},
                               separators=(",", ":")) + "\n")
            f.write('{"type":"user","toolUseResult":{"taskId":"m1"')   # a partial last line
        self.assertEqual(stop_ring.task_types([{"id": "m1", "type": "shell"}], path), ["monitor"])

    def test_one_walk_settles_every_id_and_a_last_line_needs_no_newline(self):
        path = self.monitor_transcript()
        with open(path, "rb+") as f:          # drop the trailing newline
            f.seek(-1, os.SEEK_END)
            f.truncate()
        tasks = [{"id": "m1", "type": "shell"}, {"id": "b1", "type": "shell"},
                 {"id": "zz", "type": "shell"}]
        with mock.patch.object(stop_ring, "_settle", wraps=stop_ring._settle) as walk:
            self.assertEqual(stop_ring.task_types(tasks, path), ["monitor", "shell", "shell"])
        self.assertEqual(walk.call_count, 1)    # one file (no subagents dir), one walk
        # The subagents' files are skipped once the budget is spent.
        sub = os.path.join(path[:-len(".jsonl")], "subagents")
        os.makedirs(sub)
        shutil.copy(path, os.path.join(sub, "agent-x.jsonl"))
        self.assertEqual(stop_ring.monitor_ids(path, {"zz"}, budget=-1), set())

    def test_a_subagents_monitor_counts_from_its_own_transcript(self):
        # Subagent entries go to <session>/subagents/agent-<id>.jsonl (spike A3).
        path = os.path.join(self.tmp, "s.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        sub = os.path.join(self.tmp, "s", "subagents")
        os.makedirs(sub)
        shutil.copy(self.monitor_transcript(), os.path.join(sub, "agent-a1.jsonl"))
        self.assertEqual(stop_ring.task_types([{"id": "s1", "type": "shell"}], path),
                         ["monitor"])
        # An id the main transcript settles as a background Bash isn't looked for further.
        with open(path, "a") as f:
            f.write(json.dumps({"type": "user", "toolUseResult": {"backgroundTaskId": "s1"}},
                               separators=(",", ":")) + "\n")
        self.assertEqual(stop_ring.task_types([{"id": "s1", "type": "shell"}], path), ["shell"])

    def test_the_stop_record_names_the_transcript_and_unlabeled_tasks(self):
        # pass-respawn reads the transcript path from it, and blocks a plain pass on any task.
        self.run_hook("stop-ring.sh", TAB, {"transcript_path": "/x/t.jsonl", "background_tasks": [
            {"id": "m1", "type": "monitor"}, {"id": "u1"}, {"id": "e1", "type": ""}, "junk"]})
        rec = self.stop_record()
        self.assertEqual(rec["transcript_path"], "/x/t.jsonl")
        self.assertEqual(rec["tasks"], [{"label": "monitor", "id": "m1"},
                                        {"label": "unlabeled", "id": "u1"},
                                        {"label": "unlabeled", "id": "e1"},
                                        {"label": "unlabeled"}])
        self.assertEqual(rec["waits"], [])
        self.assertIn("stop rang tasks=monitor", self.ring_log()[-1])
        self.run_hook("stop-ring.sh", TAB, {"transcript_path": ["not", "a", "string"]})
        self.assertNotIn("transcript_path", self.stop_record())

    def test_the_stop_record_keeps_each_tasks_id_and_description(self):
        # pass-respawn names each task it refuses for, and `pass-respawn --tasks` lists them
        # for the session to stop. Entries follow the 2.1.296 payload (rdn: id, type, status,
        # description, and a shell's command, which the record leaves out).
        long = "Wait for " + "x" * 300
        self.run_hook("stop-ring.sh", TAB, {"background_tasks": [
            {"id": "b0fzd27l4", "type": "shell", "status": "running",
             "description": "Wait for the deploy run to finish",
             "command": "gh run watch 38350970777 --exit-status"},
            {"id": "a1", "type": "subagent", "status": "running", "agent_type": "writer",
             "description": 'Fix the "axis"\nlabels\x1b[31m now' + chr(0x202e)},
            {"id": "w1", "type": "workflow", "status": "running", "description": long},
            {"id": "odd id", "type": "monitor", "description": 7},
            {"id": "k1", "type": "new\x1bkind\nx"}]})
        tasks = self.stop_record()["tasks"]
        self.assertEqual(tasks[0], {"label": "shell", "id": "b0fzd27l4",
                                    "description": "Wait for the deploy run to finish"})
        # Control and format characters go, double quotes become single, whitespace folds.
        self.assertEqual(tasks[1], {"label": "subagent", "id": "a1",
                                    "description": "Fix the 'axis' labels[31m now"})
        self.assertEqual(tasks[2]["description"], long[:stop_ring.DESC_CAP - 3] + "...")
        self.assertEqual(len(tasks[2]["description"]), stop_ring.DESC_CAP)
        # An id that isn't a plain name and a description that isn't a string are left out.
        self.assertEqual(tasks[3], {"label": "monitor"})
        # A type name cleaning would change can't be one of Claude Code's: it is unlabeled, so
        # it can't turn into a label a plain pass ignores (review round 3).
        self.assertEqual(tasks[4], {"label": "unlabeled", "id": "k1"})

    def test_a_type_cleaning_would_change_is_unlabeled(self):
        self.run_hook("stop-ring.sh", TAB, {"background_tasks": [
            {"id": "d1", "type": "dream "}, {"id": "c1", "type": "cloud\tsession"},
            {"id": "a1", "type": "artifact watch"}]})
        rec = self.stop_record()
        self.assertEqual([t["label"] for t in rec["tasks"]],
                         ["unlabeled", "unlabeled", "artifact watch"])
        self.assertEqual(rec["waits"], [])
        # A payload type spelled `artifact watch` has no page: lanelib blocks it.
        self.assertNotIn("url", rec["tasks"][2])

    def artifact_watch(self, url="https://claude.ai/artifact/8JLmWLDftm9VdGcLQnGr76", **extra):
        """A Stop payload entry for the live watch the Artifact tool arms on a publish, in
        2.1.296's shape: a monitor_ws, labeled `monitor`, with no server (rdn) and the
        description Yt builds, as session f857d709's task notices show it (2026-10-12)."""
        return {"id": "s31udgb0s", "type": "monitor", "status": "running",
                "description": f"live updates for artifact {url} (auto-armed on publish)",
                **extra}

    def test_an_artifact_watch_is_labeled_and_keeps_its_url(self):
        # The model never sees its id, so it can't stop one, and a plain pass must not wait
        # on it (incident e7cc7b9a, 2026-10-13).
        code = "https://claude.ai/code/artifact/0b5e7c1a-2f4d-4c1e-9a7b-3d2f1e0c9b8a"
        self.run_hook("stop-ring.sh", TAB, {"background_tasks": [
            self.artifact_watch(), self.artifact_watch(code)]})
        tasks = self.stop_record()["tasks"]
        self.assertEqual([(t["label"], t["url"]) for t in tasks],
                         [("artifact watch", "https://claude.ai/artifact/8JLmWLDftm9VdGcLQnGr76"),
                          ("artifact watch", code)])
        self.assertEqual(tasks[0]["id"], "s31udgb0s")
        self.assertIn("stop rang tasks=artifact_watch,artifact_watch", self.ring_log()[-1])

    def test_only_a_monitor_with_the_watch_description_is_an_artifact_watch(self):
        types = stop_ring.task_types
        watch = self.artifact_watch()
        self.assertEqual(types([watch], None), ["artifact watch"])
        # An MCP monitor carries its server; a Monitor the model started is a shell or has
        # its own description; the prefix must open the description and name a claude.ai page.
        self.assertEqual(types([{**watch, "server": "x", "tool": "y"}], None), ["monitor"])
        self.assertEqual(types([{**watch, "type": "shell"}], None), ["shell"])
        # A URL of another shape (a trailing slash, a query) isn't one seen live: it blocks and
        # is named, the safe side.
        for desc in ["deploy events", "see live updates for artifact https://claude.ai/artifact/x",
                     "live updates for artifact https://evil.example/artifact/x (c)",
                     "live updates for artifact https://claude.ai/artifacts/x (c)",
                     "live updates for artifact https://claude.ai/artifact/x/ (c)",
                     "live updates for artifact https://claude.ai/artifact/x?v=1 (c)", None]:
            self.assertEqual(types([{**watch, "description": desc}], None), ["monitor"], desc)
        self.assertIsNone(stop_ring.artifact_url({**watch, "server": "x"}))
        self.assertIsNone(stop_ring.artifact_url("junk"))

    def test_the_stop_record_keeps_everything_since_the_last_prompts(self):
        # pass-respawn copies `replies` for the respawned session's banner and Ctrl-b Up. A Stop
        # a hook blocked and the one ending the continued turn share a prompt_id (spike A5).
        self.run_hook("stop-ring.sh", TAB, {"prompt_id": "p1", "last_assistant_message": "One."})
        self.run_hook("stop-ring.sh", TAB, {"prompt_id": "p1", "stop_hook_active": True,
                                            "last_assistant_message": "Two, " + chr(0x00E9)})
        rec = self.stop_record()
        self.assertEqual([(r["prompt_id"], r["text"]) for r in rec["replies"]],
                         [("p1", "One."), ("p1", "Two, " + chr(0x00E9))])
        self.assertEqual(rec["waits"], [])  # the rest of the record is as before
        raw = open(os.path.join(self.state, "dotclaude", "stops", "abcdef12-0000.json"),
                   "rb").read()
        self.assertIn(chr(0x00E9).encode(), raw)  # ensure_ascii=False, as UTF-8
        self.run_hook("stop-ring.sh", TAB, {"prompt_id": "p2", "last_assistant_message": None})
        self.assertEqual(len(self.stop_record()["replies"]), 2)  # nothing to add

    def test_a_claude_p_stop_keeps_no_replies(self):
        self.run_hook("stop-ring.sh", P_RUN, {"prompt_id": "p1", "last_assistant_message": "x"})
        rec = self.stop_record()
        self.assertNotIn("replies", rec)
        self.assertEqual(rec["waits"], [])

    def test_a_corrupt_previous_record_starts_fresh(self):
        stops = os.path.join(self.state, "dotclaude", "stops")
        os.makedirs(stops)
        for junk in ("{not json", '{"replies": "nope"}', '[1, 2]',
                     '{"replies": [5, {"prompt_id": 1, "text": "x"}, {"prompt_id": "p0"}]}',
                     "[" * 100000):  # json raises RecursionError, not ValueError
            with self.subTest(junk=junk[:20]):
                with open(os.path.join(stops, "abcdef12-0000.json"), "w") as f:
                    f.write(junk)
                self.run_hook("stop-ring.sh", TAB, {"prompt_id": "p1",
                                                    "last_assistant_message": "New."})
                self.assertEqual([r["text"] for r in self.stop_record()["replies"]], ["New."])

    def test_merging_dedupes_and_keeps_five_turns(self):
        merge = stop_ring.merge_replies
        r = merge(None, "a", "p1", 1)
        self.assertEqual(r, [{"prompt_id": "p1", "text": "a", "time": 1}])
        self.assertEqual(merge(r, "a", "p1", 2), r)              # the same reply again
        self.assertEqual(len(merge(r, "a", "p2", 2)), 2)         # same text, a new turn
        for pid in ("p2", "p3", "p4", "p5", "p6"):
            r = merge(r, "reply " + pid, pid, 3)
        self.assertEqual([x["prompt_id"] for x in r], ["p2", "p3", "p4", "p5", "p6"])
        r = merge(r, "more", "p6", 4)
        self.assertEqual([x["prompt_id"] for x in r], ["p2", "p3", "p4", "p5", "p6", "p6"])
        self.assertEqual(merge(None, "", "p1", 1), [])
        self.assertEqual(merge(None, ["x"], "p1", 1), [])

    def test_a_stop_with_no_prompt_id_is_a_turn_of_its_own(self):
        merge = stop_ring.merge_replies
        r = merge(None, "x", None, 1)
        self.assertEqual(r[0]["prompt_id"], "none-1.000000")
        r = merge(r, "y", 5, 2)
        r = merge(r, "z", "", 3)
        self.assertEqual([x["prompt_id"] for x in r],
                         ["none-1.000000", "none-2.000000", "none-3.000000"])
        r = merge(r, "z", None, 4)  # the same text, but a new Stop with no id: not a repeat
        self.assertEqual(len(r), 4)
        # The hook: the newest Stop without a prompt_id doesn't join the turn before it.
        self.run_hook("stop-ring.sh", TAB, {"prompt_id": "p1", "last_assistant_message": "One."})
        self.run_hook("stop-ring.sh", TAB, {"last_assistant_message": "Notice reply."})
        ids = [x["prompt_id"] for x in self.stop_record()["replies"]]
        self.assertEqual(ids[0], "p1")
        self.assertTrue(ids[1].startswith("none-"))

    def test_merging_cuts_each_reply_to_64_kib(self):
        cap = 64 * 1024
        reply = "a" + chr(0x00E9) * cap  # two bytes each, so the cut can land mid-character
        (kept,) = stop_ring.merge_replies(None, reply, "p1", 1)
        body, note = kept["text"].rsplit("\n", 1)
        self.assertLessEqual(len(kept["text"].encode()), cap)
        self.assertGreater(len(kept["text"].encode()), cap - 100)
        self.assertTrue(reply.startswith(body))
        self.assertEqual(note, f"[cut to 64 KiB: the reply was {len(reply.encode())} bytes]")
        exact = "b" * cap  # at the cap: kept whole, no note
        self.assertEqual(stop_ring.merge_replies(None, exact, "p1", 1)[0]["text"], exact)

    def test_over_128_kib_whole_older_turns_go_first(self):
        r = None
        for pid, ch, kib in (("p1", "a", 60), ("p2", "b", 60), ("p3", "c", 20)):
            r = stop_ring.merge_replies(r, ch * (kib * 1024), pid, 1)
        self.assertEqual([(x["prompt_id"], len(x["text"]) // 1024) for x in r],
                         [("p2", 60), ("p3", 20)])
        self.assertNotIn("dropped", r[0])

    def test_over_128_kib_in_one_turn_its_oldest_replies_go_with_a_note(self):
        r = None
        for i, (ch, kib) in enumerate((("a", 60), ("b", 60), ("c", 20))):
            r = stop_ring.merge_replies(r, ch * (kib * 1024), "p1", 10 + i)
        self.assertEqual(r[0], {"prompt_id": "p1", "dropped": 1, "time": 10,
                                "text": "[1 earlier reply of this turn dropped: over 128 KiB]"})
        self.assertEqual([(x["text"][0], len(x["text"]) // 1024) for x in r[1:]],
                         [("b", 60), ("c", 20)])
        self.assertLessEqual(sum(len(x["text"].encode()) for x in r), 128 * 1024)
        r = stop_ring.merge_replies(r, "d" * (60 * 1024), "p1", 13)  # the count carries over
        self.assertEqual((r[0]["dropped"], r[0]["time"]), (2, 10))
        self.assertEqual(r[0]["text"], "[2 earlier replies of this turn dropped: over 128 KiB]")
        self.assertEqual([x["text"][0] for x in r[1:]], ["c", "d"])
        r = stop_ring.merge_replies(r, "next turn", "p2", 14)  # a new turn: the note stays
        self.assertEqual([x["prompt_id"] for x in r], ["p1", "p1", "p1", "p2"])

    def test_the_shim_rings_by_its_defaults_without_its_module(self):
        # As the old inline code did when python3 failed: exit 0, no record, and a ring.
        hooks = os.path.join(self.tmp, "hooks")
        os.mkdir(hooks)
        for name in ("stop-ring.sh", "session-pane.sh"):
            shutil.copy(os.path.join(HOOKS, name), hooks)
        self.logged_before = len(self.ring_log())
        p = subprocess.run(["bash", os.path.join(hooks, "stop-ring.sh")],
                           input=json.dumps({"session_id": "abcdef12-0000"}),
                           capture_output=True, text=True, timeout=10, env={**self.env, **TAB})
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.decided()
        self.assertTrue(self.rang())
        self.assertIsNone(self.stop_record())

    def test_a_previous_record_is_read_as_utf8_in_any_locale(self):
        stops = os.path.join(self.state, "dotclaude", "stops")
        os.makedirs(stops)
        with open(os.path.join(stops, "abcdef12-0000.json"), "w", encoding="utf-8") as f:
            json.dump({"replies": [{"prompt_id": "p1", "text": "caf" + chr(0x00E9)}]}, f,
                      ensure_ascii=False)
        self.run_hook("stop-ring.sh", {**TAB, **ASCII_LOCALE},
                      {"prompt_id": "p2", "last_assistant_message": "next"})
        self.assertEqual([x["text"] for x in self.stop_record()["replies"]],
                         ["caf" + chr(0x00E9), "next"])

    def test_the_event_is_read_as_utf8_in_any_locale(self):
        self.logged_before = len(self.ring_log())
        body = json.dumps({"session_id": "abcdef12-0000", "prompt_id": "p1",
                           "last_assistant_message": "caf" + chr(0x00E9)}, ensure_ascii=False)
        p = subprocess.run(["bash", os.path.join(HOOKS, "stop-ring.sh")], input=body.encode(),
                           capture_output=True, timeout=10,
                           env={**self.env, **TAB, **ASCII_LOCALE})
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        self.decided()
        self.assertEqual(self.stop_record()["replies"][-1]["text"], "caf" + chr(0x00E9))

    def test_a_whitespace_only_reply_is_no_turn(self):
        merge = stop_ring.merge_replies
        r = merge(None, "a", "p1", 1)
        self.assertEqual(merge(r, " \n ", "p2", 2), r)
        old = r + [{"prompt_id": "p2", "text": "  ", "time": 2}]
        self.assertEqual(merge(old, "c", "p1", 3),
                         [{"prompt_id": "p1", "text": "a", "time": 1},
                          {"prompt_id": "p1", "text": "c", "time": 3}])

    def test_a_lone_surrogate_becomes_a_question_mark(self):
        (kept,) = stop_ring.merge_replies(None, "a" + chr(0xD800) + "b", "p1", 1)
        self.assertEqual(kept["text"], "a?b")
        # The hook too, from raw JSON (json.dumps can't send a lone surrogate's escape).
        self.logged_before = len(self.ring_log())
        p = subprocess.run(["bash", os.path.join(HOOKS, "stop-ring.sh")],
                           input='{"session_id": "abcdef12-0000", "prompt_id": "p9", '
                                 '"last_assistant_message": "x\\ud800y"}',
                           capture_output=True, text=True, timeout=10,
                           env={**self.env, **TAB})
        self.assertEqual(p.returncode, 0)
        self.decided()
        self.assertEqual(self.stop_record()["replies"][-1]["text"], "x?y")

    def test_old_stop_records_are_pruned_once_a_day(self):
        stops = os.path.join(self.state, "dotclaude", "stops")
        os.makedirs(stops)
        now = time.time()

        def touch(name, age):
            path = os.path.join(stops, name)
            with open(path, "w") as f:
                f.write("{}")
            os.utime(path, (now - age, now - age))
        touch("old.json", 8 * 86400)
        touch("recent.json", 6 * 86400)
        stop_ring.prune(stops, now)
        self.assertEqual(sorted(os.listdir(stops)), [".pruned", "recent.json"])
        touch("old.json", 8 * 86400)
        stop_ring.prune(stops, now + 3600)  # within the day: no pass
        self.assertIn("old.json", os.listdir(stops))
        stop_ring.prune(stops, now + 86401)  # a day later: recent.json is now 7 days old too
        self.assertEqual(sorted(os.listdir(stops)), [".pruned"])
        stop_ring.prune(os.path.join(self.tmp, "nowhere"), now)  # best-effort: no error
        # The hook prunes too.
        touch("old.json", 8 * 86400)
        os.utime(os.path.join(stops, ".pruned"), (now - 90000, now - 90000))
        self.run_hook("stop-ring.sh", TAB)
        self.assertEqual(sorted(os.listdir(stops)), [".pruned", "abcdef12-0000.json"])

    def test_a_subagent_stop_or_an_unsafe_id_writes_no_stop_record(self):
        self.run_hook("stop-ring.sh", TAB, {"agent_id": "a1"})
        self.assertIsNone(self.stop_record())
        for sid in ("../evil", "", ".hidden", "a/b"):
            with self.subTest(sid=sid):
                self.run_hook("stop-ring.sh", TAB, {"session_id": sid})
        self.assertFalse(os.path.exists(os.path.join(self.state, "dotclaude", "stops")) and
                         os.listdir(os.path.join(self.state, "dotclaude", "stops")))
        self.assertFalse(os.path.exists(os.path.join(self.state, "dotclaude", "evil.json")))

    DEQUEUE = {"type": "queue-operation", "operation": "dequeue",
               "timestamp": "2026-10-06T19:26:22.917Z", "sessionId": "abcdef12-0000"}

    def test_a_stop_that_a_queued_input_resumes_stays_quiet(self):
        # karaoke, 2026-10-06: a subagent finished mid-turn, so background_tasks was empty at
        # the Stop while its notice waited in the queue; the dequeue started the next turn 0.5 s
        # later. Shape copied from that transcript.
        path = self.transcript({"type": "assistant", "message": {"content": "done"}})
        self.run_hook("stop-ring.sh", TAB, {"transcript_path": path}, wait=False)
        self.transcript(self.DEQUEUE)
        self.decided()
        self.assertIn("stop quiet resumed=1 tasks=- session=abcdef12", self.ring_log()[-1])
        self.assertFalse(self.seen("SoundPlayer"))

    def test_a_stop_rings_when_no_queued_input_follows(self):
        # An enqueue alone is a notice still waiting; only a dequeue (or popAll) starts a turn.
        # A dequeue from before the Stop doesn't count.
        path = self.transcript(self.DEQUEUE)
        self.run_hook("stop-ring.sh", TAB, {"transcript_path": path}, wait=False)
        self.transcript({"type": "queue-operation", "operation": "enqueue", "content": "x"},
                        {"type": "system", "subtype": "stop_hook_summary"})
        self.decided()
        self.assertTrue(self.rang())
        self.assertIn("rang tasks=-", self.ring_log()[-1])

    def test_a_popall_counts_as_resumed(self):
        path = self.transcript()
        self.run_hook("stop-ring.sh", TAB, {"transcript_path": path}, wait=False)
        self.transcript({"type": "queue-operation", "operation": "popAll"})
        self.decided()
        self.assertIn("quiet resumed=1", self.ring_log()[-1])

    def test_an_unreadable_transcript_still_rings(self):
        for path in (os.path.join(self.tmp, "missing.jsonl"), 7, ""):
            with self.subTest(path=path):
                self.run_hook("stop-ring.sh", TAB, {"transcript_path": path})
                self.assertIn("rang tasks=-", self.ring_log()[-1])

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
        self.assertIn("rang tasks=- session=abcdef12 kind=background attended=0 pane=%9", self.ring_log()[-1])
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
        self.assertIn("quiet tasks=- session=abcdef12 kind=background", self.ring_log()[-1])

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
