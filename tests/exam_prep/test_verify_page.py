"""skills/exam-prep/scripts/verify_page.mjs: where it finds Playwright, its --steps file, and what
its browser checks catch.

No browser runs in the first two: each candidate install is a fake `playwright` package whose
index.mjs prints its name and exits 7 as soon as it is imported. PATH holds only node and, where a
case needs it, a fake `npm` whose `root -g` names a temp directory, so the machine's own installs
never count. $EXAM_PREP_PLAYWRIGHT wins; else the first of node_modules/ beside the page, the
working directory's _build/node_modules/ and node_modules/, and npm's global root; with none, it
names each place it looked, says how to install, and exits 2. A --steps file that isn't
{"<fig-id>": [{"act"?, "frames", "final"}]} exits 2 before any browser starts.

With EXAM_PREP_PLAYWRIGHT set (and MathJax's and the fonts' hosts allowed), the sample hub's page
broken one way at a time fails with the matching message: a step-through's frame count, last
frame, missing handler, missing or stray --steps entry, mode button no run presses, missing status
line, a status line showing the last frame from the start, a handler that throws or never ends, a
Prev that doesn't step back, a mode button that doesn't reset, a TeX error or undefined macro, and
an overflow that shows only with the worked examples open."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERIFY_PAGE = os.path.join(REPO, "skills", "exam-prep", "scripts", "verify_page.mjs")
ASSEMBLE = os.path.join(REPO, "skills", "exam-prep", "scripts", "assemble.py")
SAMPLE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "site")
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not on PATH")
class PlaywrightProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bin = self.mk("bin")
        os.symlink(NODE, os.path.join(self.bin, "node"))
        self.hub = self.mk("hub")
        self.page = os.path.join(self.mk("hub/_build"), "notes.html")
        with open(self.page, "w", encoding="utf-8") as f:
            f.write("<p>x</p>\n")

    def mk(self, rel):
        d = os.path.join(self.tmp, rel)
        os.makedirs(d, exist_ok=True)
        return d

    def fake(self, rel, name):
        d = self.mk(rel)
        with open(os.path.join(d, "index.mjs"), "w", encoding="utf-8") as f:
            f.write(f"console.log('fake playwright {name}');\nprocess.exit(7);\n")
        return d

    def npm(self, root):
        p = os.path.join(self.bin, "npm")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"#!/bin/sh\necho '{root}'\n")
        os.chmod(p, 0o755)

    def run_it(self, cwd=None, env_dir=None, page=None):
        env = {"PATH": self.bin, "HOME": self.tmp}
        if env_dir is not None:
            env["EXAM_PREP_PLAYWRIGHT"] = env_dir
        return subprocess.run([NODE, VERIFY_PAGE, page or self.page, os.path.join(self.tmp, "out")],
                              cwd=cwd or self.tmp, env=env, capture_output=True, text=True,
                              timeout=60)

    def assertLoaded(self, r, name):
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertIn(f"fake playwright {name}", r.stdout)

    def test_an_install_beside_the_page(self):
        self.fake("hub/_build/node_modules/playwright", "beside")
        self.assertLoaded(self.run_it(), "beside")

    def test_the_working_directorys_build_install(self):
        self.fake("hub/_build/node_modules/playwright", "cwd-build")
        page = os.path.join(self.mk("elsewhere"), "p.html")
        shutil.copy(self.page, page)
        self.assertLoaded(self.run_it(cwd=self.hub, page=page), "cwd-build")

    def test_the_working_directorys_own_install(self):
        self.fake("hub/node_modules/playwright", "cwd")
        self.assertLoaded(self.run_it(cwd=self.hub), "cwd")

    def test_npms_global_root(self):
        self.fake("global/playwright", "global")
        self.npm(os.path.join(self.tmp, "global"))
        self.assertLoaded(self.run_it(), "global")

    def test_a_local_install_comes_before_the_global_one(self):
        self.fake("global/playwright", "global")
        self.npm(os.path.join(self.tmp, "global"))
        self.fake("hub/_build/node_modules/playwright", "beside")
        self.assertLoaded(self.run_it(), "beside")

    def test_the_environment_variable_wins(self):
        self.fake("hub/_build/node_modules/playwright", "beside")
        chosen = self.fake("chosen/playwright", "chosen")
        self.assertLoaded(self.run_it(env_dir=chosen), "chosen")

    def test_a_variable_naming_no_package_is_a_usage_error(self):
        self.fake("hub/_build/node_modules/playwright", "beside")
        r = self.run_it(env_dir=self.mk("empty"))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("has no index.mjs", r.stderr)
        self.assertNotIn("fake playwright", r.stdout)

    def test_none_found_says_how_to_install(self):
        r = self.run_it(cwd=self.hub)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no Playwright found", r.stderr)
        self.assertIn(os.path.join(self.hub, "_build", "node_modules", "playwright"), r.stderr)
        self.assertIn(os.path.join(self.hub, "node_modules", "playwright"), r.stderr)
        self.assertIn("npm install playwright && npx playwright install chromium", r.stderr)

    def test_none_found_names_the_global_root_it_tried(self):
        self.npm(os.path.join(self.tmp, "global"))
        r = self.run_it()
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn(os.path.join(self.tmp, "global", "playwright"), r.stderr)


@unittest.skipUnless(NODE, "node is not on PATH")
class StepsFileTest(unittest.TestCase):
    def check(self, text, ok):
        with tempfile.TemporaryDirectory() as tmp:
            page = os.path.join(tmp, "p.html")
            with open(page, "w", encoding="utf-8") as f:
                f.write("<p>x</p>\n")
            steps = os.path.join(tmp, "steps.json")
            with open(steps, "w", encoding="utf-8") as f:
                f.write(text)
            r = subprocess.run([NODE, VERIFY_PAGE, page, os.path.join(tmp, "out"), "--steps", steps],
                               env={"PATH": os.path.dirname(NODE), "HOME": tmp,
                                    "EXAM_PREP_PLAYWRIGHT": tmp},
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            # A good file gets past the --steps check to the (empty) Playwright directory.
            self.assertIn("has no index.mjs" if ok else "--steps", r.stderr)

    def test_a_good_file_passes(self):
        self.check('{"fig-1-a": [{"frames": 2, "final": "done"}, {"act": "b", "frames": 1, "final": "x"}]}',
                   ok=True)

    def test_bad_files_are_usage_errors(self):
        for bad in ("not json", "[]", '{"fig-1-a": []}', '{"fig-1-a": [{"frames": 0, "final": "x"}]}',
                    '{"fig-1-a": [{"frames": 1.5, "final": "x"}]}', '{"fig-1-a": [{"frames": 2}]}',
                    '{"fig-1-a": [{"frames": 2, "final": "  "}]}',
                    '{"fig-1-a": [{"frames": 2, "final": "x", "act": 3}]}'):
            with self.subTest(bad=bad):
                self.check(bad, ok=False)


@unittest.skipUnless(os.environ.get("EXAM_PREP_PLAYWRIGHT"),
                     "set EXAM_PREP_PLAYWRIGHT (and allow MathJax's and the fonts' hosts) to run "
                     "the browser checks")
class BrowserCatchesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        root = os.path.join(cls.tmp, "site")
        shutil.copytree(SAMPLE, root)
        spec = importlib.util.spec_from_file_location("assemble", ASSEMBLE)
        assemble = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(assemble)
        with contextlib.redirect_stdout(io.StringIO()):
            assert assemble.main(["--root", root]) == 0
        with open(os.path.join(root, "_build", "notes.html"), encoding="utf-8") as f:
            cls.page = f.read()
        with open(os.path.join(root, "_build", "frag", "steps.json"), encoding="utf-8") as f:
            cls.steps = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def fails(self, name, want, page=None, steps="same"):
        page = self.page if page is None else page
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        with open(os.path.join(d, "notes.html"), "w", encoding="utf-8") as f:
            f.write(page)
        args = [NODE, VERIFY_PAGE, os.path.join(d, "notes.html"), os.path.join(d, "shots"), "--spy",
                "sec-1-sums"]
        if steps is not None:
            with open(os.path.join(d, "steps.json"), "w", encoding="utf-8") as f:
                json.dump(self.steps if steps == "same" else steps, f)
            args += ["--steps", os.path.join(d, "steps.json")]
        r = subprocess.run(args, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(want, r.stdout)

    def edit(self, old, new):
        self.assertEqual(self.page.count(old), 1, old)
        return self.page.replace(old, new)

    def test_wrong_frame_count(self):
        self.fails("frames", "2 frames, --steps says 3",
                   steps={"fig-2-walk": [{"frames": 3, "final": "Walk A-B-C: 2 edges."}]})

    def test_wrong_last_frame(self):
        self.fails("final", "last frame doesn't show",
                   steps={"fig-2-walk": [{"frames": 2, "final": "Walk A-C"}]})

    def test_no_handler(self):
        self.fails("nohandler", "no window.NotesFig['fig-2-walk'] handler",
                   page=self.edit("window.NotesFig['fig-2-walk'] = function", "window.NotesFigX = function"))

    def test_no_steps_entry(self):
        self.fails("nosteps", "no expected run in --steps", steps=None)

    def test_a_stray_steps_entry(self):
        self.fails("stray", "--steps lists #fig-9-x",
                   steps=dict(self.steps, **{"fig-9-x": [{"frames": 1, "final": "x"}]}))

    def test_a_handler_that_throws(self):
        self.fails("throws", "errors while stepping",
                   page=self.edit("fig.dataset.step = k;", "fig.dataset.step = k; if (k === 2) null.x;"))

    def test_a_run_that_never_ends(self):
        self.fails("never", "Next never disabled", page=self.edit(
            "fig.querySelector('button[data-act=\"next\"]').disabled = k === walk.length - 1;", ""))

    def test_a_prev_that_doesnt_step_back(self):
        self.fails("prev", "Prev took", page=self.edit("else if (act === 'prev' && k > 0) k--;", ""))

    def test_a_mode_button_that_doesnt_reset(self):
        self.fails("mode", "(acb): last frame doesn't show",
                   page=self.edit("if (WALKS[act]) { mode = act; k = 0; }", ""))

    def test_a_mode_no_run_presses(self):
        self.fails("modes", 'no run in --steps presses mode "acb"',
                   steps={"fig-2-walk": [self.steps["fig-2-walk"][0]]})

    def test_no_status_line(self):
        self.fails("nostatus", "no status line", page=self.edit(' aria-live="polite"', ""))

    def test_a_status_line_that_shows_the_end_from_the_start(self):
        self.fails("early", "before any press", page=self.edit(
            "k === 0 ? '<strong>Step 0.</strong> Start at A. Press Next.'",
            "k === 0 ? 'Walk A-B-C: 2 edges. Walk A-C-B: 2 edges.'"))

    def test_tex_errors(self):
        self.fails("texerr", "TeX errors", page=self.edit(
            "Count its terms: \\(b - a + 1\\).", "Count its terms: \\(\\frac{b}\\) and \\(\\foo\\)."))

    def test_overflow_inside_an_open_worked_example(self):
        self.fails("wexwide", "with the worked examples and map open", page=self.edit(
            "<p>Setup: the range 3 to 7.</p>",
            '<p>Setup: the range 3 to 7.</p><div style="width:3000px">wide</div>'))


if __name__ == "__main__":
    unittest.main()
