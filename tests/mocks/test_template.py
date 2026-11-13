"""skills/mocks/template/mock.html: the shell's behaviour in a real browser (stdlib only).

Drives the template through layout_check's Browser and Page: screens and the jumps
questions make, Shows on, the corner controls, drag to pan, Copy choices, the kept
scroll position and the named config errors. Browser cases skip with the reason
printed to stderr when no chrome-headless-shell is found.
"""
import importlib.util
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "skills/mocks/template/mock.html"
CHECK = ROOT / "skills/mocks/scripts/layout_check.py"

spec = importlib.util.spec_from_file_location("layout_check", CHECK)
layout_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout_check)

try:
    BROWSER = layout_check.find_browser()
    SKIP_REASON = ""
except layout_check.NoBrowser as exc:
    BROWSER = None
    SKIP_REASON = f"browser cases skipped: {exc}"
    print(SKIP_REASON, file=sys.stderr)

SIZE = (1440, 800)
MAIN_OPEN = "<main>${page}"
SCREENS_LINE = 'const SCREENS = ["Orders", "Customers"];\n'
CUSTOMERS_SCREENS = 'screens: ["Customers"] }'
ORDERS_SCREENS = ', screens: ["Orders"] }'
DENSITY_ENTRY = '{ label: "Density", options: ["Comfortable", "Compact"], corner: true }'
STATUS_QUESTION = "How should an order's status read?"
SUMMARY_QUESTION = "Is the summary strip worth its height?"
LAST_ORDER_QUESTION = "Should a customer's last order show in the list?"

# Clicks the button labelled `text` among `selector`, then waits for the render to
# load when the click changed it, and for two painted frames either way.
CLICK_JS = """(async (selector, text) => {
  const button = [...document.querySelectorAll(selector)].find((b) => b.textContent.trim() === text);
  if (!button) throw new Error(`no button "${text}" in ${selector}`);
  const app = document.getElementById("app"), before = app.srcdoc;
  const loaded = new Promise((done) => { app.addEventListener("load", done, { once: true }); setTimeout(done, 2000); });
  button.click();
  if (app.srcdoc !== before) await loaded;
  await new Promise(requestAnimationFrame);
  await new Promise(requestAnimationFrame);
})"""

PRESSED_JS = """((selector) => [...document.querySelectorAll(selector)]
  .filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.textContent.trim()))"""

HEADING_JS = 'document.getElementById("app").contentDocument.querySelector("main h1").textContent'

FRAMES_JS = "new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"

SCROLLS_JS = """(() => {
  const frame = document.getElementById("frame"), win = document.getElementById("app").contentWindow;
  return { frameLeft: frame.scrollLeft, frameTop: frame.scrollTop, renderLeft: win.scrollX, renderTop: win.scrollY };
})()"""


def question(n: int) -> str:
    """The option buttons in question n's box, counted from 1 as the panel numbers them."""
    return f"#questions > .m-box:nth-child({n}) .m-seg button"


def where(n: int) -> str:
    return f"#questions > .m-box:nth-child({n}) .m-where button"


def apply_edits(source: str, edits) -> str:
    for old, new in edits:
        count = source.count(old)
        if count != 1:
            raise AssertionError(f"edit target matched {count} times, not once: {old!r}")
        source = source.replace(old, new)
    return source


class StaticFiles(unittest.TestCase):
    def test_every_edit_string_matches_the_template_once(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        for target in (MAIN_OPEN, SCREENS_LINE, CUSTOMERS_SCREENS, ORDERS_SCREENS, DENSITY_ENTRY):
            with self.subTest(target):
                self.assertEqual(source.count(target), 1)


@unittest.skipUnless(BROWSER, SKIP_REASON or "browser found")
class Template(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.browser = layout_check.Browser(BROWSER)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="mock-template-test-")
        self.addCleanup(self.dir.cleanup)

    def open(self, edits=(), size=SIZE) -> layout_check.Page:
        path = pathlib.Path(self.dir.name, f"page-{len(list(pathlib.Path(self.dir.name).iterdir()))}.html")
        path.write_text(apply_edits(TEMPLATE.read_text(encoding="utf-8"), edits), encoding="utf-8")
        tab = layout_check.Page(self.browser)
        self.addCleanup(tab.close)
        self.assertTrue(tab.open(path.as_uri(), *size), "the page never settled")
        return tab

    def click(self, tab, selector: str, text: str):
        tab.evaluate(f"{CLICK_JS}({selector!r}, {text!r})")

    def pressed(self, tab, selector: str) -> list:
        return tab.evaluate(f"{PRESSED_JS}({selector!r})")

    def errors(self, tab) -> list:
        return tab.evaluate(layout_check.READ_ERRORS_JS)

    def mouse(self, tab, kind: str, x: float, y: float, buttons: int):
        tab.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                                              "buttons": buttons, "clickCount": 1})

    def test_a_question_jumps_to_its_screen_and_moves_the_top_row(self):
        tab = self.open()
        self.assertEqual(self.pressed(tab, "#c-screen button"), ["Orders"])
        self.click(tab, question(3), "Leave it out")
        self.assertEqual(self.pressed(tab, "#c-screen button"), ["Customers"])
        self.assertEqual(self.pressed(tab, question(3)), ["Leave it out"])
        self.assertEqual(self.pressed(tab, where(3)), ["Customers"])
        self.assertEqual(self.pressed(tab, where(1)), [])
        self.assertEqual(tab.evaluate(HEADING_JS), "Customers")
        self.click(tab, question(1), "Plain text")
        self.assertEqual(self.pressed(tab, "#c-screen button"), ["Orders"])
        self.assertEqual(tab.evaluate(HEADING_JS), "Orders")
        self.assertEqual(self.errors(tab), [])

    def test_an_answer_on_a_screen_it_shows_on_stays_put(self):
        tab = self.open()
        self.click(tab, question(1), "Plain text")
        self.assertEqual(self.pressed(tab, "#c-screen button"), ["Orders"])
        self.click(tab, question(2), "Drop it")   # no screens: never jumps
        self.click(tab, "#c-screen button", "Customers")
        self.click(tab, question(2), "Keep it")
        self.assertEqual(self.pressed(tab, "#c-screen button"), ["Customers"])

    def test_shows_on_jumps_and_presses(self):
        tab = self.open()
        self.assertEqual(self.pressed(tab, where(1)), ["Orders"])
        self.click(tab, where(3), "Customers")
        self.assertEqual(self.pressed(tab, "#c-screen button"), ["Customers"])
        self.assertEqual(self.pressed(tab, where(3)), ["Customers"])
        self.assertEqual(self.pressed(tab, where(1)), [])
        self.assertEqual(tab.evaluate(HEADING_JS), "Customers")
        self.assertEqual(self.pressed(tab, question(3)), ["Show it"], "Shows on changes no answer")

    def test_a_corner_control_changes_the_render(self):
        tab = self.open()
        self.assertEqual(tab.evaluate('[...document.querySelectorAll("#corner .m-ctl > span")].map((s) => s.textContent)'),
                         ["Zoom", "Density"])
        self.assertFalse(tab.evaluate('[...document.querySelectorAll("#bar .m-ctl > span")]'
                                      '.some((s) => s.textContent === "Density")'))
        self.assertIn("--pad: 13px", tab.evaluate('document.getElementById("app").srcdoc'))
        self.click(tab, "#corner .m-seg button", "Compact")
        self.assertIn("--pad: 7px", tab.evaluate('document.getElementById("app").srcdoc'))
        self.assertEqual(self.pressed(tab, "#corner .m-seg button"), ["Fit", "Compact"])

    def test_the_corner_sits_on_the_frame_s_bottom_left_at_every_zoom(self):
        tab = self.open()
        for zoom in ("Fit", "100%", "200%", "300%"):
            self.click(tab, "#c-zoom button", zoom)
            box = tab.evaluate("""(() => {
              const f = document.getElementById("frame"), r = f.getBoundingClientRect();
              const c = document.getElementById("corner").getBoundingClientRect();
              return { left: c.left - r.left, bottom: r.top + f.clientHeight - c.bottom, right: r.right - c.right,
                       height: c.height };
            })()""")
            with self.subTest(zoom):
                self.assertAlmostEqual(box["left"], 8, delta=1)
                self.assertAlmostEqual(box["bottom"], 8, delta=1)
                self.assertGreater(box["right"], 0)
                self.assertLess(box["height"], 40, "one row at the laptop frame")
        self.assertEqual(self.errors(tab), [])

    def test_a_drag_pans_the_frame_and_the_render_s_own_button_still_clicks(self):
        button = '<button id="hit" onclick="this.textContent = \'pressed\'">Press</button>'
        tab = self.open([(MAIN_OPEN, "<main>" + button + "${page}")])
        self.click(tab, "#c-zoom button", "200%")
        hit = tab.evaluate("""(() => {
          const app = document.getElementById("app"), a = app.getBoundingClientRect(), k = a.width / app.width;
          const r = app.contentDocument.getElementById("hit").getBoundingClientRect();
          return { x: a.left + (r.left + r.width / 2) * k, y: a.top + (r.top + r.height / 2) * k };
        })()""")
        self.mouse(tab, "mousePressed", hit["x"], hit["y"], 1)
        self.mouse(tab, "mouseReleased", hit["x"], hit["y"], 0)
        tab.evaluate(FRAMES_JS)
        self.assertEqual(tab.evaluate('document.getElementById("app").contentDocument.getElementById("hit").textContent'),
                         "pressed")
        self.assertEqual(tab.evaluate(SCROLLS_JS)["frameLeft"], 0)
        self.assertEqual(tab.evaluate('getComputedStyle(document.getElementById("app").contentDocument'
                                      '.documentElement).cursor'), "grab")

        frame = tab.evaluate('(() => { const r = document.getElementById("frame").getBoundingClientRect();'
                             ' return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()')
        x, y = frame["x"], frame["y"]
        self.mouse(tab, "mousePressed", x, y, 1)
        self.mouse(tab, "mouseMoved", x - 2, y - 2, 1)
        tab.evaluate(FRAMES_JS)
        self.assertEqual(tab.evaluate(SCROLLS_JS)["frameLeft"], 0, "a 2 px move is still a click")
        for step in range(1, 11):
            self.mouse(tab, "mouseMoved", x - 20 * step, y - 15 * step, 1)
        self.mouse(tab, "mouseReleased", x - 200, y - 150, 0)
        tab.evaluate(FRAMES_JS)
        scrolls = tab.evaluate(SCROLLS_JS)
        self.assertAlmostEqual(scrolls["frameLeft"], 200, delta=2)
        self.assertAlmostEqual(scrolls["frameTop"], 150, delta=2)
        self.assertEqual(self.errors(tab), [])

    def test_no_grab_while_the_frame_fits(self):
        tab = self.open()
        cursor = 'getComputedStyle(document.getElementById("app").contentDocument.documentElement).cursor'
        self.assertEqual(tab.evaluate(cursor), "auto")
        frame = tab.evaluate('(() => { const r = document.getElementById("frame").getBoundingClientRect();'
                             ' return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()')
        self.mouse(tab, "mousePressed", frame["x"], frame["y"], 1)
        self.mouse(tab, "mouseMoved", frame["x"] - 100, frame["y"] - 100, 1)
        self.mouse(tab, "mouseReleased", frame["x"] - 100, frame["y"] - 100, 0)
        self.assertEqual(tab.evaluate(SCROLLS_JS)["frameTop"], 0)

    def copy_with(self, tab, clipboard_js: str) -> dict:
        tab.evaluate(f'Object.defineProperty(navigator, "clipboard", {{ value: {clipboard_js}, configurable: true }})')
        tab.evaluate('document.getElementById("copy").click()')
        tab.evaluate(FRAMES_JS)
        return tab.evaluate("""(() => {
          const area = document.getElementById("copy-text");
          return { copied: window.__copied, note: document.getElementById("copied").textContent,
                   shown: !area.hidden, value: area.value, focused: document.activeElement === area,
                   selected: area.selectionStart === 0 && area.selectionEnd === area.value.length };
        })()""")

    def expected_choices(self, status: str, summary: str, last: str) -> str:
        return "\n".join(["Orders page mock", f"1. {STATUS_QUESTION}: {status}", f"2. {SUMMARY_QUESTION}: {summary}",
                          f"3. {LAST_ORDER_QUESTION}: {last}"])

    def test_copy_choices_copies_the_picks(self):
        tab = self.open()
        self.assertFalse(tab.evaluate('document.getElementById("choices").hidden'))
        self.assertEqual(tab.evaluate('document.getElementById("copy").closest(".m-seg")'), None)
        self.click(tab, question(1), "Plain text")
        self.click(tab, question(3), "Leave it out")
        got = self.copy_with(tab, "{ writeText: (t) => { window.__copied = t; return Promise.resolve(); } }")
        self.assertEqual(got["copied"], self.expected_choices("Plain text", "Keep it", "Leave it out"))
        self.assertEqual(got["note"], "Copied.")
        self.assertFalse(got["shown"])

    def test_copy_choices_falls_back_to_a_selected_textarea(self):
        for name, clipboard in (("rejects", '{ writeText: () => Promise.reject(new Error("denied")) }'),
                                ("absent", "undefined")):
            with self.subTest(name):
                tab = self.open()
                self.click(tab, question(2), "Drop it")
                got = self.copy_with(tab, clipboard)
                self.assertTrue(got["shown"])
                self.assertEqual(got["value"], self.expected_choices("Pill", "Drop it", "Show it"))
                self.assertTrue(got["focused"] and got["selected"], got)
                self.assertEqual(got["note"], "Press Ctrl+C to copy.")
                self.assertEqual(self.errors(tab), [])

    def test_no_options_hides_the_choices_box(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        edits = [(f', options: {o}', "") for o in ('["Pill", "Plain text"]', '["Keep it", "Drop it"]',
                                                    '["Show it", "Leave it out"]')]
        self.assertTrue(all(source.count(old) == 1 for old, _ in edits))
        tab = self.open(edits)
        self.assertTrue(tab.evaluate('document.getElementById("choices").hidden'))

    def test_an_answer_keeps_both_scroll_positions_and_a_new_view_resets_them(self):
        tab = self.open([(MAIN_OPEN, MAIN_OPEN + '<div style="height: 2400px"></div>')])
        self.click(tab, "#c-zoom button", "200%")
        tab.evaluate("""(() => {
          const frame = document.getElementById("frame");
          frame.scrollTo((frame.scrollWidth - frame.clientWidth) / 2, (frame.scrollHeight - frame.clientHeight) / 2);
          document.getElementById("app").contentWindow.scrollTo(0, 600);
        })()""")
        tab.evaluate(FRAMES_JS)
        before = tab.evaluate(SCROLLS_JS)
        self.assertGreater(before["frameLeft"], 100)
        self.assertGreater(before["frameTop"], 100)
        self.assertEqual(before["renderTop"], 600)
        self.click(tab, question(2), "Drop it")
        self.click(tab, "#bar button", "Dark")
        self.click(tab, "#corner .m-seg button", "Compact")
        self.assertEqual(tab.evaluate(SCROLLS_JS), before, "same frame and screen: both scrollers hold")

        self.click(tab, "#c-screen button", "Customers")
        self.assertEqual(tab.evaluate(SCROLLS_JS), {"frameLeft": 0, "frameTop": 0, "renderLeft": 0, "renderTop": 0})

        tab.evaluate('document.getElementById("frame").scrollTo(300, 300);'
                     'document.getElementById("app").contentWindow.scrollTo(0, 400)')
        tab.evaluate(FRAMES_JS)
        self.click(tab, question(1), "Plain text")   # jumps back to Orders
        self.assertEqual(tab.evaluate(SCROLLS_JS), {"frameLeft": 0, "frameTop": 0, "renderLeft": 0, "renderTop": 0})

        tab.evaluate('document.getElementById("frame").scrollTo(300, 300);'
                     'document.getElementById("app").contentWindow.scrollTo(0, 400)')
        tab.evaluate(FRAMES_JS)
        self.click(tab, "#c-frame button", "iPad")
        self.assertEqual(tab.evaluate(SCROLLS_JS), {"frameLeft": 0, "frameTop": 0, "renderLeft": 0, "renderTop": 0})
        self.assertEqual(self.errors(tab), [])

    def test_a_size_change_that_keeps_the_html_still_keeps_the_scroll(self):
        # The template's render never reads state.frame, so a Size click doesn't reload it: the
        # scroll that follows must be saved under the new view, not the one the page loaded with.
        tab = self.open([(MAIN_OPEN, MAIN_OPEN + '<div style="height: 2400px"></div>')])
        self.click(tab, "#c-frame button", "iPad")
        tab.evaluate('document.getElementById("app").contentWindow.scrollTo(0, 400)')
        tab.evaluate(FRAMES_JS)
        self.click(tab, question(2), "Drop it")
        self.assertEqual(tab.evaluate(SCROLLS_JS)["renderTop"], 400)
        self.assertEqual(self.errors(tab), [])

    def test_numeric_options_press_like_names(self):
        tab = self.open([('options: ["Pill", "Plain text"]', "options: [14, 16]"),
                         (DENSITY_ENTRY, '{ label: "Density", options: [1, 2], corner: true }')])
        self.assertEqual(self.errors(tab), [])
        self.assertEqual(self.pressed(tab, question(1)), ["14"])
        self.assertEqual(self.pressed(tab, "#corner .m-seg button"), ["Fit", "1"])
        self.click(tab, question(1), "16")
        self.assertEqual(self.pressed(tab, question(1)), ["16"])

    def test_a_press_on_the_render_s_other_clickables_never_pans(self):
        # A summary and a role=button div, pressed with a jitter past the pan threshold.
        extras = ('<details id="more"><summary id="s">More</summary>Hidden</details>'
                  '<div id="d" role="button" onclick="this.textContent = \'pressed\'">Press</div>')
        tab = self.open([(MAIN_OPEN, "<main>" + extras + "${page}")])
        self.click(tab, "#c-zoom button", "200%")
        for target in ("s", "d"):
            with self.subTest(target):
                p = tab.evaluate(f"""(() => {{
                  const app = document.getElementById("app"), a = app.getBoundingClientRect(), k = a.width / app.width;
                  const r = app.contentDocument.getElementById("{target}").getBoundingClientRect();
                  return {{ x: a.left + (r.left + 4) * k, y: a.top + (r.top + r.height / 2) * k }};
                }})()""")
                self.mouse(tab, "mousePressed", p["x"], p["y"], 1)
                self.mouse(tab, "mouseMoved", p["x"] + 6, p["y"], 1)
                self.mouse(tab, "mouseReleased", p["x"] + 6, p["y"], 0)
                tab.evaluate(FRAMES_JS)
                self.assertEqual(tab.evaluate(SCROLLS_JS)["frameLeft"], 0)
        doc = 'document.getElementById("app").contentDocument'
        self.assertTrue(tab.evaluate(f'{doc}.getElementById("more").open'))
        self.assertEqual(tab.evaluate(f'{doc}.getElementById("d").textContent'), "pressed")

    def test_a_press_on_a_widget_wired_by_script_never_pans(self):
        # Clicks wired with addEventListener: a tab with tabindex, a div with its own pointer
        # cursor, and a plain div its author marked data-no-pan.
        extras = ('<div id="t" role="tab" tabindex="0">Tab</div>'
                  '<div id="c" style="cursor: pointer">Card</div>'
                  '<div id="n" data-no-pan>Knob</div>'
                  '<script>for (const id of ["t", "c", "n"]) document.getElementById(id)'
                  '.addEventListener("click", (e) => { e.currentTarget.textContent = "pressed"; });<\\/script>')
        tab = self.open([(MAIN_OPEN, "<main>" + extras + "${page}")])
        self.click(tab, "#c-zoom button", "200%")
        doc = 'document.getElementById("app").contentDocument'
        for target in ("t", "c", "n"):
            with self.subTest(target):
                p = tab.evaluate(f"""(() => {{
                  const app = document.getElementById("app"), a = app.getBoundingClientRect(), k = a.width / app.width;
                  const r = app.contentDocument.getElementById("{target}").getBoundingClientRect();
                  return {{ x: a.left + (r.left + 4) * k, y: a.top + (r.top + r.height / 2) * k }};
                }})()""")
                self.mouse(tab, "mousePressed", p["x"], p["y"], 1)
                self.mouse(tab, "mouseMoved", p["x"] + 6, p["y"], 1)
                self.mouse(tab, "mouseReleased", p["x"] + 6, p["y"], 0)
                tab.evaluate(FRAMES_JS)
                self.assertEqual(tab.evaluate(SCROLLS_JS)["frameLeft"], 0)
                self.assertEqual(tab.evaluate(f'{doc}.getElementById("{target}").textContent'), "pressed")

    def test_a_render_that_scrolls_inside_keeps_and_resets_that_scroll(self):
        # An app shell: the page is fixed and <main> scrolls.
        shell = '<main style="height: 600px; overflow: auto">${page}<div style="height: 2400px"></div>'
        tab = self.open([(MAIN_OPEN, shell)])
        main = 'document.getElementById("app").contentDocument.querySelector("main")'
        tab.evaluate(f"{main}.scrollTop = 400")
        tab.evaluate(FRAMES_JS)
        self.click(tab, question(2), "Drop it")
        self.click(tab, "#bar button", "Dark")
        self.assertEqual(tab.evaluate(f"{main}.scrollTop"), 400, "same view: the inner scroll holds")
        self.click(tab, "#c-frame button", "iPad")
        self.assertEqual(tab.evaluate(f"{main}.scrollTop"), 0, "a new frame starts at the top")
        tab.evaluate(f"{main}.scrollTop = 300")
        tab.evaluate(FRAMES_JS)
        self.click(tab, question(2), "Keep it")
        self.assertEqual(tab.evaluate(f"{main}.scrollTop"), 300)
        self.assertEqual(self.errors(tab), [])

    def test_a_scroller_with_an_id_survives_an_answer_that_moves_it(self):
        # "Drop it" removes the stats strip, so every later child of <main> moves up one place.
        box = 'style="height: 200px; overflow: auto"><div style="height: 2400px"></div>'
        pane = (f'<main>${{page}}<section {box}</section><div class="plain" {box}</div>'
                f'<div id="pane" {box}</div>')
        tab = self.open([(MAIN_OPEN, pane)])
        doc = 'document.getElementById("app").contentDocument'
        tab.evaluate(f'{doc}.querySelector("section").scrollTop = 300; {doc}.getElementById("pane").scrollTop = 500')
        tab.evaluate(FRAMES_JS)
        self.click(tab, question(2), "Drop it")
        self.assertEqual(tab.evaluate(f'{doc}.getElementById("pane").scrollTop'), 500, "found by its id")
        self.assertEqual(tab.evaluate(f'{doc}.querySelector(".plain").scrollTop'), 0,
                         "the section's old place now holds a div: it isn't given the section's scroll")
        self.assertEqual(self.errors(tab), [])

    def test_a_scroll_cut_short_by_a_shorter_render_comes_back_in_full(self):
        shell = '<main style="height: 600px; overflow: auto">${page}<div style="height: 1200px"></div>'
        tab = self.open([(MAIN_OPEN, shell)])
        main = 'document.getElementById("app").contentDocument.querySelector("main")'
        tab.evaluate(f"{main}.scrollTop = 1e6")
        tab.evaluate(FRAMES_JS)
        bottom = tab.evaluate(f"{main}.scrollTop")
        self.click(tab, question(2), "Drop it")
        self.assertLess(tab.evaluate(f"{main}.scrollTop"), bottom, "the shorter render can't scroll as far")
        self.click(tab, question(2), "Keep it")
        self.assertEqual(tab.evaluate(f"{main}.scrollTop"), bottom)

    def test_a_focusable_wrapper_still_pans(self):
        tab = self.open([(MAIN_OPEN, '<main><div tabindex="0">${page}</div>')])
        self.click(tab, "#c-zoom button", "200%")
        p = tab.evaluate("""(() => {
          const app = document.getElementById("app"), a = app.getBoundingClientRect(), k = a.width / app.width;
          const r = app.contentDocument.querySelector("tbody td").getBoundingClientRect();
          return { x: a.left + (r.left + r.width / 2) * k, y: a.top + (r.top + r.height / 2) * k };
        })()""")
        self.mouse(tab, "mousePressed", p["x"], p["y"], 1)
        for step in range(1, 6):
            self.mouse(tab, "mouseMoved", p["x"] - 20 * step, p["y"], 1)
        self.mouse(tab, "mouseReleased", p["x"] - 100, p["y"], 0)
        tab.evaluate(FRAMES_JS)
        self.assertAlmostEqual(tab.evaluate(SCROLLS_JS)["frameLeft"], 100, delta=2)

    def test_a_press_on_the_render_s_own_scrollbar_never_pans(self):
        tab = self.open([(MAIN_OPEN, MAIN_OPEN + '<div style="height: 2400px"></div>')])
        self.click(tab, "#c-zoom button", "200%")
        p = tab.evaluate("""(() => {
          const app = document.getElementById("app"), a = app.getBoundingClientRect(), k = a.width / app.width;
          const root = app.contentDocument.documentElement;
          return { gutter: app.width - root.clientWidth, x: a.left + (root.clientWidth + 2) * k, y: a.top + 200 * k };
        })()""")
        self.assertGreater(p["gutter"], 0, "the render needs its own scrollbar for this case")
        before = tab.evaluate(SCROLLS_JS)
        self.mouse(tab, "mousePressed", p["x"], p["y"], 1)
        self.mouse(tab, "mouseMoved", p["x"] - 40, p["y"] + 40, 1)
        self.mouse(tab, "mouseReleased", p["x"] - 40, p["y"] + 40, 0)
        tab.evaluate(FRAMES_JS)
        after = tab.evaluate(SCROLLS_JS)
        self.assertEqual((after["frameLeft"], after["frameTop"]), (before["frameLeft"], before["frameTop"]))

    def test_config_mistakes_are_named(self):
        cases = {
            "screens typo": ([(CUSTOMERS_SCREENS, 'screens: ["Customer"] }')],
                             f'QUESTIONS[2] ("{LAST_ORDER_QUESTION}"): screens names "Customer"'),
            "screens without SCREENS": ([(SCREENS_LINE, "")],
                                        f'QUESTIONS[0] ("{STATUS_QUESTION}") has screens, but the config has no SCREENS'),
            "control without options": ([(DENSITY_ENTRY, '{ label: "Density", corner: true }')],
                                        'CONTROLS[0] ("Density") needs options'),
            "control without a label": ([(DENSITY_ENTRY, '{ options: ["Comfortable", "Compact"] }')],
                                        "CONTROLS[0] needs a label"),
            "control named like state": ([(DENSITY_ENTRY, '{ label: "screen", options: ["A", "B"] }')],
                                         'CONTROLS[0] ("screen")'),
        }
        for name, (edits, needle) in cases.items():
            with self.subTest(name):
                tab = self.open(edits)
                errors = self.errors(tab)
                self.assertTrue(any(needle in e for e in errors), errors)
                self.assertTrue(tab.evaluate('!!document.querySelector("#c-frame button")'),
                                "the page still builds, so the check can measure it")

    def test_a_config_may_use_plain_names_the_shell_avoids(self):
        names = ("const screens = {}, controls = [], where = 0, groups = 0, pan = 0, corner = 0, problems = 0,"
                 " app = 0, main = 0, scale = 0, frameEl = 0, topRow = 0;\nfunction update() {}\nfunction refit() {}\n")
        tab = self.open([(SCREENS_LINE, SCREENS_LINE + names)])
        self.assertEqual(self.errors(tab), [])
        self.click(tab, question(3), "Leave it out")
        self.assertEqual(self.pressed(tab, "#c-screen button"), ["Customers"])

    def test_no_screens_is_today_s_page(self):
        edits = [(SCREENS_LINE, ""), (", " + CUSTOMERS_SCREENS, " }"), (ORDERS_SCREENS, " }")]
        tab = self.open(edits)
        self.assertEqual(self.errors(tab), [])
        self.assertFalse(tab.evaluate('!!document.querySelector("#c-screen, .m-where")'))
        self.click(tab, question(3), "Leave it out")
        self.assertEqual(self.errors(tab), [])

    def test_one_screen_hides_the_group(self):
        tab = self.open([(SCREENS_LINE, 'const SCREENS = ["Orders"];\n'),
                         (", " + CUSTOMERS_SCREENS, " }")])
        self.assertEqual(self.errors(tab), [])
        self.assertFalse(tab.evaluate('!!document.querySelector("#c-screen")'))
        self.assertEqual(self.pressed(tab, where(1)), ["Orders"])


if __name__ == "__main__":
    unittest.main()
