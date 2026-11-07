"""What verify.py needs from this app, and the only file an app edits. Replace every <fill: ...>:
verify.py exits 2 while any remain. Keep it plain data and small functions.

A journey is a function taking ctx. It drives the real user path, then checks the result:

  ctx.url             the app's base URL
  ctx.evidence        this run's evidence folder, a pathlib.Path
  ctx.get(path)       a GET that follows no redirect: .status, .headers, .text
  ctx.page            a browser tab, opened on first use (Page in browser.py): goto, click, fill,
                      wait_for, evaluate, screenshot, download, network
  ctx.check(ok, msg)  fails the journey with msg unless ok
  ctx.fact(key, val)  records a fact in the manifest
"""

APP = {
    "cmd": ["<fill: the repo's own dev command, one string per word>"],
    "port": "<fill: the port it listens on, as an int>",
    "host": "127.0.0.1",  # "[::1]" if the app binds IPv6 only
    "ready_timeout": 90,  # seconds for every DOCTOR row to pass
    "stop_timeout": 10,  # seconds between SIGTERM and SIGKILL
    "evidence_dir": "<fill: a folder the repo ignores>",
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
    ctx.page.click("<fill: a stable selector>")
    ctx.check(ctx.page.wait_for("<fill: a JS expression for the result>"), "the action changed the page")
    ctx.page.screenshot("main")


JOURNEYS = {"<fill: feature name>": main_journey}
