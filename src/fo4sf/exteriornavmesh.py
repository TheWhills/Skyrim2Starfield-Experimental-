"""Skyrim's exterior navmeshes on the Starfield exterior (the Tamriel overlay on the planet), and the checks that compare
the two (docs/terrain/exterior-navmesh.md).

Skyrim's exterior navmeshes belong to Skyrim cells (4096 units = 58.5 m); Starfield's exterior cells are 100 m, so a
Skyrim navmesh usually straddles two to four Starfield cells. `split_to_cells` gives each Starfield cell the triangles
whose centre lies in it (no triangle is cut): one Skyrim navmesh becomes one navmesh per Starfield cell it touches,
the triangle edges between the pieces become edge links (the way Skyrim joins its own per-cell navmeshes), and the
pieces' search grids are rebuilt. A navmesh that lies in one Starfield cell is kept as it is (its own grid).

Positions stay in Skyrim units, already in the Starfield frame (x / 70 - origin_cw_m etc. once the writer divides by 70):
x - origin_cw_m * 70, y - ..., z + height_offset_m * 70, as make_skyrim_objects.py to_local moves the references.

Everything here is arithmetic on the dicts of skyrimnavmesh, so it is tested with synthetic navmeshes.
"""
import collections
import math
import struct
from typing import Dict, List, Optional

from . import fo4land, skyrimnavmesh, skyrimrefs
from . import terrain_grid as tg

UNITS = 70.0                     # Skyrim units per metre (the repo's object scale)
SKY_CELL = 4096.0
FLT_MAX = 3.4028234663852886e38  # vanilla interior triangles with nothing above them have this height (survey)
GRID_ORDERS = ("yx", "xy")       # grid cell index = row * divisor + column; "yx": rows along y (Skyrim: verified by
                                 # tes4skyrim on 300 Skyrim.esm navmeshes; Starfield: navmesh_survey.py --exterior)
LINK_PORTAL = 0                  # edge-link type of a seam between navmeshes (0 Portal, 1 Ledge Up, 2 Ledge Down)


# ------------------------------------------------------------------------------------------------------------ reading
def read_skyrim(esm: str, world: str = "Tamriel", cells=None, plugin_name: str = "Skyrim.esm",
                defaults: Optional[Dict] = None):
    """The NAVM records of the worldspace's exterior cells (inside the inclusive rectangle cells = (x0, x1, y0, y1)) as
    Starfield-layout data (skyrimnavmesh.to_starfield; Skyrim units, form keys for navmeshes and doors).
    Returns (navmeshes, bad): navmeshes = [{formkey, skyrim_cell, record_flags, problems, geometry}]."""
    def inside(xy):
        return cells is None or (xy is not None and cells[0] <= xy[0] <= cells[1] and cells[2] <= xy[1] <= cells[3])

    out, bad = [], []
    fk = lambda f: skyrimrefs.formkey(f, plugin_name) if f else None        # noqa: E731
    with fo4land.Plugin(esm) as p:
        _wfid, start, end, _fields = p.find_world(world)

        def walk(s, e, cell):
            for item in fo4land.iter_items(p.buf, s, e):
                if item[0] == "GRUP":
                    _g, off, gend, label, gtype = item
                    if gtype in (4, 5):
                        walk(off + 24, gend, None)
                    elif gtype == 6 and cell is not None and struct.unpack("<I", label)[0] == cell["fid"]:
                        walk(off + 24, gend, cell)
                    elif gtype in (8, 9) and cell is not None and inside(cell["xy"]):
                        children(off + 24, gend, cell)
                    continue
                typ, off, _flags, fid = item
                if typ == b"CELL":
                    xy = None
                    for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                        if sig == b"XCLC" and len(d) >= 8:
                            xy = struct.unpack_from("<ii", d)
                    cell = {"fid": fid, "xy": xy}

        def children(s, e, cell):
            for typ, off, flags, fid in fo4land.iter_items(p.buf, s, e):
                if typ != b"NAVM" or flags & skyrimrefs.DELETED:
                    continue
                fields = skyrimnavmesh.navm_fields(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
                key = fk(fid)
                try:
                    nm = skyrimnavmesh.parse_skyrim(fields["nvnm"] or b"")
                except skyrimnavmesh.NavmeshError as ex:
                    bad.append({"formkey": key, "reason": str(ex)})
                    continue
                sf = skyrimnavmesh.to_starfield(nm, defaults)
                if "world" in nm["parent"]:
                    sf["parent"] = {"world": fk(nm["parent"]["world"]), "grid": list(nm["parent"]["grid"])}
                for l in sf["edge_links"]:
                    l["navmesh"] = fk(l["navmesh"])
                for d in sf["door_links"]:
                    d["door"] = fk(d["door"])
                out.append({"formkey": key, "skyrim_cell": list(cell["xy"]), "record_flags": flags,
                            "problems": skyrimnavmesh.check(nm), "geometry": sf, "skyrim": nm})

        walk(start, end, None)
    return out, bad


# ------------------------------------------------------------------------------------------------------------ frame
def frame_shift(sf: Dict, origin_cw_m=(0.0, 0.0), height_offset_m: float = 0.0) -> Dict:
    """sf with vertices and grid bounds moved into the Starfield frame (still Skyrim units)."""
    dx, dy, dz = -float(origin_cw_m[0]) * UNITS, -float(origin_cw_m[1]) * UNITS, float(height_offset_m) * UNITS
    verts = [(x + dx, y + dy, z + dz) + tuple(v[3:]) for v in sf["vertices"] for x, y, z in [v[:3]]]
    g = dict(sf["grid"])
    b = list(g["bounds"])
    if len(b) == 6:
        g["bounds"] = (b[0] + dx, b[1] + dy, b[2] + dz, b[3] + dx, b[4] + dy, b[5] + dz)
    return dict(sf, vertices=verts, grid=g)


def sf_cell(x_units: float, y_units: float):
    """Starfield exterior cell of a position in Skyrim units (Starfield frame)."""
    return tg.sf_cell_of(x_units / UNITS, y_units / UNITS)


def centroid(verts, tri):
    a, b, c = (verts[i] for i in tri["v"])
    return ((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0, (a[2] + b[2] + c[2]) / 3.0)


# ------------------------------------------------------------------------------------------------------------ grid
def tri_overlaps_rect(xs, ys, x0, y0, x1, y1) -> bool:
    """Does the triangle (plan view) overlap the rectangle? Touching counts. Separating axes: the rectangle's two and
    the triangle's three edge normals."""
    if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
        return False
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    for k in range(3):
        ax, ay = xs[k], ys[k]
        nx, ny = ys[(k + 1) % 3] - ay, ax - xs[(k + 1) % 3]
        inner = nx * (xs[(k + 2) % 3] - ax) + ny * (ys[(k + 2) % 3] - ay)
        if inner == 0:
            continue                                    # degenerate triangle: no axis from this edge
        if all((nx * (px - ax) + ny * (py - ay)) * inner < 0 for px, py in corners):
            return False
    return True


def build_grid(verts, tris, divisor: int, order: str = "yx") -> Dict:
    """The navmesh search grid: the vertices' bounding box split into divisor x divisor cells, each listing (in order)
    every triangle that overlaps it. The game looks only in the grid cell under a point, so a triangle missing from a
    cell it covers is not found there (tes4skyrim, docs/reference/navmesh_engine_contracts.md: Skyrim lists each
    triangle in every cell it truly overlaps; that rule reproduced 91,109 of 91,574 vanilla lists).
    order "yx": index = row (y) * divisor + column (x); "xy" the other."""
    divisor = max(1, int(divisor))
    if not verts:
        return {"divisor": divisor, "size": (0.0, 0.0), "bounds": (0.0,) * 6, "cells": [[] for _ in range(divisor ** 2)]}
    xs, ys, zs = ([v[i] for v in verts] for i in range(3))
    b = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
    sx, sy = (b[3] - b[0]) / divisor, (b[4] - b[1]) / divisor
    cells = [[] for _ in range(divisor * divisor)]

    def span(lo, hi, origin, step):
        if step <= 0:
            return 0, 0
        i0 = min(divisor - 1, max(0, int(math.floor((lo - origin) / step))))
        i1 = min(divisor - 1, max(0, int(math.floor((hi - origin) / step))))
        return i0, i1

    for ti, t in enumerate(tris):
        p = [verts[i] for i in t["v"]]
        txs, tys = [q[0] for q in p], [q[1] for q in p]
        x0, x1 = span(min(txs), max(txs), b[0], sx)
        y0, y1 = span(min(tys), max(tys), b[1], sy)
        for iy in range(y0, y1 + 1):
            for ix in range(x0, x1 + 1):
                if sx > 0 and sy > 0 and not tri_overlaps_rect(txs, tys, b[0] + ix * sx, b[1] + iy * sy,
                                                               b[0] + (ix + 1) * sx, b[1] + (iy + 1) * sy):
                    continue
                cells[iy * divisor + ix if order == "yx" else ix * divisor + iy].append(ti)
    return {"divisor": divisor, "size": (sx, sy), "bounds": b, "cells": cells}


def grid_agreement(sf: Dict, order: str) -> float:
    """How well build_grid reproduces a navmesh's own grid (same divisor): shared (cell, triangle) pairs / all pairs of
    either. 1.0 = identical. The survey picks the order (and checks the membership rule) with this."""
    g = sf["grid"]
    if not g["cells"]:
        return 0.0
    ours = build_grid([v[:3] for v in sf["vertices"]], sf["triangles"], g["divisor"], order)
    a = {(i, t) for i, c in enumerate(g["cells"]) for t in c}
    b = {(i, t) for i, c in enumerate(ours["cells"]) for t in c}
    return len(a & b) / max(1, len(a | b))


def piece_divisor(divisor: int, cell_size, piece_span) -> int:
    """Divisor for a piece of a navmesh: grid cells as large as the source navmesh's (cell_size = its grid's (x, y)
    size), over the piece's (x, y) span; at least 1, at most the source's divisor."""
    want = max((s / c) if c > 0 else 1.0 for s, c in zip(piece_span, cell_size))
    return max(1, min(max(1, int(divisor)), int(round(want))))


# ------------------------------------------------------------------------------------------------------------ split
def split_to_cells(navs: List[Dict], split: bool = True, order: str = "yx", link_type: int = LINK_PORTAL) -> Dict:
    """navs: [{formkey, geometry}] (Starfield frame, Skyrim units). Returns {"navmeshes": [{key, cell, source,
    geometry}], "stats"}: one navmesh per (source navmesh, Starfield cell of its triangles' centres); with split=False
    each navmesh goes whole to the cell of its vertices' bounding-box centre. Edge links are re-pointed at the pieces,
    links to navmeshes not in `navs` are cut (edge opened), an inner edge between two pieces becomes a pair of links
    of `link_type` (Portal, the type of Skyrim's own cell-seam links). Door links follow their triangle."""
    by_key = collections.OrderedDict((n["formkey"], n["geometry"]) for n in navs)
    lt = link_type
    cell_of = {}
    for k, g in by_key.items():
        V = g["vertices"]
        if split:
            cell_of[k] = [sf_cell(*centroid(V, t)[:2]) for t in g["triangles"]]
        else:
            xs, ys = [v[0] for v in V] or [0.0], [v[1] for v in V] or [0.0]
            c = sf_cell((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
            cell_of[k] = [c] * len(g["triangles"])
    groups, new_index = collections.OrderedDict(), {}
    for k, cells in cell_of.items():
        cs = sorted(set(cells))
        for c in cs:
            pk = k if len(cs) == 1 else f"{k}@{c[0]},{c[1]}"
            groups[pk] = (k, c, len(cs) == 1, [])
        for t, c in enumerate(cells):
            pk = k if len(cs) == 1 else f"{k}@{c[0]},{c[1]}"
            new_index[(k, t)] = (pk, len(groups[pk][3]))
            groups[pk][3].append(t)
    stats = {"source_navmeshes": len(by_key), "navmeshes": len(groups), "split": sum(len(set(c)) > 1 for c in
             cell_of.values()), "links_kept": 0, "links_cut": 0, "links_added": 0, "doors": 0,
             "link_type_new": lt, "cells": len({g[1] for g in groups.values()})}
    out = []
    for pk, (k, c, whole, tlist) in groups.items():
        g = by_key[k]
        if whole:
            vmap = {i: i for i in range(len(g["vertices"]))}
            verts = list(g["vertices"])
        else:
            vmap, verts = {}, []
            for t in tlist:
                for v in g["triangles"][t]["v"]:
                    if v not in vmap:
                        vmap[v] = len(verts)
                        verts.append(g["vertices"][v])
        links, tris = [], []
        for t in tlist:
            tri = g["triangles"][t]
            e, flags = list(tri["e"]), tri["flags"]
            for kk in range(3):
                bit = skyrimnavmesh.EDGE_LINK_FLAGS[kk]
                ek = e[kk]
                if ek == 0xFFFF:
                    flags &= ~bit
                    continue
                if flags & bit:
                    l = g["edge_links"][ek] if 0 <= ek < len(g["edge_links"]) else None
                    tgt = new_index.get((l["navmesh"], l["triangle"])) if l else None
                    if tgt is None:
                        e[kk], flags = 0xFFFF, flags & ~bit
                        stats["links_cut"] += 1
                        continue
                    e[kk] = len(links)
                    links.append({"type": l["type"], "navmesh": tgt[0], "triangle": tgt[1], "edge": kk})
                    stats["links_kept"] += 1
                    continue
                tgt = new_index.get((k, ek))
                if tgt is None:                             # neighbour out of range (bad source): open edge
                    e[kk] = 0xFFFF
                elif tgt[0] == pk:
                    e[kk] = tgt[1]
                else:
                    e[kk] = len(links)
                    links.append({"type": lt, "navmesh": tgt[0], "triangle": tgt[1], "edge": kk})
                    flags |= bit
                    stats["links_added"] += 1
            tris.append(dict(tri, v=tuple(vmap[v] for v in tri["v"]), e=tuple(e), flags=flags))
        doors = []
        for d in g["door_links"]:
            tgt = new_index.get((k, d["triangle"]))
            if tgt is not None and tgt[0] == pk:
                doors.append(dict(d, triangle=tgt[1]))
        stats["doors"] += len(doors)
        if whole:
            grid = g["grid"]
        else:
            span = (max(v[0] for v in verts) - min(v[0] for v in verts), max(v[1] for v in verts) - min(v[1] for v in verts))
            grid = build_grid(verts, tris, piece_divisor(g["grid"]["divisor"], g["grid"]["size"], span), order)
        geo = dict(g, vertices=verts, triangles=tris, edge_links=links, door_links=doors, grid=grid)
        out.append({"key": pk, "cell": [c[0], c[1]], "source": k, "geometry": geo})
    return {"navmeshes": out, "stats": stats}


# ------------------------------------------------------------------------------------------------------------ checks
def _seg_dist(p, a, b):
    """Distance from point p to the segment ab (3-D)."""
    d = [b[i] - a[i] for i in range(3)]
    dd = sum(x * x for x in d)
    t = 0.0 if dd == 0 else max(0.0, min(1.0, sum((p[i] - a[i]) * d[i] for i in range(3)) / dd))
    return math.dist(p[:3], [a[i] + t * d[i] for i in range(3)])


def edge_link_problems(navs: Dict[str, Dict], tol: float = 1.0) -> Dict:
    """Do the edge links join triangles that really touch along that edge? navs = {key: geometry} (any units; tol in the
    same units). For each link, the leaving edge AB against the target triangle's three edges CD: "shared" when A and
    B are both target vertices (within tol); otherwise the gap = the smallest, over CD, of the distance from AB's
    middle to CD or from CD's middle to AB (0 for edges on one line that overlap, as at a T-junction across a seam).
    A gap over tol is a mismatch. Links between pieces of one source navmesh (keys "<source>@x,y") count as "seam",
    the rest as "between". Returns counts, the gap distribution of the non-shared links, and examples."""
    out = {"links": 0, "outside": 0, "bad_index": 0, "shared": 0, "mismatch": 0,
           "by_kind": {"seam": {"links": 0, "mismatch": 0}, "between": {"links": 0, "mismatch": 0}},
           "gaps": [], "examples": []}
    src = lambda k: str(k).split("@")[0]                                   # noqa: E731
    gaps = []
    for key, g in navs.items():
        V = g["vertices"]
        for ti, t in enumerate(g["triangles"]):
            for kk in range(3):
                if not t["flags"] & skyrimnavmesh.EDGE_LINK_FLAGS[kk] or t["e"][kk] == 0xFFFF:
                    continue
                out["links"] += 1
                l = g["edge_links"][t["e"][kk]] if t["e"][kk] < len(g["edge_links"]) else None
                h = navs.get(l["navmesh"]) if l else None
                if l is None:
                    out["bad_index"] += 1
                    continue
                if h is None:
                    out["outside"] += 1
                    continue
                if not 0 <= l["triangle"] < len(h["triangles"]):
                    out["bad_index"] += 1
                    continue
                kind = "seam" if src(l["navmesh"]) == src(key) and l["navmesh"] != key else "between"
                out["by_kind"][kind]["links"] += 1
                a, b = V[t["v"][kk]], V[t["v"][(kk + 1) % 3]]
                other = [h["vertices"][i] for i in h["triangles"][l["triangle"]]["v"]]
                near = lambda p: min(math.dist(p[:3], q[:3]) for q in other)      # noqa: E731
                if near(a) <= tol and near(b) <= tol:
                    out["shared"] += 1
                    continue
                mab = [(a[i] + b[i]) / 2 for i in range(3)]
                gap = math.inf
                for j in range(3):
                    c, d = other[j], other[(j + 1) % 3]
                    mcd = [(c[i] + d[i]) / 2 for i in range(3)]
                    gap = min(gap, _seg_dist(mab, c, d), _seg_dist(mcd, a, b))
                gaps.append(gap)
                if gap > tol:
                    out["mismatch"] += 1
                    out["by_kind"][kind]["mismatch"] += 1
                    if len(out["examples"]) < 10:
                        out["examples"].append({"navmesh": key, "triangle": ti, "edge": kk, "to": l["navmesh"],
                                                "to_triangle": l["triangle"], "gap": round(gap, 3)})
    gaps.sort()
    q = lambda f: round(gaps[min(len(gaps) - 1, int(f * (len(gaps) - 1)))], 3) if gaps else None   # noqa: E731
    out["gaps"] = {"n": len(gaps), "median": q(0.5), "p95": q(0.95), "max": q(1.0)}
    return out


def outside_cell(g: Dict, cell, cell_size: float = tg.SF_CELL_M * UNITS) -> float:
    """Fraction of the triangles whose centre lies outside the 100 m Starfield cell `cell` (units as the vertices)."""
    if not g["triangles"]:
        return 0.0
    n = 0
    for t in g["triangles"]:
        x, y, _ = centroid(g["vertices"], t)
        if (int(math.floor(x / cell_size)), int(math.floor(y / cell_size))) != tuple(cell):
            n += 1
    return n / len(g["triangles"])


def nearest_offsets(src_pts, dst_pts, cell: float = 200.0):
    """Distance from each source point to the nearest destination point (a hash grid; units as given)."""
    grid = collections.defaultdict(list)
    for p in dst_pts:
        grid[(int(p[0] // cell), int(p[1] // cell))].append(p)
    out = []
    for p in src_pts:
        cx, cy = int(p[0] // cell), int(p[1] // cell)
        best = math.inf
        for ix in (cx - 1, cx, cx + 1):
            for iy in (cy - 1, cy, cy + 1):
                for q in grid.get((ix, iy), ()):
                    best = min(best, math.dist(p[:3], q[:3]))
        out.append(best)
    return out


def read_starfield_exterior(esm: str, limit: Optional[int] = None):
    """Yield {world, cell, cell_xy, navmesh, flags, nm} for the NAVM records in exterior cells of a Starfield plugin
    (vanilla Starfield.esm for the survey, our FO4Port.esm for the compare). FormIDs are raw (master index byte
    included); nm = skyrimnavmesh.parse_starfield or {"error": ...}."""
    n = 0
    with fo4land.Plugin(esm) as p:
        top = next((it for it in fo4land.iter_items(p.buf, p.body, len(p.buf))
                    if it[0] == "GRUP" and it[3] == b"WRLD"), None)
        if top is None:
            return
        stack = [(top[1] + 24, top[2], None, None)]
        while stack:
            start, end, world, cell = stack.pop()
            last_world, last_cell = world, cell
            for it in fo4land.iter_items(p.buf, start, end):
                if it[0] == "GRUP":
                    _g, off, gend, label, gtype = it
                    lab = struct.unpack("<I", label)[0]
                    if gtype == 1:
                        stack.append((off + 24, gend, lab, None))
                    elif gtype == 6:
                        c = last_cell if last_cell and last_cell["fid"] == lab else {"fid": lab, "xy": None}
                        stack.append((off + 24, gend, last_world, c))
                    else:
                        stack.append((off + 24, gend, last_world, cell))
                    continue
                typ, off, flags, fid = it
                if typ == b"WRLD":
                    last_world = fid
                elif typ == b"CELL":
                    xy = None
                    for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                        if sig == b"XCLC" and len(d) >= 8:
                            xy = struct.unpack_from("<ii", d)
                    last_cell = {"fid": fid, "xy": xy}
                elif typ == b"NAVM" and cell is not None:
                    data = next((bytes(d) for s, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off))
                                 if s == b"NVNM"), b"")
                    try:
                        nm = skyrimnavmesh.parse_starfield(data)
                    except skyrimnavmesh.NavmeshError as ex:
                        nm = {"error": str(ex)}
                    yield {"world": world, "cell": cell["fid"], "cell_xy": cell["xy"], "navmesh": fid,
                           "flags": flags, "nm": nm}
                    n += 1
                    if limit is not None and n >= limit:
                        return


# ------------------------------------------------------------------------------------------------------------ NAVI
def parse_nvmi(d: bytes) -> Dict:
    """One Starfield NVMI (navmesh info, in the NAVI record; xEdit wbDefinitionsSF1): navmesh, flags, approx location,
    preferred %, edge-link navmeshes, preferred edge links, door links, traversals, optional island data, pathing cell
    (world + grid Y, X, or 0 + cell), then one unknown byte and a u32-counted array ("tail")."""
    r = skyrimnavmesh._R(bytes(d))
    nav, flags = r.take("II")
    loc = r.take("3f")
    pref, = r.take("f")
    edges = [r.take("I")[0] for _ in range(r.count())]
    preferred = [r.take("I")[0] for _ in range(r.count())]
    doors = [r.take("II") for _ in range(r.count())]
    trav = [r.take("III3f3f3fIII") for _ in range(r.count())]
    island, = r.take("B")
    if island:
        r.take("6f")
        for _ in range(r.count()):
            r.take("3H")
        for _ in range(r.count()):
            r.take("3f")
    crc, world = r.take("II")
    if world:
        gy, gx = r.take("hh")
        parent = {"world": world, "grid": (gx, gy)}
    else:
        parent = {"cell": r.take("I")[0]}
    tail = bytes(r.d[r.p:])
    return {"navmesh": nav, "flags": flags, "location": loc, "preferred_pct": pref, "edge_links": edges,
            "preferred_edge_links": preferred, "door_links": doors, "traversals": len(trav), "island": bool(island),
            "crc": crc, "parent": parent, "tail": tail.hex()}


def iter_records(esm: str, types):
    """Yield (type, form id, record flags, subrecords list) for every record of the given types, anywhere in the file
    (top-level groups and nested world / cell children)."""
    types = set(types)
    with fo4land.Plugin(esm) as p:
        stack = [(p.body, len(p.buf))]
        while stack:
            start, end = stack.pop()
            for it in fo4land.iter_items(p.buf, start, end):
                if it[0] == "GRUP":
                    stack.append((it[1] + 24, it[2]))
                    continue
                typ, off, flags, fid = it
                if typ in types:
                    yield typ, fid, flags, [(sig, bytes(d)) for sig, d in
                                            fo4land.iter_subrecords(fo4land.record_data(p.buf, off))]


def read_navi(esm: str) -> List[Dict]:
    """The NAVI records of a Starfield plugin: [{form, version, infos: [parse_nvmi or {"error"}], has_nvpp}]."""
    out = []
    for _typ, fid, _flags, subs in iter_records(esm, (b"NAVI",)):
        rec = {"form": fid, "version": None, "infos": [], "has_nvpp": False}
        for sig, d in subs:
            if sig == b"NVER" and len(d) >= 4:
                rec["version"] = struct.unpack_from("<I", d)[0]
            elif sig == b"NVMI":
                try:
                    rec["infos"].append(parse_nvmi(d))
                except skyrimnavmesh.NavmeshError as ex:
                    rec["infos"].append({"error": str(ex)})
            elif sig == b"NVPP":
                rec["has_nvpp"] = True
        out.append(rec)
    return out
