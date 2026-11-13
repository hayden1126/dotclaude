"""skills/exam-prep/templates/verify-*.py: the checker skeletons a hub copies into _build/verify/.

Each is copied into a temp `_build/verify/` beside a made-up reference module, filled by text
replacement the way a hub fills it, and run as the workflow runs it: `python3 -I` from the hub
root. Pinned: an empty self-test or example generator fails; a mismatch fails and names the
answer; the tolerance compares floats; the self-test fails until its checks and skips cover every
official part; the example generator replaces its output only on a run that succeeds and covers
the backbone's worked examples exactly, so a failed run keeps the last good output; the
sibling import works under -I; PARTS's documented command counts the solutions files' part
blocks; and each `.py` template the CHANGELOG's newest round names carries that round's date,
while a newest round with no Files item, or one naming no file at all, fails (one naming files
but no `.py` template passes: that round changed none)."""
import os
import re
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES = os.path.join(REPO, "skills", "exam-prep", "templates")
CHANGELOG = os.path.join(REPO, "skills", "exam-prep", "references", "CHANGELOG.md")

REFERENCE = '''def total(xs):
    return sum(xs)
'''
BACKBONE = """# Backbone
- Worked examples: `ex-1-sum` Worked example 1.1: "Adding" (data: `examples.out.md`).
"""
SUM = ('    from reference import total\n'
       '    section("ex-1-sum", "Adding three numbers")\n'
       '    row("Step", "Running total")\n'
       '    row(1, total([4]))\n'
       '    row(2, total([4, 5]))')
GOOD = "# good output\n"


def newest_round(text):
    """(the newest `## Round <n> (<date>)` entry's date, the `templates/*.py` files its `- **Files:**`
    item names) in a CHANGELOG's text, as its header describes the entries. The names are None
    when the entry has no Files item, or one naming no backquoted path at all (unparsable)."""
    heads = list(re.finditer(r"^## Round (\d+) \((\d{4}-\d{2}-\d{2})\)[ \t]*$", text, re.M))
    if not heads:
        return None, None
    head = max(heads, key=lambda m: int(m.group(1)))
    end = text.find("\n## ", head.end())
    section = text[head.end():end if end != -1 else len(text)]
    files = re.search(r"^- \*\*Files:\*\*(.*?)(?=^- \*\*|\Z)", section, re.M | re.S)
    if not files or not re.search(r"`[^`\s]+`", files.group(1)):
        return head.group(2), None
    return head.group(2), set(re.findall(r"`templates/([^`/\s]+\.py)`", files.group(1)))


def baseline_problems(text, templates):
    """What is wrong with the `.py` templates' baseline dates against a CHANGELOG's text: each
    template the newest round's Files list names must carry that round's date. A missing entry,
    or a Files item missing or naming no file it can read, is a problem too: the check would
    otherwise pass on nothing. A Files item naming files but no `templates/*.py` one passes: that
    round changed no `.py` template."""
    date, names = newest_round(text)
    if not date:
        return ["no `## Round <n> (<date>)` entry in the CHANGELOG"]
    if names is None:
        return [f"the Round entry of {date} has no `- **Files:**` item naming a backquoted file"]
    out = []
    for name in sorted(names):
        path = os.path.join(templates, name)
        if not os.path.exists(path):
            out.append(f"the CHANGELOG names templates/{name}, which doesn't exist")
            continue
        with open(path, encoding="utf-8") as f:
            head = f.read(2000)
        m = re.search(r"baseline as of (\d{4}-\d{2}-\d{2})", head)
        if not m:
            out.append(f"templates/{name} carries no `baseline as of <date>`")
        elif m.group(1) != date:
            out.append(f"templates/{name} carries {m.group(1)}, not the round's {date}")
    return out


class BaselineDate(unittest.TestCase):
    def test_a_template_the_newest_round_changed_carries_its_date(self):
        # Round 9: verify-selftest.py and verify-set-key.py changed in round 8 under a baseline
        # dated 2026-10-20. 12-retro step 3 dates each file a round changes with that round's
        # date, so a stale date hides the change from whoever compares a hub copy's date with the
        # CHANGELOG. Each `.py` template the newest round's Files list names carries that round's
        # date.
        with open(CHANGELOG, encoding="utf-8") as f:
            self.assertEqual(baseline_problems(f.read(), TEMPLATES), [])

    def test_a_round_it_cant_read_fails_rather_than_passing_on_nothing(self):
        # Review round 11: a Files list it couldn't find or parse left the name set empty, and
        # the loop over it passed. Each of these must fail.
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "verify-a.py"), "w", encoding="utf-8") as f:
                f.write("# baseline as of 2026-02-03\n")
            good = "## Round 2 (2026-02-03)\n\n- **Files:** `templates/verify-a.py`.\n"
            self.assertEqual(baseline_problems(good, tmp), [])
            for text, needle in (
                    ("# Changelog\n", "no `## Round"),
                    ("## Round 2 (2026-02-03)\n\n- Files: `templates/verify-a.py`.\n",
                     "has no `- **Files:**` item"),
                    ("## Round 2 (2026-02-03)\n\n- **Files:** SKILL.md and scripts/x.py.\n",
                     "has no `- **Files:**` item"),
                    ("## Round 2 (2026-02-04)\n\n- **Files:** `templates/verify-a.py`.\n",
                     "carries 2026-02-03, not the round's 2026-02-04"),
                    ("## Round 2 (2026-02-03)\n\n- **Files:** `templates/verify-b.py`.\n",
                     "which doesn't exist")):
                with self.subTest(needle):
                    problems = baseline_problems(text, tmp)
                    self.assertEqual(len(problems), 1, problems)
                    self.assertIn(needle, problems[0])
            # Review round 12: a round naming files but no `.py` template changed none, and
            # passes.
            self.assertEqual(baseline_problems(
                "## Round 2 (2026-02-03)\n\n- **Files:** `SKILL.md`, `scripts/x.py`.\n", tmp), [])

    def test_the_round_parser_reads_the_newest_entry(self):
        text = ("# Changelog\n\n- **Files:** `templates/x.py`, from the header's format.\n\n"
                "## Round 1 (2026-01-02)\n\n- **Files:** `templates/old.py`, baseline 2026-01-02.\n"
                "## Round 2 (2026-02-03)\n\n- **Files:** `SKILL.md`, `templates/STYLE.md`,\n"
                "  `templates/verify-a.py` and `templates/verify-b.py`, each baseline 2026-02-03;\n"
                "  `scripts/check.py`, which carries no date.\n"
                "- **Changes:** `templates/verify-c.py` named outside the Files item.\n")
        self.assertEqual(newest_round(text), ("2026-02-03", {"verify-a.py", "verify-b.py"}))
        self.assertEqual(newest_round(text.replace("- **Files:** `SKILL", "- Files: `SKILL")),
                         ("2026-02-03", None))
        self.assertEqual(newest_round("# Changelog\n"), (None, None))
        self.assertEqual(newest_round("## Round 3 (2026-03-04)\n\n- **Files:** none.\n"),
                         ("2026-03-04", None))
        self.assertEqual(newest_round("## Round 3 (2026-03-04)\n\n- **Files:** `SKILL.md`.\n"),
                         ("2026-03-04", set()))


class Skeleton(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.verify = os.path.join(self.tmp.name, "_build", "verify")
        os.makedirs(self.verify)
        with open(os.path.join(self.verify, "reference.py"), "w") as f:
            f.write(REFERENCE)
        with open(os.path.join(self.tmp.name, "_build", "backbone.md"), "w") as f:
            f.write(BACKBONE)

    def install(self, template, name, body=None, parts=None):
        with open(os.path.join(TEMPLATES, template), encoding="utf-8") as f:
            text = f.read()
        if body is not None:
            marker = "    pass\n\n\ndef "
            self.assertEqual(text.count(marker), 1)
            text = text.replace(marker, body + "\n\n\ndef ")
        if parts is not None:
            self.assertEqual(text.count("PARTS = None"), 1)
            text = text.replace("PARTS = None", f"PARTS = {parts}")
        with open(os.path.join(self.verify, name), "w", encoding="utf-8") as f:
            f.write(text)

    def run_script(self, name):
        return subprocess.run(["python3", "-I", os.path.join("_build", "verify", name)],
                              cwd=self.tmp.name, capture_output=True, text=True)

    def output(self):
        path = os.path.join(self.verify, "examples.out.md")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def put_good_output(self):
        with open(os.path.join(self.verify, "examples.out.md"), "w", encoding="utf-8") as f:
            f.write(GOOD)

    # ---- self-test ----

    def test_an_empty_selftest_fails(self):
        self.install("verify-selftest.py", "selftest.py", parts=0)
        r = self.run_script("selftest.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("NO CHECKS", r.stdout)

    def test_selftest_passes_fails_and_tolerates(self):
        body = ('    from reference import total\n'
                '    check("HW1 Q1 [HW1S p.1]", total([1, 2]), 3)\n'
                '    check("HW1 Q2 [HW1S p.1]", total([0.1, 0.2]), 0.3, tol=1e-9)')
        self.install("verify-selftest.py", "selftest.py", body, parts=2)
        r = self.run_script("selftest.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2 checks, 0 skipped, 0 course examples: ALL PASS", r.stdout)
        self.install("verify-selftest.py", "selftest.py",
                     body + '\n    check("HW1 Q3 [HW1S p.2]", total([2, 2]), 5)', parts=3)
        r = self.run_script("selftest.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL  HW1 Q3 [HW1S p.2]\n      got  4\n      want 5", r.stdout)
        self.assertIn("1 FAILED: ['HW1 Q3 [HW1S p.2]']", r.stdout)

    def test_selftest_must_cover_every_official_part(self):
        body = ('    from reference import total\n'
                '    check("HW1 Q1 [HW1S p.1]", total([1, 2]), 3)\n'
                '    skip("HW1 Q2 [HW1S p.1]", "prove")')
        self.install("verify-selftest.py", "selftest.py", body)
        r = self.run_script("selftest.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("PARTS NOT SET", r.stdout)
        self.install("verify-selftest.py", "selftest.py", body, parts=40)
        r = self.run_script("selftest.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("COVERS 2 OF 40 OFFICIAL PARTS", r.stdout)
        self.install("verify-selftest.py", "selftest.py", body, parts=2)
        r = self.run_script("selftest.py")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("SKIP  HW1 Q2 [HW1S p.1] (prove)", r.stdout)
        self.assertIn("1 checks, 1 skipped, 0 course examples: ALL PASS", r.stdout)

    def test_selftest_counts_each_part_once(self):
        body = ('    from reference import total\n'
                '    check("HW1 Q1 [HW1S p.1]", total([1, 2]), 3)\n'
                '    check("HW1 Q1 [HW1S p.1]", total([3]), 3)')
        self.install("verify-selftest.py", "selftest.py", body, parts=2)
        r = self.run_script("selftest.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("TWICE ['HW1 Q1 [HW1S p.1]']", r.stdout)
        self.assertIn("COVERS 1 OF 2 OFFICIAL PARTS", r.stdout)

    def test_course_examples_check_the_reference_before_any_solutions(self):
        body = ('    from reference import total\n'
                '    example("D1 p.4 worked example", total([2, 3]), 5)')
        self.install("verify-selftest.py", "selftest.py", body, parts=0)
        r = self.run_script("selftest.py")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("0 checks, 0 skipped, 1 course examples: ALL PASS", r.stdout)
        self.install("verify-selftest.py", "selftest.py",
                     body.replace("), 5)", "), 6)"), parts=0)
        r = self.run_script("selftest.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL  D1 p.4 worked example", r.stdout)

    def test_the_parts_count_is_the_solutions_files_part_blocks(self):
        # The documented command counts each question part whose block in _build/solutions/
        # holds a `Solution [` line: one per part however many lines it has, never a stem's
        # block, an answers file's page block or a `No official solution.` part.
        solutions = os.path.join(self.tmp.name, "_build", "solutions")
        os.makedirs(solutions)
        with open(os.path.join(self.tmp.name, "MANIFEST.md"), "w") as f:
            f.write("| Doc id | File | Pages | Scope | Answers | Notes |\n|---|---|---|---|---|---|\n"
                    "| HW1 | `sources/hw1.pdf` | 2 | in | no | homework |\n"
                    "| HW1S | `sources/hw1s.pdf` | 2 | in | yes | solutions to HW1 |\n")
        with open(os.path.join(solutions, "hw.md"), "w") as f:
            f.write("### [HW1 Q1 stem] s\nSolution [HW1S p.1]: the setup\n"
                    "### [HW1 Q1a] a\nSolution [HW1S p.1]: 3\n### [HW1 Q1b] b\n"
                    "- Solution [HW1S p.1]: 4\nSolution [HW1S p.2]: and 5\n"
                    "### [HW1 Q1c] c\nNo official solution.\n"
                    "### [HW1 Q1d] d\nSolution [HW1S p.2] [HW1S p.1]: 6\n"
                    "### [HW1S p.2] Solutions, continued\nSolution [HW1S p.2]: 7\n")
        with open(os.path.join(TEMPLATES, "verify-selftest.py"), encoding="utf-8") as f:
            cmd = next(l.strip() for l in f if "extract_check.py --parts" in l)
        skill = os.path.dirname(TEMPLATES)
        r = subprocess.run(["bash", "-c", cmd.replace("<skill>", skill)], cwd=self.tmp.name,
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "3", r.stderr)

    # ---- example generator ----

    def test_an_empty_example_generator_fails_and_writes_nothing(self):
        self.install("verify-examples.py", "examples.py")
        r = self.run_script("examples.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("NO EXAMPLES", r.stderr)
        self.assertIsNone(self.output())
        self.assertEqual(sorted(os.listdir(self.verify)), ["examples.py", "reference.py"])

    def test_examples_write_a_section_per_id(self):
        self.install("verify-examples.py", "examples.py",
                     SUM + '\n    section("value-2-total", "A total the notes need")\n'
                           '    emit(f"{total([1, 1])}")')
        r = self.run_script("examples.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.output()
        self.assertIn("## ex-1-sum: Adding three numbers\n", out)
        self.assertIn("| 2 | 9 |", out)
        self.assertIn("## value-2-total: A total the notes need\n\n2\n", out)
        self.assertIn("ex-1-sum\n", r.stderr)
        self.assertIn("wrote examples.out.md, 2 sections", r.stderr)
        self.assertNotIn("examples.out.md.tmp", os.listdir(self.verify))

    def test_a_failing_run_keeps_the_last_good_output(self):
        self.put_good_output()
        self.install("verify-examples.py", "examples.py",
                     SUM + '\n    assert False, "unsolvable input: pick another"')
        r = self.run_script("examples.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unsolvable input", r.stderr)
        self.assertEqual(self.output(), GOOD)
        self.assertNotIn("examples.out.md.tmp", os.listdir(self.verify))

    def test_examples_must_match_the_backbone(self):
        cases = [
            ('    section("ex-2-other", "Not the one")', "MISSING ex-1-sum"),
            (SUM + '\n    section("ex-9-typo", "x")', "NOT IN THE BACKBONE ex-9-typo"),
            (SUM + '\n    section("ex-1-sum", "again")', "TWICE ex-1-sum"),
        ]
        for body, needle in cases:
            with self.subTest(needle=needle):
                self.put_good_output()
                self.install("verify-examples.py", "examples.py", body)
                r = self.run_script("examples.py")
                self.assertEqual(r.returncode, 1)
                self.assertIn(needle, r.stderr)
                self.assertIn("not replaced", r.stderr)
                self.assertEqual(self.output(), GOOD)

    def test_examples_without_a_backbone_fail(self):
        os.remove(os.path.join(self.tmp.name, "_build", "backbone.md"))
        self.install("verify-examples.py", "examples.py", SUM)
        r = self.run_script("examples.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the backbone lists the worked examples", r.stderr)


if __name__ == "__main__":
    unittest.main()
