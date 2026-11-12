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

from fo4sf import bsa, facefit, headcorr, nif as nifmod, sfmesh, sfplugin, skyrimnpc, skyrimskin  # noqa: E402
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


def converted_races(races_plugin):
    """{Skyrim race EditorID: {"name", "form_id" (local), "parts": {female: {vanilla HDPT EditorID: local FormID}},
    "head": {female: local FormID}, "mouth": {female: local FormID}}} from the race plugin and its race_heads.json."""
    folder = os.path.dirname(os.path.abspath(races_plugin))
    with open(os.path.join(folder, "race_heads.json"), encoding="utf-8") as fh:
        rep = json.load(fh)
    hd = {sfplugin.edid(sb): fid & 0xFFFFFF for _t, _h, sb, fid in sfplugin.records(races_plugin, [b"HDPT"])}
    out = {}
    for race, r in (rep.get("new_races") or {}).items():
        if "form_id" not in r:
            continue
        if not r.get("edid"):
            continue                                  # a race_heads.json from before 2026-11-10: rebuild the races
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
    for _t, _h, subs, _fid in sfplugin.records(esm, [b"RACE"]):
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
                    (0 if eth == skin[1] else 6) + 0.5 * template_wear(subs)
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
    race_recs = sfplugin.records(esm, [b"RACE"])
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
    return npc_records.skin_tone(rgb), npc_records.skyrim_ethnicity(real.get("race_edids", {}).get(src.get("race"), ""))


def with_race_hair(src, real):
    """The Skyrim NPC with its race's default hair added when it has none of its own (2026-11-06: Nazeem has no head
    parts, wears his race's short hair in Skyrim, and kept the Starfield template's hair)."""
    hdpt = real["hdpt"]
    if any(hdpt.get(f, {}).get("type") == 3 for f in src.get("head_parts", [])):
        return src
    _t, defaults = real.get("races", {}).get(src.get("race"), ({}, {False: [], True: []}))
    hair = [f for f in defaults.get(src.get("female", False), []) if hdpt.get(f, {}).get("type") == 3]
    return dict(src, head_parts=list(src.get("head_parts", [])) + hair[:1]) if hair else src


def face_colors(subs, src, real, hair_color_name):
    """Eye colour (ECOL, from the Skyrim eyes head part's name), skin tone (STON 0-8, from the skin tone tint) and brow
    colour (BCOL = the hair colour; Skyrim brows take the hair colour) on the test NPC (owner 2026-11-06). NPCs without
    their own eyes use their race's default eyes."""
    tints, defaults = real.get("races", {}).get(src.get("race"), ({}, {False: [], True: []}))
    hdpt = real["hdpt"]
    own = [p for p in (hdpt.get(f) for f in src.get("head_parts", [])) if p and p.get("type") == 2]
    eyes, where = (own[0], "own") if own else (next(
        (hdpt[f] for f in defaults.get(src.get("female", False), []) if f in hdpt and hdpt[f].get("type") == 2),
        None), "race default")
    ecol, ehow = npc_records.eye_color(eyes.get("edid") if eyes else None)
    rgb, shown = npc_records.skyrim_skin_rgb(src, tints)
    ston = npc_records.skin_tone(rgb)
    values = {}
    if ston is not None:
        values[b"STON"] = bytes([ston])
    if ecol:
        values[b"ECOL"] = sfplugin.zs(ecol)
    if hair_color_name:
        values[b"BCOL"] = sfplugin.zs(hair_color_name)
    ethnicity = npc_records.skyrim_ethnicity(real.get("race_edids", {}).get(src.get("race"), ""))
    derma, dhow = npc_records.choose_dermaesthetic(real.get("derma", []), ethnicity, src.get("female", False), ston)
    placed = False
    if derma:
        subs, placed = npc_records.with_layer_texture(subs, "Dermaesthetic", derma,
                                                      real.get("derma_paths", {}).get(derma))
    info = {"eyes": {"skyrim": eyes.get("edid") if eyes else None, "from": where, "starfield": ecol, "how": ehow},
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
    sky = bsa.SkyrimArchives(a.skyrim_data)
    esm = os.path.join(a.skyrim_data, "Skyrim.esm")

    races = {fid: sfplugin.edid(s) for _t, _h, s, fid in sfplugin.records(esm, [b"RACE"])}
    npcs = {fid: skyrimnpc.parse_npc(s, fid) for _t, _h, s, fid in sfplugin.records(esm, [b"NPC_"])}
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
    for female in (False, True):
        if not any(n["female"] == female for n in chosen):
            continue
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
        setup[female] = (sliders, head, base, al, model_space, corr)
        report["sexes"]["female" if female else "male"] = dict(
            hrep, sliders=len(sliders), skyrim_base_vertices=len(base), alignment_scale=al[0],
            alignment_rms_m=al[3], alignment_rotated=bool(not np.allclose(al[1], np.eye(3))),
            alignment="model space via the head node (2026-11-09)" if model_space else "legacy ICP on the mesh",
            transfer="surface (headcorr)" if corr is not None else "nearest vertices",
            correspondence=corr.report if corr is not None else None)
    dial_ids = race_dials(os.path.join(sf_data, "Starfield.esm"))
    for female, (sliders, *_rest) in setup.items():
        ids = {s.id for s in sliders}
        rd = set(dial_ids[female])
        report["sexes"]["female" if female else "male"]["race_dials"] = {
            "count": len(rd), "also_slider_ids": len(rd & ids), "slider_ids_not_dials": len(ids - rd)}

    for n in chosen:
        sliders, head, base, al, model_space, corr = setup[n["female"]]
        row = {"edid": n["edid"], "form_id": f"{n['form_id']:08X}", "female": n["female"]}
        if "child" in races.get(n["race"], "").lower():
            # 2026-11-10: Skyrim's children (ChildRace: their own head, body and skeleton) would come out as adults
            # on the adult template; they wait for the child path (races-roadmap.md, children)
            row["error"] = f"child ({races.get(n['race'])}): not converted yet (Starfield's child race pending)"
            report["npcs"].append(row)
            print({k: v for k, v in row.items()})
            continue
        try:
            fg = skyrim_head(hkx_to_af.read_any(skyrimnpc.facegen_paths("Skyrim.esm", n["form_id"])["mesh"], sky),
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
                                      pos_unit=a.pos_unit, limit=a.dial_limit,
                                      ridge=a.ridge)
            names = {s.id: f"{s.region}: {s.name}" for s in sliders}
            if a.preview and getattr(head, "triangles", None) is not None and len(head.triangles):
                fitted = facefit.deform(head, sliders, values, pos_unit=a.pos_unit)
                os.makedirs(os.path.join(out, "faces_preview"), exist_ok=True)
                png = os.path.join(out, "faces_preview", f"{n['edid']}.png")
                hair_probe.write_png(png, facepreview.sheet([head.vertices, head.vertices + disp, fitted],
                                                            head.triangles))
                row["preview"] = png
            row.update(rep, dials={str(k): round(v, 4) for k, v in sorted(values.items())},
                       dial_names={str(k): names.get(k, "") for k in sorted(values)},
                       skyrim_face_change_m=float(np.sqrt(np.mean(np.sum(disp ** 2, 1)))))
        except (SystemExit, ValueError, nifmod.NifError) as e:
            row["error"] = str(e)
        report["npcs"].append(row)
        print({k: v for k, v in row.items() if k not in ("dials", "dial_names")})

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
            sky_otft = {fid: sfplugin.edid(s_) for _t, _h, s_, fid in sfplugin.records(esm, [b"OTFT"])}
        race_index = None
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
        for row in report["npcs"]:
            if "dials" not in row:
                continue
            want = a.template_npc[int(row["female"])] if len(a.template_npc) > int(row["female"]) else None
            skin = target_skin(by_edid[row["edid"].lower()], npcs, real) if real is not None else None
            tpl = (pick_template(npc_recs, human, row["female"], want, skin=skin, baked=baked) if baked else None) \
                or pick_template(npc_recs, human, row["female"], want, skin=skin)
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
            face_colour = None
            if race_index is not None and sky_race in conv_races:
                subs, swapped = on_race(subs, conv_races[sky_race], row["female"], race_index, sf_hdpt_all,
                                        lambda rec: struct.unpack("<I", bytes(dict(rec[2]).get(b"PNAM", bytes(4)))[0])
                                        if rec is not None else None)
                row.setdefault("race", {}).update(npc_race=f"S2S_{conv_races[sky_race]['name']}Race",
                                                  parts_swapped=swapped)
                rgb = (((row.get("dressed") or {}).get("face_colors") or {}).get("skin") or {}).get("skyrim_rgb")
                subs, skin, face_colour = race_skin(subs, conv_races[sky_race], row["female"], rgb)
                if skin:
                    row["race"]["skin"] = skin
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
        children = {}
        if recs and a.voice_lines:
            import npc_voice
            vt = {sfplugin.edid(r[2]): r for r in sfplugin.records(sf_esm, [b"VTYP"])}
            qt = next(r for r in sfplugin.records(sf_esm, [b"QUST"]) if sfplugin.edid(r[2]) == "DialogueGeneric")
            top, children = npc_voice.add_voices(recs, test_subs, report["npcs"], a.voice_lines, len(masters), PLUGIN,
                                                 out, vt["GenericMaleEvenToned"], qt, report)
            recs += top
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
