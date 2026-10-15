"""Skyrim exterior references -> the placement export the object pipeline reads (docs/CELL-EXPORT.md, schema v2), so
exterior.select / exterior.place / dotnet/TerrainOverlays take Skyrim objects exactly as they take FO4's.

Read straight from Skyrim.esm with fo4land's record walker (24-byte headers, zlib records, WRLD -> blocks -> CELL ->
persistent / temporary children). Per reference: FormKey "XXXXXX:Skyrim.esm", base type in Mutagen's names (STAT ->
Static, TREE -> Tree, ...), base EditorID / FormKey / model (MODL; armour's world model MOD2), position and rotation
(DATA, game units and radians), scale (XSCL), the raw record flags and the 0x800 initially-disabled mask, persistence
(0x400 or the worldspace's persistent cell), the exterior cell (XCLC, or floor(position / 4096) for persistent refs)
and the enable parent (XESP). Placed actors (ACHR) go to deferred_refs: NPCs are not translated.
"""
import math
import struct

from fo4sf import fo4land

SIG_TYPES = {
    "STAT": "Static", "MSTT": "MovableStatic", "TREE": "Tree", "FLOR": "Flora", "FURN": "Furniture", "DOOR": "Door",
    "ACTI": "Activator", "CONT": "Container", "MISC": "MiscItem", "LIGH": "Light", "TXST": "TextureSet",
    "IDLM": "IdleMarker", "SOUN": "SoundMarker", "ASPC": "AcousticSpace", "ALCH": "Ingestible", "WEAP": "Weapon",
    "AMMO": "Ammunition", "ARMO": "Armor", "BOOK": "Book", "INGR": "Ingredient", "KEYM": "Key", "SLGM": "SoulGem",
    "SCRL": "Scroll", "APPA": "AlchemicalApparatus", "ADDN": "AddonNode", "ARTO": "ArtObject", "HAZD": "Hazard",
    "EXPL": "Explosion", "PROJ": "Projectile", "SCOL": "StaticCollection", "NPC_": "Npc", "LVLN": "LeveledNpc",
}
# what Skyrim places outdoors that becomes a plain Starfield static (visuals + collision, no function)
CONVERT_TYPES = ("Static", "StaticCollection", "MovableStatic", "Tree", "Flora", "Furniture", "Door", "Activator",
                 "Container", "MiscItem", "Ingestible", "Weapon", "Ammunition", "Armor", "Book", "Ingredient", "Key",
                 "SoulGem", "Scroll", "AlchemicalApparatus")
PLACED = (b"REFR", b"ACHR", b"PGRE", b"PHZD", b"PMIS", b"PARW", b"PBEA", b"PFLA", b"PCON", b"PBAR")
DELETED, PERSISTENT, DISABLED = 0x20, 0x400, 0x800


def formkey(fid: int, plugin: str = "Skyrim.esm") -> str:
    return f"{fid & 0xFFFFFF:06X}:{plugin}"


def read_bases(p: fo4land.Plugin, wanted_sigs=tuple(SIG_TYPES)) -> dict:
    """{form id: (type, editor id, model)} of every base record of the wanted signatures (top groups only)."""
    want = {s.encode() for s in wanted_sigs}
    out = {}
    for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
        if item[0] != "GRUP" or item[3] not in want:
            continue
        for typ, off, flags, fid in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
            if typ == "GRUP" or flags & DELETED:
                continue
            edid, model, mod2 = "", "", ""
            for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                if sig == b"EDID":
                    edid = fo4land.zstring(d)
                elif sig == b"MODL" and not model and typ != b"ARMO":
                    # ARMO's MODL entries are its armature FormIDs (4 bytes), not paths: reading them as text produced
                    # 75 garbage model names on the owner's Skyrim SE. Its world model is MOD2. Paths end in .nif.
                    cand = fo4land.zstring(d)
                    if cand.lower().endswith(".nif"):
                        model = cand
                elif sig == b"MOD2" and not mod2:
                    mod2 = fo4land.zstring(d)
            out[fid] = (SIG_TYPES.get(typ.decode("ascii"), typ.decode("ascii")), edid, model or mod2)
    return out


def _parse_ref(data: bytes):
    r = {"base": None, "pos": None, "rot": None, "scale": 1.0, "xesp": None}
    for sig, d in fo4land.iter_subrecords(data):
        if sig == b"NAME" and len(d) >= 4:
            r["base"] = struct.unpack_from("<I", d)[0]
        elif sig == b"DATA" and len(d) >= 24:
            v = struct.unpack_from("<6f", d)
            r["pos"], r["rot"] = list(v[:3]), list(v[3:])
        elif sig == b"XSCL" and len(d) >= 4:
            r["scale"] = struct.unpack_from("<f", d)[0]
        elif sig == b"XESP" and len(d) >= 5:
            parent, flags = struct.unpack_from("<IB", d)
            r["xesp"] = (parent, flags)
    return r


def export_world(esm: str, world: str = "Tamriel", cells=None, plugin_name: str = "Skyrim.esm") -> dict:
    """The schema-v2 export of every placed reference in the worldspace (or only exterior cells inside the inclusive
    rectangle cells = (x0, x1, y0, y1); persistent references are kept when their position lies inside it)."""
    def inside(xy):
        return cells is None or (cells[0] <= xy[0] <= cells[1] and cells[2] <= xy[1] <= cells[3])

    refs, deferred, stats = [], [], {"cells": 0, "deleted": 0, "no_base": 0}
    with fo4land.Plugin(esm) as p:
        bases = read_bases(p)
        _wfid, start, end, _fields = p.find_world(world)

        def walk(s, e, cell):
            for item in fo4land.iter_items(p.buf, s, e):
                if item[0] == "GRUP":
                    _g, off, gend, label, gtype = item
                    if gtype in (4, 5):
                        walk(off + 24, gend, None)
                    elif gtype == 6 and cell is not None and struct.unpack("<I", label)[0] == cell["fid"]:
                        walk(off + 24, gend, cell)
                    elif gtype in (8, 9) and cell is not None:
                        children(off + 24, gend, cell, gtype == 8)
                    continue
                typ, off, _flags, fid = item
                if typ != b"CELL":
                    continue
                xy = None
                for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                    if sig == b"XCLC" and len(d) >= 8:
                        xy = struct.unpack_from("<ii", d)
                cell = {"fid": fid, "xy": xy}
                if xy is not None:
                    stats["cells"] += 1

        def children(s, e, cell, persistent_group):
            for item in fo4land.iter_items(p.buf, s, e):
                if item[0] == "GRUP":
                    continue
                typ, off, flags, fid = item
                if typ not in PLACED:
                    continue
                if flags & DELETED:
                    stats["deleted"] += 1
                    continue
                r = _parse_ref(fo4land.record_data(p.buf, off))
                if r["pos"] is None:
                    continue
                xy = cell["xy"] if cell["xy"] is not None else (int(math.floor(r["pos"][0] / 4096.0)),
                                                                int(math.floor(r["pos"][1] / 4096.0)))
                if not inside(xy):
                    continue
                btype, bedid, model = bases.get(r["base"], (None, "", ""))
                entry = {"formkey": formkey(fid, plugin_name), "type": btype or "?", "base_editor_id": bedid,
                         "base_formkey": formkey(r["base"], plugin_name) if r["base"] else None, "model": model,
                         "pos": r["pos"], "rot": r["rot"], "scale": r["scale"], "disabled": flags & DISABLED,
                         "record_flags": flags, "persistent": bool(persistent_group or flags & PERSISTENT),
                         "exterior_cell": list(xy),
                         "enable_parent": None if r["xesp"] is None else
                         {"reference": formkey(r["xesp"][0], plugin_name), "flags": r["xesp"][1]}}
                if typ == b"ACHR":
                    entry["reason"] = "placed actor: NPCs are not translated (terrain and objects only)"
                    deferred.append(entry)
                elif btype is None:
                    stats["no_base"] += 1
                    entry["reason"] = f"base {entry['base_formkey']} is not a placeable record read here"
                    deferred.append(entry)
                elif typ != b"REFR":
                    entry["reason"] = f"{typ.decode()} (placed hazard / projectile / beam): not translated"
                    deferred.append(entry)
                else:
                    refs.append(entry)

        walk(start, end, None)
    return {"schema_version": 2, "cell": world, "worldspace": world, "source": plugin_name,
            "cells_filter": list(cells) if cells else None, "refs": refs, "deferred_refs": deferred, "stats": stats}
