"""tmux/claude-mute: the device-wide mute's CLI (status, on, off), the tab bar's mark and the Mute
menu, against a temp XDG_STATE_HOME and a stub tmux that logs its argv (stdlib only)."""
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "tmux", "claude-mute")

loader = importlib.machinery.SourceFileLoader("claude_mute", SCRIPT)
spec = importlib.util.spec_from_loader("claude_mute", loader)
cm = importlib.util.module_from_spec(spec)
loader.exec_module(cm)

SOUND, TOAST = chr(0x1F507), chr(0x1F515)
DOT = " " + chr(0xB7) + " "
NOW = 1_800_000_000.0
CLIENT = "/dev/pts/7"
CENTRE_Y = "#{?#{==:#{status-position},top},0,#{popup_centre_y}}"

# Logs each call as "tmux\x1f<arg>\x1f<arg>...", and answers list-clients from $STUB_CLIENTS.
TMUX_STUB = r"""#!/usr/bin/env bash
{ printf 'tmux'; printf '\x1f%s' "$@"; printf '\n'; } >> "$STUB_LOG"
case "$1" in
  list-clients) printf '%b' "${STUB_CLIENTS:-}" ;;
esac
exit 0
"""


def cells(text):
    """Terminal cells: each mute glyph is two."""
    return len(text) + text.count(SOUND) + text.count(TOAST)


def tz_at(hh, mm):
    """(TZ, offset): a fixed-offset TZ under which the wall clock reads hh:mm now, and its
    seconds east of UTC. POSIX TZ counts west, so the sign flips."""
    now = int(time.time())  # wall clock
    offset = (hh * 3600 + mm * 60 - now % 86400 + 43200) % 86400 - 43200
    sign, east = ("-", offset) if offset >= 0 else ("+", -offset)
    return "FAKE%s%02d:%02d:%02d" % (sign, east // 3600, east // 60 % 60, east % 60), offset


def ends(until, offset, weekday=False):
    """A mute's end as the CLI names it under tz_at's offset."""
    return time.strftime("%a %H:%M" if weekday else "%H:%M", time.gmtime(until + offset))


def timed(secs, now=NOW):
    return {"since": now - 60, "until": now + secs}


OFF = {"since": NOW - 60, "until": None}


class ClaudeMute(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.state = os.path.join(self.tmp, "state")
        self.dir = os.path.join(self.state, "dotclaude")
        self.flag = os.path.join(self.dir, "mute.json")
        stubs = os.path.join(self.tmp, "stubs")
        os.mkdir(stubs)
        with open(os.path.join(stubs, "tmux"), "w") as f:
            f.write(TMUX_STUB)
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        self.log = os.path.join(self.tmp, "tmux.log")
        # The CLI's clock reads local noon: under a fixed UTC, a timed mute that ran past UTC
        # midnight named its weekday and failed the cases that expect today's end.
        tz, self.offset = tz_at(12, 0)
        self.env = {**os.environ, "XDG_STATE_HOME": self.state, "TZ": tz,
                    "PATH": stubs + os.pathsep + os.environ["PATH"], "STUB_LOG": self.log,
                    "STUB_CLIENTS": "$9 /dev/pts/1\\n$3 %s\\n" % CLIENT}

    def run_cli(self, *args, env=None, py=("-I",), timeout=20):
        p = subprocess.run([sys.executable, *py, SCRIPT, *args], capture_output=True,
                           timeout=timeout, env={**self.env, **(env or {})})
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def write(self, flag):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.flag, "w", encoding="utf-8") as f:
            f.write(flag if isinstance(flag, str) else json.dumps(flag))

    def on_disk(self):
        with open(self.flag, encoding="utf-8") as f:
            return json.load(f)

    def calls(self, verb=None):
        try:
            with open(self.log, encoding="utf-8") as f:
                rows = [line.rstrip("\n").split("\x1f")[1:] for line in f]
        except FileNotFoundError:
            return []
        return [r for r in rows if verb is None or r[:1] == [verb]]

    # --- status, on, off ------------------------------------------------------------------

    def test_status_with_nothing_muted(self):
        for args in ((), ("status",)):
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args), (0, "sound:  on\ntoasts: on\n", ""))
        self.assertFalse(os.path.lexists(self.flag))

    def test_on_defaults_to_all_for_an_hour(self):
        before = time.time()  # wall clock
        rc, out, err = self.run_cli("on")
        after = time.time()  # wall clock
        self.assertEqual((rc, err), (0, ""))
        flag = self.on_disk()
        self.assertEqual(sorted(flag), ["sound", "toast"])
        for name in ("sound", "toast"):
            self.assertLessEqual(before + 3600, flag[name]["until"])
            self.assertLessEqual(flag[name]["until"], after + 3600)
        until = ends(flag["sound"]["until"], self.offset)
        self.assertEqual(out, "sound:  muted, 60 min left (until %s)\n"
                              "toasts: muted, 60 min left (until %s)\n" % (until, until))

    def test_on_and_off_round_trip_per_switch(self):
        rc, out, _ = self.run_cli("on", "sound", "--for", "90m")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(self.on_disk()), ["sound"])
        until = ends(self.on_disk()["sound"]["until"], self.offset)
        self.assertEqual(out, "sound:  muted, 90 min left (until %s)\ntoasts: on\n" % until)
        rc, out, _ = self.run_cli("on", "toast", "--until-off")
        self.assertEqual(rc, 0)
        self.assertIsNone(self.on_disk()["toast"]["until"])
        self.assertTrue(out.endswith("toasts: muted until unmuted\n"), out)
        self.assertEqual(self.run_cli("off", "sound"),
                         (0, "sound:  on\ntoasts: muted until unmuted\n", ""))
        self.assertEqual(sorted(self.on_disk()), ["toast"])
        self.assertEqual(self.run_cli("off"), (0, "sound:  on\ntoasts: on\n", ""))
        self.assertFalse(os.path.lexists(self.flag))      # the hooks' fast path again
        self.assertEqual(self.run_cli("on", "all", "--until-off")[0], 0)
        self.assertEqual(self.on_disk(), {n: {"since": self.on_disk()[n]["since"], "until": None}
                                          for n in ("sound", "toast")})
        self.assertEqual(self.run_cli("off", "all")[0], 0)
        self.assertFalse(os.path.lexists(self.flag))

    def test_durations(self):
        for text, secs in (("1m", 60), ("05m", 300), ("90m", 5400), ("1h", 3600),
                           ("24h", 86400), ("1440m", 86400)):
            with self.subTest(text=text):
                self.assertEqual(cm.duration(text), secs)
        before = time.time()  # wall clock
        self.assertEqual(self.run_cli("on", "toast", "--for", "24h")[0], 0)
        self.assertLessEqual(before + 86400, self.on_disk()["toast"]["until"])

    def test_bad_arguments_are_a_usage_error_and_write_nothing(self):
        bad = [("on", "--for", d) for d in ("0m", "0h", "-5m", "25h", "1441m", "1.5h", "10",
                                            "h", "m", "10s", "", chr(0xFF15) + "m", "1H")]
        bad += [("on", "--for"), ("on", "--for", "1h", "--for", "2h"),
                ("on", "--for", "1h", "--until-off"), ("on", "--until-off", "--until-off"),
                ("on", "sound", "toast"), ("on", "toasts"), ("on", "sound", "x"),
                ("off", "--for", "1h"), ("off", "--until-off"), ("off", "sound", "sound"),
                ("on", "--client"), ("mark", "x"), ("status", "x"), ("menu",),
                ("menu", "a", "b"), ("bogus",)]
        for args in bad:
            with self.subTest(args=args):
                rc, out, err = self.run_cli(*args)
                self.assertEqual((rc, out), (2, ""))
                self.assertIn("usage:\n  claude-mute [status]", err)
                self.assertNotIn("Traceback", err)
                self.assertFalse(os.path.lexists(self.flag))
        rc, out, _ = self.run_cli("--help")
        self.assertEqual(rc, 0)
        self.assertIn("claude-mute on [sound|toast|all] [--for <N>m|<N>h | --until-off]", out)

    def test_status_says_when_the_flag_cant_be_read(self):
        self.write({"sound": 3, "toast": OFF})
        rc, out, _ = self.run_cli()
        self.assertEqual(rc, 0)
        self.assertEqual(out.splitlines()[:2], ["sound:  on", "toasts: muted until unmuted"])
        self.assertEqual(out.splitlines()[2],
                         "note:   %s is malformed, and a mute in it that can't be read is not "
                         "in force (claude-mute off clears it)" % self.flag)
        os.unlink(self.flag)
        os.mkdir(self.flag)
        rc, out, _ = self.run_cli()
        self.assertEqual(out.splitlines()[:2], ["sound:  on", "toasts: on"])
        self.assertIn("%s is unreadable" % self.flag, out)

    def test_a_stamp_out_of_range_is_malformed_and_off_clears_it(self):
        # math.isfinite(10**400) raised OverflowError under mute_state's lock, and
        # time.localtime(1e308) in status: each crashed with a traceback, so `off` couldn't
        # clear the flag and the menu wouldn't open.
        huge = "1" + "0" * 400
        flags = {"a 400-digit until": '{"sound": {"since": 1, "until": %s}}' % huge,
                 "a 400-digit since": '{"sound": {"since": %s, "until": null}}' % huge,
                 "until 1e308": '{"sound": {"since": 1, "until": 1e308}}',
                 "a negative since": '{"sound": {"since": -1, "until": null}}'}
        for name, raw in flags.items():
            with self.subTest(name):
                self.write(raw)
                rc, out, err = self.run_cli("status")
                self.assertEqual((rc, err), (0, ""))
                self.assertEqual(out.splitlines()[:2], ["sound:  on", "toasts: on"])
                self.assertIn("%s is malformed" % self.flag, out)
                self.assertEqual(self.run_cli("mark"), (0, SOUND + "? \n", ""))
                argv = self.menu()
                self.assertTrue(argv[argv.index("-T") + 1].endswith(DOT + "flag malformed"), argv)
                self.assertEqual(self.run_cli("off"), (0, "sound:  on\ntoasts: on\n", ""))
                self.assertFalse(os.path.lexists(self.flag))

    def test_on_over_a_huge_until_answers(self):
        # The menu's items run `on` with --client, whose answer named the end with
        # time.localtime: 1e308 is out of range now, so the switch reads as malformed and drops.
        self.write('{"sound": {"since": 1, "until": 1e308}}')
        rc, out, err = self.run_cli("on", "toast", "--until-off", "--client", CLIENT)
        self.assertEqual((rc, out, err), (0, "sound:  on\ntoasts: muted until unmuted\n", ""))
        self.assertEqual(sorted(self.on_disk()), ["toast"])
        [m] = self.calls("display-message")
        self.assertEqual(m[3], "claude-mute: sound on" + DOT + "toasts muted until unmuted")

    def test_the_end_shows_the_weekday_when_it_isnt_today(self):
        self.addCleanup(time.tzset)                           # runs once TZ is restored
        with mock.patch.dict(os.environ, {"TZ": "UTC"}):
            time.tzset()
            self.assertEqual(cm.clock(NOW + 3600, NOW), "09:00")      # NOW is 08:00 UTC
            self.assertEqual(cm.clock(NOW + 23 * 3600, NOW),
                             time.strftime("%a", time.gmtime(NOW + 86400)) + " 07:00")

    def test_an_end_past_midnight_names_its_weekday(self):
        tz, offset = tz_at(23, 30)
        rc, out, err = self.run_cli("on", "sound", "--for", "1h", "--client", CLIENT,
                                    env={"TZ": tz})
        self.assertEqual((rc, err), (0, ""))
        until = self.on_disk()["sound"]["until"]
        self.assertNotEqual(ends(until - 3600, offset, weekday=True)[:3],
                            ends(until, offset, weekday=True)[:3])      # it did cross midnight
        end = ends(until, offset, weekday=True)
        self.assertEqual(out, "sound:  muted, 60 min left (until %s)\ntoasts: on\n" % end)
        [m] = self.calls("display-message")
        self.assertEqual(m[3], "claude-mute: sound muted until %s" % end + DOT + "toasts on")

    # --- the write the OS refuses ---------------------------------------------------------

    @unittest.skipIf(os.geteuid() == 0, "root writes through a read-only mode")
    def test_a_refused_write_says_where_to_go_instead(self):
        os.makedirs(self.dir)
        os.chmod(self.dir, 0o555)
        self.addCleanup(os.chmod, self.dir, 0o755)
        lock = os.path.join(self.dir, "mute.lock")
        for args, path in ((("on",), lock), (("off", "sound"), lock)):
            with self.subTest(args=args):
                rc, out, err = self.run_cli(*args)
                self.assertEqual((rc, out), (1, ""))
                self.assertEqual(err, "claude-mute: can't write %s: Permission denied; use "
                                      "Ctrl-b Enter, Mute%s or a shell outside Claude (a ! "
                                      "line at a Claude prompt may run in its sandbox)\n"
                                 % (path, chr(0x2026)))
        # With the lock already there, the temp file beside the flag is refused: name its dir.
        os.chmod(self.dir, 0o755)
        open(lock, "w").close()
        os.chmod(self.dir, 0o555)
        rc, _, err = self.run_cli("on", "--client", CLIENT)
        self.assertEqual(rc, 1)
        self.assertTrue(err.startswith("claude-mute: can't write %s: Permission denied; "
                                       % self.dir), err)
        self.assertEqual(err.count("\n"), 1)
        [m] = self.calls("display-message")
        self.assertEqual(m[1:3], ["-c", CLIENT])
        self.assertTrue(m[3].startswith("claude-mute: can't write %s: " % self.dir), m)
        self.assertFalse(os.path.lexists(self.flag))

    def test_another_write_error_is_one_line_without_the_sandbox_hint(self):
        os.makedirs(self.flag)                               # a directory where the flag goes
        # `off` fails on the unlink; `on` on os.replace(temp, flag), whose error has the temp as
        # filename and the flag as filename2: the line names the flag either way.
        for args in (("off",), ("on",), ("on", "toast", "--for", "5m")):
            with self.subTest(args=args):
                rc, out, err = self.run_cli(*args)
                self.assertEqual((rc, out), (1, ""))
                self.assertEqual(err.count("\n"), 1)
                self.assertEqual(err, "claude-mute: can't write %s: Is a directory\n" % self.flag)
                self.assertNotIn("Traceback", err)
                self.assertEqual(sorted(os.listdir(self.dir)), ["mute.json", "mute.lock"])

    # --- the mark -------------------------------------------------------------------------

    def test_every_mark_form(self):
        cases = [
            ({}, None, ""),
            ({"sound": timed(42 * 60)}, None, SOUND + "42m "),
            ({"sound": timed(41 * 60 + 0.5)}, None, SOUND + "42m "),     # rounded up
            ({"sound": timed(0.5)}, None, SOUND + "1m "),
            ({"toast": timed(42 * 60)}, None, TOAST + "42m "),
            ({"sound": timed(5 * 60), "toast": timed(42 * 60)}, None,
             SOUND + "5m " + TOAST + "42m "),
            ({"sound": OFF}, None, SOUND + " "),
            ({"sound": OFF, "toast": OFF}, None, SOUND + " " + TOAST + " "),
            ({"sound": timed(42 * 60), "toast": OFF}, None, SOUND + "42m " + TOAST + " "),
            # the 100-minute boundary: whole hours, rounded up, from there
            ({"sound": timed(99 * 60)}, None, SOUND + "99m "),
            ({"sound": timed(99 * 60 + 1)}, None, SOUND + "2h "),
            ({"sound": timed(100 * 60)}, None, SOUND + "2h "),
            ({"sound": timed(120 * 60)}, None, SOUND + "2h "),
            ({"sound": timed(120 * 60 + 1)}, None, SOUND + "3h "),
            ({"sound": timed(24 * 3600)}, None, SOUND + "24h "),
            # a hand-written flag past the CLI's 24 hours still fits
            ({"sound": timed(99 * 3600 + 1)}, None, SOUND + "5d "),
            ({"sound": timed(100 * 86400)}, None, SOUND + " "),
            # a note: on its own, and beside a muted switch
            ({}, "malformed", SOUND + "? "),
            ({}, "unreadable", SOUND + "? "),
            ({"toast": timed(42 * 60)}, "malformed", TOAST + "42m ? "),
        ]
        for muted, note, want in cases:
            with self.subTest(muted=muted, note=note):
                got = cm.mark_text(muted, note, NOW)
                self.assertEqual(got, want)
                self.assertLessEqual(cells(got), 12)
                self.assertTrue(got == "" or got.endswith(" ") and not got.endswith("  "))
        widest = cm.mark_text({"sound": timed(99 * 60), "toast": timed(99 * 60)}, None, NOW)
        self.assertEqual(cells(widest), 12)

    def test_status_right_length_fits_the_widest_status_right(self):
        # claude.conf's status-right at its widest: a space, the widest mark, the host cut to
        # 10, two spaces, `%a %H:%M` (9) and a space. One cell short and tmux cuts a cell off it.
        with open(os.path.join(REPO, "tmux", "claude.conf"), encoding="utf-8") as f:
            conf = f.read()
        self.assertIn('\nset -g status-right " #(~/.local/bin/claude-mute mark)'
                      '#{=10:host_short}  %a %H:%M "\n', conf)
        length = int(re.search(r"^set -g status-right-length (\d+)$", conf, re.M).group(1))
        widest = cm.mark_text({"sound": timed(99 * 60), "toast": timed(99 * 60)}, None, NOW)
        self.assertEqual(length, 1 + cells(widest) + 10 + 2 + len("Wed 23:59") + 1)

    def test_the_mark_from_the_flag(self):
        self.assertEqual(self.run_cli("mark"), (0, "", ""))  # no flag file: nothing
        self.assertFalse(os.path.lexists(self.dir))
        now = time.time()  # wall clock
        self.write({"sound": {"since": now, "until": now + 41 * 60 + 30}})  # wall clock
        self.assertEqual(self.run_cli("mark"), (0, SOUND + "42m \n", ""))
        # tmux runs it with its own environment: UTF-8 whatever the locale
        self.assertEqual(self.run_cli("mark", env={"LC_ALL": "C", "LANG": "C"}),
                         (0, SOUND + "42m \n", ""))
        self.write({"sound": {"since": now - 7200, "until": now - 3600}})  # wall clock
        self.assertEqual(self.run_cli("mark"), (0, "", ""))  # expired: nothing
        self.write("{not json")
        self.assertEqual(self.run_cli("mark"), (0, SOUND + "? \n", ""))
        self.write({"sound": [], "toast": {"since": now, "until": None}})  # wall clock
        self.assertEqual(self.run_cli("mark"), (0, TOAST + " ? \n", ""))
        os.unlink(self.flag)
        os.symlink(os.path.join(self.tmp, "nowhere"), self.flag)  # a dangling link
        self.assertEqual(self.run_cli("mark"), (0, SOUND + "? \n", ""))

    def test_the_mark_with_no_flag_loads_nothing_heavy(self):
        # tmux runs it every 2 s per client: autopass_state (and its subprocess, tomllib) load
        # only on a write.
        _, _, err = self.run_cli("mark", py=("-I", "-X", "importtime"))
        self.assertIn("mute_state", err)
        self.assertNotIn("autopass_state", err)
        self.assertNotIn("subprocess", err)
        self.write({"sound": OFF})
        _, out, err = self.run_cli("mark", py=("-I", "-X", "importtime"))
        self.assertEqual(out, SOUND + " \n")
        self.assertNotIn("autopass_state", err)              # reading doesn't need it either
        self.write({"sound": {"since": 1, "until": 2}})      # ran out long ago: pruned
        _, out, err = self.run_cli("mark", py=("-I", "-X", "importtime"))
        self.assertEqual(out, "")
        self.assertFalse(os.path.lexists(self.flag))
        self.assertNotIn("autopass_state", err)              # nor does the prune
        _, _, err = self.run_cli("on", py=("-I", "-X", "importtime"))
        self.assertIn("autopass_state", err)                 # the check can see it

    def test_the_mark_prunes_a_flag_whose_mutes_ran_out(self):
        # A timed mute that runs out leaves the flag, which cost every ring a Python start and
        # the mark its slow path for good: the mark removes a flag that mutes nothing now and has
        # no note.
        now = time.time()  # wall clock
        gone = {"since": now - 7200, "until": now - 3600}
        self.write({"sound": gone})
        self.assertEqual(self.run_cli("mark"), (0, "", ""))
        self.assertFalse(os.path.lexists(self.flag))
        live = {"sound": gone, "toast": {"since": now, "until": None}}
        self.write(live)
        self.assertEqual(self.run_cli("mark"), (0, TOAST + " \n", ""))
        self.assertEqual(self.on_disk(), live)
        self.write({"sound": gone, "toast": [1]})            # malformed: its ? keeps showing
        self.assertEqual(self.run_cli("mark"), (0, SOUND + "? \n", ""))
        self.assertEqual(self.on_disk(), {"sound": gone, "toast": [1]})

    def test_a_held_lock_means_the_mark_skips_the_prune(self):
        now = time.time()  # wall clock
        self.write({"sound": {"since": now - 7200, "until": now - 3600}})
        fd = os.open(os.path.join(self.dir, "mute.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)                   # a writer has it: never wait
            self.assertEqual(self.run_cli("mark", timeout=5), (0, "", ""))
            self.assertTrue(os.path.lexists(self.flag))
        finally:
            os.close(fd)
        self.assertEqual(self.run_cli("mark"), (0, "", ""))
        self.assertFalse(os.path.lexists(self.flag))

    @unittest.skipIf(os.geteuid() == 0, "root writes through a read-only mode")
    def test_a_prune_the_os_refuses_leaves_the_mark_silent(self):
        now = time.time()  # wall clock
        self.write({"sound": {"since": now - 7200, "until": now - 3600}})
        os.chmod(self.dir, 0o555)
        self.addCleanup(os.chmod, self.dir, 0o755)
        self.assertEqual(self.run_cli("mark"), (0, "", ""))
        self.assertTrue(os.path.lexists(self.flag))

    # --- the menu -------------------------------------------------------------------------

    def menu(self, client=CLIENT):
        rc, out, err = self.run_cli("menu", client)
        self.assertEqual((rc, out, err), (0, "", ""))
        menus = self.calls("display-menu")
        return menus[-1] if menus else None

    def items(self, argv):
        """The menu's items after -y and its value: (name, key, command), or "" alone."""
        rest = argv[argv.index("-y") + 2:]
        out = []
        while rest:
            if rest[0] == "":
                out.append("")
                rest = rest[1:]
            else:
                out.append(tuple(rest[:3]))
                rest = rest[3:]
        return out

    def test_the_menu_argv(self):
        now = time.time()  # wall clock
        self.write({"sound": {"since": now, "until": now + 41 * 60 + 30}})  # wall clock
        argv = self.menu()
        head = argv[:argv.index("-y") + 2]
        self.assertEqual(head, ["display-menu", "-M", "-c", CLIENT, "-t", "$3:", "-T",
                                "#[align=centre]Mute: sound 42m" + DOT + "toasts on",
                                "-x", "C", "-y", CENTRE_Y])
        items = self.items(argv)
        self.assertEqual([i if i == "" else i[0] for i in items],
                         ["Mute both for 1 hour", "Mute both until unmuted",
                          "Mute sound for 1 hour", "Mute sound until unmuted",
                          "Mute toasts for 1 hour", "Mute toasts until unmuted", "",
                          "Unmute sound", "-Unmute toasts", "Unmute all"])
        keys = [i[1] for i in items if i]
        self.assertEqual(len(set(keys)), len(keys))
        want = {"Mute both for 1 hour": "on all --for 1h", "Mute both until unmuted":
                "on all --until-off", "Mute sound for 1 hour": "on sound --for 1h",
                "Mute sound until unmuted": "on sound --until-off",
                "Mute toasts for 1 hour": "on toast --for 1h",
                "Mute toasts until unmuted": "on toast --until-off",
                "Unmute sound": "off sound", "-Unmute toasts": "off toast",
                "Unmute all": "off all"}
        for name, _, command in (i for i in items if i):
            with self.subTest(item=name):
                self.assertEqual(command, "run-shell '%s %s --client %s >/dev/null 2>&1; true'"
                                 % (SCRIPT, want[name], CLIENT))
        self.assertEqual(self.calls("display-message"), [])
        self.assertEqual(sorted(self.on_disk()), ["sound"])  # the menu itself writes nothing

    def test_the_menu_opens_at_row_0_under_a_top_bar(self):
        # test_tmux_tab_bar's row-0 check scans the confs; this menu lives here.
        with open(os.path.join(REPO, "tmux", "claude.conf"), encoding="utf-8") as f:
            self.assertIn("set -g @overlay_y_centre '%s'\n" % CENTRE_Y, f.read())
        self.assertEqual(cm.MENU_Y, CENTRE_Y)
        argv = self.menu()
        self.assertEqual(argv[argv.index("-y") + 1], CENTRE_Y)
        self.assertEqual(argv[argv.index("-x") + 1], "C")

    def test_the_menu_title_and_dim_items_follow_the_state(self):
        argv = self.menu()
        self.assertEqual(argv[argv.index("-T") + 1],
                         "#[align=centre]Mute: sound on" + DOT + "toasts on")
        names = [i[0] for i in self.items(argv) if i]
        self.assertIn("-Unmute sound", names)
        self.assertIn("-Unmute toasts", names)
        self.assertIn("Unmute all", names)                   # clears a bad flag too
        self.write({"sound": OFF, "toast": [1]})
        argv = self.menu()
        self.assertEqual(argv[argv.index("-T") + 1], "#[align=centre]Mute: sound muted" + DOT
                         + "toasts on" + DOT + "flag malformed")
        names = [i[0] for i in self.items(argv) if i]
        self.assertIn("Unmute sound", names)
        self.assertIn("-Unmute toasts", names)

    def test_a_client_the_server_doesnt_list_gets_no_session(self):
        argv = self.menu("/dev/pts/44")
        self.assertEqual(argv[:4], ["display-menu", "-M", "-c", "/dev/pts/44"])
        self.assertNotIn("-t", argv[:argv.index("-T")])

    def test_no_client_opens_where_tmux_puts_it_and_its_items_tell_no_one(self):
        argv = self.menu("")
        self.assertEqual(argv[:3], ["display-menu", "-M", "-T"])
        for name, _, command in (i for i in self.items(argv) if i):
            with self.subTest(item=name):
                self.assertNotIn("--client", command)
                self.assertTrue(command.endswith(" >/dev/null 2>&1; true'"), command)

    def test_a_client_name_run_shell_cant_quote_gets_a_message_not_a_menu(self):
        for client in ("/dev/pts/1'x", "/dev/pts/#1", "/dev/pts/\x01"):
            with self.subTest(client=client):
                self.assertIsNone(self.menu(client))
                m = self.calls("display-message")[-1]
                self.assertEqual(m[1:3], ["-c", client])
                self.assertIn("can't build the menu", m[3])

    def test_an_item_mutes_and_answers_on_the_client(self):
        argv = self.menu()
        command = dict((i[0], i[2]) for i in self.items(argv) if i)["Mute toasts until unmuted"]
        inner = re.fullmatch(r"run-shell '(.*)'", command).group(1)
        p = subprocess.run(["sh", "-c", inner], capture_output=True, timeout=20, env=self.env)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, b"", b""))
        self.assertEqual(sorted(self.on_disk()), ["toast"])
        self.assertIsNone(self.on_disk()["toast"]["until"])
        [m] = self.calls("display-message")
        self.assertEqual(m, ["display-message", "-c", CLIENT,
                             "claude-mute: sound on" + DOT + "toasts muted until unmuted"])
        # Unmute all, then a timed one: the line names the local time it ends.
        for name in ("Unmute all", "Mute sound for 1 hour"):
            command = dict((i[0], i[2]) for i in self.items(self.menu()) if i)[name]
            inner = re.fullmatch(r"run-shell '(.*)'", command).group(1)
            subprocess.run(["sh", "-c", inner], timeout=20, env=self.env, check=True)
        until = ends(self.on_disk()["sound"]["until"], self.offset)
        self.assertEqual(self.calls("display-message")[-1][3],
                         "claude-mute: sound muted until %s" % until + DOT + "toasts on")

    def test_a_hash_in_a_message_is_doubled(self):
        cm.tell(None, "x#y")                                  # no client: no message at all
        with mock.patch.object(cm, "tmux") as tmux:
            cm.tell(CLIENT, "a#[b] c#d")
        tmux.assert_called_once_with("display-message", "-c", CLIENT, "claude-mute: a[b] c##d")


class Mode(unittest.TestCase):
    def test_the_script_is_executable(self):
        self.assertTrue(os.stat(SCRIPT).st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
