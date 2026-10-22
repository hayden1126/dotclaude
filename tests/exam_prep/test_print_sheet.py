"""skills/exam-prep/scripts/print_sheet.mjs and templates/cheatsheet.html, printed and judged by
check_pdf.py.

The sample sheet is the template filled from tests/exam_prep/fixtures/sheet/ (values.json, then
side1.html and side2.html as the two sides' blocks), as 07-cheatsheet step 3 fills it.

No browser runs in the first group: print_sheet.mjs refuses bad usage (exit 2), and a sheet with
no doctype or with a slot left (exit 1), before it loads Playwright, which here is a fake package
that exits 7 when imported; set notation like {{1}} or {{A}} isn't a slot. The template's slots are exactly the ones the sample fills,
and its classes are exactly 07-cheatsheet's vocabulary table, which the sample keeps to.

With EXAM_PREP_PLAYWRIGHT set, the sample prints from relative paths and passes check_pdf.py, and
so does its A4 form, made as the template's comment says. Fill follows the content (a side ending
in a figure too) and the column count. Broken one way at a time, the sample fails with the
matching message: a side that spills past its last column, a wide element with no text in it, a
table wider than its column (by less than the gap too; a table or pre the columns break apart is
not), SVG text or a superscript below the
floor, a section sign, a remote stylesheet, a portrait @page, a third side, a script, and a sheet
with no .page. It prints from the hub root into cheatsheet/, and runs no inline handler."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "exam-prep")
PRINT_SHEET = os.path.join(SKILL, "scripts", "print_sheet.mjs")
CHECK_PDF = os.path.join(SKILL, "scripts", "check_pdf.py")
TEMPLATE = os.path.join(SKILL, "templates", "cheatsheet.html")
WORKFLOW = os.path.join(SKILL, "workflows", "07-cheatsheet.md")
FIXTURE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "sheet")
NODE = shutil.which("node")
SLOT = re.compile(r"\{\{([^{}\n]+)\}\}")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def sample(edit=None):
    """The template filled from the fixture, its opening comment dropped; edit(text) -> text."""
    text = re.sub(r"<!-- Baseline.*?-->\n", "", read(TEMPLATE), count=1, flags=re.S)
    values = json.loads(read(os.path.join(FIXTURE, "values.json")))
    values["SIDE 1 BLOCKS"] = read(os.path.join(FIXTURE, "side1.html"))
    values["SIDE 2 BLOCKS"] = read(os.path.join(FIXTURE, "side2.html"))
    text = SLOT.sub(lambda m: values[m.group(1)], text)
    return edit(text) if edit else text


def css_classes(text):
    style = re.search(r"<style>(.*?)</style>", text, re.S).group(1)
    style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
    return set(re.findall(r"\.([a-z][\w-]*)", re.sub(r"\{[^{}]*\}", "{}", style)))


def vocabulary():
    """The classes 07-cheatsheet's table lists (`.hue1` to `.hue6` is a range)."""
    out = set()
    for line in read(WORKFLOW).splitlines():
        if not line.startswith("| `"):
            continue
        cell = line.split("|")[1]
        for code in re.findall(r"`([^`]+)`", cell):
            out |= set(re.findall(r"\.([a-z][\w-]*)", code))
        for name, lo, hi in re.findall(r"`\.([a-z]+)(\d)` to `\.\1(\d)`", cell):
            out |= {f"{name}{i}" for i in range(int(lo), int(hi) + 1)}
    return out


class TemplateTest(unittest.TestCase):
    def test_the_sample_fills_every_slot(self):
        slots = set(SLOT.findall(read(TEMPLATE).split("-->", 1)[1]))
        values = set(json.loads(read(os.path.join(FIXTURE, "values.json"))))
        self.assertEqual(slots, values | {"SIDE 1 BLOCKS", "SIDE 2 BLOCKS"})
        self.assertEqual(SLOT.findall(sample()), [])

    def test_the_template_styles_exactly_the_vocabulary(self):
        self.assertEqual(css_classes(read(TEMPLATE)), vocabulary())

    def test_the_sample_keeps_to_the_vocabulary(self):
        used = set()
        for name in ("side1.html", "side2.html"):
            for attr in re.findall(r'class="([^"]+)"', read(os.path.join(FIXTURE, name))):
                used |= set(attr.split())
        self.assertLessEqual(used, vocabulary())

    def test_the_vocabulary_parser(self):
        self.assertIn("hue3", vocabulary())
        self.assertIn("sh", vocabulary())
        self.assertIn("alt", vocabulary())


@unittest.skipUnless(NODE, "node is not on PATH")
class RefusalsTest(unittest.TestCase):
    """Each exits before Playwright loads: the fake package would exit 7."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        fake = os.path.join(self.tmp, "fake-playwright")
        os.mkdir(fake)
        with open(os.path.join(fake, "index.mjs"), "w", encoding="utf-8") as f:
            f.write("console.log('fake playwright');\nprocess.exit(7);\n")
        self.env = {"PATH": os.path.dirname(NODE), "HOME": self.tmp, "EXAM_PREP_PLAYWRIGHT": fake}

    def run_it(self, *args, text=None):
        sheet = os.path.join(self.tmp, "sheet.html")
        if text is not None:
            with open(sheet, "w", encoding="utf-8") as f:
                f.write(text)
        return subprocess.run([NODE, PRINT_SHEET, *args], cwd=self.tmp, env=self.env,
                              capture_output=True, text=True, timeout=60)

    def test_usage(self):
        for args in ([], ["sheet.html"], ["sheet.html", "out.png"], ["nope.html", "out.pdf"],
                     ["sheet.html", "no/such/dir/out.pdf"], ["a", "b", "c"]):
            with self.subTest(args=args):
                r = self.run_it(*args, text=sample())
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("usage:", r.stderr)

    def test_no_doctype(self):
        r = self.run_it("sheet.html", "out.pdf", text=sample().split("\n", 1)[1])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("doesn't start with <!doctype html>", r.stderr)

    def test_a_placeholder_left(self):
        r = self.run_it("sheet.html", "out.pdf", text=sample().replace("GRF101", "{{COURSE}}", 1))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("still holds the slot {{COURSE}}", r.stderr)
        r = self.run_it("sheet.html", "out.pdf", text=read(TEMPLATE))
        self.assertEqual(r.returncode, 1)
        self.assertIn("still holds the slot", r.stderr)

    def test_set_notation_is_not_a_slot(self):
        r = self.run_it("sheet.html", "out.pdf", text=sample().replace("Layer k holds", "{{1}}, {{a}}, {{A}}, {{AB}} Layer k holds"))
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)

    def test_a_good_sheet_reaches_playwright(self):
        r = self.run_it("sheet.html", "out.pdf", text=sample())
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertIn("fake playwright", r.stdout)


@unittest.skipUnless(NODE and os.environ.get("EXAM_PREP_PLAYWRIGHT"),
                     "set EXAM_PREP_PLAYWRIGHT to run the browser tests")
class PrintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def print_it(self, text, name="sheet"):
        with open(os.path.join(self.tmp, f"{name}.html"), "w", encoding="utf-8") as f:
            f.write(text)
        return subprocess.run([NODE, PRINT_SHEET, f"{name}.html", f"{name}.pdf"], cwd=self.tmp,
                              capture_output=True, text=True, timeout=120)

    def check(self, *args, name="sheet"):
        return subprocess.run([sys.executable, "-I", CHECK_PDF, f"{name}.pdf", "--floor", "6",
                               "--forbid", "Nobody Here", *args],
                              cwd=self.tmp, capture_output=True, text=True, timeout=120)

    def printed(self, edit=None):
        r = self.print_it(sample(edit))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def fails(self, want, edit):
        printed = self.printed(edit)
        r = self.check()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(want, r.stdout)
        return printed

    def test_the_sample_passes(self):
        r = self.printed()
        self.assertIn("side1: ends in column 1 of 5", r.stdout)
        layout = json.loads(read(os.path.join(self.tmp, "sheet.layout.json")))
        self.assertEqual(layout["sheet"], "sheet.html")
        self.assertEqual([p["wide"] for p in layout["pages"]], [[], []])
        self.assertEqual([p["id"] for p in layout["pages"]], ["side1", "side2"])
        self.assertEqual(layout["remote"], [])
        # Side 1 ends two thirds down its first column (the figure, then two short lines).
        self.assertTrue(0.55 < layout["pages"][0]["fill"]["bottom"] < 0.8, layout["pages"][0])
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ALL CHECKS PASS", r.stdout)
        self.assertIn("DejaVuSansCondensed", r.stdout)
        self.assertIn("WARN side 1 ends in column 1 of 5", r.stdout)

    def test_fill_follows_the_content(self):
        def more(text):
            start = text.index('<div class="hue1">\n<h2>')
            end = text.index('</div>\n\n<div class="page" id="side2">')
            return text[:start] + text[start:end] * 3 + text[end:]
        r = self.printed(more)
        self.assertRegex(r.stdout, r"side1: ends in column [23] of 5")

    def test_a_spilled_column(self):
        def spill(text):
            start = text.index('<div class="hue1">\n<h2>')
            end = text.index('</div>\n\n<div class="page" id="side2">')
            return text[:start] + text[start:end] * 14 + text[end:]
        self.fails("side 1 clips content past its last column or its foot (FB-138)", spill)

    def test_a_wide_element_with_no_text(self):
        self.fails("side 1 clips content", lambda t: t.replace(
            '<div class="hue1">\n<h2>Graph basics',
            '<div style="width: 12in; height: 2pt; background: #000"></div>\n<div class="hue1">\n<h2>Graph basics'))

    def test_a_side_ending_in_a_figure(self):
        self.printed()
        base = json.loads(read(os.path.join(self.tmp, "sheet.layout.json")))["pages"][1]["fill"]
        figure = re.search(r'<figure class="sf">.*?</svg>', sample(), re.S).group(0) + "</figure>"
        last = "<tr><td>x<sub>i</sub></td><td>the i-th item</td></tr>\n</table>"
        self.printed(lambda t: t.replace(last, last + "\n" + figure))
        fill = json.loads(read(os.path.join(self.tmp, "sheet.layout.json")))["pages"][1]["fill"]
        self.assertEqual(fill["col"], base["col"])
        self.assertGreater(fill["bottom"], base["bottom"] + 0.05)

    def test_the_column_count_is_read(self):
        r = self.printed(lambda t: t.replace("column-count: 5;", "column-count: 4;", 1))
        self.assertIn("side1: ends in column 1 of 4", r.stdout)

    def test_small_svg_text(self):
        self.fails("page 1: 4.", lambda t: t.replace('font-size="9">S<', 'font-size="5">S<'))

    def test_a_small_superscript(self):
        self.fails("is below the 6 pt floor", lambda t: t.replace("n<sup>2</sup>",
                                                                  'n<sup style="font-size:4pt">2</sup>'))

    def test_a_section_sign(self):
        self.fails("a section sign points into the notes", lambda t: t.replace(
            "Layer k holds", "See §3.2. Layer k holds"))

    def test_a_remote_stylesheet(self):
        url = "https://fonts.googleapis.com/css2?family=Inter"
        printed = self.fails(f"the sheet requested {url}", lambda t: t.replace(
            "<style>", f'<link rel="stylesheet" href="{url}">\n<style>', 1))
        self.assertIn("REMOTE request aborted, to fonts.googleapis.com", printed.stdout)
        self.assertNotIn("family=Inter", printed.stdout)

    def test_portrait(self):
        self.fails("want letter landscape", lambda t: t.replace("Letter landscape", "Letter portrait"))

    def test_a_third_side(self):
        self.fails("3 pages, want 2", lambda t: t.replace(
            "</body>", '<div class="page" id="side3"><p>more</p></div>\n</body>'))

    def test_a_table_wider_than_its_column(self):
        row = lambda cell: "<tr>" + "".join(f"<{cell}>col{i}</{cell}>" for i in range(12)) + "</tr>"
        table = f'<table class="c">{row("th")}{row("td")}</table>'
        printed = self.fails('side 2, column 1: table.c "col0', lambda t: t.replace(
            "<h2>Answer templates</h2>", "<h2>Answer templates</h2>\n" + table))
        # print_sheet.mjs can't mask a name, so it names the box but not its text.
        self.assertIn("WIDER THAN ITS COLUMN: column 1: table.c\n", printed.stdout)
        self.assertNotIn("col0", printed.stdout)

    def test_a4(self):
        def a4(text):
            return (text.replace("Letter landscape", "A4 landscape")
                    .replace("--page-w: 10.6in;", "--page-w: 11.29in;")
                    .replace("--page-h: 8.1in;", "--page-h: 7.86in;"))
        self.printed(a4)
        r = self.check("--paper", "a4")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ALL CHECKS PASS", r.stdout)

    def test_a_table_and_a_pre_broken_across_columns_are_not_wide(self):
        # A block the columns break apart is measured piece by piece, not by its bounding box.
        rows = "".join(f"<tr><td>s{i}</td><td>symbol {i}</td></tr>" for i in range(90))
        code = "\n".join(f"line {i}" for i in range(110))
        self.printed(lambda t: t.replace("<td>the i-th item</td></tr>\n</table>",
                                         f"<td>the i-th item</td></tr>\n{rows}</table>\n<pre>{code}</pre>"))
        layout = json.loads(read(os.path.join(self.tmp, "sheet.layout.json")))
        self.assertEqual(layout["pages"][1]["wide"], [])
        self.assertGreaterEqual(layout["pages"][1]["fill"]["col"], 3)
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_table_a_few_pixels_too_wide(self):
        # Less than the column gap: the right edge must be the column's, not the next one's start.
        self.fails('side 1, column 1: table.c', lambda t: t.replace(
            '<p class="k">Connectivity</p>',
            '<table class="c" style="width: calc(100% + 4px)"><tr><td>a</td></tr></table>\n'
            '<p class="k">Connectivity</p>'))

    def test_from_the_hub_root(self):
        # 07 step 4 prints cheatsheet/<name>.html to cheatsheet/<name>.pdf from the hub root.
        os.mkdir(os.path.join(self.tmp, "cheatsheet"))
        r = self.print_it(sample(), name="cheatsheet/sheet")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.check(name="cheatsheet/sheet")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_inline_handlers_dont_run(self):
        self.printed(lambda t: t.replace(
            '<p class="k">Connectivity</p>',
            '<img src="missing.png" alt="" onerror="this.outerHTML=\'INJECTED\'">\n<p class="k">Connectivity</p>'))
        text = subprocess.run(["pdftotext", "sheet.pdf", "-"], cwd=self.tmp, capture_output=True,
                              text=True).stdout
        self.assertIn("Connectivity", text)
        self.assertNotIn("INJECTED", text)

    def test_a_script_is_refused(self):
        r = self.print_it(sample(lambda t: t.replace("</body>", "<script>document.title = 'x'</script>\n</body>")))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("holds a <script>: the sheet prints with JavaScript off", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "sheet.pdf")))

    def test_no_page(self):
        r = self.print_it(sample(lambda t: t.replace('class="page"', 'class="pg"')))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("has no .page element", r.stderr)


if __name__ == "__main__":
    unittest.main()
