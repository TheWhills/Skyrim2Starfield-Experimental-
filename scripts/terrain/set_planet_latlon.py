"""Show or move where Skyrim sits on its planet, the latitude / longitude in the planet record's CNAM (master worldspaces),
without rebuilding anything (docs/terrain/skyrim-tamriel.md "Sun path").

The sun's path over a place depends on its latitude: at a pole it circles near the horizon (owner, 2026-11-08: "it
never really gets above you in the sky"); near the equator it climbs high at noon.

    python -I scripts\\terrain\\set_planet_latlon.py --staging C:\\Modding\\staging\\skyrim_all
    python -I scripts\\terrain\\set_planet_latlon.py --staging C:\\Modding\\staging\\skyrim_all --latlon 0.3 0 ^
        --starfield "<Starfield>"

Without --latlon: prints each master worldspace entry (latitude, longitude in radians and degrees) and the planet's
FNAM floats. With --latlon: rewrites the entries of the planet plugin in --staging in place (same size), updates
overlays_params.json (so a later make_planet.py or rebuild keeps the new place), and with --starfield also patches the
installed copy in <Starfield>\\Data when it is the same file as the staged one before the change. Starfield closed.
The planet's own biome map is all ocean on the installed Nirn (--land-px 0), so any latitude has sea round Skyrim;
with a land disc (make_planet.py --land-px > 0) only the poles do.
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402


def cnam_entries(path):
    """[(file offset of the CNAM data, [(lat, lon, world FormID)]), FNAM floats] of the plugin's PNDT records."""
    out = []
    with fo4land.Plugin(path) as p:
        for typ, off, flags, fid in walk(p):
            if typ != b"PNDT":
                continue
            if flags & fo4land.COMPRESSED:
                sys.exit(f"{path}: the planet record is compressed; rebuild it with make_planet.py")
            pos = off + 24
            end = pos + struct.unpack_from("<I", p.buf, off + 4)[0]
            rec = {"form": fid, "cnam": None, "fnam": None}
            while pos + 6 <= end:
                sig, size = bytes(p.buf[pos:pos + 4]), struct.unpack_from("<H", p.buf, pos + 4)[0]
                d = bytes(p.buf[pos + 6:pos + 6 + size])
                if sig == b"CNAM" and rec["cnam"] is None and size % 20 == 0:
                    rec["cnam"] = (pos + 6, [struct.unpack_from("<ddI", d, i) for i in range(0, size, 20)])
                elif sig == b"FNAM" and rec["fnam"] is None and size % 4 == 0:
                    rec["fnam"] = [round(x, 4) for x in struct.unpack(f"<{size // 4}f", d)]
                pos += 6 + size
            out.append(rec)
    return out


def walk(p):
    stack = [(p.body, len(p.buf))]
    while stack:
        s, e = stack.pop()
        for it in fo4land.iter_items(p.buf, s, e):
            if it[0] == "GRUP":
                stack.append((it[1] + 24, it[2]))
            else:
                yield it


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def patch(path, offset, entries):
    with open(path, "r+b") as fh:
        fh.seek(offset)
        fh.write(b"".join(struct.pack("<ddI", la, lo, fid) for la, lo, fid in entries))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", required=True, help="the staged exterior (overlays_params.json, the planet plugin)")
    ap.add_argument("--latlon", type=float, nargs=2, metavar=("LAT", "LON"), help="new place, radians")
    ap.add_argument("--starfield", default="", help="also patch the installed copy in <Starfield>\\Data")
    a = ap.parse_args(argv)
    with open(os.path.join(a.staging, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    if not prm.get("mars"):
        sys.exit("this build has no planet plugin (overlays_params.json 'mars')")
    plugin = os.path.join(a.staging, prm["mars"]["plugin"])
    recs = [r for r in cnam_entries(plugin) if r["cnam"]]
    if not recs:
        sys.exit(f"{plugin}: no planet record with master worldspaces")
    for r in recs:
        for la, lo, fid in r["cnam"][1]:
            print(f"planet {r['form']:08X}: world {fid:08X} at latitude {la:.6f} rad ({math.degrees(la):.2f} deg), "
                  f"longitude {lo:.6f} rad ({math.degrees(lo):.2f} deg)")
        print(f"  FNAM floats {r['fnam']}")
    if not a.latlon:
        return 0
    lat, lon = a.latlon
    if abs(lat) > math.pi / 2 + 1e-9:
        sys.exit("latitude must be within -1.5707963 .. 1.5707963 rad")
    installed = os.path.join(a.starfield, "Data", prm["mars"]["plugin"]) if a.starfield else ""
    same = bool(installed) and os.path.exists(installed) and sha(installed) == sha(plugin)
    if installed and not same:
        print(f"note: {installed} is not the staged file (missing or different); not patched - reinstall instead")
    for r in recs:
        off, entries = r["cnam"]
        new = [(lat, lon, fid) for _la, _lo, fid in entries]
        patch(plugin, off, new)
        if same:
            patch(installed, off, new)
    for o in prm["overlays"]:
        o["latitude"], o["longitude"] = lat, lon
    with open(os.path.join(a.staging, "overlays_params.json"), "w", encoding="utf-8") as fh:
        json.dump(prm, fh, indent=1)
    print(f"moved to latitude {lat} rad ({math.degrees(lat):.2f} deg), longitude {lon} rad: {plugin}"
          + (f" and {installed}" if same else "") + "; overlays_params.json updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
