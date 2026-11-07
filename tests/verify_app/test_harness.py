"""The verify harness against a fixture app: one planted break per promise. Each test builds a temp
git repo holding the template's files, picks a free port and runs verify.py as a subprocess. Signal
tests use Popen on the pid directly, never a shell's `&`, which makes children ignore SIGINT."""
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
import unittest

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE.parents[1] / "skills" / "verify-app" / "template"
EXITS = {0: "proved", 1: "app failed", 2: "could not judge", 3: "cleanup failed"}


def load(path: pathlib.Path):
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
        for name in ("verify.py", "browser.py"):
            shutil.copy(TEMPLATE / name, self.skill / name)
        shutil.copy(HERE / "fixture" / "journeys.py", self.skill / "journeys.py")
        (self.repo / ".gitignore").write_text("evidence/\n__pycache__/\n", encoding="utf-8")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "start")
        self.port = free_port()
        self.addCleanup(self.reap_child)

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
        return [sys.executable, *flags, str(self.skill / "verify.py"), *args]

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

    def test_python_isolated_mode_works(self):
        code, _, output = self.run_harness(flags=("-I", "-B"))
        self.assertEqual(code, 0, output)
        self.assertFalse((self.skill / "__pycache__").exists())

    def test_it_runs_from_any_directory(self):
        code, _, output = self.run_harness(cwd=self.outside)
        self.assertEqual(code, 0, output)

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
    def test_unfilled_markers_exit_2_naming_them(self):
        shutil.copy(TEMPLATE / "journeys.py", self.skill / "journeys.py")
        code, manifest, output = self.run_harness()
        self.assertEqual(code, 2)
        self.assertIn("<fill:", output)
        self.assertIsNone(manifest)

    def test_a_marker_left_in_the_recipe_exits_2(self):
        (self.skill / "SKILL.md").write_text("Skip paths: <fill: paths>\n", encoding="utf-8")
        code, _, output = self.run_harness()
        self.assertEqual(code, 2)
        self.assertIn("<fill: paths>", output)

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
                             ("doctor", {"doctor": []}),
                             ("journeys", {"journeys": []})):
            with self.subTest(name=name):
                self.assertEqual(self.run_harness(**config)[0], 2)

    def test_a_missing_journeys_file_exits_2(self):
        (self.skill / "journeys.py").unlink()
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


if __name__ == "__main__":
    unittest.main()
