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


def planet_subrecords(subs, name, edid, radius_km, slot, worlds, biomes, orbit_scale):
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
            d = d[:4] + struct.pack("<f", float(biomes[fid])) + d[8:]
        out.append((s, d))
    have = {struct.unpack_from("<I", d)[0] for s, d in out if s == b"PPBD"}
    missing = set(biomes) - have
    if missing:
        raise ValueError(f"the template planet has no PPBD entry for biomes {sorted(hex(m) for m in missing)}")
    return out


def biome_map(land_px: float, land=LAND, ocean=OCEAN, size=256) -> bytes:
    """Both pole maps: a land disc of radius land_px pixels round the centre, ocean elsewhere."""
    c = (size - 1) / 2.0
    ids = [land if math.hypot(x - c, y - c) <= land_px else ocean for y in range(size) for x in range(size)]
    one = struct.pack("<III", size, size, size * size) + struct.pack(f"<{size * size}I", *ids) + \
        struct.pack("<I", size * size) + bytes([RESOURCE_NONE]) * (size * size)
    return struct.pack("<HI", 0x105, 2) + struct.pack("<2I", ocean, land) + struct.pack("<I", 2) + one + one


def write_plugin(path, planet_header: bytes, subs, fid: int):
    """Replace the planet plugin's content: its TES4 header (masters as TerrainOverlays wrote them) and one PNDT group
    holding the new planet."""
    raw = open(path, "rb").read()
    tes4_size = REC.unpack_from(raw, 0)[1]
    tes4 = bytearray(raw[:24 + tes4_size])
    data = b"".join(s + struct.pack("<H", len(d)) + d for s, d in subs)
    _t, _size, flags, _fid = REC.unpack_from(planet_header, 0)
    rec = struct.pack("<4sIII", b"PNDT", len(data), flags & ~fo4land.COMPRESSED, fid) + planet_header[16:24] + data
    grp = struct.pack("<4sI4si", b"GRUP", 24 + len(rec), b"PNDT", 0) + bytes(8) + rec
    # TES4 HEDR: version f32, record count u32, next object id u32
    subs4 = list(fo4land.iter_subrecords(bytes(tes4[24:])))
    off = 24
    for s, d in subs4:
        if s == b"HEDR" and len(d) >= 12:
            struct.pack_into("<II", tes4, off + 6 + 4, 1, (fid & 0xFFFFFF) + 1)
        off += 6 + len(d)
    with open(path, "wb") as fh:
        fh.write(bytes(tes4) + grp)
    return len(data)


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
    with fo4land.Plugin(a.sf_esm) as p:
        _off, header, subs = find_record(p.buf, p.body, b"PNDT", a.template)
    new = planet_subrecords(subs, a.name, f"{a.name}PlanetData", a.radius_km, a.slot, worlds,
                            {OCEAN: 95.0, LAND: 5.0}, a.orbit_scale)
    fid = (len(masters) << 24) | 0x800
    n = write_plugin(plugin, header, new, fid)
    bm = os.path.join(a.staging, "Data", "planetdata", "biomemaps", f"{a.name.lower()}.biom")
    os.makedirs(os.path.dirname(bm), exist_ok=True)
    with open(bm, "wb") as fh:
        fh.write(biome_map(a.land_px))
    px_km = math.pi / 2 * a.radius_km / 128
    print(f"{prm['mars']['plugin']}: new planet {a.name} ({fid:08X}, {n:,} bytes of fields, cloned from {a.template}), "
          f"radius {a.radius_km:g} km, slot {a.slot}, master worldspaces {[(round(la, 4), round(lo, 4), hex(f)) for la, lo, f in worlds]}")
    print(f"biome map {bm}: land disc {a.land_px:g} px (~{a.land_px * px_km:.1f} km, one pixel ~{px_km:.2f} km) at both "
          f"poles, ocean elsewhere")
    if any(abs(abs(la) - math.pi / 2) > 0.01 for la, _lo, _f in worlds):
        print("WARNING: the overlay is not on a pole; the land disc is at the poles (rebuild the terrain with "
              "--latlon -1.5707963 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
