"""What a Skyrim NPC's day is made of, and which Starfield package templates could run it (owner 2026-11-08: "try an
NPC with their schedule"; first NPC: Orgnar, the Sleeping Giant Inn's innkeeper). Read-only.

    python -I scripts\\npc\\package_survey.py --skyrim "<Skyrim SE>\\Data\\Skyrim.esm" --npc Orgnar ^
        --starfield "<Starfield>\\Data\\Starfield.esm" --out C:\\Modding\\work\\packages

Skyrim side, per --npc: the NPC (and its template chain when it takes AI packages from a template), each package in
order (the game runs the first whose schedule and conditions fit): template EditorID, schedule, flags, every data input
with its value (a reference: its base object, type and cell), the template's own inputs; where the NPC stands (its
ACHR references, cell, position) and what in its cells it owns (beds, chairs, counters: XOWN).
Starfield side: every package template (PACK type 19) with its inputs and procedure types and how many packages use
it, and for each Skyrim template the Starfield one of the same EditorID (or the closest names).
Writes <out>\\package_survey.json and prints a short summary.
"""
import argparse
import difflib
import json
import os
import struct
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import packages, skyrimnpc  # noqa: E402

TEMPLATE_AI_PACKAGES = skyrimnpc.TEMPLATE_AI_PACKAGES


def describe_inputs(ix, pack):
    out = []
    idx = [n["index"] for n in pack["input_names"] if n["name"] is None]     # a package's values in UNAM order
    for i, inp in enumerate(pack["inputs"]):
        v = inp["value"]
        if isinstance(v, dict) and v.get("is_form") and v.get("value"):
            v = dict(v, form=ix.name_of(v["value"]))
        out.append({"index": idx[i] if i < len(idx) else None, "type": inp["type"], "value": v})
    return out


def skyrim_npc(ix, edid):
    fid = ix.find_edid(b"NPC_", edid)
    if fid is None:
        return {"npc": edid, "error": "no NPC_ with this EditorID"}
    npc = skyrimnpc.parse_npc(ix.subs(fid), fid)
    chain, cur = [], npc
    while cur["template"] and cur["template_flags"] & TEMPLATE_AI_PACKAGES and len(chain) < 8:
        t = cur["template"]
        chain.append(ix.name_of(t))
        if ix.kind(t) != "NPC_":
            break                                       # a leveled list: packages come from whatever it picks
        cur = skyrimnpc.parse_npc(ix.subs(t), t)
    pk = []
    for p in cur["packages"]:
        pack = packages.parse_pack(ix.subs(p))
        tpl = None
        if pack["template"]:
            t = packages.parse_pack(ix.subs(pack["template"]))
            tpl = {"form": f"{pack['template']:08X}", "edid": t["edid"], "inputs": t["input_names"],
                   "procedures": t["procedures"], "group": t["group"]}
        pk.append({"form": f"{p:08X}", "edid": pack["edid"], "schedule": pack["schedule"], "flags": pack["flags"],
                   "type": pack["type"], "speed": pack["speed"], "interrupt_override": pack["interrupt_override"],
                   "conditions": pack["conditions"], "has_script": pack["has_script"], "owner_quest":
                   ix.name_of(pack["owner_quest"]) if pack["owner_quest"] else None, "template": tpl,
                   "inputs": describe_inputs(ix, pack)})
    refs = []
    for r in ix.by_type.get(b"ACHR", []):
        base = next((struct.unpack_from("<I", d)[0] for s, d in ix.subs(r) if s == b"NAME" and len(d) == 4), None)
        if base == fid:
            pos = next((struct.unpack_from("<3f", d) for s, d in ix.subs(r) if s == b"DATA" and len(d) >= 12), None)
            refs.append(dict(ix.name_of(r), pos=[round(c, 1) for c in pos] if pos else None))
    cells = {ix.cell_of.get(int(r["form"], 16)) for r in refs} - {None}
    owned = []
    for r, c in ix.cell_of.items():
        if c not in cells or ix.kind(r) != "REFR":
            continue
        for s, d in ix.subs(r):
            if s == b"XOWN" and len(d) >= 4 and struct.unpack_from("<I", d)[0] == fid:
                pos = next((struct.unpack_from("<3f", dd) for ss, dd in ix.subs(r) if ss == b"DATA"), None)
                owned.append(dict(ix.name_of(r), pos=[round(v, 1) for v in pos] if pos else None))
    return {"npc": edid, "form": f"{fid:08X}", "template_chain": chain, "packages": pk, "placed": refs,
            "owned_in_its_cells": owned, "factions": [ix.name_of(f)["edid"] for f, _r in npc["factions"]]}


def starfield_templates(ix):
    tpls, uses = {}, Counter()
    for fid in ix.by_type.get(b"PACK", []):
        p = packages.parse_pack(ix.subs(fid), starfield=True)
        if p["type"] == packages.TEMPLATE:
            tpls[fid] = p
        elif p["template"]:
            uses[p["template"]] += 1
    return [{"form": f"{f:08X}", "edid": p["edid"], "inputs": p["input_names"],
             "input_types": [i["type"] for i in p["inputs"]], "procedures": [x["procedure"] for x in p["procedures"]],
             "group": p["group"], "used_by": uses[f]} for f, p in sorted(tpls.items(), key=lambda kv: -uses[kv[0]])]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True)
    ap.add_argument("--npc", action="append", required=True, help="Skyrim NPC EditorID (repeatable)")
    ap.add_argument("--starfield", default="", help="Starfield.esm (its package templates)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t0 = time.time()
    sky = packages.Index(a.skyrim)
    npcs = [skyrim_npc(sky, e) for e in a.npc]
    sky.close()
    report = {"npcs": npcs}
    if a.starfield:
        sf = packages.Index(a.starfield)
        tpls = starfield_templates(sf)
        sf.close()
        report["starfield_templates"] = tpls
        names = {t["edid"].lower(): t for t in tpls if t["edid"]}
        match = {}
        for n in npcs:
            for p in n.get("packages", []):
                e = (p.get("template") or {}).get("edid")
                if not e or e in match:
                    continue
                same = names.get(e.lower())
                close = difflib.get_close_matches(e.lower(), list(names), n=4, cutoff=0.5)
                match[e] = {"same_edid": same and {"form": same["form"], "inputs": same["inputs"],
                                                   "used_by": same["used_by"]},
                            "close": [{"edid": names[c]["edid"], "form": names[c]["form"], "used_by": names[c]["used_by"],
                                       "inputs": names[c]["inputs"]} for c in close]}
        report["template_match"] = match
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "package_survey.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    for n in npcs:
        if "error" in n:
            print(f"{n['npc']}: {n['error']}")
            continue
        print(f"{n['npc']} ({n['form']}): {len(n['packages'])} packages"
              + (f" (from template {n['template_chain'][-1]['edid']})" if n["template_chain"] else "")
              + f"; placed {[(r['cell'] or {}).get('edid') if r.get('cell') else '?' for r in n['placed']]}; "
              f"owns {len(n['owned_in_its_cells'])} things in its cells")
        for p in n["packages"]:
            s = p["schedule"] or {}
            tpl = (p["template"] or {}).get("edid")
            m = (report.get("template_match") or {}).get(tpl, {})
            print(f"  {p['edid']:40} template {tpl!s:28} hour {s.get('hour')} for {s.get('duration_min')} min; "
                  f"Starfield: {'same name' if m.get('same_edid') else ', '.join(c['edid'] for c in m.get('close', [])) or '-'}")
    if a.starfield:
        print(f"Starfield: {len(report['starfield_templates'])} package templates; most used: "
              + ", ".join(f"{t['edid']} ({t['used_by']})" for t in report["starfield_templates"][:12]))
    print(f"-> {os.path.join(a.out, 'package_survey.json')} ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
