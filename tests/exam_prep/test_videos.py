"""skills/exam-prep/scripts/videos.py, which builds the watch list, practice/videos.html, from
practice/videos.json on the notes chassis.

The sample is tests/exam_prep/fixtures/videos/ (two synthetic topics, made-up titles and
11-character fake ids; its notes ids are the sample notes hub's, fixtures/site/). It builds: the
chassis filled (no placeholder left, the Review toggle swapped for By idea / By lecture), one
accent rule per topic, each pick's link with &t=<start>s, the kind chips, flags, differs lines and
"Matches your notes" for an empty list, the notes row's concise box, the by-lecture view in
timestamp order across topics with its gaps marked "Skipped", and the footer's counts. With the
sample hub's notes page built at _build/notes.html, its ids are checked and its headings name the
links. Broken one way at a time, the sample fails with exit 1, writes nothing, and names the file
and field of each problem; several problems are all listed. With EXAM_PREP_PLAYWRIGHT set (and
MathJax's and the fonts' hosts allowed), verify_page.mjs and verify_videos.mjs pass on the page."""
import contextlib
import copy
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL = os.path.join(REPO, "skills", "exam-prep")
SCRIPTS = os.path.join(SKILL, "scripts")
FIXTURE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "videos")
SITE = os.path.join(REPO, "tests", "exam_prep", "fixtures", "site")
DATA = os.path.join("practice", "videos.json")


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


videos = load("videos")
assemble = load("assemble")


def sample():
    with open(os.path.join(FIXTURE, DATA), encoding="utf-8") as f:
        return json.load(f)


class Hub:
    """A temporary hub holding the sample (or edited) data; run() builds it."""

    def __init__(self, data=None, notes=False):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "practice"))
        if data is None:
            shutil.copy(os.path.join(FIXTURE, DATA), os.path.join(self.root, DATA))
        else:
            with open(os.path.join(self.root, DATA), "w", encoding="utf-8") as f:
                f.write(data if isinstance(data, str) else json.dumps(data))
        if notes:
            site = os.path.join(self.root, "site")
            shutil.copytree(SITE, site, symlinks=False)
            with contextlib.redirect_stdout(io.StringIO()):
                assert assemble.main(["--root", site]) == 0
            os.makedirs(os.path.join(self.root, "_build"))
            shutil.copy(os.path.join(site, "_build", "notes.html"), os.path.join(self.root, "_build", "notes.html"))

    def run(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = videos.main(["--root", self.root])
        return code, out.getvalue(), err.getvalue()

    @property
    def page_path(self):
        return os.path.join(self.root, "practice", "videos.html")

    def page(self):
        with open(self.page_path, encoding="utf-8") as f:
            return f.read()

    def close(self):
        self.tmp.cleanup()


def pick(data, t, i, p):
    return data["topics"][t]["ideas"][i]["picks"][p]


class Builds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hub = Hub()
        cls.code, cls.out, cls.err = cls.hub.run()
        cls.html = cls.hub.page() if cls.code == 0 else ""

    @classmethod
    def tearDownClass(cls):
        cls.hub.close()

    def test_it_builds(self):
        self.assertEqual(self.code, 0, self.err)
        self.assertIn("6 picks in 2 topics", self.out)
        self.assertIn("checked for form only", self.out)

    def test_the_chassis_filled(self):
        self.assertNotRegex(self.html, r"\{\{|<!-- (SECTIONS|EXAM-DAY MAP|FIGURE SCRIPTS|REVIEW TOGGLE) -->")
        self.assertIn("<title>GRF101 Midterm 1 watch list</title>", self.html)
        self.assertNotIn('class="viewtog"', self.html)  # verify_page.mjs would run the Review view
        self.assertEqual(self.html.count('<div class="vidtog"'), 2)  # the rail and the top bar
        self.assertIn('id="themeBtn2"', self.html)
        self.assertIn(assemble.accents(2), self.html)
        self.assertEqual(self.html.count("Baseline as of"), 0)  # the templates' headers are dropped

    def test_links_with_start(self):
        self.assertIn('href="https://www.youtube.com/watch?v=fakeVid0001&amp;t=95s" target="_blank" rel="noopener"',
                      self.html)
        self.assertIn("watch?v=fakeVid0002&amp;t=3725s", self.html)
        self.assertIn('href="https://www.youtube.com/watch?v=yoursVid001"', self.html)  # no start: no t
        self.assertNotIn("<iframe", self.html)

    def test_timestamps(self):
        self.assertIn('<span class="vtime">1:35–9:20</span>', self.html)
        self.assertIn('<span class="vtime">1:02:05–1:10:00</span>', self.html)

    def test_chips_and_flags(self):
        for kind, chip in (("segment", "lecture"), ("yours", "your pick"), ("notes", "no good video")):
            self.assertRegex(self.html, rf'<li class="pick k-{kind}"[^\n]*>\n<div class="ptop">.*'
                                        rf'<span class="kchip k-{kind}">{chip}</span>')
        self.assertNotIn('class="kchip k-video"', self.html)
        for flag in ("quiet audio", "fast pace", "different symbols"):
            self.assertIn(f'<span class="flag">{flag}</span>', self.html)
        self.assertIn('<ul class="vlegend"', self.html)

    def test_differs_and_matches(self):
        self.assertIn('<div class="vline vdiff"><span class="vlab">Differs</span><div><ul><li>Writes the sum '
                      "with i from 0, where the notes start at 1.</li></ul></div></div>", self.html)
        self.assertEqual(self.html.count('<span class="vlab">Differs</span><div>Matches your notes</div>'), 2)

    def test_thread_tested_also(self):
        self.assertEqual(self.html.count('<span class="vlab">Thread</span>'), 6)
        self.assertEqual(self.html.count('<span class="vlab">Tested</span>'), 6)
        self.assertIn('<div class="vline valso"><span class="vlab">+ also</span><div><p>From a cut video on the '
                      "same trick:</p><ul><li>An odd count leaves one middle term.</li></ul>", self.html)

    def test_the_concise_box(self):
        self.assertIn('<div class="concise"><ul><li><strong>Rule</strong> Sum for either-or', self.html)
        self.assertIn("<li><strong>Trap</strong> Counting the overlap twice.</li>"
                      "<li><strong>Answer form</strong> The rule named, then the count.</li></ul></div>", self.html)

    def test_topics_ideas_and_notes_links(self):
        self.assertIn('<section class="note" id="t-counting">\n<h2><span class="n">§1</span> Counting</h2>\n'
                      '<div class="vintro"><ul><li>How many things', self.html)
        self.assertIn('<h3 id="i-graphs-2">Walks</h3>', self.html)
        self.assertIn('<a class="vnote" href="https://example.invalid/notes#sec-2-walks" target="_blank" '
                      'rel="noopener">sec-2-walks</a>', self.html)

    def test_by_lecture_in_timestamp_order(self):
        view = self.html.split('<div id="view-lecture">', 1)[1].split("</div>", 1)[0]
        self.assertIn("<h2>Lecture 3: counting and graphs</h2>", view)
        rows = re.findall(r'<li class="(lgap|lrow)"(?: data-start="(\d+)")?>(.*?)</li>', view)
        self.assertEqual([(k, s) for k, s, _ in rows],
                         [("lgap", ""), ("lrow", "300"), ("lgap", ""), ("lrow", "1500")])
        self.assertEqual(rows[0][2], "Skipped 0:00–5:00 (5:00)")
        self.assertEqual(rows[2][2], "Skipped 12:00–25:00 (13:00)")
        # graphs (the second topic) comes first: timestamp order across topics, each row linking back
        self.assertIn('<a class="lback" href="#i-graphs-1-1">Nodes and edges</a>', rows[1][2])
        self.assertIn('<a class="lback" href="#i-counting-1-2">Sums of a range</a>', rows[3][2])
        self.assertIn('id="i-graphs-1-1"', self.html)

    def test_footer(self):
        self.assertIn('<footer class="vfoot">6 picks (2 video, 2 lecture, 1 yours, 1 notes) across 4 ideas in '
                      "2 topics.</footer>", self.html)

    def test_text_is_escaped(self):
        data = sample()
        pick(data, 0, 0, 0)["title"] = "<b>bold</b> & co"
        hub = Hub(data)
        try:
            code, _, err = hub.run()
            self.assertEqual(code, 0, err)
            self.assertIn("&lt;b&gt;bold&lt;/b&gt; &amp; co", hub.page())
        finally:
            hub.close()

    def test_no_segments_no_toggle(self):
        data = sample()
        data["topics"][0]["ideas"][0]["picks"].pop(1)
        data["topics"][1]["ideas"][0]["picks"][0] = copy.deepcopy(pick(data, 0, 1, 0))
        hub = Hub(data)
        try:
            code, _, err = hub.run()
            self.assertEqual(code, 0, err)
            page = hub.page()
            self.assertNotIn("vidtog\"", page)
            self.assertNotIn('id="view-lecture"', page)
        finally:
            hub.close()


class NotesPage(unittest.TestCase):
    def test_ids_checked_and_named_against_the_built_notes(self):
        hub = Hub(notes=True)
        try:
            code, out, err = hub.run()
            self.assertEqual(code, 0, err)
            self.assertNotIn("form only", out)
            self.assertIn('rel="noopener">2.2 Walks</a>', hub.page())
        finally:
            hub.close()

    def test_an_id_the_notes_lack(self):
        data = sample()
        data["topics"][1]["ideas"][1]["notes"] = ["sec-2-walking"]
        hub = Hub(data, notes=True)
        try:
            code, _, err = hub.run()
            self.assertEqual(code, 1)
            self.assertIn('topics[1].ideas[1].notes[0]: "sec-2-walking" isn\'t an id in _build/notes.html', err)
        finally:
            hub.close()


class Refuses(unittest.TestCase):
    def fails(self, edit, *expected, problems=None):
        data = sample()
        edit(data)
        hub = Hub(data)
        try:
            code, _, err = hub.run()
            self.assertEqual(code, 1, err)
            self.assertFalse(os.path.exists(hub.page_path))
            name = os.path.join(hub.root, DATA)
            for e in expected:
                self.assertIn(f"{name}: {e}", err)
            if problems is not None:
                self.assertIn(f"{problems} problem{'' if problems == 1 else 's'}; practice/videos.html not written",
                              err)
            return err
        finally:
            hub.close()

    def test_unknown_kind(self):
        self.fails(lambda d: pick(d, 0, 0, 0).update(kind="clip"),
                   'topics[0].ideas[0].picks[0].kind: unknown kind "clip"', problems=1)

    def test_segment_without_start(self):
        self.fails(lambda d: pick(d, 0, 0, 1).pop("start"),
                   "topics[0].ideas[0].picks[1].start: a segment needs start", problems=1)

    def test_end_not_after_start(self):
        self.fails(lambda d: pick(d, 0, 0, 0).update(end=95),
                   "topics[0].ideas[0].picks[0].end: end 95 isn't after start 95", problems=1)
        self.fails(lambda d: pick(d, 0, 0, 0).update(end=40),
                   "topics[0].ideas[0].picks[0].end: end 40 isn't after start 95")

    def test_bad_video_id(self):
        for bad in ("short", "fakeVid0001x", "fake id 001"):
            self.fails(lambda d: pick(d, 1, 1, 0).update(video_id=bad),
                       "topics[1].ideas[1].picks[0].video_id: ", problems=1)

    def test_bad_notes_id(self):
        for bad in ("Sec-1-sums", "sec-1_sums", "notes-1", "ex-1"):
            self.fails(lambda d: d["topics"][0]["ideas"][0].update(notes=[bad]),
                       f'topics[0].ideas[0].notes[0]: "{bad}" isn\'t a notes id', problems=1)

    def test_missing_thread_or_tested(self):
        self.fails(lambda d: pick(d, 0, 1, 0).pop("thread"), "topics[0].ideas[1].picks[0].thread: missing",
                   problems=1)
        self.fails(lambda d: pick(d, 1, 0, 0).pop("tested"), "topics[1].ideas[0].picks[0].tested: missing",
                   problems=1)

    def test_missing_differs(self):
        self.fails(lambda d: pick(d, 0, 0, 1).pop("differs"),
                   "topics[0].ideas[0].picks[1].differs: missing (write [] for none)", problems=1)

    def test_explain_label_outside_the_six(self):
        self.fails(lambda d: pick(d, 0, 1, 0)["explain"].append({"label": "Hint", "text": "x"}),
                   "topics[0].ideas[1].picks[0].explain[3].label: 'Hint' isn't one of Rule, Why, Steps, "
                   "Example, Trap, Answer form", problems=1)

    def test_explain_out_of_order(self):
        self.fails(lambda d: pick(d, 0, 1, 0)["explain"].reverse(),
                   "topics[0].ideas[1].picks[0].explain[1].label: 'Trap' out of order",
                   "topics[0].ideas[1].picks[0].explain[2].label: 'Rule' out of order", problems=2)

    def test_explain_on_a_video(self):
        self.fails(lambda d: pick(d, 0, 0, 0).update(explain=[{"label": "Rule", "text": "x"}]),
                   "topics[0].ideas[0].picks[0].explain: only a notes row takes explain", problems=1)

    def test_duplicate_stretch_across_the_page(self):
        def edit(d):
            twin = copy.deepcopy(pick(d, 0, 0, 0))
            twin["end"] = 300
            d["topics"][1]["ideas"][1]["picks"].append(twin)
        self.fails(edit, "topics[1].ideas[1].picks[1]: the same stretch as topics[0].ideas[0].picks[0] "
                         "(fakeVid0001 from 1:35): fold it into that row's also", problems=1)

    def test_overlapping_ranges_in_one_idea(self):
        def edit(d):
            twin = copy.deepcopy(pick(d, 0, 0, 0))
            twin.update(start=500, end=900)
            d["topics"][0]["ideas"][0]["picks"].append(twin)
        self.fails(edit, "topics[0].ideas[0].picks[3]: overlaps topics[0].ideas[0].picks[0]", problems=1)

    def test_adjacent_ranges_in_one_idea(self):
        def edit(d):
            twin = copy.deepcopy(pick(d, 0, 0, 0))
            twin.update(start=565, end=900)  # 5 s after the first ends
            d["topics"][0]["ideas"][0]["picks"].append(twin)
        self.fails(edit, "topics[0].ideas[0].picks[3]: adjoins topics[0].ideas[0].picks[0]", problems=1)

    def test_far_apart_ranges_of_one_video_pass(self):
        data = sample()
        twin = copy.deepcopy(pick(data, 0, 0, 0))
        twin.update(start=900, end=1000)
        data["topics"][0]["ideas"][0]["picks"].append(twin)
        hub = Hub(data)
        try:
            code, _, err = hub.run()
            self.assertEqual(code, 0, err)
        finally:
            hub.close()

    def test_one_lecture_one_video(self):
        self.fails(lambda d: pick(d, 1, 0, 0).update(video_id="LECTURE4bbb"),
                   "topics[1].ideas[0].picks[0].video_id: lecture lec-3 is video LECTURE3aaa", problems=1)

    def test_a_lecture_not_named(self):
        self.fails(lambda d: pick(d, 1, 0, 0).update(lecture="lec-9"),
                   'topics[1].ideas[0].picks[0].lecture: "lec-9" isn\'t in lectures')

    def test_video_fields_on_a_notes_row(self):
        self.fails(lambda d: pick(d, 0, 1, 0).update(video_id="fakeVid0003"),
                   "topics[0].ideas[1].picks[0].video_id: a notes row has no video", problems=1)

    def test_shape(self):
        self.fails(lambda d: d.pop("notes_url"), "(top).notes_url: missing", problems=1)
        self.fails(lambda d: d.update(notes_url="http://example.invalid/notes"), "notes_url: want")
        self.fails(lambda d: d["topics"][0].update(section="8"), 'topics[0].section: "8" isn\'t')
        self.fails(lambda d: d["topics"][1].update(key="counting"), 'topics[1].key: "counting" is another')
        self.fails(lambda d: pick(d, 0, 0, 0).update(start=True), "topics[0].ideas[0].picks[0].start: want whole")
        self.fails(lambda d: pick(d, 0, 0, 0).update(colour="red"), "topics[0].ideas[0].picks[0].colour: unknown")
        self.fails(lambda d: d["topics"][0]["ideas"][0].update(picks=[]), "topics[0].ideas[0].picks: want a list")

    def test_every_problem_listed(self):
        def edit(d):
            pick(d, 0, 0, 0)["kind"] = "clip"
            pick(d, 1, 1, 0)["video_id"] = "short"
            pick(d, 1, 0, 0).pop("thread")
        self.fails(edit, "topics[0].ideas[0].picks[0].kind", "topics[1].ideas[1].picks[0].video_id",
                   "topics[1].ideas[0].picks[0].thread", problems=3)

    def test_not_json(self):
        hub = Hub('{"exam": "Midterm 1",\n  "topics": [}')
        try:
            code, _, err = hub.run()
            self.assertEqual(code, 1)
            self.assertIn("line 2 column", err)
            self.assertFalse(os.path.exists(hub.page_path))
        finally:
            hub.close()

    def test_no_data_is_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(videos.main(["--root", tmp]), 2)
            self.assertIn("no data at", err.getvalue())


@unittest.skipUnless(os.environ.get("EXAM_PREP_PLAYWRIGHT"),
                     "set EXAM_PREP_PLAYWRIGHT (and allow MathJax's and the fonts' hosts) to run the browser checks")
class Browser(unittest.TestCase):
    def test_the_sample_page_passes_the_browser_checks(self):
        hub = Hub()
        try:
            code, _, err = hub.run()
            self.assertEqual(code, 0, err)
            shots = os.path.join(hub.root, "shots")
            # The default spy targets: the chassis's foot room lets the last idea reach the line.
            r = subprocess.run(["node", os.path.join(SCRIPTS, "verify_page.mjs"), hub.page_path, shots],
                               capture_output=True, text=True, timeout=600)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("ALL CHECKS PASS", r.stdout)
            # the last idea, which the page's end used to stop short: 390 and 1280, light and dark
            self.assertEqual(r.stdout.count("spy ok #i-graphs-2"), 4, r.stdout)
            self.assertIn("theme chrome: track", r.stdout)
            r = subprocess.run(["node", os.path.join(SCRIPTS, "verify_videos.mjs"), hub.page_path, shots],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("ALL VIDEO CHECKS PASS", r.stdout)
            for width in (390, 1280):
                self.assertIn(f"ok {width}-light: By lecture shows the lecture view alone", r.stdout)
        finally:
            hub.close()


if __name__ == "__main__":
    unittest.main()
