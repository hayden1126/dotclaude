"""skills/exam-prep/scripts/mock_leak.py, the mock page's leak check (FB-154).

The fixture mock's page, built by mockpage.py, passes against its key, naming the five parts whose
answers are too short to check. The same page with a key answer put back fails, wherever it
sits: in a hidden view, an aria-label, a comment or a script, split by phrasing tags (with
attributes too, a link among them), a soft hyphen or a comment, in another case, across a line
break or a no-break space, after a CDATA section's first > outside SVG (terminated or not), in
an SVG title split by markup or CDATA, or split by a child of SVG text, a <font> tag or any format
character; so does the key's title or STOP phrase. Another
mock's key and the values file count too. A value inside a longer word, and a short value, don't
count. A Markdown page (the cram order) is read with its emphasis and code marks dropped, both
ways for underscores, as written and as HTML (a <br>, an entity), its blockquote marks and links
read as text, each copy counted once, a LaTeX page with its markup, colors, escapes and comments
and with commands it doesn't know dropped, and a page with no views names its hits "the page". A
key's answer is searched in each reading of its Markdown and as written (a lone ** kept), and a
true-or-false answer's witness on its own, however the verdict leads into it. The output names
the key, the part and the place (no part once past an article), never an answer. An Answer:
line outside a bare ## Question N block (a titled heading, Variants, before any heading) is
refused, and so is bad usage (a file that isn't UTF-8 among it): exit 2."""
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(REPO, "skills", "exam-prep", "scripts")
FIXTURE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "mock")
KEY = os.path.join(FIXTURE, "mock-exam1-key.md")
LONG = ["S A B C T, dist(T) = 7",
        "With S to A 1, S to B 2 and B to A -3, A is finalized at 1 before the path S B A of weight -1 is seen",
        "False: a triangle plus an isolated vertex", "False: two disjoint triangles"]



def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Leak(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.clean = os.path.join(cls.tmp.name, "mock.html")
        subprocess.run([sys.executable, os.path.join(SCRIPTS, "mockpage.py"),
                        os.path.join(FIXTURE, "mock-exam1.md"), "--out", cls.clean,
                        "--backbone", os.path.join(FIXTURE, "backbone.md")], check=True, capture_output=True)
        with open(cls.clean, encoding="utf-8") as f:
            cls.page = f.read()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_on(self, page=None, key=KEY, args=None):
        path = os.path.join(self.tmp.name, "edited.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.page if page is None else page)
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "mock_leak.py")] + (args or [path, key]),
                           capture_output=True, text=True, timeout=60)
        for value in LONG:
            self.assertNotIn(value.lower(), (r.stdout + r.stderr).lower(), "the output shows an answer")
        return r.returncode, r.stdout, r.stderr

    def edit(self, old, new):
        self.assertIn(old, self.page)
        return self.page.replace(old, new, 1)

    def test_the_clean_page_passes(self):
        rc, out, err = self.run_on()
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out.strip(), "LEAK OK: 4 answers checked; under 8 characters, not checked: "
                                      "mock-exam1-key.md Q1(a), Q1(b), Q3(a), Q4(a), Q4(d)")

    def test_an_answer_anywhere_in_the_page_fails(self):
        type_view = self.page.index('<div id="view-type"')
        q4b = self.page.index('data-part="Q4(b)"', type_view)
        cases = {
            "in a hidden view": (self.page[:q4b] + self.page[q4b:].replace(
                "</header>", "</header><p>False: a triangle plus an isolated vertex</p>", 1),
                "mock-exam1-key.md Q4(b): its answer is in the page (view-type, in Q4(b))"),
            "in an aria-label": (self.edit('aria-label="Answer space"',
                                           'aria-label="False: two disjoint triangles"'),
                                 "mock-exam1-key.md Q4(c): its answer is in the page (view-paper, in Q1(a))"),
            "in a comment": (self.edit("</main>", "<!-- S A B C T, dist(T) = 7 --></main>"),
                             "mock-exam1-key.md Q2(a): its answer is in the page"),
            "in a script": (self.edit("</main>", "<script>var a='false: two disjoint triangles'</script></main>"),
                            "mock-exam1-key.md Q4(c): its answer is in the page"),
            "split by inline tags, in another case": (
                self.edit("</main>", "<p>FALSE: a tri<em>angle</em> plus <span>an\nisolated</span> ver<code>tex</code>.</p></main>"),
                "mock-exam1-key.md Q4(b): its answer is in the page"),
            "across a no-break space": (self.edit("</main>", "<p>S A B C T, dist(T)&nbsp;=&#32;7</p></main>"),
                                        "mock-exam1-key.md Q2(a): its answer is in the page"),
            # Round 7: tags with attributes, a link, a soft hyphen and a comment inside the phrase.
            "split by a span with a class": (
                self.edit("</main>", '<p>False: a triangle plus an <span class="term">isolated vertex</span>.</p></main>'),
                "mock-exam1-key.md Q4(b): its answer is in the page"),
            "split by a link": (self.edit("</main>", '<p>S A B C T, <a class="xref" href="#sec-2">dist(T) = 7</a></p></main>'),
                                "mock-exam1-key.md Q2(a): its answer is in the page"),
            "split mid-word by a link": (
                self.edit("</main>", '<p>False: two disjoint tri<a href="#sec-2">angles</a></p></main>'),
                "mock-exam1-key.md Q4(c): its answer is in the page"),
            "split by a script": (
                self.edit("</main>", "<p>False: a triangle plus an <script>1</script>isolated vertex</p></main>"),
                "mock-exam1-key.md Q4(b): its answer is in the page"),
            "in SVG CDATA, split by a tspan": (
                self.edit("</main>", "<svg><text><![CDATA[False: two dis]]><tspan>joint</tspan> triangles</text></svg></main>"),
                "mock-exam1-key.md Q4(c): its answer is in the page"),
            # Round 9: outside SVG a browser ends `<![CDATA[` at the first >, and inside SVG it
            # parses a <title>'s markup, which html.parser 3.12.3 reads as text.
            "in CDATA outside SVG, past its first >": (
                self.edit("</main>", "<p>S A B<![CDATA[> C T, dist(T) = 7]]></p></main>"),
                "mock-exam1-key.md Q2(a): its answer is in the page"),
            "split by markup in an SVG title": (
                self.edit("</main>", "<svg><title>False: two dis<b></b>joint triangles</title></svg></main>"),
                "mock-exam1-key.md Q4(c): its answer is in the page"),
            # Round 10: an unterminated CDATA outside SVG ends at its >, a CDATA inside an SVG
            # title shows, SVG <text> draws its runs as one line, <font> is phrasing, LRM is invisible.
            "after an unterminated CDATA outside SVG": (
                self.edit("</main>", "<p>x<![CDATA[></p><p>False: two dis<b></b>joint triangles</p></main>"),
                "mock-exam1-key.md Q4(c): its answer is in the page"),
            "split by CDATA in an SVG title": (
                self.edit("</main>", "<svg><title>False: <![CDATA[two dis]]>joint triangles</title></svg></main>"),
                "mock-exam1-key.md Q4(c): its answer is in the page"),
            "split by a child of SVG text": (
                self.edit("</main>", "<svg><text>False: two dis<desc></desc>joint triangles</text></svg></main>"),
                "mock-exam1-key.md Q4(c): its answer is in the page"),
            "split by a font tag and a left-to-right mark": (
                self.edit("</main>", "<p>False: two dis<font>joint</font>&lrm; tri&lrm;angles</p></main>"),
                "mock-exam1-key.md Q4(c): its answer is in the page"),
            "an attribute's text is never printed as the place": (
                self.edit("</main>", '<div data-part="False: two disjoint triangles" id="view-False: two disjoint triangles">x</div></main>'),
                "mock-exam1-key.md Q4(c): its answer is in the page (view-topic, in a part)"),
            "split by a soft hyphen and a comment": (
                self.edit("</main>", "<p>False: two dis&shy;joint <!-- x -->triangles</p></main>"),
                "mock-exam1-key.md Q4(c): its answer is in the page"),
            "the key's title": (self.edit("<h1>GRF101", "<h1>Answer Key GRF101"),
                                'the key\'s phrase "answer key" is in the page (the header)'),
            "the STOP line": (self.edit("</main>", "<p>STOP. Quarantined\nkey.</p></main>"),
                              'the key\'s phrase "quarantined key" is in the page'),
        }
        for name, (page, message) in cases.items():
            with self.subTest(name):
                rc, out, err = self.run_on(page)
                self.assertEqual(rc, 1, out + err)
                self.assertIn(message, err)
                self.assertTrue(out.startswith("LEAK: "), out)

    def test_every_format_character_is_invisible(self):
        # A browser draws none of them, so none splits a phrase (round 10).
        import importlib.util
        import unicodedata
        spec = importlib.util.spec_from_file_location("mock_leak", os.path.join(SCRIPTS, "mock_leak.py"))
        leak = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(leak)
        missed = [f"U+{c:04X}" for c in range(sys.maxunicode + 1)
                  if unicodedata.category(chr(c)) == "Cf" and not leak.INVISIBLE.match(chr(c))]
        self.assertEqual(missed, [])

    def test_every_hit_is_listed(self):
        rc, out, err = self.run_on(self.edit("</main>", "<p>False: two disjoint triangles</p>"
                                                        "<p>False: two disjoint triangles</p></main>"))
        self.assertEqual(rc, 1)
        self.assertEqual(err.count("mock-exam1-key.md Q4(c): its answer is in the page"), 2)
        self.assertIn("LEAK: 2 found", out)

    def test_a_longer_word_and_a_short_value_dont_count(self):
        for name, page in {"a longer word": self.edit("</main>", "<p>False: two disjoint trianglesx</p></main>"),
                           "a short value": self.edit("</main>", "<p>True. 6. 3. 2.</p></main>")}.items():
            with self.subTest(name):
                self.assertEqual(self.run_on(page)[0], 0)

    def test_emphasis_in_the_key_is_dropped(self):
        key = os.path.join(self.tmp.name, "styled-key.md")
        with open(key, "w", encoding="utf-8") as f:
            f.write("# ANSWER KEY: x\n\n## Question 4\n\n**(b)** Answer: **False**: a *triangle* plus "
                    "an isolated `vertex`.\n")
        rc, _, err = self.run_on(self.edit("</main>", "<p>False: a triangle plus an isolated vertex</p></main>"),
                                 key=key)
        self.assertEqual(rc, 1)
        self.assertIn("styled-key.md Q4(b): its answer", err)
        with open(key, "w", encoding="utf-8") as f:
            f.write("# ANSWER KEY: x\n\n## Question 4\n\n**(b)** Answer: _False_: a __triangle__ plus an isolated vertex\n")
        rc, _, err = self.run_on(self.edit("</main>", "<p>False: a triangle plus an isolated vertex</p></main>"),
                                 key=key)
        self.assertEqual(rc, 1)
        self.assertIn("styled-key.md Q4(b): its answer", err)

    def test_each_reading_of_an_answer_is_searched(self):
        # Round 5: a < in a Markdown page's math opened a "tag" that hid the rest; LaTeX markup,
        # emphasis marks inside code, a witness without its verdict and \_ each hid an answer.
        key = self.write("read-key.md", "# ANSWER KEY: x\n\n## Question 1\n\n"
                         "**(a)** Answer: `f(*args, **kwargs)` forwards every argument\n\n"
                         "**(b)** Answer: x\\_1 = 3 and x\\_2 = 5\n\n"
                         "**(c)** Answer: __init__ builds the object\n\n"
                         "**(d)** Answer: False: two disjoint triangles\n\n"
                         "**(e)** Answer: \\(a *b* c\\) is associative\n\n"
                         "**(f)** Answer: True: take K4\n")
        cases = {
            "page.md": ("Order \\(u<v\\) first. False: two disjoint triangles. Then \\(a>b\\).", "Q1(d): its answer"),
            "sheet.tex": ("\\textbf{\\emph{False}}: two disjoint~triangles", "Q1(d): its answer"),
            "code.html": ("<p><code>f(*args, **kwargs)</code> forwards every argument</p>", "Q1(a): its answer"),
            "esc.html": ("<p>x_1 = 3 and x_2 = 5</p>", "Q1(b): its answer"),
            "init.html": ("<p>__init__ builds the object</p>", "Q1(c): its answer"),
            "witness.html": ("<p>Take two disjoint triangles.</p>", "Q1(d): its answer's witness"),
            "math.html": ("<p>\\(a *b* c\\) is associative</p>", "Q1(e): its answer"),
        }
        for name, (text, needle) in cases.items():
            with self.subTest(name):
                rc, _, err = self.run_on(args=[self.write(name, text), key])
                self.assertEqual(rc, 1, err)
                self.assertIn(f"read-key.md {needle} is in the page", err)
        # The other ways a key writes a verdict with its witness, a lone ** kept, Markdown a page
        # shows as written, and LaTeX's escapes (round 6).
        key2 = self.write("read2-key.md", "# ANSWER KEY: x\n\n## Question 1\n\n"
                          "**(a)** Answer: False (two disjoint triangles)\n\n"
                          "**(b)** Answer: False, e.g. a triangle plus an isolated vertex\n\n"
                          "**(c)** Answer: True - every vertex has even degree\n\n"
                          "**(d)** Answer: n**2 comparisons in the worst case\n\n"
                          "**(e)** Answer: **Kruskal** picks AB first\n\n"
                          "**(f)** Answer: 50% of the edges & all vertices\n\n"
                          "**(g)** Answer: `__init__` sets every field\n\n"
                          "**(h)** Answer: every vertex is co\u00adloured\n")
        cases = {
            "paren.html": ("<p>Take two disjoint triangles.</p>", "Q1(a): its answer's witness"),
            "eg.html": ("<p>Take a triangle plus an isolated vertex.</p>", "Q1(b): its answer's witness"),
            "dash.html": ("<p>Here every vertex has even degree.</p>", "Q1(c): its answer's witness"),
            "lone.html": ("<p>n**2 comparisons in the worst case</p>", "Q1(d): its answer"),
            "shown.html": ("<p>**Kruskal** picks AB first</p>", "Q1(e): its answer"),
            "amp.tex": ("50\\% of the edges \\& all vertices", "Q1(f): its answer"),
            "init.md": ("Then __init__ sets every field.", "Q1(g): its answer"),
            "shy.html": ("<p>Every vertex is coloured.</p>", "Q1(h): its answer"),
        }
        for name, (text, needle) in cases.items():
            with self.subTest(name):
                rc, _, err = self.run_on(args=[self.write(name, text), key2])
                self.assertEqual(rc, 1, err)
                self.assertIn(f"read2-key.md {needle} is in the page", err)
        for name, text, needle in (("esc.tex", "x\\_1 = 3 and x\\_2 = 5\\\\", "Q1(b): its answer"),
                                   ("hyph.tex", "False: two dis\\-joint\\,triangles", "Q1(d): its answer"),
                                   ("bf.tex", "{\\bf False}: two disjoint\\\\\ntriangles", "Q1(d): its answer"),
                                   # Round 9: a comment eats its line's end; inline HTML renders.
                                   ("comment.tex", "False: two %a note\n   disjoint triangles", "Q1(d): its answer"),
                                   ("br.md", "| False: two disjoint<br>triangles |", "Q1(d): its answer"),
                                   ("shy.md", "False: two dis&shy;joint triangles", "Q1(d): its answer"),
                                   # Round 10: two comments in a row, a color, a command it doesn't
                                   # know, a blockquote and a link.
                                   ("comments.tex", "False: two %a\n    %b\ndisjoint triangles", "Q1(d): its answer"),
                                   ("color.tex", "False: two \\textcolor{red}{disjoint} triangles", "Q1(d): its answer"),
                                   ("unknown.tex", "False: two \\foo{disjoint} triangles", "Q1(d): its answer"),
                                   ("quote.md", "> **False**: two disjoint\n> triangles", "Q1(d): its answer"),
                                   ("link.md", "False: two [disjoint](https://x.example/d) triangles", "Q1(d): its answer")):
            with self.subTest(name):
                rc, _, err = self.run_on(args=[self.write(name, text), key])
                self.assertEqual(rc, 1, err)
                self.assertIn(f"read-key.md {needle} is in the page", err)
        # Past an SVG text, a block still splits a word (round 10).
        rc, out, err = self.run_on(self.edit("</main>", "<svg><text>x</text></svg><p>False: two dis</p>"
                                                        "<p>joint triangles</p></main>"))
        self.assertEqual(rc, 0, err)
        # A witness under 8 characters would match by chance, as a short answer would.
        rc, out, err = self.run_on(args=[self.write("short.html", "<p>Then take K4.</p>"), key])
        self.assertEqual(rc, 0, err)

    def test_a_markdown_page_and_a_page_with_no_views(self):
        # The cram order is Markdown: emphasis there would split a phrase that tags don't (round 4).
        cram = self.write("cram-order.md", read(os.path.join(FIXTURE, "cram-order.md")))
        rc, out, _ = self.run_on(args=[cram, KEY])
        self.assertEqual(rc, 0, out)
        cram = self.write("cram-order.md", read(os.path.join(FIXTURE, "cram-order.md")).replace(
            "## Tonight", "**False**: two *disjoint* `triangles`, and _False_: a __triangle__ plus an isolated vertex\n\n## Tonight"))
        rc, _, err = self.run_on(args=[cram, KEY])
        self.assertEqual(rc, 1)
        self.assertIn("Q4(c): its answer is in the page (the page)", err)
        self.assertIn("Q4(b): its answer is in the page (the page)", err)
        self.assertEqual(err.count("Q4(c): its answer is in the page"), 1, "one copy, read three ways, counts once")
        rc, _, err = self.run_on("<p>False: two disjoint triangles</p>")
        self.assertIn("Q4(c): its answer is in the page (the page)", err)

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_every_key_counts_and_the_values_file_too(self):
        other = self.write("mock-exam1-2-key.md", "# ANSWER KEY: x\n\n## Question 1\n\n**(a)** Answer: Kruskal picks AB first\n")
        values = self.write("mock-values-key.md", "# Mock key values\n\n## exam1-2\n\n- Q3(b): eleven spanning trees\n")
        page = self.edit("</main>", "<p>Kruskal picks AB first, giving eleven spanning trees.</p></main>")
        rc, out, err = self.run_on(page, args=[os.path.join(self.tmp.name, "edited.html"), KEY, other, values])
        self.assertEqual(rc, 1, out + err)
        self.assertIn("mock-exam1-2-key.md Q1(a): its answer is in the page", err)
        self.assertIn("mock-values-key.md exam1-2 Q3(b): its answer is in the page", err)

    def test_a_values_file_with_no_values_is_fine(self):
        values = self.write("mock-values-key.md", "# KEY VALUES: the mocks' computed answers\n\n> **STOP.**\n\n## proofs\n")
        rc, out, err = self.run_on(args=[os.path.join(self.tmp.name, "edited.html"), KEY, values])
        self.assertEqual(rc, 0, err)
        other = self.write("plain-key.md", "# ANSWER KEY: x\n\n## Question 1\n")
        rc, _, err = self.run_on(args=[os.path.join(self.tmp.name, "edited.html"), KEY, other])
        self.assertEqual(rc, 2)
        self.assertIn("plain-key.md has no **(x)** Answer: lines", err)

    def test_an_answer_outside_a_question_block_is_refused(self):
        for name, text in (("a titled heading", "## Question 1: Degree sums\n\n**(a)** Answer: twelve edges\n"),
                           ("under Variants", "## Question 1\n\n**(a)** Answer: 6\n\n## Variants\n\n**(b)** Answer: x\n"),
                           ("before any heading", "**(a)** Answer: twelve edges\n")):
            with self.subTest(name):
                rc, _, err = self.run_on(key=self.write("bad-key.md", "# ANSWER KEY: x\n\n" + text))
                self.assertEqual(rc, 2)
                self.assertIn("an Answer: line outside a bare ## Question N block", err)

    def test_a_hit_after_a_part_names_no_part(self):
        rc, _, err = self.run_on(self.edit("<p>The directed graph below", "<p>False: two disjoint triangles. The directed graph below"))
        self.assertEqual(rc, 1)
        self.assertIn("Q4(c): its answer is in the page (view-paper)", err)

    def test_an_earlier_key_as_the_page(self):
        # The student reads an earlier mock's key before the later attempts; its own title and
        # STOP line aren't hits with --no-markers (round 8).
        earlier = self.write("mock-exam1-1-key.md", read(KEY) + "\nCounterexample: Kruskal picks AB first.\n")
        later = self.write("mock-exam1-2-key.md", "# ANSWER KEY: x\n\n## Question 1\n\n**(a)** Answer: Kruskal picks AB first\n")
        rc, out, err = self.run_on(args=["--no-markers", earlier, later])
        self.assertEqual(rc, 1, out + err)
        self.assertIn("mock-exam1-2-key.md Q1(a): its answer is in the page", err)
        self.assertNotIn("the key's phrase", err)
        rc, out, err = self.run_on(args=["--no-markers", self.write("plain-key.md", read(KEY)), later])
        self.assertEqual((rc, err), (0, ""), out)
        rc, _, err = self.run_on(args=[earlier, later])
        self.assertIn('the key\'s phrase "answer key" is in the page', err)

    def test_a_file_that_isnt_utf8_is_bad_usage(self):
        latin = os.path.join(self.tmp.name, "latin-key.md")
        with open(latin, "wb") as f:
            f.write("# ANSWER KEY: x\n\n## Question 1\n\n**(a)** Answer: caf\xe9 au lait\n".encode("latin-1"))
        page = os.path.join(self.tmp.name, "latin.html")
        with open(page, "wb") as f:
            f.write("<p>caf\xe9</p>".encode("latin-1"))
        for args, name in (([os.path.join(self.tmp.name, "edited.html"), KEY, latin], "latin-key.md"),
                           ([page, KEY], "latin.html")):
            with self.subTest(name):
                rc, _, err = self.run_on(args=args)
                self.assertEqual(rc, 2, err)
                self.assertIn(f"{name} isn't UTF-8 text", err)

    def test_bad_usage(self):
        empty = os.path.join(self.tmp.name, "empty-key.md")
        with open(empty, "w", encoding="utf-8") as f:
            f.write("# ANSWER KEY: x\n\n## Question 1\n\nThe working, with no Answer: line.\n")
        missing = os.path.join(self.tmp.name, "none.html")
        for name, kwargs, message in (("a key with no answers", {"key": empty}, "has no **(x)** Answer:"),
                                      ("a missing page", {"args": [missing, KEY]}, "none.html"),
                                      ("one argument", {"args": [KEY]}, "usage:")):
            with self.subTest(name):
                rc, _, err = self.run_on(**kwargs)
                self.assertEqual(rc, 2)
                self.assertIn(message, err)


if __name__ == "__main__":
    unittest.main()
