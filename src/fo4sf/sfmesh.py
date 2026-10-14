"""Starfield `.mesh` (BSMeshData) reader and writer.

Layout from the open-source fo76utils/nifskope `nif.xml` (`BSMeshData`) and `MeshFile.cpp`.
Everything is little-endian. Values are kept in their *raw packed form* so that
parse -> serialize is byte-identical (the S1 oracle); helpers decode/encode to floats.

    u32 version (0..2)
    u32 indices_size; indices_size/3 x (u16,u16,u16)          triangles
    f32 scale; u32 weights_per_vertex
    u32 n; n x (i16,i16,i16)                                  positions, value = i16/32767*scale
    u32 n; n x (f16,f16)                                      uv1
    u32 n; n x (f16,f16)                                      uv2
    u32 n; n x u32 BGRA                                       vertex colours
    u32 n; n x u32                                            normals  (packed 10:10:10:2)
    u32 n; n x u32                                            tangents (packed 10:10:10:2, w = bitangent sign)
    u32 n; n x (u16 bone, u16 weight)                         skin weights
    [version >= 1] u32 n_lods; n x (u32 indices_size, tris)   lower LODs
    [optional] u32 n; n x 4 x u32                             meshlets (vcount, voffset, tcount, toffset)
    [optional] u32 n; n x 24 bytes                            cull data
The last two sections are absent in some skinned meshes (the file ends after the LOD count).
"""
import struct
from dataclasses import dataclass, field
from typing import List, Tuple

Tri = Tuple[int, int, int]


@dataclass
class SfMesh:
    version: int = 2
    triangles: List[Tri] = field(default_factory=list)
    scale: float = 1.0
    weights_per_vertex: int = 0
    positions: List[Tuple[int, int, int]] = field(default_factory=list)   # raw int16
    uv1: List[Tuple[int, int]] = field(default_factory=list)             # raw half-float bits
    uv2: List[Tuple[int, int]] = field(default_factory=list)
    colors: List[int] = field(default_factory=list)                      # raw u32 BGRA
    normals: List[int] = field(default_factory=list)                     # raw packed u32
    tangents: List[int] = field(default_factory=list)
    weights: List[Tuple[int, int]] = field(default_factory=list)
    lods: List[List[Tri]] = field(default_factory=list)
    meshlets: List[Tuple[int, int, int, int]] = field(default_factory=list)
    cull_data: List[bytes] = field(default_factory=list)                 # 24 bytes each
    has_meshlet_section: bool = True                                     # False: file ends after the LOD count
    tail: bytes = b""                                                    # unparsed trailing bytes (should be empty)


class MeshFormatError(ValueError):
    pass


class _Reader:
    def __init__(self, data):
        self.d, self.p = data, 0

    def u32(self):
        self._need(4)
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self):
        self._need(4)
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def array(self, count, fmt):
        size = struct.calcsize("<" + fmt)
        self._need(count * size)
        out = list(struct.iter_unpack("<" + fmt, self.d[self.p:self.p + count * size]))
        self.p += count * size
        return out

    def raw(self, n):
        self._need(n)
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def _need(self, n):
        if self.p + n > len(self.d):
            raise MeshFormatError(f"truncated at {self.p}, need {n} more bytes of {len(self.d)}")


def parse(data: bytes) -> SfMesh:
    r = _Reader(data)
    m = SfMesh()
    m.version = r.u32()
    if m.version > 2:
        raise MeshFormatError(f"unknown mesh version {m.version}")
    idx = r.u32()
    if idx % 3:
        raise MeshFormatError(f"index count {idx} not a multiple of 3")
    m.triangles = r.array(idx // 3, "HHH")
    m.scale = r.f32()
    m.weights_per_vertex = r.u32()
    m.positions = r.array(r.u32(), "hhh")
    m.uv1 = r.array(r.u32(), "HH")
    m.uv2 = r.array(r.u32(), "HH")
    m.colors = [v for (v,) in r.array(r.u32(), "I")]
    m.normals = [v for (v,) in r.array(r.u32(), "I")]
    m.tangents = [v for (v,) in r.array(r.u32(), "I")]
    m.weights = r.array(r.u32(), "HH")
    if m.version >= 1:
        for _ in range(r.u32()):
            n = r.u32()
            if n % 3:
                raise MeshFormatError("LOD index count not a multiple of 3")
            m.lods.append(r.array(n // 3, "HHH"))
    # Some skinned meshes (e.g. face meshes) end right after the LOD count: no meshlet/cull sections at all.
    m.has_meshlet_section = r.p < len(data)
    if m.has_meshlet_section:
        m.meshlets = r.array(r.u32(), "IIII")
        m.cull_data = [r.raw(24) for _ in range(r.u32())]
    m.tail = data[r.p:]
    return m


def serialize(m: SfMesh) -> bytes:
    out = [struct.pack("<II", m.version, len(m.triangles) * 3)]
    out.append(b"".join(struct.pack("<HHH", *t) for t in m.triangles))
    out.append(struct.pack("<fI", m.scale, m.weights_per_vertex))

    def arr(items, fmt, flat=False):
        pack = (lambda i: struct.pack("<" + fmt, i)) if flat else (lambda i: struct.pack("<" + fmt, *i))
        return struct.pack("<I", len(items)) + b"".join(pack(i) for i in items)

    out.append(arr(m.positions, "hhh"))
    out.append(arr(m.uv1, "HH"))
    out.append(arr(m.uv2, "HH"))
    out.append(arr(m.colors, "I", flat=True))
    out.append(arr(m.normals, "I", flat=True))
    out.append(arr(m.tangents, "I", flat=True))
    out.append(arr(m.weights, "HH"))
    if m.version >= 1:
        out.append(struct.pack("<I", len(m.lods)))
        for lod in m.lods:
            out.append(struct.pack("<I", len(lod) * 3) + b"".join(struct.pack("<HHH", *t) for t in lod))
    if m.has_meshlet_section:
        out.append(arr(m.meshlets, "IIII"))
        out.append(struct.pack("<I", len(m.cull_data)) + b"".join(m.cull_data))
    out.append(m.tail)
    return b"".join(out)


# ---- meshlets ------------------------------------------------------------------------------
# Rule verified against 4,000 vanilla meshes (docs/spikes/S1): triangles are split, in order, into
# consecutive groups of at most 96 unique vertices and 128 triangles. Per meshlet:
#   vertex_count  = number of unique vertices its triangles use
#   vertex_offset = running sum of previous vertex_counts
#   tri_count     = triangles in the group
#   tri_offset    = running sum of round_up(3 * tri_count, 4)   (bytes of 3-byte local triangles)
# Cull data = the group's vertex bounding box as 6 floats: centre xyz, half-extent xyz (mesh space).

MESHLET_MAX_VERTS = 96
MESHLET_MAX_TRIS = 128


def split_into_meshlets(triangles, max_verts=MESHLET_MAX_VERTS, max_tris=MESHLET_MAX_TRIS):
    """Greedy in-order partition. Returns a list of (start_triangle, triangle_count)."""
    groups, start, verts = [], 0, set()
    for i, t in enumerate(triangles):
        new = verts | set(t)
        if i > start and (len(new) > max_verts or i - start >= max_tris):
            groups.append((start, i - start))
            start, new = i, set(t)
        verts = new
    if triangles:
        groups.append((start, len(triangles) - start))
    return groups


def meshlet_cull(group_triangles, positions, scale):
    verts = sorted({v for t in group_triangles for v in t})
    pts = [decode_position(positions[v], scale) for v in verts]
    lo = [min(p[a] for p in pts) for a in range(3)]
    hi = [max(p[a] for p in pts) for a in range(3)]
    return struct.pack("<6f", *[(lo[a] + hi[a]) / 2 for a in range(3)], *[(hi[a] - lo[a]) / 2 for a in range(3)])


def build_meshlets(m: SfMesh, groups=None):
    """Fill m.meshlets and m.cull_data from m.triangles / m.positions (call after the geometry is final)."""
    groups = groups if groups is not None else split_into_meshlets(m.triangles)
    m.meshlets, m.cull_data, vo, to = [], [], 0, 0
    for start, count in groups:
        tris = m.triangles[start:start + count]
        vc = len({v for t in tris for v in t})
        m.meshlets.append((vc, vo, count, to))
        m.cull_data.append(meshlet_cull(tris, m.positions, m.scale))
        vo += vc
        to += -(-(3 * count) // 4) * 4
    m.has_meshlet_section = True
    return m


# ---- value helpers -------------------------------------------------------------------------

def decode_position(raw, scale):
    return tuple(c / 32767.0 * scale for c in raw)


def encode_positions(points):
    """float (x,y,z) list -> (scale, raw int16 list). Scale is the largest absolute coordinate."""
    scale = max((abs(c) for p in points for c in p), default=0.0) or 1.0
    raw = [tuple(max(-32767, min(32767, round(c / scale * 32767.0))) for c in p) for p in points]
    return scale, raw


def decode_packed(u32):
    """10:10:10:2 -> (x, y, z, w) floats; xyz in -1..1, w in 0..1 (bitangent sign when used for tangents)."""
    x = (u32 & 0x3FF) / 1023.0 * 2.0 - 1.0
    y = ((u32 >> 10) & 0x3FF) / 1023.0 * 2.0 - 1.0
    z = ((u32 >> 20) & 0x3FF) / 1023.0 * 2.0 - 1.0
    w = (u32 >> 30) / 3.0
    return x, y, z, w


def encode_packed(x, y, z, w=0.0):
    def q(v):
        return max(0, min(1023, round((v + 1.0) * 0.5 * 1023.0)))
    return q(x) | (q(y) << 10) | (q(z) << 20) | (max(0, min(3, round(w * 3.0))) << 30)


def half_to_float(bits):
    return struct.unpack("<e", struct.pack("<H", bits))[0]


def float_to_half(v):
    return struct.unpack("<H", struct.pack("<e", v))[0]
