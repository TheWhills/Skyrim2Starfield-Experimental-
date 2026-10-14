"""Transplant Fallout 4 mesh collision into a Starfield collision blob.

FO4 (Havok 2014 packfile) and Starfield (Havok 2019 tagfile) store hknpCompressedMeshShape data with the same
hkcdStaticMeshTree layout: a compressed AABB tree over sections, each section with its own small tree, quantised packed
vertices, shared vertices, primitives (triangle / quad vertex indices) and primitive data runs. So FO4's finished
collision mesh (authored for gameplay: stairs are ramps, walls are simplified) can be copied across; only the
container format and a few section fields differ:

    FO4 section  @76 (firstShared << 8 | numPacked)  @80 (firstPrimitive << 8 | count)  @84 (firstRun << 8 | count)
                 @88 numPacked  @89 numSharedIndices  @90 leafIndex u16  @92 page  @93 flags  @94 layerData
    SF section   @76 firstSharedVertexIndex  @80 firstPrimitiveIndex  @84 firstDataRunIndex  @88 numPackedVertices
                 @89 numPrimitives  @90 numDataRuns  @91 page  @92 leafIndex u16  @94 layerData  @95 flags

The Starfield side is rebuilt around a template tagfile taken from a vanilla Starfield static (read from the user's
install at conversion time, never shipped): its TYPE section, physics system, material and body are reused; the shape's
data arrays, sections and trees come from FO4. Starfield's SIMD tree (a 4-wide AABB tree over triangle shape keys, present in every vanilla mesh) is generated.
"""
import math
import os
import struct
from typing import Dict, List, Optional, Tuple

from . import hkpackfile, hktagfile

TEMPLATE_NIF = "meshes/architecture/city/akila/interiorkit/ak_int_wallmid03.nif"   # vanilla static with a mesh body

# FO4 hknpCompressedMeshShapeData (object-relative): mesh tree at +16
FO4_TREE = 16
FO4_ARRAYS = {"nodes": 16, "sections": 80, "primitives": 96, "sharedVerticesIndex": 112, "packedVertices": 128,
              "sharedVertices": 144, "primitiveDataRuns": 160}
ELEM_SIZE = {"nodes": 5, "sections": 96, "primitives": 4, "sharedVerticesIndex": 2, "packedVertices": 4,
             "sharedVertices": 8, "primitiveDataRuns": 4}
FO4_SECTION_NODES = 4                                 # per-section tree: Aabb4BytesCodec


class _Writer:
    """Items (objects / arrays) laid out into a tagfile DATA section; pointers are item numbers patched via PTCH."""

    def __init__(self):
        self.items: List[Tuple[int, int, bytearray, int]] = []     # (type, flags, payload, count)
        self.ptrs: List[Tuple[int, int, int, int]] = []           # (pointer type, item, offset in item, target item)

    def add(self, type_idx: int, flags: int, payload: bytes, count: int) -> int:
        self.items.append((type_idx, flags, bytearray(payload), count))
        return len(self.items)                                     # item numbers start at 1 (0 = null)

    def ptr(self, ptr_type: int, item: int, offset: int, target: Optional[int]):
        if target:
            self.ptrs.append((ptr_type, item, offset, target))

    def build(self, sdk: bytes, type_section: bytes) -> bytes:
        data, offsets = bytearray(), []
        for _, _, payload, _ in self.items:
            data += b"\0" * (-len(data) % 16)
            offsets.append(len(data))
            data += payload
        data += b"\0" * (-len(data) % 16)
        patches: Dict[int, List[int]] = {}
        for ptype, item, off, target in self.ptrs:
            at = offsets[item - 1] + off
            struct.pack_into("<Q", data, at, target)
            patches.setdefault(ptype, []).append(at)
        item_tab = bytearray(12)                                   # item 0: null
        for (ti, fl, _, cnt), off in zip(self.items, offsets):
            item_tab += struct.pack("<III", (fl << 24) | ti, off, cnt)
        ptch = bytearray()
        for ptype, offs in patches.items():
            ptch += struct.pack("<II", ptype, len(offs)) + struct.pack(f"<{len(offs)}I", *sorted(offs))

        def sec(tag, payload, leaf=True):
            return struct.pack(">I", ((1 if leaf else 0) << 30) | (len(payload) + 8)) + tag + payload
        indx = sec(b"ITEM", bytes(item_tab)) + sec(b"PTCH", bytes(ptch))
        body = sec(b"SDKV", sdk) + sec(b"DATA", bytes(data)) + type_section + sec(b"INDX", indx, leaf=False)
        return sec(b"TAG0", body, leaf=False)


def _type(tf: hktagfile.Tagfile, name: str) -> int:
    for t in tf.types:
        if tf.type_name(t.index) == name:
            return t.index
    raise hktagfile.TagfileError(f"template has no type {name}")


def _field(tf: hktagfile.Tagfile, type_idx: int, name: str) -> hktagfile.Field:
    return next(f for f in tf.all_fields(type_idx) if f.name == name)


def _fo4_mesh_body(p: hkpackfile.Packfile):
    """Locate the single supported body; never discard additional bodies.

    Unsupported source systems raise so the converter records its fallback.
    Convex-only single-body systems return None for the separate convex path.
    """
    from . import fo4collision as fc
    classes = dict(p.objects())
    systems = [o for o, c in classes.items() if c == "hknpPhysicsSystemData"]
    if len(systems) != 1:
        raise hkpackfile.PackfileError("mesh transplant requires one source physics system")
    at, n = p.array(systems[0] + fc.SYS_BODIES)
    if n > 1:
        raise hkpackfile.PackfileError(f"mesh transplant cannot preserve all {n} source collision bodies")
    if n < 0 or (n and at is None):
        raise hkpackfile.PackfileError("invalid source collision body array")
    if n == 0:
        return None
    shape = p.pointer(at)
    if classes.get(shape) != "hknpCompressedMeshShape":
        return None
    rotation = p.unpack("<4f", at + fc.BODY_ROT)
    if (not all(math.isfinite(x) for x in rotation) or
            any(abs(x) > 1e-4 for x in rotation[:3]) or abs(abs(rotation[3]) - 1) > 1e-4):
        raise hkpackfile.PackfileError("mesh transplant cannot preserve source body rotation")
    pos = p.unpack("<3f", at + fc.BODY_POS)
    if not all(math.isfinite(x) for x in pos) or any(abs(x) > 1e-5 for x in pos):
        raise hkpackfile.PackfileError("mesh transplant cannot preserve source body translation")
    data = p.pointer(shape + fc.CMS_DATA)
    if data is None:
        raise hkpackfile.PackfileError("compressed mesh body has no data")
    return data, pos


def _convert_section(fo4: bytes) -> bytearray:
    s = bytearray(96)
    s[16:72] = fo4[16:72]                                          # domain + codec parameters
    first_packed, shared_d, prim_d, run_d = struct.unpack_from("<4I", fo4, 72)
    struct.pack_into("<4I", s, 72, first_packed, shared_d >> 8, prim_d >> 8, run_d >> 8)
    s[88] = fo4[88]                                                # numPackedVertices
    s[89] = prim_d & 0xFF                                          # numPrimitives
    s[90] = run_d & 0xFF                                           # numDataRuns
    s[91] = fo4[92]                                                # page
    s[92:94] = fo4[90:92]                                          # leafIndex
    s[94] = fo4[94]                                                # layerData
    s[95] = fo4[93]                                                # flags
    return s


def transplant(fo4_blob: bytes, sf_template_blob: bytes) -> Optional[bytes]:
    """Starfield bhkPhysicsSystem blob holding FO4's compressed mesh collision, or None if the FO4 blob has no unrotated
    mesh body (convex-only collision is handled elsewhere). Unsupported multi-body systems or body transforms raise
    PackfileError so the caller records an explicit fallback; no source bodies are silently omitted."""
    p = hkpackfile.Packfile(fo4_blob)
    found = _fo4_mesh_body(p)
    if found is None:
        return None
    d, pos = found
    if any(abs(x) > 1e-5 for x in pos):
        return None
    tf = hktagfile.Tagfile(sf_template_blob)
    blob = tf.blob
    tmpl = {tf.type_name(it.type): it for it in tf.items[1:]}

    def tmpl_bytes(name):
        it = tmpl[name]
        return blob[tf.data_start + it.offset:tf.data_start + it.offset + tf.size_of(it.type) * it.count]

    T_PSD, T_BODY = _type(tf, "hknpPhysicsSystemData"), _type(tf, "hknpPhysicsSystemData::bodyCinfoWithAttachment")
    T_MAT, T_CMS = _type(tf, "hknpMaterial"), _type(tf, "hknpCompressedMeshShape")
    T_DATA = _type(tf, "hknpCompressedMeshShapeData")
    T_TREE = _type(tf, "hknpCompressedMeshShapeTree")
    T_SEC = _type(tf, "hkcdStaticMeshTree::Section")
    tree_off = _field(tf, T_DATA, "meshTree").offset

    def arr_types(owner, field):
        ft = _field(tf, owner, field).type                         # hkArray<E, ...>
        return ft, dict(tf.types[ft].params)["tT"]

    w = _Writer()
    i_psd = w.add(T_PSD, 0x10, tmpl_bytes("hknpPhysicsSystemData"), 1)
    i_mat = w.add(T_MAT, 0x20, tmpl_bytes("hknpMaterial"), tmpl["hknpMaterial"].count)
    i_body = w.add(T_BODY, 0x20, tmpl_bytes("hknpPhysicsSystemData::bodyCinfoWithAttachment"), 1)
    w.ptr(_field(tf, T_PSD, "materials").type, i_psd, _field(tf, T_PSD, "materials").offset, i_mat)
    w.ptr(_field(tf, T_PSD, "bodyCinfos").type, i_psd, _field(tf, T_PSD, "bodyCinfos").offset, i_body)

    # FO4 arrays
    fo4 = {}
    for name, off in FO4_ARRAYS.items():
        at, n = p.array(d + off)
        fo4[name] = (p.raw(at, ELEM_SIZE[name] * n) if n else b"", n)
    n_tris = sum(1 if q[2] == q[3] else 2 for q in struct.iter_unpack("<4B", fo4["primitives"][0]))

    cms = bytearray(tmpl_bytes("hknpCompressedMeshShape"))
    i_cms = w.add(T_CMS, 0x10, cms, 1)
    w.ptr(_field(tf, T_BODY, "shape").type, i_body, _field(tf, T_BODY, "shape").offset, i_cms)
    # vanilla: numTriangles 0, numShapeKeyBits = tree bitsPerKey, interior bit field sized maxKeyValue + 1
    n_prim_keys, bits_per_key, max_key = struct.unpack_from("<iiI", p.raw(d + FO4_TREE + 48, 12))
    struct.pack_into("<ii", w.items[i_cms - 1][2], _field(tf, T_CMS, "numTriangles").offset, 0, 0)
    w.items[i_cms - 1][2][_field(tf, T_CMS, "numShapeKeyBits").offset] = bits_per_key
    n_bits = max_key + 1
    bits = _field(tf, T_CMS, "triangleIsInterior")
    nwords = (n_bits + 31) // 32
    words_ptr_type = _field(tf, bits.type, "storage").type
    words_arr_type = _field(tf, words_ptr_type, "words").type
    i_words = w.add(dict(tf.types[words_arr_type].params)["tT"], 0x20, bytes(4 * nwords), nwords)
    w.ptr(words_arr_type, i_cms, bits.offset + _field(tf, words_ptr_type, "words").offset, i_words)
    struct.pack_into("<i", w.items[i_cms - 1][2], bits.offset + _field(tf, words_ptr_type, "numBits").offset, n_bits)

    data = bytearray(tmpl_bytes("hknpCompressedMeshShapeData"))
    for f in ("nodes", "sections", "primitives", "sharedVerticesIndex", "packedVertices", "sharedVertices",
              "primitiveDataRuns"):
        struct.pack_into("<16x", data, tree_off + _field(tf, T_TREE, f).offset)       # cleared; set by patches
    data[tree_off + 16:tree_off + 48] = p.raw(d + FO4_TREE + 16, 32)                   # domain
    data[tree_off + 48:tree_off + 64] = p.raw(d + FO4_TREE + 48, 16)                   # keys, bits, max key, flat
    simd = _field(tf, T_DATA, "simdTree")
    data[simd.offset:simd.offset + tf.size_of(simd.type)] = bytes(tf.size_of(simd.type))
    conn = _field(tf, T_DATA, "connectivity")
    data[conn.offset:conn.offset + tf.size_of(conn.type)] = bytes(tf.size_of(conn.type))
    data[_field(tf, T_DATA, "hasSimdTree").offset] = 1            # every vanilla mesh has one; built over FO4 triangles
    data[simd.offset + _field(tf, simd.type, "isCompact").offset] = 1
    i_data = w.add(T_DATA, 0x10, data, 1)
    from . import fo4collision
    simd_raw = build_simd_tree(fo4collision.compressed_mesh_keys(p, d))
    simd_arr_t, simd_elem_t = arr_types(simd.type, "nodes")
    i_simd = w.add(simd_elem_t, 0x20, simd_raw, len(simd_raw) // 128)
    w.ptr(simd_arr_t, i_data, simd.offset + _field(tf, simd.type, "nodes").offset, i_simd)
    w.ptr(_field(tf, T_CMS, "data").type, i_cms, _field(tf, T_CMS, "data").offset, i_data)

    for name in ("nodes", "primitives", "sharedVerticesIndex", "packedVertices", "sharedVertices",
                 "primitiveDataRuns"):
        raw, n = fo4[name]
        if not n:
            continue
        arr_t, elem_t = arr_types(T_TREE, name)
        i = w.add(elem_t, 0x20, raw, n)
        w.ptr(arr_t, i_data, tree_off + _field(tf, T_TREE, name).offset, i)

    sec_raw, nsec = fo4["sections"]
    sec_arr_t, sec_elem_t = arr_types(T_TREE, "sections")
    sections = bytearray()
    for k in range(nsec):
        sections += _convert_section(sec_raw[96 * k:96 * k + 96])
    i_secs = w.add(sec_elem_t, 0x20, sections, nsec)
    w.ptr(sec_arr_t, i_data, tree_off + _field(tf, T_TREE, "sections").offset, i_secs)
    sec_at, _ = p.array(d + FO4_ARRAYS["sections"])
    node_arr_t, node_elem_t = arr_types(T_SEC, "nodes")
    for k in range(nsec):
        at, n = p.array(sec_at + 96 * k)
        if n:
            i = w.add(node_elem_t, 0x20, p.raw(at, FO4_SECTION_NODES * n), n)
            w.ptr(node_arr_t, i_secs, 96 * k + _field(tf, T_SEC, "nodes").offset, i)

    type_sec = next((blob[s - 8:e] for tag, s, e in hktagfile.sections(blob, 8, len(blob)) if tag == "TYPE"))
    sdk = next((blob[s:e] for tag, s, e in hktagfile.sections(blob, 8, len(blob)) if tag == "SDKV"))
    return w.build(sdk, type_sec)


def template_from_nif(sf_nif: bytes) -> bytes:
    """The first bhkPhysicsSystem blob of a vanilla Starfield NIF (use TEMPLATE_NIF: a static with a mesh body)."""
    from . import nif as nifmod
    f = nifmod.parse(sf_nif)
    for i in range(len(f.blocks)):
        if f.type_of(i) == "bhkPhysicsSystem":
            n, = struct.unpack_from("<I", f.blocks[i], 0)
            return f.blocks[i][4:4 + n]
    raise ValueError("template NIF has no bhkPhysicsSystem")


FLT_MAX = 3.40282e38


def build_simd_tree(leaves) -> bytes:
    """hkcdSimdTree nodes (128 bytes each: lx hx ly hy lz hz as 4-lane float vectors, data u32[4], isLeaf, isActive) over
    [(key, (lo, hi))]: node 0 is an empty sentinel, node 1 the root; inner lanes hold child node indices and child boxes,
    leaf lanes hold triangle shape keys (unused lanes: empty box, data 0xffffffff in leaves / 0 in inner nodes)."""
    nodes = [None]                                     # index 0: sentinel

    def bounds(items):
        lo = tuple(min(it[1][0][a] for it in items) for a in range(3))
        hi = tuple(max(it[1][1][a] for it in items) for a in range(3))
        return lo, hi

    def emit(index, lanes, leaf):
        lx, hx, ly, hy, lz, hz, data = [], [], [], [], [], [], []
        for i in range(4):
            if i < len(lanes):
                (lo, hi), d = lanes[i]
                lx.append(lo[0]); hx.append(hi[0]); ly.append(lo[1]); hy.append(hi[1]); lz.append(lo[2]); hz.append(hi[2])
                data.append(d)
            else:
                lx.append(FLT_MAX); hx.append(-FLT_MAX); ly.append(FLT_MAX); hy.append(-FLT_MAX)
                lz.append(FLT_MAX); hz.append(-FLT_MAX)
                data.append(0xFFFFFFFF if leaf else 0)
        nodes[index] = (struct.pack("<24f", *lx, *hx, *ly, *hy, *lz, *hz) + struct.pack("<4I", *data)
                        + bytes([1 if leaf else 0, 0]) + bytes(14))

    def build(index, items):
        if len(items) <= 4:
            emit(index, [(it[1], it[0]) for it in items], True)
            return
        lo, hi = bounds(items)
        axis = max(range(3), key=lambda a: hi[a] - lo[a])
        items = sorted(items, key=lambda it: it[1][0][axis] + it[1][1][axis])
        n = len(items)
        groups = [g for g in (items[i * n // 4:(i + 1) * n // 4] for i in range(4)) if g]
        first = len(nodes)
        nodes.extend([None] * len(groups))             # children get consecutive indices, then recurse (as vanilla)
        emit(index, [(bounds(g), first + i) for i, g in enumerate(groups)], False)
        for i, g in enumerate(groups):
            build(first + i, g)

    nodes.append(None)
    build(1, list(leaves))
    sentinel = (struct.pack("<24f", *([FLT_MAX] * 4 + [-FLT_MAX] * 4) * 3) + bytes(16) + bytes(16))
    nodes[0] = sentinel
    return b"".join(nodes)


def decode_sf_mesh(sf_blob: bytes):
    """Triangles of the first hknpCompressedMeshShapeData in a Starfield tagfile, decoded with Starfield's section fields
    (used to verify transplants round-trip; also handy for vanilla collision)."""
    tf = hktagfile.Tagfile(sf_blob)
    b, D = tf.blob, tf.data_start
    T_DATA = _type(tf, "hknpCompressedMeshShapeData")
    data_item = next(it for it in tf.items[1:] if it.type == T_DATA)
    T_TREE = _type(tf, "hknpCompressedMeshShapeTree")
    tree = D + data_item.offset + _field(tf, T_DATA, "meshTree").offset
    by_off = {D + it.offset: it for it in tf.items[1:]}
    ptr_items = {}
    for _, offs in tf.patches:
        for o in offs:
            ptr_items[D + o] = tf.items[struct.unpack_from("<Q", b, D + o)[0]]

    def arr(name):
        it = ptr_items.get(tree + _field(tf, T_TREE, name).offset)
        return (D + it.offset, it.count) if it else (0, 0)
    dmin = struct.unpack_from("<3f", b, tree + 16)
    dmax = struct.unpack_from("<3f", b, tree + 32)
    sec_at, nsec = arr("sections")
    prim_at, _ = arr("primitives")
    sidx_at, _ = arr("sharedVerticesIndex")
    pack_at, _ = arr("packedVertices")
    shar_at, nshared = arr("sharedVertices")
    shared = []
    for k in range(nshared):
        v, = struct.unpack_from("<Q", b, shar_at + 8 * k)
        q = (v & 0x1FFFFF, (v >> 21) & 0x1FFFFF, v >> 42)
        bits = (0x1FFFFF, 0x1FFFFF, 0x3FFFFF)
        shared.append(tuple(dmin[a] + q[a] * (dmax[a] - dmin[a]) / bits[a] for a in range(3)))
    tris = []
    for s in range(nsec):
        so = sec_at + 96 * s
        off, scale = struct.unpack_from("<3f", b, so + 48), struct.unpack_from("<3f", b, so + 60)
        first_packed, first_shared, first_prim, _ = struct.unpack_from("<4I", b, so + 72)
        npacked, nprim = b[so + 88], b[so + 89]

        def vert(i):
            if i < npacked:
                v, = struct.unpack_from("<I", b, pack_at + 4 * (first_packed + i))
                q = (v & 0x7FF, (v >> 11) & 0x7FF, v >> 22)
                return tuple(off[a] + q[a] * scale[a] for a in range(3))
            j, = struct.unpack_from("<H", b, sidx_at + 2 * (first_shared + i - npacked))
            return shared[j]
        for k in range(nprim):
            i0, i1, i2, i3 = b[prim_at + 4 * (first_prim + k):prim_at + 4 * (first_prim + k) + 4]
            tris.append((vert(i0), vert(i1), vert(i2)))
            if i2 != i3:
                tris.append((vert(i0), vert(i2), vert(i3)))
    return tris


# ---- every body, native shapes -----------------------------------------------------------------------------------
# Template: Bethesda's own collision test file, whose single physics system holds sphere, capsule, box, convex, cylinder,
# compressed-mesh and compound bodies, so its TYPE section covers every shape we emit (read from the user's install).
UNIVERSAL_TEMPLATE_NIF = "meshes/test/fbx_export/test_fbx_collision_same_node01.nif"


class _Tmpl:
    def __init__(self, blob: bytes):
        self.tf = hktagfile.Tagfile(blob)
        self.blob = blob

    def item_bytes(self, name: str, k: int = 0, count: Optional[int] = None) -> bytes:
        its = [it for it in self.tf.items[1:] if self.tf.type_name(it.type) == name]
        it = its[k]
        n = self.tf.size_of(it.type) * (it.count if count is None else count)
        return self.blob[self.tf.data_start + it.offset:self.tf.data_start + it.offset + n]

    def type(self, name: str) -> int:
        return _type(self.tf, name)

    def field(self, type_idx: int, name: str) -> hktagfile.Field:
        return _field(self.tf, type_idx, name)

    def arr_types(self, owner: int, name: str):
        ft = self.field(owner, name).type
        return ft, dict(self.tf.types[ft].params)["tT"]


def _hull_links(faces: List[List[int]], nverts: int):
    """faceLinks (per face edge: the face / edge running the opposite way) and vertexEdges (per vertex: the last edge
    leaving it), as in vanilla Starfield hulls. Raises if the hull is not closed."""
    where = {}
    for f, idx in enumerate(faces):
        for e in range(len(idx)):
            where[(idx[e], idx[(e + 1) % len(idx)])] = (f, e)
    links = []
    for f, idx in enumerate(faces):
        for e in range(len(idx)):
            opp = where.get((idx[(e + 1) % len(idx)], idx[e]))
            if opp is None:
                raise hkpackfile.PackfileError("convex hull is not closed (missing opposite edge)")
            links.append(opp)
    vedges = [None] * nverts
    for f, idx in enumerate(faces):
        for e, v in enumerate(idx):
            vedges[v] = (f, e)
    if any(v is None for v in vedges):
        raise hkpackfile.PackfileError("convex hull has unused vertices")
    return links, vedges


def _quat_matrix(q):
    x, y, z, w = q
    return (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
            2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
            2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y))


def convex_hull_triangles(verts, grid=1e-4):
    """Incremental 3D convex hull: triangles wound counter-clockwise seen from outside, always closed. Used when the
    polygon rebuild (convex_hull_faces) cannot close, e.g. a lampshade of 60 nearly coplanar points where tolerance-merged
    polygons overlap. Runs on points snapped to a 0.1 mm integer grid with exact integer orientation tests: float
    tolerances on near-coplanar points gave inconsistent hulls (165 faces for 58 points). Returns indices into `verts`
    (the first of any points that snap together)."""
    first, idx, q = {}, [], []
    for i, v in enumerate(verts):
        k = tuple(int(round(c / grid)) for c in v)
        if k not in first:
            first[k] = len(q)
            idx.append(i)
            q.append(k)
    n = len(q)
    sub = lambda a, b: (a[0] - b[0], a[1] - b[1], a[2] - b[2])
    cross = lambda a, b: (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    dot = lambda a, b: a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    if n < 4:
        raise hkpackfile.PackfileError("degenerate hull (fewer than 4 distinct points)")
    i0 = 0
    i1 = max(range(n), key=lambda i: dot(sub(q[i], q[i0]), sub(q[i], q[i0])))
    d01 = sub(q[i1], q[i0])
    i2 = max(range(n), key=lambda i: dot(c := cross(d01, sub(q[i], q[i0])), c))
    nrm = cross(d01, sub(q[i2], q[i0]))
    i3 = max(range(n), key=lambda i: abs(dot(nrm, sub(q[i], q[i0]))))
    side = dot(nrm, sub(q[i3], q[i0]))
    if side == 0:
        raise hkpackfile.PackfileError("degenerate (flat) hull")
    if side > 0:                                         # make (i0, i1, i2) face away from i3
        i1, i2 = i2, i1
    faces = [(i0, i1, i2), (i0, i3, i1), (i1, i3, i2), (i2, i3, i0)]
    above = lambda f, p: dot(cross(sub(q[f[1]], q[f[0]]), sub(q[f[2]], q[f[0]])), sub(p, q[f[0]])) > 0
    for k in range(n):
        if k in (i0, i1, i2, i3):
            continue
        visible = [f for f in faces if above(f, q[k])]
        if not visible:
            continue
        edges = set()
        for f in visible:
            edges.update(((f[0], f[1]), (f[1], f[2]), (f[2], f[0])))
        horizon = [e for e in edges if (e[1], e[0]) not in edges]
        vis = set(visible)
        faces = [f for f in faces if f not in vis] + [(a, b, k) for a, b in horizon]
    return [[idx[x] for x in f] for f in faces]

def thicken_if_flat(verts, half=0.005, eps=1e-4):
    """A planar point set (FO4 has a few flat "hulls", e.g. SubLight02Hanging's plate) has no closed hull: return it as
    two copies offset +-half metres along its normal (a 1 cm slab). Non-planar sets are returned unchanged."""
    import math
    n = None
    for i in range(1, len(verts)):
        for j in range(i + 1, len(verts)):
            u = [verts[i][k] - verts[0][k] for k in range(3)]
            v = [verts[j][k] - verts[0][k] for k in range(3)]
            c = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            ln = math.sqrt(sum(x * x for x in c))
            if ln > 1e-9:
                n = tuple(x / ln for x in c)
                break
        if n:
            break
    if n is None or any(abs(sum(n[k] * (p[k] - verts[0][k]) for k in range(3))) > eps for p in verts):
        return verts
    return ([tuple(p[k] + half * n[k] for k in range(3)) for p in verts] +
            [tuple(p[k] - half * n[k] for k in range(3)) for p in verts])


def convex_hull_faces(verts, eps=1e-4):
    """Faces of the convex hull of a small point set, each a polygon wound counter-clockwise seen from outside (as vanilla
    Starfield hulls). Brute force over vertex triples (FO4 hulls have few vertices); coplanar points form one face."""
    import math
    n = len(verts)
    sub = lambda a, b: (a[0] - b[0], a[1] - b[1], a[2] - b[2])
    cross = lambda a, b: (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    dot = lambda a, b: a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    faces, seen = [], []
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                nrm = cross(sub(verts[j], verts[i]), sub(verts[k], verts[i]))
                ln = math.sqrt(dot(nrm, nrm))
                if ln < 1e-9:
                    continue
                nrm = tuple(x / ln for x in nrm)
                d = dot(nrm, verts[i])
                side = [dot(nrm, v) - d for v in verts]
                if all(s <= eps for s in side):
                    pass
                elif all(s >= -eps for s in side):
                    nrm, d = tuple(-x for x in nrm), -d
                else:
                    continue
                if any(abs(dot(nrm, m) - 1) < 1e-6 and abs(d - dd) < eps for m, dd in seen):
                    continue
                seen.append((nrm, d))
                on = [q for q in range(n) if abs(dot(nrm, verts[q]) - d) <= eps]
                c = tuple(sum(verts[q][a] for q in on) / len(on) for a in range(3))
                u = sub(verts[on[0]], c)
                ul = math.sqrt(dot(u, u)) or 1.0
                u = tuple(x / ul for x in u)
                v = cross(nrm, u)
                on.sort(key=lambda q: math.atan2(dot(sub(verts[q], c), v), dot(sub(verts[q], c), u)))
                faces.append(on)                         # angle increasing around +normal = counter-clockwise outside
    return faces


def _faces_raw(faces, fo4_raw: bytes) -> bytes:
    """Face records (first index u16, count u8, minHalfAngle u8) for the rebuilt, contiguous index list."""
    out, first = b"", 0
    for k, f in enumerate(faces):
        out += struct.pack("<HBB", first, len(f), fo4_raw[4 * k + 3])
        first += len(f)
    return out


def _emit_sphere(w: "_Writer", t: _Tmpl, p: hkpackfile.Packfile, shape: int, R, tr) -> int:
    """FO4 hknpSphereShape (radius @20, centre as the first hull vertex) -> Starfield hknpSphereShape (hull with one
    float3 vertex, radius in convexRadius), centre moved by the instance transform."""
    from . import fo4collision as fc
    va, nv = fc._rel(p, shape + fc.CVX_VERTS)
    if nv < 1:
        raise hkpackfile.PackfileError("sphere without a centre vertex")
    c = p.unpack("<3f", va)
    centre = tuple(tr[i] + sum(R[3 * i + k] * c[k] for k in range(3)) for i in range(3))
    radius, = p.unpack("<f", shape + 20)
    T_SPH = t.type("hknpSphereShape")
    body = bytearray(t.item_bytes("hknpSphereShape"))
    struct.pack_into("<f", body, t.field(T_SPH, "convexRadius").offset, radius)
    struct.pack_into("<Q", body, t.field(T_SPH, "properties").offset, 0)
    hull = t.field(T_SPH, "hull")
    for fname in ("vertices", "planes", "faces", "indices", "faceLinks", "vertexEdges"):
        struct.pack_into("<Q", body, hull.offset + t.field(hull.type, fname).offset, 0)
    i_shape = w.add(T_SPH, 0x10, body, 1)
    rel_t = t.field(hull.type, "vertices").type
    i_v = w.add(dict(t.tf.types[rel_t].params)["tT"], 0x20, struct.pack("<3f", *centre), 1)
    w.ptr(rel_t, i_shape, hull.offset + t.field(hull.type, "vertices").offset, i_v)
    return i_shape


STAIR_HELPER_MAX_SLOPE = 40.0      # degrees; FO4 helpers up to ~46 degrees stop Starfield's character controller


def _flatten_helper(verts, faces, node_rot, max_slope=STAIR_HELPER_MAX_SLOPE):
    """Stretch a stair-helper wedge so its slope (measured in the collision node's orientation) is at most max_slope:
    the low front vertices move horizontally away from the top edge; the top stays where FO4 put it. Returns new verts."""
    import math
    R = node_rot or (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    W = [tuple(sum(R[3 * i + k] * v[k] for k in range(3)) for i in range(3)) for v in verts]
    zmin, zmax = min(w[2] for w in W), max(w[2] for w in W)
    rise = zmax - zmin
    if rise < 0.3:
        return verts
    top = [w for w in W if w[2] >= zmax - 0.05]
    tc = (sum(w[0] for w in top) / len(top), sum(w[1] for w in top) / len(top))
    # bottom edge = every vertex in the lowest 0.15 m (a slab helper has its two faces' bottom vertices at slightly
    # different heights); they all move by ONE vector along the ramp, so the slab stays planar and keeps its width
    low = [i for i, w in enumerate(W) if w[2] <= zmin + 0.15]
    lc = (sum(W[i][0] for i in low) / len(low), sum(W[i][1] for i in low) / len(low))
    dx, dy = lc[0] - tc[0], lc[1] - tc[1]
    run = math.hypot(dx, dy)
    if run < 1e-3 or math.degrees(math.atan2(rise, run)) <= max_slope:
        return verts
    extra = rise / math.tan(math.radians(max_slope)) - run
    out = list(W)
    for i in low:
        out[i] = (W[i][0] + extra * dx / run, W[i][1] + extra * dy / run, W[i][2])
    # back to node space (R is a rotation: inverse = transpose)
    return [tuple(sum(R[3 * k + i] * w[k] for k in range(3)) for i in range(3)) for w in out]


def _planes_from_faces(verts, faces) -> bytes:
    """Outward face planes (n, d) with n.x + d = 0, recomputed after vertices moved."""
    import math
    c = tuple(sum(v[i] for v in verts) / len(verts) for i in range(3))
    out = b""
    for f in faces:
        a, b, d_ = verts[f[0]], verts[f[1]], verts[f[2]]
        u = [b[i] - a[i] for i in range(3)]
        v = [d_[i] - a[i] for i in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        ln = math.sqrt(sum(x * x for x in n)) or 1.0
        n = tuple(x / ln for x in n)
        if sum(n[i] * (c[i] - a[i]) for i in range(3)) > 0:
            n = tuple(-x for x in n)
        out += struct.pack("<4f", *n, -sum(n[i] * a[i] for i in range(3)))
    return out


def _emit_convex(w: "_Writer", t: _Tmpl, p: hkpackfile.Packfile, shape: int, rot=(0.0, 0.0, 0.0, 1.0),
                 pos=(0.0, 0.0, 0.0), flatten_node_rot=None, vertex_only: bool = False) -> int:
    """FO4 hknpConvexPolytopeShape -> Starfield hknpConvexShape (hull: float3 vertices, planes, faces, indices, links).
    The FO4 body transform (absolute, NIF-root space) is baked into vertices and planes.
    vertex_only: FO4 plain hknpConvexShape (e.g. V111Glass01's panes) stores only vertices; faces come from the hull
    rebuild (a flat pane becomes a 1 cm slab)."""
    from . import fo4collision as fc
    va, nv = fc._rel(p, shape + fc.CVX_VERTS)
    if vertex_only:
        fa = ia = pa = 0
        nf = 0
    else:
        fa, nf = fc._rel(p, shape + fc.CVX_FACES)
        ia, _ = fc._rel(p, shape + fc.CVX_INDICES)
        pa, _ = fc._rel(p, shape + 64)                   # planes (count is padded to 4; one plane per face)
    R = rot if len(rot) == 9 else _quat_matrix(rot)        # 3x3 row-major matrix or (x, y, z, w) quaternion
    xf = lambda v: tuple(R[3 * i] * v[0] + R[3 * i + 1] * v[1] + R[3 * i + 2] * v[2] for i in range(3))
    verts = [tuple(a + b for a, b in zip(xf(p.unpack("<3f", va + 16 * k)), pos)) for k in range(nv)]
    planes = b""
    for k in range(nf):                                  # plane: n.x + d = 0  ->  n' = R n, d' = d - n'.pos
        nx, ny, nz, dd = p.unpack("<4f", pa + 16 * k)
        n2 = xf((nx, ny, nz))
        planes += struct.pack("<4f", *n2, dd - sum(a * b for a, b in zip(n2, pos)))
    face_raw = p.raw(fa, 4 * nf) if nf else b""
    faces = []
    for k in range(nf):
        first, cnt = struct.unpack_from("<HB", face_raw, 4 * k)
        faces.append(list(p.raw(ia + first, cnt)))
    used = sorted({v for f in faces for v in f})          # FO4 hulls can carry unreferenced vertices: compact them
    if faces and len(used) != nv:
        remap = {v: k for k, v in enumerate(used)}
        verts = [verts[v] for v in used]
        faces = [[remap[v] for v in f] for f in faces]
        nv = len(verts)
    if flatten_node_rot is not None and faces:                       # steep stair helper: stretch to a walkable slope
        moved = _flatten_helper(verts, faces, flatten_node_rot)
        if moved != verts:
            verts = moved
            planes = _planes_from_faces(verts, faces)
    try:
        _hull_links(faces, nv)
    except hkpackfile.PackfileError:                       # FO4 hull with broken topology: rebuild faces from vertices
        verts = thicken_if_flat(verts)
        faces = convex_hull_faces(verts)
        try:
            _hull_links(faces, len(verts))
        except hkpackfile.PackfileError:                   # overlapping near-coplanar polygons: triangulated hull
            faces = convex_hull_triangles(verts)
        used = sorted({v for f in faces for v in f})
        remap = {v: k for k, v in enumerate(used)}
        verts = [verts[v] for v in used]
        faces = [[remap[v] for v in f] for f in faces]
        nv, nf = len(verts), len(faces)
        face_raw = bytes([0, 0, 0, 127]) * nf               # minHalfAngle 127 as vanilla boxes; rebuilt by _faces_raw
        planes = _planes_from_faces(verts, faces)
    nidx = sum(len(f) for f in faces)
    links, vedges = _hull_links(faces, nv)
    T_CVX = t.type("hknpConvexShape")
    body = bytearray(t.item_bytes("hknpConvexShape"))
    radius, = p.unpack("<f", shape + 20)
    struct.pack_into("<f", body, t.field(T_CVX, "convexRadius").offset, radius)
    struct.pack_into("<Q", body, t.field(T_CVX, "properties").offset, 0)             # static: no mass properties
    hull = t.field(T_CVX, "hull")
    for fname in ("vertices", "planes", "faces", "indices", "faceLinks", "vertexEdges"):
        struct.pack_into("<Q", body, hull.offset + t.field(hull.type, fname).offset, 0)
    i_shape = w.add(T_CVX, 0x10, body, 1)
    edge = lambda fe: struct.pack("<HBB", fe[0], fe[1], 0)
    payloads = {
        "vertices": (b"".join(struct.pack("<3f", *v) for v in verts), nv),
        "planes": (planes, nf),
        "faces": (_faces_raw(faces, face_raw), nf),
        "indices": (bytes(v for f in faces for v in f), nidx),
        "faceLinks": (b"".join(edge(x) for x in links), len(links)),
        "vertexEdges": (b"".join(edge(x) for x in vedges), nv),
    }
    for fname, (raw, n) in payloads.items():
        rel_t = t.field(hull.type, fname).type                       # hkRelArray<E>
        elem_t = dict(t.tf.types[rel_t].params)["tT"]
        i = w.add(elem_t, 0x20, raw, n)
        w.ptr(rel_t, i_shape, hull.offset + t.field(hull.type, fname).offset, i)
    return i_shape


def _shift_aabb(raw: bytes, pos) -> bytes:
    lo = struct.unpack_from("<4f", raw, 0)
    hi = struct.unpack_from("<4f", raw, 16)
    return struct.pack("<8f", *(lo[i] + pos[i] for i in range(3)), lo[3], *(hi[i] + pos[i] for i in range(3)), hi[3])


def _emit_mesh(w: "_Writer", t: _Tmpl, p: hkpackfile.Packfile, d: int, pos=(0.0, 0.0, 0.0)) -> int:
    """FO4 hknpCompressedMeshShapeData -> Starfield hknpCompressedMeshShape (+ data, trees, SIMD tree). A body
    translation is baked in (domain, section domains and codec offsets move; quantised data stay relative)."""
    from . import fo4collision
    tf = t.tf
    T_CMS, T_DATA = t.type("hknpCompressedMeshShape"), t.type("hknpCompressedMeshShapeData")
    T_TREE, T_SEC = t.type("hknpCompressedMeshShapeTree"), t.type("hkcdStaticMeshTree::Section")
    tree_off = t.field(T_DATA, "meshTree").offset
    fo4 = {}
    for name, off in FO4_ARRAYS.items():
        at, n = p.array(d + off)
        fo4[name] = (p.raw(at, ELEM_SIZE[name] * n) if n else b"", n)
    cms = bytearray(t.item_bytes("hknpCompressedMeshShape"))
    struct.pack_into("<Q", cms, t.field(T_CMS, "properties").offset, 0)
    n_keys, bits_per_key, max_key = struct.unpack_from("<iiI", p.raw(d + FO4_TREE + 48, 12))
    struct.pack_into("<ii", cms, t.field(T_CMS, "numTriangles").offset, 0, 0)
    cms[t.field(T_CMS, "numShapeKeyBits").offset] = bits_per_key
    bits = t.field(T_CMS, "triangleIsInterior")
    words_ptr = t.field(bits.type, "storage").type
    words_arr = t.field(words_ptr, "words").type
    n_bits = max_key + 1
    struct.pack_into("<i", cms, bits.offset + t.field(words_ptr, "numBits").offset, n_bits)
    for fname in ("data",):
        struct.pack_into("<Q", cms, t.field(T_CMS, fname).offset, 0)
    struct.pack_into("<16x", cms, t.field(T_CMS, "externShapes").offset)
    i_cms = w.add(T_CMS, 0x10, cms, 1)
    nwords = (n_bits + 31) // 32
    i_words = w.add(dict(tf.types[words_arr].params)["tT"], 0x20, bytes(4 * nwords), nwords)
    w.ptr(words_arr, i_cms, bits.offset + t.field(words_ptr, "words").offset, i_words)

    data = bytearray(t.item_bytes("hknpCompressedMeshShapeData"))
    for f in ("nodes", "sections", "primitives", "sharedVerticesIndex", "packedVertices", "sharedVertices",
              "primitiveDataRuns"):
        struct.pack_into("<16x", data, tree_off + t.field(T_TREE, f).offset)
    data[tree_off + 16:tree_off + 48] = _shift_aabb(p.raw(d + FO4_TREE + 16, 32), pos)
    data[tree_off + 48:tree_off + 64] = p.raw(d + FO4_TREE + 48, 16)
    simd = t.field(T_DATA, "simdTree")
    data[simd.offset:simd.offset + tf.size_of(simd.type)] = bytes(tf.size_of(simd.type))
    conn = t.field(T_DATA, "connectivity")
    data[conn.offset:conn.offset + tf.size_of(conn.type)] = bytes(tf.size_of(conn.type))
    data[t.field(T_DATA, "hasSimdTree").offset] = 1
    data[simd.offset + t.field(simd.type, "isCompact").offset] = 1
    i_data = w.add(T_DATA, 0x10, data, 1)
    w.ptr(t.field(T_CMS, "data").type, i_cms, t.field(T_CMS, "data").offset, i_data)
    keys = [(k, (tuple(a + b for a, b in zip(lo, pos)), tuple(a + b for a, b in zip(hi, pos))))
            for k, (lo, hi) in fo4collision.compressed_mesh_keys(p, d)]
    simd_raw = build_simd_tree(keys)
    simd_arr_t, simd_elem_t = t.arr_types(simd.type, "nodes")
    i_simd = w.add(simd_elem_t, 0x20, simd_raw, len(simd_raw) // 128)
    w.ptr(simd_arr_t, i_data, simd.offset + t.field(simd.type, "nodes").offset, i_simd)
    for name in ("nodes", "primitives", "sharedVerticesIndex", "packedVertices", "sharedVertices", "primitiveDataRuns"):
        raw, n = fo4[name]
        if n:
            arr_t, elem_t = t.arr_types(T_TREE, name)
            i = w.add(elem_t, 0x20, raw, n)
            w.ptr(arr_t, i_data, tree_off + t.field(T_TREE, name).offset, i)
    sec_raw, nsec = fo4["sections"]
    sec_arr_t, sec_elem_t = t.arr_types(T_TREE, "sections")
    secs = []
    for k in range(nsec):
        s = _convert_section(sec_raw[96 * k:96 * k + 96])
        s[16:48] = _shift_aabb(bytes(s[16:48]), pos)
        struct.pack_into("<3f", s, 48, *(a + b for a, b in zip(struct.unpack_from("<3f", s, 48), pos)))   # codec offset
        secs.append(bytes(s))
    i_secs = w.add(sec_elem_t, 0x20, b"".join(secs), nsec)
    w.ptr(sec_arr_t, i_data, tree_off + t.field(T_TREE, "sections").offset, i_secs)
    sec_at, _ = p.array(d + FO4_ARRAYS["sections"])
    node_arr_t, node_elem_t = t.arr_types(T_SEC, "nodes")
    for k in range(nsec):
        at, n = p.array(sec_at + 96 * k)
        if n:
            i = w.add(node_elem_t, 0x20, p.raw(at, FO4_SECTION_NODES * n), n)
            w.ptr(node_arr_t, i_secs, 96 * k + t.field(T_SEC, "nodes").offset, i)
    return i_cms


# FO4 and Starfield collision layers share indices 0-36 and 38-42, 44-56 (COLL records); 37 and 43 differ.
FO4_BODY_FILTER = 20                                  # FO4 hknpBodyCinfo collisionFilterInfo (layer in the low 7 bits)
UNMAPPED_LAYERS = {37: "L_DOORDETECTION", 43: "L_CUSTOMPICK1"}


def convert_bodies(fo4_blob: bytes, template_blob: bytes, select: Optional[List[int]] = None,
                   node_rot=None, skipped: Optional[list] = None) -> list:
    """One native Starfield single-body physics blob per selected FO4 body (all bodies when select is None).
    FO4 shapes live in the space of the NIF node that owns the collision object; the body cinfo transform is not a
    placement (a crate whose shape already matches its render mesh carries a 0.29 m body position; a stair helper's
    body rotation duplicates its node's). So the Starfield body is identity, as in vanilla files, and the caller puts the
    blob on a node with the FO4 node's transform. The FO4 collision layer is kept (stair helpers stay stair helpers).
    Unsupported shapes or layers raise PackfileError (explicit fallback).
    Items are blobs, or (blob, translation, rotation 3x3 row-major) for a rotated compound mesh instance: that body is
    in its own space and goes on a child node with this transform (relative to the FO4 collision node)."""
    from . import fo4collision as fc
    p = hkpackfile.Packfile(fo4_blob)
    classes = dict(p.objects())
    systems = [o for o, c in classes.items() if c == "hknpPhysicsSystemData"]
    if len(systems) != 1:
        raise hkpackfile.PackfileError("expected one source physics system")
    at, n = p.array(systems[0] + fc.SYS_BODIES)
    if n <= 0 or at is None:
        return []
    t = _Tmpl(template_blob)
    T_PSD, T_BODY = t.type("hknpPhysicsSystemData"), t.type("hknpPhysicsSystemData::bodyCinfoWithAttachment")
    T_MAT = t.type("hknpMaterial")
    type_sec = next(blob_sec for blob_sec in (template_blob[s - 8:e] for tag, s, e in
                    hktagfile.sections(template_blob, 8, len(template_blob)) if tag == "TYPE"))
    sdk = next(template_blob[s:e] for tag, s, e in hktagfile.sections(template_blob, 8, len(template_blob)) if tag == "SDKV")
    out = []
    for k in (range(n) if select is None else select):
        if not 0 <= k < n:
            raise hkpackfile.PackfileError(f"collision object selects missing body {k} of {n}")
        b = at + fc.BODY_SIZE * k
        shape = p.pointer(b)
        cls = classes.get(shape, "?")
        pos, rot = p.unpack("<4f", b + fc.BODY_POS), p.unpack("<4f", b + fc.BODY_ROT)
        if not all(math.isfinite(x) for x in pos + rot):
            raise hkpackfile.PackfileError("non-finite source body transform")
        if os.environ.get("FO4PORT_SKIP_ROTATED_BODIES") == "1" and any(abs(x) > 1e-4 for x in rot[:3]):
            continue                                      # diagnostic only: isolate rotated bodies in game tests
        filt, = p.unpack("<I", b + FO4_BODY_FILTER)
        if os.environ.get("FO4PORT_DROP_STAIRHELPER") == "1" and (filt & 0x7F) == 31:
            continue                                       # diagnostic only: test stairs without the helper ramp
        if (filt & 0x7F) in UNMAPPED_LAYERS:
            raise hkpackfile.PackfileError(f"body {k} uses {UNMAPPED_LAYERS[filt & 0x7F]} (no Starfield equivalent)")
        for kind, obj, R, tr in _shape_parts(p, classes, shape, IDENTITY3, (0.0, 0.0, 0.0)):
            w = _Writer()
            i_psd = w.add(T_PSD, 0x10, t.item_bytes("hknpPhysicsSystemData"), 1)
            i_mat = w.add(T_MAT, 0x20, t.item_bytes("hknpMaterial", count=1), 1)
            body = bytearray(t.item_bytes("hknpPhysicsSystemData::bodyCinfoWithAttachment", count=1))
            struct.pack_into("<H", body, t.field(T_BODY, "materialId").offset, 0)
            struct.pack_into("<4f", body, t.field(T_BODY, "position").offset, 0.0, 0.0, 0.0, 0.0)
            struct.pack_into("<4f", body, t.field(T_BODY, "orientation").offset, 0.0, 0.0, 0.0, 1.0)
            struct.pack_into("<I", body, t.field(T_BODY, "collisionFilterInfo").offset, filt)
            i_body = w.add(T_BODY, 0x20, body, 1)
            w.ptr(t.field(T_PSD, "materials").type, i_psd, t.field(T_PSD, "materials").offset, i_mat)
            w.ptr(t.field(T_PSD, "bodyCinfos").type, i_psd, t.field(T_PSD, "bodyCinfos").offset, i_body)
            if kind == "mesh":
                try:
                    keys = fc.compressed_mesh_keys(p, obj)
                except hkpackfile.PackfileError as e:
                    # FO4 precombines (CM*.NIF) carry extra small bodies whose primitives use another encoding (packed 0,
                    # 4 shared vertices per primitive, index triples): thin debris rods ~1 cm thick. Not decoded yet.
                    # Skip that part only and report it, instead of losing the whole model's collision to guessed boxes.
                    if skipped is None or "shared vertex index" not in str(e):
                        raise
                    skipped.append(f"body {k}: {e}")
                    continue
                if not keys:                               # only degenerate / unused primitives: nothing to collide with
                    continue
                if any(abs(a - b_) > 1e-4 for a, b_ in zip(R, IDENTITY3)):
                    # rotated compound instance: keep the mesh in its own space and return the instance transform for
                    # the caller's child node (re-quantising the compressed mesh would change FO4's geometry)
                    i_shape = _emit_mesh(w, t, p, obj, (0.0, 0.0, 0.0))
                    w.ptr(t.field(T_BODY, "shape").type, i_body, t.field(T_BODY, "shape").offset, i_shape)
                    out.append((w.build(sdk, type_sec), tuple(tr), tuple(R)))
                    continue
                i_shape = _emit_mesh(w, t, p, obj, tr)
            elif kind == "sphere":
                i_shape = _emit_sphere(w, t, p, obj, R, tr)
            else:
                helper = (filt & 0x7F) == 31
                i_shape = _emit_convex(w, t, p, obj, R, tr,
                                       flatten_node_rot=(node_rot or IDENTITY3) if helper else None,
                                       vertex_only=(kind == "convex-verts"))
            w.ptr(t.field(T_BODY, "shape").type, i_body, t.field(T_BODY, "shape").offset, i_shape)
            out.append(w.build(sdk, type_sec))
    return out


IDENTITY3 = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
# hknpDynamicCompoundShape (FO4 2014; layout as in Codex's fo4_compounds.py, cross-checked with PyNifly): instances
# hkArray @96, 128 bytes each: rotation as three column vectors @0/16/32, translation @48, scale @64, child shape @80
COMPOUND_INSTANCES, INSTANCE_SIZE = 96, 128


def _shape_parts(p, classes, shape, R, tr, depth=0):
    """Leaf shapes of an FO4 body shape with their accumulated transform (node space): [(kind, object, R, translation)],
    kind "mesh" (object = compressed mesh data) or "convex" (object = convex polytope). Compounds are flattened."""
    from . import fo4collision as fc
    if depth > 16:
        raise hkpackfile.PackfileError("compound collision nesting too deep")
    cls = classes.get(shape, "?")
    if cls == "hknpCompressedMeshShape":
        d = p.pointer(shape + fc.CMS_DATA)
        if d is None:
            raise hkpackfile.PackfileError("compressed mesh body has no data")
        return [("mesh", d, R, tr)]
    if cls in ("hknpConvexPolytopeShape", "hknpCapsuleShape"):   # FO4 capsules carry a full polytope hull + radius
        return [("convex", shape, R, tr)]
    if cls == "hknpConvexShape":                                  # vertices only (glass panes): hull rebuilt
        return [("convex-verts", shape, R, tr)]
    if cls == "hknpSphereShape":
        return [("sphere", shape, R, tr)]
    if cls == "hknpDynamicCompoundShape":
        at, n = p.array(shape + COMPOUND_INSTANCES)
        if n <= 0 or n > 65535 or at is None:
            raise hkpackfile.PackfileError("invalid compound instance array")
        parts = []
        for i in range(n):
            inst = at + INSTANCE_SIZE * i
            child = p.pointer(inst + 80)
            if child is None:
                raise hkpackfile.PackfileError("compound child shape missing")
            cols = [p.unpack("<3f", inst + 16 * c) for c in range(3)]
            Ri = tuple(cols[c][r] for r in range(3) for c in range(3))
            ti = p.unpack("<3f", inst + 48)
            scale = p.unpack("<3f", inst + 64)
            if not all(math.isfinite(x) for x in Ri + ti + scale) or any(abs(s - 1) > 1e-4 for s in scale):
                raise hkpackfile.PackfileError("scaled or non-finite compound instance (not supported yet)")
            R2 = tuple(sum(R[3 * r + k] * Ri[3 * k + c] for k in range(3)) for r in range(3) for c in range(3))
            t2 = tuple(tr[r] + sum(R[3 * r + k] * ti[k] for k in range(3)) for r in range(3))
            parts += _shape_parts(p, classes, child, R2, t2, depth + 1)
        return parts
    raise hkpackfile.PackfileError(f"unsupported shape {cls}")
