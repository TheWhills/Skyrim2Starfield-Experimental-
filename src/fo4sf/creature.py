"""Skyrim creatures on their own skeletons, for Starfield (docs/npc/creatures.md). Pure functions; the build script
(scripts/npc/creature_build.py) reads the games and writes the files.

What a Starfield creature is made of (verified on CritterRace, owner's probes 2026-11-17): a thin skeleton.nif
(<Name>_mrRigRoot > Root > COM, plus CharacterController under the root; a sphere body on COM, a capsule on the
controller; no bones) and a .rig holding the bones, the first being COM. So the Skyrim skeleton becomes a rig:
* the Skyrim root (NPC Root [Root]) is folded into its child, the centre-of-mass bone (the chicken's Pelvis), which is
  renamed COM so that it is the bone the shell's COM node carries (supported: the critter's rig starts at COM and its
  skeleton.nif has a COM node; the engine joining them by name is the hypothesis the test checks);
* every other bone keeps its Skyrim name and its local rest; translations go to metres (retarget.SKYRIM_M_PER_UNIT).
Clips follow the same fold, so a clip's COM track is root * pelvis on every frame (no root-motion split yet: the
first test plays locomotion in place, unresolved where Starfield's creature clips keep root motion).
The mesh is skinned with binds = the inverse of each bone's bind world from the Skyrim mesh (the convention of the
game's own hairs, skyrimhair.nif_files), so it is drawn as Skyrim draws it; unlike worn gear, a creature body carries
its own bone nodes (build_body_nif).
"""
import math
import re
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import nif as nifmod
from .retarget import Rig, SKYRIM_M_PER_UNIT, qmul, qrot

COM = "COM"


ROOT = "Root"
IDENTITY_Q = np.array([0.0, 0.0, 0.0, 1.0])


@dataclass
class CreatureRig:
    names: List[str]
    parents: List[int]
    t: np.ndarray            # (B, 3) metres, local rest
    q: np.ndarray            # (B, 4) x y z w
    sources: List[int]       # index of each bone in the Skyrim skeleton (-1: Root, which Skyrim has no bone for)
    root: int                # the folded Skyrim root (index in the Skyrim skeleton), -1 if none
    com: int                 # the Skyrim bone that became COM
    level: np.ndarray = None # COM's Skyrim rest rotation, moved into COM's children (COM rests unrotated)

    @property
    def com_index(self) -> int:
        return self.names.index(COM)

    def fold(self, lt, lq, unit: float = SKYRIM_M_PER_UNIT):
        """Skyrim locals (..., Bs, 3) / (..., Bs, 4) in Havok units -> this rig's locals in metres: Root (if any) at
        rest (root motion is added by the caller), the Skyrim root folded into COM, and COM levelled (self.level
        taken out of COM and put into its children: every bone's world transform is unchanged)."""
        lt, lq = np.asarray(lt, float), np.asarray(lq, float)
        lead = lt.shape[:-2]
        B = len(self.names)
        t = np.zeros(lead + (B, 3))
        q = np.zeros(lead + (B, 4))
        q[..., 3] = 1.0
        mine = [i for i, src in enumerate(self.sources) if src >= 0]
        srcs = [self.sources[i] for i in mine]
        t[..., mine, :] = lt[..., srcs, :] * unit
        q[..., mine, :] = lq[..., srcs, :]
        k = self.com_index
        if self.root >= 0:
            rq, rt = lq[..., self.root, :], lt[..., self.root, :] * unit
            q[..., k, :] = qmul(rq, lq[..., self.com, :])
            t[..., k, :] = rt + qrot(rq, lt[..., self.com, :] * unit)
        if self.level is not None:
            lv = np.broadcast_to(self.level, q[..., k, :].shape)
            q[..., k, :] = qmul(q[..., k, :], lv * np.array([-1.0, -1.0, -1.0, 1.0]))
            for c, p in enumerate(self.parents):
                if p == k:
                    t[..., c, :] = qrot(lv, t[..., c, :])
                    q[..., c, :] = qmul(lv, q[..., c, :])
        return t, q

    def rig(self) -> Rig:
        return Rig(self.names, self.parents, self.t, self.q)

    def reordered(self, order: Sequence[int]) -> "CreatureRig":
        """The same rig with its bones in `order` (old indices; every parent must come before its children)."""
        order = list(order)
        if sorted(order) != list(range(len(self.names))):
            raise ValueError("order is not a permutation of the bones")
        new = {old: i for i, old in enumerate(order)}
        parents = [new[self.parents[o]] if self.parents[o] >= 0 else -1 for o in order]
        if any(p >= i for i, p in enumerate(parents)):
            raise ValueError("a parent would follow its child")
        return CreatureRig([self.names[o] for o in order], parents, np.asarray(self.t)[order],
                           np.asarray(self.q)[order], [self.sources[o] for o in order], self.root, self.com, self.level)


def creature_rig(sk: Rig, com: str = "Pelvis", root: Optional[str] = None,
                 unit: float = SKYRIM_M_PER_UNIT, add_root: bool = True, level_com: bool = True) -> CreatureRig:
    """The Starfield rig of a Skyrim creature skeleton (Havok units): `root` (default the skeleton's root when it is
    the COM bone's parent) folded into `com`, which is renamed COM; with add_root a Root bone at the origin above it
    (the shell's Root > COM; the critter's moving clips key Root, owner's motion probe 2026-11-17); with level_com
    COM rests unrotated, as the critter's does (its clips hold COM level), its Skyrim rest rotation moved into its
    children (owner, 2026-11-17 14:29 / 14:38: with the chicken's Pelvis pitch (-56 deg about x) on COM the birds
    stood tilted back, legs pedalling in front). Other bones keep names and hierarchy; bones outside COM's subtree
    (none on the chicken) are dropped."""
    if com not in sk.index:
        raise ValueError(f"no bone {com!r}")
    ci = sk.index[com]
    ri = sk.parents[ci] if root is None else sk.index.get(root, -1)
    if root is not None and ri < 0:
        raise ValueError(f"no bone {root!r}")
    if ri >= 0 and sk.parents[ci] != ri:
        raise ValueError(f"{root!r} is not the parent of {com!r}")
    keep = []
    for i in range(len(sk.names)):                       # parents precede children (Rig): one pass finds the subtree
        if i == ci or (sk.parents[i] >= 0 and sk.parents[i] in keep):
            keep.append(i)
    lead = 1 if add_root else 0
    pos = {s: k + lead for k, s in enumerate(keep)}
    names = ([ROOT] if add_root else []) + [COM if i == ci else sk.names[i] for i in keep]
    parents = ([-1] if add_root else []) + [(0 if add_root else -1) if i == ci else pos[sk.parents[i]] for i in keep]
    sources = ([-1] if add_root else []) + keep
    cr = CreatureRig(names, parents, np.zeros((len(names), 3)), np.zeros((len(names), 4)), sources, ri, ci)
    cr.t, cr.q = cr.fold(sk.t, sk.q, unit)
    if level_com:
        lv = cr.q[cr.com_index].copy()
        cr.level = lv / (np.linalg.norm(lv) or 1.0)
        cr.t, cr.q = cr.fold(sk.t, sk.q, unit)
    return cr


def clip_locals(clip: dict, sk: Rig, cr: CreatureRig, unit: float = SKYRIM_M_PER_UNIT):
    """(F, B, 3) metres / (F, B, 4): a decoded Skyrim clip (skyrimhkx.decode_clip) on the creature rig; bones the
    clip leaves out keep their rest."""
    from .retarget import skyrim_locals
    lt, lq = skyrim_locals(clip, sk)
    return cr.fold(lt, lq, unit)


def bone_name_map(mesh_bones, rig_names, com_source: str) -> Dict[str, str]:
    """{mesh bone: rig bone}: the same name ignoring case (Skyrim's mesh says HEAD where its skeleton says Head), the
    COM source bone to COM. Raises on a mesh bone the rig lacks."""
    low = {n.lower(): n for n in rig_names}
    out = {}
    for b in mesh_bones:
        if b.lower() == com_source.lower():
            out[b] = COM
        elif b.lower() in low:
            out[b] = low[b.lower()]
        else:
            raise ValueError(f"mesh bone {b!r} is not in the rig")
    return out


def quantize_weights(weights, index: Dict[str, int], k: int = 4) -> List[Tuple[int, int]]:
    """Per-vertex [(rig bone name, weight)] -> k (bone index, u16 weight) pairs per vertex, heaviest first, summing to
    65535 (sfmesh's layout, as skyrimhair._mesh)."""
    out = []
    for vw in weights:
        vw = sorted(vw, key=lambda bw: -bw[1])[:k]
        s = sum(w for _b, w in vw) or 1.0
        q = [(index[b], int(round(w / s * 65535))) for b, w in vw]
        if q:
            q[0] = (q[0][0], q[0][1] + 65535 - sum(w for _b, w in q))
        q += [(0, 0)] * (k - len(q))
        out += q
    return out


COM_NODE = "COM_Twin"     # the vanilla trilobite body's name for its COM node (owner's model compare, 2026-11-17)


def quat_to_rot9(q) -> Tuple[float, ...]:
    """Row-major 3x3 (v' = R v, the NIF convention of nif._compose) of a quaternion (x, y, z, w)."""
    x, y, z, w = (float(v) for v in q)
    n = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
            2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
            2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y))


BODY_BSX = 0x1004A        # the vanilla trilobite body's BSXFlags (owner's model compare 2, 2026-11-17)


BODY_LODS = 4             # the vanilla trilobite body fills LOD0-3 (owner's model compare 2026-11-17)


def build_body_nif(root_name: bytes, shape, cr: CreatureRig, bones: List[str], bsx_flags: int = BODY_BSX,
                   lods: int = BODY_LODS, ragdoll=None) -> nifmod.NifFile:
    """A creature body NIF laid out like the vanilla trilobite's (verified layout, owner's model compare 2026-11-17):
    the model carries its own bone nodes (root > COM_Twin > the rig's hierarchy at rest, each with NiStringExtraData
    'sgoKeep'), the skin's BSSkin::Instance points at those nodes (skeleton root = the root node), and its SkinAttach
    names are empty. Worn gear (sfnif.build_skinned_nif: names only, no nodes) drew nothing on a creature (owner,
    2026-11-17 14:02: heard, not seen). As vanilla (model compare 2): COM_Twin sits at the model's origin and carries
    NiStringExtraData ParentBoneName = COM instead of sgoKeep, i.e. the body hangs off the skeleton's COM bone and
    the model is in COM's space (skinned_files moves the mesh there); its children carry the rig's local rest.
    `shape` is an sfnif.SkinnedShape whose bones / binds are in `bones` order. lods: how many of the four LOD slots
    the mesh fills (vanilla: all four, each skinned; with only LOD0 the chicken slid with still legs a few feet away,
    owner 2026-11-17 17:52 / 18:12, after the rig LOD fix: supported, the engine drew an empty lower LOD unskinned).
    ragdoll: (Havok tagfile of an hknpRagdollData, [rig bone of body 0, body 1, ...]) adds, as the vanilla trilobite
    body, one bhkRagdollSystem block (u32 size + tagfile) and per body a bhkNPCollisionObject (target node, flags 0x80,
    system block, body index) on that bone's node (COM's body on COM_Twin) (creature_ragdoll)."""
    from . import sfnif
    f = nifmod.NifFile(endian=1, user_version=12, bs_version=173, author=b"\x00", unknown_int=0,
                       export_script=b"\x00", sf_data=b"\x7a\x00")
    s_keep = f.string_index(b"sgoKeep")
    root = f.add_block("NiNode", b"")
    bsx = f.add_block("BSXFlags", struct.pack("<iI", f.string_index(b"BSX"), bsx_flags))
    node_of, kids = {}, {root: []}
    for i, name in enumerate(cr.names):
        if name == ROOT:                                 # the body hangs off COM: no Root node in it (vanilla)
            continue
        b = f.add_block("NiNode", b"")
        if name == COM:
            e = f.add_block("NiStringExtraData", struct.pack("<ii", f.string_index(b"ParentBoneName"),
                                                             f.string_index(name.encode("latin-1"))))
        else:
            e = f.add_block("NiStringExtraData", struct.pack("<ii", s_keep, s_keep))
        node_of[i] = (b, e)
        kids[b] = []
        p = cr.parents[i]
        kids[root if name == COM or p < 0 or cr.names[p] == ROOT else node_of[p][0]].append(b)
    base = len(f.blocks)
    nb = len(bones)
    g = sfnif.BSGeometry(name_idx=f.string_index(shape.name), extra_refs=[base + 2, base + 3], sphere=(0.0, 0.0, 0.0, 0.0),
                         box=(sfnif.FLT_MAX,) * 6, skin=base + 4, shader=base + 1,
                         meshes=[sfnif.MeshRef(shape.indices_size, shape.num_verts, 0x40, shape.mesh_path)] * lods
                         + [None] * (4 - lods))
    f.add_block("BSGeometry", sfnif.build_bsgeometry(g))
    kids[root].append(base)
    f.add_block("BSLightingShaderProperty", struct.pack("<iIi", f.string_index(shape.material_path.encode("latin-1")), 0, -1))
    f.add_block("NiIntegerExtraData", struct.pack("<iI", f.string_index(b"MaterialID"), sfnif.material_id(shape.material_path)))
    f.add_block("SkinAttach", struct.pack("<iI", f.string_index(b"SkinBMP"), nb) + struct.pack("<I", 0) * nb)
    refs = [node_of[cr.names.index(b)][0] for b in bones]
    f.add_block("BSSkin::Instance", struct.pack("<iiI", root, base + 5, nb) + struct.pack(f"<{nb}i", *refs)
                + struct.pack("<I", 0))
    f.add_block("BSSkin::BoneData", struct.pack("<I", nb) + b"".join(
        struct.pack("<4f9f3ff", *sphere, *rot, *trans, scale) for sphere, rot, trans, scale in shape.binds))
    ident = struct.pack("<3f9ff", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1.0)
    collision = {}
    if ragdoll is not None:
        blob, body_bones = ragdoll
        system = f.add_block("bhkRagdollSystem", struct.pack("<I", len(blob)) + blob)
        for k, bone in enumerate(body_bones):
            if bone == ROOT or bone not in cr.names:
                raise ValueError(f"ragdoll body {k}: no node for bone {bone!r}")
            nb_ = node_of[cr.names.index(bone)][0]
            collision[nb_] = f.add_block("bhkNPCollisionObject", struct.pack("<iHiI", nb_, 0x80, system, k))

    def node(name_idx, extra, xform, children, coll=-1):
        return (struct.pack("<iI", name_idx, len(extra)) + struct.pack(f"<{len(extra)}i", *extra)
                + struct.pack("<iI", -1, 0xE) + xform + struct.pack("<iI", coll, len(children))
                + struct.pack(f"<{len(children)}i", *children))
    f.blocks[root] = node(f.string_index(root_name), [bsx], ident, kids[root])
    for i, name in enumerate(cr.names):
        if name == ROOT:
            continue
        b, e = node_of[i]
        if name == COM:                                  # COM_Twin: the model's origin is COM itself
            xform = ident
        else:
            xform = struct.pack("<3f", *map(float, cr.t[i])) + struct.pack("<9ff", *quat_to_rot9(cr.q[i]), 1.0)
        nm = COM_NODE if name == COM else name
        f.blocks[b] = node(f.string_index(nm.encode("latin-1")), [e], xform, kids[b], collision.get(b, -1))
    f.footer = struct.pack("<II", 1, 0)
    return f


def rest_worlds(cr: CreatureRig) -> Dict[str, np.ndarray]:
    """{bone: 4x4 rest world (metres, the actor's model space)} of the rig."""
    wt, wq = cr.rig().rest_world()
    out = {}
    for i, n in enumerate(cr.names):
        m = np.eye(4)
        m[:3, :3] = np.array(quat_to_rot9(wq[i])).reshape(3, 3)
        m[:3, 3] = wt[i]
        out[n] = m
    return out


def com_world(cr: CreatureRig) -> np.ndarray:
    """4x4 rest world of COM, metres."""
    wt, wq = cr.rig().rest_world()
    k = cr.com_index
    m = np.eye(4)
    m[:3, :3] = np.array(quat_to_rot9(wq[k])).reshape(3, 3)
    m[:3, 3] = wt[k]
    return m


def to_com_space(shape, cr: CreatureRig, tangents=None):
    """(shape, tangents) moved from the actor's model space into COM's (vertices, normals, tangents, bind worlds),
    the space of a vanilla creature body (build_body_nif)."""
    import dataclasses
    inv = np.linalg.inv(com_world(cr))
    R, T = inv[:3, :3], inv[:3, 3]
    pts = np.asarray(shape.points, float) @ R.T + T
    nrm = np.asarray(shape.normals, float) @ R.T if len(shape.normals) else shape.normals
    joints = {b: inv @ w for b, w in shape.joints.items()}
    tan = None if tangents is None else [tuple(np.asarray(t, float) @ R.T) for t in tangents]
    return dataclasses.replace(shape, points=pts, normals=nrm, joints=joints), tan


def with_back_faces(shape, tangents=None):
    """(shape, tangents) with a mirrored copy of every triangle (reversed winding, normals negated, the same UVs,
    weights and tangents): a Skyrim surface drawn double-sided (SLSF2_Double_Sided) as one-sided Starfield geometry,
    as skyrimconvert.with_back_faces does for statics. Owner, 2026-11-17 17:35: the converted chickens walk right but
    look "almost missing a piece or underbelly" (supported: their inward-facing faces culled)."""
    import dataclasses
    nv = len(shape.points)
    if 2 * nv > 0xFFFF:
        raise ValueError(f"{nv} vertices: doubled they exceed u16 indices")
    pts = np.concatenate([np.asarray(shape.points, float)] * 2)
    nrm = np.asarray(shape.normals, float)
    nrm = np.concatenate([nrm, -nrm]) if len(nrm) else nrm
    tris = [tuple(t) for t in shape.triangles] + [(a + nv, c + nv, b + nv) for a, b, c in shape.triangles]
    out = dataclasses.replace(shape, points=pts, normals=nrm, uvs=list(shape.uvs) * 2, triangles=tris,
                              weights=list(shape.weights) * 2)
    return out, (list(tangents) * 2 if tangents is not None else None)


def skinned_files(shape, material_path: str, out_name: str, com_source: str, cr: CreatureRig,
                  tangents=None, bsx_flags: int = BODY_BSX, lods: int = BODY_LODS, ragdoll=None) -> Dict[str, bytes]:
    """{"meshes/<out_name>.nif", "geometries/<a>/<b>.mesh"}: a gearfit.SkyShape (metres, the actor's model space,
    bind worlds per bone) as a creature body (build_body_nif, in COM's space) skinned to the creature rig's bones.
    tangents: per-vertex model-space tangents (the Skyrim mesh's, turned like its normals), else none are written."""
    from . import convert_static, sfmesh, sfnif
    shape, tangents = to_com_space(shape, cr, tangents)
    rig_names = cr.names
    names = bone_name_map(shape.bones, rig_names, com_source)
    used = sorted({names[shape.bones[b]] for vw in shape.weights for b, _w in vw}, key=lambda n: (n != COM, n))
    index = {n: i for i, n in enumerate(used)}
    pts = [tuple(map(float, p)) for p in shape.points]
    fo4 = nifmod.Fo4Shape(shape.name, (0.0, 0.0, 0.0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0, -1, -1, -1, pts,
                          list(shape.uvs), [tuple(map(float, n)) for n in shape.normals],
                          [tuple(map(float, t)) for t in tangents] if tangents is not None else [], [],
                          list(shape.triangles), True)
    m = convert_static.shape_to_mesh(fo4, 1.0)
    m.weights_per_vertex = 4
    m.weights = quantize_weights([[(names[shape.bones[b]], w) for b, w in vw] for vw in shape.weights], index)
    data = sfmesh.serialize(m)
    d, f = convert_static.mesh_file_path(data)
    # Binds from the RIG's rest pose (in COM's space), not the Skyrim mesh's bind worlds: the engine draws a vertex at
    # bone_world * bind * v, so at rest bone_world must cancel the bind. With COM levelled (fix 4) the mesh's Pelvis
    # bind (pitched -56 deg) no longer matches COM's rest (level): every vertex weighted to COM (belly, lower breast)
    # was swung 56 deg up into the body at rest (owner, 2026-11-17 17:35-17:46: "missing a piece or underbelly",
    # unchanged by --opaque). Every other bone's mesh bind equals the rig's within 0.1 deg (creature_build.json).
    joints = {names[b]: w for b, w in shape.joints.items() if b in names}
    rest = rest_worlds(cr)
    to_com = np.linalg.inv(com_world(cr))
    joints.update({b: to_com @ rest[b] for b in rest if b in joints or b == COM})
    binds = []
    P = np.asarray(shape.points, float)
    for b in used:
        if b not in joints:
            raise ValueError(f"bone {b} has no bind")
        inv = np.linalg.inv(joints[b])
        sel = [k for k, vw in enumerate(shape.weights) if any(names[shape.bones[x]] == b for x, _w in vw)]
        loc = P[sel] @ inv[:3, :3].T + inv[:3, 3]
        c = (loc.min(0) + loc.max(0)) / 2
        r = float(np.linalg.norm(loc - c, axis=1).max())
        binds.append((tuple(map(float, c)) + (r,), tuple(map(float, inv[:3, :3].reshape(9))),
                      tuple(map(float, inv[:3, 3])), 1.0))
    sh = sfnif.SkinnedShape(shape.name or b"Body", f"{d}\\{f}".encode(), len(m.triangles) * 3, len(m.positions),
                            material_path, [b.encode("latin-1") for b in used], binds)
    n = build_body_nif(b"ExportScene", sh, cr, used, bsx_flags, lods, ragdoll)
    return {f"geometries/{d}/{f}.mesh": data, f"meshes/{out_name}.nif": nifmod.serialize(n)}


NODE_TYPES = ("NiNode", "BSFadeNode")


def _node_name(n, i) -> bytes:
    idx = struct.unpack_from("<i", n.blocks[i], 0)[0]
    return n.strings[idx] if 0 <= idx < len(n.strings) else b""


def shell_skeleton(data: bytes, root_name: str, com_t, com_q=None) -> bytes:
    """A copy of a vanilla creature skeleton.nif shell (the critter's) for another creature: the root node renamed
    (Critter_mrRigRoot -> <root_name>) and the COM node moved to com_t (metres, its local translation under Root) and,
    with com_q (x, y, z, w), turned to the creature's own COM rest rotation. Without com_q the critter's COM rotation
    stayed (owner, 2026-11-17 14:29: chickens drawn but tilted back, legs pedalling forward: supported, the engine
    places COM by the shell's node, so the rig's rest rotation must be there too).
    The physics (a sphere on COM, the controller capsule) is kept as it is: critter-sized (unresolved: resizing)."""
    n = nifmod.parse(data)
    nodes = [i for i in range(len(n.blocks)) if n.type_of(i) in NODE_TYPES]
    children = {c for i in nodes for c in nifmod.node_children(n, i)}
    roots = [i for i in nodes if i not in children]
    coms = [i for i in nodes if _node_name(n, i) == COM.encode()]
    if len(roots) != 1 or len(coms) != 1:
        raise nifmod.NifError(f"not a creature shell: roots {len(roots)}, COM nodes {len(coms)}")
    r = roots[0]
    idx = struct.unpack_from("<i", n.blocks[r], 0)[0]
    others = [i for i in range(len(n.blocks)) if i != r and len(n.blocks[i]) >= 4
              and struct.unpack_from("<i", n.blocks[i], 0)[0] == idx]
    new = n.string_index(root_name.encode()) if others else idx
    if not others:
        n.strings[idx] = root_name.encode()
        n.max_string_len = max(n.max_string_len, len(n.strings[idx]))
    n.blocks[r] = struct.pack("<i", new) + n.blocks[r][4:]
    b = n.blocks[coms[0]]
    ne = struct.unpack_from("<I", b, 4)[0]
    p = 8 + 4 * ne + 8
    b = b[:p] + struct.pack("<3f", *map(float, com_t)) + b[p + 12:]
    if com_q is not None:
        b = b[:p + 12] + struct.pack("<9f", *quat_to_rot9(com_q)) + b[p + 48:]
    n.blocks[coms[0]] = b
    return nifmod.serialize(n)


# A .rig bone record is 96 bytes from byte 128 (record k at 128 + 96 k). Verified 2026-11-17 by a byte diff of the vanilla
# critter rig against CALUMI's copy of it (docs/npc/creatures.md): +24 mirror partner index, +28 level, +40 a float;
# CALUMI writes -1 / 0 / 0.0 there. With those three restored from vanilla the vanilla trilobite keeps animating at a
# distance; without them it (and the chicken) freezes and slides a few feet off (owner, 2026-11-17 19:11).
RIG_RECORDS, RIG_RECORD = 128, 96
RIG_MIRROR, RIG_LEVEL, RIG_WEIGHT = 24, 28, 40
# vanilla critter levels: Root 5, COM 4, the core spine 3, the body 2, the last two depths 1 / 0
LEVEL_ROOT, LEVEL_COM, LEVEL_TRUNK, LEVEL_BODY = 5, 4, 3, 2
WEIGHT_CORE, WEIGHT_TRUNK = 1.0, 2.0
WEIGHT_BY_LEVEL = {2: 5.0, 1: 30.0, 0: 60.0}


def mirror_name(name: str) -> str:
    """The left/right partner's name (Left <-> Right, L_ <-> R_, a leading L/R before a capital, a trailing L/R), or
    the name itself for a centre bone."""
    for a, b in (("Left", "Right"), ("Right", "Left")):
        if a in name:
            return name.replace(a, b, 1)
    m = re.match(r"^([LR])(_|(?=[A-Z]))(.*)$", name)
    if m:
        return ("R" if m.group(1) == "L" else "L") + m.group(2) + m.group(3)
    m = re.match(r"^(.*[a-z0-9])([LR])$", name)
    if m:
        return m.group(1) + ("R" if m.group(2) == "L" else "L")
    return name


def rig_fields(cr: "CreatureRig", trunk_share: float = 0.4):
    """(mirror, level, weight) per bone (rig order) in the vanilla critter rig's pattern: mirror = the partner's index
    (itself for centre bones or when the partner is missing); level Root 5, COM 4, trunk 3 (from COM down the child
    with the most descendants while that subtree holds >= trunk_share of all bones: the critter's two spine bones),
    every other bone min(2, deepest - depth) with depth counted from COM (2 for the body, 1 and 0 for the last two
    depths). That rule gives every level of the vanilla critter rig (test_creature). Weight (meaning unresolved;
    vanilla grows from 1 at the core to 60 at the tips) 1 core, 2 trunk, then 5 / 30 / 60 for levels 2 / 1 / 0.
    Levels are what the distance freeze turned on: a Root at 0 (fix 7) froze the whole body."""
    names, parents = list(cr.names), list(cr.parents)
    n = len(names)
    idx = {nm.lower(): i for i, nm in enumerate(names)}
    kids = [[] for _ in range(n)]
    for i, p in enumerate(parents):
        if p >= 0:
            kids[p].append(i)
    size = [1] * n
    for i in reversed(range(n)):                       # parents precede children in a rig
        if parents[i] >= 0:
            size[parents[i]] += size[i]
    trunk = set()
    ci = names.index(COM) if COM in names else None
    cur = ci
    while cur is not None and kids[cur]:
        best = max(kids[cur], key=lambda j: size[j])
        if size[best] < trunk_share * n:
            break
        trunk.add(best)
        cur = best
    depth = [0] * n                                     # from COM (COM's children 1)
    for i in range(n):
        if ci is not None and i != ci and parents[i] >= 0:
            depth[i] = depth[parents[i]] + 1 if parents[i] != ci else 1
    below = [i for i in range(n) if ci is not None and i != ci and parents[i] >= 0 and _under(parents, i, ci)]
    deepest = max((depth[i] for i in below), default=0)
    mirror, level, weight = [], [], []
    for i, nm in enumerate(names):
        mirror.append(idx.get(mirror_name(nm).lower(), i))
        if nm == ROOT or parents[i] < 0:
            lv, w = LEVEL_ROOT, WEIGHT_CORE
        elif i == ci:
            lv, w = LEVEL_COM, WEIGHT_CORE
        elif i in trunk:
            lv, w = LEVEL_TRUNK, WEIGHT_TRUNK
        else:
            lv = max(0, min(LEVEL_BODY, deepest - depth[i]))
            w = WEIGHT_BY_LEVEL[lv]
        level.append(lv)
        weight.append(w)
    return mirror, level, weight


def mirror_clip(cr: "CreatureRig", lt, lq, mirror: Sequence[int]):
    """A clip (F, B, 3) / (F, B, 4) on this rig as its mirror image across the actor's YZ plane (x = right): every
    bone takes its partner's (mirror[b]) model-space pose reflected, so a left turn becomes a right turn and Root's
    root motion turns the other way. The partners' rest frames need not be mirror images (a fixed per-bone turn
    K_b = mirror(rest_m)^-1 rest_b is kept, as retarget.mirror_grip does); bones whose partner's local translation never
    changes keep their own rest offset, so bone lengths stay the rig's. Skyrim plays the chicken's right turns this
    way (its behaviour's "[mirror]" generators)."""
    from .retarget import qinv, qmirror_x
    lt, lq = np.asarray(lt, float), np.asarray(lq, float)
    rig = cr.rig()
    wt, wq = rig.fk(lt, lq)
    _rt0, rq0 = rig.rest_world()
    m = np.asarray(mirror, int)
    flip = np.array([-1.0, 1.0, 1.0])
    K = qmul(qinv(qmirror_x(rq0[m])), rq0)                               # (B, 4)
    nq = qmul(qmirror_x(wq[:, m]), K[None])
    nq /= np.linalg.norm(nq, axis=-1, keepdims=True)
    nt = wt[:, m] * flip
    out_t, out_q = np.empty_like(lt), np.empty_like(lq)
    for b, p in enumerate(cr.parents):
        if p < 0:
            out_t[:, b], out_q[:, b] = nt[:, b], nq[:, b]
            continue
        inv = qinv(nq[:, p])
        out_q[:, b] = qmul(inv, nq[:, b])
        src = lt[:, m[b]]
        out_t[:, b] = cr.t[b] if np.allclose(src, src[:1], atol=1e-6) else qrot(inv, nt[:, b] - nt[:, p])
    return out_t, out_q


DEATH_FRAMES, DEATH_ROLL_DEG, DEATH_LIE_M = 21, 85.0, 0.09
DEATH_DROOP = (("Neck0", -25.0), ("Neck1", -20.0), ("Neck2", -15.0))


def death_clip(cr: "CreatureRig", start_t, start_q, side: int = 1, frames: int = DEATH_FRAMES,
               roll_deg: float = DEATH_ROLL_DEG, lie_height: float = DEATH_LIE_M, droop=DEATH_DROOP):
    """A fall-over clip (frames, B, 3) / (frames, B, 4) from one pose (start_t / start_q (B, 3) / (B, 4) locals, e.g.
    the idle's first frame): COM rolls roll_deg about the actor's forward axis (+y; side +1 onto its right side, -1
    its left) and sinks to lie_height metres, the neck bones in `droop` bend down (about the body's side axis, in their
    parent's rest frame), all eased in (s = t^2) and held on the last frame. Skyrim's chicken has no death clip (its
    ragdoll takes over at once); in Starfield the critter graph plays a death clip and the body keeps that clip's last
    pose until hit (owner, 2026-11-17 22:38: the chicken died standing on its idle)."""
    start_t, start_q = np.asarray(start_t, float), np.asarray(start_q, float)
    lt = np.repeat(start_t[None], frames, 0)
    lq = np.repeat(start_q[None], frames, 0)
    ci = cr.names.index(COM)
    rest = rest_worlds(cr)
    for f in range(frames):
        u = (f / (frames - 1)) ** 2 if frames > 1 else 1.0
        a = math.radians(roll_deg) * u * (1 if side >= 0 else -1)
        roll = np.array([0.0, math.sin(a / 2), 0.0, math.cos(a / 2)])
        lq[f, ci] = qmul(roll, start_q[ci])
        lt[f, ci] = start_t[ci] + np.array([0.0, 0.0, (lie_height - start_t[ci][2]) * u])
        for bone, deg in droop:
            if bone not in cr.names:
                continue
            b = cr.names.index(bone)
            p = cr.parents[b]
            axis = rest[cr.names[p]][:3, :3].T @ np.array([1.0, 0.0, 0.0]) if p >= 0 else np.array([1.0, 0, 0])
            h = math.radians(deg) * u / 2
            lq[f, b] = qmul(np.array([*(axis * math.sin(h)), math.cos(h)]), start_q[b])
    return lt, lq


def sorted_by_level(cr: "CreatureRig") -> "CreatureRig":
    """The rig with its bones sorted by rig_fields level, highest first (stable, so parents stay before children:
    a child's level never exceeds its parent's). Vanilla rigs are in this order (the critter: 5, 4, 3, 3, 2 x 19,
    1 x 6, 0 x 2), and the game seems to animate only a leading run of the list far off: with the chicken's legs
    (level 2) listed after its comb and wattles (0), its head (1) animated afar and its legs did not (owner,
    2026-11-17 19:20)."""
    _m, level, _w = rig_fields(cr)
    order = sorted(range(len(cr.names)), key=lambda i: -level[i])
    return cr.reordered(order)


def _under(parents, i, anc) -> bool:
    while i >= 0:
        if i == anc:
            return True
        i = parents[i]
    return False


def set_rig_fields(data: bytes, mirror: Sequence[int], level: Sequence[int], weight: Sequence[float]) -> bytes:
    """A CALUMI-written .rig with each bone record's mirror (+24), level (+28) and weight (+40) set. The layout is
    checked first: 12 x 0xFF before +24 and CALUMI's -1 / 0 / 0.0 in the three fields, else ValueError."""
    data = bytearray(data)
    n = len(level)
    if not len(mirror) == len(weight) == n:
        raise ValueError("mirror, level and weight differ in length")
    end = RIG_RECORDS + RIG_RECORD * n
    if end > len(data):
        raise ValueError(f"rig of {len(data)} bytes too short for {n} bone records")
    for k in range(n):
        r = RIG_RECORDS + RIG_RECORD * k
        if data[r + 12:r + RIG_MIRROR] != b"\xff" * 12 or struct.unpack_from("<ii", data, r + RIG_MIRROR) != (-1, 0) \
                or struct.unpack_from("<f", data, r + RIG_WEIGHT) != (0.0,):
            raise ValueError(f"bone {k}: unexpected record layout at {r}")
    for k in range(n):
        r = RIG_RECORDS + RIG_RECORD * k
        struct.pack_into("<ii", data, r + RIG_MIRROR, int(mirror[k]), int(level[k]))
        struct.pack_into("<f", data, r + RIG_WEIGHT, float(weight[k]))
    return bytes(data)

