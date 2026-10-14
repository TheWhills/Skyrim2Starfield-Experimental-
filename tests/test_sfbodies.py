"""Reading back converted Starfield collision (src/fo4sf/sfbodies.py) from synthetic tagfiles and NIFs (no game data)."""
import math
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import nif, sfbodies, sfnif  # noqa: E402


def _v(x):
    """Havok varint (1 or 2 bytes, enough for these fixtures)."""
    assert 0 <= x < 0x4000
    return bytes([x]) if x < 0x80 else bytes([0x80 | (x >> 8), x & 0xFF])


def _sec(tag, payload, leaf=True):
    return struct.pack(">I", ((1 if leaf else 0) << 30) | (len(payload) + 8)) + tag + payload


class TagWriter:
    """Minimal TAG0 writer: named types with sizes and fields, items and pointer patches (what hktagfile reads)."""

    def __init__(self):
        self.types = []          # (name, size, [(field, offset, type name)])
        self.items = []          # (type name, payload, count)
        self.ptrs = []           # (item, offset, target item)

    def type(self, name, size, fields=()):
        self.types.append((name, size, list(fields)))

    def item(self, tname, payload, count=1):
        self.items.append((tname, bytearray(payload), count))
        return len(self.items)

    def ptr(self, item, offset, target):
        self.ptrs.append((item, offset, target))

    def build(self):
        names = [t[0] for t in self.types]
        tidx = {n: i + 1 for i, n in enumerate(names)}
        fields = sorted({f for t in self.types for f, _, _ in t[2]})
        fidx = {f: i for i, f in enumerate(fields)}
        tst = b"".join(n.encode() + b"\0" for n in names)
        fst = b"".join(f.encode() + b"\0" for f in fields)
        tna = _v(len(names) + 1) + b"".join(_v(i) + _v(0) for i in range(len(names)))
        tbdy = b""
        for name, size, fl in self.types:
            opt = 0x8 | (0x20 if fl else 0)
            tbdy += _v(tidx[name]) + _v(0) + _v(opt) + _v(size) + _v(4)
            if fl:
                tbdy += _v(len(fl)) + b"".join(_v(fidx[f]) + _v(0) + _v(o) + _v(tidx[t]) for f, o, t in fl)
        data, offsets = bytearray(), []
        for _, payload, _ in self.items:
            data += b"\0" * (-len(data) % 16)
            offsets.append(len(data))
            data += payload
        data += b"\0" * (-len(data) % 16)
        pt = []
        for item, off, target in self.ptrs:
            at = offsets[item - 1] + off
            struct.pack_into("<Q", data, at, target)
            pt.append(at)
        item_tab = bytes(12) + b"".join(struct.pack("<III", tidx[t], o, c) for (t, _, c), o in zip(self.items, offsets))
        ptch = struct.pack("<II", 1, len(pt)) + struct.pack(f"<{len(pt)}I", *pt) if pt else b""
        types = (_sec(b"TST1", tst) + _sec(b"TNA1", tna) + _sec(b"FST1", fst) + _sec(b"TBDY", tbdy))
        body = (_sec(b"SDKV", b"20190200") + _sec(b"DATA", bytes(data)) + _sec(b"TYPE", types, leaf=False)
                + _sec(b"INDX", _sec(b"ITEM", item_tab) + _sec(b"PTCH", ptch), leaf=False))
        return _sec(b"TAG0", body, leaf=False)


BODY = "hknpPhysicsSystemData::bodyCinfoWithAttachment"


def body_types(w, shape_type):
    w.type("ptr", 8)
    w.type("float3", 12)
    w.type("u8", 1)
    w.type("face", 4)
    w.type(BODY, 64, [("shape", 0, "ptr"), ("position", 16, "float3"), ("orientation", 32, "float3"),
                      ("collisionFilterInfo", 48, "u8")])


def add_body(w, shape_item, pos=(0, 0, 0), quat=(0, 0, 0, 1), layer=1):
    b = bytearray(64)
    struct.pack_into("<3f", b, 16, *pos)
    struct.pack_into("<4f", b, 32, *quat)
    struct.pack_into("<I", b, 48, layer)
    i = w.item(BODY, b)
    w.ptr(i, 0, shape_item)
    return i


def convex_blob(verts, faces, radius=0.0, pos=(0, 0, 0), quat=(0, 0, 0, 1), kind="hknpConvexShape"):
    w = TagWriter()
    body_types(w, kind)
    w.type("hull", 48, [("vertices", 0, "ptr"), ("faces", 16, "ptr"), ("indices", 32, "ptr")])
    w.type(kind, 80, [("convexRadius", 8, "float3"), ("hull", 16, "hull")])
    shape = bytearray(80)
    struct.pack_into("<f", shape, 8, radius)
    s = w.item(kind, shape)
    vi = w.item("float3", b"".join(struct.pack("<3f", *v) for v in verts), len(verts))
    fr, idx = b"", b""
    for f in faces:
        fr += struct.pack("<HBB", len(idx), len(f), 0)
        idx += bytes(f)
    fi = w.item("face", fr, len(faces))
    ii = w.item("u8", idx, len(idx))
    w.ptr(s, 16, vi)
    w.ptr(s, 32, fi)
    w.ptr(s, 48, ii)
    add_body(w, s, pos, quat)
    return w.build()


def cube(lo, hi):
    v = [(x, y, z) for z in (lo[2], hi[2]) for y in (lo[1], hi[1]) for x in (lo[0], hi[0])]
    faces = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]]
    return v, faces


def mesh_blob(packed, prims, n_shared_idx=0, section_off=(0, 0, 0), scale=(0.01, 0.01, 0.01)):
    """One compressed-mesh body: one section of packed vertices (quantised 11/11/10 bits) and primitives."""
    w = TagWriter()
    body_types(w, "hknpCompressedMeshShape")
    w.type("tree", 160, [("sections", 64, "ptr"), ("primitives", 80, "ptr"), ("sharedVerticesIndex", 96, "ptr"),
                         ("packedVertices", 112, "ptr"), ("sharedVertices", 128, "ptr")])
    w.type("hknpCompressedMeshShapeData", 176, [("meshTree", 0, "tree")])
    w.type("hknpCompressedMeshShape", 32, [("data", 8, "ptr")])
    w.type("section", 96)
    w.type("u32", 4)
    w.type("u16", 2)
    s = w.item("hknpCompressedMeshShape", bytes(32))
    d = w.item("hknpCompressedMeshShapeData", bytes(176))
    w.ptr(s, 8, d)
    sec = bytearray(96)
    struct.pack_into("<3f", sec, 48, *section_off)
    struct.pack_into("<3f", sec, 60, *scale)
    struct.pack_into("<4I", sec, 72, 0, 0, 0, 0)
    sec[88], sec[89] = len(packed), len(prims)
    si = w.item("section", sec, 1)
    pk = b"".join(struct.pack("<I", q[0] | (q[1] << 11) | (q[2] << 22)) for q in packed)
    pi = w.item("u32", pk, len(packed))
    pr = w.item("u32", b"".join(bytes(p) for p in prims), len(prims))
    sh = w.item("u16", bytes(2 * n_shared_idx), n_shared_idx) if n_shared_idx else None
    w.ptr(d, 64, si)
    w.ptr(d, 112, pi)
    w.ptr(d, 80, pr)
    if sh:
        w.ptr(d, 96, sh)
    add_body(w, s)
    return w.build()


class SfBodiesTests(unittest.TestCase):
    def test_convex_cube_triangles_and_radius(self):
        v, f = cube((0, 0, 0), (2, 1, 0.5))
        bodies = sfbodies.blob_bodies(convex_blob(v, f))
        self.assertEqual(len(bodies), 1)
        tris = bodies[0]["triangles"]
        self.assertEqual(len(tris), 12)
        self.assertEqual(bodies[0]["layer"], 1)
        zs = [p[2] for t in tris for p in t]
        self.assertAlmostEqual(max(zs), 0.5, places=6)
        # a convex radius pushes every face out along its normal: the top rises by the radius
        tris = sfbodies.blob_bodies(convex_blob(v, f, radius=0.05))[0]["triangles"]
        self.assertAlmostEqual(max(p[2] for t in tris for p in t), 0.55, places=5)
        self.assertAlmostEqual(min(p[0] for t in tris for p in t), -0.05, places=5)

    def test_body_position_and_rotation_are_applied(self):
        v, f = cube((0, 0, 0), (1, 1, 1))
        q = (0, 0, math.sin(math.pi / 4), math.cos(math.pi / 4))       # 90 degrees about +z (counter-clockwise)
        tris = sfbodies.blob_bodies(convex_blob(v, f, pos=(10, 0, 0), quat=q))[0]["triangles"]
        pts = {tuple(round(c, 5) for c in p) for t in tris for p in t}
        self.assertIn((10.0, 1.0, 0.0), pts)                        # (1, 0, 0) -> (0, 1, 0), then + (10, 0, 0)
        self.assertIn((9.0, 0.0, 1.0), pts)                         # (0, 1, 1) -> (-1, 0, 1)

    def test_sphere_is_an_octahedron_of_its_radius(self):
        w = convex_blob([(1, 2, 3)], [], radius=0.5, kind="hknpSphereShape")
        tris = sfbodies.blob_bodies(w)[0]["triangles"]
        self.assertEqual(len(tris), 8)
        self.assertAlmostEqual(max(p[2] for t in tris for p in t), 3.5)

    def test_compressed_mesh_quad_and_unused_slot(self):
        packed = [(0, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0)]
        prims = [(0, 1, 2, 3), (0x2D, 0x2D, 0x2D, 0x2D), (1, 1, 1, 1)]   # quad, unused 0xDEAD-style slot, point
        tris = sfbodies.blob_bodies(mesh_blob(packed, prims, section_off=(5, 0, 2)))[0]["triangles"]
        self.assertEqual(len(tris), 2)
        pts = {tuple(round(c, 5) for c in p) for t in tris for p in t}
        self.assertEqual(pts, {(5.0, 0.0, 2.0), (6.0, 0.0, 2.0), (6.0, 1.0, 2.0), (5.0, 1.0, 2.0)})

    def test_compressed_mesh_out_of_range_section_is_an_error(self):
        blob = bytearray(mesh_blob([(0, 0, 0)] * 3, [(0, 1, 2, 2)]))
        # claim 9 packed vertices in a section whose array holds 3
        at = blob.find(struct.pack("<3f", 0.01, 0.01, 0.01)) + 28
        blob[at] = 9
        with self.assertRaises(sfbodies.BodyError):
            sfbodies.blob_bodies(bytes(blob))

    def test_unsupported_shape_raises(self):
        v, f = cube((0, 0, 0), (1, 1, 1))
        with self.assertRaises(sfbodies.BodyError):
            sfbodies.blob_bodies(convex_blob(v, f, kind="hknpCapsuleThing"))

    def test_nif_node_transform_places_each_body(self):
        v, f = cube((0, 0, 0), (1, 1, 1))
        blob = convex_blob(v, f)
        rot = (0, -1, 0, 1, 0, 0, 0, 0, 1)                           # +x -> +y (row-major)
        n = sfnif.build_static_nif(b"Test", [], child_collision_blobs=[blob, (blob, (0, 0, 3), rot)])
        bodies = sfbodies.nif_bodies(nif.serialize(n))
        self.assertEqual(len(bodies), 2)
        first = {tuple(round(c, 5) for c in p) for t in bodies[0]["triangles"] for p in t}
        second = {tuple(round(c, 5) for c in p) for t in bodies[1]["triangles"] for p in t}
        self.assertIn((1.0, 1.0, 1.0), first)
        self.assertIn((0.0, 1.0, 3.0), second)                       # (1, 0, 0) rotated to (0, 1, 0), lifted 3
        self.assertIn((-1.0, 1.0, 4.0), second)
        st = sfbodies.triangle_stats(bodies)
        self.assertEqual(st["bodies"], 2)
        self.assertEqual(st["max"][2], 4.0)

    def test_box_triangles_cover_the_box(self):
        tris = sfbodies.box_triangles((0, 0, 1), (1, 2, 1))
        self.assertEqual(len(tris), 12)
        pts = {p for t in tris for p in t}
        self.assertEqual(len(pts), 8)
        self.assertEqual(max(p[2] for p in pts), 2)


if __name__ == "__main__":
    unittest.main()
