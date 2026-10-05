"""skills/deck-production/scripts/geometry.py: the geometry gate (stdlib only).

Most cases call evaluate() on canned probe JSON, an outcome x rule matrix with
no browser. GeometryEndToEnd drives headless Chrome over the fixture deck and
skips, with the reason, when no browser is installed. The probe-side
principles (vector svg is not media, a ::before scrim is seen through its host,
the growth test) are exercised there, on the fixture's good and bad slides."""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "skills", "deck-production", "scripts", "geometry.py")
FIXTURE = os.path.join(REPO, "tests", "deck_production", "fixtures", "geodeck")

_spec = importlib.util.spec_from_file_location("geometry", SCRIPT)
geometry = importlib.util.module_from_spec(_spec)
sys.modules["geometry"] = geometry        # dataclasses resolve their module by name
_spec.loader.exec_module(geometry)
deckcfg = geometry.deckcfg

TRANSPARENT = "rgba(0, 0, 0, 0)"
NAVY = "rgba(11, 19, 32, 0.92)"
SHADOW = "rgb(0, 0, 0) 0px 2px 8px"


def box(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


class Probe:
    """Builds the JSON geometry_probe.js returns, one node at a time. Text is
    20 px regular unless a case says otherwise; line rects are 30 px tall
    (content area), so their em-box ink is the middle 20 px."""

    def __init__(self, margin=96):
        self.data = {"canvas": {"w": 1920, "h": 1080}, "scale": 1, "margin": margin,
                     "elements": [], "texts": [], "markers": [], "media": [], "clipping": []}

    def el(self, parent=None, token=None, tag="div", position="static", display="block",
           maxWidth="none", textShadow="none", fontSize=20, fontWeight=400,
           bg=TRANSPARENT, image="none", pseudo=(), rect=None):
        node = len(self.data["elements"])
        self.data["elements"].append({
            "parent": parent, "token": token or f".n{node}", "tag": tag, "position": position,
            "display": display, "maxWidth": maxWidth, "textShadow": textShadow,
            "fontSize": fontSize, "fontWeight": fontWeight,
            "paints": [[bg, image], *pseudo], "box": rect or box(0, 0, 0, 0)})
        return node

    def label(self, *lines, text=None, **root):
        """An absolutely positioned label holding one text item. Text styles
        (font, shadow) go in `text`: the probe reads them computed on the text."""
        node = self.el(self.el(position="absolute", **root), **(text or {}))
        return self.text(node, *lines)

    def text(self, node, *lines, exempt=(), grows=None, chars=40):
        self.data["texts"].append({"node": node, "lines": list(lines), "samples": [],
                                   "exempt": list(exempt), "grows": grows, "chars": chars,
                                   "text": "x"})
        return node

    def item(self, node):
        return next(t for t in self.data["texts"] if t["node"] == node)

    def over(self, node, *stack, points=5):
        """Paint stacks under a text item, topmost first: the text, then what
        lies below it down to (and past) the media."""
        self.item(node)["samples"] = [[node, *stack] for _ in range(points)]

    def marker(self, rect, parent=None):
        self.data["markers"].append({"node": self.el(parent), "box": rect})

    def media(self, rect=None, parent=None, tag="img", scrimmed=False):
        node = self.el(parent, tag=tag)
        self.data["media"].append({"node": node, "box": rect or box(800, 100, 800, 800),
                                   "scrimmed": scrimmed})
        return node

    def clip(self, node, rect, x=True, y=True):
        self.data["clipping"].append({"node": node, "box": rect, "x": x, "y": y})


def shipped_rules():
    return geometry.parse_rules(pathlib.Path(geometry.RULES_FILE).read_text(), "test")


def fired(probe, rules=None):
    return [v.rule for v in geometry.evaluate(probe.data, rules or shipped_rules(), "s1")]


def overlap_bad():
    p = Probe()
    p.label(box(200, 200, 300, 30))
    p.label(box(300, 210, 300, 30))
    return p


def overlap_good():
    p = Probe()
    p.label(box(200, 200, 300, 30))
    p.label(box(200, 260, 300, 30))
    return p


def marker_bad():
    p = Probe()
    p.label(box(200, 200, 300, 30))
    p.marker(box(250, 210, 14, 14))
    return p


def marker_good():
    p = Probe()
    p.label(box(200, 200, 300, 30))
    p.marker(box(600, 210, 14, 14))
    return p


def unbounded_bad():
    p = Probe()
    p.item(p.label(box(200, 200, 900, 30)))["grows"] = 600
    return p


def unbounded_good():
    p = Probe()
    p.item(p.label(box(200, 200, 400, 30)))["grows"] = 0
    return p


def media_case(**root):
    p = Probe()
    m = p.media()
    t = p.label(box(900, 300, 300, 30), **root)
    p.over(t, p.data["elements"][t]["parent"], m)
    return p


def safe_bad():
    p = Probe()
    p.text(p.el(), box(40, 200, 300, 30))
    return p


def safe_good():
    p = Probe()
    p.text(p.el(), box(96, 200, 300, 30))
    return p


def clearance_bad():
    p = Probe()
    p.label(box(200, 200, 300, 30))
    p.label(box(200, 222, 300, 30))           # ink 205-225 and 227-247: 2 px apart
    return p


def clip_bad():
    p = Probe()
    frame = p.el()
    p.text(p.el(frame), box(100, 100, 400, 30))
    p.clip(frame, box(100, 100, 250, 200))
    return p


def clip_good():
    p = Probe()
    frame = p.el()
    p.text(p.el(frame), box(100, 100, 200, 30))
    p.clip(frame, box(100, 100, 250, 200))
    return p


MATRIX = {
    "text-overlap": (overlap_bad, overlap_good),
    "covers-marker": (marker_bad, marker_good),
    "unbounded-abs-text": (unbounded_bad, unbounded_good),
    "text-on-media": (media_case, lambda: media_case(bg=NAVY)),
    "safe-area": (safe_bad, safe_good),
    "clearance": (clearance_bad, overlap_good),
    "clipped-text": (clip_bad, clip_good),
}


class RuleMatrix(unittest.TestCase):
    def test_the_matrix_covers_every_rule(self):
        self.assertEqual(set(MATRIX), set(geometry.RULES))
        self.assertEqual({r["id"] for r in shipped_rules()}, set(geometry.RULES))

    def test_every_rule_fires_on_its_bad_case(self):
        for rule, (bad, _good) in MATRIX.items():
            with self.subTest(rule=rule):
                self.assertIn(rule, fired(bad()))

    def test_every_good_case_is_clean(self):
        for rule, (_bad, good) in MATRIX.items():
            with self.subTest(rule=rule):
                self.assertEqual(fired(good()), [])

    def test_the_output_line_names_slide_rule_subject_and_size(self):
        (v,) = [v for v in geometry.evaluate(overlap_bad().data, shipped_rules(), "s05-map")
                if v.rule == "text-overlap"]
        self.assertRegex(v.line(), r"^ERROR s05-map text-overlap  \.n0 \.n1 x \.n2 \.n3  "
                                   r"\(200x10 px\)$")


class TextOverlapScope(unittest.TestCase):
    def test_nested_items_never_overlap(self):
        p = Probe()
        outer = p.text(p.el(position="absolute"), box(200, 200, 300, 30))
        p.text(p.el(outer), box(200, 200, 300, 30))
        self.assertNotIn("text-overlap", fired(p))

    def test_in_flow_siblings_under_one_positioned_box_never_overlap(self):
        # A flex column's name and caption: one layout pass places both.
        p = Probe()
        col = p.el(p.el(position="absolute"), display="flex")
        p.text(p.el(col), box(200, 200, 300, 30))
        p.text(p.el(col), box(200, 210, 300, 30))
        self.assertNotIn("text-overlap", fired(p))

    def test_two_svg_labels_are_placed_independently(self):
        p = Probe()
        svg = p.el(tag="svg", display="inline")
        p.text(p.el(svg, tag="text", display="inline"), box(200, 200, 100, 30))
        p.text(p.el(svg, tag="text", display="inline"), box(250, 200, 100, 30))
        self.assertIn("text-overlap", fired(p))

    def test_content_areas_touching_is_not_ink_on_ink(self):
        # Two stacked lines whose content areas overlap by 7 px; their em
        # boxes do not meet (23 px type, 33 px content area, 26 px apart).
        p = Probe()
        svg = p.el(tag="svg", display="inline")
        p.text(p.el(svg, tag="text", fontSize=23), box(124, 490, 52, 33))
        p.text(p.el(svg, tag="text", fontSize=23), box(124, 516, 52, 33))
        self.assertNotIn("text-overlap", fired(p))

    def test_a_sliver_under_min_depth_does_not_count(self):
        p = Probe()
        p.label(box(200, 200, 300, 20), text={"fontSize": 20})
        p.label(box(200, 218, 300, 20), text={"fontSize": 20})   # 300x2 px of em box
        self.assertNotIn("text-overlap", fired(p))
        p = Probe()
        p.label(box(200, 200, 300, 20), text={"fontSize": 20})
        p.label(box(200, 216, 300, 20), text={"fontSize": 20})   # 4 px deep
        self.assertIn("text-overlap", fired(p))


class UnboundedScope(unittest.TestCase):
    def outcome(self, grows, chars=40, **text):
        p = Probe()
        p.item(p.label(box(200, 200, 500, 30), text=text))["grows"] = grows
        p.item(p.data["texts"][0]["node"])["chars"] = chars
        return "unbounded-abs-text" in fired(p)

    def test_small_running_text_whose_box_grows_fires(self):
        self.assertTrue(self.outcome(300))

    def test_a_box_that_does_not_grow_is_bounded(self):
        self.assertFalse(self.outcome(0))
        self.assertFalse(self.outcome(1))                # within tolerance

    def test_large_text_sets_its_own_width(self):
        self.assertFalse(self.outcome(300, fontSize=24))
        self.assertFalse(self.outcome(300, fontSize=19, fontWeight=700))
        self.assertTrue(self.outcome(300, fontSize=19, fontWeight=400))

    def test_a_short_label_sets_its_own_width(self):
        self.assertFalse(self.outcome(300, chars=16))

    def test_text_outside_any_positioned_box_is_not_judged(self):
        p = Probe()
        p.text(p.el(), box(200, 200, 900, 30), grows=None)
        self.assertNotIn("unbounded-abs-text", fired(p))

    def test_one_finding_per_positioned_box_naming_the_widest_line(self):
        p = Probe()
        root = p.el(position="absolute")
        p.text(p.el(root), box(200, 200, 100, 30), grows=50)
        p.text(p.el(root), box(200, 240, 600, 30), grows=50)
        found = [v for v in geometry.evaluate(p.data, shipped_rules(), "s1")
                 if v.rule == "unbounded-abs-text"]
        self.assertEqual(len(found), 1)
        self.assertIn("runs 600 px wide", found[0].detail)


class TextOnMediaScope(unittest.TestCase):
    def test_wcag_split_for_text_shadow(self):
        cases = {
            "small, shadow only": ({"textShadow": SHADOW}, True),
            "large, shadow": ({"textShadow": SHADOW, "fontSize": 24}, False),
            "large bold, shadow": ({"textShadow": SHADOW, "fontSize": 19, "fontWeight": 700}, False),
            "large, no shadow": ({"fontSize": 30}, True),
        }
        for name, (text, fires) in cases.items():
            with self.subTest(case=name):
                p = Probe()
                m = p.media()
                t = p.label(box(900, 300, 300, 30), text=text)
                p.over(t, p.data["elements"][t]["parent"], m)
                self.assertEqual("text-on-media" in fired(p), fires)

    def test_what_counts_as_a_panel_or_scrim(self):
        cases = {
            "opaque panel": (dict(bg=NAVY), False),
            "faint panel": (dict(bg="rgba(0, 0, 0, 0.2)"), True),
            "gradient scrim": (dict(image="linear-gradient(rgba(0, 0, 0, 0) 40%, "
                                          "rgba(0, 0, 0, 0.55) 100%)"), False),
            "faint gradient": (dict(image="radial-gradient(rgba(0, 0, 0, 0.1), "
                                          "rgba(0, 0, 0, 0))"), True),
            "::before scrim": (dict(pseudo=[[TRANSPARENT, "linear-gradient(rgba(0, 0, 0, 0.8), "
                                                          "rgba(0, 0, 0, 0.6))"]]), False),
        }
        for name, (root, fires) in cases.items():
            with self.subTest(case=name):
                self.assertEqual("text-on-media" in fired(media_case(**root)), fires)

    def test_a_sibling_overlay_between_text_and_media_is_a_scrim(self):
        p = Probe()
        m = p.media()
        scrim = p.el(image="linear-gradient(rgba(0, 0, 0, 0), rgba(0, 0, 0, 0.9))")
        t = p.label(box(900, 300, 300, 30))
        p.over(t, p.data["elements"][t]["parent"], scrim, m)
        self.assertNotIn("text-on-media", fired(p))

    def test_a_panel_below_the_media_is_no_panel(self):
        p = Probe()
        card = p.el(bg="rgb(255, 255, 255)")
        m = p.media(parent=card)
        t = p.text(p.el(card), box(900, 300, 300, 30))
        p.over(t, m, card)
        self.assertIn("text-on-media", fired(p))

    def test_a_url_background_with_its_own_gradient_layer_is_scrimmed(self):
        p = Probe()
        m = p.media(tag="div", scrimmed=True)
        t = p.label(box(900, 300, 300, 30))
        p.over(t, p.data["elements"][t]["parent"], m)
        self.assertNotIn("text-on-media", fired(p))

    def test_text_not_sampled_over_media_is_not_judged(self):
        p = Probe()
        p.media()
        p.label(box(100, 300, 300, 30))           # no samples: no line over media
        self.assertNotIn("text-on-media", fired(p))


class RuleScopes(unittest.TestCase):
    def test_a_marker_holding_the_text_is_not_covered(self):
        p = Probe()
        pin = p.el()
        p.data["markers"].append({"node": pin, "box": box(200, 200, 300, 30)})
        p.text(p.el(pin), box(200, 200, 300, 30))
        self.assertNotIn("covers-marker", fired(p))

    def test_safe_area_honours_exempt_and_the_margin_token(self):
        p = Probe()
        p.text(p.el(tag="footer"), box(96, 1040, 300, 20), exempt=["safe-area"])
        self.assertNotIn("safe-area", fired(p))
        p = Probe(margin=40)
        p.text(p.el(), box(40, 200, 300, 30))
        self.assertNotIn("safe-area", fired(p))
        p = Probe(margin=None)                       # no token: fallback_margin 96
        p.text(p.el(), box(40, 200, 300, 30))
        self.assertIn("safe-area", fired(p))

    def test_safe_area_skips_text_on_a_panel_that_reaches_the_edge(self):
        p = Probe()
        side = p.el(bg="rgb(28, 31, 68)", rect=box(0, 0, 640, 1080))
        p.text(p.el(side), box(64, 200, 300, 30))
        self.assertNotIn("safe-area", fired(p))
        p = Probe()
        card = p.el(bg="rgb(28, 31, 68)", rect=box(40, 160, 400, 200))   # floats: no edge
        p.text(p.el(card), box(64, 200, 300, 30))
        self.assertIn("safe-area", fired(p))

    def test_clearance_skips_one_flow_one_drawing_and_overlaps(self):
        p = Probe()
        tag = p.el(position="absolute")
        p.text(p.el(tag), box(200, 200, 300, 30))
        p.text(p.el(tag), box(200, 222, 300, 30))
        self.assertNotIn("clearance", fired(p))
        p = Probe()
        svg = p.el(tag="svg", display="inline")
        p.text(p.el(svg, tag="text"), box(200, 200, 300, 30))
        p.text(p.el(svg, tag="text"), box(200, 222, 300, 30))
        self.assertNotIn("clearance", fired(p))
        self.assertNotIn("clearance", fired(overlap_bad()))

    def test_clipping_checks_only_the_clipped_axis(self):
        p = Probe()
        frame = p.el()
        p.text(p.el(frame), box(100, 100, 400, 30))
        p.clip(frame, box(100, 100, 250, 200), x=False, y=True)
        self.assertNotIn("clipped-text", fired(p))


class SeverityAndConfig(unittest.TestCase):
    def deck(self, toml):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        pathlib.Path(tmp, "deck.toml").write_text(toml)
        return geometry.load_rules(deckcfg.load(tmp))

    def test_severity_decides_the_exit_code(self):
        rules = shipped_rules()
        warns = geometry.evaluate(safe_bad().data, rules, "s1")
        self.assertEqual({v.severity for v in warns}, {"warn"})
        self.assertEqual(geometry.exit_code(warns), deckcfg.EXIT_OK)
        errors = geometry.evaluate(overlap_bad().data, rules, "s1")
        self.assertEqual(geometry.exit_code(errors), deckcfg.EXIT_FAIL)
        self.assertEqual(geometry.exit_code([]), deckcfg.EXIT_OK)

    def test_deck_toml_disables_and_tunes_rules(self):
        rules = self.deck('[geometry]\ndisable = ["text-on-media"]\n'
                          '[geometry.clearance]\nmin_gap = 1\n'
                          '[geometry.safe-area]\nseverity = "error"\nmargin = 20\n'
                          '[geometry.text-overlap]\nenabled = false\n')
        self.assertNotIn("text-on-media", fired(media_case(), rules))
        self.assertNotIn("clearance", fired(clearance_bad(), rules))
        self.assertNotIn("text-overlap", fired(overlap_bad(), rules))
        self.assertNotIn("safe-area", fired(safe_bad(), rules))       # 40 px clears a 20 margin
        p = Probe()
        p.text(p.el(), box(5, 200, 300, 30))
        found = geometry.evaluate(p.data, rules, "s1")
        self.assertEqual([(v.rule, v.severity) for v in found], [("safe-area", "error")])
        self.assertEqual(geometry.exit_code(found), deckcfg.EXIT_FAIL)

    def test_override_typos_fail_loudly(self):
        bad = {
            "unknown rule table": "[geometry.text-overlaps]\nmin_area = 9\n",
            "unknown disable id": '[geometry]\ndisable = ["nope"]\n',
            "unknown param": "[geometry.clearance]\nmin_gapp = 9\n",
            "wrong param type": '[geometry.clearance]\nmin_gap = "9"\n',
            "bad severity": '[geometry.clearance]\nseverity = "fatal"\n',
        }
        for name, toml in bad.items():
            with self.subTest(case=name):
                with self.assertRaises(deckcfg.ConfigError):
                    self.deck(toml)

    def test_a_rules_file_cannot_name_a_rule_without_an_evaluator(self):
        with self.assertRaises(deckcfg.ConfigError):
            geometry.parse_rules('[[rule]]\nid = "x"\nseverity = "error"\nenabled = true\n', "t")

    def test_color_and_gradient_parsing(self):
        self.assertEqual(geometry.alpha("rgb(1, 2, 3)"), 1.0)
        self.assertEqual(geometry.alpha("rgba(1, 2, 3, 0.25)"), 0.25)
        self.assertEqual(geometry.alpha(TRANSPARENT), 0.0)
        self.assertEqual(geometry.alpha("color(srgb 1 0 0 / 0.5)"), 0.5)
        layers = geometry.split_layers("linear-gradient(rgba(0, 0, 0, 0.2), rgb(0, 0, 0)), "
                                       'url("a.png")')
        self.assertEqual(len(layers), 2)
        self.assertEqual(geometry.gradient_alpha(layers[0]), 1.0)
        self.assertEqual(geometry.split_layers("none"), [])


class MissingBrowser(unittest.TestCase):
    def test_no_browser_exits_3_with_the_install_hint(self):
        err = io.StringIO()
        with mock.patch.object(geometry, "find_browser", return_value=None), \
                mock.patch.object(sys, "argv", ["geometry.py", FIXTURE]), \
                contextlib.redirect_stderr(err):
            code = geometry.main()
        self.assertEqual(code, deckcfg.EXIT_ENV)
        self.assertIn("chrome-headless-shell", err.getvalue())


class GeometryEndToEnd(unittest.TestCase):
    """The real path: Chrome over the fixture, through the CLI. The good slide
    carries a vector overlay svg across its labels (not media), and one label
    over the globe image darkened by a ::before gradient (a scrim)."""

    @classmethod
    def setUpClass(cls):
        if geometry.find_browser(deckcfg.load(FIXTURE)) is None:
            raise unittest.SkipTest("no headless Chrome found: " + geometry.INSTALL_HINT)

    def run_gate(self, *args):
        p = subprocess.run([sys.executable, SCRIPT, FIXTURE, *args, "--json"],
                           capture_output=True, text=True, timeout=120)
        return p, json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else None

    def test_the_colliding_labels_fail(self):
        p, out = self.run_gate("--slides", "bad")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        found = {(v["rule"], v["subject"]) for v in out["violations"]}
        self.assertIn(("text-overlap", ".label-north .l-cap x .label-south .l-name"), found)
        # the growth test: both caption boxes widen with their content
        self.assertIn(("unbounded-abs-text", ".label-north"), found)
        self.assertIn(("unbounded-abs-text", ".label-south"), found)
        self.assertIn(("text-on-media", ".label-north .l-cap on .globe"), found)

    def test_the_fixed_twin_passes_clean(self):
        p, out = self.run_gate("--slides", "good")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("geometry: 0 errors, 0 warnings on 1 slides", p.stdout)
        self.assertEqual(out["slides"], {"good": {"errors": 0, "warnings": 0}})
        self.assertNotIn("Traceback", p.stderr)

    def test_the_scrim_is_what_passes_the_label_over_the_image(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        strict = pathlib.Path(tmp, "deck.toml")
        strict.write_text("[substrate]\ntier = \"none\"\n"
                          "[geometry.text-on-media]\nmin_panel_alpha = 0.95\n")
        p, out = self.run_gate("--slides", "good", "--config", str(strict))
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual({v["subject"] for v in out["violations"]},
                         {".label-south .l-name on .globe", ".label-south .l-cap on .globe"})

    def test_an_unknown_slide_is_a_usage_error(self):
        p, _ = self.run_gate("--slides", "nope")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("have: bad, good", p.stderr)


if __name__ == "__main__":
    unittest.main()
