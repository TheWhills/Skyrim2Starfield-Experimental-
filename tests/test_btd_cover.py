"""scripts/terrain/btd_cover.py (2026-11-23): ground cover's reading (tail index, mirrored slot) made to match."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import btd_cover as C  # noqa: E402
from fo4sf import btd  # noqa: E402


def terrain():
    q = np.zeros((2, 2, 8), np.uint8)
    q[0, 0, :5] = [1, 2, 3, 4, 5]
    q[0, 0, 6] = 6
    q[0, 1, :5] = [2, 1, 0, 0, 0]           # two layers: slots 3 / 4 empty
    q[1, 0, :5] = [3, 3, 3, 3, 3]
    h = np.zeros((128, 128), np.uint16)
    return btd.Btd(5, 0.0, 1.0, [0xA, 0xB, 0xC, 0xD, 0xE, 0xF0], h, h.copy(), q)


class CoverEncodeTest(unittest.TestCase):
    def test_encode(self):
        t = terrain()
        new, st = C.cover_encode(t)
        self.assertEqual(C.check(t, new), 0)
        T, N = t.ltex, new.ltex
        b = new.quad_map[0, 0]
        self.assertEqual([C.head(N, int(v)) for v in b[:5]], [0xA, 0xB, 0xC, 0xD, 0xE])    # rendering unchanged
        self.assertEqual([C.tail(N, int(v)) for v in b[:5]], [0xE, 0xD, 0xC, 0xB, 0xA])    # cover: slot 4 - j
        self.assertEqual(C.head(N, int(b[6])), 0xF0)
        self.assertEqual(int(b[6]), len(N))                    # byte 6 = the table's length
        self.assertEqual([N[int(b[6]) - int(v)] for v in b[:5]], [0xE, 0xD, 0xC, 0xB, 0xA])   # table[b6 - b]
        self.assertEqual(st["lost"], 2)              # quadrant (0, 1): bytes 3 / 4 empty, bytes 0 / 1 used
        self.assertEqual(st["table"], 2 * st["pairs"])
        self.assertEqual(new.quad_map[1, 1].tolist(), [0] * 8)
        data = btd.write(new)
        self.assertEqual(C.check(t, btd.read(data)), 0)
        self.assertEqual(T, [0xA, 0xB, 0xC, 0xD, 0xE, 0xF0])

    def test_the_owners_spots(self):
        """The 2026-11-23 readings: at the flowers byte 1 = 43 (tail 56 - 43 -> entry 13) with slot 3's alpha 7."""
        table = list(range(1000, 1056))
        self.assertEqual(C.tail(table, 43), 1013)
        self.assertEqual(C.head(table, 43), 1042)

    def test_covered_only(self):
        t = terrain()
        new, st = C.cover_encode(t, covered={0xC}, none_fid=0xE)
        self.assertEqual(C.check(t, new, {0xC}), 0)
        b = new.quad_map[0, 0]
        self.assertEqual([C.tail(new.ltex, int(v)) for v in b[:5]], [0xE, 0xE, 0xC, 0xE, 0xE])
        self.assertLess(st["pairs"], C.cover_encode(t)[1]["pairs"])

    def test_too_many_pairs(self):
        q = np.zeros((40, 40, 8), np.uint8)
        rng = np.random.default_rng(1)
        q[:, :, :5] = rng.integers(1, 30, size=(40, 40, 5))   # far more than 127 pairs
        h = np.zeros((2560, 2560), np.uint16)
        t = btd.Btd(5, 0.0, 1.0, list(range(100, 130)), h, h.copy(), q)
        with self.assertRaises(ValueError):
            C.cover_encode(t)


if __name__ == "__main__":
    unittest.main()
