"""Terrain experiment 2c: the real Fallout 4 objects around Red Rocket on the exp2b terrain (docs/terrain/experiment2c.md).

    dotnet run --project dotnet/Fo4Land -c Release -- <Fallout4.esm> export-exterior Commonwealth -20 16 -15 21 <work>/export.json
    python scripts/terrain/make_exp2c.py select --export <work>/export.json --work <work>
    python scripts/convert_batch.py --cell-json <work>/convert_input.json --staging <work>/convert --prefix fo4cw
           --types <printed by select> --limit 100000 --resume  + the usual converter arguments (--starfield-data too)
    python scripts/terrain/make_exp2c.py stage --work <work> --exp2b <terrain_exp2b2> --out <terrain_exp2c> --sf-esm <Starfield.esm>
    python scripts/terrain/make_exp2c.py check --work <work> --exp2b <terrain_exp2b2> --out <terrain_exp2c> [--fo4 <Fallout4.esm>]
           [--fo4-data <FO4 Data>] [--sf-data <Starfield Data>]

select   classifies every exported reference: convert, or skip with a reason (never silently). Writes convert_input.json
         (the references to convert, schema v2) and selection.json.
stage    joins the selection with the converter manifest (exterior.place), copies the base experiment's Data files (BTD,
         mask, ...) and params, writes objects.json for dotnet/TerrainExp2, copies the converted meshes / geometries /
         materials / textures under Data\\, builds FO4TerrainExp2.esm (+ the unchanged Mars plugin) with TerrainExp2, and
         writes plan.json: four runner entries, each carrying every key of the base entry and judged relative to its own
         terrain reference probe (z_ref): 1 terrain gate (exp2b's terrain points near Red Rocket), 2 object tops at least
         1 m above the terrain, 3 the shop floor (informational), 4 exp2b points now on or near objects (informational).
check    raw-walks the plugins (masters, cells, REFR counts, base records, models on disk, base records unchanged),
         decodes the BTD under every placed object's origin (object z - terrain z; with --fo4 also against FO4's own LAND),
         re-derives every plan point from the converted collision (with --fo4-data also from FO4's own collision),
         validates the entries against the runner's keys and predicts what each verdict can tell. Writes offline_check.json.
Everything this writes stays outside the repo (derived game data).
"""
import argparse
import hashlib
import itertools
import json
import math
import os
import shutil
import statistics
import struct
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
from fo4sf import btd, exterior, fo4land, sfbodies  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402

sys.path.insert(0, HERE)
import overlay_records  # noqa: E402

EDID_PREFIX = "FO4CW_"
BUILDING = "0211C0:Fallout4.esm"        # RedRExt_Workshop01: rocket tower, canopy roof, shop ceiling (no floor)
SHOP = "1B5F12:Fallout4.esm"            # RedRExt_Workshop02: shop floor and roof, same origin and rotation
SHOP_LOCAL = (-6.0, 9.0, 6.0, 19.0)     # shop footprint in the building's own frame (x0, y0, x1, y1), metres
FLOOR_DROP = 0.75                        # floor entry: dropped from floor + 0.75 m (feet), head stays under the ceiling
PLAYER_HEIGHT = 1.9                      # room needed above the drop height
DROP_Z = 150.0
MIN_FLAT_AREA = 6.0                      # m2 of level (normal z > 0.995) collision for a "large flat object"
NATIVE = ("fo4-native", "fo4-none", "passable-door")
DATA_TREES = ("meshes", "geometries", "materials", "textures")

# The runner (scripts/game/testqueue.py judge, kind terrain, claude/test-queue 7319c39) fails a terrain test only
# when a height is more than TOLERANCE off, after taking the Z offset from the z_ref probe. A judged object point must
# therefore stand at least MIN_DISCRIMINATION above every terrain sample under its landing disc: without the object
# the player lands on the terrain and the error is at least that much (2 x the tolerance).
TOLERANCE = 0.5
MIN_DISCRIMINATION = 1.0
# Judged terrain points: no collision standing more than 0.1 m above the terrain within 1.0 m (the capsule radius is
# unresolved; exp2c's first plan used 0.6 m and kept flat_2, which has a 0.64 m top 0.6 to 1.0 m away).
TERRAIN_CLEAR_RADII = (0.15, 0.3, 0.45, 0.6, 0.8, 1.0)
# The Z reference probe of every entry (plan key z_ref): open terrain near the arrival, see reference_point().
REF_LABEL = "zref_ground"
REF_CLEAR = 1.5                          # m: no collision above the terrain (or reaching into a 3 m column) this close
REF_SEARCH = 40.0                        # m around the arrival
CAPSULE = (0.4, 1.8)                     # assumed player cylinder (radius, height) for the teleport path check
# Keys the runner's plan_terrain reads from a plan.json entry (claude/test-queue 7319c39). Every key of exp2b's entry
# is carried into each exp2c entry unless exp2c sets it itself (ENTRY_OWN), so a key the runner learns later (as z_ref
# was, after exp2c was first staged) cannot be dropped silently: validate_plan() names any difference.
RUNNER_KEYS = ("coc", "travel", "label", "anchor", "spawn_local", "drop_above_spawn", "settle_ms", "z_ref", "drop_z",
               "points", "beyond", "hop_m", "hop_wait_ms")
ENTRY_OWN = ("label", "points", "drop_z", "z_ref", "spawn_local")
POINT_KEYS = ("label", "x", "y", "expect")


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save(path, value, indent=1):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=indent)
    os.replace(tmp, path)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------------------- select
def cmd_select(a):
    export = load(a.export)
    sub, skipped = exterior.select(export)
    save(os.path.join(a.work, "convert_input.json"), sub)
    models = sorted({exterior.source_key(r["model"]) for r in sub["refs"]})
    rep = {"export": os.path.abspath(a.export), "refs": len(export["refs"]), "deferred": len(export.get("deferred_refs", [])),
           "to_convert": len(sub["refs"]), "models": len(models), "skipped": len(skipped),
           "skip_reasons": exterior.reason_counts(skipped), "convert_types": list(exterior.CONVERT_TYPES),
           "skipped_refs": skipped}
    save(os.path.join(a.work, "selection.json"), rep)
    print(f"{rep['refs']} references + {rep['deferred']} deferred: convert {rep['to_convert']} ({rep['models']} models), "
          f"skip {rep['skipped']}: {rep['skip_reasons']}")
    print("convert_batch --types " + ",".join(exterior.CONVERT_TYPES))
    return 0


# ------------------------------------------------------------------------------------------------------------- world
class World:
    """Placed objects with their converted collision, the decoded BTD and the queries the plan needs."""

    def __init__(self, data_dir, bases, placed, btd_path):
        self.bases, self.placed = bases, placed
        self.model_tris, self.collision_errors = {}, {}
        for i, b in enumerate(bases):
            try:
                with open(os.path.join(data_dir, "meshes", b["model"]), "rb") as f:
                    bodies = sfbodies.nif_bodies(f.read())
                self.model_tris[i] = np.array([t for body in bodies for t in body["triangles"]], np.float64).reshape(-1, 3, 3)
            except (OSError, ValueError, struct.error) as e:
                self.collision_errors[b["model"]] = f"{type(e).__name__}: {e}"
        self.tris, self.owners = exterior.world_triangles(self.model_tris, placed)
        self.index = exterior.SurfaceIndex(self.tris, self.owners)
        with open(btd_path, "rb") as f:
            t = btd.read(f.read())
        self.heights, self.n = t.heights_m(), t.ncx
        self.step = (t.hmax - t.hmin) / 65535.0
        self.hmin = t.hmin
        self.origin = tg.grid_origin(self.n)
        self.by_src = {p["src"]: k for k, p in enumerate(placed)}

    def ground(self, x, y):
        return tg.point_interp(self.heights, self.origin, self.origin, tg.SF_STEP_M, x, y)["bilinear"]

    def ground_all(self, x, y):
        return tg.point_interp(self.heights, self.origin, self.origin, tg.SF_STEP_M, x, y)

    def landing(self, x, y, drop_z):
        return exterior.landing(self.index.top, self.ground, x, y, drop_z)

    def bounds(self, k, local=None):
        """xy AABB (x0, y0, x1, y1) of placed object k's collision, or of a rectangle in its own frame."""
        p = self.placed[k]
        if local is not None:
            x0, y0, x1, y1 = local
            pts = [exterior.to_world((x, y, 0), p["pos"], p["rot"], p["scale"]) for x in (x0, x1) for y in (y0, y1)]
        else:
            pts = self.tris[self.owners == k].reshape(-1, 3)
        pts = np.asarray(pts)
        return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())

    def describe(self, k):
        if k is None:
            return None
        p, b = self.placed[k], self.bases[self.placed[k]["base"]]
        return {"src": p["src"], "edid": b["edid"], "model": b["model"], "pos": p["pos"], "rot": p["rot"],
                "scale": p["scale"], "collision": b.get("collision")}

    def level_area(self):
        """Per placed object: area (m2) of its level (normal z > 0.995) world collision triangles."""
        if not len(self.tris):
            return np.zeros(len(self.placed))
        u, w = self.tris[:, 1] - self.tris[:, 0], self.tris[:, 2] - self.tris[:, 0]
        n = np.cross(u, w)
        ln = np.linalg.norm(n, axis=1)
        level = n[:, 2] / np.maximum(ln, 1e-12) > 0.995
        return np.bincount(self.owners[level], weights=ln[level] / 2, minlength=len(self.placed))


def terrain_points(world, points, drop_z, radii=TERRAIN_CLEAR_RADII):
    """exp2b's terrain points re-judged with the objects in place:
    terrain              no object stands more than 0.1 m above the terrain within radii[-1] (1.0 m): expect unchanged
    terrain_covered      a placed object's collision is above the terrain at the point: expect = that surface
    terrain_near_object  the point is terrain but an object within radii[-1] may catch the dropped player: expect
                         unchanged, the reading is informational
    The original terrain expectation is kept as terrain_expect."""
    out = []
    for p in points:
        land = world.landing(p["x"], p["y"], drop_z)
        near = exterior.nearby_object(world.index.top, world.ground, p["x"], p["y"], drop_z, radii=radii)
        q = {"label": p["label"], "x": p["x"], "y": p["y"], "kind": "terrain", "expect": p["expect"],
             "terrain_expect": p["expect"], "landing": landing_json(world, land),
             "nearby_object": None if near is None else {"distance": near["distance"], "height": round(near["height"], 4),
                                                         "owner": world.describe(near["owner"])}}
        if land["on_object"]:
            q.update(kind="terrain_covered", expect=round(land["centre"], 4), owner=world.describe(land["owner"]))
        elif near is not None:
            q.update(kind="terrain_near_object", owner=world.describe(near["owner"]))
        out.append(q)
    return out


def landing_json(world, land):
    return {"centre": round(land["centre"], 4), "max": round(land["z"], 4), "spread": round(land["spread"], 4),
            "ground": round(land["ground"], 4), "on_object": land["on_object"], "all_on_object": land["all_on_object"],
            "owners": [world.placed[k]["src"] for k in land["owners"]]}


def discrimination(world, x, y, expect, radius=0.6):
    """How far the expected landing stands above the highest terrain sample under the landing disc: the least error
    the runner would see if the object were missing and the player landed on the terrain instead."""
    return expect - max(world.ground(x + dx, y + dy) for dx, dy in exterior.disc_offsets(radius))


def object_point(world, k, label, kind, drop_z, bounds=None, need_clearance=0.0, count=1):
    picks = exterior.pick_points(world.index, world.ground, k, bounds or world.bounds(k), drop_z, count=count,
                                 need_clearance=need_clearance)
    out = []
    for i, (x, y, land, free) in enumerate(picks):
        out.append({"label": label if count == 1 else f"{label}_{i + 1}", "x": round(x, 4), "y": round(y, 4),
                    "kind": kind, "expect": round(land["centre"], 4), "landing": landing_json(world, land),
                    "above_terrain": round(land["centre"] - land["ground"], 4),
                    "discrimination": round(discrimination(world, x, y, land["centre"]), 4),
                    "clearance": None if math.isinf(free) else round(free, 4), "owner": world.describe(k)})
    return out


def object_class(disc):
    """elevated (>= 3 m above the terrain under the disc), raised (>= MIN_DISCRIMINATION) or ground (less: the runner's
    verdict cannot tell the object from the terrain, readings are informational)."""
    return "elevated" if disc >= 3.0 else "raised" if disc >= MIN_DISCRIMINATION else "ground"


def large_flat_objects(world, exclude, want=None):
    """The biggest level tops (sampled on a 1 m grid, exposed to a drop from DROP_Z) among plain statics with FO4's
    own collision, upright (|rot x|, |rot y| < 0.02 rad) and enabled, each a different model, by object_class():
    `want` = {"elevated": 1, "raised": 1, "ground": 2} by default. Only elevated and raised ones discriminate."""
    want = dict(want or {"elevated": 1, "raised": 1, "ground": 2})
    area = world.level_area()
    scored = []
    for k in np.argsort(-area):
        k = int(k)
        p, b = world.placed[k], world.bases[world.placed[k]["base"]]
        if area[k] < MIN_FLAT_AREA:
            break
        if (p["src"] in exclude or p["disabled"] or b.get("collision") != "fo4-native" or abs(p["rot"][0]) >= 0.02
                or abs(p["rot"][1]) >= 0.02 or b["model"].lower().startswith(("fo4cw\\scol\\", "fo4cw/scol/"))):
            continue
        n = len(exterior.flat_samples(world.index, world.ground, k, world.bounds(k), DROP_Z, step=1.0))
        if n:
            scored.append((-n, p["src"], k))
    scored.sort()
    chosen, models = [], set()
    for _, src, k in scored:
        b = world.bases[world.placed[k]["base"]]
        if b["model"] in models:
            continue
        pts = object_point(world, k, "", "object_top", DROP_Z)
        if not pts:
            continue
        cls = object_class(pts[0]["discrimination"])
        if want.get(cls, 0) == 0:
            continue
        want[cls] -= 1
        models.add(b["model"])
        stem = b["edid"][len(EDID_PREFIX):].lower()
        word = {"elevated": "roof", "raised": "top", "ground": "flat"}[cls]
        pts[0]["label"] = f"{word}_{stem}"[:40]
        pts[0]["object_class"] = cls
        chosen.append(pts[0])
        if not any(want.values()):
            break
    return chosen


# ------------------------------------------------------------------------------------------------- z reference, paths
def reference_ok(world, x, y, max_ground=math.inf, clear=REF_CLEAR):
    """Can (x, y) serve as the entry's Z reference probe (z_ref)? Level terrain (the three interpolation rules within
    one quantisation step, at most 0.02 m spread over the 0.6 m disc), no collision surface above the terrain within
    `clear` (dense rings), no triangle reaching into a 3 m column of radius `clear` (walls) and terrain at most
    max_ground (a low drop must start above it). Returns the terrain height or None."""
    hs = world.ground_all(x, y)
    g = hs["bilinear"]
    if g > max_ground or max(hs.values()) - min(hs.values()) > world.step:
        return None
    disc = [world.ground(x + dx, y + dy) for dx, dy in exterior.disc_offsets(0.6)]
    if max(disc) - min(disc) > 0.02:
        return None
    for dx, dy in exterior.disc_offsets(clear, rings=6, per_ring=24):
        gg = world.ground(x + dx, y + dy)
        if any(z > gg - 0.05 for z, _ in world.index.surfaces(x + dx, y + dy)):
            return None
    if exterior.capsule_hits(world.index, world.ground, x, y, g + 0.02, radius=clear, height=3.0):
        return None
    return g


def reference_point(world, centre, accept=None, max_ground=math.inf, search=REF_SEARCH, step=1.0):
    """The open, level terrain point closest to `centre` (x, y) that passes reference_ok() and accept(x, y, ground)
    (e.g. a clear teleport path in the low-drop entry). Returns a terrain-kind plan point or None."""
    cx, cy = centre
    n = int(search / step)
    cands = sorted(((i * step) ** 2 + (j * step) ** 2, cx + i * step, cy + j * step)
                   for i in range(-n, n + 1) for j in range(-n, n + 1) if (i * i + j * j) * step * step <= search * search)
    for _, x, y in cands:
        x, y = round(x, 4), round(y, 4)
        g = reference_ok(world, x, y, max_ground)
        if g is None or (accept is not None and not accept(x, y, g)):
            continue
        hs = world.ground_all(x, y)
        return {"label": REF_LABEL, "x": x, "y": y, "kind": "terrain_ref", "expect": round(g, 4), "terrain_expect": round(g, 4),
                "interpolations": {m: round(v, 5) for m, v in hs.items()}, "clear_radius": REF_CLEAR,
                "landing": landing_json(world, world.landing(x, y, DROP_Z)), "nearby_object": None,
                "distance_from_arrival": round(math.hypot(x - cx, y - cy), 3)}
    return None


def path_report(world, start, points, drop_z, capsule=CAPSULE):
    """The runner's teleports through an entry (setpos x, y, z from where the player stands, then the drop; the
    player is assumed to stand at each point's expected landing before the next) and what each position would overlap
    with the assumed capsule: [{"to", "positions": [[x, y, z, [hits]]]}]. Also returns whether every position is clear."""
    out, ok, cur = [], True, tuple(start)
    for p in points:
        steps = []
        for x, y, z in exterior.setpos_path(cur, (p["x"], p["y"]), drop_z):
            hits = exterior.capsule_hits(world.index, world.ground, x, y, z, radius=capsule[0], height=capsule[1])
            ok = ok and not hits
            steps.append([round(x, 4), round(y, 4), round(z, 4), [world.placed[h]["src"] if isinstance(h, int) else h
                                                                  for h in hits]])
        out.append({"to": p["label"], "positions": steps})
        cur = (p["x"], p["y"], p["expect"])
    return out, ok


def position_cost(hits):
    """0 for a clear teleport position, 1 when only terrain overlaps (probably harmless: the vanilla LC172World run
    moved the player between 8 probes on real relief and read every probe at its x and y), 10 when a placed object
    does (no evidence yet whether setpos resolves that)."""
    return 0 if not hits else 10 if any(h != "terrain" for h in hits) else 1


def order_points(world, start, points, drop_z, capsule=CAPSULE, exhaustive=7):
    """The order of an entry's points whose teleport positions (path_report) cost least (position_cost), every order
    for up to `exhaustive` points, else greedily; ties keep the given order. The z_ref probe may go anywhere: the
    runner finds it by its label."""
    n = len(points)
    if n < 2:
        return list(points)
    nodes = [tuple(start)] + [(p["x"], p["y"], p["expect"]) for p in points]

    def leg(i, j):
        return sum(position_cost(exterior.capsule_hits(world.index, world.ground, x, y, z, radius=capsule[0],
                                                       height=capsule[1]))
                   for x, y, z in exterior.setpos_path(nodes[i], (points[j]["x"], points[j]["y"]), drop_z))
    cost = [[leg(i, j) if i != j + 1 else 0 for j in range(n)] for i in range(n + 1)]
    if n <= exhaustive:
        def total(perm):
            return cost[0][perm[0]] + sum(cost[perm[k] + 1][perm[k + 1]] for k in range(n - 1))
        best = min(itertools.permutations(range(n)), key=lambda perm: (total(perm), perm))
    else:
        best, cur, left = [], 0, list(range(n))
        while left:
            j = min(left, key=lambda j: (cost[cur][j], j))
            best.append(j)
            left.remove(j)
            cur = j + 1
    return [points[k] for k in best]


# ------------------------------------------------------------------------------------------------------------- plan
def plan_entry(base, label, drop_z, points, z_ref, spawn_local):
    """One runner entry: every key of exp2b's entry `base` except the ones exp2c sets (ENTRY_OWN), then exp2c's."""
    if base.get("drop_above_spawn"):
        raise ValueError("the base entry drops relative to the arrival (drop_above_spawn); exp2c's drop heights are "
                         "drop_z in the worldspace frame: decide which before staging")
    e = {k: v for k, v in base.items() if k not in ENTRY_OWN}
    e.update(label=label, drop_z=drop_z, spawn_local=spawn_local, z_ref=z_ref,
             points=[{k: p[k] for k in POINT_KEYS} for p in points])
    return e


def validate_plan(plan, base, kinds):
    """Problems (empty = none) of plan entries against the runner's keys and exp2b's entry: an unknown key, a key of
    `base` not carried, a z_ref that names no terrain_ref point of its own entry, duplicate labels, a point with keys
    other than label / x / y / expect. kinds[(entry index, label)] = the point's kind."""
    problems = []
    for i, e in enumerate(plan):
        tag = f"entry {i + 1}"
        for k in e:
            if k not in RUNNER_KEYS:
                problems.append(f"{tag}: key {k!r} is not read by the runner")
        for k, v in base.items():
            if k not in ENTRY_OWN and e.get(k) != v:
                problems.append(f"{tag}: exp2b key {k!r} not carried")
        labels = [p["label"] for p in e.get("points", [])]
        if len(set(labels)) != len(labels):
            problems.append(f"{tag}: duplicate point labels")
        if not e.get("z_ref"):
            problems.append(f"{tag}: no z_ref (the runner then takes the Z offset from the anchor or the arrival)")
        elif e["z_ref"] not in labels:
            problems.append(f"{tag}: z_ref {e['z_ref']!r} is not one of its points")
        elif kinds.get((i, e["z_ref"])) != "terrain_ref":
            problems.append(f"{tag}: z_ref {e['z_ref']!r} is a {kinds.get((i, e['z_ref']))} point, not the terrain reference")
        for p in e.get("points", []):
            if tuple(sorted(p)) != tuple(sorted(POINT_KEYS)):
                problems.append(f"{tag}: point {p.get('label')} has keys {sorted(p)}")
    return problems


def judge_heights(points, reads, z_ref, tolerance=TOLERANCE):
    """The runner's height verdict for one terrain test (scripts/game/testqueue.py judge, claude/test-queue 7319c39)
    on reads in the worldspace's own frame: oz = read(z_ref) - expect(z_ref), worst = max |read - oz - expect|,
    FAIL above the tolerance. Returns (verdict, worst, z offset)."""
    oz = 0.0
    for p, r in zip(points, reads):
        if p["label"] == z_ref:
            oz = r - p["expect"]
    worst = max(abs(r - oz - p["expect"]) for p, r in zip(points, reads))
    return ("FAIL" if worst > tolerance else "PASS"), worst, oz


def scenario_reads(world, entry, meta, scenario):
    """Predicted getpos z of every point of a plan entry (worldspace frame) when
    no_objects     no placed object loads: every drop lands on the terrain (highest terrain sample under the disc)
    flat_terrain   the BTD relief is missing (exp2b 2026-10-11: z = -116.00, its minimum, everywhere): terrain points
                   read one constant (the BTD minimum here), objects keep their absolute height"""
    reads = []
    for p in entry["points"]:
        m = meta[p["label"]]
        on_terrain = m["kind"] in ("terrain", "terrain_ref", "terrain_near_object")
        if scenario == "no_objects":
            reads.append(p["expect"] if on_terrain else
                         max(world.ground(p["x"] + dx, p["y"] + dy) for dx, dy in exterior.disc_offsets(0.6)))
        elif scenario == "flat_terrain":
            reads.append(world.hmin if on_terrain else p["expect"])
        else:
            raise ValueError(scenario)
    return reads


# ------------------------------------------------------------------------------------------------------------- stage
def copy_tree(src, dst):
    """Copy src into dst; files already there with the same size and a newer or equal mtime are kept."""
    copied = kept = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for fn in files:
            s, d = os.path.join(root, fn), os.path.join(dst, rel, fn)
            if os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s) and os.path.getmtime(d) >= os.path.getmtime(s):
                kept += 1
                continue
            shutil.copy2(s, d)
            copied += 1
    return copied, kept


def collision_kind(item):
    if "door" in item:
        return "rigged-door-box"
    src = (item.get("collision_report") or {}).get("source")
    return src if src in NATIVE else "guessed-boxes" if (item.get("collision_report") or {}).get("boxes") else "none"


def cmd_stage(a):
    b2 = a.exp2b
    prm = load(os.path.join(b2, "exp2_params.json"))
    plan_b = load(os.path.join(b2, "plan.json"))
    sel = load(os.path.join(a.work, "convert_input.json"))
    selrep = load(os.path.join(a.work, "selection.json"))
    man = load(os.path.join(a.work, "convert", "manifest.json"))
    bases, placed, skipped_conv = exterior.place(sel, man, prm["cell_min"], prm["cell_max"], EDID_PREFIX)
    items = {i["source"].replace("/", "\\").lower(): i for i in man["items"]}
    for b in bases:
        b["collision"] = collision_kind(items[b["key"]])
    skipped = selrep["skipped_refs"] + skipped_conv
    total = selrep["refs"] + selrep["deferred"]
    if len(placed) + len(skipped) != total:
        sys.exit(f"accounting: {len(placed)} placed + {len(skipped)} skipped != {total} exported")

    out = a.out
    os.makedirs(out, exist_ok=True)
    base_files = copy_base_data(b2, out)                              # BTD, mask and any other terrain file of the base
    for tree in DATA_TREES:
        c, k = copy_tree(os.path.join(a.work, "convert", tree), os.path.join(out, "Data", tree))
        print(f"Data\\{tree}: {c} copied, {k} up to date")

    objects = {"edid_prefix": EDID_PREFIX,
               "bases": [{k: b[k] for k in ("edid", "model", "door", "source", "collision") if k in b} for b in bases],
               "refs": [{k: p[k] for k in ("src", "base", "cell", "pos", "rot", "scale", "disabled")} for p in placed]}
    save(os.path.join(out, "objects.json"), objects, indent=None)
    save(os.path.join(out, "exp2_params.json"), dict(prm, objects="objects.json"))
    save(os.path.join(out, "skipped.json"), {"counts": exterior.reason_counts(skipped), "refs": skipped})

    world = World(os.path.join(out, "Data"), bases, placed, os.path.join(out, *prm["btd_file"].split("/")))
    if world.collision_errors:
        sys.exit(f"converted collision unreadable: {world.collision_errors}")
    print(f"{len(bases)} bases, {len(placed)} references, {len(world.tris):,} collision triangles")

    e1 = plan_b[0]
    plan, expected = build_plan(world, prm, e1)
    save(os.path.join(out, "plan.json"), plan)

    # the plugin: TerrainExp2 with objects.json (terrain records keep exp2b's FormIDs; the Mars plugin is rebuilt)
    if a.sf_esm:
        subprocess.run(["dotnet", "run", "--project", os.path.join(REPO, "dotnet", "TerrainExp2"), "-c", "Release", "--",
                        a.sf_esm, out], check=True)
    ids = load(os.path.join(out, "formids.json")) if os.path.exists(os.path.join(out, "formids.json")) else None
    for p in expected["points"]:
        for o in (p.get("owner"), (p.get("nearby_object") or {}).get("owner")):
            if o and ids:
                o["refr"] = overlay_records.ANCHOR_LOAD_BYTE + ids["refs"][o["src"]]
    expected = dict({
        "experiment": "terrain_exp2c", "base": os.path.abspath(b2), "base_files": base_files,
        "prerequisite": PREREQUISITE,
        "hypothesis": "FO4 position / 70 = worldspace position in metres for terrain (H) and objects alike; an object's "
                      "collision then sits on the BTD as in FO4",
        "objects": {"exported": total, "placed": len(placed), "bases": len(bases),
                    "doors": sum(1 for b in bases if "door" in b), "initially_disabled": sum(p["disabled"] for p in placed),
                    "fo4_persistent_placed_temporary": sum(p["fo4_persistent"] for p in placed),
                    "enable_parent_not_translated": sum(p["enable_parent"] for p in placed),
                    "collision": {k: sum(1 for p in placed if bases[p["base"]]["collision"] == k)
                                  for k in sorted({b["collision"] for b in bases})},
                    "skipped": exterior.reason_counts(skipped)}}, **expected)
    save(os.path.join(out, "expected.json"), expected)
    readme(out, prm, plan, expected)
    for i, e in enumerate(plan):
        d = expected["entries"][i]
        print(f"entry {i + 1} ({d['role']}): {len(e['points'])} points from {e['drop_z']} m, z_ref {e['z_ref']}, "
              f"predicted {d['predicted']}, teleports clear {d['teleports_clear']}")
    print(f"spawn_local {expected['spawn']['spawn_local']}; dropped {[p['label'] for p in expected['dropped_points']]}")
    return 0


PREREQUISITE = ("Queue exp2c only after a run of the same terrain (exp2b family: same BTD, mask, records) has read the "
                "BTD relief in game. exp2b attempt 1 (2026-10-11 16:46) read z = -116.00, the BTD minimum, at the "
                "arrival and all 14 probes (flat ground), and its persistent anchor read its unmerged local position. "
                "Until the terrain is right, entry 1 fails and entries 2 to 4 cannot be read as alignment checks.")
ROLES = ("terrain gate", "objects", "informational: shop floor", "informational")
# predicted verdicts per entry: flat_terrain only for the terrain gate, whose points are all terrain (elsewhere it would
# depend on where the objects sit when the relief is missing, which nobody knows)
SCENARIOS = (("no_objects", "flat_terrain"), ("no_objects",), ("no_objects",), ("no_objects",))


def copy_base_data(b2, out):
    """Copy every file under the base experiment's Data folder (BTD, overlay mask, and e.g. exp2b2's second BTD copy
    under meshes\\terrain) into out\\Data; returns their paths relative to the folder ("Data/...")."""
    files = []
    for root, _dirs, names in os.walk(os.path.join(b2, "Data")):
        for fn in sorted(names):
            s = os.path.join(root, fn)
            rel = os.path.relpath(s, b2).replace("\\", "/")
            d = os.path.join(out, *rel.split("/"))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if not (os.path.exists(d) and sha256(d) == sha256(s)):
                shutil.copy2(s, d)
            files.append(rel)
    return sorted(files)


def object_area(placed, cell_m=100.0):
    """(x0, y0, x1, y1) metres of the Starfield cells that hold placed objects."""
    xs = [p["cell"][0] for p in placed]
    ys = [p["cell"][1] for p in placed]
    return min(xs) * cell_m, min(ys) * cell_m, (max(xs) + 1) * cell_m, (max(ys) + 1) * cell_m


def floor_route(world, start, cands, drop_z):
    """Two floor candidates, in an order whose teleports (from the arrival `start`) never overlap collision."""
    for i in range(len(cands)):
        for j in range(len(cands)):
            if i == j:
                continue
            order = [cands[i], cands[j]]
            if path_report(world, start, order, drop_z)[1]:
                return order
    return None


def build_plan(world, prm, e1):
    """The four runner entries and expected.json's point metadata. Every entry starts with (or, in the floor entry,
    may end with) the terrain reference probe REF_LABEL and names it as z_ref, so heights are judged against terrain
    read in the same test, whatever the arrival or the anchor read:
    1 terrain gate  exp2b's terrain points inside the object cells and clear of objects within 1.0 m: the BTD relief
                    (a flat ground fails it)
    2 objects       object tops at least MIN_DISCRIMINATION above the terrain (without the objects the entry fails)
    3 shop floor    informational: the floor is 0.14 m above the terrain, below the runner's 0.5 m tolerance, so the
                    verdict passes with or without the floor; compare the readings with the reference
    4 informational exp2b points now on or near an object, ground-level flat objects (also below the tolerance)"""
    placed = world.placed
    spawn = prm["spawn"]
    land_spawn = world.landing(spawn[0], spawn[1], spawn[2])
    spawn_local = [e1["spawn_local"][0], e1["spawn_local"][1], round(land_spawn["centre"], 4)]
    start = (spawn[0], spawn[1], land_spawn["centre"])

    x0, y0, x1, y1 = object_area(placed)
    terr = terrain_points(world, e1["points"], e1["drop_z"])
    inside = [p for p in terr if x0 <= p["x"] < x1 and y0 <= p["y"] < y1]
    dropped = [dict(p, reason=f"outside the object cells x {x0:.0f}..{x1:.0f}, y {y0:.0f}..{y1:.0f} m: exp2b's "
                              "terrain question (resampled_sw MOVED 141.9 m in exp2b attempt 1)")
               for p in terr if p not in inside]
    pts_terrain = [p for p in inside if p["kind"] == "terrain"]
    pts_info = [p for p in inside if p["kind"] != "terrain"]

    shop = world.by_src[SHOP]
    roof = object_point(world, shop, "redrocket_roof", "object_top", DROP_Z)
    for p in roof:
        p["object_class"] = object_class(p["discrimination"])
    tops = roof + large_flat_objects(world, exclude={BUILDING, SHOP})
    pts_obj = [p for p in tops if p["object_class"] != "ground"]
    pts_info += [p for p in tops if p["object_class"] == "ground"]

    # the shop floor (RedRExt_Workshop02), under its ceiling, dropped from floor + FLOOR_DROP
    shop_bounds = world.bounds(world.by_src[BUILDING], local=SHOP_LOCAL)
    floor = [z for _x, _y, z in exterior.flat_samples(world.index, world.ground, shop, shop_bounds,
                                                      placed[shop]["pos"][2] + 1.0)]
    floor_z = statistics.median(floor)
    drop_low = round(floor_z + FLOOR_DROP, 2)
    cands = object_point(world, shop, "redrocket_floor", "floor", drop_low, bounds=shop_bounds,
                         need_clearance=FLOOR_DROP + PLAYER_HEIGHT, count=6)
    pts_floor = floor_route(world, start, cands, drop_low)
    if not pts_floor:
        sys.exit("no two floor points inside the shop with a clear teleport path from the arrival")
    for i, p in enumerate(pts_floor):
        p["label"] = f"redrocket_floor_{i + 1}"

    # the Z reference: open level terrain near the arrival, also reachable by the low floor drop (before or after the
    # floor points), so one probe serves all four entries
    route = {}

    def accept(x, y, g):
        ref = {"label": REF_LABEL, "x": x, "y": y, "expect": g}
        for order in ([ref] + pts_floor, pts_floor + [ref]):
            if path_report(world, start, order, drop_low)[1]:
                route["first"] = order[0] is ref
                return True
        return False

    ref = reference_point(world, (spawn[0], spawn[1]), accept=accept, max_ground=drop_low - 0.5)
    if ref is None:
        sys.exit(f"no terrain reference within {REF_SEARCH} m of the arrival")
    floor_entry = [ref] + pts_floor if route["first"] else pts_floor + [ref]

    drops = [e1["drop_z"], DROP_Z, drop_low, e1["drop_z"]]
    # the 150 m entries visit their points in the order whose teleport positions overlap the least collision (the
    # floor entry is already built clear)
    groups = [order_points(world, start, [ref] + pts_terrain, drops[0]),
              order_points(world, start, [ref] + pts_obj, drops[1]),
              floor_entry,
              order_points(world, start, [ref] + pts_info, drops[3])]
    labels = [
        "terrain exp2c 1/4 (terrain gate): exp2b terrain points near Red Rocket clear of objects within 1 m, heights "
        f"relative to {REF_LABEL} (a flat ground fails)",
        f"terrain exp2c 2/4 (objects): FO4 object tops >= {MIN_DISCRIMINATION} m above the terrain (Red Rocket roof, "
        f"large flat tops), relative to {REF_LABEL} (fails if the objects are missing)",
        "terrain exp2c 3/4 (informational: the shop floor is 0.14 m above the terrain, under the 0.5 m tolerance): "
        f"dropped from {drop_low} m under the shop ceiling; compare the floor readings with {REF_LABEL}",
        "terrain exp2c 4/4 (informational): exp2b points now on or near an object and ground-level flat objects "
        f"(< {MIN_DISCRIMINATION} m above the terrain)",
    ]
    plan = [plan_entry(e1, lab, dz, pts, REF_LABEL, spawn_local) for lab, dz, pts in zip(labels, drops, groups)]
    kinds = {(i, p["label"]): p["kind"] for i, g in enumerate(groups) for p in g}
    problems = validate_plan(plan, e1, kinds)
    if problems:
        sys.exit("plan: " + "; ".join(problems))

    entries = []
    for i, (e, g) in enumerate(zip(plan, groups)):
        meta = {p["label"]: p for p in g}
        pred = {}
        for sc in SCENARIOS[i]:
            v, worst, _ = judge_heights(e["points"], scenario_reads(world, e, meta, sc), e["z_ref"])
            pred[sc] = {"verdict": v, "worst_m": round(worst, 3)}
        paths, clear = path_report(world, start, e["points"], e["drop_z"])
        entries.append({"label": e["label"], "role": ROLES[i], "drop_z": e["drop_z"], "z_ref": e["z_ref"],
                        "predicted": pred, "teleports_clear": clear, "teleports": paths})
    return plan, {
        "spawn": {"marker": spawn, "landing": landing_json(world, land_spawn), "spawn_local": spawn_local,
                  "exp2b_spawn_local": e1["spawn_local"]},
        "reference": ref,
        "floor": {"owner": SHOP, "samples": len(floor), "median_z": round(floor_z, 4), "min_z": round(min(floor), 4),
                  "max_z": round(max(floor), 4), "drop_z": drop_low,
                  "terrain_under_floor_points": [round(world.ground(p["x"], p["y"]), 4) for p in pts_floor]},
        "entries": entries,
        "points": [dict(p, entry=i) for i, g in enumerate(groups) for p in g],
        "dropped_points": dropped,
    }


def readme(out, prm, plan, exp):
    base = os.path.splitext(prm["plugin"])[0]
    pl = [prm["plugin"], prm["mars"]["plugin"]]
    o = exp["objects"]
    ref = exp["reference"]
    lines = [
        "Terrain experiment 2c (Claude, 2026-10-11). NOT deployed, NOT queued. Recipe: docs/terrain/experiment2c.md",
        f"(branch claude/terrain-exterior-statics). Base: {exp['base']} (same BTD, mask, Location, Mars registration,",
        f"anchor and FormIDs; its Data files: {', '.join(exp['base_files'])}) plus the real Fallout 4 objects of",
        f"cells x -20..-15, y 16..21 around Red Rocket: {o['placed']:,} references of {o['bases']:,} converted models",
        f"(STAT, {o['doors']} rigged DOOR) at FO4 position / 70, in one plugin; nothing depends on FO4Port.esm.",
        "Skipped references and why: skipped.json.",
        "",
        "PREREQUISITE: " + exp["prerequisite"],
        "",
        "Install (game closed). The runner does it:",
        f"  scripts/game/exp_install.py install --exp-dir <this folder> --starfield <game> --plugins {','.join(pl)} --pack",
        f"  --pack puts the folders under Data\\ into \"{base} - Main.ba2\" (General). BTD storage: every vanilla terrain",
        "  archive stores its BTDs uncompressed, and exp2b's zlib-packed BTD read its minimum everywhere (another track's",
        "  finding, supported hypothesis): pack .btd files with Archive2 -compression=None.",
        "  TEXTURES: Data\\textures\\fo4cw holds the converted DDS textures; Starfield reads textures from a DDS-format",
        f"  archive (\"{base} - Textures.ba2\", as FO4Port - Textures.ba2). The installer on claude/runner-npc-nav",
        "  (PR #68) builds that archive; the one on claude/test-queue puts them into the General archive, where the",
        "  objects may show untextured. Positions and collision do not depend on textures.",
        "By hand: build the BA2(s) with Archive2 from Data\\ (root = Data), copy them and the esm files to Starfield\\Data",
        "and add to Plugins.txt, in this order, before FO4Port.esm:  " + "  ".join("*" + p for p in pl),
        "",
        f"In game (test save), console: tgm, then for each entry below: coc {plan[0]['coc']}; the arrival",
        f"(player.getpos right after coc, settled) -> S, offset O = S - spawn_local {plan[0]['spawn_local']}: the player",
        "falls from the COC marker (2 m up) onto the pump island under the canopy, 0.117 m above the terrain. Only the x",
        f"and y of O are trusted (whole cells). The persistent anchor (prid {plan[0]['anchor']['ref']}) read its unmerged",
        "local position in exp1d and exp2b, so the runner falls back to the arrival. For every point: player.setpos x",
        "<x + O.x>, player.setpos y <y + O.y>, player.setpos z <drop_z + O.z>, wait 8 s, player.getpos z -> R.",
        f"Heights are relative to the entry's z_ref probe {REF_LABEL} (open level terrain {ref['distance_from_arrival']} m",
        f"from the arrival, nothing above the terrain within {REF_CLEAR} m): Z = R(point) - R({REF_LABEL}) +",
        f"{ref['expect']}; PASS when every Z is within {TOLERANCE} m of expect.",
    ]
    meta = {(q["entry"], q["label"]): q for q in exp["points"]}
    for i, e in enumerate(plan):
        d = exp["entries"][i]
        pr = d["predicted"]
        lines += ["", f"  {e['label']}", f"  drop_z {e['drop_z']}, z_ref {e['z_ref']}; predicted verdict without the "
                  f"objects: {pr['no_objects']['verdict']} (worst {pr['no_objects']['worst_m']} m)" +
                  (f", on flat terrain: {pr['flat_terrain']['verdict']} (worst {pr['flat_terrain']['worst_m']} m)"
                   if "flat_terrain" in pr else "")]
        for p in e["points"]:
            m = meta[(i, p["label"])]
            owner = (m.get("owner") or {}).get("edid", "")
            near = m.get("nearby_object") or {}
            what = {"terrain": "terrain", "terrain_ref": "terrain, the Z reference",
                    "terrain_covered": "exp2b terrain point now on " + owner,
                    "terrain_near_object": f"terrain, {owner} {near.get('height', 0):.2f} m high at {near.get('distance')} m",
                    "object_top": f"top of {owner}, {m.get('discrimination', 0):.2f} m above the terrain",
                    "floor": f"shop floor {owner}, {m.get('discrimination', 0):.2f} m above the terrain"}[m["kind"]]
            lines.append(f"    {p['label']:<34} x {p['x']:>10.4f}  y {p['y']:>10.4f}  -> {p['expect']:.4f}   {what}")
    lines += [
        "",
        "Files: " + ", ".join(pl) + ", " + ", ".join(f.replace("/", "\\") for f in exp["base_files"]) + ",",
        "Data\\meshes\\fo4cw, Data\\geometries, Data\\materials\\fo4cw, Data\\textures\\fo4cw, objects.json (what TerrainExp2",
        "placed), formids.json, skipped.json, plan.json (runner input, worldspace's own frame), expected.json (every point",
        "with its owner and landing, predicted verdicts, teleport paths), offline_check.json (make_exp2c.py check). Never",
        "install together with experiment 1 or 2b (same plugin names / MarsPlanetData override). Uninstall:",
        "exp_install.py uninstall.",
    ]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ------------------------------------------------------------------------------------------------------------- check
def fo4_ground(esm, placed, cells):
    """FO4's own terrain height (FO4 LAND, bilinear on the merged vertex grid) under every placed origin, metres."""
    x0, x1, y0, y1 = cells
    wanted = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    with fo4land.Plugin(esm) as p:
        world = p.read_world("Commonwealth", cells=wanted, refs=False)
    grids = {xy: fo4land.decode_vhgt(c["vhgt"]) for xy, c in world["cells"].items() if c["vhgt"]}
    merged, _ = fo4land.merge_cells(grids, x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    ox, oy = x0 * fo4land.CELL_UNITS, y0 * fo4land.CELL_UNITS
    out = []
    for q in placed:
        h = fo4land.height_at(merged, ox, oy, q["pos"][0] * 70.0, q["pos"][1] * 70.0)
        out.append(None if h is None or not math.isfinite(h) else h / 70.0)
    return out


def fo4_collision_tops(fo4_data, plan, metas):
    """Every point that lands on an object, checked against FO4's OWN collision: the source NIF read from the FO4
    mesh archives, its bodies decoded by scripts/game/routes.collision_bodies (independent of the converter and of
    sfbodies), placed with the reference's position, rotation and scale; the highest surface under the entry's drop
    height at the point, and the collision layer it belongs to (1 = static; the offline surface model treats every layer
    as solid, so a top on a layer the player passes through would be a false landing). Returns [{"entry", "label",
    "edid", "fo4_top", "layer", "expect", "diff_mm"}] (fo4_top None: FO4's collision of that model does not decode
    there, e.g. hknpDynamicCompoundShape)."""
    sys.path.insert(0, os.path.join(REPO, "scripts", "game"))
    import routes
    from fo4sf import ba2, nif as nifmod
    archives = [ba2.Ba2(os.path.join(fo4_data, fn)) for fn in sorted(os.listdir(fo4_data))
                if fn.lower().startswith("fallout4 - meshes") and fn.lower().endswith(".ba2")]
    cache, out = {}, []
    for e, entry in enumerate(plan):
        for p in entry["points"]:
            m = metas[(e, p["label"])]
            o = m.get("owner")
            if not o or m["kind"] not in ("object_top", "floor", "terrain_covered"):
                continue
            src = o["src"]
            if src not in cache:
                name = "meshes\\" + o["model"].replace("/", "\\").split("\\", 1)[1]
                blob = next((a.read(name) for a in archives if a.find(name) is not None), None)
                layers = {}
                if blob is not None:
                    for layer, pts, tr in routes.collision_bodies(nifmod.parse(blob)):
                        layers.setdefault(layer, []).extend(
                            tuple(exterior.to_world(pts[i], o["pos"], o["rot"], o["scale"]) for i in t) for t in tr)
                cache[src] = layers
            tops = [(z, layer) for layer, tris in cache[src].items()
                    if (z := exterior.top_z(tris, p["x"], p["y"], below=entry["drop_z"])) is not None]
            top, layer = max(tops) if tops else (None, None)
            out.append({"entry": e, "label": p["label"], "edid": o["edid"], "fo4_top": None if top is None else round(top, 5),
                        "layer": layer, "expect": p["expect"],
                        "diff_mm": None if top is None else round((top - p["expect"]) * 1000, 3)})
    return out


def ref_record_check(recs, own_prefix, objects, ids):
    """Compare the plugin's REFRs with objects.json: count per cell, base, position, rotation, scale, flags."""
    by_fid = {r["fid"]: r for r in recs}
    problems, worst_pos, worst_rot = [], 0.0, 0.0
    bases = objects["bases"]
    base_fid = {b["edid"]: own_prefix | int(ids["bases"][b["edid"]], 16) for b in bases}
    for r in objects["refs"]:
        fid = own_prefix | int(ids["refs"][r["src"]], 16)
        rec = by_fid.get(fid)
        if rec is None or rec["sig"] != "REFR":
            problems.append(f"{r['src']}: no REFR {fid:08X}")
            continue
        q = fo4land.parse_ref(rec["fields"])
        if q["base"] != base_fid[bases[r["base"]]["edid"]]:
            problems.append(f"{r['src']}: base {q['base']:08X}")
        worst_pos = max(worst_pos, max(abs(u - v) for u, v in zip(q["pos"], r["pos"])))
        worst_rot = max(worst_rot, max(abs(u - v) for u, v in zip(q["rot"], r["rot"])))
        if abs(q["scale"] - r["scale"]) > 1e-4:
            problems.append(f"{r['src']}: scale {q['scale']} != {r['scale']}")
        if bool(rec["flags"] & 0x800) != bool(r["disabled"]):
            problems.append(f"{r['src']}: disabled flag")
    return problems, worst_pos, worst_rot


def walk_cells(path):
    """{cell FormID: {"grid": (x, y) or None, "refs": [REFR FormIDs]}} from the plugin's group structure (raw)."""
    buf = overlay_records.read_bytes(path)
    hsize = struct.unpack_from("<I", buf, 4)[0]
    cells, cur = {}, {"id": None}

    def walk(start, end):
        for item in fo4land.iter_items(buf, start, end):
            if item[0] == "GRUP":
                _g, off, gend, label, gtype = item
                if gtype in (6, 8, 9):
                    owner = struct.unpack("<I", label)[0] if gtype == 6 else cur["id"]
                    saved = cur["id"]
                    cur["id"] = owner
                    walk(off + 24, gend)
                    cur["id"] = saved
                else:
                    walk(off + 24, gend)
                continue
            typ, off, _flags, fid = item
            if typ == b"CELL":
                grid = next((struct.unpack_from("<ii", d) for s, d in fo4land.iter_subrecords(fo4land.record_data(buf, off))
                             if s == b"XCLC"), None)
                cells[fid] = {"grid": grid, "refs": []}
                cur["id"] = fid
            elif typ == b"REFR" and cur["id"] in cells:
                cells[cur["id"]]["refs"].append(fid)
    walk(24 + hsize, len(buf))
    return cells


def cmd_check(a):
    out, b2 = a.out, a.exp2b
    prm = load(os.path.join(out, "exp2_params.json"))
    plan = load(os.path.join(out, "plan.json"))
    exp = load(os.path.join(out, "expected.json"))
    objects = load(os.path.join(out, "objects.json"))
    ids = load(os.path.join(out, "formids.json"))
    checks, rep = [], {}

    def need(cond, what):
        checks.append([what, bool(cond)])

    # 1. exp2b parts unchanged: every Data file of the base (BTD, mask, ...), the Mars plugin bytes; terrain records
    #    of the main plugin
    base_files = sorted(set(exp.get("base_files", [])) | {prm["btd_file"], prm["mask"]})
    for rel in base_files + [prm["mars"]["plugin"]]:
        need(os.path.isfile(os.path.join(b2, *rel.split("/"))) and
             sha256(os.path.join(out, *rel.split("/"))) == sha256(os.path.join(b2, *rel.split("/"))),
             f"{rel} byte-identical to the base")
    new = overlay_records.walk_plugin(os.path.join(out, prm["plugin"]))
    old = overlay_records.walk_plugin(os.path.join(b2, prm["plugin"]))
    new_by = {r["fid"]: r for r in new["records"]}
    same = sum(1 for r in old["records"] if r["fid"] in new_by and new_by[r["fid"]]["sig"] == r["sig"]
               and new_by[r["fid"]]["flags"] == r["flags"] and new_by[r["fid"]]["fields"] == r["fields"])
    need(same == len(old["records"]), f"every exp2b record unchanged in exp2c ({same}/{len(old['records'])})")
    need(new["masters"] == ["Starfield.esm"], f"masters {new['masters']}")

    # 2. the terrain side through the exp2b check (BTD points, WRLD/LCTN/SFBK, anchor, Mars entry, mask) with the
    #    uncovered terrain points and exp2b's spawn (ground under the COC marker)
    b_plan = load(os.path.join(b2, "plan.json"))
    terr = list({p["label"]: p for p in exp["points"] if p["kind"] in ("terrain", "terrain_ref")}.values())
    tplan = [dict(b_plan[0], points=[{k: p[k] for k in ("label", "x", "y", "expect")} for p in terr])]
    ok, trep = overlay_records.check_staging(out, prm, tplan, overlay_records.vanilla_mars_count(a.sf_data))
    for what, good in trep["checks"]:
        need(good, "exp2b check: " + what)
    rep["terrain"] = {k: trep[k] for k in ("points", "plugin", "mars", "mask", "btd") if k in trep}

    # 3. object records: STAT / DOOR, models on disk, REFRs per cell, positions
    own = len(new["masters"]) << 24
    recs = new["records"]
    stats = [r for r in recs if r["sig"] in ("STAT", "DOOR")]
    need(len(stats) == len(objects["bases"]), f"{len(stats)} STAT/DOOR = {len(objects['bases'])} bases")
    missing = []
    for r in stats:
        model = fo4land.zstring(overlay_records.field(r, "MODL", b""))
        if not os.path.isfile(os.path.join(out, "Data", "meshes", model)):
            missing.append(model)
    need(not missing, f"every base model is in Data\\meshes ({len(missing)} missing)")
    deps = dependency_check(os.path.join(out, "Data"), [b["model"] for b in objects["bases"]],
                            vanilla=vanilla_textures(a.sf_data))
    need(not deps["missing"], f"every geometry / material / texture the models name exists: ours in Data, the rest in "
         f"the Starfield texture archives ({deps['missing_count']} missing, {deps['counts']})")
    problems, worst_pos, worst_rot = ref_record_check(recs, own, objects, ids)
    need(not problems, f"every REFR matches objects.json ({len(problems)} problems)")
    need(worst_pos < 1e-3 and worst_rot < 1e-5, f"REFR position / rotation as written (worst {worst_pos:.2e} m, {worst_rot:.2e} rad)")
    cells = walk_cells(os.path.join(out, prm["plugin"]))
    per_cell = {}
    for r in objects["refs"]:
        per_cell[tuple(r["cell"])] = per_cell.get(tuple(r["cell"]), 0) + 1
    got = {c["grid"]: len(c["refs"]) for c in cells.values() if c["grid"] is not None and c["refs"]}
    spawn_cell = tuple(prm["spawn_cell"])
    want = dict(per_cell)
    want[spawn_cell] = want.get(spawn_cell, 0) + 1                    # + the COC marker
    need(got == want, f"REFRs per exterior cell match ({len(got)} cells with references)")
    refrs = sum(1 for r in recs if r["sig"] == "REFR")
    need(refrs == len(objects["refs"]) + 2, f"{refrs} REFR = {len(objects['refs'])} objects + COC marker + anchor")
    wrong_cell = [r["src"] for r in objects["refs"] if list(r["cell"]) != list(tg.sf_cell_of(r["pos"][0], r["pos"][1]))]
    need(not wrong_cell, f"every reference is in the cell of its written position ({len(wrong_cell)} not: {wrong_cell[:5]})")
    rep["plugin"] = {"bytes": new["bytes"], "masters": new["masters"],
                     "records": {s: sum(1 for r in recs if r["sig"] == s) for s in sorted({r["sig"] for r in recs})},
                     "cells_with_refs": len(got), "refs_per_cell_max": max(got.values()), "ref_problems": problems[:20],
                     "worst_pos_m": worst_pos, "worst_rot_rad": worst_rot, "dependencies": deps["counts"]}

    # 4. object z - terrain z under every placed origin (BTD; with --fo4 also FO4's own LAND)
    sel = load(os.path.join(a.work, "convert_input.json"))
    man = load(os.path.join(a.work, "convert", "manifest.json"))
    bases, placed, _ = exterior.place(sel, man, prm["cell_min"], prm["cell_max"], EDID_PREFIX)
    items = {i["source"].replace("/", "\\").lower(): i for i in man["items"]}
    for b in bases:
        b["collision"] = collision_kind(items[b["key"]])
    world = World(os.path.join(out, "Data"), bases, placed, os.path.join(out, *prm["btd_file"].split("/")))
    btd_dz = [p["pos"][2] - world.ground(p["pos"][0], p["pos"][1]) for p in placed]
    fo4_dz = None
    if a.fo4:
        g4 = fo4_ground(a.fo4, placed, (-21, -14, 15, 22))
        fo4_dz = [None if g is None else p["pos"][2] - g for p, g in zip(placed, g4)]
    k = world.by_src[BUILDING]
    gb = world.ground_all(*placed[k]["pos"][:2])
    building = {"src": BUILDING, "pos": placed[k]["pos"], "btd_ground": {m: round(v, 5) for m, v in gb.items()},
                "object_minus_btd_mm": {m: round((placed[k]["pos"][2] - v) * 1000, 2) for m, v in gb.items()},
                "object_minus_fo4_land_mm": None if fo4_dz is None else round(fo4_dz[k] * 1000, 2)}
    need(max(abs(v) for v in building["object_minus_btd_mm"].values()) <= world.step * 1000,
         f"Red Rocket building z - BTD ground within one quantisation step ({building['object_minus_btd_mm']} mm)")
    if fo4_dz is not None:
        need(abs(fo4_dz[k]) < 1e-3, f"Red Rocket building z - FO4 LAND ground = {fo4_dz[k] * 1000:.2f} mm (FO4 says 0)")
        idx = [i for i, f in enumerate(fo4_dz) if f is not None]
        diff = np.array([btd_dz[i] - fo4_dz[i] for i in idx])
        worst = sorted(range(len(idx)), key=lambda j: -abs(diff[j]))[:5]
        rep["fo4_vs_btd_under_objects"] = {
            "objects": len(idx), "median_abs_mm": round(float(np.median(np.abs(diff))) * 1000, 2),
            "p95_abs_mm": round(float(np.percentile(np.abs(diff), 95)) * 1000, 2),
            "p99_abs_mm": round(float(np.percentile(np.abs(diff), 99)) * 1000, 2),
            "max_abs_mm": round(float(np.abs(diff).max()) * 1000, 2),
            "within_1cm": int((np.abs(diff) <= 0.01).sum()), "within_5cm": int((np.abs(diff) <= 0.05).sum()),
            "worst": [{"src": placed[idx[j]]["src"], "edid": bases[placed[idx[j]]["base"]]["edid"],
                       "pos": placed[idx[j]]["pos"], "btd_minus_fo4_mm": round(float(diff[j]) * 1000, 1)} for j in worst]}
    arr = np.array(btd_dz)
    rep["object_minus_btd"] = {"objects": len(arr), "building": building,
                               "histogram_m": {f"{lo}..{hi}": int(((arr >= lo) & (arr < hi)).sum())
                                               for lo, hi in ((-50, -1), (-1, -0.25), (-0.25, -0.05), (-0.05, 0.05),
                                                              (0.05, 0.25), (0.25, 1), (1, 50))},
                               "by_edid": {placed[i]["src"]: {"edid": bases[placed[i]["base"]]["edid"],
                                                              "btd_dz": round(btd_dz[i], 4),
                                                              "fo4_dz": None if fo4_dz is None or fo4_dz[i] is None else round(fo4_dz[i], 4)}
                                           for i in sorted({world.by_src[p["owner"]["src"]] for p in exp["points"] if p.get("owner")})}}

    # 5. every plan point re-derived from the converted collision + BTD (independent of stage's search)
    metas = {(q["entry"], q["label"]): q for q in exp["points"]}
    kinds = {k: q["kind"] for k, q in metas.items()}
    problems = validate_plan(plan, b_plan[0], kinds)
    need(not problems, f"plan entries carry every exp2b key and a z_ref on their own terrain reference ({problems[:3]})")
    pts = []
    for e, entry in enumerate(plan):
        for p in entry["points"]:
            meta = metas[(e, p["label"])]
            land = world.landing(p["x"], p["y"], entry["drop_z"])
            err = abs(land["centre"] - p["expect"])
            if meta["kind"] in ("terrain", "terrain_near_object", "terrain_ref"):
                hs = world.ground_all(p["x"], p["y"])
                err = max(abs(v - p["expect"]) for v in hs.values())
                near = exterior.nearby_object(world.index.top, world.ground, p["x"], p["y"], entry["drop_z"],
                                              radii=TERRAIN_CLEAR_RADII)
                need(not land["on_object"] and err <= world.step, f"{p['label']}: still terrain, decoded within one step")
                need((near is None) == (meta["kind"] != "terrain_near_object"), f"{p['label']}: " + (
                    f"no object within {TERRAIN_CLEAR_RADII[-1]} m" if near is None else
                    f"object {world.placed[near['owner']]['src']} {near['height']:.2f} m high at {near['distance']} m"))
                if meta["kind"] == "terrain_ref":
                    need(reference_ok(world, p["x"], p["y"]) is not None,
                         f"{p['label']} (entry {e + 1}): level open terrain, nothing above it within {REF_CLEAR} m")
                    need(entry["drop_z"] - p["expect"] >= 0.5, f"{p['label']} (entry {e + 1}): dropped from "
                         f"{entry['drop_z'] - p['expect']:.2f} m above the terrain")
            else:
                owner = world.by_src[meta["owner"]["src"]]
                need(land["on_object"] and land["owner"] == owner and err < 1e-3,
                     f"{p['label']}: lands on {meta['owner']['edid']} at {p['expect']} (error {err * 1000:.2f} mm)")
                if meta["kind"] in ("object_top", "floor"):
                    need(land["all_on_object"] and land["spread"] <= 0.02, f"{p['label']}: level, whole disc on the object")
                if e == 1:
                    d = discrimination(world, p["x"], p["y"], p["expect"])
                    need(d >= MIN_DISCRIMINATION, f"{p['label']}: {d:.2f} m above the highest terrain under the disc "
                         f"(judged object points need >= {MIN_DISCRIMINATION} m)")
                if meta["kind"] == "floor":
                    free = exterior.clearance(world.index, p["x"], p["y"], land["centre"])
                    need(entry["drop_z"] - p["expect"] >= 0.5 and free >= entry["drop_z"] - p["expect"] + PLAYER_HEIGHT,
                         f"{p['label']}: drop height {entry['drop_z'] - p['expect']:.2f} m, {free:.2f} m free above the floor")
            if entry["drop_z"] >= DROP_Z:                              # the drop starts above everything at the point
                tops = [s[0][0] for dx, dy in exterior.disc_offsets(1.0) if (s := world.index.surfaces(p["x"] + dx, p["y"] + dy))]
                need(entry["drop_z"] >= max(tops + [p["expect"]]) + 10, f"{p['label']}: drop_z {entry['drop_z']} >= "
                     f"every collision top within 1 m + 10 m ({max(tops + [p['expect']]):.2f})")
            pts.append({"entry": e, "label": p["label"], "kind": meta["kind"], "expect": p["expect"],
                        "landing": landing_json(world, land), "error_mm": round(err * 1000, 3)})
    land = world.landing(prm["spawn"][0], prm["spawn"][1], prm["spawn"][2])
    need(all(abs(land["centre"] - e["spawn_local"][2]) < 1e-3 for e in plan),
         "spawn_local z = what the player lands on under the COC marker")
    need(exterior.clearance(world.index, prm["spawn"][0], prm["spawn"][1], land["centre"]) >= PLAYER_HEIGHT,
         "room for the player above the arrival")

    # 6. what the runner's verdict can tell: predicted verdicts without the objects and on flat terrain (exp2b's
    #    first attempt), and the teleport paths with the assumed capsule (required clear in the low-drop entry)
    start = (prm["spawn"][0], prm["spawn"][1], land["centre"])
    rep["entries"] = []
    for e, entry in enumerate(plan):
        meta = {p["label"]: metas[(e, p["label"])] for p in entry["points"]}
        pred = {sc: judge_heights(entry["points"], scenario_reads(world, entry, meta, sc), entry["z_ref"])[:2]
                for sc in SCENARIOS[e]}
        planned = judge_heights(entry["points"], [p["expect"] for p in entry["points"]], entry["z_ref"])
        paths, clear = path_report(world, start, entry["points"], entry["drop_z"])
        rep["entries"].append({"label": entry["label"], "planned": planned[0],
                               "predicted": {sc: {"verdict": v, "worst_m": round(w, 3)} for sc, (v, w) in pred.items()},
                               "teleports_clear": clear, "teleports": paths})
        if e == 0:
            need(pred["flat_terrain"][0] == "FAIL" and pred["flat_terrain"][1] >= MIN_DISCRIMINATION,
                 f"entry 1 fails on flat terrain (worst {pred['flat_terrain'][1]:.2f} m)")
            need(pred["no_objects"][0] == "PASS", "entry 1 does not depend on the objects")
        if e == 1:
            need(pred["no_objects"][0] == "FAIL" and pred["no_objects"][1] >= MIN_DISCRIMINATION,
                 f"entry 2 fails without the objects (worst {pred['no_objects'][1]:.2f} m)")
        if entry["drop_z"] < DROP_Z:
            need(clear, f"entry {e + 1} (low drop): no teleport position overlaps collision or terrain (capsule "
                        f"{CAPSULE[0]} m x {CAPSULE[1]} m, assumed)")

    # 7. with --fo4-data: the object points against FO4's own collision (source NIFs, not the converted ones)
    if a.fo4_data:
        rep["fo4_collision_tops"] = fo4_collision_tops(a.fo4_data, plan, metas)
        for t in rep["fo4_collision_tops"]:
            if t["entry"] in (1, 2):                                   # the judged objects and the shop floor
                need(t["diff_mm"] is not None and abs(t["diff_mm"]) < 1.0 and t["layer"] == 1,
                     f"{t['label']}: FO4's own collision top {t['fo4_top']} (layer {t['layer']}) = expect {t['expect']} "
                     f"({t['diff_mm']} mm)")
    rep["points"] = pts
    rep["checks"] = checks
    rep["pass"] = all(c[1] for c in checks)
    save(os.path.join(out, "offline_check.json"), rep)
    for what, good in checks:
        print(("  ok   " if good else "  FAIL ") + what)
    for p in pts:
        print(f"  {p['label']:<36} {p['kind']:<16} expect {p['expect']:9.4f}  landing {p['landing']['centre']:9.4f}  "
              f"spread {p['landing']['spread']:.3f}  error {p['error_mm']:.3f} mm")
    print(json.dumps({k: rep[k] for k in ("plugin", "object_minus_btd", "fo4_vs_btd_under_objects") if k in rep}, indent=1)[:6000])
    print("CHECK", "PASS" if rep["pass"] else "FAIL")
    return 0 if rep["pass"] else 1


def dependency_check(data, models, prefix="fo4cw", vanilla=None):
    """Every geometry a converted NIF's BSGeometry blocks name (Data\\geometries\\<path>.mesh), every material its
    shader properties name (Data\\materials\\...) and every texture those .mat files name exists: our own files
    (textures\\<prefix>\\...) under Data, the rest (vanilla parents / textures the template keeps) in `vanilla`, a set
    of lower-case archive names from the Starfield texture archives (None: not checked, counted as unverified)."""
    from fo4sf import nif as nifmod
    from fo4sf import sfnif
    seen_mats, seen_tex, missing = set(), set(), []
    counts = {"nifs": 0, "meshes": 0, "materials": 0, "textures_own": 0, "textures_vanilla": 0, "vanilla_unverified": 0}
    for m in sorted(set(models)):
        with open(os.path.join(data, "meshes", m), "rb") as f:
            n = nifmod.parse(f.read())
        counts["nifs"] += 1
        for i in range(len(n.blocks)):
            if n.type_of(i) != "BSGeometry":
                continue
            for ref in sfnif.parse_bsgeometry(n.blocks[i]).meshes:
                if ref is None:
                    continue
                counts["meshes"] += 1
                rel = ref.path.decode("latin-1").replace("/", "\\") + ".mesh"
                if not os.path.isfile(os.path.join(data, "geometries", rel)):
                    missing.append("geometries\\" + rel)
        for path in nifmod.referenced_paths(n):
            low = path.replace("/", "\\").lower()
            if not low.endswith(".mat") or low in seen_mats:
                continue
            seen_mats.add(low)
            counts["materials"] += 1
            mp = os.path.join(data, low)
            if not os.path.isfile(mp):
                missing.append(path)
                continue
            with open(mp, encoding="utf-8") as f:
                for tex in _json_strings(json.load(f)):
                    rel = tex.replace("/", "\\").lower()
                    if not rel.endswith(".dds") or rel in seen_tex:
                        continue
                    seen_tex.add(rel)
                    rel = rel[len("data\\"):] if rel.startswith("data\\") else rel
                    rel = rel if rel.startswith("textures\\") else "textures\\" + rel
                    if rel.startswith(f"textures\\{prefix}\\"):
                        counts["textures_own"] += 1
                        if not os.path.isfile(os.path.join(data, rel)):
                            missing.append(rel)
                    else:
                        counts["textures_vanilla"] += 1
                        if vanilla is None:
                            counts["vanilla_unverified"] += 1
                        elif rel.replace("\\", "/") not in vanilla:
                            missing.append(rel)
    return {"counts": counts, "missing": sorted(set(missing))[:50], "missing_count": len(set(missing))}


def _json_strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _json_strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _json_strings(x)


def vanilla_textures(sf_data):
    """Lower-case names (forward slashes) in the Starfield texture archives, or None without a Data folder."""
    if not sf_data or not os.path.isdir(sf_data):
        return None
    from fo4sf import ba2
    names = set()
    for fn in sorted(os.listdir(sf_data)):
        if fn.lower().startswith("starfield - textures") and fn.lower().endswith(".ba2"):
            names.update(n.replace("\\", "/").lower() for n in ba2.Ba2(os.path.join(sf_data, fn)).names)
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--export", required=True)
    s.add_argument("--work", required=True)
    for name in ("stage", "check"):
        s = sub.add_parser(name)
        s.add_argument("--work", required=True)
        s.add_argument("--exp2b", required=True)
        s.add_argument("--out", required=True)
        if name == "stage":
            s.add_argument("--sf-esm", default="", help="Starfield.esm: build the plugin with dotnet/TerrainExp2")
        else:
            s.add_argument("--sf-data", default="", help="Starfield Data (vanilla Mars entry count)")
            s.add_argument("--fo4", default="", help="Fallout4.esm: also compare against FO4's own terrain under each object")
            s.add_argument("--fo4-data", default="", help="FO4 Data folder (mesh archives): object points against FO4's "
                                                          "own collision")
    a = ap.parse_args()
    return {"select": cmd_select, "stage": cmd_stage, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
