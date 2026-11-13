"""skills/exam-prep: checks on the skill's own files (stdlib only, no browser).

SKILL.md's frontmatter is what Claude Code reads to decide whether to load the skill, so its shape
is pinned here. Every template, workflow and reference opens with the baseline header, since only
12-retro may change them. Rule ids cited anywhere in the skill must exist in the references, and
paths the skill names must exist, except the ones later stages will add (PENDING, which shrinks as
each stage lands and fails once a pending path exists). The privacy check reads the maintainer's
private denylist when it exists and skips otherwise: the repo is public, and the denylist itself
names what must stay out of it. Every workflow site of the questions check gives the one
command that builds its own file list."""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "exam-prep")
TESTS = os.path.join(REPO, "tests", "exam_prep")
REFS = os.path.join(SKILL, "references")
DENYLIST = os.path.expanduser("~/scratch/exam-prep/denylist.txt")
EM_DASH = chr(0x2014)

# Paths the skill names that a later stage creates. Remove each one in the commit that adds it.
PENDING = set()

ID = re.compile(r"\b(FB-\d{3,}|L\d{2,}|K\d{2,})\b")
DEFINED = re.compile(r"^\|\s*(?:~~)?(FB-\d{3,}|L\d{2,}|K\d{2,})\b")
PATH = re.compile(r"(?:(?<=<skill>/)|(?<![\w./~-]))"
                  r"((?:workflows|templates|scripts|references)/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9]+)+)")


BINARY = (".png", ".jpg", ".pdf")


def files(root):
    """Every text file under root, as (relative path, text)."""
    out = []
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(names):
            if name.endswith(BINARY):
                continue
            path = os.path.join(base, name)
            with open(path, encoding="utf-8", errors="replace") as f:
                out.append((os.path.relpath(path, root), f.read()))
    return out


def defined_ids():
    ids = set()
    for name in ("feedback-log.md", "lessons.md", "backlog.md"):
        with open(os.path.join(REFS, name), encoding="utf-8") as f:
            for line in f:
                m = DEFINED.match(line)
                if m:
                    ids.add(m.group(1))
    return ids


class Frontmatter(unittest.TestCase):
    def test_name_and_description(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        m = re.match(r"---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(m, "SKILL.md opens with a --- frontmatter block")
        block = m.group(1)
        self.assertLessEqual(len(block), 1024, "frontmatter stays within 1024 characters")
        self.assertIn("name: exam-prep\n", block + "\n")
        desc = re.search(r"^description: (.*)$", block, re.M)
        self.assertIsNotNone(desc)
        self.assertTrue(desc.group(1).startswith("Use when "), desc.group(1)[:40])


# The step-through example's figure goes into the page verbatim, where assemble.py refuses any
# comment, so the example carries its header in its script instead.
EXAMPLE = os.path.join("templates", "stepthrough-example")


class BaselineHeader(unittest.TestCase):
    def test_every_doc_carries_it(self):
        missing = []
        for rel, text in files(SKILL):
            if rel.startswith(EXAMPLE + os.sep):
                if not rel.endswith(".js"):
                    continue
            elif rel.startswith("scripts" + os.sep) or not rel.endswith((".md", ".tmpl", ".html")):
                continue
            head = "\n".join(text.splitlines()[:10]).lower()
            if "baseline as of 20" not in head or "12-retro" not in head:
                missing.append(rel)
        self.assertEqual(missing, [], "each opens with 'Baseline as of <date>; changes only "
                                      "via `12-retro`' in its first lines")


class Prose(unittest.TestCase):
    def test_no_em_dash(self):
        hits = [f"{rel}:{n}" for rel, text in files(SKILL)
                for n, line in enumerate(text.splitlines(), 1) if EM_DASH in line]
        self.assertEqual(hits, [], "technical-writing: colons, parentheses or full stops instead")


class CitedIds(unittest.TestCase):
    def test_every_cited_id_is_defined(self):
        known = defined_ids()
        self.assertIn("FB-001", known)
        self.assertIn("L01", known)
        self.assertIn("K01", known)
        unknown = sorted({f"{rel}: {m.group(1)}" for rel, text in files(SKILL)
                          for m in ID.finditer(text) if m.group(1) not in known})
        self.assertEqual(unknown, [])

    def test_the_parsers(self):
        self.assertEqual(DEFINED.match("| ~~FB-073~~ | retired |").group(1), "FB-073")
        self.assertIsNone(DEFINED.match("see FB-073"))
        self.assertEqual([m.group(1) for m in ID.finditer("FB-012, L04 and K18; K-org.F1")],
                         ["FB-012", "L04", "K18"])


class NamedPaths(unittest.TestCase):
    def named(self):
        return {m.group(1) for _, text in files(SKILL) for m in PATH.finditer(text)}

    def test_named_paths_exist_or_are_pending(self):
        missing = sorted(p for p in self.named() - PENDING
                         if not os.path.exists(os.path.join(SKILL, p)))
        self.assertEqual(missing, [], "add the file, or add it to PENDING if a later stage "
                                      "builds it")

    def test_pending_paths_are_still_missing(self):
        landed = sorted(p for p in PENDING if os.path.exists(os.path.join(SKILL, p)))
        self.assertEqual(landed, [], "remove these from PENDING: they exist now")

    def test_the_path_pattern(self):
        text = ("`<skill>/templates/PLAN.md.tmpl`, `workflows/01-ingest.md`, "
                "`~/.claude/templates/STATUS.md`, `_build/templates/x.md`, `workflows/NN-*.md`")
        self.assertEqual(sorted(m.group(1) for m in PATH.finditer(text)),
                         ["templates/PLAN.md.tmpl", "workflows/01-ingest.md"])


WATCH = os.path.join(SKILL, "templates", "WATCH.md")
W_RULE = re.compile(r"^- \*\*(?:~~)?W(\d+)\.", re.M)
# A W id cited as a watch-list rule; `[W1 §2.1]` and `W1 (all)` are a document's citations.
W_CITE = re.compile(r"\bW(\d+)\b(?! §| \(all\))")


def watch_ids():
    with open(WATCH, encoding="utf-8") as f:
        return [int(n) for n in W_RULE.findall(f.read())]


class WatchRules(unittest.TestCase):
    def test_ids_run_from_w1_without_a_gap(self):
        ids = watch_ids()
        self.assertTrue(ids, "WATCH.md defines its rules as `- **W<n>. Title.**` bullets")
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_every_cited_w_id_is_defined(self):
        known = set(watch_ids())
        unknown = []
        for rel in (os.path.join("templates", "WATCH.md"),
                    os.path.join("workflows", "08-practice.md"),
                    os.path.join("workflows", "00-intake.md")):
            with open(os.path.join(SKILL, rel), encoding="utf-8") as f:
                unknown += [f"{rel}: W{n}" for n in W_CITE.findall(f.read())
                            if int(n) not in known]
        self.assertEqual(unknown, [])

    def test_the_watch_list_step_and_its_plan_line(self):
        with open(os.path.join(SKILL, "workflows", "08-practice.md"), encoding="utf-8") as f:
            practice = f.read()
        self.assertIn("\n## Watch list\n", practice)
        self.assertIn("`Watch list: yes`", practice)
        with open(os.path.join(SKILL, "workflows", "00-intake.md"), encoding="utf-8") as f:
            self.assertIn("**Watch list.**", f.read())
        with open(os.path.join(SKILL, "templates", "PLAN.md.tmpl"), encoding="utf-8") as f:
            self.assertRegex(f.read(), r"(?m)^- Watch list: ")

    def test_the_cite_pattern(self):
        self.assertEqual(W_CITE.findall("(W12), W3 to W5; `[W1 §2.1]`, `W1 (all)`"),
                         ["12", "3", "5"])


class QuestionsCheckFiles(unittest.TestCase):
    """05-verify step 5 runs the questions check, and 07-cheatsheet before a sheet is published
    or printed, 08-practice's "Changing the notes or a sheet" item 4, 10-polish and
    11-next-exam (twice) run it again. Round 17 found the hand-written file lists drifting from
    extract_check.py's home rule, so mock_leak.py now builds the list itself (`--hub .`, from
    `extract_check.py --leak-files`): each site gives the one command, and none lists a file by
    hand, a `_build/solutions/` path or a `--questions` or `--allow` argument. Round 18 found
    the sheets unchecked (`--pages notes/*.md`), so the command passes no page: it reads every
    page under `notes/` and `cheatsheet/`, and 08's table row and item 4 run it on a change to
    a sheet too; 09-tutor checks a held passage alone (`--pages _build/held-check.md`). 05-verify
    names `--leak-files` and the line printed with no unattempted set."""

    COMMAND = "`python3 -I <skill>/scripts/mock_leak.py --hub .`"
    SITES = {"05-verify.md": 1, "07-cheatsheet.md": 1, "08-practice.md": 1, "10-polish.md": 1,
             "11-next-exam.md": 2}
    # 09-tutor's check of a held passage before it is offered back: the one page it reads.
    HELD = "`python3 -I <skill>/scripts/mock_leak.py --hub . --pages _build/held-check.md`"
    # The round 14 to 16 wordings of the hand-written list, and round 17's notes-only pages.
    OLD = ("extract and own solutions file", "and its own solutions file",
           "each unattempted set's extract and its solutions file when it has one",
           "one file per set", "exits 2 on a missing path", "--pages notes/")
    HAND = ("_build/solutions/", "_build/extract/", "--questions", "--allow")

    @staticmethod
    def flat(name):
        with open(os.path.join(SKILL, "workflows", name), encoding="utf-8") as f:
            return " ".join(f.read().split())

    def test_each_site_gives_the_one_command(self):
        for name, count in self.SITES.items():
            flat = self.flat(name)
            self.assertEqual(flat.count(self.COMMAND), count, name)
            for old in self.OLD:
                self.assertNotIn(old, flat, name)

    def test_no_site_lists_files_by_hand(self):
        for name in self.SITES:
            flat = self.flat(name)
            for m in re.finditer(re.escape(self.COMMAND), flat):
                context = flat[max(0, m.start() - 900):m.end() + 900]
                self.assertTrue("questions check" in context or "QUESTIONS OK" in context,
                                (name, context))
                around = flat[max(0, m.start() - 600):m.end() + 600]
                for hand in self.HAND:
                    self.assertNotIn(hand, around, (name, hand))

    def test_the_tutor_checks_a_held_passage_alone(self):
        """09-tutor offers a held passage back only once the check on it alone passes: the
        passage isn't under `notes/`, and the one command can't target a set (round 18)."""
        flat = self.flat("09-tutor.md")
        self.assertEqual(flat.count(self.HELD), 1)
        m = flat.index(self.HELD)
        self.assertIn("questions check", flat[max(0, m - 900):m + 900])
        around = flat[max(0, m - 600):m + 600]
        for hand in self.HAND:
            self.assertNotIn(hand, around, hand)
        self.assertIn("writes the original text to `_build/held-check.md`", flat)
        self.assertIn("offered only once this prints QUESTIONS OK", flat)
        self.assertNotIn("questions check against that set", flat)

    def test_no_workflow_passes_question_files(self):
        for name in sorted(os.listdir(os.path.join(SKILL, "workflows"))):
            self.assertNotIn("--questions", self.flat(name), name)
            self.assertNotIn("--pages notes/", self.flat(name), name)

    def test_a_sheet_change_runs_it(self):
        flat = self.flat("08-practice.md")
        self.assertIn("| the questions check, on a change to the notes or a sheet;", flat)
        self.assertIn("4. **The checks.** When the notes or a sheet changed, `05-verify` step 5's "
                      "questions check", flat)
        sheet = self.flat("07-cheatsheet.md")
        done = sheet.split("## Done when", 1)[1]
        self.assertIn("the questions check (step 6) prints QUESTIONS OK with the sheets in place",
                      done)
        final = sheet.split("## The final sheet", 1)[1].split("## After shipping", 1)[0]
        self.assertIn("Step 6's questions check", final)

    def test_the_first_site_names_the_list_and_the_empty_case(self):
        flat = self.flat("05-verify.md")
        for phrase in ("`python3 -I <skill>/scripts/extract_check.py --leak-files`",
                       "`questions <path>`", "`allow <path>`",
                       "`QUESTIONS OK: no unattempted set`", "The main session runs it"):
            self.assertIn(phrase, flat)


class KeySectionRule(unittest.TestCase):
    """A `sections:` key's name followed by a space then a letter or digit (`Key formulas` under
    `sections: Key`, `Marking scheme 2`) is no key section: extract_check.py's key_section()
    strips the spaces first. A rule worded "followed by a character that is no letter or digit"
    reads a space as such a character, so every prose site says "after any spaces" (round 16)."""

    SITES = ("templates/MANIFEST.md.tmpl", "references/CHANGELOG.md", "workflows/02-extract.md")
    RULE = "followed, after any spaces, by nothing,"

    def test_each_site_says_after_any_spaces(self):
        for rel in self.SITES:
            with open(os.path.join(SKILL, rel), encoding="utf-8") as f:
                flat = " ".join(f.read().split())
            self.assertIn(self.RULE, flat, rel)

    def test_no_prose_site_reads_a_space_as_the_break(self):
        for rel, text in files(SKILL):
            if rel.startswith("scripts" + os.sep):
                continue
            flat = " ".join(text.split())
            for m in re.finditer("no letter or digit", flat):
                before = flat[max(0, m.start() - 80):m.start()]
                self.assertIn("after any spaces", before, (rel, before))


class KeySectionPageReference(unittest.TestCase):
    """The key-section rule's one exception: a locator naming a key section is key material
    whatever page reference it carries (`[PE3 Marking scheme p.2]`), and a Key name that carries
    a page reference (`sections: Answers p.4`) matches its block. Round 17 found it in 02 alone,
    so the Extract brief, the MANIFEST legend and the CHANGELOG say it too."""

    SITES = ("templates/MANIFEST.md.tmpl", "references/CHANGELOG.md", "workflows/02-extract.md",
             "templates/agent-briefs.md")

    def test_each_site_gives_the_exception(self):
        for rel in self.SITES:
            with open(os.path.join(SKILL, rel), encoding="utf-8") as f:
                flat = " ".join(f.read().split())
            for phrase in ("whatever page reference it carries", "Marking scheme p.2]",
                           "Answers p.4"):
                self.assertIn(phrase, flat, (rel, phrase))


class HomeRule(unittest.TestCase):
    """Round 16: a set's home solutions file is the one beside each extract holding any block of
    that set, a page, section or slide block included, so a deck split into parts keeps a key
    slide beside the part holding it; a block whose set no extract holds fails NO HOME FILE.
    02-extract, the MANIFEST legend and the Extract brief state the rule, and 02's step 3 gives
    the failure with its message and AN ANSWERS PAGE IN AN EXTRACT's home and why."""

    RULE = ("A set's home is the solutions file beside each extract holding any block of that set "
            "(a page, section or slide block counts, not only a question part's)")
    SITES = ("workflows/02-extract.md", "templates/MANIFEST.md.tmpl", "templates/agent-briefs.md")
    NO_HOME = ("`NO HOME FILE: [<doc> <loc>] has no home: no extract holds a block of <SET>; "
               "extract <SET> first`")

    @staticmethod
    def flat(rel):
        with open(os.path.join(SKILL, rel), encoding="utf-8") as f:
            return " ".join(f.read().split())

    def test_each_site_states_the_rule(self):
        for rel in self.SITES:
            self.assertIn(self.RULE, self.flat(rel), rel)

    def test_step_3_fails_a_block_with_no_home(self):
        flat = self.flat("workflows/02-extract.md")
        step3 = flat.split("## Step 3", 1)[1].split("## Step 4", 1)[0]
        self.assertIn(self.NO_HOME, step3)
        self.assertIn("`AN ANSWERS PAGE IN AN EXTRACT: [<doc> <loc>] is ...; move it to "
                      "_build/solutions/<name>.md, <why>`", step3)
        self.assertIn("(`NO HOME FILE`)", flat.split("## Done when", 1)[1])


class QuotingRule(unittest.TestCase):
    """A set's official solution is quoted only once that set is attempted and, when its answers
    file solves several sets, once every set that file solves is attempted. 04-write, STYLE S7
    and 05-verify say so; the hub's CLAUDE.md said only "that set" until round 16."""

    SITES = {"templates/hub-CLAUDE.md.tmpl": "when its answers file solves several sets, every set "
                                             "that file solves",
             "templates/STYLE.md": "when its answers file solves several sets, once every set "
                                   "that file solves is attempted",
             "workflows/04-write.md": "when its answers file solves several sets, once every set "
                                      "that file solves is attempted"}

    def test_each_site_gives_the_multi_set_condition(self):
        for rel, phrase in self.SITES.items():
            with open(os.path.join(SKILL, rel), encoding="utf-8") as f:
                flat = " ".join(f.read().split())
            self.assertIn(phrase, flat, rel)


class Privacy(unittest.TestCase):
    def test_no_denylisted_string(self):
        if not os.path.exists(DENYLIST):
            self.skipTest("no private denylist on this machine")
        with open(DENYLIST, encoding="utf-8") as f:
            terms = [t.strip() for t in f if t.strip() and not t.lstrip().startswith("#")]
        self.assertTrue(terms)
        hits = []
        for root in (SKILL, TESTS):
            for rel, text in files(root):
                low = text.lower()
                hits += [f"{os.path.basename(root)}/{rel}: {t}" for t in terms
                         if t.lower() in low]
        self.assertEqual(hits, [])

    def test_code_cites_a_decision_by_its_id(self):
        # Round 8: a script's comment recorded a decision as "(the student's call, <date>)", a
        # personal record in a public repo; a decision is cited by its feedback-log id. Round 9:
        # an undated one in a test's comment slipped past, so the check reads the tests too and
        # any wording of it (this file names it, so it is left out).
        call = re.compile(r"the\s+student's\s+call", re.I)
        hits = [os.path.join(top, rel) for top in (SKILL, TESTS)
                for rel, text in files(top)
                if rel.endswith((".py", ".mjs", ".sh")) and call.search(text)
                and os.path.join(top, rel) != os.path.abspath(__file__)]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
