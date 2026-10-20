"""skills/exam-prep/scripts/assemble.py: the notes page from the chassis and the fragments.

A synthetic hub: the skill's own chassis template with its placeholders filled, its CHASSIS.md, two
notes files, their section fragments, an exam-day map and one step-through figure. The page gets
every piece in its place and one accent rule per section; anything malformed (a placeholder left,
a missing or misnamed fragment, a forbidden tag, attribute or link, a class outside CHASSIS.md's
component table, a TODO-VERIFY, a FIG marker with no step-through, a step-through placed other
than once, no map) writes nothing and leaves the last good page alone, while escaped markup in a
code block is text and passes. The skill repo's synthetic sample hub, the source of the chassis's
reference screenshots, is the template filled, links the skill's CHASSIS.md and assembles with
every link resolved; with EXAM_PREP_PLAYWRIGHT set, its page also passes verify_page.mjs."""
import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "exam-prep")
SCRIPT = os.path.join(SKILL, "scripts", "assemble.py")
CHASSIS = os.path.join(SKILL, "templates", "notes-chassis.html")
CHASSIS_MD = os.path.join(SKILL, "templates", "CHASSIS.md")
LINKCHECK = os.path.join(SKILL, "scripts", "linkcheck.py")
VERIFY_PAGE = os.path.join(SKILL, "scripts", "verify_page.mjs")
SAMPLE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "site")

_spec = importlib.util.spec_from_file_location("assemble", SCRIPT)
assemble = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(assemble)

SEC1 = """<section class="note" id="sec-1">
  <h2><span class="n">§1</span> Widgets</h2>
  <h3 id="sec-1-basics">1.1 Basics</h3>
  <p>A <strong>widget</strong> <a class="slink">D1 p.2</a>, see <a class="xref" href="#sec-2-more">§2.1</a>.</p>
  <div class="callout def"><div class="lab">Definition</div><p>x</p></div>
</section>"""
SEC2 = """<section class="note" id="sec-2">
  <h2><span class="n">§2</span> Gadgets</h2>
  <h3 id="sec-2-more">2.1 More</h3>
  <!-- FIG fig-2-walk: a walk through the gadget -->
  <ol class="steps"><li>one</li></ol>
</section>"""
STEP = """<figure id="fig-2-walk"><svg viewBox="0 0 10 10"></svg>
<div class="fig-controls"><button data-act="next">Next</button></div></figure>"""
NAV = """<details class="examnav"><summary>Exam-day map</summary><div class="ebody">
<p class="efound"><a class="xref" href="#sec-1-basics">§1.1</a></p></div></details>"""


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def filled_chassis():
    return re.sub(r"\{\{[^}]*\}\}", "Filled", read(CHASSIS))


class Hub:
    def __init__(self, sections=None, chassis=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        sections = {1: SEC1, 2: SEC2} if sections is None else sections
        os.makedirs(os.path.join(self.root, "notes"))
        os.makedirs(os.path.join(self.root, "_build", "frag"))
        self.write("_build/chassis.html", filled_chassis() if chassis is None else chassis)
        self.write("_build/CHASSIS.md", read(CHASSIS_MD))
        for n, text in sections.items():
            self.write(f"notes/{n:02d}-s{n}.md", f"# §{n} S\n")
            if text is not None:
                self.write(f"_build/frag/sec{n}.html", text)
        self.write("_build/frag/examnav.html", NAV)
        self.write("_build/frag/step-fig-2-walk.html", STEP)
        self.write("_build/frag/step-figs.js", "window.NotesFig['fig-2-walk']=function(){};")

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def remove(self, rel):
        os.remove(os.path.join(self.root, rel))

    def run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = assemble.main(["--root", self.root])
        return rc, out.getvalue()

    def page(self):
        path = os.path.join(self.root, "_build", "notes.html")
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def close(self):
        self.tmp.cleanup()


class AssembleTest(unittest.TestCase):
    def hub(self, **kw):
        h = Hub(**kw)
        self.addCleanup(h.close)
        return h

    def test_template_has_each_marker_once_and_only_placeholders_to_fill(self):
        with open(CHASSIS, encoding="utf-8") as f:
            text = f.read()
        for m in assemble.MARKERS:
            self.assertEqual(text.count(m), 1, m)
        self.assertTrue(re.search(r"\{\{[^}]*\}\}", text))
        # A fragment, as the artifact host wraps it (CHASSIS.md): no document of its own.
        self.assertTrue(re.match(r"<!--.*?-->\n<title>", text, re.S))
        self.assertIsNone(re.search(r"<!doctype|<html\b|<head\b|<body\b", text, re.I))

    def test_assembles_every_piece_in_place(self):
        h = self.hub()
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        page = h.page()
        self.assertLess(page.index('id="sec-1"'), page.index('id="sec-2"'))
        self.assertLess(page.index('class="examnav"'), page.index('id="sec-1"'))
        self.assertIn('<figure id="fig-2-walk">', page)
        self.assertNotIn("<!-- FIG", page)
        self.assertIn("window.NotesFig['fig-2-walk']", page)
        for m in assemble.MARKERS:
            self.assertNotIn(m, page)
        self.assertIn(".wrap section.note:nth-of-type(2){--sec-accent:#277a4d", page)
        self.assertNotIn("nth-of-type(3)", page)
        self.assertIn(':root[data-theme="dark"] .wrap section.note:nth-of-type(1){--sec-accent:#4cbbda}',
                      page)
        size = os.path.getsize(os.path.join(h.root, "_build", "notes.html"))
        self.assertIn(f"({size:,} bytes)", out)  # bytes, not characters: the page holds a §

    def test_accents_cycle_past_seven_sections(self):
        css = assemble.accents(9)
        self.assertIn("nth-of-type(8){--sec-accent:#0b6e8f", css)
        self.assertIn("nth-of-type(9){--sec-accent:#277a4d", css)
        self.assertEqual(css.count('[data-theme="dark"] .wrap'), 9)
        self.assertEqual(css.count(':root:not([data-theme="light"])'), 9)

    def assertRefused(self, h, needle):
        rc, out = h.run()
        self.assertEqual(rc, 1, out)
        self.assertIn(needle, out)
        self.assertIsNone(h.page())

    def test_unfilled_placeholder_refused(self):
        with open(CHASSIS, encoding="utf-8") as f:
            self.assertRefused(self.hub(chassis=f.read()), "not filled")

    def test_marker_missing_refused(self):
        h = self.hub(chassis=filled_chassis().replace("<!-- SECTIONS -->", ""))
        self.assertRefused(h, "<!-- SECTIONS --> appears 0 times")

    def test_missing_fragment_refused(self):
        self.assertRefused(self.hub(sections={1: SEC1, 2: None}), "frag/sec2.html missing")

    def test_fragment_with_the_wrong_id_refused(self):
        self.assertRefused(self.hub(sections={1: SEC1, 2: SEC2.replace('id="sec-2"', 'id="sec-3"')}),
                           'not one <section class="note" id="sec-2">')

    def test_two_sections_in_one_fragment_refused(self):
        self.assertRefused(self.hub(sections={1: SEC1 + "\n" + SEC1.replace("sec-1", "sec-1b"),
                                              2: SEC2}), "frag/sec1.html: not one")

    def test_content_after_the_section_refused(self):
        self.assertRefused(self.hub(sections={1: SEC1 + "\n<p>stray</p>", 2: SEC2}),
                           "frag/sec1.html: not one")

    def test_unknown_class_in_the_exam_day_map_refused(self):
        h = self.hub()
        h.write("_build/frag/examnav.html", NAV.replace('class="efound"', 'class="found"'))
        self.assertRefused(h, "frag/examnav.html: classes outside CHASSIS.md's component table: found")

    def in_sec1(self, extra):
        return self.hub(sections={1: SEC1.replace("</section>", extra + "\n</section>"), 2: SEC2})

    def test_forbidden_tags_refused(self):
        for bad, tag in (("<script>x()</script>", "script"), ("<style>p{}</style>", "style"),
                         ('<link rel="stylesheet" href="https://x.example/a.css">', "link"),
                         ('<iframe src="https://x.example"></iframe>', "iframe"),
                         ('<base href="https://x.example/">', "base"),
                         ('<SCRIPT>x()</SCRIPT>', "script"),
                         ('<svg><set attributeName="href" to="#x"/></svg>', "set"),
                         ('<svg><animate attributeName="href"/></svg>', "animate"),
                         ('<svg><foreignObject><p>x</p></foreignObject></svg>', "foreignobject")):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(bad), f"forbidden tags: {tag}")

    def test_style_and_event_attributes_refused(self):
        for bad, attr in (('<p style="color:red">x</p>', "style"),
                          ('<p onclick="x()">x</p>', "onclick"),
                          ('<svg onload="x()"></svg>', "onload"),
                          ('<img ONERROR=x() src="https://x.example/a.png">', "onerror")):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(bad), f"forbidden attributes: {attr}")

    def test_links_other_than_ids_http_and_mail_refused(self):
        for bad in ('<a href="javascript:x()">x</a>', '<a href="JavaScript:x()">x</a>',
                    '<a href="&#106;avascript:x()">x</a>', '<a href="java\tscript:x()">x</a>',
                    '<a href="data:text/html,x">x</a>', '<img src="sources/d1.png">',
                    '<svg><use xlink:href="javascript:x()"/></svg>'):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(bad), "links that aren't #id, http(s) or mailto")

    def test_markup_a_browser_reads_differently_refused(self):
        for bad in ('<![CDATA[><script>x()</script><p class="rail">]]>',
                    "<!--><script>x()</script>-->", "<!-- a note -->", "<!DOCTYPE html>",
                    "<?php x ?>", "<!-- FIG fig-1-x: a > b -->"):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(bad), "markup a browser reads differently")

    def test_tex_that_makes_html_refused_outside_code(self):
        for bad in ("\\(\\href{javascript:x()}{a}\\)", "\\(\\style{position:fixed}{a}\\)",
                    "\\(\\class{rail}{a}\\)", "\\(\\cssId{sec-1}{a}\\)",
                    "<code>x</code> then \\(\\href{javascript:x()}{a}\\)"):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(f"<p>{bad}</p>"), "MathJax macros that make HTML")
        h = self.in_sec1("<pre><code>\\href{https://x.example}{a}</code></pre>"
                         "<p><code>\\style</code>, and \\(\\classify\\) is no macro.</p>")
        rc, out = h.run()
        self.assertEqual(rc, 0, out)

    def test_safe_links_pass(self):
        h = self.in_sec1('<p><a href="https://x.example/a">a</a> <a href="mailto:t@x.example">m</a> '
                         '<a class="xref" href="#sec-2-more">b</a></p>')
        rc, out = h.run()
        self.assertEqual(rc, 0, out)

    def test_escaped_markup_in_code_is_text(self):
        h = self.in_sec1('<pre><code>&lt;div class="fancy" style="color:red" onclick="x()"&gt;'
                         '&lt;script&gt;x()&lt;/script&gt; a &amp;&amp; b</code></pre>'
                         '<p>Inline <code>&lt;style&gt;</code> too.</p>')
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        self.assertIn("&lt;script&gt;", h.page())

    def test_unknown_class_refused(self):
        for bad, cls in (('class="callout fancy"', "fancy"), ("class=fancy", "fancy"),
                         ("class='callout  fancy'", "fancy")):
            with self.subTest(bad=bad):
                h = self.hub(sections={1: SEC1.replace('class="callout def"', bad), 2: SEC2})
                self.assertRefused(h, f"classes outside CHASSIS.md's component table: {cls}")

    def test_the_pages_own_classes_refused_in_a_fragment(self):
        classes = assemble.chassis_classes(filled_chassis())
        for c in ("rail", "toc", "active", "figbox"):
            with self.subTest(c=c):
                self.assertIn(c, classes)
                self.assertRefused(self.in_sec1(f'<div class="{c}">x</div>'),
                                   f"component table: {c}")

    def test_hook_classes_only_in_a_step_through(self):
        h = self.hub()
        h.write("_build/frag/step-fig-2-walk.html",
                STEP.replace("</figure>", '<p class="fs-status">Step 0.</p></figure>'))
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        self.assertRefused(self.in_sec1('<p class="fs-status">x</p>'), "component table: fs-status")

    def test_a_step_through_is_checked_too(self):
        h = self.hub()
        h.write("_build/frag/step-fig-2-walk.html", STEP.replace("<svg", '<svg onload="x()"'))
        self.assertRefused(h, "frag/step-fig-2-walk.html: forbidden attributes: onload")

    def test_todo_verify_refused(self):
        self.assertRefused(self.in_sec1("<p>TODO-VERIFY: the sum of 3 to 7</p>"),
                           "frag/sec1.html: a TODO-VERIFY is left")

    def test_a_step_through_with_no_marker_refused(self):
        h = self.hub(sections={1: SEC1, 2: SEC2.replace(
            "<!-- FIG fig-2-walk: a walk through the gadget -->", "<figure id=\"fig-2-walk\"></figure>")})
        self.assertRefused(h, "frag/step-fig-2-walk.html: its FIG marker appears 0 times")

    def test_a_marker_placed_twice_refused(self):
        marker = "<!-- FIG fig-2-walk: a walk through the gadget -->"
        h = self.hub(sections={1: SEC1, 2: SEC2.replace(marker, marker + "\n" + marker)})
        self.assertRefused(h, "frag/step-fig-2-walk.html: its FIG marker appears 2 times")

    def test_missing_chassis_md_refused(self):
        h = self.hub()
        h.remove("_build/CHASSIS.md")
        self.assertRefused(h, "_build/CHASSIS.md missing")

    def test_chassis_md_naming_an_unstyled_class_refused(self):
        h = self.hub()
        h.write("_build/CHASSIS.md", read(CHASSIS_MD).replace("| `.tbl-wrap` |", "| `.tbl-wrap`, `.glow` |"))
        self.assertRefused(h, "CHASSIS.md names .glow, which chassis.html's CSS doesn't style")

    def test_chassis_md_with_no_table_refused(self):
        h = self.hub()
        h.write("_build/CHASSIS.md", "# CHASSIS\n\nNo table.\n")
        self.assertRefused(h, "no component table")

    def test_only_the_tables_first_column_names_classes(self):
        md = ("## Components\n\n| Class | What it is |\n|---|---|\n| `.a`, `p.b` | uses `.c` |\n\n"
              "## Later\n\n| `.d` | x |\n")
        self.assertEqual(assemble.vocabulary(md), {"a", "b"})

    def test_vocabulary_is_the_component_table(self):
        vocab = assemble.vocabulary(read(CHASSIS_MD))
        for c in ("note", "n", "steps", "callout", "lab", "def", "key", "warn", "example", "wex",
                  "wex-t", "connects", "slink", "xref", "tbl-wrap", "fig-controls", "bx", "accbx",
                  "fill-surf", "dash", "mono", "mut", "sm", "acc", "examnav", "ebody", "efound",
                  "egrid", "eq", "eqh", "edrill"):
            self.assertIn(c, vocab)
        self.assertEqual(vocab - assemble.chassis_classes(read(CHASSIS)), set())
        for c in ("rail", "toc", "active", "figbox", "layout", "wrap"):
            self.assertNotIn(c, vocab)

    def test_chassis_classes_come_from_its_css(self):
        classes = assemble.chassis_classes(filled_chassis())
        for c in ("note", "slink", "xref", "callout", "def", "example", "wex", "warn", "key", "lab",
                  "steps", "connects", "tbl-wrap", "figbox", "bx", "accbx", "examnav", "wex-t"):
            self.assertIn(c, classes)
        self.assertNotIn("fancy", classes)

    def test_fig_marker_with_no_step_through_refused(self):
        h = self.hub()
        h.remove("_build/frag/step-fig-2-walk.html")
        self.assertRefused(h, "FIG marker fig-2-walk left")

    def test_missing_exam_day_map_refused(self):
        h = self.hub()
        h.remove("_build/frag/examnav.html")
        self.assertRefused(h, "frag/examnav.html missing")

    def test_a_refusal_keeps_the_last_good_page(self):
        h = self.hub()
        self.assertEqual(h.run()[0], 0)
        good = h.page()
        h.remove("_build/frag/examnav.html")
        self.assertEqual(h.run()[0], 1)
        self.assertEqual(h.page(), good)

    def test_the_sample_hubs_chassis_is_the_template_filled(self):
        template = re.sub(r"\A<!--.*?-->\n", "", read(CHASSIS), count=1, flags=re.S)
        parts = re.split(r"(\{\{[^}]*\}\})", template)
        pattern = "".join("(.+?)" if i % 2 else re.escape(p) for i, p in enumerate(parts))
        sample = read(os.path.join(SAMPLE, "_build", "chassis.html"))
        m = re.fullmatch(pattern, sample, re.S)
        self.assertTrue(m, "the sample hub's chassis.html drifted from templates/notes-chassis.html")
        self.assertNotIn("{{", sample)
        self.assertEqual(read(os.path.join(SAMPLE, "_build", "CHASSIS.md")), read(CHASSIS_MD))

    def test_the_sample_hub_assembles_with_every_link_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "site")
            shutil.copytree(SAMPLE, root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(assemble.main(["--root", root]), 0, out.getvalue())
            page = os.path.join(root, "_build", "notes.html")
            r = subprocess.run(["python3", "-I", LINKCHECK, "--html", page],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("0 unresolved; 0 duplicate ids", r.stdout)

    @unittest.skipUnless(os.environ.get("EXAM_PREP_PLAYWRIGHT"),
                         "set EXAM_PREP_PLAYWRIGHT (and allow MathJax's and the fonts' hosts) to "
                         "run the browser checks")
    def test_the_sample_page_passes_the_browser_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "site")
            shutil.copytree(SAMPLE, root)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(assemble.main(["--root", root]), 0)
            r = subprocess.run(["node", VERIFY_PAGE, os.path.join(root, "_build", "notes.html"),
                                os.path.join(tmp, "shots"), "--spy",
                                "sec-1-sums,sec-1-rules,sec-2-basics,sec-2-walks", "--steps",
                                os.path.join(root, "_build", "frag", "steps.json")],
                               capture_output=True, text=True, timeout=600)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("ALL CHECKS PASS", r.stdout)
            for mode in ("abc", "acb"):
                self.assertIn(f"step-through #fig-2-walk ({mode}) ok: 2 frames, forward and back", r.stdout)

    def test_no_chassis_is_a_usage_error(self):
        h = self.hub()
        h.remove("_build/chassis.html")
        self.assertEqual(h.run()[0], 2)


if __name__ == "__main__":
    unittest.main()
