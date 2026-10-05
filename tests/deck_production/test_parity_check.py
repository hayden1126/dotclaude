"""skills/deck-production/scripts/parity_check.py: the geometry facts that
`deckkit regress` holds as a golden (stdlib only, no browser).

geometry.py's output is stubbed: these pin what the golden keeps (counts per
slide and rule, totals, the exit code), what it never keeps (ratios, subjects,
steps), and that a run without a browser is recorded rather than crashing."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "skills", "deck-production", "scripts", "parity_check.py")

_spec = importlib.util.spec_from_file_location("parity_check", SCRIPT)
parity_check = importlib.util.module_from_spec(_spec)
sys.modules["parity_check"] = parity_check
_spec.loader.exec_module(parity_check)


def violation(slide, rule, severity, detail="4.12:1 < 4.5", step=""):
    return {"slide": slide, "rule": rule, "severity": severity,
            "subject": ".wrap .caption", "detail": detail, "step": step}


def geometry_output(violations, slides, code):
    """What geometry.py --json prints: one line per violation, the summary,
    then the JSON object on the last line."""
    errors = sum(v["severity"] == "error" for v in violations)
    payload = {"errors": errors, "warnings": len(violations) - errors,
               "slides": slides, "violations": violations, "exit": code}
    lines = [f"{v['severity'].upper()} {v['slide']} {v['rule']}  {v['subject']}  ({v['detail']})"
             for v in violations]
    lines.append(f"geometry: {errors} errors, {len(violations) - errors} warnings "
                 f"on {len(slides)} slides")
    lines.append(json.dumps(payload))
    return "\n".join(lines) + "\n"


SLIDES = {"s01": {"errors": 0, "warnings": 0}, "s02": {"errors": 2, "warnings": 1},
          "s03": {"errors": 1, "warnings": 0}}
VIOLATIONS = [
    violation("s02", "text-contrast", "error"),
    violation("s02", "text-contrast", "error", detail="2.94:1 < 4.5", step="2/3"),
    violation("s02", "clearance", "warn", detail="5 px apart"),
    violation("s03", "text-overlap", "error", detail="31x18 px"),
]


class GeometryFacts(unittest.TestCase):
    def test_counts_per_slide_and_rule_with_totals_and_exit(self):
        facts = parity_check.geometry_facts(1, geometry_output(VIOLATIONS, SLIDES, 1))
        self.assertEqual(facts, {
            "slides": {
                "s01": {},
                "s02": {"text-contrast": {"errors": 2, "warnings": 0},
                        "clearance": {"errors": 0, "warnings": 1}},
                "s03": {"text-overlap": {"errors": 1, "warnings": 0}},
            },
            "errors": 3, "warnings": 1, "exit": 1,
        })

    def test_readings_that_move_across_renders_never_reach_the_golden(self):
        moved = [dict(v, detail=v["detail"].replace("4.12", "4.13").replace("2.94", "2.95"))
                 for v in VIOLATIONS]
        a = parity_check.geometry_facts(1, geometry_output(VIOLATIONS, SLIDES, 1))
        b = parity_check.geometry_facts(1, geometry_output(moved, SLIDES, 1))
        self.assertEqual(a, b)
        text = json.dumps(a)
        for leaked in ("4.12", "2/3", ".caption", "31x18"):
            self.assertNotIn(leaked, text)

    def test_a_clean_run_records_every_slide(self):
        clean = {label: {"errors": 0, "warnings": 0} for label in SLIDES}
        facts = parity_check.geometry_facts(0, geometry_output([], clean, 0))
        self.assertEqual(facts, {"slides": {"s01": {}, "s02": {}, "s03": {}},
                                 "errors": 0, "warnings": 0, "exit": 0})

    def test_no_browser_records_the_exit_code_alone(self):
        out = ("environment: no headless Chrome found\n"
               "  install: npx @puppeteer/browsers install chrome-headless-shell@stable\n")
        self.assertEqual(parity_check.geometry_facts(3, out), {"exit": 3})
        self.assertEqual(parity_check.geometry_facts(3, ""), {"exit": 3})

    def test_a_config_error_records_the_exit_code_alone(self):
        out = "error: deck.toml: [geometry] disable names unknown rule 'overlap'\n"
        self.assertEqual(parity_check.geometry_facts(2, out), {"exit": 2})

    def test_stderr_after_the_report_does_not_hide_it(self):
        out = geometry_output(VIOLATIONS, SLIDES, 1) + "a stray stderr line\n"
        self.assertEqual(parity_check.geometry_facts(1, out)["errors"], 3)

    def test_the_golden_diff_shows_a_lost_browser(self):
        golden = parity_check.geometry_facts(1, geometry_output(VIOLATIONS, SLIDES, 1))
        diffs = parity_check.compare({"geometry": {"exit": 3}}, {"geometry": golden})
        self.assertIn("geometry.exit: golden 1 != observed 3", diffs)
        self.assertTrue(any(d.startswith("geometry.slides: missing") for d in diffs))


class CollectRunsGeometry(unittest.TestCase):
    """collect() runs geometry.py on the reference deck with the parity
    config and --json, and stores its facts; the other tools are stubbed."""

    def fake_run(self, argv, timeout=600):
        self.calls.append(argv)
        script = pathlib.Path(argv[0]).name
        if script == "build.py":
            return 0, json.dumps({"rows": 3, "built": 3, "sha256": "ab", "would_change": False})
        if script == "lint.py":
            return 0, "lint: 0 errors, 0 warnings, 0 FLAG\n"
        if script == "package.py":
            return 0, json.dumps({"note_blocks_stripped": 0, "byte_delta": 0})
        if script == "geometry.py":
            if isinstance(self.geometry_result, Exception):
                raise self.geometry_result
            return self.geometry_result
        raise AssertionError(f"unexpected tool {script}")

    def collect(self, geometry_result):
        self.calls = []
        self.geometry_result = geometry_result
        with tempfile.TemporaryDirectory() as tmp:
            ref, config = pathlib.Path(tmp, "ref"), pathlib.Path(tmp, "parity.toml")
            ref.mkdir()
            with mock.patch.object(parity_check, "run", self.fake_run):
                facts = parity_check.collect(ref, config, pathlib.Path(tmp, "work"))
            geometry_calls = [c for c in self.calls if c[0].endswith("geometry.py")]
            self.assertEqual(geometry_calls,
                             [[str(parity_check.SCRIPTS / "geometry.py"), str(ref),
                               "--config", str(config), "--json"]])
        return facts

    def test_geometry_facts_are_collected(self):
        facts = self.collect((1, geometry_output(VIOLATIONS, SLIDES, 1)))
        self.assertEqual(facts["geometry"]["errors"], 3)
        self.assertEqual(facts["geometry"]["slides"]["s03"],
                         {"text-overlap": {"errors": 1, "warnings": 0}})
        self.assertIn("geometry 3 errors, 1 warnings on 3 slides",
                      parity_check.geometry_line(facts))

    def test_geometry_gets_its_own_longer_timeout(self):
        """Patches subprocess.run, not run(), so the timeout is checked where
        it takes effect: what run() hands the child process."""
        self.assertEqual(parity_check.GEOMETRY_TIMEOUT, 1800)
        outputs = {
            "build.py": json.dumps({"rows": 3, "built": 3, "sha256": "ab",
                                    "would_change": False}),
            "lint.py": "lint: 0 errors, 0 warnings, 0 FLAG\n",
            "package.py": json.dumps({"note_blocks_stripped": 0, "byte_delta": 0}),
            "geometry.py": geometry_output([], {"s01": {}}, 0),
        }
        timeouts: dict[str, list] = {}

        def fake_subprocess_run(argv, **kwargs):
            script = pathlib.Path(argv[1]).name
            timeouts.setdefault(script, []).append(kwargs.get("timeout"))
            return subprocess.CompletedProcess(argv, 0, stdout=outputs[script], stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            ref, config = pathlib.Path(tmp, "ref"), pathlib.Path(tmp, "parity.toml")
            ref.mkdir()
            with mock.patch.object(parity_check.subprocess, "run", fake_subprocess_run):
                facts = parity_check.collect(ref, config, pathlib.Path(tmp, "work"))
        self.assertEqual(facts["geometry"]["exit"], 0)
        self.assertEqual(timeouts["geometry.py"], [1800])
        self.assertEqual(timeouts["build.py"], [600])
        self.assertEqual(timeouts["lint.py"], [600])
        self.assertEqual(timeouts["package.py"], [600, 600])

    def test_a_geometry_timeout_is_recorded_not_raised(self):
        facts = self.collect(subprocess.TimeoutExpired(["geometry.py"], 1800))
        self.assertEqual(facts["geometry"], {"exit": "timeout"})
        self.assertIn("not measured (exit timeout)", parity_check.geometry_line(facts))

    def test_no_browser_does_not_crash_the_harness(self):
        facts = self.collect((3, "environment: no headless Chrome found\n"))
        self.assertEqual(facts["geometry"], {"exit": 3})
        self.assertIn("not measured (exit 3)", parity_check.geometry_line(facts))


if __name__ == "__main__":
    unittest.main()
