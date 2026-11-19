"""Children's own hair, taken from their FaceGen head (docs/npc/children-mods.md, step 3; 2026-11-19).

Why from the FaceGen NIF: Realistic RS Children's hair head parts point into KS Hairdos (`KS Hairdo's\\*.nif`), which
the mod does not ship, but the Creation Kit bakes every head part into the child's FaceGen NIF as a shape named after
the part's EditorID (verified on the mod files: Frodnar's 0ChainReactionDUPLICATE001 / ...HLDUPLICATE001 /
0_HAIRLINE_Male_Human_CurlyScalpDUPLICATE002, Dorthe's 0MellowDUPLICATE001 ...), already shaped for the child's own
head and in the same model space as the FaceGen face (hair z 115..133 units over a face at 110..132).

So a child's hair is: the FaceGen NIF's shapes named after its hair head part and that part's extra parts, placed
with the child's own face alignment (the scale-and-shift that put its FaceGen face on Starfield's child head:
face_fit.head_alignment / facefit.align_to_local), then the looks-menu hair pipeline (scripts/npc/skyrim_hairs.py
build_part with the vanilla Skyrim hairs' settings: follow the skull difference, one copy of KS's two-pass shapes,
cards outward, pushed out of the head, Starfield's hair shader, _facebones twin) against the child's own baked head
and Starfield's child skeleton, written as a head part of ours copied from the template child's own hair.

The textures are still KS Hairdos' (`textures\\ks hairdo's\\...`; Realistic RS Children ships only 5 of them): a
child whose hair textures are in no archive / folder of the load order is reported and keeps the template's hair.
The hair colour is the NPC's Skyrim one matched to a Starfield hair colour name (as the adults' --hairs-plugin hair).
"""
import argparse
import os
import struct
import types
from typing import Dict, List, Optional

import numpy as np

HAIR = 3
CHILD_SKELETON = "meshes/actors/child/characterassets/skeleton.nif"
OUT_DIR = "s2s/children/hair"
STAGING = "_staging_child_hair"


def hair_shape_names(npc: Dict, hdpt: Dict[int, Dict]) -> List[str]:
    """Lower-case EditorIDs of the NPC's hair head part (type 3) and its extra parts (followed, in order): the names
    of its hair shapes in its FaceGen NIF."""
    out: List[str] = []
    seen = set()

    def walk(fid):
        if fid in seen or fid not in hdpt:
            return
        seen.add(fid)
        p = hdpt[fid]
        if p.get("edid"):
            out.append(p["edid"].lower())
        for x in p.get("extra_parts") or []:
            walk(x)
    for fid in npc.get("head_parts") or []:
        p = hdpt.get(fid)
        if p and p.get("type") == HAIR:
            walk(fid)
            break
    return out


def facegen_hair_shapes(nif_bytes: bytes, names) -> List[Dict]:
    """[{name, vertices, textures}] of the FaceGen NIF's skinned shapes named in `names` (case-insensitive)."""
    from fo4sf import nif as nifmod, skyrimnif, skyrimskin
    want = {x.lower() for x in names}
    n = nifmod.parse(nif_bytes)
    out = []
    for s in skyrimskin.skinned_shapes(n):
        nm = (s.name or b"").decode("latin-1")
        if nm.lower() in want:
            tex = skyrimnif.texture_set(n, s.shader_ref) if s.shader_ref >= 0 else None
            out.append({"name": nm, "vertices": len(s.positions), "textures": [t for t in (tex or [])[:2] if t]})
    return out


def missing_textures(shapes: List[Dict], src) -> List[str]:
    """The diffuse textures of the shapes that `src` (the Skyrim side: .texture(path)) does not have."""
    miss = []
    for sh in shapes:
        for t in sh["textures"][:1]:
            if t and t not in miss and src.texture(t) is None:
                miss.append(t)
    return miss


def sky_to_starfield(ctx) -> np.ndarray:
    """4x4 Skyrim model space (units) -> Starfield child model space (m): the face alignment (ctx["al"]: Skyrim model
    -> the head's mesh-local frame) followed by the head node (local -> model). A scale and shift (align_to_local
    fits no rotation in model space); raises ValueError for a fit made without the model space (legacy)."""
    if not ctx.get("model_space"):
        raise ValueError("the child's face alignment is not in model space (legacy fit): no hair placement")
    s, R, t = ctx["al"][:3]
    A = np.eye(4)
    A[:3, :3] = float(s) * np.asarray(R, float)
    A[:3, 3] = np.asarray(t, float)
    M = np.asarray(ctx["head"].model_xf, float) @ A
    d = np.diag(M)[:3]
    off = M[:3, :3] - np.diag(d)
    if np.abs(off).max() > 1e-3 * np.abs(d).mean():
        raise ValueError("the face alignment turns the head (not a scale and shift): no hair placement")
    return M


def placement(nif_bytes: bytes, M: np.ndarray, sf_head_t) -> tuple:
    """(scale (3,), offset (3,)) for skyrimhair.convert, so its Placement puts a Skyrim model point p (units) at
    M's diagonal * p + M's shift: convert maps p to sf_head + offset + scale * (p * UNIT - anchor * UNIT), with
    anchor the NIF's head bone at skinning (skyrimhair.head_anchor)."""
    from fo4sf import nif as nifmod, skyrimhair
    n = nifmod.parse(nif_bytes)
    nodes, _parent = skyrimhair.node_worlds(n)
    anchor = skyrimhair.head_anchor(n, nodes)[:3, 3]
    d = np.diag(M)[:3]
    scale = d / skyrimhair.UNIT
    offset = M[:3, 3] + d * anchor - np.asarray(sf_head_t, float)
    return scale, offset


def child_world(skeleton_bytes: bytes) -> Dict[str, np.ndarray]:
    """{bone: rest world (m)} of Starfield's child skeleton; ValueError without C_Head."""
    from fo4sf import skyrimhair
    import npc_hair
    w = npc_hair.skeleton_world(skeleton_bytes)
    if skyrimhair.SF_HEAD not in w:
        raise ValueError(f"no {skyrimhair.SF_HEAD} in the child skeleton")
    return w


def shape_settings(starfield: str):
    """The hair shaping / material settings of the vanilla Skyrim hairs (skyrim_hairs.VANILLA_DEFAULTS: no hairline
    lift, volume or drape - the FaceGen hair was made for this child's head)."""
    import hair_pack
    import skyrim_hairs
    ap = argparse.ArgumentParser()
    hair_pack.add_shape_args(ap)
    ap.set_defaults(**skyrim_hairs.VANILLA_DEFAULTS)
    ctx = ap.parse_args([])
    ctx.starfield = starfield
    ctx.skyrim_data = None
    return ctx


def baked_surface(starfield: str, out: str, head_nif_rel: str):
    """(points, normals) in model space (m) of the child's own baked head as written under `out` (its NIF and
    .mesh files), or None."""
    import hair_pack

    def read(rel):
        for r in (rel, rel.lower()):
            p = os.path.join(out, *r.split("/"))
            if os.path.isfile(p):
                with open(p, "rb") as fh:
                    return fh.read()
        return None
    raw = read(head_nif_rel)
    got = hair_pack.game_mesh_of(starfield, raw, read=read) if raw is not None else None
    return None if got is None else (got[0], got[1])


class _OneMesh:
    """A stand-in Skyrim source for skyrim_hairs.build_part: every model read is the child's FaceGen NIF."""
    def __init__(self, data: bytes):
        self.data = data

    def mesh(self, _rel):
        return self.data


def build_child_hair(edid: str, female: bool, fg_bytes: bytes, fg_rel: str, names: List[str], ctx, fg_points,
                     sf_world, surface, fb, conv, staging: str, settings) -> Dict:
    """One child's hair converted into staging: skyrim_hairs.build_part on the FaceGen NIF's hair shapes. ctx:
    child_faces.child_setup's; fg_points: its FaceGen head in the same space as ctx["base"] (child_faces.
    facegen_points); surface: its baked head (baked_surface); fb: the template hair's _facebones template
    (hair_pack.facebones_template) or None. Returns build_part's row (ok, model, ...) plus the placement."""
    import hair_pack
    import skyrim_hairs
    from fo4sf import facefit, skyrimhair
    M = sky_to_starfield(ctx)
    scale, offset = placement(fg_bytes, M, sf_world[skyrimhair.SF_HEAD][:3, 3])
    hc = types.SimpleNamespace(**vars(settings))
    hc.head_scale, hc.head_offset = scale, offset
    hc.head_surface = surface
    hc.sky_head = facefit.apply4(M, np.asarray(fg_points, float)) if fg_points is not None else None
    if surface is None or not hc.conform:
        hc.head_surface = None
    if not hc.follow_head:
        hc.sky_head = None
    rep: Dict = {}
    hair_pack.setup_reference(hc, sf_world, rep, fb[4][0] if fb is not None and len(fb) > 4 and fb[4] is not None
                              else None)
    row = skyrim_hairs.build_part({"edid": f"S2S_ChildHair_{edid}", "plugin": "FaceGen"}, [fg_rel],
                                  _OneMesh(fg_bytes), conv, sf_world, hc, fb, staging,
                                  getattr(hc, "spread_face_bones", True), out_name=f"{OUT_DIR}/{edid.lower()}",
                                  keep_shapes=names)
    row["placement"] = {"scale_m_per_unit": round(float(np.mean(np.diag(M)[:3])), 6),
                        "shift_m": [round(float(v), 4) for v in M[:3, 3]]}
    row["template_reference"] = rep.get("vanilla_hair")
    return row


def child_tone_slots(sf_esm_records, read_texture, female: bool, decode) -> Dict:
    """{"slots": [slot, ...] lightest first, "group": ..., "medians": {...}} of Starfield's child body skin tone
    group of the sex (ChildRace's BSTT string naming an AVMD by TNAM / YNAM / EDID), by each slot's texture's median
    luminance (skintone.slot_ranks; vanilla's adult slots are not in brightness order, races.md 2026-11-11).
    sf_esm_records: [(type, header, subs, FormID)] holding RACE and AVMD; read_texture: path -> bytes; decode: DDS
    bytes -> RGBA. Raises KeyError / ValueError when something is missing."""
    from fo4sf import sfplugin, skintone

    def text(d):
        d = bytes(d)
        return d.split(b"\0")[0].decode("latin-1")
    race = next((s for t, _h, s, _f in sf_esm_records if t == b"RACE" and sfplugin.edid(s) == "ChildRace"), None)
    if race is None:
        raise KeyError("ChildRace")
    groups = [text(d) for s, d in race if s == b"BSTT" and len(d) > 1]
    pick = [g for g in groups if ("female" in g.lower()) == bool(female)] or groups
    if not pick:
        raise KeyError("ChildRace has no body skin tone (BSTT)")
    name = pick[0].lower()
    avmd = next((s for t, _h, s, _f in sf_esm_records if t == b"AVMD" and
                 any(sg in (b"TNAM", b"YNAM", b"EDID") and text(d).lower() == name for sg, d in s)), None)
    if avmd is None:
        raise KeyError(f"no skin tone group {pick[0]}")
    tex = [text(d) for s, d in avmd if s == b"VNAM" and len(d) > 1]
    if not tex:
        raise ValueError(f"skin tone group {pick[0]} lists no textures")
    imgs = {k: decode(read_texture(p)) for k, p in enumerate(tex)}
    ranks = skintone.slot_ranks(imgs)
    slots = sorted(ranks, key=lambda k: ranks[k])
    return {"group": pick[0], "textures": tex, "slots": slots,
            "medians": {k: list(skintone.median_colour(imgs[k])) for k in slots}}


def tone_slot(rank: Optional[int], slots: Optional[List[int]]) -> Optional[int]:
    """The STON slot of a child tone rank (0 = lightest, child_faces.child_tone), through the slots' lightness order
    (child_tone_slots) when known; the rank itself otherwise."""
    if rank is None:
        return None
    if not slots:
        return rank
    return slots[min(max(0, rank), len(slots) - 1)]


def hair_record_subs(npc_subs, sf_hdpt, fid: int):
    """The child NPC's subrecords with its hair head part (type 3) swapped for ours (npc_hair.with_head_parts)."""
    import npc_hair
    return npc_hair.with_head_parts(npc_subs, sf_hdpt, {HAIR: fid})


def u32(d) -> int:
    return struct.unpack("<I", bytes(d)[:4])[0]
