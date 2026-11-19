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


def usable_shapes(names: List[str], shapes: List[Dict], src) -> tuple:
    """(names, shapes, left out {shape: missing texture}): the hair without its extra layers whose texture `src` lacks
    (2026-11-19, owner's run: KS Hairdos SMP has no hairline\\scalp.dds, Frodnar's scalp layer; the layer is a
    shadow under the hair). Nothing is kept when the hair part's own shape (names[0]) lacks its texture."""
    left = {}
    for sh in shapes:
        miss = missing_textures([sh], src)
        if miss:
            left[sh["name"]] = miss[0]
    main = names[0].lower() if names else None
    if any(k.lower() == main for k in left) or not any(sh["name"].lower() == main for sh in shapes):
        return names, [], left or {main: "no shape of the hair part"}
    keep = [sh for sh in shapes if sh["name"] not in left]
    dropped = {k.lower() for k in left}
    return [n for n in names if n not in dropped], keep, left


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
                     sf_world, surface, fb, conv, staging: str, settings, pre=None) -> Dict:
    """One child's hair converted into staging: skyrim_hairs.build_part on the FaceGen NIF's hair shapes. ctx:
    child_faces.child_setup's; fg_points: its FaceGen head in the same space as ctx["base"] (child_faces.
    facegen_points); surface: its baked head (baked_surface); fb: the template hair's _facebones template
    (hair_pack.facebones_template) or None; pre: the 4x4 move its fitted face shape made after the face alignment
    (childshape.prealign's matrix; 2026-11-19, owner: eyes and brows too high, the hair low on the forehead - the
    hair had stayed at the alignment's size, 1.09x smaller than the face for Frodnar), or None. Returns
    build_part's row (ok, model, ...) plus the placement."""
    import hair_pack
    import skyrim_hairs
    from fo4sf import facefit, skyrimhair
    M = sky_to_starfield(ctx)
    if pre is not None:
        M = np.asarray(pre, float) @ M
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


def tone_group(sf_esm_records, female: bool, sig: bytes = b"BSTT", race: str = "ChildRace"):
    """(name, AVMD record (type, header, subs, FormID), [texture, ...]) of a race's skin tone group of one sex: the
    race's `sig` string (BSTT body, HSTT hands, FSTT face) naming an AVMD by TNAM / YNAM / EDID (else any text
    field); a complex group whose VNAMs are simple-group names is followed to the sex's simple group. Raises KeyError
    / ValueError when something is missing (with .fields to report)."""
    from fo4sf import sfplugin

    def text(d):
        d = bytes(d)
        return d.split(b"\0")[0].decode("latin-1")
    rrec = next((s for t, _h, s, _f in sf_esm_records if t == b"RACE" and sfplugin.edid(s) == race), None)
    if rrec is None:
        raise KeyError(race)
    groups = [text(d) for s, d in rrec if s == sig and len(d) > 1]
    pick = [g for g in groups if ("female" in g.lower()) == bool(female)] or groups
    if not pick:
        raise KeyError(f"{race} has no {sig.decode()} skin tone string")
    name = pick[0].lower()
    avmd = next((r for r in sf_esm_records if r[0] == b"AVMD" and
                 any(sg in (b"TNAM", b"YNAM", b"EDID") and text(d).lower() == name for sg, d in r[2])), None)
    if avmd is None:      # 2026-11-19: the face string matched no group by these fields; any text field then
        avmd = next((r for r in sf_esm_records if r[0] == b"AVMD" and
                     any(len(d) > 1 and text(d).lower() == name for _sg, d in r[2])), None)
    if avmd is None:
        near = sorted({text(d) for t, _h, s_, _f in sf_esm_records if t == b"AVMD" for sg, d in s_
                       if sg == b"EDID" and "child" in text(d).lower()})
        err = KeyError(f"no skin tone group {pick[0]}")
        err.fields = [("child AVMD EditorIDs", ", ".join(near[:40]))]
        raise err
    label = pick[0]
    tex = [text(d) for s, d in avmd[2] if s == b"VNAM" and len(d) > 1]
    if tex and not any(t.lower().endswith(".dds") for t in tex):
        # 2026-11-19 (owner's run): the face string names a complex group whose entries are simple groups
        sub = [t for t in tex if ("female" in t.lower()) == bool(female)] or tex
        inner = next((r for r in sf_esm_records if r[0] == b"AVMD" and r[2] is not avmd[2] and
                      any(sg in (b"EDID", b"TNAM", b"YNAM") and text(d).lower() == sub[0].lower()
                          for sg, d in r[2])), None)
        if inner is not None:
            label = f"{pick[0]} -> {sub[0]}"
            avmd = inner
            tex = [text(d) for s, d in avmd[2] if s == b"VNAM" and len(d) > 1]
    if not tex:
        err = ValueError(f"skin tone group {label} lists no textures")
        err.fields = [(sg.decode("latin-1"), text(d) if bytes(d)[-1:] == b"\0" else bytes(d).hex()[:64])
                      for sg, d in avmd[2][:60]]
        raise err
    return label, avmd, tex


def child_tone_slots(sf_esm_records, read_texture, female: bool, decode, sig: bytes = b"BSTT",
                     race: str = "ChildRace") -> Dict:
    """{"slots": [slot, ...] lightest first, "group": ..., "textures": [...], "medians": {slot: rgb}} of a race's
    skin tone group of the sex (tone_group; ChildRace by default, HumanRace for the adult ones), by each slot's
    texture's median luminance (skintone.slot_ranks; vanilla's adult slots are not in brightness order, races.md
    2026-11-11). sf_esm_records: [(type, header, subs, FormID)] holding RACE and AVMD; read_texture: path -> bytes;
    decode: DDS bytes -> RGBA. Raises KeyError / ValueError when something is missing (.fields: what was found)."""
    from fo4sf import skintone
    label, _avmd, tex = tone_group(sf_esm_records, female, sig, race)
    imgs = {k: decode(read_texture(p)) for k, p in enumerate(tex)}
    ranks = skintone.slot_ranks(imgs)
    slots = sorted(ranks, key=lambda k: ranks[k])
    return {"group": label, "textures": tex, "slots": slots,
            "medians": {k: list(skintone.median_colour(imgs[k])) for k in slots}}


TONE_DIR = "s2s/children/tones"
LIGHT_LABEL = "s2s_child_light"
TONE_SIGS = (b"BSTT", b"HSTT", b"FSTT")


def skin_median(rgba):
    """sRGB median colour of a tone texture's skin: pixels with some colour (saturation >= 0.12) and brightness
    (2026-11-19: the child body texture's grey background and painted grey underwear pulled its plain median down to
    a dull (164,126,103); the skin itself reads lighter and pinker)."""
    rgb = rgba[..., :3].reshape(-1, 3).astype(np.float32)
    mx, mn = rgb.max(1), rgb.min(1)
    sel = (mx > 40) & ((mx - mn) / np.maximum(mx, 1) >= 0.12)
    px = rgb[sel] if sel.sum() >= 16 else rgb
    return tuple(int(v) for v in np.median(px, axis=0))


def recolour_skin(rgba, target):
    """rgba with each channel scaled (linear light) so its skin_median becomes target; detail and alpha kept."""
    from fo4sf.textures import srgb_to_linear, linear_to_srgb
    have = srgb_to_linear(np.array(skin_median(rgba), np.float32))
    f = srgb_to_linear(np.array(target, np.float32)) / np.maximum(have, 1e-4)
    out = linear_to_srgb(np.clip(srgb_to_linear(rgba[..., :3].astype(np.float32)) * f[None, None, :], 0.0, 1.0))
    return np.concatenate([np.round(out).clip(0, 255).astype(np.uint8), rgba[..., 3:4]], -1)


def with_appended_entry(subs, label: str, path: str, index: int):
    """A tone group's AVMD subrecords with one entry (LNAM label / VNAM path / NNAM as the first entry's) appended at
    `index` (the alien mods' way of adding tones, skintone.appended_tones; verified for adult groups 2026-11-11). A
    group with fewer entries is first padded with copies of its last one, so one STON names the new entry in every
    group. ITMC raised."""
    subs = list(subs)
    vn = [i for i, (s_, _d) in enumerate(subs) if s_ == b"VNAM"]
    if not vn:
        raise ValueError("tone group has no VNAM entries")
    ln = [i for i, (s_, _d) in enumerate(subs) if s_ == b"LNAM"]
    n0 = len(vn)
    if index < n0:
        raise ValueError(f"index {index} inside the group's {n0} entries")
    nnam0 = next((d for s_, d in subs[(ln or vn)[0]:] if s_ == b"NNAM"), struct.pack("<I", 0))

    def entry(lnam, vnam):
        return ([(b"LNAM", lnam)] if ln else []) + [(b"VNAM", vnam), (b"NNAM", nnam0)]
    new = []
    for _k in range(index - n0):
        new += entry(subs[ln[-1]][1] if ln else None, subs[vn[-1]][1])
    new += entry(label.encode("latin-1") + b"\0", path.encode("latin-1") + b"\0")
    end = max(i for i, (s_, _d) in enumerate(subs) if s_ in (b"LNAM", b"VNAM", b"NNAM")) + 1
    out = subs[:end] + new + subs[end:]
    return [(s_, struct.pack("<I", index + 1) if s_ == b"ITMC" else d) for s_, d in out]


# How much lighter a child's face texture must be than its body texture to look the same in game, per channel in
# linear light (2026-11-19, owner's run: face recoloured to the lightest body's skin (172,125,95) still tan next to
# "pale white" hands; on his daylight screenshots the face rendered about 1.3-3x darker than the hands, and its green
# / blue 1.2-1.4x / 1.6-2x lower against red): HUE times each strength in FACE_LEVELS, one tone per strength.
FACE_HUE = (1.0, 1.3, 1.8)
FACE_LEVELS = (("Face13", 1.3), ("Face17", 1.7), ("Face22", 2.2))
FACE_MAIN = 1              # the level the converted children get; the others go to the comparison copies


def face_level_target(body_skin, level: float, hue=FACE_HUE):
    """sRGB skin colour for a child face texture: body_skin (sRGB) times hue * level in linear light, clipped."""
    from fo4sf.textures import srgb_to_linear, linear_to_srgb
    lin = srgb_to_linear(np.array(body_skin, np.float32)) * np.array(hue, np.float32) * float(level)
    return [int(round(float(v))) for v in np.clip(linear_to_srgb(np.clip(lin, 0.0, 1.0)), 0, 255)]


def light_child_tone(sf_esm_records, read_texture, decode, levels=FACE_LEVELS, children=(), paint=None):
    """Light child tones pairing Starfield's lightest child body with lighter faces (2026-11-19, owner: Frodnar's
    hands pale white, his face tan. ChildRace's three tones pair body and face texture by index, and index 1 - the
    lightest body - is the middle, orange face; the baked face textures are not drawn on a child: the adult
    template's painted stubble never showed). Per group of ChildRace's BSTT / HSTT / FSTT strings (each sex): one new
    entry per level, at the same indices in all - the body / hands: their lightest vanilla texture; the face: its
    lightest vanilla texture recoloured so its skin is face_level_target of that body's skin (skin_median).
    children [(edid, female)] with paint(edid, face_rgba) -> RGBA or None: after the levels, one more tone per child
    whose face is its painted face (fo4sf.childpaint, on the main level's face; 2026-11-19, owner: "looks like
    he's someone ethnic or someone doing whiteface") - its own entry in its sex's groups.
    Returns {"index": first STON, "indices": {label: STON}, "children": {edid: STON}, "records": [AVMD overrides],
    "textures": {path under textures/: rgba}, "report": {...}}."""
    from fo4sf import skintone
    found, rep = {}, {}
    for female in (False, True):
        for sig in TONE_SIGS:
            key = f"{'female' if female else 'male'}_{sig.decode().lower()}"
            try:
                label, avmd, tex = tone_group(sf_esm_records, female, sig)
            except (KeyError, ValueError) as e:
                rep[key] = f"none: {e}"
                continue
            imgs = {k: decode(read_texture(p)) for k, p in enumerate(tex)}
            ranks = skintone.slot_ranks(imgs)
            light = min(ranks, key=lambda k: ranks[k])
            found[(female, sig)] = (label, avmd, tex, imgs, light)
    if not any(sig == b"BSTT" for _f, sig in found) or not any(sig == b"FSTT" for _f, sig in found):
        raise KeyError("ChildRace body or face tone group not found: " + str(rep))
    first = max(len(v[2]) for v in found.values())
    indices = {lab: first + k for k, (lab, _lv) in enumerate(levels)}
    main_level = levels[min(FACE_MAIN, len(levels) - 1)]
    textures, entries, groups, faces = {}, {}, {}, {}
    for (female, sig), (label, avmd, tex, imgs, light) in sorted(found.items()):
        sex = "female" if female else "male"
        key = f"{sex}_{sig.decode().lower()}"
        fid = avmd[3]
        if fid in groups:          # one group shared by both sexes: extended once
            rep[key] = {"from": tex[light], "group": label, "shared": True}
            groups[fid][2].add(female)
            continue
        groups[fid] = (avmd, sig, {female})
        info = {"from": tex[light], "group": label, "vanilla_entries": len(tex)}
        ent = entries.setdefault(fid, {})
        if sig == b"FSTT":
            body = found.get((female, b"BSTT"))
            body_skin = skin_median(body[3][body[4]])
            prefix = "textures/" if tex[light].lower().startswith("textures") else ""
            info.update(face_skin=list(skin_median(imgs[light])), body_skin=list(body_skin), new={})
            for lab, lv in levels:
                rel = f"{TONE_DIR}/{sex}_face_{lab.lower()}_color.dds"
                target = face_level_target(body_skin, lv)
                textures[rel] = recolour_skin(imgs[light], target)
                ent[indices[lab]] = (f"{LIGHT_LABEL}_{lab.lower()}", prefix + rel)
                info["new"][lab] = {"ston": indices[lab], "face_skin": target, "texture": prefix + rel}
            faces[female] = (prefix, f"{TONE_DIR}/{sex}_face_{main_level[0].lower()}_color.dds")
        else:
            for lab, _lv in levels:
                ent[indices[lab]] = (f"{LIGHT_LABEL}_{lab.lower()}", tex[light])
            info["new"] = tex[light]
        rep[key] = info
    child_idx, child_rep = {}, {}
    nxt = first + len(levels)
    for edid, female in children:
        if paint is None or female not in faces:
            continue
        prefix, main_rel = faces[female]
        try:
            got = paint(edid, textures[main_rel])
        except (KeyError, ValueError, OSError) as e:
            child_rep[edid] = f"none: {type(e).__name__}: {e}"
            continue
        if got is None:
            continue
        sex = "female" if female else "male"
        rel = f"{TONE_DIR}/{edid.lower()}_face_color.dds"
        textures[rel] = got
        for fid, (avmd, sig, sexes) in groups.items():
            if female not in sexes:
                continue
            body = found[(female, sig)] if (female, sig) in found else found[(not female, sig)]
            path = prefix + rel if sig == b"FSTT" else body[2][body[4]]
            entries[fid][nxt] = (f"{LIGHT_LABEL}_{edid.lower()}", path)
        child_idx[edid] = nxt
        child_rep[edid] = {"ston": nxt, "texture": prefix + rel, "sex": sex}
        nxt += 1
    records = []
    for fid, (avmd, _sig, _sexes) in groups.items():
        subs = avmd[2]
        for idx in sorted(entries[fid]):
            label, path = entries[fid][idx]
            subs = with_appended_entry(subs, label, path, idx)
        records.append((avmd[0], avmd[1], subs, fid))
    if child_rep:
        rep["children"] = child_rep
    return {"index": first, "indices": indices, "children": child_idx, "records": records, "textures": textures,
            "report": rep}


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
