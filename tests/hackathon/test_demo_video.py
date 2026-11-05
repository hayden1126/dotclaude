"""Tests for skills/demo-video: offline checks on the template, and real takes when asked.

The end-to-end cases run only with HACKATHON_PLAYWRIGHT set to a dir holding
node_modules/playwright, whose browser build is installed or cached. They install nothing.
"""

import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SKILL = REPO / "skills" / "demo-video"
TEMPLATE = SKILL / "template"
FIXTURE = HERE / "fixtures" / "todo-app"
PLAYWRIGHT_DIR = os.environ.get("HACKATHON_PLAYWRIGHT")
NODE = shutil.which("node")
TAKE_TIMEOUT_S = 120

# Imports a beats file the way record.mjs does, with no Playwright on hand, and checks its shape.
BEATS_SHAPE_CHECK = """
const { app, beats, requiredHosts = [] } = await import(process.argv[1]);
const fine = typeof app.cmd === 'string' && typeof app.url === 'string' && Array.isArray(requiredHosts)
  && beats.length > 0 && beats.every(b => typeof b.caption === 'string' && typeof b.act === 'function');
if (!fine) { console.error('bad shape'); process.exit(1); }
console.log(beats.length);
"""


def clean_env(**overrides):
    env = {k: v for k, v in os.environ.items() if k not in {"OUT", "SIZE", "FPS", "BEATS", "HEADED", "APP_CMD", "APP_URL", "PORT"}}
    env.update(overrides)
    return env


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def port_open(port):
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def ffprobe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return data["streams"][0], float(data["format"]["duration"])


def top_level_atoms(path):
    atoms = []
    with open(path, "rb") as video:
        while header := video.read(8):
            size, kind = struct.unpack(">I4s", header)
            atoms.append(kind.decode("latin-1"))
            if size == 1:
                size = struct.unpack(">Q", video.read(8))[0]
                video.seek(size - 16, os.SEEK_CUR)
            elif size == 0:
                break
            else:
                video.seek(size - 8, os.SEEK_CUR)
    return atoms


class Project:
    """A throwaway project laid out the way the skill says: template in demo/, app beside it."""

    def __init__(self, root, beats_text=None, beats_file=FIXTURE / "beats.mjs"):
        self.root = Path(root)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/"
        self.out = self.root / "demo" / "out"
        (self.root / "demo").mkdir()
        shutil.copy(TEMPLATE / "record.mjs", self.root / "demo" / "record.mjs")
        shutil.copy(FIXTURE / "server.mjs", self.root / "server.mjs")
        if beats_text is None:
            shutil.copy(beats_file, self.root / "demo" / "beats.mjs")
        else:
            (self.root / "demo" / "beats.mjs").write_text(beats_text)
        if PLAYWRIGHT_DIR:
            (self.root / "node_modules").symlink_to(Path(PLAYWRIGHT_DIR) / "node_modules")

    def env(self, **overrides):
        return clean_env(PORT=str(self.port), APP_URL=self.url, **overrides)

    def take(self, **overrides):
        return subprocess.run([NODE, "demo/record.mjs"], cwd=self.root, env=self.env(**overrides),
                              capture_output=True, text=True, timeout=TAKE_TIMEOUT_S)

    def leftovers(self):
        return sorted(p.name for p in (self.root / "demo").iterdir() if p.name.startswith("out"))


def one_beat(act, extra=""):
    return (
        "export const app = { cmd: 'node server.mjs', url: 'http://unused.invalid/' };\n"
        f"{extra}\n"
        f"export const beats = [{{ caption: 'One beat', act: async ({{ page, click }}) => {{ {act} }} }}];\n")


class TemplateOffline(unittest.TestCase):
    def test_skill_is_manual_and_named(self):
        text = (SKILL / "SKILL.md").read_text()
        head = text.split("---")[1]
        self.assertIn("name: demo-video", head)
        self.assertIn("disable-model-invocation: true", head)

    def test_skill_fits_itself_to_the_event(self):
        text = (SKILL / "SKILL.md").read_text()
        for needed in ("EVENT.md", "submission asset, a stage backup or both", "may not apply", "BEATS="):
            self.assertIn(needed, text)

    def test_machinery_keeps_no_project_specifics(self):
        text = (TEMPLATE / "record.mjs").read_text()
        for leftover in ("LOOPS", "stamps", "errand", "library book"):
            self.assertNotIn(leftover, text)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_node_check_passes(self):
        files = [TEMPLATE / "record.mjs", TEMPLATE / "beats.mjs", FIXTURE / "server.mjs", FIXTURE / "beats.mjs"]
        for path in files:
            with self.subTest(path=path.name):
                result = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_beats_files_parse_without_playwright(self):
        for path in (TEMPLATE / "beats.mjs", FIXTURE / "beats.mjs"):
            with self.subTest(path=str(path.relative_to(REPO))):
                result = subprocess.run(
                    [NODE, "--input-type=module", "-e", BEATS_SHAPE_CHECK, path.as_uri()],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertGreater(int(result.stdout), 0)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_bad_size_fails_loud(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Project(tmp)
            for size in ("big", "1921x1080", "0x0"):
                with self.subTest(size=size):
                    result = project.take(SIZE=size)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("SIZE must be", result.stderr)
                    self.assertEqual(project.leftovers(), [])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_bad_fps_and_beat_range_fail_loud(self):
        cases = [("FPS", "fast", "FPS must be"), ("FPS", "0", "FPS must be")]
        cases += [("BEATS", value, "BEATS must be") for value in ("x", "0", "5-2", "99", "1-99")]
        with tempfile.TemporaryDirectory() as tmp:
            project = Project(tmp)
            for name, value, expected in cases:
                with self.subTest(name=name, value=value):
                    result = project.take(**{name: value})
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(expected, result.stderr)
                    self.assertEqual(project.leftovers(), [])


@unittest.skipUnless(PLAYWRIGHT_DIR, "set HACKATHON_PLAYWRIGHT to a dir holding node_modules/playwright")
class Takes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (Path(PLAYWRIGHT_DIR) / "node_modules" / "playwright").is_dir():
            raise AssertionError(f"no node_modules/playwright in {PLAYWRIGHT_DIR}")

    def project(self, *args, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Project(tmp.name, *args, **kwargs)

    def assert_failed_clean(self, project, result, expected):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stderr)
        self.assertEqual(project.leftovers(), [], "a failed take left something behind")
        self.assertFalse(port_open(project.port), "the app outlived the take")

    def test_good_take_then_a_second_of_the_same_length(self):
        project = self.project()
        first = project.take()
        self.assertEqual(first.returncode, 0, first.stderr)
        stream, duration = ffprobe(project.out / "demo.mp4")
        self.assertEqual(stream["codec_name"], "h264")
        self.assertEqual((stream["width"], stream["height"]), (1920, 1080))
        self.assertEqual(stream["pix_fmt"], "yuv420p")
        self.assertEqual(stream["r_frame_rate"], "30/1")
        self.assertEqual(stream["avg_frame_rate"], "30/1")
        atoms = top_level_atoms(project.out / "demo.mp4")
        self.assertLess(atoms.index("moov"), atoms.index("mdat"), "+faststart puts moov first")

        steps = json.loads((project.out / "steps.json").read_text())
        self.assertEqual(len(steps["steps"]), 6)
        srt = (project.out / "captions.srt").read_text()
        self.assertEqual(srt.count(" --> "), 6)
        self.assertIn("Tick one off, and the count follows", srt)
        self.assertEqual(sorted(p.name for p in project.out.iterdir()), ["captions.srt", "demo.mp4", "steps.json"])
        self.assertEqual(project.leftovers(), ["out"])
        self.assertFalse(port_open(project.port), "the app outlived the take")

        second = project.take()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertLess(abs(duration - ffprobe(project.out / "demo.mp4")[1]), 2)

    def test_template_example_drives_the_fixture(self):
        project = self.project(beats_file=TEMPLATE / "beats.mjs")
        result = project.take(APP_CMD="node server.mjs")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((project.out / "demo.mp4").exists())

    def test_format_overrides(self):
        act = "await page.waitForTimeout(300);"
        project = self.project(one_beat(act))
        result = project.take(SIZE="1280x720", FPS="24")
        self.assertEqual(result.returncode, 0, result.stderr)
        stream, _ = ffprobe(project.out / "demo.mp4")
        self.assertEqual((stream["width"], stream["height"]), (1280, 720))
        self.assertEqual(stream["r_frame_rate"], "24/1")

        in_beats = self.project(one_beat(act, "export const size = '640x360';"))
        self.assertEqual(in_beats.take().returncode, 0)
        stream, _ = ffprobe(in_beats.out / "demo.mp4")
        self.assertEqual((stream["width"], stream["height"]), (640, 360))
        self.assertEqual(in_beats.take(SIZE="1280x720").returncode, 0)
        stream, _ = ffprobe(in_beats.out / "demo.mp4")
        self.assertEqual((stream["width"], stream["height"]), (1280, 720), "SIZE beats beats.mjs")

    def test_clip_of_a_few_beats_needs_the_earlier_ones_for_its_state(self):
        project = self.project()
        result = project.take(BEATS="5-6")
        self.assertEqual(result.returncode, 0, result.stderr)
        steps = json.loads((project.out / "steps.json").read_text())["steps"]
        self.assertEqual([s["caption"][:4] for s in steps], ["Tick", "Relo"])
        srt = (project.out / "captions.srt").read_text()
        self.assertEqual(srt.count(" --> "), 2)
        self.assertIn("00:00:00,000 --> ", srt.splitlines()[1])
        self.assertNotIn("Type one in", srt)
        _, duration = ffprobe(project.out / "demo.mp4")
        expected = steps[-1]["end"] - steps[0]["start"]
        self.assertLess(abs(duration - expected), 1.5, "the lead-in beats are trimmed off")

    def test_app_that_exits_at_once(self):
        project = self.project()
        result = project.take(APP_CMD="exit 0")
        self.assert_failed_clean(project, result, "before it answered")

    def test_app_failure_shows_its_output(self):
        project = self.project()
        result = project.take(APP_CMD="echo the-reason-it-died; exit 7")
        self.assert_failed_clean(project, result, "the-reason-it-died")

    def test_failed_take_removes_the_previous_video(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        self.assertEqual(project.take().returncode, 0)
        self.assertTrue((project.out / "demo.mp4").exists())
        result = project.take(APP_CMD="exit 0")
        self.assert_failed_clean(project, result, "before it answered")

    def test_output_dir_keeps_files_it_did_not_write(self):
        project = self.project()
        project.out.mkdir()
        (project.out / "notes.txt").write_text("mine")
        result = project.take(APP_CMD="exit 0")
        self.assertEqual(result.returncode, 1)
        self.assertEqual([p.name for p in project.out.iterdir()], ["notes.txt"])

    def test_port_already_answering(self):
        project = self.project()
        squatter = subprocess.Popen([NODE, "server.mjs"], cwd=project.root, env=project.env(),
                                    stdout=subprocess.DEVNULL)
        self.addCleanup(squatter.wait)
        self.addCleanup(squatter.kill)
        for _ in range(100):
            if port_open(project.port):
                break
            time.sleep(0.05)
        result = project.take()
        self.assertEqual(result.returncode, 1)
        self.assertIn("already answers", result.stderr)
        self.assertEqual(project.leftovers(), [])

    def test_each_failure_kills_the_take(self):
        cases = {
            "page error": ("await page.evaluate(() => { setTimeout(() => { throw new Error('kaput'); }); });", "kaput"),
            "5xx": ("await page.evaluate(() => fetch('/boom'));", "HTTP 500"),
            "first-party request": ("await page.evaluate(() => fetch('/drop').catch(() => {}));", "request failed"),
            "step timeout": ("await click('#nothing-here');", "#nothing-here"),
            "app dies midway": ("await page.evaluate(() => fetch('/die').catch(() => {}));", "the app exited"),
        }
        for name, (act, expected) in cases.items():
            with self.subTest(name):
                project = self.project(one_beat(act))
                self.assert_failed_clean(project, project.take(), expected)

    def test_beat_limit_catches_a_hung_action(self):
        beats = (
            "export const app = { cmd: 'node server.mjs', url: 'http://unused.invalid/' };\n"
            "export const beats = [{ caption: 'Hangs', limit: 1, act: () => new Promise(() => {}) }];\n")
        project = self.project(beats)
        self.assert_failed_clean(project, project.take(), "ran past its 1 s limit")

    def test_page_cancelling_its_own_request_is_not_a_failure(self):
        act = ("await page.evaluate(async () => { const stop = new AbortController();"
               " const pending = fetch('/hang', { signal: stop.signal }).catch(() => {});"
               " await new Promise(r => setTimeout(r, 300)); stop.abort(); await pending; });")
        project = self.project(one_beat(act))
        result = project.take()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_third_party_failure_warns_unless_required(self):
        closed = free_port()
        act = (f"await page.evaluate(() => {{ const img = document.createElement('img');"
               f" img.src = 'http://127.0.0.2:{closed}/font.png'; document.body.append(img); }});"
               " await page.waitForTimeout(500);")

        project = self.project(one_beat(act))
        result = project.take()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("third-party", result.stderr)
        self.assertEqual(len(json.loads((project.out / "steps.json").read_text())["warnings"]), 1)

        strict = self.project(one_beat(act, "export const requiredHosts = ['127.0.0.2'];"))
        self.assert_failed_clean(strict, strict.take(), "request failed")

    def test_signal_stops_the_app_and_leaves_nothing(self):
        project = self.project()
        take = subprocess.Popen([NODE, "demo/record.mjs"], cwd=project.root, env=project.env(),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(take.wait)
        self.addCleanup(take.kill)
        for _ in range(200):
            if port_open(project.port):
                break
            time.sleep(0.05)
        time.sleep(2)
        take.send_signal(signal.SIGTERM)
        self.assertEqual(take.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertEqual(project.leftovers(), [])
        for _ in range(60):
            if not port_open(project.port):
                break
            time.sleep(0.05)
        self.assertFalse(port_open(project.port), "the app outlived the take")


if __name__ == "__main__":
    unittest.main()
