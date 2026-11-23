"""Which files inside Starfield's archives match a pattern, and which archive holds them (read-only), 2026-11-23.

Native grass: every model inside the game's archives grows, none of ours (plugin archive, loose, MO2, nor listed in
StarfieldCustom.ini sResourceArchiveList). Supported hypothesis: the grass system needs something else that the game
ships per grass model (e.g. in Starfield - DensityMaps.ba2: Starfield.exe names a BSProcGen DensityMapDB) and our
models lack. This lists the files whose path matches --grep (case-insensitive regex) in every Data\\*.ba2, counts per
archive and folder, and with --zip copies up to --samples of them (outside the repo) for a closer look.

    python -I scripts\\tools\\ba2_find.py --sf-data "<Starfield>\\Data" --grep "hellebore|mossmounds" ^
        --zip C:\\Modding\\work\\grass_find.zip
    python -I scripts\\tools\\ba2_find.py --sf-data ... --archive "Starfield - DensityMaps.ba2" --grep .   (one archive)
"""
import argparse
import glob
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2  # noqa: E402


def find(sf_data, rx, archive=""):
    """[(archive name, path, size)] of the archived files whose path matches rx."""
    out = []
    pattern = os.path.join(sf_data, archive) if archive else os.path.join(sf_data, "*.ba2")
    for p in sorted(glob.glob(pattern)):
        try:
            arc = ba2.Ba2(p)
        except Exception as e:                           # noqa: BLE001 (reported, the others go on)
            print(f"  {os.path.basename(p)}: {e}")
            continue
        for i, name in enumerate(arc.names):
            if rx.search(name):
                e = arc.entries[i]
                out.append((os.path.basename(p), name, e.unpacked or e.packed or 0))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--grep", required=True)
    ap.add_argument("--archive", default="", help="one archive file name (default: every *.ba2)")
    ap.add_argument("--max", type=int, default=60, help="paths printed (default 60)")
    ap.add_argument("--zip", default="")
    ap.add_argument("--samples", type=int, default=12)
    a = ap.parse_args(argv)
    if a.zip and os.path.abspath(a.zip).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--zip must be outside the repository")
    hits = find(a.sf_data, re.compile(a.grep, re.I), a.archive)
    per_arc, per_dir = {}, {}
    for arcn, name, _s in hits:
        per_arc[arcn] = per_arc.get(arcn, 0) + 1
        d = os.path.dirname(name.replace("/", "\\")).lower()
        per_dir[d] = per_dir.get(d, 0) + 1
    print(f"{len(hits):,} files match /{a.grep}/")
    for k, v in sorted(per_arc.items(), key=lambda kv: -kv[1]):
        print(f"  {v:8,}  {k}")
    print("by folder:")
    for k, v in sorted(per_dir.items(), key=lambda kv: -kv[1])[:25]:
        print(f"  {v:8,}  {k}")
    for arcn, name, size in hits[:a.max]:
        print(f"  {size:10,}  {name}  [{arcn}]")
    if a.zip:
        with zipfile.ZipFile(a.zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("files.txt", "\n".join(f"{arcn}\t{name}\t{size}" for arcn, name, size in hits))
            for arcn, name, size in hits[:a.samples]:
                if size > 16 * 1024 * 1024:
                    continue
                try:
                    z.writestr(name.replace("\\", "/"), ba2.Ba2(os.path.join(a.sf_data, arcn)).read(name))
                except Exception as e:                   # noqa: BLE001
                    print(f"  could not read {name}: {e}")
        print(f"-> {a.zip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
