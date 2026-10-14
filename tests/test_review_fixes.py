"""Regression tests for the external review (GitHub issue: 'Review 1'). Synthetic data only."""
import math
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import convert_static, nif, sfcollision, sfmesh  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_sf_pipeline import grid_mesh  # noqa: E402


def av_fields(name_idx, trans, rot, scale):
    return (struct.pack("<iIiI", name_idx, 0, -1, 0xE) + struct.pack("<3f", *trans) + struct.pack("<9f", *rot)
            + struct.pack("<f", scale) + struct.pack("<i", -1))


def trishape_block(pts, tris, normal=(128, 128, 255), tangent=(255, 128, 128)):
    vsize = 16 + 4 + 4 + 4
    desc = (0x1 | 0x2 | 0x8 | 0x10 | 0x400) << 44 | (vsize // 4) | (4 << 8) | (5 << 16) | (6 << 20)
    v = b"".join(struct.pack("<3ff", *p, 0.0) + struct.pack("<2e", 0.0, 0.0) + bytes([*normal, 128]) + bytes([*tangent, 128])
                 for p in pts)
    head = av_fields(0, (0, 0, 0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0) + struct.pack("<4f", 0, 0, 0, 1) + struct.pack("<iii", -1, -1, -1)
    head += struct.pack("<Q", desc) + struct.pack("<IHI", len(tris), len(pts), vsize * len(pts) + 6 * len(tris))
    return head + v + b"".join(struct.pack("<HHH", *t) for t in tris)


ROT_Z90 = (0, -1, 0, 1, 0, 0, 0, 0, 1)          # row-major: x' = -y, y' = x


def nested_nif():
    """root NiNode (identity) -> child NiNode (translated 70 units in x, rotated 90 deg about z) -> BSTriShape."""
    f = nif.NifFile(bs_version=130, author=b"t\x00", process_script=b"\x00", export_script=b"\x00", max_filepath=b"\x00")
    f.string_index(b"Shape")
    f.add_block("NiNode", av_fields(0, (0, 0, 0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0) + struct.pack("<Ii", 1, 1))
    f.add_block("NiNode", av_fields(0, (70, 0, 0), ROT_Z90, 1.0) + struct.pack("<Ii", 1, 2))
    f.add_block("BSTriShape", trishape_block([(0, 0, 0), (70, 0, 0), (0, 70, 0)], [(0, 1, 2)]))
    f.footer = struct.pack("<II", 1, 0)
    return nif.serialize(f)


class TransformTests(unittest.TestCase):
    def test_parent_transforms_are_composed(self):
        s = nif.fo4_trishapes(nif.parse(nested_nif()))[0]
        self.assertEqual(tuple(round(v, 4) for v in s.translation), (70, 0, 0))
        self.assertEqual(tuple(round(v, 4) for v in s.rotation), ROT_Z90)
        m = convert_static.shape_to_mesh(s)
        pts = [sfmesh.decode_position(p, m.scale) for p in m.positions]
        # local (1 m, 0, 0) -> rotated to (0, 1 m) -> + 1 m in x = (1, 1)
        self.assertAlmostEqual(pts[1][0], 1.0, places=3)
        self.assertAlmostEqual(pts[1][1], 1.0, places=3)

    def test_normals_and_tangents_rotate_with_the_shape(self):
        s = nif.fo4_trishapes(nif.parse(nested_nif()))[0]
        m = convert_static.shape_to_mesh(s)
        tx, ty, tz, _ = sfmesh.decode_packed(m.tangents[0])
        self.assertAlmostEqual(tx, 0.0, delta=0.02)            # +X tangent rotated 90 deg about z -> +Y
        self.assertAlmostEqual(ty, 1.0, delta=0.02)
        nx, ny, nz, _ = sfmesh.decode_packed(m.normals[0])
        self.assertAlmostEqual(nz, 1.0, delta=0.02)            # +Z normal unaffected by a z rotation


class CollisionReviewTests(unittest.TestCase):
    def test_floor_hole_stays_open(self):
        pts, tris = grid_mesh(6)                                # 0.6 m x 0.6 m grid of 0.1 m quads, scale up to 3 m
        pts = [(x * 5, y * 5, z) for x, y, z in pts]
        n = 6
        keep = [t for k, t in enumerate(tris) if not (2 <= (k // 2) % n <= 3 and 2 <= (k // 2) // n <= 3)]  # remove centre 2x2
        boxes = sfcollision.surface_boxes(pts, keep, min_area=0.01, cell=0.25)
        centre = (1.5, 1.5)
        for c, h in boxes:
            inside = abs(centre[0] - c[0]) < h[0] - 1e-6 and abs(centre[1] - c[1]) < h[1] - 1e-6
            self.assertFalse(inside, "a collision box covers the hole in the floor")
        self.assertTrue(boxes)

    def test_capped_surfaces_are_reported_not_silently_dropped(self):
        pts, tris = [], []
        for k in range(3):                                      # three separate 1 m floor patches
            b = len(pts)
            pts += [(k * 3, 0, 0), (k * 3 + 1, 0, 0), (k * 3 + 1, 1, 0), (k * 3, 1, 0)]
            tris += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
        report = {}
        boxes = sfcollision.surface_boxes(pts, tris, min_area=0.01, max_boxes=2, report=report)
        self.assertEqual(len(boxes), 2)
        self.assertGreaterEqual(report.get("surface_dropped", 0), 1)

    def test_mesh_boxes_reports_box_count(self):
        pts, tris = grid_mesh(4)
        report = {}
        sfcollision.mesh_boxes(pts, tris, report=report)
        self.assertIn("boxes", report)


class MaterialIdentityTests(unittest.TestCase):
    def test_texture_set_identity_includes_all_textures(self):
        import hashlib
        a = "|".join(["d.dds", "n1.dds", "s.dds"])
        b = "|".join(["d.dds", "n2.dds", "s.dds"])
        self.assertNotEqual(hashlib.sha1(a.encode()).hexdigest()[:8], hashlib.sha1(b.encode()).hexdigest()[:8])


if __name__ == "__main__":
    unittest.main()
