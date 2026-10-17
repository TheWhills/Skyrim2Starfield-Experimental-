"""Skyrim's rivers and lakes as Starfield cell water (make_skyrim_overlay.py build --skyrim-water).

Skyrim (verified only on synthetic files here): an exterior cell whose DATA flags set "has water" (0x2) holds water at
XCLW (game units) or, without XCLW, at the worldspace's default water height (DNAM; Tamriel's sea, -14000). Rivers are
stepped: each cell has one flat level, and the river bed falls from cell to cell.

Starfield keeps the same cell fields (Mutagen Cell.xml: XCLW WaterHeight, XCWT Water, DATA flag HasWater 0x2) and its
worldspaces list the cells with their own level (WRLD XCLW CellWaterHeightLocations + WHGT WaterHeights: New Atlantis
lists 8 cells, owner's SfInspect dump). Supported hypothesis, not yet seen in game: an overlay worldspace's cells draw
water at their XCLW.

Starfield cells are 100 m, Skyrim's 58.5 m, so one Starfield cell can span two river steps. Each Starfield cell takes
the level that keeps most of Skyrim's LAND vertices inside it right: wet where Skyrim had water above the ground, dry
where it had none, and never more than 2 % of them wet where Skyrim is dry (owner's Jemison views: a mountain lake's
level otherwise hung as a flat sheet over the slope beside it). Cells whose best level is the sea (the default) are left to the planet's own ocean unless include_sea (owner's
whole-map test: the ocean and Solitude's docks had no water inside the overlay, so --skyrim-water-sea writes them).
"""
from typing import Dict, List, Optional, Tuple

from fo4sf import fo4land
from fo4sf import terrain_grid as tg

UNITS_PER_M = 70.0
STEP = fo4land.CELL_UNITS / 32.0


def cell_levels(grids: Dict[Tuple[int, int], "object"], water: Dict[Tuple[int, int], Optional[float]],
                default_water: Optional[float], origin_m=(0.0, 0.0), offset_m: float = 0.0,
                cell_range: Optional[Tuple[int, int]] = None, max_false_wet: float = 0.02,
                include_sea: bool = False) -> List[dict]:
    """[{"cell": [x, y], "height_m", "wet_vertices", "agree"}] for every Starfield cell that should hold water above
    the sea. grids: SkyrimLand.grids (33 x 33 heights, units); water: SkyrimLand.water (units, cells with water only);
    origin_m: the overlay's origin_cw_m; offset_m: --height-offset; cell_range: (min, max) overlay cell index."""
    per: Dict[Tuple[int, int], List[Tuple[float, Optional[float]]]] = {}
    for (cx, cy), g in grids.items():
        own = water.get((cx, cy))
        for r in range(33):
            for c in range(33):
                x = (cx * fo4land.CELL_UNITS + c * STEP) / UNITS_PER_M - origin_m[0]
                y = (cy * fo4land.CELL_UNITS + r * STEP) / UNITS_PER_M - origin_m[1]
                sc = tg.sf_cell_of(x, y)
                if cell_range and not (cell_range[0] <= sc[0] <= cell_range[1] and cell_range[0] <= sc[1] <= cell_range[1]):
                    continue
                per.setdefault(sc, []).append((float(g[r, c]), own))
    out = []
    for sc, verts in sorted(per.items()):
        wet = [(z, w) for z, w in verts if w is not None and z < w]
        if not wet:
            continue
        best, best_score = None, -1
        for h in sorted({w for _z, w in wet}):
            # a level that floods ground Skyrim keeps dry (a mountain lake's level over the valley beside it) would
            # hang in the air as a flat sheet over that ground: allow at most max_false_wet of the cell's vertices
            false_wet = sum(1 for z, w in verts if z < h and not (w is not None and z < w))
            if false_wet > max_false_wet * len(verts):
                continue
            score = sum(1 for z, w in verts if (w is not None and z < w) == (z < h))
            if score > best_score:
                best, best_score = h, score
        if best is None:
            continue
        if default_water is not None and abs(best - default_water) < 1.0 and not include_sea:
            continue                                   # the sea, left to the planet's ocean unless include_sea
        out.append({"cell": list(sc), "height_m": round(best / UNITS_PER_M + offset_m, 3), "wet_vertices": len(wet),
                    "agree": round(best_score / len(verts), 3)})
    return out


def outside_sea(cell_range: Tuple[int, int], origin_m, offset_m: float, grid_bounds, holes, sea_units: float,
                taken=()) -> List[dict]:
    """Sea water for every overlay cell that reaches past Skyrim's ground: cells (part) outside the LAND rectangle
    `grid_bounds` (Skyrim cell x0, x1, y0, y1) or over a hole (a Skyrim cell without LAND), which the overlay builder
    fills with sea floor (make_skyrim_overlay.py --outside-fill sea). `taken`: overlay cells that already have water.
    Owner's view (2026-10-17): with the old land-height fill the overlay's outer ring was a flat plateau ~155 m above
    Jemison's sea, a pale cliff around Skyrim's coast."""
    x0, x1, y0, y1 = grid_bounds
    holes = set(map(tuple, holes))
    taken = set(map(tuple, taken))
    cu = fo4land.CELL_UNITS
    out = []
    lo, hi = cell_range
    for sx in range(lo, hi + 1):
        for sy in range(lo, hi + 1):
            if (sx, sy) in taken:
                continue
            ux0, ux1 = (sx * 100.0 + origin_m[0]) * UNITS_PER_M, ((sx + 1) * 100.0 + origin_m[0]) * UNITS_PER_M
            uy0, uy1 = (sy * 100.0 + origin_m[1]) * UNITS_PER_M, ((sy + 1) * 100.0 + origin_m[1]) * UNITS_PER_M
            kx0, kx1 = int(ux0 // cu), int((ux1 - 1e-6) // cu)
            ky0, ky1 = int(uy0 // cu), int((uy1 - 1e-6) // cu)
            beyond = kx0 < x0 or kx1 > x1 or ky0 < y0 or ky1 > y1
            if not beyond:
                beyond = any((kx, ky) in holes for kx in range(kx0, kx1 + 1) for ky in range(ky0, ky1 + 1))
            if beyond:
                out.append({"cell": [sx, sy], "height_m": round(sea_units / UNITS_PER_M + offset_m, 3),
                            "wet_vertices": 0, "agree": 1.0, "outside": True})
    return out
