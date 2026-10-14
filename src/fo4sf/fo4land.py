"""Fallout 4 landscape reader: LAND/VHGT heights, CELL grid (XCLC) and placed references of one worldspace.

The VHGT decoding follows fo76utils' `fo4land` (src/landdata.cpp, LandscapeData::loadESMFile; MIT licence,
(c) 2021-2025 fo76utils), which was read as the reference; no code was copied or run:

* VHGT = float32 offset, then 33 x 33 signed bytes, then 3 unused bytes (fo4land requires size >= 1093).
* Row 0 is the south edge, column 0 the west edge. The first byte of each row is a gradient added to the running
  height of the previous row's first vertex; the other bytes of a row are gradients from the vertex to the west.
* Absolute height in game units = 8 * (offset + accumulated gradient). fo4land writes `offset * 8 + (z << 3)`.
* A cell is 4096 units wide, so the 33 vertices of a row are 128 units apart and row/column 32 lies on the
  neighbouring cell's row/column 0. fo4land keeps only 32 x 32 vertices per cell (it drops the shared 33rd); this
  module keeps all 33 so the shared edges can be checked.

The plugin walker reads the standard Bethesda group layout: top group WRLD, a WRLD record followed by its world
children group (type 1), exterior blocks (4) and sub-blocks (5), each CELL followed by its cell children group (6)
with persistent (8) and temporary (9) children. Compressed records (flag 0x40000) are a u32 size + zlib stream.
"""
import mmap
import re
import struct
import zlib

import numpy as np

GRID = 33
CELL_UNITS = 4096.0
VERTEX_SPACING = CELL_UNITS / (GRID - 1)  # 128 units
UNITS_PER_METRE = 70.0  # the repo's object conversion; NOT proven to be the right scale for Starfield terrain
COMPRESSED = 0x00040000
VHGT_MIN_SIZE = 4 + GRID * GRID  # 1093, the same lower bound fo4land checks
REF_TYPES = (b"REFR", b"ACHR")

_REC = struct.Struct("<4sIII")  # type, data size, flags, form id (header is 24 bytes)
_GRP = struct.Struct("<4sI4si")  # "GRUP", total size incl. header, label, group type


# ---------------------------------------------------------------------------------------------------- VHGT

def decode_vhgt(data):
    """Return a (33, 33) float64 array of absolute heights in FO4 units; [row, col], row 0 = south, col 0 = west."""
    if len(data) < VHGT_MIN_SIZE:
        raise ValueError(f"VHGT too short: {len(data)} < {VHGT_MIN_SIZE}")
    offset = struct.unpack_from("<f", data, 0)[0]
    g = np.frombuffer(bytes(data[4:VHGT_MIN_SIZE]), dtype=np.int8).astype(np.int64).reshape(GRID, GRID)
    z = np.empty((GRID, GRID), dtype=np.int64)
    z[:, 0] = np.cumsum(g[:, 0])
    z[:, 1:] = z[:, :1] + np.cumsum(g[:, 1:], axis=1)
    return (float(offset) + z.astype(np.float64)) * 8.0


def encode_vhgt(offset, steps, pad=b"\0\0\0"):
    """Inverse of decode_vhgt for tests: `steps` is a (33, 33) integer array of heights in 8-unit steps relative
    to `offset` (so height = 8 * (offset + steps)). Raises if a gradient does not fit a signed byte."""
    s = np.asarray(steps, dtype=np.int64).reshape(GRID, GRID)
    g = np.empty_like(s)
    g[:, 0] = np.diff(s[:, 0], prepend=0)
    g[:, 1:] = np.diff(s, axis=1)
    if g.min() < -128 or g.max() > 127:
        raise ValueError("gradient outside signed byte range")
    return struct.pack("<f", offset) + g.astype(np.int8).tobytes() + pad


# ---------------------------------------------------------------------------------------------------- records

def iter_subrecords(data):
    """Yield (sig, bytes) for a record's fields; handles XXXX big-size prefixes."""
    p, n, big = 0, len(data), None
    while p + 6 <= n:
        sig = bytes(data[p:p + 4])
        size = struct.unpack_from("<H", data, p + 4)[0]
        p += 6
        if big is not None:
            size, big = big, None
        if sig == b"XXXX":
            big = struct.unpack_from("<I", data, p)[0]
            p += size
            continue
        yield sig, data[p:p + size]
        p += size


def record_data(buf, off):
    """Field bytes of the record at `off` (decompressed when flagged)."""
    _typ, size, flags, _fid = _REC.unpack_from(buf, off)
    raw = buf[off + 24:off + 24 + size]
    if flags & COMPRESSED:
        return zlib.decompress(raw[4:])
    return bytes(raw)


def iter_items(buf, start, end):
    """Yield items in [start, end): ('GRUP', off, end_off, label_bytes, group_type) or (type, off, flags, fid)."""
    off = start
    while off + 24 <= end:
        typ = bytes(buf[off:off + 4])
        if typ == b"GRUP":
            _t, gsize, label, gtype = _GRP.unpack_from(buf, off)
            yield "GRUP", off, off + gsize, label, gtype
            off += gsize
        else:
            _t, size, flags, fid = _REC.unpack_from(buf, off)
            yield typ, off, flags, fid
            off += 24 + size


def zstring(b):
    return bytes(b).split(b"\0", 1)[0].decode("cp1252", "replace")


def parse_ref(fields):
    """Pick NAME (base), DATA (pos, rot) and XSCL from a REFR/ACHR field list."""
    out = {"base": None, "pos": None, "rot": None, "scale": 1.0}
    for sig, d in fields:
        if sig == b"NAME" and len(d) >= 4:
            out["base"] = struct.unpack_from("<I", d)[0]
        elif sig == b"DATA" and len(d) >= 24:
            v = struct.unpack_from("<6f", d)
            out["pos"], out["rot"] = list(v[:3]), list(v[3:])
        elif sig == b"XSCL" and len(d) >= 4:
            out["scale"] = struct.unpack_from("<f", d)[0]
    return out


class Plugin:
    """Memory-mapped plugin file. Use as a context manager."""

    def __init__(self, path):
        self.path = path
        self._f = open(path, "rb")
        self.buf = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        typ, size, _flags, _fid = _REC.unpack_from(self.buf, 0)
        if typ != b"TES4":
            raise ValueError(f"{path}: not a plugin")
        self.body = 24 + size

    def close(self):
        self.buf.close()
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def top_group(self, label):
        for item in iter_items(self.buf, self.body, len(self.buf)):
            if item[0] == "GRUP" and item[3] == label:
                return item[1] + 24, item[2]
        return None

    # ------------------------------------------------------------------ base records

    def base_records(self, wanted=None, edid_regex=None, skip_groups=(b"WRLD", b"CELL", b"DIAL", b"QUST")):
        """{form_id: (type, editor_id, obnd)} for top-level records whose id is in `wanted` or whose EDID matches.
        obnd = (x1, y1, z1, x2, y2, z2) object bounds in FO4 units, or None."""
        rx = re.compile(edid_regex, re.I) if edid_regex else None
        out = {}
        for item in iter_items(self.buf, self.body, len(self.buf)):
            if item[0] != "GRUP" or item[3] in skip_groups:
                continue
            for typ, off, _flags, fid in iter_items(self.buf, item[1] + 24, item[2]):
                if typ == "GRUP":
                    continue
                if wanted is not None and fid not in wanted and rx is None:
                    continue
                edid, obnd = "", None
                for sig, d in iter_subrecords(record_data(self.buf, off)):
                    if sig == b"EDID":
                        edid = zstring(d)
                    elif sig == b"OBND" and len(d) >= 12:
                        obnd = struct.unpack_from("<6h", d)
                        break
                if (wanted is not None and fid in wanted) or (rx is not None and rx.search(edid)):
                    out[fid] = (typ.decode("ascii"), edid, obnd)
        return out

    # ------------------------------------------------------------------ worldspace

    def find_world(self, edid):
        """(form_id, world_children_start, end, fields) of the WRLD whose EDID equals `edid`."""
        start, end = self.top_group(b"WRLD")
        pending = None
        for item in iter_items(self.buf, start, end):
            if item[0] == "GRUP":
                if pending and item[4] == 1 and struct.unpack("<I", item[3])[0] == pending[0]:
                    return pending[0], item[1] + 24, item[2], pending[1]
                continue
            typ, off, _flags, fid = item
            if typ == b"WRLD":
                fields = list(iter_subrecords(record_data(self.buf, off)))
                name = next((zstring(d) for s, d in fields if s == b"EDID"), "")
                pending = (fid, fields) if name == edid else None
        raise KeyError(f"worldspace {edid!r} not found")

    def read_world(self, edid, cells=None, refs=True):
        """Walk one worldspace. `cells`: set of (x, y) to load LAND/refs for (None = all).
        Returns {"world_fid", "world_fields", "cells": {(x, y): cell}, "persistent": [ref, ...]}.
        cell = {"fid", "edid", "x", "y", "vhgt": bytes|None, "land_fid", "refs": [ref], "persistent_refs": [ref]}.
        """
        wfid, start, end, wfields = self.find_world(edid)
        result = {"world_fid": wfid, "world_fields": wfields, "cells": {}, "persistent": []}
        self._walk_world(start, end, cells, refs, result, None, in_block=False)
        return result

    def _walk_world(self, start, end, wanted, refs, result, cell, in_block):
        for item in iter_items(self.buf, start, end):
            if item[0] == "GRUP":
                _g, off, gend, label, gtype = item
                if gtype in (4, 5):
                    self._walk_world(off + 24, gend, wanted, refs, result, None, in_block=True)
                elif gtype == 6:
                    if cell is not None and struct.unpack("<I", label)[0] == cell["fid"]:
                        self._walk_world(off + 24, gend, wanted, refs, result, cell, in_block)
                elif gtype in (8, 9) and cell is not None:
                    self._read_cell_children(off + 24, gend, refs, cell, persistent=(gtype == 8))
                continue
            typ, off, _flags, fid = item
            if typ != b"CELL":
                continue
            xy, name = None, ""
            for sig, d in iter_subrecords(record_data(self.buf, off)):
                if sig == b"XCLC" and len(d) >= 8:
                    xy = struct.unpack_from("<ii", d)
                elif sig == b"EDID":
                    name = zstring(d)
            new = {"fid": fid, "edid": name, "x": None, "y": None, "vhgt": None, "land_fid": None,
                   "refs": [], "persistent_refs": []}
            if not in_block or xy is None:
                # The worldspace's persistent cell sits directly in the world children group, outside the exterior
                # blocks. In Fallout4.esm Commonwealth it is CELL 00018AA2 with XCLC (0, 0) and 33,146 persistent
                # children, so it must not be confused with the real cell (0, 0).
                new["persistent_cell"] = True
                new["x"], new["y"] = xy if xy else (None, None)
                cell = new
                result["persistent_cell"] = new
                continue
            new["x"], new["y"] = xy
            if wanted is None or xy in wanted:
                result["cells"][xy] = new
                cell = new
            else:
                cell = None

    def _read_cell_children(self, start, end, refs, cell, persistent):
        for item in iter_items(self.buf, start, end):
            if item[0] == "GRUP":
                continue
            typ, off, _flags, fid = item
            if typ == b"LAND":
                for sig, d in iter_subrecords(record_data(self.buf, off)):
                    if sig == b"VHGT":
                        cell["vhgt"], cell["land_fid"] = bytes(d), fid
            elif refs and typ in REF_TYPES:
                r = parse_ref(iter_subrecords(record_data(self.buf, off)))
                r["fid"], r["type"] = fid, typ.decode("ascii")
                (cell["persistent_refs"] if persistent else cell["refs"]).append(r)


# ---------------------------------------------------------------------------------------------------- patch

def cell_of(x, y):
    """Cell grid coordinates containing world position (x, y) in FO4 units."""
    return int(np.floor(x / CELL_UNITS)), int(np.floor(y / CELL_UNITS))


def merge_cells(grids, x0, y0, nx, ny):
    """Merge per-cell (33, 33) grids {(cx, cy): array} into one ((32*ny+1), (32*nx+1)) grid with origin
    (x0, y0) at index [0, 0] (south-west). Returns (merged, edge_report). Shared edge vertices are taken from the
    south / west cell; edge_report holds the max |difference| against the neighbour's copy."""
    n = GRID - 1
    merged = np.full((n * ny + 1, n * nx + 1), np.nan)
    ew, ns = [], []
    for cy in range(ny):
        for cx in range(nx):
            g = grids[(x0 + cx, y0 + cy)]
            r0, c0 = cy * n, cx * n
            block = merged[r0:r0 + GRID, c0:c0 + GRID]
            mask = np.isnan(block)
            block[mask] = g[mask]
            east = grids.get((x0 + cx + 1, y0 + cy))
            if east is not None and cx + 1 < nx:
                ew.append(float(np.abs(g[:, n] - east[:, 0]).max()))
            north = grids.get((x0 + cx, y0 + cy + 1))
            if north is not None and cy + 1 < ny:
                ns.append(float(np.abs(g[n, :] - north[0, :]).max()))
    report = {"east_west_pairs": len(ew), "east_west_max_abs": max(ew) if ew else None,
              "north_south_pairs": len(ns), "north_south_max_abs": max(ns) if ns else None}
    return merged, report


def edge_mismatches(grids):
    """Compare every east/north neighbour pair present in {(cx, cy): (33, 33) grid}.
    Returns {"pairs", "max_abs", "mismatched_vertices", "mismatches": [{cell, neighbour, max_abs, vertices}]}."""
    out = {"pairs": 0, "max_abs": 0.0, "mismatched_vertices": 0, "mismatches": []}
    n = GRID - 1
    for (x, y), g in grids.items():
        for dx, dy in ((1, 0), (0, 1)):
            nb = grids.get((x + dx, y + dy))
            if nb is None:
                continue
            a, b = (g[:, n], nb[:, 0]) if dx else (g[n, :], nb[0, :])
            diff = np.abs(a - b)
            out["pairs"] += 1
            if diff.max() > 0:
                out["max_abs"] = max(out["max_abs"], float(diff.max()))
                out["mismatched_vertices"] += int((diff > 0).sum())
                out["mismatches"].append({"cell": [x, y], "neighbour": [x + dx, y + dy],
                                          "max_abs": float(diff.max()), "vertices": int((diff > 0).sum())})
    return out


def height_at(merged, origin_x, origin_y, x, y, method="bilinear"):
    """Terrain height at world (x, y) from a merged grid whose [0, 0] vertex is at (origin_x, origin_y).
    method: 'bilinear', 'tri_sw_ne' or 'tri_nw_se' (the two possible quad splits; FO4's split is unresolved)."""
    u = (x - origin_x) / VERTEX_SPACING
    v = (y - origin_y) / VERTEX_SPACING
    rows, cols = merged.shape
    if not (0 <= u <= cols - 1 and 0 <= v <= rows - 1):
        return None
    c, r = min(int(u), cols - 2), min(int(v), rows - 2)
    fu, fv = u - c, v - r
    h00, h01 = merged[r, c], merged[r, c + 1]
    h10, h11 = merged[r + 1, c], merged[r + 1, c + 1]
    if method == "bilinear":
        return float(h00 * (1 - fu) * (1 - fv) + h01 * fu * (1 - fv) + h10 * (1 - fu) * fv + h11 * fu * fv)
    if method == "tri_sw_ne":  # diagonal from (0,0) to (1,1)
        if fu >= fv:
            return float(h00 + (h01 - h00) * fu + (h11 - h01) * fv)
        return float(h00 + (h10 - h00) * fv + (h11 - h10) * fu)
    if method == "tri_nw_se":  # diagonal from (0,1) to (1,0)
        if fu + fv <= 1:
            return float(h00 + (h01 - h00) * fu + (h10 - h00) * fv)
        return float(h11 + (h10 - h11) * (1 - fu) + (h01 - h11) * (1 - fv))
    raise ValueError(method)


def slope_degrees(merged):
    """Per-vertex slope (degrees) from central differences at 128-unit spacing."""
    dz_dy, dz_dx = np.gradient(merged, VERTEX_SPACING)
    return np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
