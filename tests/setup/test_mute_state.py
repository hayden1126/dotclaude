"""hooks/mute_state.py: the device-wide mute's flag, its reader's notes and its locked writer
(stdlib only). Each test gets its own XDG_STATE_HOME. hooks/notify.sh and hooks/stop-ring.sh
obeying it: tests/setup/test_tmux_hooks.py."""
import fcntl
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
SCRIPT = os.path.join(REPO, "hooks", "mute_state.py")

spec = importlib.util.spec_from_file_location("mute_state", SCRIPT)
ms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ms)

NOW = 1_800_000_000.0
ON = {"since": NOW - 60, "until": None}


class MuteState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.state = os.path.join(self.tmp, "state")
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.state})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.flag = os.path.join(self.state, "dotclaude", "mute.json")

    def write(self, flag):
        """The flag file: a dict as JSON, str or bytes as they are."""
        os.makedirs(os.path.dirname(self.flag), exist_ok=True)
        if isinstance(flag, dict):
            flag = json.dumps(flag)
        with open(self.flag, "wb") as f:
            f.write(flag.encode() if isinstance(flag, str) else flag)

    def on_disk(self):
        with open(self.flag, encoding="utf-8") as f:
            return json.load(f)

    def check(self, *args):
        p = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True,
                           timeout=10, env={**os.environ, "XDG_STATE_HOME": self.state})
        return p.returncode, p.stdout, p.stderr

    # --- the reader -----------------------------------------------------------------------

    def test_paths_live_in_the_state_dir(self):
        self.assertEqual(ms.flag_path(), self.flag)
        self.assertEqual(ms.lock_path(), os.path.join(self.state, "dotclaude", "mute.lock"))

    def test_the_state_dir_is_autopass_states(self):
        # mute_state keeps its own copy of the rule so a read never imports autopass_state.
        aspec = importlib.util.spec_from_file_location(
            "autopass_state", os.path.join(REPO, "hooks", "autopass_state.py"))
        aps = importlib.util.module_from_spec(aspec)
        aspec.loader.exec_module(aps)
        for env in ({"XDG_STATE_HOME": self.state}, {"XDG_STATE_HOME": ""}, {}):
            with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=False):
                if not env:
                    os.environ.pop("XDG_STATE_HOME", None)
                self.assertEqual(ms.state_dir(), aps.state_dir())

    def test_no_file_mutes_nothing_without_a_note(self):
        self.assertEqual(ms.current(NOW), ({}, None))
        os.makedirs(os.path.dirname(self.flag))
        self.assertEqual(ms.current(NOW), ({}, None))

    def test_each_switch_alone(self):
        self.write({"sound": ON})
        self.assertEqual(ms.current(NOW), ({"sound": ON}, None))
        self.write({"toast": {"since": NOW, "until": NOW + 3600}})
        self.assertEqual(ms.current(NOW), ({"toast": {"since": NOW, "until": NOW + 3600}}, None))
        self.assertEqual(ms.check_line(NOW), "0 1 -")

    def test_expiry_at_the_boundary(self):
        for until, muted in ((NOW + 0.001, True), (NOW, False), (NOW - 1, False), (None, True)):
            with self.subTest(until=until):
                self.write({"sound": {"since": NOW - 10, "until": until}})
                self.assertEqual("sound" in ms.current(NOW)[0], muted)
                self.assertIsNone(ms.current(NOW)[1])   # an expired mute is no fault

    def test_unknown_keys_are_ignored(self):
        self.write({"sound": {**ON, "by": "menu"}, "volume": 3, "toast": ON})
        self.assertEqual(ms.current(NOW), ({"sound": ON, "toast": ON}, None))

    def test_unreadable_flags(self):
        cases = {"a directory": lambda: os.makedirs(self.flag),
                 "a dangling link": lambda: os.symlink(os.path.join(self.tmp, "gone"), self.flag),
                 "a FIFO": lambda: os.mkfifo(self.flag)}
        if os.geteuid() != 0:   # root reads a mode-000 file
            cases["mode 000"] = lambda: (self.write({"sound": ON}), os.chmod(self.flag, 0))
        for name, make in cases.items():
            with self.subTest(name):
                os.makedirs(os.path.dirname(self.flag), exist_ok=True)
                make()
                self.assertEqual(ms.current(NOW), ({}, "unreadable"))
                # A FIFO can't hang it: the subprocess's timeout would fail the test.
                self.assertEqual(self.check("check"), (0, "0 0 unreadable\n", ""))
                if os.path.isdir(self.flag) and not os.path.islink(self.flag):
                    os.rmdir(self.flag)
                else:
                    os.unlink(self.flag)

    def test_malformed_flags(self):
        deep = '{"sound": ' + "[" * 30000 + "]" * 30000 + "}"   # json recurses on nesting
        self.assertLess(len(deep), ms.MAX_BYTES)
        cases = {"not JSON": "{sound", "empty": "", "not UTF-8": b'{"sound": "\xff"}',
                 "a UTF-8 BOM": b"\xef\xbb\xbf{}", "deep": deep, "a list": "[]", "null": "null",
                 "past the cap": json.dumps({"sound": ON}) + " " * ms.MAX_BYTES,
                 # past Python's 4,300-digit int conversion limit: json.loads raises ValueError
                 "a 5,000-digit number": '{"sound": {"since": 1%s, "until": null}}' % ("0" * 5000)}
        for name, raw in cases.items():
            with self.subTest(name):
                self.write(raw)
                self.assertEqual(ms.current(NOW), ({}, "malformed"))
                self.assertEqual(self.check("check"), (0, "0 0 malformed\n", ""))

    def test_the_cap_itself_still_reads(self):
        body = json.dumps({"sound": ON})
        self.write(body + " " * (ms.MAX_BYTES - len(body)))
        self.assertEqual(ms.current(NOW), ({"sound": ON}, None))

    def test_a_switch_of_the_wrong_shape(self):
        bad = ["yes", True, None, [], {}, {"since": NOW}, {"until": None},
               {"since": True, "until": None}, {"since": NOW, "until": False},
               {"since": "1", "until": None}, {"since": NOW, "until": "never"},
               {"since": float("nan"), "until": None}, {"since": NOW, "until": float("inf")},
               # stamps out of range: math.isfinite(10**400) and time.localtime(1e308) raise
               # OverflowError, and a negative epoch is no time a mute was set or ends
               {"since": NOW, "until": 10 ** 400}, {"since": 10 ** 400, "until": None},
               {"since": -10 ** 400, "until": None}, {"since": NOW, "until": 1e308},
               {"since": -1, "until": None}, {"since": NOW, "until": -0.5},
               {"since": NOW, "until": 2 ** 32}, {"since": 2.0 ** 32, "until": None}]
        for value in bad:
            with self.subTest(value=value):
                self.write(json.dumps({"sound": value, "toast": ON}))
                self.assertEqual(ms.current(NOW), ({"toast": ON}, "malformed"))
                self.assertEqual(ms.check_line(NOW), "0 1 malformed")

    def test_ints_and_floats_are_numbers(self):
        self.write({"sound": {"since": 5, "until": int(NOW) + 1},
                    "toast": {"since": 5.5, "until": None}})
        self.assertEqual(ms.check_line(NOW), "1 1 -")

    def test_stamps_run_from_0_up_to_2_to_the_32(self):
        # 2**32 is 2106, and time.localtime takes anything below it.
        self.write({"sound": {"since": 0, "until": 2 ** 32 - 1},
                    "toast": {"since": 0.0, "until": 2.0 ** 32 - 0.5}})
        self.assertEqual(ms.check_line(NOW), "1 1 -")
        for stamp in (0, 2 ** 32 - 1, 2.0 ** 32 - 0.5):
            time.localtime(stamp)

    def test_check_prints_one_line_and_exits_0(self):
        self.assertEqual(self.check("check"), (0, "0 0 -\n", ""))
        self.write({"sound": ON, "toast": {"since": 1, "until": time.time() + 3600}})  # wall clock
        self.assertEqual(self.check("check"), (0, "1 1 -\n", ""))
        for args in ((), ("status",), ("check", "x")):
            with self.subTest(args=args):
                code, out, err = self.check(*args)
                self.assertEqual((code, out), (2, ""))
                self.assertIn("usage", err)

    # --- the writer -----------------------------------------------------------------------

    def test_mute_then_unmute_round_trips(self):
        sound = {"since": NOW, "until": None}
        toast = {"since": NOW + 1, "until": NOW + 3600}
        self.assertEqual(ms.mute(["sound"], None, now=NOW), {"sound": sound})
        self.assertEqual(self.on_disk(), {"sound": sound})
        self.assertEqual(ms.current(NOW + 10**6)[0], {"sound": sound})
        ms.mute(("toast",), NOW + 3600, now=NOW + 1)
        self.assertEqual(self.on_disk(), {"sound": sound, "toast": toast})
        self.assertEqual(ms.unmute(["sound"], now=NOW + 2), {"toast": toast})
        self.assertEqual(ms.check_line(NOW + 2), "0 1 -")
        self.assertEqual(ms.unmute(["toast"], now=NOW + 3), {})
        self.assertFalse(os.path.lexists(self.flag))   # nothing muted: the hooks' fast path
        self.assertEqual(ms.unmute(["sound", "toast"], now=NOW + 4), {})   # no file: still fine

    def test_a_remute_moves_since_and_until(self):
        ms.mute(["sound"], NOW + 60, now=NOW)
        ms.mute(["sound"], None, now=NOW + 30)
        self.assertEqual(self.on_disk(), {"sound": {"since": NOW + 30, "until": None}})

    def test_expired_entries_are_pruned_on_write(self):
        self.write({"sound": {"since": NOW - 7200, "until": NOW - 3600}, "toast": ON})
        ms.mute(["toast"], NOW + 60, now=NOW)
        self.assertEqual(self.on_disk(), {"toast": {"since": NOW, "until": NOW + 60}})
        self.write({"sound": {"since": NOW - 7200, "until": NOW - 3600}})
        ms.unmute(["toast"], now=NOW)
        self.assertFalse(os.path.lexists(self.flag))

    def test_a_write_over_a_bad_flag_starts_empty(self):
        for raw in ("{garbage", json.dumps({"sound": "yes", "toast": ON, "x": 1})):
            with self.subTest(raw=raw):
                self.write(raw)
                ms.mute(["sound"], None, now=NOW)
                kept = {"toast": ON} if "toast" in raw else {}
                self.assertEqual(self.on_disk(), {**kept, "sound": {"since": NOW, "until": None}})
                self.assertEqual(ms.current(NOW)[1], None)
        self.write("{garbage")
        ms.unmute(["sound"], now=NOW)
        self.assertFalse(os.path.lexists(self.flag))

    def test_a_directory_at_the_path_raises(self):
        os.makedirs(self.flag)
        with self.assertRaises(OSError):
            ms.mute(["sound"], None, now=NOW)
        with self.assertRaises(OSError):
            ms.unmute(["sound"], now=NOW)

    def test_bad_arguments_raise_and_write_nothing(self):
        for names, until in ((["volume"], None), ([], None), ("sound", None),
                             (["sound"], NOW), (["sound"], NOW - 1), (["sound"], True),
                             (["sound"], "later"), (["sound"], float("inf")),
                             (["sound"], 10 ** 400), (["sound"], 1e308), (["sound"], 2 ** 32)):
            with self.subTest(names=names, until=until):
                with self.assertRaises(ValueError):
                    ms.mute(names, until, now=NOW)
        with self.assertRaises(ValueError):
            ms.unmute(["all"], now=NOW)
        self.assertFalse(os.path.lexists(self.flag))

    def test_two_writers_at_once_both_land(self):
        # The menu and the CLI can race. The test holds the lock, so both writers queue on it
        # with nothing written; once it lets go, each one's read-modify-write keeps the other's.
        code = ("import sys; sys.path.insert(0, %r); import mute_state; "
                "mute_state.mute([sys.argv[1]], None)") % os.path.dirname(SCRIPT)
        os.makedirs(os.path.dirname(self.flag))
        env = {**os.environ, "XDG_STATE_HOME": self.state}
        fd = os.open(ms.lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            procs = [subprocess.Popen([sys.executable, "-I", "-c", code, name], env=env)
                     for name in ("sound", "toast")]
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                self.assertFalse(os.path.lexists(self.flag), "a writer didn't wait for the lock")
                time.sleep(0.05)
        finally:
            os.close(fd)
        for p in procs:
            self.assertEqual(p.wait(timeout=10), 0)
        self.assertEqual(sorted(self.on_disk()), ["sound", "toast"])
        self.assertEqual(ms.check_line(), "1 1 -")


if __name__ == "__main__":
    unittest.main()
