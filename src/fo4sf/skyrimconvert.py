"""Skyrim (Special Edition) static models -> Starfield NIF + .mesh + .mat + DDS, on top of pipeline.Converter.

What is reused unchanged: Starfield mesh / NIF writing (convert_static.shape_to_mesh, sfnif.build_static_nif), texture
conversion and caps (Converter._convert_texture_set: colour BC1, normal BC5, roughness BC4, opacity BC4), the cloned
vanilla material templates (opaque, alpha-tested cutout, decal), the neutral fallback material, and the box-collision
writer verified in game (sfcollision.box_blob).

What is Skyrim's: geometry (skyrimnif.trishapes: BS 100 BSTriShape, NiTriShape / NiTriStrips), materials named by
BSShaderTextureSet (diffuse + normal; Skyrim keeps specular in the normal map's alpha and has no smoothness map, so
roughness is the converter's uniform "fairly rough"), NiAlphaProperty test / blend (foliage cutouts, decals), and
collision: Skyrim's own Havok collision decoded to triangles (skyrimnif.collision_bodies) and, with a Starfield mesh
template, encoded as native Starfield compressed-mesh bodies, one per Skyrim body with its layer (cmsencode,
meshcollision.mesh_body; 2026-10-22); otherwise, or if that fails, rebuilt as Starfield boxes (sfcollision.mesh_boxes:
thin boxes behind flat surfaces + voxel boxes for the rest, which put ledges on ramps: docs/interior/skyrim-interiors.md). A model Skyrim gives no
collision gets none (grass, small plants, cobwebs: the player walks through them in Skyrim too). Boxes are an
approximation of curved rock and tree collision, not Starfield's native mesh shape (see docs/terrain/skyrim-objects.md).
"""
import dataclasses
import hashlib
import os
import re
from typing import Dict, List, Optional

from . import convert_material as cm, convert_static, nif as nifmod, pipeline, sfcollision, sfmesh, sfnif, skyrimfire, \
    skyrimnif, skyrimrefs
from .skyrimflames import FlameMixin

UNIT = 1.0 / 70.0
# landscape pieces (rocks, cliffs, mountains, boulders): solid from below, what matters is the walkable top and the
# sides, so they get column boxes; everything else (buildings, ruins, bridges, trees, props) keeps the surface/voxel
# boxes FO4 architecture uses (thin walls, floors and arches stay open)
LANDSCAPE_RE = re.compile(r"[\\/]landscape[\\/]|rock|cliff|mountain|boulder|glacier|iceberg", re.I)
COLUMN_MIN_BOXES, COLUMN_MAX_BOXES = 128, 512
TOP_TOL = 0.1           # m: tops of the columns merged into one box differ by at most this (a step the player walks)


def column_budget(points) -> int:
    """Boxes a landscape piece may use: one per 16 m2 of footprint, at least 128, at most 512."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    return int(min(COLUMN_MAX_BOXES, max(COLUMN_MIN_BOXES, area / 16.0)))


def _surface_samples(P, T, spacing):
    """Vertices plus barycentric samples so that no point of any triangle is farther than about `spacing` from one."""
    import numpy as np
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    edge = np.max(np.stack([np.linalg.norm(a - b, axis=1), np.linalg.norm(b - c, axis=1),
                            np.linalg.norm(c - a, axis=1)]), axis=0)
    k = np.clip(np.ceil(edge / spacing), 1, 64).astype(np.int64)
    out = [P]
    for kk in np.unique(k):
        if kk < 2:
            continue
        sel = k == kk
        w = np.array([(i / kk, j / kk) for i in range(kk + 1) for j in range(kk + 1 - i)])
        u, v = w[:, 0][None, :, None], w[:, 1][None, :, None]
        pts = (1 - u - v) * a[sel][:, None, :] + u * b[sel][:, None, :] + v * c[sel][:, None, :]
        out.append(pts.reshape(-1, 3))
    return np.concatenate(out)


def column_boxes(points, triangles, max_boxes=None, cell=None, report=None):
    """Axis-aligned boxes covering a solid landscape piece: the collision surface is rasterised into vertical columns of
    `cell` metres (each spans from the piece's lowest point up to the highest surface point in it), columns are merged along x then y where
    their bottoms and tops agree within a tolerance, and the grid coarsens (x 1.25) until the count fits the budget
    (column_budget unless given). Nothing is dropped: a large piece gets coarser columns, never holes. Walkable tops
    keep the surface height within about half a cell times the slope. Returns [(centre, half)]."""
    import numpy as np
    P = np.asarray(points, np.float64)
    T = np.asarray(triangles, np.int64)
    budget = max_boxes or column_budget(points)
    lo, hi = P.min(axis=0), P.max(axis=0)
    area = max((hi[0] - lo[0]) * (hi[1] - lo[1]), 1e-6)
    cell = cell or max(0.5, 0.5 * (area / budget) ** 0.5)       # start near the size that can fit the budget
    S = _surface_samples(P, T, cell / 2.0)
    while True:
        ix = np.floor((S[:, 0] - lo[0]) / cell).astype(np.int64)
        iy = np.floor((S[:, 1] - lo[1]) / cell).astype(np.int64)
        key = ix * (iy.max() + 2) + iy
        order = np.argsort(key, kind="stable")
        ks, zs = key[order], S[order, 2]
        starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
        zmax = np.maximum.reduceat(zs, starts)
        cx, cy = ix[order][starts], iy[order][starts]
        # solid from the piece's lowest point: Skyrim rock collision is often open underneath (sunk into the
        # ground); a column then still blocks from below, and merging depends on the tops only
        cols = {(int(x), int(y)): (float(lo[2]), float(b)) for x, y, b in zip(cx, cy, zmax)}
        # merge only columns whose tops ALL lie within TOP_TOL of each other (a merged box takes the highest top):
        # until 2026-11-08 each column was compared with the run's running maximum, so on a long slope the top crept
        # up column by column and a road ramp became a ledge up to 2 m above Skyrim's surface (owner: an invisible
        # hump on Riverwood's RoadStraightLongRamp01, gone with the road disabled; collision_view.py measures it)
        tol = TOP_TOL
        runs = []                                   # [x0, x1, bottom, top, y0, y1, lowest top]
        for y in sorted({k[1] for k in cols}):
            cur = None
            for x in sorted(k[0] for k in cols if k[1] == y):
                z0, z1 = cols[(x, y)]
                if cur and x == cur[1] + 1 and abs(z0 - cur[2]) <= tol and max(cur[3], z1) - min(cur[6], z1) <= tol:
                    cur = [cur[0], x, min(cur[2], z0), max(cur[3], z1), y, y, min(cur[6], z1)]
                else:
                    if cur:
                        runs.append(cur)
                    cur = [x, x, z0, z1, y, y, z1]
            if cur:
                runs.append(cur)
        merged, open_ = [], {}
        for r in sorted(runs, key=lambda r: (r[4], r[0])):
            o = open_.get((r[0], r[1]))
            if o and r[4] == o[5] + 1 and abs(r[2] - o[2]) <= tol and max(o[3], r[3]) - min(o[6], r[6]) <= tol:
                o[2], o[3], o[5], o[6] = min(o[2], r[2]), max(o[3], r[3]), r[4], min(o[6], r[6])
            else:
                if o:
                    merged.append(o)
                open_[(r[0], r[1])] = list(r)
        merged += open_.values()
        if len(merged) <= budget:
            boxes = []
            for x0, x1, z0, z1, y0, y1, _lowest in merged:
                bl = (lo[0] + x0 * cell, lo[1] + y0 * cell, z0)
                bh = (min(lo[0] + (x1 + 1) * cell, hi[0]), min(lo[1] + (y1 + 1) * cell, hi[1]), max(z1, z0 + 0.05))
                boxes.append((tuple((bl[k] + bh[k]) / 2 for k in range(3)), tuple((bh[k] - bl[k]) / 2 for k in range(3))))
            if report is not None:
                report["column_cell_m"] = round(cell, 3)
                report["boxes"] = len(boxes)
                report["column_budget"] = budget
            return boxes
        cell *= 1.25


STAIR_HELPER_LAYER = 31               # Skyrim / FO4 / Starfield STAIRHELPER: only the character controller collides


def native_collision(src: nifmod.NifFile, sf_mesh_template: bytes, report: dict,
                     stair_layer: Optional[int] = STAIR_HELPER_LAYER) -> list:
    """The model's own Skyrim collision as native Starfield bodies: one compressed-mesh body per Skyrim rigid body, same
    triangles (metres, root frame), same Havok layer (stair helpers stay stair helpers). Non-solid bodies (triggers,
    portals, AI / sound volumes) get none. Stair flights get an extra ramp body on `stair_layer` (None: no ramps).
    Raises on anything it cannot encode (the caller falls back to boxes)."""
    from . import meshcollision
    bodies = skyrimnif.collision_bodies(src, report)
    blobs, skipped, n_tris = [], {}, 0
    for layer, pts, tris in bodies:
        if layer in meshcollision.NON_SOLID_LAYERS:
            skipped[str(layer)] = skipped.get(str(layer), 0) + 1
            continue
        if not tris:
            continue
        m = [(x * UNIT, y * UNIT, z * UNIT) for x, y, z in pts]
        blobs.append(meshcollision.mesh_body(m, tris, sf_mesh_template, layer))
        n_tris += len(tris)
    if stair_layer is not None and blobs and STAIR_HELPER_LAYER not in {l for l, _p, t in bodies if t}:
        # Starfield's character controller does not glide over Skyrim's step collision: add a stair-helper ramp body
        # over each flight (src/fo4sf/stairramp.py). Models with their own stair helpers keep those only.
        from . import stairramp
        solid_p, solid_t = [], []
        for layer, pts, tris in bodies:
            if tris and layer not in meshcollision.NON_SOLID_LAYERS:
                base = len(solid_p)
                solid_p += [(x * UNIT, y * UNIT, z * UNIT) for x, y, z in pts]
                solid_t += [(a + base, b + base, c + base) for a, b, c in tris]
        rp, rt, ramps = stairramp.stair_ramps(solid_p, solid_t)
        if rt:
            blobs.append(meshcollision.mesh_body(rp, rt, sf_mesh_template, stair_layer))
            report["stair_ramps"] = ramps
    report["source"] = "skyrim-native" if blobs else "skyrim-none"
    report["bodies"] = len(blobs)
    report["layers"] = sorted({str(l) for l, _p, t in bodies if t and l not in meshcollision.NON_SOLID_LAYERS})
    report["skyrim_collision_triangles"] = n_tris
    if skipped:
        report["skipped_layers"] = skipped
    return blobs


def collision_boxes(src: nifmod.NifFile, template: bytes, report: dict, landscape: bool = False) -> list:
    """Starfield single-box physics blobs approximating the model's own Skyrim collision (metres), or []. Non-solid
    bodies (meshcollision.NON_SOLID_LAYERS) are left out: a trigger volume made into boxes is an invisible wall."""
    from . import meshcollision
    pts, tris = skyrimnif.collision_triangles(src, report, skip_layers=tuple(meshcollision.NON_SOLID_LAYERS))
    if not tris:
        report["source"] = "skyrim-none"
        return []
    m = [(x * UNIT, y * UNIT, z * UNIT) for x, y, z in pts]
    lo = [min(p[a] for p in m) for a in range(3)]
    hi = [max(p[a] for p in m) for a in range(3)]
    report["collision_bounds_m"] = [[round(v, 3) for v in lo], [round(v, 3) for v in hi]]
    if landscape:
        boxes = column_boxes(m, tris, report=report)
        report["method"] = "columns"
    else:
        boxes = sfcollision.mesh_boxes(m, tris, report=report)
        report["method"] = "surfaces+voxels"
    report["source"] = "skyrim-boxes"
    return [sfcollision.box_blob(template, c, h) for c, h in boxes]


MAX_VERTICES = 0xFFFF                 # Starfield .mesh triangle indices are u16


def alt_texture_blocks(shapes, alt) -> Dict[int, list]:
    """{shape block: texture paths} for a base's alternate textures (skyrimrefs.alternate_textures). An entry names its
    shape (3D name, compared case-insensitively) and gives its index among the model's geometry; the name decides, the
    index only for an entry whose name matches no shape. Verified on RoadChunkM01Snow: 'RoadChunkM01:0' index 0 and
    'RoadChunkM01:2' index 1 are the model's two BSTriShapes in order."""
    names = {}
    for s in shapes:
        names.setdefault((s.name or b"").decode("latin-1").lower(), s.block)
    out = {}
    for e in alt:
        block = names.get(e["name"].lower())
        if block is None and 0 <= int(e["index"]) < len(shapes):
            block = shapes[int(e["index"])].block
        if block is not None:
            out[block] = list(e["textures"])
    return out


def swap_textures(paths: list, alt: Optional[list]) -> list:
    """A shape's texture set with an alternate texture set applied: Skyrim replaces the whole set; a set without a
    normal map keeps the shape's own normal map (the converter needs one; none seen in Skyrim's alternate sets)."""
    if not alt or not alt[0]:
        return paths
    out = list(alt) + [""] * max(0, len(paths) - len(alt))
    if not out[1] and len(paths) > 1:
        out[1] = paths[1]
    return out


def with_back_faces(s: nifmod.Fo4Shape) -> Optional[nifmod.Fo4Shape]:
    """The shape plus a mirrored copy of every triangle (reversed winding, normals negated, tangents kept so the
    recomputed handedness flips with the normal): a double-sided Skyrim surface as plain one-sided Starfield geometry,
    with no new material type. None when the doubled vertex count would not fit u16 indices."""
    nv = len(s.positions)
    if 2 * nv > MAX_VERTICES:
        return None
    return dataclasses.replace(
        s, positions=list(s.positions) * 2, uvs=list(s.uvs) * 2 if s.uvs else s.uvs,
        normals=list(s.normals) + [(-x, -y, -z) for x, y, z in s.normals] if s.normals else s.normals,
        tangents=list(s.tangents) * 2 if s.tangents else s.tangents,
        colors=list(s.colors) * 2 if s.colors else s.colors,
        triangles=[tuple(t) for t in s.triangles] + [(a + nv, c + nv, b + nv) for a, b, c in s.triangles])


# Vertex-alpha cutouts (2026-11-25, owner's Whiterun market: grass and moss layers of the city's ground meshes drawn
# where Skyrim hides them). Skyrim draws an alpha-tested shape with Vertex_Alpha (skyrimnif.vertex_alpha) where
# texture alpha x vertex alpha >= the threshold; Starfield's cutout material sees the texture only. So the shape is cut
# along its vertex alpha: below threshold / 255 nothing is drawn (Skyrim draws nothing there whatever the texture),
# above it the shape is split into VA_BANDS bands of vertex alpha, each with a cutout threshold raised to make up for its
# vertex alpha (texture alpha >= threshold / vertex alpha, at the band's middle). Geometry and a threshold per band
# only: no Starfield vertex-colour material setting is needed (vanilla has AlphaBlenderSettings UseVertexColor, how it
# combines with the opacity map is unverified).
VA_BANDS = 4
VA_SOLID = 250          # every vertex alpha at least this: the shape is left as it is


def vertex_alpha_bands(ref: int, has_opacity: bool, n: int = VA_BANDS) -> list:
    """[(low, high or None, cutout threshold 0..255)] for an alpha-tested shape with threshold `ref`: the vertex-alpha
    ranges to keep and the threshold each one's material needs. Without an opacity map (the texture's alpha is solid,
    the material is opaque) one range from ref / 255 up, as it is. ref 0 cuts nothing: []."""
    if ref <= 0:
        return []
    r = ref / 255.0
    if not has_opacity or r >= 1.0:
        return [(r, None, ref)]
    edges = [r + (1.0 - r) * k / n for k in range(n + 1)]
    out = []
    for k in range(n):
        lo, hi = edges[k], edges[k + 1]
        thr = min(255, max(ref, int(round(255.0 * (r / lo + r / hi) / 2.0))))
        out.append((lo, hi if k < n - 1 else None, thr))
    return out


def clip_vertex_alpha(s: nifmod.Fo4Shape, lo: float, hi: Optional[float] = None) -> Optional[nifmod.Fo4Shape]:
    """The part of the shape whose vertex alpha (0..1, interpolated across each triangle as the GPU does) lies in
    [lo, hi] (hi None: no upper limit): each triangle clipped against both levels and fanned back into triangles
    (winding kept). A vertex made on an edge is shared by the triangles on both sides; every attribute is interpolated
    there (normals renormalised). Unused vertices are dropped. None when nothing is left."""
    import math
    alpha = [c[3] / 255.0 for c in s.colors]
    attrs = {k: getattr(s, k) for k in ("positions", "uvs", "normals", "tangents", "colors") if getattr(s, k)}
    out = {k: list(v) for k, v in attrs.items()}
    made = {}

    def cut(i, j, level):
        key = (min(i, j), max(i, j), level)
        if key not in made:
            t = (level - alpha[i]) / (alpha[j] - alpha[i])
            for k, v in attrs.items():
                x = [p + t * (q - p) for p, q in zip(out[k][i], out[k][j])]
                if k == "colors":
                    x = [int(round(min(255.0, max(0.0, c)))) for c in x]
                elif k == "normals":
                    ln = math.sqrt(sum(c * c for c in x)) or 1.0
                    x = [c / ln for c in x]
                out[k].append(tuple(x))
            alpha.append(level)
            made[key] = len(alpha) - 1
        return made[key]

    def clip(poly, inside, level):
        res = []
        for m, cur in enumerate(poly):
            nxt = poly[(m + 1) % len(poly)]
            ci, ni = inside(alpha[cur]), inside(alpha[nxt])
            if ci:
                res.append(cur)
            if ci != ni:
                res.append(cut(cur, nxt, level))
        return res

    tris = []
    for tri in s.triangles:
        poly = clip(list(tri), lambda a: a >= lo, lo)
        if hi is not None and len(poly) >= 3:
            poly = clip(poly, lambda a: a <= hi, hi)
        tris += [(poly[0], poly[k], poly[k + 1]) for k in range(1, len(poly) - 1)]
    if not tris:
        return None
    used = sorted({i for t in tris for i in t})
    new = {old: k for k, old in enumerate(used)}
    keep = {k: [v[i] for i in used] for k, v in out.items()}
    return dataclasses.replace(s, triangles=[tuple(new[i] for i in t) for t in tris],
                               **{k: keep.get(k, []) for k in ("positions", "uvs", "normals", "tangents", "colors")})


# Skyrim water inside models (2026-11-26, owner: Whiterun's streams, pools and the horse troughs drew white). Skyrim
# draws a BSWaterShaderProperty shape as water of the type its base names (ACTI WNAM -> WATR: WRWaterPool01 074EEA,
# WRStairsStreamLACT 085FC8, HorseTrough01 0F762D; verified in Skyrim.esm). The converter had no material for it (the
# neutral one: white). Now the water shapes leave the model and become a model of their own, "<model>_water.nif":
# Skyrim's exact surfaces with Starfield's water placeholder material, no collision, laid out as vanilla
# Water\Water16m.nif is (a plane BSGeometry + MaterialID + "Materials\Water\WaterPlaceholder.mat"; the look comes from the
# activator's water type WTFM, not the mesh: verified, Starfield - Meshes01.ba2 and Starfield.esm ACTI 039FD6).
# make_skyrim_objects stage places it as a copy of the vanilla water activator (TerrainOverlays "water_template").
# First way, 2026-11-26 (owner's test: tiled squares of scaled Water16mClearLake pieces, small ones far-green and a
# patchwork): water_squares, kept as stage --water-squares. SLOPED shapes (streams down steps) go into the water model
# too (a probe: water on a sloped mesh is unverified; the vanilla Waterfall_Outside_02.mat probe drew nothing).
WATER_EFFECT = r"fxwhitewater|fxfluid|fxwatertile|fxwaterfall|fxrapid|fxfoam"   # water effect textures (foam, falls)
WATER_FLAT_UNITS = 24.0           # z range (game units) up to which a water shape counts as flat (WRStairsStreamL: 10)
WATER_SUFFIX = "_water"
WATER_MATERIAL = "Materials\\Water\\WaterPlaceholder.mat"          # vanilla Water16m.nif's own


# Splash / "in water" (2026-11-26, owner: no splash stepping in): vanilla Water\Water16m.nif's physics is one plain
# hknpBoxShape body on the root node, 16 x 16 m from the surface down 16 m (Water16m1mDepth: 1 m) - the box template
# sfcollision.box_blob patches (verified: check_template passes, read_box (0, 0, -8) +- (8, 8, 8)). A water model gets
# the same: the vanilla water blob (its collision filter = water) as a box over its flat surfaces, WATER_DEPTH_M deep.
WATER_DEPTH_M = 1.5
WATER_PHYSICS_NIF = "meshes/water/water16m.nif"


def water_volume(shapes, template: bytes, depth_m: float = WATER_DEPTH_M) -> Optional[bytes]:
    """The vanilla water box blob reshaped to cover the given (flat) water shapes: their footprint's bounds in the
    model (metres), from the highest surface down depth_m. None without shapes."""
    from . import sfcollision
    pts = []
    for s in shapes:
        R, t, sc = s.rotation, s.translation, s.scale
        pts += [tuple((sc * sum(R[3 * a + k] * v[k] for k in range(3)) + t[a]) * UNIT for a in range(3))
                for v in s.positions]
    if not pts:
        return None
    lo = [min(p[a] for p in pts) for a in range(3)]
    hi = [max(p[a] for p in pts) for a in range(3)]
    top = hi[2]
    return sfcollision.box_blob(template, ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, top - depth_m / 2),
                                ((hi[0] - lo[0]) / 2, (hi[1] - lo[1]) / 2, depth_m / 2))


def is_water_shader(src, shader_ref) -> bool:
    return 0 <= shader_ref < len(src.blocks) and src.type_of(shader_ref) == "BSWaterShaderProperty"


def water_squares(s: nifmod.Fo4Shape, max_squares: int = 300, cell: Optional[float] = None) -> dict:
    """A flat water shape's surface as squares: {"z", "squares": [[cx, cy, side], ...], "area", "covered"} in model
    units (the shape's world transform in the model applied). The footprint (union of its triangles seen from above)
    is rasterised on a grid of `cell` units (default: a twelfth of its smaller side, 4..24); squares only cover grid cells
    entirely inside it (no water past Skyrim's edge), the largest first, until max_squares."""
    import numpy as np
    R, t, sc = s.rotation, s.translation, s.scale
    P = np.array([[sc * sum(R[3 * a + k] * v[k] for k in range(3)) + t[a] for a in range(3)] for v in s.positions])
    T = np.array(s.triangles, dtype=np.int64).reshape(-1, 3)
    lo, hi = P[:, :2].min(0), P[:, :2].max(0)
    size = hi - lo
    g = cell or float(min(24.0, max(4.0, min(size) / 12.0)))
    if not cell and min(size) > 0:                    # a whole number of cells across the smaller side
        g = float(min(size)) / max(1, int(np.ceil(min(size) / g - 1e-9)))
    nx, ny = max(1, int(np.ceil(size[0] / g))), max(1, int(np.ceil(size[1] / g)))
    xs, ys = lo[0] + np.arange(nx + 1) * g, lo[1] + np.arange(ny + 1) * g
    cx, cy = (xs[:-1] + xs[1:]) / 2, (ys[:-1] + ys[1:]) / 2

    def inside(qx, qy):
        """[len(qy), len(qx)] True where the point lies in some triangle (edges count, 1e-6 slack)."""
        X, Y = np.meshgrid(qx, qy)
        hit = np.zeros(X.shape, bool)
        for a, b, c in T:
            (x1, y1), (x2, y2), (x3, y3) = P[a, :2], P[b, :2], P[c, :2]
            d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
            if abs(d) < 1e-12:
                continue
            l1 = ((y2 - y3) * (X - x3) + (x3 - x2) * (Y - y3)) / d
            l2 = ((y3 - y1) * (X - x3) + (x1 - x3) * (Y - y3)) / d
            hit |= (l1 >= -1e-6) & (l2 >= -1e-6) & (1 - l1 - l2 >= -1e-6)
        return hit
    corners, centres = inside(xs, ys), inside(cx, cy)
    free = centres & corners[:-1, :-1] & corners[1:, :-1] & corners[:-1, 1:] & corners[1:, 1:]
    full = int(inside(cx, cy).sum())
    squares = []
    while free.any() and len(squares) < max_squares:
        dp = np.zeros((ny + 1, nx + 1), np.int64)        # largest square ending at each cell (top-right corner)
        for j in range(ny):
            for i in range(nx):
                if free[j, i]:
                    dp[j + 1, i + 1] = 1 + min(dp[j, i + 1], dp[j + 1, i], dp[j, i])
        k = int(dp.max())
        j, i = np.unravel_index(int(dp.argmax()), dp.shape)
        j0, i0 = j - k, i - k
        free[j0:j, i0:i] = False
        squares.append([float(lo[0] + (i0 + k / 2) * g), float(lo[1] + (j0 + k / 2) * g), float(k * g)])
    covered = sum(sq[2] ** 2 for sq in squares)
    return {"z": float(np.median(P[:, 2])), "squares": [[round(v, 3) for v in sq] for sq in squares],
            "area": round(full * g * g, 1), "covered": round(covered, 1), "cell": round(g, 3)}


def convert_static_sse(src: nifmod.NifFile, shapes: List[nifmod.Fo4Shape], out_name: str, material_paths: list,
                       collision_template: Optional[bytes], report: dict, landscape: bool = False,
                       sf_mesh_template: Optional[bytes] = None,
                       stair_layer: Optional[int] = STAIR_HELPER_LAYER, allow_empty: bool = False,
                       animated_node: Optional[bytes] = None, root_collision: Optional[bytes] = None) -> Dict[str, bytes]:
    """sf_mesh_template (a vanilla Starfield multi-shape physics blob, meshcollision.UNIVERSAL_TEMPLATE_NIF): Skyrim's
    own collision becomes native Starfield mesh bodies (native_collision, with stair ramps on stair_layer); boxes are
    the fallback, with the reason in report["native_error"]."""
    files, static_shapes, all_pts = {}, [], []
    for i, s in enumerate(shapes):
        if material_paths[i] is None:                 # effect shader / refraction / skipped shape
            continue
        m = convert_static.shape_to_mesh(s, UNIT)
        data = sfmesh.serialize(m)
        d, f = convert_static.mesh_file_path(data)
        files[f"geometries/{d}/{f}.mesh"] = data
        pts = [sfmesh.decode_position(p, m.scale) for p in m.positions]
        all_pts += pts
        sphere, box = sfnif.bounds_from_points(pts)
        static_shapes.append(sfnif.StaticShape(s.name or f"Shape{i}".encode(), f"{d}\\{f}".encode(),
                                               len(m.triangles) * 3, len(m.positions), material_paths[i], sphere, box))
    if not static_shapes and not allow_empty:
        raise nifmod.NifError("no shape left after skipping effect shaders")
    if all_pts:
        lo = [min(p[a] for p in all_pts) for a in range(3)]
        hi = [max(p[a] for p in all_pts) for a in range(3)]
        report["render_bounds_m"] = [[round(v, 3) for v in lo], [round(v, 3) for v in hi]]
    else:                                             # allow_empty: an editor-marker model, nothing drawn
        lo, hi = [-1e9] * 3, [1e9] * 3
        report["render_bounds_m"] = None
    blobs = None
    if sf_mesh_template is not None:
        try:
            blobs = native_collision(src, sf_mesh_template, report, stair_layer=stair_layer)
        except Exception as e:                       # noqa: BLE001  (fallback by design, reason recorded)
            report["native_error"] = f"{type(e).__name__}: {e}"
            for k in ("source", "bodies", "layers", "skipped_layers", "stair_ramps"):
                report.pop(k, None)
    if blobs is None:
        blobs = collision_boxes(src, collision_template, report, landscape) if collision_template is not None else []
    if report.get("source") == "skyrim-native" and "collision_bounds_m" not in report:
        pts = [p for _l, v, _t in skyrimnif.collision_bodies(src) for p in v]
        if pts:
            report["collision_bounds_m"] = [[round(min(p[a] for p in pts) * UNIT, 3) for a in range(3)],
                                            [round(max(p[a] for p in pts) * UNIT, 3) for a in range(3)]]
    if "collision_bounds_m" in report:               # sanity on real data: collision should overlap the visible model
        cl, ch = report["collision_bounds_m"]
        overlap = all(cl[a] <= hi[a] + 0.5 and ch[a] >= lo[a] - 0.5 for a in range(3))
        report["collision_overlaps_render"] = overlap
    node = out_name.rsplit("/", 1)[-1].encode()
    # root_collision: one physics body on the root node, as vanilla Water\Water16m.nif's water volume
    out = sfnif.build_static_nif(node, static_shapes, child_collision_blobs=blobs,
                                 **({"collision_blob": root_collision} if root_collision is not None else {}),
                                 **({"animated_node": animated_node} if animated_node else {}))
    files[f"meshes/{out_name}.nif"] = nifmod.serialize(out)
    return files


# Spinning parts (skyrimnif.spin_part; 2026-11-18, the mill water wheel): written as a model of their own in the part's
# frame turned so its axis is +Y (the axis Starfield's generic rotate_y01 turns about: the yard fan blades'
# SimpleIdleLoop01 + genericrig + rotate_y01, sf_animated_object_probe), placed by make_skyrim_objects / exterior.place
# on a copy of that fan static. VANILLA_SPIN_SIGN: the direction rotate_y01 turns about +Y (assumed +1, unverified:
# if the wheel turns backwards in game, change it to -1); a part Skyrim turns the other way is written turned 180 deg
# about its Z, which reverses its +Y.
SPIN_SUFFIX = "_spin"
SPIN_NODE = b"Rotate_Y01"         # the node rotate_y01 turns (the vanilla fan blade's own; sfnif.build_static_nif)
VANILLA_SPIN_SIGN = 1
_TO_Y = {0: (0, -1, 0, 1, 0, 0, 0, 0, 1),        # node x -> +y (row-major, v_spin = Q v_node)
         1: (1, 0, 0, 0, 1, 0, 0, 0, 1),
         2: (1, 0, 0, 0, 0, 1, 0, -1, 0)}         # node z -> +y
_FLIP_Z = (-1, 0, 0, 0, -1, 0, 0, 0, 1)


def _m3(a, b):
    return tuple(sum(a[3 * r + k] * b[3 * k + c] for k in range(3)) for r in range(3) for c in range(3))


def _t3(a):
    return (a[0], a[3], a[6], a[1], a[4], a[7], a[2], a[5], a[8])


def _mv(a, v):
    return tuple(a[3 * r] * v[0] + a[3 * r + 1] * v[1] + a[3 * r + 2] * v[2] for r in range(3))


def spin_frame(axis: int, sign: int, vanilla_sign: int = VANILLA_SPIN_SIGN):
    """Q (row-major, node frame -> spin model frame): the node's turning axis onto +Y, then 180 deg about Z when the
    part turns the other way from Starfield's rotate_y01."""
    q = _TO_Y[axis]
    return _m3(_FLIP_Z, q) if sign != vanilla_sign else q


def to_spin_frame(shapes, node_t, node_r, node_s, q):
    """The shapes (world transforms in the source model) moved into the spin model's frame: v_spin =
    Q R_n^T (v_world - t_n) / s_n."""
    inv = _m3(q, _t3(node_r))
    out = []
    for s in shapes:
        t = _mv(inv, tuple(s.translation[a] - node_t[a] for a in range(3)))
        out.append(dataclasses.replace(s, translation=tuple(v / node_s for v in t),
                                       rotation=_m3(inv, s.rotation), scale=s.scale / node_s))
    return out


def convert_skinned_sse(shapes: List[nifmod.Fo4Shape], out_name: str, material_paths: list, bone: str,
                        report: dict) -> Dict[str, bytes]:
    """A worn NIF in which every vertex rides one Starfield bone (rigid skinning, e.g. a weapon held by a bone):
    shapes must already be in that bone's local frame; the bind is identity (drawn at bone_world * vertex), so the
    result does not depend on the skeleton's rest pose."""
    files, skinned = {}, []
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    for i, s in enumerate(shapes):
        if material_paths[i] is None:
            continue
        m = convert_static.shape_to_mesh(s, UNIT)
        m.weights_per_vertex = 4
        m.weights = [(0, 65535), (0, 0), (0, 0), (0, 0)] * len(m.positions)
        data = sfmesh.serialize(m)
        d, f = convert_static.mesh_file_path(data)
        files[f"geometries/{d}/{f}.mesh"] = data
        pts = [sfmesh.decode_position(p, m.scale) for p in m.positions]
        for p in pts:
            for a in range(3):
                lo[a], hi[a] = min(lo[a], p[a]), max(hi[a], p[a])
        (cx, cy, cz, r), _box = sfnif.bounds_from_points(pts)
        skinned.append(sfnif.SkinnedShape(s.name or f"Shape{i}".encode(), f"{d}\\{f}".encode(), len(m.triangles) * 3,
                                          len(m.positions), material_paths[i], [bone.encode()],
                                          [((cx, cy, cz, r), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)]))
    if not skinned:
        raise nifmod.NifError("no shape left after skipping effect shaders")
    report["render_bounds_m"] = [[round(v, 3) for v in lo], [round(v, 3) for v in hi]]
    report["skinned_to"] = bone
    out = sfnif.build_skinned_nif(out_name.rsplit("/", 1)[-1].encode(), skinned)
    files[f"meshes/{out_name}.nif"] = nifmod.serialize(out)
    return files


class SkyrimConverter(FlameMixin, pipeline.Converter):
    """pipeline.Converter with a Skyrim source (bsa.SkyrimArchives) and Skyrim materials / geometry / collision."""

    def __init__(self, src, staging, texconv_exe, content_resources, collision_template=None, prefix="skyrim",
                 max_texture=None, shape_hook=None, sf_mesh_template=None, stair_layer=STAIR_HELPER_LAYER):
        super().__init__(src, staging, texconv_exe, content_resources, collision_template, prefix=prefix,
                         no_collision_pattern="", max_texture=max_texture)
        # shape_hook(nif, shapes, report) -> shapes: change the geometry before conversion (skyrimweapon.weapon_shapes
        # moves weapons into Starfield's WEAPON frame and drops scabbards)
        self.shape_hook = shape_hook
        self.sf_mesh_template = sf_mesh_template      # native Skyrim collision (convert_static_sse); None = boxes
        self.stair_layer = stair_layer                # layer of the stair ramps added to native collision; None = none
        # flames (skyrimfire): effect shapes whose texture matches fire_pattern become emissive effect materials;
        # AddOnNode<n> with n in addon_models gets that add-on's flame particles as cards; fire=False = old behaviour
        self.fire = True
        self.fire_pattern = skyrimfire.FIRE_EFFECT
        self.addon_models = dict(skyrimfire.ADDON_MODELS)
        self._effect_template = None
        self._addon_flames = {}
        self.flame_style = "skyrim"                   # skyrimfire.FLAME_STYLES
        self.sf_candle_mesh = None                    # sfmesh.SfMesh of Starfield's candle flame (candle_style starfield)
        self._layered = set()                         # material paths that take normalize_card_uvs
        # turning parts (skyrimnif.spin_part) as models of their own: only for callers that place them (make_skyrim_objects
        # convert); elsewhere (interiors, weapons, first run) the part stays in the model, standing still
        self.split_spin = False

    def skyrim_material(self, diffuse: str, normal: str, test: bool, blend: bool, ref: int,
                        flat_normal_ok: bool = False, albedo_tint: Optional[tuple] = None,
                        albedo_target: Optional[tuple] = None, specular: Optional[dict] = None) -> Optional[str]:
        """specular: the shape's Skyrim specular (skyrimnif.specular), giving the roughness map (2026-11-25: every object
        had a uniform 'fairly rough' sheen; Skyrim's road is masked to ~14 % and its rocks have none). Not part of the
        material's name, so converted files keep their names: a second shape with the same textures but another
        specular uses the first one's material (counted in stats["specular_conflicts"])."""
        kind = "decal" if blend and not test else "cutout" if test else "opaque"
        ident = "|".join([diffuse.replace("\\", "/").lower(), normal.replace("\\", "/").lower(), kind, str(ref)]
                         + ([",".join(f"{v:.3f}" for v in albedo_tint)] if albedo_tint else [])
                         + (["to:" + ",".join(str(int(v)) for v in albedo_target)] if albedo_target else []))
        stem = re.sub(r"^textures[\\/]", "", diffuse.replace("\\", "/"), flags=re.I).lower()
        stem = os.path.splitext(stem)[0] + "_" + hashlib.sha1(ident.encode()).hexdigest()[:8]
        if kind == "decal":
            stem = "decals/" + stem
        key = "sky:" + stem
        spec_of = self.__dict__.setdefault("_specular_of", {})
        if key in spec_of and spec_of[key] != specular:
            self.stats["specular_conflicts"] = self.stats.get("specular_conflicts", 0) + 1
        if key not in self._materials:
            spec_of[key] = specular
            try:
                self._materials[key] = self._convert_texture_set(stem, diffuse, normal, "", alpha_test=test,
                                                                 alpha_ref=ref, decal=(kind == "decal"),
                                                                 flat_normal_ok=flat_normal_ok,
                                                                 albedo_tint=albedo_tint, albedo_target=albedo_target,
                                                                 skyrim_specular=specular)
                self.stats["materials_ok"] += 1
            except Exception as e:                    # noqa: BLE001  (fallback by design; reason is recorded)
                self._materials[key] = None
                self.stats["materials_fallback"] += 1
                self.material_errors[key] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    def skyrim_hair_material(self, diffuse: str, normal: str, ref: int,
                             color: Optional[tuple] = None, opacity_ramp: Optional[tuple] = None,
                             strands: bool = False, tint: Optional[tuple] = None,
                             transpose: bool = False, orient: bool = False,
                             look: Optional[str] = None, coverage: float = 1.0, region=None,
                             cutout: Optional[int] = None, vanilla_maps: bool = False) -> Optional[str]:
        """A Starfield hair-shader material (Hair1Layer, cm.build_hair_mat) for a Skyrim hair texture: the diffuse's
        colour (recoloured to average `color`, sRGB 0-255, when given: pipeline.recolor) and its alpha as the opacity
        map; None when it cannot be made (the caller falls back). orient: the strands are cut along the texture's own
        strands region by region (pipeline.strand_orientation; the map is kept: hair_orientation_of). look:
        diagnostic variants: 'flat' (the albedo one colour, its visible mean), 'solid' (opacity full everywhere).
        coverage > 1: the alpha made denser before the strand cut, 1 - (1 - a) ** coverage (shapes Skyrim
        alpha-blended, e.g. the hairlines: blended they read as a coat of colour, cut into strands as thin hair).
        region: UV points (n, 2) of the part of the texture the shape shows: its alpha is first scaled to its own
        level there (pipeline.normalize_region_alpha); the material is then that shape's own. cutout: Skyrim's
        alpha-test threshold (0-255): solid over it, the strand cut only near it (pipeline.cutout_alpha).
        vanilla_maps: albedo, AO and hair ID in the ranges of Starfield's own hair (pipeline.VANILLA_*)."""
        stem = re.sub(r"^textures[\\/]", "", diffuse.replace("\\", "/"), flags=re.I).lower()
        stem = os.path.splitext(stem)[0] + "_hair"
        if color:
            stem += "_" + "".join(f"{int(v):02x}" for v in color[:3])
        if transpose:                               # strands turned to run down the texture (skyrimhair.strand_axis)
            stem += "_rot"
        if tint:                                    # Skyrim's hair tint, multiplied in (an NPC's own colour)
            stem += "_t" + "".join(f"{min(255, int(round(v * 255))):02x}" for v in tint[:3])
        if orient and strands:                      # strands cut region by region (kept apart from KS's files)
            stem += "_o"
        if look:
            stem += "_" + look
        if coverage > 1.0:
            stem += "_c%g" % coverage
        if cutout is not None:
            stem += "_k%d" % int(cutout)
        if vanilla_maps:
            stem += "_v"
        if region is not None and len(region):      # keyed by the coarse cells it touches: hairlines sampling the
            import numpy as np                       # same part of the texture share one material (2026-11-03: one
            cells = np.unique(np.floor(np.mod(np.asarray(region, float), 1.0) * 16).astype(int), axis=0)   # per
            stem += "_r" + hashlib.sha1(cells.tobytes()).hexdigest()[:8]    # shape re-converted the atlas ~45x)
        key = "skyhair:" + stem + ("|ramp:%d,%d" % tuple(opacity_ramp) if opacity_ramp else "") + \
            ("|strands" if strands else "")
        if key not in self._materials:
            try:
                self._materials[key] = self._convert_texture_set(stem, diffuse, normal, "", alpha_test=True,
                                                                 alpha_ref=ref, flat_normal_ok=True, hair=True,
                                                                 albedo_target=color, opacity_ramp=opacity_ramp,
                                                                 strands=strands, albedo_tint=tint,
                                                                 transpose=transpose, orient=orient and strands,
                                                                 look=look, coverage=coverage, region=region,
                                                                 cutout=cutout, vanilla_maps=vanilla_maps)
                if self._materials[key] is not None and stem in self.hair_orientation:
                    self._hair_material_stem[self._materials[key]] = stem
                self.stats["materials_ok"] += 1
            except Exception as e:                    # noqa: BLE001  (fallback by design; reason is recorded)
                self._materials[key] = None
                self.material_errors[key] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    @property
    def _hair_material_stem(self) -> dict:
        if "_hair_mat_stem" not in self.__dict__:
            self._hair_mat_stem = {}
        return self._hair_mat_stem

    def hair_coverage_of(self, material: Optional[str]):
        """The opacity record (pipeline: alpha mean, share over the threshold, share after the strand cut) of a hair
        material made with orient=True, or None."""
        stem = self._hair_material_stem.get(material) if material else None
        return self.hair_coverage.get(stem) if stem else None

    def hair_orientation_of(self, material: Optional[str]):
        """The strand_orientation map (True: strands along U) of a hair material made with orient=True, or None."""
        stem = self._hair_material_stem.get(material) if material else None
        return self.hair_orientation.get(stem) if stem else None

    def _shape_material(self, src, s, flat_normal_ok: bool = False,
                        albedo_tint: Optional[tuple] = None, albedo_target: Optional[tuple] = None) -> Optional[str]:
        """flat_normal_ok: a diffuse without a normal map converts with a flat normal (Skyrim grass) instead of
        falling back to the neutral material. albedo_target: sRGB the visible colour is recoloured to average (Skyrim's
        skin textures are tinted by the engine; 2026-11-20 children's bare skin)."""
        if s.shader_ref < 0:
            return self.neutral
        kind = src.type_of(s.shader_ref)
        if kind == "BSEffectShaderProperty":          # fire / candle flames: effect material; glow, fog, magic: skipped
            m = self.skyrim_flame_material(src, s.shader_ref) if self.fire else None
            return m or (self.skyrim_water_effect_material(src, s.shader_ref)
                         if getattr(self, "water_effects", True) else None)
        if skyrimnif.refraction(src, s.shader_ref):  # heat haze / refraction: not translated, like effect shaders
            return None
        paths = swap_textures(skyrimnif.texture_set(src, s.shader_ref),
                              getattr(self, "_alt_by_block", {}).get(getattr(s, "block", None)))
        if skyrimnif.normal_map_as_diffuse(paths):
            return None
        if not paths or not paths[0]:
            return self.neutral
        test, blend, ref = skyrimnif.alpha_test(src, s.alpha_ref)
        normal = paths[1] if len(paths) > 1 else ""
        if normal and skyrimnif.model_space_normals(src, s.shader_ref):
            # an object-space normal map would light the surface wrongly in Starfield's tangent-space shader: drop it
            # and light from the mesh's own vertex normals (flat normal map) until a model -> tangent bake exists
            normal, flat_normal_ok = "", True
            self.stats["model_space_normals_dropped"] = self.stats.get("model_space_normals_dropped", 0) + 1
        if not normal and not (blend and not test) and not flat_normal_ok:
            return self.neutral
        mat = self.skyrim_material(paths[0], normal, test, blend, ref, flat_normal_ok=flat_normal_ok,
                                   albedo_tint=albedo_tint,
                                   **({"specular": skyrimnif.specular(src, s.shader_ref)}
                                      if getattr(self, "skyrim_specular", False) else {}),
                                   **({"albedo_target": albedo_target} if albedo_target is not None else {}))
        if mat is None and blend and not test:
            return None                               # an overlay we could not convert: leave it out, as FO4 does
        return mat or self.neutral

    def skyrim_water_effect_material(self, src, shader_ref) -> Optional[str]:
        """Skyrim's moving water effects (2026-11-26, owner: the streams lack Skyrim's flow, no waterfalls): foam on the
        streams (FXWhiteWater01), waterfall sheets (FXfluidTile01), the Wind District fall (FXwaterTile01) are effect
        shaders with a scrolling texture faded by vertex alpha. They become the same scrolling effect material as the
        flames (FlameMixin.flame_material: Skyrim's own UV scroll controller, vertex colour blend), kind "water": a dim
        emittance (skyrimfire.EMITTANCE). None for any other effect (glow, fog, magic stay skipped)."""
        try:
            info = skyrimfire.effect_shader(src, shader_ref)
        except Exception:                                           # noqa: BLE001
            return None
        if not re.search(WATER_EFFECT, info.get("source") or "", re.I):
            return None
        return self.flame_material(info["source"], **skyrimfire.bake_params(info),
                                   scroll=skyrimfire.uv_scroll(info["controllers"]), kind="water",
                                   vertex_color=info["vertex_alpha"])

    def _threshold_material(self, mat: str, ref: int) -> Optional[str]:
        """The cutout material `mat` (skyrim_material: materials\\<prefix>\\<stem>.mat over textures\\<prefix>\\<stem>_*)
        with another alpha threshold: the same textures, a material of its own (<stem>_va<ref>). None when `mat` is not
        such a material or has no opacity map."""
        pre = f"materials\\{self.prefix}\\".lower()
        low = mat.lower()
        if not (low.startswith(pre) and low.endswith(".mat")) or low[len(pre):].startswith("decals"):
            return None
        stem = mat[len(pre):-4].replace("\\", "/")
        key = f"skyva:{stem}|{ref}"
        if key not in self._materials:
            tex_rel = f"textures/{self.prefix}/{stem}"
            if not os.path.isfile(os.path.join(self.staging, *f"{tex_rel}_opacity.dds".split("/"))):
                return None
            vstem = f"{stem}_va{ref:03d}"
            m = cm.build_mat(self.template_mat, "FO4Port_" + re.sub(r"[^a-z0-9]+", "_", vstem),
                             *(cm.game_path(f"{tex_rel}_{k}.dds") for k in ("color", "normal", "rough")),
                             opacity=cm.game_path(f"{tex_rel}_opacity.dds"), alpha_threshold=ref / 255.0)
            rel = f"materials/{self.prefix}/{vstem}.mat"
            p = os.path.join(self.staging, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(cm.dump_mat(m))
            self._materials[key] = rel.replace("/", "\\")
        return self._materials[key]

    def _vertex_alpha_cut(self, src, shapes, mats, report: dict):
        """(shapes, materials) with every alpha-tested Vertex_Alpha shape cut along its vertex alpha (VA_BANDS,
        clip_vertex_alpha): only the parts Skyrim draws, each with the threshold its vertex alpha needs. A shape
        whose vertex alpha is all under the threshold is gone; one whose parts would not fit u16 indices stays whole."""
        out_s, out_m = [], []
        for s, m in zip(shapes, mats):
            if (m is None or m == self.neutral or not s.colors or "\\effects\\" in m.lower()
                    or not skyrimnif.vertex_alpha(src, s.shader_ref)):
                out_s.append(s)
                out_m.append(m)
                continue
            test, _blend, ref = skyrimnif.alpha_test(src, s.alpha_ref)
            if not test or min(c[3] for c in s.colors) >= VA_SOLID:
                out_s.append(s)
                out_m.append(m)
                continue
            pre = f"materials\\{self.prefix}\\"
            stem = m[len(pre):-4].replace("\\", "/") if m.lower().startswith(pre.lower()) else ""
            has_opacity = bool(stem) and os.path.isfile(
                os.path.join(self.staging, *f"textures/{self.prefix}/{stem}_opacity.dds".split("/")))
            bands = vertex_alpha_bands(ref, has_opacity)
            parts = []
            for lo, hi, thr in bands:
                part = clip_vertex_alpha(s, lo, hi)
                if part is not None:
                    parts.append((part, m if thr == ref else (self._threshold_material(m, thr) or m)))
            if not bands or any(len(p.positions) > MAX_VERTICES for p, _m in parts):
                out_s.append(s)
                out_m.append(m)
                report["vertex_alpha_too_big"] = report.get("vertex_alpha_too_big", 0) + bool(bands)
                continue
            report["vertex_alpha_shapes"] = report.get("vertex_alpha_shapes", 0) + 1
            report["vertex_alpha_parts"] = report.get("vertex_alpha_parts", 0) + len(parts)
            self.stats["vertex_alpha_shapes"] = self.stats.get("vertex_alpha_shapes", 0) + 1
            for p, pm in parts:
                out_s.append(p)
                out_m.append(pm)
        return out_s, out_m

    def _spin_model(self, src, spin: dict, shapes, out_name: str, res: dict) -> Dict[str, bytes]:
        """The spinning part as its own static model (no collision: it turns) in the spin frame; res["spin"] tells
        make_skyrim_objects where to place it: model, pivot (metres, source model space), frame (row-major rotation of
        the spin model's axes in the source model), the Skyrim node, direction and period."""
        t, r, sc = nifmod.world_transforms(src)(spin["block"])
        q = spin_frame(spin["axis"], spin["sign"])
        moved = to_spin_frame(shapes, t, r, sc, q)
        mats = [self._shape_material(src, s) for s in moved]
        report = {}
        files = convert_static_sse(src, moved, out_name, mats, None, report, animated_node=SPIN_NODE)
        lo, hi = [float("inf")] * 3, [float("-inf")] * 3
        for m in moved:
            for v in m.positions:
                w = _mv(m.rotation, v)
                for a in range(3):
                    c = (m.scale * w[a] + m.translation[a]) * UNIT
                    lo[a], hi[a] = min(lo[a], c), max(hi[a], c)
        res["spin"] = {"model": out_name.replace("/", "\\") + ".nif", "pivot_m": [round(v * UNIT, 5) for v in t],
                       "frame": [round(v, 6) for v in _m3(r, _t3(q))], "scale": round(sc, 6), "node": spin["node"], "axis": spin["axis"],
                       "sign": spin["sign"], "period_s": round(spin["period"], 3), "shapes": len(moved),
                       "bounds": [[round(v, 4) for v in lo], [round(v, 4) for v in hi]],
                       "flipped": q != _TO_Y[spin["axis"]]}
        return files

    def convert_nif(self, nif_name: str, skin_bone: Optional[str] = None, out_suffix: str = "",
                    alt_textures: Optional[list] = None) -> dict:
        """skin_bone: write a worn NIF rigidly skinned to that Starfield bone (the shape hook must put the geometry in
        the bone's frame) instead of a static model; out_suffix is appended to the output name. alt_textures: the
        base's alternate textures (skyrimrefs.alternate_textures, matched to shapes by alt_texture_blocks): the model
        is written as <name>_alt<id> with those shapes' texture sets swapped."""
        res = {"nif": nif_name, "ok": False}
        self._alt_by_block = {}
        spin_ok = not (skin_bone or out_suffix)
        if alt_textures:
            out_suffix += "_alt" + skyrimrefs.alt_id(alt_textures)
        try:
            raw = self.src.mesh(nif_name)
            if raw is None:
                raise FileNotFoundError("mesh not in the Skyrim archives or loose files")
            src = nifmod.parse(raw)
            if not skin_bone:                         # placed models: Skyrim ignores the root node's own transform
                cleared = skyrimnif.clear_root_transform(src)
                if cleared:
                    res["root_transform_cleared"] = True
                    self.stats["root_transforms_cleared"] = self.stats.get("root_transforms_cleared", 0) + 1
            shapes = skyrimnif.trishapes(src)
            if alt_textures:
                self._alt_by_block = alt_texture_blocks(shapes, alt_textures)
                res["alt_shapes"] = len(self._alt_by_block)
                if not self._alt_by_block:
                    raise ValueError("no shape of the model matches its alternate textures")
            hook_report = {}
            if self.shape_hook is not None:
                shapes = self.shape_hook(src, shapes, hook_report)
            # editor-only geometry left out (skyrimnif.editor_only): EditorMarker-named shapes anywhere, and untextured
            # shapes in a *Marker.nif model (2026-11-16: the whole model dropped took the forge pit and anvil with it:
            # BlacksmithForgeMarker.nif holds the real forge too); a model with nothing else becomes an empty model
            marker_model = bool(skyrimnif.MARKER_MODEL_RE.search(nif_name.replace("/", "\\")))
            hidden = skyrimnif.editor_marker_blocks(src)
            culled = frozenset(skyrimnif.hidden_blocks(src))      # the hidden flag (2026-11-18: the mill wheel axle)
            why = [skyrimnif.editor_only(src, s, marker_model, hidden, culled) for s in shapes]
            dropped = [f"{(s.name or b'').decode('latin-1')} ({w})" for s, w in zip(shapes, why) if w]
            editor_shapes = len(dropped)
            shapes = [s for s, w in zip(shapes, why) if not w]
            spin, spin_shapes = (skyrimnif.spin_part(src) if self.split_spin and spin_ok else None), []
            if spin is not None:                          # the turning part: a model of its own (below)
                sub = skyrimnif.subtree(src, spin["block"])
                spin_shapes = [s for s in shapes if s.block in sub]
                shapes = [s for s in shapes if s.block not in sub]
                if not spin_shapes:
                    spin = None
            if editor_shapes:
                self.stats["editor_marker_shapes"] = self.stats.get("editor_marker_shapes", 0) + editor_shapes
                self.stats.setdefault("editor_marker_models", {})[os.path.basename(nif_name).lower()] = dropped
            if not shapes and not editor_shapes and not spin_shapes:
                raise ValueError("no triangle geometry")
            mats = [self._shape_material(src, s) for s in shapes]
            water, water_shapes, flat_water = [], [], []   # Skyrim water shapes: a water model of their own (below)
            if not skin_bone:
                for i, s in enumerate(shapes):
                    if not is_water_shader(src, s.shader_ref):
                        continue
                    zs = [s.scale * sum(s.rotation[6 + k] * v[k] for k in range(3)) + s.translation[2]
                          for v in s.positions] or [0.0]
                    if max(zs) - min(zs) <= WATER_FLAT_UNITS:   # squares too: stage --water-squares (the first way)
                        water.append(dict(water_squares(s), shape=(s.name or b"").decode("latin-1")))
                    else:
                        water.append({"sloped": True, "shape": (s.name or b"").decode("latin-1"),
                                      "z_range": round(max(zs) - min(zs), 1)})
                    water_shapes.append(s)
                    if "sloped" not in water[-1]:
                        flat_water.append(s)
                    mats[i] = None                    # not in the model itself
            water_only = bool(water) and all(m is None or is_water_shader(src, s.shader_ref)
                                             for s, m in zip(shapes, mats))
            va_report = {}
            shapes, mats = self._vertex_alpha_cut(src, shapes, mats, va_report)
            flame_shapes = sum(1 for s, m in zip(shapes, mats) if m and "\\effects\\" in m)
            shapes = [skyrimfire.normalize_card_uvs(s) if m in getattr(self, "_layered", ()) else s for s, m in zip(shapes, mats)]
            doubled = too_big = 0
            for i, s in enumerate(shapes):
                if mats[i] is not None and skyrimnif.double_sided(src, s.shader_ref):
                    d = with_back_faces(s)
                    if d is None:
                        too_big += 1                  # left one-sided: visible from the front only
                    else:
                        shapes[i], doubled = d, doubled + 1
            cards = []
            if self.fire and not skin_bone:
                cards, card_mats = self.addon_flames(src)
                own, own_mats = self.model_flames(src)
                cards, card_mats = cards + own, card_mats + own_mats
                shapes, mats = list(shapes) + cards, list(mats) + card_mats
            if mats and all(m is None for m in mats) and not water:
                raise ValueError("only effect-shader / refraction shapes, skipped")
            if not shapes and skin_bone:
                raise ValueError("only editor-marker geometry")
            rel = re.sub(r"^meshes[\\/]", "", nif_name.replace("\\", "/"), flags=re.I)
            out_name = f"{self.prefix}/{os.path.splitext(rel)[0].lower()}{out_suffix}"
            report = {}
            if skin_bone:
                files = convert_skinned_sse(shapes, out_name, mats, skin_bone, report)
            else:
                # a model that is only water (a pool, the Gildergreen's ring) keeps no collision: nobody walks on it
                files = convert_static_sse(src, shapes, out_name, mats,
                                           None if water_only else self.collision_template, report,
                                           landscape=bool(LANDSCAPE_RE.search(nif_name)),
                                           sf_mesh_template=None if water_only else self.sf_mesh_template,
                                           stair_layer=self.stair_layer,
                                           allow_empty=editor_shapes > 0 or bool(spin_shapes) or bool(water))
            if spin is not None:
                files.update(self._spin_model(src, spin, spin_shapes, out_name + SPIN_SUFFIX, res))
            if water_shapes:                          # the water surfaces as their own model (a water activator's)
                wrep = {}
                tpl = getattr(self, "water_physics_template", None)
                volume = water_volume(flat_water, tpl) if tpl and flat_water else None
                files.update(convert_static_sse(src, water_shapes, out_name + WATER_SUFFIX,
                                                [WATER_MATERIAL] * len(water_shapes), None, wrep,
                                                root_collision=volume))
                res["water_model"] = {"model": (out_name + WATER_SUFFIX).replace("/", "\\") + ".nif",
                                      "bounds": wrep.get("render_bounds_m"), "shapes": len(water_shapes),
                                      "volume": volume is not None}
            for relp, data in files.items():
                p = os.path.join(self.staging, *relp.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(data)
            res.update(ok=True, out_name=out_name, shapes=len(shapes), materials=mats,
                       collision="skyrim" if self.collision_template is not None else None,
                       collision_report=report, skipped_effect_shapes=sum(1 for m in mats if m is None),
                       fallback_materials=sum(1 for m in mats if m == self.neutral),
                       double_sided_shapes=doubled, double_sided_too_big=too_big,
                       flame_shapes=flame_shapes, flame_cards=len(cards),
                       sf_effects=self.model_fire_effects(src) if self.fire and not skin_bone else [],
                       addon_nodes=len(skyrimfire.addon_nodes(src)), editor_marker_shapes=editor_shapes,
                       **({"water": water} if water else {}), **va_report, **hook_report)
            self.stats["assets"] += 1
        except Exception as e:                       # noqa: BLE001  (recorded per asset, batch continues)
            res["reason"] = f"{type(e).__name__}: {e}"
            self.stats["failed"] += 1
        self._alt_by_block = {}
        return res
