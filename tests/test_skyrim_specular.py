"""Skyrim specular -> roughness for converted objects (2026-11-25: the road shone in the sun beside the matte terrain;
every object had one uniform 'fairly rough' value whatever Skyrim's shader said)."""
import os
import struct
import sys
import unittest
from types import SimpleNamespace as NS

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import skyrimnif, textures  # noqa: E402


def lighting_block(flags1, gloss, colour, strength, n_extra=0):
    """BSLightingShaderProperty (SSE): shader type, name, extra data refs, controller, flags 1 / 2, UV offset + scale,
    texture set, emissive colour + multiple, clamp mode, alpha, refraction, glossiness, specular colour, strength."""
    return (struct.pack("<IiI", 1, -1, n_extra) + struct.pack(f"<{n_extra}i", *range(n_extra)) + struct.pack("<i", -1)
            + struct.pack("<II", flags1, 0) + struct.pack("<4f", 0, 0, 1, 1) + struct.pack("<i", 3)
            + struct.pack("<4f", 0, 0, 0, 1) + struct.pack("<I3f", 3, 1.0, 0.0, gloss)
            + struct.pack("<3f", *colour) + struct.pack("<3f", strength, 0.3, 2.0))


class SpecularTest(unittest.TestCase):
    def test_reads_the_shader(self):
        blocks = [lighting_block(0x82400101, 30.0, (1, 1, 1), 1.0),          # RoadChunkM01's shapes
                  lighting_block(0x82400300, 187.0, (0.37, 0.37, 0.37), 1.04, n_extra=2),   # RockL01: off
                  b"\0" * 8]
        n = NS(blocks=blocks, type_of=lambda i: "BSLightingShaderProperty" if i < 2 else "BSEffectShaderProperty")
        self.assertEqual(skyrimnif.specular(n, 0), {"on": True, "glossiness": 30.0, "strength": 1.0})
        rock = skyrimnif.specular(n, 1)
        self.assertFalse(rock["on"])
        self.assertAlmostEqual(rock["strength"], 1.04 * 0.37, places=3)
        self.assertIsNone(skyrimnif.specular(n, 2))
        self.assertIsNone(skyrimnif.specular(n, -1))

    def test_roughness(self):
        self.assertAlmostEqual(textures.gloss_roughness(30), 0.5, places=6)
        self.assertGreater(textures.gloss_roughness(10), textures.gloss_roughness(100))
        m = np.array([[0, 36, 255]], np.uint8)
        r = textures.roughness_from_specular_mask(m, 30, 1.0)
        self.assertEqual(r.tolist(), [[255, 237, 128]])       # none = matte; road median ~0.93; full mask 0.5
        self.assertEqual(textures.roughness_from_specular_mask(m, 30, 0.0).tolist(), [[255, 255, 255]])
        self.assertEqual(textures.roughness_from_specular_mask(m, 30, 4.0)[0, 2], 128)   # clamped at the mask

    def test_mean_pool(self):
        p = np.arange(256, dtype=np.uint8).reshape(16, 16)
        q = textures.mean_pool(p, 4)
        self.assertEqual(q.shape, (4, 4))
        self.assertEqual(int(q[0, 0]), int(round(p[:4, :4].mean())))
        self.assertEqual(textures.mean_pool(np.full((4, 4), 40, np.uint8), 4).tolist(), [[40] * 4] * 4)   # spec off
        self.assertEqual(textures.mean_pool(np.full((8, 8), 7, np.uint8), 4).shape, (4, 4))      # never below a block


if __name__ == "__main__":
    unittest.main()
