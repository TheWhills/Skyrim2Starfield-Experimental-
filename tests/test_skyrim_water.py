"""Synthetic tests for Skyrim river / lake levels as Starfield cell water (src/fo4sf/skyrimwater.py). No game data."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import skyrimwater  # noqa: E402

SEA = -14000.0


class LevelTests(unittest.TestCase):
    def test_river_cell_gets_its_level_sea_and_dry_cells_none(self):
        bed = np.full((33, 33), 0.0)                      # a river bed at 0 units with water at 700 (10 m)
        dry = np.full((33, 33), 5000.0)                   # high ground, has no water
        low = np.full((33, 33), -15000.0)                 # sea floor under the default sea
        grids = {(0, 0): bed, (3, 0): dry, (6, 0): low}
        water = {(0, 0): 700.0, (6, 0): SEA}
        got = skyrimwater.cell_levels(grids, water, SEA, offset_m=185.0)
        cells = {tuple(c["cell"]): c for c in got}
        self.assertEqual(set(cells), {(0, 0)})            # Skyrim cell (0, 0) = 58.5 m: inside Starfield cell (0, 0)
        self.assertAlmostEqual(cells[(0, 0)]["height_m"], 10.0 + 185.0)
        self.assertEqual(cells[(0, 0)]["agree"], 1.0)

    def test_two_river_steps_in_one_cell_take_the_level_that_fits_most(self):
        a = np.zeros((33, 33)); b = np.full((33, 33), -700.0)
        water = {(0, 0): 350.0, (1, 0): -350.0}           # upstream 5 m, downstream -5 m; beds 5 m below each
        got = skyrimwater.cell_levels({(0, 0): a, (1, 0): b}, water, SEA)
        c = {tuple(x["cell"]): x for x in got}[(0, 0)]   # both Skyrim cells start inside Starfield cell (0, 0)
        self.assertIn(c["height_m"], (5.0, -5.0))
        self.assertGreaterEqual(c["agree"], 0.5)

    def test_a_level_that_floods_dry_ground_is_refused(self):
        lake = np.full((33, 33), 1000.0); lake[:5, :5] = 0.0         # a small lake (water 700) in high ground
        valley = np.full((33, 33), -3000.0)                           # dry valley beside it, far below the lake
        got = skyrimwater.cell_levels({(0, 0): lake, (1, 0): valley}, {(0, 0): 700.0}, SEA)
        self.assertEqual(got, [])                                     # the lake's level would hang over the valley
        got = skyrimwater.cell_levels({(0, 0): lake, (1, 0): valley}, {(0, 0): 700.0}, SEA, max_false_wet=1.0)
        self.assertEqual(len(got), 1)

    def test_cell_range_and_origin(self):
        got = skyrimwater.cell_levels({(0, 0): np.zeros((33, 33))}, {(0, 0): 700.0}, SEA, origin_m=(200.0, 0.0),
                                      cell_range=(-36, 36))
        self.assertEqual({tuple(c["cell"]) for c in got}, {(-2, 0)})
        self.assertEqual(skyrimwater.cell_levels({(0, 0): np.zeros((33, 33))}, {(0, 0): 700.0}, SEA,
                                                 cell_range=(5, 9)), [])


if __name__ == "__main__":
    unittest.main()
