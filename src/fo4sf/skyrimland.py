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
CHILD_MARGIN = 4                   # parent cells read around a child worldspace (a city's surroundings)
CELL_UNITS = fo4land.CELL_UNITS


def world_dnam(fields):
    """(default land height, default water height) in game units from a WRLD's DNAM, or (None, None)."""
    for sig, d in fields:
        if sig == b"DNAM" and len(d) >= 8:
            return struct.unpack_from("<ff", d)
    return None, None


def world_parent(fields):
    """(parent WRLD form id or None, parent flags) from WNAM / PNAM (PNAM bit 0x1 = Use Land Data)."""
    parent, flags = None, 0
    for sig, d in fields:
        if sig == b"WNAM" and len(d) >= 4:
            parent = struct.unpack_from("<I", d)[0] or None
        elif sig == b"PNAM" and len(d) >= 2:
            flags = struct.unpack_from("<H", d)[0]
    return parent, flags


def world_edid(p: fo4land.Plugin, fid: int) -> str:
    start, end = p.top_group(b"WRLD")
    for item in fo4land.iter_items(p.buf, start, end):
        if item[0] != "GRUP" and item[3] == fid:
            for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, item[1])):
                if sig == b"EDID":
                    return fo4land.zstring(d)
    raise KeyError(f"worldspace {fid:08X} not found")


def list_worlds(esm: str) -> list:
    """[{edid, form_id, parent, use_land, cells, land, extent}] of every worldspace in the plugin."""
    out = []
    with fo4land.Plugin(esm) as p:
        start, end = p.top_group(b"WRLD")
        recs = [(item[1], item[3]) for item in fo4land.iter_items(p.buf, start, end) if item[0] == b"WRLD"]
        names = {}
        for off, fid in recs:
            for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                if sig == b"EDID":
                    names[fid] = fo4land.zstring(d)
        for off, fid in recs:
            fields = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
            parent, flags = world_parent(fields)
            w = p.read_world(names[fid], cells=None, refs=False)
            cells = list(w["cells"])
            land = sum(1 for c in w["cells"].values() if c["vhgt"])
            ext = None
            if cells:
                xs, ys = [x for x, _ in cells], [y for _, y in cells]
                ext = [min(xs), max(xs), min(ys), max(ys)]
            out.append({"edid": names[fid], "form_id": "%08X" % fid, "parent": names.get(parent),
                        "use_parent_land": bool(flags & 1), "cells": len(cells), "land": land, "extent": ext})
    return out


class SkyrimLand:
    """Every exterior cell of one worldspace: decoded VHGT grids, cell EditorIDs and the WRLD defaults.

    grids    {(cx, cy): (33, 33) float64 heights in game units}
    edids    {(cx, cy): cell EditorID} for cells that have one
    extent   (x0, x1, y0, y1): inclusive rectangle of the cells that have VHGT
    holes    cells inside `extent` without VHGT (filled with `default_land` by the overlay builder)
    """

    def __init__(self, esm, world=WORLD):
        self.esm, self.world = esm, world
        self.land_source = world                  # the worldspace whose LAND the heights come from
        child_extent = None
        with fo4land.Plugin(esm) as p:
            w = p.read_world(world, cells=None, refs=False)
            self.world_fid = w["world_fid"]
            self.default_land, self.default_water = world_dnam(w["world_fields"])
            self.parent, self.parent_flags = world_parent(w["world_fields"])
            self.grids, self.edids, self.cells = {}, {}, set()
            for xy, c in w["cells"].items():
                self.cells.add(xy)
                if c["edid"]:
                    self.edids[xy] = c["edid"]
                if c["vhgt"]:
                    self.grids[xy] = fo4land.decode_vhgt(c["vhgt"])
            if not self.grids and self.parent and self.cells:
                # a child worldspace without LAND of its own (Skyrim's walled cities use their parent's terrain, flag
                # "Use Land Data"; they share the parent's coordinates): the parent's LAND under the child's cells
                pedid = world_edid(p, self.parent)
                xs = [x for x, _ in self.cells]
                ys = [y for _, y in self.cells]
                child_extent = (min(xs), max(xs), min(ys), max(ys))
                m = CHILD_MARGIN                  # plus a ring of the parent's terrain around the city (outside the walls)
                want = {(x, y) for x in range(min(xs) - m, max(xs) + m + 1) for y in range(min(ys) - m, max(ys) + m + 1)}
                pw = p.read_world(pedid, cells=want, refs=False)
                for xy, c in pw["cells"].items():
                    if c["vhgt"]:
                        self.grids[xy] = fo4land.decode_vhgt(c["vhgt"])
                if self.default_land is None:
                    self.default_land, self.default_water = world_dnam(pw["world_fields"])
                self.land_source = pedid
        if not self.grids:
            raise ValueError(f"{esm}: worldspace {world!r} has no LAND/VHGT" +
                             (" and its parent none under its cells" if self.parent else ""))
        xs = [x for x, _ in self.grids]
        ys = [y for _, y in self.grids]
        self.grid_bounds = (min(xs), max(xs), min(ys), max(ys))       # every cell with heights
        # the rectangle the overlay is sized for: the LAND extent, or for a child on its parent's land the child's cells
        self.extent = child_extent if self.land_source != world else self.grid_bounds
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
        return {"world": self.world, "world_fid": "%08X" % self.world_fid, "land_source": self.land_source,
                "cells": len(self.cells),
                "cells_with_vhgt": len(self.grids), "extent": {"x": [x0, x1], "y": [y0, y1]},
                "extent_m": {"x": [x0 * CELL_UNITS / 70.0, (x1 + 1) * CELL_UNITS / 70.0],
                             "y": [y0 * CELL_UNITS / 70.0, (y1 + 1) * CELL_UNITS / 70.0]},
                "holes": len(self.holes), "holes_first": [list(h) for h in self.holes[:10]],
                "heights_units": [lo, hi], "heights_m": [lo / 70.0, hi / 70.0],
                "default_land_units": self.default_land, "default_water_units": self.default_water,
                "named_cells": len(self.edids)}


FALLOFF_CELLS = 4.0               # outside the LAND rectangle: blend from the edge height to the fill over 4 cells (234 m)


def falloff_weight(d, length):
    """1 at the LAND edge (d = 0), falling smoothly (smoothstep) to 0 at d >= length; d and length in game units."""
    if length <= 0:
        return (np.asarray(d) <= 0).astype(np.float64)
    t = np.clip(np.asarray(d, dtype=np.float64) / length, 0.0, 1.0)
    return 1.0 - t * t * (3.0 - 2.0 * t)


class SkyrimHeights:
    """Drop-in for make_cw_overlays.Fo4Heights backed by an already read SkyrimLand (no second pass over the ESM).

    Inside the LAND rectangle (`grid`) heights are Skyrim's, holes at the fill height. Outside it Skyrim has no ground
    at all, and the square overlay still needs heights there: instead of repeating the edge vertex outwards (streaks,
    and a cliff wherever the edge is a mountain, which Starfield's edge blending turns into a wall), each outside
    vertex takes the nearest edge height eased to the fill height over `falloff` game units. The value depends only on
    the vertex's position, so neighbouring tiles agree on their seams."""

    def __init__(self, land, grid=None, fill=None, falloff_cells=FALLOFF_CELLS):
        self.land = land
        self.world = land.world
        self.grid = tuple(grid) if grid else land.grid_bounds
        self.fill = land.fill_height() if fill is None else fill
        self.falloff = float(falloff_cells) * fo4land.CELL_UNITS
        self.grids = dict(land.grids)

    def load(self, cells):        # everything is already decoded
        return None

    def merged(self, x0, x1, y0, y1):
        """Vertex grid (game units) and origin for the inclusive cell rectangle, NOT clamped to the LAND grid."""
        gx0, gx1, gy0, gy1 = self.grid
        origin = (x0 * fo4land.CELL_UNITS, y0 * fo4land.CELL_UNITS)
        ix0, ix1, iy0, iy1 = max(x0, gx0), min(x1, gx1), max(y0, gy0), min(y1, gy1)
        if (ix0, ix1, iy0, iy1) == (x0, x1, y0, y1):
            return merge_with_fill(self.grids, x0, x1, y0, y1, self.fill), origin
        q = fo4land.GRID - 1                                  # vertices per cell edge (32)
        cols = np.arange(x0 * q, (x1 + 1) * q + 1)            # global vertex indices of the requested grid
        rows = np.arange(y0 * q, (y1 + 1) * q + 1)
        if ix0 > ix1 or iy0 > iy1:                            # entirely outside: the nearest edge is the whole grid's
            ix0, ix1, iy0, iy1 = gx0, gx1, gy0, gy1
        inner = merge_with_fill(self.grids, ix0, ix1, iy0, iy1, self.fill)
        lo_c, hi_c, lo_r, hi_r = ix0 * q, (ix1 + 1) * q, iy0 * q, (iy1 + 1) * q
        cc, rr = np.clip(cols, lo_c, hi_c), np.clip(rows, lo_r, hi_r)
        step = fo4land.CELL_UNITS / q
        dx2 = (((cols - cc) * step) ** 2)[None, :]
        out = np.empty((len(rows), len(cols)))
        for a in range(0, len(rows), 512):                    # row chunks: no full-size temporaries for all of Tamriel
            b = min(a + 512, len(rows))
            edge = inner[np.ix_(rr[a:b] - lo_r, cc - lo_c)]   # nearest vertex of the LAND rectangle
            d = np.sqrt((((rows[a:b] - rr[a:b]) * step) ** 2)[:, None] + dx2)
            out[a:b] = self.fill + (edge - self.fill) * falloff_weight(d, self.falloff)
        return out, origin


def merge_with_fill(grids, x0, x1, y0, y1, fill):
    """fo4land.merge_cells over the inclusive rectangle where cells without a grid take `fill`, but only on vertices
    no real cell covers: a real neighbour keeps its own shared edge vertices (merge_cells alone would let whichever
    cell lies south / west win the shared edge, so a missing cell there would overwrite the real edge)."""
    nan = np.full((fo4land.GRID, fo4land.GRID), np.nan)
    have = {(x, y): grids.get((x, y), nan) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    g, _ = fo4land.merge_cells(have, x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    g[np.isnan(g)] = float(fill)
    return g
