"""scripts/terrain/ground_tone.py (2026-11-22): Skyrim's ground look (diffuse x local VCLR) against our converted one."""
import os
import struct
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import ground_tone as T  # noqa: E402


def dxt1(rgb565, size=8):
    """A legacy-header DXT1 DDS of one solid 565 colour."""
    hdr = bytearray(128)
    hdr[:4] = b"DDS "
    struct.pack_into("<I", hdr, 4, 124)
    struct.pack_into("<II", hdr, 12, size, size)
    struct.pack_into("<I", hdr, 28, 1)
    hdr[84:88] = b"DXT1"
    block = struct.pack("<HHI", rgb565, rgb565, 0)
    return bytes(hdr) + block * ((size // 4) ** 2)


class AreaTest(unittest.TestCase):
    def test_local_vertex_colour_and_share(self):
        a = np.zeros((33, 33))
        a[:, :16] = 1.0                       # texture 1 in the west half, texture 2 in the east half
        cells = {(0, 0): {1: a, 2: 1.0 - a}}
        vc = np.full((33, 33, 3), 255, np.uint8)
        vc[:, :16] = (128, 255, 128)          # Skyrim greens the west half
        near = T.area_textures(cells, {(0, 0): vc}, 1024.0, 2048.0, 600.0)     # a spot in the west half
        self.assertEqual(set(near), {1})
        self.assertAlmostEqual(near[1][1][0], 128 / 255, places=6)
        both = T.area_textures(cells, {}, 2048.0, 2048.0, 4096.0)                # no VCLR: white
        self.assertEqual(both[2][1], (1.0, 1.0, 1.0))
        self.assertGreater(both[1][0], 0)
        self.assertEqual(T.area_textures(cells, {}, 99999.0, 0.0, 100.0), {})


class ToneTest(unittest.TestCase):
    def test_decode_and_report(self):
        grey = T.mean_linear(T.decode(dxt1(0x8410)))      # (16, 32, 16) in 565 = sRGB ~ (132, 130, 132)
        self.assertAlmostEqual(T.lum(grey), 0.225, delta=0.01)
        dark = T.mean_linear(T.decode(dxt1(0x2104)))      # sRGB ~ (33, 32, 33)
        self.assertIsNone(T.decode(b"DDS " + bytes(80) + b"BC7X" + bytes(40)))   # unknown format, no texconv
        look = T.tint_linear(grey, (0.5, 1.0, 0.5))
        self.assertGreater(look[1], look[0])               # greened
        lines = T.report([("LGrass", 0.75, grey, (0.5, 1.0, 0.5), (1.0, 1.0, 1.0), dark),
                          ("LMissing", 0.25, None, (1.0, 1.0, 1.0), None, None)])
        self.assertIn("LGrass", lines[1])                  # biggest share first
        self.assertIn("(not found)", lines[2])
        mix = [ln for ln in lines if ln.startswith("area mix")][0]
        ratio = float(mix.split("(")[3].split("x")[0])
        self.assertLess(ratio, 0.3)                        # ours much darker than Skyrim's look here


if __name__ == "__main__":
    unittest.main()
