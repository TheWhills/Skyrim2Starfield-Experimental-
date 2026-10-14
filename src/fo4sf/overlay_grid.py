"""Split a Commonwealth region into Starfield overlay worldspaces (one or a grid of tiles) that fit edge to edge.

docs/terrain/commonwealth-scale.md explains the choice. This module is the pure arithmetic, tested with synthetic data
(tests/test_overlay_grid.py):

* Commonwealth frame ("CW"): metres = FO4 units / 70 from the FO4 origin (the repo's object scale). Starfield cells are
  100 m, so Starfield cell c covers CW [100 c, 100 (c + 1)).
* A tile is an n x n-cell overlay worldspace. Its BTD follows the grid rule of terrain_grid.py: the south-west sample is
  n // 2 cells west / south of the tile's own origin. The tile's own (local) frame is the CW frame shifted so that the
  tile's cell (cx0 + n // 2, cy0 + n // 2) is local cell (0, 0): local = CW - origin_m.
* Adjacent tiles sample one continuous 0.78125 m lattice: the first sample of a tile is one step after the last sample
  of its west / south neighbour, exactly as LOD0 blocks follow each other inside one BTD. With one shared height range
  the raw u16 values across a seam are those a single BTD of the whole region would hold.
* Overlay masks: 255 on the cell ring of OUTER edges (where vanilla overlays blend into procedural ground), 0 on
  inner seams between tiles (overlay.mask_array(n, edges=mask_edges(tile, tiles))). The image row order of a mask
  (north-first or south-first) is unresolved, so by default the north / south rings are written only when both are
  outer edges: the mask then reads the same either way and a seam never gets 255 by a flipped row order.
* Planet placement hypothesis H_ll (supported, unverified in game): near a registration the merge offset of an
  overlay moves at true planet scale, x east = R cos(lat) dlon, y north = R dlat, in 100 m cells; reference = one
  measured registration (World01 on Mars: latitude 0.2, longitude 1.2 rad -> local origin at planet cell (+30, -35)).
  PNDT CNAM stores latitude first, then longitude, in radians (Earth overlays sit at their real cities).
* Locating a tile from height reads (locate_tile): persistent anchors in our overlays read back their unmerged local
  position in game, so where a tile actually sits in another tile's landing is measured by heights alone: probes at
  known positions in the landing, matched against the tile's own BTD at every whole-cell shift.
"""
import math
from dataclasses import dataclass

import numpy as np

from . import terrain_grid as tg
from .overlay import EDGES

SF_CELL_M = tg.SF_CELL_M
MARS_RADIUS_KM = 3390.0              # MarsPlanetData body FNAM radius (Starfield.esm)
# measured 2026-10-11 (runner obs.json): World01 at latitude 0.2, longitude 1.2 rad on Mars -> its local origin at
# planet cell (+30, -35): COC marker (50, 50) arrived at (3050, -3450) in the FIRST attempt of all five registered runs
# (terrain_exp1_mars, exp1b, exp1c, B_w01, exp1d). The three second attempts that coc'd again in the same game
# session arrived at (77.6, 101.1), (74.0, 8.0) and (75.3, 99.7) instead: not a whole-cell offset of (50, 50), so
# not this merge (unexplained). exp2b kept its offset (-12, -27) in both attempts.
WORLD01_LATLON = (0.2, 1.2)
WORLD01_OFFSET = (30, -35)


@dataclass(frozen=True)
class Tile:
    ix: int          # column in the tile grid (0 = west)
    iy: int          # row in the tile grid (0 = south)
    cx0: int         # first Starfield cell (CW frame) on x
    cy0: int         # first Starfield cell (CW frame) on y
    n: int           # cells per side

    @property
    def tag(self):
        return f"{self.ix}{self.iy}" if max(self.ix, self.iy) < 10 else f"{self.ix}_{self.iy}"

    @property
    def cells_x(self):
        return self.cx0, self.cx0 + self.n - 1

    @property
    def cells_y(self):
        return self.cy0, self.cy0 + self.n - 1

    @property
    def origin_m(self):
        """CW position (metres) of the tile's local origin."""
        return (self.cx0 + self.n // 2) * SF_CELL_M, (self.cy0 + self.n // 2) * SF_CELL_M

    @property
    def bounds_m(self):
        """CW rectangle (xmin, xmax, ymin, ymax) the tile covers (the last sample is one step short of xmax)."""
        return (self.cx0 * SF_CELL_M, (self.cx0 + self.n) * SF_CELL_M,
                self.cy0 * SF_CELL_M, (self.cy0 + self.n) * SF_CELL_M)

    def to_local(self, x, y):
        ox, oy = self.origin_m
        return x - ox, y - oy

    def to_cw(self, x, y):
        ox, oy = self.origin_m
        return x + ox, y + oy

    def contains(self, x, y):
        x0, x1, y0, y1 = self.bounds_m
        return x0 <= x < x1 and y0 <= y < y1

    def sample_coords(self):
        """CW coordinates of the tile's BTD sample columns and rows (row 0 = south)."""
        k = np.arange(self.n * tg.SF_CELL_SAMPLES) * tg.SF_STEP_M
        return self.cx0 * SF_CELL_M + k, self.cy0 * SF_CELL_M + k


# ------------------------------------------------------------------------------------------------------------ region
def sf_cells_of_fo4_rect(x0, x1, y0, y1, units_per_metre=tg.UNITS_PER_METRE):
    """Inclusive Starfield cell rectangle (CW frame) that covers the inclusive FO4 cell rectangle x0..x1, y0..y1."""
    def rng(a, b):
        lo = a * tg.FO4_CELL_UNITS / units_per_metre
        hi = (b + 1) * tg.FO4_CELL_UNITS / units_per_metre
        return int(math.floor(lo / SF_CELL_M)), int(math.ceil(hi / SF_CELL_M)) - 1
    (cx0, cx1), (cy0, cy1) = rng(x0, x1), rng(y0, y1)
    return cx0, cx1, cy0, cy1


def split(cx0, cx1, cy0, cy1, tile, pad="centre"):
    """Tiles of `tile` x `tile` cells covering the inclusive Starfield cell rectangle. The rectangle is padded up to a
    whole number of tiles per axis: 'centre' splits the extra cells between both sides (west / south get the smaller
    half), 'sw' adds them on the east / north, 'origin' aligns the tile grid so that tile origins sit on multiples of
    `tile` cells: the tile over the CW origin then has its own frame equal to the CW frame (FO4 position / 70 is its
    local position, as in experiment 2). Returns tiles ordered south row first, west to east."""
    if tile < 3:
        raise ValueError("tiles need at least 3 x 3 cells (the vanilla minimum)")
    if cx1 < cx0 or cy1 < cy0:
        raise ValueError("empty rectangle")
    if pad not in ("centre", "sw", "origin"):
        raise ValueError(f"unknown padding {pad!r}")

    def axis(a0, a1):
        if pad == "origin":
            start = math.floor((a0 + tile // 2) / tile) * tile - tile // 2
            count = -(-(a1 - start + 1) // tile)
            return [start + k * tile for k in range(count)]
        w = a1 - a0 + 1
        count = -(-w // tile)
        extra = count * tile - w
        start = a0 - (extra // 2 if pad == "centre" else 0)
        return [start + k * tile for k in range(count)]

    xs, ys = axis(cx0, cx1), axis(cy0, cy1)
    return [Tile(ix, iy, x, y, tile) for iy, y in enumerate(ys) for ix, x in enumerate(xs)]


def grid_shape(tiles):
    return max(t.ix for t in tiles) + 1, max(t.iy for t in tiles) + 1


def outer_edges(tile, tiles):
    """Edges of `tile` without a neighbouring tile ('w', 'e', 's', 'n')."""
    have = {(t.ix, t.iy) for t in tiles}
    nb = {"w": (-1, 0), "e": (1, 0), "s": (0, -1), "n": (0, 1)}
    return tuple(e for e in EDGES if (tile.ix + nb[e][0], tile.iy + nb[e][1]) not in have)


MASK_NS = ("symmetric", "outer")


def mask_edges(tile, tiles, ns="symmetric"):
    """Edges whose cell ring is 255 in the tile's overlay mask. 'outer': every outer edge. 'symmetric' (default): as
    'outer', but the north and south rings only when both are outer edges, so a mask is the same under either image
    row order (unresolved, docs/terrain/overlay-records.md). In a grid with more than one row every tile then has 0 on
    its outer north / south edge too; west / east rings stay on outer edges."""
    if ns not in MASK_NS:
        raise ValueError(f"ns must be one of {MASK_NS}")
    outer = outer_edges(tile, tiles)
    if ns == "outer" or ("n" in outer and "s" in outer):
        return outer
    return tuple(e for e in outer if e not in ("n", "s"))


def seams(tiles):
    """Seam segments between neighbouring tiles: dicts with axis 'x' (a vertical line x = const between a west tile a
    and an east tile b) or 'y' (horizontal line y = const between a south tile a and a north tile b), the line's CW
    coordinate in metres and the segment's span along it."""
    by = {(t.ix, t.iy): t for t in tiles}
    out = []
    for t in tiles:
        e = by.get((t.ix + 1, t.iy))
        if e:
            x0, x1, y0, y1 = t.bounds_m
            out.append({"axis": "x", "at_m": x1, "span_m": (y0, y1), "a": t, "b": e,
                        "name": f"T{t.tag}|T{e.tag}"})
        nn = by.get((t.ix, t.iy + 1))
        if nn:
            x0, x1, y0, y1 = t.bounds_m
            out.append({"axis": "y", "at_m": y1, "span_m": (x0, x1), "a": t, "b": nn,
                        "name": f"T{t.tag}/T{nn.tag}"})
    return out


def tile_at(tiles, x, y):
    return next((t for t in tiles if t.contains(x, y)), None)


# ------------------------------------------------------------------------------------------------------------ heights
def height_range(hmin, hmax, margin=1.0):
    """Whole-metre BTD height range around the data, shared by every tile so seams quantise identically."""
    return float(math.floor(hmin) - margin), float(math.ceil(hmax) + margin)


def seam_raw_continuity(raw_a, raw_b, axis):
    """For two tiles' raw u16 grids ([row, col], row 0 = south) and the seam axis ('x': b east of a, 'y': b north of
    a), the boundary sample rows/cols on both sides: (last of a, first of b). Used by tests and the offline check."""
    if axis == "x":
        return raw_a[:, -1], raw_b[:, 0]
    return raw_a[-1, :], raw_b[0, :]


# ------------------------------------------------------------------------------------------------------------ planet
def cells_per_radian(radius_km):
    return radius_km * 1000.0 / SF_CELL_M


def predicted_offset(lat, lon, ref_latlon=WORLD01_LATLON, ref_offset=WORLD01_OFFSET, radius_km=MARS_RADIUS_KM):
    """Hypothesis H_ll: planet cell (x, y) of an overlay's local origin registered at (lat, lon) radians, from one
    measured reference registration in the same landing. Continuous; the engine is expected to use whole cells."""
    k = cells_per_radian(radius_km)
    lat0, lon0 = ref_latlon
    return (ref_offset[0] + (lon - lon0) * k * math.cos((lat + lat0) / 2.0),
            ref_offset[1] + (lat - lat0) * k)


def latlon_for_offset(target, ref_latlon=WORLD01_LATLON, ref_offset=WORLD01_OFFSET, radius_km=MARS_RADIUS_KM):
    """Inverse of predicted_offset: (lat, lon) radians that put an overlay's local origin at planet cell `target`."""
    k = cells_per_radian(radius_km)
    lat0, lon0 = ref_latlon
    lat = lat0 + (target[1] - ref_offset[1]) / k
    lon = lon0 + (target[0] - ref_offset[0]) / (k * math.cos((lat + lat0) / 2.0))
    return lat, lon


def group_targets(tiles, centre_cell=(0, 0)):
    """Planet cell targets for every tile's local origin so the tiles lie edge to edge with the region's centre (a cell
    corner of the padded rectangle) at `centre_cell`. Whole cells: {tile: (x, y)}."""
    x0 = min(t.cx0 for t in tiles)
    y0 = min(t.cy0 for t in tiles)
    x1 = max(t.cx0 + t.n for t in tiles)
    y1 = max(t.cy0 + t.n for t in tiles)
    gx, gy = (x0 + x1) // 2, (y0 + y1) // 2
    out = {}
    for t in tiles:
        ox, oy = t.cx0 + t.n // 2, t.cy0 + t.n // 2
        out[t] = (ox - gx + centre_cell[0], oy - gy + centre_cell[1])
    return out


def check_adjacent(tiles, targets):
    """True when the planet targets keep every tile at its CW cell distance from every other tile."""
    ref = tiles[0]
    rx, ry = targets[ref]
    for t in tiles:
        dx = (t.cx0 + t.n // 2) - (ref.cx0 + ref.n // 2)
        dy = (t.cy0 + t.n // 2) - (ref.cy0 + ref.n // 2)
        if targets[t] != (rx + dx, ry + dy):
            return False
    return True


# ------------------------------------------------------------------------------------------------------------ locate
def whole_cells(dx, dy, tol_m=2.0):
    """(cx, cy) when the offset (dx, dy) metres is a whole number of 100 m cells within tol_m on both axes, else None.
    A merge offset is whole cells (verified on LC172World, World01, exp2b); a spawn that slid or an unmerged load is
    not."""
    cx, cy = round(dx / SF_CELL_M), round(dy / SF_CELL_M)
    if abs(dx - cx * SF_CELL_M) <= tol_m and abs(dy - cy * SF_CELL_M) <= tol_m:
        return int(cx), int(cy)
    return None


def locate_tile(reads, n, decode, centre=(0, 0), window=30, tol=0.5, min_points=3, ring_m=SF_CELL_M, free_z=False):
    """Where an n x n-cell overlay sits, from height reads taken in another frame.

    reads: [(x, y, h)] positions and heights in the frame of the entry (the coc'd tile's own frame, Z offset removed).
    decode(lx, ly): the overlay's heights at its own local position (an iterable: one value per interpolation rule).
    A candidate D (whole cells) puts the overlay's local origin at frame position 100 * D; a read at q is then at
    overlay-local q - 100 D. Reads inside the overlay but within ring_m of its edge (the 1-cell merge ring) are counted
    apart and not required to match. A candidate is consistent when at least min_points interior reads fall inside and
    every one matches within tol (free_z: after removing their median difference, one Z offset per candidate).
    Candidates: every D within `window` cells of `centre` on both axes. Returns {best, consistent: [...], top: [...]},
    each item {d, inside, match, ring, ring_match, dz}; best = the consistent candidate with the most interior reads
    (ties: nearest to centre), None if no candidate is consistent."""
    lo = -(n // 2) * SF_CELL_M
    hi = lo + n * SF_CELL_M
    pts = [(float(x), float(y), float(h)) for x, y, h in reads]
    out = []
    for i in range(centre[0] - window, centre[0] + window + 1):
        for j in range(centre[1] - window, centre[1] + window + 1):
            inner, ring = [], []
            for x, y, h in pts:
                lx, ly = x - i * SF_CELL_M, y - j * SF_CELL_M
                if not (lo <= lx < hi and lo <= ly < hi):
                    continue
                vals = list(decode(lx, ly))
                edge = min(lx - lo, hi - lx, ly - lo, hi - ly)
                (ring if edge < ring_m else inner).append((h, vals))
            if not inner and not ring:
                continue
            dz = 0.0
            if free_z and inner:
                dz = float(np.median([h - v[0] for h, v in inner]))

            def ok(h, vals):
                return min(abs(h - dz - v) for v in vals) <= tol
            m = sum(1 for h, v in inner if ok(h, v))
            rm = sum(1 for h, v in ring if ok(h, v))
            out.append({"d": (i, j), "inside": len(inner), "match": m, "ring": len(ring), "ring_match": rm,
                        "dz": round(dz, 3)})
    need = min_points + (1 if free_z else 0)

    def dist(c):
        return abs(c["d"][0] - centre[0]) + abs(c["d"][1] - centre[1])
    consistent = sorted((c for c in out if c["inside"] >= need and c["match"] == c["inside"]),
                        key=lambda c: (-c["inside"], dist(c)))
    top = sorted(out, key=lambda c: (-c["match"], c["inside"] - c["match"], dist(c)))[:5]
    return {"best": consistent[0] if consistent else None, "consistent": consistent[:5], "top": top}
