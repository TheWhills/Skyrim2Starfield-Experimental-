"""Compare the cells inside worldspaces (read-only): for each world, every CELL record's subrecords (how many of its
cells have each one, with one sample value), the persistent cell's subrecords, and what the cells hold (record types
and GRUP types in their children: temporary, persistent, and any other kind). For finding what a world whose composite
LOD draws keeps per cell that ours does not (compare_worlds.py does the WRLD record itself).

    python -I scripts\\tools\\compare_cells.py --data "<Starfield>\\Data" > C:\\Modding\\work\\cells.txt

It also checks how each world's block / sub-block GRUP labels follow from its cells' coordinates (rules: label
order (y, x) or (x, y), floor or truncating division by 32 / 8): the owner's Creation Kit refused our south-west
corner cells ("Error adding cell ... to world space"), which a wrong label for negative coordinates would explain.

Each world is "<plugin>::<EditorID>"; defaults: NewAtlantis, ShatteredSpace's Dazra, LC030World (composite LOD draws),
LC172World (none), ours.
"""
import argparse
import os
import struct
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402

DEFAULT = ["Starfield.esm::NewAtlantis", "ShatteredSpace.esm::SFBGS001DazraWorld", "Starfield.esm::LC030World",
           "Starfield.esm::LC172World", "SkyrimTerrainTamriel.esm::SKY_Tamriel"]


def show(d: bytes, n=40) -> str:
    return f"[{len(d)}] {d[:n].hex(' ')}{' ...' if len(d) > n else ''}"


LABEL_RULES = {
    # how a block (type 4) / sub-block (type 5) GRUP label is derived from a cell's (x, y): two int16 in the label
    "(y, x) floor": lambda x, y, n: (y // n, x // n),
    "(x, y) floor": lambda x, y, n: (x // n, y // n),
    "(y, x) trunc": lambda x, y, n: (int(y / n), int(x / n)),
    "(x, y) trunc": lambda x, y, n: (int(x / n), int(y / n)),
}


def survey(path, edid):
    out = {"cells": 0, "sigs": Counter(), "sample": {}, "persistent": None, "child_types": Counter(),
           "group_types": Counter(), "cell_flags": Counter(), "labels": Counter(), "label_examples": []}
    with fo4land.Plugin(path) as p:
        _wf, start, end, _f = p.find_world(edid)

        def walk(s, e, depth, block=None, sub=None):
            for item in fo4land.iter_items(p.buf, s, e):
                if item[0] == "GRUP":
                    _g, off, gend, label, gtype = item
                    out["group_types"][gtype] += 1
                    if gtype == 4:
                        walk(off + 24, gend, depth + 1, struct.unpack("<hh", label), None)
                    elif gtype == 5:
                        walk(off + 24, gend, depth + 1, block, struct.unpack("<hh", label))
                    elif gtype in (1, 6):
                        walk(off + 24, gend, depth + 1, block, sub)
                    else:                                # cell children (8 persistent, 9 temporary, others)
                        for sub in fo4land.iter_items(p.buf, off + 24, gend):
                            k = f"GRUP {sub[4]}" if sub[0] == "GRUP" else sub[0].decode("latin-1")
                            out["child_types"][f"in GRUP {gtype}: {k}"] += 1
                    continue
                typ, off, flags, _fid = item
                if typ != b"CELL":
                    out["child_types"][f"world level: {typ.decode('latin-1')}"] += 1
                    continue
                fields = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
                sigs = {s.decode("latin-1") for s, _d in fields}
                if b"XCLC" not in {s for s, _d in fields}:
                    out["persistent"] = [(s.decode("latin-1"), bytes(d)) for s, d in fields]
                    out["persistent_flags"] = flags
                    continue
                out["cells"] += 1
                out["cell_flags"][f"0x{flags:08X}"] += 1
                x, y = struct.unpack("<ii", dict(fields)[b"XCLC"][:8])
                if block is not None and sub is not None and abs(x) < 10000 and abs(y) < 10000:
                    for name, rule in LABEL_RULES.items():
                        if rule(x, y, 32) == block and rule(x, y, 8) == sub:
                            out["labels"][name] += 1
                    if len(out["label_examples"]) < 6 and (x < 0 or y < 0):
                        out["label_examples"].append(((x, y), block, sub))
                for s, d in fields:
                    k = s.decode("latin-1")
                    out["sample"].setdefault(k, bytes(d))
                out["sigs"].update(sigs)
        walk(start, end, 0)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("worlds", nargs="*", default=DEFAULT)
    a = ap.parse_args(argv)
    res = {}
    for w in a.worlds:
        plugin, edid = w.split("::")
        try:
            res[w] = survey(os.path.join(a.data, plugin), edid)
        except (OSError, KeyError) as e:
            print(f"{w}: {e}")
    for w, r in res.items():
        print(f"== {w}: {r['cells']} exterior cells; record flags {dict(r['cell_flags'])}")
        print(f"   GRUP types: {dict(sorted(r['group_types'].items()))}")
        for k, n in sorted(r["child_types"].items()):
            print(f"   {n:8,}  {k}")
        print(f"   block / sub-block labels matching each rule: {dict(r['labels'])} of {r['cells']} cells")
        for xy, b, sb in r["label_examples"]:
            print(f"      cell {xy}: block label {b}, sub-block label {sb}")
        print(f"   persistent cell (flags 0x{r.get('persistent_flags', 0):08X}):")
        for s, d in r["persistent"] or []:
            print(f"      {s} {show(d)}")
    sigs = sorted({s for r in res.values() for s in r["sigs"]})
    print("\nexterior cell subrecords: share of cells that have it, and a sample")
    for s in sigs:
        print(s)
        for w, r in res.items():
            n = r["sigs"].get(s, 0)
            frac = f"{n / r['cells']:.0%}" if r["cells"] else "-"
            print(f"    {w}: {frac}" + (f"  e.g. {show(r['sample'][s])}" if n else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
