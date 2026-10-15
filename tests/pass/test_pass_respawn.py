"""skills/pass/scripts/pass-respawn: the /pass gate, the resume mode read at act time, the
detached waiter and its drops, and the inputs it trusts.

Each test runs the script in-process against a throwaway repo (tests/lanes/_fixture.py, which
points HOME and XDG_STATE_HOME into a temp dir). Fakes stand in for everything live:
  - tmux: a fake first on PATH that logs each call's argv (one argument per \\x1f field) and
    answers `display-message -p` with $FAKE_TMUX_PANE (pane pid and current command) or the
    server line; a command named in $FAKE_TMUX_FAIL exits 1.
  - the session file: load_session is wrapped so each read writes the next scripted status to
    $HOME/.claude/sessions/<pid>.json first (the last one repeats; the first is the call's own
    read), then reads it for real. When the status first turns idle (or shell), the wrapper writes
    the stop record stop-ring.sh would (self.stop_waits; None writes none). A callable in the
    script runs first and gives the status (Base.then: it appends to the transcript once).
  - /proc: proc_start is replaced, and a fake process table stands in for proc_table.
  - the transcript: a file under the fake $HOME/.claude/projects, which tests append to.
handoff-check runs for real as a subprocess. Nothing reaches the live tmux server or the real
~/.claude."""
import contextlib
import datetime
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import types
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lanes"))
from _fixture import LanesRepo  # noqa: E402

SCRIPT = os.path.join(REPO, "skills", "pass", "scripts", "pass-respawn")


def load():
    loader = SourceFileLoader("pass_respawn", SCRIPT)
    mod = module_from_spec(spec_from_loader("pass_respawn", loader))
    loader.exec_module(mod)
    return mod


_ring = SourceFileLoader("stop_ring", os.path.join(REPO, "hooks", "stop_ring.py"))
stop_ring = module_from_spec(spec_from_loader("stop_ring", _ring))
_ring.exec_module(stop_ring)

# The live watch the Artifact tool arms on a publish, as stop-ring.sh records it.
URL = "https://claude.ai/artifact/8JLmWLDftm9VdGcLQnGr76"
WATCH = {"label": "artifact watch", "id": "s31udgb0s", "url": URL,
         "description": f"live updates for artifact {URL} (auto-armed on publish)"}
DEPLOY = {"label": "monitor", "id": "b0fzd27l4", "description": "deploy events"}
AGENT = {"label": "subagent", "id": "a1b2c3d4", "description": "Write the notice hook"}

# Transcript entries around a turn's end, as Claude Code 2.1.300 writes them (lane pass-timeout's
# spike, .lane/artifacts/spike/status-and-transcript.log).
END = {"type": "system", "subtype": "turn_duration", "durationMs": 1400, "isSidechain": False}
STOP_ONLY = {"type": "system", "subtype": "stop_hook_summary", "isSidechain": False}
INTERRUPT = {"type": "user", "isSidechain": False, "message": {"role": "user", "content": [
    {"type": "text", "text": "[Request interrupted by user for tool use]"}]}}
STARTS = {  # what starts a turn after the end
    "a dequeued notice": {"type": "queue-operation", "operation": "dequeue"},
    "a task notice": {"type": "user", "isSidechain": False, "origin": {"kind": "task-notification"},
                      "message": {"role": "user", "content": "<task-notification>done"}},
    "an agent's message": {"type": "user", "isSidechain": False, "isMeta": True,
                           "origin": {"kind": "peer"},
                           "message": {"role": "user", "content": "Another session sent this"}},
    "an assistant entry": {"type": "assistant", "isSidechain": False,
                           "message": {"content": [{"type": "text", "text": "ok"}]}},
}
AFTER_END = (  # the bookkeeping that follows a turn's end, none of it a new turn
    {"type": "last-prompt", "lastPrompt": "x"}, {"type": "ai-title", "aiTitle": "Chart work"},
    {"type": "mode", "mode": "normal"}, {"type": "permission-mode", "permissionMode": "default"},
    {"type": "atis-latch"}, {"type": "file-history-snapshot"}, {"type": "api-request"},
    {"type": "attachment", "attachment": {"type": "hook_success"}},
    {"type": "system", "subtype": "away_summary"}, {"type": "file-history-delta"},
    {"type": "queue-operation", "operation": "remove"}, {"type": "cost-state"},
    {"type": "user", "isSidechain": False, "message": {"content": "Stop hook feedback:\nx"}})


def hms(when):
    """Epoch seconds as a notice's UTC clock time."""
    return datetime.datetime.fromtimestamp(when, datetime.timezone.utc).strftime("%H:%M:%S")


FAKE_TMUX = r"""#!/bin/sh
{ printf 'tmux'; for a in "$@"; do printf '\037%s' "$a"; done; printf '\n'; } >> "$FAKE_TMUX_LOG"
printf '%s\n' "$PATH" >> "$FAKE_TMUX_LOG.path"
for f in $FAKE_TMUX_FAIL; do
  if [ "$1" = "$f" ]; then echo "can't find pane: %4" >&2; exit 1; fi
done
case "$1" in
  display-message)
    if [ "$2" = -p ]; then
      case "$5" in
        *pane_in_mode*) printf '%s\n' "$FAKE_TMUX_MODE" ;;
        *pane_pid*) printf '%s\n' "$FAKE_TMUX_PANE" ;;
        *session_id*) printf '%s\n' "$FAKE_TMUX_WHERE" ;;
        *) printf '%s\n' "$FAKE_TMUX_SERVER" ;;
      esac
    fi ;;
  capture-pane) printf '%s\n' "$FAKE_TMUX_SCREEN" ;;
  list-clients) [ -n "$FAKE_TMUX_CLIENTS" ] && printf '%s\n' "$FAKE_TMUX_CLIENTS" ;;
esac
exit 0
"""

# The toast: a fake powershell.exe logs its argv like the fake tmux and exits $FAKE_TOAST_EXIT;
# a fake wslpath answers one Windows path. Both sit first on PATH, and Base drops every /mnt/
# entry from PATH, so the real powershell.exe never runs.
FAKE_POWERSHELL = r"""#!/bin/sh
{ printf 'powershell.exe'; for a in "$@"; do printf '\037%s' "$a"; done; printf '\n'; } \
  >> "$FAKE_TOAST_LOG"
exit "${FAKE_TOAST_EXIT:-0}"
"""
FAKE_WSLPATH = r"""#!/bin/sh
[ "$1" = -w ] || exit 1
printf '%s\n' 'C:\fake\notify-toast.ps1'
"""
WINPATH = r"C:\fake\notify-toast.ps1"
WHERE = "$2 3 [repo] chart work"  # the pane's session id, window index and window name
CLIENTS = "/dev/pts/7\n/dev/pts/9"  # the clients attached to that session

TODAY = datetime.date.today()
GOOD = """# STATUS: chart work

## Direction
- Ship the chart fix.

## Notes for next session
- Run the chart tests, then open the PR for #42.
"""
FIRST = "- Run the chart tests, then open the PR for #42."


def marked(text, day=TODAY):
    """text with an approval marker dated day on the Next block's first item."""
    return text.replace(FIRST, f"{FIRST[:-1]} (approved by Hayden {day}).")


APPROVED = marked(GOOD)
SID = "sess-0001"
CLAUDE, PANE_SHELL, SHELL = 900000, 899999, 900001
START = 4242
SERVER = "1791000000 222 /tmp/tmux-1000/default"
ESC, PROMPT_MARK, NBSP = chr(27), chr(0x276F), chr(0xA0)
RULE = chr(0x2500) * 20


def screen(box):
    """A captured pane (tmux capture-pane -e -p): a reply, the input box line holding box after
    the prompt mark and its no-break space, then the status bar rows."""
    return "\n".join(["Done: the handoff is committed.", "",
                      f"{ESC}[39m{PROMPT_MARK}{NBSP} {box}", f"{ESC}[2m{RULE}{ESC}[0m",
                      "  Opus 5.5 | ctx 41%"])


EMPTY_BOX = screen("")


def table(*extra, claude=True):
    """A process table: this test process under a zsh under the session's claude, which runs
    under the pane's shell and runs its MCP servers, plus extra (pid, comm, ppid) rows."""
    t = {os.getpid(): ("python3", SHELL), SHELL: ("zsh", CLAUDE), CLAUDE: ("claude", PANE_SHELL),
         PANE_SHELL: ("zsh", 1), 900002: ("npm", CLAUDE), 900003: ("socat", CLAUDE),
         900005: ("node", 900002)}
    if not claude:
        del t[CLAUDE]
        t[SHELL] = ("zsh", PANE_SHELL)
    for pid, comm, ppid in extra:
        t[pid] = (comm, ppid)
    return t


def typed(text):
    return {"type": "user", "origin": {"kind": "human"},
            "message": {"role": "user", "content": text}}


class Base(LanesRepo):
    init_lanes = False

    def setUp(self):
        super().setUp()
        self.mod = load()
        self.mod.POLL, self.mod.SETTLE, self.mod.COMPACT_GAP = 0.01, 0.05, 0.01
        self.real_roots = self.mod.writable_roots
        self.mod.writable_roots = (lambda repo, cwd, launch=None, session_argv=None:
                                   [repo.toplevel, repo.main] if repo else [])
        self.tmux = os.path.join(self.fake_bin, "tmux")
        with open(self.tmux, "w") as f:
            f.write(FAKE_TMUX)
        os.chmod(self.tmux, 0o755)
        for name, body in (("powershell.exe", FAKE_POWERSHELL), ("wslpath", FAKE_WSLPATH)):
            with open(os.path.join(self.fake_bin, name), "w") as f:
                f.write(body)
            os.chmod(os.path.join(self.fake_bin, name), 0o755)
        self.write(os.path.join(self.home, ".claude", "notify-toast.ps1"), "# the toast\n")
        self.claude = os.path.join(self.fake_bin, "claude")
        self.tmux_log = os.path.join(self.tmp, "tmux.log")
        self.toast_log = os.path.join(self.tmp, "toast.log")
        self.env["PATH"] = os.pathsep.join(e for e in self.env["PATH"].split(os.pathsep)
                                           if not e.startswith("/mnt/"))
        self.env.update(TMUX_PANE="%4", CLAUDE_CODE_SESSION_ID=SID, FAKE_TMUX_LOG=self.tmux_log,
                        FAKE_TMUX_SERVER=SERVER, FAKE_TMUX_PANE=f"{PANE_SHELL} claude",
                        FAKE_TMUX_FAIL="", FAKE_TMUX_MODE="0", FAKE_TMUX_SCREEN=EMPTY_BOX,
                        FAKE_TMUX_WHERE=WHERE, FAKE_TMUX_CLIENTS=CLIENTS,
                        FAKE_TOAST_LOG=self.toast_log, FAKE_TOAST_EXIT="0")
        patch = mock.patch.dict(os.environ, self.env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.state = os.path.join(self.tmp, "state", "dotclaude")
        self.sessions = os.path.join(self.home, ".claude", "sessions")
        self.started = time.time() - 60
        self.session_cwd = self.main
        self.script = ["busy", "idle"]
        self.stop_waits = []
        self.stop_tasks = None  # every task label; None means the waits
        # The stop record's `replies` (hooks/stop_ring.py); None writes no key.
        self.stop_replies = [{"prompt_id": "p1", "text": "Done: the handoff is committed.",
                              "time": time.time()}]
        self.start_now = START
        self.status, self.updated, self.stopped = None, 0, False
        real_start = self.mod.proc_start
        self.mod.proc_start = lambda pid: self.start_now if pid == CLAUDE else real_start(pid)
        self.real_load = self.mod.load_session
        self.mod.load_session = self.fake_load
        # then()'s entries wait here for a scan that doesn't follow their own read (landed_scan).
        self.pending, self.reads, self.scanned = [], 0, 0
        self.real_scan = self.mod.scan_turns
        self.mod.scan_turns = self.landed_scan
        self.write_session({"status": "busy"})
        self.say(typed("the prompt that ran /pass"))

    # --- fakes ---------------------------------------------------------------------------

    def session_record(self, entry):
        status = entry.get("status")
        if status != self.status:
            self.status, self.updated = status, int(time.time() * 1000) + 1
            if status in ("idle", "shell") and self.stop_waits is not None and not self.stopped:
                self.write_stop(self.stop_waits)
                self.stopped = True
        return {"sessionId": SID, "pid": CLAUDE, "procStart": START, "status": status,
                "statusUpdatedAt": self.updated, "startedAt": int(self.started * 1000),
                "cwd": self.session_cwd, "tmux": "main:@3.%4",
                **{k: v for k, v in entry.items() if k != "status"}}

    def write_session(self, entry):
        path = os.path.join(self.sessions, f"{CLAUDE}.json")
        if entry is None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
        else:
            self.write(path, json.dumps(self.session_record(entry)))

    def fake_load(self, pid):
        self.reads += 1
        entry = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if callable(entry):
            entry = entry()
        self.write_session({"status": entry} if isinstance(entry, str) else entry)
        return self.real_load(pid)

    def then(self, status, *entries, stop=None):
        """A scripted read whose status comes at once and whose transcript entries land a beat
        later (once, however often the script repeats it), as the spike's poller saw: the
        session file changes 0.1 to 0.4 s before turn_duration's bytes can be read. The entries
        land at the next scan that doesn't directly follow this read (landed_scan): the settle's
        fresh scan, or the next poll's. Given stop, the stop record (the Stop hook ran before
        the turn's end) is written at once."""
        done = []

        def read():
            if not done:
                done.append(True)
                self.pending.append((self.reads, entries))
                if stop is not None:
                    self.write_stop(stop)
            return status
        return read

    def landed_scan(self, plan):
        """scan_turns, once then()'s entries have landed: every read's but the latest's when
        this scan is the one right after that read (observe's own)."""
        first = self.scanned != self.reads
        self.scanned = self.reads
        due = [e for n, e in self.pending if not (first and n == self.reads)]
        self.pending = [(n, e) for n, e in self.pending if first and n == self.reads]
        for entries in due:
            self.say(*entries)
        return self.real_scan(plan)

    def lagged(self, status, *entries, after=0.2):
        """A scripted read whose status comes at once and whose transcript entries land `after`
        secs later (once), as a new turn's user entry trails the session file's busy (the spike,
        20:17:40: about 150 ms)."""
        timers = []

        def read():
            if not timers:
                timer = threading.Timer(after, self.say, entries)
                timers.append(timer)
                timer.start()
                self.addCleanup(timer.join)
                self.addCleanup(timer.cancel)   # cleanups run last first: cancel, then join
            return status
        return read

    def reset(self, *script):
        """A fresh turn for another call in the same test: a new script, no stop yet."""
        self.script = list(script) or ["busy", "idle"]
        self.status, self.stopped = None, False
        for path in (self.tmux_log, self.toast_log):
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)

    def write_stop(self, waits, at=None):
        tasks = waits if self.stop_tasks is None else self.stop_tasks
        rec = {"session_id": SID, "time": at or time.time(), "waits": waits, "tasks": tasks}
        if self.stop_replies is not None:
            rec["replies"] = self.stop_replies
        self.write(os.path.join(self.state, "stops", f"{SID}.json"), json.dumps(rec))

    def transcript(self):
        return os.path.join(self.home, ".claude", "projects",
                            re.sub(r"[^A-Za-z0-9]", "-", self.session_cwd), f"{SID}.jsonl")

    def say(self, *entries):
        os.makedirs(os.path.dirname(self.transcript()), exist_ok=True)
        with open(self.transcript(), "a") as f:
            for e in entries:
                f.write((e if isinstance(e, str) else json.dumps(e)) + "\n")

    def raw(self, text):
        """Append text to the transcript as is: no newline, so a line can be left torn."""
        with open(self.transcript(), "a") as f:
            f.write(text)

    def notice_file(self, sid=SID):
        return os.path.join(self.state, "pass-notice", f"{sid}.json")

    def notice(self):
        with open(self.notice_file(), encoding="utf-8") as f:
            return json.load(f)

    # --- running and reading -------------------------------------------------------------

    def run_pass(self, *args, procs=None, cwd=None):
        out = io.StringIO()
        argv = [*args, "-C", cwd or self.main]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.mod.main(argv, procs=procs or table)
        return code, out.getvalue()

    def plan(self, *args, cwd=None):
        return self.mod.prepare(self.mod.parse([*args, "--foreground", "-C", cwd or self.main]),
                                table)

    def calls(self, *prefix):
        if not os.path.exists(self.tmux_log):
            return []
        with open(self.tmux_log) as f:
            argvs = [line.split("\x1f") for line in f.read().splitlines()]
        return [a for a in argvs if a[:len(prefix)] == list(prefix)]

    def log(self):
        path = os.path.join(self.state, "pass.log")
        if not os.path.exists(path):
            return ""
        with open(path) as f:
            return f.read()

    def carry_marker(self):
        return os.path.join(self.state, "pass-carry", "4.json")

    def last_reply(self):
        return os.path.join(self.state, "pass-last", "4.json")

    def old_last_reply(self):
        """A pass-last file from an earlier pass in this pane."""
        self.write(self.last_reply(), json.dumps({"tab": {}, "from_session": "older",
                                                  "written_at": 1, "message": "old",
                                                  "shown": True}))

    def notices(self):
        """The status-line messages shown (display-message without -p)."""
        return [a for a in self.calls("tmux", "display-message") if a[2] != "-p"]

    def toasts(self, want=1, tries=60):
        """The toasts sent: each fake powershell.exe call's argv. The toast is detached, so wait
        up to tries * 0.05 s (3 s) for want of them."""
        argvs = []
        for _ in range(tries):
            if os.path.exists(self.toast_log):
                with open(self.toast_log) as f:
                    done = f.read().rpartition("\n")[0]  # a line still being written waits
                argvs = [line.split("\x1f") for line in done.splitlines()]
                if len(argvs) >= want:
                    return argvs
            time.sleep(0.05)
        return argvs

    def assertLoud(self, words, toast=True):
        """One held message per client of the pane's session (-d 0 -c <client> -t %4) holding
        words and naming the tab, and, with toast, one toast holding them too."""
        msgs = self.notices()
        self.assertEqual([m[:7] for m in msgs],
                         [["tmux", "display-message", "-d", "0", "-c", c, "-t"]
                          for c in CLIENTS.split("\n")])
        for m in msgs:
            self.assertEqual(m[7], "%4")
            self.assertIn(words, m[-1])
            self.assertIn(" in tab 3: ", m[-1])
        if toast:
            (argv,) = self.toasts()
            self.assertEqual(argv[1:6], ["-ExecutionPolicy", "Bypass", "-File", WINPATH,
                                         "-Message"])
            # The toast names the window too: no status bar beside it says which tab.
            self.assertIn(words.replace(" in tab 3: ", " in tab 3 ([repo] chart work): "),
                          argv[6])
            self.assertIn(" in tab 3 ([repo] chart work): ", argv[6])

    def assertDropped(self, outcome, words):
        self.assertEqual(self.calls("tmux", "respawn-pane"), [])
        self.assertEqual(self.calls("tmux", "send-keys"), [])
        if outcome in self.mod.QUIET:
            # Hayden caused it: the brief line, no held notice, no toast (a short look here;
            # LoudNotice waits the full 3 s for each quiet outcome).
            (msg,) = self.notices()
            self.assertEqual(msg[:4], ["tmux", "display-message", "-t", "%4"])
            self.assertIn(words, msg[-1])
            self.assertEqual(self.toasts(tries=4), [])
        else:
            self.assertLoud(words)
        self.assertIn(f"outcome={outcome}", self.log())

    def assertNoTypedPath(self, argvs):
        for argv in argvs:
            for arg in argv:
                self.assertNotIn("$(", arg)
                self.assertNotIn("\n", arg)


class Plain(Base):
    def setUp(self):
        super().setUp()
        self.commit("STATUS.md", GOOD, msg="Handoff")

    PROMPT = "Read STATUS.md (and PLAN.md if present), then plan the next step."
    GO = "Read STATUS.md (and PLAN.md if present), then continue with the approved next step."

    def respawn(self, *mode, prompt=None):
        return [self.tmux, "respawn-pane", "-k", "-t", "%4", "-c", self.main, "--",
                self.claude, *mode, prompt or self.PROMPT]

    # --- the resume mode ---------------------------------------------------------------

    def test_unapproved_resumes_in_plan_mode(self):
        code, out = self.run_pass("--print")
        self.assertEqual(code, 0, out)
        self.assertIn("mode: plain (plan)", out)
        self.assertIn(shlex.join(self.respawn("--permission-mode", "plan")), out.splitlines())
        self.assertEqual(self.calls("tmux", "respawn-pane"), [])
        self.assertFalse(os.path.exists(self.carry_marker()))

    def test_approved_resumes_in_the_default_mode(self):
        self.commit("STATUS.md", APPROVED, msg="Handoff")
        code, out = self.run_pass("--print")
        self.assertEqual(code, 0, out)
        self.assertIn("mode: plain (default)", out)
        self.assertIn(shlex.join(self.respawn(prompt=self.GO)), out.splitlines())

    def test_a_marker_on_the_second_item_resumes_in_plan_mode(self):
        self.commit("STATUS.md", GOOD + f"- Then merge it (approved by Hayden {TODAY}).\n",
                    msg="Handoff")
        code, out = self.run_pass("--print")
        self.assertEqual(code, 0, out)
        self.assertIn("mode: plain (plan)", out)

    def test_a_stale_dated_marker_refuses_and_reads_as_unapproved(self):
        self.commit("STATUS.md", marked(GOOD, TODAY - datetime.timedelta(days=1)), msg="Handoff")
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn("approval marker predates this session", out)
        # Past the gate (which fails it) the waiter's own read still says unapproved.
        self.commit("STATUS.md", APPROVED, msg="Handoff")
        plan = self.plan()
        later = {"startedAt": int((time.time() + 2 * 86400) * 1000)}
        self.assertFalse(self.mod.approved_now(plan, later))
        self.assertTrue(self.mod.approved_now(plan, {"startedAt": int(self.started * 1000)}))
        self.assertFalse(self.mod.approved_now(plan, {}))

    def test_the_mode_is_read_at_act_time(self):
        # The approval is gone by the time the turn ends: plan mode, though it was approved at
        # the call. STATUS.md names itself, so the uncommitted edit passes the gate.
        note = "- STATUS.md edits after the handoff stay uncommitted.\n"
        self.commit("STATUS.md", APPROVED + note, msg="Handoff")
        plan = self.plan()
        self.write(os.path.join(self.main, "STATUS.md"), GOOD + note)
        self.assertEqual(self.mod.wait_and_act(plan, table), "respawn")
        (respawn,) = self.calls("tmux", "respawn-pane")
        self.assertEqual(respawn[1:], self.respawn("--permission-mode", "plan")[1:])

    def test_an_approved_waiter_respawns_in_the_default_mode(self):
        self.commit("STATUS.md", APPROVED, msg="Handoff")
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        (respawn,) = self.calls("tmux", "respawn-pane")
        self.assertEqual(respawn[1:], self.respawn(prompt=self.GO)[1:])

    def test_a_malformed_marker_fails_the_gate(self):
        self.commit("STATUS.md", GOOD + "- Then merge it (approved by Hayden).\n", msg="Handoff")
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn("malformed approval marker", out)
        self.assertIn("outcome=refused", self.log())

    def test_compact_types_the_focus_then_the_prompt(self):
        code, out = self.run_pass("--compact", "--print")
        self.assertEqual(code, 0, out)
        self.assertIn("mode: compact (plan)", out)
        lines = out.splitlines()
        focus = self.mod.compact_focus("STATUS.md")
        self.assertIn("STATUS.md holds the exact facts", focus)
        for argv in (["send-keys", "-t", "%4", "-l", f"/compact {focus}"],
                     ["send-keys", "-t", "%4", "Enter"],
                     ["send-keys", "-t", "%4", "-l", self.PROMPT + " Call EnterPlanMode first."]):
            self.assertIn(shlex.join([self.tmux, *argv]), lines)

    def test_approved_compact_skips_plan_mode(self):
        self.commit("STATUS.md", APPROVED, msg="Handoff")
        code, out = self.run_pass("--compact", "--print")
        self.assertEqual(code, 0, out)
        self.assertIn("mode: compact (default)", out)
        self.assertNotIn("EnterPlanMode", out)
        self.assertIn("then continue with the approved next step.", out)

    # --- refusals at call time -----------------------------------------------------------

    def test_no_tmux_pane_prints_the_manual_line(self):
        del os.environ["TMUX_PANE"]
        code, out = self.run_pass()
        self.assertEqual(code, 2, out)
        self.assertIn(f"/clear, then: {self.PROMPT}", out)
        self.assertEqual(self.calls("tmux"), [])

    def test_compact_without_a_tmux_pane_prints_the_manual_compact(self):
        del os.environ["TMUX_PANE"]
        code, out = self.run_pass("--compact")
        self.assertEqual(code, 2, out)
        self.assertIn(f"/compact {self.mod.compact_focus('STATUS.md')}, then: {self.PROMPT}", out)
        self.assertEqual(self.calls("tmux"), [])
        self.assertIn("mode=compact outcome=refused no tmux pane", self.log())

    def test_a_failing_handoff_check_refuses(self):
        self.write(os.path.join(self.main, "scratch.txt"), "x")
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL", out)
        self.assertIn("scratch.txt", out)
        self.assertEqual(self.calls("tmux"), [])
        self.assertIn("outcome=refused", self.log())

    def test_both_modes_refuse_when_the_sessions_claude_is_not_found(self):
        for mode in ((), ("--compact",)):
            code, out = self.run_pass(*mode, "--print", procs=lambda: table(claude=False))
            self.assertEqual(code, 1, out)
            self.assertIn("can't find this session's claude", out)

    def test_a_session_file_that_does_not_match_refuses(self):
        for entry, words in (({"status": "busy", "sessionId": "other"}, "session id"),
                             ({"status": "busy", "tmux": "main:@3.%9"}, "pane"),
                             (None, "no session file")):
            with self.subTest(words=words):
                self.script = [entry]
                code, out = self.run_pass("--print")
                self.assertEqual(code, 1, out)
                self.assertIn(words, out)
        self.script = ["busy"]
        self.start_now = START + 1  # the pid was reused
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn("procStart", out)

    def test_no_session_id_refuses(self):
        del os.environ["CLAUDE_CODE_SESSION_ID"]
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn("CLAUDE_CODE_SESSION_ID", out)

    def test_a_path_entry_in_a_sandbox_writable_dir_is_skipped(self):
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: [self.fake_bin]
        code, out = self.run_pass("--print")
        self.assertNotIn(self.fake_bin, out)

    def test_a_claude_or_git_linked_into_a_sandbox_writable_dir_is_refused(self):
        wbin, safe = os.path.join(self.tmp, "wbin"), os.path.join(self.tmp, "safe")
        os.makedirs(wbin)
        os.makedirs(safe)
        shutil.move(self.claude, os.path.join(wbin, "claude"))
        os.symlink(os.path.join(wbin, "claude"), os.path.join(safe, "claude"))
        os.environ["PATH"] = safe + os.pathsep + os.environ["PATH"]
        self.mod.writable_roots = lambda repo, cwd, launch=None, session_argv=None: [wbin]
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn(f"claude resolves to {wbin}/claude", out)
        os.symlink(shutil.which("git"), os.path.join(wbin, "git"))
        os.symlink(os.path.join(wbin, "git"), os.path.join(safe, "git"))
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn(f"git resolves to {wbin}/git", out)

    def test_claude_missing_from_path_is_refused(self):
        os.remove(self.claude)
        os.environ["PATH"] = os.pathsep.join([self.fake_bin, os.path.dirname(shutil.which("git"))])
        if shutil.which("claude"):
            self.skipTest("a claude sits beside git on this machine")
        code, out = self.run_pass("--print")
        self.assertEqual(code, 1, out)
        self.assertIn("claude is not on PATH", out)

    def test_the_timeout_must_be_finite_positive_and_at_most_an_hour(self):
        for bad in ("inf", "nan", "0", "-1", "3601", "soon"):
            with self.subTest(bad=bad), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    self.mod.parse(["--timeout", bad])
                self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.mod.parse(["--timeout", "3600"]).timeout, 3600)
        self.assertEqual(self.mod.parse(["--timeout", "0.3"]).timeout, 0.3)

    def test_writable_roots_reads_every_settings_file(self):
        managed = os.path.join(self.tmp, "managed-settings.json")
        managed_d = os.path.join(self.tmp, "managed-settings.d")
        self.mod.MANAGED_SETTINGS, self.mod.MANAGED_DIR = managed, managed_d

        def allow(path, *dirs):
            self.write(path, json.dumps({"sandbox": {"filesystem": {"allowWrite": list(dirs)}}}))
        allow(os.path.join(self.home, ".claude", "settings.json"), "~/userw")
        allow(managed, "/managedw")
        allow(os.path.join(managed_d, "10-x.json"), "/managed-dw")
        allow(os.path.join(self.main, ".claude", "settings.json"), "projw")
        allow(os.path.join(self.main, ".claude", "settings.local.json"), "/localw")
        import lanelib
        roots = self.real_roots(lanelib.resolve(self.main), self.main)
        for want in (os.path.join(self.home, "userw"), "/managedw", "/managed-dw",
                     os.path.join(self.main, "projw"), "/localw", self.main, "/tmp"):
            self.assertIn(want, roots)
        # Before the checkout is known (git hasn't run yet), the call's dir stands in for it.
        early = self.real_roots(None, self.main)
        self.assertIn(self.main, early)
        self.assertIn("/managedw", early)

    # --- the waiter ----------------------------------------------------------------------

    def test_busy_then_idle_respawns_after_writing_the_carry(self):
        self.script = ["busy", "busy", "waiting", "busy", "idle"]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        (respawn,) = self.calls("tmux", "respawn-pane")
        self.assertEqual(respawn[1:], self.respawn("--permission-mode", "plan")[1:])
        with open(self.carry_marker()) as f:
            carry = json.load(f)
        self.assertEqual(carry["session_id"], SID)
        self.assertEqual(carry["tab"], {"socket": "/tmp/tmux-1000/default",
                                        "server_start": 1791000000, "server_pid": 222,
                                        "pane": "%4"})
        self.assertLess(abs(time.time() - carry["written_at"]), 30)
        self.assertIn(f"session={SID} pane=%4 mode=plain outcome=respawn", self.log())

    def test_compact_waits_for_idle_and_never_respawns(self):
        self.stop_waits = ["shell"]  # a compact keeps background work, so it doesn't matter
        code, out = self.run_pass("--compact", "--foreground")
        self.assertEqual(code, 0, out)
        keys = [a[1:] for a in self.calls("tmux", "send-keys")]
        focus = self.mod.compact_focus("STATUS.md")
        self.assertEqual(keys, [["send-keys", "-t", "%4", "-l", f"/compact {focus}"],
                                ["send-keys", "-t", "%4", "Enter"],
                                ["send-keys", "-t", "%4", "-l",
                                 self.PROMPT + " Call EnterPlanMode first."],
                                ["send-keys", "-t", "%4", "Enter"]])
        self.assertEqual(self.calls("tmux", "respawn-pane"), [])
        self.assertFalse(os.path.exists(self.carry_marker()))
        self.assertIn("mode=compact outcome=compact", self.log())
        self.assertFalse(os.path.exists(self.last_reply()))  # the conversation survives

    REPLIES = [{"prompt_id": "p1", "text": "Earlier: the tests pass.", "time": 1.0},
               {"prompt_id": "p2", "text": "Done: the PR is up.", "time": 2.0},
               {"prompt_id": "p2", "text": "Pass armed. Next: review " + chr(0x00E9), "time": 3.0}]

    def test_a_plain_pass_writes_the_replies_for_the_banner(self):
        self.stop_replies = self.REPLIES
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        with open(self.last_reply(), "rb") as f:
            raw = f.read()
        self.assertIn(chr(0x00E9).encode(), raw)  # UTF-8, not escaped
        last = json.loads(raw)
        self.assertEqual(last["tab"], {"socket": "/tmp/tmux-1000/default",
                                       "server_start": 1791000000, "server_pid": 222,
                                       "pane": "%4"})
        self.assertEqual((last["from_session"], last["replies"], last["shown"]),
                         (SID, self.REPLIES, False))
        self.assertLess(abs(time.time() - last["written_at"]), 30)
        self.assertTrue(os.path.exists(self.carry_marker()))  # its own file, beside the carry

    def test_only_replies_with_text_are_copied(self):
        self.stop_replies = [5, {"prompt_id": "p1", "text": ""}, {"prompt_id": "p1", "text": 7},
                             {"prompt_id": None, "text": "no prompt"}, *self.REPLIES[:1]]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        with open(self.last_reply()) as f:
            self.assertEqual(json.load(f)["replies"], self.REPLIES[:1])

    def prompt(self, pid, content, **fields):
        """A main-chain typed prompt in the transcript, as Claude Code writes it."""
        return {"type": "user", "origin": {"kind": "human"}, "promptId": pid,
                "isSidechain": False, "timestamp": "2026-10-12T18:27:29.500Z",
                "message": {"role": "user", "content": content}, **fields}

    def written(self):
        with open(self.last_reply()) as f:
            return json.load(f)

    def test_each_turns_prompt_is_written_beside_its_replies(self):
        self.stop_replies = self.REPLIES
        self.say(self.prompt("p2", "Open the PR.\nThen pass."),
                 self.prompt("p1", "Run the tests " + chr(0x00E9)),
                 self.prompt("p2", "a second typed entry for p2 is ignored"),
                 self.prompt("p9", "a turn the replies don't have"))
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        stamp = datetime.datetime(2026, 10, 12, 18, 27, 29, 500000,
                                  tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(self.written()["prompts"], [
            {"prompt_id": "p1", "text": "Run the tests " + chr(0x00E9), "time": stamp},
            {"prompt_id": "p2", "text": "Open the PR.\nThen pass.", "time": stamp}])

    def test_only_a_main_chain_typed_prompt_counts(self):
        self.stop_replies = self.REPLIES
        self.say(self.prompt("p1", "from a subagent", isSidechain=True),
                 self.prompt("p1", "the skill body", isMeta=True),
                 self.prompt("p1", [{"type": "tool_result", "content": "x"}], origin=None),
                 self.prompt("p1", "   "),
                 "{not json", "", "[1, 2]", "[" * 100000,  # RecursionError in json
                 self.prompt("p2", "the real one"))
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual([p.get("text") for p in self.written()["prompts"]], ["the real one"])

    def test_a_session_file_too_deep_for_json_reads_as_none(self):
        self.write(os.path.join(self.sessions, f"{CLAUDE}.json"), "[" * 100000)  # json raises RecursionError, not ValueError
        self.assertIsNone(self.real_load(CLAUDE))

    def test_a_turn_a_notice_started_is_marked_and_one_past_the_read_is_left_out(self):
        self.stop_replies = [{"prompt_id": p, "text": "reply " + p} for p in ("p1", "p2", "p3")]
        self.say(self.prompt("p1", "<task-notification>done</task-notification>",
                             origin={"kind": "task-notification"}),
                 self.prompt("p1", "typed after the notice, same turn"),
                 # An agent's message is meta too.
                 self.prompt("p2", "Another Claude session sent a message", isMeta=True,
                             origin={"kind": "peer"}),
                 # p3's start is past the read: only its tool result is left.
                 self.prompt("p3", [{"type": "tool_result", "content": "x"}], origin=None))
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual([(p["prompt_id"], p.get("notice"), p.get("text"))
                          for p in self.written()["prompts"]],
                         [("p1", True, None), ("p2", True, None)])

    def test_a_lone_surrogate_in_one_prompt_keeps_every_prompt(self):
        self.stop_replies = self.REPLIES
        self.say(self.prompt("p1", "cut mid-emoji " + chr(0xD83D)), self.prompt("p2", "fine"))
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual([p["text"] for p in self.written()["prompts"]],
                         ["cut mid-emoji ?", "fine"])

    def test_a_slash_command_and_an_image_show_as_typed(self):
        self.stop_replies = self.REPLIES
        command = ("<command-message>pass</command-message>\n<command-name>/pass</command-name>\n"
                   "<command-args>compact</command-args>")
        self.say(self.prompt("p1", command),
                 self.prompt("p2", [{"type": "image", "source": {"type": "base64", "data": "x"}},
                                    {"type": "text", "text": "what is this?"}]))
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual([p["text"] for p in self.written()["prompts"]],
                         ["/pass compact", "[image]\nwhat is this?"])
        self.assertEqual(self.mod.prompt_text("<command-message>x</command-message>\n"
                                              "<command-name>/clear</command-name>"), "/clear")
        self.assertEqual(self.mod.prompt_text("<command-message>x</command-message>\n"
                                              "<command-name>review</command-name>\n"
                                              "<command-args></command-args>"), "/review")

    def test_a_long_prompt_is_cut_at_12_lines_or_1_kib(self):
        clip = self.mod.clip_prompt
        many = "\n".join(f"line {i}" for i in range(1, 21))
        self.assertEqual(clip(many), "\n".join(f"line {i}" for i in range(1, 13))
                         + "\n" + chr(0x2026) + " (8 more lines)")
        self.assertEqual(clip("\n".join(["l"] * 13)),
                         "\n".join(["l"] * 12) + "\n" + chr(0x2026) + " (1 more line)")
        self.assertEqual(clip("\n".join(["l"] * 12)), "\n".join(["l"] * 12))
        one = clip(chr(0x00E9) * 1000)                       # 2,000 bytes on one line
        self.assertEqual(one, chr(0x00E9) * 512 + chr(0x2026))   # cut on a character boundary
        two = clip("a" * 1000 + "\n" + "b" * 100 + "\nc")
        self.assertEqual(two, "a" * 1000 + "\n" + "b" * 23 + chr(0x2026) + "\n" + chr(0x2026)
                         + " (1 more line)")
        self.assertEqual(clip("a" * 1024 + "\nb"), "a" * 1024 + "\n" + chr(0x2026)
                         + " (1 more line)")                 # no room for a cut line
        self.assertEqual(clip("\n\nfine  \n\n"), "fine")
        self.assertLessEqual(len(clip("x" * 5000).encode()), 1024 + 3)

    def test_only_the_transcripts_last_8_mib_is_read(self):
        self.mod.PROMPT_TAIL = 200
        self.stop_replies = self.REPLIES
        self.say(self.prompt("p1", "too far back"), {"type": "pad", "x": "y" * 300},
                 self.prompt("p2", "recent"))
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual([p["text"] for p in self.written()["prompts"]], ["recent"])

    def test_no_transcript_writes_no_prompts(self):
        # A transcript gone at the call drops the pass (`resumed`), so this calls write_last
        # with one that went away after the call.
        self.stop_replies = self.REPLIES
        plan = self.plan()
        self.write_stop([])
        os.remove(self.transcript())
        tab = {"socket": "/tmp/s", "server_start": 1, "server_pid": 2, "pane": "%4"}
        self.assertEqual(self.mod.write_last(plan, tab), self.last_reply())
        self.assertNotIn("prompts", self.written())
        self.assertEqual(self.written()["replies"], self.REPLIES)
        self.assertIsNone(self.mod.read_prompts(None, ["p1"]))
        self.assertIsNone(self.mod.read_prompts(self.tmp, ["p1"]))   # a directory

    def test_a_surprise_in_the_transcript_never_stops_the_pass(self):
        self.stop_replies = self.REPLIES
        self.mod.prompt_text = lambda content: 1 / 0
        self.say(self.prompt("p1", "boom"))
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls("tmux", "respawn-pane")), 1)
        self.assertNotIn("prompts", self.written())

    def test_compact_leaves_an_earlier_last_reply_alone(self):
        self.old_last_reply()
        code, out = self.run_pass("--compact", "--foreground")
        self.assertEqual(code, 0, out)
        with open(self.last_reply()) as f:
            self.assertEqual(json.load(f)["from_session"], "older")

    def test_no_reply_text_removes_an_earlier_last_reply(self):
        # The popup must never show an earlier pass's replies as this one's.
        for replies in (None, [], "text", [{"prompt_id": "p1", "text": ""}],
                        [{"prompt_id": "p1", "text": None}]):
            with self.subTest(replies=replies):
                self.reset()
                self.old_last_reply()
                self.stop_replies = replies
                code, out = self.run_pass("--foreground")
                self.assertEqual(code, 0, out)
                self.assertEqual(len(self.calls("tmux", "respawn-pane")), 1)
                self.assertFalse(os.path.exists(self.last_reply()))

    def test_an_unreadable_tab_writes_no_carry_and_removes_an_earlier_last_reply(self):
        # pane_tab returns None when tmux's server line can't be read.
        os.environ["FAKE_TMUX_SERVER"] = "not a server line"
        self.old_last_reply()
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls("tmux", "respawn-pane")), 1)
        self.assertFalse(os.path.exists(self.carry_marker()))
        self.assertFalse(os.path.exists(self.last_reply()))

    def test_old_last_replies_are_pruned_once_a_day(self):
        lasts = os.path.dirname(self.last_reply())
        now = time.time()

        def touch(name, age):
            self.write(os.path.join(lasts, name), "{}")
            os.utime(os.path.join(lasts, name), (now - age, now - age))
        touch("9.json", 8 * 86400)
        touch("8.json", 6 * 86400)
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(os.listdir(lasts)), [".pruned", "4.json", "8.json"])
        touch("9.json", 8 * 86400)
        self.mod.prune(lasts, now + 3600)  # within the day: no pass
        self.assertIn("9.json", os.listdir(lasts))
        self.mod.prune(lasts, now + 86401)  # a day later: 8.json is past 7 days too
        self.assertEqual(sorted(os.listdir(lasts)), [".pruned", "4.json"])

    def test_shell_status_is_at_the_prompt_so_compact_acts(self):
        # Live, 2026-10-12: at the prompt with a background shell running, the session file
        # reads `shell`, never `idle`, so a waiter that wanted `idle` sat until its timeout.
        self.script = ["busy", "shell"]
        self.stop_waits = ["shell"]
        code, out = self.run_pass("--compact", "--foreground", "--timeout", "3")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls("tmux", "send-keys")), 4)
        self.assertIn("mode=compact outcome=compact", self.log())

    def test_shell_status_in_plain_mode_drops_busy_on_the_stop_records_waits(self):
        # `shell` ends the wait, so a plain pass reaches the stop record, which names the
        # background shell: a respawn would kill it. The drop must come from those waits, not
        # from a missing record.
        self.script = ["busy", "shell"]
        self.stop_waits = ["shell"]
        code, out = self.run_pass("--foreground", "--timeout", "3")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", "waiting on 1 shell (a respawn would kill it)")
        self.assertIn("busy: waits: shell", self.log())
        self.assertNotIn("no stop record", self.log())

    def test_the_call_returns_and_a_detached_waiter_acts_after(self):
        self.script = ["busy"] * 30 + ["idle"]
        code, out = self.run_pass("--compact")
        self.assertEqual(code, 0, out)
        self.assertIn("once this turn ends", out)
        self.assertNotIn("outcome=compact", self.log())   # the call didn't wait
        for _ in range(200):
            if "outcome=compact" in self.log():
                break
            time.sleep(0.05)
        self.assertIn("mode=compact outcome=compact", self.log())
        self.assertEqual(len(self.calls("tmux", "send-keys")), 4)

    def test_an_approved_detached_waiter_respawns(self):
        self.commit("STATUS.md", APPROVED, msg="Handoff")
        code, out = self.run_pass()
        self.assertEqual(code, 0, out)
        for _ in range(200):
            if "outcome=respawn" in self.log():
                break
            time.sleep(0.05)
        self.assertIn("mode=plain outcome=respawn", self.log())
        (respawn,) = self.calls("tmux", "respawn-pane")
        self.assertEqual(respawn[1:], self.respawn(prompt=self.GO)[1:])

    def test_a_queued_prompt_in_the_settle_drops_resumed(self):
        self.script = ["busy", "idle", "busy"]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("resumed", "pass dropped")

    def test_a_new_turn_that_already_ended_in_the_settle_drops_resumed(self):
        self.script = ["busy", "idle", {"status": "idle", "statusUpdatedAt": 10 ** 13}]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("resumed", "pass dropped")

    def test_the_final_recheck_catches_a_turn_that_starts_after_the_gate(self):
        self.script = ["busy", "idle", "idle", "busy"]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("resumed", "pass dropped")

    def test_an_idle_from_before_the_call_does_not_count(self):
        self.script = ["busy", {"status": "idle", "statusUpdatedAt": 1000}]
        code, out = self.run_pass("--foreground", "--timeout", "0.3")
        self.assertEqual(code, 1, out)
        self.assertDropped("timeout", "pass dropped")

    def test_a_turn_that_never_ends_drops_timeout(self):
        self.script = ["busy"]
        code, out = self.run_pass("--foreground", "--timeout", "0.3")
        self.assertEqual(code, 1, out)
        self.assertDropped("timeout", "pass dropped")

    def test_a_stop_a_hook_blocked_never_acts(self):
        # The Stop hook wrote its record, but another hook blocked the Stop: the turn goes on,
        # so the session file stays busy.
        self.script = ["busy"]
        plan = self.plan()
        self.write_stop([])
        plan.timeout = 0.3
        self.assertEqual(self.mod.wait_and_act(plan, table), "timeout")
        self.assertDropped("timeout", "pass dropped")

    def test_a_typed_prompt_after_the_call_drops_resumed(self):
        self.say(typed("an earlier prompt, before the call"))
        plan = self.plan()
        self.say(typed("wait, don't pass yet"))
        self.assertEqual(self.mod.wait_and_act(plan, table), "resumed")
        self.assertDropped("resumed", "pass dropped")

    def test_other_transcript_entries_after_the_call_do_not_drop(self):
        self.say(typed("an earlier prompt, before the call"))
        plan = self.plan()
        result = [{"type": "tool_result", "content": "x"}]
        self.say({"type": "user", "message": {"content": result}},
                 {"type": "user", "origin": {"kind": "human"},
                  "message": {"content": result}},
                 {"type": "user", "origin": {"kind": "task-notification"},
                  "message": {"content": "task done"}},
                 {"type": "assistant", "message": {"content": "ok"}}, "not json {",
                 "[" * 100000)  # RecursionError in json
        self.assertEqual(self.mod.wait_and_act(plan, table), "respawn")

    def test_waits_at_the_stop_drop_busy(self):
        self.stop_waits = ["shell"]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", "waiting on 1 shell (a respawn would kill it)")
        self.assertIn("waits: shell", self.log())

    def test_a_teammate_at_the_stop_drops_busy(self):
        # stop-ring.sh doesn't count a teammate as a wait, but a respawn kills it in-process.
        self.stop_tasks = ["teammate"]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", "1 teammate running (a respawn would kill it)")
        self.assertIn("busy: tasks: teammate", self.log())

    def test_a_refusal_names_each_task_its_id_and_the_fix(self):
        # Incident e7cc7b9a: "busy: tasks: monitor" named no task, so nobody could tell which
        # to stop. The notice, the toast and pass.log name each, with the id to stop it by.
        self.stop_tasks = [DEPLOY]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", 'monitor "deploy events" (b0fzd27l4) running (a respawn '
                           "would kill it). Stop it (/tasks, or ask Claude to TaskStop it), "
                           "or /pass compact keeps it")
        self.assertIn('busy: tasks: monitor "deploy events" (b0fzd27l4)', self.log())

    def test_a_refusal_shows_two_tasks_and_counts_the_rest(self):
        long = "x" * 60
        self.stop_tasks = [{"label": "monitor", "id": "m1", "description": long},
                           {"label": "teammate", "id": "t1"},
                           {"label": "monitor", "id": "m2", "description": "second"},
                           {"label": "MCP task", "id": "p1", "description": "an MCP job"}]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        cut = "x" * (self.mod.SHOWN_CHARS - 3) + "..."
        self.assertDropped("busy", f'monitor "{cut}" (m1), teammate (t1), +2 more (1 monitor, '
                           "1 MCP task) running (a respawn would kill them). Stop them")
        # pass.log keeps each one whole with its id: what a session reads to stop them.
        self.assertIn(f'busy: tasks: monitor "{long}" (m1), teammate (t1), monitor "second" '
                      '(m2), MCP task "an MCP job" (p1)', self.log())

    def test_a_task_description_reaches_tmux_literally(self):
        # A description is the model's text; display-message expands #(cmd), #{} and %H.
        self.stop_tasks = [{"label": "monitor", "id": "m1",
                            "description": "#(touch pwned) #{pane_id} %H"}]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        for m in self.notices():
            self.assertIn('monitor "##(touch pwned) ##{pane_id} %%H" (m1)', m[-1])
        (toast,) = self.toasts()
        self.assertIn('monitor "#(touch pwned) #{pane_id} %H" (m1)', toast[6])

    def test_a_wait_is_named_from_the_records_tasks(self):
        self.stop_waits = ["shell"]
        self.stop_tasks = [{"label": "shell", "id": "b0fzd27l4",
                            "description": "Wait for the deploy run to finish"}, WATCH]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", 'waiting on shell "Wait for the deploy run to finish" '
                           "(b0fzd27l4) (a respawn would kill it). /pass compact keeps it, or "
                           "let it finish and /pass")
        self.assertIn('busy: waits: shell "Wait for the deploy run to finish" (b0fzd27l4); '
                      f"ignored: artifact watch {URL} (s31udgb0s)", self.log())

    def test_a_wait_and_a_task_are_both_named(self):
        # Review round 1: naming only the wait sent Hayden to wait it out, then a second
        # refusal for the monitor. Both parts name what the respawn would kill, and the fix
        # covers both.
        self.stop_waits = ["shell"]
        self.stop_tasks = [{"label": "shell", "id": "b1", "description": "npm test"}, DEPLOY,
                           WATCH]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", 'waiting on shell "npm test" (b1), and monitor "deploy '
                           'events" (b0fzd27l4) running (a respawn would kill them). /pass '
                           "compact keeps them, or let the waits finish, stop the rest (/tasks, "
                           "or ask Claude to TaskStop them) and /pass")
        self.assertIn('busy: waits: shell "npm test" (b1); tasks: monitor "deploy events" '
                      f"(b0fzd27l4); ignored: artifact watch {URL} (s31udgb0s)", self.log())

    def test_a_wait_the_tasks_dont_describe_is_still_named(self):
        # Review round 2: a second wait with no task entry fell out of the notice.
        self.stop_waits = ["shell", "subagent"]
        self.stop_tasks = [{"label": "shell", "id": "b1", "description": "npm test"}]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", 'waiting on shell "npm test" (b1), +1 more (1 subagent) (a '
                           "respawn would kill them)")
        self.assertIn('busy: waits: shell "npm test" (b1), subagent', self.log())

    def test_waits_and_tasks_together_name_two_in_all(self):
        # The notice fits a status line: SHOWN named across both parts, the rest counted.
        self.stop_waits = ["shell"]
        self.stop_tasks = [{"label": "shell", "id": f"b{i}", "description": f"job {i}"}
                           for i in (1, 2, 3)] + [DEPLOY, {"label": "monitor", "id": "m2"}]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", 'waiting on shell "job 1" (b1), shell "job 2" (b2), +1 more '
                           "(1 shell), and 2 monitors running (a respawn would kill them)")

    def test_an_artifact_watch_alone_lets_the_pass_respawn(self):
        # The Artifact tool's live watch: the session never sees its id and can't stop it, so
        # the respawn ends it and pass.log names the page, for Hayden to watch it again.
        self.stop_tasks = [WATCH, {"label": "dream", "id": "d1"}]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls("tmux", "respawn-pane")), 1)
        self.assertIn(f"outcome=respawn plan mode; ignored: artifact watch {URL} (s31udgb0s)",
                      self.log())

    def test_an_artifact_watch_beside_a_monitor_is_left_out_of_the_notice(self):
        self.stop_tasks = [WATCH, DEPLOY]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", 'monitor "deploy events" (b0fzd27l4) running (a respawn '
                           "would kill it)")
        for m in self.notices():
            self.assertNotIn("artifact", m[-1])
        self.assertIn(f"; ignored: artifact watch {URL} (s31udgb0s)", self.log())

    def test_the_incident_now_respawns(self):
        # e7cc7b9a's Stops listed one task, the watch its Artifact publish armed, in 2.1.296's
        # payload shape; recorded the way stop-ring.sh now records it, it clears a plain pass.
        payload = [{"id": "s31udgb0s", "type": "monitor", "status": "running",
                    "description": f"live updates for artifact {URL} (auto-armed on publish)"}]
        self.stop_tasks = stop_ring.task_entries(payload, stop_ring.task_types(payload, None))
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertIn("outcome=respawn", self.log())

    def test_tasks_lists_the_last_stops_tasks(self):
        # Skill step 2 reads this, never ps: tasks aren't child processes, MCP servers are.
        self.stop_tasks = [DEPLOY, {"label": "shell", "id": "b2", "description": "npm run dev"},
                           WATCH, {"label": "dream", "id": "d1"}, "teammate"]
        self.write_stop(["shell"], at=time.time() - 90)
        code, out = self.run_pass("--tasks")
        self.assertEqual(code, 0, out)
        self.assertIn(f"session {SID} at its last Stop, 1 min ago", out)
        self.assertIn("started or ended since then aren't listed", out)
        for line in ['monitor "deploy events" (b0fzd27l4): blocks a plain pass',
                     'shell "npm run dev" (b2): blocks a plain pass; the turn waits on it',
                     f"artifact watch {URL} (s31udgb0s): doesn't block a plain pass",
                     "dream (d1): doesn't block a plain pass", "teammate: blocks a plain pass"]:
            self.assertIn("\n  " + line + "\n", out)
        # Read-only: nothing shown, logged or queued.
        self.assertEqual((self.notices(), self.log()), ([], ""))
        self.assertFalse(os.listdir(os.path.join(self.state, "pass-pending"))
                         if os.path.isdir(os.path.join(self.state, "pass-pending")) else [])

    def test_a_type_that_only_looks_ignored_still_refuses(self):
        # Review round 3: no payload type may reach an ignored label by cleaning, and a type
        # spelled `artifact watch` (no page) is no artifact watch.
        payload = [{"id": "d1", "type": "dream "}, {"id": "a1", "type": "artifact watch"}]
        self.stop_tasks = stop_ring.task_entries(payload, stop_ring.task_types(payload, None))
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", "unlabeled task (d1), artifact watch (a1) running")

    def test_a_record_time_that_isnt_finite_refuses(self):
        for when in (float("nan"), float("inf")):
            with self.subTest(when=when):
                plan = types.SimpleNamespace(session_id=SID, called=time.time())
                rec = {"time": when, "waits": [], "tasks": []}
                self.assertEqual(self.mod.stop_problem(plan, rec)[0],
                                 "no stop record since the call")
        self.write(os.path.join(self.state, "stops", f"{SID}.json"),
                   json.dumps({"time": float("-inf"), "waits": [], "tasks": []}))
        code, out = self.run_pass("--tasks")
        self.assertEqual(code, 0, out)
        self.assertIn("the record's time can't be read: a plain pass would refuse", out)

    def test_tasks_never_reads_clear_where_the_waiter_refuses(self):
        # Review round 1: a wait with no task entry, or waits that aren't a list, must not
        # print "none" or "doesn't block" when the waiter would refuse that record.
        stops = os.path.join(self.state, "stops", f"{SID}.json")
        self.write(stops, json.dumps({"time": time.time(), "waits": ["shell"], "tasks": []}))
        code, out = self.run_pass("--tasks")
        self.assertEqual(code, 0, out)
        self.assertIn("\n  shell: blocks a plain pass; the turn waits on it\n", out)
        self.assertNotIn("\n  none\n", out)
        self.write(stops, json.dumps({"time": time.time(), "waits": "shell", "tasks": [WATCH]}))
        code, out = self.run_pass("--tasks")
        self.assertIn("\n  (waits can't be read: a plain pass would refuse)\n", out)

    def test_tasks_with_no_record_or_task_list_says_so(self):
        code, out = self.run_pass("--tasks")
        self.assertEqual(code, 0, out)
        self.assertIn(f"no stop record for session {SID}", out)
        # Review rounds 6 and 7: a record that exists but can't be read refuses, as the waiter
        # does. Only a missing path says "yet": a dangling link or a directory there doesn't.
        path = os.path.join(self.state, "stops", f"{SID}.json")
        unreadable = "the stop record can't be read: a plain pass would refuse"
        cases = [("{}", "the record's time can't be read: a plain pass would refuse"),
                 ("[]", unreadable), ("null", unreadable), ("not json", unreadable),
                 ("", unreadable), ("[" * 100000, unreadable),  # RecursionError in json
                 ("<dangling link>", unreadable), ("<directory>", unreadable)]
        for body, says in cases:
            with self.subTest(body=body[:12]):
                if body == "<dangling link>":
                    os.remove(path)
                    os.symlink(path + ".gone", path)
                elif body == "<directory>":
                    os.remove(path)
                    os.mkdir(path)
                else:
                    self.write(path, body)
                code, out = self.run_pass("--tasks")
                self.assertEqual(code, 0, out)
                self.assertNotIn("no stop record", out)
                self.assertIn(says, out)
        os.rmdir(path)
        self.write(path, json.dumps({"time": time.time(), "waits": []}))
        code, out = self.run_pass("--tasks")
        self.assertIn("no task list: a plain pass would refuse", out)
        self.write_stop([])
        code, out = self.run_pass("--tasks")
        self.assertIn("\n  none\n", out)
        del os.environ["CLAUDE_CODE_SESSION_ID"]
        code, out = self.run_pass("--tasks")
        self.assertEqual(code, 1, out)
        self.assertIn("CLAUDE_CODE_SESSION_ID", out)

    def test_no_stop_record_drops_busy(self):
        self.stop_waits = None
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", "the Stop wrote no record, so background work")
        self.assertIn("busy: no stop record", self.log())

    def test_a_stop_record_from_before_the_call_drops_busy(self):
        self.stop_waits = None
        self.write_stop([], at=time.time() - 30)
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", "no record since the call")

    def test_a_pane_not_running_claude_drops_gone(self):
        for pane in (f"{PANE_SHELL} zsh", "12345 claude"):
            with self.subTest(pane=pane):
                os.environ["FAKE_TMUX_PANE"] = pane
                self.reset()
                self.assertEqual(self.mod.wait_and_act(self.plan(), table), "gone")
                self.assertDropped("gone", "pass dropped")

    def test_a_gone_pane_or_session_drops_gone_at_once(self):
        for script, fail, dead in ((["busy"], "display-message", False), ([None], "", False),
                                   (["busy"], "", True),
                                   ([{"status": "busy", "sessionId": "x"}], "", False),
                                   ([{"status": "busy", "tmux": "main:@3.%5"}], "", False)):
            with self.subTest(script=script, fail=fail, dead=dead):
                self.reset("busy")
                plan = self.plan()
                plan.timeout = 30
                self.script = script
                os.environ["FAKE_TMUX_FAIL"] = fail
                self.start_now = None if dead else START
                began = time.monotonic()
                self.assertEqual(self.mod.wait_and_act(plan, table), "gone")
                self.assertLess(time.monotonic() - began, 5)
                self.assertDropped("gone", "pass dropped")
                os.environ["FAKE_TMUX_FAIL"] = ""
                self.start_now = START

    def test_a_failed_respawn_removes_the_carry(self):
        os.environ["FAKE_TMUX_FAIL"] = "respawn-pane"
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertEqual(len(self.calls("tmux", "respawn-pane")), 1)
        self.assertFalse(os.path.exists(self.carry_marker()))
        self.assertFalse(os.path.exists(self.last_reply()))
        self.assertIn("outcome=failed", self.log())
        self.assertIn("can't find pane", self.log())
        self.assertLoud("pass failed in tab 3: tmux could not respawn or type into the pane. "
                        "See pass.log")

    def test_an_error_after_the_carry_removes_it_and_logs_error(self):
        real = self.mod.tmux

        def tmux(plan, *args):
            if args[0] == "respawn-pane":
                self.assertTrue(os.path.exists(self.carry_marker()))
                self.assertTrue(os.path.exists(self.last_reply()))
                raise RuntimeError("boom")
            return real(plan, *args)
        self.mod.tmux = tmux
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertFalse(os.path.exists(self.carry_marker()))
        self.assertFalse(os.path.exists(self.last_reply()))
        self.assertIn("outcome=error RuntimeError: boom", self.log())
        self.assertLoud("pass failed in tab 3: an error in the waiter. See pass.log")

    def test_a_waiter_that_cannot_detach_reports_error(self):
        real_fork = os.fork
        forks = []

        def second_fork_fails():
            forks.append(1)
            if len(forks) > 1:
                raise OSError("out of processes")
            return real_fork()
        for patch, words in ((mock.patch.object(os, "setsid", side_effect=OSError("no setsid")),
                              "no setsid"),
                             (mock.patch.object(os, "fork", side_effect=second_fork_fails),
                              "out of processes")):
            with self.subTest(words=words):
                with patch:
                    code, out = self.run_pass("--compact")
                self.assertEqual(code, 1, out)
                self.assertIn(f"the waiter didn't start: OSError: {words}", out)
                self.assertNotIn("once this turn ends", out)
                self.assertIn(f"outcome=error detach: OSError: {words}", self.log())
        time.sleep(0.3)
        self.assertEqual(self.calls("tmux", "send-keys"), [])

    # --- staleness ----------------------------------------------------------------------

    def test_an_edit_after_the_call_drops_stale(self):
        plan = self.plan()
        self.write(os.path.join(self.main, "late.txt"), "x")
        self.assertEqual(self.mod.wait_and_act(plan, table), "stale")
        self.assertDropped("stale", "handoff is stale")

    def test_a_commit_after_the_call_drops_stale(self):
        plan = self.plan()
        time.sleep(1.05)  # past the status file's mtime, at commit-time resolution
        self.commit("late.txt", "x")
        self.assertEqual(self.mod.wait_and_act(plan, table), "stale")
        self.assertDropped("stale", "handoff is stale")


class Handed(Base):
    """A checkout whose handoff passes, with no tests of its own (Plain's would run again)."""
    PROMPT = Plain.PROMPT

    def setUp(self):
        super().setUp()
        self.commit("STATUS.md", GOOD, msg="Handoff")


class TurnEnd(Handed):
    """The turn's end while delegated work runs. Claude Code 2.1.300's session file says `busy`
    at the prompt while an agent, a teammate or a workflow runs (isLoading || delegatedActive),
    so the transcript past the call says when the turn ended (the live timeouts of 70e81418 and
    2ae29a58)."""

    def compacts(self, *script, timeout="5"):
        self.script = list(script)
        return self.run_pass("--compact", "--foreground", "--timeout", timeout)

    def test_busy_with_a_turn_end_past_the_call_is_at_the_prompt(self):
        code, out = self.compacts("busy", self.then("busy", END))
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls("tmux", "send-keys")), 4)
        self.assertIn("mode=compact outcome=compact", self.log())

    def test_plain_with_an_agent_running_refuses_busy_naming_it(self):
        # Not `timeout`: the turn's end lets the waiter reach the stop record, which names it.
        self.stop_tasks = [AGENT]
        self.script = ["busy", self.then("busy", END, stop=["subagent"])]
        code, out = self.run_pass("--foreground", "--timeout", "5")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", 'waiting on subagent "Write the notice hook" (a1b2c3d4) (a '
                           "respawn would kill it)")
        self.assertIn('busy: waits: subagent "Write the notice hook" (a1b2c3d4)', self.log())
        self.assertNotIn("outcome=timeout", self.log())

    def test_a_turn_end_from_before_the_call_does_not_count(self):
        self.say(END)
        code, out = self.compacts("busy", timeout="0.3")
        self.assertEqual(code, 1, out)
        self.assertDropped("timeout", "pass dropped")

    def test_a_stop_a_hook_blocked_is_no_turn_end(self):
        # The spike: a blocked Stop writes stop_hook_summary and the hook's feedback, and
        # turn_duration only at the real end.
        blocked = ({"type": "attachment", "attachment": {"type": "hook_blocking_error"}},
                   STOP_ONLY, {"type": "user", "isSidechain": False,
                               "message": {"role": "user", "content": "Stop hook feedback:\nx"}},
                   STARTS["an assistant entry"])
        code, out = self.compacts("busy", self.then("busy", *blocked), timeout="0.3")
        self.assertEqual(code, 1, out)
        self.assertDropped("timeout", "pass dropped")

    def test_an_interrupt_ends_the_turn(self):
        code, out = self.compacts("busy", self.then("busy", INTERRUPT))
        self.assertEqual(code, 0, out)
        self.assertIn("mode=compact outcome=compact", self.log())

    def test_a_turn_start_after_the_end_drops_resumed(self):
        # The end lands at the read after then()'s (the break), the settle reads the session
        # file twice (look_again), and a start queued at the settle's second read lands at the
        # final re-check's first.
        for name, start in STARTS.items():
            for where, between in (("in the settle", ()),
                                   ("at the final re-check", ("busy", "busy"))):
                with self.subTest(start=name, where=where):
                    self.reset()
                    code, out = self.compacts("busy", self.then("busy", END), *between,
                                              self.then("busy", start))
                    self.assertEqual(code, 1, out)
                    self.assertDropped("resumed", "pass dropped")
                    line = self.log().splitlines()[-1]
                    self.assertIn("outcome=resumed a new turn in the transcript " + where, line)

    def test_a_status_flip_with_no_turn_start_does_not_drop(self):
        # The spike: an agent resuming after its shell ended flipped `shell` to `busy` with no
        # transcript entry, so once the end is known only a start marker means a new turn. The
        # end lands at the read after then()'s, which is the break, at `busy`.
        code, out = self.compacts("busy", self.then("busy", END), "busy", "shell", "busy")
        self.assertEqual(code, 0, out)
        self.assertIn("mode=compact outcome=compact", self.log())

    def test_a_status_flip_whose_start_marker_lands_late_drops_resumed(self):
        # The spike (20:17:40): a new turn sets the session file busy about 150 ms before its
        # user entry reaches the transcript. A flip once the end is known waits TRANSCRIPT_LAG
        # for that start marker before it is let through.
        start = STARTS["a task notice"]
        for where, between in (("in the settle", ()),
                               ("at the final re-check", ("shell", "shell"))):
            with self.subTest(where=where):
                self.reset()
                code, out = self.compacts("busy", self.then("shell", END), *between,
                                          self.lagged("busy", start))
                self.assertEqual(code, 1, out)
                self.assertDropped("resumed", "pass dropped")
                self.assertIn("outcome=resumed a new turn in the transcript " + where,
                              self.log().splitlines()[-1])

    def test_a_turn_start_on_a_session_kept_busy_drops_resumed(self):
        # An agent runs throughout, so the status stays busy: a new turn changes no
        # statusUpdatedAt, and only its start marker, about 150 ms late, shows it. Once the end
        # is known the settle and the final re-check always give it TRANSCRIPT_LAG.
        start = STARTS["a task notice"]
        with self.subTest(where="in the settle"):
            code, out = self.compacts("busy", self.then("busy", END), self.lagged("busy", start))
            self.assertEqual(code, 1, out)
            self.assertDropped("resumed", "pass dropped")
            self.assertIn("outcome=resumed a new turn in the transcript in the settle",
                          self.log().splitlines()[-1])
        with self.subTest(where="at the final re-check"):
            # The start lands 0.2 s after the final re-check's first look (its first procs
            # read), when the waiter would otherwise act.
            self.reset("busy", self.then("busy", END), "busy")
            plan = self.plan("--compact")
            land = self.lagged(None, start)
            self.assertEqual(self.mod.wait_and_act(plan, lambda: (land(), table())[1]),
                             "resumed")
            self.assertEqual(self.calls("tmux", "send-keys"), [])
            self.assertIn("outcome=resumed a new turn in the transcript at the final re-check",
                          self.log().splitlines()[-1])

    def test_an_idle_break_keeps_the_strict_status_rule(self):
        # At the prompt with no background work nothing flips idle to busy but a turn, so a
        # status change alone drops: Hayden's prompt sets the file busy at the settle's second
        # look, and its user entry reaches the transcript only after.
        code, out = self.compacts("busy", self.then("idle", END), "idle",
                                  self.lagged("busy", typed("wait, don't pass"), after=0.3))
        self.assertEqual(code, 1, out)
        self.assertDropped("resumed", "pass dropped")
        self.assertIn("outcome=resumed status busy in the settle", self.log().splitlines()[-1])

    def test_a_shell_break_then_a_bare_flip_to_busy_still_acts(self):
        # A background shell or an agent flips the status with no turn (the spike, 20:19:29).
        # The break poll sees `shell` before the end lands; the settle's fresh scan finds it.
        code, out = self.compacts("busy", self.then("shell", END), "busy")
        self.assertEqual(code, 0, out)
        self.assertIn("mode=compact outcome=compact", self.log())

    def test_a_shell_break_whose_end_lands_after_the_status_still_acts(self):
        # The reviewer's case: turn_duration's bytes land 30 ms after the status went `shell`,
        # so the break poll can't see them. The rule is picked after the settle (0.3 s here;
        # 1 s live, past the spike's 0.1 to 0.4 s), so an agent resuming in it, `shell` to
        # `busy` with no turn, is no resumption.
        self.mod.SETTLE = 0.3
        code, out = self.compacts("busy", self.lagged("shell", END, after=0.03), "busy")
        self.assertEqual(code, 0, out)
        self.assertIn("mode=compact outcome=compact", self.log())

    def test_a_busy_break_keeps_looking_while_the_status_flips(self):
        # A flip at the second look earns another TRANSCRIPT_LAG; a start marker that lands in
        # it drops resumed.
        code, out = self.compacts("busy", self.then("busy", END), "busy", "shell",
                                  self.lagged("busy", STARTS["a task notice"], after=0.3))
        self.assertEqual(code, 1, out)
        self.assertDropped("resumed", "pass dropped")
        self.assertIn("outcome=resumed a new turn in the transcript in the settle",
                      self.log().splitlines()[-1])

    def test_a_status_that_keeps_flipping_is_looked_at_three_rounds_at_most(self):
        began = time.monotonic()
        code, out = self.compacts("busy", self.then("busy", END), "busy",
                                  *["shell", "busy"] * 10)
        self.assertEqual(code, 0, out)
        self.assertIn("mode=compact outcome=compact", self.log())
        # The settle and the final re-check: at most LAG_ROUNDS waits each.
        self.assertLess(time.monotonic() - began,
                        2 * self.mod.LAG_ROUNDS * self.mod.TRANSCRIPT_LAG + 3)

    def test_a_whole_turn_after_the_passing_turns_end_drops_resumed(self):
        # The end, then a notice turn's start and its own end, all before the first look: the
        # latest end has no start after it, but the passing turn's own end (the first) does.
        turn = (END, STARTS["a task notice"], STARTS["an assistant entry"], END)
        for mode in ((), ("--compact",)):
            for status in ("busy", "idle"):
                with self.subTest(mode=mode, status=status):
                    self.reset()
                    self.script = ["busy", self.then(status, *turn)]
                    code, out = self.run_pass(*mode, "--foreground", "--timeout", "5")
                    self.assertEqual(code, 1, out)
                    self.assertDropped("resumed", "pass dropped")
                    self.assertIn("outcome=resumed a new turn in the transcript",
                                  self.log().splitlines()[-1])

    def test_bookkeeping_after_the_end_does_not_count(self):
        code, out = self.compacts("busy", self.then("busy", END, *AFTER_END),
                                  self.then("busy", *AFTER_END))
        self.assertEqual(code, 0, out)
        self.assertIn("mode=compact outcome=compact", self.log())

    def test_sidechain_entries_do_not_count(self):
        def side(entry):
            return {**entry, "isSidechain": True}
        code, out = self.compacts("busy", self.then("busy", side(END)), timeout="0.3")
        self.assertEqual(code, 1, out)
        self.assertDropped("timeout", "pass dropped")
        self.reset()
        code, out = self.compacts("busy", self.then("busy", END),
                                  self.then("busy", *map(side, STARTS.values())))
        self.assertEqual(code, 0, out)
        self.assertIn("mode=compact outcome=compact", self.log())

    def test_a_torn_last_line_is_read_once_complete(self):
        line = json.dumps(END)
        plan = self.plan("--compact")
        self.raw(line[:15])
        self.mod.scan_turns(plan)
        self.assertFalse(self.mod.turn_over(plan))
        self.assertEqual(plan.read_at, os.path.getsize(self.transcript()))  # read once
        self.raw(line[15:] + "\n")
        self.mod.scan_turns(plan)
        self.assertTrue(self.mod.turn_over(plan))
        self.assertEqual((plan.read_at, plan.torn), (os.path.getsize(self.transcript()), b""))
        # The same across the waiter's polls.
        self.reset()
        code, out = self.compacts("busy", lambda: (self.raw(line[:15]), "busy")[1],
                                  self.then("busy", line[15:]))
        self.assertEqual(code, 0, out)
        self.assertIn("mode=compact outcome=compact", self.log())


class Notices(Handed):
    """Every drop, and `partial`, leaves the session a notice at pass-notice/<sid>.json, which
    hooks/pass-notice.sh injects into its next turn: tmux alone never reached the session."""

    FIELDS = {"v", "session_id", "outcome", "mode", "called", "dropped", "text"}
    READ_LOG = "Read pass.log, then run the pass skill again."

    def loud(self, n, cause, fix):
        return (f"[pass] The {n['mode']} pass you queued at {hms(n['called'])}Z was dropped at "
                f"{hms(n['dropped'])}Z ({n['outcome']}): {cause}. No pass is pending now, so "
                f"don't tell anyone one is queued. {fix} Tell Hayden in one line.")

    def case_stale(self):
        plan = self.plan()
        late = os.path.join(self.main, "late.txt")
        self.write(late, "x")
        try:
            self.assertEqual(self.mod.wait_and_act(plan, table), "stale")
        finally:
            os.remove(late)
        gaps = re.findall(r"outcome=stale (.*)$", self.log(), re.M)[-1]
        self.assertIn("late.txt", gaps)
        return "stale", "plain", lambda n: self.loud(
            n, f"the handoff went stale (work landed after it: {gaps})",
            "Run the delta handoff and handoff-check, then run the pass skill again if it still "
            "applies.")

    def case_busy_at_the_stop(self):
        self.stop_tasks = [DEPLOY]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        return "busy", "plain", lambda n: self.loud(
            n, 'monitor "deploy events" (b0fzd27l4) running (a respawn would kill it). Stop it '
               "(/tasks, or ask Claude to TaskStop it), or /pass compact keeps it",
            f"Follow the pass skill's step 2 (pass-respawn -C {self.main} --tasks, then TaskStop "
            "the leftovers) or pass in compact mode.")

    def case_busy_in_the_pane(self):
        os.environ["FAKE_TMUX_MODE"] = "1"
        code, out = self.run_pass("--compact", "--foreground")
        self.assertEqual(code, 1, out)
        return "busy", "compact", lambda n: self.loud(
            n, "pane in copy mode at the final check",
            "Run the pass skill again once Hayden has cleared it.")

    def case_timeout(self):
        self.script = ["busy"]
        code, out = self.run_pass("--compact", "--foreground", "--timeout", "0.3")
        self.assertEqual(code, 1, out)
        return "timeout", "compact", lambda n: self.loud(
            n, "the turn didn't end within 0.3 s of the call",
            "Make pass-respawn the turn's last action, then run the pass skill again.")

    def case_failed(self):
        os.environ["FAKE_TMUX_FAIL"] = "respawn-pane"
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        return "failed", "plain", lambda n: self.loud(
            n, "tmux could not respawn or type into the pane (can't find pane: %4)",
            self.READ_LOG)

    def case_error(self):
        real = self.mod.tmux

        def tmux(plan, *args):
            if args[0] == "respawn-pane":
                raise RuntimeError("boom")
            return real(plan, *args)
        self.mod.tmux = tmux
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        return "error", "plain", lambda n: self.loud(
            n, "the waiter hit an error (RuntimeError: boom)", self.READ_LOG)

    def case_resumed(self):
        plan = self.plan()
        self.say(typed("wait, don't pass yet"))
        self.assertEqual(self.mod.wait_and_act(plan, table), "resumed")
        return "resumed", "plain", lambda n: (
            f"[pass] The plain pass you queued at {hms(n['called'])}Z was dropped: a prompt was "
            "typed or queued after the call. No pass is pending now; run the pass skill again "
            "once this work is done, if it still applies.")

    def case_gone(self):
        os.environ["FAKE_TMUX_PANE"] = f"{PANE_SHELL} zsh"
        self.assertEqual(self.mod.wait_and_act(self.plan("--compact"), table), "gone")
        return "gone", "compact", lambda n: (
            f"[pass] The compact pass you queued at {hms(n['called'])}Z was dropped: the pane or "
            f"its claude changed (pane %4 runs zsh (pid {PANE_SHELL}), not claude {CLAUDE}). No "
            "pass is pending now.")

    def case_cancelled(self):
        def term():
            raise self.mod.Cancelled()  # as on_term raises it on --cancel's SIGTERM
        self.script = ["busy", term]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        return "cancelled", "plain", lambda n: (
            f"[pass] The plain pass you queued at {hms(n['called'])}Z was cancelled. No pass is "
            "pending now.")

    def case_partial(self):
        checks = []

        def pane_problem(plan):  # clear at the final re-check, a draft in the compact gap
            checks.append(plan)
            return None if len(checks) == 1 else "unsent draft in the input box"
        self.mod.pane_problem = pane_problem
        self.assertEqual(self.mod.wait_and_act(self.plan("--compact"), table), "partial")
        prompt = self.PROMPT + " Call EnterPlanMode first."
        return "partial", "compact", lambda n: (
            f"[pass] The compact pass you queued at {hms(n['called'])}Z sent /compact, but the "
            "resume prompt wasn't typed (unsent draft in the input box). No pass is pending now. "
            f"Treat this as your resume prompt unless Hayden's message says otherwise: {prompt}")

    def test_every_drop_and_partial_leaves_the_session_a_notice(self):
        real = (self.mod.tmux, self.mod.pane_problem)
        env = {k: os.environ[k] for k in ("FAKE_TMUX_FAIL", "FAKE_TMUX_MODE", "FAKE_TMUX_PANE")}
        seen = set()
        for case in (self.case_stale, self.case_busy_at_the_stop, self.case_busy_in_the_pane,
                     self.case_timeout, self.case_failed, self.case_error, self.case_resumed,
                     self.case_gone, self.case_cancelled, self.case_partial):
            with self.subTest(case=case.__name__):
                self.reset()
                self.stop_tasks = None
                os.environ.update(env)
                self.mod.tmux, self.mod.pane_problem = real
                with contextlib.suppress(FileNotFoundError):
                    os.remove(self.notice_file())
                began = time.time()
                outcome, mode, want = case()
                n = self.notice()
                self.assertEqual(set(n), self.FIELDS)
                self.assertEqual((n["v"], n["session_id"], n["outcome"], n["mode"]),
                                 (1, SID, outcome, mode))
                self.assertTrue(began <= n["called"] <= n["dropped"] <= time.time(), n)
                self.assertEqual(n["text"], want(n))
                self.assertEqual(os.stat(self.notice_file()).st_mode & 0o777, 0o600)
                seen.add(outcome)
        self.assertEqual(seen, set(self.mod.DROPS) | {"partial"})

    def test_a_resumed_notice_names_its_reason(self):
        # The notice and the brief status-line message (QUIET) both follow the reason; an
        # unreadable transcript is loud.
        again = ("No pass is pending now; run the pass skill again once this work is done, if "
                 "it still applies.")
        status = ("pass dropped: the session's status changed after its turn. /pass again if "
                  "it still applies")
        cases = (
            ("a typed prompt", lambda: ["busy", self.then("busy", typed("wait")), "idle"],
             "a prompt was typed or queued after the call", again, self.mod.DROPS["resumed"]),
            ("a new turn", lambda: ["busy", self.then("busy", END),
                                    self.then("busy", STARTS["a task notice"])],
             "a new turn started after the call (a prompt, a task notice or an agent's "
             "message)", again,
             "pass dropped: a new turn started after the call. /pass again if it still applies"),
            ("a dialog", lambda: ["busy", "idle", "waiting"],
             "the session's status became waiting (a dialog, or a change the waiter can't "
             "read)", again, status),
            ("a status change", lambda: ["busy", "idle", "busy"],
             "the session's status changed after its turn ended (now busy), so a new turn "
             "can't be ruled out", again, status),
            # An autopass would loop on this one: passing again drops the same way.
            ("no transcript", lambda: (os.remove(self.transcript()), ["busy", "idle"])[1],
             "the transcript couldn't be read, so a prompt after the call can't be ruled out",
             "No pass is pending now. Tell Hayden; passing again drops the same way until the "
             "transcript can be read.",
             "pass dropped: the transcript couldn't be read; passing again drops the same way"))
        for name, script, cause, tail, shown in cases:
            with self.subTest(reason=name):
                self.reset()
                self.script = script()
                code, out = self.run_pass("--compact", "--foreground", "--timeout", "5")
                self.assertEqual(code, 1, out)
                n = self.notice()
                self.assertEqual(n["outcome"], "resumed")
                self.assertEqual(n["text"], f"[pass] The compact pass you queued at "
                                            f"{hms(n['called'])}Z was dropped: {cause}. {tail}")
                if name == "no transcript":
                    # Not Hayden's doing and it recurs on every pass, so it is loud: the held
                    # line and the toast, though the outcome stays `resumed`.
                    self.assertLoud(shown.replace("pass dropped: ", "pass dropped in tab 3: "))
                    continue
                (msg,) = self.notices()
                self.assertEqual(msg[1:], ["display-message", "-t", "%4", shown])
                self.assertEqual(self.toasts(tries=4), [])   # still QUIET

    def test_a_pane_tmux_cannot_answer_has_its_own_cause(self):
        # Not "pane in copy mode": tmux gave no answer at the final check.
        real = self.mod.tmux
        self.mod.tmux = lambda plan, *args: (None if "#{pane_in_mode}" in args
                                             else real(plan, *args))
        code, out = self.run_pass("--compact", "--foreground")
        self.assertEqual(code, 1, out)
        self.assertLoud("pass dropped in tab 3: tmux didn't answer. /pass again once the tab is "
                        "back")
        self.assertIn("outcome=busy busy: tmux didn't answer", self.log())
        n = self.notice()
        self.assertEqual(n["text"], self.loud(n, "tmux didn't answer at the final check",
                                              "Run the pass skill again once the tab is back."))

    def test_a_prompt_that_failed_after_compact_went_out_is_handed_over(self):
        # send-keys 3 or 4: /compact and its Enter are out, so passing again would compact a
        # second time. The outcome stays `failed`; the notice, the held tmux line, the toast and
        # pass.log hand over the resume prompt, as `partial`'s do. Once the prompt may be in the
        # box (the Enter failed, or tmux gave no answer, so the keys may have gone), telling
        # Hayden to type it would double it: he is told to press Enter instead.
        real = self.mod.tmux
        prompt = self.PROMPT + " Call EnterPlanMode first."
        pane_err = "can't find pane: %4"
        head = f"[pass] The compact pass you queued at {{}}Z sent /compact"
        take = ("No pass is pending now. Treat this as your resume prompt unless Hayden's "
                f"message says otherwise: {prompt}")
        not_typed = (f"pass failed after /compact was sent; type the resume prompt yourself in "
                     f"tab 3: {prompt}")
        typed_in = (f"pass failed after the resume prompt was typed; press Enter (or type it if "
                    f"the box is empty) in tab 3: {prompt}")

        def maybe_typed(said):
            return (f" and typed the resume prompt, but its Enter may not have gone through "
                    f"(tmux: {said}), so the prompt may sit unsent in the input box. {take}")
        cases = (  # (send-keys call that fails, tmux's answer, what pass.log and the notice say)
            (3, pane_err, pane_err, not_typed,
             f", but the resume prompt wasn't typed or sent (tmux: {pane_err}). {take}"),
            # An error with no text: the notice says so rather than repeat pass.log's prompt.
            (3, "", "no error text", not_typed,
             f", but the resume prompt wasn't typed or sent (tmux: no error text). {take}"),
            (4, pane_err, pane_err, typed_in, maybe_typed(pane_err)),
            # No answer at all (a timeout): the keys may have gone, so the prompt may be in.
            (3, None, "tmux didn't run", typed_in, maybe_typed("tmux didn't run")),
            (1, pane_err, pane_err, "pass failed in tab 3: tmux could not respawn or type into "
                                    "the pane", None))
        for nth, answer, said, shown, notice in cases:
            with self.subTest(nth=nth, answer=answer):
                self.reset()
                sent = []

                def tmux(plan, *args, nth=nth, answer=answer, sent=sent):
                    if args[0] == "send-keys":
                        sent.append(args)
                        if len(sent) == nth:
                            return (None if answer is None
                                    else subprocess.CompletedProcess(args, 1, "", answer))
                    return real(plan, *args)
                self.mod.tmux = tmux
                code, out = self.run_pass("--compact", "--foreground")
                self.assertEqual(code, 1, out)
                (line,) = [ln for ln in self.log().splitlines() if "outcome=failed" in ln][-1:]
                self.assertIn(f"outcome=failed send-keys {nth} of 4: {said}", line)
                self.assertLoud(shown)
                n = self.notice()
                self.assertEqual(n["outcome"], "failed")
                if notice is None:
                    self.assertNotIn("resume prompt", line)
                    self.assertEqual(n["text"], self.loud(
                        n, f"tmux could not respawn or type into the pane (send-keys {nth} of 4: "
                           f"{pane_err})", self.READ_LOG))
                    continue
                self.assertTrue(line.endswith(f"; resume prompt: {prompt}"), line)
                self.assertEqual(n["text"], head.format(hms(n["called"])) + notice)
                self.assertEqual(n["text"].count(prompt), 1)   # handed over once, not repeated
        self.mod.tmux = real

    def test_the_notice_comes_after_the_log_and_before_any_tmux_call(self):
        # A dying tmux server can't delay or skip it: once the drop is logged, tmux is gone here.
        real = self.mod.tmux
        ready = []

        def tmux(plan, *args):
            if self.log().count(" outcome=") > logged:
                ready.append(os.path.exists(self.notice_file()))
                return None   # as when tmux didn't run
            return real(plan, *args)
        self.mod.tmux = tmux
        for outcome, args, script, words in (
                ("timeout", ("--compact", "--timeout", "0.3"), ["busy"], None),
                ("resumed", (), None, "wait"), ("busy", (), None, None)):
            with self.subTest(outcome=outcome):
                self.reset(*(script or ()))
                self.stop_waits = ["shell"] if outcome == "busy" else []
                with contextlib.suppress(FileNotFoundError):
                    os.remove(self.notice_file())
                logged, ready[:] = self.log().count(" outcome="), []
                if words:
                    self.script = ["busy", self.then("busy", typed(words)), "idle"]
                code, out = self.run_pass(*args, "--foreground")
                self.assertEqual(code, 1, out)
                self.assertEqual(self.notice()["outcome"], outcome)
                self.assertTrue(ready and all(ready), ready)

    def test_a_tmux_that_fails_every_call_still_gets_the_notice(self):
        os.environ["FAKE_TMUX_FAIL"] = ("display-message capture-pane list-clients send-keys "
                                        "respawn-pane")
        for mode in ((), ("--compact",)):
            with self.subTest(mode=mode):
                self.reset()
                code, out = self.run_pass(*mode, "--foreground")
                self.assertEqual(code, 1, out)
                n = self.notice()
                self.assertEqual((n["outcome"], n["mode"]),
                                 ("gone", "compact" if mode else "plain"))
                self.assertIn("can't find pane: %4", n["text"])

    def test_a_new_call_clears_the_sessions_old_notice(self):
        for sid in (SID, "other-session"):
            self.write(self.notice_file(sid), json.dumps({"v": 1, "session_id": sid, "text": "x"}))
        cleared = []
        self.script = ["busy", lambda: (cleared.append(not os.path.exists(self.notice_file())),
                                        "busy")[1], "idle"]
        code, out = self.run_pass("--compact", "--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual(cleared, [True])   # gone before the wait began
        self.assertFalse(os.path.exists(self.notice_file()))
        self.assertTrue(os.path.exists(self.notice_file("other-session")))

    def test_old_notices_and_taken_files_are_pruned_at_the_call(self):
        notices, now = os.path.dirname(self.notice_file()), time.time()
        for name, age in (("old.json", 8 * 86400), ("new.json", 6 * 86400),
                          ("a.json.12.taken", 2 * 86400), ("b.json.13.taken", 12 * 3600)):
            self.write(os.path.join(notices, name), "{}")
            os.utime(os.path.join(notices, name), (now - age, now - age))
        code, out = self.run_pass("--compact", "--foreground")
        self.assertEqual(code, 0, out)
        # No stamp file inside: the hook's shim reads an empty dir as "nothing to inject".
        self.assertEqual(sorted(os.listdir(notices)), ["b.json.13.taken", "new.json"])


class Lane(Base):
    init_lanes = True

    def setUp(self):
        super().setUp()
        self.lane("new", "chart-fix", "--claim", "42")
        self.path = self.lane_path("chart-fix")
        self.session_cwd = self.path
        self.write_session({"status": "busy"})
        self.say(typed("the prompt that ran /pass"))
        self.hook("lane-identity.sh", {"session_id": SID, "cwd": self.path,
                                       "source": "startup", "hook_event_name": "SessionStart"})
        self.body = self.read(self.record("chart-fix")).replace(
            "## Next\n", "## Next\n- Write the axis test for #42, then run it.\n")
        time.sleep(1.05)
        self.write(self.record("chart-fix"), self.body)

    PROMPT = "Read your lane record .lane/STATUS.md, then plan the next step."

    def respawn(self, *mode, prompt=None):
        return [self.tmux, "respawn-pane", "-k", "-t", "%4", "-c", self.path, "--", self.claude,
                *mode, prompt or self.PROMPT]

    def test_print_in_a_lane_names_the_lane_record(self):
        code, out = self.run_pass("--print", cwd=self.path)
        self.assertEqual(code, 0, out)
        self.assertIn(shlex.join(self.respawn("--permission-mode", "plan")), out.splitlines())

    def test_compact_in_a_lane_points_the_focus_at_the_record(self):
        code, out = self.run_pass("--compact", "--print", cwd=self.path)
        self.assertEqual(code, 0, out)
        self.assertIn(shlex.join([self.tmux, "send-keys", "-t", "%4", "-l",
                                  f"/compact {self.mod.compact_focus('.lane/STATUS.md')}"]),
                      out.splitlines())
        self.assertIn(self.PROMPT + " Call EnterPlanMode first.", out)

    def test_the_waiter_in_a_lane_respawns(self):
        code, out = self.run_pass("--foreground", cwd=self.path)
        self.assertEqual(code, 0, out)
        (respawn,) = self.calls("tmux", "respawn-pane")
        self.assertEqual(respawn[1:], self.respawn("--permission-mode", "plan")[1:])
        self.assertTrue(os.path.exists(self.carry_marker()))

    def test_an_approved_lane_respawns_in_the_default_mode(self):
        self.write(self.record("chart-fix"), self.body.replace(
            "then run it.", f"then run it (approved by Hayden {TODAY})."))
        code, out = self.run_pass("--foreground", cwd=self.path)
        self.assertEqual(code, 0, out)
        (respawn,) = self.calls("tmux", "respawn-pane")
        go = "Read your lane record .lane/STATUS.md, then continue with the approved next step."
        self.assertEqual(respawn[1:], self.respawn(prompt=go)[1:])

    def test_the_waiter_in_a_lane_compacts(self):
        code, out = self.run_pass("--compact", "--foreground", cwd=self.path)
        self.assertEqual(code, 0, out)
        keys = [a[-1] for a in self.calls("tmux", "send-keys")]
        self.assertEqual(keys, [f"/compact {self.mod.compact_focus('.lane/STATUS.md')}", "Enter",
                                self.PROMPT + " Call EnterPlanMode first.", "Enter"])

    def test_an_edit_in_the_lane_after_the_call_drops_stale(self):
        plan = self.plan(cwd=self.path)
        self.write(os.path.join(self.path, "late.txt"), "x")
        self.assertEqual(self.mod.wait_and_act(plan, table), "stale")
        self.assertDropped("stale", "handoff is stale")

    def test_background_work_in_a_lane_drops_busy(self):
        self.stop_tasks = ["monitor"]
        code, out = self.run_pass("--foreground", cwd=self.path)
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", "1 monitor running")
        self.assertFalse(os.path.exists(self.carry_marker()))

    def test_a_planted_lane_path_never_reaches_argv_or_keys(self):
        # lane.json is sandbox-writable. Its path may be a link to the lane named with shell
        # syntax and a newline: identity still matches (it resolves to the lane), but the
        # prompt and focus must carry only the computed .lane/STATUS.md.
        evil = os.path.join(self.tmp, "$(touch pwned)\nx")
        os.symlink(self.path, evil)
        lane_json = os.path.join(self.common, "lanes", "chart-fix", "lane.json")
        rec = self.lane_json("chart-fix")
        rec["path"] = evil
        self.write(lane_json, json.dumps(rec))
        for mode in ((), ("--compact",)):
            self.reset()
            code, out = self.run_pass(*mode, "--print", cwd=self.path)
            self.assertEqual(code, 0, out)
            self.assertNotIn("pwned", out)
        self.reset()
        self.assertEqual(self.mod.wait_and_act(self.plan(cwd=self.path), table), "respawn")
        respawns = self.calls("tmux", "respawn-pane")
        self.reset()
        self.assertEqual(self.mod.wait_and_act(self.plan("--compact", cwd=self.path), table),
                         "compact")
        keys = self.calls("tmux", "send-keys")
        self.assertNoTypedPath(respawns + keys)
        self.assertEqual(len(respawns), 1)
        self.assertTrue(any(".lane/STATUS.md" in a[-1] for a in keys))


class Units(unittest.TestCase):
    """The pieces that read the kernel and Claude Code's files."""

    def setUp(self):
        self.mod = load()
        self.dir = __import__("tempfile").mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_a_refusal_names_a_task_of_every_label(self):
        # The labels stop-ring.sh records (2.1.296's friendly names, an internal name for an
        # unmapped type, `unlabeled`); stop-ring's waits take the waits branch.
        plan = types.SimpleNamespace(session_id="s1", called=0)
        waits = {"subagent", "shell", "workflow", "cloud session"}
        for label in ("subagent", "shell", "monitor", "workflow", "cloud session", "teammate",
                      "MCP task", "auto-mode scan", "memory import", "unlabeled", "local_bash"):
            with self.subTest(label=label):
                rec = {"time": 1.0, "waits": [label] if label in waits else [],
                       "tasks": [{"label": label, "id": "t1", "description": "its job"}]}
                detail, notice = self.mod.stop_problem(plan, rec)
                noun = "unlabeled task" if label == "unlabeled" else label
                self.assertIn(f'{noun} "its job" (t1)', notice)
                self.assertIn(f'{noun} "its job" (t1)', detail)
                self.assertTrue(detail.startswith("waits: " if label in waits else "tasks: "))
        for tasks in ([{"label": "dream", "id": "d1"}], [WATCH], []):
            self.assertIsNone(self.mod.stop_problem(plan, {"time": 1.0, "waits": [],
                                                           "tasks": tasks}))

    def test_the_stop_record_is_read_as_utf8_in_any_locale(self):
        # stop_ring.py writes it as UTF-8. The C locale with Python's UTF-8 mode and coercion off
        # reads files as ASCII by default.
        stops = os.path.join(self.dir, "dotclaude", "stops")
        os.makedirs(stops)
        with open(os.path.join(stops, "s1.json"), "w", encoding="utf-8") as f:
            json.dump({"replies": [{"prompt_id": "p1", "text": "caf" + chr(0x00E9)}]}, f,
                      ensure_ascii=False)
        code = ("from importlib.machinery import SourceFileLoader\n"
                "from importlib.util import module_from_spec, spec_from_loader\n"
                f"loader = SourceFileLoader('pr', {SCRIPT!r})\n"
                "mod = module_from_spec(spec_from_loader('pr', loader))\n"
                "loader.exec_module(mod)\n"
                "print(ascii(mod.stop_record('s1')['replies'][0]['text']))\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "TMUX"))}
        env.update(LC_ALL="C", LANG="C", PYTHONCOERCECLOCALE="0", XDG_STATE_HOME=self.dir)
        p = subprocess.run([sys.executable, "-X", "utf8=0", "-c", code], capture_output=True,
                           text=True, timeout=20, env=env)
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "'caf\\xe9'"), p.stderr)

    def test_the_sessions_claude_is_the_nearest_claude_ancestor(self):
        self.assertEqual(self.mod.session_claude(table(), os.getpid()), CLAUDE)
        self.assertIsNone(self.mod.session_claude(table(claude=False), os.getpid()))
        self.assertIsNone(self.mod.session_claude({5: ("zsh", 6), 6: ("zsh", 5)}, 5))  # a cycle

    def stat(self, rows):
        for pid, stat in rows:
            os.makedirs(os.path.join(self.dir, pid))
            with open(os.path.join(self.dir, pid, "stat"), "w") as f:
                f.write(stat)

    def test_proc_table_reads_comm_and_ppid(self):
        self.stat((("123", "123 (odd (name) x) S 45 1 1 0"), ("7", "7 (claude) S 1 7 7"),
                   ("self", "1 (x) S 0"), ("99", "garbage")))
        self.assertEqual(self.mod.proc_table(self.dir),
                         {123: ("odd (name) x", 45), 7: ("claude", 1)})

    def test_proc_start_reads_field_22_and_a_zombie_has_none(self):
        tail = " ".join(str(n) for n in range(4, 22))  # fields 4..21, then starttime
        self.stat((("10", f"10 (cl aude) S {tail} 98765 0 0"),
                   ("11", f"11 (claude) Z {tail} 555 0 0")))
        self.assertEqual(self.mod.proc_start(10, self.dir), 98765)
        self.assertIsNone(self.mod.proc_start(11, self.dir))
        self.assertIsNone(self.mod.proc_start(12, self.dir))

    def test_the_transcript_path_follows_the_session(self):
        with mock.patch.dict(os.environ, {"HOME": self.dir}):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            self.assertEqual(self.mod.transcript_path({"cwd": "/a/b.c_d"}, "s1"),
                             os.path.join(self.dir, ".claude", "projects", "-a-b-c-d", "s1.jsonl"))
            self.assertEqual(self.mod.transcript_path({"cwd": "/a", "transcript_path": "/t.jsonl"},
                                                      "s1"), "/t.jsonl")
            self.assertIsNone(self.mod.transcript_path({}, "s1"))

    def test_typed_since_scans_only_past_the_offset(self):
        path = os.path.join(self.dir, "t.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps(typed("before")) + "\n")
        size = os.path.getsize(path)
        self.assertFalse(self.mod.typed_since(path, size))
        self.assertTrue(self.mod.typed_since(path, 0))
        with open(path, "a") as f:
            f.write(json.dumps(typed("after")) + "\n")
        self.assertTrue(self.mod.typed_since(path, size))
        self.assertFalse(self.mod.typed_since(os.path.join(self.dir, "none"), 0))


if __name__ == "__main__":
    unittest.main()
