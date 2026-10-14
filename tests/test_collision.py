"""Synthetic tests for the box-collision generator (no game data: the template blob is fabricated)."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import nif, sfcollision, sfnif  # noqa: E402


def fake_template():
    b = bytearray(sfcollision.BLOB_SIZE)
    b[0:8] = b"\x00\x00\x18\x18TAG0"
    b[100:112] = b"hknpBoxShape"
    struct.pack_into("<3f", b, 528, 1.0, 0.0, 0.0)
    struct.pack_into("<3f", b, 544, 0.0, 1.0, 0.0)
    struct.pack_into("<3f", b, 560, 0.0, 0.0, 1.0)
    return bytes(b)


class CollisionTests(unittest.TestCase):
    def test_box_roundtrip(self):
        blob = sfcollision.box_blob(fake_template(), (0.1, -0.2, 0.5), (0.45, 0.4, 0.52))
        c, h = sfcollision.read_box(blob)
        for a, b in zip(c + h, (0.1, -0.2, 0.5, 0.45, 0.4, 0.52)):
            self.assertAlmostEqual(a, b, places=5)
        self.assertEqual(len(blob), sfcollision.BLOB_SIZE)

    def test_only_listed_words_change(self):
        t = fake_template()
        blob = sfcollision.box_blob(t, (1, 2, 3), (4, 5, 6))
        changed = {o for o in range(0, len(t), 4) if t[o:o + 4] != blob[o:o + 4]}
        self.assertTrue(changed <= set(sfcollision.LINEAR))
        self.assertEqual(len(sfcollision.LINEAR), 36)      # 6 centre/half words + 24 corner words + 6 face planes

    def test_face_planes(self):
        blob = sfcollision.box_blob(fake_template(), (0.0, 0.0, 1.0), (0.5, 0.5, 1.0))
        g = lambda o: struct.unpack_from("<f", blob, o)[0]  # noqa: E731
        self.assertAlmostEqual(g(700), -0.5)      # -cx - hx
        self.assertAlmostEqual(g(780), 0.0)       #  cz - hz  (box sits on z = 0)

    def test_rejects_bad_templates(self):
        with self.assertRaises(sfcollision.CollisionError):
            sfcollision.box_blob(b"\0" * 100, (0, 0, 0), (1, 1, 1))
        rotated = bytearray(fake_template())
        struct.pack_into("<f", rotated, 532, 0.5)
        with self.assertRaises(sfcollision.CollisionError):
            sfcollision.box_blob(bytes(rotated), (0, 0, 0), (1, 1, 1))

    def test_minimum_half_extent(self):
        blob = sfcollision.box_blob(fake_template(), (0, 0, 0), (0.0, 1.0, 1.0))
        self.assertAlmostEqual(sfcollision.read_box(blob)[1][0], sfcollision.MIN_HALF, places=6)

    def test_static_nif_with_collision_layout(self):
        shape = sfnif.StaticShape(b"Chair:0", b"a" * 20 + b"\\" + b"b" * 20, 6, 4, "m.mat", (0, 0, 0, 1), (0,) * 6)
        blob = sfcollision.box_blob(fake_template(), (0, 0, 0.5), (0.4, 0.4, 0.5))
        f = sfnif.build_static_nif(b"Chair", [shape], collision_blob=blob)
        data = nif.serialize(f)
        g = nif.parse(data)
        self.assertEqual([g.type_of(i) for i in range(len(g.blocks))],
                         ["NiNode", "BSXFlags", "bhkNPCollisionObject", "bhkPhysicsSystem", "BSGeometry",
                          "NiIntegerExtraData", "BSLightingShaderProperty"])
        self.assertEqual(struct.unpack("<iHiI", g.blocks[2]), (0, 0x80, 3, 0))
        self.assertEqual(struct.unpack_from("<i", g.blocks[0], 8 + 4 + 8 + 52)[0], 2)      # root owns the collision object
        self.assertEqual(struct.unpack_from("<iI", g.blocks[1], 0)[1], 2)                  # BSXFlags = 2
        self.assertEqual(sfnif.parse_bsgeometry(g.blocks[4]).shader, 6)
        self.assertEqual(g.blocks[3][4:], blob)

    def test_surface_boxes_floor_slab_and_leftovers(self):
        pts = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0), (0, 0, 1), (1, 0, 0.5), (1, 1, 1)]
        rest = []
        boxes = sfcollision.surface_boxes(pts, [(0, 1, 2), (0, 2, 3), (0, 5, 6)], leftovers=rest, min_area=0.01)
        self.assertEqual(len(boxes), 1)
        c, h = boxes[0]
        self.assertAlmostEqual(c[2], -0.075)                      # slab sits just under the floor
        self.assertEqual((round(h[0], 3), round(h[1], 3)), (1.0, 1.0))
        self.assertEqual(rest, [(0, 5, 6)])                       # the sloped triangle is left for voxel boxes

    def test_voxel_boxes_cover_a_slope(self):
        pts = [(0, 0, 0), (2, 0, 1), (2, 1, 1), (0, 1, 0)]          # 2 m long ramp rising 1 m
        boxes = sfcollision.voxel_boxes(pts, [(0, 1, 2), (0, 2, 3)], voxel=0.25)
        self.assertGreater(len(boxes), 3)
        self.assertGreaterEqual(max(c[2] + h[2] for c, h in boxes), 1.0)
        for c, h in boxes:
            self.assertTrue(-0.3 <= c[0] <= 2.3 and -0.3 <= c[1] <= 1.3)

    def test_voxel_boxes_respect_cap(self):
        import math
        pts, tris = [], []
        for i in range(40):                                       # a curved wall strip
            a = i / 40 * math.pi
            pts += [(math.cos(a) * 3, math.sin(a) * 3, 0), (math.cos(a) * 3, math.sin(a) * 3, 3)]
        for i in range(39):
            k = 2 * i
            tris += [(k, k + 2, k + 1), (k + 1, k + 2, k + 3)]
        self.assertLessEqual(len(sfcollision.voxel_boxes(pts, tris, voxel=0.1, max_boxes=20)), 20)

    def test_no_collision_layout_unchanged(self):
        shape = sfnif.StaticShape(b"X:0", b"a" * 20 + b"\\" + b"b" * 20, 3, 3, "m.mat", (0, 0, 0, 1), (0,) * 6)
        g = nif.parse(nif.serialize(sfnif.build_static_nif(b"X", [shape])))
        self.assertEqual(len(g.blocks), 5)
        self.assertEqual(struct.unpack_from("<i", g.blocks[0], 8 + 4 + 8 + 52)[0], -1)


if __name__ == "__main__":
    unittest.main()
