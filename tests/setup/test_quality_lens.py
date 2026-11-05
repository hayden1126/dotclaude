"""The quality-lens skill stays manual: without its frontmatter flag it would fire on its own,
silently, and its advisory findings would join ordinary reviews."""
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "quality-lens", "SKILL.md")


def frontmatter(path):
    """The key: value lines between a file's two opening --- markers."""
    with open(path) as f:
        lines = f.read().split("\n")
    end = lines.index("---", 1)
    return dict(line.split(": ", 1) for line in lines[1:end])


class QualityLens(unittest.TestCase):
    def test_runs_only_on_its_slash_command(self):
        fields = frontmatter(SKILL)
        self.assertEqual(fields["name"], "quality-lens")
        self.assertEqual(fields["disable-model-invocation"], "true")

    def test_readme_lists_it(self):
        with open(os.path.join(REPO, "README.md")) as f:
            row = next(line for line in f if line.startswith("| `skills/` |"))
        self.assertIn("`quality-lens`", row)


if __name__ == "__main__":
    unittest.main()
