"""tmux/claude-restore: reopen, after a reboot, the Claude tabs that were open in tmux `main`, each
running `claude --resume <id>` in its own directory (stdlib only).

hooks/session-registry.sh keeps one entry per open tab in
$XDG_STATE_HOME/dotclaude/open-sessions/. An entry from an earlier boot is a candidate. One with
no end mark is restored; one marked by SessionEnd `other` is restored only if it ended in the old
boot's final 120 s (a shutdown), not earlier (a window closed while work went on). Stubs stand in
for tmux and claude and record every call."""
import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "tmux", "claude-restore")

STUB = """#!/usr/bin/env bash
printf '%s\\n' "$(basename "$0") $*" >> "$STUB_LOG"
case "$(basename "$0") $1" in
  "tmux has-session") [ -n "${STUB_HAS_MAIN:-}" ] ;;
  "tmux new-window")
    n=$(( $(cat "$STUB_LOG.panes" 2>/dev/null || echo 100) + 1 ))
    echo "$n" > "$STUB_LOG.panes"
    printf '%%%s\\n' "$n" ;;
  "claude agents") [ -z "${STUB_AGENTS_FAIL:-}" ] || exit 1; printf '%s\\n' "${STUB_AGENTS:-[]}" ;;
esac
"""

OLD = "00000000-0000-0000-0000-00000000000a"
NOW_BOOT = "00000000-0000-0000-0000-00000000000b"


def sid(n):
    return f"{n:08d}-5e55-4000-8000-000000000000"


class Restore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        home = os.path.join(self.tmp, "home")
        local_bin = os.path.join(home, ".local", "bin")
        os.makedirs(stubs)
        os.makedirs(local_bin)
        # tmux's server PATH lacks ~/.local/bin, where claude lives: the script must add it.
        for path in (os.path.join(stubs, "tmux"), os.path.join(local_bin, "claude")):
            with open(path, "w") as f:
                f.write(STUB)
            os.chmod(path, 0o755)
        boot = os.path.join(self.tmp, "boot_id")
        with open(boot, "w") as f:
            f.write(NOW_BOOT + "\n")
        self.log = os.path.join(self.tmp, "calls.log")
        self.state = os.path.join(self.tmp, "state", "dotclaude")
        self.reg = os.path.join(self.state, "open-sessions")
        os.makedirs(self.reg)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(PATH=stubs + os.pathsep + "/usr/bin:/bin", HOME=home, STUB_LOG=self.log,
                        XDG_STATE_HOME=os.path.join(self.tmp, "state"),
                        DOTCLAUDE_BOOT_ID_FILE=boot, STUB_HAS_MAIN="1")
        self.now = time.time()

    # --- fixtures -----------------------------------------------------------------------

    def entry(self, n, window, pane=None, age=600, ended=None, boot=OLD, transcript=True,
              cwd=True, transcript_age=None):
        """Write a registry entry for session n, `age` seconds old, in a real cwd."""
        path = os.path.join(self.tmp, "code", f"repo{n}")
        if cwd:
            os.makedirs(path, exist_ok=True)
        tpath = os.path.join(self.tmp, "projects", f"{sid(n)}.jsonl")
        if transcript:
            os.makedirs(os.path.dirname(tpath), exist_ok=True)
            open(tpath, "w").close()
            t = self.now - (age if transcript_age is None else transcript_age)
            os.utime(tpath, (t, t))
        e = {"session_id": sid(n), "cwd": path, "transcript_path": tpath,
             "pane": pane or f"%{n}", "window_index": window, "boot_id": boot,
             "ts": self.now - age}
        if ended is not None:
            e["ended_other_at"] = self.now - ended
        with open(os.path.join(self.reg, sid(n) + ".json"), "w") as f:
            json.dump(e, f)
        return path

    def run_restore(self, *args):
        p = subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True,
                           timeout=20, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def calls(self, prefix="tmux"):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [c for c in f.read().splitlines() if c.startswith(prefix)]

    def resumed(self):
        """The (cwd, session id) pairs restored, in order, with each send-keys on its new pane."""
        out, pane_cwd = [], {}
        for c in self.calls():
            if c.startswith("tmux new-window"):
                words = c.split()
                self.assertIn("-d", words)
                self.assertEqual(words[words.index("-t") + 1], "=main:")
                pane_cwd[None] = words[words.index("-c") + 1]
            elif c.startswith("tmux send-keys"):
                words = c.split()
                self.assertEqual(words[-1], "Enter")
                self.assertEqual(words[4:6], ["claude", "--resume"])
                out.append((pane_cwd.pop(None), words[6], words[3]))
        panes = [p for _, _, p in out]
        self.assertEqual(panes, [f"%{101 + i}" for i in range(len(out))])  # each on its own pane
        return [(cwd, s) for cwd, s, _ in out]

    def registry(self, sub=""):
        d = os.path.join(self.reg, sub)
        return sorted(n for n in os.listdir(d) if n.endswith(".json")) if os.path.isdir(d) else []

    def restore_log(self):
        path = os.path.join(self.state, "restore.log")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return f.read().splitlines()

    # --- which entries come back --------------------------------------------------------

    def test_open_tabs_come_back_in_window_order(self):
        a = self.entry(1, window=4)
        b = self.entry(2, window=1)
        c = self.entry(3, window=2)
        self.run_restore()
        self.assertEqual(self.resumed(), [(b, sid(2)), (c, sid(3)), (a, sid(1))])

    def test_a_tab_killed_in_the_final_batch_comes_back(self):
        # A shutdown that signals claude marks every tab `other` within seconds of the end.
        a = self.entry(1, window=1, age=300, ended=5)
        b = self.entry(2, window=2, age=300, ended=4)
        self.run_restore()
        self.assertEqual(self.resumed(), [(a, sid(1)), (b, sid(2))])

    def test_a_tab_closed_earlier_stays_closed(self):
        # Window 1 was killed 15 minutes before the end; tab 2 kept working until the reboot.
        self.entry(1, window=1, age=1200, ended=900)
        b = self.entry(2, window=2, age=600, transcript_age=10)
        self.run_restore()
        self.assertEqual(self.resumed(), [(b, sid(2))])
        self.assertTrue(any(sid(1)[:8] in line and "skip" in line for line in self.restore_log()))

    def test_a_tab_closed_just_inside_the_window_comes_back(self):
        # The last activity is the transcript write 10 s before the end; 100 s before that is in.
        a = self.entry(1, window=1, age=1200, ended=110)
        b = self.entry(2, window=2, age=600, transcript_age=10)
        self.run_restore()
        self.assertEqual(self.resumed(), [(a, sid(1)), (b, sid(2))])

    def test_entries_from_this_boot_are_left_alone(self):
        self.entry(1, window=1, boot=NOW_BOOT)
        self.run_restore()
        self.assertEqual(self.resumed(), [])
        self.assertEqual(self.registry(), [sid(1) + ".json"])

    def test_a_live_session_is_not_resumed_twice(self):
        self.entry(1, window=1)
        b = self.entry(2, window=2)
        self.env["STUB_AGENTS"] = json.dumps([
            {"sessionId": sid(1), "pid": 4242, "kind": "interactive"},
            {"sessionId": sid(2), "kind": "interactive"}])  # no pid: not running
        self.run_restore()
        self.assertEqual(self.resumed(), [(b, sid(2))])

    def test_a_failing_agents_call_does_not_stop_the_restore(self):
        a = self.entry(1, window=1)
        self.env["STUB_AGENTS_FAIL"] = "1"
        self.run_restore()
        self.assertEqual(self.resumed(), [(a, sid(1))])

    def test_a_tab_with_no_transcript_reopens_as_a_fresh_claude(self):
        # A session writes no transcript before its first input (a tab fresh from /clear).
        a = self.entry(1, window=1)
        b = self.entry(2, window=2, transcript=False)
        self.run_restore()
        calls = [c for c in self.calls() if "new-window" in c or "send-keys" in c]
        self.assertEqual(len(calls), 4)
        self.assertIn(f"-c {a}", calls[0])
        self.assertTrue(calls[1].endswith(f"claude --resume {sid(1)} Enter"), calls[1])
        self.assertIn(f"-c {b}", calls[2])
        self.assertEqual(calls[3].split()[4:], ["claude", "Enter"])
        self.assertTrue(any("transcript" in line for line in self.restore_log()))
        self.assertEqual(self.registry("restored"), [sid(1) + ".json", sid(2) + ".json"])

    def test_a_missing_directory_is_skipped_and_logged(self):
        self.entry(1, window=1, cwd=False)
        self.run_restore()
        self.assertEqual(self.resumed(), [])
        self.assertTrue(any("cwd" in line or "directory" in line for line in self.restore_log()))

    def test_one_pane_restores_its_newest_session(self):
        # Claude crashed and a new claude started in the same pane.
        self.entry(1, window=1, pane="%5", age=900)
        b = self.entry(2, window=1, pane="%5", age=100)
        self.run_restore()
        self.assertEqual(self.resumed(), [(b, sid(2))])

    def test_an_unsafe_id_in_the_registry_is_never_typed(self):
        path = os.path.join(self.reg, "bad.json")
        with open(path, "w") as f:
            json.dump({"session_id": "x; rm -rf ~", "cwd": self.tmp, "pane": "%1",
                       "window_index": 1, "boot_id": OLD, "ts": self.now,
                       "transcript_path": "/nonexistent"}, f)
        self.run_restore()
        self.assertEqual(self.calls("tmux send-keys"), [])

    # --- modes --------------------------------------------------------------------------

    def test_list_changes_nothing(self):
        self.entry(1, window=1)
        self.entry(2, window=2, transcript=False)
        p = self.run_restore("--list")
        self.assertEqual([c for c in self.calls() if "new-window" in c or "send-keys" in c
                          or "new-session" in c], [])
        self.assertEqual(self.registry(), [sid(1) + ".json", sid(2) + ".json"])
        self.assertEqual(self.registry("restored"), [])
        self.assertIn(sid(1)[:8], p.stdout)
        self.assertIn("transcript", p.stdout)
        self.assertEqual(self.restore_log(), [])

    def test_auto_for_another_session_does_nothing(self):
        self.entry(1, window=1)
        self.run_restore("--auto", "view-123")
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.calls("claude"), [])
        self.assertEqual(self.registry(), [sid(1) + ".json"])

    def test_auto_for_main_restores(self):
        a = self.entry(1, window=1)
        self.run_restore("--auto", "main")
        self.assertEqual(self.resumed(), [(a, sid(1))])

    def test_a_manual_run_creates_main_when_absent(self):
        self.entry(1, window=1)
        del self.env["STUB_HAS_MAIN"]
        self.run_restore()
        tmux = self.calls()
        self.assertIn("tmux new-session -d -s main", tmux)
        self.assertLess(tmux.index("tmux new-session -d -s main"),
                        next(i for i, c in enumerate(tmux) if c.startswith("tmux new-window")))

    def test_a_second_run_restores_nothing(self):
        self.entry(1, window=1)
        self.run_restore()
        first = len(self.calls("tmux send-keys"))
        self.run_restore()
        self.assertEqual((first, len(self.calls("tmux send-keys"))), (1, 1))

    def test_restored_holds_only_the_last_restore(self):
        self.entry(1, window=1)
        self.run_restore()
        self.assertEqual(self.registry(), [])
        self.assertEqual(self.registry("restored"), [sid(1) + ".json"])
        self.entry(2, window=1)
        self.run_restore()
        self.assertEqual(self.registry("restored"), [sid(2) + ".json"])

    def test_every_decision_is_logged(self):
        self.entry(1, window=1)
        self.entry(2, window=2, cwd=False)
        self.run_restore()
        log = self.restore_log()
        self.assertEqual(len(log), 2)
        self.assertIn(sid(1)[:8], log[0])
        self.assertIn("repo1", log[0])
        self.assertIn("restored", log[0])
        self.assertIn("skip", log[1])

    def test_a_held_lock_means_another_run_is_restoring(self):
        self.entry(1, window=1)
        with open(os.path.join(self.reg, ".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.run_restore("--auto", "main")
        self.assertEqual(self.calls("tmux send-keys"), [])
        self.assertEqual(self.registry(), [sid(1) + ".json"])

    def test_no_registry_is_quiet(self):
        shutil.rmtree(self.reg)
        p = self.run_restore("--auto", "main")
        self.assertEqual((p.stdout, p.stderr), ("", ""))
        self.assertEqual(self.calls("tmux new-window"), [])

    def test_the_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
