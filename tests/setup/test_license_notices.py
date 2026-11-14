"""README's License table names exactly the third-party license texts git tracks, so a part
added with its license can't go unlisted, and a row can't outlive or precede its file. The demo
recorder's scripts and the verify harness are copied into other repos, so each carries the root license
itself."""
import os
import re
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Wide on purpose, over the whole path: a false match fails loudly, a miss passes silently.
TEXT_PATH = re.compile(r"licen[cs]e|copying|copyright|notice", re.I)
CODE = (".py", ".sh", ".js", ".mjs", ".ts")  # pass-notice.sh and this test are code, not texts
RECORDERS = {  # file copied into other repos: the comment prefix its license header uses
    os.path.join(REPO, "skills", "demo-video", "template", "record.mjs"): "// ",
    os.path.join(REPO, "skills", "demo-video", "template", "voice.mjs"): "// ",
    os.path.join(REPO, "skills", "verify-app", "template", "verify.py"): "# ",
    os.path.join(REPO, "skills", "verify-app", "template", "browser.py"): "# ",
}


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
    """The paths git tracks that look like a license text. Git's list, not the disk's, because
    only tracked files ship."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, env=env, check=True,
                         capture_output=True, text=True).stdout
    return {path for path in out.split("\0") if TEXT_PATH.search(path) and not path.endswith(CODE)}


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

    def test_copied_code_opens_with_the_root_license(self):
        with open(os.path.join(REPO, "LICENSE"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        for path, prefix in RECORDERS.items():
            header = "".join(f"{prefix}{line}".rstrip() + "\n" for line in lines)
            with open(path, encoding="utf-8") as f, self.subTest(path=path):
                self.assertTrue(f.read().startswith(header))


if __name__ == "__main__":
    unittest.main()
