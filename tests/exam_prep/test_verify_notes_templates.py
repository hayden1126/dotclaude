"""skills/exam-prep/templates/compare-notes.py and fidelity.py: the notes checkers a hub copies
into _build/verify/.

Each runs in a temp hub copied from fixtures/verify-notes (two notes files, their fragments and an
examples.out.md, all matching), as the workflows run it: `python3 -I` from the hub root. Pinned:
each self-test passes on the hub; a clean hub passes; each error the brief names, planted into
the hub's own files, fails the real run with a line naming where and what (a dropped `.rv`, and
a `.rv` on a Not-on banner, among them); braces in math or mid-heading, `x^{.5}`, are read as
text, not as an attribute block; and each self-test
fails when its comparison is made a no-op (NOT CAUGHT) or its plant changes nothing (PLANT DID
NOTHING)."""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TEMPLATES = os.path.join(REPO, "skills", "exam-prep", "templates")
FIXTURE = os.path.join(HERE, "fixtures", "verify-notes")
FILLED = ("FILLED = {}", 'FILLED = {"value-codes": "notes/01-counting.md"}')
NOOP_COMPARE = ("def compare(notes, out_text, filled):\n",
                "def compare(notes, out_text, filled):\n    return []\n")
NOOP_SPLICE = ("def splice(text, line, start, end, new):\n",
               "def splice(text, line, start, end, new):\n    return text\n")
NOOP_PAIR = ("def compare_pair(md, html, name):\n",
             "def compare_pair(md, html, name):\n    return []\n")
NOOP_FRAG_SPLICE = ("def splice(text, start, end, new):\n",
                    "def splice(text, start, end, new):\n    return text\n")


class Hub(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.hub = os.path.join(tmp.name, "hub")
        shutil.copytree(FIXTURE, self.hub)

    def install(self, template, name, *edits):
        with open(os.path.join(TEMPLATES, template), encoding="utf-8") as f:
            text = f.read()
        for old, new in edits:
            self.assertEqual(text.count(old), 1, old)
            text = text.replace(old, new)
        with open(os.path.join(self.hub, "_build", "verify", name), "w", encoding="utf-8") as f:
            f.write(text)

    def edit(self, rel, old, new):
        path = os.path.join(self.hub, rel)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text.count(old), 1, old)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new))

    def run_script(self, name, *args):
        return subprocess.run(["python3", "-I", os.path.join("_build", "verify", name), *args],
                              cwd=self.hub, capture_output=True, text=True)


class CompareNotes(Hub):
    def compare(self, *args):
        self.install("compare-notes.py", "compare_notes.py", FILLED)
        return self.run_script("compare_notes.py", *args)

    def test_the_self_test_passes_and_plants_into_the_hub(self):
        r = self.compare("--self-test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS  the clean sample matches its checker output", r.stdout)
        self.assertIn("PASS  hub: a changed number at notes/01-counting.md:20 3 to 4: caught",
                      r.stdout)
        # The reorder lands in the visit order, the miss a hand-written comparison once had.
        self.assertIn("PASS  hub: a reordered sequence at notes/02-paths.md:29 S, A to A, S: "
                      "caught", r.stdout)
        self.assertTrue(r.stdout.rstrip().endswith("SELF-TEST OK"), r.stdout)

    def test_a_clean_hub_matches(self):
        r = self.compare()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), "NOTES MATCH: 2 worked examples, 1 values")

    def test_a_wrong_distance_fails_and_names_where(self):
        self.edit("notes/02-paths.md", "`G`; distance 2.", "`G`; distance 3.")
        r = self.compare()
        self.assertEqual(r.returncode, 1)
        self.assertIn("notes/02-paths.md:29 §2.1 ex-2-bfs: the notes print 3 where the checker "
                      "has 2", r.stdout)

    def test_a_reordered_visit_order_fails(self):
        self.edit("notes/02-paths.md", "visit order `S`, `A`, `B`, `G`",
                  "visit order `S`, `B`, `A`, `G`")
        r = self.compare()
        self.assertEqual(r.returncode, 1)
        lines = r.stdout.splitlines()
        self.assertTrue(lines[:-1], r.stdout)
        self.assertTrue(all(l.startswith("notes/02-paths.md:29 §2.1 ex-2-bfs: ")
                            for l in lines[:-1]), r.stdout)

    def test_an_omitted_value_and_a_wrong_conclusion_fail(self):
        self.edit("notes/02-paths.md", "`G`; distance 2.", "`G`.")
        self.edit("notes/01-counting.md", "> Step 1: 5 terms.", "> Step 1: the terms.")
        self.edit("notes/02-paths.md", "at distance 2, the", "at distance 5, the")
        r = self.compare()
        self.assertEqual(r.returncode, 1)
        self.assertIn("ex-2-bfs: the notes omit 2, which the checker prints", r.stdout)
        # An omission is placed at the next value the notes print.
        self.assertIn("notes/01-counting.md:22 §1.1 ex-1-range: the notes omit 5", r.stdout)
        self.assertIn("notes/02-paths.md:30 §2.1 ex-2-bfs: the Conclusion prints 5, which the "
                      "checker's section doesn't", r.stdout)

    def test_names_count_in_backticks_only(self):
        # A bare capital is prose; the trace's names are code (CONVERT.md).
        self.edit("notes/02-paths.md", "> Step 4: expand `G`, the goal.",
                  "> Step 4: expand `G`, the goal. A run stops here.")
        self.assertEqual(self.compare().returncode, 0)
        self.edit("notes/02-paths.md", "visit order `S`, `A`, `B`, `G`",
                  "visit order S, A, B, G")
        r = self.compare()
        self.assertEqual(r.returncode, 1)
        self.assertIn("the notes omit S, A, B, G, which the checker prints", r.stdout)

    def test_values_todo_and_coverage(self):
        self.install("compare-notes.py", "compare_notes.py")
        r = self.run_script("compare_notes.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("examples.out.md value-codes: NOT IN FILLED", r.stdout)
        self.edit("notes/01-counting.md", "17576", "17575")
        self.edit("notes/01-counting.md", "To sum a range:", "To sum a range: TODO-VERIFY: n")
        self.edit("notes/01-counting.md", "{#ex-1-range}", "{#ex-1-sum}")
        r = self.compare()
        self.assertEqual(r.returncode, 1)
        self.assertIn("notes/01-counting.md value-codes: the file doesn't print 17576, in that "
                      "order", r.stdout)
        self.assertIn("notes/01-counting.md:13: TODO-VERIFY left", r.stdout)
        self.assertIn("notes/01-counting.md:19 §1.1 ex-1-sum: NO CHECKER SECTION", r.stdout)
        self.assertIn("examples.out.md ex-1-range: NOT IN THE NOTES", r.stdout)

    def test_a_noop_comparison_fails_the_self_test(self):
        self.install("compare-notes.py", "compare_notes.py", FILLED, NOOP_COMPARE)
        r = self.run_script("compare_notes.py", "--self-test")
        self.assertEqual(r.returncode, 1)
        self.assertIn("hub: a changed number at notes/01-counting.md:20 3 to 4: NOT CAUGHT",
                      r.stdout)
        self.assertIn("PASS  the clean sample matches", r.stdout)
        self.assertIn("SELF-TEST FAILED: 4 of the checks", r.stdout)

    def test_a_noop_plant_trips_the_guard(self):
        self.install("compare-notes.py", "compare_notes.py", FILLED, NOOP_SPLICE)
        r = self.run_script("compare_notes.py", "--self-test")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL  sample: PLANT DID NOTHING: a changed number", r.stdout)
        self.assertIn("FAIL  hub: PLANT DID NOTHING: a reordered sequence", r.stdout)
        self.assertIn("SELF-TEST FAILED: 4 of the checks", r.stdout)


class Fidelity(Hub):
    def fidelity(self, *args):
        self.install("fidelity.py", "fidelity.py")
        return self.run_script("fidelity.py", *args)

    def test_the_self_test_passes_and_plants_into_every_fragment(self):
        r = self.fidelity("--self-test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS  the clean sample pair passes", r.stdout)
        for frag in ("sample", "sec1.html", "sec2.html"):
            for what in ("a dropped sentence", "a changed number", "two swapped steps",
                         "a dropped citation"):
                self.assertRegex(r.stdout, rf"PASS  {frag}: {what} \(.*\): caught")
        self.assertTrue(r.stdout.rstrip().endswith("SELF-TEST OK"), r.stdout)

    def test_a_clean_hub_passes_with_step_labels_and_list_numbers_dropped(self):
        r = self.fidelity()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), "FIDELITY OK: 2 fragments")
        # A Markdown list number is the renderer's, not content.
        self.edit("notes/02-paths.md", "2. **Ties:**", "7. **Ties:**")
        self.assertEqual(self.fidelity().returncode, 0)

    def test_a_dropped_sentence_fails(self):
        self.edit("_build/frag/sec2.html", "Breadth-first search finds a path with the fewest "
                  "edges. ", "")
        r = self.fidelity()
        self.assertEqual(r.returncode, 1)
        self.assertIn("sec2.html sec-2: text: the fragment drops 'Breadth - first search finds "
                      "a path with the fewest edges'", r.stdout)

    def test_a_changed_number_fails(self):
        self.edit("_build/frag/sec1.html", "<strong>Result:</strong> 25.",
                  "<strong>Result:</strong> 26.")
        r = self.fidelity()
        self.assertEqual(r.returncode, 1)
        self.assertIn("sec1.html sec-1-sums: text: the fragment has '26' where the notes have "
                      "'25'", r.stdout)

    def test_two_swapped_steps_fail(self):
        first = "<li>Put the start on the frontier.</li>"
        second = "<li>Expand the frontier's first node and add its new neighbours.</li>"
        self.edit("_build/frag/sec2.html", first + "\n    " + second, second + "\n    " + first)
        r = self.fidelity()
        self.assertEqual(r.returncode, 1)
        self.assertIn("sec2.html sec-2-bfs: text:", r.stdout)

    def test_a_dropped_citation_fails(self):
        self.edit("_build/frag/sec1.html", ' <a class="slink">D1 p.6</a>', "")
        r = self.fidelity()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.splitlines()[0],
                         "sec1.html sec-1-rules: citations: the fragment drops D1 p.6")

    def test_a_changed_callout_and_a_missing_fragment_fail(self):
        self.edit("_build/frag/sec2.html", 'class="callout warn"', 'class="callout def"')
        r = self.fidelity()
        self.assertEqual(r.returncode, 1)
        self.assertIn("sec2.html sec-2-bfs: callouts: the fragment drops warn Not on Exam 1",
                      r.stdout)
        # A named section is checked alone.
        self.assertEqual(self.fidelity("sec1").stdout.strip(), "FIDELITY OK: 1 fragments")
        os.remove(os.path.join(self.hub, "_build", "frag", "sec2.html"))
        r = self.fidelity()
        self.assertEqual(r.returncode, 1)
        self.assertIn("notes/02-paths.md: no _build/frag/sec2.html", r.stdout)

    def test_the_self_test_plants_a_dropped_rv(self):
        r = self.fidelity("--self-test")
        self.assertRegex(r.stdout, r"PASS  sample: a dropped \.rv \(.*\): caught \(sample sec-1-order: "
                                   r"callouts: ")
        self.assertIn("SKIP  sec1.html: a dropped .rv: no rv class", r.stdout)

    def test_a_dropped_rv_fails(self):
        self.edit("notes/01-counting.md", "{#ex-1-range}", "{#ex-1-range .rv}")
        self.edit("notes/01-counting.md", "> **Pitfall:** Adding", "> **Pitfall:** {.rv} Adding")
        self.edit("_build/frag/sec1.html", 'class="callout example wex" id="ex-1-range"',
                  'class="callout example wex rv" id="ex-1-range"')
        self.edit("_build/frag/sec1.html", '<div class="callout warn">', '<div class="callout warn rv">')
        self.assertEqual(self.fidelity().stdout.strip(), "FIDELITY OK: 2 fragments")
        self.edit("_build/frag/sec1.html", '<div class="callout warn rv">', '<div class="callout warn">')
        r = self.fidelity()
        self.assertEqual(r.returncode, 1)
        self.assertIn("sec1.html sec-1-rules: callouts: the fragment has warn Pitfall where the notes "
                      "have warn Pitfall rv", r.stdout)
        # Its self-test plants the drop in the hub's own fragment too.
        self.edit("_build/frag/sec1.html", '<div class="callout warn">', '<div class="callout warn rv">')
        self.assertRegex(self.fidelity("--self-test").stdout, r"PASS  sec1\.html: a dropped \.rv \(.*\): caught")

    def test_math_braces_are_text_not_an_attribute_block(self):
        # `x^{.5}` or `y_{#k}` in math, and `x^{.rv}` in a heading, are text: only a block at a
        # line's end or right after a callout's label, after a space, is an attribute block.
        self.edit("notes/01-counting.md", "Step 1: Count its terms: \\(b - a + 1\\).",
                  "Step 1: Count its terms: \\(b - a + 1\\), not \\(x^{.5}\\) or \\(y_{#k}\\).")
        self.edit("_build/frag/sec1.html", "<li>Count its terms: \\(b - a + 1\\).</li>",
                  "<li>Count its terms: \\(b - a + 1\\), not \\(x^{.5}\\) or \\(y_{#k}\\).</li>")
        self.edit("notes/01-counting.md", "## 1.1 Sums of a range {#sec-1-sums}",
                  "## 1.1 Sums of a range, x^{.rv} {#sec-1-sums}")
        self.edit("_build/frag/sec1.html", '<h3 id="sec-1-sums">1.1 Sums of a range</h3>',
                  '<h3 id="sec-1-sums">1.1 Sums of a range, x^{.rv}</h3>')
        r = self.fidelity()
        self.assertEqual(r.stdout.strip(), "FIDELITY OK: 2 fragments", r.stdout + r.stderr)
        self.edit("_build/frag/sec1.html", "\\(x^{.5}\\)", "\\(x^{.7}\\)")
        r = self.fidelity()
        self.assertEqual(r.returncode, 1)
        self.assertIn("sec1.html sec-1-sums: text:", r.stdout)

    def test_rv_on_a_not_on_banner_fails(self):
        self.edit("notes/02-paths.md", "> **Not on Exam 1:** bidirectional", "> **Not on Exam 1:** {.rv} bidirectional")
        self.edit("_build/frag/sec2.html", '<div class="callout warn">', '<div class="callout warn rv">')
        r = self.fidelity()
        self.assertEqual(r.returncode, 1)
        self.assertIn("sec2.html sec-2-bfs: the notes put .rv on a line that is no worked example or Pitfall",
                      r.stdout)

    def test_a_noop_rv_plant_trips_the_guard(self):
        self.install("fidelity.py", "fidelity.py",
                     ('        return splice(html, m.start(1), m.end(1), ""), m.group(0)[:40]\n',
                      "        return html, m.group(0)[:40]\n"))
        r = self.run_script("fidelity.py", "--self-test")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL  sample: PLANT DID NOTHING: a dropped .rv", r.stdout)
        self.assertIn("SELF-TEST FAILED: 1 of the checks", r.stdout)

    def test_a_noop_comparison_fails_the_self_test(self):
        self.install("fidelity.py", "fidelity.py", NOOP_PAIR)
        r = self.run_script("fidelity.py", "--self-test")
        self.assertEqual(r.returncode, 1)
        self.assertIn("sample: a dropped sentence ('Search order matters.'): NOT CAUGHT",
                      r.stdout)
        self.assertIn("SELF-TEST FAILED: 13 of the checks", r.stdout)

    def test_a_noop_plant_trips_the_guard(self):
        self.install("fidelity.py", "fidelity.py", NOOP_FRAG_SPLICE)
        r = self.run_script("fidelity.py", "--self-test")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL  sample: PLANT DID NOTHING: a dropped citation", r.stdout)
        self.assertIn("SELF-TEST FAILED: 13 of the checks", r.stdout)


if __name__ == "__main__":
    unittest.main()
