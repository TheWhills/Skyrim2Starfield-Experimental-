"""Fallout 4 exterior references -> placements in a Starfield worldspace (terrain experiment 2c).

Input: an exterior placement export (dotnet/Fo4Land export-exterior, schema v2 like dotnet/Fo4Export's cell exports) and
the converter's manifest (scripts/convert_batch.py). Every reference ends in exactly one of two lists, never silently
dropped: `placed` (a converted model at FO4 position / 70) or `skipped` with a reason code and detail.

Frames: a FO4 position (x, y, z) in game units becomes (x, y, z) / 70 metres in the worldspace's own frame, the same
absolute mapping the experiment 2 BTD uses (hypothesis H, docs/terrain/experiment2.md). The Starfield exterior cell is
floor(x / 100 m), floor(y / 100 m) (terrain_grid.sf_cell_of). Rotations are copied (radians, both games use the same
reference convention); for offline geometry they are applied as PluginSpike does: Bethesda angles turn clockwise seen
from the positive axis, X then Y then Z (`ref_matrix`; a pure Z rotation is the familiar clockwise heading).
"""
import math
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import terrain_grid as tg

UNITS_PER_METRE = 70.0

# base record types whose models go through the converter (convert_batch's interior default plus the loose items an
# exterior holds: plants, food, weapons, ammunition, armour; they become plain statics here, visuals only)
CONVERT_TYPES = ("Static", "StaticCollection", "MovableStatic", "Furniture", "Door", "Activator", "Container",
                 "MiscItem", "Terminal", "Flora", "Ingestible", "Weapon", "Ammunition", "Armor")

# types that are never converted, with the reason (everything else outside CONVERT_TYPES gets "type_not_translated")
TYPE_REASONS = {
    "Light": "light source: exterior lights are not translated (daylight scene, no Starfield LIGH records built)",
    "TextureSet": "decal (placed texture set): no decal translation yet",
    "BendableSpline": "bendable spline (power lines, cables): no Starfield equivalent built yet",
    "IdleMarker": "idle marker: AI animation marker, editor-only",
    "SoundMarker": "sound marker: ambient sound not translated",
    "AcousticSpace": "acoustic space: ambient sound not translated",
}
# the same model filter convert_batch applies to cell exports (editor markers; fog / light / particle effect meshes)
MARKER_RE = re.compile(r"marker", re.I)
EFFECTS_RE = re.compile(r"^\\?effects[\\/]", re.I)
# placed water planes (activators using meshes\water\*.nif): FO4 renders them with its water type; converted as a
# static they would be an opaque grey sheet at water level, so they stay out until water is translated
WATER_RE = re.compile(r"^\\?water[\\/]", re.I)


def source_key(model: str) -> str:
    """convert_batch's identity of a model: 'meshes\\' + the model path, compared case-insensitively."""
    return ("meshes\\" + model.replace("/", "\\").lstrip("\\")).lower()


def classify(ref: dict, convert_types=CONVERT_TYPES) -> Tuple[str, Optional[str], str]:
    """('convert', None, '') or ('skip', reason code, detail) for one exported reference."""
    t, model = ref.get("type") or "?", ref.get("model") or ""
    if t in TYPE_REASONS:
        return "skip", "type_not_translated", TYPE_REASONS[t]
    if t not in convert_types:
        return "skip", "type_not_translated", f"base type {t} is not converted"
    if not model:
        what = {"Activator": "trigger volume or primitive (no model)", "Static": "static without a model (collision "
                "plane / primitive)"}.get(t, f"{t} base without a model")
        return "skip", "no_model", what
    if MARKER_RE.search(model):
        return "skip", "editor_marker", f"editor marker model {model}"
    if EFFECTS_RE.search(model):
        return "skip", "effect", f"effect mesh (fog, light beam or particles) {model}"
    if WATER_RE.search(model):
        return "skip", "water", f"placed water plane {model}: no water translation yet (as a static it is an opaque sheet)"
    return "convert", None, ""


def select(export: dict, convert_types=CONVERT_TYPES) -> Tuple[dict, List[dict]]:
    """(cell JSON with only the references to convert, [skipped entries]) for convert_batch --cell-json."""
    keep, skipped = [], []
    for r in export["refs"]:
        action, code, detail = classify(r, convert_types)
        if action == "convert":
            keep.append(r)
        else:
            skipped.append(skip_entry(r, code, detail))
    for d in export.get("deferred_refs", []):
        skipped.append(skip_entry(d, "deferred", d.get("reason", "deferred by the exporter")))
    sub = {k: v for k, v in export.items() if k not in ("refs", "deferred_refs")}
    sub["refs"] = keep
    return sub, skipped


def skip_entry(ref: dict, code: str, detail: str) -> dict:
    return {"formkey": ref.get("formkey"), "type": ref.get("type"), "base_editor_id": ref.get("base_editor_id"),
            "model": ref.get("model"), "exterior_cell": ref.get("exterior_cell"), "reason": code, "detail": detail}


# ------------------------------------------------------------------------------------------------------------ geometry
def ref_matrix(rot) -> Tuple[float, ...]:
    """Row-major 3x3 world rotation of a reference (radians, Bethesda clockwise angles, X then Y then Z), the matrix
    PluginSpike.RotateOffset and scripts/game/routes.py use: R = Rz(-z) Ry(-y) Rx(-x)."""
    cx, sx = math.cos(-rot[0]), math.sin(-rot[0])
    cy, sy = math.cos(-rot[1]), math.sin(-rot[1])
    cz, sz = math.cos(-rot[2]), math.sin(-rot[2])
    rx = (1, 0, 0, 0, cx, -sx, 0, sx, cx)
    ry = (cy, 0, sy, 0, 1, 0, -sy, 0, cy)
    rz = (cz, -sz, 0, sz, cz, 0, 0, 0, 1)
    return _mul(rz, _mul(ry, rx))


def _mul(a, b):
    return tuple(sum(a[3 * r + k] * b[3 * k + c] for k in range(3)) for r in range(3) for c in range(3))


def to_world(v, pos_m, rot, scale):
    """A model-space point (metres) of a reference placed at pos_m (metres) with rot (radians) and scale."""
    m = ref_matrix(rot)
    return tuple(pos_m[a] + scale * (m[3 * a] * v[0] + m[3 * a + 1] * v[1] + m[3 * a + 2] * v[2]) for a in range(3))


def metres(pos_units) -> Tuple[float, float, float]:
    return tuple(float(v) / UNITS_PER_METRE for v in pos_units)


# ------------------------------------------------------------------------------------------------------------ placing
def plugin_editor_id(manifest_editor_id: str, prefix: str) -> str:
    """The base record EditorID in the experiment plugin: convert_batch's 'FO4Port_<stem>' with our own prefix, so the
    experiment never shares an EditorID with FO4Port.esm."""
    return prefix + manifest_editor_id[len("FO4Port_"):] if manifest_editor_id.startswith("FO4Port_") \
        else prefix + manifest_editor_id


def place(selected: dict, manifest: dict, cell_min: int, cell_max: int, edid_prefix: str = "FO4CW_"):
    """Join the selected references with the converter manifest.
    Returns (bases, placed, skipped): bases = [{"key", "edid", "model", "door"?}] in first-use order;
    placed = [{"src", "base", "cell", "pos", "rot", "scale", "disabled", ...}] (pos in metres, door origin offsets
    applied); skipped = [{..., "reason", "detail"}]."""
    items = {i["source"].replace("/", "\\").lower(): i for i in manifest["items"]}
    failures = {f["nif"].replace("/", "\\").lower(): f["reason"] for f in manifest.get("failures", [])}
    bases, base_index, placed, skipped = [], {}, [], []
    edids = set()
    for r in sorted(selected["refs"], key=lambda r: r["formkey"]):
        key = source_key(r["model"])
        item = items.get(key)
        if item is None:
            if key in failures:
                skipped.append(skip_entry(r, "conversion_failed", failures[key]))
            else:
                skipped.append(skip_entry(r, "not_converted", "model missing from the converter manifest"))
            continue
        pos = metres(r["pos"])
        scale = float(r.get("scale") or 1.0)
        rot = [float(v) for v in r["rot"]]
        if "door" in item:                       # rigged door: its NIF origin is the hinge, shift as PluginSpike does
            off = item["door"]["origin_offset"]
            m = ref_matrix(rot)
            pos = tuple(pos[a] + scale * sum(m[3 * a + k] * off[k] for k in range(3)) for a in range(3))
        # the cell of the position actually written, after the hinge shift (a door near a cell edge can cross it)
        cell = tg.sf_cell_of(pos[0], pos[1])
        if not (cell_min <= cell[0] <= cell_max and cell_min <= cell[1] <= cell_max):
            skipped.append(skip_entry(r, "outside_terrain", f"Starfield cell {list(cell)} outside {cell_min}..{cell_max}"))
            continue
        if key not in base_index:
            edid = plugin_editor_id(item["editor_id"], edid_prefix)
            if edid.lower() in edids:
                raise ValueError(f"duplicate base EditorID {edid}")
            edids.add(edid.lower())
            base = {"key": key, "edid": edid, "model": item["model"], "source": item["source"]}
            if "door" in item:
                base["door"] = item["door"]
            base_index[key] = len(bases)
            bases.append(base)
        placed.append({"src": r["formkey"], "base": base_index[key], "cell": list(cell),
                       "pos": [round(v, 5) for v in pos], "rot": rot, "scale": scale,
                       "disabled": bool(r.get("disabled")), "fo4_persistent": bool(r.get("persistent")),
                       "fo4_cell": r.get("exterior_cell"), "enable_parent": r.get("enable_parent") is not None})
    return bases, placed, skipped


def reason_counts(skipped: List[dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for s in skipped:
        out[s["reason"]] = out.get(s["reason"], 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ------------------------------------------------------------------------------------------------------------ surfaces
def point_in_triangle_z(tri, x, y) -> Optional[float]:
    """z of the triangle's plane at (x, y) when (x, y) lies inside its xy projection (edges included), else None."""
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
    d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(d) < 1e-12:
        return None
    l1 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / d
    l2 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / d
    l3 = 1.0 - l1 - l2
    if min(l1, l2, l3) < -1e-9:
        return None
    return l1 * az + l2 * bz + l3 * cz


def surfaces_at(tris, x, y) -> List[float]:
    """Every z where a triangle covers (x, y), highest first."""
    zs = [z for t in tris if (z := point_in_triangle_z(t, x, y)) is not None]
    return sorted(zs, reverse=True)


def top_z(tris, x, y, below=math.inf) -> Optional[float]:
    """Highest surface at (x, y) not above `below` (what a player dropped from `below` lands on), or None."""
    zs = [z for z in surfaces_at(tris, x, y) if z <= below]
    return zs[0] if zs else None


def world_triangles(model_tris, placed, skip_disabled=True):
    """(tris (N, 3, 3), owners (N,)) of every placed reference: model_tris[base] is a (M, 3, 3) array in model space
    (metres), moved by scale, ref_matrix(rot) and pos. Initially disabled references have no collision in game and
    are left out unless skip_disabled is False."""
    out, own = [], []
    for k, p in enumerate(placed):
        if skip_disabled and p.get("disabled"):
            continue
        t = np.asarray(model_tris.get(p["base"], ()), np.float64).reshape(-1, 3, 3)
        if not len(t):
            continue
        m = np.array(ref_matrix(p["rot"])).reshape(3, 3)
        w = (t.reshape(-1, 3) * float(p["scale"])) @ m.T + np.asarray(p["pos"], np.float64)
        out.append(w.reshape(-1, 3, 3))
        own.append(np.full(len(t), k, np.int64))
    if not out:
        return np.zeros((0, 3, 3)), np.zeros(0, np.int64)
    return np.concatenate(out), np.concatenate(own)


class SurfaceIndex:
    """World collision triangles of many placed objects, bucketed on an xy grid for fast vertical queries.
    tris: (N, 3, 3) array (metres), owners: (N,) int array (index of the placed reference)."""

    def __init__(self, tris, owners, cell: float = 4.0):
        self.tris = np.asarray(tris, np.float64).reshape(-1, 3, 3)
        self.owners = np.asarray(owners, np.int64).reshape(-1)
        self.cell = cell
        self.buckets: Dict[Tuple[int, int], list] = {}
        if not len(self.tris):
            return
        lo = np.floor(self.tris[:, :, :2].min(axis=1) / cell).astype(np.int64)
        hi = np.floor(self.tris[:, :, :2].max(axis=1) / cell).astype(np.int64)
        for k in range(len(self.tris)):
            for i in range(lo[k, 0], hi[k, 0] + 1):
                for j in range(lo[k, 1], hi[k, 1] + 1):
                    self.buckets.setdefault((int(i), int(j)), []).append(k)
        self.buckets = {key: np.array(v, np.int64) for key, v in self.buckets.items()}

    def surfaces(self, x: float, y: float):
        """[(z, owner)] of every triangle covering (x, y), highest first."""
        idx = self.buckets.get((int(math.floor(x / self.cell)), int(math.floor(y / self.cell))))
        if idx is None:
            return []
        t = self.tris[idx]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        d = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
        ok = np.abs(d) > 1e-12
        d = np.where(ok, d, 1.0)
        l1 = ((b[:, 1] - c[:, 1]) * (x - c[:, 0]) + (c[:, 0] - b[:, 0]) * (y - c[:, 1])) / d
        l2 = ((c[:, 1] - a[:, 1]) * (x - c[:, 0]) + (a[:, 0] - c[:, 0]) * (y - c[:, 1])) / d
        l3 = 1.0 - l1 - l2
        hit = ok & (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
        z = l1 * a[:, 2] + l2 * b[:, 2] + l3 * c[:, 2]
        out = sorted(zip(z[hit].tolist(), self.owners[idx][hit].tolist()), reverse=True)
        return out

    def top(self, x: float, y: float, below: float = math.inf):
        """(z, owner) of the highest surface at (x, y) not above `below`, or None."""
        for z, o in self.surfaces(x, y):
            if z <= below:
                return z, o
        return None

    def near(self, x: float, y: float, r: float):
        """Indices of the triangles whose buckets touch the square (x - r .. x + r, y - r .. y + r) (a superset)."""
        i0, i1 = int(math.floor((x - r) / self.cell)), int(math.floor((x + r) / self.cell))
        j0, j1 = int(math.floor((y - r) / self.cell)), int(math.floor((y + r) / self.cell))
        parts = [self.buckets[(i, j)] for i in range(i0, i1 + 1) for j in range(j0, j1 + 1) if (i, j) in self.buckets]
        return np.unique(np.concatenate(parts)) if parts else np.zeros(0, np.int64)


def disc_offsets(radius: float, rings: int = 2, per_ring: int = 8):
    """(dx, dy) samples of a disc: the centre plus `rings` rings of `per_ring` points."""
    out = [(0.0, 0.0)]
    for k in range(1, rings + 1):
        r = radius * k / rings
        out += [(r * math.cos(2 * math.pi * j / per_ring), r * math.sin(2 * math.pi * j / per_ring)) for j in range(per_ring)]
    return out


def triangles_top(tris):
    """A `top` function for landing() over a plain triangle list (owner None)."""
    def top(x, y, below):
        z = top_z(tris, x, y, below)
        return None if z is None else (z, None)
    return top


def landing(top, ground, x, y, drop_z, radius=0.6):
    """What a player dropped at (x, y) from drop_z lands on, judged over a disc of `radius` (about the character
    capsule). top(x, y, below) -> (z, owner) or None is the highest collision surface not above `below`
    (SurfaceIndex.top, or triangles_top); ground(x, y) the terrain height. Returns {"z": highest support under the
    disc, "spread": max - min support over the disc, "ground": terrain z at the centre, "on_object": the centre's
    support is a collision surface above the terrain, "all_on_object", "owner": the centre support's owner,
    "owners": every owner supporting part of the disc}."""
    zs, objs, owners, centre_owner = [], [], set(), None
    for k, (dx, dy) in enumerate(disc_offsets(radius)):
        g = ground(x + dx, y + dy)
        hit = top(x + dx, y + dy, drop_z)
        on = hit is not None and hit[0] > g
        zs.append(hit[0] if on else g)
        objs.append(on)
        if on:
            owners.add(hit[1])
            if k == 0:
                centre_owner = hit[1]
    return {"z": max(zs), "centre": zs[0], "spread": max(zs) - min(zs), "ground": ground(x, y), "on_object": objs[0],
            "all_on_object": all(objs), "owner": centre_owner, "owners": sorted(owners, key=str)}


def nearby_object(top, ground, x, y, drop_z, radii=(0.15, 0.3, 0.45, 0.6), per_ring=24, threshold=0.1):
    """The closest collision surface standing more than `threshold` above the terrain around (x, y), as seen by a
    drop from drop_z: {"distance", "height" (above the terrain there), "owner"} for the first ring (smallest radius)
    where one appears (its highest sample), or None when the rings are clear. A dropped player whose capsule
    reaches such a surface may land on it instead of the terrain."""
    for r in radii:
        best = None
        for k in range(per_ring):
            px, py = x + r * math.cos(2 * math.pi * k / per_ring), y + r * math.sin(2 * math.pi * k / per_ring)
            hit = top(px, py, drop_z)
            if hit is None:
                continue
            h = hit[0] - ground(px, py)
            if h > threshold and (best is None or h > best["height"]):
                best = {"distance": r, "height": h, "owner": hit[1]}
        if best is not None:
            return best
    return None


def clearance(index: SurfaceIndex, x, y, z, radius=0.6, skin=0.05):
    """Free height above z over a disc: lowest collision surface higher than z + skin at any disc sample, minus z
    (math.inf when nothing is above)."""
    best = math.inf
    for dx, dy in disc_offsets(radius):
        above = [s for s, _ in index.surfaces(x + dx, y + dy) if s > z + skin]
        if above:
            best = min(best, min(above) - z)
    return best


def flat_samples(index: SurfaceIndex, ground, owner, bounds, drop_z, step=0.5, min_above=0.02):
    """(x, y, z) on a grid over bounds (x0, y0, x1, y1) where a drop from drop_z lands on `owner` (its surface is the
    highest one not above drop_z and lies more than min_above over the terrain)."""
    x0, y0, x1, y1 = bounds
    out = []
    for x in np.arange(x0 + step / 2, x1, step):
        for y in np.arange(y0 + step / 2, y1, step):
            hit = index.top(float(x), float(y), drop_z)
            if hit is not None and hit[1] == owner and hit[0] > ground(float(x), float(y)) + min_above:
                out.append((float(x), float(y), hit[0]))
    return out


def interior_order(samples, radius=2.0, flat_tol=0.03, min_count=1):
    """Samples ranked by how interior and level their neighbourhood is: the count of samples within `radius` whose
    z lies within flat_tol of the sample's own z (more = farther from an edge or a step), ties broken by distance to
    the samples' centroid, then by position (deterministic). Samples below min_count neighbours are dropped."""
    if not samples:
        return []
    s = np.asarray(samples, np.float64)
    cx, cy = s[:, 0].mean(), s[:, 1].mean()
    ranked = []
    for x, y, z in samples:
        d = np.hypot(s[:, 0] - x, s[:, 1] - y)
        cnt = int(((d <= radius + 1e-9) & (np.abs(s[:, 2] - z) <= flat_tol)).sum())
        if cnt >= min_count:
            ranked.append((-cnt, round(math.hypot(x - cx, y - cy), 6), x, y, z))
    ranked.sort()
    return [(x, y, z, -c) for c, _, x, y, z in ranked]


def pick_points(index: SurfaceIndex, ground, owner, bounds, drop_z, count=1, min_gap=3.0, step=0.5, radius=0.6,
                flat_tol=0.02, need_clearance=0.0):
    """Up to `count` measuring points on `owner`: interior, level samples whose whole landing disc rests on the owner
    (spread <= flat_tol) and, when need_clearance > 0, with that much free height above the surface (room for the
    dropped player under a roof). Points are at least min_gap apart. Returns [(x, y, landing dict, clearance)]."""
    picked = []
    for x, y, z, _ in interior_order(flat_samples(index, ground, owner, bounds, drop_z, step), radius=2.0,
                                     flat_tol=flat_tol, min_count=9):
        if any(math.hypot(x - p[0], y - p[1]) < min_gap for p in picked):
            continue
        land = landing(index.top, ground, x, y, drop_z, radius)
        if not (land["all_on_object"] and land["owners"] == [owner] and land["spread"] <= flat_tol):
            continue
        free = clearance(index, x, y, land["centre"], radius) if need_clearance else math.inf
        if free < need_clearance:
            continue
        picked.append((x, y, land, free))
        if len(picked) == count:
            break
    return picked


# ------------------------------------------------------------------------------------------------------------ teleports
def setpos_path(start, target_xy, drop_z):
    """The positions the runner's Teleport passes through (scripts/game/qstep.ps1: player.setpos x, then y, then z) on
    its way from start (x, y, z: where the player stands) to target_xy at drop_z: [(x1, y0, z0), (x1, y1, z0),
    (x1, y1, drop_z)]."""
    x0, y0, z0 = start
    x1, y1 = target_xy
    return [(x1, y0, z0), (x1, y1, z0), (x1, y1, drop_z)]


def _clip_z(poly, zlo, zhi):
    """The part of a polygon [(x, y, z)] between the planes z = zlo and z = zhi (Sutherland-Hodgman)."""
    def clip(poly, inside, level):
        out = []
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            ia, ib = inside(a), inside(b)
            if ia:
                out.append(a)
            if ia != ib:
                t = (level - a[2]) / (b[2] - a[2])
                out.append(tuple(a[k] + (b[k] - a[k]) * t for k in range(3)))
        return out
    poly = clip(list(poly), lambda p: p[2] >= zlo, zlo)
    return clip(poly, lambda p: p[2] <= zhi, zhi) if poly else []


def _xy_distance(poly, x, y) -> float:
    """Distance in xy from (x, y) to a convex polygon's projection (0 inside; degenerate polygons by their edges)."""
    n = len(poly)
    if n >= 3:
        signs = [(poly[(i + 1) % n][0] - poly[i][0]) * (y - poly[i][1]) - (poly[(i + 1) % n][1] - poly[i][1]) * (x - poly[i][0])
                 for i in range(n)]
        if (all(s >= -1e-12 for s in signs) or all(s <= 1e-12 for s in signs)) and any(abs(s) > 1e-12 for s in signs):
            return 0.0
    best = math.inf
    for i in range(n):
        (ax, ay, _), (bx, by, _) = poly[i], poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy
        t = 0.0 if ll < 1e-18 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ll))
        best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best


def capsule_hits(index: SurfaceIndex, ground, x, y, z, radius=0.4, height=1.8, skin=0.05):
    """What a standing player (a vertical cylinder of `radius` from z + skin to z + height, z = the feet) placed at
    (x, y, z) overlaps: [owner] of every collision triangle that reaches into the cylinder (walls included, not only
    the surfaces a vertical ray sees), plus "terrain" when the terrain rises above z + skin anywhere under the disc.
    Empty = clear. The radius and height are assumptions (the capsule is unresolved); skin ignores touching contact.
    A cylinder wholly inside a closed solid wider and taller than itself touches no triangle and is not reported."""
    hits = set()
    for k in index.near(x, y, radius).tolist():
        tri = index.tris[k]
        if tri[:, 2].max() <= z + skin or tri[:, 2].min() >= z + height:
            continue
        poly = _clip_z([tuple(v) for v in tri.tolist()], z + skin, z + height)
        if poly and _xy_distance(poly, x, y) < radius:
            hits.add(int(index.owners[k]))
    out = sorted(hits)
    if any(ground(x + dx, y + dy) > z + skin for dx, dy in disc_offsets(radius)):
        out.append("terrain")
    return out
