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
    env = {k: v for k, v in os.environ.items() if k not in {"OUT", "SIZE", "FPS", "BEATS", "HEADED", "APP_CMD", "APP_URL", "PORT", "SLOW_SCRIPT_MS", "SLOW_ROOT_MS", "VOICE"}}
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


def stream_codecs(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
                            capture_output=True, text=True, check=True)
    return result.stdout.split()


def tone(path, seconds, lead=0.0, frequency=440, gain=4, rate=48000):
    """A stand-in voice: a tone after `lead` seconds of silence, at -6 dB unless `gain` says otherwise."""
    graph = f"sine=frequency={frequency}:sample_rate={rate}:duration={seconds},volume={gain}"
    if lead:
        graph += f",adelay={int(lead * 1000)}:all=1"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", graph, str(path)], check=True)


def sequence(path, parts, rate=48000, noise=0.0):
    """A stand-in voice from parts in order: (frequency or None for silence, seconds, gain), over room noise.

    One expression, so a part's level is exact however quiet (gain 1 is the sine source's default -18 dB).
    """
    terms, at = [f"{noise}*(random(0)-0.5)"] if noise else [], 0.0
    for frequency, seconds, *gain in parts:
        if frequency:
            terms.append(f"{(gain[0] if gain else 4) / 8}*sin(2*PI*{frequency}*t)*between(t\\,{at:.6f}\\,{at + seconds - 1 / rate:.6f})")
        at += seconds
    expression = "+".join(terms) or "0"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"aevalsrc={expression}:s={rate}:c=mono:d={at:.6f}", str(path)], check=True)


def level(path, start, end, frequency=None):
    """The mean level in dB between two times, in a narrow band around `frequency` when given."""
    band = f"bandpass=f={frequency}:width_type=h:width=60," * 4 if frequency else ""  # One pass leaks a loud tone nearby.
    result = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-ss", str(start), "-t", str(end - start), "-i", str(path),
                             "-map", "0:a:0", "-af", band + "volumedetect", "-f", "null", "-"],
                            capture_output=True, text=True, check=True)
    found = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", result.stderr)
    return float(found.group(1)) if found else float("-inf")


def video_hash(path):
    result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy",
                             "-f", "md5", "-"], capture_output=True, text=True, check=True)
    return result.stdout.strip()


class Project:
    """A throwaway project laid out the way the skill says: template in demo/, app beside it."""

    def __init__(self, root, beats_text=None, beats_file=FIXTURE / "beats.mjs"):
        self.root = Path(root)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/"
        self.out = self.root / "demo" / "out"
        (self.root / "demo").mkdir()
        shutil.copy(TEMPLATE / "record.mjs", self.root / "demo" / "record.mjs")
        shutil.copy(TEMPLATE / "voice.mjs", self.root / "demo" / "voice.mjs")
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

    def wrap_browser(self, new_page_delay_ms=0, set_content_delay_ms=0):
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
      const page = await newPage();
      const setContent = page.setContent.bind(page);
      page.setContent = async (...args) => {{
        await setContent(...args);
        await new Promise(resolve => setTimeout(resolve, {set_content_delay_ms}));
      }};
      return page;
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

    def test_ffmpeg_cannot_read_a_keypress_from_the_terminal(self):
        self.assertIn("'-nostdin'", (TEMPLATE / "record.mjs").read_text())

    def test_setup_keeps_beats_already_written(self):
        text = (SKILL / "SKILL.md").read_text()
        command = re.search(r"`(mkdir -p demo && cat .*?)`\. Add", text).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            env = clean_env(CLAUDE_SKILL_DIR=str(SKILL))
            subprocess.run(["sh", "-c", command], cwd=tmp, env=env, check=True)
            beats = Path(tmp) / "demo" / "beats.mjs"
            self.assertEqual(beats.read_text(), (TEMPLATE / "beats.mjs").read_text())
            beats.write_text("// mine")
            (Path(tmp) / "demo" / "record.mjs").write_text("// old")
            subprocess.run(["sh", "-c", command], cwd=tmp, env=env, check=True)
            self.assertEqual(beats.read_text(), "// mine")
            self.assertEqual((Path(tmp) / "demo" / "record.mjs").read_text(), (TEMPLATE / "record.mjs").read_text())
            self.assertEqual((Path(tmp) / "demo" / "voice.mjs").read_text(), (TEMPLATE / "voice.mjs").read_text())

    def test_a_voice_recording_stays_out_of_git_and_out_of_an_agents_hands(self):
        text = (SKILL / "SKILL.md").read_text()
        self.assertIn("`demo/voice*/` and `demo/node_modules/`", text)
        self.assertIn("Never run the line for them with the sandbox off", text)
        self.assertIn("never run `voice.mjs` with the sandbox off", text)
        self.assertNotIn("RDPSource", (TEMPLATE / "record.mjs").read_text())

    def test_voice_never_records(self):
        text = (TEMPLATE / "voice.mjs").read_text()
        # The capture device appears once, in the line it prints, and that line only ever goes to console.log.
        self.assertEqual(text.count("RDPSource"), 1)
        self.assertEqual(text.count("pulse"), 1)
        uses = [line for line in text.splitlines() if "recordLine(" in line]
        self.assertTrue(uses)
        for line in uses:
            self.assertTrue(line.startswith("const recordLine") or "console.log(" in line, line)

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
        for name in ("record.mjs", "voice.mjs"):
            text = (TEMPLATE / name).read_text()
            for leftover in ("LOOPS", "stamps", "errand", "library book"):
                self.assertNotIn(leftover, text)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_node_check_passes(self):
        files = [TEMPLATE / "record.mjs", TEMPLATE / "voice.mjs", TEMPLATE / "beats.mjs", FIXTURE / "server.mjs",
                 FIXTURE / "beats.mjs"]
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

        in_beats = self.project(one_beat(act, "export const size = '640x360';\nexport const fps = 24;"))
        self.assertEqual(in_beats.take().returncode, 0)
        stream, _ = ffprobe(in_beats.out / "demo.mp4")
        self.assertEqual((stream["width"], stream["height"]), (640, 360))
        self.assertEqual(stream["r_frame_rate"], "24/1", "fps in beats.mjs holds for every retake")
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

    def test_captions_stay_true_when_the_start_page_returns_late(self):
        project = self.project(CAPTION_BEATS)
        project.wrap_browser(set_content_delay_ms=1000)
        result = project.take(SIZE=CAPTION_TAKE_SIZE)
        self.assertEqual(result.returncode, 0, result.stderr)
        starts = srt_starts(project.out / "captions.srt")
        changes = band_changes(caption_band(project.out / "demo.mp4"), 30)
        seen = f"changes {changes} against captions {starts}"
        for start in starts[1:]:
            self.assertLess(min(abs(start - change) for change in changes), CAPTION_TOLERANCE_S, seen)

    def test_an_empty_video_never_replaces_a_short_clip(self):
        # A clip starts on its own first caption, so a quick beat runs just under a second.
        project = self.project(
            "export const app = { cmd: 'node server.mjs', url: 'http://unused.invalid/' };\n"
            "export const beats = [{ caption: 'First', act: async () => {} }, { caption: 'Quick', act: async () => {} }];\n")
        self.assertEqual(project.take(BEATS="2", SIZE="640x360").returncode, 0)
        clip = project.root / "demo" / "out-clip" / "demo.mp4"
        good = clip.read_bytes()
        bin_dir = project.root / "bin"
        bin_dir.mkdir()
        real = shutil.which("ffmpeg")
        shim = bin_dir / "ffmpeg"
        # Seeking past the end gives an mp4 with no frames and exit 0, whose length reads N/A.
        shim.write_text(
            '#!/bin/sh\ncase " $* " in *" -movflags "*)\n'
            '  prev=""; n=$#; i=0\n'
            '  while [ $i -lt $n ]; do a=$1; shift; [ "$prev" = "-ss" ] && a=9999; set -- "$@" "$a"; prev=$a; i=$((i+1)); done;;\n'
            f'esac\nexec "{real}" "$@"\n')
        shim.chmod(0o755)
        result = project.take(BEATS="2", SIZE="640x360", PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(clip.read_bytes(), good)

    def test_a_scheme_less_proxy_variable_and_a_local_app_on_another_address(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        dead = f"127.0.0.1:{free_port()}"
        env = {name: dead for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
        result = project.take(SIZE="640x360", **env)
        self.assertEqual(result.returncode, 0, result.stderr)

        other = self.project(one_beat("await page.waitForTimeout(100);"))
        env = clean_env(PORT=str(other.port), SIZE="640x360", APP_URL=f"http://0.0.0.0:{other.port}/", NO_PROXY="", no_proxy="",
                        **{name: "http://" + dead for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")})
        result = subprocess.run([NODE, "demo/record.mjs"], cwd=other.root, env=env, capture_output=True, text=True,
                                timeout=TAKE_TIMEOUT_S)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_redirect_to_another_host_keeps_the_apps_failures_loud(self):
        for page_html, act in (("<h1>x</h1>", "await page.evaluate(() => fetch('/boom'));"),
                               ("<script src=/boom></script><h1>x</h1>", "await page.waitForTimeout(100);")):
            with self.subTest(page_html):
                self.check_a_redirect(page_html, act)

    def check_a_redirect(self, page_html, act):
        project = self.project(one_beat(act))
        (project.root / "redirects.mjs").write_text(
            "import http from 'node:http';\n"
            "http.createServer((request, response) => {\n"
            "  if (request.headers.host.startsWith('127.0.0.3')) {\n"
            "    response.writeHead(302, { location: `http://127.0.0.2:${process.env.PORT}/` });\n"
            "    return response.end();\n"
            "  }\n"
            "  if (request.url === '/boom') { response.statusCode = 500; return response.end(); }\n"
            "  response.setHeader('content-type', 'text/html');\n"
            f"  response.end('<!doctype html><title>x</title>{page_html}');\n"
            "}).listen(Number(process.env.PORT), '0.0.0.0');\n")
        running = subprocess.Popen([NODE, "redirects.mjs"], cwd=project.root, env=project.env(), stdout=subprocess.DEVNULL)
        self.addCleanup(running.wait)
        self.addCleanup(running.kill)
        self.wait_for_port(project, running)
        result = subprocess.run([NODE, "demo/record.mjs"], cwd=project.root, capture_output=True, text=True, timeout=TAKE_TIMEOUT_S,
                                env=clean_env(PORT=str(project.port), APP_CMD="", APP_URL=f"http://127.0.0.3:{project.port}/"))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("HTTP 500", result.stderr)

    @unittest.skipUnless(shutil.which("openssl"), "openssl is not installed")
    def test_a_self_signed_app_records_when_the_project_says_so(self):
        project = self.project(one_beat("await page.locator('h1').waitFor();", "export const ignoreHTTPSErrors = true;"))
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "key.pem", "-out", "cert.pem",
                        "-days", "1", "-subj", "/CN=localhost"], cwd=project.root, capture_output=True, check=True)
        (project.root / "tls.mjs").write_text(
            "import https from 'node:https';\nimport fs from 'node:fs';\n"
            "https.createServer({ key: fs.readFileSync('key.pem'), cert: fs.readFileSync('cert.pem') }, (request, response) => {\n"
            "  response.setHeader('content-type', 'text/html');\n"
            "  response.end('<!doctype html><title>x</title><h1>x</h1>');\n"
            "}).listen(Number(process.env.PORT), '127.0.0.1');\n")
        url = f"https://127.0.0.1:{project.port}/"
        result = subprocess.run([NODE, "demo/record.mjs"], cwd=project.root, capture_output=True, text=True, timeout=TAKE_TIMEOUT_S,
                                env=clean_env(PORT=str(project.port), APP_CMD="node tls.mjs", APP_URL=url))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_browser_goes_through_the_proxy_variables_with_their_password(self):
        project = self.project(one_beat("await page.locator('h1').waitFor();"))
        (project.root / "proxy.mjs").write_text(
            "import http from 'node:http';\n"
            "const wanted = 'Basic ' + Buffer.from('user:pa@ss').toString('base64');\n"
            "http.createServer((request, response) => {\n"
            "  if (request.headers['proxy-authorization'] !== wanted) {\n"
            "    response.writeHead(407, { 'proxy-authenticate': 'Basic realm=\"x\"' });\n"
            "    return response.end();\n"
            "  }\n"
            "  response.setHeader('content-type', 'text/html');\n"
            "  response.end('<!doctype html><title>x</title><h1>through the proxy</h1>');\n"
            "}).listen(Number(process.env.PORT), '127.0.0.1');\n")
        running = subprocess.Popen([NODE, "proxy.mjs"], cwd=project.root, env=project.env(), stdout=subprocess.DEVNULL)
        self.addCleanup(running.wait)
        self.addCleanup(running.kill)
        self.wait_for_port(project, running)
        proxy = f"http://user:pa%40ss@127.0.0.1:{project.port}"
        env = clean_env(APP_CMD="", APP_URL="http://demo.invalid/", SIZE="640x360", HTTP_PROXY=proxy, HTTPS_PROXY=proxy,
                        http_proxy=proxy, https_proxy=proxy)
        result = subprocess.run([NODE, "demo/record.mjs"], cwd=project.root, env=env, capture_output=True, text=True,
                                timeout=TAKE_TIMEOUT_S)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("pa@ss", result.stdout + result.stderr)
        self.assertNotIn("pa%40ss", result.stdout + result.stderr)

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

    def test_a_retake_keeps_the_last_set_beside_it(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        self.assertEqual(project.take().returncode, 0)
        first = {name: (project.out / name).read_bytes() for name in ("demo.mp4", "captions.srt", "steps.json")}
        self.assertFalse((project.out / "demo.prev.mp4").exists())
        self.assertEqual(project.take().returncode, 0)
        for name, kept in (("demo.prev.mp4", "demo.mp4"), ("captions.prev.srt", "captions.srt"), ("steps.prev.json", "steps.json")):
            self.assertEqual((project.out / name).read_bytes(), first[kept], name)

    def test_a_page_slow_to_answer_starts_a_take_and_is_asked_once(self):
        project = self.project(one_beat(
            "const hits = await page.evaluate(async () => (await fetch('/hits')).json());"
            " if (hits > 2) throw new Error('the page was asked ' + hits + ' times');"))
        result = project.take(SLOW_ROOT_MS="3000", SIZE="640x360")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_app_already_running_elsewhere_is_recorded_and_left_running(self):
        project = self.project(one_beat("await page.waitForTimeout(100);"))
        running = subprocess.Popen([NODE, "server.mjs"], cwd=project.root, env=project.env(), stdout=subprocess.DEVNULL)
        self.addCleanup(running.wait)
        self.addCleanup(running.kill)
        self.wait_for_port(project, running)
        result = project.take(APP_CMD="", SIZE="640x360")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((project.out / "demo.mp4").exists())
        self.assertTrue(port_open(project.port), "a take stopped an app it didn't start")

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

    def test_a_voice_goes_on_a_real_take_and_a_retake_moves_it_aside(self):
        project = self.project()
        first = project.take()
        self.assertEqual(first.returncode, 0, first.stderr)
        _, duration = ffprobe(project.out / "demo.mp4")
        voice_dir = project.root / "demo" / "voice"
        voice_dir.mkdir()
        tone(voice_dir / "all.wav", 3, lead=1)
        voiced = subprocess.run([NODE, "demo/voice.mjs"], cwd=project.root, env=project.env(),
                                capture_output=True, text=True, timeout=TAKE_TIMEOUT_S)
        self.assertEqual(voiced.returncode, 0, voiced.stderr)
        self.assertEqual(stream_codecs(project.out / "demo-voice.mp4"), ["h264", "aac"])
        self.assertLess(abs(ffprobe(project.out / "demo-voice.mp4")[1] - duration), 0.1)

        second = project.take()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse((project.out / "demo-voice.mp4").exists(), "a voice cut to the last take outlived it")
        self.assertTrue((project.out / "demo-voice.prev.mp4").exists())
        self.assertIn("voice.mjs", second.stderr)

    def wait_for_port(self, project, take):
        for _ in range(200):
            if port_open(project.port):
                return
            time.sleep(0.05)
        self.fail(f"the app never opened its port, take exit {take.poll()}")


HEARD_DB = -30  # A tone at -6 dB reads well above this in its span, and silence far below it.


@unittest.skipUnless(NODE, "node is not installed")
class Voice(unittest.TestCase):
    """voice.mjs on a stand-in take, so these need neither Playwright nor a microphone."""

    TAKE_S = 8
    BEATS = ((0.2, 3.0), (3.0, 5.5), (5.5, 8.0))

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.demo = self.root / "demo"
        self.out = self.demo / "out"
        self.voice_dir = self.demo / "voice"
        self.out.mkdir(parents=True)
        self.voice_dir.mkdir()
        shutil.copy(TEMPLATE / "voice.mjs", self.demo / "voice.mjs")
        self.result = self.out / "demo-voice.mp4"
        self.make_take(self.out / "demo.mp4")
        trim = 0.4  # steps.json counts from before the trim, as record.mjs writes it.
        steps = [{"caption": f"Beat {i}", "start": a + trim, "end": b + trim} for i, (a, b) in enumerate(self.BEATS, 1)]
        (self.out / "steps.json").write_text(json.dumps({"lead": 0.6, "trim": trim, "steps": steps, "warnings": []}))

    def make_take(self, path, size="320x240", rate=30):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi",
                        "-i", f"testsrc=size={size}:rate={rate}:duration={self.TAKE_S}",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path)], check=True)

    def run_voice(self, *args, **env):
        return subprocess.run([NODE, "demo/voice.mjs", *args], cwd=self.root, env=clean_env(**env),
                              capture_output=True, text=True, timeout=60)

    def built(self):
        result = self.run_voice()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stream_codecs(self.result), ["h264", "aac"])
        self.assertLess(abs(ffprobe(self.result)[1] - self.TAKE_S), 0.1, "the voiced video must keep the take's length")
        self.assertEqual(video_hash(self.result), video_hash(self.out / "demo.mp4"), "the picture is copied, never re-encoded")
        return result

    def assert_refused(self, expected):
        before = self.result.read_bytes() if self.result.exists() else None
        result = self.run_voice()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(expected, result.stderr)
        self.assertEqual(self.result.read_bytes() if self.result.exists() else None, before)
        self.assertEqual([p.name for p in self.out.iterdir() if p.name.startswith(".")], [])

    def test_a_short_read_keeps_the_whole_video(self):
        tone(self.voice_dir / "all.wav", 2)
        self.built()
        self.assertGreater(level(self.result, 0.5, 2.0), HEARD_DB)
        self.assertLess(level(self.result, 3.0, 7.5), -60)

    def test_a_reads_leading_silence_goes_so_the_first_word_lands_on_the_first_caption(self):
        tone(self.voice_dir / "all.wav", 3, lead=1.5)
        self.built()
        self.assertGreater(level(self.result, 0.3, 3.0), HEARD_DB)
        self.assertLess(level(self.result, 3.6, 7.5), -60)

    def test_a_click_before_the_read_does_not_stop_the_trim(self):
        sequence(self.voice_dir / "all.wav", [(None, 0.3), (2000, 0.04, 2), (None, 1.2), (440, 3)])
        self.built()
        self.assertGreater(level(self.result, 0.35, 0.6, 440), HEARD_DB, "the read starts late, kept behind the click")
        self.assertLess(level(self.result, 0.0, 3.0, 2000), -50, "the click was kept")

    def test_a_noisy_room_still_trims(self):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "aevalsrc=0.03*random(0)+0.3*sin(2*PI*440*t)*between(t\\,2\\,4):d=6",
                        str(self.voice_dir / "all.wav")], check=True)
        self.built()
        self.assertGreater(level(self.result, 0.4, 0.6, 440), HEARD_DB)

    def test_a_faint_sound_just_before_speech_is_kept(self):
        # About -64 dB: under even the soft bar, so only the margin keeps it.
        sequence(self.voice_dir / "all.wav", [(None, 1.0), (440, 0.1, 0.005), (3000, 2)])
        self.built()
        self.assertGreater(level(self.result, 0.2, 0.3, 440), -85, "the margin before the speech was cut")  # -70 kept, -91 cut
        self.assertGreater(level(self.result, 0.5, 2.0, 3000), HEARD_DB)

    def test_a_recorders_opening_zeros_are_not_the_room(self):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "aevalsrc=0.01*(random(0)-0.5)*gt(t\\,0.6)+0.5*sin(2*PI*440*t)*between(t\\,3\\,5):s=48000:d=5.5",
                        str(self.voice_dir / "all.wav")], check=True)
        self.built()
        self.assertGreater(level(self.result, 0.4, 0.6, 440), HEARD_DB, "the room's noise before the read was kept")

    def test_a_loud_room_still_trims_and_says_it_is_rough(self):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "aevalsrc=0.07*random(0)+0.3*sin(2*PI*440*t)*between(t\\,2\\,4):s=48000:d=6",
                        str(self.voice_dir / "all.wav")], check=True)
        self.assertIn("over the room's noise", self.built().stderr)
        self.assertGreater(level(self.result, 0.4, 0.6, 440), HEARD_DB)

    def test_a_short_first_word_is_kept(self):
        sequence(self.voice_dir / "all.wav", [(None, 1.0), (440, 0.15), (None, 0.4), (3000, 2)])
        self.built()
        self.assertGreater(level(self.result, 0.3, 0.45, 440), HEARD_DB, "the first word was dropped")

    def test_a_click_after_the_last_word_is_dropped(self):
        tone(self.voice_dir / "all.wav", 7)
        sequence(self.voice_dir / "2.wav", [(None, 0.5), (1000, 1.5), (None, 1.5), (2000, 0.05, 2)])
        self.built()
        self.assertLess(level(self.result, 3.0, 5.5, 2000), -50)

    def test_a_long_soft_opening_is_kept(self):
        # About -48 dB for 0.3 s: under the bar for speech, joined to it, so the speech grows over it.
        sequence(self.voice_dir / "all.wav", [(None, 1.0), (440, 0.3, 0.032), (3000, 2)], noise=0.001)  # A room at about -72 dB.
        self.built()
        self.assertGreater(level(self.result, 0.3, 0.45, 440), -58, "the start of a soft opening was cut")  # -52 kept, -66 cut

    def test_a_file_whose_clock_jumps(self):
        # Speech is found by counting samples, so the cut must count them too, not trust the file's clock.
        even = self.root / "even.wav"
        sequence(even, [(None, 1.0), (440, 1.0), (880, 2)])
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(even), "-af",
                        "asetpts=PTS+if(gte(N\\,48000)\\,72000\\,0)", "-c:a", "libopus",
                        str(self.voice_dir / "all.mka")], check=True)
        self.built()
        self.assertGreater(level(self.result, 2.5, 3.0, 880), HEARD_DB, "the end of the read was cut")  # -9 kept, -91 cut

    def test_a_linked_voice_file_counts(self):
        tone(self.voice_dir / "all.wav", 7, frequency=440)
        tone(self.root / "retake.wav", 2, frequency=1000)
        (self.voice_dir / "2.wav").symlink_to(self.root / "retake.wav")
        self.built()
        self.assertGreater(level(self.result, 3.2, 4.9, 1000), HEARD_DB)

    def test_a_link_to_nothing_is_refused(self):
        tone(self.voice_dir / "all.wav", 2)
        (self.voice_dir / "2.wav").symlink_to(self.root / "gone.wav")
        self.assert_refused("2.wav")

    def test_windows_download_sidecars_are_skipped(self):
        tone(self.voice_dir / "all.wav", 2)
        (self.voice_dir / "all.wav:Zone.Identifier").write_text("[ZoneTransfer]\nZoneId=3\n")
        self.built()

    def test_silence_after_the_last_word_is_dropped(self):
        tone(self.voice_dir / "all.wav", 7, frequency=440)
        sequence(self.voice_dir / "2.wav", [(None, 0.5), (1000, 1.5), (None, 3.0)])  # Longer than beat 2 only with its tail.
        self.built()
        self.assertGreater(level(self.result, 3.2, 4.4, 1000), HEARD_DB)

    def test_a_piped_recording_that_does_not_know_its_length(self):
        piped = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                                "aevalsrc=0.5*sin(2*PI*440*t)*(lt(t\\,1)+gt(t\\,2)):d=3", "-c:a", "libopus", "-f", "webm", "-"],
                               capture_output=True, check=True)
        (self.voice_dir / "all.webm").write_bytes(piped.stdout)
        self.built()
        self.assertGreater(level(self.result, 2.3, 3.0), HEARD_DB, "the last sentence was lost")

    def test_clips_land_on_their_beats(self):
        tone(self.voice_dir / "1.wav", 1)
        tone(self.voice_dir / "3.wav", 1, lead=0.7)
        self.built()
        self.assertGreater(level(self.result, 0.3, 1.1), HEARD_DB)
        self.assertLess(level(self.result, 1.5, 5.3), -60)
        self.assertGreater(level(self.result, 5.6, 6.0), HEARD_DB, "a clip's leading silence was kept")

    def test_a_clip_may_run_on_into_a_beat_with_no_voice(self):
        tone(self.voice_dir / "1.wav", 4)
        self.built()
        self.assertGreater(level(self.result, 3.2, 4.0), HEARD_DB)

    def test_a_retake_replaces_that_part_of_the_read_only(self):
        tone(self.voice_dir / "all.wav", 7, frequency=440)
        tone(self.voice_dir / "2.wav", 2, frequency=1000)
        self.built()
        self.assertGreater(level(self.result, 0.5, 2.8, 440), HEARD_DB)
        self.assertLess(level(self.result, 3.2, 5.2, 440), -50, "the read still plays under the retake")
        self.assertGreater(level(self.result, 3.2, 4.9, 1000), HEARD_DB)
        self.assertGreater(level(self.result, 5.7, 7.0, 440), HEARD_DB)

    def test_the_read_resumes_at_its_own_place_after_a_retake(self):
        # The read's second tone starts in the file just where beat 3 starts in the take, after its 1 s lead.
        sequence(self.voice_dir / "all.wav", [(None, 1.0), (440, 5.3), (880, 1.7)])
        tone(self.voice_dir / "2.wav", 2, frequency=1000)
        self.built()
        self.assertLess(level(self.result, 5.8, 6.3, 440), -50, "the read came back at the wrong place in the file")
        self.assertGreater(level(self.result, 5.8, 7.0, 880), HEARD_DB)

    def test_a_clip_after_the_read_has_ended_may_run_on(self):
        tone(self.voice_dir / "all.wav", 2)
        tone(self.voice_dir / "2.wav", 3)
        self.built()
        self.assertGreater(level(self.result, 5.6, 5.9), HEARD_DB)

    def test_two_retakes_side_by_side(self):
        tone(self.voice_dir / "all.wav", 7, frequency=440)
        tone(self.voice_dir / "1.wav", 2, frequency=1000)
        tone(self.voice_dir / "2.wav", 2, frequency=1000)
        self.built()
        self.assertLess(level(self.result, 0.4, 5.3, 440), -50)
        self.assertGreater(level(self.result, 5.7, 7.0, 440), HEARD_DB)

    def test_any_recorders_file_works(self):
        for name, rate in (("all.wav", 44100), ("all.wav", 48000), ("all.m4a", 44100), ("all.m4a", 48000), ("all.mp3", 44100)):
            with self.subTest(name=name, rate=rate):
                for old in self.voice_dir.iterdir():
                    old.unlink()
                tone(self.voice_dir / name, 2, rate=rate)
                self.built()
                self.assertGreater(level(self.result, 0.5, 2.0), HEARD_DB)

    def test_a_file_only_named_like_a_hidden_one_is_skipped(self):
        tone(self.voice_dir / "all.wav", 2)
        (self.voice_dir / ".DS_Store").write_text("finder")
        self.built()

    def test_a_good_build_keeps_the_last_one_beside_it(self):
        tone(self.voice_dir / "all.wav", 2)
        self.built()
        first = self.result.read_bytes()
        tone(self.voice_dir / "all.wav", 3)
        self.built()
        self.assertEqual((self.out / "demo-voice.prev.mp4").read_bytes(), first)

    def test_a_clipped_file_warns_and_still_builds(self):
        tone(self.voice_dir / "all.wav", 2, gain=8)
        self.assertIn("clipped", self.built().stderr)

    def test_no_voice_files(self):
        self.assert_refused("cues")

    def test_no_take_yet(self):
        (self.out / "demo.mp4").unlink()
        tone(self.voice_dir / "all.wav", 2)
        self.assert_refused("record.mjs")

    def test_a_file_with_the_wrong_name(self):
        tone(self.voice_dir / "intro.wav", 2)
        self.assert_refused("intro.wav")

    def test_a_beat_the_take_does_not_have(self):
        tone(self.voice_dir / "4.wav", 1)
        self.assert_refused("4.wav")

    def test_beat_zero_is_refused(self):
        tone(self.voice_dir / "0.wav", 1)
        self.assert_refused("0.wav")

    def test_two_files_for_one_beat(self):
        tone(self.voice_dir / "2.wav", 1)
        tone(self.voice_dir / "2.m4a", 1)
        self.assert_refused("2.m4a")

    def test_a_file_with_no_audio_in_it(self):
        (self.voice_dir / "all.wav").write_text("not audio")
        self.assert_refused("all.wav")

    def test_a_recording_with_no_voice_in_it(self):
        tone(self.voice_dir / "all.wav", 2, gain=0.15)  # About -35 dB: what a room gave the real microphone.
        self.assert_refused("too quiet")

    def test_a_read_longer_than_the_take(self):
        tone(self.voice_dir / "all.wav", 9)
        self.assert_refused("all.wav")

    def test_a_clip_past_the_end_of_the_take(self):
        tone(self.voice_dir / "3.wav", 3.5)
        self.assert_refused("3.wav")

    def test_a_clip_that_runs_into_the_next_clip(self):
        tone(self.voice_dir / "1.wav", 3.5)
        tone(self.voice_dir / "2.wav", 1)
        self.assert_refused("1.wav")

    def test_a_retake_longer_than_its_beat(self):
        tone(self.voice_dir / "all.wav", 7)
        tone(self.voice_dir / "2.wav", 3)
        self.assert_refused("2.wav")

    def test_a_failure_keeps_the_last_good_build(self):
        tone(self.voice_dir / "all.wav", 2)
        self.built()
        tone(self.voice_dir / "4.wav", 1)
        self.assert_refused("4.wav")

    def test_an_other_output_dir_and_voice_dir(self):
        other = self.demo / "out-clip"
        shutil.copytree(self.out, other)
        voices = self.root / "takes"
        voices.mkdir()
        tone(voices / "all.wav", 2)
        result = self.run_voice(OUT=str(other), VOICE=str(voices))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((other / "demo-voice.mp4").exists())
        self.assertFalse(self.result.exists())

    def test_a_signal_during_the_build_publishes_nothing(self):
        tone(self.voice_dir / "all.wav", 2)
        self.built()
        before = self.result.read_bytes()
        tone(self.voice_dir / "all.wav", 3)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        shim = bin_dir / "ffmpeg"
        shim.write_text(f"""#!/bin/sh
{shutil.which("ffmpeg")} "$@"
status=$?
case "$*" in *.demo-voice.*) kill -TERM "$PPID" ;; esac
exit $status
""")
        shim.chmod(0o755)
        result = self.run_voice(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertEqual(self.result.read_bytes(), before)
        self.assertEqual([p.name for p in self.out.iterdir() if p.name.startswith(".")], [])

    def test_a_build_that_came_out_silent_is_refused(self):
        tone(self.voice_dir / "all.wav", 2)
        self.built()
        before = self.result.read_bytes()
        tone(self.voice_dir / "all.wav", 3)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        shim = bin_dir / "ffmpeg"
        real = shutil.which("ffmpeg")
        # A stand-in that keeps the streams right and empties the sound, as bad timestamps once did.
        shim.write_text(f"""#!/bin/sh
{real} "$@" || exit $?
for last; do :; done
case "$last" in
  *.demo-voice.*) {real} -nostdin -y -v error -i "$last" -f lavfi -i anullsrc=r=48000:cl=mono -map 0:v -map 1:a \\
    -c:v copy -c:a aac -t {self.TAKE_S} "$last.mp4" && mv "$last.mp4" "$last" ;;
esac
""")
        shim.chmod(0o755)
        result = self.run_voice(PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("silent", result.stderr)
        self.assertEqual(self.result.read_bytes(), before)

    def test_a_clip_takes_voice_dir_is_its_own(self):
        other = self.demo / "out-clip"
        shutil.copytree(self.out, other)
        tone(self.voice_dir / "1.wav", 1)
        tone(self.root / "line.wav", 1)
        added = self.run_voice("add", "1", str(self.root / "line.wav"), OUT=str(other))
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertTrue((self.demo / "voice-clip" / "1.wav").exists())
        self.assertEqual(sorted(p.name for p in self.voice_dir.iterdir()), ["1.wav"], "the full take's voice was touched")
        (self.demo / "voice-clip" / "1.wav").unlink()
        refused = self.run_voice(OUT=str(other))
        self.assertEqual(refused.returncode, 1)
        self.assertIn("voice-clip", refused.stderr)

    def test_an_out_with_another_name_needs_voice_named(self):
        for name in ("takes", "output"):
            with self.subTest(name=name):
                other = self.demo / name
                shutil.copytree(self.out, other)
                tone(self.root / "line.wav", 1)
                for args in ((), ("add", "1", str(self.root / "line.wav"))):
                    result = self.run_voice(*args, OUT=str(other))
                    self.assertEqual(result.returncode, 1, args)
                    self.assertIn("set VOICE", result.stderr)

    def recording_line(self, part):
        result = self.run_voice("cues")
        self.assertEqual(result.returncode, 0, result.stderr)
        label = "whole read" if part == "all" else f"beat {part}"
        return next(l for l in result.stdout.splitlines() if l.strip().startswith(label + ":")).split(": ", 1)[1]

    def run_line(self, line):
        """Runs a printed recording line as the speaker would, and returns the file it says it made.

        The line's temp dir moves from /tmp, which the sandbox can't write, into this test's own dir, and
        a stand-in replaces the microphone. Nothing here deletes: the test dir goes with the test.
        """
        self.assertIn("mktemp -d /tmp/voice.XXXXXX", line)
        line = line.replace("/tmp/voice.", f"{self.root}/voice.")
        bin_dir = self.root / "bin"
        bin_dir.mkdir(exist_ok=True)
        shim = bin_dir / "ffmpeg"
        shim.write_text(f"""#!/bin/sh
for last; do :; done
exec {shutil.which("ffmpeg")} -nostdin -v error -f lavfi -i sine=frequency=440:duration=1 -ac 1 "$last"
""")
        shim.chmod(0o755)
        result = subprocess.run(["sh", "-c", line], capture_output=True, text=True, timeout=60,
                                env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        self.assertEqual(result.returncode, 0, result.stderr)
        made = Path(result.stdout.strip())
        self.assertTrue(result.stdout.strip(), "the line printed no path")
        self.assertEqual(made.parent.parent, self.root, f"the line wrote outside its own new dir: {made}")
        self.assertTrue(made.parent.name.startswith("voice."))
        return made

    def test_a_recording_line_writes_only_a_new_private_file(self):
        target = self.root / "precious"
        target.write_text("keep")
        (self.voice_dir / "2.wav").symlink_to(target)  # Planted where an unsandboxed write could follow it.
        made = self.run_line(self.recording_line("2"))
        self.assertEqual(target.read_text(), "keep")
        self.assertEqual(made.name, "2.wav")
        self.assertEqual(stream_codecs(made), ["pcm_s16le"])

    def test_a_recording_goes_in_with_add(self):
        made = self.run_line(self.recording_line("all"))
        added = self.run_voice("add", "all", str(made))
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertEqual((self.voice_dir / "all.wav").read_bytes(), made.read_bytes())

    def test_add_keeps_the_parts_last_file_out_of_the_build(self):
        tone(self.voice_dir / "2.m4a", 1, frequency=440)
        tone(self.root / "retake.wav", 1, frequency=1000)
        added = self.run_voice("add", "2", str(self.root / "retake.wav"))
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertEqual(sorted(p.name for p in self.voice_dir.iterdir()), [".2.m4a.prev", "2.wav"])
        self.built()
        self.assertGreater(level(self.result, 3.1, 3.9, 1000), HEARD_DB)

    def test_add_refuses_a_silent_file_and_a_part_the_take_lacks(self):
        tone(self.root / "quiet.wav", 2, gain=0.15)
        tone(self.root / "fine.wav", 2)
        for args, expected in ((("all", str(self.root / "quiet.wav")), "too quiet"),
                               (("4", str(self.root / "fine.wav")), "1 to 3"),
                               (("intro", str(self.root / "fine.wav")), "1 to 3"),
                               (("all",), "needs a part and a file")):
            with self.subTest(args=args):
                result = self.run_voice("add", *args)
                self.assertEqual(result.returncode, 1)
                self.assertIn(expected, result.stderr)
        self.assertEqual(list(self.voice_dir.iterdir()), [])

    def test_a_long_line_says_to_use_your_own_terminal(self):
        steps = json.loads((self.out / "steps.json").read_text())
        steps["steps"][-1]["end"] = 200
        (self.out / "steps.json").write_text(json.dumps(steps))
        self.assertIn("your own terminal", self.run_voice("cues").stdout)

    def test_a_recording_that_stops_mid_speech_warns(self):
        tone(self.voice_dir / "all.wav", 2)
        self.assertIn("still going", self.built().stderr)
        sequence(self.voice_dir / "all.wav", [(440, 2), (None, 0.5)])
        self.assertNotIn("still going", self.built().stderr)

    def test_a_clip_takes_steps_start_at_its_first_beat(self):
        # A BEATS=2-3 take trims to its first beat, so that beat starts at 0.
        steps = [{"caption": "Two", "start": 4.0, "end": 6.5}, {"caption": "Three", "start": 6.5, "end": 9.0}]
        (self.out / "steps.json").write_text(json.dumps({"lead": 0.6, "trim": 4.0, "steps": steps, "warnings": []}))
        tone(self.voice_dir / "2.wav", 1, lead=0.5)
        self.built()
        self.assertGreater(level(self.result, 2.55, 3.3), HEARD_DB)
        self.assertLess(level(self.result, 0.0, 2.4), -60)

    def test_cues_list_each_beat_and_a_line_to_record_it(self):
        result = self.run_voice("cues")
        self.assertEqual(result.returncode, 0, result.stderr)
        for caption in ("Beat 1", "Beat 2", "Beat 3"):
            self.assertIn(caption, result.stdout)
        self.assertIn('"$d/all.wav"', result.stdout)
        self.assertIn('"$d/2.wav"', result.stdout)
        self.assertIn("-nostdin", result.stdout)
        self.assertRegex(result.stdout, r"-t \d+")
        self.assertNotIn("demo/voice", result.stdout.split("Then:")[0], "a recording line must not write into demo/")

    def test_check_passes_an_export_in_the_takes_format(self):
        tone(self.voice_dir / "all.wav", 2)
        self.built()
        result = self.run_voice("check", str(self.result))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_allows_a_hand_edit_to_change_the_length_and_says_so(self):
        cut = self.root / "cut.mp4"
        tone(self.voice_dir / "all.wav", 2)
        self.built()
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(self.result), "-t", "5", "-c", "copy", str(cut)], check=True)
        result = self.run_voice("check", str(cut))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("shorter", result.stdout)

    def test_check_fails_the_wrong_size_or_rate_or_no_audio(self):
        wrong_size = self.root / "size.mp4"
        self.make_take(wrong_size, size="160x120")
        tone(self.root / "voice.wav", 2)
        with_audio = self.root / "size-audio.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(wrong_size), "-i", str(self.root / "voice.wav"),
                        "-c:v", "copy", "-c:a", "aac", str(with_audio)], check=True)
        result = self.run_voice("check", str(with_audio))
        self.assertEqual(result.returncode, 1)
        self.assertIn("160x120", result.stderr)

        wrong_rate = self.root / "rate.mp4"
        self.make_take(wrong_rate, rate=24)
        self.assertIn("24", self.run_voice("check", str(wrong_rate)).stderr)

        silent = self.run_voice("check", str(self.out / "demo.mp4"))
        self.assertEqual(silent.returncode, 1)
        self.assertIn("no audio", silent.stderr)

    def test_check_needs_a_file_it_can_read(self):
        self.assertEqual(self.run_voice("check", "nothing.mp4").returncode, 1)
        self.assertEqual(self.run_voice("check").returncode, 1)

    def test_an_unknown_command_is_refused(self):
        self.assertEqual(self.run_voice("mix").returncode, 1)


if __name__ == "__main__":
    unittest.main()
