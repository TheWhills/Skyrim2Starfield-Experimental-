import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("opening_oracle", Path(__file__).resolve().parents[1] / "scripts/oracles/collision_openings.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


class OpeningOracleTests(unittest.TestCase):
    def test_detects_intrusion_but_not_boundary_contact(self):
        boxes = [((1, 1, -.1), (.5, .5, .1))]
        self.assertEqual(oracle.blocked_probes(boxes, [(1, 1), (1.5, 1), (2, 2)]), [[1, 1]])

    def test_wall_opening_and_other_plane(self):
        boxes = [((-.1, 1, 1), (.1, .5, .5))]
        self.assertEqual(oracle.blocked_probes(boxes, [(1, 1)], axis=0), [[1, 1]])
        self.assertEqual(oracle.blocked_probes(boxes, [(1, 1)], axis=0, plane=2), [])

    def test_fixture_probes_are_inside_source_hole(self):
        _, _, probes = oracle.ring(.4)
        self.assertTrue(all(1.3 < x < 1.7 and 1.3 < y < 1.7 for x, y in probes))
        with self.assertRaises(ValueError):
            oracle.ring(0)

    def test_rejects_malformed_box(self):
        with self.assertRaises(ValueError):
            oracle.blocked_probes([((0, 0, 0), (-1, 1, 1))], [(0, 0)])


if __name__ == "__main__":
    unittest.main()
