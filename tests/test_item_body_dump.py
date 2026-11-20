"""item_body_dump: long arrays cut, floats rounded (2026-11-20, vanilla item bodies decoded)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))

import item_body_dump as D  # noqa: E402


class CutTests(unittest.TestCase):
    def test_cut(self):
        v = {"a": list(range(10)), "b": {"c": [1.23456789, [1, 2, 3]]}}
        self.assertEqual(D.cut(v, 3), {"a": [0, 1, 2, "... 10 in all"], "b": {"c": [1.234568, [1, 2, 3]]}})
        self.assertIn("error", D.decode(b"not a tagfile", 3))

    def test_summary(self):
        v = {"motionProperties": [{"gravityFactor": 1.0}], "bodyCinfos": [
            {"motionType": 2, "mass": 2.0, "qualityId": 255, "massDistribution": {"$class": "hknpRefMassDistribution"},
             "shape": {"$class": "hknpConvexShape", "flags": 67, "properties": {"entries": [
                 {"object": {"$class": "hknpShapeMassProperties"}}]}}}]}
        s = D.summary(v)
        self.assertEqual(s[0], "motionProperties: 1")
        self.assertIn("motionType 2, mass 2.0", s[1])
        self.assertIn("['hknpShapeMassProperties']", s[1])
        self.assertIn("hknpRefMassDistribution", s[1])
        self.assertEqual(D.summary({}), ["motionProperties: 0"])


if __name__ == "__main__":
    unittest.main()
