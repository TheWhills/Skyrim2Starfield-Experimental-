"""A ship landing site on the Skyrim overlay (make_skyrim_overlay.py build -> overlays_params.json "landing"; used by
scripts/terrain/make_planet.py for the landing and map markers).

The flattest dry square of pad_m metres within radius_m of a point (the overlay's arrival, Riverwood by default),
from Skyrim's own LAND heights: every Skyrim vertex inside the square is above the sea and not under any river / lake
water, and the square's height range (max - min) is the smallest found on a step_m grid. New Atlantis's landing pad
markers are ShipLandingMarker_80m_Large (owner's survey_markers.py run): 80 m pads.
"""
import math
from typing import Dict, Optional, Tuple

import numpy as np

from fo4sf import fo4land

UNITS_PER_M = 70.0
STEP_UNITS = fo4land.CELL_UNITS / 32.0


def flat_site(grids, water, default_water: Optional[float], origin_m=(0.0, 0.0), offset_m: float = 0.0,
              near_xy=(0.0, 0.0), radius_m: float = 1500.0, pad_m: float = 80.0, step_m: float = 20.0,
              min_above_sea_m: float = 3.0) -> Optional[Dict[str, float]]:
    """{"x", "y", "z" (top of the ground in the square), "range_m", "distance_m"} or None (no dry square found)."""
    cell_m = fo4land.CELL_UNITS / UNITS_PER_M
    reach = radius_m + pad_m
    xs, ys, zs, wet = [], [], [], []
    cols = np.arange(33) * STEP_UNITS / UNITS_PER_M
    for (cx, cy), g in grids.items():
        x0 = cx * cell_m - origin_m[0]
        y0 = cy * cell_m - origin_m[1]
        if abs(x0 + cell_m / 2 - near_xy[0]) > reach + cell_m or abs(y0 + cell_m / 2 - near_xy[1]) > reach + cell_m:
            continue
        gx, gy = np.meshgrid(x0 + cols, y0 + cols)          # rows = y, columns = x, as the LAND grid
        z = np.asarray(g, np.float64)
        own = water.get((cx, cy))
        w = np.zeros_like(z, bool) if own is None else (z < own)
        xs.append(gx.ravel()); ys.append(gy.ravel()); zs.append(z.ravel()); wet.append(w.ravel())
    if not xs:
        return None
    x, y, z, w = (np.concatenate(v) for v in (xs, ys, zs, wet))
    sea = (default_water if default_water is not None else -1e9) + min_above_sea_m * UNITS_PER_M
    bad = w | (z < sea)
    # bin the vertices onto the step grid; a pad is k x k bins (min / max / bad / count per bin, then per window)
    k = max(1, int(round(pad_m / step_m)))
    gx0, gy0 = near_xy[0] - reach, near_xy[1] - reach
    n = int(math.ceil(2 * reach / step_m)) + 1
    ix = np.floor((x - gx0) / step_m).astype(np.int64)
    iy = np.floor((y - gy0) / step_m).astype(np.int64)
    keep = (ix >= 0) & (ix < n) & (iy >= 0) & (iy < n)
    ix, iy, zk, bk = ix[keep], iy[keep], z[keep], bad[keep]
    zmax = np.full((n, n), -np.inf); zmin = np.full((n, n), np.inf)
    cnt = np.zeros((n, n), np.int64); nbad = np.zeros((n, n), np.int64)
    np.maximum.at(zmax, (iy, ix), zk); np.minimum.at(zmin, (iy, ix), zk)
    np.add.at(cnt, (iy, ix), 1); np.add.at(nbad, (iy, ix), bk.astype(np.int64))
    m = n - k + 1
    wmax = np.full((m, m), -np.inf); wmin = np.full((m, m), np.inf)
    wcnt = np.zeros((m, m), np.int64); wbad = np.zeros((m, m), np.int64)
    for dy in range(k):
        for dx in range(k):
            wmax = np.maximum(wmax, zmax[dy:dy + m, dx:dx + m]); wmin = np.minimum(wmin, zmin[dy:dy + m, dx:dx + m])
            wcnt += cnt[dy:dy + m, dx:dx + m]; wbad += nbad[dy:dy + m, dx:dx + m]
    jj, ii = np.mgrid[0:m, 0:m]
    cx = gx0 + (ii + k / 2) * step_m
    cy = gy0 + (jj + k / 2) * step_m
    dist = np.hypot(cx - near_xy[0], cy - near_xy[1])
    ok = (wbad == 0) & (wcnt >= 16) & (dist <= radius_m) & np.isfinite(wmax)
    if not ok.any():
        return None
    rng = np.where(ok, (wmax - wmin) / UNITS_PER_M, np.inf)
    score = np.round(rng, 1) * 1e6 + dist                  # flattest first, then nearest
    j, i = np.unravel_index(int(np.argmin(np.where(ok, score, np.inf))), score.shape)
    return {"x": round(float(cx[j, i]), 3), "y": round(float(cy[j, i]), 3),
            "z": round(float(wmax[j, i]) / UNITS_PER_M + offset_m, 3), "range_m": round(float(rng[j, i]), 2),
            "distance_m": round(float(dist[j, i]), 1)}
