"""NIF container (Gamebryo 20.2.0.7 + Bethesda stream header) for Fallout 4 (BS 130) and Starfield (BS 175).

Splits a file into header fields, string table, opaque blocks (sized by the header) and a footer, and writes it
back byte-identically. Block *contents* are interpreted only where a converter needs them (see fo4_trishapes).
"""
import re
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

MAGIC = b"Gamebryo File Format, Version 20.2.0.7\n"
VERSION = 0x14020007


class NifError(ValueError):
    pass


@dataclass
class NifFile:
    endian: int = 1
    user_version: int = 12
    bs_version: int = 130
    author: bytes = b""
    unknown_int: int = 0                     # present when bs_version > 130
    process_script: bytes = b""              # present when bs_version < 131
    export_script: bytes = b""
    max_filepath: Optional[bytes] = None     # present for 103 <= bs_version < 170
    sf_data: bytes = b""                     # "Unknown Data" present for bs_version >= 170
    block_types: List[str] = field(default_factory=list)
    block_type_index: List[int] = field(default_factory=list)
    strings: List[bytes] = field(default_factory=list)
    max_string_len: int = 0
    groups: List[int] = field(default_factory=list)
    blocks: List[bytes] = field(default_factory=list)
    footer: bytes = b""

    def type_of(self, i):
        return self.block_types[self.block_type_index[i]]

    def add_block(self, type_name: str, data: bytes) -> int:
        if type_name not in self.block_types:
            self.block_types.append(type_name)
        self.block_type_index.append(self.block_types.index(type_name))
        self.blocks.append(data)
        return len(self.blocks) - 1

    def string_index(self, s: bytes) -> int:
        """Index of `s` in the string table (added if missing); -1 (0xFFFFFFFF) is 'no string'."""
        if s not in self.strings:
            self.strings.append(s)
            self.max_string_len = max(self.max_string_len, len(s))
        return self.strings.index(s)


def _short(d, p):
    n = d[p]
    return d[p + 1:p + 1 + n], p + 1 + n


def parse(data: bytes) -> NifFile:
    if not data.startswith(b"Gamebryo File Format"):
        raise NifError("not a NIF")
    nl = data.index(b"\n")
    if data[:nl + 1] != MAGIC:
        raise NifError(f"unsupported header line {data[:nl]!r}")
    p = nl + 1
    version, endian = struct.unpack_from("<IB", data, p)
    p += 5
    if version != VERSION:
        raise NifError(f"unsupported version {version:#x}")
    n = NifFile(endian=endian)
    n.user_version, nblocks, n.bs_version = struct.unpack_from("<III", data, p)
    p += 12
    n.author, p = _short(data, p)
    if n.bs_version > 130:
        n.unknown_int, = struct.unpack_from("<I", data, p)
        p += 4
    if n.bs_version < 131:
        n.process_script, p = _short(data, p)
    n.export_script, p = _short(data, p)
    if 103 <= n.bs_version < 170:
        n.max_filepath, p = _short(data, p)
    if n.bs_version >= 170:
        n.sf_data, p = _short(data, p)
    ntypes, = struct.unpack_from("<H", data, p)
    p += 2
    for _ in range(ntypes):
        ln, = struct.unpack_from("<I", data, p)
        p += 4
        n.block_types.append(data[p:p + ln].decode("ascii"))
        p += ln
    n.block_type_index = list(struct.unpack_from(f"<{nblocks}H", data, p))
    p += 2 * nblocks
    sizes = struct.unpack_from(f"<{nblocks}I", data, p)
    p += 4 * nblocks
    nstr, n.max_string_len = struct.unpack_from("<II", data, p)
    p += 8
    for _ in range(nstr):
        ln, = struct.unpack_from("<I", data, p)
        p += 4
        n.strings.append(data[p:p + ln])
        p += ln
    ngroups, = struct.unpack_from("<I", data, p)
    p += 4
    n.groups = list(struct.unpack_from(f"<{ngroups}I", data, p))
    p += 4 * ngroups
    for sz in sizes:
        n.blocks.append(data[p:p + sz])
        p += sz
    n.footer = data[p:]
    if sum(sizes) != sum(len(b) for b in n.blocks) or any(len(b) != s for b, s in zip(n.blocks, sizes)):
        raise NifError("block sizes run past end of file")
    return n


def serialize(n: NifFile) -> bytes:
    short = lambda b: bytes([len(b)]) + b  # noqa: E731
    out = [MAGIC, struct.pack("<IBIII", VERSION, n.endian, n.user_version, len(n.blocks), n.bs_version)]
    out.append(short(n.author))
    if n.bs_version > 130:
        out.append(struct.pack("<I", n.unknown_int))
    if n.bs_version < 131:
        out.append(short(n.process_script))
    out.append(short(n.export_script))
    if 103 <= n.bs_version < 170:
        out.append(short(n.max_filepath or b""))
    if n.bs_version >= 170:
        out.append(short(n.sf_data))
    out.append(struct.pack("<H", len(n.block_types)))
    for t in n.block_types:
        out.append(struct.pack("<I", len(t)) + t.encode("ascii"))
    out.append(struct.pack(f"<{len(n.blocks)}H", *n.block_type_index))
    out.append(struct.pack(f"<{len(n.blocks)}I", *[len(b) for b in n.blocks]))
    out.append(struct.pack("<II", len(n.strings), n.max_string_len))
    for s in n.strings:
        out.append(struct.pack("<I", len(s)) + s)
    out.append(struct.pack("<I", len(n.groups)) + struct.pack(f"<{len(n.groups)}I", *n.groups))
    out.extend(n.blocks)
    out.append(n.footer)
    return b"".join(out)


# ---- Fallout 4 geometry --------------------------------------------------------------------

VF_VERTEX, VF_UV, VF_UV2, VF_NORMAL, VF_TANGENT, VF_COLOR, VF_SKIN = 0x1, 0x2, 0x4, 0x8, 0x10, 0x20, 0x40
VF_FULL = 0x400


@dataclass
class Fo4Shape:
    name: bytes
    translation: tuple
    rotation: tuple          # 9 floats, row-major
    scale: float
    shader_ref: int
    alpha_ref: int
    skin_ref: int
    positions: list          # (x, y, z) floats
    uvs: list                # (u, v) floats
    normals: list            # (x, y, z) floats, may be empty
    tangents: list
    colors: list             # (r, g, b, a) bytes
    triangles: list          # (a, b, c)
    skinned: bool
    block: int = -1          # source block index


def _av_transform(blk: bytes):
    """(translation, row-major rotation, scale) of an NiAVObject block (BS >= 130 layout)."""
    _, nextra = struct.unpack_from("<iI", blk, 0)
    p = 8 + 4 * nextra + 8                         # extra refs, controller, flags
    tr = struct.unpack_from("<3f", blk, p)
    rot = struct.unpack_from("<9f", blk, p + 12)
    scale, = struct.unpack_from("<f", blk, p + 48)
    return tr, rot, scale


def node_children(n: NifFile, i: int) -> List[int]:
    """Child refs of an NiNode-derived block (FO4 layout: NiAVObject fields + collision ref, then the children array)."""
    blk = n.blocks[i]
    _, nextra = struct.unpack_from("<iI", blk, 0)
    p = 8 + 4 * nextra + 8 + 52 + 4
    count, = struct.unpack_from("<I", blk, p)
    if count > 100000 or p + 4 + 4 * count > len(blk):
        return []
    return [c for c in struct.unpack_from(f"<{count}i", blk, p + 4) if 0 <= c < len(n.blocks)]


def _compose(parent, local):
    """World transform of `local` under `parent`; both (t, R row-major 9-tuple, s) with v' = s*R*v + t."""
    (tp, rp, sp), (tl, rl, sl) = parent, local
    r = tuple(sum(rp[3 * a + k] * rl[3 * k + b] for k in range(3)) for a in range(3) for b in range(3))
    t = tuple(sp * sum(rp[3 * a + k] * tl[k] for k in range(3)) + tp[a] for a in range(3))
    return t, r, sp * sl


def world_transforms(n: NifFile):
    """block index -> world (t, R, s), composing every NiNode ancestor from the roots down (footer roots or parentless nodes)."""
    nodes = [i for i in range(len(n.blocks)) if n.type_of(i).endswith("Node") and n.type_of(i) != "BSFaceGenNiNode"]
    parent = {}
    for i in nodes:
        try:
            for c in node_children(n, i):
                parent.setdefault(c, i)
        except struct.error:
            pass
    cache = {}

    def world(i, depth=0):
        if i in cache:
            return cache[i]
        local = _av_transform(n.blocks[i])
        w = local if i not in parent or depth > 64 else _compose(world(parent[i], depth + 1), local)
        cache[i] = w
        return w
    return world


def fo4_trishapes(n: NifFile) -> List[Fo4Shape]:
    """Decode every BSTriShape / BSSubIndexTriShape block (vertex data and triangles only). The returned translation /
    rotation / scale are the shape's WORLD transform (all parent NiNodes composed), so geometry lands where FO4 draws it."""
    if n.bs_version != 130:
        raise NifError(f"fo4_trishapes needs BS 130, got {n.bs_version}")
    world = world_transforms(n)
    shapes = []
    for i, blk in enumerate(n.blocks):
        if n.type_of(i) not in ("BSTriShape", "BSSubIndexTriShape", "BSMeshLODTriShape"):
            continue
        p = 0
        name_idx, nextra = struct.unpack_from("<iI", blk, p)
        p += 8 + 4 * nextra
        p += 4  # controller
        p += 4  # flags
        tr = struct.unpack_from("<3f", blk, p); p += 12
        rot = struct.unpack_from("<9f", blk, p); p += 36
        scale, = struct.unpack_from("<f", blk, p); p += 4
        p += 4  # collision object
        p += 16  # bounding sphere
        skin, shader, alpha = struct.unpack_from("<iii", blk, p); p += 12
        desc, = struct.unpack_from("<Q", blk, p); p += 8
        ntri, nvert, dsize = struct.unpack_from("<IHI", blk, p); p += 10
        if dsize == 0:
            continue                                   # shape whose geometry is not stored in the block (e.g. destruction stubs)
        attrs = (desc >> 44) & 0xFFF
        vsize = (desc & 0xF) * 4
        if dsize != vsize * nvert + ntri * 6:
            raise NifError(f"block {i}: data size {dsize} != {vsize}*{nvert}+{ntri}*6")
        pos, uv, nor, tan, col = [], [], [], [], []
        for v in range(nvert):
            q = p + v * vsize
            if (attrs & 0x401) == 0x401:
                pos.append(struct.unpack_from("<3f", blk, q)); q += 16   # xyz + bitangent X / unused
            elif attrs & VF_VERTEX:
                pos.append(tuple(struct.unpack_from("<3e", blk, q))); q += 8
            if attrs & VF_UV:
                uv.append(tuple(struct.unpack_from("<2e", blk, q))); q += 4
            if attrs & VF_NORMAL:
                b = blk[q:q + 4]; q += 4
                nor.append(tuple(c / 255.0 * 2.0 - 1.0 for c in b[:3]))
                if attrs & VF_TANGENT:
                    b = blk[q:q + 4]; q += 4
                    tan.append(tuple(c / 255.0 * 2.0 - 1.0 for c in b[:3]))
            if attrs & VF_COLOR:
                col.append(tuple(blk[q:q + 4])); q += 4
        p += vsize * nvert
        tris = list(struct.iter_unpack("<HHH", blk[p:p + ntri * 6]))
        if n.type_of(i) == "BSMeshLODTriShape" and len(blk) >= p + ntri * 6 + 12:
            sizes = struct.unpack_from("<3I", blk, p + ntri * 6)
            if sum(sizes) == ntri and max(sizes) > 0:   # triangles hold all LOD levels back to back: keep the most detailed
                k = max(range(3), key=lambda j: sizes[j])
                start = sum(sizes[:k])
                tris = tris[start:start + sizes[k]]
        name = n.strings[name_idx] if 0 <= name_idx < len(n.strings) else b""
        tr, rot, scale = world(i)
        shapes.append(Fo4Shape(name, tr, rot, scale, shader, alpha, skin, pos, uv, nor, tan, col, tris,
                               bool(attrs & VF_SKIN), i))
    return shapes


def descendants(n: NifFile, i: int) -> set:
    """Block indices of node i and everything below it (children of NiNodes, recursively)."""
    out, todo = set(), [i]
    while todo:
        j = todo.pop()
        if j in out or not (0 <= j < len(n.blocks)):
            continue
        out.add(j)
        if n.type_of(j).endswith("Node"):
            todo += node_children(n, j)
    return out


def door_hinge(n: NifFile) -> Optional[Tuple[int, tuple]]:
    """(node index, world pivot) of the node an FO4 door's "Open" NiControllerSequence animates first, or None.
    Sequence layout: name, num controlled blocks, array grow by, then per block: interpolator, controller, priority (byte),
    node name (string index), property type, controller type, controller id, interpolator id."""
    for i in range(len(n.blocks)):
        if n.type_of(i) != "NiControllerSequence":
            continue
        blk = n.blocks[i]
        name_idx, count = struct.unpack_from("<iI", blk, 0)
        if count == 0 or n.strings[name_idx] != b"Open":
            continue
        target, = struct.unpack_from("<i", blk, 12 + 9)
        if not (0 <= target < len(n.strings)):
            return None
        world = world_transforms(n)
        for j in range(len(n.blocks)):
            if n.type_of(j) == "NiNode" and struct.unpack_from("<i", n.blocks[j], 0)[0] == target:
                return j, tuple(world(j)[0])     # only the pivot matters: the swing axis is vertical either way
        return None
    return None


def _last_rotation_key(d: bytes) -> Optional[tuple]:
    """Rotation at the last key of an NiTransformData block, as a row-major 3x3 matrix (None without rotation keys).
    Handles quaternion keys (linear / quadratic / TBC) and XYZ (Euler, per-axis float keys) rotation."""
    import math
    num, = struct.unpack_from("<I", d, 0)
    if num == 0:
        return None
    rtype, = struct.unpack_from("<I", d, 4)
    p = 8
    if rtype == 4:                                    # XYZ: three float key groups
        angles = []
        for _ in range(3):
            n, = struct.unpack_from("<I", d, p); p += 4
            if n == 0:
                angles.append(0.0)
                continue
            kt, = struct.unpack_from("<I", d, p); p += 4
            size = {1: 8, 2: 16, 3: 20}[kt]
            angles.append(struct.unpack_from("<f", d, p + (n - 1) * size + 4)[0])
            p += n * size
        x, y, z = angles
        cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
        rx = (1, 0, 0, 0, cx, -sx, 0, sx, cx)
        ry = (cy, 0, sy, 0, 1, 0, -sy, 0, cy)
        rz = (cz, -sz, 0, sz, cz, 0, 0, 0, 1)
        return _matmul(rz, _matmul(ry, rx))
    size = 20 + (12 if rtype == 3 else 0)             # time + quaternion (w, x, y, z) [+ TBC]
    _, w, x, y, z = struct.unpack_from("<5f", d, p + (num - 1) * size)
    return (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
            2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
            2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y))


def _matmul(a, b):
    return tuple(sum(a[3 * r + k] * b[3 * k + c] for k in range(3)) for r in range(3) for c in range(3))


def door_closed_rotation(n: NifFile, hinge_node: int) -> Optional[tuple]:
    """Local rotation of an FO4 door's hinge node at the end of its "Close" sequence (the closed pose; a door's rest pose
    in the NIF can be open). None if there is no usable Close sequence."""
    name_idx, = struct.unpack_from("<i", n.blocks[hinge_node], 0)
    for i in range(len(n.blocks)):
        if n.type_of(i) != "NiControllerSequence":
            continue
        blk = n.blocks[i]
        seq_name, count = struct.unpack_from("<iI", blk, 0)
        if n.strings[seq_name] != b"Close":
            continue
        for k in range(count):
            base = 12 + 29 * k
            interp, = struct.unpack_from("<i", blk, base)
            node, = struct.unpack_from("<i", blk, base + 9)
            if node != name_idx or not (0 <= interp < len(n.blocks)) or n.type_of(interp) != "NiTransformInterpolator":
                continue
            data, = struct.unpack_from("<i", n.blocks[interp], 32)
            if 0 <= data < len(n.blocks) and n.type_of(data) == "NiTransformData":
                return _last_rotation_key(n.blocks[data])
    return None


def referenced_paths(n: NifFile) -> List[str]:
    """Texture / material / mesh-like paths mentioned in the string table or block bytes (diagnostic only)."""
    pat = re.compile(rb"[A-Za-z0-9_\\/ .-]{4,160}\.(?:dds|bgsm|bgem|mat|mesh|hkx)", re.I)
    found = set()
    for s in n.strings:
        found.update(m.decode("latin-1") for m in pat.findall(s))
    for b in n.blocks:
        found.update(m.decode("latin-1") for m in pat.findall(b))
    return sorted(found)
