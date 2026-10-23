"""Invisible ramps over stair steps in a collision mesh (metres, z up).

Skyrim's collision often models stairs as real steps; Skyrim's character controller climbs them, Starfield's does not
glide over steps that tall (owner's Oct 2026 run, Alva's House: "you run into each one and eventually go up"). Bethesda's
own fix in their games is a stair-helper ramp: a sloped plane through the step nosings on a layer only the character
controller collides with, so the player walks a slope while items and projectiles still meet the steps.

stair_ramps(points, triangles) finds runs of at least MIN_STEPS steps and returns ramp triangles. A step is an
up-facing flat region whose minimum-area rectangle is narrow (STEP_DEPTH) and longer than deep; consecutive steps are
parallel, offset along the stair direction by about one run, higher by one rise (RISE), and overlap sideways. The ramp
goes from one run before the first step's front edge (one rise lower) to the last step's front edge, extended to the
floor below and the landing above when a flat surface is there. Nothing is returned for meshes that are already ramps.
"""
import math

UP = 0.97                       # |normal z| for a flat, up-facing triangle
SAME_Z = 0.012                  # metres: one tread
RISE = (0.06, 0.45)             # metres between consecutive steps
RUN = (0.10, 0.75)              # metres between consecutive step front edges
STEP_DEPTH = (0.10, 0.70)       # the short side of a step's rectangle
MIN_LENGTH = 0.35               # the long side
PARALLEL = math.radians(12)
MIN_STEPS = 3
MIN_SIDE_OVERLAP = 0.5          # of the narrower step


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _hull(pts):
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(p)
        return out
    lo, hi = half(pts), half(reversed(pts))
    return lo[:-1] + hi[:-1]


def min_rect(pts):
    """Minimum-area rectangle of 2-D points: (angle of the long side, length, depth, centre (x, y))."""
    h = _hull(pts)
    best = None
    edges = [(h[i], h[(i + 1) % len(h)]) for i in range(len(h))] if len(h) > 1 else [((0, 0), (1, 0))]
    for a, b in edges:
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        c, s = math.cos(ang), math.sin(ang)
        us = [p[0] * c + p[1] * s for p in h]
        vs = [-p[0] * s + p[1] * c for p in h]
        du, dv = max(us) - min(us), max(vs) - min(vs)
        if best is None or du * dv < best[0]:
            cu, cv = (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2
            centre = (cu * c - cv * s, cu * s + cv * c)
            best = (du * dv, ang, du, dv, centre) if du >= dv else (du * dv, ang + math.pi / 2, dv, du, centre)
    _area, ang, length, depth, centre = best
    return ang % math.pi, length, depth, centre


def treads(points, triangles):
    """Flat up-facing regions: [{z, pts: [(x, y)], area}], triangles joined when they share a vertex position (1 mm)
    at the same height."""
    flat = []
    for t in triangles:
        a, b, c = (points[i] for i in t)
        n = _cross(_sub(b, a), _sub(c, a))
        ln = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
        if ln < 2e-4 or abs(n[2]) / ln < UP:
            continue
        flat.append(((a, b, c), ln / 2))
    parent = list(range(len(flat)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    key_owner = {}
    for i, (tri, _area) in enumerate(flat):
        for p in tri:
            k = (round(p[0], 3), round(p[1], 3), round(p[2] / SAME_Z))
            j = key_owner.setdefault(k, i)
            if j != i:
                parent[find(i)] = find(j)
    groups = {}
    for i, (tri, area) in enumerate(flat):
        g = groups.setdefault(find(i), {"zs": [], "pts": [], "area": 0.0})
        g["zs"].extend(p[2] for p in tri)
        g["pts"].extend((p[0], p[1]) for p in tri)
        g["area"] += area
    return [{"z": sum(g["zs"]) / len(g["zs"]), "pts": g["pts"], "area": g["area"]} for g in groups.values()]


def _angle_diff(a, b):
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


def _span(pts, axis):
    vals = [p[0] * axis[0] + p[1] * axis[1] for p in pts]
    return min(vals), max(vals)


def stair_runs(points, triangles):
    """Runs of steps: [{steps: [tread], dir: (x, y) uphill, side: (x, y)}], each tread with its rectangle."""
    ts = treads(points, triangles)
    steps = []
    for t in ts:
        ang, length, depth, centre = min_rect(t["pts"])
        if STEP_DEPTH[0] <= depth <= STEP_DEPTH[1] and length >= MIN_LENGTH and length >= 1.5 * depth:
            steps.append(dict(t, ang=ang, length=length, depth=depth, centre=centre))
    steps.sort(key=lambda s: s["z"])
    # link each step to the next one up: parallel, one rise higher, one run further across the long side, overlapping
    nxt = {}
    for i, s in enumerate(steps):
        side = (math.cos(s["ang"]), math.sin(s["ang"]))
        normal = (-side[1], side[0])
        best = None
        for j in range(i + 1, len(steps)):
            u = steps[j]
            dz = u["z"] - s["z"]
            if dz > RISE[1]:
                break
            if dz < RISE[0] or _angle_diff(s["ang"], u["ang"]) > PARALLEL:
                continue
            off = (u["centre"][0] - s["centre"][0]) * normal[0] + (u["centre"][1] - s["centre"][1]) * normal[1]
            if not RUN[0] <= abs(off) <= RUN[1]:
                continue
            a0, a1 = _span(s["pts"], side)
            b0, b1 = _span(u["pts"], side)
            if min(a1, b1) - max(a0, b0) < MIN_SIDE_OVERLAP * min(a1 - a0, b1 - b0):
                continue
            if best is None or dz < best[0]:
                best = (dz, j, 1 if off > 0 else -1)
        if best:
            nxt[i] = (best[1], best[2])
    runs, used = [], set()
    starts = set(nxt) - {j for j, _sgn in nxt.values()}
    for i in sorted(starts, key=lambda k: steps[k]["z"]):
        chain, sgn = [i], nxt[i][1]
        while chain[-1] in nxt and nxt[chain[-1]][1] == sgn and nxt[chain[-1]][0] not in used:
            chain.append(nxt[chain[-1]][0])
        if len(chain) < MIN_STEPS:
            continue
        used.update(chain)
        s0 = steps[chain[0]]
        side = (math.cos(s0["ang"]), math.sin(s0["ang"]))
        up = (-side[1] * sgn, side[0] * sgn)
        runs.append({"steps": [steps[k] for k in chain], "dir": up, "side": side})
    return runs, ts


def _surface_at(ts, x, y, z, tol=0.05):
    """A flat region at height z (within tol) whose rectangle contains (x, y)."""
    for t in ts:
        if abs(t["z"] - z) > tol:
            continue
        ang, length, depth, centre = min_rect(t["pts"])
        c, s = math.cos(ang), math.sin(ang)
        dx, dy = x - centre[0], y - centre[1]
        if abs(dx * c + dy * s) <= length / 2 + 0.02 and abs(-dx * s + dy * c) <= depth / 2 + 0.02:
            return True
    return False


def stair_ramps(points, triangles):
    """(ramp points, ramp triangles, report list) for the stair runs found in this collision mesh (metres)."""
    runs, ts = stair_runs(points, triangles)
    out_p, out_t, report = [], [], []
    for r in runs:
        st, d, w = r["steps"], r["dir"], r["side"]
        fronts = [_span(s["pts"], d)[0] for s in st]                 # each step's front edge along the uphill dir
        zs = [s["z"] for s in st]
        n = len(st)
        rise = (zs[-1] - zs[0]) / (n - 1)
        run = (fronts[-1] - fronts[0]) / (n - 1)
        if run <= 0 or rise <= 0:
            continue
        lo = max(_span(s["pts"], w)[0] for s in st)
        hi = min(_span(s["pts"], w)[1] for s in st)
        if hi - lo < MIN_LENGTH * 0.8:
            continue
        mid_w = (lo + hi) / 2
        at = lambda dd, ww: (d[0] * dd + w[0] * ww, d[1] * dd + w[1] * ww)    # noqa: E731
        d0, z0 = fronts[0] - run, zs[0] - rise                          # the floor in front of the first step
        if not _surface_at(ts, *at(d0 + run * 0.5, mid_w), z0, tol=max(0.05, rise * 0.5)):
            d0, z0 = fronts[0], zs[0]
        d1, z1 = fronts[-1], zs[-1]
        if _surface_at(ts, *at(fronts[-1] + run * 1.5, mid_w), zs[-1] + rise, tol=max(0.05, rise * 0.5)):
            d1, z1 = fronts[-1] + run, zs[-1] + rise                     # the landing's front edge
        base = len(out_p)
        for dd, zz in ((d0, z0), (d1, z1)):
            for ww in (lo, hi):
                x, y = at(dd, ww)
                out_p.append((x, y, zz))
        # counter-clockwise seen from above (normal up): bottom-lo, bottom-hi, top-hi / bottom-lo, top-hi, top-lo
        a, b, c, e = base, base + 1, base + 3, base + 2
        crossz = (out_p[b][0] - out_p[a][0]) * (out_p[c][1] - out_p[a][1]) - (out_p[b][1] - out_p[a][1]) * (out_p[c][0] - out_p[a][0])
        out_t += [(a, b, c), (a, c, e)] if crossz > 0 else [(a, c, b), (a, e, c)]
        report.append({"steps": n, "rise_m": round(rise, 3), "run_m": round(run, 3), "width_m": round(hi - lo, 3),
                       "from_z_m": round(z0, 3), "to_z_m": round(z1, 3),
                       "slope_deg": round(math.degrees(math.atan2(z1 - z0, d1 - d0)), 1)})
    return out_p, out_t, report
