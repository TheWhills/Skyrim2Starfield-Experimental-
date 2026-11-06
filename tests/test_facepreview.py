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
