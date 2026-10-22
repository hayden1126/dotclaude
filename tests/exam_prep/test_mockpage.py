"""skills/exam-prep/scripts/mockpage.py, which builds the mock page from a mock in
templates/MOCK.md's format (08-practice).

The sample is tests/exam_prep/fixtures/mock/ (a synthetic GRF101 mock, its key and a backbone).
It builds: the header, then the same nine parts in each of the three views, ids unique across the
page (a figure's ids, in any quote form, and its url(#...) references suffixed per copy),
part-level Type and Topic lines overriding the question's, a question with no parts answered as
one part (a), groups in the type list's order and by section number with the backbone's names.
Text is escaped and math kept for MathJax.

It never reads a key: a -key.md path is refused (exit 2), and so is a mock holding a key's title,
STOP line or Answer: lines (exit 1). Broken one way at a time, the sample fails with exit 1 and a
message naming the file and line: each format rule in MOCK.md (the header points table and links
too), a control character or a line break other than a newline, a MathJax macro that makes HTML
in a title, a question title or the header, and each way a figure block can carry markup a
browser runs (a tag left open at its end, an end tag outside SVG's), repeat an id another
figure, a copy of one or the page has, or point url(#id) at another figure's id, load an
image-set(), name an attribute twice or put a tag but <tspan> inside <text>. A hidden tag in an SVG title fails on any Python: as a raw
< where html.parser reads <title> as text, as a tag where it doesn't. A `---`, part or tag line
inside a code block or figure is content. A missing backbone, one that isn't UTF-8, or one whose
section title holds a macro that makes HTML, is bad usage (exit 2); a mock that isn't UTF-8 fails
(exit 1)."""
import html.parser
import os
import re
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "exam-prep")
MOCKPAGE = os.path.join(SKILL, "scripts", "mockpage.py")
FIXTURE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "mock")
MOCK = os.path.join(FIXTURE, "mock-exam1.md")
KEY = os.path.join(FIXTURE, "mock-exam1-key.md")
BACKBONE = os.path.join(FIXTURE, "backbone.md")
PARTS = ["Q1(a)", "Q1(b)", "Q2(a)", "Q2(b)", "Q3(a)", "Q4(a)", "Q4(b)", "Q4(c)", "Q4(d)"]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def sample(*edits):
    """The fixture mock with each (old, new) replaced once; an old string that isn't there fails."""
    text = read(MOCK)
    for old, new in edits:
        assert old in text, f"the fixture no longer holds {old!r}"
        text = text.replace(old, new, 1)
    return text


def views(page):
    """{view: its html} for the three view divs."""
    out = {}
    for v in ("paper", "type", "topic"):
        a = page.index(f'<div id="view-{v}"')
        b = page.find('<div id="view-', a + 1)
        out[v] = page[a:b if b > 0 else page.index("</main>")]
    return out


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_on(self, text=None, path=None, backbone=BACKBONE, name="mock-exam1.md"):
        """(exit code, stdout, stderr, page or None) for text written as name, or for path."""
        if path is None:
            path = os.path.join(self.tmp.name, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(sample() if text is None else text)
        out = os.path.join(self.tmp.name, "_build", "mock.html")
        if os.path.exists(out):
            os.remove(out)
        r = subprocess.run([sys.executable, MOCKPAGE, path, "--out", out, "--backbone", backbone],
                           capture_output=True, text=True, timeout=60)
        page = read(out) if os.path.exists(out) else None
        return r.returncode, r.stdout, r.stderr, page

    def page(self, text=None):
        rc, out, err, page = self.run_on(text)
        self.assertEqual(rc, 0, err)
        return page

    def fails(self, text, message, line=None):
        rc, _, err, page = self.run_on(text)
        self.assertEqual(rc, 1, err)
        self.assertIsNone(page)
        self.assertIn(message, err)
        if line is not None:
            self.assertRegex(err, rf"\.md:{line}: ")
        return err


class Sample(Build):
    def test_the_sample_builds(self):
        rc, out, err, page = self.run_on()
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("4 questions, 9 parts, 24 points, 50 minutes", out)
        self.assertIn("<title>GRF101 Mock Exam 1</title>", page)
        self.assertNotIn("<!-- MOCK", page)
        self.assertNotIn("{{", page)
        self.assertFalse(page.startswith("<!--"), "the template's own comment stays out of the page")

    def test_every_view_holds_every_part(self):
        v = views(self.page())
        paper = re.findall(r'data-part="([^"]+)"', v["paper"])
        self.assertEqual(paper, PARTS)
        for name in ("type", "topic"):
            self.assertEqual(sorted(set(re.findall(r'data-part="([^"]+)"', v[name]))), sorted(PARTS), name)

    def test_ids_are_unique_and_only_the_paper_copy_is_a_target(self):
        page = self.page()
        ids = re.findall(r'\bid="([^"]+)"', page)
        self.assertEqual(sorted(i for i in set(ids) if ids.count(i) > 1), [])
        v = views(page)
        self.assertIn('data-part="Q2(b)" id="q2b"', v["paper"])
        self.assertNotRegex(v["type"] + v["topic"], r'data-part="[^"]+" id=')

    def test_each_figure_copy_points_at_its_own_marker(self):
        page = self.page()
        ids = set(re.findall(r'\bid="([^"]+)"', page))
        refs = re.findall(r"url\(#([^)]+)\)", page)
        self.assertGreater(len(refs), 2)
        self.assertEqual([r for r in refs if r not in ids], [])
        self.assertEqual(len(set(refs)), len(refs), "each copy has its own marker")

    def test_tags_and_their_overrides(self):
        paper = views(self.page())["paper"]

        def chips(pid):
            art = re.search(rf'<article class="part" data-part="{re.escape(pid)}".*?</header>', paper, re.S).group(0)
            return re.findall(r'<span class="chip (?:type|topic)">([^<]+)</span>', art)
        self.assertEqual(chips("Q2(a)"), ["Trace", "§3 Shortest paths"])
        self.assertEqual(chips("Q2(b)"), ["Justify", "§2 Graph basics", "§3 Shortest paths"])
        self.assertEqual(chips("Q4(d)"), ["True or false", "§3 Shortest paths"])
        self.assertEqual(chips("Q3(a)"), ["Compute", "Table", "§1 Counting", "§2 Graph basics"])

    def test_a_question_with_no_parts_is_one_part_worth_all_its_points(self):
        paper = views(self.page())["paper"]
        art = re.search(r'<article class="part" data-part="Q3\(a\)".*?</article>', paper, re.S).group(0)
        self.assertIn('<span class="pts">2 pts</span>', art)
        self.assertIn("<table>", art)
        self.assertEqual(paper.count("<table>"), 1, "the body shows once, as the part")

    def test_groups_follow_the_type_list_and_the_section_numbers(self):
        v = views(self.page())
        self.assertEqual(re.findall(r'<section class="grp"><h2>([^<]+)<', v["type"]),
                         ["Trace", "Compute", "Table", "Justify", "True or false"])
        self.assertEqual(re.findall(r'<section class="grp"><h2>([^<]+)<', v["topic"]),
                         ["§1 Counting", "§2 Graph basics", "§3 Shortest paths"])
        self.assertIn("Compute<span class=\"pts\">3 parts · 8 pts</span>", v["type"])

    def test_the_stem_goes_with_each_part_in_the_group_views(self):
        v = views(self.page())
        self.assertEqual(v["paper"].count("<details"), 0)
        trace = re.search(r'<section class="grp"><h2>Trace<.*?</section>', v["type"], re.S).group(0)
        self.assertIn("<summary>Question 2: Shortest paths</summary>", trace)
        self.assertIn("<svg", trace)

    def test_the_header_and_inline_markdown(self):
        page = self.page()
        self.assertIn("<p>Name: ____________ ID: ________</p>", page)
        self.assertIn("<strong>Rules.</strong>", page)
        self.assertIn("matrix <em>A</em> below", page)
        self.assertIn("\\((3, 3, 2, 2, 2)\\)", page)
        self.assertIn("<pre><code>if d[u] + w(u, v) &lt; d[v]:", page)

    def test_math_is_kept_and_escaped_for_mathjax(self):
        page = self.page(sample(("has \\(n - 1\\) edges.", "has \\(a_1 < b\\_2 * c * d\\) edges.")))
        self.assertIn("\\(a_1 &lt; b\\_2 * c * d\\)", page)
        # Math inside a code span is code, read in one pass (round 7: it printed NUL characters).
        page = self.page(sample(("has \\(n - 1\\) edges.", "has `a \\(x\\) b` edges.")))
        self.assertIn("<code>a \\(x\\) b</code>", page)
        self.assertNotIn("\x00", page)

    def test_stray_html_shows_as_text(self):
        page = self.page(sample(("How many edges does it have?",
                                 'How many <img src=x onerror="alert(1)"> edges?')))
        self.assertNotIn("<img", page)
        self.assertIn("&lt;img src=x", page)

    def test_a_fence_or_figure_keeps_its_lines_as_content(self):
        page = self.page(sample(("    d[v] = d[u] + w(u, v)\n```",
                                 "    d[v] = d[u] + w(u, v)\n---\nType: int\n**(c) (2 pts)** x\n```")))
        self.assertIn("---\nType: int\n**(c) (2 pts)** x</code></pre>", page)
        self.assertEqual(re.findall(r'data-part="([^"]+)"', views(page)["paper"]), PARTS)


class Key(Build):
    def test_a_key_path_is_refused(self):
        rc, _, err, page = self.run_on(path=KEY)
        self.assertEqual(rc, 2)
        self.assertIn("is a key", err)
        self.assertIsNone(page)

    def test_key_content_is_refused(self):
        for line in ("# ANSWER KEY: GRF101 Mock Exam 1",
                     "> **STOP. Quarantined key.** Attempt it first.",
                     "**(a)** Answer: 6"):
            with self.subTest(line=line):
                self.fails(sample(("_(answer space)_", f"{line}\n\n_(answer space)_")), "reads like an answer key")

    def test_the_key_itself_under_a_mock_name_is_refused(self):
        self.fails(read(KEY), "reads like an answer key", line=1)


class Format(Build):
    def test_each_rule(self):
        cases = [
            ("## Question 2: Shortest paths (12 points)", "## Question 3: Shortest paths (12 points)",
             "question 3 where question 2 belongs"),
            ("## Question 2: Shortest paths (12 points)", "## Question 2: Shortest paths",
             "a question starts with ## Question N"),
            ("## Question 2: Shortest paths (12 points)", "## Question 02: Shortest paths (12 points)",
             "a question starts with ## Question N"),
            ("## Question 2: Shortest paths (12 points)", "## Question \u0662: Shortest paths (12 points)",
             "a question starts with ## Question N"),
            ("| 2 | Shortest paths | 12 |", "| \u00b2 | Shortest paths | 12 |", "the points table has no row for 2"),
            ("**(b) (3 pts)** A graph on 5", "**(b) (\u0663 pts)** A graph on 5", "its points are missing"),
            ("**Time:** 50 minutes.", "**Time:** \u0665\u0660 minutes.", "the header has no **Time:**"),
            ("Topic: §3\n\nThe directed", "Topic: §\u0663\n\nThe directed", "isn't a section number like §2"),
            ("**(b) (3 pts)** A graph on 5", "**(c) (3 pts)** A graph on 5", "part (c) where (b) belongs"),
            ("**(b) (3 pts)** A graph on 5", "**(b)** A graph on 5", "its points are missing"),
            ("**(b) (3 pts)** A graph on 5", "**(b) (4 pts)** A graph on 5", "parts sum to 7 points, not 6"),
            ("**Total:** 24 points.", "**Total:** 25 points.", "the questions sum to 24 points, the header says 25"),
            ("Type: trace\n", "Type: trace | essay\n", "type 'essay' isn't one of"),
            ("Topic: §3\n\nThe directed", "Topic: §4\n\nThe directed", "topic §4 isn't a section of the backbone"),
            ("Topic: §3\n\nThe directed", "Topic: 3\n\nThe directed", "topic '3' isn't a section number"),
            ("Type: trace\n", "Type:\n", "Type: with no value"),
            ("Type: compute\nTopic: §2\n\n**(a)", "Topic: §2\n\n**(a)", "Q1(a) has no Type: line"),
            ("Mark each statement", "### Mark each statement", "a heading inside a question"),
            ("Mark each statement", "TODO-VERIFY Mark each statement", "a TODO-VERIFY is left"),
            ("\\[ (A^3)_{11} \\]", "\\[ \\href{x}{(A^3)_{11}} \\]", "\\href makes HTML inside math"),
            ("| | 1 | 2 | 3 |\n|---|---|---|---|", "| | 1 | 2 | 3 |", "a table needs a | --- | line"),
            ("# GRF101 Mock Exam 1", "GRF101 Mock Exam 1", "the mock starts with its # title line"),
            ("**Time:** 50 minutes. ", "", "the header has no **Time:**"),
            ("**Rules.**", "# Rules\n\n**Rules.**", "a heading inside a question"),
            ("How many edges does it have?", "See [the notes](https://x.test/n).", "a link or image"),
            ("How many edges does it have?", "![graph](g.png)", "a link or image"),
            ("| 2 | Shortest paths | 12 |", "| 2 | Shortest paths | 10 |", "the points table gives question 2 10, the mock 12"),
            ("| | **Total** | **24** |", "| | **Total** | **40** |", "the points table gives the total 40, the mock 24"),
            ("| 3 | Counting walks | 2 |\n", "", "the points table has no row for 3"),
            ("| | **Total** | **24** |", "| 9 | Extra | 0 |", "the points table lists question 9"),
        ]
        for old, new, message in cases:
            with self.subTest(message=message):
                self.fails(sample((old, new)), message)

    def test_a_macro_that_makes_html_is_refused_anywhere(self):
        for macro in ("\\href{javascript:alert(1)}{x}", "\\style{color:red}{x}", "\\class{c}{x}",
                      "\\cssId{i}{x}", '\\mmlToken{mi}[href="javascript:alert(1)"]{x}', "\\require{html}",
                      "\\data{part=Q9(a)}{x}", "\\bbox[position:fixed]{x}"):
            for where, old in (("the title", "# GRF101 Mock Exam 1"),
                               ("a question title", "## Question 2: Shortest paths (12 points)"),
                               ("the header", "**Rules.** Closed book")):
                with self.subTest(macro=macro, where=where):
                    new = old.replace("Mock Exam 1", f"Mock \\({macro}\\) Exam 1").replace(
                        "Shortest paths", f"Paths \\({macro}\\)").replace("Closed book", f"Closed \\({macro}\\)")
                    self.fails(sample((old, new)), "makes HTML inside math")

    def test_a_name_that_only_starts_like_a_macro_is_fine(self):
        self.page(sample(("has \\(n - 1\\) edges.", "has \\(\\classify(n) - \\hrefx\\) edges.")))
        self.fails(sample(("has \\(n - 1\\) edges.", "has \\(\\bbox[position:fixed]{n}\\) edges.")),
                   "\\bbox makes HTML inside math")

    def test_a_key_line_indented_or_inside_a_line_and_a_control_character(self):
        self.fails(sample(("_(answer space)_", "  **(a)** Answer: 6\n\n_(answer space)_")), "reads like an answer key")
        self.fails(sample(("_(answer space)_", "- see **(a)** Answer: 6\n\n_(answer space)_")), "reads like an answer key")
        self.fails(sample(("How many edges", "How\x07 many edges")), "a control character")

    def test_a_line_break_other_than_a_newline_is_refused_at_its_line(self):
        # mock_key.py splits the mock at newlines alone: a part line hidden behind \x0c would
        # carry its own type here and not there (round 3).
        line = next(k for k, t in enumerate(sample().splitlines(), 1) if "How many edges" in t)
        for ch in ("\x0b", "\x0c", "\x1c", "\x1e", "\x85", "\u2028", "\u2029", "\x9f"):
            with self.subTest(ch=hex(ord(ch))):
                self.fails(sample(("How many edges", f"How{ch}Type: compute many edges")),
                           "a control character or a line break other than a newline", line=line)

    def test_the_points_table_is_required(self):
        text = sample()
        start = text.index("| Question | Topic | Points |")
        self.fails(text[:start] + text[text.index("---", start + 40):], "the header has no points table")

    def test_the_message_names_the_line(self):
        text = sample(("**(b) (3 pts)** A graph on 5", "**(c) (3 pts)** A graph on 5"))
        line = text.splitlines().index(next(t for t in text.splitlines() if t.startswith("**(c) (3 pts)**"))) + 1
        self.fails(text, "part (c) where (b) belongs", line=line)

    def test_no_header_rule_and_no_questions(self):
        self.fails("# T\n\n**Time:** 5 minutes. **Total:** 1 point.\n", "no --- line ends the header")
        self.fails("# T\n\n**Time:** 5 minutes. **Total:** 1 point.\n\n---\n\n", "no questions")


class Figure(Build):
    SVG = '<svg viewBox="0 0 320 140" role="img" aria-label="Directed graph'

    def test_each_way_a_figure_can_run_markup(self):
        cases = [
            ('<g>', '<script>alert(1)</script><g>', "<script> isn't one of SVG's"),
            ('<g>', '<foreignObject><p>x</p></foreignObject><g>',
             "<foreignobject> isn't one of SVG's"),
            ('<g>', '<image href="x.png"/><g>', "<image> isn't one of SVG's"),
            ('<g>', '<g font-size="14" onclick="alert(1)">', "has the attribute onclick"),
            ('<g>', '<g font-size="14" style="fill:red">', "has the attribute style"),
            ('<g>', '<path href="#x"/><g>', "has the attribute href"),
            ('<g>', '<!-- x --><g>', "an HTML comment"),
            ('<g>', '<![CDATA[ x ]]><g>', "a CDATA section"),
            ('<g>', '<title><img src=x onerror=alert(1)></title><g>',
             "a raw < in its text|<img> isn't one of SVG's"),
            ('<g>', '<text>a < b</text><g>', "a raw < in its text"),
            ('<g>', '</svg><svg role="img" aria-label="y"><g>', "one <svg> per figure"),
            (self.SVG, '<svg viewBox="0 0 320 140" aria-label="Directed graph', 'needs role="img" and an aria-label'),
            # html.parser's close() drops a tag left open at the end unread; a browser reads on
            # into the page, where it ran as an <img onerror> (round 4).
            ('</g>\n</svg>', '</g>\n<img src onerror=alert(1) a="\n</svg>', "left open runs past its </svg>"),
            ('</g>\n</svg>', '</g>\n<!-- x\n</svg>', "left open runs past its </svg>"),
            ('</g>', '</g></div>', "</div> isn't one of SVG's"),
            ('</g>', '</g></p>', "</p> isn't one of SVG's"),
            # A browser reads markup inside SVG's <title> and <desc> as HTML; html.parser may not
            # (round 5): they hold text only, and tags nest strictly.
            ('<g>', '<desc><title><g class="</title><img src onerror=alert(1)>"/></title></desc><g>',
             "<title> inside <desc>, which holds text only"),
            ('<g>', '<title>t<g/></title><g>', "<g> inside <title>|a raw < in its text"),
            ('<g>', '<g></text>', "</text> where <g> is open"),
            ('<g>', '<!DOCTYPE x><g>', "a declaration"),
            ('<g>', '<?x y?><g>', "a processing instruction"),
            ('<g>', '<![x[ y ]]><g>', "a <!\\[ section html.parser can't read|a CDATA section"),
            # Round 8: a url() that loads something, and a CSS escape that could spell one.
            ('<g>', '<g fill="url(https://x.example/a.svg)">', "has a url\\(\\) that isn't url\\(#id\\)"),
            ('<g>', '<g fill="URL( \'//x.example/a\' )">', "has a url\\(\\) that isn't url\\(#id\\)"),
            ('<g>', '<g fill="\\75 rl(#x)">', "<g>'s fill holds a backslash"),
            # Round 9: image-set() loads too, and a browser keeps a repeated attribute's first
            # value where this check would read its last.
            ('<g>', '<g mask="-webkit-image-set(\'https://x.example/a.png\' 1x)">', "or an image-set\\(\\)"),
            (self.SVG, self.SVG.replace('role="img"', 'role="img" aria-label=""', 1), "names an attribute twice"),
            # Round 10: a child of <text> a browser doesn't draw would split a word for the leak check.
            ('<g>', '<text x="1" y="9">a<desc/>b</text><g>', "<desc> inside <text>, which holds text and <tspan> only"),
        ]
        for old, new, message in cases:
            with self.subTest(message=message):
                # Which message a hidden tag gets depends on whether this Python's html.parser
                # reads <title> as raw text (recent security releases do); either way it fails.
                rc, _, err, page = self.run_on(sample((old, new)))
                self.assertEqual(rc, 1, err)
                self.assertRegex(err, f"\\.md:\\d+: figure: .*({message})")

    def test_an_open_block_is_named_at_its_first_line(self):
        for old, new, message in (("</g>\n</svg>", "</g>", "a figure with no closing </svg>"),
                                  ("    d[v] = d[u] + w(u, v)\n```", "    d[v] = d[u] + w(u, v)",
                                   "a code block with no closing ```")):
            with self.subTest(message=message):
                text = sample((old, new))
                opener = "<svg" if "figure" in message else "```"
                line = next(k for k, t in enumerate(text.splitlines(), 1) if t.startswith(opener))
                self.fails(text, message, line=line)

    def test_url_in_capitals_is_suffixed_too(self):
        page = self.page(sample(('marker-end="url(#arrow)"', 'marker-end="URL(#arrow)"')))
        ids = re.findall(r"""\bid=["']([^"']+)["']""", page)
        refs = re.findall(r"""url\(['"]?#([^)'"]+)['"]?\)""", page, re.I)
        self.assertEqual(len([r for r in refs if r.startswith("arrow")]), len(refs))
        self.assertEqual([r for r in refs if r not in ids], [])

    def test_a_reference_to_another_figures_marker_is_refused(self):
        # Each copy suffixes its own references, so one into another figure would dangle (round 7).
        figure = ('<svg viewBox="0 0 10 10" role="img" aria-label="x">\n<line x1="0" y1="0" x2="5" y2="5" '
                  'marker-end="url(#arrow)"/>\n</svg>\n\n')
        self.fails(sample(("Mark each statement", figure + "Mark each statement")),
                   "url(#arrow) names no id of its own figure")

    def test_a_figure_id_twice_in_a_mock_is_refused(self):
        figure = ('<svg viewBox="0 0 10 10" role="img" aria-label="x">\n<defs><marker id="arrow"><path d="M0 0"/>'
                  '</marker></defs>\n</svg>\n\n')
        self.fails(sample(("Mark each statement", figure + "Mark each statement")), "id 'arrow' again (line 41)")

    def test_ids_in_any_quote_form_are_suffixed_with_their_references(self):
        page = self.page(sample(('<marker id="arrow"', "<marker id='arrow'"),
                                ('marker-end="url(#arrow)"', 'marker-end="url(\'#arrow\')"')))
        ids = re.findall(r"""\bid=["']([^"']+)["']""", page)
        self.assertEqual(sorted(i for i in set(ids) if ids.count(i) > 1), [])
        refs = re.findall(r"""url\(['"]?#([^)'"]+)['"]?\)""", page)
        self.assertEqual(len(refs), 6, "the paper copy, two in the type view, three in the topic view")
        self.assertEqual([r for r in refs if r not in ids], [])

    def test_a_copy_keeps_every_attribute_and_text(self):
        label = 'Tree; node id=\'r\' onmouseover=\'alert(1)\' is the root, id=x too'
        page = self.page(sample((self.SVG, self.SVG.replace("Directed graph", label)),
                                ('<text x="15" y="75">S</text>', '<text x="15" y="75">S id=\'s\'</text>'),
                                ('<marker id="arrow"', "<marker id=arrow")))

        class Figures(html.parser.HTMLParser):
            def __init__(self):
                super().__init__()
                self.copies, self.texts, self.inside, self.ids = [], [], False, []

            def handle_starttag(self, tag, attrs):
                self.ids += [v for k, v in attrs if k == "id"]
                if tag == "svg":
                    self.copies.append([])
                    self.inside = True
                if self.inside:
                    self.copies[-1].append((tag, [k for k, _ in attrs], dict(attrs).get("aria-label")))

            def handle_endtag(self, tag):
                if tag == "svg":
                    self.inside = False

            def handle_data(self, data):
                if self.inside and data.strip():
                    self.texts.append(data)
        f = Figures()
        f.feed(page)
        self.assertEqual(len(f.copies), 6)
        self.assertTrue(all(c == f.copies[0] for c in f.copies), "a copy's tags or attributes differ")
        self.assertTrue(f.copies[0][0][2].startswith(label + ": S to A"), f.copies[0][0][2])
        self.assertEqual(f.texts.count("S id='s'"), 6)
        self.assertEqual(sorted(i for i in set(f.ids) if f.ids.count(i) > 1), [])
        self.assertIn("arrow-ty1s", f.ids)

    def test_every_copy_is_written_back_from_what_the_check_read(self):
        # The page never gets the raw block: an odd but legal attribute comes out quoted and
        # escaped in every copy, as the check read it (round 5).
        page = self.page(sample(('<marker id="arrow"', '<marker data-x=a`b&amp;"c id="arrow"')))
        self.assertEqual(page.count('data-x="a`b&amp;&quot;c"'), 6)
        self.assertNotIn("data-x=a`b", page)
        self.assertEqual(page.count('<path d="M0 0 L10 5 L0 10 z"/>'), 6, "a self-closing tag stays one")

    def test_character_references_in_a_figure(self):
        for ref, message in (("&#92;href", "&#92; in its text: write the character itself"),
                             ("&bsol;", "&bsol; in its text: only &lt;"),):
            with self.subTest(ref=ref):
                self.fails(sample(('<text x="15" y="75">S</text>', f'<text x="15" y="75">S{ref}</text>')), message)
                self.fails(sample(("<g>", f"<title>S{ref}</title><g>")), message)
        self.page(sample(('<text x="15" y="75">S</text>', '<text x="15" y="75">S &amp; &quot;T&quot;</text>')))

    def test_a_figure_id_the_page_uses_or_a_header_figure_shares(self):
        for pid in ("q2b", "view-type", "main", "MathJax-script", "MJX-SVG-global-cache"):
            with self.subTest(pid=pid):
                self.fails(sample(('<marker id="arrow"', f'<marker id="{pid}"'), ("url(#arrow)", f"url(#{pid})")),
                           f"id '{pid}' is one the page uses itself")
        header_fig = '<svg viewBox="0 0 1 1" role="img" aria-label="h">\n<defs><marker id="arrow"/></defs>\n</svg>\n\n'
        self.fails(sample(("**Rules.**", header_fig + "**Rules.**")), "id 'arrow' again")

    def test_a_copy_id_another_figure_or_the_page_has_is_refused(self):
        copy = next(i for i in re.findall(r'id="(arrow-[^"]+)"', self.page()))
        figure = (f'<svg viewBox="0 0 10 10" role="img" aria-label="x">\n<defs><marker id="{copy}"><path d="M0 0"/>'
                  '</marker></defs>\n</svg>\n\n')
        self.fails(sample(("Mark each statement", figure + "Mark each statement")),
                   f"its id 'arrow' becomes '{copy}' in another view, an id the page already has")
        self.fails(sample(('<marker id="arrow"', '<marker id="view"'), ("url(#arrow)", "url(#view)")),
                   "its id 'view' becomes 'view-")

    def test_an_escaped_less_than_sign_is_fine_and_text_is_escaped(self):
        page = self.page(sample(('<text x="15" y="75">S</text>', '<text x="15" y="75">S &lt; A > B</text>')))
        self.assertIn("S &lt; A &gt; B", page)


class Usage(Build):
    def test_a_missing_backbone_is_bad_usage(self):
        rc, _, err, page = self.run_on(backbone=os.path.join(self.tmp.name, "none.md"))
        self.assertEqual(rc, 2)
        self.assertIn("no backbone", err)
        self.assertIsNone(page)

    def test_a_backbone_with_no_sections_is_bad_usage(self):
        empty = os.path.join(self.tmp.name, "backbone.md")
        with open(empty, "w", encoding="utf-8") as f:
            f.write("# Backbone\n\n## Counting\n\n## §\u0663 Walks (`sec-3`)\n")
        rc, _, err, _ = self.run_on(backbone=empty)
        self.assertEqual(rc, 2)
        self.assertIn("no ## §N", err)

    def test_a_backbone_title_with_a_macro_that_makes_html_is_bad_usage(self):
        with open(BACKBONE, encoding="utf-8") as f:
            text = f.read()
        bad = os.path.join(self.tmp.name, "backbone.md")
        with open(bad, "w", encoding="utf-8") as f:
            f.write(re.sub(r"^(## §1 )", r"\1\\(\\style{color:red}{x}\\) ", text, count=1, flags=re.M))
        rc, _, err, _ = self.run_on(backbone=bad)
        self.assertEqual(rc, 2, err)
        self.assertIn("§1's title holds \\style, which makes HTML inside math", err)

    def test_a_file_that_isnt_utf8_is_named(self):
        latin = os.path.join(self.tmp.name, "latin.md")
        with open(latin, "wb") as f:
            f.write(read(BACKBONE).replace("Counting", "Counting caf\xe9", 1).encode("latin-1"))
        rc, _, err, page = self.run_on(backbone=latin)
        self.assertEqual((rc, page), (2, None), err)
        self.assertIn("latin.md isn't UTF-8 text", err)
        mock = os.path.join(self.tmp.name, "mock-exam1.md")
        with open(mock, "wb") as f:
            f.write(sample(("Mark each statement", "Mark each caf\xe9 statement")).encode("latin-1"))
        rc, _, err, page = self.run_on(path=mock)
        self.assertEqual((rc, page), (1, None), err)
        self.assertIn("mock-exam1.md: not UTF-8 text", err)

    def test_a_missing_mock_is_bad_usage(self):
        rc, _, err, _ = self.run_on(path=os.path.join(self.tmp.name, "none.md"))
        self.assertEqual(rc, 2)
        self.assertIn("no mock at", err)


if __name__ == "__main__":
    unittest.main()
