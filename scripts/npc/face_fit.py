"""Fit Starfield face sliders to Skyrim NPCs' faces (src/fo4sf/facefit.py), optionally as a test plugin to look at.

Reads (Skyrim): Skyrim.esm NPC_ / RACE records, each NPC's baked FaceGen head and the base heads
(meshes\\actors\\character\\character assets\\{male,female}head.nif) from the Skyrim archives.
Reads (Starfield): the facial bone regions (humanracefacialboneregions*.txt), the skinned head NIF and its geometry
(.mesh) and Starfield.esm's HumanRace face dials, from the game archives (or --regions / --head-nif files, e.g. a
face-bone mod's).

    python -I scripts\\npc\\face_fit.py --skyrim-data "<Skyrim SE>\\Data" --starfield "<Starfield>" --out <folder>
        [--npc EDID ...] [--count 12] [--test-plugin [--hair --texconv <texconv.exe>]]

Writes <out>\\faces.json (per NPC: dial values by slider id and name, fit RMS before / after, alignment) and, with
--test-plugin, S2SFaceTest.esm: one Starfield NPC per fitted face (a vanilla human NPC of the same sex copied, its face
dials replaced, its phenotype morphs cleared) named "<Skyrim EditorID> (S2S)", to place with the console
(player.placeatme <id>; the ids are in faces.json).
With --hair the test NPCs also wear their Skyrim hair and beard (scripts/npc/npc_hair.py: the looks-menu hair pipeline
of scripts/npc/skyrim_hairs.py, fitted to the NPC's sex, hair colour baked in; --hair-legacy: the first rigid
conversion), packed as "S2SFaceTest - Main.ba2" / "- Textures.ba2".
Unverified until the first run (all reported in faces.json): position units (cm), dial value range (-1..1), that
FMSI is the regions file's slider ID, the head NIF's bind convention.
"""
import argparse
import json
import os
import re
import struct
import sys
from typing import Dict, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

from fo4sf import bsa, facefit, headcorr, nif as nifmod, sfmesh, sfplugin, skyrimload, skyrimnpc, skyrimskin  # noqa: E402
import hkx_to_af  # noqa: E402  (archive helpers)
import npc_records  # noqa: E402
import hair_probe  # noqa: E402  (PNG writer)
from fo4sf import facepreview  # noqa: E402

HUMAN_RACES = {"NordRace", "ImperialRace", "BretonRace", "RedguardRace", "DarkElfRace", "HighElfRace", "WoodElfRace",
               "OrcRace"}
# well-known NPCs tried first for the default sample (EditorIDs as guessed; missing ones are skipped)
SAMPLE = ["HousecarlWhiterun", "BalgruufTheGreater", "Delphine", "Brynjolf", "AelaTheHuntress", "UlfricStormcloak",
          "GeneralTullius", "Ysolda", "Farengar", "Irileth", "Belethor", "Hulda"]
SKY_HEADS = {False: r"meshes\actors\character\character assets\malehead.nif",
             True: r"meshes\actors\character\character assets\femalehead.nif"}
SF_REGIONS = {False: "meshes/actors/human/characterassets/humanracefacialboneregionsmale.txt",
              True: "meshes/actors/human/characterassets/female/humanracefacialboneregionsfemale.txt"}
SF_HEADS = {False: "meshes/actors/human/characterassets/male/malehead_facebones.nif",
            True: "meshes/actors/human/characterassets/female/femalehead_facebones.nif"}
FACE_SIGS = (b"FMSI", b"FMRS", b"FMRI", b"FMRG", b"BMPN", b"BMPV")
PLUGIN = "S2SFaceTest.esm"


def skyrim_head(data: bytes, model: bool = False):
    """The head shape's vertices (Skyrim units): as stored (skin space), or with model=True in model space (its
    NiSkinData overall transform undone: what facefit.align_to_local expects)."""
    n = nifmod.parse(data)
    s = skyrimnpc.head_shape(skyrimskin.skinned_shapes(n))
    if s is None:
        return None
    p = np.array(s.positions, float)
    return facefit.apply4(facefit.skyrim_model_matrix(n, s), p) if model else p


def skyrim_head_uvs(data: bytes):
    """(N, 2) UVs of the head shape in a Skyrim head NIF (None without one or without UVs)."""
    s = skyrimnpc.head_shape(skyrimskin.skinned_shapes(nifmod.parse(data)))
    return None if s is None or not s.uvs else np.asarray(s.uvs, float).reshape(-1, 2)


def skyrim_head_triangles(data: bytes):
    """(T, 3) triangles of the head shape in a Skyrim head NIF (None without one)."""
    s = skyrimnpc.head_shape(skyrimskin.skinned_shapes(nifmod.parse(data)))
    return None if s is None else np.asarray(s.triangles, int).reshape(-1, 3)


def skyrim_head_matrix(data: bytes):
    """4x4 skin -> model space of the head shape in a Skyrim head NIF (facefit.skyrim_model_matrix; identity without
    a head shape)."""
    n = nifmod.parse(data)
    s = skyrimnpc.head_shape(skyrimskin.skinned_shapes(n))
    return facefit.skyrim_model_matrix(n, s) if s is not None else np.eye(4)


# ------------------------------------------------------------------------- NPCs on their converted race (2026-11-10)
# Owner: Faendal (Bosmer) should show up with the Bosmer head. With --races-plugin (race_heads.py's S2SRaceTest.esm,
# its race_heads.json next to it) an NPC whose Skyrim race was converted gets that race, its head and its face parts,
# and the fit takes only what is the NPC's own: its FaceGen head minus Skyrim's base head WITH the race's morph
# (Maleheadraces.tri / Femaleheadraces.tri), so the race shape (already in the race head) is not fitted twice.

def race_delta(sky, female, race_edid, base_bytes, model_space, cache):
    """Skyrim's race morph for race_edid on the base head's vertices (Skyrim units; model space when model_space, as
    skyrim_head gives the base), or None if the races .tri has no such morph. The .tri's vertices are matched to the
    NIF's by position (the same head)."""
    key = (female, race_edid, model_space)
    if key in cache:
        return cache[key]
    import race_probe
    from fo4sf import skyrimtri
    tri = cache.get(("tri", female))
    if tri is None:
        tri = cache[("tri", female)] = skyrimtri.parse(hkx_to_af.read_any(race_probe.SKY_RACE_TRI[female], sky),
                                                       deltas=True)
    m = next((x for x in tri["morphs"] if x["name"].lower() == race_edid.lower()), None)
    if m is None:
        cache[key] = None
        return None
    nif_skin = skyrim_head(base_bytes, model=False)
    tri_base = np.asarray(tri["base"], float)
    j, _d = facefit._nearest(tri_base, np.asarray(nif_skin, float), 1)
    d = np.asarray(m["deltas"], float)[j[:, 0]]
    if model_space:
        d = d @ skyrim_head_matrix(base_bytes)[:3, :3].T
    cache[key] = d
    return d


def race_heads_stale(races_plugin) -> str:
    """A warning when race_heads.json beside the race plugin is older than the plugin, else "" (2026-11-13: the MO2
    folder held the 11-12 plugin with the 11-11 race_heads.json, face_fit found 1 race of 10 and every NPC lost its
    converted race, Faendal human again)."""
    folder = os.path.dirname(os.path.abspath(races_plugin))
    js = os.path.join(folder, "race_heads.json")
    try:
        if os.path.getmtime(js) + 60 < os.path.getmtime(races_plugin):
            return (f"{js} is older than {os.path.basename(races_plugin)}: copy race_heads.json from the race build's "
                    "--out folder next to the plugin, or NPCs may lose their converted race")
    except OSError:
        pass
    return ""


def converted_races(races_plugin):
    """{Skyrim race EditorID: {"name", "form_id" (local), "parts": {female: {vanilla HDPT EditorID: local FormID}},
    "head": {female: local FormID}, "mouth": {female: local FormID}}} from the race plugin and its race_heads.json."""
    folder = os.path.dirname(os.path.abspath(races_plugin))
    stale = race_heads_stale(races_plugin)
    if stale:
        print(f"WARNING: {stale}")
    try:
        with open(os.path.join(folder, "race_heads.json"), encoding="utf-8") as fh:
            rep = json.load(fh)
    except (OSError, ValueError):
        rep = {}
    recs = sfplugin.records(races_plugin, [b"HDPT", b"RACE"])
    hd = {sfplugin.edid(sb): fid & 0xFFFFFF for t, _h, sb, fid in recs if t == b"HDPT"}
    # the plugin's own races, by EditorID (2026-11-19, owner: "why did this happen to faendal AGAIN, hes human AGAIN" -
    # race_heads.json beside the plugin was older than it on every run that day, the warning lost in the log; on
    # 11-13 the same: 1 race of 10). FormIDs come from the plugin; race_heads.json only adds the skin tones.
    import race_heads
    by_name = {v: k for k, v in race_heads.NAMES.items()}
    plugin_races = {}
    for t, _h, sb, fid in recs:
        mm = re.match(r"^S2S_(.+)Race$", sfplugin.edid(sb) or "") if t == b"RACE" else None
        if mm and mm.group(1) in by_name:
            plugin_races[by_name[mm.group(1)]] = {"edid": sfplugin.edid(sb), "form_id": f"{fid:08X}",
                                                  "from": "plugin"}
    listed = {k: v for k, v in (rep.get("new_races") or {}).items() if "form_id" in v and v.get("edid")}
    merged = plugin_races if plugin_races else listed   # the file's only for a plugin without RACE records
    out = {}
    for race, r in merged.items():
        name = re.sub(r"^S2S_|Race$", "", r["edid"])
        pre = f"S2S_{name}Race_"
        parts = {False: {}, True: {}}
        for e, fid in hd.items():
            mm = re.match(re.escape(pre) + r"(.+)_([MF])$", e)
            if mm and not mm.group(1).startswith("Mouth"):
                parts[mm.group(2) == "F"][mm.group(1)] = fid
        tones = race_tones(rep, race, folder)
        out[race] = {"name": name, "form_id": int(r["form_id"], 16) & 0xFFFFFF, "parts": parts, "tones": tones,
                     "head": {f: hd[f"{pre}{SEX}_Head"] for f, SEX in ((False, "male"), (True, "female"))
                              if f"{pre}{SEX}_Head" in hd},
                     "mouth": {f: hd[f"{pre}Mouth_{c}"] for f, c in ((False, "M"), (True, "F"))
                               if f"{pre}Mouth_{c}" in hd}}
    return out


def race_tones(rep, race, folder):
    """{"first": the race's first appended tone (STON), "ramp": {female: [sRGB per slot k]}, "textures": [written
    tone textures], "folder"} from race_heads.json (rep), or None for a race without tones of its own (the human
    races keep Starfield's tones). 2026-11-12, owner: a converted NPC always matches its race and skin."""
    t = ((rep.get("new_races") or {}).get(race) or {}).get("skin_tones") or {}
    tex = (rep.get("skin_tone_textures") or {}).get(race) or {}
    if t.get("method") != "append" or not t.get("first_index") or not tex:
        return None
    ramp = {}
    for path, rgb in tex.items():
        m = re.search(r"/body/(male|female)_sk(\d+)_color\.dds$", path)
        if m:
            ramp.setdefault(m.group(1) == "female", {})[int(m.group(2))] = list(rgb)[:3]
    return {"first": int(t["first_index"][0]), "ramp": {f: [v[k] for k in sorted(v)] for f, v in ramp.items()},
            "textures": list(tex), "folder": folder}


RACE_TONE_DEFAULT = 4          # race_heads.RACE_TONE_DEFAULT: the middle of the race's 9 tones


def race_tone_rank(ramp, rgb):
    """The race slot (0 = lightest) whose Skyrim colour is nearest the NPC's Skyrim skin colour by luminance, or
    RACE_TONE_DEFAULT without one."""
    if not ramp or not rgb or rgb[0] is None:
        return RACE_TONE_DEFAULT
    y = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]           # noqa: E731
    return min(range(len(ramp)), key=lambda k: abs(y(ramp[k]) - y(rgb)))


def race_skin(subs, conv, female, rgb):
    """(subs, info, colour or None): an NPC of a converted race with tones of its own on the race's tone nearest its
    Skyrim skin (STON = the race's first tone + slot), without the human Dermaesthetic face skin layer; colour:
    bytes -> bytes recolouring its baked face to that tone's body texture (race_heads.face_tone, as the race's own
    NPCs and presets). (subs, None, None) for a race without tones."""
    t = conv.get("tones")
    if not t or female not in t["ramp"]:
        return subs, None, None
    import race_heads as rh
    k = race_tone_rank(t["ramp"][female], rgb)
    subs = rh.without_layer(rh.with_ston(subs, t["first"] + k), rh.SKIN_LAYER)
    try:
        target = rh.face_targets(t["textures"], t["folder"], rank=k).get(female)
    except OSError:                   # the tone textures are not beside race_heads.json (point at race_heads' --out)
        target = None
    info = {"slot": k, "ston": t["first"] + k, "menu_tone": t["first"] + k + 1, "skyrim_rgb": rgb,
            "face_target": list(target) if target else None}
    return subs, info, (rh.face_tone(target) if target else None)


def facegen_mesh(esm, fid):
    """An NPC's baked FaceGen head path: by the plugin that defines the NPC (a LoadOrder), else Skyrim.esm."""
    if isinstance(esm, skyrimload.LoadOrder):
        return esm.facegen_paths(fid)["mesh"]
    return skyrimnpc.facegen_paths("Skyrim.esm", fid)["mesh"]


def child_context(n, sky, sf_data, a, cache, transfer=None):
    """child_faces.child_setup for the child NPC n (its race's base head, its sex), cached in cache by (female,
    base head); transfer None = a.transfer. A setup made without the surface correspondence (transfer "none", for
    the hair: only the alignment is needed) is kept apart and never used for a face."""
    import child_faces
    import npc_hair
    female = n["female"]
    if "_sky" not in cache:                    # the Skyrim side once: races and head parts (load order aware)
        cache["_sky"] = ({fid: s_ for _t, _h, s_, fid in skyrimload.records(a.load_order, [b"RACE"])},
                         npc_hair.head_parts(a.load_order)[0])
    sky_races, sky_parts = cache["_sky"]
    # 2026-11-19: the base head is the child race's own Face part (RS Children Overhaul: its child head)
    base_rel = child_faces.base_head_path(sky_races.get(n["race"], []), sky_parts, female)
    transfer = a.transfer if transfer is None else transfer
    key = (female, base_rel.lower())
    if key in cache:
        return cache[key]
    lite = (female, base_rel.lower(), "lite")
    if transfer == "none" and lite in cache:
        return cache[lite]
    hd = {sfplugin.edid(sb).lower(): sb for _t, _h, sb, _f in
          sfplugin.records(os.path.join(sf_data, "Starfield.esm"), [b"HDPT"])}
    van = hd.get(child_faces.SF_CHILD_HEAD_PART[female].lower())
    if van is None:
        raise ValueError(f"no {child_faces.SF_CHILD_HEAD_PART[female]} in Starfield.esm")
    modl = bytes(dict(van).get(b"MODL", b"")).split(b"\0")[0].decode("latin-1")
    ctx = child_faces.child_setup(sky, sf_data, female, sys.modules[__name__], modl, transfer, base_rel=base_rel)
    cache[lite if transfer == "none" else key] = ctx
    return ctx


def with_own_head(subs, row, recs, masters, sf_hdpt, race_head=None):
    """subs with its face head part (type 1) swapped for a new one: the vanilla head part (race_heads.HEAD_PART, its
    morph record, valid-race list and extra parts kept, as the race heads are made) with the NPC's own head model
    (row own_head.model); race_head: the converted race's head part FormID (in this plugin's master space), the
    face part after on_race. Returns (subs, the new head part's FormID hex)."""
    import race_heads
    female = row["female"]
    van = next((r for r in sf_hdpt.values() if sfplugin.edid(r[2]) == race_heads.HEAD_PART[female]), None)
    if van is None:
        raise KeyError(race_heads.HEAD_PART[female])
    fid = sfplugin.new_form_id(len(recs), masters=len(masters))
    recs.append((b"HDPT", van[1], sfplugin.edit(list(van[2]), {
        b"EDID": sfplugin.zs(f"S2S_Head_{row['edid']}"), b"MODL": sfplugin.zs(row["own_head"]["model"])}), fid))
    out, swapped = [], False
    for sg, d in subs:
        if sg == b"PNAM" and len(d) == 4 and not swapped:
            v = struct.unpack("<I", bytes(d))[0]
            rec = sf_hdpt.get(v)
            is_face = v == race_head or (rec is not None and hdpt_type(rec) == 1)
            if is_face:
                d, swapped = struct.pack("<I", fid), True
        out.append((sg, d))
    if not swapped:
        out.append((b"PNAM", struct.pack("<I", fid)))
    return out, f"{fid:08X}"


def uses_adult_shape(a, n) -> bool:
    """--shape-npc names this adult: its own head, the children's feature-matched fit (fo4sf.childshape) on its
    race's head, instead of Starfield's face dials (2026-11-19, owner on Faendal: the dials left him "pretty much"
    the template - his fit took the error from 2.5 to 1.9 mm only)."""
    return n["edid"].lower() in {x.lower() for x in (getattr(a, "shape_npc", None) or [])}


def head_mesh(nif_bytes, read):
    """(LOD 0 mesh path as the NIF names it, mesh-local vertices (V, 3), triangles (T, 3)) of a Starfield head NIF;
    read: Data-relative path -> bytes."""
    paths, _skin = facefit.starfield_head_parts(nif_bytes)
    if not paths:
        raise ValueError("head NIF has no geometry reference")
    mesh = sfmesh.parse(read("geometries/" + paths[0].replace("\\", "/") + ".mesh"))
    pos, _ws = facefit.mesh_arrays(mesh)
    return paths[0], np.asarray(pos, float), np.array([tuple(t) for t in mesh.triangles], int)


ADULT_HEAD_DIR = "S2S\\Faces"


def adult_own_head(n, fg, fg_bytes, al, model_space, base, base_bytes, conv, races_plugin, sf_data, out, a, cache):
    """An adult's own head (--shape-npc): the vanilla head NIF (Human_Male_Head / _Female_Head) with a mesh baked to
    the NPC's Skyrim FaceGen face by the children's fit (child_shape_disp), on its converted race's head (the race
    plugin's baked mesh, from the race plugin's folder) when it has one; written under out as
    S2S\\Faces\\<edid>Head.nif (+ its _facebones twin) with its meshes. Returns {"model", "files", "shape",
    "on"}."""
    import types
    import race_heads
    import child_faces
    from fo4sf import headbake
    female = n["female"]
    esm = os.path.join(sf_data, "Starfield.esm")
    vread = lambda r: hkx_to_af.vanilla_file(r, sf_data)[0]                      # noqa: E731
    modl = race_heads.vanilla_head_model(esm, female)
    nif_rel = "meshes/" + modl.replace("\\", "/").lower()
    nif_bytes = vread(nif_rel)
    mpath, v_van, tris = head_mesh(nif_bytes, vread)
    v_on, on = v_van, "the vanilla head"
    if conv is not None and races_plugin:
        folder = os.path.dirname(os.path.abspath(races_plugin))

        def rread(r):
            path = os.path.join(folder, *r.split("/"))
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    return fh.read()
            return vread(r)
        rnif = rread("meshes/" + race_heads.race_model_path(conv["name"], female).replace("\\", "/").lower())
        _rp, v_race, rtris = head_mesh(rnif, rread)
        if len(v_race) == len(v_van) and len(rtris) == len(tris):
            v_on, on = v_race, f"S2S_{conv['name']}Race's head"
    head = types.SimpleNamespace(vertices=v_on, triangles=tris, model_xf=starfield_head_node(nif_bytes))
    ctx = {"head": head, "al": al, "model_space": model_space, "base": base,
           "base_tris": skyrim_head_triangles(base_bytes)}
    disp, shape = child_shape_disp(ctx, fg, fg_bytes)
    total = v_on + disp - v_van
    out_nif = "meshes/" + f"{ADULT_HEAD_DIR}\\{n['edid']}Head.nif".replace("\\", "/").lower()
    files = headbake.baked_head_files(nif_bytes, vread, mpath, v_van, total, out_nif)
    try:
        fb = vread(child_faces.twin(nif_rel))
    except (SystemExit, KeyError, OSError):
        fb = None
    if fb is not None:                 # the _facebones twin, what the game draws NPCs from
        try:
            fpaths, _s = facefit.starfield_head_parts(fb)
        except nifmod.NifError:
            fpaths = None
        if fpaths:
            files.update(headbake.baked_head_files(fb, vread, fpaths[0], v_van, total, child_faces.twin(out_nif)))
    for rel, data in files.items():
        path = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    preview = child_preview(n["edid"], ctx, fg, disp, out, cache)
    mag = np.linalg.norm(disp, axis=1)
    return {"model": f"{ADULT_HEAD_DIR}\\{n['edid']}Head.nif", "files": sorted(files), "shape": shape, "on": on,
            "preview": preview, "max_move_m": round(float(mag.max()), 4)}


def uses_child_shape(a, n) -> bool:
    """--child-shape-npc names this child (the feature-matched fit, fo4sf.childshape)."""
    return n["edid"].lower() in {x.lower() for x in (getattr(a, "child_shape_npc", None) or [])}


def child_shape_disp(ctx, fg, fg_bytes):
    """(moves on Starfield's child head in its mesh-local frame, report) by fo4sf.childshape: the FaceGen head
    (fg: in the base head's space, child_faces.facegen_points) and its eyes taken to Starfield's model space by the
    face alignment, Starfield's head by its node; the moves back into the mesh-local frame."""
    import child_hair
    from fo4sf import childshape
    head = ctx["head"]
    node = np.asarray(head.model_xf, float)
    M = child_hair.sky_to_starfield(ctx)
    sky_tris = ctx.get("base_tris")
    if sky_tris is None:
        raise ValueError("no Skyrim base head triangles")
    sky_model = facefit.apply4(M, np.asarray(fg, float))
    eyes = childshape.facegen_eyes(fg_bytes, fg)
    if eyes is None:                   # what the FaceGen NIF holds (2026-11-19, Faendal: no eyes found)
        try:
            shapes = [(x.name or b"").decode("latin-1") for x in skyrimskin.skinned_shapes(nifmod.parse(fg_bytes))]
        except nifmod.NifError:
            shapes = []
        raise ValueError(f"Skyrim FaceGen head: no eyes shape with the head bone among {shapes}")
    eyes = facefit.apply4(M, eyes)
    mouth = childshape.skyrim_mouth(sky_model, sky_tris)
    disp_model, rep = childshape.child_shape(facefit.apply4(node, head.vertices), np.asarray(head.triangles, int),
                                             sky_model, sky_tris, eyes, mouth)
    return disp_model @ np.linalg.inv(node[:3, :3]).T, rep


def child_face(n, sky_race, sky, sf_data, out, a, cache):
    """{"child": {...}, "dials": {}} for a Skyrim child NPC: its face baked into a head of its own on Starfield's
    child head (child_faces), the files written under out. cache: child_context's."""
    import child_faces
    ctx = child_context(n, sky, sf_data, a, cache)
    fg = child_faces.facegen_points(ctx, sys.modules[__name__],
                                    hkx_to_af.read_any(facegen_mesh(a.load_order, n["form_id"]), sky))
    if fg is None:
        raise ValueError("FaceGen head has no head shape")
    shape = None
    paint = None
    if uses_child_shape(a, n):         # 2026-11-19 (owner's option 2): the child's own shape, feature by feature
        fg_bytes = hkx_to_af.read_any(facegen_mesh(a.load_order, n["form_id"]), sky)
        try:
            disp, shape = child_shape_disp(ctx, fg, fg_bytes)
        except ValueError as e:
            shape = {"error": f"{e}: the difference transfer instead"}
            disp = child_faces.child_disp(ctx, fg, a.smooth, not a.no_symmetry)
        else:
            try:
                paint = child_paint_points(ctx, fg, fg_bytes, disp, shape, n, a, out, sf_data)
            except (ValueError, KeyError, OSError, SystemExit) as e:
                paint = {"error": f"{type(e).__name__}: {e}"}
    else:
        disp = child_faces.child_disp(ctx, fg, a.smooth, not a.no_symmetry)
    files = child_faces.child_head_files(ctx, disp, n["edid"], lambda r: hkx_to_af.vanilla_file(r, sf_data)[0])
    for rel, data in files.items():
        path = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    mag = np.linalg.norm(disp, axis=1)
    preview = child_preview(n["edid"], ctx, fg, disp, out, cache) if previewing(a, n) else None
    return {"child": {"skyrim_race": sky_race, "head_model": child_faces.child_model_path(n["edid"]),
                      **({"preview": preview} if preview else {}), **({"shape": shape} if shape else {}),
                      **({"paint": paint} if paint else {}),
                      "files": sorted(files), "max_move_m": round(float(mag.max()), 4),
                      "rms_move_m": round(float(np.sqrt(np.mean(mag ** 2))), 5), "setup": ctx["report"]},
            "dials": {}}


PAINT_DIR = "_child_paint"
HAIR_LIFT_MAX = 0.008      # m: a child's hair is lifted at most this much with its forehead (Frodnar 7.6 mm; Dorthe's
                           # 16 mm would float her hair off the crown: the hair moves rigidly, nothing pulls it down)


def starfield_mesh_uvs(sf_data, mesh_path, count: int):
    """(N, 2) UVs (uv1) of a Starfield .mesh (geometries/<mesh_path>.mesh), checked against the head's vertex
    count."""
    data, _ = hkx_to_af.vanilla_file("geometries/" + mesh_path.replace("\\", "/") + ".mesh", sf_data)
    mesh = sfmesh.parse(data)
    if len(mesh.uv1) != count:
        raise ValueError(f"{mesh_path}: {len(mesh.uv1)} UVs for a head of {count} vertices")
    return np.array([[sfmesh.half_to_float(u), sfmesh.half_to_float(v)] for u, v in mesh.uv1], float)


def hair_lift_matrix(row):
    """4x4 that lifts a child's hair with its forehead (the face shape's prealign hair_lift_m, at most
    HAIR_LIFT_MAX), or None: raised, not scaled with the face (2026-11-19, Dorthe's hair stood out at the back like a
    bulb when scaled 1.11x)."""
    lift = (((row.get("child") or {}).get("shape") or {}).get("prealign") or {}).get("hair_lift_m")
    if not lift:
        return None
    pre = np.eye(4)
    pre[2, 3] = float(np.clip(lift, -HAIR_LIFT_MAX, HAIR_LIFT_MAX))
    return pre


def child_paint_points(ctx, fg, fg_bytes, disp, shape, n, a, out, sf_data) -> dict:
    """Where the child's Skyrim face paint lands on Starfield's head (fo4sf.childpaint; 2026-11-19, owner: Frodnar
    "looks like he's someone ethnic or someone doing whiteface"): per Starfield head vertex, its Skyrim UV (the
    closest point of its fitted place on the prealigned Skyrim face) and a weight (the face, not the eye sockets'
    or mouth's insides). Saved as out/_child_paint/<edid>.npz with the head's UVs and triangles; the bake
    (child_paint_face) reads the tint later. Returns {"file", "tint", "vertices_painted"}."""
    import child_hair
    from fo4sf import childpaint, childshape
    head = ctx["head"]
    if not ctx.get("mesh_path"):
        raise ValueError("Starfield child head: no .mesh path")
    sf_uv = starfield_mesh_uvs(sf_data, ctx["mesh_path"], len(head.vertices))
    sky_uv = skyrim_head_uvs(fg_bytes)
    if sky_uv is None or len(sky_uv) != len(fg):
        raise ValueError("Skyrim FaceGen head has no UVs matching its points")
    pre = (shape.get("prealign") or {}).get("matrix")
    if pre is None:
        raise ValueError("no prealign move in the shape report")
    node = np.asarray(head.model_xf, float)
    M = np.asarray(pre, float) @ child_hair.sky_to_starfield(ctx)
    sky_model = facefit.apply4(M, np.asarray(fg, float))
    sf_t = np.asarray(head.triangles, int)
    sf_model = facefit.apply4(node, head.vertices)
    fitted = facefit.apply4(node, np.asarray(head.vertices, float) + np.asarray(disp, float))
    eyes, mouth = childshape.starfield_eyes_mouth(sf_model, sf_t)
    if eyes is None or mouth is None:
        raise ValueError("Starfield head: eye / mouth openings not found")
    w = childshape.face_weight(sf_model, eyes, mouth) * (1.0 - childshape.inside_mouth(sf_model, mouth))
    for c in np.asarray(eyes, float):          # the socket behind each opening: no paint
        dax = np.linalg.norm((sf_model - c)[:, [0, 2]], axis=1)
        w = np.where((dax < 0.016) & (sf_model[:, 1] < c[1] - 0.004), 0.0, w)
    sky_mouth = childshape.skyrim_mouth(sky_model, ctx["base_tris"])
    sky_eyes = childshape.facegen_eyes(fg_bytes, fg)
    sky_flip = False
    if sky_eyes is not None and sky_mouth is not None:
        sky_uv, sky_flip = childpaint.upright_uv(sky_uv, sky_model, facefit.apply4(M, sky_eyes), sky_mouth)
    sf_uv, sf_flip = childpaint.upright_uv(sf_uv, sf_model, eyes, mouth)
    uv, wt = childpaint.vertex_sky_uv(fitted, sky_model, ctx["base_tris"], sky_uv, w)
    tint = skyrimnpc.facegen_paths("Skyrim.esm", n["form_id"])["tint"]
    mesh = facegen_mesh(a.load_order, n["form_id"])
    if "facegeom" in mesh.lower():
        tint = mesh.replace("meshes", "textures", 1).replace("facegeom", "facetint").rsplit(".", 1)[0] + ".dds"
    path = os.path.join(out, PAINT_DIR, f"{n['edid'].lower()}.npz")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lips, eye_w = childpaint.lip_eye_weights(sf_model, eyes, mouth)
    np.savez_compressed(path, sf_uv=sf_uv.astype(np.float32), sf_tris=sf_t.astype(np.int32),
                        sky_uv=uv.astype(np.float32), weight=wt.astype(np.float32),
                        lips=lips.astype(np.float32), eyes=eye_w.astype(np.float32))
    return {"file": f"{PAINT_DIR}/{n['edid'].lower()}.npz", "tint": tint, "version": childpaint.VERSION,
            "uv_flipped": {"starfield": sf_flip, "skyrim": sky_flip},
            "vertices_painted": int((wt > 0.5).sum())}


def child_paint_face(row, sky, texconv, out):
    """paint(edid, face_rgba) for child_hair.light_child_tone: the child's Skyrim face tint (row child.paint.tint,
    decoded through texconv when compressed) on the face texture through its saved correspondences."""
    import race_heads
    from fo4sf import childpaint
    info = (row.get("child") or {}).get("paint") or {}
    if not info.get("file"):
        raise KeyError(info.get("error") or "no paint correspondences")
    z = np.load(os.path.join(out, *info["file"].split("/")))
    data = hkx_to_af.read_any(info["tint"], sky)
    if not data:
        raise KeyError(f"{info['tint']} not in the Skyrim load order")
    tint = race_heads.decode_any_dds(data, texconv)

    def paint(edid, face_rgba):
        layer = childpaint.paint_layer(z["sf_uv"], z["sf_tris"], z["sky_uv"], z["weight"], tint, face_rgba.shape[0],
                                       z["lips"] if "lips" in z.files else None,
                                       z["eyes"] if "eyes" in z.files else None)
        row["child"]["paint"]["tint_skin_linear"] = [round(x, 4) for x in layer["tint_skin"]]
        return childpaint.painted_face(face_rgba, layer)
    return paint


def previewing(a, n) -> bool:
    """--preview (every NPC) or --preview-npc naming this one (2026-11-19: a child's preview without refitting all)."""
    return bool(a.preview) or n["edid"].lower() in {x.lower() for x in (getattr(a, "preview_npc", None) or [])}


def child_preview(edid, ctx, fg, disp, out, cache):
    """--preview for a child (2026-11-19, owner: compare the faces without the game): faces_preview/<edid>_child.png,
    columns the Skyrim FaceGen head (placed by the face alignment), Starfield's child head and ours, rows front /
    three-quarter / side and the moves on ours as heat; and <edid>_child.npz with the shapes (Starfield's head in its
    mesh-local frame + node, Skyrim's base and FaceGen heads in Skyrim model units with their triangles, the
    alignment, the moves), so a fitting change can be tried and drawn without the game. Returns the paths."""
    import child_hair
    from fo4sf import facepreview
    head = ctx["head"]
    node = np.asarray(head.model_xf, float)
    M = child_hair.sky_to_starfield(ctx)
    sky_tris = ctx.get("base_tris")
    sf_tris = np.asarray(head.triangles, int)
    vanilla = facefit.apply4(node, head.vertices)
    ours = facefit.apply4(node, head.vertices + disp)
    cols = [(facefit.apply4(M, np.asarray(fg, float)), sky_tris)] if sky_tris is not None else []
    cols += [(vanilla, sf_tris), (ours, sf_tris)]
    img = facepreview.mesh_sheet(cols, heat_of=(len(cols) - 1, np.linalg.norm(disp, axis=1)))
    folder = os.path.join(out, "faces_preview")
    os.makedirs(folder, exist_ok=True)
    png = os.path.join(folder, f"{edid}_child.png")
    hair_probe.write_png(png, img)
    npz = os.path.join(folder, f"{edid}_child.npz")
    s_, R_, t_ = ctx["al"][:3]
    np.savez_compressed(npz, sf_local=np.asarray(head.vertices, np.float32), sf_tris=sf_tris.astype(np.int32),
                        sf_node=node, sky_base=np.asarray(ctx["base"], np.float32),
                        sky_tris=np.asarray(sky_tris if sky_tris is not None else np.zeros((0, 3)), np.int32),
                        sky_facegen=np.asarray(fg, np.float32), al_s=float(s_), al_R=np.asarray(R_, float),
                        al_t=np.asarray(t_, float), disp=np.asarray(disp, np.float32))
    return {"png": png, "npz": npz}


FIT_CACHE = "_fit_cache.json"     # in --out: each NPC's fit result by an input key (2026-11-12)
FIT_VERSION = 2                   # bump when the fit changes in a way the hashed code below does not show
FIT_FUNCS = ("skyrim_head", "skyrim_head_triangles", "skyrim_head_matrix", "race_delta", "head_alignment",
             "starfield_head_node", "starfield_head", "child_context", "child_face", "child_shape_disp",
             "uses_child_shape", "child_paint_points", "skyrim_head_uvs", "starfield_mesh_uvs")
CHILD_FUNCS = ("child_context", "child_face", "child_shape_disp", "uses_child_shape", "child_paint_points",
               "skyrim_head_uvs", "starfield_mesh_uvs")


def fit_code_hash(child=False):
    """The fitting code: face_fit's fit functions (FIT_FUNCS, their source), src/fo4sf facefit / headcorr / headbake,
    FIT_VERSION; for children (child=True) also child_face and child_faces.py. 2026-11-19 (owner: "why is every adult
    refitting"): adults' keys leave the child code out, so a change to the children's fit refits only children. The
    writer code is not in it (it runs every time)."""
    import hashlib
    import inspect
    import child_faces
    h = hashlib.sha1(str(FIT_VERSION).encode())
    mod = sys.modules[__name__]
    for f in FIT_FUNCS:
        if f in CHILD_FUNCS and not child:
            continue
        h.update(inspect.getsource(getattr(mod, f)).encode())
    from fo4sf import headbake
    from fo4sf import childpaint, childshape
    for m in (facefit, headcorr, headbake) + ((child_faces, childshape, childpaint) if child else ()):
        with open(m.__file__, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def fit_settings(a, sf_data):
    """What the fit of every NPC depends on besides its own face: the fit options, the regions / head / recipe
    files given, and the game files the defaults come from (size and time: a game update refits)."""
    def stamp(path):
        try:
            st = os.stat(path)
            return [os.path.basename(path), st.st_size, int(st.st_mtime)]
        except OSError:
            return [path, None]
    files = [stamp(p) for p in list(a.regions or []) + list(a.head_nif) + ([a.facebones_recipe] if a.facebones_recipe
                                                                            else [])]
    games = [stamp(os.path.join(sf_data, "Starfield.esm"))] + [
        stamp(os.path.join(sf_data, f)) for f in sorted(os.listdir(sf_data)) if f.lower().startswith(
            "starfield - meshes") and f.lower().endswith(".ba2")] if os.path.isdir(sf_data) else []
    return {"pos_unit": a.pos_unit, "smooth": a.smooth, "dial_limit": a.dial_limit, "ridge": a.ridge,
            "symmetry": not a.no_symmetry, "transfer": a.transfer, "legacy": bool(a.legacy_alignment),
            "blends": None if a.no_blends else a.blend_ethnicity,
            "files": files, "games": games}
    # Skyrim mods (--skyrim-mod) are not a setting here (2026-11-19, owner: "why is every adult refitting"): an NPC a
    # mod changes has other FaceGen bytes, which its own key already holds (npc_fit_key)


def npc_fit_key(code, settings, facegen_bytes, sky_race, race_converted, extra=None):
    """One NPC's fit key: the fitting code and settings, its FaceGen head, its Skyrim race and whether it is fitted
    against that race's morph (a converted race: the NPC's own features only)."""
    import hashlib
    h = hashlib.sha1(code.encode())
    h.update(json.dumps(settings, sort_keys=True).encode())
    h.update(facegen_bytes)
    h.update(repr((sky_race, bool(race_converted))).encode())
    if extra is not None:              # per-NPC fit choices (a child's --child-shape-npc); None keeps older keys
        h.update(repr(extra).encode())
    return h.hexdigest()


def previous_rows(out):
    """{edid: row} of the last run's faces.json in out ({} without one)."""
    try:
        with open(os.path.join(out, "faces.json"), encoding="utf-8") as fh:
            return {r.get("edid"): r for r in json.load(fh).get("npcs", []) if isinstance(r, dict)}
    except (OSError, ValueError, AttributeError):
        return {}


def npc_changes(rows, recs, test_subs, out, before) -> dict:
    """Which test NPCs differ from the last run (2026-11-19, owner: "it feels like changing one thing about one NPC
    causes every single NPC to get touched"): per NPC a hash of its record, the head parts of this plugin it uses and
    the files its row lists (a child's head files), kept as test_npc.sha1 and compared with the last run's.
    Prints and returns {"changed": [...], "unchanged": [...], "new": [...]}."""
    import hashlib
    by_fid = {r[3]: r for r in recs}
    out_rep = {"changed": [], "unchanged": [], "new": []}
    for row in rows:
        k = test_subs.get(row.get("edid")) if isinstance(row.get("test_npc"), dict) else None
        if k is None or k >= len(recs):
            continue
        h = hashlib.sha1(repr(recs[k][2]).encode())
        for sg, d in recs[k][2]:
            if sg == b"PNAM" and len(d) == 4:
                part = by_fid.get(struct.unpack("<I", bytes(d))[0])
                if part is not None:
                    h.update(repr(part[2]).encode())
        for rel in sorted((row.get("child") or {}).get("files", [])):
            try:
                with open(os.path.join(out, *rel.split("/")), "rb") as fh:
                    h.update(fh.read())
            except OSError:
                pass
        row["test_npc"]["sha1"] = h.hexdigest()
        old = ((before.get(row["edid"]) or {}).get("test_npc") or {})
        old = old.get("sha1") if isinstance(old, dict) else None
        out_rep["new" if old is None else "changed" if old != row["test_npc"]["sha1"] else "unchanged"].append(
            row["edid"])
    print(f"NPCs changed since the last run: {', '.join(out_rep['changed']) or 'none'}"
          f"{'; unchanged: ' + str(len(out_rep['unchanged'])) if out_rep['unchanged'] else ''}"
          f"{'; first time compared: ' + ', '.join(out_rep['new']) if out_rep['new'] else ''}")
    return out_rep


def load_fit_cache(out):
    try:
        with open(os.path.join(out, FIT_CACHE), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def cached_fit(cache, edid, key, out):
    """The cached row of an NPC when its key matches and the files its fit wrote (a child's head) are there."""
    e = cache.get(edid.lower())
    if not e or e.get("key") != key:
        return None
    row = e.get("row") or {}
    for rel in (row.get("child") or {}).get("files", []):
        if not os.path.isfile(os.path.join(out, *rel.split("/"))):
            return None
    return json.loads(json.dumps(row))


def converted_child_races(races_plugin):
    """{Skyrim child race EditorID: local FormID of ours} from race_heads.json beside the race plugin."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(races_plugin)), "race_heads.json"),
                  encoding="utf-8") as fh:
            rep = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {k: int(v["form_id"], 16) & 0xFFFFFF for k, v in (rep.get("child_races") or {}).items()}


def write_child_npc(row, n, npcs, real, races, npc_recs, sf_hdpt_recs, child_race, conv_child, race_index, recs,
                    masters, test_subs, tone_slots=None, light_ston=None, own_ston=None):
    """The child's test NPC: a vanilla child NPC (child_faces.pick_child_template) with our head part (its baked
    head) as Face, on our child race when race_heads built it (else ChildRace), its STON from its Skyrim skin on
    the child scale (tone_slots {female: slots lightest first}: child_hair.child_tone_slots; 2026-11-19, owner's
    Frodnar came out darker than in Skyrim with STON 0); its outfit and voice the template's, its hair too until
    add_child_hair_files gives it its own."""
    import child_faces
    import child_hair
    female = row["female"]
    eth = child_faces.CHILD_ETHNICITY
    tpl = child_faces.pick_child_template(npc_recs, child_race, female, ethnicity=eth)
    if tpl is None:
        row["test_npc"] = "no vanilla child NPC of this sex"
        return
    van = next((r for r in sf_hdpt_recs if sfplugin.edid(r[2]).lower() ==
                child_faces.SF_CHILD_HEAD_PART[female].lower()), None)
    if van is None:
        row["test_npc"] = f"no {child_faces.SF_CHILD_HEAD_PART[female]} in Starfield.esm"
        return
    part_types = {r[3]: hdpt_type(r) for r in sf_hdpt_recs}
    hfid = sfplugin.new_form_id(len(recs), masters=len(masters))
    recs.append((b"HDPT", van[1], child_faces.child_head_part(van[2], row["edid"], row["child"]["head_model"]), hfid))
    full = f"{row['edid']} (S2S)"
    ston = None
    if real is not None:
        full = npc_records.npc_name(n, real["strings"])
        rank = child_faces.child_tone(target_skin(n, npcs, real)[0])
        ston = child_hair.tone_slot(rank, (tone_slots or {}).get(female))
        if rank == 0 and light_ston is not None:      # the added light tone (child_hair.light_child_tone)
            ston = light_ston
        if own_ston is not None:                       # its own tone: its Skyrim face paint (fo4sf.childpaint)
            ston = own_ston
        row["child_tone"] = {"rank_lightest_0": rank, "ston": ston,
                             "slots_by_lightness": (tone_slots or {}).get(female)}
    sky_race = races.get(n["race"], "")
    race_fid = None
    if race_index is not None and sky_race in conv_child:
        race_fid = (race_index << 24) | conv_child[sky_race]
    subs = child_faces.child_npc_subs(tpl[2], row["edid"], full, hfid, part_types, race_fid, ston)
    eyes = None
    if real is not None:               # 2026-11-19, owner: Frodnar's eyes brown, blue in Skyrim - as the adults' ECOL
        ecol, eyes = skyrim_eye_colour(n, real)
        if ecol:
            subs = npc_records.with_face_colors(subs, {b"ECOL": sfplugin.zs(ecol)})
    donor = next((r for r in npc_recs if sfplugin.edid(r[2]) == child_faces.FACE_DONORS[female]), None)
    if donor is not None:              # 2026-11-19: a European face skin layer from a vanilla child that has one
        subs = child_faces.with_face_block(subs, donor[2])
    subs = without_templates(sfplugin.edit(subs, {}, drop=STRIP))
    fid = sfplugin.new_form_id(len(recs), masters=len(masters))
    test_subs[row["edid"]] = len(recs)
    recs.append((b"NPC_", tpl[1], subs, fid))
    row["name"] = full
    row["test_npc"] = {"form_id": f"{fid:08X}", "template": sfplugin.edid(tpl[2]), "template_form_id": f"{tpl[3]:08X}",
                       "head_part": f"{hfid:08X}", "race": f"S2S child race {race_fid:08X}" if race_fid else "ChildRace",
                       "ston": ston, "eyes": eyes, "face_skin": {"wanted": eth,
                                                   "template": list(child_faces.face_ethnicity(tpl[2])),
                                                   "donor": sfplugin.edid(donor[2]) if donor is not None else
                                                   f"{child_faces.FACE_DONORS[female]} not found",
                                                   "layers": [f"{n_}: {t_} ({i_})" for n_, t_, i_ in face_layers(subs)]},
                       "console": f"player.placeatme xx{fid & 0xFFFFFF:06X}  (xx = S2SFaceTest.esm's load order index)"}


def hdpt_type(rec):
    """The head part type (PNAM) of an HDPT record (type, header, subs, FormID), or None. (2026-11-12, owner's first
    run with every race: the inline version indexed the bytes, not the unpacked tuple: TypeError.)"""
    if rec is None:
        return None
    d = bytes(dict(rec[2]).get(b"PNAM", bytes(4)))
    return struct.unpack("<I", d[:4])[0] if len(d) >= 4 else None


def on_race(subs, conv, female, index, sf_hdpt, part_type):
    """NPC subrecords on its converted race: RNAM the race, each head part (PNAM) swapped for the race's copy (by the
    vanilla part's EditorID), the Face part for the race head, the teeth for the race mouth. index: the race plugin's
    master index. Returns (subs, swapped count)."""
    full = lambda fid: (index << 24) | fid                                        # noqa: E731
    out, n = [], 0
    for sg, d in subs:
        if sg == b"RNAM" and len(d) == 4:
            d = struct.pack("<I", full(conv["form_id"]))
        elif sg == b"PNAM" and len(d) == 4:
            v = struct.unpack("<I", bytes(d))[0]
            rec = sf_hdpt.get(v)
            typ = part_type(rec) if rec is not None else None
            new = None
            if typ == 1 and female in conv["head"]:
                new = conv["head"][female]
            elif typ == 9 and female in conv["mouth"]:
                new = conv["mouth"][female]
            elif rec is not None:
                new = conv["parts"][female].get(sfplugin.edid(rec[2]))
            if new is not None:
                d = struct.pack("<I", full(new))
                n += 1
        out.append((sg, d))
    return out, n


def starfield_head_node(nif_bytes):
    """4x4 (local -> model) of the head NIF's first BSGeometry: its .mesh vertices are in that shape's frame."""
    from fo4sf import sfweaponleft, skyrimhair
    shapes = sfweaponleft.shapes_in_model(nifmod.parse(nif_bytes))
    return skyrimhair.xf_matrix(shapes[0][1]) if shapes else None


def head_alignment(head, sky_base_bytes, legacy=False):
    """(Skyrim base head points, alignment onto head.vertices, model space used): the Skyrim head in model space
    aligned through the Starfield head's node transform (facefit.align_to_local); legacy: the old ICP on the raw
    mesh-local points (90 degrees off for Starfield's heads, 2026-11-09), kept for comparison."""
    node = getattr(head, "model_xf", None)
    if node is not None and not legacy:
        base = skyrim_head(sky_base_bytes, model=True)
        return base, facefit.align_to_local(base, head.vertices, node), True
    base = skyrim_head(sky_base_bytes)
    al = facefit.align_heads(base, head.vertices)
    rot_free = facefit.align_heads(base, head.vertices, rotate=False)
    if rot_free[3] <= al[3] * 1.05:
        al = rot_free
    return base, al, False


def starfield_head(sf_data, female, head_nif=None, recipe=None):
    """recipe: facefit.load_recipe of a face-bone mod (More Sliders): its weight moves onto the new bones, which the
    mod's SFSE plugin makes at load time, are applied to the head's vanilla .mesh here too."""
    nif_bytes, _rel = hkx_to_af.vanilla_file(head_nif or SF_HEADS[female], sf_data)
    paths, skin = facefit.starfield_head_parts(nif_bytes)
    if not paths:
        raise SystemExit("head NIF has no geometry reference")
    mesh_rel = "geometries/" + paths[0].replace("\\", "/") + ".mesh"
    mesh_bytes, _ = hkx_to_af.vanilla_file(mesh_rel, sf_data)
    mesh = sfmesh.parse(mesh_bytes)
    pos, ws = facefit.mesh_arrays(mesh)
    bones = [b.decode("latin-1") if isinstance(b, bytes) else b for b in skin.get("bones", [])]
    rrep = None
    if recipe is not None:
        block = recipe.get(facefit._mesh_key(mesh_rel))
        if block is None:
            rrep = {"error": f"the recipe has no MESH block for {mesh_rel}"}
        elif block["vertices"] != len(pos):
            rrep = {"error": f"recipe expects {block['vertices']} vertices, {mesh_rel} has {len(pos)} (another "
                             "game version?)"}
        else:
            top = max((max(p, c) for _v, p, c, _a in block["moves"]), default=-1)
            if top >= len(bones):
                raise SystemExit(f"the recipe names bone {top}, the head NIF has {len(bones)}: use the mod's "
                                 "_facebones head NIF (--head-nif)")
            ws, rrep = facefit.apply_recipe(ws, block["moves"])
    head, rep = facefit.face_head(pos, ws, bones, skin.get("binds", []))
    if rrep is not None:
        rep["recipe"] = rrep
    head.triangles = np.array([tuple(t) for t in mesh.triangles], int)
    head.model_xf = starfield_head_node(nif_bytes)
    return head, rep


def race_dials(esm):
    """{female: [face dial indices]} of HumanRace (RACE chargen: MNAM / FNAM section, FDSI per dial)."""
    out = {False: [], True: []}
    for _t, _h, subs, _fid in skyrimload.records(esm, [b"RACE"]):
        if sfplugin.edid(subs) != "HumanRace":
            continue
        female = None
        for sig, d in subs:
            if sig == b"MNAM":
                female = False
            elif sig == b"FNAM":
                female = True
            elif sig == b"FDSI" and female is not None and len(d) >= 4:
                out[female].append(struct.unpack_from("<I", bytes(d), 0)[0])
    return out


def face_subrecords(values):
    out = []
    for k in sorted(values):
        out += [(b"FMSI", struct.pack("<I", int(k))), (b"FMRS", struct.pack("<f", float(values[k])))]
    return out


BLEND_KEY = re.compile(r"^(male|female)_([a-z]{2})_([a-z]{2}\d)_(\w+)$", re.I)   # <sex>_<ethnicity>_<phenotype>_<region>
BLEND_ETHNICITIES = ("eu",)       # owner 2026-11-12: Skyrim has no ethnicities; faces from the generic western blends


def head_blends(morph, nverts, female, ethnicities=BLEND_ETHNICITIES):
    """(names, D (K, V, 3), regions) of the head morph.dat's shape blends (Starfield's looks-menu "shape blends", the
    keys vanilla NPCs carry as BMPN): its phenotype keys <sex>_<ethnicity>_<phenotype>_<region> of these
    ethnicities ("all" for every one); our race keys (<sex>_sk_...) and body keys are not blends."""
    sex = "female" if female else "male"
    names, regions = [], []
    for k in morph.keys:
        g = BLEND_KEY.match(k)
        if not g or g.group(1).lower() != sex or g.group(2).lower() == "sk":
            continue
        if "all" not in ethnicities and g.group(2).lower() not in ethnicities:
            continue
        names.append(k)
        regions.append(g.group(4))
    D = np.zeros((len(names), nverts, 3))
    for i, k in enumerate(names):
        for v, d in morph.deltas[k].items():
            if v < nverts:
                D[i, v] = d
    return names, D, regions


def with_blends(subs, blends):
    """NPC subrecords with BMPN (key) / BMPV (f32 weight) pairs, name sorted, right after the face data (as
    race_heads.with_blends); existing pairs replaced."""
    subs = [(s, d) for s, d in subs if s not in (b"BMPN", b"BMPV")]
    face = [i for i, (s, _d) in enumerate(subs) if s in (b"FMSI", b"FMRS", b"FMRI", b"FMRG")]
    at = face[-1] + 1 if face else next((i for i, (s, _d) in enumerate(subs) if s in (b"ATTX", b"STON", b"HCOL")),
                                        len(subs))
    add = []
    for name in sorted(blends):
        add += [(b"BMPN", sfplugin.zs(name)), (b"BMPV", struct.pack("<f", float(blends[name])))]
    return subs[:at] + add + subs[at:]


def with_face(subs, values, keep=()):
    """The NPC's subrecords with face dials replaced by `values` and phenotype / morph-group data removed (`keep`:
    sigs of that data left as they are)."""
    gone = tuple(s for s in FACE_SIGS if s not in keep)
    first = next((i for i, (s, _d) in enumerate(subs) if s in gone), None)
    kept = [(s, d) for s, d in subs if s not in gone]
    if first is None:
        first = next((i for i, (s, _d) in enumerate(kept) if s in (b"ATTX", b"STON", b"HCOL")), len(kept))
    else:
        first = sum(1 for s, _d in subs[:first] if s not in gone)
    return kept[:first] + face_subrecords(values) + kept[first:]


# Data a test copy must not carry: scripts (VMAD) and companion affinity hooks (QSTA quest, BNAM dialogue)
STRIP = (b"VMAD", b"QSTA", b"BNAM", b"SHRT", b"SOFT")   # SOFT: space outfit (2026-11-03: Ysolda in a helmeted suit)
# 2026-11-06: Saadia / Nazeem spawned in a spacesuit from their new templates' default outfit / inventory; the test NPCs
# wear nothing until clothing is converted
STRIP_GEAR = (b"DOFT", b"CNTO", b"COCT")
# The body every test NPC gets, by sex (male, female): its weight triangle (MWGT thin / muscular / fat) and body morph
# region values (MRSV), whatever template the face came from (2026-11-08, owner: Delphine's outfit, the one Ysolda wears
# cleanly, came through at the shoulders; her template, picked by skin tone, is CF_KlaudiaSwist, Ysolda's
# ChargenPresetFemale04). Converted outfits follow only the three weight sliders, so the bodies they were checked on are
# used: ChargenPresetFemale04_Swap (Ralof, Orgnar, Embry) and ChargenPresetFemale04 (Ysolda). --body-npc none keeps
# each template's own body.
BODY_NPC = ("ChargenPresetFemale04_Swap", "ChargenPresetFemale04")
# The template every NPC of a sex copies (2026-11-12, owner: "always the generic western-looking one"; Faendal came out
# on SG02ChandaBanda, Nazeem on MQ101_MinerLaserDrillMale04, Sigrid / Hilde on CF_KlaudiaSwist: picked by skin tone).
# Skin tone is separate: STON and the face colour follow the NPC (race_skin on a converted race, human_face_colour
# otherwise). --template-by-tone: the old pick by tone; --template-npc names others.
GENERIC_TEMPLATE = BODY_NPC
BODY_SIGS = (b"MWGT", b"MRSV")


def with_body(subs, body_subs):
    """subs with body_subs' MWGT / MRSV in place of its own (only where subs has the field: a missing one would land
    after EDID, out of the record's order). Returns (subs, [sigs replaced])."""
    have = {s for s, _d in subs}
    rep = {s: bytes(d) for s, d in body_subs if s in BODY_SIGS and s in have}
    return (sfplugin.edit(subs, rep) if rep else subs), sorted(s.decode() for s in rep)
# 2026-11-06: Nazeem came out as "a random black guy with Starfield hair and beard" and the test NPCs kept spawning in
# spacesuits: Starfield NPCs take traits / face / inventory from template NPCs listed in TPTA (2,142 of 2,983 faced
# humans) when the template flags in ACBS (u16 at bytes 14-15, e.g. 0x6C13) say so; TPLT is the single template.
STRIP_TEMPLATES = (b"TPLT", b"TPTA")


def without_templates(subs) -> list:
    """subs with TPLT / TPTA dropped and the ACBS template flags (bytes 14-15) cleared."""
    out = []
    for s, d in subs:
        if s in STRIP_TEMPLATES:
            continue
        if s == b"ACBS" and len(d) >= 16:
            d = bytes(d)[:14] + b"\0\0" + bytes(d)[16:]
        out.append((s, d))
    return out


BAKED_FACE = re.compile(r"facecustomization[\\/]starfield\.esm[\\/]([0-9a-f]{8})_(color|normal|rough|ao)\.dds$",
                        re.I)


def baked_face_index(names_by_archive) -> Dict[int, Dict[str, Tuple[str, str]]]:
    """{FormID: {kind: (archive, entry)}} of the pre-built face textures Starfield ships per vanilla NPC
    (owner's facegen_probe 2026-11-06, verified: textures/actors/character/facecustomization/starfield.esm/
    <FormID 8 hex>_color / _normal / _rough / _ao.dds, plus a baked head mesh under meshes/.../facegendata/facegeom;
    a new NPC has none and the game shows a default light face). Later archives (the patch) win."""
    out: Dict[int, Dict[str, Tuple[str, str]]] = {}
    for arc in sorted(names_by_archive):
        for n in names_by_archive[arc]:
            m = BAKED_FACE.search(n.replace("\\", "/"))
            if m:
                out.setdefault(int(m.group(1), 16), {})[m.group(2).lower()] = (arc, n)
    return out


def write_baked_face(index, tpl_fid: int, new_fid: int, data_dir: str, out: str, plugin: str = None,
                     colour=None) -> list:
    """The template's baked face textures copied under the new NPC's FormID (load-order byte dropped, as the game
    names its own) in out/textures/actors/character/facecustomization/<plugin>/. The baked head mesh is not
    copied: the face shape stays ours (runtime). colour: bytes -> bytes applied to the colour texture (race_heads:
    a race's skin tone, 2026-11-11). Returns the written paths."""
    from fo4sf import ba2
    plugin = plugin or PLUGIN
    folder = os.path.join(out, "textures", "actors", "character", "facecustomization", plugin)
    written, opened = [], {}
    for kind, (arc, name) in sorted(index.get(tpl_fid, {}).items()):
        if arc not in opened:
            opened[arc] = ba2.Ba2(os.path.join(data_dir, arc))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{new_fid & 0xFFFFFF:08x}_{kind}.dds")
        data = opened[arc].read(name)
        if colour is not None and kind == "color":
            data = colour(data)
        with open(path, "wb") as fh:
            fh.write(data)
        written.append(path)
    return written


# Texture layers that bake wear into a template's face colour (2026-11-06: Ralof borrowed BE_CF02_DmitriMoldavski's
# textures and came out weathered): skin-matched templates with fewer of these, and not old, are preferred
ROUGH_LAYERS = ("Accents1", "Accents2", "ColorlessAccents1", "ColorlessAccents2", "Scars", "EnvironmentMask")


def template_wear(subs) -> float:
    """How weathered a template's baked face is likely to be: its rough texture layers, +2 for an old face (ol)."""
    layers = [fo4land_zstring(d) for s, d in subs if s == b"TNAM"]
    wear = float(sum(1 for n in layers if n in ROUGH_LAYERS))
    layer = None
    for s, d in subs:
        if s == b"TNAM":
            layer = fo4land_zstring(d)
        elif s == b"QNAM" and layer == "Dermaesthetic":
            m = npc_records.DERMA.match(fo4land_zstring(d))
            if m and m.group(3).lower().startswith("ol"):
                wear += 2.0
            break
    return wear


def template_skin(subs):
    """(STON, face skin ethnicity) of a Starfield NPC (its Dermaesthetic texture's first word, lower case)."""
    ston = next((bytes(d)[0] for s, d in subs if s == b"STON" and len(d)), None)
    layer, eth = None, None
    for s, d in subs:
        if s == b"TNAM":
            layer = fo4land_zstring(d)
        elif s == b"QNAM" and layer == "Dermaesthetic":
            m = npc_records.DERMA.match(fo4land_zstring(d))
            eth = m.group(1).lower() if m else None
            break
    return ston, eth


# Starfield's body skin tone textures (owner's skin tone probe 2026-11-11), slot k = STON k
HUMAN_BODY_TONE = {False: "textures/actors/human/naked_body/nakedbodym_sk{k}_color.dds",
                   True: "textures/actors/human/naked_body/nakedbodyf_sk{k}_color.dds"}
TONE_GAP = 2       # template skin tone this many steps or more from the NPC's: its baked face recoloured


def human_face_colour(tpl_subs, ston, female, read):
    """bytes -> bytes recolouring a template's baked face to the body tone the NPC gets (the median colour of
    Starfield's body tone texture at its STON), or None when the template's own tone is within TONE_GAP - 1 of it.
    2026-11-12: the template is now chosen by face ethnicity first, so a dark Nord can get a pale European template
    whose baked face (what a non-player NPC shows) would not match its body."""
    tpl_ston = template_skin(tpl_subs)[0]
    if ston is None or tpl_ston is None or abs(tpl_ston - ston) < TONE_GAP:
        return None, None
    from fo4sf import skintone
    import race_heads as rh
    target = skintone.median_colour(skintone.decode_dds(read(HUMAN_BODY_TONE[female].format(k=ston))))
    return rh.face_tone(target), {"template_ston": tpl_ston, "ston": ston, "face_target": list(target)}


# Every converted NPC's template and face skin texture are of one ethnicity, the generic western one (2026-11-12,
# owner: "Skyrim doesn't have ethnicities": a template's ethnic face would show through, a Nord with Asian eyes; the
# features come from Skyrim's sliders, the colour from the skin tone and the recoloured face). Was per race
# (npc_records.SKYRIM_ETHNICITY: Redguard african).
FACE_ETHNICITY = "european"

# a template of another face ethnicity only when none of the NPC's is left (was 6, less than the 8 steps of skin tone:
# 2026-11-12, owner: "we don't want a Delphine mapped on the Asian preset")
ETHNICITY_MISMATCH = 100


ELDER_RACES = ("elderrace", "elderracevampire")
AGE_ACCENTS = re.compile(r"wrinkles|crowsfeet|roughface|undereyecrease|nasolabial", re.I)
# layers an old template should not carry: they would put one NPC's scars / make-up / dirt on every elder
NOT_GENERIC = ("Scars", "TattooMask", "MakeupFullPaintMask1", "MakeupFullPaintMask2", "Eyeshadow1", "Eyeshadow2",
               "Eyeliner1", "Eyeliner2", "Lipstick1", "Lipstick2", "EnvironmentMask", "Cheeks1", "Cheeks2")


def face_layers(subs):
    """[(layer name, texture name, intensity u32)] of an NPC's face texture layers (TNAM, QNAM, INTV)."""
    out, cur = [], None
    for s, d in subs:
        if s == b"TNAM":
            cur = [fo4land_zstring(d), "", 0]
            out.append(cur)
        elif cur is not None and s == b"QNAM":
            cur[1] = fo4land_zstring(d)
        elif cur is not None and s == b"INTV" and len(d) >= 4:
            cur[2] = struct.unpack_from("<I", bytes(d), 0)[0]
    return [tuple(x) for x in out]


def pick_elder_template(npc_recs, race_fid, female, baked=None):
    """The generic OLD template of a sex (2026-11-13, owner: Elder-race NPCs should look old; Starfield's age is in the
    face skin: an ol phenotype Dermaesthetic plus wrinkle accents, the looks menu's Facial Forms, baked into the
    template's face textures). A plain voiced vanilla NPC (as pick_template) with a european_<sex>_ol Dermaesthetic and
    the most wrinkle accents (Accents / ColorlessAccents with wrinkles, crow's feet, rough face ...), and none of the
    one-person layers (NOT_GENERIC: scars, make-up, dirt, tattoos). None if there is none."""
    sex = "female" if female else "male"
    best = []
    for r in npc_recs:
        subs = r[2]
        sigs = {s for s, _d in subs}
        acbs = next((bytes(d) for s, d in subs if s == b"ACBS"), b"")
        if bool(acbs and struct.unpack_from("<I", acbs, 0)[0] & 1) != female:
            continue
        rnam = next((struct.unpack_from("<I", bytes(d), 0)[0] for s, d in subs if s == b"RNAM"), None)
        if rnam != race_fid or b"FMSI" not in sigs or b"TPLT" in sigs or b"VTCK" not in sigs:
            continue
        if sigs & {b"VMAD", b"QSTA", b"BNAM"} or (baked is not None and r[3] not in baked):
            continue
        layers = face_layers(subs)
        derma = next((t for n, t, _i in layers if n == "Dermaesthetic"), "")
        if not re.match(rf"european_{sex}_ol\d", derma, re.I):
            continue
        if any(n in NOT_GENERIC for n, _t, _i in layers):
            continue
        age = sum(i for n, t, i in layers if "Accents" in n and AGE_ACCENTS.search(t))
        best.append((-age, len(layers), sfplugin.edid(subs), r))
    return min(best, key=lambda b: b[:3])[3] if best else None


def pick_template(npc_recs, race_fid, female, edid=None, skin=None, baked=None):
    """A vanilla human NPC of the sex to copy: `edid` when given; else one with face dials and no template, preferring
    plain ones (no scripts, no affinity data: a generic NPC rather than a quest character) with a voice type (VTCK:
    the game's generic greetings, owner 2026-11-05). skin (STON, ethnicity): among those, the one whose skin tone and
    face skin ethnicity are nearest (2026-11-06: STON + the Dermaesthetic texture changed Nazeem's body, not his face,
    which kept the light template's colour from a field not yet known)."""
    if skin is not None and edid is None:
        voiced = []
        for r in npc_recs:
            subs = r[2]
            sigs = {s for s, _d in subs}
            acbs = next((bytes(d) for s, d in subs if s == b"ACBS"), b"")
            is_f = bool(acbs and struct.unpack_from("<I", acbs, 0)[0] & 1)
            rnam = next((struct.unpack_from("<I", bytes(d), 0)[0] for s, d in subs if s == b"RNAM"), None)
            if rnam == race_fid and is_f == female and b"FMSI" in sigs and b"TPLT" not in sigs \
                    and not (sigs & {b"VMAD", b"QSTA", b"BNAM"}) and b"VTCK" in sigs \
                    and (baked is None or r[3] in baked):
                ston, eth = template_skin(subs)
                cost = abs((ston if ston is not None else 4) - (skin[0] if skin[0] is not None else 4)) + \
                    (0 if eth == skin[1] else ETHNICITY_MISMATCH) + 0.5 * template_wear(subs)
                voiced.append((cost, sfplugin.edid(subs), r))
        if voiced:
            return min(voiced, key=lambda c: (c[0], c[1]))[2]
    best = plain_best = None
    for t, h, subs, fid in npc_recs:
        if edid is not None:
            if sfplugin.edid(subs).lower() == edid.lower():
                return t, h, subs, fid
            continue
        sigs = {s for s, _d in subs}
        acbs = next((bytes(d) for s, d in subs if s == b"ACBS"), b"")
        is_f = bool(acbs and struct.unpack_from("<I", acbs, 0)[0] & 1)
        rnam = next((struct.unpack_from("<I", bytes(d), 0)[0] for s, d in subs if s == b"RNAM"), None)
        if rnam == race_fid and is_f == female and b"FMSI" in sigs and b"TPLT" not in sigs \
                and (baked is None or fid in baked):
            plain = not (sigs & {b"VMAD", b"QSTA", b"BNAM"})
            if plain and b"VTCK" in sigs:                # a voice type: the game's generic greetings and barks
                return t, h, subs, fid
            if plain:
                plain_best = plain_best or (t, h, subs, fid)
            best = best or (t, h, subs, fid)
    return plain_best or best


def npc_setup(a, sky, esm, sf_esm, npc_recs, report) -> dict:
    """--hairs-plugin: what the real NPC conversion needs once (npc_records)."""
    import npc_hair
    hp = os.path.abspath(a.hairs_plugin)
    masters = npc_records.plugin_masters(hp) + [os.path.basename(hp)]
    sf_hdpt = {r[3]: r for r in sfplugin.records(sf_esm, [b"HDPT"])}
    hdpt, clfm = npc_hair.head_parts(esm)
    names = {fo4land_zstring(d) for _t, _h, subs, _f in npc_recs for sig, d in subs if sig == b"HCOL"} - {""}
    palette = None
    if a.hair_colors:
        with open(a.hair_colors, encoding="utf-8") as fh:
            palette = json.load(fh).get("palette") or None
    voices = {fid: sfplugin.edid(subs) for _t, _h, subs, fid in sfplugin.records(sf_esm, [b"VTYP"])}
    strings = npc_records.skyrim_names(sky, a.strings_language)
    index = npc_records.hairs_index(hp)
    race_recs = skyrimload.records(esm, [b"RACE"])
    races = {fid: (npc_records.race_tints(rs), npc_records.race_defaults(rs)) for _t, _h, rs, fid in race_recs}
    race_edids = {fid: sfplugin.edid(rs) for _t, _h, rs, fid in race_recs}
    derma = npc_records.dermaesthetic_names(npc_recs)
    derma_paths = npc_records.dermaesthetic_paths(npc_recs)
    beard_map = {}
    if getattr(a, "beard_map", None):
        with open(a.beard_map, encoding="utf-8") as fh:
            beard_map = json.load(fh).get("matches", {})
    report["npc_conversion"] = {"beard_map": len(beard_map), "hairs_plugin": hp, "masters": masters, "hairstyles_in_it": len(index),
                                "starfield_hair_colors": sorted(names), "palette": bool(palette),
                                "skyrim_strings": len(strings)}
    return dict(masters=masters, sf_hdpt=sf_hdpt, hdpt=hdpt, clfm=clfm, names=names, palette=palette,
                voices=voices, strings=strings, index=index, races=races, race_edids=race_edids,
                derma=derma, derma_paths=derma_paths, part_type=npc_hair.part_type,
                npc_parts=npc_hair.npc_parts, with_hair_color=npc_hair.with_hair_color, beard_map=beard_map)


def npc_dress(subs, n, npcs, real, row) -> list:
    """The NPC's converted Skyrim hair / beard (from --hairs-plugin, by Skyrim EditorID; a template beard dropped when
    Skyrim gives none) and its hair colour name (npc_records.match_hair_color)."""
    faces = skyrimnpc.faces_by_template(npcs)
    src = npcs.get(faces.get(n["form_id"], n["form_id"]), n)          # whose face (and hair) it wears
    parts = real["npc_parts"](with_race_hair(src, real), real["hdpt"])
    new, info = {}, {}
    beards = real.get("beard_map") or {}
    for kind, (part, _models) in parts.items():
        fid = real["index"].get(part["edid"].lower())
        if kind == npc_records.FACIAL_HAIR and part["edid"] in beards:
            # a vanilla Starfield beard matched by shape (beard_match.py; 2026-11-07, owner's choice)
            m = beards[part["edid"]]
            fid = int(m["form_id"], 16)
            info["facial_hair"] = {"skyrim": part["edid"], "starfield": m.get("starfield"), "form_id": m["form_id"]}
            new[kind] = fid
            continue
        info[{3: "hair", 4: "facial_hair"}.get(kind, str(kind))] = (
            {"skyrim": part["edid"], "form_id": f"{fid:08X}"} if fid else
            {"skyrim": part["edid"], "missing": "not in the hairs plugin (build it with --facial-hair for beards)"})
        if fid:
            new[kind] = fid
    drop = [k for k in (npc_records.HAIR, npc_records.FACIAL_HAIR) if k not in parts]
    subs = npc_records.with_parts(subs, real["sf_hdpt"], new, drop=drop, part_type=real["part_type"])
    color = real["clfm"].get(src.get("hair_color"))
    name, how = npc_records.match_hair_color(color, real["names"], real["palette"])
    if not name and color is None:
        name = npc_records.default_hair_color(real.get("race_edids", {}).get(src.get("race"), ""), real["names"])
        how = "no Skyrim hair colour: the race's usual" if name else how
    if name:
        subs = real["with_hair_color"](subs, name)
    info["hair_color"] = {"skyrim": (color or {}).get("edid"), "skyrim_rgb": list((color or {}).get("rgba") or [])[:3],
                          "starfield": name, "how": how}
    subs, info["face_colors"] = face_colors(subs, src, real, name)
    row["dressed"] = info
    return subs


def target_skin(n, npcs, real):
    """(STON, ethnicity) the converted NPC should have: its Skyrim skin tone tint and race."""
    faces = skyrimnpc.faces_by_template(npcs)
    src = npcs.get(faces.get(n["form_id"], n["form_id"]), n)
    tints, _d = real.get("races", {}).get(src.get("race"), ({}, {}))
    rgb, _how = npc_records.skyrim_skin_rgb(src, tints)
    return npc_records.skin_tone(rgb), FACE_ETHNICITY


def with_race_hair(src, real):
    """The Skyrim NPC with its race's default hair added when it has none of its own (2026-11-06: Nazeem has no head
    parts, wears his race's short hair in Skyrim, and kept the Starfield template's hair)."""
    hdpt = real["hdpt"]
    if any(hdpt.get(f, {}).get("type") == 3 for f in src.get("head_parts", [])):
        return src
    _t, defaults = real.get("races", {}).get(src.get("race"), ({}, {False: [], True: []}))
    hair = [f for f in defaults.get(src.get("female", False), []) if hdpt.get(f, {}).get("type") == 3]
    return dict(src, head_parts=list(src.get("head_parts", [])) + hair[:1]) if hair else src


def skyrim_eye_colour(src, real):
    """(Starfield eye colour name or None, report) from the NPC's Skyrim eyes head part (its own, else its race's
    default; npc_records.eye_color judges by the part's EditorID)."""
    _tints, defaults = real.get("races", {}).get(src.get("race"), ({}, {False: [], True: []}))
    hdpt = real["hdpt"]
    own = [p for p in (hdpt.get(f) for f in src.get("head_parts", [])) if p and p.get("type") == 2]
    eyes, where = (own[0], "own") if own else (next(
        (hdpt[f] for f in defaults.get(src.get("female", False), []) if f in hdpt and hdpt[f].get("type") == 2),
        None), "race default")
    ecol, ehow = npc_records.eye_color(eyes.get("edid") if eyes else None)
    return ecol, {"skyrim": eyes.get("edid") if eyes else None, "from": where, "starfield": ecol, "how": ehow}


def face_colors(subs, src, real, hair_color_name):
    """Eye colour (ECOL, from the Skyrim eyes head part's name), skin tone (STON 0-8, from the skin tone tint) and brow
    colour (BCOL = the hair colour; Skyrim brows take the hair colour) on the test NPC (owner 2026-11-06). NPCs without
    their own eyes use their race's default eyes."""
    tints, _defaults = real.get("races", {}).get(src.get("race"), ({}, {False: [], True: []}))
    ecol, eye_info = skyrim_eye_colour(src, real)
    rgb, shown = npc_records.skyrim_skin_rgb(src, tints)
    ston = npc_records.skin_tone(rgb)
    values = {}
    if ston is not None:
        values[b"STON"] = bytes([ston])
    if ecol:
        values[b"ECOL"] = sfplugin.zs(ecol)
    if hair_color_name:
        values[b"BCOL"] = sfplugin.zs(hair_color_name)
    ethnicity = FACE_ETHNICITY
    derma, dhow = npc_records.choose_dermaesthetic(real.get("derma", []), ethnicity, src.get("female", False), ston)
    placed = False
    if derma:
        subs, placed = npc_records.with_layer_texture(subs, "Dermaesthetic", derma,
                                                      real.get("derma_paths", {}).get(derma))
    info = {"eyes": eye_info,
            "face_skin": {"starfield": derma, "how": dhow, "set": placed},
            "skin": {"skyrim_rgb": rgb, "from": shown, "starfield_ston": ston,
                     "note": "0 = lightest, 8 = darkest (body: verified 2026-11-06)"},
            "brow_color": hair_color_name}
    return npc_records.with_face_colors(subs, values), info


def fo4land_zstring(d) -> str:
    return bytes(d).split(b"\0")[0].decode("latin-1")


def add_hair_files(a, out, sky, esm, sf_data, rows, npcs, chosen, recs, test_subs) -> dict:
    """--hair: convert and pack the test NPCs' Skyrim hair (npc_hair.add_hair), head part records added to recs."""
    import shutil
    import hair_pack
    import npc_hair
    from fo4sf import skyrimconvert
    cr = a.content_resources or os.path.join(a.starfield, "Tools", "ContentResources.zip")
    if not os.path.isfile(cr):
        sys.exit(f"ContentResources.zip (Creation Kit) not found: {cr}")
    staging = os.path.join(out, "_staging")
    shutil.rmtree(staging, ignore_errors=True)
    conv = skyrimconvert.SkyrimConverter(sky, staging, a.texconv, cr, collision_template=None, prefix="s2s")
    sf_esm = os.path.join(sf_data, "Starfield.esm")
    sf_recs = sfplugin.records(sf_esm, [b"HDPT", b"FLST"])
    sf_hdpt = {r[3]: r for r in sf_recs if r[0] == b"HDPT"}
    hdpt, clfm = npc_hair.head_parts(esm)
    res = {}
    if a.hair_legacy:                         # the first conversion: rigid on the head, cutout material
        sf_world = npc_hair.skeleton_world(hkx_to_af.vanilla_file(npc_hair.SF_SKELETON, sf_data)[0])
        npc_hair.add_hair(rows, npcs, chosen, recs, test_subs, a, sky, conv, sf_world, sf_hdpt, hdpt, clfm,
                          staging)
    else:                                     # the looks-menu hair pipeline (scripts/npc/skyrim_hairs.py)
        import argparse as _ap
        import skyrim_hairs
        from fo4sf import smpcloth
        shape = _ap.ArgumentParser()
        hair_pack.add_shape_args(shape)
        shape.set_defaults(**skyrim_hairs.VANILLA_DEFAULTS)
        ctx = shape.parse_args([])
        ctx.skyrim_data, ctx.starfield = a.skyrim_data, a.starfield
        conv.hair_settings = dict(skyrim_hairs.VANILLA_HAIR_SETTINGS)
        rep = res.setdefault("hair_pipeline", {})
        blob = hair_pack.find_template(a.starfield, rep)
        sk = smpcloth.human_skeleton(smpcloth.check_template(blob))
        world = smpcloth.skeleton_world(sk)
        sf_world = {b["name"]: world[i] for i, b in enumerate(sk["bones"])}
        flst = [r for r in sf_recs if r[0] == b"FLST"]
        stem = os.path.splitext(os.path.basename((rep.get("cloth_template") or "").replace("\\", "/")))[0]
        ctxs = {}
        for female in sorted({n["female"] for n in chosen}):
            tpl = skyrim_hairs.chargen_template(sf_hdpt, flst, female, skyrim_hairs.HAIR,
                                                stem if female else stem.replace("_f", "_m"))
            ctxs[female] = skyrim_hairs.sex_context(ctx, sf_world, rep, female, tpl, a.starfield)
        names = {fo4land_zstring(d) for _t, _h, subs, _f in sfplugin.records(sf_esm, [b"NPC_"])
                 for sig, d in subs if sig == b"HCOL"} - {""}
        name = a.hair_color_name or npc_hair.neutral_hair_color(names)
        rep["starfield_hair_colors"] = {"seen": sorted(names), "chosen_for_baked_hair": name}
        npc_hair.add_hair(rows, npcs, chosen, recs, test_subs, a, sky, conv, sf_world, sf_hdpt, hdpt, clfm,
                          staging, ctxs=ctxs, hair_color_name=name)
    base = os.path.splitext(PLUGIN)[0]
    res.update(hair_pack.pack(staging, out, a.starfield, a.archive2, f"{base} - Main.ba2", f"{base} - Textures.ba2"))
    res["converter"] = {"stats": conv.stats, "material_errors": conv.material_errors}
    shutil.rmtree(staging, ignore_errors=True)
    return res


def child_template_looks(rec, sf_hdpt_recs) -> dict:
    """What a vanilla child NPC's look is made of (2026-11-19: Starfield's children have no face layers, dials or
    blends): its STON, hair colour, head parts (EditorID: type), face texture layers (TNAM / QNAM / INTV, any name)
    and which face fields it carries at all."""
    names = {r[3]: (sfplugin.edid(r[2]), hdpt_type(r)) for r in sf_hdpt_recs}
    subs = rec[2]
    parts = [names.get(struct.unpack("<I", bytes(d)[:4])[0], (f"{struct.unpack('<I', bytes(d)[:4])[0]:08X}", None))
             for s_, d in subs if s_ == b"PNAM" and len(d) == 4]
    return {"ston": next((bytes(d)[0] for s_, d in subs if s_ == b"STON" and len(d)), None),
            "hair_color": next((fo4land_zstring(d) for s_, d in subs if s_ == b"HCOL"), None),
            "head_parts": [f"{e} ({t})" for e, t in parts],
            "face_layers": [f"{n}: {t} ({i})" for n, t, i in face_layers(subs)],
            "face_fields": sorted({s_.decode("latin-1") for s_, _d in subs
                                   if s_ in (b"FMRI", b"FMRS", b"FMSI", b"BMPN", b"MSDK", b"TNAM", b"QNAM", b"FTSM",
                                             b"FTST", b"NAM9", b"NAMA", b"MRSV")}),
            "all_fields": sorted({s_.decode("latin-1") for s_, _d in subs})}


CHILD_CONTROLS = ("VanillaHead", "NoFaceSkin", "Tone0", "Tone1", "Tone2")


def child_baked_face(row, n, npcs, real, npc_recs, human, baked, sf_data, out, read=None, fid=None):
    """Pre-built face textures for a child's test NPC, made exactly as an adult test NPC's (2026-11-19, owner: "why
    isnt it following how our npcs faces are done"): the European HumanRace template with a baked face nearest the
    NPC's Skyrim skin tone (pick_template, adult STON from target_skin), its textures copied under the child's FormID
    (fid: another NPC's), recoloured only when the template's tone is TONE_GAP or more from the NPC's
    (human_face_colour, to the adult body tone of that STON; read: game texture path -> bytes). Starfield's child
    head has the adult head's face layout (verified in game 2026-11-19). Was: always recoloured to the child body
    tone texture's median - a tan-orange face over pale hands in game. Returns the report entry."""
    female = row["female"]
    adult = target_skin(n, npcs, real)[0] if real is not None else None
    tpl = pick_template(npc_recs, human, female, None, skin=(adult, FACE_ETHNICITY), baked=baked)
    if tpl is None:
        return "none: no template with a baked face"
    colour, how = (None, None)
    if read is not None:
        colour, how = human_face_colour(tpl[2], adult, female, read)
    fid = int(row["test_npc"]["form_id"], 16) if fid is None else fid
    files = write_baked_face(baked, tpl[3], fid, sf_data, out, colour=colour)
    return {"template": sfplugin.edid(tpl[2]), "template_skin": list(template_skin(tpl[2])), "adult_ston": adult,
            "recoloured": how or "no: the template's own tone", "files": [os.path.basename(f) for f in files]}


def derma_names(npc_recs) -> list:
    """Every Dermaesthetic face skin texture name Starfield's NPCs use (TNAM Dermaesthetic -> its QNAM)."""
    out = set()
    for r in npc_recs:
        layer = None
        for s_, d in r[2]:
            if s_ == b"TNAM":
                layer = fo4land_zstring(d)
            elif s_ == b"QNAM" and layer == "Dermaesthetic":
                out.add(fo4land_zstring(d))
    return sorted(out)


def child_skin_choices(names, female, count=4) -> list:
    """European face skins for a child to try (2026-11-19, owner: "he's not quite white skinned" on Bobby Katz's
    European_Male_Md1_Sk1): the young (yo1) phenotype's, else the md1's, lowest Sk numbers first, as the game names
    them (which Sk is lightest is not known: compared in game)."""
    sex = "female" if female else "male"
    got = {}
    for n in names:
        m = re.match(r"^european_(male|female)_(yo1|md1)_sk(\d+)$", n, re.I)
        if m and m.group(1).lower() == sex:
            got.setdefault(m.group(2).lower(), []).append((int(m.group(3)), n))
    for ph in ("yo1", "md1"):
        if got.get(ph):
            return [n for _k, n in sorted(got[ph])[:count]]
    return []


def with_derma(subs, name):
    """subs with the Dermaesthetic face layer's texture (QNAM) set to name (unchanged without such a layer)."""
    out, layer = [], None
    for s_, d in subs:
        if s_ == b"TNAM":
            layer = fo4land_zstring(d)
        elif s_ == b"QNAM" and layer == "Dermaesthetic":
            d = sfplugin.zs(name)
        out.append((s_, d))
    return out


def add_child_controls(rows, recs, test_subs, masters, skins=None, tone_variants=None):
    """--child-controls (2026-11-19, owner: Frodnar reads African; vanilla children differ only by STON,
    hair and hair colour - no face head parts, layers or dials - so their look is the race's one child head plus the
    face tone of their STON): copies of each child's finished test NPC (its hair included) with Starfield's own
    child head (our Face part left out: the race's) at its STON, without the donor face skin layer, and with our head
    at each child STON 0 / 1 / 2, to tell the head shape from the skin and the tone. Row "control_npcs": {variant: console}."""
    for row in rows:
        tn = row.get("test_npc")
        if not row.get("child") or not isinstance(tn, dict) or row["edid"] not in test_subs:
            continue
        t, h, subs, _fid = recs[test_subs[row["edid"]]]
        head = int(tn["head_part"], 16)
        out = {}
        variants = list(CHILD_CONTROLS) + [f"Skin_{n}" for n in (skins or {}).get(bool(row.get("female")), [])]
        if tone_variants is not None:       # 2026-11-19: only the face strength copies (the rest have done their job)
            if tn.get("ston") not in tone_variants.values():
                continue                       # a child on a vanilla tone: nothing to compare
            variants = [k for k, st in tone_variants.items() if st != tn.get("ston")]
        for v in variants:
            if tone_variants is not None and v in tone_variants:
                vs = npc_records.with_face_colors(list(subs), {b"STON": bytes([tone_variants[v]])})
            elif v == "VanillaHead":
                vs = [(s_, d) for s_, d in subs if not (s_ == b"PNAM" and len(d) == 4 and
                                                        struct.unpack("<I", bytes(d))[0] == head)]
            elif v == "NoFaceSkin":          # without the donor's face skin layer (the race's default face)
                import child_faces
                vs = [(s_, d) for s_, d in subs if s_ not in child_faces.FACE_SIGS]
            elif v.startswith("Skin_"):           # another European face skin
                vs = with_derma(list(subs), v[len("Skin_"):])
            else:
                vs = npc_records.with_face_colors(list(subs), {b"STON": bytes([int(v[-1])])})
            vs = sfplugin.edit(vs, {b"EDID": sfplugin.zs(f"S2SFaceControl_{row['edid']}_{v}"),
                                    b"FULL": sfplugin.zs(f"{row.get('name') or row['edid']} ({v})")})
            fid = sfplugin.new_form_id(len(recs), masters=len(masters))
            recs.append((t, h, vs, fid))
            out[v] = f"player.placeatme xx{fid & 0xFFFFFF:06X}"
        row["control_npcs"] = out


def child_npc_survey(npc_recs, child_race, sf_hdpt_recs) -> list:
    """Every ChildRace NPC of Starfield.esm with what its look is made of (child_template_looks), its template (TPLT,
    by EditorID) and whether it has a voice (2026-11-19, owner: the NG+ children playing the Constellation are among
    the few children with looks of their own; templated ones are not offered as templates, so they were not listed)."""
    edids = {fid: sfplugin.edid(sb) for _t, _h, sb, fid in npc_recs}
    out = []
    for r in npc_recs:
        subs = r[2]
        if next((struct.unpack("<I", bytes(d)[:4])[0] for s_, d in subs if s_ == b"RNAM" and len(d) >= 4), None) \
                != child_race:
            continue
        acbs = next((bytes(d) for s_, d in subs if s_ == b"ACBS"), b"")
        tplt = next((struct.unpack("<I", bytes(d)[:4])[0] for s_, d in subs if s_ == b"TPLT" and len(d) >= 4), None)
        out.append(dict({"edid": sfplugin.edid(subs), "form_id": f"{r[3]:08X}",
                         "female": bool(acbs and struct.unpack_from("<I", acbs, 0)[0] & 1),
                         "template": edids.get(tplt, f"{tplt:08X}") if tplt is not None else None,
                         "voiced": any(s_ == b"VTCK" for s_, _d in subs)},
                        **child_template_looks(r, sf_hdpt_recs)))
    return sorted(out, key=lambda x: x["edid"].lower())


def child_tone_order(sf_esm, sf_data, females) -> dict:
    """{female: [slot, ...] lightest first} of Starfield's child skin tones (child_hair.child_tone_slots), plus
    "_report"; a sex whose textures cannot be read is left out (reported)."""
    import child_hair
    import skin_tone_probe
    from fo4sf import skintone
    out, rep = {}, {}
    try:
        recs = sfplugin.records(sf_esm, [b"RACE", b"AVMD"])
        arcs = skin_tone_probe.TextureArchives(sf_data)
    except (OSError, ValueError) as e:
        return {"_report": {"error": str(e)}}
    for female in sorted(set(females)):
        sex = "female" if female else "male"
        try:
            got = child_hair.child_tone_slots(recs, arcs.read, female, skintone.decode_dds)
            out[female] = got["slots"]
            rep[sex] = got
        except (KeyError, ValueError, OSError) as e:
            rep[sex] = {"error": f"{type(e).__name__}: {e}"}
        try:          # 2026-11-19: the face's tone group, for comparison (its slots may run another way)
            rep[sex + "_face"] = child_hair.child_tone_slots(recs, arcs.read, female, skintone.decode_dds, b"FSTT")
        except (KeyError, ValueError, OSError) as e:
            rep[sex + "_face"] = {"error": f"{type(e).__name__}: {e}", "fields": getattr(e, "fields", None)}
    out["_report"] = rep
    return out


def add_child_light_tone(sf_esm, sf_data, out, recs, rows=(), sky=None, texconv="") -> dict:
    """child_hair.light_child_tone: its AVMD overrides added to recs (face_fit adds them after every new record:
    2026-11-19, owner: "did his ID change" - in the middle they shifted Frodnar's FormID), its face texture written (uncompressed RGBA8
    sRGB) under out/textures/. Returns {"index": STON, ...report} or {"error": ...}."""
    import child_hair
    import skin_tone_probe
    from fo4sf import skintone
    painted = {r["edid"]: r for r in rows if ((r.get("child") or {}).get("paint") or {}).get("file")}

    def paint(edid, face_rgba):
        return child_paint_face(painted[edid], sky, texconv, out)(edid, face_rgba)
    try:
        got = child_hair.light_child_tone(sfplugin.records(sf_esm, [b"RACE", b"AVMD"]),
                                          skin_tone_probe.TextureArchives(sf_data).read, skintone.decode_dds,
                                          children=[(e, bool(r.get("female"))) for e, r in painted.items()],
                                          paint=paint)
    except (KeyError, ValueError, OSError) as e:
        return {"error": f"{type(e).__name__}: {e}"}
    for rel, rgba in got["textures"].items():
        path = os.path.join(out, "textures", *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(skintone.raw_dds(rgba))
    recs.extend(got["records"])
    main = child_hair.FACE_LEVELS[child_hair.FACE_MAIN][0]
    return {"index": got["indices"][main], "main": main, "indices": got["indices"],
            "children": got.get("children", {}), "groups": got["report"], "textures": sorted(got["textures"])}


def add_child_hair_files(a, out, sky, sf_data, rows, by_edid, recs, test_subs, masters, real, child_ctx) -> dict:
    """The children's own hair from their FaceGen NIFs (scripts/npc/child_hair.py), each a head part of ours copied
    from its template child's hair and put on its test NPC, its hair colour matched (with --hairs-plugin); files
    packed as "S2SFaceTest - Main.ba2" / "- Textures.ba2" (Archive2) or loose. Needs --texconv. Fills row["hair"]."""
    import shutil
    import child_faces
    import child_hair
    import hair_pack
    import npc_hair
    import skyrim_hairs
    from fo4sf import skyrimconvert, skyrimhair
    cr = a.content_resources or os.path.join(a.starfield, "Tools", "ContentResources.zip")
    if not os.path.isfile(cr):
        return {"error": f"ContentResources.zip (Creation Kit) not found: {cr}"}
    try:
        sf_world = child_hair.child_world(hkx_to_af.vanilla_file(child_hair.CHILD_SKELETON, sf_data)[0])
    except (SystemExit, KeyError, OSError, ValueError, nifmod.NifError) as e:
        return {"error": f"child skeleton {child_hair.CHILD_SKELETON}: {e}"}
    staging = os.path.join(out, child_hair.STAGING)
    shutil.rmtree(staging, ignore_errors=True)
    conv = skyrimconvert.SkyrimConverter(sky, staging, a.texconv, cr, collision_template=None, prefix="s2s")
    conv.hair_settings = dict(skyrim_hairs.VANILLA_HAIR_SETTINGS)
    sf_hdpt = {r[3]: r for r in sfplugin.records(os.path.join(sf_data, "Starfield.esm"), [b"HDPT"])}
    hdpt = (child_ctx.get("_sky") or (None, None))[1] or npc_hair.head_parts(a.load_order)[0]
    settings = child_hair.shape_settings(a.starfield)
    res = {"child_skeleton_C_Head_m": [round(float(v), 4) for v in sf_world[skyrimhair.SF_HEAD][:3, 3]],
           "facebones": {}}
    fbs, done = {}, 0
    for row in rows:
        if not row.get("child") or not isinstance(row.get("test_npc"), dict) or row["edid"] not in test_subs:
            continue
        n = by_edid[row["edid"].lower()]
        info = row["hair"] = {}
        names = child_hair.hair_shape_names(n, hdpt)
        if not names:
            info["note"] = "no hair head part on the Skyrim NPC: the template's hair"
            continue
        info["skyrim"] = names[0]
        try:
            fg_rel = facegen_mesh(a.load_order, n["form_id"])
            fg = hkx_to_af.read_any(fg_rel, sky)
            shapes = child_hair.facegen_hair_shapes(fg, names)
            info["facegen_shapes"] = [x["name"] for x in shapes]
            if not shapes:
                info["error"] = f"no shape named {', '.join(names)} in its FaceGen NIF: the template's hair"
                continue
            names, shapes, left = child_hair.usable_shapes(names, shapes, sky)
            if left:
                info["left_out"] = left
            if not shapes:
                info["error"] = (f"textures not in the Skyrim load order: {', '.join(sorted(set(left.values())))} "
                                 "(KS Hairdos: add its mod folder with --skyrim-mod): the template's hair")
                continue
            k = test_subs[row["edid"]]
            tpl = npc_hair.starfield_part_template(recs[k][2], sf_hdpt, child_hair.HAIR, n["female"])
            if tpl is None:
                info["error"] = "no Starfield hair head part to copy"
                continue
            model = skyrim_hairs.record_model(tpl)
            if model not in fbs:
                frep = res["facebones"].setdefault(model, {})
                fbs[model] = hair_pack.facebones_template(a.starfield, model, frep,
                                                          "x:meshes/" + model.replace("\\", "/"))
            ctx = child_context(n, sky, sf_data, a, child_ctx, transfer="none")
            fgp = child_faces.facegen_points(ctx, sys.modules[__name__], fg)
            head_nif = next((f for f in row["child"].get("files", [])
                             if f.lower().endswith(f"/{row['edid'].lower()}head.nif")), None)
            surface = child_hair.baked_surface(a.starfield, out, head_nif) if head_nif else None
            pre = hair_lift_matrix(row)
            hrow = child_hair.build_child_hair(row["edid"], n["female"], fg, fg_rel, names, ctx, fgp, sf_world,
                                               surface, fbs[model], conv, staging, settings, pre)
        except (skyrimhair.HairError, nifmod.NifError, ValueError, KeyError, OSError) as e:
            info["error"] = f"{type(e).__name__}: {e}"
            continue
        info.update({x: hrow[x] for x in ("placement", "fit", "follow_head", "conform", "dropped_duplicate_shapes",
                                          "shapes", "vertices", "materials", "face_bones", "skipped",
                                          "template_reference") if x in hrow})
        info["head_surface"] = "its baked head" if surface is not None else "none found: not conformed"
        if not hrow.get("ok"):
            info["error"] = hrow.get("reason") or "not converted"
            continue
        fid = sfplugin.new_form_id(len(recs), masters=len(masters))
        recs.append(npc_hair.head_part_record(tpl, fid, f"S2S_ChildHair_{row['edid']}", hrow["model"]))
        t, h, subs, nfid = recs[k]
        subs = child_hair.hair_record_subs(subs, sf_hdpt, fid)
        if real is not None:
            color = real["clfm"].get(n.get("hair_color"))
            name, how = npc_records.match_hair_color(color, real["names"], real["palette"])
            if name:
                subs = real["with_hair_color"](subs, name)
            info["hair_color"] = {"skyrim": (color or {}).get("edid"),
                                  "skyrim_rgb": list((color or {}).get("rgba") or [])[:3], "starfield": name,
                                  "how": how}
        recs[k] = (t, h, subs, nfid)
        info.update(model=hrow["model"], form_id=f"{fid:08X}", starfield_template=sfplugin.edid(tpl[2]))
        done += 1
    res["children_with_own_hair"] = done
    if done:
        base = os.path.splitext(PLUGIN)[0]
        res.update(hair_pack.pack(staging, out, a.starfield, a.archive2, f"{base} - Main.ba2",
                                  f"{base} - Textures.ba2"))
    res["converter"] = {"stats": conv.stats, "material_errors": conv.material_errors}
    shutil.rmtree(staging, ignore_errors=True)
    return res


def outfits_by_npc(path: str, master_index: int) -> dict:
    """{Skyrim NPC EditorID, lower case: FormID as seen from the plugin that has `path` as master number
    master_index} of the outfits gear_fit wrote (EDID S2S_<NPC>_outfit_Outfit)."""
    out = {}
    for _t, _h, subs, fid in sfplugin.records(path, [b"OTFT"]):
        e = sfplugin.edid(subs)
        m = re.match(r"S2S_(.+)_outfit_Outfit$", e, re.I)
        if m:
            out[m.group(1).lower()] = (master_index << 24) | (fid & 0xFFFFFF)
    return out


def item_outfits(path: str, master_index: int) -> dict:
    """{our OTFT EditorID, lower case: FormID as seen from the plugin that has `path` as master number master_index}
    of item_convert.py's outfits (S2S_<Skyrim OTFT EditorID>)."""
    return {sfplugin.edid(subs).lower(): (master_index << 24) | (fid & 0xFFFFFF)
            for _t, _h, subs, fid in sfplugin.records(path, [b"OTFT"]) if sfplugin.edid(subs)}


def npc_item_outfit(npc: dict, sky_otft: dict, items: dict):
    """(FormID, Skyrim OTFT EditorID) of the converted outfit a Skyrim NPC's default outfit became, or (None, why)."""
    e = sky_otft.get(npc.get("outfit"))
    if not e:
        return None, "no default outfit in Skyrim"
    fid = items.get(f"s2s_{e}".lower())
    return (fid, e) if fid is not None else (None, f"{e} not converted (item_convert.py --npc {npc.get('edid')})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--skyrim-mods-dir", default="",
                    help="folder of Skyrim mod folders (MO2: <ModOrganizer>/Skyrim Special Edition/mods), for --skyrim-mod names")
    ap.add_argument("--skyrim-mod", action="append", default=[],
                    help="a Skyrim mod folder (name under --skyrim-mods-dir, or a path), repeatable, in load order: its "
                         "plugins override Skyrim.esm, its BSAs and loose files Skyrim's (src/fo4sf/skyrimload.py)")
    ap.add_argument("--starfield", required=True, help="Starfield install folder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--npc", action="append", default=[], help="Skyrim NPC EditorID (repeatable)")
    ap.add_argument("--count", type=int, default=12, help="sample size without --npc")
    ap.add_argument("--legacy-alignment", action="store_true",
                    help="the old Skyrim -> Starfield head alignment (ICP on the raw mesh, 90 degrees off; 2026-11-09) "
                         "instead of model space through the head's node transform, to compare")
    ap.add_argument("--transfer", choices=["surface", "nearest"], default="surface",
                    help="Skyrim face -> Starfield head: surface (a point on the Skyrim surface per Starfield vertex, "
                         "seams welded; fo4sf.headcorr, 2026-11-09) or nearest (the old 4-nearest-vertex average)")
    ap.add_argument("--regions", help="facial bone regions file to use instead of the game's (per sex: give twice, "
                                      "male first)", action="append", default=[])
    ap.add_argument("--head-nif", action="append", default=[], help="head NIF instead of the game's (male, female)")
    ap.add_argument("--facebones-recipe",
                    help="a face-bone mod's weight recipe (More Sliders: SFSE\\Plugins\\MoreSlidersFaceBones\\"
                         "MoreSlidersFaceBones_recipe.txt), with that mod's --regions and --head-nif: its new bones' "
                         "sliders then move the head in the fit as they do in game")
    ap.add_argument("--keep-blend-morphs", action="store_true",
                    help="keep the template's blend morph presets (BMPN / BMPV: female_af_md1_Mouth ...) and morph "
                         "region data (FMRI / FMRG) instead of removing them (2026-11-06: Saadia's record matched her "
                         "dark template in every colour field and her face was still white: the base face skin seems "
                         "to come from these presets). The template's blend also changes the face shape.")
    ap.add_argument("--no-baked-face-textures", dest="baked_face_textures", action="store_false",
                    help="do not copy a template's pre-built face textures (_color / _normal / _rough / _ao) under each "
                         "test NPC's FormID (default: copy them, choosing templates that have them; without, "
                         "Starfield shows a default light face: verified in game 2026-11-06)")
    ap.add_argument("--control-npcs", action="store_true",
                    help="also write each NPC with its template's own face data (our hair, colours, outfit, name), "
                         "'<name> (template face)': tells whether our face dials cause the light faces")
    ap.add_argument("--ridge", type=float, default=0.05,
                    help="cost of each dial's size, relative to an average dial's effect (2026-11-05: at 1e-6 More "
                         "Sliders' 307 sliders fought each other at +-1 and Ralof came out deformed; 0 = off)")
    ap.add_argument("--no-symmetry", action="store_true",
                    help="fit the Skyrim face as it is, not averaged with its mirror image")
    ap.add_argument("--pos-unit", type=float, default=0.01, help="metres per regions-file position unit")
    ap.add_argument("--test-plugin", action="store_true")
    ap.add_argument("--beard-map", help="beard_match.py's beard_match.json: Skyrim beards worn as the matched vanilla "
                                        "Starfield beards (with --hairs-plugin)")
    ap.add_argument("--items-plugin", help="S2SClothes.esm from scripts/armor/item_convert.py: each test NPC wears "
                                           "the converted outfit its Skyrim default outfit became (before "
                                           "--outfits-plugin's per-NPC outfit); the plugin becomes a master")
    ap.add_argument("--outfits-plugin", help="S2SArmorTest.esm from scripts/armor/gear_fit.py: each test NPC wears the "
                                             "outfit made for it there (gear_fit --name <NPC EditorID>_outfit), as "
                                             "default and space outfit; the plugin becomes a master")
    ap.add_argument("--body-npc", action="append", default=[],
                    help="Starfield NPC EditorID whose body (MWGT / MRSV) the test NPCs get (male, then female; "
                         f"default {BODY_NPC[0]}, {BODY_NPC[1]}; 'none' keeps each template's)")
    ap.add_argument("--template-npc", action="append", default=[],
                    help="Starfield NPC EditorID the test NPCs copy (male, then female); default: a plain one")
    ap.add_argument("--no-elder-template", action="store_true",
                    help="Elder-race NPCs on the generic template too (default: the generic old one, "
                         "pick_elder_template: its baked face carries Starfield's age wrinkles)")
    ap.add_argument("--template-by-tone", action="store_true",
                    help="pick each NPC's template by skin tone (before 2026-11-12) instead of the generic one per sex "
                         f"({', '.join(GENERIC_TEMPLATE)})")
    ap.add_argument("--child-controls", action="store_true",
                    help="with --test-plugin: each child also as copies with Starfield's own child head and with "
                         "its head at child skin tone 0 / 1 / 2 (head shape vs tone in game)")
    ap.add_argument("--hair", action="store_true",
                    help="with --test-plugin: the test NPCs wear their Skyrim hair and beard (needs --texconv)")
    ap.add_argument("--texconv", help="texconv.exe, for --hair")
    ap.add_argument("--content-resources", help="default: <Starfield>/Tools/ContentResources.zip (for --hair)")
    ap.add_argument("--archive2", help="default: <Starfield>/Tools/Archive2/Archive2.exe")
    ap.add_argument("--smooth", type=int, default=10,
                    help="smooth the Skyrim face's displacement over Starfield's head this many steps before the fit "
                         "(0: off; 2026-11-05: lumpy at Skyrim's vertex spacing)")
    ap.add_argument("--dial-limit", type=float, default=1.0,
                    help="largest dial value (1 = the looks menu's range; e.g. 1.5 to test whether the game takes "
                         "more: the fit hit 1.0 on 8 of Ralof's dials)")
    ap.add_argument("--no-blends", action="store_true",
                    help="fit only the face sliders (dials), not Starfield's shape blends (the head morph.dat's "
                         "phenotype keys, written as BMPN / BMPV); the fit before 2026-11-12")
    ap.add_argument("--blend-ethnicity", default=",".join(BLEND_ETHNICITIES),
                    help="which phenotype keys may be blended (comma list of the keys' ethnicity codes, or 'all'; "
                         "default eu: the generic western faces, owner 2026-11-12)")
    ap.add_argument("--refit", action="store_true",
                    help="fit every NPC again (default: an NPC whose FaceGen head, race, fit settings and fitting "
                         "code are unchanged since the last run reuses that fit; the plugin is always rewritten)")
    ap.add_argument("--shape-npc", action="append", default=[],
                    help="this adult (repeatable) gets its own head, fitted feature by feature as the children's "
                         "(fo4sf.childshape) on its race's head, instead of Starfield's face dials")
    ap.add_argument("--child-shape-npc", action="append", default=[],
                    help="this child (repeatable) gets its own face shape fitted feature by feature (fo4sf.childshape) "
                         "instead of its FaceGen difference from the base child head")
    ap.add_argument("--preview-npc", action="append", default=[],
                    help="like --preview for this NPC only (repeatable; the others reuse their fits)")
    ap.add_argument("--preview", action="store_true",
                    help="faces_preview\\<NPC>.png per NPC: Starfield's base head, the Skyrim face on it (the fit's "
                         "target), our fitted face; front, side, and a heat map of each one's change from the base")
    ap.add_argument("--races-plugin", help="race_heads.py's S2SRaceTest.esm (race_heads.json beside it): NPCs of a "
                                           "converted Skyrim race go on that race, with its head and face parts, and "
                                           "only their own features are fitted (2026-11-10)")
    ap.add_argument("--hairs-plugin",
                    help="S2SSkyrimHairs.esm (scripts/npc/skyrim_hairs.py): the NPCs wear its converted looks-menu "
                         "hair / beard of their Skyrim head parts (it becomes a master), get their Skyrim names and the "
                         "Starfield hair colour closest to their Skyrim one (owner 2026-11-05); instead of --hair")
    ap.add_argument("--hair-colors", help="hair_color_probe.py's hair_colors.json ({name: [r, g, b]}), for "
                                          "--hairs-plugin's colour match (else by colour words)")
    ap.add_argument("--voice-lines", help="skyrim_voice.py's --out folder (lines.json + converted .wem / .ffxanim): the "
                                          "NPCs get their own voice type and their Skyrim greetings (needs "
                                          "--test-plugin); files go under <--out>\\Sound\\Voice")
    ap.add_argument("--strings-language", default="english", help="Skyrim string tables for the NPCs' names")
    ap.add_argument("--hair-legacy", action="store_true",
                    help="with --hair: the first conversion (rigid, cutout material, no _facebones twin) instead of the "
                         "looks-menu hair pipeline (fitted, Starfield's hair shader)")
    ap.add_argument("--hair-color-name",
                    help="with --hair: the Starfield hair colour name (HCOL) the test NPCs get; the Skyrim colour is "
                         "baked into the hair, so a light one (default: the lightest-sounding one the game's NPCs use)")
    ap.add_argument("--hair-tint-gain", type=float, default=1.0,
                    help="hair colour baked into the texture as texture x colour x gain (Skyrim's tint strength "
                         "unverified)")
    a = ap.parse_args(argv)
    if a.hair and not (a.test_plugin and a.texconv):
        sys.exit("--hair needs --test-plugin and --texconv")
    if a.beard_map and not a.hairs_plugin:
        sys.exit("--beard-map works with --hairs-plugin (the NPCs' converted hair / beard): add it")
    if a.beard_map and not os.path.isfile(a.beard_map):
        sys.exit(f"--beard-map not found: {a.beard_map}")
    if a.hairs_plugin and a.hair:
        sys.exit("--hairs-plugin and --hair both give the NPCs hair: pick one")
    if a.hairs_plugin and not os.path.isfile(a.hairs_plugin):
        sys.exit(f"--hairs-plugin not found: {a.hairs_plugin}")
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(out, exist_ok=True)
    sf_data = os.path.join(a.starfield, "Data")
    mods = skyrimload.mod_folders(a.skyrim_mods_dir, a.skyrim_mod)
    if mods:                                   # 2026-11-19: Skyrim with mods over it (children: RS Children ...)
        esm = skyrimload.LoadOrder(a.skyrim_data, mods)
        sky = esm.archives
        print(f"Skyrim load order: {', '.join(esm.loaded())}"
              + (f" (masters not loaded: {', '.join(esm.missing)})" if esm.missing else ""))
    else:
        sky = bsa.SkyrimArchives(a.skyrim_data)
        esm = os.path.join(a.skyrim_data, "Skyrim.esm")
    a.load_order = esm

    races = {fid: sfplugin.edid(s) for _t, _h, s, fid in skyrimload.records(esm, [b"RACE"])}
    npcs = {fid: skyrimnpc.parse_npc(s, fid) for _t, _h, s, fid in skyrimload.records(esm, [b"NPC_"])}
    faces = skyrimnpc.faces_by_template(npcs)
    by_edid = {n["edid"].lower(): n for n in npcs.values()}
    chosen = [by_edid[e.lower()] for e in (a.npc or SAMPLE) if e.lower() in by_edid]
    missing = [e for e in (a.npc or []) if e.lower() not in by_edid]
    if missing:
        print(f"not in Skyrim.esm (EditorIDs, check the spelling): {', '.join(missing)}")
    if not a.npc:
        for n in sorted(npcs.values(), key=lambda n: n["edid"]):
            if len(chosen) >= a.count:
                break
            if n not in chosen and races.get(n["race"]) in HUMAN_RACES and n["full_name_id"] is not None \
                    and faces[n["form_id"]] == n["form_id"]:
                chosen.append(n)
        chosen = chosen[:a.count]
    print(f"{len(npcs)} Skyrim NPCs; fitting {len(chosen)}: {', '.join(n['edid'] for n in chosen)}")

    report = {"settings": {"pos_unit": a.pos_unit, "smooth": a.smooth, "dial_limit": a.dial_limit,
                           "ridge": a.ridge, "symmetric": not a.no_symmetry}, "sexes": {},
              "npcs": []}
    setup = {}
    recipe = None
    base_bytes_of, race_cache = {}, {}
    conv_races = converted_races(a.races_plugin) if a.races_plugin else {}
    if conv_races:
        report["races_plugin"] = {"plugin": os.path.basename(a.races_plugin),
                                  "races": {k: f"S2S_{v['name']}Race" for k, v in conv_races.items()}}
    if a.facebones_recipe:
        with open(a.facebones_recipe, encoding="utf-8", errors="replace") as fh:
            recipe = facefit.load_recipe(fh.read())
    def sex_setup(female):
        """Starfield's head, Skyrim's base head aligned on it and the correspondence, for one sex: made the first
        time an NPC of that sex is fitted (2026-11-12: a run whose NPCs are all reused makes none)."""
        if female in setup:
            return setup[female]
        reg_file = a.regions[int(female)] if len(a.regions) > int(female) else None
        if reg_file:
            with open(reg_file, encoding="utf-8") as fh:
                text = fh.read()
        else:
            text = hkx_to_af.vanilla_file(SF_REGIONS[female], sf_data)[0].decode("utf-8", "replace")
        sliders = facefit.load_regions(text)
        head, hrep = starfield_head(sf_data, female, a.head_nif[int(female)] if len(a.head_nif) > int(female) else None,
                                    recipe)
        base_bytes = hkx_to_af.read_any(SKY_HEADS[female], sky)
        base_bytes_of[female] = base_bytes
        base, al, model_space = head_alignment(head, base_bytes, legacy=a.legacy_alignment)
        corr = None
        if a.transfer == "surface" and getattr(head, "triangles", None) is not None and len(head.triangles):
            s_, R_, t_ = al[:3]
            node = getattr(head, "model_xf", None)
            corr = headcorr.correspond(s_ * base @ R_.T + t_, skyrim_head_triangles(base_bytes), head.vertices,
                                       head.triangles, to_model=np.asarray(node, float) if model_space and
                                       node is not None else None)
        blend_set, brep = None, None
        if not a.no_blends:
            try:
                import race_probe
                from fo4sf import sfmorph
                sex_name = "female" if female else "male"
                mdata, mrel = hkx_to_af.vanilla_file(race_probe.SF_MORPH.format(sex=sex_name, part="head"), sf_data)
                morph = sfmorph.parse(mdata)
                if morph.num_vertices != len(head.vertices):
                    brep = {"error": f"head morph.dat has {morph.num_vertices} vertices, the head {len(head.vertices)}"}
                else:
                    eth = tuple(x.strip().lower() for x in a.blend_ethnicity.split(","))
                    names, D, groups = head_blends(morph, len(head.vertices), female, eth)
                    blend_set = (names, D, groups) if names else None
                    brep = {"morph": mrel, "offered": len(names), "regions": sorted(set(groups)), "ethnicities": eth}
            except (SystemExit, KeyError, OSError, ValueError) as e:
                brep = {"error": str(e)[:200]}
        setup[female] = (sliders, head, base, al, model_space, corr, blend_set)
        report["sexes"]["female" if female else "male"] = dict(
            hrep, sliders=len(sliders), skyrim_base_vertices=len(base), alignment_scale=al[0],
            alignment_rms_m=al[3], alignment_rotated=bool(not np.allclose(al[1], np.eye(3))),
            alignment="model space via the head node (2026-11-09)" if model_space else "legacy ICP on the mesh",
            transfer="surface (headcorr)" if corr is not None else "nearest vertices",
            correspondence=corr.report if corr is not None else None, shape_blends=brep)
        if dial_ids_of[0] is None:
            dial_ids_of[0] = race_dials(os.path.join(sf_data, "Starfield.esm"))
        ids = {s.id for s in sliders}
        rd = set(dial_ids_of[0][female])
        report["sexes"]["female" if female else "male"]["race_dials"] = {
            "count": len(rd), "also_slider_ids": len(rd & ids), "slider_ids_not_dials": len(ids - rd)}
        return setup[female]

    dial_ids_of = [None]
    fit_cache = load_fit_cache(out)
    code_hash = {False: fit_code_hash(), True: fit_code_hash(child=True)}
    settings_now = fit_settings(a, sf_data)
    reused = []

    child_ctx = {}
    for n in chosen:
        row = {"edid": n["edid"], "form_id": f"{n['form_id']:08X}", "female": n["female"]}
        sky_race = races.get(n["race"], "")
        key = None
        if not previewing(a, n) and not a.refit:
            try:
                fg_bytes = hkx_to_af.read_any(facegen_mesh(esm, n["form_id"]), sky)
                key = npc_fit_key(code_hash["child" in sky_race.lower()], settings_now, fg_bytes, sky_race,
                                  sky_race in conv_races,
                                  ("child_shape",) if "child" in sky_race.lower() and uses_child_shape(a, n) else
                                  (("own_head", code_hash[True]) if uses_adult_shape(a, n) else None))
            except (SystemExit, KeyError, OSError):
                key = None
            hit = cached_fit(fit_cache, n["edid"], key, out) if key else None
            if hit is not None:
                hit["fit_reused"] = True
                report["npcs"].append(hit)
                reused.append(n["edid"])
                for sx, srep in (fit_cache.get("_sexes") or {}).items():
                    report["sexes"].setdefault(sx, srep)
                continue

        def remember(r):
            if key and "error" not in r:
                fit_cache[n["edid"].lower()] = {"key": key, "row": r}
            else:
                fit_cache.pop(n["edid"].lower(), None)
        if "child" in sky_race.lower():
            # 2026-11-12: Skyrim's children (NordRaceChild ...) get their own face baked into a head of their own on
            # Starfield's child head (child_faces); no dials (Starfield's children have none)
            try:
                row.update(child_face(n, races.get(n["race"]), sky, sf_data, out, a, child_ctx))
            except (SystemExit, ValueError, KeyError, OSError, nifmod.NifError) as e:
                row["error"] = f"child ({races.get(n['race'])}): {e}"
            remember(row)
            report["npcs"].append(row)
            print({k: v for k, v in row.items() if k != "dials"})
            continue
        try:
            sliders, head, base, al, model_space, corr, blend_set = sex_setup(n["female"])
            fg = skyrim_head(hkx_to_af.read_any(facegen_mesh(esm, n["form_id"]), sky),
                             model=model_space)
            if fg is None or len(fg) != len(base):
                raise ValueError(f"FaceGen head has {0 if fg is None else len(fg)} vertices, base head {len(base)}")
            ref = base
            sky_race = races.get(n["race"], "")
            if conv_races and sky_race in conv_races:
                rd = race_delta(sky, n["female"], sky_race, base_bytes_of[n["female"]], model_space, race_cache)
                if rd is not None and len(rd) == len(base):
                    ref = base + rd                       # only the NPC's own features are fitted
                    row["race"] = {"skyrim": sky_race, "converted": f"S2S_{conv_races[sky_race]['name']}Race",
                                   "fitted_against": "Skyrim base head + race morph"}
            if corr is not None:
                disp = corr.transfer((fg - ref) @ al[1].T * al[0], a.smooth)
            else:
                disp = facefit.transfer(ref, fg, al, head.vertices)
                if a.smooth and getattr(head, "triangles", None) is not None and len(head.triangles):
                    disp = facefit.smooth_field(disp, head.triangles, a.smooth)
            if not a.no_symmetry:
                disp = facefit.symmetrize(disp, head.vertices)
            values, rep = facefit.fit(head, sliders, head.vertices + disp, facefit.face_weights(head),
                                      pos_unit=a.pos_unit, limit=a.dial_limit, ridge=a.ridge,
                                      blends=(blend_set[0], blend_set[1]) if blend_set else None,
                                      blend_groups=blend_set[2] if blend_set else None)
            names = {s.id: f"{s.region}: {s.name}" for s in sliders}
            if previewing(a, n) and getattr(head, "triangles", None) is not None and len(head.triangles):
                shaped = head
                if rep.get("blends") and blend_set:
                    bw = np.array([rep["blends"].get(k, 0.0) for k in blend_set[0]])
                    shaped = facefit._with_vertices(head, head.vertices + np.tensordot(bw, blend_set[1], axes=1))
                fitted = facefit.deform(shaped, sliders, values, pos_unit=a.pos_unit)
                os.makedirs(os.path.join(out, "faces_preview"), exist_ok=True)
                png = os.path.join(out, "faces_preview", f"{n['edid']}.png")
                hair_probe.write_png(png, facepreview.sheet([head.vertices, head.vertices + disp, fitted],
                                                            head.triangles))
                row["preview"] = png
            row.update(rep, dials={str(k): round(v, 4) for k, v in sorted(values.items())},
                       dial_names={str(k): names.get(k, "") for k in sorted(values)},
                       skyrim_face_change_m=float(np.sqrt(np.mean(np.sum(disp ** 2, 1)))))
            if uses_adult_shape(a, n):     # its own head instead of the dials (the children's way)
                try:
                    own = adult_own_head(n, fg, hkx_to_af.read_any(facegen_mesh(esm, n["form_id"]), sky), al,
                                         model_space, base, base_bytes_of[n["female"]],
                                         conv_races.get(sky_race) if conv_races else None, a.races_plugin,
                                         sf_data, out, a, child_ctx)
                    row["own_head"] = own
                    row["dials_fitted"] = row.pop("dials")
                    row["dials"] = {}
                    if row.get("blends"):          # no shape blends on top of its own head either
                        row["blends_fitted"] = row.pop("blends")
                except (ValueError, KeyError, OSError, SystemExit, nifmod.NifError) as e:
                    row["own_head"] = {"error": f"{type(e).__name__}: {e}: the dials instead"}
        except (SystemExit, ValueError, nifmod.NifError) as e:
            row["error"] = str(e)
        remember(row)
        report["npcs"].append(row)
        print({k: v for k, v in row.items() if k not in ("dials", "dial_names")})
    fit_cache["_sexes"] = dict(fit_cache.get("_sexes") or {}, **report["sexes"])
    with open(os.path.join(out, FIT_CACHE), "w", encoding="utf-8") as fh:
        json.dump(fit_cache, fh)
    if reused:
        print(f"{len(reused)} NPC fits unchanged, reused (--refit to fit again): {', '.join(reused)}")

    if a.test_plugin:
        sf_esm = os.path.join(sf_data, "Starfield.esm")
        info = sfplugin.header_info(sf_esm)
        human = next(fid for _t, _h, s, fid in sfplugin.records(sf_esm, [b"RACE"]) if sfplugin.edid(s) == "HumanRace")
        npc_recs = sfplugin.records(sf_esm, [b"NPC_"])
        recs, test_subs = [], {}
        masters = ["Starfield.esm"]
        real = None
        if a.hairs_plugin:
            real = npc_setup(a, sky, esm, sf_esm, npc_recs, report)
            masters = real["masters"]
        # 2026-11-06: with no outfit (DOFT / SOFT dropped, or a template without one: ChargenPresetFemale01) the
        # game dressed the test NPCs in a spacesuit; Ralof, who kept his template's outfit, wore plain underwear.
        # An empty outfit of our own, as default and space outfit, keeps them in underwear until clothing exists.
        baked = None
        if a.baked_face_textures:
            from fo4sf import ba2
            names = {}
            for fn in sorted(os.listdir(sf_data)):
                if fn.lower().startswith("starfield - textures") and fn.lower().endswith(".ba2"):
                    names[fn] = ba2.Ba2(os.path.join(sf_data, fn)).names
            baked = baked_face_index(names)
            report["baked_faces"] = len(baked)
        worn, items, sky_otft = {}, {}, {}
        if a.items_plugin:
            masters = list(masters) + [os.path.basename(a.items_plugin)]
            items = item_outfits(a.items_plugin, len(masters) - 1)
            sky_otft = {fid: sfplugin.edid(s_) for _t, _h, s_, fid in skyrimload.records(esm, [b"OTFT"])}
        race_index = None
        sf_hdpt_all = None
        if conv_races:
            masters = list(masters) + [os.path.basename(a.races_plugin)]
            race_index = len(masters) - 1
            sf_hdpt_all = {r[3]: r for r in sfplugin.records(sf_esm, [b"HDPT"])}
        if a.outfits_plugin:
            masters = list(masters) + [os.path.basename(a.outfits_plugin)]
            worn = outfits_by_npc(a.outfits_plugin, len(masters) - 1)
            report["outfits"] = {k: f"{v:08X}" for k, v in worn.items()}
        no_outfit = None
        otft = sfplugin.records(sf_esm, [b"OTFT"])
        if otft:
            no_outfit = sfplugin.new_form_id(0, masters=len(masters))
            recs.append((b"OTFT", otft[0][1], [(b"EDID", sfplugin.zs("S2S_NoOutfit")), (b"INAM", b"")], no_outfit))
        tone_arcs = None
        child_race = next((fid for _t, _h, s_, fid in sfplugin.records(sf_esm, [b"RACE"])
                           if sfplugin.edid(s_) == "ChildRace"), None)
        conv_child = converted_child_races(a.races_plugin) if a.races_plugin else {}
        sf_hdpt_recs = None
        tone_slots = None
        light_ston = None
        late_recs = []      # overrides added after every new record, so they do not shift the new FormIDs
        for row in report["npcs"]:
            if "dials" not in row:
                continue
            if row.get("child"):
                if sf_hdpt_recs is None:
                    sf_hdpt_recs = sfplugin.records(sf_esm, [b"HDPT"])
                if "child_templates" not in report:      # what the game offers (2026-11-19: face skin by ethnicity)
                    import child_faces
                    report["child_templates"] = {
                        ("female" if f else "male"): [dict({"edid": e, "plain": p_, "ethnicity": et, "face_skin": tx},
                                                           **child_template_looks(r_, sf_hdpt_recs))
                                                      for e, p_, et, tx, r_ in
                                                      child_faces.child_templates(npc_recs, child_race, f)]
                        for f in (False, True)}
                    report["child_npcs_all"] = child_npc_survey(npc_recs, child_race, sf_hdpt_recs)
                if tone_slots is None and real is not None:
                    tone_slots = child_tone_order(sf_esm, sf_data, [r["female"] for r in report["npcs"]
                                                                    if r.get("child")])
                    report["child_skin_tones"] = tone_slots.pop("_report", None)
                    import child_faces
                    lightest = [r for r in report["npcs"] if r.get("child") and real is not None and
                                child_faces.child_tone(target_skin(by_edid[r["edid"].lower()], npcs, real)[0]) == 0]
                    light = add_child_light_tone(sf_esm, sf_data, out, late_recs, lightest, sky,
                                                 getattr(a, "texconv", "") or "")
                    report["child_light_tone"] = light
                    light_ston = light.get("index") if isinstance(light, dict) else None
                own = (report.get("child_light_tone") or {}).get("children", {}).get(row["edid"])
                write_child_npc(row, by_edid[row["edid"].lower()], npcs, real, races, npc_recs, sf_hdpt_recs,
                                child_race, conv_child, race_index, recs, masters, test_subs, tone_slots,
                                light_ston, own)
                if baked and isinstance(row.get("test_npc"), dict):
                    try:
                        if tone_arcs is None:
                            import skin_tone_probe
                            tone_arcs = skin_tone_probe.TextureArchives(sf_data)
                        row["test_npc"]["baked_face"] = child_baked_face(
                            row, by_edid[row["edid"].lower()], npcs, real, npc_recs, human, baked, sf_data, out,
                            tone_arcs.read)
                    except (KeyError, ValueError, OSError) as e:
                        row["test_npc"]["baked_face"] = f"none: {type(e).__name__}: {e}"
                continue
            want = a.template_npc[int(row["female"])] if len(a.template_npc) > int(row["female"]) else None
            elder = None
            if want is None and not a.no_elder_template and \
                    races.get(by_edid[row["edid"].lower()].get("race"), "").lower() in ELDER_RACES:
                elder = (pick_elder_template(npc_recs, human, row["female"], baked=baked) if baked else None) or \
                    pick_elder_template(npc_recs, human, row["female"])
                row["elder_template"] = sfplugin.edid(elder[2]) if elder else "none found: the generic one"
            if want is None and not a.template_by_tone:
                want = GENERIC_TEMPLATE[int(row["female"])]
            if elder is not None:
                want = sfplugin.edid(elder[2])
            skin = target_skin(by_edid[row["edid"].lower()], npcs, real) if real is not None else None
            tpl = (pick_template(npc_recs, human, row["female"], want, skin=skin, baked=baked) if baked else None) \
                or pick_template(npc_recs, human, row["female"], want, skin=skin)
            if tpl is None and want is not None and not a.template_npc:      # the generic one is not in this game
                tpl = (pick_template(npc_recs, human, row["female"], None, skin=skin, baked=baked) if baked
                       else None) or pick_template(npc_recs, human, row["female"], None, skin=skin)
            if tpl is None:
                row["test_npc"] = "no vanilla template NPC of this sex"
                continue
            fid = sfplugin.new_form_id(len(recs), masters=len(masters))
            full = f"{row['edid']} (S2S)"
            if real is not None:
                full = npc_records.npc_name(by_edid[row["edid"].lower()], real["strings"])
            keep = (b"BMPN", b"BMPV", b"FMRI", b"FMRG") if a.keep_blend_morphs else ()
            subs = sfplugin.edit(with_face(tpl[2], {int(k): v for k, v in row["dials"].items()}, keep),
                                 {b"EDID": sfplugin.zs(f"S2SFace_{row['edid']}"),
                                  b"FULL": sfplugin.zs(full)}, drop=STRIP + STRIP_GEAR)
            subs = without_templates(subs)
            if row.get("blends"):
                subs = with_blends(subs, row["blends"])
            if no_outfit is not None:
                subs = sfplugin.edit(subs, {b"DOFT": struct.pack("<I", no_outfit), b"SOFT": struct.pack("<I", no_outfit)})
            item_fid = None
            if items:
                item_fid, why = npc_item_outfit(by_edid[row["edid"].lower()], sky_otft, items)
                row["item_outfit"] = why if item_fid is None else f"S2S_{why}"
            if item_fid is not None:
                o = struct.pack("<I", item_fid)
                subs = sfplugin.edit(subs, {b"DOFT": o, b"SOFT": o})
                row["outfit"] = f"{item_fid:08X}"
            elif row["edid"].lower() in worn:
                o = struct.pack("<I", worn[row["edid"].lower()])
                subs = sfplugin.edit(subs, {b"DOFT": o, b"SOFT": o})
                row["outfit"] = f"{worn[row['edid'].lower()]:08X}"
            if real is not None:
                subs = npc_dress(subs, by_edid[row["edid"].lower()], npcs, real, row)
                row["name"] = full
                vt = next((struct.unpack_from("<I", bytes(d), 0)[0] for sg, d in subs if sg == b"VTCK"), None)
                row["voice_type"] = real["voices"].get(vt, f"{vt:08X}" if vt else None)
            sky_race = races.get(by_edid[row["edid"].lower()]["race"], "")
            face_colour = rskin = None
            if race_index is not None and sky_race in conv_races:
                subs, swapped = on_race(subs, conv_races[sky_race], row["female"], race_index, sf_hdpt_all,
                                        hdpt_type)
                row.setdefault("race", {}).update(npc_race=f"S2S_{conv_races[sky_race]['name']}Race",
                                                  parts_swapped=swapped)
                rgb = (((row.get("dressed") or {}).get("face_colors") or {}).get("skin") or {}).get("skyrim_rgb")
                subs, rskin, face_colour = race_skin(subs, conv_races[sky_race], row["female"], rgb)
            if isinstance(row.get("own_head"), dict) and row["own_head"].get("model"):
                rh = None
                if race_index is not None and sky_race in conv_races and row["female"] in conv_races[sky_race]["head"]:
                    rh = (race_index << 24) | conv_races[sky_race]["head"][row["female"]]
                subs, hd = with_own_head(subs, row, recs, masters, sf_hdpt_all or {r[3]: r for r in
                                         sfplugin.records(sf_esm, [b"HDPT"])}, rh)
                row["own_head"]["head_part"] = hd
                if rskin:
                    row["race"]["skin"] = rskin
            body_names = (list(a.body_npc) + list(BODY_NPC)[len(a.body_npc):])[:2]
            body_name = body_names[int(row["female"])]
            body_note = "template's own"
            if body_name.lower() != "none":
                body = next((r for r in npc_recs if sfplugin.edid(r[2]).lower() == body_name.lower()), None)
                if body is None:
                    body_note = f"{body_name} not in Starfield.esm: template's own"
                else:
                    subs, got = with_body(subs, body[2])
                    body_note = f"{body_name} ({', '.join(got) or 'no MWGT / MRSV on the template: unchanged'})"
            test_subs[row["edid"]] = len(recs)
            recs.append((b"NPC_", tpl[1], subs, fid))
            row["test_npc"] = {"form_id": f"{fid:08X}", "template": sfplugin.edid(tpl[2]),
                               "template_form_id": f"{tpl[3]:08X}",
                               "template_console": f"player.placeatme {tpl[3]:X}  (the vanilla NPC it was copied "
                                                   f"from, to compare in game)",
                               "console": f"player.placeatme xx{fid & 0xFFFFFF:06X}  (xx = S2SFaceTest.esm's load "
                                          f"order index)", "body": body_note}
            if baked and tpl[3] in baked and rskin is None and skin is not None:
                try:
                    if tone_arcs is None:
                        import skin_tone_probe
                        tone_arcs = skin_tone_probe.TextureArchives(sf_data)
                    face_colour, fc = human_face_colour(tpl[2], skin[0], row["female"], tone_arcs.read)
                    if fc:
                        row["test_npc"]["face_recoloured"] = fc
                except (KeyError, ValueError, OSError) as e:      # no such texture / format: the template's face
                    row["test_npc"]["face_recoloured"] = f"not recoloured: {e}"
            if baked and tpl[3] in baked:
                row["test_npc"]["baked_face_textures"] = [os.path.basename(p) for p in
                                                          write_baked_face(baked, tpl[3], fid, sf_data, out,
                                                                           colour=face_colour)]
            if a.control_npcs:
                # the same NPC with the template's own face data (dials, presets) kept: only hair, colours, outfit
                # and name are ours (2026-11-06: our Saadia's face stays light where her template's is dark)
                cfid = sfplugin.new_form_id(len(recs), masters=len(masters))
                csubs = sfplugin.edit(tpl[2], {b"EDID": sfplugin.zs(f"S2SFaceControl_{row['edid']}"),
                                                b"FULL": sfplugin.zs(f"{full} (template face)")},
                                      drop=STRIP + STRIP_GEAR)
                csubs = without_templates(csubs)
                if no_outfit is not None:
                    csubs = sfplugin.edit(csubs, {b"DOFT": struct.pack("<I", no_outfit),
                                                  b"SOFT": struct.pack("<I", no_outfit)})
                if item_fid is not None or row["edid"].lower() in worn:
                    o = struct.pack("<I", item_fid if item_fid is not None else worn[row["edid"].lower()])
                    csubs = sfplugin.edit(csubs, {b"DOFT": o, b"SOFT": o})
                if real is not None:
                    csubs = npc_dress(csubs, by_edid[row["edid"].lower()], npcs, real, dict(row))
                recs.append((b"NPC_", tpl[1], csubs, cfid))
                row["control_npc"] = {"form_id": f"{cfid:08X}",
                                      "console": f"player.placeatme xx{cfid & 0xFFFFFF:06X}  (template face, our hair "
                                                 f"and colours)"}
        if recs and a.hair:
            report["hair_packing"] = add_hair_files(a, out, sky, esm, sf_data, report["npcs"], npcs, chosen, recs,
                                                    test_subs)
        elif recs and any(r.get("child") for r in report["npcs"]):
            if a.texconv:               # 2026-11-19: the children's own hair, from their FaceGen NIFs
                report["child_hair"] = add_child_hair_files(a, out, sky, sf_data, report["npcs"], by_edid, recs,
                                                            test_subs, masters, real, child_ctx)
            else:
                report["child_hair"] = "not converted: give --texconv (children keep the template's hair)"
        if recs and a.child_controls:
            dn = derma_names(npc_recs)
            skins = {f: child_skin_choices(dn, f) for f in (False, True)}
            report["child_skin_choices"] = {("female" if f else "male"): v for f, v in skins.items()}
            light = report.get("child_light_tone")
            tv = light.get("indices") if isinstance(light, dict) and light.get("indices") else None
            add_child_controls(report["npcs"], recs, test_subs, masters, skins, tv)
        children = {}
        if recs and a.voice_lines:
            import npc_voice
            vt = {sfplugin.edid(r[2]): r for r in sfplugin.records(sf_esm, [b"VTYP"])}
            qt = next(r for r in sfplugin.records(sf_esm, [b"QUST"]) if sfplugin.edid(r[2]) == "DialogueGeneric")
            top, children = npc_voice.add_voices(recs, test_subs, report["npcs"], a.voice_lines, len(masters), PLUGIN,
                                                 out, vt["GenericMaleEvenToned"], qt, report)
            recs += top
        recs.extend(late_recs)
        report["changed_since_last_run"] = npc_changes(report["npcs"], recs, test_subs, out, previous_rows(out))
        if recs:
            with open(os.path.join(out, PLUGIN), "wb") as fh:
                fh.write(sfplugin.build(recs, info, author="Skyrim2Starfield faces", masters=masters,
                                        children=children))
            print(f"{PLUGIN}: {len(recs)} test NPCs")
    with open(os.path.join(out, "faces.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(f"report: {os.path.join(out, 'faces.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
