"""Synthetic tests for the Starfield mesh / NIF writers and the static converter (no game data)."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import convert_static, nif, sfmesh, sfnif  # noqa: E402


def grid_mesh(n):
    """n x n quad grid in the XY plane: enough triangles to need several meshlets."""
    pts = [(x * 0.1, y * 0.1, 0.0) for y in range(n + 1) for x in range(n + 1)]
    tris = []
    for y in range(n):
        for x in range(n):
            a = y * (n + 1) + x
            tris += [(a, a + 1, a + n + 1), (a + 1, a + n + 2, a + n + 1)]
    return pts, tris


class MeshTests(unittest.TestCase):
    def test_roundtrip_with_meshlets(self):
        pts, tris = grid_mesh(12)
        m = sfmesh.SfMesh()
        m.scale, m.positions = sfmesh.encode_positions(pts)
        m.triangles = tris
        m.uv1 = [(sfmesh.float_to_half(p[0]), sfmesh.float_to_half(p[1])) for p in pts]
        m.normals = [sfmesh.encode_packed(0, 0, 1, 1 / 3)] * len(pts)
        sfmesh.build_meshlets(m)
        data = sfmesh.serialize(m)
        again = sfmesh.parse(data)
        self.assertEqual(sfmesh.serialize(again), data)
        self.assertGreater(len(m.meshlets), 1)

    def test_meshlet_invariants(self):
        pts, tris = grid_mesh(20)
        m = sfmesh.SfMesh(triangles=tris)
        m.scale, m.positions = sfmesh.encode_positions(pts)
        sfmesh.build_meshlets(m)
        start, vo, to = 0, 0, 0
        for vc, v_off, tc, t_off in m.meshlets:
            group = tris[start:start + tc]
            self.assertEqual(vc, len({v for t in group for v in t}))
            self.assertEqual((v_off, t_off), (vo, to))
            self.assertLessEqual(vc, 96)
            self.assertLessEqual(tc, 128)
            start, vo, to = start + tc, vo + vc, to + -(-(3 * tc) // 4) * 4
        self.assertEqual(start, len(tris))

    def test_position_and_packed_codecs(self):
        pts = [(0.5, -1.25, 2.0), (-2.0, 0.0, 0.1)]
        scale, raw = sfmesh.encode_positions(pts)
        for p, r in zip(pts, raw):
            for a, b in zip(p, sfmesh.decode_position(r, scale)):
                self.assertAlmostEqual(a, b, delta=scale / 32767 * 1.01)
        x, y, z, w = sfmesh.decode_packed(sfmesh.encode_packed(0.0, 0.6, -0.8, 1.0))
        self.assertAlmostEqual(0.6, y, delta=0.002)
        self.assertAlmostEqual(1.0, w)

    def test_truncated_and_unknown_version(self):
        with self.assertRaises(sfmesh.MeshFormatError):
            sfmesh.parse(struct.pack("<II", 9, 0))
        with self.assertRaises(sfmesh.MeshFormatError):
            sfmesh.parse(struct.pack("<II", 2, 3))

    def test_face_style_mesh_without_meshlet_section(self):
        m = sfmesh.SfMesh(version=2)
        m.scale, m.positions = sfmesh.encode_positions([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
        m.triangles = [(0, 1, 2)]
        m.has_meshlet_section = False
        data = sfmesh.serialize(m)
        self.assertFalse(sfmesh.parse(data).has_meshlet_section)
        self.assertEqual(sfmesh.serialize(sfmesh.parse(data)), data)


class NifTests(unittest.TestCase):
    def test_material_id_known_vanilla_value(self):
        # taken from vanilla meshes/setdressing/posters/chemposter06.nif
        self.assertEqual(sfnif.material_id("Materials\\SetDressing\\Posters\\BlankPoster01.mat"), 0x28204586)

    def test_static_nif_layout_and_roundtrip(self):
        shape = sfnif.StaticShape(b"Chair:0", b"0123456789abcdef0123\\0123456789abcdef0123", 6, 4,
                                  "Materials\\Common\\Metal\\MetalIronCast01.mat",
                                  (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
        f = sfnif.build_static_nif(b"Chair", [shape])
        data = nif.serialize(f)
        g = nif.parse(data)
        self.assertEqual(nif.serialize(g), data)
        self.assertEqual([g.type_of(i) for i in range(len(g.blocks))],
                         ["NiNode", "BSXFlags", "BSGeometry", "NiIntegerExtraData", "BSLightingShaderProperty"])
        geo = sfnif.parse_bsgeometry(g.blocks[2])
        self.assertEqual(geo.shader, 4)
        self.assertEqual(geo.meshes[0].path, shape.mesh_path)
        self.assertEqual(sfnif.build_bsgeometry(geo), g.blocks[2])

    def test_multi_shape_block_refs(self):
        mk = lambda n: sfnif.StaticShape(n, b"a" * 20 + b"\\" + b"b" * 20, 3, 3, "m.mat", (0, 0, 0, 1), (0,) * 6)  # noqa: E731
        f = sfnif.build_static_nif(b"X", [mk(b"A:0"), mk(b"B:0")])
        self.assertEqual(len(f.blocks), 2 + 3 * 2)
        self.assertEqual(sfnif.parse_bsgeometry(f.blocks[5]).shader, 7)


def fake_fo4_nif(n=4):
    """A hand-built FO4 (BS 130) NIF holding one BSTriShape quad grid, full-precision vertices, UVs, normals, tangents."""
    pts, tris = grid_mesh(n)
    f = nif.NifFile(bs_version=130, author=b"t\x00", process_script=b"\x00", export_script=b"\x00", max_filepath=b"\x00")
    f.string_index(b"Quad:0")
    vsize = 16 + 4 + 4 + 4
    desc = (0x1 | 0x2 | 0x8 | 0x10 | 0x400) << 44 | (vsize // 4) | (4 << 8) | (5 << 16) | (6 << 20)
    vdata = b""
    for (x, y, z) in pts:
        vdata += struct.pack("<3ff", x * 70, y * 70, z * 70, 0.0)               # position + bitangent X
        vdata += struct.pack("<2e", x, y)                                      # UV
        vdata += bytes([128, 128, 255, 128]) + bytes([255, 128, 128, 128])     # normal(+Z) / tangent(+X)
    head = struct.pack("<iIiI", 0, 0, -1, 0xE)          # name, no extra data, controller, flags
    head += struct.pack("<3f", 0, 0, 0) + struct.pack("<9f", 1, 0, 0, 0, 1, 0, 0, 0, 1) + struct.pack("<f", 1.0)
    head += struct.pack("<i", -1) + struct.pack("<4f", 0, 0, 0, 1) + struct.pack("<iii", -1, -1, -1)
    head += struct.pack("<Q", desc) + struct.pack("<IHI", len(tris), len(pts), vsize * len(pts) + len(tris) * 6)
    f.add_block("BSTriShape", head + vdata + b"".join(struct.pack("<HHH", *t) for t in tris))
    f.footer = struct.pack("<II", 1, 0)
    return nif.serialize(f), pts, tris


class ConvertTests(unittest.TestCase):
    def test_fo4_reader_decodes_fake_shape(self):
        raw, pts, tris = fake_fo4_nif()
        shapes = nif.fo4_trishapes(nif.parse(raw))
        self.assertEqual(len(shapes), 1)
        self.assertEqual(len(shapes[0].positions), len(pts))
        self.assertEqual(shapes[0].triangles, tris)
        self.assertAlmostEqual(shapes[0].positions[1][0], pts[1][0] * 70, places=3)
        self.assertAlmostEqual(shapes[0].normals[0][2], 1.0, delta=0.01)

    def test_end_to_end_static_conversion(self):
        raw, pts, tris = fake_fo4_nif(6)
        files = convert_static.convert_static(raw, "fo4port/test/quad")
        nifs = [k for k in files if k.endswith(".nif")]
        meshes = [k for k in files if k.endswith(".mesh")]
        self.assertEqual(nifs, ["meshes/fo4port/test/quad.nif"])
        self.assertEqual(len(meshes), 1)
        out = nif.parse(files[nifs[0]])
        geo = sfnif.parse_bsgeometry(out.blocks[2])
        self.assertEqual("geometries/" + geo.meshes[0].path.decode().replace("\\", "/") + ".mesh", meshes[0])
        m = sfmesh.parse(files[meshes[0]])
        self.assertEqual((geo.meshes[0].num_verts, geo.meshes[0].indices_size), (len(pts), len(tris) * 3))
        # 0.6 FO4-units-worth of grid (x70) -> metres: back to the original 0.6 m extent
        decoded = [sfmesh.decode_position(p, m.scale) for p in m.positions]
        self.assertAlmostEqual(max(p[0] for p in decoded) - min(p[0] for p in decoded), 0.6, places=3)
        self.assertEqual(sfmesh.serialize(m), files[meshes[0]])
        self.assertTrue(all(t >> 30 in (0, 3) for t in m.tangents))

    def test_deterministic_output(self):
        raw, _, _ = fake_fo4_nif()
        self.assertEqual(convert_static.convert_static(raw, "a/b"), convert_static.convert_static(raw, "a/b"))


if __name__ == "__main__":
    unittest.main()
