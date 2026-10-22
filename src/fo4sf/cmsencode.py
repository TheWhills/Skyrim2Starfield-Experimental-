"""Build a Havok compressed mesh (hkcdStaticMeshTree, as in hknpCompressedMeshShapeData) from plain triangles.

Fallout 4 collision can be copied into Starfield as is (meshcollision.transplant); Skyrim's Havok 2010 collision cannot,
so Skyrim models need their decoded triangles (skyrimnif.collision_triangles) encoded from scratch. The output uses
FO4's array layout, which Starfield shares except for a few section fields (meshcollision._convert_section maps them),
so the existing Starfield emitter writes it.

Layout, measured on 34 FO4 compressed meshes (50 sections, 5,449 triangles; scripts in the 2026-10-22 docs entry):
* Domain: hkAabb of the whole mesh (min xyz w, max xyz w; w = 1.0). Header after it: numPrimitiveKeys i32 (one per
  triangle), bitsPerKey i32 (= maxKeyValue.bit_length()), maxKeyValue u32, 0.
* Shape key of a triangle: section << 8 | primitive << 1 | (1 for the second half of a quad).
* Sections (96 bytes, FO4 order): nodes hkArray, domain hkAabb @16, codec @48 (offset = domain min, scale = span /
  (2047, 2047, 1023)), firstPackedVertex u32 @72, sharedIndices (first << 8 | count) @76, primitives (first << 8 | count)
  @80, dataRuns (first << 8 | count) @84, numPacked u8 @88, numSharedIndices u8 @89, leafIndex u16 @90 (the section's
  leaf in the top tree), page / flags / layerData 0.
* Packed vertices u32: 11 / 11 / 10 bits over the section codec. Shared vertices u64: 21 / 21 / 22 bits over the mesh
  domain (used here for vertices several sections touch, so neighbouring sections meet without cracks).
* Primitives: 4 vertex slots (u8, section-local: packed first, then shared); a triangle repeats its third slot.
* Data runs (value u16, first u8, count u8) cover each section's primitives in order; value = material (0 here).
* AABB trees, depth first, full binary (2n - 1 nodes), each child box stored relative to its parent's DECODED box:
  per axis a byte (high nibble h, low nibble l), min = parent.min + h^2 * span / 226, max = parent.max - l^2 * span / 226.
  Section trees (4 bytes: xyz, data): data odd = internal, right child at k + (data - 1); data even = leaf, primitive
  data >> 1. Top tree (5 bytes: xyz, hi, lo): hi & 0x80 = internal, right child at k + 2 * ((hi & 0x7F) << 8 | lo); else
  leaf, section (hi << 8 | lo). So a section holds at most 127 primitives (MAX_PRIMS keeps a margin).
"""
import math
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

Vec = Tuple[float, float, float]
Box = Tuple[Vec, Vec]

MAX_PRIMS = 120          # per section (leaf data is 7 bits)
MAX_SLOTS = 250          # packed + shared vertex slots per section (u8 indices)
PACKED_LEVELS = (2047.0, 2047.0, 1023.0)
SHARED_LEVELS = (0x1FFFFF, 0x1FFFFF, 0x3FFFFF)
CODEC_DIV = 226.0


@dataclass
class Section:
    domain: Box
    codec: Tuple[Vec, Vec]                  # offset, scale
    nodes: bytes                            # 4-byte tree
    first_packed: int
    num_packed: int
    first_shared_index: int
    num_shared_index: int
    first_prim: int
    num_prims: int
    first_run: int
    num_runs: int
    leaf_index: int = 0

    def fo4_bytes(self) -> bytes:
        s = bytearray(96)
        s[16:48] = _aabb(self.domain)
        struct.pack_into("<6f", s, 48, *self.codec[0], *self.codec[1])
        struct.pack_into("<4I", s, 72, self.first_packed, self.first_shared_index << 8 | self.num_shared_index,
                         self.first_prim << 8 | self.num_prims, self.first_run << 8 | self.num_runs)
        s[88], s[89] = self.num_packed, self.num_shared_index
        struct.pack_into("<H", s, 90, self.leaf_index)
        return bytes(s)


@dataclass
class Encoded:
    domain: Box
    nodes: bytes                            # 5-byte top tree
    sections: List[Section]
    primitives: bytes
    shared_index: bytes
    packed: bytes
    shared: bytes
    runs: bytes
    keys: List[Tuple[int, Box]] = field(default_factory=list)

    @property
    def max_key(self) -> int:
        return max(k for k, _ in self.keys)

    def header(self) -> bytes:
        return struct.pack("<iiII", len(self.keys), self.max_key.bit_length(), self.max_key, 0)

    def domain_bytes(self) -> bytes:
        return _aabb(self.domain)

    def arrays(self) -> Dict[str, Tuple[bytes, int]]:
        """FO4-layout arrays by meshcollision's names (raw bytes, element count)."""
        return {"nodes": (self.nodes, len(self.nodes) // 5),
                "sections": (b"".join(s.fo4_bytes() for s in self.sections), len(self.sections)),
                "primitives": (self.primitives, len(self.primitives) // 4),
                "sharedVerticesIndex": (self.shared_index, len(self.shared_index) // 2),
                "packedVertices": (self.packed, len(self.packed) // 4),
                "sharedVertices": (self.shared, len(self.shared) // 8),
                "primitiveDataRuns": (self.runs, len(self.runs) // 4)}


def f32(x: float) -> float:
    """x as stored (float32): the game decodes from these values, so every decoded position and box uses them too."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _f32_step(x: float, up: bool) -> float:
    """The float32 next to x (x already a float32 value) towards +inf (up) or -inf."""
    bits, = struct.unpack("<i", struct.pack("<f", x))
    if x == 0.0:
        return struct.unpack("<f", struct.pack("<I", 1 if up else 0x80000001))[0]
    bits += 1 if (x > 0) == up else -1
    return struct.unpack("<f", struct.pack("<i", bits))[0]


def f32_down(x: float) -> float:
    y = f32(x)
    return y if y <= x else _f32_step(y, False)


def f32_up(x: float) -> float:
    y = f32(x)
    return y if y >= x else _f32_step(y, True)


def _f32box(box: Box) -> Box:
    """Box edges as float32, rounded outwards so the box still holds everything it held."""
    return (tuple(f32_down(v) for v in box[0]), tuple(f32_up(v) for v in box[1]))


PAD = 1e-6               # metres: leaf boxes grow by this before compression (float32 rounding in the game's decoding)


def _pad(box: Box) -> Box:
    return (tuple(v - PAD - abs(v) * 1e-6 for v in box[0]), tuple(v + PAD + abs(v) * 1e-6 for v in box[1]))


def _aabb(box: Box) -> bytes:
    return struct.pack("<8f", *box[0], 1.0, *box[1], 1.0)


def _bounds(pts: Sequence[Vec]) -> Box:
    return (tuple(min(p[a] for p in pts) for a in range(3)), tuple(max(p[a] for p in pts) for a in range(3)))


def _union(boxes: Sequence[Box]) -> Box:
    return (tuple(min(b[0][a] for b in boxes) for a in range(3)), tuple(max(b[1][a] for b in boxes) for a in range(3)))


def compress(parent: Box, child: Box) -> Tuple[bytes, Box]:
    """xyz codec bytes for `child` inside the (decoded) `parent`, and the box they decode to, which always contains the
    child (rounded outwards)."""
    out, lo, hi = bytearray(3), [0.0] * 3, [0.0] * 3
    for a in range(3):
        p0, p1 = parent[0][a], parent[1][a]
        span = p1 - p0
        h = l = 0
        if span > 0:
            h = min(15, int(math.sqrt(max(0.0, child[0][a] - p0) / span * CODEC_DIV)))
            while h > 0 and p0 + h * h * span / CODEC_DIV > child[0][a]:
                h -= 1
            l = min(15, int(math.sqrt(max(0.0, p1 - child[1][a]) / span * CODEC_DIV)))
            while l > 0 and p1 - l * l * span / CODEC_DIV < child[1][a]:
                l -= 1
        out[a] = h << 4 | l
        lo[a], hi[a] = p0 + h * h * span / CODEC_DIV, p1 - l * l * span / CODEC_DIV
    return bytes(out), (tuple(lo), tuple(hi))


def decompress(parent: Box, xyz: bytes) -> Box:
    lo, hi = [0.0] * 3, [0.0] * 3
    for a in range(3):
        span = parent[1][a] - parent[0][a]
        h, l = xyz[a] >> 4, xyz[a] & 15
        lo[a], hi[a] = parent[0][a] + h * h * span / CODEC_DIV, parent[1][a] - l * l * span / CODEC_DIV
    return tuple(lo), tuple(hi)


def _split(items: List[int], boxes: Sequence[Box]) -> Tuple[List[int], List[int]]:
    """Median split along the longest axis of the item centres."""
    b = _union([boxes[i] for i in items])
    ax = max(range(3), key=lambda a: b[1][a] - b[0][a])
    order = sorted(items, key=lambda i: boxes[i][0][ax] + boxes[i][1][ax])
    mid = len(order) // 2
    return order[:mid], order[mid:]


def build_tree(boxes: Sequence[Box], root: Box, node_bytes: int) -> Tuple[bytes, Dict[int, int]]:
    """Depth-first compressed AABB tree over `boxes` (leaf value = item index) inside `root`. Returns (nodes, leaf node
    index per item)."""
    nodes: List[Optional[bytes]] = []
    where: Dict[int, int] = {}

    def rec(items: List[int], parent: Box) -> None:
        k = len(nodes)
        nodes.append(None)
        xyz, dec = compress(parent, _pad(_union([boxes[i] for i in items])))
        if len(items) == 1:
            v = items[0]
            where[v] = k
            if node_bytes == 4:
                if v > 127:
                    raise ValueError("section tree leaf above 127")
                nodes[k] = xyz + bytes([v << 1])
            else:
                if v > 0x7FFF:
                    raise ValueError("top tree leaf above 32767")
                nodes[k] = xyz + bytes([v >> 8, v & 0xFF])
            return
        left, right = _split(items, boxes)
        rec(left, dec)
        off = len(nodes) - k                      # right child offset (even: left subtree is a full tree)
        if node_bytes == 4:
            if off > 254:
                raise ValueError("section tree too deep for 4-byte nodes")
            nodes[k] = xyz + bytes([off | 1])
        else:
            nodes[k] = xyz + bytes([0x80 | (off // 2) >> 8, (off // 2) & 0xFF])
        rec(right, dec)
    rec(list(range(len(boxes))), root)
    return b"".join(nodes), where


def _sections(points: Sequence[Vec], tris: List[Tuple[int, int, int]]) -> List[List[int]]:
    """Triangle index groups, split spatially until each fits a section (primitives and vertex slots)."""
    boxes = [_bounds([points[i] for i in t]) for t in tris]
    out, todo = [], [list(range(len(tris)))]
    while todo:
        g = todo.pop()
        verts = {v for i in g for v in tris[i]}
        if len(g) <= MAX_PRIMS and len(verts) <= MAX_SLOTS:
            out.append(g)
            continue
        a, b = _split(g, boxes)
        todo += [b, a]
    return out[::-1]


def _q(v: float, lo: float, span: float, levels: float) -> int:
    return 0 if span <= 0 else max(0, min(int(levels), int(round((v - lo) / span * levels))))


def encode(points: Sequence[Vec], triangles: Sequence[Tuple[int, int, int]], material: int = 0) -> Encoded:
    """Compressed mesh for the triangles (metres). Degenerate triangles are dropped; raises ValueError if none remain."""
    tris = [tuple(t) for t in triangles if len({t[0], t[1], t[2]}) == 3
            and len({tuple(points[i]) for i in t}) == 3]
    if not tris:
        raise ValueError("no triangles")
    used = sorted({v for t in tris for v in t})
    # the mesh box gets a margin (10 um + relative) above the sections' own float32 padding, so they all fit inside it
    raw = _bounds([points[i] for i in used])
    domain = _f32box((tuple(v - 1e-5 - abs(v) * 1e-5 for v in raw[0]), tuple(v + 1e-5 + abs(v) * 1e-5 for v in raw[1])))
    dspan = tuple(domain[1][a] - domain[0][a] for a in range(3))
    groups = _sections(points, tris)
    owners: Dict[int, set] = {}
    for s, g in enumerate(groups):
        for i in g:
            for v in tris[i]:
                owners.setdefault(v, set()).add(s)
    shared_ids = sorted(v for v, o in owners.items() if len(o) > 1)
    shared_slot = {v: k for k, v in enumerate(shared_ids)}
    shared_raw = bytearray()
    shared_dec: Dict[int, Vec] = {}
    for v in shared_ids:
        q = [_q(points[v][a], domain[0][a], dspan[a], SHARED_LEVELS[a]) for a in range(3)]
        shared_raw += struct.pack("<Q", q[0] | q[1] << 21 | q[2] << 42)
        shared_dec[v] = tuple(domain[0][a] + q[a] * (domain[1][a] - domain[0][a]) / SHARED_LEVELS[a] for a in range(3))
    sections, prims, sidx, packed, runs, keys, sec_boxes = [], bytearray(), bytearray(), bytearray(), bytearray(), [], []
    for s, g in enumerate(groups):
        verts = sorted({v for i in g for v in tris[i]})
        own = [v for v in verts if v not in shared_slot]
        shr = [v for v in verts if v in shared_slot]
        box = _f32box(_bounds([points[v] for v in own] + [shared_dec[v] for v in shr]))
        span = tuple(box[1][a] - box[0][a] for a in range(3))
        scale = tuple(f32(span[a] / PACKED_LEVELS[a]) if span[a] > 0 else 0.0 for a in range(3))
        slot, dec = {}, {}
        first_packed = len(packed) // 4
        for v in own:
            q = [0 if scale[a] == 0 else max(0, min(int(PACKED_LEVELS[a]), int(round((points[v][a] - box[0][a]) / scale[a]))))
                 for a in range(3)]
            packed += struct.pack("<I", q[0] | q[1] << 11 | q[2] << 22)
            slot[v] = len(slot)
            dec[v] = tuple(box[0][a] + q[a] * scale[a] for a in range(3))
        first_shared = len(sidx) // 2
        for v in shr:
            sidx += struct.pack("<H", shared_slot[v])
            slot[v] = len(slot)
            dec[v] = shared_dec[v]
        first_prim = len(prims) // 4
        pboxes = []
        for j, i in enumerate(g):
            a, b, c = tris[i]
            prims += bytes([slot[a], slot[b], slot[c], slot[c]])
            pb = _bounds([dec[a], dec[b], dec[c]])
            pboxes.append(pb)
            keys.append((s << 8 | j << 1, pb))
        # a section's box must hold its decoded vertices: packed ones can reach off + 2047 * scale (float32 scale)
        box = (box[0], tuple(max(box[1][a], f32_up(max(dec[v][a] for v in dec) + PAD)) for a in range(3)))
        nodes, _ = build_tree(pboxes, box, 4)
        first_run = len(runs) // 4
        runs += struct.pack("<HBB", material, 0, len(g))
        sections.append(Section(box, (box[0], scale), nodes, first_packed, len(own), first_shared, len(shr), first_prim,
                                len(g), first_run, 1))
        sec_boxes.append(box)
    top, where = build_tree(sec_boxes, domain, 5)
    for s, sec in enumerate(sections):
        sec.leaf_index = where[s]
    return Encoded(domain, top, sections, bytes(prims), bytes(sidx), bytes(packed), bytes(shared_raw), bytes(runs), keys)


# ---- reading back (tests and checks) ------------------------------------------------------------------------------
def walk(nodes: bytes, node_bytes: int, root: Box):
    """[(leaf value, decoded box)] of a compressed tree, checking its shape; raises ValueError if malformed."""
    n = len(nodes) // node_bytes
    out = []

    def rec(k, parent):
        if k >= n:
            raise ValueError(f"node {k} out of range ({n})")
        raw = nodes[node_bytes * k:node_bytes * (k + 1)]
        box = decompress(parent, raw[:3])
        if node_bytes == 4:
            internal, value = bool(raw[3] & 1), raw[3] >> 1
        else:
            internal, value = bool(raw[3] & 0x80), ((raw[3] & 0x7F) << 8) | raw[4]
        if not internal:
            out.append((value, box))
            return k + 1
        right = k + 2 * value
        if rec(k + 1, box) != right:
            raise ValueError(f"node {k}: right child {right} does not follow the left subtree")
        return rec(right, box)
    if rec(0, root) != n:
        raise ValueError("tree has unreachable nodes")
    return out


def decode(e: Encoded) -> List[Tuple[Vec, Vec, Vec]]:
    """Triangles as stored (quantised), section by section."""
    d0, d1 = e.domain
    span = tuple(d1[a] - d0[a] for a in range(3))
    shared = []
    for k in range(len(e.shared) // 8):
        v, = struct.unpack_from("<Q", e.shared, 8 * k)
        q = (v & 0x1FFFFF, (v >> 21) & 0x1FFFFF, v >> 42)
        shared.append(tuple(d0[a] + q[a] * span[a] / SHARED_LEVELS[a] for a in range(3)))
    out = []
    for s in e.sections:
        off, sc = s.codec
        verts = []
        for k in range(s.num_packed):
            v, = struct.unpack_from("<I", e.packed, 4 * (s.first_packed + k))
            q = (v & 0x7FF, (v >> 11) & 0x7FF, v >> 22)
            verts.append(tuple(off[a] + q[a] * sc[a] for a in range(3)))
        for k in range(s.num_shared_index):
            j, = struct.unpack_from("<H", e.shared_index, 2 * (s.first_shared_index + k))
            verts.append(shared[j])
        for k in range(s.num_prims):
            a, b, c, d = e.primitives[4 * (s.first_prim + k):4 * (s.first_prim + k) + 4]
            out.append((verts[a], verts[b], verts[c]))
            if c != d:
                out.append((verts[a], verts[c], verts[d]))
    return out


def check(e: Encoded, eps: float = 1e-5) -> List[str]:
    """Problems in an encoding: tree shape, every triangle inside its leaf box, every section inside its top leaf,
    leaf indices, slot and key limits."""
    problems = []
    tris = decode(e)
    try:
        top = dict(walk(e.nodes, 5, e.domain))
    except ValueError as x:
        return [f"top tree: {x}"]
    if sorted(top) != list(range(len(e.sections))):
        problems.append("top tree leaves are not the sections")
    k = 0
    for s_i, s in enumerate(e.sections):
        if s.num_packed + s.num_shared_index > 255 or s.num_prims > 127:
            problems.append(f"section {s_i} over its limits")
        if s_i in top and any(top[s_i][0][a] > s.domain[0][a] + eps or top[s_i][1][a] < s.domain[1][a] - eps
                              for a in range(3)):
            problems.append(f"section {s_i} outside its top-tree leaf")
        try:
            leaves = dict(walk(s.nodes, 4, s.domain))
        except ValueError as x:
            problems.append(f"section {s_i} tree: {x}")
            continue
        if sorted(leaves) != list(range(s.num_prims)):
            problems.append(f"section {s_i}: leaves are not its primitives")
        for j in range(s.num_prims):
            t = tris[k]
            k += 1
            b = leaves.get(j)
            if b and any(min(p[a] for p in t) < b[0][a] - eps or max(p[a] for p in t) > b[1][a] + eps for a in range(3)):
                problems.append(f"section {s_i} primitive {j} outside its leaf box")
        n_top = len(e.nodes) // 5
        if not 0 <= s.leaf_index < n_top or e.nodes[5 * s.leaf_index + 3] & 0x80:
            problems.append(f"section {s_i}: leaf index {s.leaf_index} is not a leaf")
    return problems


# ---- FO4 packfile view ----------------------------------------------------------------------------------------------
# meshcollision._emit_mesh (verified in game with FO4 data) and fo4collision's decoder read a FO4 hknpCompressedMesh-
# ShapeData through Packfile.raw / unpack / array / pointer. Fo4View lays an Encoded out the same way in memory, so the
# unchanged writer and decoder run on it: the data object at 0 (tree at +16: nodes hkArray, domain @32, header @64,
# arrays at FO4's offsets), then the arrays, then each section's node array.
FO4_DATA_SIZE = 176
FO4_ARRAY_OFFSETS = {"nodes": 16, "sections": 80, "primitives": 96, "sharedVerticesIndex": 112, "packedVertices": 128,
                     "sharedVertices": 144, "primitiveDataRuns": 160}


class Fo4View:
    def __init__(self, e: "Encoded"):
        mem = bytearray(FO4_DATA_SIZE)
        mem[32:64] = e.domain_bytes()
        mem[64:80] = e.header()
        self._arrays: Dict[int, Tuple[int, int]] = {}

        def put(raw: bytes, n: int) -> int:
            nonlocal mem
            at = (len(mem) + 15) & ~15
            mem += bytes(at - len(mem)) + raw
            return at
        sec_at = None
        for name, (raw, n) in e.arrays().items():
            at = put(raw, n) if n else 0
            self._arrays[FO4_ARRAY_OFFSETS[name]] = (at if n else None, n)
            if name == "sections":
                sec_at = at
        for k, s in enumerate(e.sections):
            n = len(s.nodes) // 4
            self._arrays[sec_at + 96 * k] = (put(s.nodes, n), n)
        self.mem = bytes(mem)

    def raw(self, off: int, n: int) -> bytes:
        return self.mem[off:off + n]

    def unpack(self, fmt: str, off: int):
        return struct.unpack_from(fmt, self.mem, off)

    def array(self, off: int) -> Tuple[Optional[int], int]:
        return self._arrays.get(off, (None, 0))

    def pointer(self, off: int) -> Optional[int]:
        return self._arrays.get(off, (None, 0))[0]
