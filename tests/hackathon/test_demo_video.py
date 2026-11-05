"""Tests for skills/demo-video: offline checks on the template, and real takes when asked.

The end-to-end cases run only with HACKATHON_PLAYWRIGHT set to a dir holding
node_modules/playwright, whose browser build is installed or cached. They install nothing.
"""

import json
import os
import re
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
BAND_BOTTOM = 130  # The caption box sits 48 px off the bottom edge, and one line of it is about 66 px tall.
BAND_HEIGHT = 110
BAND_SIZE = (480, 24)
BAND_CHANGE = 1.0  # Mean change in gray level per pixel: encoder noise stays well under it.

# Imports a beats file the way record.mjs does, with no Playwright on hand, and checks its shape.
BEATS_SHAPE_CHECK = """
const { app, beats, requiredHosts = [] } = await import(process.argv[1]);
const fine = typeof app.cmd === 'string' && typeof app.url === 'string' && Array.isArray(requiredHosts)
  && beats.length > 0 && beats.every(b => typeof b.caption === 'string' && typeof b.act === 'function');
if (!fine) { console.error('bad shape'); process.exit(1); }
console.log(beats.length);
"""


def clean_env(**overrides):
    env = {k: v for k, v in os.environ.items() if k not in {"OUT", "SIZE", "FPS", "BEATS", "HEADED", "APP_CMD", "APP_URL", "PORT", "SLOW_SCRIPT_MS"}}
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


def srt_starts(path):
    stamps = re.findall(r"^(\d\d):(\d\d):(\d\d),(\d{3}) --> ", path.read_text(), re.MULTILINE)
    return [int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 for h, m, s, ms in stamps]


def caption_band(path):
    """The strip of each frame the caption sits in, small and gray, as one bytes object per frame."""
    width, height = BAND_SIZE
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"crop=iw:{BAND_HEIGHT}:0:ih-{BAND_BOTTOM},scale={width}:{height},format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True, check=True).stdout
    size = width * height
    return [raw[i:i + size] for i in range(0, len(raw), size)]


def band_difference(one, other):
    return sum(abs(a - b) for a, b in zip(one, other)) / len(one)


def band_changes(frames, fps):
    """The time each visible change in the band begins. A fade over a few frames counts as one."""
    changes = []
    changing = False
    for index in range(1, len(frames)):
        moved = band_difference(frames[index - 1], frames[index]) > BAND_CHANGE
        if moved and not changing:
            changes.append(index / fps)
        changing = moved
    return changes


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

    def wrap_browser(self, new_page_delay_ms=0):
        """Puts a Playwright shim in the project: always headless, since a test may have no display.

        The launch options land in launch.json, so a test can check that a take asked for a window. The
        delay comes before the page and so before the video, as a slow machine's would.
        """
        (self.root / "node_modules").unlink()
        shim = self.root / "node_modules" / "playwright"
        shim.mkdir(parents=True)
        real = Path(PLAYWRIGHT_DIR).resolve() / "node_modules" / "resolve-from-here.js"
        (shim / "package.json").write_text('{"type": "module", "main": "index.mjs"}')
        (shim / "index.mjs").write_text(f"""
import {{ createRequire }} from 'node:module';
import fs from 'node:fs';
const {{ chromium: real }} = createRequire({json.dumps(str(real))})('playwright');
export const chromium = {{ launch: async options => {{
  fs.writeFileSync('launch.json', JSON.stringify(options));
  const browser = await real.launch({{ ...options, headless: true }});
  const newContext = browser.newContext.bind(browser);
  browser.newContext = async contextOptions => {{
    const context = await newContext(contextOptions);
    const newPage = context.newPage.bind(context);
    context.newPage = async () => {{
      await new Promise(resolve => setTimeout(resolve, {new_page_delay_ms}));
      return newPage();
    }};
    return context;
  }};
  return browser;
}} }};
""")


def one_beat(act, extra=""):
    return (
        "export const app = { cmd: 'node server.mjs', url: 'http://unused.invalid/' };\n"
        f"{extra}\n"
        f"export const beats = [{{ caption: 'One beat', act: async ({{ page, click }}) => {{ {act} }} }}];\n")


# Four captions of different lengths, with nothing else moving in the band.
CAPTION_TAKE_SIZE = "1280x720"
CAPTION_TOLERANCE_S = 0.3
CAPTION_DELAYS_MS = (0, 1000)  # On a quick machine the gap before the page is under the tolerance, so force one too.
CAPTION_BEATS = (
    "export const app = { cmd: 'node server.mjs', url: 'http://unused.invalid/' };\n"
    "const act = async ({ page }) => { await page.waitForTimeout(1000); };\n"
    "export const beats = [\n"
    "  { caption: 'First', act },\n"
    "  { caption: 'The second caption is a good deal longer', act },\n"
    "  { caption: 'Third, of a middling length', act },\n"
    "  { caption: 'Fourth, and short again', act },\n"
    "];\n")


class TemplateOffline(unittest.TestCase):
    def test_skill_is_manual_and_named(self):
        text = (SKILL / "SKILL.md").read_text()
        head = text.split("---")[1]
        self.assertIn("name: demo-video", head)
        self.assertIn("disable-model-invocation: true", head)

    def test_skill_never_sends_a_rehearsal_outside_the_sandbox(self):
        text = (SKILL / "SKILL.md").read_text()
        self.assertNotIn("outside the sandbox", text)
        self.assertIn("their own terminal", text)
        for needed in ("out-clip", "out-rehearsal", "waitFor({ timeout })"):
            self.assertIn(needed, text)

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
        clip = project.root / "demo" / "out-clip"
        steps = json.loads((clip / "steps.json").read_text())["steps"]
        self.assertEqual([s["caption"][:4] for s in steps], ["Tick", "Relo"])
        srt = (clip / "captions.srt").read_text()
        self.assertEqual(srt.count(" --> "), 2)
        self.assertIn("00:00:00,000 --> ", srt.splitlines()[1])
        self.assertNotIn("Type one in", srt)
        _, duration = ffprobe(clip / "demo.mp4")
        expected = steps[-1]["end"] - steps[0]["start"]
        self.assertLess(abs(duration - expected), 1.5, "the lead-in beats are trimmed off")

    def test_a_clip_or_a_rehearsal_leaves_the_full_take_alone(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        self.assertEqual(project.take().returncode, 0)
        full = (project.out / "demo.mp4").read_bytes()

        clip = project.take(BEATS="1")
        self.assertEqual(clip.returncode, 0, clip.stderr)
        self.assertTrue((project.root / "demo" / "out-clip" / "demo.mp4").exists())
        self.assertEqual((project.out / "demo.mp4").read_bytes(), full, "a clip replaced the full take")

        project.wrap_browser()
        rehearsal = project.take(HEADED="1")
        self.assertEqual(rehearsal.returncode, 0, rehearsal.stderr)
        self.assertFalse(json.loads((project.root / "launch.json").read_text())["headless"])
        self.assertTrue((project.root / "demo" / "out-rehearsal" / "demo.mp4").exists())
        self.assertEqual((project.out / "demo.mp4").read_bytes(), full, "a rehearsal replaced the full take")

    def test_an_explicit_out_wins(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        project.wrap_browser()
        for name, overrides in (("clip", {"BEATS": "1"}), ("rehearsal", {"HEADED": "1"})):
            with self.subTest(name):
                result = project.take(OUT=f"demo/out-mine-{name}", **overrides)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((project.root / "demo" / f"out-mine-{name}" / "demo.mp4").exists())
        self.assertEqual(project.leftovers(), ["out-mine-clip", "out-mine-rehearsal"])

    def caption_take(self, delay_ms, **overrides):
        project = self.project(CAPTION_BEATS)
        if delay_ms:
            project.wrap_browser(new_page_delay_ms=delay_ms)
        result = project.take(SIZE=CAPTION_TAKE_SIZE, **overrides)
        self.assertEqual(result.returncode, 0, result.stderr)
        return project

    def test_captions_land_where_the_srt_says(self):
        for delay_ms in CAPTION_DELAYS_MS:
            with self.subTest(delay_ms=delay_ms):
                project = self.caption_take(delay_ms)
                starts = srt_starts(project.out / "captions.srt")
                self.assertEqual(len(starts), 4)
                changes = band_changes(caption_band(project.out / "demo.mp4"), 30)
                seen = f"changes {changes} against captions {starts}"
                # A take with a quick page load also opens on that first paint, beside the first caption.
                for change in changes:
                    self.assertLess(min(abs(start - change) for start in starts), CAPTION_TOLERANCE_S, seen)
                for start in starts:
                    self.assertLess(min(abs(start - change) for change in changes), CAPTION_TOLERANCE_S, seen)

    def test_captions_stay_true_when_the_first_page_is_slow_to_paint(self):
        project = self.caption_take(0, SLOW_SCRIPT_MS="4000")
        starts = srt_starts(project.out / "captions.srt")
        steps = json.loads((project.out / "steps.json").read_text())
        self.assertGreater(steps["lead"], 3.5, "the slow load really happened")
        changes = band_changes(caption_band(project.out / "demo.mp4"), 30)
        seen = f"changes {changes} against captions {starts}"
        for start in starts:
            self.assertLess(min(abs(start - change) for change in changes), CAPTION_TOLERANCE_S, seen)

    def test_a_wait_cannot_match_the_caption(self):
        passes_only_on_the_caption = self.project(one_beat("await page.getByText('One beat').waitFor({ timeout: 1000 });"))
        result = passes_only_on_the_caption.take()
        self.assert_failed_clean(passes_only_on_the_caption, result, "Timeout 1000ms")

    def test_a_caption_repeating_the_apps_text_does_not_break_a_wait(self):
        beats = (
            "export const app = { cmd: 'node server.mjs', url: 'http://unused.invalid/' };\n"
            "export const beats = [{ caption: 'To-do', act: async ({ page }) => {\n"
            "  await page.getByText('To-do', { exact: true }).waitFor();\n"
            "} }];\n")
        project = self.project(beats)
        result = project.take()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_overlay_can_be_seen_after_the_app_replaces_the_page(self):
        beats = (
            "export const app = { cmd: 'node server.mjs', url: 'http://unused.invalid/' };\n"
            "const wipe = async ({ page }) => {\n"
            "  await page.evaluate(() => { document.documentElement.replaceChildren(document.createElement('body')); });\n"
            "  await page.waitForTimeout(600);\n"
            "};\n"
            "const hold = async ({ page }) => { await page.waitForTimeout(1000); };\n"
            "export const beats = [{ caption: 'Wiped', act: wipe }, { caption: 'Still captioned', act: hold }];\n")
        project = self.project(beats)
        result = project.take(SIZE=CAPTION_TAKE_SIZE)
        self.assertEqual(result.returncode, 0, result.stderr)
        frames = caption_band(project.out / "demo.mp4")
        starts = srt_starts(project.out / "captions.srt")
        # The wiped page is plain white, so a frame with no overlay has no dark pixel in this band.
        at_second = frames[min(int((starts[1] + 0.5) * 30), len(frames) - 1)]
        self.assertLess(min(at_second), 100, "the caption is gone from the frame")

    def test_a_playwright_click_reaches_the_app_through_the_overlay(self):
        project = self.project(one_beat("await page.locator('#new-item').click({ timeout: 2000 });"
                                        " await page.locator('#new-item:focus').waitFor({ timeout: 1000 });"))
        result = project.take()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_beat_that_wedges_the_page_fails_at_the_next_caption(self):
        beats = (
            "export const app = { cmd: 'node server.mjs', url: 'http://unused.invalid/' };\n"
            "export const beats = [\n"
            "  { caption: 'Wedge', act: async ({ page }) => {\n"
            "    await page.evaluate(() => { setTimeout(() => { for (;;); }, 0); });\n"
            "  } },\n"
            "  { caption: 'Next', limit: 3, act: async () => {} },\n"
            "];\n")
        project = self.project(beats)
        self.assert_failed_clean(project, project.take(), "ran past its 3 s limit")

    def test_a_short_video_never_replaces_a_good_take(self):
        beats = one_beat("await page.waitForTimeout(5000);")
        project = self.project(beats)
        self.assertEqual(project.take().returncode, 0)
        good = (project.out / "demo.mp4").read_bytes()
        # A stand-in ffmpeg that cuts the video to a second, as a recorder dying midway would leave it.
        bin_dir = project.root / "bin"
        bin_dir.mkdir()
        real = shutil.which("ffmpeg")
        shim = bin_dir / "ffmpeg"
        shim.write_text(f'#!/bin/sh\ncase " $* " in *" -movflags "*) exec "{real}" -t 1 "$@";; *) exec "{real}" "$@";; esac\n')
        shim.chmod(0o755)
        result = project.take(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("the recording stopped early", result.stderr)
        self.assertEqual((project.out / "demo.mp4").read_bytes(), good)
        self.assertEqual(project.leftovers(), ["out"])

    def test_ffmpeg_cannot_read_a_keypress_from_the_terminal(self):
        self.assertIn("'-nostdin'", (TEMPLATE / "record.mjs").read_text())

    def test_a_retake_keeps_the_last_set_beside_it(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        self.assertEqual(project.take().returncode, 0)
        first = {name: (project.out / name).read_bytes() for name in ("demo.mp4", "captions.srt", "steps.json")}
        self.assertFalse((project.out / "demo.prev.mp4").exists())
        self.assertEqual(project.take().returncode, 0)
        for name, kept in (("demo.prev.mp4", "demo.mp4"), ("captions.prev.srt", "captions.srt"), ("steps.prev.json", "steps.json")):
            self.assertEqual((project.out / name).read_bytes(), first[kept], name)

    def test_a_first_load_past_the_step_timeout_is_fine(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        result = project.take(SLOW_SCRIPT_MS="9000", SIZE="640x360")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_signal_during_the_encode_publishes_nothing(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        self.assertEqual(project.take().returncode, 0)
        good = (project.out / "demo.mp4").read_bytes()
        bin_dir = project.root / "bin"
        bin_dir.mkdir()
        real = shutil.which("ffmpeg")
        marker = project.root / "encoding"
        shim = bin_dir / "ffmpeg"
        shim.write_text(f'#!/bin/sh\ncase " $* " in *" -movflags "*) touch "{marker}"; sleep 2;; esac\nexec "{real}" "$@"\n')
        shim.chmod(0o755)
        take = subprocess.Popen([NODE, "demo/record.mjs"], cwd=project.root,
                                env=project.env(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}"),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(take.wait)
        self.addCleanup(take.kill)
        for _ in range(600):
            if marker.exists():
                break
            time.sleep(0.05)
        self.assertTrue(marker.exists(), "the take never reached its encode")
        take.send_signal(signal.SIGTERM)
        self.assertEqual(take.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertEqual((project.out / "demo.mp4").read_bytes(), good)
        self.assertFalse((project.out / "demo.prev.mp4").exists())
        self.assertEqual(project.leftovers(), ["out"])

    def test_a_second_tab_is_watched_and_warned_about(self):
        opener = ("const [tab] = await Promise.all([page.context().waitForEvent('page'),"
                  " page.evaluate(() => { window.open('/', '_blank'); })]);"
                  " await tab.waitForLoadState();")
        project = self.project(one_beat(opener + " await page.waitForTimeout(300);"))
        result = project.take()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("a second tab opened", result.stderr)
        self.assertEqual(len(json.loads((project.out / "steps.json").read_text())["warnings"]), 1)

        broken = self.project(one_beat(opener + " await tab.evaluate(() => fetch('/boom')); await page.waitForTimeout(100);"))
        self.assert_failed_clean(broken, broken.take(), "HTTP 500")

    def test_a_clip_starts_on_its_first_caption(self):
        for delay_ms in CAPTION_DELAYS_MS:
            with self.subTest(delay_ms=delay_ms):
                clip = self.caption_take(delay_ms, BEATS="2-3").root / "demo" / "out-clip"
                starts = srt_starts(clip / "captions.srt")
                self.assertEqual(starts[0], 0)
                frames = caption_band(clip / "demo.mp4")
                changes = band_changes(frames, 30)
                seen = f"changes {changes} against captions {starts}"
                # The earlier beat's caption may show for a frame or two, but no longer than the tolerance.
                late = [change for change in changes if change >= CAPTION_TOLERANCE_S]
                self.assertEqual(len(late), 1, seen)
                self.assertLess(abs(starts[1] - late[0]), CAPTION_TOLERANCE_S, seen)
                settled = frames[int(CAPTION_TOLERANCE_S * 30)]
                just_before_next = frames[int(late[0] * 30) - 2]
                self.assertLess(band_difference(settled, just_before_next), BAND_CHANGE, "the clip opens on another caption")

    def test_a_slow_step_gets_its_own_wait_and_the_default_stays(self):
        late = ("await page.evaluate(() => { setTimeout(() => { const late = document.createElement('p');"
                " late.id = 'late'; document.body.append(late); }, 9000); });")
        slow = self.project(one_beat(late + " await page.locator('#late').waitFor({ state: 'attached', timeout: 15000 });"))
        result = slow.take()
        self.assertEqual(result.returncode, 0, result.stderr)

        default = self.project(one_beat(late + " await page.locator('#late').waitFor({ state: 'attached' });"))
        self.assert_failed_clean(default, default.take(), "8000ms")

    def test_a_beat_limit_can_be_raised_past_the_default(self):
        beats = (
            "export const app = { cmd: 'node server.mjs', url: 'http://unused.invalid/' };\n"
            "export const beats = [{ caption: 'A long live call', limit: 75, act: async ({ page }) => {\n"
            "  await page.waitForTimeout(61000);\n"
            "} }];\n")
        project = self.project(beats)
        result = project.take(SIZE="640x360")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_app_that_exits_at_once(self):
        project = self.project()
        result = project.take(APP_CMD="exit 0")
        self.assert_failed_clean(project, result, "before it answered")

    def test_app_failure_shows_its_output(self):
        project = self.project()
        result = project.take(APP_CMD="echo the-reason-it-died; exit 7")
        self.assert_failed_clean(project, result, "the-reason-it-died")

    def test_failed_take_keeps_the_previous_video_and_says_so(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        self.assertEqual(project.take().returncode, 0)
        video = project.out / "demo.mp4"
        before = video.read_bytes()
        result = project.take(APP_CMD="exit 0")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("is the previous take, unchanged", result.stderr)
        self.assertEqual(video.read_bytes(), before)
        self.assertEqual(project.leftovers(), ["out"], "a failed take left its staging dir")
        self.assertFalse(port_open(project.port), "the app outlived the take")

    def test_output_dir_keeps_files_it_did_not_write(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        project.out.mkdir()
        (project.out / "notes.txt").write_text("mine")
        failed = project.take(APP_CMD="exit 0")
        self.assertEqual(failed.returncode, 1)
        self.assertEqual([p.name for p in project.out.iterdir()], ["notes.txt"])
        good = project.take()
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(sorted(p.name for p in project.out.iterdir()),
                         ["captions.srt", "demo.mp4", "notes.txt", "steps.json"])

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
        self.wait_for_port(project, take)
        time.sleep(2)
        take.send_signal(signal.SIGTERM)
        self.assertEqual(take.wait(timeout=30), 128 + signal.SIGTERM)
        self.assertEqual(project.leftovers(), [])
        self.assertFalse(port_open(project.port), "the app outlived the take")

    def test_a_signal_takes_down_an_app_that_ignores_sigterm(self):
        for sent in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(sent.name):
                project = self.project()
                stubborn = project.root / "stubborn.mjs"
                stubborn.write_text("process.on('SIGTERM', () => {}); await import('./server.mjs');\n")
                take = subprocess.Popen([NODE, "demo/record.mjs"], cwd=project.root,
                                        env=project.env(APP_CMD="exec node stubborn.mjs"),
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.addCleanup(take.wait)
                self.addCleanup(take.kill)
                self.wait_for_port(project, take)
                time.sleep(3)  # The browser is up by now, and Playwright's own handlers would be too.
                take.send_signal(sent)
                self.assertEqual(take.wait(timeout=30), 128 + sent)
                self.assertFalse(port_open(project.port), "the app outlived the take")

    def wait_for_port(self, project, take):
        for _ in range(200):
            if port_open(project.port):
                return
            time.sleep(0.05)
        self.fail(f"the app never opened its port, take exit {take.poll()}")


if __name__ == "__main__":
    unittest.main()
