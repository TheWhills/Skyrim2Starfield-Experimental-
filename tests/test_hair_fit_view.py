"""scripts/armor/hair_fit_view.py: the head-depth test, region counts and the page, on synthetic data."""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts", "armor"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import hair_fit_view as V  # noqa: E402


def sphere(n=4000, r=0.09, c=(0.0, 0.0, 1.65)):
    d = np.random.default_rng(2).normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    return np.asarray(c) + r * d, d


class FitViewTests(unittest.TestCase):
    def test_depth_regions_and_page(self):
        pts, nrm = sphere()
        head = np.eye(4)
        head[:3, 3] = (0.0, 0.0, 1.62)
        probe = np.array([[0.0, 0.0, 1.65 + 0.07],      # 2 cm inside, top
                          [0.0, 0.08, 1.65],            # 1 cm inside, front
                          [0.0, -0.12, 1.60],           # outside, back
                          [0.0, 0.0, 1.65 + 0.095]])    # 5 mm outside
        d = V.head_depth(probe, pts, nrm)
        self.assertAlmostEqual(d[0], -0.02, delta=0.003)
        self.assertAlmostEqual(d[1], -0.01, delta=0.003)
        self.assertGreater(d[2], 0.0)
        self.assertAlmostEqual(d[3], 0.005, delta=0.003)
        r = V.regions(probe, d, head)
        self.assertEqual((r["inside"], r["top"], r["forehead / face (front)"], r["back"]), (2, 1, 1, 0))
        self.assertAlmostEqual(r["deepest_mm"], 20.0, delta=3.0)
        html = V.page({"head": (pts[:10], np.ones((10, 3))), "wig": (probe, np.zeros((4, 3)))}, "T", r)
        self.assertIn("three.min.js", html)
        self.assertIn('"wig":{"p":[0,1720,0,', html)            # model (x, y, z) -> page (x, z, y), mm
        self.assertNotIn("DATAJSON", html)


if __name__ == "__main__":
    unittest.main()
