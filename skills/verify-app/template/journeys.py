"""What verify.py needs from this app, and the only file an app edits. Replace every fill slot
below: verify.py exits 2 while any remain. Keep it plain data and small functions.

A journey is a function taking ctx. It drives the real user path, then checks the result:

  ctx.url             the app's base URL
  ctx.evidence        this run's evidence folder, a pathlib.Path
  ctx.get(path)       a GET that follows no redirect: .status, .headers, .text
  ctx.page            a browser tab, opened on first use (Page in browser.py): goto, click, click_text,
                      fill, wait_for, evaluate, screenshot, download, network
  ctx.check(ok, msg)  fails the journey with msg unless ok
  ctx.fact(key, val)  records a fact in the manifest

Selectors: an id, an ARIA label or a data attribute first. A control with none of those is clicked
by its visible text, ctx.page.click_text("Export SVG"), which fails unless exactly one visible
button, link or role=button says it. Never by position alone.
"""

APP = {
    "cmd": ["<fill: the repo's own dev command, one string per word>"],
    "port": "<fill: the port it listens on, as an int>",
    "host": "127.0.0.1",  # "[::1]" if the app binds IPv6 only
    "cwd": ".",  # where cmd runs, relative to the repo root: a package folder in a monorepo
    "ready_timeout": 300,  # seconds for every DOCTOR row to pass; lower it from a measured ready_seconds
    "stop_timeout": 10,  # seconds between SIGTERM and SIGKILL
    "evidence_dir": "<fill: a folder the repo ignores, relative to the repo root>",
    "browser": True,  # False if every journey uses ctx.get only
}

# GET only: path, expected status, text the body must contain. They double as the ready check, so
# name what proves the app is usable, not just that a process answers.
DOCTOR = [("<fill: a path>", 200, "<fill: text only a working page shows>")]

# Method, path. A run fails if the browser's network log shows one: a paid API, a send, a publish.
# This detects a hit, it can't stop it, so a journey must never click its way there.
FORBIDDEN_REQUESTS = [("POST", "<fill: a path that costs money or sends, or empty this list>")]


def preflight(root):
    """Return a reason to refuse before anything starts, or None. root is the repo, a pathlib.Path.
    Use it for what the port check can't see, such as another server's lock file."""
    return None


def main_journey(ctx):
    """<fill: what a user does and what proves it worked>"""
    ctx.page.goto("/")
    # goto waits for the load event, not for client code: on a server-rendered page a click before
    # hydration is lost without an error. Wait for a sign the client is live first, such as a
    # request only the client makes: performance.getEntriesByName(location.origin + "/api/x").length
    ctx.page.wait_for("<fill: a JS expression true once the client is live>", what="the client to start")
    ctx.page.click("<fill: a stable selector>")
    # wait_for returns something truthy or raises a timeout, so it can't be the check. Wait for the
    # result to show, then check an exact value read from the page, so a wrong one fails with msg.
    ctx.page.wait_for("<fill: a JS expression true once the result shows>", what="the result")
    value = ctx.page.evaluate("<fill: a JS expression for an exact value, such as a row count>")
    ctx.check(value == "<fill: the exact value it must equal; a number replaces the quotes too, such as 3>", f"the result reads {value!r}")
    ctx.page.screenshot("main")


JOURNEYS = {"<fill: feature name>": main_journey}
