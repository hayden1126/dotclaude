"""skills/exam-prep/scripts/extract_check.py: extracts against MANIFEST's scope, on a synthetic hub.

The hub has every kind of row: PDFs (one scoped by a page range), a reveal deck, a homework with
its official solutions, a Word file, the Ed digest, and reserved, pending and out rows. Pinned: a
dropped page or slide fails; scope wider than the renders fails and narrower passes; build-frame
runs cover every page in the run; a question block's cites cover only its own doc and answer
docs; a doc with no blocks fails, unless a STATUS `Unverified:` line names it; a reserved doc's
blocks fail; the brief's closing Coverage line adds no UNREADABLE flag."""
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
             "**Shape:** compute\nSolution [HW1S p.1-2]: 42\n",
    "W1.md": "### [W1 Overview] the document's first section\n",
}
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

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def extract(self, name, text):
        self.write(f"_build/extract/{name}", text)

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

    def test_the_coverage_line_counts_no_flag(self):
        self.extract("D1.md", FULL["D1.md"]
                     + "Coverage: pages 1-7; 7 blocks; 1 (image only: p.1); UNREADABLE: none.\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("D1: 7 pages in scope, 7 rendered, 7 with a block, 0 image only, "
                      "0 UNREADABLE", out)

    def test_an_arrived_pending_file_must_get_a_scope(self):
        self.extract("D10.md", "### [D10 p.1] arrived\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("D10: PENDING, yet the extracts hold 1 blocks for it", out)

    def test_answers_pair_with_their_own_set(self):
        manifest = MANIFEST.replace("| X1 |", "| HW2 | `sources/homework/hw2.pdf` | 1 | in | no | yes | |\n| X1 |")
        self.write("MANIFEST.md", manifest)
        self.write("_build/pages/HW2/p-001.png", "")
        self.extract("hw.md", "### [HW1 Q1] One\nPages: [HW1 pp.1-2]\nSolution [HW1S p.1]: 4\n"
                              "### [HW2 Q1] Two\nPages: [HW2 p.1]\nAs in [HW1S p.2].\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("HW1: 2 pages in scope, 2 rendered, 2 with a block", out)
        self.assertIn("HW1S: 2 pages in scope, 2 rendered, 1 with a block, 0 image only, "
                      "0 UNREADABLE; MISSING 2", out)

    def test_a_solutions_file_without_pages_is_covered_by_its_cites(self):
        self.write("MANIFEST.md", MANIFEST.replace("`sources/homework/hw1s.pdf` | 2 |",
                                                   "`sources/homework/hw1s.docx` | n/a |"))
        self.extract("hw.md", "### [HW1 Q1] One\nPages: [HW1 p.1-2]\nSolution [HW1S Q1]: 4\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("HW1S: 1 blocks", out)

    def test_columns_are_found_by_name(self):
        self.write("MANIFEST.md", "| Doc id | Scope | File | Pages |\n|---|---|---|---|\n"
                                  "| D1 | in | `sources/lectures/d1.pdf` | 7 |\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("D1: 7 pages in scope, 7 rendered, 7 with a block", out)

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
                self.assertNotIn("warning: HW1S", out)
        self.write("MANIFEST.md", MANIFEST.replace("official solutions to HW1", "the key"))
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("warning: HW1S holds answers but no `solutions to <doc>` note", out)

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


if __name__ == "__main__":
    unittest.main()
