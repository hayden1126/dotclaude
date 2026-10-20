"""skills/exam-prep/templates/verify-mock-key.py, the mock key's checker (08-practice, FB-156).

Copied into a temp hub's `_build/verify/mock_key.py` beside a small reference, filled by text
replacement the way a hub fills it, and run as the workflow runs it (`python3 -I` from the hub
root) on the fixture mock and key in `practice/`. Filled, it prints KEY OK with the four computed
parts asserted and the five others listed as reasoned, writes the values under a STOP header to
practice/mock-values-key.md, and shows no answer in the terminal. A mock of proofs alone passes
with no value. It fails, naming the part, on a key answer that differs (emphasis, a final period
and spacing aside), a computable part with no value (a part's own Type: line counts over its
question's; one in a code block or a figure block doesn't), an empty why, a value for a part the
mock lacks or named twice, a value or a mock line holding a line break other than a newline, key
parts that differ from the mock's, an empty answer or one outside a bare `## Question N` block, a
key that drops a lone ** or a __name__'s underscores from the value, a file that isn't UTF-8, a
missing key (the values still written), no slugs, and a value() or reasoned() call whose slug
isn't one or whose part isn't a part id (swapped arguments print no value). A stop in values()
prints an assert's message only when the assert is the checker's own, and an exit's or a
print's never. A run that crashes keeps
the last good values file."""
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE = os.path.join(REPO, "skills", "exam-prep", "templates", "verify-mock-key.py")
FIXTURE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "mock")
SECRETS = ["dist(T) = 7", "S A B C T"]

REFERENCE = '''import heapq


def edges(degrees):
    assert sum(degrees) % 2 == 0, "an odd degree sum"
    return sum(degrees) // 2


def degree4(n, m):
    y = 2 * m - 3 * n
    assert 0 <= y <= n, "no such graph"
    return y


def dijkstra(graph, start):
    dist, order, heap = {start: 0}, [], [(0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if u in order:
            continue
        order.append(u)
        for v, w in sorted(graph.get(u, {}).items()):
            if v not in dist or d + w < dist[v]:
                dist[v] = d + w
                heapq.heappush(heap, (d + w, v))
    return order, dist


def closed_walks(adj, length, v):
    m = [row[:] for row in adj]
    for _ in range(length - 1):
        m = [[sum(m[i][k] * adj[k][j] for k in range(len(adj))) for j in range(len(adj))]
             for i in range(len(adj))]
    return m[v][v]
'''

BODY = '''    from reference import closed_walks, degree4, dijkstra, edges
    value("exam1", "Q1(a)", edges([3, 3, 2, 2, 2]))
    value("exam1", "Q1(b)", degree4(5, 9))
    graph = {"S": {"A": 2, "B": 5}, "A": {"B": 1, "C": 4}, "B": {"C": 1, "T": 6}, "C": {"T": 3}}
    order, dist = dijkstra(graph, "S")
    value("exam1", "Q2(a)", f"{' '.join(order)}, dist(T) = {dist['T']}")
    value("exam1", "Q3(a)", closed_walks([[0, 1, 1], [1, 0, 1], [1, 1, 0]], 3, 0))
'''


def fill(body=BODY, mocks='["exam1"]'):
    with open(TEMPLATE, encoding="utf-8") as f:
        text = f.read()
    text, n = re.subn(r"    # ---- Fill in: import the reference.*?\n    pass\n", lambda m: body, text, flags=re.S)
    assert n == 1, "the template's fill-in block moved"
    assert "MOCKS = []" in text
    return text.replace("MOCKS = []", f"MOCKS = {mocks}", 1)


class SameReading(unittest.TestCase):
    def test_plain_reads_an_answer_as_mock_leak_does(self):
        """The key checker and the leak check read every key answer alike (round 5): code spans
        and math as written, emphasis marks dropped outside them, \\_ as _."""
        def load(name, path):
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        key = load("mock_key_template", TEMPLATE)
        leak = load("mock_leak", os.path.join(REPO, "skills", "exam-prep", "scripts", "mock_leak.py"))
        for answer, want in (("`f(*args, **kwargs)` forwards", "f(*args, **kwargs) forwards"),
                             ("**False**: two _disjoint_ triangles.", "False: two disjoint triangles"),
                             ("*True*: a 2*3 grid", "True: a 2*3 grid"),
                             ("x\\_1 and \\(x_1 + 2**k\\)", "x_1 and \\(x_1 + 2**k\\)"),
                             ("__S__ then `__init__`", "S then __init__"),
                             ("n**2 comparisons", "n**2 comparisons"), ("x__1 and y", "x__1 and y")):
            with self.subTest(answer):
                self.assertEqual(key.plain(answer), want)
                self.assertEqual(leak.plain(answer), want)
        for answer, want in (("__S__ then `__init__`", "__S__ then __init__"), ("_x_ and **y**", "_x_ and y")):
            with self.subTest(answer, underscores=False):
                self.assertEqual(key.plain(answer, underscores=False), want)
                self.assertEqual(leak.plain(answer, underscores=False), want)


class MockKey(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.hub = tmp.name
        self.verify = os.path.join(self.hub, "_build", "verify")
        os.makedirs(self.verify)
        os.makedirs(os.path.join(self.hub, "practice"))
        for name in ("mock-exam1.md", "mock-exam1-key.md"):
            shutil.copy(os.path.join(FIXTURE, name), os.path.join(self.hub, "practice", name))
        with open(os.path.join(self.verify, "reference.py"), "w", encoding="utf-8") as f:
            f.write(REFERENCE)
        self.out = os.path.join(self.hub, "practice", "mock-values-key.md")

    def edit(self, name, old, new):
        path = os.path.join(self.hub, "practice", name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(old, text)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new, 1))

    def run_key(self, script=None):
        with open(os.path.join(self.verify, "mock_key.py"), "w", encoding="utf-8") as f:
            f.write(fill() if script is None else script)
        r = subprocess.run([sys.executable, "-I", os.path.join("_build", "verify", "mock_key.py")],
                           cwd=self.hub, capture_output=True, text=True, timeout=60)
        for secret in SECRETS:
            self.assertNotIn(secret, r.stdout + r.stderr, "the terminal shows an answer")
        return r.returncode, r.stdout + r.stderr

    def fails(self, message, script=None):
        rc, out = self.run_key(script)
        self.assertEqual(rc, 1, out)
        self.assertIn(message, out)
        self.assertNotIn("KEY OK", out)
        return out

    def test_the_filled_checker_passes(self):
        rc, out = self.run_key()
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS  exam1 Q2(a)", out)
        self.assertEqual(out.strip().splitlines()[-1],
                         "KEY OK: exam1: 4 of 9 parts asserted; reasoned: Q2(b), Q4(a), Q4(b), Q4(c), Q4(d)")
        with open(self.out, encoding="utf-8") as f:
            values = f.read()
        self.assertTrue(values.startswith("# KEY VALUES: "), values[:80])
        self.assertIn("> **STOP. Quarantined key.**", values)
        self.assertIn("## exam1\n\n- Q1(a): 6\n- Q1(b): 3\n- Q2(a): S A B C T, dist(T) = 7\n- Q3(a): 2\n", values)

    def test_a_key_answer_that_differs_fails(self):
        self.edit("mock-exam1-key.md", "Answer: S A B C T, dist(T) = 7", "Answer: S A C B T, dist(T) = 7")
        self.fails("FAIL  exam1 Q2(a): the key's answer isn't the value in practice/mock-values-key.md")

    def test_emphasis_a_period_and_spacing_dont_count(self):
        self.edit("mock-exam1-key.md", "**(a)** Answer: 6", "**(a)** Answer: **6**.")
        self.edit("mock-exam1-key.md", "**(b)** Answer: 3", "**(b)** Answer: __3__")
        self.edit("mock-exam1-key.md", "**(a)** Answer: 2", "**(a)** Answer: _2_")
        self.edit("mock-exam1-key.md", "Answer: S A B C T, dist(T) = 7", "Answer: `S A  B C T`, dist(T)  = 7")
        self.assertEqual(self.run_key()[0], 0)

    def test_marks_that_are_the_values_own_text_count(self):
        # A lone ** or a __name__ is the value's own text, not emphasis (round 6).
        key = os.path.join(self.hub, "practice", "mock-exam1-key.md")
        with open(key, encoding="utf-8") as f:
            original = f.read()
        walks = 'value("exam1", "Q3(a)", closed_walks([[0, 1, 1], [1, 0, 1], [1, 1, 0]], 3, 0))'
        for computed, answer, rc in (("n**2", "n2", 1), ("n**2", "n**2", 0), ("__init__", "init", 1),
                                     ("__init__", "__init__", 0), ("2", "_2_", 0), ("2.", "2", 0),
                                     ("a  b", "a b", 0)):
            with self.subTest(computed=computed, answer=answer):
                with open(key, "w", encoding="utf-8") as f:
                    f.write(original.replace("**(a)** Answer: 2", f"**(a)** Answer: {answer}", 1))
                got, out = self.run_key(fill(BODY.replace(walks, f'value("exam1", "Q3(a)", {computed!r})')))
                self.assertEqual(got, rc, out)

    def test_a_file_that_isnt_utf8_is_named(self):
        with open(os.path.join(self.hub, "practice", "mock-exam1-key.md"), "ab") as f:
            f.write("caf\xe9".encode("latin-1"))
        self.fails("mock-exam1-key.md isn't UTF-8 text")

    def test_a_computable_part_needs_a_value(self):
        without = fill(BODY.replace('    value("exam1", "Q3(a)"', '    0 and value("exam1", "Q3(a)"'))
        out = self.fails("exam1 UNCHECKED Q3(a) (compute, table): add a value()", without)
        self.assertNotIn("UNCHECKED Q2(b)", out)
        for kind, computable in (("trace", True), ("compute", True), ("table", True), ("classify", False),
                                 ("true-false", False), ("design", False)):
            with self.subTest(kind):
                q3 = "## Question 3: Counting walks (2 points)\n\nType: "
                self.edit("mock-exam1.md", q3 + "compute | table", q3 + kind)
                if computable:
                    self.fails(f"exam1 UNCHECKED Q3(a) ({kind})", without)
                else:
                    self.assertEqual(self.run_key(without)[0], 0)
                self.edit("mock-exam1.md", q3 + kind, q3 + "compute | table")

    def test_a_reasoned_part_is_listed(self):
        rc, out = self.run_key(fill(BODY.replace(
            '    value("exam1", "Q3(a)", closed_walks([[0, 1, 1], [1, 0, 1], [1, 1, 0]], 3, 0))',
            '    reasoned("exam1", "Q3(a)", "drawn by hand")')))
        self.assertEqual(rc, 0, out)
        self.assertIn("3 of 9 parts asserted; reasoned: Q2(b), Q3(a), Q4(a)", out)

    def test_a_reasoned_part_needs_its_why(self):
        self.fails('reasoned(\'exam1\', \'Q3(a)\') needs a why',
                   fill(BODY + '    reasoned("exam1", "Q3(a)", " ")\n'))

    def test_a_part_inherits_its_question_type_unless_it_has_its_own(self):
        self.edit("mock-exam1.md", "Type: justify\nTopic: §2, §3", "Topic: §2, §3")
        self.fails("exam1 UNCHECKED Q2(b) (trace)")

    def test_a_type_line_in_a_code_block_doesnt_count(self):
        self.edit("mock-exam1.md", "**(a) (1 pt)** Every tree", "```\nType: compute\n```\n\n**(a) (1 pt)** Every tree")
        self.edit("mock-exam1.md", "**(b) (1 pt)** Every graph", "**(b) (1 pt)**\n\n```\nType: compute\n```\n\nEvery graph")
        self.assertEqual(self.run_key()[0], 0)

    def test_lines_in_a_figure_block_dont_count(self):
        figure = ('<svg viewBox="0 0 10 10" role="img" aria-label="x">\n<text x="1" y="1">a\nType: compute\n'
                  '## Question 9\n**(z) (1 pt)** z</text>\n</svg>\n\n')
        self.edit("mock-exam1.md", "**(a) (1 pt)** Every tree", figure + "**(a) (1 pt)** Every tree")
        self.assertEqual(self.run_key()[0], 0)
        one_line = '<svg role="img" aria-label="y"><g/></svg>\nType: compute\n\n'
        self.edit("mock-exam1.md", "**(b) (1 pt)** Every graph", one_line + "**(b) (1 pt)** Every graph")
        self.fails("exam1 UNCHECKED Q4(a) (compute)")

    def test_a_line_break_in_the_mock_other_than_a_newline(self):
        # mockpage.py refuses it; split here at newlines alone, the Type: line would hide (round 3).
        self.edit("mock-exam1.md", "**(a) (1 pt)** Every tree", "Some prose.\x0cType: compute\n\n**(a) (1 pt)** Every tree")
        self.fails("a line break other than a newline: run mockpage.py")

    def test_a_value_for_a_part_the_mock_lacks_or_twice(self):
        self.fails("exam1 NOT IN THE MOCK Q5(a)", fill(BODY + '    value("exam1", "Q5(a)", 1)\n'))
        self.fails("exam1 TWICE Q1(a)", fill(BODY + '    value("exam1", "Q1(a)", 6)\n'))
        self.fails("value()'s first argument isn't a slug in MOCKS", fill(BODY + '    value("exam1-2", "Q1(a)", 6)\n'))

    def test_swapped_arguments_print_no_value(self):
        # Swapped, an argument the message would name is an answer (round 9).
        self.fails("value()'s first argument isn't a slug in MOCKS",
                   fill(BODY + '    value("S A B C T, dist(T) = 7", "exam1", "Q4(a)")\n'))
        self.fails("value()'s second argument isn't a part id like Q2(a)",
                   fill(BODY + '    value("exam1", "S A B C T, dist(T) = 7", "Q4(a)")\n'))
        self.fails("reasoned()'s second argument isn't a part id like Q2(a)",
                   fill(BODY + '    reasoned("exam1", "S A B C T", "a proof")\n'))

    def test_a_stop_in_values_prints_no_message_but_its_own_asserts(self):
        out = self.fails("assert failed: exam1 Q4(a): a tie on distance",
                         fill(BODY + '    assert False, "exam1 Q4(a): a tie on distance"\n'))
        self.assertRegex(out, r"mock_key\.py:\d+: assert failed")
        out = self.fails("values() stopped: KeyError at mock_key.py:",
                         fill(BODY + '    {}["S A B C T, dist(T) = 7"]\n'))
        self.assertIn("its message isn't printed", out)
        # Round 10: an exit, and anything the reference prints, stay off the terminal too.
        self.fails("values() stopped: SystemExit at mock_key.py:",
                   fill(BODY + '    raise SystemExit("S A B C T, dist(T) = 7")\n'))
        rc, out = self.run_key(fill(BODY + '    import sys\n    print("S A B C T, dist(T) = 7")\n'
                                           '    print("S A B C T", file=sys.stderr)\n'))
        self.assertEqual(rc, 0, out)

    def test_the_key_and_the_mock_have_the_same_parts(self):
        self.edit("mock-exam1-key.md", "**(d)** Answer: True\n", "")
        self.fails("exam1 KEY LACKS Q4(d)")
        self.edit("mock-exam1-key.md", "**(c)** Answer:", "**(d)** Answer: True\n\n**(e)** Answer: x\n\n**(c)** Answer:")
        self.fails("exam1 KEY HAS Q4(e), NOT IN THE MOCK")

    def test_a_part_twice_in_the_key(self):
        self.edit("mock-exam1-key.md", "**(d)** Answer: True\n", "**(d)** Answer: True\n\n**(d)** Answer: True\n")
        self.fails("exam1 KEY TWICE Q4(d)")

    def test_no_key_yet_still_writes_the_values(self):
        os.remove(os.path.join(self.hub, "practice", "mock-exam1-key.md"))
        self.fails("NO KEY practice/mock-exam1-key.md: write it from practice/mock-values-key.md")
        with open(self.out, encoding="utf-8") as f:
            self.assertIn("- Q2(a): S A B C T, dist(T) = 7", f.read())

    def test_an_empty_checker_fails(self):
        self.fails("NO MOCKS", fill(mocks="[]"))
        self.fails("exam1 UNCHECKED Q1(a)", fill(body="    pass\n"))

    def test_a_mock_of_proofs_alone_needs_no_value(self):
        with open(os.path.join(self.hub, "practice", "mock-proofs.md"), "w", encoding="utf-8") as f:
            f.write("# P\n\n**Time:** 5 minutes. **Total:** 2 points.\n\n---\n\n"
                    "## Question 1: Trees (2 points)\n\nType: prove\nTopic: §2\n\nProve it.\n")
        with open(os.path.join(self.hub, "practice", "mock-proofs-key.md"), "w", encoding="utf-8") as f:
            f.write("# ANSWER KEY: P\n\n## Question 1\n\n**(a)** Answer: by induction on n\n")
        rc, out = self.run_key(fill(body="    pass\n", mocks='["proofs"]'))
        self.assertEqual(rc, 0, out)
        self.assertIn("KEY OK: proofs: 0 of 1 parts asserted; reasoned: Q1(a)", out)
        page = os.path.join(self.hub, "page.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write("<p>Prove it.</p>")
        r = subprocess.run([sys.executable, os.path.join(REPO, "skills", "exam-prep", "scripts", "mock_leak.py"), page,
                            os.path.join(self.hub, "practice", "mock-proofs-key.md"), self.out],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_value_on_two_lines_and_a_mock_called_values(self):
        for broken in ("a\\nb", "a\\rb", "a\\x0cb", "a\\x85b"):
            with self.subTest(broken=broken):
                self.fails("spans lines", fill(BODY + f'    value("exam1", "Q4(a)", "{broken}")\n'))
        self.fails("a mock can't be called 'values'", fill(mocks='["exam1", "values"]'))

    def test_an_empty_answer_or_one_outside_a_question_block(self):
        self.edit("mock-exam1-key.md", "**(d)** Answer: True", "**(d)** Answer:")
        self.fails("exam1 KEY EMPTY Q4(d)")
        self.edit("mock-exam1-key.md", "**(d)** Answer:", "**(d)** Answer: True")
        self.edit("mock-exam1-key.md", "## Question 4\n", "## Question 4: True or false\n")
        self.fails("exam1 KEY LINE ")

    def test_a_crash_keeps_the_last_good_output(self):
        self.assertEqual(self.run_key()[0], 0)
        with open(self.out, encoding="utf-8") as f:
            good = f.read()
        rc, out = self.run_key(fill(BODY + '    value("exam1", "Q4(a)", degree4(5, 20))\n'))
        self.assertNotEqual(rc, 0)
        # The reference's own assert: its message may hold a value, so only where it stopped.
        self.assertIn("values() stopped: AssertionError at reference.py:", out)
        self.assertNotIn("no such graph", out)
        with open(self.out, encoding="utf-8") as f:
            self.assertEqual(f.read(), good)
        self.assertEqual([n for n in os.listdir(os.path.join(self.hub, "practice")) if n.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
