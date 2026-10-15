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
import struct

from fo4sf import fo4land, skyrimrefs

INTERIOR = 0x1                     # CELL DATA flag
COC_MARKER = "COCMarkerHeading"
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
    for sig, d in fo4land.iter_subrecords(data):
        if sig == b"XTEL" and len(d) >= 28:
            door, *pr = struct.unpack_from("<I6f", d)
            return door, list(pr[:3]), list(pr[3:])
    return None


def _arrivals_into(p, door_fids):
    """[(pos, rot, from door fid)] of persistent references anywhere whose XTEL destination is one of `door_fids`."""
    found = []

    def walk(s, e):
        for item in fo4land.iter_items(p.buf, s, e):
            if item[0] == "GRUP":
                walk(item[1] + 24, item[2])
                continue
            typ, off, flags, fid = item
            if typ == b"REFR" and flags & skyrimrefs.PERSISTENT and not flags & skyrimrefs.DELETED:
                x = _xtel(fo4land.record_data(p.buf, off))
                if x and x[0] in door_fids:
                    found.append((x[1], x[2], fid))
    for label in (b"WRLD", b"CELL"):
        rng = p.top_group(label)
        if rng:
            walk(*rng)
    return found


def export_interior(esm: str, edid: str, plugin_name: str = "Skyrim.esm") -> dict:
    """Schema-v2 export of one interior cell (by EditorID, case-insensitive): refs (with type / model / transform),
    deferred_refs (actors, placed hazards, unknown bases), "arrival" {pos, rot, source} and per-door teleport links."""
    with fo4land.Plugin(esm) as p:
        bases = skyrimrefs.read_bases(p)
        lights = read_lights(p)
        hit = None
        for fid, fields, rng in _cells(p):
            if _is_interior(fields) and _edid(fields).lower() == edid.lower():
                hit = (fid, fields, rng)
                break
        if hit is None:
            raise KeyError(f"interior cell {edid!r} not found in {esm}")
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
                if xr is not None and xr > 0:                       # the reference's own radius override
                    light["radius"] = round(xr, 2)
                entry["light"] = light
            x = _xtel(data)
            if x:
                entry["teleport_destination"] = {"door": skyrimrefs.formkey(x[0], plugin_name), "pos": x[1],
                                                 "rot": x[2]}
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
        if cocs:
            arrival = {"pos": cocs[0]["pos"], "rot": cocs[0]["rot"], "source": "COCMarkerHeading in the cell"}
        else:
            ins = _arrivals_into(p, {fid for fid, _e in doors})
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
            "interior": True, "source": plugin_name, "lighting": cell_lighting(fields, plugin_name), "refs": refs, "deferred_refs": deferred, "arrival": arrival,
            "load_doors": [e["formkey"] for _f, e in doors if "teleport_destination" in e]}


def plugin_cell(export: dict, selected_refs: list) -> dict:
    """The cell JSON PluginSpike reads (`cell`, `refs` with formkey / type / base_editor_id / model / pos / rot / scale /
    disabled): the references selected for conversion, every light (with its Skyrim "light" data: PluginSpike makes a
    Starfield light per distinct Skyrim light), the cell's "skyrim_lighting", and one COCMarkerHeading at the arrival
    point when the cell has none of its own."""
    keep = {r["formkey"] for r in selected_refs}
    refs = []
    for r in export["refs"]:
        if r["formkey"] in keep or r["type"] == "Light" or r["base_editor_id"] == COC_MARKER:
            refs.append({k: r.get(k) for k in ("formkey", "type", "base_editor_id", "model", "pos", "rot", "scale",
                                               "disabled")})
            if "light" in r:
                refs[-1]["light"] = r["light"]
    arr = export.get("arrival")
    if arr and not any(r["base_editor_id"] == COC_MARKER for r in refs):
        z_up = [arr["pos"][0], arr["pos"][1], arr["pos"][2] + 10.0]     # 10 units up: spawn above the floor, not in it
        refs.append({"formkey": "ARRIVAL:" + export["cell"], "type": "Static", "base_editor_id": COC_MARKER,
                     "model": "", "pos": z_up, "rot": arr["rot"], "scale": 1.0, "disabled": 0})
    out = {"schema_version": 2, "cell": export["cell"], "refs": refs}
    if export.get("lighting"):
        out["skyrim_lighting"] = export["lighting"]
    return out
