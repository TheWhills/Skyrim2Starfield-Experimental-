"""Check the Skyrim -> Starfield bone table (src/fo4sf/skeletonmap.py) against two real skeleton NIFs: coverage (every
name exists, every bone is accounted for), and per mapped pair the rest-pose world positions (metres), their distance,
and the segment length ratio Starfield / Skyrim (parent joint -> joint), which the retargeter uses to rescale.

    python -I scripts\\armor\\bone_map_report.py --skyrim "<BodySlide>\\res\\skeleton_male_sse.nif" ^
        --starfield "<BodySlide>\\res\\skeleton_male_sf.nif" [--json C:\\Modding\\work\\bone_map.json]

Either skeleton may come from the games themselves (Skyrim: meshes\\actors\\character\\character assets\\skeleton.nif;
Starfield: meshes\\actors\\human\\characterassets\\skeleton.nif). Read-only; the JSON (optional) is the table plus the
measurements, written outside the repository.
"""
import argparse
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import nif, skeletonmap as M  # noqa: E402

SKYRIM_M_PER_UNIT = 0.0142875                     # Skyrim game unit = 1/70 m (Bethesda's 1 unit = 1.428 cm)
NODE_TYPES = ("NiNode", "BSFadeNode", "BSLeafAnimNode")


def joints(path: str, scale: float):
    """{name: (world position in metres, parent name)} of every node in a skeleton NIF."""
    f = nif.parse(open(path, "rb").read())
    world = nif.world_transforms(f)
    nodes = [i for i in range(len(f.blocks)) if f.type_of(i) in NODE_TYPES]

    def name(i):
        si, = struct.unpack_from("<i", f.blocks[i], 0)
        return f.strings[si].decode("latin-1") if 0 <= si < len(f.strings) else ""
    parent = {}
    for i in nodes:
        for c in nif.node_children(f, i):
            parent[c] = i
    out = {}
    for i in nodes:
        t = world(i)[0]
        out[name(i)] = (tuple(v * scale for v in t), name(parent[i]) if i in parent else None)
    return out


def measure(sk: dict, sf: dict):
    rows = []
    for a, b in sorted(M.MAP.items(), key=lambda kv: kv[1]):
        if a not in sk or b not in sf:
            rows.append({"skyrim": a, "starfield": b, "missing": a not in sk and "skyrim" or "starfield"})
            continue
        pa, pb = sk[a][0], sf[b][0]
        row = {"skyrim": a, "starfield": b, "skyrim_m": [round(v, 3) for v in pa],
               "starfield_m": [round(v, 3) for v in pb], "distance_m": round(math.dist(pa, pb), 3)}
        sp, fp = sk[a][1], sf[b][1]
        if sp in sk and fp in sf:
            ls, lf = math.dist(sk[sp][0], pa), math.dist(sf[fp][0], pb)
            if ls > 1e-4 and lf > 1e-4:
                row["length_ratio"] = round(lf / ls, 3)
        rows.append(row)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim skeleton NIF (game units)")
    ap.add_argument("--starfield", required=True, help="Starfield human skeleton NIF (metres)")
    ap.add_argument("--json", help="write the table + measurements here")
    a = ap.parse_args(argv)
    sk = joints(a.skyrim, SKYRIM_M_PER_UNIT)
    sf = joints(a.starfield, 1.0)
    cov = M.coverage(list(sk), list(sf))
    # a Skyrim NIF skeleton carries many more nodes than the 99 animated bones (XPMSE-style extras): only names the
    # table uses are expected to resolve
    cov["skyrim_missing_from_table"] = f"{len(cov['skyrim_missing_from_table'])} NIF-only nodes (not animated bones)"
    rows = measure(sk, sf)
    print(f"Skyrim {len(sk)} nodes, Starfield {len(sf)} nodes; table: {len(M.MAP)} mapped, {len(M.SPLIT)} split, "
          f"{len(M.DERIVED)} derived, {len(M.WORLD)} world-solved, {len(M.REST)} rest, {len(M.UNMAPPED)} unmapped")
    print(f"coverage: {json.dumps(cov)}")
    print(f"{'Starfield':18} {'Skyrim':30} {'dist m':>7} {'len x':>6}   Skyrim m -> Starfield m")
    for r in rows:
        if "missing" in r:
            print(f"{r['starfield']:18} {r['skyrim']:30} missing in {r['missing']}")
            continue
        print(f"{r['starfield']:18} {r['skyrim']:30} {r['distance_m']:7.3f} {r.get('length_ratio', ''):>6}   "
              f"{r['skyrim_m']} -> {r['starfield_m']}")
    d = sorted(r["distance_m"] for r in rows if "distance_m" in r)
    if d:
        print(f"rest-pose distance: median {d[len(d) // 2]:.3f} m, max {d[-1]:.3f} m")
    if a.json:
        out = {"map": M.MAP, "split": M.SPLIT, "derived": M.DERIVED, "world": M.WORLD, "rest": list(M.REST),
               "unmapped": M.UNMAPPED, "coverage": cov, "measurements": rows}
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        print(f"wrote {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
