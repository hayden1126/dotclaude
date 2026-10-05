"""tmux/claude-restore: reopen, after the tmux server dies (a reboot, `wsl --terminate`, `tmux
kill-server`), the Claude tabs that were open in it, each running `claude --resume <id>` in its
own directory (stdlib only).

hooks/session-registry.sh keeps one entry per open tab in
$XDG_STATE_HOME/dotclaude/open-sessions/, naming its server by socket path and start time. An
entry from the current socket but an earlier server is a candidate; other sockets are never
touched. One with no end mark is restored; one marked by SessionEnd `other` is restored only if
it ended in the old server's final 120 s (a shutdown), not earlier (a window closed while work
went on). Stubs stand in for tmux and claude and log each call's argv, one argument per field."""
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
{ printf '%s' "$(basename "$0")"; printf '\\x1f%s' "$@"; printf '\\n'; } >> "$STUB_LOG"
# The fds this call inherited: the restore's lock must not outlive it in a server or daemon.
{ printf '%s' "$(basename "$0") $1:"; ls /proc/$$/fd | tr '\\n' ' '; echo; } >> "$STUB_LOG.fds"
case "$(basename "$0") $1" in
  "tmux has-session") [ -n "${STUB_HAS_MAIN:-}" ] ;;
  "tmux display") printf '%s %s %s\\n' "$STUB_START" "$STUB_PID" "$STUB_SOCKET" ;;
  "tmux new-window")
    [ -z "${STUB_FAIL_NEW_WINDOW:-}" ] || exit 1
    n=$(( $(cat "$STUB_LOG.panes" 2>/dev/null || echo 100) + 1 ))
    echo "$n" > "$STUB_LOG.panes"
    printf '%%%s\\n' "$n" ;;
  "claude agents") [ -z "${STUB_AGENTS_FAIL:-}" ] || exit 1; printf '%s\\n' "${STUB_AGENTS:-[]}" ;;
esac
"""

SOCKET = "/tmp/tmux-1000/default"
OLD_START = 1_700_000_000
OLD_PID = 111
CUR_PID = 222


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
        self.log = os.path.join(self.tmp, "calls.log")
        self.state = os.path.join(self.tmp, "state", "dotclaude")
        self.reg = os.path.join(self.state, "open-sessions")
        os.makedirs(self.reg)
        self.now = time.time()
        # The old server died an hour ago; the current one started a minute ago.
        self.died = self.now - 3600
        self.start = int(self.now - 60)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(PATH=stubs + os.pathsep + "/usr/bin:/bin", HOME=home, STUB_LOG=self.log,
                        XDG_STATE_HOME=os.path.join(self.tmp, "state"), STUB_HAS_MAIN="1",
                        STUB_START=str(self.start), STUB_PID=str(CUR_PID),
                        STUB_SOCKET=SOCKET)

    # --- fixtures -----------------------------------------------------------------------

    def entry(self, n, window, pane=None, age=600, ended=None, transcript=True, cwd=True,
              transcript_age=None, socket=SOCKET, server_start=OLD_START, server_pid=OLD_PID,
              dirname=None, died=None):
        """Write an entry for session n, its times `age`/`ended` seconds before its server
        died (`died`, default the old server's), in a real cwd."""
        died = self.died if died is None else died
        path = os.path.join(self.tmp, "code", dirname or f"repo{n}")
        if cwd:
            os.makedirs(path, exist_ok=True)
        tpath = os.path.join(self.tmp, "projects", f"{sid(n)}.jsonl")
        if transcript:
            os.makedirs(os.path.dirname(tpath), exist_ok=True)
            open(tpath, "w").close()
            t = died - (age if transcript_age is None else transcript_age)
            os.utime(tpath, (t, t))
        e = {"session_id": sid(n), "cwd": path, "transcript_path": tpath,
             "pane": pane or f"%{n}", "window_index": window, "socket": socket,
             "server_start": server_start, "server_pid": server_pid, "ts": died - age}
        if ended is not None:
            e["ended_other_at"] = died - ended
        with open(os.path.join(self.reg, sid(n) + ".json"), "w") as f:
            json.dump(e, f)
        return path

    def touch(self, n, when):
        tpath = os.path.join(self.tmp, "projects", f"{sid(n)}.jsonl")
        os.utime(tpath, (when, when))

    def run_restore(self, *args):
        p = subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True,
                           timeout=20, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def calls(self, *prefix):
        """Each logged call as its argv list; with a prefix, only calls starting with it."""
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            argvs = [line.split("\x1f") for line in f.read().splitlines()]
        return [a for a in argvs if a[:len(prefix)] == list(prefix)]

    def resumed(self):
        """The (cwd, session id) pairs restored, in order, each typed into its own new pane."""
        out, cwd, panes = [], None, []
        for a in self.calls("tmux"):
            if a[1] == "new-window":
                self.assertEqual(a[:7], ["tmux", "new-window", "-d", "-P", "-F", "#{pane_id}",
                                         "-t"])
                self.assertEqual(a[7:9], ["=main:", "-c"])
                cwd = a[9]
            elif a[1] == "send-keys":
                self.assertEqual(len(a), 6, a)   # the command is ONE argument, then Enter
                self.assertEqual((a[2], a[5]), ("-t", "Enter"))
                panes.append(a[3])
                words = a[4].split(" ")
                self.assertEqual(words[:2], ["claude", "--resume"], a)
                out.append((cwd, words[2]))
        self.assertEqual(panes, [f"%{101 + i}" for i in range(len(panes))])
        return out

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

    def test_send_keys_types_the_command_as_one_argument(self):
        self.entry(1, window=1)
        self.run_restore()
        self.assertEqual([a[4:] for a in self.calls("tmux", "send-keys")],
                         [[f"claude --resume {sid(1)}", "Enter"]])

    def test_a_tab_killed_in_the_final_batch_comes_back(self):
        # A shutdown that signals claude marks every tab `other` within seconds of the end.
        a = self.entry(1, window=1, age=300, ended=5)
        b = self.entry(2, window=2, age=300, ended=4)
        self.run_restore()
        self.assertEqual(self.resumed(), [(a, sid(1)), (b, sid(2))])

    def test_a_tab_closed_earlier_stays_closed(self):
        # Window 1 was killed 15 minutes before the end; tab 2 kept working until the death.
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

    def test_activity_after_the_new_server_started_is_not_the_old_end(self):
        # Both tabs died in the shutdown. Since then something touched tab 1's transcript (a
        # `claude --resume` by hand under the new server): that is not the old server's end.
        a = self.entry(1, window=1, age=300, ended=5)
        b = self.entry(2, window=2, age=300, ended=4)
        self.touch(1, self.now - 5)
        self.run_restore()
        self.assertEqual(self.resumed(), [(a, sid(1)), (b, sid(2))])

    def test_entries_from_the_current_server_are_left_alone(self):
        self.entry(1, window=1, server_start=self.start, server_pid=CUR_PID)
        self.run_restore()
        self.assertEqual(self.resumed(), [])
        self.assertEqual(self.registry(), [sid(1) + ".json"])

    def test_entries_from_another_socket_are_never_touched(self):
        # A `tmux -L probe` server's tabs aren't main's.
        self.entry(1, window=1, socket="/tmp/tmux-1000/probe")
        b = self.entry(2, window=2)
        self.run_restore()
        self.assertEqual(self.resumed(), [(b, sid(2))])
        self.assertEqual(self.registry(), [sid(1) + ".json"])
        self.assertEqual(self.registry("restored"), [sid(2) + ".json"])
        self.assertFalse(any(sid(1)[:8] in line for line in self.restore_log()))

    def test_an_entry_with_malformed_server_fields_is_ignored_not_fatal(self):
        # A corrupt or hand-edited file (or one missing server_pid) must not block the rest.
        self.entry(1, window=1, server_pid=[1])
        self.entry(3, window=3, server_pid=None)
        self.entry(4, window=4, pane=["%4"])
        b = self.entry(2, window=2)
        self.run_restore()
        self.assertEqual(self.resumed(), [(b, sid(2))])
        self.assertEqual(self.registry(), [sid(1) + ".json", sid(3) + ".json", sid(4) + ".json"])

    def test_another_socket_in_the_same_pane_does_not_hide_the_tab(self):
        # Pane ids restart at %0 on every server, so a newer probe entry can share the pane.
        self.entry(1, window=1, pane="%3", age=900)
        self.entry(2, window=1, pane="%3", age=100, socket="/tmp/tmux-1000/probe")
        self.run_restore()
        self.assertEqual([s for _, s in self.resumed()], [sid(1)])

    def test_the_same_pane_on_two_old_servers_is_two_tabs(self):
        a = self.entry(1, window=1, pane="%3", age=900, server_start=OLD_START - 86400)
        b = self.entry(2, window=2, pane="%3", age=100)
        self.run_restore()
        self.assertEqual(self.resumed(), [(a, sid(1)), (b, sid(2))])

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
        calls = [x for x in self.calls("tmux") if x[1] in ("new-window", "send-keys")]
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0][9], a)
        self.assertEqual(calls[1][4:], [f"claude --resume {sid(1)}", "Enter"])
        self.assertEqual(calls[2][9], b)
        self.assertEqual(calls[3][4:], ["claude", "Enter"])
        self.assertTrue(any("transcript" in line for line in self.restore_log()))
        self.assertEqual(self.registry("restored"), [sid(1) + ".json", sid(2) + ".json"])

    def test_a_missing_directory_is_skipped_and_logged(self):
        self.entry(1, window=1, cwd=False)
        self.run_restore()
        self.assertEqual(self.resumed(), [])
        self.assertTrue(any("directory" in line for line in self.restore_log()))

    def test_a_hash_in_the_directory_is_skipped(self):
        # tmux format-expands new-window -c, so #{...} in a path would open somewhere else.
        self.entry(1, window=1, dirname="c#{pane_id}")
        b = self.entry(2, window=2)
        self.run_restore()
        self.assertEqual(self.resumed(), [(b, sid(2))])
        self.assertTrue(any(sid(1)[:8] in line and "#" in line for line in self.restore_log()))

    def test_a_tab_in_the_directory_name_keeps_the_fields_apart(self):
        a = self.entry(1, window=1, dirname="a\tb")
        self.run_restore()
        self.assertEqual(self.resumed(), [])  # skipped, not opened in a shifted directory
        self.assertEqual(self.registry("restored"), [sid(1) + ".json"])
        self.assertTrue(os.path.isdir(a))

    def test_one_pane_restores_its_newest_session(self):
        # Claude crashed and a new claude started in the same pane.
        self.entry(1, window=1, pane="%5", age=900)
        b = self.entry(2, window=1, pane="%5", age=100)
        self.run_restore()
        self.assertEqual(self.resumed(), [(b, sid(2))])

    def test_an_older_session_in_a_pane_stays_dead_when_the_newer_was_closed(self):
        # A pane runs one claude at a time, so the older entry in pane %5 is a dead session,
        # even though the newer one was closed long before the end and stays closed too.
        self.entry(1, window=1, pane="%5", age=1000)
        self.entry(2, window=1, pane="%5", age=950, ended=900)
        c = self.entry(3, window=2, age=600, transcript_age=10)
        self.run_restore()
        self.assertEqual(self.resumed(), [(c, sid(3))])

    def test_each_old_server_has_its_own_last_activity(self):
        # Server A was killed (tabs marked within seconds); server B started on the same socket,
        # its tab worked for an hour more, and then B died unsignalled. Both servers' tabs return.
        a_died = self.died - 3600
        a1 = self.entry(1, window=1, age=300, ended=5, server_start=OLD_START - 7200,
                        server_pid=101, died=a_died)
        a2 = self.entry(2, window=2, age=300, ended=4, server_start=OLD_START - 7200,
                        server_pid=101, died=a_died)
        b = self.entry(3, window=3, age=600, transcript_age=10)
        self.run_restore()
        self.assertEqual(self.resumed(), [(a1, sid(1)), (a2, sid(2)), (b, sid(3))])

    def test_a_same_second_restart_is_told_apart_by_pid(self):
        a = self.entry(1, window=1, server_start=self.start, server_pid=OLD_PID)
        self.run_restore()
        self.assertEqual(self.resumed(), [(a, sid(1))])

    def test_a_transcript_written_after_its_mark_does_not_move_the_end(self):
        # After the shutdown, `claude --continue` outside tmux wrote tab 1's transcript 600 s
        # later (still before the current server started): its mark still counts as the end.
        a = self.entry(1, window=1, age=300, ended=5)
        b = self.entry(2, window=2, age=300, ended=4)
        c = self.entry(3, window=3, age=300, ended=3)
        self.touch(1, self.died + 600)
        self.run_restore()
        self.assertEqual(self.resumed(), [(a, sid(1)), (b, sid(2)), (c, sid(3))])

    def test_the_lock_never_reaches_tmux_or_claude(self):
        # tmux new-session may start the server and claude agents the daemon: a lock fd they
        # inherit would outlive this run and block every later one.
        self.entry(1, window=1)
        del self.env["STUB_HAS_MAIN"]
        self.run_restore()
        with open(self.log + ".fds") as f:
            lines = f.read().splitlines()
        self.assertTrue(any(line.startswith("tmux new-session:") for line in lines))
        self.assertTrue(any(line.startswith("claude agents:") for line in lines))
        for line in lines:
            with self.subTest(call=line.split(":")[0]):
                self.assertNotIn("9", line.split(":", 1)[1].split())

    def test_an_unsafe_id_in_the_registry_is_never_typed(self):
        path = os.path.join(self.reg, "bad.json")
        with open(path, "w") as f:
            json.dump({"session_id": "x; rm -rf ~", "cwd": self.tmp, "pane": "%1",
                       "window_index": 1, "socket": SOCKET, "server_start": OLD_START,
                       "server_pid": OLD_PID,
                       "ts": self.died, "transcript_path": "/nonexistent"}, f)
        self.run_restore()
        self.assertEqual(self.calls("tmux", "send-keys"), [])

    # --- failures and retries -----------------------------------------------------------

    def test_a_failed_window_puts_the_entry_back_for_the_next_run(self):
        a = self.entry(1, window=1)
        self.env["STUB_FAIL_NEW_WINDOW"] = "1"
        self.run_restore()
        self.assertEqual(self.registry(), [sid(1) + ".json"])
        self.assertTrue(any("failed" in line for line in self.restore_log()))
        del self.env["STUB_FAIL_NEW_WINDOW"]
        self.run_restore()
        self.assertEqual(self.resumed(), [(a, sid(1))])
        self.assertEqual(self.registry(), [])

    def test_each_entry_moves_just_before_its_own_window(self):
        # A kill mid-loop must leave the unprocessed entries for the next run: when tab 1's
        # window opens, tab 2's entry is still in place.
        self.entry(1, window=1)
        self.entry(2, window=2)
        stub = os.path.join(self.tmp, "bin", "tmux")
        with open(stub) as f:
            text = f.read()
        with open(stub, "w") as f:
            f.write(text.replace('"tmux new-window")',
                                 '"tmux new-window")\n    ls "$REG" | tr "\\n" " " >> "$STUB_LOG.ls"'
                                 '; echo >> "$STUB_LOG.ls"'))
        self.env["REG"] = self.reg
        self.run_restore()
        with open(self.log + ".ls") as f:
            first = f.read().splitlines()[0]
        self.assertNotIn(sid(1) + ".json", first)
        self.assertIn(sid(2) + ".json", first)

    # --- modes --------------------------------------------------------------------------

    def test_list_changes_nothing(self):
        self.entry(1, window=1)
        self.entry(2, window=2, cwd=False)
        p = self.run_restore("--list")
        self.assertEqual([a for a in self.calls("tmux")
                          if a[1] in ("new-window", "send-keys", "new-session")], [])
        self.assertEqual(self.registry(), [sid(1) + ".json", sid(2) + ".json"])
        self.assertEqual(self.registry("restored"), [])
        self.assertIn(sid(1)[:8], p.stdout)
        self.assertIn("directory", p.stdout)
        self.assertEqual(self.restore_log(), [])

    def test_auto_for_another_session_does_nothing(self):
        self.entry(1, window=1)
        self.run_restore("--auto", "view-123")
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.registry(), [sid(1) + ".json"])

    def test_auto_for_main_restores(self):
        a = self.entry(1, window=1)
        self.run_restore("--auto", "main")
        self.assertEqual(self.resumed(), [(a, sid(1))])

    def test_a_manual_run_creates_main_before_reading_the_server(self):
        self.entry(1, window=1)
        del self.env["STUB_HAS_MAIN"]
        self.run_restore()
        tmux = [a[1] for a in self.calls("tmux")]
        self.assertIn(["tmux", "new-session", "-d", "-s", "main"], self.calls("tmux"))
        self.assertLess(tmux.index("new-session"), tmux.index("display"))
        self.assertLess(tmux.index("display"), tmux.index("new-window"))

    def test_a_second_run_restores_nothing(self):
        self.entry(1, window=1)
        self.run_restore()
        self.run_restore()
        self.assertEqual(len(self.calls("tmux", "send-keys")), 1)
        self.assertEqual(self.registry("restored"), [sid(1) + ".json"])

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
        self.assertEqual(self.calls("tmux", "send-keys"), [])
        self.assertEqual(self.registry(), [sid(1) + ".json"])

    def test_no_registry_is_quiet(self):
        shutil.rmtree(self.reg)
        p = self.run_restore("--auto", "main")
        self.assertEqual((p.stdout, p.stderr), ("", ""))
        self.assertEqual(self.calls("tmux", "new-window"), [])

    def test_the_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
