"""FO4 -> Starfield mesh collision transplant: section field mapping, SIMD tree layout, tagfile varints (synthetic data)."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import hktagfile, meshcollision  # noqa: E402


class SectionTests(unittest.TestCase):
    def test_fo4_section_fields_map_to_starfield(self):
        fo4 = bytearray(96)
        fo4[16:72] = bytes(range(56))                                   # domain + codec params copied verbatim
        struct.pack_into("<4I", fo4, 72, 42, (44 << 8) | 42, (54 << 8) | 94, (5 << 8) | 18)
        fo4[88], fo4[89] = 42, 124                                      # numPacked, numSharedIndices (FO4 only)
        struct.pack_into("<H", fo4, 90, 5)                              # leafIndex
        fo4[92], fo4[93], fo4[94] = 7, 3, 9                             # page, flags, layerData
        sf = meshcollision._convert_section(bytes(fo4))
        self.assertEqual(sf[16:72], fo4[16:72])
        self.assertEqual(struct.unpack_from("<4I", sf, 72), (42, 44, 54, 5))
        self.assertEqual((sf[88], sf[89], sf[90], sf[91]), (42, 94, 18, 7))
        self.assertEqual(struct.unpack_from("<H", sf, 92)[0], 5)
        self.assertEqual((sf[94], sf[95]), (9, 3))


class SimdTreeTests(unittest.TestCase):
    def leaves(self, n):
        return [(2 * i, ((i, 0.0, 0.0), (i + 1.0, 1.0, 1.0))) for i in range(n)]

    def walk(self, raw):
        nodes = [raw[k:k + 128] for k in range(0, len(raw), 128)]
        keys, seen = [], set()

        def visit(i):
            self.assertNotIn(i, seen)
            seen.add(i)
            n = nodes[i]
            data = struct.unpack_from("<4I", n, 96)
            lx = struct.unpack_from("<4f", n, 0)
            if n[112]:
                keys.extend(d for d, x in zip(data, lx) if d != 0xFFFFFFFF)
            else:
                for d, x in zip(data, lx):
                    if x < 1e30:                                        # active lane
                        visit(d)
        visit(1)
        return nodes, keys

    def test_small_tree_is_one_leaf_under_sentinel(self):
        raw = meshcollision.build_simd_tree(self.leaves(3))
        nodes, keys = self.walk(raw)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(sorted(keys), [0, 2, 4])
        self.assertEqual(struct.unpack_from("<4I", nodes[1], 96)[3], 0xFFFFFFFF)   # unused leaf lane

    def test_every_key_reachable_once_and_boxes_contain_children(self):
        raw = meshcollision.build_simd_tree(self.leaves(57))
        nodes, keys = self.walk(raw)
        self.assertEqual(sorted(keys), [2 * i for i in range(57)])
        root = nodes[1]
        lo_x = min(x for x in struct.unpack_from("<4f", root, 0) if x < 1e30)
        hi_x = max(x for x in struct.unpack_from("<4f", root, 16) if x > -1e30)
        self.assertEqual((lo_x, hi_x), (0.0, 57.0))


class HullTests(unittest.TestCase):
    # unit cube, faces as in the vanilla Starfield box (outward winding)
    FACES = [[4, 2, 0, 1], [3, 5, 7, 6], [7, 4, 1, 6], [0, 2, 5, 3], [2, 4, 7, 5], [6, 1, 0, 3]]

    def test_face_links_point_to_the_opposite_edge(self):
        links, vedges = meshcollision._hull_links(self.FACES, 8)
        self.assertEqual(len(links), 24)
        flat = [(f, e) for f, idx in enumerate(self.FACES) for e in range(len(idx))]
        for (f, e), (g, j) in zip(flat, links):
            a, b = self.FACES[f][e], self.FACES[f][(e + 1) % 4]
            self.assertEqual((self.FACES[g][j], self.FACES[g][(j + 1) % 4]), (b, a))
        self.assertEqual(vedges[0], (5, 2))                                  # vanilla picks the last edge leaving v0

    def test_convex_hull_faces_rebuild_a_closed_outward_cube(self):
        cube = [(x, y, z) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)] + [(0.0, 0.0, 0.0)]  # + interior
        faces = meshcollision.convex_hull_faces(cube)
        self.assertEqual(sorted(len(f) for f in faces), [4] * 6)
        self.assertNotIn(8, {v for f in faces for v in f})                    # interior point is not on the hull
        meshcollision._hull_links(faces, 8)                                    # closed: every edge has an opposite
        for f in faces:                                                        # counter-clockwise seen from outside
            a, b, c = (cube[i] for i in f[:3])
            u = [b[i] - a[i] for i in range(3)]
            v = [c[i] - a[i] for i in range(3)]
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            self.assertGreater(sum(n[i] * a[i] for i in range(3)), 0)

    def test_flat_point_set_becomes_a_closed_slab(self):
        square = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
        slab = meshcollision.thicken_if_flat(square)
        self.assertEqual(sorted({round(p[2], 4) for p in slab}), [-0.005, 0.005])
        faces = meshcollision.convex_hull_faces(slab)
        self.assertEqual(len(faces), 6)
        meshcollision._hull_links(faces, 8)                                    # closed
        cube = [(x, y, z) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]
        self.assertEqual(meshcollision.thicken_if_flat(cube), cube)            # solid input unchanged

    def test_triangle_hull_of_a_shallow_cone_is_closed_and_outward(self):
        import math
        pts = [(math.cos(a) * r, math.sin(a) * r, z) for r, z in ((0.33, -0.82), (0.28, -0.69))
               for a in [i * math.pi / 8 for i in range(16)]] + [(0.0, 0.0, -0.6), (0.0, 0.0, -0.75)]   # + interior
        faces = meshcollision.convex_hull_triangles(pts)
        used = sorted({v for f in faces for v in f})
        self.assertNotIn(33, used)                                             # interior point not on the hull
        remap = {v: k for k, v in enumerate(used)}
        meshcollision._hull_links([[remap[v] for v in f] for f in faces], len(used))   # closed
        c = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
        for f in faces:                                                        # outward
            a, b, d = (pts[i] for i in f)
            u = [b[k] - a[k] for k in range(3)]
            v = [d[k] - a[k] for k in range(3)]
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            self.assertGreater(sum(n[k] * (a[k] - c[k]) for k in range(3)), 0)

    def test_open_hull_and_unused_vertex_rejected(self):
        with self.assertRaises(Exception):
            meshcollision._hull_links(self.FACES[:5], 8)
        with self.assertRaises(Exception):
            meshcollision._hull_links(self.FACES, 9)

    def test_faces_rebuilt_contiguously(self):
        raw = bytes([0, 0, 4, 127]) * 2
        out = meshcollision._faces_raw([[0, 1, 2], [2, 1, 3, 4]], raw)
        self.assertEqual(struct.unpack("<HBBHBB", out), (0, 3, 127, 3, 4, 127))


class StairHelperTests(unittest.TestCase):
    # thin slab helper like V111HallStairs01: top edge at y 1.2 / z 0.45, bottom edge at y -0.75 / z -1.45 (~44 deg)
    VERTS = [(0.9, 1.2, 0.43), (0.9, -0.75, -1.45), (0.9, 1.14, 0.48), (-0.9, 1.2, 0.43),
             (0.9, -0.80, -1.40), (-0.9, 1.14, 0.48), (-0.9, -0.75, -1.45), (-0.9, -0.80, -1.40)]

    def slope(self, verts):
        import math
        top = [v for v in verts if v[2] > 0.4]
        low = [v for v in verts if v[2] < -1.3]
        ty = sum(v[1] for v in top) / len(top)
        ly = sum(v[1] for v in low) / len(low)
        return math.degrees(math.atan2(0.45 + 1.425, ty - ly))

    def test_steep_helper_is_stretched_to_the_limit_and_keeps_width_and_top(self):
        out = meshcollision._flatten_helper(self.VERTS, [], None)
        self.assertLessEqual(self.slope(out), meshcollision.STAIR_HELPER_MAX_SLOPE + 0.5)
        self.assertEqual([v for v in out if v[2] > 0.4], [v for v in self.VERTS if v[2] > 0.4])   # top untouched
        self.assertEqual({round(abs(v[0]), 6) for v in out}, {0.9})                              # width unchanged

    def test_gentle_helper_unchanged(self):
        gentle = [(x, y * 2.0, z) for x, y, z in self.VERTS]                                       # ~25 degrees
        self.assertEqual(meshcollision._flatten_helper(gentle, [], None), gentle)

    def test_planes_point_outward(self):
        cube = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        top = [[1, 5, 7, 3]]                                                                        # z = +1 face
        nx, ny, nz, d = struct.unpack("<4f", meshcollision._planes_from_faces(cube, top))
        self.assertEqual((round(nx, 6), round(ny, 6), round(nz, 6), round(d, 6)), (0, 0, 1, -1))


class VarintTests(unittest.TestCase):
    def test_lengths(self):
        self.assertEqual(hktagfile._varint(bytes([0x05]), 0), (5, 1))
        self.assertEqual(hktagfile._varint(bytes([0x80, 0xA0]), 0), (0xA0, 2))
        self.assertEqual(hktagfile._varint(bytes([0xC1, 0x02, 0x03]), 0), (0x10203, 3))
        self.assertEqual(hktagfile._varint(bytes([0xE8, 0xFF, 0xFF, 0xFF, 0xFF]), 0), (0xFFFFFFFF, 5))


if __name__ == "__main__":
    unittest.main()
