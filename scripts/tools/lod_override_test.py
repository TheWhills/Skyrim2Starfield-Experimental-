"""LOD diagnostic in a vanilla world whose distant composites draw (New Atlantis by default): puts a Gagarin crane in
place of one vanilla object's composite LOD files (every level and block), into a staged build's Data, so the next
install packs them into our archive at the vanilla paths. In game, look at that object from far away (outside the
loaded cells, over 1 km): cranes standing above it mean the engine reads composite LOD from a plugin's archive and
draws our NIF / mesh layout, so the Skyrim world's problem is in how that world is set up; no cranes mean composite
LOD is not read from our archive at all (or not our layout).

    python -I scripts\\tools\\lod_override_test.py --sf-data "<Starfield>\\Data" --out C:\\Modding\\staging\\skyrim_all
    python -I scripts\\tools\\lod_override_test.py --out C:\\Modding\\staging\\skyrim_all --remove

Then uninstall / install as usual. --prefix picks the object (default na_lod_apollotower, New Atlantis's Apollo tower).
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2, skyrimlod  # noqa: E402

MANIFEST = "lod_override_test.json"           # in <out>\Data's root (not packed)


def remove(data):
    mf = os.path.join(data, MANIFEST)
    if not os.path.isfile(mf):
        return 0
    files = json.load(open(mf, encoding="utf-8"))
    for rel in files:
        p = os.path.join(data, *rel.split("/"))
        if os.path.isfile(p):
            os.remove(p)
    os.remove(mf)
    return len(files)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="the staged build (its Data folder gets the files)")
    ap.add_argument("--sf-data", help="Starfield Data folder (read-only)")
    ap.add_argument("--world", default="newatlantis", help="composite folder (lowercase world EditorID)")
    ap.add_argument("--prefix", default="na_lod_apollotower", help="composite file name prefix (the LOD layer)")
    ap.add_argument("--remove", action="store_true", help="remove what an earlier run wrote")
    a = ap.parse_args(argv)
    data = os.path.join(a.out, "Data")
    n = remove(data)
    if a.remove:
        print(f"removed {n} files")
        return 0
    if not a.sf_data:
        sys.exit("--sf-data is required")
    found = sorted(glob.glob(os.path.join(a.sf_data, "Starfield - *.ba2")))
    # the patch archive overrides the base LOD archive; then the base one; then the rest (crane meshes)
    found.sort(key=lambda p: (0 if "lodmeshespatch" in p.lower() else 1 if "lodmeshes" in p.lower() else 2, p))
    arcs = {}

    def arc(p):
        if p not in arcs:
            try:
                arcs[p] = ba2.Ba2(p)
            except Exception:                            # noqa: BLE001 (archives we cannot index)
                arcs[p] = None
        return arcs[p]

    def read(name):
        for p in found:
            x = arc(p)
            if x is not None and x.find(name) is not None:
                return x.read(name)
        raise FileNotFoundError(name)
    want = f"meshes/lod/generated/composite/{a.world.lower()}/{a.prefix.lower()}_"
    targets, seen = [], set()
    for p in found[:2]:
        x = arc(p)
        if x is None:
            continue
        for name in x.names:
            k = name.replace("\\", "/").lower()
            if k.startswith(want) and k.endswith(".nif") and k not in seen:
                seen.add(k)
                targets.append((name, x.read(name)))
    if not targets:
        sys.exit(f"no {want}*.nif in {', '.join(os.path.basename(p) for p in found[:2])}")
    files = skyrimlod.override_test(data, targets, read)
    with open(os.path.join(data, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(files, fh)
    print(f"{len(targets)} vanilla composites of {a.prefix} ({a.world}) replaced by cranes in {data}; "
          f"install, then look at it from over 1 km away")
    return 0


if __name__ == "__main__":
    sys.exit(main())
