"""skills/deck-production/scripts/doctor.py: the exit code (stdlib only, no
browser).

Every probe of the machine is stubbed, so these pin the doctor's verdict, not
what this machine has installed. The geometry gate's 0/0 is part of every exit
gate from phase C on, so no browser for it is a core gap (exit 3), while full
Chrome in place of the headless shell is an optional one (exit 0)."""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "skills", "deck-production", "scripts", "doctor.py")

_spec = importlib.util.spec_from_file_location("doctor", SCRIPT)
doctor = importlib.util.module_from_spec(_spec)
sys.modules["doctor"] = doctor
_spec.loader.exec_module(doctor)

FINE = {"state": doctor.OK, "detail": "stubbed"}


class DoctorExit(unittest.TestCase):
    """Outcome x geometry browser: missing, headless shell, full Chrome, each
    with and without --json, and with the fonts python broken."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.deck = pathlib.Path(self.tmp.name, "deck")
        self.deck.mkdir()
        self.browser = pathlib.Path(self.tmp.name, "chrome-headless-shell")
        self.browser.write_text("")

    def run_doctor(self, found_browser, *flags, fonts_state=doctor.OK):
        def probe_python(path, modules):
            if "fontTools" in modules:
                return {"state": fonts_state, "detail": "stubbed"}
            return dict(FINE)

        env = {k: v for k, v in os.environ.items()
               if not k.startswith("DECKKIT_") and k != "PUPPETEER_EXECUTABLE_PATH"}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(sys, "argv", ["doctor.py", str(self.deck), *flags]), \
                mock.patch.object(doctor, "probe_python", probe_python), \
                mock.patch.object(doctor, "probe_binary", lambda *a, **k: dict(FINE)), \
                mock.patch.object(doctor.deckcfg, "find_chrome", lambda cfg=None: "/stub/chrome"), \
                mock.patch.object(doctor.geometry, "find_browser", lambda cfg: found_browser), \
                contextlib.redirect_stdout(out):
            code = doctor.main()
        return code, out.getvalue()

    def test_no_geometry_browser_exits_3(self):
        code, out = self.run_doctor(None)
        self.assertEqual(code, doctor.deckcfg.EXIT_ENV)
        self.assertIn("XX geometry browser", out)
        self.assertIn(doctor.geometry.INSTALL_HINT, out)

    def test_a_configured_browser_that_does_not_exist_exits_3(self):
        code, out = self.run_doctor((str(self.browser.with_name("gone")), False))
        self.assertEqual(code, doctor.deckcfg.EXIT_ENV)
        self.assertIn("does not exist", out)

    def test_headless_shell_found_passes(self):
        code, out = self.run_doctor((str(self.browser), True))
        self.assertEqual(code, doctor.deckcfg.EXIT_OK)
        self.assertIn("ok geometry browser", out)

    def test_full_chrome_is_optional_and_passes(self):
        code, out = self.run_doctor((str(self.browser), False))
        self.assertEqual(code, doctor.deckcfg.EXIT_OK)
        self.assertIn(".. geometry browser", out)
        self.assertIn("headless shell is preferred", out)

    def test_json_exits_the_same_way(self):
        for found, expected, state in (
                (None, doctor.deckcfg.EXIT_ENV, doctor.BAD),
                ((str(self.browser), True), doctor.deckcfg.EXIT_OK, doctor.OK),
                ((str(self.browser), False), doctor.deckcfg.EXIT_OK, doctor.WARN)):
            with self.subTest(found=found):
                code, out = self.run_doctor(found, "--json")
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(out)["tools"]["geometry browser"]["state"], state)

    def test_a_broken_fonts_python_still_exits_3_with_a_browser(self):
        code, _ = self.run_doctor((str(self.browser), True), fonts_state=doctor.BAD)
        self.assertEqual(code, doctor.deckcfg.EXIT_ENV)


if __name__ == "__main__":
    unittest.main()
