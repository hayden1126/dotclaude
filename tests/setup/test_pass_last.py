"""tmux/pass-last: the Ctrl-b P popup that shows what a tab's Claude said before a plain /pass
(stdlib only).

It reads $XDG_STATE_HOME/dotclaude/pass-last/<pane number>.json and shows every reply, grouped by
turn, oldest first, only when the entry's tab is this pane on this tmux server. A stub tmux
answers `display` with the current pane ($STUB_PANE) or the server line ($STUB_SERVER; empty
fails). Output is not a terminal here, so the script prints instead of starting less."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import sys
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "tmux", "pass-last")

spec = importlib.util.spec_from_file_location("pass_banner",
                                              os.path.join(REPO, "hooks", "pass_banner.py"))
pass_banner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pass_banner)

# A locale whose files read as ASCII: C, with Python's UTF-8 mode and coercion off. -I ignores
# those env switches and coerces C to UTF-8, so the fake python3 drops -I and adds -X utf8=0.
ASCII_LOCALE = {"LC_ALL": "C", "LANG": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0",
                "FAKE_PY_ASCII": "1"}
FAKE_PYTHON = """#!/usr/bin/env bash
if [ -n "${FAKE_PY_ASCII:-}" ]; then
  args=(); for a in "$@"; do [ "$a" = -I ] || args+=("$a"); done
  exec %s -X utf8=0 "${args[@]}"
fi
exec %s "$@"
"""

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
T1 = time.mktime((2026, 10, 12, 13, 50, 0, 0, 0, -1))
T2 = time.mktime((2026, 10, 12, 14, 4, 0, 0, 0, -1))
SAVED = time.mktime((2026, 10, 12, 14, 5, 0, 0, 0, -1))
HEAD = "Replies before the pass (saved 2026-10-12 14:05, session old-session-1); the newest are " \
       "last, q closes."


class PassLast(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        os.mkdir(stubs)
        with open(os.path.join(stubs, "tmux"), "w") as f:
            f.write(STUB)
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        with open(os.path.join(stubs, "python3"), "w") as f:
            f.write(FAKE_PYTHON % (sys.executable, sys.executable))
        os.chmod(os.path.join(stubs, "python3"), 0o755)
        self.log = os.path.join(self.tmp, "calls.log")
        self.dir = os.path.join(self.tmp, "state", "dotclaude", "pass-last")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], STUB_LOG=self.log,
                        HOME=os.path.join(self.tmp, "home"), STUB_SERVER=SERVER,
                        STUB_PANE="%7", XDG_STATE_HOME=os.path.join(self.tmp, "state"))

    def entry(self, message="Done: the PR is up.\nNext: review it.", **fields):
        """A pass-last entry; message= gives it one reply."""
        e = {"tab": TAB, "from_session": "old-session-1", "written_at": SAVED,
             "replies": [{"prompt_id": "p1", "text": message, "time": T2}], "shown": True,
             **fields}
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
            HEAD + "\n\n== Replies from 2026-10-12 14:04 (last turn) ==\n\nline 1\n"))
        self.assertTrue(out.endswith("line 100\n"))  # no cap: the popup scrolls
        self.assertIn(["tmux", "display", "-p", "-t", "%7",
                       "#{start_time} #{pid} #{socket_path}"], self.calls())

    def test_every_prompts_replies_show_oldest_first_under_a_time_header(self):
        self.entry(replies=[{"prompt_id": "p1", "text": "Older reply.", "time": T1},
                            {"prompt_id": "p2", "text": "First part.\n", "time": T2},
                            {"prompt_id": "p2", "text": "Pass armed.", "time": T2 + 30},
                            {"prompt_id": "p3", "text": " "}, 5])
        self.assertEqual(self.show("%7"), "\n\n".join([
            HEAD, "== Replies from 2026-10-12 13:50 ==", "Older reply.",
            "== Replies from 2026-10-12 14:04 (last turn) ==", "First part.",
            "Pass armed."]) + "\n")

    def test_the_popup_and_the_banner_agree_on_the_last_turn(self):
        cases = [
            [{"prompt_id": "p1", "text": "a"}, {"prompt_id": "p2", "text": "b"},
             {"prompt_id": "p1", "text": "c"}],                       # an id that recurs
            [{"prompt_id": "p1", "text": "a"}, {"prompt_id": "none-1.0", "text": "b"}],
            [{"prompt_id": "p1", "text": "a"}, {"prompt_id": "p1", "text": " "},
             {"prompt_id": "p1", "text": "c"}, 5],                    # junk inside the turn
            [{"prompt_id": "p1", "text": "a"}, {"prompt_id": "p2", "text": "b"},
             {"prompt_id": "p2", "text": "c"}],
        ]
        for replies in cases:
            with self.subTest(replies=replies):
                self.entry(replies=[dict(r, time=T2) if isinstance(r, dict) else r
                                    for r in replies])
                popup_last = self.show("%7").split("(last turn) ==\n\n", 1)[1]
                self.assertEqual(popup_last, "\n\n".join(pass_banner.newest_group(replies)) + "\n")

    def test_the_entry_is_read_as_utf8_in_any_locale(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "7.json"), "w", encoding="utf-8") as f:
            json.dump({"tab": TAB, "written_at": SAVED, "from_session": "s1",
                       "replies": [{"prompt_id": "p1", "text": "caf" + chr(0x00E9),
                                    "time": T2}]}, f, ensure_ascii=False)
        self.env.update(ASCII_LOCALE)
        p = subprocess.run(["bash", SCRIPT, "%7"], capture_output=True, timeout=10, env=self.env,
                           stdin=subprocess.DEVNULL)
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        self.assertTrue(p.stdout.endswith(("caf" + chr(0x00E9) + "\n").encode()), p.stdout)

    def test_less_opens_at_the_end_and_ignores_a_quit_if_one_screen(self):
        # A LESS=-F in the environment would close a short popup at once; -+F turns it off.
        with open(SCRIPT) as f:
            self.assertIn("| less -+F +G\n", f.read())

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
        self.entry(replies=[])
        self.assertEqual(self.show("%7"), NONE + "\n")
        self.entry(message="")
        self.assertEqual(self.show("%7"), NONE + "\n")
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
        self.entry(message="red " + chr(27) + "[31mtext" + chr(7) + chr(0x9B) + chr(0x85)
               + chr(0x7F))
        self.assertTrue(self.show("%7").endswith("red [31mtext\n"))

    def test_a_lone_surrogate_does_not_break_it(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "7.json"), "w") as f:
            f.write(json.dumps({"tab": TAB, "written_at": SAVED, "from_session": "s@",
                                "replies": [{"prompt_id": "p1", "text": "a@b", "time": T2}]})
                    .replace("@", "\\ud800"))
        out = self.show("%7")
        self.assertTrue(out.endswith("a?b\n"), out)
        self.assertIn("session s?)", out)

    def calls(self):
        with open(self.log) as f:
            return [line.split("\x1f") for line in f.read().splitlines()]


if __name__ == "__main__":
    unittest.main()
