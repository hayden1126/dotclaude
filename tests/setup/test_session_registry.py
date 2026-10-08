"""hooks/session-registry.sh: the record of which Claude session is open in which tmux tab, kept
for tmux/claude-restore (stdlib only).

SessionStart writes $XDG_STATE_HOME/dotclaude/open-sessions/<session_id>.json for a tab
(TMUX_PANE set, ATTENDED not 0, not a subagent), naming the tmux server it runs under (socket
path and start time) so claude-restore can tell which tabs died with an earlier server.
SessionEnd deletes the entry on an explicit end (/exit, /clear, logout) and only marks it on
`other`, which a window kill, a SIGTERM and a tmux server kill all send (probed 2026-10-05), so a
shutdown can't be told from a closed window at hook time. In a tab it then hands the payload to
~/.local/bin/claude-saved, fail-open. A stub tmux answers `display` and logs each call's argv, one
argument per field."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "session-registry.sh")

STUB = """#!/usr/bin/env bash
{ printf '%s' "$(basename "$0")"; printf '\\x1f%s' "$@"; printf '\\n'; } >> "$STUB_LOG"
case "$1" in
  display|display-message)
    [ -z "${STUB_NO_SERVER:-}" ] || exit 1
    printf '%s %s %s %s\\n' "$STUB_START" "$STUB_PID" "${STUB_WINDOW:-3}" "$STUB_SOCKET" ;;
esac
exit 0
"""

SID = "0b6f2a1e-1111-4c2d-9e3f-aaaaaaaaaaaa"
NEW = "7c1d9e2f-2222-4a5b-8c6d-bbbbbbbbbbbb"
SOCKET = "/tmp/tmux-1000/my socket"   # a space: the path is the rest of the display line
START = 1791222157
PID = 4321
TAB = {"TMUX": "/tmp/tmux-1000/default,1,0", "TMUX_PANE": "%7",
       "CLAUDE_CODE_SESSION_ATTENDED": "1"}


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        os.mkdir(stubs)
        with open(os.path.join(stubs, "tmux"), "w") as f:
            f.write(STUB)
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        self.log = os.path.join(self.tmp, "calls.log")
        self.dir = os.path.join(self.tmp, "state", "dotclaude", "open-sessions")
        # The test may itself run inside a Claude session in a tmux tab: start from a clean env.
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.home = os.path.join(self.tmp, "home")   # never the real ~/.local/bin/claude-saved
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], STUB_LOG=self.log,
                        HOME=self.home, XDG_STATE_HOME=os.path.join(self.tmp, "state"),
                        STUB_START=str(START), STUB_PID=str(PID), STUB_SOCKET=SOCKET)

    def fire(self, event, session=TAB, **payload):
        body = {"session_id": SID, "hook_event_name": event, "cwd": "/home/u/code/dna",
                "transcript_path": f"/home/u/.claude/projects/dna/{payload.get('session_id', SID)}.jsonl",
                **payload}
        p = subprocess.run(["bash", HOOK], input=json.dumps(body), capture_output=True,
                           text=True, timeout=10, env={**self.env, **session})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((p.stdout, p.stderr), ("", ""))

    def start(self, session=TAB, **payload):
        self.fire("SessionStart", session, **{"source": "startup", **payload})

    def end(self, reason, **payload):
        self.fire("SessionEnd", reason=reason, **payload)

    def entries(self):
        if not os.path.isdir(self.dir):
            return {}
        out = {}
        for name in os.listdir(self.dir):
            if name.endswith(".json"):
                with open(os.path.join(self.dir, name)) as f:
                    out[name[:-5]] = json.load(f)
        return out

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [line.split("\x1f") for line in f.read().splitlines()]

    def test_a_tab_start_writes_its_entry(self):
        self.start()
        e = self.entries()[SID]
        self.assertEqual({k: e[k] for k in ("session_id", "cwd", "pane", "window_index",
                                             "socket", "server_start", "server_pid")},
                         {"session_id": SID, "cwd": "/home/u/code/dna", "pane": "%7",
                          "window_index": 3, "socket": SOCKET, "server_start": START,
                          "server_pid": PID})
        self.assertNotIn("boot_id", e)
        self.assertTrue(e["transcript_path"].endswith(SID + ".jsonl"))
        self.assertIsInstance(e["ts"], (int, float))
        self.assertNotIn("ended_other_at", e)
        self.assertEqual(self.calls(), [["tmux", "display", "-p", "-t", "%7",
                                         "#{start_time} #{pid} #{window_index} #{socket_path}"]])
        self.assertEqual(sorted(os.listdir(self.dir)), [SID + ".json"])  # no tmp left behind

    def test_every_source_refreshes_the_entry(self):
        self.start()
        last = self.entries()[SID]["ts"]
        for source in ("resume", "clear", "compact"):
            with self.subTest(source=source):
                time.sleep(0.01)
                self.fire("SessionStart", source=source)
                ts = self.entries()[SID]["ts"]
                self.assertGreater(ts, last)
                last = ts

    def test_a_restart_clears_an_old_end_mark(self):
        self.start()
        self.end("other")
        self.fire("SessionStart", source="resume")
        self.assertNotIn("ended_other_at", self.entries()[SID])

    def test_no_entry_outside_tmux(self):
        self.start(session={"CLAUDE_CODE_SESSION_ATTENDED": "1"})
        self.assertEqual(self.entries(), {})

    def test_no_entry_when_the_server_cannot_be_read(self):
        self.env["STUB_NO_SERVER"] = "1"
        self.start()
        self.assertEqual(self.entries(), {})

    def test_no_entry_without_a_directory(self):
        self.start(cwd="")
        self.assertEqual(self.entries(), {})

    def test_no_entry_for_a_p_run(self):
        # A `claude -p` run started from a tab inherits its TMUX_PANE.
        self.start(session={**TAB, "CLAUDE_CODE_SESSION_ATTENDED": "0"})
        self.assertEqual(self.entries(), {})

    def test_no_entry_for_a_subagent(self):
        self.start(agent_id="a1", agent_type="writer")
        self.assertEqual(self.entries(), {})

    def test_an_unsafe_session_id_writes_nothing(self):
        for sid in ("../../evil", "a b", "", "x;rm"):
            with self.subTest(sid=sid):
                self.start(session_id=sid)
        self.assertEqual(self.entries(), {})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "state", "evil.json")))

    def test_clear_replaces_the_old_id_with_the_new(self):
        self.start()
        self.end("clear")
        self.fire("SessionStart", source="clear", session_id=NEW)
        self.assertEqual(list(self.entries()), [NEW])

    def test_an_explicit_end_deletes_the_entry(self):
        for reason in ("prompt_input_exit", "logout", "clear", "something_new"):
            with self.subTest(reason=reason):
                self.start()
                self.end(reason)
                self.assertEqual(self.entries(), {})

    def test_other_marks_and_keeps_the_entry(self):
        self.start()
        self.end("other")
        e = self.entries()[SID]
        self.assertIsInstance(e["ended_other_at"], (int, float))
        self.assertEqual((e["pane"], e["server_start"]), ("%7", START))

    def test_an_end_for_an_unknown_session_writes_nothing(self):
        self.end("other")
        self.assertEqual(self.entries(), {})

    def test_bad_input_still_exits_clean(self):
        for text in ("", "{not json", "[1, 2]"):
            with self.subTest(text=text):
                p = subprocess.run(["bash", HOOK], input=text, capture_output=True, text=True,
                                   timeout=10, env={**self.env, **TAB})
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(self.entries(), {})

    # --- the hand-off to claude-saved -------------------------------------------------------

    def saved_stub(self, body="", mode=0o755):
        """A claude-saved that logs its args and stdin, then runs body."""
        path = os.path.join(self.home, ".local", "bin", "claude-saved")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write('#!/usr/bin/env bash\n'
                    '{ printf "%s\\n" "$*"; cat; printf "\\n"; } >> "$STUB_LOG.saved"\n' + body)
        os.chmod(path, mode)

    def handed(self):
        """Each hand-off as (args, payload)."""
        path = self.log + ".saved"
        if not os.path.exists(path):
            return []
        with open(path) as f:
            lines = f.read().splitlines()
        return [(lines[i], json.loads(lines[i + 1])) for i in range(0, len(lines), 2)]

    def test_a_tab_hands_each_start_and_end_to_claude_saved(self):
        self.saved_stub()
        self.start()
        self.end("clear")
        handed = self.handed()
        self.assertEqual([(args, d["hook_event_name"], d["session_id"]) for args, d in handed],
                         [("hook", "SessionStart", SID), ("hook", "SessionEnd", SID)])
        self.assertEqual(handed[1][1]["reason"], "clear")

    def test_no_hand_off_outside_a_tab_or_without_claude_saved(self):
        self.saved_stub(mode=0o644)   # linked but not executable
        self.start()
        self.saved_stub()
        self.fire("SessionEnd", session={"CLAUDE_CODE_SESSION_ATTENDED": "1"}, reason="other")
        self.start(session={**TAB, "CLAUDE_CODE_SESSION_ATTENDED": "0"})
        self.start(agent_id="a1")
        self.assertEqual(self.handed(), [])

    def test_a_failing_claude_saved_changes_nothing(self):
        self.saved_stub('echo noise; echo more >&2; exit 3\n')
        self.start()   # fire() asserts exit 0 and no output
        self.assertIn(SID, self.entries())
        self.assertEqual(len(self.handed()), 1)

    def test_a_hung_claude_saved_is_cut_off(self):
        self.saved_stub('exec sleep 30\n')
        t = time.monotonic()
        self.start()
        self.assertLess(time.monotonic() - t, 8)
        self.assertIn(SID, self.entries())


class Wiring(unittest.TestCase):
    def test_the_baseline_runs_the_hook_on_start_and_end(self):
        with open(os.path.join(REPO, "settings.json")) as f:
            hooks = json.load(f)["hooks"]

        def matchers(event):
            return [g.get("matcher") for g in hooks.get(event, [])
                    if any("session-registry.sh" in h.get("command", "")
                           for h in g.get("hooks", []))]

        start = matchers("SessionStart")
        self.assertEqual(len(start), 1)
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertTrue(start[0] is None or re.fullmatch(start[0], source) or
                                source in start[0].split("|"))
        self.assertEqual(len(matchers("SessionEnd")), 1)


if __name__ == "__main__":
    unittest.main()
