"""Checks on the mocks skill's own files: how it triggers, that the folder stands alone, and that no
private name reaches this public repo (stdlib only, no browser, no model calls)."""
import glob
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "mocks")
DENYLISTS = glob.glob(os.path.expanduser("~/scratch/*/denylist.txt"))
EM_DASH = chr(0x2014)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def skill_files():
    for root, dirs, files in os.walk(SKILL):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            yield os.path.join(root, name)


def frontmatter():
    match = re.match(r"---\n(.*?)\n---\n", read(os.path.join(SKILL, "SKILL.md")), re.S)
    return match.group(1) if match else ""


class Trigger(unittest.TestCase):
    def test_it_loads_on_its_own(self):
        self.assertNotIn("disable-model-invocation", frontmatter())

    def test_the_description_names_triggers_and_near_misses(self):
        text = frontmatter()
        self.assertIn("name: mocks", text)
        for word in ("clickable", "mock", "prototype", "test mocks", "mock exams", "mock servers"):
            self.assertIn(word, text)

    def test_the_description_fits_the_limit(self):
        self.assertLessEqual(len(frontmatter()), 1024)


class Files(unittest.TestCase):
    def test_what_the_skill_names_exists(self):
        text = read(os.path.join(SKILL, "SKILL.md"))
        for path in re.findall(r"<skill dir>/([\w./-]+)", text):
            with self.subTest(path=path):
                self.assertTrue(os.path.isfile(os.path.join(SKILL, path)), path)

    def test_the_folder_stands_alone(self):
        for path in skill_files():
            with self.subTest(path=path):
                self.assertNotRegex(read(path), r"skills/(?!mocks)[\w-]+/|\.\./")

    def test_no_em_dashes(self):
        for path in skill_files():
            with self.subTest(path=path):
                self.assertNotIn(EM_DASH, read(path))

    def test_the_frontend_skill_points_here(self):
        text = read(os.path.join(REPO, "skills", "frontend-ui-discipline", "SKILL.md"))
        self.assertRegex(text, r"`mocks`")

    def test_the_readme_lists_the_skill_and_its_tests(self):
        lines = read(os.path.join(REPO, "README.md")).splitlines()
        skill_rows = [line for line in lines if line.startswith("| `skills/` |")]
        self.assertEqual(len(skill_rows), 1)
        self.assertIn("`mocks`", skill_rows[0])
        self.assertTrue([line for line in lines if line.startswith("| `tests/mocks/` |")])


@unittest.skipUnless(DENYLISTS, "no private denylist on this machine")
class PrivateNames(unittest.TestCase):
    def test_no_denylisted_string_in_the_skill_or_its_tests(self):
        terms = [t.strip().lower() for path in DENYLISTS for t in read(path).splitlines() if t.strip()]
        paths = list(skill_files())
        here = os.path.dirname(os.path.abspath(__file__))
        paths += [os.path.join(here, f) for f in os.listdir(here) if f.endswith(".py")]
        for path in paths:
            text = read(path).lower()
            for term in terms:
                with self.subTest(path=path, term="(private)"):
                    self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
