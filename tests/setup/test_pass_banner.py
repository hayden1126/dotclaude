"""hooks/pass-banner.sh (and pass_banner.py): after a plain /pass respawned a tab, the new
session's `startup` shows what the old session said in its last turn, once, as a SessionStart
systemMessage (stdlib only).

The entry is $XDG_STATE_HOME/dotclaude/pass-last/<pane number>.json, which pass-respawn writes.
A stub tmux on PATH answers `display` with the server line ($STUB_SERVER; empty fails) and logs
each call. The env starts scrubbed of CLAUDE* and TMUX*, since the test may run in a Claude tab.
HOME is a temp dir holding a ~/.local/bin/pass-last, as setup-tmux.sh links it, so the tail names
Ctrl-b Up; one test removes it."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import sys
import time
import unittest
from unittest import mock

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
SERVER = f"1791222157 4321 120 {SOCKET}"  # start, pid, pane width, socket
E = chr(27) + "["
ELL = chr(0x2026)


def head(prompt=None, at=1.0):
    """The banner's head: the turn's time, then the prompt's first line or the dim note."""
    stamp = " (%s)" % time.strftime("%H:%M", time.localtime(at)) if at is not None else ""
    you = (f"{E}32mYou:{E}38;5;246m {prompt}" if prompt is not None
           else f"{E}2mYou: (prompt not saved){E}22m")
    return f"{E}1mLast turn{stamp}{E}22m\n{you}\n\n"


def turn(*texts):
    return [{"prompt_id": "p1", "text": t} for t in texts]


def open_styles(text):
    """The SGR styles still open at the end of text (own resets: 22 closes 1 and 2, 23 closes 3,
    24 closes 4, and the banner gray 38;5;246 closes a color)."""
    closes = {"22": {"1", "2"}, "23": {"3"}, "24": {"4"}, "38;5;246": {"32", "33", "35", "36"}}
    now = set()
    for params in re.findall(re.escape(E) + r"([0-9;]*)m", text):
        for code in re.findall(r"38;5;\d+|[0-9]+", params):
            if code in closes:
                now -= closes[code]
            else:
                now.add(code)
    return now
TAB = {"socket": SOCKET, "server_start": 1791222157, "server_pid": 4321, "pane": "%7"}
ENV = {"TMUX": "/tmp/tmux-1000/default,1,0", "TMUX_PANE": "%7",
       "CLAUDE_CODE_SESSION_ATTENDED": "1"}
REPLY = "Done: the PR is up.\nNext: review it."
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


class Banner(unittest.TestCase):
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
                        XDG_STATE_HOME=os.path.join(self.tmp, "state"))
        self.popup = os.path.join(self.env["HOME"], ".local", "bin", "pass-last")
        os.makedirs(os.path.dirname(self.popup))
        open(self.popup, "w").close()
        patch = mock.patch.dict(os.environ, {"HOME": self.env["HOME"]})  # banner() in-process
        patch.start()
        self.addCleanup(patch.stop)

    def entry(self, pane="7", message=REPLY, **fields):
        """A pass-last entry; message= gives it one reply."""
        e = {"tab": TAB, "from_session": "old-session-1", "written_at": time.time(),  # wall clock
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
        self.assertEqual(self.start(), head() + REPLY)
        self.assertIs(self.read()["shown"], True)
        self.assertEqual(self.read()["replies"][0]["text"], REPLY)  # kept for Ctrl-b Up
        self.assertIsNone(self.start())                   # once
        self.assertEqual(os.listdir(self.dir), ["7.json"])  # renamed into place

    def test_a_stale_entry_shows_nothing(self):
        self.entry(written_at=time.time() - 121)  # wall clock
        self.assertIsNone(self.start())
        self.assertIs(self.read()["shown"], False)
        # From the future: not this respawn either.
        self.entry(written_at=time.time() + 60)  # wall clock
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

    def test_a_record_too_deep_for_json_reads_as_none(self):
        # json raises RecursionError, not ValueError, on deep nesting. The shim hides stderr and
        # exits 0, so only load() in-process shows the crash.
        os.makedirs(self.dir, exist_ok=True)
        path = os.path.join(self.dir, "7.json")
        with open(path, "w") as f:
            f.write("[" * 100000)
        self.assertIsNone(pass_banner.load(path))
        self.assertIsNone(self.start())

    def test_control_characters_never_reach_the_banner(self):
        self.entry(message="red " + chr(27) + "[31mtext" + chr(7) + chr(0x9B) + chr(0x85)
                   + "\r\nnext\tcol" + chr(0x7F),
                   prompts=[{"prompt_id": "p1", "text": "go " + chr(27) + "[2Jnow" + chr(0x9B)}])
        self.assertEqual(self.start(), head("go [2Jnow") + "red [31mtext\nnext col")

    def test_a_lone_surrogate_does_not_break_it(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "7.json"), "w") as f:
            f.write(json.dumps({"tab": TAB, "written_at": time.time(), "shown": False,  # wall clock
                                "replies": [{"prompt_id": "p1", "text": "a@b"}]})
                    .replace("@", "\\ud800"))
        self.assertEqual(self.start(), head(at=None) + "a?b")

    def test_the_last_turns_replies_show_together(self):
        # A Stop auto-pass blocks and the Stop that ends the continued turn share a prompt_id.
        self.entry(replies=[{"prompt_id": "p1", "text": "Older turn's reply.", "time": 1.0},
                            {"prompt_id": "p2", "text": "First part.\n", "time": 2.0},
                            {"prompt_id": "p2", "text": "Pass armed.", "time": 3.0}])
        self.assertEqual(self.start(), head(at=2.0) + "First part.\n\nPass armed.")

    def test_the_last_turn_is_the_run_at_the_end(self):
        # The popup splits turns by runs too (tests/setup/test_pass_last.py checks they agree).
        def group(replies):
            return [r["text"] for r in pass_banner.newest_group(replies)]
        self.assertEqual(group([{"prompt_id": "p1", "text": "a"}, {"prompt_id": "p2", "text": "b"},
                                {"prompt_id": "p1", "text": "c"}, 5]), ["c"])
        self.assertEqual(group([{"prompt_id": "p1", "text": "a"},
                                {"prompt_id": "none-2.0", "text": "b"}]), ["b"])
        self.assertEqual(group([{"prompt_id": "p1", "text": "a"}, {"prompt_id": "p1", "text": " "},
                                {"prompt_id": "p1", "text": "c"}]), ["a", "c"])

    def test_the_turns_prompt_shows_its_first_line(self):
        prompts = [{"prompt_id": "p0", "text": "an older turn's prompt"},
                   {"prompt_id": "p1", "text": "\nFix the banner\nand the popup too"}]
        self.entry(prompts=prompts)
        self.assertEqual(self.start(), head("Fix the banner" + ELL) + REPLY)
        self.entry(prompts=[{"prompt_id": "p1", "text": "x" * 150}])
        self.assertEqual(self.start(), head("x" * 100 + ELL) + REPLY)
        self.entry(prompts=[{"prompt_id": "p1", "text": "one line"}])
        self.assertEqual(self.start(), head("one line") + REPLY)

    def test_a_turn_without_a_saved_prompt_says_so(self):
        for prompts in ([{"prompt_id": "p0", "text": "another turn's"}], [], "x", None,
                        [{"prompt_id": "p1", "text": "  "}, 5],
                        [{"prompt_id": "p1", "notice": "yes"}]):
            with self.subTest(prompts=prompts):
                self.entry(prompts=prompts)
                self.assertEqual(self.start(), head() + REPLY)

    def test_a_turn_a_notice_started_says_a_background_notice(self):
        self.entry(prompts=[{"prompt_id": "p1", "notice": True, "time": 1.0}])
        notice = head().replace("(prompt not saved)", "(no prompt: a background notice)")
        self.assertEqual(self.start(), notice + REPLY)

    def test_a_corrupt_reply_time_drops_the_stamp_not_the_banner(self):
        for bad in (1e20, float("nan"), -1e20):
            with self.subTest(time=bad):
                out = pass_banner.banner([{"prompt_id": "p1", "text": "hi", "time": bad}])
                self.assertTrue(out.startswith(f"{E}1mLast turn{E}22m\n"), out)

    def test_markdown_is_rendered_to_the_panes_width_with_own_resets(self):
        self.env["STUB_SERVER"] = f"1791222157 4321 40 {SOCKET}"    # 35 columns of text
        self.entry(message="## Plan\n\n- **one** with `code` and words that wrap past the "
                   "width here\n\n```\nls\n```")
        out = self.start()
        self.assertNotIn(E + "0m", out)
        self.assertEqual(out[len(head()):].split("\n"), [
            f"{E}1;35mPlan{E}22;38;5;246m", "",
            f"  {chr(0x2022)} {E}1mone{E}22m with {E}36mcode{E}38;5;246m and words that",  # 32
            "    wrap past the width here", "",
            f"{E}2m{chr(0x2502)} {E}22m{E}33mls{E}38;5;246m"])
        self.assertEqual(self.calls()[-1][-1], "#{start_time} #{pid} #{pane_width} "
                                               "#{socket_path}")

    def test_an_unknown_pane_width_renders_at_80_less_the_indent(self):
        self.env["STUB_SERVER"] = f"1791222157 4321  {SOCKET}"
        words = " ".join(["word"] * 30)                 # 149 columns
        self.entry(message=words)
        lines = self.start()[len(head()):].split("\n")
        self.assertEqual([len(line) for line in lines], [74, 74])   # 15 words: 74 columns

    def test_without_the_popup_installed_the_tail_names_the_file(self):
        os.remove(self.popup)
        self.entry(message="\n".join(f"line {i}" for i in range(1, 61)))
        out = self.start()
        self.assertEqual(out.split("\n")[-1], "%s 20 more lines in %s" % (
            ELL, os.path.join(self.dir, "7.json")))
        self.assertLessEqual(len(out.encode()), 4096)
        long = pass_banner.banner(turn("```\n" + chr(0x00E9) * 5000 + "\n```"), None, 75,
                                  "/state/dotclaude/pass-last/7.json")
        self.assertLessEqual(len(long.encode()), 4096)
        self.assertTrue(long.endswith(" 1 more line in /state/dotclaude/pass-last/7.json"))

    def test_an_entry_is_read_as_utf8_in_any_locale(self):
        self.entry(message="caf" + chr(0x00E9) + " " + ELL)
        with open(os.path.join(self.dir, "7.json"), "rb") as f:
            raw = f.read()
        with open(os.path.join(self.dir, "7.json"), "wb") as f:  # as pass-respawn writes it
            f.write(raw.replace(b"\\u00e9", chr(0x00E9).encode()))
        self.assertIn(chr(0x00E9).encode(), open(os.path.join(self.dir, "7.json"), "rb").read())
        self.assertEqual(self.start(session={**ENV, **ASCII_LOCALE}),
                         head() + "caf" + chr(0x00E9) + " " + ELL)

    def test_a_non_ascii_event_still_shows_the_banner_in_any_locale(self):
        # The banner uses no payload text, so this guards the parse, not the decoding.
        self.entry()
        body = json.dumps({"session_id": "new-session-2", "hook_event_name": "SessionStart",
                           "source": "startup", "cwd": "/home/u/caf" + chr(0x00E9)},
                          ensure_ascii=False)
        p = subprocess.run(["bash", HOOK], input=body.encode(), capture_output=True,
                           timeout=10, env={**self.env, **ENV, **ASCII_LOCALE})
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        self.assertEqual(json.loads(p.stdout)["systemMessage"], head() + REPLY)

    def test_a_long_reply_is_cut_at_40_lines(self):
        self.entry(message="\n".join(f"line {i}" for i in range(1, 61)))
        lines = self.start().split("\n")
        self.assertEqual(lines[3], "line 1")                 # under the 3 head lines
        self.assertEqual(lines[42], "line 40")
        self.assertEqual(lines[43], ELL + " 20 more lines: Ctrl-b Up shows the whole reply")
        self.assertEqual(len(lines), 44)

    def test_the_whole_banner_stays_within_4_kib_escapes_counted(self):
        for texts in (["\n".join("x" * 199 for _ in range(30))],    # 200 bytes a line
                      ["\n".join(chr(0x00E9) * 150 for _ in range(30))],
                      ["\n".join("**%s** `c`" % ("b" * 150) for _ in range(30))],
                      ["a" * 3000, "b" * 3000]):
            with self.subTest(first=texts[0][:3]):
                out = pass_banner.banner(turn(*texts), None, 300)
                self.assertLessEqual(len(out.encode()), 4096)
                self.assertTrue(out.split("\n")[-1].startswith(ELL + " "))
                self.assertEqual(open_styles(out), set())
        out = pass_banner.banner(turn("\n".join("x" * 199 for _ in range(30))), None, 300)
        # head (53 bytes with its escapes), 19 lines (3,799), tail (51): 3,903; a 20th line
        # (200) would pass 4 KiB.
        self.assertEqual(len(out.split("\n")), 3 + 19 + 1)
        self.assertEqual(out.split("\n")[-1],
                         ELL + " 11 more lines: Ctrl-b Up shows the whole reply")
        # A code line costs 29 bytes of bar and escapes: head 53 + 29 + 4,014 is exactly 4 KiB.
        fits = pass_banner.banner(turn("```\n" + "x" * 4014 + "\n```"), None, 75)
        self.assertEqual(len(fits.encode()), 4096)
        self.assertTrue(fits.endswith("x" + E + "38;5;246m"))
        over = pass_banner.banner(turn("```\n" + "x" * 4015 + "\n```"), None, 75)
        self.assertTrue(over.endswith(" 1 more line: Ctrl-b Up shows the whole reply"))

    def test_one_huge_line_is_cut_outside_escapes_with_its_styles_closed(self):
        out = pass_banner.banner(turn("```\n" + chr(0x00E9) * 5000 + "\n```"), None, 75)
        self.assertLessEqual(len(out.encode()), 4096)
        self.assertNotIn(E + "0m", out)
        self.assertEqual(open_styles(out), set())
        body, rest = out[len(head(at=None)):].split("\n")
        self.assertTrue(body.startswith(f"{E}2m{chr(0x2502)} {E}22m{E}33m"), body)
        self.assertTrue(body.endswith(chr(0x00E9) + E + "38;5;246m"), body)
        self.assertGreater(body.count(chr(0x00E9)), 1900)
        self.assertEqual(rest, ELL + " 1 more line: Ctrl-b Up shows the whole reply")

    def test_a_cut_between_lines_leaves_no_style_open(self):
        text = "\n".join("**bold %d** and `code` and *it*" % i for i in range(60))
        out = pass_banner.banner(turn(text), "prompt", 75)
        self.assertTrue(out.endswith(" 20 more lines: Ctrl-b Up shows the whole reply"))
        self.assertEqual(open_styles(out), set())
        for line in out.split("\n"):
            self.assertEqual(open_styles(line), set(), line)
        self.assertNotIn(E + "0m", out)

    def test_a_short_reply_is_whole_and_trailing_blank_lines_go(self):
        self.assertEqual(pass_banner.banner(turn("one\ntwo\n\n")), head(at=None) + "one\ntwo")
        forty = "\n".join(["l"] * 40)
        self.assertEqual(pass_banner.banner(turn(forty)), head(at=None) + forty)

    def calls(self):
        with open(self.log) as f:
            return [line.split("\x1f") for line in f.read().splitlines()]

    def test_without_md_render_the_banner_is_the_plain_text(self):
        with mock.patch.object(pass_banner, "md_render", None):
            self.assertEqual(pass_banner.banner(turn("**b** `c`"), "p"),
                             "Last turn\nYou: p\n\n**b** `c`")

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
