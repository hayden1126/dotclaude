"""skills/deck-production/scripts/geometry.py: the geometry gate (stdlib only).

Most cases call evaluate() on canned probe JSON, an outcome x rule matrix with
no browser. GeometryEndToEnd drives headless Chrome over the fixture deck and
skips, with the reason, when no browser is installed."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "skills", "deck-production", "scripts", "geometry.py")
FIXTURE = os.path.join(REPO, "tests", "deck_production", "fixtures", "geodeck")

_spec = importlib.util.spec_from_file_location("geometry", SCRIPT)
geometry = importlib.util.module_from_spec(_spec)
sys.modules["geometry"] = geometry        # dataclasses resolve their module by name
_spec.loader.exec_module(geometry)
deckcfg = geometry.deckcfg

TRANSPARENT = "rgba(0, 0, 0, 0)"


def box(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


class Probe:
    """Builds the JSON geometry_probe.js returns, one node at a time."""

    def __init__(self, margin=96):
        self.data = {"canvas": {"w": 1920, "h": 1080}, "scale": 1, "margin": margin,
                     "elements": [], "texts": [], "markers": [], "media": [], "clipping": []}

    def el(self, parent=None, token=None, tag="div", position="static", display="block",
           maxWidth="none", width="auto", left="auto", right="auto", textShadow="none",
           background=TRANSPARENT, backgroundImage=False):
        node = len(self.data["elements"])
        self.data["elements"].append({
            "parent": parent, "token": token or f".n{node}", "tag": tag, "position": position,
            "display": display, "maxWidth": maxWidth, "width": width, "left": left,
            "right": right, "textShadow": textShadow, "background": background,
            "backgroundImage": backgroundImage, "box": box(0, 0, 0, 0)})
        return node

    def label(self, *lines, text_style=None, **style):
        """An absolutely positioned label holding one text item. text-shadow
        inherits, so the probe reads it computed on the text element: pass it
        in text_style, which lands there."""
        root = self.el(position="absolute", **style)
        return self.text(self.el(root, **(text_style or {})), *lines)

    def text(self, node, *lines, exempt=()):
        self.data["texts"].append({"node": node, "lines": list(lines), "exempt": list(exempt),
                                   "text": "x"})
        return node

    def marker(self, rect, parent=None):
        self.data["markers"].append({"node": self.el(parent), "box": rect})

    def media(self, rect, parent=None, tag="img"):
        node = self.el(parent, tag=tag)
        self.data["media"].append({"node": node, "box": rect})
        return node

    def clip(self, node, rect, x=True, y=True):
        self.data["clipping"].append({"node": node, "box": rect, "x": x, "y": y})


def shipped_rules():
    return geometry.parse_rules(pathlib.Path(geometry.RULES_FILE).read_text(), "test")


def fired(probe, rules=None):
    return [v.rule for v in geometry.evaluate(probe.data, rules or shipped_rules(), "s1")]


# Bounded labels unless a case says otherwise, so unbounded-abs-text stays out
# of the other rules' cases.
B = {"maxWidth": "400px"}


def overlap_bad():
    p = Probe()
    p.label(box(200, 200, 300, 30), **B)
    p.label(box(300, 210, 300, 30), **B)
    return p


def overlap_good():
    p = Probe()
    p.label(box(200, 200, 300, 30), **B)
    p.label(box(200, 260, 300, 30), **B)
    return p


def marker_bad():
    p = Probe()
    p.label(box(200, 200, 300, 30), **B)
    p.marker(box(250, 210, 14, 14))
    return p


def marker_good():
    p = Probe()
    p.label(box(200, 200, 300, 30), **B)
    p.marker(box(600, 210, 14, 14))
    return p


def unbounded_bad():
    p = Probe()
    p.label(box(200, 200, 900, 30))
    return p


def media_bad():
    p = Probe()
    p.media(box(800, 100, 800, 800))
    p.label(box(900, 300, 300, 30), **B)
    return p


def media_good():
    p = Probe()
    p.media(box(800, 100, 800, 800))
    p.label(box(900, 300, 300, 30), background="rgba(11, 19, 32, 0.92)", **B)
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
    p.label(box(200, 200, 300, 30), **B)
    p.label(box(200, 234, 300, 30), **B)
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
    "unbounded-abs-text": (unbounded_bad, overlap_good),
    "text-on-media": (media_bad, media_good),
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
        (v,) = [v for v in geometry.evaluate(overlap_bad().data, shipped_rules(), "s17-globe")
                if v.rule == "text-overlap"]
        self.assertRegex(v.line(), r"^ERROR s17-globe text-overlap  \.n0 \.n1 x \.n2 \.n3  "
                                   r"\(200x20 px\)$")


class TextOverlapScope(unittest.TestCase):
    def test_nested_items_never_overlap(self):
        p = Probe()
        outer = p.text(p.el(position="absolute", **B), box(200, 200, 300, 30))
        p.text(p.el(outer, display="block"), box(200, 200, 300, 30))
        self.assertNotIn("text-overlap", fired(p))

    def test_inline_runs_in_one_block_never_overlap(self):
        p = Probe()
        para = p.el(position="absolute", **B)
        p.text(p.el(para, tag="b", display="inline"), box(200, 200, 100, 30))
        p.text(p.el(para, tag="i", display="inline"), box(250, 200, 100, 30))
        self.assertNotIn("text-overlap", fired(p))

    def test_two_svg_labels_are_separate_blocks(self):
        p = Probe()
        svg = p.el(tag="svg", display="inline")
        p.text(p.el(svg, tag="text", display="inline"), box(200, 200, 100, 30))
        p.text(p.el(svg, tag="text", display="inline"), box(250, 200, 100, 30))
        self.assertIn("text-overlap", fired(p))

    def test_a_touch_under_min_area_does_not_count(self):
        p = Probe()
        p.label(box(200, 200, 300, 30), **B)
        p.label(box(498, 228, 300, 30), **B)        # 2x2 px corner
        self.assertNotIn("text-overlap", fired(p))


class RuleScopes(unittest.TestCase):
    def test_a_marker_holding_the_text_is_not_covered(self):
        p = Probe()
        pin = p.el()
        p.data["markers"].append({"node": pin, "box": box(200, 200, 300, 30)})
        p.text(p.el(pin), box(200, 200, 300, 30))
        self.assertNotIn("covers-marker", fired(p))

    def test_unbounded_is_quiet_when_anything_bounds_the_text(self):
        cases = {
            "max-width on the root": dict(root={"maxWidth": "400px"}),
            "width on the root": dict(root={"width": "300px"}),
            "both insets": dict(root={"left": "96px", "right": "96px"}),
            "max-width on the caption": dict(child={"maxWidth": "420px"}),
        }
        for name, case in cases.items():
            with self.subTest(case=name):
                p = Probe()
                root = p.el(position="absolute", **case.get("root", {}))
                p.text(p.el(root, **case.get("child", {})), box(200, 200, 300, 30))
                self.assertNotIn("unbounded-abs-text", fired(p))

    def test_one_unbounded_finding_per_positioned_element(self):
        p = Probe()
        root = p.el(position="absolute")
        p.text(p.el(root), box(200, 200, 100, 30))
        p.text(p.el(root), box(200, 240, 600, 30))
        found = [v for v in geometry.evaluate(p.data, shipped_rules(), "s1")
                 if v.rule == "unbounded-abs-text"]
        self.assertEqual(len(found), 1)
        self.assertIn("600 px wide", found[0].detail)

    def test_text_on_media_outcomes(self):
        cases = {
            "shadow": (dict(text_style={"textShadow": "rgb(0, 0, 0) 0px 2px 8px"}), False),
            "opaque panel": (dict(background="rgba(0, 0, 0, 0.8)"), False),
            "background image": (dict(backgroundImage=True), False),
            "faint panel": (dict(background="rgba(0, 0, 0, 0.2)"), True),
            "bare": ({}, True),
        }
        for name, (style, fires) in cases.items():
            with self.subTest(case=name):
                p = Probe()
                p.media(box(800, 100, 800, 800))
                p.label(box(900, 300, 300, 30), **B, **style)
                self.assertEqual("text-on-media" in fired(p), fires)

    def test_a_panel_that_also_holds_the_media_is_no_panel(self):
        p = Probe()
        card = p.el(background="rgb(255, 255, 255)")
        p.media(box(800, 100, 800, 800), parent=card)
        p.text(p.el(card), box(900, 300, 300, 30))
        self.assertIn("text-on-media", fired(p))

    def test_text_inside_the_media_is_not_on_it(self):
        p = Probe()
        svg = p.media(box(800, 100, 800, 800), tag="svg")
        p.text(p.el(svg, tag="text", display="inline"), box(900, 300, 100, 30))
        self.assertNotIn("text-on-media", fired(p))

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

    def test_clearance_skips_one_flow_and_leaves_overlap_to_its_rule(self):
        p = Probe()
        tag = p.el(position="absolute", **B)
        p.text(p.el(tag), box(200, 200, 300, 30))
        p.text(p.el(tag), box(200, 232, 300, 30))
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
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp))
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
                          '[geometry.clearance]\nmin_gap = 2\n'
                          '[geometry.safe-area]\nseverity = "error"\nmargin = 20\n'
                          '[geometry.text-overlap]\nenabled = false\n')
        self.assertNotIn("text-on-media", fired(media_bad(), rules))
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

    def test_alpha_parses_computed_colors(self):
        self.assertEqual(geometry.alpha("rgb(1, 2, 3)"), 1.0)
        self.assertEqual(geometry.alpha("rgba(1, 2, 3, 0.25)"), 0.25)
        self.assertEqual(geometry.alpha(TRANSPARENT), 0.0)
        self.assertEqual(geometry.alpha("color(srgb 1 0 0 / 0.5)"), 0.5)


class MissingBrowser(unittest.TestCase):
    def test_no_browser_exits_3_with_the_install_hint(self):
        import contextlib
        import io
        from unittest import mock
        err = io.StringIO()
        with mock.patch.object(geometry, "find_browser", return_value=None), \
                mock.patch.object(sys, "argv", ["geometry.py", FIXTURE]), \
                contextlib.redirect_stderr(err):
            code = geometry.main()
        self.assertEqual(code, deckcfg.EXIT_ENV)
        self.assertIn("chrome-headless-shell", err.getvalue())


class GeometryEndToEnd(unittest.TestCase):
    """The real path: Chrome over the fixture, through the CLI."""

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
        rules = {v["rule"] for v in out["violations"]}
        self.assertLessEqual({"text-overlap", "unbounded-abs-text"}, rules)
        self.assertIn(".tag-north .t-cap x .tag-south .t-name",
                      [v["subject"] for v in out["violations"] if v["rule"] == "text-overlap"])

    def test_the_fixed_twin_passes_clean(self):
        p, out = self.run_gate("--slides", "good")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("geometry: 0 errors, 0 warnings on 1 slides", p.stdout)
        self.assertEqual(out["slides"], {"good": {"errors": 0, "warnings": 0}})

    def test_an_unknown_slide_is_a_usage_error(self):
        p, _ = self.run_gate("--slides", "nope")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("have: bad, good", p.stderr)


if __name__ == "__main__":
    unittest.main()
