"""Skyrim (Special Edition) landscape as a source for the Starfield terrain builder.

Skyrim stores exterior terrain exactly like Fallout 4, so this module reuses `fo4land` unchanged:

* LAND -> VHGT: f32 offset, 33 x 33 signed byte gradients, 3 unused bytes; height = 8 * (offset + accumulated
  gradient) game units; row 0 = south, column 0 = west; 4,096-unit cells, so vertices are 128 units apart
  (UESP "Skyrim Mod:Mod File Format/LAND"; same decoder as fo4land.decode_vhgt).
* 24-byte record and group headers, zlib-compressed records (flag 0x40000: u32 size + zlib stream), WRLD top group
  -> world children (1) -> exterior blocks (4) / sub-blocks (5) -> CELL + cell children (6, 8, 9).
* Game units: Skyrim, Fallout 4 and Oblivion share the Bethesda unit, so the repo's 70 units per metre applies
  (verified for FO4 objects and terrain in Starfield, docs/terrain/core64c.md; for Skyrim a supported hypothesis
  with the same engine lineage, first checked by the in-game probes of the Skyrim overlay).

What is Skyrim-specific is only which data exists: the worldspace is `Tamriel`, its LAND grid is not the
Commonwealth's fixed -96..95 square (the extent is read from the file), some cells inside the rectangle may have no
LAND (the engine then draws the WRLD DNAM default land height; this module fills them with it and reports them), and
landmarks come from exterior cell EditorIDs (the names `coc` accepts) instead of hard-coded FO4 form ids.

Everything is read-only; nothing derived from the game files is written into the repository.
"""
import math
import re
import struct

import numpy as np

from fo4sf import fo4land

WORLD = "Tamriel"
CELL_UNITS = fo4land.CELL_UNITS


def world_dnam(fields):
    """(default land height, default water height) in game units from a WRLD's DNAM, or (None, None)."""
    for sig, d in fields:
        if sig == b"DNAM" and len(d) >= 8:
            return struct.unpack_from("<ff", d)
    return None, None


class SkyrimLand:
    """Every exterior cell of one worldspace: decoded VHGT grids, cell EditorIDs and the WRLD defaults.

    grids    {(cx, cy): (33, 33) float64 heights in game units}
    edids    {(cx, cy): cell EditorID} for cells that have one
    extent   (x0, x1, y0, y1): inclusive rectangle of the cells that have VHGT
    holes    cells inside `extent` without VHGT (filled with `default_land` by the overlay builder)
    """

    def __init__(self, esm, world=WORLD):
        self.esm, self.world = esm, world
        with fo4land.Plugin(esm) as p:
            w = p.read_world(world, cells=None, refs=False)
        self.world_fid = w["world_fid"]
        self.default_land, self.default_water = world_dnam(w["world_fields"])
        self.grids, self.edids, self.cells = {}, {}, set()
        for xy, c in w["cells"].items():
            self.cells.add(xy)
            if c["edid"]:
                self.edids[xy] = c["edid"]
            if c["vhgt"]:
                self.grids[xy] = fo4land.decode_vhgt(c["vhgt"])
        if not self.grids:
            raise ValueError(f"{esm}: worldspace {world!r} has no LAND/VHGT")
        xs = [x for x, _ in self.grids]
        ys = [y for _, y in self.grids]
        self.extent = (min(xs), max(xs), min(ys), max(ys))
        x0, x1, y0, y1 = self.extent
        self.holes = sorted((x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1) if (x, y) not in self.grids)

    # ------------------------------------------------------------------ numbers

    def height_range(self):
        """(min, max) height in game units over every VHGT vertex."""
        lo = min(float(g.min()) for g in self.grids.values())
        hi = max(float(g.max()) for g in self.grids.values())
        return lo, hi

    def fill_height(self):
        """Height for a cell without LAND: the WRLD default land height, else the lowest real vertex."""
        if self.default_land is not None and math.isfinite(self.default_land):
            return float(self.default_land)
        return self.height_range()[0]

    def seams(self):
        """fo4land.edge_mismatches over every neighbour pair (Skyrim's own cell borders should match exactly)."""
        rep = fo4land.edge_mismatches(self.grids)
        rep["mismatches"] = sorted(rep["mismatches"], key=lambda s: -s["max_abs"])[:5]
        return rep

    # ------------------------------------------------------------------ landmarks

    def find_cells(self, pattern):
        """[(edid, (cx, cy))] of exterior cells whose EditorID matches the regex (case-insensitive), sorted."""
        rx = re.compile(pattern, re.I)
        return sorted(((e, xy) for xy, e in self.edids.items() if rx.search(e)), key=lambda t: t[0].lower())

    def cell_by_edid(self, edid):
        for xy, e in self.edids.items():
            if e.lower() == edid.lower():
                return xy
        return None

    def landmark(self, spec):
        """A landmark tuple (name, form id, x, y) in game units at a cell centre, the overlay builder's format.
        `spec` is an exterior cell EditorID (e.g. one `coc` accepts) or 'X,Y' cell coordinates.
        Returns None if no such cell exists in the worldspace."""
        m = re.fullmatch(r"\s*(-?\d+)\s*,\s*(-?\d+)\s*", spec)
        if m:
            xy, name = (int(m.group(1)), int(m.group(2))), f"cell_{m.group(1)}_{m.group(2)}".replace("-", "m")
            if xy not in self.cells and xy not in self.grids:
                return None
        else:
            xy, name = self.cell_by_edid(spec), spec
            if xy is None:
                return None
        name = re.sub(r"[^A-Za-z0-9_]", "_", name).lower()
        return (name, 0, (xy[0] + 0.5) * CELL_UNITS, (xy[1] + 0.5) * CELL_UNITS)

    def summary(self):
        lo, hi = self.height_range()
        x0, x1, y0, y1 = self.extent
        return {"world": self.world, "world_fid": "%08X" % self.world_fid, "cells": len(self.cells),
                "cells_with_vhgt": len(self.grids), "extent": {"x": [x0, x1], "y": [y0, y1]},
                "extent_m": {"x": [x0 * CELL_UNITS / 70.0, (x1 + 1) * CELL_UNITS / 70.0],
                             "y": [y0 * CELL_UNITS / 70.0, (y1 + 1) * CELL_UNITS / 70.0]},
                "holes": len(self.holes), "holes_first": [list(h) for h in self.holes[:10]],
                "heights_units": [lo, hi], "heights_m": [lo / 70.0, hi / 70.0],
                "default_land_units": self.default_land, "default_water_units": self.default_water,
                "named_cells": len(self.edids)}


class SkyrimHeights:
    """Drop-in for make_cw_overlays.Fo4Heights backed by an already read SkyrimLand (no second pass over the ESM)."""

    def __init__(self, land, grid=None, fill=None):
        self.land = land
        self.world = land.world
        self.grid = tuple(grid) if grid else land.extent
        self.fill = land.fill_height() if fill is None else fill
        self.grids = dict(land.grids)

    def load(self, cells):        # everything is already decoded
        return None

    def merged(self, x0, x1, y0, y1):
        gx0, gx1, gy0, gy1 = self.grid
        x0, x1 = max(x0, gx0), min(x1, gx1)
        y0, y1 = max(y0, gy0), min(y1, gy1)
        return merge_with_fill(self.grids, x0, x1, y0, y1, self.fill), (x0 * fo4land.CELL_UNITS,
                                                                       y0 * fo4land.CELL_UNITS)


def merge_with_fill(grids, x0, x1, y0, y1, fill):
    """fo4land.merge_cells over the inclusive rectangle where cells without a grid take `fill`, but only on vertices
    no real cell covers: a real neighbour keeps its own shared edge vertices (merge_cells alone would let whichever
    cell lies south / west win the shared edge, so a missing cell there would overwrite the real edge)."""
    nan = np.full((fo4land.GRID, fo4land.GRID), np.nan)
    have = {(x, y): grids.get((x, y), nan) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    g, _ = fo4land.merge_cells(have, x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    g[np.isnan(g)] = float(fill)
    return g
