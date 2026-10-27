"""Starfield Havok cloth (BSClothExtraData) built from bone chains: the physics of a Skyrim HDT-SMP hair or cape as the
engine's own bone-driving cloth, the setup every Starfield physics hair uses (src/fo4sf/sfcloth.py survey).

What the engine runs (decoded from the game's and mods' cloth, docs/armor/animation-port.md "Cloth writer"):
* operators Skin (hclBoneSpaceSkinPNOperator: the sim mesh's rest vertices follow their host bones) -> Move Particles
  (pinned particles take those positions) -> Sim (hclSimulateOperator) -> MeshBoneDeform
  (hclSimpleMeshBoneDeformOperator: each chain bone follows one simulated triangle); the visible mesh is ordinary
  skinning to the host and chain bones.
* triangle frame of the bone deformer (verified on OC Ponytail and Eris Hairstyles, every pair to 1e-4):
  origin c = triangle centroid, axes [v0 - c, v1 - c, cross(v1 - v0, v2 - v0) / 3]; bone = frame @ local.
* skin blocks: 16 consecutive vertices per block (the last padded with its final vertex), one bone each
  (oneBlendEntries; control bytes 0 / 1 / 2 / 3 = four / three / two / one-bone blocks, the localPNs in control order).
  Bone-space skin (Eris): local position = inverse(bone rest world) @ vertex as floats. Object-space skin (OC, the
  art tools'): vertex = sum of weight x bone world @ boneFromSkinMesh @ local, local positions packed (verified on
  OC Ponytail's 160 pinned particles to 5e-5 m). Packed vectors are hkPackedVector3: value * 2^16 * float(bits =
  w << 16); w = 0x3000 for unit normals.
* standard links: stiffnessA = s * wA / (wA + wB), stiffnessB = -s * wB / (wA + wB) with w = inverse mass; no
  particle twice in one batch of 4; leftovers as singles.
* colliders: a shape in a frame at its bone's origin with model axes at rest (collidableTransformMap offset = the
  inverse of the bone's rest rotation); capsules: dir = normalised end - start, capLenSqrdInv = 1 / |end - start|^2.
* transform trackers: Skin reads its bones, Sim reads the collider bones (both components), MeshBoneDeform writes the
  chain bones; a state's usage is the union.

The output is the template's hclClothData / hkaSkeleton with every per-rig part replaced, so fields this module does not
know keep the template's values. Template = a Starfield physics hair with the needed types (hktagwrite copies its TYPE
section); it is read from the user's game or mods at conversion time, never committed.
"""
import copy
import math
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import hktagfile, hktagwrite

SKIN_OPS = ("hclBoneSpaceSkinPNOperator", "hclObjectSpaceSkinPNOperator")
OPERATORS = ("hclMoveParticlesOperator", "hclSimulateOperator", "hclSimpleMeshBoneDeformOperator")
NEEDED_TYPES = OPERATORS + ("hclStandardLinkConstraintSetMx", "hclCapsuleShape")
STRETCH_TYPES = ("hclStretchLinkConstraintSetMx", "hclStretchLinkConstraintSet")
RANGE_TYPE = "hclLocalRangeConstraintSet"


class ClothBuildError(ValueError):
    pass


# -- small maths -------------------------------------------------------------------------------------------------------
def quat_matrix(q) -> np.ndarray:
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def matrix_quat(m: np.ndarray) -> Tuple[float, float, float, float]:
    """(x, y, z, w) of a rotation matrix."""
    t = m[0, 0] + m[1, 1] + m[2, 2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    n = math.sqrt(x * x + y * y + z * z + w * w)
    return (x / n, y / n, z / n, w / n)


def skeleton_world(sk: Dict) -> List[np.ndarray]:
    """Rest world (model space) 4x4 per bone of an hkaSkeleton value."""
    out = []
    for i, t in enumerate(sk["referencePose"]):
        m = np.eye(4)
        m[:3, :3] = quat_matrix(t["rotation"]) * np.array(t["scale"][:3])
        m[:3, 3] = t["translation"][:3]
        p = sk["parentIndices"][i]
        out.append(m if p < 0 else out[p] @ m)
    return out


def mat4_values(m: np.ndarray) -> List[float]:
    """hkMatrix4 field values (column-major)."""
    return [float(v) for v in np.asarray(m, float).T.reshape(16)]


def triangle_frame(v0, v1, v2) -> np.ndarray:
    """The bone deformer's frame of a triangle (see the module notes)."""
    c = (v0 + v1 + v2) / 3.0
    f = np.eye(4)
    f[:3, 0], f[:3, 1], f[:3, 2], f[:3, 3] = v0 - c, v1 - c, np.cross(v1 - v0, v2 - v0) / 3.0, c
    return f


def pack_vector3(v) -> List[int]:
    """hkPackedVector3 values of a vector with |components| <= 1 (exponent word 0x3000: scale 2^-15)."""
    return [int(max(-32767, min(32767, round(float(c) * 32768.0)))) for c in v[:3]] + [0x3000]


def pack_position(v) -> List[int]:
    """hkPackedVector3 of any vector: the exponent word is a power of two (a float with no mantissa bits below the
    top 16, as the stored files') so the largest component fits in 15 bits."""
    m = max(abs(float(c)) for c in v[:3])
    if m < 1e-12:
        return [0, 0, 0, 0x3000]
    e = math.ceil(math.log2(m / (32767.0 * 65536.0)))
    scale = 2.0 ** e
    bits = struct.unpack("<I", struct.pack("<f", scale))[0] >> 16
    return [int(max(-32767, min(32767, round(float(c) / (65536.0 * scale))))) for c in v[:3]] + [bits]


def unpack_vector3(vals) -> np.ndarray:
    scale = struct.unpack("<f", struct.pack("<I", (vals[3] & 0xFFFF) << 16))[0]
    return np.array(vals[:3], float) * 65536.0 * scale


def bitfield(indices, n: int) -> Dict:
    words = [0] * ((n + 31) // 32)
    for i in indices:
        words[i // 32] |= 1 << (i % 32)
    return {"storage": {"words": words, "numBits": n}}


# -- the rig -----------------------------------------------------------------------------------------------------------
@dataclass
class ChainBone:
    name: str                   # Starfield bone name (new; created by the engine from the cloth skeleton)
    parent: str                 # another ChainBone or a skeleton bone (the host, e.g. C_Head)
    world: np.ndarray           # rest transform in model space (4x4, metres)
    mass: float = 0.2           # kg, from the SMP bone
    limit: float = 0.4          # radians the bone may turn from its rest pose relative to its parent (SMP limits)
    tip: Optional[np.ndarray] = None     # end point for a bone with no chain child (default: extrapolated)


@dataclass
class Capsule:
    name: str
    bone: str                   # skeleton bone the collider rides on
    start: np.ndarray           # in the frame at the bone's origin with model axes at rest
    end: np.ndarray
    radius: float


@dataclass
class Settings:
    width: float = 0.015        # m, side offset of the second particle row (gives each bone a twist reference)
    damping: float = 0.9        # globalDampingPerSecond
    gravity: float = -9.81
    radius: float = 0.005       # particle collision radius (m)
    friction: float = 0.3
    range_scale: float = 1.0    # scales the local-range distances (looser > 1)
    name: str = "S2S Bone Chain Cloth"


@dataclass
class Rig:
    positions: np.ndarray                    # (n, 3) particles
    fixed: List[int]
    masses: List[float]
    host: List[str]                          # per particle: the bone its rest position follows
    triangles: List[Tuple[int, int, int]]
    driven: List[Tuple[str, int]]            # (chain bone, triangle index)
    links: List[Tuple[int, int]]
    stretch: List[Tuple[int, int, float]]    # (root, particle, max length)
    ranges: List[Tuple[int, float]]          # (particle, max distance from its rest position)
    report: Dict = field(default_factory=dict)


def _children(bones: List[ChainBone]) -> Dict[str, List[ChainBone]]:
    out: Dict[str, List[ChainBone]] = {}
    for b in bones:
        out.setdefault(b.parent, []).append(b)
    return out


def _side(b: ChainBone, along: np.ndarray) -> np.ndarray:
    """Unit vector perpendicular to the segment: the bone's own axis most perpendicular to it."""
    best, out = 2.0, None
    for k in range(3):
        a = b.world[:3, k] / (np.linalg.norm(b.world[:3, k]) or 1.0)
        d = abs(float(a @ along))
        if d < best:
            best, out = d, a
    s = out - (out @ along) * along
    return s / (np.linalg.norm(s) or 1.0)


def build_rig(bones: List[ChainBone], host_of_root: Dict[str, str], s: Settings) -> Rig:
    """Particles and triangles for chains of bones. A joint (a bone's origin, or the end of a bone with no chain
    child) gets two particles: A on the joint and B beside it; each bone follows the triangle (A0, B0, A1) of its
    joints. The origins of chain roots (bones whose parent is not a chain bone) are pinned: SMP's first simulated
    bone pivots on its kinematic anchor at its own origin."""
    names = {b.name for b in bones}
    kids = _children(bones)
    pos: List[np.ndarray] = []
    fixed, masses, host = [], [], []
    joint_of: Dict[str, int] = {}            # bone -> A particle of its origin
    end_of: Dict[str, int] = {}
    side_of: Dict[int, int] = {}             # A particle -> its B particle
    root_of: Dict[int, int] = {}             # A particle -> A particle of the chain root
    path_len: Dict[int, float] = {}
    angle: Dict[int, float] = {}             # A particle -> cumulative limit of the bones above it
    reach: Dict[int, float] = {}             # A particle -> how far it may move from rest
    triangles, driven, links = [], [], []

    def new(p, pinned, m, h):
        pos.append(np.asarray(p, float))
        fixed.append(pinned)
        masses.append(0.0 if pinned else m)
        host.append(h)
        return len(pos) - 1

    def joint(p, side_dir, pinned, m, h):
        a = new(p, pinned, m, h)
        side_of[a] = new(p + s.width * side_dir, pinned, m, h)
        return a

    order, seen = [], set()

    def visit(b):
        if b.name in seen:
            return
        if b.parent in names:
            visit(next(x for x in bones if x.name == b.parent))
        seen.add(b.name)
        order.append(b)
    for b in bones:
        visit(b)

    for b in order:
        origin = b.world[:3, 3]
        chain_kids = kids.get(b.name, [])
        if chain_kids:
            end = chain_kids[0].world[:3, 3]
        elif b.tip is not None:
            end = np.asarray(b.tip, float)
        else:
            par = next((x for x in bones if x.name == b.parent), None)
            prev = origin - par.world[:3, 3] if par is not None else np.array([0.0, 0.0, -0.05])
            end = origin + (prev if np.linalg.norm(prev) > 1e-4 else np.array([0.0, 0.0, -0.05]))
        seg = end - origin
        length = float(np.linalg.norm(seg))
        if length < 1e-4:
            raise ClothBuildError(f"bone {b.name}: zero length")
        along = seg / length
        side = _side(b, along)
        if b.parent in names:
            a0 = end_of[b.parent]
            if np.linalg.norm(pos[a0] - origin) > 1e-3:            # a branch starting off its parent's end
                anchor = joint_of[b.parent]
                a0 = joint(origin, side, False, b.mass * 0.5, host[anchor])
                links += [(anchor, a0), (end_of[b.parent], a0)]
                root_of[a0] = root_of[anchor]
                path_len[a0] = path_len[anchor] + float(np.linalg.norm(origin - pos[anchor]))
                angle[a0] = angle[anchor]
                reach[a0] = reach[anchor]
        else:
            h = host_of_root.get(b.name)
            if h is None:
                raise ClothBuildError(f"chain root {b.name}: no host bone")
            a0 = joint(origin, side, True, 0.0, h)
            root_of[a0] = a0
            path_len[a0], angle[a0], reach[a0] = 0.0, 0.0, 0.0
        joint_of[b.name] = a0
        h = host[a0]
        a1 = joint(end, side, False, b.mass * 0.5, h)
        end_of[b.name] = a1
        root_of[a1] = root_of[a0]
        path_len[a1] = path_len[a0] + length
        angle[a1] = angle[a0] + max(0.0, b.limit)
        # the end moves at most along the chord of every bone above it turning by its accumulated limit
        reach[a1] = reach[a0] + length * 2.0 * math.sin(min(angle[a1], math.pi) / 2.0)
        b0, b1 = side_of[a0], side_of[a1]
        triangles.append((a0, b0, a1))
        driven.append((b.name, len(triangles) - 1))
        triangles.append((b0, b1, a1))
        links += [(a0, a1), (b0, b1), (a1, b1), (b0, a1), (a0, b0)]
    links = [(i, j) for i, j in dict.fromkeys(tuple(sorted(l)) for l in links) if not (fixed[i] and fixed[j])]
    stretch, ranges = [], []
    for a, r in root_of.items():
        if fixed[a]:
            continue
        for p in (a, side_of[a]):
            stretch.append((r if p == a else side_of[r], p, path_len[a]))
            ranges.append((p, reach[a] * s.range_scale))
    return Rig(np.array(pos), [i for i, f in enumerate(fixed) if f], masses, host, triangles, driven, links,
               stretch, ranges, {"particles": len(pos), "fixed": sum(fixed), "triangles": len(triangles),
                                 "bones": len(order)})


# -- cloth data --------------------------------------------------------------------------------------------------------
def human_skeleton(template_root: Dict) -> Dict:
    """The template's hkaSkeleton without the bones its cloth drives (and their descendants)."""
    cd, sk = template_root["hclClothData"], template_root["hkaSkeleton"]
    drop = set()
    for o in cd["operators"]:
        for pr in o.get("triangleBonePairs", []):
            drop.add(pr["boneOffset"] // 64)
    parents = sk["parentIndices"]
    changed = True
    while changed:
        changed = False
        for i, p in enumerate(parents):
            if p in drop and i not in drop:
                drop.add(i)
                changed = True
    keep = [i for i in range(len(parents)) if i not in drop]
    new_index = {old: k for k, old in enumerate(keep)}
    out = {k: v for k, v in sk.items() if k not in ("parentIndices", "bones", "referencePose")}
    out["parentIndices"] = [new_index.get(parents[i], -1) for i in keep]
    out["bones"] = [dict(sk["bones"][i]) for i in keep]
    out["referencePose"] = [copy.deepcopy(sk["referencePose"][i]) for i in keep]
    return out


def template_kind(root: Dict) -> Dict:
    """Which classes the template's cloth uses: {"skin", "stretch", "range"} (None = absent)."""
    cd = root["hclClothData"]
    classes = [o.get("$class") for o in cd["operators"]]
    skin = next((c for c in classes if c in SKIN_OPS), None)
    sets = [c.get("$class") for c in cd["simClothDatas"][0]["staticConstraintSets"]]
    return {"skin": skin, "stretch": next((c for c in STRETCH_TYPES if c in sets), None),
            "range": RANGE_TYPE if RANGE_TYPE in sets else None}


def check_template(template_blob: bytes) -> Dict:
    """The template's root objects; raises when it is not a bone-driving cloth with the classes this builder writes
    (a skin operator of either kind, move / simulate / bone-deform operators, standard links, capsules)."""
    tf = hktagfile.Tagfile(template_blob)
    have = {t.name for t in tf.types}
    missing = [n for n in NEEDED_TYPES if n not in have]
    if not any(n in have for n in SKIN_OPS):
        missing.append(" or ".join(SKIN_OPS))
    if missing:
        raise ClothBuildError("cloth template lacks types: " + ", ".join(missing))
    root = tf.root()
    cd = root.get("hclClothData")
    if cd is None or "hkaSkeleton" not in root:
        raise ClothBuildError("cloth template has no hclClothData / hkaSkeleton")
    classes = [o.get("$class") for o in cd["operators"]]
    if (len(classes) < 4 or classes[0] not in SKIN_OPS or tuple(classes[1:4]) != OPERATORS
            or len(cd["bufferDefinitions"]) != 2 or len(cd["simClothDatas"]) != 1):
        raise ClothBuildError(f"cloth template layout not a bone-driving hair: {classes}")
    root["$kind"] = template_kind(root)
    return root


def template_score(root: Dict) -> int:
    """Preference among usable templates: stretch links and a local range, as SMP's limits need."""
    k = root.get("$kind") or template_kind(root)
    return (k["range"] is not None) * 2 + (k["stretch"] is not None)


def _std_links(links, inv_mass, rest):
    """hclStandardLinkConstraintSetMx batches (4 links, no particle twice) and singles."""
    todo = list(links)
    batches, singles = [], []
    while todo:
        used, batch, rest_todo = set(), [], []
        for l in todo:
            if len(batch) < 4 and l[0] not in used and l[1] not in used:
                batch.append(l)
                used |= set(l)
            else:
                rest_todo.append(l)
        todo = rest_todo
        if len(batch) < 4:
            singles += batch
            continue
        b = {"restLengths": [], "stiffnessesA": [], "stiffnessesB": [], "particlesA": [], "particlesB": []}
        for i, j in batch:
            wa, wb = inv_mass[i], inv_mass[j]
            b["restLengths"].append(rest(i, j))
            b["stiffnessesA"].append(wa / (wa + wb))
            b["stiffnessesB"].append(-wb / (wa + wb))
            b["particlesA"].append(i)
            b["particlesB"].append(j)
        batches.append(b)
    singles = [{"restLength": rest(i, j), "stiffnessA": inv_mass[i] / (inv_mass[i] + inv_mass[j]),
                "stiffnessB": -inv_mass[j] / (inv_mass[i] + inv_mass[j]), "particleA": i, "particleB": j}
               for i, j in singles]
    return batches, singles


def _stretch_batches(stretch):
    out = []
    for k in range(0, len(stretch), 4):
        part = stretch[k:k + 4]
        while len(part) < 4:                          # pad with a copy of the last link (same effect twice)
            part = part + [part[-1]]
        out.append({"restLengths": [p[2] for p in part], "stiffnesses": [1.0] * 4,
                    "particlesA": [p[0] for p in part], "particlesB": [p[1] for p in part]})
    return out


def _capsule(c: Capsule) -> Dict:
    d = np.asarray(c.end, float) - np.asarray(c.start, float)
    ln2 = float(d @ d)
    if ln2 < 1e-10:
        raise ClothBuildError(f"collider {c.name}: start and end coincide (use a short capsule)")
    return {"sizeAndFlags": 0, "refCount": 0, "type": 0, "start": [*map(float, c.start), 0.0],
            "end": [*map(float, c.end), 0.0], "dir": [*map(float, d / math.sqrt(ln2)), 0.0], "radius": float(c.radius),
            "capLenSqrdInv": 1.0 / ln2, "$class": "hclCapsuleShape"}


def build_cloth(template_root: Dict, bones: List[ChainBone], host_of_root: Dict[str, str], colliders: List[Capsule],
                s: Settings = Settings(), keep_template_colliders: bool = True) -> Tuple[Dict, Rig]:
    """(root objects {"hclClothData", "hkaSkeleton"}, rig) for the chains; write with hktagwrite.write(template_blob,
    hktagwrite.container([...]))."""
    t_cd, t_sk = template_root["hclClothData"], template_root["hkaSkeleton"]
    t_names = [b["name"] for b in t_sk["bones"]]
    t_world = skeleton_world(t_sk)
    sk = human_skeleton(template_root)
    names = [b["name"] for b in sk["bones"]]
    world = skeleton_world(sk)
    for b in bones:
        if b.name in names:
            raise ClothBuildError(f"chain bone {b.name} is already a skeleton bone")
    rig = build_rig(bones, host_of_root, s)
    if len(rig.fixed) == len(rig.positions):
        raise ClothBuildError("nothing to simulate")
    # skeleton: human bones, then the chain bones parents first
    index = {n: i for i, n in enumerate(names)}
    pending = list(bones)
    while pending:
        progressed = False
        for b in list(pending):
            if b.parent in index:
                p = index[b.parent]
                local = np.linalg.inv(world[p]) @ b.world
                r = local[:3, :3]
                sc = np.linalg.norm(r, axis=0)
                q = matrix_quat(r / sc)
                sk["parentIndices"].append(p)
                sk["bones"].append({"name": b.name, "lockTranslation": False})
                sk["referencePose"].append({"translation": [*map(float, local[:3, 3]), 0.0], "rotation": list(q),
                                            "scale": [*map(float, sc), 0.0]})
                world.append(world[p] @ local)
                index[b.name] = len(names)
                names.append(b.name)
                pending.remove(b)
                progressed = True
        if not progressed:
            raise ClothBuildError("chain bones with unknown parents: " + ", ".join(b.name for b in pending))
    nb = len(names)

    cd = copy.deepcopy(t_cd)
    cd["name"] = s.name
    sim = cd["simClothDatas"][0]
    n = len(rig.positions)
    fixed = set(rig.fixed)
    inv_mass = [0.0 if i in fixed else 1.0 / max(rig.masses[i], 1e-4) for i in range(n)]
    sim["name"] = "Sim"
    sim["simulationInfo"] = {"gravity": [0.0, 0.0, s.gravity, 0.0], "globalDampingPerSecond": s.damping}
    sim["particleDatas"] = [{"mass": 0.0 if i in fixed else rig.masses[i], "invMass": inv_mass[i],
                             "radius": s.radius, "friction": s.friction} for i in range(n)]
    sim["fixedParticles"] = list(rig.fixed)
    sim["doNormals"] = False
    sim["simClothPoses"] = [{"sizeAndFlags": 0, "refCount": 0, "name": "DefaultClothPose",
                             "positions": [[*map(float, p), 1.0] for p in rig.positions], "$class": "hclSimClothPose"}]
    rest = lambda i, j: float(np.linalg.norm(rig.positions[i] - rig.positions[j]))
    batches, singles = _std_links(rig.links, inv_mass, rest)
    kind = template_root.get("$kind") or template_kind(template_root)
    sets = [{"sizeAndFlags": 0, "refCount": 0, "name": "StandardLink Constraint", "constraintId": {"value": 0},
             "type": 0, "batches": batches, "singles": singles, "$class": "hclStandardLinkConstraintSetMx"}]
    if kind["stretch"] == "hclStretchLinkConstraintSetMx":
        sets.append({"sizeAndFlags": 0, "refCount": 0, "name": "StretchLink Constraint",
                     "constraintId": {"value": len(sets)}, "type": 0, "batches": _stretch_batches(rig.stretch),
                     "singles": [], "$class": "hclStretchLinkConstraintSetMx"})
    elif kind["stretch"] == "hclStretchLinkConstraintSet":
        sets.append({"sizeAndFlags": 0, "refCount": 0, "name": "StretchLink Constraint",
                     "constraintId": {"value": len(sets)}, "type": 0,
                     "links": [{"particleA": a_, "particleB": b_, "restLength": float(r_), "stiffness": 1.0}
                               for a_, b_, r_ in rig.stretch], "$class": "hclStretchLinkConstraintSet"})
    if kind["range"]:
        sets.append({"sizeAndFlags": 0, "refCount": 0, "name": "LocalRange Constraint",
                     "constraintId": {"value": len(sets)}, "type": 0,
                     "localConstraints": [{"particleIndex": p, "referenceVertex": p, "maximumDistance": float(d),
                                           "maxNormalDistance": 3.4028200183756560e38,
                                           "minNormalDistance": -3.4028200183756560e38} for p, d in rig.ranges],
                     "localStiffnessConstraints": [], "referenceMeshBufferIdx": 0, "stiffness": 1.0, "shapeType": 0,
                     "applyNormalComponent": False, "$class": RANGE_TYPE})
    sim["staticConstraintSets"] = sets
    sim["antiPinchConstraintSets"] = []

    # colliders: the template's (on human bones, remapped) and the given capsules
    cols, col_bones, offsets = [], [], []
    if keep_template_colliders:
        cm = t_cd["simClothDatas"][0]["collidableTransformMap"]
        for c, ti, off in zip(t_cd["simClothDatas"][0]["perInstanceCollidables"], cm["transformIndices"],
                              cm["offsets"]):
            if t_names[ti] in index and c["shape"].get("$class") == "hclCapsuleShape":
                cols.append(copy.deepcopy(c))
                col_bones.append(index[t_names[ti]])
                offsets.append(list(off))
    for c in colliders:
        if c.bone not in index:
            raise ClothBuildError(f"collider {c.name}: no bone {c.bone}")
        bi = index[c.bone]
        w = world[bi]
        rest_t = np.eye(4)
        rest_t[:3, 3] = w[:3, 3]
        off = np.eye(4)
        off[:3, :3] = w[:3, :3].T
        cols.append({"sizeAndFlags": 0, "refCount": 0, "transform": mat4_values(rest_t),
                     "linearVelocity": [0.0] * 4, "angularVelocity": [0.0] * 4, "userData": 0,
                     "shape": _capsule(c), "name": c.name, "pinchDetectionRadius": 0.01,
                     "pinchDetectionPriority": 0, "pinchDetectionEnabled": False,
                     "virtualCollisionPointCollisionEnabled": False, "enabled": True, "$class": "hclCollidable"})
        col_bones.append(bi)
        offsets.append(mat4_values(off))
    if len(cols) > 32:
        raise ClothBuildError("more than 32 colliders (collision masks are 32 bits)")
    sim["perInstanceCollidables"] = cols
    sim["collidableTransformMap"] = {"transformSetIndex": 0, "transformIndices": col_bones, "offsets": offsets}
    sim["collidablePinchingDatas"] = [{"pinchDetectionEnabled": False, "pinchDetectionPriority": 0,
                                       "pinchDetectionRadius": 0.01} for _ in cols]
    every = (1 << len(cols)) - 1
    sim["staticCollisionMasks"] = [0 if i in fixed else every for i in range(n)]
    sim["perParticlePinchDetectionEnabledFlags"] = [False] * n
    sim["maxParticleRadius"] = s.radius
    sim["totalMass"] = float(sum(rig.masses))
    tri = [i for t in rig.triangles for i in t]
    sim["triangleIndices"] = tri
    sim["triangleFlips"] = [0] * ((len(rig.triangles) + 7) // 8)
    sim["minPinchedParticleIndex"] = sim["maxPinchedParticleIndex"] = 0
    tm = sim.get("transferMotionData")
    if isinstance(tm, dict):
        host0 = rig.host[rig.fixed[0]] if rig.fixed else "C_Head"
        tm["transformIndex"] = index.get(host0, 0)
    vc = sim.get("virtualCollisionPointsData")
    if isinstance(vc, dict):
        for k, v in vc.items():
            if isinstance(v, list):
                vc[k] = []
        vc["numVCPoints"] = vc["numLandscapeVCPoints"] = 0
    sim["numLandscapeCollidableParticles"] = 0
    sim["landscapeCollisionEnabled"] = False

    # buffers: scratch = one vertex per particle (the skinned rest pose), sim buffer = the particles
    scratch, simbuf = cd["bufferDefinitions"]
    for b in (scratch, simbuf):
        b["meshName"] = "S2S_SimMesh"
    scratch["numVertices"] = n
    simbuf["numVertices"], simbuf["numTriangles"] = n, len(rig.triangles)
    cd["transformSetDefinitions"][0]["numTransforms"] = nb
    cd["transformSetDefinitions"][0]["name"] = "S2S TransformSet"

    skin, move, simop, deform = cd["operators"][:4]
    cd["operators"] = [skin, move, simop, deform]          # extra template operators (e.g. a gather) dropped
    hosts = sorted({index[h] for h in rig.host})
    sub = {b: k for k, b in enumerate(hosts)}
    object_space = skin["$class"] == "hclObjectSpaceSkinPNOperator"
    blocks, local = [], []
    for k in range(0, n, 16):
        verts = list(range(k, min(k + 16, n)))
        verts += [verts[-1]] * (16 - len(verts))
        blocks.append({"vertexIndices": verts, "boneIndices": [sub[index[rig.host[v]]] for v in verts]})
        pts, nrm = [], []
        for v in verts:
            if object_space:                               # skin mesh space = model space, boneFromSkinMesh = inv
                pts.append({"values": pack_position(rig.positions[v])})
            else:
                w = world[index[rig.host[v]]]
                lp = np.linalg.inv(w) @ np.array([*rig.positions[v], 1.0])
                pts.append([float(lp[0]), float(lp[1]), float(lp[2]), 1.0])
            nrm.append({"values": pack_vector3([0.0, 0.0, 1.0])})
        local.append({"localPosition": pts, "localNormal": nrm})
    skin["transformSubset"] = hosts
    deformer = {"fourBlendEntries": [], "threeBlendEntries": [], "twoBlendEntries": [],
                "oneBlendEntries": blocks, "controlBytes": [3] * len(blocks),
                "startVertexIndex": 0, "endVertexIndex": n - 1, "partialWrite": False}
    if object_space:
        deformer.update(eightBlendEntries=[], sevenBlendEntries=[], sixBlendEntries=[], fiveBlendEntries=[])
        skin["objectSpaceDeformer"] = deformer
        skin["boneFromSkinMeshTransforms"] = [mat4_values(np.linalg.inv(world[b])) for b in hosts]
    else:
        skin["boneSpaceDeformer"] = deformer
    skin["localPNs"] = local
    skin["localUnpackedPNs"] = []
    move["vertexParticlePairs"] = [{"vertexIndex": p, "particleIndex": p} for p in rig.fixed]
    cfg = simop["simulateOpConfigs"][0]
    ids = list(range(len(sets)))
    if kind["range"]:                                    # local range first, as the game's hairs
        ids = ids[-1:] + ids[:-1]
    cfg["constraintExecution"] = ids + [-1]
    cfg["instanceCollidablesUsed"] = []
    cfg["useAllInstanceCollidables"] = True
    pairs, locs = [], []
    for name, t in rig.driven:
        bi = index[name]
        v = [rig.positions[i] for i in rig.triangles[t]]
        f = triangle_frame(*v)
        pairs.append({"boneOffset": 64 * bi, "triangleOffset": 6 * t})
        locs.append(mat4_values(np.linalg.inv(f) @ world[bi]))
    deform["triangleBonePairs"] = pairs
    deform["localBoneTransforms"] = locs

    driven_idx = [index[nm] for nm, _ in rig.driven]
    zero = bitfield([], nb)

    def tracker(read=(), written=()):
        return {"read": bitfield(read, nb), "readBeforeWrite": bitfield(read, nb), "written": bitfield(written, nb)}

    def usage(flags, comps):
        return [{"transformSetIndex": 0, "transformSetUsage": {"perComponentFlags": list(flags),
                                                                "perComponentTransformTrackers": comps}}]
    empty = {"read": zero, "readBeforeWrite": zero, "written": zero}
    skin["usedTransformSets"] = usage((9, 0), [tracker(hosts), copy.deepcopy(empty)])
    simop["usedTransformSets"] = usage((9, 9) if col_bones else (0, 0),
                                       [tracker(sorted(set(col_bones))), tracker(sorted(set(col_bones)))])
    deform["usedTransformSets"] = usage((2, 0), [tracker((), driven_idx), copy.deepcopy(empty)])
    read_all = sorted(set(hosts) | set(col_bones))
    for st in cd["clothStateDatas"]:
        st["operators"] = [0, 1, 2, 3]
        st["usedTransformSets"] = usage((11, 9 if col_bones else 0),
                                        [tracker(read_all, driven_idx), tracker(sorted(set(col_bones)))])
        st["usedSimCloths"] = [0]
        g = st["dependencyGraph"]
        g["branches"] = [{"branchId": 0, "stateOperatorIndices": [0, 1, 2, 3], "parentBranches": [],
                          "childBranches": []}]
        g["rootBranchIds"] = [0]
        g["children"] = [[1], [2], [3], []]
        g["parents"] = [[], [0], [1], [2]]
    cd["stateTransitions"] = []
    cd["actions"] = []
    sk["name"] = "S2S"
    rig.report.update(skeleton_bones=nb, chain_bones=len(bones), colliders=[c["name"] for c in cols])
    rig.report["template_kind"] = kind
    return {"hclClothData": cd, "hkaSkeleton": sk}, rig


def write(template_blob: bytes, root: Dict) -> bytes:
    """The cloth tagfile (BSClothExtraData payload)."""
    cd, sk = root["hclClothData"], root["hkaSkeleton"]
    cd.setdefault("$class", "hclClothData")
    sk.setdefault("$class", "hkaSkeleton")
    return hktagwrite.write(template_blob, hktagwrite.container([("hclClothData", cd), ("hkaSkeleton", sk)]))


def skin_rest(skin: Dict, world: List[np.ndarray]) -> Dict[int, Tuple[np.ndarray, list]]:
    """{scratch vertex: (rest position, [(bone, weight)])} of a skin operator of either kind (one-bone blocks and
    blended ones, in control-byte order)."""
    kinds = {0: ("fourBlendEntries", 4), 1: ("threeBlendEntries", 3), 2: ("twoBlendEntries", 2),
             3: ("oneBlendEntries", 1)}
    obj = skin["$class"] == "hclObjectSpaceSkinPNOperator"
    d = skin["objectSpaceDeformer" if obj else "boneSpaceDeformer"]
    mats = [np.array(m, float).reshape(4, 4).T for m in skin.get("boneFromSkinMeshTransforms", [])]
    used = {k: 0 for k in kinds}
    out = {}
    for bi, c in enumerate(d["controlBytes"]):
        name, nb = kinds[c]
        blk = d[name][used[c]]
        used[c] += 1
        pn = skin["localPNs"][bi]

        def local(i):
            raw = pn["localPosition"][i]
            return unpack_vector3(raw["values"]) if isinstance(raw, dict) else np.array(raw[:4], float)
        for k, v in enumerate(blk["vertexIndices"]):
            if v in out:
                continue
            p = np.zeros(3)
            if nb == 1:
                bw = [(blk["boneIndices"][k], 1.0)]
                lp = local(k)[:3]
                bone = skin["transformSubset"][bw[0][0]]
                m = world[bone] @ mats[bw[0][0]] if obj else world[bone]
                p = m[:3, :3] @ lp + m[:3, 3]
            elif obj:                                 # object space: one local position, u8 weights
                bw = [(blk["boneIndices"][k * nb + j], blk["boneWeights"][k * nb + j] / 255.0) for j in range(nb)]
                lp = local(k)[:3]
                for b, w in bw:
                    m = world[skin["transformSubset"][b]] @ mats[b]
                    p += w * (m[:3, :3] @ lp + m[:3, 3])
            else:                                     # bone space: a weighted local point per bone (w = weight)
                bw = []
                for j in range(nb):
                    b = blk["boneIndices"][k * nb + j]
                    lp = local(k * nb + j)
                    m = world[skin["transformSubset"][b]]
                    p += m[:3, :3] @ lp[:3] + m[:3, 3] * lp[3]
                    bw.append((b, float(lp[3])))
            out[v] = (p, [(skin["transformSubset"][b], w) for b, w in bw])
    return out


def verify(blob: bytes) -> Dict:
    """Re-read a written cloth and check it (verify_root)."""
    return verify_root(hktagfile.Tagfile(blob).root())


def verify_root(root: Dict) -> Dict:
    """Check cloth objects against the rules above: every chain bone's rest pose comes back from its triangle, pinned
    particles come back from the skin, link rest lengths match the pose, batches hold distinct particles. Returns the
    worst errors (metres / unitless). On the game's and mods' own hairs (Eris, OC): bones 2e-4, pins 5e-5 at most."""
    cd, sk = root["hclClothData"], root["hkaSkeleton"]
    world = skeleton_world(sk)
    sim = cd["simClothDatas"][0]
    P = np.array([p[:3] for p in sim["simClothPoses"][0]["positions"]])
    T = np.array(sim["triangleIndices"]).reshape(-1, 3)
    skin, move, _simop, deform = cd["operators"][:4]
    bone_err = 0.0
    for pr, lv in zip(deform["triangleBonePairs"], deform["localBoneTransforms"]):
        b, t = pr["boneOffset"] // 64, pr["triangleOffset"] // 6
        got = triangle_frame(*P[T[t]]) @ np.array(lv, float).reshape(4, 4).T
        bone_err = max(bone_err, float(np.abs(got - world[b]).max()))
    pin_err = 0.0
    pinned = {pr["vertexIndex"]: pr["particleIndex"] for pr in move["vertexParticlePairs"]}
    for v, (lp, bones) in skin_rest(skin, world).items():
        if v in pinned:
            pin_err = max(pin_err, float(np.linalg.norm(lp - P[pinned[v]])))
    link_err, shared = 0.0, 0
    for cs in sim["staticConstraintSets"]:
        if cs["$class"] == "hclStandardLinkConstraintSetMx":
            for b in cs["batches"]:
                if len(set(b["particlesA"] + b["particlesB"])) < 8:
                    shared += 1
                for i, j, r in zip(b["particlesA"], b["particlesB"], b["restLengths"]):
                    link_err = max(link_err, abs(float(np.linalg.norm(P[i] - P[j])) - r))
    return {"bone_from_triangle": bone_err, "pinned_from_skin": pin_err, "link_rest": link_err,
            "batches_sharing_particles": shared, "particles": len(P), "triangles": len(T),
            "driven_bones": len(deform["triangleBonePairs"]), "skeleton_bones": len(sk["bones"])}
