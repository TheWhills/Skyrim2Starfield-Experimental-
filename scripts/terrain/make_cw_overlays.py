"""Commonwealth terrain as Starfield overlay worldspaces: one overlay or a grid of edge-matched tiles for any FO4 cell
rectangle (docs/terrain/commonwealth-scale.md). Experiment 3 = 2 x 2 tiles of 14 x 14 cells around Sanctuary,
Vault 111 and Red Rocket. core64 (section 6a) = one 64 x 64-cell overlay of the playable core with --plan rays: one
coc arrival per entry, probes at increasing distance from it in one direction each.

    python scripts/terrain/make_cw_overlays.py build --fo4 <Fallout4.esm> --sf-data <Starfield Data> --out <dir>
        [--fo4-cells -35 10 -6 40] [--tile 14] [--prefix FO4CW3] [--plugin FO4TerrainExp3.esm] ...
    dotnet run --project dotnet/TerrainOverlays -c Release -- <Starfield.esm> <dir>     (reads overlays_params.json)
    python scripts/terrain/make_cw_overlays.py check --sf-data <Starfield Data> --out <dir>
    python scripts/terrain/make_cw_overlays.py analyse --out <dir> --runs <runner queue folder> [--json <file>]

build writes, all OUTSIDE the repo (derived game data):
  Data/Terrain/<WORLD>.btd                     one BTD per tile, FO4 heights / 70 at CW positions, one shared range
  Data/textures/terrain/overlaymasks/<world>.dds   255 on outer edges' cell ring (north / south only in pairs by
                                                   default: mask row order unresolved), 0 on seams between tiles
  overlays_params.json   what dotnet/TerrainOverlays needs (worlds, blocks, FNAM, anchors, COC, lat/long per tile)
  plan.json              runner format (make_plan): per tile its own heights and seam sides; in the first tile's
                         landing a group entry (seam pairs: passes only if the tiles lie edge to edge), one locate
                         transect per other tile and an edges entry. Every entry uses the coc'd tile's own frame and
                         spawn (x, y) for the merge offset, a z_ref probe for the Z offset, waits for the whole fall.
  expected.json, README.txt, preview.png
check re-reads the staged files: decoded heights at every plan point, seam continuity, masks, the entry contract
(frame = coc'd tile, spawn_local, z_ref, drop and wait, jump lengths) and a raw record walk of both plugins (WRLD,
XLCN/LCTN, SFBK, anchor, COC cell, PNDT CNAM entries).
analyse reads the runner's obs.json files and reports what they measured, whatever the verdict: each landing's merge
offset, the Z offset, every point's error and where each tile really sits (whole-cell shift that fits the heights).

Placement (hypothesis H_ll, src/fo4sf/overlay_grid.py): tile lat/long from one measured registration (World01 on
Mars) at true planet scale. Supported, not verified. Our persistent anchors read back their unmerged local position
in game (exp1d, exp2b), so placement is measured from heights (locate entries + analyse), not from anchors.
"""
import argparse
import json
import math
import os
import re
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))
sys.path.insert(0, HERE)
from fo4sf import btd, fo4land, overlay  # noqa: E402
from fo4sf import overlay_grid as og  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402
import overlay_records as orc  # noqa: E402

SPAWN_ABOVE = 2.0
MAX_SLOPE = 25.0
FO4_GRID = (-96, 95)                    # Commonwealth LAND cells on both axes (verified, architecture.md 2)
# FO4 references used as landmarks (Fallout4.esm, Commonwealth; FO4 units): the Red Rocket building (as experiment 2)
# and the Sanctuary / Vault 111 map markers
LANDMARKS = (("redrocket", 0x000211C0, -69232.0, 80304.0),
             ("sanctuary", 0x00072A48, -80768.19, 88174.80),
             ("vault111", 0x0009F272, -89271.98, 91369.30))
DIST = {"near": (0.8, 2.7), "ring": (40.0, 60.0), "inner": (140.0, 170.0)}   # metres from the seam, per side
PLAN_KEYS = ("coc", "label", "anchor", "spawn_local", "z_ref", "drop_z", "settle_ms", "points")
RAY_PLAN_KEYS = ("coc", "label", "spawn_local", "z_ref", "drop_z", "settle_ms", "points")
# Drops (runner qstep.ps1 'terrain'): every point of an entry is dropped from drop_z (entry frame) + the runner's Z
# offset, which is 0 here because spawn_local carries no z: a spawn read mid-fall (exp1d a1 z -500, exp2b a2 z -354)
# would otherwise lower every drop below the ground. The Z offset is judged from the z_ref probe instead.
DROP_MARGIN = 40.0      # metres above the highest expected point of an entry (room for an unknown Z offset)
MARS_G = 3.71           # m/s2, Mars surface gravity (0.38 g), for fall times
FALL_BELOW = 20.0       # the wait also covers a fall this far below the lowest expected point
MIN_SETTLE_MS = 8000
MAX_JUMP = 400.0        # waypoint probes keep consecutive setpos jumps at or under about this (exp2b a1: a 349 m jump
#                         ended 141.9 m short, a 560 m one arrived; the cause is unknown, shorter is the cheap guard)
LOCATE_STEP = 200.0     # spacing of locate probes along a transect
EDGE_KEEP = 150.0       # locate and waypoint probes stay this far inside tile edges (outside every merge ring)
# --plan rays (one large overlay, e.g. the 64-cell core): every entry is one coc arrival and one direction, probes at
# these distances from the arrival's flat point (the first, z_ref), all at least RAY_EDGE_KEEP inside the overlay.
# exp3 (2026-10-11) read real terrain only in the overlay it arrived in; these entries measure how far one overlay
# loads around an arrival.
RAY_DISTANCES = (0.0, 200.0, 500.0, 1000.0, 2000.0, 3000.0)
RAYS = (("nw", 135.0), ("ne", 45.0), ("e", 0.0), ("se", -40.0), ("s", -90.0), ("w", 180.0))   # name, bearing (deg)
RAY_EDGE_KEEP = 200.0   # two cells
RAY_FLAT_DEG = 10.0     # ray probes prefer vertices this flat within their snap radius (16 vertices = 29 m)
ARRIVAL = "redrocket"   # landmark the single overlay's COC marker sits next to (its nearest flat vertex)
# further landmarks for ray plans, added to the ray nearest their bearing from the arrival (Fallout4.esm, FO4 units):
# the Sanctuary bridge (STAT NorthBridge) and the Concord map marker (cell ConcordExt, -15, 17)
RAY_LANDMARKS = (("sanctuary_bridge", 0x0001F970, -76744.0, 83336.0),
                 ("concord", 0x00082138, -60286.01, 72977.79))
COC_MARKER = 0x000032       # STAT COCMarkerHeading (Starfield.esm), the COC cell's marker base
EXP2B_LATLON = (0.3, -1.2)  # FO4CW_Commonwealth's Mars registration (rad): merged at planet cell (-12, -27), in game


def m(units):
    return units / tg.UNITS_PER_METRE


def landmarks(a):
    """(name, form id, x, y) landmarks in source units: LANDMARKS unless the caller set a.landmarks (another source)."""
    return tuple(getattr(a, "landmarks", LANDMARKS))


def ray_landmarks(a):
    return tuple(getattr(a, "ray_landmarks", RAY_LANDMARKS))


def arrival_name(a):
    """Landmark the single overlay's COC marker sits next to: ARRIVAL unless the caller set a.arrival."""
    return getattr(a, "arrival", ARRIVAL)


# ---------------------------------------------------------------------------------------------------------------- FO4
class Fo4Heights:
    """Decoded FO4 LAND vertex grids {(cx, cy): (33, 33) FO4 units} from Fallout4.esm or a cached .npz
    (arrays 'grid' (N, 2) cell coordinates and 'heights' (N, 33, 33)).

    The source is a parameter so other games with the same LAND/VHGT layout can use this builder (Skyrim:
    src/fo4sf/skyrimland.py): `world` is the WRLD EditorID, `grid` the inclusive LAND cell rectangle (x0, x1, y0, y1)
    and `fill` the height (game units) of a cell inside the grid that has no VHGT. Fallout 4's defaults are unchanged:
    Commonwealth, -96..95 on both axes, and a missing cell is an error."""

    def __init__(self, esm=None, npz=None, world="Commonwealth", grid=None, fill=None):
        self.esm, self.npz, self.grids = esm, npz, {}
        self.world = world
        self.grid = tuple(grid) if grid else (FO4_GRID[0], FO4_GRID[1], FO4_GRID[0], FO4_GRID[1])
        self.fill = fill

    def load(self, cells):
        want = {c for c in cells if c not in self.grids}
        if not want:
            return
        if self.npz:
            z = np.load(self.npz)
            for (x, y), h in zip(z["grid"].tolist(), z["heights"]):
                if (x, y) in want:
                    self.grids[(x, y)] = h.astype(np.float64)
        else:
            with fo4land.Plugin(self.esm) as p:
                world = p.read_world(self.world, cells=want, refs=False)
            for xy, c in world["cells"].items():
                if c["vhgt"]:
                    self.grids[xy] = fo4land.decode_vhgt(c["vhgt"])

    def merged(self, x0, x1, y0, y1):
        """Merged vertex grid and its CW-unit origin for the inclusive FO4 cell rectangle (clamped to the LAND grid)."""
        gx0, gx1, gy0, gy1 = self.grid
        x0, x1 = max(x0, gx0), min(x1, gx1)
        y0, y1 = max(y0, gy0), min(y1, gy1)
        cells = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
        self.load(cells)
        missing = [c for c in cells if c not in self.grids]
        if missing and self.fill is None:
            sys.exit(f"FO4 cells without VHGT: {missing[:8]} ({len(missing)})")
        if missing:                           # the engine draws a cell without LAND at the world's default height
            from fo4sf import skyrimland
            return (skyrimland.merge_with_fill(self.grids, x0, x1, y0, y1, self.fill),
                    (x0 * tg.FO4_CELL_UNITS, y0 * tg.FO4_CELL_UNITS))
        g, _ = fo4land.merge_cells(self.grids, x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        return g, (x0 * tg.FO4_CELL_UNITS, y0 * tg.FO4_CELL_UNITS)


def tile_vertices(fo4, tile):
    """FO4 vertex grid around a tile (one extra FO4 cell on every side) and its origin in FO4 units."""
    x0, x1, y0, y1 = tile.bounds_m
    cx0, cx1, cy0, cy1 = tg.fo4_cells_covering(x0, x1, y0, y1)
    return fo4.merged(cx0 - 1, cx1 + 1, cy0 - 1, cy1 + 1)


def tile_strips(fo4, tile, rows=1024):
    """Tile heights in metres at its BTD sample positions (CW frame), as (first row, block [rows, cols]) strips from
    the south, so a 64- or 90-cell overlay never holds its whole float grid. Each strip resamples only the FO4 vertex
    rows it needs; the arithmetic per sample is the same as one call over the whole grid (all coordinates here are
    exact binary fractions), so the result is identical (tests compare with tile_heights)."""
    g, (ox, oy) = tile_vertices(fo4, tile)
    xs, ys = tile.sample_coords()
    xu = xs * tg.UNITS_PER_METRE
    sp = tg.FO4_VERTEX_UNITS
    last = g.shape[0] - 1
    for r0 in range(0, len(ys), rows):
        yu = ys[r0:r0 + rows] * tg.UNITS_PER_METRE
        a = int(min(max(math.floor((yu[0] - oy) / sp), 0), last))
        b = int(min(max(math.floor((yu[-1] - oy) / sp) + 1, 0), last))
        if b <= a:
            a, b = max(min(a, last - 1), 0), min(max(a, 0) + 1, last)
        block = tg.resample_bilinear(g[a:b + 1], ox, oy + a * sp, sp, xu, yu) / tg.UNITS_PER_METRE
        yield r0, block


def tile_heights(fo4, tile):
    """Tile heights in metres [row, col] (row 0 = south) at its BTD sample positions (CW frame), in one array."""
    g, (ox, oy) = tile_vertices(fo4, tile)
    xs, ys = tile.sample_coords()
    return tg.resample_bilinear(g, ox, oy, tg.FO4_VERTEX_UNITS, xs * tg.UNITS_PER_METRE,
                                ys * tg.UNITS_PER_METRE) / tg.UNITS_PER_METRE


def decode_at(raw, hmin, hmax, n, lx, ly):
    """Height of an n x n-cell BTD's raw grid at local (lx, ly) under bilinear and both triangle splits. Decodes only
    the 2 x 2 samples around the point: same values and edge clamping as tg.point_interp over the whole decoded grid,
    without holding a float copy of a 64- or 90-cell overlay."""
    o = tg.grid_origin(n)
    last = raw.shape[0] - 2
    c = min(max(int(math.floor((lx - o) / tg.SF_STEP_M)), 0), last)
    r = min(max(int(math.floor((ly - o) / tg.SF_STEP_M)), 0), last)
    win = hmin + raw[r:r + 2, c:c + 2].astype(np.float64) / 65535.0 * (hmax - hmin)
    return tg.point_interp(win, o + c * tg.SF_STEP_M, o + r * tg.SF_STEP_M, tg.SF_STEP_M, lx, ly)


# ---------------------------------------------------------------------------------------------------------- points
class TileData:
    def __init__(self, tile, raw, hmin, hmax, verts, vorigin):
        self.tile, self.raw = tile, raw
        self.hmin, self.hmax = hmin, hmax
        self.step = (hmax - hmin) / 65535.0
        self.verts, self.vorigin = verts, vorigin       # FO4 vertex grid (units) and its origin (units)

    def decoded(self, x_cw, y_cw):
        """Height of the written BTD at a CW position under bilinear and both triangle splits."""
        lx, ly = self.tile.to_local(x_cw, y_cw)
        return decode_at(self.raw, self.hmin, self.hmax, self.tile.n, lx, ly)

    def vertex(self, r, c):
        """CW position (m) and FO4 height (m) of vertex (r, c) of the tile's FO4 grid."""
        xu = self.vorigin[0] + c * tg.FO4_VERTEX_UNITS
        yu = self.vorigin[1] + r * tg.FO4_VERTEX_UNITS
        return m(xu), m(yu), m(float(self.verts[r, c]))

    def rc_of(self, x_cw, y_cw):
        return ((y_cw * tg.UNITS_PER_METRE - self.vorigin[1]) / tg.FO4_VERTEX_UNITS,
                (x_cw * tg.UNITS_PER_METRE - self.vorigin[0]) / tg.FO4_VERTEX_UNITS)

    def rc_global(self, i, j):
        """Row and column in this tile's FO4 grid of the global vertex (i, j) at (128 i, 128 j) FO4 units."""
        return (j - int(self.vorigin[1] // tg.FO4_VERTEX_UNITS), i - int(self.vorigin[0] // tg.FO4_VERTEX_UNITS))

    def eligible(self, r, c, max_slope=MAX_SLOPE):
        """FO4 vertex inside the tile's own samples whose decoded height equals the FO4 height within one quantisation
        step under every interpolation rule, on a slope the player can stand on."""
        if not (1 <= r < self.verts.shape[0] - 1 and 1 <= c < self.verts.shape[1] - 1):
            return False
        x, y, z = self.vertex(r, c)
        x0, x1, y0, y1 = self.tile.bounds_m
        last = tg.SF_STEP_M
        if not (x0 <= x <= x1 - last and y0 <= y <= y1 - last):
            return False
        if tg.local_slope_deg(self.verts, r, c, tg.FO4_VERTEX_UNITS) > max_slope:
            return False
        return max(abs(v - z) for v in self.decoded(x, y).values()) <= self.step

    def point(self, r, c, label, kind, **meta):
        x, y, z = self.vertex(r, c)
        hs = self.decoded(x, y)
        return {"label": label, "kind": kind, "tile": self.tile.tag, "x_cw": round(x, 4), "y_cw": round(y, 4),
                "expect": round(z, 4), "fo4_units": [x * 70.0, y * 70.0, z * 70.0],
                "fo4_cell": list(fo4land.cell_of(x * 70.0, y * 70.0)), "sf_cell_cw": list(tg.sf_cell_of(x, y)),
                "slope_deg": round(tg.local_slope_deg(self.verts, r, c, tg.FO4_VERTEX_UNITS), 2),
                "decoded": {k: round(v, 5) for k, v in hs.items()},
                "error_m": round(max(abs(v - z) for v in hs.values()), 6), **meta}

    def nearest_eligible(self, x_cw, y_cw, radius=12, max_slope=MAX_SLOPE, prefer_flat=False):
        r0, c0 = (int(round(v)) for v in self.rc_of(x_cw, y_cw))
        cand = sorted(((r, c) for r in range(r0 - radius, r0 + radius + 1) for c in range(c0 - radius, c0 + radius + 1)),
                      key=lambda t: (t[0] - r0) ** 2 + (t[1] - c0) ** 2)
        if prefer_flat:
            for r, c in cand:
                if self.eligible(r, c, max_slope=3.0):
                    return r, c
        return next(((r, c) for r, c in cand if self.eligible(r, c, max_slope)), None)


def vertex_indices_between(lo_m, hi_m):
    """Global FO4 vertex indices k (vertex at k * 128 units = k * 128 / 70 m) with lo_m <= position <= hi_m."""
    s = tg.FO4_VERTEX_UNITS / tg.UNITS_PER_METRE
    return [k for k in range(int(math.floor(lo_m / s)) - 1, int(math.ceil(hi_m / s)) + 2) if lo_m <= k * s <= hi_m]


def seam_pairs(seam, ta, tb, ends=150.0):
    """For each distance class a pair of FO4 vertices on the same FO4 vertex line across the seam, one in tile a (west
    / south) and one in tile b (east / north), DIST metres from the seam line and at least `ends` metres from the ends
    of the segment. Classes are spread along the segment. Returns [(cls, pa, pb)]."""
    out = []
    lo, hi = seam["span_m"]
    at = seam["at_m"]
    s = tg.FO4_VERTEX_UNITS / tg.UNITS_PER_METRE
    along_ok = vertex_indices_between(lo + ends, hi - ends)
    for k, (cls, (dmin, dmax)) in enumerate(DIST.items()):
        mid = (lo + (hi - lo) * (k + 1) / (len(DIST) + 1)) / s
        best = None
        for j in sorted(along_ok, key=lambda v: abs(v - mid)):
            ia = vertex_indices_between(at - dmax, at - dmin)
            ib = vertex_indices_between(at + dmin, at + dmax)
            if seam["axis"] == "x":
                ga = [ta.rc_global(i, j) for i in reversed(ia)]
                gb = [tb.rc_global(i, j) for i in ib]
            else:
                ga = [ta.rc_global(j, i) for i in reversed(ia)]
                gb = [tb.rc_global(j, i) for i in ib]
            ea = next((rc for rc in ga if ta.eligible(*rc)), None)
            eb = next((rc for rc in gb if tb.eligible(*rc)), None)
            if ea and eb:
                best = (ea, eb)
                break
        if best is None:
            sys.exit(f"no eligible {cls} pair on seam {seam['name']}")
        name = f"{seam['axis']}_T{ta.tile.tag}_T{tb.tile.tag}_{cls}"
        pa = ta.point(*best[0], name + "_a", "seam", seam=seam["name"], side="a", distance_class=cls)
        pb = tb.point(*best[1], name + "_b", "seam", seam=seam["name"], side="b", distance_class=cls)
        for p in (pa, pb):
            p["distance_to_seam_m"] = round(abs((p["x_cw"] if seam["axis"] == "x" else p["y_cw"]) - at), 4)
        out.append((cls, pa, pb))
    return out


def interior_points(td, tiles, grid_points=0, marks=LANDMARKS):
    """Landmarks in the tile (at least two cells from an outer edge), a flat vertex near the tile's centre, the
    steepest eligible vertex (5..25 deg) near the centre, and optionally a grid_points x grid_points spread of eligible
    vertices over the tile (for large single overlays). `marks`: (name, form id, x, y) in source units."""
    t = td.tile
    outer = og.outer_edges(t, tiles)
    x0, x1, y0, y1 = t.bounds_m
    margin = {e: 200.0 if e in outer else 0.0 for e in overlay.EDGES}
    pts = []
    for i in range(grid_points):
        for j in range(grid_points):
            gx = x0 + margin["w"] + (x1 - margin["e"] - x0 - margin["w"]) * (2 * i + 1) / (2 * grid_points)
            gy = y0 + margin["s"] + (y1 - margin["n"] - y0 - margin["s"]) * (2 * j + 1) / (2 * grid_points)
            rc = td.nearest_eligible(gx, gy, radius=20)
            if rc:
                pts.append(td.point(*rc, f"grid_T{t.tag}_{i}{j}", "grid"))
    for name, fid, xu, yu in marks:
        x, y = m(xu), m(yu)
        if x0 + margin["w"] <= x < x1 - margin["e"] and y0 + margin["s"] <= y < y1 - margin["n"]:
            rc = td.nearest_eligible(x, y)
            if rc:
                p = td.point(*rc, name, "landmark", landmark_fid="%08X" % fid,
                             landmark_m=[round(x, 4), round(y, 4)])
                p["dist_from_landmark_m"] = round(math.hypot(p["x_cw"] - x, p["y_cw"] - y), 2)
                pts.append(p)
    cx, cy = t.origin_m
    centre = td.nearest_eligible(cx + 50.0, cy + 50.0, radius=40, prefer_flat=True)
    if centre is None:
        sys.exit(f"no eligible vertex near the centre of tile {t.tag}")
    pts.append(td.point(*centre, f"centre_T{t.tag}", "centre"))
    r0, c0 = (int(round(v)) for v in td.rc_of(cx + 50.0, cy + 50.0))
    best = None
    rows, cols = td.verts.shape                    # stay inside the vertex grid (negative indices would wrap)
    for r in range(max(r0 - 80, 1), min(r0 + 81, rows - 1), 2):
        for c in range(max(c0 - 80, 1), min(c0 + 81, cols - 1), 2):
            s = tg.local_slope_deg(td.verts, r, c, tg.FO4_VERTEX_UNITS)
            if 5.0 <= s <= MAX_SLOPE and (best is None or s > best[0]) and td.eligible(r, c):
                best = (s, r, c)
    if best:
        pts.append(td.point(best[1], best[2], f"slope_T{t.tag}", "slope"))
    return pts, centre


# ---------------------------------------------------------------------------------------------------------- build
def build(a):
    tiles = og.split(*og.sf_cells_of_fo4_rect(*a.fo4_cells), a.tile, a.pad)
    gx, gy = og.grid_shape(tiles)
    print(f"FO4 cells {a.fo4_cells} -> {len(tiles)} tiles ({gx} x {gy}) of {a.tile} x {a.tile} cells: " +
          ", ".join(f"T{t.tag} x {t.cells_x} y {t.cells_y}" for t in tiles))
    fo4 = getattr(a, "heights", None) or Fo4Heights(a.fo4, a.fo4_npz)
    gx0, gx1, gy0, gy1 = fo4.grid
    need = set()
    for t in tiles:                                   # read every FO4 cell once
        cx0, cx1, cy0, cy1 = tg.fo4_cells_covering(*t.bounds_m)
        need |= {(x, y) for x in range(max(cx0 - 1, gx0), min(cx1 + 1, gx1) + 1)
                 for y in range(max(cy0 - 1, gy0), min(cy1 + 1, gy1) + 1)}
    fo4.load(need)
    print(f"FO4 cells read: {len(fo4.grids)}")
    lo, hi = math.inf, -math.inf
    extent = {}
    for t in tiles:                                   # pass 1: shared height range
        tl, th = math.inf, -math.inf
        for _, h in tile_strips(fo4, t):
            tl, th = min(tl, float(h.min())), max(th, float(h.max()))
        extent[t] = (tl, th)
        lo, hi = min(lo, tl), max(hi, th)
    hmin, hmax = og.height_range(lo, hi)
    step = (hmax - hmin) / 65535.0
    table, quad = ltex_source(a.sf_data)
    tds = {}
    sizes = {}
    for t in tiles:                                   # pass 2: quantise and write
        raw = np.empty((t.n * tg.SF_CELL_SAMPLES, t.n * tg.SF_CELL_SAMPLES), np.uint16)
        for r0, h in tile_strips(fo4, t):
            raw[r0:r0 + h.shape[0]] = btd.quantize(h, hmin, hmax)
        land_tex = getattr(a, "land_textures", None)   # optional (tab, weights, quad map) per tile, e.g. Skyrim's layers
        if land_tex:
            tab, wts, qmap = land_tex(t)
        else:
            tab, wts, qmap = table, np.zeros_like(raw), np.tile(np.frombuffer(quad, np.uint8), (2 * t.n, 2 * t.n, 1))
        data = btd.write(btd.Btd(6, hmin, hmax, tab, raw, wts, qmap))
        path = os.path.join(a.out, "Data", "Terrain", world_name(a, t) + ".btd")
        for p in [path] + [os.path.join(a.out, *c.split("/")) for c in btd_copies(a, t)]:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
        sizes[t.tag] = len(data)
        del data
        verts, vorigin = tile_vertices(fo4, t)
        tds[t] = TileData(t, raw, hmin, hmax, verts, vorigin)
        print(f"  T{t.tag}: {path} ({sizes[t.tag]:,} B), heights {extent[t][0]:.2f}..{extent[t][1]:.2f} m")
    print(f"shared range {hmin}..{hmax} m, step {step * 1000:.3f} mm")

    # seams: continuity of the raw samples across every seam (same lattice, same range)
    seam_list = og.seams(tiles)
    seam_rep = [seam_continuity(s, tds[s["a"]], tds[s["b"]]) for s in seam_list]

    # points
    own, anchors, spawns = {}, {}, {}
    for t in tiles:
        pts, centre = interior_points(tds[t], tiles, a.grid_points, landmarks(a))
        own[t] = pts
        rr = next((p for p in pts if p["label"] == arrival_name(a)), None)
        ap = rr or next(p for p in pts if p["kind"] == "centre")
        if plan_mode(a) == "rays":                    # the COC marker on a flat vertex: the arrival probe and z_ref
            rc = tds[t].nearest_eligible(ap["x_cw"], ap["y_cw"], radius=40, prefer_flat=True)
            ap = tds[t].point(*rc, "arrival", "arrival", near=ap["label"])
        anchors[t] = ap
    pairs = {}
    for s in seam_list:
        pairs[s["name"]] = seam_pairs(s, tds[s["a"]], tds[s["b"]])
        for cls, pa, pb in pairs[s["name"]]:
            own[s["a"]].append(pa)
            own[s["b"]].append(pb)

    targets = og.group_targets(tiles, tuple(a.centre_cell))
    ref = (a.ref_lat, a.ref_lon)
    latlon = {t: og.latlon_for_offset(targets[t], ref, tuple(a.ref_offset), a.radius_km) for t in tiles}
    stage(a, tiles, tds, own, anchors, pairs, seam_rep, targets, latlon, hmin, hmax, sizes, table, quad)


def ltex_source(sf_data):
    """LTEX table and quadrant bytes of vanilla TempJemisonWorld (one plain ground texture), as experiment 2."""
    import make_exp2
    return make_exp2.ltex_template(sf_data)


def world_name(a, t):
    """WRLD EditorID (also the BTD's and mask's file name): --world for a single overlay, else <prefix>_T<tag>."""
    return getattr(a, "world", None) or f"{a.prefix}_T{t.tag}"


def plan_mode(a):
    return getattr(a, "plan", None) or "grid"


def btd_copies(a, t):
    """Extra staged copies of a tile's BTD: with --btd-copy-meshes also Data/meshes/terrain/<world>.btd, the path
    Shattered Space ships its overlay BTDs under (experiment 2b, verified in game 2026-10-11, had both)."""
    return [f"Data/meshes/terrain/{world_name(a, t)}.btd"] if getattr(a, "btd_copy_meshes", False) else []


def seam_continuity(s, ta, tb):
    """Raw u16 steps across the seam against the steps next to it on both sides: a seam that continues the lattice
    has no step larger than the local slope allows."""
    a_last, b_first = og.seam_raw_continuity(ta.raw.astype(np.int64), tb.raw.astype(np.int64), s["axis"])
    if s["axis"] == "x":
        a_prev, b_next = ta.raw[:, -2].astype(np.int64), tb.raw[:, 1].astype(np.int64)
    else:
        a_prev, b_next = ta.raw[-2, :].astype(np.int64), tb.raw[1, :].astype(np.int64)
    across = np.abs(b_first - a_last)
    beside = np.maximum(np.abs(a_last - a_prev), np.abs(b_next - b_first))
    bad = int((across > 2 * beside + 2).sum())
    return {"seam": s["name"], "axis": s["axis"], "at_m": s["at_m"], "samples": int(across.size),
            "max_step_across_m": float(across.max()) * ta.step, "max_step_beside_m": float(beside.max()) * ta.step,
            "samples_with_step_over_2x_local": bad}


def to_plan_point(p, frame_tile):
    x, y = frame_tile.to_local(p["x_cw"], p["y_cw"])
    return {"label": p["label"], "x": round(x, 4), "y": round(y, 4), "expect": p["expect"]}


def drop_z(points, margin=DROP_MARGIN):
    return float(math.ceil((max(p["expect"] for p in points) + margin) / 5.0) * 5.0)


def fall_seconds(drop, lowest, below=FALL_BELOW, g=MARS_G):
    """Free-fall time (no drag) from drop to `below` metres under the lowest expected point."""
    return math.sqrt(2.0 * max(drop - lowest + below, 0.0) / g)


def settle_ms(drop, lowest):
    """Runner wait after each drop: the whole free fall plus 1 s, at least MIN_SETTLE_MS. (The runner adds about 2.9 s
    of console steps between setpos z and the wait, which is left as margin.)"""
    return int(max(MIN_SETTLE_MS, 500 * math.ceil((fall_seconds(drop, lowest) + 1.0) / 0.5)))


def edge_distance(tile, x, y):
    x0, x1, y0, y1 = tile.bounds_m
    return min(x - x0, x1 - x, y - y0, y1 - y)


def snap(tds, tiles, x, y, label, kind, keep=EDGE_KEEP, radius=12, **meta):
    """The eligible FO4 vertex nearest to CW (x, y) in the tile that holds it under H_ll (tiles edge to edge),
    preferring vertices at least `keep` metres inside that tile's edges. None when there is none."""
    t = og.tile_at(tiles, x, y)
    if t is None:
        return None
    td = tds[t]
    r0, c0 = (int(round(v)) for v in td.rc_of(x, y))
    cand = sorted(((r, c) for r in range(r0 - radius, r0 + radius + 1) for c in range(c0 - radius, c0 + radius + 1)),
                  key=lambda rc: (rc[0] - r0) ** 2 + (rc[1] - c0) ** 2)
    first = None
    for r, c in cand:
        if not td.eligible(r, c):
            continue
        vx, vy, _ = td.vertex(r, c)
        if edge_distance(t, vx, vy) >= keep:
            return td.point(r, c, label, kind, **meta)
        first = first or (r, c)
    return td.point(*first, label, kind, **meta) if first else None


JUMP_SLACK = 1.25       # a waypoint may move its legs to this many times max_jump
WAYPOINT_OFFSETS = sorted(((dx, dy) for dx in range(-225, 226, 75) for dy in range(-225, 226, 75)),
                          key=lambda o: o[0] ** 2 + o[1] ** 2)


def waypoint(tds, allowed, ideal, here, nxt, legs_left, label, max_jump=MAX_JUMP, keep=EDGE_KEEP):
    """An eligible vertex near CW `ideal` in one of the `allowed` tiles, at least `keep` metres inside that tile's
    edges (never in a merge ring), reachable from `here` in one jump and leaving `nxt` within `legs_left` jumps (each
    up to JUMP_SLACK * max_jump). Tries positions up to 225 m around `ideal`, nearest first; None if none fits."""
    lim = JUMP_SLACK * max_jump
    for dx, dy in WAYPOINT_OFFSETS:
        x, y = ideal[0] + dx, ideal[1] + dy
        t = og.tile_at(allowed, x, y)
        if t is None or edge_distance(t, x, y) < keep:
            continue
        p = snap(tds, [t], x, y, label, "waypoint", keep=keep, radius=6)
        if p is None or edge_distance(t, p["x_cw"], p["y_cw"]) < keep:
            continue
        if math.hypot(p["x_cw"] - here[0], p["y_cw"] - here[1]) <= lim and \
                math.hypot(nxt["x_cw"] - p["x_cw"], nxt["y_cw"] - p["y_cw"]) <= legs_left * lim:
            return p
    return None


def route(points, start, tds, tiles, max_jump=MAX_JUMP, prefix="wp", allowed=None):
    """Probe order for one entry: nearest neighbour from the spawn (CW `start`), with waypoint probes inserted wherever
    a jump would exceed max_jump, evenly along the leg (waypoint(): eligible vertices in the `allowed` tiles, default
    all, outside every merge ring; H_ll expectations). A tile entry allows only its own tile: in its landing the other
    tiles' places are unknown. Returns (points, longest jump)."""
    allowed = list(allowed or tiles)
    left = list(points)
    out, here, k, longest = [], start, 0, 0.0
    while left:
        nxt = min(left, key=lambda p: math.hypot(p["x_cw"] - here[0], p["y_cw"] - here[1]))
        left.remove(nxt)
        d = math.hypot(nxt["x_cw"] - here[0], nxt["y_cw"] - here[1])
        if max_jump and d > max_jump:
            steps, leg0 = int(math.ceil(d / max_jump)), here
            for s in range(1, steps):
                ideal = (leg0[0] + (nxt["x_cw"] - leg0[0]) * s / steps, leg0[1] + (nxt["y_cw"] - leg0[1]) * s / steps)
                w = waypoint(tds, allowed, ideal, here, nxt, steps - s, f"{prefix}_{k:02d}", max_jump)
                if w is not None:
                    longest = max(longest, math.hypot(w["x_cw"] - here[0], w["y_cw"] - here[1]))
                    out.append(w)
                    here = (w["x_cw"], w["y_cw"])
                    k += 1
            d = math.hypot(nxt["x_cw"] - here[0], nxt["y_cw"] - here[1])
        longest = max(longest, d)
        out.append(nxt)
        here = (nxt["x_cw"], nxt["y_cw"])
    return out, longest


def locate_transect(tds, tiles, target, start, step=LOCATE_STEP, keep=EDGE_KEEP):
    """Locate probes from CW `start` (the first tile's centre point) toward the centre of `target` and on to its far
    edge (less `keep`), every `step` metres, skipping positions within `keep` of any tile edge. In the first tile's
    frame they cover the target at any whole-cell shift along that line from about half to 1.4 times its H_ll
    distance (at least three probes inside it)."""
    x0, x1, y0, y1 = target.bounds_m
    gx, gy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    length = math.hypot(gx - start[0], gy - start[1])
    ux, uy = (gx - start[0]) / length, (gy - start[1]) / length
    end = length
    while x0 + keep <= start[0] + ux * (end + 1) <= x1 - keep and y0 + keep <= start[1] + uy * (end + 1) <= y1 - keep:
        end += 1.0
    pts, k, d = [], 0, step
    while d <= end:
        x, y = start[0] + ux * d, start[1] + uy * d
        t = og.tile_at(tiles, x, y)
        if t is not None and edge_distance(t, x, y) >= keep:
            p = snap(tds, tiles, x, y, f"loc_T{target.tag}_{k:02d}", "locate", keep=keep, radius=8,
                     transect=f"T{target.tag}", along_m=round(d, 1))
            if p is not None and edge_distance(og.tile_at(tiles, p["x_cw"], p["y_cw"]), p["x_cw"], p["y_cw"]) >= keep - 15:
                pts.append(p)
                k += 1
        d += step
    return pts


def edge_points(td, tiles, mask_edges):
    """Probes in the outer cell ring (DIST 'ring') and inside it (DIST 'inner') of each outer edge of one tile, away
    from its corners; the label carries the mask value written on that edge (255 or 0)."""
    t = td.tile
    x0, x1, y0, y1 = t.bounds_m
    pts = []
    for e in og.outer_edges(t, tiles):
        val = 255 if e in mask_edges else 0
        for frac, cls in ((1 / 3, "ring"), (2 / 3, "ring"), (1 / 2, "inner")):
            dmin, dmax = DIST[cls]
            inset = (dmin + dmax) / 2.0
            along = (x0 + (x1 - x0) * frac) if e in ("s", "n") else (y0 + (y1 - y0) * frac)
            x, y = {"w": (x0 + inset, along), "e": (x1 - inset, along),
                    "s": (along, y0 + inset), "n": (along, y1 - inset)}[e]
            r0, c0 = (int(round(v)) for v in td.rc_of(x, y))
            best = None
            for r, c in sorted(((r, c) for r in range(r0 - 12, r0 + 13) for c in range(c0 - 12, c0 + 13)),
                               key=lambda rc: (rc[0] - r0) ** 2 + (rc[1] - c0) ** 2):
                vx, vy, _ = td.vertex(r, c)
                de = {"w": vx - x0, "e": x1 - vx, "s": vy - y0, "n": y1 - vy}[e]
                others = [v for k, v in {"w": vx - x0, "e": x1 - vx, "s": vy - y0, "n": y1 - vy}.items() if k != e]
                if dmin <= de <= dmax and min(others) >= EDGE_KEEP and td.eligible(r, c):
                    best = (r, c, de)
                    break
            if best is None:
                sys.exit(f"no eligible {cls} vertex on the {e} edge of tile {t.tag}")
            name = f"edge_{e}{val}_{cls}" + (f"_{int(frac * 3)}" if cls == "ring" else "")
            p = td.point(best[0], best[1], name, "edge", edge=e, mask=val, distance_class=cls)
            p["distance_to_edge_m"] = round(best[2], 4)
            pts.append(p)
    return pts


ENTRY_KINDS = ("tile", "group", "locate", "edges", "ray")


def entry_kind(label):
    """Entry kind from a plan label '<experiment> <kind> ...' (the runner keeps the label as the test's 'model')."""
    parts = str(label).split(" ")
    return parts[1].rstrip(":") if len(parts) > 1 and parts[1].rstrip(":") in ENTRY_KINDS else None


def make_plan(a, tiles, tds, own, pairs, by_tag, hmin, hmax):
    """Runner entries (plan.json) and the CW points behind them (expected.json 'entries').

    Every entry cocs into the tile whose frame its points use and takes the merge offset from that tile's spawn
    (spawn_local, x and y only): our persistent anchors read back their unmerged local position (exp1d a1, a2 and
    exp2b a1, a2), so the runner's anchor offset is 0 and it falls back to the spawn; no entry relies on another
    tile's anchor. z_ref names the entry's flat centre probe: the judge takes the Z offset from it.
      tile    one per tile: its own heights (landmarks, centre, slope) and its side of each seam (near, ring, inner)
      group   in the first tile's landing: both sides of every seam (passes only if the tiles lie edge to edge)
      locate  in the first tile's landing: a transect toward each other tile; `analyse` finds where that tile really
              sits from the heights read (whole-cell shift), whether or not H_ll holds
      edges   the first tile's outer edges: cell ring with mask 255 and with mask 0, and inside it"""
    first = tiles[0]
    plan, entries = [], []
    centre = {t: next(p for p in own[t] if p["kind"] == "centre") for t in tiles}

    def add(kind, t, label, pts_cw, drop=None, lowest=None):
        o = by_tag[t.tag]
        start = t.to_cw(*o["anchor"]["local"][:2])
        ordered, longest = route(pts_cw, start, tds, tiles, a.max_jump, prefix=f"wp{len(plan)}",
                                 allowed=None if kind in ("group", "locate") else [t])
        pts = [to_plan_point(p, t) for p in ordered]
        dz = drop if drop is not None else drop_z(pts)
        low = min(p["expect"] for p in pts) if lowest is None else lowest
        plan.append({"coc": o["coc"], "label": f"{a.experiment} {kind} {label}",
                     "anchor": {"ref": o["anchor"]["ref"], "local": o["anchor"]["local"]},
                     "spawn_local": o["anchor"]["local"][:2], "z_ref": centre[t]["label"], "drop_z": dz,
                     "settle_ms": settle_ms(dz, low), "points": pts})
        entries.append({"index": len(plan) - 1, "kind": kind, "frame": t.tag, "coc": o["coc"],
                        "longest_jump_m": round(longest, 1), "points": ordered})

    alignment_label = f"{a.alignment}, HNAM {a.hnam}"
    for t in tiles:
        add("tile", t, f"T{t.tag} ({t.n}x{t.n} cells, CW cells x {t.cells_x} y {t.cells_y}; {alignment_label}): own "
                       "heights and its side of every seam; its landing's merge offset from the spawn", own[t])
    if len(tiles) > 1:
        seam_pts = [p for prs in pairs.values() for _, pa, pb in prs for p in (pa, pb)]
        add("group", first, f"T{first.tag} landing: both sides of every seam in T{first.tag}'s frame (passes only if "
                            "the tiles lie edge to edge, H_ll at scale 1, and the seams are exact)",
            [centre[first]] + seam_pts)
        start = (centre[first]["x_cw"], centre[first]["y_cw"])
        for t in tiles[1:]:
            pts = locate_transect(tds, tiles, t, start, a.locate_step)
            add("locate", first, f"T{t.tag} from T{first.tag}'s landing: transect toward T{t.tag} (passes if it sits "
                                 f"where H_ll puts it; where it really sits: make_cw_overlays.py analyse)",
                [centre[first]] + pts, drop=drop_z([{"expect": hmax}]), lowest=hmin)
        me = og.mask_edges(first, tiles, a.mask_ns)
        add("edges", first, f"T{first.tag}: cell ring of its outer edges with the mask value in the label "
                            f"({', '.join(e + ('255' if e in me else '0') for e in og.outer_edges(first, tiles))}) "
                            "and inside it (does the merge ring blend where the mask is 255 / 0?)",
            [centre[first]] + edge_points(tds[first], tiles, me))
    return plan, entries


def bearing_deg(x0, y0, x1, y1):
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


def nearest_ray(rays, bearing):
    """Name of the ray (name, bearing in degrees, 0 = east, 90 = north) closest to `bearing`."""
    return min(rays, key=lambda r: abs((bearing - r[1] + 180.0) % 360.0 - 180.0))[0]


def parse_rays(spec):
    """'nw:135,e:0' -> (('nw', 135.0), ('e', 0.0))."""
    out = []
    for part in str(spec).split(","):
        name, _, deg = part.strip().partition(":")
        if not re.fullmatch(r"[a-z0-9]+", name) or not deg:
            raise ValueError(f"bad ray {part!r} (want name:degrees)")
        out.append((name, float(deg)))
    if len({n for n, _ in out}) != len(out):
        raise ValueError("ray names must be unique")
    return tuple(out)


def snap_inside(td, x, y, keep, radius=16, flat=RAY_FLAT_DEG):
    """(row, col) of the eligible FO4 vertex nearest to CW (x, y) that lies at least `keep` metres inside the tile's
    edges, preferring one on a slope of at most `flat` degrees within the radius (on a slope the player's capsule
    touches the ground off its centre), or None."""
    t = td.tile
    r0, c0 = (int(round(v)) for v in td.rc_of(x, y))
    cand = sorted(((r, c) for r in range(r0 - radius, r0 + radius + 1) for c in range(c0 - radius, c0 + radius + 1)),
                  key=lambda rc: (rc[0] - r0) ** 2 + (rc[1] - c0) ** 2)
    rows, cols = td.verts.shape                    # candidates beyond the source vertex grid have no height
    inside = [(r, c) for r, c in cand if 0 <= r < rows and 0 <= c < cols
              and edge_distance(t, *td.vertex(r, c)[:2]) >= keep]
    for slope in (flat, MAX_SLOPE):
        rc = next(((r, c) for r, c in inside if td.eligible(r, c, max_slope=slope)), None)
        if rc is not None:
            return rc
    return None


def make_ray_plan(a, t, td, o, arrival):
    """Runner entries for ONE overlay (--plan rays): every entry is one coc arrival (o['coc']) and one direction:
    the arrival's flat vertex first (the COC marker's ground, z_ref), then FO4 vertices at RAY_DISTANCES from it
    along the ray's bearing while they stay at least --edge-keep metres inside the overlay, plus the landmarks
    (Sanctuary, Vault 111, the Sanctuary bridge, Concord) on the ray nearest their bearing, all ordered by distance
    from the arrival. spawn_local is the marker's ground (x, y, z): the runner's Z offset is spawn z - ground z, and
    the judge takes the Z offset from z_ref anyway. No waypoints: the distances are the measurement (exp3 read real
    terrain only in the overlay it arrived in, so how far one overlay loads around an arrival is the question)."""
    keep = a.edge_keep
    ax, ay = arrival["x_cw"], arrival["y_cw"]
    extra = {}
    for name, fid, xu, yu in landmarks(a) + ray_landmarks(a):
        x, y = m(xu), m(yu)
        if name == arrival_name(a) or not t.contains(x, y) or edge_distance(t, x, y) < keep:
            continue
        rc = snap_inside(td, x, y, keep, radius=12)
        if rc is None:
            continue
        p = td.point(*rc, name, "landmark", landmark_fid="%08X" % fid, landmark_m=[round(x, 4), round(y, 4)])
        p["dist_from_landmark_m"] = round(math.hypot(p["x_cw"] - x, p["y_cw"] - y), 2)
        extra.setdefault(nearest_ray(a.rays, bearing_deg(ax, ay, x, y)), []).append(p)
    plan, entries = [], []
    for name, deg in a.rays:
        ux, uy = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        pts, skipped = [], []
        for d in sorted(a.ray_distances):
            if d <= 0.0:
                continue
            x, y = ax + ux * d, ay + uy * d
            if not t.contains(x, y) or edge_distance(t, x, y) < keep:
                skipped.append(d)
                continue
            rc = snap_inside(td, x, y, keep)
            if rc is None:
                skipped.append(d)
                continue
            pts.append(td.point(*rc, f"{name}_{d:g}m", "ray", ray=name, distance_m=d))
        pts += extra.get(name, [])
        if not pts:
            continue
        for p in pts:
            p["from_arrival_m"] = round(math.hypot(p["x_cw"] - ax, p["y_cw"] - ay), 1)
        pts = [dict(arrival, from_arrival_m=0.0)] + sorted(pts, key=lambda p: p["from_arrival_m"])
        here, longest = (ax, ay), 0.0
        for p in pts:
            longest = max(longest, math.hypot(p["x_cw"] - here[0], p["y_cw"] - here[1]))
            here = (p["x_cw"], p["y_cw"])
        plan_pts = [to_plan_point(p, t) for p in pts]
        dz = drop_z(plan_pts)
        lm = [p["label"] for p in pts if p["kind"] == "landmark"]
        dists = ", ".join("%g" % p["from_arrival_m"] for p in pts)
        plan.append({"coc": o["coc"],
                     "label": f"{a.experiment} ray {name}: one arrival at {o['coc']}, probes {dists} m from it toward "
                              f"bearing {deg:g} deg (0 = east)" + (f", landmarks {', '.join(lm)}" if lm else "") +
                              f"; one {t.n}x{t.n}-cell overlay ({a.alignment}, HNAM {a.hnam})",
                     "spawn_local": list(o["anchor"]["local"]), "z_ref": arrival["label"], "drop_z": dz,
                     "settle_ms": settle_ms(dz, min(p["expect"] for p in plan_pts)), "points": plan_pts})
        entries.append({"index": len(plan) - 1, "kind": "ray", "frame": t.tag, "coc": o["coc"], "ray": name,
                        "bearing_deg": deg, "skipped_distances_m": skipped, "longest_jump_m": round(longest, 1),
                        "points": pts})
    return plan, entries


def stage(a, tiles, tds, own, anchors, pairs, seam_rep, targets, latlon, hmin, hmax, sizes, table, quad):
    first = tiles[0]
    overlays, plan = [], []
    for k, t in enumerate(tiles):
        w = world_name(a, t)
        ap = anchors[t]
        ax, ay = t.to_local(ap["x_cw"], ap["y_cw"])
        local = [round(ax, 4), round(ay, 4), ap["expect"]]
        fid = orc.ANCHOR_ID + k
        mask_edges = og.mask_edges(t, tiles, a.mask_ns)
        overlays.append({
            "world": w, "tag": t.tag, "ix": t.ix, "iy": t.iy, "n": t.n,
            "cells_cw": {"x": list(t.cells_x), "y": list(t.cells_y)}, "origin_cw_m": list(t.origin_m),
            "cell_min": tg.cell_range(t.n)[0], "cell_max": tg.cell_range(t.n)[1],
            "btd_path": f"Data\\TERRAIN\\{w}.btd", "btd_file": f"Data/Terrain/{w}.btd", "btd_bytes": sizes[t.tag],
            "btd_copies": btd_copies(a, t),
            "fnam": overlay.fnam_values(tds[t].raw), "mask": orc.mask_rel(w), "mask_outer_edges": list(mask_edges),
            "coc": (getattr(a, "coc", None) or w + "Spawn"), "spawn": [local[0], local[1], round(local[2] + SPAWN_ABOVE, 4)],
            "spawn_cell": list(tg.sf_cell_of(local[0], local[1])),
            "anchor": {"edid": w + "Anchor", "local": local, "form_id": fid, "ref": orc.anchor_ref(fid, a.load_byte)},
            "location": w + "Location", "block": w + "Block",
            "bounds_min_m": tg.grid_origin(t.n), "bounds_max_m": tg.grid_origin(t.n) + t.n * tg.SF_CELL_M,
            "planet_target_cell": list(targets[t]),
            "latitude": latlon[t][0], "longitude": latlon[t][1]})
        if getattr(a, "display_name", None):          # WRLD/LCTN FULL; dotnet/TerrainOverlays keeps its FO4 name without
            overlays[-1]["name"] = a.display_name if len(tiles) == 1 else f"{a.display_name} {t.tag}"
    by_tag = {o["tag"]: o for o in overlays}
    if plan_mode(a) == "rays":
        plan, entries = make_ray_plan(a, first, tds[first], by_tag[first.tag], anchors[first])
    else:
        plan, entries = make_plan(a, tiles, tds, own, pairs, by_tag, hmin, hmax)

    mars = None if a.no_mars else {"plugin": a.mars_plugin, "planet": "MarsPlanetData",
                                   "radius_km": a.radius_km,
                                   "hypothesis": "H_ll: true planet scale from the reference registration",
                                   "reference": {"latitude": a.ref_lat, "longitude": a.ref_lon,
                                                 "offset_cells": list(a.ref_offset)}}
    params = {"plugin": a.plugin, "prefix": a.prefix, "hmin": hmin, "hmax": hmax, "alignment": a.alignment,
              "hnam": a.hnam, "mars": mars, "overlays": overlays, "anchor_load_byte": a.load_byte,
              "mask_ns": a.mask_ns, "max_jump_m": 0.0 if plan_mode(a) == "rays" else a.max_jump,
              "plan_mode": plan_mode(a), "edge_keep_m": getattr(a, "edge_keep", RAY_EDGE_KEEP),
              "note": "latitude/longitude in radians; PNDT CNAM stores latitude first (Mutagen calls it Longitude)"}
    masks = []
    for o in overlays:
        masks.append(write_mask(a.out, o["world"], o["n"], o["mask_outer_edges"], a.mask_writer))
    check = {"points": sum(len(e["points"]) for e in plan), "seams": seam_rep,
             "max_point_error_m": max(p["error_m"] for e in entries for p in e["points"]),
             "quantisation_step_m": (hmax - hmin) / 65535.0,
             "entries": [{"index": e["index"], "kind": e["kind"], "frame": f"T{e['frame']}", "points": len(e["points"]),
                          "waypoints": sum(1 for p in e["points"] if p["kind"] == "waypoint"),
                          "longest_jump_m": e["longest_jump_m"], "drop_z": plan[e["index"]]["drop_z"],
                          "settle_ms": plan[e["index"]]["settle_ms"]} for e in entries]}
    expected = {"experiment": a.experiment, "plugin": a.plugin, "fo4_cells": list(a.fo4_cells), "tile": a.tile,
                "grid": list(og.grid_shape(tiles)), "height_range_m": [hmin, hmax],
                "quantisation_step_m": (hmax - hmin) / 65535.0,
                "ltex": {"table": ["%08X" % x for x in table], "quadrant_bytes": list(quad)},
                "frames": "CW = FO4 units / 70 from the FO4 origin; each tile's own frame = CW - origin_cw_m",
                "hypotheses": {"H": "BTD height = world z (Absolute, HNAM 0: no Z offset)",
                               "H_ll": "overlay merge offset moves at true planet scale near the reference registration",
                               "seams": "inner seams with mask 0 keep the tiles' own heights (no blend into procedural "
                                        "ground)",
                               "grid": "an even-sized BTD's south-west sample is n // 2 cells west / south of the local "
                                       "origin (as for odd sizes; 14 is the first even size tested in game)"},
                "overlays": overlays, "seams": seam_rep,
                "points": {t.tag: own[t] for t in tiles},
                "entries": [dict(e) for e in entries],
                "offline_check": check}
    for name, obj in (("plan.json", plan), ("expected.json", expected), ("overlays_params.json", params)):
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1)
    readme(a, params, plan, masks)
    preview(tds, tiles, own, os.path.join(a.out, "preview.png"))
    print(json.dumps(check, indent=1))
    print(f"staged {len(tiles)} tiles, {len(plan)} plan entries, {check['points']} points in {a.out}; next: dotnet run "
          f"--project dotnet/TerrainOverlays -c Release -- <Starfield.esm> {a.out}")


def write_mask(out, world, n, edges, writer):
    img = overlay.mask_array(n, edges=edges) if edges else np.zeros((n * 100, n * 100), np.uint8)
    dst = os.path.join(out, *orc.mask_rel(world).split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if writer == "builtin":
        data = overlay.dds_bc4(img)
    else:
        import subprocess
        import tempfile
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, world.lower() + ".png")
            Image.fromarray(img, "L").save(png)
            r = subprocess.run([orc.TEXCONV, "-nologo", "-y", "-f", "BC4_UNORM", "-m", "1", "-o", tmp, png],
                               capture_output=True, text=True)
            made = os.path.join(tmp, world.lower() + ".dds")
            if r.returncode != 0 or not os.path.isfile(made):
                sys.exit("texconv failed:\n" + r.stdout + r.stderr)
            data = orc.read_bytes(made)
    with open(dst, "wb") as f:
        f.write(data)
    return mask_report(out, world, n, edges)


def mask_report(out, world, n, edges):
    data = orc.read_bytes(os.path.join(out, *orc.mask_rel(world).split("/")))
    info = overlay.dds_info(data)
    img = overlay.bc4_decode(data)
    want = overlay.mask_array(n, edges=edges) if edges else np.zeros((n * 100, n * 100), np.uint8)
    differ = int((img.astype(np.int32) != want.astype(np.int32)).sum()) if img.shape == want.shape else int(want.size)
    return {"file": orc.mask_rel(world), "bytes": len(data), "width": info["width"], "height": info["height"],
            "mips": info["mips"], "format": info["format"], "outer_edges": list(edges), "pixels_differ": differ}


def readme_rays(a, params, plan, masks):
    """README of a single-overlay ray experiment (--plan rays), e.g. terrain_core64."""
    pl = [params["plugin"]] + ([params["mars"]["plugin"]] if params.get("mars") else [])
    base = os.path.splitext(params["plugin"])[0]
    o = params["overlays"][0]
    files = [o["btd_file"]] + o["btd_copies"] + [o["mask"]]
    lines = [f"Terrain {a.experiment} (Claude, 2026-10-11). NOT deployed. Recipe: docs/terrain/commonwealth-scale.md",
             "(branch claude/terrain-core64).",
             "",
             f"ONE overlay worldspace {o['world']} of {o['n']} x {o['n']} Starfield cells ({o['n'] / 10:g} km), CW cells x "
             f"{o['cells_cw']['x']} y {o['cells_cw']['y']}",
             f"(FO4 cells {a.fo4_cells}, padded; own origin at CW {o['origin_cw_m']}: local position = FO4 position / 70).",
             f"Real FO4 heights / 70, range {params['hmin']}..{params['hmax']} m, alignment {a.alignment} (INAM 1, HNAM "
             f"{a.hnam}), own Location {o['location']},",
             f"overlay mask: 255 on the outer cell ring ({', '.join(o['mask_outer_edges'])}), 0 inside.",
             f"COC cell {o['coc']} with a COCMarkerHeading 2 m above the arrival's flat vertex (next to {arrival_name(a)} if "
             f"inside) at local {o['anchor']['local']} (ground).",
             f"Registered on Mars by {params['mars']['plugin'] if params.get('mars') else 'nothing'} at latitude "
             f"{o['latitude']:.9f}, longitude {o['longitude']:.9f} rad",
             "(= experiment 2b's registration, verified in game 2026-10-11: merged at planet cell (-12, -27))."
             if (round(o["latitude"], 12), round(o["longitude"], 12)) == EXP2B_LATLON else
             f"(H_ll target planet cell {o['planet_target_cell']}; not a registration verified in game).",
             "Never install together with another terrain experiment (every Mars plugin overrides MarsPlanetData).",
             "",
             "Install (game closed). The runner does it:",
             f"  scripts/game/exp_install.py install --exp-dir <this folder> --starfield <game> --plugins {','.join(pl)} --pack",
             f"  --pack builds \"{base} - Main.ba2\" from Data\\ (Archive2 -compression=None: every entry stored), holding",
             "  " + ", ".join(files) + ";",
             f"  the plugins go to the game's Data root. Queue: testqueue.py plan-terrain --exp-dir <this folder> --plugins "
             f"{','.join(pl)} --fresh",
             "",
             f"Plan: {len(plan)} entries, {sum(len(e['points']) for e in plan)} points. Each entry is ONE coc arrival "
             f"({o['coc']}) and one direction:",
             "the arrival's flat vertex (z_ref) first, then FO4 vertices at increasing distance from it, all at least "
             f"{params['edge_keep_m']:g} m inside the overlay:"]
    for e in plan:
        lines.append(f"  {e['label'].split(':')[0].split(' ', 1)[1]}: " +
                     ", ".join(f"{p['label']}" for p in e["points"]) + f" (drop {e['drop_z']:g}, wait {e['settle_ms']} ms)")
    lines += ["spawn_local = the COC marker's ground (x, y, z); expect = FO4 height / 70 at an FO4 vertex (local frame).",
              "Reading: every probe at its height (within 0.5 m after the z_ref Z offset) -> the whole overlay loads",
              "around one arrival; probes that hang at the drop height or read procedural ground from some distance on",
              "-> the overlay streams only near the arrival (compare the distances per direction).",
              "", "Masks: " + ", ".join(f"{k['file']} ({k['width']} px, ring on {k['outer_edges'] or 'none'}, "
                                         f"{k['pixels_differ']} px differ)" for k in masks)]
    with open(os.path.join(a.out, "README.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def readme(a, params, plan, masks):
    if plan_mode(a) == "rays":
        return readme_rays(a, params, plan, masks)
    pl = [params["plugin"]] + ([params["mars"]["plugin"]] if params.get("mars") else [])
    base = os.path.splitext(params["plugin"])[0]
    ov = params["overlays"]
    kinds = [entry_kind(e["label"]) for e in plan]
    count = {k: kinds.count(k) for k in ENTRY_KINDS if k in kinds}
    lines = [f"Terrain {a.experiment} (Claude, 2026-10-11). NOT deployed. Recipe: docs/terrain/commonwealth-scale.md",
             "(branch claude/commonwealth-terrain-scale).",
             "",
             "DO NOT QUEUE until an exp2b rerun with the BTD stored uncompressed (terrain_exp2b3, installer",
             "claude/test-queue f210b91) reads the BTD's own heights. exp2b's packed BTD read flat -116.00 (its minimum)",
             "at every probe; until a run reads real heights this experiment would only repeat that.",
             "",
             f"{len(ov)} overlay worldspace(s) of {ov[0]['n']} x {ov[0]['n']} cells, edge to edge in the Commonwealth frame "
             f"(FO4 cells {a.fo4_cells}), one shared",
             f"height range {params['hmin']}..{params['hmax']} m, alignment {a.alignment} (HNAM {a.hnam}), one Location each,",
             f"masks: 255 on the outer edges' cell ring, 0 on seams; north / south rings mode '{a.mask_ns}' (mask row order",
             "is unresolved: 'symmetric' writes them only in pairs, so a flipped row order cannot put 255 on a seam).",
             "A persistent anchor and a COC cell per tile.",
             "Registered on Mars by " + (params["mars"]["plugin"] if params.get("mars") else "nothing") +
             " at lat/long chosen by hypothesis H_ll (true planet scale from World01's measured",
             "offset), so that the tiles should lie edge to edge around planet cell " + str(a.centre_cell) + ".",
             "Never install together with experiment 1 or 2 (all Mars plugins override MarsPlanetData).",
             "",
             "Install (game closed). The runner does it:",
             f"  scripts/game/exp_install.py install --exp-dir <this folder> --starfield <game> --plugins {','.join(pl)} --pack",
             f"  --pack puts Data\\Terrain and Data\\textures into \"{base} - Main.ba2\" (loose files are not read); since",
             "  claude/test-queue f210b91 it stores every entry uncompressed (Archive2 -compression=None), as all vanilla",
             "  terrain archives do. Check: every entry of the built archive has packed size 0.",
             f"  Anchor refs assume load-order byte {params.get('anchor_load_byte', '02')} (as exp2b's resolved); the "
             "runner reads them literally.",
             "",
             "Tiles (CW = Commonwealth frame, metres = FO4 units / 70):"]
    for o in ov:
        lines.append(f"  {o['world']}: CW cells x {o['cells_cw']['x']} y {o['cells_cw']['y']}, own origin at CW "
                     f"{o['origin_cw_m']}, coc {o['coc']}, anchor {o['anchor']['ref']} at local {o['anchor']['local']},")
        lines.append(f"      lat {o['latitude']:.9f} lon {o['longitude']:.9f} rad -> predicted planet cell "
                     f"{o['planet_target_cell']}, mask ring on {o['mask_outer_edges'] or 'no edge'}")
    lines += ["",
              "In game (test save), console, per plan entry: tgm; coc <coc>; player.getpos x/y -> S; offset O = S -",
              "spawn_local (x, y; whole 100 m cells when merged); for every point: player.setpos x <x+O.x>, y <y+O.y>,",
              "z <drop_z>, wait settle_ms, player.getpos z. Heights are judged relative to the z_ref probe (the entry's",
              "flat centre): Z offset = z(z_ref) - its expect. The runner does all of this (spawn fallback: our anchors",
              "read back their unmerged local position, so the anchor offset is 0 and the spawn is used).",
              f"Plan: {len(plan)} entries ({', '.join(f'{v} {k}' for k, v in count.items())}), "
              f"{sum(len(e['points']) for e in plan)} points.",
              "Reading (details: docs/terrain/commonwealth-scale.md section 6):",
              "  python scripts/terrain/make_cw_overlays.py analyse --out <this folder> --runs <runner queue folder>",
              "  gives per entry the merge offset of its landing (whole cells or not), the Z offset, every point's error,",
              "  and per tile where it sits (whole-cell shift that matches the heights read; own tile: (0, 0) expected).",
              "  tile entries pass -> each tile's heights exact; group passes -> tiles edge to edge (H_ll at scale 1) and",
              "  seams exact; locate entries -> where each tile really is in T00's landing, even if H_ll is wrong;",
              "  edges -> whether the outer ring blends with mask 255 and with mask 0.",
              "", "Masks: " + ", ".join(f"{k['file']} ({k['width']} px, ring on {k['outer_edges'] or 'none'}, "
                                         f"{k['pixels_differ']} px differ)" for k in masks)]
    with open(os.path.join(a.out, "README.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def preview(tds, tiles, own, path, k=8):
    from PIL import Image, ImageDraw
    x0 = min(t.cx0 for t in tiles)
    y0 = min(t.cy0 for t in tiles)
    x1 = max(t.cx0 + t.n for t in tiles)
    y1 = max(t.cy0 + t.n for t in tiles)
    px = 128 // k
    W, H = (x1 - x0) * px, (y1 - y0) * px
    img = np.zeros((H, W))
    for t in tiles:
        d = tds[t].hmin + tds[t].raw[::k, ::k].astype(np.float64) / 65535.0 * (tds[t].hmax - tds[t].hmin)
        r0 = (t.cy0 - y0) * px
        c0 = (t.cx0 - x0) * px
        img[r0:r0 + d.shape[0], c0:c0 + d.shape[1]] = d
    img = img[::-1]
    lo, hi = float(img.min()), float(img.max())
    im = Image.fromarray(((img - lo) / max(hi - lo, 1e-6) * 255).astype(np.uint8)).convert("RGB")
    dr = ImageDraw.Draw(im)

    def xy(x, y):
        return (x / 100.0 - x0) * px, H - 1 - (y / 100.0 - y0) * px

    for t in tiles:
        bx0, bx1, by0, by1 = t.bounds_m
        a, b = xy(bx0, by1), xy(bx1, by0)
        dr.rectangle([a, b], outline=(255, 200, 0))
        dr.text((a[0] + 4, a[1] + 4), f"T{t.tag}", fill=(255, 200, 0))
    for t in tiles:
        for p in own[t]:
            x, y = xy(p["x_cw"], p["y_cw"])
            col = (255, 60, 60) if p["kind"] == "seam" else (60, 220, 255)
            dr.ellipse([x - 3, y - 3, x + 3, y + 3], outline=col)
    dr.text((4, H - 14), f"N up, {lo:.0f}..{hi:.0f} m; red: seam points, cyan: tile points", fill=(255, 255, 0))
    im.save(path)


# ---------------------------------------------------------------------------------------------------------- check
def check(a):
    prm = json.loads(orc.read_bytes(os.path.join(a.out, "overlays_params.json")))
    plan = json.loads(orc.read_bytes(os.path.join(a.out, "plan.json")))
    ok, rep = check_staging(a.out, prm, plan, orc.vanilla_mars_count(a.sf_data), plugins=not a.no_plugins)
    for what, good in rep["checks"]:
        if not good or a.verbose:
            print(("  ok   " if good else "  FAIL ") + what)
    print(f"  {sum(1 for c in rep['checks'] if c[1])} of {len(rep['checks'])} checks ok")
    for p in rep["points"]:
        if a.verbose:
            print(f"  {p['entry']:<5} {p['label']:<26} expect {p['expect']:9.4f} decoded {p['decoded']['bilinear']:9.4f} "
                  f"error {p['error_mm']:7.3f} mm (tile {p['tile']})")
    with open(os.path.join(a.out, "offline_check.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    print(json.dumps({k: rep[k] for k in ("summary", "seams", "mars") if k in rep}, indent=1))
    print("CHECK", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def check_staging(out, prm, plan, vanilla_mars_entries=None, plugins=True):
    """Offline verification of a staged overlay grid. Returns (ok, report). plugins=False skips the record walk
    (before dotnet/TerrainOverlays ran, and in the synthetic tests)."""
    checks, rep = [], {}

    def need(cond, what):
        checks.append([what, bool(cond)])

    ovs = prm["overlays"]
    tiles, dec, raws, steps = {}, {}, {}, {}
    for o in ovs:
        t = og.Tile(o["ix"], o["iy"], o["cells_cw"]["x"][0], o["cells_cw"]["y"][0], o["n"])
        tiles[o["tag"]] = t
        b = btd.read(orc.read_bytes(os.path.join(out, *o["btd_file"].split("/"))))
        need(b.ncx == b.ncy == o["n"], f"{o['world']}: BTD {b.ncx} x {b.ncy} cells = DNAM {o['n']}")
        need((b.hmin, b.hmax) == (prm["hmin"], prm["hmax"]), f"{o['world']}: BTD range = shared {prm['hmin']}..{prm['hmax']}")
        need(overlay.fnam_match(struct.pack(f"<{len(o['fnam'])}H", *o["fnam"]), b.heights_raw)[0] == o["n"] ** 2,
             f"{o['world']}: params FNAM = SW-corner rule")
        need(list(t.origin_m) == o["origin_cw_m"], f"{o['world']}: origin {o['origin_cw_m']}")
        dec[o["tag"]], raws[o["tag"]], steps[o["tag"]] = (b.hmin, b.hmax), b.heights_raw, (b.hmax - b.hmin) / 65535.0
    tl = list(tiles.values())
    # tiles abut exactly and seams continue the lattice
    seam_rep = []
    for s in og.seams(tl):
        ta, tb = s["a"], s["b"]
        ra, rb = raws[ta.tag].astype(np.int64), raws[tb.tag].astype(np.int64)
        a_last, b_first = og.seam_raw_continuity(ra, rb, s["axis"])
        a_prev = ra[:, -2] if s["axis"] == "x" else ra[-2, :]
        b_next = rb[:, 1] if s["axis"] == "x" else rb[1, :]
        across = np.abs(b_first - a_last)
        beside = np.maximum(np.abs(a_last - a_prev), np.abs(b_next - b_first))
        bad = int((across > 2 * beside + 2).sum())
        need(bad == 0, f"seam {s['name']}: no step across the seam beyond twice the local slope ({bad} samples)")
        xa = ta.bounds_m[1] if s["axis"] == "x" else ta.bounds_m[3]
        xb = tb.bounds_m[0] if s["axis"] == "x" else tb.bounds_m[2]
        need(xa == xb == s["at_m"], f"seam {s['name']}: tiles abut at {s['at_m']} m")
        seam_rep.append({"seam": s["name"], "max_step_across_m": float(across.max()) * steps[ta.tag],
                         "max_step_beside_m": float(beside.max()) * steps[ta.tag], "bad": bad})
    rep["seams"] = seam_rep
    # plan points: decode in the tile that holds each point (by CW position)
    by_ref = {o["anchor"]["ref"]: o for o in ovs}
    by_coc = {o["coc"]: o for o in ovs}
    pts = []
    jumps = []
    rays = prm.get("plan_mode") == "rays"
    keep = prm.get("edge_keep_m", RAY_EDGE_KEEP)
    for i, w in enumerate(plan):
        keys = RAY_PLAN_KEYS if rays else PLAN_KEYS
        need(all(k in w for k in keys), f"plan entry {i} has {', '.join(keys)}")
        if not all(k in w for k in keys):
            continue
        if rays:
            # one overlay, one coc arrival per entry: the points are in the overlay's own frame, spawn_local is the
            # COC marker's ground (x, y, z), the first point is that ground vertex and is the z_ref probe
            frame = by_coc.get(w["coc"])
            need(frame is not None, f"plan entry {i}: coc {w['coc']} is the overlay's COC cell")
            need(entry_kind(w["label"]) == "ray", f"plan entry {i}: a ray entry")
            if frame is None:
                continue
            loc = list(frame["anchor"]["local"])
            need(list(w["spawn_local"]) == loc, f"plan entry {i}: spawn_local = the COC marker's ground {loc}")
            p0 = w["points"][0] if w["points"] else {}
            need(w["z_ref"] == p0.get("label") and [p0.get("x"), p0.get("y"), p0.get("expect")] == loc,
                 f"plan entry {i}: z_ref {w['z_ref']} = the first point = the arrival's ground vertex")
            dist = [math.hypot(p["x"] - loc[0], p["y"] - loc[1]) for p in w["points"]]
            need(all(dist[k] <= dist[k + 1] + 1e-6 for k in range(len(dist) - 1)),
                 f"plan entry {i}: points at increasing distance from the arrival (up to {max(dist):.0f} m)")
        else:
            frame = by_ref.get(w["anchor"]["ref"])
            need(frame is not None and w["anchor"]["local"] == frame["anchor"]["local"],
                 f"plan entry {i}: anchor = a tile anchor")
            need(w["coc"] in by_coc, f"plan entry {i}: coc {w['coc']} is a tile COC cell")
            if frame is None or w["coc"] not in by_coc:
                continue
            # the runner offsets the points by the coc'd tile's own merge offset (anchor, else spawn): the points must
            # be in that tile's frame, and spawn_local must be x, y only (a spawn read mid-fall must not move the drops)
            need(by_coc[w["coc"]]["anchor"]["ref"] == w["anchor"]["ref"], f"plan entry {i}: frame = the coc'd tile")
            need(list(w.get("spawn_local", [])) == list(frame["anchor"]["local"][:2]),
                 f"plan entry {i}: spawn_local = the coc'd tile's spawn, x and y only")
        labels = [p["label"] for p in w["points"]]
        need(len(set(labels)) == len(labels), f"plan entry {i}: point labels unique")
        need(w.get("z_ref") in labels, f"plan entry {i}: z_ref {w.get('z_ref')} is one of its points")
        ft = tiles[frame["tag"]]
        top, low = max(p["expect"] for p in w["points"]), min(p["expect"] for p in w["points"])
        if entry_kind(w["label"]) == "locate":          # probes may land on any tile: clear the whole range
            top, low = max(top, prm["hmax"]), min(low, prm["hmin"])
        need(w["drop_z"] >= top + DROP_MARGIN - 1e-6, f"plan entry {i}: drop_z {w['drop_z']} >= {top:.1f} + {DROP_MARGIN}")
        need(w["settle_ms"] >= 1000.0 * fall_seconds(w["drop_z"], low),
             f"plan entry {i}: settle {w['settle_ms']} ms covers the fall ({fall_seconds(w['drop_z'], low):.1f} s)")
        here, longest = list(frame["anchor"]["local"][:2]), 0.0
        for p in w["points"]:
            longest = max(longest, math.hypot(p["x"] - here[0], p["y"] - here[1]))
            here = [p["x"], p["y"]]
        jumps.append({"entry": i, "longest_jump_m": round(longest, 1)})
        if prm.get("max_jump_m"):
            need(longest <= 1.25 * prm["max_jump_m"], f"plan entry {i}: longest jump {longest:.0f} m")
        for p in w["points"]:
            x, y = ft.to_cw(p["x"], p["y"])
            t = og.tile_at(tl, x, y)
            need(t is not None, f"plan entry {i} point {p['label']}: inside a tile")
            if t is None:
                continue
            if entry_kind(w["label"]) in ("tile", "edges"):    # read in the tile's own landing: nothing else is known
                need(t is ft, f"plan entry {i} point {p['label']}: in the coc'd tile")
            if rays:
                need(t is ft and edge_distance(t, x, y) >= keep - 1e-6,
                     f"plan entry {i} point {p['label']}: at least {keep:g} m inside the overlay")
            if p["label"].startswith("wp"):
                need(edge_distance(t, x, y) >= EDGE_KEEP - 1e-6, f"plan entry {i} waypoint {p['label']}: outside merge rings")
            lx, ly = t.to_local(x, y)
            hs = decode_at(raws[t.tag], *dec[t.tag], t.n, lx, ly)
            e = max(abs(v - p["expect"]) for v in hs.values())
            pts.append({"entry": i, "label": p["label"], "tile": t.tag, "x": p["x"], "y": p["y"], "expect": p["expect"],
                        "decoded": {k: round(v, 4) for k, v in hs.items()}, "error_mm": round(e * 1000, 3)})
            need(e <= steps[t.tag], f"plan entry {i} point {p['label']}: decoded within one step in T{t.tag}")
    rep["points"] = pts
    rep["jumps"] = jumps
    for o in ovs:   # anchors on the ground of their own tile
        t = tiles[o["tag"]]
        ax, ay, az = o["anchor"]["local"]
        g = decode_at(raws[o["tag"]], *dec[o["tag"]], t.n, ax, ay)
        need(max(abs(v - az) for v in g.values()) <= steps[o["tag"]], f"{o['world']}: anchor z = ground")
        need(abs(o["spawn"][2] - az - SPAWN_ABOVE) < 1e-6 and o["spawn"][:2] == [ax, ay], f"{o['world']}: COC marker 2 m above the anchor")

    if plugins:
        check_plugins(out, prm, raws, need, rep, vanilla_mars_entries)
    masks = []
    for o in ovs:
        mk = mask_report(out, o["world"], o["n"], tuple(o["mask_outer_edges"]))
        need(mk["format"] == "BC4" and mk["mips"] == 1 and mk["width"] == mk["height"] == o["n"] * 100 and
             mk["pixels_differ"] == 0, f"{o['world']}: mask BC4 {mk['width']} px, ring on {mk['outer_edges']}, exact")
        masks.append(mk)
    rep["masks"] = masks
    rep["archive_inputs"] = archive_inputs(out, prm, need)
    rep["checks"] = checks
    ok = all(c[1] for c in checks)
    rep["summary"] = {"checks": len(checks), "failed": sum(1 for c in checks if not c[1]), "points": len(pts),
                      "max_point_error_mm": max(p["error_mm"] for p in pts) if pts else None,
                      "step_mm": round(min(steps.values()) * 1000, 4)}
    rep["pass"] = ok
    return ok, rep


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def archive_inputs(out, prm, need):
    """The staged Data tree, which scripts/game/exp_install.py --pack (claude/test-queue) packs whole, every top-level
    folder, into '<plugin> - Main.ba2' with -compression=None: exactly each overlay's BTD (Data/Terrain/<world>.btd),
    its byte-identical copies (Data/meshes/terrain/<world>.btd with --btd-copy-meshes) and its mask, nothing else."""
    data = os.path.join(out, "Data")
    want = {}
    for o in prm["overlays"]:
        need(o["btd_file"] == f"Data/Terrain/{o['world']}.btd", f"{o['world']}: BTD named after the WRLD EditorID")
        for rel in [o["btd_file"]] + list(o.get("btd_copies", [])) + [o["mask"]]:
            want[rel.lower()] = rel
    have = {}
    for root, _, files in os.walk(data):
        for f in files:
            rel = "Data/" + os.path.relpath(os.path.join(root, f), data).replace(os.sep, "/")
            have[rel.lower()] = rel
    need(set(have) == set(want), f"Data tree holds exactly the BTDs, their copies and the masks ({len(have)} files; "
                                 f"extra {sorted(set(have) - set(want))}, missing {sorted(set(want) - set(have))})")
    need(all(r.isascii() and " " not in r for r in have.values()), "archive paths are plain ASCII without spaces")
    files = []
    for o in prm["overlays"]:
        main = sha256_file(os.path.join(out, *o["btd_file"].split("/")))
        for c in o.get("btd_copies", []):
            p = os.path.join(out, *c.split("/"))
            need(os.path.isfile(p) and sha256_file(p) == main, f"{c}: byte-identical copy of {o['btd_file']}")
    for k in sorted(have):
        p = os.path.join(out, *have[k].split("/"))
        files.append({"path": have[k], "bytes": os.path.getsize(p)})
    return {"folders": sorted({f["path"].split("/")[1] for f in files}), "files": files,
            "total_bytes": sum(f["bytes"] for f in files),
            "packing": "exp_install.py --pack: Archive2 -format=General -compression=None (stored)"}


def latlon_cells(a, b, radius_km=og.MARS_RADIUS_KM):
    """Distance in planet cells between two (lat, lon) registrations at true planet scale (H_ll's local metric)."""
    k = og.cells_per_radian(radius_km)
    dlon = (b[1] - a[1] + math.pi) % (2 * math.pi) - math.pi
    return math.hypot((b[0] - a[0]) * k, dlon * k * math.cos((a[0] + b[0]) / 2.0))


def check_plugins(out, prm, raws, need, rep, vanilla_mars_entries):
    """Raw record walk of the overlay plugin and the Mars registration plugin (independent of Mutagen)."""
    ovs = prm["overlays"]
    d = orc.walk_plugin(os.path.join(out, prm["plugin"]))
    own = len(d["masters"]) << 24
    recs = d["records"]
    by_fid = {r["fid"]: r for r in recs}
    locs = set()
    wrld_fid = {}
    for k, o in enumerate(ovs):
        wr = [r for r in recs if r["sig"] == "WRLD" and orc.edid(r) == o["world"]]
        need(len(wr) == 1, f"one WRLD {o['world']}")
        if not wr:
            continue
        w = wr[0]
        wrld_fid[o["world"]] = w["fid"]
        xlcn = orc.field(w, "XLCN")
        loc = by_fid.get(struct.unpack("<I", xlcn)[0]) if xlcn else None
        need(loc is not None and loc["sig"] == "LCTN" and orc.edid(loc) == o["location"], f"{o['world']}: XLCN -> {o['location']}")
        if loc:
            locs.add(loc["fid"])
            kw = list(struct.unpack(f"<{len(orc.field(loc, 'KWDA', b'')) // 4}I", orc.field(loc, "KWDA", b"")))
            parent = struct.unpack("<I", orc.field(loc, "PNAM"))[0] if orc.field(loc, "PNAM") else None
            need(orc.LOC_TYPE_OVERLAY in kw and parent == orc.MARS_SURFACE, f"{o['world']}: location keyword + Mars parent")
        sfbk = by_fid.get(orc.overlay_block_ref(w))
        need(sfbk is not None and sfbk["sig"] == "SFBK" and orc.edid(sfbk) == o["block"], f"{o['world']}: overlay -> {o['block']}")
        if sfbk:
            fn = orc.field(sfbk, "FNAM", b"")
            exact, cells, worst = overlay.fnam_match(fn, raws[o["tag"]])
            need(fo4land.zstring(orc.field(sfbk, "ANAM", b"")) == o["btd_path"], f"{o['world']}: ANAM {o['btd_path']}")
            need(list(struct.unpack("<2I", orc.field(sfbk, "DNAM"))) == [o["n"], o["n"]], f"{o['world']}: DNAM {o['n']}")
            need(exact == cells == o["n"] ** 2, f"{o['world']}: FNAM {exact}/{cells} cells = SW-corner rule")
            need(list(struct.unpack("<2f", orc.field(sfbk, "ENAM"))) == [prm["hmin"], prm["hmax"]], f"{o['world']}: ENAM range")
            inam = orc.field(sfbk, "INAM", b"\0")[0]
            hnam = struct.unpack("<h", orc.field(sfbk, "HNAM", b"\0\0"))[0]
            need(inam == (1 if prm["alignment"] == "absolute" else 0) and hnam == prm["hnam"], f"{o['world']}: INAM {inam} HNAM {hnam}")
        an = [r for r in recs if r["sig"] == "REFR" and orc.edid(r) == o["anchor"]["edid"]]
        need(len(an) == 1, f"{o['world']}: one anchor REFR")
        if an:
            ar = fo4land.parse_ref(an[0]["fields"])
            need(ar["base"] == orc.XMARKER and an[0]["flags"] & orc.PERSISTENT, f"{o['world']}: anchor XMarker, persistent")
            need(an[0]["fid"] == own | o["anchor"]["form_id"] and o["anchor"]["ref"][2:].upper() == "%06X" % o["anchor"]["form_id"],
                 f"{o['world']}: anchor FormID {an[0]['fid']:08X} = plan ref {o['anchor']['ref']} (low 24 bits)")
            need(o["anchor"]["ref"][:2].upper() == prm.get("anchor_load_byte", orc.ANCHOR_LOAD_BYTE).upper(),
                 f"{o['world']}: plan ref load-order byte {o['anchor']['ref'][:2]} (assumed at run time)")
            need(max(abs(p - q) for p, q in zip(ar["pos"], o["anchor"]["local"])) < 1e-3, f"{o['world']}: anchor at {ar['pos']}")
        coc = [r for r in recs if r["sig"] == "CELL" and orc.edid(r) == o["coc"]]
        need(len(coc) == 1, f"{o['world']}: COC cell {o['coc']}")
        xclc = orc.field(coc[0], "XCLC") if coc else None
        need(xclc is not None and list(struct.unpack_from("<2i", xclc)) == o["spawn_cell"],
             f"{o['world']}: COC cell at grid {o['spawn_cell']}")
        mk = [r for r in recs if r["sig"] == "REFR" and orc.edid(r) == o["coc"] + "Marker"]
        need(len(mk) == 1, f"{o['world']}: one COC marker {o['coc']}Marker")
        if mk:
            mr = fo4land.parse_ref(mk[0]["fields"])
            need(mr["base"] == COC_MARKER and max(abs(p - q) for p, q in zip(mr["pos"], o["spawn"])) < 1e-3,
                 f"{o['world']}: COC marker is a COCMarkerHeading at {mr['pos']} (spawn {o['spawn']})")
    need(len(locs) == len(ovs), "every overlay has its own Location (the CK warns about shared ones)")
    rep["plugin"] = {"file": prm["plugin"], "bytes": d["bytes"], "masters": d["masters"],
                     "records": {s: sum(1 for r in recs if r["sig"] == s) for s in sorted({r["sig"] for r in recs})}}

    if prm.get("mars"):
        mp = orc.walk_plugin(os.path.join(out, prm["mars"]["plugin"]))
        pl = [r for r in mp["records"] if r["sig"] == "PNDT"]
        need(len(pl) == 1 and pl[0]["fid"] == orc.MARS_PNDT, "Mars plugin overrides PNDT MarsPlanetData 0003F59A")
        need(mp["masters"][:1] == ["Starfield.esm"] and prm["plugin"] in mp["masters"], f"Mars plugin masters {mp['masters']}")
        idx = mp["masters"].index(prm["plugin"]) << 24 if prm["plugin"] in mp["masters"] else -1
        ents = orc.pndt_entries(pl[0]) if pl else []
        mine = []
        for o in ovs:
            e = [x for x in ents if x[2] == idx | (wrld_fid.get(o["world"], 0) & 0xFFFFFF)]
            need(len(e) == 1, f"PNDT CNAM has one entry for {o['world']}")
            if e:
                need(abs(e[0][0] - o["latitude"]) < 1e-12 and abs(e[0][1] - o["longitude"]) < 1e-12,
                     f"{o['world']}: CNAM latitude first, longitude second ({e[0][0]:.9f}, {e[0][1]:.9f})")
                others = [x for x in ents if x is not e[0]]
                need(not any(abs(x[0] - e[0][0]) < 1e-9 and abs(x[1] - e[0][1]) < 1e-9 for x in others) and
                     sum(1 for x in ents if x[2] & 0xFFFFFF == e[0][2] & 0xFFFFFF and x[2] >> 24 == idx >> 24) == 1,
                     f"{o['world']}: CNAM entry unique (no other entry at its lat/long or with its WRLD)")
                foreign = [x for x in others if x[2] >> 24 != idx >> 24]       # not one of our own tiles
                near = min(foreign, key=lambda x: latlon_cells(e[0], x), default=None)
                gap = latlon_cells(e[0], near, prm["mars"].get("radius_km", og.MARS_RADIUS_KM)) if near else None
                need(gap is None or gap > o["n"], f"{o['world']}: nearest other CNAM entry {gap:.0f} cells away "
                                                  f"(> {o['n']}, true planet scale)" if gap is not None else "no other entry")
                mine.append({"world": o["world"], "f64_0_latitude": e[0][0], "f64_1_longitude": e[0][1],
                             "index": ents.index(e[0]), "predicted_cell": o["planet_target_cell"],
                             "nearest_other": {"wrld": "%08X" % near[2], "latitude": near[0], "longitude": near[1],
                                               "cells": round(gap, 1)} if near else None})
        if vanilla_mars_entries is not None:
            need(len(ents) == vanilla_mars_entries + len(ovs), f"PNDT CNAM {len(ents)} = vanilla {vanilla_mars_entries} + {len(ovs)}")
        rep["mars"] = {"file": prm["mars"]["plugin"], "bytes": mp["bytes"], "entries": len(ents), "ours": mine}


# --------------------------------------------------------------------------------------------------------- analyse
def parse3(s):
    try:
        v = [float(x) for x in str(s).split()]
    except ValueError:
        return None
    return v if len(v) == 3 else None


def load_runs(dirs):
    """(spec, obs, attempt folder) of every runner attempt under the queue folders: tests/<id>/a<n>/spec.json and
    obs.json (PowerShell writes obs.json with a BOM)."""
    import glob
    out = []
    for d in dirs:
        for sp in sorted(glob.glob(os.path.join(d, "tests", "*", "a*", "spec.json"))):
            ob = os.path.join(os.path.dirname(sp), "obs.json")
            if os.path.isfile(ob):
                with open(sp, encoding="utf-8-sig") as f:
                    spec = json.load(f)
                with open(ob, encoding="utf-8-sig") as f:
                    obs = json.load(f)
                out.append((spec, obs, os.path.dirname(sp)))
    return out


def analyse_attempt(spec, obs, prm, raws, tol=0.5, window=30, free_z=False):
    """What one runner attempt measured, independent of the runner's verdict: the merge offset of its landing (from
    the spawn; whole cells or not), the anchor read, the Z offset (z_ref probe), every point's height error in the
    entry's frame, and for every tile the whole-cell shift that matches the heights read (og.locate_tile): (0, 0) for
    the coc'd tile itself, H_ll's prediction for the others if they lie edge to edge."""
    ovs = {o["anchor"]["ref"]: o for o in prm["overlays"]}
    frame = ovs.get((spec.get("anchor") or {}).get("ref"))
    if frame is None and not spec.get("anchor"):        # ray entries (--plan rays) carry no anchor: the coc'd overlay
        frame = next((o for o in prm["overlays"] if o["coc"] == spec.get("world_coc")), None)
    if frame is None:
        return {"id": spec.get("id"), "error": "the entry's anchor is not one of the staged tiles"}
    tiles = {o["tag"]: og.Tile(o["ix"], o["iy"], o["cells_cw"]["x"][0], o["cells_cw"]["y"][0], o["n"])
             for o in prm["overlays"]}
    ft = tiles[frame["tag"]]
    res = {"id": spec.get("id"), "kind": entry_kind(spec.get("model", "")), "frame": f"T{frame['tag']}",
           "anchor_read": obs.get("anchor_read"), "anchor_unmerged": bool(obs.get("anchor_unmerged")),
           "runner_offset": obs.get("offset"), "runner_offset_from": obs.get("offset_from")}
    spawn, sl = parse3(obs.get("spawn_read")), spec.get("spawn_local")
    merge, merge_from = None, None
    if spawn and sl:
        so = (spawn[0] - sl[0], spawn[1] - sl[1])
        cells = og.whole_cells(*so)
        res.update(spawn_read=spawn, spawn_offset_m=[round(v, 2) for v in so], spawn_offset_cells=cells)
        if cells is not None:
            merge, merge_from = (cells[0] * og.SF_CELL_M, cells[1] * og.SF_CELL_M), "spawn (whole cells)"
    ar = parse3(obs.get("anchor_read"))
    if ar:
        loc = frame["anchor"]["local"]
        res["anchor_offset_m"] = [round(ar[k] - loc[k], 2) for k in range(3)]
    if merge is None and obs.get("offset"):
        merge, merge_from = tuple(obs["offset"][:2]), f"runner ({obs.get('offset_from')})"
    if merge is None:
        merge, merge_from = (0.0, 0.0), "none (0)"
    res["merge_offset_m"], res["merge_from"] = [round(v, 2) for v in merge], merge_from
    reads = [(p, parse3(o.get("read")) if isinstance(o, dict) else None)
             for p, o in zip(spec.get("points", []), obs.get("points") or [])]
    oz, oz_from = 0.0, "none (0)"
    zr = next(((p, r) for p, r in reads if r and p["label"] == spec.get("z_ref")), None)
    if zr and zr[1][2] > prm["hmin"] - 50:
        oz, oz_from = zr[1][2] - zr[0]["expect"], f"z_ref {zr[0]['label']}"
    elif spawn and sl and len(sl) >= 3:
        oz, oz_from = spawn[2] - sl[2], "spawn"
    res["z_offset_m"], res["z_from"] = round(oz, 3), oz_from
    pts, use = [], []
    for p, r in reads:
        if r is None:
            pts.append({"label": p["label"], "read": None})
            continue
        q = (r[0] - merge[0], r[1] - merge[1])
        h = r[2] - oz
        fell = h < prm["hmin"] - 50
        cx, cy = ft.to_cw(*q)
        t = og.tile_at(list(tiles.values()), cx, cy)
        dec = None
        if t is not None:
            raw = raws[t.tag]
            dec = decode_at(raw, prm["hmin"], prm["hmax"], t.n, *t.to_local(cx, cy))
        roff = obs.get("offset") or []
        runner_oz = float(roff[2]) if len(roff) >= 3 else 0.0      # the runner drops from drop_z + its Z offset
        pts.append({"label": p["label"], "x": round(q[0], 2), "y": round(q[1], 2), "h": round(h, 3),
                    "moved_m": round(math.hypot(q[0] - p["x"], q[1] - p["y"]), 2), "expect": p["expect"],
                    "error_m": round(h - p["expect"], 3), "fell": fell,
                    # still at the drop height: nothing loaded under the probe (exp3: neighbouring overlays)
                    "hung": abs(r[2] - (float(spec.get("drop_z", 0.0)) + runner_oz)) < 0.05,
                    "from_spawn_m": round(math.hypot(p["x"] - sl[0], p["y"] - sl[1]), 1) if sl else None,
                    "h_ll_tile": f"T{t.tag}" if t else None,
                    "h_ll_decoded_error_m": round(min(abs(h - v) for v in dec.values()), 3) if dec else None})
        if not fell:
            use.append((q[0], q[1], h, r[2]))
    res["points"] = pts
    good = [p for p in pts if p.get("h") is not None and not p["fell"]]
    res["summary"] = {"read": len(good) + sum(1 for p in pts if p.get("fell")), "of": len(spec.get("points", [])),
                      "fell": sum(1 for p in pts if p.get("fell")),
                      "hung": sum(1 for p in pts if p.get("hung")),
                      "within_0.5m": sum(1 for p in good if abs(p["error_m"]) <= 0.5),
                      "worst_m": max((abs(p["error_m"]) for p in good), default=None)}

    def decoder(tag):
        t = tiles[tag]
        return lambda lx, ly: decode_at(raws[tag], prm["hmin"], prm["hmax"], t.n, lx, ly).values()
    # the coc'd tile itself: (0, 0) unless its BTD sits off its own frame (e.g. a wrong grid-origin rule for even
    # sizes). If its heights do not fit with the z_ref Z offset (a z_ref probe off by a shift reads the wrong height),
    # search again with a free Z offset on the raw heights and use that offset for the other tiles.
    rel = [(x, y, h) for x, y, h, _ in use]
    own = og.locate_tile(rel, ft.n, decoder(frame["tag"]), (0, 0), window=2, tol=tol)
    res["locate_z"] = res["z_from"]
    if own["best"] is None:
        alt = og.locate_tile([(x, y, z) for x, y, _, z in use], ft.n, decoder(frame["tag"]), (0, 0), window=2,
                             tol=tol, free_z=True)
        if alt["best"] is not None:
            own, dz = alt, alt["best"]["dz"]
            rel = [(x, y, z - dz) for x, y, _, z in use]
            res["locate_z"] = f"free, from the coc'd tile's own heights ({dz:+.2f} m)"
    use = rel
    loc = {f"T{frame['tag']}": {"predicted": [0, 0], **own}}
    d0 = own["best"]["d"] if own["best"] else (0, 0)
    lo, hi = tg.grid_origin(ft.n), tg.grid_origin(ft.n) + ft.n * og.SF_CELL_M

    def explained_by_frame(x, y, h):
        """A read that the coc'd tile itself explains (at its own located shift) is not evidence for another tile."""
        lx, ly = x - d0[0] * og.SF_CELL_M, y - d0[1] * og.SF_CELL_M
        return lo <= lx < hi and lo <= ly < hi and min(abs(h - v) for v in decoder(frame["tag"])(lx, ly)) <= tol
    rest = [r for r in use if not explained_by_frame(*r)]
    for tag, t in tiles.items():
        if tag == frame["tag"]:
            continue
        pred = (int(round((t.origin_m[0] - ft.origin_m[0]) / og.SF_CELL_M)),
                int(round((t.origin_m[1] - ft.origin_m[1]) / og.SF_CELL_M)))
        loc[f"T{tag}"] = {"predicted": list(pred), **og.locate_tile(rest, t.n, decoder(tag), pred, window=window,
                                                                    tol=tol, free_z=free_z)}
    res["locate"] = loc
    return res


def analyse(a):
    prm = json.loads(orc.read_bytes(os.path.join(a.out, "overlays_params.json")))
    raws = {o["tag"]: btd.read(orc.read_bytes(os.path.join(a.out, *o["btd_file"].split("/")))).heights_raw
            for o in prm["overlays"]}
    runs = load_runs(a.runs)
    if not runs:
        sys.exit(f"no runner attempts (tests/*/a*/spec.json + obs.json) under {a.runs}")
    out = [dict(analyse_attempt(spec, obs, prm, raws, a.tol, a.window, a.free_z), dir=d) for spec, obs, d in runs]
    for r in out:
        if "error" in r:
            print(f"{r['id']}: {r['error']}")
            continue
        s = r["summary"]
        print(f"{r['id']} [{os.path.basename(r['dir'])}] {r['kind']} in {r['frame']}'s landing: merge offset "
              f"{r['merge_offset_m']} m from {r['merge_from']} (spawn offset {r.get('spawn_offset_m')}, whole cells "
              f"{r.get('spawn_offset_cells')}); anchor offset {r.get('anchor_offset_m')}; Z offset {r['z_offset_m']} "
              f"from {r['z_from']}")
        print(f"    points {s['read']} of {s['of']} read, {s['fell']} fell through, {s['hung']} hung at the drop height, "
              f"{s['within_0.5m']} within 0.5 m, worst {s['worst_m']}; tiles located with Z offset {r['locate_z']}")
        if r["kind"] == "ray":                         # how far the overlay loads around this arrival
            print("    " + "; ".join(f"{p['label']} @{p.get('from_spawn_m')} m: " +
                                     ("no read" if p.get("h") is None else "hung" if p.get("hung") else
                                      f"{p['error_m']:+.2f} m") for p in r["points"]))
        for tag, v in r["locate"].items():
            b = v["best"]
            alt = ", ".join(f"{tuple(c['d'])} {c['match']}/{c['inside']}" for c in v["consistent"][1:3])
            top = v["top"][0] if v["top"] else None
            print(f"    {tag}: predicted {tuple(v['predicted'])}; " +
                  (f"found at {tuple(b['d'])} ({b['match']}/{b['inside']} interior reads match, ring "
                   f"{b['ring_match']}/{b['ring']})" if b else
                   f"not found (best {tuple(top['d'])} {top['match']}/{top['inside']})" if top else "no read inside") +
                  (f"; also consistent: {alt}" if alt else ""))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
    return 0


def parser():
    """The command line (also the defaults other front ends start from, e.g. scripts/terrain/make_skyrim_overlay.py)."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("build", "check", "analyse"))
    ap.add_argument("--fo4", help="Fallout4.esm")
    ap.add_argument("--fo4-npz", help="cached FO4 LAND grids (.npz with 'grid' and 'heights') instead of --fo4")
    ap.add_argument("--sf-data", default="", help="Starfield Data folder (build: LTEX template BTD; check: Starfield.esm)")
    ap.add_argument("--out", required=True, help="staging folder, e.g. C:\\Modding\\staging\\terrain_exp3")
    ap.add_argument("--fo4-cells", type=int, nargs=4, default=[-35, 10, -6, 40], metavar=("X0", "X1", "Y0", "Y1"),
                    help="inclusive FO4 cell rectangle (default: experiment 3 around Sanctuary, Vault 111, Red Rocket)")
    ap.add_argument("--tile", type=int, default=14, help="cells per tile side (14 = the largest vanilla unique overlay); "
                                                         "a tile at least as large as the region gives one overlay")
    ap.add_argument("--pad", choices=("centre", "sw", "origin"), default="centre",
                    help="padding of the region to whole tiles; origin: tile origins on multiples of --tile cells, so the "
                         "tile over the FO4 origin has local = CW (single overlays)")
    ap.add_argument("--grid-points", type=int, default=0, help="also check a K x K spread of vertices per tile")
    ap.add_argument("--prefix", default="FO4CW3", help="EditorID prefix of the worlds (FO4CW3_T00, ...)")
    ap.add_argument("--plugin", default="FO4TerrainExp3.esm")
    ap.add_argument("--mars-plugin", default="FO4TerrainExp3_Mars.esm")
    ap.add_argument("--no-mars", action="store_true")
    ap.add_argument("--experiment", default="terrain_exp3")
    ap.add_argument("--alignment", choices=("relative", "absolute"), default="absolute")
    ap.add_argument("--hnam", type=int, default=0)
    ap.add_argument("--radius-km", type=float, default=og.MARS_RADIUS_KM)
    ap.add_argument("--ref-lat", type=float, default=og.WORLD01_LATLON[0], help="reference registration latitude (rad)")
    ap.add_argument("--ref-lon", type=float, default=og.WORLD01_LATLON[1], help="reference registration longitude (rad)")
    ap.add_argument("--ref-offset", type=int, nargs=2, default=list(og.WORLD01_OFFSET),
                    help="measured planet cell of the reference overlay's local origin")
    ap.add_argument("--centre-cell", type=int, nargs=2, default=[0, 0], help="planet cell for the region's centre")
    ap.add_argument("--mask-writer", choices=("texconv", "builtin"), default="texconv")
    ap.add_argument("--mask-ns", choices=og.MASK_NS, default="symmetric",
                    help="north / south mask rings: 'symmetric' only in pairs (mask row order unresolved), 'outer' on "
                         "every outer edge")
    ap.add_argument("--load-byte", default=orc.ANCHOR_LOAD_BYTE,
                    help="load-order byte of the plugin at run time for the anchor refs in plan.json (exp2b: 02)")
    ap.add_argument("--max-jump", type=float, default=MAX_JUMP, help="waypoints keep setpos jumps under this (0: off)")
    ap.add_argument("--locate-step", type=float, default=LOCATE_STEP, help="spacing of locate probes (m)")
    ap.add_argument("--plan", choices=("grid", "rays"), default="grid",
                    help="grid: tile / group / locate / edges entries (exp3); rays: one overlay, one coc arrival per "
                         "entry, probes at --ray-distances from the arrival along each of --rays (core64)")
    ap.add_argument("--world", default="", help="WRLD EditorID of a single overlay (default <prefix>_T<tag>)")
    ap.add_argument("--coc", default="", help="COC cell EditorID of a single overlay (default <world>Spawn)")
    ap.add_argument("--btd-copy-meshes", action="store_true",
                    help="also stage the BTD as Data/meshes/terrain/<world>.btd (as Shattered Space ships it)")
    ap.add_argument("--rays", type=parse_rays, default=RAYS, help="rays plan: name:bearing_deg,... (0 = east)")
    ap.add_argument("--ray-distances", type=float, nargs="+", default=list(RAY_DISTANCES))
    ap.add_argument("--edge-keep", type=float, default=RAY_EDGE_KEEP, help="rays plan: metres inside the overlay edge")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--no-plugins", action="store_true", help="check: skip the plugin record walk (before dotnet ran)")
    ap.add_argument("--runs", nargs="+", default=[], help="analyse: runner queue folder(s) with tests/*/a*/obs.json")
    ap.add_argument("--tol", type=float, default=0.5, help="analyse: height match tolerance (m)")
    ap.add_argument("--window", type=int, default=30, help="analyse: cells searched around H_ll's prediction")
    ap.add_argument("--free-z", action="store_true", help="analyse: allow one Z offset per tile and shift")
    ap.add_argument("--json", default="", help="analyse: write the full result here")
    return ap


def main():
    a = parser().parse_args()
    if a.cmd == "build":
        if not a.sf_data:
            sys.exit("--sf-data is required for build")
        if not (a.fo4 or a.fo4_npz):
            sys.exit("--fo4 or --fo4-npz is required for build")
        if not re.fullmatch(r"[0-9A-Fa-f]{2}", a.load_byte):
            sys.exit("--load-byte must be two hex digits")
        for v in (a.world, a.coc):
            if v and not re.fullmatch(r"[A-Za-z0-9_]+", v):
                sys.exit(f"bad EditorID {v!r}")
        if a.coc and not a.coc.endswith("Spawn"):
            sys.exit("--coc must end in Spawn (the runner's COC naming)")
        if (a.world or a.coc or a.plan == "rays") and len(og.split(*og.sf_cells_of_fo4_rect(*a.fo4_cells), a.tile,
                                                                   a.pad)) != 1:
            sys.exit("--world, --coc and --plan rays need a single overlay (--tile at least the region, --pad origin)")
        os.makedirs(a.out, exist_ok=True)
        return build(a)
    if a.cmd == "analyse":
        return analyse(a)
    if not a.sf_data:
        sys.exit("--sf-data is required for check")
    return check(a)


if __name__ == "__main__":
    sys.exit(main())
