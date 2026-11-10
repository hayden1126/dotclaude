"""skills/exam-prep/scripts/verify_page.mjs: where it finds Playwright, its --steps file, and what
its browser checks catch.

No browser runs in the first two: each candidate install is a fake `playwright` package whose
index.mjs prints its name and exits 7 as soon as it is imported. PATH holds only node and, where a
case needs it, a fake `npm` whose `root -g` names a temp directory, so the machine's own installs
never count. $EXAM_PREP_PLAYWRIGHT wins; else the first of node_modules/ beside the page, the
working directory's _build/node_modules/ and node_modules/, and npm's global root; with none, it
names each place it looked, says how to install, and exits 2. A --steps file that isn't
{"<fig-id>": [{"act"?, "frames", "final"}]} exits 2 before any browser starts, and so does a
page with a step-through (a .fig-controls row) run with no --steps.

With EXAM_PREP_PLAYWRIGHT set (and MathJax's and the fonts' hosts allowed), the sample hub's page
broken one way at a time fails with the matching message: a step-through's frame count, last
frame, missing handler, missing or stray --steps entry, mode button no run presses, missing status
line, a status line showing the last frame from the start, a handler that throws or never ends, a
Prev that doesn't step back, a mode button that doesn't reset, a TeX error or undefined macro,
an overflow that shows only with the worked examples open, a MathJax startup that never finishes
or fails,
and an element named currentScript, which the pinned loader path ignores but which, unpinned,
moves MathJax's loader to its host; a long page whose rail scrolls the page with scrollIntoView,
which cuts a long jump short in WebKit (C1); and --views on the mock page (its own class)."""
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
VERIFY_PAGE = os.path.join(REPO, "skills", "exam-prep", "scripts", "verify_page.mjs")
ASSEMBLE = os.path.join(REPO, "skills", "exam-prep", "scripts", "assemble.py")
SAMPLE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "site")
MOCK = os.path.join(REPO, "tests", "exam_prep", "fixtures", "mock")
MOCKPAGE = os.path.join(REPO, "skills", "exam-prep", "scripts", "mockpage.py")
NODE = shutil.which("node")


def webkit_installed():
    """Whether the Playwright in $EXAM_PREP_PLAYWRIGHT has its WebKit build on disk."""
    probe = ("import(process.argv[1]).then((m) => { const p = m.webkit.executablePath(); "
             "console.log(require('fs').existsSync(p) ? 'yes' : 'no'); })")
    r = subprocess.run([NODE, "-e", probe, os.path.join(os.environ["EXAM_PREP_PLAYWRIGHT"], "index.mjs")],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip() == "yes"


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
        return subprocess.run([NODE, VERIFY_PAGE, page or self.page, os.path.join(self.tmp, "out"),
                               "--no-long-jump"],
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
            r = subprocess.run([NODE, VERIFY_PAGE, page, os.path.join(tmp, "out"), "--steps", steps,
                                "--no-long-jump"],
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

    def run_without_steps(self, page):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "p.html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(page)
            return subprocess.run([NODE, VERIFY_PAGE, path, os.path.join(tmp, "out"), "--no-long-jump"],
                                  env={"PATH": os.path.dirname(NODE), "HOME": tmp,
                                       "EXAM_PREP_PLAYWRIGHT": tmp},
                                  capture_output=True, text=True, timeout=60)

    def test_step_throughs_with_no_steps_file_are_bad_usage(self):
        # It would check less without saying so: exit 2 before any browser starts.
        r = self.run_without_steps('<figure id="fig-1-a"><svg></svg><div class="fig-controls">'
                                   '<button data-act="next">Next</button></div></figure>')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("the page has step-throughs (a .fig-controls row) and no --steps", r.stderr)
        # No step-through (a mock page, a class named only as text in code): on to Playwright.
        for page in ('<main><nav class="views"><button data-view="paper">Paper</button></nav></main>',
                     '<pre><code>&lt;div class="fig-controls"&gt;</code></pre>'):
            with self.subTest(page=page):
                r = self.run_without_steps(page)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("has no index.mjs", r.stderr)


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

    def fails(self, name, want, page=None, steps="same", long_jump=False):
        r = self.verify(name, page, steps, long_jump)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(want, r.stdout)
        return r.stdout

    def verify(self, name, page=None, steps="same", long_jump=False):
        """verify_page.mjs on page; without long_jump it passes --no-long-jump, which saves eight
        page loads a run (test_assemble's sample page run checks the default)."""
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
        if not long_jump:
            args.append("--no-long-jump")
        return subprocess.run(args, capture_output=True, text=True, timeout=600)

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
        self.fails("nosteps", "no expected run in --steps", steps={})

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

    def test_an_element_named_currentscript_cant_move_mathjax(self):
        # Unpinned, MathJax takes the host its components load from off document.currentScript,
        # which a named <img> replaces: ui/safe came from it (round 9, probed in Chromium).
        named = self.edit('<section class="note" id="sec-1">',
                          '<section class="note" id="sec-1"><img name="currentScript" src="https://x.example/es5/a.png" alt="">')
        r = self.verify("named", named)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ALL CHECKS PASS", r.stdout)
        pin = "      paths:{mathjax:'https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5'}\n"
        self.assertEqual(named.count(pin), 1)
        out = self.fails("unpinned", "scripts loaded from outside MathJax's own directory: https://x.example/es5/ui/safe.js",
                         page=named.replace(pin, ""))
        self.assertIn("window.MathJax doesn't pin loader.paths.mathjax", out)

    def test_no_mathjax_script_to_pin_to(self):
        self.fails("noid", 'no <script id="MathJax-script" src="..."> in the page', page=self.edit(' id="MathJax-script"', ""))

    def test_a_startup_that_never_finishes(self):
        self.fails("hang", "MathJax never finished typesetting", page=self.edit(
            "svg:{fontCache:'none'},", "svg:{fontCache:'none'}, startup:{pageReady:function(){return new Promise(function(){})}},"))

    def test_a_script_loaded_while_typesetting(self):
        # Requested after the page went quiet, so only the check once MathJax finishes sees it.
        late = ("startup:{pageReady:function(){return new Promise(function(r){setTimeout(r,1500)}).then(function(){"
                "var s=document.createElement('script');s.src='https://x.example/late.js';document.head.appendChild(s);"
                "return MathJax.startup.defaultPageReady();});}},")
        self.fails("late", "scripts loaded from outside MathJax's own directory: https://x.example/late.js",
                   page=self.edit("svg:{fontCache:'none'},", "svg:{fontCache:'none'}, " + late))

    def test_a_startup_that_fails(self):
        self.fails("reject", "MathJax failed while starting", page=self.edit(
            "svg:{fontCache:'none'},", "svg:{fontCache:'none'}, startup:{pageReady:function(){return Promise.reject(new Error('x'))}},"))

    def test_every_static_figure_is_shot(self):
        # Dry run 2: only a look catches an edge through a node, and static figures had no shot.
        page = self.edit("<p>Setup: the range 3 to 7.</p>",
                         '<p>Setup: the range 3 to 7.</p><figure id="fig-1-in-wex"><svg viewBox="0 0 120 60" '
                         'role="img" aria-label="A dot"><circle cx="60" cy="30" r="18" class="bx fill-surf"/>'
                         '</svg></figure>')
        r = self.verify("statics", page)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        shots = set(os.listdir(os.path.join(self.tmp, "statics", "shots")))
        for tag in ("1280-light", "1280-dark", "390-light", "390-dark"):
            for fig in ("fig-2-triangle", "fig-1-in-wex"):
                self.assertIn(f"{tag}-{fig}.png", shots)

    def test_a_static_figure_that_cannot_be_seen(self):
        # Its shot would show some other part of the page under the figure's name.
        self.fails("hidden", "static figure #fig-1-hidden not visible for its shot", page=self.edit(
            "<p>Setup: the range 3 to 7.</p>",
            '<p>Setup: the range 3 to 7.</p><figure id="fig-1-hidden" style="display:none"><svg '
            'viewBox="0 0 10 10" role="img" aria-label="A dot"><circle cx="5" cy="5" r="4"/></svg>'
            '</figure>'))

    def test_a_long_jump_cut_short_in_webkit(self):
        # The rail kept its active link in view with scrollIntoView, which in WebKit moves the page
        # too and cancels the smooth jump the click started (C1): Safari stopped short of the target.
        # The jump must still be moving when the spy reaches a link the rail has to scroll to, so
        # the page gets a fourth section, after the source key, with forty subsections.
        if not webkit_installed():
            self.skipTest("Playwright's WebKit isn't installed (npx playwright install webkit)")
        para = "<p>Filler, so the jump from the top to the last rail entry runs a long way.</p>" * 4
        subs = "".join(f'\n  <h3 id="sec-4-part-{i}">4.{i} Part {i}</h3>\n  {para}' for i in range(1, 41))
        long = self.edit("    </main>", '<section class="note" id="sec-4">\n  <h2><span class="n">§4</span>'
                         f'Filler</h2>{subs}\n</section>\n    </main>')
        r = self.verify("jumpok", long, long_jump=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("long jump webkit 1280px top->last ok: #sec-4-part-40", r.stdout)
        self.assertIn("long jump webkit 1280px bottom->first ok: #sec-1", r.stdout)
        fixed = ("    var a=byId[id]; if(a){ /* keep active visible in rail: scroll the rail alone, since\n"
                 "      scrollIntoView also moves the page and cancels a smooth jump in flight (WebKit) */\n"
                 "      var r=a.getBoundingClientRect(), rr=rail.getBoundingClientRect();\n"
                 "      if(r.top<rr.top+80) rail.scrollTop+=r.top-rr.top-80;\n"
                 "      else if(r.bottom>rr.bottom-20) rail.scrollTop+=r.bottom-rr.bottom+20;\n"
                 "    }\n")
        old = ("    var a=byId[id]; if(a&&a.scrollIntoView){ /* keep active visible in rail */\n"
               "      var r=a.getBoundingClientRect(); if(r.top<80||r.bottom>window.innerHeight-20) "
               "a.scrollIntoView({block:'nearest'});\n"
               "    }\n")
        self.assertEqual(long.count(fixed), 1)
        # The old rail code is pinned on a closed map: the sample's open map (K02) moves the page's
        # geometry so that WebKit cuts the old jump short going up only.
        opened = '<details class="examnav" open>'
        self.assertEqual(long.count(opened), 1)
        closed = long.replace(fixed, old).replace(opened, '<details class="examnav">')
        out = self.fails("jumpold", "long jump webkit 1280px top->last: #sec-4-part-40 landed at top",
                         page=closed, long_jump=True)
        self.assertIn("long jump webkit 1280px bottom->first: #sec-1 landed at top", out)

    def test_the_review_view_shows_its_blocks_and_hides_the_rest(self):
        r = self.verify("review", long_jump=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[1280-light-review]", r.stdout)
        self.assertIn("  review view shows its blocks and hides the rest", r.stdout)
        self.assertIn("hidden-target link #sec-2-walks: switched to Full notes", r.stdout)
        self.assertIn("long jump chromium 1280px review top->last ok:", r.stdout)
        self.assertIn("long jump chromium 390px review bottom->first ok: #sec-2", r.stdout)
        shots = set(os.listdir(os.path.join(self.tmp, "review", "shots")))
        for name in ("390-dark-review-top.png", "1280-light-review-map.png", "1280-light-review-key.png"):
            self.assertIn(name, shots)

    def test_a_review_view_that_shows_an_untagged_paragraph_or_hides_an_rv_block(self):
        # The page's own rule broken one way at a time: the check reads CHASSIS.md's rule itself.
        keep_p = self.edit("if(tag==='h2') return;", "if(tag==='h2'||tag==='p') return;")
        self.fails("rvshowp", "the Review view shows p", page=keep_p)
        hide_rv = self.edit("if(k.classList.contains('rv')){ if(h3) h3.classList.remove('rvhide'); return; }", "")
        out = self.fails("rvhide", "the Review view hides div.callout.warn.rv", page=hide_rv)
        self.assertIn("the Review view hides h3#sec-1-sums", out)
        no_must = self.edit("if(must&&(tag==='ul'||tag==='ol')){ must=false; return; }", "")
        self.fails("rvmust", "the Review view hides ul", page=no_must)

    def test_a_hidden_target_link_that_doesnt_switch_views(self):
        self.fails("rvlink", "hidden in the Review view, didn't switch to Full notes",
                   page=self.edit("if(!t||shown(t)) return;", "return;"))

    def test_overflow_inside_an_open_worked_example(self):
        self.fails("wexwide", "with the worked examples and map open", page=self.edit(
            "<p>Setup: the range 3 to 7.</p>",
            '<p>Setup: the range 3 to 7.</p><div style="width:3000px">wide</div>'))


@unittest.skipUnless(os.environ.get("EXAM_PREP_PLAYWRIGHT"),
                     "set EXAM_PREP_PLAYWRIGHT (and allow MathJax's and the fonts' hosts) to run "
                     "the browser checks")
class ViewsTest(unittest.TestCase):
    """--views on the fixture mock page (tests/exam_prep/fixtures/mock/, built by mockpage.py):
    it passes, with no scroll-spy target and one screenshot per view; broken, it names the view
    that lacks a part or holds an extra one, overflows with its stems open, has zero-size math, a
    MathJax \\href to javascript: (put in past mockpage.py's guard) or an inline event handler,
    shows the wrong pane,
    leaves the wrong button pressed or has no pane, and a page with fewer than two view buttons."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        out = os.path.join(cls.tmp, "mock.html")
        subprocess.run(["python3", MOCKPAGE, os.path.join(MOCK, "mock-exam1.md"), "--out", out,
                        "--backbone", os.path.join(MOCK, "backbone.md")], check=True, capture_output=True)
        with open(out, encoding="utf-8") as f:
            cls.page = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_views(self, name, page):
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        with open(os.path.join(d, "mock.html"), "w", encoding="utf-8") as f:
            f.write(page)
        r = subprocess.run([NODE, VERIFY_PAGE, os.path.join(d, "mock.html"), os.path.join(d, "shots"), "--views",
                            "--no-long-jump"],
                           capture_output=True, text=True, timeout=600)
        return r, os.path.join(d, "shots")

    def in_view(self, page, view, old, new):
        """page with old replaced by new once, inside #view-<view>."""
        a = page.index(f'<div id="view-{view}"')
        self.assertIn(old, page[a:])
        return page[:a] + page[a:].replace(old, new, 1)

    def test_the_mock_page_passes(self):
        r, shots = self.run_views("ok", self.page)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ALL CHECKS PASS", r.stdout)
        self.assertNotIn("spy", r.stdout)
        self.assertEqual(sorted(n for n in os.listdir(shots) if n.startswith("390-light-view-")),
                         ["390-light-view-paper.png", "390-light-view-topic.png", "390-light-view-type.png"])

    def test_parts_and_overflow_per_view(self):
        page = self.in_view(self.page, "type", 'data-part="Q4(d)"', 'data-gone="Q4(d)"')
        page = self.in_view(page, "topic", "</section>",
                            '<article class="part" data-part="Q9(a)">x</article></section>')
        page = self.in_view(page, "topic", "</summary>", '</summary><div style="width:3000px">wide</div>')
        page = self.in_view(page, "type", "</header>", '</header><style>#zz mjx-container{width:0!important}</style><p id="zz">\\(x\\)</p>')
        page = page.replace("<h1>", "<h1>\\(\\href{ JavaScript:alert(1)}{x}\\) \\(\\class{rail}{y}\\) ", 1)
        page = page.replace("<h1>", '<h1><span onmouseover="void 0"></span>', 1)
        # Without MathJax's ui/safe the macros' links and classes reach the page (round 8).
        self.assertEqual(page.count("load:['ui/safe'],"), 1)
        page = page.replace("load:['ui/safe'],", "", 1)
        r, _ = self.run_views("parts", page)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for want in ("view type: lacks Q4(d), which view paper holds", "view topic: holds Q9(a), which view paper lacks",
                     "view topic: horizontal overflow", "view type: 1 zero-size math", "javascript: links (a MathJax",
                     "1 elements with an inline event handler: span", "MathJax's ui/safe isn't loaded",
                     "elements inside math with a class, id or style"):
            self.assertIn(want, r.stdout)
        self.assertNotIn("view type: horizontal overflow", r.stdout)

    def test_mathjax_filters_what_its_macros_add(self):
        # The template loads ui/safe: a macro the build's text checks missed adds no link, class,
        # id or style, and the page passes (round 8).
        page = self.page.replace("<h1>", "<h1>\\(\\href{javascript:alert(1)}{a}\\) \\(\\class{rail}{b}\\) "
                                 "\\(\\cssId{q1a}{c}\\) \\(\\style{position:fixed;top:0}{d}\\) "
                                 # ui/safe keeps an mjx- id, as MathJax's own equation labels have.
                                 "\\(\\cssId{mjx-x}{e}\\) ", 1)
        r, _ = self.run_views("safe", page)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ALL CHECKS PASS", r.stdout)

    def test_a_javascript_link_ui_safe_lets_through(self):
        # Its scheme check finds no scheme in java<newline>script:, which a browser's URL parser
        # reads as javascript: (round 10): the link check still catches it.
        page = self.page.replace("<h1>", "<h1>\\(\\href{java\nscript:alert(1)}{a}\\) ", 1)
        r, _ = self.run_views("jsnl", page)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("javascript: links", r.stdout)

    def test_a_style_in_math_that_loads_an_image(self):
        # ui/safe keeps a cursor style; an image-set() in it loads (round 10).
        page = self.page.replace("<h1>", '<h1>\\(\\style{cursor:image-set("https://x.example/a.png" 1x),auto}{q}\\) ', 1)
        r, _ = self.run_views("imgset", page)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("elements inside math with a class, id or style", r.stdout)

    def test_a_broken_switcher_and_a_missing_pane(self):
        page = self.page.replace("if(pane) pane.hidden=!on;", "", 1)
        page = page.replace("b.setAttribute('aria-pressed',on?'true':'false');", "", 1)
        self.assertEqual(page.count('id="view-topic"'), 1)
        page = page.replace('id="view-topic"', 'id="view-topix"')
        r, _ = self.run_views("switch", page)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for want in ("view type: shows view-paper", "view type: pressed buttons paper",
                     "view topic: no #view-topic for its button"):
            self.assertIn(want, r.stdout)

    def test_fewer_than_two_buttons(self):
        page = re.sub(r'\s*<button type="button" data-view="(type|topic)".*?</button>', "", self.page)
        r, _ = self.run_views("buttons", page)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("--views: 1 view buttons", r.stdout)


if __name__ == "__main__":
    unittest.main()
