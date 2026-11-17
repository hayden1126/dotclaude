"""The journeys the harness tests run. FIXTURE_CONFIG (JSON) picks the settings for one test."""
import json
import os
import pathlib
import shutil
import sys
import time

CONFIG = json.loads(os.environ["FIXTURE_CONFIG"])
STATE = pathlib.Path(os.environ["FIXTURE_DIR"])

APP = {
    "cmd": [sys.executable, CONFIG["app_path"]],
    "port": CONFIG["port"],
    "ready_timeout": CONFIG.get("ready_timeout", 3),
    "stop_timeout": 1,
    "evidence_dir": "evidence",
    "browser": CONFIG.get("browser", False),
}
APP.update(CONFIG.get("app", {}))
DOCTOR = [tuple(row) for row in CONFIG.get("doctor", [["/", 200, "fixture home"], ["/health", 200, "ok"]])]
FORBIDDEN_REQUESTS = [("POST", "/paid")]


def preflight(root):
    if CONFIG.get("preflight") == "raise":
        raise OSError("preflight blew up")
    if CONFIG.get("preflight") == "wait":
        wait_here(None)
    return CONFIG.get("preflight")


def wait_here(ctx):
    (STATE / "started").write_text("yes", encoding="utf-8")
    time.sleep(40)


def home(ctx):
    reply = ctx.get("/health")
    ctx.check(reply.status == 200, f"/health answered {reply.status}")
    ctx.check("ok" in reply.text, "/health says ok")
    ctx.fact("health", reply.text)


def echo_env(ctx):
    """What the app's environment held, by the fixture's /env route, and what the harness's own held."""
    text = ctx.get("/env").text
    ctx.check(text == CONFIG["expect"], f"/env said {text!r}")
    ctx.check(os.environ.get("FIXTURE_ECHO") == CONFIG["journey_echo"], "APP env reached the harness itself")


def wrong_expectation(ctx):
    ctx.check(ctx.get("/health").text == "not what it says", "/health text is wrong on purpose")


def no_checks(ctx):
    ctx.get("/health")


def raises(ctx):
    raise ValueError("a bug in the journey")


def crash_app(ctx):
    ctx.get("/crash")
    ctx.check(True, "unreachable: the app is gone")


def click_and_download(ctx):
    page = ctx.page
    page.goto("/")
    page.click("#go")
    text = page.wait_for("document.getElementById('result').textContent === 'clicked' && 'clicked'",
                         what="the click to land")
    ctx.check(text == "clicked", "the click changed the page")
    page.screenshot("clicked")
    page.click("#save")
    saved = page.download()
    ctx.check(saved.read_bytes() == b"exported bytes", "the download holds the export")
    page.goto("/file.bin")
    ctx.check(page.download().read_bytes() == b"file bytes", "a link straight to a file downloads it")
    ctx.fact("download", saved.name)


def click_by_text(ctx):
    ctx.page.goto("/")
    ctx.page.click_text("Export", timeout=5)
    result = ctx.page.wait_for("document.getElementById('result').textContent !== 'idle' &&"
                               " document.getElementById('result').textContent", what="the click to land")
    ctx.check(result == "by text", f"the trimmed exact match was clicked, not {result!r}")
    ctx.fact("result", result)


def click_stacked(ctx):
    """Two block children render as two lines: the rendered text is "Big Small text", while the
    raw textContent runs the two together as "BigSmall" and keeps the source's line break."""
    ctx.page.goto("/")
    ctx.page.click_text("Big Small text", timeout=5)
    result = ctx.page.wait_for("document.getElementById('result').textContent !== 'idle' &&"
                               " document.getElementById('result').textContent", what="the click to land")
    ctx.check(result == "stacked", f"the stacked button was clicked, not {result!r}")


def wait_node(ctx):
    ctx.page.goto("/")
    ctx.page.wait_for("document.body", what="the body")
    ctx.check(True, "unreachable: a DOM node can't come back by value")


def evaluate_window(ctx):
    ctx.page.goto("/")
    ctx.page.evaluate("window")
    ctx.check(True, "unreachable: the window can't come back by value")


def smooth_click(ctx):
    ctx.page.goto("/smooth")
    ctx.page.click("#far", timeout=5)
    result = ctx.page.wait_for("document.getElementById('result').textContent !== 'idle' &&"
                               " document.getElementById('result').textContent", 3, "the click to land")
    ctx.check(result == "far", f"the click hit #far, not {result!r}")


def smooth_click_text(ctx):
    ctx.page.goto("/smooth")
    ctx.page.click_text("Far text", timeout=5)
    result = ctx.page.wait_for("document.getElementById('result').textContent !== 'idle' &&"
                               " document.getElementById('result').textContent", 3, "the click to land")
    ctx.check(result == "far text", f"the click hit the text, not {result!r}")


def click_target(ctx):
    """One row of the click_text target table: CONFIG names the page, the text and what it sets."""
    ctx.page.goto(CONFIG["path"])
    ctx.page.click_text(CONFIG["text"], timeout=CONFIG["timeout"])
    result = ctx.page.wait_for("document.getElementById('result').textContent !== 'idle' &&"
                               " document.getElementById('result').textContent", 3, "the click to land")
    ctx.check(result == CONFIG["expect"], f"the click set {result!r}")


def evaluate_nested(ctx):
    ctx.page.goto("/")
    ctx.page.evaluate("[document.body]")
    ctx.check(True, "unreachable: a DOM node inside an array can't come back by value")


def wipe_evidence(ctx):
    """What a test runner a journey starts may do to the folder it writes into."""
    shutil.rmtree(ctx.evidence)
    ctx.check(not ctx.evidence.exists(), "the run's folder is gone")


def wipe_evidence_in_browser(ctx):
    ctx.page.goto("/")
    shutil.rmtree(ctx.evidence)
    ctx.page.goto("/file.bin")
    saved = ctx.page.download()
    ctx.check(saved.read_bytes() == b"file bytes", "the download after the wipe was saved")
    shot = ctx.page.screenshot("after-wipe")
    ctx.check(shot.stat().st_size > 0, "the screenshot after the wipe was saved")


def wipe_evidence_with_a_browser_open(ctx):
    """No screenshot or download after the wipe: only the manifest's save makes the folder again."""
    ctx.page.goto("/")
    shutil.rmtree(ctx.evidence)
    ctx.check(not ctx.evidence.exists(), "the run's folder is gone")


def click_text_only(ctx):
    ctx.page.goto("/")
    ctx.page.click_text(CONFIG["text"], timeout=0.5)
    ctx.check(True, "unreachable unless exactly one control matched")


def hits_forbidden(ctx):
    page = ctx.page
    page.goto("/")
    page.click("#pay")
    page.wait_for("document.getElementById('paid').textContent === 'paid'", what="the payment")
    ctx.check(True, "the page says paid")


def page_stuck(ctx):
    ctx.page.goto("/")
    ctx.page.wait_for("false", timeout=0.3, what="something that never comes")


def kill_browser(ctx):
    page = ctx.page
    page.goto("/")
    os.kill(page.browser.proc.pid, 9)
    page.evaluate("1")
    ctx.check(True, "unreachable: the browser is dead")


def kill_browser_quietly(ctx):
    page = ctx.page
    page.goto("/")
    os.kill(page.browser.proc.pid, 9)
    ctx.check(True, "the journey never notices")


def wait_in_browser(ctx):
    ctx.page.goto("/")
    (STATE / "browser.pid").write_text(str(ctx.page.browser.proc.pid), encoding="utf-8")
    (STATE / "browser.profile").write_text(ctx.page.browser.profile, encoding="utf-8")
    wait_here(ctx)


JOURNEYS = {name: globals()[name] for name in CONFIG.get("journeys", ["home"])}
JOURNEYS.update({key: globals()[name] for key, name in CONFIG.get("named", {}).items()})
