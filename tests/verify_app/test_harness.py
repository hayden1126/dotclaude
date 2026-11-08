"""The verify harness against a fixture app: one planted break per promise. Each test builds a temp
git repo laid out as the generator leaves an app repo (the harness in tools/verify/, the recipe in
.claude/skills/verify/), picks a free port and runs verify.py as a subprocess. Signal
tests use Popen on the pid directly, never a shell's `&`, which makes children ignore SIGINT."""
import itertools
import importlib.util
import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE.parents[1] / "skills" / "verify-app" / "template"
EXITS = {0: "proved", 1: "app failed", 2: "could not judge", 3: "cleanup failed"}
# Every slot the generator fills, per template file. A literal marker anywhere else (a docstring
# that quotes one) would keep a fully filled file at exit 2.
SLOTS = {
    "journeys.py": (
        "<fill: the repo's own dev command, one string per word>",
        "<fill: the port it listens on, as an int>",
        "<fill: a folder the repo ignores, relative to the repo root>",
        "<fill: a path>",
        "<fill: text only a working page shows>",
        "<fill: a path that costs money or sends, or empty this list>",
        "<fill: what a user does and what proves it worked>",
        "<fill: a JS expression true once the client is live>",
        "<fill: a stable selector>",
        "<fill: a JS expression true once the result shows>",
        "<fill: a JS expression for an exact value, such as a row count>",
        "<fill: the exact value it must equal; a number replaces the quotes too, such as 3>",
        "<fill: feature name>",
    ),
    "SKILL.md": (
        "<fill: app name>",
        "<fill: surface, such as web app or API>",
        "<fill: harness folder>",
        '<fill: paths or globs, such as docs/ and *.md, or "none">',
        "<fill: feature>",
        "<fill: JOURNEYS key>",
        "<fill: route and clicks>",
        "<fill: observable end state>",
        '<fill: app-specific edges, such as a lock file left after a SIGKILL, or "none">',
    ),
}


# click_text targets on the fixture's /svg and /targets pages: (row, path, text, expected). expected
# is the #result text the one matching control sets, or (exit code, the count the error names).
# Rows marked * fail on 5eb0a9d's harness: an SVG element's innerText is undefined, so the filter
# threw on every poll, and innerText alone missed the source text under text-transform. Rows marked +
# fail on a6c5997's harness, which took either text at once, so a hidden span's words matched too.
CLICK_TARGETS = (
    ("* HTML button beside an SVG <a> and an SVG role=button", "/svg", "Plain", "plain"),
    ("* SVG role=button by its textContent", "/svg", "Svg button", "svg button"),
    ("* text-transform: uppercase button by its source text", "/targets", "Export svg", "transformed"),
    ("text-transform: uppercase button by its rendered text", "/targets", "EXPORT SVG", "transformed"),
    ("case-sensitive: neither rendered nor source text", "/targets", "export svg", (1, 0)),
    ("two block children as one line", "/targets", "A B", "stacked"),
    ("two equal matches", "/targets", "Twin", (1, 2)),
    ("zero matches", "/targets", "Nobody", (1, 0)),
    ("+ rendered text beats the source text of a button with a hidden span", "/targets", "Save draft",
     "save draft"),
    ("rendered text leaves out a hidden span", "/targets", "Save", "save"),
)
# Page.evaluate results: (row, expression, expected). expected is the value, or (JourneyError, text
# its message names). Rows marked * changed from 5eb0a9d's harness, which checked only the top level
# and trusted CDP's subtype. Deliberate gaps: NaN, Infinity, -0 and a BigInt at the top come back as
# None (CDP sends them as unserializableValue); a getter that throws is a PageError, the page's own
# error; a Proxy whose getPrototypeOf trap lies about a non-plain target is copied by its own keys; a
# page that replaced Object.keys or Object.getPrototypeOf before the call can fool the walk. Rows
# marked + fail on a6c5997's harness. Each row runs on a fresh page, so a row that replaces a builtin
# leaves the next one alone.
UNRETURNABLE = "JourneyError"
NESTED_297 = 1
for _ in range(297):
    NESTED_297 = [NESTED_297]
EVALUATE_ROWS = (
    ("boolean", "true", True),
    ("number", "3", 3),
    ("string", '"s"', "s"),
    ("null", "null", None),
    ("undefined", "undefined", None),
    ("array of primitives", '[1, "a"]', [1, "a"]),
    ("plain object", "({a: 1})", {"a": 1}),
    ("nested plain object", "({a: {b: [1, {c: null}]}})", {"a": {"b": [1, {"c": None}]}}),
    ("object with no prototype", "Object.assign(Object.create(null), {a: 1})", {"a": 1}),
    ("promise of a plain value", "new Promise(done => setTimeout(() => done({a: 1}), 10))", {"a": 1}),
    ("DOM node", "document.body", (UNRETURNABLE, "a HTMLBodyElement")),
    ("* DOM node in an array", "[document.body]", (UNRETURNABLE, "a HTMLBodyElement at [0]")),
    ("* DOM node in an object", "({el: document.body})", (UNRETURNABLE, "a HTMLBodyElement at .el")),
    ("* NodeList", 'document.querySelectorAll("p")', (UNRETURNABLE, "a NodeList")),
    ("function", "() => 1", (UNRETURNABLE, "a function")),
    ("* function in an object", "({f: () => 1})", (UNRETURNABLE, "a function at .f")),
    ("symbol", "Symbol('s')", (UNRETURNABLE, "a symbol")),
    ("Map", "new Map([[1, 2]])", (UNRETURNABLE, "a Map")),
    ("* Date in an array", "[new Date(0)]", (UNRETURNABLE, "a Date at [0]")),
    ("window", "window", (UNRETURNABLE, "a Window")),
    ("cyclic object", "(() => { const o = {a: 1}; o.self = o; return o })()", (UNRETURNABLE, "a cycle at .self")),
    ("* Proxy over a plain object", "new Proxy({a: 1}, {})", {"a": 1}),
    ("* Proxy over a plain object, nested", "({p: new Proxy({a: [1]}, {})})", {"p": {"a": [1]}}),
    ("* Proxy over an array", "new Proxy([1, 2], {})", [1, 2]),
    ("Proxy over a DOM node", "new Proxy(document.body, {})", (UNRETURNABLE, "a HTMLBodyElement")),
    ("+ 20,000 levels deep", "(() => { let o = null; for (let i = 0; i < 20000; i++) o = {n: o}; return o })()",
     (UNRETURNABLE, "a value nested more than 297 levels deep")),
    ("297 levels deep", "(() => { let o = 1; for (let i = 0; i < 297; i++) o = [o]; return o })()", NESTED_297),
    ("+ 298 levels deep", "(() => { let o = 1; for (let i = 0; i < 298; i++) o = [o]; return o })()",
     (UNRETURNABLE, "a value nested more than 297 levels deep")),
    ("+ plain object from a same-origin iframe",
     "(() => { const f = document.createElement('iframe'); document.body.append(f); "
     "return f.contentWindow.JSON.parse('{\"a\":1}') })()", {"a": 1}),
    ("+ class instance", "new (class Point { constructor(){ this.x = 1 } })()",
     (UNRETURNABLE, "a Point instance, not a plain object")),
    ("+ DOM node in an array, with Array.from and map replaced",
     "(() => { Array.from = () => [{}]; Array.prototype.map = () => []; return [document.body] })()",
     (UNRETURNABLE, "a HTMLBodyElement at [0]")),
    ("a key named __proto__", """JSON.parse('{"__proto__": 1}')""", {"__proto__": 1}),
)


def load(path: pathlib.Path):
    sys.dont_write_bytecode = True  # no __pycache__ in the template folder that gets copied
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def gone(pid: int, wait: float = 3.0) -> bool:
    """Whether pid has exited, a zombie included."""
    deadline = time.monotonic() + wait
    while True:
        try:
            state = pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            return True
        if state in "ZX":
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)


def git(repo: pathlib.Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=repo,
                          env=env, check=True, capture_output=True, text=True).stdout.strip()


class Case(unittest.TestCase):
    def setUp(self):
        self.top = pathlib.Path(tempfile.mkdtemp(prefix="verify-app-")).resolve()
        self.addCleanup(shutil.rmtree, self.top, ignore_errors=True)
        self.repo, self.state, self.outside = (self.top / n for n in ("repo", "state", "outside"))
        self.skill = self.repo / ".claude" / "skills" / "verify"
        self.state.mkdir()
        self.outside.mkdir()
        self.skill.mkdir(parents=True)
        self.place_harness(self.repo / "tools" / "verify")
        self.recipe = self.skill / "SKILL.md"
        self.recipe.write_text("# Verify the fixture\n\nA filled recipe: the harness scans it for markers.\n",
                               encoding="utf-8")
        (self.repo / ".gitignore").write_text("evidence/\n__pycache__/\n", encoding="utf-8")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "start")
        self.port = free_port()
        self.addCleanup(self.reap_child)

    def place_harness(self, folder: pathlib.Path):
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("verify.py", "browser.py"):
            shutil.copy(TEMPLATE / name, folder / name)
        shutil.copy(HERE / "fixture" / "journeys.py", folder / "journeys.py")
        self.harness = folder

    def reap_child(self):
        """End a sleeper a test left alive on purpose; its pid file is this test's own record."""
        path = self.state / "child.pid"
        if path.exists():
            try:
                os.kill(int(path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def env(self, mode: str, config: dict) -> dict:
        config = {"port": self.port, "app_path": str(HERE / "fixture" / "app.py"), **config}
        return {**os.environ, "FIXTURE_MODE": mode, "FIXTURE_PORT": str(self.port),
                "FIXTURE_DIR": str(self.state), "FIXTURE_OUTSIDE": str(self.outside),
                "FIXTURE_CONFIG": json.dumps(config)}

    def command(self, args: tuple = (), flags: tuple = ("-B",)) -> list:
        return [sys.executable, *flags, str(self.harness / "verify.py"), *args]

    def run_harness(self, mode: str = "normal",
        args: tuple = (),
        flags: tuple = ("-B",),
        env: dict | None = None,
        cwd: pathlib.Path | None = None,
        **config,
    ) -> tuple:
        """Run verify.py to its end: (exit code, manifest or None, stdout and stderr)."""
        done = subprocess.run(self.command(args, flags), cwd=cwd or self.repo,
                              env={**self.env(mode, config), **(env or {})},
                              capture_output=True, text=True, timeout=60)
        self.assertIn(done.returncode, EXITS, done.stderr)
        manifest = self.manifest(required=False)
        if manifest is not None:
            self.assertEqual(manifest["exit_code"], done.returncode, done.stdout + done.stderr)
            self.assertEqual(manifest["outcome"], EXITS[done.returncode])
        return done.returncode, manifest, done.stdout + done.stderr

    def run_dir(self) -> pathlib.Path | None:
        found = sorted((self.repo / "evidence").glob("*/manifest.json"))
        return found[-1].parent if found else None

    def manifest(self, required: bool = True) -> dict | None:
        where = self.run_dir()
        if where is None:
            self.assertFalse(required, "no manifest")
            return None
        return json.loads((where / "manifest.json").read_text(encoding="utf-8"))

    def child_pid(self) -> int:
        return int((self.state / "child.pid").read_text())

    def requests(self) -> list:
        path = self.state / "requests.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def assert_clean(self, manifest: dict):
        self.assertTrue(manifest["port_free_after"])
        self.assertEqual(manifest["processes_left"], [])

    def assert_never_launched(self, manifest: dict):
        self.assertIsNone(manifest["app_pid"])
        self.assertFalse((self.run_dir() / "app.log").exists())
        self.assertIsNone(manifest["port_free_after"])
        self.assertEqual(self.requests(), [])

    def stub_chrome(self, mode: str) -> tuple:
        """A fake browser that breaks in mode: (its path, the file it records profile and pid in)."""
        record = self.state / f"stub-{mode}"
        path = self.outside / f"stub-chrome-{mode}"
        path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "fixture" / "stub_chrome.py"}" '
                        f'"{mode}" "{record}" "$@"\n', encoding="utf-8")
        path.chmod(0o755)
        return path, record

    def assert_stub_gone(self, record: pathlib.Path):
        profile, pid = record.read_text(encoding="utf-8").split()
        self.assertTrue(gone(int(pid)), "the browser process must be ended")
        self.assertFalse(pathlib.Path(profile).exists(), "the throwaway profile must be removed")

    def start_and_wait(self, config: dict) -> subprocess.Popen:
        """Start verify.py and return once a journey has reached its wait."""
        proc = subprocess.Popen(self.command(), cwd=self.repo, env=self.env("normal", config),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(proc.wait)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.monotonic() + 30
        while not (self.state / "started").exists():
            self.assertLess(time.monotonic(), deadline, "the journey never started")
            self.assertIsNone(proc.poll())
            time.sleep(0.05)
        return proc


class Proved(Case):
    def test_happy_path_exits_0_with_a_full_manifest(self):
        code, manifest, _ = self.run_harness()
        self.assertEqual(code, 0)
        self.assertEqual(manifest["commit"], git(self.repo, "rev-parse", "HEAD"))
        self.assertIs(manifest["dirty"], False)
        self.assertEqual(manifest["tier"], "full")
        self.assertIn("verify.py", " ".join(manifest["command"]))
        self.assertEqual([(j["name"], j["outcome"]) for j in manifest["journeys"]], [("home", "passed")])
        self.assertEqual(manifest["journeys"][0]["checks"], 2)
        self.assertEqual(manifest["facts"], {"health": "ok"})
        self.assertGreater(manifest["duration_seconds"], 0)
        self.assertIn("namespace", manifest["port_scope"])
        self.assertTrue(manifest["ready"])
        self.assertEqual([row["ok"] for row in manifest["doctor"]], [True, True])
        self.assert_clean(manifest)
        self.assertIn("fixture starting", (self.run_dir() / "app.log").read_text(encoding="utf-8"))
        self.assertRegex(self.run_dir().name, r"^\d{8}T\d{6}Z-full-[0-9a-f]+$")

    def test_the_app_is_gone_after_a_passing_run(self):
        _, manifest, _ = self.run_harness()
        self.assertTrue(gone(manifest["app_pid"]))

    def test_the_dirty_flag_sees_a_changed_file(self):
        (self.repo / ".gitignore").write_text("evidence/\n__pycache__/\nmore\n", encoding="utf-8")
        _, manifest, _ = self.run_harness()
        self.assertIs(manifest["dirty"], True)

    def test_git_variables_in_the_environment_are_ignored(self):
        code, manifest, _ = self.run_harness(env={"GIT_DIR": str(self.outside), "GIT_WORK_TREE": "/"})
        self.assertEqual(code, 0)
        self.assertEqual(manifest["commit"], git(self.repo, "rev-parse", "HEAD"))

    def test_git_never_sees_the_run_token(self):
        """A daemon git starts (fsmonitor) would carry the token and be swept or reported."""
        fake = self.outside / "bin"
        fake.mkdir()
        (fake / "git").write_text(f'#!/bin/sh\nenv >> "{self.state}/git.env"\nexec "{shutil.which("git")}" "$@"\n',
                                  encoding="utf-8")
        (fake / "git").chmod(0o755)
        code, manifest, output = self.run_harness(env={"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"})
        self.assertEqual(code, 0, output)
        self.assertEqual(manifest["commit"], git(self.repo, "rev-parse", "HEAD"), "git ran through the fake")
        seen = (self.state / "git.env").read_text(encoding="utf-8").splitlines()
        self.assertTrue([line for line in seen if line.startswith("FIXTURE_DIR=")], "the fake saw git's env")
        # A short message: the dumped env holds the caller's proxy settings, never print it.
        self.assertFalse([line for line in seen if line.startswith("VERIFY_RUN_TOKEN=")], "git got the token")

    def test_python_isolated_mode_works(self):
        code, _, output = self.run_harness(flags=("-I", "-B"))
        self.assertEqual(code, 0, output)
        self.assertFalse((self.harness / "__pycache__").exists())

    def test_it_runs_from_any_directory(self):
        code, _, output = self.run_harness(cwd=self.outside)
        self.assertEqual(code, 0, output)

    def test_the_root_is_the_git_top_level_at_any_depth(self):
        self.place_harness(self.repo / "packages" / "web" / "scripts" / "verify")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "deeper")
        code, manifest, output = self.run_harness(cwd=self.outside)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.run_dir().parents[1], self.repo, "evidence_dir is relative to the top level")
        self.assertEqual((self.state / "cwd").read_text(encoding="utf-8"), str(self.repo))
        self.assertIs(manifest["dirty"], False)

    def test_app_cwd_starts_the_app_in_a_package_folder(self):
        (self.repo / "packages" / "web").mkdir(parents=True)
        code, manifest, output = self.run_harness("setsid", app={"cwd": "packages/web"})
        self.assertEqual(code, 0, output)
        self.assertEqual((self.state / "cwd").read_text(encoding="utf-8"), str(self.repo / "packages" / "web"))
        self.assertEqual(self.run_dir().parents[1], self.repo)
        self.assertEqual([p["pid"] for p in manifest["swept"]], [self.child_pid()],
                         "a carrier in the package folder is still inside the repo")
        self.assert_clean(manifest)

    def test_app_env_reaches_the_app_over_the_inherited_env_and_keeps_the_token(self):
        """APP env is merged over what the harness inherited, for the app's command only. Fails on
        db435f5, which had no env key: the app saw the caller's value."""
        code, manifest, output = self.run_harness(app={"env": {"FIXTURE_ECHO": "from APP"}}, journeys=["echo_env"],
                                                  expect="FIXTURE_ECHO=from APP; token=set",
                                                  journey_echo="from the caller",
                                                  env={"FIXTURE_ECHO": "from the caller"})
        self.assertEqual(code, 0, output)
        self.assertEqual([(j["name"], j["outcome"]) for j in manifest["journeys"]], [("echo_env", "passed")])
        self.assert_clean(manifest)

    def test_quick_is_launch_and_doctor_with_no_browser(self):
        stub = self.outside / "stub-chrome"
        stub.write_text(f"#!/bin/sh\ntouch {self.state}/browser-started\n", encoding="utf-8")
        stub.chmod(0o755)
        code, manifest, output = self.run_harness(args=("--quick",), browser=True,
                                                  journeys=["wrong_expectation"],
                                                  env={"VERIFY_CHROME": str(stub)})
        self.assertEqual(code, 0, output)
        self.assertEqual(manifest["tier"], "quick")
        self.assertEqual(manifest["journeys"], [])
        self.assertIsNone(manifest["browser"])
        self.assertFalse((self.state / "browser-started").exists())
        self.assert_clean(manifest)

    def test_journey_flag_runs_only_that_journey(self):
        code, manifest, _ = self.run_harness(args=("--journey", "home"),
                                             journeys=["home", "wrong_expectation"])
        self.assertEqual(code, 0)
        self.assertEqual([j["name"] for j in manifest["journeys"]], ["home"])

    def test_a_run_folder_deleted_mid_run_is_made_again(self):
        """A Playwright spec a journey runs empties its output folder: the verdict must still land."""
        code, manifest, output = self.run_harness(journeys=["wipe_evidence"])
        self.assertEqual(code, 0, output)
        self.assertEqual([(j["name"], j["outcome"]) for j in manifest["journeys"]], [("wipe_evidence", "passed")])
        self.assertEqual(manifest["verdict"], {"outcome": "proved", "exit_code": 0})
        self.assert_clean(manifest)

    def test_doctor_does_not_follow_a_redirect(self):
        code, manifest, _ = self.run_harness(doctor=[["/moved", 302, ""]])
        self.assertEqual(code, 0)
        self.assertEqual(manifest["doctor"][0]["status"], 302)
        self.assertNotIn("GET /elsewhere", self.requests())


class AppFailed(Case):
    def test_boot_crash_exits_1_at_once_with_its_status(self):
        started = time.monotonic()
        code, manifest, _ = self.run_harness("boot_crash", ready_timeout=30)
        self.assertEqual(code, 1)
        self.assertLess(time.monotonic() - started, 15, "a crash must not wait for the timeout")
        self.assertEqual(manifest["app_exit_status"], 3)
        self.assertFalse(manifest["ready"])
        self.assertIn("exited", manifest["failure"])
        self.assert_clean(manifest)

    def test_never_ready_exits_1_as_a_timeout(self):
        code, manifest, _ = self.run_harness("never_ready", ready_timeout=1)
        self.assertEqual(code, 1)
        self.assertFalse(manifest["ready"])
        self.assertIsNone(manifest["app_exit_status"])
        self.assertIn("never ready", manifest["failure"])
        self.assert_clean(manifest)

    def test_a_crash_mid_drive_exits_1_with_its_status(self):
        code, manifest, _ = self.run_harness(journeys=["crash_app"])
        self.assertEqual(code, 1)
        self.assertTrue(manifest["ready"])
        self.assertEqual(manifest["app_exit_status"], 7)
        self.assertIn("exited", manifest["failure"])

    def test_a_doctor_failure_exits_1_naming_the_check(self):
        code, manifest, _ = self.run_harness("bad_doctor", ready_timeout=1)
        self.assertEqual(code, 1)
        self.assertEqual((manifest["doctor"][0]["ok"], manifest["doctor"][0]["status"]), (False, 500))
        self.assertIn("doctor", manifest["failure"])
        self.assertTrue(manifest["port_free_after"])

    def test_a_failed_check_exits_1_and_keeps_the_evidence(self):
        code, manifest, _ = self.run_harness(journeys=["wrong_expectation", "home"])
        self.assertEqual(code, 1)
        self.assertEqual([j["outcome"] for j in manifest["journeys"]], ["failed", "passed"])
        self.assertIn("wrong on purpose", manifest["journeys"][0]["detail"])
        self.assertTrue((self.run_dir() / "app.log").stat().st_size)
        self.assert_clean(manifest)


class NoVerdict(Case):
    def test_a_filled_template_clears_the_marker_scan(self):
        for name, folder in (("journeys.py", self.harness), ("SKILL.md", self.skill)):
            text = (TEMPLATE / name).read_text(encoding="utf-8")
            for slot in SLOTS[name]:
                self.assertIn(slot, text, name)
                text = text.replace(slot, "filled")
            (folder / name).write_text(text, encoding="utf-8")
        code, manifest, output = self.run_harness()
        self.assertEqual(code, 2)
        self.assertNotIn("unfilled markers", output)
        self.assertIn("APP port must be an int", output, "the scan passed and the config was read")
        self.assertIsNone(manifest)

    def test_unfilled_markers_exit_2_naming_them(self):
        shutil.copy(TEMPLATE / "journeys.py", self.harness / "journeys.py")
        code, manifest, output = self.run_harness()
        self.assertEqual(code, 2)
        self.assertIn("<fill:", output)
        self.assertIsNone(manifest)

    def test_a_marker_left_in_the_recipe_exits_2(self):
        (self.skill / "SKILL.md").write_text("Skip paths: <fill: paths>\n", encoding="utf-8")
        code, _, output = self.run_harness()
        self.assertEqual(code, 2)
        self.assertIn("<fill: paths>", output)

    def test_a_missing_or_unreadable_recipe_exits_2_naming_it(self):
        """In a sandbox an unwritten .claude/skills file can show as a /dev/null mount: never scan it as clean."""
        for kind in ("missing", "empty", "blank", "dev null", "a folder"):
            with self.subTest(kind=kind):
                shutil.rmtree(self.repo / "evidence", ignore_errors=True)
                if self.recipe.is_dir() and not self.recipe.is_symlink():
                    self.recipe.rmdir()
                else:
                    self.recipe.unlink(missing_ok=True)
                if kind == "empty":
                    self.recipe.write_text("", encoding="utf-8")
                elif kind == "blank":
                    self.recipe.write_text("\n  \n", encoding="utf-8")
                elif kind == "dev null":
                    self.recipe.symlink_to(os.devnull)
                elif kind == "a folder":
                    self.recipe.mkdir()
                code, manifest, output = self.run_harness()
                self.assertEqual(code, 2, output)
                self.assertIn(str(self.recipe), output)
                self.assertIn("empty" if kind in ("empty", "blank") else "missing or not a regular file", output)
                self.assertIsNone(manifest)
                self.assertEqual(self.requests(), [])

    def test_a_harness_outside_a_git_work_tree_exits_2(self):
        if subprocess.run(["git", "-C", str(self.outside), "rev-parse"], capture_output=True).returncode == 0:
            self.skipTest("the temp folder is inside a git work tree here")
        self.place_harness(self.outside / "verify")
        code, manifest, output = self.run_harness()
        self.assertEqual(code, 2)
        self.assertIn("git work tree", output)
        self.assertIsNone(manifest)
        self.assertFalse((self.outside / "evidence").exists())
        self.assertEqual(self.requests(), [])

    def test_an_unknown_journey_exits_2(self):
        code, _, output = self.run_harness(args=("--journey", "nope"))
        self.assertEqual(code, 2)
        self.assertIn("nope", output)
        self.assertEqual(self.requests(), [])

    def test_a_bad_flag_and_a_help_request_exit_2(self):
        for flag in ("--nope", "--help"):
            with self.subTest(flag=flag):
                self.assertEqual(self.run_harness(args=(flag,))[0], 2)

    def test_quick_with_a_journey_exits_2(self):
        self.assertEqual(self.run_harness(args=("--quick", "--journey", "home"))[0], 2)

    def test_a_doctor_row_that_is_not_a_plain_get_exits_2_unsent(self):
        code, _, output = self.run_harness(doctor=[["POST", "/paid", 200, "ok"]])
        self.assertEqual(code, 2)
        self.assertIn("DOCTOR", output)
        self.assertEqual(self.requests(), [])

    def test_bad_config_exits_2(self):
        for name, config in (("cmd", {"app": {"cmd": "python3 app.py"}}),
                             ("port", {"app": {"port": "5180"}}),
                             ("evidence", {"app": {"evidence_dir": "../outside"}}),
                             ("cwd outside", {"app": {"cwd": "../outside"}}),
                             ("cwd absolute", {"app": {"cwd": "/"}}),
                             ("cwd missing", {"app": {"cwd": "nowhere"}}),
                             ("doctor", {"doctor": []}),
                             ("journeys", {"journeys": []})):
            with self.subTest(name=name):
                self.assertEqual(self.run_harness(**config)[0], 2)

    def test_a_bad_app_env_exits_2_unlaunched(self):
        """Fails on db435f5, which ignored the key and proved."""
        for value in ("FOO=1", ["FOO=1"], None, {"FOO": 1}, {"FOO": None}, {"": "x"}, {"A=B": "x"},
                      {"FOO": "a\0b"}):
            with self.subTest(value=value):
                shutil.rmtree(self.repo / "evidence", ignore_errors=True)
                code, manifest, output = self.run_harness(app={"env": value})
                self.assertEqual(code, 2, output)
                self.assertIn("APP env must", output)
                self.assertIsNone(manifest)
                self.assertEqual(self.requests(), [])

    def test_app_env_cannot_set_the_run_token(self):
        """The sweep finds the app's processes by the token, so a journey's config must not replace it.
        Fails on db435f5, which ignored the key and proved."""
        code, manifest, output = self.run_harness(app={"env": {"VERIFY_RUN_TOKEN": "mine"}})
        self.assertEqual(code, 2, output)
        self.assertIn("APP env can't set VERIFY_RUN_TOKEN", output)
        self.assertIsNone(manifest)
        self.assertEqual(self.requests(), [])

    def test_a_bad_timeout_or_port_exits_2_unlaunched(self):
        cases = [(key, value) for key in ("stop_timeout", "ready_timeout")
                 for value in ("10", 0, -1, True, None, float("nan"))]
        cases += [("port", value) for value in (True, 0, 70000)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                shutil.rmtree(self.repo / "evidence", ignore_errors=True)
                code, manifest, output = self.run_harness(app={key: value})
                self.assertEqual(code, 2, output)
                self.assertIn(key, output)
                self.assertIsNone(manifest)
                self.assertEqual(self.requests(), [])

    def test_a_browser_that_fails_setup_exits_2_and_leaves_nothing(self):
        """Before the tab is ready the app has not been judged, so no setup step's error is exit 1."""
        for method in ("Browser.setDownloadBehavior", "Target.createTarget", "Target.attachToTarget",
                       "Page.enable", "Emulation.setDeviceMetricsOverride"):
            with self.subTest(method=method):
                shutil.rmtree(self.repo / "evidence", ignore_errors=True)
                stub, record = self.stub_chrome(method)
                code, manifest, output = self.run_harness(journeys=["page_stuck"], browser=True,
                                                          env={"VERIFY_CHROME": str(stub)})
                self.assertEqual(code, 2, output)
                self.assertEqual(manifest["journeys"][0]["outcome"], "not judged")
                self.assertIn(method, manifest["failure"])
                self.assert_stub_gone(record)
                self.assert_clean(manifest)

    def test_a_missing_journeys_file_exits_2(self):
        (self.harness / "journeys.py").unlink()
        self.assertEqual(self.run_harness()[0], 2)

    def test_a_command_that_cannot_start_exits_2(self):
        code, manifest, _ = self.run_harness(app={"cmd": [str(self.outside / "missing")]})
        self.assertEqual(code, 2)
        self.assertIn("cannot start", manifest["failure"])

    def test_preflight_refusal_exits_2_before_launch(self):
        code, manifest, _ = self.run_harness(preflight="a lock is present")
        self.assertEqual(code, 2)
        self.assertIn("a lock is present", manifest["failure"])
        self.assert_never_launched(manifest)

    def test_a_preflight_exception_exits_2_before_launch(self):
        code, manifest, _ = self.run_harness(preflight="raise")
        self.assertEqual(code, 2)
        self.assertIn("preflight blew up", manifest["failure"])
        self.assert_never_launched(manifest)

    def test_a_held_port_exits_2_and_the_holder_survives(self):
        holder = subprocess.Popen([sys.executable, str(HERE / "fixture" / "app.py")],
                                  env=self.env("normal", {}), stdout=subprocess.DEVNULL)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        deadline = time.monotonic() + 10
        while True:
            with socket.socket() as s:
                if not s.connect_ex(("127.0.0.1", self.port)):
                    break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        code, manifest, _ = self.run_harness()
        self.assertEqual(code, 2)
        self.assertIs(manifest["port_held_before"], True)
        self.assertIn("held", manifest["failure"])
        self.assertIsNone(holder.poll(), "the holder must survive")
        self.assertIsNone(manifest["app_pid"])
        self.assertIsNone(manifest["port_free_after"])

    def test_a_port_held_only_on_ipv6_exits_2(self):
        holder = socket.socket(socket.AF_INET6)
        self.addCleanup(holder.close)
        try:
            holder.bind(("::1", self.port))
        except OSError:
            self.skipTest("no ::1 here")
        holder.listen()
        code, manifest, _ = self.run_harness()
        self.assertEqual(code, 2)
        self.assertIs(manifest["port_held_before"], True)

    def test_a_journey_bug_exits_2(self):
        code, manifest, _ = self.run_harness(journeys=["raises"])
        self.assertEqual(code, 2)
        self.assertEqual(manifest["journeys"][0]["outcome"], "not judged")
        self.assertIn("a bug in the journey", manifest["journeys"][0]["detail"])
        self.assert_clean(manifest)

    def test_a_journey_that_checks_nothing_exits_2(self):
        code, manifest, _ = self.run_harness(journeys=["no_checks"])
        self.assertEqual(code, 2)
        self.assertIn("no check", manifest["journeys"][0]["detail"])

    def test_a_journey_needing_a_browser_with_browser_off_exits_2(self):
        code, manifest, _ = self.run_harness(journeys=["page_stuck"], browser=False)
        self.assertEqual(code, 2)
        self.assertIn("browser", manifest["journeys"][0]["detail"])


class Cleanup(Case):
    def test_a_grandchild_in_the_group_is_ended(self):
        code, manifest, _ = self.run_harness("grandchild")
        self.assertEqual(code, 0)
        self.assertTrue(gone(self.child_pid()))
        self.assertIs(manifest["sigkill_used"], False)
        self.assertEqual(manifest["swept"], [], "the group signal must end it, not the sweep")
        self.assert_clean(manifest)

    def test_a_setsid_child_in_the_repo_is_swept(self):
        code, manifest, _ = self.run_harness("setsid")
        self.assertEqual(code, 0)
        self.assertTrue(gone(self.child_pid()))
        self.assertEqual([p["pid"] for p in manifest["swept"]], [self.child_pid()])
        self.assert_clean(manifest)

    def test_a_child_ignoring_sigterm_gets_sigkill(self):
        code, manifest, _ = self.run_harness("ignore_term")
        self.assertEqual(code, 0)
        self.assertTrue(gone(self.child_pid()))
        self.assertIs(manifest["sigkill_used"], True)
        self.assertEqual(manifest["swept"], [], "the group's SIGKILL must end it, not the sweep")
        self.assert_clean(manifest)

    def test_a_token_carrier_outside_the_repo_is_named_and_never_signalled(self):
        code, manifest, _ = self.run_harness("outside")
        self.assertEqual(code, 3)
        self.assertEqual([(p["pid"], p["outside_repo"]) for p in manifest["processes_left"]],
                         [(self.child_pid(), True)])
        self.assertFalse(gone(self.child_pid(), wait=0.3), "it must not be signalled")
        self.assertEqual(manifest["verdict"], {"outcome": "proved", "exit_code": 0})

    def test_a_port_still_answering_after_cleanup_exits_3(self):
        code, manifest, _ = self.run_harness("outside_port")
        self.assertEqual(code, 3)
        self.assertIs(manifest["port_free_after"], False)

    def test_cleanup_failure_beats_a_failed_journey_and_keeps_both(self):
        code, manifest, _ = self.run_harness("outside", journeys=["wrong_expectation"])
        self.assertEqual(code, 3)
        self.assertEqual(manifest["verdict"], {"outcome": "app failed", "exit_code": 1})

    def test_a_zombie_with_the_token_does_not_count_as_left(self):
        verify = load(TEMPLATE / "verify.py")
        env = {**os.environ, verify.TOKEN_VAR: "zombie-token"}
        sleeper = subprocess.Popen(["sleep", "30"], env=env, cwd=self.repo, start_new_session=True)
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        deadline = time.monotonic() + 3
        while not verify.carriers("zombie-token", sleeper.pid, str(self.repo))[0]:
            self.assertLess(time.monotonic(), deadline, "the scan never saw the live sleeper")
            time.sleep(0.02)
        sleeper.send_signal(signal.SIGKILL)  # not reaped: it stays in /proc as state Z, in its group
        self.assertTrue(gone(sleeper.pid))
        self.assertEqual(verify.carriers("zombie-token", sleeper.pid, str(self.repo)), ([], []))


    def test_a_group_member_with_an_unreadable_environ_is_still_ended(self):
        probe = subprocess.Popen([sys.executable, "-c", "import ctypes, time\nctypes.CDLL(None).prctl(4, 0)\n"
                                  "time.sleep(5)"], stdout=subprocess.PIPE)
        self.addCleanup(probe.wait)
        self.addCleanup(probe.kill)
        time.sleep(0.3)
        try:
            pathlib.Path(f"/proc/{probe.pid}/environ").read_bytes()
            self.skipTest("a non-dumpable process's environ is readable here (root, or CAP_SYS_PTRACE)")
        except PermissionError:
            pass
        code, manifest, output = self.run_harness("undumpable")
        self.assertTrue(gone(self.child_pid()), "stat shows it in the group, so it is ours to end")
        self.assertEqual(code, 0, output)
        self.assertIs(manifest["sigkill_used"], True)
        self.assert_clean(manifest)

    def test_a_process_gone_before_its_signal_does_not_stop_cleanup(self):
        """os.kill and os.killpg raise ProcessLookupError for a target that exited after the scan, and
        PermissionError for one another user owns (a setuid helper in the group): cleanup goes on."""
        verify = load(TEMPLATE / "verify.py")
        ghost = {"pid": 1 << 30, "name": "ghost", "cwd": str(self.repo), "outside_repo": False}
        for where, error in itertools.product(("group", "stray"), (ProcessLookupError, PermissionError)):
            with self.subTest(where=where, error=error.__name__):
                scans = []

                def scan(token, group, root):
                    scans.append(token)
                    return ([ghost], []) if len(scans) <= 2 else ([], [])

                run = object.__new__(verify.Run)
                run.spec = types.SimpleNamespace(APP={"stop_timeout": 0.2})
                run.app = types.SimpleNamespace(pid=1 << 30, wait=lambda timeout: 0) if where == "group" else None
                run.token, run.port, run.manifest = "ghost-token", self.port, {"sigkill_used": False}
                gone_error = mock.Mock(side_effect=error)
                with mock.patch.object(verify, "carriers", scan), \
                        mock.patch.object(verify.os, "kill", gone_error), \
                        mock.patch.object(verify.os, "killpg", gone_error):
                    run.stop()
                self.assertTrue(gone_error.called)
                self.assertEqual(run.manifest["processes_left"], [])
                self.assertIs(run.manifest["port_free_after"], True)


class Units(Case):
    def test_the_newest_cached_build_wins(self):
        browser = load(TEMPLATE / "browser.py")
        for kind, names, newest in (
                ("puppeteer", ("linux-131.0.6778.85", "linux-130.0.6779.0", "linux-9.0.1.1"),
                 "linux-131.0.6778.85"),
                ("playwright", ("1148", "1200", "999"), "chromium_headless_shell-1200")):
            with self.subTest(kind=kind):
                home = self.top / f"home-{kind}"
                pattern = browser.CACHE_GLOBS[0 if kind == "puppeteer" else 1].removeprefix("~/")
                for name in names:
                    path = home / pattern.replace("*", name, 1).replace("*", "linux64")
                    path.parent.mkdir(parents=True)
                    path.write_text("", encoding="utf-8")
                    path.chmod(0o755)
                with mock.patch.dict(os.environ, {"HOME": str(home)}):
                    os.environ.pop("VERIFY_CHROME", None)
                    self.assertEqual(pathlib.Path(browser.find_browser()).parts[-3], newest)

    def test_a_browser_that_never_answers_is_a_browser_error_and_leaves_nothing(self):
        browser = load(TEMPLATE / "browser.py")
        stub, record = self.stub_chrome("hang")
        out = self.top / "out"
        out.mkdir()
        started = time.monotonic()
        with self.assertRaises(browser.BrowserError):
            browser.Browser(str(stub), out, self.top, timeout=1)
        self.assertLess(time.monotonic() - started, 10)
        self.assert_stub_gone(record)


class Interrupts(Case):
    def interrupted(self, signum: int):
        proc = self.start_and_wait({"journeys": ["wait_here"]})
        pid = self.manifest()["app_pid"]
        proc.send_signal(signum)
        code = proc.wait(timeout=30)
        manifest = self.manifest()
        self.assertEqual((code, manifest["exit_code"]), (2, 2))
        self.assertEqual(manifest["outcome"], "could not judge")
        self.assertEqual(manifest["interrupted"], signal.Signals(signum).name)
        self.assertEqual(manifest["journeys"][0]["outcome"], "running")
        self.assertTrue(gone(pid))
        self.assert_clean(manifest)

    def test_sigterm_mid_drive_cleans_up_and_exits_2(self):
        self.interrupted(signal.SIGTERM)

    def test_sigint_mid_drive_cleans_up_and_exits_2(self):
        self.interrupted(signal.SIGINT)

    def test_a_killed_harness_leaves_the_manifest_running(self):
        proc = self.start_and_wait({"preflight": "wait"})
        proc.kill()
        proc.wait()
        self.assertEqual(self.manifest()["outcome"], "running")
        self.assertIsNone(self.manifest()["exit_code"])


class RealBrowser(Case):
    @classmethod
    def setUpClass(cls):
        browser = load(TEMPLATE / "browser.py")
        try:
            browser.find_browser()
        except browser.NoBrowser as exc:
            print(f"verify_app: skipping browser cases: {exc}", file=sys.stderr)
            raise unittest.SkipTest(str(exc))

    def test_a_click_and_a_form_post_download(self):
        code, manifest, output = self.run_harness(journeys=["click_and_download"], browser=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(manifest["facts"], {"download": "out.bin"})
        self.assertTrue((self.run_dir() / "clicked.png").stat().st_size)
        self.assertEqual((self.run_dir() / "downloads" / "out.bin").read_bytes(), b"exported bytes")
        self.assertIn("POST /export", self.requests())
        network = json.loads((self.run_dir() / "network.json").read_text(encoding="utf-8"))
        self.assertIn("/export", " ".join(row["url"] for row in network))
        self.assert_clean(manifest)

    def test_click_text_clicks_the_one_exact_visible_match(self):
        code, manifest, output = self.run_harness(journeys=["click_by_text"], browser=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(manifest["facts"], {"result": "by text"})

    def test_click_text_fails_naming_the_count_unless_exactly_one_matches(self):
        for text, count in (("Nope", 0), ("Secret", 0), ("Copy", 2)):
            with self.subTest(text=text):
                shutil.rmtree(self.repo / "evidence", ignore_errors=True)
                code, manifest, _ = self.run_harness(journeys=["click_text_only"], browser=True, text=text)
                self.assertEqual(code, 1)
                detail = manifest["journeys"][0]["detail"]
                self.assertIn(f"{count} visible", detail)
                self.assertIn(repr(text), detail)

    def test_click_text_matches_the_rendered_text(self):
        """A big word above a small line renders as two lines; raw textContent runs them together."""
        code, manifest, output = self.run_harness(journeys=["click_stacked"], browser=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(manifest["journeys"][0]["outcome"], "passed", manifest["journeys"][0]["detail"])

    def test_an_expression_the_browser_cannot_return_fails_fast_with_exit_2(self):
        """A DOM node comes back by value as {}, which reads as false, so wait_for used to time out
        and blame the app (exit 1). The journey is what is wrong."""
        for journey in ("wait_node", "evaluate_window", "evaluate_nested"):
            with self.subTest(journey=journey):
                shutil.rmtree(self.repo / "evidence", ignore_errors=True)
                code, manifest, output = self.run_harness(journeys=[journey], browser=True)
                self.assertEqual(code, 2, output)
                row = manifest["journeys"][0]
                self.assertEqual(row["outcome"], "not judged")
                self.assertIn("JourneyError", row["detail"])
                self.assertIn("return a boolean, number or string", row["detail"])
                self.assertLess(row["seconds"], 10, "it must fail at once, not wait out wait_for's 30 s")
                self.assertIn("boolean, number or string", manifest["failure"])
                self.assert_clean(manifest)

    def test_click_text_target_table(self):
        """Every row of CLICK_TARGETS through the whole harness, so a failure shows its exit code."""
        for row, path, text, expected in CLICK_TARGETS:
            with self.subTest(row=row):
                shutil.rmtree(self.repo / "evidence", ignore_errors=True)
                code, manifest, output = self.run_harness(
                    journeys=["click_target"], browser=True, path=path, text=text,
                    expect=expected if isinstance(expected, str) else None,
                    timeout=5 if isinstance(expected, str) else 0.5)
                journey = manifest["journeys"][0]
                if isinstance(expected, str):
                    self.assertEqual((code, journey["outcome"]), (0, "passed"), journey["detail"] or output)
                else:
                    exit_code, count = expected
                    self.assertEqual((code, journey["outcome"]), (exit_code, "failed"), output)
                    self.assertIn(f"{count} visible elements", journey["detail"])
                    self.assertIn(repr(text), journey["detail"])
                self.assert_clean(manifest)

    def test_a_run_folder_deleted_mid_run_is_made_again_for_a_screenshot(self):
        code, manifest, output = self.run_harness(journeys=["wipe_evidence_in_browser"], browser=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(manifest["journeys"][0]["outcome"], "passed", manifest["journeys"][0]["detail"])
        self.assertTrue((self.run_dir() / "after-wipe.png").stat().st_size)
        self.assertEqual((self.run_dir() / "downloads" / "file.bin").read_bytes(), b"file bytes")
        self.assertTrue(json.loads((self.run_dir() / "network.json").read_text(encoding="utf-8")))

    def test_a_run_folder_deleted_mid_run_gets_its_downloads_folder_back_at_the_next_save(self):
        code, manifest, output = self.run_harness(journeys=["wipe_evidence_with_a_browser_open"], browser=True)
        self.assertEqual(code, 0, output)
        self.assertTrue((self.run_dir() / "downloads").is_dir())

    def test_clicks_wait_out_a_smooth_scroll(self):
        code, manifest, output = self.run_harness(journeys=["smooth_click", "smooth_click_text"], browser=True)
        self.assertEqual([(j["name"], j["outcome"], j["detail"]) for j in manifest["journeys"]],
                         [("smooth_click", "passed", None), ("smooth_click_text", "passed", None)], output)
        self.assertEqual(code, 0, output)

    def test_a_journey_key_with_a_slash_still_saves_its_failure_screenshot(self):
        code, manifest, output = self.run_harness(journeys=[], named={"pages/stuck one": "page_stuck"},
                                                  browser=True)
        self.assertEqual(code, 1, output)
        self.assertEqual(manifest["journeys"][0]["outcome"], "failed")
        self.assertTrue((self.run_dir() / "pages_stuck_one-failure.png").stat().st_size)

    def test_a_forbidden_request_fails_the_journey(self):
        code, manifest, _ = self.run_harness(journeys=["hits_forbidden"], browser=True)
        self.assertEqual(code, 1)
        self.assertEqual(manifest["journeys"][0]["outcome"], "failed")
        self.assertIn("POST /paid", manifest["journeys"][0]["detail"])

    def test_a_stuck_page_fails_and_saves_a_screenshot(self):
        code, manifest, _ = self.run_harness(journeys=["page_stuck"], browser=True)
        self.assertEqual(code, 1)
        self.assertEqual(manifest["journeys"][0]["outcome"], "failed")
        self.assertTrue((self.run_dir() / "page_stuck-failure.png").stat().st_size)

    def test_the_browser_process_dying_exits_2(self):
        code, manifest, _ = self.run_harness(journeys=["kill_browser"], browser=True)
        self.assertEqual(code, 2)
        self.assertEqual(manifest["journeys"][0]["outcome"], "not judged")
        self.assertIn("browser", manifest["failure"])
        self.assert_clean(manifest)

    def test_a_browser_death_the_journey_never_saw_exits_2(self):
        code, manifest, _ = self.run_harness(journeys=["kill_browser_quietly"], browser=True)
        self.assertEqual(code, 2)
        self.assertIn("browser", manifest["failure"])

    def test_no_browser_exits_2_before_launch(self):
        code, manifest, _ = self.run_harness(journeys=["click_and_download"], browser=True,
                                             env={"VERIFY_CHROME": str(self.outside / "none")})
        self.assertEqual(code, 2)
        self.assertIn("VERIFY_CHROME", manifest["failure"])
        self.assert_never_launched(manifest)

    def test_sigterm_with_a_browser_open_ends_it_and_exits_2(self):
        proc = self.start_and_wait({"journeys": ["wait_in_browser"], "browser": True})
        browser_pid = int((self.state / "browser.pid").read_text())
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=30), 2)
        self.assertTrue(gone(browser_pid))
        self.assertFalse(pathlib.Path((self.state / "browser.profile").read_text()).exists(),
                         "Browser.close removes its profile; the pipe closing at exit would not")
        self.assert_clean(self.manifest())


class EvaluateTable(unittest.TestCase):
    """Every row of EVALUATE_ROWS in one real browser tab. How a JourneyError reaches exit 2 is
    test_an_expression_the_browser_cannot_return_fails_fast_with_exit_2's part."""

    @classmethod
    def setUpClass(cls):
        cls.browser_mod = load(TEMPLATE / "browser.py")
        try:
            binary = cls.browser_mod.find_browser()
        except cls.browser_mod.NoBrowser as exc:
            print(f"verify_app: skipping browser cases: {exc}", file=sys.stderr)
            raise unittest.SkipTest(str(exc))
        cls.top = pathlib.Path(tempfile.mkdtemp(prefix="verify-app-evaluate-")).resolve()
        cls.browser = cls.browser_mod.Browser(binary, cls.top, cls.top)
        cls.page = cls.browser_mod.Page(cls.browser, "about:blank")

    def fresh(self):
        self.page.goto("data:text/html,<p>one</p><p>two</p>")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        shutil.rmtree(cls.top, ignore_errors=True)

    def test_every_row(self):
        for row, expression, expected in EVALUATE_ROWS:
            with self.subTest(row=row):
                self.fresh()
                if isinstance(expected, tuple) and expected[0] == UNRETURNABLE:
                    with self.assertRaises(self.browser_mod.JourneyError) as caught:
                        self.page.evaluate(expression)
                    self.assertIn(f"returned {expected[1]},", str(caught.exception))
                    self.assertIn("return a boolean, number or string", str(caught.exception))
                else:
                    self.assertEqual(self.page.evaluate(expression), expected)

    def test_the_handle_is_released_on_every_path(self):
        """A kept handle pins its object in the page for the tab's life: every result and every
        thrown exception CDP hands back by reference is released, a page's own throw included."""
        handed, released = [], []
        real = self.page.call

        def spy(method, params=None, timeout=30.0):
            if method == "Runtime.releaseObject":
                released.append(params["objectId"])
            reply = real(method, params, timeout)
            if method in ("Runtime.evaluate", "Runtime.callFunctionOn"):
                for found in (reply.get("result", {}), reply.get("exceptionDetails", {}).get("exception", {})):
                    if "objectId" in found:
                        handed.append(found["objectId"])
            return reply

        throws = ("(() => { throw new Error('the page threw') })()",
                  "({get a() { throw new Error('a getter threw') }})")
        for expression in [row[1] for row in EVALUATE_ROWS] + list(throws):
            self.fresh()
            with mock.patch.object(self.page, "call", spy):
                try:
                    self.page.evaluate(expression)
                except (self.browser_mod.JourneyError, self.browser_mod.PageError):
                    pass
        self.assertGreater(len(handed), len(EVALUATE_ROWS))
        self.assertEqual(sorted(released), sorted(handed))


if __name__ == "__main__":
    unittest.main()
