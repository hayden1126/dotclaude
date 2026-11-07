"""skills/mocks: the template page and scripts/layout_check.py (stdlib only).

Each mutant is a temp copy of the template with a few exact string edits. It
must fail the check on the assertion it targets, and only on the assertions it
lists, so no assertion passes by being unable to fail. Every edit is matched
against the template in a browser-free test, so renaming a rule fails loudly
instead of turning a mutant into a pass. Browser cases skip with the reason
printed to stderr when no chrome-headless-shell is found.
"""
import importlib.util
import json
import os
import pathlib
import re
import subprocess
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

LINE = re.compile(r"^(?P<result>ok  |FAIL) (?P<scope>[^:]+): (?P<kind>[^:]+): (?P<got>.*)$")

BODY_HEIGHT = ("height: calc(100dvh - env(safe-area-inset-top, 0px) "
               "- env(safe-area-inset-bottom, 0px)); ")
PANEL_SCROLL = ".m-panel { min-height: 0; overflow-y: auto; padding: 1px;"
FIT_MIN = "Math.min(1, widthLeft / f.width, heightLeft / f.height)"
RESIZE_OBSERVER = 'new ResizeObserver(refit).observe(document.querySelector(".m-main"));\n'
RESIZE_LISTENER = 'addEventListener("resize", refit);\n'
PANEL_COLUMN = "minmax(var(--m-panel-min), 1fr)"
MAIN_ROWS = "grid-template-rows: minmax(0, 1fr);"
CONTROLS_OPEN = "const CONTROLS = [\n"
FRAMES_BLOCK = """const FRAMES = [
  { label: "Laptop", width: 1440, height: 900 },
  { label: "iPad", width: 1024, height: 768 },
  { label: "Phone", width: 390, height: 844 },
];
"""
FRAME_HOOK = 'id="frame"'
QUESTIONS_OPEN = "const QUESTIONS = [\n"
QUESTIONS_CLOSE = "\n];\nconst ABOUT"


def extra_groups(count: int) -> str:
    """CONTROLS entries that widen the top row."""
    return "".join(f'  {{ label: "Group {n}", options: ["First choice", "Second choice", "Third choice"] }},\n'
                   for n in range(count))


# Each mutant: its edits, the assertion it must fail, and any other assertion
# that its break also trips by design (a panel that stops scrolling spills past
# the page, so the page scrolls too).
MUTANTS = {
    "page_scrolls": {
        "edits": [("html { overflow: hidden; }", ""), (BODY_HEIGHT, "")],
        "kind": "no page scroll",
        "also": {"render on screen", "questions scroll"},
    },
    "render_off_screen": {
        "edits": [(FIT_MIN, "Math.min(1, widthLeft / f.width)")],
        "kind": "render on screen",
        "also": set(),
    },
    "too_many_controls": {
        "edits": [(CONTROLS_OPEN, CONTROLS_OPEN + extra_groups(9))],
        "kind": "top row",
        "also": set(),
    },
    "panel_does_not_scroll": {
        "edits": [(PANEL_SCROLL, ".m-panel { min-height: 0; padding: 1px;")],
        "kind": "questions scroll",
        "also": {"no page scroll"},
    },
    "render_moves_with_questions": {
        "edits": [(PANEL_SCROLL, ".m-panel { min-height: 0; padding: 1px;"),
                  (MAIN_ROWS, "grid-template-rows: auto; overflow-y: auto; scrollbar-width: none;")],
        "kind": "render stays",
        "also": set(),
    },
    "no_refit": {
        "edits": [(RESIZE_OBSERVER, ""), (RESIZE_LISTENER, "")],
        "kind": "render on screen",
        "scope": "resize",
        "also": set(),
    },
    "columns_do_not_fill": {
        "edits": [(PANEL_COLUMN, "var(--m-panel-min)")],
        "kind": "width fill",
        "also": set(),
    },
}


def apply_edits(source: str, edits: list[tuple[str, str]]) -> str:
    """Apply exact one-match edits; a miss raises instead of leaving a clean copy."""
    for old, new in edits:
        count = source.count(old)
        if count != 1:
            raise AssertionError(f"edit target matched {count} times, not once: {old!r}")
        source = source.replace(old, new)
    return source


def run_check(page: pathlib.Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHECK), str(page)], capture_output=True, text=True,
                          timeout=170, env=env)


def parsed(out: str) -> list[dict]:
    return [m.groupdict() for m in map(LINE.match, out.splitlines()) if m]


class TemporaryPages(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="mock-layout-test-")
        self.addCleanup(self.dir.cleanup)
        self.template = TEMPLATE.read_text(encoding="utf-8")

    def page(self, edits: list[tuple[str, str]] = ()) -> pathlib.Path:
        path = pathlib.Path(self.dir.name, "page.html")
        path.write_text(apply_edits(self.template, list(edits)), encoding="utf-8")
        return path


class StaticFiles(TemporaryPages):
    def test_every_mutation_string_matches_the_template_once(self):
        for name, mutant in MUTANTS.items():
            with self.subTest(name):
                apply_edits(self.template, mutant["edits"])
        apply_edits(self.template, [(FRAMES_BLOCK, ""), (FRAME_HOOK, 'id="x"'),
                                    (QUESTIONS_OPEN, ""), (QUESTIONS_CLOSE, "")])

    def test_no_em_dash_in_shipped_files(self):
        for path in (TEMPLATE, CHECK, pathlib.Path(__file__)):
            self.assertNotIn(chr(0x2014), path.read_text(encoding="utf-8"), path.name)

    def test_template_page_contract(self):
        for needle in ('<!doctype html>', '<meta charset="utf-8">',
                       'content="width=device-width, initial-scale=1, viewport-fit=cover"',
                       '<meta name="claude:viewport-fit-sides" content="cover">',
                       '--m-panel-min: 340px', '--m-gap: 12px',
                       'padding-left: max(16px, env(safe-area-inset-left, 0px))',
                       'padding-right: max(16px, env(safe-area-inset-right, 0px))',
                       'top: env(safe-area-inset-top, 0px)',
                       ':root:not([data-theme="light"])', ':root[data-theme="dark"]'):
            self.assertIn(needle, self.template)
        self.assertNotIn("352", self.template)


class MissingInputs(TemporaryPages):
    def test_bad_mock_chrome_exits_2_with_a_hint(self):
        env = {**os.environ, "MOCK_CHROME": str(pathlib.Path(self.dir.name, "no-such-browser"))}
        result = run_check(self.page(), env)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("MOCK_CHROME", result.stderr)
        self.assertIn("npx", result.stderr)

    def test_missing_page_exits_2(self):
        result = run_check(pathlib.Path(self.dir.name, "absent.html"))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("absent.html", result.stderr)


@unittest.skipUnless(BROWSER, SKIP_REASON or "browser found")
class CleanPages(TemporaryPages):
    def test_template_passes_and_the_scroll_assertion_is_real(self):
        result = run_check(self.page())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "LAYOUT_OK")
        lines = parsed(result.stdout)
        self.assertEqual([l for l in lines if l["result"] == "FAIL"], [])
        scrolled = [l for l in lines if l["kind"] == "questions scroll" and l["got"].startswith("scrolled ")]
        small = {l["scope"].split()[1] for l in scrolled}
        self.assertLessEqual({"1280x680", "1101x700"}, small, "the template's questions must overflow here")

    def test_every_wide_assertion_runs_for_every_frame(self):
        lines = parsed(run_check(self.page()).stdout)
        for size in ("1905x960", "1440x800", "1280x680", "1101x700"):
            for frame in ("Laptop", "iPad", "Phone"):
                kinds = {l["kind"] for l in lines if l["scope"] == f"wide {size} {frame}"}
                self.assertEqual(kinds, {"width fill", "render on screen", "no page scroll", "top row",
                                         "questions scroll", "render stays"}, f"{size} {frame}")

    def test_one_custom_frame_passes(self):
        kiosk = 'const FRAMES = [\n  { label: "Kiosk", width: 1080, height: 1920 },\n];\n'
        result = run_check(self.page([(FRAMES_BLOCK, kiosk)]))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        scopes = {l["scope"] for l in parsed(result.stdout)}
        self.assertIn("wide 1440x800 Kiosk", scopes)
        self.assertFalse([s for s in scopes if "Laptop" in s])

    def test_page_missing_frame_exits_2_and_names_it(self):
        result = run_check(self.page([(FRAME_HOOK, 'id="not-frame"')]))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("#frame", result.stderr)


@unittest.skipUnless(BROWSER, SKIP_REASON or "browser found")
class Mutants(TemporaryPages):
    def assert_mutant_fails(self, name: str):
        mutant = MUTANTS[name]
        result = run_check(self.page(mutant["edits"]))
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, out)
        failed = [l for l in parsed(result.stdout) if l["result"] == "FAIL"]
        scope = mutant.get("scope", "")
        self.assertTrue([l for l in failed if l["kind"] == mutant["kind"] and l["scope"].startswith(scope)],
                        f"{mutant['kind']!r} did not fail:\n{out}")
        self.assertLessEqual({l["kind"] for l in failed}, {mutant["kind"]} | mutant["also"], out)
        self.assertRegex(result.stdout.splitlines()[-1], r"^\d+ of \d+ assertions FAILED$")

    def test_page_scrolls(self):
        self.assert_mutant_fails("page_scrolls")

    def test_render_off_screen(self):
        self.assert_mutant_fails("render_off_screen")

    def test_too_many_controls(self):
        self.assert_mutant_fails("too_many_controls")

    def test_panel_does_not_scroll(self):
        self.assert_mutant_fails("panel_does_not_scroll")

    def test_render_moves_with_questions(self):
        self.assert_mutant_fails("render_moves_with_questions")

    def test_no_refit(self):
        self.assert_mutant_fails("no_refit")

    def test_columns_do_not_fill(self):
        self.assert_mutant_fails("columns_do_not_fill")


@unittest.skipUnless(BROWSER, SKIP_REASON or "browser found")
class LivePage(TemporaryPages):
    def open(self, page: pathlib.Path, width: int, height: int):
        browser = layout_check.Browser(BROWSER)
        self.addCleanup(browser.close)
        tab = layout_check.Page(browser)
        tab.open(page.as_uri(), width, height)
        return tab

    def test_fit_top_steps_fire_in_order_and_only_when_needed(self):
        steps = ["m-fit-1", "m-fit-2", "m-fit-3"]
        page = self.page([(CONTROLS_OPEN, CONTROLS_OPEN + extra_groups(3))])
        tab = self.open(page, 1905, 800)
        state = """(() => {
          const top = document.querySelector(".m-top");
          const on = [...top.classList].filter((c) => c.startsWith("m-fit-")).sort();
          const fits = rowFits();
          let neededLast = true;
          if (on.length) {
            const last = on[on.length - 1];
            top.classList.remove(last); neededLast = !rowFits(); top.classList.add(last);
          }
          return { on, fits, neededLast };
        })()"""
        seen = []
        for width in range(1905, 1100, -16):
            self.assertTrue(tab.resize(width, 800), f"page never settled at {width}")
            now = tab.evaluate(state)
            self.assertEqual(now["on"], steps[:len(now["on"])], f"steps out of order at {width}")
            self.assertTrue(now["neededLast"], f"{now['on'][-1:]} was not needed at {width}")
            if len(now["on"]) < 3:
                self.assertTrue(now["fits"], f"row does not fit at {width} with {now['on']}")
            if not seen or seen[-1] != now["on"]:
                seen.append(now["on"])
        self.assertEqual(seen, [steps[:n] for n in range(4)], "every step must fire, in order")
        self.assertTrue(tab.resize(1905, 800))
        self.assertEqual(tab.evaluate(state)["on"], [], "a wide window clears the steps again")

    def test_stacked_page_has_no_scrollbar_feedback_loop(self):
        """A short panel puts the page height where a scrollbar's width changes the
        scale enough to remove the scrollbar again, the worst case for that loop."""
        short = apply_edits(self.template, [])
        start = short.index(QUESTIONS_OPEN) + len(QUESTIONS_OPEN)
        short = short[:start] + short[short.index(QUESTIONS_CLOSE):]
        page = pathlib.Path(self.dir.name, "short.html")
        page.write_text(short, encoding="utf-8")
        tab = self.open(page, 1024, 3000)
        tall = tab.evaluate("document.documentElement.scrollHeight")
        watch = """new Promise((done) => {
          let changes = 0;
          const seen = new MutationObserver(() => { changes += 1; });
          seen.observe(document.getElementById("frame"), { attributes: true, attributeFilter: ["style"] });
          setTimeout(() => { seen.disconnect(); done(changes); }, 400);
        })"""
        for height in range(tall - 12, tall + 1, 2):
            tab.set_viewport(1024, height)
            self.assertLessEqual(tab.evaluate(watch), 2, f"frame kept resizing at 1024x{height}")


if __name__ == "__main__":
    unittest.main()
