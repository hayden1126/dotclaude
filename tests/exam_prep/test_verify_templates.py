"""skills/exam-prep/templates/verify-*.py: the checker skeletons a hub copies into _build/verify/.

Each is copied into a temp `_build/verify/` beside a made-up reference module, filled by text
replacement the way a hub fills it, and run as the workflow runs it: `python3 -I` from the hub
root. Pinned: an empty self-test or example generator fails; a mismatch fails and names the
answer; the tolerance compares floats; the self-test fails until its checks and skips cover every
official part; the example generator replaces its output only on a run that succeeds and covers
the backbone's worked examples exactly, so a failed run keeps the last good output; and the
sibling import works under -I."""
import os
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES = os.path.join(REPO, "skills", "exam-prep", "templates")

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

    def test_the_parts_grep_counts_every_solution_line_form(self):
        extract = os.path.join(self.tmp.name, "_build", "extract")
        os.makedirs(extract)
        with open(os.path.join(extract, "hw.md"), "w") as f:
            f.write("### [HW1 Q1a] a\nSolution [HW1S p.1]: 3\n### [HW1 Q1b] b\n"
                    "- Solution [HW1S p.1]: 4\n### [HW1 Q1c] c\n  * Solution [HW1S p.2]: 5\n"
                    "See the Solution [HW1S p.2] above.\n")
        with open(os.path.join(TEMPLATES, "verify-selftest.py"), encoding="utf-8") as f:
            cmd = next(l.strip() for l in f if "grep" in l and "Solution" in l)
        r = subprocess.run(["bash", "-c", cmd], cwd=self.tmp.name, capture_output=True, text=True)
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
