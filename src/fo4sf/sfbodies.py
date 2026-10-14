"""Read back the collision of a CONVERTED Starfield NIF (our converter's output) as plain triangles.

Used to know where a placed object's solid surfaces are (terrain experiment 2c: the top of a floor a dropped player
lands on). The NIF side follows sfnif.build_static_nif: every bhkNPCollisionObject (target node i32, flags u16,
bhkPhysicsSystem block i32) holds one Havok tagfile; the target node's world transform (nif.world_transforms, metres)
places it. Inside each tagfile, the physics system's body cinfos point at the shape:

  hknpCompressedMeshShape  meshcollision's Starfield section layout (@48 codec offset, @60 scale, @72 firstPacked,
                           @76 firstShared, @80 firstPrimitive, @88 numPacked u8, @89 numPrimitives u8); a primitive
                           slot is used only when all four indices are inside the section's packed + shared vertices
                           (the section's shared count = next section's firstShared - its own, as in FO4's arrays)
  hknpConvexShape / hknpSphereShape / hknpBoxShape   the hull: float3 vertices, faces (u16 first index, u8 count,
                           u8 angle) into u8 indices; convexRadius pushes every face out along its normal (a sphere is
                           its centre vertex + radius, returned as an octahedron)

Body position / orientation (quaternion x, y, z, w) are applied (our converter writes identity).
Everything is metres in the NIF's root space.
"""
import math
import struct
from typing import Dict, List, Tuple

from . import hktagfile, sfcollision
from . import nif as nifmod

Vec = Tuple[float, float, float]
Tri = Tuple[Vec, Vec, Vec]

SECTION_SIZE = 96


class BodyError(ValueError):
    pass


def _type_index(tf: hktagfile.Tagfile, name: str):
    for t in tf.types:
        if tf.type_name(t.index) == name:
            return t.index
    return None


def _field(tf: hktagfile.Tagfile, type_idx: int, name: str) -> hktagfile.Field:
    for f in tf.all_fields(type_idx):
        if f.name == name:
            return f
    raise BodyError(f"type {tf.type_name(type_idx)} has no field {name}")


class _Reader:
    def __init__(self, blob: bytes):
        self.tf = hktagfile.Tagfile(blob)
        self.b, self.D = self.tf.blob, self.tf.data_start
        self.ptr = {}
        for _, offs in self.tf.patches:
            for o in offs:
                idx, = struct.unpack_from("<Q", self.b, self.D + o)
                if 0 < idx < len(self.tf.items):
                    self.ptr[self.D + o] = self.tf.items[idx]

    def items_of(self, name):
        ti = _type_index(self.tf, name)
        return [] if ti is None else [it for it in self.tf.items[1:] if it.type == ti]

    def target(self, at):
        """(absolute offset, count, item) of the item a pointer / array / relarray field at `at` points to."""
        it = self.ptr.get(at)
        return (self.D + it.offset, it.count, it) if it else (0, 0, None)


def _quat_apply(q, v):
    x, y, z, w = q
    r = (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
         2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
         2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y))
    return tuple(r[3 * i] * v[0] + r[3 * i + 1] * v[1] + r[3 * i + 2] * v[2] for i in range(3))


def _cms_triangles(r: _Reader, cms_at: int, cms_type: int) -> List[Tri]:
    tf, b, D = r.tf, r.b, r.D
    data_at, _, data_item = r.target(cms_at + _field(tf, cms_type, "data").offset)
    if not data_at:
        raise BodyError("compressed mesh without data")
    f_tree = _field(tf, data_item.type, "meshTree")                 # hknpCompressedMeshShapeData.meshTree
    t_tree = f_tree.type
    tree = data_at + f_tree.offset

    def arr(name):
        at, n, _ = r.target(tree + _field(tf, t_tree, name).offset)
        return at, n
    dmin = struct.unpack_from("<3f", b, tree + 16)
    dmax = struct.unpack_from("<3f", b, tree + 32)
    sec_at, nsec = arr("sections")
    prim_at, nprim_total = arr("primitives")
    sidx_at, nsidx = arr("sharedVerticesIndex")
    pack_at, npack_total = arr("packedVertices")
    shar_at, nshared = arr("sharedVertices")
    bits = (0x1FFFFF, 0x1FFFFF, 0x3FFFFF)
    shared = []
    for k in range(nshared):
        v, = struct.unpack_from("<Q", b, shar_at + 8 * k)
        q = (v & 0x1FFFFF, (v >> 21) & 0x1FFFFF, v >> 42)
        shared.append(tuple(dmin[a] + q[a] * (dmax[a] - dmin[a]) / bits[a] for a in range(3)))
    firsts = [struct.unpack_from("<I", b, sec_at + SECTION_SIZE * s + 76)[0] for s in range(nsec)]
    tris = []
    for s in range(nsec):
        so = sec_at + SECTION_SIZE * s
        off, scale = struct.unpack_from("<3f", b, so + 48), struct.unpack_from("<3f", b, so + 60)
        first_packed, first_shared, first_prim, _ = struct.unpack_from("<4I", b, so + 72)
        npacked, nprim = b[so + 88], b[so + 89]
        nsh = (firsts[s + 1] if s + 1 < nsec else nsidx) - first_shared
        if nsh < 0 or first_shared + nsh > nsidx or first_packed + npacked > npack_total or first_prim + nprim > nprim_total:
            raise BodyError(f"section {s} indexes outside its arrays")
        limit = npacked + nsh

        def vert(i):
            if i < npacked:
                v, = struct.unpack_from("<I", b, pack_at + 4 * (first_packed + i))
                q = (v & 0x7FF, (v >> 11) & 0x7FF, v >> 22)
                return tuple(off[a] + q[a] * scale[a] for a in range(3))
            j, = struct.unpack_from("<H", b, sidx_at + 2 * (first_shared + i - npacked))
            if j >= nshared:
                raise BodyError(f"shared vertex {j} out of range ({nshared})")
            return shared[j]
        for k in range(nprim):
            i0, i1, i2, i3 = b[prim_at + 4 * (first_prim + k):prim_at + 4 * (first_prim + k) + 4]
            if max(i0, i1, i2, i3) >= limit or i0 == i1 == i2 == i3:     # unused slot or degenerate point
                continue
            tris.append((vert(i0), vert(i1), vert(i2)))
            if i2 != i3:
                tris.append((vert(i0), vert(i2), vert(i3)))
    return tris


def _hull_triangles(r: _Reader, shape_at: int, shape_type: int, kind: str) -> List[Tri]:
    tf, b = r.tf, r.b
    hull = _field(tf, shape_type, "hull")
    radius, = struct.unpack_from("<f", b, shape_at + _field(tf, shape_type, "convexRadius").offset)
    va, nv, vit = r.target(shape_at + hull.offset + _field(tf, hull.type, "vertices").offset)
    if not nv:
        raise BodyError(f"{kind} without hull vertices")
    stride = tf.size_of(vit.type) or 12
    verts = [struct.unpack_from("<3f", b, va + stride * k) for k in range(nv)]
    if kind == "hknpSphereShape":
        c, rr = verts[0], radius
        o = [(c[0] + rr, c[1], c[2]), (c[0] - rr, c[1], c[2]), (c[0], c[1] + rr, c[2]), (c[0], c[1] - rr, c[2]),
             (c[0], c[1], c[2] + rr), (c[0], c[1], c[2] - rr)]
        return [(o[a], o[bb], o[z]) for a in (0, 1) for bb in (2, 3) for z in (4, 5)]
    fa, nf, _ = r.target(shape_at + hull.offset + _field(tf, hull.type, "faces").offset)
    ia, ni, _ = r.target(shape_at + hull.offset + _field(tf, hull.type, "indices").offset)
    centre = tuple(sum(v[a] for v in verts) / nv for a in range(3))
    tris = []
    for k in range(nf):
        first, cnt = struct.unpack_from("<HB", b, fa + 4 * k)
        if cnt < 3 or first + cnt > ni:
            raise BodyError(f"hull face {k} indexes outside the index array")
        idx = list(b[ia + first:ia + first + cnt])
        if max(idx) >= nv:
            raise BodyError(f"hull face {k} uses vertex {max(idx)} of {nv}")
        poly = [verts[i] for i in idx]
        if radius:
            u = [poly[1][a] - poly[0][a] for a in range(3)]
            w = [poly[2][a] - poly[0][a] for a in range(3)]
            n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
            ln = math.sqrt(sum(x * x for x in n)) or 1.0
            n = [x / ln for x in n]
            if sum(n[a] * (poly[0][a] - centre[a]) for a in range(3)) < 0:
                n = [-x for x in n]
            poly = [tuple(p[a] + radius * n[a] for a in range(3)) for p in poly]
        tris += [(poly[0], poly[j], poly[j + 1]) for j in range(1, cnt - 1)]
    return tris


def box_triangles(centre, half) -> List[Tri]:
    """The 12 triangles of an axis-aligned box."""
    c = [tuple(centre[a] + (half[a] if (k >> a) & 1 else -half[a]) for a in range(3)) for k in range(8)]
    quads = [(0, 2, 6, 4), (1, 5, 7, 3), (0, 4, 5, 1), (2, 3, 7, 6), (0, 1, 3, 2), (4, 6, 7, 5)]
    return [t for q in quads for t in ((c[q[0]], c[q[1]], c[q[2]]), (c[q[0]], c[q[2]], c[q[3]]))]


def blob_bodies(blob: bytes) -> List[dict]:
    """[{"shape": class, "layer": collision layer, "triangles": [...]}] for every body of one Starfield tagfile physics
    system, in the space of the NIF node that owns it. Unsupported shapes raise BodyError."""
    r = _Reader(blob)
    tf = r.tf
    t_body = _type_index(tf, "hknpPhysicsSystemData::bodyCinfoWithAttachment")
    if t_body is None:
        raise BodyError("no body cinfo type")
    size = tf.size_of(t_body)
    f_shape, f_pos = _field(tf, t_body, "shape"), _field(tf, t_body, "position")
    f_rot, f_filter = _field(tf, t_body, "orientation"), _field(tf, t_body, "collisionFilterInfo")
    out = []
    for it in r.items_of("hknpPhysicsSystemData::bodyCinfoWithAttachment"):
        for k in range(it.count):
            at = r.D + it.offset + size * k
            s_at, _, s_item = r.target(at + f_shape.offset)
            if s_item is None:
                raise BodyError(f"body {k} has no shape")
            kind = tf.type_name(s_item.type)
            if kind == "hknpCompressedMeshShape":
                tris = _cms_triangles(r, s_at, s_item.type)
            elif kind == "hknpBoxShape" and len(blob) == sfcollision.BLOB_SIZE:
                tris = box_triangles(*sfcollision.read_box(blob))   # the vanilla box template (sfcollision.box_blob)
            elif kind in ("hknpConvexShape", "hknpConvexPolytopeShape", "hknpSphereShape", "hknpBoxShape"):
                tris = _hull_triangles(r, s_at, s_item.type, kind)
            else:
                raise BodyError(f"unsupported shape {kind}")
            pos = struct.unpack_from("<3f", r.b, at + f_pos.offset)
            q = struct.unpack_from("<4f", r.b, at + f_rot.offset)
            if any(abs(x) > 1e-6 for x in q[:3]) or any(abs(x) > 1e-6 for x in pos):
                if not all(math.isfinite(x) for x in pos + q):
                    raise BodyError(f"body {k} has a non-finite transform")
                tris = [tuple(tuple(a + c for a, c in zip(_quat_apply(q, v), pos)) for v in t) for t in tris]
            layer = struct.unpack_from("<I", r.b, at + f_filter.offset)[0] & 0x7F
            out.append({"shape": kind, "layer": layer, "triangles": tris})
    return out


def nif_bodies(nif_bytes: bytes) -> List[dict]:
    """Every collision body of a Starfield NIF with its triangles in NIF root space (metres):
    [{"node": block, "shape", "layer", "triangles"}]."""
    f = nifmod.parse(nif_bytes)
    world = nifmod.world_transforms(f)
    out = []
    for i in range(len(f.blocks)):
        if f.type_of(i) != "bhkNPCollisionObject":
            continue
        target, _, data = struct.unpack_from("<iHi", f.blocks[i], 0)
        if not (0 <= target < len(f.blocks)) or not (0 <= data < len(f.blocks)) or f.type_of(data) != "bhkPhysicsSystem":
            raise BodyError(f"collision object {i}: bad target or data")
        n, = struct.unpack_from("<I", f.blocks[data], 0)
        t, rot, s = world(target)

        def place(v):
            return tuple(t[a] + s * (rot[3 * a] * v[0] + rot[3 * a + 1] * v[1] + rot[3 * a + 2] * v[2]) for a in range(3))
        for body in blob_bodies(f.blocks[data][4:4 + n]):
            body["triangles"] = [tuple(place(v) for v in tri) for tri in body["triangles"]]
            body["node"] = target
            out.append(body)
    return out


def triangle_stats(bodies: List[dict]) -> Dict[str, object]:
    """Small summary for reports: body count, shape classes, triangles, bounds."""
    tris = [t for b in bodies for t in b["triangles"]]
    if not tris:
        return {"bodies": len(bodies), "triangles": 0}
    pts = [v for t in tris for v in t]
    return {"bodies": len(bodies), "shapes": sorted({b["shape"] for b in bodies}), "triangles": len(tris),
            "min": [round(min(p[a] for p in pts), 4) for a in range(3)],
            "max": [round(max(p[a] for p in pts), 4) for a in range(3)]}
