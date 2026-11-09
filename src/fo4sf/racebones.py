"""Race proportions from Skyrim skeletons (XPMSE-style "CME" nodes, as Racial Body Morphs uses) onto Starfield's.

How the Skyrim side works (verified on Racial Body Morphs - Extreme, Nexus 65047, 2026-11-09): every race and sex has
its own skeleton.nif (RACE ANAM points at it). Between a bone and its child bone XPMSE inserts helper nodes the
animations never touch (e.g. NPC Neck -> "CME Neck [Neck]" -> "CME Neck [Neck]" -> NPC Head); the mod gives the inner
one a scale and / or a translation (Orc male: neck 0.9, so the head is smaller; upper body 1.106 between COM and
Spine; High Elf male: the calf moved 6 units down the thigh, longer legs). Everything skinned to the bones below
follows, bodies and armour alike, so no clothes are remade.

Starfield's human skeleton has no such helpers (probe, 2026-11-09: every node between Root and the animated bones is a
rig bone; the non-rig nodes are leaves: CalfMass, Deltoid, Butt ... the chargen bone modifiers). So the same effect
needs helper nodes inserted the way XPMSE did (insert_helpers); whether Starfield's animation keeps a non-rig parent's
scale is the in-game question.
"""
import struct
from typing import Dict, List

from . import nif, skeletonmap

UNIT = 1.0 / 70.0                        # metres per Skyrim unit
HELPER = "S2S_RB_{}"                     # inserted helper node above a Starfield bone


def _names(f: nif.NifFile) -> Dict[int, str]:
    out = {}
    for i in range(len(f.blocks)):
        if f.type_of(i).endswith("Node"):
            si, = struct.unpack_from("<i", f.blocks[i], 0)
            out[i] = f.strings[si].decode("latin-1") if 0 <= si < len(f.strings) else ""
    return out


def _parents(f: nif.NifFile, nodes) -> Dict[int, int]:
    par = {}
    for i in nodes:
        for c in nif.node_children(f, i):
            par.setdefault(c, i)
    return par


def is_bone(name: str) -> bool:
    return name.startswith("NPC ")


def _identity(tr, tol=1e-4) -> bool:
    t, r, s = tr
    return (abs(s - 1.0) < tol and max(abs(x) for x in t) < tol
            and max(abs(r[k] - (1.0 if k in (0, 4, 8) else 0.0)) for k in range(9)) < tol)


def cme_values(nif_bytes: bytes) -> List[dict]:
    """[{"parent", "child", "scale", "offset_units", "nodes"}] for every Skyrim bone whose chain up to the nearest bone
    above it passes helper (non-bone) nodes that together are not the identity: their composed local transform, in
    the parent bone's frame, game units."""
    f = nif.parse(nif_bytes)
    name = _names(f)
    par = _parents(f, name)
    out = []
    for i, n in name.items():
        if not is_bone(n):
            continue
        chain, j = [], par.get(i)
        while j is not None and j in name and not is_bone(name[j]):
            chain.append(j)
            j = par.get(j)
        if not chain or j is None or j not in name:
            continue
        tr = ((0.0, 0.0, 0.0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0)
        for k in reversed(chain):                            # top (next to the parent bone) down to the child
            tr = nif._compose(tr, nif._av_transform(f.blocks[k]))
        if _identity(tr):
            continue
        out.append({"parent": name[j], "child": n, "scale": round(tr[2], 4),
                    "offset_units": [round(x, 3) for x in tr[0]],
                    "rotated": max(abs(tr[1][k] - (1.0 if k in (0, 4, 8) else 0.0)) for k in range(9)) > 1e-4,
                    "nodes": [name[k] or f"<unnamed {k}>" for k in reversed(chain)]})
    return out


def world_rotations(nif_bytes: bytes) -> Dict[str, tuple]:
    """{node name: (world row-major rotation, world scale)} of a skeleton NIF (first node of each name)."""
    f = nif.parse(nif_bytes)
    w = nif.world_transforms(f)
    out = {}
    for i, n in _names(f).items():
        if n and n not in out:
            t, r, s = w(i)
            out[n] = (r, s)
    return out


def _mat_t_vec(r, v):                                       # R^T v, R row-major
    return [sum(r[3 * k + a] * v[k] for k in range(3)) for a in range(3)]


def _mat_vec(r, v):
    return [sum(r[3 * a + k] * v[k] for k in range(3)) for a in range(3)]


def to_starfield(rows, sky_rot: Dict[str, tuple], sf_rot: Dict[str, tuple], sf_parent: Dict[str, str]):
    """(helpers, notes): per Starfield bone the helper to insert above it, {"bone", "nif_parent", "scale", "offset_m"
    (in the NIF parent's frame), "from"}. The Skyrim child bone maps to the Starfield bone (skeletonmap, the first of a
    split); the offset goes Skyrim parent frame -> character space -> the Starfield NIF parent's frame (both games: Z up,
    +Y forward, +X the character's left side, checked on hands, feet and head). Two rows on one bone: scales multiply,
    offsets add."""
    helpers, notes = {}, []
    for r in rows:
        sf = skeletonmap.starfield_of(r["child"])
        if not sf:
            notes.append(f"{r['child']}: no Starfield bone (left out)")
            continue
        bone = sf[0][0]
        if bone not in sf_parent:
            notes.append(f"{r['child']} -> {bone}: not in the Starfield skeleton (left out)")
            continue
        p_sky = sky_rot.get(r["parent"])
        p_sf = sf_rot.get(sf_parent[bone])
        if p_sky is None or p_sf is None:
            notes.append(f"{r['child']}: parent frame unknown (left out)")
            continue
        world = _mat_vec(p_sky[0], r["offset_units"])
        local = [x * UNIT / (p_sf[1] or 1.0) for x in _mat_t_vec(p_sf[0], world)]
        want = skeletonmap.starfield_of(r["parent"])
        if want and want[0][0] != sf_parent[bone]:
            notes.append(f"{r['child']}: Skyrim parent {r['parent']} -> {want[0][0]}, Starfield {bone}'s parent is "
                         f"{sf_parent[bone]}: helper above {bone}")
        if r.get("rotated"):
            notes.append(f"{r['child']}: helper rotation left out (scale / offset only)")
        h = helpers.get(bone)
        if h is None:
            helpers[bone] = {"bone": bone, "nif_parent": sf_parent[bone], "scale": r["scale"],
                             "offset_m": [round(x, 4) for x in local], "from": [r["child"]]}
        else:
            h["scale"] = round(h["scale"] * r["scale"], 4)
            h["offset_m"] = [round(a + b, 4) for a, b in zip(h["offset_m"], local)]
            h["from"].append(r["child"])
    return list(helpers.values()), notes


def nif_parents(nif_bytes: bytes) -> Dict[str, str]:
    """{node name: parent node name} of a skeleton NIF."""
    f = nif.parse(nif_bytes)
    name = _names(f)
    par = _parents(f, name)
    return {n: name[par[i]] for i, n in name.items() if n and i in par and par[i] in name}


def _children_at(blk: bytes) -> int:
    _, nextra = struct.unpack_from("<iI", blk, 0)
    return 8 + 4 * nextra + 8 + 52 + 4                     # NiAVObject fields + collision ref, then the count


def insert_helpers(nif_bytes: bytes, helpers) -> bytes:
    """The skeleton with one NiNode HELPER.format(bone) between each helper's bone and its parent: local translation
    offset_m, scale `scale`, identity rotation (Starfield NiNode layout, as sfnif.merge_under_node writes); the bone's
    own local transform unchanged, so at scale 1 / offset 0 nothing moves."""
    f = nif.parse(nif_bytes)
    name = _names(f)
    by = {}
    for i, n in name.items():
        by.setdefault(n, i)
    par = _parents(f, name)
    for h in helpers:
        i = by.get(h["bone"])
        if i is None or i not in par:
            raise ValueError(f"{h['bone']}: not in the skeleton")
        p = par[i]
        hid = len(f.blocks)
        t = h.get("offset_m") or (0.0, 0.0, 0.0)
        f.add_block("NiNode", struct.pack("<iIiI", f.string_index(HELPER.format(h["bone"]).encode()), 0, -1, 0xE)
                    + struct.pack("<3f9ff", *t, 1, 0, 0, 0, 1, 0, 0, 0, 1, float(h["scale"]))
                    + struct.pack("<iI", -1, 1) + struct.pack("<i", i))
        blk = f.blocks[p]
        at = _children_at(blk)
        n, = struct.unpack_from("<I", blk, at)
        kids = [hid if c == i else c for c in struct.unpack_from(f"<{n}i", blk, at + 4)]
        f.blocks[p] = blk[:at + 4] + struct.pack(f"<{n}i", *kids) + blk[at + 4 + 4 * n:]
        par[i] = hid
    return nif.serialize(f)
