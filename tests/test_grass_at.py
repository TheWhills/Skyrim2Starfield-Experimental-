"""scripts/terrain/grass_at.py (2026-11-23): Skyrim's grass at a spot against what our native-grass build grows."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import grass_at as G  # noqa: E402

GRAS = {0x10: {"edid": "ForestGrass01", "density": 30, "min_slope": 0, "max_slope": 60},
        0x11: {"edid": "TundraGrass01", "density": 20, "min_slope": 0, "max_slope": 45},
        0x12: {"edid": "TundraGrass02", "density": 10, "min_slope": 0, "max_slope": 45}}
REPORT = {"slots": {"00000100": ["ForestGrass01", "TundraGrass01", "TundraGrass02"]},
          "vanilla_paths": {"ForestGrass01": "meshes\\landscape\\grass\\a.nif",
                            "TundraGrass01": "meshes\\landscape\\grass\\b.nif"},
          "shared_models": {"TundraGrass02": "landscape\\grass\\b.nif"},
          "materials": {"ForestGrass01": "Materials\\Landscape\\Grass\\Bladed\\GrassCityShort01.mat",
                        "TundraGrass01": "Materials\\Landscape\\Grass\\Bladed\\GrassFieldDried01.mat"},
          "failed": {}}


class DescribeTest(unittest.TestCase):
    def test_slot_shared_by_two_textures(self):
        near = {1: (3.0, None), 2: (1.0, None), 3: (1.0, None)}
        info = {1: {"edid": "LForest"}, 2: {"edid": "LTundra"}, 3: {"edid": "LRoad"}}
        mapping = {"a": {"edid": "LForest", "starfield": "SKYG_LForest"},
                   "b": {"edid": "LTundra", "starfield": "SKYG_LForest"},     # drawn with the same slot
                   "c": {"edid": "LRoad", "starfield": "Rock01"}}             # a vanilla texture
        lines = G.describe(near, info, {1: [0x10], 2: [0x11, 0x12]}, GRAS, mapping,
                           [{"form_id": 0x100, "skyrim": "LForest"}], REPORT)
        text = "\n".join(lines)
        self.assertTrue(lines[0].startswith("LForest  60 %  Skyrim grows: ForestGrass01"))
        self.assertIn("its ground cover grows 3", text)
        self.assertIn("* ForestGrass01        density  30  slope 0-60  a.nif  [GrassCityShort01.mat]", text)
        self.assertIn("  TundraGrass01", text)                       # grows on LForest via the shared slot
        self.assertIn("shares b.nif  [GrassFieldDried01.mat]", text)  # material of the model's owner
        self.assertIn("LRoad  20 %  Skyrim grows: no grass", text)
        self.assertIn("Rock01 (a vanilla Starfield texture", text)

    def test_unmapped_and_failed(self):
        rep = dict(REPORT, failed={"TundraGrass01": "boom"})
        self.assertIn("FAILED", G.grass_line("TundraGrass01", GRAS[0x11], rep))
        lines = G.describe({1: (1.0, None)}, {1: {"edid": "LX"}}, {}, GRAS, {}, [], rep)
        self.assertIn("not mapped", lines[1])


class PositionTest(unittest.TestCase):
    def test_skyrim_pos_wins_and_shift(self):
        ov = {"spawn": [10.0, 20.0, 0.0], "origin_cw_m": [100.0, -50.0]}
        self.assertEqual(G.skyrim_units(ov, [1, 2], [3, 4], [18000.5, -46000.0]), (18000.5, -46000.0))
        self.assertEqual(G.skyrim_units(ov, [5.0, 6.0]), ((5 + 100) * 70.0, (6 - 50) * 70.0))
        # walked 2 m east of the coc spot (3, 4): overlay spot = spawn + (2, 0)
        self.assertEqual(G.skyrim_units(ov, [5.0, 4.0], [3.0, 4.0]), ((12 + 100) * 70.0, (20 - 50) * 70.0))


class PresenceTest(unittest.TestCase):
    def test_grass_under_an_opaque_layer_counts(self):
        import numpy as np
        from fo4sf import landtex
        # quadrant 0: base LFieldGrass (grassy), an opaque NoGrass layer over all of it
        layers = [(0, 0x1, -1, None), (0, 0x2, 0, {p: 1.0 for p in range(289)})]
        w = landtex.cell_weights(layers)
        self.assertEqual(float(w.get(0x1, np.zeros((33, 33)))[:16, :16].sum()), 0.0)   # invisible on top
        pres = landtex.cell_layer_presence(layers)
        self.assertTrue((pres[0x1][:17, :17] == 1.0).all())                          # but painted
        self.assertEqual(float(pres[0x1][20:, 20:].sum()), 0.0)                      # only in its quadrant
        shares, any_g = G.presence_shares({(0, 0): pres}, 500.0, 500.0, 300.0, {0x1})
        self.assertEqual(any_g, 1.0)
        self.assertEqual(shares[0x2], 1.0)
        lines = G.presence_lines(shares, any_g, {0x2: 1.0}, {0x1: {"edid": "LFieldGrass02"}}, {0x1: [0x10]}, GRAS)
        self.assertIn("painted under 100 % of the ground here; visible on top: 0 %", lines[1])
        self.assertIn("LFieldGrass02          painted under 100 % (visible   0 %): ForestGrass01", lines[2])


if __name__ == "__main__":
    unittest.main()
