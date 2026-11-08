"""The journeys the harness tests run. FIXTURE_CONFIG (JSON) picks the settings for one test."""
import json
import os
import pathlib
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
