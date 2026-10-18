import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import skyrimsite  # noqa: E402

SEA = -14000.0


class FlatSite(unittest.TestCase):
    def test_picks_the_flat_dry_square(self):
        rng = np.random.default_rng(1)
        grids = {}
        for cx in range(-4, 5):
            for cy in range(-4, 5):
                grids[(cx, cy)] = rng.uniform(0, 3000, (33, 33))      # rough ground, up to 43 m of relief
        grids[(2, 1)] = np.full((33, 33), 500.0)                      # one flat Skyrim cell (58.5 m)
        grids[(3, 1)] = np.full((33, 33), 500.0)
        grids[(2, 2)] = np.full((33, 33), 500.0)
        grids[(3, 2)] = np.full((33, 33), 500.0)
        site = skyrimsite.flat_site(grids, {}, SEA, offset_m=100.0, near_xy=(0.0, 0.0), radius_m=400.0)
        self.assertIsNotNone(site)
        self.assertLess(site["range_m"], 0.01)
        self.assertTrue(117 <= site["x"] <= 234 and 58 <= site["y"] <= 176)   # inside the flat 2 x 2 Skyrim cells
        self.assertAlmostEqual(site["z"], 500 / 70 + 100.0, 3)

    def test_wet_ground_is_refused(self):
        grids = {(0, 0): np.zeros((33, 33)), (1, 0): np.zeros((33, 33)), (0, 1): np.zeros((33, 33)),
                 (1, 1): np.zeros((33, 33))}
        water = {k: 70.0 for k in grids}                              # all under 1 m of water
        self.assertIsNone(skyrimsite.flat_site(grids, water, SEA, near_xy=(58, 58), radius_m=100))


if __name__ == "__main__":
    unittest.main()
