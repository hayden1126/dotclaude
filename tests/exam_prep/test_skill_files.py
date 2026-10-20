"""skills/exam-prep: checks on the skill's own files (stdlib only, no browser).

SKILL.md's frontmatter is what Claude Code reads to decide whether to load the skill, so its shape
is pinned here. Every template, workflow and reference opens with the baseline header, since only
12-retro may change them. Rule ids cited anywhere in the skill must exist in the references, and
paths the skill names must exist, except the ones later stages will add (PENDING, which shrinks as
each stage lands and fails once a pending path exists). The privacy check reads the maintainer's
private denylist when it exists and skips otherwise: the repo is public, and the denylist itself
names what must stay out of it."""
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
PENDING = {
    "scripts/linkcheck.py",
    "templates/CHASSIS.md",
    "templates/CONVERT.md",
    "templates/STYLE.md",
    "workflows/03-backbone.md",
    "workflows/04-write.md",
    "workflows/05-verify.md",
    "workflows/06-site.md",
    "workflows/07-cheatsheet.md",
    "workflows/08-practice.md",
    "workflows/09-tutor.md",
    "workflows/10-polish.md",
    "workflows/11-next-exam.md",
    "workflows/12-retro.md",
}

ID = re.compile(r"\b(FB-\d{3}|L\d{2}|K\d{2})\b")
DEFINED = re.compile(r"^\|\s*(?:~~)?(FB-\d{3}|L\d{2}|K\d{2})\b")
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


class BaselineHeader(unittest.TestCase):
    def test_every_doc_carries_it(self):
        missing = []
        for rel, text in files(SKILL):
            if rel.startswith("scripts" + os.sep) or not rel.endswith((".md", ".tmpl", ".html")):
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
        self.assertEqual(hits, [], "writing-voice: colons, parentheses or full stops instead")


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


if __name__ == "__main__":
    unittest.main()
