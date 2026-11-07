"""README's License table names exactly the third-party license texts git tracks, so a part
added with its license can't go unlisted, and a row can't outlive or precede its file. The demo
recorder is copied into other repos, so it carries the root license itself."""
import os
import re
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEXT_NAME = re.compile(r"(^|[-_.])(licen[cs]es?|unlicense|copying|copyright|notices?)([-_.]|$)", re.I)
CODE = (".py", ".sh", ".js", ".mjs", ".ts")  # pass-notice.sh and this test are code, not texts
NOT_TEXTS = ("bin/", "docs/")  # scripts with no suffix, and prose about licenses
RECORDER = os.path.join(REPO, "skills", "demo-video", "template", "record.mjs")


def license_section():
    """README's text from the License heading to the next heading of that level."""
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    return re.search(r"^## License\n(.*?)(?=^## |\Z)", readme, re.M | re.S).group(1)


def table_rows():
    """The paths in the last column of each License table row, below its header row."""
    rows = [line for line in license_section().splitlines() if line.startswith("| ")]
    return [re.findall(r"`([^`]+)`", row.rstrip(" |").rsplit("|", 1)[-1]) for row in rows[1:]]


def listed_texts():
    return {path for row in table_rows() for path in row}


def tracked_texts():
    """The paths git tracks that are named like a license text or sit in a _licences folder.
    Git's list, not the disk's, because only tracked files ship."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, env=env, check=True,
                         capture_output=True, text=True).stdout
    return {path for path in out.split("\0") if path
            and (("/_licences/" in path)
                 or (TEXT_NAME.search(os.path.basename(path)) and not path.endswith(CODE)
                     and not path.startswith(NOT_TEXTS)))}


class LicenseNotices(unittest.TestCase):
    def test_table_lists_exactly_the_tracked_texts(self):
        self.assertTrue(listed_texts())
        self.assertEqual(tracked_texts() - {"LICENSE"}, listed_texts())

    def test_every_row_names_a_text(self):
        self.assertTrue(table_rows())
        self.assertTrue(all(table_rows()), table_rows())

    def test_every_listed_text_exists(self):
        self.assertEqual([p for p in listed_texts() if not os.path.isfile(os.path.join(REPO, p))], [])

    def test_root_license_is_mit_and_readme_says_so(self):
        self.assertIn("LICENSE", tracked_texts())
        with open(os.path.join(REPO, "LICENSE"), encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.startswith("MIT License\n"))
        self.assertIn("Copyright (c) 2026 Chun Hei Leung", text)
        self.assertIn("MIT licensed: see [LICENSE](LICENSE)", license_section())

    def test_recorder_opens_with_the_root_license(self):
        with open(os.path.join(REPO, "LICENSE"), encoding="utf-8") as f:
            header = "".join(f"// {line}".rstrip() + "\n" for line in f.read().splitlines())
        with open(RECORDER, encoding="utf-8") as f:
            self.assertTrue(f.read().startswith(header))


if __name__ == "__main__":
    unittest.main()
