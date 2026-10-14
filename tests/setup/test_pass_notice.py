"""hooks/pass-notice.sh and hooks/pass_notice.py: a dropped /pass's notice reaches the session's
next turn start or main-thread tool call, once (stdlib only).

pass-respawn's waiter writes $XDG_STATE_HOME/dotclaude/pass-notice/<session>.json at every drop:
{"v": 1, "session_id", "outcome", "mode", "called", "dropped", "text"}. Each test has its own
HOME and XDG_STATE_HOME, and the env starts scrubbed of CLAUDE* and TMUX*, since the test may run
inside a Claude tab. The shim runs end to end (every run must exit 0 with nothing on stderr);
the module is also loaded in-process for the parts a shim can't reach."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, "hooks")
SHIM = os.path.join(HOOKS, "pass-notice.sh")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HOOKS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pn = load("pass_notice")

SID = "5e2f0c1a-aaaa-bbbb-cccc-000000000001"
OTHER = "5e2f0c1a-aaaa-bbbb-cccc-000000000002"
# Quotes, a newline and a non-ASCII character: the text must reach the model as written.
TEXT = ('[pass] The pass you queued at 18:20Z (compact) was dropped: timeout: the turn hadn\'t '
        'ended after 600 s.\nNo pass is pending now. Rerun it once the "agents" finish. '
        'Tell Hayden in one line. ' + chr(0x2713))
# A stub python3 that records each run, so a test can prove the shim never started Python.
PY_STUB = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$PY_RAN"\ncat >/dev/null\n'


def notice(**over):
    n = {"v": 1, "session_id": SID, "outcome": "timeout", "mode": "compact",
         "called": 1791222100, "dropped": 1791222700, "text": TEXT}
    n.update(over)
    return n


def payload(event="UserPromptSubmit", sid=SID, **extra):
    """An event shaped like Claude Code's (2.1.300)."""
    d = {"session_id": sid, "transcript_path": "/home/u/.claude/projects/p/%s.jsonl" % sid,
         "cwd": "/home/u/code/dna", "permission_mode": "default", "hook_event_name": event}
    if event == "UserPromptSubmit":
        d["prompt"] = "go on"
    elif event == "PostToolUse":
        d.update(tool_name="Bash", tool_input={"command": "ls", "description": "List files"},
                 tool_response={"stdout": "a\n", "stderr": "", "interrupted": False,
                                "isImage": False},
                 tool_use_id="toolu_01")
    d.update(extra)
    return d


def read(path):
    with open(path, "rb") as f:
        return f.read()


def said(event, text=TEXT):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.state = os.path.join(self.tmp, "state")
        self.dir = os.path.join(self.state, "dotclaude", "pass-notice")
        self.err = os.path.join(self.state, "dotclaude", "pass-notice.err")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(HOME=self.home, XDG_STATE_HOME=self.state)
        patch = mock.patch.dict(os.environ, {"HOME": self.home, "XDG_STATE_HOME": self.state})
        patch.start()
        self.addCleanup(patch.stop)

    # ---- fixtures ----
    def write(self, data, sid=SID, name=None):
        """A notice file: data is a dict (written as JSON), a str or bytes."""
        os.makedirs(self.dir, exist_ok=True)
        path = os.path.join(self.dir, name or sid + ".json")
        if isinstance(data, dict):
            data = json.dumps(data)
        with open(path, "wb") as f:
            f.write(data.encode() if isinstance(data, str) else data)
        return path

    def files(self):
        return sorted(os.listdir(self.dir)) if os.path.isdir(self.dir) else []

    def run_shim(self, d, env=None, shim=SHIM, cwd=None):
        """The shim's stdout for event d (a dict, or raw text). It must exit 0 and print nothing
        to stderr."""
        p = subprocess.run(["bash", shim], input=d if isinstance(d, str) else json.dumps(d),
                           capture_output=True, text=True, timeout=20, env=env or self.env,
                           cwd=cwd or self.tmp)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        return p.stdout

    def out(self, d, **kw):
        """The shim's output parsed, or None when it printed nothing."""
        s = self.run_shim(d, **kw)
        return json.loads(s) if s else None

    def stub_python(self):
        """Put a recording python3 first on PATH; returns the record's path."""
        stubs = os.path.join(self.tmp, "stubs")
        os.makedirs(stubs, exist_ok=True)
        with open(os.path.join(stubs, "python3"), "w") as f:
            f.write(PY_STUB)
        os.chmod(os.path.join(stubs, "python3"), 0o755)
        ran = os.path.join(self.tmp, "py-ran")
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], PY_RAN=ran)
        return ran


class SaysItOnce(Base):
    def test_a_prompt_gets_the_notice_once(self):
        self.write(notice())
        self.assertEqual(self.out(payload("UserPromptSubmit")), said("UserPromptSubmit"))
        self.assertEqual(self.files(), [])  # claimed and deleted, no .taken left
        self.assertIsNone(self.out(payload("UserPromptSubmit")))
        self.assertEqual(read(self.err), b"")  # the shim's redirect makes it; nothing went wrong

    def test_a_main_thread_tool_call_gets_the_notice_once(self):
        self.write(notice())
        self.assertEqual(self.out(payload("PostToolUse")), said("PostToolUse"))
        self.assertEqual(self.files(), [])
        self.assertIsNone(self.out(payload("PostToolUse")))

    def test_an_agent_hand_back_or_task_notice_gets_it(self):
        # They reach the session as UserPromptSubmit prompts with no agent_id: the turn they
        # start is the session's next turn, so the notice belongs there.
        for prompt in ("<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>",
                       "[agent-handback] writer: done"):
            with self.subTest(prompt=prompt[:20]):
                self.write(notice())
                self.assertEqual(self.out(payload(prompt=prompt)), said("UserPromptSubmit"))

    def test_the_state_dir_defaults_under_home(self):
        # The shim and the module agree on the fallback, as pass-respawn's waiter writes it.
        self.env.pop("XDG_STATE_HOME")
        self.dir = os.path.join(self.home, ".local", "state", "dotclaude", "pass-notice")
        self.write(notice())
        self.assertEqual(self.out(payload()), said("UserPromptSubmit"))
        self.assertEqual(self.files(), [])

    def test_racing_hooks_say_it_once(self):
        # A prompt's hooks and a tool call's can run at once: the rename lets exactly one claim.
        self.write(notice())
        procs = [subprocess.Popen(["bash", SHIM], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=self.env, cwd=self.tmp)
                 for _ in range(8)]
        for p in procs:  # every hook gets its event before any is read, so they overlap
            p.stdin.write(json.dumps(payload("PostToolUse")))
            p.stdin.close()
        outs = [(p.stdout.read(), p.stderr.read()) for p in procs]
        for p in procs:
            p.stdout.close()
            p.stderr.close()
            p.wait(timeout=20)
        self.assertEqual([p.returncode for p in procs], [0] * 8)
        self.assertEqual([e for _, e in outs], [""] * 8)
        self.assertEqual([json.loads(o) for o, _ in outs if o], [said("PostToolUse")])
        self.assertEqual(self.files(), [])

    def test_long_text_is_capped(self):
        text = "a" * (pn.CAP - 10) + "b" * 20
        self.write(notice(text=text))
        self.assertEqual(pn.CAP, 4000)
        self.assertEqual(self.out(payload()), said("UserPromptSubmit", text[:4000]))

    def test_the_shim_finds_the_module_through_its_installed_link(self):
        # setup.sh links hooks/pass-notice.sh into ~/.claude/hooks/; the .py stays beside the
        # real path.
        link = os.path.join(self.home, ".claude", "hooks", "pass-notice.sh")
        os.makedirs(os.path.dirname(link))
        os.symlink(SHIM, link)
        self.write(notice())
        self.assertEqual(self.out(payload(), shim=link), said("UserPromptSubmit"))

    def test_a_projects_json_py_never_runs(self):
        # The hook runs in the project's directory; python3 -I keeps it off the import path.
        ran = os.path.join(self.tmp, "ran")
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(proj)
        with open(os.path.join(proj, "json.py"), "w") as f:
            f.write(f"open({ran!r}, 'a').write(__name__)\n")
        self.write(notice())
        self.assertEqual(self.out(payload(), cwd=proj), said("UserPromptSubmit"))
        self.assertFalse(os.path.exists(ran))


class NoPython(Base):
    """With no *.json in pass-notice/, the common case, the shim never starts Python (FastPath
    has the case of another session's notice)."""

    def test_no_notice_starts_no_python(self):
        ran = self.stub_python()
        cases = {"missing dir": lambda: None,
                 "empty dir": lambda: os.makedirs(self.dir, exist_ok=True),
                 # a racing hook's claimed file, and names that aren't notices
                 "no json": lambda: [self.write(notice(), name=n) for n in
                                     (SID + ".json.4242.taken", "x.json.tmp", "notes.txt")]}
        for case, make in cases.items():
            with self.subTest(case=case):
                make()
                for event in ("UserPromptSubmit", "PostToolUse"):
                    self.assertEqual(self.run_shim(payload(event)), "")
                self.assertFalse(os.path.exists(ran), case)

    def test_a_notice_starts_it_isolated(self):
        # The control for the case above: the stub does run once a notice is there.
        ran = self.stub_python()
        self.write(notice())
        self.assertEqual(self.run_shim(payload()), "")
        with open(ran) as f:
            self.assertEqual(f.read(), "-I %s\n" % os.path.realpath(
                os.path.join(HOOKS, "pass_notice.py")))


def spaced(d):
    """d as JSON with blanks around every colon and a newline after every comma."""
    return json.dumps(d, separators=(",\n", " :\t "))


def runs(ran):
    """How many times the stub python3 ran."""
    return len(read(ran).splitlines()) if os.path.exists(ran) else 0


class FastPath(Base):
    """The shim reads the payload's session id itself (Claude Code writes session_id first), so
    a notice no event will claim (a `gone` after /clear or exit) costs other sessions no
    Python. With no plain id found, Python decides."""

    def setUp(self):
        super().setUp()
        self.real = dict(self.env)  # without the stub, to see the notice said
        self.ran = self.stub_python()

    def test_another_sessions_notice_starts_no_python_here(self):
        self.write(notice(session_id=OTHER), sid=OTHER)
        for event in ("UserPromptSubmit", "PostToolUse"):
            for raw in (json.dumps(payload(event)), spaced(payload(event))):
                with self.subTest(event=event, raw=raw[:30]):
                    self.assertEqual(self.run_shim(raw), "")
        self.assertEqual(runs(self.ran), 0)
        self.assertEqual(self.files(), [OTHER + ".json"])

    def test_this_sessions_notice_is_still_said(self):
        self.write(notice(session_id=OTHER), sid=OTHER)
        self.write(notice())
        self.assertEqual(self.run_shim(payload()), "")
        self.assertEqual(runs(self.ran), 1)  # the stub ran: the fast path let it through
        self.assertEqual(self.out(payload(), env=self.real), said("UserPromptSubmit"))
        self.assertEqual(self.files(), [OTHER + ".json"])

    def test_blanks_around_the_colon_still_find_the_id(self):
        self.write(notice(session_id=OTHER), sid=OTHER)
        self.assertEqual(self.run_shim(spaced(payload("PostToolUse"))), "")
        self.assertEqual(runs(self.ran), 0)
        self.write(notice())
        self.assertEqual(self.out(spaced(payload("PostToolUse")), env=self.real),
                         said("PostToolUse"))

    def test_a_later_session_id_in_the_payload_is_not_taken(self):
        # A prompt that quotes one arrives escaped; a tool's own session_id key arrives as a
        # real key. Either way the first, Claude Code's, is the one.
        later = [payload(prompt='see "session_id":"%s" in the log' % OTHER),
                 payload("PostToolUse", tool_name="TaskStop", tool_input={"session_id": OTHER})]
        self.write(notice(session_id=OTHER), sid=OTHER)
        for d in later:
            self.assertEqual(self.run_shim(d), "")
        self.assertEqual(runs(self.ran), 0)
        for d in later:
            self.write(notice())
            self.assertEqual(self.out(d, env=self.real),
                             said(d["hook_event_name"]))
        self.assertEqual(self.files(), [OTHER + ".json"])

    def test_with_no_plain_id_found_python_decides(self):
        # Fail toward delivery: Python parses the JSON for real. A JSON escape in the key or the
        # value hides the id from the shim but not from json.loads.
        bs = chr(92)
        key = json.dumps(payload()).replace('"session_id"', '"session' + bs + 'u005fid"', 1)
        value = json.dumps(payload()).replace('"%s"' % SID, '"%su0035%s"' % (bs, SID[1:]), 1)
        no_id = json.dumps({k: v for k, v in payload().items() if k != "session_id"})
        self.write(notice(session_id=OTHER), sid=OTHER)
        for raw in (key, value, no_id):
            self.assertEqual(self.run_shim(raw), "")
        self.assertEqual(runs(self.ran), 3)
        for raw in (key, value):
            with self.subTest(raw=raw[:30]):
                self.write(notice())
                self.assertEqual(self.out(raw, env=self.real), said("UserPromptSubmit"))
        self.assertEqual(self.files(), [OTHER + ".json"])

    def test_a_symlinked_notice_still_reaches_python_to_be_deleted(self):
        # A dangling link fails `-e`; the shim must not leave it for the prune.
        os.makedirs(self.dir)
        os.symlink(os.path.join(self.tmp, "gone.json"), os.path.join(self.dir, SID + ".json"))
        self.assertIsNone(self.out(payload(), env=self.real))
        self.assertEqual(self.files(), [])


class LeftForLater(Base):
    """Events the notice isn't for leave it in place for one that is."""

    def test_another_sessions_notice_is_left_alone(self):
        path = self.write(notice(session_id=OTHER), sid=OTHER)
        before = read(path)
        for event in ("UserPromptSubmit", "PostToolUse"):
            self.assertIsNone(self.out(payload(event)))
        self.assertEqual(self.files(), [OTHER + ".json"])
        self.assertEqual(read(path), before)

    def test_a_subagent_payload_says_nothing_and_leaves_the_file(self):
        self.write(notice())
        for event in ("UserPromptSubmit", "PostToolUse"):
            for agent in ("a1b2c3", ""):
                with self.subTest(event=event, agent=agent):
                    self.assertIsNone(self.out(payload(event, agent_id=agent,
                                                       agent_type="writer")))
        self.assertEqual(self.files(), [SID + ".json"])

    def test_other_events_leave_the_file(self):
        self.write(notice())
        for event in ("Stop", "SessionStart", "PreToolUse", "Notification", None):
            with self.subTest(event=event):
                self.assertIsNone(self.out(payload(event)))
        self.assertEqual(self.files(), [SID + ".json"])

    def test_a_session_id_that_isnt_a_plain_name_is_skipped(self):
        self.write(notice())
        os.makedirs(os.path.join(self.state, "dotclaude"), exist_ok=True)
        outside = os.path.join(self.state, "dotclaude", "evil.json")
        with open(outside, "w") as f:
            json.dump(notice(session_id="../evil"), f)
        for sid in ("", "../evil", ".hidden", "a/b", "a b", "x" * 129, 123, None,
                    SID + "\n"):
            with self.subTest(sid=sid):
                self.assertIsNone(self.out(payload(sid=sid)))
        self.assertEqual(self.files(), [SID + ".json"])
        self.assertTrue(os.path.exists(outside))

    def test_a_bad_payload_says_nothing(self):
        self.write(notice())
        for raw in ("", "not json", "[1, 2]", '"UserPromptSubmit"', "{"):
            with self.subTest(raw=raw):
                self.assertEqual(self.run_shim(raw), "")
        self.assertEqual(self.files(), [SID + ".json"])


class DroppedUnsaid(Base):
    """A notice that breaks the contract is deleted without a word to the session."""

    BAD = {
        "another session's id inside": notice(session_id=OTHER),
        "no session id": {k: v for k, v in notice().items() if k != "session_id"},
        "v 2": notice(v=2),
        "v as a string": notice(v="1"),
        "v true": notice(v=True),
        "v 1.0": notice(v=1.0),
        "no v": {k: v for k, v in notice().items() if k != "v"},
        "empty text": notice(text=""),
        "blank text": notice(text=" \n\t"),
        "text not a string": notice(text=["dropped"]),
        "no text": {k: v for k, v in notice().items() if k != "text"},
        "not json": "the pass was dropped",
        "an empty file": b"",
        "a json array": json.dumps([notice()]),
        "a json string": json.dumps(TEXT),
        "json null": "null",
        "not utf-8": json.dumps(notice(text="caf" + chr(0xe9)), ensure_ascii=False).encode("latin-1"),
        "deep nesting": "[" * 50000 + "]" * 50000,
        "over 64 KiB": json.dumps(notice(text="x" * (64 * 1024))),
    }

    def test_a_bad_notice_is_deleted_unsaid(self):
        for case, data in self.BAD.items():
            for event in ("UserPromptSubmit", "PostToolUse"):
                with self.subTest(case=case, event=event):
                    self.write(data)
                    self.assertIsNone(self.out(payload(event)))
                    self.assertEqual(self.files(), [])
        with open(self.err) as f:
            log = f.read()
        # One line per dropped notice, naming the session; never the notice's own text.
        self.assertEqual(len(log.splitlines()), 2 * len(self.BAD))
        self.assertTrue(all(SID in line for line in log.splitlines()))
        self.assertNotIn("the pass was dropped", log)

    def test_a_symlinked_notice_is_deleted_unread(self):
        target = os.path.join(self.tmp, "real.json")
        with open(target, "w") as f:
            json.dump(notice(), f)
        before = read(target)
        for dest in (target, os.path.join(self.tmp, "gone.json")):
            with self.subTest(dest=dest):
                os.makedirs(self.dir, exist_ok=True)
                os.symlink(dest, os.path.join(self.dir, SID + ".json"))
                self.assertIsNone(self.out(payload()))
                self.assertEqual(self.files(), [])
        self.assertEqual(read(target), before)  # the target is never touched

    def test_a_fifo_is_dropped_without_waiting(self):
        # Opening a FIFO to read blocks until a writer comes; the hook must not hang on one.
        os.makedirs(self.dir)
        os.mkfifo(os.path.join(self.dir, SID + ".json"))
        self.assertIsNone(self.out(payload()))
        self.assertEqual(self.files(), [])


class InProcess(Base):
    def handle(self, d):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = pn.handle(d)
        return out, err.getvalue()

    def test_a_taken_file_from_a_racing_hook_is_not_said_again(self):
        # The hook that renamed it says it and deletes it; this one finds no notice.
        taken = self.write(notice(), name=SID + ".json.4242.taken")
        self.assertEqual(self.handle(payload()), (None, ""))
        self.assertEqual(self.files(), [os.path.basename(taken)])  # the other hook's to delete

    def test_the_claim_is_a_rename_to_a_pid_named_file(self):
        self.write(notice())
        seen = []
        real = pn.read_notice

        def spy(path):
            seen.append((os.path.basename(path), self.files()))
            return real(path)

        with mock.patch.object(pn, "read_notice", spy):
            self.assertEqual(self.handle(payload()), (said("UserPromptSubmit"), ""))
        name = "%s.json.%d.taken" % (SID, os.getpid())
        self.assertEqual(seen, [(name, [name])])
        self.assertEqual(self.files(), [])

    def test_a_rename_that_fails_otherwise_says_nothing(self):
        # Not a lost race: main() logs it and fails open.
        self.write(notice())
        with mock.patch.object(pn.os, "rename", side_effect=PermissionError(13, "denied")):
            out = io.StringIO()
            err = io.StringIO()
            stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload()).encode()))
            with mock.patch.object(pn.sys, "stdin", stdin), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                pn.main()
        self.assertEqual(out.getvalue(), "")
        self.assertIn("PermissionError", err.getvalue())
        self.assertEqual(self.files(), [SID + ".json"])

    def test_the_text_is_cut_by_characters_not_bytes(self):
        text = chr(0xe9) * (pn.CAP + 5)
        self.write(notice(text=text))
        out, err = self.handle(payload("PostToolUse"))
        self.assertEqual(out, said("PostToolUse", chr(0xe9) * pn.CAP))
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
