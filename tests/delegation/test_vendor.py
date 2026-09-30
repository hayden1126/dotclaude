"""The vendored Parable is the pinned file, unedited, with its license."""
import hashlib
import os
import re
import unittest

from _paths import SCRIPTS

VENDOR = os.path.join(SCRIPTS, "vendor")


class Vendor(unittest.TestCase):
    def test_parable_matches_its_pin(self):
        with open(os.path.join(VENDOR, "README.md")) as f:
            pin = re.search(r"sha256: `([0-9a-f]{64})`", f.read()).group(1)
        with open(os.path.join(VENDOR, "parable.py"), "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), pin)

    def test_license_is_kept(self):
        with open(os.path.join(VENDOR, "LICENSE-parable")) as f:
            text = f.read()
        self.assertIn("MIT License", text)
        self.assertIn("Copyright (c) 2025 Parable authors", text)


if __name__ == "__main__":
    unittest.main()
