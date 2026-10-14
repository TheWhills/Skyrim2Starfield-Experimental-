"""Build movement test routes for a converted cell from Fallout 4's own data (no guessing from screenshots).

usage: python routes.py --fo4-data <FO4 Data> --cell-json <cell.json> --manifest <manifest.json> --out routes.json

Stairs: every placed model whose FO4 collision has a stair ramp: the L_STAIRHELPER body (layer 31) if present, else the
collision triangles sloped 20-50 degrees. The ramp's low and high ends (node space -> placement) give a start point 0.8 m
before the low end, the heading towards the high end, and the expected height at the top.
Doors: every placed converted door (manifest item with "door"): start 1.6 m in front of the FO4 origin facing through
the opening, press E, walk; pass = the player ends at least 1 m past the door plane.
Coordinates are metres in Starfield cell space (FO4 units / 70); reference rotations use Bethesda's clockwise angles.
"""
import argparse
import json
import math
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from fo4sf import fo4collision, hkpackfile, nif, pipeline  # noqa: E402

UNIT = 1.0 / 70.0
STAIRHELPER = 31


def ref_matrix(rot):
    """Bethesda reference rotation (radians, clockwise), applied X then Y then Z: same as PluginSpike.RotateOffset."""
    cx, sx = math.cos(-rot[0]), math.sin(-rot[0])
    cy, sy = math.cos(-rot[1]), math.sin(-rot[1])
    cz, sz = math.cos(-rot[2]), math.sin(-rot[2])
    rx = (1, 0, 0, 0, cx, -sx, 0, sx, cx)
    ry = (cy, 0, sy, 0, 1, 0, -sy, 0, cy)
    rz = (cz, -sz, 0, sz, cz, 0, 0, 0, 1)
    return nif._matmul(rz, nif._matmul(ry, rx))


def apply(m, v):
    return tuple(m[3 * i] * v[0] + m[3 * i + 1] * v[1] + m[3 * i + 2] * v[2] for i in range(3))


def collision_bodies(f):
    """(layer, points, triangles) of every FO4 collision body of a NIF, points in NIF root space (metres)."""
    world = nif.world_transforms(f)
    for i in range(len(f.blocks)):
        if f.type_of(i) != "bhkNPCollisionObject":
            continue
        target, _, data = struct.unpack_from("<iHi", f.blocks[i], 0)
        body = struct.unpack_from("<I", f.blocks[i], 10)[0] if len(f.blocks[i]) >= 14 else 0
        if not (0 <= data < len(f.blocks)) or f.type_of(data) != "bhkPhysicsSystem":
            continue
        n, = struct.unpack_from("<I", f.blocks[data], 0)
        try:
            p = hkpackfile.Packfile(f.blocks[data][4:4 + n])
        except hkpackfile.PackfileError:
            continue
        classes = dict(p.objects())
        sysobj = next(o for o, c in classes.items() if c == "hknpPhysicsSystemData")
        at, nb = p.array(sysobj + fo4collision.SYS_BODIES)
        tr, rot, _ = world(target)
        to_root = lambda v: tuple(a + b * UNIT for a, b in zip(apply(rot, v), tr))
        for k in ([body] if 0 <= body < nb else []):
            b = at + fo4collision.BODY_SIZE * k
            shape = p.pointer(b)
            layer = p.unpack("<I", b + 20)[0] & 0x7F
            cls = classes.get(shape)
            try:
                if cls == "hknpConvexPolytopeShape":
                    pts, tris = fo4collision._convex(p, shape)
                elif cls == "hknpCompressedMeshShape":
                    pts, tris = fo4collision._compressed_mesh(p, p.pointer(shape + fo4collision.CMS_DATA))
                else:
                    continue
            except (IndexError, hkpackfile.PackfileError):
                continue
            yield layer, [to_root(v) for v in pts], tris


def ramp_points(f):
    """Node-space-transformed (NIF root, metres) points of the stair ramp of a FO4 NIF, or [] if it has none."""
    helper, sloped = [], []
    for layer, pts, tris in collision_bodies(f):
        if layer == STAIRHELPER:
            helper += pts
            continue
        for t in tris:
            a, b_, c = (pts[x] for x in t)
            u = [b_[q] - a[q] for q in range(3)]
            v = [c[q] - a[q] for q in range(3)]
            nrm = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            ln = math.sqrt(sum(x * x for x in nrm)) or 1
            tilt = math.degrees(math.acos(max(-1, min(1, nrm[2] / ln))))
            if 20 < tilt < 50:
                sloped += [a, b_, c]
    return (helper, "stairhelper") if helper else (sloped, "sloped-collision") if sloped else ([], None)


def walkable_triangles(f):
    """Upward-facing collision triangles (|normal z| >= 0.3) of a FO4 NIF in NIF root space: what can be stood on."""
    out = []
    for layer, pts, tris in collision_bodies(f):
        if layer == STAIRHELPER:
            continue
        for t in tris:
            a, b, c = (pts[x] for x in t)
            u = [b[q] - a[q] for q in range(3)]
            v = [c[q] - a[q] for q in range(3)]
            nz = u[0] * v[1] - u[1] * v[0]
            ln = math.sqrt((u[1] * v[2] - u[2] * v[1]) ** 2 + (u[2] * v[0] - u[0] * v[2]) ** 2 + nz * nz)
            if ln > 1e-9 and abs(nz) / ln >= 0.3:
                out.append((a, b, c))
    return out


def surface_z(tris, x, y, below):
    """Highest z of any triangle over (x, y) that is not above `below`, or None."""
    best = None
    for a, b, c in tris:
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        l1 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d
        l2 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d
        l3 = 1 - l1 - l2
        if min(l1, l2, l3) < -1e-6:
            continue
        z = l1 * a[2] + l2 * b[2] + l3 * c[2]
        if z <= below and (best is None or z > best):
            best = z
    return best


def emerge(lo, hi, ground):
    """Where a ramp from lo to hi comes out of the surrounding ground: (fraction along the ramp, ground z there or None).
    FO4 sinks the foot of stairs into terrain and mounds (Parsons' retaining-wall stairs start 2.5 m below the grass):
    teleporting to the buried foot puts the player under the floor. ground(x, y, below) is the highest walkable
    surface of the neighbouring models."""
    steps = 40
    for s in range(steps + 1):
        t = s / steps
        p = tuple(lo[i] + t * (hi[i] - lo[i]) for i in range(3))
        g = ground(p[0], p[1], p[2] + 1.5)               # a mound up to 1.5 m above the ramp buries it
        if g is None or g <= p[2] + 0.15:
            return t, g
    return 1.0, None


def door_frame(f):
    """(centre, unit normal) of a door model in its local space (metres): bounds of all render shapes, normal along the
    thinner horizontal axis. None if it has no geometry."""
    pts = []
    hinge = nif.door_hinge(f)                       # the closed leaf spans the opening: use it alone when there is one
    moving = nif.descendants(f, hinge[0]) if hinge else None
    for s in nif.fo4_trishapes(f):
        if moving is not None and s.block not in moving:
            continue
        for v in s.positions:
            pts.append(tuple((sum(s.rotation[3 * r + k] * v[k] for k in range(3)) * s.scale + s.translation[r]) * UNIT
                             for r in range(3)))
    if not pts:
        return None
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    centre = tuple((lo[i] + hi[i]) / 2 for i in range(3))
    axis = (1.0, 0.0, 0.0) if hi[0] - lo[0] <= hi[1] - lo[1] else (0.0, 1.0, 0.0)
    return (centre[0], centre[1], lo[2]), axis


def ends(points):
    zs = [p[2] for p in points]
    lo_z, hi_z = min(zs), max(zs)
    low = [p for p in points if p[2] <= lo_z + 0.05]
    high = [p for p in points if p[2] >= hi_z - 0.05]
    mean = lambda ps: tuple(sum(p[i] for p in ps) / len(ps) for i in range(3))
    return mean(low), mean(high)


def neighbour_ground(cell, stair_ref, centre, radius, src, items, cache):
    """ground(x, y, below) over the walkable collision of the models placed within `radius` of `centre` (not the stair)."""
    tris = []
    for r in cell["refs"]:
        if r is stair_ref or not r.get("model") or r.get("type") == "Light":
            continue
        pos = tuple(x * UNIT for x in r["pos"])
        if math.hypot(pos[0] - centre[0], pos[1] - centre[1]) > radius + 6.0:   # model origins can be ~6 m off-centre
            continue
        key = "meshes\\" + r["model"].lstrip("\\").lower()
        if key not in items:
            continue
        if key not in cache:
            raw = src.mesh(key)
            try:
                cache[key] = walkable_triangles(nif.parse(raw)) if raw else []
            except Exception:                              # noqa: BLE001  (one unreadable model must not stop routes)
                cache[key] = []
        if not cache[key]:
            continue
        R, sc = ref_matrix(r["rot"]), r.get("scale", 1.0) or 1.0
        pl = lambda v: tuple(a + b for a, b in zip(apply(R, tuple(x * sc for x in v)), pos))
        for a, b, c in cache[key]:
            pa, pb, pc = pl(a), pl(b), pl(c)
            if min(p[0] for p in (pa, pb, pc)) > centre[0] + radius or max(p[0] for p in (pa, pb, pc)) < centre[0] - radius:
                continue
            if min(p[1] for p in (pa, pb, pc)) > centre[1] + radius or max(p[1] for p in (pa, pb, pc)) < centre[1] - radius:
                continue
            tris.append((pa, pb, pc))
    return lambda x, y, below: surface_z(tris, x, y, below)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fo4-data", required=True)
    ap.add_argument("--cell-json", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--formids", default="", help="plugin formids.json: door routes get the door's Starfield ref id "
                    "(local FormID) so the runner can close it before each crossing")
    a = ap.parse_args()
    formids = json.load(open(a.formids, encoding="utf-8-sig")) if a.formids else {}
    src = pipeline.Fo4Archives(a.fo4_data)
    cell = json.load(open(a.cell_json, encoding="utf-8-sig"))
    man = json.load(open(a.manifest))
    items = {it["source"].lower(): it for it in man["items"]}
    routes, cache, skipped, tri_cache = [], {}, {}, {}
    for r in cell["refs"]:
        model = r.get("model") or ""
        key = "meshes\\" + model.lstrip("\\").lower()
        it = items.get(key)
        if not it:
            continue
        pos = tuple(x * UNIT for x in r["pos"])
        R = ref_matrix(r["rot"])
        sc = r.get("scale", 1.0) or 1.0
        place = lambda v: tuple(a_ + b_ for a_, b_ in zip(apply(R, tuple(x * sc for x in v)), pos))
        if it.get("door"):
            # facing from the door's own geometry: the thinnest horizontal axis of its local bounds is the door normal;
            # the route crosses the middle of the opening, once from each side (a leaf may swing towards the player)
            if key not in cache:
                raw = src.mesh(key)
                cache[key] = door_frame(nif.parse(raw)) if raw else None
            frame = cache[key]
            if frame is None:
                continue
            centre_l, axis_l = frame
            centre = place(centre_l)
            n = tuple(x - y for x, y in zip(place(axis_l), pos))
            local = formids.get(f"REFR:FO4Port_{cell['cell']}:{r['formkey']}")
            for side in (1, -1):
                ns = tuple(side * x for x in n)
                start = tuple(centre[i] - 1.6 * ns[i] for i in range(3))
                routes.append({"cell": cell["cell"], "kind": "door", "ref": r["formkey"], "model": model, "side": side,
                               **({"sf_ref_local": f"{local:06X}"} if local is not None else {}),
                               "start": [round(start[0], 2), round(start[1], 2), round(pos[2] + 0.3, 2)],
                               "heading": round(math.degrees(math.atan2(ns[0], ns[1])) % 360, 1), "use": True,
                               "walk_ms": 1100,
                               "expect": {"plane_point": [round(x, 3) for x in centre],
                                          "plane_normal": [round(x, 4) for x in ns], "min_past": 0.8}})
            continue
        if "stair" not in model.lower():
            continue
        if key not in cache:
            raw = src.mesh(key)
            cache[key] = ramp_points(nif.parse(raw)) if raw else ([], None)
        pts, how = cache[key]
        if not pts:
            skipped[model] = skipped.get(model, 0) + 1
            continue
        lo, hi = ends([place(p) for p in pts])
        d = (hi[0] - lo[0], hi[1] - lo[1])
        run = math.hypot(*d) or 1.0
        ground = neighbour_ground(cell, r, ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2), run / 2 + 4.0, src, items, tri_cache)
        t, g = emerge(lo, hi, ground)
        if t >= 0.8:                # "almost all buried" is more likely an overlapping piece (Prydwen platform stairs
            t, g = 0.0, None        # passed in game): keep the plain route and flag it rather than drop it
            skipped[model + " (looks buried, route kept)"] = skipped.get(model + " (looks buried, route kept)", 0) + 1
        if t > 0:                                         # foot buried: start where the ramp comes out of the ground
            lo = tuple(lo[i] + t * (hi[i] - lo[i]) for i in range(2)) + (max(lo[2] + t * (hi[2] - lo[2]), g or -1e9),)
            d = (hi[0] - lo[0], hi[1] - lo[1])
            run = math.hypot(*d) or 1.0
        sx, sy = lo[0] - 0.8 * d[0] / run, lo[1] - 0.8 * d[1] / run
        sz = ground(sx, sy, lo[2] + 1.0)
        start = (sx, sy, (sz if sz is not None and t > 0 else lo[2]) + 0.3)
        routes.append({"cell": cell["cell"], "kind": "stairs", "ref": r["formkey"], "model": model, "ramp": how,
                       "buried_fraction": round(t, 2),
                       "start": [round(x, 2) for x in start], "heading": round(math.degrees(math.atan2(d[0], d[1])) % 360, 1),
                       # the player runs ~4.6 m/s: walk just past the high end (mirrored flights share landings, a longer
                       # walk goes up one and down the other)
                       "use": False, "walk_ms": int(250 + 1000 * (run + 1.0) / 4.0),
                       "expect": {"low": [round(x, 2) for x in lo], "high": [round(x, 2) for x in hi], "min_rise": round(0.8 * (hi[2] - lo[2]), 2)}})
    routes = routes[:a.max]
    json.dump({"routes": routes, "skipped_stairs_without_ramp": skipped}, open(a.out, "w"), indent=1)
    print(f"{len(routes)} routes ({sum(r['kind'] == 'stairs' for r in routes)} stairs, "
          f"{sum(r['kind'] == 'door' for r in routes)} doors); stairs without a ramp: {skipped}")


if __name__ == "__main__":
    main()
