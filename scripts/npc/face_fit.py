"""Fit Starfield face sliders to Skyrim NPCs' faces (src/fo4sf/facefit.py), optionally as a test plugin to look at.

Reads (Skyrim): Skyrim.esm NPC_ / RACE records, each NPC's baked FaceGen head and the base heads
(meshes\\actors\\character\\character assets\\{male,female}head.nif) from the Skyrim archives.
Reads (Starfield): the facial bone regions (humanracefacialboneregions*.txt), the skinned head NIF and its geometry
(.mesh) and Starfield.esm's HumanRace face dials, from the game archives (or --regions / --head-nif files, e.g. a
face-bone mod's).

    python -I scripts\\npc\\face_fit.py --skyrim-data "<Skyrim SE>\\Data" --starfield "<Starfield>" --out <folder>
        [--npc EDID ...] [--count 12] [--test-plugin]

Writes <out>\\faces.json (per NPC: dial values by slider id and name, fit RMS before / after, alignment) and, with
--test-plugin, S2SFaceTest.esm: one Starfield NPC per fitted face (a vanilla human NPC of the same sex copied, its face
dials replaced, its phenotype morphs cleared) named "<Skyrim EditorID> (S2S)", to place with the console
(player.placeatme <id>; the ids are in faces.json).
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

import numpy as np  # noqa: E402

from fo4sf import bsa, facefit, nif as nifmod, sfmesh, sfplugin, skyrimnpc, skyrimskin  # noqa: E402
import hkx_to_af  # noqa: E402  (archive helpers)

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
    pos, ws = facefit.mesh_arrays(sfmesh.parse(mesh_bytes))
    bones = [b.decode("latin-1") if isinstance(b, bytes) else b for b in skin.get("bones", [])]
    return facefit.face_head(pos, ws, bones, skin.get("binds", []))


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
STRIP = (b"VMAD", b"QSTA", b"BNAM", b"SHRT")


def pick_template(npc_recs, race_fid, female, edid=None):
    """A vanilla human NPC of the sex to copy: `edid` when given; else one with face dials and no template, preferring
    plain ones (no scripts, no affinity data: a generic NPC rather than a quest character)."""
    best = None
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
            if plain:
                return t, h, subs, fid
            best = best or (t, h, subs, fid)
    return best


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
    a = ap.parse_args(argv)
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

    report = {"settings": {"pos_unit": a.pos_unit}, "sexes": {}, "npcs": []}
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
            values, rep = facefit.fit(head, sliders, head.vertices + disp, facefit.face_weights(head),
                                      pos_unit=a.pos_unit)
            names = {s.id: f"{s.region}: {s.name}" for s in sliders}
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
        recs = []
        for row in report["npcs"]:
            if "dials" not in row:
                continue
            want = a.template_npc[int(row["female"])] if len(a.template_npc) > int(row["female"]) else None
            tpl = pick_template(npc_recs, human, row["female"], want)
            if tpl is None:
                row["test_npc"] = "no vanilla template NPC of this sex"
                continue
            fid = sfplugin.new_form_id(len(recs))
            subs = sfplugin.edit(with_face(tpl[2], {int(k): v for k, v in row["dials"].items()}),
                                 {b"EDID": sfplugin.zs(f"S2SFace_{row['edid']}"),
                                  b"FULL": sfplugin.zs(f"{row['edid']} (S2S)")}, drop=STRIP)
            recs.append((b"NPC_", tpl[1], subs, fid))
            row["test_npc"] = {"form_id": f"{fid:08X}", "template": sfplugin.edid(tpl[2]),
                               "console": f"player.placeatme xx{fid & 0xFFFFFF:06X}  (xx = S2SFaceTest.esm's load "
                                          f"order index)"}
        if recs:
            with open(os.path.join(out, PLUGIN), "wb") as fh:
                fh.write(sfplugin.build(recs, info, author="Skyrim2Starfield faces"))
            print(f"{PLUGIN}: {len(recs)} test NPCs")
    with open(os.path.join(out, "faces.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(f"report: {os.path.join(out, 'faces.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
