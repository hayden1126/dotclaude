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
    the stop record stop-ring.sh would (self.stop_waits; None writes none).
  - /proc: proc_start is replaced, and a fake process table stands in for proc_table.
  - the transcript: a file under the fake $HOME/.claude/projects.
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
WATCH = {"label": "artifact watch", "id": "s8k2m4p6q", "url": URL,
         "description": f"live updates for artifact {URL} (comments sent to Claude)"}
DEPLOY = {"label": "monitor", "id": "b0fzd27l4", "description": "deploy events"}


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
        entry = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        self.write_session({"status": entry} if isinstance(entry, str) else entry)
        return self.real_load(pid)

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
        return open(path).read() if os.path.exists(path) else ""

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
                 "{not json", "", "[1, 2]",
                 self.prompt("p2", "the real one"))
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual([p.get("text") for p in self.written()["prompts"]], ["the real one"])

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
                 {"type": "assistant", "message": {"content": "ok"}}, "not json {")
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
                      f"ignored: artifact watch {URL} (s8k2m4p6q)", self.log())

    def test_an_artifact_watch_alone_lets_the_pass_respawn(self):
        # The Artifact tool's live watch: Claude Code hides it and nothing could stop it, so
        # the respawn ends it and pass.log names the page, for Hayden to watch it again.
        self.stop_tasks = [WATCH, {"label": "dream", "id": "d1"}]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls("tmux", "respawn-pane")), 1)
        self.assertIn(f"outcome=respawn plan mode; ignored: artifact watch {URL} (s8k2m4p6q)",
                      self.log())

    def test_an_artifact_watch_beside_a_monitor_is_left_out_of_the_notice(self):
        self.stop_tasks = [WATCH, DEPLOY]
        code, out = self.run_pass("--foreground")
        self.assertEqual(code, 1, out)
        self.assertDropped("busy", 'monitor "deploy events" (b0fzd27l4) running (a respawn '
                           "would kill it)")
        for m in self.notices():
            self.assertNotIn("artifact", m[-1])
        self.assertIn(f"; ignored: artifact watch {URL} (s8k2m4p6q)", self.log())

    def test_the_incident_now_respawns(self):
        # e7cc7b9a's Stops listed one task, the watch its Artifact publish armed, in 2.1.296's
        # payload shape; recorded the way stop-ring.sh now records it, it clears a plain pass.
        payload = [{"id": "s8k2m4p6q", "type": "monitor", "status": "running",
                    "description": f"live updates for artifact {URL} (comments sent to Claude)"}]
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
                     f"artifact watch {URL} (s8k2m4p6q): doesn't block a plain pass",
                     "dream (d1): doesn't block a plain pass", "teammate: blocks a plain pass"]:
            self.assertIn("\n  " + line + "\n", out)
        # Read-only: nothing shown, logged or queued.
        self.assertEqual((self.notices(), self.log()), ([], ""))
        self.assertFalse(os.listdir(os.path.join(self.state, "pass-pending"))
                         if os.path.isdir(os.path.join(self.state, "pass-pending")) else [])

    def test_tasks_with_no_record_or_task_list_says_so(self):
        code, out = self.run_pass("--tasks")
        self.assertEqual(code, 0, out)
        self.assertIn(f"no stop record for session {SID}", out)
        self.write(os.path.join(self.state, "stops", f"{SID}.json"),
                   json.dumps({"time": time.time(), "waits": []}))
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
