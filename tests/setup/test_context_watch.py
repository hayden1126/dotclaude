"""hooks/context-watch.sh, hooks/autopass_toggle.py and hooks/autopass_state.py: the autopass
context watcher, its tiers and the per-tab /autopass toggle (stdlib only).

Each test has its own HOME (for ~/.claude/settings.json and ~/.config/dotclaude/pass.toml) and
XDG_STATE_HOME, and a stub tmux on PATH that answers `display` with $STUB_SERVER (empty fails).
The env starts scrubbed of CLAUDE* and TMUX*, since the test may run inside a Claude tab. The
shims run end to end; the modules are also loaded in-process for the parts a shim can't reach.
Transcript lines copy the real entry shape (spike A3, Claude Code 2.1.296)."""
import contextlib
import fcntl
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from importlib.machinery import SourceFileLoader
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, "hooks")
WATCH = os.path.join(HOOKS, "context-watch.sh")
TOGGLE = os.path.join(HOOKS, "autopass_toggle.py")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HOOKS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cw = load("context_watch")
aps = cw.aps  # the module context_watch imported, so a patch reaches it
toggle_mod = load("autopass_toggle")

STUB = """#!/usr/bin/env bash
case "$1" in
  display|display-message)
    [ -n "${STUB_SERVER:-}" ] || exit 1
    printf '%s\\n' "$STUB_SERVER" ;;
esac
exit 0
"""
SOCKET = "/tmp/tmux-1000/my socket"
SERVER = f"1791222157 4321 {SOCKET}"
OTHER_SERVER = f"1791999999 9999 {SOCKET}"
TAB = {"socket": SOCKET, "server_start": 1791222157, "server_pid": 4321, "pane": "%7"}
IN_TAB = {"TMUX": "/tmp/tmux-1000/default,1,0", "TMUX_PANE": "%7"}
SID = "5e2f0c1a-aaaa-bbbb-cccc-000000000001"


def assistant(total, sidechain=False, text="ok"):
    """A main-chain assistant entry whose usage sums to total, shaped like a real one."""
    read = total // 2
    return {"parentUuid": "u-1", "isSidechain": sidechain, "userType": "external",
            "cwd": "/home/u/code/dna", "sessionId": SID, "version": "2.1.296",
            "gitBranch": "main", "type": "assistant", "uuid": "a-%d" % total,
            "timestamp": "2026-10-12T10:00:00.000Z", "requestId": "req_1",
            "message": {"id": "msg_1", "type": "message", "role": "assistant",
                        "model": "claude-opus-5-5", "content": [{"type": "text", "text": text}],
                        "stop_reason": "end_turn", "stop_sequence": None,
                        "usage": {"input_tokens": 2, "cache_creation_input_tokens":
                                  total - read - 2, "cache_read_input_tokens": read,
                                  "output_tokens": 131,
                                  "cache_creation": {"ephemeral_1h_input_tokens": total - read - 2,
                                                     "ephemeral_5m_input_tokens": 0},
                                  "service_tier": "standard"}}}


USER = {"parentUuid": "a-1", "isSidechain": False, "type": "user", "uuid": "u-2",
        "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                                 "content": "done"}]}}
SYSTEM = {"type": "system", "subtype": "stop_hook_summary", "isSidechain": False,
          "hookCount": 3, "uuid": "s-1"}
# A compact, as Claude Code writes it: the boundary, then the summary as a user entry. The
# boundary's postTokens leaves out the system prompt and tools (60-70k under the next real
# count), so it is no count.
BOUNDARY = {"parentUuid": None, "logicalParentUuid": "a-1", "isSidechain": False,
            "type": "system", "subtype": "compact_boundary", "content": "Conversation compacted",
            "isMeta": False, "level": "info", "uuid": "b-1",
            "compactMetadata": {"trigger": "manual", "preTokens": 521139, "postTokens": 42286}}
SUMMARY = {"parentUuid": "b-1", "isSidechain": False, "type": "user", "uuid": "u-3",
           "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
           "message": {"role": "user", "content": "This session is being continued from a "
                                                  "previous conversation ..."}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        stubs = os.path.join(self.tmp, "bin")
        os.mkdir(stubs)
        with open(os.path.join(stubs, "tmux"), "w") as f:
            f.write(STUB)
        os.chmod(os.path.join(stubs, "tmux"), 0o755)
        self.home = os.path.join(self.tmp, "home")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(os.path.join(self.home, ".claude"))
        self.transcript = os.path.join(self.tmp, "t.jsonl")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE", "TMUX")) and k != "XDG_CONFIG_HOME"}
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], HOME=self.home,
                        XDG_STATE_HOME=self.state, STUB_SERVER=SERVER,
                        CLAUDE_CODE_SESSION_ATTENDED="1")
        patch = mock.patch.dict(os.environ, {k: self.env[k] for k in
                                             ("PATH", "HOME", "XDG_STATE_HOME", "STUB_SERVER")})
        patch.start()
        self.addCleanup(patch.stop)
        # In-process calls see os.environ: scrub it like self.env (CLAUDE_CONFIG_DIR would
        # otherwise pick the live settings.json's window). The patch restores every key.
        for k in [k for k in os.environ if k.startswith(("CLAUDE", "TMUX"))]:
            os.environ.pop(k)
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.cwd = self.tmp  # not a git repo: no lane
        self.stop_record([], [])  # no background work: a tool call gets the plain texts

    # ---- fixtures ----
    def pass_toml(self, text):
        d = os.path.join(self.home, ".config", "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "pass.toml"), "w") as f:
            f.write(text)

    def on(self):
        self.pass_toml("autopass = true\n")

    def write_transcript(self, total, before=(), after=(SYSTEM,)):
        """A transcript whose last main-chain entry is the assistant's (its final reply is on
        disk, as at a Stop after spike A8's wait, or at a tool call)."""
        with open(self.transcript, "w") as f:
            for e in [*before, assistant(total), *after]:   # compact, as Claude Code writes
                f.write(json.dumps(e, separators=(",", ":")) + "\n")

    def append(self, *entries):
        with open(self.transcript, "a") as f:
            for e in entries:
                f.write(json.dumps(e, separators=(",", ":")) + "\n")

    def stop_at(self, total, *before):
        """A Stop after appending entries and then an assistant entry at total."""
        self.append(*before, assistant(total), SYSTEM)
        return self.stop()

    def write_ctx_window(self, win, sid=SID):
        d = os.path.join(self.state, "dotclaude", "ctx")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".json"), "w") as f:
            json.dump({"tokens": 1, "time": 1.0, "window": win}, f)

    def no_stop_record(self):
        os.unlink(os.path.join(self.state, "dotclaude", "stops", SID + ".json"))

    def stop_record(self, waits, tasks, age=5):
        d = os.path.join(self.state, "dotclaude", "stops")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, SID + ".json"), "w") as f:
            json.dump({"session_id": SID, "time": time.time() - age, "waits": waits,  # wall clock
                       "tasks": tasks}, f)

    # ---- running ----
    def run_shim(self, hook, payload, session=None):
        p = subprocess.run(["bash", hook], input=json.dumps(payload), capture_output=True,
                           text=True, timeout=20, env={**self.env, **(IN_TAB if session is None else session)},
                           cwd=self.tmp)
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        return json.loads(p.stdout) if p.stdout else None

    def event(self, event, total=None, session=None, **payload):
        if total is not None:
            self.write_transcript(total)
        body = {"session_id": SID, "hook_event_name": event, "transcript_path": self.transcript,
                "cwd": self.cwd, **payload}
        if event == "PostToolUse":
            body.setdefault("tool_name", "Bash")
        return self.run_shim(WATCH, body, session)

    def stop(self, total=None, **kw):
        return self.event("Stop", total, **kw)

    def tool(self, total=None, **kw):
        return self.event("PostToolUse", total, **kw)

    def ctx(self):
        return self.ctx_of(SID)

    def ctx_of(self, sid):
        with open(os.path.join(self.state, "dotclaude", "ctx", sid + ".json")) as f:
            return json.load(f)

    def has_ctx(self):
        return os.path.exists(os.path.join(self.state, "dotclaude", "ctx", SID + ".json"))


def text(key, n, c="567k", tasks=None):
    """A tier's text; with tasks (as the nudge names them), the note naming them: to the model,
    or to Hayden for an off-mode systemMessage."""
    note = "" if tasks is None else (cw.TASKS_SEEN if key.startswith("off") else cw.TASKS_NOTE)
    return cw.TEXTS[key].format(n=n, c=c) + note.format(tasks=tasks)


def block(key, n, tasks=None):
    return {"decision": "block", "reason": text(key, n, tasks=tasks)}


def context(key, n, tasks=None):
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "additionalContext": text(key, n, tasks=tasks)}}


class Tiers(Base):
    def test_below_each_tier_nothing_is_said_but_the_count_is_written(self):
        self.on()
        self.assertIsNone(self.stop(299_999, session_id="s1"))
        self.assertEqual(self.ctx_of("s1")["tokens"], 299_999)
        self.assertIsNone(self.tool(479_999, session_id="s2"))     # past soft: Stop only
        # s3 has no stop record: its work is unknown, so the compact text
        self.assertEqual(self.tool(519_999, session_id="s3"), context("wrap_unknown", "520k"))
        self.assertIsNone(self.stop(299_999))
        self.assertEqual(self.ctx()["tokens"], 299_999)
        self.assertLess(time.time() - self.ctx()["time"], 30)  # wall clock

    def test_soft_fires_once_per_crossing_and_only_on_stop(self):
        self.on()
        self.assertIsNone(self.tool(310_000))      # soft never speaks on a tool call
        self.assertEqual(self.ctx()["tokens"], 310_000)
        self.assertEqual(self.stop(310_000), block("soft", "310k"))
        self.assertIsNone(self.stop(330_000))      # once
        self.assertIsNone(self.tool(400_000))

    def test_wrap_fires_on_a_tool_call_and_the_stop_does_not_repeat_it(self):
        self.on()
        self.assertEqual(self.tool(487_000), context("wrap", "487k"))
        self.assertIsNone(self.tool(490_000))
        self.assertIsNone(self.stop(495_000))

    def test_wrap_fires_on_stop_as_a_block(self):
        self.on()
        self.assertEqual(self.stop(481_000), block("wrap", "481k"))

    def test_hard_fires_and_re_arms_every_20k(self):
        self.on()
        self.assertEqual(self.stop(525_000), block("hard", "525k"))
        self.assertIsNone(self.tool(544_999))
        self.assertEqual(self.tool(545_000), context("hard", "545k"))
        self.assertIsNone(self.stop(560_000))
        self.assertEqual(self.stop(565_000), block("hard", "565k"))

    def test_only_the_highest_crossed_tier_speaks(self):
        self.on()
        self.assertEqual(self.stop(530_000), block("hard", "530k"))
        self.assertIsNone(self.stop(531_000))   # soft and wrap fired with it
        self.assertEqual(self.stop(490_000), None)  # under hard: re-armed, wrap still fired
        self.assertEqual(self.stop(500_000), None)

    def test_a_drop_re_arms(self):
        self.on()
        self.assertEqual(self.stop(310_000), block("soft", "310k"))
        self.assertIsNone(self.stop(60_000))     # a compact
        self.assertEqual(self.ctx()["tokens"], 60_000)
        self.assertEqual(self.stop(305_000), block("soft", "305k"))

    def test_a_new_session_id_is_a_new_record(self):
        self.on()
        self.assertEqual(self.stop(310_000), block("soft", "310k"))
        self.assertEqual(self.stop(311_000, session_id="other-session"), block("soft", "311k"))


class Off(Base):
    def test_off_says_only_the_hard_line_once_per_crossing(self):
        self.assertIsNone(self.stop(310_000))
        self.assertIsNone(self.tool(490_000))
        self.assertIsNone(self.stop(495_000))
        self.assertEqual(self.tool(521_000), {"systemMessage": text("off", "521k")})
        self.assertIsNone(self.stop(545_000))    # no +20k re-arm when off
        self.assertIsNone(self.tool(566_000))
        self.assertIsNone(self.stop(100_000))
        self.assertEqual(self.stop(522_000), {"systemMessage": text("off", "522k")})

    def test_off_with_background_tasks_says_pass_compact(self):
        self.assertEqual(self.stop(521_000, background_tasks=[{"type": "monitor"}]),
                         {"systemMessage": text("off_compact", "521k", tasks="monitor")})

    def test_pass_toml_follows_xdg_config_home(self):
        # A live test gives one session its own pass.toml without moving every other session's.
        conf = os.path.join(self.tmp, "conf")
        os.makedirs(os.path.join(conf, "dotclaude"))
        with open(os.path.join(conf, "dotclaude", "pass.toml"), "w") as f:
            f.write("autopass = true\ntiers = [100000, 150000, 200000]\n")
        self.assertEqual(aps.pass_toml(), {})
        os.environ["XDG_CONFIG_HOME"] = conf
        self.assertEqual(aps.pass_toml_path(), os.path.join(conf, "dotclaude", "pass.toml"))
        self.assertIs(aps.pass_toml()["autopass"], True)

    def test_pass_toml_false_is_off(self):
        self.pass_toml("autopass = false\n")
        self.assertIsNone(self.stop(310_000))


class Background(Base):
    def test_busy_on_stop_keeps_soft_and_wrap_quiet_and_armed(self):
        self.on()
        shell = [{"type": "shell", "id": "b1"}]
        self.assertIsNone(self.stop(310_000, background_tasks=shell))
        self.assertEqual(self.stop(312_000), block("soft", "312k"))
        self.assertIsNone(self.stop(485_000, background_tasks=[{"type": "subagent"}]))
        self.assertEqual(self.stop(486_000), block("wrap", "486k"))

    def test_busy_on_stop_gives_the_hard_tiers_busy_variant(self):
        self.on()
        self.assertEqual(self.stop(525_000, background_tasks=[{"type": "workflow"}]),
                         block("hard_busy", "525k", "workflow"))
        self.assertIsNone(self.stop(526_000))

    def test_monitor_only_tasks_say_compact_mode_at_every_tier(self):
        self.on()
        mon = [{"type": "monitor"}, {"type": "dream"}]
        self.assertEqual(self.stop(310_000, background_tasks=mon),
                         block("soft_compact", "310k", "monitor"))
        self.assertEqual(self.stop(481_000, background_tasks=mon),
                         block("wrap_compact", "481k", "monitor"))
        self.assertEqual(self.stop(521_000, background_tasks=mon),
                         block("hard_compact", "521k", "monitor"))

    def test_a_monitor_the_payload_calls_a_shell_still_lets_soft_speak(self):
        # Spike A10: the payload labels a Monitor `shell`. The transcript shows the Monitor
        # tool started it, so it blocks a plain pass (compact texts) but isn't busy work.
        started = [
            {"type": "assistant", "isSidechain": False, "message": {"content": [
                {"type": "tool_use", "id": "tu_m", "name": "Monitor", "input": {}}]}},
            {"type": "user", "isSidechain": False, "toolUseResult": {"taskId": "m1"},
             "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_m"}]}}]
        self.on()
        self.write_transcript(310_000, before=started)
        mon = [{"id": "m1", "type": "shell", "status": "running"}]
        self.assertEqual(self.stop(background_tasks=mon), block("soft_compact", "310k",
                                                                "monitor (m1)"))
        # A background Bash shell is still busy: soft stays quiet.
        self.write_transcript(320_000, before=started)
        sh = [{"id": "b1", "type": "shell", "status": "running"}]
        self.assertIsNone(self.stop(background_tasks=sh, session_id="other-session"))

    def test_teammates_and_unlabeled_tasks_block_a_plain_pass_too(self):
        self.on()
        self.assertEqual(self.stop(310_000, background_tasks=[{"id": "x"}]),
                         block("soft_compact", "310k", "unlabeled task (x)"))
        self.assertEqual(self.stop(481_000, background_tasks=[{"type": "teammate"}]),
                         block("wrap_compact", "481k", "teammate"))

    def test_dream_alone_is_no_background_work(self):
        self.on()
        self.assertEqual(self.stop(310_000, background_tasks=[{"type": "dream"}]),
                         block("soft", "310k"))

    def test_the_nudge_names_each_task_and_its_id(self):
        # Before the handoff the session stops what is done (pass skill step 2); the nudge
        # hands it each id, which a compaction may have taken. An artifact watch isn't named.
        self.on()
        tasks = [{"id": "b0fzd27l4", "type": "monitor", "status": "running",
                  "description": "deploy events"},
                 {"id": "b2", "type": "shell", "status": "running", "description": "npm run dev",
                  "command": "npm run dev -- --port 5222"},
                 {"id": "s1", "type": "monitor", "status": "running",
                  "description": "live updates for artifact https://claude.ai/artifact/x (c)"}]
        self.assertEqual(self.stop(525_000, background_tasks=tasks),
                         block("hard_busy", "525k", 'monitor "deploy events" (b0fzd27l4), '
                                                    'shell "npm run dev" (b2)'))
        # A tool call reads the same names from the stop record.
        self.stop_record(["shell"], [{"label": "shell", "id": "b2", "description": "npm run dev"}])
        self.assertEqual(self.tool(546_000),
                         context("hard_busy", "546k", 'shell "npm run dev" (b2)'))
        self.assertIn("TaskStop", cw.TASKS_NOTE)
        self.assertIn("ask Hayden", cw.TASKS_NOTE)

    def test_unreadable_waits_in_the_record_are_unknown_work(self):
        # Review round 1: waits that aren't a list made a tool call read the record as clear,
        # where pass-respawn refuses it.
        self.on()
        self.stop_record("shell", [])
        self.assertEqual(self.tool(485_000), context("wrap_unknown", "485k"))

    def test_without_lanelib_every_task_blocks(self):
        # The rule lives in lanelib; without it (a broken install, where pass-respawn can't
        # run either) no task can be shown safe, so the nudge says compact mode.
        self.write_transcript(310_000)
        watch = [{"id": "s1", "type": "monitor", "status": "running",
                  "description": "live updates for artifact https://claude.ai/artifact/x (c)"}]
        payload = {"session_id": SID, "hook_event_name": "Stop",
                   "transcript_path": self.transcript, "cwd": self.cwd,
                   "background_tasks": watch}
        with mock.patch.object(aps, "lanelib", return_value=None), \
                mock.patch.object(aps, "decide", return_value=(True, "pass.toml")):
            self.assertEqual(cw.handle(payload), block("soft_compact", "310k", "artifact watch"))

    def test_a_description_with_braces_reaches_the_nudge_as_text(self):
        # The names fill TASKS_NOTE as a value; a brace in one is never a format field.
        self.on()
        tasks = [{"id": "m1", "type": "monitor", "description": "watch {tasks} {0} {n}"}]
        self.assertIn('Running: monitor "watch {tasks} {0} {n}" (m1).',
                      self.stop(310_000, background_tasks=tasks)["reason"])

    def test_the_nudge_names_at_most_ten_tasks(self):
        self.on()
        tasks = [{"id": f"m{i}", "type": "monitor", "description": f"watch {i}"}
                 for i in range(12)]
        names = ", ".join(f'monitor "watch {i}" (m{i})' for i in range(cw.NUDGE_SHOWN))
        self.assertEqual(self.stop(310_000, background_tasks=tasks),
                         block("soft_compact", "310k", names + ", +2 more"))

    def test_an_artifact_watch_alone_is_no_background_work(self):
        # The Artifact tool's live watch: a plain pass ends it, so no compact advice for it.
        self.on()
        watch = [{"id": "s1", "type": "monitor", "status": "running",
                  "description": "live updates for artifact https://claude.ai/artifact/x (c)"}]
        self.assertEqual(self.stop(310_000, background_tasks=watch), block("soft", "310k"))
        self.stop_record([], [{"label": "artifact watch", "id": "s1",
                               "url": "https://claude.ai/artifact/x"}])
        self.assertEqual(self.tool(485_000), context("wrap", "485k"))

    def test_a_tool_call_reads_the_fresh_stop_record(self):
        self.on()
        self.stop_record(["subagent"], ["subagent"])
        self.assertIsNone(self.tool(485_000))                           # busy: wrap quiet
        self.assertEqual(self.tool(525_000), context("hard_busy", "525k", "subagent"))
        self.stop_record([], ["monitor"])
        self.assertEqual(self.tool(546_000), context("hard_compact", "546k", "monitor"))

    def test_a_tool_call_reads_monitor_only_tasks_as_compact_at_wrap(self):
        self.on()
        self.stop_record([], ["monitor"])
        self.assertEqual(self.tool(485_000), context("wrap_compact", "485k", "monitor"))

    def test_a_stale_stop_record_is_unknown_work_and_says_compact(self):
        self.on()
        self.stop_record(["shell"], ["shell"], age=601)
        self.assertEqual(self.tool(485_000), context("wrap_unknown", "485k"))

    def test_no_stop_record_is_unknown_work_and_says_compact(self):
        self.on()
        self.no_stop_record()
        self.assertEqual(self.tool(525_000), context("hard_unknown", "525k"))

    def test_off_with_unknown_work_says_pass_compact(self):
        self.no_stop_record()
        self.assertEqual(self.tool(525_000), {"systemMessage": text("off_unknown", "525k")})

    def test_a_stop_records_without_a_task_list_says_compact(self):
        self.on()
        d = os.path.join(self.state, "dotclaude", "stops", SID + ".json")
        with open(d, "w") as f:
            json.dump({"time": time.time(), "waits": []}, f)  # wall clock
        self.assertEqual(self.tool(485_000), context("wrap_unknown", "485k"))

    def test_the_plain_pass_rule_is_pass_respawns(self):
        # One definition: lanelib.plain_pass_blockers, which pass-respawn's stop_problem uses.
        lib = aps.lanelib()
        # A bare `artifact watch` label has no page: only stop_ring's match writes one.
        self.assertEqual(lib.plain_pass_blockers(["dream", "monitor", "unlabeled",
                                                  "artifact watch"]),
                         [{"label": "monitor"}, {"label": "unlabeled"},
                          {"label": "artifact watch"}])
        self.assertEqual(lib.plain_pass_blockers(None), [{"label": "?"}])
        with open(os.path.join(REPO, "skills", "pass", "scripts", "pass-respawn")) as f:
            self.assertIn("lanelib.plain_pass_blockers(tasks)", f.read())

    def test_a_pending_pass_silences_every_tier(self):
        self.on()
        d = os.path.join(self.state, "dotclaude", "pass-pending")
        os.makedirs(d)
        fd = os.open(os.path.join(d, SID + ".lock"), os.O_RDWR | os.O_CREAT)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.assertIsNone(self.stop(525_000))
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(self.stop(526_000), block("hard", "526k"))  # nothing was marked


class Skips(Base):
    def test_a_subagent_event_is_ignored(self):
        self.on()
        self.assertIsNone(self.stop(525_000, agent_id="a1", agent_type="writer"))
        self.assertFalse(self.has_ctx())

    def test_a_p_run_gets_its_count_but_no_nudge(self):
        self.on()
        self.assertIsNone(self.stop(525_000, session={**IN_TAB,
                                                       "CLAUDE_CODE_SESSION_ATTENDED": "0"}))
        self.assertEqual(self.ctx()["tokens"], 525_000)
        self.assertIsNone(self.tool(530_000, session={**IN_TAB,
                                                       "CLAUDE_CODE_SESSION_ATTENDED": "0"}))
        self.assertEqual(self.ctx()["tokens"], 530_000)
        self.assertFalse(os.path.exists(os.path.join(self.state, "dotclaude", "ctx-watch",
                                                     SID + ".json")))

    def test_a_background_session_gets_its_count_but_no_nudge(self):
        # `claude --bg`: no TMUX_PANE, ATTENDED=0, CLAUDE_JOB_DIR (probed on 2.1.289).
        self.on()
        bg = {"CLAUDE_CODE_SESSION_ATTENDED": "0", "CLAUDE_JOB_DIR": "/tmp/job"}
        self.assertIsNone(self.stop(525_000, session=bg))
        self.assertEqual(self.ctx()["tokens"], 525_000)
        self.assertEqual(self.stop(526_000), block("hard", "526k"))  # attended: nudged

    def test_a_session_id_that_is_not_plain_is_ignored(self):
        self.on()
        self.assertIsNone(self.stop(525_000, session_id="../evil"))
        self.assertFalse(os.path.exists(os.path.join(self.state, "dotclaude", "evil.json")))

    def test_a_transcript_parse_miss_says_nothing(self):
        self.on()
        with open(self.transcript, "w") as f:
            f.write("not json\n{\"type\": \"assistant\"}\n")
        self.assertIsNone(self.stop())
        self.assertFalse(self.has_ctx())
        self.assertIsNone(self.stop(transcript_path=os.path.join(self.tmp, "missing.jsonl")))
        self.assertIsNone(self.stop(transcript_path=7))
        self.assertIsNone(self.run_shim(WATCH, ["not", "a", "dict"]))
        p = subprocess.run(["bash", WATCH], input="{", capture_output=True, text=True,
                           env={**self.env, **IN_TAB})
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_a_line_too_deep_for_json_in_the_tail_is_skipped(self):
        # "[" * 100000: RecursionError in json, not ValueError. The line holds every needle
        # main_chain and starts_handoff look for, so both parse it.
        self.write_transcript(330_000)
        with open(self.transcript, "a") as f:
            f.write("[" * 100000 + ' "assistant" "tool_use" "Skill" pass-respawn\n')
        self.assertEqual(cw.tokens(self.transcript), 330_000)
        self.assertFalse(cw.handoff_since(self.transcript, 0))
        self.on()
        self.assertEqual(self.stop(), block("soft", "330k"))   # exits 0, empty stderr

    def test_sidechain_and_zero_usage_entries_do_not_count(self):
        zero = assistant(0)
        zero["message"]["model"] = "<synthetic>"
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            zero["message"]["usage"][k] = 0
        self.write_transcript(320_000, after=(USER, assistant(900_000, sidechain=True), zero))
        self.on()
        self.assertEqual(self.stop(), block("soft", "320k"))

    def test_a_large_line_after_the_entry_widens_the_read_once(self):
        big = dict(USER, toolUseResult={"stdout": "x" * (cw.TAIL + 1000)})
        self.write_transcript(330_000, after=(big,))
        self.assertEqual(cw.tokens(self.transcript), 330_000)
        huge = dict(USER, toolUseResult={"stdout": "x" * (cw.WIDE + 1000)})
        self.write_transcript(330_000, after=(huge,))
        self.assertIsNone(cw.tokens(self.transcript))   # past the widened read: quiet

    def test_the_last_entry_wins(self):
        self.write_transcript(41_538, before=(assistant(30_000), USER))
        self.assertEqual(cw.tokens(self.transcript), 41_538)


class Compact(Base):
    """Session 89ae7cc8 (2026-10-20): the first tool call after a /compact ran before its own
    assistant entry reached the transcript (batched writes), and the walk back passed the
    boundary to the pre-compact reply: "521k ... hand off now" at a real 107k."""

    def test_a_boundary_before_any_usage_is_no_count(self):
        quoted = dict(USER, toolUseResult={"stdout": '{"subtype":"compact_boundary"}'})
        big = dict(USER, toolUseResult={"stdout": "x" * (cw.TAIL + 1000)})
        cases = [((BOUNDARY, SUMMARY), (None, False)),
                 ((BOUNDARY,), (None, False)),
                 ((BOUNDARY, SUMMARY, USER), (None, False)),
                 ((BOUNDARY, SUMMARY, assistant(107_000)), (107_000, True)),
                 ((BOUNDARY, big), (None, False)),            # no widening past the boundary
                 ((dict(BOUNDARY, isSidechain=True), USER), (521_000, False)),
                 ((quoted,), (521_000, False))]               # only quotes the subtype
        for after, want in cases:
            self.write_transcript(521_000, after=after)
            self.assertEqual(cw.scan(self.transcript), want, after)

    def test_a_tool_call_right_after_a_compact_says_nothing_and_writes_nothing(self):
        self.on()
        self.write_transcript(525_000, after=(BOUNDARY, SUMMARY, USER))
        self.assertIsNone(self.tool())
        self.assertFalse(self.has_ctx())

    def test_sessionstart_compact_blanks_the_count_and_the_next_one_re_arms(self):
        self.on()
        self.write_ctx_window(600_000)
        self.assertEqual(self.stop(525_000), block("hard", "525k"))
        self.append(BOUNDARY, SUMMARY)
        self.assertIsNone(self.event("SessionStart", source="compact"))
        ctx = self.ctx()
        self.assertEqual((ctx["tokens"], ctx["window"]), (None, 600_000))
        self.assertIsNone(self.tool())                    # still no count: nothing written
        self.assertIsNone(self.ctx()["tokens"])
        self.append(assistant(107_000), USER)
        self.assertIsNone(self.tool())
        self.assertEqual(self.ctx()["tokens"], 107_000)
        with open(os.path.join(self.state, "dotclaude", "ctx-watch", SID + ".json")) as f:
            self.assertEqual(set(json.load(f)["fired"].values()), {None})
        self.assertEqual(self.stop(525_000), block("hard", "525k"))   # fires again

    def test_a_p_runs_count_is_blanked_too(self):
        # `lane ls` reads a `claude -p` or `--bg` session's count as well.
        bg = {**IN_TAB, "CLAUDE_CODE_SESSION_ATTENDED": "0"}
        self.stop(525_000, session=bg)
        self.assertIsNone(self.event("SessionStart", session=bg, source="compact"))
        self.assertIsNone(self.ctx()["tokens"])

    def test_sessionstart_other_than_compact_writes_nothing(self):
        for source in ("startup", "resume", "clear", None):
            self.assertIsNone(self.event("SessionStart", source=source))
        self.assertIsNone(self.event("SessionStart", source="compact", agent_id="a1"))
        self.assertIsNone(self.event("SessionStart", source="compact", session_id="../evil"))
        self.assertFalse(self.has_ctx())
        self.assertFalse(os.path.exists(os.path.join(self.state, "dotclaude", "evil.json")))


class StopWait(Base):
    """Spike A8: at a Stop the turn's final reply lands in the transcript about 100 ms into the
    hook, so the watcher waits for it rather than count the previous turn."""

    def payload(self, event="Stop"):
        return {"session_id": SID, "hook_event_name": event, "transcript_path": self.transcript,
                "cwd": self.cwd}

    def handle_landing(self, *entries, event="Stop"):
        """cw.handle, with entries appended right after the watcher's first read, so a pass
        means it read again (no race with a timer)."""
        real, calls = cw.scan, []

        def scan(path):
            out = real(path)
            calls.append(out)
            if len(calls) == 1:
                self.append(*entries)
            return out
        err = io.StringIO()
        with mock.patch.object(cw, "scan", scan), contextlib.redirect_stderr(err):
            out = cw.handle(self.payload(event))
        self.assertEqual(err.getvalue(), "")
        return out, calls

    def test_scan_says_whether_the_final_reply_is_on_disk(self):
        zero = assistant(0)
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            zero["message"]["usage"][k] = 0
        big = dict(USER, toolUseResult={"stdout": "x" * (cw.TAIL + 1000)})
        cases = [((SYSTEM,), (41_000, True)),
                 ((USER, SYSTEM), (41_000, False)),
                 ((USER, assistant(900_000, sidechain=True)), (41_000, False)),
                 ((USER, zero), (41_000, True)),   # a synthetic error reply ends the turn too
                 ((big,), (41_000, False))]        # a final user line past the first read
        for after, want in cases:
            self.write_transcript(41_000, after=after)
            self.assertEqual(cw.scan(self.transcript), want, after)
        with open(self.transcript, "w") as f:
            f.write(json.dumps(USER) + "\n")
        self.assertEqual(cw.scan(self.transcript), (None, False))
        open(self.transcript, "w").close()   # nothing in reach yet: the reply would be readable
        self.assertEqual(cw.scan(self.transcript), (None, False))
        # Unreadable: nothing will land there.
        self.assertEqual(cw.scan(os.path.join(self.tmp, "missing.jsonl")), (None, None))
        self.assertEqual(cw.scan(7), (None, None))

    def test_a_stop_waits_for_the_final_reply(self):
        self.on()
        self.write_transcript(200_000, after=(USER,))   # the turn's prompt, its reply not yet
        out, calls = self.handle_landing(assistant(320_000), SYSTEM)
        self.assertEqual(out, block("soft", "320k"))
        self.assertEqual(self.ctx()["tokens"], 320_000)
        self.assertEqual(calls[0], (200_000, False))

    def test_a_sessions_first_stop_gets_its_count(self):
        with open(self.transcript, "w") as f:
            f.write(json.dumps(USER) + "\n")
        out, _ = self.handle_landing(assistant(41_538))
        self.assertIsNone(out)
        self.assertEqual(self.ctx()["tokens"], 41_538)

    def test_a_tool_call_never_waits(self):
        self.write_transcript(41_000, after=(USER,))
        _, calls = self.handle_landing(assistant(60_000), event="PostToolUse")
        self.assertEqual((len(calls), self.ctx()["tokens"]), (1, 41_000))

    def test_an_unreadable_transcript_does_not_wait(self):
        err = io.StringIO()
        start = time.monotonic()
        with mock.patch.object(cw, "STOP_WAIT", 30), contextlib.redirect_stderr(err):
            for path in (os.path.join(self.tmp, "missing.jsonl"), 7):
                self.assertIsNone(cw.handle(dict(self.payload(), transcript_path=path)))
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(err.getvalue(), "")

    def test_a_stop_right_after_a_compact_waits_for_its_reply(self):
        self.write_transcript(521_000, after=(BOUNDARY, SUMMARY, USER))
        out, calls = self.handle_landing(assistant(107_000), SYSTEM)
        self.assertIsNone(out)
        self.assertEqual((calls[0], self.ctx()["tokens"]), ((None, False), 107_000))

    def test_a_stop_with_no_reply_after_a_compact_waits_then_says_nothing(self):
        # 5 of 344 real compacts had a Stop before any reply: it waits like any Stop, then
        # logs, and counts nothing rather than the pre-compact reply.
        self.on()
        self.write_transcript(525_000, after=(BOUNDARY, SUMMARY))
        self.assertIsNone(self.stop())
        self.assertFalse(self.has_ctx())
        with open(os.path.join(self.state, "dotclaude", "context-watch.err")) as f:
            self.assertIn("context-watch %s: no final reply in the transcript after 1.5 s; "
                          "no count" % SID, f.read())

    def test_a_reply_that_never_lands_logs_a_line_and_uses_the_previous_count(self):
        # End to end: the shim appends the line to context-watch.err, never to the session.
        self.on()
        self.write_transcript(320_000, after=(USER,))
        start = time.monotonic()
        self.assertEqual(self.stop(), block("soft", "320k"))
        self.assertGreaterEqual(time.monotonic() - start, cw.STOP_WAIT)
        with open(os.path.join(self.state, "dotclaude", "context-watch.err")) as f:
            self.assertIn("context-watch %s: no final reply in the transcript after 1.5 s; "
                          "used the previous reply's" % SID, f.read())


class Decide(Base):
    def flag(self, on, tab=TAB):
        aps.set_flag("%7", tab, on)

    def test_the_tab_flag_beats_everything(self):
        self.pass_toml("autopass = false\n")
        self.flag(True)
        self.assertEqual(aps.decide(self.cwd, "%7"), (True, "tab"))
        self.flag(False)
        with mock.patch.object(aps, "lane_setting", return_value=True):
            self.assertEqual(aps.decide(self.cwd, "%7"), (False, "tab"))

    def test_a_flag_from_another_server_is_ignored(self):
        self.flag(True)
        os.environ["STUB_SERVER"] = OTHER_SERVER
        self.assertEqual(aps.decide(self.cwd, "%7"), (False, "default"))
        self.assertEqual(aps.decide(self.cwd, "%8"), (False, "default"))  # another pane

    def test_the_lanes_config_beats_pass_toml(self):
        self.pass_toml("autopass = false\n")

        class Repo:
            def __init__(self, ident, config):
                self.ident, self.cfg = ident, config

            def identity(self):
                return self.ident, None

            def config(self):
                return self.cfg

        lib = aps.lanelib()
        cases = [(Repo("lane", {}), (True, "lanes")),
                 (Repo("lane", {"autopass": False}), (False, "lanes")),
                 (Repo("lane", {"autopass": "yes"}), (True, "lanes")),
                 (Repo("main", {}), (True, "lanes")),   # the lead passes itself too
                 (Repo("main", {"autopass": False}), (False, "lanes")),
                 (Repo("unregistered", {"autopass": True}), (False, "pass.toml")),
                 (Repo("plain", {"autopass": True}), (False, "pass.toml")),
                 (None, (False, "pass.toml"))]
        for repo, want in cases:
            with mock.patch.object(lib, "resolve", return_value=repo):
                self.assertEqual(aps.decide(self.cwd, None), want)

    def test_pass_toml_then_the_default(self):
        self.assertEqual(aps.decide(self.cwd, "%7"), (False, "default"))
        self.pass_toml("autopass = true\n")
        self.assertEqual(aps.decide(self.cwd, "%7"), (True, "pass.toml"))
        self.pass_toml('autopass = "on"\n')
        self.assertEqual(aps.decide(self.cwd, "%7"), (False, "default"))
        self.pass_toml("autopass = [\n")
        self.assertEqual(aps.decide(self.cwd, "%7"), (False, "default"))

    def test_a_real_git_checkout_without_lanes_is_not_a_lane(self):
        subprocess.run(["git", "init", "-q", self.cwd], check=True)
        self.assertIsNone(aps.lane_setting(self.cwd))

    def test_the_watcher_follows_the_tab_flag(self):
        self.flag(True)
        self.assertEqual(self.stop(310_000), block("soft", "310k"))


class TierValues(Base):
    def settings(self, value):
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as f:
            json.dump({"autoCompactWindow": value}, f)

    def test_the_default_tiers(self):
        self.assertEqual(aps.window(), 600_000)
        self.assertEqual(aps.tiers(), {"soft": 300_000, "wrap": 480_000, "hard": 520_000,
                                       "compact_at": 567_000})

    def test_the_window_comes_from_settings(self):
        self.settings(400_000)
        self.assertEqual(aps.tiers(), {"soft": 200_000, "wrap": 307_000, "hard": 335_000,
                                       "compact_at": 367_000})
        self.on()
        self.assertEqual(self.stop(336_000),
                         {"decision": "block", "reason": text("hard", "336k", "367k")})
        for garbage in (True, -5, "600000", None):
            self.settings(garbage)
            self.assertEqual(aps.window(), 600_000)

    def test_a_window_too_small_for_the_tiers_keeps_the_watcher_quiet(self):
        self.settings(100_000)
        self.assertIsNone(aps.tiers())
        self.on()
        self.assertIsNone(self.stop(90_000))
        self.assertEqual(self.ctx()["tokens"], 90_000)
        # wrap-up under 60k is quiet too, even with soft still under it
        self.assertEqual(aps.tiers(110_000, {})["wrap"], 60_500)
        self.assertIsNone(aps.tiers(109_000, {}))

    def test_small_windows_scale_the_margins(self):
        # compact_at = w - 33k, hard = compact_at - min(47k, 8% w), wrap = hard - min(40k,
        # 7% w), soft = w // 2: 600k is unchanged, a small window keeps room above its start.
        self.assertEqual(aps.tiers(600_000, {}), {"soft": 300_000, "wrap": 480_000,
                                                  "hard": 520_000, "compact_at": 567_000})
        self.assertEqual(aps.tiers(200_000, {}), {"soft": 100_000, "wrap": 137_000,
                                                  "hard": 151_000, "compact_at": 167_000})
        self.assertEqual(aps.tiers(150_000, {}), {"soft": 75_000, "wrap": 94_500,
                                                  "hard": 105_000, "compact_at": 117_000})
        self.assertEqual(aps.tiers(300_000, {}), {"soft": 150_000, "wrap": 222_000,
                                                  "hard": 243_000, "compact_at": 267_000})
        self.assertEqual(aps.tiers(1_000_000, {}), {"soft": 500_000, "wrap": 880_000,
                                                    "hard": 920_000, "compact_at": 967_000})

    def test_the_models_window_from_the_ctx_file_lowers_the_tiers(self):
        self.on()
        self.write_ctx_window(200_000)
        self.assertIsNone(self.stop(99_000))
        self.assertEqual(self.stop(101_000), {"decision": "block",
                                              "reason": text("soft", "101k", "167k")})
        self.assertEqual(self.ctx(), {**self.ctx(), "tokens": 101_000, "window": 200_000})

    def test_a_larger_or_insane_model_window_does_not_raise_the_tiers(self):
        self.on()
        for win in (1_000_000, 10, "200000", True):
            self.write_ctx_window(win)
            self.assertIsNone(self.stop(299_000))       # 600k's soft tier, not crossed
            self.assertEqual(self.ctx()["window"], win)  # kept, never clobbered
            self.assertEqual(aps.window(self.transcript, win), 600_000)

    def test_the_config_dir_comes_from_the_transcript_path(self):
        cfg = os.path.join(self.tmp, "other-config")
        os.makedirs(os.path.join(cfg, "projects", "-home-u-dna"))
        with open(os.path.join(cfg, "settings.json"), "w") as f:
            json.dump({"autoCompactWindow": 400_000}, f)
        self.transcript = os.path.join(cfg, "projects", "-home-u-dna", SID + ".jsonl")
        self.assertEqual(aps.window(self.transcript), 400_000)
        self.assertEqual(aps.window(os.path.join(self.tmp, "t.jsonl")), 600_000)  # ~/.claude
        self.on()
        self.assertEqual(self.stop(336_000), {"decision": "block",
                                              "reason": text("hard", "336k", "367k")})

    def test_a_valid_tiers_override(self):
        self.pass_toml("autopass = true\ntiers = [20000, 40000, 50000]\n")
        self.assertEqual(aps.tiers(), {"soft": 20_000, "wrap": 40_000, "hard": 50_000,
                                       "compact_at": 567_000})
        self.assertEqual(self.stop(25_000), block("soft", "25k"))
        self.assertEqual(self.tool(51_000), context("hard", "51k"))

    def test_a_garbage_tiers_override_falls_back(self):
        for bad in ('"x"', "[3, 2, 1]", "[1, 2]", "[1, 2, 600000]", "[1.5, 2, 3]",
                    "[true, 2, 3]", "[0, 1, 2]"):
            self.pass_toml("tiers = %s\n" % bad)
            self.assertEqual(aps.tiers()["soft"], 300_000, bad)


class Toggle(Base):
    """The CLI the autopass mod runs: `autopass_toggle.py SESSION_ID CWD ARGS`, ARGS being what
    was typed after `/autopass` (the engine has already matched the command name)."""

    def reply(self, args, session=None):
        p = subprocess.run(["python3", "-I", TOGGLE, SID, self.cwd, args],
                           capture_output=True, text=True, timeout=20, cwd=self.tmp,
                           env={**self.env, **(IN_TAB if session is None else session)})
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertTrue(p.stdout.endswith("\n") and p.stdout.count("\n") == 1, p.stdout)
        return p.stdout[:-1]

    def flag(self):
        with open(os.path.join(self.state, "dotclaude", "autopass", "7.json")) as f:
            return json.load(f)

    def test_on_and_off_write_the_tab_flag(self):
        self.assertEqual(self.reply("on"),
                         "on in this tab: it nudges a handoff at each context tier.")
        self.assertEqual((self.flag()["tab"], self.flag()["on"]), (TAB, True))
        self.assertEqual(aps.decide(self.cwd, "%7"), (True, "tab"))
        self.assertEqual(self.reply("  OFF  "), "off in this tab: no nudges; one line at the hard tier.")
        self.assertIs(self.flag()["on"], False)

    def test_status_reports_tokens_the_next_tier_and_the_source(self):
        self.assertEqual(self.reply("status"),
                         "off (the default). Context unknown yet, next tier: soft at "
                         "300k; auto-compact near 567k.")
        self.write_transcript(312_000)
        self.stop()
        self.reply("on")
        self.assertEqual(self.reply(""),
                         "on (set in this tab). Context 312k, next tier: wrap-up at "
                         "480k; auto-compact near 567k.")
        self.write_transcript(530_000)
        self.stop()
        self.assertIn("past the hard tier (520k)", self.reply("status"))

    def test_status_after_a_compact_says_unknown_yet(self):
        self.write_transcript(530_000)
        self.stop()
        self.event("SessionStart", source="compact")
        self.assertIn("Context unknown yet, next tier: soft at 300k", self.reply("status"))

    def test_status_reads_the_window_from_the_inherited_config_dir(self):
        conf = os.path.join(self.tmp, "cfg")
        os.makedirs(conf)
        with open(os.path.join(conf, "settings.json"), "w") as f:
            json.dump({"autoCompactWindow": 400_000}, f)
        self.env["CLAUDE_CONFIG_DIR"] = conf
        self.assertNotIn("567k", self.reply("status"))

    def test_the_texts_name_the_pass_toml_the_watcher_reads(self):
        for conf, shown in ((os.path.join(self.home, "conf"), "~/conf/dotclaude/pass.toml"),
                            (os.path.join(self.tmp, "conf"),
                             os.path.join(self.tmp, "conf", "dotclaude", "pass.toml"))):
            os.makedirs(os.path.join(conf, "dotclaude"))
            with open(os.path.join(conf, "dotclaude", "pass.toml"), "w") as f:
                f.write("autopass = true\n")
            self.env["XDG_CONFIG_HOME"] = conf
            self.assertIn("on (from %s)." % shown, self.reply("status"))
            self.assertIn(shown, self.reply("on", session={}))

    def test_without_tmux_nothing_is_written(self):
        out = self.reply("on", session={})
        self.assertIn("per tmux tab", out)
        self.assertIn("~/.config/dotclaude/pass.toml", out)
        self.assertFalse(os.path.exists(os.path.join(self.state, "dotclaude", "autopass")))
        self.env["STUB_SERVER"] = ""
        self.assertIn("tmux didn't say", self.reply("off"))

    def test_garbage_arguments_get_the_usage(self):
        for args in ("maybe", "on please", "on\noff", "status now", "-x"):
            self.assertEqual(self.reply(args), toggle_mod.USAGE, args)
        self.assertIn("off (the default)", self.reply("   \n"))

    def test_a_reply_never_starts_with_the_plugin_name(self):
        # The engine shows each reply under the plugin's name ("autopass: ..."); a reply that
        # led with it too would read "autopass: autopass on".
        for args, session in (("on", None), ("off", None), ("status", None), ("on", {}),
                              ("x", None)):
            self.assertFalse(self.reply(args, session).lower().startswith("autopass"), args)

    def test_a_wrong_argument_count_fails_loudly(self):
        p = subprocess.run(["python3", "-I", TOGGLE, SID, self.cwd], capture_output=True,
                           text=True, timeout=20, env=self.env, cwd=self.tmp)
        self.assertEqual((p.returncode, p.stdout), (2, ""))
        self.assertIn("usage: autopass_toggle.py", p.stderr)

    def test_a_busy_session_lock_delays_the_cache_drop_and_says_so(self):
        d = os.path.join(self.state, "dotclaude", "ctx-watch")
        os.makedirs(d)
        fd = os.open(os.path.join(d, SID + ".lock"), os.O_RDWR | os.O_CREAT)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        out = self.reply("on")
        self.assertIn("on in this tab", out)
        self.assertIn(toggle_mod.LATE.strip(), out)
        self.assertEqual(self.flag()["on"], True)   # the flag itself is written regardless

    def test_a_toggle_drops_the_watchers_cached_decision(self):
        self.write_transcript(525_000)
        self.assertEqual(self.stop(), {"systemMessage": text("off", "525k")})  # caches off
        self.reply("on")
        self.assertEqual(self.stop(), block("hard", "525k"))


def skill_call(skill, sidechain=False):
    """A main-chain assistant entry calling the Skill tool, as the transcript records it."""
    e = assistant(1, sidechain=sidechain)
    e["message"]["content"] = [{"type": "tool_use", "id": "toolu_1", "name": "Skill",
                                "input": {"skill": skill}}]
    del e["message"]["usage"]
    return e


def bash_call(command):
    e = skill_call("x")
    e["message"]["content"] = [{"type": "tool_use", "id": "toolu_2", "name": "Bash",
                                "input": {"command": command, "description": "Pass"}}]
    return e


class Rearm(Base):
    def test_a_count_hovering_at_a_tier_does_not_fire_it_again(self):
        self.on()
        self.assertEqual(self.stop(310_000), block("soft", "310k"))
        for n in (290_000, 305_000, 250_000, 320_000):   # never more than 50k under
            self.assertIsNone(self.stop(n), n)
        self.assertIsNone(self.stop(249_999))            # re-armed
        self.assertEqual(self.stop(301_000), block("soft", "301k"))

    def test_hovering_at_the_hard_tier_off_does_not_repeat_the_line(self):
        self.assertEqual(self.stop(521_000), {"systemMessage": text("off", "521k")})
        self.assertIsNone(self.stop(500_000))
        self.assertIsNone(self.stop(522_000))
        self.assertIsNone(self.stop(469_000))
        self.assertEqual(self.stop(521_000), {"systemMessage": text("off", "521k")})

    def test_a_handoff_after_the_hard_tier_stops_its_re_arm(self):
        self.on()
        self.write_transcript(525_000)
        self.assertEqual(self.stop(), block("hard", "525k"))
        rec = cw.fresh_record(aps.load_json(aps.watch_path(SID)))
        self.assertEqual(rec["hard_offset"], os.path.getsize(self.transcript))
        self.assertIsInstance(rec["hard_time"], float)
        self.assertIsNone(self.stop_at(546_000, skill_call("pass")))
        self.assertIsNone(self.stop_at(570_000))         # still handing off
        self.assertIsNone(self.stop_at(100_000))         # a compact re-arms everything
        self.assertEqual(self.stop_at(525_000), block("hard", "525k"))
        self.assertEqual(self.stop_at(546_000), block("hard", "546k"))  # no handoff since

    def test_a_pass_respawn_call_counts(self):
        self.on()
        for i, cmd in enumerate(("pass-respawn -C /home/u/code/dna --compact",
                                 "  ! pass-respawn -C /home/u/code/dna",
                                 "/home/u/.local/bin/pass-respawn -C /x")):
            sid = "s%d" % i
            self.write_transcript(525_000)
            self.assertEqual(self.stop(session_id=sid), block("hard", "525k"))
            self.append(bash_call(cmd), assistant(546_000))
            self.assertIsNone(self.stop(session_id=sid), cmd)

    def test_naming_pass_respawn_or_a_handoff_alone_does_not_count(self):
        self.on()
        for i, call in enumerate((bash_call("grep pass-respawn README.md"),
                                  bash_call("git diff -- skills/pass/scripts/pass-respawn"),
                                  bash_call("echo hi; pass-respawn -C /x"),
                                  skill_call("handoff"))):
            sid = "n%d" % i
            self.write_transcript(525_000)
            self.assertEqual(self.stop(session_id=sid), block("hard", "525k"))
            self.append(call, assistant(546_000))
            self.assertEqual(self.stop(session_id=sid), block("hard", "546k"), i)

    def test_a_pass_that_never_comes_lets_the_re_arm_resume(self):
        self.on()
        self.write_transcript(525_000)
        self.assertEqual(self.stop(), block("hard", "525k"))
        self.assertIsNone(self.stop_at(546_000, skill_call("pass")))   # seen at 546k
        self.assertIsNone(self.stop_at(585_999))                       # under 546k + 40k
        self.assertEqual(self.stop_at(586_000), block("hard", "586k")) # expired: fires
        self.assertIsNone(self.stop_at(600_000))                       # under 586k + 20k
        self.assertEqual(self.stop_at(606_000), block("hard", "606k")) # old call not re-read

    def test_other_calls_and_a_subagents_skill_call_do_not(self):
        self.on()
        self.write_transcript(525_000)
        self.assertEqual(self.stop(), block("hard", "525k"))
        self.assertEqual(self.stop_at(546_000, skill_call("pass", sidechain=True),
                                      skill_call("writing-voice"), bash_call("git status")),
                         block("hard", "546k"))

    def test_a_handoff_before_the_firing_does_not_count(self):
        self.on()
        self.write_transcript(525_000, before=(skill_call("pass"),))
        self.assertEqual(self.stop(), block("hard", "525k"))
        self.assertEqual(self.stop_at(546_000), block("hard", "546k"))


class Locks(Base):
    def test_the_lock_is_per_session_and_a_busy_one_says_nothing(self):
        self.on()
        d = os.path.join(self.state, "dotclaude", "ctx-watch")
        os.makedirs(d)
        fd = os.open(os.path.join(d, SID + ".lock"), os.O_RDWR | os.O_CREAT)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.assertIsNone(self.stop(310_000))
        self.assertEqual(self.ctx()["tokens"], 310_000)   # the count still lands
        self.assertEqual(self.stop(310_000, session_id="other"), block("soft", "310k"))
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(self.stop(311_000), block("soft", "311k"))  # nothing was marked

    def test_decide_runs_before_the_lock(self):
        self.on()
        self.write_transcript(310_000)
        held = []

        def decide(cwd, pane):
            with aps.watch_lock(SID, wait=0) as locked:
                held.append(locked)
            return True, "pass.toml"

        payload = {"session_id": SID, "hook_event_name": "Stop",
                   "transcript_path": self.transcript, "cwd": self.cwd}
        with mock.patch.object(aps, "decide", decide):
            self.assertEqual(cw.handle(payload), block("soft", "310k"))
        self.assertEqual(held, [True])


class PassRuleParity(Base):
    """One stop record through every reader: pass-respawn's waiter (stop_problem), its --tasks,
    and the nudge's recorded_work. None may read a record dated after the call as clearer than
    the waiter does (review round 2: a wait labeled `dream` read as clear in two of them).
    --tasks has no call to date against, so a record from before it is out of scope here."""

    def test_every_reader_agrees_whether_a_plain_pass_is_clear(self):
        loader = SourceFileLoader("pass_respawn", os.path.join(REPO, "skills", "pass",
                                                                "scripts", "pass-respawn"))
        pr = importlib.util.module_from_spec(importlib.util.spec_from_loader("pass_respawn",
                                                                              loader))
        loader.exec_module(pr)
        # Called a minute before each record, as in a real pass.
        plan = types.SimpleNamespace(session_id=SID, called=time.time() - 60)  # wall clock
        watch = {"label": "artifact watch", "id": "s1", "url": "https://claude.ai/artifact/x"}
        cases = [({"waits": [], "tasks": []}, True),
                 ({"waits": [], "tasks": [watch, {"label": "dream"}, "dream"]}, True),
                 ({"waits": [], "tasks": [{"label": "monitor", "id": "m1"}]}, False),
                 ({"waits": [], "tasks": [None, 3]}, False),
                 ({"waits": ["shell"], "tasks": [{"label": "shell", "id": "b1"}]}, False),
                 ({"waits": ["shell"], "tasks": []}, False),
                 ({"waits": ["dream"], "tasks": []}, False),
                 ({"waits": ["artifact watch"], "tasks": [watch]}, False),
                 ({"waits": [1], "tasks": []}, False),
                 ({"waits": "shell", "tasks": []}, False),
                 ({"tasks": []}, False),
                 ({"waits": [], "tasks": "monitor"}, False),
                 ({"waits": []}, False),
                 # Review round 3: an artifact watch counts only with its page, and a time
                 # that isn't a finite number can't date the record after the call.
                 ({"waits": [], "tasks": [{"label": "artifact watch", "id": "s1"}]}, False),
                 ({"waits": [], "tasks": ["artifact watch"]}, False),
                 ({"time": float("nan"), "waits": [], "tasks": []}, False),
                 ({"time": float("inf"), "waits": [], "tasks": []}, False),
                 ({"time": float("-inf"), "waits": [], "tasks": []}, False),
                 ({"time": 10 ** 400, "waits": [], "tasks": []}, False),  # past a float
                 ({"time": "now", "waits": [], "tasks": []}, False),
                 ({"time": True, "waits": [], "tasks": []}, False)]  # review round 6
        path = os.path.join(self.state, "dotclaude", "stops", SID + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        for body, clear in cases:
            with self.subTest(body=body):
                rec = {"session_id": SID, "time": time.time(), **body}  # wall clock
                with open(path, "w") as f:
                    json.dump(rec, f)
                self.assertEqual(pr.stop_problem(plan, rec) is None, clear)
                self.assertEqual(cw.recorded_work(SID)[0] is None, clear)
                out = io.StringIO()
                with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": SID}), \
                        contextlib.redirect_stdout(out):
                    self.assertEqual(pr.main(["--tasks", "-C", self.cwd]), 0)
                blocks = re.search(r"blocks a plain pass|can't be read|no task list",
                                   out.getvalue())
                self.assertEqual(blocks is None, clear, out.getvalue())

    def test_a_record_too_deep_for_json_reads_as_unknown(self):
        # Review round 7: json raises RecursionError, not ValueError, on deep nesting.
        path = os.path.join(self.state, "dotclaude", "stops", SID + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("[" * 100000)
        self.assertIsNone(aps.load_json(path))
        self.assertEqual(cw.recorded_work(SID), ("unknown", []))


class PlainPassRule(unittest.TestCase):
    def test_odd_entries_block_as_unlabeled_and_never_raise(self):
        lib = aps.lanelib()
        self.assertEqual(lib.plain_pass_blockers([{"a": 1}, ["x"], "dream", None, 3, "monitor",
                                                  {"label": ""}, {"label": 5}, ""]),
                         [{"label": "unlabeled"}] * 4 + [{"label": "monitor"}]
                         + [{"label": "unlabeled"}] * 3)
        self.assertEqual(lib.plain_pass_blockers(["dream", "dream"]), [])

    def test_record_entries_keep_their_names_and_an_artifact_watch_never_blocks(self):
        # stop-ring.sh's record keeps each task as {label, id, description, url}; a plain
        # pass ignores memory upkeep and the Artifact tool's live watch (incident e7cc7b9a).
        lib = aps.lanelib()
        watch = {"label": "artifact watch", "id": "s1", "url": "https://claude.ai/artifact/x"}
        mon = {"label": "monitor", "id": "m1", "description": "deploy events"}
        self.assertEqual(lib.plain_pass_blockers([watch, mon, {"label": "dream", "id": "d1"}]),
                         [mon])
        self.assertEqual(lib.plain_pass_blockers([watch]), [])
        # Only string fields survive: a record is data, and its text reaches tmux and the log.
        self.assertEqual(lib.task_entries([{"label": "shell", "id": 3, "description": ["x"],
                                            "url": "u", "extra": "e"}]),
                         [{"label": "shell", "url": "u"}])
        self.assertIsNone(lib.task_entries("monitor"))


def typed_command(name, args="", as_list=False):
    """A main-chain user entry for a typed skill command, the shape Claude Code 2.1.296 writes
    (probed live with a project skill): string content, origin human."""
    body = ("<command-message>%s</command-message>\n<command-name>/%s</command-name>\n"
            "<command-args>%s</command-args>" % (name, name, args))
    return {"parentUuid": "a-1", "isSidechain": False, "type": "user", "uuid": "u-9",
            "origin": {"kind": "human"},
            "message": {"role": "user",
                        "content": [{"type": "text", "text": body}] if as_list else body}}


def skill_body(name):
    """The isMeta user entry that follows a typed skill command, holding the skill's body."""
    return {"parentUuid": "u-9", "isSidechain": False, "type": "user", "uuid": "u-10",
            "isMeta": True,
            "message": {"role": "user", "content": [
                {"type": "text", "text": "Base directory for this skill: /home/u/.claude/"
                                         "skills/%s\n\n# %s" % (name, name)}]}}


class TypedPass(Base):
    def test_a_typed_pass_starts_the_pause_before_its_handoff_call(self):
        self.on()
        for i, entry in enumerate((typed_command("pass"),
                                   typed_command("pass", "compact", as_list=True))):
            sid = "t%d" % i
            self.write_transcript(525_000)
            self.assertEqual(self.stop(session_id=sid), block("hard", "525k"))
            self.append(entry, skill_body("pass"), skill_call("handoff"), assistant(546_000))
            self.assertIsNone(self.stop(session_id=sid))

    def test_a_typed_handoff_and_pass_counts_through_the_skill_call(self):
        # "handoff and pass" reaches the model as text; the model calls the pass skill.
        self.on()
        self.write_transcript(525_000)
        self.assertEqual(self.stop(), block("hard", "525k"))
        said = {"parentUuid": "a-1", "isSidechain": False, "type": "user", "uuid": "u-8",
                "message": {"role": "user", "content": "handoff and pass"}}
        self.append(said, skill_call("pass"), skill_call("handoff"), assistant(546_000))
        self.assertIsNone(self.stop())

    def test_other_commands_and_a_subagents_pass_do_not_count(self):
        self.on()
        sub = typed_command("pass")
        sub["isSidechain"] = True
        self.write_transcript(525_000)
        self.assertEqual(self.stop(), block("hard", "525k"))
        self.append(typed_command("passive"), skill_body("passive"), typed_command("passx"),
                    typed_command("compact"), sub,
                    {"type": "user", "isSidechain": False,
                     "message": {"role": "user", "content": "explain /pass please"}},
                    {"type": "user", "isSidechain": False, "origin": {"kind": "human"},
                     "message": {"role": "user", "content": "the hook matches "
                                 "<command-name>/pass</command-name> in a typed /pass"}},
                    assistant(546_000))
        self.assertEqual(self.stop(), block("hard", "546k"))

    def test_an_expired_pause_moves_the_scan_past_the_old_call_even_when_quiet(self):
        # The expiry at 586k happens while a pass is pending (mode() is None: nothing fires),
        # and must still move hard_offset, or the old pass call is found again at 587k.
        self.on()
        self.write_transcript(525_000)
        self.assertEqual(self.stop(), block("hard", "525k"))
        self.assertIsNone(self.stop_at(546_000, skill_call("pass")))
        d = os.path.join(self.state, "dotclaude", "pass-pending")
        os.makedirs(d)
        fd = os.open(os.path.join(d, SID + ".lock"), os.O_RDWR | os.O_CREAT)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.assertIsNone(self.stop_at(586_000))
        rec = cw.fresh_record(aps.load_json(aps.watch_path(SID)))
        self.assertEqual((rec["handing_off"], rec["hard_offset"]),
                         (False, os.path.getsize(self.transcript)))
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(self.stop_at(587_000), block("hard", "587k"))


class SmallWindows(Base):
    def test_a_150k_window_re_arms_after_a_compact(self):
        # hysteresis min(50k, tier // 4): hard 105k re-arms under 78.75k
        self.on()
        self.write_ctx_window(150_000)
        self.assertEqual(self.stop(106_000), {"decision": "block",
                                              "reason": text("hard", "106k", "117k")})
        self.assertIsNone(self.stop(60_000))
        self.assertEqual(self.stop(106_000), {"decision": "block",
                                              "reason": text("hard", "106k", "117k")})

    def test_a_150k_windows_hard_re_arm_stays_under_compact(self):
        tiers = aps.tiers(150_000, {})
        self.assertEqual(cw.rearm_step(tiers), 6_000)         # (117k - 105k) // 2
        self.assertEqual(cw.rearm_step(aps.tiers(600_000, {})), 20_000)
        self.on()
        self.write_ctx_window(150_000)
        self.assertEqual(self.stop(106_000)["reason"], text("hard", "106k", "117k"))
        self.assertIsNone(self.stop(111_999))
        self.assertEqual(self.stop(112_000)["reason"], text("hard", "112k", "117k"))

    def test_soft_on_200k_re_arms_after_a_compact_sized_drop(self):
        self.on()
        self.write_ctx_window(200_000)
        self.assertEqual(self.stop(101_000)["reason"], text("soft", "101k", "167k"))
        self.assertIsNone(self.stop(80_000))       # 100k - 25k = 75k: not yet
        self.assertIsNone(self.stop(101_000))
        self.assertIsNone(self.stop(40_000))       # a compact
        self.assertEqual(self.stop(101_000)["reason"], text("soft", "101k", "167k"))

    def test_600k_keeps_its_50k_hysteresis(self):
        tiers = aps.tiers(600_000, {})
        self.assertEqual([cw.hysteresis(tiers, t) for t in aps.TIER_NAMES],
                         [50_000, 50_000, 50_000])


class Wording(Base):
    def test_each_work_state_picks_its_text(self):
        tiers = aps.tiers(600_000, {})
        cases = [(None, "wrap"), ("blocked", "wrap_compact"), ("unknown", "wrap_unknown")]
        for state, key in cases:
            rec = cw.fresh_record(None)
            self.assertEqual(cw.step(rec, 485_000, tiers, "PostToolUse", lambda: True,
                                     lambda: state)[0], key)
        rec = cw.fresh_record(None)
        self.assertEqual(cw.step(rec, 485_000, tiers, "Stop", lambda: True,
                                 lambda: "busy")[0], None)
        for state, key in (("busy", "off_compact"), ("blocked", "off_compact"),
                           ("unknown", "off_unknown"), (None, "off")):
            rec = cw.fresh_record(None)
            self.assertEqual(cw.step(rec, 525_000, tiers, "Stop", lambda: False,
                                     lambda: state)[0], key)

    def test_unknown_texts_never_claim_tasks_run(self):
        self.assertNotIn("soft_unknown", cw.TEXTS)   # soft never meets unknown work
        for key in ("wrap_unknown", "hard_unknown", "off_unknown"):
            self.assertNotIn("are running", cw.TEXTS[key])
            self.assertIn("compact", cw.TEXTS[key])
        self.assertIn("safe whether or not background work is running", cw.TEXTS["hard_unknown"])
        self.assertIn("/pass compact is safe if background work may be running",
                      cw.TEXTS["off_unknown"])


class CacheRace(Base):
    def test_a_decision_made_before_a_toggle_is_never_served_after_it(self):
        # Hook A reads the flag generation and decides "off"; the toggle writes the flag and
        # drops the cache; then A stores its stale entry. The next hook must decide again.
        self.write_transcript(525_000)
        payload = {"session_id": SID, "hook_event_name": "Stop",
                   "transcript_path": self.transcript, "cwd": self.cwd}
        real = aps.decide

        def decide_then_toggle(cwd, pane):
            answer = real(cwd, pane)                     # off: the default
            toggle_mod.toggle("on", SID, "%7")           # lands mid-hook
            return answer

        with mock.patch.object(aps, "decide", decide_then_toggle):
            self.assertEqual(cw.handle(payload, "%7"), {"systemMessage": text("off", "525k")})
        stale = aps.load_json(aps.watch_path(SID))["mode"]
        self.assertEqual((stale["on"], stale["flag"]), (False, "absent"))
        self.assertEqual(aps.flag_generation("%7"), "g1")
        self.assertEqual(cw.handle(payload, "%7"), block("hard", "525k"))

    def test_two_writes_in_one_tick_still_differ(self):
        aps.set_flag("%7", TAB, True)
        first = aps.flag_generation("%7")
        aps.set_flag("%7", TAB, True)
        self.assertNotEqual(aps.flag_generation("%7"), first)
        self.assertEqual(aps.flag_generation(None), "absent")


class LockPrune(Base):
    def test_a_lock_in_use_is_never_pruned_and_an_old_idle_one_is(self):
        d = os.path.join(self.state, "dotclaude", "ctx-watch")
        os.makedirs(d)
        old = time.time() - 30 * 86400  # wall clock
        for name in (SID, "idle"):
            path = os.path.join(d, name + ".lock")
            open(path, "w").close()
            os.utime(path, (old, old))
        with aps.watch_lock(SID) as locked:
            self.assertTrue(locked)
            cw.prune_locks(d, time.time())  # wall clock
        self.assertTrue(os.path.exists(os.path.join(d, SID + ".lock")))
        self.assertFalse(os.path.exists(os.path.join(d, "idle.lock")))

    def test_a_lock_file_unlinked_before_its_flock_is_taken_again_at_the_path(self):
        # The prune can unlink the file between open and flock; a lock on the old inode
        # excludes nobody, so watch_lock must end up holding the file now at the path.
        path = os.path.join(self.state, "dotclaude", "ctx-watch", SID + ".ctx.lock")
        real = fcntl.flock
        calls = []

        def flock(fd, op):
            if not calls and os.path.exists(path):
                os.unlink(path)  # the prune, landing between open and the first flock
            calls.append(op)
            return real(fd, op)

        with mock.patch.object(aps.fcntl, "flock", flock):
            with aps.watch_lock(SID, kind=".ctx") as locked:
                self.assertTrue(locked)
                other = os.open(path, os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError):
                        real(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(other)
        self.assertGreaterEqual(len(calls), 2)


class CtxOrder(Base):
    def test_an_older_count_landing_late_never_replaces_a_newer_one(self):
        aps.write_ctx(SID, 500_000, 200.0)
        aps.write_ctx(SID, 400_000, 100.0)  # a parallel tool call's hook, finishing last
        self.assertEqual({k: aps.read_ctx(SID)[k] for k in ("tokens", "time")},
                         {"tokens": 500_000, "time": 200.0})
        aps.merge_ctx(SID, {"window": 200_000, "window_at": 150.0})  # the widget's fields land
        self.assertEqual(aps.read_ctx(SID)["window"], 200_000)
        aps.write_ctx(SID, 510_000, 300.0)
        self.assertEqual(aps.read_ctx(SID)["tokens"], 510_000)

    def test_the_compact_blank_and_a_late_count_never_undo_each_other(self):
        aps.write_ctx(SID, 520_000, 100.0)
        aps.merge_ctx(SID, {"tokens": None, "time": 200.0})   # SessionStart(compact)
        aps.write_ctx(SID, 521_000, 150.0)   # a pre-compact hook finishing late: dropped
        self.assertIsNone(aps.read_ctx(SID)["tokens"])
        aps.write_ctx(SID, 107_000, 300.0)
        aps.merge_ctx(SID, {"tokens": None, "time": 250.0})   # a blank that waited on the lock
        self.assertEqual({k: aps.read_ctx(SID)[k] for k in ("tokens", "time")},
                         {"tokens": 107_000, "time": 300.0})


if __name__ == "__main__":
    unittest.main()
