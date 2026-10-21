"""Skyrim interior cells (houses, inns, caves, barrows, ruins) -> the schema-v2 placement export, plus what the upstream
plugin writer (dotnet/PluginSpike) needs to build one Starfield interior cell from it. Read-only.

Skyrim.esm layout (same record walker as skyrimrefs): top group CELL -> interior cell blocks (group type 2) ->
sub-blocks (3) -> CELL record (interior: DATA flag 0x1) followed by its children group (6, label = cell FormID) ->
persistent (8) and temporary (9) children holding REFR / ACHR / placed hazards. References as in skyrimrefs.

Arrival: `coc <cell>` in Starfield needs a COCMarkerHeading reference in the cell (PluginSpike places Starfield's own
marker wherever the export has a ref whose base EditorID is COCMarkerHeading). Order of preference:
1. the cell's own COCMarkerHeading reference (Skyrim's coc target);
2. else where a load door elsewhere sends the player INTO this cell: the XTEL (teleport destination: door FormID,
   position 3f, rotation 3f, no-alarm u32; xEdit wbDefinitionsTES5) of a persistent reference whose destination door is
   one of this cell's references;
3. else the cell's own door references' positions (flagged: may face a wall).
"""
import re
import struct

from fo4sf import fo4land, skyrimrefs

INTERIOR = 0x1                     # CELL DATA flag
COC_MARKER = "COCMarkerHeading"
MIN_REF_RADIUS = 64.0             # units (~0.9 m): smaller XRDS values on light references are ignored
LIGHT_FLICKER, LIGHT_PULSE, LIGHT_OFF_BY_DEFAULT = 0x8, 0x80, 0x20      # LIGH DATA flags (xEdit wbDefinitionsTES5)


def _rgb(d, off):
    return list(d[off:off + 3])


def read_lights(p) -> dict:
    """{LIGH form id: light data} from the LIGH top group. DATA (SSE, 48 bytes; xEdit wbDefinitionsTES5): time i32,
    radius u32 (units), colour RGBx, flags u32, falloff exponent, FOV, near clip, flicker period, flicker intensity
    amplitude, flicker movement amplitude (f32), value u32, weight f32. FNAM: fade (brightness multiplier)."""
    rng = p.top_group(b"LIGH")
    out = {}
    if rng is None:
        return out
    for typ, off, flags, fid in fo4land.iter_items(p.buf, *rng):
        if typ == "GRUP" or flags & skyrimrefs.DELETED:
            continue
        light = {"radius": 0.0, "color": [255, 255, 255], "flags": 0, "fade": 1.0}
        for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
            if sig == b"DATA" and len(d) >= 40:
                _t, radius = struct.unpack_from("<iI", d, 0)
                fl, fexp, fov, near, period, amp, move = struct.unpack_from("<I6f", d, 12)
                light.update(radius=float(radius), color=_rgb(d, 8), flags=fl, falloff_exponent=round(fexp, 4),
                             fov=round(fov, 2), flicker=bool(fl & (LIGHT_FLICKER | LIGHT_PULSE)),
                             flicker_period=round(period, 4), flicker_intensity=round(amp, 4),
                             flicker_movement=round(move, 4), off_by_default=bool(fl & LIGHT_OFF_BY_DEFAULT))
            elif sig == b"FNAM" and len(d) >= 4:
                light["fade"] = round(struct.unpack_from("<f", d)[0], 4)
        out[fid] = light
    return out


def cell_lighting(fields, plugin_name="Skyrim.esm"):
    """The Skyrim cell's own lighting: XCLL (ambient, directional, fog near colours, fog near / far, ..., directional
    ambient x6, specular, fresnel, fog far colour, fog max, light fade begin / end, inherit flags), LTMP lighting
    template, XCIM image space. None when the cell has none of them."""
    out = {}
    for sig, d in fields:
        if sig == b"XCLL" and len(d) >= 12:
            out.update(ambient=_rgb(d, 0), directional=_rgb(d, 4), fog_near_color=_rgb(d, 8))
            if len(d) >= 92:
                out.update(fog_far_color=_rgb(d, 72), light_fade_begin=round(struct.unpack_from("<f", d, 80)[0], 1),
                           light_fade_end=round(struct.unpack_from("<f", d, 84)[0], 1),
                           inherits=struct.unpack_from("<I", d, 88)[0])
        elif sig == b"LTMP" and len(d) >= 4 and struct.unpack_from("<I", d)[0]:
            out["template"] = skyrimrefs.formkey(struct.unpack_from("<I", d)[0], plugin_name)
        elif sig == b"XCIM" and len(d) >= 4 and struct.unpack_from("<I", d)[0]:
            out["image_space"] = skyrimrefs.formkey(struct.unpack_from("<I", d)[0], plugin_name)
    return out or None


def _xrds(data):
    for sig, d in fo4land.iter_subrecords(data):
        if sig == b"XRDS" and len(d) >= 4:
            return struct.unpack_from("<f", d)[0]
    return None


def _cells(p):
    """Yield (cell fid, cell fields, children group (start, end) or None) for every CELL in the CELL top group."""
    rng = p.top_group(b"CELL")
    if rng is None:
        return
    for blk in fo4land.iter_items(p.buf, *rng):
        if blk[0] != "GRUP" or blk[4] != 2:
            continue
        for sub in fo4land.iter_items(p.buf, blk[1] + 24, blk[2]):
            if sub[0] != "GRUP" or sub[4] != 3:
                continue
            pending = None                                   # a CELL waiting for its children group
            for item in fo4land.iter_items(p.buf, sub[1] + 24, sub[2]):
                if item[0] == "GRUP":
                    if item[4] == 6 and pending and struct.unpack("<I", item[3])[0] == pending[0]:
                        yield pending[0], pending[1], (item[1] + 24, item[2])
                        pending = None
                    continue
                if pending:
                    yield pending[0], pending[1], None
                typ, off, flags, fid = item
                pending = ((fid, list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off))))
                           if typ == b"CELL" and not flags & skyrimrefs.DELETED else None)
            if pending:
                yield pending[0], pending[1], None


def _is_interior(fields):
    for sig, d in fields:
        if sig == b"DATA" and len(d) >= 1:
            return bool(d[0] & INTERIOR)
    return False


def _edid(fields):
    for sig, d in fields:
        if sig == b"EDID":
            return fo4land.zstring(d)
    return ""


def _children(p, rng):
    """Yield (type, record flags, fid, persistent group?, fields) for the placed records under a cell children group."""
    for item in fo4land.iter_items(p.buf, *rng):
        if item[0] != "GRUP":
            continue
        _g, off, gend, _label, gtype = item
        if gtype not in (8, 9):
            continue
        for typ, roff, flags, fid in fo4land.iter_items(p.buf, off + 24, gend):
            if typ == "GRUP" or typ not in skyrimrefs.PLACED:
                continue
            yield typ, flags, fid, gtype == 8, fo4land.record_data(p.buf, roff)


def _navmeshes(p, rng, plugin_name="Skyrim.esm", defaults=None):
    """The cell's navmeshes (NAVM records in its children groups) as Starfield-ready data (skyrimnavmesh.to_starfield,
    Skyrim units) with FormIDs as form keys: parent cell, linked navmeshes and doors stay Skyrim's for the writer to
    map. Navmeshes that do not read are reported, not raised."""
    from . import skyrimnavmesh
    out, bad = [], []
    for item in fo4land.iter_items(p.buf, *rng):
        if item[0] != "GRUP" or item[4] not in (8, 9):
            continue
        for typ, roff, flags, fid in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
            if typ != b"NAVM" or flags & skyrimrefs.DELETED:
                continue
            fields = skyrimnavmesh.navm_fields(fo4land.iter_subrecords(fo4land.record_data(p.buf, roff)))
            key = skyrimrefs.formkey(fid, plugin_name)
            try:
                nm = skyrimnavmesh.parse_skyrim(fields["nvnm"] or b"")
            except skyrimnavmesh.NavmeshError as e:
                bad.append({"formkey": key, "reason": str(e)})
                continue
            sf = skyrimnavmesh.to_starfield(nm, defaults)
            fk = lambda f: skyrimrefs.formkey(f, plugin_name) if f else None     # noqa: E731
            sf["parent"] = {"cell": fk(nm["parent"]["cell"])} if "cell" in nm["parent"] else \
                {"world": fk(nm["parent"]["world"]), "grid": list(nm["parent"]["grid"])}
            for l in sf["edge_links"]:
                l["navmesh"] = fk(l["navmesh"])
            for d in sf["door_links"]:
                d["door"] = fk(d["door"])
            out.append({"formkey": key, "record_flags": flags, "problems": skyrimnavmesh.check(nm),
                        "geometry": sf})
    return out, bad


def list_interiors(esm: str) -> list:
    """[{edid, form_id, refs, lights, doors, actors, coc}] of every interior cell, sorted by EditorID."""
    out = []
    with fo4land.Plugin(esm) as p:
        bases = skyrimrefs.read_bases(p, ("STAT", "LIGH", "DOOR"))
        for fid, fields, rng in _cells(p):
            if not _is_interior(fields):
                continue
            c = {"edid": _edid(fields), "form_id": "%08X" % fid, "refs": 0, "lights": 0, "doors": 0, "actors": 0,
                 "coc": False}
            for typ, flags, _rf, _pers, data in (_children(p, rng) if rng else ()):
                if flags & skyrimrefs.DELETED:
                    continue
                if typ == b"ACHR":
                    c["actors"] += 1
                    continue
                c["refs"] += 1
                base = skyrimrefs._parse_ref(data)["base"]
                btype, bedid, _m = bases.get(base, (None, "", ""))
                c["lights"] += btype == "Light"
                c["doors"] += btype == "Door"
                c["coc"] |= bedid == COC_MARKER
            out.append(c)
    return sorted(out, key=lambda c: c["edid"].lower())


def _xtel(data):
    """(destination door fid, position, rotation, flags) of a reference's XTEL, or None. Skyrim and Starfield share
    the layout (door, pos 3f, rot 3f, flags u32: no alarm / no load screen / relative position; xEdit)."""
    for sig, d in fo4land.iter_subrecords(data):
        if sig == b"XTEL" and len(d) >= 28:
            door, *pr = struct.unpack_from("<I6f", d)
            flags = struct.unpack_from("<I", d, 28)[0] if len(d) >= 32 else 0
            return door, list(pr[:3]), list(pr[3:]), flags
    return None


class Source:
    """One open Skyrim plugin, read once for any number of interior cells: bases, lights, the interior cells by
    EditorID and (on first use) an index of every persistent load door, interior or exterior."""

    def __init__(self, p, plugin_name="Skyrim.esm", navmesh_defaults=None):
        self.p, self.plugin_name, self.navmesh_defaults = p, plugin_name, navmesh_defaults
        self.bases = skyrimrefs.read_bases(p)
        self.lights = read_lights(p)
        self.cells, self.names = {}, {}           # lower EditorID -> (fid, fields, children range); fid -> EditorID
        for fid, fields, rng in _cells(p):
            if _is_interior(fields):
                self.cells.setdefault(_edid(fields).lower(), (fid, fields, rng))
                self.names[fid] = _edid(fields)
        self._doors = None

    def doors(self) -> dict:
        """{door fid: (cell fid, or None for a worldspace door, (dest fid, pos, rot, flags))} of every persistent
        reference with a teleport (XTEL): worldspace doors first, then interior ones (Skyrim pairs them both ways)."""
        if self._doors is not None:
            return self._doors
        found = {}
        p = self.p

        def walk(s, e):
            for item in fo4land.iter_items(p.buf, s, e):
                if item[0] == "GRUP":
                    walk(item[1] + 24, item[2])
                    continue
                typ, off, flags, fid = item
                if typ == b"REFR" and flags & skyrimrefs.PERSISTENT and not flags & skyrimrefs.DELETED:
                    x = _xtel(fo4land.record_data(p.buf, off))
                    if x:
                        found[fid] = (None, x)
        rng = p.top_group(b"WRLD")
        if rng:
            walk(*rng)
        for cfid, _fields, crng in self.cells.values():
            for typ, flags, fid, pers, data in (_children(p, crng) if crng else ()):
                if typ == b"REFR" and (pers or flags & skyrimrefs.PERSISTENT) and not flags & skyrimrefs.DELETED:
                    x = _xtel(data)
                    if x:
                        found[fid] = (cfid, x)
        self._doors = found
        return found

    def connected(self, start: str, depth: int) -> list:
        """EditorIDs of the interior cells reachable from `start` through at most `depth` interior-to-interior load
        doors (breadth first, `start` first). Doors to the worldspace end a path."""
        first = self.cells.get(start.lower())
        if first is None:
            raise KeyError(f"interior cell {start!r} not found")
        doors = self.doors()
        by_cell = {}
        for fid, (cfid, x) in doors.items():
            if cfid is not None:
                by_cell.setdefault(cfid, []).append(x[0])
        seen, frontier = [first[0]], [first[0]]
        for _ in range(max(depth, 0)):
            nxt = []
            for cfid in frontier:
                for dest in by_cell.get(cfid, ()):
                    there = doors.get(dest, (None,))[0]
                    if there is not None and there not in seen:
                        seen.append(there)
                        nxt.append(there)
            frontier = nxt
        return [self.names[c] for c in seen]

    def export(self, edid: str) -> dict:
        """Schema-v2 export of one interior cell (by EditorID, case-insensitive): refs (with type / model / transform),
        deferred_refs (actors, placed hazards, unknown bases), "arrival" {pos, rot, source}, per-door teleport links
        (with the destination door's cell: an interior EditorID or "exterior") and the cell's navmeshes."""
        p, plugin_name, bases, lights = self.p, self.plugin_name, self.bases, self.lights
        hit = self.cells.get(edid.lower())
        if hit is None:
            raise KeyError(f"interior cell {edid!r} not found")
        cfid, fields, rng = hit
        name = _edid(fields)
        refs, deferred, doors, cocs = [], [], [], []
        for typ, flags, fid, pers, data in (_children(p, rng) if rng else ()):
            if flags & skyrimrefs.DELETED:
                continue
            r = skyrimrefs._parse_ref(data)
            if r["pos"] is None:
                continue
            btype, bedid, model = bases.get(r["base"], (None, "", ""))
            entry = {"formkey": skyrimrefs.formkey(fid, plugin_name), "type": btype or "?", "base_editor_id": bedid,
                     "base_formkey": skyrimrefs.formkey(r["base"], plugin_name) if r["base"] else None,
                     "model": model, "pos": r["pos"], "rot": r["rot"], "scale": r["scale"],
                     "disabled": flags & skyrimrefs.DISABLED, "record_flags": flags,
                     "persistent": bool(pers or flags & skyrimrefs.PERSISTENT),
                     "enable_parent": None if r["xesp"] is None else
                     {"reference": skyrimrefs.formkey(r["xesp"][0], plugin_name), "flags": r["xesp"][1]}}
            if btype == "Light" and r["base"] in lights:
                light = dict(lights[r["base"]])
                xr = _xrds(data)
                if xr is not None:
                    light["ref_radius"] = round(xr, 2)
                    # the reference's own radius override; values under MIN_REF_RADIUS are not lighting radii (owner's
                    # Sleeping Giant Inn: ~10 units on several lights turned them into 0.14 m pinpricks)
                    if xr >= MIN_REF_RADIUS:
                        light["radius"] = round(xr, 2)
                entry["light"] = light
            x = _xtel(data)
            if x:
                there = self.doors().get(x[0])
                entry["teleport_destination"] = {
                    "door": skyrimrefs.formkey(x[0], plugin_name), "pos": x[1], "rot": x[2], "flags": x[3],
                    "cell": None if there is None else "exterior" if there[0] is None else self.names[there[0]]}
            if typ == b"ACHR":
                entry["reason"] = "placed actor: NPCs are not translated"
                deferred.append(entry)
            elif btype is None:
                entry["reason"] = f"base {entry['base_formkey']} is not a placeable record read here"
                deferred.append(entry)
            elif typ != b"REFR":
                entry["reason"] = f"{typ.decode()} (placed hazard / projectile / beam): not translated"
                deferred.append(entry)
            else:
                refs.append(entry)
                if btype == "Door":
                    doors.append((fid, entry))
                if bedid == COC_MARKER:
                    cocs.append(entry)
        navmeshes, bad_navmeshes = (_navmeshes(p, rng, plugin_name, self.navmesh_defaults) if rng else ([], []))
        if cocs:
            arrival = {"pos": cocs[0]["pos"], "rot": cocs[0]["rot"], "source": "COCMarkerHeading in the cell"}
        else:
            mine = {fid for fid, _e in doors}
            ins = [(x[1], x[2], fid) for fid, (_c, x) in self.doors().items() if x[0] in mine]
            if ins:
                pos, rot, via = ins[0]
                arrival = {"pos": pos, "rot": rot,
                           "source": f"teleport destination of door {skyrimrefs.formkey(via, plugin_name)}"}
            elif doors:
                arrival = {"pos": doors[0][1]["pos"], "rot": doors[0][1]["rot"],
                           "source": "position of the cell's first door (no teleport into it found)"}
            else:
                arrival = None
        return {"schema_version": 2, "cell": name, "cell_formkey": skyrimrefs.formkey(cfid, plugin_name),
                "interior": True, "source": plugin_name, "lighting": cell_lighting(fields, plugin_name), "refs": refs,
                "deferred_refs": deferred, "arrival": arrival,
                "load_doors": [e["formkey"] for _f, e in doors if "teleport_destination" in e],
                "navmeshes": navmeshes, "unreadable_navmeshes": bad_navmeshes}


def export_interior(esm: str, edid: str, plugin_name: str = "Skyrim.esm", navmesh_defaults=None) -> dict:
    """Schema-v2 export of one interior cell (Source.export)."""
    with fo4land.Plugin(esm) as p:
        return Source(p, plugin_name, navmesh_defaults).export(edid)


def pick_cells(src: Source, names=(), find="", connected_from="", depth=1, limit=0) -> list:
    """The batch's interior EditorIDs, in order, without repeats: `names`, then cells whose EditorID matches the regex
    `find`, then the cells `depth` load doors from `connected_from`. Unknown names raise KeyError. `limit` > 0 caps."""
    out, seen = [], set()

    def add(n):
        hit = src.cells.get(n.lower())
        if hit is None:
            raise KeyError(f"interior cell {n!r} not found")
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(src.names[hit[0]])
    for n in names:
        add(n)
    if find:
        rx = re.compile(find, re.I)
        for n in sorted(src.names.values(), key=str.lower):
            if rx.search(n):
                add(n)
    if connected_from:
        for n in src.connected(connected_from, depth):
            add(n)
    return out[:limit] if limit > 0 else out


def link_load_doors(exports: list) -> dict:
    """Pair the batch's load doors: a door whose Skyrim teleport lands at a door placed in another cell of the batch
    gets "teleport" {door, cell, pos, rot, flags} (Skyrim form key and units; PluginSpike maps them). Returns counts:
    linked, and unlinked by reason (to the worldspace, to a cell outside the batch, destination door unknown)."""
    where = {}
    for e in exports:
        for r in e["refs"]:
            if r["type"] == "Door":
                where[r["formkey"]] = e["cell"]
    linked, unlinked = 0, {}
    for e in exports:
        for r in e["refs"]:
            t = r.get("teleport_destination")
            if not t or r["type"] != "Door":
                continue
            dest = where.get(t["door"])
            if dest is not None:
                r["teleport"] = {"door": t["door"], "cell": dest, "pos": t["pos"], "rot": t["rot"],
                                 "flags": t.get("flags", 0)}
                linked += 1
                continue
            r.pop("teleport", None)
            why = ("to the worldspace (exterior plugin: not linked yet)" if t.get("cell") == "exterior" else
                   "destination door not found" if t.get("cell") is None else
                   f"to a cell outside the batch ({t['cell']})")
            unlinked[why] = unlinked.get(why, 0) + 1
    return {"linked": linked, "unlinked": unlinked}


def plugin_cell(export: dict, selected_refs: list, batch_navmeshes=None) -> dict:
    """The cell JSON PluginSpike reads (`cell`, `refs` with formkey / type / base_editor_id / model / pos / rot / scale /
    disabled): the references selected for conversion, every light (with its Skyrim "light" data: PluginSpike makes a
    Starfield light per distinct Skyrim light), the cell's "skyrim_lighting", and one COCMarkerHeading at the arrival
    point when the cell has none of its own. Linked load doors (link_load_doors) carry "teleport"; edge links to
    navmeshes outside `batch_navmeshes` (default: this cell's) are cut."""
    keep = {r["formkey"] for r in selected_refs}
    refs = []
    for r in export["refs"]:
        if r["formkey"] in keep or r["type"] == "Light" or r["base_editor_id"] == COC_MARKER:
            refs.append({k: r.get(k) for k in ("formkey", "type", "base_editor_id", "model", "pos", "rot", "scale",
                                               "disabled")})
            if "light" in r:
                refs[-1]["light"] = r["light"]
            if "teleport" in r:
                refs[-1]["teleport"] = r["teleport"]
    arr = export.get("arrival")
    if arr and not any(r["base_editor_id"] == COC_MARKER for r in refs):
        z_up = [arr["pos"][0], arr["pos"][1], arr["pos"][2] + 10.0]     # 10 units up: spawn above the floor, not in it
        refs.append({"formkey": "ARRIVAL:" + export["cell"], "type": "Static", "base_editor_id": COC_MARKER,
                     "model": "", "pos": z_up, "rot": arr["rot"], "scale": 1.0, "disabled": 0})
    out = {"schema_version": 2, "cell": export["cell"], "cell_formkey": export.get("cell_formkey"), "refs": refs}
    if export.get("navmeshes"):
        # edge links to navmeshes outside this cell cannot be written yet (no target): cut cleanly
        from . import skyrimnavmesh
        here = set(batch_navmeshes or ()) | {n["formkey"] for n in export["navmeshes"]}
        out["navmeshes"] = [{"formkey": n["formkey"], "geometry": skyrimnavmesh.cut_links(n["geometry"], here)}
                            for n in export["navmeshes"]]
    if export.get("lighting"):
        out["skyrim_lighting"] = export["lighting"]
    return out
