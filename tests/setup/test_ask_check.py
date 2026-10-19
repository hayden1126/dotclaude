"""hooks/ask-check.sh: the PreToolUse(AskUserQuestion) check on risky asks (stdlib only).

A risky ask is denied once, before the dialog, with a checklist as the reason; the resend in the
same window passes. The transcripts are synthetic, in the shapes 2.1.304 writes (lane ask-check's
probe): a typed prompt is a user entry with origin.kind "human", a tool_use sits in an assistant
entry, its tool_result in the next user entry (is_error and "PreToolUse:<tool> hook error:
<reason>" on a deny), an agent's notice is a user entry with origin.kind "task-notification".
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "hooks", "ask-check.sh")
SKILL = os.path.join(REPO, "skills", "lanes", "SKILL.md")
sys.path.insert(0, os.path.join(REPO, "tests", "lanes"))
from _fixture import LanesRepo  # noqa: E402  (on sys.path from the line above)

SID = "6f1d2c3b-8a9e-4f00-b1c2-d3e4f5a6b7c8"
NOTICE = ("<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n"
          "<summary>Agent \"Map the hooks\" finished</summary>\n<result>{}</result>\n"
          "</task-notification>")
SHELL_NOTICE = ("<task-notification>\n<task-id>b2</task-id>\n<status>completed</status>\n"
                "<summary>Background command \"run tests\" completed (exit code 0)</summary>\n"
                "</task-notification>")


def load_module():
    spec = importlib.util.spec_from_file_location("ask_check",
                                                  os.path.join(REPO, "hooks", "ask_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def typed(text="go on"):
    return {"type": "user", "origin": {"kind": "human"}, "message": {"role": "user",
                                                                     "content": text}}


def notice(text=NOTICE, kind="task-notification"):
    return {"type": "user", "origin": {"kind": kind}, "message": {"role": "user", "content": text}}


def use(tid, name, **inp):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def result(tid, content="ok", error=False, tur=None):
    block = {"tool_use_id": tid, "type": "tool_result", "content": content}
    if error:
        block["is_error"] = True
    row = {"type": "user", "message": {"role": "user", "content": [block]}}
    if tur is not None:
        row["toolUseResult"] = tur
    return row


def denied(tid, prefix="PreToolUse:AskUserQuestion hook error: ", blocks=False):
    text = prefix + "ask-check: this ask was held back before the dialog, since ..."
    return result(tid, [{"type": "text", "text": text}] if blocks else text, error=True,
                  tur="Error: " + text)


def answered(tid):
    return result(tid, 'User has answered your questions: "Tea or coffee?"="Tea".',
                  tur={"questions": [], "answers": {"Tea or coffee?": "Tea"}})


def agent_done(tid):
    return result(tid, [{"type": "text", "text": "Found three hooks."}],
                  tur={"status": "completed", "prompt": "map the hooks"})


def agent_launched(tid):
    return result(tid, [{"type": "text", "text": "Async agent launched successfully."}],
                  tur={"status": "async_launched", "isAsync": True})


def report_rows(checks=0):
    """A foreground agent's report, then checks Read calls with their results."""
    rows = [use("t-agent", "Agent", prompt="map"), agent_done("t-agent")]
    for i in range(checks):
        rows += [use(f"t-read{i}", "Read", file_path="/x"), result(f"t-read{i}")]
    return rows


def question(text="Tea or coffee?", *options):
    return {"question": text, "header": "Drink", "multiSelect": False,
            "options": [{"label": o, "description": o} for o in (options or ("Tea", "Coffee"))]}


class Harness:
    """Writes self.transcript and fires the hook; the test class supplies tmp, env and cwd."""

    def entries(self, rows):
        with open(self.transcript, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "permission-mode", "permissionMode": "default"}) + "\n")
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n")

    def fire(self, *questions, **extra):
        event = {"session_id": SID, "transcript_path": self.transcript, "cwd": self.cwd,
                 "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                 "permission_mode": "default", "tool_use_id": "t-ask",
                 "tool_input": {"questions": list(questions) or [question()]}, **extra}
        p = subprocess.run(["bash", HOOK], input=json.dumps(event), capture_output=True,
                           text=True, env=self.env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None

    def log(self):
        try:
            with open(os.path.join(self.env["XDG_STATE_HOME"], "dotclaude",
                                   "ask-check.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def assertDenied(self, out, *rules):
        self.assertIsNotNone(out, "expected a deny")
        self.assertEqual(out["permissionDecision"], "deny")
        reason = out["permissionDecisionReason"]
        self.assertTrue(reason.startswith(load_module().MARKER), reason)
        for item in load_module().CHECKLIST:
            self.assertIn(item, reason)
        self.assertIn("deny " + ",".join(rules), self.log())
        return reason


class Check(Harness, unittest.TestCase):
    """Outside any git repo: the report, ticks and window rules."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.cwd = os.path.join(self.tmp, "work")
        os.makedirs(self.cwd)
        os.makedirs(os.path.join(self.tmp, ".git"))  # /tmp/.git exists on HAYPC: stop the walk
        self.transcript = os.path.join(self.tmp, SID + ".jsonl")
        self.env = dict(os.environ, XDG_STATE_HOME=os.path.join(self.tmp, "state"))
        self.env.pop("GIT_DIR", None)

    def test_a_plain_ask_passes_silently(self):
        self.entries([typed()])
        self.assertIsNone(self.fire())
        self.assertEqual(self.log(), "")

    def test_an_agent_report_with_no_check_after_it_is_denied(self):
        self.entries([typed(), *report_rows(checks=0)])
        reason = self.assertDenied(self.fire(), "report")
        self.assertIn("0 checks", reason)

    def test_one_check_after_a_report_is_still_thin_two_clear_it(self):
        self.entries([typed(), *report_rows(checks=1)])
        self.assertIn("1 check ", self.assertDenied(self.fire(), "report"))
        self.entries([typed(), *report_rows(checks=2)])
        self.assertIsNone(self.fire())

    def test_glob_grep_and_bash_count_as_checks_and_edit_does_not(self):
        rows = [typed(), *report_rows(), use("g", "Grep", pattern="x"), result("g"),
                use("b", "Bash", command="ls"), result("b")]
        self.entries(rows)
        self.assertIsNone(self.fire())
        rows = [typed(), *report_rows(), use("e", "Edit", file_path="/x"), result("e"),
                use("w", "Write", file_path="/x"), result("w")]
        self.entries(rows)
        self.assertDenied(self.fire(), "report")

    def test_a_task_notification_from_an_agent_is_a_report(self):
        self.entries([typed(), notice()])
        self.assertDenied(self.fire(), "report")

    def test_a_subagent_hand_back_is_a_report(self):
        self.entries([typed(), notice("<agent-message from=\"w\">[Subagent hand-back] done",
                                      kind="peer")])
        self.assertDenied(self.fire(), "report")

    def test_a_background_command_notice_or_an_agent_launch_is_no_report(self):
        self.entries([typed(), notice(SHELL_NOTICE), use("a", "Agent", prompt="x"),
                      agent_launched("a")])
        self.assertIsNone(self.fire())

    def test_checks_count_after_the_newest_report_only(self):
        rows = [typed(), *report_rows(checks=3), notice()]
        self.entries(rows)
        self.assertDenied(self.fire(), "report")

    def test_a_typed_prompt_after_the_report_starts_a_new_window(self):
        self.entries([typed(), *report_rows(), typed("now ask me")])
        self.assertIsNone(self.fire())

    def test_an_answered_ask_or_an_approved_plan_starts_a_new_window(self):
        self.entries([typed(), *report_rows(), use("q", "AskUserQuestion"), answered("q")])
        self.assertIsNone(self.fire())
        self.entries([typed(), *report_rows(), use("p", "ExitPlanMode"),
                      result("p", "User has approved your plan.")])
        self.assertIsNone(self.fire())

    def test_a_rejected_plan_keeps_the_window(self):
        self.entries([typed(), *report_rows(), use("p", "ExitPlanMode"),
                      result("p", "The user doesn't want to proceed", error=True)])
        self.assertDenied(self.fire(), "report")

    def test_meta_and_injected_user_rows_are_no_boundary(self):
        meta = {"type": "user", "isMeta": True, "origin": {"kind": "human"},
                "message": {"role": "user", "content": "skill body"}}
        self.entries([typed(), *report_rows(), meta, notice(SHELL_NOTICE),
                      notice("<cross-session-message>hi</cross-session-message>", kind="peer")])
        self.assertDenied(self.fire(), "report")

    def test_subagent_rows_are_ignored(self):
        side = dict(agent_done("s"), isSidechain=True)
        self.entries([typed(), use("s", "Agent", prompt="x"), side])
        self.assertIsNone(self.fire())

    def test_four_backticked_names_are_denied_three_pass(self):
        self.entries([typed()])
        three = question("Should `a_b` call `c_d` or `e_f`?")
        self.assertIsNone(self.fire(three))
        four = question("Should `a_b` call `c_d` or `e_f` before `g_h`?")
        reason = self.assertDenied(self.fire(four), "ticks")
        self.assertIn("4 backticked names", reason)

    def test_backticks_add_up_across_questions_but_not_options(self):
        self.entries([typed()])
        self.assertDenied(self.fire(question("`a1` or `b2`?"), question("`c3` or `d4`?")), "ticks")
        opts = question("Which?", "`a1` `b2`", "`c3` `d4` `e5`")
        self.assertIsNone(self.fire(opts))

    def test_the_resend_after_a_deny_passes(self):
        self.entries([typed(), *report_rows(), use("q1", "AskUserQuestion"), denied("q1")])
        self.assertIsNone(self.fire())
        self.assertIn("pass already-denied", self.log())

    def test_the_hooks_own_reason_lets_its_resend_through(self):
        # Round trip: the reason fire() printed, written back as Claude Code writes a deny.
        rows = [typed(), *report_rows()]
        self.entries(rows)
        reason = self.assertDenied(self.fire(), "report")
        text = "PreToolUse:AskUserQuestion hook error: " + reason
        self.entries(rows + [use("q1", "AskUserQuestion"),
                             result("q1", text, error=True, tur="Error: " + text)])
        self.assertIsNone(self.fire())

    def test_the_deny_is_found_past_big_rows_after_it(self):
        mod = load_module()
        mod.TAIL_MAX = mod.CHUNK = 4096
        blob = {"type": "api-request-blob", "blob": "z" * 20000,
                "messages": [{"role": "user", "content": "x"}]}
        self.entries([typed(), *report_rows(), use("q1", "AskUserQuestion"), denied("q1"),
                      blob, blob])
        self.assertTrue(mod.window(self.transcript)["denied"])
        mod.READ_MAX = 8192
        self.assertFalse(mod.window(self.transcript)["denied"])  # the hard cap still holds

    def test_the_deny_is_found_whatever_claude_code_wraps_it_in(self):
        # Only the reason's own opening is matched: a release may reword the prefix.
        for row in (denied("q1", prefix="PreToolUse:AskUserQuestion [bash x] blocked: "),
                    denied("q1", blocks=True)):
            with self.subTest(row=row["message"]["content"][0]["content"]):
                self.entries([typed(), *report_rows(), use("q1", "AskUserQuestion"), row])
                self.assertIsNone(self.fire())

    def test_a_deny_before_the_last_typed_prompt_does_not_count(self):
        self.entries([typed(), use("q1", "AskUserQuestion"), denied("q1"), typed("again"),
                      *report_rows()])
        self.assertDenied(self.fire(), "report")

    def test_a_deny_before_an_answer_does_not_count(self):
        self.entries([typed(), use("q1", "AskUserQuestion"), denied("q1"),
                      use("q2", "AskUserQuestion"), answered("q2"), *report_rows()])
        self.assertDenied(self.fire(), "report")

    def test_another_hooks_deny_is_not_this_ones(self):
        other = result("q1", "PreToolUse:AskUserQuestion hook error: subagent-policy: no",
                       error=True)
        self.entries([typed(), *report_rows(), use("q1", "AskUserQuestion"), other])
        self.assertDenied(self.fire(), "report")

    def test_both_rules_are_named_in_one_reason(self):
        self.entries([typed(), *report_rows()])
        reason = self.assertDenied(self.fire(question("`a1` `b2` `c3` `d4`?")), "report", "ticks")
        self.assertIn("subagent report", reason)
        self.assertIn("backticked", reason)

    def test_a_subagent_payload_is_skipped(self):
        self.entries([typed(), *report_rows()])
        self.assertIsNone(self.fire(agent_id="a123", agent_type="Explore"))

    def test_another_tool_is_skipped(self):
        self.entries([typed(), *report_rows()])
        self.assertIsNone(self.fire(tool_name="Read"))

    def test_no_transcript_allows_since_a_resend_could_never_pass(self):
        self.transcript = os.path.join(self.tmp, "gone.jsonl")
        self.assertIsNone(self.fire(question("`a1` `b2` `c3` `d4`?")))

    def test_junk_and_deep_lines_are_skipped(self):
        self.entries([typed(), *report_rows()])
        with open(self.transcript, "a") as f:
            f.write('{"type":"user" not json\n{"type":"user","x":' + "[" * 100000 + "\n")
        self.assertDenied(self.fire(), "report")

    def test_a_last_line_with_no_newline_is_read(self):
        self.entries([typed()])
        with open(self.transcript, "a") as f:
            f.write(json.dumps(notice(), separators=(",", ":")))
        self.assertDenied(self.fire(), "report")

    def test_a_report_past_the_cap_is_out_of_the_window(self):
        mod = load_module()
        mod.TAIL_MAX = mod.CHUNK = 4096
        big = use("e", "Edit", file_path="/x", new_string="y" * 6000)
        self.entries([typed(), notice(), big, result("e")])
        self.assertFalse(mod.window(self.transcript)["report"])
        self.entries([typed(), notice(), use("e", "Edit", file_path="/x"), result("e")])
        self.assertTrue(mod.window(self.transcript)["report"])

    def test_a_crash_fails_open_and_is_logged(self):
        self.entries([typed()])
        self.assertIsNone(self.fire(tool_input={"questions": "not a list"}))
        self.assertIn("error", self.log())

    def test_the_window_is_read_past_one_chunk(self):
        big = use("e", "Edit", file_path="/x", new_string="y" * (2 * load_module().CHUNK))
        self.entries([typed(), notice(), big, result("e")])
        self.assertDenied(self.fire(), "report")
        self.entries([notice(), typed(), big, result("e")])
        self.assertIsNone(self.fire())

    def test_the_checklist_matches_the_lanes_skill(self):
        with open(SKILL) as f:
            text = f.read()
        for i, item in enumerate(load_module().CHECKLIST, 1):
            self.assertIn(f"{i}. {item}", text)


class CrossLane(Harness, LanesRepo):
    """A real lanes repo (tests/lanes/_fixture.py): lanes alpha and beta, beta changing files."""

    def setUp(self):
        super().setUp()
        self.lane("new", "alpha")
        self.lane("new", "beta")
        self.beta = self.lane_path("beta")
        for d in ("hooks", "skills", "docs"):
            os.makedirs(os.path.join(self.beta, d))
        self.commit("hooks/stop_ring.py", "x\n", cwd=self.beta)
        self.commit("settings.json", "{}\n", cwd=self.beta)
        self.cwd = self.lane_path("alpha")
        self.transcript = os.path.join(self.tmp, SID + ".jsonl")
        self.entries([typed()])

    def brief(self, lane_id, expected):
        path = self.record(lane_id)
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(text.replace("- Expected files: <files>", f"- Expected files: {expected}"))

    def test_another_lanes_committed_file_unnamed_is_denied(self):
        reason = self.assertDenied(self.fire(question("Change hooks/stop_ring.py?")), "lane")
        self.assertIn("lane beta", reason)
        self.assertIn("hooks/stop_ring.py", reason)

    def test_absolute_and_dot_paths_match_and_longer_names_do_not(self):
        for text in ("Change /home/h/proj/hooks/stop_ring.py?", "Change ./hooks/stop_ring.py?",
                     "Change ~/.claude/hooks/stop_ring.py?", "It's in hooks/stop_ring.py."):
            with self.subTest(text=text):
                self.assertDenied(self.fire(question(text)), "lane")
        for text in ("Change hooks/my_stop_ring.py?", "Restore hooks/stop_ring.py.bak?"):
            with self.subTest(text=text):
                self.assertIsNone(self.fire(question(text)))

    def test_a_long_basename_matches_too_and_a_short_one_only_by_path(self):
        self.assertDenied(self.fire(question("Change stop_ring.py's timer?")), "lane")
        self.commit("lib.py", "x\n", cwd=self.beta)
        self.assertIsNone(self.fire(question("Change lib.py?")))

    def test_naming_the_lane_passes(self):
        self.assertIsNone(self.fire(question("hooks/stop_ring.py is lane beta's; touch it?")))

    def test_the_askers_own_lane_files_pass(self):
        os.makedirs(os.path.join(self.cwd, "hooks"))
        self.commit("hooks/mine_only.py", "x\n", cwd=self.cwd)
        self.assertIsNone(self.fire(question("Change hooks/mine_only.py?")))

    def test_the_main_checkout_counts_every_live_lane(self):
        self.cwd = self.main
        self.assertDenied(self.fire(question("Change hooks/stop_ring.py?")), "lane")

    def test_expected_files_count_before_any_commit(self):
        self.brief("alpha", "x")
        self.brief("beta", "skills/lanes/scripts/lane, docs/lanes.md (the S3 part) tests/lanes")
        self.assertDenied(self.fire(question("Edit skills/lanes/scripts/lane?")), "lane")
        self.assertDenied(self.fire(question("Edit docs/lanes.md's intro?")), "lane")
        self.assertIsNone(self.fire(question("Add a case in tests/lanes/test_cli.py?")))

    def test_prose_with_a_slash_is_no_entry_and_a_glob_matches_its_files(self):
        self.brief("beta", "the and/or rules, skills/lanes/*.py /etc/hosts.txt docs/**/*.md")
        self.assertIsNone(self.fire(question("Edit /etc/hosts.txt?")))
        self.assertDenied(self.fire(question("Edit docs/a/b/deep.md?")), "lane")
        self.assertIsNone(self.fire(question("Keep one and/or both?")))
        self.assertDenied(self.fire(question("Edit skills/lanes/lanelib_extra.py?")), "lane")
        self.assertIsNone(self.fire(question("Edit skills/lanes/SKILL.md?")))

    def test_a_deep_folder_entry_covers_paths_under_it_a_shallow_one_does_not(self):
        self.brief("beta", "skills/autopass/ hooks/")
        self.assertDenied(self.fire(question("Edit skills/autopass/state.py?")), "lane")
        self.assertDenied(self.fire(question("Add a file in skills/autopass/?")), "lane")
        self.assertIsNone(self.fire(question("Edit hooks/notify.sh?")))
        self.assertIsNone(self.fire(question("Does autopass fire?")))

    def test_generic_names_and_skipped_files_need_more(self):
        self.commit("STATUS.md", "x\n", cwd=self.beta)
        os.makedirs(os.path.join(self.beta, "skills", "pass"))
        self.commit("skills/pass/SKILL.md", "x\n", cwd=self.beta)
        self.assertIsNone(self.fire(question("Update STATUS.md and the SKILL.md wording?")))
        self.assertDenied(self.fire(question("Update skills/pass/SKILL.md?")), "lane")

    def test_a_lane_whose_worktree_is_gone_counts_for_nothing(self):
        shutil.rmtree(self.beta)
        self.assertIsNone(self.fire(question("Change hooks/stop_ring.py?")))

    def test_a_closed_lane_counts_for_nothing(self):
        lanes = os.path.join(self.common, "lanes")
        os.makedirs(os.path.join(lanes, "_closed"), exist_ok=True)
        os.rename(os.path.join(lanes, "beta"), os.path.join(lanes, "_closed", "beta-2026-10-19"))
        self.assertIsNone(self.fire(question("Change hooks/stop_ring.py?")))

    def test_a_symlinked_record_is_not_read(self):
        target = os.path.join(self.tmp, "elsewhere.md")
        with open(target, "w") as f:
            f.write("- Expected files: hooks/secret-tool.sh\n")
        status = self.record("beta")
        os.remove(status)
        os.symlink(target, status)
        self.assertIsNone(self.fire(question("Change hooks/secret-tool.sh?")))
        os.remove(status)  # the same line in the real file counts
        with open(status, "w") as f:
            f.write("- Expected files: hooks/secret-tool.sh\n")
        self.assertDenied(self.fire(question("Change hooks/secret-tool.sh?")), "lane")

    def test_a_switched_lane_is_read_by_its_checked_out_branch(self):
        self.git("switch", "-q", "-c", "feat/beta-two", cwd=self.beta)
        self.commit("hooks/notify_two.py", "x\n", cwd=self.beta)
        self.assertDenied(self.fire(question("Change hooks/notify_two.py?")), "lane")

    def test_a_plain_word_lane_id_is_named_only_as_a_lane(self):
        self.lane("new", "relay")
        relay = self.lane_path("relay")
        os.makedirs(os.path.join(relay, "bin"))
        self.commit("bin/relay-tool", "x\n", cwd=relay)
        for text in ("Does bin/relay-tool relay the paste?", "Edit bin/relay-tool?"):
            with self.subTest(text=text):
                self.assertDenied(self.fire(question(text)), "lane")
        for text in ("bin/relay-tool is lane relay's: edit it?", "Edit bin/relay-tool (`relay`)?",
                     "Ask the relay lane about bin/relay-tool?"):
            with self.subTest(text=text):
                self.assertIsNone(self.fire(question(text)))

    def test_a_lane_id_written_as_a_file_name_does_not_name_the_lane(self):
        self.lane("new", "stop-ring")
        ring = self.lane_path("stop-ring")
        os.makedirs(os.path.join(ring, "hooks"))
        self.commit("hooks/stop-ring.sh", "x\n", cwd=ring)
        self.assertDenied(self.fire(question("Edit hooks/stop-ring.sh?")), "lane")
        self.assertIsNone(self.fire(question("Edit hooks/stop-ring.sh (lane stop-ring's)?")))
        self.assertIsNone(self.fire(question("Ask stop-ring before editing hooks/stop-ring.sh?")))

    def test_a_failed_diff_costs_only_its_own_lane(self):
        self.lane("new", "gamma")
        gamma = self.lane_path("gamma")
        os.makedirs(os.path.join(gamma, "hooks"))
        self.commit("hooks/gamma_hook.py", "x\n", cwd=gamma)
        mod = load_module()
        real = mod.committed_files

        def slow_beta(repo, base, ref):
            if "beta" in ref:
                raise subprocess.TimeoutExpired("git", mod.GIT_WAIT)
            return real(repo, base, ref)

        text = "Change hooks/stop_ring.py and hooks/gamma_hook.py?"
        with mock.patch.object(mod, "committed_files", slow_beta):
            self.assertEqual(mod.lane_hits(text, self.cwd), [("gamma", "hooks/gamma_hook.py")])
        self.assertIn("diff unread lane=beta TimeoutExpired", self.log())

    def test_a_spent_budget_skips_the_lanes_left(self):
        mod = load_module()
        mod.LANE_BUDGET = -1
        self.assertEqual(mod.lane_hits("Change hooks/stop_ring.py?", self.cwd), [])
        self.assertIn("lane budget spent: skipped lane beta", self.log())

    def test_a_repo_without_lanes_runs_no_lane_lookup(self):
        plain = os.path.join(self.tmp, "plain")
        self.git("init", "-q", plain, cwd=self.tmp)
        mod = load_module()
        with mock.patch.object(mod, "worktree_heads", side_effect=AssertionError("looked up")):
            self.assertEqual(mod.lane_hits("Change hooks/stop_ring.py?", plain), [])

    def test_the_other_rules_hold_without_lanelib(self):
        mod = load_module()
        mod.lanelib, mod.LANELIB_ERROR = None, ImportError("gone")
        self.assertEqual(mod.lane_hits("Change hooks/stop_ring.py?", self.cwd), [])
        self.assertIn("lane rule off", self.log())


if __name__ == "__main__":
    unittest.main()
