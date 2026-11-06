"""Which records of Starfield.esm name a clothing morph (2026-11-06: our morph.dat files are not applied; a Nexus
article on Starfield's mesh layout says morph files are "referenced in esm files"). Searches every record's
subrecords for a text (default: the vanilla nightwear's morph folder name, outfit_nightwear_01_m) and prints, per hit,
the record type, EditorID, FormID, the subrecord and its text, and the full subrecord list of each record found.
Writes morph_ref_probe.json into --out.

    python -I scripts\\armor\\morph_ref_probe.py --starfield "D:\\...\\Starfield" --out "C:\\Modding\\work\\morph_ref"
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land, sfplugin  # noqa: E402


def text(d: bytes) -> str:
    runs = [r.decode("latin-1") for r in re.findall(rb"[ -~]{4,}", bytes(d))]
    return " | ".join(runs) if runs else bytes(d)[:24].hex()


def search(esm: str, needles, limit: int = 40):
    """[(type, edid, fid, sig, text, all subrecord tags)] of records whose subrecords contain a needle (lower case)."""
    nd = [n.lower().encode("latin-1") for n in needles]
    hits = []
    with fo4land.Plugin(esm) as p:
        def walk(start, end):
            for it in fo4land.iter_items(p.buf, start, end):
                if it[0] == "GRUP":
                    walk(it[1] + 24, it[2])
                    continue
                typ, off, _fl, fid = it
                data = bytes(fo4land.record_data(p.buf, off))
                low = data.lower()
                if not any(n in low for n in nd):
                    continue
                subs = [(s, bytes(d)) for s, d in fo4land.iter_subrecords(data)]
                for s, d in subs:
                    if any(n in d.lower() for n in nd):
                        hits.append({"type": typ.decode("latin-1") if isinstance(typ, bytes) else str(typ),
                                     "edid": sfplugin.edid(subs), "form": f"{fid:08X}",
                                     "field": s.decode("latin-1"), "text": text(d),
                                     "fields": [(x.decode("latin-1"), text(y)[:80]) for x, y in subs]})
                if len(hits) >= limit:
                    return
        walk(p.body, len(p.buf))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--text", action="append", default=[], help="text to look for (default: outfit_nightwear_01_m)")
    a = ap.parse_args(argv)
    hits = search(os.path.join(a.starfield, "Data", "Starfield.esm"), a.text or ["outfit_nightwear_01_m"])
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "morph_ref_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(hits, fh, indent=1)
    for h in hits:
        print(f"{h['type']} {h['form']} {h['edid']}: {h['field']} = {h['text']}")
    seen = set()
    for h in hits:
        if h["form"] in seen:
            continue
        seen.add(h["form"])
        print(f"fields of {h['type']} {h['edid']}:", " ".join(f for f, _t in h["fields"]))
    print(f"{len(hits)} hits; wrote", os.path.join(a.out, "morph_ref_probe.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
