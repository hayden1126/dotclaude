"""delegation_checks: the canary tiers and the due rules (no model calls, no real claude).

The units step and the live tier are replaced in every test, so nothing here recurses into the
suite or launches `claude -p`; a fake `claude` on PATH stands in for the binary. Every test also
runs with DELEGATION_CHECKS_CHILD set, so even a missed stub can't start a background job."""
import datetime
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from _paths import HOOKS, SCRIPTS, load_script

checks = load_script("delegation_checks.py")
LEDGER = os.path.join(SCRIPTS, "delegation-ledger")
DAY = 86400
NOW = 2_000_000_000.0  # a fixed clock for evaluate() and stamp_audit()
DEAD = 2 ** 22 + 12345  # beyond pid_max on this box, so never alive
iso = checks._iso
REAL_LAUNCH = checks.launch_background  # before any test replaces it


def ok_quick(version):
    return {"version": version, "ts": iso(NOW), "ok": True, "results": []}


class StateTest(unittest.TestCase):
    """Each test gets a throwaway state dir and due.toml, as an attended session."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.due = os.path.join(self.tmp.name, "due.toml")
        env = {"XDG_STATE_HOME": self.tmp.name, "DELEGATION_DUE": self.due,
               checks.CHILD_ENV: "1", "CLAUDE_CODE_SESSION_ATTENDED": "1"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, checks, "DUE_PATH", checks.DUE_PATH)
        checks.DUE_PATH = self.due

    def state(self, name):
        return checks.read_state(name)

    def write_due(self, text):
        with open(self.due, "w") as f:
            f.write(text)


class Strings(unittest.TestCase):
    def test_all_present_passes(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"\0".join(s.encode() for s, _ in checks.CANARY_STRINGS))
            f.flush()
            ok, detail = checks.check_strings(f.name)
        self.assertTrue(ok, detail)

    def test_a_missing_string_fails_and_is_named(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b"\0".join(s.encode() for s, _ in checks.CANARY_STRINGS
                               if s != "customAgentType"))
            f.flush()
            ok, detail = checks.check_strings(f.name)
        self.assertFalse(ok)
        self.assertIn("customAgentType", detail)

    def test_every_string_names_its_consumer(self):
        for s, who in checks.CANARY_STRINGS:
            self.assertTrue(s and who, s)

    def test_the_watch_guards_strings_are_checked(self):
        # Found in the 2.1.286 binary. The whole summary, 'was stopped after reaching its
        # background time limit', isn't one string there: 'was' is joined in at runtime.
        names = {s for s, _ in checks.CANARY_STRINGS}
        for s in ("do not restart it", "background time limit", "task-notification",
                  "queued_command", "stopped after reaching its background time limit",
                  "tool-use-id", "background_tasks", "prompt_id", "CLAUDE_CODE_SESSION_ID"):
            self.assertIn(s, names)


class GuardShim(StateTest):
    """check_guard_shim against a shim script written here, in the test's state dir."""

    def shim(self, body):
        path = os.path.join(self.tmp.name, "watch-guard.sh")
        with open(path, "w") as f:
            f.write(body)
        return path

    def test_a_clean_run_passes(self):
        ok, detail = checks.check_guard_shim(self.shim("cat >/dev/null; exit 0\n"))
        self.assertTrue(ok, detail)

    def test_a_logged_error_fails_and_is_quoted(self):
        # Where the real shim logs: its own XDG_STATE_HOME's delegation-ledger.err.
        ok, detail = checks.check_guard_shim(self.shim(
            'cat >/dev/null; d="$XDG_STATE_HOME/dotclaude"; mkdir -p "$d"; '
            'echo "ModuleNotFoundError: x" >>"$d/delegation-ledger.err"; exit 0\n'))
        self.assertFalse(ok)
        self.assertTrue(detail.endswith(" exited 0 and printed 0 chars, and logged: "
                                        "ModuleNotFoundError: x"), detail)

    def test_another_writer_of_the_real_log_doesnt_fail_it(self):
        # A guard's routine line (an adoption, say) lands in the real log meanwhile.
        err = checks.state_path("delegation-ledger.err")
        os.makedirs(os.path.dirname(err), exist_ok=True)
        ok, detail = checks.check_guard_shim(self.shim(
            f"cat >/dev/null; echo 'watch-guard: adopted watch w-1' >>{err}; exit 0\n"))
        self.assertTrue(ok, detail)

    def test_a_missing_shim_fails(self):
        ok, detail = checks.check_guard_shim(os.path.join(self.tmp.name, "nope.sh"))
        self.assertEqual((ok, detail), (False, f"{os.path.join(self.tmp.name, 'nope.sh')} is "
                                               "missing"))

    def test_the_real_shim_runs_clean_against_this_checkout(self):
        home = os.path.join(self.tmp.name, "home")
        os.makedirs(os.path.join(home, ".claude", "skills", "delegation"))
        os.symlink(SCRIPTS, os.path.join(home, ".claude", "skills", "delegation", "scripts"))
        with mock.patch.dict(os.environ, {"HOME": home}):
            ok, detail = checks.check_guard_shim(os.path.join(HOOKS, "watch-guard.sh"))
        self.assertTrue(ok, detail)


class FakeClaude(unittest.TestCase):
    """A fake `claude` on PATH that answers --version and `sandbox status`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.status = os.path.join(self.tmp.name, "status.json")
        self.version = os.path.join(self.tmp.name, "version.txt")
        exe = os.path.join(self.tmp.name, "claude")
        with open(exe, "w") as f:
            f.write(f'#!/bin/sh\ncase "$1" in\n  --version) cat "{self.version}" ;;\n'
                    f'  sandbox) cat "{self.status}" ;;\nesac\n')
        os.chmod(exe, 0o755)
        self.say_version("2.1.300 (Claude Code)\n")
        patcher = mock.patch.dict(os.environ, {"PATH": self.tmp.name + os.pathsep
                                               + os.environ["PATH"]})
        patcher.start()
        self.addCleanup(patcher.stop)

    def say_version(self, text):
        with open(self.version, "w") as f:
            f.write(text)

    def posture(self, drop=(), **over):
        s = {"statusVersion": 3, "enabled": True, "autoAllowBashIfSandboxed": False,
             "unavailableReason": None}
        s.update(over)
        for k in drop:
            del s[k]
        with open(self.status, "w") as f:
            f.write(json.dumps(s) + "\n")
        return checks.check_posture()

    def test_version_is_parsed(self):
        self.assertEqual(checks.cc_version(), "2.1.300")

    def test_version_after_a_warning_line_is_still_found(self):
        self.say_version("warning: a newer version is available\n2.1.301 (Claude Code)\n")
        self.assertEqual(checks.cc_version(), "2.1.301")
        self.say_version("no version here\n")
        self.assertIsNone(checks.cc_version())

    def test_baseline_posture_passes(self):
        self.assertTrue(self.posture()[0])

    def test_sandbox_off_or_auto_allow_on_fails(self):
        ok, detail = self.posture(enabled=False)
        self.assertFalse(ok)
        self.assertIn("enabled=False", detail)
        self.assertFalse(self.posture(autoAllowBashIfSandboxed=True)[0])
        self.assertFalse(self.posture(unavailableReason="bwrap missing")[0])

    def test_a_key_that_is_gone_fails(self):
        ok, detail = self.posture(drop=("unavailableReason",))
        self.assertFalse(ok)
        self.assertIn("unavailableReason missing", detail)

    def test_no_json_fails(self):
        with open(self.status, "w") as f:
            f.write("not json\n")
        self.assertFalse(checks.check_posture()[0])


class Canary(StateTest):
    def setUp(self):
        super().setUp()
        os.environ.pop("SANDBOX_RUNTIME", None)  # restored by StateTest's patch.dict
        for name in ("cc_version", "check_units", "check_posture", "check_strings",
                     "check_guard_shim", "run_live"):
            self.addCleanup(setattr, checks, name, getattr(checks, name))
        checks.cc_version = lambda timeout=10: "2.1.300"
        checks.check_units = lambda: (True, "units stub")
        checks.check_posture = lambda: (True, "posture stub")
        checks.check_strings = lambda: (True, "strings stub")
        checks.check_guard_shim = lambda: (True, "guard stub")
        checks.run_live = lambda log: self.fail("the live tier ran without a stub")
        self.out = []

    def run_canary(self, quick_only, **kw):
        return checks.canary(quick_only, out=self.out.append, **kw)

    def test_quick_records_its_result(self):
        self.assertEqual(self.run_canary(True), 0)
        q = self.state("canary.json")["quick"]
        self.assertEqual((q["version"], q["ok"]), ("2.1.300", True))

    def test_a_failed_check_fails_the_tier_and_skips_the_live_tier(self):
        checks.check_strings = lambda: (False, "missing agent_id")
        self.assertEqual(self.run_canary(False), 1)
        self.assertFalse(self.state("canary.json")["quick"]["ok"])
        self.assertNotIn("green_full", self.state("canary.json"))

    def test_a_crashing_check_is_a_failure(self):
        def boom():
            raise OSError("no binary")
        checks.check_strings = boom
        self.assertEqual(self.run_canary(True), 1)
        self.assertIn("no binary", self.state("canary.json")["quick"]["results"][2]["detail"])

    def test_the_live_tier_refuses_inside_the_sandbox(self):
        with mock.patch.dict(os.environ, {"SANDBOX_RUNTIME": "1"}):
            self.assertEqual(self.run_canary(False), 2)
        self.assertEqual(self.state("canary.json"), {})
        self.assertIn("outside the sandbox", self.out[0])

    def test_a_failed_live_tier_keeps_the_old_green(self):
        checks.update_state("canary.json", green_full={"version": "2.1.290", "ts": iso(NOW)})
        checks.run_live = lambda log: (False, 50, 52, ["[FAIL] report (auto)"])
        self.assertEqual(self.run_canary(False), 1)
        st = self.state("canary.json")
        self.assertEqual(st["green_full"]["version"], "2.1.290")
        self.assertEqual((st["full"]["ok"], st["full"]["score"]), (False, "50/52"))

    def test_a_green_live_tier_records_green_full_and_its_size(self):
        checks.run_live = lambda log: (True, 52, 52, [])
        self.assertEqual(self.run_canary(False), 0)
        g = self.state("canary.json")["green_full"]
        self.assertEqual((g["version"], g["total"]), ("2.1.300", 52))

    def test_fewer_checks_than_the_last_green_run_is_not_green(self):
        checks.update_state("canary.json", green_full={"version": "2.1.290", "ts": iso(NOW),
                                                       "total": 52})
        checks.run_live = lambda log: (True, 40, 40, [])
        self.assertEqual(self.run_canary(False), 1)
        self.assertEqual(self.state("canary.json")["green_full"]["total"], 52)
        self.assertTrue(any("--accept-fewer" in ln for ln in self.out))
        self.assertEqual(self.run_canary(False, accept_fewer=True), 0)
        self.assertEqual(self.state("canary.json")["green_full"]["total"], 40)

    def test_a_crashing_live_tier_is_recorded_as_failed(self):
        def boom(log):
            raise OSError("run.py vanished")
        checks.run_live = boom
        self.assertEqual(self.run_canary(False), 1)
        full = self.state("canary.json")["full"]
        self.assertFalse(full["ok"])
        self.assertIn("run.py vanished", full["score"])


class RunLive(unittest.TestCase):
    """run_live against a stand-in run.py."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "tests", "delegation"))
        self.addCleanup(setattr, checks, "REPO", checks.REPO)
        checks.REPO = self.tmp.name
        self.log = os.path.join(self.tmp.name, "log")

    def harness(self, body):
        with open(os.path.join(self.tmp.name, "tests", "delegation", "run.py"), "w") as f:
            f.write(body)

    def test_zero_checks_is_not_green(self):
        self.harness('print("\\n0/0 checks passed")\n')  # run.py exits 0 with no results
        self.assertFalse(checks.run_live(self.log)[0])

    def test_all_passed_is_green(self):
        self.harness('print("  [PASS] x\\n\\n2/2 checks passed")\n')
        self.assertEqual(checks.run_live(self.log), (True, 2, 2, []))

    def test_a_failure_is_named(self):
        self.harness('import sys\nprint("  [FAIL] y\\n\\n1/2 checks passed")\nsys.exit(1)\n')
        ok, n, m, fails = checks.run_live(self.log)
        self.assertEqual((ok, n, m, fails), (False, 1, 2, ["[FAIL] y"]))


class Evaluate(unittest.TestCase):
    V = "2.1.300"

    def ev(self, canary=None, audit=None, due=None, items=(), today=None, version=V, **kw):
        audit = {"ts": iso(NOW)} if audit is None else audit
        return checks.evaluate(version, canary or {}, audit, due or {}, list(items), now=NOW,
                               today=today or datetime.date(2033, 5, 18), **kw)

    def green(self, version, days_ago):
        return {"quick": ok_quick(self.V),
                "green_full": {"version": version, "ts": iso(NOW - days_ago * DAY)}}

    def test_a_new_version_starts_the_quick_tier_quietly(self):
        canary = self.green(self.V, 0)
        canary["quick"] = ok_quick("2.1.299")
        nudges, jobs, _ = self.ev(canary)
        self.assertEqual((nudges, jobs), ([], ["quick"]))

    def test_no_relaunch_within_ten_minutes(self):
        canary = self.green(self.V, 0)
        canary["quick"] = ok_quick("2.1.299")
        _, jobs, _ = self.ev(canary, due={"bg_started": iso(NOW - 120)})
        self.assertEqual(jobs, [])
        _, jobs, _ = self.ev(canary, due={"bg_started": iso(NOW - 700)})
        self.assertEqual(jobs, ["quick"])

    def test_a_failed_quick_tier_nudges_every_time(self):
        canary = self.green(self.V, 0)
        canary["quick"] = {"version": self.V, "ok": False, "results": [
            {"check": "units", "ok": True, "detail": "x"},
            {"check": "strings", "ok": False, "detail": "missing agent_id"}]}
        nudges, jobs, _ = self.ev(canary)
        self.assertEqual(jobs, [])
        self.assertEqual(len(nudges), 1)
        self.assertIn("strings: missing agent_id", nudges[0])

    def test_full_tier_cadence(self):
        self.assertIn("full canary is due", self.ev({"quick": ok_quick(self.V)})[0][0])
        self.assertIn("full canary is due", self.ev(self.green("2.1.290", 8))[0][0])
        self.assertEqual(self.ev(self.green("2.1.290", 3))[0], [])
        self.assertEqual(self.ev(self.green(self.V, 30))[0], [])  # same version: nothing new

    def test_a_due_full_canary_asks_for_the_manual_rearm_check_too(self):
        self.assertIn("and so is the manual watch-guard re-arm check (docs/delegation.md, Long "
                      "waits)", self.ev(self.green("2.1.290", 8))[0][0])

    def test_a_failed_full_run_nudges_until_one_passes_even_after_an_upgrade(self):
        canary = self.green("2.1.285", 2)
        canary["full"] = {"version": "2.1.286", "ts": iso(NOW - DAY), "ok": False,
                          "score": "50/52", "log": "/x.log"}
        (nudge,), _, _ = self.ev(canary)  # now on 2.1.300, the green run only 2 days old
        self.assertIn("failed", nudge)
        self.assertIn("50/52", nudge)
        canary["green_full"] = {"version": "2.1.300", "ts": iso(NOW)}  # a later run passed
        self.assertEqual(self.ev(canary)[0], [])

    def test_an_unreadable_version_is_a_nudge_not_silence(self):
        nudges, jobs, _ = self.ev(self.green(self.V, 0), version=None)
        self.assertEqual(jobs, [])
        self.assertIn("can't read the Claude Code version", nudges[0])

    def test_dated_items_from_their_date_on(self):
        today = datetime.date(2026, 10, 7)
        items = [(datetime.date(2026, 10, 7), "review denials"),
                 (datetime.date(2026, 10, 1), "older"), (datetime.date(2026, 10, 8), "later")]
        nudges, _, _ = self.ev(self.green(self.V, 0), items=items, today=today)
        self.assertEqual(len(nudges), 2)
        self.assertTrue(any("review denials" in n for n in nudges))
        self.assertFalse(any("later" in n for n in nudges))

    def test_a_malformed_due_file_is_a_nudge(self):
        nudges, _, _ = self.ev(self.green(self.V, 0), items_error="ValueError: bad date")
        self.assertIn("due.toml is malformed", nudges[0])

    def test_audit_runs_daily_and_its_warnings_show_until_marked(self):
        canary = self.green(self.V, 0)
        _, jobs, _ = self.ev(canary, audit={"ts": iso(NOW - 25 * 3600)})
        self.assertEqual(jobs, ["audit"])
        _, jobs, _ = self.ev(canary, audit={})
        self.assertEqual(jobs, ["audit"])
        nudges, _, warns = self.ev(canary, audit={"ts": iso(NOW), "warns": ["policy hook: x"],
                                                  "shown": False})
        self.assertEqual(warns, ["policy hook: x"])
        self.assertIn("policy hook: x", nudges[0])
        nudges, _, warns = self.ev(canary, audit={"ts": iso(NOW), "warns": ["x"], "shown": True})
        self.assertEqual((nudges, warns), ([], []))

    def test_the_monthly_audit_is_due_once_the_ledger_is_a_month_old(self):
        canary, old = self.green(self.V, 0), iso(NOW - 31 * DAY)
        self.assertIn("monthly audit is due", self.ev(canary, ledger_since=old)[0][0])
        self.assertEqual(self.ev(canary, ledger_since=iso(NOW - 10 * DAY))[0], [])
        self.assertEqual(self.ev(canary, ledger_since=None)[0], [])
        fresh = {"ts": iso(NOW), "monthly": iso(NOW - 2 * DAY)}
        self.assertEqual(self.ev(canary, audit=fresh, ledger_since=old)[0], [])
        stale = {"ts": iso(NOW), "monthly": iso(NOW - 31 * DAY)}
        self.assertIn("monthly audit is due",
                      self.ev(canary, audit=stale, ledger_since=old)[0][0])

    def test_wrong_shaped_state_does_not_silence_the_dated_items(self):
        items = [(datetime.date(2020, 1, 1), "still shown")]
        for canary, audit in (({"quick": "x", "full": [1], "green_full": 3}, {"warns": "x"}),
                              ({"quick": {"version": self.V, "ok": False, "results": ["x"]}},
                               {"warns": [1, None], "ts": 5})):
            nudges, _, _ = self.ev(canary, audit=audit, items=items)
            self.assertTrue(any("still shown" in n for n in nudges), nudges)

    def test_orphans_come_from_the_argument_alone(self):
        orphans = [{"id": "w-1", "description": "the build"}, {"id": "w-2"}]
        with mock.patch("builtins.open", side_effect=AssertionError("evaluate read a file")), \
                mock.patch.object(checks.glob, "glob",
                                  side_effect=AssertionError("evaluate listed a dir")), \
                mock.patch.object(checks.dc, "pid_alive",
                                  side_effect=AssertionError("evaluate checked a pid")):
            nudges, _, _ = self.ev(self.green(self.V, 0), orphans=orphans)
        self.assertEqual(nudges, [
            "2 watches left by a Claude Code process that has ended: w-1 (the build), w-2. "
            "Pick one up with `delegation-ledger wait --resume <id>`, or drop it with "
            "`delegation-ledger wait --drop <id>`."])


class Hook(StateTest):
    def setUp(self):
        super().setUp()
        for name in ("cc_version", "launch_background"):
            self.addCleanup(setattr, checks, name, getattr(checks, name))
        checks.cc_version = lambda timeout=10: "2.1.300"
        self.launched = []
        checks.launch_background = self.launched.append
        self.out = []

    def settled(self):
        checks.update_state("canary.json", quick=ok_quick("2.1.300"),
                            green_full={"version": "2.1.300", "ts": checks.dc.now_iso()})
        checks.update_state("audit.json", ts=checks.dc.now_iso())

    def test_nothing_due_prints_nothing(self):
        self.settled()
        self.assertEqual(checks.hook_main("{}", out=self.out.append), 0)
        self.assertEqual((self.out, self.launched), ([], []))

    def test_a_new_version_launches_and_records_the_start(self):
        checks.hook_main("{}", out=self.out.append)
        self.assertEqual(self.launched, [["quick", "audit"]])
        self.assertIn("bg_started", self.state("due.json"))
        checks.hook_main("{}", out=self.out.append)
        self.assertEqual(len(self.launched), 1)  # throttled

    def test_output_is_a_system_message_only(self):
        self.write_due('[[item]]\ndate = 2020-01-01\ndo = "check the thing"\n')
        checks.hook_main("{}", out=self.out.append)
        (line,) = self.out
        obj = json.loads(line)
        self.assertIn("check the thing", obj["systemMessage"])
        self.assertEqual(set(obj), {"systemMessage"})  # for Hayden, not the model's context

    def test_audit_warnings_are_marked_shown(self):
        checks.update_state("audit.json", ts=checks.dc.now_iso(), warns=["x"], shown=False)
        checks.hook_main("{}", out=self.out.append)
        self.assertTrue(self.state("audit.json")["shown"])

    def test_newer_warnings_are_not_marked_shown(self):
        checks.update_state("audit.json", ts=checks.dc.now_iso(), warns=["new"], shown=False)
        checks.mark_shown(["old"])
        self.assertFalse(self.state("audit.json")["shown"])

    def test_a_headless_session_prints_nothing_and_marks_nothing(self):
        checks.update_state("audit.json", ts=checks.dc.now_iso(), warns=["x"], shown=False)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "0"}):
            checks.hook_main("{}", out=self.out.append)
        self.assertEqual(self.out, [])
        self.assertFalse(self.state("audit.json")["shown"])
        self.assertEqual(self.launched, [["quick"]])  # the cheap checks still start

    def test_the_nudge_survives_a_failed_launch(self):
        def boom(jobs):
            raise OSError("fork failed")
        checks.launch_background = boom
        checks.hook_main("{}", out=self.out.append)
        self.assertEqual(len(self.out), 1)
        with open(checks.state_path("delegation-ledger.err")) as f:
            self.assertIn("fork failed", f.read())

    def ledger(self, *lines):
        os.makedirs(checks.dc.state_dir(), exist_ok=True)
        with open(checks.dc.ledger_path(), "w") as f:
            f.writelines(line + "\n" for line in lines)

    def test_a_month_old_ledger_asks_for_the_monthly_audit(self):
        self.settled()
        self.ledger(json.dumps({"ts": iso(checks.time.time() - 31 * DAY)}),
                    json.dumps({"ts": checks.dc.now_iso()}))
        checks.hook_main("{}", out=self.out.append)
        (line,) = self.out
        self.assertIn("monthly audit is due", json.loads(line)["systemMessage"])
        checks.update_state("audit.json", monthly=checks.dc.now_iso())
        self.out.clear()
        checks.hook_main("{}", out=self.out.append)
        self.assertEqual(self.out, [])

    def test_first_row_ts_reads_one_line_and_fails_soft(self):
        self.assertIsNone(checks.dc.first_row_ts())  # no ledger
        self.ledger()
        self.assertIsNone(checks.dc.first_row_ts())  # empty
        self.ledger("not json", "[1]", json.dumps({"ts": "x"}))
        self.assertIsNone(checks.dc.first_row_ts())  # nothing with a valid ts
        # A damaged head neither silences the nudge nor fires it early: the first row with a
        # valid ts wins.
        self.ledger("torn {", json.dumps({"ts": "x"}), json.dumps({"ts": "2026-09-30T05:16:58Z"}),
                    json.dumps({"ts": "2026-10-01T00:00:00Z"}))
        self.assertEqual(checks.dc.first_row_ts(), "2026-09-30T05:16:58Z")

    def test_a_malformed_due_file_is_named_not_silent(self):
        self.settled()
        self.write_due("[[item]]\ndate = not-a-date\n")
        self.assertEqual(checks.hook_main("{}", out=self.out.append), 0)
        (line,) = self.out
        self.assertIn("due.toml is malformed", json.loads(line)["systemMessage"])

    def test_an_item_without_a_do_string_is_malformed(self):
        self.write_due("[[item]]\ndate = 2026-10-07\n")
        with self.assertRaises(ValueError):
            checks.load_items()

    def test_a_missing_due_file_has_no_items(self):
        self.assertEqual(checks.load_items(), [])

    def test_the_child_guard_blocks_a_real_launch(self):
        with mock.patch.object(checks.subprocess, "Popen",
                               side_effect=AssertionError("launched under the child guard")):
            REAL_LAUNCH(["quick"])  # StateTest sets the guard


class Orphans(StateTest):
    """Watches left by a Claude Code process that has ended. A temp HOME whose one live
    session, s1, is this process; every other check is settled, so the watch nudge is the only
    one."""

    def setUp(self):
        super().setUp()
        home = os.path.join(self.tmp.name, "home")
        sessions = os.path.join(home, ".claude", "sessions")
        os.makedirs(sessions)
        with open(os.path.join(sessions, "1.json"), "w") as f:
            json.dump({"pid": os.getpid(), "procStart": checks.dc.proc_start(os.getpid()),
                       "sessionId": "s1"}, f)
        patcher = mock.patch.dict(os.environ, {"HOME": home})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Inside the sandbox the lead's CLAUDE_PID is inherited but invisible, and SANDBOX_RUNTIME
        # is set, either of which would hide every watch. The sandbox test sets CLAUDE_PID.
        os.environ.pop("CLAUDE_PID", None)
        os.environ.pop("SANDBOX_RUNTIME", None)
        for name in ("cc_version", "launch_background"):
            self.addCleanup(setattr, checks, name, getattr(checks, name))
        checks.cc_version = lambda timeout=10: "2.1.300"
        checks.launch_background = lambda jobs: None
        checks.update_state("canary.json", quick=ok_quick("2.1.300"),
                            green_full={"version": "2.1.300", "ts": checks.dc.now_iso()})
        checks.update_state("audit.json", ts=checks.dc.now_iso())
        self.watches = checks.dc.watches_dir()
        os.makedirs(self.watches)
        self.out = []

    def watch(self, wid="w-1", sid="gone", state="open", live=False, desc="the build",
              **fields):
        w = {"id": wid, "session_id": sid, "state": state, "description": desc,
             "condition": {"file": os.path.join(self.tmp.name, "never")},
             "created": checks.dc.now_iso(),
             "waiter_pid": os.getpid() if live else DEAD,
             "waiter_start": checks.dc.proc_start(os.getpid()) if live else None,
             "waiter_heartbeat": checks.dc.now_iso(), "poll_s": 15, "blocked_at": None}
        w.update(fields)
        checks.dc.write_json(os.path.join(self.watches, f"{wid}.json"), w)

    def message(self, payload="{}"):
        self.out.clear()
        self.assertEqual(checks.hook_main(payload, out=self.out.append), 0)
        return json.loads(self.out[0])["systemMessage"] if self.out else ""

    def test_an_orphaned_open_watch_is_named_with_its_commands(self):
        self.watch()
        self.assertEqual(self.message(), (
            "Delegation checks: (1) 1 watch left by a Claude Code process that has ended: w-1 "
            "(the build). Pick one up with `delegation-ledger wait --resume <id>`, or drop it "
            "with `delegation-ledger wait --drop <id>`."))

    def test_an_acknowledged_watch_is_named_too(self):
        self.watch(state="acknowledged")
        self.assertIn("1 watch left by a Claude Code process that has ended: w-1 (the build).",
                      self.message())

    def test_a_live_sessions_watch_is_not_named(self):
        self.watch(sid="s1")
        self.assertEqual(self.message(), "")

    def test_the_starting_session_counts_as_live(self):
        self.watch(sid="s2")
        self.assertEqual(self.message(json.dumps({"session_id": "s2"})), "")
        self.assertIn("w-1 (the build)", self.message(json.dumps({"session_id": "s3"})))
        self.assertIn("w-1 (the build)", self.message("not json"))  # nothing to spare

    def test_a_watch_whose_claude_process_runs_is_not_named(self):
        # That process adopts it at its next stop, under its new session id (a /clear).
        self.watch(claude_pid=os.getpid(), claude_start=checks.dc.proc_start(os.getpid()))
        self.assertEqual(self.message(), "")

    def test_a_watch_whose_claude_process_ended_is_named_even_in_a_live_session(self):
        # A crash, then claude --continue: the session runs on, but its waiter's exit is lost.
        self.watch(sid="s1", live=True, claude_pid=DEAD, claude_start=None)
        self.assertIn("w-1 (the build; its waiter is still running)", self.message())
        self.assertIn("w-1 (the build", self.message(json.dumps({"session_id": "s1"})))

    def test_a_live_waiter_of_an_ended_session_is_named_too(self):
        # A bare waiter outlives a SIGKILLed Claude Code, and its exit reaches nobody.
        self.watch(live=True)
        self.assertIn("1 watch left by a Claude Code process that has ended: w-1 (the build; "
                      "its waiter is still running).", self.message())

    def test_an_unknown_session_counts_only_once_its_waiter_is_dead(self):
        self.watch(sid="unknown", live=True)
        self.assertEqual(self.message(), "")
        self.watch(sid="unknown")
        self.assertIn("w-1 (the build)", self.message())

    def test_ended_watches_are_not_named(self):
        for state in checks.dc.ENDED:
            self.watch(f"w-{state}", state=state)
        self.assertEqual(self.message(), "")

    def unheard(self, wid="w-1", sid="gone", state="done", ended=None, **fields):
        """A watch that ended while its Claude process was gone, so nobody heard."""
        self.watch(wid, sid=sid, state=state, ended=ended or checks.dc.now_iso(),
                   claude_pid=DEAD, claude_start=None, **dict({"reported": False}, **fields))

    def read(self, wid="w-1"):
        return checks.dc.read_watch(wid)

    def test_an_end_nobody_heard_is_named_once(self):
        # After a crash, a plain `claude` starts a new session id, so no guard says it.
        self.unheard()
        self.assertEqual(self.message(json.dumps({"session_id": "s-new"})), (
            "Delegation checks: (1) 1 watch ended while no Claude Code process was listening: "
            "w-1 (the build, done). Check the results."))
        self.assertIs(self.read()["reported"], True)
        self.assertEqual(self.message(json.dumps({"session_id": "s-new"})), "")

    def test_the_starting_sessions_own_unheard_end_is_left_to_its_guard(self):
        # claude --continue keeps the id, and its guard says it to the model at the first stop.
        self.unheard(sid="s2")
        self.assertEqual(self.message(json.dumps({"session_id": "s2"})), "")
        self.assertIs(self.read()["reported"], False)

    def test_a_headless_session_doesnt_use_up_an_unheard_end(self):
        self.unheard()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "0"}):
            self.assertEqual(self.message(), "")
        self.assertIs(self.read()["reported"], False)

    def test_only_the_named_unheard_ends_are_marked(self):
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        for i in (4, 3, 2, 1):  # w-1 ended first
            self.unheard(f"w-{i}", desc=f"job {i}", ended=iso(now - 60 + i),
                         state="failed" if i == 2 else "done")
        self.assertIn("4 watches ended while no Claude Code process was listening: w-1 (job 1, "
                      "done), w-2 (job 2, failed), w-3 (job 3, done) and 1 more.", self.message())
        self.assertEqual([self.read(f"w-{i}")["reported"] for i in (1, 2, 3, 4)],
                         [True, True, True, False])

    def test_an_end_from_before_reported_existed_isnt_named(self):
        self.watch(state="done", ended=checks.dc.now_iso(), claude_pid=DEAD, claude_start=None)
        self.assertEqual(self.message(), "")

    def test_more_than_three_list_the_three_oldest_and_count_the_rest(self):
        for i in (5, 4, 3, 2, 1):
            self.watch(f"w-{i}", desc=f"job {i}", created=iso(NOW + i))
        msg = self.message()
        self.assertIn("5 watches left by a Claude Code process that has ended: w-1 (job 1), "
                      "w-2 (job 2), w-3 (job 3) and 2 more. Pick one up", msg)
        self.assertNotIn("w-4", msg)

    def torn(self, wid="w-torn"):
        with open(os.path.join(self.watches, f"{wid}.json"), "w") as f:
            f.write("{torn")

    def errors(self):
        with open(checks.state_path("delegation-ledger.err")) as f:
            return f.read()

    def test_a_damaged_file_is_counted_and_the_healthy_orphan_still_listed(self):
        self.watch()
        self.torn()
        self.assertEqual(self.message(), (
            "Delegation checks: (1) 1 watch left by a Claude Code process that has ended: w-1 "
            "(the build). Pick one up with `delegation-ledger wait --resume <id>`, or drop it "
            "with `delegation-ledger wait --drop <id>`. (1 watch file couldn't be read; see "
            "delegation-ledger.err)"))
        self.assertIn("w-torn: damaged file", self.errors())

    def test_only_damaged_files_give_the_count_alone(self):
        self.torn()
        self.watch("w-odd", session_id=["not", "an", "id"])  # parses, but can't be judged
        self.assertEqual(self.message(), "Delegation checks: (1) 2 watch files couldn't be "
                                         "read; see delegation-ledger.err.")
        self.assertIn("w-odd.json: TypeError", self.errors())

    def test_an_error_outside_the_file_reads_drops_only_this_nudge(self):
        self.watch()
        self.write_due('[[item]]\ndate = 2020-01-01\ndo = "check the thing"\n')
        with mock.patch.object(checks.dc, "live_sessions", side_effect=OSError("no sessions")):
            msg = self.message()
        self.assertIn("check the thing", msg)
        self.assertNotIn("watch", msg)
        self.assertIn("no sessions", self.errors())

    def test_a_headless_session_prints_nothing(self):
        self.watch()
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "0"}):
            self.assertEqual(self.message(), "")

    def test_a_sandboxed_run_names_none(self):
        # Where the session's own pid can't be seen, every waiter and session reads as dead.
        self.watch()
        with mock.patch.dict(os.environ, {"CLAUDE_PID": str(DEAD)}):
            self.assertEqual(self.message(), "")


class AuditStamp(StateTest):
    def stamp(self, hours, warns, shown, at):
        checks.stamp_audit(hours, [f"WARN {w}" for w in warns] + ["ok   fine"], shown, now=at)
        return self.state("audit.json")

    def test_a_narrow_manual_audit_does_not_move_the_stamp(self):
        self.stamp(168, [], True, NOW)
        st = self.stamp(1, [], True, NOW + 20 * 3600)  # covers only the last hour
        self.assertEqual(st["ts"], iso(NOW))

    def test_a_covering_audit_moves_it(self):
        self.stamp(168, [], True, NOW)
        self.assertEqual(self.stamp(21, [], True, NOW + 20 * 3600)["ts"], iso(NOW + 20 * 3600))

    def test_unseen_warnings_are_kept_and_merged(self):
        self.stamp(168, ["a"], False, NOW)
        st = self.stamp(25, ["a", "b"], False, NOW + DAY)
        self.assertEqual((st["warns"], st["shown"]), (["a", "b"], False))
        st = self.stamp(25, ["c"], True, NOW + 2 * DAY)  # a manual run printed its own
        self.assertEqual((st["warns"], st["shown"]), (["a", "b"], False))

    def test_no_warnings_is_shown(self):
        self.assertTrue(self.stamp(168, [], False, NOW)["shown"])


class Background(StateTest):
    def test_a_held_lock_skips_the_job(self):
        self.addCleanup(setattr, checks, "run_quick", checks.run_quick)
        checks.run_quick = lambda v: self.fail("ran while another job held the lock")
        os.makedirs(checks.dc.state_dir(), exist_ok=True)
        with open(checks.state_path("checks.lock"), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            self.assertEqual(checks.background(["quick"]), 0)

    def test_a_fresh_audit_is_not_rerun(self):
        checks.update_state("audit.json", ts=checks.dc.now_iso(), hours=168.0)
        self.addCleanup(setattr, checks.subprocess, "run", checks.subprocess.run)
        checks.subprocess.run = lambda *a, **k: self.fail("reran a fresh audit")
        checks.background(["audit"])

    def test_a_crashing_audit_becomes_a_warning(self):
        crash = os.path.join(self.tmp.name, "crash.py")
        with open(crash, "w") as f:
            f.write("import sys\nsys.stderr.write('Traceback\\nKeyError: boom\\n')\nsys.exit(3)\n")
        self.addCleanup(setattr, checks, "LEDGER", checks.LEDGER)
        checks.LEDGER = crash
        checks.background(["audit"])
        st = self.state("audit.json")
        self.assertIn("crashed (exit 3): KeyError: boom", st["warns"][0])
        self.assertFalse(st["shown"])


class CLI(StateTest):
    """Through the real delegation-ledger, as the hook shim runs it."""

    def ledger(self, *args, stdin=""):
        return subprocess.run([sys.executable, LEDGER, *args], input=stdin, text=True,
                              capture_output=True, env=dict(os.environ))

    def rows(self, *rows):
        os.makedirs(checks.dc.state_dir(), exist_ok=True)
        with open(os.path.join(checks.dc.state_dir(), "delegations.jsonl"), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def test_audit_writes_the_stamp(self):
        self.ledger("audit")
        st = self.state("audit.json")
        self.assertEqual((st["shown"], st["warns"], st["hours"]), (True, [], 168.0))
        self.ledger("audit", "--hours", "2", "--unshown")
        self.assertEqual(self.state("audit.json")["hours"], 2.0)

    def test_audit_pairs_a_writer_that_spans_the_window_edge(self):
        now = checks.time.time()
        base = {"runner": "claude", "id": "w1", "agent_type": "writer"}
        self.rows(dict(base, event="start", ts=iso(now - 3 * 3600), main_before="aaa"),
                  dict(base, event="stop", ts=iso(now - 600), main_after="bbb"))
        p = self.ledger("audit", "--hours", "1")
        self.assertIn("WARN main checkout changed while writer w1", p.stdout)

    def test_hook_mode_exits_zero_and_names_a_malformed_due_file(self):
        self.write_due("this is not toml [[[")
        p = self.ledger("due", "--hook", stdin='{"hook_event_name":"SessionStart"}')
        self.assertEqual(p.returncode, 0)
        self.assertIn("due.toml is malformed", json.loads(p.stdout)["systemMessage"])

    def test_the_shim_exits_zero(self):
        with open(os.path.join(HOOKS, "delegation-due.sh")) as f:
            self.assertTrue(f.read().rstrip().endswith("exit 0"))
        self.assertTrue(os.access(os.path.join(HOOKS, "delegation-due.sh"), os.X_OK))


if __name__ == "__main__":
    unittest.main()
