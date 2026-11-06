"""How Starfield stores an NPC's eyes, eyebrows and skin tone, and what Skyrim says for the test NPCs (owner
2026-11-06: match eye colour, skin tone and brows; compare two men and two women). Read-only; writes
--out\\npc_face_probe.json:

  * Starfield: over Starfield.esm's human NPCs with a face (RNAM HumanRace, FMSI): how often each subrecord appears and
    its most common values (as text when it reads as text: hair colour is a name, HCOL), the head parts they use by
    head-part type (PNAM) with the most used EditorIDs, a few NPCs dumped in full, HumanRace's subrecords (its text
    values: chargen lists?), and EditorIDs anywhere that mention eyes / skin tone / brows;
  * Skyrim (with --skyrim-data and --npc): each NPC's head parts (type, EditorID, model), texture lighting (QNAM),
    and tint layers with their race mask (path and kind: skin tone, lips ...).

    python -I scripts\\npc\\npc_face_probe.py --starfield "D:\\...\\Starfield" --skyrim-data "C:\\...\\Data" --npc Ralof --npc Nazeem --npc Ysolda --npc Saadia --out C:\\Modding\\work\\npc_face_probe
"""
import argparse
import collections
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)                     # npc_records (python -I leaves the script's own folder off the path)

from fo4sf import fo4land, sfplugin, skyrimnpc  # noqa: E402
import npc_records  # noqa: E402

DUMP = ("SarahMorgan", "Barrett", "ChargenPresetFemale02_Swap", "ChargenPresetMale01")
WORDS = re.compile(r"eye|skin.?tone|brow|complexion", re.I)
SKIP_GROUPS = {b"DIAL", b"INFO", b"CELL", b"WRLD", b"NAVM", b"LAND", b"REFR", b"ACHR", b"QUST", b"PNDT", b"STDT",
               b"SCEN", b"PACK", b"LCTN", b"BIOM"}
def value(d: bytes):
    d = bytes(d)
    if d and d[-1:] == b"\0" and all(32 <= b < 127 for b in d[:-1]) and len(d) > 1:
        return d[:-1].decode("latin-1")
    return d[:24].hex() + ("..." if len(d) > 24 else "")


def dump(subs) -> list:
    return [{"sig": s.decode("latin-1"), "size": len(d), "value": value(d)} for s, d in subs]


def starfield(esm: str, dump_names=DUMP) -> dict:
    races = {fid: sfplugin.edid(s) for _t, _h, s, fid in sfplugin.records(esm, [b"RACE"])}
    human = next((f for f, e in races.items() if e == "HumanRace"), None)
    hdpt = {fid: s for _t, _h, s, fid in sfplugin.records(esm, [b"HDPT"])}

    def ptype(subs):
        d = next((bytes(d) for s, d in subs if s == b"PNAM" and len(d) >= 4), None)
        return struct.unpack_from("<I", d, 0)[0] if d else None
    sig_count, values, parts = collections.Counter(), collections.defaultdict(collections.Counter), {}
    derma, layers = collections.Counter(), collections.Counter()
    dumps, n = [], 0
    for _t, _h, subs, fid in sfplugin.records(esm, [b"NPC_"]):
        sigs = {s for s, _d in subs}
        rnam = next((struct.unpack_from("<I", bytes(d), 0)[0] for s, d in subs if s == b"RNAM"), None)
        e = sfplugin.edid(subs)
        if e in dump_names or (e.startswith("ChargenPreset") and len(dumps) < 6):
            dumps.append({"edid": e, "form_id": f"{fid:08X}", "subs": dump(subs)})
        if rnam != human or b"FMSI" not in sigs:
            continue
        n += 1
        layer = None
        ston = next((bytes(d)[0] for s_, d in subs if s_ == b"STON" and len(d)), None)
        for s_, d in subs:                     # texture layers: MNAM, TNAM name, QNAM texture, VNAM folder, NNAM, INTV
            if s_ == b"TNAM":
                layer = value(d)
                layers[layer] += 1
            elif s_ == b"QNAM" and layer == "Dermaesthetic":
                derma[f"{value(d)} | STON {ston}"] += 1
                layer = None
        for s in sigs:
            sig_count[s.decode("latin-1")] += 1
        for s, d in subs:
            if len(d) <= 64 and s not in (b"EDID", b"FULL", b"FMSI", b"FMRS", b"FMRI", b"FMRG"):
                values[s.decode("latin-1")][value(d)] += 1
            if s == b"PNAM" and len(d) >= 4:
                p = struct.unpack_from("<I", bytes(d), 0)[0]
                hp = hdpt.get(p)
                t = ptype(hp) if hp is not None else None
                row = parts.setdefault(str(t), collections.Counter())
                row[sfplugin.edid(hp) if hp is not None else f"{p:08X}"] += 1
    hp_types = collections.Counter(str(ptype(s)) for s in hdpt.values())
    race = next((s for _t, _h, s, fid in sfplugin.records(esm, [b"RACE"]) if fid == human), [])
    race_sigs = collections.Counter(s.decode("latin-1") for s, _d in race)
    race_text = [f"{s.decode('latin-1')}: {value(d)}" for s, d in race
                 if isinstance(value(d), str) and not re.fullmatch(r"[0-9a-f.]+", value(d))][:300]
    return {"human_npcs_with_face": n,
            "subrecords": sig_count.most_common(),
            "values": {k: {"distinct": len(v), "top": v.most_common(15)} for k, v in sorted(values.items())},
            "head_part_types_in_esm": hp_types.most_common(),
            "head_parts_used_by_type": {k: {"distinct": len(v), "top": v.most_common(25)} for k, v in parts.items()},
            "texture_layers": layers.most_common(),
            "dermaesthetic_by_skin_tone": sorted(derma.items()),
            "dumps": dumps, "human_race_subrecords": race_sigs.most_common(), "human_race_text": race_text,
            "editor_ids": editor_ids(esm)}


def editor_ids(esm: str, limit: int = 300) -> list:
    """(record type, EditorID) of records whose EditorID mentions eyes / skin tone / brows (big groups skipped)."""
    out = []
    with fo4land.Plugin(esm) as p:
        for g in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if g[0] != "GRUP" or g[3] in SKIP_GROUPS:
                continue
            for it in fo4land.iter_items(p.buf, g[1] + 24, g[2]):
                if it[0] == "GRUP":
                    continue
                typ, off, _fl, fid = it
                try:
                    subs = fo4land.iter_subrecords(fo4land.record_data(p.buf, off))
                    e = next((fo4land.zstring(d) for s, d in subs if s == b"EDID"), "")
                except Exception:                           # noqa: BLE001 (report only)
                    continue
                if WORDS.search(e):
                    out.append(f"{typ.decode('latin-1')} {fid:08X} {e}")
                    if len(out) >= limit:
                        return out
    return out


def skyrim(esm: str, names) -> list:
    npcs = {fid: skyrimnpc.parse_npc(s, fid) for _t, _h, s, fid in sfplugin.records(esm, [b"NPC_"])}
    by_edid = {n["edid"].lower(): n for n in npcs.values()}
    hdpt = {fid: skyrimnpc.parse_head_part(s, fid) for _t, _h, s, fid in sfplugin.records(esm, [b"HDPT"])}
    races = {fid: (sfplugin.edid(s), npc_records.race_tints(s)) for _t, _h, s, fid in sfplugin.records(esm, [b"RACE"])}
    out = []
    for name in names:
        n = by_edid.get(name.lower())
        if n is None:
            out.append({"npc": name, "error": "no such NPC"})
            continue
        src, seen = n, set()
        while src.get("template") and src["template_flags"] & skyrimnpc.TEMPLATE_TRAITS and src["template"] in npcs \
                and src["template"] not in seen:
            seen.add(src["template"])
            src = npcs[src["template"]]
        race_edid, tints = races.get(src["race"], ("?", {}))
        parts = []
        for fid in src["head_parts"]:
            p = hdpt.get(fid, {})
            parts.append({"form_id": f"{fid:08X}", "edid": p.get("edid"),
                          "type": skyrimnpc.HEAD_PART_TYPES.get(p.get("type"), p.get("type")), "model": p.get("model")})
        out.append({"npc": n["edid"], "traits_from": src["edid"], "female": n["female"], "race": race_edid,
                    "texture_lighting": src.get("texture_lighting"), "head_parts": parts,
                    "tints": [{"index": t["index"], "mask": tints.get((n["female"], t["index"]), ("", None))[0],
                               "kind": tints.get((n["female"], t["index"]), ("", None))[1], "color": t["color"],
                               "value": t["value"]} for t in src["tints"]]})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--skyrim-data")
    ap.add_argument("--npc", action="append", default=[])
    ap.add_argument("--out", required=True, help="a folder outside the repository")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(a.out, exist_ok=True)
    rep = {"starfield": starfield(os.path.join(a.starfield, "Data", "Starfield.esm"))}
    if a.skyrim_data and a.npc:
        rep["skyrim"] = skyrim(os.path.join(a.skyrim_data, "Skyrim.esm"), a.npc)
    path = os.path.join(a.out, "npc_face_probe.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, default=str)
    sf = rep["starfield"]
    print(f"Starfield human NPCs with a face: {sf['human_npcs_with_face']}; head part types used: "
          f"{sorted(sf['head_parts_used_by_type'])}; EditorIDs mentioning eyes / skin / brows: {len(sf['editor_ids'])}")
    for row in rep.get("skyrim", []):
        print(row.get("npc"), row.get("race"), [p["edid"] for p in row.get("head_parts", [])], row.get("error", ""))
    print("report:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
