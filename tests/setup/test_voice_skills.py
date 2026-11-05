"""The three writing skills stay separate, each naming the others' work as out of its scope, so a
commit doesn't load a persona and no voice bleeds into another's writing."""
import os
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS = ("technical-writing", "formal-voice", "casual-voice")


def description(name):
    """The description line of a skill's frontmatter."""
    with open(os.path.join(REPO, "skills", name, "SKILL.md")) as f:
        lines = f.read().split("\n")
    header = lines[1:lines.index("---", 1)]
    return next(line for line in header if line.startswith("description: "))


class VoiceSkills(unittest.TestCase):
    def test_each_description_points_away_to_the_others(self):
        for name in SKILLS:
            text = description(name)
            not_for = text[text.index("Not for"):]
            for other in SKILLS:
                if other != name:
                    self.assertIn(other, not_for, name)
            self.assertIn("sourced", not_for, name)
            self.assertIn("chat with Hayden", not_for, name)

    def test_the_old_skill_is_gone_and_nothing_names_it(self):
        # Split so this file's own check doesn't match itself.
        old = "writing" + "-voice"
        self.assertFalse(os.path.exists(os.path.join(REPO, "skills", old)))
        found = subprocess.run(["git", "grep", "-l", "--untracked", old, "--",
                                ".", ":!STATUS.md", ":!PLAN.md"],
                               cwd=REPO, capture_output=True, text=True).stdout.split()
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
