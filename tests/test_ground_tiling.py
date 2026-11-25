"""ground_tiling.py (2026-11-25): the staged ground materials at Skyrim's own texture repeat, 2048 / 12 units = 2.44 m
(measured on Skyrim's ground-matched meshes), only TilingDistance changed; idempotent."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from fo4sf import convert_material as cm, skyrimground  # noqa: E402

MAT = {"Objects": [{"Components": [
    {"Data": {"Name": "x"}, "Index": 0, "Type": "BSComponentDB::CTName"},
    {"Data": {"BlendSoftness": "0.28", "MaxDisplacement": "0", "RotationAngle": "148", "TilingDistance": "4.88"},
     "Index": 0, "Type": "BSMaterial::TerrainSettingsComponent"}]}]}


class GroundTilingTest(unittest.TestCase):
    def test_constant(self):
        self.assertAlmostEqual(skyrimground.SKYRIM_TILING_M, 2048 / 12 / 70, places=6)
        self.assertEqual(round(skyrimground.SKYRIM_TILING_M, 2), 2.44)

    def test_rewrites_only_the_tiling(self):
        import ground_tiling
        with tempfile.TemporaryDirectory() as t:
            d = os.path.join(t, "Data", "materials", "skyrim", "ground")
            os.makedirs(d)
            p = os.path.join(d, "ldirt02.mat")
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(cm.dump_mat(MAT))
            before = open(p, encoding="utf-8").read()
            with contextlib.redirect_stdout(io.StringIO()) as out:
                ground_tiling.main(["--staging", t])
                ground_tiling.main(["--staging", t])
            after = open(p, encoding="utf-8").read()
        self.assertIn("1 ground materials set to 2.44 m per repeat, rotation 0", out.getvalue())
        self.assertIn("0 ground materials set to 2.44 m per repeat, rotation 0 (1 already)", out.getvalue())
        self.assertEqual(after, before.replace('"4.88"', '"2.44"').replace('"148"', '"0"'))   # rotation 0 too


if __name__ == "__main__":
    unittest.main()
