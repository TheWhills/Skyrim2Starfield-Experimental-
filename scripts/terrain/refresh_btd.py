"""New ground-texture layers in an already staged exterior, its heights untouched (2026-11-21, owner: "spots in the
terrain that are supposed to fade or have a snow texture or blend ... got off like squares into each other").

    python -I scripts\\terrain\\refresh_btd.py rebuild --staging C:\\Modding\\staging\\skyrim_all --fresh C:\\Modding\\staging\\skyrim_all_blend
    python -I scripts\\terrain\\refresh_btd.py splice  --staging C:\\Modding\\staging\\skyrim_all --fresh C:\\Modding\\staging\\skyrim_all_blend

rebuild: runs the staging's own build (its build_command.txt) again into --fresh, with --ltex-blend / --ltex-warp
(default noise / 3.5: landtex "noise") added last so they win. Nothing in --staging is written.
splice: every .btd of the staging takes the texture part (LTEX table, quadrant map, sample weights) of the fresh BTD at
the same path, and keeps its own heights, height range and everything else (plugins, FormIDs, objects, grass, LOD,
water, the planet). A BTD whose fresh twin has another size or LTEX table is left alone and reported. Then reinstall
the staging (deploy_skyrim_exterior.py uninstall, install; tools\\owner\\terrain_blend.ps1 does all of it).
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

from fo4sf import btd  # noqa: E402


def build_args(staging, fresh, blend="noise", warp=3.5):
    """The staging's make_skyrim_overlay.py build arguments (from "build" on), with --out fresh and the blend options
    appended (argparse: the last one wins)."""
    from make_skyrim_overlay import split_cmdline
    path = os.path.join(staging, "build_command.txt")
    if not os.path.isfile(path):
        sys.exit(f"no {path}: not a make_skyrim_overlay.py build folder")
    with open(path, encoding="utf-8") as fh:
        args = split_cmdline(fh.read().strip())
    k = next((i for i, x in enumerate(args) if x == "build"), None)
    if k is None:
        sys.exit(f"{path} is not a build command")
    return args[k:] + ["--out", fresh, "--ltex-blend", blend, "--ltex-warp", str(warp)]


def btd_files(root):
    """{path relative to root\\Data (lower case, "\\\\"): absolute path} of every .btd under root\\Data."""
    out = {}
    data = os.path.join(root, "Data")
    for dirpath, _dirs, files in os.walk(data):
        for f in files:
            if f.lower().endswith(".btd"):
                p = os.path.join(dirpath, f)
                out[os.path.relpath(p, data).replace("/", "\\").lower()] = p
    return out


def splice_one(old: bytes, new: bytes):
    """(bytes, None) with old's heights and new's textures, or (None, why) when they do not fit together."""
    a, b = btd.read(old), btd.read(new)
    if a.heights_raw.shape != b.heights_raw.shape:
        return None, f"size {a.heights_raw.shape} vs fresh {b.heights_raw.shape}"
    if list(a.ltex) != list(b.ltex):
        return None, f"LTEX table differs ({len(a.ltex)} vs fresh {len(b.ltex)} entries)"
    out = btd.Btd(a.version, a.hmin, a.hmax, list(a.ltex), a.heights_raw, b.weights, b.quad_map)
    return btd.write(out), None


def cmd_splice(a):
    old, new = btd_files(a.staging), btd_files(a.fresh)
    if not old:
        sys.exit(f"no .btd under {a.staging}\\Data")
    done, kept, missing = 0, [], []
    for rel, p in sorted(old.items()):
        q = new.get(rel)
        if q is None:
            missing.append(rel)
            continue
        with open(p, "rb") as fh:
            ob = fh.read()
        with open(q, "rb") as fh:
            nb = fh.read()
        data, why = splice_one(ob, nb)
        if data is None:
            kept.append(f"{rel}: {why}")
            continue
        before = btd.read(ob)
        after = btd.read(data)
        assert np.array_equal(before.heights_raw, after.heights_raw)          # heights exactly as installed
        if not a.dry_run:
            with open(p, "wb") as fh:
                fh.write(data)
        done += 1
    print(f"{'would splice' if a.dry_run else 'spliced'} {done} of {len(old)} BTDs (heights kept, textures from "
          f"{a.fresh}); {len(missing)} with no fresh twin, {len(kept)} left alone")
    for m in missing[:10]:
        print(f"  no fresh twin: {m}")
    for k in kept[:10]:
        print(f"  left alone: {k}")
    return 0 if done else 1


def cmd_rebuild(a):
    if os.path.abspath(a.fresh).lower() == os.path.abspath(a.staging).lower():
        sys.exit("--fresh must be another folder than --staging")
    args = build_args(a.staging, a.fresh, a.blend, a.warp)
    cmd = [sys.executable, "-I", os.path.join(HERE, "make_skyrim_overlay.py")] + args
    print("running:", subprocess.list2cmdline(cmd))
    if a.dry_run:
        return 0
    return subprocess.call(cmd)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("rebuild", "splice"))
    ap.add_argument("--staging", required=True, help="the installed exterior's staging (C:\\Modding\\staging\\skyrim_all)")
    ap.add_argument("--fresh", required=True, help="where the fresh build goes / is (another folder)")
    ap.add_argument("--blend", choices=("solid", "dither", "noise"), default="noise", help="rebuild: --ltex-blend")
    ap.add_argument("--warp", type=float, default=3.5, help="rebuild: --ltex-warp (m)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    return cmd_rebuild(a) if a.cmd == "rebuild" else cmd_splice(a)


if __name__ == "__main__":
    sys.exit(main())
