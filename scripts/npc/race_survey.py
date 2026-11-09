"""Every Skyrim race against what Starfield's character system can do, to plan faithful races with working sliders
(owner 2026-11-08: "figure out each race difference ... eventually we need to have them all with sliders as well, not
just static parts"). Read-only; docs/npc/races.md.

    python -I scripts\\npc\\race_survey.py --skyrim-data "$sky" --starfield $sf --out C:\\Modding\\work\\races

Skyrim (Skyrim.esm; record layouts xEdit wbDefinitionsTES5 RACE / HDPT / ARMA): per race, how many NPCs use it, flags
(playable, FaceGen head, child), keywords, height / weight per sex, skeleton, the skin armor's worn models (body,
hands, feet, tail), and per sex the head data: head parts (type, model, vertex count, extra parts such as ears /
tusks / mouth, and their .tri files: race morph, expression tri, chargen tri with its slider names), face morph
presets (nose / brow / eye / lip variants), race presets, hair colours, face detail textures, the default face texture,
tint layers (mask file and type: skin tone, war paint, dirt ...), hairs / eyes available, morph race, armor race.
Each race's head is compared with NordRace's (same vertex count = same topology; then how far its base head differs).
Starfield (Starfield.esm, wbDefinitionsSF1): per RACE with NPCs, its skeleton, chargen per sex (race presets, morph
groups and their morphs, face morph phenotypes, face dials, skin tone files), head parts and bone modifiers; head
parts by type (incl. the Creature Head / Tail types) and which carry a morph (MRPH); and the character files in the
archives (facial bone regions, heads, chargen morph folders).
Writes <out>\\race_survey.json and <out>\\race_survey.md (a table per race).
"""
import argparse
import json
import os
import re
import struct
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import bsa, fo4land, nif as nifmod, packages, skyrimskin, skyrimtri  # noqa: E402

SKY_PART_TYPES = ["Misc", "Face", "Eyes", "Hair", "Facial Hair", "Scar", "Eyebrows"]
SF_PART_TYPES = ["Misc", "Face", "Right Eye", "Hair", "Facial Hair", "Scar", "Eyebrows", "Jewelry", "Meatcaps",
                 "Teeth", "Head Rear", "Extra Hair", "Left Eye", "Eyelashes", "Creature Head", "Creature Torso",
                 "Creature Arms", "Creature Legs", "Creature Tail", "Creature Wings"]
TRI_KINDS = {0: "race_morph", 1: "tri", 2: "chargen"}
TINT_TYPES = ["None", "Lip Color", "Cheek Color", "Eyeliner", "EyeSocket Upper", "EyeSocket Lower", "Skin Tone",
              "Paint", "Laugh Lines", "Cheek Color Lower", "Nose", "Chin", "Neck", "Forehead", "Dirt", "Unknown 16"]
RACE_FLAGS = {0x1: "Playable", 0x2: "FaceGen Head", 0x4: "Child"}
SEX = {b"MNAM": "male", b"FNAM": "female"}
U = 70.0


def zs(d):
    return fo4land.zstring(d)


def u32(d, o=0):
    return struct.unpack_from("<I", d, o)[0]


def edids(ix, fids):
    return [ix.edid(f) or f"{f:08X}" for f in fids]


# ------------------------------------------------------------------------------------------------------------ Skyrim
def sky_head_part(ix, fid, files, seen=None):
    """A Skyrim HDPT with its extra parts (recursively) and files."""
    seen = seen if seen is not None else set()
    if fid in seen or ix.kind(fid) != "HDPT":
        return None
    seen.add(fid)
    out = {"edid": ix.edid(fid), "form": f"{fid:08X}", "type": None, "model": None, "flags": 0, "tris": [],
           "extra": []}
    kind = None
    for s, d in ix.subs(fid):
        if s == b"MODL":
            out["model"] = zs(d)
        elif s == b"PNAM" and len(d) >= 4:
            t = u32(d)
            out["type"] = SKY_PART_TYPES[t] if t < len(SKY_PART_TYPES) else t
        elif s == b"DATA" and d:
            out["flags"] = d[0]
        elif s == b"NAM0" and len(d) >= 4:
            kind = TRI_KINDS.get(u32(d), u32(d))
        elif s == b"NAM1":
            out["tris"].append({"kind": kind, "file": zs(d)})
        elif s == b"HNAM" and len(d) >= 4:
            ex = sky_head_part(ix, u32(d), files, seen)
            if ex:
                out["extra"].append(ex)
        elif s == b"TNAM" and len(d) >= 4:
            out["texture_set"] = ix.edid(u32(d))
    if out["model"]:
        out["mesh"] = files.mesh_info(out["model"])
    for t in out["tris"]:
        t.update(files.tri_info(t["file"]))
    return out


class SkyFiles:
    """Skyrim archive reads, cached: a NIF's shapes and vertex counts, a .tri's morphs."""

    def __init__(self, archives):
        self.a = archives
        self.cache = {}

    def _read(self, path, prefix):
        if self.a is None:
            return None
        p = bsa.norm(path)
        return self.a._read(p if p.startswith(prefix) else prefix + p)

    def mesh_info(self, path):
        key = ("nif", path.lower())
        if key not in self.cache:
            d = self._read(path, "meshes\\")
            if d is None:
                self.cache[key] = {"error": "not in the archives" if self.a else "no --skyrim-data"}
            else:
                try:
                    sh = skyrimskin.skinned_shapes(nifmod.parse(d))
                    self.cache[key] = {"shapes": [{"name": s.name.decode("latin-1"), "vertices": len(s.positions)}
                                                  for s in sh]}
                except Exception as e:                   # report, keep going
                    self.cache[key] = {"error": f"{type(e).__name__}: {e}"}
        return self.cache[key]

    def tri(self, path):
        key = ("tri", path.lower())
        if key not in self.cache:
            d = self._read(path, "meshes\\")
            if d is None:
                self.cache[key] = None
            else:
                try:
                    self.cache[key] = skyrimtri.parse(d)
                except Exception as e:
                    self.cache[key] = {"error": f"{type(e).__name__}: {e}"}
        return self.cache[key]

    def tri_info(self, path):
        t = self.tri(path)
        if t is None:
            return {"error": "not in the archives" if self.a else "no --skyrim-data"}
        if "error" in t:
            return {"error": t["error"]}
        return {"vertices": t["vertices"], "complete": t["complete"], "morphs": [m["name"] for m in t["morphs"]],
                "morph_max_offset": {m["name"]: m["max_offset"] for m in t["morphs"]},
                "stat_morphs": len(t["stat_morphs"])}


def sky_arma_models(ix, armo):
    out = []
    for s, d in ix.subs(armo):
        if s == b"MODL" and len(d) == 4:
            a = u32(d)
            row = {"addon": ix.edid(a)}
            for s2, d2 in ix.subs(a):
                if s2 == b"MOD2":
                    row["male"] = zs(d2)
                elif s2 == b"MOD3":
                    row["female"] = zs(d2)
                elif s2 in (b"BOD2", b"BODT") and len(d2) >= 4:
                    row["slots"] = [30 + i for i in range(32) if u32(d2) >> i & 1]
                elif s2 == b"RNAM" and len(d2) == 4:
                    row["race"] = ix.edid(u32(d2))
            out.append(row)
    return out


def sky_race(ix, fid, files):
    r = {"edid": ix.edid(fid), "form": f"{fid:08X}", "keywords": [], "flags": [], "height": {}, "weight": {},
         "skeleton": {}, "body_parts": {"male": [], "female": []}, "head": {}}
    sex, section, tint = None, "top", None
    for s, d in ix.subs(fid):
        if s in SEX:
            sex = SEX[s]
            if section == "head":
                r["head"].setdefault(sex, {"parts": [], "presets": 0, "morph_variants": 0, "hair_colors": 0,
                                           "face_detail_sets": 0, "default_face_texture": None, "tints": [],
                                           "model": None})
            continue
        if s == b"KWDA":
            r["keywords"] = edids(ix, struct.unpack_from(f"<{len(d) // 4}I", d))
        elif s == b"WNAM" and len(d) == 4 and u32(d):
            r["skin"] = {"armor": ix.edid(u32(d)), "addons": sky_arma_models(ix, u32(d))}
        elif s == b"DATA" and len(d) >= 36 and section == "top":
            hm, hf, wm, wf, fl = struct.unpack_from("<4fI", d, 16)
            r["height"] = {"male": round(hm, 3), "female": round(hf, 3)}
            r["weight"] = {"male": round(wm, 3), "female": round(wf, 3)}
            r["flags"] = [n for b, n in RACE_FLAGS.items() if fl & b]
        elif s == b"ANAM" and section == "top" and sex:
            r["skeleton"][sex] = zs(d)
        elif s == b"NAM1":
            section = "body"
        elif s == b"MODL" and section == "body" and sex:
            r["body_parts"][sex].append(zs(d))
        elif s == b"NAM3":
            section = "behavior"
        elif s == b"MODL" and section == "behavior" and sex:
            r.setdefault("behavior", {})[sex] = zs(d)
        elif s == b"HNAM" and section != "head":
            r["hairs"] = len(d) // 4
        elif s == b"ENAM" and section != "head":
            r["eyes"] = edids(ix, struct.unpack_from(f"<{len(d) // 4}I", d))
        elif s == b"VTCK" and len(d) >= 8:
            r["voices"] = edids(ix, struct.unpack_from("<2I", d))
        elif s == b"HCLF" and len(d) >= 8:
            r["default_hair_colors"] = edids(ix, struct.unpack_from("<2I", d))
        elif s == b"NAM0":
            section = "head"
        elif s == b"NAM8" and len(d) == 4:
            r["morph_race"] = ix.edid(u32(d))
        elif s == b"RNAM" and len(d) == 4:
            r["armor_race"] = ix.edid(u32(d))
        elif section == "head" and sex:
            h = r["head"].setdefault(sex, {"parts": [], "presets": 0, "morph_variants": 0, "hair_colors": 0,
                                           "face_detail_sets": 0, "default_face_texture": None, "tints": [],
                                           "model": None})
            if s == b"HEAD" and len(d) == 4:
                part = sky_head_part(ix, u32(d), files)
                if part:
                    h["parts"].append(part)
            elif s == b"MPAV":
                h["morph_variants"] += 1
            elif s in (b"RPRM", b"RPRF"):
                h["presets"] += 1
            elif s in (b"AHCM", b"AHCF"):
                h["hair_colors"] += 1
            elif s in (b"FTSM", b"FTSF"):
                h["face_detail_sets"] += 1
            elif s in (b"DFTM", b"DFTF") and len(d) == 4:
                h["default_face_texture"] = ix.edid(u32(d))
            elif s == b"TINI" and len(d) >= 2:
                tint = {"index": struct.unpack_from("<H", d)[0], "file": None, "type": None, "presets": 0}
                h["tints"].append(tint)
            elif s == b"TINT" and tint is not None:
                tint["file"] = zs(d)
            elif s == b"TINP" and tint is not None and len(d) >= 2:
                t = struct.unpack_from("<H", d)[0]
                tint["type"] = TINT_TYPES[t] if t < len(TINT_TYPES) else t
            elif s == b"TINC" and tint is not None:
                tint["presets"] += 1
            elif s == b"MODL":
                h["model"] = zs(d)
    return r


def face_part(head):
    """The race head's Face part (type Face), or None."""
    return next((p for p in (head or {}).get("parts", []) if p.get("type") == "Face"), None)


def compare_heads(races, files):
    """Each race's face part against NordRace's (same sex): vertex counts, and with the same count the largest and
    mean distance between their base heads (from the expression .tri's base vertices, units and metres)."""
    nord = next((r for r in races if r["edid"] == "NordRace"), None)
    if not nord:
        return
    for r in races:
        for sex, h in r["head"].items():
            f, nf = face_part(h), face_part(nord["head"].get(sex))
            if not f or not nf:
                continue
            cmp = {"model": f["model"], "nord_model": nf["model"], "same_model": (f["model"] or "").lower() ==
                   (nf["model"] or "").lower()}
            mv = [s["vertices"] for s in (f.get("mesh") or {}).get("shapes", [])]
            nv = [s["vertices"] for s in (nf.get("mesh") or {}).get("shapes", [])]
            cmp["vertices"], cmp["nord_vertices"] = mv, nv
            tri = next((t for t in f["tris"] if t["kind"] == "tri"), None)
            ntri = next((t for t in nf["tris"] if t["kind"] == "tri"), None)
            if tri and ntri:
                a, b = files.tri(tri["file"]), files.tri(ntri["file"])
                if a and b and "base" in a and "base" in b:
                    cmp["same_topology"] = a["vertices"] == b["vertices"] and a["triangles"] == b["triangles"]
                    if cmp["same_topology"]:
                        import numpy as np
                        dd = np.linalg.norm(a["base"] - b["base"], axis=1)
                        cmp["base_diff_mean_m"] = round(float(dd.mean()) / U, 4)
                        cmp["base_diff_max_m"] = round(float(dd.max()) / U, 4)
                    cmp["expression_morphs_same"] = [m["name"] for m in a["morphs"]] == [m["name"] for m in b["morphs"]]
            chargen = next((t for t in f["tris"] if t["kind"] == "chargen"), None)
            nch = next((t for t in nf["tris"] if t["kind"] == "chargen"), None)
            if chargen and nch:
                cm, nm = set(chargen.get("morphs", [])), set(nch.get("morphs", []))
                cmp["chargen_sliders"] = len(cm)
                cmp["chargen_only_here"] = sorted(cm - nm)
                cmp["chargen_missing_here"] = sorted(nm - cm)
            extras = sorted({(e.get("type"), e.get("edid")) for p in h["parts"] for e in [p] + p.get("extra", [])
                             if e.get("type") not in ("Face",)}, key=str)
            nextras = sorted({(e.get("type"), e.get("edid")) for p in nord["head"][sex]["parts"]
                              for e in [p] + p.get("extra", []) if e.get("type") not in ("Face",)}, key=str)
            cmp["parts"] = [f"{t}: {e}" for t, e in extras]
            cmp["parts_not_in_nord"] = [f"{t}: {e}" for t, e in extras if (t, e) not in set(nextras)]
            h["vs_nord"] = cmp


def skyrim_side(esm, archives):
    ix = packages.Index(esm)
    try:
        files = SkyFiles(archives)
        count = Counter()
        for n in ix.by_type.get(b"NPC_", []):
            rn = next((u32(d) for s, d in ix.subs(n) if s == b"RNAM" and len(d) == 4), None)
            if rn is not None:
                count[rn] += 1
        races = []
        for fid in ix.by_type.get(b"RACE", []):
            r = sky_race(ix, fid, files)
            r["npcs"] = count[fid]
            races.append(r)
        compare_heads(races, files)
        races.sort(key=lambda r: (-("Playable" in r["flags"]), -r["npcs"]))
        return races
    finally:
        ix.close()


# --------------------------------------------------------------------------------------------------------- Starfield
def sf_race(ix, fid):
    r = {"edid": ix.edid(fid), "form": f"{fid:08X}", "skeleton": {}, "chargen": {}, "head_parts": {},
         "bone_modifiers": {}}
    sex, group, morph = None, None, None
    for s, d in ix.subs(fid):
        if s in SEX:
            sex = SEX[s]
            continue
        if not sex:
            continue
        c = r["chargen"].setdefault(sex, {"presets": 0, "morph_groups": [], "phenotypes": [], "dials": 0})
        if s == b"ANAM" and sex not in r["skeleton"]:
            r["skeleton"][sex] = zs(d)
        elif s in (b"RPRM", b"RPRF"):
            c["presets"] += 1
        elif s == b"MPGN":
            group = {"name": zs(d), "morphs": []}
            c["morph_groups"].append(group)
        elif s == b"MPGM" and group is not None:
            group["morphs"].append(zs(d))
        elif s == b"FMRI" and len(d) >= 4:
            morph = {"index": u32(d)}
            c["phenotypes"].append(morph)
        elif s == b"FMRU" and morph is not None and "id" not in morph:
            morph["id"] = zs(d)
        elif s == b"FDDS":
            c["skin_subtype"] = zs(d)
        elif s == b"FDSI":
            c["dials"] += 1
        elif s in (b"BSTT", b"HSTT", b"FCTP", b"FSTT"):
            c[s.decode()] = zs(d)
        elif s == b"HEAD" and len(d) == 4:
            p = u32(d)
            t = next((u32(dd) for ss, dd in ix.subs(p) if ss == b"PNAM" and len(dd) >= 4), None)
            mdl = next((zs(dd) for ss, dd in ix.subs(p) if ss == b"MODL"), None)
            r["head_parts"].setdefault(sex, []).append(
                {"edid": ix.edid(p), "type": SF_PART_TYPES[t] if t is not None and t < len(SF_PART_TYPES) else t,
                 "model": mdl})
        elif s == b"BNAM" and len(d) == 4 and ix.kind(u32(d)) == "BMOD":
            b = u32(d)
            dd = next((dd for ss, dd in ix.subs(b) if ss == b"DATA"), b"")
            parts, p = [], 0
            for _ in range(3):                             # type, driver, target: u16-length strings
                if p + 2 > len(dd):
                    break
                n = struct.unpack_from("<H", dd, p)[0]
                parts.append(dd[p + 2:p + 2 + n].split(b"\0", 1)[0].decode("latin-1", "replace"))
                p += 2 + n
            r["bone_modifiers"].setdefault(sex, []).append({"edid": ix.edid(b), "type_driver_target": parts})
        elif s == b"NAM8" and len(d) == 4:
            r["morph_race"] = ix.edid(u32(d))
        elif s == b"RNAM" and len(d) == 4:
            r["armor_race"] = ix.edid(u32(d))
    r["chargen"] = {k: v for k, v in r["chargen"].items() if v["morph_groups"] or v["dials"] or v["phenotypes"]}
    return r


def sf_archive_files(sf_data):
    from fo4sf import ba2
    rx = re.compile(r"facialboneregions|characterassets/.*\.(nif|txt)$|morphs/human/[^/]+/chargen/[^/]+/|"
                    r"actors/(human|creatures?)/[^/]*/?.*head.*\.nif$", re.I)
    found, folders = [], Counter()
    data = os.path.join(sf_data, "Data")
    for fn in sorted(os.listdir(data)):
        if not (fn.lower().startswith("starfield - meshes") and fn.lower().endswith(".ba2")):
            continue
        try:
            arc = ba2.Ba2(os.path.join(data, fn))
        except Exception:
            continue
        for n in arc.names:
            p = n.replace("\\", "/").lower()
            if "morphs/human/" in p and "/chargen/" in p:
                folders["/".join(p.split("/")[:6])] += 1
            elif rx.search(p):
                found.append(p)
    return {"files": sorted(set(found))[:400], "chargen_morph_folders": dict(folders.most_common(60))}


def starfield_side(sf_data):
    ix = packages.Index(os.path.join(sf_data, "Data", "Starfield.esm"))
    try:
        count = Counter()
        for n in ix.by_type.get(b"NPC_", []):
            rn = next((u32(d) for s, d in ix.subs(n) if s == b"RNAM" and len(d) == 4), None)
            if rn is not None:
                count[rn] += 1
        races = []
        for fid in ix.by_type.get(b"RACE", []):
            if count[fid] == 0:
                continue
            r = sf_race(ix, fid)
            r["npcs"] = count[fid]
            races.append(r)
        races.sort(key=lambda r: -r["npcs"])
        parts = Counter()
        morphs = Counter()
        creature = []
        for p in ix.by_type.get(b"HDPT", []):
            subs = ix.subs(p)
            t = next((u32(d) for s, d in subs if s == b"PNAM" and len(d) >= 4), None)
            name = SF_PART_TYPES[t] if t is not None and t < len(SF_PART_TYPES) else str(t)
            parts[name] += 1
            if any(s == b"MNAM" for s, _d in subs):
                morphs[name] += 1
            if t is not None and t >= 14 and len(creature) < 40:
                creature.append({"edid": ix.edid(p), "type": name,
                                 "model": next((zs(d) for s, d in subs if s == b"MODL"), None)})
        return {"races": races, "head_parts_by_type": dict(parts), "head_parts_with_morph": dict(morphs),
                "creature_parts": creature}
    finally:
        ix.close()


# -------------------------------------------------------------------------------------------------------- report
def markdown(sky, sf):
    L = ["# Skyrim races vs Starfield (race_survey.py)", ""]
    for r in sky:
        if r["npcs"] == 0 and "Playable" not in r["flags"]:
            continue
        L.append(f"## {r['edid']} ({r['npcs']} NPCs; {', '.join(r['flags']) or '-'})")
        L.append(f"height m/f {r['height'].get('male')} / {r['height'].get('female')}, weight "
                 f"{r['weight'].get('male')} / {r['weight'].get('female')}; skeleton {r['skeleton'].get('male')}; "
                 f"armor race {r.get('armor_race')}, morph race {r.get('morph_race')}")
        if r.get("skin"):
            L.append("skin: " + "; ".join(f"{a['addon']} {a.get('slots')}" for a in r["skin"]["addons"]))
        for sex, h in r["head"].items():
            v = h.get("vs_nord", {})
            L.append(f"- {sex}: parts {v.get('parts') or [p['type'] for p in h['parts']]}; tints {len(h['tints'])} "
                     f"({', '.join(sorted({str(t['type']) for t in h['tints']}))}); presets {h['presets']}, morph "
                     f"variants {h['morph_variants']}, hair colours {h['hair_colors']}")
            if v:
                L.append(f"  - vs Nord: same model {v.get('same_model')}, same topology {v.get('same_topology')}, "
                         f"base head differs mean {v.get('base_diff_mean_m')} m / max {v.get('base_diff_max_m')} m; "
                         f"chargen sliders {v.get('chargen_sliders')}, only here {v.get('chargen_only_here')}, "
                         f"missing {v.get('chargen_missing_here')}; parts not in Nord {v.get('parts_not_in_nord')}")
        L.append("")
    if sf:
        L.append("# Starfield")
        for r in sf["races"][:20]:
            ch = "; ".join(f"{sx}: {len(c['morph_groups'])} morph groups, {len(c['phenotypes'])} phenotypes, "
                           f"{c['dials']} dials, {c['presets']} presets" for sx, c in r["chargen"].items())
            L.append(f"- {r['edid']} ({r['npcs']} NPCs): {ch or 'no chargen'}; head parts "
                     f"{[p['type'] for p in r['head_parts'].get('male', [])]}; bone modifiers "
                     f"{len(r['bone_modifiers'].get('male', []))}")
        L.append(f"- head parts by type: {sf['head_parts_by_type']}; with a morph: {sf['head_parts_with_morph']}")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True, help="Skyrim SE Data folder (Skyrim.esm and the archives)")
    ap.add_argument("--skyrim-esm", default="", help="default: <skyrim-data>\\Skyrim.esm")
    ap.add_argument("--starfield", default="", help="Starfield install folder (Data\\Starfield.esm, archives)")
    ap.add_argument("--no-archives", action="store_true", help="records only (no meshes / .tri files)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t0 = time.time()
    archives = None if a.no_archives else bsa.SkyrimArchives(a.skyrim_data)
    sky = skyrim_side(a.skyrim_esm or os.path.join(a.skyrim_data, "Skyrim.esm"), archives)
    sf = None
    if a.starfield:
        sf = starfield_side(a.starfield)
        if not a.no_archives:
            sf["archive_files"] = sf_archive_files(a.starfield)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "race_survey.json"), "w", encoding="utf-8") as fh:
        json.dump({"skyrim": sky, "starfield": sf}, fh, indent=1, default=str)
    md = markdown(sky, sf)
    with open(os.path.join(a.out, "race_survey.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    shown = [r for r in sky if "Playable" in r["flags"]]
    print(f"Skyrim: {len(sky)} races, {len(shown)} playable")
    for r in shown:
        for sex in ("male", "female"):
            v = r["head"].get(sex, {}).get("vs_nord", {})
            print(f"  {r['edid']:18} {sex:6} {r['npcs']:4} NPCs  h {r['height'].get(sex)}  same topology "
                  f"{v.get('same_topology')}  base diff {v.get('base_diff_mean_m')} m  sliders "
                  f"{v.get('chargen_sliders')}  extra parts {v.get('parts_not_in_nord')}")
    if sf:
        print(f"Starfield: {len(sf['races'])} races with NPCs; chargen in "
              f"{[r['edid'] for r in sf['races'] if r['chargen']]}; head parts by type {sf['head_parts_by_type']}")
    print(f"-> {os.path.join(a.out, 'race_survey.md')} ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
