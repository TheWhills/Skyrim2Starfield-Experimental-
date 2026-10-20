"""Copy the vanilla Skyrim animation files the Starfield port still needs out of the game's archives, read-only.

Vanilla only: archives in load order (Skyrim - *.bsa, then DLC / Creation Club), loose files ignored unless
--loose (MO2 keeps mods out of the game folder, so the archives are vanilla). Copied (docs/armor/animation-port.md):
  * meshes\\animationdatasinglefile.txt and animationsetdatasinglefile.txt: vanilla clips keep their root motion
    there, not in the .hkx (rootmotion.parse_motion_data, hkx_to_af --motion)
  * the character behaviours (clip triggers and timings, as the 1hm_behavior dump used for the sword)
  * stance clips Starfield lacks: two-handed sword (2hm_*), two-handed axe / hammer (2hw_*), dual wield (dw*),
    shield (shd_*), and the one-handed set (1hm_*) for comparison

    python -I scripts\\armor\\skyrim_anim_extract.py --skyrim-data "<Skyrim Special Edition>\\Data" --out <folder>

Writes the files under <out> with their archive paths and manifest.json (path, size, archive). Game files: keep the
output outside the repository and do not share it publicly.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import bsa  # noqa: E402

WANTED = [
    r"^meshes\\animationdatasinglefile\.txt$",
    r"^meshes\\animationsetdatasinglefile\.txt$",
    r"^meshes\\actors\\character\\behaviors\\[^\\]+\.hkx$",
    r"^meshes\\actors\\character\\animations\\(2hm|2hw|dw|shd|1hm)[^\\]*\.hkx$",
]


def wanted(name: str, patterns=None) -> bool:
    n = bsa.norm(name)
    return any(re.search(p, n) for p in (patterns or WANTED))


def extract(data_dir: str, out: str, loose: bool = False, patterns=None):
    """{archive path: (size, source)} for every wanted file; later archives override earlier ones, as in game."""
    arcs = bsa.SkyrimArchives(data_dir, loose=loose)
    picked = {}
    for a in arcs.archives:                                   # load order: a later archive wins
        for i, n in enumerate(a.names):
            if wanted(n, patterns):
                picked[bsa.norm(n)] = (a, i)
    manifest = []
    for n in sorted(picked):
        a, i = picked[n]
        data, src = None, os.path.basename(a.path)
        if loose:
            data = arcs._loose(n)
            if data is not None:
                src = "loose"
        if data is None:
            data = a.read(i)
        dst = os.path.join(out, *n.split("\\"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        manifest.append({"path": n, "size": len(data), "source": src})
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--loose", action="store_true", help="let loose files in Data win over the archives")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(out, exist_ok=True)
    m = extract(a.skyrim_data, out, a.loose)
    kinds = {}
    for e in m:
        base = e["path"].split("\\")[-1]
        k = base.split("_")[0] if base.endswith(".hkx") else base
        kinds[k] = kinds.get(k, 0) + 1
    print(f"{len(m)} files, {sum(e['size'] for e in m) / 1e6:.1f} MB -> {out}: {kinds}")
    return 0 if m else 1


if __name__ == "__main__":
    sys.exit(main())
