"""tmux/claude-saved: Star (a bookmark that outlives the tab) and Shelve (save the chat, close the
tab now) for Claude tmux tabs, the shelf menu that reopens them, and the hook side that keeps a
star on its tab across /clear (stdlib only).

The session in a pane comes from Claude's live-session files (~/.claude/sessions/*.json, an
interactive session with a live pid) and else from hooks/session-registry.sh's open-sessions
entries on the current server. A saved chat keeps the `model` and `effort` its open-sessions entry
records (the flags its claude launched with), and Open resumes it with what lanelib.carried_pick
makes of them. A stub tmux answers the display formats the script reads and logs each call's argv,
one argument per field; os.getpid() stands in for a live claude pid."""
import fcntl
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

import fg_pane

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
      '#{pane_current_command}') printf '%s\n' "$STUB_COMMAND" ;;
      '#{window_panes}') echo "${STUB_WINDOW_PANES:-1}" ;;
      '#{@tab_place}x') printf '%sx\n' "${STUB_PLACE:-}" ;;
      '#{pane_id} #{session_id} #{client_height} #{client_width}')
        echo "$STUB_CLIENT_PANE \$1 $STUB_HEIGHT $STUB_WIDTH" ;;
    esac ;;
  show|show-options) printf '%s\n' "${STUB_STATE:-}" ;;
  list-clients)
    printf '%%99 $9 50 200 /dev/pts/1\n%s $1 %s %s %s\n' \
      "$STUB_CLIENT_PANE" "$STUB_HEIGHT" "$STUB_WIDTH" "$STUB_CLIENT" ;;
  list-panes) printf '%b' "${STUB_PANES:-}" ;;
  new-window) echo %101 ;;
esac
exit 0
"""

# `claude stop <job>` (Shelve in an attach tab): logs its argv like the tmux stub.
CLAUDE_STUB = r"""#!/usr/bin/env bash
{ printf 'claude'; printf '\x1f%s' "$@"; printf '\n'; } >> "$STUB_LOG"
exit "${STUB_CLAUDE_RC:-0}"
"""

SOCKET = "/tmp/tmux-1000/default"
START = 1_791_000_000
PID = 222
CLIENT = "/dev/pts/3"
DEAD = 99_999_999   # above any pid_max: never a live process
TITLE = "✳ [repo1] Fix the parser"
PICK = {"model": "sonnet", "effort": "low"}


def command(name, args=""):
    """A slash command's user entry, as Claude Code 2.1.301 writes /model and /effort."""
    return {"type": "user", "isSidechain": False, "message": {"role": "user", "content": (
        f"<command-name>{name}</command-name>\n            <command-message>{name[1:]}"
        f"</command-message>\n            <command-args>{args}</command-args>")}}


def reply(model, effort="medium"):
    """A main-chain assistant entry and what it ran with."""
    return {"type": "assistant", "isSidechain": False, "effort": effort,
            "message": {"model": model, "role": "assistant",
                        "content": [{"type": "text", "text": "ok"}]}}


def items_of(menu):
    """A display-menu argv's items: everything after -y and its value."""
    return menu[menu.index("-y") + 2:]


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
        with open(os.path.join(stubs, "claude"), "w") as f:
            f.write(CLAUDE_STUB)
        os.chmod(os.path.join(stubs, "claude"), 0o755)
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
                        STUB_HEIGHT="50", STUB_WIDTH="200", STUB_STATE="idle",
                        STUB_COMMAND="claude",
                        # The pane's first process: an ancestor of this test, whose own pid
                        # stands in for the claude in the pane.
                        STUB_PANE_PID=str(os.getppid()))
        self.ppid = os.getppid()
        self.n = 0
        self.clients = []

    # --- fixtures -----------------------------------------------------------------------

    def cwd(self, n):
        path = os.path.join(self.tmp, "code", f"repo{n}")
        os.makedirs(path, exist_ok=True)
        return path

    def transcript(self, n, history=()):
        path = os.path.join(self.home, ".claude", "projects", f"-code-repo{n}", f"{sid(n)}.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.writelines(json.dumps(h) + "\n" for h in history)
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

    def registered(self, n, pane, server_start=START, ended=None, ts=None, attach=False,
                   pick=None):
        e = {"session_id": sid(n), "cwd": self.cwd(n), "transcript_path": "", "pane": pane,
             "window_index": 1, "socket": SOCKET, "server_start": server_start,
             "server_pid": PID, "ts": ts or time.time()}  # wall clock
        if ended:
            e["ended_other_at"] = ended
        if attach:
            e |= {"attach": True, "job_id": sid(n)[:8]}
        e |= pick or {}
        with open(os.path.join(self.reg, sid(n) + ".json"), "w") as f:
            json.dump(e, f)

    def background(self, n, job=None, name=None, pid=None, proc_start=None):
        """Claude's sessions file for background session n, hosted by the daemon: no tmux
        field, a jobId (what `claude attach` takes) and a name."""
        self.n += 1
        e = {"pid": os.getpid() if pid is None else pid, "sessionId": sid(n),
             "cwd": self.cwd(n), "kind": "bg", "status": "idle",
             "jobId": sid(n)[:8] if job is None else job,
             "name": f"[repo{n}] Job number {n}" if name is None else name, "updatedAt": self.n}
        if proc_start is not None:
            e["procStart"] = proc_start
        with open(os.path.join(self.sessions, f"{self.n}.json"), "w") as f:
            json.dump(e, f)

    def client(self, *args, argv0="claude"):
        """A Claude client process under the pane's process (this test's parent), its argv
        exactly argv0 + args as /proc shows a real `claude attach <job>`: bash runs the script
        file named by args[0] from its cwd, and sleeps."""
        d = os.path.join(self.tmp, "client")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, args[0]), "w") as f:
            f.write("sleep 30\n:\n")
        p = subprocess.Popen([argv0, *args], executable="/bin/bash", cwd=d,
                             start_new_session=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        self.clients = getattr(self, "clients", []) + [p.pid]
        self.last_client = p.pid

        def stop():
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()
        self.addCleanup(stop)
        return stop

    def first_client(self):
        return self.clients[0]

    def put(self, n, starred=False, shelved=False, pane="%4", age=60, title=None, cwd=None,
            pick=None):
        os.makedirs(self.store, exist_ok=True)
        e = {"session_id": sid(n), "cwd": self.cwd(n) if cwd is None else cwd,
             "title": f"[repo{n}] chat {n}" if title is None else title,
             "transcript_path": "", "starred": starred, "shelved": shelved,
             "saved_at": time.time() - age,  # wall clock
             "tab": {"socket": SOCKET, "server_start": START, "server_pid": PID, "pane": pane},
             **(pick or {})}
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
        return ["tmux", "set", "-p", "-t", pane, "@claude_star", "1"] in self.calls("tmux")

    def star_unset(self, pane="%4"):
        return ["tmux", "set", "-pu", "-t", pane, "@claude_star"] in self.calls("tmux")
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
        now = time.time()  # wall clock
        self.registered(1, "%4", ts=now - 100)
        self.registered(2, "%4", ts=now)
        self.registered(3, "%4", ts=now + 50, server_start=START - 9)  # another server
        self.registered(5, "%4", ts=now + 60, ended=now)               # window killed
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

    # --- claude run by its versioned path ---------------------------------------------------
    # tmux names the pane `2.1.303` (argv[0]'s basename). The registry fallback takes it for
    # claude only when the pane tty's foreground process runs from a claude/versions directory:
    # a crashed claude's entry must not get a program that merely carries a version name killed.

    def versioned_pane(self, home="claude/versions"):
        """Make the pane %4 (its process: the returned pid) run a foreground job as
        <tmp>/<home>/2.1.303, which tmux names `2.1.303`."""
        argv0 = fg_pane.link(self.tmp, *home.split("/"), "2.1.303")
        pane_pid, _ = fg_pane.spawn(self, argv0)
        self.env.update(STUB_PANE_PID=str(pane_pid), STUB_COMMAND="2.1.303")
        return pane_pid

    def test_the_registry_counts_for_a_versioned_claude(self):
        self.registered(1, "%4")
        self.transcript(1)
        self.versioned_pane()
        self.run_saved("star", "%4", CLIENT)
        self.assertTrue(self.saved()[sid(1)]["starred"])
        self.assertTrue(self.star_set())
        self.run_saved("sync", "%4")
        self.assertFalse(self.star_unset())
        self.run_saved("shelve", "%4", CLIENT)
        self.assertEqual(self.calls("tmux", "kill-window"), [["tmux", "kill-window", "-t", "%4"]])

    def test_the_registry_never_counts_for_a_version_name_from_elsewhere(self):
        self.registered(1, "%4")
        self.transcript(1)
        self.versioned_pane(home="other")
        for action in ("star", "shelve"):
            with self.subTest(action=action):
                self.run_saved(action, "%4", CLIENT)
                self.assertEqual(self.saved(), {})
                self.assertIn("no Claude session", self.messages()[-1])
        self.assertEqual(self.calls("tmux", "kill-window"), [])

    def test_a_versioned_attach_client_wins_over_a_crashed_claudes_entry(self):
        # tmux names the client's pane `2.1.303` too: the registry fallback would take the
        # crashed chat for the tab's, and Shelve would close the tab and leave the background
        # chat running unseen.
        self.registered(2, "%4")
        self.transcript(2)
        self.background(1)
        self.transcript(1)
        self.client("attach", sid(1)[:8], argv0="/home/u/.local/share/claude/versions/2.1.303")
        self.env["STUB_COMMAND"] = "2.1.303"
        self.run_saved("shelve", "%4", CLIENT)
        self.assertEqual(list(self.saved()), [sid(1)])
        self.assertEqual(self.calls("claude"), [["claude", "stop", sid(1)[:8]]])

    def test_open_goes_to_a_versioned_claudes_registry_pane(self):
        self.put(1, shelved=True)
        self.transcript(1)
        self.registered(1, "%7")
        pane_pid = self.versioned_pane()
        self.env["STUB_PANES"] = f"$1 @3 %7 {pane_pid} 2.1.303\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertIn(["tmux", "select-pane", "-t", "%7"], self.calls("tmux"))

    def test_open_reopens_past_a_version_name_from_elsewhere(self):
        self.put(1, shelved=True)
        self.transcript(1)
        self.registered(1, "%7")
        pane_pid = self.versioned_pane(home="other")
        self.env["STUB_PANES"] = f"$1 @3 %7 {pane_pid} 2.1.303\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(len(self.opened()), 1)

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
        items = items_of(self.menu(CLIENT))
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
                         ["tmux", "set", "-p", "-t", "%4", "@claude_star", "1"])

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
                         ["tmux", "set", "-p", "-t", "%4", "@claude_star", "1"])

    def test_clear_writes_the_new_entry_before_removing_the_old(self):
        # A failed write (here a directory in the way of the new file) must leave the old one.
        self.put(1, starred=True)
        os.makedirs(os.path.join(self.store, sid(2) + ".json"))
        self.hook("SessionStart", 2, source="clear")
        self.assertTrue(self.saved()[sid(1)]["starred"])

    # --- the /pass carry: a respawn starts as `startup`, and pass-respawn leaves a marker ---

    def carry(self, n, pane="%4", age=5, server_start=START):
        """pass-respawn's one-shot marker for session n leaving pane."""
        d = os.path.join(self.state, "pass-carry")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, pane[1:] + ".json")
        with open(path, "w") as f:
            json.dump({"session_id": sid(n), "written_at": time.time() - age,  # wall clock
                       "tab": {"socket": SOCKET, "server_start": server_start,
                               "server_pid": PID, "pane": pane}}, f)
        return path

    def test_a_pass_carry_moves_the_star_on_startup(self):
        self.put(1, starred=True)
        marker = self.carry(1)
        self.hook("SessionStart", 2, source="startup")
        self.assertEqual(list(self.saved()), [sid(2)])
        e = self.saved()[sid(2)]
        self.assertEqual((e["starred"], e["tab"]["pane"]), (True, "%4"))
        self.assertEqual(e["transcript_path"], f"/x/{sid(2)}.jsonl")
        self.assertFalse(os.path.exists(marker))
        self.assertTrue(self.star_set())

    def test_a_stale_pass_carry_changes_nothing(self):
        self.put(1, starred=True)
        marker = self.carry(1, age=200)
        self.hook("SessionStart", 2, source="startup")
        self.assertEqual(list(self.saved()), [sid(1)])
        self.assertIsNone(self.saved()[sid(1)]["tab"])   # the plain startup rule: ★ goes
        self.assertFalse(os.path.exists(marker))

    def test_a_pass_carry_for_another_pane_or_server_changes_nothing(self):
        self.put(1, starred=True, pane="%4")
        marker = self.carry(1, pane="%4")
        self.hook("SessionStart", 2, pane="%5", source="startup")
        self.assertTrue(os.path.exists(marker))   # not this pane's
        self.assertEqual(self.saved()[sid(1)]["tab"]["pane"], "%4")
        self.carry(1, pane="%4", server_start=START + 5)   # same pane id, another server
        self.hook("SessionStart", 3, pane="%4", source="startup")
        self.assertEqual(list(self.saved()), [sid(1)])
        self.assertFalse(os.path.exists(marker))

    def test_a_pass_carry_is_consumed_once(self):
        self.put(1, starred=True)
        marker = self.carry(1)
        self.hook("SessionStart", 2, source="startup")
        self.assertFalse(os.path.exists(marker))
        self.hook("SessionStart", 3, source="startup")   # a later plain start takes the tab
        self.assertEqual(list(self.saved()), [sid(2)])
        self.assertIsNone(self.saved()[sid(2)]["tab"])

    def test_a_pass_carry_for_another_chat_changes_nothing(self):
        self.put(1, starred=True)
        marker = self.carry(7)
        self.hook("SessionStart", 2, source="startup")
        self.assertEqual(list(self.saved()), [sid(1)])
        self.assertFalse(os.path.exists(marker))

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
        self.assertEqual(self.calls("claude"), [])   # its kill ends the chat

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
        self.assertEqual(tail, [["set", "-pu", "-t", "%4", "@claude_star"],
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
        self.env["STUB_PANES"] = f"$1 @3 %7 {self.ppid} claude\\n$1 @1 %4 1 claude\\n"
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
        self.env["STUB_PANES"] = f"$1 @3 %7 {DEAD} claude\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertNotIn("select-pane", [a[1] for a in self.calls("tmux")])
        self.assertIn("already running elsewhere", self.messages()[-1])

    def test_a_reused_pid_is_not_the_chat(self):
        # A sessions file left by a restart whose pid now names another process: its procStart
        # doesn't match that process's start time, so the chat isn't running and it reopens.
        # Claude writes procStart as a digit string; an int counts the same.
        for proc_start in (1, "1"):
            with self.subTest(proc_start=proc_start):
                self.setUp()
                self.put(1, shelved=True)
                self.transcript(1)
                self.live(1, "%7", proc_start=proc_start)
                self.env["STUB_PANES"] = f"$1 @3 %7 {DEAD} claude\\n"
                self.run_saved("open", sid(1), CLIENT)
                self.assertEqual(len(self.opened()), 1)

    def test_a_matching_proc_start_counts_as_live(self):
        with open(f"/proc/{os.getpid()}/stat") as f:
            start = int(f.read().rpartition(")")[2].split()[19])
        self.put(1, shelved=True)
        self.transcript(1)
        self.live(1, "%7", proc_start=start)
        self.env["STUB_PANES"] = f"$1 @3 %7 {self.ppid} claude\\n$1 @1 %4 1 claude\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertIn(["tmux", "select-pane", "-t", "%7"], self.calls("tmux"))

    def test_open_a_chat_running_in_another_session_switches_the_client(self):
        self.put(1, starred=True)
        self.registered(1, "%7")
        self.env["STUB_PANES"] = f"$2 @3 %7 {self.ppid} claude\\n$1 @1 %4 1 claude\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertIn(["tmux", "switch-client", "-c", CLIENT, "-t", "%7"], self.calls("tmux"))

    def test_open_a_chat_running_outside_tmux_stops(self):
        self.put(1, shelved=True)
        self.transcript(1)
        self.live(1, "", tmux="")
        self.env["STUB_PANES"] = "$1 @1 %4 1 claude\\n"
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
        self.env["STUB_PANES"] = "$1 @1 %4 1 claude\\n"
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

    # --- the launch flags (docs/lanes.md, "Model and effort") ------------------------------

    def picked(self, n):
        e = self.saved()[sid(n)]
        return {k: e[k] for k in ("model", "effort") if k in e}

    def test_star_and_shelve_copy_the_flags_from_the_registry(self):
        for action in ("star", "shelve"):
            with self.subTest(action=action):
                self.setUp()
                self.live(1, "%4")
                self.registered(1, "%4", pick=PICK)
                self.transcript(1)
                self.run_saved(action, "%4", CLIENT)
                self.assertEqual(self.picked(1), PICK)

    def test_a_registry_entry_without_flags_clears_the_saved_ones(self):
        # A claude launched with none, or an entry from before the fields: no stale pick stays.
        self.live(1, "%4")
        self.registered(1, "%4")
        self.transcript(1)
        self.put(1, starred=True, pick=PICK)
        self.run_saved("shelve", "%4", CLIENT)
        self.assertEqual(self.picked(1), {})

    def test_each_start_refreshes_the_saved_flags(self):
        self.put(1, starred=True, pick=PICK)
        self.registered(1, "%4", pick={"effort": "max"})
        self.hook("SessionStart", 1, source="resume")
        self.assertEqual(self.picked(1), {"effort": "max"})
        self.registered(1, "%4")
        self.hook("SessionStart", 1, source="compact")
        self.assertEqual(self.picked(1), {})

    def test_clear_moves_the_star_with_the_new_sessions_flags(self):
        self.live(1, "%4")
        self.registered(1, "%4", pick=PICK)
        self.transcript(1)
        self.run_saved("star", "%4", CLIENT)
        self.hook("SessionEnd", 1, reason="clear")
        self.registered(2, "%4", pick={"model": "opus"})
        self.hook("SessionStart", 2, source="clear")
        self.assertEqual(list(self.saved()), [sid(2)])
        self.assertEqual(self.picked(2), {"model": "opus"})

    def test_track_keeps_the_flags_of_the_tab_it_ran_in(self):
        self.background(1)
        self.transcript(1)
        self.registered(1, "%33", ended=time.time() - 600, pick=PICK)  # wall clock
        self.client("attach", sid(1)[:8])
        self.track_panes(("%7", self.ppid, 3))
        self.run_saved("track")
        e = self.reg_entry(1)
        self.assertEqual((e["attach"], e["model"], e["effort"]), (True, "sonnet", "low"))

    def test_open_resumes_with_the_carried_flags(self):
        self.put(1, shelved=True, pick=PICK)
        self.transcript(1)
        self.put(2, shelved=True, pick=PICK)
        self.transcript(2, history=[command("/model", "opus"), reply("claude-opus-5-5", "high")])
        self.put(3, shelved=True, pick={"model": "sonnet[1m]"})
        self.transcript(3)
        for n in (1, 2, 3):
            self.run_saved("open", sid(n), CLIENT)
        self.assertEqual([c for _, _, c in self.opened()],
                         [f"claude --resume {sid(1)} --model sonnet --effort low",
                          f"claude --resume {sid(2)} --model opus --effort high",
                          f"claude --resume {sid(3)} --model sonnet\\[1m\\]"])

    def test_open_an_old_or_malformed_entry_resumes_bare(self):
        self.put(1, shelved=True)
        self.transcript(1)
        self.put(2, shelved=True, pick={"model": "a b", "effort": "extreme"})
        self.transcript(2)
        self.put(3, shelved=True, pick={"model": ["opus"], "effort": 5})
        self.transcript(3)
        for n in (1, 2, 3):
            self.run_saved("open", sid(n), CLIENT)
        self.assertEqual([c for _, _, c in self.opened()],
                         [f"claude --resume {sid(n)}" for n in (1, 2, 3)])

    def test_open_a_chat_live_in_the_background_attaches_bare(self):
        # The resume attaches to the running session, whose pick is its own.
        self.put(1, shelved=True, pick=PICK)
        self.transcript(1)
        self.background(1)
        self.env["STUB_PANES"] = "$1 @1 %4 1 claude\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [("$1:", self.cwd(1), f"claude --resume {sid(1)}")])

    def test_open_still_opens_when_lanelib_fails(self):
        # A copy of the script with no lanelib beside it, one that raises on import, and one
        # whose carried_pick raises: the chat opens bare, and a refusal still says why.
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, "tmux"))
        shutil.copy(SCRIPT, os.path.join(repo, "tmux"))
        script = os.path.join(repo, "tmux", "claude-saved")
        lib = os.path.join(repo, "skills", "lanes", "scripts", "lanelib.py")
        for n, body in enumerate((None, "raise RuntimeError('broken')\n",
                                  "def stored_pick(e):\n    return {'--model': 'x'}\n"
                                  "def carried_pick(*a, **k):\n    raise RuntimeError('broken')\n"),
                                 1):
            with self.subTest(lanelib=body):
                if body:
                    os.makedirs(os.path.dirname(lib), exist_ok=True)
                    with open(lib, "w") as f:
                        f.write(body)
                self.put(n, shelved=True, pick=PICK)
                self.transcript(n)
                for args in (("open", sid(n), CLIENT), ("open", sid(9), CLIENT)):
                    p = subprocess.run(["bash", script, *args], capture_output=True, text=True,
                                       timeout=20, env=self.env)
                    self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(self.opened()[-1][2], f"claude --resume {sid(n)}")
                self.assertIn("is not saved", self.messages()[-1])

    # --- attach tabs: a tab whose `claude attach <job>` shows a background session --------

    def proc_start(self):
        with open(f"/proc/{os.getpid()}/stat") as f:
            return int(f.read().rpartition(")")[2].split()[19])

    def test_star_finds_an_attached_background_chat(self):
        self.background(1, proc_start=str(self.proc_start()))
        t = self.transcript(1)
        self.client("attach", sid(1)[:8])
        self.run_saved("star", "%4", CLIENT)
        e = self.saved()[sid(1)]
        self.assertEqual((e["starred"], e["cwd"], e["transcript_path"]), (True, self.cwd(1), t))
        self.assertEqual(e["tab"]["pane"], "%4")
        self.assertTrue(self.star_set())

    def test_an_attach_client_names_its_chat_by_job_id(self):
        # argv[0] may be the full path the client re-execs itself under (a `claude --resume` of
        # a background chat does), or claude's versioned path.
        for argv0 in ("claude", "/home/u/.local/bin/claude",
                      "/home/u/.local/share/claude/versions/2.1.303"):
            with self.subTest(argv0=argv0):
                self.setUp()
                self.background(1)
                self.background(2)
                self.transcript(1)
                stop = self.client("attach", sid(1)[:8], argv0=argv0)
                self.run_saved("star", "%4", CLIENT)
                stop()   # the next case's client must be the only one
                self.assertEqual(list(self.saved()), [sid(1)])

    def test_a_client_that_names_no_single_live_chat_is_not_the_tabs(self):
        # A name part stays in the argv while the session gets renamed (its title follows the
        # chat), so it can come to name another session; and `claude attach` refuses a full
        # session id. Only the jobId is trusted.
        cases = {"name part": (("attach", "Job number 1"), {}),
                 "session id": (("attach", sid(1)), {}),
                 "unknown job": (("attach", "ffffffff"), {}),
                 "dead session": (("attach", sid(1)[:8]), {"pid": DEAD}),
                 "reused pid": (("attach", sid(1)[:8]), {"proc_start": "1"}),
                 "agent view": (("agents",), {})}
        for case, (args, bg) in cases.items():
            with self.subTest(case=case):
                self.setUp()
                self.background(1, **bg)
                self.background(2)
                self.transcript(1)
                stop = self.client(*args)
                self.run_saved("star", "%4", CLIENT)
                stop()
                self.assertEqual(self.saved(), {})
                self.assertIn("no Claude session found", self.messages()[-1])

    def test_a_tracked_attach_entry_is_not_the_tabs_chat_once_the_client_moved_on(self):
        # "<-" turned the client into agent view (still `claude`): only /proc says what an
        # attach tab shows, never track's entry, which lags up to a minute.
        self.background(1)
        self.transcript(1)
        self.registered(1, "%4", attach=True)
        self.put(1, shelved=True)
        self.client("agents")
        self.run_saved("star", "%4", CLIENT)
        self.assertIn("no Claude session found", self.messages()[-1])
        self.env["STUB_PANES"] = f"$1 @1 %4 {self.ppid} claude\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.calls("tmux", "select-pane"), [])
        self.assertEqual(len(self.opened()), 1)

    def test_a_stopped_attach_client_is_not_what_the_tab_shows(self):
        # A SIGSTOPped `claude attach 1` (Claude's own Ctrl+Z exits the client instead), then
        # `claude attach 2`: the pane shows 2. Two running clients showing different chats
        # leave no answer at all.
        self.background(1)
        self.background(2)
        self.transcript(1)
        self.transcript(2)
        self.client("attach", sid(1)[:8])
        os.killpg(self.last_client, signal.SIGSTOP)
        self.client("attach", sid(2)[:8])
        self.run_saved("star", "%4", CLIENT)
        self.assertEqual(list(self.saved()), [sid(2)])
        os.killpg(self.first_client(), signal.SIGCONT)
        self.run_saved("star", "%4", CLIENT)   # unstar 2 if it resolved; it must not
        self.assertTrue(self.saved()[sid(2)]["starred"])
        self.assertIn("no Claude session found", self.messages()[-1])

    def test_a_suspended_tab_session_loses_to_a_running_attach_client(self):
        # Ctrl+Z on an interactive claude (it stops), then `claude attach 2` in the same shell.
        held = subprocess.Popen(["sleep", "30"])
        self.addCleanup(held.wait)
        self.addCleanup(held.kill)
        os.kill(held.pid, signal.SIGSTOP)
        self.live(1, "%4", pid=held.pid)
        self.background(2)
        self.transcript(1)
        self.transcript(2)
        self.client("attach", sid(2)[:8])
        self.run_saved("star", "%4", CLIENT)
        self.assertEqual(list(self.saved()), [sid(2)])
        self.track_panes(("%4", self.ppid, 1))
        self.run_saved("track")
        self.assertEqual(self.reg_entry(2)["pane"], "%4")
        # Shelve would kill the suspended chat with the tab, unsaved: it refuses instead.
        self.run_saved("shelve", "%4", CLIENT)
        self.assertEqual(self.calls("tmux", "kill-window") + self.calls("claude"), [])
        self.assertFalse(self.saved()[sid(2)]["shelved"])
        self.assertIn("suspended", self.messages()[-1])

    def test_an_attach_client_outside_the_pane_is_not_the_tabs(self):
        self.background(1)
        self.transcript(1)
        self.client("attach", sid(1)[:8])
        self.env["STUB_PANE_PID"] = str(DEAD)
        self.run_saved("star", "%4", CLIENT)
        self.assertEqual(self.saved(), {})

    def test_sync_sets_the_star_of_an_attach_tab(self):
        self.background(1)
        self.put(1, starred=True)
        self.client("attach", sid(1)[:8])
        self.run_saved("sync", "%4")
        self.assertTrue(self.star_set())

    def test_shelve_an_attach_tab_stops_its_session(self):
        # Closing the tab only ends the viewer: the chat would run on, unseen, in the daemon.
        self.background(1)
        self.registered(1, "%4", attach=True)
        self.transcript(1)
        self.client("attach", sid(1)[:8])
        self.run_saved("shelve", "%4", CLIENT)
        self.assertTrue(self.saved()[sid(1)]["shelved"])
        self.assertFalse(os.path.exists(os.path.join(self.reg, sid(1) + ".json")))
        self.assertEqual(self.calls("tmux", "kill-window"), [["tmux", "kill-window", "-t", "%4"]])
        self.assertEqual(self.calls("claude"), [["claude", "stop", sid(1)[:8]]])
        # Stop first: killing a server's last window ends the server and could take this
        # run-shell, and the stop, with it.
        order = [a[:2] for a in self.calls() if a[:2] in (["claude", "stop"], ["tmux", "kill-window"])]
        self.assertEqual(order, [["claude", "stop"], ["tmux", "kill-window"]])
        self.assertEqual(self.messages()[-1], "claude-saved: shelved: [repo1] Fix the parser")

    def test_shelve_an_attach_tab_says_when_the_stop_fails(self):
        self.background(1)
        self.transcript(1)
        self.client("attach", sid(1)[:8])
        self.env["STUB_CLAUDE_RC"] = "1"
        self.run_saved("shelve", "%4", CLIENT)
        self.assertTrue(self.saved()[sid(1)]["shelved"])
        self.assertEqual(len(self.calls("tmux", "kill-window")), 1)
        self.assertIn("still runs in the background", self.messages()[-1])

    def test_shelve_a_busy_attach_tab_asks_first(self):
        self.background(1)
        self.transcript(1)
        self.client("attach", sid(1)[:8])
        self.env["STUB_STATE"] = "busy"
        self.run_saved("shelve", "%4", CLIENT)
        self.assertEqual(self.saved(), {})
        self.assertEqual(self.calls("claude"), [])
        self.assertEqual(len(self.calls("tmux", "confirm-before")), 1)

    def test_open_an_attached_chat_goes_to_its_tab(self):
        self.put(1, starred=True)
        self.background(1)
        self.client("attach", sid(1)[:8])
        self.env["STUB_PANES"] = f"$1 @3 %7 {self.ppid} claude\\n$1 @1 %4 1 claude\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(self.opened(), [])
        self.assertIn(["tmux", "select-pane", "-t", "%7"], self.calls("tmux"))

    def test_open_a_chat_live_in_the_background_attaches_and_takes_it_off_the_shelf(self):
        # `claude --resume` of a background chat becomes `claude attach <job>`, so no
        # SessionStart follows: open takes it off the shelf itself, and puts a star on its tab.
        for starred in (False, True):
            with self.subTest(starred=starred):
                self.setUp()
                self.put(1, shelved=True, starred=starred)
                self.transcript(1)
                self.background(1)
                self.env["STUB_PANES"] = "$1 @1 %4 1 claude\\n"
                self.run_saved("open", sid(1), CLIENT)
                self.assertEqual(self.opened(), [("$1:", self.cwd(1), f"claude --resume {sid(1)}")])
                if starred:
                    e = self.saved()[sid(1)]
                    self.assertFalse(e["shelved"])
                    self.assertEqual(e["tab"]["pane"], "%101")
                    self.assertTrue(self.star_set("%101"))
                else:
                    self.assertEqual(self.saved(), {})

    def test_rm_clears_the_star_of_an_attach_tab(self):
        self.put(1, starred=True)
        self.background(1)
        self.client("attach", sid(1)[:8])
        self.env["STUB_PANES"] = f"$1 @3 %7 {self.ppid} claude\\n"
        self.run_saved("rm", sid(1), CLIENT)
        self.assertTrue(self.star_unset("%7"))

    # --- track: open-sessions entries for attach tabs, for claude-restore ------------------

    def reg_entry(self, n):
        try:
            with open(os.path.join(self.reg, sid(n) + ".json")) as f:
                return json.load(f)
        except OSError:
            return None

    def track_panes(self, *rows):
        """list-panes rows as track reads them: pane, its process, window index."""
        self.env["STUB_PANES"] = "".join(
            f"{START} {PID} {pane} {pid} {index} {SOCKET}\\n" for pane, pid, index in rows)

    def test_track_records_an_attach_tab_for_restore(self):
        self.background(1)
        t = self.transcript(1)
        # The tab it ran in before.
        self.registered(1, "%33", ended=time.time() - 600)  # wall clock
        self.client("attach", sid(1)[:8])
        self.track_panes(("%4", 1, 1), ("%7", self.ppid, 3))
        self.run_saved("track")
        e = self.reg_entry(1)
        self.assertEqual({k: e[k] for k in ("session_id", "cwd", "transcript_path", "pane",
                                            "window_index", "socket", "server_start",
                                            "server_pid", "attach", "job_id")},
                         {"session_id": sid(1), "cwd": self.cwd(1), "transcript_path": t,
                          "pane": "%7", "window_index": 3, "socket": SOCKET,
                          "server_start": START, "server_pid": PID, "attach": True,
                          "job_id": sid(1)[:8]})
        self.assertNotIn("ended_other_at", e)
        self.assertAlmostEqual(e["ts"], time.time(), delta=30)  # wall clock

    def test_track_keeps_the_tabs_place(self):
        # Review round 2: track rewrites an attach tab's record whole, so it carries the
        # window's @tab_place (tmux-tab-bar's, opaque here) as session-registry.sh does: read
        # live, the old record's when tmux doesn't answer, none when empty or junk.
        self.background(1)
        self.client("attach", sid(1)[:8])
        self.track_panes(("%7", self.ppid, 3))
        place = '{"row": "c:1", "pos": 0, "after": "s", "name": "a b"}'
        self.env["STUB_PLACE"] = place
        self.run_saved("track")
        self.assertEqual(self.reg_entry(1)["place"], place)
        self.assertIn(["tmux", "display", "-p", "-t", "%7", "#{@tab_place}x"],
                      self.calls("tmux", "display"))
        self.env.update(STUB_PLACE="other", STUB_GONE="%7")
        self.run_saved("track")
        self.assertEqual(self.reg_entry(1)["place"], place)       # no answer: the old one
        del self.env["STUB_GONE"]
        for bad in ("", "x\x01y", "x" * 2049):
            with self.subTest(bad=bad):
                self.env["STUB_PLACE"] = bad
                self.run_saved("track")
                self.assertNotIn("place", self.reg_entry(1))
                self.assertIs(self.reg_entry(1)["attach"], True)

    def test_track_writes_and_sweeps_under_the_records_lock(self):
        # tmux-tab-bar compares and replaces a record's place under open-sessions/.records.lock;
        # track's write (and its sweep of a gone tab's entry) must wait for it.
        self.background(1)
        self.client("attach", sid(1)[:8])
        self.track_panes(("%7", self.ppid, 3))
        os.makedirs(self.reg, exist_ok=True)
        fd = os.open(os.path.join(self.reg, ".records.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        for want in (True, False):
            with self.subTest(written=want):
                if not want:
                    self.track_panes(("%7", 1, 3))                 # the tab moved on: swept
                fcntl.flock(fd, fcntl.LOCK_EX)
                p = subprocess.Popen(["bash", SCRIPT, "track"], stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     env=self.env)
                time.sleep(0.8)
                self.assertEqual(self.reg_entry(1) is None, want)  # waiting on the lock
                fcntl.flock(fd, fcntl.LOCK_UN)
                self.assertEqual(p.wait(timeout=10), 0)
                self.assertEqual(self.reg_entry(1) is not None, want)

    def track_waiting(self):
        """track started while this test holds the records lock: (the process, the lock fd)."""
        os.makedirs(self.reg, exist_ok=True)
        fd = os.open(os.path.join(self.reg, ".records.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        p = subprocess.Popen(["bash", SCRIPT, "track"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env)
        time.sleep(0.8)
        return p, fd

    def test_track_writes_nothing_back_after_a_shelve_it_waited_on(self):
        # Review round 3: a Shelve that lands while track waits for the lock saved the chat as
        # shelved and deleted its entry; track checks again under the lock.
        self.background(1)
        self.client("attach", sid(1)[:8])
        self.track_panes(("%7", self.ppid, 3))
        p, fd = self.track_waiting()
        self.put(1, shelved=True, age=0)                # Shelve's save; its delete found none
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(p.wait(timeout=10), 0)
        self.assertIsNone(self.reg_entry(1))

    def test_track_keeps_a_record_the_registry_rewrote_while_it_waited(self):
        # Review round 3: the sweep found a gone attach tab's entry, and while it waited for the
        # lock the registry rewrote the file as a plain tab's record (the chat resumed in one).
        self.background(1)
        self.client("attach", sid(1)[:8])
        self.track_panes(("%7", self.ppid, 3))
        self.run_saved("track")
        self.assertIs(self.reg_entry(1)["attach"], True)
        self.track_panes(("%7", 1, 3))                  # the tab moved on: swept
        p, fd = self.track_waiting()
        rec = {k: v for k, v in self.reg_entry(1).items() if k not in ("attach", "job_id")}
        with open(os.path.join(self.reg, sid(1) + ".json"), "w") as f:
            json.dump({**rec, "pane": "%9"}, f)
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(p.wait(timeout=10), 0)
        self.assertEqual(self.reg_entry(1)["pane"], "%9")

    def test_track_leaves_a_record_rewritten_while_it_waited(self):
        # Review round 4: the chat resumed in a plain tab while track waited for the lock, and
        # the registry rewrote the record for it; track's attach record must not replace it.
        self.background(1)
        self.client("attach", sid(1)[:8])
        self.track_panes(("%7", self.ppid, 3))
        p, fd = self.track_waiting()
        plain = {"session_id": sid(1), "cwd": self.cwd(1), "pane": "%9", "window_index": 5,
                 "socket": SOCKET, "server_start": START, "server_pid": PID}
        with open(os.path.join(self.reg, sid(1) + ".json"), "w") as f:
            json.dump(plain, f)
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(p.wait(timeout=10), 0)
        self.assertEqual(self.reg_entry(1), plain)

    def test_track_drops_an_attach_entry_whose_tab_moved_on(self):
        # The tab closed, or a /clear gave the job a new session id (sid 2 under job 1's id),
        # so the entry for what it showed goes. A tab's own entry and another server's stay.
        self.background(2, job=sid(1)[:8])
        self.registered(1, "%7", attach=True)
        self.registered(3, "%8", attach=True)
        self.registered(4, "%9")
        self.registered(5, "%7", attach=True, server_start=START - 9)
        self.client("attach", sid(1)[:8])
        self.track_panes(("%7", self.ppid, 3), ("%9", 1, 4))
        self.run_saved("track")
        self.assertIsNone(self.reg_entry(1))
        self.assertIsNone(self.reg_entry(3))
        self.assertEqual(self.reg_entry(2)["pane"], "%7")
        self.assertIsNotNone(self.reg_entry(4))
        self.assertIsNotNone(self.reg_entry(5))

    def test_track_skips_a_pane_running_a_tab_session_and_a_shelved_chat(self):
        # A live interactive session under the pane is what it shows (resolve agrees), and a
        # chat Shelve just closed must not come back from a track that read /proc before the
        # kill.
        self.background(1)
        self.client("attach", sid(1)[:8])
        self.live(2, "%7")
        self.track_panes(("%7", self.ppid, 3))
        self.run_saved("track")
        self.assertIsNone(self.reg_entry(1))
        os.remove(os.path.join(self.sessions, "2.json"))
        # Shelved just now, or after this track started (a saved_at past its clock).
        for age in (0, -20):
            with self.subTest(age=age):
                self.put(1, shelved=True, age=age)
                before = self.saved()
                self.run_saved("track")
                self.assertIsNone(self.reg_entry(1))
                self.assertEqual(self.saved(), before)

    def test_track_takes_a_reattached_chat_off_the_shelf(self):
        # Shelved a while ago, then attached again (its stop failed, or it was started from
        # agent view): no SessionStart reaches claude-saved, so track does that hook's work.
        for starred in (False, True):
            with self.subTest(starred=starred):
                self.setUp()
                self.background(1)
                self.put(1, shelved=True, starred=starred, pane="%9", age=60)
                stop = self.client("attach", sid(1)[:8])
                self.track_panes(("%7", self.ppid, 3))
                self.run_saved("track")
                stop()
                self.assertEqual(self.reg_entry(1)["pane"], "%7")
                if starred:
                    e = self.saved()[sid(1)]
                    self.assertFalse(e["shelved"])
                    self.assertEqual(e["tab"]["pane"], "%7")
                else:
                    self.assertEqual(self.saved(), {})

    def test_track_with_no_tmux_answer_changes_nothing(self):
        self.registered(1, "%7", attach=True)
        self.env["STUB_PANES"] = ""
        p = self.run_saved("track")
        self.assertEqual((p.stdout, p.stderr), ("", ""))
        self.assertIsNotNone(self.reg_entry(1))

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
        # Row 0 under a top bar, where tmux 3.7c can't draw a busy pane over the menu's top rows,
        # read from the client's own session ($1, not whichever grouped session tmux would
        # pick); -M, so a click on an item works in a menu no mouse event opened.
        self.assertEqual(m[2:14], ["-M", "-c", CLIENT, "-t", "$1:", "-T", "#[align=centre]Shelf",
                                   "-x", "C", "-y",
                                   "#{?#{==:#{status-position},top},0,#{popup_centre_y}}",
                                   "Star this tab"])
        items = items_of(m)
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
        self.assertEqual(items_of(self.menu(CLIENT))[0], "Unstar this tab")

    def test_an_empty_menu_still_offers_this_tab(self):
        self.live(1, "%4")
        items = items_of(self.menu(CLIENT))
        self.assertEqual(items[:7], [
            "Star this tab", "*", f"run-shell '{SCRIPT} star %4 {CLIENT}'",
            "Shelve this tab", "V", f"run-shell '{SCRIPT} shelve %4 {CLIENT}'", ""])
        self.assertEqual(items[7:], ["-(nothing saved)", "", ""])

    def test_a_saved_file_too_deep_for_json_is_skipped(self):
        self.live(1, "%4")
        os.makedirs(self.store, exist_ok=True)
        with open(os.path.join(self.store, sid(2) + ".json"), "w") as f:
            f.write("[" * 100000)  # json raises RecursionError, not ValueError
        self.assertEqual(items_of(self.menu(CLIENT))[7:], ["-(nothing saved)", "", ""])

    def test_the_menu_disables_this_tab_without_a_chat(self):
        self.put(1, shelved=True)
        items = items_of(self.menu(CLIENT))
        self.assertEqual(items[:7], ["-Star this tab", "", "", "-Shelve this tab", "", "", ""])

    def test_the_menu_disables_this_tab_where_claude_isnt_running(self):
        self.registered(1, "%4")   # stale: the pane runs a shell now
        self.env["STUB_STATE"] = ""
        items = items_of(self.menu(CLIENT))
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
        args, out, i = items_of(m), [], 0
        while i < len(args):
            out.append(args[i])
            i += 1 if args[i] == "" else 3
        return out

    def test_the_remove_menu_runs_rm(self):
        self.put(1, starred=True)
        m = self.menu("--remove", CLIENT)
        self.assertEqual(m[m.index("-T"):m.index("-T") + 2], ["-T", "#[align=centre]Remove from shelf"])
        self.assertEqual(items_of(m), ["★ [repo1] chat 1 · 1m", "1",
                                       f"run-shell '{SCRIPT} rm {sid(1)} {CLIENT}'"])

    def test_rm_drops_the_entry_and_the_mark_where_it_runs(self):
        self.put(1, starred=True)
        self.live(1, "%7")
        self.env["STUB_PANES"] = f"$1 @3 %7 {self.ppid} claude\\n"
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

    # --- round 2: stale registry entries, double opens, the per-pane star -------------------

    def test_a_stale_registry_entry_is_not_the_tabs_chat(self):
        # claude crashed in %4 (no SessionEnd) and the pane runs a shell now; a split pane's
        # claude keeps the window's @claude_state set, so only the pane's command can tell.
        self.registered(1, "%4")
        self.transcript(1)
        self.env["STUB_COMMAND"] = "zsh"
        for action in ("star", "shelve"):
            with self.subTest(action=action):
                self.run_saved(action, "%4", CLIENT)
                self.assertIn("no Claude session found", self.messages()[-1])
        self.assertEqual(self.saved(), {})
        self.assertEqual(self.calls("tmux", "kill-pane") + self.calls("tmux", "kill-window"), [])
        items = items_of(self.menu(CLIENT))
        self.assertEqual(items[:6], ["-Star this tab", "", "", "-Shelve this tab", "", ""])

    def test_open_skips_a_stale_registry_pane(self):
        # The registry says chat 1 is in %7, but %7 runs a shell, or another live chat.
        for rows, other in (("$1 @3 %7 {ppid} zsh\\n", False), ("$1 @3 %7 {ppid} claude\\n", True)):
            with self.subTest(other=other):
                self.setUp()
                self.put(1, shelved=True)
                self.transcript(1)
                self.registered(1, "%7")
                if other:
                    self.live(2, "%7")
                self.env["STUB_PANES"] = rows.format(ppid=self.ppid)
                self.run_saved("open", sid(1), CLIENT)
                self.assertEqual(self.calls("tmux", "select-pane"), [])
                self.assertEqual(len(self.opened()), 1)

    def test_rm_leaves_a_stale_registry_pane_alone(self):
        self.put(1, starred=True)
        self.registered(1, "%7")
        self.env["STUB_PANES"] = f"$1 @3 %7 {self.ppid} zsh\\n"
        self.run_saved("rm", sid(1), CLIENT)
        self.assertEqual(self.saved(), {})
        self.assertEqual(self.calls("tmux", "set"), [])

    def test_a_second_open_goes_to_the_window_the_first_made(self):
        self.put(1, shelved=True)
        self.transcript(1)
        self.run_saved("open", sid(1), CLIENT)
        opening = self.saved()[sid(1)]["opening"]
        self.assertEqual({k: opening[k] for k in ("pane", "socket", "server_start", "server_pid")},
                         {"pane": "%101", "socket": SOCKET, "server_start": START,
                          "server_pid": PID})
        # claude hasn't started yet (no sessions file, no SessionStart): %101 runs the shell.
        self.env["STUB_PANES"] = "$1 @9 %101 1 zsh\\n$1 @1 %4 1 claude\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(len(self.opened()), 1)
        self.assertIn(["tmux", "select-pane", "-t", "%101"], self.calls("tmux"))
        # Its SessionStart clears the note (and takes the chat off the shelf).
        self.put(1, starred=True)
        self.run_saved("open", sid(1), CLIENT)
        self.hook("SessionStart", 1, pane="%101", source="resume")
        self.assertNotIn("opening", self.saved()[sid(1)])

    def test_an_old_opening_note_is_ignored(self):
        self.put(1, shelved=True)
        self.transcript(1)
        self.run_saved("open", sid(1), CLIENT)
        path = os.path.join(self.store, sid(1) + ".json")
        with open(path) as f:
            e = json.load(f)
        e["opening"]["at"] -= 120   # the resume never started
        with open(path, "w") as f:
            json.dump(e, f)
        self.env["STUB_PANES"] = "$1 @9 %101 1 zsh\\n"
        self.run_saved("open", sid(1), CLIENT)
        self.assertEqual(len(self.opened()), 2)

    def test_only_a_real_exit_clears_the_star(self):
        # An in-session /resume ends the old chat (reason `resume`) just before the next one's
        # SessionStart sets the pane's ★; this end must not clear it after the fact.
        self.put(1, starred=True)
        for reason in ("resume", "other", "bypass_permissions_disabled"):
            with self.subTest(reason=reason):
                self.hook("SessionEnd", 1, reason=reason)
                self.assertEqual(self.calls("tmux", "set"), [])
        self.assertEqual(self.saved()[sid(1)]["title"], "[repo1] Fix the parser")
        self.hook("SessionEnd", 1, reason="logout")
        self.assertTrue(self.star_unset())

    def test_sync_sets_the_star_from_the_list(self):
        self.live(1, "%4")
        self.put(1, starred=True)
        self.run_saved("sync", "%4")
        self.assertTrue(self.star_set())
        self.put(1, shelved=True)
        self.run_saved("sync", "%4")
        self.assertTrue(self.star_unset())

    def test_sync_without_a_chat_clears_the_star(self):
        self.registered(1, "%4")
        self.put(1, starred=True)
        self.env["STUB_COMMAND"] = "zsh"   # the registry's claude is gone
        p = self.run_saved("sync", "%4")
        self.assertEqual((p.stdout, p.stderr), ("", ""))
        self.assertTrue(self.star_unset())

    def test_menu_titles_fit_the_client_width(self):
        self.put(1, starred=True, title="abcdefghijklmnopqrstuvwxyz")
        for width, name in (("30", "abcdefghijklm…"), ("10", "abcdefg…"),
                            ("200", "abcdefghijklmnopqrstuvwxyz")):
            with self.subTest(width=width):
                if os.path.exists(self.log):
                    os.remove(self.log)
                self.env["STUB_WIDTH"] = width
                rows = [n for n in self.names(self.menu(CLIENT)) if n.startswith("★")]
                self.assertEqual(rows, [f"★ {name} · 1m"])

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
            # Before the state glyph: Windows Terminal draws ✳ two cells wide over its space.
            self.assertIn("#I #{?@claude_star,★ ,}#{?#{==:#{@claude_state},busy}", line)
            # The ✳ prefix is stripped from the title (tmux-tab-bar's tests pin the cut that
            # runs first, so a huge title stays cheap).
            self.assertIn("#{s/✳ //:#{s/^(.{128#})", line)


if __name__ == "__main__":
    unittest.main()
