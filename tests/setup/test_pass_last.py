"""tmux/pass-last: the Ctrl-b P popup that shows the reply a tab's Claude ended on before a
plain /pass (stdlib only).

It reads $XDG_STATE_HOME/dotclaude/pass-last/<pane number>.json and shows the message only when
the entry's tab is this pane on this tmux server. A stub tmux answers `display` with the current
pane ($STUB_PANE) or the server line ($STUB_SERVER; empty fails). Output is not a terminal here,
so the script prints instead of starting less."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "tmux", "pass-last")

STUB = """#!/usr/bin/env bash
{ printf '%s' "$(basename "$0")"; printf '\\x1f%s' "$@"; printf '\\n'; } >> "$STUB_LOG"
case "$*" in
  *pane_id*) printf '%s\\n' "$STUB_PANE" ;;
  display*) [ -n "${STUB_SERVER:-}" ] || exit 1; printf '%s\\n' "$STUB_SERVER" ;;
esac
exit 0
"""

SOCKET = "/tmp/tmux-1000/default"
SERVER = f"1791222157 4321 {SOCKET}"
TAB = {"socket": SOCKET, "server_start": 1791222157, "server_pid": 4321, "pane": "%7"}
NONE = "No reply saved from a /pass in this tab."


class PassLast(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        os.mkdir(stubs)
        with open(os.path.join(stubs, "tmux"), "w") as f:
            f.write(STUB)
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        self.log = os.path.join(self.tmp, "calls.log")
        self.dir = os.path.join(self.tmp, "state", "dotclaude", "pass-last")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], STUB_LOG=self.log,
                        HOME=os.path.join(self.tmp, "home"), STUB_SERVER=SERVER,
                        STUB_PANE="%7", XDG_STATE_HOME=os.path.join(self.tmp, "state"))

    def entry(self, **fields):
        e = {"tab": TAB, "from_session": "old-session-1",
             "written_at": time.mktime((2026, 10, 12, 14, 5, 0, 0, 0, -1)),
             "message": "Done: the PR is up.\nNext: review it.", "shown": True, **fields}
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, "7.json"), "w") as f:
            json.dump(e, f)

    def show(self, *args):
        p = subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, timeout=10,
                           env=self.env, stdin=subprocess.DEVNULL)
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        return p.stdout

    def test_an_entry_for_this_tab_shows_the_whole_reply(self):
        self.entry(message="\n".join(f"line {i}" for i in range(1, 101)))
        out = self.show("%7")
        self.assertTrue(out.startswith(
            "Last reply before the pass (2026-10-12 14:05, session old-session-1):\n\nline 1\n"))
        self.assertTrue(out.endswith("line 100\n"))  # no cap: the popup scrolls
        self.assertIn(["tmux", "display", "-p", "-t", "%7",
                       "#{start_time} #{pid} #{socket_path}"], self.calls())

    def test_shown_does_not_matter_and_the_entry_stays(self):
        self.entry(shown=False)
        self.assertIn("Done: the PR is up.", self.show("%7"))
        self.assertIn("Done: the PR is up.", self.show("%7"))
        with open(os.path.join(self.dir, "7.json")) as f:
            self.assertIs(json.load(f)["shown"], False)

    def test_no_pane_argument_asks_tmux_for_the_current_pane(self):
        self.entry()
        self.assertIn("Done: the PR is up.", self.show())
        self.assertEqual(self.calls()[0], ["tmux", "display", "-p", "#{pane_id}"])

    def test_no_entry_says_so(self):
        self.assertEqual(self.show("%7"), NONE + "\n")
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "7.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(self.show("%7"), NONE + "\n")

    def test_the_wrong_tab_shows_nothing(self):
        for field, value in (("socket", "/tmp/tmux-1000/other"), ("server_start", 1),
                             ("server_pid", 1), ("pane", "%8")):
            with self.subTest(field=field):
                self.entry(tab={**TAB, field: value})
                out = self.show("%7")
                self.assertTrue(out.startswith(NONE), out)
                self.assertNotIn("Done", out)

    def test_a_bad_pane_or_an_unreadable_server_shows_nothing(self):
        self.entry()
        for pane in ("7", "%7; rm -rf x", "../7"):
            with self.subTest(pane=pane):
                self.assertNotIn("Done", self.show(pane))
        self.env["STUB_SERVER"] = ""
        self.assertTrue(self.show("%7").startswith(NONE))

    def test_control_characters_are_dropped(self):
        self.entry(message="red " + chr(27) + "[31mtext" + chr(7))
        self.assertTrue(self.show("%7").endswith("red [31mtext\n"))

    def calls(self):
        with open(self.log) as f:
            return [line.split("\x1f") for line in f.read().splitlines()]


if __name__ == "__main__":
    unittest.main()
