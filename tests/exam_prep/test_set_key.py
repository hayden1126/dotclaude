"""skills/exam-prep/templates/verify-set-key.py, a practice set's values for the tutor (09-tutor).

Copied into a temp hub's `_build/verify/set_key.py` beside a small reference, filled by text
replacement the way a hub fills it, and run as the workflow runs it (`python3 -I` from the hub
root) on an extract of a homework in `_build/extract/`. Filled, it prints SET OK with three parts
computed, one reasoned and one left to the notes, writes each value with its intermediate lines
under a STOP header to practice/tutor/HW3-values-key.md (out of 08's `practice/*-key.md` globs),
and shows no answer in the terminal. Its parts are the extract's question blocks: a stem's or a
page's block isn't one, nor is a line in fenced code (a `# comment` there doesn't end the block),
and deeper ids (Q5b.1, Q5bii, Q6.1) are parts. Every part needs a value or a reasoned() with why,
except one each of whose Shape lines starts with a kind no arithmetic answers, asks for nothing
after it and names no computation; every Shape line of a part counts (a second line, a wrapped
line, a block in another extract), a part with none fails, and a bulleted Shape line or
`**Shape**:` counts. A code fence closes only on a bare fence as long as its opener, and one that
never closes stops the run, naming its line; a set's heading that names a question but no part
id or stem (`Q2(a)`) fails, naming its line. It fails, naming the part, on a value for a part no
extract has or named twice, an empty value or why, a value that isn't text or holds a character
UTF-8 can't write, no sets or one that isn't a doc id, a set with no blocks, an extract that isn't
UTF-8, and a module of the verify folder imported outside values(); a value() or reasoned() call
whose doc isn't one or whose part isn't a part id (swapped arguments, a word like "Quicksort" too)
prints no value. A pending() part waits for the reference: SET OK lists it, and the values file
has no section for it. A stop in values() prints an assert's message only when the assert is the
checker's own, and an exit's, a print's, a raw or buffered write's or a child process's output
never. A run that stops or fails a check keeps the last good values file, and leaves no temp
file."""
import glob
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE = os.path.join(REPO, "skills", "exam-prep", "templates", "verify-set-key.py")
SECRETS = ["pop T: 7", "pop C: 4", "edges: 6"]

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
'''

EXTRACT = """# HW3 Graphs, PDF pp.1-2 (extract)
Sources: HW3 (2 pages)
Every page image was viewed.

### [HW3 p.1] Homework 3
Answer every question. Show your work.

### [HW3 Q1 stem] Degrees
A graph has the degrees 3, 3, 2, 2, 2.

### [HW3 Q1a] Edges
Pages: [HW3 p.1]
(a) (2 pts) How many edges does it have?
**Shape:** compute
**Conventions:** none

### [HW3 Q1b] Degree four
Pages: [HW3 p.1]
(b) (2 pts) A graph on 5 vertices with 9 edges has degrees 3 and 4 only. How many have degree 4?
**Shape:** calculate from the handshake lemma
**Conventions:** none

### [HW3 Q2a] Dijkstra
Pages: [HW3 p.2]
(a) (4 pts) Run Dijkstra from S. Give the order vertices are popped and each distance.
**Shape:** trace under stated conventions
**Conventions:** ties broken alphabetically

### [HW3 Q3] A proof
Pages: [HW3 p.2]
(4 pts) Prove that every tree on n vertices has n - 1 edges.
**Shape:** prove
**Conventions:** none

### [HW3 Q4] Degree table
Pages: [HW3 p.2]
(2 pts) Fill in the degree of each vertex of the graph above.
**Shape:** fill a table
**Conventions:** none

Coverage: PDF pp.1-2; 7 blocks; 0 image only; 0 flagged unreadable.
"""

BODY = '''    from reference import degree4, dijkstra, edges
    value("HW3", "Q1a", f"edges: {edges([3, 3, 2, 2, 2])}")
    value("HW3", "Q1b", str(degree4(5, 9)))
    graph = {"S": {"A": 2, "B": 5}, "A": {"B": 1, "C": 4}, "B": {"C": 1, "T": 6}, "C": {"T": 3}}
    order, dist = dijkstra(graph, "S")
    value("HW3", "Q2a", "\\n".join(f"pop {u}: {dist[u]}" for u in order))
    reasoned("HW3", "Q4", "each degree is read off the figure, as  §2.3 counts them")
'''


def fill(body=BODY, sets='["HW3"]'):
    with open(TEMPLATE, encoding="utf-8") as f:
        text = f.read()
    text, n = re.subn(r"    # ---- Fill in: import the reference.*?\n    pass\n", lambda m: body, text, flags=re.S)
    assert n == 1, "the template's fill-in block moved"
    assert "SETS = []" in text
    return text.replace("SETS = []", f"SETS = {sets}", 1)


def template():
    spec = importlib.util.spec_from_file_location("set_key_template", TEMPLATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ShapeTest(unittest.TestCase):
    def test_only_a_kind_no_arithmetic_answers_is_left_to_the_notes(self):
        settled = template().settled
        for shape in ("prove", "Prove by induction on n", "show that the tree is unique", "justify a label",
                      "true or false", "True/false with a witness", "formulate", "explain why",
                      "define the term", "proof", "a proof by induction", "justifications",
                      "true or false with a counterexample"):
            with self.subTest(shape=shape):
                self.assertTrue(settled(shape))
        # Fail closed: any other wording, or a settled kind that names a computation, needs a value.
        for shape in ("trace under stated conventions", "fill a table", "compute", "traced run", "simulate",
                      "describe the order the nodes are popped", "evaluate the sum", "short answer", "",
                      "justify the computed bound", "prove the table is complete", "approve the trace",
                      "prove the traced order is shortest",
                      # Round 2: a trace behind a settled verb, and a second clause.
                      "classify each edge (tree, back, forward, cross)", "formulate the recurrence and solve it",
                      "show that Dijkstra fails on this graph", "explain the output of the program",
                      "prove the bound; give the count", "justify it, then find the cut",
                      "explain what the given code returns", "show that it counts each edge once",
                      "prove the tree is unique and give its height", "prove the bound; give an example",
                      "justify it, then give a cut", "explain what happens when you run it",
                      "explain how to find a cut", "explain how solving gives the bound"):
            with self.subTest(shape=shape):
                self.assertFalse(settled(shape))


class SetKeyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.hub = tmp.name
        self.verify = os.path.join(self.hub, "_build", "verify")
        os.makedirs(self.verify)
        os.makedirs(os.path.join(self.hub, "_build", "extract"))
        self.extract = os.path.join(self.hub, "_build", "extract", "hw3.md")
        with open(self.extract, "w", encoding="utf-8") as f:
            f.write(EXTRACT)
        with open(os.path.join(self.verify, "reference.py"), "w", encoding="utf-8") as f:
            f.write(REFERENCE)
        self.out = os.path.join(self.hub, "practice", "tutor", "HW3-values-key.md")

    def edit(self, old, new):
        with open(self.extract, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(old, text)
        with open(self.extract, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new, 1))

    def run_key(self, script=None):
        with open(os.path.join(self.verify, "set_key.py"), "w", encoding="utf-8") as f:
            f.write(fill() if script is None else script)
        r = subprocess.run([sys.executable, "-I", os.path.join("_build", "verify", "set_key.py")],
                           cwd=self.hub, capture_output=True, text=True, timeout=60)
        for secret in SECRETS:
            self.assertNotIn(secret, r.stdout + r.stderr, "the terminal shows an answer")
        return r.returncode, r.stdout + r.stderr

    def fails(self, message, script=None):
        rc, out = self.run_key(script)
        self.assertEqual(rc, 1, out)
        self.assertIn(message, out)
        self.assertNotIn("SET OK", out)
        return out

    def test_the_filled_checker_passes(self):
        rc, out = self.run_key()
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.strip().splitlines()[-1],
                         "SET OK: HW3: 3 of 5 parts computed; reasoned: Q4; from the notes: Q3")
        with open(self.out, encoding="utf-8") as f:
            values = f.read()
        self.assertTrue(values.startswith("# TUTOR VALUES: HW3 "), values[:80])
        self.assertIn("> **STOP. Quarantined key.**", values)
        self.assertIn("\n## [HW3 Q1a]\n\n    edges: 6\n", values)
        self.assertIn("\n## [HW3 Q2a]\n\n    pop S: 0\n    pop A: 2\n    pop B: 3\n    pop C: 4\n    pop T: 7\n",
                      values)
        self.assertIn("\n## [HW3 Q4]\n\nReasoned: each degree is read off the figure, as §2.3 counts them\n", values)
        # 08's leak checks and STATUS checks glob practice/*-key.md: a homework's values stay out.
        self.assertEqual(glob.glob(os.path.join(self.hub, "practice", "*-key.md")), [])
        self.assertEqual(os.listdir(os.path.dirname(self.out)), ["HW3-values-key.md"])

    def test_a_computable_part_needs_a_value(self):
        self.fails("HW3 UNCHECKED Q2a", fill(BODY.replace('    value("HW3", "Q2a"', '    0 and value("HW3", "Q2a"')))
        out = self.fails("HW3 UNCHECKED Q4", fill(BODY.replace('    reasoned("HW3", "Q4"', '    0 and reasoned("HW3", "Q4"')))
        self.assertNotIn("UNCHECKED Q3", out)
        # A Shape that asks for no arithmetic is left to the notes; a part with no Shape line fails.
        no_q4 = fill(BODY.replace('    reasoned("HW3", "Q4"', '    0 and reasoned("HW3", "Q4"'))
        self.edit("**Shape:** fill a table\n", "**Shape:** justify a label\n")
        rc, out = self.run_key(no_q4)
        self.assertEqual(rc, 0, out)
        self.assertIn("from the notes: Q3, Q4", out)
        self.edit("**Shape:** justify a label\n", "")
        self.fails("HW3 NO SHAPE Q4", no_q4)

    def test_a_part_can_wait_for_the_reference(self):
        rc, out = self.run_key(fill(BODY.replace('    value("HW3", "Q2a"', '    pending("HW3", "Q2a")\n    0 and value("HW3", "Q2a"')))
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.strip().splitlines()[-1],
                         "SET OK: HW3: 2 of 5 parts computed; reasoned: Q4; waiting: Q2a; from the notes: Q3")
        with open(self.out, encoding="utf-8") as f:
            self.assertNotIn("[HW3 Q2a]", f.read())
        self.fails("HW3 TWICE Q2a", fill(BODY + '    pending("HW3", "Q2a")\n'))
        self.fails("pending()'s second argument isn't a part id like Q2a", fill(BODY + '    pending("HW3", "pop T: 7")\n'))

    def test_a_shape_line_in_list_form_counts(self):
        no_q4 = fill(BODY.replace('    reasoned("HW3", "Q4"', '    0 and reasoned("HW3", "Q4"'))
        for line in ("- **Shape:** justify a label\n", "**Shape**: justify a label\n", "* **Shape:** prove\n"):
            with self.subTest(line=line):
                self.edit("**Shape:** fill a table\n", line)
                rc, out = self.run_key(no_q4)
                self.assertEqual(rc, 0, out)
                self.edit(line, "**Shape:** fill a table\n")

    def test_fenced_code_in_a_part_is_its_text(self):
        # Round 1: a column-0 comment in a trace's code ended the block, so its Shape was lost
        # and the part read as having nothing to compute.
        self.edit("**Shape:** trace under stated conventions\n",
                  "```\n# start at S\n### [HW3 Q9] not a block\nrun(S)\n```\n"
                  "**Shape:** trace under stated conventions\n")
        self.fails("HW3 UNCHECKED Q2a", fill(BODY.replace('    value("HW3", "Q2a"', '    0 and value("HW3", "Q2a"')))
        self.fails("HW3 NOT A PART Q9", fill(BODY + '    reasoned("HW3", "Q9", "inside a fence")\n'))
        self.assertEqual(self.run_key()[0], 0)

    def test_a_fence_closes_only_on_its_own_bare_fence(self):
        # Round 2: a fence that never closed, or closed early, hid the parts after it.
        no_q4 = fill(BODY.replace('    reasoned("HW3", "Q4"', '    0 and reasoned("HW3", "Q4"'))
        for fence in ("```\n~~~\n", "```\n```python\n", "````\n```\n", "~~~\n```\n"):
            with self.subTest(fence=fence):
                self.edit("**Shape:** prove\n", "**Shape:** prove\n" + fence)
                try:
                    out = self.fails("_build/extract/hw3.md:33: a code fence opened here never closes", no_q4)
                    self.assertNotIn("UNCHECKED", out)
                finally:
                    self.edit("**Shape:** prove\n" + fence, "**Shape:** prove\n")
        for fence in ("```\nrun(S)\n```\n", "````\n```\n````\n", "~~~ text\n```\n~~~~\n"):
            with self.subTest(fence=fence):
                self.edit("**Shape:** prove\n", "**Shape:** prove\n" + fence)
                try:
                    self.fails("HW3 UNCHECKED Q4", no_q4)
                finally:
                    self.edit("**Shape:** prove\n" + fence, "**Shape:** prove\n")

    def test_a_heading_that_names_no_part_fails(self):
        # Round 2: 08's Q2(a) form and other near-misses read as no part at all.
        for heading in ("### [HW3 Q2(a)] x", "### [HW3 Q4a-b] x", "### [HW3 Q4a, Q4b] x", "### [HW3 Q4a ] x",
                        "## [HW3 Q7] x", "#### [HW3 Q7] x", "###[HW3 Q7] x", "### [HW3 Q7 stem ] x"):
            with self.subTest(heading=heading):
                with open(self.extract, "a", encoding="utf-8") as f:
                    f.write(f"\n{heading}\n**Shape:** compute\n")
                try:
                    self.fails("HW3 BAD HEADING _build/extract/hw3.md:43: a ### [HW3 Q..] heading")
                finally:
                    self.edit(f"\n{heading}\n**Shape:** compute\n", "")
        # A stem, a page, a word and another doc's headings pass.
        with open(self.extract, "a", encoding="utf-8") as f:
            f.write("\n### [HW3 Q7 stem] x\n### [HW3 p.2] x\n### [HW3 Quiz] x\n### [HW4 Q2(a)] x\n")
        self.assertEqual(self.run_key()[0], 0)
        # A set whose every heading is malformed names them, not only its missing blocks.
        self.fails("HW4 BAD HEADING _build/extract/hw3.md:", fill(body="    pass\n", sets='["HW4"]'))

    def test_deeper_part_ids(self):
        with open(self.extract, "a", encoding="utf-8") as f:
            for part in ("Q5b.1", "Q5bii", "Q6.1"):
                f.write(f"\n### [HW3 {part}] Deeper\n**Shape:** compute\n")
        self.fails("HW3 UNCHECKED Q5b.1")
        rc, out = self.run_key(fill(BODY + '    value("HW3", "Q5b.1", "1")\n    value("HW3", "Q5bii", "2")\n'
                                           '    reasoned("HW3", "Q6.1", "read off §2.3\'s rule")\n'))
        self.assertEqual(rc, 0, out)
        self.assertIn("SET OK: HW3: 5 of 8 parts computed; reasoned: Q4, Q6.1; from the notes: Q3", out)

    def test_every_shape_line_of_a_part_counts(self):
        # Round 2: only the first Shape line counted, so "prove" hid a second "compute".
        self.edit("**Shape:** prove\n", "**Shape:** prove\n**Shape:** compute\n")
        self.fails("HW3 UNCHECKED Q3")
        # A wrapped Shape line reads whole, up to a blank line or the next field.
        for wrapped in ("**Shape:** prove\n  the traced order is shortest\n", "**Shape:** prove\nthe traced order\n"):
            with self.subTest(wrapped=wrapped):
                self.edit("**Shape:** prove\n**Shape:** compute\n", wrapped)
                self.fails("HW3 UNCHECKED Q3")
                self.edit(wrapped, "**Shape:** prove\n**Shape:** compute\n")
        for after in ("**Conventions:** as the table of §2 says\n", "\nThe table above is traced.\n",
                      "Solution [HW3S p.1]: the table\n", "- a traced table\n", "```\nx\n```\nthe traced table\n",
                      "### [HW3 Q8] x\ntraced table\n**Shape:** prove\n",
                      "#### [HW4 Q2] y\n**Shape:** compute\n"):
            with self.subTest(after=after):
                self.edit("**Shape:** prove\n**Shape:** compute\n", "**Shape:** prove\n" + after)
                rc, out = self.run_key()
                self.assertEqual(rc, 0, out)
                self.edit("**Shape:** prove\n" + after, "**Shape:** prove\n**Shape:** compute\n")
        # The same part in a second extract (a block across a chunk boundary) counts too.
        self.edit("**Shape:** prove\n**Shape:** compute\n", "**Shape:** prove\n")
        with open(os.path.join(self.hub, "_build", "extract", "hw3-2.md"), "w", encoding="utf-8") as f:
            f.write("### [HW3 Q3] A proof, continued\n**Shape:** fill a table\n")
        self.fails("HW3 UNCHECKED Q3")
        os.remove(os.path.join(self.hub, "_build", "extract", "hw3-2.md"))
        self.edit("**Shape:** prove\n", "**Shape:** prove\n**Shape:** compute\n")
        # A heading inside a block ends it: a Shape under it belongs to no part.
        self.edit("**Shape:** prove\n**Shape:** compute\n", "\n## Notes\n\n**Shape:** compute\n")
        self.fails("HW3 NO SHAPE Q3")
        self.edit("\n## Notes\n\n**Shape:** compute\n", "**Shape:** compute\n")
        self.fails("HW3 UNCHECKED Q3")

    def test_stems_and_pages_arent_parts(self):
        self.fails("HW3 NOT A PART Q1: no ### [HW3 Q1] block", fill(BODY + '    reasoned("HW3", "Q1", "a stem")\n'))
        self.fails("reasoned()'s second argument isn't a part id like Q2a",
                   fill(BODY + '    reasoned("HW3", "p.1", "a page")\n'))
        # A block named by a word, not a question number, isn't a part either.
        with open(self.extract, "a", encoding="utf-8") as f:
            f.write("\n### [HW3 Quiz] Practice quiz\n**Shape:** compute\n")
        self.assertEqual(self.run_key()[0], 0)

    def test_a_part_no_extract_has_or_twice(self):
        self.fails("HW3 NOT A PART Q9a", fill(BODY + '    value("HW3", "Q9a", "1")\n'))
        self.fails("HW3 TWICE Q1a", fill(BODY + '    reasoned("HW3", "Q1a", "again")\n'))

    def test_swapped_arguments_print_no_value(self):
        self.fails("value()'s first argument isn't a doc id in SETS",
                   fill(BODY + '    value("pop T: 7", "HW3", "Q3")\n'))
        self.fails("value()'s second argument isn't a part id like Q2a",
                   fill(BODY + '    value("HW3", "pop T: 7", "Q3")\n'))
        self.fails("reasoned()'s first argument isn't a doc id in SETS",
                   fill(BODY + '    reasoned("HW4", "Q3", "a proof")\n'))
        # Round 1: a one-word answer starting with Q passed as a part id and was printed.
        self.fails("value()'s second argument isn't a part id like Q2a",
                   fill(BODY + '    value("HW3", "Quicksort", "Q3")\n'))

    def test_a_value_needs_text_and_a_reasoned_part_its_why(self):
        self.fails("value('HW3', 'Q3') needs text", fill(BODY + '    value("HW3", "Q3", 6)\n'))
        self.fails("value('HW3', 'Q3') is empty", fill(BODY + '    value("HW3", "Q3", " \\n ")\n'))
        self.fails("reasoned('HW3', 'Q3') needs a why", fill(BODY + '    reasoned("HW3", "Q3", "  ")\n'))
        self.fails("value('HW3', 'Q3') holds a character UTF-8 can't write",
                   fill(BODY + '    value("HW3", "Q3", "pop T: 7 \\ud800")\n'))
        self.fails("reasoned('HW3', 'Q3') holds a character UTF-8 can't write",
                   fill(BODY + '    reasoned("HW3", "Q3", "\\udfff")\n'))

    def test_a_value_on_many_lines_stays_inside_its_part(self):
        rc, out = self.run_key(fill(BODY + '    value("HW3", "Q3", "step 1\\n## [HW3 Q9a]\\x85step 3")\n'))
        self.assertEqual(rc, 0, out)
        with open(self.out, encoding="utf-8") as f:
            values = f.read()
        self.assertIn("\n## [HW3 Q3]\n\n    step 1\n    ## [HW3 Q9a]\n    step 3\n", values)
        self.assertNotRegex(values, r"(?m)^## \[HW3 Q9a\]")

    def test_a_stop_in_values_prints_no_message_but_its_own_asserts(self):
        out = self.fails("assert failed: HW3 Q2a: a tie on distance",
                         fill(BODY + '    assert False, "HW3 Q2a: a tie on distance"\n'))
        self.assertRegex(out, r"set_key\.py:\d+: assert failed")
        out = self.fails("values() stopped: KeyError at set_key.py:", fill(BODY + '    {}["pop T: 7"]\n'))
        self.assertIn("its message isn't printed", out)
        self.fails("values() stopped: SystemExit at set_key.py:", fill(BODY + '    raise SystemExit("pop T: 7")\n'))
        rc, out = self.run_key(fill(BODY + '    import sys\n    print("pop T: 7")\n'
                                           '    print("pop C: 4", file=sys.stderr)\n'))
        self.assertEqual(rc, 0, out)
        # Below Python's streams too: a raw write and a child process (round 1).
        rc, out = self.run_key(fill(BODY + '    import os, subprocess, sys\n    os.write(1, b"pop T: 7")\n'
                                           '    os.write(2, b"pop C: 4")\n'
                                           # Round 2: left in a buffer, it reached the terminal at exit.
                                           '    sys.__stdout__.write("pop T: 7")\n'
                                           '    sys.__stderr__.write("pop C: 4")\n'
                                           '    subprocess.run(["echo", "edges: 6"])\n'
                                           '    subprocess.run([sys.executable, "-c", "import sys; sys.stderr.write(\'pop T: 7\')"])\n'))
        self.assertEqual(rc, 0, out)
        self.assertIn("SET OK", out)

    def test_a_module_imported_outside_values_is_refused(self):
        # Round 2: an import hoisted to the top runs before the null device is in place.
        script = fill().replace("# -I leaves the script dir out\n", "# -I leaves the script dir out\nimport reference\n", 1)
        self.assertIn("\nimport reference\n", script)
        out = self.fails("set_key.py: reference is imported outside values(): import it inside values()", script)
        self.assertFalse(os.path.exists(self.out))

    def test_no_sets_a_bad_doc_id_and_a_set_with_no_blocks(self):
        self.fails("NO SETS", fill(sets="[]"))
        self.fails("SETS holds an entry that isn't a doc id like HW3", fill(body="    pass\n", sets='["../x"]'))
        self.fails("SETS holds an entry that isn't a doc id like HW3", fill(body="    pass\n", sets='[3]'))
        self.fails("HW9: no question blocks in _build/extract/", fill(body="    pass\n", sets='["HW9"]'))

    def test_an_extract_that_isnt_utf8_is_named(self):
        with open(os.path.join(self.hub, "_build", "extract", "bad.md"), "wb") as f:
            f.write(b"### [HW3 Q5] x\n\xff\n")
        self.fails("_build/extract/bad.md isn't UTF-8 text")

    def test_a_stop_keeps_the_last_good_output(self):
        self.assertEqual(self.run_key()[0], 0)
        with open(self.out, encoding="utf-8") as f:
            good = f.read()
        rc, out = self.run_key(fill(BODY + '    value("HW3", "Q3", str(degree4(5, 20)))\n'))
        self.assertNotEqual(rc, 0)
        # The reference's own assert: its message may hold a value, so only where it stopped.
        self.assertIn("values() stopped: AssertionError at reference.py:", out)
        self.assertNotIn("no such graph", out)
        with open(self.out, encoding="utf-8") as f:
            self.assertEqual(f.read(), good)
        # A failed check keeps it too (round 1): two answers for a part never land in the file.
        self.fails("HW3 TWICE Q1a", fill(BODY + '    reasoned("HW3", "Q1a", "again")\n'))
        with open(self.out, encoding="utf-8") as f:
            self.assertEqual(f.read(), good)


if __name__ == "__main__":
    unittest.main()
