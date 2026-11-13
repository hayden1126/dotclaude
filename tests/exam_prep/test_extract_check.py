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
block (a separate answers file's, a past exam's key page); a loose `Solution:` line outside a
fence warns. Flags in either directory count; illegible values are listed by file and line;
`--parts` counts the part blocks holding a `Solution [` line, and exits 2 with no MANIFEST.md.

Review round 11: a self-answering row names its key pages (`pp. N-M`, `inline`), and only those
are answers pages, whatever a `Pages:` line says. A `for` key reads a list, and a word in it that
is no doc id fails. The lines before a file's first block are checked as a block's are. A
bracketed or bold solution citing a solved or answers doc fails in any block. An answer line
(`Answer:`, `Final answer:`, ...) in a solved doc's block warns unless it is an answer blank. A
`yes, attempted` row still answers.

Review round 12: the key checks run after the `Unverified:` skip; an extract's cite of a key page
covers nothing; the lines before a file's first block warn as a block's do.

Review round 13: MANIFEST's Key column, read whole, replaces every reading of Notes: an Answers
yes row with no key fails NO KEY, a form it doesn't know UNREAD KEY (`for HW1; HW2`), a key on a
row without answers KEY WITHOUT ANSWERS; `sections: <name>` names a source's key sections exactly
(a "Marking scheme" block in an extract fails, a "Key formulas" one passes), fails on a paged doc
and when a named section has no block in a solutions file. An unverified row solves nothing. A
part's solutions block sits beside its extract (WRONG SOLUTIONS FILE), and an extract's cite of
another doc's page covers nothing.

Review round 14: a `for` key naming its own doc fails KEY NAMES ITS OWN DOC and reads all of that
doc as answers meanwhile; a page key on a doc without pages fails PAGES KEY ON AN UNPAGED DOC, and
a deck names its solution slides as sections (`sections: #/5`); a multi-set answers file's page
blocks hold no text (SHARED ANSWERS PAGE HOLDS TEXT); a stem's solutions block warns only while a
part lacks its own; a key section's `<name> Q1` and `<name>, ...` are key material; an idle
unverified answers file reads as no answers doc; a part in two extracts takes either extract's
solutions file."""
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

| Doc id | File | Pages | Scope | Answers | Key | Rendered | Notes |
|---|---|---|---|---|---|---|---|
| D1 | `sources/lectures/d1.pdf` | 7 | in | no | | yes | |
| D2 | `sources/lectures/d2.html` | 4 | in | no | | n/a | reveal deck |
| D3 | `sources/lectures/d3.pdf` | 6 | in, PDF pp.2-4 (last in-scope slide: PDF p.4 = printed 3) | no | | yes | |
| HW1 | `sources/homework/hw1.pdf` | 2 | in | no | | yes | |
| HW1S | `sources/homework/hw1s.pdf` | 2 | in | yes | for HW1 | yes | official solutions to HW1 |
| W1 | `sources/other/w1.docx` | n/a | concepts only | no | | n/a | |
| ED | `sources/ed/ed-digest.md` | n/a | in | no | | n/a | the Ed pull |
| D9 | `sources/lectures/d9.pdf` | 30 | reserved: Final | no | | no | |
| D10 | later | | pending: in, through slide 12 | no | | no | |
| X1 | `sources/other/x1.pdf` | 3 | out | no | | no | |
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
        self.write("MANIFEST.md", MANIFEST.replace("| 4 | in | no | | n/a | reveal deck |",
                                                   "| 4 | in, slides #/0-#/0 | no | | n/a | |"))
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
        self.write("MANIFEST.md", MANIFEST + "| C1 | `sources/other/c1.html` | n/a | in | no | | n/a | course page |\n")
        self.write("sources/other/c1.html", "<html><body><h1>Course policies</h1><p>x</p></body></html>")
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("C1: no blocks; MISSING all", out)
        self.extract("C1.md", "### [C1 Policies] the page's one section\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("C1: 1 blocks", out)
        # A slide range still reads it as a deck, which it isn't.
        self.write("MANIFEST.md", MANIFEST + "| C1 | `sources/other/c1.html` | n/a | in, slides #/0-#/2 | no | | n/a | |\n")
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
        self.write("MANIFEST.md", MANIFEST.replace("| 4 | in | no | | n/a | reveal deck |",
                                                   "| 4 | in, through #/1 | no | | n/a | |"))
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D2: SCOPE NOT UNDERSTOOD: 'in, through #/1'", out)

    def test_a_deck_scope_past_its_end_or_an_empty_deck_fails(self):
        self.write("MANIFEST.md", MANIFEST.replace("| 4 | in | no | | n/a | reveal deck |",
                                                   "| 4 | in, slides #/1-#/9 | no | | n/a | |"))
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
        manifest = MANIFEST.replace("| X1 |", "| HW2 | `sources/homework/hw2.pdf` | 1 | in | no | | yes | |\n| X1 |")
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
        by = MANIFEST.replace("| Answers | Key |", "| Answers | By | Key |")
        by = by.replace("|---|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|---|")
        by = re.sub(r"^(\| [A-Z0-9]+ \|(?:[^|]*\|){4})", r"\1 staff |", by, flags=re.M)
        self.assertEqual(by.count("| staff |"), 10, by)
        self.write("MANIFEST.md", by)
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertEqual(out, plain)

    def test_a_scope_word_it_doesnt_know_fails(self):
        for scope in ("concept only", "`in`", ""):
            with self.subTest(scope=scope):
                self.write("MANIFEST.md", MANIFEST.replace("| 4 | in | no | | n/a | reveal deck |",
                                                           f"| 4 | {scope} | no | | n/a | |"))
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

    def test_a_for_key_pairs_in_any_case_and_notes_are_never_read(self):
        for key in ("FOR HW1", "For HW1"):
            with self.subTest(key=key):
                self.write("MANIFEST.md", MANIFEST.replace("| yes | for HW1 |", f"| yes | {key} |"))
                code, out = self.run_check()
                self.assertEqual(code, 0, out)
                self.assertIn("HW1S: 2 pages in scope, 2 rendered, 2 with a block", out)
        # With an empty Key cell, an answers file solves nothing and fails NO KEY, whatever its
        # Notes say: Notes is free text.
        self.write("MANIFEST.md", MANIFEST.replace("| yes | for HW1 |", "| yes | |"))
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: NO KEY: an Answers yes row fills its Key cell (\"for HW1, HW2\", "
                      "\"pp. 7-9, 11\", \"inline\" or \"sections: <name>, <name>\")", out)
        self.assertNotIn("ANSWERS WITH NO PAIRING", out)
        # A MANIFEST with no Key column at all fails the same way.
        old = re.sub(r"^((?:\|[^|\n]*){5})\|[^|\n]*", r"\1", MANIFEST, flags=re.M)
        self.assertIn("| Doc id | File | Pages | Scope | Answers | Rendered | Notes |", old)
        self.write("MANIFEST.md", old)
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: NO KEY", out)

    def test_the_template_and_its_legend_parse(self):
        with open(os.path.join(REPO, "skills", "exam-prep", "templates", "MANIFEST.md.tmpl"),
                  encoding="utf-8") as f:
            template = f.read()
        filled = re.sub(r"\{\{([^}]*)\}\}", lambda m: {"N": "12", "K": "9", "M": "8"}.get(
            m.group(1), "x"), template)
        self.write("MANIFEST.md", filled)
        rows = extract_check.manifest_rows(os.path.join(self.root, "MANIFEST.md"))
        # The header is the Key column contract's (the optional By column aside).
        header = next(line for line in template.splitlines() if line.startswith("| Doc id"))
        self.assertEqual([c.strip() for c in header.strip("|").split("|") if c.strip() != "By"],
                         ["Doc id", "File", "Pages", "Scope", "Answers", "Key", "Rendered",
                          "Notes"])
        self.assertGreaterEqual(len(rows), 8)
        self.assertEqual(rows["HW1S"]["key"]["form"], "for")
        self.assertEqual(rows["HW1S"]["key"]["docs"], {"HW1"})
        # Every example Key cell written out (not a {{placeholder}}) is a form the check reads,
        # and an Answers yes example fills it.
        self.write("raw.md", template)
        raw = extract_check.manifest_rows(os.path.join(self.root, "raw.md"))
        for doc, row in raw.items():
            if "{{" in row["key"]["cell"]:
                continue
            self.assertNotEqual(row["key"]["form"], "unread", doc)
            if rows[doc]["answers"]:
                self.assertIsNotNone(row["key"]["form"], doc)
        for doc, row in rows.items():
            self.assertIn(row["kind"], extract_check.KINDS, doc)
            scope = row["scope"]
            if row["kind"] == "pending":
                scope = scope.split(":", 1)[1].strip()  # 01-ingest, step 5, writes it as an `in` form
            elif row["kind"] not in ("in", "concepts"):
                continue
            self.assertNotEqual(extract_check.scope_of({"scope": scope})[0], "bad", doc)
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

SOL_MANIFEST = """| Doc id | File | Pages | Scope | Answers | Key | Rendered | Notes |
|---|---|---|---|---|---|---|---|
| HW1 | `sources/hw1.pdf` | 1 | in | no | | yes | Homework 1 |
| HW1S | `sources/hw1s.pdf` | 1 | in | yes | for HW1 | yes | official solutions to HW1 |
"""
PE_ROW = "| PE1 | `sources/pe1.pdf` | 3 | in | yes | p.3 | yes | practice exam |\n"
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

    def test_a_stems_solutions_block_warns_while_a_part_lacks_its_own(self):
        # Review round 14: official text a question's parts share goes in a stem block in the
        # set's own solutions file; it warns only while a part (`Q1b`, not `Q11`) lacks a block.
        stem = "### [HW1 Q1 stem] Setup\nAll parts use f.\n"
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "### [HW1 Q1a]", "### [HW1 Q1 stem] Setup\nPages: [HW1 p.1]\n### [HW1 Q1a]"))
        self.write("_build/solutions/hw1.md", stem + SOLVED)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("warning", out)
        # A part with no block of its own: the stem block warns (and the part fails).
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "### [HW1 Q1a]", "### [HW1 Q1 stem] Setup\nPages: [HW1 p.1]\n### [HW1 Q1b] b\n"
            "Pages: [HW1 p.1]\n### [HW1 Q1a]"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("warning: _build/solutions/hw1.md:1: a solutions block for the stem "
                      "[HW1 Q1 stem]: each part still needs its own block", out)
        self.assertIn("NO SOLUTION BLOCK: write its solution or \"No official solution.\" under "
                      "### [HW1 Q1b]", out)
        # Q11 is no part of Q1, and a stem with no part at all warns.
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "### [HW1 Q1a]", "### [HW1 Q1 stem] Setup\nPages: [HW1 p.1]\n### [HW1 Q11] b\n"
            "Pages: [HW1 p.1]\n### [HW1 Q1a]"))
        self.write("_build/solutions/hw1.md", stem + SOLVED
                   + "### [HW1 Q11] b\nSolution [HW1S p.1]: 7\n### [HW1 Q2 stem] s\nx\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("[HW1 Q1 stem]", out)
        self.assertIn("a solutions block for the stem [HW1 Q2 stem]: each part still needs", out)

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
        self.write("MANIFEST.md", SOL_MANIFEST + "| D1 | `sources/d1.pdf` | 1 | in | no | | yes | |\n")
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
        self.assertIn("_build/extract/pe1.md:6: AN ANSWERS PAGE IN AN EXTRACT: [PE1 p.3] is a key "
                      "page of PE1, as its MANIFEST.md Key cell names it; move it to "
                      "_build/solutions/pe1.md", out)
        self.assertNotIn("pe1.md:1:", out)
        # Only the Key cell's pages are answers: no word in a page-less locator is guessed at.
        self.add_pe1()
        self.write("_build/extract/pe1.md", PE + "### [PE1 Key formulas] the formula sheet\n"
                                                 "\"BFS visits each vertex once.\"\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_an_answers_files_page_in_an_extract_fails(self):
        self.write("_build/extract/hw1.md", CLEAN.replace(
            CLOSE, "### [HW1S p.1] Solutions\n\"Q1a: 7\" [HW1S p.1]\n" + CLOSE))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/hw1.md:9: AN ANSWERS PAGE IN AN EXTRACT: [HW1S p.1] is a "
                      "block of HW1S, a separate answers file (its Key cell is \"for HW1\"); move "
                      "it to _build/solutions/hw1.md", out)
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

    def test_an_answers_file_with_no_key_fails(self):
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| - |"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: NO KEY", out)
        # Out of scope, no agent reads it, and it fails nothing.
        self.write("MANIFEST.md", SOL_MANIFEST.replace(
            "| 1 | in | yes | for HW1 | yes | official solutions to HW1 |",
            "| 1 | out | yes | | no | |"))
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
        key = extract_check.read_key
        rows.update({"PE1": {"answers": True, "key": key("p.3")},
                     "HW3S": {"answers": True, "key": key("for HW3")},
                     "PE9": {"answers": True, "key": key("")}})
        for loc in ("p.2, p.3", "p.2" + chr(0x2013) + "3", "P.3", "pp. 2-3"):
            self.assertTrue(extract_check.answers_cite("PE1", loc, rows), loc)
        for loc in ("p.2", "p.1-2", "P.1, p.2", "Q1", "Q1a", "Key", "Answers"):
            self.assertFalse(extract_check.answers_cite("PE1", loc, rows), loc)
        self.assertTrue(extract_check.answers_cite("HW3S", "Problem 1", rows))
        self.assertTrue(extract_check.answers_cite("HW1S", "Q1", rows))
        self.assertFalse(extract_check.answers_cite("HW1", "p.1", rows))
        # A row with no key (it fails NO KEY) marks nothing as answers.
        self.assertFalse(extract_check.answers_cite("PE9", "p.1", rows))

    def test_solved_reads_the_key_column(self):
        rows = extract_check.manifest_rows(os.path.join(self.root, "MANIFEST.md"))
        self.assertEqual(extract_check.solved(rows), {"HW1"})
        key = extract_check.read_key
        rows["PE1"] = {"answers": True, "key": key("inline"), "kind": "in"}
        rows["PE2"] = {"answers": True, "key": key("sections: Marking scheme"), "kind": "concepts"}
        rows["PE3"] = {"answers": True, "key": key("pp. 4-5"), "kind": "in"}
        rows["F1"] = {"answers": True, "key": key("p.3"), "kind": "reserved"}
        rows["PE4"] = {"answers": True, "key": key(""), "kind": "in"}
        rows["PE5"] = {"answers": True, "key": key("key p.3"), "kind": "in"}
        rows["PE6"] = {"answers": False, "key": key("p.3"), "kind": "in"}
        self.assertEqual(extract_check.solved(rows), {"HW1", "PE1", "PE2", "PE3"})

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

    def test_parts_without_a_manifest_exits_2(self):
        # Review round 11: `--parts` printed 0 for a wrong root, which a self-test read as PARTS.
        self.remove("MANIFEST.md")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.check("--parts"), (2, ""))
        self.assertIn("extract_check: no MANIFEST.md in", err.getvalue())

    # ---- review round 11 ----

    def test_a_self_answering_row_with_no_key_fails(self):
        self.add_pe1()
        self.write("MANIFEST.md", SOL_MANIFEST + PE_ROW.replace("| p.3 |", "| |"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("PE1: NO KEY: an Answers yes row fills its Key cell", out)
        # Each pages form passes, in any case; Notes holds any remark and is never read.
        for key in ("p.3", "pp. 3-3", "P.3", "pp. 3" + chr(0x2013) + "3", "PP.3"):
            with self.subTest(key):
                self.write("MANIFEST.md", SOL_MANIFEST + PE_ROW.replace(
                    "| p.3 | yes | practice exam |", f"| {key} | yes | key p.4; solutions to HW9 |"))
                rows = extract_check.manifest_rows(os.path.join(self.root, "MANIFEST.md"))
                self.assertEqual(rows["PE1"]["key"]["pages"], {3})
                code, out = self.check()
                self.assertEqual(code, 0, out)
                self.assertNotIn("NO KEY", out)

    def test_an_inline_key_passes_with_part_blocks_only(self):
        # `inline`: each solution sits under its question, so no page is a key page; the
        # extract holds the cover page and the part blocks, the solutions file only part blocks
        # (no answers page, no closing line).
        self.write("MANIFEST.md", SOL_MANIFEST + PE_ROW.replace(
            "| 3 | in | yes | p.3 | yes | practice exam |",
            "| 2 | in | yes | inline | yes | past exam with its key |"))
        for page in (1, 2):
            self.write(f"_build/pages/PE1/p-{page:03d}.png", "")
        self.write("_build/extract/pe1.md",
                   "# PE1 Practice exam (extract)\nSources: PE1 2. Every page image was viewed.\n"
                   "### [PE1 p.1] Cover\n\"Time: 50 minutes.\"\n"
                   "### [PE1 Q1] Trace\nPages: [PE1 p.2]\n\"Trace a breadth-first search from s.\"\n"
                   "### [PE1 Q2] Flow\nPages: [PE1 p.2]\n\"Find a maximum flow.\"\n"
                   "Coverage: pp.1-2; 3 blocks; 0 image only; 0 flagged unreadable.\n")
        self.write("_build/solutions/pe1.md",
                   "# PE1 solutions (extract)\nSources: PE1 2.\n"
                   "### [PE1 Q1] Trace\nSolution [PE1 p.2]: s, a, b\n"
                   "### [PE1 Q2] Flow\nSolution [PE1 p.2]: f = 7\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("PE1: 2 pages in scope, 2 rendered, 2 with a block, 2 question blocks", out)
        self.assertEqual(self.check("--parts"), (0, "3\n"))  # HW1's part and PE1's two
        # Its must-fail twin: a part with no solutions block.
        self.write("_build/solutions/pe1.md", "### [PE1 Q1] Trace\nSolution [PE1 p.2]: s, a, b\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/pe1.md:8: NO SOLUTION BLOCK", out)

    def test_the_key_cell_names_the_answers_pages_whatever_a_pages_line_says(self):
        # Review round 11: a key page named on a part's `Pages:` line read as a question page, so
        # its block passed in the extract (Pages-line laundering). The Key cell decides.
        self.add_pe1(key_in_extract=True)
        self.write("_build/extract/pe1.md", PE.replace("Pages: [PE1 p.1-2]", "Pages: [PE1 p.1-3]")
                   + PE_KEY)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/pe1.md:6: AN ANSWERS PAGE IN AN EXTRACT: [PE1 p.3] is a key "
                      "page of PE1", out)
        # Its twin, the key page in the solutions file, passes.
        self.add_pe1()
        self.write("_build/extract/pe1.md", PE.replace("Pages: [PE1 p.1-2]", "Pages: [PE1 p.1-3]"))
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_page_the_key_cell_doesnt_name_is_question_material(self):
        # A formula sheet on p.4, on no part's `Pages:` line, sits in the extract, and a line may
        # cite it; once the Key cell names it a key page, both fail.
        self.add_pe1()
        self.write("MANIFEST.md", SOL_MANIFEST + PE_ROW.replace("| 3 |", "| 4 |"))
        self.write("_build/pages/PE1/p-004.png", "")
        sheet = "### [PE1 p.4] Formula sheet\n\"Max-flow min-cut: f = c(S, T).\"\n"
        self.write("_build/extract/pe1.md", PE + "As on the sheet [PE1 p.4].\n" + sheet)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("PE1: 4 pages in scope, 4 rendered, 4 with a block", out)
        self.write("MANIFEST.md", SOL_MANIFEST + PE_ROW.replace("| 3 |", "| 4 |").replace(
            "| p.3 |", "| pp. 3-4 |"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/pe1.md:6: CITES AN ANSWERS PAGE: [PE1 p.4]", out)
        self.assertIn("_build/extract/pe1.md:7: AN ANSWERS PAGE IN AN EXTRACT: [PE1 p.4] is a key "
                      "page of PE1", out)

    def test_the_answers_cite_reads_the_key_cell(self):
        key = extract_check.read_key
        rows = {"PE1": {"answers": True, "key": key("p.3")},
                "PE2": {"answers": True, "key": key("inline")},
                "PE3": {"answers": False, "key": key("p.3")}}
        for loc in ("p.3", "pp. 2-3"):
            self.assertTrue(extract_check.answers_cite("PE1", loc, rows), loc)
        for loc in ("p.1", "p.4", "Q1", "Q1a", "Key", "answer key"):
            self.assertFalse(extract_check.answers_cite("PE1", loc, rows), loc)
        # `inline`: nothing of it is answers; a row whose Answers isn't yes holds none.
        for loc in ("p.3", "Key", "Solutions"):
            self.assertFalse(extract_check.answers_cite("PE2", loc, rows), loc)
            self.assertFalse(extract_check.answers_cite("PE3", loc, rows), loc)
        self.assertEqual(key("pp. 7-9, 11")["pages"], {7, 8, 9, 11})
        self.assertEqual(key("inline")["pages"], set())

    def test_a_for_key_naming_no_doc_fails(self):
        # Review round 11: a pairing naming "Homework" left HW1 silently unsolved.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| for Homework |"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: KEY NAMES NO DOC: \"Homework\" in its Key cell is no doc id in "
                      "MANIFEST.md", out)
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| for Homework 1 (HW1) |"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: UNREAD KEY: \"for Homework 1 (HW1)\" isn't a Key form", out)
        self.assertNotIn("KEY NAMES NO DOC", out)
        # Its twin, the bare id, passes; the remark goes in Notes.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("official solutions to HW1",
                                                       "Homework 1 (HW1) solutions"))
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_for_key_reads_a_list(self):
        extra = ("| HW2 | `sources/hw2.pdf` | 1 | in | no | | yes | |\n"
                 "| HW3 | `sources/hw3.pdf` | 1 | in | no | | yes | |\n")
        for key in ("for HW1, HW2 and HW3", "for HW1, HW2, and HW3", "for HW1 & HW2 & HW3",
                    "FOR HW1 AND HW2 and HW3"):
            with self.subTest(key):
                self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", f"| {key} |")
                           + extra)
                rows = extract_check.manifest_rows(os.path.join(self.root, "MANIFEST.md"))
                self.assertEqual(rows["HW1S"]["key"]["docs"], {"HW1", "HW2", "HW3"})
                self.assertEqual(extract_check.solved(rows), {"HW1", "HW2", "HW3"})
        # A listed id MANIFEST lacks fails.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| for HW1 & HW4 |"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: KEY NAMES NO DOC: \"HW4\"", out)

    def test_the_lines_before_the_first_block_are_checked(self):
        # Review round 11: lines before a file's first `### [` header were read by no check.
        for line, needle in (
                ("Solution [HW1S p.1]: 42", "_build/extract/hw1.md:3: SOLUTION IN AN EXTRACT: a "
                 "solution before the file's first block; move it to its part's block in "
                 "_build/solutions/hw1.md"),
                ("**Solution:** 42", "_build/extract/hw1.md:3: SOLUTION IN AN EXTRACT: a solution "
                 "before"),
                ("The key gives 42 [HW1S p.1].", "_build/extract/hw1.md:3: CITES AN ANSWERS PAGE: "
                 "[HW1S p.1]"),
                ("UNREADABLE: the set's due date", "_build/extract/hw1.md:3: UNREADABLE flag still "
                 "open")):
            with self.subTest(line):
                self.write("_build/extract/hw1.md", CLEAN.replace(
                    "### [HW1 p.1]", f"{line}\n### [HW1 p.1]"))
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn(needle, out)
        # The title, Sources and viewed lines pass (CLEAN has them), as does the twin with the
        # line in its part's solutions block.
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "### [HW1 p.1]", "Every page image was viewed.\n### [HW1 p.1]"))
        code, out = self.check()
        self.assertEqual(code, 0, out)
        # A solutions file's opening lines count their flags too.
        self.write("_build/solutions/hw1.md", "UNREADABLE: the total\n"
                   "(illegible at 300 dpi: a date)\n" + SOLVED)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/hw1.md:1: UNREADABLE flag still open", out)
        self.assertIn("_build/solutions/hw1.md:2: (illegible at 300 dpi: a date), counted, not a "
                      "failure", out)

    def test_a_solution_citing_a_solved_or_answers_doc_fails_in_any_block(self):
        # Review round 11: a lecture's block (no solved doc) quoting a homework's solution passed.
        self.write("MANIFEST.md", SOL_MANIFEST + "| D1 | `sources/d1.pdf` | 1 | in | no | | yes | |\n")
        self.write("_build/pages/D1/p-001.png", "")
        for line, needle in (
                ("Solution [HW1 p.1]: 42", "_build/extract/d1.md:2: SOLUTION IN AN EXTRACT: [D1 "
                 "p.1] holds a solution citing [HW1 p.1], a doc with official solutions; a "
                 "solution goes only in its part's block under _build/solutions/"),
                ("**Solution:** as in [HW1S p.1]", "_build/extract/d1.md:2: SOLUTION IN AN "
                 "EXTRACT: [D1 p.1] holds a solution citing [HW1S p.1], an answers doc")):
            with self.subTest(line):
                self.write("_build/extract/d1.md", f"### [D1 p.1] Flows\n{line}\n")
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn(needle, out)
        # Its twin, the lecture's own worked solution, passes.
        self.write("_build/extract/d1.md", "### [D1 p.1] Flows\nSolution [D1 p.1]: augment twice.\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_an_answer_line_in_a_solved_docs_block_warns(self):
        warn = ("warning: _build/extract/hw1.md:9: an answer line in a block of HW1, a doc with "
                "official solutions: if it is an answer, move it to its part's block in "
                "_build/solutions/hw1.md")
        for line in ("Answer: f = 42", "- Answers: 3, 4", "> Ans: 7", "1. Final answer: 7",
                     "**Final answer:** 7", "*Solution*: push flow along s-a-t",
                     "Solution (HW1S p.1): 7"):
            with self.subTest(line):
                self.write("_build/extract/hw1.md", CLEAN.replace(
                    "**Shape:** compute\n", f"**Shape:** compute\n{line}\n"))
                code, out = self.check()
                self.assertEqual(code, 0, out)  # a warning, not a failure
                self.assertIn(warn, out)
        # An answer blank, a fenced line, or a block of a doc nothing solves, doesn't warn.
        for line in ("Answer: ____", "Answer: ...", "Answer: " + chr(0x2026), "Answer:",
                     "- Answer: \\_\\_\\_", "```\nAnswer: 42\n```"):
            with self.subTest(line):
                self.write("_build/extract/hw1.md", CLEAN.replace(
                    "**Shape:** compute\n", f"**Shape:** compute\n{line}\n"))
                code, out = self.check()
                self.assertEqual(code, 0, out)
                self.assertNotIn("an answer line", out)
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| 1 | in | yes |", "| 1 | out | yes |"))
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "**Shape:** compute\n", "**Shape:** compute\nAnswer: f = 42\n"))
        self.assertNotIn("an answer line", self.check()[1])

    def test_an_attempted_answers_row_still_answers(self):
        # The tutor writes `yes, attempted` once the set is attempted: still an answers row.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| in | yes | for HW1 | yes | official",
                                                       "| in | yes, attempted | for HW1 | yes | official"))
        rows = extract_check.manifest_rows(os.path.join(self.root, "MANIFEST.md"))
        self.assertTrue(rows["HW1S"]["answers"])
        self.assertEqual(extract_check.solved(rows), {"HW1"})
        # The set's own row carries `no, attempted <date>`: still no answers row.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| in | no | | yes | Homework 1",
                                                       "| in | no, attempted 2026-11-12 | | yes | "
                                                       "Homework 1"))
        rows = extract_check.manifest_rows(os.path.join(self.root, "MANIFEST.md"))
        self.assertFalse(rows["HW1"]["answers"])
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| in | yes | for HW1 | yes | official",
                                                       "| in | yes, attempted | for HW1 | yes | official"))
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.write("_build/solutions/hw1.md", "# HW1 solutions (extract)\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("NO SOLUTION BLOCK", out)

    # ---- review round 12 ----

    def test_each_key_form_reads_whole(self):
        # Review rounds 12 and 13: a parser stopping at a joiner it didn't know read `HW1/HW2` as
        # HW1 and `p.3 and p.4` as p.3, both with exit 0. The Key cell is read whole or refused.
        en = chr(0x2013)
        for cell, form, docs, pages, names in (
                ("", None, set(), set(), set()),
                ("-", None, set(), set(), set()),
                ("for HW1", "for", {"HW1"}, set(), set()),
                ("For HW1, HW2 and HW3", "for", {"HW1", "HW2", "HW3"}, set(), set()),
                ("for HW1, HW2, and HW3", "for", {"HW1", "HW2", "HW3"}, set(), set()),
                ("for HW1 & HW2", "for", {"HW1", "HW2"}, set(), set()),
                ("FOR HW1 AND HW2", "for", {"HW1", "HW2"}, set(), set()),
                ("p.3", "pages", set(), {3}, set()),
                ("P.3", "pages", set(), {3}, set()),
                ("pp. 7-9, 11", "pages", set(), {7, 8, 9, 11}, set()),
                ("pp. 3" + en + "4", "pages", set(), {3, 4}, set()),
                ("pp. 3 & 5", "pages", set(), {3, 5}, set()),
                ("pp. 3, and 5", "pages", set(), {3, 5}, set()),
                ("pp. 3 and 5", "pages", set(), {3, 5}, set()),
                ("p.3 and p.4", "pages", set(), {3, 4}, set()),
                ("inline", "inline", set(), set(), set()),
                ("INLINE", "inline", set(), set(), set()),
                ("sections: Marking scheme, Answers", "sections", set(), set(),
                 {"marking scheme", "answers"}),
                ("Sections:  Marking   Scheme", "sections", set(), set(), {"marking scheme"})):
            with self.subTest(cell):
                key = extract_check.read_key(cell)
                self.assertEqual((key["form"], key["docs"], key["pages"], set(key["names"])),
                                 (form, docs, pages, names))
        for cell in ("for HW1/HW2", "for HW1 + HW2", "for HW1 through HW3", "for HW1 (and HW2)",
                     "for HW1 and HW2, posted late", "for HW1; HW2", "for", "solutions to HW1",
                     "p.3 or p.4", "pp. 9-7", "pp. 5, 3", "pp. 3, 3", "pages 3-4", "key p.3",
                     "key inline", "inline; p.3", "sections", "sections:", "sections: Key,",
                     "sections Marking scheme", "Marking scheme"):
            with self.subTest(cell):
                self.assertEqual(extract_check.read_key(cell)["form"], "unread")

    def test_a_key_it_cant_read_fails(self):
        # The reproductions: `HW1/HW2` and `HW1; HW2` left HW2 unsolved, so a solution in HW2's
        # extract passed.
        hw2 = "| HW2 | `sources/hw2.pdf` | 1 | in | no | | yes | |\n"
        self.write("_build/pages/HW2/p-001.png", "")
        self.write("_build/extract/hw2.md", "### [HW2 Q1a] Flow\nPages: [HW2 p.1]\n"
                                            "**Solution:** f = 42\n")
        self.write("_build/solutions/hw2.md", "### [HW2 Q1a] Flow\nSolution [HW1S p.1]: 42\n")
        for cell in ("for HW1/HW2", "for HW1; HW2"):
            with self.subTest(cell):
                self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", f"| {cell} |")
                           + hw2)
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn(f"HW1S: UNREAD KEY: \"{cell}\" isn't a Key form: write \"for HW1, "
                              "HW2\", \"pp. 7-9, 11\", \"inline\" or \"sections: Marking scheme, "
                              "Answers\"", out)
                # The unread key fails alone: no NO KEY or ANSWERS WITH NO PAIRING after it.
                self.assertNotIn("NO KEY", out)
                self.assertNotIn("ANSWERS WITH NO PAIRING", out)
        # Its twin, the list written as the Key cell reads it, solves HW2: the solution fails.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| for HW1 and HW2 |")
                   + hw2)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertNotIn("UNREAD KEY", out)
        self.assertIn("_build/extract/hw2.md:3: SOLUTION IN AN EXTRACT", out)
        # A key page list it can't read fails the same way; `p.3 and p.4` reads both pages.
        self.add_pe1()
        self.write("MANIFEST.md", SOL_MANIFEST + PE_ROW.replace("| p.3 |", "| p.3 or p.4 |"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("PE1: UNREAD KEY: \"p.3 or p.4\" isn't a Key form", out)
        self.assertNotIn("NO KEY", out)
        self.write("MANIFEST.md", SOL_MANIFEST + PE_ROW.replace("| 3 |", "| 4 |").replace(
            "| p.3 |", "| p.3 and p.4 |"))
        self.write("_build/pages/PE1/p-004.png", "")
        self.write("_build/extract/pe1.md", PE + "### [PE1 p.4] Key, part 2\n\"Q2: 7\"\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/pe1.md:6: AN ANSWERS PAGE IN AN EXTRACT: [PE1 p.4] is a key "
                      "page of PE1", out)

    def test_a_sections_key_names_its_key_sections(self):
        # Review round 13: a Word exam's key headed "Marking scheme" stayed in the extract with
        # exit 0, since only Key, Answers or Solutions read as a key. The Key cell names the
        # sections, matched whole (any case, runs of whitespace as one); no word is guessed at.
        key = extract_check.read_key
        rows = {"PE3": {"answers": True, "key": key("sections: Marking scheme, Answers")}}
        for loc in ("Marking scheme", "marking  SCHEME", "Answers"):
            self.assertTrue(extract_check.answers_cite("PE3", loc, rows), loc)
        for loc in ("Key", "Key formulas", "Answer sheet", "Marking scheme 2", "Instructions",
                    "Q1", "p.3"):
            self.assertFalse(extract_check.answers_cite("PE3", loc, rows), loc)
        row = ("| PE3 | `sources/pe3.docx` | n/a | in | yes | sections: Marking scheme | n/a | "
               "past exam |\n")
        self.write("MANIFEST.md", SOL_MANIFEST + row)
        # Its instructions, formula sheet ("Key formulas") and parts in the extract, its marking
        # scheme in the solutions file: passes.
        rules = ("### [PE3 Instructions] Rules\n\"Closed book.\"\n"
                 "### [PE3 Key formulas] Formula sheet\n\"BFS visits each vertex once.\"\n"
                 "### [PE3 Q1] Trace\n\"Trace a BFS from s.\"\n")
        scheme = "### [PE3 Marking scheme] Marking scheme\n\"Q1: s, a, b (2 marks)\"\n"
        self.write("_build/extract/pe3.md", rules)
        self.write("_build/solutions/pe3.md", "### [PE3 Q1] Trace\n"
                                              "Solution [PE3 Marking scheme]: s, a, b\n" + scheme)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("PE3: 4 blocks, 1 question blocks", out)
        # The must-fail: its marking scheme left in the extract, and a line citing it.
        self.write("_build/extract/pe3.md", rules + "As in [PE3 Marking scheme].\n" + scheme)
        self.write("_build/solutions/pe3.md", "### [PE3 Q1] Trace\n"
                                              "Solution [PE3 Marking scheme]: s, a, b\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/pe3.md:7: CITES AN ANSWERS PAGE: [PE3 Marking scheme]", out)
        self.assertIn("_build/extract/pe3.md:8: AN ANSWERS PAGE IN AN EXTRACT: [PE3 Marking "
                      "scheme] is a key section of PE3, as its MANIFEST.md Key cell names it; "
                      "move it to _build/solutions/pe3.md", out)
        self.assertIn("PE3: KEY SECTION NOT FOUND: no block [PE3 Marking scheme] in "
                      "_build/solutions/", out)
        # A named section with no block anywhere fails too; its twin with the block passes.
        self.write("_build/extract/pe3.md", rules)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("PE3: KEY SECTION NOT FOUND: no block [PE3 Marking scheme]", out)
        self.write("_build/solutions/pe3.md", "### [PE3 Q1] Trace\nSolution [PE3 Q1]: s, a, b\n"
                                              "### [PE3   marking SCHEME] Key\n\"Q1: s, a, b\"\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_sections_key_on_a_paged_doc_fails(self):
        # A PDF, or any row whose Pages is a number, has key pages, not sections.
        for row in ("| PE3 | `sources/pe3.pdf` | n/a | in | yes | sections: Key | n/a | |\n",
                    "| PE3 | `sources/pe3.docx` | 4 | in | yes | sections: Key | n/a | |\n",
                    "| PE3 | `sources/pe3.PDF` | n/a | in | yes | sections: Key | n/a | |\n"):
            with self.subTest(row):
                self.write("MANIFEST.md", SOL_MANIFEST + row)
                self.write("_build/extract/pe3.md", "### [PE3 Q1] Trace\n\"Trace a BFS.\"\n")
                self.write("_build/solutions/pe3.md", "### [PE3 Q1] Trace\nSolution [PE3 Key]: s\n"
                                                      "### [PE3 Key] Key\n\"Q1: s\"\n")
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn("PE3: SECTIONS KEY ON A PAGED DOC: use \"pp. N-M\" or \"inline\"",
                              out)
        # Its twin, a Word file with no page count, passes.
        self.write("MANIFEST.md", SOL_MANIFEST + "| PE3 | `sources/pe3.docx` | n/a | in | yes | "
                                                 "sections: Key | n/a | |\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_key_on_a_row_without_answers_fails(self):
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| in | no | | yes | Homework 1 |",
                                                       "| in | no | p.1 | yes | Homework 1 |"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1: KEY WITHOUT ANSWERS: its Key cell is filled but Answers isn't yes", out)
        # `no, attempted` is still no; `-` is an empty Key cell and passes.
        self.write("MANIFEST.md", SOL_MANIFEST.replace(
            "| in | no | | yes | Homework 1 |", "| in | no, attempted 2026-11-12 | for HW1 | yes | |"))
        self.assertIn("HW1: KEY WITHOUT ANSWERS", self.check()[1])
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| in | no | | yes | Homework 1 |",
                                                       "| in | no | - | yes | Homework 1 |"))
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_an_unverified_answers_row_skips_its_key_checks_and_solves_nothing(self):
        # Review round 12: the note checks ran before the `Unverified:` skip, so a row added at
        # the student's request without an extract failed on its note.
        self.write("STATUS.md", "# STATUS\n\n- Unverified: PE2, s9, 2026-11-12\n")
        row = "| PE2 | `sources/pe2.pdf` | 2 | in | yes | {} | no | |\n"
        for key in ("", "for HW1/HW2", "for HW9", "sections: Key"):
            with self.subTest(key):
                self.write("MANIFEST.md", SOL_MANIFEST + row.format(key))
                code, out = self.check()
                self.assertEqual(code, 0, out)
                self.assertIn("PE2: unverified, added without an extract", out)
        # Review round 13 (r13-1 #8): it solves nothing either. HW2, which only PE2 would solve,
        # needs no solutions block while PE2 is skipped...
        hw2 = "| HW2 | `sources/hw2.pdf` | 1 | in | no | | yes | |\n"
        self.write("MANIFEST.md", SOL_MANIFEST + hw2 + row.format("for HW2"))
        self.write("_build/pages/HW2/p-001.png", "")
        self.write("_build/extract/hw2.md", "### [HW2 Q1a] Flow\nPages: [HW2 p.1]\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("NO SOLUTION BLOCK", out)
        # ...and once the STATUS line goes, PE2's key solves HW2.
        self.write("STATUS.md", "# STATUS\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/hw2.md:1: NO SOLUTION BLOCK", out)
        # Once it has a block, its row is checked like any other.
        self.write("STATUS.md", "# STATUS\n\n- Unverified: PE2, s9, 2026-11-12\n")
        self.write("MANIFEST.md", SOL_MANIFEST + row.format(""))
        self.write("_build/extract/pe2.md", "### [PE2 Q1] Trace\nPages: [PE2 p.1]\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("PE2: NO KEY", out)

    def test_an_extracts_cite_of_a_key_page_covers_nothing(self):
        # Review round 12: a part's `Pages:` line naming the key page covered it, so the key page
        # needed no block anywhere.
        self.add_pe1()
        self.write("_build/extract/pe1.md", PE.replace("Pages: [PE1 p.1-2]", "Pages: [PE1 p.1-3]"))
        self.write("_build/solutions/pe1.md", "### [PE1 Q1] Trace\nSolution [PE1 Q1]: s, a, b\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("PE1: 3 pages in scope, 3 rendered, 2 with a block, 1 question blocks, "
                      "0 image only, 0 UNREADABLE; MISSING 3", out)
        # Its twin, the key page's block in the solutions file, passes.
        self.write("_build/solutions/pe1.md", "### [PE1 Q1] Trace\nSolution [PE1 Q1]: s, a, b\n"
                   + PE_KEY)
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_self_keyed_row_with_no_question_block_says_its_parts_need_blocks(self):
        self.add_pe1()
        self.write("_build/extract/pe1.md", "### [PE1 p.1] Practice exam\n### [PE1 p.2] Q1\n")
        self.write("_build/solutions/pe1.md", PE_KEY)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("PE1: ANSWERS WITH NO PAIRING: a doc with its own key (its Key cell) with no "
                      "question block in any extract; its question parts need blocks in an "
                      "extract, or its Key cell names the sets it solves (\"for HW1, HW2\")", out)

    def test_an_answer_line_before_the_first_block_warns(self):
        # Review round 12: the lines before a file's first header got the failures, not the
        # warnings. Twin of test_an_answer_line_in_a_solved_docs_block_warns.
        for line, warn in (
                ("Answer: f = 42", "warning: _build/extract/hw1.md:3: an answer line before the "
                 "file's first block, in an extract of HW1, a doc with official solutions: if it "
                 "is an answer, move it to its part's block in _build/solutions/hw1.md"),
                ("#### Solution", "warning: _build/extract/hw1.md:3: a loose `Solution:` line "
                 "before the file's first block, in an extract of HW1, a doc with official "
                 "solutions; if it gives an answer, move it to _build/solutions/hw1.md; question "
                 "text stays")):
            with self.subTest(line):
                self.write("_build/extract/hw1.md", CLEAN.replace(
                    "### [HW1 p.1]", f"{line}\n### [HW1 p.1]"))
                code, out = self.check()
                self.assertEqual(code, 0, out)  # a warning, not a failure
                self.assertIn(warn, out)
        # An answer blank, a fenced line, or a file of a doc nothing solves, doesn't warn.
        for line in ("Answer: ____", "```\nAnswer: 42\n```"):
            with self.subTest(line):
                self.write("_build/extract/hw1.md", CLEAN.replace(
                    "### [HW1 p.1]", f"{line}\n### [HW1 p.1]"))
                code, out = self.check()
                self.assertEqual(code, 0, out)
                self.assertNotIn("warning", out)
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| 1 | in | yes |", "| 1 | out | yes |"))
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "### [HW1 p.1]", "Answer: f = 42\n### [HW1 p.1]"))
        self.assertNotIn("an answer line", self.check()[1])

    # ---- review round 13 ----

    def test_a_part_block_sits_beside_its_extract(self):
        # One solutions file per set: a part's block goes in the solutions file named as the
        # extract holding its question block, and every message names that file.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| for HW1 and HW2 |")
                   + "| HW2 | `sources/hw2.pdf` | 1 | in | no | | yes | |\n")
        self.write("_build/pages/HW2/p-001.png", "")
        self.write("_build/extract/hw2.md", "### [HW2 Q1a] Flow\nPages: [HW2 p.1]\n")
        part = "### [HW2 Q1a] Flow\nSolution [HW1S p.1]: 42\n"
        self.write("_build/solutions/hw1.md", SOLVED + part)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/hw1.md:6: WRONG SOLUTIONS FILE: [HW2 Q1a] belongs in "
                      "_build/solutions/hw2.md, beside its extract", out)
        self.assertNotIn("WRONG SOLUTIONS FILE: [HW1", out)
        # Its twin passes, with the answers file's own page block in either solutions file or
        # in one of its own name (holding no text, since it solves two sets).
        shared = "### [HW1S p.1] Solutions\n(transcribed under the sets' blocks)\n"
        self.write("_build/solutions/hw2.md", part + shared)
        self.write("_build/solutions/hw1.md", SOLVED)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.write("_build/solutions/hw2.md", part)
        self.write("_build/solutions/hw1s.md", shared)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        # With no block, the failure names the part's own solutions file, not another set's.
        self.remove("_build/solutions/hw2.md")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/hw2.md:1: NO SOLUTION BLOCK: write its solution or \"No "
                      "official solution.\" under ### [HW2 Q1a] in _build/solutions/hw2.md", out)
        # A solution left in the extract names its own solutions file too.
        self.write("_build/extract/hw2.md", "### [HW2 Q1a] Flow\nPages: [HW2 p.1]\n"
                                            "Solution [HW1S p.1]: 42\n")
        self.assertIn("_build/extract/hw2.md:3: SOLUTION IN AN EXTRACT: [HW2 Q1a] is a block of "
                      "HW2, a doc with official solutions; move the solution to its part's block "
                      "in _build/solutions/hw2.md", self.check()[1])

    def test_an_extracts_cite_of_an_answers_files_page_covers_nothing(self):
        # r13-1 #5: an answers file's page named on a part's `Pages:` line in an extract covered
        # it, so the page needed no block anywhere.
        self.write("_build/extract/hw1.md", CLEAN.replace("Pages: [HW1 p.1]\n",
                                                          "Pages: [HW1 p.1], [HW1S p.1]\n"))
        self.write("_build/solutions/hw1.md", SOLVED.replace(
            "Solution [HW1S p.1]: by the min-cut bound.", "No official solution."))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: 1 pages in scope, 1 rendered, 0 with a block, 0 image only, "
                      "0 UNREADABLE; MISSING 1", out)
        # Its twin, the solutions file's cite of the page, covers it.
        self.write("_build/solutions/hw1.md", SOLVED)
        code, out = self.check()
        self.assertEqual(code, 0, out)

    # ---- review round 14 ----

    def test_a_for_key_naming_its_own_doc_fails_and_reads_all_of_it_as_answers(self):
        # r14-1 #1: `for PE1` on PE1's own row read no block or cite of PE1 as answers, so its
        # key page sat in the extract with exit 0. It fails, and every block of PE1 reads as
        # answers meanwhile (fail closed), so the key page is still caught.
        self.add_pe1(key_in_extract=True)
        self.write("MANIFEST.md", SOL_MANIFEST + PE_ROW.replace("| p.3 |", "| for PE1 |"))
        rows = {"PE1": {"answers": True, "key": extract_check.read_key("for PE1")}}
        for loc in ("p.1", "p.3", "Q1", "Cover"):
            self.assertTrue(extract_check.answers_cite("PE1", loc, rows), loc)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("PE1: KEY NAMES ITS OWN DOC: \"for\" names the docs an answers file solves; "
                      "a doc holding its own key uses \"pp. N-M\", \"inline\" or "
                      "\"sections: <name>\"", out)
        self.assertIn("_build/extract/pe1.md:6: AN ANSWERS PAGE IN AN EXTRACT: [PE1 p.3]", out)
        # In a list with another doc, too.
        self.write("MANIFEST.md", SOL_MANIFEST + PE_ROW.replace("| p.3 |", "| for HW1, PE1 |"))
        self.assertIn("PE1: KEY NAMES ITS OWN DOC", self.check()[1])
        # Its twin, the key named by its pages and its page in the solutions file, passes.
        self.add_pe1()
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("KEY NAMES ITS OWN DOC", out)

    def test_a_pages_key_on_an_unpaged_doc_fails(self):
        # r14-1 #2: a page key on a source without pages protected nothing, since its blocks'
        # locators carry no page.
        for row in ("| PE3 | `sources/pe3.docx` | n/a | in | yes | p.3 | n/a | |\n",
                    "| PE3 | `sources/pe3.docx` | | in | yes | pp. 2-3 | n/a | |\n",
                    "| PE3 | `sources/pe3.html` | n/a | in | yes | p.5 | n/a | |\n"):
            with self.subTest(row):
                self.write("MANIFEST.md", SOL_MANIFEST + row)
                self.write("_build/extract/pe3.md", "### [PE3 Q1] Trace\n\"Trace a BFS.\"\n"
                                                    "### [PE3 Key] Key\n\"Q1: s\"\n")
                self.write("_build/solutions/pe3.md", "### [PE3 Q1] Trace\nSolution [PE3 Key]: s\n")
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn("PE3: PAGES KEY ON AN UNPAGED DOC: use \"sections: <name>, "
                              "<name>\" or \"inline\"", out)
        # Its twin names the key section, which then belongs in the solutions file.
        self.write("MANIFEST.md", SOL_MANIFEST + "| PE3 | `sources/pe3.docx` | n/a | in | yes | "
                                                 "sections: Key | n/a | |\n")
        self.write("_build/extract/pe3.md", "### [PE3 Q1] Trace\n\"Trace a BFS.\"\n")
        self.write("_build/solutions/pe3.md", "### [PE3 Q1] Trace\nSolution [PE3 Key]: s\n"
                                              "### [PE3 Key] Key\n\"Q1: s\"\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        # A PDF, or a row whose Pages is a number, takes a page key.
        self.write("MANIFEST.md", SOL_MANIFEST + "| PE3 | `sources/pe3.docx` | 4 | in | yes | "
                                                 "p.4 | n/a | |\n")
        self.assertNotIn("PAGES KEY ON AN UNPAGED DOC", self.check()[1])

    def test_a_decks_solution_slides_are_named_as_sections(self):
        # A reveal deck's key is its solution slides, named by fragment: `sections: #/5`.
        deck = ("<div class=\"reveal\"><div class=\"slides\">"
                + "".join(f"<section>S{i}</section>" for i in range(6)) + "</div></div>")
        self.write("sources/r3.html", deck)
        self.write("MANIFEST.md", SOL_MANIFEST + "| R3 | `sources/r3.html` | n/a | in | yes | "
                                                 "sections: #/5 | n/a | recitation |\n")
        slides = "".join(f"### [R3 #/{i}] S{i}\n" for i in range(5))
        question = "### [R3 Q1] Trace\nPages: [R3 #/3]\n\"Trace a BFS.\"\n"
        key = "### [R3 #/5] Solutions\n\"Q1: s, a, b\"\n"
        self.write("_build/extract/r3.md", slides + question)
        self.write("_build/solutions/r3.md", "### [R3 Q1] Trace\nSolution [R3 #/5]: s, a, b\n"
                   + key)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("R3: 6 slides in scope, 6 with a block", out)
        # The must-fail: the solution slide's block left in the extract.
        self.write("_build/extract/r3.md", slides + question + key)
        self.write("_build/solutions/r3.md", "### [R3 Q1] Trace\nSolution [R3 #/5]: s, a, b\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/r3.md:9: AN ANSWERS PAGE IN AN EXTRACT: [R3 #/5] is a key "
                      "section of R3, as its MANIFEST.md Key cell names it; move it to "
                      "_build/solutions/r3.md", out)
        # A page key on the deck protects nothing, so it fails.
        self.write("MANIFEST.md", SOL_MANIFEST + "| R3 | `sources/r3.html` | n/a | in | yes | "
                                                 "p.5 | n/a | recitation |\n")
        self.assertIn("R3: PAGES KEY ON AN UNPAGED DOC", self.check()[1])

    def test_a_multi_set_answers_files_page_blocks_hold_no_text(self):
        # r14-2 #1: a page block of an answers file solving several sets sits in its own
        # solutions file, which no question check reads, so it holds no official text.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| for HW1 and HW2 |")
                   + "| HW2 | `sources/hw2.pdf` | 1 | in | no | | yes | |\n")
        self.write("_build/pages/HW2/p-001.png", "")
        self.write("_build/extract/hw2.md", "### [HW2 Q1a] Flow\nPages: [HW2 p.1]\n")
        self.write("_build/solutions/hw2.md", "### [HW2 Q1a] Flow\nSolution [HW1S p.1]: 7\n")
        ok = ("# HW1S\n### [HW1S p.1] Solutions\n(transcribed under the sets' blocks)\n\n"
              "(blank)\n(image only: a graph of f(x))\n(illegible at 300 dpi: the total)\n"
              "Coverage: p.1; 1 blocks; 1 image only; 0 flagged unreadable.\n")
        self.write("_build/solutions/hw1s.md", ok)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        for line in ("\"Q1a: f = 42\"", "f = 42", "unreadable: 42",
                     "(transcribed under the sets' blocks) f = 42"):
            with self.subTest(line):
                self.write("_build/solutions/hw1s.md", ok.replace("(blank)\n", line + "\n"))
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn("_build/solutions/hw1s.md:5: SHARED ANSWERS PAGE HOLDS TEXT: a page "
                              "block of HW1S, which solves several sets, holds only "
                              "\"(transcribed under the sets' blocks)\"; put this under its set's "
                              "stem or part block in _build/solutions/<set>.md", out)
        # An open flag fails as a flag, not as text.
        self.write("_build/solutions/hw1s.md", ok.replace("(blank)\n", "UNREADABLE: p.1 total\n"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertNotIn("SHARED ANSWERS PAGE", out)
        self.assertIn("_build/solutions/hw1s.md:5: UNREADABLE flag still open", out)
        # A single-set answers file's page block, beside its set's part blocks, holds its text.
        self.write("MANIFEST.md", SOL_MANIFEST)
        self.remove("_build/extract/hw2.md")
        self.remove("_build/solutions/hw2.md")
        self.write("_build/solutions/hw1s.md", "### [HW1S p.1] Solutions\n\"Q1a: f = 42\"\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_an_idle_unverified_answers_file_is_no_answers_doc(self):
        # r14-1 #3: an `Unverified:` answers row with no block solves nothing, and nothing of it
        # reads as answers either: an extract citing its page passes.
        self.write("STATUS.md", "# STATUS\n\n- Unverified: HW1S, s3, 2026-11-13\n")
        self.remove("_build/solutions/hw1.md")
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "**Shape:** compute\n", "**Shape:** compute\nSee [HW1S p.1].\n"))
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("HW1S: unverified, added without an extract", out)
        self.assertNotIn("CITES AN ANSWERS PAGE", out)
        # Its twin, with the STATUS line gone, is an answers file again.
        self.write("STATUS.md", "# STATUS\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/hw1.md:9: CITES AN ANSWERS PAGE: [HW1S p.1]", out)

    def test_a_key_sections_part_or_continuation_is_key_material(self):
        # r14-1 #4: `[PE3 Marking scheme Q1]` and `[PE3 Marking scheme, part 2]` are the key too.
        key = extract_check.read_key
        rows = {"PE3": {"answers": True, "key": key("sections: Marking scheme")}}
        for loc in ("Marking scheme Q1", "marking  SCHEME Q2b", "Marking scheme, part 2",
                    "Marking scheme , part 2"):
            self.assertTrue(extract_check.answers_cite("PE3", loc, rows), loc)
        for loc in ("Marking schemes", "Marking scheme 2", "Marking scheme Q1 p.3"):
            self.assertFalse(extract_check.answers_cite("PE3", loc, rows), loc)
        rows = {"PE3": {"answers": True, "key": key("sections: Key")}}
        self.assertFalse(extract_check.answers_cite("PE3", "Key formulas", rows))
        self.assertTrue(extract_check.answers_cite("PE3", "Key Q1", rows))
        self.write("MANIFEST.md", SOL_MANIFEST + "| PE3 | `sources/pe3.docx` | n/a | in | yes | "
                                                 "sections: Key | n/a | |\n")
        sols = "### [PE3 Q1] Trace\nSolution [PE3 Key Q1]: s\n### [PE3 Key] Key\n\"Q1: s\"\n"
        rules = "### [PE3 Key formulas] Formula sheet\n\"BFS visits each vertex once.\"\n"
        question = "### [PE3 Q1] Trace\n\"Trace a BFS.\"\n"
        self.write("_build/extract/pe3.md", rules + question)
        self.write("_build/solutions/pe3.md", sols)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.write("_build/extract/pe3.md", rules + question + "As in [PE3 Key, part 2].\n"
                   + "### [PE3 Key Q1] Key to Q1\n\"s\"\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/pe3.md:5: CITES AN ANSWERS PAGE: [PE3 Key, part 2]", out)
        self.assertIn("_build/extract/pe3.md:6: AN ANSWERS PAGE IN AN EXTRACT: [PE3 Key Q1] is a "
                      "key section of PE3", out)

    def test_a_part_in_two_extracts_takes_either_extracts_solutions_file(self):
        # r14-1 #5: a part whose question block sits in two extracts may have its solutions block
        # beside either; any other solutions file is wrong.
        self.write("_build/extract/hw1b.md", "### [HW1 Q1a] Max flow\nPages: [HW1 p.1]\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.remove("_build/solutions/hw1.md")
        self.write("_build/solutions/hw1b.md", SOLVED)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.remove("_build/solutions/hw1b.md")
        self.write("_build/solutions/other.md", SOLVED)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/other.md:3: WRONG SOLUTIONS FILE: [HW1 Q1a] belongs in "
                      "_build/solutions/hw1.md, beside its extract", out)


if __name__ == "__main__":
    unittest.main()
