"""Offline checks on the long-runs skill and its eval harness (no model calls)."""
import importlib.util
import json
import os
import re
import shutil
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def load_harness():
    spec = importlib.util.spec_from_file_location("long_runs_eval", os.path.join(HERE, "run.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = load_harness()
EM_DASH = chr(0x2014)
DENYLISTS = ("~/scratch/hackathon/denylist.txt", "~/scratch/exam-prep/denylist.txt")


def read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


def skill_text():
    return read("skills", "long-runs", "SKILL.md")


def frontmatter():
    return re.match(r"---\n(.*?)\n---\n", skill_text(), re.S).group(1)


def stream(*tools, reply="done", cost=0.25, skills=("long-runs",)):
    """A canned stream-json run: init, one assistant turn with these tool calls, the result."""
    return [
        {"type": "system", "subtype": "init", "skills": list(skills)},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": name, "input": inp} for name, inp in tools]}},
        {"type": "result", "total_cost_usd": cost, "num_turns": 2, "result": reply},
    ]


class SkillFile(unittest.TestCase):
    def test_it_loads_by_itself(self):
        self.assertRegex(frontmatter(), r"(?m)^name: long-runs$")
        self.assertRegex(frontmatter(), r"(?m)^description: Use when")
        self.assertNotIn("disable-model-invocation", frontmatter())

    def test_the_description_names_each_moment_and_fits(self):
        description = re.search(r"(?m)^description: (.*)$", frontmatter()).group(1)
        self.assertLess(len(description), 500)
        for word in ("start, plan or rerun", "release check", "CI", "lighter set", "time cost",
                     "after a rebase", "which checks ran", "Not for one quick command"):
            with self.subTest(word):
                self.assertIn(word, description)

    def test_the_skip_record_is_a_fixed_block_with_its_three_fields(self):
        # The guardrail: a skip is written down in these words, whoever reads it next.
        block = re.search(r"```\n(Skipped:.*?)```", skill_text(), re.S).group(1)
        self.assertEqual([line.split(":")[0] + ":" for line in block.splitlines()],
                         list(harness.SKIP_LABELS))

    def test_a_skip_never_reads_as_a_pass(self):
        self.assertIn("A skip never reads as a pass", skill_text())
        self.assertIn('never write "all green" over a partial run', skill_text())

    def test_an_unsafe_skip_says_so_instead_of_inventing_a_reason(self):
        self.assertIn("`Safe because: not shown`", skill_text())
        self.assertIn("`Caught by: nothing yet`", skill_text())
        self.assertIn("Never invent a reason", skill_text())

    def test_the_record_covers_unplanned_skips_and_reused_results(self):
        self.assertIn("planned or not", skill_text())
        self.assertIn("every result reused", skill_text())

    def test_the_guardrail_comes_before_the_plan(self):
        self.assertLess(skill_text().index("## Say what didn't run"),
                        skill_text().index("## Plan the run"))

    def test_required_gates_stay(self):
        self.assertIn("drops no gate the repo or the user requires", skill_text())

    def test_unknown_shared_state_is_answered_and_stays_apart_only_if_it_cant_be(self):
        # The baseline's failure: "keep them serial unless you know". The limit: with no way to
        # find out, parts that may share state must not run together.
        self.assertIn("not a default to serial", skill_text())
        self.assertIn("If neither route can settle it, keep those parts apart", skill_text())

    def test_the_measured_lessons_stay(self):
        self.assertIn("Timing-sensitive checks go last, on their own", skill_text())
        self.assertIn("Split a part further only with cores and memory to spare", skill_text())
        self.assertIn("an empty one can run the whole suite", skill_text())
        self.assertNotIn("load alone", skill_text())  # a quieter rerun doesn't isolate load

    def test_the_example_quotes_only_measured_figures(self):
        example = skill_text().split("## Example")[1].split("## See also")[0]
        for measured in (
            "about 2 h 37 min for one engine",  # the start wasn't logged; one engine against two
            "at least six lock waits nobody timed",  # the serial time holds waiting
            "isn't all parallelism",
            "Its slowest sweep waited on pages, not CPU",
            "The same checks at once in both engines, in one lock hold, took 40 min",  # 39 min 31 s
            "in that sweep: 0 of 15,370",  # the slowest sweep only, all ten runs of it
            "also took 40 min",  # the split run's whole sweep, 40 min 29 s
            "mean load of 59 in its main phase against 32",  # 59 covers that phase alone
            "5 of 15,370 page waits gave up",  # the split run's signal moved
            "Two things changed, so it can't say which did what",  # it split and moved two checks
            "it bought no time",  # 40 min 29 s against 39 min 31 s
            "At a load of 45",  # load has a cost, whatever the signal read
            "failed twice, then passed five of five on a quieter machine",
        ):
            self.assertIn(measured, example)
        for unmeasured in (
            "under 1",  # a load figure nobody measured
            "nearly all", "most of it",  # time shares nobody measured
            "38 min",  # the split run's first phase, not its sweep time
            "1,537", "1,500",  # one run of one sweep: 15,370 is the count across a run
        ):
            self.assertNotIn(unmeasured, example)

    def test_it_points_to_delegation_and_coding_practices_rather_than_repeating_them(self):
        self.assertIn("`delegation`", skill_text())
        self.assertIn("`coding-practices` rules 11 and 12", skill_text())
        rules = read("skills", "coding-practices", "SKILL.md")
        self.assertIn("11. **Verify claims by experiment.**", rules)
        self.assertIn("12. **Prove a change on the real path.**", rules)

    def test_no_em_dashes(self):
        self.assertNotIn(EM_DASH, skill_text())
        self.assertNotIn(EM_DASH, harness.claude_md_line())

    def test_no_private_name_in_what_this_lane_ships(self):
        shipped = skill_text() + read("tests", "long_runs", "cases.json")
        for path in DENYLISTS:
            path = os.path.expanduser(path)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                for word in f.read().split("\n"):
                    if word.strip() and not word.startswith("#"):
                        with self.subTest(path=path, word=word):
                            self.assertNotIn(word.strip().lower(), shipped.lower())


class Registered(unittest.TestCase):
    def test_claude_md_holds_the_always_loaded_rule(self):
        line = harness.claude_md_line()
        self.assertIn("load the `long-runs` skill", line)
        self.assertIn("Quote a time only from a measured run", line)
        self.assertIn("say unmeasured", line)

    def test_readme_lists_the_skill_and_its_tests(self):
        rows = read("README.md").splitlines()
        skills = next(line for line in rows if line.startswith("| `skills/` |"))
        self.assertIn("`long-runs`", skills)
        self.assertTrue(any(line.startswith("| `tests/long_runs/` |") for line in rows))

    def test_it_stays_off_codex_list(self):
        # CODEX_SKILLS is Hayden's list of portable skills, and this one names lanes.
        self.assertNotRegex(read("setup.sh"), r"CODEX_SKILLS=\(.*long-runs")


class Cases(unittest.TestCase):
    def setUp(self):
        self.cases = harness.load_cases()

    def test_every_case_is_complete(self):
        for case in self.cases:
            with self.subTest(case["id"]):
                self.assertIn(case["kind"], harness.KINDS)
                self.assertTrue(case["prompt"] and case["notes"])
                self.assertEqual("expect" in case, case["kind"] == "behaviour")

    def test_ids_are_unique(self):
        ids = [case["id"] for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_prompt_names_the_skill_or_says_to_go_faster(self):
        for case in self.cases:
            with self.subTest(case["id"]):
                self.assertNotRegex((case["prompt"] + case["notes"]).lower(),
                                    r"long-runs|\bskill\b|speed up|parallel")


class Plan(unittest.TestCase):
    CASES = [{"id": "a", "kind": "loads"}, {"id": "q", "kind": "quiet"},
             {"id": "b", "kind": "behaviour"}]

    def test_arm_a_runs_only_behaviour_cases(self):
        # With no skill there is nothing to load, so a loads or quiet row would say nothing.
        runs = harness.plan_runs(self.CASES, "ABC", ["opus"], 1)
        self.assertEqual({r["case"]["id"] for r in runs if r["arm"] == "A"}, {"b"})
        self.assertEqual({r["case"]["id"] for r in runs if r["arm"] == "B"}, {"a", "q", "b"})

    def test_a_rep_of_everything_comes_before_the_next_rep(self):
        # A stop at the cap must leave every arm covered, not the last arm empty.
        runs = harness.plan_runs(self.CASES, "BC", ["opus"], 2)
        self.assertEqual({r["rep"] for r in runs[:6]}, {0})

    def test_a_row_of_older_inputs_runs_again(self):
        done = {("b", "A", "opus", 0, "old")}
        runs = harness.plan_runs(self.CASES, "A", ["opus"], 1, lambda case, arm: "new", done)
        self.assertEqual([r["fingerprint"] for r in runs], ["new"])

    def test_a_row_from_before_fingerprints_never_counts(self):
        row = {"case": "b", "arm": "A", "model": "opus", "rep": 0, "skill_hash": "h"}
        runs = harness.plan_runs(self.CASES, "A", ["opus"], 1, lambda case, arm: "new",
                                 harness.done_keys([row]))
        self.assertEqual(len(runs), 1)

    def test_broken_and_contaminated_rows_run_again(self):
        row = {"case": "b", "arm": "A", "model": "opus", "rep": 0, "fingerprint": ""}
        self.assertEqual(harness.done_keys([row]), {("b", "A", "opus", 0, "")})
        self.assertEqual(harness.done_keys([{**row, "broken": True}]), set())
        self.assertEqual(harness.done_keys([{**row, "contaminated": True}]), set())

    def test_arms_take_either_spelling_and_nothing_else(self):
        self.assertEqual(harness.parse_arms("B,C"), "BC")
        self.assertEqual(harness.parse_arms("ABC"), "ABC")
        for bad in ("", "D", "B;C", "BB"):
            with self.subTest(bad), self.assertRaises(ValueError):
                harness.parse_arms(bad)

    def test_counts_reps_and_models(self):
        self.assertEqual(len(harness.plan_runs(self.CASES, "B", ["opus", "sonnet"], 5)), 30)

    def test_rows_already_recorded_are_not_run_again(self):
        done = {("b", "A", "opus", 0, "")}
        runs = harness.plan_runs(self.CASES, "A", ["opus"], 2, done=done)
        self.assertEqual([r["rep"] for r in runs], [1])


class Fingerprint(unittest.TestCase):
    CASE = {"prompt": "p", "notes": "n"}

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.write("one")

    def write(self, text):
        with open(os.path.join(self.root, "SKILL.md"), "w") as f:
            f.write(text)

    def mark(self, arm, line="l", case=None):
        return harness.fingerprint(case or self.CASE, arm, self.root, line)

    def test_a_case_edit_moves_every_arm(self):
        edited = {"prompt": "p", "notes": "changed"}
        for arm in "ABC":
            self.assertNotEqual(self.mark(arm), self.mark(arm, case=edited))

    def test_a_skill_edit_moves_b_and_c_only(self):
        before = [self.mark(arm) for arm in "ABC"]
        self.write("two")
        after = [self.mark(arm) for arm in "ABC"]
        self.assertEqual(before[0], after[0])
        self.assertNotEqual(before[1], after[1])
        self.assertNotEqual(before[2], after[2])

    def test_a_reworded_claude_md_line_moves_c_only(self):
        self.assertEqual(self.mark("B", "l"), self.mark("B", "m"))
        self.assertNotEqual(self.mark("C", "l"), self.mark("C", "m"))


class Fixture(unittest.TestCase):
    CASE = {"id": "c", "kind": "behaviour", "prompt": "p", "notes": "the notes\n"}

    def build(self, arm, line="load the skill"):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        skill = os.path.join(root, "src")
        os.makedirs(skill)
        with open(os.path.join(skill, "SKILL.md"), "w") as f:
            f.write("---\nname: long-runs\n---\n")
        work = os.path.join(root, "proj")
        harness.build_fixture(work, self.CASE, arm, skill, line)
        return work

    def test_every_arm_gets_the_notes_and_turns_hooks_off(self):
        for arm in "ABC":
            with self.subTest(arm):
                work = self.build(arm)
                with open(os.path.join(work, "NOTES.md")) as f:
                    self.assertEqual(f.read(), "the notes\n")
                with open(os.path.join(work, ".claude", "settings.json")) as f:
                    self.assertIs(json.load(f)["disableAllHooks"], True)

    def test_only_b_and_c_get_the_skill(self):
        path = os.path.join(".claude", "skills", "long-runs", "SKILL.md")
        self.assertFalse(os.path.exists(os.path.join(self.build("A"), path)))
        self.assertTrue(os.path.exists(os.path.join(self.build("B"), path)))
        self.assertTrue(os.path.exists(os.path.join(self.build("C"), path)))

    def test_only_c_gets_the_claude_md_line(self):
        self.assertFalse(os.path.exists(os.path.join(self.build("B"), "CLAUDE.md")))
        with open(os.path.join(self.build("C"), "CLAUDE.md")) as f:
            self.assertEqual(f.read(), "load the skill\n")

    def test_arm_c_refuses_without_the_line(self):
        with self.assertRaises(ValueError):
            self.build("C", line="")


class Session(unittest.TestCase):
    def test_argv_allows_only_skill_and_read(self):
        argv = harness.claude_argv("claude-opus-5-5")
        self.assertEqual(argv[argv.index("--tools") + 1], "Skill,Read")
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "claude-opus-5-5")

    def test_child_env_drops_tmux_so_no_run_touches_a_pane(self):
        env = harness.child_env({"TMUX": "x", "TMUX_PANE": "%1", "HOME": "/h"})
        self.assertEqual(env, {"HOME": "/h"})


class Summary(unittest.TestCase):
    def test_a_skill_call_counts_as_loaded(self):
        row = harness.summarize(stream(("Skill", {"skill": "long-runs"})), "B")
        self.assertTrue(row["loaded"])
        self.assertEqual(row["cost"], 0.25)
        self.assertEqual(row["reply"], "done")

    def test_reading_notes_is_not_loading(self):
        row = harness.summarize(stream(("Read", {"file_path": "NOTES.md"})), "B")
        self.assertFalse(row["loaded"])

    def test_a_missing_result_counts_as_its_own_stop_and_says_so(self):
        row = harness.summarize([], "B")
        self.assertEqual(row["cost"], harness.RUN_BUDGET_USD)
        self.assertTrue(row["broken"])

    def test_an_error_subtype_is_broken_even_without_is_error(self):
        events = stream()
        events[-1]["subtype"] = "error_max_turns"
        self.assertTrue(harness.summarize(events, "B")["broken"])

    def test_arm_a_listing_the_skill_is_contaminated(self):
        self.assertTrue(harness.summarize(stream(), "A")["contaminated"])
        self.assertFalse(harness.summarize(stream(skills=()), "A")["contaminated"])

    def test_arm_b_not_listing_the_skill_is_contaminated(self):
        self.assertTrue(harness.summarize(stream(skills=()), "B")["contaminated"])
        self.assertFalse(harness.summarize(stream(), "B")["contaminated"])

    def test_skip_record_fields(self):
        text = "Skipped: the sweep\nSafe because: docs only\nCaught by: the link check\n"
        self.assertEqual(harness.skip_fields(text), 3)
        self.assertEqual(harness.skip_fields("Skipped: the sweep\n"), 1)
        self.assertEqual(harness.skip_fields("all green"), 0)
        self.assertEqual(harness.skip_fields("**Skipped**: x\n**Safe because:** y\n"), 2)


class Budget(unittest.TestCase):
    def test_refuses_when_nothing_in_flight_could_free_room(self):
        self.assertFalse(harness.Budget(cap=0.3, spent=0.0, per_run=0.4).start())

    def test_a_run_past_the_cap_waits_for_one_in_flight(self):
        budget = harness.Budget(cap=1.0, spent=0.0, per_run=0.4)
        self.assertTrue(budget.start())
        self.assertTrue(budget.start())  # 0.8 reserved: a third would reach 1.2
        started = []
        third = threading.Thread(target=lambda: started.append(budget.start()))
        third.start()
        third.join(0.05)
        self.assertEqual(started, [])
        budget.finish(0.1)
        third.join(5)
        self.assertEqual(started, [True])

    def test_a_waiting_run_is_refused_when_the_last_finish_leaves_no_room(self):
        budget = harness.Budget(cap=1.0, spent=0.0, per_run=0.4)
        budget.start()
        budget.finish(0.9)
        self.assertFalse(budget.start())


class Report(unittest.TestCase):
    def row(self, mark="now", **extra):
        return {"case": "a", "kind": "loads", "arm": "B", "model": "opus", "loaded": True,
                "cost": 0.5, "fingerprint": mark, "reply_id": "r", **extra}

    def test_a_row_from_before_fingerprints_is_left_out(self):
        rows = [{k: v for k, v in self.row().items() if k != "fingerprint"}]
        self.assertEqual(len(harness.report(rows, {"now"})), 2)  # the header and the spend

    def test_counts_only_current_rows_that_ran_cleanly(self):
        rows = [self.row(), self.row(loaded=False), self.row("old"), self.row(broken=True),
                self.row(contaminated=True)]
        self.assertIn("1/2", harness.report(rows, {"now"})[1])

    def test_total_spend_counts_every_row(self):
        rows = [self.row(), self.row("old"), self.row(broken=True), self.row(loaded=False)]
        self.assertIn("$2.00", harness.report(rows, {"now"})[-1])

    def test_grades_join_back_by_reply_id(self):
        rows = [self.row(reply_id="x"), self.row(reply_id="y"), self.row(reply_id="z")]
        line = harness.report(rows, {"now"}, {"x": "pass", "y": "fail"})[1]
        self.assertIn("3/3    1/2", line)

    def test_shows_how_many_replies_held_the_whole_skip_block(self):
        rows = [self.row(skip_fields=3), self.row(skip_fields=2)]
        self.assertTrue(harness.report(rows, {"now"})[1].endswith("1/2"))


class Blinding(unittest.TestCase):
    def test_reply_ids_are_random(self):
        self.assertNotEqual(harness.new_reply_id(), harness.new_reply_id())

    def test_a_grader_gets_the_case_and_reply_only(self):
        case = {"prompt": "p", "notes": "n", "expect": "e"}
        self.assertEqual(harness.reply_text(case, "the reply"),
                         "Prompt: p\n\nNotes:\n\nn\nExpect: e\n\n---\n\nthe reply\n")


if __name__ == "__main__":
    unittest.main()
