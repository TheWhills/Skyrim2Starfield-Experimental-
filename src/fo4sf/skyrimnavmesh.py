"""Skyrim navmeshes (NAVM, NVNM version 12) -> Starfield navmesh geometry (NVNM version 17).

NPCs only move on navmesh, so converted cells need one for AI packages (sandbox, sleep, travel) to work. Skyrim's
navmeshes are hand-made per cell and record which triangles lead through which doors; the format changed little between
the games (xEdit wbDefinitionsTES5 / wbDefinitionsSF1, Mutagen's Starfield NavmeshGeometry; read for the format only):

    both:    u32 version; pathing cell (u32 CRC 'PathingCell' 0xA5E9A03C, u32 parent world, then either s16 grid Y +
             s16 grid X (exterior) or u32 parent cell); u32-counted arrays; door links (s16 triangle, u32 CRC
             'PathingDoor' 0xE48B73F3, u32 door reference); navmesh grid (u32 divisor, f32 x2 cell size, f32 x6 bounds,
             divisor^2 cells of u32-counted s16 triangle lists)
    Skyrim:  vertex = 3 f32; triangle = 3 u16 vertices, 3 s16 edges, u16 flags, u16 cover flags (16 bytes);
             edge link = u32 type, u32 navmesh, s16 triangle (10); cover triangles = s16 list
    Starfield: vertex = 3 f32 + u32 unknown (16); triangle = 3 u16 vertices, 3 u16 edges, f32 height, u8 unknown,
             u16 flags, u16 cover flags (21); edge link = u32 type, u32 navmesh, s16 triangle, u8 edge index (11);
             cover = u16 v1, u16 v2, u64 data (12); cover-triangle map = u16, u16; waypoints = 3 f32, u16 triangle,
             u32 flags (18); after the grid u16 + u16 unknown

Triangle flags are the same bits in both (Mutagen: 0x1 / 0x2 / 0x4 the edge is an edge link, 0x10 no large creatures,
0x20 overlapping, 0x40 preferred, 0x200 water, 0x400 door, 0x800 found). An edge whose flag bit is set holds an index
into the edge links instead of a neighbouring triangle; Starfield's links also say which edge they leave by.
Translation: geometry, edges, flags, edge and door links and the grid carry over; cover (Skyrim keeps a list of
cover triangles, Starfield cover edges with data) and waypoints start empty; the unknown fields get defaults that a
survey of vanilla Starfield navmeshes replaces (`defaults`). Units stay Skyrim units here: the plugin writer scales
positions to metres (/ 70) as it does for references.
"""
import struct
from typing import Dict, List, Optional

PATHING_CELL = 0xA5E9A03C
PATHING_DOOR = 0xE48B73F3
EDGE_LINK_FLAGS = (0x1, 0x2, 0x4)            # edge 0-1, 1-2, 2-0 holds an edge-link index
DEFAULTS = {"vertex_unknown": 0, "triangle_height": 0.0, "triangle_unknown": 0, "tail": (0, 0)}


class NavmeshError(ValueError):
    pass


class _R:
    def __init__(self, d: bytes):
        self.d, self.p = d, 0

    def take(self, fmt: str):
        try:
            v = struct.unpack_from("<" + fmt, self.d, self.p)
        except struct.error:
            raise NavmeshError(f"navmesh data ends at byte {self.p} (reading {fmt})") from None
        self.p += struct.calcsize("<" + fmt)
        return v

    def count(self) -> int:
        n, = self.take("I")
        if n > 1_000_000:
            raise NavmeshError(f"implausible count {n} at byte {self.p - 4}")
        return n


def parse_skyrim(data: bytes) -> Dict:
    """NVNM version 12 -> dict (units: Skyrim game units)."""
    r = _R(bytes(data))
    version, = r.take("I")
    if version != 12:
        raise NavmeshError(f"navmesh version {version}, expected Skyrim's 12")
    crc, world = r.take("II")
    if world:
        gy, gx = r.take("hh")
        parent = {"world": world, "grid": (gx, gy)}
    else:
        cell, = r.take("I")
        parent = {"cell": cell}
    verts = [r.take("3f") for _ in range(r.count())]
    tris = []
    for _ in range(r.count()):
        v0, v1, v2, e0, e1, e2, flags, cover = r.take("3H3hHH")
        tris.append({"v": (v0, v1, v2), "e": (e0, e1, e2), "flags": flags, "cover": cover})
    links = []
    for _ in range(r.count()):
        typ, nav, tri = r.take("IIh")
        links.append({"type": typ, "navmesh": nav, "triangle": tri})
    doors = []
    for _ in range(r.count()):
        tri, dcrc, door = r.take("hII")
        doors.append({"triangle": tri, "crc": dcrc, "door": door})
    cover_tris = [r.take("h")[0] for _ in range(r.count())]
    divisor, = r.take("I")
    size = r.take("2f")
    bounds = r.take("6f")
    cells = []
    if 0 <= divisor <= 12:
        for _ in range(divisor * divisor):
            cells.append([r.take("h")[0] for _ in range(r.count())])
    return {"version": version, "crc": crc, "parent": parent, "vertices": verts, "triangles": tris,
            "edge_links": links, "door_links": doors, "cover_triangles": cover_tris,
            "grid": {"divisor": divisor, "size": size, "bounds": bounds, "cells": cells},
            "trailing_bytes": len(r.d) - r.p}


def check(nm: Dict) -> List[str]:
    """Consistency problems (indices out of range); [] when the navmesh is sound."""
    out = []
    nv, nt, nl = len(nm["vertices"]), len(nm["triangles"]), len(nm["edge_links"])
    for i, t in enumerate(nm["triangles"]):
        if any(not 0 <= v < nv for v in t["v"]):
            out.append(f"triangle {i}: vertex out of range")
        for k, e in enumerate(t["e"]):
            if e == -1 or e == 0xFFFF:
                continue
            limit = nl if t["flags"] & EDGE_LINK_FLAGS[k] else nt
            if not 0 <= e < limit:
                out.append(f"triangle {i}: edge {k} -> {e} out of range ({'link' if limit == nl else 'triangle'})")
    for i, d in enumerate(nm["door_links"]):
        if not 0 <= d["triangle"] < nt:
            out.append(f"door link {i}: triangle {d['triangle']} out of range")
    return out


def to_starfield(nm: Dict, defaults: Optional[Dict] = None) -> Dict:
    """The Skyrim navmesh as Starfield v17 data (still in Skyrim units and Skyrim FormIDs; the writer maps both).
    Each edge link gets the edge it leaves by (from the triangle whose flagged edge points at it)."""
    d = dict(DEFAULTS, **(defaults or {}))
    edge_of = {}
    for t in nm["triangles"]:
        for k, e in enumerate(t["e"]):
            if t["flags"] & EDGE_LINK_FLAGS[k] and e >= 0:
                edge_of.setdefault(e, k)
    tris = [{"v": t["v"], "e": tuple(e & 0xFFFF for e in t["e"]), "height": d["triangle_height"],
             "unknown": d["triangle_unknown"], "flags": t["flags"], "cover": t["cover"]} for t in nm["triangles"]]
    links = [dict(l, edge=edge_of.get(i, 0)) for i, l in enumerate(nm["edge_links"])]
    return {"version": 17, "crc": PATHING_CELL, "parent": nm["parent"],
            "vertices": [(x, y, z, d["vertex_unknown"]) for x, y, z in nm["vertices"]], "triangles": tris,
            "edge_links": links, "door_links": [dict(x, crc=PATHING_DOOR) for x in nm["door_links"]],
            "cover": [], "cover_map": [], "waypoints": [], "grid": nm["grid"], "tail": tuple(d["tail"]),
            "dropped": {"cover_triangles": len(nm["cover_triangles"])}}


def cut_links(sf: Dict, keep) -> Dict:
    """sf with only the edge links whose target navmesh is in `keep` (a set of ids as stored in the links): a cut link's
    triangle edge becomes open (0xFFFF, edge-link flag cleared) and the remaining links are renumbered. Adds
    dropped["edge_links"]."""
    new_index, links = {}, []
    for i, l in enumerate(sf["edge_links"]):
        if l["navmesh"] in keep:
            new_index[i] = len(links)
            links.append(l)
    tris = []
    for t in sf["triangles"]:
        e, flags = list(t["e"]), t["flags"]
        for k in range(3):
            if flags & EDGE_LINK_FLAGS[k] and e[k] != 0xFFFF:
                if e[k] in new_index:
                    e[k] = new_index[e[k]]
                else:
                    e[k] = 0xFFFF
                    flags &= ~EDGE_LINK_FLAGS[k]
        tris.append(dict(t, e=tuple(e), flags=flags))
    dropped = dict(sf.get("dropped", {}), edge_links=len(sf["edge_links"]) - len(links))
    return dict(sf, triangles=tris, edge_links=links, dropped=dropped)


def serialize_starfield(sf: Dict, scale: float = 1.0, form_map=None) -> bytes:
    """NVNM v17 bytes. scale multiplies positions, grid size and bounds (1 / 70 for metres); form_map(old) -> new
    FormID for the parent cell / world, linked navmeshes and doors (identity when None)."""
    fm = form_map or (lambda x: x)
    out = [struct.pack("<II", sf["version"], sf["crc"])]
    par = sf["parent"]
    if "world" in par:
        gx, gy = par["grid"]
        out.append(struct.pack("<Ihh", fm(par["world"]), gy, gx))
    else:
        out.append(struct.pack("<II", 0, fm(par["cell"])))
    out.append(struct.pack("<I", len(sf["vertices"])))
    out += [struct.pack("<3fI", x * scale, y * scale, z * scale, u) for x, y, z, u in sf["vertices"]]
    out.append(struct.pack("<I", len(sf["triangles"])))
    for t in sf["triangles"]:
        out.append(struct.pack("<3H3HfBHH", *t["v"], *t["e"], t["height"], t["unknown"], t["flags"], t["cover"]))
    out.append(struct.pack("<I", len(sf["edge_links"])))
    out += [struct.pack("<IIhB", l["type"], fm(l["navmesh"]), l["triangle"], l["edge"]) for l in sf["edge_links"]]
    out.append(struct.pack("<I", len(sf["door_links"])))
    out += [struct.pack("<hII", x["triangle"], x["crc"], fm(x["door"])) for x in sf["door_links"]]
    out.append(struct.pack("<I", len(sf["cover"])))
    out += [struct.pack("<HHQ", *c) for c in sf["cover"]]
    out.append(struct.pack("<I", len(sf["cover_map"])))
    out += [struct.pack("<HH", *c) for c in sf["cover_map"]]
    out.append(struct.pack("<I", len(sf["waypoints"])))
    out += [struct.pack("<3fHI", w[0] * scale, w[1] * scale, w[2] * scale, w[3], w[4]) for w in sf["waypoints"]]
    g = sf["grid"]
    out.append(struct.pack("<I2f6f", g["divisor"], *(s * scale for s in g["size"]), *(b * scale for b in g["bounds"])))
    for c in g["cells"]:
        out.append(struct.pack("<I", len(c)) + struct.pack(f"<{len(c)}h", *c))
    out.append(struct.pack("<HH", *sf["tail"]))
    return b"".join(out)


def parse_starfield(data: bytes) -> Dict:
    """NVNM v17 -> dict (for checks and for surveying vanilla Starfield navmeshes)."""
    r = _R(bytes(data))
    version, crc, world = r.take("III")
    if world:
        gy, gx = r.take("hh")
        parent = {"world": world, "grid": (gx, gy)}
    else:
        parent = {"cell": r.take("I")[0]}
    verts = [r.take("3fI") for _ in range(r.count())]
    tris = []
    for _ in range(r.count()):
        v0, v1, v2, e0, e1, e2, h, unk, flags, cover = r.take("3H3HfBHH")
        tris.append({"v": (v0, v1, v2), "e": (e0, e1, e2), "height": h, "unknown": unk, "flags": flags,
                     "cover": cover})
    links = []
    for _ in range(r.count()):
        typ, nav, tri, edge = r.take("IIhB")
        links.append({"type": typ, "navmesh": nav, "triangle": tri, "edge": edge})
    doors = []
    for _ in range(r.count()):
        tri, dcrc, door = r.take("hII")
        doors.append({"triangle": tri, "crc": dcrc, "door": door})
    cover = [r.take("HHQ") for _ in range(r.count())]
    cover_map = [r.take("HH") for _ in range(r.count())]
    waypoints = [r.take("3fHI") for _ in range(r.count())]
    divisor, = r.take("I")
    size = r.take("2f")
    bounds = r.take("6f")
    cells = []
    if 0 <= divisor <= 12:
        for _ in range(divisor * divisor):
            cells.append([r.take("h")[0] for _ in range(r.count())])
    tail = r.take("HH") if len(r.d) - r.p >= 4 else (None, None)
    return {"version": version, "crc": crc, "parent": parent, "vertices": verts, "triangles": tris,
            "edge_links": links, "door_links": doors, "cover": cover, "cover_map": cover_map, "waypoints": waypoints,
            "grid": {"divisor": divisor, "size": size, "bounds": bounds, "cells": cells}, "tail": tail,
            "trailing_bytes": len(r.d) - r.p}


def navm_fields(subs) -> Dict:
    """EDID / NVNM / ONAM / PNAM / NNAM of a NAVM record's subrecords (Skyrim)."""
    out = {"edid": "", "nvnm": None, "base_objects": [], "preferred": [], "non_connectors": []}
    for sig, d in subs:
        d = bytes(d)
        if sig == b"EDID":
            out["edid"] = d.rstrip(b"\0").decode("latin-1")
        elif sig == b"NVNM":
            out["nvnm"] = d
        elif sig == b"ONAM":
            out["base_objects"] = list(struct.unpack(f"<{len(d) // 4}I", d[:len(d) // 4 * 4]))
        elif sig == b"PNAM":
            out["preferred"] = list(struct.unpack(f"<{len(d) // 2}H", d[:len(d) // 2 * 2]))
        elif sig == b"NNAM":
            out["non_connectors"] = list(struct.unpack(f"<{len(d) // 2}H", d[:len(d) // 2 * 2]))
    return out
