"""skills/exam-prep/scripts/coverage_check.py: every extract block maps to a backbone row.

A synthetic backbone and extracts: page ranges with gaps, build-frame runs that must fit wholly
inside a row, question numbers (parts and stems fall under their question), reveal slides by
horizontal index, `(all)` rows, and a block with a locator of its own. The row grammar is strict:
a stray digit in a note maps nothing, a cell that doesn't parse fails, a target must be
`skip (why)` or a subsection the backbone defines, and no blocks at all fails."""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "skills", "exam-prep", "scripts", "coverage_check.py")

_spec = importlib.util.spec_from_file_location("coverage_check", SCRIPT)
coverage_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coverage_check)

BACKBONE = """# Backbone

## §1 Widgets (`sec-1`)

| § | Title | id | Sources | Practice | How it's tested |
|---|---|---|---|---|---|
| 1.1 | Basics | `sec-1-basics` | D1 pp.2-6 | HW1 Q1 | define |
| 1.2 | More | `sec-1-more` | HW1 Q4 | | |
| 1.3 | Code | `sec-1-code` | C1 | | |

## Coverage matrix

| Source block range | → | Subsection |
|---|---|---|
| D1 p.1 | | skip (title) |
| D1 pp.2-6, 9 | | 1.1 |
| D2 #/0-2 | | 1.1 (a note: 7 and 8 here map nothing) |
| HW1 Q1-Q2 | | 1.1 / 1.2 |
| HW1 Q4a-c | | 1.2 |
| C1 (all) | | 1.3 |
"""


class Coverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "_build", "extract"))
        with open(os.path.join(self.root, "_build", "backbone.md"), "w") as f:
            f.write(BACKBONE)

    def extract(self, name, text):
        with open(os.path.join(self.root, "_build", "extract", name), "w") as f:
            f.write(text)

    def run_check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = coverage_check.main(["--root", self.root])
        return code, out.getvalue()

    def test_everything_mapped(self):
        self.extract("D1.md", "### [D1 p.1] Title\n### [D1 p.2-4] Frames\n### [D1 p.9] Recap\n")
        self.extract("D2.md", "### [D2 #/0] T\n### [D2 #/1/0] A\n### [D2 #/1/1] B\n### [D2 #/2] C\n")
        self.extract("hw.md", "### [HW1 Q1 stem] S\n### [HW1 Q1a] a\n### [HW1 Q2.1] b\n"
                              "### [HW1 Q4] d\n### [C1 main.py] concepts\n### [C1 p.3] x\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("13 extract blocks; 0 unmapped", out)

    def test_gaps_are_unmapped(self):
        self.extract("D1.md", "### [D1 p.7] Gap\n### [D1 p.5-8] Run past the row\n")
        self.extract("D2.md", "### [D2 #/3] Past the range\n")
        self.extract("hw.md", "### [HW1 Q3b] Unmapped question\n### [HW2 p.1] Unknown doc\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        for label in ("[D1 p.7] (D1.md)", "[D1 p.5-8] (D1.md)", "[D2 #/3] (D2.md)",
                      "[HW1 Q3b] (hw.md)", "[HW2 p.1] (hw.md)"):
            self.assertIn(f"UNMAPPED {label}", out)
        self.assertIn("5 extract blocks; 5 unmapped", out)

    def test_a_named_locator_needs_an_all_row(self):
        self.extract("hw.md", "### [HW1 main.py] code\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("UNMAPPED [HW1 main.py]", out)

    def test_no_matrix_or_no_backbone(self):
        with open(os.path.join(self.root, "_build", "backbone.md"), "w") as f:
            f.write("# Backbone\n")
        with self.assertRaises(SystemExit):
            self.run_check()
        os.remove(os.path.join(self.root, "_build", "backbone.md"))
        self.assertEqual(self.run_check()[0], 2)

    def test_the_row_grammar(self):
        parse = coverage_check.parse_source
        self.assertEqual(parse("D4 pp.17-20, 23"), [("D4", "pages", {17, 18, 19, 20}),
                                                    ("D4", "pages", {23})])
        self.assertEqual(parse("D2 p.1, p.32"), [("D2", "pages", {1}), ("D2", "pages", {32})])
        self.assertEqual(parse("D1 p.1, D2 p.1"), [("D1", "pages", {1}), ("D2", "pages", {1})])
        self.assertEqual(parse("D4 pp.2" + chr(0x2013) + "4"), [("D4", "pages", {2, 3, 4})])
        self.assertEqual(parse("D2 #/3-#/5"), [("D2", "slides", {3: None, 4: None, 5: None})])
        self.assertEqual(parse("D2 #/3/1-4"), [("D2", "slides", {3: {"1", "2", "3", "4"}})])
        for cell, qs in (("HW1 Q1-Q3", {1: None, 2: None, 3: None}),
                         ("HW1 Q1-3", {1: None, 2: None, 3: None}),
                         ("HW1 Q1a-d", {1: {"a", "b", "c", "d"}}),
                         ("HW1 Q2.1-2.2", {2: {"1", "2"}}),
                         ("HW1 Q2.1-3", {2: {"1", "2", "3"}}),
                         ("HW1 Q3 stem", {3: {"stem"}}),
                         ("HW1 Q3ii", {3: {"ii"}})):
            self.assertEqual(parse(cell), [("HW1", "questions", qs)], cell)
        self.assertEqual([q for _, _, q in parse("Rec4 Q3a-d, Q4a-c")],
                         [{3: {"a", "b", "c", "d"}}, {4: {"a", "b", "c"}}])
        for cell in ("D1 pp.2-6 (week 9)", "HW1 Q1-Q3 (10 pts)", "D2 #/3/1-#/5/2",
                     "D3 pp.4-9 (Q-learning)", "pp.2-6", "D1", "HW1 Q2d-a",
                     "HW1 Q2.1, 4", "HW1 Q2a-b, 3", "D2 #/3/1-2, 5", "HW1 Q3 stem, 4"):
            self.assertIsNone(parse(cell), cell)
        self.assertEqual([q for _, _, q in parse("HW1 Q1-Q2, 4")], [{1: None, 2: None}, {4: None}])

    def test_the_templates_rows_parse(self):
        with open(os.path.join(REPO, "skills", "exam-prep", "templates", "backbone.md.tmpl"),
                  encoding="utf-8") as f:
            matrix = f.read().split("## Coverage matrix", 1)[1]
        cells = [line.strip().strip("|").split("|")[0].strip()
                 for line in matrix.splitlines() if line.startswith("| {{")]
        self.assertGreaterEqual(len(cells), 5)
        for cell in cells:
            filled = cell.replace("{{", "").replace("}}", "")
            self.assertIsNotNone(coverage_check.parse_source(filled), filled)

    def test_parts_are_mapped_exactly(self):
        with open(os.path.join(self.root, "_build", "backbone.md"), "w") as f:
            f.write(BACKBONE + "| HW2 Q2a-d, Q3.1-2 | | 1.1 |\n| D3 #/4/0-1 | | 1.1 |\n"
                    "| HW3 Q1i, Q1ii | | 1.1 |\n")
        self.extract("hw2.md", "### [HW2 Q2] stem by another name\n### [HW2 Q2 stem] s\n"
                               "### [HW2 Q2d] d\n### [HW2 Q2e] e\n### [HW2 Q3.2] x\n"
                               "### [HW2 Q3.3] y\n### [D3 #/4/1] v\n### [D3 #/4/2] w\n"
                               "### [HW2 Q2b.1] deeper\n### [HW2 Q2cii] deeper\n"
                               "### [HW2 Q3.1a] deeper\n### [HW2 Q2C] not a part\n"
                               "### [HW2 Q2_a] not a part\n### [HW2 Q2.a] not a part\n"
                               "### [HW2 Q2aZ] not a part\n"
                               "### [HW3 Q1i] i\n### [HW3 Q1ii] ii\n### [HW3 Q1iii] iii\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(sorted(l.strip() for l in out.splitlines() if "UNMAPPED" in l),
                         ["UNMAPPED [D3 #/4/2] (hw2.md)", "UNMAPPED [HW2 Q2.a] (hw2.md)",
                          "UNMAPPED [HW2 Q2C] (hw2.md)", "UNMAPPED [HW2 Q2_a] (hw2.md)",
                          "UNMAPPED [HW2 Q2aZ] (hw2.md)",
                          "UNMAPPED [HW2 Q2e] (hw2.md)", "UNMAPPED [HW2 Q3.3] (hw2.md)",
                          "UNMAPPED [HW3 Q1iii] (hw2.md)"])

    def test_the_table_ends_at_the_next_heading_and_notes_may_hold_commas(self):
        with open(os.path.join(self.root, "_build", "backbone.md"), "w") as f:
            f.write(BACKBONE.replace("|---|---|---|\n| D1 p.1 |", "| :--- | --- | ---: |\n| D1 p.1 |")
                    .replace("| C1 (all) | | 1.3 |", "| C1 (all) | | 1.3 (formulation, a note), 1.1 |")
                    + "\n## Afterwards\n\n| Not | a matrix row |\n|---|---|\n| x | y |\n")
        self.extract("D1.md", "### [D1 p.2] x\n### [C1 main.py] y\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)

    def test_a_drifted_header_fails(self):
        self.extract("D1.md", "### [D1 p.2] x\n## [D1 p.3] wrong level\n### D1 p.4 no brackets\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("HEADER NOT A BLOCK D1.md:2: ## [D1 p.3] wrong level", out)
        self.assertIn("HEADER NOT A BLOCK D1.md:3: ### D1 p.4 no brackets", out)

    def test_a_bad_row_fails(self):
        with open(os.path.join(self.root, "_build", "backbone.md"), "w") as f:
            f.write(BACKBONE + "| D1 pp.7-8 (week 9) | | 1.1 |\n| D1 p.10 | | 9.9 |\n"
                               "| D1 p.11 | | skip |\n| D1 p.12 | | |\n")
        self.extract("D1.md", "### [D1 p.2] x\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("UNPARSED source cell: | D1 pp.7-8 (week 9) | | 1.1 |", out)
        for row in ("| D1 p.10 | | 9.9 |", "| D1 p.11 | | skip |", "| D1 p.12 | | |"):
            self.assertIn(f"TARGET NOT `skip (why)` OR A SUBSECTION: {row}", out)

    def test_no_blocks_fails(self):
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("NO EXTRACT BLOCKS at all", out)
        self.extract("D1.md", "### [D1 p.2] x\n")
        self.extract("drift.md", "## [D1 p.3] a header in the wrong shape\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("NO BLOCKS in drift.md", out)


if __name__ == "__main__":
    unittest.main()
