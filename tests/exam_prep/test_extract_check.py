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
doc as answers meanwhile; only a PDF is paged, so a page key on any other row fails PAGES KEY ON
AN UNPAGED DOC, and a deck (its Pages a slide count) names its solution slides as sections
(`sections: #/5`); a stem's solutions block warns only while a part lacks its own; a key
section's `<name> Q1` and `<name>, ...` are key material; an idle unverified answers file solves
nothing, yet a cite of its page still fails; a part in two extracts takes either extract's
solutions file.

Review round 15: every block in a solutions file has one home file (WRONG SOLUTIONS FILE): a
stem's beside its set's extract, a single-set answers file's page beside its set, a multi-set
answers file's page, in full, in its own lower-case file, a self-keyed doc's key page or key
section beside its own extract (KEY SECTION NOT FOUND looks there only). A key section's name
then no letter or digit (`(continued)`, `: Q2`, a deck's `#/5/0`) is key material.

Review round 16: a doc's homes are the extracts holding any block of it (a page, section, slide or
question block), not only its question blocks, so a page-only set or a deck split over two
extracts has a home; a stem's, a single-set answers page's or a key block whose set has no block
in any extract fails NO HOME FILE, and KEY SECTION NOT FOUND looks in every home. A key
section's locator is key material whatever page reference it carries (`Marking scheme p.2`).
AN ANSWERS PAGE IN AN EXTRACT names the block's home, not the extract's own solutions file.

Review round 17: an in-scope answers file keyed for a pending, reserved or out set fails KEY NAMES
A SET NOT IN SCOPE, so NO HOME FILE's "extract <SET> first" is said only of an in-scope set; a
question block labelled with an answers file's id fails ANSWERS FILE ID ON A QUESTION wherever it
sits; a `sections:` name's page reference is dropped as the locator's is; `--leak-files` prints
the questions check's files from the computed homes (LeakFiles)."""
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
        self.assertIn("PE3: KEY SECTION NOT FOUND: no block [PE3 Marking scheme] in its home "
                      "solutions file\n", out)
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
        # A PDF has key pages, not sections, whatever its Pages column holds.
        for row in ("| PE3 | `sources/pe3.pdf` | n/a | in | yes | sections: Key | n/a | |\n",
                    "| PE3 | `sources/pe3.pdf` | 4 | in | yes | sections: Key | n/a | |\n",
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
        # Its twins, a Word file with no page count or with one, pass: only a PDF is paged.
        for pages in ("n/a", "4"):
            with self.subTest(pages):
                self.write("MANIFEST.md", SOL_MANIFEST + f"| PE3 | `sources/pe3.docx` | {pages} | "
                                                         "in | yes | sections: Key | n/a | |\n")
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
        # Its twin passes, with the answers file's own page block, in full, in its own file
        # (it solves two sets); in a set's solutions file that block is wrong too.
        shared = "### [HW1S p.1] Solutions\n\"Q1a: f = 42\"\n"
        self.write("_build/solutions/hw2.md", part)
        self.write("_build/solutions/hw1.md", SOLVED)
        self.write("_build/solutions/hw1s.md", shared)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.write("_build/solutions/hw2.md", part + shared)
        self.remove("_build/solutions/hw1s.md")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/hw2.md:3: WRONG SOLUTIONS FILE: [HW1S p.1] belongs in "
                      "_build/solutions/hw1s.md, its own file, since it solves several sets", out)
        self.write("_build/solutions/hw2.md", part)
        self.write("_build/solutions/hw1s.md", shared)
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
                    "| PE3 | `sources/pe3.docx` | 4 | in | yes | p.4 | n/a | |\n",
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
        # A PDF takes a page key.
        self.write("MANIFEST.md", SOL_MANIFEST + "| PE3 | `sources/pe3.pdf` | 4 | in | yes | "
                                                 "p.4 | n/a | |\n")
        self.assertNotIn("PAGES KEY ON AN UNPAGED DOC", self.check()[1])

    def test_a_decks_solution_slides_are_named_as_sections(self):
        # A reveal deck's key is its solution slides, named by fragment: `sections: #/5`. Its
        # Pages column holds its slide count, as the fixture's deck row does; it is still unpaged.
        deck = ("<div class=\"reveal\"><div class=\"slides\">"
                + "".join(f"<section>S{i}</section>" for i in range(6)) + "</div></div>")
        self.write("sources/r3.html", deck)
        self.write("MANIFEST.md", SOL_MANIFEST + "| R3 | `sources/r3.html` | 6 | in | yes | "
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
        self.write("MANIFEST.md", SOL_MANIFEST + "| R3 | `sources/r3.html` | 6 | in | yes | "
                                                 "p.5 | n/a | recitation |\n")
        self.assertIn("R3: PAGES KEY ON AN UNPAGED DOC", self.check()[1])

    def test_a_multi_set_answers_file_holds_its_pages_in_full_in_its_own_file(self):
        # Round 15 (Hayden, 2026-11-13): an answers file solving several sets keeps its pages in
        # full in _build/solutions/<its doc id in lower case>.md, which the questions check reads
        # while any set it solves is unattempted; no pointer line, no text rule.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| for HW1 and HW2 |")
                   + "| HW2 | `sources/hw2.pdf` | 1 | in | no | | yes | |\n")
        self.write("_build/pages/HW2/p-001.png", "")
        self.write("_build/extract/hw2.md", "### [HW2 Q1a] Flow\nPages: [HW2 p.1]\n")
        self.write("_build/solutions/hw2.md", "### [HW2 Q1a] Flow\nSolution [HW1S p.1]: 7\n")
        full = ("# HW1S\n### [HW1S p.1] Solutions\n\"Q1a: f = 42, by the min-cut bound.\"\n"
                "\"Q1a (HW2): 7\"\n(image only: a graph of f(x))\n"
                "Coverage: p.1; 1 blocks; 1 image only; 0 flagged unreadable.\n")
        self.write("_build/solutions/hw1s.md", full)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("HW1S: 1 pages in scope, 1 rendered, 1 with a block, 1 image only", out)
        # The must-fail: the same page in a set's solutions file, or under another name.
        hw2 = "### [HW2 Q1a] Flow\nSolution [HW1S p.1]: 7\n"
        for name in ("hw1.md", "hw2.md", "HW1S.md", "answers.md"):
            with self.subTest(name):
                self.remove("_build/solutions/hw1s.md")
                texts = {"hw1.md": SOLVED, "hw2.md": hw2}
                texts[name] = texts.get(name, "") + full
                for n, text in texts.items():
                    self.write(f"_build/solutions/{n}", text)
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertRegex(out, re.escape(f"_build/solutions/{name}:") + r"\d+: "
                                 + re.escape("WRONG SOLUTIONS FILE: [HW1S p.1] belongs in "
                                             "_build/solutions/hw1s.md, its own file, since it "
                                             "solves several sets"))
                if name not in ("hw1.md", "hw2.md"):
                    self.remove(f"_build/solutions/{name}")
                self.write("_build/solutions/hw1.md", SOLVED)
                self.write("_build/solutions/hw2.md", hw2)
                self.write("_build/solutions/hw1s.md", full)
        # The text rule is gone: a page line no pointer form allows is no failure of its own.
        self.assertNotIn("SHARED", self.check()[1])

    def test_a_single_set_answers_files_page_sits_beside_its_set(self):
        # r15-1 #2: a single-set answers file's page block passed in any solutions file, so its
        # official text sat in a file the questions check never reads.
        self.write("_build/solutions/hw1s.md", "### [HW1S p.1] Solutions\n\"Q1a: f = 42\"\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/hw1s.md:1: WRONG SOLUTIONS FILE: [HW1S p.1] belongs in "
                      "_build/solutions/hw1.md, beside the one set it solves", out)
        # Its twin, the page block in the set's own solutions file, passes.
        self.remove("_build/solutions/hw1s.md")
        self.write("_build/solutions/hw1.md",
                   SOLVED + "### [HW1S p.1] Solutions\n\"Q1a: f = 42\"\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_stem_block_sits_beside_its_sets_extract(self):
        # r15-1 #1: a stem block with official text passed in any solutions file.
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "### [HW1 Q1a]", "### [HW1 Q1 stem] Setup\nPages: [HW1 p.1]\n### [HW1 Q1a]"))
        stem = "### [HW1 Q1 stem] Setup\nSolution [HW1S p.1]: f = 42 throughout.\n"
        self.write("_build/solutions/hw1s.md", stem)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/hw1s.md:1: WRONG SOLUTIONS FILE: [HW1 Q1 stem] belongs in "
                      "_build/solutions/hw1.md, beside its extract", out)
        # Its twin, the stem block in the set's solutions file, passes.
        self.remove("_build/solutions/hw1s.md")
        self.write("_build/solutions/hw1.md", stem + SOLVED)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        # A stem whose own question block is elsewhere may sit beside any extract of its set.
        self.write("_build/extract/hw1b.md", "### [HW1 Q2 stem] More\nPages: [HW1 p.1]\n")
        self.write("_build/solutions/hw1.md", stem + SOLVED + "### [HW1 Q2 stem] More\nx\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_self_keyed_docs_key_page_sits_beside_its_own_extract(self):
        # r15-1 #1 variant: a key page block passed in any solutions file.
        self.add_pe1()
        self.write("_build/solutions/pe1.md", PE_SOLS)
        self.write("_build/solutions/keys.md", PE_KEY)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/keys.md:1: WRONG SOLUTIONS FILE: [PE1 p.3] belongs in "
                      "_build/solutions/pe1.md, beside its own extract", out)
        # Its twin passes; a page that is no key page (the cover) is placed nowhere.
        self.write("_build/solutions/keys.md", "### [PE1 p.1] Practice exam\n\"Time: 50.\"\n")
        self.write("_build/solutions/pe1.md", PE_SOLS + PE_KEY)
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_key_section_is_found_only_beside_its_own_extract(self):
        self.write("MANIFEST.md", SOL_MANIFEST + "| PE3 | `sources/pe3.docx` | n/a | in | yes | "
                                                 "sections: Marking scheme | n/a | |\n")
        self.write("_build/extract/pe3.md", "### [PE3 Q1] Trace\n\"Trace a BFS.\"\n")
        sols = "### [PE3 Q1] Trace\nSolution [PE3 Marking scheme]: s\n"
        scheme = "### [PE3 Marking scheme] Key\n\"Q1: s\"\n"
        self.write("_build/solutions/pe3.md", sols)
        self.write("_build/solutions/keys.md", scheme)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/keys.md:1: WRONG SOLUTIONS FILE: [PE3 Marking scheme] "
                      "belongs in _build/solutions/pe3.md, beside its own extract", out)
        self.assertIn("PE3: KEY SECTION NOT FOUND: no block [PE3 Marking scheme]", out)
        # Its twin passes; so does a key section found only by its parts.
        self.remove("_build/solutions/keys.md")
        self.write("_build/solutions/pe3.md", sols + scheme)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.write("_build/solutions/pe3.md", sols + "### [PE3 Marking scheme Q1] Key\n\"s\"\n"
                   "### [PE3 Marking scheme (continued)] Key\n\"t\"\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_an_idle_unverified_answers_file_solves_nothing_yet_is_still_answers(self):
        # r14-1 #3: an `Unverified:` answers row with no block was dropped from every check, so an
        # extract line citing its page passed. It solves nothing (no part of HW1 needs a block),
        # but its pages are still answers pages.
        self.write("STATUS.md", "# STATUS\n\n- Unverified: HW1S, s3, 2026-11-13\n")
        self.remove("_build/solutions/hw1.md")
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "**Shape:** compute\n", "**Shape:** compute\nSee [HW1S p.1].\n"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: unverified, added without an extract", out)
        self.assertIn("_build/extract/hw1.md:9: CITES AN ANSWERS PAGE: [HW1S p.1]", out)
        self.assertNotIn("NO SOLUTION BLOCK", out)
        # Without the cite line it passes.
        self.write("_build/extract/hw1.md", CLEAN)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        # Its twin, with the STATUS line gone: HW1S solves HW1, so its part needs a block.
        self.write("STATUS.md", "# STATUS\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/hw1.md:5: NO SOLUTION BLOCK", out)

    def test_a_key_sections_part_or_continuation_is_key_material(self):
        # r14-1 #4: `[PE3 Marking scheme Q1]` and `[PE3 Marking scheme, part 2]` are the key too.
        key = extract_check.read_key
        rows = {"PE3": {"answers": True, "key": key("sections: Marking scheme")}}
        for loc in ("Marking scheme Q1", "marking  SCHEME Q2b", "Marking scheme, part 2",
                    "Marking scheme , part 2", "Marking scheme Q1 p.3"):
            self.assertTrue(extract_check.answers_cite("PE3", loc, rows), loc)
        for loc in ("Marking schemes", "Marking scheme 2"):
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

    def test_a_key_sections_name_then_no_letter_or_digit_is_key_material(self):
        # r15-1 #3: `Marking scheme (continued)`, `Marking scheme: Q2` and a deck's child slide
        # `#/5/0` under `sections: #/5` read as question material.
        key = extract_check.read_key
        rows = {"PE3": {"answers": True, "key": key("sections: Marking scheme")}}
        for loc in ("Marking scheme", "Marking scheme (continued)", "Marking scheme: Q2",
                    "Marking scheme - Q2", "Marking scheme, part 2", "Marking scheme Q1",
                    "Marking schemeQ1", "Marking scheme  (cont.)", "Marking scheme (continued) p.3"):
            self.assertTrue(extract_check.answers_cite("PE3", loc, rows), loc)
        for loc in ("Marking schemes", "Marking scheme 2", "Marking scheme Questions",
                    "Marking scheme q1", "Marking", "Rules"):
            self.assertFalse(extract_check.answers_cite("PE3", loc, rows), loc)
        rows = {"R3": {"answers": True, "key": key("sections: #/5")}}
        for loc in ("#/5", "#/5/0", "#/5/1"):
            self.assertTrue(extract_check.answers_cite("R3", loc, rows), loc)
        for loc in ("#/50", "#/51/0", "#/4/5"):
            self.assertFalse(extract_check.answers_cite("R3", loc, rows), loc)
        # A deck whose key is a vertical stack, #/5/0 and #/5/1: its child slides are its key.
        deck = ("<div class=\"reveal\"><div class=\"slides\">"
                + "".join(f"<section>S{i}</section>" for i in range(5))
                + "<section><section>K0</section><section>K1</section></section></div></div>")
        self.write("sources/r3.html", deck)
        self.write("MANIFEST.md", SOL_MANIFEST + "| R3 | `sources/r3.html` | 7 | in | yes | "
                                                 "sections: #/5 | n/a | recitation |\n")
        slides = "".join(f"### [R3 #/{i}] S{i}\n" for i in range(5))
        question = "### [R3 Q1] Trace\nPages: [R3 #/3]\n\"Trace a BFS.\"\n"
        key_slides = "### [R3 #/5/0] Solutions\n\"Q1: s, a\"\n### [R3 #/5/1] More\n\"then b\"\n"
        self.write("_build/extract/r3.md", slides + question)
        self.write("_build/solutions/r3.md", "### [R3 Q1] Trace\nSolution [R3 #/5/1]: s, a, b\n"
                   + key_slides)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("R3: 7 slides in scope, 7 with a block", out)
        # The must-fail: #/5/1 left in the extract, and an extract line citing #/5/0.
        self.write("_build/extract/r3.md", slides + question + "As on [R3 #/5/0].\n"
                   + "### [R3 #/5/1] More\n\"then b\"\n")
        self.write("_build/solutions/r3.md", "### [R3 Q1] Trace\nSolution [R3 #/5/1]: s, a, b\n"
                   "### [R3 #/5/0] Solutions\n\"Q1: s, a\"\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/r3.md:9: CITES AN ANSWERS PAGE: [R3 #/5/0]", out)
        self.assertIn("_build/extract/r3.md:10: AN ANSWERS PAGE IN AN EXTRACT: [R3 #/5/1] is a key "
                      "section of R3", out)

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

    def test_a_sets_home_is_every_extract_holding_any_block_of_it(self):
        # r16-1 #1: a set's home came only from extracts holding its question blocks, so an
        # answers page for a set whose extract holds only page blocks passed in any file.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| in | no | | yes |", "| in | no | - | yes |"))
        self.write("_build/extract/hw1.md", "### [HW1 p.1] Homework 1\n\"Q1a. Find f.\"\n")
        self.remove("_build/solutions/hw1.md")
        page = "### [HW1S p.1] Solutions\n\"Q1a: f = 42\"\n"
        self.write("_build/solutions/hw1s.md", page)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/hw1s.md:1: WRONG SOLUTIONS FILE: [HW1S p.1] belongs in "
                      "_build/solutions/hw1.md, beside the one set it solves", out)
        # Its twin, the page beside the set's page-only extract, passes.
        self.remove("_build/solutions/hw1s.md")
        self.write("_build/solutions/hw1.md", page)
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_solutions_block_with_no_home_fails(self):
        # r16-1 #1: a block whose home can't be computed (its in-scope set has no block in any
        # extract yet) passed in any file.
        self.remove("_build/extract/hw1.md")
        self.remove("_build/solutions/hw1.md")
        self.write("_build/solutions/hw1s.md", "### [HW1S p.1] Solutions\n\"Q1a: f = 42\"\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/hw1s.md:1: NO HOME FILE: [HW1S p.1] has no home: no "
                      "extract holds a block of HW1; extract HW1 first", out)
        # Its twin: HW1 with a block in an extract, the page beside it.
        self.write("_build/extract/hw1.md", CLEAN)
        self.write("_build/solutions/hw1.md", SOLVED + "### [HW1S p.1] Solutions\n\"Q1a: 42\"\n")
        self.remove("_build/solutions/hw1s.md")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        # r17 (Hayden, 2026-11-13): an answers file keyed for a pending or out set fails at
        # MANIFEST (KEY NAMES A SET NOT IN SCOPE), so "extract HW1 first" is never said of it.
        pending = SOL_MANIFEST.replace("| 1 | in | no | | yes | Homework 1 |",
                                       "| 1 | pending: in | no | | no | Homework 1 |")
        self.write("MANIFEST.md", pending)
        self.remove("_build/extract/hw1.md")
        self.remove("_build/solutions/hw1.md")
        self.write("_build/solutions/hw1s.md", "### [HW1S p.1] Solutions\n\"Q1a: f = 42\"\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW1S: KEY NAMES A SET NOT IN SCOPE: HW1 is pending", out)
        self.assertNotIn("NO HOME FILE", out)
        self.write("MANIFEST.md", SOL_MANIFEST + "| HW2 | `sources/hw2.pdf` | 1 | out | no | | no | |\n"
                   "| HW2S | `sources/hw2s.pdf` | 1 | in | yes | for HW2 | yes | |\n")
        self.write("_build/pages/HW2S/p-001.png", "")
        self.write("_build/extract/hw1.md", CLEAN)
        self.write("_build/solutions/hw1.md", SOLVED + "### [HW2S p.1] Solutions\n\"Q1: 7\"\n")
        self.remove("_build/solutions/hw1s.md")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("HW2S: KEY NAMES A SET NOT IN SCOPE: HW2 is out", out)
        self.assertNotIn("NO HOME FILE", out)
        # A stem of an out-of-scope set no key names is a block of an out row, as in an
        # extract: a warning, with no home to name.
        self.write("MANIFEST.md", SOL_MANIFEST + "| HW2 | `sources/hw2.pdf` | 1 | out | no | | no | |\n")
        self.write("_build/solutions/hw1.md", SOLVED + "### [HW2 Q1 stem] Setup\n"
                   "Solution [HW1S p.1]: f = 42 throughout.\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("warning: blocks for HW2, whose MANIFEST.md scope is 'out'", out)
        self.assertNotIn("NO HOME FILE", out)
        # A self-keyed doc's key section with no block of its doc in any extract.
        self.write("MANIFEST.md", SOL_MANIFEST + "| PE3 | `sources/pe3.docx` | n/a | in | yes | "
                                                 "sections: Marking scheme | n/a | |\n")
        self.write("_build/solutions/hw1.md", SOLVED)
        self.write("_build/solutions/pe3.md", "### [PE3 Marking scheme] Key\n\"Q1: s\"\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/pe3.md:1: NO HOME FILE: [PE3 Marking scheme] has no home: "
                      "no extract holds a block of PE3; extract PE3 first", out)

    def test_a_deck_split_over_two_extracts_keeps_its_key_beside_either(self):
        # r16-1 #2: the key slides beside the extract holding the deck's later slides failed
        # WRONG SOLUTIONS FILE and KEY SECTION NOT FOUND, since only r3.md holds a question block.
        deck = ("<div class=\"reveal\"><div class=\"slides\">"
                + "".join(f"<section>S{i}</section>" for i in range(6)) + "</div></div>")
        self.write("sources/r3.html", deck)
        self.write("MANIFEST.md", SOL_MANIFEST + "| R3 | `sources/r3.html` | 6 | in | yes | "
                                                 "sections: #/5 | n/a | recitation |\n")
        self.write("_build/extract/r3.md", "".join(f"### [R3 #/{i}] S{i}\n" for i in range(3))
                   + "### [R3 Q1] Trace\nPages: [R3 #/1]\n\"Trace a BFS.\"\n")
        self.write("_build/extract/r3b.md", "### [R3 #/3] S3\n### [R3 #/4] S4\n")
        self.write("_build/solutions/r3.md", "### [R3 Q1] Trace\nSolution [R3 #/5]: s, a, b\n")
        key = "### [R3 #/5] Solutions\n\"Q1: s, a, b\"\n"
        self.write("_build/solutions/r3b.md", key)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("R3: 6 slides in scope, 6 with a block", out)
        # The must-fail: the key slide in a file beside no extract of R3.
        self.remove("_build/solutions/r3b.md")
        self.write("_build/solutions/keys.md", key)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/keys.md:1: WRONG SOLUTIONS FILE: [R3 #/5] belongs in "
                      "_build/solutions/r3.md, beside its own extract", out)
        self.assertIn("R3: KEY SECTION NOT FOUND: no block [R3 #/5] in its home solutions "
                      "files\n", out)


    def test_a_key_section_with_a_page_reference_is_still_key_material(self):
        # r16-1 #3: answers_cite() read a `sections:` locator carrying a page reference as question
        # material, so `### [PE3 Marking scheme p.2]` passed in an extract.
        key = extract_check.read_key
        rows = {"PE3": {"answers": True, "key": key("sections: Marking scheme")}}
        for loc in ("Marking scheme p.2", "Marking scheme pp. 2-3", "Marking scheme, p.2",
                    "p.2 Marking scheme", "Marking scheme (continued) p.3"):
            self.assertTrue(extract_check.answers_cite("PE3", loc, rows), loc)
        for loc in ("p.2", "pp. 2-3", "Marking scheme 2 p.3", "Rules p.1"):
            self.assertFalse(extract_check.answers_cite("PE3", loc, rows), loc)
        self.write("MANIFEST.md", SOL_MANIFEST + "| PE3 | `sources/pe3.docx` | n/a | in | yes | "
                                                 "sections: Marking scheme | n/a | |\n")
        question = "### [PE3 Q1] Trace\n\"Trace a BFS.\"\n"
        self.write("_build/extract/pe3.md", question
                   + "### [PE3 Marking scheme p.2] Key\n\"Q2: t\"\n")
        self.write("_build/solutions/pe3.md", "### [PE3 Q1] Trace\n"
                   "Solution [PE3 Marking scheme]: s\n### [PE3 Marking scheme] Key\n\"Q1: s\"\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/pe3.md:3: AN ANSWERS PAGE IN AN EXTRACT: [PE3 Marking scheme "
                      "p.2] is a key section of PE3", out)
        # Its twin: the page's block beside the rest of the key, in the solutions file, passes.
        self.write("_build/extract/pe3.md", question)
        self.write("_build/solutions/pe3.md", "### [PE3 Q1] Trace\n"
                   "Solution [PE3 Marking scheme]: s\n### [PE3 Marking scheme] Key\n\"Q1: s\"\n"
                   "### [PE3 Marking scheme p.2] Key\n\"Q2: t\"\n")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_an_answers_page_in_an_extract_is_sent_to_its_home(self):
        # Merge minor: AN ANSWERS PAGE IN AN EXTRACT named the extract's own solutions file, where
        # the block then failed WRONG SOLUTIONS FILE. It names the block's home (block_home()).
        page = "### [HW1S p.1] Solutions\n\"Q1a: 7\"\n"
        self.write("_build/extract/notes.md", page)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/notes.md:1: AN ANSWERS PAGE IN AN EXTRACT: [HW1S p.1] is a "
                      "block of HW1S, a separate answers file (its Key cell is \"for HW1\"); move "
                      "it to _build/solutions/hw1.md, beside the one set it solves\n", out)
        # A multi-set answers file's page goes to its own file.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| for HW1 and HW2 |")
                   + "| HW2 | `sources/hw2.pdf` | 1 | in | no | | yes | |\n")
        self.write("_build/pages/HW2/p-001.png", "")
        self.write("_build/extract/hw2.md", "### [HW2 p.1] Homework 2\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/notes.md:1: AN ANSWERS PAGE IN AN EXTRACT: [HW1S p.1] is a "
                      "block of HW1S, a separate answers file (its Key cell is \"for HW1 and "
                      "HW2\"); move it to _build/solutions/hw1s.md, its own file, since it solves "
                      "several sets\n", out)
        # A key page in its own extract stays beside it; in a second extract of the doc, beside
        # that one.
        self.write("MANIFEST.md", SOL_MANIFEST)
        self.remove("_build/extract/notes.md")
        self.add_pe1()
        self.write("_build/extract/pe1b.md", PE_KEY)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/pe1b.md:1: AN ANSWERS PAGE IN AN EXTRACT: [PE1 p.3] is a key "
                      "page of PE1, as its MANIFEST.md Key cell names it; move it to "
                      "_build/solutions/pe1b.md, beside its own extract\n", out)
        # With no home (its set has no block in any extract), the extract's own file is named.
        self.remove("_build/extract/pe1b.md")
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| 1 | in | no | | yes | Homework 1 |",
                                                       "| 1 | pending: in | no | | no | |"))
        self.remove("_build/extract/hw1.md")
        self.remove("_build/solutions/hw1.md")
        self.write("_build/extract/notes.md", page)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/notes.md:1: AN ANSWERS PAGE IN AN EXTRACT: [HW1S p.1] is a "
                      "block of HW1S, a separate answers file (its Key cell is \"for HW1\"); move "
                      "it to _build/solutions/notes.md\n", out)

    def test_a_key_sections_name_with_a_page_reference_matches_its_block(self):
        # r17-1 #4: key_section() dropped the page reference from the locator but not from the
        # Key cell's names, so under `sections: Answers p.4` the exact block [PE3 Answers p.4]
        # was no key section: it passed in an extract and failed KEY SECTION NOT FOUND beside it.
        key = extract_check.read_key
        for cell, loc in (("sections: Answers p.4", "Answers p.4"),
                          ("sections: Answers p.4", "Answers"),
                          ("sections: Answers p.4", "Answers (continued) p.5"),
                          ("sections: Answers", "Answers p.4")):
            with self.subTest(cell=cell, loc=loc):
                rows = {"PE3": {"answers": True, "key": key(cell)}}
                self.assertTrue(extract_check.answers_cite("PE3", loc, rows))
        rows = {"PE3": {"answers": True, "key": key("sections: Answers p.4")}}
        for loc in ("Answer p.4", "Answers 2 p.4", "Rules p.4", "p.4"):
            self.assertFalse(extract_check.answers_cite("PE3", loc, rows), loc)
        self.write("MANIFEST.md", SOL_MANIFEST + "| PE3 | `sources/pe3.docx` | n/a | in | yes | "
                                                 "sections: Answers p.4 | n/a | |\n")
        question = "### [PE3 Q1] Trace\n\"Trace a BFS.\"\n"
        block = "### [PE3 Answers p.4] Key\n\"Q1: s\"\n"
        self.write("_build/extract/pe3.md", question + block)
        self.write("_build/solutions/pe3.md", "### [PE3 Q1] Trace\nSolution [PE3 Answers]: s\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/pe3.md:3: AN ANSWERS PAGE IN AN EXTRACT: [PE3 Answers p.4] "
                      "is a key section of PE3", out)
        # Its twin: the block beside its extract is the key section the Key cell names.
        self.write("_build/extract/pe3.md", question)
        self.write("_build/solutions/pe3.md", "### [PE3 Q1] Trace\nSolution [PE3 Answers]: s\n"
                   + block)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("KEY SECTION NOT FOUND", out)

    def test_a_key_naming_a_set_not_in_scope_fails(self):
        # r17 (Hayden, 2026-11-13): an in-scope answers file keyed for a set that is pending,
        # reserved or out passed, its official text then having no home but "extract HW1 first".
        self.remove("_build/extract/hw1.md")
        self.remove("_build/solutions/hw1.md")
        self.write("_build/solutions/hw1s.md", "### [HW1S p.1] Solutions\n\"Q1a: f = 42\"\n")
        for scope, kind in (("pending: in", "pending"), ("reserved: Final", "reserved"),
                            ("out", "out")):
            with self.subTest(kind):
                self.write("MANIFEST.md", SOL_MANIFEST.replace(
                    "| 1 | in | no | | yes | Homework 1 |", f"| 1 | {scope} | no | | no | |"))
                code, out = self.check()
                self.assertEqual(code, 1, out)
                # r18-2 #4: the Key names HW1 alone, so "drop it from the Key cell" would leave
                # it empty (NO KEY): the fix is the Scope alone.
                self.assertIn(f"HW1S: KEY NAMES A SET NOT IN SCOPE: HW1 is {kind}: give HW1S the "
                              "same Scope\n", out)
                self.assertNotIn("drop it", out)
        # One set of several out of scope fails alone.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| for HW1 and HW2 |")
                   .replace("| 1 | in | no | | yes | Homework 1 |", "| 1 | out | no | | no | |")
                   + "| HW2 | `sources/hw2.pdf` | 1 | in | no | | yes | |\n")
        out = self.check()[1]
        # Its twin: the Key names another set, so dropping HW1 leaves a Key: both fixes.
        self.assertIn("HW1S: KEY NAMES A SET NOT IN SCOPE: HW1 is out: drop it from the Key cell "
                      "and cut its pages from HW1S's Scope, or give HW1S the same Scope\n", out)
        self.assertNotIn("HW2 is", out)
        # Its twins: the answers row out of scope too solves nothing, so it isn't checked; both
        # in scope pass.
        for scope in ("pending: in", "out"):
            with self.subTest(answers=scope):
                self.write("MANIFEST.md", SOL_MANIFEST.replace(
                    "| 1 | in | no | | yes | Homework 1 |", f"| 1 | {scope} | no | | no | |")
                    .replace("| 1 | in | yes | for HW1 |", f"| 1 | {scope} | yes | for HW1 |"))
                self.assertNotIn("KEY NAMES A SET NOT IN SCOPE", self.check()[1])
        self.write("MANIFEST.md", SOL_MANIFEST)
        self.write("_build/extract/hw1.md", CLEAN)
        self.write("_build/solutions/hw1.md", SOLVED)
        self.remove("_build/solutions/hw1s.md")
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_a_question_block_labelled_with_the_answers_files_id_fails(self):
        # r17-1 #3: [HW1S Q1 stem] in a solutions file failed NO HOME FILE "extract HW1S first",
        # and in an extract AN ANSWERS PAGE IN AN EXTRACT sent it into the same loop. One message
        # now says to label it with the set's id, wherever it sits.
        stem = "### [HW1S Q1 stem] Setup\nSolution [HW1S p.1]: f = 42 throughout.\n"
        part = "### [HW1S Q1a] Max flow\nSolution [HW1S p.1]: 42\n"
        for loc, text in (("Q1 stem", stem), ("Q1a", part)):
            fix = (f"ANSWERS FILE ID ON A QUESTION: [HW1S {loc}] names the answers file HW1S; "
                   f"label it with the set it solves ([HW1 {loc}])\n")
            with self.subTest(loc, where="solutions"):
                self.write("_build/solutions/hw1.md", SOLVED + text)
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn(f"_build/solutions/hw1.md:6: {fix}", out)
                for other in ("NO HOME FILE", "NO SUCH PART", "WRONG SOLUTIONS FILE"):
                    self.assertNotIn(other, out)
            with self.subTest(loc, where="extract"):
                self.write("_build/solutions/hw1.md", SOLVED)
                self.write("_build/extract/notes.md", text)
                code, out = self.check()
                self.assertEqual(code, 1, out)
                self.assertIn(f"_build/extract/notes.md:1: {fix}", out)
                self.assertNotIn("AN ANSWERS PAGE IN AN EXTRACT", out)
                self.remove("_build/extract/notes.md")
        # An answers file solving several sets can't say which: the label holds a placeholder.
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| for HW1 |", "| for HW1 and HW2 |")
                   + "| HW2 | `sources/hw2.pdf` | 1 | in | no | | yes | |\n")
        self.write("_build/pages/HW2/p-001.png", "")
        self.write("_build/extract/hw2.md", "### [HW2 p.1] Homework 2\n")
        self.write("_build/solutions/hw1.md", SOLVED + stem)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/solutions/hw1.md:6: ANSWERS FILE ID ON A QUESTION: [HW1S Q1 stem] "
                      "names the answers file HW1S; label it with the set it solves "
                      "([<set> Q1 stem])\n", out)
        # Its twin: the stem labelled with the set's id, beside the set's extract, passes.
        self.write("MANIFEST.md", SOL_MANIFEST)
        self.remove("_build/extract/hw2.md")
        self.write("_build/extract/hw1.md", CLEAN.replace(
            "### [HW1 Q1a]", "### [HW1 Q1 stem] Setup\nPages: [HW1 p.1]\n### [HW1 Q1a]"))
        self.write("_build/solutions/hw1.md", SOLVED + stem.replace("HW1S Q1", "HW1 Q1"))
        code, out = self.check()
        self.assertEqual(code, 0, out)


class LeakFiles(unittest.TestCase):
    """`--leak-files` (r17, Hayden 2026-11-13): the questions check's file list, from the same
    homes the solutions check computes, so the workflows run one command instead of naming files
    by hand. An unattempted set's extracts and home solutions files, and a multi-set answers
    file's own file while any set it names is unattempted, are `questions`; every other extract
    is `allow`."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.write("MANIFEST.md", SOL_MANIFEST
                   + "| D1 | `sources/d1.pdf` | 2 | in | no | | yes | lecture |\n")
        self.write("_build/extract/hw1.md", CLEAN)
        self.write("_build/solutions/hw1.md", SOLVED)
        self.write("_build/extract/d1.md", "### [D1 p.1] Flows\n### [D1 p.2] Cuts\n")

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def leak(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = extract_check.main(["--root", self.root, "--leak-files"])
        return code, out.getvalue()

    def manifest(self, extra="", hw1="no", key="for HW1"):
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| 1 | in | no |", f"| 1 | in | {hw1} |")
                   .replace("| for HW1 |", f"| {key} |")
                   + "| D1 | `sources/d1.pdf` | 2 | in | no | | yes | lecture |\n" + extra)

    def test_an_unattempted_sets_files_are_questions_and_every_other_extract_is_allowed(self):
        self.assertEqual(self.leak(), (0, "allow _build/extract/d1.md\n"
                                          "questions _build/extract/hw1.md\n"
                                          "questions _build/solutions/hw1.md\n"))
        # A stray block of the set in a lecture's extract makes that extract and its solutions
        # file questions too (the r17 repro: [HW1 p.1] in l3.md made solutions/l3.md a home).
        self.write("_build/extract/l3.md", "### [D1 p.2] Cuts\n### [HW1 p.1] Homework 1\n")
        self.write("_build/solutions/l3.md", "### [HW1S p.1] Solutions\n\"Q1a: 42\"\n")
        self.assertEqual(self.leak(), (0, "allow _build/extract/d1.md\n"
                                          "questions _build/extract/hw1.md\n"
                                          "questions _build/extract/l3.md\n"
                                          "questions _build/solutions/hw1.md\n"
                                          "questions _build/solutions/l3.md\n"))

    def test_an_attempted_set_is_left_out_and_none_unattempted_prints_nothing(self):
        for mark in ("no, attempted 2026-11-01", "No, Attempted 2026-11-01"):
            with self.subTest(mark):
                self.manifest(hw1=mark)
                self.assertEqual(self.leak(), (0, ""))
        # Fail closed: a mark in any other form isn't one, and an `Unverified:` line exempts
        # nothing.
        for mark in ("no (attempted soon)", "not attempted"):
            with self.subTest(mark):
                self.manifest(hw1=mark)
                self.assertIn("questions _build/extract/hw1.md", self.leak()[1])
        self.manifest()
        self.write("STATUS.md", "Unverified: HW1, Q1, 2026-11-10\n")
        self.assertIn("questions _build/solutions/hw1.md", self.leak()[1])

    def test_an_attempted_sets_solutions_file_is_not_listed(self):
        self.manifest(hw1="no, attempted 2026-11-01",
                      extra="| HW2 | `sources/hw2.pdf` | 1 | in | no | | yes | |\n")
        self.write("_build/extract/hw2.md", "### [HW2 Q1a] Flow\nPages: [HW2 p.1]\n")
        self.write("_build/solutions/hw2.md", "### [HW2 Q1a] Flow\nNo official solution.\n")
        self.assertEqual(self.leak(), (0, "allow _build/extract/d1.md\n"
                                          "allow _build/extract/hw1.md\n"
                                          "questions _build/extract/hw2.md\n"
                                          "questions _build/solutions/hw2.md\n"))
        # A file serving both sets is listed (fail closed).
        self.write("_build/extract/hw1.md", CLEAN + "### [HW2 p.1] Homework 2\n")
        self.assertIn("questions _build/solutions/hw1.md", self.leak()[1])

    def test_a_multi_set_answers_file_is_listed_while_any_set_it_solves_is_unattempted(self):
        hw2 = "| HW2 | `sources/hw2.pdf` | 1 | in | {} | | yes | |\n"
        self.write("_build/extract/hw2.md", "### [HW2 Q1a] Flow\nPages: [HW2 p.1]\n")
        self.write("_build/solutions/hw1s.md", "### [HW1S p.1] Solutions\n\"Q1a (HW2): 7\"\n")
        self.manifest(hw1="no, attempted 2026-11-01", key="for HW1 and HW2",
                      extra=hw2.format("no"))
        out = self.leak()[1]
        self.assertIn("questions _build/solutions/hw1s.md\n", out)
        self.assertIn("allow _build/extract/hw1.md\n", out)
        self.manifest(hw1="no, attempted 2026-11-01", key="for HW1 and HW2",
                      extra=hw2.format("no, attempted 2026-11-02"))
        self.assertEqual(self.leak(), (0, ""))

    def test_a_self_keyed_doc_and_a_question_block_make_a_set(self):
        self.manifest(extra="| PE1 | `sources/pe1.pdf` | 3 | in | yes | p.3 | yes | |\n"
                            "| R2 | `sources/r2.pdf` | 1 | in | no | | yes | recitation |\n")
        self.write("_build/extract/pe1.md", PE)
        self.write("_build/extract/r2.md", "### [R2 Q1] Trace\nPages: [R2 p.1]\n")
        self.write("_build/solutions/hw1.md", SOLVED)
        out = self.leak()[1]
        self.assertIn("questions _build/extract/pe1.md\n", out)
        self.assertIn("questions _build/extract/r2.md\n", out)
        self.manifest(hw1="no, attempted 2026-11-01",
                      extra="| PE1 | `sources/pe1.pdf` | 3 | in | yes, attempted 2026-11-01 | p.3 "
                            "| yes | |\n| R2 | `sources/r2.pdf` | 1 | in | no, attempted "
                            "2026-11-01 | | yes | |\n")
        self.assertEqual(self.leak(), (0, ""))

    def test_a_section_name_starting_with_q_is_no_question(self):
        # r18-1 #1: `Q[\w.]+` read `[CODE Queue.java]` as a question block, so the lecture became
        # an unattempted set and its extract moved from `allow` to `questions`. A question's
        # locator is `Q` and a number.
        for loc in ("Q1", "Q1a", "Q3 stem", "Q1.2", "Q12b"):
            with self.subTest(loc):
                m = extract_check.HEADER.match(f"### [HW1 {loc}] t")
                self.assertEqual((m.group("q"), m.group("other")), (loc, None))
                self.assertEqual(bool(extract_check.PART.fullmatch(loc)), "stem" not in loc)
        for loc in ("Queue.java", "Queues", "Quiz", "Q", "Qa"):
            with self.subTest(loc):
                m = extract_check.HEADER.match(f"### [CODE {loc}] t")
                self.assertEqual((m.group("q"), m.group("other")), (None, loc))
        self.manifest(extra="| CODE | `sources/code/Queue.java` | - | in | no | | n/a | lecture "
                            "code |\n| DS | `sources/ds.docx` | - | in | no | | n/a | |\n"
                            "| L2 | `sources/l2.docx` | - | in | no | | n/a | |\n")
        self.write("_build/extract/code.md", "### [CODE Queue.java] Queue\n\"A queue removes "
                                             "items in the same order that they were added to it.\"\n")
        self.write("_build/extract/ds.md", "### [DS Queues] Queues\n\"FIFO.\"\n")
        self.write("_build/extract/l2.md", "### [L2 Quiz] Quiz\n\"Warm-up.\"\n")
        self.assertEqual(self.leak(), (0, "allow _build/extract/code.md\n"
                                          "allow _build/extract/d1.md\n"
                                          "allow _build/extract/ds.md\n"
                                          "questions _build/extract/hw1.md\n"
                                          "allow _build/extract/l2.md\n"
                                          "questions _build/solutions/hw1.md\n"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            extract_check.main(["--root", self.root])
        self.assertIn("CODE: 1 blocks, 0 image only, 0 UNREADABLE\n", out.getvalue())
        # Its twin: a real question block of the same doc makes it a set.
        self.write("_build/extract/code.md", "### [CODE Q1] Queue\n\"Trace it.\"\n")
        self.assertIn("questions _build/extract/code.md\n", self.leak()[1])

    def test_a_manifest_with_no_rows_it_reads_exits_2(self):
        # r18-1 #3: a header the reader doesn't know gave no rows, so `--leak-files` printed
        # nothing and exited 0 while the main check failed "no rows".
        reason = "extract_check: MANIFEST.md has no rows under a `| Doc id | File | ... |` header\n"
        self.write("MANIFEST.md", SOL_MANIFEST.replace("| Doc id |", "| Id |"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.leak(), (2, ""))
        self.assertEqual(err.getvalue(), reason)
        self.assertEqual(self.leak_check(), (1, reason))
        # Its twin: the header it knows lists the files.
        self.manifest()
        self.assertEqual(self.leak()[0], 0)
        self.assertIn("questions _build/extract/hw1.md\n", self.leak()[1])

    def leak_check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = extract_check.main(["--root", self.root])
        return code, out.getvalue()

    def test_an_unattempted_set_with_no_extract_lists_its_rendered_text(self):
        # r18-1 #2, r18-2 #1: a source added unverified (11-next-exam) has a row and its renders,
        # no extract; a self-keyed one is an unattempted set, which was left out of the list.
        pe4 = "| PE4 | `sources/pe4.pdf` | 4 | in | yes | pp. 3-4 | yes | |\n"
        self.manifest(extra=pe4)
        self.write("STATUS.md", "Unverified: PE4, S9, 2026-11-12\n")
        self.write("_build/text/PE4/p-003.txt", "Question 1.\n")
        self.assertEqual(self.leak(), (0, "allow _build/extract/d1.md\n"
                                          "questions _build/extract/hw1.md\n"
                                          "questions _build/solutions/hw1.md\n"
                                          "questions _build/text/PE4/\n"))
        # A Word file's rendered text, when the directory holds none.
        os.remove(os.path.join(self.root, "_build/text/PE4/p-003.txt"))
        self.manifest(extra=pe4.replace("pe4.pdf` | 4 | in | yes | pp. 3-4", "pe4.docx` | - | in | "
                                                                             "yes | inline"))
        self.write("_build/text/pe4.md", "Question 1.\n")
        self.assertIn("questions _build/text/pe4.md\n", self.leak()[1])
        # Neither: it exits 2 naming the set, whatever other set is listed.
        os.remove(os.path.join(self.root, "_build/text/pe4.md"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.leak(), (2, ""))
        self.assertEqual(err.getvalue(), "extract_check: no file holds PE4, an unattempted set: no "
                                         "extract holds a block of it and _build/text/ holds no "
                                         "rendered text of it; render it (01-ingest) or extract "
                                         "it, then rerun\n")
        # Its twin: once extracted, its extract is listed and its text isn't.
        self.write("_build/extract/pe4.md", "### [PE4 Q1] Trace\nPages: [PE4 p.1]\n")
        self.assertEqual(self.leak(), (0, "allow _build/extract/d1.md\n"
                                          "questions _build/extract/hw1.md\n"
                                          "questions _build/extract/pe4.md\n"
                                          "questions _build/solutions/hw1.md\n"))

    def test_no_manifest_exits_2(self):
        os.remove(os.path.join(self.root, "MANIFEST.md"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.leak(), (2, ""))
        self.assertIn("no MANIFEST.md", err.getvalue())

if __name__ == "__main__":
    unittest.main()
