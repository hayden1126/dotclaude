"""hooks/session-registry.sh: the record of which Claude session is open in which tmux tab, kept
for tmux/claude-restore (stdlib only).

SessionStart writes $XDG_STATE_HOME/dotclaude/open-sessions/<session_id>.json for a tab
(TMUX_PANE set, ATTENDED not 0, not a subagent), naming the tmux server it runs under (socket
path and start time) so claude-restore can tell which tabs died with an earlier server.
SessionEnd deletes the entry on an explicit end (/exit, /clear, logout) and only marks it on
`other`, which a window kill, a SIGTERM and a tmux server kill all send (probed 2026-10-05), so a
shutdown can't be told from a closed window at hook time. In a tab it then hands the payload to
~/.local/bin/claude-saved, fail-open. The entry also carries the window's @tab_place (the tab
bar's placement, opaque here) as `place` when it is a valid one, and the `--model` and `--effort`
the session's claude launched with (from /proc: its nearest ancestor whose session file names it
and the session, else its nearest ancestor named claude) as `model` and `effort`, each when
present and in its shape. A stub tmux answers `display` and logs each call's argv, one argument
per field. Each hook runs under a stub claude that writes its own session file: its own parent,
nearer than any real session the test runs in, whose launch flags would otherwise leak in."""
import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "session-registry.sh")

STUB = """#!/usr/bin/env bash
{ printf '%s' "$(basename "$0")"; printf '\\x1f%s' "$@"; printf '\\n'; } >> "$STUB_LOG"
[ "$1" != -u ] || shift
case "$1 $5" in
  "display #{@tab_place}")
    [ -z "${STUB_NO_PLACE:-}" ] || exit 1
    printf '%s\\n' "${STUB_PLACE:-}" ;;
  display*)
    [ -z "${STUB_NO_SERVER:-}" ] || exit 1
    printf '%s %s %s %s\\n' "$STUB_START" "$STUB_PID" "${STUB_WINDOW:-3}" "$STUB_SOCKET" ;;
esac
exit 0
"""

SID = "0b6f2a1e-1111-4c2d-9e3f-aaaaaaaaaaaa"
NEW = "7c1d9e2f-2222-4a5b-8c6d-bbbbbbbbbbbb"
SOCKET = "/tmp/tmux-1000/my socket"   # a space: the path is the rest of the display line
START = 1791222157
PID = 4321
TAB = {"TMUX": "/tmp/tmux-1000/default,1,0", "TMUX_PANE": "%7",
       "CLAUDE_CODE_SESSION_ATTENDED": "1"}
# A tab bar placement: opaque to the hook, so spaces, quotes, # and non-ASCII pass as they are.
PLACE = '{"row": 1, "pos": 2, "k": "a b #{pane_id} \'q\' ' + chr(0xe9) + ';"}'
# A stub claude: a direct shebang keeps its comm its file name, `claude` or a version like
# `2.1.302` (an env shebang would make it bash), and it runs the hook as a child, never exec, so
# it stays the hook's ancestor. With $STUB_SESSION set it first writes its session file as Claude
# Code does by SessionStart (~/.claude/sessions/<pid>.json: pid, procStart as stat field 22 or
# $STUB_PROC_START, sessionId).
CLAUDE = r"""#!/bin/bash
if [ -n "${STUB_SESSION:-}" ]; then
  read -r stat < "/proc/$$/stat"
  fields=(${stat##*\) })
  mkdir -p "$HOME/.claude/sessions"
  printf '{"pid": %s, "procStart": "%s", "sessionId": "%s"}' "$$" \
    "${STUB_PROC_START:-${fields[19]}}" "$STUB_SESSION" > "$HOME/.claude/sessions/$$.json"
fi
"$CLAUDE_RUNS" "$@"
exit $?
"""
OUTER = '#!/bin/bash\n"%s" %s\nexit $?\n'   # a claude above the stub, which runs it
VERSIONED = os.path.join("versions", "2.1.302")   # a claude exec'd by its versioned path
LAUNCH = ["--model", "sonnet", "--effort=low", "--permission-mode", "plan", "Read STATUS.md"]


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        os.mkdir(stubs)
        with open(os.path.join(stubs, "tmux"), "w") as f:
            f.write(STUB)
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        self.log = os.path.join(self.tmp, "calls.log")
        self.dir = os.path.join(self.tmp, "state", "dotclaude", "open-sessions")
        # The test may itself run inside a Claude session in a tmux tab: start from a clean env.
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX"))}
        self.home = os.path.join(self.tmp, "home")   # never the real ~/.local/bin/claude-saved
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], STUB_LOG=self.log,
                        HOME=self.home, XDG_STATE_HOME=os.path.join(self.tmp, "state"),
                        STUB_START=str(START), STUB_PID=str(PID), STUB_SOCKET=SOCKET)
        self.claude = self.claude_stub(os.path.join("claude-bin", "claude"))
        self.hook = HOOK

    def claude_stub(self, where, body=CLAUDE):
        """A stub claude at <tmp>/<where>, which runs $CLAUDE_RUNS with its args."""
        path = os.path.join(self.tmp, where)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(body)
        os.chmod(path, 0o755)
        return path

    def outer(self, *inner_flags):
        """A claude named claude above the current stub, which runs it with inner_flags (plain
        words): fire's launch flags go to the outer one."""
        self.claude = self.claude_stub(os.path.join("outer", "claude"),
                                       OUTER % (self.claude, " ".join(inner_flags)))

    def fire(self, event, session=TAB, launch=(), stub_session=..., **payload):
        """Run the hook as `claude <launch>` would: under the stub claude, with launch as its
        flags. The stub writes its session file naming stub_session (by default the payload's
        id; None writes none)."""
        sid = payload.get("session_id", SID)
        stub_session = sid if stub_session is ... else stub_session
        body = {"session_id": SID, "hook_event_name": event, "cwd": "/home/u/code/dna",
                "transcript_path": f"/home/u/.claude/projects/dna/{sid}.jsonl", **payload}
        runs = os.path.join(self.tmp, "run-hook")
        with open(runs, "w") as f:
            f.write('#!/bin/bash\nbash "%s"\nexit $?\n' % self.hook)
        os.chmod(runs, 0o755)
        stub = {} if stub_session is None else {"STUB_SESSION": stub_session}
        p = subprocess.run([self.claude, *launch], input=json.dumps(body), capture_output=True,
                           text=True, timeout=10,
                           env={"CLAUDE_RUNS": runs, **self.env, **stub, **session})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((p.stdout, p.stderr), ("", ""))

    def start(self, session=TAB, **payload):
        self.fire("SessionStart", session, **{"source": "startup", **payload})

    def end(self, reason, **payload):
        self.fire("SessionEnd", reason=reason, **payload)

    def entries(self):
        if not os.path.isdir(self.dir):
            return {}
        out = {}
        for name in os.listdir(self.dir):
            if name.endswith(".json"):
                with open(os.path.join(self.dir, name)) as f:
                    out[name[:-5]] = json.load(f)
        return out

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [line.split("\x1f") for line in f.read().splitlines()]

    def test_a_tab_start_writes_its_entry(self):
        self.start()
        e = self.entries()[SID]
        self.assertEqual({k: e[k] for k in ("session_id", "cwd", "pane", "window_index",
                                             "socket", "server_start", "server_pid")},
                         {"session_id": SID, "cwd": "/home/u/code/dna", "pane": "%7",
                          "window_index": 3, "socket": SOCKET, "server_start": START,
                          "server_pid": PID})
        self.assertNotIn("boot_id", e)
        self.assertTrue(e["transcript_path"].endswith(SID + ".jsonl"))
        self.assertIsInstance(e["ts"], (int, float))
        self.assertNotIn("ended_other_at", e)
        self.assertNotIn("place", e)   # the window has no @tab_place
        self.assertNotIn("model", e)   # its claude launched with no flags
        self.assertNotIn("effort", e)
        self.assertEqual(self.calls(), [["tmux", "display", "-p", "-t", "%7",
                                         "#{start_time} #{pid} #{window_index} #{socket_path}"],
                                        ["tmux", "-u", "display", "-p", "-t", "%7",
                                         "#{@tab_place}"]])
        self.assertEqual(sorted(os.listdir(self.dir)),                    # no tmp left behind
                         [".records.lock", SID + ".json"])

    def test_every_source_refreshes_the_entry(self):
        self.start()
        last = self.entries()[SID]["ts"]
        for source in ("resume", "clear", "compact"):
            with self.subTest(source=source):
                time.sleep(0.01)
                self.fire("SessionStart", source=source)
                ts = self.entries()[SID]["ts"]
                self.assertGreater(ts, last)
                last = ts

    def test_a_restart_clears_an_old_end_mark(self):
        self.start()
        self.end("other")
        self.fire("SessionStart", source="resume")
        self.assertNotIn("ended_other_at", self.entries()[SID])

    def test_no_entry_outside_tmux(self):
        self.start(session={"CLAUDE_CODE_SESSION_ATTENDED": "1"})
        self.assertEqual(self.entries(), {})

    def test_no_entry_when_the_server_cannot_be_read(self):
        self.env["STUB_NO_SERVER"] = "1"
        self.start()
        self.assertEqual(self.entries(), {})

    def test_no_entry_without_a_directory(self):
        self.start(cwd="")
        self.assertEqual(self.entries(), {})

    def test_no_entry_for_a_p_run(self):
        # A `claude -p` run started from a tab inherits its TMUX_PANE.
        self.start(session={**TAB, "CLAUDE_CODE_SESSION_ATTENDED": "0"})
        self.assertEqual(self.entries(), {})

    def test_no_entry_for_a_subagent(self):
        self.start(agent_id="a1", agent_type="writer")
        self.assertEqual(self.entries(), {})

    def test_an_unsafe_session_id_writes_nothing(self):
        for sid in ("../../evil", "a b", "", "x;rm"):
            with self.subTest(sid=sid):
                self.start(session_id=sid)
        self.assertEqual(self.entries(), {})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "state", "evil.json")))

    def test_clear_replaces_the_old_id_with_the_new(self):
        self.start()
        self.end("clear")
        self.fire("SessionStart", source="clear", session_id=NEW)
        self.assertEqual(list(self.entries()), [NEW])

    def test_an_explicit_end_deletes_the_entry(self):
        for reason in ("prompt_input_exit", "logout", "clear", "something_new"):
            with self.subTest(reason=reason):
                self.start()
                self.end(reason)
                self.assertEqual(self.entries(), {})

    def test_other_marks_and_keeps_the_entry(self):
        self.start()
        self.end("other")
        e = self.entries()[SID]
        self.assertIsInstance(e["ended_other_at"], (int, float))
        self.assertEqual((e["pane"], e["server_start"]), ("%7", START))

    # --- the tab bar's placement ------------------------------------------------------------

    def test_a_start_carries_the_windows_tab_place(self):
        self.env["STUB_PLACE"] = PLACE
        self.start()
        self.assertEqual(self.entries()[SID]["place"], PLACE)

    def test_clear_carries_the_place_to_the_new_id(self):
        # The window option outlives /clear, so the new session's entry picks it up.
        self.env["STUB_PLACE"] = PLACE
        self.start()
        self.end("clear")
        self.fire("SessionStart", source="clear", session_id=NEW)
        self.assertEqual(self.entries()[NEW]["place"], PLACE)

    def test_other_keeps_the_place(self):
        self.env["STUB_PLACE"] = PLACE
        self.start()
        self.end("other")
        e = self.entries()[SID]
        self.assertEqual(e["place"], PLACE)
        self.assertIn("ended_other_at", e)

    def test_the_longest_place_is_counted_in_bytes(self):
        self.env["STUB_PLACE"] = chr(0xe9) * 1024   # 2048 bytes of UTF-8
        self.start()
        self.assertEqual(self.entries()[SID]["place"], chr(0xe9) * 1024)

    def test_an_invalid_place_is_left_out(self):
        # A trailing newline must not be stripped into a valid value, and chr(0xdcff) reaches the
        # hook as a byte that is not UTF-8.
        for place in ("", "x" * 2049, chr(0xe9) * 1024 + "x", "a\nb", "ab\n", "a\tb",
                      "a" + chr(0x1b) + "b", "a" + chr(0x7f) + "b", "a" + chr(0xdcff) + "b"):
            with self.subTest(place=place[:12]):
                self.env["STUB_PLACE"] = place
                self.start()
                e = self.entries()[SID]
                self.assertNotIn("place", e)
                self.assertEqual(e["pane"], "%7")

    def test_an_unreadable_place_still_writes_the_entry(self):
        self.env["STUB_NO_PLACE"] = "1"
        self.start()
        self.assertNotIn("place", self.entries()[SID])

    # --- the launch flags, for claude-restore and claude-saved -----------------------------

    def test_a_start_saves_the_flags_its_claude_launched_with(self):
        self.start(launch=LAUNCH)
        e = self.entries()[SID]
        self.assertEqual((e["model"], e["effort"]), ("sonnet", "low"))
        self.start(launch=["--model", "opus", "--model=claude-sonnet-5-5[1m]"])  # the last wins
        e = self.entries()[SID]
        self.assertEqual(e["model"], "claude-sonnet-5-5[1m]")
        self.assertNotIn("effort", e)

    def test_each_start_refreshes_the_flags(self):
        self.start(launch=LAUNCH)
        self.fire("SessionStart", source="resume", launch=["--effort", "max"])
        e = self.entries()[SID]
        self.assertEqual(e["effort"], "max")
        self.assertNotIn("model", e)
        self.end("clear")
        self.fire("SessionStart", source="clear", session_id=NEW, launch=LAUNCH)
        self.assertEqual({k: self.entries()[NEW][k] for k in ("model", "effort")},
                         {"model": "sonnet", "effort": "low"})

    def test_other_keeps_the_flags(self):
        self.start(launch=LAUNCH)
        self.end("other")
        e = self.entries()[SID]
        self.assertEqual((e["model"], e["effort"]), ("sonnet", "low"))
        self.assertIn("ended_other_at", e)

    def test_a_flag_outside_its_shape_is_left_out(self):
        for launch, kept in ((["--model", "a b", "--effort", "extreme"], {}),
                             (["--model=-x", "--effort", "high"], {"effort": "high"}),
                             (["--model", "opus;x", "--effort", "High"], {}),
                             (["--model"], {})):  # a flag with no value
            with self.subTest(launch=launch):
                self.start(launch=launch)
                e = self.entries()[SID]
                self.assertEqual({k: e[k] for k in ("model", "effort") if k in e}, kept)
                self.assertEqual(e["pane"], "%7")

    def flags(self):
        return {k: v for k, v in self.entries()[SID].items() if k in ("model", "effort")}

    def test_the_nearest_claude_is_the_sessions(self):
        # A session's hook sits a few processes below its claude; any claude further up (the
        # one a test runs in, say) is another session. So by its session file, and by name.
        for stub_session in (..., None):
            with self.subTest(stub_session=stub_session):
                self.claude = self.claude_stub(os.path.join("claude-bin", "claude"))
                self.outer()
                self.start(launch=LAUNCH, stub_session=stub_session)
                self.assertEqual(self.flags(), {})

    def test_a_claude_run_by_its_versioned_path_is_found_by_its_session_file(self):
        # Its comm is the version (2.1.302), so no name finds it; its session file does, which
        # exists by SessionStart (probed on 2.1.302, startup and clear alike).
        self.claude = self.claude_stub(VERSIONED)
        self.start(launch=LAUNCH)
        self.assertEqual(self.flags(), {"model": "sonnet", "effort": "low"})
        # Nearer than a claude named claude above it, launched with other flags.
        self.outer()
        self.start(launch=["--model", "opus"])
        self.assertEqual(self.flags(), {})

    def test_only_a_file_naming_this_session_and_its_process_counts(self):
        # Another session's file, a stale procStart (a reused pid's file) and no file at all pass
        # the versioned claude (launched with opus) over: the nearest claude by name answers,
        # here one with no flags.
        self.claude = self.claude_stub(VERSIONED)
        self.outer("--model", "opus")
        for stub_session, start in ((NEW, None), (SID, "1"), (None, None)):
            with self.subTest(stub_session=stub_session, start=start):
                self.env.pop("STUB_PROC_START", None)
                if start:
                    self.env["STUB_PROC_START"] = start
                self.start(stub_session=stub_session)
                self.assertEqual(self.flags(), {})

    def test_without_a_session_file_the_nearest_claude_by_name_answers(self):
        self.start(launch=LAUNCH, stub_session=None)
        self.assertEqual(self.flags(), {"model": "sonnet", "effort": "low"})

    def test_a_linked_hook_finds_lanelib_through_its_link(self):
        # Installed, the hook is a symlink in ~/.claude/hooks to the repo's hooks/.
        link = os.path.join(self.tmp, "installed", "session-registry.sh")
        os.makedirs(os.path.dirname(link))
        os.symlink(HOOK, link)
        self.hook = link
        self.start(launch=LAUNCH)
        self.assertEqual(self.entries()[SID]["model"], "sonnet")

    def test_without_lanelib_the_entry_is_still_written(self):
        # A copy of the hook with no lanelib beside it, then with one that raises on import.
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, "hooks"))
        shutil.copy(HOOK, os.path.join(repo, "hooks"))
        self.hook = os.path.join(repo, "hooks", "session-registry.sh")
        broken = os.path.join(repo, "skills", "lanes", "scripts", "lanelib.py")
        for lanelib in (None, "raise RuntimeError('broken')\n", "def ancestry(*a):\n    1 / 0\n"):
            with self.subTest(lanelib=lanelib):
                shutil.rmtree(self.dir, ignore_errors=True)   # no earlier entry to pass on
                if lanelib:
                    os.makedirs(os.path.dirname(broken), exist_ok=True)
                    with open(broken, "w") as f:
                        f.write(lanelib)
                self.start(launch=LAUNCH)
                e = self.entries()[SID]
                self.assertEqual((e["pane"], e["socket"]), ("%7", SOCKET))
                self.assertNotIn("model", e)
                self.assertNotIn("effort", e)

    # --- the records lock, shared with tmux-tab-bar's record update ---------------------------

    def hold_lock(self):
        os.makedirs(self.dir, exist_ok=True)
        fd = os.open(os.path.join(self.dir, ".records.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)

    def test_a_lock_held_past_the_bound_still_writes_and_deletes(self):
        self.hold_lock()
        t = time.monotonic()
        self.start()
        self.assertGreaterEqual(time.monotonic() - t, 1.5)      # it waited for the lock
        self.assertIn(SID, self.entries())
        self.end("other")
        self.assertIn("ended_other_at", self.entries()[SID])
        self.end("prompt_input_exit")
        self.assertEqual(self.entries(), {})

    def test_a_start_writes_under_the_lock(self):
        # tmux-tab-bar holds the lock across its compare and replace: a write must wait for it.
        self.hold_lock()
        p = subprocess.Popen(["bash", HOOK], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env={**self.env, **TAB}, text=True)
        p.stdin.write(json.dumps({"session_id": SID, "hook_event_name": "SessionStart",
                                  "cwd": "/home/u/code/dna", "source": "startup"}))
        p.stdin.close()
        time.sleep(0.8)
        self.assertNotIn(SID, self.entries())                   # waiting on the lock
        self.assertEqual(p.wait(timeout=10), 0)
        self.assertIn(SID, self.entries())

    def test_an_end_for_an_unknown_session_writes_nothing(self):
        self.end("other")
        self.assertEqual(self.entries(), {})

    def test_bad_input_still_exits_clean(self):
        for text in ("", "{not json", "[1, 2]"):
            with self.subTest(text=text):
                p = subprocess.run(["bash", HOOK], input=text, capture_output=True, text=True,
                                   timeout=10, env={**self.env, **TAB})
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual(self.entries(), {})

    # --- the hand-off to claude-saved -------------------------------------------------------

    def saved_stub(self, body="", mode=0o755):
        """A claude-saved that logs its args and stdin, then runs body."""
        path = os.path.join(self.home, ".local", "bin", "claude-saved")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write('#!/usr/bin/env bash\n'
                    '{ printf "%s\\n" "$*"; cat; printf "\\n"; } >> "$STUB_LOG.saved"\n' + body)
        os.chmod(path, mode)

    def handed(self):
        """Each hand-off as (args, payload)."""
        path = self.log + ".saved"
        if not os.path.exists(path):
            return []
        with open(path) as f:
            lines = f.read().splitlines()
        return [(lines[i], json.loads(lines[i + 1])) for i in range(0, len(lines), 2)]

    def test_a_tab_hands_each_start_and_end_to_claude_saved(self):
        self.saved_stub()
        self.start()
        self.end("clear")
        handed = self.handed()
        self.assertEqual([(args, d["hook_event_name"], d["session_id"]) for args, d in handed],
                         [("hook", "SessionStart", SID), ("hook", "SessionEnd", SID)])
        self.assertEqual(handed[1][1]["reason"], "clear")

    def test_no_hand_off_outside_a_tab_or_without_claude_saved(self):
        self.saved_stub(mode=0o644)   # linked but not executable
        self.start()
        self.saved_stub()
        self.fire("SessionEnd", session={"CLAUDE_CODE_SESSION_ATTENDED": "1"}, reason="other")
        self.start(session={**TAB, "CLAUDE_CODE_SESSION_ATTENDED": "0"})
        self.start(agent_id="a1")
        self.assertEqual(self.handed(), [])

    def test_a_failing_claude_saved_changes_nothing(self):
        self.saved_stub('echo noise; echo more >&2; exit 3\n')
        self.start()   # fire() asserts exit 0 and no output
        self.assertIn(SID, self.entries())
        self.assertEqual(len(self.handed()), 1)

    def test_a_hung_claude_saved_is_cut_off(self):
        self.saved_stub('exec sleep 30\n')
        t = time.monotonic()
        self.start()
        self.assertLess(time.monotonic() - t, 8)
        self.assertIn(SID, self.entries())


class Wiring(unittest.TestCase):
    def test_the_baseline_runs_the_hook_on_start_and_end(self):
        with open(os.path.join(REPO, "settings.json")) as f:
            hooks = json.load(f)["hooks"]

        def matchers(event):
            return [g.get("matcher") for g in hooks.get(event, [])
                    if any("session-registry.sh" in h.get("command", "")
                           for h in g.get("hooks", []))]

        start = matchers("SessionStart")
        self.assertEqual(len(start), 1)
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertTrue(start[0] is None or re.fullmatch(start[0], source) or
                                source in start[0].split("|"))
        self.assertEqual(len(matchers("SessionEnd")), 1)


if __name__ == "__main__":
    unittest.main()
