"""Starfield Havok cloth (BSClothExtraData) read-only summary: what is simulated, what is pinned, which bones the
simulation drives, constraints and colliders. For the hair / cape physics plan in docs/armor/animation-port.md.

Verified 2026-10-19 on owner uploads (Nexus 14496 OC Hairs, 14478 OC Agent outfit, 16118 Eris Hairstyles):
* BSClothExtraData block = u32 size + a Havok tagfile (TAG0, SDK "20190200"); OC Hairs also ships the same tagfile
  as a loose .hkx next to the NIF (the add-on's export). Root container holds hclClothData + hkaSkeleton.
* The hkaSkeleton is the full Starfield human skeleton (Root, HumanExportRoot, ... CharacterController) with the
  mesh's own extra bones inserted under their host (OC ponytail: BangBoneL_0_1 / PonytailBone_33_34 under C_Head).
* Bone-driving setup ("Character Bone Deforming Clothing", OC ponytail): operators Skin Simulation
  (hclObjectSpaceSkinPNOperator: skins the hidden sim mesh to C_Head + the hair bones), Move Particles
  (hclMoveParticlesOperator: pinned particles follow their skinned vertices), Sim (hclSimulateOperator), Deform
  (hclSimpleMeshBoneDeformOperator: each driven bone follows one sim-mesh triangle; triangleBonePairs boneOffset =
  64 x bone index, triangleOffset = 6 x triangle index (u16 index bytes); localBoneTransforms = bone in the
  triangle's frame), VertGather. The visible hair is ordinary skinning to those bones.
* hclSimClothData: particleDatas (mass, invMass, radius, friction), fixedParticles, simClothPoses, constraint sets
  (hclStandardLinkConstraintSetMx: batches of 4 links rest length + stiffness; hclStretchLinkConstraintSet;
  hclVolumeConstraintMx; others possible), perInstanceCollidables (hclCapsuleShape, hclConvexGeometryShape ...)
  with collidableTransformMap = the skeleton bones they ride on. Units are metres; gravity -9.81 z.
"""
from collections import Counter
from typing import Dict, List

from . import hktagfile


class ClothError(ValueError):
    pass


def payload(block: bytes) -> bytes:
    """The tagfile inside a BSClothExtraData block (u32 size prefix)."""
    if len(block) < 12 or block[8:12] != b"TAG0":
        raise ClothError("BSClothExtraData does not hold a TAG0 tagfile")
    n = int.from_bytes(block[:4], "little")
    return block[4:4 + n]


def _rng(vals):
    vals = [round(v, 4) for v in vals]
    return [min(vals), max(vals)] if vals else None


def summary(tagfile_blob: bytes) -> Dict:
    tf = hktagfile.Tagfile(tagfile_blob)
    return summarize(tf.root(), tf.sdk)


def summarize(root: Dict, sdk: str = "") -> Dict:
    """Summary from decoded root objects ({"hclClothData": ..., "hkaSkeleton": ...}, see hktagfile.root)."""
    cd, sk = root.get("hclClothData"), root.get("hkaSkeleton")
    if cd is None:
        raise ClothError("no hclClothData in the tagfile")
    bones = [b["name"] for b in (sk or {}).get("bones", [])]
    parents = (sk or {}).get("parentIndices", [])

    def bone(i):
        return bones[i] if 0 <= i < len(bones) else f"#{i}"

    ops = [{"class": o.get("$class"), "name": o.get("name")} for o in cd.get("operators", [])]
    driven, skinned = [], []
    for o in cd.get("operators", []):
        if "triangleBonePairs" in o:
            driven += [bone(p["boneOffset"] // 64) for p in o["triangleBonePairs"]]
        if "transformSubset" in o:
            skinned += [bone(i) for i in o["transformSubset"]]
    sims = []
    for s in cd.get("simClothDatas", []):
        pd = s.get("particleDatas", [])
        sets = []
        for c in s.get("staticConstraintSets", []):
            # generic over set classes: element counts per list field, and every value under a *stiff* key
            lists = {k: len(v) for k, v in c.items() if isinstance(v, list) and k != "$class"}
            stiff = []

            def grab(v, key=""):
                if isinstance(v, dict):
                    for k, x in v.items():
                        grab(x, k)
                elif isinstance(v, list):
                    for x in v:
                        grab(x, key)
                elif isinstance(v, float) and "stiff" in key.lower():
                    stiff.append(v)
            grab(c)
            sets.append({"class": c.get("$class"), "name": c.get("name"), "lists": lists, "stiffness": _rng(stiff)})
        cmap = s.get("collidableTransformMap", {})
        on = [bone(i) for i in cmap.get("transformIndices", [])]
        cols = [{"name": c.get("name"), "shape": (c.get("shape") or {}).get("$class"),
                 "bone": on[i] if i < len(on) else None,
                 "radius": round((c.get("shape") or {}).get("radius", 0) or 0, 4) or None}
                for i, c in enumerate(s.get("perInstanceCollidables", []))]
        info = s.get("simulationInfo", {})
        sims.append({"name": s.get("name"), "particles": len(pd), "fixed": len(s.get("fixedParticles", [])),
                     "mass": _rng([p["mass"] for p in pd]), "radius": _rng([p["radius"] for p in pd]),
                     "total_mass": round(s.get("totalMass", 0), 4),
                     "gravity": [round(g, 3) for g in info.get("gravity", [])][:3],
                     "damping_per_second": round(info.get("globalDampingPerSecond", 0), 4),
                     "triangles": len(s.get("triangleIndices", [])) // 3, "constraint_sets": sets,
                     "collidables": cols})
    extra = []
    if driven or skinned:
        for name in dict.fromkeys(driven + skinned):
            if name in bones:
                i = bones.index(name)
                extra.append({"bone": name, "parent": bone(parents[i]) if i < len(parents) else None})
    return {"name": cd.get("name"), "sdk": sdk, "skeleton_bones": len(bones), "operators": ops,
            "mode": "bones" if driven else "mesh", "driven_bones": driven, "skinned_to": skinned,
            "bone_parents": extra, "sims": sims, "buffers": [(b.get("meshName"), b.get("bufferName"),
                                                               b.get("numVertices"))
                                                              for b in cd.get("bufferDefinitions", [])]}


def chains(s: Dict) -> List[Dict]:
    """Driven bones grouped by the non-driven bone they hang from: [{"host", "bones", "depth"}]."""
    par = {b["bone"]: b["parent"] for b in s["bone_parents"]}
    driven = set(s["driven_bones"])
    groups: Dict[str, List[str]] = {}
    for b in s["driven_bones"]:
        host, depth, n = b, 0, b
        while n in driven and depth < 256:
            host, n, depth = n, par.get(n), depth + 1
        groups.setdefault(n or "?", []).append(b)
    out = []
    for host, bs in groups.items():
        def depth(b):
            d = 0
            while b in driven and d < 256:
                b, d = par.get(b), d + 1
            return d
        out.append({"host": host, "bones": len(bs), "depth": max(depth(b) for b in bs)})
    return out


def stats(summaries: List[Dict]) -> Dict:
    c = Counter()
    for s in summaries:
        c["mode:" + s["mode"]] += 1
        for o in s["operators"]:
            c["op:" + str(o["class"])] += 1
        for sim in s["sims"]:
            for cs in sim["constraint_sets"]:
                c["constraint:" + str(cs["class"])] += 1
            for col in sim["collidables"]:
                c["collider:" + str(col["shape"])] += 1
    return dict(sorted(c.items()))
