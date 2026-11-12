"""What Skyrim's and Starfield's children are made of, for converting them (races roadmap I2). Read-only.

    python -I scripts\\npc\\child_probe.py --skyrim-data "$sky" --starfield $sf --npc Dorthe --npc Frodnar --out C:\\Modding\\work\\races\\child_probe

2026-11-12, owner's first child records: Skyrim has a child race per human race (NordRaceChild ...: the ADULT
skeletons, height 0.8, head parts 0001C22E / 0001C558 ...); Starfield one ChildRace (002AABCD: its own skeleton,
height 0.86, Human_Child_Head_Boy / _Girl); a vanilla child outfit is adult-sized (1.52 m, like an adult's: the
child skeleton shrinks it). Open, and what this reads:
1. Skyrim: each child race's head parts per sex (EditorID, type, model) and its Face head's vertex count and size,
   beside the adult race's: is a Skyrim child head its own mesh (topology) or the adult head?
2. Skyrim: each --npc (a child): race, head parts, and its FaceGen head (FaceGeom\\Skyrim.esm\\<FormID>.nif):
   vertex count and size, so its face can be compared with its race's child head.
3. Starfield: ChildRace's NPCs: how many per sex carry face dials (FMSI), morph blends (BMPN), pre-built face
   textures (facecustomization) and a voice; the child heads' vertex count and size beside the adult heads'.
Writes child_probe.json and prints a summary.
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

from fo4sf import sfplugin  # noqa: E402

FACE_TYPE = 1                    # HDPT PNAM: Face (Skyrim and Starfield)
SF_CHILD_RACE = "ChildRace"


def u32(d):
    return struct.unpack("<I", bytes(d)[:4])[0] if len(d) >= 4 else None


def text(d):
    return bytes(d).split(b"\0")[0].decode("latin-1")


def race_heads(subs):
    """{female: [HDPT FormIDs]} of a RACE's head part lists (HEAD after the MNAM / FNAM section markers)."""
    out, sex = {False: [], True: []}, None
    for s, d in subs:
        if s in (b"MNAM", b"FNAM") and len(d) == 0:
            sex = s == b"FNAM"
        elif s == b"HEAD" and sex is not None and len(d) == 4:
            out[sex].append(u32(d))
    return out


def size_of(verts):
    """{"vertices", "size_m" [x, y, z]} of a vertex array (Skyrim units -> m: 1 unit = 1/70 m)."""
    v = np.asarray(verts, float)
    return {"vertices": int(len(v)), "size": [round(float(x), 4) for x in v.max(0) - v.min(0)]}


def facegen_path(fid):
    """Skyrim's FaceGen head of a Skyrim.esm NPC."""
    return f"meshes/actors/character/facegendata/facegeom/skyrim.esm/{fid & 0xFFFFFF:08x}.nif"


def summarize_sf_children(npcs, child_race, baked):
    """{sex: {"npcs", "dials", "blends", "baked_face", "voiced", "examples": [EditorID]}} of Starfield NPCs on the
    child race (npcs: [(subs, FormID)])."""
    out = {}
    for subs, fid in npcs:
        if next((u32(d) for s, d in subs if s == b"RNAM"), None) != child_race:
            continue
        acbs = next((bytes(d) for s, d in subs if s == b"ACBS"), b"")
        sex = "female" if acbs and struct.unpack_from("<I", acbs, 0)[0] & 1 else "male"
        sigs = {s for s, _d in subs}
        o = out.setdefault(sex, {"npcs": 0, "dials": 0, "blends": 0, "baked_face": 0, "voiced": 0,
                                 "templated": 0, "examples": []})
        o["npcs"] += 1
        o["dials"] += b"FMSI" in sigs
        o["blends"] += b"BMPN" in sigs
        o["baked_face"] += fid in baked
        o["voiced"] += b"VTCK" in sigs
        o["templated"] += b"TPLT" in sigs
        if len(o["examples"]) < 8 and b"FMSI" in sigs and b"TPLT" not in sigs:
            o["examples"].append(f"{sfplugin.edid(subs)} {fid:08X}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--npc", action="append", default=[], help="Skyrim child NPC EditorIDs (Dorthe, Frodnar)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    import face_fit
    import hkx_to_af
    from fo4sf import bsa, facefit, sfmesh, ba2
    sky_esm = os.path.join(a.skyrim_data, "Skyrim.esm")
    sf_data = os.path.join(a.starfield, "Data")
    sf_esm = os.path.join(sf_data, "Starfield.esm")
    rep = {}

    # 1. Skyrim child races and their heads
    sky = bsa.SkyrimArchives(a.skyrim_data)
    srecs = sfplugin.records(sky_esm, [b"RACE", b"HDPT", b"NPC_"])
    shd = {f: s for t, _h, s, f in srecs if t == b"HDPT"}
    sraces = {f: s for t, _h, s, f in srecs if t == b"RACE"}
    by_edid = {sfplugin.edid(s).lower(): f for f, s in sraces.items()}

    def part(fid):
        s = shd.get(fid)
        if s is None:
            return {"form_id": f"{fid:08X}", "missing": True}
        return {"form_id": f"{fid:08X}", "edid": sfplugin.edid(s), "type": u32(dict(s).get(b"PNAM", bytes(4))),
                "model": text(dict(s).get(b"MODL", b""))}

    def head_size(model):
        if not model:
            return None
        try:
            data = hkx_to_af.read_any("meshes/" + model.replace("\\", "/"), sky)
            v = face_fit.skyrim_head(data, model=True)
            return size_of(v / 70.0) if v is not None else {"error": "no head shape"}
        except (SystemExit, Exception) as e:                 # noqa: BLE001 - report and go on
            return {"error": str(e)[:200]}

    rep["skyrim_child_races"] = {}
    for f, s in sorted(sraces.items()):
        e = sfplugin.edid(s)
        if not e.lower().endswith("racechild"):
            continue
        adult = by_edid.get(e.lower()[: -len("child")])
        entry = {"form_id": f"{f:08X}"}
        for female, parts in race_heads(s).items():
            sex = "female" if female else "male"
            ps = [part(p) for p in parts]
            face = next((p for p in ps if p.get("type") == FACE_TYPE), None)
            entry[sex] = {"parts": ps, "face_head": head_size(face["model"]) if face else None}
            if adult is not None:
                aps = [part(p) for p in race_heads(sraces[adult])[female]]
                aface = next((p for p in aps if p.get("type") == FACE_TYPE), None)
                entry[sex]["adult_face"] = aface
                entry[sex]["adult_face_head"] = head_size(aface["model"]) if aface else None
        rep["skyrim_child_races"][e] = entry
        print(f"Skyrim {e}: " + "; ".join(
            f"{sx} face {entry[sx].get('face_head')} (adult {entry[sx].get('adult_face_head')})"
            for sx in ("male", "female") if sx in entry))

    # 2. the child NPCs' FaceGen heads
    snpc = {sfplugin.edid(s).lower(): (s, f) for t, _h, s, f in srecs if t == b"NPC_"}
    rep["skyrim_npcs"] = {}
    for name in a.npc:
        hit = snpc.get(name.lower())
        if hit is None:
            rep["skyrim_npcs"][name] = {"missing": True}
            continue
        s, f = hit
        race = u32(dict(s).get(b"RNAM", bytes(4)))
        try:
            v = face_fit.skyrim_head(hkx_to_af.read_any(facegen_path(f), sky), model=True)
            fg = size_of(v / 70.0) if v is not None else {"error": "no head shape"}
        except (SystemExit, Exception) as e:                 # noqa: BLE001
            fg = {"error": str(e)[:200]}
        rep["skyrim_npcs"][name] = {"form_id": f"{f:08X}", "race": sfplugin.edid(sraces[race]) if race in sraces
                                    else f"{race:08X}", "female": bool(u32(dict(s).get(b"ACBS", bytes(4))) & 1),
                                    "head_parts": [part(u32(d)) for x, d in s if x == b"PNAM" and len(d) == 4],
                                    "facegen": fg}
        print(f"Skyrim NPC {name}: {rep['skyrim_npcs'][name]['race']}, FaceGen head {fg}")

    # 3. Starfield's children
    frecs = sfplugin.records(sf_esm, [b"RACE", b"NPC_", b"HDPT"])
    child = next((f for t, _h, s, f in frecs if t == b"RACE" and sfplugin.edid(s) == SF_CHILD_RACE), None)
    names = {}
    for fn in sorted(os.listdir(sf_data)):
        if fn.lower().startswith("starfield - textures") and fn.lower().endswith(".ba2"):
            names[fn] = ba2.Ba2(os.path.join(sf_data, fn)).names
    baked = face_fit.baked_face_index(names)
    rep["starfield_children"] = summarize_sf_children([(s, f) for t, _h, s, f in frecs if t == b"NPC_"], child,
                                                      baked)
    for sex, o in rep["starfield_children"].items():
        print(f"Starfield ChildRace {sex}: {o['npcs']} NPCs, {o['dials']} with dials, {o['blends']} blends, "
              f"{o['baked_face']} baked faces, {o['voiced']} voiced; e.g. {o['examples'][:3]}")
    hd = {sfplugin.edid(s): s for t, _h, s, _f in frecs if t == b"HDPT"}
    rep["starfield_heads"] = {}
    for e in ("Human_Child_Head_Boy", "Human_Child_Head_Girl"):
        s = hd.get(e)
        heads = {"child": text(dict(s).get(b"MODL", b"")) if s else None}
        for kind, model in (("child", heads["child"]),
                            ("adult", face_fit.SF_HEADS[e.endswith("Girl")][len("meshes/"):])):
            if not model:
                continue
            try:
                nb, _r = hkx_to_af.vanilla_file("meshes/" + model.replace("\\", "/"), sf_data)
                paths, _skin = facefit.starfield_head_parts(nb)
                mb, _ = hkx_to_af.vanilla_file("geometries/" + paths[0].replace("\\", "/") + ".mesh", sf_data)
                pos, _w = facefit.mesh_arrays(sfmesh.parse(mb))
                heads[kind + "_mesh"] = size_of(pos)
            except (SystemExit, Exception) as ex:          # noqa: BLE001
                heads[kind + "_mesh"] = {"error": str(ex)[:200]}
        rep["starfield_heads"][e] = heads
        print(f"Starfield {e}: child {heads.get('child_mesh')}, adult {heads.get('adult_mesh')}")
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "child_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"-> {os.path.join(a.out, 'child_probe.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
