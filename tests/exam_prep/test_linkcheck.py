"""skills/exam-prep/scripts/linkcheck.py: the notes' cross-references (STYLE S12).

A synthetic hub: a backbone with a registry (sections, an example, a figure, a hyphenated lettered
set and template placeholders that must not count) and two note files. Markdown mode: broken
links, registry ids never defined, duplicates, a `# §N` heading as an implicit id, bare `§N.M`
references (a failure when the backbone numbers the section, skipped inside that section, a
warning otherwise). HTML mode: unresolved and duplicate ids, parsed rather than grepped."""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "skills", "exam-prep", "scripts", "linkcheck.py")

_spec = importlib.util.spec_from_file_location("linkcheck", SCRIPT)
linkcheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(linkcheck)

BACKBONE = """# Backbone

Ids look like `sec-N-<slug>`; placeholders such as `sec-1-{{SLUG}}` and `set-{{NAME}}-a` don't count.

## §1 Widgets (`sec-1`, file `notes/01-widgets.md`, full)

| § | Title | id | Sources | Practice | How it's tested |
|---|---|---|---|---|---|
| 1.1 | Basics | `sec-1-basics` | D1 pp.2-6 | HW1 Q1 | define |
| 1.2 | Must know | `sec-1-must-know` | summary | | checklist |

- Lettered sets: `set-widget-kinds-a` .. `-c`: a) round, b) square, c) flat [D1 p.4].
- Figures: `fig-1-gear` (static) [D1 p.5].
- Worked examples: `ex-1-spin` "Spinning a widget".

## §2 Gadgets (`sec-2`, file `notes/02-gadgets.md`, concise)

| § | Title | id | Sources | Practice | How it's tested |
|---|---|---|---|---|---|
| 2.1 | Levers | `sec-2-levers` | D2 #/1-3 | | |
"""

WIDGETS = """# §1 Widgets

Widgets come in three kinds {#set-widget-kinds-a} {#set-widget-kinds-b} {#set-widget-kinds-c}.

## 1.1 Basics {#sec-1-basics}

Every widget turns; this is the core of §1 and of §1.1. Kind [(a)](#set-widget-kinds-a) spins.

<!-- FIG fig-1-gear -->

> **Worked example 1.1: Spinning a widget** {#ex-1-spin}

Levers come later, in [§2.1 Levers](#sec-2-levers). `§2.1` in code is fine.

## 1.2 Must know {#sec-1-must-know}

- [Basics](#sec-1-basics)
"""

GADGETS = """# §2 Gadgets {#sec-2}

## 2.1 Levers {#sec-2-levers}

A lever is a widget (see [§1](#sec-1)).
"""


class Markdown(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "_build"))
        os.makedirs(os.path.join(self.root, "notes"))
        self.write("_build/backbone.md", BACKBONE)
        self.write("notes/01-widgets.md", WIDGETS)
        self.write("notes/02-gadgets.md", GADGETS)

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def run_check(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = linkcheck.main(["--root", self.root, *argv])
        return code, out.getvalue()

    def test_clean_notes_pass(self):
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("2 files, 10 ids defined, 4 links, registry 10", out)

    def test_the_registry_ignores_placeholders_and_expands_sets(self):
        reg = linkcheck.registry(BACKBONE)
        self.assertIn("set-widget-kinds-c", reg)
        self.assertNotIn("sec-1-", reg)
        self.assertFalse([i for i in reg if "{" in i or "<" in i or i == "sec-N"])

    def test_failures(self):
        self.write("notes/02-gadgets.md", GADGETS.replace("{#sec-2-levers}", "")
                   + "\nSee [the gear](#fig-9-none). Recall §1.1 here.\n"
                   + "\nAgain {#sec-1-basics}.\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        for line in ("BROKEN LINK 01-widgets.md: #sec-2-levers",
                     "BROKEN LINK 02-gadgets.md: #fig-9-none",
                     "REGISTRY ID NOT DEFINED: sec-2-levers",
                     "DUPLICATE ID: sec-1-basics",
                     "BARE REFERENCE 02-gadgets.md:7: §1.1 (make it a link)"):
            self.assertIn(line, out)

    def test_an_explicit_anchor_on_a_section_heading_is_not_counted_twice(self):
        code, out = self.run_check()
        self.assertNotIn("DUPLICATE ID: sec-2", out)

    def test_warnings_dont_fail(self):
        self.write("notes/02-gadgets.md", GADGETS + "\nExtra {#sec-2-extra}. Not covered: §2.7.\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertIn("ID NOT IN REGISTRY (allowed, check): sec-2-extra", out)
        self.assertIn("BARE REFERENCE TO AN UNNUMBERED SECTION (allowed, check) "
                      "02-gadgets.md:7: §2.7", out)

    def test_fenced_code_counts_for_nothing(self):
        self.write("notes/02-gadgets.md", GADGETS + "\n```\nsee §1.1\n# §1 again {#sec-1-basics}\n"
                   "```\n\n~~~\n[x](#nowhere) §1.1\n~~~\n")
        code, out = self.run_check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("DUPLICATE", out)

    def test_a_citation_of_another_document_is_not_a_bare_reference(self):
        self.write("notes/02-gadgets.md", GADGETS + "\nThe standard says so [W1 §1.1].\n")
        self.assertEqual(self.run_check()[0], 0)

    def test_a_bracketed_section_with_no_link_is_a_bare_reference(self):
        self.write("notes/02-gadgets.md", GADGETS + "\n- A point ([§1.1]).\n")
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn("BARE REFERENCE 02-gadgets.md:7: §1.1", out)

    def test_a_subsection_heading_sets_the_section_a_line_is_in(self):
        self.write("notes/02-gadgets.md", GADGETS + "\nAs this subsection, §2.1, shows.\n")
        self.assertEqual(self.run_check()[0], 0)

    def test_missing_inputs(self):
        os.remove(os.path.join(self.root, "_build", "backbone.md"))
        self.assertEqual(self.run_check()[0], 2)


class Html(unittest.TestCase):
    def check(self, page):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(page)
        self.addCleanup(os.remove, f.name)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = linkcheck.main(["--html", f.name])
        return code, out.getvalue()

    def test_resolved_page_passes(self):
        code, out = self.check("<h2 id='sec-1'>A</h2><a href=\"#sec-1\">x</a><a href='#'>top</a>"
                               "<div data-id='sec-9'></div><a href='#sec%2D1'>enc</a>")
        self.assertEqual(code, 0, out)
        self.assertIn("2 in-page links, 1 ids; 0 unresolved; 0 duplicate ids", out)

    def test_unresolved_and_duplicates_fail(self):
        code, out = self.check('<p id="a"></p><p id="a"></p><a href="#a">1</a><a href="#b">2</a>'
                               '<script>var s = \'<p id="b"></p>\';</script>')
        self.assertEqual(code, 1)
        self.assertIn("UNRESOLVED #a (defined 2x)", out)
        self.assertIn("UNRESOLVED #b (defined 0x)", out)
        self.assertIn("DUPLICATE id a", out)


if __name__ == "__main__":
    unittest.main()
