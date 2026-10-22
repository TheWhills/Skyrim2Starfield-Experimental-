"""Compressed-mesh encoder (src/fo4sf/cmsencode.py) and native Skyrim collision wiring, on synthetic geometry."""
import math
import os
import random
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import cmsencode as C, fo4collision, meshcollision  # noqa: E402


def stairwell():
    """Landing at 2 m, a 2 m ramp down over 3 m, lower floor (metres)."""
    P, T = [], []

    def quad(a, b, c, d):
        i = len(P)
        P.extend([a, b, c, d])
        T.extend([(i, i + 1, i + 2), (i, i + 2, i + 3)])
    quad((0, 0, 2), (1.2, 0, 2), (1.2, 2, 2), (0, 2, 2))
    quad((0, 2, 2), (1.2, 2, 2), (1.2, 5, 0), (0, 5, 0))
    quad((0, 5, 0), (1.2, 5, 0), (1.2, 7, 0), (0, 7, 0))
    return P, T


def terrain(n, ox=0.0, oy=0.0, seed=0):
    rnd = random.Random(seed)
    P = [(x * 0.4 + ox, y * 0.3 + oy, math.sin(x * 0.3) * 0.5 + rnd.random() * 0.01) for y in range(n) for x in range(n)]
    T = []
    for y in range(n - 1):
        for x in range(n - 1):
            i = y * n + x
            T += [(i, i + 1, i + n + 1), (i, i + n + 1, i + n)]
    return P, T


class CodecTests(unittest.TestCase):
    def test_compress_is_conservative_and_matches_decompress(self):
        parent = ((0.0, -1.0, 10.0), (4.0, 1.0, 12.5))
        rnd = random.Random(3)
        for _ in range(500):
            lo = [rnd.uniform(parent[0][a], parent[1][a]) for a in range(3)]
            hi = [rnd.uniform(lo[a], parent[1][a]) for a in range(3)]
            xyz, dec = C.compress(parent, (tuple(lo), tuple(hi)))
            self.assertEqual(C.decompress(parent, xyz), dec)
            for a in range(3):
                self.assertLessEqual(dec[0][a], lo[a])
                self.assertGreaterEqual(dec[1][a], hi[a])
        xyz, dec = C.compress(parent, parent)
        self.assertEqual(xyz, b"\0\0\0")                                   # the whole parent: codes 0
        xyz, _ = C.compress(((0, 0, 0), (1, 1, 1)), ((0.99, 0, 0), (1, 0.01, 1)))
        self.assertEqual(xyz[0] >> 4, 14)                                  # floor(sqrt(0.99 * 226)) = 14 (15 would overshoot)
        self.assertEqual(xyz[1] & 15, 14)

    def test_tree_layouts_as_measured_on_fo4(self):
        boxes = [((i, 0, 0), (i + 1.0, 1, 1)) for i in range(5)]
        nodes, where = C.build_tree(boxes, ((0, 0, 0), (5.0, 1, 1)), 4)
        self.assertEqual(len(nodes), 4 * 9)                                # full binary tree: 2n - 1 nodes
        self.assertEqual(nodes[3] & 1, 1)                                  # root internal: odd data
        self.assertEqual(sorted(v for v, _ in C.walk(nodes, 4, ((0, 0, 0), (5.0, 1, 1)))), list(range(5)))
        for v, k in where.items():
            self.assertEqual(nodes[4 * k + 3], v << 1)                     # leaf: primitive << 1
        top, where5 = C.build_tree(boxes[:2], ((0, 0, 0), (5.0, 1, 1)), 5)
        self.assertEqual(top[3:5], b"\x80\x01")                            # internal: 0x80 | right child at +2
        self.assertEqual((where5[0], where5[1]), (1, 2))
        self.assertEqual(top[8:10], b"\x00\x00")
        self.assertEqual(top[13:15], b"\x00\x01")                          # leaf: the section number
        # a three-leaf top tree like the one read from a FO4 file (0000008001 / leaf / internal ...)
        self.assertEqual(sorted(v for v, _ in C.walk(bytes.fromhex("0000008001400a3000000290030001"), 5,
                                                    ((0, 0, 0), (1.0, 1, 1)))), [0, 1])


class EncoderTests(unittest.TestCase):
    def test_stairwell_round_trip(self):
        P, T = stairwell()
        e = C.encode(P, T)
        self.assertEqual(C.check(e, eps=0.0), [])
        self.assertEqual(len(e.sections), 1)
        tris = C.decode(e)
        self.assertEqual(len(tris), 6)
        for (a, b, c), t in zip(tris, T):
            for q, i in zip((a, b, c), t):
                self.assertLess(max(abs(q[k] - P[i][k]) for k in range(3)), 0.004)   # 11 / 10-bit packing
        self.assertEqual([k for k, _ in e.keys], [0, 2, 4, 6, 8, 10])
        n_keys, bits, max_key, zero = struct.unpack("<iiII", e.header())
        self.assertEqual((n_keys, bits, max_key, zero), (6, 4, 10, 0))

    def test_large_meshes_split_share_and_stay_valid_far_from_origin(self):
        for n, ox, oy in ((25, 0.0, 0.0), (32, 1000.123, -512.77), (40, -3333.3, 77.7)):
            P, T = terrain(n, ox, oy)
            e = C.encode(P, T)
            self.assertEqual(C.check(e, eps=0.0), [], (n, ox))
            self.assertGreater(len(e.sections), 1)
            self.assertGreater(len(e.shared), 0)                            # seams between sections use shared vertices
            for s in e.sections:
                self.assertLessEqual(s.num_prims, C.MAX_PRIMS)
                self.assertLessEqual(s.num_packed + s.num_shared_index, C.MAX_SLOTS)
            self.assertEqual(len(C.decode(e)), len(T))

    def test_fo4_decoder_reads_the_encoding(self):
        """The encoding read through fo4collision (the decoder validated on FO4 files, also used by the in-game-verified
        writer) gives the same triangles and shape keys."""
        P, T = terrain(30, 12.5, 3.0, seed=4)
        e = C.encode(P, T)
        view = C.Fo4View(e)
        pts, tris = fo4collision._compressed_mesh(view, 0)
        self.assertEqual([tuple(pts[i] for i in t) for t in tris], C.decode(e))
        keys = fo4collision.compressed_mesh_keys(view, 0)
        self.assertEqual([k for k, _ in keys], [k for k, _ in e.keys])

    def test_degenerate_input(self):
        P = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0)]
        e = C.encode(P, [(0, 1, 1), (0, 1, 3), (0, 0, 0)])             # repeated indices dropped
        self.assertEqual(len(C.decode(e)), 1)
        with self.assertRaises(ValueError):
            C.encode(P, [(0, 1, 1)])

    def test_check_catches_a_broken_tree(self):
        P, T = stairwell()
        e = C.encode(P, T)
        s = e.sections[0]
        broken = bytearray(s.nodes)
        broken[0] = 0xFF                                                   # root box shrunk to nothing on x
        s.nodes = bytes(broken)
        self.assertTrue(any("outside its leaf box" in p for p in C.check(e)))


class NativeWiringTests(unittest.TestCase):
    def test_non_solid_layers(self):
        for layer in (12, 15, 18, 21, 22):                                 # trigger, non-collidable, portal, sound, AI
            self.assertIn(layer, meshcollision.NON_SOLID_LAYERS)
        for layer in (0, 1, 2, 4, 9, 13, 31):                             # static, animstatic, clutter, trees, terrain, stairs
            self.assertNotIn(layer, meshcollision.NON_SOLID_LAYERS)

    def test_convert_static_sse_falls_back_to_boxes_with_the_reason(self):
        from fo4sf import skyrimconvert
        calls = []
        orig = skyrimconvert.native_collision
        try:
            def boom(src, tmpl, report):
                calls.append(tmpl)
                raise ValueError("template without hknpCompressedMeshShape")
            skyrimconvert.native_collision = boom
            orig_boxes = skyrimconvert.collision_boxes
            skyrimconvert.collision_boxes = lambda src, t, report, landscape=False: (report.update(source="skyrim-boxes"), ["box"])[1]
            from fo4sf import nif as nifmod, sfnif
            orig_build, orig_ser = sfnif.build_static_nif, nifmod.serialize
            sfnif.build_static_nif = lambda node, shapes, child_collision_blobs=(): ("nif", child_collision_blobs)
            nifmod.serialize = lambda out: repr(out).encode()
            shape = nifmod.Fo4Shape(name=b"s", translation=(0, 0, 0), rotation=(1, 0, 0, 0, 1, 0, 0, 0, 1), scale=1.0,
                                    shader_ref=-1, alpha_ref=-1, skin_ref=-1,
                                    positions=[(0, 0, 0), (70, 0, 0), (0, 70, 0)], uvs=[(0, 0)] * 3,
                                    normals=[(0, 0, 1)] * 3, tangents=[], colors=[], triangles=[(0, 1, 2)],
                                    skinned=False)
            report = {}
            files = skyrimconvert.convert_static_sse(None, [shape], "skyrim/x", ["m.mat"], b"boxtemplate", report,
                                                     sf_mesh_template=b"meshtemplate")
            self.assertEqual(calls, [b"meshtemplate"])
            self.assertEqual(report["native_error"], "ValueError: template without hknpCompressedMeshShape")
            self.assertEqual(report["source"], "skyrim-boxes")
            self.assertIn(b"'box'", files["meshes/skyrim/x.nif"])
        finally:
            skyrimconvert.native_collision = orig
            skyrimconvert.collision_boxes = orig_boxes
            sfnif.build_static_nif, nifmod.serialize = orig_build, orig_ser

    def test_mesh_template_option(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "terrain"))
        import types
        import make_skyrim_objects as so
        self.assertIsNone(so.mesh_template(types.SimpleNamespace(box_collision=True, starfield_data="x")))
        self.assertIsNone(so.mesh_template(types.SimpleNamespace(starfield_data="")))


class SurveyToolTests(unittest.TestCase):
    def test_runs_on_an_empty_data_folder(self):
        import contextlib
        import io
        import json
        import tempfile
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "tools"))
        import cms_survey
        with tempfile.TemporaryDirectory() as d:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cms_survey.main(["--starfield-data", d, "--out", os.path.join(d, "o")]), 0)
            self.assertEqual(json.load(open(os.path.join(d, "o", "cms_survey.json")))["meshes"], 0)


if __name__ == "__main__":
    unittest.main()
