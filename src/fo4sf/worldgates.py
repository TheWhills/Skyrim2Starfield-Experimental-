"""Gates between two of our overlay worlds: Skyrim's load doors from Tamriel into a walled city and back (2026-11-25,
owner: "Whiterun first ... loads in game from Tamriel through its gate"). docs/terrain/skyrim-cities.md "Gates".

Skyrim pairs each city gate with a door in Tamriel (both persistent, each with XTEL to the other: Whiterun's main gate
Tamriel 01B1F1 <-> WhiterunWorld 01B1F3, both WRDoorMainGate01). Our exterior and city builds place those doors as
statics. As for Riverwood's doors (verified in game 2026-11-08, PluginSpike), a separate plugin adds a NEW persistent
load door at each static's place, with XTEL to the other world's new door, in an override of each world's persistent
cell; the statics are hidden in their own plugins, in place (scripts/terrain/apply_ref_overrides.py's patch: the game
did not apply another plugin's override of an exterior temporary reference, owner 2026-11-14).

Record layouts copied from FO4Port.esm's exterior load door, which Mutagen wrote and which works in game: DOOR = EDID,
OBND (the static's), ODTY, FULL, MODL ("Meshes\\" + the static's model), FNAM 0, DEVT 1; REFR = NAME, XTEL (36 bytes:
door, landing position (m), rotation (rad), flags, 4 zero bytes: scripts/interior/door_survey.py on Starfield.esm),
DATA; record flag 0x400 (persistent: without it a door worked once, 2026-10-23).
"""
import struct

from . import fo4land, sfplugin, skyrimrefs

PERSISTENT = 0x400
DISABLED = 0x800
SINK_M = 1000.0                                      # as PluginSpike's HideExteriorStatic / apply_ref_overrides
UNITS_PER_M = 70.0
DOOR_DEVT = struct.pack("<I", 1)                     # as FO4Port.esm's LD_Ext_ doors (Mutagen's default)
WORLD_FORMID_FIELDS = (b"BNAM", b"XLCN", b"CNAM", b"NAM3", b"NAM4", b"ZNAM", b"INAM", b"WNAM")


# --------------------------------------------------------------------------------------------------- Skyrim's pairs
def skyrim_gates(esm: str, main_world: str, city_world: str, margin: int = 2) -> list:
    """[{"main": ref, "city": ref}] of the load doors linking main_world and city_world both ways, each ref
    {"src" (Skyrim form key), "pos", "rot", "xtel": {"door", "pos", "rot", "flags"}} in Skyrim units. Only the main
    world's cells around the city doors' landing points are read (margin cells)."""
    city = skyrimrefs.export_world(esm, city_world, alt_plugins=())
    every = city["refs"] + city["deferred_refs"]
    doors = [r for r in every if r.get("teleport_destination")]
    if not doors:
        return []
    xs = [int(r["teleport_destination"]["pos"][0] // 4096) for r in doors]
    ys = [int(r["teleport_destination"]["pos"][1] // 4096) for r in doors]
    rect = (min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin)
    main = skyrimrefs.export_world(esm, main_world, cells=rect, alt_plugins=())
    by_fk = {r["formkey"]: r for r in main["refs"] + main["deferred_refs"]}
    out = []
    for c in doors:
        m = by_fk.get(c["teleport_destination"]["door"])
        if m is None or not m.get("teleport_destination") or m["teleport_destination"]["door"] != c["formkey"]:
            continue                                  # leads elsewhere (an interior), or not back
        out.append({"main": _door(m), "city": _door(c)})
    return out


def _door(r):
    t = r["teleport_destination"]
    return {"src": r["formkey"], "edid": r.get("base_editor_id", ""), "pos": list(r["pos"]), "rot": list(r["rot"]),
            "xtel": {"door": t["door"], "pos": list(t["pos"]), "rot": list(t["rot"]), "flags": int(t["flags"])}}


def to_local(pos_units, overlay) -> tuple:
    """A Skyrim position (units) in an overlay's frame (metres): / 70 - origin_cw_m, z + height_offset_m (as
    make_skyrim_objects.to_local and PluginSpike's ExtPos)."""
    ox, oy = (float(v) for v in overlay.get("origin_cw_m", (0.0, 0.0)))
    oz = float(overlay.get("height_offset_m") or 0.0)
    return (pos_units[0] / UNITS_PER_M - ox, pos_units[1] / UNITS_PER_M - oy, pos_units[2] / UNITS_PER_M + oz)


# ------------------------------------------------------------------------------------------------ plugin reading
def placed_refs(path: str, local_ids) -> dict:
    """{local id: (record header 24 bytes, record flags, [(sig, data)])} of the plugin's own placed references with
    those local ids (anywhere in its worlds)."""
    want = set(local_ids)
    out = {}
    with fo4land.Plugin(path) as p:
        own = _n_masters(p)

        def walk(s, e):
            for it in fo4land.iter_items(p.buf, s, e):
                if it[0] == "GRUP":
                    walk(it[1] + 24, it[2])
                    continue
                typ, off, flags, fid = it
                if typ == b"REFR" and fid >> 24 == own and (fid & 0xFFFFFF) in want:
                    if flags & fo4land.COMPRESSED:
                        raise ValueError(f"{path}: reference {fid:08X} is compressed")
                    out[fid & 0xFFFFFF] = (bytes(p.buf[off:off + 24]), flags,
                                           [(s_, bytes(d)) for s_, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off))])
        for it in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if it[0] == "GRUP" and it[3] == b"WRLD":
                walk(it[1] + 24, it[2])
    return out


def _n_masters(p) -> int:
    return sum(1 for s, _d in fo4land.iter_subrecords(fo4land.record_data(p.buf, 0)) if s == b"MAST")


def n_masters(path: str) -> int:
    with fo4land.Plugin(path) as p:
        return _n_masters(p)


# ---------------------------------------------------------------------------------------------------- remapping
def remap(fid: int, own_from: int, own_to: int) -> int:
    return (own_to << 24) | (fid & 0xFFFFFF) if fid >> 24 == own_from else fid


def remap_world_subs(subs, own_from: int, own_to: int) -> list:
    """A WRLD record's fields as seen from another plugin, where the world's own plugin is master own_to instead of
    own_from: the 4-byte FormID fields (block BNAM, location XLCN, biome BNAM, climate CNAM, water NAM3 / NAM4 ...)
    and every reference in the large-reference grid (RNAM: i16 x, i16 y, u32 n, n x (u32 FormID, i16 x, i16 y)).
    OFST / CLSZ (the terrain plugin's own file offsets) are dropped, as make_planet.world_group does."""
    out = []
    for s, d in subs:
        if s in (b"OFST", b"CLSZ"):
            continue
        if s in WORLD_FORMID_FIELDS and len(d) == 4:
            d = struct.pack("<I", remap(struct.unpack("<I", d)[0], own_from, own_to))
        elif s == b"RNAM" and len(d) >= 8:
            gx, gy, n = struct.unpack_from("<hhI", d, 0)
            if len(d) != 8 + 8 * n:
                raise ValueError(f"RNAM of {len(d)} bytes does not hold {n} entries")
            b = bytearray(d)
            for k in range(n):
                o = 8 + 8 * k
                struct.pack_into("<I", b, o, remap(struct.unpack_from("<I", b, o)[0], own_from, own_to))
            d = bytes(b)
        out.append((s, d))
    return out


# --------------------------------------------------------------------------------------------------- new records
def door_record(stat_subs, edid: str, name: str):
    """DOOR fields for a load door with a static's model and bounds (FO4Port.esm's verified layout)."""
    st = dict(stat_subs)
    model = fo4land.zstring(st[b"MODL"])
    if not model.lower().startswith("meshes\\"):
        model = "Meshes\\" + model
    subs = [(b"EDID", sfplugin.zs(edid))]
    if b"OBND" in st:
        subs.append((b"OBND", st[b"OBND"]))
    subs += [(b"ODTY", bytes(4)), (b"FULL", sfplugin.zs(name)), (b"MODL", sfplugin.zs(model)), (b"FNAM", b"\0"),
             (b"DEVT", DOOR_DEVT)]
    return subs


def xtel(door_fid: int, pos_m, rot, flags: int = 0) -> bytes:
    return struct.pack("<I3f3fII", door_fid, *(float(v) for v in pos_m), *(float(v) for v in rot), int(flags), 0)


def door_ref_subs(base_fid: int, data: bytes, teleport: bytes) -> list:
    if len(data) != 24:
        raise ValueError("DATA must be 24 bytes (position, rotation)")
    return [(b"NAME", struct.pack("<I", base_fid)), (b"XTEL", teleport), (b"DATA", data)]


def sunk(data: bytes) -> bytes:
    """The static's DATA moved SINK_M down (what a hidden static gets, with the Initially Disabled flag)."""
    x, y, z, rx, ry, rz = struct.unpack("<6f", data)
    return struct.pack("<6f", x, y, z - SINK_M, rx, ry, rz)


def world_groups(worlds) -> bytes:
    """ONE top WRLD group: per world (wrld (header, subs, FormID), persistent cell (header, subs, FormID), [REFR record
    bytes]) the world record (override), its children group with the persistent cell (override) and our references
    in that cell's persistent children (make_planet.world_group for several worlds)."""
    body = b""
    for (wh, wsubs, wfid), (ch, csubs, cfid), refs in worlds:
        recs = b"".join(refs)
        pers = struct.pack("<4sI4si", b"GRUP", 24 + len(recs), struct.pack("<I", cfid), 8) + bytes(8) + recs
        kids6 = struct.pack("<4sI4si", b"GRUP", 24 + len(pers), struct.pack("<I", cfid), 6) + bytes(8) + pers
        body1 = sfplugin.record_bytes(b"CELL", ch, csubs, cfid) + kids6
        kids1 = struct.pack("<4sI4si", b"GRUP", 24 + len(body1), struct.pack("<I", wfid), 1) + bytes(8) + body1
        body += sfplugin.record_bytes(b"WRLD", wh, wsubs, wfid) + kids1
    return struct.pack("<4sI4si", b"GRUP", 24 + len(body), b"WRLD", 0) + bytes(8) + body
