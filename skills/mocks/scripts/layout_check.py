#!/usr/bin/python3 -I
"""Prove a mock page holds the one-screen layout, in a real headless browser.

Usage: layout_check.py <page.html>

Prints one line per assertion, `ok` or `FAIL` with the measured numbers. Exits 0
with a last line of LAYOUT_OK, 1 on any FAIL or a page that stops responding, 2
when there is no browser or the page lacks a required hook. Fit is judged at the page's default Zoom. Python
standard library only.
"""
import argparse
import fcntl
import glob
import itertools
import json
import os
import pathlib
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time

WIDE = ((1905, 960), (1440, 800), (1280, 680), (1101, 700))
STACKED = ((1100, 800), (900, 800), (1024, 768), (390, 844))
RESIZE_FROM, RESIZE_TO = (1905, 960), (1280, 680)
CONTROLS_SIZE = (1440, 800)
EDGE, GAP, TOLERANCE, FIT_TOLERANCE, TOP_ROW_MAX = 16, 12, 1, 2, 56
WHEEL_DELTA = 100000

CACHE_GLOBS = (
    "~/.cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-*/chrome-headless-shell",
    "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
)
INSTALL_HINT = ("Install one with: npx @puppeteer/browsers install chrome-headless-shell@stable "
                "--path ~/.cache/puppeteer, or set MOCK_CHROME to its path.")
HOOKS = ("header.m-top", "header.m-top h1", ".m-bar", ".m-ctl", ".m-seg", ".m-main", ".m-stage",
         "#frame.m-frame", "#scaler.m-scaler", "iframe#app", "aside.m-panel", "#caption.m-caption",
         "#c-frame button")

# Runs in every frame before the page's own script, so a throw in render(), in a
# click handler or inside the render reaches the top window's list.
ERRORS_JS = """(() => {
  let sink;
  try { sink = window.top.__mockErrors ||= []; } catch { sink = window.__mockErrors ||= []; }
  // Chrome's ResizeObserver notice arrives as an error event but is no script failure.
  addEventListener("error", (e) => { if (!e.message.startsWith("ResizeObserver loop")) sink.push(e.message); });
  addEventListener("unhandledrejection", (e) => sink.push(String(e.reason)));
})()"""

READ_ERRORS_JS = "window.__mockErrors || []"

LOADED_JS = "location.protocol !== 'about:' && document.readyState === 'complete'"

# Resolves true once the viewport has taken the size, fonts are in, the render has
# loaded and the frame has a size that holds for several painted frames.
SETTLE_JS = """(async (width, height) => {
  await document.fonts.ready;
  const started = performance.now();
  let last = "", same = 0;
  return new Promise((done) => {
    (function tick() {
      const frame = document.getElementById("frame").getBoundingClientRect();
      const doc = document.getElementById("app").contentDocument;
      const ready = innerWidth === width && innerHeight === height && frame.width > 0 && frame.height > 0
        && (!doc || doc.readyState === "complete");
      const now = [frame.left, frame.top, frame.width, frame.height].join();
      same = ready && now === last ? same + 1 : 0;
      last = now;
      if (same >= 3) return done(true);
      if (performance.now() - started > 2000) return done(false);
      requestAnimationFrame(tick);
    })();
  });
})"""

# Resolves once the panel and the frame have held still for several painted frames.
SCROLL_SETTLED_JS = """new Promise((done) => {
  const panel = document.querySelector(".m-panel"), frame = document.getElementById("frame");
  const started = performance.now();
  let last = "", same = 0;
  (function tick() {
    const now = [panel.scrollTop, frame.getBoundingClientRect().top].join();
    same = now === last ? same + 1 : 0;
    last = now;
    if (same >= 6 || performance.now() - started > 2000) return done(true);
    requestAnimationFrame(tick);
  })();
})"""

MEASURE_JS = """(() => {
  const box = (selector) => {
    const r = document.querySelector(selector).getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, height: r.height };
  };
  const root = document.documentElement, frame = document.getElementById("frame");
  const panel = document.querySelector(".m-panel"), top = document.querySelector(".m-top");
  const main = document.querySelector(".m-main"), app = document.getElementById("app");
  const css = getComputedStyle(root);
  return {
    frame: box("#frame"), render: box("#app"), panel: box(".m-panel"), top: box(".m-top"),
    windowWidth: innerWidth, windowHeight: innerHeight,
    pageHeight: root.scrollHeight, pageWidth: root.scrollWidth, clientWidth: root.clientWidth,
    frameScrollX: frame.scrollWidth - frame.clientWidth, frameScrollY: frame.scrollHeight - frame.clientHeight,
    panelOverflow: panel.scrollHeight - panel.clientHeight, panelScrollTop: panel.scrollTop,
    topOverflow: top.scrollWidth - top.clientWidth,
    columns: getComputedStyle(main).gridTemplateColumns.split(" ").length,
    renderWidth: Number(app.width), renderHeight: Number(app.height),
    mainWidth: main.clientWidth, mainHeight: main.clientHeight, stageWidth: frame.parentElement.clientWidth,
    panelMin: parseFloat(css.getPropertyValue("--m-panel-min")), gap: parseFloat(css.getPropertyValue("--m-gap")),
  };
})()"""

SCROLL_RESET_JS = """(() => {
  for (let e = document.querySelector(".m-panel"); e; e = e.parentElement) e.scrollTop = 0;
})()"""

# A click that changes the render waits for its load: the next srcdoc change would
# cancel a pending one, and any script inside that render with it.
CLICK_ALL_JS = """(async () => {
  const app = document.getElementById("app");
  for (const button of document.querySelectorAll(".m-seg button")) {
    const before = app.srcdoc;
    const loaded = new Promise((done) => { app.addEventListener("load", done, { once: true }); setTimeout(done, 1000); });
    button.click();
    await (app.srcdoc === before ? new Promise(requestAnimationFrame) : loaded);
  }
  return document.querySelectorAll(".m-seg button").length;
})()"""


class BrowserError(Exception):
    """The browser could not start, or stopped answering."""


class NoBrowser(BrowserError):
    """No usable browser binary."""


def find_browser() -> str:
    """Path of a chrome-headless-shell. Full Chrome aborts in the Claude Code
    sandbox, so it is never a fallback; MOCK_CHROME can still name one."""
    configured = os.environ.get("MOCK_CHROME")
    if configured:
        if os.access(configured, os.X_OK) and os.path.isfile(configured):
            return configured
        raise NoBrowser(f"MOCK_CHROME={configured} is not an executable file. {INSTALL_HINT}")

    def version(path: str) -> tuple[int, ...]:
        return tuple(int(n) for n in re.findall(r"\d+", pathlib.Path(path).parents[1].name))

    for pattern in CACHE_GLOBS:
        builds = sorted(glob.glob(os.path.expanduser(pattern)), key=version, reverse=True)
        if builds:
            return builds[0]
    on_path = shutil.which("chrome-headless-shell")
    if on_path:
        return on_path
    raise NoBrowser(f"no chrome-headless-shell found. {INSTALL_HINT}")


class Browser:
    """One headless browser over --remote-debugging-pipe: fd 3 takes commands,
    fd 4 returns responses and events, each a JSON message ending in NUL."""

    def __init__(self, binary: str):
        self.profile = tempfile.mkdtemp(prefix="mock-layout-")
        self._log = open(os.path.join(self.profile, "stderr.log"), "wb")
        cmd_r, self._cmd_w = os.pipe()
        self._out_r, out_w = os.pipe()

        def wire():
            # Lift both ends above 3/4 first, so placing one cannot clobber the
            # other, then dup2 onto the numbers Chrome reads. pass_fds must name
            # 3 and 4 themselves: naming the original numbers lets the child
            # close 3 and 4 before exec, and the session hangs.
            a = fcntl.fcntl(cmd_r, fcntl.F_DUPFD, 10)
            b = fcntl.fcntl(out_w, fcntl.F_DUPFD, 10)
            os.dup2(a, 3)
            os.dup2(b, 4)

        # No --hide-scrollbars: a scrollbar's width is part of the layout under test.
        args = [binary, "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                "--no-first-run", "--no-default-browser-check",
                f"--user-data-dir={self.profile}", "--remote-debugging-pipe"]
        if "headless-shell" not in pathlib.Path(binary).name:
            args.insert(1, "--headless=new")
        try:
            self.proc = subprocess.Popen(args, preexec_fn=wire, pass_fds=(3, 4),
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=self._log)
        except OSError as exc:
            self._close_fds(cmd_r, out_w, self._cmd_w, self._out_r)
            self._remove_profile()
            raise BrowserError(f"cannot start {binary}: {exc}") from None
        self._close_fds(cmd_r, out_w)   # the child's ends; ours stay open
        self._buf = b""
        self._ids = itertools.count(1)

    @staticmethod
    def _close_fds(*fds):
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass

    def _remove_profile(self):
        self._log.close()
        shutil.rmtree(self.profile, ignore_errors=True)

    def _died(self, what: str) -> BrowserError:
        self._log.flush()
        text = pathlib.Path(self.profile, "stderr.log").read_text(errors="replace")
        tail = "\n".join(text.strip().splitlines()[-5:])
        return BrowserError(what + (f":\n{tail}" if tail else ""))

    def _message(self, deadline: float) -> dict:
        while b"\0" not in self._buf:
            left = deadline - time.monotonic()
            if left <= 0:
                raise self._died("the browser stopped answering")
            ready, _, _ = select.select([self._out_r], [], [], left)
            if not ready:
                continue
            chunk = os.read(self._out_r, 1 << 20)
            if not chunk:
                raise self._died("the browser exited")
            self._buf += chunk
        raw, self._buf = self._buf.split(b"\0", 1)
        return json.loads(raw)

    def call(self,
        method: str,
        params: dict | None = None,
        session: str | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """Send one command and wait for its reply, dropping events."""
        mid = next(self._ids)
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        data = json.dumps(msg).encode() + b"\0"
        try:
            while data:
                data = data[os.write(self._cmd_w, data):]
        except BrokenPipeError:
            raise self._died("the browser exited") from None
        deadline = time.monotonic() + timeout
        while True:
            reply = self._message(deadline)
            if reply.get("id") != mid:
                continue                 # an event, or a reply nobody waits for
            if "error" in reply:
                raise BrowserError(f"{method}: {reply['error'].get('message', reply['error'])}")
            return reply.get("result", {})

    def close(self):
        try:
            self.call("Browser.close", timeout=5)
        except BrowserError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Only the process this run started, by its own handle. Other
            # sessions on the machine run Chrome too.
            self.proc.kill()
            self.proc.wait()
        self._close_fds(self._cmd_w, self._out_r)
        self._remove_profile()


class Page:
    """A tab attached in flat mode; page commands carry its sessionId."""

    def __init__(self, browser: Browser):
        self.browser = browser
        self.target = browser.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = browser.call("Target.attachToTarget",
                                    {"targetId": self.target, "flatten": True})["sessionId"]
        self.call("Page.enable")
        self.call("Page.addScriptToEvaluateOnNewDocument", {"source": ERRORS_JS})

    def call(self, method: str, params: dict | None = None) -> dict:
        return self.browser.call(method, params, self.session)

    def evaluate(self, expression: str):
        result = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                                "returnByValue": True})
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            raise BrowserError(details.get("exception", {}).get("description") or details.get("text"))
        return result["result"].get("value")

    def set_viewport(self, width: int, height: int):
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})

    def load(self, url: str, width: int, height: int):
        """Navigate at this viewport and wait for the load event's state."""
        self.set_viewport(width, height)
        self.call("Page.navigate", {"url": url})
        deadline = time.monotonic() + 15
        while not self.evaluate(LOADED_JS):
            if time.monotonic() > deadline:
                raise BrowserError(f"{url} did not finish loading")
            time.sleep(0.01)

    def settle(self, width: int, height: int) -> bool:
        return self.evaluate(f"{SETTLE_JS}({width}, {height})")

    def open(self, url: str, width: int, height: int) -> bool:
        self.load(url, width, height)
        return self.settle(width, height)

    def resize(self, width: int, height: int) -> bool:
        self.set_viewport(width, height)
        return self.settle(width, height)

    def wheel(self, x: float, y: float):
        """A real wheel gesture: it scrolls whatever a user's wheel would, so a
        scroller that isn't the panel can't hide from the check."""
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        self.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y,
                                               "deltaX": 0, "deltaY": WHEEL_DELTA})
        self.evaluate(SCROLL_SETTLED_JS)

    def close(self):
        self.browser.call("Target.closeTarget", {"targetId": self.target})


class Report:
    """Prints each assertion as it runs and keeps the tally."""

    def __init__(self):
        self.total = self.failed = 0

    def check(self, scope: str, kind: str, passed: bool, got: str):
        self.total += 1
        self.failed += not passed
        print(f"{'ok  ' if passed else 'FAIL'} {scope}: {kind}: {got}", flush=True)


def near(value: float, target: float) -> bool:
    return abs(value - target) <= TOLERANCE


def check_width_fill(report: Report, scope: str, m: dict):
    frame, panel = m["frame"], m["panel"]
    gap = panel["left"] - frame["right"]
    right_edge = m["windowWidth"] - panel["right"]
    report.check(scope, "width fill",
                 near(frame["left"], EDGE) and near(right_edge, EDGE) and near(gap, GAP),
                 f"left {frame['left']:.1f}, gap {gap:.1f}, right {right_edge:.1f}")


def check_render_on_screen(report: Report, scope: str, m: dict):
    render = m["render"]
    on_screen = (render["left"] >= 0 and render["top"] >= 0 and render["right"] <= m["windowWidth"]
                 and render["bottom"] <= m["windowHeight"])
    scrolls = m["frameScrollX"] > TOLERANCE or m["frameScrollY"] > TOLERANCE
    report.check(scope, "render on screen", on_screen and not scrolls,
                 f"right {render['right']:.1f} of {m['windowWidth']}, "
                 f"bottom {render['bottom']:.1f} of {m['windowHeight']}, "
                 f"frame overflow {m['frameScrollX']} x {m['frameScrollY']}")


def check_fit(report: Report, scope: str, m: dict, wide: bool):
    """Worked out here from the page's room, not read from its script. The panel's
    1fr takes up any slack, so width fill alone can't see a render left too small."""
    room_width = m["mainWidth"] - m["panelMin"] - m["gap"] if wide else m["stageWidth"]
    room_height = m["mainHeight"] if wide else float("inf")
    width, height = m["renderWidth"], m["renderHeight"]
    if not width or not height:
        report.check(scope, "render fit", False, "the render has no size, so render() never finished")
        return
    want = width * min(1, room_width / width, room_height / height)
    got = m["render"]["right"] - m["render"]["left"]
    # The frame clips what it can't hold without adding any scrollable overflow.
    clipped = max(m["render"]["right"] - m["frame"]["right"], m["render"]["bottom"] - m["frame"]["bottom"])
    report.check(scope, "render fit", abs(got - want) <= FIT_TOLERANCE and clipped <= FIT_TOLERANCE,
                 f"{got:.1f} px wide, room for {want:.1f}, {max(clipped, 0):.1f} px clipped")


def check_errors(report: Report, tab: Page, scope: str):
    errors = tab.evaluate(READ_ERRORS_JS)
    report.check(scope, "no script errors", not errors, "; ".join(errors[:2]) or "none")


def check_page_scrolls(report: Report, tab: Page, scope: str, m: dict):
    """A real wheel in the side gutter, off the render and the questions."""
    if m["pageHeight"] <= m["windowHeight"]:
        report.check(scope, "page scrolls", True, "fits, nothing to scroll")
        return
    tab.wheel(EDGE / 4, m["windowHeight"] / 2)
    moved = tab.evaluate("scrollY")
    tab.evaluate(SCROLL_RESET_JS)
    report.check(scope, "page scrolls", moved > 0, f"scrolled {moved:.0f} of {m['pageHeight'] - m['windowHeight']} px")


def check_scrolling(report: Report, tab: Page, scope: str, m: dict):
    """Wheel over the questions, then compare. An overflowing panel must scroll
    and the render must hold still whatever moved."""
    panel = m["panel"]
    tab.wheel((panel["left"] + panel["right"]) / 2,
              (max(panel["top"], 0) + min(panel["bottom"], m["windowHeight"])) / 2)
    after = tab.evaluate(MEASURE_JS)
    tab.evaluate(SCROLL_RESET_JS)
    moved = after["panelScrollTop"]
    if m["panelOverflow"] > 0:
        report.check(scope, "questions scroll", moved > 0,
                     f"scrolled {moved:.0f} of {m['panelOverflow']} px overflow")
    else:
        report.check(scope, "questions scroll", True, "no overflow, nothing to scroll")
    shift = max(abs(after["render"][side] - m["render"][side]) for side in ("left", "top", "right", "bottom"))
    report.check(scope, "render stays", shift <= TOLERANCE, f"moved {shift:.1f} px")


def check_settled(report: Report, scope: str, settled: bool):
    """A frame that never holds a size is a failure of its own. The assertions
    still measure it, so the report says what the page did."""
    if not settled:
        report.check(scope, "page settles", False, "the frame never held a size within 2 s")


def check_wide(report: Report, tab: Page, scope: str):
    m = tab.evaluate(MEASURE_JS)
    check_width_fill(report, scope, m)
    check_render_on_screen(report, scope, m)
    check_fit(report, scope, m, wide=True)
    check_errors(report, tab, scope)
    report.check(scope, "no page scroll", m["pageHeight"] <= m["windowHeight"],
                 f"page {m['pageHeight']} of {m['windowHeight']}")
    report.check(scope, "top row", m["top"]["height"] <= TOP_ROW_MAX and m["topOverflow"] <= 0,
                 f"{m['top']['height']:.0f} px high, {m['topOverflow']} px over")
    check_scrolling(report, tab, scope, m)


def check_stacked(report: Report, tab: Page, scope: str):
    m = tab.evaluate(MEASURE_JS)
    report.check(scope, "one column", m["columns"] == 1, f"{m['columns']} columns")
    report.check(scope, "no sideways scroll", m["pageWidth"] <= m["clientWidth"],
                 f"page {m['pageWidth']} of {m['clientWidth']}")
    frame, render = m["frame"], m["render"]
    limit = m["clientWidth"] - EDGE + TOLERANCE
    report.check(scope, "render in width",
                 frame["left"] >= EDGE - TOLERANCE and frame["right"] <= limit and render["right"] <= limit,
                 f"{frame['left']:.1f} to {frame['right']:.1f} of {m['clientWidth']}")
    check_fit(report, scope, m, wide=False)
    check_errors(report, tab, scope)
    check_page_scrolls(report, tab, scope, m)


def for_each_frame(report: Report, browser: Browser, url: str, mode: str, size: tuple[int, int], check):
    """Open the page at one viewport and run `check` for every button in #c-frame."""
    width, height = size
    tab = Page(browser)
    tab.load(url, width, height)
    labels = tab.evaluate('[...document.querySelectorAll("#c-frame button")].map((b) => b.textContent.trim())')
    for index, label in enumerate(labels):
        tab.evaluate(f'document.querySelectorAll("#c-frame button")[{index}].click()')
        scope = f"{mode} {width}x{height} {label}"
        check_settled(report, scope, tab.settle(width, height))
        check(report, tab, scope)
    tab.close()


def check_resize(report: Report, browser: Browser, url: str):
    """Shrink, then grow back, with no reload: the render refits both ways."""
    tab = Page(browser)
    tab.open(url, *RESIZE_FROM)
    for start, end in ((RESIZE_FROM, RESIZE_TO), (RESIZE_TO, RESIZE_FROM)):
        scope = "resize {}x{} to {}x{}".format(*start, *end)
        check_settled(report, scope, tab.resize(*end))
        m = tab.evaluate(MEASURE_JS)
        check_render_on_screen(report, scope, m)
        check_width_fill(report, scope, m)
        check_fit(report, scope, m, wide=True)
    tab.close()


def check_controls(report: Report, browser: Browser, url: str):
    """Click every button once. render() runs per click, so a throw on one option
    shows only here."""
    tab = Page(browser)
    tab.open(url, *CONTROLS_SIZE)
    clicked = tab.evaluate(CLICK_ALL_JS)
    check_errors(report, tab, "controls {}x{}, {} buttons".format(*CONTROLS_SIZE, clicked))
    tab.close()


def preflight(browser: Browser, url: str) -> tuple[list[str], list[str]]:
    """The hooks the page lacks, and any script error, which is usually why."""
    tab = Page(browser)
    tab.load(url, *WIDE[0])
    missing = tab.evaluate(f"{json.dumps(HOOKS)}.filter((s) => !document.querySelector(s))")
    errors = tab.evaluate(READ_ERRORS_JS)
    tab.close()
    return missing, errors


def run(browser: Browser, url: str) -> int:
    missing, errors = preflight(browser, url)
    if missing:
        print(f"the page lacks required hooks: {', '.join(missing)}", file=sys.stderr)
        for error in errors:
            print(f"its script failed: {error}", file=sys.stderr)
        return 2
    report = Report()
    for size in WIDE:
        for_each_frame(report, browser, url, "wide", size, check_wide)
    check_resize(report, browser, url)
    check_controls(report, browser, url)
    for size in STACKED:
        for_each_frame(report, browser, url, "stacked", size, check_stacked)
    if report.failed:
        print(f"{report.failed} of {report.total} assertions FAILED")
        return 1
    print("LAYOUT_OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove a mock page holds the one-screen layout.")
    parser.add_argument("page", type=pathlib.Path)
    page = parser.parse_args().page
    if not page.is_file():
        print(f"no such page: {page}", file=sys.stderr)
        return 2
    try:
        browser = Browser(find_browser())
    except BrowserError as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        return run(browser, page.resolve().as_uri())
    except BrowserError as exc:
        # The browser started, so a hang here is the page's: a loop in render(), say.
        print(f"FAIL the page stopped responding: {str(exc).splitlines()[0]}")
        return 1
    finally:
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
