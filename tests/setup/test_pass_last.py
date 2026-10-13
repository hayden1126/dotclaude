"""tmux/pass-last: the Ctrl-b Up popup that shows what a tab's Claude said before a plain /pass
(stdlib only).

It reads $XDG_STATE_HOME/dotclaude/pass-last/<pane number>.json and shows every turn, oldest first,
each under a rule with its time, Hayden's prompt and the replies rendered by hooks/md_render.py,
only when the entry's tab is this pane on this tmux server. A stub tmux answers `display` with the
current pane ($STUB_PANE) or the server line ($STUB_SERVER; empty fails). Output is not a
terminal in most tests, so the script prints plain text instead of starting less; the width is
$COLUMNS, since the script runs in a new session with no /dev/tty. One test gives it a pty and a
fake less."""
import importlib.util
import json
import os
import pty
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
# less in a terminal: its arguments and what it was given, into files.
FAKE_LESS = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$LESS_ARGS"
cat > "$LESS_OUT"
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
WIDTH = 100
E = chr(27) + "["
BAR = chr(0x258C)
NO_PROMPT = BAR + " (prompt not saved)"
NOTICE = BAR + " (no prompt: a background notice)"


def short(t):
    """The rule's time: HH:MM, with the date when the turn wasn't today (as the script has it)."""
    today = time.strftime("%Y-%m-%d") == time.strftime("%Y-%m-%d", time.localtime(t))
    return time.strftime("%H:%M" if today else "%Y-%m-%d %H:%M", time.localtime(t))


def rule(t, last=False, width=WIDTH):
    label = " %s%s " % (short(t), " " + chr(0x00B7) + " last turn" if last else "")
    ch = chr(0x2501) if last else chr(0x2500)
    return ch * 3 + label + ch * (width - 3 - len(label))


def you(*lines):
    return "\n".join([BAR + " You:"] + [BAR + " " + line for line in lines])


class PassLast(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        os.mkdir(stubs)
        for name, body in (("tmux", STUB), ("less", FAKE_LESS),
                           ("python3", FAKE_PYTHON % (sys.executable, sys.executable))):
            with open(os.path.join(stubs, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(stubs, name), 0o755)
        self.log = os.path.join(self.tmp, "calls.log")
        self.dir = os.path.join(self.tmp, "state", "dotclaude", "pass-last")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX", "LESS"))}
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], STUB_LOG=self.log,
                        HOME=os.path.join(self.tmp, "home"), STUB_SERVER=SERVER,
                        STUB_PANE="%7", XDG_STATE_HOME=os.path.join(self.tmp, "state"),
                        COLUMNS=str(WIDTH), LESS_ARGS=os.path.join(self.tmp, "less.args"),
                        LESS_OUT=os.path.join(self.tmp, "less.out"))

    def entry(self, message="Done: the PR is up.\nNext: review it.", **fields):
        """A pass-last entry; message= gives it one reply."""
        e = {"tab": TAB, "from_session": "old-session-1", "written_at": SAVED,
             "replies": [{"prompt_id": "p1", "text": message, "time": T2}], "shown": True,
             **fields}
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, "7.json"), "w") as f:
            json.dump(e, f)

    def show(self, *args, script=SCRIPT):
        p = subprocess.run(["bash", script, *args], capture_output=True, text=True, timeout=10,
                           env=self.env, stdin=subprocess.DEVNULL, start_new_session=True)
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        return p.stdout

    def test_an_entry_for_this_tab_shows_the_whole_reply(self):
        self.entry(message="\n".join(f"line {i}" for i in range(1, 101)))
        out = self.show("%7")
        self.assertTrue(out.startswith("\n\n".join(
            [HEAD, rule(T2, last=True), NO_PROMPT, "line 1\n"])), out[:400])
        self.assertTrue(out.endswith("line 100\n"))  # no cap: the popup scrolls
        self.assertIn(["tmux", "display", "-p", "-t", "%7",
                       "#{start_time} #{pid} #{socket_path}"], self.calls())

    def test_every_turn_shows_oldest_first_under_a_rule_with_its_prompt(self):
        self.entry(replies=[{"prompt_id": "p1", "text": "Older reply.", "time": T1},
                            {"prompt_id": "p2", "text": "First part.\n", "time": T2},
                            {"prompt_id": "p2", "text": "Pass armed.", "time": T2 + 30},
                            {"prompt_id": "p3", "text": " "}, 5],
                   prompts=[{"prompt_id": "p1", "text": "Run the tests.\n\nThen commit."},
                            {"prompt_id": "p9", "text": "a turn that isn't here"}, 7])
        self.assertEqual(self.show("%7"), "\n\n".join([
            HEAD, rule(T1), you("Run the tests.") + "\n" + BAR + "\n" + BAR + " Then commit.",
            "Older reply.", rule(T2, last=True), NO_PROMPT, "First part.",
            "Pass armed."]) + "\n")

    def test_a_long_prompt_wraps_under_the_bar(self):
        self.env["COLUMNS"] = "30"
        self.entry(prompts=[{"prompt_id": "p1", "text": "please fix the wrapping of this "
                             "long prompt " + chr(0x2026) + " (2 more lines)"}])
        out = self.show("%7")
        self.assertIn(you("please fix the wrapping of", "this long prompt " + chr(0x2026)
                          + " (2 more", "lines)"), out)               # 28 columns

    def test_markdown_is_rendered_and_wrapped_to_the_width(self):
        self.env["COLUMNS"] = "40"
        self.entry(message="## Plan\n\n- **one** has `code` and enough words to wrap here\n"
                           "\n```\nls -la\n```")
        out = self.show("%7")
        self.assertTrue(out.endswith("\n\n".join([
            rule(T2, last=True, width=40), NO_PROMPT,
            "Plan\n\n  " + chr(0x2022) + " one has code and enough words to\n"
            "    wrap here\n\n" + chr(0x2502) + " ls -la\n"])), out)
        self.assertNotIn(chr(27), out)                      # not a terminal: no escapes

    def test_in_a_terminal_less_gets_colors_at_the_ttys_width(self):
        self.env["COLUMNS"] = "50"
        self.entry(message="**bold** and `code`",
                   prompts=[{"prompt_id": "p1", "text": "do it"}])
        master, slave = pty.openpty()
        try:
            p = subprocess.run(["bash", SCRIPT, "%7"], stdout=slave, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL, env=self.env, timeout=10,
                               start_new_session=True)
        finally:
            os.close(slave)
            os.close(master)
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        with open(self.env["LESS_ARGS"]) as f:
            self.assertEqual(f.read().split("\n"), ["-R", "-+F", "+G", ""])
        with open(self.env["LESS_OUT"], encoding="utf-8") as f:
            out = f.read()
        self.assertIn(f"{E}1;33m" + rule(T2, last=True, width=50) + f"{E}0m", out)
        self.assertIn(f"{E}32m{BAR} You:{E}0m\n{E}32m{BAR}{E}0m do it", out)
        self.assertTrue(out.endswith(f"{E}1mbold{E}0m and {E}36mcode{E}0m\n"), out)
        self.assertTrue(out.startswith(f"{E}2mReplies before the pass"), out)

    def test_a_notice_turn_and_a_corrupt_time(self):
        self.entry(replies=[{"prompt_id": "p1", "text": "From a notice.", "time": T1},
                            {"prompt_id": "p2", "text": "Bad time.", "time": float("nan")}],
                   prompts=[{"prompt_id": "p1", "notice": True}], written_at=1e20)
        out = self.show("%7")
        self.assertIn(NOTICE, out)
        self.assertIn(NO_PROMPT, out)
        self.assertIn("saved ?", out)
        self.assertIn("Bad time.", out)

    def test_without_md_render_it_falls_back_to_the_plain_text(self):
        # A copy of the script away from hooks/, with no ~/.claude/hooks/md_render.py.
        lone = os.path.join(self.tmp, "lone", "tmux")
        os.makedirs(lone)
        shutil.copy(SCRIPT, lone)
        self.entry(replies=[{"prompt_id": "p1", "text": "Older **reply**.", "time": T1},
                            {"prompt_id": "p2", "text": "Pass armed.", "time": T2}],
                   prompts=[{"prompt_id": "p1", "text": "Run the tests"}])
        self.assertEqual(self.show("%7", script=os.path.join(lone, "pass-last")), "\n\n".join([
            HEAD, "== Replies from 2026-10-12 13:50 ==", "You: Run the tests", "Older **reply**.",
            "== Replies from 2026-10-12 14:04 (last turn) ==", "You: (prompt not saved)",
            "Pass armed."]) + "\n")
        # ~/.claude/hooks/md_render.py is the second place it looks.
        hooks = os.path.join(self.env["HOME"], ".claude", "hooks")
        os.makedirs(hooks)
        shutil.copy(os.path.join(REPO, "hooks", "md_render.py"), hooks)
        out = self.show("%7", script=os.path.join(lone, "pass-last"))
        self.assertIn(rule(T1), out)
        self.assertIn("Older reply.", out)

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
                popup_last = self.show("%7").split(
                    rule(T2, last=True) + "\n\n" + NO_PROMPT + "\n\n", 1)[1]
                banner_last = [r["text"] for r in pass_banner.newest_group(replies)]
                self.assertEqual(popup_last, "\n\n".join(banner_last) + "\n")

    def test_the_entry_is_read_as_utf8_in_any_locale(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "7.json"), "w", encoding="utf-8") as f:
            json.dump({"tab": TAB, "written_at": SAVED, "from_session": "s1",
                       "replies": [{"prompt_id": "p1", "text": "caf" + chr(0x00E9),
                                    "time": T2}]}, f, ensure_ascii=False)
        self.env.update(ASCII_LOCALE)
        p = subprocess.run(["bash", SCRIPT, "%7"], capture_output=True, timeout=10, env=self.env,
                           stdin=subprocess.DEVNULL, start_new_session=True)
        self.assertEqual((p.returncode, p.stderr), (0, b""))
        self.assertTrue(p.stdout.endswith(("caf" + chr(0x00E9) + "\n").encode()), p.stdout)

    def test_less_opens_at_the_end_and_ignores_a_quit_if_one_screen(self):
        # A LESS=-F in the environment would close a short popup at once; -+F turns it off.
        with open(SCRIPT) as f:
            self.assertIn("| less -R -+F +G\n", f.read())

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
                   + chr(0x7F),
                   prompts=[{"prompt_id": "p1", "text": "go" + chr(27) + "[2J" + chr(0x9B)}])
        out = self.show("%7")
        self.assertTrue(out.endswith(you("go[2J") + "\n\nred [31mtext\n"), out)
        self.assertNotIn(chr(27), out)

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
