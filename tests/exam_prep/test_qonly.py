"""skills/exam-prep/scripts/qonly.py and extract_check.py's question-only checks (hard rule 4).

A synthetic homework extract holds two question parts, each with its official solution under it,
one solution running on past its marker line into a fenced block, and a page block of the
answers file. Pinned: the copy keeps both questions, their data and their fields verbatim and
holds no solution line or answers-file block; a past exam with its key in the same file keeps
its question pages and drops its key page; a rerun is a no-op and a copy whose extract no longer
holds answers is removed; a code fence that never closes hides no solution marker after it;
fences pair as CommonMark pairs them (a line with an info string or 4+ spaces of indent closes
nothing) and the bracketed `Solution [<doc> <loc>]` marker, in every form the extract brief
writes, cuts even inside a fence, keeping that fence's closing line, while starter code such as
`solution[i + 1] = x` cuts nothing; extract_check.py compares a copy with what qonly.py writes
now and fails a copy with a solution line (naming file and line), a hand-edited one, a missing
copy, a stale one and an extract's unclosed fence (naming file and line), and passes the copy
qonly.py wrote."""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO, "skills", "exam-prep", "scripts")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extract_check = load("extract_check")

MANIFEST = """| Doc id | File | Pages | Scope | Answers | Rendered | Notes |
|---|---|---|---|---|---|---|
| HW1 | `sources/hw1.pdf` | 2 | in | no | yes | Homework 1 |
| HW1S | `sources/hw1s.pdf` | 2 | in | yes | yes | official solutions to HW1 |
"""
PE_ROW = "| PE1 | `sources/pe1.pdf` | 3 | in | yes | yes | practice exam; solutions to PE1 |\n"

Q1 = """### [HW1 Q1a] Shortest path
Pages: [HW1 p.1]
"Find a shortest path from s to t" in the graph with edges s-a 3, a-t 4, s-t 9. (5 points)
\\[ d(v) = \\min_u d(u) + w(u, v) \\]
**Shape:** compute
**Conventions:** ties break alphabetically
"""
Q2 = """### [HW1 Q1b] Prove it
Pages: [HW1 p.2]
"Prove that no shorter path exists." (5 points)
**Shape:** prove
**Conventions:** none
"""
HEAD = """# HW1 Homework 1, pp.1-2 (extract)
Sources: HW1 2, HW1S 2. Every page image was viewed.
### [HW1 p.1] Homework 1
"Show your work."
"""
HW = (HEAD + Q1 + "Solution [HW1S p.1]: the path s, a, t, of length 7.\n```\n# the working\n"
      "s a t\n```\nSeven, since 3 + 4 < 9.\n" + Q2 + "- Solution [HW1S p.2]: by exchange.\n"
      "### [HW1S p.2] Solutions, continued\n(image only: the answer table)\n"
      "Coverage: pp.1-2; 4 blocks; 1 image only; 0 flagged unreadable.\n")
PE = """### [PE1 p.1] Practice exam
"Time: 50 minutes."
### [PE1 Q1] Trace
Pages: [PE1 p.1-2]
"Trace a breadth-first search from s."
**Solution:** s, a, b
### [PE1 p.3] Key
"Q1: s, a, b"
"""


class QOnly(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.write("MANIFEST.md", MANIFEST)
        self.write("_build/extract/hw1.md", HW)
        self.write("_build/extract/d1.md", "### [HW1 p.2] a page\n\"no answer here\"\n")
        for doc in ("HW1", "HW1S"):
            for page in (1, 2):
                self.write(f"_build/pages/{doc}/p-{page:03d}.png", "")

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as f:
            return f.read()

    def qonly(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = load("qonly").main(["--root", self.root])
        self.assertEqual(code, 0, out.getvalue())
        return out.getvalue()

    def check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = extract_check.main(["--root", self.root])
        return code, out.getvalue()

    def test_the_copy_keeps_the_questions_and_drops_every_solution(self):
        self.qonly()
        copy = self.read("_build/q-only/hw1.md")
        first, _, body = copy.partition("\n")
        self.assertTrue(first.startswith("Question-only copy of _build/extract/hw1.md (sha256 "),
                        first)
        self.assertIn(Q1, body)
        self.assertIn(Q2, body)
        self.assertTrue(body.startswith(HEAD), body)
        self.assertTrue(body.endswith("Coverage: pp.1-2; 4 blocks; 1 image only; 0 flagged "
                                      "unreadable.\n"), body)
        for answer in ("Solution", "length 7", "the working", "3 + 4 < 9", "by exchange",
                       "[HW1S p.2]", "answer table"):
            self.assertNotIn(answer, body)
        self.assertFalse(os.path.exists(os.path.join(self.root, "_build", "q-only", "d1.md")))

    def test_a_key_in_the_same_file_keeps_its_question_pages(self):
        self.write("MANIFEST.md", MANIFEST + PE_ROW)
        self.write("_build/extract/pe1.md", PE)
        self.qonly()
        body = self.read("_build/q-only/pe1.md").partition("\n")[2]
        self.assertEqual(body, '### [PE1 p.1] Practice exam\n"Time: 50 minutes."\n'
                               '### [PE1 Q1] Trace\nPages: [PE1 p.1-2]\n'
                               '"Trace a breadth-first search from s."\n')

    def test_a_rerun_changes_nothing_and_a_copy_with_no_answers_left_goes(self):
        self.qonly()
        before = self.read("_build/q-only/hw1.md")
        self.assertIn("hw1.md: unchanged", self.qonly())
        self.assertEqual(self.read("_build/q-only/hw1.md"), before)
        self.write("_build/extract/hw1.md", HEAD + Q1 + Q2)
        self.assertIn("removed _build/q-only/hw1.md", self.qonly())
        self.assertFalse(os.path.exists(os.path.join(self.root, "_build", "q-only", "hw1.md")))

    def test_extract_check_passes_the_copy_qonly_wrote(self):
        self.qonly()
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("HW1S: 2 pages in scope, 2 rendered, 2 with a block", out)

    def test_extract_check_fails_a_missing_copy(self):
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/hw1.md: holds answers, NO QUESTION-ONLY COPY "
                      "_build/q-only/hw1.md", out)
        self.assertNotIn("d1.md", out)

    def test_extract_check_fails_a_stale_copy(self):
        self.qonly()
        self.write("_build/extract/hw1.md", HW.replace("s-t 9", "s-t 8"))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/q-only/hw1.md:1: STALE", out)

    def test_extract_check_fails_a_copy_holding_a_solution_line(self):
        self.qonly()
        copy = self.read("_build/q-only/hw1.md")
        planted = copy.replace("**Conventions:** none\n",
                               "**Conventions:** none\nSolution [HW1S p.2]: by exchange.\n")
        self.write("_build/q-only/hw1.md", planted)
        line = planted.splitlines().index("Solution [HW1S p.2]: by exchange.") + 1
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn(f"_build/q-only/hw1.md:{line}: ANSWER IN A QUESTION-ONLY COPY", out)
        # A copy that isn't qonly.py's (no first line) is read from its first line.
        self.write("_build/q-only/extra.md", "### [HW1 Q9] x\n**Solution:** 3\n")
        code, out = self.check()
        self.assertIn("_build/q-only/extra.md:2: ANSWER IN A QUESTION-ONLY COPY", out)

    def test_a_solution_comment_in_a_fence_is_code_not_a_marker(self):
        # A question's code may hold a `# solution` comment: the marker search skips fenced lines,
        # as the block split does, so the rest of the question stays.
        text = (HEAD + Q2.replace("**Shape:** prove\n",
                                  "```python\ndef f(x):\n    # solution\n    return x\n```\n"
                                  "**Shape:** prove\n")
                + "~~~\nSolution: not a marker either\n~~~\n")
        body, removed, answers_doc = load("qonly").strip(text, {})
        self.assertEqual((body, removed, answers_doc), (text, [], False))
        # Outside the fence the same block's marker still cuts.
        body, removed, _ = load("qonly").strip(text + "**Solution:** by exchange\n", {})
        self.assertEqual(body, text)
        self.assertEqual(len(removed), 1)

    def test_a_fence_that_never_closes_hides_no_solution(self):
        # A forgotten closing fence, or four backticks opened and three closed, used to hide every
        # marker after it: no copy was due and the extract went to answer-blind agents whole.
        qonly = load("qonly")
        for opener, inner in (("```python\n", ""), ("````python\n", "```\n")):
            text = ("### [HW1 Q1] Write f\nWrite f.\n" + opener + "def f(x):\n" + inner
                    + "**Solution:** return 2*x\n")
            due, body = qonly.due(text, {})
            self.assertTrue(due, opener)
            self.assertNotIn("2*x", body)
        # Open at the next block's header: the fence ends there, and that block's marker still cuts.
        text = ("### [HW1 Q1] Write f\n```\ndef f(x):\n### [HW1 Q2] Prove it\nProve it.\n"
                "**Solution:** by induction\n")
        due, body = qonly.due(text, {})
        self.assertTrue(due)
        self.assertNotIn("induction", body)
        self.assertEqual(qonly.fences(text.splitlines(keepends=True)), (set(), [1]))

    def test_the_reviewers_readme_case_cuts(self):
        # A fence opened bare, then a ```python line inside it: CommonMark reads that line as
        # content, so the fence closes on the next bare line and the marker after it is outside.
        # The old pairing closed on the ```python line, put the marker in a fence, cut nothing,
        # and the extract went whole to answer-blind agents.
        qonly = load("qonly")
        f = "```"
        text = "\n".join(["### [HW2 Q3] Fix the README", "The README reads:", f, f + "python",
                          "x = 1", f, "Solution [HW2 Q3]: fix it as:", f, f + "python", "x = 2",
                          f, "Coverage: HW2 Q3"]) + "\n"
        lines = text.splitlines(keepends=True)
        self.assertEqual(qonly.fences(lines), ({2, 3, 4, 5, 7, 8, 9, 10}, []))
        due, body = qonly.due(text, {})
        self.assertTrue(due)
        self.assertEqual(body, "".join(lines[:6] + lines[11:]))

    def test_an_info_string_line_inside_a_fence_closes_nothing(self):
        # A looser marker, so the fence parse alone decides it.
        qonly = load("qonly")
        text = ("### [HW1 Q1] Fix it\n```\n```python\nx = 1\n```\n**Solution:** 42\n"
                "```\ntail\n```\n")
        self.assertEqual(qonly.fences(text.splitlines(keepends=True)), ({1, 2, 3, 4, 6, 7, 8}, []))
        due, body = qonly.due(text, {})
        self.assertTrue(due)
        self.assertNotIn("42", body)

    def test_an_indented_fence_line_in_a_string_closes_nothing(self):
        # Four spaces in is content (an indented code line), not a closer.
        qonly = load("qonly")
        text = ('### [HW1 Q1] Fix it\n```python\ns = """\n    ```\n"""\n```\n'
                "**Solution:** 42\n```\ny\n```\n")
        self.assertEqual(qonly.fences(text.splitlines(keepends=True)),
                         ({1, 2, 3, 4, 5, 7, 8, 9}, []))
        due, body = qonly.due(text, {})
        self.assertTrue(due)
        self.assertNotIn("42", body)
        # Up to three spaces in, a bare run of the mark at least as long closes (CommonMark).
        text = "### [HW1 Q1] x\n````\n   `````  \n**Solution:** 42\n"
        self.assertEqual(qonly.fences(text.splitlines(keepends=True)), ({1, 2}, []))
        self.assertNotIn("42", qonly.due(text, {})[1])

    def test_a_header_inside_a_fence_trusts_no_fence(self):
        # A block header ends an open fence; the fence's own closer then reads as an opener and
        # pairs with the next fence line, which hid the marker between them. An unclosed fence
        # anywhere means no fence exempts anything.
        qonly = load("qonly")
        text = ("### [HW1 Q1] x\n```\n### [HW1 Q2] y\n```\n**Solution:** 42\n```\nz\n```\n"
                "### [HW1 Q3] w\n```\n# solution\n```\n")
        self.assertEqual(qonly.fences(text.splitlines(keepends=True))[1], [1, 7])
        due, body = qonly.due(text, {})
        self.assertTrue(due)
        self.assertNotIn("42", body)
        self.assertNotIn("# solution", body)

    def test_a_bracketed_marker_inside_a_fence_cuts(self):
        qonly = load("qonly")
        for mark in ("Solution [HW1S p.1]: 42", "- Solution [HW1S Q1]: 42",
                     "#### Solution [HW1S sec 2]: 42"):
            text = "### [HW1 Q1] x\nWrite f.\n```\n" + mark + "\n```\nafter\n"
            due, body = qonly.due(text, {})
            self.assertTrue(due, mark)
            # The fence's closing line stays, so the copy's fences pair as the extract's do.
            self.assertEqual(body, "### [HW1 Q1] x\nWrite f.\n```\n```\n", mark)
        # A looser marker in the same fence is code (round 1), and so is a bracket that isn't
        # the format's `[<doc> <locator>]`.
        for mark in ("**Solution:** 42", "# solution", "solutions [i] = 3"):
            text = "### [HW1 Q1] x\n```\n" + mark + "\n```\n"
            self.assertEqual(qonly.due(text, {}), (False, text), mark)

    def test_a_cut_inside_a_fence_keeps_its_closer(self):
        # The cut used to take the fence's closing line with it: the copy then held an unclosed
        # opener, so stripping it again exempted no fence and read a later block's `# solution`
        # comment as an answer, which no rerun of qonly.py could clear.
        qonly = load("qonly")
        f = "```"
        text = "\n".join(["### [HW1 Q1] x", "Write f.", f, "Solution [HW1S Q1]: 42", f,
                          "### [HW1 Q2] y", f + "python", "# solution", f]) + "\n"
        due, body = qonly.due(text, {})
        self.assertTrue(due)
        self.assertEqual(body, "\n".join(["### [HW1 Q1] x", "Write f.", f, f, "### [HW1 Q2] y",
                                          f + "python", "# solution", f]) + "\n")
        self.assertEqual(qonly.fences(body.splitlines(keepends=True))[1], [])
        self.assertEqual(qonly.strip(body, {})[1], [])
        # End to end: the copy qonly.py writes passes the check.
        self.write("_build/extract/d1.md", text)
        self.qonly()
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("ANSWER IN A QUESTION-ONLY COPY", out)

    def test_extract_check_fails_a_copy_qonly_did_not_write(self):
        # The check compares a copy with what qonly.py writes now: a hand edit fails though it
        # holds no answer, and so does a question line gone missing.
        self.qonly()
        copy = self.read("_build/q-only/hw1.md")
        edited = copy.replace('"Show your work."', '"Show your working."')
        self.write("_build/q-only/hw1.md", edited)
        line = edited.splitlines().index('"Show your working."') + 1
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn(f"_build/q-only/hw1.md:{line}: DIFFERS from what qonly.py writes", out)
        self.assertNotIn("STALE", out)
        self.write("_build/q-only/hw1.md", copy.replace("**Conventions:** none\n", ""))
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/q-only/hw1.md:", out)
        self.assertIn("DIFFERS from what qonly.py writes", out)
        self.qonly()
        self.assertEqual(self.check()[0], 0)

    def test_starter_code_indexing_a_solution_array_cuts_nothing(self):
        # `solution[i + 1]` has the bracketed marker's shape up to its `]`, but no colon or line
        # end follows: it used to cut the rest of the block, part (b) with it.
        qonly = load("qonly")
        f = "```"
        text = "\n".join(["### [HW1 Q2] Fill the table", "(a) Complete the code.", f + "python",
                          "for i in range(n):", "    solution[i + 1] = best(i)", f,
                          "(b) Give its running time."]) + "\n"
        self.assertEqual(qonly.due(text, {}), (False, text))

    def test_every_documented_marker_form_cuts_inside_a_fence(self):
        # The extract brief's `Solution [<soldoc> p.N]: ...` and `Solution [<soldoc> <section>]:
        # ...`, with a list, quote or heading mark before it, bold, more than one cite, or alone.
        qonly = load("qonly")
        for mark in ("Solution [HW1S p.1]: 42", "Solution [HW1S sec 2]: 42",
                     "Solution [HW1S p.1-2]: 42", "- Solution [HW1S Q1]: 42",
                     "* Solution [HW1S p.1]: 42", "> Solution [HW1S p.1]: 42",
                     "#### Solution [HW1S sec 2]: 42", "**Solution [HW1S p.1]:** 42",
                     "**Solution [HW1S p.1]**: 42", "**Solution** [HW1S p.1]: 42",
                     "Official solution [HW1S p.1]: 42", "Solution [HW1S p.1] [HW1S p.2]: 42",
                     "Solution [HW1S p.1]:", "Solution [HW1S p.1]", "solutions [HW1S p.1]: 42"):
            text = "### [HW1 Q1] x\nWrite f.\n```\n" + mark + "\nmore\n```\nafter\n"
            due, body = qonly.due(text, {})
            self.assertTrue(due, mark)
            self.assertEqual(body, "### [HW1 Q1] x\nWrite f.\n```\n```\n", mark)
        for line in ("solution[i + 1] = best(i)", "solution [i + 1] = 2", "Solution [a b] + 1"):
            self.assertFalse(qonly.BRACKETED.match(line), line)

    def test_extract_check_fails_an_extract_with_a_fence_that_never_closes(self):
        self.write("_build/extract/d1.md", '### [HW1 p.2] a page\n"no answer here"\n````\ncode\n```\n')
        self.qonly()
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/d1.md:3: UNCLOSED FENCE", out)
        self.assertNotIn("hw1.md:", out)  # its fence closes

    def test_extract_check_pairs_fences_as_qonly_does(self):
        # The reviewer's case in a homework extract (Answers no): its marker now makes a copy due,
        # so extract_check fails the extract until qonly.py writes one, then passes.
        f = "```"
        self.write("_build/extract/d1.md", "\n".join([
            "### [HW1 p.2] Fix the README", "The README reads:", f, f + "python", "x = 1", f,
            "Solution [HW1S p.2]: fix it as:", f, f + "python", "x = 2", f]) + "\n")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("_build/extract/d1.md: holds answers, NO QUESTION-ONLY COPY", out)
        self.assertNotIn("UNCLOSED FENCE", out)
        self.qonly()
        self.assertNotIn("x = 2", self.read("_build/q-only/d1.md"))
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_the_marker(self):
        solution = load("qonly").SOLUTION
        for line in ("Solution [HW1S p.1]: 7", "- Solution [HW1S Q1]: 7", "**Solution:** 7",
                     "**Solution**: 7", "#### Solution", "> Official solution: 7",
                     "  * solutions [X p.2]"):
            self.assertTrue(solution.match(line), line)
        for line in ("### [HW1 Q1a] Solution concepts", "Solutions to recurrences are unique.",
                     "The solution is unique.", "Pages: [HW1 p.1]"):
            self.assertFalse(solution.match(line), line)


if __name__ == "__main__":
    unittest.main()
