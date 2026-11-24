"""fo4sf.btd.with_head_padding / btd_head_pad.py (2026-11-24): low quadrant byte values drew the default ground in
game; Starfield's placeholders now head the LTEX table, unreferenced, and every used byte moves up."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from fo4sf import btd  # noqa: E402


def terrain(table):
    q = np.zeros((2, 2, 8), np.uint8)
    q[0, 0, :5] = [3, 1, 2, 4, 5]
    q[1, 1, :2] = [2, 1]
    h = np.zeros((128, 128), np.uint16)
    return btd.Btd(6, 0.0, 1.0, list(table), h, h.copy() + 7, q)


class HeadPadTest(unittest.TestCase):
    def test_pad(self):
        t = terrain([0xA, 0xB, 0xC, 0xD, 0xE])
        new = btd.with_head_padding(t)
        k = len(btd.HEAD_PAD)
        self.assertEqual(new.ltex[:k], list(btd.HEAD_PAD))
        self.assertEqual(new.quad_map[0, 0, :5].tolist(), [3 + k, 1 + k, 2 + k, 4 + k, 5 + k])
        self.assertEqual(new.quad_map[0, 1].tolist(), [0] * 8)                 # 0 stays "none"
        self.assertGreaterEqual(int(new.quad_map[new.quad_map > 0].min()), 8)
        import btd_head_pad
        self.assertTrue(btd_head_pad.same_forms(t, btd.read(btd.write(new))))
        self.assertIs(btd.with_head_padding(new), new)                         # idempotent

    def test_pad_already_in_table(self):
        t = terrain([0xA, btd.HEAD_PAD[3], 0xC, 0xD, 0xE])
        new = btd.with_head_padding(t)
        self.assertEqual(len(new.ltex), 5 + len(btd.HEAD_PAD) - 1)            # no duplicate
        import btd_head_pad
        self.assertTrue(btd_head_pad.same_forms(t, new))
        self.assertIs(btd.with_head_padding(new), new)

    def test_too_long(self):
        with self.assertRaises(btd.BtdError):
            btd.with_head_padding(terrain(list(range(100, 352))))


if __name__ == "__main__":
    unittest.main()
