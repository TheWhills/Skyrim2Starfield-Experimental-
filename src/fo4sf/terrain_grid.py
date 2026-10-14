"""Map Fallout 4 terrain (LAND vertex grid, FO4 units) onto a Starfield BTD grid (metres) at absolute positions.

Conventions (docs/terrain/architecture.md, 1.5, and docs/terrain/experiment2.md):
* Starfield exterior cell = 100 m, 128 BTD samples per cell side, so samples are 100 / 128 = 0.78125 m apart.
* A BTD of n x n cells starts n // 2 cells west / south of the world origin: its south-west sample is at
  (-(n // 2) * 100, -(n // 2) * 100) m and sample (row r, col c) is at (x0 + c * step, y0 + r * step), row 0 = south.
  (supported hypothesis, terrain experiment 1 tests it in game)
* FO4 positions and heights convert with the repo's object scale: metres = FO4 units / 70 (hypothesis H for heights).
* FO4 LAND vertices are 128 units apart, row 0 = south, column 0 = west (verified, docs/terrain/source-patch.md).

Everything here is pure arithmetic on arrays so it can be tested with synthetic grids (tests/test_terrain_grid.py).
"""
import math

import numpy as np

SF_CELL_M = 100.0
SF_CELL_SAMPLES = 128
SF_STEP_M = SF_CELL_M / SF_CELL_SAMPLES        # 0.78125 m
FO4_CELL_UNITS = 4096.0
FO4_VERTEX_UNITS = 128.0
UNITS_PER_METRE = 70.0
MAX_CELLS = 100                                 # largest vanilla BTD (100 x 100 cells, verified survey)


def grid_origin(n):
    """World x (= y) in metres of the south-west sample of an n x n-cell BTD."""
    return -(n // 2) * SF_CELL_M


def sample_coords(n):
    """World coordinates (metres) of the n * 128 sample columns (= rows) of an n x n-cell BTD."""
    return grid_origin(n) + np.arange(n * SF_CELL_SAMPLES) * SF_STEP_M


def cell_range(n):
    """Inclusive Starfield cell index range covered by an n x n-cell BTD: (first, last)."""
    return -(n // 2), n - n // 2 - 1


def sf_cell_of(x, y):
    """Starfield exterior cell (100 m grid) containing world position (x, y) in metres."""
    return int(math.floor(x / SF_CELL_M)), int(math.floor(y / SF_CELL_M))


def choose_n(xmin, xmax, ymin, ymax, max_n=MAX_CELLS):
    """Smallest n whose BTD samples span [xmin, xmax] x [ymin, ymax] (metres), given the fixed origin rule.
    The grid must reach the region on both sides of the origin, so an off-centre region needs a large n."""
    lo, hi = min(xmin, ymin), max(xmax, ymax)
    for n in range(1, max_n + 1):
        if grid_origin(n) <= lo and grid_origin(n) + (n * SF_CELL_SAMPLES - 1) * SF_STEP_M >= hi:
            return n
    raise ValueError(f"region {xmin, xmax, ymin, ymax} needs more than {max_n} x {max_n} cells")


def fo4_cells_covering(xmin_m, xmax_m, ymin_m, ymax_m, units_per_metre=UNITS_PER_METRE):
    """Inclusive FO4 cell ranges (x0, x1, y0, y1) whose vertices span the metre rectangle, so bilinear
    interpolation inside it never needs a vertex outside these cells."""
    def rng(a, b):
        return (int(math.floor(a * units_per_metre / FO4_CELL_UNITS)),
                int(math.floor(b * units_per_metre / FO4_CELL_UNITS)))
    x0, x1 = rng(xmin_m, xmax_m)
    y0, y1 = rng(ymin_m, ymax_m)
    return x0, x1, y0, y1


def _axis_weights(coords, origin, spacing, count):
    """Index of the lower vertex and the fraction towards the next one, with coordinates clamped to the grid:
    outside it the value of the nearest edge vertex is used (no extrapolation, no cliff)."""
    u = (np.asarray(coords, np.float64) - origin) / spacing
    u = np.clip(u, 0.0, count - 1)
    i = np.minimum(np.floor(u).astype(np.int64), max(count - 2, 0))
    f = u - i
    if count == 1:
        i, f = np.zeros_like(i), np.zeros_like(f)
    return i, f


def resample_bilinear(grid, origin_x, origin_y, spacing, xs, ys):
    """Bilinear interpolation of `grid` ([row, col], row 0 = south; vertex (r, c) at (origin_x + c * spacing,
    origin_y + r * spacing)) at every (xs[j], ys[i]). Returns an array [len(ys), len(xs)].
    Separable: first along x for every grid row, then along y. Points outside the grid take the nearest edge value."""
    g = np.asarray(grid, np.float64)
    rows, cols = g.shape
    ci, cf = _axis_weights(xs, origin_x, spacing, cols)
    ri, rf = _axis_weights(ys, origin_y, spacing, rows)
    c1 = np.minimum(ci + 1, cols - 1)
    r1 = np.minimum(ri + 1, rows - 1)
    along_x = g[:, ci] * (1.0 - cf) + g[:, c1] * cf               # [rows, len(xs)]
    return along_x[ri, :] * (1.0 - rf)[:, None] + along_x[r1, :] * rf[:, None]


def btd_height_at(heights_m, n, x, y):
    """Bilinear height (metres) of a decoded n x n-cell BTD grid at world (x, y), using the origin rule above."""
    o = grid_origin(n)
    return float(resample_bilinear(heights_m, o, o, SF_STEP_M, [x], [y])[0, 0])


def point_interp(grid, origin_x, origin_y, spacing, x, y):
    """Height of `grid` at one point under the three usual rules for a quad: bilinear and the two triangle splits
    (diagonal SW-NE or NW-SE). The engine's rule for BTD samples is unknown, so check points use all three."""
    g = np.asarray(grid, np.float64)
    rows, cols = g.shape
    u = min(max((x - origin_x) / spacing, 0.0), cols - 1.0)
    v = min(max((y - origin_y) / spacing, 0.0), rows - 1.0)
    c, r = min(int(u), cols - 2), min(int(v), rows - 2)
    fu, fv = u - c, v - r
    h00, h01, h10, h11 = g[r, c], g[r, c + 1], g[r + 1, c], g[r + 1, c + 1]
    sw_ne = h00 + (h01 - h00) * fu + (h11 - h01) * fv if fu >= fv else h00 + (h10 - h00) * fv + (h11 - h10) * fu
    nw_se = (h00 + (h01 - h00) * fu + (h10 - h00) * fv if fu + fv <= 1
             else h11 + (h10 - h11) * (1 - fu) + (h01 - h11) * (1 - fv))
    return {"bilinear": float(h00 * (1 - fu) * (1 - fv) + h01 * fu * (1 - fv) + h10 * (1 - fu) * fv + h11 * fu * fv),
            "tri_sw_ne": float(sw_ne), "tri_nw_se": float(nw_se)}


def local_slope_deg(grid, r, c, spacing):
    """Slope (degrees) at vertex (r, c) from central differences over its neighbours (one-sided at the edge)."""
    g = np.asarray(grid, np.float64)
    c0, c1 = max(c - 1, 0), min(c + 1, g.shape[1] - 1)
    r0, r1 = max(r - 1, 0), min(r + 1, g.shape[0] - 1)
    dx = (g[r, c1] - g[r, c0]) / ((c1 - c0) * spacing)
    dy = (g[r1, c] - g[r0, c]) / ((r1 - r0) * spacing)
    return math.degrees(math.atan(math.hypot(dx, dy)))


def is_flat(grid, r, c, radius):
    """True if all (2 * radius + 1)^2 vertices around (r, c) have the same height (False at the grid edge)."""
    g = np.asarray(grid)
    if r - radius < 0 or c - radius < 0 or r + radius >= g.shape[0] or c + radius >= g.shape[1]:
        return False
    w = g[r - radius:r + radius + 1, c - radius:c + radius + 1]
    return bool(w.max() == w.min())


def connections_raw(raw):
    """Eight raw u16 border heights for an SFBK FNAM: SW, S, SE, E, NE, N, NW, W (row 0 = south). Only the first
    one (SW corner) matches vanilla blocks (3 of 3 checked); the meaning of the other seven is unresolved."""
    h = np.asarray(raw)
    r, c = h.shape[0] - 1, h.shape[1] - 1
    return [int(h[0, 0]), int(h[0, c // 2]), int(h[0, c]), int(h[r // 2, c]),
            int(h[r, c]), int(h[r, c // 2]), int(h[r, 0]), int(h[r // 2, 0])]
