"""ground_normals.py (2026-11-25): the ground's bump strength; the terrain shades normal maps darker than objects."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))


class GroundNormalsTest(unittest.TestCase):
    def test_scale_planes(self):
        import ground_normals
        x = np.array([0.4, 0.0, 0.9, -0.6])
        y = np.array([0.2, 0.0, 0.9, 0.6])
        sx, sy = ground_normals.scale_planes(x, y, 0.5)
        self.assertTrue(np.allclose(sx[[0, 1, 3]], x[[0, 1, 3]] * 0.5))
        self.assertTrue(np.allclose(sy[[0, 1, 3]], y[[0, 1, 3]] * 0.5))
        bx, by = ground_normals.scale_planes(x, y, 2.0)              # stronger: kept inside the unit disc
        self.assertTrue((np.hypot(bx, by) <= 0.999 + 1e-9).all())
        self.assertTrue(np.allclose(np.arctan2(by, bx)[[0, 2, 3]], np.arctan2(y, x)[[0, 2, 3]]))   # same direction


if __name__ == "__main__":
    unittest.main()
