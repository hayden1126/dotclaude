"""skills/exam-prep/templates/agent-briefs.md: the briefs of agents that must not see answers.

Hard rule 4 and FB-191 keep the answers of a set the student hasn't attempted out of what they
read. Official solutions live only in `_build/solutions/`, one file per set,
`_build/solutions/<name>.md` beside the set's extract `_build/extract/<name>.md`, which the
set's extract agent writes, or, for an answers file that solves several sets, that file's own
agent, which writes each set's part blocks in that set's file plus its own pages in full in
`_build/solutions/<doc id in lower case>.md` (FB-056, hard rule 6: no file is written by two
agents). Pinned: the Extract brief names the solutions file, and its paragraph on
the answers-file agent gives that layout; each answer-blind brief that reads course sources (the
sheet gap scan, the mock writer, the audit variant behind the Must-know, sheet and cram audits)
reads the extracts and names `_build/solutions/` only as something it never opens, keeping it
out of its scope and its searches; no answer-blind brief reads a solutions file; the briefs that
need a set's conventions (the writer, the section reviewer) read the solutions files, each block
in its home file, never by a search across them, a part with its stem block; the two
cold briefs open nothing under `_build/` at all. Every brief keeps the standing blocks' shape: a
fenced text block under its heading. The backbone template and 03-backbone give the same
no-value forms for a solutions-file correction and an erratum, since answer-blind agents read
the backbone."""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIEFS = os.path.join(REPO, "skills", "exam-prep", "templates", "agent-briefs.md")

# Answer-blind briefs that read course sources, by their heading (or the variant's bold name).
READERS = ("## Sheet gap scan (stage 07)", "## Mock writer (stage 08)", "**Audit variant**")
# Answer-blind briefs that read the notes alone.
COLD = ("## Cold read (stage 05)", "## Cold solver (stage 08, from 05-verify \"The mock\")")
# Every answer-blind brief: the source readers, the cold briefs and the converter, whose figure
# data comes from the notes alone.
ANSWER_BLIND = READERS + COLD + ("## Convert (stage 06)",)
BACKBONE = os.path.join(REPO, "skills", "exam-prep", "templates", "backbone.md.tmpl")
STAGE03 = os.path.join(REPO, "skills", "exam-prep", "workflows", "03-backbone.md")


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

    def test_each_source_reader_reads_the_extracts(self):
        for name in READERS:
            text = self.briefs[name]
            self.assertIn("{{ROOT}}/_build/extract/", text, name)
            self.assertIn("Out of scope", text, name)

    def test_no_source_reader_reads_the_solutions_files(self):
        """Each bullet of an answer-blind brief that names `_build/solutions/` either says the
        agent never opens it or is the Out of scope bullet."""
        for name in READERS:
            text = self.briefs[name]
            bullets = re.split(r"\n(?=- )", text)
            named = [b for b in bullets if "_build/solutions/" in b]
            self.assertTrue(named, name)
            for b in named:
                flat = " ".join(b.split())
                self.assertTrue("never open" in flat or b.startswith("- Out of scope:"), (name, b))
            scope = text.split("- Out of scope:", 1)[1]
            self.assertIn("_build/solutions/", scope, name)

    def test_each_source_reader_keeps_its_searches_off_the_solutions(self):
        for name in ("## Sheet gap scan (stage 07)", "**Audit variant**"):
            scope = self.briefs[name].split("- Out of scope:", 1)[1]
            search = " ".join(scope.split()).split("A search (Grep, Glob) stays inside", 1)[1]
            self.assertIn("{{ROOT}}/_build/extract/", search, name)
            self.assertIn("all of {{ROOT}}/_build/ returns answer lines", search, name)
            self.assertNotIn("solutions", search.split("returns")[0], name)
        scope = self.briefs["## Mock writer (stage 08)"].split("- Out of scope:", 1)[1]
        self.assertIn("those extracts ({{ROOT}}/_build/solutions/", " ".join(scope.split()))

    def test_no_answer_blind_brief_reads_the_solutions_files(self):
        """In every answer-blind brief, `_build/solutions/` appears only in its Out of scope
        bullet or in a bullet saying the agent never opens it: no Read first, Sources or In scope
        line hands it a solutions file."""
        for name in ANSWER_BLIND:
            self.assertIn(name, self.briefs)
            for b in re.split(r"\n(?=- )", self.briefs[name]):
                if "_build/solutions/" not in b:
                    continue
                flat = " ".join(b.split())
                self.assertTrue(b.startswith("- Out of scope:") or "never open" in flat, (name, b))
                self.assertNotRegex(flat, r"(Read first|In scope|Sources):[^.]*_build/solutions/",
                                    name)

    def test_the_answers_file_agent_writes_one_solutions_file_per_set(self):
        """The paragraph before the Extract brief: a multi-set answers file's agent uses the sets'
        part ids, writes each set's part blocks in that set's file beside its extract and its
        own pages in full in its own file, each with its own Sources and Coverage lines and a
        header naming one doc, and each set's own agent writes only its extract. Round 15
        dropped the pointer-only page blocks and the SHARED ANSWERS slots."""
        text = self.briefs["## Extract (stage 02)"]
        para = text.split("```text", 1)[0].split("An answers file that solves several", 1)[1]
        para = " ".join(para.split())
        for phrase in ("`for HW1, HW2 and HW3`", "`### [<set> <part>]`",
                       "one solutions file per set",
                       "{{ROOT}}/_build/solutions/<name>.md under that set's extract `<name>`, "
                       "holding that set's part blocks",
                       "its own file, {{ROOT}}/_build/solutions/<doc id in lower case>.md",
                       "holding the answers file's page or section blocks in full",
                       "a header never names several docs", "`Sources:` line",
                       "closing `Coverage:` line", "writes only its extract",
                       "no file is written by two agents",
                       "its page blocks go in that set's file"):
            self.assertIn(phrase, para)
        self.assertNotIn("solutions to", para)

    def test_no_brief_keeps_the_pointer_layout(self):
        """Round 15: a multi-set answers file's pages are held in full in its own file, so no
        brief keeps the SHARED ANSWERS slots or the pointer line."""
        with open(BRIEFS, encoding="utf-8") as f:
            text = f.read()
        for old in ("SHARED ANSWERS", "(transcribed under the sets' blocks)",
                    "<answers file name>"):
            self.assertNotIn(old, text)
        extract = " ".join(self.briefs["## Extract (stage 02)"].split())
        self.assertIn("its page or section blocks go in its own file instead, "
                      "{{ROOT}}/_build/solutions/<doc id in lower case>.md", extract)
        self.assertIn("(`WRONG SOLUTIONS FILE`)", extract)

    def test_the_readers_find_each_block_in_its_home_file(self):
        """The Write and Review briefs find a part's solution in its set's file, with its stem
        block, and an answers page's block in its answers file's home, by the rule, never by a
        search across the solutions files (r15-2 #1)."""
        for name in ("## Write (stage 04)", "## Review (stage 05)"):
            flat = " ".join(self.briefs[name].split())
            for phrase in ("`<name>.md` beside the set's extract",
                           "`### [<doc> Q3 stem]`",
                           "the one set's file when that file solves one set",
                           "`<doc id in lower case>.md` when it solves several",
                           "the file beside its own extract for a doc holding its own key"):
                self.assertIn(phrase, flat, (name, phrase))
            self.assertNotIn("_build/solutions/*.md", flat, name)

    def test_the_review_brief_gives_the_home_rule_before_none(self):
        """Round 16: the Review brief put the home-file rule after "or none:", which read as the
        fallback when no solutions file applies; the rule comes first and "or none" last."""
        flat = " ".join(self.briefs["## Review (stage 05)"].split())
        self.assertIn("({{SOLUTIONS FILES}} in {{ROOT}}/_build/solutions/, each block in its home "
                      "file: each part's block", flat)
        self.assertIn("for a doc holding its own key; or none)", flat)
        self.assertNotIn("or none:", flat)

    def test_the_extract_brief_writes_the_solutions_file(self):
        text = self.briefs["## Extract (stage 02)"]
        self.assertIn("{{ROOT}}/_build/solutions/{{OUT}}", text)
        self.assertIn("`No official solution.`", text)
        self.assertIn("`Solution [{{SOLDOC}} p.N]: ...`", text)

    def test_the_answer_needing_briefs_read_the_solutions_files(self):
        for name in ("## Write (stage 04)", "## Review (stage 05)"):
            self.assertIn("{{SOLUTIONS FILES", self.briefs[name], name)
            self.assertIn("{{ROOT}}/_build/solutions/", self.briefs[name], name)

    def test_the_cold_briefs_open_nothing_under_build(self):
        for name in COLD:
            scope = self.briefs[name].split("- Out of scope:", 1)[1]
            self.assertIn("{{ROOT}}/_build/", scope, name)
            self.assertNotIn("_build/solutions/", self.briefs[name], name)

    def test_every_brief_is_a_fenced_text_block(self):
        for name, text in self.briefs.items():
            if name.startswith("## ") and "(stage" in name:
                self.assertIn("```text\n# Brief:", text, name)


class BackboneCorrections(unittest.TestCase):
    """Mock writers and the sheets' gap scan read the backbone, so a solutions-file correction
    and an erratum name their doc, page and part only, never a value; the corrected value sits in
    the part's solutions block. The template and 03-backbone give the same example forms."""

    CORRECTION = "`HW1S p.2, Q2a: corrected in the solutions file (re-read at 300 dpi)`"
    ERRATUM = ("`Erratum: HW1S, HW1 Q2a: the official answer is wrong; the corrected value is on "
               "the part's Erratum line in its solutions file`")

    def test_the_template_and_the_stage_agree(self):
        for path in (BACKBONE, STAGE03):
            with open(path, encoding="utf-8") as f:
                flat = " ".join(f.read().split())
            self.assertIn(self.CORRECTION, flat, path)
            self.assertIn(self.ERRATUM, flat, path)
            self.assertIn("never a value", flat, path)

    def test_the_template_erratum_slot_carries_no_value(self):
        with open(BACKBONE, encoding="utf-8") as f:
            text = f.read()
        slot = " ".join(text.split("{{ERRATUM:", 1)[1].split("}}", 1)[0].split())
        self.assertIn("by its doc and part only, never a value", slot)
        self.assertIn(self.ERRATUM, slot)
        # Its example holds no value: no "=", no "reads", no number but the ids' own.
        example = slot.split("as in", 1)[1].replace("HW1S", "").replace("HW1 Q2a", "")
        self.assertNotRegex(example, r"=|\breads\b|\d")


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
