"""Compare worldspace records field by field, raw (read-only): every subrecord of each WRLD, including ones Mutagen does
not name, plus the record's flags and its plugin's header flags. For finding what worlds whose composite LOD draws
(NewAtlantis, ShatteredSpace's SFBGS001DazraWorld) have that ours (SKY_Tamriel) lacks.

    python -I scripts\\tools\\compare_worlds.py --data "<Starfield>\\Data" > C:\\Modding\\work\\worlds.txt

Each world is "<plugin>::<EditorID>"; the defaults are the LOD worlds above, the Mars template LC172World (no LOD) and
ours. Fields whose bytes are the same in every world are listed once at the end.
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402

DEFAULT = ["Starfield.esm::NewAtlantis", "ShatteredSpace.esm::SFBGS001DazraWorld",
           "Starfield.esm::LC172World", "SkyrimTerrainTamriel.esm::SKY_Tamriel"]
LOD_WORLDS = 2                       # the first two of DEFAULT have composite LOD that draws (SettleGagarinWorld is not
                                     # that world's EditorID in Starfield.esm: owner's run)


def world_record(path, edid):
    """(record flags, form id, [(sig, bytes)], plugin header flags, child group types {type: count})."""
    with fo4land.Plugin(path) as p:
        _t, _s, hflags, _f = struct.unpack_from("<4sIII", p.buf, 0)
        rng = p.top_group(b"WRLD")
        if rng is None:
            raise KeyError(f"{path}: no WRLD group")
        found = None
        for item in fo4land.iter_items(p.buf, *rng):
            if item[0] == "GRUP":
                if found and item[4] == 1 and struct.unpack("<I", item[3])[0] == found[1]:
                    kids = {}
                    for sub in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                        k = f"GRUP type {sub[4]}" if sub[0] == "GRUP" else sub[0].decode("latin-1")
                        kids[k] = kids.get(k, 0) + 1
                    found = found[:4] + (kids,)
                    break
                continue
            typ, off, flags, fid = item
            if typ != b"WRLD":
                continue
            fields = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
            if next((fo4land.zstring(d) for s, d in fields if s == b"EDID"), "") == edid:
                found = (flags, fid, fields, hflags, {})
        if found is None:
            raise KeyError(f"{edid} not in {path}")
        return found


def show(d: bytes, n=48) -> str:
    h = d[:n].hex(" ")
    return f"[{len(d)}] {h}{' ...' if len(d) > n else ''}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="Starfield Data folder")
    ap.add_argument("worlds", nargs="*", default=DEFAULT)
    a = ap.parse_args(argv)
    recs = {}
    for w in a.worlds:
        plugin, edid = w.split("::")
        try:
            recs[w] = world_record(os.path.join(a.data, plugin), edid)
        except (OSError, KeyError) as e:
            print(f"{w}: {e}")
    names = list(recs)
    print("world | record flags | form id | plugin header flags | child groups")
    for w in names:
        fl, fid, _f, hf, kids = recs[w]
        print(f"  {w}: 0x{fl:08X} | {fid:08X} | 0x{hf:08X} | {kids}")
    per = {}                                          # sig -> {world: [bytes, ...]} (repeats in order)
    order = []
    for w in names:
        for sig, d in recs[w][2]:
            s = sig.decode("latin-1")
            if s not in per:
                per[s] = {}
                order.append(s)
            per[s].setdefault(w, []).append(bytes(d))
    same = []
    print("\nfields that differ (LOD worlds first):")
    for s in order:
        vals = [tuple(per[s].get(w, [])) for w in names]
        if len(set(vals)) == 1:
            same.append(s)
            continue
        lod_has = all(per[s].get(w) for w in names[:LOD_WORLDS]) if len(names) >= LOD_WORLDS else False
        tag = "  <- every LOD world has it" if lod_has and not per[s].get(names[-1]) else ""
        print(f"{s}{tag}")
        for w in names:
            v = per[s].get(w)
            if not v:
                print(f"    {w}: -")
            for i, d in enumerate(v or []):
                print(f"    {w}{f' #{i}' if len(v) > 1 else ''}: {show(d)}")
    print(f"\nthe same in every world: {', '.join(same) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
