"""Where the looks menu's presets come from (2026-11-12: every new-game profile and the female body type show a
human head with our tusks, though the race's own presets RPRM / RPRF are copies with our head). Read-only.

    python -I scripts\\npc\\preset_probe.py --starfield $sf --plugin <S2SRaceTest.esm> --plugin <S2SOrcPlayer.esm> --out <folder>

1. HumanRace's presets (RPRM male / RPRF female NPC FormIDs) in Starfield.esm.
2. Every record (top-level groups, all types) whose fields hold one of those FormIDs: type, EditorID, FormID, field.
   That shows the other lists the menu may read (a form list of chargen presets, a quest, ...).
3. Per --plugin: each RACE's presets with each preset NPC's Face head part (HDPT type 1) and its model, and the
   Player record's (00000007) head parts.
Writes preset_probe.json and prints a summary.
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import fo4land, sfplugin  # noqa: E402

PRESETS = (b"RPRM", b"RPRF")


def u32(d):
    return struct.unpack("<I", bytes(d)[:4])[0] if len(d) >= 4 else None


def race_presets(subs):
    """{"male": [FormIDs], "female": [...]} of a RACE's RPRM / RPRF."""
    return {"male": [u32(d) for s, d in subs if s == b"RPRM"], "female": [u32(d) for s, d in subs if s == b"RPRF"]}


def references(path, targets, skip=(b"HumanRace",)):
    """[(type, edid, FormID, field sig)] of top-level records whose 4-byte fields hold one of targets (FormIDs).
    Fields are checked at every 4-byte offset."""
    pats = {struct.pack("<I", t): t for t in targets}
    out = []
    with fo4land.Plugin(path) as p:
        for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if item[0] != "GRUP":
                continue
            for it in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                if it[0] == "GRUP":
                    continue
                typ, off, _fl, fid = it
                try:
                    data = fo4land.record_data(p.buf, off)
                except Exception:                              # noqa: BLE001 - a record we cannot read
                    continue
                if not any(k in data for k in pats):
                    continue
                subs = list(fo4land.iter_subrecords(data))
                e = sfplugin.edid([(s, bytes(d)) for s, d in subs])
                for s, d in subs:
                    d = bytes(d)
                    for i in range(0, len(d) - 3, 4):
                        t = pats.get(d[i:i + 4])
                        if t is not None:
                            out.append((typ.decode("latin-1"), e, f"{fid:08X}", s.decode("latin-1"), f"{t:08X}"))
    return out


def face_part(npc_subs, hdpt):
    """[(HDPT FormID, EditorID, model)] of an NPC's Face-type parts (hdpt {FormID: subs})."""
    out = []
    for s, d in npc_subs:
        if s == b"PNAM" and len(d) == 4:
            h = hdpt.get(u32(d))
            if h is not None and u32(dict(h).get(b"PNAM", bytes(4))) == 1:
                out.append((f"{u32(d):08X}", sfplugin.edid(h), (dict(h).get(b"MODL", b"") or b"").rstrip(b"\0")
                            .decode("latin-1")))
    return out


FACE_SIGS = (b"TNAM", b"QNAM", b"VNAM", b"NNAM", b"INTV", b"STON", b"FMRI", b"FMRG", b"TETC", b"FDDS")


def face_fields(subs):
    """[(sig, value)] of an NPC's face texture / skin fields (texture layers, STON, phenotype), readable."""
    out = []
    for s, d in subs:
        if s in FACE_SIGS:
            d = bytes(d)
            if d.endswith(b"\0") and all(32 <= c < 127 for c in d[:-1]):
                v = d[:-1].decode("latin-1")
            elif len(d) == 1:
                v = str(d[0])
            else:
                v = d.hex()
            out.append((s.decode("latin-1"), v))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--plugin", action="append", default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    sf_esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    for p in [sf_esm] + a.plugin:
        if not os.path.isfile(p):
            raise SystemExit(f"plugin not found: {p}")
    rep = {}
    human = next(r for r in sfplugin.records(sf_esm, [b"RACE"]) if sfplugin.edid(r[2]) == "HumanRace")
    pres = race_presets(human[2])
    rep["humanrace_presets"] = {k: [f"{x:08X}" for x in v] for k, v in pres.items()}
    targets = {x for v in pres.values() for x in v}
    vnpcs = {f: s for t, _h, s, f in sfplugin.records(sf_esm, [b"NPC_"]) if f in targets}
    rep["humanrace_preset_faces"] = {sfplugin.edid(s): face_fields(s) for f, s in vnpcs.items()}
    print(f"HumanRace presets: {len(pres['male'])} male, {len(pres['female'])} female; scanning Starfield.esm ...")
    refs = references(sf_esm, targets)
    rep["references"] = refs
    by = {}
    for typ, e, fid, s, _t in refs:
        by.setdefault((typ, e, fid), set()).add(s)
    for (typ, e, fid), sigs in sorted(by.items()):
        print(f"  {typ} {e} [{fid}] fields {sorted(sigs)}")
    hdpt = {f: s for t, _h, s, f in sfplugin.records(sf_esm, [b"HDPT"])}
    for p in a.plugin:                       # every plugin's head parts (the player patch names the race plugin's)
        hdpt.update({f: s for t, _h, s, f in sfplugin.records(p, [b"HDPT"])})
    for p in a.plugin:
        recs = sfplugin.records(p, [b"RACE", b"NPC_", b"HDPT", b"FLST"])
        npcs = {f: s for t, _h, s, f in recs if t == b"NPC_"}
        pr = {}
        for t, _h, s, f in recs:
            if t == b"RACE":
                rp = race_presets(s)
                pr[sfplugin.edid(s)] = {sex: [{"npc": f"{x:08X}", "edid": sfplugin.edid(npcs[x]) if x in npcs else None,
                                               "face": face_part(npcs[x], hdpt) if x in npcs else None,
                                               "face_fields": face_fields(npcs[x]) if x in npcs else None}
                                              for x in v] for sex, v in rp.items()}
            if t == b"FLST" and sfplugin.edid(s) == "CharGenPresets":
                pr["CharGenPresets"] = [f"{u32(d):08X}" for x, d in s if x == b"LNAM"]
            if t == b"NPC_" and f == 0x7:
                pr["Player"] = {"face": face_part(s, hdpt), "RNAM": f"{u32(dict(s).get(b'RNAM', bytes(4))):08X}"}
        rep[os.path.basename(p)] = pr
        for k, v in pr.items():
            if k == "Player":
                print(f"  {os.path.basename(p)} Player: race {v['RNAM']}, face parts {v['face']}")
                continue
            if k == "CharGenPresets":
                print(f"  {os.path.basename(p)} CharGenPresets override: {len(v)} entries")
                continue
            for sex, lst in v.items():
                faces = sorted({str(x['face']) for x in lst})
                print(f"  {os.path.basename(p)} {k} {sex}: {len(lst)} presets; face parts {faces[:3]}")
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "preset_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"-> {os.path.join(a.out, 'preset_probe.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
