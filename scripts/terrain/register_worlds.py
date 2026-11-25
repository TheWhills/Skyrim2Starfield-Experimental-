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
sys.path.insert(0, HERE)

from fo4sf import fo4land, sfplugin, worldgates  # noqa: E402
import make_planet  # noqa: E402

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
    # only the master-worldspace list: Nirn's PNDT (make_planet.py) has a second CNAM, 1 byte, in another component
    # (2026-11-25: the old code wrote the list over both)
    k = next(i for i, (s, _d) in enumerate(subs) if s == b"CNAM")
    psubs = list(subs)
    psubs[k] = (b"CNAM", data)
    out.insert(0, (t, h, psubs, p_fid))
    rep["entries"] = len(new_entries)
    return out, masters, rep


# ------------------------------------------------------------------------------------------------------------ gates
def _ref_with_place(path, lid):
    """(flags, subs) of the plugin's own reference lid where it stands: a static already hidden in place (Initially
    Disabled, sunk) is read from the plugin's .before_ref_overrides backup instead. None if neither has it."""
    for cand in (path, path + ".before_ref_overrides"):
        if os.path.isfile(cand):
            got = worldgates.placed_refs(cand, [lid]).get(lid)
            if got and not got[1] & worldgates.DISABLED:
                return got[1], got[2]
    return None


def _stat(path, fid):
    return next((r for r in sfplugin.records(path, [b"STAT"]) if r[3] == fid), None)


def _world_and_cell(path, edid):
    with fo4land.Plugin(path) as p:
        return make_planet.world_and_persistent_cell(p.buf, p.body, edid)


def plan_gates(main, worlds, masters, esm, main_world="Tamriel"):
    """Load doors between the main build's world and each city world, from Skyrim's door pairs (worldgates).
    masters: the registration plugin's masters (plan()); our new records follow them. Returns (DOOR records, the WRLD
    group bytes, its record count, its FormIDs, hide list, report)."""
    prm = load_params(main)
    with open(os.path.join(main, "formids.json"), encoding="utf-8") as fh:
        mids = json.load(fh)
    mov = prm["overlays"][0]
    m_plugin = os.path.join(main, mids["plugin"])
    m_last = os.path.join(main, prm["mars"]["plugin"]) if prm.get("mars") else m_plugin
    own = len(masters)
    new_ids = iter(range(10 ** 6))
    door_recs, door_base, hide, rep = [], {}, [], []
    main_refs, worlds_out = [], []
    for w in worlds:
        wp = load_params(w)
        cov = wp["overlays"][0]
        with open(os.path.join(w, "formids.json"), encoding="utf-8") as fh:
            cids = json.load(fh)
        c_plugin = os.path.join(w, cids["plugin"])
        idx = masters.index(cids["plugin"])
        with open(os.path.join(w, "skyrim_source.json"), encoding="utf-8") as fh:
            city_edid = json.load(fh)["summary"]["world"]
        pairs = worldgates.skyrim_gates(esm, main_world, city_edid)
        city_refs = []
        for pr in pairs:
            gm, gc = pr["main"], pr["city"]
            ml, cl = mids["refs"].get(gm["src"]), cids["refs"].get(gc["src"])
            entry = {"city": city_edid, "main_door": gm["src"], "city_door": gc["src"], "model": gm["edid"]}
            if ml is None or cl is None:
                entry["skipped"] = "a static of the pair is not placed (" + ("main" if ml is None else "city") + ")"
                rep.append(entry)
                continue
            ml, cl = int(ml, 16), int(cl, 16)
            got_m, got_c = _ref_with_place(m_plugin, ml), _ref_with_place(c_plugin, cl)
            if got_m is None or got_c is None:
                sys.exit(f"gate {gm['src']} / {gc['src']}: static reference not found standing in its plugin")
            dm, dc = dict(got_m[1])[b"DATA"][:24], dict(got_c[1])[b"DATA"][:24]
            m_base = struct.unpack("<I", dict(got_m[1])[b"NAME"])[0]
            stat = _stat(m_plugin, m_base)
            if stat is None:
                sys.exit(f"gate {gm['src']}: its base {m_base:08X} is not a STAT of {mids['plugin']}")
            fids = {}
            for side, name in (("to_city", cov.get("name") or city_edid), ("to_main", mov.get("name") or main_world)):
                key = (stat[3], name)
                if key not in door_base:
                    fid = sfplugin.new_form_id(next(new_ids), own)
                    edid = f"SKY_Gate{name.replace(' ', '')}_{sfplugin.edid(stat[2]).replace('SKY_', '')}"[:200]
                    door_recs.append((b"DOOR", stat[1], worldgates.door_record(stat[2], edid, name), fid))
                    door_base[key] = fid
                fids[side] = door_base[key]
            f_main, f_city = sfplugin.new_form_id(next(new_ids), own), sfplugin.new_form_id(next(new_ids), own)
            hdr = stat[1][:8] + struct.pack("<I", worldgates.PERSISTENT) + stat[1][12:]
            main_refs.append(sfplugin.record_bytes(b"REFR", hdr, worldgates.door_ref_subs(
                fids["to_city"], dm, worldgates.xtel(f_city, worldgates.to_local(gm["xtel"]["pos"], cov),
                                                    gm["xtel"]["rot"], gm["xtel"]["flags"])), f_main))
            city_refs.append(sfplugin.record_bytes(b"REFR", hdr, worldgates.door_ref_subs(
                fids["to_main"], dc, worldgates.xtel(f_main, worldgates.to_local(gc["xtel"]["pos"], mov),
                                                    gc["xtel"]["rot"], gc["xtel"]["flags"])), f_city))
            hide += [{"plugin": mids["plugin"], "local_id": "%06X" % ml, "data": worldgates.sunk(dm).hex(),
                      "original": dm.hex()},
                     {"plugin": cids["plugin"], "local_id": "%06X" % cl, "data": worldgates.sunk(dc).hex(),
                      "original": dc.hex()}]
            entry.update(main_ref="%08X" % f_main, city_ref="%08X" % f_city,
                         main_static=f"{mids['plugin']}:{ml:06X}", city_static=f"{cids['plugin']}:{cl:06X}",
                         lands_in_city=[round(v, 2) for v in worldgates.to_local(gm["xtel"]["pos"], cov)],
                         lands_in_main=[round(v, 2) for v in worldgates.to_local(gc["xtel"]["pos"], mov)])
            rep.append(entry)
        if city_refs:
            (wh, wsubs, wfid), (ch, csubs, cfid) = _world_and_cell(c_plugin, cov["world"])
            nm = worldgates.n_masters(c_plugin)
            worlds_out.append(((wh, worldgates.remap_world_subs(wsubs, nm, idx), worldgates.remap(wfid, nm, idx)),
                               (ch, worldgates.remap_world_subs(csubs, nm, idx), worldgates.remap(cfid, nm, idx)),
                               city_refs))
    tail, count, tail_fids = b"", 0, []
    if main_refs:
        (wh, wsubs, wfid), cell = _world_and_cell(m_last, mov["world"])
        # the main world's records keep their master indices: our master list starts with the planet plugin's
        main_w = ((wh, [(s, d) for s, d in wsubs if s not in (b"OFST", b"CLSZ")], wfid), cell, main_refs)
        allw = [main_w] + worlds_out
        tail = worldgates.world_groups(allw)
        count = sum(2 + len(r) for _w, _c, r in allw)
        tail_fids = [sfplugin.new_form_id(i, own) for i in range(next(new_ids))]
    return door_recs, tail, count, tail_fids, hide, rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--main", required=True, help="the installed main build (Tamriel) with its planet plugin")
    ap.add_argument("--world", action="append", required=True, help="a staged city build (repeatable)")
    ap.add_argument("--out", required=True, help="folder for the registration plugin")
    ap.add_argument("--spacing", type=float, default=0.02, help="radians of longitude between neighbours")
    ap.add_argument("--plugin", default=PLUGIN)
    ap.add_argument("--skyrim", default="", help="Skyrim.esm: also the gates (load doors both ways, as Skyrim pairs "
                    "them) between the main world and each city world (fo4sf.worldgates)")
    a = ap.parse_args(argv)
    recs, masters, rep = plan(a.main, a.world, a.spacing)
    tail, count, tail_fids = b"", 0, []
    if a.skyrim:
        doors, tail, count, tail_fids, hide, grep_ = plan_gates(a.main, a.world, masters, a.skyrim)
        recs = recs + doors
        rep.update(gates=grep_, hide=hide)
        for g in grep_:
            print(f"  gate {g['city']}: {g['main_door']} <-> {g['city_door']} ({g['model']}): " +
                  (g["skipped"] if "skipped" in g else
                   f"doors {g['main_ref']} / {g['city_ref']}, lands at {g['lands_in_city']} in the city, "
                   f"{g['lands_in_main']} outside"))
        if not any("main_ref" in g for g in grep_):
            print("  no gate linked")
    info = sfplugin.header_info(os.path.join(a.main, load_params(a.main)["mars"]["plugin"]))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, a.plugin), "wb") as fh:
        fh.write(sfplugin.build(recs, info, author="Skyrim2Starfield worlds", masters=masters,
                                tail=tail, tail_records=count, tail_fids=tail_fids))
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
