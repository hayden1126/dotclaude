"""tests/exam_prep/fixtures/make_minicourse.py: the dry run's synthetic mini-course.

Its homework answers are computed by its own search functions, so those functions are checked
against traces worked by hand: breadth-first search on G1 and H (neighbors alphabetical, a node
marked when enqueued) and Dijkstra on G2 and K (ties alphabetical). Lecture 2's "fewest edges is
not cheapest" slide quotes G2's own paths and costs.

With a headless Chromium (EXAM_PREP_CHROME, or Playwright's chrome-headless-shell) and poppler's
pdftotext and pdfinfo, the generated course is checked whole: each PDF's page count, the slide
where Exam 1 ends, the official solutions agreeing with expected.json, expected.json agreeing with
the hand traces, the intake answers, and `ed-pull rebuild` turning the raw Ed threads into a
digest whose staff items set scope and whose student claim stays a signal."""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "tests", "exam_prep", "fixtures", "make_minicourse.py")
ED_PULL = os.path.join(REPO, "skills", "exam-prep", "scripts", "ed-pull")

_spec = importlib.util.spec_from_file_location("make_minicourse", SCRIPT)
mc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mc)

# Worked by hand from the edge lists, not by the generator's functions.
G1_ORDER, G1_DIST = list("ABCDE"), {"A": 0, "B": 1, "C": 1, "D": 2, "E": 3}
G2_DIST, G2_ORDER = {"S": 0, "A": 2, "B": 3, "C": 4, "T": 7}, list("SABCT")
H_ORDER, H_DIST = list("SABCDE"), {"S": 0, "A": 1, "B": 1, "C": 2, "D": 2, "E": 3}
K_DIST, K_ORDER = {"S": 0, "A": 3, "B": 1, "C": 4, "T": 7}, list("SBACT")


def chrome():
    try:
        return mc.find_chrome(None)
    except SystemExit:
        return None


class AlgorithmsTest(unittest.TestCase):
    def test_bfs_on_g1_and_h(self):
        order, dist, rows = mc.bfs(mc.G1, "A")
        self.assertEqual((order, dist), (G1_ORDER, G1_DIST))
        self.assertEqual(rows[1], ("B", "B C"))
        self.assertEqual(mc.bfs(mc.H, "S")[:2], (H_ORDER, H_DIST))

    def test_dijkstra_on_g2_and_k(self):
        self.assertEqual(mc.dijkstra(mc.G2, "S"), (G2_DIST, G2_ORDER))
        self.assertEqual(mc.dijkstra(mc.K, "S"), (K_DIST, K_ORDER))

    def test_homework_answers(self):
        _, solutions, facts = mc.homework()
        self.assertEqual(facts["hw1_q1a"], 15)
        self.assertEqual((facts["hw1_q2a"], facts["hw1_q2b"]), (H_ORDER, H_DIST))
        self.assertEqual((facts["hw1_q3a"], facts["hw1_q3b"]), (K_DIST, K_ORDER))
        self.assertEqual(facts["hw1_q1b"]["B"], ["C", "D", "S"])
        self.assertIn("A 3, B 1, C 4, S 0, T 7", solutions)

    def test_the_fewest_edges_slide_quotes_g2(self):
        pages, facts = mc.lecture2()
        slide = next(p for p in pages if "Fewest edges is not cheapest" in p)
        self.assertIn("S-B-T uses the fewest edges, 2, and costs 5 + 6 = 11", slide)
        self.assertIn("S-A-B-C-T uses 4 edges and costs 2 + 1 + 1 + 3 = 7", slide)
        self.assertEqual(facts["G2_dijkstra_dist"]["T"], 7)


@unittest.skipUnless(chrome() and shutil.which("pdftotext") and shutil.which("pdfinfo"),
                     "needs a headless Chromium (EXAM_PREP_CHROME) and poppler's pdftotext")
class GeneratedCourseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.out = os.path.join(cls.tmp, "mc")
        with contextlib.redirect_stdout(io.StringIO()):
            assert mc.main([cls.out]) == 0
        with open(os.path.join(cls.out, "expected.json"), encoding="utf-8") as f:
            cls.expected = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def pdf(self, rel):
        return os.path.join(self.out, "course", rel)

    def text(self, rel, page=None):
        args = ["pdftotext"] + (["-f", str(page), "-l", str(page)] if page else [])
        r = subprocess.run(args + [self.pdf(rel), "-"], capture_output=True, text=True, check=True)
        return re.sub(r"\s+", " ", r.stdout)

    def test_page_counts(self):
        for rel, n in (("lectures/L1-graphs-and-bfs.pdf", 10), ("lectures/L2-shortest-paths.pdf", 10),
                       ("lectures/L3-spanning-trees.pdf", 4), ("homework/hw1.pdf", 2),
                       ("homework/hw1-solutions.pdf", 2), ("syllabus.pdf", 1)):
            with self.subTest(rel=rel):
                info = subprocess.run(["pdfinfo", self.pdf(rel)], capture_output=True, text=True,
                                      check=True).stdout
                self.assertEqual(int(re.search(r"^Pages:\s+(\d+)", info, re.M).group(1)), n)

    def test_exam_1_ends_at_lecture_2_slide_9(self):
        nine = self.text("lectures/L2-shortest-paths.pdf", 9)
        self.assertIn("Dijkstra's invariant", nine)
        self.assertIn("Lecture 2 · 9", nine)
        self.assertIn("Negative weights", self.text("lectures/L2-shortest-paths.pdf", 10))
        self.assertIn("up to Dijkstra's invariant", self.text("syllabus.pdf"))

    def test_expected_json_matches_the_hand_traces(self):
        e = self.expected
        self.assertEqual((e["G1_bfs_order"], e["G1_bfs_dist"]), (G1_ORDER, G1_DIST))
        self.assertEqual((e["G2_dijkstra_dist"], e["G2_dijkstra_order"]), (G2_DIST, G2_ORDER))
        self.assertEqual((e["hw1_q2a"], e["hw1_q2b"]), (H_ORDER, H_DIST))
        self.assertEqual((e["hw1_q3a"], e["hw1_q3b"]), (K_DIST, K_ORDER))
        self.assertEqual(e["hw1_q1a"], 15)

    def test_the_solutions_pdf_states_expected_json(self):
        t = self.text("homework/hw1-solutions.pdf")
        e = self.expected
        self.assertIn(f"(a) 6 · 5 / 2 = {e['hw1_q1a']}", t)
        self.assertIn(f"(a) {', '.join(e['hw1_q2a'])}.", t)
        self.assertIn(", ".join(f"{n} {d}" for n, d in sorted(e["hw1_q2b"].items())), t)
        self.assertIn(", ".join(f"{n} {d}" for n, d in sorted(e["hw1_q3a"].items())), t)
        self.assertIn(f"(b) {', '.join(e['hw1_q3b'])}.", t)

    def test_the_questions_hold_no_answers(self):
        t = self.text("homework/hw1.pdf")
        self.assertIn("Run Dijkstra on the graph K", t)
        self.assertNotIn(", ".join(f"{n} {d}" for n, d in sorted(self.expected["hw1_q3a"].items())), t)

    def test_the_intake_answers(self):
        with open(os.path.join(self.out, "answers.md"), encoding="utf-8") as f:
            a = f.read()
        self.assertIn("L3 is for Exam 2", a)
        self.assertIn("up to slide 9", a)
        self.assertIn("I have attempted HW1", a)

    def test_ed_pull_rebuilds_a_digest_from_the_raw_threads(self):
        hub = os.path.join(self.tmp, "hub")
        shutil.copytree(os.path.join(self.out, "ed-raw"), os.path.join(hub, "sources", "ed"))
        r = subprocess.run(["python3", "-I", ED_PULL, "rebuild"], cwd=hub, capture_output=True,
                           text=True, env={"PATH": os.environ.get("PATH", ""), "HOME": hub})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("from 4 raw threads", r.stdout)
        with open(os.path.join(hub, "sources", "ed", "ed-digest.md"), encoding="utf-8") as f:
            digest = f.read()
        scope = digest.split("## scope", 1)[1].split("\n## ", 1)[0]
        self.assertIn("through the slide on Dijkstra's invariant", scope)
        self.assertIn("break ties alphabetically", scope)
        signals = digest.split("## Student signals", 1)[1]
        self.assertIn("spanning trees are on it", signals)
        self.assertNotIn("spanning trees", scope)


if __name__ == "__main__":
    unittest.main()
