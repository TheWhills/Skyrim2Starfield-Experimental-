"""A Skyrim creature's ragdoll as a Starfield one (docs/npc/creatures.md, "ragdoll").

Skyrim (verified on the chicken's skeleton.nif, owner's file 2026-11-17): bhkBlendCollisionObject (target node i32,
flags u16, body i32) -> bhkRigidBody (shape ref at 0, translation at 52 and rotation x y z w at 68 = the node's rest
world transform in havok units (= metres), inertia hkMatrix3 at 116, centre of mass at 164, mass at 180, constraint
count at 244 and refs after) -> bhkCapsuleShape (radius at 4, end points at 16 and 32, in the body's = the node's
frame). bhkRagdollConstraint: entity count, A (the child body), B (its parent), priority, then twist / plane / motor /
pivot vectors for A and B (A's in A's frame, B's in B's), cone, plane min / max, twist min / max, max friction.

Starfield (verified on the vanilla trilobite body, owner's file 2026-11-17): one bhkRagdollSystem block (u32 size +
Havok tagfile, root hknpRagdollData) and one bhkNPCollisionObject (target node i32, flags u16 0x80, system block i32,
body index u32) per body, on the body's bone node in the creature's body NIF; each body sits at its bone's frame
(position 0, orientation identity) with its shape in that frame; constraints hold transformA / transformB = the
columns twist, plane, twist x plane and the pivot (the trilobite's satisfy col2 = col0 x col1), body A the child and
B the parent, as Skyrim's; plane limits stored as pi/2 + angle (the trilobite's +-30 deg read 1.047 / 2.094); an
unnamed ragdoll skeleton with the bodies' parent indices and boneToBodyMap 0..n-1.

Built by editing the vanilla ragdoll (template types and settings: materials, motion properties, filter info, motors,
friction atoms) through hktagwrite; the writer's round trip of the trilobite's ragdoll reads back value for value
(its item order differs from Havok's own).
"""
import copy
import math
import struct
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import hktagfile, hktagwrite
from . import nif as nifmod

RAGDOLL_TYPE = "hknpRagdollData"
COLLISION_FLAGS = 0x80
ARRAY_ALIGN, OBJECT_ALIGN = 16, 8          # the vanilla ragdoll's item alignment (hktagwrite.Writer)


def rewrite(template_blob: bytes, root) -> bytes:
    """A ragdoll tagfile of `root` (hknpRagdollData value) on the template's types, vanilla alignment."""
    return hktagwrite.Writer(template_blob, ARRAY_ALIGN, OBJECT_ALIGN).write(root, RAGDOLL_TYPE)


def _unit(v):
    v = np.asarray(v[:3], float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def _name(n, i) -> Optional[str]:
    ni, = struct.unpack_from("<i", n.blocks[i], 0)
    return n.strings[ni].decode("latin-1") if ni >= 0 else None


def skyrim_bodies(nif_bytes: bytes) -> List[Dict]:
    """The ragdoll of a Skyrim skeleton NIF: per body (parents first) {"node", "world_t" (3), "world_R" (3x3, v_world
    = R v_local), "radius", "a", "b" (capsule ends, node frame), "mass", "inertia" (3x3), "com" (3), "parent" (index
    into the list or -1), "constraint": {twist_a, plane_a, pivot_a, twist_b, plane_b, pivot_b, cone, plane_min,
    plane_max, twist_min, twist_max, friction} or None}. Non-capsule shapes raise ValueError."""
    n = nifmod.parse(nif_bytes)
    world = nifmod.world_transforms(n)
    raw, body_index = [], {}
    for i in range(len(n.blocks)):
        if n.type_of(i) != "bhkBlendCollisionObject":
            continue
        target, _flags, body = struct.unpack_from("<iHi", n.blocks[i], 0)
        rb = n.blocks[body]
        shape, = struct.unpack_from("<i", rb, 0)
        if n.type_of(shape) != "bhkCapsuleShape":
            raise ValueError(f"{_name(n, target)}: {n.type_of(shape)} (only capsules are converted)")
        cs = n.blocks[shape]
        t, R, _s = world(target)
        nc, = struct.unpack_from("<I", rb, 244)
        raw.append({"node": _name(n, target), "block": body, "world_t": np.asarray(t, float) / _havok_scale(),
                    "world_R": np.asarray(R, float).reshape(3, 3),
                    "radius": struct.unpack_from("<f", cs, 4)[0],
                    "a": np.array(struct.unpack_from("<3f", cs, 16)), "b": np.array(struct.unpack_from("<3f", cs, 32)),
                    "mass": struct.unpack_from("<f", rb, 180)[0],
                    "inertia": np.array(struct.unpack_from("<12f", rb, 116)).reshape(3, 4)[:, :3],
                    "com": np.array(struct.unpack_from("<3f", rb, 164)),
                    "constraints": list(struct.unpack_from(f"<{nc}i", rb, 248))})
        body_index[body] = len(raw) - 1
    out = []
    for b in raw:
        b["parent"], b["constraint"] = -1, None
        for c in b.pop("constraints"):
            cb = n.blocks[c]
            ea, eb = struct.unpack_from("<2i", cb, 4)
            if ea != b["block"] or eb not in body_index:
                continue
            v = [np.array(struct.unpack_from("<4f", cb, 16 + 16 * k)) for k in range(8)]
            lim = struct.unpack_from("<6f", cb, 144)
            b["parent"] = body_index[eb]
            b["constraint"] = {"twist_a": _unit(v[0]), "plane_a": _unit(v[1]), "pivot_a": v[3][:3],
                               "twist_b": _unit(v[4]), "plane_b": _unit(v[5]), "pivot_b": v[7][:3],
                               "cone": lim[0], "plane_min": lim[1], "plane_max": lim[2], "twist_min": lim[3],
                               "twist_max": lim[4], "friction": lim[5]}
        out.append(b)
    for b in out:
        del b["block"]
    return out


def _havok_scale() -> float:
    from .skyrimnif import HAVOK_SCALE
    return HAVOK_SCALE


def to_rig_frames(bodies: List[Dict], rig_worlds: Dict[str, np.ndarray], name_map: Dict[str, str]) -> List[Dict]:
    """The bodies with every point / direction moved from the Skyrim node's frame into the frame of the rig bone it
    becomes (name_map: Skyrim node -> rig bone; rig_worlds: rig bone -> 4x4 rest world, metres). A bone whose rest
    world equals the node's (every bone but a levelled COM) keeps the values; COM gets the pelvis' pitch."""
    out = []
    for b in bodies:
        bone = name_map.get(b["node"]) or name_map.get(b["node"].lower())
        if bone is None or bone not in rig_worlds:
            raise ValueError(f"no rig bone for ragdoll node {b['node']}")
        W = rig_worlds[bone]
        M = W[:3, :3].T @ b["world_R"]                         # node frame -> bone frame
        d = W[:3, :3].T @ (b["world_t"] - W[:3, 3])           # node origin in the bone frame (about 0)
        c = dict(b, bone=bone, a=M @ b["a"] + d, b=M @ b["b"] + d, com=M @ b["com"] + d,
                 inertia=M @ b["inertia"] @ M.T, frame=M, offset=d)
        out.append(c)
    for c in out:                                            # constraint vectors: A in the child's, B in the parent's
        k = c["constraint"]
        if k is None:
            continue
        p = out[c["parent"]]
        c["constraint"] = dict(k, twist_a=c["frame"] @ k["twist_a"], plane_a=c["frame"] @ k["plane_a"],
                               pivot_a=c["frame"] @ k["pivot_a"] + c["offset"],
                               twist_b=p["frame"] @ k["twist_b"], plane_b=p["frame"] @ k["plane_b"],
                               pivot_b=p["frame"] @ k["pivot_b"] + p["offset"])
    return out


def _quat_from_matrix(m) -> List[float]:
    from .retarget import mat_to_quat
    return list(mat_to_quat(np.asarray(m, float)))


def _capsule_volume(r: float, a, b) -> float:
    h = float(np.linalg.norm(np.asarray(a) - np.asarray(b)))
    return math.pi * r * r * h + 4.0 / 3.0 * math.pi * r ** 3


def _transform(twist, plane, pivot) -> List[float]:
    twist, plane = _unit(twist), _unit(plane)
    plane = _unit(plane - twist * float(np.dot(plane, twist)))     # orthonormal
    cross = np.cross(twist, plane)
    return [*twist, 0.0, *plane, 0.0, *cross, 0.0, *map(float, pivot), 0.0]


def _limit(atom: Dict, lo: float, hi: float):
    atom["minAngle"], atom["maxAngle"] = float(lo), float(hi)
    atom["invCosMinAngle"], atom["invCosMaxAngle"] = 1.0 / math.cos(lo), 1.0 / math.cos(hi)
    atom["tanMinAngle"], atom["tanMaxAngle"] = math.tan(lo), math.tan(hi)


def build_ragdoll(template_blob: bytes, bodies: List[Dict]) -> bytes:
    """An hknpRagdollData tagfile for `bodies` (to_rig_frames output, parents first) on the template's types and
    settings: body 0 takes the template root body's ids / filter, the others its first capsule body's; constraints
    copy the template's first one with this joint's frames and limits."""
    tf = hktagfile.Tagfile(template_blob)
    root = tf.item_value(1)
    if root.get("$class") not in (None, RAGDOLL_TYPE) or not root.get("bodyCinfos") or not root.get("constraintCinfos"):
        raise ValueError("template is not a ragdoll with bodies and constraints")
    tpl_root = root["bodyCinfos"][0]
    tpl_cap = next(b for b in root["bodyCinfos"] if b["shape"].get("$class") == "hknpCapsuleShape")
    tpl_con = root["constraintCinfos"][0]
    sk = root["skeleton"]
    cinfos, cons, parents = [], [], []
    for i, b in enumerate(bodies):
        ci = copy.deepcopy(tpl_cap)
        if i == 0:
            for k in ("collisionFilterInfo", "materialId", "motionPropertiesId", "qualityId", "flags"):
                ci[k] = tpl_root[k]
        shape = ci["shape"]
        shape["convexRadius"] = float(b["radius"])
        shape["hull"]["vertices"] = [{"x": float(p[0]), "y": float(p[1]), "z": float(p[2])} for p in (b["a"], b["b"])]
        ci["mass"] = float(b["mass"])
        vals, vecs = np.linalg.eigh((b["inertia"] + b["inertia"].T) / 2)
        if np.linalg.det(vecs) < 0:
            vecs[:, 0] = -vecs[:, 0]
        md = ci["massDistribution"]["massDistribution"]
        md["centerOfMassAndVolume"] = [*map(float, b["com"]), _capsule_volume(b["radius"], b["a"], b["b"])]
        md["majorAxisSpace"] = _quat_from_matrix(vecs)
        md["inertiaTensor"] = [*map(float, np.maximum(vals, 1e-6)), 0.0]
        ci["position"], ci["orientation"] = [0.0] * 4, [0.0, 0.0, 0.0, 1.0]
        cinfos.append(ci)
        parents.append(int(b["parent"]))
        k = b["constraint"]
        if k is None:
            continue
        c = copy.deepcopy(tpl_con)
        at = c["constraintData"]["atoms"]
        at["transforms"]["transformA"] = _transform(k["twist_a"], k["plane_a"], k["pivot_a"])
        at["transforms"]["transformB"] = _transform(k["twist_b"], k["plane_b"], k["pivot_b"])
        at["twistLimit"]["minAngle"], at["twistLimit"]["maxAngle"] = float(k["twist_min"]), float(k["twist_max"])
        cone = at["coneLimit"]
        cone["maxAngle"] = float(k["cone"])
        cone["invCosMaxAngle"], cone["tanMaxAngle"] = 1.0 / math.cos(k["cone"]), math.tan(k["cone"])
        _limit(at["planesLimit"], math.pi / 2 + k["plane_min"], math.pi / 2 + k["plane_max"])
        at["angFriction"]["maxFrictionTorque"] = float(k["friction"])
        c["bodyA"] = {"serialAndIndex": i}
        c["bodyB"] = {"serialAndIndex": int(b["parent"])}
        cons.append(c)
    root["bodyCinfos"] = cinfos
    root["constraintCinfos"] = cons
    bone0, bone1 = sk["bones"][0], sk["bones"][min(1, len(sk["bones"]) - 1)]
    pose0, pose1 = sk["referencePose"][0], sk["referencePose"][min(1, len(sk["referencePose"]) - 1)]
    sk["parentIndices"] = parents
    sk["bones"] = [copy.deepcopy(bone0 if i == 0 else bone1) for i in range(len(bodies))]
    sk["referencePose"] = [copy.deepcopy(pose0 if i == 0 else pose1) for i in range(len(bodies))]
    root["boneToBodyMap"] = list(range(len(bodies)))
    return rewrite(template_blob, root)


def template_from_body(nif_bytes: bytes) -> bytes:
    """The Havok tagfile of a vanilla creature body's bhkRagdollSystem block."""
    n = nifmod.parse(nif_bytes)
    for i in range(len(n.blocks)):
        if n.type_of(i) == "bhkRagdollSystem":
            blk = n.blocks[i]
            size, = struct.unpack_from("<I", blk, 0)
            return bytes(blk[4:4 + size])
    raise ValueError("no bhkRagdollSystem in the template body")
