"""S4 helper: estimate Fallout 4 units per Starfield metre from comparable vanilla furniture.

Compares the median height (Z extent) of same-category props: Fallout 4 in game units, Starfield in metres
(from the BSGeometry bounding boxes). Categories are human-scale furniture so the real-world size is similar.
usage: calibrate_units.py <repo/src> <repo/scripts> <FO4 Meshes.ba2> <Starfield Meshes01.ba2>
"""
import os
import statistics
import sys

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import recon  # noqa: E402
from fo4sf import nif, sfnif  # noqa: E402

KEYS = ["chair", "stool", "couch", "sofa", "bed", "toilet", "sink", "desk", "locker", "fridge", "barrel", "crate"]


def names(ba2, key):
    return [i for i, n in enumerate(ba2["names"]) if n.lower().endswith(".nif") and key in n.lower()
            and ("setdressing" in n.lower() or "furniture" in n.lower()) and "_lod" not in n.lower()]


def fo4_height(raw):
    shapes = [s for s in nif.fo4_trishapes(nif.parse(raw)) if s.positions and not s.skinned]
    if not shapes:
        return None
    zs = [p[2] for s in shapes for p in s.positions]
    return max(zs) - min(zs)


def sf_height(raw):
    n = nif.parse(raw)
    lo, hi = None, None
    for k, b in enumerate(n.blocks):
        if n.type_of(k) == "BSGeometry":
            g = sfnif.parse_bsgeometry(b)
            z0, z1 = g.box[2] - g.box[5], g.box[2] + g.box[5]
            lo, hi = (z0 if lo is None else min(lo, z0)), (z1 if hi is None else max(hi, z1))
    return None if lo is None else hi - lo


fo4 = recon.read_ba2(sys.argv[3])
sf = recon.read_ba2(sys.argv[4])
rows = []
for key in KEYS:
    a, b = [], []
    for i in names(fo4, key)[:120]:
        try:
            h = fo4_height(recon.extract_gnrl(fo4, i))
        except Exception:
            continue
        if h and h > 1:
            a.append(h)
    for i in names(sf, key)[:120]:
        try:
            h = sf_height(recon.extract_gnrl(sf, i))
        except Exception:
            continue
        if h and h > 0.05:
            b.append(h)
    if len(a) >= 5 and len(b) >= 5:
        ma, mb = statistics.median(a), statistics.median(b)
        rows.append((key, len(a), ma, len(b), mb, ma / mb))
        print(f"{key:8s} FO4 n={len(a):3d} median {ma:6.1f} units | SF n={len(b):3d} median {mb:5.2f} m | {ma / mb:5.1f} units/m")
if rows:
    ratios = [r[5] for r in rows]
    print(f"\nmedian units per metre across categories: {statistics.median(ratios):.1f}  (range {min(ratios):.1f}-{max(ratios):.1f}); "
          f"current assumption: 70.0")
