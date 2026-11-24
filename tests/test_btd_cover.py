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

    def test_pad(self):
        q = np.zeros((2, 2, 8), np.uint8)
        q[0, 0, :5] = [1, 2, 3, 0, 0]
        q[0, 0, 6] = 4
        h = np.zeros((128, 128), np.uint16)
        t = btd.Btd(5, 0.0, 1.0, [0xA, 0xB, 0xC, 0xF0], h, h.copy(), q)
        new = C.pad_table(t, [0x100, 0x101])
        self.assertEqual(new.ltex, [0xA, 0xB, 0xC, 0x100, 0x101, 0xF0])
        self.assertEqual(new.quad_map[0, 0].tolist(), [1, 2, 3, 0, 0, 0, 6, 0])
        self.assertEqual(C.head(new.ltex, 6), 0xF0)
        self.assertEqual([C.tail(new.ltex, b) for b in (1, 2, 3)], [0xF0, 0x101, 0x100])
        with self.assertRaises(ValueError):
            C.pad_table(t, [0xA])                       # a duplicate
        q[0, 0, 6] = 2
        with self.assertRaises(ValueError):
            C.pad_table(btd.Btd(5, 0.0, 1.0, [0xA, 0xB, 0xC, 0xF0], h, h.copy(), q), [0x100])

    def test_uniform_patch(self):
        q = np.zeros((4, 4, 8), np.uint8)
        q[:, :, :5] = [1, 2, 3, 4, 5]
        q[:, :, 6] = 6
        h = np.zeros((128, 128), np.uint16)
        t = btd.Btd(5, 0.0, 1.0, [0xA, 0xB, 0xC, 0xD, 0xE, 0xF0], h, h.copy(), q)
        new = C.uniform_patch(t, 1, 1, 2, 0xC)
        self.assertEqual(new.quad_map[0, 0, :5].tolist(), [3] * 5)
        self.assertEqual(new.quad_map[1, 1, :7].tolist(), [3] * 5 + [0, 6])
        self.assertEqual(new.quad_map[2, 2, :5].tolist(), [1, 2, 3, 4, 5])          # outside the patch
        self.assertTrue((new.weights[:128, :128] == 0x7FFF).all())
        with self.assertRaises(ValueError):
            C.uniform_patch(t, 1, 1, 2, 0x99)
        self.assertEqual(C.alpha_word(7), 0x7FFF)
        self.assertEqual(C.alpha_word(3), 0b011011011011011)
        self.assertTrue((C.uniform_patch(t, 1, 1, 2, 0xC, 3).weights[:128, :128] == 0x36DB).all())

    def test_slot_patch(self):
        q = np.zeros((4, 4, 8), np.uint8)
        q[:, :, :5] = [1, 3, 2, 3, 5]
        q[:, :, 6] = 6
        h = np.zeros((256, 256), np.uint16)
        w = np.full((256, 256), 0x1234, np.uint16)
        t = btd.Btd(5, 0.0, 1.0, [0xA, 0xB, 0xC, 0xD, 0xE, 0xF0], h, w, q)
        new, n_bytes, n_quads = C.slot_patch(t, 1, 1, 2, 0xC, 0x777)
        self.assertEqual(list(new.ltex), [0xA, 0xB, 0xC, 0xD, 0xE, 0xF0, 0x777])        # appended, others kept
        self.assertEqual(new.quad_map[0, 0, :7].tolist(), [1, 7, 2, 7, 5, 0, 0])
        self.assertEqual(new.quad_map[2, 2, :7].tolist(), [1, 3, 2, 3, 5, 0, 6])        # outside the patch
        self.assertEqual((n_bytes, n_quads), (8, 4))
        self.assertTrue(np.array_equal(new.weights, w))
        again, _b, _q = C.slot_patch(t, 1, 1, 2, 0xC, 0xF0)                             # already in the table
        self.assertEqual(len(again.ltex), 6)
        self.assertEqual(again.quad_map[1, 1, 1], 6)
        with self.assertRaises(ValueError):
            C.slot_patch(t, 1, 1, 2, 0x99, 0x777)

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
