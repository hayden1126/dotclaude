"""Tests time durations with time.monotonic(), never the wall clock. HAYPC's WSL2 wall clock
steps forward 0.3 to 0.6 s every 30 s, so a deadline or an elapsed time read from time.time()
runs up to 0.6 s long whenever a step lands inside it. A real epoch stamp (an mtime age, a JSON
stamp, a value shipped code writes or compares with time.time()) stays, with `# wall clock` on
its line. A text scan, so it covers the fake scripts tests hold in strings too (stdlib only)."""
import glob
import os
import re
import unittest

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WALL = re.compile(r"\btime\.time(_ns)?\b")
MARK = re.compile(r"#.*\bwall clock\b")
RULE = ("time durations, timeouts and deadlines with time.monotonic(); a real epoch stamp (an "
        "mtime, a JSON stamp, a value shipped code writes with time.time()) takes a "
        "`# wall clock` comment on its line")


def unmarked(lines):
    """The 1-based numbers of the lines that read the wall clock with no marker."""
    return [n for n, line in enumerate(lines, 1) if WALL.search(line) and not MARK.search(line)]


class ClockUse(unittest.TestCase):
    def test_the_check(self):
        lines = ["deadline = time.monotonic() + 10",
                 "then = time.time() - age  # wall clock",
                 "now = checks.time.time()",
                 "while time.time() < deadline:",
                 "clock = time.time",
                 "t = time.time_ns()"]
        self.assertEqual(unmarked(lines), [3, 4, 5, 6])

    def test_every_wall_clock_read_in_tests_is_marked(self):
        found = []
        for path in sorted(glob.glob(os.path.join(TESTS, "**", "*.py"), recursive=True)):
            if os.path.samefile(path, __file__):
                continue
            with open(path, encoding="utf-8") as f:
                found += [f"{os.path.relpath(path, TESTS)}:{n}" for n in unmarked(f)]
        self.assertFalse(found, RULE + ":\n" + "\n".join(found))


if __name__ == "__main__":
    unittest.main()
