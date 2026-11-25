"""skyrim_grass_native.alpha_cut (2026-11-24): only grass shapes Skyrim cuts by alpha get the translucent vegetation
shader; solid rock "grass" (RockGrassSnow01: no NiAlphaProperty) keeps a plain material."""
import os
import struct
import sys
import unittest
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))


def alpha_block(flags, threshold=50):
    # NiAlphaProperty (SSE): name index, extra data count (0), controller, flags u16, threshold u8
    return struct.pack("<iIi", 0, 0, -1) + struct.pack("<HB", flags, threshold)


class AlphaCutTest(unittest.TestCase):
    def test_alpha_cut(self):
        import skyrim_grass_native as N
        blocks = [b"", alpha_block(0x200), alpha_block(0x1), alpha_block(0x0)]
        src = NS(blocks=blocks, type_of=lambda i: "NiAlphaProperty" if i else "BSTriShape")
        self.assertTrue(N.alpha_cut(src, NS(alpha_ref=1)))       # alpha test (SnowGrass01)
        self.assertTrue(N.alpha_cut(src, NS(alpha_ref=2)))       # alpha blend
        self.assertFalse(N.alpha_cut(src, NS(alpha_ref=3)))      # property without test or blend
        self.assertFalse(N.alpha_cut(src, NS(alpha_ref=-1)))     # none (RockGrassSnow01, RockGrass01)
        self.assertFalse(N.alpha_cut(src, NS(alpha_ref=0)))      # not an alpha property


if __name__ == "__main__":
    unittest.main()
