"""Which converted object is this? Looks a reference of the installed exterior up by the FormID the console shows
(click it with the console open) or lists the objects near a spot (player.getpos x / y / z in the console, metres).

    python -I scripts\\terrain\\which_ref.py --staging C:\\Modding\\staging\\skyrim_all --ref 0A01B2C3
    python -I scripts\\terrain\\which_ref.py --staging C:\\Modding\\staging\\skyrim_all --near 1234.5 -567.8 --radius 6

Prints, per object: its FormID in the terrain plugin, the Skyrim reference it came from, the base (converted model
and the Skyrim NIF), position (metres, Starfield frame), distance and scale. For hunting invisible collision (owner,
2026-11-08: a hump in Riverwood's road the player climbs over and NPCs get stuck on), stand on it and use --near.
"""
import argparse
import json
import math
import os
import sys


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def describe(r, bases, fid_of, dist=None):
    b = bases[r["base"]] if isinstance(r.get("base"), int) and 0 <= r["base"] < len(bases) else {}
    x, y, z = r["pos"]
    return (f"{fid_of.get(r['src'], '??????'):>8}  {r['src']:<22} {b.get('edid', '?'):<34} "
            f"pos {x:9.2f} {y:9.2f} {z:8.2f}" + (f"  dist {dist:6.2f}" if dist is not None else "")
            + f"  scale {r.get('scale', 1)}  collision {b.get('collision', '?')}  {b.get('source', b.get('model', ''))}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", required=True, help="the staged exterior (objects.json, formids.json)")
    ap.add_argument("--ref", action="append", default=[], help="console FormID (load-order byte ignored)")
    ap.add_argument("--near", type=float, nargs=2, metavar=("X", "Y"), help="console position, metres")
    ap.add_argument("--radius", type=float, default=5.0, help="--near: metres (default 5)")
    ap.add_argument("--closest", type=int, default=10, help="--near: also list this many closest objects")
    a = ap.parse_args(argv)
    objs = load(os.path.join(a.staging, "objects.json"))
    ids = load(os.path.join(a.staging, "formids.json"))
    fid_of = {src: fid.upper() for src, fid in ids.get("refs", {}).items()}
    src_of = {int(fid, 16) & 0xFFFFFF: src for src, fid in fid_of.items()}
    bases, refs = objs["bases"], objs["refs"]
    by_src = {r["src"]: r for r in refs}
    found = 0
    for f in a.ref:
        v = int(f, 16)
        if v >> 24 == 0xFF:
            print(f"{f}: a runtime reference (spawned in game, e.g. by placeatme), not one of the exterior's")
            continue
        src = src_of.get(v & 0xFFFFFF)
        if src is None or src not in by_src:
            print(f"{f}: not a reference of {ids.get('plugin', 'the terrain plugin')} (another plugin's, or a base)")
            continue
        print(describe(by_src[src], bases, fid_of))
        found += 1
    if a.near:
        x, y = a.near
        dist = sorted(((math.hypot(r["pos"][0] - x, r["pos"][1] - y), i) for i, r in enumerate(refs)))
        near = [(d, refs[i]) for d, i in dist if d <= a.radius]
        print(f"{len(near)} objects within {a.radius} m of {x}, {y}:")
        for d, r in near:
            print(describe(r, bases, fid_of, d))
        if len(near) < a.closest:
            print(f"the {a.closest} closest of all {len(refs):,} objects:")
            for d, i in dist[:a.closest]:
                print(describe(refs[i], bases, fid_of, d))
        found += len(near)
    return 0 if found or not (a.ref or a.near) else 1


if __name__ == "__main__":
    sys.exit(main())
