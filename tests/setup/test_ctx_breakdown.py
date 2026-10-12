"""statusline/ctx-breakdown.py: the total chip's auto-pass colors, the on/off cue and the
`window` it writes into ctx/<session>.json for the watcher (stdlib only).

The widget runs as ccstatusline runs it: a subprocess with the statusline JSON on stdin. Each
test has its own HOME (no settings.json, so the window is the model's or 600k, and
~/.config/dotclaude/pass.toml) and XDG_STATE_HOME, a stub tmux on PATH that answers `display`
with $STUB_SERVER, and an env scrubbed of CLAUDE* and TMUX*."""
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WIDGET = os.path.join(REPO, "statusline", "ctx-breakdown.py")
HOOKS = os.path.join(REPO, "hooks")

spec = importlib.util.spec_from_file_location("autopass_state",
                                              os.path.join(HOOKS, "autopass_state.py"))
aps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aps)

STUB = """#!/usr/bin/env bash
case "$1" in
  display|display-message)
    [ -n "${STUB_SERVER:-}" ] || exit 1
    printf '%s\\n' "$STUB_SERVER" ;;
esac
exit 0
"""
SOCKET = "/tmp/tmux-1000/default"
SERVER = f"1791222157 4321 {SOCKET}"
TAB = {"socket": SOCKET, "server_start": 1791222157, "server_pid": 4321, "pane": "%7"}
SID = "5e2f0c1a-aaaa-bbbb-cccc-000000000002"
RESET = "\x1b[0m"


def chip(bg, fg, label, value, bold=False):
    return ("\x1b[1m" if bold else "") + f"\x1b[48;5;{bg}m\x1b[38;5;{fg}m {label} {value} {RESET}"


class Widget(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.state = os.path.join(self.tmp, "state")
        self.bin = os.path.join(self.tmp, "bin")
        self.cwd = os.path.join(self.tmp, "work")  # not a git repo: no lanes
        for d in (self.home, self.bin, self.cwd):
            os.makedirs(d)
        self.stub("tmux", STUB)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(HOME=self.home, XDG_STATE_HOME=self.state,
                        PATH=self.bin + os.pathsep + os.environ["PATH"])

    def stub(self, name, text):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def pass_toml(self, text):
        d = os.path.join(self.home, ".config", "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "pass.toml"), "w") as f:
            f.write(text)

    def payload(self, tokens, window=600000, sid=SID, cwd=None):
        return {"session_id": sid, "cwd": cwd or self.cwd,
                "context_window": {"total_input_tokens": tokens,
                                   "context_window_size": window}}

    def run_widget(self, payload, widget=WIDGET, args=(), env=None):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        p = subprocess.run([sys.executable, widget, *args], input=stdin, capture_output=True,
                           text=True, env={**self.env, **(env or {})}, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        return p.stdout.rstrip("\n")

    def ctx_file(self):
        return os.path.join(self.state, "dotclaude", "ctx", SID + ".json")

    def read_ctx(self):
        with open(self.ctx_file()) as f:
            return json.load(f)

    def write_ctx(self, rec):
        os.makedirs(os.path.dirname(self.ctx_file()), exist_ok=True)
        with open(self.ctx_file(), "w") as f:
            json.dump(rec, f)


class Colors(Widget):
    def bands(self, window, cases):
        for tokens, (bg, fg, label, bold) in cases:
            with self.subTest(window=window, tokens=tokens):
                out = self.run_widget(self.payload(tokens, window), args=("--no-pct",))
                fmt = f"{tokens / 1000:.0f}k" if tokens >= 99500 else f"{tokens / 1000:.1f}k"
                self.assertEqual(out, chip(bg, fg, label, fmt, bold))

    def test_bands_at_600k(self):
        # tiers 300k / 480k / 520k
        self.bands(600000, [(299000, (22, 114, "Ctx", False)),
                            (300000, (136, 230, "Ctx", False)),
                            (479000, (136, 230, "Ctx", False)),
                            (480000, (88, 210, "Ctx", False)),
                            (519000, (88, 210, "Ctx", False)),
                            (520000, (160, 231, "Ctx!", True)),
                            (580000, (160, 231, "Ctx!", True))])

    def test_bands_at_a_200k_window(self):
        # tiers 100k / 137k / 151k, from the model window under the 600k default
        self.bands(200000, [(99000, (22, 114, "Ctx", False)),
                            (100000, (136, 230, "Ctx", False)),
                            (137000, (88, 210, "Ctx", False)),
                            (151000, (160, 231, "Ctx!", True))])

    def test_autocompact_window_under_the_model_window_sets_the_tiers(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as f:
            json.dump({"autoCompactWindow": 200000}, f)
        out = self.run_widget(self.payload(140000, 1000000), args=("--no-pct",))
        self.assertTrue(out.startswith("\x1b[48;5;88m"), repr(out))

    def test_a_window_too_small_for_tiers_falls_back_to_shares(self):
        self.assertIsNone(aps.tiers(100000, {}))
        out = self.run_widget(self.payload(90000, 100000), args=("--no-pct",))
        self.assertEqual(out, chip(160, 231, "Ctx!", "90.0k", True))  # past 83%
        out = self.run_widget(self.payload(40000, 100000), args=("--no-pct",))
        self.assertEqual(out, chip(22, 114, "Ctx", "40.0k"))

    def test_the_percent_and_the_chips_are_unchanged(self):
        out = self.run_widget(self.payload(100000))
        self.assertEqual(out, chip(22, 114, "Ctx", "100k 17%"))
        out = self.run_widget(self.payload(100000), args=("--chips",))
        self.assertEqual(out, chip(22, 114, "Ctx", "100k 17%") + " (run /context for split)")


class Cue(Widget):
    def test_off_by_default_and_on_from_pass_toml(self):
        self.assertEqual(self.run_widget(self.payload(100000)),
                         chip(22, 114, "Ctx", "100k 17%"))
        self.pass_toml("autopass = true\n")
        os.remove(os.path.join(self.state, "dotclaude", "ctx-widget", SID + ".json"))
        self.assertEqual(self.run_widget(self.payload(100000)),
                         chip(22, 114, "Ctx", "100k 17% A"))

    def test_the_answer_is_cached_for_the_ttl(self):
        self.pass_toml("autopass = true\n")
        self.assertTrue(self.run_widget(self.payload(100000)).endswith(f" A {RESET}"))
        self.pass_toml("autopass = false\n")
        self.assertTrue(self.run_widget(self.payload(100000)).endswith(f" A {RESET}"))
        path = os.path.join(self.state, "dotclaude", "ctx-widget", SID + ".json")
        with open(path) as f:
            cache = json.load(f)
        self.assertEqual(cache["source"], "pass.toml")
        cache["at"] -= 11  # past the 10 s TTL
        with open(path, "w") as f:
            json.dump(cache, f)
        self.assertFalse(self.run_widget(self.payload(100000)).endswith(f" A {RESET}"))

    def test_a_tab_toggle_shows_at_once(self):
        self.pass_toml("autopass = true\n")
        env = {"TMUX": SOCKET + ",1,0", "TMUX_PANE": "%7", "STUB_SERVER": SERVER}
        self.assertTrue(self.run_widget(self.payload(100000), env=env).endswith(f" A {RESET}"))
        old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.state
        try:
            aps.set_flag("%7", TAB, False)  # /autopass off: a new generation
        finally:
            if old is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old
        self.assertFalse(self.run_widget(self.payload(100000), env=env).endswith(f" A {RESET}"))

    def test_a_slow_git_costs_the_budget_and_shows_off(self):
        self.pass_toml("autopass = true\n")  # what a decide() that ran to the end would say
        self.stub("git", "#!/bin/sh\nexec sleep 5\n")
        start = time.monotonic()
        out = self.run_widget(self.payload(100000))
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(out, chip(22, 114, "Ctx", "100k 17%"))
        with open(os.path.join(self.state, "dotclaude", "ctx-widget", SID + ".json")) as f:
            self.assertEqual(json.load(f)["source"], "unknown")

    def test_no_session_id_no_cue(self):
        self.pass_toml("autopass = true\n")
        out = self.run_widget(self.payload(100000, sid=None))
        self.assertEqual(out, chip(22, 114, "Ctx", "100k 17%"))


class Window(Widget):
    def test_merges_into_an_existing_ctx_file(self):
        self.write_ctx({"tokens": 123456, "time": 1.5})
        before = time.time()
        self.run_widget(self.payload(100000))
        rec = self.read_ctx()
        self.assertEqual((rec["tokens"], rec["time"], rec["window"]), (123456, 1.5, 600000))
        self.assertGreaterEqual(rec["window_at"], before)

    def test_writes_a_change_even_when_fresh(self):
        self.write_ctx({"tokens": 5, "window": 600000, "window_at": time.time()})
        self.run_widget(self.payload(100000, 200000))
        self.assertEqual(self.read_ctx()["window"], 200000)
        self.run_widget(self.payload(100000, 1000000))  # and back up
        self.assertEqual(self.read_ctx()["window"], 1000000)

    def test_skips_an_unchanged_fresh_window_and_rewrites_a_stale_one(self):
        fresh = time.time() - 5
        self.write_ctx({"tokens": 5, "window": 600000, "window_at": fresh})
        self.run_widget(self.payload(100000))
        self.assertEqual(self.read_ctx()["window_at"], fresh)
        self.write_ctx({"tokens": 5, "window": 600000, "window_at": fresh - 60})
        self.run_widget(self.payload(100000))
        self.assertGreater(self.read_ctx()["window_at"], fresh)

    def test_writes_before_the_first_token_count(self):
        self.assertEqual(self.run_widget(self.payload(0)), "Ctx ?")
        self.assertEqual(self.read_ctx()["window"], 600000)

    def test_no_write_for_a_bad_window_or_session_id(self):
        for window, sid in ((1000, SID), ("600000", SID), (True, SID), (600000, "../x"),
                            (600000, None)):
            with self.subTest(window=window, sid=sid):
                self.run_widget(self.payload(100000, window, sid=sid))
                self.assertFalse(os.path.exists(self.ctx_file()))
        self.assertFalse(os.path.exists(os.path.join(self.state, "dotclaude", "x.json")))

    def test_the_tiers_follow_the_window_it_wrote(self):
        self.run_widget(self.payload(100000, 200000))
        win = aps.window(None, self.read_ctx()["window"])
        self.assertEqual(aps.tiers(win, {})["soft"], 100000)


def load_widget():
    spec = importlib.util.spec_from_file_location("ctx_breakdown", WIDGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class InProcess(Widget):
    """The widget loaded in-process, for the races a subprocess can't time."""

    def setUp(self):
        super().setUp()
        handler = signal.getsignal(signal.SIGALRM)
        self.addCleanup(signal.signal, signal.SIGALRM, handler)
        self.addCleanup(signal.setitimer, signal.ITIMER_REAL, 0)
        patch = mock.patch.dict(os.environ, XDG_STATE_HOME=self.state, HOME=self.home)
        patch.start()
        self.addCleanup(patch.stop)
        self.w = load_widget()
        self.aps = self.w.load_aps()
        self.cache = os.path.join(self.state, "dotclaude", "ctx-widget", SID + ".json")

    def alarm_at_cancel(self, which):
        """setitimer that raises Slow on its `which`th cancel (0 = the first), as if the alarm
        landed right there, after decide() returned."""
        real, cancels = signal.setitimer, []

        def fake(kind, value):
            real(kind, value)
            if value == 0:
                cancels.append(1)
                if len(cancels) == which + 1:
                    raise self.w.Slow
        return mock.patch.object(self.w.signal, "setitimer", side_effect=fake)

    def test_an_alarm_after_decide_returned_caches_off(self):
        for which in (0, 1):  # inside the try, then in the finally
            with self.subTest(cancel=which):
                if os.path.exists(self.cache):
                    os.remove(self.cache)
                with self.alarm_at_cancel(which), \
                        mock.patch.object(self.aps, "decide", return_value=(True, "pass.toml")):
                    self.assertFalse(self.w.autopass_on(self.aps, SID, self.cwd, None))
                with open(self.cache) as f:
                    self.assertEqual(json.load(f)["source"], "unknown")

    def test_an_alarm_inside_decide_caches_off(self):
        def slow(*_):
            raise self.w.Slow
        with mock.patch.object(self.aps, "decide", side_effect=slow):
            self.assertFalse(self.w.autopass_on(self.aps, SID, self.cwd, None))

    def test_the_window_write_never_rolls_back_the_watchers_tokens(self):
        self.aps.write_ctx(SID, 100, 1.0)
        real_read = self.aps.read_ctx
        calls = []

        def read_then_watcher_writes(sid):
            rec = real_read(sid)
            if not calls:  # the widget's freshness check saw tokens 100; now the watcher runs
                calls.append(1)
                self.aps.write_ctx(SID, 200, 2.0)
            return rec
        with mock.patch.object(self.aps, "read_ctx", side_effect=read_then_watcher_writes):
            self.w.write_window(self.aps, SID, 600000)
        rec = self.read_ctx()
        self.assertEqual((rec["tokens"], rec["time"], rec["window"]), (200, 2.0, 600000))

    def test_a_busy_lock_skips_the_window_write_and_the_next_render_retries(self):
        self.aps.write_ctx(SID, 100, 1.0)
        with self.aps.watch_lock(SID, kind=".ctx") as locked:
            self.assertTrue(locked)
            self.run_widget(self.payload(100000))  # another process: the lock is busy
            self.assertNotIn("window", self.read_ctx())
        self.run_widget(self.payload(100000))
        self.assertEqual(self.read_ctx()["window"], 600000)
        self.assertEqual(self.read_ctx()["tokens"], 100)

    def test_the_watchers_write_under_a_busy_lock_returns_the_merge_unwritten(self):
        self.aps.merge_ctx(SID, {"tokens": 100, "time": 1.0, "window": 200000})
        with self.aps.watch_lock(SID, kind=".ctx") as locked:
            self.assertTrue(locked)
            rec = self.aps.write_ctx(SID, 300, 3.0)  # waits its second, then gives up
        self.assertEqual(rec, {"tokens": 300, "time": 3.0, "window": 200000})
        self.assertEqual(self.read_ctx()["tokens"], 100)  # the next event writes
        with self.aps.watch_lock(SID) as locked:  # the watcher's own lock never blocks it
            self.assertTrue(locked)
            self.assertEqual(self.aps.write_ctx(SID, 400, 4.0)["tokens"], 400)
        self.assertEqual(self.read_ctx()["tokens"], 400)

    def test_old_cue_caches_are_pruned_once_a_day(self):
        d = os.path.dirname(self.cache)
        os.makedirs(d)
        old, fresh = os.path.join(d, "old.json"), os.path.join(d, "fresh.json")
        for path in (old, fresh):
            with open(path, "w") as f:
                f.write("{}")
        week = time.time() - 8 * 86400
        os.utime(old, (week, week))
        self.run_widget(self.payload(100000))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))
        self.assertTrue(os.path.exists(self.cache))
        with open(old, "w") as f:  # a second render the same day leaves it
            f.write("{}")
        os.utime(old, (week, week))
        os.remove(self.cache)
        self.run_widget(self.payload(100000))
        self.assertTrue(os.path.exists(old))


class Fallback(Widget):
    def copy(self):
        d = os.path.join(self.tmp, "copied")
        os.makedirs(d)
        shutil.copy(WIDGET, d)
        return os.path.join(d, "ctx-breakdown.py")

    def test_renders_without_autopass_state(self):
        widget = self.copy()  # no ../hooks beside it
        self.pass_toml("autopass = true\n")
        self.assertEqual(self.run_widget(self.payload(100000), widget=widget),
                         chip(22, 114, "Ctx", "100k 17%"))  # no cue
        self.assertEqual(self.run_widget(self.payload(530000), widget=widget, args=("--no-pct",)),
                         chip(160, 231, "Ctx!", "530k", True))  # 83% of 600k
        self.assertEqual(self.run_widget(self.payload(420000), widget=widget, args=("--no-pct",)),
                         chip(88, 210, "Ctx", "420k"))  # 66%
        self.assertFalse(os.path.exists(self.ctx_file()))

    def test_a_symlinked_widget_finds_the_hooks_by_its_real_path(self):
        d = os.path.join(self.tmp, "ccstatusline")
        os.makedirs(d)
        link = os.path.join(d, "ctx-breakdown.py")
        os.symlink(WIDGET, link)
        self.pass_toml("autopass = true\n")
        self.assertEqual(self.run_widget(self.payload(100000), widget=link),
                         chip(22, 114, "Ctx", "100k 17% A"))
        self.assertEqual(self.read_ctx()["window"], 600000)

    def test_garbage_stdin(self):
        for stdin in ("", "not json", "[1]", "5", "null", '{"context_window": "x"}',
                      '{"context_window": {"total_input_tokens": "abc"}}',
                      '{"context_window": {"current_usage": {"input_tokens": "x"}}}',
                      '{"session_id": 7, "cwd": 3, "transcript_path": 9, '
                      '"context_window": {"total_input_tokens": 100000, '
                      '"context_window_size": "big"}}'):
            with self.subTest(stdin=stdin):
                out = self.run_widget(stdin)  # exit 0, nothing on stderr
                self.assertTrue(out == "Ctx ?" or " Ctx 100k " in out, repr(out))


if __name__ == "__main__":
    unittest.main()
