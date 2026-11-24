"""landtex.choose_layers / refresh_btd.lookalikes (2026-11-24): look-alike Skyrim twins (LFieldGrass02 and
LFieldGrass02NoGrass share one diffuse) compete for a quadrant's five textures as one group, grassy twin first."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from fo4sf import landtex  # noqa: E402


class ChooseLayersTest(unittest.TestCase):
    def test_plain_cut_without_looks(self):
        kept, merge, w = landtex.choose_layers(np.array([5.0, 1.0, 4.0, 3.0, 2.0, 0.5]))
        self.assertEqual(kept, [0, 2, 3, 4, 1])
        self.assertEqual(merge, {})
        self.assertEqual(landtex.choose_layers(np.zeros(3))[0], [0])

    def test_river_bank(self):
        """The owner's Riverwood spot: the top-five cut kept the no-grass twin; as a group the grassy one wins."""
        names = ["Dirt02", "RiverBottomNoGrass", "RiverbedEdge", "PineForest01", "FieldGrass02", "FieldGrass02NoGrass",
                 "PineForest02NoGrass"]
        sums = np.array([31.1, 30.0, 14.2, 12.2, 4.8, 5.5, 1.0])     # the twins' order as the cut saw them
        looks = [None, None, None, ("pf01",), ("fg02",), ("fg02",), ("pf02",)]
        grassy = [False, False, False, False, True, False, False]
        kept, merge, w = landtex.choose_layers(sums, looks, grassy)
        self.assertEqual([names[j] for j in kept],
                         ["Dirt02", "RiverBottomNoGrass", "RiverbedEdge", "PineForest01", "FieldGrass02"])
        self.assertEqual(merge, {5: 4})                       # the no-grass twin's weight drawn as the grassy twin
        self.assertAlmostEqual(w[4], 10.3)

    def test_fall_forest(self):
        """Ivarstead: both FallForestGrass01 twins with grass stay grassy; the rock twins share one slot."""
        names = ["FFDirt", "FFGNoGrass", "Leaves", "RocksNoRocks", "FFGNoFern", "Rocks01", "FFG01", "FFRocks"]
        sums = np.array([29.7, 20.4, 14.1, 12.4, 12.3, 5.3, 4.2, 1.6])
        looks = [None, ("ffg",), None, ("rocks",), ("ffg",), ("rocks",), ("ffg",), None]
        grassy = [False, False, False, False, True, True, True, False]
        kept, merge, w = landtex.choose_layers(sums, looks, grassy)
        self.assertEqual(set(names[j] for j in kept), {"FFDirt", "FFGNoGrass", "Leaves", "RocksNoRocks", "FFGNoFern"})
        self.assertEqual(merge, {6: 4, 5: 3})       # FFG01 -> NoFern (grassy to grassy); Rocks01 (5.3 x 2 < 12.4) ->
        #                                             NoRocks, the group's only kept twin
        self.assertAlmostEqual(w[4], 16.5)
        self.assertAlmostEqual(sum(w.values()), float(sums[:7].sum()))   # only FFRocks' weight is lost
        self.assertEqual(kept[0], 0)                                     # most (merged) weight first


class LookalikesTest(unittest.TestCase):
    def test_lookalikes(self):
        import refresh_btd
        overrides = [{"form_id": 0x30137, "skyrim": "LFieldGrass02"}, {"form_id": 0x58176, "skyrim": "LFieldGrass02NoGrass"},
                     {"form_id": "0042AED", "skyrim": "LDirtPath01"}, {"form_id": 0x1, "skyrim": "LMissing"}]
        sky = {0x1342A: {"edid": "LFieldGrass02", "diffuse": "Landscape\\FieldGrass02.dds", "normal": "N.dds"},
               0x1342B: {"edid": "LFieldGrass02NoGrass", "diffuse": "Landscape\\fieldgrass02.DDS", "normal": "n.dds"},
               0x99: {"edid": "LDirtPath01", "diffuse": "", "normal": ""}}
        out = refresh_btd.lookalikes(overrides, sky, {0x1342A: [7]})
        self.assertEqual(out[0x30137], (("landscape\\fieldgrass02.dds", "n.dds"), True))
        self.assertEqual(out[0x58176], (("landscape\\fieldgrass02.dds", "n.dds"), False))
        self.assertEqual(out[0x42AED], (None, False))         # no diffuse: its own group
        self.assertEqual(out[0x1], (None, False))


if __name__ == "__main__":
    unittest.main()
