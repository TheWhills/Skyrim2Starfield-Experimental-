"""Decode the collision geometry stored in Fallout 4 NIFs (bhkPhysicsSystem -> Havok 2014 packfile, hknp shapes) into
plain triangles in NIF space (Havok metres x 70 = FO4 units are NOT applied: hknp stores metres... see UNIT below).

FO4 collision is authored for gameplay: stairs are ramps, walls are simplified, clutter and trim are left out. Using it as
the source for Starfield collision is far better than guessing from the render mesh.

Supported shapes: hknpCompressedMeshShape (the usual architecture / prop mesh collision) and hknpConvexPolytopeShape.
Layouts (hk_2014.1.0-r1, 64-bit) were decoded from vanilla files; offsets are relative to each object.
"""
import struct
from typing import List, Tuple

from . import hkpackfile

Vec = Tuple[float, float, float]

# hknpCompressedMeshShapeData
CMD_SECTIONS, CMD_PRIMITIVES, CMD_SHARED_INDEX, CMD_PACKED, CMD_SHARED = 80, 96, 112, 128, 144
CMD_DOMAIN = 32                                      # hkAabb of the whole mesh (min xyzw, max xyzw)
SECTION_SIZE = 96
# section: nodes hkArray(16), domain hkAabb(32), codecParms float[6] @48 (offset xyz, scale xyz),
# firstPackedVertex u32 @72, sharedVertices u32 @76 (start<<8 | count), primitives u32 @80 (start<<8 | count),
# dataRuns u32 @84, numPackedVertices u8 @88, numSharedIndices u8 @89


def _compressed_mesh(p: hkpackfile.Packfile, data_obj: int) -> Tuple[List[Vec], List[Tuple[int, int, int]]]:
    sec_at, nsec = p.array(data_obj + CMD_SECTIONS)
    prim_at, _ = p.array(data_obj + CMD_PRIMITIVES)
    sidx_at, _ = p.array(data_obj + CMD_SHARED_INDEX)
    pack_at, _ = p.array(data_obj + CMD_PACKED)
    shar_at, nshared = p.array(data_obj + CMD_SHARED)
    dmin = p.unpack("<3f", data_obj + CMD_DOMAIN)
    dmax = p.unpack("<3f", data_obj + CMD_DOMAIN + 16)
    # shared vertices: 21 / 21 / 22 bits quantised over the whole domain
    shared = []
    for k in range(nshared):
        v, = p.unpack("<Q", shar_at + 8 * k)
        q = (v & 0x1FFFFF, (v >> 21) & 0x1FFFFF, v >> 42)
        bits = (0x1FFFFF, 0x1FFFFF, 0x3FFFFF)
        shared.append(tuple(dmin[a] + q[a] * (dmax[a] - dmin[a]) / bits[a] for a in range(3)))
    points: List[Vec] = []
    tris = []
    for s in range(nsec):
        so = sec_at + SECTION_SIZE * s
        off = p.unpack("<3f", so + 48)
        scale = p.unpack("<3f", so + 60)
        first_packed, shared_d, prim_d = p.unpack("<3I", so + 72)
        npacked, = p.unpack("<B", so + 88)
        sh_start = shared_d >> 8
        local = []
        for k in range(npacked):
            v, = p.unpack("<I", pack_at + 4 * (first_packed + k))
            q = (v & 0x7FF, (v >> 11) & 0x7FF, v >> 22)          # 11 / 11 / 10 bits
            local.append(len(points))
            points.append(tuple(off[a] + q[a] * scale[a] for a in range(3)))
        cache = {}

        def vertex(i):
            if i < npacked:
                return local[i]
            if i not in cache:
                j, = p.unpack("<H", sidx_at + 2 * (sh_start + i - npacked))
                if j >= len(shared):
                    raise hkpackfile.PackfileError(f"shared vertex index {j} out of range ({len(shared)})")
                cache[i] = len(points)
                points.append(shared[j])
            return cache[i]
        pstart, pcount = prim_d >> 8, prim_d & 0xFF
        limit = npacked + p.unpack("<B", so + 89)[0]      # packed + shared vertex slots of this section
        for k in range(pcount):
            a, b, c, d = p.raw(prim_at + 4 * (pstart + k), 4)
            if max(a, b, c, d) >= limit or a == b == c == d:   # unused (0xDEAD) slot or degenerate point: no triangle
                continue
            tris.append((vertex(a), vertex(b), vertex(c)))
            if c != d:                                   # quad
                tris.append((vertex(a), vertex(c), vertex(d)))
    return points, tris


# hknpPhysicsSystemData: bodyCinfos hkArray @64, 96 bytes each: shape pointer @0, position hkVector4 @48,
# orientation quaternion (x, y, z, w) @64
SYS_BODIES, BODY_SIZE, BODY_POS, BODY_ROT = 64, 96, 48, 64
CMS_DATA = 96                                        # hknpCompressedMeshShape -> hknpCompressedMeshShapeData pointer
# hknpConvexPolytopeShape: hkRelArray (u16 count, u16 offset from the field) vertices @48 (hkVector4),
# faces @68 (u16 first index, u8 count, u8 angle), indices @72 (u8)
CVX_VERTS, CVX_FACES, CVX_INDICES = 48, 68, 72


def _rel(p, field):
    n, off = p.unpack("<HH", field)
    return field + off, n


def _convex(p: hkpackfile.Packfile, obj: int):
    va, nv = _rel(p, obj + CVX_VERTS)
    fa, nf = _rel(p, obj + CVX_FACES)
    ia, _ = _rel(p, obj + CVX_INDICES)
    pts = [p.unpack("<3f", va + 16 * k) for k in range(nv)]
    tris = []
    for k in range(nf):
        first, cnt = p.unpack("<HB", fa + 4 * k)
        idx = list(p.raw(ia + first, cnt))
        tris += [(idx[0], idx[j], idx[j + 1]) for j in range(1, cnt - 1)]
    return pts, tris


def _rotate(q, v):
    x, y, z, w = q
    r = (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
         2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
         2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y))
    return tuple(r[3 * i] * v[0] + r[3 * i + 1] * v[1] + r[3 * i + 2] * v[2] for i in range(3))


def decode_bodies(blob: bytes):
    """[(shape class, points, triangles)] per body of a FO4 bhkPhysicsSystem blob, in the space of the NIF node that owns
    the collision object (metres: FO4's Havok scale is 1/70 game unit, the same as our conversion), plus skipped classes.
    Bodies with a rotation are skipped for now (quaternion convention not verified against a reference)."""
    p = hkpackfile.Packfile(blob)
    classes = dict(p.objects())
    sysobj = next(o for o, c in classes.items() if c == "hknpPhysicsSystemData")
    bodies_at, nbodies = p.array(sysobj + SYS_BODIES)
    bodies, skipped = [], []
    for k in range(nbodies):
        b = bodies_at + BODY_SIZE * k
        shape = p.pointer(b)
        cls = classes.get(shape, "?")
        rot = p.unpack("<4f", b + BODY_ROT)
        if any(abs(x) > 1e-4 for x in rot[:3]):
            skipped.append(cls + " (rotated body)")
            continue
        if cls == "hknpCompressedMeshShape":
            pts, tr = _compressed_mesh(p, p.pointer(shape + CMS_DATA))
        elif cls == "hknpConvexPolytopeShape":
            pts, tr = _convex(p, shape)
        else:
            skipped.append(cls)
            continue
        pos = p.unpack("<3f", b + BODY_POS)
        bodies.append((cls, [tuple(c + t for c, t in zip(v, pos)) for v in pts], tr))
    return bodies, skipped


def decode(blob: bytes) -> Tuple[List[Vec], List[Tuple[int, int, int]], List[str]]:
    """Triangles of every body in a FO4 bhkPhysicsSystem blob merged into one list (see decode_bodies)."""
    p = hkpackfile.Packfile(blob)
    classes = dict(p.objects())
    sysobj = next(o for o, c in classes.items() if c == "hknpPhysicsSystemData")
    bodies_at, nbodies = p.array(sysobj + SYS_BODIES)
    points: List[Vec] = []
    tris = []
    skipped = []
    for k in range(nbodies):
        b = bodies_at + BODY_SIZE * k
        shape = p.pointer(b)
        cls = classes.get(shape, "?")
        if cls == "hknpCompressedMeshShape":
            pts, tr = _compressed_mesh(p, p.pointer(shape + CMS_DATA))
        elif cls == "hknpConvexPolytopeShape":
            pts, tr = _convex(p, shape)
        else:
            skipped.append(cls)
            continue
        pos = p.unpack("<3f", b + BODY_POS)
        rot = p.unpack("<4f", b + BODY_ROT)
        base = len(points)
        points += [tuple(r + t for r, t in zip(_rotate(rot, v), pos)) for v in pts]
        tris += [(a + base, b_ + base, c + base) for a, b_, c in tr]
    return points, tris, skipped

def compressed_mesh_keys(p: hkpackfile.Packfile, data_obj: int):
    """[(shape key, (min xyz, max xyz))] per triangle of a compressed mesh. Key = section << 8 | primitive << 1 | t,
    t = 1 for the second triangle of a quad (matches maxKeyValue / numPrimitiveKeys in FO4 and vanilla Starfield)."""
    pts, _ = [], None
    sec_at, nsec = p.array(data_obj + CMD_SECTIONS)
    points, tris = _compressed_mesh(p, data_obj)        # same order: per section, per primitive, quads split
    out, k = [], 0
    prim_at, _ = p.array(data_obj + CMD_PRIMITIVES)
    for s in range(nsec):
        prim_d, = p.unpack("<I", sec_at + SECTION_SIZE * s + 80)
        pstart, pcount = prim_d >> 8, prim_d & 0xFF
        so = sec_at + SECTION_SIZE * s
        limit = p.unpack("<B", so + 88)[0] + p.unpack("<B", so + 89)[0]
        for j in range(pcount):
            a, b, c, d = p.raw(prim_at + 4 * (pstart + j), 4)
            if max(a, b, c, d) >= limit or a == b == c == d:   # unused (0xDEAD) slot / degenerate: no key
                continue
            for t in ((0,) if c == d else (0, 1)):
                tri = tris[k]
                k += 1
                P = [points[i] for i in tri]
                lo = tuple(min(q[x] for q in P) for x in range(3))
                hi = tuple(max(q[x] for q in P) for x in range(3))
                out.append(((s << 8) | (j << 1) | t, (lo, hi)))
    return out
