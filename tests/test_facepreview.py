"""src/fo4sf/facepreview.py: the face comparison sheet (face_fit.py --preview)."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import facepreview as FP  # noqa: E402


def sphere(n=30):
    u, v = np.meshgrid(np.linspace(0, np.pi, n), np.linspace(0, 2 * np.pi, 2 * n))
    p = np.c_[(np.sin(u) * np.cos(v)).ravel(), (np.sin(u) * np.sin(v)).ravel(), np.cos(u).ravel()] * 0.1
    idx = np.arange(n * 2 * n).reshape(2 * n, n)
    tris = [t for i in range(2 * n - 1) for j in range(n - 1)
            for t in ((idx[i, j], idx[i + 1, j], idx[i, j + 1]), (idx[i + 1, j], idx[i + 1, j + 1], idx[i, j + 1]))]
    return p, np.array(tris)


class PreviewTests(unittest.TestCase):
    def test_sheet(self):
        p, tris = sphere()
        q = p.copy()
        q[:, 1] += 0.02 * (q[:, 2] > 0.05)
        img = FP.sheet([p, q, p], tris, size=64)
        self.assertEqual(img.shape, (3 * 64, 3 * 64, 3))
        heat_moved = img[128:, 64:128]
        heat_still = img[128:, 128:]
        red = lambda im: ((im[:, :, 0] > 200) & (im[:, :, 1] < 120)).sum()
        self.assertGreater(red(heat_moved), 20)                 # the moved head shows red where it moved
        self.assertEqual(red(heat_still), 0)                    # the unchanged one none


if __name__ == "__main__":
    unittest.main()


class OrientAndSmoothTests(unittest.TestCase):
    def test_orientation_stands_a_lying_head_up(self):
        from fo4sf import facefit
        p, tris = sphere(40)
        head = p * [0.8, 0.9, 1.2]                                   # taller than wide / deep, Z up
        cranium = head[:, 2] > 0
        head[cranium, :2] *= 1.15                                    # wider at the top than at the chin
        nose = (head[:, 1] > 0.08) & (np.abs(head[:, 2]) < 0.03) & (np.abs(head[:, 0]) < 0.03)
        head[nose, 1] += 0.03                                        # a nose towards +Y
        lying = head[:, [2, 0, 1]] * [1, 1, -1]                      # up along X, front along -Z
        R = FP.orientation(lying)
        back = lying @ R.T
        self.assertTrue(np.allclose(np.abs(np.linalg.det(R)), 1))
        self.assertGreater(back[nose, 1].mean(), 0.09)               # the nose faces +Y again
        self.assertGreater(back[cranium, 2].mean(), 0)               # the cranium up
        img = FP.sheet([lying, lying], tris, size=48)
        self.assertEqual(img.shape, (144, 96, 3))
        noisy = np.random.default_rng(1).normal(size=(len(p), 3))
        sm = facefit.smooth_field(noisy, tris, 10)
        self.assertLess(sm.std(), noisy.std() * 0.5)
        self.assertTrue(np.allclose(facefit.smooth_field(np.ones((len(p), 3)), tris, 10), 1))
        self.assertTrue(np.allclose(facefit.smooth_field(noisy, tris, 0), noisy))

    def test_dial_limit(self):
        from fo4sf import facefit
        A = np.eye(2)
        self.assertTrue(np.allclose(facefit.bounded_lsq(A, np.array([3.0, 0.5])), [1.0, 0.5], atol=1e-6))
        self.assertTrue(np.allclose(facefit.bounded_lsq(A, np.array([3.0, 0.5]), upper=1.5), [1.5, 0.5], atol=1e-6))
