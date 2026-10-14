import importlib.util
import math
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("oriented_oracle", Path(__file__).resolve().parents[1] / "scripts/oracles/collision_oriented.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
IDENTITY = (1, 0, 0, 0, 1, 0, 0, 0, 1)


class OrientedOracleTests(unittest.TestCase):
    def test_translation_and_anisotropic_rotated_axes(self):
        box = ((3, 4, 5), (2, .1, .2), (0, -1, 0, 1, 0, 0, 0, 0, 1))
        self.assertTrue(oracle.contains(box, (3, 5.5, 5)))
        self.assertFalse(oracle.contains(box, (4.5, 4, 5)))

    def test_vertical_interval_and_outside_line(self):
        box = ((0, 0, 2), (1, 1, .1), IDENTITY)
        lo, hi = oracle.vertical_interval(box, 0, 0)
        self.assertAlmostEqual(lo, 1.9)
        self.assertAlmostEqual(hi, 2.1)
        self.assertIsNone(oracle.vertical_interval(box, 2, 0))

    def test_sloping_surface_matches_analytical_plane(self):
        s = math.sqrt(.5)
        # The upper surface is z=x + thickness/cos(45 degrees).
        box = ((0, 0, 0), (2, 1, .1), (s, 0, -s, 0, 1, 0, s, 0, s))
        for x in (-.5, 0, .5):
            _, hi = oracle.vertical_interval(box, x, 0)
            self.assertAlmostEqual(hi, x + .1 / s)

    def test_invalid_rotation_is_rejected(self):
        with self.assertRaises(ValueError):
            oracle.contains(((0, 0, 0), (1, 1, 1), (1,) * 9), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
