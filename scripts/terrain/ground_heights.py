r"""Rebuild the staged Skyrim ground textures' blend height maps at full resolution (2026-11-25), without rebuilding the
terrain: skyrimground.height_from_diffuse now keeps the colour texture's resolution (vanilla terrain: colour, normal
and height all 2048). The 256 x 256 maps made Starfield's per-pixel blend of two ground textures follow a blurred,
quarter-resolution pattern: dark smeared holes with bright rims beside the roads (owner's close-up).

For every <staging>\Data\textures\skyrim\ground\<stem>_height.dds whose stem names a Skyrim LTEX (as
make_skyrim_overlay.py names them), the map is made again from that LTEX's Skyrim diffuse. The staged file is replaced
(removed first: staging files may be hard links into the build folder). Reinstall the exterior afterwards
(tools/owner/ground_heights.ps1 does it).

    python -I scripts\terrain\ground_heights.py --skyrim <Skyrim.esm> --staging C:\Modding\staging\skyrim_all --texconv <texconv.exe>
"""
import argparse
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from fo4sf import bsa, landtex, skyrimground, textures  # noqa: E402


def stem_of(edid: str) -> str:
    """make_skyrim_overlay.py's ground stem for an LTEX EditorID."""
    return re.sub(r"[^a-z0-9]+", "_", edid.lower()).strip("_")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm (its folder holds the archives)")
    ap.add_argument("--staging", required=True)
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--size", type=int, default=0, help="0 (default): the colour texture's resolution")
    a = ap.parse_args(argv)
    ground = os.path.join(a.staging, "Data", "textures", "skyrim", "ground")
    diffuse = {}
    for path in landtex.official_plugins(a.skyrim):       # later plugins win, but only with a texture set they hold
        with landtex.fo4land.Plugin(path) as p:           # (Update.esm's LTEX overrides name Skyrim.esm's TXSTs)
            for v in landtex.read_ltex(p).values():
                if v["edid"] and v["diffuse"]:
                    diffuse[stem_of(v["edid"])] = v["diffuse"]
    src = bsa.SkyrimArchives(os.path.dirname(os.path.abspath(a.skyrim)))
    done, missing = [], []
    for fn in sorted(os.listdir(ground)):
        if not fn.endswith("_height.dds") or fn.startswith("_"):
            continue
        stem = fn[:-len("_height.dds")]
        d = src.texture(skyrimground.texture_path(diffuse[stem])) if stem in diffuse else None
        if d is None:
            missing.append(stem)
            continue
        dst = os.path.join(ground, fn)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, fn)
            skyrimground.height_from_diffuse(d, a.texconv, out, size=a.size or None)
            data = open(out, "rb").read()
        os.remove(dst)
        with open(dst, "wb") as f:
            f.write(data)
        h = textures.read_dds_header(data)
        done.append(f"{stem} {h['width']}")
    print(f"{len(done)} height maps rebuilt ({', '.join(done[:6])}{' ...' if len(done) > 6 else ''})"
          + (f"; no Skyrim diffuse found for {missing}" if missing else ""))
    return 1 if missing and not done else 0


if __name__ == "__main__":
    sys.exit(main())
