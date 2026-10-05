#!/usr/bin/env python3
"""Geometry gate: measure the rendered slides and fail on collisions.

Usage: python3 geometry.py <deck-dir> [--slides id,...] [--json] [--config PATH]
       (or `deckkit geometry <deck>`)

Screenshots miss the defect this targets: two labels whose captions have no
max-width and no panel, anchored close together, so their text runs into each
other. A reviewer sees it only when looking at the right slide at full size.
This drives headless Chrome over the deck, measures every text line and marker
in canvas pixels (geometry_probe.js), measures each text's contrast against
the pixels it is rendered on, and evaluates geometry.rules.toml against the
numbers.

The driver speaks the DevTools protocol over --remote-debugging-pipe, so it
needs no node, Puppeteer or websocket library. The deck is served over http
with serve.py's handler on an ephemeral port, never file://.

Rules (ids, severities and params live in geometry.rules.toml):
   text-overlap        the ink of two text items intersects
   covers-marker       a text line sits on a marker (map pin)
   unbounded-abs-text  running text in a box that widens with its content
   text-contrast       measured WCAG contrast against the rendered backdrop
   safe-area           text outside the canvas margin (warn)
   clearance           independently placed text closer than min_gap (warn)
   clipped-text        text cut off by an overflow-hidden ancestor

A deck tunes them in deck.toml: `[geometry] disable = [ids]`, and
`[geometry.<id>]` for severity, enabled or any param.

Exit 1 on any error-severity violation; warnings alone exit 0. A browser that
is missing or dies exits 3; a config the page rejects (a bad selector), or a
font or image that does not load within the slide's settle budget, exits 2.
A text-contrast bar lowered below WCAG AA needs a `reason`, printed on every
run, and is refused at regulated rigor.
"""
from __future__ import annotations

import argparse
import fcntl
import functools
import itertools
import json
import math
import os
import pathlib
import re
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from dataclasses import asdict, dataclass

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import deckcfg  # noqa: E402
import serve  # noqa: E402

RULES_FILE = HERE / "geometry.rules.toml"
PROBE_FILE = HERE / "geometry_probe.js"
SEVERITIES = ("error", "warn")
HEADINGS = ("h1", "h2", "h3")
AA = {"min_small": 4.5, "min_large": 3.0}   # WCAG 2.x AA, text-contrast's floor
EVAL_TIMEOUT = 30.0     # s for one in-page evaluate
SETTLE_BUDGET = 20.0    # s per slide for fonts, images, backgrounds; below EVAL_TIMEOUT
HEADLESS_SHELLS = pathlib.Path.home() / ".cache" / "puppeteer" / "chrome-headless-shell"
INSTALL_HINT = ("npx @puppeteer/browsers install chrome-headless-shell@stable "
                "--path ~/.cache/puppeteer   (or set [env] chrome / DECKKIT_ENV_CHROME)")


class BrowserError(Exception):
    """The browser could not be started or used: an environment problem."""


class BrowserDied(BrowserError):
    """The browser exited or stopped answering."""


class ProtocolError(BrowserError):
    """The browser answered a command with an error (often a page mid-load)."""


class PageError(Exception):
    """Script evaluated in the page threw."""


class SlowResource(Exception):
    """A font or image did not settle within SETTLE_BUDGET: the slide cannot
    be measured as it would render."""


@dataclass
class Violation:
    slide: str
    rule: str
    severity: str
    subject: str
    detail: str

    def line(self) -> str:
        return f"{self.severity.upper()} {self.slide} {self.rule}  {self.subject}  ({self.detail})"


# ===================================================================== rules
#
# Pure: probe JSON + resolved rules -> violations. No browser, so the tests
# exercise every rule on canned probe output.

def ink_lines(lines: list[dict], font_size: float) -> list[dict]:
    """Line rects trimmed to the em box. A Range rect is the font's content
    area (ascent + descent + line gap), taller than the glyphs; ink sits within
    the em, so two stacked lines whose content areas touch do not collide."""
    out = []
    for line in lines:
        if line["h"] > font_size:
            line = {**line, "y": line["y"] + (line["h"] - font_size) / 2, "h": font_size}
        out.append(line)
    return out


class Slide:
    """The probe's node table with the ancestor walks the rules share."""

    def __init__(self, probe: dict):
        self.probe = probe
        self.el = probe["elements"]
        self.texts = probe["texts"]

    def chain(self, node: int) -> list[int]:
        """Ancestors, nearest first, excluding the node itself and the section."""
        out = []
        parent = self.el[node]["parent"]
        while parent is not None:
            out.append(parent)
            parent = self.el[parent]["parent"]
        return out

    def up(self, node: int) -> list[int]:
        return [node, *self.chain(node)]

    def positioned(self, node: int) -> bool:
        return self.el[node]["position"] in ("absolute", "fixed")

    def nested(self, a: int, b: int) -> bool:
        """Is one item inside the other's flow? An absolutely positioned
        descendant (a badge on a card title) is placed on its own, so it is
        not nested in that sense and still counts."""
        for outer, inner in ((a, b), (b, a)):
            if outer == inner:
                return True
            path = self.up(inner)
            if outer in path:
                return not any(self.positioned(n) for n in path[:path.index(outer)])
        return False

    def one_flow(self, a: int, b: int) -> bool:
        """Are these two items lines or boxes the layout engine stacked in one
        formatting context? Then they cannot collide, however tight the
        leading: a display headline at line-height .85 overlaps its em boxes
        by design. The test: below their nearest common ancestor, no box on
        either path is positioned or displaced (a float, a transform, a
        relative offset, a negative margin, content spilling out of a fixed
        size: the probe's `displaced`), and the two branches under that
        ancestor are inline content of one line run, or boxes that do not
        intersect (grid items placed in one cell do). SVG text is placed by
        coordinates and is never one flow."""
        if self.svg(a) is not None or self.svg(b) is not None:
            return False
        up_a, up_b = self.up(a), self.up(b)
        common = next((n for n in up_a if n in up_b), None)
        if common in (a, b):
            return False                 # nested: nested() decides
        branch_a = up_a[:up_a.index(common)] if common is not None else up_a
        branch_b = up_b[:up_b.index(common)] if common is not None else up_b
        if any(self.positioned(n) or self.el[n].get("displaced")
               for n in branch_a + branch_b):
            return False
        top_a, top_b = branch_a[-1], branch_b[-1]
        if "inline" in (self.el[top_a]["display"], self.el[top_b]["display"]):
            return True
        w, h = intersect(self.el[top_a]["box"], self.el[top_b]["box"])
        return not (w > 0.5 and h > 0.5)

    def root(self, node: int) -> int | None:
        """Nearest absolutely or fixed positioned ancestor-or-self; None = the section."""
        return next((n for n in self.up(node) if self.positioned(n)), None)

    def svg(self, node: int) -> int | None:
        return next((n for n in self.up(node) if self.el[n]["tag"] == "svg"), None)

    def flow_root(self, node: int) -> int | None:
        """What lays this text out: the nearest positioned box, or inside an
        svg the <text> element itself (svg text is placed by coordinates)."""
        chain = self.up(node)
        if self.svg(node) is not None:
            return next((n for n in chain if self.el[n]["tag"] == "text"), node)
        return self.root(node)

    def heading(self, node: int) -> bool:
        return any(self.el[n]["tag"] in HEADINGS for n in self.up(node))

    def large(self, node: int, p: dict) -> bool:
        """WCAG large text: at least large_px, or large_bold_px at bold weight."""
        e = self.el[node]
        return e["fontSize"] >= p["large_px"] or (
            e["fontSize"] >= p["large_bold_px"] and e["fontWeight"] >= p["bold_weight"])

    def ink(self, t: dict) -> list[dict]:
        return ink_lines(t["lines"], self.el[t["node"]]["fontSize"])

    def paints_panel(self, node: int, min_alpha: float) -> bool:
        """Does the element (or its ::before/::after) paint a background at
        least min_alpha opaque: a color, or a gradient whose strongest stop is?"""
        for color, image in self.el[node]["paints"]:
            if alpha(color) >= min_alpha:
                return True
            for layer in split_layers(image):
                if "gradient(" in layer and gradient_alpha(layer) >= min_alpha:
                    return True
        return False

    def path(self, node: int) -> str:
        """Short selector for output: the node's token and its parent's."""
        tokens = [self.el[node]["token"]]
        parent = self.el[node]["parent"]
        if not tokens[0].startswith("#") and parent is not None:
            tokens.insert(0, self.el[parent]["token"])
        return " ".join(tokens)


COLOR_RE = re.compile(r"rgba?\([^)]*\)|color\([^)]*\)|transparent")


def alpha(color: str) -> float:
    """Alpha of a computed color: rgb() is opaque, rgba()/'/ a' carry it."""
    color = color.strip()
    if color in ("", "transparent", "none"):
        return 0.0
    if "/" in color:
        tail = color.rsplit("/", 1)[1].strip(" )")
        return float(tail[:-1]) / 100 if tail.endswith("%") else float(tail)
    nums = re.findall(r"[-\d.]+", color)
    if color.startswith("rgba") and len(nums) == 4:
        return float(nums[3])
    return 1.0


def split_layers(image: str) -> list[str]:
    """A computed background-image list, split on its top-level commas."""
    layers, depth, start = [], 0, 0
    for i, ch in enumerate(image):
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            layers.append(image[start:i].strip())
            start = i + 1
    layers.append(image[start:].strip())
    return [layer for layer in layers if layer and layer != "none"]


def gradient_alpha(layer: str) -> float:
    """The strongest stop of a gradient: a panel is judged where it is darkest."""
    stops = COLOR_RE.findall(layer)
    return max((alpha(c) for c in stops), default=1.0)


def intersect(a: dict, b: dict) -> tuple[float, float]:
    w = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    h = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    return (w, h) if w > 0 and h > 0 else (0.0, 0.0)


def gap(a: dict, b: dict) -> float:
    dx = max(0.0, b["x"] - (a["x"] + a["w"]), a["x"] - (b["x"] + b["w"]))
    dy = max(0.0, b["y"] - (a["y"] + a["h"]), a["y"] - (b["y"] + b["h"]))
    return math.hypot(dx, dy)


def worst_overlap(lines_a: list, lines_b: list) -> tuple[float, float]:
    best = (0.0, 0.0)
    for a, b in itertools.product(lines_a, lines_b):
        w, h = intersect(a, b)
        if w * h > best[0] * best[1]:
            best = (w, h)
    return best


def px(w: float, h: float) -> str:
    return f"{round(w)}x{round(h)} px"


def pair(s: Slide, a: dict, b: dict) -> str:
    return f"{s.path(a['node'])} x {s.path(b['node'])}"


def _texts(s: Slide, rule: str) -> list[dict]:
    return [t for t in s.texts if rule not in t.get("exempt", [])]


def rule_text_overlap(s: Slide, p: dict, rid: str):
    # In flow or not: a fixed-height card that overflows, a negative margin,
    # a transform or two grid items in one cell all stack ink. Skipped: an
    # item and what is nested in its own flow, and lines one flow stacked
    # (Slide.one_flow), whose em boxes may overlap by the font's design.
    for a, b in itertools.combinations(_texts(s, rid), 2):
        if s.nested(a["node"], b["node"]) or s.one_flow(a["node"], b["node"]):
            continue
        w, h = worst_overlap(s.ink(a), s.ink(b))
        if w * h > p["min_area"] and min(w, h) >= p["min_depth"]:
            yield pair(s, a, b), px(w, h)


def rule_covers_marker(s: Slide, p: dict, rid: str):
    for t in _texts(s, rid):
        for m in s.probe["markers"]:
            if s.nested(t["node"], m["node"]):
                continue
            w, h = worst_overlap(t["lines"], [m["box"]])
            if w * h > p["min_area"]:
                yield f"{s.path(t['node'])} on {s.path(m['node'])}", px(w, h)


def rule_unbounded_abs_text(s: Slide, p: dict, rid: str):
    # Running text needs a declared measure. The probe measured it: the text
    # was shortened and lengthened, and its positioned box changed width with
    # it ("content") and, lengthened, ran to the containing block's edge
    # ("edge") instead of stopping at a max-width, width or insets. Headings
    # and short labels (kickers, names) set their own width by design.
    widest: dict[int, tuple[float, dict]] = {}
    for t in _texts(s, rid):
        fit = t.get("fit")
        if not fit or not (fit["content"] and fit["edge"]):
            continue
        if t.get("chars", 0) <= p["label_chars"] or s.heading(t["node"]):
            continue
        root = s.root(t["node"])
        w = max(line["w"] for line in t["lines"])
        if root is not None and (root not in widest or w > widest[root][0]):
            widest[root] = (w, t)
    for root, (w, t) in widest.items():
        size = s.el[t["node"]]["fontSize"]
        yield (s.path(root), f"width set by content, up to the container's edge; "
                             f"{s.path(t['node'])} ({round(size)} px text) runs {round(w)} px wide")


def rule_text_contrast(s: Slide, p: dict, rid: str):
    # Judged on pixels: the backdrop was screenshotted with every glyph made
    # invisible (text-shadows kept, they are part of what the glyph sits on),
    # and the text's color was composited over each backdrop pixel under its
    # ink. A low percentile, so a few stray dots do not fail a line but a band
    # of bad backdrop does.
    pct = p["percentile"]
    for t in _texts(s, rid):
        quantiles = t.get("contrast")
        if not quantiles:
            continue
        ratio = quantiles[pct]
        node = t["node"]
        need = p["min_large"] if s.large(node, p) else p["min_small"]
        if ratio < need:
            size = round(s.el[node]["fontSize"])
            yield s.path(node), (f"{ratio:.2f}:1 at the {pct}th percentile, needs "
                                 f"{need}:1 for {size} px text")


def rule_safe_area(s: Slide, p: dict, rid: str):
    margin = p["margin"]
    if margin == "auto":
        token = s.probe.get("margin")
        margin = p["fallback_margin"] if token is None else token
    width, height = s.probe["canvas"]["w"], s.probe["canvas"]["h"]
    for t in _texts(s, rid):
        sides = {"left": 0.0, "top": 0.0, "right": 0.0, "bottom": 0.0}
        for line in t["lines"]:
            sides["left"] = max(sides["left"], margin - line["x"])
            sides["top"] = max(sides["top"], margin - line["y"])
            sides["right"] = max(sides["right"], line["x"] + line["w"] - (width - margin))
            sides["bottom"] = max(sides["bottom"], line["y"] + line["h"] - (height - margin))
        breached = {side: depth for side, depth in sides.items()
                    if depth > p["tolerance"] and not edge_panel(s, t["node"], side, p)}
        if breached:
            side, depth = max(breached.items(), key=lambda kv: kv[1])
            yield s.path(t["node"]), f"{round(depth)} px into the {round(margin)} px {side} margin"


def edge_panel(s: Slide, node: int, side: str, p: dict) -> bool:
    """Is the text on a painted panel whose own box hugs the canvas edge it is
    near (a side column, a band)? That panel sets its own inset. A full-canvas
    panel (an inset: 0 wrapper) hugs every edge and so excuses none."""
    width, height = s.probe["canvas"]["w"], s.probe["canvas"]["h"]
    for n in s.up(node):
        b = s.el[n]["box"]
        if b["w"] >= width - 2 and b["h"] >= height - 2:
            continue
        hugs = {"left": b["x"] <= 1, "top": b["y"] <= 1,
                "right": b["x"] + b["w"] >= width - 1,
                "bottom": b["y"] + b["h"] >= height - 1}[side]
        if hugs and s.paints_panel(n, p["panel_alpha"]):
            return True
    return False


def rule_clearance(s: Slide, p: dict, rid: str):
    # An overlap counts as 0 px apart, for every pair text-overlap compares:
    # a shallow one it does not report lands here (evaluate() drops the pairs
    # it does report). A near miss (gap > 0) counts only between items placed
    # independently: blocks in one positioned box sit close by design, and so
    # do the labels of one svg drawing, placed against each other by
    # coordinates.
    for a, b in itertools.combinations(_texts(s, rid), 2):
        if s.nested(a["node"], b["node"]) or s.one_flow(a["node"], b["node"]):
            continue
        ink_a, ink_b = s.ink(a), s.ink(b)
        w, h = worst_overlap(ink_a, ink_b)
        if w and h:
            yield pair(s, a, b), f"ink overlaps by {px(w, h)}"
            continue
        if s.flow_root(a["node"]) == s.flow_root(b["node"]):
            continue
        if s.svg(a["node"]) is not None and s.svg(a["node"]) == s.svg(b["node"]):
            continue
        nearest = min(gap(x, y) for x, y in itertools.product(ink_a, ink_b))
        if nearest < p["min_gap"]:
            yield pair(s, a, b), f"{round(nearest, 1)} px apart"


def rule_clipped_text(s: Slide, p: dict, rid: str):
    tol = p["tolerance"]
    for c in s.probe["clipping"]:
        box, worst, culprit = c["box"], 0.0, None
        for t in _texts(s, rid):
            if c["node"] not in s.up(t["node"]):
                continue
            for line in t["lines"]:
                over = 0.0
                if c["x"]:
                    over = max(over, box["x"] - line["x"],
                               line["x"] + line["w"] - (box["x"] + box["w"]))
                if c["y"]:
                    over = max(over, box["y"] - line["y"],
                               line["y"] + line["h"] - (box["y"] + box["h"]))
                if over > worst:
                    worst, culprit = over, t
        if worst > tol:
            yield s.path(c["node"]), f"{s.path(culprit['node'])} runs {round(worst)} px past the clip"


RULES = {
    "text-overlap": rule_text_overlap,
    "covers-marker": rule_covers_marker,
    "unbounded-abs-text": rule_unbounded_abs_text,
    "text-contrast": rule_text_contrast,
    "safe-area": rule_safe_area,
    "clearance": rule_clearance,
    "clipped-text": rule_clipped_text,
}
RULE_META = ("id", "severity", "enabled")


def evaluate(probe: dict, rules: list[dict], slide: str) -> list[Violation]:
    """Apply resolved rules to one slide's probe output."""
    s = Slide(probe)
    out = []
    for rule in rules:
        if not rule["enabled"]:
            continue
        for subject, detail in RULES[rule["id"]](s, rule["params"], rule["id"]):
            out.append(Violation(slide, rule["id"], rule["severity"], subject, detail))
    overlaps = {v.subject for v in out if v.rule == "text-overlap"}
    return [v for v in out if not (v.rule == "clearance" and v.subject in overlaps)]


def exit_code(violations: list[Violation]) -> int:
    return deckcfg.EXIT_FAIL if any(v.severity == "error" for v in violations) else deckcfg.EXIT_OK


# ============================================================ rule config

def parse_rules(text: str, source: str) -> list[dict]:
    """A rules file -> [{id, severity, enabled, params}], validated."""
    try:
        tree = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise deckcfg.ConfigError(f"{source}: {exc}") from None
    rules = []
    for i, raw in enumerate(tree.get("rule", [])):
        missing = [k for k in RULE_META if k not in raw]
        if missing:
            raise deckcfg.ConfigError(f"{source}: [[rule]][{i}] is missing {', '.join(missing)}")
        if raw["id"] not in RULES:
            raise deckcfg.ConfigError(f"{source}: [[rule]] id {raw['id']!r} has no evaluator "
                                      f"(known: {', '.join(RULES)})")
        if raw["severity"] not in SEVERITIES:
            raise deckcfg.ConfigError(f"{source}: [[rule]] {raw['id']}: severity must be "
                                      f"error|warn, got {raw['severity']!r}")
        params = {k: v for k, v in raw.items() if k not in RULE_META}
        params.setdefault("exempt", [])
        rules.append({"id": raw["id"], "severity": raw["severity"],
                      "enabled": bool(raw["enabled"]), "params": params})
    return rules


def apply_overrides(rules: list[dict], deck_geometry: dict, disable: list[str],
                    source: str, rigor: str = "standard") -> list[dict]:
    """deck.toml's [geometry] on top of the rules file. Typos fail loudly: a
    misspelled rule id or param would otherwise be a silently ignored override."""
    by_id = {r["id"]: r for r in rules}
    for rid in disable:
        if rid not in by_id:
            raise deckcfg.ConfigError(f"{source}: [geometry] disable names unknown rule {rid!r}")
        by_id[rid]["enabled"] = False
    for rid, table in deck_geometry.items():
        if not isinstance(table, dict):
            continue                     # rules / slides / disable: top-level keys
        if rid not in by_id:
            raise deckcfg.ConfigError(f"{source}: [geometry.{rid}] is not a rule "
                                      f"(known: {', '.join(by_id)})")
        rule = by_id[rid]
        for key, value in table.items():
            where = f"{source}: [geometry.{rid}] {key}"
            if key == "severity":
                if value not in SEVERITIES:
                    raise deckcfg.ConfigError(f"{where} must be error|warn, got {value!r}")
                rule["severity"] = value
            elif key == "enabled":
                rule["enabled"] = bool(value)
            elif key not in rule["params"]:
                raise deckcfg.ConfigError(f"{where}: unknown param "
                                          f"(known: {', '.join(rule['params'])})")
            elif not compatible(key, value, rule["params"][key]):
                raise deckcfg.ConfigError(f"{where} must be {type(rule['params'][key]).__name__}, "
                                          f"got {type(value).__name__}")
            else:
                rule["params"][key] = value
    contrast = by_id.get("text-contrast", {}).get("params", {})
    pct = contrast.get("percentile")
    if pct is not None and not (isinstance(pct, int) and 0 <= pct <= 100):
        raise deckcfg.ConfigError(f"{source}: [geometry.text-contrast] percentile must be "
                                  f"an integer 0-100, got {pct!r}")
    lowered = lowered_contrast(rules)
    if lowered:
        where = f"{source}: [geometry.text-contrast] " + ", ".join(
            f"{k} = {contrast[k]}" for k in lowered)
        if rigor == "regulated":
            raise deckcfg.ConfigError(f"{where}: below WCAG AA "
                                      f"({', '.join(f'{k} {AA[k]}' for k in lowered)}), "
                                      "refused at regulated rigor")
        if not str(contrast.get("reason", "")).strip():
            raise deckcfg.ConfigError(f"{where}: below WCAG AA needs a non-empty `reason` "
                                      "in the same table")
    return rules


def lowered_contrast(rules: list[dict]) -> list[str]:
    """The text-contrast bars set below WCAG AA, while the rule is on."""
    rule = next((r for r in rules if r["id"] == "text-contrast"), None)
    if rule is None or not rule["enabled"]:
        return []
    return [k for k, floor in AA.items() if rule["params"].get(k, floor) < floor]


def compatible(key: str, value, default) -> bool:
    """An override keeps its param's type; ints and floats mix; `margin` also
    takes a number in place of "auto"."""
    def number(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    if key == "margin":
        return value == "auto" or number(value)
    if number(default):
        return number(value)
    return isinstance(value, type(default))


def load_rules(cfg: deckcfg.DeckConfig) -> list[dict]:
    configured = cfg.get("geometry.rules")
    path = cfg.path("geometry.rules") if configured else RULES_FILE
    if not path.exists():
        raise deckcfg.ConfigError(f"geometry.rules: {path} does not exist")
    rules = parse_rules(path.read_text(encoding="utf-8"), str(path))
    deck_geometry = cfg.tree.get("geometry", {})
    return apply_overrides(rules, deck_geometry, cfg.get("geometry.disable"), cfg.source,
                           cfg.derive_rigor())


# ================================================================ browser

def find_browser(cfg: deckcfg.DeckConfig) -> tuple[str, bool] | None:
    """(binary, is_headless_shell). env.chrome wins, then the Puppeteer cache's
    chrome-headless-shell (it runs inside the Claude Code sandbox, where full
    Chrome aborts), then whatever Chrome deckcfg finds."""
    configured = cfg.get("env.chrome")
    if configured:
        return configured, "headless-shell" in pathlib.Path(configured).name
    if HEADLESS_SHELLS.is_dir():
        def version(p: pathlib.Path):
            return tuple(int(n) for n in re.findall(r"\d+", p.parents[1].name))
        builds = sorted(HEADLESS_SHELLS.glob("*/chrome-headless-shell-linux64/chrome-headless-shell"),
                        key=version, reverse=True)
        if builds:
            return str(builds[0]), True
    chrome = deckcfg.find_chrome(cfg)
    return (chrome, False) if chrome else None


class Browser:
    """One headless Chrome over --remote-debugging-pipe: fd 3 takes commands,
    fd 4 returns responses and events, each a JSON message ending in NUL."""

    def __init__(self, binary: str, headless_shell: bool, width: int, height: int):
        self.profile = tempfile.mkdtemp(prefix="deckkit-geometry-")
        self._log = open(os.path.join(self.profile, "stderr.log"), "wb")
        cmd_r, self._cmd_w = os.pipe()
        self._out_r, out_w = os.pipe()

        def wire():
            # Lift both ends above 3/4 first, so placing one cannot clobber the
            # other, then dup2 onto the numbers Chrome reads. pass_fds must name
            # 3 and 4 themselves: naming the original numbers lets the child
            # close 3 and 4 before exec, and the session hangs.
            a = fcntl.fcntl(cmd_r, fcntl.F_DUPFD, 10)
            b = fcntl.fcntl(out_w, fcntl.F_DUPFD, 10)
            os.dup2(a, 3)
            os.dup2(b, 4)

        args = [binary, "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
                f"--window-size={width},{height}", f"--user-data-dir={self.profile}",
                "--remote-debugging-pipe"]
        if not headless_shell:
            args.insert(1, "--headless=new")
        try:
            self.proc = subprocess.Popen(args, preexec_fn=wire, pass_fds=(3, 4),
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=self._log)
        except OSError as exc:
            self._cleanup_fds(cmd_r, out_w)
            self._remove_profile()
            raise BrowserError(f"cannot start {binary}: {exc}") from None
        self._cleanup_fds(cmd_r, out_w)   # the child's ends; ours stay open
        self._buf = b""
        self._ids = itertools.count(1)

    @staticmethod
    def _cleanup_fds(*fds):
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass

    def _remove_profile(self):
        self._log.close()
        shutil.rmtree(self.profile, ignore_errors=True)

    def stderr_tail(self) -> str:
        self._log.flush()
        try:
            text = pathlib.Path(self.profile, "stderr.log").read_text(errors="replace")
        except OSError:
            return ""
        return "\n".join(text.strip().splitlines()[-5:])

    def _died(self, what: str) -> BrowserDied:
        tail = self.stderr_tail()
        return BrowserDied(what + (f":\n{tail}" if tail else ""))

    def _message(self, deadline: float) -> dict:
        while b"\0" not in self._buf:
            left = deadline - time.monotonic()
            if left <= 0:
                raise self._died("the browser stopped answering")
            ready, _, _ = select.select([self._out_r], [], [], left)
            if not ready:
                continue
            chunk = os.read(self._out_r, 1 << 20)
            if not chunk:
                raise self._died("the browser exited")
            self._buf += chunk
        raw, self._buf = self._buf.split(b"\0", 1)
        return json.loads(raw)

    def call(self, method: str, params: dict | None = None, session: str | None = None,
             timeout: float = 30.0) -> dict:
        mid = next(self._ids)
        msg = {"id": mid, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        data = json.dumps(msg).encode() + b"\0"
        try:
            while data:
                data = data[os.write(self._cmd_w, data):]
        except BrokenPipeError:
            raise self._died("the browser exited") from None
        deadline = time.monotonic() + timeout
        while True:
            reply = self._message(deadline)
            if reply.get("id") != mid:
                continue                 # an event, or a reply nobody waits for
            if "error" in reply:
                raise ProtocolError(f"{method}: {reply['error'].get('message', reply['error'])}")
            return reply.get("result", {})

    def close(self):
        try:
            self.call("Browser.close", timeout=5)
        except BrowserError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Only the process this run started, by its own handle. Other
            # sessions on the machine run Chrome too.
            self.proc.kill()
            self.proc.wait()
        self._cleanup_fds(self._cmd_w, self._out_r)
        self._remove_profile()


class Page:
    """A tab attached in flat mode; page commands carry its sessionId."""

    def __init__(self, browser: Browser, width: int, height: int):
        self.browser = browser
        target = browser.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = browser.call("Target.attachToTarget",
                                    {"targetId": target, "flatten": True})["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return self.browser.call(method, params, self.session, timeout)

    def evaluate(self, expression: str, timeout: float = EVAL_TIMEOUT):
        result = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                                "returnByValue": True}, timeout)
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = details.get("exception", {}).get("description") or details.get("text")
            raise PageError(text)
        return result["result"].get("value")


# In-page snippets. Each returns a value or a promise; Runtime.evaluate awaits it.
READY_JS = """new Promise(done => {
  const t0 = performance.now();
  (function tick() {
    if (window.Reveal && Reveal.isReady && Reveal.isReady()) return done(true);
    if (performance.now() - t0 > 1000) return done(false);
    setTimeout(tick, 50);
  })();
})"""

SLIDES_JS = """Promise.resolve(Reveal.getSlides().map(s => {
  const i = Reveal.getIndices(s);
  return {id: s.id || '', h: i.h, v: i.v || 0};
}))"""

# Selectors that cannot parse, so a config typo is named before the probe trips on it.
BAD_SELECTORS_JS = """((pairs) => pairs.filter(([, sel]) => {
  try { document.createDocumentFragment().querySelector(sel); return false; }
  catch (e) { return true; }
}))(%s)"""

# Transitions and animations off for the whole run, so every state is final
# the moment it is set: reveal's `.fragment { transition: all .2s }` would
# otherwise leave a fragment mid-fade when probed, and animate the forced
# glyph fills of the contrast shots (a transition beats !important).
STILL_JS = """(() => {
  const s = document.createElement('style');
  s.id = 'deckkit-geometry-still';
  s.textContent = '*, *::before, *::after { transition: none !important; ' +
                  'animation: none !important; }';
  document.head.appendChild(s);
  return true;
})()"""

# Go to a slide with every fragment shown (their final state), then wait for
# what it paints with: the fonts its text uses, loaded for that text (a face
# split by unicode-range loads only the subsets its characters need), its
# images, and every url() background in it, the reveal slide background
# included (reveal sets those only when the slide is reached). One deadline
# covers all of it, below the evaluate timeout, so a hang is named, not lost.
# Returns {id, slow: [what did not settle]}.
GOTO_JS = """(async (h, v, budget) => {
  const deadline = performance.now() + budget;
  const slow = [];
  const settle = (p, what) => new Promise(done => {
    const t = setTimeout(() => { slow.push(what); done(); },
                         Math.max(0, deadline - performance.now()));
    Promise.resolve(p).then(() => { clearTimeout(t); done(); },
                            () => { clearTimeout(t); done(); });
  });
  Reveal.slide(h, v);
  for (let guard = 0; guard < 500 && Reveal.nextFragment(); guard++) {}
  for (const a of document.getAnimations()) { try { a.finish(); } catch (e) { a.cancel(); } }
  const sec = Reveal.getCurrentSlide();
  const face = cs => `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
  const faces = new Map();
  for (const el of [sec, ...sec.querySelectorAll('*')]) {
    const f = face(getComputedStyle(el));
    let text = faces.get(f) || '';
    for (const n of el.childNodes) if (n.nodeType === Node.TEXT_NODE) text += n.nodeValue;
    faces.set(f, text);
  }
  await Promise.all([...faces].map(([f, text]) =>
    settle(document.fonts.load(f, [...new Set(text.replace(/\\s/g, ''))].join('') || ' '),
           `font ${f}`)));
  await settle(document.fonts.ready, 'document.fonts.ready');
  const painted = [sec, ...sec.querySelectorAll('*')];
  const bg = Reveal.getSlideBackground ? Reveal.getSlideBackground(h, v) : null;
  if (bg) painted.push(bg, ...bg.querySelectorAll('*'));
  const urls = new Set();
  for (const el of painted) {
    for (const pseudo of [null, '::before', '::after']) {
      const image = getComputedStyle(el, pseudo).backgroundImage;
      for (const m of image.matchAll(/url\\((['"]?)(.*?)\\1\\)/g)) urls.add(m[2]);
    }
  }
  const decoded = src => { const img = new Image(); img.src = src; return img.decode(); };
  await Promise.all([
    ...[...sec.querySelectorAll('img')].map(img =>
      settle(img.decode().catch(() => null), `image ${img.currentSrc || img.src}`)),
    ...[...urls].map(u => settle(decoded(u).catch(() => null), `background ${u}`)),
  ]);
  const frame = () => settle(new Promise(r => requestAnimationFrame(r)), 'a rendered frame');
  await frame(); await frame();
  return { id: sec.id, slow };
})(%d, %d, %d)"""

# Glyphs painted in one forced fill (black, white, or transparent to hide
# them), everything else kept: text-shadows, group opacity, overlays, and an
# SVG halo (a stroke that paint-order puts under the fill). The fill color is
# what paints glyphs; `color` stays, so borders, currentColor icons and
# default-colored shadows are untouched. SVG text paints with `fill`, on
# text, tspan and textPath alike (each may set its own); a stroke painted
# over the fill is part of the glyph and is hidden with it.
FILL_JS = """(async (fill) => {
  const sec = Reveal.getCurrentSlide();
  for (const el of sec.querySelectorAll('text, tspan, textPath')) {
    const order = getComputedStyle(el).paintOrder.split(/\\s+/).filter(k => k !== 'normal');
    for (const k of ['fill', 'stroke', 'markers']) if (!order.includes(k)) order.push(k);
    el.toggleAttribute('data-deckkit-glyph-stroke', order.indexOf('stroke') > order.indexOf('fill'));
  }
  const s = document.getElementById('deckkit-geometry-fill') || document.createElement('style');
  s.id = 'deckkit-geometry-fill';
  const at = '.reveal .slides section.present';
  s.textContent = `${at}, ${at} * { -webkit-text-fill-color: ${fill} !important; ` +
    'caret-color: transparent !important; }' +
    `${at} text, ${at} tspan, ${at} textPath { fill: ${fill} !important; ` +
    'fill-opacity: 1 !important; }' +
    `${at} [data-deckkit-glyph-stroke] { stroke: transparent !important; }`;
  document.head.appendChild(s);
  for (let i = 0; i < 2; i++) await new Promise(r => requestAnimationFrame(r));
  return true;
})(%s)"""
UNFILL_JS = """((document.getElementById('deckkit-geometry-fill') || {remove() {}}).remove(),
  document.querySelectorAll('[data-deckkit-glyph-stroke]')
    .forEach(el => el.removeAttribute('data-deckkit-glyph-stroke')), true)"""


class QuietServer(serve.ReusableServer):
    """Chrome drops connections it no longer needs (an image it has, a video
    it will not play); the resulting reset is not worth a traceback."""

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            super().handle_error(request, client_address)


def slide_label(entry: dict) -> str:
    if entry["id"]:
        return entry["id"]
    return f"{entry['h'] + 1}" + (f".{entry['v'] + 1}" if entry["v"] else "")


def measure_contrast(page: Page, probe: dict) -> None:
    """Screenshot the canvas three times, glyphs forced black, white, and
    invisible, then let the page compare each text's color with the backdrop
    where its glyphs paint. Adds `contrast` (101 quantiles of the per-pixel
    WCAG ratio, or None) to every text item."""
    items = [{"lines": ink_lines(t["lines"], probe["elements"][t["node"]]["fontSize"]),
              "color": t["color"]} for t in probe["texts"]]
    if not items:
        return
    origin = probe["origin"]
    clip = {"x": origin["x"], "y": origin["y"], "width": origin["w"], "height": origin["h"],
            "scale": 1}

    def shot() -> str:
        data = page.call("Page.captureScreenshot", {"format": "png", "clip": clip})["data"]
        return json.dumps("data:image/png;base64," + data)

    shots = []
    try:
        for fill in ("#000", "#fff", "transparent"):
            page.evaluate(FILL_JS % json.dumps(fill))
            shots.append(shot())
    finally:
        page.evaluate(UNFILL_JS)
    ratios = page.evaluate(f"geometryContrast({', '.join(shots)}, {json.dumps(items)}, "
                           f"{probe['scale']})", timeout=60)
    for t, q in zip(probe["texts"], ratios):
        t["contrast"] = q


def measure(cfg: deckcfg.DeckConfig, browser_info: tuple[str, bool], wanted: list[str],
            rules: list[dict]) -> tuple[list[str], dict[str, dict]]:
    """Serve the deck, drive Chrome over it, return (slide order, probe per slide)."""
    width, height = cfg.canvas
    index = cfg.get("build.index")
    if not (cfg.deck / index).exists():
        raise deckcfg.ConfigError(f"{cfg.deck / index} does not exist (run deckkit build)")
    by_id = {r["id"]: r for r in rules}
    opts = {
        "markers": by_id["covers-marker"]["params"]["markers"] if "covers-marker" in by_id else [],
        "exempt": {r["id"]: r["params"]["exempt"] for r in rules if r["params"]["exempt"]},
    }
    selectors = [("[geometry.covers-marker] markers", sel) for sel in opts["markers"]]
    selectors += [(f"[geometry.{rid}] exempt", sel)
                  for rid, sels in opts["exempt"].items() for sel in sels]
    probe_src = PROBE_FILE.read_text(encoding="utf-8")

    # The browser starts before the server thread: Popen's preexec_fn is only
    # safe while the process has a single thread.
    browser = Browser(*browser_info, width, height)
    server = None
    try:
        handler = functools.partial(serve.RangeHandler, directory=str(cfg.deck))
        server = QuietServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        page = Page(browser, width, height)
        url = f"http://127.0.0.1:{server.server_address[1]}/{index}?export"
        page.call("Page.navigate", {"url": url})
        deadline = time.monotonic() + 30
        while True:
            try:
                if page.evaluate(READY_JS):
                    break
            except (ProtocolError, PageError):
                time.sleep(0.1)          # the context was replaced mid-load: retry
            if time.monotonic() > deadline:
                raise deckcfg.ConfigError(f"{url}: Reveal never became ready in 30 s "
                                          "(does index.html load vendor/reveal?)")

        bad = page.evaluate(BAD_SELECTORS_JS % json.dumps(selectors))
        if bad:
            raise deckcfg.ConfigError("; ".join(f"{key}: invalid CSS selector {sel!r}"
                                                for key, sel in bad))
        page.evaluate(probe_src)         # defines geometryProbe and geometryContrast
        page.evaluate(STILL_JS)

        slides = page.evaluate(SLIDES_JS)
        labels = [slide_label(s) for s in slides]
        unknown = [w for w in wanted if w not in labels]
        if unknown:
            raise deckcfg.ConfigError(f"--slides: no slide {', '.join(map(repr, unknown))} "
                                      f"(have: {', '.join(labels)})")
        contrast = by_id.get("text-contrast", {}).get("enabled", False)
        order, probes = [], {}
        for entry, label in zip(slides, labels):
            if wanted and label not in wanted:
                continue
            settled = page.evaluate(GOTO_JS % (entry["h"], entry["v"], SETTLE_BUDGET * 1000))
            if settled["slow"]:
                raise SlowResource(f"slide {label}: not loaded within {SETTLE_BUDGET:g} s: "
                                   + "; ".join(settled["slow"]))
            probe = page.evaluate(f"geometryProbe({json.dumps(opts)})")
            if contrast:
                measure_contrast(page, probe)
            probes[label] = probe
            order.append(label)
        return order, probes
    finally:
        browser.close()
        if server is not None:
            server.shutdown()
            server.server_close()


# =================================================================== main

def main() -> int:
    parser = argparse.ArgumentParser(description="Geometry gate: overlap, overflow, clearance")
    deckcfg.add_common_args(parser)
    parser.add_argument("--slides", help="comma-separated slide ids (default: all, "
                                         "or [geometry] slides)")
    args = parser.parse_args()

    cfg = deckcfg.load(args.deck, args.config)
    if args.slides is not None:
        cfg.set("geometry.slides", [s.strip() for s in args.slides.split(",") if s.strip()])
    rules = load_rules(cfg)
    lowered = lowered_contrast(rules)
    if lowered:
        params = next(r for r in rules if r["id"] == "text-contrast")["params"]
        print(f"geometry: text-contrast below WCAG AA "
              f"({', '.join(f'{k} {params[k]}' for k in lowered)}): {params['reason']}")

    found = find_browser(cfg)
    if found is None:
        print("environment: no headless Chrome found", file=sys.stderr)
        print(f"  install: {INSTALL_HINT}", file=sys.stderr)
        return deckcfg.EXIT_ENV
    try:
        order, probes = measure(cfg, found, cfg.get("geometry.slides"), rules)
    except BrowserError as exc:
        print(f"environment: {found[0]}: {exc}", file=sys.stderr)
        print(f"  install a working one: {INSTALL_HINT}", file=sys.stderr)
        return deckcfg.EXIT_ENV
    except PageError as exc:
        deckcfg.bail(f"the probe failed in the page: {exc}")
    except SlowResource as exc:
        deckcfg.bail(str(exc))

    violations: list[Violation] = []
    per_slide = {}
    for label in order:
        found_here = evaluate(probes[label], rules, label)
        violations += found_here
        per_slide[label] = {"errors": sum(v.severity == "error" for v in found_here),
                            "warnings": sum(v.severity == "warn" for v in found_here)}

    errors = sum(v.severity == "error" for v in violations)
    warnings = len(violations) - errors
    for v in violations:
        print(v.line())
    print(f"geometry: {errors} errors, {warnings} warnings on {len(order)} slides")

    code = exit_code(violations)
    if args.json:
        print(json.dumps({"errors": errors, "warnings": warnings, "slides": per_slide,
                          "violations": [asdict(v) for v in violations], "exit": code}))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except deckcfg.ConfigError as exc:
        deckcfg.bail(str(exc))
