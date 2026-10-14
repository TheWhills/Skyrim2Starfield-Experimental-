import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("stairs_oracle", Path(__file__).resolve().parents[1] / "scripts/oracles/collision_stairs.py")
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


class StairOracleTests(unittest.TestCase):
    def test_good_support_and_missing_support(self):
        boxes = [((.5, .5, .1), (.5, .5, .1))]
        self.assertEqual(oracle.support_errors(boxes, [(.5, .5, .2)]), [])
        self.assertIsNone(oracle.support_errors(boxes, [(2, .5, .2)])[0]["actual"])

    def test_higher_step_overlapping_tread_is_failure(self):
        boxes = [((.5, .5, .1), (.5, .5, .1)), ((.5, .5, .7), (.5, .5, .1))]
        error = oracle.support_errors(boxes, [(.5, .5, .2)])[0]
        self.assertAlmostEqual(error["actual"], .8)

    def test_lower_step_is_failure(self):
        error = oracle.support_errors([((.5, .5, .1), (.5, .5, .1))], [(.5, .5, .4)])[0]
        self.assertEqual(error["expected"], .4)

    def test_treads_have_explicit_source_heights(self):
        points, _, probes = oracle.stairs()
        self.assertEqual(len(probes), 6)
        for x, y, z in probes:
            self.assertTrue(any(p[2] == z for p in points))
        with self.assertRaises(ValueError):
            oracle.support_errors([], [(0, 0, float("nan"))])


if __name__ == "__main__":
    unittest.main()
