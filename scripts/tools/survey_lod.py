"""How Starfield stores distant-object LOD (read-only survey of the game's archives), before we build any for the Skyrim
overlay. Lists every archived file whose path or extension looks like LOD (a 'lod' folder or name part, .lod / .bto /
.btt / .btr), counts them by folder pattern and extension, and lists those that name one worldspace (--world, default
NewAtlantis). With --zip it copies a few samples (that world's lodsettings and LOD files, a few generated LOD NIFs) and
the full list into a zip OUTSIDE the repository, to upload.

    python -I scripts\\tools\\survey_lod.py --sf-data "<Starfield>\\Data" --world NewAtlantis ^
        --zip C:\\Modding\\work\\lod_survey.zip

Public notes so far (not verified here): LODMeshes.ba2 holds ~19,500 NIFs under meshes\\lod\\generated\\ and the
archives hold ~860 lodsettings\\*.lod files (ByroRedux issue 4933).
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

LOD_RE = re.compile(r"(^|[\\/_.])lod|\.(lod|bto|btt|btr)$", re.I)


def pattern(name: str) -> str:
    """A folder pattern: path parts with digits / hex runs and world-like names generalised."""
    parts = name.replace("/", "\\").lower().split("\\")
    head = parts[:-1][:4]
    head = [re.sub(r"[0-9a-f]{6,}", "<hex>", re.sub(r"-?\d+", "#", p)) for p in head]
    ext = os.path.splitext(parts[-1])[1]
    return "\\".join(head) + "\\*" + ext


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--world", default="NewAtlantis")
    ap.add_argument("--zip", default="")
    ap.add_argument("--samples", type=int, default=4)
    a = ap.parse_args(argv)
    if a.zip and os.path.abspath(a.zip).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--zip must be outside the repository")
    hits, counts, per_archive = [], {}, {}
    for p in sorted(glob.glob(os.path.join(a.sf_data, "*.ba2"))):
        try:
            arc = ba2.Ba2(p)
        except Exception as e:                       # noqa: BLE001
            print(f"  {os.path.basename(p)}: {e}")
            continue
        n = 0
        for i, name in enumerate(arc.names):
            if LOD_RE.search(name):
                e = arc.entries[i]
                hits.append((os.path.basename(p), name, e.unpacked or e.packed))
                k = pattern(name)
                counts[k] = counts.get(k, 0) + 1
                n += 1
        if n:
            per_archive[os.path.basename(p)] = n
    print(f"{len(hits):,} LOD-looking files in {len(per_archive)} archives:")
    for k, v in sorted(per_archive.items(), key=lambda kv: -kv[1]):
        print(f"  {v:8,}  {k}")
    print("by folder pattern:")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:40]:
        print(f"  {v:8,}  {k}")
    w = a.world.lower()
    mine = [h for h in hits if w in h[1].lower()]
    print(f"files naming {a.world}: {len(mine)}")
    for arcn, name, size in mine[:40]:
        print(f"  {size:10,}  {name}  [{arcn}]")
    if a.zip:
        os.makedirs(os.path.dirname(os.path.abspath(a.zip)) or ".", exist_ok=True)
        picks = mine[:a.samples * 4]
        gen = [h for h in hits if "\\generated\\" in h[1].lower().replace("/", "\\")][:a.samples]
        settings = [h for h in hits if h[1].lower().endswith(".lod")][:a.samples]
        with zipfile.ZipFile(a.zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("lod_files.json", json.dumps({"counts": counts, "archives": per_archive,
                                                     "files": [list(h) for h in hits]}, indent=0))
            for arcn, name, _s in dict.fromkeys(picks + gen + settings):
                try:
                    data = ba2.Ba2(os.path.join(a.sf_data, arcn)).read(name)
                except Exception as e:               # noqa: BLE001
                    print(f"  could not read {name}: {e}")
                    continue
                z.writestr("samples/" + name.replace("\\", "/"), data)
        print(f"-> {a.zip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
