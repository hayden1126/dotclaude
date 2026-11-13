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
refused, and so is bad usage (a file that isn't UTF-8 among it): exit 2, on stderr. The result,
each hit and the LEAK or LEAK OK line, goes to stdout."""
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
                self.assertIn(message, out)
                self.assertTrue(out.splitlines()[-1].startswith("LEAK: "), out)

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

    def test_the_result_goes_to_stdout(self):
        # A build reads one stream: each hit and the LEAK line on stdout, nothing on stderr.
        rc, out, err = self.run_on(self.edit("</main>", "<p>False: two disjoint triangles</p></main>"))
        self.assertEqual((rc, err), (1, ""))
        self.assertEqual(out.splitlines()[0][:52], "mock_leak: mock-exam1-key.md Q4(c): its answer is in")
        self.assertTrue(out.splitlines()[-1].startswith("LEAK: 1 found"), out)

    def test_every_hit_is_listed(self):
        rc, out, err = self.run_on(self.edit("</main>", "<p>False: two disjoint triangles</p>"
                                                        "<p>False: two disjoint triangles</p></main>"))
        self.assertEqual(rc, 1)
        self.assertEqual(out.count("mock-exam1-key.md Q4(c): its answer is in the page"), 2)
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
        rc, out, err = self.run_on(self.edit("</main>", "<p>False: a triangle plus an isolated vertex</p></main>"),
                                 key=key)
        self.assertEqual(rc, 1)
        self.assertIn("styled-key.md Q4(b): its answer", out)
        with open(key, "w", encoding="utf-8") as f:
            f.write("# ANSWER KEY: x\n\n## Question 4\n\n**(b)** Answer: _False_: a __triangle__ plus an isolated vertex\n")
        rc, out, err = self.run_on(self.edit("</main>", "<p>False: a triangle plus an isolated vertex</p></main>"),
                                 key=key)
        self.assertEqual(rc, 1)
        self.assertIn("styled-key.md Q4(b): its answer", out)

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
                rc, out, err = self.run_on(args=[self.write(name, text), key])
                self.assertEqual(rc, 1, err)
                self.assertIn(f"read-key.md {needle} is in the page", out)
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
                rc, out, err = self.run_on(args=[self.write(name, text), key2])
                self.assertEqual(rc, 1, err)
                self.assertIn(f"read2-key.md {needle} is in the page", out)
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
                rc, out, err = self.run_on(args=[self.write(name, text), key])
                self.assertEqual(rc, 1, err)
                self.assertIn(f"read-key.md {needle} is in the page", out)
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
        rc, out, err = self.run_on(args=[cram, KEY])
        self.assertEqual(rc, 1)
        self.assertIn("Q4(c): its answer is in the page (the page)", out)
        self.assertIn("Q4(b): its answer is in the page (the page)", out)
        self.assertEqual(out.count("Q4(c): its answer is in the page"), 1, "one copy, read three ways, counts once")
        rc, out, err = self.run_on("<p>False: two disjoint triangles</p>")
        self.assertIn("Q4(c): its answer is in the page (the page)", out)

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
        self.assertIn("mock-exam1-2-key.md Q1(a): its answer is in the page", out)
        self.assertIn("mock-values-key.md exam1-2 Q3(b): its answer is in the page", out)

    def test_a_values_file_with_no_values_is_fine(self):
        values = self.write("mock-values-key.md", "# KEY VALUES: the mocks' computed answers\n\n> **STOP.**\n\n## proofs\n")
        rc, out, err = self.run_on(args=[os.path.join(self.tmp.name, "edited.html"), KEY, values])
        self.assertEqual(rc, 0, err)
        other = self.write("plain-key.md", "# ANSWER KEY: x\n\n## Question 1\n")
        rc, out, err = self.run_on(args=[os.path.join(self.tmp.name, "edited.html"), KEY, other])
        self.assertEqual(rc, 2)
        self.assertIn("plain-key.md has no **(x)** Answer: lines", err)

    def test_an_answer_outside_a_question_block_is_refused(self):
        for name, text in (("a titled heading", "## Question 1: Degree sums\n\n**(a)** Answer: twelve edges\n"),
                           ("under Variants", "## Question 1\n\n**(a)** Answer: 6\n\n## Variants\n\n**(b)** Answer: x\n"),
                           ("before any heading", "**(a)** Answer: twelve edges\n")):
            with self.subTest(name):
                rc, out, err = self.run_on(key=self.write("bad-key.md", "# ANSWER KEY: x\n\n" + text))
                self.assertEqual(rc, 2)
                self.assertIn("an Answer: line outside a bare ## Question N block", err)

    def test_a_hit_after_a_part_names_no_part(self):
        rc, out, err = self.run_on(self.edit("<p>The directed graph below", "<p>False: two disjoint triangles. The directed graph below"))
        self.assertEqual(rc, 1)
        self.assertIn("Q4(c): its answer is in the page (view-paper)", out)

    def test_an_earlier_key_as_the_page(self):
        # The student reads an earlier mock's key before the later attempts; its own title and
        # STOP line aren't hits with --no-markers (round 8).
        earlier = self.write("mock-exam1-1-key.md", read(KEY) + "\nCounterexample: Kruskal picks AB first.\n")
        later = self.write("mock-exam1-2-key.md", "# ANSWER KEY: x\n\n## Question 1\n\n**(a)** Answer: Kruskal picks AB first\n")
        rc, out, err = self.run_on(args=["--no-markers", earlier, later])
        self.assertEqual(rc, 1, out + err)
        self.assertIn("mock-exam1-2-key.md Q1(a): its answer is in the page", out)
        self.assertNotIn("the key's phrase", out)
        rc, out, err = self.run_on(args=["--no-markers", self.write("plain-key.md", read(KEY)), later])
        self.assertEqual((rc, err), (0, ""), out)
        rc, out, err = self.run_on(args=[earlier, later])
        self.assertIn('the key\'s phrase "answer key" is in the page', out)

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
                rc, out, err = self.run_on(args=args)
                self.assertEqual(rc, 2, err)
                self.assertIn(f"{name} isn't UTF-8 text", err)
                self.assertEqual(out, "")

    def test_bad_usage(self):
        empty = os.path.join(self.tmp.name, "empty-key.md")
        with open(empty, "w", encoding="utf-8") as f:
            f.write("# ANSWER KEY: x\n\n## Question 1\n\nThe working, with no Answer: line.\n")
        missing = os.path.join(self.tmp.name, "none.html")
        for name, kwargs, message in (("a key with no answers", {"key": empty}, "has no **(x)** Answer:"),
                                      ("a missing page", {"args": [missing, KEY]}, "none.html"),
                                      ("one argument", {"args": [KEY]}, "usage:")):
            with self.subTest(name):
                rc, out, err = self.run_on(**kwargs)
                self.assertEqual(rc, 2)
                self.assertIn(message, err)
                self.assertEqual(out, "")


# A synthetic set's extract, as 02-extract writes one: a part block with its notes lines.
SET = """# HW9 extract

### [HW9 Q2 stem] Setup
Pages: [HW9 p.1]
Consider the weighted graph on the vertices P, Q, R and S described below.

### [HW9 Q2c] Path weights
Pages: [HW9 p.2]
Starting at vertex P, the courier relaxes every outgoing edge before choosing the cheapest unvisited
vertex. The edges P to Q, Q to R and R to S weigh 14, 23 and 31 in that order.
**Shape:** trace
**Conventions:** ties broken alphabetically
"""
PHRASE = "the courier relaxes every outgoing edge before choosing the cheapest"


class Questions(unittest.TestCase):
    """The questions mode (FB-191): a notes page that rebuilds an unattempted set's question, by 8
    words in a row or 3 numbers in order within a sentence, fails, naming the page's line and the
    question file's line and part, never the matched text; a page with neither passes, and a run
    that an --allow file also holds doesn't count."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.questions = cls.write("hw9.md", SET)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def write(cls, name, text):
        path = os.path.join(cls.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_on(self, page, *extra):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "mock_leak.py"), "--questions", self.questions,
                            *extra, "--pages", page], capture_output=True, text=True, timeout=60)
        shown = (r.stdout + r.stderr).lower()
        self.assertNotIn("courier", shown, "the output shows the question's text")
        self.assertNotIn("relaxes every", shown, "the output shows the question's text")
        return r.returncode, r.stdout, r.stderr

    def test_eight_words_in_a_row_are_caught_without_the_text(self):
        page = self.write("sec2.md", "# 2 Shortest paths\n\nIn this trace *The* courier relaxes every\n"
                                     "outgoing edge, before choosing the **cheapest** one we keep.\n")
        rc, out, err = self.run_on(page)
        self.assertEqual((rc, err), (1, ""), out)
        self.assertIn(f"{page}:3: 10 words in a row match {self.questions}:9 (HW9 Q2c)", out)
        self.assertTrue(out.splitlines()[-1].startswith("QUESTIONS: 1 found"), out)
        # Seven words aren't enough: shorter runs are common phrasing.
        short = self.write("sec3.md", "Here the courier relaxes every outgoing edge before stopping.\n")
        self.assertEqual(self.run_on(short)[0], 0)

    def test_an_html_fragment_split_by_tags_is_caught(self):
        page = self.write("sec2.html", "<section>\n<p>Here <em>the courier</em> relaxes every outgoing\n"
                                       "edge before choosing the che&shy;apest.</p>\n</section>\n")
        rc, out, err = self.run_on(page)
        self.assertEqual(rc, 1, out + err)
        self.assertIn(f"{page}:2: 10 words in a row match", out)

    def test_three_numbers_in_order_are_caught(self):
        page = self.write("sec4.md", "## Example\n\nTake a path whose legs cost 14, then 23, and last 31 units.\n")
        rc, out, err = self.run_on(page)
        self.assertEqual(rc, 1, out + err)
        self.assertIn(f"{page}:3: 3 numbers in the same order match {self.questions}:10 (HW9 Q2c)", out)
        self.assertNotIn("words in a row", out)
        # Split across two sentences, or out of order, they don't count.
        for text in ("Legs cost 14 and 23. The last costs 31.\n", "Legs cost 23, 14 and 31.\n"):
            with self.subTest(text):
                self.assertEqual(self.run_on(self.write("sec5.md", text))[0], 0)

    def test_a_normal_fragment_passes(self):
        page = self.write("sec6.md", "# 2 Shortest paths [D4 p.17]\n\nDijkstra's algorithm settles one vertex per "
                                     "round: the unvisited vertex of least tentative distance. With edges of "
                                     "weight 5, 2 and 9 from the source, it settles the weight 2 neighbour first.\n")
        rc, out, err = self.run_on(page)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out.strip(), "QUESTIONS OK: 1 pages checked against 1 question files")

    def test_allow_drops_a_run_a_source_shares(self):
        page = self.write("sec7.md", f"Recall that {PHRASE} vertex, as in lecture.\n")
        self.assertEqual(self.run_on(page)[0], 1)
        lecture = self.write("d4.md", f"### [D4 p.9] Relaxation\nIn the lecture's story {PHRASE} vertex.\n")
        rc, out, err = self.run_on(page, "--allow", lecture)
        self.assertEqual((rc, err), (0, ""), out)

    def test_a_note_line_holding_prose_is_still_read(self):
        # Any line starting `Coverage:` or `Pages:` used to be dropped whole, so question text
        # after either went unchecked. Only the brief's own forms are dropped now.
        long = ("Every courier in the depot must plan a delivery round that visits each "
                "customer once and returns home")
        page = self.write("sec9.md", f"## A round\n\n{long} before dark.\n")
        for name, lead in (("coverage", "Coverage: "), ("pages", "Pages: "),
                           ("listed pages", "- Pages: [HW9 p.3] ")):
            with self.subTest(name):
                q = self.write(f"q-{name.replace(' ', '-')}.md",
                               f"### [HW9 Q3] Rounds\n- Pages: [HW9 p.3]\n{lead}{long}.\n")
                r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "mock_leak.py"),
                                    "--questions", q, "--pages", page],
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn(f"{page}:3: ", r.stdout)
        # The real note lines are still dropped: their words match nothing.
        notes = self.write("q-notes.md", "### [HW9 Q3] Rounds\n- Pages: [HW9 p.3], [HW9 p.4]\n"
                           "Pages: [HW9 p.5]\n**Shape:** plan a delivery round that visits each "
                           "customer once\n**Conventions:** returns home before dark each day and "
                           "every night\nCoverage: HW9 pp.1-4; 4 blocks; 1 image only (p.2: a map "
                           "of the depot); 0 flagged unreadable.\n")
        echo = self.write("sec10.md", "Plan a delivery round that visits each customer once. Returns "
                          "home before dark each day and every night. Coverage HW9 pp 1 4 4 blocks "
                          "1 image only p 2 a map of the depot 0 flagged unreadable.\n")
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "mock_leak.py"),
                            "--questions", notes, "--pages", echo],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_every_closing_line_extract_check_reads_is_a_note(self):
        # NOTE_LINE's Coverage form was narrower than the checker's closing form (a range capped
        # at 80 characters with no `;`, no nested parentheses, a case-sensitive "image only"), so
        # a closing line the checker accepts was read as question text: a false hit. The closing
        # form is extract_check.COVERAGE (qonly.py's before it went).
        notes = self.write("q-closing.md", "### [HW9 Q4] Routes\n- Pages: [HW9 p.2]\n"
                           "Coverage: HW9 pp.1-4; 4 blocks; 1 image only (p.2: a map (the legend) "
                           "of every route); 0 flagged unreadable.\n")
        echo = self.write("sec11.md", "Coverage HW9 pp 1 4 4 blocks 1 image only p 2 a map the "
                          "legend of every route 0 flagged unreadable.\n")
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "mock_leak.py"),
                            "--questions", notes, "--pages", echo],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # The two patterns agree, line by line.
        import importlib.util
        mods = {}
        for name in ("mock_leak", "extract_check"):
            spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, f"{name}.py"))
            mods[name] = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mods[name])
        for line in ("Coverage: HW9 pp.1-4; 4 blocks; 1 image only (p.2: a map (the legend) of "
                     "every route); 0 flagged unreadable.",
                     "Coverage: HW9 pp.1-4 (all; the appendix too); 4 blocks; 0 image only; 0 "
                     "flagged unreadable.",
                     "coverage: pages 1-7; 7 blocks; 0 IMAGE ONLY; 0 UNREADABLE.",
                     "Coverage: pages 1-7; 7 blocks; 1 (image only: p.1); UNREADABLE: none.",
                     "Coverage: D3 pp.2-4; 2 blocks; 0 image only; 1 flagged UNREADABLE: "
                     "p.3 weight.",
                     "Coverage: 4/5 statements; 3 blocks; 2 of 3 branches",
                     "Coverage: 3/4 = 75%", "Coverage: every courier plans a round"):
            with self.subTest(line):
                self.assertEqual(bool(mods["mock_leak"].NOTE_LINE.fullmatch(line)),
                                 bool(mods["extract_check"].COVERAGE.match(line)), line)

    def test_bad_usage(self):
        page = self.write("sec8.md", "Nothing here.\n")
        for name, args, message in (
                ("a missing question file", ["--questions", os.path.join(self.tmp.name, "none.md"), "--pages", page],
                 "none.md"),
                ("no pages", ["--questions", self.questions], "usage:"),
                ("an empty directory", ["--questions", tempfile.mkdtemp(dir=self.tmp.name), "--pages", page],
                 "no question file")):
            with self.subTest(name):
                r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "mock_leak.py"), *args],
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual((r.returncode, r.stdout), (2, ""))
                self.assertIn(message, r.stderr)


HUB_HEAD = ("| Doc id | File | Pages | Scope | Answers | Key | Rendered | Notes |\n"
            "|---|---|---|---|---|---|---|---|\n")
KEY_TEXT = "the courier settles the depot first and then every customer by distance"
VALUE_TEXT = "the round costs 17, then 29, and finally 41 units in total"
# A rendered page's other lines, so its text isn't thin (render_pdf.sh's bar, 200 characters a page).
FILLER = "Each further line of the page restates the rules of the round for the reader.\n" * 4


class HubQuestions(unittest.TestCase):
    """`--hub <root>` (r17, Hayden 2026-11-13): the questions check reads the file list
    extract_check.py computes (leak_files()), so a home the workflow prose never named, a deck's
    second part or a stray block's file, is read; an attempted set's files are not, and with no
    unattempted set it passes at once. It runs under `python3 -I`, where the script's own
    directory is not on sys.path. Round 18: a section named `Queue.java` makes no set; an
    unextracted set is read from its rendered text, and one with neither is bad usage, as is a
    MANIFEST.md with no rows it reads; with no --pages the notes and the cheat sheets are read.
    Round 19: an answers file never extracted is read from its rendered text, and thin rendered
    text read alone (a scanned PDF's) is bad usage."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def run_hub(self, *args, page_text=None):
        page = self.write("notes/sec1.md", page_text or "Nothing from any set here.\n")
        # The cwd is the hub, not the scripts directory: an import that leans on it fails here.
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "mock_leak.py"), *args,
                            "--pages", page], capture_output=True, text=True, timeout=60,
                           cwd=self.root)
        return r.returncode, r.stdout, r.stderr

    def hub(self, *args, page_text=None):
        return self.run_hub("--hub", self.root, *args, page_text=page_text)

    def test_a_decks_key_slide_in_its_second_part_is_read(self):
        # The split deck: r3.md holds its questions, r3b.md its later slides, and the key slide
        # sits in solutions/r3b.md, a file the prose list never named.
        self.write("MANIFEST.md", HUB_HEAD + "| R3 | `sources/r3.html` | 6 | in | yes | "
                                             "sections: #/5 | n/a | recitation |\n")
        self.write("_build/extract/r3.md", "### [R3 #/0] S0\n### [R3 Q1] Trace\nPages: [R3 #/0]\n"
                                           "\"Trace the round.\"\n")
        self.write("_build/extract/r3b.md", "### [R3 #/3] S3\n### [R3 #/4] S4\n")
        self.write("_build/solutions/r3.md", "### [R3 Q1] Trace\nSolution [R3 #/5]: see the key\n")
        key = self.write("_build/solutions/r3b.md", f"### [R3 #/5] Solutions\n\"{KEY_TEXT}\"\n")
        rc, out, err = self.hub(page_text=f"# Rounds\n\nRecall that {KEY_TEXT}.\n")
        self.assertEqual((rc, err), (1, ""), out)
        self.assertIn(f"words in a row match {key}:2", out)
        self.assertNotIn("courier", out)
        # The page without the copy passes.
        rc, out, err = self.hub()
        self.assertEqual((rc, err), (0, ""), out)
        self.assertEqual(out, "QUESTIONS OK: 1 pages checked against 4 question files\n")

    def test_a_stray_blocks_solutions_file_is_read(self):
        # extract/l3.md holds a stray [HW1 p.1] block, so solutions/l3.md is a home of HW1, and
        # an HW1S page there whose values a page copies fails.
        self.write("MANIFEST.md", HUB_HEAD
                   + "| HW1 | `sources/hw1.pdf` | 1 | in | no | | yes | |\n"
                     "| HW1S | `sources/hw1s.pdf` | 1 | in | yes | for HW1 | yes | |\n"
                     "| L3 | `sources/l3.pdf` | 2 | in | no | | yes | lecture |\n")
        self.write("_build/extract/hw1.md", "### [HW1 Q1a] Round\nPages: [HW1 p.1]\n\"Plan it.\"\n")
        self.write("_build/solutions/hw1.md", "### [HW1 Q1a] Round\nNo official solution.\n")
        self.write("_build/extract/l3.md", "### [L3 p.1] Rounds\n### [HW1 p.1] Homework 1\n")
        sol = self.write("_build/solutions/l3.md", f"### [HW1S p.1] Solutions\n\"{VALUE_TEXT}\"\n")
        rc, out, err = self.hub(page_text="## Example\n\nA round of 17, 29 and 41 units.\n")
        self.assertEqual((rc, err), (1, ""), out)
        self.assertIn(f"3 numbers in the same order match {sol}:2", out)

    def test_an_attempted_sets_files_are_not_read_and_none_unattempted_passes(self):
        rows = ("| HW1 | `sources/hw1.pdf` | 1 | in | {} | | yes | |\n"
                "| HW2 | `sources/hw2.pdf` | 1 | in | {} | | yes | |\n"
                "| HW1S | `sources/hw1s.pdf` | 1 | in | yes | for HW1 | yes | |\n")
        self.write("MANIFEST.md", HUB_HEAD + rows.format("no, attempted 2026-11-01", "no"))
        self.write("_build/extract/hw1.md", "### [HW1 Q1a] Round\nPages: [HW1 p.1]\n")
        self.write("_build/solutions/hw1.md", f"### [HW1 Q1a] Round\nSolution [HW1S p.1]: "
                                              f"{KEY_TEXT}\n")
        self.write("_build/extract/hw2.md", "### [HW2 Q1a] Flow\nPages: [HW2 p.1]\n")
        page = f"Recall that {KEY_TEXT}.\n"
        rc, out, err = self.hub(page_text=page)
        self.assertEqual((rc, err), (0, ""), out)
        self.assertEqual(out, "QUESTIONS OK: 1 pages checked against 1 question files\n")
        # HW1 unattempted: the same page fails.
        self.write("MANIFEST.md", HUB_HEAD + rows.format("no", "no"))
        self.assertEqual(self.hub(page_text=page)[0], 1)
        # Every set attempted: nothing to read.
        self.write("MANIFEST.md", HUB_HEAD + rows.format("no, attempted 2026-11-01",
                                                         "no, attempted 2026-11-02"))
        rc, out, err = self.hub(page_text=page)
        self.assertEqual((rc, out, err), (0, "QUESTIONS OK: no unattempted set\n", ""))

    def test_a_multi_set_answers_file_is_read_while_any_set_it_solves_is_unattempted(self):
        rows = ("| HW1 | `sources/hw1.pdf` | 1 | in | no, attempted 2026-11-01 | | yes | |\n"
                "| HW2 | `sources/hw2.pdf` | 1 | in | {} | | yes | |\n"
                "| HW1S | `sources/hw1s.pdf` | 1 | in | yes | for HW1 and HW2 | yes | |\n")
        self.write("MANIFEST.md", HUB_HEAD + rows.format("no"))
        self.write("_build/extract/hw1.md", "### [HW1 Q1a] Round\nPages: [HW1 p.1]\n")
        self.write("_build/extract/hw2.md", "### [HW2 Q1a] Flow\nPages: [HW2 p.1]\n")
        full = self.write("_build/solutions/hw1s.md", f"### [HW1S p.1] Solutions\n\"{KEY_TEXT}\"\n")
        page = f"Recall that {KEY_TEXT}.\n"
        rc, out, err = self.hub(page_text=page)
        self.assertEqual((rc, err), (1, ""), out)
        self.assertIn(f"match {full}:2", out)
        self.write("MANIFEST.md", HUB_HEAD + rows.format("no, attempted 2026-11-02"))
        self.assertEqual(self.hub(page_text=page)[:2], (0, "QUESTIONS OK: no unattempted set\n"))

    def test_a_section_name_starting_with_q_is_no_set(self):
        # r18-1 #1: `[CODE Queue.java]` read as a question block made the lecture an unattempted
        # set, so notes quoting its code failed.
        sentence = "A queue removes items in the same order that they were added to it."
        self.write("MANIFEST.md", HUB_HEAD + "| CODE | `sources/code/Queue.java` | - | in | no | | "
                                             "n/a | lecture code |\n")
        self.write("_build/extract/code.md", f"### [CODE Queue.java] Queue\n\"{sentence}\"\n")
        page = f"Recall: {sentence}\n"
        rc, out, err = self.hub(page_text=page)
        self.assertEqual((rc, out, err), (0, "QUESTIONS OK: no unattempted set\n", ""))
        # Its twin: a question block of the doc (`Q` and a number) makes it a set: the copy fails.
        self.write("_build/extract/code.md", f"### [CODE Q1] Queue\n\"{sentence}\"\n")
        rc, out, err = self.hub(page_text=page)
        self.assertEqual((rc, err), (1, ""), out)

    def test_a_manifest_with_no_rows_it_reads_is_bad_usage(self):
        # r18-1 #3: `| Id | File | ... |` gave no rows, so --hub passed with "no unattempted set".
        rows = "|---|---|---|---|---|---|---|---|\n| HW1 | `sources/hw1.pdf` | 1 | in | no | | yes | |\n"
        self.write("_build/extract/hw1.md", "### [HW1 Q1a] Round\nPages: [HW1 p.1]\n")
        self.write("MANIFEST.md", HUB_HEAD.split("\n")[0].replace("| Doc id |", "| Id |") + "\n" + rows)
        rc, out, err = self.hub()
        self.assertEqual((rc, out), (2, ""), err)
        self.assertIn("MANIFEST.md has no rows under a `| Doc id | File | ... |` header", err)
        # Its twin: the header it knows reads the set.
        self.write("MANIFEST.md", HUB_HEAD.split("\n")[0] + "\n" + rows)
        rc, out, err = self.hub()
        self.assertEqual((rc, err), (0, ""), out)
        self.assertEqual(out, "QUESTIONS OK: 1 pages checked against 1 question files\n")

    def test_an_unattempted_set_with_no_extract_is_read_from_its_rendered_text(self):
        # r18-1 #2, r18-2 #1: PE4, added unverified (11-next-exam), has a row and its renders but
        # no extract. Alone it made --hub exit 2; beside another unattempted set it was left out.
        rows = ("| HW1 | `sources/hw1.pdf` | 1 | in | {} | | yes | |\n"
                "| PE4 | `sources/pe4.pdf` | 4 | in | yes | pp. 3-4 | yes | |\n")
        self.write("MANIFEST.md", HUB_HEAD + rows.format("no, attempted 2026-11-01"))
        self.write("_build/extract/hw1.md", "### [HW1 Q1a] Round\nPages: [HW1 p.1]\n\"Round it.\"\n")
        self.write("_build/pages/HW1/p-001.png", "")
        self.write("STATUS.md", "Unverified: PE4, S9, 2026-11-12\n")
        text = self.write("_build/text/PE4/p-003.txt", f"{KEY_TEXT}.\n" + FILLER)
        page = f"# Rounds\n\nRecall that {KEY_TEXT}.\n"
        rc, out, err = self.hub(page_text=page)
        self.assertEqual((rc, err), (1, ""), out)
        self.assertIn(f"words in a row match {text}:1", out)
        # Its twin: a page that copies nothing passes.
        rc, out, err = self.hub()
        self.assertEqual((rc, out, err), (0, "QUESTIONS OK: 1 pages checked against 1 question "
                                             "files\n", ""))
        # With another unattempted set, PE4's text is still read.
        self.write("MANIFEST.md", HUB_HEAD + rows.format("no"))
        rc, out, err = self.hub(page_text=page)
        self.assertEqual((rc, err), (1, ""), out)
        self.assertIn(f"words in a row match {text}:1", out)
        # With neither an extract nor rendered text, it exits 2 naming the set, alone or not (an
        # empty _build/text/PE4/ would be thin text, r19-1 #2).
        os.remove(text)
        os.rmdir(os.path.dirname(text))
        for hw1 in ("no", "no, attempted 2026-11-01"):
            with self.subTest(hw1=hw1):
                self.write("MANIFEST.md", HUB_HEAD + rows.format(hw1))
                rc, out, err = self.hub(page_text=page)
                self.assertEqual((rc, out), (2, ""), err)
                self.assertEqual(err, "mock_leak: no file holds PE4, an unattempted set: no "
                                      "extract holds a block of it and _build/text/ holds no "
                                      "rendered text of it; render it (01-ingest) or extract it, "
                                      "then rerun\n")

    def test_an_answers_file_never_extracted_is_read_from_its_rendered_text(self):
        # r19-1 #1: HW4S, added late, has rendered text and no block anywhere; it was never read,
        # so notes quoting its answer passed.
        rows = ("| HW4 | `sources/hw4.pdf` | 1 | in | {} | | yes | hw |\n"
                "| HW4S | `sources/hw4s.pdf` | 1 | in | yes | for HW4 | yes | sol |\n")
        self.write("MANIFEST.md", HUB_HEAD + rows.format("no"))
        self.write("_build/extract/hw4.md", "### [HW4 Q1a] Tree\nPages: [HW4 p.1]\n\"Find the "
                                            "minimum spanning tree of the graph shown.\"\n")
        sentence = "The minimum spanning tree has total weight 42 since edges ab bc cd are chosen first."
        text = self.write("_build/text/HW4S/p-001.txt", f"{sentence}\n" + FILLER)
        page = f"# Trees\n\n{sentence}\n"
        rc, out, err = self.hub(page_text=page)
        self.assertEqual((rc, err), (1, ""), out)
        self.assertIn(f"words in a row match {text}:1", out)
        # Its twins: a page that copies nothing passes; HW4 attempted, nothing is read.
        rc, out, err = self.hub()
        self.assertEqual((rc, out, err), (0, "QUESTIONS OK: 1 pages checked against 2 question "
                                             "files\n", ""))
        self.write("MANIFEST.md", HUB_HEAD + rows.format("no, attempted 2026-11-01"))
        self.assertEqual(self.hub(page_text=page)[:2], (0, "QUESTIONS OK: no unattempted set\n"))
        # The rendered page alone with under 200 characters (the review's own repro) is thin:
        # bad usage, extract it.
        self.write("MANIFEST.md", HUB_HEAD + rows.format("no"))
        self.write("_build/text/HW4S/p-001.txt", f"{sentence}\n")
        rc, out, err = self.hub(page_text=page)
        self.assertEqual((rc, out), (2, ""), err)
        self.assertEqual(err, "mock_leak: HW4S's rendered text _build/text/HW4S/ is thin (under 200 "
                              "characters a page on average: a scan?) and nothing of it is "
                              "extracted: extract it, then rerun\n")

    def test_thin_rendered_text_alone_is_bad_usage(self):
        # r19-1 #2: a scanned PDF renders a form feed a page; read alone it compared nothing, so
        # the hub passed.
        rows = "| PE4 | `sources/pe4.pdf` | 4 | in | yes | pp. 3-4 | yes | exam |\n"
        self.write("MANIFEST.md", HUB_HEAD + rows)
        self.write("_build/text/PE4/p-001.txt", "\f")
        rc, out, err = self.hub(page_text=f"Recall that {KEY_TEXT}.\n")
        self.assertEqual((rc, out), (2, ""), err)
        self.assertEqual(err, "mock_leak: PE4's rendered text _build/text/PE4/ is thin (under 200 "
                              "characters a page on average: a scan?) and nothing of it is "
                              "extracted: extract it, then rerun\n")
        # Its twin: once extracted, the extract is read and the page that copies it fails.
        self.write("_build/extract/pe4.md", f"### [PE4 Q1] Rounds\nPages: [PE4 p.1]\n\"{KEY_TEXT}\"\n")
        rc, out, err = self.hub(page_text=f"Recall that {KEY_TEXT}.\n")
        self.assertEqual((rc, err), (1, ""), out)

    def test_an_extract_that_isnt_utf8_is_bad_usage(self):
        # r19-1 #4: the reason names the file, not the codec's byte offset.
        self.write("MANIFEST.md", HUB_HEAD + "| HW1 | `sources/hw1.pdf` | 1 | in | no | | yes | |\n")
        self.write("_build/extract/hw1.md", "### [HW1 Q1a] Round\nPages: [HW1 p.1]\n")
        with open(os.path.join(self.root, "_build/extract/bad.md"), "wb") as f:
            f.write(b"### [HW1 p.1] Round\n\xff\n")
        rc, out, err = self.hub()
        self.assertEqual((rc, out), (2, ""), err)
        self.assertEqual(err, f"mock_leak: can't read the hub {os.path.abspath(self.root)}: "
                              "_build/extract/bad.md isn't UTF-8 text\n")
        # Its twin: the same file in UTF-8 is read.
        self.write("_build/extract/bad.md", "### [HW1 p.1] Round\n")
        self.assertEqual(self.hub()[0], 0)

    def bare_hub(self, *args):
        """--hub with no --pages: the hub's notes/ and cheatsheet/ are the pages."""
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "mock_leak.py"), "--hub",
                            self.root, *args], capture_output=True, text=True, timeout=60, cwd=self.root)
        return r.returncode, r.stdout, r.stderr

    def test_with_no_pages_the_notes_and_the_cheat_sheets_are_read(self):
        # r18-2 #2: the workflows passed only notes/*.md, so a cheat sheet rebuilding an
        # unattempted set's setup was never checked.
        self.write("MANIFEST.md", HUB_HEAD + "| HW1 | `sources/hw1.pdf` | 1 | in | no | | yes | |\n")
        self.write("_build/extract/hw1.md", f"### [HW1 Q1a] Round\nPages: [HW1 p.1]\n\"{KEY_TEXT}\"\n")
        rc, out, err = self.bare_hub()
        self.assertEqual((rc, out), (2, ""), err)
        self.assertEqual(err, "mock_leak: no page found\n")
        self.write("notes/sec1.md", "Nothing from any set here.\n")
        sheet = self.write("cheatsheet/sheet.tex", f"\\section{{Rounds}}\nRecall that {KEY_TEXT}.\n")
        rc, out, err = self.bare_hub()
        self.assertEqual((rc, err), (1, ""), out)
        self.assertIn(f"mock_leak: {sheet}:2: ", out)
        self.assertIn("QUESTIONS: 1 found; 2 pages checked against 1 question files\n", out)
        # Its twin: a sheet that copies nothing passes, and a cheat sheet alone is read.
        self.write("cheatsheet/sheet.tex", "\\section{Rounds}\nA round has a cost.\n")
        rc, out, err = self.bare_hub()
        self.assertEqual((rc, out, err), (0, "QUESTIONS OK: 2 pages checked against 1 question "
                                             "files\n", ""))
        # A finished exam's archived sheet (cheatsheet/<exam-slug>/) is frozen and isn't read.
        self.write("cheatsheet/exam-1/exam-1-final.tex", f"Recall that {KEY_TEXT}.\n")
        self.assertEqual(self.bare_hub()[:2], (0, "QUESTIONS OK: 2 pages checked against 1 "
                                                  "question files\n"))
        os.remove(os.path.join(self.root, "notes", "sec1.md"))
        os.rmdir(os.path.join(self.root, "notes"))
        self.assertEqual(self.bare_hub()[:2], (0, "QUESTIONS OK: 1 pages checked against 1 "
                                                  "question files\n"))
        # A --pages naming nothing (a glob that matched no file) is refused.
        rc, out, err = self.bare_hub("--pages")
        self.assertEqual((rc, out), (2, ""), err)
        self.assertIn("usage:", err)
        # --pages still names the pages instead: the notes page alone passes.
        rc, out, err = self.hub()
        self.assertEqual((rc, out, err), (0, "QUESTIONS OK: 1 pages checked against 1 question "
                                             "files\n", ""))

    def test_bad_usage(self):
        self.write("_build/extract/hw1.md", "### [HW1 Q1a] Round\n")
        for name, args, message in (
                ("no MANIFEST.md", ["--hub", self.root], "no MANIFEST.md"),
                ("a MANIFEST.md it can't read", ["--hub", self.root], "MANIFEST.md"),
                ("with --questions", ["--hub", self.root, "--questions",
                                      os.path.join(self.root, "_build", "extract")], "usage:"),
                ("no root", ["--hub"], "usage:")):
            with self.subTest(name):
                if name == "a MANIFEST.md it can't read":
                    self.write("MANIFEST.md", "| Doc id | Pages |\n|---|---|\n| HW1 | 1 |\n")
                rc, out, err = self.run_hub(*args)
                self.assertEqual((rc, out), (2, ""), err)
                self.assertIn(message, err)


if __name__ == "__main__":
    unittest.main()
