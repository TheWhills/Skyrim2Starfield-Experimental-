"""Which Starfield ground textures (LTEX) vanilla terrain really uses (read-only).

Reads the LTEX table of every BTD in Starfield's terrain archives (Terrain01..04, TerrainPatch: stored uncompressed,
so only each file's header is read) and counts, per LTEX, how many BTDs list it and how often it is the table's
first entry. Joins EditorIDs from Starfield.esm and prints each LTEX record's subrecords (to see what it points to).
With --mapping (a build's ltex_mapping.json) it also shows how often the current picks appear in vanilla terrain:
a pick no vanilla BTD uses is a likely cause of wrong-looking ground (owner's first --land-textures test: pale pink
ground everywhere).

    python -I scripts\\terrain\\survey_ltex.py --sf-data "<Starfield>\\Data" ^
        --mapping C:\\Modding\\staging\\skyrim_tamriel\\ltex_mapping.json --out C:\\Modding\\work\\ltex_survey.json
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land, landtex  # noqa: E402

def ltex_records(sf_esm):
    """{form id: {"edid", "fields": {sig: short text or hex}}} of every Starfield.esm LTEX."""
    out = {}
    with fo4land.Plugin(sf_esm) as p:
        for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if item[0] != "GRUP" or item[3] != b"LTEX":
                continue
            for typ, off, _fl, fid in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                if typ == "GRUP":
                    continue
                rec = {"edid": "", "fields": {}}
                for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                    s = sig.decode("ascii", "replace")
                    if s == "EDID":
                        rec["edid"] = fo4land.zstring(d)
                        continue
                    txt = d.rstrip(b"\0")
                    printable = txt and all(32 <= c < 127 for c in txt)
                    val = txt.decode("ascii") if printable else d[:16].hex() + ("..." if len(d) > 16 else "")
                    rec["fields"][s] = val if s not in rec["fields"] else rec["fields"][s] + " | " + val
                out[fid] = rec
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True, help="Starfield Data folder")
    ap.add_argument("--mapping", help="a build's ltex_mapping.json: compare its picks")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--out", help="write everything as JSON here (outside the repository)")
    a = ap.parse_args(argv)
    listed, first, btds, skipped = landtex.vanilla_usage(a.sf_data)
    recs = ltex_records(os.path.join(a.sf_data, "Starfield.esm"))
    print(f"{btds} vanilla BTDs read ({skipped} skipped: compressed / not readable), {len(listed)} LTEX used, "
          f"{len(recs)} LTEX records in Starfield.esm\n")
    print(f"{'BTDs':>5} {'first':>5}  FormID    EditorID")
    for fid, n in listed.most_common(a.top):
        print(f"{n:>5} {first[fid]:>5}  {fid:08X}  {recs.get(fid, {}).get('edid', '?')}")
    unused = sorted(r["edid"] for f, r in recs.items() if f not in listed)
    print(f"\n{len(unused)} LTEX records no vanilla BTD uses, e.g.: {', '.join(unused[:25])}")
    picks = {}
    if a.mapping:
        with open(a.mapping, encoding="utf-8") as f:
            m = json.load(f)
        by_edid = {r["edid"]: f for f, r in recs.items()}
        print("\ncurrent picks (category -> Starfield LTEX: vanilla BTDs using it):")
        for cat, v in m.get("categories", {}).items():
            fid = by_edid.get(v.get("edid"))
            picks[cat] = {"edid": v.get("edid"), "btds": listed.get(fid, 0) if fid else None}
            print(f"  {cat:8} -> {v.get('edid')}: {picks[cat]['btds']}")
        print("coverage of the Skyrim map: " + ", ".join(f"{k} {v:.0%}" for k, v in list(m.get("coverage", {}).items())[:12]))
    print("\nLTEX record fields (top 15):")
    for fid, _n in listed.most_common(15):
        r = recs.get(fid)
        if r:
            print(f"  {r['edid']}: " + "; ".join(f"{k}={v}" for k, v in r["fields"].items()))
    if a.out:
        doc = {"btds": btds, "used": [{"form_id": "%08X" % f, "edid": recs.get(f, {}).get("edid"), "btds": n,
                                       "first": first[f], "fields": recs.get(f, {}).get("fields")}
                                      for f, n in listed.most_common()],
               "unused": unused, "picks": picks}
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1)
        print(f"\n-> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
