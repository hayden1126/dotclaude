"""skills/exam-prep/scripts/assemble.py: the notes page from the chassis and the fragments.

A synthetic hub: the skill's own chassis template with its placeholders filled, its CHASSIS.md, two
notes files, their section fragments, an exam-day map and one step-through figure. The page gets
every piece in its place and one accent rule per section; anything malformed (a placeholder left,
a missing or misnamed fragment, a forbidden tag, attribute or link, a class outside CHASSIS.md's
component table, a TODO-VERIFY, a MathJax macro that makes HTML even split by any tag or
comment, or across a step-through and the text at its marker, a FIG marker inside a tag or code
or with no step-through or outside a section, a name= attribute or an id with no hyphen, a
step-through that isn't one <figure> with its id or is placed other than once, no map) writes nothing and leaves the last good page alone, while escaped markup in a
code block is text and passes. The source key is one last section with a row per code the page
cites (from MANIFEST.md, an uncited row left out; a Made by column only when a cited row has a By
cell; what a source is from Notes, with its file name under it, the file line alone without
them; three columns at most), each citation linked to its row; a code with no
row, an empty citation or one with its own href, a MANIFEST it can't read, or none when the page
cites, is refused. With a practice/cram-order.md, the map gets its cram block (an .ecram of tiers,
rows with #id links and depth labels, the Skip and Out of time lines; no mock line, no Tonight)
and opens; with none, the map stays closed; a cram order failing cram_check (an unknown id among
them), a row with no depth label while others have one or Markdown the map can't render, a
hand-written cram block or an open attribute in examnav.html is refused; a cram order with no label
on any row (written before S33) builds bare, with one WARN naming 10-polish. A citation finds its
row in any case (`Ed` the row ED) and links with the row's spelling. A writer's leftovers in a
fragment (tool-call markup, a rule id such as (FB-123) in prose) are refused by fragment and
line, a bare (S33), (L07) or (K02) warns once each and builds; code, math and a bare (C1) pass. PLAN.md's `- Review view: <N> minutes of reading` keeps
the toggle, `none` or no line strips it and refuses class rv; rv anywhere but a worked example or
a Pitfall directly in its section, rv in a section whose Not on or Unverified banner comes before
its first h3, an unreadable line, and a view over its minutes are refused; the map's cram block
and a section such a banner takes out are left out of the minutes.
A concise box builds and joins the Review view; one before the first h3, after other text, twice
in a subsection, nested, not one list of labelled items, or with a label unknown, repeated or out
of order is refused, as is class rv on it. A slide-image figure has its img/ file embedded as a
data URI; one with no citation in its caption, no alt text, a drawing beside it, a data: or other
src, or a file missing, over IMG_MAX or of the wrong type is refused, and so is an image outside a
section. The chassis has the pinned figure panel (C5): a dialog, an aria-hidden preview.
The skill repo's synthetic sample hub, the source of the chassis's
reference screenshots, is the template filled, links the skill's CHASSIS.md and assembles with
every link resolved; with EXAM_PREP_PLAYWRIGHT set, its page also passes verify_page.mjs, run as a
build runs it, so with the long jump (the one run here or in test_verify_page that keeps it on by
default)."""
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
MANIFEST = """# Source manifest: WID 101 Exam 1

| Doc id | File | Pages | Scope | Answers | Rendered | Notes |
|---|---|---|---|---|---|---|
| D1 | `sources/lectures/d1-widgets.pdf` | 4 | in | no | yes | Lecture 1: widgets |
| HW1 | `sources/homework/hw1.pdf` | 2 | in | no | yes | |
| D9 | `sources/lectures/d9.pdf` | 9 | reserved: Final | no | no | raw copy only, never opened |
"""
NAV = """<details class="examnav"><summary>Exam-day map</summary><div class="ebody">
<p class="efound"><a class="xref" href="#sec-1-basics">§1.1</a></p></div></details>"""
SEC1_MK = SEC1.replace("</section>", '  <h3 id="sec-1-must-know">1.2 Must know</h3>\n  <ul><li>x</li></ul>\n'
                                     "</section>")
RV_PITFALL = '<div class="callout warn rv"><div class="lab">Pitfall</div><p>Overlaps count twice.</p></div>\n'
RV_WEX = ('<details class="callout example wex rv" id="ex-1-w"><summary><span class="lab">Worked example 1.1'
          '</span><span class="wex-t">W</span></summary><p>Setup.</p></details>\n')
CRAM = """# Cram order: Exam 1

The night before Exam 1: 15 minutes in 2 tiers of reading.

**Out of time?** Read only the Must-know lists: [§1](https://notes.example.com/w#sec-1-must-know).

## Tier 1: Gadgets first (10 min)

1. [§2.1 More](https://notes.example.com/w#sec-2-more) (10 min): Use: A walk is **two** steps, \\(a < b\\) & `x<y`.

**Then the mock:** [Mock 1](https://mock.example.com/m1), timed (50 minutes).

## Tier 2: Widgets (5 min)

2. [§1.1 Basics](https://notes.example.com/w#sec-1-basics) (5 min): Know cold: Widgets nest.

**Skip:** nothing.

## Tonight

- Bring a pencil.
"""


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
        self.write("MANIFEST.md", MANIFEST)
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
        self.assertIn(".wrap section.note:nth-of-type(3){", page)  # the source key
        self.assertNotIn("nth-of-type(4)", page)
        self.assertIn(':root[data-theme="dark"] .wrap section.note:nth-of-type(1){--sec-accent:#4cbbda;'
                      '--sec-accent-hl:color-mix(in srgb,#4cbbda 26%,transparent)}', page)
        size = os.path.getsize(os.path.join(h.root, "_build", "notes.html"))
        self.assertIn(f"({size:,} bytes)", out)  # bytes, not characters: the page holds a §

    def test_the_source_key_has_a_row_per_cited_code_and_every_citation_links_to_it(self):
        h = self.hub(sections={1: SEC1, 2: SEC2.replace("<ol", '<p>Try it <a class="slink">HW1 Q2c</a>.</p>\n  <ol')})
        h.write("_build/frag/examnav.html", NAV.replace("</p></div>", ' <a class="slink">D1 p.3</a></p></div>'))
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        page = h.page()
        key = page[page.index('<section class="note" id="sec-3">'):]
        self.assertGreater(page.index('id="sec-3"'), page.index('id="sec-2"'))
        self.assertIn('<h2><span class="n">§3</span> Source key</h2>', key)
        # One row per cited code, in MANIFEST's order: Notes, or a blank cell when Notes is
        # empty, never the Scope. D9, reserved and cited nowhere, never appears. This MANIFEST has
        # no By column (the older form), so the key has no Made by column.
        self.assertEqual(re.findall(r'<tr id="([^"]+)">', key), ["src-D1", "src-HW1"])
        self.assertIn('<tr id="src-D1"><td><code>D1</code></td><td>Lecture 1: widgets<br>'
                      '<span class="mut sm">d1-widgets.pdf</span></td></tr>', key)
        # Empty Notes: the file line alone.
        self.assertIn('<tr id="src-HW1"><td><code>HW1</code></td><td><span class="mut sm">hw1.pdf</span></td></tr>', key)
        # Two columns here, three at most: the file sits under what it is.
        self.assertIn("<thead><tr><th>Code</th><th>What it is</th></tr></thead>", key)
        self.assertNotIn("Made by", key)
        self.assertNotIn("D9", page)
        self.assertIn('<a class="slink" href="#src-D1" title="D1: d1-widgets.pdf, Lecture 1: widgets">D1 p.2</a>', page)
        self.assertIn('<a class="slink" href="#src-D1" title="D1: d1-widgets.pdf, Lecture 1: widgets">D1 p.3</a>', page)
        self.assertIn('<a class="slink" href="#src-HW1" title="HW1: hw1.pdf">HW1 Q2c</a>', page)
        self.assertNotIn('<a class="slink">', page)

    def test_a_by_column_adds_made_by_to_the_key(self):
        cites = SEC2.replace("<ol", '<p>Try it <a class="slink">HW1 Q2c</a>.</p>\n  <ol')
        by = MANIFEST.replace("| Answers | Rendered | Notes |", "| Answers | By | Rendered | Notes |")
        by = by.replace("|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|")
        by = by.replace("| 4 | in | no | yes |", "| 4 | in | no | staff | yes |")
        by = by.replace("| 2 | in | no | yes |", "| 2 | in | no | | yes |")
        by = by.replace("| 9 | reserved: Final | no | no |", "| 9 | reserved: Final | no | textbook | no |")
        h = self.hub(sections={1: SEC1, 2: cites})
        h.write("MANIFEST.md", by)
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        page = h.page()
        key = page[page.index('<section class="note" id="sec-3">'):]
        self.assertIn("<thead><tr><th>Code</th><th>What it is</th><th>Made by</th></tr></thead>", key)
        self.assertIn("what it is and its file, and who made it.", key)
        self.assertIn('<tr id="src-D1"><td><code>D1</code></td><td>Lecture 1: widgets<br>'
                      '<span class="mut sm">d1-widgets.pdf</span></td><td>staff</td></tr>', key)
        # A cited row with an empty By cell gets an empty cell; an empty Notes cell stays blank.
        self.assertIn('<tr id="src-HW1"><td><code>HW1</code></td><td><span class="mut sm">hw1.pdf</span></td>'
                      '<td></td></tr>', key)
        self.assertIn('title="D1: d1-widgets.pdf, Lecture 1: widgets, by staff">D1 p.2</a>', page)
        # A By cell only on an uncited row (D9) adds no column.
        h = self.hub(sections={1: SEC1, 2: cites})
        h.write("MANIFEST.md", by.replace("| no | staff | yes |", "| no | | yes |"))
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Made by", h.page())

    def test_a_remark_after_a_semicolon_in_notes_stays_off_the_key(self):
        # Notes is `<what it is>[; <remark>]`: the key and the title show what it is alone.
        cites = SEC2.replace("<ol", '<p>Try it <a class="slink">HW1 Q2c</a>.</p>\n  <ol')
        h = self.hub(sections={1: SEC1, 2: cites})
        h.write("MANIFEST.md", MANIFEST.replace("| Lecture 1: widgets |",
                                                "| Lecture 1: widgets; through slide 9, the rest is Exam 2 |")
                .replace("| 2 | in | no | yes | |", "| 2 | in | no | yes | ; added late |"))
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        page = h.page()
        self.assertNotIn("the rest is Exam 2", page)
        self.assertNotIn("added late", page)
        self.assertIn('<tr id="src-D1"><td><code>D1</code></td><td>Lecture 1: widgets<br>', page)
        self.assertIn('title="D1: d1-widgets.pdf, Lecture 1: widgets">D1 p.2</a>', page)
        # A remark with no what it is before it leaves the file line alone.
        self.assertIn('<tr id="src-HW1"><td><code>HW1</code></td><td><span class="mut sm">hw1.pdf</span></td></tr>', page)

    def test_a_citation_whose_code_has_no_manifest_row_refused(self):
        self.assertRefused(self.in_sec1('<p>See <a class="slink">X7 p.1</a>.</p>'),
                           "frag/sec1.html (§1): citation `X7 p.1` names X7, which has no row in MANIFEST.md")
        h = self.hub()
        h.write("_build/frag/step-fig-2-walk.html", STEP.replace("</figure>", '<p><a class="slink">Q1 p.1</a></p></figure>'))
        self.assertRefused(h, "frag/step-fig-2-walk.html: citation `Q1 p.1` names Q1")

    def test_a_citation_code_matches_its_row_in_any_case(self):
        # Notes write a forum citation `Ed #12`; MANIFEST's row is ED. The link and the key's row
        # take the row's spelling, so they meet.
        h = self.in_sec1('<p>Asked on the forum <a class="slink">Ed #12</a>.</p>')
        h.write("MANIFEST.md", MANIFEST + "| ED | `sources/forum/posts.md` | n/a | in | no | n/a | Forum posts |\n")
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        page = h.page()
        self.assertIn('<a class="slink" href="#src-ED" title="ED: posts.md, Forum posts">Ed #12</a>', page)
        self.assertIn('<tr id="src-ED"><td><code>ED</code></td>', page)
        self.assertNotIn("src-Ed", page)
        # Two rows one case apart are one code twice.
        h = self.hub()
        h.write("MANIFEST.md", MANIFEST + "| ED | `a.md` | n/a | in | no | n/a | |\n| Ed | `b.md` | n/a | in | no | n/a | |\n")
        self.assertRefused(h, "MANIFEST.md: two rows for Ed (and ED: a citation's code matches a row in any case)")

    def test_a_citation_with_no_text_or_an_href_of_its_own_refused(self):
        self.assertRefused(self.in_sec1('<p><a class="slink"> </a></p>'), "an empty citation")
        self.assertRefused(self.in_sec1('<p><a class="slink" href="#sec-1">D1 p.2</a></p>'),
                           "citation `D1 p.2` has an href of its own")

    def test_the_source_key_needs_a_manifest_only_when_the_page_cites(self):
        h = self.hub()
        h.remove("MANIFEST.md")
        self.assertRefused(h, "MANIFEST.md missing: the page cites 1 codes")
        h = self.hub(sections={1: SEC1.replace('<a class="slink">D1 p.2</a>', ""), 2: SEC2})
        h.remove("MANIFEST.md")
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Source key", h.page())
        self.assertNotIn("nth-of-type(3)", h.page())

    def test_a_manifest_it_cant_read_refused(self):
        for text, needle in (("| Doc id | Scope |\n|---|---|\n| D1 | in |\n", "the table has no File column"),
                             ("No table.\n", "has no table"),
                             (MANIFEST + "| D1 | `x.pdf` | 1 | in | no | yes | |\n", "two rows for D1")):
            with self.subTest(needle=needle):
                h = self.hub()
                h.write("MANIFEST.md", text)
                self.assertRefused(h, f"MANIFEST.md: {needle}")

    def test_the_source_keys_text_is_checked_like_a_fragment(self):
        h = self.hub()
        h.write("MANIFEST.md", MANIFEST.replace("Lecture 1: widgets", "\\(\\class{rail}{a}\\)"))
        self.assertRefused(h, "the source key (from MANIFEST.md): MathJax macros that make HTML: \\class")
        h = self.hub()
        h.write("MANIFEST.md", MANIFEST.replace("Lecture 1: widgets", '<img src=x onerror="alert(1)">'))
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", h.page())

    def test_a_codes_row_id_is_one_token_and_distinct(self):
        self.assertEqual(assemble.source_id("D5"), "src-D5")
        self.assertEqual(assemble.source_id("HW1.S"), "src-HW1_2e_S")
        self.assertNotEqual(assemble.source_id("A_1"), assemble.source_id("A-1"))
        self.assertEqual(assemble.source_id("A 1"), "src-A_20_1")

    def test_accents_cycle_past_seven_sections(self):
        css = assemble.accents(9)
        self.assertIn("nth-of-type(8){--sec-accent:#0b6e8f", css)
        self.assertIn("nth-of-type(9){--sec-accent:#277a4d", css)
        self.assertEqual(css.count('[data-theme="dark"] .wrap'), 9)
        self.assertEqual(css.count(':root:not([data-theme="light"])'), 9)

    def test_every_dark_section_rule_sets_its_own_highlight(self):
        # A dark rule with no --sec-accent-hl kept the light band, which all but vanishes on dark.
        css = assemble.accents(8)
        dark = [ln for ln in css.splitlines() if '[data-theme="dark"]' in ln or ':root:not([data-theme="light"])' in ln]
        self.assertEqual(len(dark), 16)
        for ln in dark:
            self.assertIn("--sec-accent-hl:", ln)
        # Derived from the hue's own dark accent where the table gives none; kept where it does.
        self.assertIn("nth-of-type(1){--sec-accent:#4cbbda;--sec-accent-hl:color-mix(in srgb,#4cbbda 26%,transparent)}", css)
        self.assertIn("nth-of-type(2){--sec-accent:#5fc088;--sec-accent-hl:rgba(95,192,136,.20)}", css)

    def built_page(self):
        h = self.hub()
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        return h.page()

    def test_the_page_themes_its_scrollbars_with_an_opaque_track(self):
        # C2: a transparent page track shows white inside a light-scheme parent frame.
        page = self.built_page()
        css = re.sub(r"/\*.*?\*/", "", page.split("</style>")[0], flags=re.S)
        self.assertEqual(len(re.findall(r"--scroll-thumb:#[0-9a-f]{6}", css)), 3, "one per theme block")
        root = re.search(r"(?m)^\s*:root\{(scrollbar-color:[^}]*)\}", css)
        self.assertTrue(root, "no :root{scrollbar-color:...} rule")
        self.assertIn("scrollbar-color:var(--scroll-thumb) var(--bg)", root.group(1))
        self.assertIn("background:var(--bg)", root.group(1))
        self.assertIn(".rail{scrollbar-color:var(--scroll-thumb) transparent}", css)

    def test_the_theme_toggle_is_a_fixed_icon_with_no_words(self):
        # C3: no worded button at the rail's foot; a fixed icon top right on desktop, the top bar's
        # icon on phones, and a right gutter so text never runs under it.
        page = self.built_page()
        rail = re.search(r'<aside class="rail".*?</aside>', page, re.S).group(0)
        self.assertNotIn("<button class=\"themebtn", rail)
        self.assertNotIn("Toggle theme</button>", page)
        for bid in ("themeBtn", "themeBtn2"):
            m = re.search(rf'<button ([^>]*\bid="{bid}"[^>]*)>(.*?)</button>', page, re.S)
            self.assertTrue(m, bid)
            self.assertEqual(re.sub(r"<[^>]*>", "", m.group(2)).strip(), "", f"{bid} has words")
            self.assertIn("<svg", m.group(2))
            for attr in ('aria-label="', 'title="Toggle theme (T)"', 'aria-keyshortcuts="t"'):
                self.assertIn(attr, m.group(1), bid)
        self.assertRegex(page, r'class="themebtn themefab" id="themeBtn2"')
        self.assertIn(".themefab{position:fixed;top:.75rem;right:.75rem", page)
        phone = re.search(r"@media \(max-width:900px\)\{(.*?)\n  \}", page, re.S).group(1)
        self.assertIn(".themefab{display:none}", phone)
        self.assertIn("@media (min-width:901px){.content{padding-right:4rem}}", page)

    def test_full_screen_starts_hidden_and_the_keys_are_guarded(self):
        # C4: shown only where the frame grants it; F and T never with a modifier or while typing.
        page = self.built_page()
        for bid in ("fsBtn", "fsBtn2"):
            m = re.search(rf'<button ([^>]*\bid="{bid}"[^>]*)>', page)
            self.assertTrue(m, bid)
            for attr in (" hidden", 'aria-pressed="false"', 'aria-keyshortcuts="f"', 'title="Full screen (F)"'):
                self.assertIn(attr, m.group(1), bid)
        self.assertIn("document.fullscreenEnabled||document.webkitFullscreenEnabled", page)
        self.assertIn("addEventListener('fullscreenchange',fsSync)", page)
        self.assertIn("if(e.ctrlKey||e.metaKey||e.altKey||e.repeat) return;", page)
        self.assertIn("t.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)", page)

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
                          ('<img ONERROR=x() src="https://x.example/a.png">', "onerror"),
                          # It would stand for document.currentScript, where MathJax's loader
                          # reads the host its components come from (round 9).
                          ('<img name="currentScript" src="https://x.example/es5/a.png">', "name")):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(bad), f"forbidden attributes: {attr}")

    def test_ids_with_no_hyphen_refused(self):
        # window.NotesFig would be the element; rail is the chassis's own (round 9).
        for bad in ('<p id="NotesFig">x</p>', '<h3 id="rail">x</h3>'):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(bad), "ids with no hyphen")
        rc, out = self.in_sec1('<p id="sec-1-extra">x</p>').run()
        self.assertEqual(rc, 0, out)

    def test_links_other_than_ids_http_and_mail_refused(self):
        for bad in ('<a href="javascript:x()">x</a>', '<a href="JavaScript:x()">x</a>',
                    '<a href="&#106;avascript:x()">x</a>', '<a href="java\tscript:x()">x</a>',
                    '<a href="data:text/html,x">x</a>', '<img src="sources/d1.png">',
                    '<svg><use xlink:href="javascript:x()"/></svg>'):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(bad), "links that aren't #id, http(s) or mailto")

    def test_markup_that_ends_code_early_or_hides_in_raw_text_refused(self):
        # A browser ends a <pre> at an ancestor's end tag or a block's start, and reads a
        # raw-text tag's content to its first end tag; html.parser does neither (round 5).
        for bad, needle in (("<div><pre>a</div><p>\\(\\style{color:red}{x}\\)</p>", "</div> inside <pre>"),
                            ("<ul><li><pre>a<li>\\(\\class{rail}{x}\\)</li></ul>", "<li> inside <pre>"),
                            ('<noscript><a title="</noscript><img src onerror=alert(1)>"></a></noscript>',
                             "forbidden tags: noscript"),
                            ("<textarea>x</textarea>", "forbidden tags: textarea")) + tuple(
                (f"<{t}>x</{t}>", f"forbidden tags: {t}") for t in ("title", "xmp", "noembed", "noframes", "plaintext")):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(bad), needle)
        rc, out = self.in_sec1("<pre><code>a<br/>b <span>c</span> <a href=\"#sec-1\">d</a></code></pre>").run()
        self.assertEqual(rc, 0, out)

    def test_a_tag_left_open_at_a_fragments_end_refused(self):
        # html.parser's close() drops it unread; a browser reads on into the next fragment (round 4).
        for tail in ('<img src onerror=alert(1) a="', "<!-- open"):
            with self.subTest(tail=tail):
                self.assertRefused(self.hub(sections={1: SEC1 + "\n" + tail, 2: SEC2}), "left open at its end")

    def test_markup_a_browser_reads_differently_refused(self):
        for bad in ('<![CDATA[><script>x()</script><p class="rail">]]>',
                    "<!--><script>x()</script>-->", "<!-- a note -->", "<!DOCTYPE html>",
                    "<?php x ?>", "<!-- FIG fig-1-x: a > b -->"):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(bad), "markup a browser reads differently")
        self.assertRefused(self.in_sec1("<!-- FIG fig-1-x: S->A -->"), "a FIG marker with a < or > in its text")
        # A parser without the HTML5 comment rules ends this one at `-- >`, so the code that
        # follows would read as code; the raw count never takes a marker across a > (round 9).
        self.assertEqual(assemble.FIG.findall("<!-- FIG fig-2-x -- ><code> -->\\(x\\)</code>"), [])

    def test_tex_that_makes_html_refused_outside_code(self):
        for bad in ("\\(\\href{javascript:x()}{a}\\)", "\\(\\style{position:fixed}{a}\\)",
                    "\\(\\class{rail}{a}\\)", "\\(\\cssId{sec-1}{a}\\)",
                    '\\(\\mmlToken{mi}[href="javascript:x()"]{a}\\)', "\\(\\require{html}\\)", "\\(\\bbox[position:fixed]{a}\\)",
                    "\\(\\data{part=Q9(a)}{a}\\)",
                    "<code>x</code> then \\(\\href{javascript:x()}{a}\\)",
                    # MathJax reads one string on across <wbr>, <br> and comments (round 6), and a
                    # browser drops a stray end tag or a table tag outside a table (round 7): all
                    # the text outside code is read as one string.
                    "\\(\\cl<wbr>ass{rail}{a}\\)", "\\(\\sty<wbr/>le{position:fixed}{a}\\)",
                    "\\(\\<!-- FIG fig-2-walk: x -->cssId{sec-1}{a}\\)", "\\(\\class<br>{rail}{a}\\)",
                    "\\(\\cl</span>ass{rail}{a}\\)", "\\(\\cl<td>ass{rail}{a}\\)", "\\(\\cl</ x>ass{rail}{a}\\)",
                    "\\(\\cl</p><p>ass{rail}{a}\\)", "\\(\\cl<code>x</code>ass{rail}{a}\\)"):
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

    def test_writer_leftovers_refused_naming_the_fragment_and_line(self):
        # SEC1's </section> is line 6, so what in_sec1 adds sits on line 6.
        tool = "antml" + ":"
        for extra, needle in (
                ("<p>x</invoke></p>", "tool-call markup </invoke>"),
                ('<p><invoke name="w">x</p>', "tool-call markup <invoke>"),
                ("<p>x</content></p>", "tool-call markup </content>"),
                ('<p><parameter name="w">x</p>', "tool-call markup <parameter>"),
                ("<p>x</parameter></p>", "tool-call markup </parameter>"),
                (f"<p><{tool}invoke>x</p>", f"tool-call markup <{tool}invoke>"),
                ("<p>x &lt;/invoke&gt; y</p>", "tool-call markup </invoke>"),
                ('<p>x &lt;parameter name="w"&gt; y</p>', "tool-call markup <parameter"),
                (f"<p>x &lt;/{tool}parameter&gt;</p>", f"tool-call markup </{tool}p"),
                ("<p>Linked, as asked (FB-123).</p>", "a skill rule id (FB-123)"),
                ("<p>Themed, per CHASSIS (C4).</p>", "a skill rule id CHASSIS (C4)"),
                ("<p>Per rule (C2), a fixed icon.</p>", "a skill rule id rule (C2)")):
            with self.subTest(extra=extra):
                self.assertRefused(self.in_sec1(extra), f"frag/sec1.html:6: {needle}")
        h = self.hub()
        h.write("_build/frag/examnav.html", NAV.replace("</p></div>", "</p>\n<p>Read first (FB-7).</p></div>"))
        self.assertRefused(h, "frag/examnav.html:3: a skill rule id (FB-7)")
        h = self.hub()
        h.write("_build/frag/step-fig-2-walk.html", STEP.replace("</figure>", "<p>x</invoke></p></figure>"))
        self.assertRefused(h, "frag/step-fig-2-walk.html:2: tool-call markup </invoke>")

    def test_a_bare_s_l_or_k_id_warns_and_builds(self):
        # A course writes a state (S1), an inductor (L1) or a lecture (L3) so: one WARN per hit,
        # naming fragment and line, and the page is written.
        for extra, needle in (("<p>Know it cold (S33).</p>", "(S33)"),
                              ("<p>One idea per block (L07).</p>", "(L07)"),
                              ("<p>Opens on load (K02).</p>", "(K02)")):
            with self.subTest(extra=extra):
                h = self.in_sec1(extra)
                rc, out = h.run()
                self.assertEqual(rc, 0, out)
                self.assertIsNotNone(h.page())
                warns = [line for line in out.splitlines() if line.startswith("WARN:")]
                self.assertEqual(len(warns), 1, out)
                self.assertIn(f"WARN: frag/sec1.html:6: a skill rule id {needle}, if a writer agent left it", warns[0])
        h = self.hub()
        h.write("_build/frag/examnav.html", NAV.replace("</p></div>", "</p>\n<p>Read (S7), then (L3).</p></div>"))
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        warns = [line for line in out.splitlines() if line.startswith("WARN:")]
        self.assertEqual(len(warns), 2, out)
        self.assertIn("WARN: frag/examnav.html:3: a skill rule id (S7)", warns[0])
        self.assertIn("WARN: frag/examnav.html:3: a skill rule id (L3)", warns[1])

    def test_code_math_and_circuit_labels_are_no_leftovers(self):
        # A course can write (C1) for a capacitor or a case, and anything at all in code or math.
        h = self.in_sec1('<p>The capacitor (C1) charges, case (C2) holds, \\(f(S1) = g(L2)\\) and</p>\n'
                         '<p>\\[ (K02) + (FB-1) \\] and <code>(S33) &lt;/invoke&gt;</code>, as cited '
                         '(<a class="slink">D1 p.2</a>).</p>\n'
                         '<pre><code>(L07) &lt;parameter name="x"&gt; (FB-123)</code></pre>')
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("WARN", out)

    def test_tables_nest_strictly(self):
        # A browser moves text or a tag directly inside a table or a row out in front of the
        # table (foster parenting), which can join a macro the check read apart (round 8).
        for bad, needle in (("<div>\\(\\cl<table><tr><td>x</td>ass{rail}{a}\\)</tr></table></div>",
                             "text directly inside <tr>"),
                            ("<table><tbody><span>x</span></tbody></table>", "<span> directly inside <tbody>"),
                            ("<p>a<td>b</td></p>", "<td> outside a <tr>"),
                            ("<table><tr><td>x</tr></table>", "</tr> where <td> is open"),
                            ("<table><tr><td>x</td></tr>", "<table> never closed")):
            with self.subTest(bad=bad):
                self.assertRefused(self.in_sec1(bad), needle)
        rc, out = self.in_sec1('<div class="tbl-wrap"><table><colgroup><col/></colgroup><thead><tr><th>a</th></tr></thead>'
                               '<tbody><tr><td>1 <code>x</code></td></tr></tbody></table></div>').run()
        self.assertEqual(rc, 0, out)

    def test_text_at_a_fragments_end_is_checked_too(self):
        h = self.hub()
        h.write("_build/frag/examnav.html", NAV + "\\(\\class{rail}{a}\\)")
        self.assertRefused(h, "frag/examnav.html: MathJax macros that make HTML: \\class")

    def test_a_step_through_is_one_figure(self):
        # Spliced in at a marker mid-text, a step file's text would join the text beside it
        # into one MathJax string the checks read apart (round 6).
        marker = "<!-- FIG fig-2-walk: a walk through the gadget -->"
        for step in ("ass", STEP + "x", "<p>" + STEP + "</p>", STEP.replace('id="fig-2-walk"', 'id="fig-2-other"'),
                     STEP + STEP, STEP + "\\(\\cl</figure>"):
            with self.subTest(step=step):
                h = self.hub(sections={1: SEC1, 2: SEC2.replace(marker, "<p>\\(\\cl" + marker + "{rail}{a}\\)</p>")})
                h.write("_build/frag/step-fig-2-walk.html", step)
                self.assertRefused(h, 'frag/step-fig-2-walk.html: not one <figure id="fig-2-walk">')

    def test_a_step_throughs_text_and_its_markers_are_checked_together(self):
        # Each passes alone; on the page the figure's last text and the text after its marker
        # may join (round 7).
        marker = "<!-- FIG fig-2-walk: a walk through the gadget -->"
        h = self.hub(sections={1: SEC1, 2: SEC2.replace(marker, "<p>" + marker + "ass{rail}{a}\\)</p>")})
        h.write("_build/frag/step-fig-2-walk.html", STEP.replace("</figure>", "<p>\\(\\cl</p></figure>"))
        self.assertRefused(h, "the sections as assembled, step-throughs in place: MathJax macros that make HTML: \\class")

    def test_a_fig_marker_inside_a_tag_or_code_refused(self):
        marker = "<!-- FIG fig-2-walk: a walk through the gadget -->"
        for where in (f'<span title="{marker}">x</span>', f"<pre><code>{marker}</code></pre>"):
            with self.subTest(where=where):
                h = self.hub(sections={1: SEC1, 2: SEC2.replace(marker, where)})
                self.assertRefused(h, "frag/sec2.html: a FIG marker inside a tag, an attribute or code")

    def test_a_fig_marker_outside_a_section_refused(self):
        # Only a section's markers are put in place: one in the map or a step-through stays a
        # comment on the page (round 9).
        marker = "<!-- FIG fig-2-walk: a walk through the gadget -->"
        h = self.hub()
        h.write("_build/frag/examnav.html", NAV.replace("</div>", marker + "</div>", 1))
        self.assertRefused(h, "frag/examnav.html: a FIG marker, which only a section's text holds")
        h = self.hub()
        h.write("_build/frag/step-fig-2-walk.html", STEP.replace("</figure>", "<!-- FIG fig-2-other -->\n</figure>"))
        self.assertRefused(h, "frag/step-fig-2-walk.html: a FIG marker, which only a section's text holds")

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
            self.assertIn("0 unresolved; 0 duplicate ids; 0 citations with no in-page link", r.stdout)
            # The key lists exactly the codes the fragments cite, and each citation links to it.
            frag = os.path.join(SAMPLE, "_build", "frag")
            frags = "".join(read(os.path.join(frag, n)) for n in os.listdir(frag) if n.endswith(".html"))
            cited = {c.split()[0] for c in re.findall(r'<a class="slink">([^<]+)</a>', frags)}
            built = read(page)
            self.assertEqual(cited, {"D1", "D2", "HW1", "W1"})
            self.assertEqual(sorted(re.findall(r'<tr id="src-([^"]+)">', built)), sorted(cited))
            self.assertEqual(len(re.findall(r'<a class="slink" href="#src-', built)),
                             frags.count('<a class="slink">'))

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
            # No flag: the long jump runs by default, in Chromium at least.
            self.assertIn("[long jump]", r.stdout)
            self.assertIn("long jump chromium 1280px bottom->first ok: #sec-1", r.stdout)
            self.assertNotIn("--no-long-jump", r.stdout)

    # ---- the cram block (K02) and the Review view ----

    def cram_hub(self, cram=CRAM, plan=None, sec1=None):
        h = self.hub(sections={1: SEC1_MK if sec1 is None else sec1, 2: SEC2})
        os.makedirs(os.path.join(h.root, "practice"))
        if cram is not None:
            h.write("practice/cram-order.md", cram)
        if plan is not None:
            h.write("PLAN.md", plan)
        return h

    def test_the_cram_block_is_rendered_from_the_cram_order_and_opens_the_map(self):
        h = self.cram_hub()
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        page = h.page()
        self.assertIn('<details class="examnav" open>', page)
        self.assertEqual(page.count('class="ecram"'), 1)
        self.assertLess(page.index('class="ecram"'), page.index('class="efound"'))
        self.assertIn('<div class="eqh">Tier 1: Gadgets first (10 min)</div>', page)
        self.assertIn('<div class="eqh">Tier 2: Widgets (5 min)</div>', page)
        self.assertIn('<li><b>A walk is <strong>two</strong> steps, \\(a &lt; b\\) &amp; <code>x&lt;y</code></b> → '
                      '<a class="xref" href="#sec-2-more">§2.1 More</a> (Use)</li>', page)
        self.assertIn('<a class="xref" href="#sec-1-basics">§1.1 Basics</a> (Know cold)</li>', page)
        self.assertIn('<p class="edrill"><strong>Skip:</strong> nothing. <strong>Out of time?</strong> Read only '
                      'the Must-know lists: <a class="xref" href="#sec-1-must-know">§1</a>.</p>', page)
        block = page[page.index('class="ecram"'):page.index('class="efound"')]
        self.assertNotIn("notes.example.com", block)
        self.assertNotIn("mock", block.lower())
        self.assertNotIn("Bring", block)  # ## Tonight stays out

    def test_no_cram_order_means_no_cram_block_and_a_closed_map(self):
        h = self.cram_hub(cram=None)
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        self.assertIn('<details class="examnav">', h.page())
        self.assertNotIn('class="ecram"', h.page())

    def test_a_cram_row_with_an_unknown_id_fails(self):
        self.assertRefused(self.cram_hub(CRAM.replace("#sec-1-basics", "#sec-9-gone")),
                           "practice/cram-order.md:15: #sec-9-gone isn't an id in the notes page")

    def test_a_cram_order_that_fails_its_check_fails_the_build(self):
        self.assertRefused(self.cram_hub(CRAM.replace("(10 min)", "(12 min)", 1)),
                           "the tier says 12 min, its rows sum to 10")

    def test_cram_markdown_the_map_cant_render_refused(self):
        for thing, needle in (("an *italic* word", "`*` in"), ("a <b>raw</b> tag", "`<b` in"),
                              ("a _stressed_ word", "`_` in"), ("a [D1 p.2] cite", "`[` in")):
            with self.subTest(thing=thing):
                self.assertRefused(self.cram_hub(CRAM.replace("Know cold: Widgets nest", f"Know cold: {thing}")),
                                   needle)

    def test_a_cram_row_with_no_depth_label_refused(self):
        self.assertRefused(self.cram_hub(CRAM.replace("Know cold: Widgets nest", "Widgets nest")),
                           "practice/cram-order.md:15: no depth label")

    def test_a_cram_rows_needs_show_after_it_as_links(self):
        # K52: row 2 needs row 1's section; the map shows it after the row, linked, and the
        # Read already line stays out of the map.
        h = self.cram_hub(CRAM.replace("Widgets nest.", "Widgets nest. needs: [§2.1](https://notes.example.com/w#sec-2-more)")
                          .replace("\n\n## Tier 1:", "\n\n**Read already:** nothing.\n\n## Tier 1:"))
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        page = h.page()
        self.assertIn('<li><b>Widgets nest</b> → <a class="xref" href="#sec-1-basics">§1.1 Basics</a> (Know cold) · '
                      'needs <a class="xref" href="#sec-2-more">§2.1</a></li>', page)
        self.assertIn('<a class="xref" href="#sec-2-more">§2.1 More</a> (Use)</li>', page)
        self.assertNotIn("Read already", page)

    def test_a_cram_row_whose_need_comes_later_fails_the_build(self):
        self.assertRefused(self.cram_hub(CRAM.replace(
            "`x<y`.", "`x<y`. needs: [§1.1](https://notes.example.com/w#sec-1-basics)")),
            "practice/cram-order.md:9: needs §1.1 (#sec-1-basics), which no earlier row reads")

    def test_a_cram_order_written_before_s33_builds_without_labels_and_warns_once(self):
        # No row carries a depth label: the hub predates S33, and a rebuild mid-exam must not be
        # refused for it. The map shows the rows bare and one WARN names the pass that adds them.
        pre = CRAM.replace("(10 min): Use: ", "(10 min): ").replace("(5 min): Know cold: ", "(5 min): ")
        h = self.cram_hub(pre)
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        warns = [line for line in out.splitlines() if "WARN" in line]
        self.assertEqual(len(warns), 1, out)
        self.assertIn("WARN: practice/cram-order.md: no row carries an S33 depth label", warns[0])
        self.assertIn("10-polish", warns[0])
        page = h.page()
        self.assertIn('<li><b>Widgets nest</b> → <a class="xref" href="#sec-1-basics">§1.1 Basics</a></li>', page)
        self.assertIn('<a class="xref" href="#sec-2-more">§2.1 More</a></li>', page)
        # A labelled order builds with no WARN.
        rc, out = self.cram_hub().run()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("WARN", out)

    def test_a_half_labelled_cram_order_still_needs_every_label(self):
        h = self.cram_hub(CRAM.replace("(5 min): Know cold: ", "(5 min): "))
        self.assertRefused(h, "practice/cram-order.md:15: no depth label")
        self.assertNotIn("WARN", h.run()[1])

    def test_a_hand_written_cram_block_in_the_map_refused(self):
        for nav, needle in (
                (NAV.replace("</div></details>", '<div class="egrid"><div class="eq"><div class="eqh">Tier 1: '
                             'Rules (5 min)</div><ul><li>x</li></ul></div></div></div></details>'),
                 "a hand-written cram tier (Tier 1: Rules (5 min))"),
                (NAV.replace('<p class="efound">', '<div class="ecram"></div><p class="efound">'),
                 "a hand-written cram block (.ecram)"),
                (NAV.replace("</p></div>", " <strong>Out of time?</strong> Read §1.</p></div>"),
                 "a hand-written Out of time? line")):
            with self.subTest(needle=needle):
                h = self.hub()
                h.write("_build/frag/examnav.html", nav)
                self.assertRefused(h, needle + ": assemble.py renders the cram block from practice/cram-order.md")

    def test_an_open_map_refused(self):
        h = self.hub()
        h.write("_build/frag/examnav.html", NAV.replace('<details class="examnav">', '<details class="examnav" open>'))
        self.assertRefused(h, "frag/examnav.html: an open attribute")

    def test_minutes_keep_the_toggle_and_none_strips_it(self):
        for plan, kept in (("- Review view: 5 minutes of reading\n", True),
                           ("- Review view: none: a sheet is allowed\n", False), (None, False)):
            with self.subTest(plan=plan):
                h = self.cram_hub(plan=plan, cram=None)
                rc, out = h.run()
                self.assertEqual(rc, 0, out)
                self.assertEqual('class="viewtog"' in h.page(), kept)
                self.assertEqual("Review view: only each subsection's concise box" in h.page(), kept)
                self.assertNotIn("REVIEW TOGGLE", h.page())

    def test_rv_with_no_review_view_refused(self):
        sec1 = SEC1_MK.replace('<div class="callout def">', RV_PITFALL + '<div class="callout def">')
        for plan in ("- Review view: none: the student declined it\n", "# Plan\n", None):
            with self.subTest(plan=plan):
                self.assertRefused(self.cram_hub(plan=plan, sec1=sec1, cram=None),
                                   "class rv on the page, and PLAN.md has no `- Review view: <N> minutes")

    def test_a_review_view_line_it_cant_read_refused(self):
        self.assertRefused(self.cram_hub(plan="- Review view: about ten minutes\n", cram=None),
                           "PLAN.md: `- Review view: about ten minutes` is neither")

    def test_rv_only_on_a_worked_example_or_a_pitfall_in_its_section(self):
        plan = "- Review view: 5 minutes of reading\n"
        ok = SEC1_MK.replace('<div class="callout def">', RV_PITFALL + RV_WEX + '<div class="callout def">')
        h = self.cram_hub(plan=plan, sec1=ok, cram=None)
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        for bad, needle in (
                (RV_PITFALL.replace(">Pitfall<", ">Not on Exam 1<"), 'class rv on a "Not on Exam 1" callout'),
                (RV_PITFALL.replace(">Pitfall<", ">Unverified<"), 'class rv on a "Unverified" callout'),
                ('<p class="rv">x</p>', 'class rv on <p class="rv">'),
                ("<ul><li>" + RV_PITFALL + "</li></ul>", "an rv block inside <li>")):
            with self.subTest(needle=needle):
                sec1 = SEC1_MK.replace('<div class="callout def">', bad + '<div class="callout def">')
                self.assertRefused(self.cram_hub(plan=plan, sec1=sec1, cram=None), "frag/sec1.html: " + needle)

    def test_a_review_view_over_its_minutes_fails(self):
        long = RV_PITFALL.replace("Overlaps count twice.", "word " * 400)
        sec1 = SEC1_MK.replace('<div class="callout def">', long + '<div class="callout def">')
        self.assertRefused(self.cram_hub(plan="- Review view: 2 minutes of reading\n", sec1=sec1, cram=None),
                           f"words at {assemble.READING_RATE} a minute), over PLAN.md's 2")
        h = self.cram_hub(plan="- Review view: 4 minutes of reading\n", sec1=sec1, cram=None)
        rc, out = h.run()
        self.assertEqual(rc, 0, out)

    def test_over_its_minutes_the_remedy_is_untagging_then_new_minutes(self):
        # 07-cheatsheet's "Tag the review": untag while a tag is left; with none, ask for minutes.
        plan = "- Review view: 2 minutes of reading\n"
        long = RV_PITFALL.replace("Overlaps count twice.", "word " * 400)
        tagged = SEC1_MK.replace('<div class="callout def">', long + '<div class="callout def">')
        self.assertRefused(self.cram_hub(plan=plan, sec1=tagged, cram=None),
                           "over PLAN.md's 2: untag rv blocks from the last ranked subsection up")
        untagged = SEC1_MK.replace("<ul><li>x</li></ul>", "<ul><li>" + "word " * 400 + "</li></ul>")
        self.assertIn("word " * 400, untagged)
        self.assertRefused(self.cram_hub(plan=plan, sec1=untagged, cram=None),
                           "over PLAN.md's 2: no rv tag is left to untag, so the main session asks the "
                           "student for new minutes on PLAN.md's `- Review view:` line and logs them in "
                           "STATUS, or, when the student can't be asked, sets them and logs it")

    def banner_sec1(self, label, must="x"):
        """SEC1_MK with a label banner before its first h3, and its Must-know list holding must."""
        return SEC1_MK.replace('<h3 id="sec-1-basics">', f'<div class="callout warn"><div class="lab">{label}'
                               '</div><p>Kept for a later exam.</p></div>\n  <h3 id="sec-1-basics">') \
            .replace("<ul><li>x</li></ul>", f"<ul><li>{must}</li></ul>")

    def test_rv_in_a_section_a_banner_takes_out_refused(self):
        plan = "- Review view: 5 minutes of reading\n"
        for label in ("Not on Exam 1", "Unverified"):
            with self.subTest(label=label):
                sec1 = self.banner_sec1(label).replace('<div class="callout def">', RV_PITFALL + '<div class="callout def">')
                self.assertRefused(self.cram_hub(plan=plan, sec1=sec1, cram=None),
                                   "frag/sec1.html: an rv block in §1, which a Not on <exam> or Unverified banner")
        # A banner after the first h3 (a subsection cut, a short unverified subsection) leaves the
        # section in the view.
        late = SEC1_MK.replace('<div class="callout def">', RV_PITFALL + '<div class="callout warn"><div class="lab">'
                               'Unverified</div><p>y</p></div><div class="callout def">')
        h = self.cram_hub(plan=plan, sec1=late, cram=None)
        rc, out = h.run()
        self.assertEqual(rc, 0, out)

    def test_a_section_a_banner_takes_out_is_left_out_of_the_minutes(self):
        long = "word " * 400
        for label, ok in (("Unverified", True), ("Not on Exam 1", True), ("Pitfall", False)):
            with self.subTest(label=label):
                h = self.cram_hub(plan="- Review view: 2 minutes of reading\n", sec1=self.banner_sec1(label, long),
                                  cram=None)
                rc, out = h.run()
                self.assertEqual(rc == 0, ok, out)

    def test_the_cram_block_is_left_out_of_the_review_views_minutes(self):
        # A page tagged up to its minutes still builds once 08 step 7 writes the cram order.
        long = RV_PITFALL.replace("Overlaps count twice.", "word " * 400)
        sec1 = SEC1_MK.replace('<div class="callout def">', long + '<div class="callout def">')
        cram = CRAM.replace("Know cold: Widgets nest", "Know cold: " + "nest " * 300)
        for c in (None, cram):
            with self.subTest(cram=c is not None):
                h = self.cram_hub(plan="- Review view: 4 minutes of reading\n", sec1=sec1, cram=c)
                rc, out = h.run()
                self.assertEqual(rc, 0, out)
                self.assertEqual('class="ecram"' in h.page(), c is not None)

    def test_reading_words_counts_math_by_its_symbols(self):
        self.assertEqual(assemble.reading_words(r"Sum \(\frac{n(n+1)}{2}\) now"), 6)
        self.assertEqual(assemble.reading_words(r"\[ x \le 10 \] - a"), 3)

    # ---- the concise box, the slide-image figure and the pinned figure panel (C5, C6) ----

    BOX = ('<div class="concise"><ul>\n<li><strong>Rule:</strong> widgets nest \\(n\\) deep.</li>\n'
           '<li><strong>Trap:</strong> a gadget is no widget.</li>\n</ul></div>\n')

    def boxed(self, box=None, after='<h3 id="sec-1-basics">1.1 Basics</h3>\n'):
        return SEC1.replace(after, after + "  " + (self.BOX if box is None else box), 1)

    def test_a_concise_box_builds_and_joins_the_review_view(self):
        depth = '<p class="connects"><strong>Depth:</strong> Use <a class="slink">D1 p.2</a>.</p>\n'
        for sec1 in (self.boxed(), self.boxed(depth + self.BOX)):
            h = self.cram_hub(plan="- Review view: 5 minutes of reading\n", sec1=sec1, cram=None)
            rc, out = h.run()
            self.assertEqual(rc, 0, out)
            self.assertIn('<div class="concise"><ul>', h.page())
        section = assemble.Tree(self.boxed()).root["kids"][0]
        shown = [e["tag"] + "." + e["attrs"].get("class", "") for e in assemble.review_parts(section)]
        self.assertEqual(shown, ["h2.", "h3.", "div.concise"])

    def test_a_concise_box_out_of_form_refused(self):
        li = '<li><strong>{}:</strong> x.</li>'
        bad = [
            (SEC1.replace('<h3 id="sec-1-basics">', self.BOX + '<h3 id="sec-1-basics">'),
             "a concise box before the section's first h3"),
            (self.boxed(after='<div class="callout def"><div class="lab">Definition</div><p>x</p></div>\n'),
             "a concise box after other text under sec-1-basics"),
            (self.boxed(self.BOX + self.BOX), "a concise box twice under sec-1-basics"),
            (self.boxed('<div class="callout key concise"><div class="lab">Key rule</div></div>\n'),
             "that isn't one <ul> of labelled items"),
            (self.boxed('<div class="concise"><ul>' + li.format("Rule") + '</ul><p>x</p></div>\n'),
             "that isn't one <ul> of labelled items"),
            (self.boxed('<div class="concise"><ul><li>Rule: x</li></ul></div>\n'),
             "an item that doesn't open with <strong>Label:</strong>"),
            (self.boxed('<div class="concise"><ul>' + li.format("Idea") + '</ul></div>\n'),
             "an item that doesn't open with <strong>Label:</strong>"),
            (self.boxed('<div class="concise"><ul>' + li.format("Trap") + li.format("Rule") + '</ul></div>\n'),
             "labelled Trap, Rule: each label at most once, in the order Rule, Why, Steps"),
            (self.boxed('<div class="concise"><ul>' + li.format("Why") + li.format("Why") + '</ul></div>\n'),
             "labelled Why, Why"),
            (self.boxed('<div class="concise"><ul></ul></div>\n'), "with no items"),
            (self.boxed('<ul><li><div class="concise"><ul>' + li.format("Rule") + '</ul></div></li></ul>\n'),
             "a concise box inside <li>"),
            (self.boxed('<p class="concise">x</p>\n'), 'a concise box on <p>'),
            (self.boxed(self.BOX.replace('class="concise"', 'class="concise rv"')), 'class rv on <div class="concise rv">'),
        ]
        for sec1, needle in bad:
            with self.subTest(needle=needle):
                h = self.cram_hub(plan="- Review view: 5 minutes of reading\n", sec1=sec1, cram=None)
                self.assertRefused(h, needle)

    PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS"
           b"\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\r\xefF\xb8\x00\x00\x00\x00IEND\xaeB`\x82")
    SLIDE = ('<figure id="fig-1-board"><img src="img/fig-1-board.png" alt="A widget board, two rows of parts">\n'
             '<figcaption>Fig 1.1. The board as the slide shows it <a class="slink">D1 p.2</a>.</figcaption></figure>\n')

    def slide_hub(self, fig=None, data=PNG, name="fig-1-board.png"):
        sec1 = SEC1.replace("</section>", (self.SLIDE if fig is None else fig) + "</section>")
        h = self.hub(sections={1: sec1, 2: SEC2})
        os.makedirs(os.path.join(h.root, "_build", "img"))
        if data is not None:
            with open(os.path.join(h.root, "_build", "img", name), "wb") as f:
                f.write(data)
        return h

    def test_a_slide_image_figure_is_embedded_in_the_page(self):
        h = self.slide_hub()
        rc, out = h.run()
        self.assertEqual(rc, 0, out)
        page = h.page()
        self.assertIn('<img src="data:image/png;base64,' + __import__("base64").b64encode(self.PNG).decode(), page)
        self.assertNotIn('src="img/', page)
        self.assertIn('href="#src-D1"', page.split('id="fig-1-board"')[1])

    def test_a_slide_image_src_in_any_spelling_is_embedded(self):
        # A browser takes SRC=, a bare value and blanks around the =; each was once left as a
        # relative link, a broken image on the artifact host.
        b64 = __import__("base64").b64encode(self.PNG).decode()
        for spelling in ('SRC="img/fig-1-board.png"', "src=img/fig-1-board.png", 'src = "img/fig-1-board.png"',
                         "Src='img/fig-1-board.png'"):
            with self.subTest(spelling=spelling):
                h = self.slide_hub(fig=self.SLIDE.replace('src="img/fig-1-board.png"', spelling))
                rc, out = h.run()
                self.assertEqual(rc, 0, out)
                page = h.page()
                self.assertIn('"data:image/png;base64,' + b64 + '"', page)
                self.assertNotIn("img/fig-1-board.png", page)

    def test_embed_images_reads_every_src_spelling(self):
        h = self.slide_hub()
        problems = []
        text = assemble.embed_images("x", '<img SRC="img/fig-1-board.png" alt="a"><img src=img/fig-1-board.png alt=a>',
                                     os.path.join(h.root, "_build", "img"), problems)
        self.assertEqual(problems, [])
        self.assertNotIn("img/", text)
        self.assertEqual(text.count("data:image/png;base64,"), 2)

    def test_an_img_src_left_after_embedding_refused(self):
        # A character reference the parser decodes to img/... that the substitution can't read.
        h = self.slide_hub(fig=self.SLIDE.replace('src="img/fig-1-board.png"', 'src="img/fig-1-board&#46;png"'))
        self.assertRefused(h, "an <img> src 'img/fig-1-board.png' wasn't embedded")

    def test_a_slide_image_figure_out_of_form_refused(self):
        fig = self.SLIDE
        cases = [
            (dict(fig=fig.replace(' <a class="slink">D1 p.2</a>', "")),
             "#fig-1-board, a slide-image figure, has no source citation in its caption"),
            (dict(fig=fig.replace('<figcaption>', '<p><a class="slink">D1 p.2</a></p><figcaption>')
                  .replace(' <a class="slink">D1 p.2</a>.</figcaption>', '.</figcaption>')),
             "has no source citation in its caption"),
            (dict(fig=fig.replace('alt="A widget board, two rows of parts"', 'alt=" "')), "#fig-1-board's <img> has no alt text"),
            (dict(fig=fig.replace(' alt="A widget board, two rows of parts"', '')), "#fig-1-board's <img> has no alt text"),
            (dict(fig='<p><img src="img/fig-1-board.png" alt="x"></p>\n'), "an <img> outside a <figure id=\"fig-...\">"),
            (dict(fig=fig.replace('<figcaption>', '<svg viewBox="0 0 1 1"></svg><figcaption>')),
             "#fig-1-board holds more than its one <img>"),
            (dict(fig=fig.replace('img/fig-1-board.png', 'data:image/png;base64,AAAA')),
             "#fig-1-board's <img> src isn't img/<name>.png"),
            (dict(fig=fig.replace('img/fig-1-board.png', 'img/../notes.png')), "links that aren't #id"),
            (dict(data=None), "img/fig-1-board.png isn't in _build/img/"),
            (dict(data=b"GIF89a" + b"\0" * 20), "img/fig-1-board.png isn't the image/png its name says"),
            (dict(data=self.PNG + b"\0" * assemble.IMG_MAX), "img/fig-1-board.png is over 1,000,000 bytes"),
        ]
        for kw, needle in cases:
            with self.subTest(needle=needle):
                self.assertRefused(self.slide_hub(**kw), needle)

    def test_an_image_outside_a_section_refused(self):
        h = self.slide_hub()
        h.write("_build/frag/examnav.html", NAV.replace("</div></details>", self.SLIDE + "</div></details>"))
        self.assertRefused(h, "frag/examnav.html: an <img>, which only a section's slide-image figure holds")

    def test_the_chassis_escape_closes_the_drawer_alone_and_the_tail_reads_the_foot_padding(self):
        page = read(CHASSIS)
        # The drawer's Escape runs first and marks the key handled; the pinned panel's skips it.
        drawer = page.index("rail.classList.contains('open')){e.preventDefault();closeNav();}")
        panel = page.index("e.key==='Escape'&&!e.defaultPrevented&&!panel.hidden")
        self.assertLess(drawer, panel)
        # fitTail takes the tail out of .wrap's computed foot padding, whose bare part is 8rem in
        # both: the CSS rule and the script's constant move together.
        self.assertIn(".wrap{max-width:var(--maxw);margin:0 auto;padding-block:3rem calc(8rem + var(--tail,0px))}", page)
        self.assertIn("body.figpinned .wrap{padding-bottom:max(50vh,calc(8rem + var(--tail,0px)))}", page)
        self.assertIn("(parseFloat(getComputedStyle(main).paddingBottom)||0)-8*rem)", page)

    def test_the_chassis_pins_a_figure_in_an_accessible_panel(self):
        page = read(CHASSIS)
        panel = re.search(r'<div class="figpin figpanel"[^>]*>', page).group(0)
        for attr in ('role="dialog"', 'aria-label="Pinned figure"', 'tabindex="-1"', "hidden"):
            self.assertIn(attr, panel)
        self.assertRegex(page, r'<div class="figpin figpeek"[^>]*aria-hidden="true"[^>]*hidden>')
        self.assertIn(".figpin[hidden]{display:none}", page)
        # A plain click only, in capture so the Review view's switch sees it handled.
        self.assertIn("e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey", page)
        self.assertIn("},true);", page)
        self.assertIn("if(!reviewOn||e.defaultPrevented) return;", page)
        self.assertIn("e.pointerType!=='mouse'", page)
        phone = re.search(r"@media \(max-width:900px\)\{(.*?)\n  \}", page, re.S).group(1)
        self.assertIn("max-height:45dvh", phone)

    def test_no_chassis_is_a_usage_error(self):
        h = self.hub()
        h.remove("_build/chassis.html")
        self.assertEqual(h.run()[0], 2)


if __name__ == "__main__":
    unittest.main()
