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
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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


def build_body_nif(root_name: bytes, shape, cr: CreatureRig, bones: List[str], bsx_flags: int = BODY_BSX) -> nifmod.NifFile:
    """A creature body NIF laid out like the vanilla trilobite's (verified layout, owner's model compare 2026-11-17):
    the model carries its own bone nodes (root > COM_Twin > the rig's hierarchy at rest, each with NiStringExtraData
    'sgoKeep'), the skin's BSSkin::Instance points at those nodes (skeleton root = the root node), and its SkinAttach
    names are empty. Worn gear (sfnif.build_skinned_nif: names only, no nodes) drew nothing on a creature (owner,
    2026-11-17 14:02: heard, not seen). As vanilla (model compare 2): COM_Twin sits at the model's origin and carries
    NiStringExtraData ParentBoneName = COM instead of sgoKeep, i.e. the body hangs off the skeleton's COM bone and
    the model is in COM's space (skinned_files moves the mesh there); its children carry the rig's local rest.
    `shape` is an sfnif.SkinnedShape whose bones / binds are in `bones` order."""
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
                         meshes=[sfnif.MeshRef(shape.indices_size, shape.num_verts, 0x40, shape.mesh_path), None, None,
                                 None])
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

    def node(name_idx, extra, xform, children):
        return (struct.pack("<iI", name_idx, len(extra)) + struct.pack(f"<{len(extra)}i", *extra)
                + struct.pack("<iI", -1, 0xE) + xform + struct.pack("<iI", -1, len(children))
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
        f.blocks[b] = node(f.string_index(nm.encode("latin-1")), [e], xform, kids[b])
    f.footer = struct.pack("<II", 1, 0)
    return f


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


def skinned_files(shape, material_path: str, out_name: str, com_source: str, cr: CreatureRig,
                  tangents=None, bsx_flags: int = BODY_BSX) -> Dict[str, bytes]:
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
    joints = {names[b]: w for b, w in shape.joints.items() if b in names}
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
    n = build_body_nif(b"ExportScene", sh, cr, used, bsx_flags)
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
