"""hooks/context-watch.sh, hooks/autopass-toggle.sh and hooks/autopass_state.py: the autopass
context watcher, its tiers and the per-tab /autopass toggle (stdlib only).

Each test has its own HOME (for ~/.claude/settings.json and ~/.config/dotclaude/pass.toml) and
XDG_STATE_HOME, and a stub tmux on PATH that answers `display` with $STUB_SERVER (empty fails).
The env starts scrubbed of CLAUDE* and TMUX*, since the test may run inside a Claude tab. The
shims run end to end; the modules are also loaded in-process for the parts a shim can't reach.
Transcript lines copy the real entry shape (spike A3, Claude Code 2.1.296)."""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, "hooks")
WATCH = os.path.join(HOOKS, "context-watch.sh")
TOGGLE = os.path.join(HOOKS, "autopass-toggle.sh")


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
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "TMUX"))}
        self.env.update(PATH=stubs + os.pathsep + self.env["PATH"], HOME=self.home,
                        XDG_STATE_HOME=self.state, STUB_SERVER=SERVER,
                        CLAUDE_CODE_SESSION_ATTENDED="1")
        patch = mock.patch.dict(os.environ, {k: self.env[k] for k in
                                             ("PATH", "HOME", "XDG_STATE_HOME", "STUB_SERVER")})
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("CLAUDE_CODE_SESSION_ATTENDED", None)
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

    def write_transcript(self, total, before=(), after=(USER, SYSTEM)):
        with open(self.transcript, "w") as f:
            for e in [*before, assistant(total), *after]:
                f.write(json.dumps(e) + "\n")

    def append(self, *entries):
        with open(self.transcript, "a") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def stop_at(self, total, *before):
        """A Stop after appending entries and then an assistant entry at total."""
        self.append(*before, assistant(total), USER)
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
            json.dump({"session_id": SID, "time": time.time() - age, "waits": waits,
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


def text(key, n, c="567k"):
    return cw.TEXTS[key].format(n=n, c=c)


def block(key, n):
    return {"decision": "block", "reason": text(key, n)}


def context(key, n):
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "additionalContext": text(key, n)}}


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
        self.assertLess(time.time() - self.ctx()["time"], 30)

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
                         {"systemMessage": text("off_compact", "521k")})

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
                         block("hard_busy", "525k"))
        self.assertIsNone(self.stop(526_000))

    def test_monitor_only_tasks_say_compact_mode_at_every_tier(self):
        self.on()
        mon = [{"type": "monitor"}, {"type": "dream"}]
        self.assertEqual(self.stop(310_000, background_tasks=mon), block("soft_compact", "310k"))
        self.assertEqual(self.stop(481_000, background_tasks=mon), block("wrap_compact", "481k"))
        self.assertEqual(self.stop(521_000, background_tasks=mon), block("hard_compact", "521k"))

    def test_teammates_and_unlabeled_tasks_block_a_plain_pass_too(self):
        self.on()
        self.assertEqual(self.stop(310_000, background_tasks=[{"id": "x"}]),
                         block("soft_compact", "310k"))
        self.assertEqual(self.stop(481_000, background_tasks=[{"type": "teammate"}]),
                         block("wrap_compact", "481k"))

    def test_dream_alone_is_no_background_work(self):
        self.on()
        self.assertEqual(self.stop(310_000, background_tasks=[{"type": "dream"}]),
                         block("soft", "310k"))

    def test_a_tool_call_reads_the_fresh_stop_record(self):
        self.on()
        self.stop_record(["subagent"], ["subagent"])
        self.assertIsNone(self.tool(485_000))                           # busy: wrap quiet
        self.assertEqual(self.tool(525_000), context("hard_busy", "525k"))
        self.stop_record([], ["monitor"])
        self.assertEqual(self.tool(546_000), context("hard_compact", "546k"))

    def test_a_tool_call_reads_monitor_only_tasks_as_compact_at_wrap(self):
        self.on()
        self.stop_record([], ["monitor"])
        self.assertEqual(self.tool(485_000), context("wrap_compact", "485k"))

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
            json.dump({"time": time.time(), "waits": []}, f)
        self.assertEqual(self.tool(485_000), context("wrap_unknown", "485k"))

    def test_the_plain_pass_rule_is_pass_respawns(self):
        # One definition: lanelib.plain_pass_blockers, which pass-respawn's stop_problem uses.
        lib = aps.lanelib()
        self.assertEqual(lib.plain_pass_blockers(["dream", "monitor", "unlabeled"]),
                         ["monitor", "unlabeled"])
        self.assertEqual(lib.plain_pass_blockers(None), ["?"])
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
    def prompt(self, prompt, session=None, **payload):
        body = {"session_id": SID, "hook_event_name": "UserPromptSubmit", "prompt": prompt,
                "cwd": self.cwd, **payload}
        return self.run_shim(TOGGLE, body, session)

    def flag(self):
        with open(os.path.join(self.state, "dotclaude", "autopass", "7.json")) as f:
            return json.load(f)

    def test_on_and_off_write_the_tab_flag(self):
        out = self.prompt("/autopass on")
        self.assertEqual(out["decision"], "block")
        self.assertIn("autopass on in this tab", out["reason"])
        self.assertEqual((self.flag()["tab"], self.flag()["on"]), (TAB, True))
        self.assertEqual(aps.decide(self.cwd, "%7"), (True, "tab"))
        self.assertIn("autopass off", self.prompt("  /autopass OFF  ")["reason"])
        self.assertIs(self.flag()["on"], False)

    def test_status_reports_tokens_the_next_tier_and_the_source(self):
        self.assertEqual(self.prompt("/autopass status")["reason"],
                         "autopass off (the default). Context unknown yet, next tier: soft at "
                         "300k; auto-compact near 567k.")
        self.write_transcript(312_000)
        self.stop()
        self.prompt("/autopass on")
        self.assertEqual(self.prompt("/autopass")["reason"],
                         "autopass on (set in this tab). Context 312k, next tier: wrap-up at "
                         "480k; auto-compact near 567k.")
        self.write_transcript(530_000)
        self.stop()
        self.assertIn("past the hard tier (520k)", self.prompt("/autopass status")["reason"])

    def test_without_tmux_nothing_is_written(self):
        out = self.prompt("/autopass on", session={})
        self.assertIn("per tmux tab", out["reason"])
        self.assertIn("~/.config/dotclaude/pass.toml", out["reason"])
        self.assertFalse(os.path.exists(os.path.join(self.state, "dotclaude", "autopass")))
        self.env["STUB_SERVER"] = ""
        self.assertIn("tmux didn't say", self.prompt("/autopass off")["reason"])

    def test_garbage_arguments_get_the_usage(self):
        self.assertEqual(self.prompt("/autopass maybe")["reason"], toggle_mod.USAGE)

    def test_other_prompts_pass_through(self):
        for p in ("please /autopass on", "/autopassx", "autopass on",
                  "/pass", "<task-notification>/autopass on</task-notification>"):
            self.assertIsNone(self.prompt(p), p)

    def test_extra_words_get_the_usage_not_the_skill_body(self):
        for p in ("/autopass on please", "/autopass\non off", "/autopass status now"):
            self.assertEqual(self.prompt(p)["reason"], toggle_mod.USAGE, p)
        self.assertIn("autopass off (the default)", self.prompt("/autopass   \n")["reason"])

    def test_a_busy_session_lock_delays_the_cache_drop_and_says_so(self):
        d = os.path.join(self.state, "dotclaude", "ctx-watch")
        os.makedirs(d)
        fd = os.open(os.path.join(d, SID + ".lock"), os.O_RDWR | os.O_CREAT)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        out = self.prompt("/autopass on")["reason"]
        self.assertIn("autopass on in this tab", out)
        self.assertIn(toggle_mod.LATE.strip(), out)
        self.assertEqual(self.flag()["on"], True)   # the flag itself is written regardless

    def test_a_subagent_prompt_passes_through(self):
        self.assertIsNone(self.prompt("/autopass on", agent_id="a1"))

    def test_a_toggle_drops_the_watchers_cached_decision(self):
        self.write_transcript(525_000)
        self.assertEqual(self.stop(), {"systemMessage": text("off", "525k")})  # caches off
        self.prompt("/autopass on")
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


class PlainPassRule(unittest.TestCase):
    def test_non_strings_block_like_the_old_rule_and_never_raise(self):
        lib = aps.lanelib()
        self.assertEqual(lib.plain_pass_blockers([{"a": 1}, ["x"], "dream", None, 3, "monitor"]),
                         ["{'a': 1}", "['x']", "None", "3", "monitor"])
        self.assertEqual(lib.plain_pass_blockers(["dream", "dream"]), [])


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
        old = time.time() - 30 * 86400
        for name in (SID, "idle"):
            path = os.path.join(d, name + ".lock")
            open(path, "w").close()
            os.utime(path, (old, old))
        with aps.watch_lock(SID) as locked:
            self.assertTrue(locked)
            cw.prune_locks(d, time.time())
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


if __name__ == "__main__":
    unittest.main()
