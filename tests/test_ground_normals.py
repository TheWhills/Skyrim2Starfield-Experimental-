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


class Bc5SnormDecodeTest(unittest.TestCase):
    def test_signed_blocks_straddling_zero(self):
        """2026-11-25: BC5_SNORM read as unorm flipped ~12 % of a normal map's pixels (blocks across zero)."""
        from fo4sf import textures
        # one 4 x 4 block per channel: endpoints +100 / -100 (8-value mode, a0 > a1), indices 0, 1, 2 .. 7 repeated
        idx = [0, 1, 2, 3, 4, 5, 6, 7] * 2
        word = 0
        for i, v in enumerate(idx):
            word |= v << (3 * i)
        chan = bytes([100, 156]) + word.to_bytes(6, "little")            # 156 = int8 -100
        r, g = textures.decode_bc5(chan + chan, 4, 4, signed=True)
        pal = [100, -100] + [round(((7 - i) * 100 + i * -100) / 7) for i in range(1, 7)]
        self.assertEqual(r.dtype, np.int8)
        self.assertEqual(r.ravel().tolist(), [pal[i] for i in idx])
        self.assertEqual(g.ravel().tolist(), r.ravel().tolist())
        # 6-value mode (a0 <= a1): indices 6 / 7 are the extremes -127 / +127
        chan6 = bytes([156, 100]) + sum(v << (3 * i) for i, v in enumerate([6, 7] * 8)).to_bytes(6, "little")
        r6, _ = textures.decode_bc5(chan6 + chan6, 4, 4, signed=True)
        self.assertEqual(r6.ravel().tolist(), [-127, 127] * 8)
        u, _ = textures.decode_bc5(chan + chan, 4, 4)                     # unorm reading unchanged
        self.assertEqual(u.dtype, np.uint8)
