"""scripts/tools/ba2_find.py (2026-11-23): archived files matching a pattern, per archive."""
import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import ba2_find as F  # noqa: E402
from test_formats import build_ba2_v1_gnrl  # noqa: E402


class FindTest(unittest.TestCase):
    def test_find_and_zip(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Starfield - DensityMaps.ba2"), "wb") as fh:
                fh.write(build_ba2_v1_gnrl({"densitymaps\\grasshelleborefield02.dmap": b"abc",
                                            "densitymaps\\rock01.dmap": b"x"}))
            with open(os.path.join(d, "Starfield - Meshes01.ba2"), "wb") as fh:
                fh.write(build_ba2_v1_gnrl({"meshes\\landscape\\grass\\grasshelleborefield02.nif": b"nif"}))
            hits = F.find(d, re.compile("hellebore", re.I))
            self.assertEqual(sorted(h[0] for h in hits), ["Starfield - DensityMaps.ba2", "Starfield - Meshes01.ba2"])
            self.assertEqual(len(F.find(d, re.compile("."), "Starfield - DensityMaps.ba2")), 2)
            z = os.path.join(d, "o.zip")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(F.main(["--sf-data", d, "--grep", "hellebore", "--zip", z]), 0)
            self.assertIn("2 files match", out.getvalue())
            with zipfile.ZipFile(z) as zf:
                self.assertEqual(zf.read("densitymaps/grasshelleborefield02.dmap"), b"abc")


if __name__ == "__main__":
    unittest.main()
