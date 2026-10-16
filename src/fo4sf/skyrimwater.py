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
where it had none. Cells whose best level is the sea (the default) are left to the planet's own ocean.
"""
from typing import Dict, List, Optional, Tuple

from fo4sf import fo4land
from fo4sf import terrain_grid as tg

UNITS_PER_M = 70.0
STEP = fo4land.CELL_UNITS / 32.0


def cell_levels(grids: Dict[Tuple[int, int], "object"], water: Dict[Tuple[int, int], Optional[float]],
                default_water: Optional[float], origin_m=(0.0, 0.0), offset_m: float = 0.0,
                cell_range: Optional[Tuple[int, int]] = None) -> List[dict]:
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
            score = sum(1 for z, w in verts if (w is not None and z < w) == (z < h))
            if score > best_score:
                best, best_score = h, score
        if default_water is not None and abs(best - default_water) < 1.0:
            continue                                   # the sea: the planet's ocean already draws it
        out.append({"cell": list(sc), "height_m": round(best / UNITS_PER_M + offset_m, 3), "wet_vertices": len(wet),
                    "agree": round(best_score / len(verts), 3)})
    return out
