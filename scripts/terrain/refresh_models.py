"""Put freshly converted models into an already staged exterior without restaging it: copies <work>\\convert\\meshes over
<staging>\\Data\\meshes, only files the staging already has (same names: make_skyrim_objects.py names converted models
by their Skyrim source), so the plugins, FormIDs, grass, LOD, water and the planet stay exactly as installed.

Made for the 2026-11-08 collision fix: the installed exterior (sky_all, converted 2026-10-16) has box collision only;
converting again with --starfield-data gives Skyrim's own collision as native Starfield mesh bodies (collision lives in
the .nif, so meshes are all that change).

    python -I scripts\\terrain\\refresh_models.py --work C:\\Modding\\work\\sky_all --staging C:\\Modding\\staging\\skyrim_all

--dry-run counts what would change. Then reinstall the staging (deploy_skyrim_exterior.py uninstall, install).
"""
import argparse
import filecmp
import json
import os
import shutil
import sys
from collections import Counter


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True, help="make_skyrim_objects.py work folder (convert\\meshes)")
    ap.add_argument("--staging", required=True, help="the staged exterior (Data\\meshes)")
    ap.add_argument("--tree", default="meshes", help="which converted tree to copy (default meshes)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    src = os.path.join(a.work, "convert", a.tree)
    dst = os.path.join(a.staging, "Data", a.tree)
    if not os.path.isdir(src) or not os.path.isdir(dst):
        sys.exit(f"missing {src if not os.path.isdir(src) else dst}")
    n = Counter()
    for root, _dirs, files in os.walk(src):
        for fn in files:
            s = os.path.join(root, fn)
            d = os.path.join(dst, os.path.relpath(s, src))
            if not os.path.exists(d):
                n["not in the staging (left out)"] += 1
                continue
            if filecmp.cmp(s, d, shallow=False):
                n["unchanged"] += 1
                continue
            n["replaced"] += 1
            if not a.dry_run:
                os.remove(d)                     # staging files may be hard links into an older convert folder
                shutil.copy2(s, d)
    kinds = Counter()
    man = os.path.join(a.work, "convert", "manifest.json")
    if os.path.exists(man):
        with open(man, encoding="utf-8") as fh:
            for it in json.load(fh).get("items", []):
                c = it.get("collision_report") or {}
                kinds[c.get("source", "none") + ("/" + c["method"] if c.get("method") else "")] += 1
    print(("would replace" if a.dry_run else "replaced") + f" {n['replaced']:,} files; unchanged {n['unchanged']:,}; "
          f"not in the staging {n['not in the staging (left out)']:,}; collision of the converted models: {dict(kinds)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
