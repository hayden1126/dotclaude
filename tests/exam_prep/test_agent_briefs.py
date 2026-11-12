"""skills/exam-prep/templates/agent-briefs.md: the briefs of agents that must not see answers.

Hard rule 4 and FB-191 keep the answers of a set the student hasn't attempted out of what they
read, and an agent that greps an extract prints its Solution lines. Pinned: each answer-blind
brief that reads course sources (the sheet gap scan, the mock writer, the audit variant behind
the Must-know, sheet and cram audits) names the question-only copies, `_build/q-only/`, and keeps
the extracts of sources with copies out of its reading and its searches; the two cold briefs open
nothing under `_build/` at all. Every brief keeps the standing blocks' shape: a fenced text block
under its heading."""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIEFS = os.path.join(REPO, "skills", "exam-prep", "templates", "agent-briefs.md")

# Answer-blind briefs that read course sources, by their heading (or the variant's bold name).
READERS = ("## Sheet gap scan (stage 07)", "## Mock writer (stage 08)", "**Audit variant**")
# Answer-blind briefs that read the notes alone.
COLD = ("## Cold read (stage 05)", "## Cold solver (stage 08, from 05-verify \"The mock\")")


def sections():
    """{heading or variant name: its text up to the next one}. A brief's own `## Scope` lines sit
    inside its fence and start nothing."""
    with open(BRIEFS, encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)
    out, name, fence = {}, None, False
    for line in lines:
        if line.startswith("```"):
            fence = not fence
        elif not fence and re.match(r"## |\*\*[A-Z][\w ]* variant\*\*", line):
            name = line.rstrip("\n") if line.startswith("## ") else \
                re.match(r"\*\*[^*]+\*\*", line).group(0)
            out[name] = ""
        if name:
            out[name] += line
    return out


class AnswerBlindBriefs(unittest.TestCase):
    def setUp(self):
        self.briefs = sections()

    def test_the_briefs_exist(self):
        for name in READERS + COLD:
            self.assertIn(name, self.briefs)

    def test_each_source_reader_reads_the_question_only_copies(self):
        for name in READERS:
            text = self.briefs[name]
            self.assertIn("{{ROOT}}/_build/q-only/", text, name)
            self.assertRegex(text, r"never (?:in )?its extract|their extracts under", name)
            self.assertIn("Out of scope", text, name)

    def test_each_source_reader_keeps_its_searches_off_the_extracts(self):
        for name in ("## Sheet gap scan (stage 07)", "**Audit variant**"):
            scope = self.briefs[name].split("- Out of scope:", 1)[1]
            self.assertIn("{{ROOT}}/_build/q-only/", scope, name)
            self.assertIn("all of\n  {{ROOT}}/_build/extract/ returns answer lines", scope, name)
        scope = self.briefs["## Mock writer (stage 08)"].split("- Out of scope:", 1)[1]
        self.assertIn("those question-only copies", scope)

    def test_the_cold_briefs_open_nothing_under_build(self):
        for name in COLD:
            scope = self.briefs[name].split("- Out of scope:", 1)[1]
            self.assertIn("{{ROOT}}/_build/", scope, name)
            self.assertNotIn("q-only", self.briefs[name], name)

    def test_every_brief_is_a_fenced_text_block(self):
        for name, text in self.briefs.items():
            if name.startswith("## ") and "(stage" in name:
                self.assertIn("```text\n# Brief:", text, name)


WATCH = os.path.join(REPO, "skills", "exam-prep", "templates", "WATCH.md")
WATCH_BRIEFS = ("## Watch list ranker (stage 08)", "## Watch list cut-loss reviewer (stage 08)",
                "## Watch list annotator (stage 08)")


class WatchListBriefs(unittest.TestCase):
    """The watch list's three briefs (08-practice, "Watch list") each read the hub's WATCH.md,
    name the rule ids they apply, every one defined there, and keep out of practice/ but for the
    watch list's own data: the mocks' keys live there."""

    def setUp(self):
        self.briefs = sections()
        with open(WATCH, encoding="utf-8") as f:
            self.defined = {int(n) for n in re.findall(r"(?m)^- \*\*(?:~~)?W(\d+)\.", f.read())}

    def test_each_names_the_rules_it_applies(self):
        for name in WATCH_BRIEFS:
            self.assertIn(name, self.briefs)
            text = self.briefs[name]
            self.assertIn("{{ROOT}}/_build/WATCH.md", text, name)
            cited = {int(n) for n in re.findall(r"\bW(\d+)\b", text)}
            self.assertTrue(cited, name)
            self.assertEqual(sorted(cited - self.defined), [], name)

    def test_each_keeps_out_of_the_keys(self):
        for name in WATCH_BRIEFS:
            scope = self.briefs[name].split("- Out of scope:", 1)[1]
            self.assertIn("{{ROOT}}/practice/", scope, name)
            self.assertIn("returns key lines", scope, name)


if __name__ == "__main__":
    unittest.main()
