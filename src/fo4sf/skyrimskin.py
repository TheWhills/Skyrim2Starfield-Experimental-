"""Skinned (worn) Skyrim SE meshes: bones, bind transforms, per-vertex weights and body-part partitions. Read-only.

Layouts from niftools nif.xml (github.com/niftools/nifxml, read 2026-10-15), Skyrim SE = NIF 20.2.0.7, BS 100:
* NiSkinInstance: Data ref, Skin Partition ref, Skeleton Root ptr, Num Bones u32, Bones ptr[n].
  BSDismemberSkinInstance adds Num Partitions u32 + (Part Flag u16, Body Part u16) each.
* NiSkinData: Skin Transform (NiTransform: 3 x 3 rotation, translation, scale = 52 bytes), Num Bones u32, Has Vertex
  Weights u8, per bone: Skin Transform (52), Bounding Sphere (16), Num Vertices u16, [index u16, weight f32] x n.
* NiSkinPartition (SSE): Num Partitions u32, Data Size u32, Vertex Size u32, Vertex Desc u64, Vertex Data (Data Size /
  Vertex Size vertices, BSVertexDataSSE), then per partition: Num Vertices, Num Triangles, Num Bones, Num Strips,
  Num Weights Per Vertex (u16 each), Bones u16[], Has Vertex Map u8, Vertex Map u16[], Has Vertex Weights u8,
  Weights f32[nv x wpv], Strip Lengths u16[], Has Faces u8, Strips / Triangles, Has Bone Indices u8,
  Bone Indices u8[nv x wpv], LOD Level u8, Global VB u8, Vertex Desc u64, Triangles Copy (u16 x 3)[Num Triangles].
* A skinned SSE BSTriShape stores no vertices itself (data size 0): they are the partition block's Vertex Data, and
  "Triangles Copy" indexes them (the partition's own Triangles index its Vertex Map).
* BSVertexDesc: bits 0-3 vertex size / 4; 4-bit offsets / 4 at 8 (UV), 16 (normal), 20 (tangent), 24 (colour),
  28 (skin: 4 half-float weights + 4 u8 bone indices); attribute flags from bit 44 (0x40 = skinned).

* Weights: NiSkinData's per-bone vertex lists when stored (Has Vertex Weights); otherwise the global vertex buffer's
  4 weights + 4 bone indices per vertex, read as indices into the Bones list of the partition whose Vertex Map holds
  that vertex (**supported hypothesis**: each partition has its own bone palette; to confirm on real meshes).

Status: layouts **from nif.xml, checked on synthetic files only**; the first-run armor survey is the check on real
meshes (parse errors, weight sums, bone counts).
"""
import struct
from dataclasses import dataclass, field
from typing import List, Optional

from . import nif as nifmod
from . import skyrimnif

VF_SKIN = 0x40
TRANSFORM = struct.Struct("<9f3ff")              # NiTransform: rotation (row-major), translation, scale


@dataclass
class Bind:
    rotation: tuple
    translation: tuple
    scale: float


@dataclass
class SkinnedShape:
    name: bytes
    block: int
    bones: List[bytes]                           # bone node names, in skin order
    skin_transform: Optional[Bind]               # NiSkinData overall transform (None without NiSkinData)
    binds: List[Bind]                            # per bone: skin -> bone space at bind time
    positions: list
    uvs: list
    normals: list
    tangents: list
    triangles: list
    weights: list                                # per vertex [(bone index into `bones`, weight)], weights sum to 1
    weight_source: str                           # "skin_data" | "partition_vertices" | "none"
    body_parts: List[int] = field(default_factory=list)   # BSDismember partitions: body part ids (32 = body, ...)
    partitions: list = field(default_factory=list)        # [{"vertices", "triangles", "bones", "body_part"}]
    shader_ref: int = -1
    alpha_ref: int = -1


def _transform(d, p):
    v = TRANSFORM.unpack_from(d, p)
    return Bind(v[0:9], v[9:12], v[12])


def _skin_instance(n, i):
    blk = n.blocks[i]
    data, part, root, nb = struct.unpack_from("<iiiI", blk, 0)
    bones = list(struct.unpack_from(f"<{nb}i", blk, 16))
    p = 16 + 4 * nb
    parts = []
    if n.type_of(i) == "BSDismemberSkinInstance":
        np_, = struct.unpack_from("<I", blk, p); p += 4
        parts = [struct.unpack_from("<HH", blk, p + 4 * k) for k in range(np_)]
        p += 4 * np_
    if p != len(blk):
        raise nifmod.NifError(f"block {i}: {n.type_of(i)} has {len(blk) - p} unparsed bytes")
    return data, part, bones, parts


def _skin_data(blk):
    """(overall transform, per-bone binds, per-bone [(vertex, weight)] or None when weights are not stored)."""
    overall = _transform(blk, 0)
    nb, = struct.unpack_from("<I", blk, 52)
    has_w = blk[56]
    p = 57
    binds, weights = [], []
    for _ in range(nb):
        binds.append(_transform(blk, p)); p += 52
        p += 16                                                  # bounding sphere
        nv, = struct.unpack_from("<H", blk, p); p += 2
        if has_w:
            weights.append([struct.unpack_from("<Hf", blk, p + 6 * k) for k in range(nv)])
            p += 6 * nv
        else:
            weights.append(None)
    if p != len(blk):
        raise nifmod.NifError(f"NiSkinData: {len(blk) - p} unparsed bytes")
    return overall, binds, (weights if has_w else None)


def _vertices(buf, p, count, desc):
    """Decode `count` BSVertexDataSSE vertices from buf[p:]: positions, uvs, normals, tangents, skin [(idx[4], w[4])]."""
    vsize = (desc & 0xF) * 4
    attrs = (desc >> 44) & 0xFFF
    o_uv, o_n, o_t, o_s = (((desc >> s) & 0xF) * 4 for s in (8, 16, 20, 28))
    unb = lambda b: tuple(c / 255.0 * 2.0 - 1.0 for c in b[:3])   # noqa: E731
    pos, uv, nor, tan, skin = [], [], [], [], []
    for v in range(count):
        q = p + v * vsize
        if attrs & skyrimnif.VF_VERTEX:
            pos.append(struct.unpack_from("<3f", buf, q))
        if attrs & skyrimnif.VF_UV:
            uv.append(tuple(struct.unpack_from("<2e", buf, q + o_uv)))
        if attrs & skyrimnif.VF_NORMAL:
            nor.append(unb(buf[q + o_n:q + o_n + 4]))
            if attrs & skyrimnif.VF_TANGENT:
                tan.append(unb(buf[q + o_t:q + o_t + 4]))
        if attrs & VF_SKIN:
            w = struct.unpack_from("<4e", buf, q + o_s)
            idx = tuple(buf[q + o_s + 8:q + o_s + 12])
            skin.append((idx, w))
    return pos, uv, nor, tan, skin, p + count * vsize


def _skin_partition(blk, ssemode=True):
    """{"vertices": decoded global vertex buffer or None, "partitions": [...]}."""
    nparts, = struct.unpack_from("<I", blk, 0)
    p = 4
    glob = None
    if ssemode:
        dsize, vsize, desc = struct.unpack_from("<IIQ", blk, p); p += 16
        if dsize:
            if vsize == 0 or dsize % vsize:
                raise nifmod.NifError(f"NiSkinPartition: data size {dsize} not a multiple of vertex size {vsize}")
            pos, uv, nor, tan, skin, p = _vertices(blk, p, dsize // vsize, desc)
            glob = {"positions": pos, "uvs": uv, "normals": nor, "tangents": tan, "skin": skin, "desc": desc}
    parts = []
    for _ in range(nparts):
        nv, nt, nb, ns, wpv = struct.unpack_from("<5H", blk, p); p += 10
        bones = list(struct.unpack_from(f"<{nb}H", blk, p)); p += 2 * nb
        has_map = blk[p]; p += 1
        vmap = list(struct.unpack_from(f"<{nv}H", blk, p)) if has_map else list(range(nv))
        p += 2 * nv if has_map else 0
        has_w = blk[p]; p += 1
        w = [struct.unpack_from(f"<{wpv}f", blk, p + 4 * wpv * k) for k in range(nv)] if has_w else None
        p += 4 * wpv * nv if has_w else 0
        lens = list(struct.unpack_from(f"<{ns}H", blk, p)); p += 2 * ns
        has_faces = blk[p]; p += 1
        tris = []
        if has_faces and ns:
            for ln in lens:
                s = struct.unpack_from(f"<{ln}H", blk, p); p += 2 * ln
                tris += [(s[k], s[k + 1], s[k + 2]) if k % 2 == 0 else (s[k], s[k + 2], s[k + 1])
                         for k in range(ln - 2) if len({s[k], s[k + 1], s[k + 2]}) == 3]
        elif has_faces:
            tris = list(struct.iter_unpack("<3H", blk[p:p + 6 * nt])); p += 6 * nt
        has_bi = blk[p]; p += 1
        bi = [tuple(blk[p + wpv * k:p + wpv * (k + 1)]) for k in range(nv)] if has_bi else None
        p += wpv * nv if has_bi else 0
        copy = []
        if ssemode:
            p += 1 + 1 + 8                                       # LOD level, global VB, vertex desc
            copy = list(struct.iter_unpack("<3H", blk[p:p + 6 * nt])); p += 6 * nt
        parts.append({"vertices": nv, "triangles": nt, "bones": bones, "vertex_map": vmap, "weights": w,
                      "bone_indices": bi, "local_triangles": tris, "global_triangles": copy})
    if p != len(blk):
        raise nifmod.NifError(f"NiSkinPartition: {len(blk) - p} unparsed bytes")
    return {"vertices": glob, "partitions": parts}


def _normalise(ws):
    ws = [(b, w) for b, w in ws if w > 0]
    total = sum(w for _, w in ws) or 1.0
    return sorted(((b, w / total) for b, w in ws), key=lambda t: -t[1])


def skinned_shapes(n: nifmod.NifFile) -> List[SkinnedShape]:
    """Every skinned shape (BSTriShape / BSDynamicTriShape / NiTriShape with a skin instance) of a Skyrim SE NIF."""
    out = []
    for i, blk in enumerate(n.blocks):
        t = n.type_of(i)
        if t not in skyrimnif.TRI_TYPES + ("BSDynamicTriShape", "NiTriShape", "NiTriStrips"):
            continue
        if t in ("NiTriShape", "NiTriStrips"):
            p = skyrimnif._av_size(blk)
            skin_ref, = struct.unpack_from("<i", blk, p + 4)
        else:
            p = skyrimnif._av_size(blk) + 16
            skin_ref, = struct.unpack_from("<i", blk, p)
        if not (0 <= skin_ref < len(n.blocks)) or n.type_of(skin_ref) not in ("NiSkinInstance",
                                                                               "BSDismemberSkinInstance"):
            continue
        out.append(_one(n, i, blk, t, skin_ref))
    return out


def _one(n, i, blk, t, skin_ref):
    data_ref, part_ref, bone_refs, dismember = _skin_instance(n, skin_ref)
    bones = [skyrimnif._name(n, n.blocks[b]) if 0 <= b < len(n.blocks) else b"" for b in bone_refs]
    overall, binds, sd_weights = None, [], None
    if 0 <= data_ref < len(n.blocks) and n.type_of(data_ref) == "NiSkinData":
        overall, binds, sd_weights = _skin_data(n.blocks[data_ref])
        if len(binds) != len(bones):
            raise nifmod.NifError(f"block {i}: skin data has {len(binds)} bones, instance {len(bones)}")
    part = None
    if 0 <= part_ref < len(n.blocks) and n.type_of(part_ref) == "NiSkinPartition":
        part = _skin_partition(n.blocks[part_ref], ssemode=n.bs_version == skyrimnif.BS_SSE)

    shader = alpha = -1
    pos = uv = nor = tan = tris = []
    vertex_skin = None
    if t in ("NiTriShape", "NiTriStrips"):
        s = skyrimnif._nitrishape(n, i, blk, nifmod.world_transforms(n))
        if s is not None:
            pos, uv, nor, tan, tris, shader, alpha = (s.positions, s.uvs, s.normals, s.tangents, s.triangles,
                                                      s.shader_ref, s.alpha_ref)
    else:
        p = skyrimnif._av_size(blk) + 16
        _skin, shader, alpha = struct.unpack_from("<iii", blk, p); p += 12
        desc, = struct.unpack_from("<Q", blk, p); p += 8
        ntri, nvert, dsize = struct.unpack_from("<HHI", blk, p); p += 8
        if dsize:
            pos, uv, nor, tan, vertex_skin, p = _vertices(blk, p, nvert, desc)
            tris = list(struct.iter_unpack("<3H", blk[p:p + 6 * ntri]))
        elif part and part["vertices"]:
            g = part["vertices"]
            pos, uv, nor, tan, vertex_skin = g["positions"], g["uvs"], g["normals"], g["tangents"], g["skin"]
            tris = [tr for pt in part["partitions"] for tr in pt["global_triangles"]]
        if t == "BSDynamicTriShape":       # trailing Dynamic Data Size u32 (bytes) + vertices as (x, y, z, w) floats
            nd, = struct.unpack_from("<I", blk, len(blk) - 4 - 16 * nvert) if len(blk) >= 4 + 16 * nvert else (0,)
            if nd == 16 * nvert and nvert:
                q = len(blk) - 16 * nvert
                pos = [struct.unpack_from("<3f", blk, q + 16 * k) for k in range(nvert)]

    nv = len(pos)
    weights, source = [[] for _ in range(nv)], "none"
    if sd_weights is not None:
        for b, lst in enumerate(sd_weights):
            for v, w in lst:
                if v < nv:
                    weights[v].append((b, w))
        source = "skin_data"
    elif vertex_skin and part:
        # global vertex buffer: bone indices are partition-local (into that partition's Bones list)
        owner = {}
        for pt in part["partitions"]:
            for v in pt["vertex_map"]:
                owner.setdefault(v, pt["bones"])
        for v, (idx, ws) in enumerate(vertex_skin):
            pb = owner.get(v)
            if pb is not None:
                weights[v] = [(pb[idx[k]], float(ws[k])) for k in range(4) if k < len(idx) and idx[k] < len(pb)]
        source = "partition_vertices"
    weights = [_normalise(w) for w in weights]

    body = [bp for _flag, bp in dismember]
    parts = []
    if part:
        for k, pt in enumerate(part["partitions"]):
            parts.append({"vertices": pt["vertices"], "triangles": pt["triangles"],
                          "bones": [bones[b] if b < len(bones) else b"" for b in pt["bones"]],
                          "body_part": body[k] if k < len(body) else None})
    return SkinnedShape(skyrimnif._name(n, blk), i, bones, overall, binds, pos, uv, nor, tan, tris, weights, source,
                        body, parts, shader, alpha)


def check(s: SkinnedShape) -> dict:
    """Sanity numbers for the real-data survey: vertices without weights, weight sums, bones per shape."""
    unweighted = sum(1 for w in s.weights if not w)
    max_inf = max((len(w) for w in s.weights), default=0)
    bad_tri = sum(1 for tr in s.triangles if max(tr) >= len(s.positions)) if s.positions else len(s.triangles)
    return {"vertices": len(s.positions), "triangles": len(s.triangles), "bones": len(s.bones),
            "unweighted_vertices": unweighted, "max_influences": max_inf, "out_of_range_triangles": bad_tri,
            "weight_source": s.weight_source, "body_parts": s.body_parts}
