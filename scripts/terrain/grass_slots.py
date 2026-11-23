"""Every ground-cover slot of the native-grass build with the vanilla Starfield record it re-skins (read-only).

2026-11-23 (owner's ground_at at the Riverwood forest spot): our terrain draws Skyrim's LFieldGrass02 there with slot
00030137 at full strength (alpha 7/7), the field-grass cover is on that slot, and still nothing grows; grass does grow
on rock and cliff edges. The terrain re-skins spare vanilla LTEX records and keeps their own fields (material type,
friction, ...); 00030137 is the vanilla rock texture LRockLayered05. Supported hypothesis: the ground cover follows
the vanilla record's kind (no ground cover on rock-type ground). This lists, per slot with a ground cover in
grass_native.json: the Skyrim texture, the vanilla record, every subrecord of that record in Starfield.esm except
EDID / BNAM, and the grasses, so slots that grow can be compared with slots that do not.

    python -I scripts\\terrain\\grass_slots.py --terrain C:\\Modding\\staging\\skyrim_all ^
        --grass "<MO2 mods>\\S2S Grass Native" --sf-esm "<Starfield>\\Data\\Starfield.esm"
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)


def rows(overrides, slots, recs):
    """[(slot fid, Skyrim EDID, vanilla EDID, {sig: value} without EDID / BNAM, [grass EDIDs])] for every slot with
    ground cover, in slot order. overrides: overlays_params ltex_overrides; slots: grass_native.json "slots";
    recs: survey_ltex.ltex_records."""
    sky = {int(o["form_id"]): o for o in overrides or ()}
    out = []
    for key in sorted(slots or {}):
        fid = int(key, 16)
        o = sky.get(fid, {})
        r = recs.get(fid, {})
        fields = {k: v for k, v in (r.get("fields") or {}).items() if k not in ("EDID", "BNAM")}
        out.append((fid, o.get("skyrim", "?"), r.get("edid") or o.get("vanilla_edid", "?"), fields, list(slots[key])))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--terrain", required=True, help="the staged exterior (overlays_params.json)")
    ap.add_argument("--grass", required=True, help="the native-grass mod folder (grass_native.json)")
    ap.add_argument("--sf-esm", required=True, help="Starfield.esm")
    a = ap.parse_args(argv)
    import survey_ltex
    with open(os.path.join(a.terrain, "overlays_params.json"), encoding="utf-8") as f:
        prm = json.load(f)
    with open(os.path.join(a.grass, "grass_native.json"), encoding="utf-8") as f:
        rep = json.load(f)
    recs = survey_ltex.ltex_records(a.sf_esm)
    table = rows(prm.get("ltex_overrides") or [], rep.get("slots") or {}, recs)
    keys = sorted({k for _f, _s, _v, flds, _g in table for k in flds})
    print(f"{len(table)} slots with ground cover; vanilla LTEX fields compared: {', '.join(keys)}")
    for fid, sky, van, flds, grasses in table:
        print(f"{fid:08X}  Skyrim {sky:<24} re-skins {van:<28} grows {', '.join(grasses)}")
        print("          " + "  ".join(f"{k}={flds.get(k, '-')}" for k in keys))
    return 0


if __name__ == "__main__":
    sys.exit(main())
