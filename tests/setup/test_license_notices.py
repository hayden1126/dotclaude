"""README's License section names every third-party license text in the repo, so a part added
with its license can't go unlisted, and a listed text can't vanish while README still claims it.

Dot directories hold lane state and scratch trees, not shipped files, so the walk skips them."""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEXT_NAME = re.compile(r"(LICENSE|NOTICE)([-.].*)?$")


def license_section():
    """README's text from the License heading to the next heading of that level."""
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    return re.search(r"^## License\n(.*?)(?=^## |\Z)", readme, re.M | re.S).group(1)


def license_texts():
    """Repo-relative paths of the third-party license texts, leaving out the root LICENSE."""
    found = set()
    for folder, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
        for name in files:
            path = os.path.relpath(os.path.join(folder, name), REPO)
            if TEXT_NAME.fullmatch(name) or os.path.basename(folder) == "_licences":
                found.add(path)
    found.discard("LICENSE")
    return found


class LicenseNotices(unittest.TestCase):
    def test_readme_lists_every_license_text(self):
        listed = set(re.findall(r"`([^`]+)`", license_section()))
        self.assertEqual(license_texts() - listed, set())

    def test_every_path_readme_lists_exists(self):
        paths = [p for p in re.findall(r"`([^`]+)`", license_section()) if "/" in p]
        self.assertTrue(paths)
        self.assertEqual([p for p in paths if not os.path.exists(os.path.join(REPO, p))], [])

    def test_root_license_is_mit_and_readme_says_so(self):
        with open(os.path.join(REPO, "LICENSE"), encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.startswith("MIT License\n"))
        self.assertIn("Copyright (c) 2026 Chun Hei Leung", text)
        self.assertIn("MIT licensed: see [LICENSE](LICENSE)", license_section())


if __name__ == "__main__":
    unittest.main()
