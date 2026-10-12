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
        self.assertEqual(self.tool(519_999, session_id="s3"), context("wrap", "520k"))
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

    def test_a_stale_stop_record_counts_as_no_work(self):
        self.on()
        self.stop_record(["shell"], ["shell"], age=601)
        self.assertEqual(self.tool(485_000), context("wrap", "485k"))

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

    def test_a_p_run_is_ignored(self):
        self.on()
        self.assertIsNone(self.stop(525_000, session={**IN_TAB,
                                                       "CLAUDE_CODE_SESSION_ATTENDED": "0"}))
        self.assertFalse(self.has_ctx())

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
                 (Repo("main", {"autopass": True}), (False, "pass.toml")),
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
        self.assertEqual(aps.tiers(), {"soft": 200_000, "wrap": 280_000, "hard": 320_000,
                                       "compact_at": 367_000})
        self.on()
        self.assertEqual(self.stop(321_000),
                         {"decision": "block", "reason": text("hard", "321k", "367k")})
        for garbage in (True, -5, "600000", None):
            self.settings(garbage)
            self.assertEqual(aps.window(), 600_000)

    def test_a_window_too_small_for_the_tiers_keeps_the_watcher_quiet(self):
        self.settings(200_000)
        self.assertIsNone(aps.tiers())
        self.on()
        self.assertIsNone(self.stop(190_000))
        self.assertEqual(self.ctx()["tokens"], 190_000)

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
        for p in ("/autopass on please", "please /autopass on", "/autopassx", "autopass on",
                  "/pass", "<task-notification>/autopass on</task-notification>"):
            self.assertIsNone(self.prompt(p), p)

    def test_a_subagent_prompt_passes_through(self):
        self.assertIsNone(self.prompt("/autopass on", agent_id="a1"))

    def test_a_toggle_drops_the_watchers_cached_decision(self):
        self.write_transcript(525_000)
        self.assertEqual(self.stop(), {"systemMessage": text("off", "525k")})  # caches off
        self.prompt("/autopass on")
        self.assertEqual(self.stop(), block("hard", "525k"))


if __name__ == "__main__":
    unittest.main()
