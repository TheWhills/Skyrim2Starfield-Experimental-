"""Synthetic round trip for src/fo4sf/btd.py (no game data)."""
import os
import struct
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import btd  # noqa: E402


def make(ncx=3, ncy=2):
    yy, xx = np.mgrid[0:ncy * 128, 0:ncx * 128]
    metres = 10.0 + 0.05 * xx - 0.02 * yy
    raw = btd.quantize(metres, -500.0, 1000.0)
    w = ((xx // 7) % 8).astype(np.uint16)
    quad = np.zeros((ncy * 2, ncx * 2, 8), np.uint8)
    quad[..., 0] = 2
    return btd.Btd(6, -500.0, 1000.0, [0x10861, 0x1235C2], raw, w, quad), metres


class BtdRoundTrip(unittest.TestCase):
    def test_header_layout(self):
        t, _ = make()
        b = btd.write(t)
        self.assertEqual(b[:4], b"BTDB")
        ver, hmin, hmax, rx, ry = struct.unpack_from("<IffII", b, 4)
        self.assertEqual((ver, hmin, hmax, rx, ry), (6, -500.0, 1000.0, 384, 256))
        self.assertEqual(struct.unpack_from("<4iI", b, 24), (0, 0, 0, 0, 2))

    def test_round_trip_and_quantisation(self):
        t, metres = make()
        r = btd.read(btd.write(t))
        self.assertTrue(np.array_equal(r.heights_raw, t.heights_raw))
        self.assertTrue(np.array_equal(r.weights, t.weights))
        self.assertTrue(np.array_equal(r.quad_map, t.quad_map))
        self.assertLess(np.abs(r.heights_m() - metres).max(), 1500.0 / 65535)   # one step = 2.3 cm for -500..1000

    def test_cell_minmax_matches_lod0(self):
        t, _ = make()
        r = btd.read(btd.write(t))
        hm = r.heights_m()
        self.assertAlmostEqual(float(r.cell_minmax[1, 2, 1]), float(hm[128:256, 256:384].max()), places=3)
        self.assertAlmostEqual(float(r.cell_minmax[0, 0, 0]), float(hm[:128, :128].min()), places=3)

    def test_lod_blocks_are_subsampled(self):
        t, _ = make(ncx=3, ncy=3)
        b = btd.write(t)
        n = 9
        p = 44 + 8 + 8 * n + 32 * n + 256 * n          # header + 2 LTEX + min/max + quads + LOD4
        lod3_off, sz = struct.unpack_from("<II", b, p)
        tables = 8 * (1 + 1 + 4 + 9)
        import zlib
        raw = zlib.decompress(b[p + tables + lod3_off:p + tables + lod3_off + sz])
        h3 = np.frombuffer(raw, "<u2", 16384).reshape(128, 128)
        self.assertTrue(np.array_equal(h3[:48, :48], t.heights_raw[::8, ::8][:48, :48]))
        self.assertTrue((h3[48:, :] == 0).all())

    def test_rejects_bad_shapes(self):
        t, _ = make()
        t.weights = t.weights[:, :100]
        with self.assertRaises(btd.BtdError):
            btd.write(t)


if __name__ == "__main__":
    unittest.main()
