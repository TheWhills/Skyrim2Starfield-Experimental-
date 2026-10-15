"""Skyrim (Special Edition, NIF 20.2.0.7 / BS 100; Skyrim LE BS 83 for collision) mesh reading for the converter:
render geometry, shader textures, alpha testing, and Skyrim's own Havok collision decoded to triangles.

Geometry (returned as nif.Fo4Shape so the existing converter code can take it):
* BSTriShape (BS 100): NiAVObject fields as FO4, then bounding sphere, skin, shader, alpha refs,
  u64 vertex descriptor, u16 triangle count (u32 only from BS 130), u16 vertex count, u32 data size. Vertex attribute
  offsets come from the descriptor's nibbles (x 4 bytes); positions are always full floats in BS 100 (BSVertexDataSSE).
* NiTriShape / NiTriStrips + their data blocks (older-style meshes, common in mods): parsed with and without the
  optional "Material CRC" field, keeping the variant that consumes the block exactly.
* BSLODTriShape: Skyrim's is an NiTriShape (NiTriBasedGeom: data block, skin, materials, shader, alpha) plus LOD0 /
  LOD1 / LOD2 triangle counts (nif.xml; vanilla tree stumps, logs and flora use it). Verified on the owner's files: an
  earlier reading as a BSTriShape failed on 16 of 3,000 vanilla meshes (2026-10-15 first run).
Shapes carry WORLD transforms (nif.world_transforms: every NiNode ancestor composed), as nif.fo4_trishapes does.

Collision (`collision_triangles`): bhkCollisionObject -> bhkRigidBody[T] -> shape tree. Supported shapes:
bhkMoppBvTreeShape, bhkCompressedMeshShape (+ data: chunks with strips / lists and big triangles), bhkPackedNiTriStrips-
Shape (+ hkPackedNiTriStripsData), bhkBoxShape, bhkSphereShape, bhkCapsuleShape, bhkConvexVerticesShape, bhkList-
Shape, bhkConvexListShape, bhkTransformShape, bhkConvexTransformShape. The rigid body's own transform applies (plain
and T bodies), then Skyrim's havok scale (69.99124 game units per havok unit), then the target node's world transform. Anything else is reported
by name, never guessed.

Field layouts follow niftools' nif.xml for Skyrim / Skyrim SE. They are checked here against synthetic files only; the
per-model sanity report (collision bounds against render bounds) is the check on real data.
"""
import math
import struct
from typing import List, Optional, Tuple

from . import nif as nifmod

HAVOK_SCALE = 69.99124             # Skyrim game units per havok unit (tes4skyrim measured 69.9913 in SkyrimSE.exe)
CMS_STEP = 0.001                   # compressed-mesh chunk vertices: u16 offsets in 1/1000 havok-unit steps
BS_SSE = 100
TRI_TYPES = ("BSTriShape", "BSMeshLODTriShape")                 # BSTriShape layout (vertex buffer in the block)
NITRI_TYPES = ("NiTriShape", "NiTriStrips", "BSLODTriShape")    # NiTriBasedGeom layout (separate data block)
VF_VERTEX, VF_UV, VF_NORMAL, VF_TANGENT, VF_COLOR, VF_SKIN = 0x1, 0x2, 0x8, 0x10, 0x20, 0x40


def _av_size(blk: bytes) -> int:
    """Bytes of the NiAVObject part (name, extra data, controller, flags, transform, collision ref): BS 83/100/130."""
    _, nextra = struct.unpack_from("<iI", blk, 0)
    return 8 + 4 * nextra + 4 + 4 + 52 + 4


def _name(n, blk):
    idx, = struct.unpack_from("<i", blk, 0)
    return n.strings[idx] if 0 <= idx < len(n.strings) else b""


# ------------------------------------------------------------------------------------------------- render geometry
def _bstrishape(n, i, blk, world):
    p = _av_size(blk) + 16
    skin, shader, alpha = struct.unpack_from("<iii", blk, p); p += 12
    desc, = struct.unpack_from("<Q", blk, p); p += 8
    if n.bs_version >= 130:
        ntri, nvert, dsize = struct.unpack_from("<IHI", blk, p); p += 10
    else:
        ntri, nvert, dsize = struct.unpack_from("<HHI", blk, p); p += 8
    if dsize == 0 or nvert == 0:
        return None
    vsize = (desc & 0xF) * 4
    attrs = (desc >> 44) & 0xFFF
    if dsize != vsize * nvert + ntri * 6:
        raise nifmod.NifError(f"block {i}: data size {dsize} != {vsize}*{nvert}+{ntri}*6")
    o_uv, o_n, o_t, o_c = (((desc >> s) & 0xF) * 4 for s in (8, 16, 20, 24))
    full = n.bs_version < 130 or attrs & 0x400       # BS 100 always stores float positions
    pos, uv, nor, tan, col = [], [], [], [], []
    unb = lambda b: tuple(c / 255.0 * 2.0 - 1.0 for c in b[:3])   # noqa: E731
    for v in range(nvert):
        q = p + v * vsize
        if attrs & VF_VERTEX:
            pos.append(struct.unpack_from("<3f", blk, q) if full else tuple(struct.unpack_from("<3e", blk, q)))
        if attrs & VF_UV:
            uv.append(tuple(struct.unpack_from("<2e", blk, q + o_uv)))
        if attrs & VF_NORMAL:
            nor.append(unb(blk[q + o_n:q + o_n + 4]))
            if attrs & VF_TANGENT:
                tan.append(unb(blk[q + o_t:q + o_t + 4]))
        if attrs & VF_COLOR:
            col.append(tuple(blk[q + o_c:q + o_c + 4]))
    p += vsize * nvert
    tris = list(struct.iter_unpack("<HHH", blk[p:p + ntri * 6]))
    if n.type_of(i) == "BSMeshLODTriShape" and len(blk) >= 12:
        sizes = struct.unpack_from("<3I", blk, len(blk) - 12)
        if sum(sizes) == ntri and max(sizes) > 0:      # all LOD levels back to back: keep the most detailed
            k = max(range(3), key=lambda j: sizes[j])
            tris = tris[sum(sizes[:k]):sum(sizes[:k]) + sizes[k]]
    tr, rot, scale = world(i)
    return nifmod.Fo4Shape(_name(n, blk), tr, rot, scale, shader, alpha, skin, pos, uv, nor, tan, col, tris,
                           bool(attrs & VF_SKIN), i)


def _geom_data(d: bytes, crc: bool, strips: bool):
    """(positions, uvs, normals, tangents, colours, triangles) of NiTriShapeData / NiTriStripsData (20.2.0.7,
    Bethesda), or None when this layout variant does not consume the block exactly."""
    try:
        p = 4                                                  # group id
        nv, = struct.unpack_from("<H", d, p); p += 2
        p += 2                                                 # keep / compress flags
        has_v = d[p]; p += 1
        pos = list(struct.iter_unpack("<3f", d[p:p + 12 * nv])) if has_v else []
        p += 12 * nv if has_v else 0
        vflags, = struct.unpack_from("<H", d, p); p += 2
        if crc:
            p += 4
        has_n = d[p]; p += 1
        nor = list(struct.iter_unpack("<3f", d[p:p + 12 * nv])) if has_n else []
        p += 12 * nv if has_n else 0
        tan = []
        if has_n and vflags & 0x1000:
            tan = list(struct.iter_unpack("<3f", d[p:p + 12 * nv]))
            p += 24 * nv                                       # tangents, bitangents
        p += 16                                                # centre, radius
        has_c = d[p]; p += 1
        col = []
        if has_c:
            col = [tuple(int(max(0.0, min(1.0, c)) * 255 + 0.5) for c in rgba)
                   for rgba in struct.iter_unpack("<4f", d[p:p + 16 * nv])]
            p += 16 * nv
        nuv = vflags & 0x3F
        uv = list(struct.iter_unpack("<2f", d[p:p + 8 * nv])) if nuv else []
        p += 8 * nv * nuv
        p += 2 + 4                                             # consistency flags, additional data
        ntri, = struct.unpack_from("<H", d, p); p += 2
        tris = []
        if strips:
            ns, = struct.unpack_from("<H", d, p); p += 2
            lens = struct.unpack_from(f"<{ns}H", d, p); p += 2 * ns
            has_p = d[p]; p += 1
            if has_p:
                for ln in lens:
                    s = struct.unpack_from(f"<{ln}H", d, p); p += 2 * ln
                    for k in range(ln - 2):
                        a, b, c = s[k], s[k + 1], s[k + 2]
                        if a != b and b != c and a != c:
                            tris.append((a, b, c) if k % 2 == 0 else (a, c, b))
        else:
            p += 4                                             # number of triangle points
            has_t = d[p]; p += 1
            if has_t:
                tris = list(struct.iter_unpack("<3H", d[p:p + 6 * ntri])); p += 6 * ntri
            nm, = struct.unpack_from("<H", d, p); p += 2
            for _ in range(nm):
                k, = struct.unpack_from("<H", d, p); p += 2 + 2 * k
        if p != len(d) or len(pos) != nv:
            return None
        return pos, uv, nor, tan, col, tris
    except (struct.error, IndexError):
        return None


def _nitrishape(n, i, blk, world):
    p = _av_size(blk)
    data, skin, nmat = struct.unpack_from("<iiI", blk, p); p += 12
    p += 8 * nmat + 4 + 1                                      # material names + extra, active material, needs update
    shader, alpha = struct.unpack_from("<ii", blk, p)
    if not (0 <= data < len(n.blocks)):
        return None
    strips = n.type_of(data) == "NiTriStripsData"
    if n.type_of(data) not in ("NiTriShapeData", "NiTriStripsData"):
        return None
    got = _geom_data(n.blocks[data], False, strips) or _geom_data(n.blocks[data], True, strips)
    if got is None:
        raise nifmod.NifError(f"block {data}: {n.type_of(data)} layout not recognised")
    pos, uv, nor, tan, col, tris = got
    if n.type_of(i) == "BSLODTriShape" and len(blk) >= p + 8 + 12:
        sizes = struct.unpack_from("<3I", blk, p + 8)
        if sum(sizes) == len(tris) and max(sizes) > 0:          # LOD levels back to back: keep the most detailed
            k = max(range(3), key=lambda j: sizes[j])
            tris = tris[sum(sizes[:k]):sum(sizes[:k]) + sizes[k]]
    tr, rot, scale = world(i)
    return nifmod.Fo4Shape(_name(n, blk), tr, rot, scale, shader, alpha, skin, pos, uv, nor, tan, col, tris,
                           skin >= 0, i)


def trishapes(n: nifmod.NifFile) -> List[nifmod.Fo4Shape]:
    """Every renderable triangle shape of a Skyrim NIF with its world transform (game units)."""
    if n.bs_version >= 130:
        return nifmod.fo4_trishapes(n)
    world = nifmod.world_transforms(n)
    out = []
    for i, blk in enumerate(n.blocks):
        t = n.type_of(i)
        if t in TRI_TYPES:
            s = _bstrishape(n, i, blk, world)
        elif t in NITRI_TYPES:
            s = _nitrishape(n, i, blk, world)
        else:
            continue
        if s is not None and s.positions and s.triangles:
            out.append(s)
    return out


# ------------------------------------------------------------------------------------------------- shader / alpha
def texture_set(n, shader_ref) -> Optional[List[str]]:
    """Texture paths of a BSLightingShaderProperty's BSShaderTextureSet (Skyrim slots: 0 diffuse, 1 normal (specular
    in alpha), 2 glow / skin, 3 height, 4 environment, 5 environment mask, 6 multilayer, 7 backlight), or None."""
    if not (0 <= shader_ref < len(n.blocks)) or n.type_of(shader_ref) != "BSLightingShaderProperty":
        return None
    blk = n.blocks[shader_ref]
    n_extra, = struct.unpack_from("<I", blk, 8)
    ts, = struct.unpack_from("<i", blk, 12 + 4 * n_extra + 4 + 8 + 16)
    if not (0 <= ts < len(n.blocks)) or n.type_of(ts) != "BSShaderTextureSet":
        return None
    tb = n.blocks[ts]
    count, = struct.unpack_from("<I", tb, 0)
    paths, p = [], 4
    for _ in range(count):
        ln, = struct.unpack_from("<I", tb, p)
        paths.append(texture_path(tb[p + 4:p + 4 + ln].decode("latin-1").rstrip("\0")))
        p += 4 + ln
    return paths


def texture_path(path: str) -> str:
    """A shader texture path as the archives store it: some vanilla meshes keep Bethesda's build folder in front
    ("skyrimhd\\build\\pc\\data\\textures\\plants\\thistle01.dds": owner's first real run, thicket01 / thistle01), so
    everything before the first "textures\\" folder is dropped. Paths without one are returned unchanged."""
    norm = path.replace("/", "\\")
    k = ("\\" + norm.lower()).find("\\textures\\")     # index of "textures" in norm
    return norm[k:] if k > 0 else path


SLSF2_DOUBLE_SIDED = 0x10            # Shader Flags 2 bit 4 (nif.xml SkyrimShaderPropertyFlags2)


def double_sided(n, shader_ref) -> bool:
    """True when the shape's BSLightingShaderProperty sets SLSF2_Double_Sided (leaves, banners, cloth, cobwebs).
    Layout as texture_set: shader type, name, extra data list, controller, Shader Flags 1, Shader Flags 2."""
    if not (0 <= shader_ref < len(n.blocks)) or n.type_of(shader_ref) != "BSLightingShaderProperty":
        return False
    blk = n.blocks[shader_ref]
    n_extra, = struct.unpack_from("<I", blk, 8)
    flags2, = struct.unpack_from("<I", blk, 12 + 4 * n_extra + 8)
    return bool(flags2 & SLSF2_DOUBLE_SIDED)


SKYRIM_SHADER_TYPES = {0: "default", 1: "environment map", 2: "glow", 3: "parallax", 4: "face tint", 5: "skin tint",
                       6: "hair tint", 7: "parallax occlusion", 11: "landscape", 14: "multilayer parallax", 15: "tree",
                       16: "eye environment", 18: "snow", 19: "sparkle snow"}


def shader_info(n, shader_ref) -> dict:
    """What a shape's shader property says, for inspection: block type, Skyrim shader type (lighting only), Shader
    Flags 1 / 2, emissive colour and multiple, textures (lighting: the texture set; effect: the source and greyscale
    textures). Layouts as texture_set (SSE, BS 100)."""
    if not (0 <= shader_ref < len(n.blocks)):
        return {"type": None}
    t, blk = n.type_of(shader_ref), n.blocks[shader_ref]
    info = {"type": t}
    try:
        if t == "BSLightingShaderProperty":
            st, = struct.unpack_from("<I", blk, 0)
            n_extra, = struct.unpack_from("<I", blk, 8)
            p = 12 + 4 * n_extra + 4
            f1, f2 = struct.unpack_from("<II", blk, p)
            p += 8 + 16 + 4                                    # flags, UV offset + scale, texture set
            emit = struct.unpack_from("<4f", blk, p)
            info.update(shader_type=SKYRIM_SHADER_TYPES.get(st, st), flags1=f"{f1:08X}", flags2=f"{f2:08X}",
                        emissive=[round(v, 3) for v in emit[:3]], emissive_multiple=round(emit[3], 3),
                        textures=[x for x in (texture_set(n, shader_ref) or []) if x])
        elif t == "BSEffectShaderProperty":
            n_extra, = struct.unpack_from("<I", blk, 4)
            p = 8 + 4 * n_extra + 4
            f1, f2 = struct.unpack_from("<II", blk, p)
            p += 8 + 16
            ln, = struct.unpack_from("<I", blk, p)
            info.update(flags1=f"{f1:08X}", flags2=f"{f2:08X}",
                        textures=[blk[p + 4:p + 4 + ln].decode("latin-1").rstrip("\0")] if ln else [])
    except struct.error:
        info["error"] = "shader block shorter than expected"
    return info


def alpha_test(n, alpha_ref) -> Tuple[bool, bool, int]:
    """(alpha test, alpha blend, threshold 0..255) from a NiAlphaProperty (flags bit 0 blend, bit 9 test)."""
    if not (0 <= alpha_ref < len(n.blocks)) or n.type_of(alpha_ref) != "NiAlphaProperty":
        return False, False, 128
    blk = n.blocks[alpha_ref]
    p = 8 + 4 * struct.unpack_from("<I", blk, 4)[0] + 4
    flags, thr = struct.unpack_from("<HB", blk, p)
    return bool(flags & 0x200), bool(flags & 0x1), thr


# ------------------------------------------------------------------------------------------------- collision
class CollisionError(ValueError):
    pass


def _quat_matrix(x, y, z, w):
    ln = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / ln, y / ln, z / ln, w / ln
    return (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
            2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
            2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y))


def _apply(m, t, v):
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2] + t[0], m[3] * v[0] + m[4] * v[1] + m[5] * v[2] + t[1],
            m[6] * v[0] + m[7] * v[1] + m[8] * v[2] + t[2])


IDENT = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def _box(lo, hi):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6),
         (3, 0, 4), (3, 4, 7)]
    return v, f


def _hull(points):
    """Triangles of the convex hull of a small point set (scipy-free: meshcollision's hull)."""
    from . import meshcollision
    pts = [tuple(p) for p in points]
    try:
        return pts, [tuple(t) for t in meshcollision.convex_hull_triangles(pts)]
    except Exception:                          # noqa: BLE001  flat / degenerate piece: its bounding box instead
        lo = tuple(min(p[a] for p in pts) for a in range(3))
        hi = tuple(max(p[a] for p in pts) for a in range(3))
        return _box(lo, hi)


RB_TRANSLATION, RB_ROTATION = 52, 68


def _rigid_body_transform(blk) -> Tuple[tuple, tuple, bool]:
    """(translation in havok units, rotation matrix, stored-as-unit) of a bhkRigidBody / bhkRigidBodyT.

    Layout (niftools nif.xml, cross-checked with tes4skyrim's 250-byte bhkRigidBody: bhkWorldObject 28 + bhkEntityCInfo
    4 + bhkRigidBodyCInfo2010 212): CInfo2010 starts at 32 with unused 4, HavokFilter 4, unused 4, UnknownInt1 4,
    response / unused / contact delay 4, so Translation (Vector4) sits at 52 and Rotation (quaternion x y z w) at 68.
    Applied on bhkRigidBodyT only (collision_triangles). CORRECTION 2026-10-15: tes4skyrim's note that Skyrim also
    applies them on plain bhkRigidBody (its trapmace01 example) does not hold for vanilla clutter on the owner's files:
    plain bodies store values the engine evidently ignores (baskets 768 units off, the Orc door repeating its node
    translation), and applying them misplaced 284 surveyed models. A rotation that is not a unit quaternion is reported and treated as identity, never searched for: one
    field off, an identity body reads (0, 0, 1, 0), itself a unit quaternion (a 180 degree turn)."""
    t = struct.unpack_from("<3f", blk, RB_TRANSLATION)
    q = struct.unpack_from("<4f", blk, RB_ROTATION)
    unit = all(math.isfinite(c) for c in q) and abs(sum(c * c for c in q) - 1.0) < 1e-3
    if not unit or not all(math.isfinite(c) and abs(c) < 1e5 for c in t):
        return (0.0, 0.0, 0.0), IDENT, False
    return t, _quat_matrix(*q), True


def _vec4s(d, p, count):
    return [struct.unpack_from("<3f", d, p + 16 * k) for k in range(count)], p + 16 * count


def _cms_data(d: bytes):
    """Vertices (havok units) and triangles of a bhkCompressedMeshShapeData."""
    p = 54                                     # bits, masks, error, AABB min/max, welding and material types
    for _ in range(3):                         # materials 32 / 16 / 8
        k, = struct.unpack_from("<I", d, p); p += 4 + 4 * k
    k, = struct.unpack_from("<I", d, p); p += 4 + 8 * k            # chunk materials
    p += 4                                                          # named materials (0)
    nt, = struct.unpack_from("<I", d, p); p += 4
    transforms = []
    for _ in range(nt):
        t = struct.unpack_from("<3f", d, p)
        q = struct.unpack_from("<4f", d, p + 16)
        transforms.append((t, _quat_matrix(*q)))
        p += 32
    nbv, = struct.unpack_from("<I", d, p); p += 4
    big, p = _vec4s(d, p, nbv)
    nbt, = struct.unpack_from("<I", d, p); p += 4
    verts, tris = list(big), []
    for _ in range(nbt):
        a, b, c = struct.unpack_from("<3H", d, p); p += 12
        tris.append((a, b, c))
    nch, = struct.unpack_from("<I", d, p); p += 4
    for _ in range(nch):
        ct = struct.unpack_from("<3f", d, p); p += 16
        p += 4                                                      # material index
        _ref, ti = struct.unpack_from("<HH", d, p); p += 4
        nv, = struct.unpack_from("<I", d, p); p += 4
        q = struct.unpack_from(f"<{nv}H", d, p); p += 2 * nv
        ni, = struct.unpack_from("<I", d, p); p += 4
        idx = struct.unpack_from(f"<{ni}H", d, p); p += 2 * ni
        ns, = struct.unpack_from("<I", d, p); p += 4
        strips = struct.unpack_from(f"<{ns}H", d, p); p += 2 * ns
        nw, = struct.unpack_from("<I", d, p); p += 4 + 2 * nw
        t, m = transforms[ti] if ti < len(transforms) else ((0.0, 0.0, 0.0), IDENT)
        base = len(verts)
        for k in range(nv // 3):            # NifSkope drawCMS / tes4skyrim cms.py: translations, then the rotation
            v = (ct[0] + t[0] + q[3 * k] * CMS_STEP, ct[1] + t[1] + q[3 * k + 1] * CMS_STEP,
                 ct[2] + t[2] + q[3 * k + 2] * CMS_STEP)
            verts.append(_apply(m, (0.0, 0.0, 0.0), v))
        o = 0
        for ln in strips:
            s = idx[o:o + ln]
            for k in range(ln - 2):
                a, b, c = s[k], s[k + 1], s[k + 2]
                if a != b and b != c and a != c:
                    tris.append((base + a, base + b, base + c) if k % 2 == 0 else (base + a, base + c, base + b))
            o += ln
        for k in range(o, ni - 2, 3):
            tris.append((base + idx[k], base + idx[k + 1], base + idx[k + 2]))
    return verts, tris


def _packed_data(d: bytes):
    nt, = struct.unpack_from("<I", d, 0)
    tris = [struct.unpack_from("<3H", d, 4 + 8 * k) for k in range(nt)]
    p = 4 + 8 * nt
    nv, = struct.unpack_from("<I", d, p); p += 4
    compressed = d[p]; p += 1
    if compressed:
        verts = [tuple(struct.unpack_from("<3e", d, p + 6 * k)) for k in range(nv)]
    else:
        verts = [struct.unpack_from("<3f", d, p + 12 * k) for k in range(nv)]
    return verts, [tuple(t) for t in tris]


def _shape(n, i, depth=0):
    """(vertices in havok units, triangles, [unsupported type names]) of one havok shape block."""
    if not (0 <= i < len(n.blocks)) or depth > 32:
        return [], [], ["missing shape"]
    t, d = n.type_of(i), n.blocks[i]
    if t == "bhkMoppBvTreeShape":
        return _shape(n, struct.unpack_from("<i", d, 0)[0], depth + 1)
    if t in ("bhkCompressedMeshShape", "bhkPackedNiTriStripsShape"):
        data, = struct.unpack_from("<i", d, 52)
        if not (0 <= data < len(n.blocks)):
            return [], [], [f"{t} without data"]
        dt = n.type_of(data)
        if dt == "bhkCompressedMeshShapeData":
            v, f = _cms_data(n.blocks[data])
        elif dt == "hkPackedNiTriStripsData":
            v, f = _packed_data(n.blocks[data])
        else:
            return [], [], [f"{t} data {dt}"]
        return v, f, []
    if t == "bhkBoxShape":
        h = struct.unpack_from("<3f", d, 16)
        return (*_box((-h[0], -h[1], -h[2]), h), [])
    if t == "bhkSphereShape":
        r, = struct.unpack_from("<f", d, 4)
        return (*_box((-r, -r, -r), (r, r, r)), [])
    if t == "bhkCapsuleShape":
        r, = struct.unpack_from("<f", d, 4)
        a = struct.unpack_from("<3f", d, 16)
        b = struct.unpack_from("<3f", d, 32)
        pts = [(c[0] + dx, c[1] + dy, c[2] + dz) for c in (a, b) for dx in (-r, r) for dy in (-r, r) for dz in (-r, r)]
        return (*_hull(pts), [])
    if t == "bhkConvexVerticesShape":
        nv, = struct.unpack_from("<I", d, 32)
        pts, _ = _vec4s(d, 36, nv)
        return (*_hull(pts), [])
    if t in ("bhkListShape", "bhkConvexListShape"):
        k, = struct.unpack_from("<I", d, 0)
        verts, tris, bad = [], [], []
        for c in struct.unpack_from(f"<{k}i", d, 4):
            v, f, b = _shape(n, c, depth + 1)
            tris += [(a + len(verts), b_ + len(verts), c_ + len(verts)) for a, b_, c_ in f]
            verts += v
            bad += b
        return verts, tris, bad
    if t in ("bhkTransformShape", "bhkConvexTransformShape"):
        child, = struct.unpack_from("<i", d, 0)
        m = struct.unpack_from("<16f", d, 20)                 # hkTransform: three rotation columns, translation
        rot = (m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10])
        tr = (m[12], m[13], m[14])
        if abs(m[3]) + abs(m[7]) + abs(m[11]) > 1e-4 and abs(m[12]) + abs(m[13]) + abs(m[14]) < 1e-6:
            rot = (m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10])   # stored row-major instead
            tr = (m[3], m[7], m[11])
        v, f, b = _shape(n, child, depth + 1)
        return [_apply(rot, tr, x) for x in v], f, b
    return [], [], [t]


BODY_TRANSFORM_MODES = ("all", "t_only", "none", "body_only")
BODY_TRANSFORM_DEFAULT = "t_only"


def collision_triangles(n: nifmod.NifFile, report: Optional[dict] = None,
                        body_transform: str = BODY_TRANSFORM_DEFAULT):
    """(points, triangles) of every rigid body's collision in the NIF's root frame, in GAME units; empty when the
    model has no collision. Unsupported shape types go to report['unsupported'] (the model then keeps what decoded).

    body_transform: how a body's own stored translation / rotation (bytes 52 / 68) combines with its node's world
    transform. "t_only" (default, VERIFIED on the owner's Skyrim SE 2026-10-15): applied on bhkRigidBodyT only, then
    the node. "all" (tes4skyrim's reading, plain bodies too) put 285 of 2,473 surveyed vanilla models' collision off
    the visible mesh; "t_only" fixes 284 (the last is a collision-only wall piece). "all", "none" and "body_only"
    stay for the first-run survey, which re-measures this on every run."""
    world = nifmod.world_transforms(n)
    points, tris, bad, bodies = [], [], [], 0
    for i in range(len(n.blocks)):
        if n.type_of(i) not in ("bhkCollisionObject", "bhkSPCollisionObject", "bhkBlendCollisionObject"):
            continue
        target, _flags, body = struct.unpack_from("<iHi", n.blocks[i], 0)
        if not (0 <= body < len(n.blocks)) or not n.type_of(body).startswith("bhkRigidBody"):
            bad.append(f"collision object body {n.type_of(body) if 0 <= body < len(n.blocks) else 'missing'}")
            continue
        blk = n.blocks[body]
        shape, = struct.unpack_from("<i", blk, 0)
        v, f, b = _shape(n, shape)
        bad += b
        t, m, unit = _rigid_body_transform(blk)            # used on bhkRigidBodyT only by default (see docstring)
        if not unit:
            bad.append(f"{n.type_of(body)} rotation is not a unit quaternion (identity used)")
        is_t = n.type_of(body) == "bhkRigidBodyT"
        if body_transform in ("all", "body_only") or (body_transform == "t_only" and is_t):
            v = [_apply(m, t, x) for x in v]
        tr, rot, scale = world(target) if 0 <= target < len(n.blocks) else ((0.0, 0.0, 0.0), IDENT, 1.0)
        if body_transform == "body_only":
            tr, rot, scale = (0.0, 0.0, 0.0), IDENT, 1.0
        if report is not None:
            report.setdefault("body_list", []).append({
                "class": n.type_of(body), "layer": blk[4] if len(blk) > 4 else None,
                "translation": [round(c * HAVOK_SCALE, 1) for c in t], "rotated": m != IDENT,
                "node_translation": [round(c, 1) for c in tr]})
        base = len(points)
        for x in v:
            g = tuple(c * HAVOK_SCALE for c in x)
            points.append(_apply(tuple(scale * r for r in rot), tr, g))
        tris += [(a + base, b_ + base, c + base) for a, b_, c in f]
        bodies += 1
    if report is not None:
        report["skyrim_bodies"] = bodies
        report["skyrim_collision_triangles"] = len(tris)
        if bad:
            report["unsupported"] = sorted(set(bad))
    return points, tris
