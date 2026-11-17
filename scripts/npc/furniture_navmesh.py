"""Is each furniture spot on Skyrim's navmesh, and is the ground around it (read-only).

2026-11-16 (owner, 22:00-22:05): Alvor picks the forge but never gets in (GetSitting 0), stuck by the rail behind it,
with the forge model hidden too. The CK's animation cache (AnimationOffsets, owner's 14:48 copy) says how Starfield
enters furniture: every EnterFromStand carries its root motion (vanilla chairs walk 0.9-1.1 m into the seat, so the
actor starts out in the open) and a SetPosBegin / SetPosEnd window; ours (Skyrim's clips, --no-root-motion) move
nothing, so the actor has to reach the marker spot itself before the entry starts. The rail / wall leans that work
have their spot in the open; the forge, tanning rack and grindstone have theirs inside the station. Skyrim's navmesh
(ours is Skyrim's, converted) may not reach those spots. This prints, per furniture reference (the work stations and,
for comparison, the leans and sweep spots), each marker's position, whether it lies on a navmesh triangle, how far
the nearest navmesh is, and the same for points 0.5 / 1.0 m out on each side.

    python -I scripts\\npc\\furniture_navmesh.py --skyrim "<Skyrim Data>\\Skyrim.esm" --exterior-furniture <file>
        [--furniture <work>\\furniture.json]
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

UNIT_M = 0.0142875                    # one Skyrim unit in metres
CELL = 4096.0
WATCH = ("forge", "tanning", "sharpening", "armorworkbench", "armortable", "hammertable", "raillean", "walllean",
         "sweep", "leantable", "anvil")
SIDES = {"Front": 0.0, "Right": 90.0, "Rear": 180.0, "Left": -90.0}
Z_TOL = 100.0                          # units (1.4 m): a triangle counts if its height there is this close


def tri_height(p, a, b, c):
    """The triangle's height under p (x, y) if p is inside it (2D), else None."""
    (x, y), (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = p, a[:3], b[:3], c[:3]
    d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(d) < 1e-9:
        return None
    l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / d
    l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / d
    l3 = 1.0 - l1 - l2
    if min(l1, l2, l3) < -1e-6:
        return None
    return l1 * z1 + l2 * z2 + l3 * z3


def seg_dist(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def probe(point, tris):
    """(on navmesh, distance in units to the nearest triangle near that height, triangle flags or None)."""
    x, y, z = point
    best = None
    for a, b, c, flags in tris:
        if min(abs(a[2] - z), abs(b[2] - z), abs(c[2] - z)) > Z_TOL * 3:
            continue
        h = tri_height((x, y), a, b, c)
        if h is not None and abs(h - z) <= Z_TOL:
            return True, 0.0, flags
        d = min(seg_dist((x, y), a, b), seg_dist((x, y), b, c), seg_dist((x, y), c, a))
        if best is None or d < best:
            best = d
    return False, best, None


def marker_points(ref, markers):
    """[(label, (x, y, z), heading_deg, entry sides)] for the reference's markers (Skyrim units; heading clockwise
    from +Y, as Skyrim's rotation Z)."""
    rz = math.degrees(ref["rot"][2])
    out = []
    for i, m in enumerate(markers or [{"offset_m": [0, 0, 0], "rot_deg": 0.0, "entry": []}]):
        ox, oy, oz = (v / UNIT_M for v in m["offset_m"])
        c, s = math.cos(math.radians(rz)), math.sin(math.radians(rz))
        # Skyrim's Z rotation turns clockwise seen from above: local +Y forward -> (sin, cos)
        wx, wy = ox * c + oy * s, -ox * s + oy * c
        p = (ref["pos"][0] + wx, ref["pos"][1] + wy, ref["pos"][2] + oz)
        out.append((f"m{i}", p, rz + m.get("rot_deg", 0.0), m.get("entry") or []))
    return out


def side_point(p, heading, side, dist_m):
    h = math.radians(heading + SIDES[side])
    d = dist_m / UNIT_M
    return (p[0] + math.sin(h) * d, p[1] + math.cos(h) * d, p[2])


def triangles(navs):
    out = []
    for n in navs:
        g = n["geometry"]
        vs = g["vertices"]
        for t in g["triangles"]:
            a, b, c = (vs[i] for i in t["v"])
            out.append((a, b, c, t.get("flags")))
    return out


def report(refs, bases, tris) -> str:
    lines = []
    for r in sorted(refs, key=lambda r: r["base_editor_id"]):
        edid = r["base_editor_id"]
        if not any(k in edid.lower() for k in WATCH):
            continue
        markers = (bases.get(r.get("base_formkey")) or {}).get("markers")
        lines.append(f"\n{edid} {r['formkey']} at ({r['pos'][0]:.0f}, {r['pos'][1]:.0f}, {r['pos'][2]:.0f})")
        for label, p, heading, entry in marker_points(r, markers):
            on, d, fl = probe(p, tris)
            lines.append(f"  {label} entry {','.join(entry) or '?':12} spot: "
                         + ("ON navmesh" if on else f"off, nearest navmesh {d * UNIT_M:.2f} m" if d is not None
                            else "off, no navmesh near"))
            for side in SIDES:
                cells = []
                for dist in (0.5, 1.0):
                    on2, d2, _ = probe(side_point(p, heading, side, dist), tris)
                    cells.append(f"{dist}m " + ("on" if on2 else f"off({d2 * UNIT_M:.2f})" if d2 is not None else "off"))
                lines.append(f"      {side:5} " + "  ".join(cells))
    return "\n".join(lines)


def ref_position(subs):
    """A placed reference's DATA position (x, y, z), or None."""
    import struct
    d = next((d for s, d in subs if s == b"DATA"), None)
    return struct.unpack_from("<3f", d, 0) if d and len(d) >= 12 else None


def distances(name, pos, refs) -> str:
    """How far each watched furniture reference is from pos (metres), nearest first."""
    rows = sorted((math.dist(pos[:2], r["pos"][:2]) * UNIT_M, r["base_editor_id"], r["formkey"]) for r in refs)
    return "\n".join([f"\n{name} at ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})"]
                     + [f"  {d:6.2f} m  {e} {fk}" for d, e, fk in rows[:8]])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--exterior-furniture", required=True, help="make_skyrim_interior's exterior_furniture.json")
    ap.add_argument("--furniture", help="make_furniture's furniture.json (the markers; default: the reference itself)")
    ap.add_argument("--ref", action="append", default=[], metavar="FORMID",
                    help="also print where this Skyrim reference is (hex FormID, e.g. a package's location marker "
                         "02C308) and the furniture nearest it")
    a = ap.parse_args(argv)
    with open(a.exterior_furniture, encoding="utf-8") as fh:
        ext = json.load(fh)
    bases = {}
    if a.furniture:
        with open(a.furniture, encoding="utf-8") as fh:
            bases = json.load(fh).get("bases") or {}
    refs = [r for r in ext["refs"] if any(k in r["base_editor_id"].lower() for k in WATCH)]
    xs = [math.floor(r["pos"][0] / CELL) for r in refs]
    ys = [math.floor(r["pos"][1] / CELL) for r in refs]
    rect = (min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1)
    from fo4sf import exteriornavmesh as en
    navs, bad = en.read_skyrim(a.skyrim, ext.get("world") or "Tamriel", rect)
    tris = triangles(navs)
    print(f"Skyrim navmesh cells {rect}: {len(navs)} navmeshes, {len(tris)} triangles, unreadable {len(bad)}")
    print(report(refs, bases, tris))
    if a.ref:
        from fo4sf import packages
        ix = packages.Index(a.skyrim)
        try:
            for h in a.ref:
                fid = int(h, 16)
                pos = ref_position(ix.subs(fid))
                if pos is None:
                    print(f"\n{h}: no placed reference with a position")
                    continue
                on, d, _ = probe(pos, tris)
                print(distances(f"{h} {ix.edid(fid) or ''}", pos, refs))
                print("  itself: " + ("ON navmesh" if on else f"off ({d * UNIT_M:.2f} m)" if d is not None else "off"))
        finally:
            ix.close()


if __name__ == "__main__":
    main()
