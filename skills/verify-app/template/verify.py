# MIT License
#
# Copyright (c) 2026 Chun Hei Leung
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Launch the app, check it, drive it, save evidence and clean up, all in one command. Edit
journeys.py, not this file.

    python3 -B .claude/skills/verify/verify.py [--quick] [--journey NAME]

--quick is launch and doctor with no browser. The default runs every journey.

Exit codes, closed. Every path ends in exactly one of them:

| Code | Meaning |
|---|---|
| 0 | Proved |
| 1 | The app failed: boot crash, ready timeout, doctor failure, journey failure |
| 2 | Could not judge: no browser, port held, preflight refused, bad config, the browser process itself died, or the run was interrupted. A boot crash is never exit 2 |
| 3 | Cleanup failed. Wins over 0, 1 and 2; the manifest keeps both results |
"""
import argparse
import collections
import datetime
import http.client
import importlib.util
import json
import os
import pathlib
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # <root>/.claude/skills/verify
TOKEN_VAR = "VERIFY_RUN_TOKEN"
OUTCOMES = {0: "proved", 1: "app failed", 2: "could not judge", 3: "cleanup failed"}
PORT_SCOPE = ("Seen only from this run's own network namespace: in a sandbox a free port here says "
              "nothing about a server in another namespace, and no later command can check it.")
NO_ANSWER = (OSError, http.client.HTTPException)
SIGNALS = {"armed": True, "seen": None}
Reply = collections.namedtuple("Reply", "status headers text")


class Refused(Exception):
    """A reason this run can't judge the app."""


class AppFailed(Exception):
    """The app did not come up or stay up."""


class JourneyFailed(Exception):
    """A journey's check failed."""


class Interrupted(BaseException):
    """A signal arrived. Not an Exception, so a journey's `except Exception` can't swallow it."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)


def on_signal(signum, _frame):
    """Raise once. After that, and during cleanup, a signal is only noted: cleanup must finish."""
    SIGNALS["seen"] = SIGNALS["seen"] or signal.Signals(signum).name
    if SIGNALS["armed"]:
        SIGNALS["armed"] = False
        raise Interrupted()


def say(text: str):
    try:
        print(f"verify: {text}", flush=True)
    except OSError:  # a closed pipe must not turn a run into a failure
        pass


def load(path: pathlib.Path):
    """Import a file by path, because python3 -I drops the script's folder from sys.path."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(*args: str) -> str | None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        done = subprocess.run(["git", "--no-optional-locks", *args], cwd=ROOT, env=env,
                              capture_output=True, text=True)
    except OSError:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def fetch(url: str, timeout: float) -> Reply:
    """GET with no proxy and no redirect. Any status is an answer; no answer raises."""
    try:
        with OPENER.open(url, timeout=timeout) as r:
            return Reply(r.status, dict(r.headers), r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        with e:
            return Reply(e.code, dict(e.headers), e.read().decode("utf-8", "replace"))


def port_held(port: int) -> bool:
    """Whether anything accepts a connection on loopback, over IPv4 or IPv6."""
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except socket.timeout:
            return True
        except OSError:
            pass
    return False


def carriers(token: str | None, group: int | None, root: str) -> tuple:
    """This run's live processes: (ours, outside). Ours are the app's group and token carriers in
    the repo; outside are token carriers elsewhere, which may be a shared daemon and are only ever
    named. State Z or X has exited: a dead process can stay in /proc with a readable environ."""
    needle = f"{TOKEN_VAR}={token}".encode()
    ours, outside = [], []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            name, rest = pathlib.Path(entry.path, "stat").read_text(errors="replace").split("(", 1)[1].rsplit(")", 1)
            state, _, pgrp = rest.split()[:3]
            if state in "ZX":
                continue
            in_group = int(pgrp) == group
            carrier = needle in pathlib.Path(entry.path, "environ").read_bytes().split(b"\0")
            cwd = os.readlink(f"{entry.path}/cwd")
        except OSError:  # it exited, or it is another user's
            continue
        if in_group or carrier:
            mine = in_group or cwd == root or cwd.startswith(root + os.sep)
            (ours if mine else outside).append({"pid": int(entry.name), "name": name, "cwd": cwd,
                                                "outside_repo": not mine})
    return ours, outside


def settled(scan, seconds: float) -> list:
    """Re-run scan until it comes back empty or the time is up, and return what it last saw."""
    deadline = time.monotonic() + seconds
    while (found := scan()) and time.monotonic() < deadline:
        time.sleep(0.05)
    return found


def load_spec(journey: str | None):
    """Load journeys.py and browser.py, refusing unfilled markers and any shape they don't allow."""
    markers = [m for path in (HERE / "journeys.py", HERE / "SKILL.md") if path.exists()
               for m in re.findall(r"<fill:[^>]*>", path.read_text(encoding="utf-8"))]
    if markers:
        raise Refused(f"unfilled markers: {', '.join(markers)}")
    try:
        spec, browser = load(HERE / "journeys.py"), load(HERE / "browser.py")
        app, evidence = spec.APP, pathlib.PurePath(spec.APP["evidence_dir"])
        problems = [text for ok, text in (
            (isinstance(app.get("cmd"), list) and app["cmd"] and all(isinstance(a, str) for a in app["cmd"]),
             "APP cmd must be a list of strings"),
            (isinstance(app.get("port"), int), "APP port must be an int"),
            (isinstance(app.get("ready_timeout"), (int, float)), "APP ready_timeout must be a number"),
            (not evidence.is_absolute() and ".." not in evidence.parts, "APP evidence_dir must stay in the repo"),
            (isinstance(app.get("browser"), bool), "APP browser must be True or False"),
            (spec.DOCTOR and all(len(row) == 3 and row[0].startswith("/") and isinstance(row[1], int)
                                 and isinstance(row[2], str) for row in spec.DOCTOR),
             "DOCTOR must list (path, status, text) rows, GET only"),
            (all(len(row) == 2 for row in spec.FORBIDDEN_REQUESTS), "FORBIDDEN_REQUESTS must list (method, path)"),
            (callable(spec.preflight), "preflight must be a function"),
            (spec.JOURNEYS and all(callable(f) for f in spec.JOURNEYS.values()), "JOURNEYS must name functions"),
            (journey is None or journey in spec.JOURNEYS, f"no journey named {journey}"),
        ) if not ok]
    except Exception as exc:
        raise Refused(f"journeys.py does not load: {exc!r}") from None
    if problems:
        raise Refused("; ".join(problems))
    return spec, browser


class Ctx:
    """What a journey gets. See journeys.py."""

    def __init__(self, run):
        self.run, self.url, self.evidence = run, run.base, run.dir
        self.tab, self.checks = None, 0

    @property
    def page(self):
        if self.tab is None:
            self.tab = self.run.open_page()
        return self.tab

    def get(self, path: str, timeout: float = 30.0) -> Reply:
        try:
            return fetch(self.url + path, timeout)
        except NO_ANSWER as exc:
            raise JourneyFailed(f"GET {path} got no answer: {exc}") from None

    def check(self, condition, message: str):
        self.checks += 1
        if not condition:
            raise JourneyFailed(message)

    def fact(self, key: str, value):
        self.run.manifest["facts"][key] = value


class Run:
    def __init__(self, spec, browser, args):
        self.spec, self.browser_mod, self.args = spec, browser, args
        self.tier = "quick" if args.quick else "full"
        self.port = spec.APP["port"]
        self.base = f"http://{spec.APP.get('host', '127.0.0.1')}:{self.port}"
        self.app = self.browser = None
        self.launched, self.failed, self.network = False, [], []
        self.started, self.token = time.monotonic(), secrets.token_hex(16)
        os.environ[TOKEN_VAR] = self.token  # reaches the app, the browser and anything a journey starts
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.dir = ROOT / spec.APP["evidence_dir"] / f"{stamp}-{self.tier}-{secrets.token_hex(3)}"
        self.dir.mkdir(parents=True)
        status = git("status", "--porcelain")
        self.manifest = {
            "commit": git("rev-parse", "HEAD"), "dirty": None if status is None else bool(status),
            "tier": self.tier, "command": sys.orig_argv, "journeys": [], "outcome": "running",
            "exit_code": None, "verdict": None, "failure": None, "interrupted": None,
            "duration_seconds": None, "port_scope": PORT_SCOPE, "port_held_before": None,
            "port_free_after": None, "processes_left": [], "swept": [], "sigkill_used": False,
            "cleanup_error": None, "app_pid": None, "app_exit_status": None, "ready": False,
            "ready_seconds": None, "doctor": [], "browser": None, "token": self.token, "facts": {},
        }
        self.write()

    def write(self):
        """Replace the manifest in one step, so a killed run leaves a whole file saying "running"."""
        temp = self.dir / "manifest.json.tmp"
        temp.write_text(json.dumps(self.manifest, indent=2, default=str) + "\n", encoding="utf-8")
        os.replace(temp, self.dir / "manifest.json")

    def exited(self, wait: float = 0) -> int | None:
        """The app's exit status once it has exited."""
        if self.app is None:
            return None
        try:
            return self.app.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            return None

    def open_page(self):
        if not self.spec.APP["browser"]:
            raise Refused("this journey needs a browser, and APP browser is False")
        if self.browser is None:
            self.browser = self.browser_mod.Browser(self.manifest["browser"], self.dir, ROOT)
        return self.browser_mod.Page(self.browser, self.base)

    def launch(self):
        self.launched = True
        with open(self.dir / "app.log", "wb") as log:
            try:
                self.app = subprocess.Popen(self.spec.APP["cmd"], cwd=ROOT, stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as exc:
                raise Refused(f"the app's command cannot start: {exc}") from None
        self.manifest["app_pid"] = self.app.pid
        self.write()

    def doctor(self, path: str, status: int, text: str, timeout: float) -> dict:
        try:
            reply = fetch(self.base + path, timeout)
        except NO_ANSWER:
            return {"path": path, "status": None, "ok": False}
        return {"path": path, "status": reply.status, "ok": reply.status == status and text in reply.text}

    def wait_ready(self):
        """Ready means usable: every doctor check passes. A child that exits is a crash, not a timeout."""
        limit = self.spec.APP["ready_timeout"]
        start = time.monotonic()
        while True:
            if self.exited() is not None:
                raise AppFailed("the app exited before it was ready")
            left = start + limit - time.monotonic()
            rows = [self.doctor(*row, max(0.2, min(5, left))) for row in self.spec.DOCTOR]
            self.manifest["doctor"] = rows
            if all(row["ok"] for row in rows):
                self.manifest.update(ready=True, ready_seconds=round(time.monotonic() - start, 2))
                return
            if left <= 0:
                break
            time.sleep(0.2)
        bad = [row for row in rows if not row["ok"]]
        if all(row["status"] is None for row in bad):
            raise AppFailed(f"never ready: nothing answered in {limit}s")
        raise AppFailed("doctor failed: " + ", ".join(f"{r['path']} answered {r['status']}" for r in bad))

    def forbidden(self, rows: list) -> list:
        """The requests in rows that FORBIDDEN_REQUESTS names, as text."""
        hits = []
        for row in rows:
            path = urllib.parse.urlsplit(row["url"]).path
            if any(row["method"] == method.upper() and (path == banned or path.startswith(banned.rstrip("/") + "/"))
                   for method, banned in self.spec.FORBIDDEN_REQUESTS):
                hits.append(f"{row['method']} {path}")
        return hits

    def journey(self, name: str):
        """Run one journey. Its failure is recorded; a reason to stop the whole run is raised."""
        ctx, error, start = Ctx(self), None, time.monotonic()
        row = {"name": name, "outcome": "running", "detail": None, "checks": 0, "seconds": None}
        self.manifest["journeys"].append(row)
        self.write()
        say(f"journey {name}")
        try:
            self.spec.JOURNEYS[name](ctx)
            if not ctx.checks:
                raise Refused("no check ran, and a journey that can't fail proves nothing")
        except Exception as exc:
            error = exc
        hits = []
        if ctx.tab:
            try:
                self.browser.pump(0.3)  # a click's request can still be on its way
                hits = self.forbidden(ctx.tab.network())
                if error or hits:
                    ctx.tab.screenshot(f"{name}-failure", timeout=5)
                ctx.tab.close()
            except (self.browser_mod.BrowserError, self.browser_mod.PageError) as exc:
                error = error or exc
            self.network += ctx.tab.network()
            (self.dir / "network.json").write_text(json.dumps(self.network, indent=2) + "\n", encoding="utf-8")
        if hits or isinstance(error, (JourneyFailed, self.browser_mod.PageError)):
            detail = f"forbidden request: {', '.join(hits)}" if hits else str(error)
            row.update(outcome="failed", detail=detail)
            self.failed.append(name)
        elif error:
            row.update(outcome="not judged", detail=f"{type(error).__name__}: {error}")
        else:
            row["outcome"] = "passed"
        row.update(checks=ctx.checks, seconds=round(time.monotonic() - start, 2))
        self.write()
        if self.exited(0.5 if error else 0) is not None:
            raise AppFailed("the app exited during a journey")
        if self.browser and self.browser.proc.poll() is not None:
            raise self.browser_mod.BrowserError("the browser process died during a journey")
        if row["outcome"] == "not judged":
            raise Refused(f"journey {name}: {row['detail']}")

    def drive(self):
        """Preflight, launch, ready, then the journeys."""
        reason = self.spec.preflight(ROOT)
        if reason:
            raise Refused(f"preflight refused: {reason}")
        self.manifest["port_held_before"] = port_held(self.port)
        if self.manifest["port_held_before"]:
            raise Refused(f"port {self.port} is held by something this run did not start")
        if self.tier == "full" and self.spec.APP["browser"]:
            self.manifest["browser"] = self.browser_mod.find_browser()
        self.launch()
        self.wait_ready()
        if self.tier == "full":
            for name in [self.args.journey] if self.args.journey else self.spec.JOURNEYS:
                self.journey(name)

    def judge(self, error: BaseException | None) -> tuple:
        """The run's result before cleanup: (exit code, why)."""
        status = self.exited(0.5 if error or self.failed else 0)
        self.manifest.update(app_exit_status=status, interrupted=SIGNALS["seen"])
        if SIGNALS["seen"]:
            return 2, f"interrupted by {SIGNALS['seen']}"
        if status is not None:
            return 1, f"the app exited with status {status}"
        if isinstance(error, AppFailed):
            return 1, str(error)
        if self.failed:
            return 1, f"journey failed: {', '.join(self.failed)}"
        if error is None:
            return 0, None
        if isinstance(error, (Refused, self.browser_mod.BrowserError)):
            return 2, str(error)
        return 2, "".join(traceback.format_exception(error))

    def stop(self):
        """End the app's group, then sweep for token carriers that left it (a setsid child). Each
        step re-polls, because a process signalled a moment ago can still look alive."""
        grace = self.spec.APP.get("stop_timeout", 10)
        group = self.app.pid if self.app else None
        root = str(ROOT)
        members = lambda: carriers(None, group, root)[0]
        strays = lambda: carriers(self.token, group, root)[0]
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if group and members():
                self.manifest["sigkill_used"] = sig == signal.SIGKILL
                os.killpg(group, sig)
                settled(members, grace)
        self.manifest["swept"] = strays()
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for process in strays():
                self.manifest["sigkill_used"] |= sig == signal.SIGKILL
                os.kill(process["pid"], sig)
            settled(strays, grace)
        self.exited()
        self.manifest["processes_left"] = settled(lambda: sum(carriers(self.token, group, root), []), 2)
        self.manifest["port_free_after"] = not settled(lambda: port_held(self.port), 2)

    def cleanup(self):
        """Close the browser and stop the app. Each step runs whatever the other did."""
        errors = []
        for step, needed in ((lambda: self.browser.close(), self.browser), (self.stop, self.launched)):
            try:
                if needed:
                    step()
            except Exception as exc:
                errors.append(repr(exc))
        self.manifest["cleanup_error"] = "; ".join(errors) or None

    def finish(self, code: int, why: str | None) -> int:
        m = self.manifest
        m["verdict"], m["failure"] = {"outcome": OUTCOMES[code], "exit_code": code}, why
        if m["processes_left"] or m["port_free_after"] is False or m["cleanup_error"]:
            code = 3
        m.update(outcome=OUTCOMES[code], exit_code=code, duration_seconds=round(time.monotonic() - self.started, 2))
        self.write()
        say(f"{m['outcome']} (exit {code}){': ' + why if why else ''}")
        if code == 3:
            say(f"left running: {m['processes_left']}; port free: {m['port_free_after']}; {m['cleanup_error']}")
        say(f"evidence: {self.dir}")
        return code

    def execute(self) -> int:
        error = None
        try:
            self.drive()
            SIGNALS["armed"] = False
        except BaseException as exc:
            SIGNALS["armed"] = False
            error = exc
        code, why = self.judge(error)
        self.cleanup()
        return self.finish(code, why)


def main(argv: list) -> int:
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)
    parser = argparse.ArgumentParser(add_help=False)  # --help would exit 0, which means proved
    tier = parser.add_mutually_exclusive_group()
    tier.add_argument("--quick", action="store_true")
    tier.add_argument("--journey")
    args = parser.parse_args(argv)
    try:
        spec, browser = load_spec(args.journey)
        run = Run(spec, browser, args)
    except (Refused, OSError, Interrupted) as exc:
        say(f"could not judge (exit 2): {exc}")
        return 2
    return run.execute()


if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    except SystemExit:  # argparse's usage error
        code = 2
    except BaseException:
        traceback.print_exc()
        code = 2
    try:
        sys.stdout.flush()
    except OSError:
        pass
    os._exit(code)  # a failed flush at exit would otherwise turn the code into 120
