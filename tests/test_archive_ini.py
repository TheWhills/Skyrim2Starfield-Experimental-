"""scripts/tools/archive_ini.py (2026-11-23): the game's [Archive] list with our BA2 appended."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "tools"))

import archive_ini as A  # noqa: E402


class ArchiveIniTest(unittest.TestCase):
    def test_merged(self):
        self.assertEqual(A.merged("A.ba2, B.ba2", ["C.ba2", "a.BA2"]), "A.ba2, B.ba2, C.ba2")
        self.assertEqual(A.merged("", ["C.ba2"]), "C.ba2")

    def test_main(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Data"))
            with open(os.path.join(d, "Starfield.ini"), "w", encoding="utf-8") as fh:
                fh.write("[General]\nx=1\n[Archive]\nsResourceArchiveList2=Starfield - Meshes01.ba2, Starfield - X.ba2\n"
                         "sResourceIndexFileList=Starfield - Textures01.ba2\n")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(A.main(["--starfield", d, "--add", "S2SGrass - Main.ba2"]), 0)
            text = out.getvalue()
            self.assertIn("sResourceArchiveList2=Starfield - Meshes01.ba2, Starfield - X.ba2, S2SGrass - Main.ba2", text)
            self.assertIn("note: S2SGrass - Main.ba2 is not in", text)
            with self.assertRaises(SystemExit):
                A.main(["--starfield", os.path.join(d, "nope"), "--add", "x.ba2"])
            with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
                A.main(["--starfield", d, "--add", "x.ba2", "--key", "sResourceArchiveList"])   # not in the ini


if __name__ == "__main__":
    unittest.main()
