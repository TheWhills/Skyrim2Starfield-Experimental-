"""Find Starfield's placeable water (read-only): every base record (outside worlds / cells / dialogue) that names a WATR
record in one of its subrecords, and, with --refs, how often vanilla worlds place each one and where.

Why: at Jemison's ocean spot our cell water (rivers, lakes) does not draw (owner, 2026-10-17); flat coloured statics
are only a stand-in. Skyrim and Fallout 4 place water as objects (activators with a water type); if Starfield has
such objects, our rivers can be real water at any spot.

    python -I scripts\\tools\\find_water_objects.py --esm "<Starfield>\\Data\\Starfield.esm" [--refs] > C:\\Modding\\work\\water_objects.txt
"""
import argparse
import os
import struct
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402

SKIP = (b"WRLD", b"CELL", b"DIAL", b"QUST", b"INFO", b"NAVM", b"NAVI", b"LAND")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esm", required=True)
    ap.add_argument("--refs", action="store_true", help="also count vanilla placements (walks every world; slow)")
    a = ap.parse_args(argv)
    with fo4land.Plugin(a.esm) as p:
        waters = {}
        rng = p.top_group(b"WATR")
        for typ, off, _fl, fid in fo4land.iter_items(p.buf, *rng):
            if typ != "GRUP":
                waters[fid] = next((fo4land.zstring(d) for s, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off))
                                    if s == b"EDID"), "")
        print(f"{len(waters)} WATR records, e.g. {list(waters.values())[:8]}")
        hits = []
        for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if item[0] != "GRUP" or item[3] in SKIP or item[3] == b"WATR":
                continue
            for typ, off, _fl, fid in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                if typ == "GRUP":
                    continue
                edid, model, found = "", "", []
                for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                    if sig == b"EDID":
                        edid = fo4land.zstring(d)
                    elif sig == b"MODL":
                        model = fo4land.zstring(d)
                    for i in range(0, len(d) - 3, 4):
                        v = struct.unpack_from("<I", d, i)[0]
                        if v in waters:
                            found.append((sig.decode("latin-1"), i, waters[v]))
                if found:
                    hits.append((typ.decode("latin-1"), fid, edid, model, found))
        by_type = Counter(h[0] for h in hits)
        print(f"{len(hits)} base records name a WATR: {dict(by_type)}")
        for typ, fid, edid, model, found in hits:
            print(f"  {typ} {fid:08X} {edid:40s} model={model!r} -> " +
                  ", ".join(f"{s}@{i}:{w}" for s, i, w in found[:4]))
        if not a.refs:
            return 0
        bases = {h[1]: h for h in hits}
        placed = Counter()
        where = defaultdict(Counter)
        rng = p.top_group(b"WRLD")
        world = ""

        def walk(s, e):
            nonlocal world
            for it in fo4land.iter_items(p.buf, s, e):
                if it[0] == "GRUP":
                    walk(it[1] + 24, it[2])
                    continue
                typ, off, _fl, _fid = it
                if typ == b"WRLD":
                    world = next((fo4land.zstring(d) for sg, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off))
                                  if sg == b"EDID"), "")
                elif typ == b"REFR":
                    for sg, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                        if sg == b"NAME":
                            b = struct.unpack_from("<I", d)[0]
                            if b in bases:
                                placed[b] += 1
                                where[b][world] += 1
                            break
        walk(*rng)
        print("\nvanilla placements in worlds:")
        for b, n in placed.most_common():
            print(f"  {bases[b][2]:40s} {n:6d}  worlds: {dict(where[b].most_common(5))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
