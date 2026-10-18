"""A custom planet for the Skyrim overlay (docs/terrain/skyrim-tamriel.md "Custom planet").

Clones a vanilla planet record (PNDT, default JemisonPlanetData) into the overlay's planet plugin (the "_Mars" plugin
that TerrainOverlays wrote, which loads after the terrain plugin) as a NEW planet in the same star system, with its own
name, a small radius, two biomes (an ocean and a land biome) and its own biome map
(Data\\planetdata\\biomemaps\\<name>.biom): a land disc of --land-px pixels round the centre of both polar maps (the
poles), ocean everywhere else, so the planet's sea surrounds Skyrim when the overlay sits on a pole (--latlon -1.5707963
0 in make_skyrim_overlay.py). The overlay world is the planet's only master worldspace (PNDT CNAM).

Field readings (owner's dump_records.py runs of Jemison, Luna, Montara Luna, Vesta Lunaris, Volii Alpha; supported, not
verified): ANAM name (and biome map file name: Jemison / jemison.biom); FNAM[24] radius km as f32 at offset 12 (Luna
1737); GNAM[12] (star system id, parent body, slot); PPBD per biome (FormID, coverage % f32, ...); CNAM[20 x n]
(lat f64, lon f64, world FormID) master worldspaces; ENAM[72] orbit (f64 distances in km). Biome map: u16 0x105,
u32 n, n biome FormIDs, u32 2, then per pole map 256 x 256 u32 biome FormIDs and 256 x 256 resource bytes (8 = none:
every ocean pixel of Jemison's map holds 8).

    python scripts\\terrain\\make_planet.py --sf-esm "<Starfield>\\Data\\Starfield.esm" --staging C:\\Modding\\staging\\skyrim_all ^
        --name Nirn --radius-km 200
"""
import argparse
import json
import math
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402

REC = struct.Struct("<4sIII")
OCEAN = 0x07F88A          # OceanLife04 (Jemison's ocean)
LAND = 0x1CBD6A           # ForestDeciduousLifeJemison (the overlay world's biome)
RESOURCE_NONE = 8


def find_record(buf, body, typ: bytes, edid: str):
    """(record offset, header bytes, subrecords) of the record of that type with that EditorID."""
    for item in fo4land.iter_items(buf, body, len(buf)):
        if item[0] == "GRUP" and item[3] == typ:
            for t, off, _fl, _fid in fo4land.iter_items(buf, item[1] + 24, item[2]):
                if t == "GRUP":
                    continue
                subs = [(s, bytes(d)) for s, d in fo4land.iter_subrecords(fo4land.record_data(buf, off))]
                if next((fo4land.zstring(d) for s, d in subs if s == b"EDID"), "") == edid:
                    return off, bytes(buf[off:off + 24]), subs
    raise KeyError(f"{typ.decode()} {edid} not found")


def zs(text: str) -> bytes:
    return text.encode("latin-1") + b"\0"


def planet_subrecords(subs, name, edid, radius_km, slot, worlds, biomes, orbit_scale, remap=None):
    """The cloned subrecords with the changes listed in the module docstring. worlds: [(lat, lon, raw FormID)];
    biomes: {FormID: coverage %} (PPBD entries of other biomes are dropped)."""
    out, seen = [], {}
    for s, d in subs:
        k = seen[s] = seen.get(s, 0) + 1
        if s == b"EDID":
            d = zs(edid)
        elif s == b"FULL":
            d = zs(name)                              # our plugin is not localized: a plain string
        elif s == b"ANAM":
            d = zs(name)
        elif s == b"CNAM" and len(d) % 20 == 0 and k == 1:
            d = b"".join(struct.pack("<ddI", la, lo, fid) for la, lo, fid in worlds)
        elif s == b"FNAM" and len(d) == 24:
            d = d[:12] + struct.pack("<f", float(radius_km)) + d[16:]
        elif s == b"GNAM" and len(d) == 12:
            system, _parent, _slot = struct.unpack("<III", d)
            d = struct.pack("<III", system, 0, slot)
        elif s == b"ENAM" and len(d) == 72:
            v = list(struct.unpack("<9d", d))
            v = [x * orbit_scale if x > 1e6 else x for x in v]
            d = struct.pack("<9d", *v)
        elif s == b"PPBD":
            fid = struct.unpack_from("<I", d)[0]
            if fid not in biomes:
                continue
            d = struct.pack("<If", (remap or {}).get(fid, fid), float(biomes[fid])) + d[8:]
        out.append((s, d))
    back = {v: k for k, v in (remap or {}).items()}
    have = {back.get(struct.unpack_from("<I", d)[0], struct.unpack_from("<I", d)[0]) for s, d in out if s == b"PPBD"}
    missing = set(biomes) - have
    if missing:
        raise ValueError(f"the template planet has no PPBD entry for biomes {sorted(hex(m) for m in missing)}")
    return out


COATING = b"EFSD"     # a biome's global-layer material: OceanLife04 gl_slimeocean01.mat, FrozenLife07 gl_snow_heavy_01.mat,
                      # ForestDeciduousLifeJemison none (owner's dump_records run); the "underwater / mossy" and snow
                      # coats on every object at the ocean spot / frozen test


def clean_biome(subs, edid: str):
    """A biome's subrecords without its global-layer coating (EFSD), renamed."""
    out = [(s, zs(edid) if s == b"EDID" else d) for s, d in subs if s != COATING]
    if len(out) == len(subs):
        raise ValueError("the biome has no EFSD (coating) to remove")
    return out


def biome_map(land_px: float, land=LAND, ocean=OCEAN, size=256) -> bytes:
    """Both pole maps: a land disc of radius land_px pixels round the centre, ocean elsewhere."""
    c = (size - 1) / 2.0
    ids = [land if math.hypot(x - c, y - c) <= land_px else ocean for y in range(size) for x in range(size)]
    one = struct.pack("<III", size, size, size * size) + struct.pack(f"<{size * size}I", *ids) + \
        struct.pack("<I", size * size) + bytes([RESOURCE_NONE]) * (size * size)
    return struct.pack("<HI", 0x105, 2) + struct.pack("<2I", ocean, land) + struct.pack("<I", 2) + one + one


def record_bytes(typ: bytes, header: bytes, subs, fid: int) -> bytes:
    data = b"".join(s + struct.pack("<H", len(d)) + d for s, d in subs)
    _t, _size, flags, _fid = REC.unpack_from(header, 0)
    return struct.pack("<4sIII", typ, len(data), flags & ~fo4land.COMPRESSED, fid) + header[16:24] + data


def group_bytes(typ: bytes, recs) -> bytes:
    body = b"".join(recs)
    return struct.pack("<4sI4si", b"GRUP", 24 + len(body), typ, 0) + bytes(8) + body


def write_plugin(path, planet_header: bytes, subs, fid: int, before=(), after_groups=b"", extra_records=0,
                 top_fid=0):
    """Replace the planet plugin's content: its TES4 header (masters as TerrainOverlays wrote them), the `before`
    records ((type, header, subs, FormID), one top group per type, e.g. our BIOM) and one PNDT group with the planet."""
    raw = open(path, "rb").read()
    tes4_size = REC.unpack_from(raw, 0)[1]
    tes4 = bytearray(raw[:24 + tes4_size])
    data = b"".join(s + struct.pack("<H", len(d)) + d for s, d in subs)
    by_type = {}
    for t, h, sb, f in before:                       # one top group per record type, in first-seen order
        by_type.setdefault(t, []).append(record_bytes(t, h, sb, f))
    groups = b"".join(group_bytes(t, recs) for t, recs in by_type.items())
    grp = groups + group_bytes(b"PNDT", [record_bytes(b"PNDT", planet_header, subs, fid)]) + after_groups
    top = max([fid, top_fid] + [f for _t, _h, _s, f in before if f >> 24 == fid >> 24]) & 0xFFFFFF
    # TES4 HEDR: version f32, record count u32, next object id u32
    subs4 = list(fo4land.iter_subrecords(bytes(tes4[24:])))
    off = 24
    for s, d in subs4:
        if s == b"HEDR" and len(d) >= 12:
            struct.pack_into("<II", tes4, off + 6 + 4, 1 + len(before) + extra_records, top + 1)
        off += 6 + len(d)
    with open(path, "wb") as fh:
        fh.write(bytes(tes4) + grp)
    return len(data)


# --------------------------------------------------------------------------------------- locations and markers
# New Atlantis's chain (owner's survey_markers.py run): CityNewAtlantisLocation -> SAlphaCentauri_PJemison_Surface
# (0001AB2B) -> SAlphaCentauri_PJemison (0001AB29) -> SAlphaCentauri; Jemison's three planet locations (planet,
# _Surface, _Orbit) carry XNAM = the star system id (011720) and YNAM = the planet's slot (3). Landing pads:
# ShipLandingMarker_80m_Large (FURN 00007145); map markers: MapMarker (STAT 00000010) with XMRK, FNAM flags (0x13 on
# the spaceport's), FULL, TNAM type, VNAM, UNAM, VISI and XLKR to the pad.
JEMISON_LOCS = ("SAlphaCentauri_PJemison", "SAlphaCentauri_PJemison_Surface", "SAlphaCentauri_PJemison_Orbit")
LANDING_MARKER = 0x00007145
MAP_MARKER = 0x00000010
PERSISTENT = 0x400


def location_subrecords(subs, edid, name, parent=None, slot=None, drop=(b"LCSR", b"LCEP")):
    out = []
    for s, d in subs:
        if s in drop:
            continue
        if s == b"EDID":
            d = zs(edid)
        elif s == b"FULL":
            d = zs(name)
        elif s == b"PNAM" and parent is not None:
            d = struct.pack("<I", parent)
        elif s == b"YNAM" and slot is not None:
            d = struct.pack("<I", slot)
        out.append((s, d))
    return out


def world_and_persistent_cell(buf, body, edid):
    """((WRLD header, subs, FormID), (persistent CELL header, subs, FormID)) of a world in a plugin."""
    wrld, pending = None, None
    for item in fo4land.iter_items(buf, body, len(buf)):
        if item[0] == "GRUP" and item[3] == b"WRLD":
            for it in fo4land.iter_items(buf, item[1] + 24, item[2]):
                if it[0] == "GRUP":
                    if pending and it[4] == 1 and struct.unpack("<I", it[3])[0] == pending[2]:
                        for c in fo4land.iter_items(buf, it[1] + 24, it[2]):
                            if c[0] != "GRUP" and c[0] == b"CELL":
                                csubs = [(s, bytes(d)) for s, d in fo4land.iter_subrecords(fo4land.record_data(buf, c[1]))]
                                return pending, (bytes(buf[c[1]:c[1] + 24]), csubs, c[3])
                    continue
                typ, off, _fl, fid = it
                if typ == b"WRLD":
                    subs = [(s, bytes(d)) for s, d in fo4land.iter_subrecords(fo4land.record_data(buf, off))]
                    if next((fo4land.zstring(d) for s, d in subs if s == b"EDID"), "") == edid:
                        pending = (bytes(buf[off:off + 24]), subs, fid)
    raise KeyError(f"world {edid} (with its persistent cell) not found")


def ref_subrecords(edid, base, pos, extra=()):
    return [(b"EDID", zs(edid)), (b"NAME", struct.pack("<I", base))] + list(extra) + \
        [(b"DATA", struct.pack("<6f", float(pos[0]), float(pos[1]), float(pos[2]), 0.0, 0.0, 0.0))]


def map_marker_extra(name, landing_fid, flags=0x13, kind=4):
    return [(b"XMRK", b""), (b"FNAM", struct.pack("<I", flags)), (b"FULL", zs(name)), (b"TNAM", struct.pack("<H", kind)),
            (b"VNAM", struct.pack("<H", 0)), (b"UNAM", struct.pack("<I", 0)), (b"VISI", b"\0"),
            (b"XLKR", struct.pack("<II", 0, landing_fid))]


def world_group(wrld, cell, refs) -> bytes:
    """Top WRLD group: the world record (override), its children group with the persistent cell (override) and that
    cell's persistent children (our references)."""
    wh, wsubs, wfid = wrld
    ch, csubs, cfid = cell
    wsubs = [(s, d) for s, d in wsubs if s not in (b"OFST", b"CLSZ")]         # file offsets of the terrain plugin
    recs = b"".join(refs)
    pers = struct.pack("<4sI4si", b"GRUP", 24 + len(recs), struct.pack("<I", cfid), 8) + bytes(8) + recs
    kids6 = struct.pack("<4sI4si", b"GRUP", 24 + len(pers), struct.pack("<I", cfid), 6) + bytes(8) + pers
    cellrec = record_bytes(b"CELL", ch, csubs, cfid)
    body1 = cellrec + kids6
    kids1 = struct.pack("<4sI4si", b"GRUP", 24 + len(body1), struct.pack("<I", wfid), 1) + bytes(8) + body1
    wrec = record_bytes(b"WRLD", wh, wsubs, wfid)
    return group_bytes(b"WRLD", [wrec + kids1])


def masters_of(path):
    raw = open(path, "rb").read()
    size = REC.unpack_from(raw, 0)[1]
    return [fo4land.zstring(d) for s, d in fo4land.iter_subrecords(raw[24:24 + size]) if s == b"MAST"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-esm", required=True)
    ap.add_argument("--staging", required=True, help="the staged build (objects stage / lod --out)")
    ap.add_argument("--name", default="Nirn")
    ap.add_argument("--template", default="JemisonPlanetData")
    ap.add_argument("--radius-km", type=float, default=200.0)
    ap.add_argument("--land-px", type=float, default=3.0,
                    help="land disc radius in biome-map pixels (one pixel ~ pi/2 x radius / 128 km)")
    ap.add_argument("--only-biome", default="",
                    help="diagnostic: one biome everywhere (hex FormID with a PPBD entry in the template, e.g. 0FD00D "
                         "FrozenLife07): snow round Skyrim proves the engine reads our biome map")
    ap.add_argument("--keep-ocean-coating", action="store_true",
                    help="use vanilla OceanLife04 as is (its slime global layer coats every object)")
    ap.add_argument("--no-locations", action="store_true",
                    help="no Nirn planet / surface / orbit locations, no landing or map marker")
    ap.add_argument("--marker-name", default="Skyrim", help="the map marker's name")
    ap.add_argument("--slot", type=int, default=30, help="planet slot in the star system (unused by vanilla)")
    ap.add_argument("--orbit-scale", type=float, default=1.3, help="orbit distances x this (away from the template)")
    a = ap.parse_args(argv)
    prm = json.load(open(os.path.join(a.staging, "overlays_params.json"), encoding="utf-8"))
    if not prm.get("mars"):
        sys.exit("the build has no planet plugin (overlays_params.json 'mars'): build the terrain with --planet")
    plugin = os.path.join(a.staging, prm["mars"]["plugin"])
    terrain = os.path.join(a.staging, prm["plugin"])
    masters = masters_of(plugin)
    if [m.lower() for m in masters] != ["starfield.esm", prm["plugin"].lower()]:
        sys.exit(f"{plugin}: unexpected masters {masters}")
    worlds = []
    with fo4land.Plugin(terrain) as p:
        for ov in prm["overlays"]:
            wfid, _s, _e, _f = p.find_world(ov["world"])
            worlds.append((float(ov["latitude"]), float(ov["longitude"]), wfid))   # terrain plugin = master index 1
    own = len(masters) << 24
    fid = own | 0x800
    ocean_fid, before = OCEAN, []
    with fo4land.Plugin(a.sf_esm) as p:
        _off, header, subs = find_record(p.buf, p.body, b"PNDT", a.template)
        if not a.keep_ocean_coating:
            ocean_fid = own | 0x801
            _o, bh, bsubs = find_record(p.buf, p.body, b"BIOM", "OceanLife04")
            before = [(b"BIOM", bh, clean_biome(bsubs, f"{a.name}OceanNoCoating"), ocean_fid)]
    only = int(a.only_biome, 16) if a.only_biome else None
    new = planet_subrecords(subs, a.name, f"{a.name}PlanetData", a.radius_km, a.slot, worlds,
                            {only: 100.0} if only else {OCEAN: 95.0, LAND: 5.0}, a.orbit_scale,
                            remap=None if only else {OCEAN: ocean_fid})
    after, n_extra, top_fid, notes = b"", 0, 0, []
    if not a.no_locations:
        loc, surf, orb = own | 0x802, own | 0x803, own | 0x804
        with fo4land.Plugin(a.sf_esm) as p:
            jl = {e: find_record(p.buf, p.body, b"LCTN", e) for e in JEMISON_LOCS}
        before += [(b"LCTN", jl[JEMISON_LOCS[0]][1],
                    location_subrecords(jl[JEMISON_LOCS[0]][2], f"S{a.name}_P{a.name}", a.name, slot=a.slot), loc),
                   (b"LCTN", jl[JEMISON_LOCS[1]][1],
                    location_subrecords(jl[JEMISON_LOCS[1]][2], f"S{a.name}_P{a.name}_Surface", a.name,
                                        parent=loc, slot=a.slot), surf),
                   (b"LCTN", jl[JEMISON_LOCS[2]][1],
                    location_subrecords(jl[JEMISON_LOCS[2]][2], f"S{a.name}_P{a.name}_Orbit", a.name,
                                        parent=loc, slot=a.slot), orb)]
        with fo4land.Plugin(terrain) as p:
            for ov in prm["overlays"]:                   # our world's location moves under Nirn's surface
                _o, lh, lsubs = find_record(p.buf, p.body, b"LCTN", ov["location"])
                lfid = struct.unpack_from("<I", lh, 12)[0]
                before.append((b"LCTN", lh, [(s, struct.pack("<I", surf) if s == b"PNAM" else d) for s, d in lsubs], lfid))
            wrld, cell = world_and_persistent_cell(p.buf, p.body, prm["overlays"][0]["world"])
        site = prm.get("landing")
        if site:
            land_fid, mark_fid = own | 0x810, own | 0x811
            hdr = cell[0][:8] + struct.pack("<I", PERSISTENT) + cell[0][12:]
            pos = (site["x"], site["y"], site["z"])
            refs = [record_bytes(b"REFR", hdr, ref_subrecords(f"SKY_{a.name}LandingMarker", LANDING_MARKER, pos), land_fid),
                    record_bytes(b"REFR", hdr, ref_subrecords(f"SKY_{a.name}MapMarker", MAP_MARKER,
                                                             (pos[0], pos[1], pos[2] + 2.0),
                                                             map_marker_extra(a.marker_name, land_fid)), mark_fid)]
            after = world_group(wrld, cell, refs)
            n_extra, top_fid = 4, mark_fid
            notes.append(f"landing marker + map marker '{a.marker_name}' at ({site['x']:g}, {site['y']:g}, "
                         f"{site['z']:g}) in {prm['overlays'][0]['world']}'s persistent cell")
        else:
            notes.append("no landing site in overlays_params.json (rebuild the terrain with today's "
                         "make_skyrim_overlay.py): no landing / map marker")
        notes.insert(0, f"locations S{a.name}_P{a.name} / _Surface / _Orbit (slot {a.slot}); "
                        f"{', '.join(o['location'] for o in prm['overlays'])} now under S{a.name}_P{a.name}_Surface")
    n = write_plugin(plugin, header, new, fid, before, after, n_extra, top_fid)
    for t in notes:
        print(t)
    # where the engine looks: biomemaps\<planet>.biom for Starfield.esm's planets (Jemison Biome Overhaul replaces
    # jemison.biom there); for a planet defined in an ESM, biomemaps\<plugin>.esm\<planet>.biom (SFStarEditor's
    # README, unverified there). The first Nirn tests with only the root file showed no sign of it (owner: a frozen-only
    # map gave no snow). Both are written.
    data = biome_map(0.0, land=only, ocean=only) if only else biome_map(a.land_px, ocean=ocean_fid)
    root = os.path.join(a.staging, "Data", "planetdata", "biomemaps")
    paths = [os.path.join(root, f"{a.name.lower()}.biom"), os.path.join(root, prm["mars"]["plugin"], f"{a.name.lower()}.biom")]
    for bm in paths:
        os.makedirs(os.path.dirname(bm), exist_ok=True)
        with open(bm, "wb") as fh:
            fh.write(data)
    bm = " and ".join(paths)
    px_km = math.pi / 2 * a.radius_km / 128
    print(f"{prm['mars']['plugin']}: new planet {a.name} ({fid:08X}, {n:,} bytes of fields, cloned from {a.template}), "
          f"radius {a.radius_km:g} km, slot {a.slot}, master worldspaces {[(round(la, 4), round(lo, 4), hex(f)) for la, lo, f in worlds]}")
    if before:
        print(f"ocean biome: {a.name}OceanNoCoating ({ocean_fid:08X}), OceanLife04 without its EFSD global layer "
              f"(gl_slimeocean01: the underwater / mossy coat)")
    print(f"biome map {bm}: land disc {a.land_px:g} px (~{a.land_px * px_km:.1f} km, one pixel ~{px_km:.2f} km) at both "
          f"poles, ocean elsewhere")
    if a.land_px > 0 and any(abs(abs(la) - math.pi / 2) > 0.01 for la, _lo, _f in worlds):
        print("WARNING: the overlay is not on a pole; the land disc is at the poles (rebuild the terrain with "
              "--latlon -1.5707963 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
