"""hooks/session-registry.sh: the record of which Claude session is open in which tmux tab, kept
for tmux/claude-restore (stdlib only).

SessionStart writes $XDG_STATE_HOME/dotclaude/open-sessions/<session_id>.json for a tab
(TMUX_PANE set, ATTENDED not 0, not a subagent). SessionEnd deletes it on an explicit end
(/exit, /clear, logout) and only marks it on `other`, which a window kill, a SIGTERM and a tmux
server kill all send (probed 2026-10-05), so a shutdown can't be told from a closed window at
hook time. A stub tmux answers `display` with a window index and records every call."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "session-registry.sh")

STUB = """#!/usr/bin/env bash
printf '%s\\n' "$(basename "$0") $*" >> "$STUB_LOG"
case "$1" in
  display|display-message) printf '%s\\n' "${STUB_WINDOW:-3}" ;;
esac
exit 0
"""

SID = "0b6f2a1e-1111-4c2d-9e3f-aaaaaaaaaaaa"
NEW = "7c1d9e2f-2222-4a5b-8c6d-bbbbbbbbbbbb"
BOOT = "11111111-2222-3333-4444-555555555555"
TAB = {"TMUX": "/tmp/tmux-stub,1,0", "TMUX_PANE": "%7", "CLAUDE_CODE_SESSION_ATTENDED": "1"}


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        os.mkdir(stubs)
        with open(os.path.join(stubs, "tmux"), "w") as f:
            f.write(STUB)
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        boot = os.path.join(self.tmp, "boot_id")
        with open(boot, "w") as f:
            f.write(BOOT + "\n")
        self.log = os.path.join(self.tmp, "calls.log")
        self.dir = os.path.join(self.tmp, "state", "dotclaude", "open-sessions")
        # The test may itself run inside a Claude session in a tmux tab: start from a clean env.
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], STUB_LOG=self.log,
                        XDG_STATE_HOME=os.path.join(self.tmp, "state"),
                        DOTCLAUDE_BOOT_ID_FILE=boot)

    def fire(self, event, session=TAB, **payload):
        body = {"session_id": SID, "hook_event_name": event, "cwd": "/home/u/code/dna",
                "transcript_path": f"/home/u/.claude/projects/dna/{payload.get('session_id', SID)}.jsonl",
                **payload}
        p = subprocess.run(["bash", HOOK], input=json.dumps(body), capture_output=True,
                           text=True, timeout=10, env={**self.env, **session})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((p.stdout, p.stderr), ("", ""))

    def start(self, session=TAB, **payload):
        self.fire("SessionStart", session, source="startup", **payload)

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

    def test_a_tab_start_writes_its_entry(self):
        self.start()
        e = self.entries()[SID]
        self.assertEqual({k: e[k] for k in ("session_id", "cwd", "pane", "window_index",
                                             "boot_id")},
                         {"session_id": SID, "cwd": "/home/u/code/dna", "pane": "%7",
                          "window_index": 3, "boot_id": BOOT})
        self.assertTrue(e["transcript_path"].endswith(SID + ".jsonl"))
        self.assertIsInstance(e["ts"], (int, float))
        self.assertNotIn("ended_other_at", e)
        with open(self.log) as f:
            self.assertIn("tmux display -p -t %7 #{window_index}", f.read())
        self.assertEqual(sorted(os.listdir(self.dir)), [SID + ".json"])  # no tmp left behind

    def test_every_source_refreshes_the_entry(self):
        for source in ("startup", "resume", "compact"):
            with self.subTest(source=source):
                self.fire("SessionStart", source=source)
                self.assertIn(SID, self.entries())

    def test_a_restart_clears_an_old_end_mark(self):
        self.start()
        self.end("other")
        self.fire("SessionStart", source="resume")
        self.assertNotIn("ended_other_at", self.entries()[SID])

    def test_no_entry_outside_tmux(self):
        self.start(session={"CLAUDE_CODE_SESSION_ATTENDED": "1"})
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
        self.assertEqual(e["pane"], "%7")

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


if __name__ == "__main__":
    unittest.main()
