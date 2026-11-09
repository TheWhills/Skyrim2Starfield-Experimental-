"""outfit_probe: openings (open-edge loops) and diffuse alpha under Skyrim's alpha-test threshold at a shape's shoulders (owner, 2026-11-09:
Delphine's dress showed skin through its shoulder patches)."""
import os
import struct
import sys
import types
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import outfit_probe as P  # noqa: E402


def dds(fourcc: bytes, w: int, h: int, payload: bytes) -> bytes:
    hdr = bytearray(128)
    hdr[:4] = b"DDS "
    struct.pack_into("<IIIII", hdr, 4, 124, 0x1007, h, w, 0)
    struct.pack_into("<I", hdr, 28, 1)
    hdr[84:88] = fourcc
    return bytes(hdr) + payload


class AlphaTests(unittest.TestCase):
    def test_bc3_alpha_plane(self):
        # 8x4 texture = 2 blocks: left alpha 255 everywhere, right alpha 0 everywhere
        solid = bytes([255, 255]) + bytes(6) + bytes(8)
        clear = bytes([0, 0]) + bytes(6) + bytes(8)
        plane, fmt = P.alpha_plane(dds(b"DXT5", 8, 4, solid + clear))
        self.assertEqual(fmt, "DXT5")
        self.assertEqual(plane.shape, (4, 8))
        self.assertTrue((plane[:, :4] == 255).all() and (plane[:, 4:] == 0).all())
        self.assertTrue(np.array_equal(P.sample(plane, [(0.1, 0.5), (0.9, 0.5)]), [255, 0]))

    def test_bc1_punch_through(self):
        opaque = struct.pack("<HHI", 0xFFFF, 0x0000, 0xFFFFFFFF)       # c0 > c1: 4-colour, no alpha
        holes = struct.pack("<HHI", 0x0000, 0xFFFF, 0xFFFFFFFF)        # c0 <= c1, index 3 everywhere: alpha 0
        plane, _ = P.alpha_plane(dds(b"DXT1", 8, 4, opaque + holes))
        self.assertTrue((plane[:, :4] == 255).all() and (plane[:, 4:] == 0).all())

    def test_other_formats_report_only(self):
        self.assertIsNone(P.alpha_plane(dds(b"ATI2", 4, 4, bytes(16)))[0])

    def test_shoulder_vertices(self):
        s = types.SimpleNamespace(bones=[b"NPC Spine2 [Spn2]", b"NPC L Clavicle [LClv]", b"NPC R UpperArm [RUar]"],
                                  weights=[[(0, 1.0)], [(1, 0.7), (0, 0.3)], [(2, 0.4), (0, 0.6)], [(2, 1.0)]])
        self.assertEqual(P.shoulder_vertices(s).tolist(), [1, 3])


if __name__ == "__main__":
    unittest.main()


class OpeningTests(unittest.TestCase):
    def test_boundary_loops_weld_seams(self):
        # a 2x2 grid of quads, the middle column's vertices duplicated (a UV seam): one opening (the rim), not three
        pts, tris = [], []
        for y in range(3):
            for x in range(3):
                pts.append((x, y, 0))
        dup = {1: 9, 4: 10, 7: 11}
        pts += [pts[1], pts[4], pts[7]]
        for y in range(2):
            for x in range(2):
                a, b, c, d = y * 3 + x, y * 3 + x + 1, (y + 1) * 3 + x, (y + 1) * 3 + x + 1
                if x == 1:
                    a, c = dup.get(a, a), dup.get(c, c)
                tris += [(a, b, d), (a, d, c)]
        loops, wid = P.boundary_loops(np.array(pts, float), tris)
        self.assertEqual(len(loops), 1)
        self.assertEqual(len(loops[0]), 8)
        self.assertEqual(len(set(wid.tolist())), 9)
