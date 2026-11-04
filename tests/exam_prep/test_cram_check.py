"""skills/exam-prep/scripts/cram_check.py and templates/cram-order.md.tmpl (08-practice step 7).

The fixture cram order (tests/exam_prep/fixtures/mock/cram-order.md) passes against the sample
hub's assembled notes page, and so does the template with its placeholders filled in order; the
raw template fails on them. Broken one way at a time, the fixture fails naming the line: a
tier's minutes that aren't its rows' sum, a tier with no rows or out of order, a row out of
order, off the format, outside a tier or repeating a section, an id the notes page lacks, two
link bases or one that isn't https://, no Out of time line or one with no Must-know link, no
Skip line, a tier after Tonight, no Tonight or one with no item, another heading, no title, no
tier at all, an intro whose total or tier count isn't the tiers', and a bad link on any line; a
notes link in angle brackets, with a title in single quotes or parentheses, split across lines,
as a raw <a> or a bare URL is refused by its own name. With --plain (plain-text notes), rows name
their section as text and the same checks hold, no link allowed. A missing file, or one that
isn't UTF-8, is bad usage."""
import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "exam-prep")
CRAM_CHECK = os.path.join(SKILL, "scripts", "cram_check.py")
TEMPLATE = os.path.join(SKILL, "templates", "cram-order.md.tmpl")
FIXTURE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "mock", "cram-order.md")
SITE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "site")
BASE = "https://claude.ai/artifact/00000000-notes"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Cram(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        root = os.path.join(cls.tmp, "site")
        shutil.copytree(SITE, root)
        spec = importlib.util.spec_from_file_location("assemble", os.path.join(SKILL, "scripts", "assemble.py"))
        assemble = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(assemble)
        with contextlib.redirect_stdout(io.StringIO()):
            assert assemble.main(["--root", root]) == 0
        cls.notes = os.path.join(root, "_build", "notes.html")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_on(self, text, notes=None):
        path = os.path.join(self.tmp, "cram-order.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run([sys.executable, CRAM_CHECK, path, "--notes", notes or self.notes],
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def edited(self, *edits):
        text = read(FIXTURE)
        for old, new in edits:
            self.assertIn(old, text)
            text = text.replace(old, new, 1)
        return text

    def fails(self, text, message, line=None):
        rc, out, err = self.run_on(text)
        self.assertEqual(rc, 1, out + err)
        self.assertIn(message, err)
        self.assertNotIn("CRAM OK", out)
        if isinstance(line, str):  # the line of the first line holding this marker
            line = next(k for k, t in enumerate(text.splitlines(), 1) if line in t)
        if line is not None:
            self.assertIn(f"cram-order.md:{line}: {message}", err)

    def test_the_fixture_passes(self):
        rc, out, err = self.run_on(read(FIXTURE))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out.strip(), "CRAM OK: 2 tiers, 5 rows, 70 min; 7 links into the notes")

    def test_the_template_filled_in_order_passes(self):
        text = read(TEMPLATE)
        text = text[text.index("-->\n") + 4:]
        fills = {"{{NOTES URL}}": [BASE] * 5, "{{ID}}": ["sec-1-sums", "sec-2-walks", "sec-1-rules"],
                 "{{MINUTES}}": ["30", "10", "20", "15", "15"], "{{N.K}}": ["1.1", "2.2", "1.2"], "{{TOTAL}}": ["45"], "{{TIERS}}": ["2"]}
        for slot, values in fills.items():
            for v in values:
                self.assertIn(slot, text)
                text = text.replace(slot, v, 1)
        for slot in set(re.findall(r"\{\{[^{}]+\}\}", text)):
            text = text.replace(slot, "x")
        rc, out, err = self.run_on(text)
        self.assertEqual(rc, 0, err)
        self.assertIn("CRAM OK: 2 tiers, 3 rows, 45 min", out)

    def test_the_raw_template_fails_on_its_placeholders(self):
        self.fails(read(TEMPLATE), "a {{ placeholder is left")

    def test_each_rule(self):
        row4 = f"4. [§1.2 Rules]({BASE}#sec-1-rules) (15 min)"
        row2 = next(k for k, t in enumerate(read(FIXTURE).splitlines(), 1) if t.startswith("2. [§1.1 Sums]"))
        cases = [
            (("## Tier 1: Traces and counts (45 min)", "## Tier 1: Traces and counts (50 min)"),
             "the tier says 50 min, its rows sum to 45", "## Tier 1:"),
            (("## Tier 2: Rules (25 min)", "## Tier 3: Rules (25 min)"), "tier 3 where tier 2 belongs", "## Tier 3:"),
            ((row4, row4.replace("4.", "6.")), "row 6 where row 4 belongs", "[§1.2 Rules]"),
            ((row4, row4.replace(" (15 min)", "")), "a row is K. [§x.y Title]", "[§1.2 Rules]"),
            ((row4, row4.replace("#sec-1-rules", "#sec-1-sums")), f"#sec-1-sums again (line {row2})", "[§1.2 Rules]"),
            ((row4, row4.replace("#sec-1-rules", "#sec-1-ruels")), "#sec-1-ruels isn't an id in the notes page",
             "[§1.2 Rules]"),
            (("**Out of time?**", "Out of time?"), "no **Out of time?** line", None),
            (("#sec-1-must-know), [§2]", "#sec-1-sums), [§2]"), ("#sec-2-must-know)", "#sec-2-walks)"),
             "the Out of time line links no Must-know list", "**Out of time?**"),
            (("**Skip:** nothing", "Nothing to skip"), "no **Skip:** line", None),
            (("## Tonight", "## Tier 3: Tonight (0 min)"), "the last section is ## Tonight", None),
            (("## Tonight", "## Tonight\n\n## Tier 3: Late (5 min)"), "a tier after ## Tonight", "## Tier 3: Late"),
            (("## Tier 2: Rules (25 min)", "## Tier 2: Rules (25 min)\n\n## Extra"), "a heading that is neither",
             "## Extra"),
            (("# Cram order: GRF101 Midterm 1", "# GRF101 cram"), "the file starts with its # Cram order:", 1),
            (("each mock below.", "each mock below {{TOTAL}}."), "a {{ placeholder is left", "{{TOTAL}}"),
            (("70 minutes in 2 tiers", "90 minutes in 2 tiers"), "the intro says 90 minutes in 2 tiers, the tiers make 70",
             "minutes in"),
            (("70 minutes in 2 tiers", "70 minutes in 3 tiers"), "the intro says 70 minutes in 3 tiers", "minutes in"),
            (("70 minutes in 2 tiers", "seventy minutes"), "no intro line naming the total", None),
            (("**Skip:** nothing", f"**Skip:** [§3]({BASE}#sec-3-gone)"), "#sec-3-gone isn't an id in the notes page",
             "**Skip:**"),
            (("read the loop, don't write it.", f"read the loop; see [§2]({BASE}#sec-2-nope)."),
             "#sec-2-nope isn't an id in the notes page", "#sec-2-nope"),
            (("[§2](https://claude.ai/artifact/00000000-notes#sec-2-must-know).",
              "[§2](https://claude.ai/artifact/00000000-notes#sec-2-must-know)\nand [§3](https://claude.ai/artifact/00000000-notes#sec-3-must-know)."),
             "#sec-3-must-know isn't an id in the notes page", "#sec-3-must-know"),
            (("## Tier 2: Rules (25 min)", "### Aside\n\n## Tier 2: Rules (25 min)"), "a heading that is neither",
             "### Aside"),
            (("**Skip:** nothing", f'**Skip:** [§3]({BASE}#sec-3-gone "gone")'), "#sec-3-gone isn't an id", "**Skip:**"),
            (("**Skip:** nothing", f"**Skip:** [§3]({BASE}#sec-3-gone 'gone')"), "a notes link written", "**Skip:**"),
            (("**Skip:** nothing", f"**Skip:** [§3]({BASE}#sec-3-gone (gone))"), "a notes link written", "**Skip:**"),
            (("**Skip:** nothing", f"**Skip:** [§3](\n{BASE}#sec-3-gone)"), "a notes link written (a link split",
             "**Skip:**"),
            (("**Skip:** nothing", f'**Skip:** <a href="{BASE}#sec-3-gone">§3</a>'), "a notes link written (a raw <a>",
             "**Skip:**"),
            (("**Skip:** nothing", f"**Skip:** §3, {BASE}#sec-3-gone"), "a notes link written (a bare URL", "**Skip:**"),
            (("**Skip:** nothing", "**Skip:** [§3][s3]"), "a reference-style link or an autolink", "**Skip:**"),
            (("**Skip:** nothing", f"**Skip:** <{BASE}#sec-3-gone>"), "a reference-style link or an autolink",
             "**Skip:**"),
            ((f"4. [§1.2 Rules]({BASE}#sec-1-rules)", f"- [§1.2 Rules]({BASE}#sec-1-rules)"),
             "a row is K. [§x.y Title](URL#id) (m min): the one thing, numbered", "[§1.2 Rules]"),
            (("**Skip:** nothing", f"[§2.4 Extra]({BASE}#sec-2-basics) (30 min): more.\n\n**Skip:** nothing"),
             "a row is K. [§x.y Title](URL#id) (m min): the one thing, numbered `K.`", "[§2.4 Extra]"),
            ((f"4. [§1.2 Rules]({BASE}#sec-1-rules)", f"   4. [§1.2 Rules]({BASE}#sec-1-rules)"),
             "a row is K. [§x.y Title](URL#id) (m min): the one thing, numbered", "[§1.2 Rules]"),
        ]
        for case in cases:
            *edits, message, line = case
            with self.subTest(message):
                self.fails(self.edited(*edits), message, line)

    def test_a_notes_link_in_angle_brackets_is_refused_by_its_own_name(self):
        rc, _, err = self.run_on(self.edited(("**Skip:** nothing", f"**Skip:** [§3](<{BASE}#sec-3-gone>)")))
        self.assertEqual(rc, 1)
        self.assertIn("a notes link written", err)
        self.assertNotIn("autolink", err)

    def test_tonight_with_no_item(self):
        text = read(FIXTURE)
        for tail in ("## Tonight\n", "## Tonight\n\nGet some sleep.\n"):
            with self.subTest(tail=tail):
                self.fails(text[:text.index("## Tonight")] + tail, "## Tonight has no - item", None)

    def plain(self):
        """The fixture as plain-text notes write it: rows and the Out of time line name sections
        as text."""
        text = re.sub(r"^(\d+\. )\[(§[\d.]+ [^\]]+)\]\([^)]*\)", r"\1\2", read(FIXTURE), flags=re.M)
        return re.sub(r"^\*\*Out of time\?\*\* .*$", "**Out of time?** Read only the Must-know lists of §1 and §2.",
                      text, count=1, flags=re.M)

    def run_plain(self, text):
        path = os.path.join(self.tmp, "cram-order.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run([sys.executable, CRAM_CHECK, path, "--plain", "--notes", os.path.join(self.tmp, "none.html")],
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def test_plain_text_notes(self):
        rc, out, err = self.run_plain(self.plain())
        self.assertEqual(rc, 0, err)
        self.assertIn("CRAM OK: 2 tiers, 5 rows, 70 min; sections named as text", out)
        rc, out, err = self.run_plain(self.plain().replace("4. §1.2 Rules", "4. §1.2 Rules (counting)", 1))
        self.assertEqual(rc, 0, err)
        for edit, message in (
                (("4. §1.2 Rules", "4. §1.1 Sums"), ": §1.1 again"),
                (("4. §1.2 Rules", f"4. [§1.2 Rules]({BASE}#sec-1-rules)"), "a row is K. §x.y Title (m min)"),
                (("**Skip:** nothing", f"**Skip:** [§3]({BASE}#sec-3-gone)"), "a notes link, with plain-text notes"),
                (("the Must-know lists of", "the lists of"), "the Out of time line names no Must-know list"),
                (("(20 min)", "(25 min)"), "the tier says 45 min, its rows sum to 50"),
                (("4. §1.2 Rules", "- §1.2 Rules"), "a row is K. §x.y Title (m min): the one thing, numbered"),
                (("4. §1.2 Rules", "4) §1.2 Rules"), "a row is K. §x.y Title (m min): the one thing, numbered")):
            with self.subTest(message):
                text = self.plain()
                self.assertIn(edit[0], text)
                rc, out, err = self.run_plain(text.replace(edit[0], edit[1], 1))
                self.assertEqual(rc, 1, out)
                self.assertIn(message, err)

    def test_a_tier_with_no_rows(self):
        text = self.edited(("## Tier 2: Rules (25 min)", "## Tier 2: Rules (0 min)"))
        start = text.index("4. [§1.2")
        text = text[:start] + text[text.index("**Skip:**"):]
        self.fails(text, "a tier with no rows", "## Tier 2:")

    def test_no_tiers_and_a_row_outside_one(self):
        lines = read(FIXTURE).splitlines()
        no_tiers = "\n".join(l for l in lines if not l.startswith(("## Tier", "1.", "2.", "3.", "4.", "5.")))
        self.fails(no_tiers, "no ## Tier N: <name> (M min) heading")
        row = f"9. [§2.1 Basics]({BASE}#sec-2-basic) (5 min): x."
        self.fails(self.edited(("**Out of time?**", row + "\n\n**Out of time?**")), "a reading row outside a tier",
                   "9. [§2.1 Basics]")

    def test_one_https_base(self):
        self.fails(self.edited((f"{BASE}#sec-2-basics", "https://claude.ai/artifact/other#sec-2-basics")),
                   "the notes links use 2 bases")
        self.fails(read(FIXTURE).replace(BASE, ""), "the notes links' base (none) isn't the published page's")
        self.fails(read(FIXTURE).replace(BASE, "http://localhost/notes.html"), "isn't the published page's")

    def test_the_title_error_names_its_line(self):
        self.fails("\n\n" + read(FIXTURE).replace("# Cram order: GRF101 Midterm 1", "# GRF101", 1),
                   "the file starts with its # Cram order:", 3)

    def test_a_missing_file_is_bad_usage(self):
        rc, _, err = self.run_on(read(FIXTURE), notes=os.path.join(self.tmp, "none.html"))
        self.assertEqual(rc, 2)
        self.assertIn("no ", err)

    def test_a_file_that_isnt_utf8_is_bad_usage(self):
        latin = os.path.join(self.tmp, "latin.html")
        with open(latin, "wb") as f:
            f.write("<p id=\"sec-1\">caf\xe9</p>".encode("latin-1"))
        rc, _, err = self.run_on(read(FIXTURE), notes=latin)
        self.assertEqual(rc, 2)
        self.assertIn("latin.html isn't UTF-8 text", err)


if __name__ == "__main__":
    unittest.main()
