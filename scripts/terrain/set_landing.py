"""Move the ship's landing spot (and the "Skyrim" map marker) on Nirn to another Skyrim place, without rebuilding
anything: the flattest dry square near the place (fo4sf.skyrimsite.flat_site on Skyrim's LAND heights, as the
overlay build picks it near the arrival) goes into overlays_params.json "landing", and the planet plugin's landing
marker and map marker (make_planet.py's SKY_<name>LandingMarker / SKY_<name>MapMarker) are moved there in place.

    python -I scripts\\terrain\\set_landing.py --skyrim "$sky\\Skyrim.esm" --staging C:\\Modding\\staging\\skyrim_all ^
        --location ThroatoftheWorldLocation --starfield $sf

2026-11-15 (owner): "could we change our landing spot on the planet to the Throat of the World".

--location: a Skyrim location's EditorID (its world location marker, LCTN MNAM, is the place); --at X Y: Skyrim world
units instead. --radius: how far from the place to look (metres; the summit is steep, so a smaller radius keeps the
pad near it at the cost of a rougher square: the result prints the square's height range). Without --apply only
prints what it would do. Starfield closed. The staged planet plugin is patched (the terrain build never reads it), and
with --starfield the installed copy, when it was the same file as the staged one.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402

UNITS_PER_M = 70.0
MAP_MARKER_LIFT = 2.0               # make_planet.py puts the map marker 2 m above the landing marker


def place_of_location(sky, edid):
    """(x, y, z) Skyrim units of a location's world location marker (LCTN MNAM -> REFR DATA), or a SystemExit naming
    similar locations."""
    fid = sky.find_edid(b"LCTN", edid)
    if fid is None:
        import re
        words = [w.lower() for w in re.findall(r"[A-Z][a-z]+|[a-z]{4,}", edid) if w.lower() != "location"]
        near = sorted(e for e in (sky.edid(f) for f in sky.by_type.get(b"LCTN", [])) if e and
                      any(w in e.lower() for w in words if len(w) > 3))
        sys.exit(f"no Skyrim location {edid}" + (f"; similar: {', '.join(near[:20])}" if near else ""))
    mnam = next((struct.unpack_from("<I", d)[0] for s, d in sky.subs(fid) if s == b"MNAM" and len(d) >= 4), None)
    if not mnam:
        sys.exit(f"{edid}: no world location marker (MNAM)")
    data = next((d for s, d in sky.subs(mnam) if s == b"DATA" and len(d) >= 12), None)
    if data is None:
        sys.exit(f"{edid}: its marker {mnam:08X} has no position")
    return struct.unpack_from("<3f", data)


def marker_offsets(path, name):
    """{"landing" | "map": file offset of the DATA field's position} of the planet plugin's two markers."""
    want = {f"SKY_{name}LandingMarker".lower(): "landing", f"SKY_{name}MapMarker".lower(): "map"}
    out = {}
    with fo4land.Plugin(path) as p:
        stack = [(p.body, len(p.buf))]
        while stack:
            s, e = stack.pop()
            for it in fo4land.iter_items(p.buf, s, e):
                if it[0] == "GRUP":
                    stack.append((it[1] + 24, it[2]))
                    continue
                typ, off, flags, _fid = it
                if typ != b"REFR" or flags & fo4land.COMPRESSED:
                    continue
                size = struct.unpack_from("<I", p.buf, off + 4)[0]
                q, end, edid, data_at = off + 24, off + 24 + size, None, None
                while q + 6 <= end:
                    sig, n = bytes(p.buf[q:q + 4]), struct.unpack_from("<H", p.buf, q + 4)[0]
                    if sig == b"EDID":
                        edid = bytes(p.buf[q + 6:q + 6 + n]).rstrip(b"\0").decode("latin-1").lower()
                    elif sig == b"DATA" and n >= 24:
                        data_at = q + 6
                    q += 6 + n
                if edid in want and data_at is not None:
                    out[want[edid]] = data_at
    return out


def patch_markers(path, offsets, pos):
    with open(path, "r+b") as fh:
        for kind, at in offsets.items():
            fh.seek(at)
            z = pos[2] + (MAP_MARKER_LIFT if kind == "map" else 0.0)
            fh.write(struct.pack("<3f", pos[0], pos[1], z))


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()



def plugins_current(staging, prm):
    """Touch the staged plugins after overlays_params.json is rewritten (2026-11-18, owner: deploy_skyrim_exterior.py
    refused the exterior as "older than overlays_params.json", its guard against a failed plugin build): this tool
    patched them in place, so they are as current as the params."""
    for p in [prm.get("plugin")] + [(prm.get("mars") or {}).get("plugin")]:
        if p and os.path.isfile(os.path.join(staging, p)):
            os.utime(os.path.join(staging, p))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--staging", required=True, help="the staged exterior (overlays_params.json, the planet plugin)")
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--location", help="a Skyrim location's EditorID, e.g. ThroatoftheWorldLocation")
    where.add_argument("--at", type=float, nargs=2, metavar=("X", "Y"), help="Skyrim world units")
    ap.add_argument("--radius", type=float, nargs="+", default=[150.0, 300.0, 600.0],
                    help="metres around the place to search; several print one candidate each (default 150 300 600); "
                         "--apply takes one")
    ap.add_argument("--name", default="Nirn", help="the planet's name in make_planet.py's marker EditorIDs")
    ap.add_argument("--starfield", default="", help="also patch the installed planet plugin in <Starfield>\\Data")
    ap.add_argument("--apply", action="store_true", help="write the change (otherwise only print it)")
    a = ap.parse_args(argv)
    prm_path = os.path.join(a.staging, "overlays_params.json")
    with open(prm_path, encoding="utf-8") as fh:
        prm = json.load(fh)
    o = prm["overlays"][0]
    origin = tuple(float(v) for v in o.get("origin_cw_m", [0, 0]))
    from fo4sf import packages, skyrimland, skyrimsite
    if a.location:
        sky = packages.Index(a.skyrim)
        try:
            x, y, z_units = place_of_location(sky, a.location)
        finally:
            sky.close()
        label = a.location
    else:
        x, y = a.at
        z_units = None
        label = f"({x:g}, {y:g})"
    near = (x / UNITS_PER_M - origin[0], y / UNITS_PER_M - origin[1])
    if a.apply and len(a.radius) != 1:
        sys.exit("--apply takes one --radius (the candidate to use)")
    land = skyrimland.SkyrimLand(a.skyrim, o.get("world_edid") or skyrimland.WORLD)
    offset = o.get("height_offset_m", 0.0)
    place_z = None if z_units is None else z_units / UNITS_PER_M + offset
    print(f"{label}: Skyrim ({x:g}, {y:g}) = overlay ({near[0]:.1f}, {near[1]:.1f}) m"
          + ("" if place_z is None else f", height {place_z:.1f} m"))
    site = None
    for r in a.radius:
        site = skyrimsite.flat_site(land.grids, land.water, land.default_water, origin, offset, near, radius_m=r)
        if not site:
            print(f"  within {r:g} m: no dry 80 m square")
            continue
        drop = "" if place_z is None else f", {place_z - site['z']:.0f} m below the place"
        print(f"  within {r:g} m: pad at ({site['x']:g}, {site['y']:g}, {site['z']:g}), {site['distance_m']:g} m away"
              f"{drop}, ground range {site['range_m']:g} m over 80 m (Riverwood's pad: 4.8 m)")
    if not site:
        sys.exit(f"no dry 80 m square near {label}: try a larger --radius")
    plugin = os.path.join(a.staging, prm["mars"]["plugin"])
    offs = marker_offsets(plugin, a.name)
    if set(offs) != {"landing", "map"}:
        sys.exit(f"{plugin}: markers found {sorted(offs)}; expected SKY_{a.name}LandingMarker and SKY_{a.name}MapMarker")
    if not a.apply:
        print("(not written: add --apply)")
        return 0
    installed = os.path.join(a.starfield, "Data", os.path.basename(plugin)) if a.starfield else ""
    same = bool(installed) and os.path.isfile(installed) and sha(installed) == sha(plugin)
    pos = (site["x"], site["y"], site["z"])
    patch_markers(plugin, offs, pos)
    print(f"patched {plugin}")
    if installed:
        if same:
            patch_markers(installed, marker_offsets(installed, a.name), pos)
            print(f"patched {installed}")
        else:
            print(f"NOT patched {installed}: not the same file as the staged one; copy the staged one over it")
    prm.setdefault("landing_history", []).append(prm.get("landing"))
    prm["landing"] = dict(site, place=label)
    with open(prm_path, "w", encoding="utf-8") as fh:
        json.dump(prm, fh, indent=1)
    plugins_current(a.staging, prm)
    print(f"overlays_params.json: landing at {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
