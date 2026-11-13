"""skills/exam-prep/scripts/extract_check.py: extracts against MANIFEST's scope, on a synthetic hub.

The hub has every kind of row: PDFs (one scoped by a page range), a reveal deck, a homework with
its official solutions, a Word file, the Ed digest, and reserved, pending and out rows. Pinned: a
dropped page or slide fails; a course page saved as HTML is checked as a text source, not a deck; scope wider than the renders fails and narrower passes; build-frame
runs cover every page in the run; a question block's cites cover only its own doc and answer
docs; a doc with no blocks fails, unless a STATUS `Unverified:` line names it; a reserved doc's
blocks fail; the brief's closing Coverage line adds no UNREADABLE flag.

The solutions files (`_build/solutions/<name>.md`, beside each extract): every question part of a
solved doc needs one block there (NO SOLUTION BLOCK), holding `Solution [<doc> <loc>]:` or `No
official solution.`; a block naming no extract's part, a part's second block and an empty block
fail, a stem's block warns. An extract fails on a bracketed or bold solution in a solved doc's
block (fenced or not), on a line citing an answers page however worded (a `Pages:` line of cites
and the closing line aside, question pages read across extracts), and on an answers doc's page
block on no question part's page (a separate answers file's, a past exam's key page); a loose
`Solution:` line outside a fence warns. An answers file with no question block and no `solutions
to` note fails. Flags in either directory count; illegible values are listed by file and line;
`--parts` counts the part blocks holding a `Solution [` line."""
import contextlib
import importlib.util
import io
import os
import re
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "skills", "exam-prep", "scripts", "extract_check.py")

_spec = importlib.util.spec_from_file_location("extract_check", SCRIPT)
extract_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract_check)

MANIFEST = """# Source manifest: WID 1001 Midterm

| Doc id | File | Pages | Scope | Answers | Rendered | Notes |
|---|---|---|---|---|---|---|
| D1 | `sources/lectures/d1.pdf` | 7 | in | no | yes | |
| D2 | `sources/lectures/d2.html` | 4 | in | no | n/a | reveal deck |
| D3 | `sources/lectures/d3.pdf` | 6 | in, PDF pp.2-4 (last in-scope slide: PDF p.4 = printed 3) | no | yes | |
| HW1 | `sources/homework/hw1.pdf` | 2 | in | no | yes | |
| HW1S | `sources/homework/hw1s.pdf` | 2 | in | yes | yes | official solutions to HW1 |
| W1 | `sources/other/w1.docx` | n/a | concepts only | no | n/a | |
| ED | `sources/ed/ed-digest.md` | n/a | in | no | n/a | the Ed pull |
| D9 | `sources/lectures/d9.pdf` | 30 | reserved: Final | no | no | |
| D10 | later | | pending: in, through slide 12 | no | no | |
| X1 | `sources/other/x1.pdf` | 3 | out | no | no | |
"""

DECK = """<div class="reveal"><div class="slides">
<section>Title</section>
<section><section>A</section><section>B</section></section>
<section>Last</section>
</div></div>"""

FULL = {
    "D1.md": "".join(f"### [D1 p.{p}] t\n" for p in range(1, 8)),
    "D2.md": "### [D2 #/0] Title\n### [D2 #/1/0] A\n### [D2 #/1/1] B\n### [D2 #/2] Last\n",
    "D3.md": "### [D3 p.2] a\n### [D3 p.3-4] build frames\n",
    "hw.md": "### [HW1 Q1 stem] Setup\nPages: [HW1 p.1]\n### [HW1 Q1a] Part a\nPages: [HW1 p.2]\n"
             "**Shape:** compute\n",
    "W1.md": "### [W1 Overview] the document's first section\n",
}
# The solutions file the extract agent writes beside hw.md: one block per part of HW1, which HW1S
# solves.
SOLS = {"hw.md": "# HW1 solutions (extract)\nSources: HW1S 2.\n### [HW1 Q1a] Part a\n"
                 "Solution [HW1S p.1-2]: 42\n"}
COVERAGE = "Coverage: pages 1-7; 7 blocks; 0 image only; 0 UNREADABLE.\n"


class ExtractCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.write("MANIFEST.md", MANIFEST)
        self.write("sources/lectures/d2.html", DECK)
        for doc, pages in (("D1", range(1, 8)), ("D3", range(1, 7)), ("HW1", (1, 2)),
                           ("HW1S", (1, 2))):
            for p in pages:
                self.write(f"_build/pages/{doc}/p-{p:03d}.png", "")
        for name, text in FULL.items():
            self.extract(name, text)
        for name, text in SOLS.items():
            self.solutions(name, text)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def extract(self, name, text):
        self.write(f"_build/extract/{name}", text)

    def solutions(self, name, text):
        self.write(f"_build/solutions/{name}", text)

    def run_check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = extract_check.main(["--root", self.root])
        return code, out.getvalue()

    def test_full_coverage_passes(self):
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        for line in ("D1: 7 pages in scope, 7 rendered, 7 with a block",
                     "D2: 4 slides in scope, 4 with a block",
                     "D3: 3 pages in scope, 3 rendered, 3 with a block",
                     "HW1: 2 pages in scope, 2 rendered, 2 with a block, 2 question blocks",
                     "HW1S: 2 pages in scope, 2 rendered, 2 with a block",
                     "W1: 1 blocks",
                     "ED: the Ed digest, read as it is"):
            self.assertIn(line, out)
        for doc in ("D9", "D10", "X1"):
            self.assertNotIn(doc, out)

    def test_a_dropped_page_fails_and_the_coverage_line_is_not_a_flag(self):
        self.extract("D1.md", "### [D1 p.1] t\n(image only: title slide)\n### [D1 p.2-4] t\n"
                              "UNREADABLE: an edge label\n### [D1 p.6] t\n### [D1 p.7] t\n"
                              + COVERAGE)
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D1: 7 pages in scope, 7 rendered, 6 with a block, 1 image only, "
                      "1 UNREADABLE; MISSING 5", out)

    def test_scope_wider_than_the_renders_fails(self):
        os.remove(os.path.join(self.root, "_build", "pages", "D3", "p-004.png"))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D3: 3 pages in scope, 2 rendered, 3 with a block", out)
        self.assertIn("NOT RENDERED 4", out)

    def test_pages_outside_a_scoped_range_need_no_block(self):
        self.assertNotIn("MISSING", self.run_check()[1])  # D3 pp.1, 5, 6 are rendered, unscoped

    def test_a_dropped_slide_fails_and_a_slide_range_limits_the_deck(self):
        self.extract("D2.md", "### [D2 #/0] Title\n### [D2 #/1/0] A\n### [D2 #/2] Last\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D2: 4 slides in scope, 3 with a block, 0 image only, 0 UNREADABLE; "
                      "MISSING #/1/1", out)
        self.write("MANIFEST.md", MANIFEST.replace("| 4 | in | no | n/a | reveal deck |",
                                                   "| 4 | in, slides #/0-#/0 | no | n/a | |"))
        self.extract("D2.md", "### [D2 #/0] Title\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("D2: 1 slides in scope, 1 with a block", out)

    def test_an_unreadable_deck_fails(self):
        os.remove(os.path.join(self.root, "sources", "lectures", "d2.html"))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D2: can't read the deck sources/lectures/d2.html", out)

    def test_a_course_page_saved_as_html_is_a_text_source(self):
        # Not a reveal deck (no `slides` element): one block covers it, as for a Word file.
        self.write("MANIFEST.md", MANIFEST + "| C1 | `sources/other/c1.html` | n/a | in | no | n/a | course page |\n")
        self.write("sources/other/c1.html", "<html><body><h1>Course policies</h1><p>x</p></body></html>")
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("C1: no blocks; MISSING all", out)
        self.extract("C1.md", "### [C1 Policies] the page's one section\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("C1: 1 blocks", out)
        # A slide range still reads it as a deck, which it isn't.
        self.write("MANIFEST.md", MANIFEST + "| C1 | `sources/other/c1.html` | n/a | in, slides #/0-#/2 | no | n/a | |\n")
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("C1: can't read the deck sources/other/c1.html: no element with class `slides`", out)

    def test_a_doc_with_no_blocks_fails(self):
        os.remove(os.path.join(self.root, "_build", "extract", "W1.md"))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("W1: no blocks; MISSING all", out)

    def test_an_unverified_doc_passes_until_it_has_a_block(self):
        os.remove(os.path.join(self.root, "_build", "extract", "W1.md"))
        self.write("STATUS.md", "# STATUS\n\n- Unverified: W1, sec-3-w1, 2026-10-22 (FB-013)\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("W1: unverified, added without an extract", out)
        self.assertNotIn("MISSING", out)
        # A mention mid-line, another doc's line, or a STATUS it can't read exempts nothing.
        for status in (b"- Added W1 as asked. Unverified: W1, sec-3-w1\n",
                       b"Unverified: W10, sec-3-w1, 2026-10-22\n",
                       b"Unverified: W1's section waits\n",
                       b"\xff\xfe Unverified: W1, sec-3-w1\n"):
            with open(os.path.join(self.root, "STATUS.md"), "wb") as f:
                f.write(status)
            code, out = self.run_check()
            self.assertEqual(code, 1, (status, out))
            self.assertIn("W1: no blocks; MISSING all", out)
        # Once the doc has a block of its own, its row is checked like any other.
        self.write("STATUS.md", "Unverified: D1, sec-2-d1, 2026-10-22\n")
        self.extract("D1.md", "### [D1 p.1] t\n")
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("D1: 7 pages in scope, 7 rendered, 1 with a block", out)

    def test_a_question_block_covers_only_its_own_and_answer_docs(self):
        self.extract("D1.md", "".join(f"### [D1 p.{p}] t\n" for p in (1, 2, 3, 4, 6, 7)))
        self.extract("hw.md", FULL["hw.md"] + "### [HW1 Q2] uses a slide\nPages: [HW1 p.2]\n"
                              "As on [D1 p.5].\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D1: 7 pages in scope, 7 rendered, 6 with a block, 0 image only, "
                      "0 UNREADABLE; MISSING 5", out)
        self.assertIn("HW1S: 2 pages in scope, 2 rendered, 2 with a block", out)

    def test_a_cite_outside_a_question_block_covers_nothing(self):
        self.extract("D1.md", "".join(f"### [D1 p.{p}] see [D1 p.5]\n" for p in (1, 2, 3, 4, 6, 7)))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("MISSING 5", out)

    def test_a_reserved_docs_blocks_fail_and_unknown_ones_warn(self):
        self.extract("x.md", "### [D9 p.1] opened by mistake\n### [HW9 p.1] a typo\n"
                             "### [X1 p.1] out of scope\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D9: RESERVED, yet the extracts hold 1 blocks for it (FB-023)", out)
        self.assertIn("warning: blocks for HW9, a doc id MANIFEST.md lacks", out)
        self.assertIn("warning: blocks for X1, whose MANIFEST.md scope is 'out'", out)

    def test_a_scope_it_cant_read_fails(self):
        for scope in ("in, through PDF p.40", "in, from p.3 on", "in, slides #/0-#/2"):
            self.write("MANIFEST.md", MANIFEST.replace(
                "in, PDF pp.2-4 (last in-scope slide: PDF p.4 = printed 3)", scope))
            code, out = self.run_check()
            self.assertEqual(code, 1, scope)
            self.assertIn("D3: ", out)
        self.assertIn("a slide range fits only a reveal deck", out)
        self.write("MANIFEST.md", MANIFEST.replace("in, PDF pp.2-4", "in, PDF pp.2" + chr(0x2013) + "4"))
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("D3: 3 pages in scope", out)
        self.write("MANIFEST.md", MANIFEST.replace("| 4 | in | no | n/a | reveal deck |",
                                                   "| 4 | in, through #/1 | no | n/a | |"))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D2: SCOPE NOT UNDERSTOOD: 'in, through #/1'", out)

    def test_a_deck_scope_past_its_end_or_an_empty_deck_fails(self):
        self.write("MANIFEST.md", MANIFEST.replace("| 4 | in | no | n/a | reveal deck |",
                                                   "| 4 | in, slides #/1-#/9 | no | n/a | |"))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D2: the scope ends at #/9, past the deck's last slide #/2", out)
        self.write("MANIFEST.md", MANIFEST)
        self.write("sources/lectures/d2.html", '<div class="slides"></div>')
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D2: no slides in scope", out)

    def test_an_open_unreadable_flag_fails(self):
        self.extract("D3.md", FULL["D3.md"] + "UNREADABLE: the edge weight under node B\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D3: 3 pages in scope, 3 rendered, 3 with a block, 0 image only, "
                      "1 UNREADABLE", out)

    def test_a_value_illegible_at_300_dpi_is_counted_and_passes(self):
        # Round 9: a value illegible even at 300 dpi had no way through stage 02, which runs
        # unattended: every open `UNREADABLE:` flag fails. The marked form is counted per doc
        # and passes; a plain flag still fails.
        self.extract("D3.md", FULL["D3.md"] + "The weight under node B is "
                     "(illegible at 300 dpi: a two-digit number).\n"
                     "(Illegible at 300 dpi: the caption)\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("D3: 3 pages in scope, 3 rendered, 3 with a block, 0 image only, "
                      "0 UNREADABLE, 2 illegible at 300 dpi\n", out)
        self.assertIn("D1: 7 pages in scope, 7 rendered, 7 with a block, 0 image only, "
                      "0 UNREADABLE\n", out)
        self.extract("D3.md", FULL["D3.md"] + "(illegible at 300 dpi: a weight)\n"
                     "UNREADABLE: the edge weight under node B\n")
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("0 image only, 1 UNREADABLE, 1 illegible at 300 dpi", out)
        self.assertIn("_build/extract/D3.md:4: UNREADABLE flag still open", out)
        self.assertNotIn("D3.md:3: UNREADABLE", out)
        # Each marked value is listed by file and line.
        self.assertIn("_build/extract/D3.md:3: (illegible at 300 dpi: a weight), counted, not a "
                      "failure", out)

    def test_the_coverage_line_counts_no_flag(self):
        self.extract("D1.md", FULL["D1.md"]
                     + "Coverage: pages 1-7; 7 blocks; 1 (image only: p.1); UNREADABLE: none.\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("D1: 7 pages in scope, 7 rendered, 7 with a block, 0 image only, "
                      "0 UNREADABLE", out)

    def test_a_block_line_starting_coverage_still_counts_its_flag(self):
        # Every line starting `Coverage:` was skipped, so a block's own `Coverage: UNREADABLE:
        # ...` line hid an open flag. Only the closing line (closing()) is skipped.
        self.extract("D3.md", FULL["D3.md"] + "Coverage: UNREADABLE: the percentage in the last row\n"
                     + "Coverage: D3 pp.2-4; 2 blocks; 0 image only; 1 flagged unreadable.\n")
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("D3: 3 pages in scope, 3 rendered, 3 with a block, 0 image only, "
                      "1 UNREADABLE", out)

    def test_an_open_flag_is_named_by_file_and_line(self):
        # A closing line with detail after its tail (`1 flagged UNREADABLE: p.3 weight.`) read as
        # a block's own text: its `UNREADABLE:` counted as a second open flag, and the failure
        # named only a count. It closes now, and each open flag is named by file and line.
        self.extract("D3.md", FULL["D3.md"] + "UNREADABLE: the edge weight under node B\n"
                     + "Coverage: D3 pp.2-4; 2 blocks; 0 image only; 1 flagged UNREADABLE: "
                       "p.3 weight.\n")
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("D3: 3 pages in scope, 3 rendered, 3 with a block, 0 image only, "
                      "1 UNREADABLE", out)
        self.assertIn("_build/extract/D3.md:3: UNREADABLE flag still open", out)
        self.assertNotIn("D3.md:4:", out)
        # Round 8: stage 02 runs unattended, so the fix it names is a re-read, never a question.
        self.assertIn("re-read it at 300 dpi on a crop (02-extract step 3.2) and replace the flag "
                      "with the value", out)
        self.assertNotIn("ask the student", out)
        # Once the flag is cleared, the closing line alone fails nothing.
        self.extract("D3.md", FULL["D3.md"] + "Coverage: D3 pp.2-4; 2 blocks; 0 image only; "
                     "0 flagged unreadable (p.3 read from the slide's notes).\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)

    def test_an_arrived_pending_file_must_get_a_scope(self):
        self.extract("D10.md", "### [D10 p.1] arrived\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D10: PENDING, yet the extracts hold 1 blocks for it", out)

    def test_answers_pair_with_their_own_set(self):
        manifest = MANIFEST.replace("| X1 |", "| HW2 | `sources/homework/hw2.pdf` | 1 | in | no | yes | |\n| X1 |")
        self.write("MANIFEST.md", manifest)
        self.write("_build/pages/HW2/p-001.png", "")
        self.extract("hw.md", "### [HW1 Q1] One\nPages: [HW1 pp.1-2]\n"
                              "### [HW2 Q1] Two\nPages: [HW2 p.1]\n")
        # HW1S pairs with HW1 only, so HW2's block citing it covers none of its pages.
        self.solutions("hw.md", "### [HW1 Q1] One\nSolution [HW1S p.1]: 4\n"
                                "### [HW2 Q1] Two\nSolution [HW1S p.2]: 5\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("HW1: 2 pages in scope, 2 rendered, 2 with a block", out)
        self.assertIn("HW1S: 2 pages in scope, 2 rendered, 1 with a block, 0 image only, "
                      "0 UNREADABLE; MISSING 2", out)

    def test_a_solutions_file_without_pages_is_covered_by_its_cites(self):
        self.write("MANIFEST.md", MANIFEST.replace("`sources/homework/hw1s.pdf` | 2 |",
                                                   "`sources/homework/hw1s.docx` | n/a |"))
        self.extract("hw.md", "### [HW1 Q1] One\nPages: [HW1 p.1-2]\n")
        self.solutions("hw.md", "### [HW1 Q1] One\nSolution [HW1S Q1]: 4\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("HW1S: 1 blocks", out)

    def test_columns_are_found_by_name(self):
        self.write("MANIFEST.md", "| Doc id | Scope | File | Pages |\n|---|---|---|---|\n"
                                  "| D1 | in | `sources/lectures/d1.pdf` | 7 |\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("D1: 7 pages in scope, 7 rendered, 7 with a block", out)

    def test_a_by_column_present_or_absent_passes(self):
        # The optional By column (who made a source, for the page's source key) is read by no
        # check here: with it, every line reads as without it.
        _, plain = self.run_check()
        by = MANIFEST.replace("| Answers | Rendered | Notes |", "| Answers | By | Rendered | Notes |")
        by = by.replace("|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|")
        by = re.sub(r"^(\| [A-Z0-9]+ \|(?:[^|]*\|){4})", r"\1 staff |", by, flags=re.M)
        self.assertEqual(by.count("| staff |"), 10, by)
        self.write("MANIFEST.md", by)
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertEqual(out, plain)

    def test_a_scope_word_it_doesnt_know_fails(self):
        for scope in ("concept only", "`in`", ""):
            with self.subTest(scope=scope):
                self.write("MANIFEST.md", MANIFEST.replace("| 4 | in | no | n/a | reveal deck |",
                                                           f"| 4 | {scope} | no | n/a | |"))
                code, out = self.run_check()
                self.assertEqual(code, 1, out)
                self.assertIn("D2: SCOPE NOT UNDERSTOOD", out)

    def test_a_table_it_cant_read_fails(self):
        self.write("MANIFEST.md", "| Doc id | File | Pages | Range |\n|---|---|---|---|\n"
                                  "| D1 | `sources/lectures/d1.pdf` | 7 | in |\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("MANIFEST.md's table has no scope column", out)
        self.write("MANIFEST.md", "| Id | File | Scope |\n|---|---|---|\n"
                                  "| D1 | `sources/lectures/d1.pdf` | in |\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("MANIFEST.md has no rows", out)

    def test_a_row_whose_id_isnt_bare_fails(self):
        self.write("MANIFEST.md", MANIFEST.replace("| D1 |", "| `D1` |"))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("a MANIFEST.md row whose Doc id isn't a bare id: | `D1` |", out)

    def test_a_page_range_in_a_note_fails(self):
        self.write("MANIFEST.md", MANIFEST.replace("in, PDF pp.2-4 (last in-scope slide: PDF p.4 "
                                                   "= printed 3)", "in, PDF pp.2-4 (plus pp.5-6)"))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D3: SCOPE NOT UNDERSTOOD", out)

    def test_solutions_notes_pair_through_a_period_or_for(self):
        for note in ("official solutions to HW1.", "solutions for HW1"):
            with self.subTest(note=note):
                self.write("MANIFEST.md", MANIFEST.replace("official solutions to HW1", note))
                code, out = self.run_check()
                self.assertEqual(code, 0, out)
                self.assertIn("HW1S: 2 pages in scope, 2 rendered, 2 with a block", out)
                self.assertNotIn("HW1S: ANSWERS", out)
        # With no note, an answers file with no question block of its own solves nothing: its
        # pairing is unknown, so it fails until the note names the docs it solves.
        self.write("MANIFEST.md", MANIFEST.replace("official solutions to HW1", "the key"))
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: ANSWERS WITH NO PAIRING: an Answers `yes` doc with no question block "
                      "in any extract and no `solutions to <doc>` note; add the note to its "
                      "MANIFEST.md row's Notes", out)

    def test_the_template_and_its_legend_parse(self):
        with open(os.path.join(REPO, "skills", "exam-prep", "templates", "MANIFEST.md.tmpl"),
                  encoding="utf-8") as f:
            template = f.read()
        filled = re.sub(r"\{\{([^}]*)\}\}", lambda m: {"N": "12", "K": "9", "M": "8"}.get(
            m.group(1), "x"), template)
        self.write("MANIFEST.md", filled)
        rows = extract_check.manifest_rows(os.path.join(self.root, "MANIFEST.md"))
        self.assertEqual(len(rows), 8)
        for doc, row in rows.items():
            self.assertIn(row["kind"], extract_check.KINDS, doc)
            scope = row["scope"]
            if row["kind"] == "pending":
                scope = scope.split(":", 1)[1].strip()  # 01-ingest, step 5, writes it as an `in` form
            elif row["kind"] not in ("in", "concepts"):
                continue
            self.assertNotEqual(extract_check.scope_of({"scope": scope})[0], "bad", doc)
        self.assertEqual(rows["HW1S"]["answers_for"], {"HW1"})
        legend = template.split("- **Scope:**", 1)[1].split("- **Answers:**", 1)[0]
        forms = re.findall(r"`((?:in|concepts only)\b[^`]*)`", legend)
        self.assertGreaterEqual(len(forms), 5, forms)
        for form in forms:
            form = re.sub(r"\b[A-D]\b", lambda m: str("ABCD".index(m.group(0)) * 3 + 2), form)
            self.assertNotEqual(extract_check.scope_of({"scope": form})[0], "bad", form)

    def test_no_manifest(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(extract_check.main(["--root", os.path.join(self.root, "_build")]), 2)

    def test_spans_and_numbers(self):
        self.assertEqual(extract_check.spans([9, 3, 4, 5, 11, 12]), "3-5, 9, 11-12")
        self.assertEqual(extract_check.numbers("1-3, 7"), {1, 2, 3, 7})


# ---- separate solutions files ----

SOL_MANIFEST = """| Doc id | File | Pages | Scope | Answers | Rendered | Notes |
|---|---|---|---|---|---|---|
| HW1 | `sources/hw1.pdf` | 1 | in | no | yes | Homework 1 |
| HW1S | `sources/hw1s.pdf` | 1 | in | yes | yes | official solutions to HW1 |
"""
PE_ROW = "| PE1 | `sources/pe1.pdf` | 3 | in | yes | yes | practice exam with its key |\n"
CLOSE = "Coverage: p.1; 2 blocks; 0 image only; 0 flagged unreadable.\n"
CLEAN = ("# HW1 Homework 1, p.1 (extract)\nSources: HW1 1. Every page image was viewed.\n"
         "### [HW1 p.1] Homework 1\n\"Show your work.\"\n"
         "### [HW1 Q1a] Max flow\nPages: [HW1 p.1]\n"
         "\"Find the value f of a maximum flow from s to t.\" (5 points)\n"
         "**Shape:** compute\n" + CLOSE)
SOLVED = ("# HW1 solutions (extract)\nSources: HW1S 1. Every page image was viewed.\n"
          "### [HW1 Q1a] Max flow\nSolution [HW1S p.1]: by the min-cut bound.\n"
          "Coverage: p.1; 1 blocks; 0 image only; 0 flagged unreadable.\n")
PE = ("### [PE1 p.1] Practice exam\n\"Time: 50 minutes.\"\n"
      "### [PE1 Q1] Trace\nPages: [PE1 p.1-2]\n\"Trace a breadth-first search from s.\"\n")
PE_KEY = "### [PE1 p.3] Key\n\"Q1: s, a, b\"\n"
PE_SOLS = "### [PE1 Q1] Trace\nSolution [PE1 p.3]: s, a, b\n"


class SolutionsFiles(unittest.TestCase):
    """The extracts hold no answer; the solutions files hold one block per part of a solved
    doc."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.write("MANIFEST.md", SOL_MANIFEST)
        for doc in ("HW1", "HW1S"):
            self.write(f"_build/pages/{doc}/p-001.png", "")
        self.write("_build/extract/hw1.md", CLEAN)
        self.write("_build/solutions/hw1.md", SOLVED)

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def remove(self, rel):
        os.remove(os.path.join(self.root, rel))

    def check(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = extract_check.main(["--root", self.root, *args])
        return code, out.getvalue()

    def add_pe1(self, key_in_extract=False):
        self.write("MANIFEST.md", SOL_MANIFEST + PE_ROW)
        for page in (1, 2, 3):
            self.write(f"_build/pages/PE1/p-{page:03d}.png", "")
        self.write("_build/extract/pe1.md", PE + (PE_KEY if key_in_extract else ""))
        self.write("_build/solutions/pe1.md", PE_SOLS + ("" if key_in_extract else PE_KEY))

    def test_the_clean_pair_passes_and_parts_counts_it(self):
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("HW1: 1 pages in scope, 1 rendered, 1 with a block, 1 question blocks", out)
        # HW1S's page is covered by the solutions block's cite.
        self.assertIn("HW1S: 1 pages in scope, 1 rendered, 1 with a block", out)
        self.assertEqual(self.check("--parts"), (0, "1\n"))

    def test_a_solution_left_in_the_extract_fails(self):
        # Must-fail (a): the part's solutions block exists, yet the extract still holds the
        # solution under the part.
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "**Shape:** compute\n", "**Shape:** compute\nAnswer: f = 42\n"
                                    "Solution [HW1S p.1]: by the min-cut bound.\n"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/hw1.md:10: SOLUTION IN AN EXTRACT: [HW1 Q1a] is a block of "
                      "HW1, a doc with official solutions; move the solution to its part's block "
                      "in _build/solutions/hw1.md", out)
        # One failure per line: the cite of the answers page isn't named again.
        self.assertNotIn("hw1.md:10: CITES", out)

    def test_a_part_with_no_solutions_block_fails(self):
        # Must-fail (b): the extract is clean, but no solutions file has the part's block.
        self.write("_build/solutions/hw1.md", "# HW1 solutions (extract)\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/hw1.md:5: NO SOLUTION BLOCK: write its solution or \"No "
                      "official solution.\" under ### [HW1 Q1a] in _build/solutions/hw1.md", out)
        self.remove("_build/solutions/hw1.md")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("NO SOLUTION BLOCK", out)
        # A stem needs none; a part of a doc nothing in scope solves needs none.
        self.write("_build/extract/hw1.md", CLEAN.replace("[HW1 Q1a]", "[HW1 Q1 stem]"))
        self.assertNotIn("NO SOLUTION BLOCK", self.check()[1])
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| 1 | in | yes |", "| 1 | out | yes |"))
        self.write("_build/extract/hw1.md", CLEAN)
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_no_official_solution_is_a_block(self):
        self.write("_build/solutions/hw1.md", SOLVED.replace(
            "Solution [HW1S p.1]: by the min-cut bound.", "No official solution."))
        code, out = self.check()
        self.assertNotIn("NO SOLUTION BLOCK", out)
        self.assertNotIn("EMPTY", out)
        # HW1S's page now has no block: the answers file's page goes in as a page block.
        self.assertIn("HW1S: 1 pages in scope, 1 rendered, 0 with a block", out)
        self.write("_build/solutions/hw1.md", SOLVED.replace(
            "Solution [HW1S p.1]: by the min-cut bound.\n",
            "No official solution.\n### [HW1S p.1] Solutions\n(image only: a blank page)\n"))
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("HW1S: 1 pages in scope, 1 rendered, 1 with a block, 1 image only", out)
        # No `Solution [` line in a part's block: PARTS counts none.
        self.assertEqual(self.check("--parts"), (0, "0\n"))

    def test_a_bad_solutions_block_fails(self):
        for body, needle in (
                ("### [HW1 Q1a] Max flow\nSolution [HW1S p.1]: 7\n### [HW1 Q9] typo\n"
                 "Solution [HW1S p.1]: 3\n",
                 "_build/solutions/hw1.md:3: NO SUCH PART: [HW1 Q9] has no block in any extract"),
                ("### [HW1 Q1a] Max flow\nSolution [HW1S p.1]: 7\n### [HW1 Q1a] again\n"
                 "No official solution.\n",
                 "_build/solutions/hw1.md:1: TWO SOLUTIONS BLOCKS for [HW1 Q1a] (also "
                 "_build/solutions/hw1.md:3): keep one"),
                ("### [HW1 Q1a] Max flow\nThe flow is 7 [HW1S p.1].\n**Solution:** 7\n",
                 "_build/solutions/hw1.md:1: EMPTY SOLUTIONS BLOCK: [HW1 Q1a] holds neither a "
                 "`Solution [<doc> <loc>]: ...` line nor the line `No official solution.`")):
            with self.subTest(needle):
                self.write("_build/solutions/hw1.md", body)
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn(needle, out)

    def test_a_stems_solutions_block_warns(self):
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "### [HW1 Q1a]", "### [HW1 Q1 stem] Setup\nPages: [HW1 p.1]\n### [HW1 Q1a]"))
        self.write("_build/solutions/hw1.md", "### [HW1 Q1 stem] Setup\nAll parts use f.\n" + SOLVED)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("warning: _build/solutions/hw1.md:1: a solutions block for the stem "
                      "[HW1 Q1 stem]: each part still needs its own block", out)

    def test_a_bold_or_bracketed_solution_in_any_block_of_a_solved_doc_fails(self):
        for line in ("**Solution:** 42", "- **Official solution** 42",
                     "**Solution** [HW1 p.1]: 42", "#### Solution [HW1 p.1]"):
            with self.subTest(line):
                # Inside a fence too: neither form is code.
                self.write("_build/extract/hw1.md", CLEAN.replace(
                    '"Show your work."\n', f'"Show your work."\n```\n{line}\n```\n'))
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn("_build/extract/hw1.md:6: SOLUTION IN AN EXTRACT: [HW1 p.1]", out)
        # A lecture's worked example (no solved doc) is lecture text.
        self.write("_build/extract/hw1.md", CLEAN)
        self.write("MANIFEST.md", SOL_MANIFEST + "| D1 | `sources/d1.pdf` | 1 | in | no | yes | |\n")
        self.write("_build/pages/D1/p-001.png", "")
        self.write("_build/extract/d1.md", "### [D1 p.1] Recurrences\n**Solution:** T(n) = n log n\n"
                                           "Solution: unroll it.\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("d1.md", out)
        # Starter code indexing a solution array is no marker.
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "**Shape:** compute\n", "**Shape:** compute\n```python\nsolution[i + 1] = best(i)\n"
                                    "solution = memo[i - 1]\n```\n"))
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_loose_solution_line_outside_a_fence_warns(self):
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "**Shape:** compute\n", "**Shape:** compute\nSolution: push flow along s-a-t.\n"
                                    "```python\n# solution\n#### Solution\n```\n"))
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("warning: _build/extract/hw1.md:9: a loose `Solution:` line in a block of "
                      "HW1, a doc with official solutions; if it gives an answer, move it to "
                      "_build/solutions/hw1.md; question text stays", out)
        self.assertNotIn("hw1.md:11:", out)
        self.assertNotIn("hw1.md:12:", out)
        # A fence that never closes is trusted nowhere: its loose lines warn too.
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "**Shape:** compute\n", "**Shape:** compute\n```python\n#### Solution\n"))
        self.assertIn("warning: _build/extract/hw1.md:10: a loose", self.check()[1])

    def test_a_line_citing_an_answers_page_fails_whatever_its_wording(self):
        for line in ("The key gives f = 7 [HW1S p.1].", "Worked answer (from [HW1S p.1]): 7.",
                     "See [HW1S Q1]: 7.", "- As on [HW1S pp. 1-2]."):
            with self.subTest(line):
                self.write("_build/extract/hw1.md", CLEAN.replace(
                    "**Shape:** compute\n", f"**Shape:** compute\n{line}\n"))
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn("_build/extract/hw1.md:9: CITES AN ANSWERS PAGE: [HW1S ", out)
                self.assertIn("an answer goes under its part's block in _build/solutions/hw1.md; "
                              "if this line is the question's text, cite the question's own "
                              "page", out)
        # A cite of an answers page in a lecture's extract fails too.
        self.write("_build/extract/hw1.md", CLEAN)
        self.write("_build/extract/d1.md", "### [HW1 p.1] notes\nSee [HW1S p.1].\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/d1.md:2: CITES AN ANSWERS PAGE: [HW1S p.1]", out)

    def test_a_pages_line_and_the_closing_line_cite_nothing(self):
        # A `Pages:` line holding only cites names where a part sits, no answer; a question's own
        # cites are question text; the closing line is no block's.
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "Pages: [HW1 p.1]\n", "- Pages: [HW1 p.1], [HW1S p.1] and [HW1S p.2]\n"
                                  "\"See the figure on [HW1 p.1].\"\n"))
        code, out = self.check()
        self.assertEqual(code, 0, out)
        # A `Pages:` line with words beside its cites is read.
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "Pages: [HW1 p.1]\n", "Pages: [HW1 p.1]; the answer is on [HW1S p.1]\n"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/hw1.md:6: CITES AN ANSWERS PAGE", out)

    def test_a_past_exams_key_page_belongs_in_the_solutions_file(self):
        self.add_pe1()
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("PE1: 3 pages in scope, 3 rendered, 3 with a block, 1 question blocks", out)
        self.assertNotIn("PE1: ANSWERS", out)  # it solves itself: its parts are in an extract
        self.assertEqual(self.check("--parts"), (0, "2\n"))
        # Its key page in the extract fails; its question pages there don't.
        self.add_pe1(key_in_extract=True)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/pe1.md:6: AN ANSWERS PAGE IN AN EXTRACT: [PE1 p.3] is a "
                      "block of PE1, an answers doc, on no question part's page; move it to "
                      "_build/solutions/pe1.md", out)
        self.assertNotIn("pe1.md:1:", out)
        # A page-less section block of it is a key too.
        self.add_pe1()
        self.write("_build/extract/pe1.md", PE + "### [PE1 Key] the key\n\"Q1: s, a, b\"\n")
        self.assertIn("_build/extract/pe1.md:6: AN ANSWERS PAGE IN AN EXTRACT: [PE1 Key]",
                      self.check()[1])

    def test_an_answers_files_page_in_an_extract_fails(self):
        self.write("_build/extract/hw1.md", CLEAN.replace(
            CLOSE, "### [HW1S p.1] Solutions\n\"Q1a: 7\" [HW1S p.1]\n" + CLOSE))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/hw1.md:9: AN ANSWERS PAGE IN AN EXTRACT: [HW1S p.1] is a "
                      "block of HW1S, an answers doc, on no question part's page; move it to "
                      "_build/solutions/hw1.md", out)
        # Its lines move with it: no second failure for each.
        self.assertNotIn("hw1.md:10:", out)
        # In the solutions file it covers the page and passes.
        self.write("_build/extract/hw1.md", CLEAN)
        self.write("_build/solutions/hw1.md", SOLVED.replace(
            "Coverage:", "### [HW1S p.1] Solutions\n\"Q1a: 7\"\nCoverage:"))
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.check("--parts"), (0, "1\n"))  # a page block never counts

    def test_question_pages_count_across_extracts(self):
        # A lecture extract citing a question page of PE1, whose parts are in pe1.md, is no
        # answers cite; its key page still is.
        self.add_pe1()
        self.write("_build/extract/d1.md", "### [HW1 p.1] a page\nThe graph is on [PE1 p.2].\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.write("_build/extract/d1.md", "### [HW1 p.1] a page\nThe key is on [PE1 p.3].\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/d1.md:2: CITES AN ANSWERS PAGE: [PE1 p.3]", out)

    def test_an_answers_file_with_no_pairing_fails(self):
        self.write("MANIFEST.md", SOL_MANIFEST.replace("official solutions to HW1", "the key"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: ANSWERS WITH NO PAIRING", out)
        # Out of scope, no agent reads it, and it fails nothing.
        self.write("MANIFEST.md", SOL_MANIFEST.replace(
            "| 1 | in | yes | yes | official solutions to HW1 |", "| 1 | out | yes | no | |"))
        self.write("_build/solutions/hw1.md", "")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_open_flags_and_illegible_values_in_a_solutions_file(self):
        self.write("_build/solutions/hw1.md", SOLVED.replace(
            "by the min-cut bound.", "by the min-cut bound.\nUNREADABLE: the cut's capacity\n"
                                     "The cut is (illegible at 300 dpi: a two-digit number)."))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/hw1.md:5: UNREADABLE flag still open", out)
        self.assertIn("_build/solutions/hw1.md:6: (illegible at 300 dpi: a two-digit number), "
                      "counted, not a failure", out)
        # The closing line counts no flag.
        self.write("_build/solutions/hw1.md", SOLVED.replace(
            "0 flagged unreadable.", "1 flagged UNREADABLE: p.1 a weight."))
        self.assertEqual(self.check()[0], 0)

    def test_the_answers_cite_reads_every_page_and_locator_form(self):
        rows = extract_check.manifest_rows(os.path.join(self.root, "MANIFEST.md"))
        rows.update({"PE1": {"answers": True, "answers_for": set()},
                     "HW3S": {"answers": True, "answers_for": set()}})
        qpages = {"PE1": {1, 2}}
        for loc in ("p.2, p.3", "p.2" + chr(0x2013) + "3", "P.3", "Key", "pp. 2-3"):
            self.assertTrue(extract_check.answers_cite("PE1", loc, rows, qpages), loc)
        for loc in ("p.2", "p.1-2", "P.1, p.2", "Q1", "Q1a"):
            self.assertFalse(extract_check.answers_cite("PE1", loc, rows, qpages), loc)
        self.assertTrue(extract_check.answers_cite("HW3S", "Problem 1", rows, qpages))
        self.assertTrue(extract_check.answers_cite("HW1S", "Q1", rows, qpages))
        self.assertFalse(extract_check.answers_cite("HW1", "p.1", rows, qpages))

    def test_solved_reads_the_notes(self):
        rows = extract_check.manifest_rows(os.path.join(self.root, "MANIFEST.md"))
        self.assertEqual(extract_check.solved(rows), {"HW1"})
        rows["PE1"] = {"answers": True, "answers_for": set(), "kind": "in"}
        rows["F1"] = {"answers": True, "answers_for": set(), "kind": "reserved"}
        self.assertEqual(extract_check.solved(rows), {"HW1", "PE1"})

    def test_the_closing_line_forms(self):
        for line in ("Coverage: D3 pp.2-4; 2 blocks; 0 image only; 1 flagged UNREADABLE: "
                     "p.3 weight.",
                     "Coverage: D3 pp.2-4; 2 blocks; 0 image only; 1 flagged unreadable (p.3: the "
                     "weight).",
                     "Coverage: D3 pp.2-4; 2 blocks; 0 image only; 2 unreadable: p.3, p.4",
                     "Coverage: pages 1-7; 7 blocks; 1 (image only: p.1); UNREADABLE: none."):
            self.assertEqual(extract_check.closing(["### [D3 p.2] x\n", "y\n", line + "\n"]),
                             {2}, line)
        # A solution's own line doesn't close (it lacks the image-only and unreadable parts), nor
        # does a closing form with text after it before the next header.
        for line in ("Coverage: 4/5 statements; 3 blocks; 2 of 3 branches",
                     "Coverage: 4/5 statements; 3 blocks; 2 of 3 branches: unreadable"):
            self.assertEqual(extract_check.closing(["### [D3 p.2] x\n", "y\n", line + "\n"]),
                             set(), line)
        self.assertEqual(extract_check.closing(
            ["### [D3 p.2] x\n", "Coverage: p.2; 1 blocks; 0 image only; 0 unreadable.\n",
             "more\n"]), set())

    def test_parts_needs_no_manifest(self):
        self.remove("MANIFEST.md")
        self.assertEqual(self.check("--parts"), (0, "1\n"))


if __name__ == "__main__":
    unittest.main()
