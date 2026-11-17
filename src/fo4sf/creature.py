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
The mesh is skinned to those bone names with binds = the inverse of each bone's bind world from the Skyrim mesh (the
convention of the game's own hairs, skyrimhair.nif_files), so it is drawn as Skyrim draws it.
"""
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import nif as nifmod
from .retarget import Rig, SKYRIM_M_PER_UNIT, qmul, qrot

COM = "COM"


@dataclass
class CreatureRig:
    names: List[str]
    parents: List[int]
    t: np.ndarray            # (B, 3) metres, local rest
    q: np.ndarray            # (B, 4) x y z w
    sources: List[int]       # index of each bone in the Skyrim skeleton
    root: int                # the folded Skyrim root (index in the Skyrim skeleton), -1 if none
    com: int                 # the Skyrim bone that became COM

    def fold(self, lt, lq, unit: float = SKYRIM_M_PER_UNIT):
        """Skyrim locals (..., Bs, 3) / (..., Bs, 4) in Havok units -> this rig's locals in metres."""
        lt, lq = np.asarray(lt, float), np.asarray(lq, float)
        t = lt[..., self.sources, :] * unit
        q = lq[..., self.sources, :].copy()
        if self.root >= 0:
            k = self.sources.index(self.com)
            rq, rt = lq[..., self.root, :], lt[..., self.root, :] * unit
            q[..., k, :] = qmul(rq, lq[..., self.com, :])
            t[..., k, :] = rt + qrot(rq, lt[..., self.com, :] * unit)
        return t, q

    def rig(self) -> Rig:
        return Rig(self.names, self.parents, self.t, self.q)


def creature_rig(sk: Rig, com: str = "Pelvis", root: Optional[str] = None,
                 unit: float = SKYRIM_M_PER_UNIT) -> CreatureRig:
    """The Starfield rig of a Skyrim creature skeleton (Havok units): `root` (default the skeleton's root when it is
    the COM bone's parent) folded into `com`, which is renamed COM and becomes the rig's root; other bones keep
    names and hierarchy. Bones outside COM's subtree (none on the chicken) are dropped."""
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
    pos = {s: k for k, s in enumerate(keep)}
    names = [COM if i == ci else sk.names[i] for i in keep]
    parents = [-1 if i == ci else pos[sk.parents[i]] for i in keep]
    cr = CreatureRig(names, parents, np.zeros((len(keep), 3)), np.zeros((len(keep), 4)), keep, ri, ci)
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


def skinned_files(shape, material_path: str, out_name: str, com_source: str, rig_names: List[str]) -> Dict[str, bytes]:
    """{"meshes/<out_name>.nif", "geometries/<a>/<b>.mesh"}: a gearfit.SkyShape (metres, model space, bind worlds per
    bone) skinned to the creature rig's bone names."""
    from . import convert_static, sfmesh, sfnif
    names = bone_name_map(shape.bones, rig_names, com_source)
    used = sorted({names[shape.bones[b]] for vw in shape.weights for b, _w in vw}, key=lambda n: (n != COM, n))
    index = {n: i for i, n in enumerate(used)}
    pts = [tuple(map(float, p)) for p in shape.points]
    fo4 = nifmod.Fo4Shape(shape.name, (0.0, 0.0, 0.0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0, -1, -1, -1, pts,
                          list(shape.uvs), [tuple(map(float, n)) for n in shape.normals], [], [],
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
    n = sfnif.build_skinned_nif(out_name.rsplit("/", 1)[-1].encode(), [sh])
    return {f"geometries/{d}/{f}.mesh": data, f"meshes/{out_name}.nif": nifmod.serialize(n)}


NODE_TYPES = ("NiNode", "BSFadeNode")


def _node_name(n, i) -> bytes:
    idx = struct.unpack_from("<i", n.blocks[i], 0)[0]
    return n.strings[idx] if 0 <= idx < len(n.strings) else b""


def shell_skeleton(data: bytes, root_name: str, com_t) -> bytes:
    """A copy of a vanilla creature skeleton.nif shell (the critter's) for another creature: the root node renamed
    (Critter_mrRigRoot -> <root_name>) and the COM node moved to com_t (metres, its local translation under Root).
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
    n.blocks[coms[0]] = b[:p] + struct.pack("<3f", *map(float, com_t)) + b[p + 12:]
    return nifmod.serialize(n)
