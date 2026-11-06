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
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

from fo4sf import bsa, facefit, nif as nifmod, sfmesh, sfplugin, skyrimnpc, skyrimskin  # noqa: E402
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


def skyrim_head(data: bytes):
    shapes = skyrimskin.skinned_shapes(nifmod.parse(data))
    s = skyrimnpc.head_shape(shapes)
    return None if s is None else np.array(s.positions, float)


def starfield_head(sf_data, female, head_nif=None):
    nif_bytes, _rel = hkx_to_af.vanilla_file(head_nif or SF_HEADS[female], sf_data)
    paths, skin = facefit.starfield_head_parts(nif_bytes)
    if not paths:
        raise SystemExit("head NIF has no geometry reference")
    mesh_rel = "geometries/" + paths[0].replace("\\", "/") + ".mesh"
    mesh_bytes, _ = hkx_to_af.vanilla_file(mesh_rel, sf_data)
    mesh = sfmesh.parse(mesh_bytes)
    pos, ws = facefit.mesh_arrays(mesh)
    bones = [b.decode("latin-1") if isinstance(b, bytes) else b for b in skin.get("bones", [])]
    head, rep = facefit.face_head(pos, ws, bones, skin.get("binds", []))
    head.triangles = np.array([tuple(t) for t in mesh.triangles], int)
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


def with_face(subs, values):
    """The NPC's subrecords with face dials replaced by `values` and phenotype / morph-group data removed."""
    first = next((i for i, (s, _d) in enumerate(subs) if s in FACE_SIGS), None)
    kept = [(s, d) for s, d in subs if s not in FACE_SIGS]
    if first is None:
        first = next((i for i, (s, _d) in enumerate(kept) if s in (b"ATTX", b"STON", b"HCOL")), len(kept))
    else:
        first = sum(1 for s, _d in subs[:first] if s not in FACE_SIGS)
    return kept[:first] + face_subrecords(values) + kept[first:]


# Data a test copy must not carry: scripts (VMAD) and companion affinity hooks (QSTA quest, BNAM dialogue)
STRIP = (b"VMAD", b"QSTA", b"BNAM", b"SHRT", b"SOFT")   # SOFT: space outfit (2026-11-03: Ysolda in a helmeted suit)


def pick_template(npc_recs, race_fid, female, edid=None):
    """A vanilla human NPC of the sex to copy: `edid` when given; else one with face dials and no template, preferring
    plain ones (no scripts, no affinity data: a generic NPC rather than a quest character) with a voice type (VTCK:
    the game's generic greetings, owner 2026-11-05)."""
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
        if rnam == race_fid and is_f == female and b"FMSI" in sigs and b"TPLT" not in sigs:
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
    report["npc_conversion"] = {"hairs_plugin": hp, "masters": masters, "hairstyles_in_it": len(index),
                                "starfield_hair_colors": sorted(names), "palette": bool(palette),
                                "skyrim_strings": len(strings)}
    return dict(masters=masters, sf_hdpt=sf_hdpt, hdpt=hdpt, clfm=clfm, names=names, palette=palette,
                voices=voices, strings=strings, index=index, part_type=npc_hair.part_type,
                npc_parts=npc_hair.npc_parts, with_hair_color=npc_hair.with_hair_color)


def npc_dress(subs, n, npcs, real, row) -> list:
    """The NPC's converted Skyrim hair / beard (from --hairs-plugin, by Skyrim EditorID; a template beard dropped when
    Skyrim gives none) and its hair colour name (npc_records.match_hair_color)."""
    faces = skyrimnpc.faces_by_template(npcs)
    src = npcs.get(faces.get(n["form_id"], n["form_id"]), n)          # whose face (and hair) it wears
    parts = real["npc_parts"](src, real["hdpt"])
    new, info = {}, {}
    for kind, (part, _models) in parts.items():
        fid = real["index"].get(part["edid"].lower())
        info[{3: "hair", 4: "facial_hair"}.get(kind, str(kind))] = (
            {"skyrim": part["edid"], "form_id": f"{fid:08X}"} if fid else
            {"skyrim": part["edid"], "missing": "not in the hairs plugin (build it with --facial-hair for beards)"})
        if fid:
            new[kind] = fid
    drop = [k for k in (npc_records.HAIR, npc_records.FACIAL_HAIR) if k not in parts]
    subs = npc_records.with_parts(subs, real["sf_hdpt"], new, drop=drop, part_type=real["part_type"])
    color = real["clfm"].get(src.get("hair_color"))
    name, how = npc_records.match_hair_color(color, real["names"], real["palette"])
    if name:
        subs = real["with_hair_color"](subs, name)
    info["hair_color"] = {"skyrim": (color or {}).get("edid"), "skyrim_rgb": list((color or {}).get("rgba") or [])[:3],
                          "starfield": name, "how": how}
    row["dressed"] = info
    return subs


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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="Starfield install folder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--npc", action="append", default=[], help="Skyrim NPC EditorID (repeatable)")
    ap.add_argument("--count", type=int, default=12, help="sample size without --npc")
    ap.add_argument("--regions", help="facial bone regions file to use instead of the game's (per sex: give twice, "
                                      "male first)", action="append", default=[])
    ap.add_argument("--head-nif", action="append", default=[], help="head NIF instead of the game's (male, female)")
    ap.add_argument("--pos-unit", type=float, default=0.01, help="metres per regions-file position unit")
    ap.add_argument("--test-plugin", action="store_true")
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
    if not a.npc:
        for n in sorted(npcs.values(), key=lambda n: n["edid"]):
            if len(chosen) >= a.count:
                break
            if n not in chosen and races.get(n["race"]) in HUMAN_RACES and n["full_name_id"] is not None \
                    and faces[n["form_id"]] == n["form_id"]:
                chosen.append(n)
        chosen = chosen[:a.count]
    print(f"{len(npcs)} Skyrim NPCs; fitting {len(chosen)}: {', '.join(n['edid'] for n in chosen)}")

    report = {"settings": {"pos_unit": a.pos_unit, "smooth": a.smooth, "dial_limit": a.dial_limit}, "sexes": {},
              "npcs": []}
    setup = {}
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
        head, hrep = starfield_head(sf_data, female, a.head_nif[int(female)] if len(a.head_nif) > int(female) else None)
        base = skyrim_head(hkx_to_af.read_any(SKY_HEADS[female], sky))
        al = facefit.align_heads(base, head.vertices)
        rot_free = facefit.align_heads(base, head.vertices, rotate=False)
        if rot_free[3] <= al[3] * 1.05:                 # same facing within 5 %: no rotation (both games face +Y, Z up)
            al = rot_free
        setup[female] = (sliders, head, base, al)
        report["sexes"]["female" if female else "male"] = dict(
            hrep, sliders=len(sliders), skyrim_base_vertices=len(base), alignment_scale=al[0],
            alignment_rms_m=al[3], alignment_rotated=bool(not np.allclose(al[1], np.eye(3))))
    dial_ids = race_dials(os.path.join(sf_data, "Starfield.esm"))
    for female, (sliders, *_rest) in setup.items():
        ids = {s.id for s in sliders}
        rd = set(dial_ids[female])
        report["sexes"]["female" if female else "male"]["race_dials"] = {
            "count": len(rd), "also_slider_ids": len(rd & ids), "slider_ids_not_dials": len(ids - rd)}

    for n in chosen:
        sliders, head, base, al = setup[n["female"]]
        row = {"edid": n["edid"], "form_id": f"{n['form_id']:08X}", "female": n["female"]}
        try:
            fg = skyrim_head(hkx_to_af.read_any(skyrimnpc.facegen_paths("Skyrim.esm", n["form_id"])["mesh"], sky))
            if fg is None or len(fg) != len(base):
                raise ValueError(f"FaceGen head has {0 if fg is None else len(fg)} vertices, base head {len(base)}")
            disp = facefit.transfer(base, fg, al, head.vertices)
            if a.smooth and getattr(head, "triangles", None) is not None and len(head.triangles):
                disp = facefit.smooth_field(disp, head.triangles, a.smooth)
            values, rep = facefit.fit(head, sliders, head.vertices + disp, facefit.face_weights(head),
                                      pos_unit=a.pos_unit, limit=a.dial_limit)
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
        for row in report["npcs"]:
            if "dials" not in row:
                continue
            want = a.template_npc[int(row["female"])] if len(a.template_npc) > int(row["female"]) else None
            tpl = pick_template(npc_recs, human, row["female"], want)
            if tpl is None:
                row["test_npc"] = "no vanilla template NPC of this sex"
                continue
            fid = sfplugin.new_form_id(len(recs), masters=len(masters))
            full = f"{row['edid']} (S2S)"
            if real is not None:
                full = npc_records.npc_name(by_edid[row["edid"].lower()], real["strings"])
            subs = sfplugin.edit(with_face(tpl[2], {int(k): v for k, v in row["dials"].items()}),
                                 {b"EDID": sfplugin.zs(f"S2SFace_{row['edid']}"),
                                  b"FULL": sfplugin.zs(full)}, drop=STRIP)
            if real is not None:
                subs = npc_dress(subs, by_edid[row["edid"].lower()], npcs, real, row)
                row["name"] = full
                vt = next((struct.unpack_from("<I", bytes(d), 0)[0] for sg, d in subs if sg == b"VTCK"), None)
                row["voice_type"] = real["voices"].get(vt, f"{vt:08X}" if vt else None)
            test_subs[row["edid"]] = len(recs)
            recs.append((b"NPC_", tpl[1], subs, fid))
            row["test_npc"] = {"form_id": f"{fid:08X}", "template": sfplugin.edid(tpl[2]),
                               "console": f"player.placeatme xx{fid & 0xFFFFFF:06X}  (xx = S2SFaceTest.esm's load "
                                          f"order index)"}
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
