"""Several Skyrim worldspaces on one planet: the installed Tamriel plus the walled cities (owner 2026-11-10: "get the
worldspace for the cities like Whiterun, Solitude, Windhelm"; chose "separate, like Skyrim": each city its own space
behind its gates). docs/terrain/skyrim-cities.md.

Every terrain experiment so far registered itself by overriding one planet record (PNDT CNAM: its master
worldspaces), so two builds could not be installed together. This writes ONE registration plugin that loads last:

* an override of the planet record of the main build (the planet plugin make_planet.py wrote, e.g. Nirn in
  SkyrimTerrainTamriel_Mars.esm) with its CNAM entries kept and one entry per city world appended (latitude f64,
  longitude f64, WRLD FormID; docs/terrain/overlay-records.md section 5) - each city away from Tamriel, by default
  --spacing radians of longitude apart at Tamriel's latitude, so the overlays never overlap;
* an override of each city's location (LCTN, the one its WRLD names) with its parent (PNAM) set to the planet's
  surface location (the planet plugin's *_Surface LCTN), as make_planet.py does for Tamriel's.

Masters: the planet plugin's masters, the planet plugin, then each city's terrain plugin (built --no-mars, e.g.
make_skyrim_overlay.py build --world-edid WhiterunWorld --frame local --like <Tamriel staging> --no-mars).

    python -I scripts\\terrain\\register_worlds.py --main C:\\Modding\\staging\\skyrim_all ^
        --world C:\\Modding\\staging\\sky_whiterunworld [--world ...] --out C:\\Modding\\staging\\sky_cities_register

Unverified in game: a planet with several master worldspaces of ours (vanilla Mars lists 10), reaching a city by coc
(gates come later).
"""
import argparse
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land, sfplugin  # noqa: E402

PLUGIN = "SkyrimWorlds_Register.esm"


def masters_of(path):
    """The plugin's master file names (TES4 MAST), as written."""
    with fo4land.Plugin(path) as p:
        return [fo4land.zstring(bytes(d)) for s, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, 0))
                if s == b"MAST"]


def load_params(staging):
    path = os.path.join(staging, "overlays_params.json")
    if not os.path.isfile(path):
        sys.exit(f"{path} missing (a staged overlay build)")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def world_of(staging):
    """(terrain plugin file name, world FormID local to it, location EditorID) of a staged build."""
    prm = load_params(staging)
    path = os.path.join(staging, "formids.json")
    if not os.path.isfile(path):
        sys.exit(f"{path} missing: run the objects stage with --sf-esm (TerrainOverlays) first")
    with open(path, encoding="utf-8") as fh:
        ids = json.load(fh)
    return ids["plugin"], int(ids["world_form_id"], 16), prm["overlays"][0].get("location", "")


def cnam_entries(d):
    return [struct.unpack_from("<ddI", d, i) for i in range(0, len(d) - len(d) % 20, 20)]


def remap(fid, own_from, own_to):
    """A FormID written in a plugin whose own records have index own_from, as seen from ours (index own_to); master
    indices below own_from are kept (our master list starts with Starfield.esm, as every build's does)."""
    return (own_to << 24) | (fid & 0xFFFFFF) if fid >> 24 == own_from else fid


def plan(main, worlds, spacing=0.02, places=None):
    """The registration: (records, masters, report). main / worlds: staging folders; places: per world an optional
    (lat, lon)."""
    prm = load_params(main)
    if not prm.get("mars"):
        sys.exit(f"{main}: no planet plugin (overlays_params.json 'mars')")
    planet_plugin = os.path.join(main, prm["mars"]["plugin"])
    pm = masters_of(planet_plugin)
    masters = list(pm) + [os.path.basename(planet_plugin)]
    p_index = len(pm)
    recs_p = sfplugin.records(planet_plugin, [b"PNDT", b"LCTN"])
    planets = [r for r in recs_p if r[0] == b"PNDT" and any(s == b"CNAM" for s, _d in r[2])]
    if not planets:
        sys.exit(f"{planet_plugin}: no planet record with master worldspaces")
    t, h, subs, p_fid = planets[0]
    entries = cnam_entries(next(d for s, d in subs if s == b"CNAM"))
    lat0, lon0 = entries[0][0], entries[0][1]
    surface = next((fid for tt, _h, s, fid in recs_p if tt == b"LCTN" and sfplugin.edid(s).endswith("_Surface")
                    and fid >> 24 == p_index), None)
    out, rep = [], {"planet": f"{sfplugin.edid(subs)} {p_fid:08X}", "planet_plugin": os.path.basename(planet_plugin),
                    "kept_entries": len(entries), "worlds": []}
    new_entries = list(entries)
    for k, w in enumerate(worlds):
        plugin, w_fid, loc_edid = world_of(w)
        if plugin.lower() in (m.lower() for m in masters):
            sys.exit(f"{plugin} twice (or the main build's)")
        masters.append(plugin)
        idx = len(masters) - 1
        lat, lon = (places[k] if places and k < len(places) and places[k] else
                    (lat0, math.remainder(lon0 + spacing * (k + 1), 2 * math.pi)))
        wid = (idx << 24) | (w_fid & 0xFFFFFF)
        new_entries.append((lat, lon, wid))
        wrep = {"plugin": plugin, "world": f"{wid:08X}", "latitude": round(lat, 6), "longitude": round(lon, 6)}
        path = os.path.join(w, plugin)
        if not os.path.isfile(path):
            sys.exit(f"{path} missing")
        own = len(masters_of(path))
        loc = next((r for r in sfplugin.records(path, [b"LCTN"]) if sfplugin.edid(r[2]) == loc_edid), None)
        if loc is not None and surface is not None:
            lsubs = []
            for s, d in loc[2]:
                if s == b"PNAM" and len(d) == 4:
                    d = struct.pack("<I", surface)
                elif s == b"KWDA":
                    d = b"".join(struct.pack("<I", remap(v, own, idx)) for (v,) in struct.iter_unpack("<I", d))
                lsubs.append((s, d))
            out.append((b"LCTN", loc[1], lsubs, remap(loc[3], own, idx)))
            wrep["location"] = f"{loc_edid} -> parent {surface:08X}"
        else:
            wrep["location"] = "not changed (no LCTN of that name, or no *_Surface location in the planet plugin)"
        rep["worlds"].append(wrep)
    data = b"".join(struct.pack("<ddI", *e) for e in new_entries)
    psubs = [(s, data if s == b"CNAM" else d) for s, d in subs]
    out.insert(0, (t, h, psubs, p_fid))
    rep["entries"] = len(new_entries)
    return out, masters, rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--main", required=True, help="the installed main build (Tamriel) with its planet plugin")
    ap.add_argument("--world", action="append", required=True, help="a staged city build (repeatable)")
    ap.add_argument("--out", required=True, help="folder for the registration plugin")
    ap.add_argument("--spacing", type=float, default=0.02, help="radians of longitude between neighbours")
    ap.add_argument("--plugin", default=PLUGIN)
    a = ap.parse_args(argv)
    recs, masters, rep = plan(a.main, a.world, a.spacing)
    info = sfplugin.header_info(os.path.join(a.main, load_params(a.main)["mars"]["plugin"]))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, a.plugin), "wb") as fh:
        fh.write(sfplugin.build(recs, info, author="Skyrim2Starfield worlds", masters=masters))
    rep.update(plugin=a.plugin, masters=masters)
    with open(os.path.join(a.out, "register_worlds.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    for w in rep["worlds"]:
        print(f"  {w['plugin']}: world {w['world']} at lat {w['latitude']} lon {w['longitude']}; location {w['location']}")
    print(f"-> {os.path.join(a.out, a.plugin)} ({rep['entries']} worlds on {rep['planet']}; load it after "
          f"{', '.join(masters[1:])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
