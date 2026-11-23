"""scripts/terrain/cellgrass_survey.py (2026-11-22): which archived files are grass, folder patterns."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import cellgrass_survey as C  # noqa: E402


class GrassPathTest(unittest.TestCase):
    def test_is_grass(self):
        for yes in ("meshes\\landscape\\cellgrass\\newatlantis\\0_0.nif", "Grass\\NewAtlantis\\x.cgid",
                    "meshes/landscape/grass/fern01.nif", "landscape\\grass\\a.nif", "misc\\cellgrass.bin"):
            self.assertTrue(C.is_grass(yes), yes)
        for no in ("meshes\\setdressing\\grassrug.nif", "textures\\terrain\\grassland_color.dds",
                   "materials\\landscape\\grassfield.mat"):
            self.assertFalse(C.is_grass(no), no)

    def test_pattern(self):
        self.assertEqual(C.pattern("Meshes\\Landscape\\CellGrass\\NewAtlantis\\-12_7.nif"),
                         "meshes\\landscape\\cellgrass\\newatlantis\\*.nif")
        self.assertEqual(C.pattern("grass\\world01\\cell_3_4\\a.cgid"), "grass\\world#\\cell_#_#\\*.cgid")


if __name__ == "__main__":
    unittest.main()
