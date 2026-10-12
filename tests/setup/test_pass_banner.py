"""hooks/pass-banner.sh (and pass_banner.py): after a plain /pass respawned a tab, the new
session's `startup` shows everything the old session said since the last prompt, once, as a
SessionStart systemMessage (stdlib only).

The entry is $XDG_STATE_HOME/dotclaude/pass-last/<pane number>.json, which pass-respawn writes.
A stub tmux on PATH answers `display` with the server line ($STUB_SERVER; empty fails) and logs
each call. The env starts scrubbed of CLAUDE* and TMUX*, since the test may run in a Claude tab."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "pass-banner.sh")

spec = importlib.util.spec_from_file_location("pass_banner",
                                              os.path.join(REPO, "hooks", "pass_banner.py"))
pass_banner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pass_banner)

STUB = """#!/usr/bin/env bash
{ printf '%s' "$(basename "$0")"; printf '\\x1f%s' "$@"; printf '\\n'; } >> "$STUB_LOG"
case "$1" in
  display|display-message)
    [ -n "${STUB_SERVER:-}" ] || exit 1
    printf '%s\\n' "$STUB_SERVER" ;;
esac
exit 0
"""

SOCKET = "/tmp/tmux-1000/my socket"   # a space: the path is the rest of the display line
SERVER = f"1791222157 4321 {SOCKET}"
TAB = {"socket": SOCKET, "server_start": 1791222157, "server_pid": 4321, "pane": "%7"}
ENV = {"TMUX": "/tmp/tmux-1000/default,1,0", "TMUX_PANE": "%7",
       "CLAUDE_CODE_SESSION_ATTENDED": "1"}
REPLY = "Done: the PR is up.\nNext: review it."


class Banner(unittest.TestCase):
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
                        XDG_STATE_HOME=os.path.join(self.tmp, "state"))

    def entry(self, pane="7", message=REPLY, **fields):
        """A pass-last entry; message= gives it one reply."""
        e = {"tab": TAB, "from_session": "old-session-1", "written_at": time.time(),
             "replies": [{"prompt_id": "p1", "text": message, "time": 1.0}], "shown": False,
             **fields}
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, pane + ".json"), "w") as f:
            json.dump(e, f)

    def read(self, pane="7"):
        with open(os.path.join(self.dir, pane + ".json")) as f:
            return json.load(f)

    def start(self, session=ENV, cwd=None, **payload):
        body = {"session_id": "new-session-2", "hook_event_name": "SessionStart",
                "source": "startup", "cwd": "/home/u/code/dna", **payload}
        p = subprocess.run(["bash", HOOK], input=json.dumps(body), capture_output=True,
                           text=True, timeout=10, env={**self.env, **session}, cwd=cwd)
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        return json.loads(p.stdout)["systemMessage"] if p.stdout else None

    def test_a_matching_entry_shows_once(self):
        self.entry()
        self.assertEqual(self.start(), "Last reply before the pass:\n" + REPLY)
        self.assertIs(self.read()["shown"], True)
        self.assertEqual(self.read()["replies"][0]["text"], REPLY)  # kept for Ctrl-b P
        self.assertIsNone(self.start())                   # once
        self.assertEqual(os.listdir(self.dir), ["7.json"])  # renamed into place

    def test_a_stale_entry_shows_nothing(self):
        self.entry(written_at=time.time() - 121)
        self.assertIsNone(self.start())
        self.assertIs(self.read()["shown"], False)
        self.entry(written_at=time.time() + 60)  # from the future: not this respawn either
        self.assertIsNone(self.start())

    def test_the_wrong_tab_shows_nothing(self):
        for field, value in (("socket", "/tmp/tmux-1000/other"), ("server_start", 1),
                             ("server_pid", 1), ("pane", "%8")):
            with self.subTest(field=field):
                self.entry(tab={**TAB, field: value})
                self.assertIsNone(self.start())
                self.assertIs(self.read()["shown"], False)

    def test_an_unreadable_server_or_another_panes_file_shows_nothing(self):
        self.entry(pane="8", tab={**TAB, "pane": "%8"})
        self.assertIsNone(self.start())
        self.entry()
        self.env["STUB_SERVER"] = ""
        self.assertIsNone(self.start())

    def test_claude_p_and_subagents_skip(self):
        self.entry()
        self.assertIsNone(self.start(session={**ENV, "CLAUDE_CODE_SESSION_ATTENDED": "0"}))
        self.assertIsNone(self.start(agent_id="a1"))
        self.assertIs(self.read()["shown"], False)
        self.assertFalse(os.path.exists(self.log))  # skipped before asking tmux

    def test_only_startup_in_a_tab_shows(self):
        self.entry()
        for source in ("resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertIsNone(self.start(source=source))
        self.assertIsNone(self.start(session={"CLAUDE_CODE_SESSION_ATTENDED": "1"}))  # no pane
        self.assertIsNone(self.start(hook_event_name="SessionEnd"))
        self.assertIs(self.read()["shown"], False)
        self.assertIsNotNone(self.start())

    def test_a_shown_or_malformed_entry_shows_nothing(self):
        for fields in ({"shown": True}, {"shown": None}, {"message": ""}, {"message": 5},
                       {"message": " \n"}, {"replies": []}, {"replies": "text"},
                       {"replies": [{"prompt_id": None, "text": "x"}]},
                       {"written_at": "now"}, {"written_at": True}):
            with self.subTest(fields=fields):
                self.entry(**fields)
                self.assertIsNone(self.start())
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, "7.json"), "w") as f:
            f.write("{not json")
        self.assertIsNone(self.start())

    def test_control_characters_never_reach_the_banner(self):
        self.entry(message="red " + chr(27) + "[31mtext" + chr(7) + chr(0x9B) + chr(0x85)
                   + "\r\nnext\tcol" + chr(0x7F))
        self.assertEqual(self.start(), "Last reply before the pass:\nred [31mtext\nnext\tcol")

    def test_a_lone_surrogate_does_not_break_it(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "7.json"), "w") as f:
            f.write(json.dumps({"tab": TAB, "written_at": time.time(), "shown": False,
                                "replies": [{"prompt_id": "p1", "text": "a@b"}]})
                    .replace("@", "\\ud800"))
        self.assertEqual(self.start(), "Last reply before the pass:\na?b")

    def test_the_newest_prompts_replies_show_together(self):
        # A Stop auto-pass blocks and the Stop that ends the continued turn share a prompt_id.
        self.entry(replies=[{"prompt_id": "p1", "text": "Older prompt's reply."},
                            {"prompt_id": "p2", "text": "First part.\n"},
                            {"prompt_id": "p2", "text": "Pass armed."}])
        self.assertEqual(self.start(),
                         "Since your last prompt:\nFirst part.\n\nPass armed.")

    def test_one_reply_for_the_newest_prompt_has_the_singular_head(self):
        self.assertEqual(pass_banner.banner(["only"]), "Last reply before the pass:\nonly")
        self.assertEqual(pass_banner.newest_group(
            [{"prompt_id": "p1", "text": "a"}, {"prompt_id": "", "text": "b"}, 5]), ["b"])

    def test_a_long_reply_is_cut_at_40_lines(self):
        self.entry(message="\n".join(f"line {i}" for i in range(1, 61)))
        lines = self.start().split("\n")
        self.assertEqual(lines[1], "line 1")
        self.assertEqual(lines[40], "line 40")
        self.assertEqual(lines[41], chr(0x2026) + " 20 more lines: Ctrl-b P shows the whole reply")
        self.assertEqual(len(lines), 42)

    def test_the_whole_banner_stays_within_4_kib(self):
        for texts in (["\n".join("x" * 199 for _ in range(30))],    # 200 bytes a line
                      ["\n".join(chr(0x00E9) * 150 for _ in range(30))],
                      ["a" * 3000, "b" * 3000]):
            with self.subTest(first=texts[0][:3]):
                out = pass_banner.banner(texts)
                self.assertLessEqual(len(out.encode()), 4096)
                self.assertTrue(out.split("\n")[-1].startswith(chr(0x2026) + " "))
        out = pass_banner.banner(["\n".join("x" * 199 for _ in range(30))]).split("\n")
        # head (28 bytes), 20 lines (3,999), tail (50): 4,077; a 21st line would pass 4 KiB.
        self.assertEqual(len(out), 22)
        self.assertEqual(out[-1], chr(0x2026) + " 10 more lines: Ctrl-b P shows the whole reply")
        fits = "x" * (4096 - len("Last reply before the pass:\n"))  # exactly 4 KiB: no tail
        self.assertEqual(len(pass_banner.banner([fits]).encode()), 4096)

    def test_one_huge_line_is_cut_on_a_character_boundary(self):
        out = pass_banner.banner([chr(0x00E9) * 5000])
        self.assertLessEqual(len(out.encode()), 4096)
        head, body, rest = out.split("\n")
        self.assertEqual(body, chr(0x00E9) * len(body))
        self.assertGreater(len(body), 1900)
        self.assertEqual(rest, chr(0x2026) + " 1 more line: Ctrl-b P shows the whole reply")

    def test_a_short_reply_is_whole_and_trailing_blank_lines_go(self):
        self.assertEqual(pass_banner.banner(["one\ntwo\n\n"]),
                         "Last reply before the pass:\none\ntwo")
        forty = "\n".join(["l"] * 40)
        self.assertEqual(pass_banner.banner([forty]), "Last reply before the pass:\n" + forty)

    def test_a_projects_json_py_never_runs(self):
        cwd = os.path.join(self.tmp, "proj")
        os.mkdir(cwd)
        ran = os.path.join(self.tmp, "ran")
        with open(os.path.join(cwd, "json.py"), "w") as f:
            f.write(f"open({ran!r}, 'a').write(__name__)\n")
        self.entry()
        self.assertIsNotNone(self.start(cwd=cwd))
        self.assertFalse(os.path.exists(ran))


if __name__ == "__main__":
    unittest.main()
