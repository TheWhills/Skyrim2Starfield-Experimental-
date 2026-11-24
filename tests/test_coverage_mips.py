"""fo4sf.textures coverage-preserving mips for alpha-tested opacity maps (2026-11-24, Skyrim grass "fins")."""
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import textures as T  # noqa: E402


def blades(size=64, every=4):
    """Thin opaque blades (1 texel wide) on a transparent card: 25 % coverage."""
    a = np.zeros((size, size), np.uint8)
    a[:, ::every] = 255
    return a


class CoverageMips(unittest.TestCase):
    def test_chain_shape(self):
        lv = T.coverage_mips(blades(64), 96)
        self.assertEqual([x.shape for x in lv], [(64 >> i, 64 >> i) for i in range(7)])
        self.assertTrue(np.array_equal(lv[0], blades(64)))

    def test_coverage_kept_where_box_filter_drifts(self):
        rng = np.random.default_rng(3)                       # grass-like: sparse soft-edged blades
        a = (rng.random((128, 128)) ** 4 * 255).astype(np.uint8)
        lv = T.coverage_mips(a, 96)
        base = T.coverage(a, 96)
        box = a.astype(np.float32)
        for i, x in enumerate(lv[1:4], start=1):             # levels with enough texels to measure
            box = (box[0::2] + box[1::2]) / 2.0
            box = (box[:, 0::2] + box[:, 1::2]) / 2.0
            self.assertAlmostEqual(T.coverage(x, 96), base, delta=0.03)
        self.assertGreater(abs(T.coverage(box, 96) - base), 0.1)   # plain box filter drifts far from it

    def test_non_square(self):
        lv = T.coverage_mips(np.full((8, 2), 200, np.uint8), 96)
        self.assertEqual(lv[-1].shape, (1, 1))
        self.assertEqual(int(lv[-1][0, 0]), 200)


class AssembleMips(unittest.TestCase):
    def test_header_and_data(self):
        with tempfile.TemporaryDirectory() as d:
            blobs = []
            for i, size in enumerate((8, 4, 2)):
                p = os.path.join(d, f"l{i}.dds")
                T.write_r8(p, np.full((size, size), i, np.uint8))
                with open(p, "rb") as fh:
                    blobs.append(fh.read())
        out = T.assemble_mips(blobs)
        self.assertEqual(struct.unpack_from("<I", out, 28)[0], 3)                 # mip count
        self.assertTrue(struct.unpack_from("<I", out, 8)[0] & T.DDSD_MIPMAPCOUNT)
        self.assertEqual(out[T.DX10_HEADER_BYTES:], bytes([0] * 64 + [1] * 16 + [2] * 4))
        with self.assertRaises(T.DdsError):
            T.assemble_mips([b"nope" * 40])


if __name__ == "__main__":
    unittest.main()
