"""tmux/claude-saved: Star (a bookmark that outlives the tab) and Shelve (save the chat, close the
tab now) for Claude tmux tabs, the shelf menu that reopens them, and the hook side that keeps a
star on its tab across /clear (stdlib only).

The session in a pane comes from Claude's live-session files (~/.claude/sessions/*.json, an
interactive session with a live pid) and else from hooks/session-registry.sh's open-sessions
entries on the current server. A stub tmux answers the display formats the script reads and logs
each call's argv, one argument per field; os.getpid() stands in for a live claude pid."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "tmux", "claude-saved")

STUB = r"""#!/usr/bin/env bash
{ printf '%s' "$(basename "$0")"; printf '\x1f%s' "$@"; printf '\n'; } >> "$STUB_LOG"
fmt="${@: -1}"
case "$1" in
  display|display-message)
    [ "$2" = -p ] || exit 0
    if [ "$3" = -t ]; then
      case " ${STUB_GONE:-} " in *" $4 "*) exit 1 ;; esac
    fi
    case "$fmt" in
      '#{start_time} #{pid} #{pane_pid} #{socket_path}')
        echo "$STUB_START $STUB_PID $STUB_PANE_PID $STUB_SOCKET" ;;
      '#{pane_title}') printf '%s\n' "$STUB_TITLE" ;;
      '#{window_panes}') echo "${STUB_WINDOW_PANES:-1}" ;;
      '#{pane_id} #{session_id} #{client_height}') echo "$STUB_CLIENT_PANE \$1 $STUB_HEIGHT" ;;
    esac ;;
  show|show-options) printf '%s\n' "${STUB_STATE:-}" ;;
  list-clients)
    printf '%%99 $9 50 /dev/pts/1\n%s $1 %s %s\n' \
      "$STUB_CLIENT_PANE" "$STUB_HEIGHT" "$STUB_CLIENT" ;;
  list-panes) printf '%b' "${STUB_PANES:-}" ;;
  new-window) echo %101 ;;
esac
exit 0
"""

SOCKET = "/tmp/tmux-1000/default"
START = 1_791_000_000
PID = 222
CLIENT = "/dev/pts/3"
DEAD = 99_999_999   # above any pid_max: never a live process
TITLE = "✳ [repo1] Fix the parser"


def sid(n):
    return f"{n:08d}-5e55-4000-8000-000000000000"


class Saved(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        os.makedirs(stubs)
        with open(os.path.join(stubs, "tmux"), "w") as f:
            f.write(STUB)
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        self.home = os.path.join(self.tmp, "home")
        self.sessions = os.path.join(self.home, ".claude", "sessions")
        os.makedirs(self.sessions)
        self.log = os.path.join(self.tmp, "calls.log")
        self.state = os.path.join(self.tmp, "state", "dotclaude")
        self.store = os.path.join(self.state, "saved")
        self.reg = os.path.join(self.state, "open-sessions")
        os.makedirs(self.reg)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(PATH=stubs + os.pathsep + "/usr/bin:/bin", HOME=self.home,
                        STUB_LOG=self.log, XDG_STATE_HOME=os.path.join(self.tmp, "state"),
                        STUB_START=str(START), STUB_PID=str(PID), STUB_SOCKET=SOCKET,
                        STUB_TITLE=TITLE, STUB_CLIENT=CLIENT, STUB_CLIENT_PANE="%4",
                        STUB_HEIGHT="50", STUB_STATE="idle",
                        # The pane's first process: an ancestor of this test, whose own pid
                        # stands in for the claude in the pane.
                        STUB_PANE_PID=str(os.getppid()))
        self.ppid = os.getppid()
        self.n = 0

    # --- fixtures -----------------------------------------------------------------------

    def cwd(self, n):
        path = os.path.join(self.tmp, "code", f"repo{n}")
        os.makedirs(path, exist_ok=True)
        return path

    def transcript(self, n):
        path = os.path.join(self.home, ".claude", "projects", f"-code-repo{n}", f"{sid(n)}.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path

    def live(self, n, pane, pid=None, kind="interactive", tmux=None, proc_start=None):
        """Claude's own live-session file for session n in pane."""
        self.n += 1
        e = {}
        if proc_start is not None:
            e["procStart"] = proc_start
        with open(os.path.join(self.sessions, f"{self.n}.json"), "w") as f:
            json.dump(e | {"pid": os.getpid() if pid is None else pid, "sessionId": sid(n),
                       "cwd": self.cwd(n), "kind": kind, "status": "idle",
                       "tmux": f"main:@1.{pane}" if tmux is None else tmux,
                       "updatedAt": self.n}, f)

    def registered(self, n, pane, server_start=START, ended=None, ts=None):
        e = {"session_id": sid(n), "cwd": self.cwd(n), "transcript_path": "", "pane": pane,
             "window_index": 1, "socket": SOCKET, "server_start": server_start,
             "server_pid": PID, "ts": ts or time.time()}
        if ended:
            e["ended_other_at"] = ended
        with open(os.path.join(self.reg, sid(n) + ".json"), "w") as f:
            json.dump(e, f)

    def put(self, n, starred=False, shelved=False, pane="%4", age=60, title=None, cwd=None):
        os.makedirs(self.store, exist_ok=True)
        e = {"session_id": sid(n), "cwd": self.cwd(n) if cwd is None else cwd,
             "title": f"[repo{n}] chat {n}" if title is None else title,
             "transcript_path": "", "starred": starred, "shelved": shelved,
             "saved_at": time.time() - age,
             "tab": {"socket": SOCKET, "server_start": START, "server_pid": PID, "pane": pane}}
        with open(os.path.join(self.store, sid(n) + ".json"), "w") as f:
            json.dump(e, f)

    def saved(self):
        if not os.path.isdir(self.store):
            return {}
        out = {}
        for name in os.listdir(self.store):
            if name.endswith(".json") and os.path.isfile(os.path.join(self.store, name)):
                with open(os.path.join(self.store, name)) as f:
                    out[name[:-5]] = json.load(f)
        return out

    def run_saved(self, *args, stdin="", env=None):
        p = subprocess.run(["bash", SCRIPT, *args], input=stdin, capture_output=True, text=True,
                           timeout=20, env={**self.env, **(env or {})})
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def hook(self, event, n, pane="%4", **payload):
        body = {"session_id": sid(n), "hook_event_name": event, "cwd": self.cwd(n),
                "transcript_path": f"/x/{sid(n)}.jsonl", **payload}
        self.run_saved("hook", stdin=json.dumps(body),
                       env={"TMUX_PANE": pane, "CLAUDE_CODE_SESSION_ATTENDED": "1"})

    def calls(self, *prefix):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            argvs = [line.split("\x1f") for line in f.read().splitlines()]
        return [a for a in argvs if a[:len(prefix)] == list(prefix)]

    def messages(self):
        return [a[-1] for a in self.calls("tmux", "display-message")]

    def star_set(self, pane="%4"):
        return ["tmux", "set", "-w", "-t", pane, "@claude_star", "1"] in self.calls("tmux")

    def star_unset(self, pane="%4"):
        return ["tmux", "set", "-wu", "-t", pane, "@claude_star"] in self.calls("tmux")

    # --- star -----------------------------------------------------------------------------

    def test_star_finds_the_chat_from_claudes_session_file(self):
        self.live(1, "%4")
        self.live(2, "%4", pid=DEAD)          # a dead claude that once ran in the pane
        self.live(3, "%4", kind="bg")         # not a tab
        self.live(5, "%14")                   # %14 ends in 4 too: the match is on the whole id
        t = self.transcript(1)
        self.run_saved("star", "%4", CLIENT)
        e = self.saved()[sid(1)]
        self.assertEqual(list(self.saved()), [sid(1)])
        self.assertEqual((e["starred"], e["shelved"]), (True, False))
        self.assertEqual(e["title"], "[repo1] Fix the parser")
        self.assertEqual(e["cwd"], self.cwd(1))
        self.assertEqual(e["transcript_path"], t)
        self.assertEqual(e["tab"], {"socket": SOCKET, "server_start": START, "server_pid": PID,
                                    "pane": "%4"})
        self.assertTrue(self.star_set())
        self.assertEqual(self.calls("tmux", "display-message")[-1][2:4], ["-c", CLIENT])
        self.assertIn("starred", self.messages()[-1])

    def test_star_falls_back_to_the_registry(self):
        self.registered(1, "%4", ts=time.time() - 100)
        self.registered(2, "%4", ts=time.time())
        self.registered(3, "%4", ts=time.time() + 50, server_start=START - 9)  # another server
        self.registered(5, "%4", ts=time.time() + 60, ended=time.time())        # window killed
        self.transcript(2)
        self.run_saved("star", "%4", CLIENT)
        self.assertEqual(list(self.saved()), [sid(2)])
        self.assertTrue(self.saved()[sid(2)]["starred"])
        self.assertTrue(self.star_set())

    def test_a_sessions_file_counts_only_under_the_panes_process(self):
        # %4 is also a pane id on another tmux server, and a pid can be reused: a live claude
        # that doesn't run under this pane's process is not this tab's chat.
        self.live(1, "%4")
        self.registered(2, "%4")
        self.transcript(1)
        self.transcript(2)
        self.env["STUB_PANE_PID"] = str(DEAD)
        self.run_saved("star", "%4", CLIENT)
        self.assertEqual(list(self.saved()), [sid(2)])

    def test_star_with_no_session_says_so(self):
        self.live(1, "%5")
        self.run_saved("star", "%4", CLIENT)
        self.assertEqual(self.saved(), {})
        self.assertFalse(self.star_set())
        self.assertIn("no Claude session", self.messages()[-1])

    def test_star_and_shelve_need_claude_running_in_the_window(self):
        # A stale registry entry for a pane that now runs a shell must not get it killed.
        self.registered(1, "%4")
        self.transcript(1)
        self.env["STUB_STATE"] = ""
        for action in ("star", "shelve"):
            with self.subTest(action=action):
                self.run_saved(action, "%4", CLIENT)
                self.assertEqual(self.saved(), {})
                self.assertEqual(self.messages()[-1], "claude-saved: no Claude running in this tab")
        self.assertEqual(self.calls("tmux", "kill-window"), [])
        self.assertEqual(self.calls("tmux", "set"), [])
        self.assertTrue(os.path.exists(os.path.join(self.reg, sid(1) + ".json")))

    def test_star_with_no_transcript_refuses(self):
        self.live(1, "%4")
        self.run_saved("star", "%4", CLIENT)
        self.assertEqual(self.saved(), {})
        self.assertFalse(self.star_set())
        self.assertIn("no messages yet", self.messages()[-1])

    def test_a_style_in_a_title_never_reaches_tmux(self):
        self.live(1, "%4")
        self.transcript(1)
        self.env["STUB_TITLE"] = "a #[fg=red]b ##[bg=blue]c #d #[x"
        self.run_saved("star", "%4", CLIENT)
        self.assertEqual(self.messages()[-1], "claude-saved: starred: a b ##c ##d [x")
        items = self.menu(CLIENT)[10:]
        self.assertEqual(items[7], "★ a b ##c ##d [x · now")

    def test_unstar_deletes_the_entry(self):
        self.live(1, "%4")
        self.transcript(1)
        self.run_saved("star", "%4", CLIENT)
        self.run_saved("star", "%4", CLIENT)
        self.assertEqual(self.saved(), {})
        self.assertTrue(self.star_unset())

    def test_unstar_keeps_a_shelved_entry(self):
        self.live(1, "%4")
        self.put(1, starred=True, shelved=True)
        self.run_saved("star", "%4", CLIENT)
        e = self.saved()[sid(1)]
        self.assertEqual((e["starred"], e["shelved"]), (False, True))
        self.assertTrue(self.star_unset())

    # --- the hook side ------------------------------------------------------------------

    def test_clear_moves_the_star_to_the_new_session(self):
        self.live(1, "%4")
        self.transcript(1)
        self.run_saved("star", "%4", CLIENT)
        self.hook("SessionEnd", 1, reason="clear")
        self.hook("SessionStart", 2, source="clear")
        self.assertEqual(list(self.saved()), [sid(2)])
        e = self.saved()[sid(2)]
        self.assertEqual((e["session_id"], e["starred"]), (sid(2), True))
        self.assertEqual(e["transcript_path"], f"/x/{sid(2)}.jsonl")
        self.assertEqual(e["title"], "[repo1] Fix the parser")
        self.assertEqual(self.calls("tmux", "set")[-1],
                         ["tmux", "set", "-w", "-t", "%4", "@claude_star", "1"])

    def test_session_end_clear_does_nothing(self):
        # It races the SessionStart `clear` that follows: a title refresh could recreate the old
        # id after the re-key, and a ★ unset could land after the new one is set.
        self.put(1, starred=True)
        self.env["STUB_TITLE"] = "✳ [repo1] new title"
        self.hook("SessionEnd", 1, reason="clear")
        self.assertEqual(self.calls("tmux", "set"), [])
        self.assertEqual(self.saved()[sid(1)]["title"], "[repo1] chat 1")
        self.hook("SessionStart", 2, source="clear")
        self.hook("SessionEnd", 1, reason="clear")   # late: must not bring the old id back
        self.assertEqual(list(self.saved()), [sid(2)])
        self.assertEqual(self.calls("tmux", "set")[-1],
                         ["tmux", "set", "-w", "-t", "%4", "@claude_star", "1"])

    def test_clear_writes_the_new_entry_before_removing_the_old(self):
        # A failed write (here a directory in the way of the new file) must leave the old one.
        self.put(1, starred=True)
        os.makedirs(os.path.join(self.store, sid(2) + ".json"))
        self.hook("SessionStart", 2, source="clear")
        self.assertTrue(self.saved()[sid(1)]["starred"])

    def test_clear_in_another_pane_or_server_leaves_the_star(self):
        self.put(1, starred=True, pane="%4")
        self.hook("SessionStart", 2, pane="%5", source="clear")
        self.env["STUB_START"] = str(START + 5)   # same pane id on a newer server
        self.hook("SessionStart", 3, pane="%4", source="clear")
        self.assertEqual(list(self.saved()), [sid(1)])
        self.assertEqual(self.saved()[sid(1)]["tab"]["pane"], "%4")

    def test_resuming_another_chat_in_a_starred_tab_leaves_the_star_behind(self):
        self.put(1, starred=True, pane="%4")
        self.hook("SessionStart", 2, source="resume")
        self.assertEqual(list(self.saved()), [sid(1)])
        self.assertTrue(self.saved()[sid(1)]["starred"])
        self.assertTrue(self.star_unset())
        # The tab is no longer chat 1's: a /clear there later doesn't take its star.
        self.hook("SessionStart", 3, source="clear")
        self.assertEqual(list(self.saved()), [sid(1)])

    def test_a_starred_chat_starting_in_a_new_pane_takes_its_star_along(self):
        # A restore after a reboot, or an open from the shelf.
        self.put(1, starred=True, pane="%4")
        self.env["STUB_START"] = str(START + 100)
        self.hook("SessionStart", 1, pane="%9", source="resume")
        tab = self.saved()[sid(1)]["tab"]
        self.assertEqual((tab["pane"], tab["server_start"]), ("%9", START + 100))
        self.assertTrue(self.star_set("%9"))

    def test_a_shelved_chat_started_by_hand_leaves_the_shelf(self):
        self.put(1, shelved=True)
        self.hook("SessionStart", 1, pane="%9", source="resume")
        self.assertEqual(self.saved(), {})

    def test_session_end_clears_the_mark_and_refreshes_the_title(self):
        self.put(1, starred=True)
        self.env["STUB_TITLE"] = "⠐ [repo1] Ship #42"
        self.hook("SessionEnd", 1, reason="prompt_input_exit")
        self.assertTrue(self.star_unset())
        e = self.saved()[sid(1)]
        self.assertEqual((e["title"], e["starred"]), ("[repo1] Ship #42", True))

    def test_session_end_with_the_window_gone_keeps_the_title(self):
        self.put(1, starred=True)
        self.env["STUB_GONE"] = "%4"
        self.hook("SessionEnd", 1, reason="other")
        self.assertEqual(self.saved()[sid(1)]["title"], "[repo1] chat 1")

    def test_the_hook_skips_subagents_and_bad_input(self):
        self.put(1, starred=True, pane="%4")
        self.hook("SessionStart", 2, source="clear", agent_id="a1")
        for text in ("", "{not json", "[1]"):
            self.run_saved("hook", stdin=text, env={"TMUX_PANE": "%4"})
        self.assertEqual(list(self.saved()), [sid(1)])
        self.assertEqual(self.calls("tmux", "set"), [])

    # --- shelve -------------------------------------------------------------------------

    def test_shelve_saves_the_chat_and_closes_its_window(self):
        self.live(1, "%4")
        self.registered(1, "%4")
        self.transcript(1)
        self.run_saved("shelve", "%4", CLIENT)
        e = self.saved()[sid(1)]
        self.assertEqual((e["shelved"], e["starred"]), (True, False))
        self.assertFalse(os.path.exists(os.path.join(self.reg, sid(1) + ".json")))
        self.assertEqual(self.calls("tmux", "kill-window"), [["tmux", "kill-window", "-t", "%4"]])
        self.assertEqual(self.calls("tmux", "kill-pane"), [])

    def test_shelve_in_a_split_closes_only_the_pane(self):
        self.live(1, "%4")
        self.transcript(1)
        self.env["STUB_WINDOW_PANES"] = "2"
        self.put(1, starred=True)
        self.run_saved("shelve", "%4", CLIENT)
        self.assertEqual(self.calls("tmux", "kill-pane"), [["tmux", "kill-pane", "-t", "%4"]])
        self.assertEqual(self.calls("tmux", "kill-window"), [])
        # The window stays, so its ★ (this chat's) goes first.
        tail = [a[1:] for a in self.calls("tmux") if a[1] in ("set", "kill-pane")]
        self.assertEqual(tail, [["set", "-wu", "-t", "%4", "@claude_star"],
                                ["kill-pane", "-t", "%4"]])

    def test_shelve_keeps_a_star(self):
        self.live(1, "%4")
        self.transcript(1)
        self.put(1, starred=True)
        self.run_saved("shelve", "%4", CLIENT)
        e = self.saved()[sid(1)]
        self.assertEqual((e["shelved"], e["starred"]), (True, True))

    def test_shelve_while_busy_asks_first(self):
        self.live(1, "%4")
        self.registered(1, "%4")
        self.transcript(1)
        self.env["STUB_STATE"] = "busy"
        self.run_saved("shelve", "%4", CLIENT)
        self.assertEqual(self.saved(), {})
        self.assertEqual(self.calls("tmux", "kill-window"), [])
        [ask] = self.calls("tmux", "confirm-before")
        self.assertEqual(ask[2:7], ["-b", "-t", CLIENT, "-p",
                                    "Claude is working; shelve anyway? (y/n)"])
        self.assertEqual(ask[7], f"run-shell '{SCRIPT} shelve --force %4 {CLIENT}'")
        self.run_saved("shelve", "--force", "%4", CLIENT)
        self.assertTrue(self.saved()[sid(1)]["shelved"])
        self.assertEqual(len(self.calls("tmux", "kill-window")), 1)

    def test_shelve_with_no_transcript_refuses(self):
        self.live(1, "%4")
        self.registered(1, "%4")
        self.run_saved("shelve", "%4", CLIENT)
        self.assertEqual(self.saved(), {})
        self.assertEqual(self.calls("tmux", "kill-window"), [])
        self.assertTrue(os.path.exists(os.path.join(self.reg, sid(1) + ".json")))
        self.assertIn("no messages yet", self.messages()[-1])

    # --- open ---------------------------------------------------------------------------

    def opened(self):
        """The (session target, cwd, typed command) of each window opened."""
        out, new = [], None
        for a in self.calls("tmux"):
            if a[1] == "new-window":
                self.assertEqual(a[:6], ["tmux", "new-window", "-P", "-F", "#{pane_id}", "-t"])
                self.assertEqual(a[7], "-c")
                new = (a[6], a[8])
            elif a[1] == "send-keys":
                self.assertEqual(a[2:4] + a[5:], ["-t", "%101", "Enter"])
                out.append(new + (a[4],))
        return out

    def test_open_a_shelved_chat_reopens_it_and_its_start_takes_it_off(self):
        self.put(1, shelved=True)
        self.transcript(1)
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [("$1:", self.cwd(1), f"claude --resume {sid(1)}")])
        # Kept until the resume really starts: a claude that fails to start loses nothing.
        self.assertTrue(self.saved()[sid(1)]["shelved"])
        self.hook("SessionStart", 1, pane="%101", source="resume")
        self.assertEqual(self.saved(), {})

    def test_open_a_starred_chat_keeps_its_star(self):
        self.put(1, starred=True)
        self.transcript(1)
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(len(self.opened()), 1)
        self.hook("SessionStart", 1, pane="%101", source="resume")
        self.assertTrue(self.saved()[sid(1)]["starred"])
        self.assertTrue(self.star_set("%101"))

    def test_open_a_running_chat_goes_to_its_pane(self):
        self.put(1, starred=True)
        self.live(1, "%7")
        self.env["STUB_PANES"] = f"$1 @3 %7 {self.ppid}\\n$1 @1 %4 1\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertIn(["tmux", "select-window", "-t", "$1:@3"], self.calls("tmux"))
        self.assertIn(["tmux", "select-pane", "-t", "%7"], self.calls("tmux"))

    def test_open_a_chat_live_in_another_tmux_server_stops(self):
        # The file names %7, but its claude doesn't run under this server's %7: another server
        # holds the chat. Resuming it here would make a second live copy.
        self.put(1, shelved=True)
        self.transcript(1)
        self.live(1, "%7")
        self.env["STUB_PANES"] = f"$1 @3 %7 {DEAD}\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertNotIn("select-pane", [a[1] for a in self.calls("tmux")])
        self.assertIn("already running elsewhere", self.messages()[-1])

    def test_a_reused_pid_is_not_the_chat(self):
        # A sessions file left by a restart whose pid now names another process: its procStart
        # doesn't match that process's start time, so the chat isn't running and it reopens.
        self.put(1, shelved=True)
        self.transcript(1)
        self.live(1, "%7", proc_start=1)
        self.env["STUB_PANES"] = f"$1 @3 %7 {DEAD}\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(len(self.opened()), 1)

    def test_a_matching_proc_start_counts_as_live(self):
        with open(f"/proc/{os.getpid()}/stat") as f:
            start = int(f.read().rpartition(")")[2].split()[19])
        self.put(1, shelved=True)
        self.transcript(1)
        self.live(1, "%7", proc_start=start)
        self.env["STUB_PANES"] = f"$1 @3 %7 {self.ppid}\\n$1 @1 %4 1\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertIn(["tmux", "select-pane", "-t", "%7"], self.calls("tmux"))

    def test_open_a_chat_running_in_another_session_switches_the_client(self):
        self.put(1, starred=True)
        self.registered(1, "%7")
        self.env["STUB_PANES"] = f"$2 @3 %7 {self.ppid}\\n$1 @1 %4 1\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertIn(["tmux", "switch-client", "-c", CLIENT, "-t", "%7"], self.calls("tmux"))

    def test_open_a_chat_running_outside_tmux_stops(self):
        self.put(1, shelved=True)
        self.transcript(1)
        self.live(1, "", tmux="")
        self.env["STUB_PANES"] = "$1 @1 %4 1\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertIn("already running elsewhere", self.messages()[-1])
        self.assertTrue(self.saved()[sid(1)]["shelved"])

    def test_a_registry_pane_that_is_gone_is_skipped(self):
        # Its window was killed without a hook; the chat now runs outside tmux.
        self.put(1, shelved=True)
        self.transcript(1)
        self.registered(1, "%7")
        self.live(1, "", tmux="")
        self.env["STUB_PANES"] = "$1 @1 %4 1\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertIn("already running elsewhere", self.messages()[-1])

    def test_open_with_the_transcript_gone_keeps_the_entry(self):
        self.put(1, starred=True)
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertTrue(self.saved()[sid(1)]["starred"])
        self.assertIn("transcript is gone", self.messages()[-1])

    def test_open_with_a_bad_directory_keeps_the_entry(self):
        gone = os.path.join(self.tmp, "gone")
        hashed = os.path.join(self.tmp, "c#{pane_id}")
        os.makedirs(hashed)
        for n, cwd in ((1, gone), (2, hashed)):
            with self.subTest(cwd=cwd):
                self.put(n, shelved=True, cwd=cwd)
                self.transcript(n)
                self.run_saved("open", sid(n), CLIENT)
                self.assertEqual(self.opened(), [])
                self.assertTrue(self.saved()[sid(n)]["shelved"])
                self.assertIn("directory", self.messages()[-1])

    def test_an_unsafe_id_is_never_typed(self):
        self.run_saved("open", "x; rm -rf ~", CLIENT)
        self.assertEqual(self.calls("tmux", "send-keys"), [])

    # --- menu, rm, list -------------------------------------------------------------------

    def menu(self, *args):
        self.run_saved("menu", *args)
        [m] = self.calls("tmux", "display-menu")
        return m

    def test_the_menu_lists_newest_first_with_keys(self):
        self.live(9, "%4")
        self.put(1, starred=True, age=3 * 3600)
        self.put(2, shelved=True, age=5 * 60, title="[repo2] issue #12")
        self.put(3, starred=True, shelved=True, age=2 * 86400, title="")
        m = self.menu(CLIENT)
        self.assertEqual(m[2:11], ["-c", CLIENT, "-T", "#[align=centre]Shelf", "-x", "C",
                                   "-y", "C", "Star this tab"])
        items = m[10:]
        self.assertEqual(items[:7], [
            "Star this tab", "*", f"run-shell '{SCRIPT} star %4 {CLIENT}'",
            "Shelve this tab", "V", f"run-shell '{SCRIPT} shelve %4 {CLIENT}'", ""])
        self.assertEqual(items[7:16], [
            "▤ [repo2] issue ##12 · 5m", "1", f"run-shell '{SCRIPT} open {sid(2)} {CLIENT}'",
            "★ [repo1] chat 1 · 3h", "2", f"run-shell '{SCRIPT} open {sid(1)} {CLIENT}'",
            "★ repo3 · 2d", "3", f"run-shell '{SCRIPT} open {sid(3)} {CLIENT}'"])
        self.assertEqual(items[16:], ["", "Remove…", "-",
                                      f"run-shell '{SCRIPT} menu --remove {CLIENT}'"])

    def test_the_menu_offers_unstar_for_a_starred_tab(self):
        self.live(1, "%4")
        self.put(1, starred=True)
        self.assertEqual(self.menu(CLIENT)[10], "Unstar this tab")

    def test_an_empty_menu_still_offers_this_tab(self):
        self.live(1, "%4")
        items = self.menu(CLIENT)[10:]
        self.assertEqual(items[:7], [
            "Star this tab", "*", f"run-shell '{SCRIPT} star %4 {CLIENT}'",
            "Shelve this tab", "V", f"run-shell '{SCRIPT} shelve %4 {CLIENT}'", ""])
        self.assertEqual(items[7:], ["-(nothing saved)", "", ""])

    def test_the_menu_disables_this_tab_without_a_chat(self):
        self.put(1, shelved=True)
        items = self.menu(CLIENT)[10:]
        self.assertEqual(items[:7], ["-Star this tab", "", "", "-Shelve this tab", "", "", ""])

    def test_the_menu_disables_this_tab_where_claude_isnt_running(self):
        self.registered(1, "%4")   # stale: the pane runs a shell now
        self.env["STUB_STATE"] = ""
        items = self.menu(CLIENT)[10:]
        self.assertEqual(items[:7], ["-Star this tab", "", "", "-Shelve this tab", "", "", ""])

    def test_the_menu_fits_the_client(self):
        # tmux shows no menu taller than the client: 20 lines leave 17 inside the borders and
        # status line, 5 for the fixed items, 11 rows and one "+24 more".
        for n in range(1, 36):
            self.put(n, starred=True, age=n * 60)
        self.live(99, "%4")
        self.env["STUB_HEIGHT"] = "20"
        names = self.names(self.menu(CLIENT))
        rows = [n for n in names if n.startswith("★")]
        self.assertEqual(len(rows), 11)
        self.assertTrue(rows[0].startswith("★ [repo1] chat 1 "))
        more = names.index("-+24 more: claude-saved list")
        self.assertEqual(names[more - 1], rows[-1])
        self.assertEqual(names[more + 1:], ["", "Remove…"])
        self.assertLessEqual(len(names) + 3, 20)   # borders and the status line

    def names(self, m):
        """A display-menu argv's lines: each item's name, or "" for a separator (one argument,
        where an item is three)."""
        args, out, i = m[10:], [], 0
        while i < len(args):
            out.append(args[i])
            i += 1 if args[i] == "" else 3
        return out

    def test_the_remove_menu_runs_rm(self):
        self.put(1, starred=True)
        m = self.menu("--remove", CLIENT)
        self.assertEqual(m[4:6], ["-T", "#[align=centre]Remove from shelf"])
        self.assertEqual(m[10:], ["★ [repo1] chat 1 · 1m", "1",
                                  f"run-shell '{SCRIPT} rm {sid(1)} {CLIENT}'"])

    def test_rm_drops_the_entry_and_the_mark_where_it_runs(self):
        self.put(1, starred=True)
        self.live(1, "%7")
        self.env["STUB_PANES"] = f"$1 @3 %7 {self.ppid}\\n"
        self.run_saved("rm", sid(1), CLIENT)
        self.assertEqual(self.saved(), {})
        self.assertTrue(self.star_unset("%7"))

    def test_list_prints_one_line_per_chat(self):
        self.put(1, starred=True, age=10)
        self.put(2, shelved=True, age=5)
        p = self.run_saved("list")
        lines = p.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("▤ " + sid(2)[:8]))
        self.assertIn("repo2", lines[0])
        self.assertIn("[repo1] chat 1", lines[1])

    def test_nothing_is_printed_for_run_shell(self):
        self.live(1, "%4")
        self.transcript(1)
        for args in (("star", "%4", CLIENT), ("menu", CLIENT), ("shelve", "%4", CLIENT),
                     ("open", sid(1), CLIENT)):
            with self.subTest(args=args):
                p = self.run_saved(*args)
                self.assertEqual((p.stdout, p.stderr), ("", ""))

    def test_the_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))


class Wiring(unittest.TestCase):
    def test_claude_conf_calls_the_script_and_shows_the_star(self):
        with open(os.path.join(REPO, "tmux", "claude.conf")) as f:
            conf = f.read()
        call = '"$HOME/.local/bin/claude-saved '
        for action in ("star #{pane_id} #{client_name}", "shelve #{pane_id} #{client_name}",
                       "menu #{client_name}"):
            with self.subTest(action=action):
                self.assertIn("run-shell " + call + action + '"', conf)
        self.assertIn("bind -n MouseDown3Status display-menu", conf)
        self.assertIn('bind S run-shell ' + call + 'menu #{client_name}"', conf)
        formats = [line for line in conf.splitlines()
                   if "window-status-" in line and "format" in line]
        self.assertEqual(len(formats), 2)
        for line in formats:
            self.assertIn(",}}#{?@claude_star,★ ,}#{?pane_title,", line)
            self.assertIn("#{s/✳ //:pane_title}", line)


if __name__ == "__main__":
    unittest.main()
