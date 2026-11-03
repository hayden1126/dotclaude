"""`lane ls` shows the DA15/DA16 tripwire (lanelib.git_tamper) for the repo's common dir: a
`git: <reason>` line per finding, after the install line. It warns: the exit stays 0."""
import os
import unittest

from _fixture import LanesRepo


class LsTripwire(LanesRepo):
    def ls(self):
        p = self.run_lane("ls")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout

    def test_a_clean_repo_has_no_git_line(self):
        self.assertNotIn("git: ", self.ls())

    def test_each_finding_is_a_git_line(self):
        os.makedirs(os.path.join(self.common, "objects", "info"), exist_ok=True)
        self.write(os.path.join(self.common, "objects", "info", "alternates"), "/x/objects\n")
        self.write(os.path.join(self.common, "shallow"), "")
        lines = [x for x in self.ls().splitlines() if x.startswith("git: ")]
        self.assertEqual(len(lines), 2, lines)
        self.assertIn("objects/info/alternates", lines[0])
        self.assertIn("shallow", lines[1])

    def test_the_git_lines_come_last(self):
        self.lane("new", "chart-fix")
        self.write(os.path.join(self.common, "info", "grafts"), "")
        out = self.ls().splitlines()
        self.assertTrue(out[-1].startswith("git: info/grafts"), out)

    def test_a_commondir_in_the_main_checkouts_git_dir_is_a_git_line(self):
        # git follows a commondir file in the main checkout's .git to another dir, so the common
        # dir git names may be the planted one: ls checks the checkout's own .git too. One that
        # names a clean dir loses the lanes config (keyed by the common dir), so ls refuses; it
        # never shows a clean board.
        clean = os.path.join(self.tmp, "clean.git")
        self.git("init", "-q", "--bare", clean, cwd=self.tmp)
        for text in (".\n", clean + "\n"):
            with self.subTest(text=text):
                self.write(os.path.join(self.common, "commondir"), text)
                p = self.run_lane("ls")
                lines = [x for x in p.stdout.splitlines() if x.startswith("git: ")]
                self.assertTrue(p.returncode != 0 or any("commondir" in x for x in lines),
                                p.stdout + p.stderr)
                if text == ".\n":
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
