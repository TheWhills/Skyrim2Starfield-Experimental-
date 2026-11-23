"""scripts/re/exe_strings.py (2026-11-22): grass-related strings in an executable, on a synthetic blob."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "re"))

import exe_strings as E  # noqa: E402


class ScanTest(unittest.TestCase):
    def test_kinds_and_matches(self):
        blob = (b"\x00\x01fGrassStartFadeDistance:Grass\x00junk\x00.?AVBGSGroundCover@@\x00"
                b"Meshes\\Grass\\a.nif\x00ToggleGrass\x00no match here\x00"
                + "bAllowCreateGrass:Grass".encode("utf-16-le") + b"\x00\x00"
                + b"fGrassStartFadeDistance:Grass\x00")                       # a repeat: listed once
        hits = E.scan(blob, E.DEFAULT)
        got = {t: k for _o, k, t in hits}
        self.assertEqual(got["fGrassStartFadeDistance:Grass"], "setting")
        self.assertEqual(got[".?AVBGSGroundCover@@"], "rtti")
        self.assertEqual(got["Meshes\\Grass\\a.nif"], "path")
        self.assertEqual(got["ToggleGrass"], "identifier")
        self.assertEqual(got["bAllowCreateGrass:Grass"], "setting")         # UTF-16 too
        self.assertNotIn("no match here", got)
        self.assertEqual(len(hits), 5)

    def test_main_writes_out(self):
        with tempfile.TemporaryDirectory() as d:
            exe = os.path.join(d, "x.exe")
            with open(exe, "wb") as fh:
                fh.write(b"\x00iMinGrassSize:Grass\x00")
            out = os.path.join(d, "o.txt")
            with contextlib.redirect_stdout(io.StringIO()) as log:
                self.assertEqual(E.main(["--exe", exe, "--out", out]), 0)
            self.assertIn("setting (1)", log.getvalue())
            with open(out, encoding="utf-8") as fh:
                self.assertIn("iMinGrassSize:Grass", fh.read())


if __name__ == "__main__":
    unittest.main()
