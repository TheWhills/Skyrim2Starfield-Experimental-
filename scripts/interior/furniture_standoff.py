"""Where furniture markers stand relative to the object in front of them (the bar counter for a bartender), measured on
the game's own placements, so ours can be shifted to match (owner 2026-11-08: Orgnar with Starfield's bartender
furniture "not quite on the bar, closer tho"). Read-only; works on Skyrim.esm and Starfield.esm.

    python -I scripts\\interior\\furniture_standoff.py --esm "$sf\\Data\\Starfield.esm" --base NPCBartender_Standing ^
        --base NPCLeaningBartopFront --out C:\\Modding\\work\\furniture\\standoff_sf.json
    python -I scripts\\interior\\furniture_standoff.py --esm "$sky\\Skyrim.esm" --base CounterBarLeanMarker ^
        --base CounterLeanMarker --units 70 --out C:\\Modding\\work\\furniture\\standoff_sky.json

For every reference of each --base: the references within --radius in its cell; for each, its base's object bounds
(OBND: Starfield 6 floats in metres, Skyrim 6 int16 in units; xEdit wbObjectBounds) as a box turned by the reference's
z rotation and scaled; the marker's facing ray (Bethesda z rotation turns clockwise seen from above: forward = (sin z,
cos z)) is cast against each box whose height covers 0.6..1.4 m above the marker. Reports the first box hit: its base,
the distance from the marker to the box's face along the facing (standoff), the box top above the marker (top), and
how far the hit is off the box centre sideways. References turned about x / y (more than 0.1 rad) are skipped.
Prints the median standoff and top per --base.
"""
import argparse
import json
import math
import os
import statistics
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land, packages  # noqa: E402

BAND = (0.6, 1.4)          # m above the marker: a counter / desk / rail at hand height


def ref_data(ix, fid):
    base = pos = None
    scale = 1.0
    for s, d in fo4land.iter_subrecords(fo4land.record_data(ix.p.buf, ix.records[fid][1])):
        if s == b"NAME" and len(d) == 4:
            base = struct.unpack_from("<I", d)[0]
        elif s == b"DATA" and len(d) >= 24:
            pos = struct.unpack_from("<6f", d)
        elif s == b"XSCL" and len(d) == 4:
            scale = struct.unpack_from("<f", d)[0]
    return base, pos, scale


def bounds(ix, fid, cache, starfield):
    if fid not in cache:
        cache[fid] = None
        for s, d in ix.subs(fid):
            if s == b"OBND":
                if starfield and len(d) >= 24:
                    v = struct.unpack_from("<6f", d)
                elif len(d) >= 12:
                    v = struct.unpack_from("<6h", d)
                else:
                    break
                cache[fid] = (v[:3], v[3:])
                break
    return cache[fid]


def to_local(dx, dy, yaw):
    """World offset -> the reference's frame (inverse of its clockwise z rotation)."""
    c, s = math.cos(yaw), math.sin(yaw)
    return dx * c - dy * s, dx * s + dy * c


def ray_box(o, d, lo, hi):
    """2-D slab test: entry distance of the ray o + t d into the box [lo, hi], or None."""
    t0, t1 = -math.inf, math.inf
    for i in range(2):
        if abs(d[i]) < 1e-9:
            if not lo[i] <= o[i] <= hi[i]:
                return None
            continue
        a, b = (lo[i] - o[i]) / d[i], (hi[i] - o[i]) / d[i]
        t0, t1 = max(t0, min(a, b)), min(t1, max(a, b))
    return t0 if t0 <= t1 and t1 >= 0 else None


def marker_cells(ix, wanted):
    """{cell: [its REFR]} for the cells holding a reference of a wanted base (one pass over every reference's NAME)."""
    cells = set()
    for r, c in ix.cell_of.items():
        if ix.kind(r) != "REFR":
            continue
        for sg, d in fo4land.iter_subrecords(fo4land.record_data(ix.p.buf, ix.records[r][1])):
            if sg == b"NAME":
                if len(d) == 4 and struct.unpack_from("<I", d)[0] in wanted:
                    cells.add(c)
                break
    by_cell = {}
    for r, c in ix.cell_of.items():
        if c in cells and ix.kind(r) == "REFR":
            by_cell.setdefault(c, []).append(r)
    return by_cell


def measure(ix, base_fid, radius, units, starfield, by_cell):
    """[{ref, hit base, standoff m, top m, side m}] for every reference of base_fid."""
    cache, out = {}, []
    for c, refs in by_cell.items():
        data = {r: ref_data(ix, r) for r in refs}
        for r, (b, p, sc) in data.items():
            if b != base_fid or p is None:
                continue
            fwd = (math.sin(p[5]), math.cos(p[5]))
            best = None
            for q, (qb, qp, qs) in data.items():
                if q == r or qp is None or qb is None or abs(qp[3]) > 0.1 or abs(qp[4]) > 0.1:
                    continue
                if math.hypot(qp[0] - p[0], qp[1] - p[1]) > radius * units * 2:
                    continue
                bb = bounds(ix, qb, cache, starfield)
                if not bb:
                    continue
                lo, hi = [v * qs for v in bb[0]], [v * qs for v in bb[1]]
                zlo, zhi = (qp[2] + lo[2] - p[2]) / units, (qp[2] + hi[2] - p[2]) / units
                if zhi < BAND[0] or zlo > BAND[1] or zhi > 3.0:          # not at hand height, or a wall / pillar
                    continue
                o = to_local(p[0] - qp[0], p[1] - qp[1], qp[5])
                dl = to_local(fwd[0], fwd[1], qp[5])
                t = ray_box(o, dl, lo, hi)
                if t is None or t / units > radius:
                    continue
                hit = (o[0] + t * dl[0], o[1] + t * dl[1])
                centre = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
                if best is None or t < best["t"]:
                    best = {"t": t, "ref": f"{q:08X}", "base": ix.edid(qb), "standoff_m": round(t / units, 3),
                            "top_m": round(zhi, 3), "box_m": [round((h - l) / units, 2) for l, h in zip(lo, hi)],
                            "hit_off_centre_m": round(math.hypot(hit[0] - centre[0], hit[1] - centre[1]) / units, 2)}
            row = {"marker": f"{r:08X}", "cell": ix.edid(c), "pos": [round(v, 2) for v in p[:3]],
                   "rot_z_deg": round(math.degrees(p[5]), 1)}
            if best:
                best.pop("t")
                row.update(best)
            out.append(row)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esm", required=True)
    ap.add_argument("--base", action="append", required=True, help="furniture EditorID (repeatable)")
    ap.add_argument("--units", type=float, default=1.0, help="game units per metre: 1 Starfield, 70 Skyrim")
    ap.add_argument("--radius", type=float, default=2.0, help="m: how far in front of the marker to look")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    starfield = a.units == 1.0
    ix = packages.Index(a.esm)
    report = {}
    try:
        fids = {e: ix.find_edid(b"FURN", e) for e in a.base}
        by_cell = marker_cells(ix, {f for f in fids.values() if f is not None})
        for e in a.base:
            fid = fids[e]
            if fid is None:
                report[e] = {"error": "no FURN with this EditorID"}
                print(f"{e}: no FURN with this EditorID")
                continue
            rows = measure(ix, fid, a.radius, a.units, starfield, by_cell)
            hits = [r for r in rows if "standoff_m" in r]
            summ = {"refs": len(rows), "with_hit": len(hits)}
            if hits:
                summ.update(standoff_median_m=round(statistics.median(r["standoff_m"] for r in hits), 3),
                            top_median_m=round(statistics.median(r["top_m"] for r in hits), 3))
            report[e] = {"summary": summ, "refs": rows}
            print(f"{e}: {summ}")
            for r in hits[:8]:
                print(f"   {r['marker']} {r['cell']}: {r['base']} standoff {r['standoff_m']} m, top {r['top_m']} m, "
                      f"box {r['box_m']}")
    finally:
        ix.close()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
