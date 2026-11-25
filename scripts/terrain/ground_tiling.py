r"""Set the staged Skyrim ground materials' texture repeat (TilingDistance) without rebuilding the terrain (2026-11-25).

Skyrim repeats a ground texture every 2048 / 12 units = 2.44 m (skyrimground.SKYRIM_TILING_M, measured on Skyrim's
ground-matched meshes); the staged terrain used 4.88 m, so every ground texture drew at twice Skyrim's size. This
rewrites TilingDistance in every <staging>\Data\materials\skyrim\ground\*.mat (MaxDisplacement stays 0). The staged file
is replaced (removed first: staging files may be hard links into the build folder). Reinstall afterwards
(tools/owner/ground_heights.ps1 runs it).

    python -I scripts\terrain\ground_tiling.py --staging C:\Modding\staging\skyrim_all [--tiling 2.44]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import convert_material as cm, skyrimground  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", required=True)
    ap.add_argument("--tiling", type=float, default=round(skyrimground.SKYRIM_TILING_M, 2))
    a = ap.parse_args(argv)
    folder = os.path.join(a.staging, "Data", "materials", "skyrim", "ground")
    n = same = 0
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith(".mat"):
            continue
        p = os.path.join(folder, fn)
        with open(p, encoding="utf-8-sig") as f:
            text = f.read()
        mat = json.loads(text)
        if skyrimground.terrain_settings(mat, a.tiling) == 0:
            continue
        new = cm.dump_mat(mat)
        if new == text.replace("\r\n", "\n"):
            same += 1
            continue
        os.remove(p)
        with open(p, "w", encoding="utf-8", newline="\n") as f:      # as make_skyrim_overlay writes it
            f.write(new)
        n += 1
    print(f"{n} ground materials set to {a.tiling:g} m per repeat ({same} already)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
