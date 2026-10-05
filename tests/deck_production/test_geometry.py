"""skills/deck-production/scripts/geometry.py: the geometry gate (stdlib only).

Most cases call evaluate() on canned probe JSON, an outcome x rule matrix with
no browser. GeometryEndToEnd drives headless Chrome over the fixture deck and
skips, with the reason, when no browser is installed. The probe-side
principles are pinned there, on the fixture's slides: measured contrast over a
generated raster (bright, busy, scrimmed, haloed), through group opacity, an
overlay and a veil over half a caption, on SVG halos, on a reveal slide
background, at a hairline weight and a hair under AA; text covered by an
image; the fit test (a short caption under a max-width it never reaches is
bounded, a centered one that fills its room is not); fragments probed at
every step and judged where most visible; an entrance animation measured at
rest; a tight display headline that one flow stacks, and lines stacked half
an em deep that collide; canvas-origin margins on a slide reveal centers,
and a margin token in rem; slow fonts, backgrounds and media named."""
import contextlib
import http.server
import importlib.util
import io
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
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
NAVY = "rgb(28, 31, 68)"


def box(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def flat(ratio, n=1000, hidden=0.0):
    """A contrast measurement where every judged pixel has this ratio."""
    return {"q": [ratio] * 101, "n": n, "hidden": hidden}


class Probe:
    """Builds the JSON geometry_probe.js returns, one node at a time. Text is
    20 px regular unless a case says otherwise; line rects are 30 px tall
    (content area), so their em-box ink is the middle 20 px."""

    def __init__(self, margin=96):
        self.data = {"canvas": {"w": 1920, "h": 1080}, "scale": 1, "margin": margin,
                     "elements": [], "texts": [], "markers": [], "clipping": []}

    def el(self, parent=None, token=None, tag="div", position="static", display="block",
           fontSize=20, fontWeight=400, bg=TRANSPARENT, image="none", rect=None,
           displaced=False):
        node = len(self.data["elements"])
        self.data["elements"].append({
            "parent": parent, "token": token or f".n{node}", "tag": tag, "position": position,
            "display": display, "displaced": displaced, "fontSize": fontSize,
            "fontWeight": fontWeight, "paints": [[bg, image]], "box": rect or box(0, 0, 0, 0)})
        return node

    def label(self, *lines, text=None, **root):
        """An absolutely positioned label holding one text item. Text styles
        go in `text`: the probe reads them computed on the text element."""
        node = self.el(self.el(position="absolute", **root), **(text or {}))
        return self.text(node, *lines)

    def text(self, node, *lines, exempt=(), chars=40, fit=None, contrast=None):
        """A text item; an element with no box of its own gets its lines' bounds."""
        el = self.data["elements"][node]
        if not el["box"]["w"] and lines:
            x0, y0 = min(r["x"] for r in lines), min(r["y"] for r in lines)
            x1 = max(r["x"] + r["w"] for r in lines)
            y1 = max(r["y"] + r["h"] for r in lines)
            el["box"] = box(x0, y0, x1 - x0, y1 - y0)
        self.data["texts"].append({"node": node, "lines": list(lines), "exempt": list(exempt),
                                   "chars": chars, "fit": fit, "contrast": contrast,
                                   "color": [255, 255, 255, 1], "text": "x"})
        return node

    def item(self, node):
        return next(t for t in self.data["texts"] if t["node"] == node)

    def marker(self, rect, parent=None):
        self.data["markers"].append({"node": self.el(parent), "box": rect})

    def clip(self, node, rect, x=True, y=True):
        self.data["clipping"].append({"node": node, "box": rect, "x": x, "y": y})


def shipped_rules():
    return geometry.parse_rules(pathlib.Path(geometry.RULES_FILE).read_text(), "test")


def violations(probe, rules=None):
    return geometry.evaluate(probe.data, rules or shipped_rules(), "s1")


def fired(probe, rules=None):
    return [v.rule for v in violations(probe, rules)]


UNBOUNDED = {"content": True, "edge": True}


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


def unbounded(fit, chars=40, **text):
    p = Probe()
    t = p.item(p.label(box(200, 200, 900, 30), text=text))
    t["fit"], t["chars"] = fit, chars
    return p


def contrast(ratio, **text):
    p = Probe()
    p.item(p.label(box(200, 200, 300, 30), text=text))["contrast"] = flat(ratio)
    return p


def covered(share):
    p = Probe()
    p.item(p.label(box(200, 200, 300, 30)))["contrast"] = flat(7.0, hidden=share)
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
    "unbounded-abs-text": (lambda: unbounded(UNBOUNDED),
                           lambda: unbounded({"content": True, "edge": False})),
    "text-contrast": (lambda: contrast(3.2), lambda: contrast(4.6)),
    "covered-text": (lambda: covered(0.3), lambda: covered(0.0)),
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

    def test_in_flow_items_under_one_box_still_count(self):
        # An overflowing fixed-height card, a negative margin, two grid items
        # in one cell: one layout pass, and still ink on ink.
        p = Probe()
        card = p.el(p.el(position="absolute"), display="grid")
        p.text(p.el(card), box(200, 200, 300, 30))
        p.text(p.el(card), box(200, 210, 300, 30))
        self.assertIn("text-overlap", fired(p))

    def test_a_slide_with_no_positioned_boxes_is_checked(self):
        p = Probe()
        p.text(p.el(), box(200, 200, 300, 30))
        p.text(p.el(), box(250, 210, 300, 30))
        self.assertIn("text-overlap", fired(p))

    def test_a_positioned_descendant_over_its_ancestors_text_counts(self):
        # A badge absolutely placed over a card title is not in its flow.
        p = Probe()
        title = p.text(p.el(), box(200, 200, 300, 30))
        p.text(p.el(title, position="absolute"), box(260, 205, 80, 30))
        self.assertIn("text-overlap", fired(p))

    def test_two_svg_labels_are_placed_independently(self):
        p = Probe()
        svg = p.el(tag="svg", display="inline")
        p.text(p.el(svg, tag="text", display="inline"), box(200, 200, 100, 30))
        p.text(p.el(svg, tag="text", display="inline"), box(250, 200, 100, 30))
        self.assertIn("text-overlap", fired(p))

    def tight_headline(self, **span):
        """<h1><span>Grow</span><br><span>faster</span></h1> at 100 px,
        line-height .85: 85 px line boxes, 115 px content areas, em boxes
        that overlap by 15 px."""
        p = Probe()
        h1 = p.el(p.el(), tag="h1", fontSize=100, rect=box(96, 200, 1728, 170))
        p.text(p.el(h1, tag="span", display="inline", fontSize=100), box(96, 185, 230, 115))
        p.text(p.el(h1, tag="span", display="inline", fontSize=100, **span),
               box(96, 270, 330, 115))
        return p

    def test_lines_one_flow_stacked_are_never_compared(self):
        # However tight the leading: no text-overlap, and no clearance either.
        self.assertEqual(fired(self.tight_headline()), [])
        p = Probe()                                  # the same as two stacked blocks
        col = p.el(position="absolute")
        p.text(p.el(col, fontSize=100, rect=box(96, 200, 600, 85)), box(96, 185, 230, 115))
        p.text(p.el(col, fontSize=100, rect=box(96, 285, 600, 85)), box(96, 270, 330, 115))
        self.assertEqual(fired(p), [])

    def test_displaced_lines_in_one_flow_still_count(self):
        # A relative offset, a transform or a negative margin moves a line off
        # the place its flow gave it: the reason in-flow items are compared.
        self.assertIn("text-overlap", fired(self.tight_headline(displaced=True)))
        p = Probe()                                  # a fixed-height card spilling over the next
        col = p.el(position="absolute")
        card = p.el(col, rect=box(96, 200, 600, 40), displaced=True)
        p.text(p.el(card), box(96, 230, 300, 30))
        p.text(p.el(p.el(col, rect=box(96, 240, 600, 40))), box(96, 240, 300, 30))
        self.assertIn("text-overlap", fired(p))

    def test_content_areas_touching_is_not_ink_on_ink(self):
        # 23 px type, 33 px content areas, lines 26 px apart: the rects overlap
        # by 7 px, the em boxes do not meet.
        p = Probe()
        svg = p.el(tag="svg", display="inline")
        p.text(p.el(svg, tag="text", fontSize=23), box(124, 490, 52, 33))
        p.text(p.el(svg, tag="text", fontSize=23), box(124, 516, 52, 33))
        self.assertEqual(fired(p), [])

    def test_a_sliver_under_min_depth_is_clearance_not_overlap(self):
        p = Probe()
        p.label(box(200, 200, 300, 20))
        p.label(box(200, 218, 300, 20))          # ink overlaps 300x2 px
        found = violations(p)
        self.assertEqual([v.rule for v in found], ["clearance"])
        self.assertIn("overlaps", found[0].detail)
        p = Probe()
        p.label(box(200, 200, 300, 20))
        p.label(box(200, 216, 300, 20))          # 4 px deep: overlap, reported once
        self.assertEqual(fired(p), ["text-overlap"])


    def test_a_shallow_overlap_anywhere_compared_is_clearance(self):
        # Inside one positioned box (a negative margin) and between the labels
        # of one svg drawing: too shallow for text-overlap, still ink on ink.
        p = Probe()
        tag = p.el(position="absolute")
        p.text(p.el(tag), box(200, 200, 300, 20))
        p.text(p.el(tag, displaced=True), box(200, 218, 300, 20))
        self.assertEqual(fired(p), ["clearance"])
        p = Probe()
        svg = p.el(tag="svg", display="inline")
        p.text(p.el(svg, tag="text", display="inline"), box(200, 200, 300, 20))
        p.text(p.el(svg, tag="text", display="inline"), box(200, 218, 300, 20))
        self.assertEqual(fired(p), ["clearance"])


    def test_lines_one_flow_stacked_half_an_em_deep_collide(self):
        # One flow, no displacement: tight leading up to flow_overlap em is
        # design (a display face at .85), deeper is glyph on glyph.
        for depth, hit in ((3, False), (12, True)):
            with self.subTest(depth=depth):
                p = Probe()
                block = p.el()
                p.text(p.el(block, display="inline"), box(100, 100, 300, 30))
                p.text(p.el(block, display="inline"), box(100, 120 - depth, 300, 30))
                self.assertEqual("text-overlap" in fired(p), hit)

    def test_identical_structures_are_told_apart_by_identity(self):
        # Two cards built alike: one pair of captions collides deep
        # (text-overlap), the other only shallowly (clearance). Same subject
        # text, different elements: the shallow one must not be dropped as
        # if text-overlap had reported it.
        p = Probe()
        for top, shift in ((100, 10), (400, 18)):
            card = p.el(position="absolute", token=".card")
            p.text(p.el(card, token=".a"), box(100, top, 300, 30))
            p.text(p.el(p.el(card, token=".b-wrap", position="absolute"), token=".b"),
                   box(100, top + shift, 300, 30))
        found = [(v.rule, v.subject) for v in violations(p)]
        self.assertIn(("text-overlap", ".card .a x .b-wrap .b"), found)
        self.assertIn(("clearance", ".card .a x .b-wrap .b"), found)


class UnboundedScope(unittest.TestCase):
    def test_the_fit_outcomes(self):
        cases = {
            "content-sized, runs to the container's edge": (UNBOUNDED, True),
            "content-sized, stops short (a max-width)": ({"content": True, "edge": False}, False),
            "does not move (a width, or both insets)": ({"content": False, "edge": False}, False),
            "not in a positioned box": (None, False),
        }
        for name, (fit, fires) in cases.items():
            with self.subTest(case=name):
                self.assertEqual("unbounded-abs-text" in fired(unbounded(fit)), fires)

    def test_large_type_is_no_exemption(self):
        # A 120-character caption at 24 px still needs a measure.
        self.assertIn("unbounded-abs-text", fired(unbounded(UNBOUNDED, chars=120, fontSize=24)))

    def test_headings_and_short_labels_set_their_own_width(self):
        self.assertNotIn("unbounded-abs-text", fired(unbounded(UNBOUNDED, chars=16)))
        p = Probe()
        t = p.item(p.text(p.el(p.el(position="absolute"), tag="h2", fontSize=60),
                          box(96, 96, 1275, 70)))
        t["fit"], t["chars"] = UNBOUNDED, 80
        self.assertNotIn("unbounded-abs-text", fired(p))

    def test_one_finding_per_positioned_box_naming_the_widest_line(self):
        p = Probe()
        root = p.el(position="absolute")
        p.text(p.el(root), box(200, 200, 100, 30), fit=UNBOUNDED)
        p.text(p.el(root), box(200, 240, 600, 30), fit=UNBOUNDED)
        found = [v for v in violations(p) if v.rule == "unbounded-abs-text"]
        self.assertEqual(len(found), 1)
        self.assertIn("runs 600 px wide", found[0].detail)


class ContrastScope(unittest.TestCase):
    def test_wcag_thresholds_by_size_and_weight(self):
        cases = {
            "small at 4.4": (4.4, {}, True),
            "small at 4.5": (4.5, {}, False),
            "24 px at 3.1": (3.1, {"fontSize": 24}, False),
            "19 px bold at 3.1": (3.1, {"fontSize": 19, "fontWeight": 700}, False),
            "19 px regular at 3.1": (3.1, {"fontSize": 19}, True),
            "large at 2.9": (2.9, {"fontSize": 40}, True),
        }
        for name, (ratio, text, fires) in cases.items():
            with self.subTest(case=name):
                self.assertEqual("text-contrast" in fired(contrast(ratio, **text)), fires)

    def test_the_judged_percentile_is_a_param(self):
        p = Probe()
        q = [1.0] * 3 + [10.0] * 98              # a few stray dots, else crisp
        p.item(p.label(box(200, 200, 300, 30)))["contrast"] = {"q": q, "n": 1000, "hidden": 0}
        self.assertNotIn("text-contrast", fired(p))
        rules = shipped_rules()
        next(r for r in rules if r["id"] == "text-contrast")["params"]["percentile"] = 0
        self.assertIn("text-contrast", fired(p, rules))

    def test_unmeasurable_text_is_not_judged(self):
        p = Probe()
        p.label(box(200, 200, 300, 30))          # contrast None (no single color)
        self.assertNotIn("text-contrast", fired(p))

    def test_a_ratio_a_hair_under_the_bar_fails_and_never_shows_as_passing(self):
        found = violations(contrast(4.4999))
        self.assertEqual([v.rule for v in found], ["text-contrast"])
        self.assertIn("4.49:1", found[0].detail)

    def test_too_few_pixels_decide_only_when_the_median_fails(self):
        # Below min_pixels the 5th percentile is the worst pixel or two: a
        # stray dot. Median passing: a warning; median failing: an error.
        q = [3.0] * 50 + [6.0] * 51
        cases = {"few, median passes": ({"q": q, "n": 12, "hidden": 0}, "warn"),
                 "few, median fails": ({"q": [3.0] * 101, "n": 12, "hidden": 0}, "error"),
                 "many": ({"q": q, "n": 900, "hidden": 0}, "error")}
        for name, (measured, severity) in cases.items():
            with self.subTest(case=name):
                p = Probe()
                p.item(p.label(box(200, 200, 300, 30)))["contrast"] = measured
                found = violations(p)
                self.assertEqual([(v.rule, v.severity) for v in found],
                                 [("text-contrast", severity)])

    def test_covered_text_is_its_own_finding(self):
        self.assertEqual(fired(covered(0.3)), ["covered-text"])
        self.assertEqual(fired(covered(0.01)), [])

    def test_decorative_type_is_exempt(self):
        p = contrast(1.2)
        p.data["texts"][0]["exempt"] = ["text-contrast"]
        self.assertNotIn("text-contrast", fired(p))


class SafeAreaScope(unittest.TestCase):
    def test_exempt_and_the_margin_token(self):
        p = Probe()
        p.text(p.el(tag="footer"), box(96, 1040, 300, 20), exempt=["safe-area"])
        self.assertNotIn("safe-area", fired(p))
        p = Probe(margin=40)
        p.text(p.el(), box(40, 200, 300, 30))
        self.assertNotIn("safe-area", fired(p))
        p = Probe(margin=0)                          # a 0 token means 0, not "unset"
        p.text(p.el(), box(10, 200, 300, 30))
        self.assertNotIn("safe-area", fired(p))
        p = Probe(margin=None)                       # no token: fallback_margin 96
        p.text(p.el(), box(40, 200, 300, 30))
        self.assertIn("safe-area", fired(p))

    def test_a_panel_excuses_only_the_edge_it_hugs(self):
        side = box(0, 0, 640, 1080)                  # a left column, full height
        p = Probe()
        p.text(p.el(p.el(bg=NAVY, rect=side)), box(64, 200, 300, 30))
        self.assertNotIn("safe-area", fired(p))
        p = Probe()                                  # same column, text in its top margin
        p.text(p.el(p.el(bg=NAVY, rect=box(0, 300, 640, 780))), box(120, 40, 300, 30))
        self.assertIn("safe-area", fired(p))
        p = Probe()                                  # a full-canvas wrapper excuses nothing
        p.text(p.el(p.el(bg=NAVY, rect=box(0, 0, 1920, 1080))), box(64, 200, 300, 30))
        self.assertIn("safe-area", fired(p))
        p = Probe()                                  # a floating card hugs no edge
        p.text(p.el(p.el(bg=NAVY, rect=box(40, 160, 400, 200))), box(64, 200, 300, 30))
        self.assertIn("safe-area", fired(p))


class RuleScopes(unittest.TestCase):
    def test_a_marker_holding_the_text_is_not_covered(self):
        p = Probe()
        pin = p.el()
        p.data["markers"].append({"node": pin, "box": box(200, 200, 300, 30)})
        p.text(p.el(pin), box(200, 200, 300, 30))
        self.assertNotIn("covers-marker", fired(p))

    def test_clearance_skips_one_flow_and_one_drawing(self):
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
        rules = self.deck('[geometry]\ndisable = ["text-contrast"]\n'
                          '[geometry.clearance]\nmin_gap = 1\n'
                          '[geometry.safe-area]\nseverity = "error"\nmargin = 20\n'
                          '[geometry.text-overlap]\nenabled = false\n')
        self.assertNotIn("text-contrast", fired(contrast(1.5), rules))
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
            "percentile out of range": "[geometry.text-contrast]\npercentile = 120\n",
            "contrast lowered without a reason": "[geometry.text-contrast]\nmin_small = 3.0\n",
            "contrast lowered with a blank reason":
                '[geometry.text-contrast]\nmin_large = 2.5\nreason = "  "\n',
            "contrast lowered at regulated rigor":
                '[deck]\nrigor = "regulated"\n[geometry.text-contrast]\nmin_small = 3.0\n'
                'reason = "brand palette"\n',
            "contrast lowered for a regulated audience":
                '[deck]\naudience = "external-investor"\n[geometry.text-contrast]\n'
                'min_large = 2.5\nreason = "brand palette"\n',
        }
        for name, toml in bad.items():
            with self.subTest(case=name):
                with self.assertRaises(deckcfg.ConfigError):
                    self.deck(toml)

    def test_a_lowered_contrast_bar_names_its_key(self):
        with self.assertRaisesRegex(deckcfg.ConfigError, r"min_small = 3\.0.*reason"):
            self.deck("[geometry.text-contrast]\nmin_small = 3.0\n")
        with self.assertRaisesRegex(deckcfg.ConfigError, r"min_small = 3\.0.*regulated"):
            self.deck('[deck]\nrigor = "regulated"\n[geometry.text-contrast]\nmin_small = 3.0\n'
                      'reason = "x"\n')

    def test_a_lowered_contrast_bar_with_a_reason_applies(self):
        rules = self.deck('[geometry.text-contrast]\nmin_small = 3.0\n'
                          'reason = "brand accent, signed off by the client"\n')
        self.assertEqual(geometry.lowered_contrast(rules), ["min_small"])
        self.assertNotIn("text-contrast", fired(contrast(3.2), rules))
        self.assertIn("text-contrast", fired(contrast(2.9), rules))
        # AA and above need no reason; a disabled rule lowers nothing.
        self.assertEqual(geometry.lowered_contrast(self.deck("[geometry.text-contrast]\n"
                                                             "min_small = 7.0\n")), [])
        self.assertEqual(geometry.lowered_contrast(self.deck(
            '[geometry]\ndisable = ["text-contrast"]\n')), [])

    def test_a_zero_width_reason_is_no_reason(self):
        zwsp = chr(0x200B)
        with self.assertRaisesRegex(deckcfg.ConfigError, "reason"):
            self.deck(f'[geometry.text-contrast]\nmin_small = 3.0\nreason = "{zwsp}"\n')
        with self.assertRaisesRegex(deckcfg.ConfigError, "rigor_reason"):
            self.deck(f'[deck]\nrigor = "standard"\nrigor_reason = "{zwsp} "\n'
                      'audience = "external-investor"\n')

    def test_the_regulated_floor_cannot_be_loosened(self):
        reg = '[deck]\nrigor = "regulated"\n'
        bad = {
            "severity warn": ("[geometry.text-contrast]\nseverity = \"warn\"\n", "severity"),
            "enabled false": ("[geometry.text-contrast]\nenabled = false\n", "enabled"),
            "disabled": ('[geometry]\ndisable = ["text-contrast"]\n', "disable"),
            "percentile up": ("[geometry.text-contrast]\npercentile = 10\n", "percentile"),
            "large_px down": ("[geometry.text-contrast]\nlarge_px = 18\n", "large_px"),
            "large_bold_px down": ("[geometry.text-contrast]\nlarge_bold_px = 14\n",
                                   "large_bold_px"),
            "bold_weight down": ("[geometry.text-contrast]\nbold_weight = 400\n",
                                 "bold_weight"),
        }
        for name, (toml, key) in bad.items():
            with self.subTest(case=name):
                with self.assertRaisesRegex(deckcfg.ConfigError, f"{key}.*regulated"):
                    self.deck(reg + toml)
                self.deck('[deck]\nrigor = "standard"\n' + toml)    # allowed below it
        # Stricter is always allowed.
        self.deck(reg + "[geometry.text-contrast]\npercentile = 2\nlarge_px = 30\n")

    def test_a_regulated_deck_needs_text_contrast_in_its_rules_file(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        rules = pathlib.Path(tmp, "rules.toml")
        rules.write_text('[[rule]]\nid = "clearance"\nseverity = "warn"\nenabled = true\n'
                         'min_gap = 8\n')
        with self.assertRaisesRegex(deckcfg.ConfigError, "rules.toml: has no text-contrast"):
            self.deck(f'[deck]\nrigor = "regulated"\n[geometry]\nrules = "{rules}"\n')
        rules.write_text(pathlib.Path(geometry.RULES_FILE).read_text().replace(
            "large_px = 24", "large_px = 12"))
        with self.assertRaisesRegex(deckcfg.ConfigError, "rules.toml: text-contrast large_px"):
            self.deck(f'[deck]\nrigor = "regulated"\n[geometry]\nrules = "{rules}"\n')

    def test_declaring_a_tier_below_the_derived_one_needs_a_reason(self):
        facts = 'audience = "external-investor"\n'
        with self.assertRaisesRegex(deckcfg.ConfigError, r"rigor = 'standard'.*rigor_reason"):
            self.deck('[deck]\nrigor = "standard"\n' + facts)
        rules = self.deck('[deck]\nrigor = "standard"\nrigor_reason = "internal dry run"\n'
                          + facts + '[geometry.text-contrast]\nmin_small = 3.0\n'
                          'reason = "draft palette"\n')
        self.assertEqual(geometry.lowered_contrast(rules), ["min_small"])
        self.deck('[deck]\nrigor = "regulated"\n' + facts)          # lowers nothing

    def test_an_exemption_that_takes_the_slide_is_refused_at_regulated_rigor(self):
        rules = shipped_rules()
        p = Probe()
        for i in range(4):
            p.label(box(200, 100 + 60 * i, 300, 30))
        p.data["exemptHits"] = {"text-contrast": {"[data-decor]": 1, "section *": 4}}
        with self.assertRaisesRegex(deckcfg.ConfigError, "exempt 'section \\*' takes 4 of the 4"):
            geometry.broad_exemptions(p.data, rules, "s1", "deck.toml")
        p.data["exemptHits"] = {"text-contrast": {"[data-decor]": 1}}
        geometry.broad_exemptions(p.data, rules, "s1", "deck.toml")

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


def run_main(*argv, deck=FIXTURE, **patches):
    """geometry.main() in process: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", ["geometry.py", deck, *argv]), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
            contextlib.ExitStack() as stack:
        for name, value in patches.items():
            stack.enter_context(mock.patch.object(geometry, name, value))
        try:
            code = geometry.main()
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def config(text):
    """(temp dir, path) of a deck.toml for --config; the caller removes the dir."""
    tmp = tempfile.mkdtemp()
    path = pathlib.Path(tmp, "deck.toml")
    path.write_text('[substrate]\ntier = "none"\n' + text)
    return tmp, str(path)


class BrowserFailures(unittest.TestCase):
    def run_main(self, *argv, **patches):
        code, _out, err = run_main(*argv, **patches)
        return code, err

    def test_a_lowered_contrast_bar_prints_its_reason_on_every_run(self):
        tmp, cfg = config('[geometry.text-contrast]\nmin_small = 3.0\n'
                          'reason = "brand accent, signed off"\n')
        self.addCleanup(shutil.rmtree, tmp)
        code, out, _err = run_main("--config", cfg, find_browser=lambda cfg: None)
        self.assertEqual(code, deckcfg.EXIT_ENV)
        self.assertIn("text-contrast below WCAG AA (min_small 3.0): brand accent, signed off", out)

    def test_no_browser_exits_3_with_the_install_hint(self):
        code, err = self.run_main(find_browser=lambda cfg: None)
        self.assertEqual(code, deckcfg.EXIT_ENV)
        self.assertIn("chrome-headless-shell", err)

    def test_a_browser_that_dies_exits_3_at_once(self):
        def dies(*args, **kwargs):
            raise geometry.BrowserDied("the browser exited")
        code, err = self.run_main(measure=dies, find_browser=lambda cfg: ("x", True))
        self.assertEqual(code, deckcfg.EXIT_ENV)
        self.assertIn("the browser exited", err)

    def test_a_page_error_is_not_an_environment_problem(self):
        def throws(*args, **kwargs):
            raise geometry.PageError("TypeError: boom")
        code, err = self.run_main(measure=throws, find_browser=lambda cfg: ("x", True))
        self.assertEqual(code, deckcfg.EXIT_USAGE)
        self.assertNotIn("install", err)


class GeometryEndToEnd(unittest.TestCase):
    """The real path: Chrome over the fixture, through the CLI."""

    @classmethod
    def setUpClass(cls):
        if geometry.find_browser(deckcfg.load(FIXTURE)) is None:
            raise unittest.SkipTest("no headless Chrome found: " + geometry.INSTALL_HINT)

    def run_gate(self, *args):
        p = subprocess.run([sys.executable, SCRIPT, FIXTURE, *args, "--json"],
                           capture_output=True, text=True, timeout=180)
        return p, json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else None

    def found(self, out):
        return {(v["rule"], v["subject"]) for v in out["violations"]}

    def test_the_colliding_labels_fail(self):
        p, out = self.run_gate("--slides", "bad")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {
            ("text-overlap", ".label-north .l-cap x .label-south .l-name"),
            ("unbounded-abs-text", ".label-north"),
            ("unbounded-abs-text", ".label-south"),
        })

    def test_the_fixed_twin_passes_clean(self):
        # Includes a short caption under a max-width it never reaches: the
        # box widens when the text grows, but stops short of the container.
        # Also a display headline at line-height .85 (two lines one flow
        # stacked, em boxes 15 px into each other) and a white-on-navy
        # fragment, which reveal fades in over .2 s: measured mid-fade it
        # reads near 1:1.
        p, out = self.run_gate("--slides", "good")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("geometry: 0 errors, 0 warnings on 1 slides", p.stdout)
        self.assertNotIn("Traceback", p.stderr)

    def test_contrast_is_measured_on_pixels(self):
        # One raster: dark ink on its bright half passes; light small type on
        # its checkerboard fails; the same type on a dark scrim passes, and so
        # does a dense dark halo (measured, the halo is the backdrop).
        p, out = self.run_gate("--slides", "contrast")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {("text-contrast", ".light-on-busy")})

    def test_margins_are_the_canvas_not_a_centered_section(self):
        # Reveal centers this short slide, so its last line sits in the
        # canvas's bottom margin; the margin token is in rem.
        p, out = self.run_gate("--slides", "centered")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {("safe-area", ".low")})
        self.assertIn("96 px bottom margin", out["violations"][0]["detail"])

    def test_a_bad_selector_is_a_config_error_naming_the_key(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        cfg = pathlib.Path(tmp, "deck.toml")
        cfg.write_text('[substrate]\ntier = "none"\n[geometry.covers-marker]\nmarkers = ["[[x"]\n')
        p, _ = self.run_gate("--slides", "good", "--config", str(cfg))
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("[geometry.covers-marker] markers", p.stderr)

    def test_an_unknown_slide_is_a_usage_error(self):
        p, _ = self.run_gate("--slides", "nope")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("have: bad, good, contrast, centered, anchors, svg, veil, thin, covered, "
                      "steps, rest, flow, bright-bg", p.stderr)

    def test_a_centered_caption_is_judged_by_its_room_not_an_edge(self):
        # Both captions sit at translateX(-50%) with no max-width. The west one
        # grows past the canvas edge; the east one fills the 30% right of its
        # anchor and stops there, touching nothing. Both are unbounded.
        p, out = self.run_gate("--slides", "anchors")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {("unbounded-abs-text", ".anchor-east"),
                                           ("unbounded-abs-text", ".anchor-west")})

    def test_svg_halos_are_backdrop_and_svg_fills_are_forced(self):
        # White labels on a bright map: one haloed by a stroke painted under
        # the fill, one a textPath with its own fill inside a haloed text; both
        # pass. A tspan at fill-opacity .3 on navy fails.
        p, out = self.run_gate("--slides", "svg")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {("text-contrast", ".faint-wrap .faint")})

    def test_contrast_is_judged_through_group_opacity_and_overlays(self):
        # White on navy: in a group at opacity .4 fails, at .55 passes, and
        # under a 0.6-alpha black overlay painted above it fails, also when
        # the overlay covers only its left half (the veil is per pixel).
        p, out = self.run_gate("--slides", "veil")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {("text-contrast", ".group40 .t"),
                                           ("text-contrast", ".under-veil"),
                                           ("text-contrast", ".half-veil")})

    def test_a_thin_weight_is_judged_at_its_color_and_the_bar_unrounded(self):
        # #767676 at weight 200, 14 px, on white is 4.54:1: never fully
        # covered, but not group opacity either. #83746a is 4.4955:1, which a
        # comparison rounded to 0.01 would pass.
        p, out = self.run_gate("--slides", "thin")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {("text-contrast", ".edge-ratio")})
        self.assertIn("4.49:1", out["violations"][0]["detail"])

    def test_text_under_an_image_is_covered(self):
        p, out = self.run_gate("--slides", "covered")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {("covered-text", ".t")})

    def test_every_fragment_step_is_probed(self):
        # A current-visible note collides with a caption only at its own step
        # (3 of 4); a semi-fade-out line at half opacity in the final state
        # would fail, and is judged at full strength, where it passes.
        p, out = self.run_gate("--slides", "steps")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual([(v["rule"], v["subject"], v["step"]) for v in out["violations"]],
                         [("text-overlap", ".flash x .joins", "3/4")])
        self.assertIn("ERROR steps step 3/4 text-overlap", p.stdout)

    def test_an_entrance_animation_is_measured_at_rest(self):
        # It rises from opacity 0 and 40 px down onto the base caption; at
        # its start it is invisible and clear of it.
        p, out = self.run_gate("--slides", "rest")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {("text-overlap", ".base x .rise")})

    def test_lines_stacked_half_an_em_deep_collide(self):
        p, out = self.run_gate("--slides", "flow")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {("text-overlap", ".tight .t1 x .tight .t2")})

    def test_a_slide_background_is_loaded_before_it_is_measured(self):
        # Reveal sets a data-background-image only when its slide is reached;
        # measured alone, the slide is the first one visited.
        p, out = self.run_gate("--slides", "bright-bg")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(self.found(out), {("text-contrast", ".on-bright")})

    def test_no_contrast_shots_when_the_rule_is_off(self):
        tmp, cfg = config('[geometry]\ndisable = ["text-contrast", "covered-text"]\n')
        self.addCleanup(shutil.rmtree, tmp)

        def shots(*args):
            raise AssertionError("contrast measured with text-contrast and covered-text off")
        code, out, err = run_main("--slides", "veil", "--config", cfg, measure_contrast=shots)
        self.assertEqual(code, 0, out + err)
        self.assertIn("geometry: 0 errors, 0 warnings on 1 slides", out)

    def test_a_hanging_font_is_named_within_the_settle_budget(self):
        # A font that never answers: the slide's one settle deadline expires
        # and names it (exit 2), before the evaluate timeout could call the
        # browser dead (exit 3, with the install hint).
        hang = socket.socket()
        hang.bind(("127.0.0.1", 0))
        hang.listen(8)                   # accepted by the kernel, never answered
        self.addCleanup(hang.close)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        deck = os.path.join(tmp, "geodeck")
        shutil.copytree(FIXTURE, deck)
        index = pathlib.Path(deck, "index.html")
        face = ("@font-face { font-family: Hang; src: url(http://127.0.0.1:%d/hang.woff2); }\n"
                "    #good h2 { font-family: Hang, sans-serif; }\n  </style>"
                % hang.getsockname()[1])
        index.write_text(index.read_text().replace("</style>", face, 1))
        code, out, err = run_main("--slides", "good", deck=deck, SETTLE_BUDGET=2.0)
        self.assertEqual(code, deckcfg.EXIT_USAGE, out + err)
        self.assertRegex(err, r"slide good: not loaded within 2 s: font .*Hang")
        self.assertNotIn("install", err)

    def test_settle_names_only_what_is_pending_at_the_deadline(self):
        # One deadline for every wait, all started before it: a resource that
        # resolves (or fails) in time is never named, however late in the
        # list it comes; only one still pending when the deadline passes is.
        browser = geometry.Browser(*geometry.find_browser(deckcfg.load(FIXTURE)), 800, 600)
        self.addCleanup(browser.close)
        page = geometry.Page(browser, 800, 600)
        page.evaluate(pathlib.Path(geometry.PROBE_FILE).read_text())
        slow = page.evaluate(
            "geometrySettle([[new Promise(() => {}), 'never'],"
            " [new Promise(r => setTimeout(r, 150)), 'late but in time'],"
            " [Promise.reject(new Error('gone')), 'failed'],"
            " [new Promise(r => requestAnimationFrame(r)), 'a frame']], 400)")
        self.assertEqual(slow, ["never"])

    def hanging_socket(self):
        hang = socket.socket()
        hang.bind(("127.0.0.1", 0))
        hang.listen(8)                   # accepted by the kernel, never answered
        self.addCleanup(hang.close)
        return hang.getsockname()[1]

    def deck_copy(self, edit):
        """A copy of the fixture with index.html passed through edit()."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        deck = os.path.join(tmp, "geodeck")
        shutil.copytree(FIXTURE, deck)
        index = pathlib.Path(deck, "index.html")
        index.write_text(edit(index.read_text()))
        return deck

    def test_fonts_are_loaded_for_pseudo_content_and_by_stretch(self):
        # Named by face, not left to document.fonts.ready: a face used only by
        # ::after content, and a condensed face beside a normal one.
        port = self.hanging_socket()
        cases = {
            "pseudo": ("@font-face { font-family: HangPseudo; src: url(http://127.0.0.1:%d/p.woff2); }"
                       " #good .wrap::after { content: 'x'; font-family: HangPseudo; }",
                       r"font [^;]*HangPseudo"),
            "stretch": ("@font-face { font-family: Wide; src: local(Nope); }"
                        " @font-face { font-family: Wide; font-stretch: 75%%;"
                        " src: url(http://127.0.0.1:%d/c.woff2); }"
                        " #good h2 { font-family: Wide; font-stretch: condensed; }",
                        r"font [^;]*condensed [^;]*Wide"),
        }
        for name, (css, pattern) in cases.items():
            with self.subTest(case=name):
                deck = self.deck_copy(lambda html: html.replace(
                    "</style>", (css % port) + "\n  </style>", 1))
                code, out, err = run_main("--slides", "good", deck=deck, SETTLE_BUDGET=2.0)
                self.assertEqual(code, deckcfg.EXIT_USAGE, out + err)
                self.assertRegex(err, pattern)

    def test_media_beyond_img_and_backgrounds_is_awaited(self):
        # An svg <image>, a mask-image and a video poster that never answer.
        port = self.hanging_socket()
        base = f"http://127.0.0.1:{port}"
        markup = (f'<svg width="10" height="10"><image href="{base}/svg.png" width="10" '
                  f'height="10"/></svg><div style="width:10px;height:10px;'
                  f'mask-image:url({base}/mask.png)"></div>'
                  f'<video poster="{base}/poster.png" preload="none"></video>')
        deck = self.deck_copy(lambda html: html.replace(
            '<p class="fragment note">', markup + '<p class="fragment note">', 1))
        code, out, err = run_main("--slides", "good", deck=deck, SETTLE_BUDGET=2.0)
        self.assertEqual(code, deckcfg.EXIT_USAGE, out + err)
        for what in ("svg image", "mask", "poster"):
            self.assertIn(f"{what} {base}/", err)

    def slow_server(self, delay):
        """A threaded server that answers every request with bright.png after
        `delay` seconds, uncacheable. Returns its port."""
        body = pathlib.Path(FIXTURE, "media", "bright.png").read_bytes()

        class Slow(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(delay)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_a_slow_slide_background_is_awaited_before_it_is_measured(self):
        # 3 s late, inside a 10 s budget: measured once it is painted, so the
        # white type on it fails.
        port = self.slow_server(3)
        deck = self.deck_copy(lambda html: html.replace(
            'data-background-image="media/bright.png"',
            f'data-background-image="http://127.0.0.1:{port}/bright.png"'))
        code, out, err = run_main("--slides", "bright-bg", "--json", deck=deck,
                                  SETTLE_BUDGET=10.0)
        self.assertEqual(code, deckcfg.EXIT_FAIL, out + err)
        self.assertIn("ERROR bright-bg text-contrast  .on-bright", out)

    def test_a_slide_background_that_never_answers_is_named(self):
        port = self.hanging_socket()
        deck = self.deck_copy(lambda html: html.replace(
            'data-background-image="media/bright.png"',
            f'data-background-image="http://127.0.0.1:{port}/bright.png"'))
        code, out, err = run_main("--slides", "bright-bg", deck=deck, SETTLE_BUDGET=2.0)
        self.assertEqual(code, deckcfg.EXIT_USAGE, out + err)
        self.assertIn("background http://127.0.0.1:", err)


if __name__ == "__main__":
    unittest.main()
