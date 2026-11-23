"""Which grass files Starfield ships (read-only survey of the game's archives), 2026-11-22.

Starfield.exe's strings (scripts/re/exe_strings.py, owner's run) name a Skyrim-style grass manager next to the planet
generator: BGSGrassManager with AddCellGrassTask / CellGrass ("AddCellGrass [%i, %i]"), the folders
`meshes\\landscape\\cellgrass\\` and `landscape\\grass\\`, the setting `sCellGrassSubdirectories:Grass`, and GRASS\\
among the archive root folders. Supported hypothesis: some worlds get grass per cell from prebuilt files there (not
from the biome / ground cover route, which grew nothing on our world). This lists every archived file under those
folders (and any path with 'cellgrass' or a top-level grass\\ folder), counts them by folder pattern and archive, and
lists the files naming --world. With --zip it copies a few samples and the full list into a zip outside the repo.

    python -I scripts\\terrain\\cellgrass_survey.py --sf-data "D:\\SteamLibrary\\steamapps\\common\\Starfield\\Data" ^
        --zip C:\\Modding\\work\\cellgrass_survey.zip
"""
import argparse
import glob
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2  # noqa: E402

GRASS_RE = re.compile(r"(^|\\)(grass\\|meshes\\landscape\\(cell)?grass\\|landscape\\grass\\)|cellgrass", re.I)


def is_grass(name: str) -> bool:
    return bool(GRASS_RE.search(name.replace("/", "\\").lstrip("\\")))


def pattern(name: str) -> str:
    """A folder pattern: the first five folders, digit runs as #, long hex runs as <hex>, then *.ext."""
    parts = name.replace("/", "\\").lower().split("\\")
    head = [re.sub(r"[0-9a-f]{6,}", "<hex>", re.sub(r"-?\d+", "#", p)) for p in parts[:-1][:5]]
    return "\\".join(head) + "\\*" + os.path.splitext(parts[-1])[1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--world", default="NewAtlantis", help="list the files naming this world (default NewAtlantis)")
    ap.add_argument("--zip", default="")
    ap.add_argument("--samples", type=int, default=6)
    a = ap.parse_args(argv)
    if a.zip and os.path.abspath(a.zip).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--zip must be outside the repository")
    hits, counts, per_archive = [], {}, {}
    for p in sorted(glob.glob(os.path.join(a.sf_data, "*.ba2"))):
        try:
            arc = ba2.Ba2(p)
        except Exception as e:                       # noqa: BLE001 (reported; other archives go on)
            print(f"  {os.path.basename(p)}: {e}")
            continue
        for i, name in enumerate(arc.names):
            if is_grass(name):
                e = arc.entries[i]
                hits.append((os.path.basename(p), name, e.unpacked or e.packed or 0))
                k = pattern(name)
                counts[k] = counts.get(k, 0) + 1
                per_archive[os.path.basename(p)] = per_archive.get(os.path.basename(p), 0) + 1
    loose = []
    for root, _d, files in os.walk(a.sf_data):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), a.sf_data)
            if is_grass(rel):
                loose.append(rel)
    print(f"{len(hits):,} grass files in {len(per_archive)} archives, {len(loose)} loose:")
    for k, v in sorted(per_archive.items(), key=lambda kv: -kv[1]):
        print(f"  {v:8,}  {k}")
    print("by folder pattern:")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:40]:
        print(f"  {v:8,}  {k}")
    cell = [h for h in hits if "cellgrass" in h[1].lower() or h[1].lower().replace("/", "\\").startswith("grass\\")]
    print(f"cell grass / top-level grass\\ files: {len(cell)}")
    for arcn, name, size in cell[:25]:
        print(f"  {size:10,}  {name}  [{arcn}]")
    w = a.world.lower()
    mine = [h for h in hits if w in h[1].lower()]
    print(f"files naming {a.world}: {len(mine)}")
    for arcn, name, size in mine[:25]:
        print(f"  {size:10,}  {name}  [{arcn}]")
    for rel in loose[:10]:
        print(f"  loose: {rel}")
    if a.zip:
        os.makedirs(os.path.dirname(os.path.abspath(a.zip)) or ".", exist_ok=True)
        picks, seen_pat = [], set()
        for h in cell + mine + hits:                      # one sample per folder pattern first
            k = pattern(h[1])
            if k not in seen_pat and h[2] < 8 * 1024 * 1024:
                seen_pat.add(k)
                picks.append(h)
        picks = picks[:a.samples * 4]
        with zipfile.ZipFile(a.zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("grass_files.json", json.dumps({"counts": counts, "archives": per_archive, "loose": loose,
                                                       "files": [list(h) for h in hits]}, indent=0))
            for arcn, name, _s in picks:
                try:
                    data = ba2.Ba2(os.path.join(a.sf_data, arcn)).read(name)
                except Exception as e:               # noqa: BLE001
                    print(f"  could not read {name}: {e}")
                    continue
                z.writestr("samples/" + name.replace("\\", "/"), data)
        print(f"-> {a.zip} ({len(picks)} samples)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
