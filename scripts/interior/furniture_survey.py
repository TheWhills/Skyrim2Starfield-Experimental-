"""What the converted interiors' furniture and idle markers are in Skyrim, and what Starfield's look like, so NPC
packages get chairs, beds and lean spots to use (owner 2026-11-08: Orgnar's package runs, "without markers and anims
its harder to tell"). Read-only.

    python -I scripts\\interior\\furniture_survey.py --skyrim "$sky\\Skyrim.esm" --skyrim-data "$sky" ^
        --starfield "$sf\\Data\\Starfield.esm" --work C:\\Modding\\work\\s2s\\riverwood_doors --out C:\\Modding\\work\\furniture

Skyrim, per FURN / IDLM base placed in the batch's cells (<work>\\cells.txt; or --cell, repeatable): how many, its
model, keywords, interaction keyword (KNAM), active markers / flags (MNAM), the record's markers (ENAM index, disabled
entry points, FNMK keyword) and entry points (FNPR type Sit / Sleep / Lean), and the marker positions in its NIF
(BSFurnitureMarkerNode: offset in units, heading, animation type, entry points; only with --skyrim-data). Idle markers:
flags, timer, animations (IDLE EditorIDs).
Starfield, every FURN: flags (record 0x800000 Is Marker), model, keywords, MNAM, FNPR (Sit / Lay / Lean), SNAM marker
parameters (offset metres, rotation, keyword, entry / exit types), XMRK / NNAM marker models, template, and how many
references use it; every IDLM: keywords, animations, archetype / flavor keywords, model, uses. For each Skyrim base,
Starfield candidates with the same marker types, by name.
Writes <out>\\furniture_survey.json and prints a summary. Layouts: xEdit wbDefinitionsTES5 / wbDefinitionsSF1 (FURN,
IDLM), niftools nif.xml (BSFurnitureMarker, BS 100); docs/npc/furniture.md.
"""
import argparse
import difflib
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

from fo4sf import fo4land, nif, packages  # noqa: E402

IS_MARKER = 0x800000                        # record flag 23 (FURN, both games)
SKY_ANIM = {1: "Sit", 2: "Sleep", 4: "Lean"}            # FNPR type / NIF animation type (Skyrim)
SF_ANIM = {1: "Sit", 2: "Lay", 4: "Lean"}               # FNPR type (Starfield wbFurnitureAnimTypeEnum)
ENTRY = ["Front", "Behind", "Right", "Left", "Up"]           # FNPR / NAM0 / NIF entry points
SF_SIDES = ["Front", "Rear", "Right", "Left", "Other"]        # Starfield SNAM entry / exit types
SKY_MNAM_HIGH = {0x02000000: "Disables Activation", 0x04000000: "Is Perch", 0x08000000: "Must Exit to Talk",
                 0x10000000: "Has Lean Marker", 0x40000000: "Has Sit Marker", 0x80000000: "Has Sleep Marker"}
SF_MNAM_HIGH = {0x00100000: "Allow Cloth Sim", 0x00200000: "Disable Physics", 0x00400000: "Allow Awake Sound",
                0x00800000: "Enter With Weapon Drawn", 0x01000000: "Play Anim When Full",
                0x02000000: "Disables Activation", 0x04000000: "Is Perch", 0x08000000: "Must Exit to Talk",
                0x10000000: "Use Static Avoid Node", 0x40000000: "Has Model?", 0x80000000: "Is Sleep Furniture"}
U = 70.0                                     # Skyrim units per metre (as the rest of the converter)


def flags(v, names):
    return [n for i, n in enumerate(names) if v >> i & 1]


def mnam(v, starfield):
    low = 20 if starfield else 24
    high = SF_MNAM_HIGH if starfield else SKY_MNAM_HIGH
    return {"points": [i for i in range(low) if v >> i & 1], "flags": [n for b, n in high.items() if v & b]}


def zstr(d):
    return d.rstrip(b"\0").decode("utf-8", "replace")


def u32s(d):
    return list(struct.unpack_from(f"<{len(d) // 4}I", d))


def kw_names(ix, fids):
    return [ix.edid(f) or f"{f:08X}" for f in fids]


def base_record(ix, fid, starfield):
    """One FURN / IDLM's fields."""
    subs = ix.subs(fid)
    kind = ix.kind(fid)
    rflags = ix.records[fid][2]
    out = {"form": f"{fid:08X}", "type": kind, "edid": ix.edid(fid), "is_marker": bool(rflags & IS_MARKER),
           "record_flags": f"{rflags:08X}", "model": None, "keywords": [], "has_script": False}
    anim = SF_ANIM if starfield else SKY_ANIM
    markers, entries, params = [], [], []
    for s, d in subs:
        if s == b"MODL" and out["model"] is None:
            out["model"] = zstr(d)
        elif s == b"VMAD":
            out["has_script"] = True
        elif s == b"KWDA":
            out["keywords"] = kw_names(ix, u32s(d))
        elif s == b"KNAM" and len(d) == 4 and kind == "FURN":
            out["interaction_keyword"] = kw_names(ix, u32s(d))[0]
        elif s == b"FNAM" and len(d) == 2 and kind == "FURN":
            out["fnam"] = ["Ignored By Sandbox"] if d[0] & 2 else []
        elif s == b"MNAM" and len(d) == 4 and kind == "FURN":
            out["mnam"] = mnam(struct.unpack("<I", d)[0], starfield)
        elif s == b"WBDT" and d:
            out["bench_type"] = d[0]
        elif s == b"NAM1" and len(d) == 4:
            out["associated"] = ix.edid(struct.unpack("<I", d)[0])
        elif s == b"FTMP" and len(d) == 4:
            out["template"] = ix.edid(struct.unpack("<I", d)[0])
        elif s == b"ENAM" and len(d) == 4:
            markers.append({"index": struct.unpack("<I", d)[0]})
        elif s == b"NAM0" and len(d) == 4 and markers:
            markers[-1]["disabled"] = flags(struct.unpack_from("<H", d, 2)[0], ENTRY)
        elif s == b"FNMK" and len(d) == 4 and markers:
            k = struct.unpack("<I", d)[0]
            markers[-1]["keyword"] = ix.edid(k) if k else None
        elif s == b"FNPR" and len(d) >= 4:
            t, e = struct.unpack_from("<HH", d)
            entries.append({"type": anim.get(t, t), "entry": flags(e, ENTRY)})
        elif s == b"SNAM" and starfield and kind == "FURN":
            params = sf_marker_params(ix, d, struct.unpack_from("<H", ix.p.buf, ix.records[fid][1] + 20)[0])
        elif s == b"XMRK":
            out["marker_model"] = zstr(d)
        elif s == b"NNAM" and kind == "FURN":
            out["marker_files"] = d.count(b"\0") // 2
        elif s == b"IDLF" and d:
            out["idle_flags"] = d[0]
        elif s == b"IDLT" and len(d) == 4:
            out["idle_timer"] = round(struct.unpack("<f", d)[0], 3)
        elif s == b"IDLA":
            out["animations"] = kw_names(ix, u32s(d))
        elif s == b"PNAM" and len(d) == 4 and kind == "IDLM" and starfield:
            out["archetype"] = ix.edid(struct.unpack("<I", d)[0])
        elif s == b"QNAM" and len(d) == 4 and kind == "IDLM" and starfield:
            out["flavor"] = ix.edid(struct.unpack("<I", d)[0])
        elif s == b"RNAM" and len(d) == 4 and kind == "IDLM" and starfield:
            out["action"] = ix.edid(struct.unpack("<I", d)[0])
    if markers:
        out["markers"] = markers
    if entries:
        out["entry_points"] = entries
    if params:
        out["marker_params"] = params
    return out


def snam_size(version):
    """SNAM element bytes by record version (xEdit wbSNAMMarkerParams): offset 3f, rotation f, keyword (20); from 125
    entry types u8 + 3 unused (24); from 555 exit types u8 + 3 unused (28)."""
    return 28 if version >= 555 else 24 if version >= 125 else 20


def sf_marker_params(ix, d, version):
    """SNAM Marker Parameters: offset x/y/z (metres), rotation z, keyword, [entry types, exit types]."""
    size = snam_size(version)
    if len(d) % size:
        return [{"raw": d.hex(), "note": f"{len(d)} bytes, not a multiple of {size} (record version {version})"}]
    out = []
    for p in range(0, len(d), size):
        x, y, z, r, k = struct.unpack_from("<4fI", d, p)
        m = {"offset_m": [round(x, 3), round(y, 3), round(z, 3)], "rot_z_deg": round(r * 57.29578, 1),
             "keyword": ix.edid(k) if k else None}
        if size >= 24:
            m["entry"] = flags(d[p + 20], SF_SIDES)
        if size >= 28:
            m["exit"] = flags(d[p + 24], SF_SIDES)
        out.append(m)
    return out


def nif_markers(data):
    """BSFurnitureMarkerNode (NiExtraData: name, u32 count, count x [offset 3f, heading f, anim type u16, entry u16]
    for BS > 34) in a Skyrim NIF: offsets in the NIF's units, relative to the node holding it (normally the root)."""
    n = nif.parse(data)
    out = []
    for i in range(len(n.blocks)):
        if n.type_of(i) not in ("BSFurnitureMarkerNode", "BSFurnitureMarker"):
            continue
        b = n.blocks[i]
        cnt = struct.unpack_from("<I", b, 4)[0]
        if 8 + 20 * cnt != len(b):
            out.append({"block": i, "error": f"{len(b)} bytes for {cnt} positions"})
            continue
        for k in range(cnt):
            x, y, z, h, t, e = struct.unpack_from("<4fHH", b, 8 + 20 * k)
            out.append({"offset": [round(x, 2), round(y, 2), round(z, 2)], "offset_m": [round(x / U, 3),
                        round(y / U, 3), round(z / U, 3)], "heading_deg": round(h * 57.29578, 1),
                        "anim": SKY_ANIM.get(t, t), "entry": flags(e, ENTRY)})
    return out


def batch_cells(work, extra):
    names = list(extra or [])
    path = os.path.join(work, "cells.txt") if work else ""
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    with open(line, encoding="utf-8") as c:
                        names.append(json.load(c)["cell"])
    return names


def ref_base(ix, fid):
    for s, d in fo4land.iter_subrecords(fo4land.record_data(ix.p.buf, ix.records[fid][1])):
        if s == b"NAME" and len(d) == 4:
            return struct.unpack_from("<I", d)[0]
    return None


def skyrim_side(ix, cells, archives):
    cell_ids = {}
    for c in cells:
        f = ix.find_edid(b"CELL", c)
        if f is not None:
            cell_ids[f] = c
    placed = {}
    for r, c in ix.cell_of.items():
        if c not in cell_ids or ix.kind(r) != "REFR":
            continue
        b = ref_base(ix, r)
        if b is not None and ix.kind(b) in ("FURN", "IDLM"):
            placed.setdefault(b, Counter())[cell_ids[c]] += 1
    out = []
    for b, where in sorted(placed.items(), key=lambda kv: (ix.kind(kv[0]), -sum(kv[1].values()))):
        rec = base_record(ix, b, starfield=False)
        rec["placed"] = dict(where)
        if archives is not None and rec.get("model"):
            data = archives.mesh(rec["model"])
            if data is None:
                rec["nif_markers"] = "model not found in the Skyrim archives"
            else:
                try:
                    rec["nif_markers"] = nif_markers(data)
                except (nif.NifError, struct.error, ValueError) as e:
                    rec["nif_markers"] = f"unreadable: {e}"
        out.append(rec)
    return out, [c for c in cells if c not in cell_ids.values()]


def starfield_side(ix, uses):
    furn = [base_record(ix, f, starfield=True) for f in ix.by_type.get(b"FURN", [])]
    idlm = [base_record(ix, f, starfield=True) for f in ix.by_type.get(b"IDLM", [])]
    if uses:
        want = {int(r["form"], 16) for r in furn + idlm}
        count = Counter()
        for r in ix.by_type.get(b"REFR", []):
            b = ref_base(ix, r)
            if b in want:
                count[b] += 1
        for r in furn + idlm:
            r["uses"] = count[int(r["form"], 16)]
    return furn, idlm


def anim_types(rec, starfield):
    """The marker kinds of a base: Sit / Sleep / Lean (Starfield's Lay read as Sleep)."""
    t = {e["type"] for e in rec.get("entry_points", [])}
    if not starfield:
        t |= {m["anim"] for m in rec.get("nif_markers", []) if isinstance(rec.get("nif_markers"), list)
              and isinstance(m, dict) and "anim" in m}
    return {"Sleep" if x == "Lay" else x for x in t if isinstance(x, str)}


def tokens(edid):
    return set(w.lower() for w in re.findall(r"[A-Z][a-z]+|[a-z]+", edid or "") if len(w) > 2)


def candidates(sky, sf_furn, n=6):
    """Starfield FURN with the same marker kinds, closest names first (token overlap, then difflib)."""
    want = anim_types(sky, starfield=False)
    pool = [r for r in sf_furn if not r["has_script"] and r.get("edid") and (not want or anim_types(r, True) == want)]
    tk = tokens(sky.get("edid"))

    def score(r):
        return (len(tk & tokens(r["edid"])), difflib.SequenceMatcher(None, (sky["edid"] or "").lower(),
                                                                     r["edid"].lower()).ratio(), r.get("uses", 0))
    best = sorted(pool, key=score, reverse=True)[:n]
    return [{"form": r["form"], "edid": r["edid"], "is_marker": r["is_marker"], "uses": r.get("uses"),
             "keywords": r["keywords"][:6], "marker_params": r.get("marker_params")} for r in best]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--skyrim-data", default="", help="Skyrim Data folder (archives): marker positions from the NIFs")
    ap.add_argument("--starfield", default="", help="Starfield.esm")
    ap.add_argument("--work", default="", help="interior batch work folder (cells.txt)")
    ap.add_argument("--cell", action="append", default=[], help="Skyrim cell EditorID (repeatable)")
    ap.add_argument("--no-uses", action="store_true", help="skip counting Starfield references per base (faster)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t0 = time.time()
    cells = batch_cells(a.work, a.cell)
    if not cells:
        ap.error("no cells: give --work (with cells.txt) or --cell")
    archives = None
    if a.skyrim_data:
        from fo4sf import bsa
        archives = bsa.SkyrimArchives(a.skyrim_data)
    sky = packages.Index(a.skyrim)
    try:
        sky_bases, missing = skyrim_side(sky, cells, archives)
    finally:
        sky.close()
    report = {"cells": cells, "cells_not_found": missing, "skyrim": sky_bases}
    if a.starfield:
        sf = packages.Index(a.starfield)
        try:
            furn, idlm = starfield_side(sf, not a.no_uses)
        finally:
            sf.close()
        furn.sort(key=lambda r: -(r.get("uses") or 0))
        idlm.sort(key=lambda r: -(r.get("uses") or 0))
        report["starfield_furniture"] = furn
        report["starfield_idle_markers"] = idlm
        snam_kw = Counter(m.get("keyword") for r in furn for m in (r.get("marker_params") or [])
                          if isinstance(m, dict))
        report["starfield_marker_keywords"] = snam_kw.most_common()
        for s in sky_bases:
            if s["type"] == "FURN":
                s["starfield_candidates"] = candidates(s, furn)
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "furniture_survey.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)

    if missing:
        print(f"cells not in Skyrim.esm: {missing}")
    print(f"Skyrim: {len(sky_bases)} furniture / idle marker bases in {len(cells)} cells")
    for s in sky_bases:
        nm = s.get("nif_markers")
        marks = ", ".join(f"{m['anim']} {m['offset']} {m['heading_deg']}deg" for m in nm if "anim" in m) \
            if isinstance(nm, list) else (nm or "")
        extra = (f" anims {s.get('animations')}" if s["type"] == "IDLM" else
                 f" kw {s['keywords']} mnam {s.get('mnam', {}).get('flags')} entries "
                 f"{[e['type'] for e in s.get('entry_points', [])]}")
        print(f"  {s['type']} {s['edid']} x{sum(s['placed'].values())}{' (marker)' if s['is_marker'] else ''}:{extra}"
              + (f"; NIF: {marks}" if marks else ""))
        for c in s.get("starfield_candidates", [])[:3]:
            print(f"      Starfield {c['edid']} ({c['form']}, {c['uses']} uses{', marker' if c['is_marker'] else ''})")
    if a.starfield:
        furn = report["starfield_furniture"]
        sizes = Counter(len(r.get("marker_params") or []) for r in furn)
        print(f"Starfield: {len(furn)} furniture ({sum(r['is_marker'] for r in furn)} marker-only, "
              f"{sum(1 for r in furn if r.get('marker_params'))} with SNAM; markers per SNAM {dict(sorted(sizes.items()))}), "
              f"{len(report['starfield_idle_markers'])} idle markers")
        print("  SNAM keywords: " + ", ".join(f"{k} ({v})" for k, v in report["starfield_marker_keywords"][:15]))
        print("  most used furniture: " + ", ".join(f"{r['edid']} ({r.get('uses')})" for r in furn[:12]))
        mk = [r for r in furn if r["is_marker"]][:12]
        print("  marker-only furniture: " + ", ".join(f"{r['edid']} ({r.get('uses')})" for r in mk))
        print("  most used idle markers: " + ", ".join(f"{r['edid']} ({r.get('uses')})"
                                                      for r in report["starfield_idle_markers"][:12]))
    print(f"-> {path} ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
