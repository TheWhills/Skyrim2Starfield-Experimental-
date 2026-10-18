"""Survey a vanilla world's landing and map markers (read-only), to give the Skyrim overlay the same: every reference in
the world whose base EditorID matches --base (default: landing / map markers) or that carries map-marker data (XMRK),
with its base (type, EditorID), cell, position and every subrecord (hex preview, text when readable). Also lists the
world's location chain: the WRLD's XLCN location and, per location, its EditorID, parent (PNAM) and keywords.

    python -I scripts\\tools\\survey_markers.py --esm "<Starfield>\\Data\\Starfield.esm" --world NewAtlantis > C:\\Modding\\work\\markers.txt

Why: to land on the Skyrim overlay from orbit and see it on the planet map (owner, 2026-10-18), it needs what New
Atlantis has: a ship landing marker, a map marker, and locations under the planet's own (Nirn has none yet).
"""
import argparse
import os
import re
import struct
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402


def text_of(d: bytes):
    s = d.rstrip(b"\0")
    return s.decode("latin-1") if len(s) >= 3 and all(32 <= c < 127 for c in s) else None


def show(subs, n=72):
    for s, d in subs:
        d = bytes(d)
        t = text_of(d)
        print(f"      {s.decode('latin-1')} [{len(d)}] {d[:n].hex(' ')}{' ...' if len(d) > n else ''}"
              + (f"   '{t}'" if t else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esm", required=True)
    ap.add_argument("--world", default="NewAtlantis")
    ap.add_argument("--base", default=r"landing|mapmarker|shipmarker|landingzone",
                    help="regex on the base EditorID")
    ap.add_argument("--limit", type=int, default=40, help="most matches printed in full")
    a = ap.parse_args(argv)
    rx = re.compile(a.base, re.I)
    with fo4land.Plugin(a.esm) as p:
        wfid, start, end, wfields = p.find_world(a.world)
        refs = []                                       # (offset, fid, cell xy, subrecords)

        def walk(s, e, cell):
            for it in fo4land.iter_items(p.buf, s, e):
                if it[0] == "GRUP":
                    walk(it[1] + 24, it[2], cell)
                    continue
                typ, off, _fl, fid = it
                if typ == b"CELL":
                    xy = None
                    for sg, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                        if sg == b"XCLC":
                            xy = struct.unpack_from("<ii", d)
                    cell = xy if xy else "persistent"
                elif typ == b"REFR":
                    subs = [(sg, bytes(d)) for sg, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off))]
                    refs.append((fid, cell, subs))
        walk(start, end, None)
        bases = {struct.unpack_from("<I", d)[0] for _f, _c, subs in refs for s, d in subs if s == b"NAME"}
        info = p.base_records(wanted=bases)
        print(f"{a.world} ({wfid:08X}): {len(refs):,} references, {len(bases):,} bases")
        xlcn = next((struct.unpack_from("<I", d)[0] for s, d in wfields if s == b"XLCN"), None)
        hits, kinds = [], Counter()
        for fid, cell, subs in refs:
            d = dict(subs)
            base = struct.unpack_from("<I", d[b"NAME"])[0] if b"NAME" in d else None
            typ, bedid, _ob = info.get(base, ("?", "?", None))
            if rx.search(bedid) or b"XMRK" in d:
                hits.append((fid, cell, base, typ, bedid, subs))
                kinds[f"{typ} {bedid}"] += 1
        print(f"{len(hits)} marker references; by base: {dict(kinds.most_common())}")
        for fid, cell, base, typ, bedid, subs in hits[:a.limit]:
            pos = struct.unpack_from("<3f", dict(subs)[b"DATA"]) if b"DATA" in dict(subs) else None
            print(f"  REFR {fid:08X} in cell {cell}, base {typ} {base:08X} {bedid}, pos "
                  f"{tuple(round(v, 1) for v in pos) if pos else None}")
            show(subs)
        # the location chain
        print(f"\nworld location XLCN: {xlcn:08X}" if xlcn else "\nworld has no XLCN")
        rng = p.top_group(b"LCTN")
        locs = {}
        if rng:
            for typ, off, _fl, fid in fo4land.iter_items(p.buf, *rng):
                if typ == "GRUP":
                    continue
                locs[fid] = [(sg, bytes(d)) for sg, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off))]
        cur, seen = xlcn, set()
        while cur and cur in locs and cur not in seen:
            seen.add(cur)
            subs = locs[cur]
            d = dict(subs)
            edid = fo4land.zstring(d.get(b"EDID", b""))
            print(f"  LCTN {cur:08X} {edid}")
            show(subs, 48)
            cur = struct.unpack_from("<I", d[b"PNAM"])[0] if b"PNAM" in d and len(d[b"PNAM"]) >= 4 else None
    return 0


if __name__ == "__main__":
    sys.exit(main())
