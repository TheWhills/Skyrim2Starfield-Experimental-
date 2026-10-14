"""Starfield (BS 173/175) NIF blocks we need to write, decoded from nif.xml and checked against vanilla files.

A minimal static prop is five blocks (see build_static_nif):
    0 NiNode            root, one child, extra data -> BSXFlags
    1 BSXFlags
    2 BSGeometry        bounds + `Meshes[0]` = path of an external .mesh (relative to Data/geometries, no extension)
    3 NiIntegerExtraData "MaterialID" = crc32_bethesda(lowercase material path)
    4 BSLightingShaderProperty   whose *name* is the .mat path
"""
import struct
import zlib
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import nif as nifmod

NIL = 0xFFFFFFFF


def material_id(path: str) -> int:
    """CRC32 (poly 0xEDB88320, init 0, no final xor) of the lowercase path, backslashes, latin-1.
    Verified against 60/60 vanilla NIFs."""
    return zlib.crc32(path.lower().replace("/", "\\").encode("latin-1"), 0xFFFFFFFF) ^ 0xFFFFFFFF


@dataclass
class MeshRef:
    indices_size: int
    num_verts: int
    flags: int
    path: bytes            # e.g. b"<20 hex>\\<20 hex>"


@dataclass
class BSGeometry:
    name_idx: int = 0
    extra_refs: List[int] = field(default_factory=list)
    controller: int = -1
    flags: int = 0xE
    translation: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: Tuple[float, ...] = (1, 0, 0, 0, 1, 0, 0, 0, 1)
    scale: float = 1.0
    collision: int = -1
    sphere: Tuple[float, float, float, float] = (0, 0, 0, 0)       # centre xyz, radius
    box: Tuple[float, ...] = (0, 0, 0, 0, 0, 0)                     # centre xyz, half-extent xyz
    skin: int = -1
    shader: int = -1
    alpha: int = -1
    meshes: List[Optional[MeshRef]] = field(default_factory=lambda: [None] * 4)


def parse_bsgeometry(b: bytes) -> BSGeometry:
    g = BSGeometry()
    g.name_idx, n = struct.unpack_from("<iI", b, 0)
    p = 8
    g.extra_refs = list(struct.unpack_from(f"<{n}i", b, p)); p += 4 * n
    g.controller, g.flags = struct.unpack_from("<iI", b, p); p += 8
    g.translation = struct.unpack_from("<3f", b, p); p += 12
    g.rotation = struct.unpack_from("<9f", b, p); p += 36
    g.scale, g.collision = struct.unpack_from("<fi", b, p); p += 8
    g.sphere = struct.unpack_from("<4f", b, p); p += 16
    g.box = struct.unpack_from("<6f", b, p); p += 24
    g.skin, g.shader, g.alpha = struct.unpack_from("<3i", b, p); p += 12
    g.meshes = []
    for _ in range(4):
        has = b[p]; p += 1
        if not has:
            g.meshes.append(None)
            continue
        isz, nv, fl = struct.unpack_from("<3I", b, p); p += 12
        if fl & 512:
            raise nifmod.NifError("embedded mesh data not supported")
        ln, = struct.unpack_from("<I", b, p); p += 4
        g.meshes.append(MeshRef(isz, nv, fl, b[p:p + ln])); p += ln
    if p != len(b):
        raise nifmod.NifError(f"BSGeometry: {len(b) - p} unparsed bytes")
    return g


def build_bsgeometry(g: BSGeometry) -> bytes:
    out = [struct.pack("<iI", g.name_idx, len(g.extra_refs)), struct.pack(f"<{len(g.extra_refs)}i", *g.extra_refs),
           struct.pack("<iI", g.controller, g.flags), struct.pack("<3f", *g.translation),
           struct.pack("<9f", *g.rotation), struct.pack("<fi", g.scale, g.collision),
           struct.pack("<4f", *g.sphere), struct.pack("<6f", *g.box),
           struct.pack("<3i", g.skin, g.shader, g.alpha)]
    for m in g.meshes:
        if m is None:
            out.append(b"\x00")
        else:
            out.append(b"\x01" + struct.pack("<3I", m.indices_size, m.num_verts, m.flags)
                       + struct.pack("<I", len(m.path)) + m.path)
    return b"".join(out)


def bounds_from_points(points):
    lo = [min(p[a] for p in points) for a in range(3)]
    hi = [max(p[a] for p in points) for a in range(3)]
    c = [(lo[a] + hi[a]) / 2 for a in range(3)]
    ext = [(hi[a] - lo[a]) / 2 for a in range(3)]
    radius = max(((p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2) ** 0.5 for p in points)
    return (*c, radius), (*c, *ext)


@dataclass
class StaticShape:
    name: bytes
    mesh_path: bytes        # b"<20 hex>\\<20 hex>"
    indices_size: int
    num_verts: int
    material_path: str
    sphere: tuple
    box: tuple


def build_static_nif(node_name: bytes, shapes: List[StaticShape], bs_version: int = 173,
                     collision_blob: Optional[bytes] = None,
                     child_collision_blobs: Optional[List[bytes]] = None) -> nifmod.NifFile:
    """A static prop NIF laid out like vanilla `setdressing` props: NiNode, BSXFlags, [bhkNPCollisionObject,
    bhkPhysicsSystem,] then per shape BSGeometry + NiIntegerExtraData("MaterialID") + BSLightingShaderProperty
    (named by its .mat path). The root node owns the collision object; BSXFlags is 2 when there is collision."""
    f = nifmod.NifFile(endian=1, user_version=12, bs_version=bs_version, author=b"\x00", unknown_int=0,
                       export_script=b"\x00", sf_data=b"\x7a\x00")
    s_node = f.string_index(node_name)
    s_bsx = f.string_index(b"BSX")
    s_matid = f.string_index(b"MaterialID")
    ident = struct.pack("<3f9ff", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1.0)
    first = 4 if collision_blob is not None else 2
    extra = list(child_collision_blobs or [])
    extra_start = first + 3 * len(shapes)          # each extra body: NiNode, bhkNPCollisionObject, bhkPhysicsSystem
    children = [first + 3 * i for i in range(len(shapes))] + [extra_start + 3 * j for j in range(len(extra))]
    coll_ref = 2 if collision_blob is not None else -1
    f.add_block("NiNode", struct.pack("<iIiiI", s_node, 1, 1, -1, 0xE) + ident
                + struct.pack("<iI", coll_ref, len(children)) + struct.pack(f"<{len(children)}i", *children))
    f.add_block("BSXFlags", struct.pack("<iI", s_bsx, 2 if (collision_blob is not None or extra) else 0))
    if collision_blob is not None:
        f.add_block("bhkNPCollisionObject", struct.pack("<iHiI", 0, 0x80, 3, 0))      # target = root node, data = block 3
        f.add_block("bhkPhysicsSystem", struct.pack("<I", len(collision_blob)) + collision_blob)
    for i, s in enumerate(shapes):
        base = first + 3 * i
        g = BSGeometry(name_idx=f.string_index(s.name), extra_refs=[base + 1], sphere=s.sphere, box=s.box,
                       shader=base + 2,
                       meshes=[MeshRef(s.indices_size, s.num_verts, 0x40, s.mesh_path), None, None, None])
        f.add_block("BSGeometry", build_bsgeometry(g))
        f.add_block("NiIntegerExtraData", struct.pack("<iI", s_matid, material_id(s.material_path)))
        f.add_block("BSLightingShaderProperty",
                    struct.pack("<iIi", f.string_index(s.material_path.encode("latin-1")), 0, -1))
    for j, entry in enumerate(extra):             # one collision body per child node
        # entry: blob (identity node) or (blob, translation xyz, rotation row-major 3x3) for bodies that FO4 attaches
        # to a transformed child node
        blob, xform = (entry, ident) if isinstance(entry, (bytes, bytearray)) else \
            (entry[0], struct.pack("<3f9ff", *entry[1], *entry[2], 1.0))
        node = extra_start + 3 * j
        f.add_block("NiNode", struct.pack("<iIiI", f.string_index(b"Collision%d" % j), 0, -1, 0xE) + xform
                    + struct.pack("<iI", node + 1, 0))
        f.add_block("bhkNPCollisionObject", struct.pack("<iHiI", node, 0x80, node + 2, 0))
        f.add_block("bhkPhysicsSystem", struct.pack("<I", len(blob)) + blob)
    f.footer = struct.pack("<II", 1, 0)
    return f


# Vanilla hinged door used as the animation template (DOOR 0AA24A AK_Ext_Bld_WallA_DoorA_01_Alt02). Its skeleton.rig stores
# the bind pose of these nodes, so a converted door must use the same node names and the same hinge position.
DOOR_TEMPLATE = {
    "nif": "meshes/architecture/city/akila/animated/doors/ak_ext_bld_walla_doora_01/ak_ext_bld_walla_doora_01.nif",
    "anim_graph": "AnimTextData\\Tables\\Graphs\\SimpleOpenClose01.agx",
    "skeleton": "architecture\\city\\akila\\animated\\doors\\ak_ext_bld_walla_doora_01\\characterassets\\skeleton.rig",
    "animations": "architecture\\city\\akila\\animated\\doors\\ak_ext_bld_walla_doora_01\\animations",
    "anim_root": b"AK_Door_Anim_02_Root",
    "hinge": b"Hinge01_Point",
    "hinge_pos": (-0.823, 1.698, 0.0),                       # metres, from skeleton.rig (and the vanilla NIF)
    "leaf": b"mesh001",                                       # node holding leaf geometry + body, as vanilla. rig: AK_Door_Anim_02_Root > Hinge01_Point > door > attach nodes
    "hinge_children": {b"REF_ATTACH_NODE": (1.123, 0.009, 1.069), b"LookAtNode": (1.117, -0.001, 1.024)},
}


def build_door_nif(node_name: bytes, static_shapes: List[StaticShape], moving_shapes: List[StaticShape],
                   template: dict = DOOR_TEMPLATE, bs_version: int = 173,
                   leaf_collision: Optional[bytes] = None,
                   frame_collision_blobs: Optional[List[bytes]] = None,
                   frame_collision_transforms: Optional[list] = None) -> nifmod.NifFile:
    """Door NIF laid out like the template door: root -> [frame node at the hinge position -> static shapes]
    and root -> anim root -> hinge (at the template's hinge position) -> moving shapes + attach nodes. All shape geometry is
    expected relative to the FO4 pivot, so both groups sit at the hinge position. Animated nodes carry NiStringExtraData
    "sgoKeep" like vanilla so they survive optimisation. leaf_collision (a bhkPhysicsSystem blob, hinge-local) goes on the
    node holding the moving shapes: activation ("Open") needs a body to hit.
    frame_collision_blobs are stationary bodies in the same pivot-local space,
    attached below Frame outside the animation tree. Caller must preserve openings.
    frame_collision_transforms optionally supplies (translation xyz, rotation
    row-major 3x3) per body in pivot-local space; blobs are then body-local."""
    frame_collision_blobs = list(frame_collision_blobs or [])
    import math
    identity = (1, 0, 0, 0, 1, 0, 0, 0, 1)
    transforms = list(frame_collision_transforms) if frame_collision_transforms is not None else [
        ((0.0, 0.0, 0.0), identity) for _ in frame_collision_blobs]
    if len(transforms) != len(frame_collision_blobs):
        raise ValueError("frame collision transform count must match body count")
    for translation, rotation in transforms:
        if len(translation) != 3 or len(rotation) != 9 or not all(math.isfinite(v) for v in (*translation, *rotation)):
            raise ValueError("frame collision transform must contain finite xyz and a 3x3 rotation")
        for i in range(3):
            for j in range(3):
                dot = sum(rotation[3 * i + k] * rotation[3 * j + k] for k in range(3))
                if abs(dot - (1 if i == j else 0)) > 1e-4:
                    raise ValueError("frame collision rotation must be orthonormal")
        a, b, c, d, e, g, h, j, k = rotation
        if abs(a * (e * k - g * j) - b * (d * k - g * h) + c * (d * j - e * h) - 1) > 1e-4:
            raise ValueError("frame collision rotation must preserve handedness")
    f = nifmod.NifFile(endian=1, user_version=12, bs_version=bs_version, author=b"\x00", unknown_int=0,
                       export_script=b"\x00", sf_data=b"\x7a\x00")
    s_matid = f.string_index(b"MaterialID")
    s_keep = f.string_index(b"sgoKeep")
    rot_scale = struct.pack("<9ff", 1, 0, 0, 0, 1, 0, 0, 0, 1, 1.0)

    node_rotations = {}

    def node(name: bytes, pos, keep: bool, coll: Optional[bytes] = None, rotation=None) -> int:
        i = f.add_block("NiNode", b"")                     # filled in by finish()
        extra = [f.add_block("NiStringExtraData", struct.pack("<ii", s_keep, s_keep))] if keep else []
        c = -1
        if coll is not None:
            c = f.add_block("bhkNPCollisionObject", struct.pack("<iHiI", i, 0x80, len(f.blocks) + 1, 0))
            f.add_block("bhkPhysicsSystem", struct.pack("<I", len(coll)) + coll)
        pending[i] = (f.string_index(name), extra, pos, [], c)
        if rotation is not None:
            node_rotations[i] = struct.pack("<9ff", *rotation, 1.0)
        return i

    def finish(i):
        name, extra, pos, kids, coll = pending[i]
        f.blocks[i] = (struct.pack("<iI", name, len(extra)) + struct.pack(f"<{len(extra)}i", *extra)
                       + struct.pack("<iI", -1, 0xE) + struct.pack("<3f", *pos) + node_rotations.get(i, rot_scale)
                       + struct.pack("<iI", coll, len(kids)) + struct.pack(f"<{len(kids)}i", *kids))

    def shape(s: StaticShape) -> int:
        base = len(f.blocks)
        g = BSGeometry(name_idx=f.string_index(s.name), extra_refs=[base + 1], sphere=s.sphere, box=s.box, shader=base + 2,
                       meshes=[MeshRef(s.indices_size, s.num_verts, 0x40, s.mesh_path), None, None, None])
        f.add_block("BSGeometry", build_bsgeometry(g))
        f.add_block("NiIntegerExtraData", struct.pack("<iI", s_matid, material_id(s.material_path)))
        f.add_block("BSLightingShaderProperty", struct.pack("<iIi", f.string_index(s.material_path.encode("latin-1")), 0, -1))
        return base

    pending = {}
    root = f.add_block("NiNode", b"")
    bsx = f.add_block("BSXFlags", struct.pack("<iI", f.string_index(b"BSX"), 0x0A if leaf_collision or frame_collision_blobs else 0))   # havok + complex, as vanilla doors (0x2A)
    pending[root] = (f.string_index(node_name), [bsx], (0.0, 0.0, 0.0), [], -1)
    hp = template["hinge_pos"]
    anim = node(template["anim_root"], (0.0, 0.0, 0.0), True)       # same order and nesting as the vanilla door
    pending[root][3].append(anim)
    if template.get("leaf"):
        hinge = node(template["hinge"], hp, True)
        pending[anim][3].append(hinge)
        leaf = node(template["leaf"], (0.0, 0.0, 0.0), True, leaf_collision)   # the bone the open/close animation rotates
        pending[hinge][3].append(leaf)
    else:                                         # geometry, collision and attach nodes directly on the hinge node
        hinge = leaf = node(template["hinge"], hp, True, leaf_collision)
        pending[anim][3].append(hinge)
    pending[leaf][3].extend(shape(s) for s in moving_shapes)
    for name, pos in template["hinge_children"].items():
        pending[leaf][3].append(node(name, pos, True))
    if static_shapes or frame_collision_blobs:
        frame = node(b"Frame", hp, False)
        pending[root][3].append(frame)
        pending[frame][3].extend(shape(s) for s in static_shapes)
        for i, blob in enumerate(frame_collision_blobs):
            translation, rotation = transforms[i]
            pending[frame][3].append(node(b"FrameCollision%d" % i, translation, False, blob, rotation))
    for i in pending:
        finish(i)
    f.footer = struct.pack("<II", 1, 0)
    return f
