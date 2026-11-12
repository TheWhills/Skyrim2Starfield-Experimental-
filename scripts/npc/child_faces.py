"""Skyrim's children on Starfield's child head (races roadmap I2, 2026-11-12).

What the owner's child_probe showed: every Skyrim child race (NordRaceChild ...) shares one child head
(MaleHeadChild, ChildHead.nif: 1,211 vertices, its own topology, both sexes), and each child's FaceGen head has that
topology (Dorthe, Frodnar: 1,211). Starfield's children (ChildRace) have no face dials, blends or pre-built face
textures: a child's face is its head part, Human_Child_Head_Boy / _Girl (Actors\\Child\\Mesh\\Child_Head_*.nif, the
adult head's topology, 15,370 vertices).

So a child is converted by baking its own face into a head model of its own: its FaceGen head minus Skyrim's child
head (what is the child's own), moved onto Starfield's child head through the same surface correspondence the races
use (headcorr, after face_fit's head alignment), written with headbake like the race heads. face_fit uses this for
NPCs of a Skyrim child race (child_npc_subs: a vanilla child NPC as template, the baked head as its Face part, the
converted child race when race_heads built it).
"""
import os
import struct

import numpy as np

SKY_CHILD_HEAD = r"meshes\actors\character\character assets\childhead.nif"
SF_CHILD_HEAD_PART = {False: "Human_Child_Head_Boy", True: "Human_Child_Head_Girl"}
CHILD_TONES = 3              # Starfield's child skin tone groups hold 3 textures (owner's skin tone probe)
FACE_TYPE = 1                # HDPT PNAM: Face


def _u32(d):
    return struct.unpack("<I", bytes(d)[:4])[0] if len(d) >= 4 else None


def twin(path):
    stem, ext = os.path.splitext(path)
    return stem + "_facebones" + ext


def child_model_path(edid):
    """The MODL of a child NPC's own baked head (Data\\meshes-relative)."""
    return f"S2S\\Children\\{edid}Head.nif"


def child_tone(ston):
    """A child's STON (0..CHILD_TONES-1) from an adult-scale one (0..8), or None."""
    if ston is None:
        return None
    return int(round(min(8, max(0, ston)) * (CHILD_TONES - 1) / 8))


def child_setup(sky, sf_data, female, face_fit, head_modl, transfer="surface"):
    """{head, base, al, model_space, corr, nif, mesh_path} for one sex: Starfield's child head (its _facebones twin
    when there is one, as the adult heads), Skyrim's child head aligned onto it, and the surface correspondence."""
    from fo4sf import facefit, headcorr
    hk = face_fit.hkx_to_af
    rel = "meshes/" + head_modl.replace("\\", "/").lower()
    try:
        hk.vanilla_file(twin(rel), sf_data)
        head_nif = twin(rel)
    except (SystemExit, KeyError, OSError):
        head_nif = rel
    head, _hrep = face_fit.starfield_head(sf_data, female, head_nif)
    base_bytes = hk.read_any(SKY_CHILD_HEAD, sky)
    base, al, model_space = face_fit.head_alignment(head, base_bytes)
    corr = None
    if transfer == "surface" and getattr(head, "triangles", None) is not None and len(head.triangles):
        s, R, t = al[:3]
        node = getattr(head, "model_xf", None)
        corr = headcorr.correspond(s * base @ R.T + t, face_fit.skyrim_head_triangles(base_bytes), head.vertices,
                                   head.triangles, to_model=np.asarray(node, float) if model_space and
                                   node is not None else None)
    nif_bytes, _r = hk.vanilla_file(rel, sf_data)
    paths, _skin = facefit.starfield_head_parts(nif_bytes)
    return {"head": head, "base": base, "al": al, "model_space": model_space, "corr": corr, "nif": nif_bytes,
            "nif_rel": rel, "mesh_path": paths[0] if paths else None,
            "report": {"head": head_nif, "alignment_rms_m": float(al[3]), "scale": float(al[0]),
                       "correspondence": corr.report if corr is not None else None}}


def child_disp(ctx, facegen_points, smooth=10, symmetry=True):
    """(N, 3) moves on Starfield's child head: the child's FaceGen head (points in the same space as ctx["base"])
    minus Skyrim's child head, rotated / scaled by the alignment and carried over by the correspondence."""
    from fo4sf import facefit
    base, al, corr, head = ctx["base"], ctx["al"], ctx["corr"], ctx["head"]
    fg = np.asarray(facegen_points, float)
    if fg.shape != base.shape:
        raise ValueError(f"FaceGen head has {len(fg)} vertices, Skyrim's child head {len(base)}")
    if corr is not None:
        disp = corr.transfer((fg - base) @ al[1].T * al[0], smooth)
    else:
        disp = facefit.transfer(base, fg, al, head.vertices)
    if symmetry:
        disp = facefit.symmetrize(disp, head.vertices)
    return disp


def child_head_files(ctx, disp, edid, read):
    """{Data-relative path: bytes}: the child's own head (the vanilla child head NIF with the baked mesh) and its
    _facebones twin when the game has one; MODL child_model_path(edid)."""
    from fo4sf import headbake
    out_nif = "meshes/" + child_model_path(edid).replace("\\", "/").lower()
    verts = ctx["head"].vertices
    files = headbake.baked_head_files(ctx["nif"], read, ctx["mesh_path"], verts, disp, out_nif)
    try:
        fb = read(twin(ctx["nif_rel"]))
    except (SystemExit, KeyError, OSError):
        fb = None
    if fb is not None:
        from fo4sf import facefit
        fpaths, _s = facefit.starfield_head_parts(fb)
        if fpaths:
            files.update(headbake.baked_head_files(fb, read, fpaths[0], verts, disp, twin(out_nif)))
    return files


def pick_child_template(npc_recs, child_race, female):
    """A vanilla child NPC of the sex to copy: on ChildRace, no template (TPLT), a voice type, no scripts / quest
    data; the first such by EditorID. None if there is none."""
    best = []
    for r in npc_recs:
        subs = r[2]
        sigs = {s for s, _d in subs}
        if next((_u32(d) for s, d in subs if s == b"RNAM"), None) != child_race:
            continue
        acbs = next((bytes(d) for s, d in subs if s == b"ACBS"), b"")
        if bool(acbs and struct.unpack_from("<I", acbs, 0)[0] & 1) != female:
            continue
        if b"TPLT" in sigs or b"VTCK" not in sigs:
            continue
        plain = not (sigs & {b"VMAD", b"QSTA", b"BNAM"})
        edid = next((bytes(d).split(b"\0")[0].decode("latin-1") for s, d in subs if s == b"EDID"), "")
        best.append((not plain, edid, r))
    return min(best, key=lambda x: (x[0], x[1]))[2] if best else None


def child_npc_subs(tpl_subs, edid, full, head_fid, part_types, race_fid=None, ston=None):
    """The template child's subrecords as our child: EDID / FULL, its Face head part(s) replaced by head_fid (added
    if it had none), RNAM race_fid when given, STON (0..2) when given. part_types {HDPT FormID: type}."""
    from fo4sf import sfplugin
    out, placed = [], False
    for s, d in tpl_subs:
        if s == b"PNAM" and len(d) == 4 and part_types.get(_u32(d)) == FACE_TYPE:
            if not placed:
                out.append((b"PNAM", struct.pack("<I", head_fid)))
                placed = True
            continue
        out.append((s, d))
    if not placed:
        at = max([i + 1 for i, (s, _d) in enumerate(out) if s == b"PNAM"] or
                 [next((i + 1 for i, (s, _d) in enumerate(out) if s == b"RNAM"), len(out))])
        out = out[:at] + [(b"PNAM", struct.pack("<I", head_fid))] + out[at:]
    vals = {b"EDID": sfplugin.zs(f"S2SFace_{edid}"), b"FULL": sfplugin.zs(full)}
    if race_fid is not None:
        vals[b"RNAM"] = struct.pack("<I", race_fid)
    out = sfplugin.edit(out, vals)
    if ston is not None:
        import npc_records
        out = npc_records.with_face_colors(out, {b"STON": bytes([ston])})
    return out


def child_head_part(vanilla_subs, edid, modl):
    """Our child head part: the vanilla child head (Human_Child_Head_Boy / _Girl: its morph record, valid-race list
    and extra parts kept) with its own EditorID and model."""
    from fo4sf import sfplugin
    return sfplugin.edit(list(vanilla_subs), {b"EDID": sfplugin.zs(f"S2S_ChildHead_{edid}"),
                                              b"MODL": sfplugin.zs(modl)})
